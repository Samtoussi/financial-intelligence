
import argparse
import hashlib
import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import requests


BASE_URL = "https://data.sec.gov/api/xbrl/companyfacts"
RAW_DIR = Path("data/raw/sec/companyfacts")

COMPANIES = {
    "MSFT": 789019,
    "JPM": 19617,
    "CAT": 18230,
}


def fetch_companyfacts(cik: int, user_agent: str) -> bytes:
    url = f"{BASE_URL}/CIK{cik:010d}.json"

    session = requests.Session()
    session.headers.update({
        "User-Agent": user_agent,
        "Accept": "application/json",
        "Accept-Encoding": "gzip, deflate",
    })

    for attempt in range(1, 4):
        try:
            response = session.get(url, timeout=60)

            if response.status_code in (429, 500, 502, 503, 504):
                if attempt < 3:
                    wait = 2 ** attempt
                    print(
                        f"HTTP {response.status_code}. "
                        f"Retrying in {wait}s..."
                    )
                    time.sleep(wait)
                    continue

            response.raise_for_status()
            return response.content

        except (requests.Timeout, requests.ConnectionError):
            if attempt == 3:
                raise

            wait = 2 ** attempt
            print(f"Connection issue. Retrying in {wait}s...")
            time.sleep(wait)

    raise RuntimeError("SEC request failed after retries")


def validate_companyfacts(payload: bytes, expected_cik: int) -> dict:
    data = json.loads(payload)

    if not isinstance(data, dict):
        raise ValueError("Expected a JSON object")

    if data.get("cik") != expected_cik:
        raise ValueError(
            f"CIK mismatch: expected {expected_cik}, "
            f"got {data.get('cik')}"
        )

    facts = data.get("facts")

    if not isinstance(facts, dict) or not facts:
        raise ValueError("Missing or empty facts object")

    concept_count = 0
    observation_count = 0

    for taxonomy, concepts in facts.items():
        if not isinstance(concepts, dict):
            raise ValueError(f"Invalid taxonomy: {taxonomy}")

        for concept_name, concept in concepts.items():
            concept_count += 1

            units = concept.get("units", {})
            if not isinstance(units, dict):
                raise ValueError(
                    f"Invalid units for {taxonomy}.{concept_name}"
                )

            for observations in units.values():
                if not isinstance(observations, list):
                    raise ValueError("Invalid observation collection")

                observation_count += len(observations)

    if observation_count == 0:
        raise ValueError("No observations found")

    return {
        "company": data.get("entityName"),
        "cik": data["cik"],
        "taxonomies": len(facts),
        "concepts": concept_count,
        "observations": observation_count,
    }


def save_snapshot(
    ticker: str,
    payload: bytes,
    summary: dict,
) -> Path:
    retrieved_at = datetime.now(timezone.utc)
    timestamp = retrieved_at.strftime("%Y%m%dT%H%M%SZ")
    digest = hashlib.sha256(payload).hexdigest()

    output_dir = RAW_DIR / ticker
    output_dir.mkdir(parents=True, exist_ok=True)

    # The timestamp preserves chronological filename ordering.
    # A random suffix prevents repeated saves in the same second
    # from targeting the same snapshot files.
    filename = f"{timestamp}_{digest[:12]}_{uuid.uuid4().hex[:12]}"
    json_path = output_dir / f"{filename}.json"
    metadata_path = output_dir / f"{filename}.metadata.json"

    metadata = {
        "ticker": ticker,
        "source_url": (
            f"{BASE_URL}/CIK{summary['cik']:010d}.json"
        ),
        "retrieved_at_utc": retrieved_at.isoformat(),
        "sha256": digest,
        "size_bytes": len(payload),
        **summary,
    }

    temp_json = json_path.with_suffix(".json.tmp")
    temp_metadata = metadata_path.with_suffix(".json.tmp")

    published_json = False

    try:
        temp_json.write_bytes(payload)
        temp_metadata.write_text(
            json.dumps(metadata, indent=2),
            encoding="utf-8",
        )

        # Reject a pre-existing destination rather than
        # intentionally replacing historical artifacts.
        if json_path.exists() or metadata_path.exists():
            raise FileExistsError(
                f"Snapshot destination already exists: {filename}"
            )

        os.replace(temp_json, json_path)
        published_json = True

        os.replace(temp_metadata, metadata_path)

    except Exception:
        # Only remove a payload published by this invocation.
        if published_json:
            json_path.unlink(missing_ok=True)
        raise

    finally:
        temp_json.unlink(missing_ok=True)
        temp_metadata.unlink(missing_ok=True)

    return json_path


def main():
    parser = argparse.ArgumentParser(
        description="Download SEC Company Facts snapshots"
    )
    parser.add_argument(
        "ticker",
        choices=sorted(COMPANIES),
        help="Company ticker",
    )
    args = parser.parse_args()

    user_agent = os.environ.get("SEC_USER_AGENT", "").strip()

    if not user_agent or "@" not in user_agent:
        raise ValueError(
            "Set SEC_USER_AGENT to an identifying application "
            "name and your real contact email."
        )

    ticker = args.ticker
    cik = COMPANIES[ticker]

    print(f"Fetching {ticker} (CIK {cik})...")

    payload = fetch_companyfacts(cik, user_agent)
    summary = validate_companyfacts(payload, cik)
    path = save_snapshot(ticker, payload, summary)

    print(f"Company:      {summary['company']}")
    print(f"Concepts:     {summary['concepts']:,}")
    print(f"Observations: {summary['observations']:,}")
    print(f"Saved:        {path}")
    print("PASS: Raw snapshot validated and persisted")


if __name__ == "__main__":
    main()
