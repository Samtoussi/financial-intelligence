
import json
from unittest.mock import patch

import pytest

from src.ai.analyst import execute_tool


def test_financial_tool_dispatch():
    expected = {
        "ticker": "MSFT",
        "fiscal_year": 2025,
        "revenue_usd": 281724000000,
        "yoy_growth_pct": 14.93,
        "is_comparable": True,
    }

    with patch(
        "src.ai.analyst.get_annual_financials",
        return_value=expected,
    ) as mock_financials:
        result = execute_tool(
            "get_annual_financials",
            json.dumps({
                "ticker": "MSFT",
                "fiscal_year": 2025,
            }),
        )

    mock_financials.assert_called_once_with(
        ticker="MSFT",
        fiscal_year=2025,
    )

    assert result == expected


def test_unsupported_ticker():
    with pytest.raises(ValueError, match="Unsupported ticker"):
        execute_tool(
            "get_annual_financials",
            '{"ticker": "AAPL", "fiscal_year": 2025}',
        )


@pytest.mark.parametrize(
    "year",
    [1999, 2031, "2025", True, None],
)
def test_invalid_fiscal_year(year):
    with pytest.raises(ValueError, match="Invalid fiscal year"):
        execute_tool(
            "get_annual_financials",
            json.dumps({
                "ticker": "MSFT",
                "fiscal_year": year,
            }),
        )


def test_unknown_tool():
    with pytest.raises(ValueError, match="Unsupported tool"):
        execute_tool(
            "execute_sql",
            '{"query": "DROP TABLE annual_revenue"}',
        )


def test_extra_arguments_rejected():
    with pytest.raises(
        ValueError,
        match="Invalid financial tool arguments",
    ):
        execute_tool(
            "get_annual_financials",
            json.dumps({
                "ticker": "MSFT",
                "fiscal_year": 2025,
                "database_path": "other.duckdb",
            }),
        )


def test_missing_financial_data():
    with patch(
        "src.ai.analyst.get_annual_financials",
        return_value=None,
    ):
        result = execute_tool(
            "get_annual_financials",
            '{"ticker": "MSFT", "fiscal_year": 2020}',
        )

    assert result is None


def test_filing_search_dispatch():
    expected = [
        {
            "chunk_id": "abc123",
            "ticker": "MSFT",
            "item": "1A",
            "source_url": "https://www.sec.gov/example",
            "text": "Cybersecurity risks may affect operations.",
        }
    ]

    with patch(
        "src.ai.analyst.search_filings",
        return_value=expected,
    ) as mock_search:
        result = execute_tool(
            "search_filings",
            json.dumps({
                "query": "cybersecurity",
                "ticker": "MSFT",
                "limit": 2,
            }),
        )

    mock_search.assert_called_once_with(
        query="cybersecurity",
        ticker="MSFT",
        limit=2,
    )

    assert result == expected
    assert result[0]["chunk_id"] == "abc123"
    assert result[0]["source_url"].startswith("https://")


@pytest.mark.parametrize(
    "query,limit",
    [
        ("", 2),
        ("   ", 2),
        ("risk", 0),
        ("risk", 4),
        ("risk", True),
    ],
)
def test_invalid_search_arguments(query, limit):
    with pytest.raises(ValueError):
        execute_tool(
            "search_filings",
            json.dumps({
                "query": query,
                "ticker": "MSFT",
                "limit": limit,
            }),
        )
