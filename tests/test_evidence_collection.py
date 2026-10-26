
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from src.ai.analyst import analyze, ask_analyst


def response(output=None, answer="", response_id="response_1"):
    return SimpleNamespace(
        id=response_id,
        status="completed",
        output=output or [],
        output_text=answer,
    )


def tool_call(name, arguments, call_id):
    return SimpleNamespace(
        type="function_call",
        name=name,
        arguments=arguments,
        call_id=call_id,
    )


def financial_result(
    ticker,
    revenue,
    growth,
    comparable=True,
):
    return {
        "ticker": ticker,
        "cik": 789019 if ticker == "MSFT" else 18230,
        "fiscal_year": 2025,
        "period_start": "2024-01-01",
        "period_end": "2025-12-31",
        "revenue_usd": revenue,
        "previous_year_revenue_usd": None,
        "yoy_growth_pct": growth,
        "is_comparable": comparable,
        "source_concept": (
            "RevenueFromContractWithCustomerExcludingAssessedTax"
        ),
        "source_accession": "test-accession",
        "source_filed_date": "2026-07-29",
    }


def document_result(ticker="MSFT", chunk_id="chunk-001"):
    return {
        "ticker": ticker,
        "chunk_id": chunk_id,
        "item": "Item 1A",
        "source_url": "https://www.sec.gov/example",
        "text": "Cybersecurity incidents may disrupt operations.",
    }


@patch("src.ai.analyst.OpenAI")
@patch("src.ai.analyst.execute_tool")
def test_collects_multiple_financial_results(mock_tool, mock_openai):
    microsoft = financial_result("MSFT", 281724000000, 14.93)
    caterpillar = financial_result("CAT", 67589000000, 4.29)

    mock_tool.side_effect = [microsoft, caterpillar]

    first = response(
        output=[
            tool_call(
                "get_annual_financials",
                '{"ticker":"MSFT","fiscal_year":2025}',
                "call_1",
            ),
            tool_call(
                "get_annual_financials",
                '{"ticker":"CAT","fiscal_year":2025}',
                "call_2",
            ),
        ]
    )
    second = response(answer="Comparison complete.")

    client = MagicMock()
    client.responses.create.side_effect = [first, second]
    mock_openai.return_value = client

    result = analyze("Compare Microsoft and Caterpillar")

    assert result.answer == "Comparison complete."
    assert result.financial_evidence == [microsoft, caterpillar]
    assert result.document_evidence == []
    assert "Microsoft (MSFT), 2025" in result.financial_summary
    assert "Caterpillar (CAT), 2025" in result.financial_summary
    assert "Revenue: $281.724B" in result.financial_summary
    assert "YoY growth: +14.93%" in result.financial_summary
    assert client.responses.create.call_count == 2


@patch("src.ai.analyst.OpenAI")
@patch("src.ai.analyst.execute_tool")
def test_missing_data_not_collected(mock_tool, mock_openai):
    mock_tool.return_value = None

    first = response(
        output=[
            tool_call(
                "get_annual_financials",
                '{"ticker":"MSFT","fiscal_year":2030}',
                "call_1",
            )
        ]
    )
    second = response(answer="Data unavailable.")

    client = MagicMock()
    client.responses.create.side_effect = [first, second]
    mock_openai.return_value = client

    result = analyze("Microsoft 2030")

    assert result.financial_evidence == []
    assert result.financial_summary == ""
    assert result.document_evidence == []


@patch("src.ai.analyst.OpenAI")
@patch("src.ai.analyst.execute_tool")
def test_failed_tool_not_collected(mock_tool, mock_openai):
    mock_tool.side_effect = ValueError("Invalid fiscal year")

    first = response(
        output=[
            tool_call(
                "get_annual_financials",
                '{"ticker":"MSFT","fiscal_year":9999}',
                "call_1",
            )
        ]
    )
    second = response(answer="Invalid request.")

    client = MagicMock()
    client.responses.create.side_effect = [first, second]
    mock_openai.return_value = client

    result = analyze("Microsoft 9999")

    assert result.financial_evidence == []
    assert result.financial_summary == ""
    assert result.document_evidence == []


@patch("src.ai.analyst.OpenAI")
@patch("src.ai.analyst.execute_tool")
def test_collects_document_evidence(mock_tool, mock_openai):
    passage = document_result()
    mock_tool.return_value = [passage]

    first = response(
        output=[
            tool_call(
                "search_filings",
                '{"query":"risk","ticker":"MSFT","limit":1}',
                "call_1",
            )
        ]
    )
    second = response(answer="Risk analysis.")

    client = MagicMock()
    client.responses.create.side_effect = [first, second]
    mock_openai.return_value = client

    result = analyze("Microsoft risks")

    assert result.financial_evidence == []
    assert result.financial_summary == ""
    assert result.document_evidence == [passage]
    assert result.document_evidence[0]["source_url"] == (
        "https://www.sec.gov/example"
    )


@patch("src.ai.analyst.OpenAI")
@patch("src.ai.analyst.execute_tool")
def test_rejects_incomplete_document_evidence(mock_tool, mock_openai):
    mock_tool.return_value = [
        {
            "ticker": "MSFT",
            "chunk_id": "chunk-001",
            "text": "Missing source URL.",
        }
    ]

    first = response(
        output=[
            tool_call(
                "search_filings",
                '{"query":"risk","ticker":"MSFT","limit":1}',
                "call_1",
            )
        ]
    )
    second = response(answer="Risk analysis.")

    client = MagicMock()
    client.responses.create.side_effect = [first, second]
    mock_openai.return_value = client

    result = analyze("Microsoft risks")

    assert result.document_evidence == []


@patch("src.ai.analyst.OpenAI")
@patch("src.ai.analyst.execute_tool")
def test_collects_financial_and_document_evidence(
    mock_tool,
    mock_openai,
):
    microsoft = financial_result("MSFT", 281724000000, 14.93)
    passage = document_result()

    mock_tool.side_effect = [microsoft, [passage]]

    first = response(
        output=[
            tool_call(
                "get_annual_financials",
                '{"ticker":"MSFT","fiscal_year":2025}',
                "call_1",
            ),
            tool_call(
                "search_filings",
                '{"query":"risk","ticker":"MSFT","limit":1}',
                "call_2",
            ),
        ]
    )
    second = response(answer="Financial and risk analysis.")

    client = MagicMock()
    client.responses.create.side_effect = [first, second]
    mock_openai.return_value = client

    result = analyze("Microsoft revenue and risks")

    assert result.financial_evidence == [microsoft]
    assert result.document_evidence == [passage]
    assert "Revenue: $281.724B" in result.financial_summary


@patch("src.ai.analyst.analyze")
def test_existing_interface_preserved(mock_analyze):
    mock_analyze.return_value = SimpleNamespace(
        answer="Revenue grew 99%.",
        financial_evidence=[
            {"ticker": "MSFT", "fiscal_year": 2025}
        ],
        financial_summary="Verified Gold growth: +14.93%",
    )

    assert (
        ask_analyst("What was Microsoft's revenue growth?")
        == "Verified Gold growth: +14.93%"
    )
