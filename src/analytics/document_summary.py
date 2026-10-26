
def format_document_summaries(
    evidence: list[dict],
) -> str:
    """
    Format retrieved SEC filing passages with source references.

    Passages are presented as source excerpts, not as
    independently verified analytical conclusions.
    """
    if not evidence:
        return ""

    sections = []
    seen = set()

    for item in evidence:
        if not isinstance(item, dict):
            continue

        ticker = item.get("ticker")
        chunk_id = item.get("chunk_id")
        source_url = item.get("source_url")
        text = item.get("text")
        filing_item = item.get("item", "Unknown section")

        if not all(
            isinstance(value, str) and value.strip()
            for value in (
                ticker,
                chunk_id,
                source_url,
                text,
            )
        ):
            continue

        key = (ticker, chunk_id)

        if key in seen:
            continue

        seen.add(key)

        excerpt = " ".join(text.split())

        sections.append(
            f"{ticker} — {filing_item}\n"
            f"Source excerpt: {excerpt}\n"
            f"Chunk: {chunk_id}\n"
            f"Source: {source_url}"
        )

    if not sections:
        return ""

    return (
        "SEC filing excerpts\n\n"
        + "\n\n".join(sections)
    )
