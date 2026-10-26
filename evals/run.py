
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.ai.analyst import analyze
from src.ai.response_builder import build_user_response
from src.ai.risk_evidence import validate_risk_claims


CASES_PATH = Path(__file__).with_name("cases.json")
REPORTS_DIR = Path(__file__).with_name("reports")


def check_technical(case: dict, result) -> list[str]:
    failures = []

    expected_tickers = set(case["expected_tickers"])
    expected_year = case["expected_fiscal_year"]

    if case["requires_financial_evidence"]:
        actual_pairs = {
            (item.get("ticker"), item.get("fiscal_year"))
            for item in result.financial_evidence
        }

        expected_pairs = {
            (ticker, expected_year)
            for ticker in expected_tickers
        }

        missing = expected_pairs - actual_pairs

        if missing:
            failures.append(
                f"Missing Gold evidence: {sorted(missing)}"
            )

        if not result.financial_summary:
            failures.append("Missing financial summary")

    if case["requires_document_evidence"]:
        actual_tickers = {
            item.get("ticker")
            for item in result.document_evidence
        }

        missing = expected_tickers - actual_tickers

        if missing:
            failures.append(
                f"Missing SEC evidence: {sorted(missing)}"
            )

    claims = serialize_risk_claims(result.risk_claims)

    validated = validate_risk_claims(
        claims,
        result.document_evidence,
    )

    if len(validated) != len(result.risk_claims):
        failures.append(
            "Risk claims contain invalid source references"
        )

    return failures


def check_answer_coverage(
    case: dict,
    result,
    response,
) -> list[str]:
    failures = []

    if not response.text.strip():
        failures.append("Empty user response")

    if case["requires_risk_claims"]:
        expected_tickers = set(case["expected_tickers"])

        actual_tickers = {
            claim.ticker
            for claim in result.risk_claims
        }

        missing = expected_tickers - actual_tickers

        if missing:
            failures.append(
                f"Missing risk explanations: {sorted(missing)}"
            )

    return failures


def serialize_risk_claims(claims) -> list[dict]:
    return [
        {
            "ticker": claim.ticker,
            "explanation": claim.explanation,
            "chunk_id": claim.chunk_id,
            "source_url": claim.source_url,
        }
        for claim in claims
    ]


def run_case(case: dict) -> dict:
    started = time.perf_counter()

    result = None
    response = None
    technical_failures = []
    coverage_failures = []

    try:
        result = analyze(case["question"])
        response = build_user_response(result)

        technical_failures = check_technical(
            case,
            result,
        )

        coverage_failures = check_answer_coverage(
            case,
            result,
            response,
        )

    except Exception as exc:
        technical_failures = [
            f"{type(exc).__name__}: {exc}"
        ]
        coverage_failures = [
            "Evaluation could not complete"
        ]

    elapsed = round(
        time.perf_counter() - started,
        2,
    )

    technical_ok = not technical_failures
    coverage_ok = not coverage_failures

    return {
        "id": case["id"],
        "category": case["category"],
        "question": case["question"],
        "duration_seconds": elapsed,
        "technical_pass": technical_ok,
        "coverage_pass": coverage_ok,
        "overall_pass": technical_ok and coverage_ok,
        "technical_failures": technical_failures,
        "coverage_failures": coverage_failures,
        "answer": response.text if response else None,
        "financial_evidence": (
            result.financial_evidence if result else []
        ),
        "document_evidence": (
            result.document_evidence if result else []
        ),
        "risk_claims": (
            serialize_risk_claims(result.risk_claims)
            if result else []
        ),
    }


def main():
    cases = json.loads(
        CASES_PATH.read_text(encoding="utf-8")
    )["cases"]

    print("\nFINANCIAL INTELLIGENCE EVALUATION V1.2")
    print(f"Cases: {len(cases)}\n")

    results = []

    for case in cases:
        result = run_case(case)
        results.append(result)

        print(
            f"[{result['id']}] "
            f"({result['duration_seconds']:.2f}s)"
        )

        print(
            "  Technical: "
            + (
                "PASS"
                if result["technical_pass"]
                else "FAIL"
            )
        )

        print(
            "  Coverage:  "
            + (
                "PASS"
                if result["coverage_pass"]
                else "FAIL"
            )
        )

        for failure in (
            result["technical_failures"]
            + result["coverage_failures"]
        ):
            print(f"  - {failure}")

        print()

    technical_passed = sum(
        item["technical_pass"]
        for item in results
    )

    coverage_passed = sum(
        item["coverage_pass"]
        for item in results
    )

    overall_passed = sum(
        item["overall_pass"]
        for item in results
    )

    timestamp = datetime.now(
        timezone.utc
    ).strftime("%Y%m%dT%H%M%SZ")

    report = {
        "evaluation_version": "1.2",
        "timestamp_utc": timestamp,
        "total_cases": len(results),
        "technical_passed": technical_passed,
        "coverage_passed": coverage_passed,
        "overall_passed": overall_passed,
        "results": results,
    }

    REPORTS_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    report_path = (
        REPORTS_DIR / f"evaluation_{timestamp}.json"
    )

    report_path.write_text(
        json.dumps(
            report,
            indent=2,
            ensure_ascii=False,
            default=str,
        ),
        encoding="utf-8",
    )

    print("=" * 48)
    print(
        f"Technical: {technical_passed}/{len(results)}"
    )
    print(
        f"Coverage:  {coverage_passed}/{len(results)}"
    )
    print(
        f"Overall:   {overall_passed}/{len(results)}"
    )
    print(f"Report:    {report_path}")

    if overall_passed != len(results):
        sys.exit(1)


if __name__ == "__main__":
    main()
