import re


FINANCIAL_PATTERNS = (
    r"\brevenue\b",
    r"\brevenues\b",
    r"\brevenue growth\b",
    r"\bsales growth\b",
    r"\bannual sales\b",
    r"\bturnover\b",
    r"\byoy growth\b",
    r"\byear.over.year growth\b",
)


def requires_financial_evidence(question: str) -> bool:
    """
    Detect explicit requests for governed revenue metrics.

    This is intentionally narrow. It does not attempt to
    classify every possible financial question.
    """
    normalized = question.lower()

    return any(
        re.search(pattern, normalized)
        for pattern in FINANCIAL_PATTERNS
    )