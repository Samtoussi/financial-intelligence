
import json

import pytest

from src.operations.dbt_results import summarize_dbt_results


def write_results(tmp_path, results, invocation_id="test-invocation"):
    target = tmp_path / "dbt"
    target.mkdir()

    data = {
        "metadata": {
            "invocation_id": invocation_id,
            "dbt_version": "1.12.6",
            "generated_at": "2026-11-03T14:00:00Z",
        },
        "results": results,
    }

    (target / "run_results.json").write_text(
        json.dumps(data),
        encoding="utf-8",
    )
    return target


def test_summarizes_successful_dbt_build(tmp_path):
    target = write_results(tmp_path, [
        {"unique_id": "model.fi.annual_revenue", "status": "success"},
        {"unique_id": "model.fi.annual_growth", "status": "success"},
        {"unique_id": "test.fi.revenue_not_null", "status": "pass"},
        {"unique_id": "test.fi.revenue_unique", "status": "pass"},
    ])

    summary = summarize_dbt_results(target)

    assert summary["invocation_id"] == "test-invocation"
    assert summary["model_success"] == 2
    assert summary["test_pass"] == 2
    assert summary["failed"] == 0


def test_summarizes_failed_dbt_build(tmp_path):
    target = write_results(tmp_path, [
        {"unique_id": "model.fi.annual_revenue", "status": "success"},
        {"unique_id": "model.fi.annual_growth", "status": "error"},
        {"unique_id": "test.fi.revenue_not_null", "status": "skipped"},
    ])

    summary = summarize_dbt_results(target)

    assert summary["model_success"] == 1
    assert summary["failed"] == 1
    assert summary["status_counts"]["test:skipped"] == 1


def test_missing_results_are_rejected(tmp_path):
    with pytest.raises(FileNotFoundError):
        summarize_dbt_results(tmp_path)


def test_empty_results_are_rejected(tmp_path):
    target = write_results(tmp_path, [])

    with pytest.raises(ValueError, match="empty or invalid"):
        summarize_dbt_results(target)


def test_missing_invocation_id_is_rejected(tmp_path):
    target = write_results(tmp_path, [
        {"unique_id": "model.fi.test", "status": "success"}
    ], invocation_id="")

    with pytest.raises(ValueError, match="invocation_id"):
        summarize_dbt_results(target)
