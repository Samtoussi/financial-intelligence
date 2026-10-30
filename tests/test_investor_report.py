"""Offline M004 presentation, fail-closed gates, and immutable historical inputs."""
import copy
import hashlib
import json
from pathlib import Path

import pytest
from test_report_profiles import case
from src.ai.report_generator import render_report
from src.analytics import investor_report as ir
from src.evaluation.investor_report import evaluate_presentation
from src.evaluation.report_evaluation import evaluate_report
from evals.render_investor_report import main


def hashes(directory):
    return {str(p.relative_to(directory)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in directory.rglob('*') if p.is_file()}


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


@pytest.fixture
def approved_run(case, tmp_path):
    directory = tmp_path / 'input'
    directory.mkdir()
    reviews = {n['id']: {'status': 'pass', 'reviewer': 'Synthetic fixture only',
               'rationale': 'Controlled fixture, not a production decision.',
               'evidence_ids': [c['evidence_id'] for c in n['citations']]}
               for n in case.report['notes']}
    result = evaluate_report(case.report, case.evidence, case.gt,
        source_sha256=case.metadata['sha256'], reviews=reviews, profile=case.profile)
    assert result['overall_pass']
    data = {'source.json': case.metadata, 'sections.json': case.sections,
            'evidence.json': case.evidence, 'ground_truth.json': case.gt,
            'generated.json': case.report, 'review.json': reviews, 'evaluation.json': result,
            'run.json': {'status': 'completed_reviewed', 'overall_pass': True, 'profile': case.profile}}
    for name, value in data.items():
        write_json(directory / name, value)
    (directory / 'summary.md').write_text(render_report(case.report, case.evidence), encoding='utf-8')
    return directory


def test_both_profiles_complete_offline_report(approved_run, case, tmp_path):
    before = hashes(approved_run)
    output, result = ir.write_presentation(approved_run, tmp_path / 'outputs')
    assert hashes(approved_run) == before
    assert result['automatic_pass'] and not result['overall_pass']
    assert result['manual_review_status'] == 'pending_manual_review'
    report = (output / 'report.md').read_text(encoding='utf-8')
    detail = (output / 'supporting_detail.md').read_text(encoding='utf-8')
    view = json.loads((output / 'presentation.json').read_text(encoding='utf-8'))
    assert len([m for m in view['metrics'] if m['id'].endswith('_revenue')]) == len(case.config['metrics']) - 4
    assert '+18.4%' in report if case.profile == 'msft_fy2026_q1' else '+18.8%' in report
    assert '$77.7B' in report if case.profile == 'msft_fy2026_q1' else '$92.3B' in report
    assert len([l for l in report.split('## Investor takeaways')[1].split('## Segment revenue')[0].splitlines()
                if l.startswith('- ')]) == 2
    assert 'M004 presentation review pending' in report
    assert '\n\n| Metric' in report and '\n\n- **' in report
    for m in case.report['metrics']:
        assert m['current'] in detail and m['prior'] in detail and m['unit'] in detail
    for note in case.report['notes']:
        assert ir.text(note['text']) in detail
    for e in case.evidence:
        assert e['evidence_id'] not in report
    assert {'report.md','supporting_detail.md','supporting_detail.json','input_manifest.json',
            'presentation.json','m003_gate.json','presentation_evaluation.json','review_template.json'} <= {p.name for p in output.iterdir()}
    template = json.loads((output / 'review_template.json').read_text())
    assert template['report_sha256'] == hashlib.sha256((output / 'report.md').read_bytes()).hexdigest()
    assert template['status'] == 'pending_manual_review' and not (output / 'review.json').exists()
    assert main(['--run', str(approved_run), '--output-root', str(tmp_path/'cli')]) == 2


@pytest.mark.parametrize('amount,unit,expected', [
    ('77673','USD millions','$77.7B'), ('37961','USD millions','$38.0B'),
    ('77650','USD millions','$77.7B'), ('77649','USD millions','$77.6B'),
    ('99950','USD millions','$100.0B'), ('3.30','USD per share','$3.30'),
    ('3.72','USD per share','$3.72')])
def test_half_up_display_rounding(amount, unit, expected):
    assert ir.money(amount, unit) == expected


def metric(mid, current, prior):
    return {'id': mid, 'current': current, 'prior': prior}


def test_exact_growth_comparisons_and_ties():
    a, b = metric('a','125','100'), metric('b','250','200')
    assert ir.leaders([a,b]) == ['a','b']
    # Both display as 25.0%, but the exact rate has a unique leader.
    assert ir.leaders([metric('a','12501','10000'),metric('b','12500','10000')]) == ['a']
    assert ir.leaders([metric('a','90','100'),metric('b','80','100')]) == []
    assert ir.leaders([metric('a','100','100'),metric('b','100','100')]) == []
    with pytest.raises(ValueError):
        ir.leaders([metric('a','100','0')])


@pytest.mark.parametrize('state', ['missing_evaluation','failed','pending','review_missing','stale_values',
    'stale_review','stale_summary','wrong_source','missing_ground_truth','unreviewed_run','version'])
def test_missing_failed_pending_stale_gates(approved_run, state, tmp_path):
    def read(name): return json.loads((approved_run/name).read_text(encoding='utf-8'))
    if state == 'missing_evaluation': (approved_run/'evaluation.json').unlink()
    elif state == 'missing_ground_truth': (approved_run/'ground_truth.json').unlink()
    elif state == 'review_missing': (approved_run/'review.json').unlink()
    elif state == 'stale_summary': (approved_run/'summary.md').write_text('Changed',encoding='utf-8')
    elif state == 'wrong_source':
        data=read('source.json');data['source_url']='https://example.com/other';write_json(approved_run/'source.json',data)
    elif state == 'unreviewed_run':
        data=read('run.json');data['status']='completed_pending_review';write_json(approved_run/'run.json',data)
    elif state == 'stale_values':
        data=read('generated.json');data['metrics'][0]['current']='1';write_json(approved_run/'generated.json',data)
    elif state == 'stale_review':
        data=read('review.json');next(iter(data.values()))['rationale']='Changed';write_json(approved_run/'review.json',data)
    else:
        data=read('evaluation.json')
        if state=='version': data['evaluation_version']='unknown'
        elif state=='pending': data['overall_pass']=False
        else: data['automatic_pass']=False
        write_json(approved_run/'evaluation.json',data)
    before=hashes(approved_run)
    with pytest.raises(ir.GateError): ir.write_presentation(approved_run,tmp_path/'output')
    assert hashes(approved_run)==before and not (tmp_path/'output').exists()


@pytest.mark.parametrize('tamper',['rounding','summary','comparison','leader','source','coverage','quote','span','narrative','status','rendered','completeness'])
def test_presentation_checks_reject_tampering(approved_run, tamper):
    bundle=ir.load_evaluated_run(approved_run);view=ir.build_presentation(bundle)
    if tamper=='rounding': view['metrics'][0]['display_current']='$1.0B'
    elif tamper=='summary': view['summary']+=' This guarantees future growth.'
    elif tamper=='comparison': view['earnings_comparison']='Profits were driven by AI.'
    elif tamper=='leader': view['fastest_segment_ids']=[]
    elif tamper=='source': next(iter(view['sources'].values()))['url']='https://example.com'
    elif tamper=='coverage': next(iter(view['claims'].values()))['citations'][0]['reference']='missing'
    elif tamper=='quote': next(iter(view['claims'].values()))['citations'][0]['quote']='Invented source quotation'
    elif tamper=='span': next(iter(view['claims'].values()))['citations'][0]['span_ids']=['unknown']
    elif tamper=='narrative': view['notes'][0]['text']+=' Investment recommendation.'
    elif tamper=='status': view['m004_review_status']='pass'
    elif tamper=='completeness': view['report']['period_end']='2000-01-01'
    if tamper=='coverage':
        # Check mapping separately without requiring a broken link to render.
        rendered='broken'
    else: rendered=ir.render_main(view)
    if tamper=='rendered': rendered+='\nUnsupported additional claim.\n'
    result=evaluate_presentation(bundle,view,rendered,'broken' if tamper=='coverage' else ir.render_details(view))
    assert not result['automatic_pass'] and not result['overall_pass']


def test_no_output_in_historical_directory_or_overwrite(approved_run,tmp_path):
    before=hashes(approved_run)
    for root in (approved_run,approved_run/'child',approved_run.parent):
        with pytest.raises(ValueError,match='separate'):ir.write_presentation(approved_run,root)
    a,_=ir.write_presentation(approved_run,tmp_path/'outputs')
    old=hashes(a)
    b,_=ir.write_presentation(approved_run,tmp_path/'outputs')
    assert a!=b and hashes(a)==old and hashes(approved_run)==before


@pytest.mark.parametrize('folder', ['evals/reports/m002/20261029T182225Z_684dec81',
                                    'evals/reports/m003/20261030T211637Z_de30375b'])
def test_cached_reviewed_runs_read_only(folder,tmp_path):
    directory=Path(folder)
    if not directory.exists():pytest.skip('Private reviewed run unavailable')
    before=hashes(directory)
    output,result=ir.write_presentation(directory,tmp_path/'rendered')
    assert result['automatic_pass'] and not result['overall_pass']
    assert hashes(directory)==before
    claims=json.loads((output/'supporting_detail.json').read_text(encoding='utf-8'))
    evidence={e['evidence_id']:e for e in json.loads((directory/'evidence.json').read_text(encoding='utf-8'))}
    for claim in claims.values():
        for cite in claim['citations']:assert cite['quote'].encode() in evidence[cite['evidence_id']]['text'].encode()

def test_rendered_segment_ties_and_no_growth(approved_run):
    bundle = ir.load_evaluated_run(approved_run)
    segments = [m for m in bundle['report']['metrics'] if m['id'].endswith('_revenue')]
    for m in segments:
        m['current'] = str(ir.number(m['prior']) * 2)
        m['yoy_percent'] = '100.0'
    view = ir.build_presentation(bundle)
    assert view['fastest_segment_ids'] == [m['id'] for m in segments]
    assert 'shared the fastest segment revenue growth' in view['summary']
    for m in segments:
        m['current'] = m['prior']
        m['yoy_percent'] = '0.0'
    view = ir.build_presentation(bundle)
    assert not view['fastest_segment_ids']
    assert 'No configured segment recorded revenue growth.' in view['summary']


def test_equal_rounded_earnings_rates_do_not_claim_outperformance():
    operating = {'yoy_percent':'12.5'}
    revenue = {'yoy_percent':'12.5'}
    assert ir.earnings_comparison(operating,revenue) == 'Operating income and revenue both increased 12.5% after rounding.'


def test_renderer_makes_no_network_calls(approved_run,tmp_path,monkeypatch):
    import socket
    import requests
    def forbidden(*args,**kwargs): raise AssertionError('Network call attempted')
    monkeypatch.setattr(socket,'create_connection',forbidden)
    monkeypatch.setattr(socket.socket,'connect',forbidden)
    monkeypatch.setattr(requests.sessions.Session,'request',forbidden)
    assert ir.write_presentation(approved_run,tmp_path/'offline')[1]['automatic_pass']


def test_changed_input_during_render_is_rejected(approved_run,tmp_path,monkeypatch):
    original = ir.build_presentation
    def changed(bundle):
        view = original(bundle)
        (approved_run/'summary.md').write_text('Modified concurrently',encoding='utf-8')
        return view
    monkeypatch.setattr(ir,'build_presentation',changed)
    with pytest.raises(ir.GateError,match='Input changed'):
        ir.write_presentation(approved_run,tmp_path/'outputs')
    assert not (tmp_path/'outputs').exists()

def test_natural_summary_and_operating_comparison_for_both_profiles(approved_run, case):
    bundle = ir.load_evaluated_run(approved_run)
    view = ir.build_presentation(bundle)
    if case.profile == 'msft_fy2026_q1':
        expected = ('Microsoft reported revenue of $77.7 billion, up 18.4% year over year, '
                    'while operating income increased 24.3%. Intelligent Cloud was the '
                    'fastest-growing segment, with revenue up 28.2%.')
        comparison = 'Operating income grew faster than revenue (24.3% versus 18.4%).'
    else:
        expected = ('Microsoft reported revenue of $92.3 billion, up 18.8% year over year, '
                    'while operating income increased 21.0%. Agents and Infra was the '
                    'fastest-growing segment, with revenue up 24.5%.')
        comparison = 'Operating income grew faster than revenue (21.0% versus 18.8%).'
    assert view['summary'] == expected
    assert view['earnings_comparison'] == comparison
    assert view['comparison_claim_ids'] == ['operating_income', 'revenue']
    for wording in (view['summary'],view['earnings_comparison']):
        assert 'changed +' not in wording and 'leverage' not in wording and 'driven' not in wording
    assert evaluate_presentation(bundle,view,ir.render_main(view),ir.render_details(view))['automatic_pass']


@pytest.mark.parametrize('operating,revenue,expected', [
    ('10.0','20.0','Operating income grew more slowly than revenue (10.0% versus 20.0%).'),
    ('20.0','10.0','Operating income grew faster than revenue (20.0% versus 10.0%).'),
    ('-5.0','-10.0','Operating income declined less than revenue (5.0% versus 10.0%).'),
    ('-10.0','-5.0','Operating income declined more than revenue (10.0% versus 5.0%).'),
    ('-5.0','10.0','Operating income declined 5.0%, while revenue increased 10.0%.'),
    ('5.0','-10.0','Operating income increased 5.0%, while revenue declined 10.0%.'),
    ('0.0','10.0','Operating income was unchanged at the displayed precision, while revenue increased 10.0%.'),
    ('10.0','0.0','Operating income increased 10.0%, while revenue was unchanged at the displayed precision.'),
    ('0.0','0.0','Operating income and revenue were unchanged at the displayed precision.'),
    ('-0.0','0.0','Operating income and revenue were unchanged at the displayed precision.'),
    ('-5.0','-5.0','Operating income and revenue both declined 5.0% after rounding.'),
])
def test_natural_comparisons_do_not_invent_outperformance(operating,revenue,expected):
    assert ir.earnings_comparison({'yoy_percent':operating},{'yoy_percent':revenue}) == expected


@pytest.mark.parametrize('value,expected', [('12.5','increased 12.5%'),('-12.5','declined 12.5%'),
                                         ('0.0','was unchanged at the displayed precision')])
def test_directional_operating_prose(value,expected):
    assert ir.movement(value) == expected


@pytest.mark.parametrize('folder', ['evals/reports/m002/20261029T182225Z_684dec81',
                                    'evals/reports/m003/20261030T211637Z_de30375b'])
def test_reviewed_qualitative_note_is_byte_exact_in_rendered_markdown(folder):
    directory = Path(folder)
    if not directory.exists():pytest.skip('Private reviewed run unavailable')
    bundle = ir.load_evaluated_run(directory)
    view = ir.build_presentation(bundle)
    note = next(n for n in bundle['report']['notes'] if n['id']=='azure_growth_vs_cloud_margin')
    assert note['text'].encode('utf-8') in ir.render_main(view).encode('utf-8')
    assert note['text'].encode('utf-8') in ir.render_details(view).encode('utf-8')


def test_approved_note_cannot_be_silently_escaped_or_shortened():
    note = {'text':'Reviewed statement with *formatting*.'}
    with pytest.raises(ir.GateError,match='byte-exact reuse'):
        ir.approved_note_text(note)
    assert note['text']=='Reviewed statement with *formatting*.'
