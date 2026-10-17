
import pytest

from src.transformation.parse_filings import (
    RAW_DIR,
    parse_filing,
)


@pytest.mark.parametrize(
    "ticker,expected_method",
    [
        ("MSFT", "direct"),
        ("JPM", "referenced"),
        ("CAT", "direct"),
    ],
)
def test_real_filing_extraction(ticker, expected_method):
    if not list((RAW_DIR / ticker).glob("*/*.html")):
        pytest.skip(f"No local snapshot for {ticker}")

    sections = parse_filing(ticker)

    assert len(sections) == 2
    assert {s["item"] for s in sections} == {"1A", "7"}

    for section in sections:
        assert section["characters"] > 500
        assert section["words"] > 100
        assert section["source_url"]
        assert section["accession"]

    mda = next(s for s in sections if s["item"] == "7")

    assert mda["extraction_method"] == expected_method

    if ticker == "JPM":
        assert "The following is Management" in mda["text"]
        assert "FORWARD-LOOKING STATEMENTS" in mda["text"]
        assert (
            "Management’s report on internal control"
            not in mda["text"]
        )
