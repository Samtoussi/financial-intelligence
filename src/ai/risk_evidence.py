
from dataclasses import dataclass


@dataclass(frozen=True)
class RiskClaim:
    ticker: str
    explanation: str
    chunk_id: str
    source_url: str


def validate_risk_claims(
    claims: list[dict],
    document_evidence: list[dict],
) -> list[RiskClaim]:
    """
    Validate AI-generated risk claims against retrieved SEC evidence.

    A valid claim must:
    - Have a non-empty explanation.
    - Reference an existing ticker and chunk ID.
    - Use the source URL from the retrieved evidence.

    This validates provenance, not semantic correctness.
    """

    evidence_index = {}

    for item in document_evidence:
        if not isinstance(item, dict):
            continue

        ticker = item.get("ticker")
        chunk_id = item.get("chunk_id")
        source_url = item.get("source_url")
        text = item.get("text")

        if not all(
            isinstance(value, str) and value.strip()
            for value in (ticker, chunk_id, source_url, text)
        ):
            continue

        evidence_index[(ticker, chunk_id)] = source_url

    validated = []

    for claim in claims:
        if not isinstance(claim, dict):
            continue

        ticker = claim.get("ticker")
        explanation = claim.get("explanation")
        chunk_id = claim.get("chunk_id")
        source_url = claim.get("source_url")

        if not all(
            isinstance(value, str) and value.strip()
            for value in (
                ticker,
                explanation,
                chunk_id,
                source_url,
            )
        ):
            continue

        expected_url = evidence_index.get((ticker, chunk_id))

        if expected_url is None:
            continue

        if source_url != expected_url:
            continue

        validated.append(
            RiskClaim(
                ticker=ticker,
                explanation=explanation.strip(),
                chunk_id=chunk_id,
                source_url=expected_url,
            )
        )

    return validated
