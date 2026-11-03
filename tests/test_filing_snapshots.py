import hashlib
import json
from pathlib import Path

import pytest

from src.ingestion import filings


@pytest.fixture
def filing():
    return {
        "cik": 789019,
        "accession": "0000789019-26-000001",
        "form": "10-K",
        "filing_date": "2026-01-01",
        "report_date": "2025-12-31",
        "source_url": "https://www.sec.gov/example",
    }


def test_metadata_failure_removes_published_html(
    tmp_path, monkeypatch, filing
):
    monkeypatch.setattr(filings, "RAW_DIR", tmp_path)

    original_replace = filings.os.replace

    def fail_metadata_replace(source, destination):
        if str(destination).endswith(".metadata.json"):
            raise OSError("Simulated metadata publication failure")

        return original_replace(source, destination)

    monkeypatch.setattr(
        filings.os,
        "replace",
        fail_metadata_replace,
    )

    with pytest.raises(
        OSError,
        match="Simulated metadata publication failure",
    ):
        filings.save_snapshot(
            "MSFT",
            b"<html>Example filing</html>",
            filing,
        )

    output_dir = tmp_path / "MSFT" / filing["accession"]

    assert not list(output_dir.glob("*.html"))
    assert not list(output_dir.glob("*.metadata.json"))
    assert not list(output_dir.glob("*.tmp"))


def test_repeated_identical_snapshots_have_unique_paths(
    tmp_path, monkeypatch, filing
):
    monkeypatch.setattr(filings, "RAW_DIR", tmp_path)

    payload = b"<html>Example filing</html>"

    first = filings.save_snapshot("MSFT", payload, filing)
    second = filings.save_snapshot("MSFT", payload, filing)

    assert first != second
    assert first.exists()
    assert second.exists()

    metadata_files = list(
        first.parent.glob("*.metadata.json")
    )
    assert len(metadata_files) == 2

    for path in metadata_files:
        metadata = json.loads(path.read_text(encoding="utf-8"))
        assert metadata["accession"] == filing["accession"]
        assert metadata["size_bytes"] == len(payload)


def test_retry_after_metadata_failure_succeeds(
    tmp_path, monkeypatch, filing
):
    monkeypatch.setattr(filings, "RAW_DIR", tmp_path)

    payload = b"<html>Example filing</html>"
    original_replace = filings.os.replace
    fail_once = True

    def fail_first_metadata_replace(source, destination):
        nonlocal fail_once

        if (
            str(destination).endswith(".metadata.json")
            and fail_once
        ):
            fail_once = False
            raise OSError("Simulated transient metadata failure")

        return original_replace(source, destination)

    monkeypatch.setattr(
        filings.os,
        "replace",
        fail_first_metadata_replace,
    )

    # First attempt fails during metadata publication.
    with pytest.raises(
        OSError,
        match="Simulated transient metadata failure",
    ):
        filings.save_snapshot("MSFT", payload, filing)

    output_dir = tmp_path / "MSFT" / filing["accession"]

    assert not list(output_dir.glob("*.html"))
    assert not list(output_dir.glob("*.metadata.json"))
    assert not list(output_dir.glob("*.tmp"))

    # Second attempt succeeds without manual cleanup.
    snapshot_path = filings.save_snapshot(
        "MSFT",
        payload,
        filing,
    )

    assert snapshot_path.exists()
    assert snapshot_path.read_bytes() == payload

    metadata_files = list(
        output_dir.glob("*.metadata.json")
    )
    assert len(metadata_files) == 1

    metadata = json.loads(
        metadata_files[0].read_text(encoding="utf-8")
    )

    assert metadata["sha256"] == hashlib.sha256(payload).hexdigest()
    assert metadata["size_bytes"] == len(payload)

    assert len(list(output_dir.glob("*.html"))) == 1
    assert not list(output_dir.glob("*.tmp"))
