import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from src.transformation import load_companyfacts


OLD_TIME = datetime(2026, 10, 9, tzinfo=timezone.utc)
NEW_TIME = datetime(2026, 10, 13, tzinfo=timezone.utc)


class TestSnapshotLifecycle(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)

        self.db_path = Path(self.temp_dir.name) / "test.duckdb"

        self.db_patch = patch.object(
            load_companyfacts,
            "DB_PATH",
            self.db_path,
        )
        self.db_patch.start()
        self.addCleanup(self.db_patch.stop)

    def create_parquet(self, filename, cik, snapshot_id, values):
        rows = []

        for index, value in enumerate(values):
            rows.append({
                "snapshot_id": snapshot_id,
                "observation_index": index,
                "cik": cik,
                "taxonomy": "us-gaap",
                "concept": "Revenues",
                "unit": "USD",
                "value": float(value),
                "start_date": None,
                "end_date": None,
                "accession": f"filing-{index}",
                "filed_date": None,
                "form": "10-K",
                "fiscal_year": 2023,
                "fiscal_period": "FY",
                "frame": None,
                "raw_observation": "{}",
            })

        path = Path(self.temp_dir.name) / filename
        pq.write_table(pa.Table.from_pylist(rows), path)

        return path

    def load(self, path, snapshot_id, count, cik, retrieved_at=OLD_TIME):
        return load_companyfacts.load_duckdb(
            path,
            snapshot_id,
            count,
            cik,
            retrieved_at,
        )

    def query(self, sql):
        with duckdb.connect(str(self.db_path)) as con:
            return con.execute(sql).fetchall()

    def test_same_snapshot_is_idempotent(self):
        path = self.create_parquet(
            "msft.parquet", 789019, "snapshot-a", [100, 200]
        )

        for _ in range(2):
            self.assertEqual(
                self.load(path, "snapshot-a", 2, 789019),
                2,
            )

        self.assertEqual(
            self.query("SELECT COUNT(*) FROM financial_observations"),
            [(2,)],
        )

        self.assertEqual(
            self.query("SELECT COUNT(*) FROM loaded_snapshots"),
            [(1,)],
        )

    def test_new_snapshot_replaces_old(self):
        old_path = self.create_parquet(
            "old.parquet", 789019, "snapshot-a", [100, 200]
        )
        new_path = self.create_parquet(
            "new.parquet", 789019, "snapshot-b", [300]
        )

        self.load(old_path, "snapshot-a", 2, 789019, OLD_TIME)
        self.load(new_path, "snapshot-b", 1, 789019, NEW_TIME)

        self.assertEqual(
            self.query("""
                SELECT snapshot_id, value
                FROM financial_observations
            """),
            [("snapshot-b", 300.0)],
        )

        self.assertEqual(
            self.query("SELECT COUNT(*) FROM loaded_snapshots"),
            [(2,)],
        )

    def test_rejects_older_snapshot(self):
        new_path = self.create_parquet(
            "new.parquet", 789019, "snapshot-new", [300]
        )
        old_path = self.create_parquet(
            "old.parquet", 789019, "snapshot-old", [100]
        )

        self.load(new_path, "snapshot-new", 1, 789019, NEW_TIME)

        with self.assertRaises(ValueError):
            self.load(
                old_path,
                "snapshot-old",
                1,
                789019,
                OLD_TIME,
            )

        self.assertEqual(
            self.query("""
                SELECT snapshot_id, value
                FROM financial_observations
            """),
            [("snapshot-new", 300.0)],
        )

    def test_other_companies_are_unchanged(self):
        msft_path = self.create_parquet(
            "msft.parquet", 789019, "snapshot-a", [100]
        )
        jpm_path = self.create_parquet(
            "jpm.parquet", 19617, "snapshot-jpm", [500]
        )
        new_msft_path = self.create_parquet(
            "msft-new.parquet", 789019, "snapshot-b", [200]
        )

        self.load(msft_path, "snapshot-a", 1, 789019, OLD_TIME)
        self.load(jpm_path, "snapshot-jpm", 1, 19617, OLD_TIME)
        self.load(new_msft_path, "snapshot-b", 1, 789019, NEW_TIME)

        self.assertEqual(
            self.query("""
                SELECT cik, value
                FROM financial_observations
                ORDER BY cik
            """),
            [(19617, 500.0), (789019, 200.0)],
        )

    def test_failed_load_rolls_back(self):
        original_path = self.create_parquet(
            "original.parquet", 789019, "snapshot-a", [100]
        )
        invalid_path = self.create_parquet(
            "invalid.parquet", 789019, "snapshot-b", [200]
        )

        self.load(original_path, "snapshot-a", 1, 789019)

        with self.assertRaises(ValueError):
            self.load(
                invalid_path,
                "snapshot-b",
                999,
                789019,
                NEW_TIME,
            )

        self.assertEqual(
            self.query("""
                SELECT snapshot_id, value
                FROM financial_observations
            """),
            [("snapshot-a", 100.0)],
        )

        self.assertEqual(
            self.query("SELECT COUNT(*) FROM loaded_snapshots"),
            [(1,)],
        )

    def test_rejects_empty_snapshot(self):
        path = self.create_parquet(
            "empty.parquet", 789019, "snapshot-empty", [100]
        )

        table = pq.read_table(path)
        pq.write_table(table.slice(0, 0), path)

        with self.assertRaises(ValueError):
            self.load(path, "snapshot-empty", 0, 789019)

    def test_rejects_wrong_company(self):
        path = self.create_parquet(
            "wrong-company.parquet", 19617, "snapshot-a", [100]
        )

        with self.assertRaises(ValueError):
            self.load(path, "snapshot-a", 1, 789019)

    def test_rejects_wrong_snapshot(self):
        path = self.create_parquet(
            "wrong-snapshot.parquet", 789019, "snapshot-a", [100]
        )

        with self.assertRaises(ValueError):
            self.load(path, "snapshot-b", 1, 789019)

    def test_rejects_duplicate_observation_indices(self):
        path = self.create_parquet(
            "duplicates.parquet", 789019, "snapshot-a", [100, 200]
        )

        table = pq.read_table(path)
        rows = table.to_pylist()
        rows[1]["observation_index"] = rows[0]["observation_index"]

        pq.write_table(pa.Table.from_pylist(rows), path)

        with self.assertRaises(ValueError):
            self.load(path, "snapshot-a", 2, 789019)


if __name__ == "__main__":
    unittest.main()