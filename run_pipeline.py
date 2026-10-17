
import os
import subprocess
import sys
import time
from pathlib import Path

from src.ingestion.companyfacts import (
    COMPANIES,
    fetch_companyfacts,
    save_snapshot,
    validate_companyfacts,
)
from src.transformation.load_companyfacts import (
    load_duckdb,
    normalize,
    read_snapshot_metadata,
    write_parquet,
)

import hashlib
import json


ROOT = Path(__file__).resolve().parent


def run_pipeline():
    start = time.perf_counter()

    os.chdir(ROOT)

    user_agent = os.environ.get("SEC_USER_AGENT", "").strip()

    if not user_agent or "@" not in user_agent:
        raise ValueError(
            "Set SEC_USER_AGENT to an identifying application "
            "name and your real contact email."
        )

    for ticker, cik in COMPANIES.items():
        print(f"\n{'=' * 60}")
        print(f"PROCESSING {ticker} (CIK {cik})")
        print("=" * 60)

        # Bronze: SEC EDGAR -> raw JSON
        print("\n[BRONZE] Fetching SEC CompanyFacts...")

        payload = fetch_companyfacts(cik, user_agent)
        summary = validate_companyfacts(payload, cik)
        snapshot_path = save_snapshot(ticker, payload, summary)

        print(f"Saved: {snapshot_path}")
        print(f"Observations: {summary['observations']:,}")

        # Silver: raw JSON -> Parquet -> DuckDB
        print("\n[SILVER] Normalizing and loading...")

        snapshot_id = hashlib.sha256(payload).hexdigest()
        data = json.loads(payload)

        retrieved_at = read_snapshot_metadata(
            snapshot_path,
            ticker,
            cik,
            snapshot_id,
        )

        rows = normalize(data, snapshot_id)
        parquet_path = write_parquet(
            rows,
            ticker,
            snapshot_id,
        )

        loaded = load_duckdb(
            parquet_path,
            snapshot_id,
            len(rows),
            cik,
            retrieved_at,
        )

        print(f"Parquet: {parquet_path}")
        print(f"DuckDB rows: {loaded:,}")

    # Gold: dbt models + tests
    print(f"\n{'=' * 60}")
    print("GOLD — DBT BUILD")
    print("=" * 60)

    subprocess.run(
        [
            "dbt",
            "build",
            "--project-dir",
            "dbt",
            "--profiles-dir",
            "dbt",
        ],
        check=True,
        cwd=ROOT,
    )

    elapsed = time.perf_counter() - start

    print(f"\n{'=' * 60}")
    print("PIPELINE COMPLETED SUCCESSFULLY")
    print(f"Elapsed: {elapsed:.2f}s")
    print("=" * 60)


if __name__ == "__main__":
    try:
        run_pipeline()
    except Exception as exc:
        print(f"\nPIPELINE FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
