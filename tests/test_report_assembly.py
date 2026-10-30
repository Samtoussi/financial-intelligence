"""Deterministic assembly and unchanged saved-run regressions."""
import copy
import hashlib
import json
from decimal import Decimal
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from openai.lib._pydantic import _ensure_strict_json_schema
from test_report_profiles import case, SECOND
from test_report_pipeline import mock_client
from src.ai import report_assembly as a
from src.evaluation.report_evaluation import evaluate_report
from evals import run_report


def narrative(prepared, profile):
    return {'notes':[{'id':nid,'text':'Controlled interpretation awaiting human review.',
                     'span_ids':[s['span_id'] for s in prepared['spans'] if s['claim_id']==nid]}
                    for nid in a.get_profile(profile)['topics']]}


def test_round_once():
    assert a.growth(Decimal('30897'),Decimal('24092'))=='28.2'
    assert a.growth(Decimal('11245'),Decimal('10000'))=='12.5'


def test_offline_assembly(case,tmp_path,monkeypatch):
    prepared=a.prepare(case.evidence,case.profile)
    raw=narrative(prepared,case.profile)
    result=a.assemble(raw,case.evidence,case.profile,prepared)
    evaluation=evaluate_report(result,case.evidence,case.gt,source_sha256=case.metadata['sha256'],profile=case.profile)
    assert evaluation['automatic_pass'] and not evaluation['overall_pass']
    assert len(prepared['numeric_provenance'])==2*len(result['metrics'])
    for s in prepared['spans']:
        e=next(e for e in case.evidence if e['evidence_id']==s['evidence_id'])
        assert s['quote'].encode()==e['text'][s['start_char']-e['start_char']:s['end_char']-e['start_char']].encode()
    assert prepared==a.prepare(case.evidence,case.profile)
    monkeypatch.setattr(run_report,'save_sections',lambda *args:None)
    monkeypatch.setattr(run_report,'process_ticker',lambda *args:None)
    client=mock_client(raw)
    directory,evaluation=run_report.run_baseline(snapshot_path=case.snapshot,profile=case.profile,
        generation_mode=a.MODE,client=client,reports_dir=tmp_path/'runs')
    assert evaluation['automatic_pass'] and not evaluation['overall_pass']
    assert json.loads((directory/'raw_llm.json').read_text())==raw
    assert json.loads((directory/'generated.json').read_text())==result
    assert all(r['status']=='pending_manual_review' for r in evaluation['manual_reviews'])
    payload=json.loads(client.responses.create.call_args.kwargs['input'])
    assert 'ground_truth' not in payload
    assert json.loads((directory/'output_schema.json').read_text()) == client.responses.create.call_args.kwargs['text']['format']
    assert json.loads((directory/'allowed_span_ids.json').read_text()) == a.allowed_span_ids(prepared, case.profile)
    assert run_report.reevaluate(directory)['automatic_pass']


@pytest.mark.parametrize('corruption',['duplicate','missing','period','unsupported','identity','hash'])
def test_source_rejections(case,corruption):
    e=case.evidence[0]
    if corruption=='duplicate':
        row=next(x for x in e['text'].splitlines() if 'Total revenue |' in x)
        e['text']+='\n'+row
    elif corruption=='missing':e['text']=e['text'].replace('Total revenue','Unknown revenue')
    elif corruption=='period':e['text']=e['text'].replace(case.config['report']['prior_end'][:4],'2020')
    elif corruption=='unsupported':e['text']=e['text'].replace('Total revenue |','Total revenue | N/A |')
    elif corruption=='identity':e['source_sha256']='b'*64
    elif corruption=='hash':e['text_sha256']='b'*64
    if corruption!='hash':
        e['end_char']=e['start_char']+len(e['text'])
        e['text_sha256']=hashlib.sha256(e['text'].encode()).hexdigest()
    with pytest.raises(ValueError):a.prepare(case.evidence,case.profile)


@pytest.mark.parametrize('corruption',['unknown','unsupported','identity'])
def test_span_rejections(case,corruption):
    prepared=a.prepare(case.evidence,case.profile)
    raw=narrative(prepared,case.profile)
    if corruption=='unknown':raw['notes'][0]['span_ids']=['unknown']
    elif corruption=='unsupported':raw['notes'][0]['span_ids']=[prepared['spans'][0]['span_id']]
    else:prepared['spans'][0]['accession']='wrong'
    with pytest.raises(ValueError):a.assemble(raw,case.evidence,case.profile,prepared)


def test_raw_saved_before_failed_assembly(case,tmp_path):
    saved={}
    raw=narrative(a.prepare(case.evidence,case.profile),case.profile)
    raw['notes'][0]['span_ids']=['unknown']
    with pytest.raises(ValueError):a.generate(case.evidence,case.profile,client=mock_client(raw),save=lambda k,v:saved.update({k:v}))
    assert saved['raw_llm.json']==raw and 'raw_llm_text.json' in saved and 'raw_response.json' in saved


def test_failed_live_artifact_still_fails_read_only():
    directory=Path('evals/reports/m003/20261030T190009Z_b7b34556')
    if not directory.exists():pytest.skip('Saved private artifact unavailable')
    before={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in directory.iterdir() if p.is_file()}
    read=lambda name:json.loads((directory/name).read_text(encoding='utf-8'))
    result=evaluate_report(read('generated.json'),read('evidence.json'),read('ground_truth.json'),
        source_sha256=read('source.json')['sha256'],profile=SECOND)
    assert result['financial_values']['passed']==14
    assert result['yoy_changes']['passed']==6 and result['table_evidence_support']['passed']==6
    assert not result['quote_membership_pass'] and not result['automatic_pass']
    assert before=={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in directory.iterdir() if p.is_file()}

@pytest.mark.parametrize('profile,folder',[
    ('msft_fy2027_q1','evals/reports/m002/20261029T182225Z_684dec81'),
    (SECOND,'evals/reports/m003/20261030T190009Z_b7b34556')])
def test_cached_source_assembly(profile,folder):
    directory=Path(folder)
    if not directory.exists():pytest.skip('Private cached source unavailable')
    read=lambda name:json.loads((directory/name).read_text(encoding='utf-8'))
    evidence=read('evidence.json')
    prepared=a.prepare(evidence,profile)
    assembled=a.assemble(narrative(prepared,profile),evidence,profile,prepared)
    result=evaluate_report(assembled,evidence,read('ground_truth.json'),
        source_sha256=read('source.json')['sha256'],profile=profile)
    assert result['automatic_pass'] and not result['overall_pass']


def test_topic_contract_matches_registry_and_api_schema(case):
    prepared = a.prepare(case.evidence, case.profile)
    allowed = a.allowed_span_ids(prepared, case.profile)
    numeric_ids = {s['span_id'] for s in prepared['spans']
                   if s['claim_id'] in case.config['metrics']}
    raw = narrative(prepared, case.profile)
    client = mock_client(raw)
    saved = {}
    assembled, generation = a.generate(case.evidence, case.profile, client=client,
                                      save=lambda name, value: saved.update({name: value}))
    sent = client.responses.create.call_args.kwargs
    payload = json.loads(sent['input'])
    assert set(allowed) == set(case.config['topics'])
    for topic in payload['interpretation_topics']:
        expected = [s['span_id'] for s in prepared['spans'] if s['claim_id'] == topic['id']]
        assert topic['allowed_span_ids'] == expected == allowed[topic['id']]
        assert topic['question'] == case.config['topics'][topic['id']]
        assert not numeric_ids.intersection(expected)
    assert "claim_id must equal the note's id" in sent['instructions']
    assert "only span_ids in that topic's allowed_span_ids" in sent['instructions']
    assert "cannot serve as qualitative-note citations unless explicitly bound" in sent['instructions']
    schema = sent['text']['format']
    assert schema == saved['output_schema.json'] == a.schema_for(case.profile, allowed)
    assert saved['allowed_span_ids.json'] == allowed
    assert generation['prompt_version'] == a.PROMPT_VERSION
    body = schema['schema']
    for variant in body['properties']['notes']['items']['anyOf']:
        props = variant['properties']
        nid, = props['id']['enum']
        assert props['span_ids']['items']['enum'] == allowed[nid]
    Draft202012Validator.check_schema(body)
    Draft202012Validator(body).validate(raw)
    assert body['type'] == 'object' and 'anyOf' not in body
    assert _ensure_strict_json_schema(copy.deepcopy(body), path=(), root=copy.deepcopy(body)) == body
    supported = {'type', 'properties', 'required', 'additionalProperties', 'items',
                 'minItems', 'maxItems', 'anyOf', 'enum'}

    def check_subset(node):
        assert set(node).issubset(supported)
        if node.get('type') == 'object':
            assert node['additionalProperties'] is False
            assert set(node['required']) == set(node['properties'])
        for child in node.get('properties', {}).values():
            check_subset(child)
        if 'items' in node:
            check_subset(node['items'])
        for branch in node.get('anyOf', []):
            check_subset(branch)

    check_subset(body)
    result = evaluate_report(assembled, case.evidence, case.gt,
                             source_sha256=case.metadata['sha256'], profile=case.profile)
    assert result['automatic_pass'] and not result['overall_pass']
    assert all(r['status'] == 'pending_manual_review' for r in result['manual_reviews'])


@pytest.mark.parametrize('corruption', ['wrong_topic', 'numeric', 'unknown', 'missing',
                                         'duplicate', 'unknown_topic'])
def test_contract_and_assembler_reject_invalid_notes(case, corruption):
    prepared = a.prepare(case.evidence, case.profile)
    allowed = a.allowed_span_ids(prepared, case.profile)
    raw = narrative(prepared, case.profile)
    if corruption == 'wrong_topic':
        raw['notes'][0]['span_ids'] = raw['notes'][1]['span_ids'][:]
    elif corruption == 'numeric':
        raw['notes'][0]['span_ids'] = [prepared['spans'][0]['span_id']]
    elif corruption == 'unknown':
        raw['notes'][0]['span_ids'] = ['unknown']
    elif corruption == 'missing':
        raw['notes'].pop()
    elif corruption == 'duplicate':
        raw['notes'][1] = copy.deepcopy(raw['notes'][0])
    else:
        raw['notes'][0]['id'] = 'unknown_topic'
    validator = Draft202012Validator(a.schema_for(case.profile, allowed)['schema'])
    # Array uniqueness by topic remains an application responsibility.
    assert validator.is_valid(raw) == (corruption == 'duplicate')
    with pytest.raises(ValueError):
        a.assemble(raw, case.evidence, case.profile, prepared)


def test_missing_eligible_topic_fails_closed(case):
    prepared = a.prepare(case.evidence, case.profile)
    prepared['spans'] = [s for s in prepared['spans'] if s['claim_id'] != next(iter(case.config['topics']))]
    with pytest.raises(ValueError, match='Missing eligible'):
        a.allowed_span_ids(prepared, case.profile)
    with pytest.raises(ValueError, match='Missing eligible'):
        a.schema_for(case.profile, {})


def test_saved_contract_failure_remains_rejected_read_only():
    directory = Path('evals/reports/m003/20261030T210941Z_60e7f993')
    if not directory.exists():
        pytest.skip('Saved private response unavailable')
    before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
              for p in directory.iterdir() if p.is_file()}
    read = lambda name: json.loads((directory / name).read_text(encoding='utf-8'))
    prepared, raw = read('assembly_inputs.json'), read('raw_llm.json')
    assert prepared == a.prepare(read('evidence.json'), SECOND)
    body = a.schema_for(SECOND, a.allowed_span_ids(prepared, SECOND))['schema']
    assert not Draft202012Validator(body).is_valid(raw)
    with pytest.raises(ValueError, match='unsupported claim span ID'):
        a.assemble(raw, read('evidence.json'), SECOND, prepared)
    assert before == {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                      for p in directory.iterdir() if p.is_file()}


def test_m002_default_contract_matches_archived_run():
    from src.ai.report_generator import instructions_for, output_schema
    directory = Path('evals/reports/m002/20261029T182225Z_684dec81')
    if not directory.exists():
        pytest.skip('Approved private run unavailable')
    assert instructions_for() == (directory / 'instructions.txt').read_text(encoding='utf-8')
    assert output_schema() == json.loads((directory / 'output_schema.json').read_text(encoding='utf-8'))
