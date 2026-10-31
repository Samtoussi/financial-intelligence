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


def evaluate_financials(report, extraction, ground_truth, *, payload, metadata):
    """Independent M006 financial checks plus source-bound assembly integrity.

    No AI notes are expected or approved. The oracle is used here only, never
    passed to production assembly. Existing MSFT/CAT evaluation is unchanged.
    """
    from src.ai.report_assembly import assemble_financials
    from src.evaluation.jpm_ground_truth import validate_dataset
    oracle_check = validate_dataset(ground_truth)
    failures = []
    canonical = None
    try:
        canonical = assemble_financials(extraction, payload, metadata)
    except (ValueError, KeyError, TypeError) as exc:
        failures.append('Source/extraction validation: ' + str(exc))
    if not isinstance(report, dict):
        report = {}
    canonical_match = canonical is not None and report == canonical
    if not canonical_match:
        failures.append('Report differs from source-bound deterministic assembly (including scopes, units, references or unsupported claims)')
    metrics = report.get('metrics', [])
    if not isinstance(metrics, list): metrics = []
    actual = {m.get('id'): m for m in metrics if isinstance(m, dict)}
    source_metrics = {m['id']: m for m in canonical['metrics']} if canonical else {}
    source_pairs = sum(m == source_metrics.get(mid) for mid, m in actual.items() if mid in source_metrics)
    values, yoy, stocks, period_units = 0, 0, 0, 0
    for o in ground_truth['metrics']:
        m = actual.get(o['id'], {})
        for p in ('current', 'prior'):
            if isinstance(m.get(p), str) and m[p] == o[p]['value']:
                values += 1
        expected_periods = {p: {k: v for k, v in o[p]['period'].items() if k != 'fiscal_period'}
                            for p in ('current', 'prior')}
        if (m.get('periods') == expected_periods and m.get('unit') == o['unit']
                and m.get('kind') == o['kind'] and m.get('comparison') == o['comparison']
                and m.get('source_label') == o['label'] and m.get('gaap_status') == o['gaap_status']):
            period_units += 1
        if m.get('change_percent') == oracle_check['changes'][o['id']]['percent']:
            if o['kind'] == 'flow': yoy += 1
            else: stocks += 1
    if (values, yoy, stocks, period_units) != (16, 6, 2, 8) or len(metrics) != 8 or len(actual) != 8:
        failures.append('Independent metric/period/unit/change comparison failed')

    # Build independent expected accounting operands from the manually
    # transcribed oracle, not from production reconciliation output.
    om = {m['id']: m for m in ground_truth['metrics']}
    support = ground_truth['supporting_values']
    expected = {}
    for p in ('current', 'prior'):
        expected['reported_revenue:'+p] = ([om[mid][p]['value'] for mid in ('net_interest_income', 'noninterest_revenue')], [1, 1], om['total_net_revenue'][p]['value'])
        for b in ground_truth['reported_to_managed']:
            v = b[p]
            expected['managed:'+b['metric_id']+':'+p] = ([v['reported'], v['fte_adjustment']], [1, 1], v['managed'])
        expected['credit_net_addition:'+p] = ([om['provision_for_credit_losses'][p]['value'], support['net_charge_offs'][p]], [1, -1], support['net_addition_to_allowance'][p])
        expected['net_loans:'+p] = ([om['total_loans'][p]['value'], str(-Decimal(support['loan_loss_allowance_signed'][p]))], [1, -1], support['net_loans'][p])
    acl = support['allowance_components_current']
    expected['principal_allowance:current'] = ([acl[k] for k in ('loan_losses', 'lending_related_commitments', 'investment_securities')], [1, 1, 1], acl['principal_table_total'])
    expected['firmwide_allowance:current'] = ([acl['principal_table_total'], acl['cib_accounts_receivable']], [1, 1], acl['firmwide_total'])
    rows = report.get('reconciliation', [])
    if not isinstance(rows, list): rows = []
    ar = {r.get('id'): r for r in rows if isinstance(r, dict)}
    reconciled = 0
    for rid, (operands, coefficients, result) in expected.items():
        r = ar.get(rid, {})
        p = rid.rsplit(':', 1)[1]
        period_metric = om['total_loans'] if rid.startswith(('net_loans:', 'principal_allowance:', 'firmwide_allowance:')) else om['total_net_revenue']
        period = {k: v for k, v in period_metric[p]['period'].items() if k != 'fiscal_period'}
        try:
            good = ([t['value'] for t in r['operands']] == operands
                    and [t['coefficient'] for t in r['operands']] == coefficients
                    and r['result'] == result and r['unit'] == 'USD millions' and r['period'] == period
                    and sum(Decimal(t['value'])*Decimal(t['coefficient']) for t in r['operands']) == Decimal(result))
        except (KeyError, TypeError, InvalidOperation):
            good = False
        reconciled += bool(good)
    if reconciled != 14 or len(rows) != 14 or len(ar) != 14:
        failures.append('Independent accounting reconciliation failed')
    stock = report.get('allowance_stock', {})
    if not isinstance(stock, dict): stock = {}
    if any(stock.get(p) != support['firmwide_allowance'][p] for p in ('current', 'prior')):
        failures.append('Independent firmwide allowance stock comparison failed')
    return {'evaluation_version': 'm006-financial-eval-v1',
        'financial_values': {'passed': values, 'total': 16},
        'yoy_changes': {'passed': yoy, 'total': 6},
        'since_year_end_changes': {'passed': stocks, 'total': 2},
        'period_unit_scope_checks': {'passed': period_units, 'total': 8},
        'table_evidence_support': {'passed': source_pairs, 'total': 8},
        'reconciliation': {'passed': reconciled, 'total': 14},
        'source_integrity_pass': canonical is not None, 'source_bound_report_pass': canonical_match,
        'automatic_pass': not failures, 'overall_pass': False, 'failures': failures,
        'manual_reviews': [{'id': rid, 'status': 'pending_manual_review'}
                           for rid in ('oracle', 'semantic', 'presentation')],
        'limitations': 'Financial foundation only. No AI interpretation, complete allowance rollforward or human approval.'}


def evaluate_banking_response(raw, evidence, extraction, ground_truth, *, payload, metadata):
    """Validate saved notes before AI-report assembly; oracle never enters context."""
    from src.ai.report_assembly import prepare, assemble_financials
    from src.analytics.jpm_narrative import validate_notes
    foundation = assemble_financials(extraction, payload, metadata)
    prepared = prepare(evidence, 'jpm_2026_q2')
    financial = evaluate_financials(foundation, extraction, ground_truth, payload=payload, metadata=metadata)
    narrative = validate_notes(raw, prepared)
    source_ok = evidence == extraction['evidence'] and prepared['financial_foundation'] == foundation
    return {'evaluation_version': 'm006-ai-eval-v1', 'financial': financial, 'narrative': narrative,
        'source_context_pass': source_ok,
        'automatic_pass': financial['automatic_pass'] and narrative['automatic_pass'] and source_ok,
        'overall_pass': False,
        'manual_reviews': [{'id': n, 'status': 'pending_manual_review'} for n in (
            'reported_vs_managed', 'credit_loss_measures', 'significant_earnings_items')],
        'limitations': 'Deterministic safeguards are bounded, not complete semantic entailment. Human oracle, semantic and presentation approval remain required.'}


def evaluate_banking_report(report, raw, evidence, extraction, ground_truth, *, payload, metadata):
    from src.ai.report_assembly import assemble
    result = evaluate_banking_response(raw, evidence, extraction, ground_truth, payload=payload, metadata=metadata)
    match = result['automatic_pass'] and assemble(raw, evidence, 'jpm_2026_q2') == report
    return {**result, 'assembled_response_match': bool(match), 'automatic_pass': bool(match)}


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
