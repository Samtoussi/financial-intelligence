"""M006 step 1: bounded independent oracle checks, not production extraction.

No report profiles, production parsers, assembly, retrieval or model calls.
The mixed-period oracle deliberately does not change MSFT/CAT validators.
"""
import argparse
import hashlib
import json
import re
from decimal import Decimal, ROUND_HALF_UP, localcontext
from pathlib import Path

from bs4 import BeautifulSoup
from src.evaluation.ground_truth import load_dataset, require

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PATH = ROOT / 'evals/ground_truth/jpm_2026_q2.json'
URL = 'https://www.sec.gov/Archives/edgar/data/19617/000162828026054343/jpm-20260630.htm'
INDEX = URL.replace('jpm-20260630.htm', '0001628280-26-054343-index.html')
SHA256 = '75e02668ad64cef396ee9f9b10a8982f70f8e1c6879b833be9eae0e02f599d6b'
DETAIL_SHA256 = '955d3ff42604c9e8e6311914094ad1ae25ee37bba4ea5ced8aff476f82e08782'
REPORT = {'company': 'JPMorgan Chase & Co.', 'cik': '0000019617', 'form': '10-Q',
          'accession': '0001628280-26-054343', 'fiscal_period': 'FY2026 Q2',
          'period_end': '2026-06-30', 'filing_date': '2026-08-06',
          'document': 'jpm-20260630.htm', 'source_url': URL}
PERIODS = {
    'current': {'fiscal_period': 'FY2026 Q2', 'start': '2026-04-01', 'end': '2026-06-30'},
    'prior': {'fiscal_period': 'FY2025 Q2', 'start': '2025-04-01', 'end': '2025-06-30'},
    'balance_current': {'as_of': '2026-06-30'}, 'balance_prior': {'as_of': '2025-12-31'}}
LABELS = {
    'total_net_revenue': 'Total net revenue', 'net_interest_income': 'Net interest income',
    'noninterest_revenue': 'Noninterest revenue', 'net_income': 'Net income',
    'diluted_eps': 'Diluted earnings per share', 'provision_for_credit_losses': 'Provision for credit losses',
    'total_loans': 'Loans (included $ 62,889 and $ 70,684 at fair value)',
    'total_deposits': 'Deposits (included $ 26,229 and $ 20,930 at fair value)'}
STOCKS = {'total_loans', 'total_deposits'}
TOPICS = {'reported_vs_managed', 'credit_loss_measures', 'significant_earnings_items'}


def decimal(value, *, signed=False, eps=False):
    pattern = r'-?\d+' if signed else r'\d+\.\d{2}' if eps else r'\d+'
    require(isinstance(value, str) and re.fullmatch(pattern, value), 'Invalid exact value/precision')
    return Decimal(value)


def check_citation(cite, *, row=None, page=None):
    require(isinstance(cite, dict) and cite.get('url') == URL, 'Wrong source citation URL')
    for field in ('section', 'table', 'row', 'columns'):
        require(isinstance(cite.get(field), str) and cite[field].strip(), 'Missing citation ' + field)
    require(type(cite.get('page')) is int and cite['page'] > 0, 'Missing citation page')
    require(row is None or cite['row'] == row, 'Incorrect source row')
    require(page is None or cite['page'] == page, 'Incorrect source page')


def validate_dataset(data):
    """Pure schema/Decimal/identity checks; does not claim raw-source verification."""
    try:
        return _validate(data)
    except (KeyError, TypeError, AttributeError, StopIteration) as exc:
        raise ValueError('Missing or malformed JPM oracle field') from exc


def _validate(data):
    require(data['schema_version'] == 2 and data['oracle_contract'] == 'm006-jpm-oracle-v1'
            and data['milestone'] == 'M006', 'Incorrect JPM oracle contract')
    require(all(data['report'].get(k) == v for k, v in REPORT.items()), 'Incorrect filing identity')
    require(data['report']['filing_date_source']['url'] == INDEX, 'Incorrect filing-detail source')
    require(data['periods'] == PERIODS, 'Incorrect locked periods/as-of dates')
    snapshot = data['source_snapshot']
    require(snapshot['sha256'] == SHA256 and snapshot['filing_detail_sha256'] == DETAIL_SHA256,
            'Incorrect pinned source checksum')
    require(snapshot['size_bytes'] == 11513994, 'Incorrect source size')
    metrics = data['metrics']
    require(len(metrics) == 8 and {m['id'] for m in metrics} == set(LABELS), 'Missing/duplicate/unexpected metric IDs')
    by_id, changes = {}, {}
    for m in metrics:
        mid = m['id']; stock = mid in STOCKS
        require(m['label'] == LABELS[mid] and m['gaap_status'] == 'GAAP reported', 'Incorrect statement label/basis')
        require(m['unit'] == ('USD per share' if mid == 'diluted_eps' else 'USD millions'), 'Incorrect metric unit')
        require(m['kind'] == ('point_in_time' if stock else 'flow'), 'Incorrect flow/stock classification')
        require(m['comparison'] == ('since_year_end' if stock else 'yoy'), 'Incorrect comparison basis')
        require(isinstance(m['scope'], str) and len(m['scope'].strip()) > 20, 'Missing accounting scope')
        check_citation(m['source'], row=LABELS[mid], page=95 if stock else 93)
        require(m['source']['columns'] == ('June 30, 2026 / December 31, 2025' if stock else
            'Three months ended June 30: 2026 / 2025; exclude six-month YTD columns'), 'Incorrect selected columns')
        pair = []
        for p in ('current', 'prior'):
            require(m[p]['period'] == PERIODS['balance_' + p if stock else p], 'Incorrect metric period')
            value = decimal(m[p]['value'], eps=mid == 'diluted_eps')
            require(value > 0, 'Unsupported nonpositive core observation')
            pair.append(value)
        by_id[mid] = pair
        with localcontext() as ctx:
            ctx.prec = 50
            changes[mid] = {'comparison': m['comparison'], 'percent': str(((pair[0]-pair[1])/pair[1]*100).quantize(
                Decimal('.1'), rounding=ROUND_HALF_UP))}
    for p in range(2):
        require(by_id['net_interest_income'][p] + by_id['noninterest_revenue'][p] == by_id['total_net_revenue'][p],
                'Reported revenue identity failed')
    bridge = data['reported_to_managed']
    require(len(bridge) == 3 and {b['metric_id'] for b in bridge} == {
        'noninterest_revenue', 'net_interest_income', 'total_net_revenue'}, 'Incorrect basis bridge scope')
    indexed = {b['metric_id']: b for b in bridge}
    for b in bridge:
        require(b['unit'] == 'USD millions', 'Incorrect bridge units')
        check_citation(b['source'], page=18)
        for i, p in enumerate(('current', 'prior')):
            v = b[p]
            require(v['period'] == PERIODS[p], 'Incorrect bridge period')
            require(decimal(v['reported']) == by_id[b['metric_id']][i], 'Reported bridge/metric mismatch')
            require(decimal(v['reported']) + decimal(v['fte_adjustment']) == decimal(v['managed']), 'FTE bridge failed')
    for p in ('current', 'prior'):
        for column in ('reported', 'fte_adjustment', 'managed'):
            require(decimal(indexed['net_interest_income'][p][column]) + decimal(indexed['noninterest_revenue'][p][column])
                    == decimal(indexed['total_net_revenue'][p][column]), 'Basis-specific revenue identity failed')
    support = data['supporting_values']
    for key in ('net_income_applicable_to_common_stockholders', 'loan_loss_allowance_signed', 'net_loans',
                'net_charge_offs', 'net_addition_to_allowance', 'firmwide_allowance', 'net_income_managed'):
        v = support[key]; require(v['unit'] == 'USD millions', 'Incorrect supporting units')
        check_citation(v['source'])
        for p in ('current', 'prior'): decimal(v[p], signed=key == 'loan_loss_allowance_signed')
    for i, p in enumerate(('current', 'prior')):
        require(by_id['net_income'][i] == decimal(support['net_income_managed'][p]), 'FTE net-income neutrality failed')
        require(decimal(support['net_income_applicable_to_common_stockholders'][p]) < by_id['net_income'][i], 'Incorrect income scope')
        require(by_id['total_loans'][i] + decimal(support['loan_loss_allowance_signed'][p], signed=True)
                == decimal(support['net_loans'][p]), 'Loans/allowance/net-loans identity failed')
        require(by_id['provision_for_credit_losses'][i] - decimal(support['net_charge_offs'][p])
                == decimal(support['net_addition_to_allowance'][p]), 'Provision/charge-off period bridge failed')
    acl = support['allowance_components_current']; check_citation(acl['source'], page=76)
    require(acl['as_of'] == PERIODS['balance_current']['as_of'] and acl['unit'] == 'USD millions', 'Incorrect ACL date/unit')
    require(decimal(acl['loan_losses']) == -decimal(support['loan_loss_allowance_signed']['current'], signed=True), 'Loan allowance mismatch')
    require(sum(decimal(acl[k]) for k in ('loan_losses', 'lending_related_commitments', 'investment_securities'))
            == decimal(acl['principal_table_total']), 'Principal allowance table failed')
    require(decimal(acl['principal_table_total']) + decimal(acl['cib_accounts_receivable'])
            == decimal(acl['firmwide_total']) == decimal(support['firmwide_allowance']['current']), 'Broad allowance scope failed')
    cases = data['qualitative_review_cases']
    require(len(cases) == 3 and {c['id'] for c in cases} == TOPICS, 'Incorrect qualitative cases')
    for case in cases + data['supporting_evidence']:
        require(case['status'] == 'pending_manual_review' and case['conclusion'] is None, 'Human review must remain pending')
        require(isinstance(case['question'], str) and case['question'].strip(), 'Missing semantic question')
        require(bool(case['evidence_locations']), 'Missing qualitative evidence')
        for e in case['evidence_locations']:
            require(e['url'] == URL and type(e['page']) is int and e['page'] > 0 and e['section'] and e['location'], 'Incorrect qualitative location')
            require(isinstance(e['quote'], str) and len(e['quote']) >= 40, 'Missing source passage')
            require(e['quote_sha256'] == hashlib.sha256(e['quote'].encode()).hexdigest(), 'Passage hash mismatch')
            require(type(e['start_char']) is int and e['start_char'] >= 0
                    and e['end_char']-e['start_char'] == len(e['quote']), 'Incorrect passage offsets')
    capital = data['optional_capital_note']
    require(capital['headline_metric'] is False and capital['status'] == 'pending_manual_review', 'CET1 is optional and unapproved')
    require(capital['unit'] == 'percent' and capital['kind'] == 'point_in_time'
            and capital['entity'] == 'JPMorgan Chase & Co. consolidated (the Firm), not JPMorgan Chase Bank, N.A.'
            and capital['regulatory_basis'] == 'Standardized', 'Incorrect capital entity/basis/unit')
    for p in ('current', 'prior'): require(capital[p]['period'] == PERIODS['balance_'+p], 'Incorrect CET1 dates')
    require(all(re.fullmatch(r'\d+\.\d', capital[p]['value']) for p in ('current', 'prior')), 'Incorrect CET1 precision')
    require((Decimal(capital['current']['value'])-Decimal(capital['prior']['value']))*100
            == decimal(capital['change_basis_points'], signed=True), 'Incorrect CET1 basis-point change')
    check_citation(capital['source'], row='CET1 capital ratio', page=46)
    require(data['verification']['human_review_status'] == 'pending_manual_review'
            and data['verification']['independent_of_production_extraction'] is True, 'Incorrect oracle independence/review record')
    return {'oracle_contract': data['oracle_contract'], 'metric_values_checked': 16,
            'changes': changes, 'reported_and_managed_identities_pass': True,
            'credit_and_balance_identities_pass': True, 'cet1_change_basis_points': capital['change_basis_points'],
            'human_review_status': 'pending_manual_review', 'overall_approved': False}


def source_document(payload):
    soup = BeautifulSoup(payload, 'lxml')
    for tag in soup.find_all(['head', 'script', 'style', 'ix:header', 'ix:hidden', 'noscript']): tag.decompose()
    return soup


def normalized(text):
    return re.sub(r'\s+', ' ', text).strip()


def _table(soup, *terms):
    tables = [t for t in soup.find_all('table') if all(term in normalized(t.get_text(' ', strip=True)) for term in terms)]
    require(len(tables) == 1, 'Missing/ambiguous independent source table')
    return tables[0]


def _rows(table, *, quarter_only=False):
    result = {}
    for tr in table.find_all('tr'):
        cells = [normalized(c.get_text(' ', strip=True)) for c in tr.find_all(['td', 'th'], recursive=False)]
        if quarter_only and any('Six months ended' in c for c in cells): break
        if cells and cells[0]: result.setdefault(cells[0], []).append(cells[1:])
    return result


def _values(rows, label):
    require(len(rows.get(label, [])) == 1, 'Missing/ambiguous independent source row')
    tokens = [c for c in rows[label][0] if c and c not in {'$', '%'}]
    require(all(c in {'NA', '\u2014'} or re.fullmatch(r'\(?\s*-?\d[\d,]*(?:\.\d+)?\s*\)?', c) for c in tokens), 'Unsupported source cells')
    return [c if c == 'NA' else '0' if c == '\u2014' else ('-' if c.startswith('(') else '') + c.strip('() ').replace(' ', '').replace(',', '') for c in tokens]


def verify_tables(data, soup):
    """Independent evaluation selectors only; also usable with a public test excerpt."""
    income = _table(soup, 'Weighted-average diluted shares', 'Net income applicable to common stockholders')
    header = normalized(income.get_text(' ', strip=True)).split('Revenue')[0]
    require('Three months ended June 30, Six months ended June 30,' in header
            and 'in millions, except per share data' in header
            and re.findall(r'20\d{2}', header) == ['2026', '2025', '2026', '2025'], 'Incorrect income columns/units')
    balance = _table(soup, 'Total stockholders', 'Loans, net of allowance for loan losses', 'Deposits with banks')
    require('June 30, 2026 December 31, 2025' in normalized(balance.get_text(' ', strip=True))
            and 'in millions, except share data' in normalized(balance.get_text(' ', strip=True)), 'Incorrect balance columns/units')
    ir, br = _rows(income), _rows(balance)
    for m in data['metrics']:
        values = _values(br if m['id'] in STOCKS else ir, m['label'])
        require(len(values) == (2 if m['id'] in STOCKS else 4)
                and values[:2] == [m[p]['value'] for p in ('current', 'prior')], 'Oracle value absent from original statement: '+m['id'])
    managed = _table(soup, 'Fully taxable-equivalent adjustments', 'Managed basis', 'Other income')
    mr = _rows(managed, quarter_only=True)
    require('Three months ended June 30, 2026 2025' in normalized(managed.get_text(' ', strip=True)), 'Incorrect bridge periods')
    for b in data['reported_to_managed']:
        require(_values(mr, b['source']['row']) == [b[p][c] for p in ('current', 'prior')
                for c in ('reported', 'fte_adjustment', 'managed')], 'Oracle bridge absent from source')
    managed_net = _values(mr, 'Net income')
    require(managed_net == [data['supporting_values']['net_income_managed']['current'], 'NA',
        data['supporting_values']['net_income_managed']['current'], data['supporting_values']['net_income_managed']['prior'], 'NA',
        data['supporting_values']['net_income_managed']['prior']], 'Incorrect source FTE net-income neutrality')
    for key, label, rows in (
        ('net_income_applicable_to_common_stockholders', 'Net income applicable to common stockholders', ir),
        ('loan_loss_allowance_signed', 'Allowance for loan losses', br),
        ('net_loans', 'Loans, net of allowance for loan losses', br)):
        require(_values(rows, label)[:2] == [data['supporting_values'][key][p] for p in ('current', 'prior')], 'Incorrect supporting statement value')
    highlights = _table(soup, 'Allowances for credit losses', '2Q26', '4Q25', 'Net charge-offs')
    hr = _rows(highlights)
    for key, label, indexes in (('net_charge_offs', 'Net charge-offs', (0,4)),
                               ('firmwide_allowance', 'Allowances for credit losses', (0,2))):
        vals = _values(hr, label)
        require([vals[i] for i in indexes] == [data['supporting_values'][key][p] for p in ('current', 'prior')], 'Incorrect credit date/scope')
    acl_table = _table(soup, 'Allowance for credit losses and related information', 'Allowance for lending-related commitments')
    ar = _rows(acl_table); acl = data['supporting_values']['allowance_components_current']
    for key, label in (('loan_losses', 'Total allowance for loan losses'),
                       ('lending_related_commitments', 'Total allowance for lending-related commitments'),
                       ('investment_securities', 'Total allowance for investment securities'),
                       ('principal_table_total', 'Total allowance for credit losses (b)')):
        require(_values(ar, label)[3] == acl[key], 'Incorrect source allowance component')
    credit_quote = next(c for c in data['qualitative_review_cases'] if c['id'] == 'credit_loss_measures')['evidence_locations'][0]['quote']
    additions = re.findall(r'net addition to the allowance for credit losses was \$\s*(\d+) million', credit_quote)
    require(len(additions) >= 2 and [additions[0], additions[-1]] == [data['supporting_values']['net_addition_to_allowance'][p]
            for p in ('current', 'prior')], 'Incorrect source period net additions')
    footnote = next(c for c in data['supporting_evidence'] if c['id'] == 'allowance_scope')['evidence_locations'][0]['quote']
    amount = re.search(r'allowance for credit losses of \$\s*(\d+) million', footnote)
    require(amount is not None and amount[1] == acl['cib_accounts_receivable'], 'Incorrect CIB receivables allowance')
    capital = _table(soup, 'Standardized Advanced', 'Capital ratio requirements (a)', 'CET1 capital ratio')
    require('June 30, 2026 December 31, 2025 Capital ratio requirements' in normalized(capital.get_text(' ', strip=True)), 'Incorrect capital columns')
    require(_values(_rows(capital), 'CET1 capital ratio')[:2] == [data['optional_capital_note'][p]['value'] for p in ('current','prior')], 'Incorrect source CET1 values')
    return True


def verify_sources(data, payload, metadata, detail, detail_metadata):
    result = validate_dataset(data)
    require(hashlib.sha256(payload).hexdigest() == SHA256 and len(payload) == data['source_snapshot']['size_bytes'], 'Raw source checksum mismatch')
    require(hashlib.sha256(detail).hexdigest() == DETAIL_SHA256, 'Filing-detail checksum mismatch')
    expected = {'ticker': 'JPM', 'cik': 19617, 'accession': REPORT['accession'], 'form': '10-Q',
                'filing_date': REPORT['filing_date'], 'report_date': REPORT['period_end']}
    for meta in (metadata, detail_metadata):
        require(all(meta.get(k) == v for k,v in expected.items()), 'Snapshot identity mismatch')
    require(metadata.get('sha256') == SHA256 and metadata.get('source_url') == URL
            and metadata.get('document') == REPORT['document'] and metadata.get('size_bytes') == len(payload)
            and metadata.get('filing_detail_url') == INDEX
            and metadata.get('filing_detail_sha256') == DETAIL_SHA256, 'Incorrect source metadata')
    require(detail_metadata.get('sha256') == DETAIL_SHA256 and detail_metadata.get('source_url') == INDEX
            and detail_metadata.get('size_bytes') == len(detail), 'Incorrect detail metadata')
    index_text = normalized(BeautifulSoup(detail, 'lxml').get_text(' ', strip=True))
    require(all(t in index_text for t in ('0000019617', REPORT['accession'], '10-Q', '2026-08-06', '2026-06-30', REPORT['document'])), 'Filing-detail identity mismatch')
    soup = source_document(payload)
    verify_tables(data, soup)
    text = normalized(soup.get_text(' ', strip=True))
    for case in data['qualitative_review_cases'] + data['supporting_evidence']:
        for e in case['evidence_locations']:
            require(text[e['start_char']:e['end_char']] == e['quote'], 'Passage is not exact original-source text')
    return {**result, 'source_verified': True, 'source_sha256': SHA256, 'filing_detail_sha256': DETAIL_SHA256}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--oracle', type=Path, default=DEFAULT_PATH)
    args = parser.parse_args()
    data = load_dataset(args.oracle); s = data['source_snapshot']
    result = verify_sources(data, (ROOT/s['path']).read_bytes(), load_dataset(ROOT/s['metadata_path']),
                            (ROOT/s['filing_detail_path']).read_bytes(), load_dataset(ROOT/s['filing_detail_metadata_path']))
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
