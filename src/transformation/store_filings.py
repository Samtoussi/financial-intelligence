
import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from src.ingestion.companyfacts import COMPANIES
from src.transformation.parse_filings import parse_filing


OUTPUT_DIR = Path("data/processed/filings")

SCHEMA = pa.schema(
    [
        ("ticker", pa.string()),
        ("cik", pa.int64()),
        ("accession", pa.string()),
        ("filing_date", pa.string()),
        ("report_date", pa.string()),
        ("form", pa.string()),
        ("item", pa.string()),
        ("source_url", pa.string()),
        ("extraction_method", pa.string()),
        ("text", pa.string()),
        ("characters", pa.int64()),
        ("words", pa.int64()),
        ("text_sha256", pa.string()),
    ]
)


def prepare_sections(ticker: str) -> list[dict]:
    sections = parse_filing(ticker)

    if len(sections) != 2:
        raise ValueError(
            f"Expected 2 sections for {ticker}, got {len(sections)}"
        )

    if {section["item"] for section in sections} != {"1A", "7"}:
        raise ValueError("Unexpected or duplicate filing sections")

    records = []

    for section in sections:
        text = section["text"]

        if not text or len(text) < 500:
            raise ValueError(
                f"Invalid section text: {ticker} Item {section['item']}"
            )

        if len(text) != section["characters"]:
            raise ValueError("Character count mismatch")

        if len(text.split()) != section["words"]:
            raise ValueError("Word count mismatch")

        record = {
            **section,
            "text_sha256": hashlib.sha256(
                text.encode("utf-8")
            ).hexdigest(),
        }

        records.append(record)

    if len({record["accession"] for record in records}) != 1:
        raise ValueError("Sections belong to different filings")

    return records


def save_sections(
    ticker: str,
    records: list[dict],
    output_dir: Path = OUTPUT_DIR,
) -> Path:
    if not records:
        raise ValueError("Cannot save empty records")

    if any(record["ticker"] != ticker for record in records):
        raise ValueError("Ticker mismatch")

    accession = records[0]["accession"]

    if any(record["accession"] != accession for record in records):
        raise ValueError("Accession mismatch")

    target_dir = output_dir / ticker / accession
    target_dir.mkdir(parents=True, exist_ok=True)

    output_path = target_dir / "sections.parquet"

    table = pa.Table.from_pylist(records, schema=SCHEMA)

    # Write to a temporary file first, then atomically replace
    # the destination. A failed write should not corrupt an
    # existing Parquet snapshot.
    temp_path = None

    try:
        with tempfile.NamedTemporaryFile(
            dir=target_dir,
            prefix=".sections_",
            suffix=".parquet",
            delete=False,
        ) as temp:
            temp_path = Path(temp.name)

        pq.write_table(
            table,
            temp_path,
            compression="zstd",
        )

        # Verify that the file can be read before publishing it.
        verified = pq.read_table(temp_path)

        if verified.num_rows != len(records):
            raise ValueError("Parquet verification failed")

        os.replace(temp_path, output_path)

    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)

    return output_path


def main():
    parser = argparse.ArgumentParser(
        description="Store parsed SEC filing sections as Parquet"
    )

    parser.add_argument(
        "ticker",
        choices=sorted(COMPANIES),
    )

    args = parser.parse_args()

    records = prepare_sections(args.ticker)
    path = save_sections(args.ticker, records)

    print(f"\n=== {args.ticker} FILING STORAGE ===")
    print(f"Accession: {records[0]['accession']}")
    print(f"Sections: {len(records)}")

    for record in records:
        print(
            f"Item {record['item']}: "
            f"{record['words']:,} words "
            f"({record['extraction_method']})"
        )

    print(f"Saved: {path}")
    print("PASS: Filing sections stored as Parquet")


if __name__ == "__main__":
    main()
