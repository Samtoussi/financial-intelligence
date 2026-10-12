import unittest
from pathlib import Path

import duckdb


SQL_PATH = (
    Path(__file__).resolve().parents[1]
    / "sql"
    / "historical_value_changes.sql"
)


class TestHistoricalChanges(unittest.TestCase):

    def setUp(self):
        self.con = duckdb.connect(":memory:")

        self.con.execute("""
            CREATE TABLE financial_observations (
                cik INTEGER,
                taxonomy VARCHAR,
                concept VARCHAR,
                unit VARCHAR,
                start_date DATE,
                end_date DATE,
                accession VARCHAR,
                filed_date DATE,
                form VARCHAR,
                value DOUBLE
            )
        """)

    def tearDown(self):
        self.con.close()

    def insert_observation(
        self,
        value,
        accession,
        filed_date,
        concept="AccountsReceivableNetCurrent",
        start_date=None,
        end_date="2017-06-30",
        form="10-K",
    ):
        self.con.execute("""
            INSERT INTO financial_observations (
                cik,
                taxonomy,
                concept,
                unit,
                start_date,
                end_date,
                accession,
                filed_date,
                form,
                value
            )
            VALUES (
                789019,
                'us-gaap',
                ?,
                'USD',
                ?,
                ?,
                ?,
                ?,
                ?,
                ?
            )
        """, [
            concept,
            start_date,
            end_date,
            accession,
            filed_date,
            form,
            value,
        ])

    def run_model(self):
        sql = SQL_PATH.read_text(encoding="utf-8")

        self.con.execute(f"""
            CREATE OR REPLACE VIEW historical_value_changes AS
            {sql}
        """)

        return self.con.execute("""
            SELECT
                concept,
                previous_value,
                new_value,
                absolute_change,
                percentage_change,
                previous_accession,
                new_accession
            FROM historical_value_changes
            ORDER BY new_filed_date
        """).fetchall()

    def test_detects_historical_change(self):
        self.insert_observation(
            19792000000,
            "filing-1",
            "2017-08-02",
        )

        self.insert_observation(
            22431000000,
            "filing-2",
            "2017-10-26",
            form="10-Q",
        )

        rows = self.run_model()

        self.assertEqual(len(rows), 1)

        row = rows[0]

        self.assertEqual(row[1], 19792000000)
        self.assertEqual(row[2], 22431000000)
        self.assertEqual(row[3], 2639000000)
        self.assertEqual(row[4], 13.33)
        self.assertEqual(row[5], "filing-1")
        self.assertEqual(row[6], "filing-2")

    def test_ignores_unchanged_values(self):
        self.insert_observation(
            1000000,
            "filing-1",
            "2017-08-02",
        )

        self.insert_observation(
            1000000,
            "filing-2",
            "2017-10-26",
        )

        rows = self.run_model()

        self.assertEqual(len(rows), 0)

    def test_excludes_conflicting_filing(self):
        self.insert_observation(
            1000000,
            "filing-1",
            "2017-08-02",
        )

        self.insert_observation(
            2000000,
            "filing-1",
            "2017-08-02",
        )

        self.insert_observation(
            3000000,
            "filing-2",
            "2017-10-26",
        )

        rows = self.run_model()

        self.assertEqual(len(rows), 0)

    def test_does_not_compare_different_periods(self):
        self.insert_observation(
            1000000,
            "filing-1",
            "2017-08-02",
            end_date="2017-06-30",
        )

        self.insert_observation(
            2000000,
            "filing-2",
            "2017-10-26",
            end_date="2017-09-30",
        )

        rows = self.run_model()

        self.assertEqual(len(rows), 0)


if __name__ == "__main__":
    unittest.main()