"""M005 real-source excerpt contracts; controlled notes are never human approvals."""
import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from evals.run_report import run_baseline
from src.ai import report_assembly as assembly
from src.analytics import investor_report as ir
from src.analytics.report_evidence import build_report_evidence
from src.analytics.report_profiles import get_profile
from src.analytics.report_tables import token_value, selected_pair
from src.evaluation.report_ground_truth import load_report_dataset, validate_report_dataset
from src.evaluation.report_evaluation import evaluate_report
from src.ingestion import filings
from src.transformation import parse_filings, store_filings, chunk_filings

PROFILE = 'cat_2026_q1'


def controlled_notes(prepared):
    texts = {
        'gaap_vs_non_gaap': 'GAAP diluted EPS was $5.47 versus $4.20. Adjusted EPS was $5.54 versus $4.25, excluding restructuring costs of $0.07 and $0.05 per share, respectively.',
        'segment_comparability': 'The 2025 segment information was retrospectively adjusted to the 2026 presentation. Rail-related responsibilities moved from Power & Energy to Resource Industries effective January 1, 2026.',
        'sales_volume_and_price': 'Caterpillar attributed the increase in consolidated sales and revenues primarily to higher sales volume of $2.3 billion and favorable price realization of $426 million.',
    }
    return {'notes': [{'id': nid, 'text': text,
        'span_ids': [s['span_id'] for s in prepared['spans'] if s['claim_id'] == nid]}
        for nid, text in texts.items()]}


def client_for(raw):
    client = Mock()
    client.responses.create.return_value = SimpleNamespace(status='completed',
        output_text=json.dumps(raw), id='offline-controlled-no-live-call', usage=None)
    return client


@pytest.fixture
def cat_case(tmp_path, monkeypatch):
    c = get_profile(PROFILE)
    for module, attr, path in ((filings, 'RAW_DIR', tmp_path/'raw'),
        (parse_filings, 'RAW_DIR', tmp_path/'raw'), (store_filings, 'OUTPUT_DIR', tmp_path/'sections'),
        (chunk_filings, 'SECTIONS_DIR', tmp_path/'sections'), (chunk_filings, 'CHUNKS_DIR', tmp_path/'chunks')):
        monkeypatch.setattr(module, attr, path)
    # save_sections binds its default at definition time; runner passes through this wrapper.
    import evals.run_report as runner
    monkeypatch.setattr(runner, 'save_sections', lambda ticker, sections: store_filings.save_sections(ticker, sections, tmp_path/'sections'))
    filing = {k: c['report'][k] for k in ('cik','form','accession','filing_date','document','source_url')}
    filing['report_date'] = c['report']['period_end']
    snapshot = filings.save_snapshot('CAT', Path('tests/fixtures/cat_2026_q1_excerpt.html').read_bytes(), filing)
    sections = store_filings.prepare_sections('CAT', form='10-Q', accession=filing['accession'], snapshot_path=snapshot)
    _, meta = parse_filings.load_latest_snapshot('CAT', form='10-Q', accession=filing['accession'], snapshot_path=snapshot)
    evidence = build_report_evidence(sections, meta, profile=PROFILE)
    prepared = assembly.prepare(evidence, PROFILE)
    raw = controlled_notes(prepared)
    report = assembly.assemble(raw, evidence, PROFILE)
    return SimpleNamespace(config=c, snapshot=snapshot, sections=sections, source=meta,
        evidence=evidence, prepared=prepared, raw=raw, report=report, gt=load_report_dataset(PROFILE))


def evaluate(case):
    return evaluate_report(case.report, case.evidence, case.gt, source_sha256=case.source['sha256'], profile=PROFILE)


def test_exact_oracle_and_reconciliation(cat_case):
    c = cat_case
    assert validate_report_dataset(c.gt, PROFILE) == {
        'revenue':'22.2', 'operating_income':'19.6', 'net_income':'27.3', 'diluted_eps':'30.2',
        'power_and_energy_revenue':'21.6', 'construction_industries_revenue':'38.1',
        'resource_industries_revenue':'3.7', 'financial_products_revenue':'8.8'}
    result = evaluate(c)
    assert result['automatic_pass'], result
    assert result['financial_values'] == {'passed':16,'total':16}
    assert result['table_evidence_support'] == {'passed':8,'total':8}
    assert result['reconciliation'] == {'passed':48,'total':48,'identities_pass':True}
    assert not result['overall_pass']
    assert all(r['status']=='pending_manual_review' for r in result['manual_reviews'])
    assert c.report['reconciliation'][6]['total'] == ['-1747','-1456']
    assert 'EXCLUDED_MARKET_RISK' not in ''.join(s['text'] for s in c.sections)
    assert {p['column_year'] for p in c.prepared['numeric_provenance']} == {'2026','2025'}


@pytest.mark.parametrize('token,expected', [('( 1,747 )','-1747'), ('-218','-218'), ('—','0'), ('5.47','5.47')])
def test_signed_source_tokens(token, expected):
    assert str(token_value(token)) == expected


@pytest.mark.parametrize('token', ['1,74','NaN','1e3','1 footnote','--1','(1,2)'])
def test_invalid_tokens_fail_closed(token):
    with pytest.raises(ValueError): token_value(token)


@pytest.mark.parametrize('corruption', ['value','yoy','basis','scope','reconciliation','sign','quote','ticker','claim'])
def test_corruption_is_rejected(cat_case, corruption):
    c=cat_case
    if corruption=='value': c.report['metrics'][0]['current']='17416'
    elif corruption=='yoy': c.report['metrics'][0]['yoy_percent']='22.3'
    elif corruption=='basis': c.report['metrics'][4]['gaap_status']='GAAP'
    elif corruption=='scope': c.report['metrics'][4]['current']='5713'
    elif corruption=='reconciliation': c.report['reconciliation'].pop()
    elif corruption=='sign': c.report['reconciliation'][6]['total'][0]='1747'
    elif corruption=='quote': c.report['metrics'][4]['citations'].pop()
    elif corruption=='ticker': c.report['report']['ticker']='MSFT'
    elif corruption=='claim':
        c.raw['notes'][0]['span_ids']=[c.prepared['spans'][0]['span_id']]
        with pytest.raises(ValueError): assembly.assemble(c.raw,c.evidence,PROFILE)
        return
    assert not evaluate(c)['automatic_pass']


@pytest.mark.parametrize('corruption', ['period','unit','footnote','duplicate','boundary'])
def test_changed_source_layout_fails(cat_case, corruption):
    c=cat_case
    sections=copy.deepcopy(c.sections)
    t=sections[0]['text']
    if corruption=='period': t=t.replace('Three Months Ended March 31, 2026','Three Months Ended June 30, 2026')
    elif corruption=='unit': t=t.replace('Millions of dollars','Thousands of dollars')
    elif corruption=='footnote': t=t.replace('| 1 | — |','| 2 | — |')
    elif corruption=='duplicate': t=t.replace('| Total sales and revenues |','| Operating profit |')
    elif corruption=='boundary': t=t.replace('16. Segment information','16. Other information')
    sections[0]['text']=t
    with pytest.raises(ValueError): build_report_evidence(sections,c.source,profile=PROFILE)


@pytest.mark.parametrize('corruption', ['value','sign','row','columns','period','income_scope'])
def test_oracle_corruption_rejected(cat_case, corruption):
    data=cat_case.gt
    if corruption=='value': data['reconciliation'][0]['external'][0]='5714'
    elif corruption=='sign': data['reconciliation'][6]['total'][0]='1747'
    elif corruption=='row': data['metrics'][2]['source']['row']='Profit of consolidated and affiliated companies'
    elif corruption=='columns': data['metrics'][4]['source']['columns']='External sales'
    elif corruption=='period': data['periods']['prior']['start']='2025-04-01'
    elif corruption=='income_scope': data['metrics'][2]['gaap_status']='GAAP'
    with pytest.raises(ValueError): validate_report_dataset(data,PROFILE)


def test_runner_and_pending_draft(cat_case,tmp_path):
    c=cat_case
    client=client_for(c.raw)
    run,result=run_baseline(snapshot_path=c.snapshot,profile=PROFILE,generation_mode='m003-v2',
        client=client,reports_dir=tmp_path/'runs')
    assert result['automatic_pass'] and not result['overall_pass']
    client.responses.create.assert_called_once()
    request=client.responses.create.call_args.kwargs
    assert 'Azure' not in request['instructions'] and 'ground_truth' not in request['input']
    with pytest.raises(ir.GateError): ir.load_evaluated_run(run)
    before={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in run.iterdir() if p.is_file()}
    output,presentation=ir.write_presentation(run,tmp_path/'views',allow_pending_review=True)
    assert presentation['automatic_pass'], presentation
    assert not presentation['overall_pass'] and not presentation['m003_gate_pass']
    text=(output/'report.md').read_text(encoding='utf-8')
    assert 'Semantic and M004 presentation review pending' in text
    assert 'Corporate Items and Eliminations' in text and '-1747 / -1456' in text
    assert 'M003 automatic checks and qualitative reviews passed' not in text
    assert 'Microsoft' not in text and 'Cloud' not in text
    assert before=={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in run.iterdir() if p.is_file()}
    assert not (run/'review.json').exists()


@pytest.mark.parametrize('corruption', ['reconciliation','status','company','quote'])
def test_presentation_tampering(cat_case,tmp_path,corruption):
    c=cat_case
    run,_=run_baseline(snapshot_path=c.snapshot,profile=PROFILE,generation_mode='m003-v2',
        client=client_for(c.raw),reports_dir=tmp_path/'runs')
    bundle=ir.load_evaluated_run(run,allow_pending_review=True)
    view=ir.build_presentation(bundle)
    if corruption=='reconciliation': view['reconciliation'][6]['total'][0]='1747'
    elif corruption=='status': view['m003_overall_pass']=True
    elif corruption=='company': view['company']='Microsoft'
    elif corruption=='quote': next(iter(view['claims'].values()))['citations'][0]['quote']='fabricated quotation'
    from src.evaluation.investor_report import evaluate_presentation
    result=evaluate_presentation(bundle,view,ir.render_main(view),ir.render_details(view))
    assert not result['automatic_pass']


def test_cached_cat_source_when_available():
    paths=list(Path('data/raw/sec/filings/CAT/0000018230-26-000021').glob('*.html'))
    if not paths: pytest.skip('Private SEC snapshot unavailable; excerpt contracts run independently')
    path=paths[0]
    assert hashlib.sha256(path.read_bytes()).hexdigest()==load_report_dataset(PROFILE)['verification']['source_sha256']
    sections=store_filings.prepare_sections('CAT',form='10-Q',accession=get_profile(PROFILE)['report']['accession'],snapshot_path=path)
    _,source=parse_filings.load_latest_snapshot('CAT',form='10-Q',snapshot_path=path)
    evidence=build_report_evidence(sections,source,profile=PROFILE)
    prepared=assembly.prepare(evidence,PROFILE)
    report=assembly.assemble(controlled_notes(prepared),evidence,PROFILE)
    assert evaluate_report(report,evidence,load_report_dataset(PROFILE),source_sha256=source['sha256'],profile=PROFILE)['automatic_pass']
