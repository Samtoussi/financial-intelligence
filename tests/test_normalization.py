
import unittest

from src.transformation.load_companyfacts import normalize


class TestCompanyFactsNormalization(unittest.TestCase):

    def test_preserves_filing_history(self):
        data = {
            "cik": 789019,
            "facts": {
                "us-gaap": {
                    "AccountsReceivableNetCurrent": {
                        "units": {
                            "USD": [
                                {
                                    "val": 19792000000,
                                    "end": "2017-06-30",
                                    "accn": "original-filing",
                                    "filed": "2017-08-02",
                                    "form": "10-K",
                                },
                                {
                                    "val": 22431000000,
                                    "end": "2017-06-30",
                                    "accn": "later-filing",
                                    "filed": "2017-10-26",
                                    "form": "10-Q",
                                },
                            ]
                        }
                    }
                }
            },
        }

        rows = normalize(data, "test-snapshot")

        self.assertEqual(len(rows), 2)

        self.assertEqual(
            [row["value"] for row in rows],
            [19792000000, 22431000000],
        )

        self.assertEqual(
            [row["accession"] for row in rows],
            ["original-filing", "later-filing"],
        )

        self.assertEqual(
            [row["observation_index"] for row in rows],
            [0, 1],
        )

        self.assertTrue(
            all(row["snapshot_id"] == "test-snapshot"
                for row in rows)
        )


if __name__ == "__main__":
    unittest.main()
