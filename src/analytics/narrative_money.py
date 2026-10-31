"""Bounded monetary-unit checks for the observed CAT narrative evidence.

This checks value/dimension support, not full semantic entailment. It never
rewrites narrative or quotations, and never reads an evaluation oracle.
"""
import re
from decimal import Decimal

VERSION = 'cat-narrative-money-v2'
NUMBER = r'-?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?'
SCALE = r'(?:thousand|million|billion|mn|bn|m|b)\b'
MONEY = re.compile(
    rf'(?:(?:US\$|\$|USD\s+)\s*(?P<prefixed>{NUMBER})(?!\d|\.\d|,\d)'
    rf'|(?P<worded>{NUMBER})\s+(?=(?:{SCALE}\s+)?(?:dollars|USD)\b))', re.I)
FACTORS = {'thousand': Decimal(1000), 'million': Decimal(1000000),
           'billion': Decimal(1000000000), 'mn': Decimal(1000000),
           'bn': Decimal(1000000000), 'm': Decimal(1000000), 'b': Decimal(1000000000)}
SHARE = r'(?:per[\s\-\u2011]+(?:common\s+)?share|/\s*share)\b'
EPS_PREFIX = re.compile(r'(?:\bEPS|\b(?:profit|earnings) per (?:common )?share)\b[^$;.!?]{0,90}$', re.I)
# Only coordination can share a trailing qualifier or a preceding EPS subject.
# Parentheses/new subjects prevent a nearby EPS mention from qualifying costs.
JOIN = re.compile(r'\s*(?:in\s+(?:Q[1-4]\s+)?20\d{2}\s*)?(?:and|versus|vs\.?|,)\s*$', re.I)
# EPS alone may retain its established dimension across these explicit temporal
# comparisons. Full matching excludes a new subject such as restructuring costs;
# aggregate scales continue to use the narrower JOIN contract above.
MONTH = r'(?:January|February|March|April|May|June|July|August|September|October|November|December)'
DATE = (rf'(?:20\d{{2}}|Q[1-4]\s+20\d{{2}}|{MONTH}\s+\d{{1,2}},?\s+20\d{{2}}|'
        rf'(?:the\s+)?(?:three months|quarter)\s+ended\s+{MONTH}\s+\d{{1,2}},?\s+20\d{{2}}|'
        r'(?:the\s+)?(?:first|second|third|fourth)\s+quarter\s+of\s+20\d{2})')
EPS_COMPARISON = re.compile(
    rf'\s*(?:(?:in|for|during)\s+{DATE}\s*)?'
    r'(?:and|versus|vs\.?|compared\s+(?:with|to)|against)\s*$', re.I)


def _number(value):
    return Decimal(value.replace(',', ''))


def _suffix(text, end):
    tail = text[end:]
    scale = re.match(rf'\s*({SCALE})', tail, re.I)
    if scale:
        dimension = ('USD/share' if re.match(rf'\s*(?:dollars?\s+)?{SHARE}', tail[scale.end():], re.I) else 'USD')
        return dimension, FACTORS[scale[1].lower()]
    if re.match(rf'\s*(?:dollars?\s+)?{SHARE}', tail, re.I):
        return 'USD/share', Decimal(1)
    if re.match(r'\s*(?:in\s+)?(?:diluted\s+)?(?:EPS|earnings per share|profit per share)\b', tail, re.I):
        return 'USD/share', Decimal(1)
    if re.match(r'\s*(?:dollars|USD)\b', tail, re.I):
        return 'USD', Decimal(1)
    return None


def _source_values(quotes):
    supported = set()
    for quote in quotes:
        # Explicit scales in prose are source units; do not inherit a table's
        # millions header into surrounding narrative or its EPS columns.
        for match in MONEY.finditer(quote):
            unit = _suffix(quote, match.end())
            if unit:
                supported.add((unit[0], _number(match['prefixed'] or match['worded']) * unit[1]))
        # Observed CAT Highlights adjustment table: two periods, each with
        # Profit Before Taxes (USD millions), then Profit Per Share (USD/share).
        header = re.search(r'(?m)^\| \(Dollars in millions except per share data\)'
            r' \| Profit Before Taxes \| Profit Per Share \| \| Profit Before Taxes \| Profit Per Share[^\n]*', quote)
        if not header:
            continue
        table = quote[header.end():].split('A detailed reconciliation')[0]
        for label in ('Profit', 'Restructuring (income) costs', 'Adjusted profit'):
            rows = re.findall(r'(?m)^\| ' + re.escape(label) + r' \|([^\n]*)', table)
            if len(rows) != 1:
                continue
            cells = [v.strip() for v in rows[0].strip('| ').split('|') if v.strip() and v.strip() != '$']
            if len(cells) != 4 or not all(re.fullmatch(NUMBER, v) for v in cells):
                continue
            for i, cell in enumerate(cells):
                supported.add(('USD/share' if i % 2 else 'USD',
                               _number(cell) * (1 if i % 2 else 1000000)))
    return supported


def validate_monetary_narrative(text, quotes):
    """Return a diagnostic; source citation validation remains the caller's job.

    Supports currency-prefixed amounts and amounts written in dollars/USD.
    Unknown or unsupported monetary expressions fail; percentages and bare years
    are not currency claims. Human review still checks meaning and attribution.
    """
    matches = list(MONEY.finditer(text))
    supported = _source_values(quotes)
    claims, errors = [], []
    resolved = []
    for i, match in enumerate(matches):
        amount = _number(match['prefixed'] or match['worded'])
        unit = _suffix(text, match.end())
        # A qualifier can apply to a short coordinated list: $41 and $33 million.
        j = i
        while unit is None and j + 1 < len(matches) and JOIN.fullmatch(text[matches[j].end():matches[j+1].start()]):
            j += 1
            unit = _suffix(text, matches[j].end())
        # Parenthesized unit declarations apply to this clause, not the document.
        prefix = re.split(r'[;!?]|(?<!\d)\.|\.(?!\d)', text[:match.start()])[-1]
        if unit is None:
            declaration = re.search(r'\((?:in\s+)?(?:USD|dollars in)\s+(thousands|millions|billions)\)[^()]*$', prefix, re.I)
            if declaration:
                unit = ('USD', FACTORS[declaration[1].lower().rstrip('s')])
        if EPS_PREFIX.search(prefix):
            unit = ('USD/share', unit[1] if unit else Decimal(1))
        if unit is None and i:
            gap = text[matches[i-1].end():match.start()]
            gap = re.sub(rf'^\s*(?:{SCALE}(?:\s+dollars)?|{SHARE}|dollars)\s*', '', gap, count=1, flags=re.I)
            if JOIN.fullmatch(gap):
                unit = resolved[-1]
            elif (resolved[-1] == ('USD/share', Decimal(1))
                  and claims[-1]['source_supported'] and len(gap) <= 128
                  and EPS_COMPARISON.fullmatch(gap)):
                unit = resolved[-1]
        # Without a contextual scale, a dollar amount means actual dollars.
        # $41 cannot match a cited 41-million-dollar cell. Fully expanded dollar
        # values can match, e.g. $41,000,000 or 41000000 dollars.
        unit = unit or ('USD', Decimal(1))
        resolved.append(unit)
        canonical = amount * unit[1]
        ok = (unit[0], canonical) in supported
        claim = {'text': text[match.start():match.end()], 'start_char': match.start(),
                 'end_char': match.end(), 'dimension': unit[0],
                 'canonical_value': str(canonical), 'source_supported': ok}
        claims.append(claim)
        if not ok:
            errors.append({**claim, 'reason': 'Monetary amount/scale is absent from cited evidence in this dimension; state source-supported units explicitly.'})
    for marker in re.finditer(r'US\$|\$|\bUSD(?=\s+[-\d])', text, re.I):
        if not any(m.start() <= marker.start() < m.end() for m in matches):
            errors.append({'text': marker[0], 'start_char': marker.start(), 'end_char': marker.end(),
                           'reason': 'Unsupported monetary syntax; use explicit numeric amounts and source-supported units.'})
    return {'validation_version': VERSION, 'automatic_pass': not errors,
            'claims': claims, 'errors': errors,
            'limitations': 'Bounded monetary value/dimension support, not full semantic entailment or period/causal verification.'}
