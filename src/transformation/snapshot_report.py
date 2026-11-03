
import argparse
import json
from collections import Counter
from datetime import datetime
from pathlib import Path

import pyarrow.parquet as pq

from src.transformation.snapshot_comparison import compare_snapshots


ROOT = Path(__file__).resolve().parents[2]
BRONZE_ROOT = ROOT / "data/raw/sec/companyfacts"
SILVER_ROOT = ROOT / "data/processed/companyfacts"


def find_snapshots(ticker):
    folder = BRONZE_ROOT / ticker
    snapshots = {}

    for path in folder.glob("*.metadata.json"):
        metadata = json.loads(path.read_text(encoding="utf-8"))

        if metadata.get("ticker") != ticker:
            continue

        snapshot_id = metadata["sha256"]
        retrieved_at = datetime.fromisoformat(
            metadata["retrieved_at_utc"]
        )

        parquet_path = (
            SILVER_ROOT / ticker / f"{snapshot_id}.parquet"
        )

        if not parquet_path.is_file():
            continue

        previous = snapshots.get(snapshot_id)

        if previous is None or retrieved_at > previous["retrieved_at"]:
            snapshots[snapshot_id] = {
                "snapshot_id": snapshot_id,
                "retrieved_at": retrieved_at,
                "parquet_path": parquet_path,
            }

    return sorted(
        snapshots.values(),
        key=lambda item: (item["retrieved_at"], item["snapshot_id"]),
    )


def summarize_changes(result):
    return {
        "added": len(result["added"]),
        "removed": len(result["removed"]),
        "changed": len(result["changed"]),
        "ambiguous": len(result["ambiguous"]),
        "added_forms": dict(
            Counter(row["form"] for row in result["added"])
        ),
    }


def build_report(ticker):
    snapshots = find_snapshots(ticker)

    if len(snapshots) < 2:
        raise ValueError(
            f"{ticker}: at least two distinct snapshots are required"
        )

    before_info, after_info = snapshots[-2:]

    before = pq.read_table(before_info["parquet_path"]).to_pylist()
    after = pq.read_table(after_info["parquet_path"]).to_pylist()

    result = compare_snapshots(before, after)

    return {
        "ticker": ticker,
        "before": before_info,
        "after": after_info,
        "summary": summarize_changes(result),
    }


def main():
    parser = argparse.ArgumentParser(
        description="Compare historical SEC CompanyFacts snapshots"
    )
    parser.add_argument("ticker", type=str.upper)
    args = parser.parse_args()

    report = build_report(args.ticker)

    print(f"\nCompanyFacts Snapshot Comparison: {report['ticker']}")
    print("=" * 55)

    for label in ("before", "after"):
        snapshot = report[label]
        print(
            f"{label.capitalize()}: "
            f"{snapshot['retrieved_at'].isoformat()} "
            f"({snapshot['snapshot_id'][:12]})"
        )

    print("\nChanges:")
    for category in ("added", "removed", "changed", "ambiguous"):
        print(f"  {category.capitalize()}: {report['summary'][category]:,}")

    print("\nAdded SEC forms:")
    forms = report["summary"]["added_forms"]

    if forms:
        for form, count in sorted(
            forms.items(),
            key=lambda item: (-item[1], item[0]),
        ):
            print(f"  {form}: {count:,}")
    else:
        print("  None")


if __name__ == "__main__":
    main()
