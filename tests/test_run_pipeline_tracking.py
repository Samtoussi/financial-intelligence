import os
from pathlib import Path

import json

import pytest

import run_pipeline


@pytest.fixture(autouse=True)
def restore_working_directory():
    original = Path.cwd()
    try:
        yield
    finally:
        os.chdir(original)


def test_preflight_failure_creates_run_record(tmp_path, monkeypatch):
    monkeypatch.setattr(run_pipeline, "ROOT", tmp_path)
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)

    with pytest.raises(ValueError, match="SEC_USER_AGENT"):
        run_pipeline.run_pipeline()

    manifests = list(
        (tmp_path / "data" / "runs" / "companyfacts").glob("*/run.json")
    )

    assert len(manifests) == 1

    saved = json.loads(manifests[0].read_text(encoding="utf-8"))

    assert saved["pipeline"] == "companyfacts"
    assert saved["status"] == "failed"
    assert saved["error_type"] == "ValueError"
    assert len(saved["stages"]) == 1
    assert saved["stages"][0]["name"] == "preflight"
    assert saved["stages"][0]["status"] == "failed"


def test_successful_pipeline_creates_stage_history(tmp_path, monkeypatch):
    monkeypatch.setattr(run_pipeline, "ROOT", tmp_path)
    monkeypatch.setenv("SEC_USER_AGENT", "FinancialIntelligence contact@example.com")
    monkeypatch.setattr(run_pipeline, "COMPANIES", {"MSFT": "0000789019"})

    payload = b'{"facts": {}}'
    snapshot_id = run_pipeline.hashlib.sha256(payload).hexdigest()

    monkeypatch.setattr(run_pipeline, "fetch_companyfacts", lambda *args: payload)
    monkeypatch.setattr(
        run_pipeline,
        "validate_companyfacts",
        lambda *args: {"observations": 10},
    )
    monkeypatch.setattr(
        run_pipeline,
        "save_snapshot",
        lambda *args: tmp_path / "snapshot.json",
    )
    monkeypatch.setattr(
        run_pipeline,
        "read_snapshot_metadata",
        lambda *args: "2026-11-03T14:00:00Z",
    )
    monkeypatch.setattr(run_pipeline, "normalize", lambda *args: [1, 2, 3])
    monkeypatch.setattr(
        run_pipeline,
        "write_parquet",
        lambda *args: tmp_path / "silver.parquet",
    )
    monkeypatch.setattr(run_pipeline, "load_duckdb", lambda *args: 3)
    monkeypatch.setattr(run_pipeline.subprocess, "run", lambda *args, **kwargs: None)

    run_pipeline.run_pipeline()

    manifests = list(
        (tmp_path / "data" / "runs" / "companyfacts").glob("*/run.json")
    )
    assert len(manifests) == 1

    saved = json.loads(manifests[0].read_text(encoding="utf-8"))

    assert saved["status"] == "success"
    assert [stage["name"] for stage in saved["stages"]] == [
        "preflight",
        "bronze",
        "silver",
        "gold",
    ]
    assert all(stage["status"] == "success" for stage in saved["stages"])
    assert saved["stages"][1]["artifacts"]["snapshot_sha256"] == snapshot_id
    assert saved["stages"][2]["artifacts"]["loaded_rows"] == 3


def test_bronze_failure_preserves_original_error(tmp_path, monkeypatch):
    monkeypatch.setattr(run_pipeline, "ROOT", tmp_path)
    monkeypatch.setenv("SEC_USER_AGENT", "FinancialIntelligence contact@example.com")
    monkeypatch.setattr(run_pipeline, "COMPANIES", {"MSFT": "0000789019"})

    def fail_fetch(*args):
        raise TimeoutError("Sensitive SEC request details")

    monkeypatch.setattr(run_pipeline, "fetch_companyfacts", fail_fetch)

    with pytest.raises(TimeoutError, match="Sensitive SEC request details"):
        run_pipeline.run_pipeline()

    manifests = list(
        (tmp_path / "data" / "runs" / "companyfacts").glob("*/run.json")
    )
    assert len(manifests) == 1

    raw = manifests[0].read_text(encoding="utf-8")
    saved = json.loads(raw)

    assert saved["status"] == "failed"
    assert saved["stages"][-1]["name"] == "bronze"
    assert saved["stages"][-1]["status"] == "failed"
    assert saved["error_type"] == "TimeoutError"
    assert "Sensitive SEC request details" not in raw
