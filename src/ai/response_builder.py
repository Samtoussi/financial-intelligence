
from dataclasses import dataclass

from src.ai.analyst import AnalysisResult
from src.analytics.document_summary import format_document_summaries


@dataclass
class UserResponse:
    text: str
    financial_verified: bool


UNAVAILABLE_MESSAGE = (
    "Verified financial data is unavailable for "
    "this request. No financial figures are provided."
)

INSUFFICIENT_RISK_MESSAGE = (
    "No source-linked risk explanations are available "
    "from the retrieved SEC excerpts."
)

RISK_GENERATION_ERROR_MESSAGE = (
    "SEC excerpts were retrieved, but the AI risk analysis "
    "could not be completed. Please try again."
)


def format_risk_claims(
    claims: list,
    document_evidence: list[dict] | None = None,
) -> str:
    """Group risk claims by filing while preserving individual sources."""
    if not claims:
        return ""

    evidence_index = {
        (
            item.get("ticker"),
            item.get("chunk_id"),
            item.get("source_url"),
        ): item
        for item in (document_evidence or [])
    }

    groups = {}

    for claim in claims:
        passage = evidence_index.get(
            (claim.ticker, claim.chunk_id, claim.source_url),
            {},
        )

        metadata = passage.get("filing_metadata")

        if not (
            isinstance(metadata, dict)
            and metadata.get("accession")
            and metadata.get("accession") == passage.get("accession")
            and all(
                metadata.get(field)
                for field in ("form", "report_date", "filing_date")
            )
        ):
            metadata = None

        if metadata:
            group_key = (
                claim.ticker,
                metadata["accession"],
            )
        else:
            group_key = (
                claim.ticker,
                passage.get("accession"),
                claim.source_url,
            )

        if group_key not in groups:
            groups[group_key] = {
                "ticker": claim.ticker,
                "metadata": metadata,
                "claims": [],
            }

        groups[group_key]["claims"].append(claim)

    sections = ["SEC risk analysis"]

    for group in groups.values():
        lines = [group["ticker"]]
        metadata = group["metadata"]

        if metadata:
            lines.extend([
                (
                    f"Filing: {metadata['form']} · "
                    f"reporting period ending {metadata['report_date']}"
                ),
                f"Filed: {metadata['filing_date']}",
                f"Accession: {metadata['accession']}",
            ])

        for index, claim in enumerate(group["claims"], start=1):
            lines.extend([
                "",
                f"{index}. {claim.explanation}",
                f"Chunk: {claim.chunk_id}",
                f"Source: {claim.source_url}",
            ])

        sections.append("\n".join(lines))

    return "\n\n".join(sections)


def build_user_response(result: AnalysisResult) -> UserResponse:
    """Compose verified financials and source-linked SEC evidence."""
    financial_evidence = result.financial_evidence
    document_evidence = getattr(result, "document_evidence", [])
    risk_claims = getattr(result, "risk_claims", [])
    risk_generation_attempted = getattr(
        result, "risk_generation_attempted", False
    )
    risk_generation_failed = getattr(
        result, "risk_generation_failed", False
    )

    risk_summary = format_risk_claims(
        risk_claims,
        document_evidence,
    )

    if risk_generation_failed:
        qualitative_section = RISK_GENERATION_ERROR_MESSAGE
    elif risk_summary:
        qualitative_section = risk_summary
    elif risk_generation_attempted and document_evidence:
        qualitative_section = INSUFFICIENT_RISK_MESSAGE
    else:
        qualitative_section = format_document_summaries(
            document_evidence
        )

    if financial_evidence:
        if not result.financial_summary:
            raise ValueError(
                "Financial evidence exists but no verified "
                "financial summary was generated."
            )

        if qualitative_section:
            return UserResponse(
                text=(
                    "Financial performance\n\n"
                    + result.financial_summary
                    + "\n\n"
                    + qualitative_section
                ),
                financial_verified=True,
            )

        return UserResponse(
            text=result.financial_summary,
            financial_verified=True,
        )

    if (
        getattr(result, "financial_tool_attempted", False)
        or getattr(result, "financial_evidence_required", False)
    ):
        parts = [UNAVAILABLE_MESSAGE]

        if qualitative_section:
            parts.append(qualitative_section)

        return UserResponse(
            text="\n\n".join(parts),
            financial_verified=False,
        )

    if qualitative_section:
        return UserResponse(
            text=qualitative_section,
            financial_verified=False,
        )

    return UserResponse(
        text=result.answer,
        financial_verified=False,
    )
