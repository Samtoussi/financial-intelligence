
from src.ai.analyst import AnalysisResult
from src.ai.response_builder import build_user_response


def document_result(ticker="MSFT", chunk_id="chunk-001"):
    return {
        "ticker": ticker,
        "chunk_id": chunk_id,
        "item": "Item 1A",
        "source_url": "https://www.sec.gov/example",
        "text": "Cybersecurity incidents may disrupt operations.",
    }


def test_combined_financial_and_document_response():
    result = AnalysisResult(
        answer="AI claims Microsoft grew 99%.",
        financial_evidence=[
            {"ticker": "MSFT", "fiscal_year": 2025}
        ],
        financial_summary=(
            "Microsoft (MSFT), 2025\n"
            "Revenue: $281.724B\n"
            "YoY growth: +14.93%"
        ),
        financial_evidence_required=True,
        document_evidence=[document_result()],
    )

    response = build_user_response(result)

    assert response.financial_verified is True
    assert "Financial performance" in response.text
    assert "Revenue: $281.724B" in response.text
    assert "YoY growth: +14.93%" in response.text
    assert "SEC filing excerpts" in response.text
    assert "Cybersecurity incidents" in response.text
    assert "Chunk: chunk-001" in response.text
    assert "99%" not in response.text


def test_qualitative_document_response():
    result = AnalysisResult(
        answer="Unsupported AI interpretation.",
        financial_evidence=[],
        document_evidence=[document_result()],
    )

    response = build_user_response(result)

    assert response.financial_verified is False
    assert "SEC filing excerpts" in response.text
    assert "Cybersecurity incidents" in response.text
    assert "Unsupported AI interpretation" not in response.text


def test_missing_financial_data_with_document_evidence():
    result = AnalysisResult(
        answer="Revenue was $999 billion.",
        financial_evidence=[],
        financial_tool_attempted=True,
        financial_evidence_required=True,
        document_evidence=[document_result()],
    )

    response = build_user_response(result)

    assert response.financial_verified is False
    assert "unavailable" in response.text
    assert "$999 billion" not in response.text
    assert "Cybersecurity incidents" in response.text


def test_missing_document_evidence_preserves_financial_summary():
    result = AnalysisResult(
        answer="Incorrect AI interpretation.",
        financial_evidence=[
            {"ticker": "MSFT", "fiscal_year": 2025}
        ],
        financial_summary="Microsoft revenue: $281.724B",
        document_evidence=[],
    )

    response = build_user_response(result)

    assert response.financial_verified is True
    assert "Microsoft revenue: $281.724B" in response.text
    assert "SEC filing excerpts" not in response.text


def test_empty_evidence_preserves_existing_behavior():
    result = AnalysisResult(
        answer="General explanation.",
        financial_evidence=[],
        document_evidence=[],
    )

    response = build_user_response(result)

    assert response.text == "General explanation."
    assert response.financial_verified is False
