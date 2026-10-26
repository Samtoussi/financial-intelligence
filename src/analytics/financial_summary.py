
from collections.abc import Iterable
from numbers import Real


COMPANY_NAMES = {
    "MSFT": "Microsoft",
    "CAT": "Caterpillar",
    "JPM": "JPMorgan Chase",
}


def format_usd(value: int | float) -> str:
    """Format a USD amount in billions without recalculating it."""

    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError("USD amount must be numeric")

    return f"${value / 1_000_000_000:,.3f}B"


def format_financial_summary(evidence: dict) -> str:
    """Format one governed Gold financial result."""

    ticker = evidence["ticker"]
    fiscal_year = evidence["fiscal_year"]
    revenue = evidence["revenue_usd"]
    growth = evidence["yoy_growth_pct"]
    comparable = evidence["is_comparable"]

    company = COMPANY_NAMES.get(ticker, ticker)

    lines = [
        f"{company} ({ticker}), {fiscal_year}",
        f"Revenue: {format_usd(revenue)}",
    ]

    if comparable is True and growth is not None:
        if isinstance(growth, bool) or not isinstance(growth, Real):
            raise ValueError("Growth must be numeric")

        lines.append(f"YoY growth: {growth:+.2f}%")
    else:
        lines.append("YoY growth: unavailable or non-comparable")

    lines.append(
        "Reporting period: "
        f"{evidence['period_start']} to {evidence['period_end']}"
    )

    lines.append(
        "Source: "
        f"{evidence['source_concept']}, "
        f"SEC accession {evidence['source_accession']} "
        f"(filed {evidence['source_filed_date']})"
    )

    return "\n".join(lines)


def format_financial_summaries(
    financial_evidence: Iterable[dict],
) -> str:
    """Format multiple governed Gold results."""

    return "\n\n".join(
        format_financial_summary(item)
        for item in financial_evidence
    )
