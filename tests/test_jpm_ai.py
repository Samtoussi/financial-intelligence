"""Offline synthetic narrative tests. Never human approvals or live calls."""
import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.ai import report_assembly as a
from src.analytics import jpm_extraction as bank
from src.analytics.jpm_narrative import validate_notes
from src.analytics.investor_report import build_banking_presentation, render_banking_main, render_banking_details
from src.evaluation.report_evaluation import evaluate_banking_response, evaluate_banking_report
from src.evaluation.investor_report import evaluate_banking_presentation
from src.evaluation.ground_truth import load_dataset
from src.evaluation.jpm_ground_truth import DEFAULT_PATH

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT/'tests/fixtures'
CASES = load_dataset(FIXTURES/'jpm_m006_negative_notes.json')['cases']


@pytest.fixture
def case(monkeypatch):
    payload = (FIXTURES/'jpm_2026_q2_extraction.html').read_bytes()
    sha = hashlib.sha256(payload).hexdigest();monkeypatch.setattr(bank, 'SOURCE_SHA256', sha)
    metadata = {**bank.SOURCE, 'sha256':sha};extraction = bank.extract_jpm(payload, metadata)
    prepared = a.prepare(extraction['evidence'], 'jpm_2026_q2')
    texts = load_dataset(FIXTURES/'jpm_m006_positive_notes.json')['texts']
    raw = {'notes':[{'id':nid, 'text':t, 'span_ids':[s['span_id'] for s in prepared['spans'] if s['claim_id']==nid]} for nid,t in texts.items()]}
    return SimpleNamespace(payload=payload, metadata=metadata, extraction=extraction,
        evidence=extraction['evidence'], prepared=prepared, raw=raw, gt=load_dataset(DEFAULT_PATH))


def evaluate(c, raw=None):
    return evaluate_banking_response(c.raw if raw is None else raw, c.evidence, c.extraction, c.gt,
                                     payload=c.payload, metadata=c.metadata)


@pytest.mark.parametrize('c', CASES, ids=lambda c:c['id'])
def test_negative_fixture_is_rejected_before_assembly(case, c):
    next(n for n in case.raw['notes'] if n['id']==c['topic'])['text'] = c['negative']
    result = validate_notes(case.raw, case.prepared)
    assert not result['automatic_pass'], result
    assert any(c['rule'] in f for f in result['failures']), result
    with pytest.raises(ValueError, match='Banking narrative rejected'):
        a.assemble(case.raw, case.evidence, 'jpm_2026_q2')


@pytest.mark.parametrize('c', CASES, ids=lambda c:c['id'])
def test_every_rejection_rule_has_a_valid_positive_counterpart(case, c):
    next(n for n in case.raw['notes'] if n['id']==c['topic'])['text'] = c['positive']
    result = validate_notes(case.raw, case.prepared)
    assert result['automatic_pass'], result


@pytest.mark.parametrize('text', [
    'Diluted EPS was $7.70 in the quarter ended June 30, 2026 compared with $5.24 in 2025. The Visa-related net gain was $4.6 billion.',
    'Diluted EPS was $7.70 per share. Other equity investment gains were $1.0 billion.',
])
def test_valid_eps_and_aggregate_money_do_not_leak_units(case, text):
    case.raw['notes'][2]['text'] = text
    assert validate_notes(case.raw, case.prepared)['automatic_pass']


@pytest.mark.parametrize('text', [
    'Provision expense was $2.515 billion; net charge-offs were $2.366 billion.',
    'Provision expense was $2.5 billion; net charge-offs were $2.4 billion.',
    'Firmwide allowance balances were $31.531 billion at June 30, 2026.',
    'Total loans increased 3.3% since year-end; deposit liabilities increased 6.0% since year-end.',
])
def test_correct_accounting_scales_and_percentages_pass(case, text):
    case.raw['notes'][1]['text'] = text
    assert validate_notes(case.raw, case.prepared)['automatic_pass']


@pytest.mark.parametrize('kind', ['missing', 'unknown', 'cross_topic', 'duplicate', 'inline_reference', 'unsupported_number', 'wrong_accession'])
def test_citation_and_schema_errors_fail_closed(case, kind):
    if kind=='missing': case.raw['notes'][0]['span_ids']=[]
    if kind=='unknown': case.raw['notes'][0]['span_ids']=['fabricated']
    if kind=='cross_topic': case.raw['notes'][0]['span_ids']=case.raw['notes'][1]['span_ids']
    if kind=='duplicate': case.raw['notes'][1]=copy.deepcopy(case.raw['notes'][0])
    if kind=='inline_reference': case.raw['notes'][0]['text']='See [source](https://example.com).'
    if kind=='unsupported_number': case.raw['notes'][0]['text']='Revenue was $100 billion.'
    if kind=='wrong_accession':
        case.evidence[0]['accession']='0001628280-26-000000'
        with pytest.raises(ValueError): a.prepare(case.evidence, 'jpm_2026_q2')
        return
    assert not validate_notes(case.raw, case.prepared)['automatic_pass']


def test_exact_saved_replay_financial_authority_and_investor_rendering(case):
    result = evaluate(case);assert result['automatic_pass'] and not result['overall_pass'],result
    report = a.assemble(case.raw, case.evidence, 'jpm_2026_q2', case.prepared)
    assert report['metrics']==case.prepared['financial_foundation']['metrics']
    assert report['reconciliation']==case.prepared['financial_foundation']['reconciliation']
    result = evaluate_banking_report(report, case.raw, case.evidence, case.extraction, case.gt,
                                    payload=case.payload, metadata=case.metadata)
    assert result['automatic_pass']
    view = build_banking_presentation(report, case.raw, case.extraction, case.payload, case.metadata)
    main, detail = render_banking_main(report, view), render_banking_details(report, view)
    assert '## Executive summary' in main and 'AI-generated interpretation' in main
    assert 'Reported versus managed context' in main and 'Change since year-end' in main
    assert 'Principal allowance table total' not in main and 'Principal allowance table total' in detail
    assert case.raw['notes'][2]['text'] in main
    for altered in (main+'\nUnsupported claim.', main.replace('Change since year-end','YoY')):
        assert not evaluate_banking_presentation(report, case.raw, case.extraction, view, altered, detail,
            payload=case.payload, metadata=case.metadata, evaluation=result)['automatic_pass']
    assert evaluate_banking_presentation(report, case.raw, case.extraction, view, main, detail,
        payload=case.payload, metadata=case.metadata, evaluation=result)['automatic_pass']


def test_shared_generate_calls_once_persists_before_validation_and_has_no_oracle_context(case):
    raw_text=json.dumps(case.raw, indent=1)
    response=SimpleNamespace(status='completed',output_text=raw_text,id='synthetic-no-live-call',usage=None)
    client=Mock();client.responses.create.return_value=response
    saved={}
    def validate(raw):
        assert saved['raw_llm_text.json']==raw_text and saved['raw_llm.json']==case.raw
        return evaluate(case, raw)
    report, generation=a.generate(case.evidence,'jpm_2026_q2',client=client,save=lambda k,v:saved.setdefault(k,v),validate_raw=validate)
    assert client.responses.create.call_count==1
    packet=json.loads(client.responses.create.call_args.kwargs['input'])
    assert 'ground_truth' not in packet and 'oracle' not in json.dumps(packet)
    assert len(packet['spans'])==9 and len(report['notes'])==3
    assert generation['response_id']=='synthetic-no-live-call'
    allowed=a.allowed_span_ids(case.prepared,'jpm_2026_q2')
    assert {k:len(v) for k,v in allowed.items()}=={'reported_vs_managed':2,'credit_loss_measures':5,'significant_earnings_items':2}
    assert a.schema_for('jpm_2026_q2',allowed)['strict']


def test_failed_preassembly_callback_never_assembles_or_retries(case, monkeypatch):
    response=SimpleNamespace(status='completed', output_text=json.dumps(case.raw), id='synthetic-rejected', usage=None)
    client=Mock();client.responses.create.return_value=response;saved={}
    def forbidden(*args): raise AssertionError('Must not assemble rejected response')
    monkeypatch.setattr(a,'assemble',forbidden)
    with pytest.raises(ValueError,match='Pre-assembly'):
        a.generate(case.evidence,'jpm_2026_q2',client=client,save=lambda k,v:saved.setdefault(k,v),validate_raw=lambda r:{'automatic_pass':False})
    assert client.responses.create.call_count==1 and 'raw_response.json' in saved and 'raw_llm.json' in saved


def test_jpm_requires_callback_without_affecting_other_prompts(case):
    client=Mock()
    with pytest.raises(ValueError,match='independent'):
        a.generate(case.evidence,'jpm_2026_q2',client=client)
    client.responses.create.assert_not_called()
    for profile in ('msft_fy2026_q1','msft_fy2027_q1'):
        assert a.instructions_for(profile)==a.INSTRUCTIONS
    assert a.prompt_version('cat_2026_q1')=='m005-assembly-v2'


def test_current_prior_number_binding_and_defining_evidence(case):
    case.raw['notes'][0]['text']='GAAP reported revenue was $57.347 billion in 2025.'
    assert not validate_notes(case.raw,case.prepared)['automatic_pass']
    case.raw['notes'][0]['text']='GAAP reported revenue was $44.912 billion in 2025.'
    assert validate_notes(case.raw,case.prepared)['automatic_pass']
    case.raw['notes'][0]['span_ids']=[s['span_id'] for s in case.prepared['spans'] if s['claim_id']=='reported_vs_managed' and s['source_label']=='income_statement']
    assert not validate_notes(case.raw,case.prepared)['automatic_pass']


def test_chargeoff_values_require_their_actual_source_not_just_a_bridge_citation(case):
    n=case.raw['notes'][1];n['text']='Net charge-offs were $2.366 billion.'
    n['span_ids']=[s['span_id'] for s in case.prepared['spans'] if s['claim_id']==n['id'] and s['source_label'] in ('credit_context','income_statement')]
    assert not validate_notes(case.raw,case.prepared)['automatic_pass']
    n['span_ids'] += [s['span_id'] for s in case.prepared['spans'] if s['claim_id']==n['id'] and s['source_label']=='credit_highlights']
    assert validate_notes(case.raw,case.prepared)['automatic_pass']


@pytest.mark.parametrize('text',[
    'Net income includes a $4.6 billion Visa-related net gain.',
    'Results include a $4.6 billion Visa-related net gain and $1.0 billion of gains on certain equity investments.',
    'Diluted EPS was $7.70 alongside a $4.6 billion Visa-related net gain.',
])
def test_postfixed_embedded_items_do_not_inherit_the_headline_measure(case,text):
    case.raw['notes'][2]['text']=text
    assert validate_notes(case.raw,case.prepared)['automatic_pass']


def test_managed_basis_after_measure_is_valid_but_cannot_change_gaap_headline(case):
    case.raw['notes'][0]['text']='Net revenue on a managed basis was $58.022 billion.'
    assert validate_notes(case.raw,case.prepared)['automatic_pass']
    case.raw['notes'][0]['text']='GAAP reported net revenue was $58.022 billion.'
    assert not validate_notes(case.raw,case.prepared)['automatic_pass']


@pytest.mark.parametrize('accepted',[True,False])
def test_existing_runner_preserves_response_and_stops_on_rejection(case,tmp_path,monkeypatch,accepted):
    import evals.run_report as runner
    import src.evaluation.jpm_ground_truth as source_validation
    # Test-only original-source stub; real original checksum/table coverage is
    # independently exercised by test_jpm_ground_truth, not by these fake bytes.
    monkeypatch.chdir(ROOT);monkeypatch.setattr(runner,'ROOT',tmp_path)
    monkeypatch.setattr(source_validation,'verify_sources',lambda *args:{'source_verified':True,'test_fixture_only':True})
    gtpath=tmp_path/'evals/ground_truth/jpm_2026_q2.json';gtpath.parent.mkdir(parents=True)
    gtpath.write_text(json.dumps(case.gt),encoding='utf-8')
    for key,content in [('filing_detail_path','fixture detail'),('filing_detail_metadata_path','{}')]:
        p=tmp_path/case.gt['source_snapshot'][key];p.parent.mkdir(parents=True,exist_ok=True);p.write_text(content,encoding='utf-8')
    snapshot=tmp_path/'source.html';snapshot.write_bytes(case.payload)
    snapshot.with_suffix('.metadata.json').write_text(json.dumps(case.metadata),encoding='utf-8')
    if not accepted:case.raw['notes'][2]['text']='Visa gains are recurring operating earnings.'
    raw_text=json.dumps(case.raw,indent=3)
    response=SimpleNamespace(status='completed',output_text=raw_text,id='synthetic-runner-response',usage=None,
        model_dump=lambda:{'id':'synthetic-runner-response','status':'completed','output_text':raw_text})
    client=Mock();client.responses.create.return_value=response
    directory,result=runner.run_baseline(snapshot_path=snapshot,client=client,reports_dir=tmp_path/'outputs',
        profile='jpm_2026_q2',generation_mode=a.MODE)
    assert client.responses.create.call_count==1
    assert (directory/'raw_output.txt').read_bytes()==raw_text.encode()
    assert load_dataset(directory/'raw_llm_text.json')==raw_text
    assert load_dataset(directory/'raw_response.json')['id']=='synthetic-runner-response'
    assert (directory/'report.md').exists()==accepted and (directory/'generated.json').exists()==accepted
    assert load_dataset(directory/'response_evaluation.json')['automatic_pass']==accepted
    assert load_dataset(directory/'run.json')['status']==('completed_pending_review' if accepted else 'failed_preserved')
    assert not load_dataset(directory/'run.json')['live_model_call_attempted']

# Scoped M006 live-response regression cases; synthetic wording, no API calls.
FTE_SENTENCE = ('FTE adjustments increased total net revenue by $675 million to a managed total of '
                '$58,022 million (noninterest revenue +$564 million; net interest income +$111 million).')


@pytest.mark.parametrize('suffix,accepted', [
    ('Defining source: reported_to_managed.', True),
    ('An ordinary_identifier is descriptive.', True),
    ('Defining source: fabricated_label.', False),
    ('Defining source: income_statement.', False),
    ('Defining source: credit_context.', False),
    ('Source: reported_to_managed.', False),
    ('Reference: invented.', False),
    ('Defining source: reported_to_managed', False),
    ('See https://example.com.', False),
    ('See [invented].', False),
    ('An _emphasized_ claim.', False),
    ('An *emphasized* claim.', False),
])
def test_scoped_defining_source_annotations(case, suffix, accepted):
    case.raw['notes'][0]['text'] = 'Managed reporting does not change net income. ' + suffix
    assert validate_notes(case.raw, case.prepared)['automatic_pass'] == accepted


def test_annotation_does_not_replace_structured_citation(case):
    note = case.raw['notes'][0]
    note['text'] = 'Defining source: reported_to_managed.'
    note['span_ids'] = [s['span_id'] for s in case.prepared['spans']
                        if s['claim_id'] == note['id'] and s['source_label'] == 'income_statement']
    result = validate_notes(case.raw, case.prepared)
    assert not result['automatic_pass']
    assert any('Unsupported source label' in f for f in result['failures'])
    assert any('Missing topic-defining source' in f for f in result['failures'])


@pytest.mark.parametrize('text,accepted', [
    (FTE_SENTENCE, True),
    (FTE_SENTENCE.replace('$564', '$111').replace('$111 million)', '$564 million)'), False),
    (FTE_SENTENCE.replace('$675', '$564'), False),
    (FTE_SENTENCE.replace('$58,022', '$57,347'), False),
    (FTE_SENTENCE.replace('managed total', 'GAAP reported total'), False),
    ('GAAP reported net revenue was $58,022 million.', False),
    ('GAAP reported net revenue was $57,347 million.', True),
    ('FTE adjustments increased noninterest revenue by $564 million to a managed total of $32,400 million.', True),
    ('FTE adjustments increased net interest income by $111 million to a managed total of $25,622 million.', True),
    ('FTE adjustments increased noninterest revenue by $111 million to a managed total of $32,400 million.', False),
    ('FTE adjustments increased net interest income by $564 million to a managed total of $25,622 million.', False),
    ('FTE adjustments increased total net revenue by $768 million to a managed total of $45,680 million in 2025.', True),
    ('FTE adjustments increased total net revenue by $768 million to a managed total of $45,680 million in 2026.', False),
])
def test_fte_adjustment_measure_and_result_binding(case, text, accepted):
    case.raw['notes'][0]['text'] = text
    assert validate_notes(case.raw, case.prepared)['automatic_pass'] == accepted


@pytest.mark.parametrize('hyphen', ['-', '\u2010', '\u2011', '\u2012', '\u2013', ' '])
@pytest.mark.parametrize('swapped', [False, True])
def test_credit_hyphens_preserve_measure_identity(case, hyphen, swapped):
    provision, chargeoffs = ('$2.4', '$2.5') if swapped else ('$2.5', '$2.4')
    case.raw['notes'][1]['text'] = (f'Provision for credit losses was {provision} billion; '
                                  f'net charge{hyphen}offs were {chargeoffs} billion.')
    assert validate_notes(case.raw, case.prepared)['automatic_pass'] != swapped


@pytest.mark.parametrize('text,accepted', [
    ('Provision was $2.5 billion; net charge-offs were $2.4 billion; the disclosed net addition was $149 million.', True),
    ('Provision was $2.515 billion minus net charge-offs of $2.366 billion equals a net addition of $149 million.', True),
    ('Provision was $2.5 billion minus net charge-offs of $2.4 billion equals a net addition of $149 million.', False),
    ('Provision was $2.5 billion - net charge-offs of $2.4 billion = a net addition of $149 million.', False),
    ('Firmwide allowance was $31,531 million as of June 30, 2026.', True),
    ('Principal allowance total was $31,366 million as of June 30, 2026.', True),
    ('Loan allowance was $26,152 million as of June 30, 2026.', True),
    ('Firmwide allowance was $31,366 million as of June 30, 2026.', False),
    ('Principal allowance total was $31,531 million as of June 30, 2026.', False),
    ('Loan allowance was $31,531 million as of June 30, 2026.', False),
])
def test_credit_precision_and_allowance_scopes(case, text, accepted):
    case.raw['notes'][1]['text'] = text
    assert validate_notes(case.raw, case.prepared)['automatic_pass'] == accepted


def test_future_banking_instructions_use_structured_citations():
    assert 'Use structured span_ids for all citations.' in a.instructions_for('jpm_2026_q2')
    assert 'Do not add "Defining source: ..." labels' in a.instructions_for('jpm_2026_q2')

@pytest.mark.parametrize('value,accepted', [
    ('An ordinary_identifier.', True),
    ('Defining source: reported_to_managed.', True),
    ('An _emphasized_ statement.', False),
    ('A [reference].', False),
    ('A *bold* statement.', False),
])
def test_banking_renderer_preserves_only_safe_prose(value, accepted):
    from src.analytics.investor_report import banking_note_text, approved_note_text, GateError
    if accepted:
        assert banking_note_text({'text':value}) == value
        # Shared historic company behavior is unchanged.
        with pytest.raises(GateError): approved_note_text({'text':value})
    else:
        with pytest.raises(GateError): banking_note_text({'text':value})


def test_explicit_rounded_subtraction_yields_is_not_exact(case):
    case.raw['notes'][1]['text'] = ('Provision was $2.5 billion minus net charge-offs of $2.4 billion '
                                  'yields a disclosed net addition of $149 million.')
    result = validate_notes(case.raw, case.prepared)
    assert any('false_explicit_arithmetic' in f for f in result['failures'])
