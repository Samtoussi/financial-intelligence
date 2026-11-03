"""Offline CLI projection of explicit MSFT, CAT and JPM evaluation contracts."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from test_jpm_ai import case as jpm_case
from test_report_profiles import case as msft_case
from test_cat_report import cat_case
from evals import run_report as runner
from src.ai import report_assembly as assembly
from src.evaluation.report_evaluation import evaluate_report, evaluate_banking_report


def banking_evaluation(case):
    report = assembly.assemble(case.raw,case.evidence,'jpm_2026_q2')
    return evaluate_banking_report(report,case.raw,case.evidence,case.extraction,case.gt,
        payload=case.payload,metadata=case.metadata)


def invoke(monkeypatch, result, profile):
    generated = Mock(return_value=(Path('offline-cli-run'), result))
    monkeypatch.setattr(runner, 'run_baseline', generated)
    return runner.main(['--profile',profile,'--generation-mode','m003-v2']), generated


@pytest.fixture
def saved_jpm_run(tmp_path, monkeypatch):
    directory = tmp_path / 'jpm-run'
    directory.mkdir()
    accession = assembly.get_profile('jpm_2026_q2')['report']['accession']
    # Deliberately no MSFT/CAT sections or evidence: reject before reading them.
    for name, value in {
        'source.json': {'accession': accession},
        'run.json': {'profile': 'jpm_2026_q2', 'status': 'failed_preserved', 'overall_pass': False},
        'evaluation.json': {'automatic_pass': False, 'overall_pass': False},
        'presentation_evaluation.json': {'automatic_pass': False},
        'live_attempt.json': {'attempt_count': 1},
    }.items():
        (directory / name).write_text(json.dumps(value), encoding='utf-8')
    def forbidden(*args, **kwargs):
        pytest.fail('JPM rejection must not evaluate, generate, fetch or write artifacts')
    for name in ('write_json', 'build_report_evidence', 'evaluate_report', 'run_baseline', 'run_banking', 'fetch'):
        monkeypatch.setattr(runner, name, forbidden)
    return directory


@pytest.mark.parametrize('profile', [None, 'jpm_2026_q2', 'msft_fy2026_q1'])
def test_jpm_reevaluation_rejected_without_writes(saved_jpm_run, profile):
    before = {p.name: p.read_bytes() for p in saved_jpm_run.iterdir()}
    with pytest.raises(runner.UnsupportedJPMReevaluation, match='JPM --evaluate-run is not supported'):
        runner.reevaluate(saved_jpm_run, profile=profile, reviews={'unused': 'must not promote'})
    assert {p.name: p.read_bytes() for p in saved_jpm_run.iterdir()} == before


@pytest.mark.parametrize('profile', [None, 'jpm_2026_q2', 'msft_fy2026_q1'])
def test_jpm_evaluate_run_cli_has_actionable_rejection(saved_jpm_run, profile, capsys):
    before = {p.name: p.read_bytes() for p in saved_jpm_run.iterdir()}
    arguments = ['--evaluate-run', str(saved_jpm_run)]
    if profile is not None:
        arguments += ['--profile', profile]
    assert runner.main(arguments) == 1
    captured = capsys.readouterr()
    assert not captured.out
    assert 'JPM --evaluate-run is not supported' in captured.err
    assert 'evaluation.json' in captured.err and 'docs/operations.md' in captured.err
    assert 'Traceback' not in captured.err and 'KeyError' not in captured.err
    assert {p.name: p.read_bytes() for p in saved_jpm_run.iterdir()} == before


def test_jpm_cli_saved_response_with_generation_mocked(jpm_case,monkeypatch,capsys):
    saved = Path('evals/reports/m006/final-presentations/step5_20261031T174931Z_63f650d6')
    if (saved/'evaluation.json').exists():
        # Use the actual immutable attempt-2 replay locally; portable CI uses
        # the explicitly synthetic fixture through the same evaluator contract.
        result = json.loads((saved/'evaluation.json').read_text(encoding='utf-8'))
        original = json.loads((saved/'original_ai_output.txt').read_text(encoding='utf-8'))
        assert {n['id'] for n in original['notes']} == set(assembly.get_profile('jpm_2026_q2')['topics'])
    else:
        result = banking_evaluation(jpm_case)
    before = copy.deepcopy(result)
    code, generation = invoke(monkeypatch,result,'jpm_2026_q2')
    output = json.loads(capsys.readouterr().out)
    assert code == 2  # Automatic success retains the existing pending-review exit code.
    assert output['financial_values'] == {'passed':16,'total':16}
    assert output['yoy_changes'] == {'passed':6,'total':6}
    assert output['table_evidence_support'] == {'passed':8,'total':8}
    assert output['automatic_pass'] and not output['overall_pass']
    assert result == before
    generation.assert_called_once()


def test_msft_cli_output_is_unchanged(msft_case,monkeypatch,capsys):
    c=msft_case
    result=evaluate_report(c.report,c.evidence,c.gt,source_sha256=c.metadata['sha256'],profile=c.profile)
    code,_=invoke(monkeypatch,result,c.profile)
    output=json.loads(capsys.readouterr().out)
    assert code==2
    assert output=={'run_dir':'offline-cli-run',**{k:result[k] for k in
        ('financial_values','yoy_changes','table_evidence_support','automatic_pass','overall_pass')},
        'manual_reviews':{r['id']:r['status'] for r in result['manual_reviews']}}


def test_cat_cli_output_is_unchanged(cat_case,monkeypatch,capsys):
    c=cat_case
    result=evaluate_report(c.report,c.evidence,c.gt,source_sha256=c.source['sha256'],profile='cat_2026_q1')
    code,_=invoke(monkeypatch,result,'cat_2026_q1')
    output=json.loads(capsys.readouterr().out)
    assert code==2
    assert output['financial_values']==result['financial_values']
    assert output['yoy_changes']==result['yoy_changes']
    assert output['table_evidence_support']==result['table_evidence_support']


@pytest.mark.parametrize('corruption', ['none','version','financial','financial_version',
    'counter','counter_type','status','reviews','duplicate_reviews','source_gate','narrative','assembled_match','inconsistent_gate'])
def test_malformed_jpm_results_fail_explicitly(jpm_case,monkeypatch,capsys,corruption):
    result=banking_evaluation(jpm_case)
    if corruption=='none': result=None
    elif corruption=='version': result.pop('evaluation_version')
    elif corruption=='financial':
        # Top-level counters must not silently substitute for missing JPM data.
        result.update(result.pop('financial'))
        result['evaluation_version']='m006-ai-eval-v1'
    elif corruption=='financial_version': result['financial']['evaluation_version']='unknown'
    elif corruption=='counter': result['financial'].pop('financial_values')
    elif corruption=='counter_type': result['financial']['financial_values']['passed']='16'
    elif corruption=='status': result['automatic_pass']='true'
    elif corruption=='reviews': result.pop('manual_reviews')
    elif corruption=='duplicate_reviews': result['manual_reviews'].append(copy.deepcopy(result['manual_reviews'][0]))
    elif corruption=='source_gate': result.pop('source_context_pass')
    elif corruption=='narrative': result.pop('narrative')
    elif corruption=='assembled_match': result.pop('assembled_response_match')
    else: result['financial']['automatic_pass']=False
    code,_=invoke(monkeypatch,result,'jpm_2026_q2')
    captured=capsys.readouterr()
    assert code==1 and not captured.out
    assert 'Invalid evaluation result contract:' in captured.err


@pytest.mark.parametrize('corruption',['counter','version','reviews'])
def test_malformed_legacy_results_fail_explicitly(msft_case,monkeypatch,capsys,corruption):
    c=msft_case
    result=evaluate_report(c.report,c.evidence,c.gt,source_sha256=c.metadata['sha256'],profile=c.profile)
    if corruption=='counter': result.pop('yoy_changes')
    elif corruption=='version': result['evaluation_version']='m006-ai-eval-v1'
    else: result['manual_reviews']=None
    code,_=invoke(monkeypatch,result,c.profile)
    captured=capsys.readouterr()
    assert code==1 and 'Invalid evaluation result contract:' in captured.err


@pytest.mark.parametrize('automatic,overall,expected',[(False,False,1),(True,False,2),(True,True,0)])
def test_legacy_cli_exit_gates_are_unchanged(msft_case,monkeypatch,capsys,automatic,overall,expected):
    c=msft_case
    result=evaluate_report(c.report,c.evidence,c.gt,source_sha256=c.metadata['sha256'],profile=c.profile)
    result.update(automatic_pass=automatic,overall_pass=overall)
    code,_=invoke(monkeypatch,result,c.profile)
    assert code==expected


def test_failed_jpm_evaluation_cannot_assemble_or_render(jpm_case,monkeypatch):
    c=jpm_case
    forbidden=Mock(side_effect=AssertionError('Failed evaluation must not assemble'))
    monkeypatch.setattr(assembly,'assemble',forbidden)
    client=Mock()
    client.responses.create.return_value=SimpleNamespace(status='completed',
        output_text=json.dumps(c.raw),id='offline-rejected',usage=None)
    saved={}
    with pytest.raises(ValueError,match='Pre-assembly automatic evaluation rejected'):
        assembly.generate(c.evidence,'jpm_2026_q2',client=client,
            save=lambda name,value:saved.setdefault(name,value),
            validate_raw=lambda raw:{'automatic_pass':False})
    forbidden.assert_not_called()
    client.responses.create.assert_called_once()
    assert saved['raw_llm.json']==c.raw and 'raw_response.json' in saved


def test_jpm_failed_report_result_does_not_pass_cli(jpm_case,monkeypatch,capsys):
    result=banking_evaluation(jpm_case)
    result['narrative']['automatic_pass']=False
    result['assembled_response_match']=False
    result['automatic_pass']=False
    code,_=invoke(monkeypatch,result,'jpm_2026_q2')
    assert code==1 and not json.loads(capsys.readouterr().out)['automatic_pass']
