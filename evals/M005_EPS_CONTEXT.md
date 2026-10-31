# M005: offline EPS context correction

## Root cause and bounded fix

The second saved response, `20261031T135327Z_98c78688`, correctly qualified
restructuring costs as $41 million and $33 million. Its earnings note established
USD/share with "profit per common share" and "profit per share", but the validator
lost that dimension at the next currency token. `EPS_PREFIX` intentionally cannot
see across an earlier dollar sign. The fallback `JOIN` accepted only a bare year
or Q-number/year after "in", followed by a short comparison connector. It did not
accept these actual intervening strings:

- `in the three months ended March 31, 2026 and`
- `for 2026 and`

The fix adds a separate, fully matched EPS comparison grammar. It accepts bounded
calendar-year, quarter/year, named-month date, quarter-ended, three-months-ended
and named-quarter phrases after `in`, `for` or `during`, followed by an explicit
comparison connector. Inheritance requires that the immediately preceding amount
was already source-supported in USD/share with unit scale 1. The intervening text
is limited to 128 characters and cannot contain a new subject, sentence or
parenthetical monetary claim. Every resulting amount must still independently
match a cited USD/share value. Other dollar amounts are not assumed to be EPS.

Aggregate-dollar parsing and the original `JOIN` rule remain unchanged. The
original missing-unit $41/$33 response still fails. The helper version is now
`cat-narrative-money-v2`, and the CAT evaluator is `m005-eval-v3`. The investor gate
requires that new CAT version rather than relabeling old saved evaluations.
Microsoft prompts, profiles and evaluation contracts are unchanged. The saved CAT
prompt remains `m005-assembly-v2`; no narrative was regenerated.

## Tests

`tests/test_eps_context.py` adds 28 cases: byte-exact saved wording, 10 longer
comparison forms, 14 negative cases, mixed EPS/aggregate claims, evidence support,
and real saved-source replay. The fixture
`tests/fixtures/cat_m005_second_notes.json` is byte-equal to the historical raw
notes. Test excerpts receive their own source-span IDs without editing note text.

The 50 original monetary-unit cases remain. Focused total: **78 passed**. Missing
units, unsupported EPS amounts, intervening subjects, sentence/semicolon
boundaries and invalid aggregate/per-share dimensions remain negative cases.

Full suite: **607 passed, 0 failed, 0 skipped**, nine existing-style parser
warnings, in **51.23 seconds**:

```powershell
.venv/Scripts/python.exe -B -m pytest tests -q -p no:cacheprovider --basetemp=data/m005-eps-fix/pytest-full-1
```

Both Microsoft reviewed runs additionally pass read-only gate replay. The exact
original defective CAT response still reports errors for `$41` and `$33` only.

## Offline reassembly and investor output

Original response directory remains unchanged:

`evals/reports/m005/fresh-live/20261031T135327Z_98c78688/`

New diagnostic and complete derived run:

`evals/reports/m005/eps-context-diagnostics/20261031T135903Z_36cca949/`

Existing `prepare`, `assemble`, `evaluate_report` and technical rendering
functions were called offline. Source HTML checksum, evidence reconstruction,
saved registry and strict output schema were checked. The independent oracle's
bytes match the pre-fix inventory. Raw notes, raw response, prompt, schema and
source records were copied byte-exact; a separate manifest records offline
derivation and its parent run. The incomplete historical manifest was not changed.

Automatic evaluation passes: **16/16 values, 8/8 YoY, 8/8 source-supported pairs,
48/48 reconciliation values, 12/12 monetary mentions**, plus metadata, citation
integrity and exact quotations. Overall remains false with semantic review
pending. Diagnostic/source hashes are recorded in `diagnostic.json`; archived
oracle and semantic review templates remain pending.

New investor presentation, produced by the existing M004 layer in explicit
pending-review draft mode:

`evals/reports/m005/eps-context-presentations/20261031T135903Z_3670fe1a/report.md`

Presentation checks pass with 195 core words. All three saved notes appear
unchanged in supporting detail. The presentation evaluation remains overall
false and its separate hash-bound review template remains pending. No human
approval file was created.

All **287 pre-existing source/oracle/report files**, including **246 report
artifacts**, retain their hashes. Earlier diagnostics and both live responses are
unchanged. The ignored integrity inventory is
`data/m005-eps-fix/historical_hashes.json`.

Changed files for this fix: `src/analytics/narrative_money.py`,
`src/evaluation/report_evaluation.py`, `src/analytics/investor_report.py`, the
version assertions in `tests/test_narrative_money.py`, the new EPS tests/fixture,
and this document. No dependencies, SEC/OpenAI calls, narrative repair, commits
or pushes were introduced.

Oracle, semantic and presentation human review are still required. This remains
a bounded value/dimension check, not a general semantic or causal verifier.
