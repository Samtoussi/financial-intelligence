
import json
from collections import Counter
from pathlib import Path


def summarize_dbt_results(target_dir: Path) -> dict:
    path = Path(target_dir) / "run_results.json"

    if not path.is_file():
        raise FileNotFoundError(
            "dbt run_results.json missing from this execution"
        )

    data = json.loads(path.read_text(encoding="utf-8"))
    metadata = data["metadata"]
    results = data["results"]

    invocation_id = metadata["invocation_id"]
    if not isinstance(invocation_id, str) or not invocation_id:
        raise ValueError("Invalid dbt invocation_id")

    if not isinstance(results, list) or not results:
        raise ValueError("dbt results are empty or invalid")

    counts = Counter()
    for result in results:
        resource_type = result["unique_id"].split(".", 1)[0]
        counts[(resource_type, result["status"])] += 1

    return {
        "invocation_id": invocation_id,
        "dbt_version": metadata["dbt_version"],
        "generated_at": metadata["generated_at"],
        "run_results_path": str(path),
        "model_success": counts[("model", "success")],
        "test_pass": counts[("test", "pass")],
        "failed": sum(
            count
            for (_, status), count in counts.items()
            if status in {"error", "fail"}
        ),
        "status_counts": {
            f"{resource_type}:{status}": count
            for (resource_type, status), count in sorted(counts.items())
        },
    }
