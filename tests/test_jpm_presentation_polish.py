"""Presentation-only JPM polish; original AI notes and SEC claims stay intact."""
import copy
import pytest
from test_jpm_ai import case
from src.ai import report_assembly as a
from src.analytics.investor_report import (presented_banking_note, build_banking_presentation,
    render_banking_main, render_banking_details, GateError)
from src.evaluation.investor_report import evaluate_banking_presentation
from src.evaluation.report_evaluation import evaluate_banking_report

CREDIT = ('Provision for credit losses (a quarterly flow) was $2.5 billion for April–June 2026, '
          'net charge‑offs (a quarterly flow) were $2.4 billion, resulting in a disclosed net addition '
          'to the allowance of $149 million for the quarter. The firmwide allowance for credit losses '
          '(a dated stock) was $31,531 million as of June 30, 2026; provision and charge‑offs are flows '
          'and are distinct from the allowance stock.')


def report_for(case):
    case.raw['notes'][1]['text'] = CREDIT + ' Defining source: credit_context.'
    return a.assemble(case.raw, case.evidence, 'jpm_2026_q2')


@pytest.mark.parametrize('topic,label', [('reported_vs_managed','reported_to_managed'),
    ('credit_loss_measures','credit_context'),('significant_earnings_items','significant_items')])
def test_only_validated_suffix_is_removed(case, topic, label):
    report = report_for(case)
    note = next(n for n in report['notes'] if n['id'] == topic)
    note['text'] = 'Original prose stays intact. Defining source: ' + label + '.'
    before = copy.deepcopy(report)
    assert presented_banking_note(note, report) == 'Original prose stays intact.'
    assert report == before


@pytest.mark.parametrize('suffix', ['fabricated_label.', 'income_statement.', 'credit_context.',
                                   'reported_to_managed', 'reported_to_managed. Extra prose.'])
def test_unsupported_or_non_suffix_annotation_is_never_removed(case, suffix):
    report = report_for(case);note = report['notes'][0]
    note['text'] = 'Original prose. Defining source: ' + suffix
    with pytest.raises(GateError): presented_banking_note(note, report)


def test_selected_citations_are_required_for_suffix_removal(case):
    report = report_for(case);note = report['notes'][0]
    note['text'] = 'Original prose. Defining source: reported_to_managed.'
    note['citations'] = []
    with pytest.raises(GateError): presented_banking_note(note, report)


def test_credit_polish_uses_exact_values_and_preserves_stock_and_audit(case):
    report = report_for(case);before = copy.deepcopy(report)
    note = report['notes'][1];result = presented_banking_note(note, report)
    assert 'rounded quarterly flows of $2.5 billion' in result
    assert '$2.4 billion net charge-offs' in result
    assert '$2,515M - $2,366M = $149M' in result
    assert 'not the inputs to that exact subtraction' in result
    assert CREDIT.split('The firmwide')[1] in result
    assert 'Defining source:' not in result
    assert report == before


@pytest.mark.parametrize('field,value', [('result','100'),('unit','USD billions')])
def test_polish_cannot_hide_changed_exact_financials(case, field, value):
    report = report_for(case)
    row = next(r for r in report['reconciliation'] if r['id']=='credit_net_addition:current')
    row[field] = value
    with pytest.raises(GateError): presented_banking_note(report['notes'][1], report)


def test_other_credit_wording_is_preserved(case):
    report = report_for(case);note = report['notes'][1]
    note['text'] = 'Provision expense is a quarterly flow; allowances are dated stocks.'
    assert presented_banking_note(note, report) == note['text']


def test_complete_polish_remains_independently_evaluated(case):
    report = report_for(case);before = copy.deepcopy(case.raw)
    view = build_banking_presentation(report,case.raw,case.extraction,case.payload,case.metadata)
    main = render_banking_main(report,view);detail = render_banking_details(report,view)
    evaluation = evaluate_banking_report(report,case.raw,case.evidence,case.extraction,case.gt,
        payload=case.payload,metadata=case.metadata)
    assert evaluation['automatic_pass']
    check = evaluate_banking_presentation(report,case.raw,case.extraction,view,main,detail,
        payload=case.payload,metadata=case.metadata,evaluation=evaluation)
    assert check['automatic_pass']
    assert 'Defining source:' not in main and 'Defining source:' not in detail
    assert '$2,515M - $2,366M = $149M' in main and '$2,515M - $2,366M = $149M' in detail
    assert case.raw == before
    tampered = main.replace('$31,531', '$26,152')
    assert not evaluate_banking_presentation(report,case.raw,case.extraction,view,tampered,detail,
        payload=case.payload,metadata=case.metadata,evaluation=evaluation)['automatic_pass']
    # Every rendered interpretation retains its structured SEC reference block.
    from src.analytics.investor_report import references, presented_banking_note
    for note in report['notes']:
        assert presented_banking_note(note,report) + '\n\n' + references(view,[note['id']]) in main
