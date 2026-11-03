
import json
import os
from pathlib import Path

import pytest

import run_filings


@pytest.fixture(autouse=True)
def restore_working_directory():
    original = Path.cwd()
    try:
        yield
    finally:
        os.chdir(original)


def read_run(tmp_path):
    manifests = list(
        (tmp_path / "data" / "runs" / "filings").glob("*/run.json")
    )
    assert len(manifests) == 1
    return json.loads(manifests[0].read_text(encoding="utf-8"))


def test_invalid_ticker_creates_failed_run(tmp_path, monkeypatch):
    monkeypatch.setattr(run_filings, "ROOT", tmp_path)

    with pytest.raises(ValueError, match="Unsupported ticker"):
        run_filings.run_filings("INVALID")

    saved = read_run(tmp_path)

    assert saved["status"] == "failed"
    assert saved["error_type"] == "ValueError"
    assert saved["stages"][0]["name"] == "preflight"
    assert saved["stages"][0]["status"] == "failed"


def test_successful_filing_creates_stage_history(tmp_path, monkeypatch):
    monkeypatch.setattr(run_filings, "ROOT", tmp_path)
    monkeypatch.setenv(
        "SEC_USER_AGENT",
        "FinancialIntelligence contact@example.com",
    )
    monkeypatch.setattr(run_filings, "COMPANIES", {"MSFT": "0000789019"})

    filing = {
        "accession": "0000789019-26-000001",
        "filing_date": "2026-10-01",
        "source_url": "https://example.com/filing.htm",
    }
    payload = b"<html>Test filing</html>"

    monkeypatch.setattr(
        run_filings,
        "discover_latest_10k",
        lambda *args: filing,
    )
    monkeypatch.setattr(run_filings, "fetch", lambda *args: payload)
    monkeypatch.setattr(
        run_filings,
        "save_snapshot",
        lambda *args: tmp_path / "filing.html",
    )
    monkeypatch.setattr(
        run_filings,
        "prepare_sections",
        lambda *args, **kwargs: [
            {"item": "1A", "words": 100, "extraction_method": "test"}
        ],
    )
    monkeypatch.setattr(
        run_filings,
        "save_sections",
        lambda *args: tmp_path / "sections.parquet",
    )
    monkeypatch.setattr(
        run_filings,
        "process_ticker",
        lambda *args: (tmp_path / "chunks.parquet", 12),
    )

    run_filings.run_filings("msft")

    saved = read_run(tmp_path)

    assert saved["status"] == "success"
    assert saved["arguments"]["ticker"] == "MSFT"
    assert [stage["name"] for stage in saved["stages"]] == [
        "preflight",
        "bronze",
        "silver",
        "retrieval",
    ]
    assert all(stage["status"] == "success" for stage in saved["stages"])
    assert saved["stages"][1]["artifacts"]["accession"] == filing["accession"]
    assert saved["stages"][2]["artifacts"]["section_count"] == 1
    assert saved["stages"][3]["artifacts"]["total_searchable_chunks"] == 12


def test_filing_fetch_failure_records_stage(tmp_path, monkeypatch):
    monkeypatch.setattr(run_filings, "ROOT", tmp_path)
    monkeypatch.setenv(
        "SEC_USER_AGENT",
        "FinancialIntelligence contact@example.com",
    )
    monkeypatch.setattr(run_filings, "COMPANIES", {"MSFT": "0000789019"})

    filing = {
        "accession": "0000789019-26-000001",
        "filing_date": "2026-10-01",
        "source_url": "https://example.com/filing.htm",
    }

    monkeypatch.setattr(
        run_filings,
        "discover_latest_10k",
        lambda *args: filing,
    )

    def fail_fetch(*args):
        raise TimeoutError("Sensitive SEC request details")

    monkeypatch.setattr(run_filings, "fetch", fail_fetch)

    with pytest.raises(TimeoutError, match="Sensitive SEC request details"):
        run_filings.run_filings("MSFT")

    saved = read_run(tmp_path)

    assert saved["status"] == "failed"
    assert saved["error_type"] == "TimeoutError"
    assert saved["stages"][-1]["name"] == "bronze"
    assert saved["stages"][-1]["status"] == "failed"
    assert "Sensitive SEC request details" not in json.dumps(saved)
