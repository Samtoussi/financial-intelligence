"""Presentation checks supplement, never replace, the independent M003 evaluator."""
import re
from decimal import Decimal, ROUND_HALF_UP
from fractions import Fraction

from src.analytics.investor_report import LABELS, SOURCE_LABELS, render_main, render_details
from src.analytics.report_profiles import segment_ids


def evaluate_banking_presentation(report, raw, extraction, view, main, detail, *, payload, metadata, evaluation):
    from src.analytics.investor_report import build_banking_presentation, render_banking_main, render_banking_details
    failures = []
    try:
        expected = build_banking_presentation(report, raw, extraction, payload, metadata)
        if view != expected: failures.append('Changed banking presentation/source references')
        if main != render_banking_main(report, expected): failures.append('Changed investor report')
        if detail != render_banking_details(report, expected): failures.append('Changed supporting detail')
    except (ValueError, KeyError, TypeError) as exc:
        failures.append('Invalid banking presentation: '+str(exc))
    if evaluation.get('evaluation_version') != 'm006-ai-eval-v1' or not evaluation.get('automatic_pass') or evaluation.get('overall_pass'):
        failures.append('Banking automatic gate must pass; human approval remains pending')
    return {'evaluation_version': 'm006-ai-presentation-v1', 'automatic_pass': not failures,
        'overall_pass': False, 'review_status': 'pending_manual_review', 'failures': failures}


def evaluate_financial_presentation(report, extraction, view, report_text, detail_text, *,
                                    payload, metadata, financial_evaluation):
    """M006 financial-only presentation checks, separate from AI approval."""
    from src.analytics.investor_report import (build_financial_presentation,
        render_financial_main, render_financial_details)
    failures = []
    expected = None
    try:
        expected = build_financial_presentation(report, extraction, payload, metadata)
    except (ValueError, KeyError, TypeError) as exc:
        failures.append('Source-bound presentation: '+str(exc))
    if expected is None or view != expected:
        failures.append('Financial view changed values, units, periods, scopes, claims or references')
    if expected is not None:
        if report_text != render_financial_main(expected): failures.append('Main financial presentation changed')
        if detail_text != render_financial_details(expected): failures.append('Financial supporting detail changed')
    gate = financial_evaluation
    if (not isinstance(gate, dict) or gate.get('evaluation_version') != 'm006-financial-eval-v1'
            or gate.get('automatic_pass') is not True or gate.get('overall_pass') is not False
            or gate.get('financial_values') != {'passed': 16, 'total': 16}
            or gate.get('yoy_changes') != {'passed': 6, 'total': 6}
            or gate.get('since_year_end_changes') != {'passed': 2, 'total': 2}
            or gate.get('period_unit_scope_checks') != {'passed': 8, 'total': 8}
            or gate.get('table_evidence_support') != {'passed': 8, 'total': 8}
            or gate.get('reconciliation') != {'passed': 14, 'total': 14}
            or gate.get('source_bound_report_pass') is not True or gate.get('source_integrity_pass') is not True
            or gate.get('failures') != []):
        failures.append('Independent financial gate is missing, failed or inconsistent')
    if isinstance(report_text, str):
        balance = report_text.partition('## Loans and deposits since year-end')[2].partition('## Reported versus managed')[0]
        if not balance or 'YoY' in balance or 'Change since year-end' not in balance:
            failures.append('Balance comparison labeling')
        if not all(s in balance for s in ('June 30, 2026', 'December 31, 2025', 'USD millions')):
            failures.append('Balance dates/units')
        if not all(s in report_text for s in ('USD per share', 'FTE adjustment', 'GAAP reported',
            'Human review pending', '## Significant earnings items', '## Source references')):
            failures.append('Missing banking context, units or review status')
    else:
        failures.append('Missing financial Markdown')
    return {'evaluation_version': 'm006-financial-presentation-eval-v1',
        'automatic_pass': not failures, 'overall_pass': False,
        'review_status': 'pending_manual_review', 'failures': failures,
        'limitations': 'Deterministic financial foundation only; no AI narrative or human approval.'}


def evaluate_presentation(bundle, view, report_text, detail_text):
    failures = []
    def check(condition, message):
        if not condition:
            failures.append(message)
    original = bundle['report']
    config = bundle['config']
    cat = config.get('contract') == 'm005-v1'
    expected = {m['id']: m for m in original['metrics']}
    actual = {m['id']: m for m in view['metrics']}
    check(set(actual) == set(expected) and len(actual) == len(view['metrics']), 'Metric completeness')
    check(view['report'] == original['report'], 'Report identity')
    check(view['notes'] == original['notes'], 'Narrative changed')
    check(view['takeaway_ids'] == ([config['presentation']['takeaway']] if cat else ['azure_growth_vs_cloud_margin']), 'Takeaway selection')
    check(view['m004_review_status'] == 'pending_manual_review', 'Unreviewed presentation approval')
    check(view['m003_overall_pass'] == bundle['evaluation']['overall_pass']
          and bundle['evaluation']['automatic_pass'] and view['m003_automatic_pass']
          and (cat or bundle['evaluation']['overall_pass']), 'M003 gate')
    for mid, m in actual.items():
        if mid not in expected:
            continue
        source = expected[mid]
        check(all(m.get(k) == source[k] for k in source), f'Exact value/basis changed: {mid}')
        check(m['label'] == config.get('presentation', {}).get('labels', LABELS).get(mid, config['metrics'][mid][0]), f'Label changed: {mid}')
        for period in ('current', 'prior'):
            amount = Decimal(source[period].replace(',', ''))
            display = m['display_' + period]
            if source['unit'] == 'USD millions':
                rounded = (amount / 1000).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)
                valid = display == f'${rounded:,.1f}B'
            else:
                valid = display == f'${amount:.2f}'
            check(valid, f'Display rounding: {mid}.{period}')
        growth = Decimal(source['yoy_percent'])
        check(m['display_yoy'] == f'{growth:+.1f}%', f'YoY formatting: {mid}')
    segments = [m for m in original['metrics'] if m['id'] in segment_ids(config)]
    ratios = {m['id']: Fraction(Decimal(m['current'].replace(',', ''))) /
              Fraction(Decimal(m['prior'].replace(',', ''))) for m in segments}
    maximum = max(ratios.values())
    winners = [mid for mid, ratio in ratios.items() if ratio == maximum] if maximum > 1 else []
    check(view['fastest_segment_ids'] == winners, 'False growth leader/tie claim')
    check(view['summary_claim_ids'] == ['revenue', 'operating_income'] + [m['id'] for m in segments],
          'Summary citation coverage')
    revenue_yoy = Decimal(expected['revenue']['yoy_percent'])
    op_yoy = Decimal(expected['operating_income']['yoy_percent'])
    def change_description(change):
        if change == 0:
            return 'was unchanged at the displayed precision'
        return f"{'increased' if change > 0 else 'declined'} {abs(change):.1f}%"
    revenue_display = (Decimal(expected['revenue']['current'].replace(',', '')) / 1000).quantize(
        Decimal('0.1'), rounding=ROUND_HALF_UP)
    direction = (f"{'up' if revenue_yoy > 0 else 'down'} {abs(revenue_yoy):.1f}%"
                 if revenue_yoy else 'unchanged at the displayed precision')
    summary = (f'Microsoft reported revenue of ${revenue_display:,.1f} billion, {direction} year over year, '
               f'while operating income {change_description(op_yoy)}.')
    if cat:
        summary = (f'Caterpillar reported sales and revenues of ${revenue_display:,.1f} billion, {direction} year over year, '
                   f'while operating profit {change_description(op_yoy)}.')
    if winners:
        labels = [bundle['config']['metrics'][mid][0] for mid in winners]
        names = (' and '.join(labels) if len(labels) < 3 else
                 ', '.join(labels[:-1]) + ', and ' + labels[-1])
        growth = abs(Decimal(expected[winners[0]]['yoy_percent']))
        growth_description = (f'revenue up {growth:.1f}%' if growth else
                              'revenue growth rounding to 0.0%')
        if len(winners) == 1:
            summary += f' {names} was the fastest-growing segment, with {growth_description}.'
        else:
            summary += (f' {names} shared the fastest segment revenue growth, '
                        f'each with {growth_description}.')
    else:
        summary += ' No configured segment recorded revenue growth.'
    check(view['summary'] == summary, 'Unsupported summary wording')
    check(view['comparison_claim_ids'] == ['operating_income', 'revenue'], 'Comparison citations')
    if op_yoy == revenue_yoy:
        if op_yoy == 0:
            comparison = 'Operating income and revenue were unchanged at the displayed precision.'
        else:
            verb = 'increased' if op_yoy > 0 else 'declined'
            comparison = f'Operating income and revenue both {verb} {abs(op_yoy):.1f}% after rounding.'
    elif min(op_yoy, revenue_yoy) > 0:
        relation = 'faster' if op_yoy > revenue_yoy else 'more slowly'
        comparison = f'Operating income grew {relation} than revenue ({op_yoy:.1f}% versus {revenue_yoy:.1f}%).'
    elif max(op_yoy, revenue_yoy) < 0:
        relation = 'less' if op_yoy > revenue_yoy else 'more'
        comparison = f'Operating income declined {relation} than revenue ({abs(op_yoy):.1f}% versus {abs(revenue_yoy):.1f}%).'
    else:
        comparison = (f'Operating income {change_description(op_yoy)}, '
                      f'while revenue {change_description(revenue_yoy)}.')
    if cat:
        comparison = comparison.replace('Operating income', 'Operating profit').replace('revenue', 'sales and revenues')
    check(view['earnings_comparison'] == comparison, 'Unsupported earnings comparison')
    evidence = {e['evidence_id']: e for e in bundle['evidence']}
    registry = {s['span_id']: s for s in bundle['registry']['spans']}
    reconciliation_claims = {'reconciliation:' + r['label'] for r in original.get('reconciliation', [])}
    check(set(view['claims']) == set(expected) | {n['id'] for n in original['notes']} | reconciliation_claims, 'Claim completeness')
    if cat:
        check(view.get('reconciliation') == original['reconciliation'], 'Reconciliation changed')
        check(view.get('headline_ids') == list(config['presentation']['labels']) and view.get('company') == 'Caterpillar'
              and view.get('contract') == 'm005-v1' and view.get('version') == 'm005-presentation-v1'
              and view.get('segment_ids') == segment_ids(config), 'Presentation contract changed')
    source_ids = [s['evidence_id'] for s in view['sources'].values()]
    check(set(source_ids) == set(evidence) and len(source_ids) == len(evidence), 'Source map completeness')
    for source in view['sources'].values():
        e = evidence.get(source['evidence_id'], {})
        check(source['url'] == e.get('source_url') and source['label'] == SOURCE_LABELS.get(e.get('label')),
              'Source identity or readable label')
    originals = {i['id']: i for i in original['metrics'] + original['notes']}
    originals.update({'reconciliation:' + r['label']: r for r in original.get('reconciliation', [])})
    for mid, claim in view['claims'].items():
        check([{k: c[k] for k in ('evidence_id', 'quote')} for c in claim['citations']] ==
              originals.get(mid, {}).get('citations'), f'Citation mapping changed: {mid}')
        for cite in claim['citations']:
            e = evidence.get(cite['evidence_id'], {})
            check(cite['quote'] in e.get('text', ''), 'Non-exact quotation')
            reference = view['sources'].get(cite['reference'], {})
            check(reference.get('evidence_id') == cite['evidence_id'], 'Broken citation coverage')
            check(bool(cite['span_ids']) and all(sid in registry and registry[sid]['claim_id'] == mid
                  and registry[sid]['evidence_id'] == cite['evidence_id'] for sid in cite['span_ids']),
                  'Span claim/source mismatch')
    try:
        check(report_text == render_main(view) and detail_text == render_details(view), 'Unmapped rendered text')
    except (KeyError, ValueError, TypeError):
        check(False, 'Unrenderable citation mapping')
    check(not any(eid in report_text for eid in evidence), 'Internal evidence IDs in investor prose')
    for heading in ('# Caterpillar' if cat else '# Microsoft', '## Executive summary', '## Headline financials',
                    '## Investor takeaways', '## Segment revenue', '## Sources'):
        check(heading in report_text, f'Missing report section: {heading}')
    core = report_text.split('## Segment revenue')[0]
    readable = re.sub(r'\[([^\]]+)\]\[[^\]]+\]', r'\1', core)
    core_words = len(readable.split())
    check(core_words <= 220, 'Core exceeds 220-word review budget; never silently truncate notes')
    if cat:
        check('## Revenue reconciliation' in report_text and 'include intersegment activity' in report_text, 'Missing reconciliation scope')
        check(bundle['evaluation']['overall_pass'] or 'Semantic and M004 presentation review pending' in report_text, 'Pending semantics hidden')
    return {'evaluation_version': 'm005-presentation-eval-v1' if cat else 'm004-a-eval-v2',
            'm003_gate_pass': bool(bundle['evaluation']['overall_pass']),
            'automatic_pass': not failures, 'overall_pass': False,
            'manual_review_status': 'pending_manual_review', 'failures': failures,
            'core_word_count': core_words, 'core_word_budget': 220,
            'limitations': 'Word count does not prove 30-second comprehension. Human presentation review '
                           'must assess emphasis, faithful interpretation, and readable formatting separately from M003.'}
