"""Offline M001 validation; no network or model calls."""
import argparse
import json
import re
import sys
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
from pathlib import Path

DEFAULT_PATH = Path(__file__).resolve().parents[2] / 'evals/ground_truth/msft_fy2027_q1.json'
SOURCE = 'https://www.sec.gov/Archives/edgar/data/789019/000119312526436133/msft-20260930.htm'
IDS = {'revenue', 'operating_income', 'net_income', 'diluted_eps',
       'agents_and_infra_revenue', 'devices_and_consumer_revenue'}
PERIODS = {
    'current': {'fiscal_period': 'FY2027 Q1', 'start': '2026-07-01', 'end': '2026-09-30'},
    'prior': {'fiscal_period': 'FY2026 Q1', 'start': '2025-07-01', 'end': '2025-09-30'},
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def number(value):
    require(isinstance(value, str) and re.fullmatch(r'\d+(?:\.\d+)?', value),
            'value must be a finite nonnegative decimal string')
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError('invalid decimal value') from exc
    require(result.is_finite() and result > 0, 'M001 values must be positive')
    return result


def yoy(current, prior):
    """Return percentage change, rounding only the display to one decimal."""
    with localcontext() as ctx:
        ctx.prec = 50
        change = (number(current) - number(prior)) / number(prior) * Decimal(100)
        return format(change.quantize(Decimal('0.1'), rounding=ROUND_HALF_UP), '.1f')


def citation(source, fields, url=SOURCE):
    require(isinstance(source, dict), 'missing citation')
    for field in fields:
        require(isinstance(source.get(field), str) and source[field].strip(),
                f'missing citation {field}')
    require(source.get('url') == url, 'incorrect citation URL')


def validate(data):
    """Raise ValueError for invalid M001 data; return computed YoY displays."""
    try:
        return _validate(data)
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError(f'missing or malformed dataset field: {exc}') from exc


def _validate(data):
    require(data['schema_version'] == 1 and data['milestone'] == 'M001', 'invalid schema')
    report = data['report']
    expected = {'company': 'Microsoft Corporation', 'cik': '0000789019', 'form': '10-Q',
                'fiscal_period': 'FY2027 Q1', 'period_end': '2026-09-30',
                'filing_date': '2026-10-28', 'accession': '0001193125-26-436133',
                'source_url': SOURCE}
    require(all(report.get(k) == v for k, v in expected.items()), 'inconsistent report metadata')
    require(date.fromisoformat(report['filing_date']) >= date.fromisoformat(report['period_end']),
            'filing precedes period end')
    citation(report['filing_date_source'], ('url', 'section', 'location'),
             'https://microsoft.gcs-web.com/financial-information/sec-filings')
    require(data['periods'] == PERIODS, 'inconsistent report periods')
    metrics = data['metrics']
    require(isinstance(metrics, list), 'metrics must be a list')
    ids = [m['id'] for m in metrics]
    require(len(ids) == len(set(ids)), 'duplicate metric IDs')
    require(set(ids) == IDS, 'missing or unexpected metric IDs')
    values, changes = {}, {}
    for metric in metrics:
        mid = metric['id']
        eps = mid == 'diluted_eps'
        segment = mid.endswith('_revenue')
        require(metric['unit'] == ('USD per share' if eps else 'USD millions'), 'inconsistent units')
        require(metric['gaap_status'] == ('GAAP segment disclosure' if segment else 'GAAP'),
                'inconsistent GAAP status')
        citation(metric.get('source'), ('url', 'section', 'table', 'row', 'columns'))
        require(type(metric['source'].get('page')) is int and metric['source']['page'] > 0,
                'missing citation page')
        values[mid] = {}
        for period in PERIODS:
            observation = metric[period]
            require(observation['period'] == PERIODS[period], 'inconsistent metric periods')
            value = number(observation['value'])
            require(value == value.quantize(Decimal('0.01') if eps else Decimal('1')),
                    'invalid value precision for unit')
            values[mid][period] = value
        changes[mid] = yoy(metric['current']['value'], metric['prior']['value'])
    for period in PERIODS:
        require(values['agents_and_infra_revenue'][period] + values['devices_and_consumer_revenue'][period]
                == values['revenue'][period], f'incorrect segment total: {period}')
        require(values['net_income'][period] <= values['operating_income'][period] <= values['revenue'][period],
                f'inconsistent income ordering: {period}')
    cases = data['qualitative_review_cases']
    require(len(cases) == 3 and {c['id'] for c in cases} == {
        'gaap_vs_non_gaap', 'recast_segment_comparability', 'azure_growth_vs_cloud_margin'},
        'invalid qualitative cases')
    for case in cases:
        require(case['status'] == 'pending_manual_review' and case['conclusion'] is None,
                'M001 qualitative conclusions require manual review')
        require(isinstance(case['question'], str) and case['question'].strip(), 'missing review question')
        require(case['evidence_locations'], 'missing review evidence locations')
        for evidence in case['evidence_locations']:
            citation(evidence, ('url', 'section', 'location'))
            require(type(evidence.get('page')) is int and evidence['page'] > 0, 'missing evidence page')
    return changes


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, f'duplicate JSON key: {key}')
        result[key] = value
    return result


def load_dataset(path=DEFAULT_PATH):
    return json.loads(Path(path).read_text(encoding='utf-8'), object_pairs_hook=unique_object)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('path', nargs='?', type=Path, default=DEFAULT_PATH)
    args = parser.parse_args()
    try:
        changes = validate(load_dataset(args.path))
    except (ValueError, OSError) as exc:
        print(f'INVALID: {exc}', file=sys.stderr)
        return 1
    print(json.dumps({'valid': True, 'metric_count': len(changes), 'yoy_percent': changes,
                      'manual_review_pending': 3}, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
