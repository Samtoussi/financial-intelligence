"""Shared runtime warehouse path for ingestion and financial readers."""
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def get_duckdb_path() -> Path:
    """Read overrides on each call; relative overrides follow the process cwd."""
    return Path(os.environ.get(
        "FI_DUCKDB_PATH", str(ROOT / "data/warehouse/financial_intelligence.duckdb"),
    )).resolve()
