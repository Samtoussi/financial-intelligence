
from dataclasses import dataclass

from src.ai.analyst import analyze
from src.ai.response_builder import build_user_response
from src.analytics.financials import COMPANIES


@dataclass(frozen=True)
class DashboardContext:
    ticker: str
    fiscal_year: int

    def __post_init__(self):
        if self.ticker not in COMPANIES:
            raise ValueError("Unsupported dashboard ticker")

        if (
            type(self.fiscal_year) is not int
            or not 2000 <= self.fiscal_year <= 2030
        ):
            raise ValueError("Invalid dashboard fiscal year")


def build_contextual_question(
    question: str,
    context: DashboardContext,
) -> str:
    """
    Supply dashboard selection as fallback context.

    Explicit companies and years in the user's question
    must take precedence over dashboard selection.
    """
    if not question.strip():
        raise ValueError("Question cannot be empty")

    return (
        "Dashboard context:\n"
        f"- Selected company: {context.ticker}\n"
        f"- Selected fiscal year: {context.fiscal_year}\n\n"
        "Instructions:\n"
        "- Use dashboard context only when the user's question "
        "does not explicitly specify a company or fiscal year.\n"
        "- An explicitly named company overrides the selected company.\n"
        "- An explicitly named year overrides the selected fiscal year.\n"
        "- For SEC risks, distinguish the selected fiscal year "
        "from the actual filing period of retrieved documents.\n\n"
        f"User question:\n{question}"
    )


def answer_dashboard_question(
    question: str,
    context: DashboardContext | None = None,
) -> str:
    """
    Run the existing analyst and return its governed response.

    Dashboard context is optional to preserve existing callers.
    """
    effective_question = (
        build_contextual_question(question, context)
        if context is not None
        else question
    )

    result = analyze(effective_question)
    response = build_user_response(result)

    return response.text
