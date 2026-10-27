
from unittest.mock import Mock

import pytest

from src.ai import dashboard
from src.ai.dashboard import (
    DashboardContext,
    build_contextual_question,
)


def test_dashboard_uses_governed_response(monkeypatch):
    question = "What was Microsoft's revenue in FY2025?"

    raw_result = Mock()
    raw_result.answer = "UNVERIFIED MODEL ANSWER"

    governed_response = Mock()
    governed_response.text = (
        "Microsoft (MSFT), 2025\n"
        "Revenue: $281.724B\n"
        "YoY growth: +14.93%"
    )

    mock_analyze = Mock(return_value=raw_result)
    mock_builder = Mock(return_value=governed_response)

    monkeypatch.setattr(dashboard, "analyze", mock_analyze)
    monkeypatch.setattr(
        dashboard,
        "build_user_response",
        mock_builder,
    )

    answer = dashboard.answer_dashboard_question(question)

    mock_analyze.assert_called_once_with(question)
    mock_builder.assert_called_once_with(raw_result)

    assert answer == governed_response.text
    assert "UNVERIFIED MODEL ANSWER" not in answer


def test_dashboard_propagates_analysis_errors(monkeypatch):
    mock_analyze = Mock(
        side_effect=RuntimeError("Analysis unavailable")
    )
    mock_builder = Mock()

    monkeypatch.setattr(dashboard, "analyze", mock_analyze)
    monkeypatch.setattr(
        dashboard,
        "build_user_response",
        mock_builder,
    )

    with pytest.raises(RuntimeError, match="Analysis unavailable"):
        dashboard.answer_dashboard_question("Test question")

    mock_builder.assert_not_called()


def test_contextual_question_includes_dashboard_selection():
    context = DashboardContext(
        ticker="MSFT",
        fiscal_year=2026,
    )

    question = build_contextual_question(
        "How much did revenue grow?",
        context,
    )

    assert "Selected company: MSFT" in question
    assert "Selected fiscal year: 2026" in question
    assert "How much did revenue grow?" in question


def test_contextual_question_preserves_explicit_request():
    context = DashboardContext(
        ticker="MSFT",
        fiscal_year=2026,
    )

    question = build_contextual_question(
        "What was JPM's revenue in 2025?",
        context,
    )

    assert "What was JPM's revenue in 2025?" in question
    assert "explicitly named company overrides" in question
    assert "explicitly named year overrides" in question


@pytest.mark.parametrize(
    "ticker, year",
    [
        ("AAPL", 2025),
        ("MSFT", "2025"),
        ("MSFT", True),
        ("MSFT", 2035),
    ],
)
def test_invalid_dashboard_context(ticker, year):
    with pytest.raises(ValueError):
        DashboardContext(ticker=ticker, fiscal_year=year)


def test_contextual_dashboard_uses_governed_response(monkeypatch):
    raw_result = Mock()
    governed_response = Mock(text="Verified Gold result")

    mock_analyze = Mock(return_value=raw_result)
    mock_builder = Mock(return_value=governed_response)

    monkeypatch.setattr(dashboard, "analyze", mock_analyze)
    monkeypatch.setattr(
        dashboard,
        "build_user_response",
        mock_builder,
    )

    context = DashboardContext(
        ticker="CAT",
        fiscal_year=2025,
    )

    answer = dashboard.answer_dashboard_question(
        "How much did revenue grow?",
        context,
    )

    assert answer == "Verified Gold result"

    sent_question = mock_analyze.call_args.args[0]

    assert "Selected company: CAT" in sent_question
    assert "Selected fiscal year: 2025" in sent_question
    assert "How much did revenue grow?" in sent_question

    mock_builder.assert_called_once_with(raw_result)


def test_empty_contextual_question():
    context = DashboardContext(
        ticker="MSFT",
        fiscal_year=2026,
    )

    with pytest.raises(ValueError, match="Question cannot be empty"):
        build_contextual_question("   ", context)
