
from unittest.mock import Mock

from src.ai import dashboard


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

    monkeypatch.setattr(
        dashboard,
        "analyze",
        mock_analyze,
    )
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

    monkeypatch.setattr(
        dashboard,
        "analyze",
        mock_analyze,
    )
    monkeypatch.setattr(
        dashboard,
        "build_user_response",
        mock_builder,
    )

    try:
        dashboard.answer_dashboard_question("Test question")
    except RuntimeError as exc:
        assert str(exc) == "Analysis unavailable"
    else:
        raise AssertionError("Expected RuntimeError")

    mock_builder.assert_not_called()
