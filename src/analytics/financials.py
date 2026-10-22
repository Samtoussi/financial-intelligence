
from pathlib import Path

import duckdb


ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "data" / "warehouse" / "financial_intelligence.duckdb"

COMPANIES = {
    "MSFT": 789019,
    "CAT": 18230,
    "JPM": 19617,
}


def get_annual_financials(
    ticker: str,
    fiscal_year: int,
) -> dict | None:
    """
    Retrieve governed annual financial metrics from dbt Gold.

    Returns None if the company/year is unavailable.
    Never calculates growth outside the Gold model.
    """

    ticker = ticker.upper().strip()

    if ticker not in COMPANIES:
        raise ValueError(f"Unsupported ticker: {ticker}")

    if not isinstance(fiscal_year, int) or isinstance(fiscal_year, bool):
        raise ValueError("fiscal_year must be an integer")

    if not DB_PATH.is_file():
        raise FileNotFoundError(f"DuckDB database not found: {DB_PATH}")

    con = duckdb.connect(str(DB_PATH), read_only=True)

    try:
        row = con.execute(
            """
            SELECT
                r.cik,
                r.fiscal_year,
                r.start_date,
                r.end_date,
                r.revenue_usd,
                g.previous_year_revenue_usd,
                g.yoy_growth_pct,
                g.is_comparable,
                r.source_concept,
                r.source_accession,
                r.source_filed_date
            FROM main_gold.annual_revenue AS r
            JOIN main_gold.annual_revenue_growth AS g
              ON r.cik = g.cik
             AND r.fiscal_year = g.fiscal_year
            WHERE r.cik = ?
              AND r.fiscal_year = ?
            """,
            [COMPANIES[ticker], fiscal_year],
        ).fetchone()

    finally:
        con.close()

    if row is None:
        return None

    return {
        "ticker": ticker,
        "cik": row[0],
        "fiscal_year": row[1],
        "period_start": row[2].isoformat(),
        "period_end": row[3].isoformat(),
        "revenue_usd": row[4],
        "previous_year_revenue_usd": row[5],
        "yoy_growth_pct": row[6],
        "is_comparable": row[7],
        "source_concept": row[8],
        "source_accession": row[9],
        "source_filed_date": row[10].isoformat(),
    }
