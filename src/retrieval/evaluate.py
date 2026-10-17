
import argparse
import csv
from pathlib import Path

from src.retrieval.search_filings import search_filings


QUERIES = [
    ("interest rate risk", None),
    ("cloud revenue", "MSFT"),
    ("credit losses", "JPM"),
    ("supply chain", "CAT"),
    ("foreign exchange", None),
]

OUTPUT_PATH = Path("data/evaluation/retrieval_baseline.csv")


def evaluate(limit: int = 5) -> None:
    if limit < 1:
        raise ValueError("Limit must be positive")

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    rows = []

    for query, ticker in QUERIES:
        results = search_filings(
            query,
            ticker=ticker,
            limit=limit,
        )

        print(f"\nQUERY: {query}")
        print(f"FILTER: {ticker or 'ALL'}")
        print(f"RESULTS: {len(results)}")

        for rank, result in enumerate(results, 1):
            print(
                f"  {rank}. {result['ticker']} "
                f"Item {result['item']} "
                f"| Score {result['score']:.1f}"
            )

            rows.append({
                "query": query,
                "ticker_filter": ticker or "",
                "rank": rank,
                "result_ticker": result["ticker"],
                "item": result["item"],
                "chunk_id": result["chunk_id"],
                "score": result["score"],
                "text": result["text"],
                "source_url": result["source_url"],
                "relevance": "",
            })

    with OUTPUT_PATH.open(
        "w",
        newline="",
        encoding="utf-8",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "query",
                "ticker_filter",
                "rank",
                "result_ticker",
                "item",
                "chunk_id",
                "score",
                "text",
                "source_url",
                "relevance",
            ],
        )

        writer.writeheader()
        writer.writerows(rows)

    print("\n=== RETRIEVAL EVALUATION V1 ===")
    print(f"Queries: {len(QUERIES)}")
    print(f"Results exported: {len(rows)}")
    print(f"Saved: {OUTPUT_PATH}")
    print("PASS: Baseline exported for manual review")


def main():
    parser = argparse.ArgumentParser(
        description="Evaluate SEC filing retrieval"
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=5,
    )

    args = parser.parse_args()
    evaluate(limit=args.limit)


if __name__ == "__main__":
    main()
