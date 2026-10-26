
from unittest.mock import patch

from src.ai.analyst import (
    AnalysisResult,
    build_analysis_result,
)
from src.ai.response_builder import build_user_response
from src.ai.risk_evidence import RiskClaim


def sample_document():
    return {
        "ticker": "MSFT",
        "chunk_id": "msft-001",
        "item": "1A",
        "source_url": "https://www.sec.gov/msft",
        "text": "Geopolitical instability may affect operations.",
    }


def sample_claim():
    return RiskClaim(
        ticker="MSFT",
        explanation=(
            "Geopolitical instability may affect operations."
        ),
        chunk_id="msft-001",
        source_url="https://www.sec.gov/msft",
    )


@patch("src.ai.analyst.generate_risk_claims")
def test_analysis_collects_risk_claims(mock_generator):
    mock_generator.return_value = [sample_claim()]

    result = build_analysis_result(
        answer="AI answer",
        financial_evidence=[],
        document_evidence=[sample_document()],
        financial_tool_attempted=False,
        financial_evidence_required=False,
    )

    assert len(result.risk_claims) == 1
    assert result.risk_claims[0].ticker == "MSFT"
    mock_generator.assert_called_once()


@patch("src.ai.analyst.generate_risk_claims")
def test_risk_generation_failure_preserves_result(mock_generator):
    mock_generator.side_effect = RuntimeError("API timeout")

    result = build_analysis_result(
        answer="AI answer",
        financial_evidence=[],
        document_evidence=[sample_document()],
        financial_tool_attempted=False,
        financial_evidence_required=False,
    )

    assert result.risk_claims == []
    assert result.document_evidence == [sample_document()]


def test_response_contains_risk_explanation():
    result = AnalysisResult(
        answer="Unverified AI answer",
        financial_evidence=[],
        document_evidence=[sample_document()],
        risk_claims=[sample_claim()],
    )

    response = build_user_response(result)

    assert "SEC risk analysis" in response.text
    assert "Geopolitical instability" in response.text
    assert "Chunk: msft-001" in response.text
    assert "https://www.sec.gov/msft" in response.text
    assert "Unverified AI answer" not in response.text


def test_no_risk_claims_does_not_dump_document():
    result = AnalysisResult(
        answer="AI interpretation",
        financial_evidence=[],
        document_evidence=[sample_document()],
        risk_claims=[],
        risk_generation_attempted=True,
    )

    response = build_user_response(result)

    assert "No source-linked risk explanations" in response.text
    assert "Source excerpt:" not in response.text


def test_financial_summary_combined_with_risk():
    result = AnalysisResult(
        answer="AI invented $999 billion.",
        financial_evidence=[
            {"ticker": "MSFT", "fiscal_year": 2025}
        ],
        financial_summary="Microsoft revenue: $281.724B",
        document_evidence=[sample_document()],
        risk_claims=[sample_claim()],
    )

    response = build_user_response(result)

    assert response.financial_verified is True
    assert "Microsoft revenue: $281.724B" in response.text
    assert "SEC risk analysis" in response.text
    assert "$999 billion" not in response.text
