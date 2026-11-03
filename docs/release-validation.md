# Release validation evidence

M012-C evidence inspection: November 3, 2026, at documentation revision
`6fc5a016cf5012a64a1ecf12cdb32e526be36d31`. This summary records local evidence;
it does not distribute private archives or claim a fresh SEC/OpenAI execution.

## Microsoft M011 scenario

- Profile: `msft_fy2026_q1`; CIK 789019; Form 10-Q.
- SEC accession: `0001193125-25-256321`, filed October 29, 2025.
- Document: `msft-20250930.htm`; quarter July–September 2025 versus July–September 2024.
- [Pinned SEC filing](https://www.sec.gov/Archives/edgar/data/789019/000119312525256321/msft-20250930.htm).
- Original saved run: `evals/reports/m003/20261030T211637Z_de30375b/`.
- M011 replay: `data/m011/msft-4b0d09e6d89740999de65b9ca5821ae7/saved-run/`.
- M011 presentation: `data/m011/msft-4b0d09e6d89740999de65b9ca5821ae7/presentations/20261103T172731Z_ab850fb4/`.

These are local paths under ignored directories, not files supplied by a clone.
Quarterly financial values are extracted from filing tables and assembled in
Python; they do **not** come from CompanyFacts/dbt Gold.

### Historical inference, replay and review

The original archive records a live OpenAI call using `m003-v2`, with raw response
status `completed`, returned model `gpt-5-mini-2025-08-07`, and response ID
`resp_0ff7cd30d411ec79006ae50937ce4087d2965ef3dae883b87f`. That ID matches
`generation.json`, which records 8,764 input and 1,478 output tokens. These are
saved request/response records, not an independent confirmation from OpenAI today.

M011 copied the saved run, re-evaluated it offline and rendered a separate
presentation. It did not create new model commentary. Saved semantic reviews
remain attributed to “Human review assisted by ChatGPT”; they are distinct from
the later visual presentation approval by “Project owner”.

| Check | Verified local result |
|---|---|
| Independent financial values | 14/14 |
| YoY changes | 7/7 |
| Source-supported metric pairs | 7/7 |
| Saved semantic reviews | All three pass; source-run overall pass true |
| Current read-only source-run render gate | Pass |
| Current automatic presentation evaluation | Pass, zero failures; 194 core words within 220-word budget |
| Presentation input manifest | All 21 source-artifact hashes match |
| Owner presentation review | Pass, with exact report/detail hashes |
| Separate combined review record | `automatic_pass=true`, `manual_review_pass=true`, `overall_pass=true` |

The current automatic presentation result matches `presentation_evaluation.json`
exactly. That automatic-only evaluator intentionally retains `overall_pass=false`
and pending presentation review. `reviewed_presentation_evaluation.json` is a
separate combined record, not native approval support added to the evaluator.
The owner's rationale covers clarity, faithful comparisons, narrative context,
citations, formatting and completeness. It asserts neither measured reading time
nor personal inspection of original SEC HTML.

### SHA-256 identifiers

| Artifact | SHA-256 |
|---|---|
| Cached original SEC HTML | `ddc8ccac31f51b0be3509a3dbe001c560ee357502a77652dfbad3e92c3d9f432` |
| M011 `report.md` | `a4f3f83b43d260989126ad1f25564bd87ea9b9c1586fbe05f0db2b5efad0c1d4` |
| M011 `supporting_detail.md` | `53b5371c4284e321bc6f5ed714040163f8750018f9eaebfa7e93080e6b637c99` |
| M011 `presentation_review.json` | `c31d824b4a7ae656551b6889a26c5da01be247ccc7fb4b99151a82e983ec62e5` |
| M011 `reviewed_presentation_evaluation.json` | `ee79a8dd88f4fea4b31a7288da8adcdac05df6d99f104384ade5de89e4244ae2` |

Hashes were recomputed locally. The combined record references the matching owner
review hash; both review records match the actual report/detail hashes. Hashes
establish local consistency, not independent source authentication or signatures.

### Reproduction commands and prerequisites

With dependencies already installed, run from the repository root. The full
[Microsoft recipe](operations.md#microsoft-fy2026-q1-reproduction) explains source
acquisition, explicit snapshot selection, writes, costs and review boundaries.
For an offline replay, the original private archive must already exist:

```powershell
$py = '.\.venv\Scripts\python.exe'
$original = 'evals/reports/m003/20261030T211637Z_de30375b'
$work = Join-Path 'data/release-validation' ('msft-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $work | Out-Null
$run = Join-Path $work 'saved-run'
Copy-Item -LiteralPath $original -Destination $run -Recurse
& $py -B evals/run_report.py --profile msft_fy2026_q1 --evaluate-run $run --reviews (Join-Path $run 'review.json')
& $py -B evals/render_investor_report.py --run $run --output-root (Join-Path $work 'presentations')
```

Evaluation writes the copy and returns 0 when automatic/semantic gates pass.
Rendering writes a new presentation and returns 2 for pending presentation review.
Existing approval does not automatically apply to that new output. Fresh inference
uses `--generation-mode m003-v2 --snapshot <exact-cached-HTML-path>` and incurs an
OpenAI call; it is not this offline replay. No inference or regeneration was run
during the M012-C inspection.

## Local test checkpoint and CI status

**Reported local checkpoint:** 1,201 passed, 4 skipped, 14 parser warnings in
140.11 seconds, after isolating tracking tests from the shared CI warehouse.
The recorded command was:

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q --basetemp=data/test_tmp/ci-tracking-full -p no:cacheprovider
```

The tested change was subsequently committed as
`ea6062c31ce4cab511309526f9da228d566c599a`. The inspection revision `6fc5a01`
differs from it only in README/operations documentation. No persisted test log
binding that result to a commit was recovered, so this remains a reported local
checkpoint, not a newly executed or machine-attested release test. No tests were
rerun for this documentation task. Older README/M009 counts remain historical.

**Latest GitHub Actions conclusion and revision: not verified.** The read-only
`gh run list --repo Samtoussi/financial-intelligence --workflow ci.yml --limit 1`
lookup could not run because GitHub CLI was unauthenticated. Public Actions/API
fetches were also unavailable. No run ID, remote revision or success is asserted.
Check the [Actions page](https://github.com/Samtoussi/financial-intelligence/actions)
before release. The [configured workflow](../.github/workflows/ci.yml) prepares a
synthetic warehouse, builds dbt and runs pytest; it does not perform live SEC or
OpenAI calls. [Fresh-checkout test preparation](operations.md#offline-test-preparation)
is documented separately.

## Public showcase integrity and approval boundary

All 11 files listed in the public manifest matched their hashes; all six public
Markdown files matched the separate content-approval hashes. These files are
tracked. The manifest SHA-256 is
`380f528ffbc85e4061b6ae91ef382b7bf522e0e173601a6eec93a9788a1d754c`;
the public content-approval file SHA-256 is
`c19d8ece3a5162001d8f9d0a0be15a71a490cf4c84f553f9101ca465966a4a7a`.

The M011 owner approval covers its private Microsoft presentation copy only.
It does not promote the M004 archive or approve MSFT/CAT/JPM public derivatives.
Public viewing reports saved outcomes and checks package integrity; it does not
replay omitted private-source evaluations. Existing public content approval and
rights conditions remain as documented in the [notice](../showcase/quarterly/NOTICE.md),
[manifest](../showcase/quarterly/manifest.json) and
[approval record](../showcase/quarterly/publication_approval.json).

Remaining release verification: confirm the actual remote CI outcome and revision.
A fresh-clone install is not established by this local artifact inspection.
