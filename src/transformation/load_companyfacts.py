
import argparse
import hashlib
import json
import time
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq


RAW_DIR = Path("data/raw/sec/companyfacts")
PARQUET_DIR = Path("data/processed/companyfacts")
DB_PATH = Path("data/warehouse/financial_intelligence.duckdb")

COMPANIES = {
    "MSFT": 789019,
    "JPM": 19617,
    "CAT": 18230,
}


CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS financial_observations (
    snapshot_id VARCHAR NOT NULL,
    observation_index BIGINT NOT NULL,
    cik INTEGER NOT NULL,
    taxonomy VARCHAR NOT NULL,
    concept VARCHAR NOT NULL,
    unit VARCHAR NOT NULL,
    value DOUBLE,
    start_date DATE,
    end_date DATE,
    accession VARCHAR,
    filed_date DATE,
    form VARCHAR,
    fiscal_year INTEGER,
    fiscal_period VARCHAR,
    frame VARCHAR,
    raw_observation JSON
)
"""


def latest_snapshot(ticker):
    folder = RAW_DIR / ticker

    snapshots = sorted(
        path
        for path in folder.glob("*.json")
        if not path.name.endswith(".metadata.json")
    )

    if not snapshots:
        raise FileNotFoundError(
            f"No snapshots found for {ticker}"
        )

    return snapshots[-1]


def normalize(data, snapshot_id):
    rows = []
    index = 0

    for taxonomy, concepts in data["facts"].items():
        for concept_name, concept_data in concepts.items():
            for unit, observations in concept_data["units"].items():
                for observation in observations:
                    rows.append({
                        "snapshot_id": snapshot_id,
                        "observation_index": index,
                        "cik": data["cik"],
                        "taxonomy": taxonomy,
                        "concept": concept_name,
                        "unit": unit,
                        "value": observation.get("val"),
                        "start_date": observation.get("start"),
                        "end_date": observation.get("end"),
                        "accession": observation.get("accn"),
                        "filed_date": observation.get("filed"),
                        "form": observation.get("form"),
                        "fiscal_year": observation.get("fy"),
                        "fiscal_period": observation.get("fp"),
                        "frame": observation.get("frame"),
                        "raw_observation": json.dumps(observation),
                    })
                    index += 1

    return rows


def write_parquet(rows, ticker, snapshot_id):
    output_dir = PARQUET_DIR / ticker
    output_dir.mkdir(parents=True, exist_ok=True)

    output_path = output_dir / f"{snapshot_id}.parquet"

    schema = pa.schema([
        ("snapshot_id", pa.string()),
        ("observation_index", pa.int64()),
        ("cik", pa.int32()),
        ("taxonomy", pa.string()),
        ("concept", pa.string()),
        ("unit", pa.string()),
        ("value", pa.float64()),
        ("start_date", pa.date32()),
        ("end_date", pa.date32()),
        ("accession", pa.string()),
        ("filed_date", pa.date32()),
        ("form", pa.string()),
        ("fiscal_year", pa.int32()),
        ("fiscal_period", pa.string()),
        ("frame", pa.string()),
        ("raw_observation", pa.string()),
    ])

    # Arrow converts ISO date strings to date32.
    # Use explicit conversion for predictable typing.
    from datetime import date

    for row in rows:
        for column in ("start_date", "end_date", "filed_date"):
            if row[column] is not None:
                row[column] = date.fromisoformat(row[column])

    table = pa.Table.from_pylist(rows, schema=schema)
    pq.write_table(table, output_path, compression="zstd")

    return output_path


def load_duckdb(parquet_path, snapshot_id, expected_count):
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect(str(DB_PATH))

    try:
        con.execute("BEGIN TRANSACTION")
        con.execute(CREATE_TABLE_SQL)

        con.execute(
            """
            DELETE FROM financial_observations
            WHERE snapshot_id = ?
            """,
            [snapshot_id],
        )

        con.execute(
            """
            INSERT INTO financial_observations
            SELECT
                snapshot_id,
                observation_index,
                cik,
                taxonomy,
                concept,
                unit,
                value,
                start_date,
                end_date,
                accession,
                filed_date,
                form,
                fiscal_year,
                fiscal_period,
                frame,
                raw_observation::JSON
            FROM read_parquet(?)
            """,
            [str(parquet_path)],
        )

        actual_count = con.execute(
            """
            SELECT COUNT(*)
            FROM financial_observations
            WHERE snapshot_id = ?
            """,
            [snapshot_id],
        ).fetchone()[0]

        if actual_count != expected_count:
            raise RuntimeError(
                f"Count mismatch: {actual_count} != {expected_count}"
            )

        con.execute("COMMIT")

        return actual_count

    except Exception:
        con.execute("ROLLBACK")
        raise

    finally:
        con.close()


def inspect_microsoft(snapshot_id):
    con = duckdb.connect(str(DB_PATH), read_only=True)

    try:
        return con.execute(
            """
            SELECT DISTINCT
                value,
                filed_date,
                accession
            FROM financial_observations
            WHERE snapshot_id = ?
              AND cik = 789019
              AND taxonomy = 'us-gaap'
              AND concept = 'AccountsReceivableNetCurrent'
              AND unit = 'USD'
              AND end_date = DATE '2017-06-30'
            ORDER BY filed_date, accession, value
            """,
            [snapshot_id],
        ).fetchall()
    finally:
        con.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("ticker", choices=sorted(COMPANIES))
    args = parser.parse_args()

    start = time.perf_counter()

    snapshot = latest_snapshot(args.ticker)
    payload = snapshot.read_bytes()
    data = json.loads(payload)

    if data.get("cik") != COMPANIES[args.ticker]:
        raise ValueError("Snapshot CIK does not match ticker")

    snapshot_id = hashlib.sha256(payload).hexdigest()
    rows = normalize(data, snapshot_id)

    print(f"Snapshot: {snapshot.name}")
    print(f"Normalized observations: {len(rows):,}")

    parquet_path = write_parquet(
        rows, args.ticker, snapshot_id
    )

    loaded = load_duckdb(
        parquet_path, snapshot_id, len(rows)
    )

    print(f"Parquet: {parquet_path}")
    print(f"DuckDB rows: {loaded:,}")

    if args.ticker == "MSFT":
        print("\nMicrosoft AR — 2017-06-30")

        for value, filed, accession in inspect_microsoft(snapshot_id):
            print(
                f"{filed} | ${value:,.0f} | {accession}"
            )

    elapsed = time.perf_counter() - start

    print(f"\nElapsed: {elapsed:.2f}s")
    print("PASS: Bulk load completed")


if __name__ == "__main__":
    main()
