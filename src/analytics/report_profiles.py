"""Pinned Microsoft and Caterpillar filings. Configuration only: no oracle values."""
from copy import deepcopy

REPORT = {
    "ticker": "MSFT", "cik": 789019, "form": "10-Q",
    "accession": "0001193125-26-436133", "fiscal_period": "FY2027 Q1",
    "period_start": "2026-07-01", "period_end": "2026-09-30",
    "prior_start": "2025-07-01", "prior_end": "2025-09-30",
    "filing_date": "2026-10-28", "document": "msft-20260930.htm",
    "source_url": "https://www.sec.gov/Archives/edgar/data/789019/000119312526436133/msft-20260930.htm",
}
METRICS = {
    "revenue": ("Total revenue", "USD millions", "GAAP"),
    "operating_income": ("Operating income", "USD millions", "GAAP"),
    "net_income": ("Net income", "USD millions", "GAAP"),
    "diluted_eps": ("Diluted", "USD per share", "GAAP"),
    "agents_and_infra_revenue": ("Agents and Infra", "USD millions", "GAAP segment disclosure"),
    "devices_and_consumer_revenue": ("Devices and Consumer", "USD millions", "GAAP segment disclosure"),
}
NOTE_IDS = ("gaap_vs_non_gaap", "recast_segment_comparability", "azure_growth_vs_cloud_margin")


TOPICS = {
    NOTE_IDS[0]: "Distinguish reported earnings from adjusted measures.",
    NOTE_IDS[1]: "Assess the basis for prior segment comparisons.",
    NOTE_IDS[2]: "Distinguish Azure revenue growth from Cloud gross margin percentage.",
}
BOUNDARIES = [
    ("income_statement", "I.1", None, r"Refer to accompanying notes", True),
    ("segment_table", "I.1", r"Segment revenue, cost of revenue, operating expenses", r"No sales to an individual country", False),
    ("recast_disclosure", "I.1", r"Recast of Certain Prior Period Information", r"Estimates and Assumptions", False),
    ("management_summary", "I.2", r"(?:FINANCI\s*AL\s+SUMMARY|SUMMARY RESULTS OF OPERATIONS)", r"\nOPERATING EXPENSES\n", False),
]
DEFAULT_PROFILE = "msft_fy2027_q1"
PROFILES = {DEFAULT_PROFILE: {"id": DEFAULT_PROFILE, "report": REPORT, "metrics": METRICS,
    "topics": TOPICS, "boundaries": BOUNDARIES, "ground_truth": "msft_fy2027_q1.json"}}
second = deepcopy(PROFILES[DEFAULT_PROFILE])
second.update(id="msft_fy2026_q1", ground_truth="msft_fy2026_q1.json")
second["report"].update(accession="0001193125-25-256321", fiscal_period="FY2026 Q1",
    period_start="2025-07-01", period_end="2025-09-30", prior_start="2024-07-01", prior_end="2024-09-30",
    filing_date="2025-10-29", document="msft-20250930.htm",
    source_url="https://www.sec.gov/Archives/edgar/data/789019/000119312525256321/msft-20250930.htm")
second["metrics"] = dict(list(METRICS.items())[:4])
second["metrics"].update({
    "productivity_and_business_processes_revenue": ("Productivity and Business Processes", "USD millions", "GAAP segment disclosure"),
    "intelligent_cloud_revenue": ("Intelligent Cloud", "USD millions", "GAAP segment disclosure"),
    "more_personal_computing_revenue": ("More Personal Computing", "USD millions", "GAAP segment disclosure"),
})
second["topics"] = {
    "gaap_vs_non_gaap": TOPICS["gaap_vs_non_gaap"],
    "segment_comparability": "Assess the segment reporting basis for both periods using Note 16; do not infer an undisclosed recast.",
    "azure_growth_vs_cloud_margin": TOPICS["azure_growth_vs_cloud_margin"],
}
second["boundaries"][1] = ("segment_table", "I.1", BOUNDARIES[1][2], r"No sales to an individual customer or country", False)
second["boundaries"][2] = ("segment_basis", "I.1", r"NOTE 16 . SEGMENT INFORMATION AND GEOGRAPHIC DATA", r"Our reportable segments are described below", False)
PROFILES[second["id"]] = second


def get_profile(profile=DEFAULT_PROFILE):
    # Resolve only named configurations, never arbitrary caller data.
    return deepcopy(PROFILES[profile])


def profile_for_accession(accession):
    matches = [key for key, value in PROFILES.items() if value["report"]["accession"] == accession]
    if len(matches) != 1:
        raise ValueError("Unsupported filing accession")
    return matches[0]


def table_context(profile):
    report = profile["report"]
    return (profile.get('table_period', "Three Months Ended September 30"), report["period_end"][:4], report["prior_end"][:4], "millions")


def segment_ids(config):
    if config.get('bindings'):
        return [mid for mid, binding in config['bindings'].items() if binding['role'] == 'segment']
    return [mid for mid in config['metrics'] if mid.endswith('_revenue')]


# M005: configuration contains source selectors, never expected financial values.
cat = {
    'id': 'cat_2026_q1', 'ground_truth': 'cat_2026_q1.json', 'contract': 'm005-v1',
    'company': 'Caterpillar Inc.', 'display_company': 'Caterpillar',
    'table_period': 'Three Months Ended March 31', 'prior_fiscal_period': 'FY2025 Q1',
    'report': {'ticker': 'CAT', 'cik': 18230, 'form': '10-Q',
        'accession': '0000018230-26-000021', 'fiscal_period': 'FY2026 Q1',
        'period_start': '2026-01-01', 'period_end': '2026-03-31',
        'prior_start': '2025-01-01', 'prior_end': '2025-03-31',
        'filing_date': '2026-05-06', 'document': 'cat-20260331.htm',
        'source_url': 'https://www.sec.gov/Archives/edgar/data/18230/000001823026000021/cat-20260331.htm'},
    'metrics': {
        'revenue': ('Total sales and revenues', 'USD millions', 'GAAP'),
        'operating_income': ('Operating profit', 'USD millions', 'GAAP'),
        'net_income': ('Profit 1', 'USD millions', 'GAAP attributable to common shareholders'),
        'diluted_eps': ('Profit per common share \u2013 diluted 2', 'USD per share', 'GAAP'),
        'power_and_energy_revenue': ('Power & Energy', 'USD millions', 'Segment total including intersegment'),
        'construction_industries_revenue': ('Construction Industries', 'USD millions', 'Segment total including intersegment'),
        'resource_industries_revenue': ('Resource Industries', 'USD millions', 'Segment total including intersegment'),
        'financial_products_revenue': ('Financial Products Segment', 'USD millions', 'Segment total including intersegment'),
    },
    'boundaries': [
        ('income_statement', 'I.1', r'Consolidated Statement of Results of Operations', r'Consolidated Statement of Comprehensive Income', False),
        ('segment_table', 'I.1', r'\| Sales and Revenues by Geographic Region', r'For the three months ended March 31, 2026 and 2025, Power & Energy external sales', False),
        ('segment_basis', 'I.1', r'16\. Segment information', r'B\. Description of segments', False),
        ('management_summary', 'I.2', r'Highlights for the first quarter of 2026 include:', r'Trends and Economic Conditions', False),
    ],
    'topics': {
        'gaap_vs_non_gaap': 'Distinguish GAAP diluted EPS from adjusted EPS and explain only the disclosed restructuring adjustment for both periods.',
        'segment_comparability': 'Explain the retrospective adjustment of 2025 segment figures and the January 2026 rail-business transfer; do not compare unrecast values.',
        'sales_volume_and_price': 'Explain the disclosed sales-volume and price-realization contributions to consolidated revenue growth; avoid extrapolation or unsupported causes.',
    },
    'topic_windows': {'gaap_vs_non_gaap': ['management_summary'],
        'segment_comparability': ['segment_basis'], 'sales_volume_and_price': ['management_summary']},
    'presentation': {'takeaway': 'sales_volume_and_price',
        'labels': {'revenue': 'Sales and revenues', 'operating_income': 'Operating profit',
                   'net_income': 'Profit attributable to common shareholders', 'diluted_eps': 'Diluted EPS'}},
}
cat['bindings'] = {mid: {'window': 'income_statement', 'role': 'headline', 'layout': 'paired_row'}
                   for mid in list(cat['metrics'])[:4]}
cat['bindings'].update({mid: {'window': 'segment_table', 'role': 'segment', 'layout': 'period_blocks', 'column': 'total'}
                        for mid in list(cat['metrics'])[4:]})
cat['reconciliation_rows'] = [v[0] for v in list(cat['metrics'].values())[4:]] + [
    'Total sales and revenues from reportable segments', 'All Other Segment',
    'Corporate Items and Eliminations', 'Total Sales and Revenues']
PROFILES[cat['id']] = cat
