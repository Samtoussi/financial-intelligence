
import json

import pytest

from src.operations.run_tracking import RunTracker


def read_manifest(tracker):
    return json.loads(tracker.manifest_path.read_text(encoding="utf-8"))


def test_successful_run(tmp_path):
    tracker = RunTracker("companyfacts", tmp_path, {"test": True})

    tracker.start_stage("bronze", "MSFT")
    tracker.complete_stage({"observations": 100})
    tracker.start_stage("silver", "MSFT")
    tracker.complete_stage({"loaded_rows": 100})
    tracker.complete()

    saved = read_manifest(tracker)

    assert saved["status"] == "success"
    assert len(saved["stages"]) == 2
    assert all(stage["status"] == "success" for stage in saved["stages"])
    assert saved["stages"][0]["artifacts"]["observations"] == 100
    assert saved["finished_at"] is not None
    assert saved["duration_seconds"] >= 0


def test_failed_run(tmp_path):
    tracker = RunTracker("companyfacts", tmp_path)

    tracker.start_stage("bronze", "MSFT")
    tracker.fail(TimeoutError("Sensitive error details"))

    saved = read_manifest(tracker)

    assert saved["status"] == "failed"
    assert saved["stages"][0]["status"] == "failed"
    assert saved["error_type"] == "TimeoutError"
    assert saved["stages"][0]["error_type"] == "TimeoutError"
    assert "Sensitive error details" not in json.dumps(saved)


def test_cannot_start_overlapping_stages(tmp_path):
    tracker = RunTracker("companyfacts", tmp_path)

    tracker.start_stage("bronze", "MSFT")

    with pytest.raises(RuntimeError):
        tracker.start_stage("silver", "MSFT")


def test_cannot_complete_without_active_stage(tmp_path):
    tracker = RunTracker("companyfacts", tmp_path)

    with pytest.raises(RuntimeError):
        tracker.complete_stage()


def test_cannot_complete_run_with_active_stage(tmp_path):
    tracker = RunTracker("companyfacts", tmp_path)

    tracker.start_stage("bronze", "MSFT")

    with pytest.raises(RuntimeError):
        tracker.complete()


def test_cannot_start_stage_after_completion(tmp_path):
    tracker = RunTracker("companyfacts", tmp_path)
    tracker.complete()

    with pytest.raises(RuntimeError):
        tracker.start_stage("bronze", "MSFT")


def test_cannot_complete_run_twice(tmp_path):
    tracker = RunTracker("companyfacts", tmp_path)
    tracker.complete()

    with pytest.raises(RuntimeError):
        tracker.complete()


def test_cannot_complete_failed_run(tmp_path):
    tracker = RunTracker("companyfacts", tmp_path)
    tracker.fail(ValueError("Failure"))

    with pytest.raises(RuntimeError):
        tracker.complete()


def test_unfinished_run_remains_running(tmp_path):
    tracker = RunTracker("filings", tmp_path, {"ticker": "CAT"})
    tracker.start_stage("bronze", "CAT")

    saved = read_manifest(tracker)

    assert saved["status"] == "running"
    assert saved["stages"][0]["status"] == "running"
    assert saved["finished_at"] is None


def test_manifest_write_failure_preserves_previous_record(tmp_path, monkeypatch):
    tracker = RunTracker("companyfacts", tmp_path)
    original = read_manifest(tracker)

    def fail_replace(source, destination):
        raise OSError("Simulated disk write failure")

    monkeypatch.setattr(
        "src.operations.run_tracking.os.replace",
        fail_replace,
    )

    with pytest.raises(OSError, match="Simulated disk write failure"):
        tracker.start_stage("bronze", "MSFT")

    saved = read_manifest(tracker)

    assert saved == original
    assert saved["status"] == "running"
    assert saved["stages"] == []


def test_write_failure_preserves_in_memory_state(tmp_path, monkeypatch):
    tracker = RunTracker("companyfacts", tmp_path)
    original = read_manifest(tracker)

    def fail_replace(source, destination):
        raise OSError("Simulated persistence failure")

    monkeypatch.setattr(
        "src.operations.run_tracking.os.replace",
        fail_replace,
    )

    with pytest.raises(OSError):
        tracker.start_stage("bronze", "MSFT")

    assert tracker.manifest == original
    assert tracker._active_stage is None
    assert tracker._stage_started is None
    assert read_manifest(tracker) == original
