"""M006 deterministic financial foundation; oracle expectations stay in evals."""
import copy
import hashlib
import json
from pathlib import Path

import pytest

from src.ai import report_assembly as assembly
from src.analytics import jpm_extraction as extraction
from src.analytics import investor_report as renderer
from src.evaluation.report_evaluation import evaluate_financials
from src.evaluation.investor_report import evaluate_financial_presentation
from src.evaluation.ground_truth import load_dataset
from src.evaluation.jpm_ground_truth import DEFAULT_PATH

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def case(monkeypatch):
    raw = (ROOT/'tests/fixtures/jpm_2026_q2_extraction.html').read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    monkeypatch.setattr(extraction, 'SOURCE_SHA256', sha)
    meta = {**extraction.SOURCE, 'sha256': sha}
    bundle = extraction.extract_jpm(raw, meta)
    report = assembly.assemble_financials(bundle, raw, meta)
    oracle = load_dataset(DEFAULT_PATH)
    return {'raw': raw, 'meta': meta, 'bundle': bundle, 'report': report, 'oracle': oracle}


def evaluate(c, report=None):
    return evaluate_financials(c['report'] if report is None else report, c['bundle'], c['oracle'],
                              payload=c['raw'], metadata=c['meta'])


def present(c):
    view = renderer.build_financial_presentation(c['report'], c['bundle'], c['raw'], c['meta'])
    return view, renderer.render_financial_main(view), renderer.render_financial_details(view)


def check_presentation(c, view, main, detail, gate=None):
    return evaluate_financial_presentation(c['report'], c['bundle'], view, main, detail,
        payload=c['raw'], metadata=c['meta'], financial_evaluation=evaluate(c) if gate is None else gate)


def test_all_values_changes_and_reconciliations_match_independent_oracle(case):
    result = evaluate(case)
    assert result['automatic_pass'], result
    assert result['financial_values'] == {'passed': 16, 'total': 16}
    assert result['yoy_changes'] == {'passed': 6, 'total': 6}
    assert result['since_year_end_changes'] == {'passed': 2, 'total': 2}
    assert result['period_unit_scope_checks'] == {'passed': 8, 'total': 8}
    assert result['table_evidence_support'] == {'passed': 8, 'total': 8}
    assert result['reconciliation'] == {'passed': 14, 'total': 14}
    assert not result['overall_pass']
    assert {r['status'] for r in result['manual_reviews']} == {'pending_manual_review'}
    assert case['report']['notes'] == []
    assert [m['change_percent'] for m in case['report']['metrics']] == ['27.7', '9.9', '46.7', '41.2', '46.9', '-11.7', '3.3', '6.0']
    assert all(m['scope'] and m['citations'] for m in case['report']['metrics'])
    assert evaluate(case, json.loads(json.dumps(case['report'])))['automatic_pass']


def test_exact_presentations_have_separate_comparisons_and_no_ai(case):
    view, main, detail = present(case)
    check = check_presentation(case, view, main, detail)
    assert check['automatic_pass'] and not check['overall_pass'], check
    assert '| Diluted EPS | 7.70 | 5.24 | +46.9% | USD per share |' in main
    assert '| Total loans before separately presented allowance | 1,542,462 | 1,493,429 | +3.3% | USD millions |' in main
    assert '$4.6 billion net gain related to Visa shares' in main
    assert 'GAAP reported' in main and 'Managed basis' in main
    assert 'not constitute a complete beginning-to-ending allowance rollforward' in main
    assert 'A lower provision alone does not establish improving credit quality.' in main
    assert 'Scope: Consolidated balance-sheet deposit liabilities' in detail
    assert '2026-04-01 to 2026-06-30' in detail and '2025-12-31' in detail
    assert '## Segment' not in main and 'CET1' not in main
    for metric in case['report']['metrics']:
        for cite in metric['citations']: assert cite['quote'] in detail


def change(obj, path, value):
    for key in path[:-1]: obj = obj[key]
    obj[path[-1]] = value


@pytest.mark.parametrize('path,value', [
    (('metrics', 0, 'current'), '107183'),  # Six-month revenue.
    (('metrics', 4, 'current'), '13.63'),  # Six-month EPS.
    (('metrics', 0, 'periods', 'current', 'start'), '2026-01-01'),
    (('metrics', 0, 'current'), '58022'),  # Managed revenue in GAAP headline.
    (('metrics', 0, 'gaap_status'), 'Managed'),
    (('metrics', 6, 'current'), '1516310'),  # Net loans.
    (('metrics', 6, 'source_label'), 'Retained loans, average'),
    (('metrics', 6, 'scope'), 'Average retained loans'),
    (('metrics', 7, 'current'), '285091'),  # Deposits with banks.
    (('metrics', 7, 'scope'), 'Deposits with banks, asset'),
    (('metrics', 6, 'comparison'), 'yoy'),
    (('metrics', 6, 'periods', 'prior', 'as_of'), '2025-06-30'),
    (('metrics', 6, 'change_percent'), '330'),
    (('metrics', 0, 'unit'), ''),
    (('metrics', 0, 'unit'), 'USD billions'),
    (('metrics', 4, 'unit'), 'USD millions'),
    (('metrics', 4, 'current'), '7.7'),
    (('metrics', 3, 'current'), '20752'),  # Income applicable to common.
    (('metrics', 5, 'current'), '2366'),  # Charge-offs in provision row.
    (('metrics', 0, 'citations', 0, 'quote'), 'Unsupported source quote'),
    (('metrics', 0, 'citations', 0, 'accession'), '0001628280-26-000000'),
    (('metrics', 0, 'citations', 0, 'source_url'), 'https://example.com'),
    (('metrics', 0, 'citations', 0, 'start_char'), 0),
    (('reconciliation', 0, 'result'), '58022'),
    (('reconciliation', 0, 'operands', 0, 'value'), '25512'),
    (('reconciliation', 0, 'unit'), 'USD billions'),
    (('reconciliation', 0, 'period', 'start'), '2026-01-01'),
    (('reconciliation', 4, 'operands', 1, 'coefficient'), 1),  # Addition instead of charge-off deduction.
    (('allowance_stock', 'current'), '31366'),  # Principal table versus broad scope.
    (('allowance_stock', 'periods', 'prior', 'as_of'), '2025-06-30'),
    (('source_context', 3, 'citations', 0, 'quote'), 'Visa gains are recurring operating performance.'),
    (('notes',), [{'id': 'credit', 'text': 'Lower provisions prove improving credit quality.'}]),
    (('review_status',), 'pass'),
])
def test_report_rejects_wrong_financials_scopes_identities_and_claims(case, path, value):
    change(case['report'], path, value)
    result = evaluate(case)
    assert not result['automatic_pass'] and not result['overall_pass']
    with pytest.raises(renderer.GateError):
        renderer.build_financial_presentation(case['report'], case['bundle'], case['raw'], case['meta'])


@pytest.mark.parametrize('part,old,new', [
    ('main', 'Change since year-end', 'YoY change'),
    ('main', 'December 31, 2025', 'June 30, 2025'),
    ('main', 'USD millions', 'USD'),
    ('main', 'USD per share', 'USD'),
    ('main', '+3.3%', '+3.3 basis points'),
    ('main', 'Headline revenue is GAAP reported.', 'Headline revenue is managed.'),
    ('main', 'A lower provision alone does not establish improving credit quality.', 'Lower provisions prove improving credit quality.'),
    ('main', 'net gain related to Visa shares', 'recurring operating gain related to Visa shares'),
    ('main', '[S1]: https://www.sec.gov', '[S1]: https://example.com'),
    ('detail', 'USD per share', 'USD millions'),
    ('detail', 'Scope: Consolidated balance-sheet deposit liabilities', 'Scope: Deposits with banks'),
])
def test_presentation_rejects_misleading_units_labels_claims_and_references(case, part, old, new):
    view, main, detail = present(case)
    assert old in (main if part == 'main' else detail)
    if part == 'main': main = main.replace(old, new)
    else: detail = detail.replace(old, new)
    assert not check_presentation(case, view, main, detail)['automatic_pass']


def test_unsupported_extra_text_or_view_changes_and_missing_gate_are_rejected(case):
    view, main, detail = present(case)
    assert not check_presentation(case, view, main+'\nStrong credit quality.\n', detail)['automatic_pass']
    view['metrics'][0]['display_current'] = '$58.0B'
    assert not check_presentation(case, view, main, detail)['automatic_pass']
    assert not check_presentation(case, view, main, detail, gate={})['automatic_pass']


def test_assembly_rejects_changed_extraction_and_does_not_repair_it(case):
    case['bundle']['metrics'][0]['current']['value'] = '58022'
    before = copy.deepcopy(case['bundle'])
    with pytest.raises(ValueError): assembly.assemble_financials(case['bundle'], case['raw'], case['meta'])
    assert case['bundle'] == before


def test_independent_oracle_detects_mutually_consistent_but_wrong_production_report(case, monkeypatch):
    # Independent numbers must still fail if the source-bound layer regresses.
    bad = copy.deepcopy(case['report'])
    bad['metrics'][0]['current'] = '58022'
    monkeypatch.setattr(assembly, 'assemble_financials', lambda *args: bad)
    result = evaluate(case, bad)
    assert result['source_bound_report_pass']
    assert not result['automatic_pass'] and result['financial_values']['passed'] == 15


@pytest.mark.parametrize('kind', ['fte', 'allowance', 'dates'])
def test_independent_reconciliation_checks_survive_production_regression(case, monkeypatch, kind):
    bad = copy.deepcopy(case['report'])
    if kind == 'fte':
        r = next(r for r in bad['reconciliation'] if r['id'] == 'managed:noninterest_revenue:current')
        r['operands'][1]['value'] = '565'; r['result'] = '32401'  # Arithmetic still balances.
    elif kind == 'allowance':
        r = next(r for r in bad['reconciliation'] if r['id'] == 'firmwide_allowance:current')
        r['operands'][1]['value'] = '166'; r['result'] = '31532'
    else:
        r = next(r for r in bad['reconciliation'] if r['id'] == 'net_loans:prior')
        r['period']['as_of'] = '2025-06-30'
    monkeypatch.setattr(assembly, 'assemble_financials', lambda *args: bad)
    result = evaluate(case, bad)
    assert result['source_bound_report_pass']
    assert not result['automatic_pass'] and result['reconciliation']['passed'] == 13


def test_assembly_has_no_oracle_dependency_or_model_call(case, monkeypatch):
    import src.evaluation.jpm_ground_truth as gt
    def forbidden(*args, **kwargs): raise AssertionError('Forbidden oracle/model call')
    monkeypatch.setattr(gt, 'validate_dataset', forbidden)
    monkeypatch.setattr(assembly, 'OpenAI', forbidden)
    assert assembly.assemble_financials(case['bundle'], case['raw'], case['meta']) == case['report']


def test_new_output_directories_preserve_all_inputs_and_pending_reviews(case, tmp_path):
    before = copy.deepcopy(case)
    root = tmp_path/'foundation'
    first, gate, checks = renderer.write_financial_foundation(case['bundle'], case['raw'], case['meta'], case['oracle'], root)
    hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in first.iterdir()}
    second, _, _ = renderer.write_financial_foundation(case['bundle'], case['raw'], case['meta'], case['oracle'], root)
    assert first != second and case == before
    assert hashes == {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in first.iterdir()}
    assert gate['automatic_pass'] and checks['automatic_pass']
    assert not gate['overall_pass'] and not checks['overall_pass']
    review = load_dataset(first/'review_template.json')
    assert review['status'] == 'pending_manual_review' and not review['reviewer']
    assert not (first/'raw_llm.json').exists()


def test_original_saved_extraction_assembles_offline_without_mutating_history():
    source = ROOT/'data/m006-step2/extraction.json'
    if not source.exists(): pytest.skip('Private saved extraction unavailable; public excerpt tested')
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    bundle = load_dataset(source);oracle = load_dataset(DEFAULT_PATH)
    raw = (ROOT/oracle['source_snapshot']['path']).read_bytes();meta = bundle['source']
    report = assembly.assemble_financials(bundle, raw, meta)
    result = evaluate_financials(report, bundle, oracle, payload=raw, metadata=meta)
    assert result['automatic_pass'] and not result['overall_pass'], result
    view = renderer.build_financial_presentation(report, bundle, raw, meta)
    assert '| Noninterest revenue | 31,836 | 21,703 | +46.7%' in renderer.render_financial_main(view)
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before
