
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import duckdb

from src.ingestion.companyfacts import (
    COMPANIES,
    fetch_companyfacts,
    save_snapshot,
    validate_companyfacts,
)
from src.operations.dbt_results import summarize_dbt_results
from src.operations.run_tracking import RunTracker
from src.transformation.load_companyfacts import (
    active_snapshot,
    load_duckdb,
    normalize,
    read_snapshot_metadata,
    write_parquet,
)
from src.warehouse import get_duckdb_path


ROOT = Path(__file__).resolve().parent


def get_active_snapshot(cik):
    """Return the warehouse's active snapshot, or None if uninitialized."""
    db_path = get_duckdb_path()

    if not db_path.exists():
        return None

    con = duckdb.connect(str(db_path), read_only=True)

    try:
        table_exists = con.execute(
            """
            SELECT COUNT(*)
            FROM information_schema.tables
            WHERE table_schema = 'main'
              AND table_name = 'financial_observations'
            """
        ).fetchone()[0]

        if not table_exists:
            return None

        return active_snapshot(con, cik)
    finally:
        con.close()


def run_pipeline():
    start = time.perf_counter()
    os.chdir(ROOT)

    tracker = RunTracker("companyfacts", ROOT)
    gold_diagnostics = None

    print(f"\nRUN ID: {tracker.run_id}")
    print(f"Manifest: {tracker.manifest_path}")

    try:
        tracker.start_stage("preflight")

        user_agent = os.environ.get("SEC_USER_AGENT", "").strip()

        if not user_agent or "@" not in user_agent:
            raise ValueError(
                "Set SEC_USER_AGENT to an identifying application "
                "name and your real contact email."
            )

        tracker.complete_stage()

        for ticker, cik in COMPANIES.items():
            print(f"\n{'=' * 60}")
            print(f"PROCESSING {ticker} (CIK {cik})")
            print("=" * 60)

            # Bronze: SEC EDGAR -> raw JSON
            tracker.start_stage("bronze", ticker)
            print("\n[BRONZE] Fetching SEC CompanyFacts...")

            payload = fetch_companyfacts(cik, user_agent)
            summary = validate_companyfacts(payload, cik)
            snapshot_path = save_snapshot(ticker, payload, summary)

            snapshot_id = hashlib.sha256(payload).hexdigest()

            print(f"Saved: {snapshot_path}")
            print(f"Observations: {summary['observations']:,}")

            tracker.complete_stage({
                "snapshot_path": str(snapshot_path),
                "snapshot_sha256": snapshot_id,
                "observations": summary["observations"],
            })

            # Silver: skip when warehouse already has this snapshot
            tracker.start_stage("silver", ticker)

            current_snapshot = get_active_snapshot(cik)

            if current_snapshot == snapshot_id:
                print(
                    "\n[SILVER] SKIPPED: "
                    "Snapshot already active in warehouse."
                )
                print(f"SHA-256: {snapshot_id}")

                tracker.complete_stage({
                    "skipped": True,
                    "reason": "unchanged_snapshot",
                    "snapshot_sha256": snapshot_id,
                })
                continue

            print("\n[SILVER] Normalizing and loading...")

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

            tracker.complete_stage({
                "skipped": False,
                "parquet_path": str(parquet_path),
                "snapshot_sha256": snapshot_id,
                "normalized_rows": len(rows),
                "loaded_rows": loaded,
            })

        # Gold: dbt models + tests
        tracker.start_stage("gold")

        print(f"\n{'=' * 60}")
        print("GOLD - DBT BUILD")
        print("=" * 60)

        dbt_target = tracker.run_dir / "dbt"

        warehouse_path = get_duckdb_path()

        try:
            subprocess.run(
                [
                    "dbt",
                    "build",
                    "--project-dir",
                    "dbt",
                    "--profiles-dir",
                    "dbt",
                    "--target-path",
                    str(dbt_target),
                ],
                check=True,
                cwd=ROOT,
            )
        except subprocess.CalledProcessError:
            if (dbt_target / "run_results.json").is_file():
                try:
                    gold_diagnostics = summarize_dbt_results(dbt_target)
                    gold_diagnostics["warehouse_path"] = str(warehouse_path)
                except (ValueError, KeyError, TypeError, json.JSONDecodeError):
                    gold_diagnostics = {
                        "artifact_status": "invalid",
                        "warehouse_path": str(warehouse_path),
                    }
            else:
                gold_diagnostics = {
                    "artifact_status": "missing",
                    "warehouse_path": str(warehouse_path),
                }
            raise

        dbt_summary = summarize_dbt_results(dbt_target)
        gold_diagnostics = {
            **dbt_summary,
            "warehouse_path": str(warehouse_path),
        }

        if dbt_summary["failed"]:
            raise RuntimeError(
                "dbt reported failed nodes despite a successful exit code"
            )

        tracker.complete_stage(gold_diagnostics)
        tracker.complete()

    except Exception as exc:
        try:
            if tracker.manifest["status"] == "running":
                tracker.fail(exc, artifacts=gold_diagnostics)
        except Exception as tracking_error:
            print(
                f"RUN TRACKING FAILED: {type(tracking_error).__name__}",
                file=sys.stderr,
            )
        raise

    elapsed = time.perf_counter() - start

    print(f"\n{'=' * 60}")
    print("PIPELINE COMPLETED SUCCESSFULLY")
    print(f"Run ID: {tracker.run_id}")
    print(f"Manifest: {tracker.manifest_path}")
    print(f"Elapsed: {elapsed:.2f}s")
    print("=" * 60)


if __name__ == "__main__":
    try:
        run_pipeline()
    except Exception as exc:
        print(
            f"\nPIPELINE FAILED: {type(exc).__name__}",
            file=sys.stderr,
        )
        sys.exit(1)
