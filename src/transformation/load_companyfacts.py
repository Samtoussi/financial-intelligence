import os
import tempfile

import argparse
import hashlib
import json
import time
from datetime import date, datetime, timezone
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

CREATE_METADATA_SQL = """
CREATE TABLE IF NOT EXISTS loaded_snapshots (
    cik INTEGER NOT NULL,
    snapshot_id VARCHAR NOT NULL,
    loaded_at TIMESTAMP NOT NULL,
    row_count BIGINT NOT NULL,
    retrieved_at_utc TIMESTAMPTZ,
    PRIMARY KEY (cik, snapshot_id)
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


def read_snapshot_metadata(snapshot_path, ticker, cik, snapshot_id):
    metadata_path = snapshot_path.with_name(
        f"{snapshot_path.stem}.metadata.json"
    )

    if not metadata_path.exists():
        raise FileNotFoundError(
            f"Missing snapshot metadata: {metadata_path}"
        )

    metadata = json.loads(
        metadata_path.read_text(encoding="utf-8")
    )

    if metadata.get("ticker") != ticker:
        raise ValueError("Metadata ticker mismatch")

    if metadata.get("cik") != cik:
        raise ValueError("Metadata CIK mismatch")

    if metadata.get("sha256") != snapshot_id:
        raise ValueError("Metadata SHA-256 mismatch")

    retrieved_at = datetime.fromisoformat(
        metadata["retrieved_at_utc"]
    )

    if retrieved_at.tzinfo is None:
        raise ValueError(
            "Snapshot retrieval timestamp must include timezone"
        )

    return retrieved_at.astimezone(timezone.utc)


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

    for row in rows:
        for column in ("start_date", "end_date", "filed_date"):
            if isinstance(row[column], str):
                row[column] = date.fromisoformat(row[column])

    table = pa.Table.from_pylist(rows, schema=schema)

    temp_path = None

    try:
        with tempfile.NamedTemporaryFile(
            dir=output_dir,
            prefix=".companyfacts_",
            suffix=".parquet",
            delete=False,
        ) as temp:
            temp_path = Path(temp.name)

        pq.write_table(
            table,
            temp_path,
            compression="zstd",
        )

        verified = pq.read_table(temp_path)

        if verified.num_rows != len(rows):
            raise ValueError("Parquet verification failed")

        os.replace(temp_path, output_path)

    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)

    return output_path


def validate_parquet(con, parquet_path, snapshot_id, cik, expected_count):
    if expected_count <= 0:
        raise ValueError("Cannot load an empty snapshot")

    result = con.execute(
        """
        SELECT
            COUNT(*) AS total_rows,
            COUNT(*) FILTER (
                WHERE cik IS DISTINCT FROM ?
            ) AS wrong_cik,
            COUNT(*) FILTER (
                WHERE snapshot_id IS DISTINCT FROM ?
            ) AS wrong_snapshot,
            COUNT(DISTINCT observation_index) AS unique_indices
        FROM read_parquet(?)
        """,
        [cik, snapshot_id, str(parquet_path)],
    ).fetchone()

    total, wrong_cik, wrong_snapshot, unique_indices = result

    if total != expected_count:
        raise ValueError(
            f"Parquet count mismatch: {total} != {expected_count}"
        )

    if wrong_cik:
        raise ValueError(
            f"Parquet contains {wrong_cik} rows with incorrect CIK"
        )

    if wrong_snapshot:
        raise ValueError(
            f"Parquet contains {wrong_snapshot} rows with incorrect snapshot ID"
        )

    if unique_indices != total:
        raise ValueError(
            "Parquet contains duplicate or null observation indices"
        )


def migrate_loaded_snapshots(con):
    columns = {
        row[1]
        for row in con.execute(
            "PRAGMA table_info('loaded_snapshots')"
        ).fetchall()
    }

    if "retrieved_at_utc" not in columns:
        con.execute(
            """
            ALTER TABLE loaded_snapshots
            ADD COLUMN retrieved_at_utc TIMESTAMPTZ
            """
        )


def active_snapshot(con, cik):
    rows = con.execute(
        """
        SELECT DISTINCT snapshot_id
        FROM financial_observations
        WHERE cik = ?
        """,
        [cik],
    ).fetchall()

    if len(rows) > 1:
        raise RuntimeError(
            f"Company {cik} has multiple active snapshots"
        )

    return rows[0][0] if rows else None


def load_duckdb(
    parquet_path,
    snapshot_id,
    expected_count,
    cik,
    retrieved_at_utc,
):
    if retrieved_at_utc.tzinfo is None:
        raise ValueError("Retrieval timestamp must include timezone")

    retrieved_at_utc = retrieved_at_utc.astimezone(timezone.utc)

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect(str(DB_PATH))
    transaction_started = False

    try:
        con.execute("BEGIN TRANSACTION")
        transaction_started = True

        con.execute(CREATE_TABLE_SQL)
        con.execute(CREATE_METADATA_SQL)
        migrate_loaded_snapshots(con)

        validate_parquet(
            con,
            parquet_path,
            snapshot_id,
            cik,
            expected_count,
        )

        current_id = active_snapshot(con, cik)

        if current_id is not None and current_id != snapshot_id:
            current_row = con.execute(
                """
                SELECT retrieved_at_utc
                FROM loaded_snapshots
                WHERE cik = ?
                  AND snapshot_id = ?
                """,
                [cik, current_id],
            ).fetchone()

            if current_row is None or current_row[0] is None:
                raise RuntimeError(
                    "Active snapshot has no retrieval timestamp. "
                    "Run metadata migration before replacement."
                )

            current_time = current_row[0]

            if retrieved_at_utc <= current_time:
                raise ValueError(
                    "Incoming snapshot is not newer than "
                    "the active snapshot"
                )

        con.execute(
            """
            DELETE FROM financial_observations
            WHERE cik = ?
            """,
            [cik],
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
            WHERE cik = ?
              AND snapshot_id = ?
            """,
            [cik, snapshot_id],
        ).fetchone()[0]

        if actual_count != expected_count:
            raise RuntimeError(
                f"Count mismatch: {actual_count} != {expected_count}"
            )

        con.execute(
            """
            INSERT INTO loaded_snapshots (
                cik,
                snapshot_id,
                loaded_at,
                row_count,
                retrieved_at_utc
            )
            VALUES (?, ?, CURRENT_TIMESTAMP, ?, ?)
            ON CONFLICT (cik, snapshot_id)
            DO UPDATE SET
                loaded_at = EXCLUDED.loaded_at,
                row_count = EXCLUDED.row_count,
                retrieved_at_utc = EXCLUDED.retrieved_at_utc
            """,
            [cik, snapshot_id, actual_count, retrieved_at_utc],
        )

        con.execute("COMMIT")
        transaction_started = False

        return actual_count

    except Exception:
        if transaction_started:
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

    cik = COMPANIES[args.ticker]

    if data.get("cik") != cik:
        raise ValueError("Snapshot CIK does not match ticker")

    snapshot_id = hashlib.sha256(payload).hexdigest()

    retrieved_at_utc = read_snapshot_metadata(
        snapshot,
        args.ticker,
        cik,
        snapshot_id,
    )

    rows = normalize(data, snapshot_id)

    print(f"Snapshot: {snapshot.name}")
    print(f"Retrieved: {retrieved_at_utc.isoformat()}")
    print(f"Normalized observations: {len(rows):,}")

    parquet_path = write_parquet(
        rows,
        args.ticker,
        snapshot_id,
    )

    loaded = load_duckdb(
        parquet_path,
        snapshot_id,
        len(rows),
        cik,
        retrieved_at_utc,
    )

    print(f"Parquet: {parquet_path}")
    print(f"DuckDB rows: {loaded:,}")

    if args.ticker == "MSFT":
        print("\nMicrosoft AR — 2017-06-30")

        for value, filed, accession in inspect_microsoft(snapshot_id):
            print(f"{filed} | ${value:,.0f} | {accession}")

    elapsed = time.perf_counter() - start

    print(f"\nElapsed: {elapsed:.2f}s")
    print("PASS: Bulk load completed")


if __name__ == "__main__":
    main()