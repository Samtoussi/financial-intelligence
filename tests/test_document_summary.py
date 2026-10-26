
from src.analytics.document_summary import (
    format_document_summaries,
)


def make_passage(
    ticker="MSFT",
    chunk_id="chunk-001",
    text="Cybersecurity incidents may disrupt operations.",
):
    return {
        "ticker": ticker,
        "chunk_id": chunk_id,
        "item": "Item 1A",
        "source_url": "https://www.sec.gov/example",
        "text": text,
    }


def test_empty_evidence():
    assert format_document_summaries([]) == ""


def test_formats_document_passage():
    result = format_document_summaries(
        [make_passage()]
    )

    assert "SEC filing excerpts" in result
    assert "MSFT — Item 1A" in result
    assert "Cybersecurity incidents" in result
    assert "Chunk: chunk-001" in result
    assert "Source: https://www.sec.gov/example" in result


def test_multiple_companies():
    result = format_document_summaries(
        [
            make_passage("MSFT", "msft-001"),
            make_passage(
                "CAT",
                "cat-001",
                "Supply chain disruptions may affect production.",
            ),
        ]
    )

    assert "MSFT — Item 1A" in result
    assert "CAT — Item 1A" in result
    assert "Supply chain disruptions" in result


def test_duplicate_chunks_removed():
    passage = make_passage()

    result = format_document_summaries(
        [passage, passage]
    )

    assert result.count("Chunk: chunk-001") == 1


def test_missing_source_rejected():
    passage = make_passage()
    passage.pop("source_url")

    assert format_document_summaries([passage]) == ""


def test_whitespace_normalized():
    result = format_document_summaries(
        [
            make_passage(
                text="Cybersecurity\n\n incidents   may disrupt operations."
            )
        ]
    )

    assert (
        "Cybersecurity incidents may disrupt operations."
        in result
    )


def test_invalid_evidence_ignored():
    result = format_document_summaries(
        [
            None,
            {},
            make_passage(),
        ]
    )

    assert result.count("Chunk: chunk-001") == 1
