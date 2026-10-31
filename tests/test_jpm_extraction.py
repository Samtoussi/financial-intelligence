"""Banking extraction versus the unchanged independent oracle, without AI."""
import ast
import copy
import hashlib
import json
from pathlib import Path
import warnings

from bs4 import XMLParsedAsHTMLWarning
import pytest

from src.analytics import jpm_extraction as jpm
from src.evaluation.ground_truth import load_dataset
from src.evaluation import jpm_ground_truth as oracle_checks
from src.transformation import parse_filings, store_filings

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT/'tests/fixtures/jpm_2026_q2_extraction.html'


@pytest.fixture
def source(monkeypatch):
    # Synthetic TOC wrappers around public independent source excerpts.
    # Only this fixture hash is substituted, never the expected oracle values.
    raw = FIXTURE.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    monkeypatch.setattr(jpm, 'SOURCE_SHA256', sha)
    return raw, {**jpm.SOURCE, 'sha256': sha}


@pytest.fixture
def bundle(source):
    return jpm.extract_jpm(*source)


def compare_oracle(bundle):
    oracle = load_dataset(oracle_checks.DEFAULT_PATH)
    expected = {m['id']: m for m in oracle['metrics']}
    assert {m['id'] for m in bundle['metrics']} == set(expected)
    for m in bundle['metrics']:
        o = expected[m['id']]
        assert m['label'] == o['label']
        assert m['unit'] == o['unit'] and m['kind'] == o['kind']
        assert m['basis'] == o['gaap_status'] and m['comparison'] == o['comparison']
        for p in ('current', 'prior'):
            assert m[p]['value'] == o[p]['value']
            assert m[p]['period'] == {k: v for k, v in o[p]['period'].items() if k != 'fiscal_period'}
    for b in oracle['reported_to_managed']:
        assert bundle['reported_to_managed'][b['metric_id']]['values'] == [b[p][c]
            for p in ('current', 'prior') for c in ('reported', 'fte_adjustment', 'managed')]
    s = oracle['supporting_values']
    for key, other in [('net_charge_offs', 'net_charge_offs'), ('net_additions', 'net_addition_to_allowance'),
                       ('firmwide_allowance', 'firmwide_allowance')]:
        assert bundle['credit'][key] == [s[other][p] for p in ('current', 'prior')]


def test_portable_values_and_reconciliations_match_independent_oracle(bundle, source):
    compare_oracle(bundle)
    assert jpm.validate_extraction(bundle, *source)
    assert jpm.validate_extraction(json.loads(json.dumps(bundle)), *source)
    assert bundle['reconciliations_pass']
    assert bundle['credit']['current_cib_receivables_allowance'] == '165'
    assert bundle['credit']['current_components']['principal_total']['value'] == '31366'
    assert len(bundle['metrics']) == 8  # No CET1 or segment headline additions.


def test_exact_source_membership_hashes_and_citations(bundle):
    sections = {s['item']: s for s in bundle['sections']}
    evidence = {e['evidence_id']: e for e in bundle['evidence']}
    for e in evidence.values():
        text = sections[e['item']]['text']
        assert e['text'] == text[e['start_char']:e['end_char']]
        assert e['text_sha256'] == hashlib.sha256(e['text'].encode()).hexdigest()
        assert e['section_sha256'] == hashlib.sha256(text.encode()).hexdigest()
        assert e['chunk_ids'] and e['source_sha256'] == bundle['source']['sha256']
    for m in bundle['metrics']:
        cite = m['citation']; e = evidence[cite['evidence_id']]
        assert sections[e['item']]['text'][cite['start_char']:cite['end_char']] == cite['quote']
        assert e['start_char'] <= cite['start_char'] < cite['end_char'] <= e['end_char']
        assert m['source_columns'] == [0, 1]
        assert m['excluded_columns'] == ([2, 3] if m['kind'] == 'flow' else [])


def test_banking_evidence_is_bounded_and_separates_accounting_scopes(bundle):
    e = {x['label']: x['text'] for x in bundle['evidence']}
    assert 'U.S. GAAP' in e['reported_to_managed'] and 'Fully taxable-equivalent' in e['reported_to_managed']
    assert 'Six months ended' not in e['reported_to_managed']
    assert 'Quarterly results' in e['credit_context'] and 'Year-to-date results' not in e['credit_context']
    assert '$4.6 billion net gain related to Visa shares' in e['significant_items']
    assert 'accounts receivable in CIB' in e['allowance_scope']
    assert 'segment_table' not in e
    assert bundle['metrics'][-1]['comparison'] == 'since_year_end'


def set_path(obj, path, value):
    for key in path[:-1]: obj = obj[key]
    obj[path[-1]] = value


@pytest.mark.parametrize('path,value', [
    (('metrics', 0, 'current', 'value'), '107183'),  # Six months.
    (('metrics', 4, 'current', 'value'), '13.63'),  # YTD EPS.
    (('metrics', 0, 'current', 'value'), '58022'),  # Managed revenue.
    (('metrics', 6, 'current', 'value'), '1516310'),  # Net loans.
    (('metrics', 6, 'current', 'value'), '1463808'),  # Retained end-of-period.
    (('metrics', 6, 'current', 'value'), '1418293'),  # Average retained.
    (('metrics', 7, 'current', 'value'), '285091'),  # Deposits with banks.
    (('metrics', 3, 'current', 'value'), '20752'),  # Income applicable to common.
    (('metrics', 5, 'current', 'value'), '2366'),  # Charge-offs.
    (('metrics', 0, 'current', 'period', 'start'), '2026-01-01'),
    (('metrics', 6, 'prior', 'period', 'as_of'), '2025-06-30'),
    (('metrics', 6, 'comparison'), 'yoy'),
    (('metrics', 0, 'unit'), 'USD billions'),
    (('metrics', 4, 'unit'), 'USD millions'),
    (('metrics', 0, 'basis'), 'Managed'),
    (('metrics', 0, 'source_columns'), [2, 3]),
    (('metrics', 0, 'citation', 'quote'), '| Total net revenue | 107183 | 90222 |'),
    (('metrics', 0, 'citation', 'start_char'), 0),
    (('evidence', 0, 'accession'), '0001628280-26-000000'),
    (('evidence', 0, 'source_sha256'), '0'*64),
    (('evidence', 0, 'end_char'), 1),
    (('evidence', 0, 'text'), 'Unsupported source evidence'),
    (('sections', 0, 'accession'), '0001628280-26-000000'),
    (('source', 'source_url'), 'https://example.com'),
    (('credit', 'firmwide_allowance', 0), '31366'),
])
def test_serialized_extraction_rejects_unsupported_claims(bundle, source, path, value):
    set_path(bundle, path, value)
    with pytest.raises(ValueError, match='not supported'):
        jpm.validate_extraction(bundle, *source)


@pytest.mark.parametrize('window,old,new', [
    ('income_statement', 'Three months ended', 'Six months ended'),
    ('income_statement', '2026 | | 2025 | | 2026 | | 2025', '2026 | | 2026 | | 2025 | | 2025'),
    ('income_statement', 'in millions, except per share data', 'in billions, except per share data'),
    ('income_statement', '| Total net revenue |', '| Managed total net revenue |'),
    ('balance_sheet', 'December 31, 2025', 'June 30, 2025'),
    ('balance_sheet', '| Loans (included', '| Retained loans (included'),
    ('balance_sheet', '| Deposits (included', '| Deposits with banks (included'),
    ('reported_to_managed', 'Three months ended', 'Six months ended'),
    ('reported_to_managed', 'Fully taxable-equivalent adjustments', 'Other adjustments'),
    ('credit_highlights', '4Q25', '2Q25'),
    ('allowance_scope', 'At June 30, 2026 and 2025', 'At December 31, 2025 and 2024'),
])
def test_source_context_rejected_before_value_selection(bundle, window, old, new):
    evidence = copy.deepcopy(bundle['evidence'])
    e = next(x for x in evidence if x['label'] == window)
    assert old in e['text']
    e['text'] = e['text'].replace(old, new)
    with pytest.raises(ValueError):
        jpm.extract_values(evidence)


@pytest.mark.parametrize('alter', ['missing_start', 'duplicate_destination', 'ambiguous_link', 'reversed'])
def test_independent_section_ranges_fail_closed(source, alter):
    soup = parse_filings.parse_html(source[0])
    if alter == 'missing_start': soup.find(id='mda').decompose()
    if alter == 'duplicate_destination': soup.body.append(copy.copy(soup.find(id='fin')))
    if alter == 'ambiguous_link':
        link = soup.new_tag('a', href='#other');link.string = 'Financial Statements';soup.body.append(link)
    if alter == 'reversed': soup.body.append(soup.find(id='mda').extract())
    with pytest.raises(ValueError):
        parse_filings.jpm_quarterly_sections(soup, source[1])


def test_existing_parse_and_prepare_contract_supports_reordered_jpm_sections(source, tmp_path):
    raw, metadata = source
    p = tmp_path/'fixture.html';p.write_bytes(raw)
    p.with_suffix('.metadata.json').write_text(json.dumps(metadata), encoding='utf-8')
    sections = store_filings.prepare_sections('JPM', form='10-Q', accession=jpm.SOURCE['accession'], snapshot_path=p)
    assert [s['item'] for s in sections] == ['I.1', 'I.2']
    assert all(s['extraction_method'] == 'independent_toc_ranges' for s in sections)
    assert sections[0]['text'].startswith('Consolidated statements of income')
    assert sections[1]['text'].startswith('Consolidated financial highlights')
    assert 'Consolidated balance sheets (unaudited)' not in sections[1]['text']
    assert 'net gain related to Visa' not in sections[0]['text']


@pytest.mark.parametrize('key,value', [('accession', '0001628280-26-000000'), ('cik', 1),
    ('form', '10-K'), ('report_date', '2026-03-31'), ('sha256', '0'*64)])
def test_wrong_source_identity_or_checksum_is_rejected(source, key, value):
    raw, meta = source;meta[key] = value
    with pytest.raises(ValueError): jpm.extract_jpm(raw, meta)


def test_corrupted_original_bytes_are_rejected(source):
    with pytest.raises(ValueError, match='checksum'): jpm.extract_jpm(source[0]+b' ', source[1])


def test_production_does_not_import_oracle_or_ai():
    tree = ast.parse(Path(jpm.__file__).read_text(encoding='utf-8'))
    modules = [n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
    assert not any('evaluation' in m or 'evals' in m or '.ai' in m for m in modules)


def test_original_pinned_source_extraction_and_expected_parser_warning():
    oracle = load_dataset(oracle_checks.DEFAULT_PATH);s = oracle['source_snapshot']
    path = ROOT/s['path']
    if not path.exists(): pytest.skip('Private pinned original unavailable; public source fixture tested')
    raw = path.read_bytes();meta = load_dataset(ROOT/s['metadata_path'])
    before = hashlib.sha256(raw).hexdigest()
    with warnings.catch_warnings(record=True) as observed:
        warnings.simplefilter('always', XMLParsedAsHTMLWarning)
        bundle = jpm.extract_jpm(raw, meta)
    assert any(issubclass(w.category, XMLParsedAsHTMLWarning) for w in observed)
    assert raw.lstrip().startswith(b'<?xml')  # Inline XBRL HTML carries XML declaration.
    compare_oracle(bundle)
    assert jpm.validate_extraction(bundle, raw, meta)
    assert parse_filings.parse_filing('JPM', form='10-Q', accession=meta['accession'], snapshot_path=path) == bundle['sections']
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before == s['sha256']
