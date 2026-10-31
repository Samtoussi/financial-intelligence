# M005 quality fix: monetary units in qualitative notes

## Root cause and historical status

The exact saved response is
`evals/reports/m005/live/20261031T122747Z_afd425eb/raw_llm.json`.
Its earnings note describes restructuring costs as "$41 in 2026" and "$33 in
2025". The cited Highlights table explicitly states dollars in millions except
per-share data. Its restructuring row is 41 / 0.07 / 33 / 0.05: USD millions
and USD/share for the current period, then the same dimensions for the prior.

The old `m005-eval-v1` independently verified 16 structured financial values,
eight YoY calculations, eight source-supported pairs and 48 reconciliation
values. Those checks did not examine numbers embedded in qualitative prose.
Assembly verified topic/span eligibility and resolved exact quotations. The
qualitative evaluator verified citation provenance, quotation membership and
nonempty text, then left semantic review pending. The prompt required supported
assertions but did not explicitly require table-level units in standalone prose.
Valid citations therefore accompanied a materially misleading monetary claim.

The old automatic result was true; overall approval was already false. No
historical response, evaluation, review, supporting artifact or presentation is
rewritten or approved by this fix.

## New behavior

`src/analytics/narrative_money.py` implements the bounded
`cat-narrative-money-v1` check, applied to M005 CAT notes only. It reads only
the note and its cited source quotations; it has no oracle or model dependency.

- Identify currency-prefixed amounts (`$`, `US$`, `USD`) and amounts written in
  dollars/USD. Interpret explicit thousand/million/billion scales using Decimal.
- Build supported aggregate-dollar and USD/share values from explicitly scaled
  source prose and the observed CAT adjustment table's typed columns. Numeric
  table cells without the dimensional header cannot support these claims.
- Require each identified narrative amount to match a cited value in the stated
  dimension. An unqualified $41 means 41 actual dollars; it cannot match the
  source's USD 41 million. The checker never supplies the missing word.
- Recognize local EPS/profit-per-share wording and explicit per-share suffixes,
  including the nonbreaking hyphens in the saved response. A nearby parenthetical
  EPS adjustment does not qualify an aggregate restructuring amount.
- Accept short coordinated units (`$41 and $33 million`), clause-local explicit
  declarations (`costs (USD millions) were $41 and $33`), fully expanded dollar
  values and exact scale conversions (`$0.041 billion`). A qualifier cannot flow
  across a sentence or semicolon to another claim.
- Reject unsupported monetary syntax and wrong source scales/dimensions. Plain
  years and percentages are not treated as money.

The assembler now rejects the saved note before producing an assembled report.
The evaluator independently invokes the same source-unit check on the saved
report, so direct evaluation cannot bypass assembly enforcement. A synthetic
passing review cannot override the automatic failure. Numeric oracle, citation,
source-row and reconciliation checks remain mandatory and unchanged.

The CAT evaluator is now `m005-eval-v2` and includes per-note
`narrative_monetary_units` diagnostics with exact text offsets, dimensions,
canonical values and errors. The new CAT prompt explicitly requires standalone
source units and is versioned `m005-assembly-v2`. No live call was made with it.

The investor gate requires the new CAT evaluation version; old v1 records cannot
be silently promoted or treated as current evaluations. Their historical version
labels and results remain unchanged. The two Microsoft profiles retain their
prompts, schemas, evaluator output contracts and archived read-only replay.

This remains a bounded guard, not general semantic verification. It does not
establish causal or period attribution, or that two equal monetary amounts refer
to the same economic item. It does not parse arbitrary spelled-out amounts,
unmarked numbers or every currency/financial idiom. Unsupported forms need
explicit supported wording and human review; no general NLP framework was added.

## Separate read-only diagnostic

`evals/check_cat_narrative.py` reconstructs evidence and the source registry,
checks raw-note consistency, attempts strict assembly, and runs the independent
report evaluator against the archived oracle. It hashes every input file,
including any human-review record, and verifies the set/hashes before writing.
The output must be outside the input run and uses a unique directory. It does
not call the existing in-place `reevaluate` function, load credentials or make
SEC/OpenAI requests.

```powershell
.venv/Scripts/python.exe -B evals/check_cat_narrative.py --run evals/reports/m005/live/20261031T122747Z_afd425eb
```

Saved diagnostic:

`evals/reports/m005/unit-diagnostics/20261031T134530Z_6a8a08ce/`

`evaluation.json` reports:

- `evaluation_version: m005-eval-v2`
- `automatic_pass: false`, `overall_pass: false`
- Earnings note rejected for exactly `$41` and `$33`.
- All six EPS/per-share mentions in that note remain supported.
- Segment and sales-volume/price notes pass this bounded check.
- Financial values 16/16, YoY 8/8, source-supported pairs 8/8, reconciliation
  values 48/48; citation integrity and quote membership still pass.
- All actual semantic-review statuses remain pending.

`diagnostic.json` records the unchanged input hashes, the historical v1 automatic
pass, the new rejection and assembly error. CLI exit code **1 is expected** for
this negative case. Neither this diagnostic nor the earlier investor draft is
an approval or a corrected report.

## Tests and integrity

The byte-exact saved `raw_llm.json` is copied into
`tests/fixtures/cat_m005_defective_notes.json` as an explicitly defective test
input. `tests/test_narrative_money.py` uses that text with the compact source
excerpt even when private run artifacts are absent. When the historical run is
available it additionally checks fixture/source byte equality and read-only
rejection against the saved real evidence.

Focused results: **50 passed**: 25 valid wording cases, 18 ambiguous/unsupported
wording cases, and seven integration/source/contract tests. Positive cases cover
EPS, per-share adjustments, percentages, shared qualifiers, USD wording, expanded
amounts, scale conversions and qualified source prose. Negative cases cover the
exact defect, unit leakage, wrong scales, mixed aggregate/per-share dimensions,
invented values and malformed monetary tokens. Corrected wording exists only
as an in-memory test candidate; it is never written into the historical run.

Final full suite: **579 passed, 0 failed, 0 skipped**, nine existing-style
cached-source parser warnings, in **47.01 seconds**. This includes all 529 M005
tests and 50 new monetary-unit tests.

```powershell
.venv/Scripts/python.exe -B -m pytest tests -q -p no:cacheprovider --basetemp=data/m005-quality/pytest-full-final
```

All **229 pre-fix report artifact files retain their hashes**, including raw
responses, evaluations, review templates and investor presentations. The hash
inventory is the ignored local `data/m005-quality/historical_hashes.json`.
Both MSFT approved source runs pass read-only gate replay with their existing
`m003-eval-v1` output. `git diff --check` passes and the Git index is unchanged.
No human-review records were modified. There were no SEC or OpenAI calls.

## Scope of this fix

Changed existing implementation files: `src/ai/report_assembly.py`,
`src/evaluation/report_evaluation.py`, `src/analytics/investor_report.py`.
Added implementation/diagnostic files: `src/analytics/narrative_money.py`,
`evals/check_cat_narrative.py`. Added tests/fixture:
`tests/test_narrative_money.py`, `tests/fixtures/cat_m005_defective_notes.json`.
Documentation: this file and a historical-status note in `evals/M005.md`.
Other working-tree M005 changes predate this quality-fix request.

No dependencies, additional live calls, historical edits, human-review decisions,
commits or pushes are introduced.

## Recommended next step

Review this safeguard first. If accepted, explicitly authorize a fresh CAT
generation using the revised prompt and checks, with a new run directory and a
bounded attempt count. Retain the defective run as the negative example. Require
all automatic checks plus independent oracle, semantic and presentation review
before accepting the new report. Do not edit or promote the old response.
