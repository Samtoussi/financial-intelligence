
import json
from datetime import datetime, timezone

import pytest

from src.transformation import snapshot_report


def create_snapshot(tmp_path, ticker, sha, timestamp, suffix=""):
    bronze = tmp_path / "bronze" / ticker
    silver = tmp_path / "silver" / ticker

    bronze.mkdir(parents=True, exist_ok=True)
    silver.mkdir(parents=True, exist_ok=True)

    metadata = {
        "ticker": ticker,
        "sha256": sha,
        "retrieved_at_utc": timestamp,
    }

    name = f"{timestamp[:10].replace('-', '')}_{sha[:12]}{suffix}"
    (bronze / f"{name}.metadata.json").write_text(
        json.dumps(metadata),
        encoding="utf-8",
    )

    (silver / f"{sha}.parquet").touch()


@pytest.fixture
def snapshot_dirs(tmp_path, monkeypatch):
    monkeypatch.setattr(
        snapshot_report, "BRONZE_ROOT", tmp_path / "bronze"
    )
    monkeypatch.setattr(
        snapshot_report, "SILVER_ROOT", tmp_path / "silver"
    )
    return tmp_path


def test_snapshots_are_chronological(snapshot_dirs):
    create_snapshot(
        snapshot_dirs, "JPM", "a" * 64,
        "2026-10-13T10:00:00+00:00",
    )
    create_snapshot(
        snapshot_dirs, "JPM", "b" * 64,
        "2026-11-03T10:00:00+00:00",
    )

    result = snapshot_report.find_snapshots("JPM")

    assert [s["snapshot_id"] for s in result] == [
        "a" * 64, "b" * 64
    ]


def test_duplicate_hash_keeps_latest_retrieval(snapshot_dirs):
    create_snapshot(
        snapshot_dirs, "JPM", "a" * 64,
        "2026-10-13T10:00:00+00:00",
        suffix="_first",
    )
    create_snapshot(
        snapshot_dirs, "JPM", "a" * 64,
        "2026-10-17T10:00:00+00:00",
        suffix="_second",
    )

    result = snapshot_report.find_snapshots("JPM")

    assert len(result) == 1
    assert result[0]["retrieved_at"] == datetime(
        2026, 10, 17, 10, 0, tzinfo=timezone.utc
    )


def test_old_and_new_filenames(snapshot_dirs):
    create_snapshot(
        snapshot_dirs, "JPM", "a" * 64,
        "2026-10-13T10:00:00+00:00",
    )
    create_snapshot(
        snapshot_dirs, "JPM", "b" * 64,
        "2026-11-03T10:00:00+00:00",
        suffix="_uuid123",
    )

    result = snapshot_report.find_snapshots("JPM")

    assert len(result) == 2


def test_missing_parquet_is_ignored(snapshot_dirs):
    create_snapshot(
        snapshot_dirs, "JPM", "a" * 64,
        "2026-10-13T10:00:00+00:00",
    )

    parquet = (
        snapshot_dirs / "silver" / "JPM" / f"{'a' * 64}.parquet"
    )
    parquet.unlink()

    assert snapshot_report.find_snapshots("JPM") == []


def test_requires_two_distinct_snapshots(snapshot_dirs):
    create_snapshot(
        snapshot_dirs, "JPM", "a" * 64,
        "2026-10-13T10:00:00+00:00",
    )

    with pytest.raises(ValueError, match="at least two"):
        snapshot_report.build_report("JPM")


def test_summary_counts():
    changes = {
        "added": [
            {"form": "10-K"},
            {"form": "10-K"},
            {"form": "10-Q"},
        ],
        "removed": [{}],
        "changed": [{}],
        "ambiguous": [],
    }

    result = snapshot_report.summarize_changes(changes)

    assert result == {
        "added": 3,
        "removed": 1,
        "changed": 1,
        "ambiguous": 0,
        "added_forms": {"10-K": 2, "10-Q": 1},
    }


def test_build_report_with_real_parquet(snapshot_dirs):
    import pyarrow as pa
    import pyarrow.parquet as pq

    ticker = "JPM"
    old_hash = "a" * 64
    new_hash = "b" * 64

    create_snapshot(
        snapshot_dirs,
        ticker,
        old_hash,
        "2026-10-17T10:00:00+00:00",
    )
    create_snapshot(
        snapshot_dirs,
        ticker,
        new_hash,
        "2026-11-03T10:00:00+00:00",
        suffix="_uuid123",
    )

    old_rows = [
        {
            "cik": 19617,
            "taxonomy": "us-gaap",
            "concept": "Assets",
            "unit": "USD",
            "start_date": None,
            "end_date": "2026-09-30",
            "accession": "0000000000-26-000001",
            "filed_date": "2026-10-17",
            "form": "10-Q",
            "fiscal_year": 2026,
            "fiscal_period": "Q3",
            "frame": "CY2026Q3I",
            "value": 100.0,
        }
    ]

    new_rows = [
        old_rows[0],
        {
            **old_rows[0],
            "concept": "Liabilities",
            "value": 50.0,
        },
    ]

    silver = snapshot_dirs / "silver" / ticker

    pq.write_table(
        pa.Table.from_pylist(old_rows),
        silver / f"{old_hash}.parquet",
    )
    pq.write_table(
        pa.Table.from_pylist(new_rows),
        silver / f"{new_hash}.parquet",
    )

    report = snapshot_report.build_report(ticker)

    assert report["ticker"] == ticker
    assert report["before"]["snapshot_id"] == old_hash
    assert report["after"]["snapshot_id"] == new_hash

    assert report["summary"] == {
        "added": 1,
        "removed": 0,
        "changed": 0,
        "ambiguous": 0,
        "added_forms": {"10-Q": 1},
    }
