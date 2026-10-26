
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


@patch("src.ai.analyst.OpenAI")
@patch("src.ai.analyst.execute_tool")
def test_collects_multiple_financial_results(mock_tool, mock_openai):
    microsoft = {
        "ticker": "MSFT",
        "fiscal_year": 2025,
        "revenue_usd": 281724000000,
    }
    caterpillar = {
        "ticker": "CAT",
        "fiscal_year": 2025,
        "revenue_usd": 67589000000,
    }

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


@patch("src.ai.analyst.OpenAI")
@patch("src.ai.analyst.execute_tool")
def test_document_search_not_collected(mock_tool, mock_openai):
    mock_tool.return_value = [
        {
            "ticker": "MSFT",
            "chunk_id": "abc",
            "text": "Risk factors",
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

    assert result.financial_evidence == []


@patch("src.ai.analyst.analyze")
def test_existing_interface_preserved(mock_analyze):
    mock_analyze.return_value = SimpleNamespace(
        answer="Original answer",
        financial_evidence=[],
    )

    assert ask_analyst("Question") == "Original answer"
