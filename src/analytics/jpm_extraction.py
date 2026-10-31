"""Bounded JPM Q2 2026 source extraction, without oracle or AI dependencies.

This is an extraction contract only, not a report-generation profile. Evidence
uses the existing registry's section-relative offsets and hash conventions.
"""
import hashlib
import re
from decimal import Decimal, ROUND_HALF_UP, localcontext

from src.transformation.parse_filings import parse_html, jpm_quarterly_sections
from src.transformation.chunk_filings import create_chunks

SOURCE = {
    'ticker': 'JPM', 'cik': 19617, 'form': '10-Q',
    'accession': '0001628280-26-054343', 'filing_date': '2026-08-06',
    'report_date': '2026-06-30',
    'source_url': 'https://www.sec.gov/Archives/edgar/data/19617/000162828026054343/jpm-20260630.htm',
}
SOURCE_SHA256 = '75e02668ad64cef396ee9f9b10a8982f70f8e1c6879b833be9eae0e02f599d6b'
FLOWS = {
    'total_net_revenue': 'Total net revenue', 'net_interest_income': 'Net interest income',
    'noninterest_revenue': 'Noninterest revenue', 'net_income': 'Net income',
    'diluted_eps': 'Diluted earnings per share', 'provision_for_credit_losses': 'Provision for credit losses',
}
FLOW_PERIODS = ({'start': '2026-04-01', 'end': '2026-06-30'},
                {'start': '2025-04-01', 'end': '2025-06-30'})
STOCK_PERIODS = ({'as_of': '2026-06-30'}, {'as_of': '2025-12-31'})
# Regexes select observed headings/rows, never expected financial values.
WINDOWS = (
    ('income_statement', 'I.1', r'(?m)^Consolidated statements of income \(unaudited\)',
     r'(?m)^Consolidated statements of comprehensive income'),
    ('balance_sheet', 'I.1', r'(?m)^Consolidated balance sheets \(unaudited\)',
     r'(?m)^Consolidated statements of changes'),
    ('reported_to_managed', 'I.2', r'The Firm prepares its Consolidated Financial Statements in accordance with U.S. GAAP',
     r'(?m)^\| \| Six months ended June 30,'),
    ('credit_highlights', 'I.2', r'(?m)^Consolidated financial highlights \(unaudited\)', r'(?m)^\| INTRODUCTION'),
    ('credit_context', 'I.2', r'Quarterly results\nThe provision for credit losses was',
     r'(?m)^Year-to-date results'),
    ('allowance_scope', 'I.2', r'(?m)^\| Allowance for credit losses and related information',
     r'(?m)^Allocation of allowance for loan losses'),
    ('significant_items', 'I.2', r"The Firm's results included a", r'equity investments in Corporate and CIB\.'),
)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def _one(pattern, text):
    matches = list(re.finditer(pattern, text))
    require(len(matches) == 1, 'Missing/ambiguous JPM source boundary: ' + pattern)
    return matches[0]


def build_evidence(sections, metadata):
    """Bind independently resolved section windows; no financial expectations."""
    require(all(metadata.get(k) == v for k, v in SOURCE.items()), 'Unsupported JPM source identity')
    require(metadata.get('sha256') == SOURCE_SHA256, 'Unsupported JPM source checksum')
    by_item = {s['item']: s for s in sections}
    require(len(sections) == 2 and set(by_item) == {'I.1', 'I.2'}, 'Missing/duplicate JPM sections')
    for s in sections:
        require(all(s.get(k) == v for k, v in SOURCE.items()), 'JPM section accession/identity mismatch')
    chunks = {item: create_chunks(s) for item, s in by_item.items()}
    evidence = []
    for label, item, opening, closing in WINDOWS:
        section = by_item[item]['text']
        start = _one(opening, section).start()
        # Resolve the closing within this window, not relative to another item.
        tail = section[start:]
        if label in {'reported_to_managed', 'credit_context'}:
            end_match = re.search(closing, tail)
            require(end_match is not None, 'Missing JPM quarter/YTD boundary')
        else:
            end_match = _one(closing, tail)
        end = start + (end_match.end() if label == 'significant_items' else end_match.start())
        text = section[start:end]
        require(40 <= len(text) <= 25000, 'Invalid bounded JPM evidence window')
        sh = hashlib.sha256(section.encode()).hexdigest()
        identity = f"{SOURCE['accession']}|{item}|{sh}|{start}|{end}"
        evidence.append({**SOURCE, 'label': label, 'item': item,
            'evidence_id': hashlib.sha256(identity.encode()).hexdigest()[:24],
            'source_sha256': metadata['sha256'], 'section_sha256': sh,
            'chunk_ids': [c['chunk_id'] for c in chunks[item]
                          if c['start_char'] < end and c['end_char'] > start],
            'text_sha256': hashlib.sha256(text.encode()).hexdigest(),
            'start_char': start, 'end_char': end, 'text': text})
    return evidence


def _row(evidence, pattern, count):
    matches = []
    for match in re.finditer(r'(?m)^\|.*$', evidence['text']):
        cells = [c.strip() for c in match[0].split('|') if c.strip()]
        if cells and re.fullmatch(pattern, cells[0]):
            tokens = [c for c in cells[1:] if c not in {'$', '%'}]
            require(len(tokens) == count, 'Incorrect JPM source column count')
            values = []
            for token in tokens:
                require(token in {'NA', '\u2014'} or re.fullmatch(r'\(?\s*\d[\d,]*(?:\.\d+)?\s*\)?', token), 'Invalid JPM source number/unit')
                values.append(token if token == 'NA' else '0' if token == '\u2014' else str(Decimal(
                    ('-' if token.startswith('(') else '') + token.strip('() ').replace(' ', '').replace(',', ''))))
            matches.append((cells[0], values, match))
    require(len(matches) == 1, 'Missing/ambiguous JPM statement row: ' + pattern)
    label, values, match = matches[0]
    return label, values, {'evidence_id': evidence['evidence_id'],
        'start_char': evidence['start_char'] + match.start(),
        'end_char': evidence['start_char'] + match.end(), 'quote': match[0]}


def _header(text, expected, message):
    compact = re.sub(r'[|\s]+', ' ', text).strip()
    require(expected in compact, message)


def loan_balances(evidence):
    """Exact separately presented allowance and net loans, with source rows.

    Supplementary assembly inputs; preserves the existing extraction bundle.
    """
    balance = next(e for e in evidence if e['label'] == 'balance_sheet')
    result = {}
    for key, label in (('signed_allowance', 'Allowance for loan losses'),
                       ('net_loans', 'Loans, net of allowance for loan losses')):
        _, values, citation = _row(balance, re.escape(label), 2)
        result[key] = {'values': values, 'citation': citation}
    return result


def extract_values(evidence):
    """Select quarter flows and dated stocks from validated source windows.

    Consumers must verify source membership with validate_extraction before
    using a serialized bundle. extract_jpm constructs windows from pinned bytes.
    """
    e = {x['label']: x for x in evidence}
    require(len(evidence) == len(WINDOWS) and set(e) == {w[0] for w in WINDOWS}, 'Incorrect JPM evidence set')
    income, balance = e['income_statement'], e['balance_sheet']
    _header(income['text'].split('| Revenue')[0],
        'Three months ended June 30, Six months ended June 30, (in millions, except per share data) 2026 2025 2026 2025',
        'Wrong JPM quarter duration, units or column years')
    _header(balance['text'].split('| Assets')[0],
        '(in millions, except share data) June 30, 2026 December 31, 2025', 'Wrong JPM balance dates/units')
    metrics = []
    selections = [(mid, re.escape(label), income, 4, 'flow') for mid, label in FLOWS.items()]
    selections += [('total_loans', r'Loans \(included \$ [\d,]+ and \$ [\d,]+ at fair value\)', balance, 2, 'point_in_time'),
                   ('total_deposits', r'Deposits \(included \$ [\d,]+ and \$ [\d,]+ at fair value\)', balance, 2, 'point_in_time')]
    for mid, pattern, window, count, kind in selections:
        label, values, cite = _row(window, pattern, count)
        if mid == 'total_deposits':
            require(window['text'].index('| Liabilities') < window['text'].index(cite['quote']), 'Deposits must be liability, not bank asset')
        if mid == 'total_loans':
            require(window['text'].index('| Assets') < window['text'].index(cite['quote']) < window['text'].index('| Liabilities'), 'Loans must be consolidated asset')
        require(all(Decimal(v) > 0 for v in values[:2]), 'Invalid nonpositive JPM metric')
        unit = 'USD per share' if mid == 'diluted_eps' else 'USD millions'
        require(all(re.fullmatch(r'\d+\.\d{2}' if mid == 'diluted_eps' else r'\d+', v) for v in values[:2]), 'Incorrect JPM financial precision')
        periods = FLOW_PERIODS if kind == 'flow' else STOCK_PERIODS
        with localcontext() as ctx:
            ctx.prec = 50
            change = str(((Decimal(values[0])-Decimal(values[1]))/Decimal(values[1])*100).quantize(Decimal('.1'), rounding=ROUND_HALF_UP))
        metrics.append({'id': mid, 'label': label, 'unit': unit, 'basis': 'GAAP reported', 'kind': kind,
            'current': {'value': values[0], 'period': dict(periods[0])},
            'prior': {'value': values[1], 'period': dict(periods[1])},
            'source_columns': [0, 1], 'excluded_columns': [2, 3] if kind == 'flow' else [],
            'comparison': 'yoy' if kind == 'flow' else 'since_year_end', 'change_percent': change, 'citation': cite})
    pairs = {m['id']: [Decimal(m[p]['value']) for p in ('current', 'prior')] for m in metrics}
    for i in range(2):
        require(pairs['net_interest_income'][i] + pairs['noninterest_revenue'][i] == pairs['total_net_revenue'][i], 'JPM reported revenue identity failed')
    bridge = e['reported_to_managed']
    _header(bridge['text'], 'Three months ended June 30, 2026 2025 (in millions, except ratios) Reported Fully taxable-equivalent adjustments (a) Managed basis Reported Fully taxable-equivalent adjustments (a) Managed basis', 'Wrong JPM reported/managed quarter columns/units')
    bridges = {}
    for mid, label in [('noninterest_revenue', 'Total noninterest revenue'), ('net_interest_income', 'Net interest income'), ('total_net_revenue', 'Total net revenue')]:
        _, v, cite = _row(bridge, re.escape(label), 6)
        for i in range(2):
            require(Decimal(v[i*3]) == pairs[mid][i] and Decimal(v[i*3])+Decimal(v[i*3+1]) == Decimal(v[i*3+2]), 'JPM reported/FTE/managed bridge failed')
        bridges[mid] = {'values': v, 'unit': 'USD millions', 'columns': ['reported', 'fte_adjustment', 'managed']*2, 'citation': cite}
    for col in range(6):
        require(Decimal(bridges['noninterest_revenue']['values'][col])+Decimal(bridges['net_interest_income']['values'][col]) == Decimal(bridges['total_net_revenue']['values'][col]), 'JPM basis component identity failed')
    _, ni, _ = _row(bridge, 'Net income', 6)
    require(ni == [str(pairs['net_income'][0]), 'NA', str(pairs['net_income'][0]), str(pairs['net_income'][1]), 'NA', str(pairs['net_income'][1])], 'JPM managed net-income neutrality failed')
    credit = e['credit_highlights']
    _header(credit['text'], '2Q26 1Q26 4Q25 3Q25 2Q25 2026 2025', 'Wrong JPM credit observation dates')
    _header(credit['text'], '(in millions, except per share, ratio, employee data and where otherwise noted)', 'Wrong JPM credit units')
    _, nco, nco_cite = _row(credit, 'Net charge-offs', 7)
    _, acl, acl_cite = _row(credit, 'Allowances for credit losses', 7)
    context = e['credit_context']['text']
    additions = []
    for paragraph in (r'Quarterly results\n[^\n]+', r'(?m)^In the prior year, [^\n]+'):
        passage = _one(paragraph, context)[0]
        additions.append(_one(r'net addition to the allowance for credit losses was \$(\d+) million', passage)[1])
    for i, col in enumerate((0, 4)):
        require(pairs['provision_for_credit_losses'][i]-Decimal(nco[col]) == Decimal(additions[i]), 'JPM provision/charge-off/net-addition mismatch')
    allowance = e['allowance_scope']
    _header(allowance['text'], '2026 2025 Six months ended June 30, Consumer, excluding credit card Credit card Wholesale Total Consumer, excluding credit card Credit card Wholesale Total (in millions, except ratios)', 'Wrong JPM allowance period/scope/units')
    components = {}
    for key, label in [('loan_losses', 'Total allowance for loan losses'), ('commitments', 'Total allowance for lending-related commitments'), ('securities', 'Total allowance for investment securities'), ('principal_total', 'Total allowance for credit losses (b)')]:
        _, vals, cite = _row(allowance, re.escape(label), 8)
        components[key] = {'value': vals[3], 'citation': cite}
    footnote = re.search(r'At June 30, 2026 and 2025, in addition to the allowance for credit losses in the table above, the Firm also had an allowance for credit losses of \$(\d+) million and \$(\d+) million, respectively, associated with certain accounts receivable in CIB\.', allowance['text'])
    require(footnote is not None, 'Missing dated CIB allowance scope footnote')
    require(sum(Decimal(components[k]['value']) for k in ('loan_losses', 'commitments', 'securities')) == Decimal(components['principal_total']['value']), 'JPM principal allowance scope failed')
    require(Decimal(components['principal_total']['value'])+Decimal(footnote[1]) == Decimal(acl[0]), 'JPM broad allowance scope failed')
    _, ll, _ = _row(balance, 'Allowance for loan losses', 2)
    _, net, _ = _row(balance, 'Loans, net of allowance for loan losses', 2)
    require(Decimal(components['loan_losses']['value']) == -Decimal(ll[0]), 'JPM loan allowance scope mismatch')
    for i in range(2):
        require(pairs['total_loans'][i]+Decimal(ll[i]) == Decimal(net[i]), 'JPM gross/net loan scope failed')
    return {'metrics': metrics, 'reported_to_managed': bridges,
        'credit': {'unit': 'USD millions', 'net_charge_offs': [nco[0], nco[4]], 'net_charge_off_periods': [dict(p) for p in FLOW_PERIODS],
            'net_additions': [additions[0], additions[-1]], 'firmwide_allowance': [acl[0], acl[2]],
            'allowance_dates': [dict(p) for p in STOCK_PERIODS], 'current_components': components,
            'current_cib_receivables_allowance': footnote[1], 'citations': [nco_cite, acl_cite]},
        'reconciliations_pass': True, 'limitations': ['Not a complete allowance stock rollforward.',
            'No numerical business-segment reporting or adjusted earnings calculation.']}


def validate_extraction(bundle, payload, metadata):
    """Reject changed values, periods, units, identities or unsupported spans."""
    require(all(metadata.get(k) == v for k, v in SOURCE.items()), 'Unsupported JPM source identity')
    require(hashlib.sha256(payload).hexdigest() == metadata.get('sha256') == SOURCE_SHA256, 'JPM original source checksum mismatch')
    sections = jpm_quarterly_sections(parse_html(payload), metadata)
    evidence = build_evidence(sections, metadata)
    expected = {'contract': 'm006-jpm-extraction-v1', 'source': dict(metadata), 'sections': sections,
                'evidence': evidence, **extract_values(evidence)}
    require(bundle == expected, 'JPM extraction is not supported by the pinned original source')
    return True


def extract_jpm(payload, metadata):
    require(all(metadata.get(k) == v for k, v in SOURCE.items()), 'Unsupported JPM source identity')
    require(hashlib.sha256(payload).hexdigest() == metadata.get('sha256') == SOURCE_SHA256, 'JPM original source checksum mismatch')
    sections = jpm_quarterly_sections(parse_html(payload), metadata)
    evidence = build_evidence(sections, metadata)
    return {'contract': 'm006-jpm-extraction-v1', 'source': dict(metadata), 'sections': sections,
            'evidence': evidence, **extract_values(evidence)}
