
import pytest

from src.ai.analyst import AnalysisResult
from src.ai.response_builder import build_user_response


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
