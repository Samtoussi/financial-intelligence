"""Two observed Microsoft filings. Configuration only: no oracle values."""
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
    # Resolve only the two named configurations, never arbitrary caller data.
    return deepcopy(PROFILES[profile])


def profile_for_accession(accession):
    matches = [key for key, value in PROFILES.items() if value["report"]["accession"] == accession]
    if len(matches) != 1:
        raise ValueError("Unsupported filing accession")
    return matches[0]


def table_context(profile):
    report = profile["report"]
    return ("Three Months Ended September 30", report["period_end"][:4], report["prior_end"][:4], "millions")
