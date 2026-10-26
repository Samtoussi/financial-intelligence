
from src.ai.risk_evidence import validate_risk_claims


def sample_evidence():
    return [
        {
            "ticker": "MSFT",
            "chunk_id": "msft-001",
            "source_url": "https://www.sec.gov/msft",
            "text": "Geopolitical instability may affect operations.",
        },
        {
            "ticker": "CAT",
            "chunk_id": "cat-001",
            "source_url": "https://www.sec.gov/cat",
            "text": "Supply chain disruptions may affect demand.",
        },
    ]


def sample_claim():
    return {
        "ticker": "MSFT",
        "explanation": "Geopolitical instability is an operational risk.",
        "chunk_id": "msft-001",
        "source_url": "https://www.sec.gov/msft",
    }


def test_valid_claim():
    result = validate_risk_claims(
        [sample_claim()],
        sample_evidence(),
    )

    assert len(result) == 1
    assert result[0].ticker == "MSFT"
    assert result[0].chunk_id == "msft-001"


def test_unknown_chunk_rejected():
    claim = sample_claim()
    claim["chunk_id"] = "invented-chunk"

    assert validate_risk_claims(
        [claim],
        sample_evidence(),
    ) == []


def test_wrong_source_url_rejected():
    claim = sample_claim()
    claim["source_url"] = "https://example.com/fake"

    assert validate_risk_claims(
        [claim],
        sample_evidence(),
    ) == []


def test_wrong_ticker_rejected():
    claim = sample_claim()
    claim["ticker"] = "CAT"

    assert validate_risk_claims(
        [claim],
        sample_evidence(),
    ) == []


def test_empty_explanation_rejected():
    claim = sample_claim()
    claim["explanation"] = "   "

    assert validate_risk_claims(
        [claim],
        sample_evidence(),
    ) == []


def test_multiple_valid_claims():
    claims = [
        sample_claim(),
        {
            "ticker": "CAT",
            "explanation": "Supply chain challenges are a risk.",
            "chunk_id": "cat-001",
            "source_url": "https://www.sec.gov/cat",
        },
    ]

    result = validate_risk_claims(
        claims,
        sample_evidence(),
    )

    assert len(result) == 2
    assert {claim.ticker for claim in result} == {"MSFT", "CAT"}


def test_missing_evidence_rejects_claim():
    assert validate_risk_claims(
        [sample_claim()],
        [],
    ) == []


def test_invalid_claim_structure_rejected():
    assert validate_risk_claims(
        [None, {}, "invalid", 123],
        sample_evidence(),
    ) == []
