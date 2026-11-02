
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.ingestion import companyfacts


class TestSnapshotPublication(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)

        self.raw_dir = Path(self.temp_dir.name)

        raw_dir_patch = patch.object(
            companyfacts,
            "RAW_DIR",
            self.raw_dir,
        )
        raw_dir_patch.start()
        self.addCleanup(raw_dir_patch.stop)

        self.payload = b'{"cik":789019,"facts":{"us-gaap":{}}}'
        self.summary = {
            "cik": 789019,
            "company": "Microsoft Corporation",
            "concepts": 1,
            "observations": 1,
        }

    def test_failed_metadata_publication_leaves_no_orphan_snapshot(self):
        original_replace = companyfacts.os.replace

        def fail_metadata_replace(src, dst):
            if str(dst).endswith(".metadata.json"):
                raise OSError("Simulated metadata publication failure")

            return original_replace(src, dst)

        with patch.object(
            companyfacts.os,
            "replace",
            side_effect=fail_metadata_replace,
        ):
            with self.assertRaisesRegex(
                OSError,
                "Simulated metadata publication failure",
            ):
                companyfacts.save_snapshot(
                    "MSFT",
                    self.payload,
                    self.summary,
                )

        output_dir = self.raw_dir / "MSFT"

        self.assertEqual(
            list(output_dir.glob("*.json")),
            [],
        )

        self.assertEqual(
            list(output_dir.glob("*.tmp")),
            [],
        )

    def test_repeated_save_preserves_existing_snapshot(self):
        first_path = companyfacts.save_snapshot(
            "MSFT",
            self.payload,
            self.summary,
        )

        first_bytes = first_path.read_bytes()
        first_metadata_path = first_path.with_name(
            f"{first_path.stem}.metadata.json"
        )
        first_metadata_bytes = first_metadata_path.read_bytes()

        # Save identical payload again immediately.
        second_path = companyfacts.save_snapshot(
            "MSFT",
            self.payload,
            self.summary,
        )

        second_metadata_path = second_path.with_name(
            f"{second_path.stem}.metadata.json"
        )

        # Both snapshots must exist independently.
        self.assertNotEqual(first_path, second_path)

        self.assertTrue(first_path.exists())
        self.assertTrue(first_metadata_path.exists())
        self.assertTrue(second_path.exists())
        self.assertTrue(second_metadata_path.exists())

        # The first snapshot must remain byte-identical.
        self.assertEqual(first_path.read_bytes(), first_bytes)
        self.assertEqual(
            first_metadata_path.read_bytes(),
            first_metadata_bytes,
        )

        # Both snapshots must contain the original payload.
        self.assertEqual(second_path.read_bytes(), self.payload)

        expected_digest = hashlib.sha256(
            self.payload
        ).hexdigest()

        for metadata_path in (
            first_metadata_path,
            second_metadata_path,
        ):
            metadata = json.loads(
                metadata_path.read_text(encoding="utf-8")
            )

            self.assertEqual(metadata["sha256"], expected_digest)
            self.assertEqual(metadata["size_bytes"], len(self.payload))
            self.assertEqual(metadata["ticker"], "MSFT")
            self.assertEqual(metadata["cik"], 789019)

        # No temporary files should remain.
        self.assertEqual(
            list((self.raw_dir / "MSFT").glob("*.tmp")),
            [],
        )


if __name__ == "__main__":
    unittest.main()
