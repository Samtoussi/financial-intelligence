
from src.ai.analyst import analyze
from src.ai.response_builder import build_user_response


def answer_dashboard_question(question: str) -> str:
    """
    Run the existing AI analyst and return its governed response.

    Never expose the raw model answer directly to the dashboard.
    """
    result = analyze(question)
    response = build_user_response(result)

    return response.text
