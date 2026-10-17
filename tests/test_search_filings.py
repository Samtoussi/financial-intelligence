
import pytest

from src.retrieval.search_filings import (
    calculate_score,
    search_filings,
    tokenize,
)


def test_tokenize():
    assert tokenize("Interest-Rate Risk!") == [
        "interest",
        "rate",
        "risk",
    ]


def test_exact_word_matching():
    assert calculate_score(
        ["risk"],
        "Risk management is important.",
    ) > 0

    assert calculate_score(
        ["risk"],
        "Risky investments can be volatile.",
    ) == 0


def test_all_query_terms_required():
    assert calculate_score(
        ["interest", "rate", "risk"],
        "Interest rate exposure increased.",
    ) == 0


def test_phrase_match_bonus():
    exact = calculate_score(
        ["interest", "rate", "risk"],
        "Interest rate risk affects earnings.",
    )

    scattered = calculate_score(
        ["interest", "rate", "risk"],
        "Interest and risk affect the rate.",
    )

    assert exact > scattered


def test_case_insensitive_matching():
    lower = calculate_score(
        ["credit", "losses"],
        "credit losses increased",
    )

    upper = calculate_score(
        ["credit", "losses"],
        "CREDIT LOSSES INCREASED",
    )

    assert lower == upper


def test_empty_query_rejected():
    with pytest.raises(ValueError, match="words"):
        search_filings("!!!")


def test_invalid_limit_rejected():
    with pytest.raises(ValueError, match="positive"):
        search_filings("revenue", limit=0)
