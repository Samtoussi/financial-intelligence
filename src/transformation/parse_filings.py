
import argparse
import hashlib
import json
import re
import warnings
from pathlib import Path

from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
from bs4.element import NavigableString, Tag

from src.ingestion.companyfacts import COMPANIES


RAW_DIR = Path("data/raw/sec/filings")
TARGET_ITEMS = ("1A", "7")

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def normalized_heading(text: str) -> str:
    text = normalize(text).casefold()
    text = text.replace("’", "'").replace("‘", "'")
    return text.rstrip(".: ")


def load_latest_snapshot(ticker: str) -> tuple[bytes, dict]:
    root = RAW_DIR / ticker

    snapshots = sorted(
        root.glob("*/*.html"),
        key=lambda path: path.stat().st_mtime_ns,
        reverse=True,
    )

    if not snapshots:
        raise FileNotFoundError(f"No filing snapshot for {ticker}")

    path = snapshots[0]
    metadata_path = path.with_name(
        path.name.removesuffix(".html") + ".metadata.json"
    )

    payload = path.read_bytes()
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))

    actual_hash = hashlib.sha256(payload).hexdigest()

    if actual_hash != metadata["sha256"]:
        raise ValueError(f"Snapshot checksum mismatch: {path}")

    if metadata["ticker"] != ticker:
        raise ValueError("Snapshot ticker mismatch")

    return payload, metadata


def parse_html(payload: bytes) -> BeautifulSoup:
    soup = BeautifulSoup(payload, "lxml")

    for tag in soup.find_all(
        ["script", "style", "ix:header", "ix:hidden", "head", "noscript"]
    ):
        tag.decompose()

    return soup


def heading_candidates(soup: BeautifulSoup, item: str) -> list[Tag]:
    pattern = re.compile(
        rf"^ITEM\s+{re.escape(item)}\.\s+\S",
        re.IGNORECASE,
    )

    candidates = []

    for element in soup.find_all(["p", "div", "h1", "h2", "h3"]):
        text = normalize(element.get_text(" ", strip=True))

        if len(text) > 200 or not pattern.match(text):
            continue

        if any(parent in candidates for parent in element.parents):
            continue

        candidates.append(element)

    return candidates


def find_heading(soup: BeautifulSoup, item: str) -> Tag:
    anchor_pattern = re.compile(
        rf"^item[_-]{re.escape(item.lower())}(?:[_-]|$)",
        re.IGNORECASE,
    )

    anchors = [
        tag
        for tag in soup.find_all(id=True)
        if anchor_pattern.match(tag.get("id", ""))
    ]

    if len(anchors) == 1:
        return anchors[0]

    candidates = heading_candidates(soup, item)

    if len(candidates) != 1:
        raise ValueError(
            f"Ambiguous Item {item}: "
            f"{len(anchors)} anchors, {len(candidates)} headings"
        )

    return candidates[0]


def extract_section(
    soup: BeautifulSoup,
    start: Tag,
    end: Tag,
    minimum_characters: int = 500,
) -> str:
    nodes = list(soup.descendants)

    positions = {
        id(node): index
        for index, node in enumerate(nodes)
    }

    start_index = positions[id(start)]
    end_index = positions[id(end)]

    if start_index >= end_index:
        raise ValueError("Invalid section boundaries")

    parts = [
        str(node).strip()
        for node in nodes[start_index:end_index]
        if isinstance(node, NavigableString) and str(node).strip()
    ]

    text = normalize(" ".join(parts))

    if len(text) < minimum_characters:
        raise ValueError(
            f"Extracted section is unexpectedly short: {len(text)} characters"
        )

    return text


def is_mda_reference(text: str) -> bool:
    normalized = normalized_heading(text)

    return (
        len(text) < 2000
        and "management's discussion and analysis" in normalized
        and (
            "appears on pages" in normalized
            or "appears on page" in normalized
            or "incorporated by reference" in normalized
        )
    )


def find_exact_heading(
    soup: BeautifulSoup,
    heading: str,
    after: Tag,
    before: Tag | None = None,
) -> Tag:
    nodes = list(soup.descendants)
    positions = {
        id(node): index
        for index, node in enumerate(nodes)
    }

    after_position = positions[id(after)]
    before_position = (
        positions[id(before)]
        if before is not None
        else len(nodes)
    )

    target = normalized_heading(heading)
    candidates = []

    for element in soup.find_all(["div", "p", "h1", "h2", "h3"]):
        position = positions[id(element)]

        if not after_position < position < before_position:
            continue

        text = normalized_heading(element.get_text(" ", strip=True))

        if text != target:
            continue

        # Avoid treating a container and its nested heading
        # as two independent matches.
        if any(
            normalized_heading(
                child.get_text(" ", strip=True)
            ) == target
            for child in element.find_all(
                ["div", "p", "h1", "h2", "h3"]
            )
        ):
            continue

        candidates.append(element)

    return candidates


def find_referenced_mda(soup: BeautifulSoup, item7: Tag) -> tuple[Tag, Tag]:
    item7a = find_heading(soup, "7A")

    starts = find_exact_heading(
        soup,
        "Management's discussion and analysis",
        after=item7a,
    )

    # A genuine MD&A introduction should immediately discuss
    # management's analysis, rather than being a page header.
    valid_starts = []

    for candidate in starts:
        nodes = list(soup.descendants)
        positions = {
            id(node): index
            for index, node in enumerate(nodes)
        }

        position = positions[id(candidate)]

        preview = normalize(
            " ".join(
                str(node).strip()
                for node in nodes[position:position + 150]
                if isinstance(node, NavigableString)
                and str(node).strip()
            )
        ).casefold()

        if (
            "the following is management" in preview
            and "financial condition" in preview
        ):
            valid_starts.append(candidate)

    if len(valid_starts) != 1:
        raise ValueError(
            "Could not uniquely identify referenced MD&A start: "
            f"{len(valid_starts)} candidates"
        )

    start = valid_starts[0]

    ends = find_exact_heading(
        soup,
        "Management's report on internal control over financial reporting",
        after=start,
    )

    if len(ends) != 1:
        raise ValueError(
            "Could not uniquely identify referenced MD&A end: "
            f"{len(ends)} candidates"
        )

    end = ends[0]

    # The boundary is validated against the actual document,
    # not a hardcoded DOM position.
    return start, end


def parse_filing(ticker: str) -> list[dict]:
    payload, metadata = load_latest_snapshot(ticker)
    soup = parse_html(payload)

    boundaries = {
        "1A": "1B",
        "7": "7A",
    }

    results = []

    for item in TARGET_ITEMS:
        start = find_heading(soup, item)
        end = find_heading(soup, boundaries[item])

        text = extract_section(
            soup,
            start,
            end,
            minimum_characters=1 if item == "7" else 500,
        )

        extraction_method = "direct"

        if item == "7" and is_mda_reference(text):
            referenced_start, referenced_end = find_referenced_mda(
                soup,
                start,
            )

            text = extract_section(
                soup,
                referenced_start,
                referenced_end,
            )

            extraction_method = "referenced"

        elif len(text) < 500:
            raise ValueError(
                f"Item {item} is unexpectedly short and "
                "no supported reference was identified"
            )

        results.append(
            {
                "ticker": ticker,
                "cik": metadata["cik"],
                "accession": metadata["accession"],
                "filing_date": metadata["filing_date"],
                "report_date": metadata["report_date"],
                "form": metadata["form"],
                "item": item,
                "source_url": metadata["source_url"],
                "extraction_method": extraction_method,
                "text": text,
                "characters": len(text),
                "words": len(text.split()),
            }
        )

    return results


def main():
    parser = argparse.ArgumentParser(
        description="Extract narrative sections from SEC 10-K filings"
    )

    parser.add_argument(
        "ticker",
        choices=sorted(COMPANIES),
    )

    args = parser.parse_args()
    sections = parse_filing(args.ticker)

    for section in sections:
        print(f"\n=== {section['ticker']} ITEM {section['item']} ===")
        print(f"Method: {section['extraction_method']}")
        print(f"Characters: {section['characters']:,}")
        print(f"Words: {section['words']:,}")
        print(f"Start: {section['text'][:250]}")
        print(f"End: {section['text'][-250:]}")

    print("\nPASS: Sections extracted from local snapshot")


if __name__ == "__main__":
    main()
