"""Two observed layouts: synthetic regressions plus optional cached SEC verification."""
import hashlib
import json
import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from bs4 import BeautifulSoup

from test_report_pipeline import sample_html, mock_client
from src.analytics.report_profiles import DEFAULT_PROFILE, PROFILES, get_profile
from src.analytics.report_evidence import build_report_evidence
from src.ai.report_generator import generate_report, output_schema, INSTRUCTIONS
from src.evaluation.report_ground_truth import load_report_dataset, validate_report_dataset
from src.evaluation.report_evaluation import evaluate_report, _source_row
from src.evaluation.ground_truth import yoy
from src.ingestion import filings
from src.transformation import parse_filings, store_filings
from evals import run_report

SECOND = 'msft_fy2026_q1'


def controlled_report(profile, evidence):
    c = get_profile(profile)
    gt = load_report_dataset(profile)
    by_label = {e['label']: e for e in evidence}
    entries = []
    for m in gt['metrics']:
        e = by_label['segment_table' if m['id'].endswith('_revenue') else 'income_statement']
        entries.append({'id': m['id'], 'current': m['current']['value'], 'prior': m['prior']['value'],
                        'unit': m['unit'], 'gaap_status': m['gaap_status'],
                        'yoy_percent': yoy(m['current']['value'], m['prior']['value']),
                        'citations': [{'evidence_id': e['evidence_id'], 'quote': e['text']}]})
    notes = []
    for nid in c['topics']:
        label = ('recast_disclosure' if profile == DEFAULT_PROFILE else 'segment_basis') if 'comparability' in nid else 'management_summary'
        e = by_label[label]
        notes.append({'id': nid, 'text': 'Controlled test interpretation requiring human review.',
                      'citations': [{'evidence_id': e['evidence_id'], 'quote': e['text']}]})
    return {'report': {k:c['report'][k] for k in output_schema(profile)['schema']['properties']['report']['properties']},
            'metrics': entries, 'notes': notes}


@pytest.fixture(params=[key for key in PROFILES if key.startswith('msft_')])
def case(request, tmp_path, monkeypatch):
    profile = request.param
    c = get_profile(profile)
    gt = load_report_dataset(profile)
    html = sample_html().decode()
    if profile == SECOND:
        # This layout has no recast note; all three segments are explicitly retained.
        old = html.index('<p>Recast of Certain Prior Period Information</p>')
        end = html.index('<p>Estimates and Assumptions</p>', old)
        html = html[:old] + '<p>NOTE 16 - SEGMENT INFORMATION AND GEOGRAPHIC DATA</p><p>During the periods presented, three segments were reported.</p><p>Our reportable segments are described below.</p>' + html[end:]
        html = html.replace('2026', 'CURRENT_YEAR').replace('2025', '2024').replace('CURRENT_YEAR', '2025')
        pairs = dict(zip(['92,279','77,673','45,915','37,961','36,629','27,747','4.92','3.72'], ['77,673','65,585','37,961','30,552','27,747','24,667','3.72','3.30']))
        html = re.sub('|'.join(re.escape(x) for x in pairs), lambda m:pairs[m[0]], html)
        start = html.index('<tr><td>Agents and Infra')
        end = html.index('</table>', start)
        html = html[:start] + ''.join(f'<tr><td>{c["metrics"][m["id"]][0]}</td></tr><tr><td>Revenue</td><td>{m["current"]["value"]}</td><td>{m["prior"]["value"]}</td></tr>' for m in gt['metrics'][4:]) + html[end:]
        html = html.replace('No sales to an individual country', 'No sales to an individual customer or country')
    raw = tmp_path / 'raw'
    monkeypatch.setattr(filings, 'RAW_DIR', raw)
    monkeypatch.setattr(parse_filings, 'RAW_DIR', raw)
    filing = {k:c['report'][k] for k in ('cik','form','accession','filing_date','document','source_url')}
    filing['report_date'] = c['report']['period_end']
    path = filings.save_snapshot('MSFT', html.encode(), filing)
    _, meta = parse_filings.load_latest_snapshot('MSFT', form='10-Q', accession=filing['accession'], snapshot_path=path)
    sections = store_filings.prepare_sections('MSFT', form='10-Q', accession=filing['accession'], snapshot_path=path)
    evidence = build_report_evidence(sections, meta, profile=profile)
    return SimpleNamespace(profile=profile, config=c, gt=gt, snapshot=path, metadata=meta, sections=sections,
                           evidence=evidence, report=controlled_report(profile, evidence))


def evaluate(case, **kwargs):
    return evaluate_report(case.report, case.evidence, case.gt, source_sha256=case.metadata['sha256'], profile=case.profile, **kwargs)


def test_profile_pipeline_and_oracle_separation(case):
    n = len(case.config['metrics'])
    assert len(validate_report_dataset(case.gt, case.profile)) == n
    result = evaluate(case)
    assert result['financial_values'] == {'passed': n*2, 'total': n*2}
    assert result['yoy_changes'] == {'passed': n, 'total': n}
    assert result['table_evidence_support'] == {'passed': n, 'total': n}
    assert result['automatic_pass'] and not result['overall_pass']
    assert all(r['status'] == 'pending_manual_review' for r in result['manual_reviews'])
    client = mock_client(case.report)
    generate_report(case.evidence, client=client, profile=case.profile)
    sent = client.responses.create.call_args.kwargs
    payload = json.loads(sent['input'])
    assert set(payload) == {'report', 'requested_metrics', 'interpretation_topics', 'evidence'}
    assert all(set(m) == {'id','label','unit','gaap_status'} for m in payload['requested_metrics'])
    assert len(payload['requested_metrics']) == n
    assert sent['text']['format']['schema']['properties']['metrics']['minItems'] == n
    assert 'ground_truth' not in sent['input'] and 'verification' not in sent['input']
    if case.profile == DEFAULT_PROFILE:
        assert sent['instructions'] == INSTRUCTIONS
    else:
        assert 'recast_disclosure' not in {e['label'] for e in case.evidence}
        assert 'segment_basis' in {e['label'] for e in case.evidence}


def test_wrong_filing_rejected_at_all_stages(case):
    other = SECOND if case.profile == DEFAULT_PROFILE else DEFAULT_PROFILE
    with pytest.raises(ValueError, match='Pinned source mismatch'):
        build_report_evidence(case.sections, case.metadata, profile=other)
    client = Mock()
    with pytest.raises(ValueError, match='wrong-filing'):
        generate_report(case.evidence, client=client, profile=other)
    client.responses.create.assert_not_called()
    with pytest.raises(ValueError, match='metadata|schema'):
        validate_report_dataset(case.gt, other)
    case.evidence[0]['accession'] = get_profile(other)['report']['accession']
    assert not evaluate(case)['citation_integrity_pass']


@pytest.mark.parametrize('label', ['income_statement','segment_table','basis','management_summary'])
def test_missing_boundaries_fail_closed(case, label):
    boundary = case.config['boundaries'][2 if label == 'basis' else {'income_statement':0,'segment_table':1,'management_summary':3}[label]]
    _, item, start, end, _ = boundary
    section = next(s for s in case.sections if s['item'] == item)
    pattern = start or end
    section['text'] = re.sub(pattern, 'REMOVED BOUNDARY', section['text'], flags=re.I)
    with pytest.raises(ValueError, match='evidence missing'):
        build_report_evidence(case.sections, case.metadata, profile=case.profile)


@pytest.mark.parametrize('mode', ['reverse','wrong','extra'])
def test_period_column_order_and_scope(case, mode):
    current, prior = case.config['report']['period_end'][:4], case.config['report']['prior_end'][:4]
    def corrupt(text):
        if mode == 'reverse':
            return text.replace(current,'TEMPYEAR').replace(prior,current).replace('TEMPYEAR',prior)
        if mode == 'wrong': return text.replace(prior,'2023')
        return text.replace(current, current+' | 2023')
    case.sections[0]['text'] = corrupt(case.sections[0]['text'])
    with pytest.raises(ValueError, match='period columns'):
        build_report_evidence(case.sections, case.metadata, profile=case.profile)
    # A valid hash and real numbers cannot overcome wrong column context.
    for e in case.evidence:
        if e['label'] in ('income_statement','segment_table'):
            e['text'] = corrupt(e['text'])
            e['text_sha256'] = hashlib.sha256(e['text'].encode()).hexdigest()
    assert not evaluate(case)['automatic_pass']


@pytest.mark.parametrize('period', ['current','prior'])
def test_each_incorrect_value_and_segment_reconciliation(case, period):
    for index in range(len(case.report['metrics'])):
        original = case.report['metrics'][index][period]
        case.report['metrics'][index][period] = '1.01'
        result = evaluate(case)
        assert not result['automatic_pass']
        assert result['financial_values']['passed'] == len(case.report['metrics'])*2-1
        case.report['metrics'][index][period] = original
    case.gt['metrics'][-1][period]['value'] = '1'
    with pytest.raises(ValueError, match='segment total'):
        validate_report_dataset(case.gt, case.profile)


def test_pending_failed_and_invalid_reviews_never_pass(case):
    reviews = {n['id']:{'status':'pass','reviewer':'Controlled test','rationale':'Test-only decision',
                       'evidence_ids':[n['citations'][0]['evidence_id']]} for n in case.report['notes']}
    assert evaluate(case, reviews=reviews)['overall_pass']
    for status in ('pending_manual_review','fail'):
        reviews[case.report['notes'][0]['id']]['status'] = status
        assert not evaluate(case, reviews=reviews)['overall_pass']
    reviews[case.report['notes'][0]['id']].update(status='pass', evidence_ids=['unknown'])
    assert not evaluate(case, reviews=reviews)['overall_pass']


def test_saved_run_infers_profile_and_keeps_output(case, tmp_path, monkeypatch):
    monkeypatch.setattr(run_report, 'save_sections', lambda *a: None)
    monkeypatch.setattr(run_report, 'process_ticker', lambda *a: None)
    client = mock_client(case.report)
    directory, result = run_report.run_baseline(snapshot_path=case.snapshot, profile=case.profile,
                                               client=client, reports_dir=tmp_path/'reports')
    before = (directory/'generated.json').read_bytes()
    assert result['automatic_pass']
    assert run_report.main(['--evaluate-run',str(directory)]) == 2
    assert (directory/'generated.json').read_bytes() == before
    assert json.loads((directory/'run.json').read_text())['profile'] == case.profile
    client.responses.create.assert_called_once()
    wrong = SECOND if case.profile == DEFAULT_PROFILE else DEFAULT_PROFILE
    assert run_report.main(['--evaluate-run',str(directory),'--profile',wrong]) == 1


@pytest.mark.parametrize('profile', [key for key in PROFILES if key.startswith('msft_')])
def test_cached_sec_tables_independently_match_oracle(profile):
    c = get_profile(profile)
    paths = sorted((Path('data/raw/sec/filings/MSFT')/c['report']['accession']).glob('*.html'))
    if not paths: pytest.skip('Official snapshot not cached; never fetch in tests')
    payload, meta = parse_filings.load_latest_snapshot('MSFT',form='10-Q',accession=c['report']['accession'],snapshot_path=paths[0])
    sections = store_filings.prepare_sections('MSFT',form='10-Q',accession=c['report']['accession'],snapshot_path=paths[0])
    evidence = build_report_evidence(sections, meta, profile=profile)
    gt = load_report_dataset(profile)
    # Independent HTML-cell read, separate from normalized section/evaluator row logic.
    soup = BeautifulSoup(payload,'lxml')
    for m in gt['metrics']:
        label = c['metrics'][m['id']][0]
        segment = m['id'].endswith('_revenue')
        matches=[]
        for table in soup.find_all('table'):
            text=table.get_text(' ',strip=True)
            if segment and label not in text: continue
            if not segment and not all(x in text for x in ('Total revenue','Operating income','Net income','Diluted')): continue
            seen = not segment
            for row in table.find_all('tr'):
                cells = [x.get_text(' ',strip=True) for x in row.find_all(['td','th'],recursive=False)]
                cells = [x for x in cells if x and x != '$']
                if label in cells: seen=True
                if seen and cells and cells[0] == ('Revenue' if segment else label):
                    amounts=[x.replace(',','') for x in cells[1:] if re.fullmatch(r'\d[\d,]*(?:\.\d+)?',x)]
                    if len(amounts)==2: matches.append(amounts)
                    if segment: break
        assert [m['current']['value'],m['prior']['value']] in matches
        assert any((row:=_source_row(e,m['id'],profile=profile)) and [str(x) for x in row[1]] == [m['current']['value'],m['prior']['value']] for e in evidence)


def test_approved_m002_evidence_and_result_are_reproduced_read_only():
    directory=Path('evals/reports/m002/20261029T182225Z_684dec81')
    if not directory.exists(): pytest.skip('Approved private run not present')
    hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in directory.iterdir() if p.is_file()}
    read=lambda name:json.loads((directory/name).read_text(encoding='utf-8'))
    source=read('source.json')
    evidence=build_report_evidence(read('sections.json'),source)
    assert evidence == read('evidence.json')
    result=evaluate_report(read('generated.json'),evidence,read('ground_truth.json'),source_sha256=source['sha256'],reviews=read('review.json'))
    assert result['overall_pass'] and result['financial_values']['passed']==12
    assert hashes == {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in directory.iterdir() if p.is_file()}

@pytest.mark.parametrize('index,field', [(5,'yoy_percent'),(0,'yoy_percent')])
def test_wrong_yoy_is_not_tolerated(case, index, field):
    # Includes the live FY2026 Q1 Intelligent Cloud error: 28.3 instead of 28.2.
    case.report['metrics'][index][field] = '28.3' if case.profile == SECOND and index == 5 else '999.9'
    result = evaluate(case)
    assert result['financial_values']['passed'] == len(case.report['metrics'])*2
    assert result['yoy_changes']['passed'] == len(case.report['metrics'])-1
    assert not result['automatic_pass']


def test_modified_empty_table_cells_are_not_verbatim_quotes(case):
    # Preserve the live failure: do not normalize away invented empty table cells.
    metric = case.report['metrics'][-1]
    e = next(e for e in case.evidence if e['label'] == 'segment_table')
    row = _source_row(e, metric['id'], profile=case.profile)[0]
    label = case.config['metrics'][metric['id']][0]
    metric['citations'][0]['quote'] = f'| {label} |\n| | | | | | | | | | | | | | | | | | | |\n{row}'
    result = evaluate(case)
    assert not result['quote_membership_pass']
    assert result['table_evidence_support']['passed'] == len(case.report['metrics'])-1
    assert not result['automatic_pass']


@pytest.mark.parametrize('boundary_index', range(4))
def test_missing_end_boundaries_rejected(case, boundary_index):
    _, item, _, ending, _ = case.config['boundaries'][boundary_index]
    section = next(s for s in case.sections if s['item'] == item)
    section['text'] = re.sub(ending,'MISSING END',section['text'],flags=re.I)
    with pytest.raises(ValueError,match='evidence missing'):
        build_report_evidence(case.sections,case.metadata,profile=case.profile)


@pytest.mark.parametrize('corruption', ['unit','gaap','url','columns','page','period','duplicate','nonfinite','income_order','review'])
def test_report_oracle_validation_retains_strict_requirements(case, corruption):
    data = case.gt
    if corruption == 'unit': data['metrics'][0]['unit'] = 'USD billions'
    elif corruption == 'gaap': data['metrics'][0]['gaap_status'] = 'non-GAAP'
    elif corruption == 'url': data['metrics'][0]['source']['url'] = 'https://example.com'
    elif corruption == 'columns': data['metrics'][0]['source']['columns'] = 'reversed columns'
    elif corruption == 'page': data['metrics'][0]['source']['page'] = None
    elif corruption == 'period': data['metrics'][0]['prior']['period'] = {'end':'2020-09-30'}
    elif corruption == 'duplicate': data['metrics'].append(data['metrics'][0])
    elif corruption == 'nonfinite': data['metrics'][0]['current']['value'] = 'NaN'
    elif corruption == 'income_order': data['metrics'][2]['current']['value'] = '999999'
    elif corruption == 'review': data['qualitative_review_cases'][0]['status'] = 'pass'
    with pytest.raises(ValueError): validate_report_dataset(data,case.profile)


def test_archived_profile_tampering_is_rejected(case, tmp_path, monkeypatch):
    monkeypatch.setattr(run_report,'save_sections',lambda *a:None)
    monkeypatch.setattr(run_report,'process_ticker',lambda *a:None)
    directory,_=run_report.run_baseline(snapshot_path=case.snapshot,profile=case.profile,
                                      client=mock_client(case.report),reports_dir=tmp_path/'reports')
    path=directory/'profile.json'
    saved=json.loads(path.read_text())
    saved['report']['prior_end']='2020-09-30'
    path.write_text(json.dumps(saved))
    with pytest.raises(ValueError,match='Saved profile'):
        run_report.reevaluate(directory)
