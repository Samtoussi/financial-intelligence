from pathlib import Path

import duckdb

DB_PATH = Path("data/warehouse/financial_intelligence.duckdb")


def main():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    if DB_PATH.exists():
        raise FileExistsError(
            f"Refusing to overwrite existing database: {DB_PATH}"
        )

    rows = [
        # Microsoft: FY2015 -> FY2016 should NOT be comparable.
        (789019, "SalesRevenueNet", 90000000000, "2014-07-01", "2015-06-30", "2015-07-31", "msft-2015"),
        (789019, "RevenueFromContractWithCustomerExcludingAssessedTax", 95000000000, "2015-07-01", "2016-06-30", "2017-07-31", "msft-2016"),
        (789019, "RevenueFromContractWithCustomerExcludingAssessedTax", 105000000000, "2016-07-01", "2017-06-30", "2017-07-31", "msft-2017"),

        # Caterpillar: repeated filing for the same fiscal year.
        (18230, "Revenues", 50000000000, "2023-01-01", "2023-12-31", "2024-02-01", "cat-old"),
        (18230, "Revenues", 51000000000, "2023-01-01", "2023-12-31", "2024-03-01", "cat-new"),
        (18230, "Revenues", 55000000000, "2024-01-01", "2024-12-31", "2025-02-01", "cat-2024"),

        # JPMorgan: concept priority and annual growth.
        (19617, "RevenuesNetOfInterestExpense", 140000000000, "2023-01-01", "2023-12-31", "2024-02-01", "jpm-alt"),
        (19617, "Revenues", 145000000000, "2023-01-01", "2023-12-31", "2024-02-01", "jpm-main"),
        (19617, "Revenues", 155000000000, "2024-01-01", "2024-12-31", "2025-02-01", "jpm-2024"),
    ]

    con = duckdb.connect(str(DB_PATH))

    try:
        con.execute("""
            CREATE TABLE main.financial_observations (
                cik INTEGER,
                taxonomy VARCHAR,
                concept VARCHAR,
                unit VARCHAR,
                value DOUBLE,
                start_date DATE,
                end_date DATE,
                accession VARCHAR,
                filed_date DATE,
                form VARCHAR
            )
        """)

        con.executemany(
            """
            INSERT INTO main.financial_observations
            VALUES (
                ?, 'us-gaap', ?, 'USD', ?,
                CAST(? AS DATE),
                CAST(? AS DATE),
                ?, CAST(? AS DATE), '10-K'
            )
            """,
            [
                (cik, concept, value, start, end, accession, filed)
                for cik, concept, value, start, end, filed, accession in rows
            ],
        )

        print(f"Created CI database: {DB_PATH}")
        print(f"Inserted {len(rows)} synthetic observations")
    finally:
        con.close()


if __name__ == "__main__":
    main()