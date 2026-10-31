"""Independent, offline M006 oracle checks; no production extraction involved."""
import ast
from copy import deepcopy
import hashlib
from pathlib import Path

import pytest

from src.evaluation import jpm_ground_truth as jpm
from src.evaluation.ground_truth import load_dataset

FIXTURE = jpm.ROOT / 'tests/fixtures/jpm_2026_q2_oracle_excerpt.html'
EXPECTED = [
    ('total_net_revenue', '57347', '44912'),
    ('net_interest_income', '25511', '23209'),
    ('noninterest_revenue', '31836', '21703'),
    ('net_income', '21155', '14987'), ('diluted_eps', '7.70', '5.24'),
    ('provision_for_credit_losses', '2515', '2849'),
    ('total_loans', '1542462', '1493429'), ('total_deposits', '2713700', '2559320'),
]


@pytest.fixture
def oracle():
    return load_dataset(jpm.DEFAULT_PATH)


@pytest.mark.parametrize('mid,current,prior', EXPECTED)
def test_independently_transcribed_values(oracle, mid, current, prior):
    metric = next(m for m in oracle['metrics'] if m['id'] == mid)
    assert [metric[p]['value'] for p in ('current', 'prior')] == [current, prior]
    assert metric['unit'] == ('USD per share' if mid == 'diluted_eps' else 'USD millions')


def test_portable_source_tables_and_exact_decimal_identities(oracle):
    result = jpm.validate_dataset(oracle)
    assert jpm.verify_tables(oracle, jpm.source_document(FIXTURE.read_bytes()))
    assert result['metric_values_checked'] == 16
    assert result['changes']['total_loans'] == {'comparison': 'since_year_end', 'percent': '3.3'}
    assert result['changes']['diluted_eps']['percent'] == '46.9'
    assert result['reported_and_managed_identities_pass']
    assert result['credit_and_balance_identities_pass']
    assert result['cet1_change_basis_points'] == '-40'
    assert result['human_review_status'] == 'pending_manual_review'
    assert not result['overall_approved']
    assert 'source_verified' not in result  # Excerpts cannot authenticate full SEC bytes.


def set_path(data, path, value):
    target = data
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value


@pytest.mark.parametrize('path,value', [
    (('report', 'accession'), '0001628280-26-000000'),
    (('report', 'filing_date'), '2026-08-05'),
    (('report', 'filing_date_source', 'url'), jpm.URL),
    (('source_snapshot', 'sha256'), '0'*64),
    (('periods', 'current', 'start'), '2026-01-01'),
    (('periods', 'balance_prior', 'as_of'), '2025-06-30'),
    (('metrics', 0, 'current', 'value'), '107183'),  # Six-month YTD.
    (('metrics', 0, 'gaap_status'), 'Managed'),
    (('metrics', 4, 'current', 'value'), '7.7'),  # Preserve statement precision.
    (('metrics', 4, 'unit'), 'USD millions'),
    (('metrics', 6, 'kind'), 'flow'),
    (('metrics', 6, 'comparison'), 'yoy'),
    (('metrics', 6, 'prior', 'period', 'as_of'), '2025-06-30'),
    (('metrics', 6, 'current', 'value'), '1516310'),  # Net loans, not selected loans.
    (('metrics', 3, 'current', 'value'), '20752'),  # Income applicable to common.
    (('metrics', 5, 'current', 'value'), '2366'),  # Charge-offs, not provision.
    (('metrics', 0, 'source', 'page'), 95),
    (('metrics', 0, 'source', 'columns'), 'Six months ended June 30'),
    (('metrics', 0, 'source', 'url'), 'https://example.com'),
    (('reported_to_managed', 0, 'current', 'fte_adjustment'), '0'),
    (('reported_to_managed', 0, 'unit'), 'USD billions'),
    (('supporting_values', 'net_charge_offs', 'current'), '2515'),
    (('supporting_values', 'allowance_components_current', 'cib_accounts_receivable'), '0'),
    (('optional_capital_note', 'entity'), 'JPMorgan Chase Bank, N.A.'),
    (('optional_capital_note', 'regulatory_basis'), 'Advanced'),
    (('optional_capital_note', 'unit'), 'basis points'),
    (('optional_capital_note', 'headline_metric'), True),
    (('optional_capital_note', 'change_basis_points'), '-0.4'),
    (('qualitative_review_cases', 0, 'status'), 'pass'),
    (('qualitative_review_cases', 0, 'evidence_locations', 0, 'quote'), 'Invented interpretation'),
    (('verification', 'independent_of_production_extraction'), False),
])
def test_schema_period_accounting_and_evidence_fail_closed(oracle, path, value):
    set_path(oracle, path, value)
    with pytest.raises(ValueError):
        jpm.validate_dataset(oracle)


@pytest.mark.parametrize('mid,bad', [
    ('total_loans', '1516310'), ('total_loans', '1491678'),
    ('total_deposits', '285091'), ('net_income', '20752'),
    ('total_net_revenue', '58022'), ('provision_for_credit_losses', '5022'),
    ('diluted_eps', '13.63'),
])
def test_original_statement_selection_rejects_wrong_scope_even_without_identities(oracle, mid, bad):
    next(m for m in oracle['metrics'] if m['id'] == mid)['current']['value'] = bad
    with pytest.raises(ValueError):
        jpm.verify_tables(oracle, jpm.source_document(FIXTURE.read_bytes()))


def test_ytd_header_cannot_be_used_as_quarter(oracle):
    soup = jpm.source_document(FIXTURE.read_bytes())
    income = jpm._table(soup, 'Weighted-average diluted shares', 'Net income applicable to common stockholders')
    for node in income.find_all(string=True):
        if 'Three months ended' in node:
            node.replace_with(str(node).replace('Three months ended', 'Six months ended'))
    with pytest.raises(ValueError, match='income columns'):
        jpm.verify_tables(oracle, soup)


def test_duplicate_or_missing_metrics_and_duplicate_json_keys(oracle, tmp_path):
    oracle['metrics'][0] = deepcopy(oracle['metrics'][1])
    with pytest.raises(ValueError):
        jpm.validate_dataset(oracle)
    path = tmp_path / 'duplicate.json'
    path.write_text('{"schema_version":2,"schema_version":2}', encoding='utf-8')
    with pytest.raises(ValueError):
        load_dataset(path)


@pytest.fixture
def pinned(oracle):
    s = oracle['source_snapshot']
    paths = [jpm.ROOT/s[k] for k in ('path', 'metadata_path', 'filing_detail_path', 'filing_detail_metadata_path')]
    if not all(p.exists() for p in paths):
        pytest.skip('Original ignored SEC snapshots unavailable; portable tables tested separately')
    return paths[0].read_bytes(), load_dataset(paths[1]), paths[2].read_bytes(), load_dataset(paths[3])


def test_original_sec_snapshot_identity_checksum_and_passages(oracle, pinned):
    result = jpm.verify_sources(oracle, *pinned)
    assert result['source_verified'] and result['source_sha256'] == jpm.SHA256


@pytest.mark.parametrize('target', ['html', 'detail', 'metadata', 'detail_metadata', 'offset', 'quote'])
def test_original_source_checks_reject_corruption(oracle, pinned, target):
    html, metadata, detail, detail_metadata = pinned
    if target == 'html': html += b' '
    if target == 'detail': detail += b' '
    if target == 'metadata': metadata['filing_date'] = '2026-08-05'
    if target == 'detail_metadata': detail_metadata['source_url'] = jpm.URL
    e = oracle['qualitative_review_cases'][0]['evidence_locations'][0]
    if target == 'offset':
        e['start_char'] += 1
        e['end_char'] += 1
    if target == 'quote':
        e['quote'] = 'X' + e['quote'][1:]
        e['quote_sha256'] = hashlib.sha256(e['quote'].encode()).hexdigest()
    with pytest.raises(ValueError):
        jpm.verify_sources(oracle, html, metadata, detail, detail_metadata)


def test_oracle_validator_has_no_production_extraction_dependency():
    tree = ast.parse(Path(jpm.__file__).read_text(encoding='utf-8'))
    modules = [n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
    assert [m for m in modules if m.startswith('src.')] == ['src.evaluation.ground_truth']
