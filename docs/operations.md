
# Operations & Recovery

Financial Intelligence is a locally operated, manually invoked data platform. Pipeline executions are tracked using persistent JSON manifests to support debugging, artifact traceability and recovery.

## Execution Tracking

The CompanyFacts and Filings pipelines create a unique run ID for each execution.

Run manifests are stored at:

- `data/runs/companyfacts/<run_id>/run.json`
- `data/runs/filings/<run_id>/run.json`

Each manifest records:

- Pipeline name and unique run ID
- Execution status (`running`, `success`, `failed`)
- UTC start and finish timestamps
- Execution and stage durations
- Stage-level status and artifact references
- Exception types for failed executions

CompanyFacts tracks preflight, Bronze and Silver for each company, followed by Gold.

Filings tracks preflight, Bronze, Silver and retrieval.

Exception messages are intentionally excluded from manifests to avoid persisting potentially sensitive information.

## dbt Artifact Correlation

Each CompanyFacts execution uses an isolated dbt target directory:

`data/runs/companyfacts/<run_id>/dbt/`

The Gold stage records:

- dbt invocation ID and version
- Artifact generation timestamp
- Model and test result counts
- Failed node count
- Path to `run_results.json`
- DuckDB warehouse path

The warehouse path defaults to `data/warehouse/financial_intelligence.duckdb` and can be overridden using `FI_DUCKDB_PATH`.

A failed dbt execution may still produce `run_results.json`. When available and valid, its diagnostic summary is recorded in the failed Gold stage.

If the result artifact is missing or invalid, the run records that condition instead.

## Failure Investigation

1. Locate the relevant pipeline's latest run directory under `data/runs/`.
2. Open `run.json` and inspect the overall status.
3. Identify the failed stage and its exception type.
4. Review the recorded artifact paths and identifiers.
5. For Gold failures, inspect the execution-specific dbt `run_results.json`, if present.
6. Correct the underlying problem before retrying.

Run manifests contain diagnostic metadata, not complete error logs.

## Recovery & Reruns

Pipeline executions are manually restarted. A retry creates a new run ID rather than resuming an existing execution.

Filing snapshots use unique filenames, temporary files and rollback when metadata publication raises a Python exception.

If metadata publication fails after the HTML file has been published, the current invocation removes its HTML file. Temporary files are also cleaned up.

Regression tests verify that a subsequent snapshot save can succeed without manual cleanup after a simulated publication failure.

CompanyFacts snapshots use corresponding temporary-file and rollback protections.

Before retrying, inspect the failure and verify that its cause has been addressed. A successful retry does not rewrite the previous run's failure status.

## Known Limitations

- There is no automatic retry scheduler or checkpoint-based resume.
- Abrupt process termination between publishing a snapshot payload and its metadata can leave an incomplete artifact pair.
- A run interrupted without executing its Python exception handler may retain `running` status.
- Separate file replacements do not provide an atomic multi-file transaction.
- Run manifests and dbt artifacts are local and are not sent to a centralized monitoring service.

These limitations are accepted for the current manually operated portfolio scope.

## Verification

Run the complete test suite from the repository root:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

M008 verification baseline: 1,159 tests passed, 14 parser warnings, November 2026.

The parser warnings are related to XML documents processed using an HTML parser and are tracked separately from operational reliability.
