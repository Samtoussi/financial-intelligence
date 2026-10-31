"""Bounded selectors for the observed paired-row and CAT period-block tables.

No oracle imports. Offsets and quotations always address unchanged section text.
"""
import re
from decimal import Decimal

NUMBER = r'(?:-?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?|\(\s*(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?\s*\)|—)'


def token_value(token):
    token = token.strip()
    if not re.fullmatch(NUMBER, token):
        raise ValueError('Unsupported source numeric token')
    if token == '—':
        return Decimal(0)
    negative = token.startswith('(')
    return Decimal(token.strip('() ').replace(',', '').replace(' ', '')) * (-1 if negative else 1)


def row(text, label):
    matches = list(re.finditer(r'(?m)^\s*\|\s*' + re.escape(label) + r'\s*\|[^\n]*', text))
    if len(matches) != 1:
        raise ValueError('Missing or ambiguous source row: ' + label)
    return matches[0]


def row_tokens(match):
    cells = [c.strip() for c in match[0].strip().strip('|').split('|')][1:]
    cells = [c for c in cells if c and c != '$']
    if not all(re.fullmatch(NUMBER, c) for c in cells):
        raise ValueError('Unsupported source row cell')
    return cells


def period_blocks(text, config):
    title = config['table_period']
    years = [config['report'][k][:4] for k in ('period_end', 'prior_end')]
    matches = list(re.finditer(r'(?m)^\|\s*' + re.escape(title) + r', (\d{4})\s*\|[^\n]*', text))
    if [m[1] for m in matches] != years:
        raise ValueError('Unsupported period-block columns')
    if not all(term in text[:matches[0].start()] for term in (
            'Millions of dollars', 'External Sales and Revenues',
            'Intersegment Sales and Revenues', 'Total Sales and Revenues')):
        raise ValueError('Missing segment columns/units')
    end = text.find('\n1 Includes revenues', matches[1].end())
    if end < 0:
        raise ValueError('Missing observed Financial Products footnote')
    return [(m.end(), text[m.end():stop]) for m, stop in
            zip(matches, (matches[1].start(), end))]


def selected_pair(text, label, binding, config):
    """Return values and exact source ranges; select columns, never scrape all numbers."""
    if binding['layout'] == 'paired_row':
        header = text[:row(text, config['metrics']['revenue'][0]).start()]
        if (re.findall(r'(?<!\d)(?:19|20)\d{2}(?!\d)', header) !=
                [config['report'][k][:4] for k in ('period_end', 'prior_end')]
                or config['table_period'] not in header
                or 'millions except per share data' not in header):
            raise ValueError('Unsupported statement header')
        m = row(text, label)
        tokens = row_tokens(m)
        if len(tokens) != 2:
            raise ValueError('Unsupported paired source values')
        return [token_value(t) for t in tokens], [(m.start(), m.end())], tokens
    result, ranges, tokens = [], [], []
    for offset, block in period_blocks(text, config):
        m = row(block, label)
        cells = row_tokens(m)
        # CAT's Financial Products external column has a separately rendered footnote 1.
        if label == 'Financial Products Segment':
            if len(cells) != 8 or cells[5] != '1':
                raise ValueError('Changed Financial Products footnote layout')
            cells.pop(5)
        if len(cells) != 7:
            raise ValueError('Unsupported geographic source columns')
        index = {'external': 4, 'intersegment': 5, 'total': 6}[binding['column']]
        tokens.append(cells[index]); result.append(token_value(cells[index]))
        ranges.append((offset + m.start(), offset + m.end()))
    return result, ranges, tokens


def reconciliation_values(text, config):
    return [{'label': label, **{column: [str(v) for v in selected_pair(text, label,
                {'layout': 'period_blocks', 'column': column}, config)[0]]
            for column in ('external', 'intersegment', 'total')}}
            for label in config['reconciliation_rows']]


def check_reconciliation(rows, revenue):
    if len(rows) != 8 or len({r['label'] for r in rows}) != 8:
        raise ValueError('Incomplete reconciliation')
    for p in range(2):
        for r in rows:
            if Decimal(r['external'][p]) + Decimal(r['intersegment'][p]) != Decimal(r['total'][p]):
                raise ValueError('External/intersegment identity failed')
        for col in ('external', 'intersegment', 'total'):
            v = [Decimal(r[col][p]) for r in rows]
            if sum(v[:4]) != v[4] or v[4] + v[5] + v[6] != v[7]:
                raise ValueError('Segment reconciliation failed')
        if Decimal(rows[-1]['intersegment'][p]) != 0 or Decimal(rows[-1]['total'][p]) != Decimal(revenue[p]):
            raise ValueError('Consolidated revenue reconciliation failed')
