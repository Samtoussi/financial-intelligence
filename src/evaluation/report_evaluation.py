"""Quarterly report numeric checks, citation integrity, bounded table support and manual review.

Quoted text membership is not semantic entailment. Numerical support is checked
against the labeled source table rows; interpretation remains explicitly manual.
"""
import hashlib
import re
from decimal import Decimal, InvalidOperation

from src.analytics.report_profiles import DEFAULT_PROFILE, get_profile, table_context
from src.evaluation.ground_truth import yoy
from src.evaluation.report_ground_truth import validate_report_dataset
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


def valid_table_context(text, config):
    """Require the declared pair in table-header order, not merely elsewhere in a packet."""
    terms = table_context(config)
    if not all(term in text for term in terms):
        return False
    header = text.split("Revenue")[0].split("Total revenue")[0]
    years = re.findall(r"(?<!\d)(?:19|20)\d{2}(?!\d)", header)
    return years == list(terms[1:3])


def _source_row(evidence, mid, *, profile=DEFAULT_PROFILE):
    metrics = get_profile(profile)["metrics"]
    text = evidence["text"]
    label = metrics[mid][0]
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


def evaluate_report(report, evidence, ground_truth, *, source_sha256, reviews=None, profile=DEFAULT_PROFILE):
    """Evaluate untrusted model output; pending manual review never passes."""
    config = get_profile(profile)
    report_identity, metrics = config["report"], config["metrics"]
    note_ids = tuple(config["topics"])
    validate_report_dataset(ground_truth, profile)
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
        if (e.get("accession") != report_identity["accession"] or e.get("source_url") != report_identity["source_url"]
                or e.get("ticker") != report_identity['ticker'] or e.get("form") != report_identity['form']
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
        if meta.get(key) != report_identity[key]:
            metadata_errors.append(f"Report mismatch: {key}")
    actual_metrics = report.get("metrics", [])
    actual_metrics = actual_metrics if isinstance(actual_metrics, list) else []
    by_id = {}
    for m in actual_metrics:
        if not isinstance(m, dict) or m.get("id") not in metrics or m.get("id") in by_id:
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
        valid_citations = citations(m, mid)
        if config.get('bindings'):
            from src.analytics.report_tables import selected_pair
            binding = config['bindings'][mid]
            for e, _ in valid_citations:
                if e['label'] != binding['window']:
                    continue
                try:
                    pair, ranges, _ = selected_pair(e['text'], metrics[mid][0], binding, config)
                    supported = (pair == [decimal_value(m.get(p)) for p in ('current', 'prior')]
                        and all(any(cited['evidence_id'] == e['evidence_id'] and e['text'][a:b] in q
                                    for cited, q in valid_citations) for a, b in ranges))
                except ValueError:
                    supported = False
                if supported:
                    break
        for e, quote in ([] if config.get('bindings') else valid_citations):
            source_row = _source_row(e, mid, profile=profile)
            if source_row is None:
                continue
            row, amounts = source_row
            context = valid_table_context(e["text"], config)
            if mid == "diluted_eps":
                context = context and "per share" in e["text"]
            if (context and normalize(row).strip("| ") in normalize(quote)
                    and (not mid.endswith("_revenue") or metrics[mid][0] in quote)
                    and amounts == [decimal_value(m.get("current")), decimal_value(m.get("prior"))]):
                supported = True
        support_passed += int(supported)
        if not supported:
            support_errors.append(f"No labeled source row supports pair: {mid}")
        details.append({"id": mid, "values": values_ok, "yoy_pass": growth_ok,
                        "expected_yoy_percent": expected_yoy, "table_support_pass": supported})
    reconciliation_result = None
    if config.get('reconciliation_rows'):
        from src.analytics.report_tables import reconciliation_values, check_reconciliation
        rows = report.get('reconciliation', [])
        expected_rows = [{k: r[k] for k in ('label', 'external', 'intersegment', 'total')} for r in ground_truth['reconciliation']]
        try:
            actual_rows = [{k: r[k] for k in ('label', 'external', 'intersegment', 'total')} for r in rows]
            if actual_rows != expected_rows:
                raise ValueError('Oracle reconciliation mismatch')
            check_reconciliation(rows, [by_id['revenue'][p] for p in ('current', 'prior')])
            for r in rows:
                supported = False
                for e, q in citations(r, 'reconciliation:' + r['label']):
                    if e['label'] == 'segment_table' and q == e['text'] and reconciliation_values(e['text'], config) == expected_rows:
                        supported = True
                if not supported:
                    raise ValueError('Unsupported reconciliation row')
            reconciliation_result = {'passed': 48, 'total': 48, 'identities_pass': True}
        except (ValueError, KeyError, TypeError):
            support_errors.append('Reconciliation oracle/source/identity mismatch')
            reconciliation_result = {'passed': 0, 'total': 48, 'identities_pass': False}
    notes = report.get("notes", [])
    notes = notes if isinstance(notes, list) else []
    notes_by_id = {}
    for note in notes:
        if not isinstance(note, dict) or note.get("id") not in note_ids or note.get("id") in notes_by_id:
            failures.append("Unexpected, malformed or duplicate interpretation note")
        else:
            notes_by_id[note["id"]] = note
    manual = []
    monetary_checks = []
    reviews = reviews or {}
    for nid in note_ids:
        note = notes_by_id.get(nid, {})
        cited = citations(note, nid)
        if not isinstance(note.get("text"), str) or not note["text"].strip():
            failures.append(f"Missing note text: {nid}")
        elif config.get('contract') == 'm005-v1':
            from src.analytics.narrative_money import validate_monetary_narrative
            check = validate_monetary_narrative(note['text'], [quote for _, quote in cited])
            monetary_checks.append({'note_id': nid, **check})
            if not check['automatic_pass']:
                support_errors.append(f'Unsupported narrative monetary units: {nid}')
        review = reviews.get(nid, {})
        status = review.get("status", "pending_manual_review")
        if status not in {"pass", "fail", "pending_manual_review"}:
            status = "pending_manual_review"
        if status in {"pass", "fail"} and not (
            isinstance(review.get("reviewer"), str) and review["reviewer"].strip()
            and isinstance(review.get("rationale"), str) and review["rationale"].strip()
            and isinstance(review.get("evidence_ids"), list) and review["evidence_ids"]
            and all(isinstance(eid, str) for eid in review["evidence_ids"])
            and set(review["evidence_ids"]).issubset({e["evidence_id"] for e, _ in cited})
        ):
            status = "pending_manual_review"
        manual.append({"id": nid, "status": status, "rubric": config['topics'][nid] if config.get('contract') else RUBRIC.get(nid, config["topics"][nid]),
                       "reviewer": review.get("reviewer"), "rationale": review.get("rationale"),
                       "evidence_ids": [e["evidence_id"] for e, _ in cited],
                       "instruction": "Compare every assertion with the quoted disclosure; a matching quote alone is insufficient."})
    automatic_ok = not (failures or integrity_errors or quote_errors or metadata_errors or support_errors)
    result = {
        "evaluation_version": "m005-eval-v3" if config.get('contract') else "m003-eval-v1",
        "number_normalization": "Correctly grouped thousands separators are removed before exact Decimal comparison; no numeric tolerance is used.",
        "financial_values": {"passed": value_passed, "total": 2 * len(metrics)},
        "yoy_changes": {"passed": yoy_passed, "total": len(metrics)},
        "table_evidence_support": {"passed": support_passed, "total": len(metrics)},
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
    if reconciliation_result is not None:
        result['reconciliation'] = reconciliation_result
    if config.get('contract') == 'm005-v1':
        result['narrative_monetary_units'] = {'automatic_pass': all(c['automatic_pass'] for c in monetary_checks),
                                            'notes': monetary_checks}
    return result
