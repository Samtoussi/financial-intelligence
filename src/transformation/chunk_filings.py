
import argparse
import hashlib
import os
import re
import tempfile
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq


SECTIONS_DIR = Path("data/processed/filings")
CHUNKS_DIR = Path("data/processed/filing_chunks")

TARGET_WORDS = 300
MAX_WORDS = 350

SCHEMA = pa.schema(
    [
        ("chunk_id", pa.string()),
        ("ticker", pa.string()),
        ("cik", pa.int64()),
        ("accession", pa.string()),
        ("filing_date", pa.string()),
        ("report_date", pa.string()),
        ("form", pa.string()),
        ("item", pa.string()),
        ("source_url", pa.string()),
        ("chunk_index", pa.int64()),
        ("start_char", pa.int64()),
        ("end_char", pa.int64()),
        ("text", pa.string()),
        ("words", pa.int64()),
        ("section_sha256", pa.string()),
    ]
)


def word_count(text: str) -> int:
    return len(text.split())


def sentence_spans(text: str) -> list[tuple[int, int]]:
    # A conservative baseline: split at punctuation followed
    # by whitespace and an uppercase letter or digit.
    boundary = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])")

    spans = []
    start = 0

    for match in boundary.finditer(text):
        end = match.start()
        if text[start:end].strip():
            spans.append((start, end))
        start = match.end()

    if text[start:].strip():
        spans.append((start, len(text)))

    return spans


def split_long_span(
    text: str,
    start: int,
    end: int,
    max_words: int,
) -> list[tuple[int, int]]:
    # Some SEC tables and disclosures have no usable
    # sentence boundaries. Fall back to word boundaries.
    words = list(re.finditer(r"\S+", text[start:end]))

    result = []

    for offset in range(0, len(words), max_words):
        group = words[offset : offset + max_words]

        chunk_start = start + group[0].start()
        chunk_end = start + group[-1].end()

        result.append((chunk_start, chunk_end))

    return result


def create_chunks(
    section: dict,
    target_words: int = TARGET_WORDS,
    max_words: int = MAX_WORDS,
) -> list[dict]:
    if not 0 < target_words <= max_words:
        raise ValueError("Invalid chunk size configuration")

    text = section["text"]

    if not text or not text.strip():
        raise ValueError("Cannot chunk empty section")

    spans = []

    for start, end in sentence_spans(text):
        if word_count(text[start:end]) > max_words:
            spans.extend(
                split_long_span(text, start, end, max_words)
            )
        else:
            spans.append((start, end))

    boundaries = []
    current_start = None
    current_end = None
    current_words = 0

    for start, end in spans:
        count = word_count(text[start:end])

        if current_start is None:
            current_start = start
            current_end = end
            current_words = count
            continue

        if current_words + count > max_words:
            boundaries.append((current_start, current_end))
            current_start = start
            current_end = end
            current_words = count
        else:
            current_end = end
            current_words += count

            if current_words >= target_words:
                boundaries.append((current_start, current_end))
                current_start = None
                current_end = None
                current_words = 0

    if current_start is not None:
        boundaries.append((current_start, current_end))

    section_hash = hashlib.sha256(
        text.encode("utf-8")
    ).hexdigest()

    chunks = []

    for index, (start, end) in enumerate(boundaries):
        chunk_text = text[start:end]

        identity = (
            f"{section['ticker']}|"
            f"{section['accession']}|"
            f"{section['item']}|"
            f"{section_hash}|"
            f"{start}|{end}"
        )

        chunk_id = hashlib.sha256(
            identity.encode("utf-8")
        ).hexdigest()[:24]

        chunks.append(
            {
                "chunk_id": chunk_id,
                "ticker": section["ticker"],
                "cik": section["cik"],
                "accession": section["accession"],
                "filing_date": section["filing_date"],
                "report_date": section["report_date"],
                "form": section["form"],
                "item": section["item"],
                "source_url": section["source_url"],
                "chunk_index": index,
                "start_char": start,
                "end_char": end,
                "text": chunk_text,
                "words": word_count(chunk_text),
                "section_sha256": section_hash,
            }
        )

    return chunks


def process_ticker(ticker: str) -> tuple[Path, int]:
    files = sorted((SECTIONS_DIR / ticker).glob("*/sections.parquet"))

    if not files:
        raise FileNotFoundError(
            f"No stored filing sections for {ticker}"
        )

    all_chunks = []

    for path in files:
        sections = pq.read_table(path).to_pylist()

        for section in sections:
            all_chunks.extend(create_chunks(section))

    if not all_chunks:
        raise ValueError("No chunks produced")

    output_dir = CHUNKS_DIR / ticker
    output_dir.mkdir(parents=True, exist_ok=True)

    output_path = output_dir / "chunks.parquet"
    table = pa.Table.from_pylist(all_chunks, schema=SCHEMA)

    temp_path = None

    try:
        with tempfile.NamedTemporaryFile(
            dir=output_dir,
            prefix=".chunks_",
            suffix=".parquet",
            delete=False,
        ) as temp:
            temp_path = Path(temp.name)

        pq.write_table(
            table,
            temp_path,
            compression="zstd",
        )

        verified = pq.read_table(temp_path)

        if verified.num_rows != len(all_chunks):
            raise ValueError("Chunk verification failed")

        os.replace(temp_path, output_path)

    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)

    return output_path, len(all_chunks)


def main():
    parser = argparse.ArgumentParser(
        description="Chunk stored SEC filing sections"
    )
    parser.add_argument("ticker")
    args = parser.parse_args()

    path, count = process_ticker(args.ticker.upper())

    print(f"\n=== {args.ticker.upper()} CHUNKING ===")
    print(f"Chunks: {count}")
    print(f"Saved: {path}")
    print("PASS: Filing chunks stored as Parquet")


if __name__ == "__main__":
    main()
