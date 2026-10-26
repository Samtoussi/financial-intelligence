
from dataclasses import dataclass

from src.ai.analyst import AnalysisResult


@dataclass
class UserResponse:
    text: str
    financial_verified: bool


def build_user_response(result: AnalysisResult) -> UserResponse:
    """
    Build a user-facing response.

    Financial evidence takes precedence over unverified
    AI-generated text.
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

    return UserResponse(
        text=result.answer,
        financial_verified=False,
    )
