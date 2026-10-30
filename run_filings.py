
import argparse
import os
import sys
import time
from pathlib import Path

from src.ingestion.companyfacts import COMPANIES
from src.ingestion.filings import (
    discover_latest_10k,
    discover_filing,
    fetch,
    save_snapshot,
)
from src.transformation.store_filings import (
    prepare_sections,
    save_sections,
)
from src.transformation.chunk_filings import process_ticker


ROOT = Path(__file__).resolve().parent


def run_filings(ticker: str, *, form: str = "10-K", accession: str | None = None) -> None:
    start = time.perf_counter()
    os.chdir(ROOT)

    ticker = ticker.upper()

    if ticker not in COMPANIES:
        raise ValueError(
            f"Unsupported ticker: {ticker}. "
            f"Available: {', '.join(COMPANIES)}"
        )

    user_agent = os.environ.get(
        "SEC_USER_AGENT", ""
    ).strip()

    if not user_agent or "@" not in user_agent:
        raise ValueError(
            "Set SEC_USER_AGENT to an identifying application "
            "name and your real contact email."
        )

    cik = COMPANIES[ticker]

    print(f"\n{'=' * 60}")
    print(f"DOCUMENT PIPELINE: {ticker}")
    print(f"CIK: {cik}")
    print("=" * 60)

    # Bronze: Discover and download the latest SEC 10-K.
    print(f"\n[BRONZE] Discovering {form}" + (f" {accession}..." if accession else " (latest)..."))

    filing = (discover_latest_10k(cik, user_agent) if form == "10-K" and accession is None
              else discover_filing(cik, user_agent, form, accession))

    print(f"Accession: {filing['accession']}")
    print(f"Filing date: {filing['filing_date']}")
    print(f"Source: {filing['source_url']}")

    payload = fetch(
        filing["source_url"],
        user_agent,
    )

    snapshot_path = save_snapshot(
        ticker,
        payload,
        filing,
    )

    print(f"Snapshot: {snapshot_path}")

    # Silver: Parse and validate Item 1A and Item 7.
    print(f"\n[SILVER] Extracting {form} sections...")

    records = prepare_sections(ticker, form=form, accession=filing["accession"], snapshot_path=snapshot_path)

    for record in records:
        print(
            f"Item {record['item']}: "
            f"{record['words']:,} words "
            f"({record['extraction_method']})"
        )

    sections_path = save_sections(
        ticker,
        records,
    )

    print(f"Sections: {sections_path}")

    # Retrieval: Create searchable Parquet chunks.
    print("\n[RETRIEVAL] Building filing chunks...")

    chunks_path, chunk_count = process_ticker(
        ticker
    )

    print(f"Chunks: {chunk_count}")
    print(f"Saved: {chunks_path}")

    elapsed = time.perf_counter() - start

    print(f"\n{'=' * 60}")
    print("DOCUMENT PIPELINE COMPLETED SUCCESSFULLY")
    print(f"Ticker: {ticker}")
    print(f"Accession: {filing['accession']}")
    print(f"Sections: {len(records)}")
    print(f"Searchable chunks: {chunk_count}")
    print(f"Elapsed: {elapsed:.2f}s")
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(
        description="SEC document pipeline (default: latest 10-K)"
    )

    parser.add_argument(
        "ticker",
        help="Company ticker, e.g. MSFT",
    )

    parser.add_argument("--form", choices=("10-K", "10-Q"), default="10-K")
    parser.add_argument("--accession")

    args = parser.parse_args()

    try:
        run_filings(args.ticker, form=args.form, accession=args.accession)
    except Exception as exc:
        print(
            f"\nDOCUMENT PIPELINE FAILED: {exc}",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
