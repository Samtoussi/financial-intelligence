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


def format_risk_claims(claims: list, document_evidence: list[dict] | None = None) -> str:
    if not claims:
        return ""

    evidence_index = {
        (item.get("ticker"), item.get("chunk_id"), item.get("source_url")): item
        for item in (document_evidence or [])
    }
    sections = []

    for claim in claims:
        passage = evidence_index.get(
            (claim.ticker, claim.chunk_id, claim.source_url), {}
        )
        metadata = passage.get("filing_metadata")
        lines = [claim.ticker, claim.explanation]

        if metadata and metadata.get("accession") == passage.get("accession"):
            lines.extend([
                f"Filing: {metadata['form']} · reporting period ending {metadata['report_date']}",
                f"Filed: {metadata['filing_date']}",
                f"Accession: {metadata['accession']}",
            ])

        lines.extend([
            f"Chunk: {claim.chunk_id}",
            f"Source: {claim.source_url}",
        ])
        sections.append("\n".join(lines))

    return "SEC risk analysis\n\n" + "\n\n".join(sections)


def build_user_response(result: AnalysisResult) -> UserResponse:
    """Compose Gold-backed metrics and source-linked SEC risk evidence."""
    financial_evidence = result.financial_evidence
    document_evidence = getattr(result, "document_evidence", [])
    risk_claims = getattr(result, "risk_claims", [])
    risk_generation_attempted = getattr(result, "risk_generation_attempted", False)

    risk_summary = format_risk_claims(risk_claims, document_evidence)

    if risk_summary:
        qualitative_section = risk_summary
    elif risk_generation_attempted and document_evidence:
        qualitative_section = INSUFFICIENT_RISK_MESSAGE
    else:
        qualitative_section = format_document_summaries(document_evidence)

    if financial_evidence:
        if not result.financial_summary:
            raise ValueError(
                "Financial evidence exists but no verified "
                "financial summary was generated."
            )
        if qualitative_section:
            return UserResponse(
                text="Financial performance\n\n" + result.financial_summary + "\n\n" + qualitative_section,
                financial_verified=True,
            )
        return UserResponse(text=result.financial_summary, financial_verified=True)

    if (
        getattr(result, "financial_tool_attempted", False)
        or getattr(result, "financial_evidence_required", False)
    ):
        parts = [UNAVAILABLE_MESSAGE]
        if qualitative_section:
            parts.append(qualitative_section)
        return UserResponse(text="\n\n".join(parts), financial_verified=False)

    if qualitative_section:
        return UserResponse(text=qualitative_section, financial_verified=False)

    return UserResponse(text=result.answer, financial_verified=False)
