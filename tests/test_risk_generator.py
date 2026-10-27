
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.ai.risk_generator import generate_risk_claims


def sample_evidence():
    return [
        {
            "ticker": "MSFT",
            "chunk_id": "msft-001",
            "item": "1A",
            "source_url": "https://www.sec.gov/msft",
            "text": (
                "Geopolitical instability may disrupt "
                "operations and access to markets."
            ),
        }
    ]


def make_client(payload, status="completed"):
    client = MagicMock()
    client.responses.create.return_value = SimpleNamespace(
        status=status,
        output_text=json.dumps(payload),
    )
    return client


def test_generates_valid_risk_claim():
    client = make_client({
        "claims": [
            {
                "ticker": "MSFT",
                "explanation": (
                    "Geopolitical instability may disrupt "
                    "operations and market access."
                ),
                "chunk_id": "msft-001",
                "source_url": "https://www.sec.gov/msft",
            }
        ]
    })

    result = generate_risk_claims(
        sample_evidence(),
        client=client,
    )

    assert len(result) == 1
    assert result[0].ticker == "MSFT"
    assert result[0].chunk_id == "msft-001"

    request = client.responses.create.call_args.kwargs

    assert request["text"]["format"]["strict"] is True


def test_rejects_invented_source():
    client = make_client({
        "claims": [
            {
                "ticker": "MSFT",
                "explanation": "Invented explanation.",
                "chunk_id": "fake-chunk",
                "source_url": "https://www.sec.gov/msft",
            }
        ]
    })

    result = generate_risk_claims(
        sample_evidence(),
        client=client,
    )

    assert result == []


def test_no_supported_risks():
    client = make_client({"claims": []})

    result = generate_risk_claims(
        sample_evidence(),
        client=client,
    )

    assert result == []


def test_empty_evidence_skips_api():
    client = MagicMock()

    result = generate_risk_claims(
        [],
        client=client,
    )

    assert result == []
    client.responses.create.assert_not_called()


def test_incomplete_response_rejected():
    client = make_client(
        {"claims": []},
        status="incomplete",
    )

    with pytest.raises(
        RuntimeError,
        match="Risk generation incomplete",
    ):
        generate_risk_claims(
            sample_evidence(),
            client=client,
        )


def test_invalid_json_rejected():
    client = MagicMock()
    client.responses.create.return_value = SimpleNamespace(
        status="completed",
        output_text="not json",
    )

    with pytest.raises(
        ValueError,
        match="invalid JSON",
    ):
        generate_risk_claims(
            sample_evidence(),
            client=client,
        )


def test_invalid_structure_rejected():
    client = make_client({"claims": "invalid"})

    with pytest.raises(
        ValueError,
        match="invalid claims",
    ):
        generate_risk_claims(
            sample_evidence(),
            client=client,
        )


@patch("src.ai.risk_generator.OpenAI")
def test_default_client_configuration(mock_openai):
    client = make_client({"claims": []})
    mock_openai.return_value = client

    result = generate_risk_claims(sample_evidence())

    assert result == []
    mock_openai.assert_called_once_with(
        timeout=90.0,
        max_retries=0,
    )


def test_question_is_passed_to_risk_generator():
    client = make_client({"claims": []})

    generate_risk_claims(
        sample_evidence(),
        client=client,
        question="What are Microsoft's cybersecurity risks?",
    )

    request = client.responses.create.call_args.kwargs
    payload = json.loads(request["input"])

    assert payload["question"] == (
        "What are Microsoft's cybersecurity risks?"
    )
    assert payload["evidence"] == sample_evidence()


def test_instructions_require_question_relevance():
    client = make_client({"claims": []})

    generate_risk_claims(
        sample_evidence(),
        client=client,
        question="What are the cybersecurity risks?",
    )

    request = client.responses.create.call_args.kwargs

    assert "directly relevant" in request["instructions"]
    assert "Omit excerpts" in request["instructions"]
