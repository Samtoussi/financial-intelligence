"""M005 unit regression: exact defective model text, never an approved response."""
import copy
import hashlib
import json
from pathlib import Path

import pytest

from test_cat_report import cat_case, PROFILE
from src.ai import report_assembly as assembly
from src.analytics.narrative_money import validate_monetary_narrative
from src.evaluation.report_evaluation import evaluate_report

FIXTURE = Path('tests/fixtures/cat_m005_defective_notes.json')
HISTORICAL = Path('evals/reports/m005/live/20261031T122747Z_afd425eb')


def defective_notes():
    return json.loads(FIXTURE.read_text(encoding='utf-8'))


def quote(case):
    return [e['text'] for e in case.evidence if e['label']=='management_summary']


def bind_fixture(case):
    # Preserve exact saved model wording. Test-excerpt source hashes have their
    # own registry IDs, so bind only IDs, never change the negative-case text.
    raw=defective_notes()
    for note in raw['notes']:
        note['span_ids']=[s['span_id'] for s in case.prepared['spans'] if s['claim_id']==note['id']]
    return raw


def test_exact_saved_response_rejected(cat_case):
    raw=bind_fixture(cat_case)
    checks=[validate_monetary_narrative(n['text'],quote(cat_case)) for n in raw['notes']]
    assert [c['automatic_pass'] for c in checks]==[False,True,True]
    assert [e['text'] for e in checks[0]['errors']]==['$41','$33']
    assert [c['text'] for c in checks[0]['claims'] if c['source_supported']]==[
        '$5.47','$4.20','$5.54','$4.25','$0.07','$0.05']
    before=copy.deepcopy(raw)
    with pytest.raises(ValueError,match='Unsupported narrative monetary units: gaap_vs_non_gaap'):
        assembly.assemble(raw,cat_case.evidence,PROFILE)
    assert raw==before


@pytest.mark.parametrize('text', [
    'Restructuring costs were $41 million and $33 million.',
    'Restructuring costs were $41 and $33 million.',
    'Restructuring costs were $41 million and $33.',
    'Restructuring costs were $41 in 2026 and $33 million in 2025.',
    'Restructuring costs (USD millions) were $41 and $33.',
    'Restructuring costs (in USD millions) were $41 and $33.',
    'Restructuring costs were USD 41 million and USD 33 million.',
    'Restructuring costs were 41 million dollars and 33 million dollars.',
    'Restructuring costs were $41,000,000 and $33,000,000.',
    'Restructuring costs were 41000000 dollars and 33000000 dollars.',
    'Restructuring costs were $0.041 billion and $0.033 billion.',
    'Restructuring costs were $41M and $33m.',
    'Profit before taxes was $3,211 million versus $2,570 million.',
    'GAAP diluted EPS was $5.47 versus $4.20.',
    'Profit per share was $5.47 in Q1 2026 and $4.20 in Q1 2025.',
    'Adjusted EPS was $5.54 versus $4.25.',
    'The adjustments were $0.07 and $0.05 per share.',
    'The per-share impacts were $0.07 per-share and $0.05 per\u2011share.',
    '$5.47 diluted EPS compares with $4.20 diluted EPS.',
    'EPS was $5.47, including restructuring costs of $41 million ($0.07 per share).',
    'Higher sales volume of $2.3 billion and favorable price realization of $426 million contributed to growth.',
    'Revenue increased $3.166 billion (22%).',
    'Operating profit margin was 17.7 percent versus 18.1 percent.',
    'Sales increased 22% and EPS increased 30.2%.',
    '2025 segment figures were retrospectively adjusted for the 2026 presentation.',
])
def test_valid_wording(cat_case,text):
    result=validate_monetary_narrative(text,quote(cat_case))
    assert result['automatic_pass'],result


@pytest.mark.parametrize('text', [
    'Restructuring costs were $41 and $33.',
    'Restructuring costs were USD 41 and USD 33.',
    'Restructuring costs were 41 dollars and 33 dollars.',
    'Restructuring costs were $41 billion and $33 million.',
    'Restructuring costs were $41 thousand and $33 million.',
    'Restructuring costs were $41 per share.',
    'Restructuring costs were $41 in 2026 (a $0.07 per-share impact).',
    'EPS was $5.47. Restructuring costs were $41.',
    'Costs were $41. Elsewhere, EPS was $5.47.',
    'EPS was $5.47; restructuring costs were $41.',
    'Costs (USD millions) were $41. Other costs were $33.',
    'EPS was $5.47 million.',
    'EPS was $41 million.',
    'The adjustment was $41 million per share.',
    'The adjustment was $0.07 million.',
    'Costs were $42 million.',
    'Costs were $4,1 million.',
    'Costs were $unknown.',
])
def test_ambiguous_or_unsupported_wording(cat_case,text):
    assert not validate_monetary_narrative(text,quote(cat_case))['automatic_pass']


def test_only_cited_units_count(cat_case):
    assert not validate_monetary_narrative('Costs were $41 million.',[])['automatic_pass']
    source=quote(cat_case)[0].replace('Dollars in millions except per share data','Dollars in thousands except per share data')
    assert not validate_monetary_narrative('Costs were $41 million.',[source])['automatic_pass']
    # A quote containing numeric cells but no dimensional header is insufficient.
    assert not validate_monetary_narrative('Costs were $41 million.',[
        '| Restructuring (income) costs | 41 | 0.07 | 33 | 0.05 |'])['automatic_pass']


def test_evaluator_rejects_without_assembly_and_cannot_be_overridden(cat_case):
    c=cat_case
    report=copy.deepcopy(c.report)
    report['notes'][0]['text']=defective_notes()['notes'][0]['text']
    reviews={n['id']:{'status':'pass','reviewer':'Synthetic test only',
        'rationale':'Cannot override automatic unit rejection.',
        'evidence_ids':[x['evidence_id'] for x in n['citations']]} for n in report['notes']}
    result=evaluate_report(report,c.evidence,c.gt,source_sha256=c.source['sha256'],profile=PROFILE,reviews=reviews)
    assert not result['automatic_pass'] and not result['overall_pass']
    assert result['evaluation_version']=='m005-eval-v3'
    assert result['financial_values']=={'passed':16,'total':16}
    assert result['yoy_changes']=={'passed':8,'total':8}
    assert result['table_evidence_support']=={'passed':8,'total':8}
    assert result['reconciliation']['passed']==48
    assert result['citation_integrity_pass'] and result['quote_membership_pass']
    assert not result['narrative_monetary_units']['automatic_pass']


def test_valid_note_assembles_and_evaluates_without_approving(cat_case):
    c=cat_case
    raw=bind_fixture(c)
    # Test-only candidate. Never write this replacement to historical artifacts.
    raw['notes'][0]['text']=raw['notes'][0]['text'].replace('$41 in','$41 million in').replace('$33 in','$33 million in')
    report=assembly.assemble(raw,c.evidence,PROFILE)
    result=evaluate_report(report,c.evidence,c.gt,source_sha256=c.source['sha256'],profile=PROFILE)
    assert result['automatic_pass'] and not result['overall_pass']
    assert result['narrative_monetary_units']['automatic_pass']
    assert report['notes'][0]['text']==raw['notes'][0]['text']
    assert report['notes'][0]['citations']==c.report['notes'][0]['citations']


def test_saved_source_read_only_negative_when_available():
    if not HISTORICAL.exists(): pytest.skip('Private historical run unavailable; exact text fixture still runs')
    before={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in HISTORICAL.iterdir() if p.is_file()}
    read=lambda name:json.loads((HISTORICAL/name).read_text(encoding='utf-8'))
    assert FIXTURE.read_bytes()==(HISTORICAL/'raw_llm.json').read_bytes()
    result=evaluate_report(read('generated.json'),read('evidence.json'),read('ground_truth.json'),
        source_sha256=read('source.json')['sha256'],profile=PROFILE)
    assert not result['automatic_pass'] and read('evaluation.json')['automatic_pass']
    with pytest.raises(ValueError,match='Unsupported narrative monetary units'):
        assembly.assemble(read('raw_llm.json'),read('evidence.json'),PROFILE,read('assembly_inputs.json'))
    from src.analytics.investor_report import load_evaluated_run, GateError
    with pytest.raises(GateError): load_evaluated_run(HISTORICAL,allow_pending_review=True)
    assert before=={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in HISTORICAL.iterdir() if p.is_file()}


def test_prompt_version_isolated_to_cat():
    assert assembly.prompt_version(PROFILE)=='m005-assembly-v2'
    assert 'write $41 million, not $41' in assembly.instructions_for(PROFILE)
    for profile in ('msft_fy2026_q1','msft_fy2027_q1'):
        assert assembly.instructions_for(profile)==assembly.INSTRUCTIONS
        assert assembly.prompt_version(profile)==assembly.PROMPT_VERSION


def test_separate_diagnostic_never_overwrites_history(tmp_path):
    if not HISTORICAL.exists(): pytest.skip('Private historical run unavailable')
    from evals.check_cat_narrative import diagnose
    before={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in HISTORICAL.iterdir() if p.is_file()}
    output,diagnostic=diagnose(HISTORICAL,tmp_path/'diagnostics')
    assert diagnostic['assembly_rejected'] and not diagnostic['current_automatic_pass']
    assert diagnostic['saved_evaluation_version']=='m005-eval-v1'
    assert diagnostic['saved_automatic_pass']
    assert json.loads((output/'evaluation.json').read_text(encoding='utf-8'))['evaluation_version']=='m005-eval-v3'
    assert before=={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in HISTORICAL.iterdir() if p.is_file()}
    with pytest.raises(ValueError,match='separate'):
        diagnose(HISTORICAL,HISTORICAL/'diagnostic')
