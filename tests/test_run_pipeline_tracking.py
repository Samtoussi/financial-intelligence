
import json
import os
from pathlib import Path

import pytest

import run_pipeline


@pytest.fixture(autouse=True)
def restore_working_directory():
    original = Path.cwd()
    try:
        yield
    finally:
        os.chdir(original)


def fake_dbt_build(args, **kwargs):
    target_index = args.index("--target-path") + 1
    target = Path(args[target_index])
    target.mkdir(parents=True, exist_ok=True)

    result = {
        "metadata": {
            "invocation_id": "mock-dbt-invocation",
            "dbt_version": "1.12.6",
            "generated_at": "2026-11-03T14:00:00Z",
        },
        "results": [
            {
                "unique_id": "model.fi.annual_revenue",
                "status": "success",
            },
            {
                "unique_id": "test.fi.revenue_not_null",
                "status": "pass",
            },
        ],
    }

    (target / "run_results.json").write_text(
        json.dumps(result),
        encoding="utf-8",
    )


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
    monkeypatch.setattr(run_pipeline.subprocess, "run", fake_dbt_build)

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

    gold = saved["stages"][-1]["artifacts"]

    assert gold["invocation_id"] == "mock-dbt-invocation"
    assert gold["model_success"] == 1
    assert gold["test_pass"] == 1
    assert gold["failed"] == 0
    assert gold["run_results_path"].endswith("run_results.json")
    assert gold["warehouse_path"]


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


def run_with_dbt_failure(tmp_path, monkeypatch, artifact):
    monkeypatch.setattr(run_pipeline, "ROOT", tmp_path)
    monkeypatch.setenv(
        "SEC_USER_AGENT",
        "FinancialIntelligence contact@example.com",
    )
    monkeypatch.setattr(
        run_pipeline,
        "COMPANIES",
        {"MSFT": "0000789019"},
    )

    payload = b'{"facts": {}}'
    snapshot_id = run_pipeline.hashlib.sha256(payload).hexdigest()

    monkeypatch.setattr(
        run_pipeline,
        "fetch_companyfacts",
        lambda *args: payload,
    )
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
    monkeypatch.setattr(
        run_pipeline,
        "normalize",
        lambda *args: [1, 2, 3],
    )
    monkeypatch.setattr(
        run_pipeline,
        "write_parquet",
        lambda *args: tmp_path / "silver.parquet",
    )
    monkeypatch.setattr(
        run_pipeline,
        "load_duckdb",
        lambda *args: 3,
    )

    def failing_dbt(args, **kwargs):
        target = Path(args[args.index("--target-path") + 1])
        target.mkdir(parents=True, exist_ok=True)

        if artifact == "valid":
            result = {
                "metadata": {
                    "invocation_id": "failed-dbt-invocation",
                    "dbt_version": "1.12.6",
                    "generated_at": "2026-11-03T14:00:00Z",
                },
                "results": [
                    {
                        "unique_id": "model.fi.revenue",
                        "status": "error",
                    }
                ],
            }
            (target / "run_results.json").write_text(
                json.dumps(result),
                encoding="utf-8",
            )

        elif artifact == "corrupt":
            (target / "run_results.json").write_text(
                "{invalid json",
                encoding="utf-8",
            )

        raise run_pipeline.subprocess.CalledProcessError(
            1,
            args,
            "Sensitive dbt failure details",
        )

    monkeypatch.setattr(
        run_pipeline.subprocess,
        "run",
        failing_dbt,
    )

    with pytest.raises(
        run_pipeline.subprocess.CalledProcessError
    ):
        run_pipeline.run_pipeline()

    manifests = list(
        (tmp_path / "data" / "runs" / "companyfacts").glob("*/run.json")
    )
    assert len(manifests) == 1

    raw = manifests[0].read_text(encoding="utf-8")
    return json.loads(raw), raw


def test_dbt_failure_preserves_valid_diagnostics(tmp_path, monkeypatch):
    saved, raw = run_with_dbt_failure(
        tmp_path,
        monkeypatch,
        artifact="valid",
    )

    assert saved["status"] == "failed"
    assert saved["error_type"] == "CalledProcessError"

    gold = saved["stages"][-1]
    assert gold["name"] == "gold"
    assert gold["status"] == "failed"
    assert gold["artifacts"]["invocation_id"] == "failed-dbt-invocation"
    assert gold["artifacts"]["failed"] == 1
    assert "Sensitive dbt failure details" not in raw


def test_dbt_failure_without_artifact(tmp_path, monkeypatch):
    saved, _ = run_with_dbt_failure(
        tmp_path,
        monkeypatch,
        artifact="missing",
    )

    assert saved["status"] == "failed"

    gold = saved["stages"][-1]
    assert gold["status"] == "failed"
    assert gold["artifacts"]["artifact_status"] == "missing"


def test_dbt_failure_with_corrupt_artifact(tmp_path, monkeypatch):
    saved, _ = run_with_dbt_failure(
        tmp_path,
        monkeypatch,
        artifact="corrupt",
    )

    assert saved["status"] == "failed"

    gold = saved["stages"][-1]
    assert gold["status"] == "failed"
    assert gold["artifacts"]["artifact_status"] == "invalid"
