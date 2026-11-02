
import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from src.transformation.load_companyfacts import read_snapshot_metadata


class TestCompanyFactsIntegrity(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)

        self.snapshot_path = (
            Path(self.temp_dir.name) / "20261102_120000_abc123.json"
        )

        self.payload = {
            "cik": 789019,
            "entityName": "Microsoft Corporation",
            "facts": {
                "us-gaap": {
                    "Revenues": {
                        "units": {
                            "USD": [
                                {
                                    "val": 100,
                                    "end": "2026-06-30",
                                    "form": "10-K",
                                }
                            ]
                        }
                    }
                }
            },
        }

        self.snapshot_path.write_text(
            json.dumps(self.payload),
            encoding="utf-8",
        )

        self.snapshot_id = hashlib.sha256(
            self.snapshot_path.read_bytes()
        ).hexdigest()

        self.metadata_path = self.snapshot_path.with_name(
            f"{self.snapshot_path.stem}.metadata.json"
        )

        self.metadata = {
            "ticker": "MSFT",
            "cik": 789019,
            "sha256": self.snapshot_id,
            "retrieved_at_utc": "2026-11-02T12:00:00+00:00",
        }

        self.write_metadata()

    def write_metadata(self):
        self.metadata_path.write_text(
            json.dumps(self.metadata),
            encoding="utf-8",
        )

    def verify(self):
        actual_snapshot_id = hashlib.sha256(
            self.snapshot_path.read_bytes()
        ).hexdigest()

        return read_snapshot_metadata(
            self.snapshot_path,
            "MSFT",
            789019,
            actual_snapshot_id,
        )

    def test_valid_snapshot_metadata(self):
        retrieved_at = self.verify()

        self.assertEqual(
            retrieved_at,
            datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc),
        )

    def test_tampered_snapshot_is_rejected(self):
        self.snapshot_path.write_text(
            json.dumps({"cik": 789019, "facts": {}}),
            encoding="utf-8",
        )

        with self.assertRaisesRegex(
            ValueError, "Metadata SHA-256 mismatch"
        ):
            self.verify()

    def test_missing_metadata_is_rejected(self):
        self.metadata_path.unlink()

        with self.assertRaises(FileNotFoundError):
            self.verify()

    def test_wrong_ticker_is_rejected(self):
        self.metadata["ticker"] = "JPM"
        self.write_metadata()

        with self.assertRaisesRegex(
            ValueError, "Metadata ticker mismatch"
        ):
            self.verify()

    def test_wrong_cik_is_rejected(self):
        self.metadata["cik"] = 19617
        self.write_metadata()

        with self.assertRaisesRegex(
            ValueError, "Metadata CIK mismatch"
        ):
            self.verify()

    def test_missing_timestamp_is_rejected(self):
        del self.metadata["retrieved_at_utc"]
        self.write_metadata()

        with self.assertRaises(KeyError):
            self.verify()

    def test_naive_timestamp_is_rejected(self):
        self.metadata["retrieved_at_utc"] = "2026-11-02T12:00:00"
        self.write_metadata()

        with self.assertRaisesRegex(
            ValueError, "must include timezone"
        ):
            self.verify()


if __name__ == "__main__":
    unittest.main()
