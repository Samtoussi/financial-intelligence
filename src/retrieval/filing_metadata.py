"""Look up SEC filing dates using the already processed filing sections."""
from functools import lru_cache
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[2]
SECTIONS_DIR = ROOT / "data" / "processed" / "filings"


@lru_cache(maxsize=256)
def get_filing_metadata(accession: str) -> dict | None:
    """Return metadata for an indexed accession, or None if unavailable."""
    if not isinstance(accession, str) or not accession.strip():
        return None

    paths = sorted(SECTIONS_DIR.glob("*/*/sections.parquet"))
    if not paths:
        return None

    con = duckdb.connect()
    try:
        rows = con.execute(
            """
            SELECT DISTINCT ticker, accession, form, report_date, filing_date
            FROM read_parquet(?)
            WHERE accession = ?
            """,
            [[str(path) for path in paths], accession],
        ).fetchall()
    finally:
        con.close()

    if len(rows) != 1:
        return None

    ticker, accession, form, report_date, filing_date = rows[0]
    if not all((ticker, accession, form, report_date, filing_date)):
        return None

    return {
        "ticker": ticker,
        "accession": accession,
        "form": form,
        "report_date": report_date,
        "filing_date": filing_date,
    }
