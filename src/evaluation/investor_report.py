"""Presentation checks supplement, never replace, the independent M003 evaluator."""
import re
from decimal import Decimal, ROUND_HALF_UP
from fractions import Fraction

from src.analytics.investor_report import LABELS, SOURCE_LABELS, render_main, render_details


def evaluate_presentation(bundle, view, report_text, detail_text):
    failures = []
    def check(condition, message):
        if not condition:
            failures.append(message)
    original = bundle['report']
    expected = {m['id']: m for m in original['metrics']}
    actual = {m['id']: m for m in view['metrics']}
    check(set(actual) == set(expected) and len(actual) == len(view['metrics']), 'Metric completeness')
    check(view['report'] == original['report'], 'Report identity')
    check(view['notes'] == original['notes'], 'Narrative changed')
    check(view['takeaway_ids'] == ['azure_growth_vs_cloud_margin'], 'Takeaway selection')
    check(view['m004_review_status'] == 'pending_manual_review', 'Unreviewed presentation approval')
    check(bundle['evaluation']['overall_pass'] and view['m003_overall_pass']
          and view['m003_automatic_pass'], 'M003 gate')
    for mid, m in actual.items():
        if mid not in expected:
            continue
        source = expected[mid]
        check(all(m.get(k) == source[k] for k in source), f'Exact value/basis changed: {mid}')
        check(m['label'] == LABELS.get(mid, bundle['config']['metrics'][mid][0]), f'Label changed: {mid}')
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
    segments = [m for m in original['metrics'] if m['id'].endswith('_revenue')]
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
    check(view['earnings_comparison'] == comparison, 'Unsupported earnings comparison')
    evidence = {e['evidence_id']: e for e in bundle['evidence']}
    registry = {s['span_id']: s for s in bundle['registry']['spans']}
    check(set(view['claims']) == set(expected) | {n['id'] for n in original['notes']}, 'Claim completeness')
    source_ids = [s['evidence_id'] for s in view['sources'].values()]
    check(set(source_ids) == set(evidence) and len(source_ids) == len(evidence), 'Source map completeness')
    for source in view['sources'].values():
        e = evidence.get(source['evidence_id'], {})
        check(source['url'] == e.get('source_url') and source['label'] == SOURCE_LABELS.get(e.get('label')),
              'Source identity or readable label')
    originals = {i['id']: i for i in original['metrics'] + original['notes']}
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
    for heading in ('# Microsoft', '## Executive summary', '## Headline financials',
                    '## Investor takeaways', '## Segment revenue', '## Sources'):
        check(heading in report_text, f'Missing report section: {heading}')
    core = report_text.split('## Segment revenue')[0]
    readable = re.sub(r'\[([^\]]+)\]\[[^\]]+\]', r'\1', core)
    core_words = len(readable.split())
    check(core_words <= 220, 'Core exceeds 220-word review budget; never silently truncate notes')
    return {'evaluation_version': 'm004-a-eval-v2',
            'm003_gate_pass': bool(bundle['evaluation']['overall_pass']),
            'automatic_pass': not failures, 'overall_pass': False,
            'manual_review_status': 'pending_manual_review', 'failures': failures,
            'core_word_count': core_words, 'core_word_budget': 220,
            'limitations': 'Word count does not prove 30-second comprehension. Human presentation review '
                           'must assess emphasis, faithful interpretation, and readable formatting separately from M003.'}
