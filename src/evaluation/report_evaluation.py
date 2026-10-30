"""M002 numeric checks, citation integrity, bounded table support and manual review.

Quoted text membership is not semantic entailment. Numerical support is checked
against the labeled source table rows; interpretation remains explicitly manual.
"""
import hashlib
import re
from decimal import Decimal, InvalidOperation

from src.analytics.report_evidence import REPORT, METRICS, NOTE_IDS
from src.evaluation.ground_truth import validate, yoy
from src.transformation.parse_filings import normalize

RUBRIC = {
    "gaap_vs_non_gaap": "Check reported net income/EPS against the income statement. "
        "Confirm adjusted measures are explicitly non-GAAP, and any stated adjustment matches the cited disclosure.",
    "recast_segment_comparability": "Check Note 1: prior segment figures must use the recast current structure. "
        "Reject claims that compare unrecast segment figures or infer an accounting-standard change.",
    "azure_growth_vs_cloud_margin": "Verify that Azure revenue growth and Microsoft Cloud gross margin "
        "percentage refer to different measures and scopes. Check level versus change and any claimed driver.",
}


def decimal_value(value):
    # Accept correctly grouped display thousands, never arbitrary comma removal.
    if not isinstance(value, str) or not re.fullmatch(r"-?(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d+)?", value):
        return None
    try:
        number = Decimal(value.replace(",", ""))
        return number if number.is_finite() else None
    except InvalidOperation:
        return None


def _source_row(evidence, mid):
    text = evidence["text"]
    label = METRICS[mid][0]
    if mid.endswith("_revenue"):
        if evidence.get("label") != "segment_table":
            return None
        start = text.find(label)
        if start < 0:
            return None
        lines = text[start:].splitlines()
        row = next((line for line in lines[1:] if re.match(r"\s*\|?\s*Revenue\s*\|", line)), "")
    else:
        if evidence.get("label") != "income_statement":
            return None
        # EPS must precede the weighted-average share table, whose row is also 'Diluted'.
        text = text.split("Weighted average shares outstanding")[0]
        row = next((line for line in text.splitlines()
                    if re.match(r"\s*\|?\s*" + re.escape(label) + r"\s*\|", line)), "")
    amounts = re.findall(r"(?<![\w.])\d[\d,]*(?:\.\d+)?(?![\w.])", row)
    if len(amounts) != 2:
        return None
    return row, [Decimal(n.replace(",", "")) for n in amounts]


def evaluate_report(report, evidence, ground_truth, *, source_sha256, reviews=None):
    """Evaluate untrusted model output; pending manual review never passes."""
    validate(ground_truth)
    failures = []
    integrity_errors = []
    quote_errors = []
    metadata_errors = []
    support_errors = []
    if not isinstance(report, dict):
        report = {}
        failures.append("Report is not an object")
    index = {}
    for e in evidence:
        if not isinstance(e, dict):
            integrity_errors.append("Malformed evidence")
            continue
        eid = e.get("evidence_id")
        text = e.get("text")
        if not isinstance(eid, str) or eid in index:
            integrity_errors.append("Missing or duplicate evidence ID")
            continue
        if (e.get("accession") != REPORT["accession"] or e.get("source_url") != REPORT["source_url"]
                or e.get("ticker") != "MSFT" or e.get("form") != "10-Q"
                or not re.fullmatch(r"[0-9a-f]{64}", source_sha256 or "")
                or e.get("source_sha256") != source_sha256
                or not isinstance(text, str) or not text.strip()
                or e.get("text_sha256") != hashlib.sha256((text or "").encode()).hexdigest()):
            integrity_errors.append(f"Invalid evidence source/hash: {eid}")
            continue
        index[eid] = e

    def citations(item, name):
        cited = item.get("citations")
        good = []
        if not isinstance(cited, list) or not cited:
            integrity_errors.append(f"Missing citations: {name}")
            return good
        for cite in cited:
            if not isinstance(cite, dict) or cite.get("evidence_id") not in index:
                integrity_errors.append(f"Unknown/wrong-filing evidence reference: {name}")
                continue
            e = index[cite["evidence_id"]]
            quote = cite.get("quote")
            if not isinstance(quote, str) or len(quote.strip()) < 12 or normalize(quote) not in normalize(e["text"]):
                quote_errors.append(f"Quotation absent from cited evidence: {name}")
                continue
            good.append((e, quote))
        return good

    meta = report.get("report")
    meta = meta if isinstance(meta, dict) else {}
    for key in ("ticker", "form", "accession", "fiscal_period", "period_start", "period_end", "prior_start", "prior_end"):
        if meta.get(key) != REPORT[key]:
            metadata_errors.append(f"Report mismatch: {key}")
    actual_metrics = report.get("metrics", [])
    actual_metrics = actual_metrics if isinstance(actual_metrics, list) else []
    by_id = {}
    for m in actual_metrics:
        if not isinstance(m, dict) or m.get("id") not in METRICS or m.get("id") in by_id:
            failures.append("Unexpected, malformed or duplicate metric")
        else:
            by_id[m["id"]] = m
    value_passed = yoy_passed = support_passed = 0
    details = []
    for expected in ground_truth["metrics"]:
        mid = expected["id"]
        m = by_id.get(mid, {})
        values_ok = {}
        for period in ("current", "prior"):
            ok = decimal_value(m.get(period)) == Decimal(expected[period]["value"])
            values_ok[period] = ok
            value_passed += int(ok)
            if not ok:
                failures.append(f"Value mismatch: {mid}.{period}")
        expected_yoy = yoy(expected["current"]["value"], expected["prior"]["value"])
        growth_ok = decimal_value(m.get("yoy_percent")) == Decimal(expected_yoy)
        yoy_passed += int(growth_ok)
        if not growth_ok:
            failures.append(f"YoY mismatch: {mid}")
        for field in ("unit", "gaap_status"):
            if m.get(field) != expected[field]:
                metadata_errors.append(f"Metric mismatch: {mid}.{field}")
        supported = False
        for e, quote in citations(m, mid):
            source_row = _source_row(e, mid)
            if source_row is None:
                continue
            row, amounts = source_row
            context = all(term in e["text"] for term in ("2026", "2025", "September 30", "millions"))
            if mid == "diluted_eps":
                context = context and "per share" in e["text"]
            if (context and normalize(row).strip("| ") in normalize(quote)
                    and (not mid.endswith("_revenue") or METRICS[mid][0] in quote)
                    and amounts == [decimal_value(m.get("current")), decimal_value(m.get("prior"))]):
                supported = True
        support_passed += int(supported)
        if not supported:
            support_errors.append(f"No labeled source row supports pair: {mid}")
        details.append({"id": mid, "values": values_ok, "yoy_pass": growth_ok,
                        "expected_yoy_percent": expected_yoy, "table_support_pass": supported})
    notes = report.get("notes", [])
    notes = notes if isinstance(notes, list) else []
    notes_by_id = {}
    for note in notes:
        if not isinstance(note, dict) or note.get("id") not in NOTE_IDS or note.get("id") in notes_by_id:
            failures.append("Unexpected, malformed or duplicate interpretation note")
        else:
            notes_by_id[note["id"]] = note
    manual = []
    reviews = reviews or {}
    for nid in NOTE_IDS:
        note = notes_by_id.get(nid, {})
        cited = citations(note, nid)
        if not isinstance(note.get("text"), str) or not note["text"].strip():
            failures.append(f"Missing note text: {nid}")
        review = reviews.get(nid, {})
        status = review.get("status", "pending_manual_review")
        if status not in {"pass", "fail", "pending_manual_review"}:
            status = "pending_manual_review"
        if status in {"pass", "fail"} and not (
            isinstance(review.get("reviewer"), str) and review["reviewer"].strip()
            and isinstance(review.get("rationale"), str) and review["rationale"].strip()
            and review.get("evidence_ids") and set(review["evidence_ids"]).issubset({e["evidence_id"] for e, _ in cited})
        ):
            status = "pending_manual_review"
        manual.append({"id": nid, "status": status, "rubric": RUBRIC[nid],
                       "reviewer": review.get("reviewer"), "rationale": review.get("rationale"),
                       "evidence_ids": [e["evidence_id"] for e, _ in cited],
                       "instruction": "Compare every assertion with the quoted disclosure; a matching quote alone is insufficient."})
    automatic_ok = not (failures or integrity_errors or quote_errors or metadata_errors or support_errors)
    return {
        "evaluation_version": "m002-eval-v2",
        "number_normalization": "Correctly grouped thousands separators are removed before exact Decimal comparison; no numeric tolerance is used.",
        "financial_values": {"passed": value_passed, "total": 12},
        "yoy_changes": {"passed": yoy_passed, "total": 6},
        "table_evidence_support": {"passed": support_passed, "total": 6},
        "metric_details": details, "metadata_pass": not metadata_errors,
        "citation_integrity_pass": not integrity_errors,
        "quote_membership_pass": not quote_errors,
        "automatic_pass": automatic_ok,
        "overall_pass": automatic_ok and all(r["status"] == "pass" for r in manual),
        "failures": failures, "metadata_errors": metadata_errors,
        "citation_errors": integrity_errors, "quote_errors": quote_errors,
        "support_errors": support_errors, "manual_reviews": manual,
        "limitations": "Table-row checks support the numeric pairs only. Quote membership and source hashes "
                      "do not establish semantic correctness of interpretation notes. Pending reviews are not passes.",
    }
