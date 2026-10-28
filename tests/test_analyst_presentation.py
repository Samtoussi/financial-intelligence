from unittest.mock import patch
import pytest

from src.ai.response_builder import format_risk_claims
from src.ai.risk_evidence import RiskClaim
from src.ui import analyst
from src.ui.analyst import present_answer, progressive_chunks


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


@pytest.mark.parametrize("present", [False, True])
def test_avatar_uses_optional_local_file(tmp_path, monkeypatch, present):
    avatar = tmp_path / "avatar.png"
    monkeypatch.setattr(analyst, "ANALYST_AVATAR", str(avatar))
    if present:
        avatar.touch()
    assert analyst.get_analyst_avatar() == (str(avatar) if present else ":material/smart_toy:")


@pytest.mark.parametrize("present", [False, True])
@pytest.mark.parametrize("fails", [False, True])
def test_loading_uses_optional_html_or_spinner_and_cleans_up(tmp_path, monkeypatch, present, fails):
    animation = tmp_path / "thinking.html"
    monkeypatch.setattr(analyst, "THINKING_ART", animation)
    if present:
        animation.write_text("<span>Test loading indicator</span>", encoding="utf-8")
    with patch.object(analyst.st, "empty") as empty, patch.object(analyst.st, "spinner") as spinner:
        def run():
            with analyst.analyst_loading():
                if fails:
                    raise RuntimeError("Analysis failed")
        if fails:
            with pytest.raises(RuntimeError, match="Analysis failed"):
                run()
        else:
            run()
        if present:
            empty.return_value.html.assert_called_once_with(animation)
            empty.return_value.empty.assert_called_once()
            spinner.assert_not_called()
        else:
            empty.assert_not_called()
            spinner.assert_called_once_with("Analyzing financial data and SEC filings…")
            spinner.return_value.__enter__.assert_called_once()
            spinner.return_value.__exit__.assert_called_once()
