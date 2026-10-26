
from dataclasses import dataclass

from src.ai.analyst import AnalysisResult


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
    Build a user-facing response.

    Governed financial evidence takes precedence over
    unverified AI-generated financial text.

    Financial questions without valid Gold evidence
    fail closed, even if the model skipped the tool.
    """

    if result.financial_evidence:
        if not result.financial_summary:
            raise ValueError(
                "Financial evidence exists but no verified "
                "financial summary was generated."
            )

        return UserResponse(
            text=result.financial_summary,
            financial_verified=True,
        )

    if (
        result.financial_tool_attempted
        or result.financial_evidence_required
    ):
        return UserResponse(
            text=UNAVAILABLE_MESSAGE,
            financial_verified=False,
        )

    return UserResponse(
        text=result.answer,
        financial_verified=False,
    )
