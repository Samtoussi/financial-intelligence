
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.ai.analyst import ask_analyst


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


@patch("src.ai.analyst.OpenAI")
@patch("src.ai.analyst.execute_tool")
def test_successful_tool_flow(mock_tool, mock_openai):
    mock_tool.return_value = {
        "ticker": "MSFT",
        "revenue_usd": 281724000000,
    }

    first = make_response(
        output=[make_tool_call()],
    )

    second = make_response(
        output_text="Microsoft revenue was $281.724 billion.",
        response_id="response_2",
    )

    client = MagicMock()
    client.responses.create.side_effect = [first, second]
    mock_openai.return_value = client

    result = ask_analyst("What was Microsoft's revenue?")

    assert result == "Microsoft revenue was $281.724 billion."
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
