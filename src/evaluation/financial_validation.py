
from numbers import Real


def validate_financial_answer(
    actual: dict | None,
    proposed: dict | None,
) -> list[str]:
    """
    Validate structured financial figures against governed Gold data.

    Returns a list of errors. An empty list means validation passed.

    This does not validate free-text AI responses.
    """

    if actual is None:
        if proposed is None:
            return []

        return ["Financial data is unavailable, but values were provided"]

    if proposed is None:
        return ["Financial data exists, but no values were provided"]

    errors = []

    for field in ("ticker", "fiscal_year", "revenue_usd"):
        if proposed.get(field) != actual.get(field):
            errors.append(f"Mismatch: {field}")

    actual_comparable = actual.get("is_comparable")
    proposed_comparable = proposed.get("is_comparable")

    if (
        type(actual_comparable) is not bool
        or type(proposed_comparable) is not bool
        or proposed_comparable != actual_comparable
    ):
        errors.append("Mismatch: is_comparable")

    actual_growth = actual.get("yoy_growth_pct")
    proposed_growth = proposed.get("yoy_growth_pct")

    if actual_comparable is False:
        if proposed_growth is not None:
            errors.append(
                "Growth must be unavailable when data is non-comparable"
            )
    elif actual_comparable is True:
        if (
            isinstance(actual_growth, bool)
            or not isinstance(actual_growth, Real)
            or isinstance(proposed_growth, bool)
            or not isinstance(proposed_growth, Real)
            or abs(proposed_growth - actual_growth) > 0.01
        ):
            errors.append("Mismatch: yoy_growth_pct")

    return errors
