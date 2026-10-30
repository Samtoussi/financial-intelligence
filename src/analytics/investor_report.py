"""Offline investor presentation of saved reports; historical inputs are read-only."""
import copy
import hashlib
import json
import re
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from fractions import Fraction
from pathlib import Path
from uuid import uuid4

from src.ai.report_assembly import MODE, assemble, prepare
from src.ai.report_generator import render_report
from src.analytics.report_evidence import build_report_evidence
from src.analytics.report_profiles import DEFAULT_PROFILE, get_profile, profile_for_accession
from src.evaluation.report_evaluation import evaluate_report
from src.evaluation.report_ground_truth import load_report_dataset

VERSION = 'm004-a-v2'
LABELS = {'revenue': 'Revenue', 'operating_income': 'Operating income',
          'net_income': 'Net income', 'diluted_eps': 'Diluted EPS'}
SOURCE_LABELS = {'income_statement': 'Income statements · Part I, Item 1',
                 'segment_table': 'Segment disclosures · Part I, Item 1',
                 'segment_basis': 'Segment reporting basis · Part I, Item 1',
                 'recast_disclosure': 'Segment recast disclosure · Part I, Item 1',
                 'management_summary': 'Management discussion · Part I, Item 2'}
NOTE_LABELS = {'gaap_vs_non_gaap': 'Earnings basis',
               'azure_growth_vs_cloud_margin': 'Cloud growth and margin',
               'segment_comparability': 'Segment reporting basis',
               'recast_segment_comparability': 'Segment comparability'}


class GateError(ValueError):
    """Saved run is incomplete, unapproved, inconsistent, or stale."""


def digest(payload):
    return hashlib.sha256(payload).hexdigest()


def load_evaluated_run(directory):
    directory = Path(directory).resolve()
    blobs = {p.name: p.read_bytes() for p in directory.iterdir() if p.is_file()}
    def read(name):
        if name not in blobs:
            raise GateError(f'Missing saved artifact: {name}')
        return json.loads(blobs[name].decode('utf-8'))
    try:
        source, report, saved, run = (read(n) for n in
            ('source.json', 'generated.json', 'evaluation.json', 'run.json'))
        profile = profile_for_accession(source['accession'])
        config = get_profile(profile)
        if 'profile.json' in blobs and read('profile.json') != json.loads(json.dumps(config)):
            raise GateError('Saved profile is inconsistent')
        evidence = read('evidence.json')
        if evidence != build_report_evidence(read('sections.json'), source, profile=profile):
            raise GateError('Evidence does not match saved sections')
        if not saved.get('automatic_pass') or not saved.get('overall_pass'):
            raise GateError('M003 automatic and human review gates must pass')
        if run.get('status') != 'completed_reviewed' or run.get('overall_pass') is not True:
            raise GateError('Saved run has not completed review')
        if 'profile' in run and run['profile'] != profile:
            raise GateError('Run profile mismatch')
        if blobs.get('summary.md', b'').decode('utf-8').replace('\r\n', '\n') != render_report(report, evidence):
            raise GateError('Saved summary is missing or stale')
        registry = prepare(evidence, profile)
        if run.get('generation_mode') == MODE:
            if assemble(read('raw_llm.json'), evidence, profile, read('assembly_inputs.json')) != report:
                raise GateError('Raw response and assembled report disagree')
            if json.loads(read('raw_llm_text.json')) != read('raw_llm.json'):
                raise GateError('Raw response text is inconsistent')
        ground_truth = load_report_dataset(profile, directory / 'ground_truth.json')
        fresh = evaluate_report(report, evidence, ground_truth, source_sha256=source['sha256'],
                                reviews=read('review.json'), profile=profile)
        # The approved M002 artifact predates the profile-aware evaluator version only.
        versions = {'m003-eval-v1'} | ({'m002-eval-v2'} if profile == DEFAULT_PROFILE else set())
        if saved.get('evaluation_version') not in versions:
            raise GateError('Unknown evaluation version')
        if not fresh['overall_pass'] or any(saved.get(k) != v for k, v in fresh.items()
                                            if k != 'evaluation_version'):
            raise GateError('Saved evaluation/reviews are stale or fail read-only evaluation')
        for item in report['metrics'] + report['notes']:
            for cite in item['citations']:
                e = next(e for e in evidence if e['evidence_id'] == cite['evidence_id'])
                if cite['quote'] not in e['text']:
                    raise GateError('Quotation is not byte-exact saved evidence')
        return {'directory': str(directory), 'profile': profile, 'config': config,
                'report': report, 'evidence': evidence, 'registry': registry, 'evaluation': fresh,
                'hashes': {name: digest(data) for name, data in blobs.items()}}
    except GateError:
        raise
    except (KeyError, ValueError, TypeError, AttributeError, OSError, StopIteration) as exc:
        raise GateError(f'Invalid saved run ({type(exc).__name__})') from None


def number(value):
    return Decimal(value.replace(',', ''))


def money(value, unit):
    amount = number(value)
    if unit == 'USD millions':
        rounded = (amount / Decimal(1000)).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)
        return f'${rounded:,.1f}B'
    if unit == 'USD per share':
        return f'${amount:.2f}'
    raise ValueError('Unsupported financial display unit')


def percent(value):
    return f'{number(value):+.1f}%'


def rate(metric):
    current, prior = Fraction(number(metric['current'])), Fraction(number(metric['prior']))
    if prior <= 0:
        raise ValueError('Unsupported comparison denominator')
    return (current - prior) / prior


def leaders(segments):
    best = max(rate(m) for m in segments)
    # Nonpositive maxima do not justify a fastest-growing segment claim.
    return [m['id'] for m in segments if rate(m) == best] if best > 0 else []


def text(value):
    """Escape narrative Markdown syntax without treating it as a quotation."""
    return re.sub(r'([\\`*_[\]<>|])', r'\\\1', value).replace('\n', ' ')


def approved_note_text(note):
    """Do not silently rewrite reviewed narrative to make it safe Markdown."""
    if text(note['text']) != note['text']:
        raise GateError('Approved note requires formatting review before byte-exact reuse')
    return note['text']


def movement(value):
    change = number(value)
    if change == 0:
        return 'was unchanged at the displayed precision'
    verb = 'increased' if change > 0 else 'declined'
    return f'{verb} {abs(change):.1f}%'


def build_presentation(bundle):
    config, report = bundle['config'], bundle['report']
    sources = {f'S{i}': {'label': SOURCE_LABELS[e['label']], 'url': e['source_url'],
                         'evidence_id': e['evidence_id']}
               for i, e in enumerate(bundle['evidence'], 1)}
    refs = {s['evidence_id']: ref for ref, s in sources.items()}
    claims = {}
    for item in report['metrics'] + report['notes']:
        citations = []
        for cite in item['citations']:
            span_ids = [s['span_id'] for s in bundle['registry']['spans']
                        if s['claim_id'] == item['id'] and s['evidence_id'] == cite['evidence_id']
                        and (s['quote'] in cite['quote'] or cite['quote'] in s['quote'])]
            if not span_ids:
                raise GateError('Citation cannot be mapped to a claim-bound source span')
            citations.append({**cite, 'span_ids': span_ids, 'reference': refs[cite['evidence_id']]})
        claims[item['id']] = {'citations': citations}
    metrics = [{**m, 'label': LABELS.get(m['id'], config['metrics'][m['id']][0]),
                'display_current': money(m['current'], m['unit']),
                'display_prior': money(m['prior'], m['unit']),
                'display_yoy': percent(m['yoy_percent'])} for m in report['metrics']]
    by_id = {m['id']: m for m in metrics}
    segments = [m for m in metrics if m['id'].endswith('_revenue')]
    fastest = leaders(segments)
    labels = [by_id[mid]['label'] for mid in fastest]
    names = (' and '.join(labels) if len(labels) < 3 else
             ', '.join(labels[:-1]) + ', and ' + labels[-1])
    revenue, operating = by_id['revenue'], by_id['operating_income']
    revenue_change = number(revenue['yoy_percent'])
    direction = (f"{'up' if revenue_change > 0 else 'down'} {abs(revenue_change):.1f}%"
                 if revenue_change else 'unchanged at the displayed precision')
    revenue_amount = revenue['display_current'].removesuffix('B') + ' billion'
    summary = (f"Microsoft reported revenue of {revenue_amount}, {direction} year over year, "
               f"while operating income {movement(operating['yoy_percent'])}.")
    if fastest:
        growth = abs(number(by_id[fastest[0]]['yoy_percent']))
        growth_description = (f'revenue up {growth:.1f}%' if growth else
                              'revenue growth rounding to 0.0%')
        if len(fastest) == 1:
            summary += f' {names} was the fastest-growing segment, with {growth_description}.'
        else:
            summary += (f' {names} shared the fastest segment revenue growth, '
                        f'each with {growth_description}.')
    else:
        summary += ' No configured segment recorded revenue growth.'
    note_ids = ['azure_growth_vs_cloud_margin']
    comparison = earnings_comparison(operating, revenue)
    view = {'version': VERSION, 'report': report['report'], 'metrics': metrics,
            'notes': report['notes'], 'takeaway_ids': note_ids, 'fastest_segment_ids': fastest,
            'summary': summary, 'earnings_comparison': comparison,
            'comparison_claim_ids': ['operating_income', 'revenue'],
            'sources': sources, 'claims': claims,
            'summary_claim_ids': ['revenue', 'operating_income'] + [m['id'] for m in segments],
            'm003_automatic_pass': True, 'm003_overall_pass': True,
            'm004_review_status': 'pending_manual_review'}
    return copy.deepcopy(view)


def earnings_comparison(operating, revenue):
    op, rev = number(operating['yoy_percent']), number(revenue['yoy_percent'])
    if op == rev:
        if op == 0:
            return 'Operating income and revenue were unchanged at the displayed precision.'
        verb = 'increased' if op > 0 else 'declined'
        return f'Operating income and revenue both {verb} {abs(op):.1f}% after rounding.'
    if min(op, rev) > 0:
        relation = 'faster' if op > rev else 'more slowly'
        return f'Operating income grew {relation} than revenue ({op:.1f}% versus {rev:.1f}%).'
    if max(op, rev) < 0:
        relation = 'less' if op > rev else 'more'
        return f'Operating income declined {relation} than revenue ({abs(op):.1f}% versus {abs(rev):.1f}%).'
    return (f"Operating income {movement(operating['yoy_percent'])}, "
            f"while revenue {movement(revenue['yoy_percent'])}.")

def references(view, ids):
    refs = list(dict.fromkeys(c['reference'] for mid in ids for c in view['claims'][mid]['citations']))
    return ' '.join(f"[{view['sources'][ref]['label'].partition('\u00b7')[0].strip()}][{ref}]" for ref in refs)


def render_main(view):
    meta = view['report']
    metrics = {m['id']: m for m in view['metrics']}
    lines = [f"# Microsoft (MSFT) · {meta['fiscal_period']}",
             f"{meta['period_start']} to {meta['period_end']}; compared with {meta['prior_start']} to {meta['prior_end']}.",
             '**Automated draft · M004 presentation review pending.** M003 automatic checks and qualitative reviews passed.',
             '## Executive summary', text(view['summary']) + ' ' + references(view, view['summary_claim_ids']),
             '## Headline financials', 'GAAP. B = USD billions, rounded to one decimal; EPS = USD per share. YoY is calculated from exact source values.',
             '| Metric | Current | YoY |', '|---|---:|---:|']
    for mid in LABELS:
        m = metrics[mid]
        lines.append(f"| {m['label']} | **{m['display_current']}** | {m['display_yoy']} |")
    lines += [references(view, list(LABELS)), '## Investor takeaways']
    lines.append('- **Operating performance:** ' + text(view['earnings_comparison']) + ' ' +
                 references(view, view['comparison_claim_ids']))
    for nid in view['takeaway_ids']:
        note = next(n for n in view['notes'] if n['id'] == nid)
        lines.append(f"- **{NOTE_LABELS[nid]}:** {approved_note_text(note)} {references(view, [nid])}")
    lines += ['## Segment revenue', '| Segment | Current | Prior | YoY |', '|---|---:|---:|---:|']
    segments = [m for m in view['metrics'] if m['id'].endswith('_revenue')]
    for m in segments:
        lines.append(f"| {m['label']} | {m['display_current']} | {m['display_prior']} | {m['display_yoy']} |")
    basis = next(n['id'] for n in view['notes'] if 'comparability' in n['id'])
    lines += [references(view, [m['id'] for m in segments] + [basis]),
              '[Exact financial values, reporting basis, all approved notes, and source quotations](supporting_detail.md).',
              '## Sources', f"Microsoft Form {meta['form']}, accession {meta['accession']}."]
    lines += [f"- [{s['label']}][{ref}]" for ref, s in view['sources'].items()]
    lines += [f"[{ref}]: {s['url']} \"{s['label']}\"" for ref, s in view['sources'].items()]
    formatted = []
    for i, line in enumerate(lines):
        if i and (line.startswith('#') or lines[i-1].startswith('#')
                  or line.startswith('- ') and not lines[i-1].startswith('- ')
                  or line.startswith('|') != lines[i-1].startswith('|')
                  or line.startswith('[') and not line.startswith('[S')
                  or line.startswith('[S') and not lines[i-1].startswith('[S')
                  or i == 2):
            formatted.append('')
        formatted.append(line)
    return '\n'.join(formatted) + '\n'


def render_details(view):
    lines = ['# Supporting detail', '', 'Exact reported values. USD millions except diluted EPS (USD per share).', '',
             '| Metric | Current | Prior | YoY | Unit | Basis |', '|---|---:|---:|---:|---|---|']
    for m in view['metrics']:
        lines.append(f"| {m['label']} | {m['current']} | {m['prior']} | {m['yoy_percent']}% | {m['unit']} | {m['gaap_status']} |")
    for note in view['notes']:
        lines += [f"\n## {NOTE_LABELS[note['id']]}", '', approved_note_text(note), '']
    lines += ['\n## Exact saved source quotations', 'These are saved extracted-text quotations, not raw HTML markup.']
    for mid, claim in view['claims'].items():
        label = next((m['label'] for m in view['metrics'] if m['id'] == mid), NOTE_LABELS.get(mid))
        lines.append(f'\n### {label}\n')
        for cite in claim['citations']:
            s = view['sources'][cite['reference']]
            fence = '`' * max(3, max((len(x) for x in re.findall(r'`+', cite['quote'])), default=0) + 1)
            lines += [f"[{s['label']}]({s['url']})", '', fence, cite['quote'], fence]
    return '\n'.join(lines) + '\n'


def write_presentation(input_dir, output_root):
    from src.evaluation.investor_report import evaluate_presentation
    bundle = load_evaluated_run(input_dir)
    view = build_presentation(bundle)
    report, detail = render_main(view), render_details(view)
    evaluation = evaluate_presentation(bundle, view, report, detail)
    if not evaluation['automatic_pass']:
        raise ValueError('Presentation failed automatic checks')
    root, source = Path(output_root).resolve(), Path(input_dir).resolve()
    if root == source or root.is_relative_to(source) or source.is_relative_to(root):
        raise ValueError('M004 output must be separate from the source run')
    for name, expected in bundle['hashes'].items():
        if digest((source / name).read_bytes()) != expected:
            raise GateError('Input changed during presentation')
    if {p.name for p in source.iterdir() if p.is_file()} != set(bundle['hashes']):
        raise GateError('Input artifact set changed during presentation')
    output = root / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '_' + uuid4().hex[:8])
    output.mkdir(parents=True, exist_ok=False)
    files = {'presentation.json': view, 'supporting_detail.json': view['claims'],
             'input_manifest.json': {'renderer_version': VERSION, 'input_directory': str(source),
                 'profile': bundle['profile'], 'input_sha256': bundle['hashes']},
             'm003_gate.json': bundle['evaluation'], 'presentation_evaluation.json': evaluation,
             'review_template.json': {'status': 'pending_manual_review', 'reviewer': '', 'rationale': '',
                 'report_sha256': digest(report.encode()), 'supporting_detail_sha256': digest(detail.encode()),
                 'criteria': ['30-second comprehension and clarity', 'faithful emphasis and comparisons',
                              'narrative context and citations', 'formatting and completeness']}}
    for name, data in files.items():
        (output / name).write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    (output / 'report.md').write_bytes(report.encode('utf-8'))
    (output / 'supporting_detail.md').write_bytes(detail.encode('utf-8'))
    return output, evaluation
