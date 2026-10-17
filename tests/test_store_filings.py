
import hashlib

import pyarrow.parquet as pq
import pytest

from src.transformation.store_filings import save_sections


def make_records():
    records = []

    for item in ("1A", "7"):
        text = f"Financial disclosure for Item {item}. " * 30

        records.append(
            {
                "ticker": "TEST",
                "cik": 12345,
                "accession": "0000000000-26-000001",
                "filing_date": "2026-01-01",
                "report_date": "2025-12-31",
                "form": "10-K",
                "item": item,
                "source_url": "https://www.sec.gov/example",
                "extraction_method": "direct",
                "text": text,
                "characters": len(text),
                "words": len(text.split()),
                "text_sha256": hashlib.sha256(
                    text.encode("utf-8")
                ).hexdigest(),
            }
        )

    return records


def test_sections_saved_as_parquet(tmp_path):
    records = make_records()

    path = save_sections("TEST", records, tmp_path)

    assert path.exists()

    table = pq.read_table(path)

    assert table.num_rows == 2
    assert set(table.column("item").to_pylist()) == {"1A", "7"}


def test_repeated_save_is_idempotent(tmp_path):
    records = make_records()

    first = save_sections("TEST", records, tmp_path)
    second = save_sections("TEST", records, tmp_path)

    assert first == second
    assert len(list(tmp_path.rglob("*.parquet"))) == 1
    assert pq.read_table(second).num_rows == 2


def test_empty_records_rejected(tmp_path):
    with pytest.raises(ValueError, match="empty"):
        save_sections("TEST", [], tmp_path)


def test_ticker_mismatch_rejected(tmp_path):
    records = make_records()

    with pytest.raises(ValueError, match="Ticker mismatch"):
        save_sections("WRONG", records, tmp_path)


def test_accession_mismatch_rejected(tmp_path):
    records = make_records()
    records[1]["accession"] = "different-accession"

    with pytest.raises(ValueError, match="Accession mismatch"):
        save_sections("TEST", records, tmp_path)


def test_failed_write_preserves_existing_file(tmp_path, monkeypatch):
    from src.transformation import store_filings

    records = make_records()
    path = save_sections("TEST", records, tmp_path)

    original_bytes = path.read_bytes()

    def simulated_failure(*args, **kwargs):
        raise OSError("Simulated disk write failure")

    monkeypatch.setattr(
        store_filings.pq,
        "write_table",
        simulated_failure,
    )

    with pytest.raises(OSError, match="Simulated disk write failure"):
        save_sections("TEST", records, tmp_path)

    assert path.read_bytes() == original_bytes
    assert pq.read_table(path).num_rows == 2

    # No temporary files should remain after failure.
    assert not list(path.parent.glob(".sections_*.parquet"))
