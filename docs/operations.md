
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

Python ingestion, analytics and AI financial tools read this variable at runtime,
and dashboard cache entries include the resolved warehouse path. Relative overrides
are resolved against the process working directory; run pipeline and dbt commands
from the repository root, or use an absolute path. dbt reads the environment on
each invocation. Changing the variable selects a warehouse; it does not populate
it or migrate data. Restart a separate running app process to change its environment.

A failed dbt execution may still produce `run_results.json`. When available and valid, its diagnostic summary is recorded in the failed Gold stage.
If the result artifact is missing or invalid, the run records that condition instead.

## Incremental Processing & Snapshot History

CompanyFacts uses content-addressed snapshots identified by the SHA-256 hash of the original SEC response.

Each pipeline execution retrieves and stores a Bronze snapshot. Before Silver processing, the incoming snapshot ID is compared with the company's active snapshot in DuckDB.

- Unchanged snapshots skip Silver normalization, Parquet writing and warehouse loading.
- Changed snapshots are normalized into a complete Silver Parquet dataset.
- DuckDB replaces the selected company's observations within a transaction.
- Other companies' observations remain unaffected.
- Gold models are rebuilt on each successful pipeline execution.

Snapshot history is preserved in Bronze, while Silver Parquet files are addressed by snapshot hash. The warehouse contains the active observations for each company rather than all historical versions.

Historical snapshots can be compared using:

```powershell
.\.venv\Scripts\python.exe -m src.transformation.snapshot_report JPM
```

The report compares the two most recent distinct snapshots with available Silver Parquet files and summarizes added, removed, changed and ambiguous observations.

### Incremental Loading Design Decision

Row-level incremental updates using MERGE or UPSERT were evaluated but are not implemented.

The current warehouse is approximately 17.76 MB and contains roughly 127,000 active CompanyFacts observations across three companies.

Full replacement per company was retained because:

- DuckDB handles the current dataset size without an observed performance bottleneck.
- Transactional replacement provides a straightforward recovery and consistency model.
- Every active observation belongs to one identifiable snapshot.
- Row-level updates would require additional identity, lineage and deletion-handling complexity.

Row-level incremental loading may be reconsidered if future data volume or measured loading performance justifies it.

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

## Quarterly report re-evaluation

`python evals/run_report.py --evaluate-run <run-directory>` supports saved
Microsoft and Caterpillar runs. It makes no SEC or model calls, but writes
`evaluation.json` and updates `run.json`. Use `--reviews <review-json>` only
with the applicable completed manual-review records.

JPM `--evaluate-run` is explicitly unsupported and returns exit code 1 with an
actionable message, whether the JPM profile is supplied or inferred from the
saved source accession. Rejection does not modify saved artifacts or invoke
generation, source downloads, attempt-ledger updates or review promotion.

For JPM, inspect the saved `evaluation.json`, `presentation_evaluation.json`
and `run.json` directly. Saved results are historical evidence, not a fresh
evaluation. M006's documented offline replay used the banking-specific evaluators
and original source artifacts; it was not generic `--evaluate-run` support.
Those evaluators require the financial foundation, original source and extraction
validation, raw narrative and accounting-scope checks. No general JPM replay CLI
is provided. Do not use generation as a substitute for re-evaluation or reset
the live-attempt ledger. Existing source-verification, attempt and human-review
gates remain in force.

## Microsoft FY2026 Q1 reproduction

Run from the repository root with the existing virtual environment and installed
dependencies. The supported profile is `msft_fy2026_q1`: CIK 789019, 10-Q accession
`0001193125-25-256321`, document `msft-20250930.htm`, filed October 29, 2025,
covering July–September 2025 versus July–September 2024. These quarterly values
come from filing tables, not CompanyFacts or dbt Gold. See
[profile configuration](../src/analytics/report_profiles.py) and
[report runner](../evals/run_report.py).

### Offline replay of the reviewed saved run

This route requires the existing local `evals/reports/m003/20261030T211637Z_de30375b`
archive, including its saved source/evidence, raw response, oracle and `review.json`.
It is ignored runtime evidence and is **not available in a fresh clone**. No model
or SEC call is made. Copy it before re-evaluating: the CLI writes `evaluation.json`
and `run.json`. This validates saved output; it does not generate new AI commentary.

```powershell
$py = '.\.venv\Scripts\python.exe'
$original = 'evals/reports/m003/20261030T211637Z_de30375b'
$work = Join-Path 'data/release-validation' ('msft-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $work | Out-Null
$run = Join-Path $work 'saved-run'
Copy-Item -LiteralPath $original -Destination $run -Recurse
& $py -B evals/run_report.py --profile msft_fy2026_q1 --evaluate-run $run --reviews (Join-Path $run 'review.json')
```

Expected exit code: 0 if current automatic checks and the saved semantic reviews
pass. The reviewer attribution remains historical; copying does not create a new
review. Omitting `--reviews` makes semantic reviews pending again. Preserve the
original archive and its historical failures.

### New inference from an explicitly selected filing

Deterministic assembly (`m003-v2`) owns financial extraction and calculations;
it does **not** make new commentary generation offline. The following command
uses cached HTML without SEC access but makes one paid OpenAI call, with SDK
retries disabled. Configure `OPENAI_API_KEY` in the process environment or root
`.env`; do not put credentials in version control.

The existing local snapshot is shown explicitly below. It and its matching
metadata sidecar must exist; a fresh clone has neither. To acquire the pinned
source, first set `SEC_USER_AGENT` to an application name and real contact email,
then run `python -m run_filings MSFT --form 10-Q --accession 0001193125-25-256321`.
That command requires SEC access and writes a new raw snapshot, sections, company
chunks and an execution manifest, without triggering AI. Use its exact printed
`Snapshot:` path in place of the cached path below. Do not select a different filing.

```powershell
$py = '.\.venv\Scripts\python.exe'
$snapshot = 'data/raw/sec/filings/MSFT/0001193125-25-256321/20261030T184859Z_ddc8ccac31f5.html'
& $py -B evals/run_report.py --profile msft_fy2026_q1 --generation-mode m003-v2 --snapshot $snapshot
```

Generation writes a new run under `evals/reports/m003/`, and updates stored
sections/company chunks. It saves source evidence, assembly inputs, model output,
summary, evaluation and review template. Expected exit code: 2 for automatic pass
with semantic review pending; 1 for failure. Inspect artifacts before proceeding.
Explicit snapshot selection avoids ambiguity if the accession has multiple cached
copies. Do not use the default profile or legacy generation mode for this recipe.

Set `$run` to the exact `run_dir` printed by generation. Copy that new run's
`review_template.json` to `review.json` only if no review exists:

```powershell
$run = '<run_dir printed by generation>'
Copy-Item -LiteralPath (Join-Path $run 'review_template.json') -Destination (Join-Path $run 'review.json')
```

A human must
review all three notes against cited evidence and complete status, reviewer,
rationale and evidence IDs. Do not copy approval from an older model response.
Then re-evaluate offline:

```powershell
& $py -B evals/run_report.py --profile msft_fy2026_q1 --evaluate-run $run --reviews (Join-Path $run 'review.json')
```

Only proceed to rendering when automatic and semantic gates pass (exit code 0).
For a new run, first set `$work` to a new validation directory as in the offline
example; keep presentation output separate from the source run.

### Offline presentation and manual acceptance

Both routes converge on an eligible `$run`. Rendering uses saved artifacts and
makes no SEC/OpenAI calls. It writes a new timestamped presentation directory:

```powershell
& $py -B evals/render_investor_report.py --run $run --output-root (Join-Path $work 'presentations')
```

Exit code **2** means automatic presentation checks passed and manual presentation
review is pending; it is not overall acceptance. Inspect `report.md`,
`supporting_detail.md`, `presentation_evaluation.json` and `review_template.json`
in the printed `output_directory`. Human presentation review covers clarity,
faithful comparisons, narrative context/citations, formatting and completeness.
Record approval separately with the exact report/detail hashes. The existing
automatic-only evaluator has no approval/promotion CLI and retains
`overall_pass: false`; a separate combined approval record must not be presented
as its native output. No command grants implicit approval or publishes a report.

### Microsoft presentation approval boundaries

The original M004 presentation archive retains its generation-time pending state
and lacks its original final hash-bound approval; acceptance was documented in
[M004](../evals/M004.md#final-presentation-approval-and-git-checkpoint).
A separate M011 copy at
`data/m011/msft-4b0d09e6d89740999de65b9ca5821ae7/presentations/20261103T172731Z_ab850fb4/`
received project-owner approval in `presentation_review.json`. Its
`reviewed_presentation_evaluation.json` combines automatic checks and that
hash-bound approval with `overall_pass: true`; it does not modify the evaluator
or original archive. These local records remain ignored. They do not approve
public showcase derivatives, which have their own
[content approval](../showcase/quarterly/publication_approval.json).

## Known Limitations

- There is no automatic retry scheduler or checkpoint-based resume.
- Abrupt process termination between publishing a snapshot payload and its metadata can leave an incomplete artifact pair.
- A run interrupted without executing its Python exception handler may retain `running` status.
- Separate file replacements do not provide an atomic multi-file transaction.
- Run manifests and dbt artifacts are local and are not sent to a centralized monitoring service.

These limitations are accepted for the current manually operated portfolio scope.

## Verification

### Offline test preparation

Use an installed environment in a fresh checkout, from the repository root. Follow
[CI](../.github/workflows/ci.yml): create the synthetic financial warehouse, build
and test dbt Gold, then run pytest. Fixture creation **refuses to overwrite an
existing database**; do not delete or replace a populated local warehouse for this
recipe. The fixture script uses the default path rather than `FI_DUCKDB_PATH`, so
ensure that override is unset for this preparation:

```powershell
Remove-Item Env:FI_DUCKDB_PATH -ErrorAction SilentlyContinue
python scripts/create_ci_db.py
dbt build --project-dir dbt --profiles-dir dbt
python -m pytest tests -v
```

Dependencies must already be installed and the virtual environment activated.
These commands write synthetic data, dbt artifacts and test outputs, but make no
SEC or OpenAI calls. Fixture rows support warehouse-dependent query tests; they
are not real-source verification. Tests using private cached filings can skip.

Public-showcase checks need installed dependencies but no warehouse, credentials
or private report archive: `python -m pytest tests/test_public_quarterly_reports.py -q`.
They verify the public package and route isolation, not fresh SEC evaluation.

### Historical verification

M009 verification baseline: 1,180 tests passed, 4 skipped, 14 parser warnings, November 2026.

This is the preserved milestone baseline, not current release-candidate evidence.
The current release checkpoint is handled separately in M012-C.

The parser warnings are related to XML documents processed using an HTML parser and are tracked separately from operational reliability.
