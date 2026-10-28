from unittest.mock import patch
import hashlib

from PIL import Image

from src.ai.response_builder import format_risk_claims
from src.ai.risk_evidence import RiskClaim
from src.ui.analyst import ANALYST_AVATAR, ASSETS, present_answer, progressive_chunks


def test_risk_presentation_preserves_claims_and_source_mapping():
    url = "https://www.sec.gov/Archives/edgar/data/789019/filing.htm"
    claims = [RiskClaim("MSFT", "Service disruptions may affect customer retention.", "chunk-1", url),
              RiskClaim("MSFT", "Competition may affect demand.", "chunk-2", url)]
    evidence = [dict(ticker="MSFT", chunk_id=claim.chunk_id, source_url=url,
                     accession="accession-2025", filing_metadata=dict(
                         accession="accession-2025", form="10-K",
                         report_date="2025-06-30", filing_date="2025-07-30"))
                for claim in claims]
    original = format_risk_claims(claims, evidence)
    body, details = present_answer(original)
    assert details
    for claim in claims:
        assert claim.explanation in body
        assert claim.chunk_id not in body
    assert "accession-2025" not in body
    assert "2025-06-30" in body
    assert body.count(f"[SEC filing 1]({url})") == 2
    assert "not direct quotations" in body
    assert "does not quantify future growth" in body


def test_financial_values_and_noncomparable_text_are_not_rewritten():
    answer = ("Microsoft (MSFT), 2025\nRevenue: $110.000B\n"
              "YoY growth: unavailable or non-comparable\n"
              "Reporting period: 2024-07-01 to 2025-06-30\n"
              "Source: RevenueConcept, SEC accession accession-2025 (filed 2025-07-30)")
    body, details = present_answer(answer)
    assert details
    assert "#### Financial performance" in body
    assert "$110.000B" in body
    assert "unavailable or non-comparable" in body
    assert "2024-07-01 to 2025-06-30" in body
    assert "RevenueConcept" not in body
    assert "accession-2025" not in body


def test_unknown_prose_errors_and_existing_links_are_preserved():
    text = "Analysis unavailable.\n\nSee [SEC](https://www.sec.gov/)."
    body, details = present_answer(text)
    assert body == text
    assert not details


def test_progressive_chunks_preserve_text_and_atomic_citations():
    text = "#### Revenue\n\n" + "A business explanation. " * 100
    link = "[SEC filing 1](https://www.sec.gov/filing.htm)"
    text += link
    with patch("src.ui.analyst.pause") as sleep:
        chunks = list(progressive_chunks(text))
    assert "".join(chunks) == text
    assert 1 < len(chunks) <= 60
    assert any(link in chunk for chunk in chunks)
    assert sleep.call_count <= 60


def test_animation_is_self_contained_and_respects_reduced_motion():
    html = (ASSETS / "valentin_thinking.html").read_text(encoding="utf-8")
    assert "@keyframes fi-valentin-particle" in html
    assert "prefers-reduced-motion:reduce" in html
    assert "<script" not in html
    assert "http" not in html
    assert "data-testid" not in html
    assert "<svg" not in html  # Streamlit's HTML sanitizer removes inline SVG.
    assert html.count('<span class="fi-particle') == 37
    assert 'role="status"' in html
    assert (ASSETS / "valentin_logo.png").read_bytes().startswith(b"\x89PNG")
    assert "width:26px; height:26px" in html
    assert "gap:8px; min-height:26px" in html


def test_avatar_has_transparency_and_original_logo_is_unchanged():
    assert ANALYST_AVATAR == str(ASSETS / "valentin_avatar.png")
    with Image.open(ANALYST_AVATAR) as image:
        assert image.mode == "RGBA"
        alpha = image.getchannel("A")
        assert alpha.getextrema() == (0, 255)
        assert image.getpixel((0, 0))[3] == 0
        assert sum(alpha.histogram()[1:255]) > 0  # Soft edges/glow, not a binary cutout.
    assert hashlib.sha256((ASSETS / "valentin_logo.png").read_bytes()).hexdigest() == (
        "a2731bdd611cabe73a5b7fbb63c738339cec8dd8433f435e7359d4cbd2c75a04"
    )
