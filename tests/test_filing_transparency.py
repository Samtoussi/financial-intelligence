from types import SimpleNamespace
from unittest.mock import patch

from src.ai.response_builder import format_risk_claims
from src.retrieval.filing_metadata import get_filing_metadata


def test_missing_metadata_returns_none(tmp_path):
    with patch("src.retrieval.filing_metadata.SECTIONS_DIR", tmp_path):
        get_filing_metadata.cache_clear()
        assert get_filing_metadata("0000000000-26-000001") is None
        get_filing_metadata.cache_clear()


def test_risk_claim_displays_matching_filing_period():
    claim = SimpleNamespace(
        ticker="MSFT", explanation="Cybersecurity exposure.",
        chunk_id="msft-001", source_url="https://www.sec.gov/example",
    )
    evidence = [{
        "ticker": "MSFT", "chunk_id": "msft-001",
        "source_url": "https://www.sec.gov/example",
        "accession": "0001193125-26-323660",
        "filing_metadata": {
            "ticker": "MSFT", "accession": "0001193125-26-323660",
            "form": "10-K", "report_date": "2026-06-30",
            "filing_date": "2026-07-29",
        },
    }]
    text = format_risk_claims([claim], evidence)
    assert "reporting period ending 2026-06-30" in text
    assert "Filed: 2026-07-29" in text
    assert "Accession: 0001193125-26-323660" in text


def test_risk_claim_does_not_invent_filing_period():
    claim = SimpleNamespace(
        ticker="MSFT", explanation="Cybersecurity exposure.",
        chunk_id="msft-001", source_url="https://www.sec.gov/example",
    )
    text = format_risk_claims([claim], [])
    assert "reporting period" not in text
    assert "Filed:" not in text
