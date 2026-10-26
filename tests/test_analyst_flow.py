
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.ai.analyst import analyze, ask_analyst


def make_response(
    *,
    status="completed",
    output=None,
    output_text="",
    response_id="response_1",
    incomplete_details=None,
):
    return SimpleNamespace(
        id=response_id,
        status=status,
        output=output if output is not None else [],
        output_text=output_text,
        incomplete_details=incomplete_details,
        usage=None,
    )


def make_tool_call():
    return SimpleNamespace(
        type="function_call",
        name="get_annual_financials",
        arguments='{"ticker":"MSFT","fiscal_year":2025}',
        call_id="call_1",
    )


def make_financial_result():
    return {
        "ticker": "MSFT",
        "cik": 789019,
        "fiscal_year": 2025,
        "period_start": "2024-07-01",
        "period_end": "2025-06-30",
        "revenue_usd": 281724000000,
        "previous_year_revenue_usd": 245122000000,
        "yoy_growth_pct": 14.93,
        "is_comparable": True,
        "source_concept": (
            "RevenueFromContractWithCustomerExcludingAssessedTax"
        ),
        "source_accession": "0001193125-26-323660",
        "source_filed_date": "2026-07-29",
    }


@patch("src.ai.analyst.OpenAI")
@patch("src.ai.analyst.execute_tool")
def test_successful_tool_flow(mock_tool, mock_openai):
    mock_tool.return_value = make_financial_result()

    first = make_response(
        output=[make_tool_call()],
    )

    second = make_response(
        output_text="Microsoft revenue was $999 billion.",
        response_id="response_2",
    )

    client = MagicMock()
    client.responses.create.side_effect = [first, second]
    mock_openai.return_value = client

    result = ask_analyst("What was Microsoft's revenue?")

    assert "Microsoft (MSFT), 2025" in result
    assert "Revenue: $281.724B" in result
    assert "YoY growth: +14.93%" in result
    assert "$999 billion" not in result

    assert client.responses.create.call_count == 2

    mock_tool.assert_called_once_with(
        "get_annual_financials",
        '{"ticker":"MSFT","fiscal_year":2025}',
    )

    second_request = client.responses.create.call_args_list[1].kwargs

    assert second_request["previous_response_id"] == "response_1"
    assert second_request["input"][0]["type"] == "function_call_output"
    assert second_request["input"][0]["call_id"] == "call_1"


@patch("src.ai.analyst.OpenAI")
@patch("src.ai.analyst.execute_tool")
def test_failed_financial_lookup_blocks_ai_answer(
    mock_tool,
    mock_openai,
):
    mock_tool.return_value = None

    first = make_response(
        output=[make_tool_call()],
    )

    second = make_response(
        output_text="Microsoft revenue was $999 billion.",
        response_id="response_2",
    )

    client = MagicMock()
    client.responses.create.side_effect = [first, second]
    mock_openai.return_value = client

    result = ask_analyst("What was Microsoft's revenue?")

    assert "unavailable" in result
    assert "$999 billion" not in result
    assert client.responses.create.call_count == 2


@patch("src.ai.analyst.OpenAI")
@patch("src.ai.analyst.execute_tool")
def test_failed_financial_lookup_sets_attempt_flag(
    mock_tool,
    mock_openai,
):
    mock_tool.side_effect = ValueError("Invalid fiscal year")

    first = make_response(
        output=[make_tool_call()],
    )

    second = make_response(
        output_text="Financial data unavailable.",
        response_id="response_2",
    )

    client = MagicMock()
    client.responses.create.side_effect = [first, second]
    mock_openai.return_value = client

    result = analyze("What was Microsoft's revenue?")

    assert result.financial_tool_attempted is True
    assert result.financial_evidence == []
    assert result.financial_summary == ""
    assert client.responses.create.call_count == 2


@patch("src.ai.analyst.OpenAI")
def test_incomplete_response_rejected(mock_openai):
    client = MagicMock()
    client.responses.create.return_value = make_response(
        status="incomplete",
        incomplete_details=SimpleNamespace(
            reason="max_output_tokens",
        ),
    )
    mock_openai.return_value = client

    with pytest.raises(
        RuntimeError,
        match="Model response incomplete",
    ):
        ask_analyst("Analyze Microsoft")


@patch("src.ai.analyst.OpenAI")
def test_empty_answer_rejected(mock_openai):
    client = MagicMock()
    client.responses.create.return_value = make_response(
        output_text="",
    )
    mock_openai.return_value = client

    with pytest.raises(
        RuntimeError,
        match="Model returned no answer",
    ):
        ask_analyst("Analyze Microsoft")


@patch("src.ai.analyst.OpenAI")
@patch("src.ai.analyst.execute_tool")
def test_max_tool_rounds(mock_tool, mock_openai):
    mock_tool.return_value = None

    client = MagicMock()
    client.responses.create.side_effect = [
        make_response(
            output=[make_tool_call()],
            response_id=f"response_{i}",
        )
        for i in range(1, 5)
    ]

    mock_openai.return_value = client

    with pytest.raises(
        RuntimeError,
        match="Maximum tool rounds reached",
    ):
        ask_analyst("Analyze Microsoft")

    assert client.responses.create.call_count == 4


def test_empty_question_rejected():
    with pytest.raises(
        ValueError,
        match="Question cannot be empty",
    ):
        ask_analyst("   ")


@patch("src.ai.analyst.OpenAI")
@patch("src.ai.analyst.execute_tool")
def test_final_answer_after_three_tool_rounds(
    mock_tool,
    mock_openai,
):
    mock_tool.return_value = None

    client = MagicMock()
    client.responses.create.side_effect = [
        make_response(
            output=[make_tool_call()],
            response_id=f"response_{i}",
        )
        for i in range(1, 4)
    ] + [
        make_response(
            output_text="Final answer.",
            response_id="response_4",
        )
    ]

    mock_openai.return_value = client

    result = ask_analyst("Analyze Microsoft")

    assert "unavailable" in result
    assert client.responses.create.call_count == 4

    final_request = client.responses.create.call_args_list[-1].kwargs

    assert final_request["tool_choice"] == "none"
    assert final_request["previous_response_id"] == "response_3"
