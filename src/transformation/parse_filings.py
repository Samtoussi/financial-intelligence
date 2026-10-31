
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


def load_latest_snapshot(
    ticker: str, *, accession: str | None = None, form: str = "10-K",
    snapshot_path: Path | None = None,
) -> tuple[bytes, dict]:
    root = RAW_DIR / ticker

    if accession is not None and not re.fullmatch(r"\d{10}-\d{2}-\d{6}", accession):
        raise ValueError("Invalid accession")
    snapshots = sorted(
        ([Path(snapshot_path)] if snapshot_path is not None else
         root.glob(f"{accession or '*'}/*.html")),
        key=lambda path: path.stat().st_mtime_ns,
        reverse=True,
    )

    if not snapshots:
        raise FileNotFoundError(f"No filing snapshot for {ticker}")

    for path in snapshots:
        metadata_path = path.with_name(path.stem + ".metadata.json")
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if metadata.get("form") == form and (
            accession is None or metadata.get("accession") == accession
        ):
            break
    else:
        raise ValueError(f"No matching {form} snapshot for {ticker}, accession={accession}")

    payload = path.read_bytes()

    actual_hash = hashlib.sha256(payload).hexdigest()

    if actual_hash != metadata["sha256"]:
        raise ValueError(f"Snapshot checksum mismatch: {path}")

    if metadata["ticker"] != ticker:
        raise ValueError("Snapshot ticker mismatch")

    return payload, metadata


def quarterly_boundaries(soup: BeautifulSoup, *, cat_layout=False) -> list[Tag]:
    """Bounded Microsoft layout: resolve the three Part I TOC destinations.

    Following TOC links avoids repeated page headers and Part II item numbers.
    Ambiguous or changed layouts fail closed.
    """
    titles = (
        "financial statements",
        "management’s discussion and analysis of financial condition and results of operations",
        "quantitative and qualitative disclosures about market risk",
    )
    result = []
    for title in titles:
        def matches(a):
            label = normalized_heading(a.get_text(" ", strip=True)).replace("'", "’")
            if cat_layout:
                # Observed CAT TOC; the downloaded document contains U+FFFD here.
                label = label.replace('\ufffd', '’')
            return label == title
        links = [a for a in soup.find_all("a", href=True) if matches(a)]
        destinations = {a["href"][1:] for a in links if a["href"].startswith("#")}
        if len(destinations) != 1:
            raise ValueError(f"Ambiguous 10-Q boundary: {title}")
        target = destinations.pop()
        nodes = soup.find_all(id=target) or soup.find_all("a", attrs={"name": target})
        if len(nodes) != 1:
            raise ValueError(f"Missing or ambiguous 10-Q destination: {title}")
        result.append(nodes[0])
    return result


def quarterly_text(soup: BeautifulSoup, start: Tag, end: Tag) -> str:
    """Preserve table rows/cells alongside the surrounding labels and units."""
    nodes = list(soup.descendants)
    positions = {id(node): i for i, node in enumerate(nodes)}
    lo, hi = positions[id(start)], positions[id(end)]
    if lo >= hi:
        raise ValueError("Invalid 10-Q section boundaries")
    parts = []
    for node in nodes[lo:hi]:
        if isinstance(node, Tag):
            if node.name == "tr":
                parts.append("\n")
            elif node.name in {"td", "th"}:
                parts.append(" | ")
            elif node.name in {"p", "div", "br"} and node.find_parent("table") is None:
                parts.append("\n")
        elif isinstance(node, NavigableString) and str(node).strip():
            parts.append(normalize(str(node)) + " ")
    text = "\n".join(normalize(line) for line in "".join(parts).splitlines() if line.strip())
    if len(text) < 500:
        raise ValueError("10-Q section is unexpectedly short")
    return text


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


def parse_filing(
    ticker: str, *, accession: str | None = None, form: str = "10-K",
    snapshot_path: Path | None = None,
) -> list[dict]:
    payload, metadata = load_latest_snapshot(
        ticker, accession=accession, form=form, snapshot_path=snapshot_path,
    )
    soup = parse_html(payload)

    if form == "10-Q":
        if ticker not in {"MSFT", "CAT"}:
            raise ValueError("10-Q extraction currently supports MSFT and CAT only")
        starts = quarterly_boundaries(soup, cat_layout=ticker == 'CAT')
        records = []
        for i, item in enumerate(("I.1", "I.2")):
            text = quarterly_text(soup, starts[i], starts[i + 1])
            records.append({
                **{key: metadata[key] for key in (
                    "ticker", "cik", "accession", "filing_date", "report_date", "form", "source_url",
                )},
                "item": item, "extraction_method": "part_i_toc",
                "text": text, "characters": len(text), "words": len(text.split()),
            })
        return records
    if form != "10-K":
        raise ValueError("Unsupported filing form")

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
