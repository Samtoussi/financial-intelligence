
from types import SimpleNamespace

from src.ai.response_builder import format_risk_claims


def make_claim(chunk_id, explanation, source_url):
    return SimpleNamespace(
        ticker="MSFT",
        chunk_id=chunk_id,
        explanation=explanation,
        source_url=source_url,
    )


def make_evidence(chunk_id, accession, report_date, source_url):
    return {
        "ticker": "MSFT",
        "chunk_id": chunk_id,
        "accession": accession,
        "source_url": source_url,
        "filing_metadata": {
            "accession": accession,
            "form": "10-K",
            "report_date": report_date,
            "filing_date": "2026-07-29",
        },
        "text": "SEC risk passage",
    }


def test_same_filing_metadata_appears_once():
    url = "https://www.sec.gov/msft-2026"

    claims = [
        make_claim("chunk-1", "Cyberattack risk.", url),
        make_claim("chunk-2", "Supply chain risk.", url),
    ]

    evidence = [
        make_evidence("chunk-1", "accession-2026", "2026-06-30", url),
        make_evidence("chunk-2", "accession-2026", "2026-06-30", url),
    ]

    output = format_risk_claims(claims, evidence)

    assert output.count("Filing: 10-K") == 1
    assert output.count("Accession: accession-2026") == 1
    assert "1. Cyberattack risk." in output
    assert "2. Supply chain risk." in output
    assert "Chunk: chunk-1" in output
    assert "Chunk: chunk-2" in output
    assert output.count(f"Source: {url}") == 2


def test_different_filings_have_separate_groups():
    url_2025 = "https://www.sec.gov/msft-2025"
    url_2026 = "https://www.sec.gov/msft-2026"

    claims = [
        make_claim("chunk-1", "Risk from 2025.", url_2025),
        make_claim("chunk-2", "Risk from 2026.", url_2026),
    ]

    evidence = [
        make_evidence(
            "chunk-1",
            "accession-2025",
            "2025-06-30",
            url_2025,
        ),
        make_evidence(
            "chunk-2",
            "accession-2026",
            "2026-06-30",
            url_2026,
        ),
    ]

    output = format_risk_claims(claims, evidence)

    assert output.count("Filing: 10-K") == 2
    assert "Accession: accession-2025" in output
    assert "Accession: accession-2026" in output
    assert output.count("1. Risk from") == 2


def test_missing_metadata_preserves_risk_sources():
    url = "https://www.sec.gov/msft"

    claims = [
        make_claim("chunk-1", "Cybersecurity risk.", url),
    ]

    evidence = [
        {
            "ticker": "MSFT",
            "chunk_id": "chunk-1",
            "source_url": url,
            "text": "SEC risk passage",
        }
    ]

    output = format_risk_claims(claims, evidence)

    assert "Cybersecurity risk." in output
    assert "Chunk: chunk-1" in output
    assert f"Source: {url}" in output
    assert "Filing: 10-K" not in output


def test_empty_claims_return_empty_output():
    assert format_risk_claims([], []) == ""
