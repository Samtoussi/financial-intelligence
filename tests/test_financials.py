
import pytest

from src.analytics.financials import (
    get_annual_financials,
    get_financial_history,
)


@pytest.mark.parametrize(
    "ticker, year",
    [
        ("MSFT", 2017),
        ("CAT", 2024),
        ("JPM", 2024),
    ],
)
def test_supported_companies(ticker, year):
    result = get_annual_financials(ticker, year)

    assert result is not None
    assert result["ticker"] == ticker
    assert result["fiscal_year"] == year
    assert result["revenue_usd"] > 0
    assert result["source_accession"]
    assert result["source_concept"]
    assert result["source_filed_date"]


def test_case_insensitive_ticker():
    result = get_annual_financials("msft", 2017)

    assert result["ticker"] == "MSFT"


def test_non_comparable_period():
    result = get_annual_financials("MSFT", 2016)

    assert result["is_comparable"] is False
    assert result["yoy_growth_pct"] is None


def test_missing_year():
    assert get_annual_financials("MSFT", 1900) is None


def test_unsupported_ticker():
    with pytest.raises(ValueError, match="Unsupported ticker"):
        get_annual_financials("AAPL", 2025)


@pytest.mark.parametrize("year", ["2025", None, True])
def test_invalid_year(year):
    with pytest.raises(ValueError, match="fiscal_year"):
        get_annual_financials("MSFT", year)


@pytest.mark.parametrize("ticker", ["MSFT", "CAT", "JPM"])
def test_financial_history_is_sorted(ticker):
    history = get_financial_history(ticker)

    assert history

    years = [record["fiscal_year"] for record in history]

    assert years == sorted(years)
    assert len(years) == len(set(years))


@pytest.mark.parametrize("ticker", ["MSFT", "CAT", "JPM"])
def test_financial_history_matches_annual_financials(ticker):
    history = get_financial_history(ticker)

    assert history

    for record in history:
        annual = get_annual_financials(
            ticker,
            record["fiscal_year"],
        )

        assert record == annual


def test_financial_history_case_insensitive():
    history = get_financial_history("msft")

    assert history
    assert all(record["ticker"] == "MSFT" for record in history)


def test_financial_history_unsupported_ticker():
    with pytest.raises(ValueError, match="Unsupported ticker"):
        get_financial_history("AAPL")
