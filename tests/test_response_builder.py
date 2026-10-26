
import pytest

from src.ai.analyst import AnalysisResult
from src.ai.response_builder import build_user_response
from src.ai.financial_intent import requires_financial_evidence


def test_financial_evidence_overrides_ai_answer():
    result = AnalysisResult(
        answer="Microsoft grew 99%, according to the AI.",
        financial_evidence=[
            {
                "ticker": "MSFT",
                "fiscal_year": 2025,
                "revenue_usd": 281724000000,
            }
        ],
        financial_summary=(
            "Microsoft (MSFT), 2025\n"
            "Revenue: $281.724B\n"
            "YoY growth: +14.93%"
        ),
    )

    response = build_user_response(result)

    assert response.financial_verified is True
    assert "14.93%" in response.text
    assert "99%" not in response.text
    assert response.text == result.financial_summary


def test_qualitative_answer_remains_unverified():
    result = AnalysisResult(
        answer="Microsoft discusses cybersecurity risks.",
        financial_evidence=[],
        financial_summary="",
    )

    response = build_user_response(result)

    assert response.text == result.answer
    assert response.financial_verified is False


def test_missing_summary_fails_closed():
    result = AnalysisResult(
        answer="Revenue grew by 99%.",
        financial_evidence=[
            {
                "ticker": "MSFT",
                "fiscal_year": 2025,
            }
        ],
        financial_summary="",
    )

    with pytest.raises(ValueError):
        build_user_response(result)


def test_empty_result_is_unverified():
    result = AnalysisResult(
        answer="",
        financial_evidence=[],
        financial_summary="",
    )

    response = build_user_response(result)

    assert response.text == ""
    assert response.financial_verified is False


def test_multiple_financial_results():
    summary = (
        "Microsoft (MSFT), 2025\n"
        "Revenue: $281.724B\n\n"
        "Caterpillar (CAT), 2025\n"
        "Revenue: $67.589B"
    )

    result = AnalysisResult(
        answer="AI-generated comparison.",
        financial_evidence=[
            {"ticker": "MSFT", "fiscal_year": 2025},
            {"ticker": "CAT", "fiscal_year": 2025},
        ],
        financial_summary=summary,
    )

    response = build_user_response(result)

    assert response.financial_verified is True
    assert response.text == summary
    assert "AI-generated comparison" not in response.text


def test_failed_financial_lookup_does_not_use_ai_answer():
    result = AnalysisResult(
        answer="Microsoft revenue was $999 billion.",
        financial_evidence=[],
        financial_summary="",
        financial_tool_attempted=True,
    )

    response = build_user_response(result)

    assert response.financial_verified is False
    assert "$999 billion" not in response.text
    assert "unavailable" in response.text


def test_no_financial_lookup_preserves_qualitative_answer():
    result = AnalysisResult(
        answer="Microsoft discusses cybersecurity risks.",
        financial_evidence=[],
        financial_summary="",
        financial_tool_attempted=False,
    )

    response = build_user_response(result)

    assert response.text == result.answer
    assert response.financial_verified is False


def test_failed_lookup_with_empty_ai_answer():
    result = AnalysisResult(
        answer="",
        financial_evidence=[],
        financial_summary="",
        financial_tool_attempted=True,
    )

    response = build_user_response(result)

    assert response.financial_verified is False
    assert "unavailable" in response.text


def test_successful_financial_lookup_takes_precedence():
    result = AnalysisResult(
        answer="Incorrect AI revenue: $999 billion.",
        financial_evidence=[
            {"ticker": "MSFT", "fiscal_year": 2025}
        ],
        financial_summary="Microsoft revenue: $281.724B",
        financial_tool_attempted=True,
    )

    response = build_user_response(result)

    assert response.financial_verified is True
    assert response.text == "Microsoft revenue: $281.724B"
    assert "$999 billion" not in response.text


def test_financial_question_without_tool_call_is_blocked():
    result = AnalysisResult(
        answer="Microsoft revenue was $999 billion.",
        financial_evidence=[],
        financial_summary="",
        financial_tool_attempted=False,
        financial_evidence_required=True,
    )

    response = build_user_response(result)

    assert response.financial_verified is False
    assert "$999 billion" not in response.text
    assert "unavailable" in response.text


def test_financial_intent_detection():
    assert requires_financial_evidence(
        "What was Microsoft's revenue in 2025?"
    )
    assert requires_financial_evidence(
        "Compare revenue growth for MSFT and CAT"
    )
    assert requires_financial_evidence(
        "Show annual sales for JPM"
    )


def test_qualitative_intent_detection():
    assert not requires_financial_evidence(
        "What cybersecurity risks does Microsoft discuss?"
    )
    assert not requires_financial_evidence(
        "Summarize Caterpillar's business strategy"
    )
