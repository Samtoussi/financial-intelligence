
import pytest
from bs4 import BeautifulSoup

from src.transformation.parse_filings import (
    extract_section,
    find_heading,
    is_mda_reference,
    normalize,
    parse_html,
)


def make_html(body: str) -> BeautifulSoup:
    return parse_html(
        f"<html><body>{body}</body></html>".encode()
    )


def test_normalize_whitespace():
    assert normalize("Hello \n  financial\t world") == (
        "Hello financial world"
    )


def test_direct_section_extraction():
    soup = make_html(
        "<div>Item 1A. Risk Factors</div>"
        "<p>" + "Financial risk disclosure. " * 40 + "</p>"
        "<div>Item 1B. Unresolved Staff Comments</div>"
    )

    start = find_heading(soup, "1A")
    end = find_heading(soup, "1B")
    text = extract_section(soup, start, end)

    assert text.startswith("Item 1A. Risk Factors")
    assert "Financial risk disclosure" in text
    assert "Item 1B" not in text


def test_referenced_mda_detection():
    reference = (
        "Item 7. Management’s Discussion and Analysis. "
        "Management’s discussion and analysis appears on "
        "pages 46–160."
    )

    assert is_mda_reference(reference)


def test_direct_mda_not_mistaken_for_reference():
    direct = (
        "Item 7. Management’s Discussion and Analysis. "
        "Our financial performance improved significantly "
        "during the fiscal year."
    )

    assert not is_mda_reference(direct)


def test_ambiguous_heading_rejected():
    soup = make_html(
        "<div>Item 1A. Risk Factors</div>"
        "<div>Item 1A. Additional Risk Factors</div>"
    )

    with pytest.raises(ValueError, match="Ambiguous"):
        find_heading(soup, "1A")


def test_invalid_section_boundaries_rejected():
    soup = make_html(
        "<div>Item 1B. Unresolved Staff Comments</div>"
        "<div>Item 1A. Risk Factors</div>"
    )

    with pytest.raises(ValueError, match="Invalid section boundaries"):
        extract_section(
            soup,
            find_heading(soup, "1A"),
            find_heading(soup, "1B"),
        )


def test_short_section_rejected():
    soup = make_html(
        "<div>Item 1A. Risk Factors</div>"
        "<p>Short disclosure.</p>"
        "<div>Item 1B. Unresolved Staff Comments</div>"
    )

    with pytest.raises(ValueError, match="unexpectedly short"):
        extract_section(
            soup,
            find_heading(soup, "1A"),
            find_heading(soup, "1B"),
        )


def test_hidden_xbrl_removed():
    soup = make_html(
        "<ix:header>"
        "<ix:hidden>Secret XBRL metadata</ix:hidden>"
        "</ix:header>"
        "<p>Visible financial disclosure</p>"
    )

    text = soup.get_text(" ", strip=True)

    assert "Secret XBRL metadata" not in text
    assert "Visible financial disclosure" in text
