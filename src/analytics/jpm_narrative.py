"""Bounded banking narrative safeguards, not a semantic-entailment model.

Facts come from deterministic source extraction, never the independent oracle.
No text repairs. Human semantic review remains mandatory.
"""
import re
from decimal import Decimal, ROUND_HALF_UP

from src.analytics.narrative_money import MONEY, NUMBER, validate_monetary_narrative

VERSION = 'm006-narrative-v2'
ROLES = {
    'net_interest_income': r'net interest income',
    'noninterest_revenue': r'noninterest (?:revenue|income)',
    'total_net_revenue': r'(?:(?:GAAP|reported|headline)(?: reported| GAAP)? (?:total )?(?:net )?revenue|total net revenue|net revenue|revenue)',
    'managed_revenue': r'managed(?:[- ]basis)? (?:total )?(?:net )?revenue|(?:net )?revenue on (?:a )?managed basis',
    'managed_net_interest_income': r'managed(?:[- ]basis)? net interest income',
    'managed_noninterest_revenue': r'managed(?:[- ]basis)? noninterest revenue',
    'net_income': r'net income|net profit', 'diluted_eps': r'(?:diluted )?EPS|earnings per (?:common )?share',
    'provision_for_credit_losses': r'provision(?:s| expense| for credit losses)?',
    'net_charge_offs': r'net charge[- \u2010\u2011\u2012\u2013]offs',
    'net_additions': r'net addition(?:s)?(?: to (?:the )?allowance(?: for credit losses)?)?',
    'firmwide_allowance': r'(?:firmwide|broad)(?: allowance)?(?: allowance for credit losses| allowance)|allowance (?:balance|stock)s?',
    'loan_allowance': r'loan(?: loss)? allowance|allowance for loan losses',
    'total_loans': r'(?:total |balance[- ]sheet )?loans', 'net_loans': r'net loans',
    'total_deposits': r'(?:total |deposit )?deposits|deposit liabilities',
    'fte_adjustment': r'(?:FTE|fully taxable[- ]equivalent) adjustments?',
    'visa_gain': r'Visa(?:[- ]related)?(?: (?:net )?gain)?|net gain (?:related to|on) Visa(?: shares)?',
    'equity_gains': r'(?:certain )?equity investment(?:s| gains)?',
    'principal_allowance': r'principal allowance(?: table)?(?: total)?',
    'cib_allowance': r'CIB (?:accounts )?receivables allowance',
}


def facts_for(prepared):
    facts = []
    def add(role, value, unit, citations, year):
        dimension = 'USD/share' if unit == 'USD per share' else 'percent' if unit == 'percent' else 'USD'
        v = Decimal(value) * (1000000 if dimension == 'USD' else 1)
        ids = sorted({c['evidence_id'] for c in citations})
        facts.append({'role': role, 'value': str(v), 'dimension': dimension, 'year': year, 'evidence_ids': ids})
        if dimension == 'USD':
            rounded = (v/Decimal(1000000000)).quantize(Decimal('.1'), rounding=ROUND_HALF_UP)*1000000000
            facts.append({'role': role, 'value': str(rounded), 'dimension': dimension, 'year': year, 'evidence_ids': ids})
    f = prepared['financial_foundation']
    for m in f['metrics']:
        for p, year in (('current', '2026'), ('prior', '2025')):
            add(m['id'], m[p], m['unit'], m['citations'], year)
        add(m['id'], m['change_percent'], 'percent', m['citations'], '2026')
    for r in f['reconciliation']:
        year = (r['period'].get('as_of') or r['period']['end'])[:4]
        rid = r['id']
        if rid.startswith('managed:'):
            role = {'total_net_revenue': 'managed_revenue', 'noninterest_revenue': 'managed_noninterest_revenue',
                    'net_interest_income': 'managed_net_interest_income'}[rid.split(':')[1]]
            add(role, r['result'], r['unit'], r['citations'], year)
            add('fte_adjustment', r['operands'][1]['value'], r['unit'], r['citations'], year)
            add('fte_adjustment:' + rid.split(':')[1], r['operands'][1]['value'], r['unit'], r['citations'], year)
        if rid.startswith('credit_net_addition:'):
            add('net_charge_offs', r['operands'][1]['value'], r['unit'], [r['citations'][1]], year)
            add('net_additions', r['result'], r['unit'], [r['citations'][-1]], year)
        if rid.startswith('net_loans:'):
            add('loan_allowance', r['operands'][1]['value'], r['unit'], [r['citations'][1]], year)
            add('net_loans', r['result'], r['unit'], [r['citations'][2]], year)
        if rid.startswith('firmwide_allowance:'):
            for i, (role, t) in enumerate(zip(('principal_allowance', 'cib_allowance'), r['operands'])):
                add(role, t['value'], r['unit'], [r['citations'][i]], year)
    stock = f['allowance_stock']
    for p, year in (('current', '2026'), ('prior', '2025')):
        add('firmwide_allowance', stock[p], stock['unit'], stock['citations'], year)
    # Supplemental significant items are deterministic disclosures, not new
    # headline metrics. Bind amounts only to their own original source window.
    sig = next(c for c in f['source_context'] if c['id'] == 'significant_items')['citations']
    quote = sig[0]['quote']
    for role, pattern in (
        ('visa_gain', r'\$(\d+(?:\.\d+)?) billion net gain related to Visa'),
        ('equity_gains', r'\$(\d+(?:\.\d+)?) billion of gains on certain equity investments')):
        match = re.search(pattern, quote)
        if not match: raise ValueError('Missing significant-item source amount')
        add(role, str(Decimal(match[1])*1000), 'USD millions', sig, '2026')
    return facts


def _sentences(text):
    return re.split(r'(?<!\d)[.!?]|[.!?](?!\d)|\n', text)


def _negated(clause):
    return bool(re.search(r'\b(?:not|no|never|neither|unchanged|rather than)\b|non[- ]recurring', clause, re.I))


def _fte_role(text, start):
    # Bind the adjustment and resulting balance separately. No amounts are
    # embedded here: typed facts retain measure, period and source eligibility.
    measure = r'(total net revenue|noninterest revenue|net interest income)'
    amount = rf'\${NUMBER}\s+(?:million|billion)'
    pattern = (rf'FTE adjustments? increased {measure} by (?P<adjustment>{amount})'
               rf' to (?:a )?managed total of (?P<total>{amount})')
    for match in re.finditer(pattern, text, re.I):
        metric = {'total net revenue':'total_net_revenue', 'noninterest revenue':'noninterest_revenue',
                  'net interest income':'net_interest_income'}[match[1].lower()]
        if match.start('adjustment') <= start < match.end('adjustment'):
            return 'fte_adjustment:' + metric
        if match.start('total') <= start < match.end('total'):
            return {'total_net_revenue':'managed_revenue', 'noninterest_revenue':'managed_noninterest_revenue',
                    'net_interest_income':'managed_net_interest_income'}[metric]
        # Component amounts inherit adjustment context only inside the immediate
        # parenthesized, signed breakdown of this explicit FTE construction.
        tail = text[match.end():]
        group = re.match(r'\s*\(([^()]*)\)', tail)
        if group:
            for component in re.finditer(rf'{measure}\s+\+(?P<value>{amount})', group[1], re.I):
                offset = match.end() + group.start(1)
                if offset + component.start('value') <= start < offset + component.end('value'):
                    return 'fte_adjustment:' + {'total net revenue':'total_net_revenue',
                        'noninterest revenue':'noninterest_revenue', 'net interest income':'net_interest_income'}[component[1].lower()]
    return None


def _role(text, start, end):
    fte = _fte_role(text, start)
    if fte: return fte
    left = re.split(r'(?<!\d)[.!?;]|[.!?;](?!\d)', text[:start])[-1]
    candidates = []
    for role, pattern in ROLES.items():
        for m in re.finditer(pattern, left, re.I): candidates.append((m.end(), len(m[0]), role))
    right = re.split(r'(?<!\d)[.!?;]|[.!?;](?!\d)', text[end:])[0][:90]
    postfix = []
    for role, pattern in ROLES.items():
        m = re.search(pattern, right, re.I)
        if m: postfix.append((-m.start(), len(m[0]), role))
    # "Net income includes $4.6 billion Visa gains" names an embedded item,
    # not a $4.6 billion net-income total. Only bounded linking phrases may
    # switch to a postfixed measure; comparisons retain their shared subject.
    if postfix and (not candidates or re.search(r'\b(?:includes?|included|including|contains?|with|alongside|and|plus)\s+(?:a\s+)?$', left, re.I)):
        return max(postfix)[2]
    return max(candidates)[2] if candidates else None


def _year(text, start, end):
    left = re.split(r'(?<!\d)[.!?;]|[.!?;](?!\d)', text[:start])[-1][-120:]
    right = re.split(r'(?<!\d)[.!?;]|[.!?;](?!\d)', text[end:])[0][:80]
    # A later amount owns its own date qualifier; never borrow across it.
    next_amount = MONEY.search(right)
    if next_amount: right = right[:next_amount.start()]
    before = list(re.finditer(r'\b20\d{2}\b', left)); after = re.search(r'\b20\d{2}\b', right)
    if after and (not before or after.start() < len(left)-before[-1].end()): return after[0]
    return before[-1][0] if before else None


def validate_text(text, facts, quotes):
    failures = []
    supported = {(f['dimension'], Decimal(f['value'])) for f in facts if f['dimension'] != 'percent'}
    money = validate_monetary_narrative(text, quotes, supported_values=supported)
    if not money['automatic_pass']: failures.append('monetary_scale_or_value')
    numbers = []
    for c in money['claims']:
        numbers.append((c['start_char'], c['end_char'], Decimal(c['canonical_value']), c['dimension']))
    for m in re.finditer(rf'(?P<n>{NUMBER})\s*(?:%|percent\b|basis points\b|bps\b)', text, re.I):
        # No capital ratio/bps contract in this report.
        numbers.append((m.start(), m.end(), Decimal(m['n'].replace(',', '')), 'bps' if re.search(r'basis|bps', m[0], re.I) else 'percent'))
    for start, end, value, dimension in numbers:
        role = _role(text, start, end)
        year = _year(text, start, end)
        if dimension == 'percent' and re.search(r'\b(?:since|versus|from|compared with)\b', text[end:end+45], re.I):
            year = None  # This date identifies the comparison base, not the current observation.
        if not any(f['role'] == role and f['dimension'] == dimension and Decimal(f['value']) == value
                   and (year is None or f['year'] == year) for f in facts):
            failures.append('number_measure_or_dimension_binding')
    # Explicit arithmetic uses the displayed operands, never hidden unrounded
    # values. Separately disclosed rounded observations are not an equation.
    claims = money['claims']
    for a, b, c in zip(claims, claims[1:], claims[2:]):
        gap1 = text[a['end_char']:b['start_char']]
        gap2 = text[b['end_char']:c['start_char']]
        if (re.search(r'\bminus\b|\bless\b|\s[-?]\s', gap1, re.I)
                and re.search(r'\bequals?\b|\byields?\b|\bgives?\b|\bresults? in\b|\bresulting in\b|=', gap2, re.I)
                and not re.search(r'[;!?]|(?<!\d)\.|\.(?!\d)', gap1 + gap2)):
            if (a['dimension'] != b['dimension'] or b['dimension'] != c['dimension']
                    or Decimal(a['canonical_value']) - Decimal(b['canonical_value']) != Decimal(c['canonical_value'])):
                failures.append('false_explicit_arithmetic')
    # Catch unqualified/bare financial figures; dates/years are not money.
    dates = [(m.start(), m.end()) for m in re.finditer(r'20(?:25|26)-\d{2}-\d{2}|(?:April|June|December)\s+(?:1|30|31),?\s+20(?:25|26)|\b20(?:25|26)\b', text)]
    for m in re.finditer(rf'(?<![\w.]){NUMBER}(?!\w|\.\d)', text):
        if not any(a <= m.start() and m.end() <= b for a, b, *_ in numbers) and not any(a <= m.start() and m.end() <= b for a,b in dates):
            failures.append('unqualified_or_unsupported_number')
    normalized_quotes = ' '.join(re.sub(r'\W+', ' ', q.lower()) for q in quotes)
    for sentence in _sentences(text):
        fte_context = False
        for clause in re.split(r'\bbut\b|\bhowever\b|;', sentence, flags=re.I):
            negated = _negated(clause)
            fte_context |= bool(re.search(r'FTE|fully taxable', clause, re.I))
            if not negated:
                if fte_context and re.search(r'(?:increas|boost|rais|improv|reduc|chang)\w*.{0,45}(?:net income|EPS)', clause, re.I): failures.append('fte_net_income')
                if re.search(r'(?:credit quality.{0,25}(?:improv|strong|better)|(?:improv|better|strong).{0,25}credit quality)', clause, re.I): failures.append('unsupported_credit_quality')
                if (re.search(r'Visa|gain', clause, re.I) and re.search(r'\brecurring\b|core (?:profit|earnings)|operating earnings', clause, re.I)
                        and not re.search(r'(?:separate(?:ly)?|distinct|distinguish\w*)\b.{0,35}\bfrom\b.{0,30}recurring', clause, re.I)): failures.append('recurring_gain')
                if re.search(r'adjusted (?:net income|profit|EPS|earnings)|would have|earnings without|excluding (?:the )?(?:Visa |these |disclosed )?gains', clause, re.I): failures.append('invented_adjusted_earnings')
                if re.search(r'six[- ]month|year[- ]to[- ]date|\bYTD\b|first half', clause, re.I): failures.append('quarter_ytd')
                if re.search(r'loans|deposits|balances', clause, re.I) and re.search(r'YoY|year.over.year', clause, re.I): failures.append('balance_comparison')
                if re.search(r'loans|deposits|balances', clause, re.I) and re.search(r'June 30,? 2025|2025-06-30', clause, re.I): failures.append('balance_comparison')
                if (re.search(r'(?:headline|total) loans (?:are|mean|represent).{0,15}(?:net|retained|average)|deposit liabilities (?:are|mean).{0,15}deposits with banks', clause, re.I)
                        and not re.search(r'distinct from|separate from', clause, re.I)): failures.append('balance_scope')
                if re.search(r'complete.{0,20}allowance rollforward|fully reconciles.{0,20}allowance', clause, re.I): failures.append('invented_rollforward')
            for cause in re.finditer(r'\b(?:because|due to|driven by|caused by|resulted from|reflecting)\s+(.+)', clause, re.I):
                predicate = re.sub(r'\W+', ' ', cause[1].lower()).strip()
                if not negated and predicate not in normalized_quotes: failures.append('unsupported_causal_claim')
    return {'automatic_pass': not failures, 'failures': sorted(set(failures)), 'monetary': money}


def validate_notes(raw, prepared):
    from src.analytics.report_profiles import get_profile
    topics = get_profile('jpm_2026_q2')['topics']
    failures = []; details = []
    if not isinstance(raw, dict) or set(raw) != {'notes'} or not isinstance(raw['notes'], list):
        return {'validation_version': VERSION, 'automatic_pass': False, 'failures': ['Invalid narrative schema'], 'notes': []}
    spans = {s['span_id']: s for s in prepared['spans']}; facts = facts_for(prepared); seen = set()
    for n in raw['notes']:
        if (not isinstance(n, dict) or set(n) != {'id', 'text', 'span_ids'} or n.get('id') not in topics
                or n['id'] in seen or not isinstance(n['text'], str) or not n['text'].strip()
                or not isinstance(n['span_ids'], list) or not n['span_ids']):
            failures.append('Invalid/missing/duplicate note'); continue
        seen.add(n['id'])
        selected = [spans.get(sid) for sid in n['span_ids'] if isinstance(sid, str)]
        if len(selected) != len(n['span_ids']) or any(s is None or s['claim_id'] != n['id'] for s in selected):
            failures.append('Unknown or cross-topic citation: '+n['id']); continue
        labels = {s['source_label'] for s in selected}
        # Legacy defining-source annotations are descriptive, never substitutes
        # for structured citations. Validate each exact label against selection.
        annotations = list(re.finditer(r'\bDefining source:\s*([A-Za-z0-9_]+)\.', n['text']))
        prose = n['text']
        for annotation in reversed(annotations):
            defining = {'reported_vs_managed':'reported_to_managed', 'credit_loss_measures':'credit_context',
                        'significant_earnings_items':'significant_items'}[n['id']]
            if annotation[1] != defining or annotation[1] not in labels:
                failures.append('Unsupported source label: ' + n['id'])
            prose = prose[:annotation.start()] + prose[annotation.end():]
        if (re.search(r'https?://|[\[\]<>`*\\|]|(?<!\w)_(?=\w)|(?<=\w)_(?!\w)', prose)
                or re.search(r'\b(?:defining source|source|reference|citation)\s*:', prose, re.I)):
            failures.append('Unsupported inline reference or markup: '+n['id'])
        ids = {s['evidence_id'] for s in selected}
        mandatory = {'reported_vs_managed':'reported_to_managed', 'credit_loss_measures':'credit_context',
                     'significant_earnings_items':'significant_items'}[n['id']]
        if mandatory not in {s['source_label'] for s in selected}:
            failures.append('Missing topic-defining source: '+n['id'])
        supported = [f for f in facts if ids.intersection(f['evidence_ids'])]
        result = validate_text(n['text'], supported, [s['quote'] for s in selected])
        details.append({'id': n['id'], **result})
        failures += [n['id']+': '+f for f in result['failures']]
    if seen != set(topics): failures.append('Missing required topics')
    return {'validation_version': VERSION, 'automatic_pass': not failures, 'failures': failures, 'notes': details,
        'limitations': 'Bounded numeric/accounting/causal checks are not complete semantic entailment. Human review is required.'}
