
import pytest

from src.analytics.financial_summary import (
    format_financial_summary,
    format_financial_summaries,
    format_usd,
)


@pytest.fixture
def microsoft():
    return {
        "ticker": "MSFT",
        "fiscal_year": 2025,
        "revenue_usd": 281724000000,
        "yoy_growth_pct": 14.93,
        "is_comparable": True,
        "period_start": "2024-07-01",
        "period_end": "2025-06-30",
        "source_concept": (
            "RevenueFromContractWithCustomerExcludingAssessedTax"
        ),
        "source_accession": "0001193125-26-323660",
        "source_filed_date": "2026-07-29",
    }


def test_usd_formatting():
    assert format_usd(281724000000) == "$281.724B"


def test_usd_rejects_boolean():
    with pytest.raises(ValueError):
        format_usd(True)


def test_financial_summary(microsoft):
    summary = format_financial_summary(microsoft)

    assert "Microsoft (MSFT), 2025" in summary
    assert "Revenue: $281.724B" in summary
    assert "YoY growth: +14.93%" in summary
    assert "2024-07-01 to 2025-06-30" in summary
    assert "0001193125-26-323660" in summary
    assert "filed 2026-07-29" in summary


def test_non_comparable_growth(microsoft):
    microsoft["is_comparable"] = False
    microsoft["yoy_growth_pct"] = None

    summary = format_financial_summary(microsoft)

    assert "YoY growth: unavailable or non-comparable" in summary
    assert "14.93%" not in summary


def test_missing_growth(microsoft):
    microsoft["yoy_growth_pct"] = None

    summary = format_financial_summary(microsoft)

    assert "YoY growth: unavailable or non-comparable" in summary


def test_multiple_companies(microsoft):
    caterpillar = microsoft.copy()
    caterpillar["ticker"] = "CAT"
    caterpillar["revenue_usd"] = 67589000000
    caterpillar["yoy_growth_pct"] = 4.29

    summary = format_financial_summaries(
        [microsoft, caterpillar]
    )

    assert "Microsoft (MSFT)" in summary
    assert "Caterpillar (CAT)" in summary
    assert summary.count("Revenue:") == 2


def test_empty_evidence():
    assert format_financial_summaries([]) == ""


def test_invalid_growth_type(microsoft):
    microsoft["yoy_growth_pct"] = "14.93"

    with pytest.raises(ValueError):
        format_financial_summary(microsoft)
