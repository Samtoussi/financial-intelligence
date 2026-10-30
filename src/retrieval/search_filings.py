
import argparse
import re
from pathlib import Path

import duckdb


CHUNKS_PATH = "data/processed/filing_chunks/*/chunks.parquet"

COLUMNS = [
    "chunk_id",
    "ticker",
    "accession",
    "item",
    "chunk_index",
    "source_url",
    "words",
    "text",
]


def tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def calculate_score(
    query_terms: list[str],
    text: str,
) -> float:
    tokens = tokenize(text)

    if not tokens:
        return 0.0

    unique_terms = set(query_terms)

    frequencies = {
        term: tokens.count(term)
        for term in unique_terms
    }

    # Every query term must match as a complete word.
    if any(count == 0 for count in frequencies.values()):
        return 0.0

    # Normalize frequency by chunk length.
    frequency_score = (
        sum(frequencies.values()) / len(tokens)
    ) * 100

    # Reward the exact ordered query phrase.
    phrase_matches = sum(
        tokens[i:i + len(query_terms)] == query_terms
        for i in range(len(tokens) - len(query_terms) + 1)
    )

    phrase_bonus = (
        5.0 * phrase_matches
        if len(query_terms) > 1
        else 0.0
    )

    return round(frequency_score + phrase_bonus, 4)


def search_filings(
    query: str,
    ticker: str | None = None,
    limit: int = 5,
    *, accession: str | None = None,
) -> list[dict]:
    query_terms = tokenize(query)

    if not query_terms:
        raise ValueError("Search query must contain words")

    if limit < 1:
        raise ValueError("Limit must be positive")

    if not list(
        Path("data/processed/filing_chunks").glob(
            "*/chunks.parquet"
        )
    ):
        raise FileNotFoundError("No filing chunks found")

    con = duckdb.connect()

    try:
        sql = f"""
            SELECT
                chunk_id,
                ticker,
                accession,
                item,
                chunk_index,
                source_url,
                words,
                text
            FROM read_parquet('{CHUNKS_PATH}')
        """

        params = []

        filters = []
        if ticker:
            filters.append("ticker = ?")
            params.append(ticker.upper())
        if accession:
            filters.append("accession = ?")
            params.append(accession)
        else:
            # Keep the annual analyst's existing corpus when quarters are indexed.
            filters.append("form = '10-K'")
        if filters:
            sql += " WHERE " + " AND ".join(filters)

        rows = con.execute(sql, params).fetchall()

    finally:
        con.close()

    results = []

    for row in rows:
        result = dict(zip(COLUMNS, row))

        score = calculate_score(
            query_terms,
            result["text"],
        )

        if score <= 0:
            continue

        result["score"] = score
        results.append(result)

    results.sort(
        key=lambda r: (
            -r["score"],
            r["ticker"],
            r["item"],
            r["chunk_index"],
        )
    )

    return results[:limit]


def main():
    parser = argparse.ArgumentParser(
        description="Search SEC filing chunks"
    )

    parser.add_argument("query")
    parser.add_argument("--ticker")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--accession")

    args = parser.parse_args()

    results = search_filings(
        args.query,
        ticker=args.ticker,
        limit=args.limit,
        accession=args.accession,
    )

    print(f"\nQUERY: {args.query}")
    print(f"RESULTS: {len(results)}\n")

    for index, result in enumerate(results, 1):
        print(
            f"[{index}] {result['ticker']} "
            f"Item {result['item']} "
            f"| Score: {result['score']:.2f}"
        )

        print(f"Source: {result['source_url']}")
        print(f"Chunk: {result['chunk_id']}")
        print(f"Text: {result['text'][:500]}...")
        print()


if __name__ == "__main__":
    main()
