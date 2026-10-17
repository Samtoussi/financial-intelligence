
import argparse
import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

from src.ingestion.companyfacts import COMPANIES


SUBMISSIONS_URL = "https://data.sec.gov/submissions"
ARCHIVES_URL = "https://www.sec.gov/Archives/edgar/data"
RAW_DIR = Path("data/raw/sec/filings")


def fetch(url: str, user_agent: str) -> bytes:
    session = requests.Session()
    session.headers.update({
        "User-Agent": user_agent,
        "Accept-Encoding": "gzip, deflate",
    })

    for attempt in range(1, 4):
        try:
            response = session.get(url, timeout=90)

            if response.status_code in (429, 500, 502, 503, 504):
                if attempt < 3:
                    time.sleep(2 ** attempt)
                    continue

            response.raise_for_status()
            return response.content

        except (requests.Timeout, requests.ConnectionError):
            if attempt == 3:
                raise
            time.sleep(2 ** attempt)

    raise RuntimeError("SEC request failed after retries")


def discover_latest_10k(cik: int, user_agent: str) -> dict:
    url = f"{SUBMISSIONS_URL}/CIK{cik:010d}.json"
    data = json.loads(fetch(url, user_agent))
    recent = data["filings"]["recent"]

    for index, form in enumerate(recent["form"]):
        if form != "10-K":
            continue

        accession = recent["accessionNumber"][index]
        document = recent["primaryDocument"][index]

        return {
            "cik": cik,
            "form": form,
            "accession": accession,
            "filing_date": recent["filingDate"][index],
            "report_date": recent["reportDate"][index],
            "document": document,
            "source_url": (
                f"{ARCHIVES_URL}/{cik}/"
                f"{accession.replace('-', '')}/{document}"
            ),
        }

    raise ValueError(f"No recent 10-K found for CIK {cik}")


def save_snapshot(ticker: str, payload: bytes, filing: dict) -> Path:
    if not payload.strip():
        raise ValueError("Empty filing document")

    retrieved_at = datetime.now(timezone.utc)
    timestamp = retrieved_at.strftime("%Y%m%dT%H%M%SZ")
    digest = hashlib.sha256(payload).hexdigest()

    output_dir = RAW_DIR / ticker / filing["accession"]
    output_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{timestamp}_{digest[:12]}"
    html_path = output_dir / f"{filename}.html"
    metadata_path = output_dir / f"{filename}.metadata.json"

    metadata = {
        "ticker": ticker,
        **filing,
        "retrieved_at_utc": retrieved_at.isoformat(),
        "sha256": digest,
        "size_bytes": len(payload),
    }

    temp_html = html_path.with_suffix(".html.tmp")
    temp_metadata = metadata_path.with_suffix(".json.tmp")

    try:
        temp_html.write_bytes(payload)
        temp_metadata.write_text(
            json.dumps(metadata, indent=2),
            encoding="utf-8",
        )

        os.replace(temp_html, html_path)
        os.replace(temp_metadata, metadata_path)
    finally:
        temp_html.unlink(missing_ok=True)
        temp_metadata.unlink(missing_ok=True)

    return html_path


def main():
    parser = argparse.ArgumentParser(
        description="Download latest SEC 10-K filing"
    )
    parser.add_argument("ticker", choices=sorted(COMPANIES))
    args = parser.parse_args()

    user_agent = os.environ.get("SEC_USER_AGENT", "").strip()

    if not user_agent or "@" not in user_agent:
        raise ValueError("Set SEC_USER_AGENT with a contact email")

    ticker = args.ticker
    cik = COMPANIES[ticker]

    print(f"Discovering latest 10-K for {ticker}...")

    filing = discover_latest_10k(cik, user_agent)
    payload = fetch(filing["source_url"], user_agent)
    path = save_snapshot(ticker, payload, filing)

    print(f"Accession: {filing['accession']}")
    print(f"Filing date: {filing['filing_date']}")
    print(f"Size: {len(payload):,} bytes")
    print(f"Saved: {path}")
    print("PASS: Filing snapshot persisted")


if __name__ == "__main__":
    main()
