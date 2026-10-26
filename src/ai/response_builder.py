
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


def build_user_response(result: AnalysisResult) -> UserResponse:
    """
    Compose governed financial metrics and SEC excerpts.

    Financial figures come exclusively from Gold.
    Document excerpts come from retrieved SEC passages.
    Unverified AI text is not mixed into governed answers.

    Preserve the existing financial-only response format.
    """

    financial_evidence = result.financial_evidence
    document_evidence = getattr(
        result,
        "document_evidence",
        [],
    )

    document_summary = format_document_summaries(
        document_evidence
    )

    if financial_evidence:
        if not result.financial_summary:
            raise ValueError(
                "Financial evidence exists but no verified "
                "financial summary was generated."
            )

        if document_summary:
            return UserResponse(
                text=(
                    "Financial performance\n\n"
                    + result.financial_summary
                    + "\n\n"
                    + document_summary
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

        if document_summary:
            parts.append(document_summary)

        return UserResponse(
            text="\n\n".join(parts),
            financial_verified=False,
        )

    if document_summary:
        return UserResponse(
            text=document_summary,
            financial_verified=False,
        )

    return UserResponse(
        text=result.answer,
        financial_verified=False,
    )
