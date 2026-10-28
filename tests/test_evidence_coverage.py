"""Request coverage tests use controlled model/tool responses, never live APIs."""
import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from streamlit.testing.v1 import AppTest

from src.ai import analyst, dashboard
from src.ai.dashboard import DashboardContext
from src.ai.financial_intent import requires_filing_evidence
from src.ai.response_builder import (
    INSUFFICIENT_RISK_MESSAGE, MISSING_RISK_EVIDENCE_MESSAGE, build_user_response,
)
from src.ai.risk_evidence import RiskClaim


QUESTION = "What were the key risks Microsoft disclosed in its FY2026 10-K, and how could they affect its future growth?"
DOCUMENT = dict(
    ticker="MSFT", chunk_id="test-chunk", item="1A", accession="test-accession",
    source_url="https://www.sec.gov/test-filing.htm",
    text="Competition may affect demand.",
    filing_metadata=dict(ticker="MSFT", accession="test-accession", form="10-K",
                         report_date="2026-06-30", filing_date="2026-07-29"),
)
CLAIM = RiskClaim("MSFT", DOCUMENT["text"], DOCUMENT["chunk_id"], DOCUMENT["source_url"])
FINANCIAL = dict(
    ticker="MSFT", fiscal_year=2026, revenue_usd=331839000000, yoy_growth_pct=17.79,
    is_comparable=True, period_start="2025-07-01", period_end="2026-06-30",
    source_concept="RevenueConcept", source_accession="test-accession", source_filed_date="2026-07-29",
)


def response(calls=(), text="Unverified model answer", ident="response-1"):
    return SimpleNamespace(id=ident, status="completed", output=list(calls), output_text=text)


def tool(name, **arguments):
    return SimpleNamespace(type="function_call", name=name,
                           arguments=json.dumps(arguments), call_id=name)


@pytest.fixture
def backend(monkeypatch):
    client = Mock()
    client.responses.create.return_value = response()
    monkeypatch.setattr(analyst, "OpenAI", Mock(return_value=client))
    search = Mock(return_value=[DOCUMENT])
    monkeypatch.setattr(analyst, "search_filings", search)
    monkeypatch.setattr(analyst, "get_filing_metadata", Mock(return_value=DOCUMENT["filing_metadata"]))
    monkeypatch.setattr(analyst, "get_annual_financials", Mock(return_value=FINANCIAL))
    generator = Mock(return_value=[CLAIM])
    monkeypatch.setattr(analyst, "generate_risk_claims", generator)
    return client, search, generator


def test_skipped_search_is_performed_without_another_routing_call(backend):
    client, search, generator = backend
    result = analyst.analyze(QUESTION)
    search.assert_called_once_with(query="risk factors", ticker="MSFT", limit=3)
    assert client.responses.create.call_count == 1
    assert result.filing_evidence_required and result.filing_search_attempted
    assert not result.financial_evidence_required
    assert result.document_evidence[0]["filing_metadata"]["report_date"] == "2026-06-30"
    generator.assert_called_once_with(result.document_evidence, question=QUESTION)
    assert result.risk_claims == [CLAIM]


def test_zero_match_model_search_is_not_retried_or_hidden(backend):
    client, search, generator = backend
    search.return_value = []
    client.responses.create.side_effect = [response([
        tool("search_filings", query="FY2026 10-K", ticker="MSFT", limit=3)
    ]), response()]
    result = analyst.analyze(QUESTION)
    assert result.filing_search_attempted
    assert search.call_count == 1
    generator.assert_not_called()
    text = build_user_response(result).text
    assert MISSING_RISK_EVIDENCE_MESSAGE in text
    assert "Unverified model answer" not in text


def test_supported_model_search_preserves_claims_and_citations(backend):
    client, search, _ = backend
    client.responses.create.side_effect = [response([
        tool("search_filings", query="competition", ticker="MSFT", limit=3)
    ]), response()]
    text = build_user_response(analyst.analyze(QUESTION)).text
    search.assert_called_once_with(query="competition", ticker="MSFT", limit=3)
    assert CLAIM.explanation in text
    assert CLAIM.source_url in text
    assert "2026-06-30" in text
    assert MISSING_RISK_EVIDENCE_MESSAGE not in text


@pytest.mark.parametrize("available", [False, True])
def test_combined_question_preserves_financials_with_risks_or_warning(backend, available):
    client, search, generator = backend
    search.return_value = [DOCUMENT] if available else []
    client.responses.create.side_effect = [response([
        tool("get_annual_financials", ticker="MSFT", fiscal_year=2026)
    ]), response()]
    result = analyst.analyze("Show Microsoft revenue and the risks in its FY2026 10-K.")
    assert result.financial_evidence_required and result.filing_evidence_required
    text = build_user_response(result).text
    assert "$331.839B" in text and "+17.79%" in text
    assert "Reporting period: 2025-07-01 to 2026-06-30" in text
    assert (CLAIM.explanation if available else MISSING_RISK_EVIDENCE_MESSAGE) in text
    assert generator.call_count == int(available)


def test_financial_question_does_not_inherit_filing_intent_from_context(backend):
    client, search, generator = backend
    client.responses.create.side_effect = [response([
        tool("get_annual_financials", ticker="MSFT", fiscal_year=2026)
    ]), response()]
    text = dashboard.answer_dashboard_question("What was revenue?", DashboardContext("MSFT", 2026))
    assert "$331.839B" in text
    search.assert_not_called()
    generator.assert_not_called()


def test_risk_generation_retains_selected_year_context(backend):
    _, _, generator = backend
    dashboard.answer_dashboard_question("Explain its risks.", DashboardContext("MSFT", 2026))
    question = generator.call_args.kwargs["question"]
    assert "Selected fiscal year: 2026" in question
    assert "Selected company: MSFT" in question
    assert "User question:\nExplain its risks." in question


@pytest.mark.parametrize("question, expected", [
    ("Explain its risks.", "CAT"),
    (QUESTION, "MSFT"),
    ("Explain JPMorgan's risk factors.", "JPM"),
])
def test_original_company_name_overrides_dashboard_selection(backend, question, expected):
    _, search, _ = backend
    search.return_value = []
    text = dashboard.answer_dashboard_question(question, DashboardContext("CAT", 2026))
    assert MISSING_RISK_EVIDENCE_MESSAGE in text
    search.assert_called_once_with(query="risk factors", ticker=expected, limit=3)


@pytest.mark.parametrize("failure", [FileNotFoundError("No local filings"), RuntimeError("Search unavailable")])
@pytest.mark.parametrize("model_search", [False, True])
def test_retrieval_failure_preserves_financial_context(backend, failure, model_search):
    client, search, generator = backend
    search.side_effect = failure
    calls = [tool("get_annual_financials", ticker="MSFT", fiscal_year=2026)]
    if model_search:
        calls.append(tool("search_filings", query="risks", ticker="MSFT", limit=3))
    client.responses.create.side_effect = [response(calls), response()]
    result = analyst.analyze("Show Microsoft revenue and risks.")
    assert result.filing_search_attempted and search.call_count == 1
    generator.assert_not_called()
    text = build_user_response(result).text
    assert "$331.839B" in text and MISSING_RISK_EVIDENCE_MESSAGE in text


def test_insufficient_claims_do_not_fall_back_to_model_prose(backend):
    _, _, generator = backend
    generator.return_value = []
    text = build_user_response(analyst.analyze(QUESTION)).text
    assert INSUFFICIENT_RISK_MESSAGE in text
    assert "Unverified model answer" not in text


def test_unresolved_company_reports_missing_evidence_without_guessing(backend):
    _, search, _ = backend
    text = build_user_response(analyst.analyze("Explain the filing risks.")).text
    search.assert_not_called()
    assert MISSING_RISK_EVIDENCE_MESSAGE in text


@pytest.mark.parametrize("question, required", [
    (QUESTION, True), ("Summarize Microsoft's annual report.", True),
    ("What was Microsoft's revenue?", False), ("Explain Microsoft's business strategy.", False),
])
def test_narrow_filing_intent(question, required):
    assert requires_filing_evidence(question) is required


@pytest.mark.parametrize("available", [False, True])
def test_risks_or_missing_warning_render_in_main_answer(backend, available):
    _, search, _ = backend
    search.return_value = [DOCUMENT] if available else []
    answer = dashboard.answer_dashboard_question(QUESTION, DashboardContext("MSFT", 2026))
    app = AppTest.from_string(
        "import streamlit as st\nfrom src.ui.analyst import render_answer\n"
        "render_answer(st.session_state.answer, progressive=True)", default_timeout=15,
    )
    app.session_state.answer = answer
    with patch("src.ui.analyst.pause"):
        app.run()
    assert not app.exception
    visible = app.markdown[0].value
    assert (CLAIM.explanation if available else MISSING_RISK_EVIDENCE_MESSAGE) in visible
    if available:
        assert f"[SEC filing 1]({CLAIM.source_url})" in visible
        assert not app.expander[0].markdown
