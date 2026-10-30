"""Bounded M002 evidence selection from independently parsed filing sections.

This module never reads evaluation fixtures. Offsets address stored section text;
the source hash addresses the original HTML bytes, not the normalized text.
"""
import hashlib
import re

from src.transformation.chunk_filings import create_chunks

REPORT = {
    "ticker": "MSFT", "cik": 789019, "form": "10-Q",
    "accession": "0001193125-26-436133", "fiscal_period": "FY2027 Q1",
    "period_start": "2026-07-01", "period_end": "2026-09-30",
    "prior_start": "2025-07-01", "prior_end": "2025-09-30",
    "filing_date": "2026-10-28", "document": "msft-20260930.htm",
    "source_url": "https://www.sec.gov/Archives/edgar/data/789019/000119312526436133/msft-20260930.htm",
}
METRICS = {
    "revenue": ("Total revenue", "USD millions", "GAAP"),
    "operating_income": ("Operating income", "USD millions", "GAAP"),
    "net_income": ("Net income", "USD millions", "GAAP"),
    "diluted_eps": ("Diluted", "USD per share", "GAAP"),
    "agents_and_infra_revenue": ("Agents and Infra", "USD millions", "GAAP segment disclosure"),
    "devices_and_consumer_revenue": ("Devices and Consumer", "USD millions", "GAAP segment disclosure"),
}
NOTE_IDS = ("gaap_vs_non_gaap", "recast_segment_comparability", "azure_growth_vs_cloud_margin")


def _position(text, pattern, start=0):
    match = re.search(pattern, text[start:], re.I)
    if match is None:
        raise ValueError(f"Required filing evidence missing: {pattern}")
    return start + match.start()


def build_report_evidence(sections: list[dict], metadata: dict) -> list[dict]:
    for key in ("ticker", "cik", "form", "accession", "report_date", "filing_date", "source_url"):
        expected = REPORT["period_end"] if key == "report_date" else REPORT[key]
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
            "ticker", "cik", "form", "accession", "report_date", "source_url",
        )):
            raise ValueError("Section belongs to another filing")
    financial = by_item["I.1"]["text"]
    commentary = by_item["I.2"]["text"]
    segment_start = _position(financial, r"Segment revenue, cost of revenue, operating expenses")
    recast_start = _position(financial, r"Recast of Certain Prior Period Information")
    summary_start = _position(commentary, r"(?:FINANCI\s*AL\s+SUMMARY|SUMMARY RESULTS OF OPERATIONS)")
    windows = [
        ("income_statement", "I.1", 0,
         _position(financial, r"Refer to accompanying notes") + len("Refer to accompanying notes.")),
        ("segment_table", "I.1", segment_start,
         _position(financial, r"No sales to an individual country", segment_start)),
        ("recast_disclosure", "I.1", recast_start,
         _position(financial, r"Estimates and Assumptions", recast_start)),
        ("management_summary", "I.2", summary_start,
         _position(commentary, r"\nOPERATING EXPENSES\n", summary_start)),
    ]
    chunks = {item: create_chunks(section) for item, section in by_item.items()}
    evidence = []
    for label, item, start, end in windows:
        section = by_item[item]
        text = section["text"][start:end]
        if not text.strip() or len(text) > 25000:
            raise ValueError(f"Invalid bounded evidence window: {label}")
        section_hash = hashlib.sha256(section["text"].encode("utf-8")).hexdigest()
        identity = f"{REPORT['accession']}|{item}|{section_hash}|{start}|{end}"
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
    for label, rows in (("income_statement", list(METRICS)[:4]),
                        ("segment_table", list(METRICS)[4:])):
        text = next(e["text"] for e in evidence if e["label"] == label)
        for term in ("2026", "2025", "millions", "September 30", *(METRICS[m][0] for m in rows)):
            if term.casefold() not in text.casefold():
                raise ValueError(f"Missing table context: {term}")
    return evidence
