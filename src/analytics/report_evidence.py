"""Bounded two-profile evidence selection from independently parsed filing sections.

This module never reads evaluation fixtures. Offsets address stored section text;
the source hash addresses the original HTML bytes, not the normalized text.
"""
import hashlib
import re

from src.transformation.chunk_filings import create_chunks

from src.analytics.report_profiles import DEFAULT_PROFILE, REPORT, METRICS, NOTE_IDS, get_profile, table_context


def _position(text, pattern, start=0):
    match = re.search(pattern, text[start:], re.I)
    if match is None:
        raise ValueError(f"Required filing evidence missing: {pattern}")
    return start + match.start()


def build_report_evidence(sections: list[dict], metadata: dict, *, profile=DEFAULT_PROFILE) -> list[dict]:
    config = get_profile(profile)
    report, metrics = config["report"], config["metrics"]
    for key in ("ticker", "cik", "form", "accession", "report_date", "filing_date", "source_url"):
        expected = report["period_end"] if key == "report_date" else report[key]
        if metadata.get(key) != expected:
            raise ValueError(f"Pinned source mismatch: {key}")
    source_hash = metadata.get("sha256", "")
    if not re.fullmatch(r"[0-9a-f]{64}", source_hash):
        raise ValueError("Missing source SHA-256")
    by_item = {s["item"]: s for s in sections}
    if len(sections) != 2 or set(by_item) != {"I.1", "I.2"}:
        raise ValueError("Missing quarterly sections")
    for section in sections:
        if any(section.get(key) != metadata[key] for key in (
            "ticker", "cik", "form", "accession", "report_date", "filing_date", "source_url",
        )):
            raise ValueError("Section belongs to another filing")
    windows = []
    for label, item, start_pattern, end_pattern, include_end in config["boundaries"]:
        text = by_item[item]["text"]
        start = _position(text, start_pattern) if start_pattern else 0
        end = _position(text, end_pattern, start)
        if include_end:
            end += len("Refer to accompanying notes.")
        if end <= start:
            raise ValueError(f"Invalid evidence boundaries: {label}")
        windows.append((label, item, start, end))
    chunks = {item: create_chunks(section) for item, section in by_item.items()}
    evidence = []
    for label, item, start, end in windows:
        section = by_item[item]
        text = section["text"][start:end]
        if not text.strip() or len(text) > 25000:
            raise ValueError(f"Invalid bounded evidence window: {label}")
        section_hash = hashlib.sha256(section["text"].encode("utf-8")).hexdigest()
        identity = f"{report['accession']}|{item}|{section_hash}|{start}|{end}"
        evidence.append({
            "evidence_id": hashlib.sha256(identity.encode()).hexdigest()[:24],
            "label": label, "ticker": metadata["ticker"], "form": metadata["form"],
            "accession": metadata["accession"], "source_url": metadata["source_url"],
            "source_sha256": source_hash, "section_sha256": section_hash,
            "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "item": item, "start_char": start, "end_char": end,
            "chunk_ids": [c["chunk_id"] for c in chunks[item]
                          if c["start_char"] < end and c["end_char"] > start],
            "text": text,
        })
    # Require the metric labels, column periods and units in their own table context.
    for label, rows in (("income_statement", list(metrics)[:4]),
                        ("segment_table", list(metrics)[4:])):
        text = next(e["text"] for e in evidence if e["label"] == label)
        header = text.split("Revenue")[0].split("Total revenue")[0]
        if re.findall(r"(?<!\d)(?:19|20)\d{2}(?!\d)", header) != list(table_context(config)[1:3]):
            raise ValueError("Invalid table period columns")
        for term in (*table_context(config), *(metrics[m][0] for m in rows)):
            if term.casefold() not in text.casefold():
                raise ValueError(f"Missing table context: {term}")
    return evidence
