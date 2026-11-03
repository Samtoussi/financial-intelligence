
from unittest.mock import MagicMock, patch

import duckdb
import pytest

import run_pipeline


def test_get_active_snapshot_returns_none_when_db_missing(tmp_path):
    db_path = tmp_path / "missing.duckdb"

    with patch.dict("os.environ", {"FI_DUCKDB_PATH": str(db_path)}):
        assert run_pipeline.get_active_snapshot(789019) is None

    assert not db_path.exists()


def test_get_active_snapshot_returns_none_when_table_missing(tmp_path):
    db_path = tmp_path / "warehouse.duckdb"

    con = duckdb.connect(str(db_path))
    con.close()

    with patch.dict("os.environ", {"FI_DUCKDB_PATH": str(db_path)}):
        assert run_pipeline.get_active_snapshot(789019) is None


def test_get_active_snapshot_reads_existing_snapshot(tmp_path):
    db_path = tmp_path / "warehouse.duckdb"

    con = duckdb.connect(str(db_path))
    con.execute(
        """
        CREATE TABLE financial_observations (
            cik INTEGER,
            snapshot_id VARCHAR
        )
        """
    )
    con.execute(
        """
        INSERT INTO financial_observations
        VALUES (789019, 'snapshot-abc')
        """
    )
    con.close()

    with patch.dict("os.environ", {"FI_DUCKDB_PATH": str(db_path)}):
        assert run_pipeline.get_active_snapshot(789019) == "snapshot-abc"


def test_get_active_snapshot_rejects_multiple_active_snapshots(tmp_path):
    db_path = tmp_path / "warehouse.duckdb"

    con = duckdb.connect(str(db_path))
    con.execute(
        """
        CREATE TABLE financial_observations (
            cik INTEGER,
            snapshot_id VARCHAR
        )
        """
    )
    con.execute(
        """
        INSERT INTO financial_observations
        VALUES
            (789019, 'snapshot-abc'),
            (789019, 'snapshot-def')
        """
    )
    con.close()

    with patch.dict("os.environ", {"FI_DUCKDB_PATH": str(db_path)}):
        with pytest.raises(RuntimeError, match="multiple active snapshots"):
            run_pipeline.get_active_snapshot(789019)


def test_get_active_snapshot_propagates_database_errors(tmp_path):
    db_path = tmp_path / "invalid.duckdb"
    db_path.write_text("not a valid DuckDB database")

    with patch.dict("os.environ", {"FI_DUCKDB_PATH": str(db_path)}):
        with pytest.raises(duckdb.Error):
            run_pipeline.get_active_snapshot(789019)


def test_unchanged_snapshot_skips_silver_processing(tmp_path, monkeypatch):
    payload = b'{"example": true}'
    snapshot_id = run_pipeline.hashlib.sha256(payload).hexdigest()

    tracker = MagicMock()
    tracker.run_id = "test-run"
    tracker.run_dir = tmp_path / "run"
    tracker.manifest_path = tmp_path / "run.json"

    monkeypatch.setenv("SEC_USER_AGENT", "FI Test test@example.com")
    monkeypatch.setattr(run_pipeline, "ROOT", tmp_path)
    monkeypatch.setattr(run_pipeline, "COMPANIES", {"MSFT": 789019})
    monkeypatch.setattr(run_pipeline, "RunTracker", lambda *args: tracker)

    monkeypatch.setattr(
        run_pipeline, "fetch_companyfacts", lambda *args: payload
    )
    monkeypatch.setattr(
        run_pipeline,
        "validate_companyfacts",
        lambda *args: {"observations": 1},
    )
    monkeypatch.setattr(
        run_pipeline,
        "save_snapshot",
        lambda *args: tmp_path / "snapshot.json",
    )
    monkeypatch.setattr(
        run_pipeline,
        "get_active_snapshot",
        lambda cik: snapshot_id,
    )

    normalize = MagicMock()
    write_parquet = MagicMock()
    load_duckdb = MagicMock()

    monkeypatch.setattr(run_pipeline, "normalize", normalize)
    monkeypatch.setattr(run_pipeline, "write_parquet", write_parquet)
    monkeypatch.setattr(run_pipeline, "load_duckdb", load_duckdb)

    monkeypatch.setattr(
        run_pipeline,
        "summarize_dbt_results",
        lambda *args: {"failed": []},
    )
    monkeypatch.setattr(
        run_pipeline.subprocess,
        "run",
        lambda *args, **kwargs: None,
    )

    run_pipeline.run_pipeline()

    normalize.assert_not_called()
    write_parquet.assert_not_called()
    load_duckdb.assert_not_called()

    assert any(
        call.args
        and isinstance(call.args[0], dict)
        and call.args[0].get("reason") == "unchanged_snapshot"
        for call in tracker.complete_stage.call_args_list
    )


def test_changed_snapshot_runs_silver_processing(tmp_path, monkeypatch):
    payload = b'{"example": true}'
    snapshot_id = run_pipeline.hashlib.sha256(payload).hexdigest()
    snapshot_path = tmp_path / "snapshot.json"
    parquet_path = tmp_path / "snapshot.parquet"

    tracker = MagicMock()
    tracker.run_id = "test-run"
    tracker.run_dir = tmp_path / "run"
    tracker.manifest_path = tmp_path / "run.json"

    monkeypatch.setenv("SEC_USER_AGENT", "FI Test test@example.com")
    monkeypatch.setattr(run_pipeline, "ROOT", tmp_path)
    monkeypatch.setattr(run_pipeline, "COMPANIES", {"MSFT": 789019})
    monkeypatch.setattr(run_pipeline, "RunTracker", lambda *args: tracker)

    monkeypatch.setattr(
        run_pipeline, "fetch_companyfacts", lambda *args: payload
    )
    monkeypatch.setattr(
        run_pipeline,
        "validate_companyfacts",
        lambda *args: {"observations": 1},
    )
    monkeypatch.setattr(
        run_pipeline,
        "save_snapshot",
        lambda *args: snapshot_path,
    )
    monkeypatch.setattr(
        run_pipeline,
        "get_active_snapshot",
        lambda cik: "previous-snapshot",
    )

    retrieved_at = object()
    rows = [{"value": 100}]

    read_metadata = MagicMock(return_value=retrieved_at)
    normalize = MagicMock(return_value=rows)
    write_parquet = MagicMock(return_value=parquet_path)
    load_duckdb = MagicMock(return_value=1)

    monkeypatch.setattr(
        run_pipeline, "read_snapshot_metadata", read_metadata
    )
    monkeypatch.setattr(run_pipeline, "normalize", normalize)
    monkeypatch.setattr(run_pipeline, "write_parquet", write_parquet)
    monkeypatch.setattr(run_pipeline, "load_duckdb", load_duckdb)

    monkeypatch.setattr(
        run_pipeline,
        "summarize_dbt_results",
        lambda *args: {"failed": []},
    )
    monkeypatch.setattr(
        run_pipeline.subprocess,
        "run",
        lambda *args, **kwargs: None,
    )

    run_pipeline.run_pipeline()

    read_metadata.assert_called_once_with(
        snapshot_path, "MSFT", 789019, snapshot_id
    )
    normalize.assert_called_once_with(
        {"example": True}, snapshot_id
    )
    write_parquet.assert_called_once_with(
        rows, "MSFT", snapshot_id
    )
    load_duckdb.assert_called_once_with(
        parquet_path, snapshot_id, 1, 789019, retrieved_at
    )

    assert any(
        call.args
        and isinstance(call.args[0], dict)
        and call.args[0].get("skipped") is False
        for call in tracker.complete_stage.call_args_list
    )
