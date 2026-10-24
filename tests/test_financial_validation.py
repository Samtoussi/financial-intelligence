
import pytest

from src.evaluation.financial_validation import (
    validate_financial_answer,
)


@pytest.fixture
def gold_data():
    return {
        "ticker": "MSFT",
        "fiscal_year": 2025,
        "revenue_usd": 281724000000,
        "yoy_growth_pct": 14.93,
        "is_comparable": True,
    }


def test_valid_answer(gold_data):
    assert validate_financial_answer(gold_data, gold_data.copy()) == []


def test_wrong_revenue(gold_data):
    proposed = gold_data.copy()
    proposed["revenue_usd"] = 300000000000

    assert "Mismatch: revenue_usd" in validate_financial_answer(
        gold_data, proposed
    )


def test_wrong_growth(gold_data):
    proposed = gold_data.copy()
    proposed["yoy_growth_pct"] = 25.0

    assert "Mismatch: yoy_growth_pct" in validate_financial_answer(
        gold_data, proposed
    )


def test_wrong_ticker(gold_data):
    proposed = gold_data.copy()
    proposed["ticker"] = "CAT"

    assert "Mismatch: ticker" in validate_financial_answer(
        gold_data, proposed
    )


def test_wrong_fiscal_year(gold_data):
    proposed = gold_data.copy()
    proposed["fiscal_year"] = 2024

    assert "Mismatch: fiscal_year" in validate_financial_answer(
        gold_data, proposed
    )


def test_rounding_tolerance(gold_data):
    proposed = gold_data.copy()
    proposed["yoy_growth_pct"] = 14.934

    assert validate_financial_answer(gold_data, proposed) == []


def test_non_comparable_growth_rejected(gold_data):
    actual = gold_data.copy()
    actual["is_comparable"] = False
    actual["yoy_growth_pct"] = None

    proposed = actual.copy()
    proposed["yoy_growth_pct"] = 14.93

    assert (
        "Growth must be unavailable when data is non-comparable"
        in validate_financial_answer(actual, proposed)
    )


def test_non_comparable_without_growth_accepted(gold_data):
    actual = gold_data.copy()
    actual["is_comparable"] = False
    actual["yoy_growth_pct"] = None

    assert validate_financial_answer(actual, actual.copy()) == []


def test_false_comparability_rejected(gold_data):
    proposed = gold_data.copy()
    proposed["is_comparable"] = False

    assert "Mismatch: is_comparable" in validate_financial_answer(
        gold_data, proposed
    )


def test_missing_data_not_invented():
    assert validate_financial_answer(None, None) == []


def test_missing_data_hallucination():
    proposed = {
        "ticker": "MSFT",
        "fiscal_year": 2030,
        "revenue_usd": 999999999999,
    }

    assert validate_financial_answer(None, proposed)


def test_existing_data_missing_answer(gold_data):
    assert validate_financial_answer(gold_data, None)
