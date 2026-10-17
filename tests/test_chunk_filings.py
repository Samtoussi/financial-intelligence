
import hashlib

import pytest

from src.transformation.chunk_filings import create_chunks


def make_section(text):
    return {
        "ticker": "TEST",
        "cik": 12345,
        "accession": "0000000000-26-000001",
        "filing_date": "2026-01-01",
        "report_date": "2025-12-31",
        "form": "10-K",
        "item": "7",
        "source_url": "https://www.sec.gov/example",
        "text": text,
    }


def test_exact_text_reconstruction():
    text = "Revenue increased significantly. " * 1000
    chunks = create_chunks(make_section(text))

    assert " ".join(c["text"] for c in chunks) == text
    assert all(
        text[c["start_char"]:c["end_char"]] == c["text"]
        for c in chunks
    )


def test_chunk_word_limit():
    text = "Financial performance improved. " * 1000
    chunks = create_chunks(make_section(text))

    assert all(0 < c["words"] <= 350 for c in chunks)


def test_long_sentence_fallback():
    text = " ".join(["financial"] * 1000)
    chunks = create_chunks(make_section(text))

    assert len(chunks) > 1
    assert all(c["words"] <= 350 for c in chunks)
    assert " ".join(c["text"] for c in chunks) == text


def test_stable_chunk_ids():
    text = "Operating revenue increased. " * 500
    section = make_section(text)

    first = create_chunks(section)
    second = create_chunks(section)

    assert [c["chunk_id"] for c in first] == [
        c["chunk_id"] for c in second
    ]


def test_section_hash():
    text = "Risk disclosure. " * 500
    chunks = create_chunks(make_section(text))

    expected_hash = hashlib.sha256(
        text.encode("utf-8")
    ).hexdigest()

    assert all(
        c["section_sha256"] == expected_hash
        for c in chunks
    )


def test_empty_section_rejected():
    with pytest.raises(ValueError, match="empty"):
        create_chunks(make_section(""))


def test_invalid_chunk_configuration():
    with pytest.raises(ValueError, match="Invalid"):
        create_chunks(
            make_section("Financial results."),
            target_words=400,
            max_words=350,
        )
