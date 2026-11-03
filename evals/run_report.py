"""Reproducible single-call two-profile baseline and offline re-evaluation."""
import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
from src.ai import report_assembly
from src.analytics.report_evidence import build_report_evidence
from src.analytics.report_profiles import DEFAULT_PROFILE, PROFILES, get_profile, profile_for_accession
from src.ai.report_generator import (MODEL, generate_report, render_report, output_schema,
                                     instructions_for, prompt_version)
from src.evaluation.report_ground_truth import load_report_dataset
from src.evaluation.report_evaluation import evaluate_report
from src.ingestion.filings import discover_filing, fetch, save_snapshot
from src.transformation.parse_filings import load_latest_snapshot, resolve_cached_snapshot
from src.transformation.store_filings import prepare_sections, save_sections
from src.transformation.chunk_filings import process_ticker


def write_json(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def reevaluate(run_dir: Path, *, reviews=None, profile=None):
    read = lambda name: json.loads((run_dir / name).read_text(encoding="utf-8"))
    source, evidence = read("source.json"), read("evidence.json")
    selected = profile or profile_for_accession(source["accession"])
    profile_path = run_dir / "profile.json"
    if profile_path.exists() and json.loads(profile_path.read_text(encoding="utf-8")) != json.loads(json.dumps(get_profile(selected))):
        raise ValueError("Saved profile disagrees with selected filing configuration")
    if evidence != build_report_evidence(read("sections.json"), source, profile=selected):
        raise ValueError("Saved evidence disagrees with saved section spans/provenance")
    gt_path = run_dir / "ground_truth.json"
    ground_truth = load_report_dataset(selected, gt_path) if gt_path.exists() else load_report_dataset(selected)
    generated = read("generated.json")
    if read("run.json").get("generation_mode") == report_assembly.MODE:
        rebuilt = report_assembly.assemble(read("raw_llm.json"), evidence, selected, read("assembly_inputs.json"))
        if rebuilt != generated:
            raise ValueError("Saved assembled report disagrees with raw response/source spans")
    evaluation = evaluate_report(generated, evidence, ground_truth,
                                 source_sha256=source["sha256"], reviews=reviews, profile=selected)
    write_json(run_dir / "evaluation.json", evaluation)
    manifest = read("run.json")
    manifest.update(status=("completed_reviewed" if evaluation["overall_pass"] else
                            "completed_pending_review" if evaluation["automatic_pass"] else "automatic_checks_failed"),
                    overall_pass=evaluation["overall_pass"])
    write_json(run_dir / "run.json", manifest)
    return evaluation


def run_baseline(*, snapshot_path=None, download=False, client=None, model=MODEL,
                 reports_dir=None, profile=DEFAULT_PROFILE, generation_mode="legacy"):
    """Generate once. Save failures without credentials or exception/request dumps."""
    if profile == 'jpm_2026_q2':
        if download or generation_mode != report_assembly.MODE:
            raise ValueError('JPM uses pinned offline source and deterministic assembly only')
        return run_banking(snapshot_path=snapshot_path, client=client, model=model, reports_dir=reports_dir)
    if generation_mode not in ("legacy", report_assembly.MODE):
        raise ValueError("Unsupported generation mode")
    assembly_mode = generation_mode == report_assembly.MODE
    config = get_profile(profile)
    report = config["report"]
    ticker = report["ticker"]
    if config.get("contract") and not assembly_mode:
        raise ValueError("New profiles require deterministic assembly mode m003-v2")
    reports_dir = reports_dir or ROOT / ("evals/reports/m005" if config.get('contract') else "evals/reports/m002" if profile == DEFAULT_PROFILE and not assembly_mode else "evals/reports/m003")
    os.chdir(ROOT)
    load_dotenv(ROOT / ".env")
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:8]
    run_dir = Path(reports_dir) / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    manifest = {"run_id": run_id, "model": model, "prompt_version": report_assembly.prompt_version(profile) if assembly_mode else prompt_version(profile), "profile": profile,
                "status": "started", "live_model_call_attempted": False}
    if assembly_mode:
        manifest["generation_mode"] = generation_mode
    write_json(run_dir / "run.json", manifest)
    write_json(run_dir / "profile.json", config)
    (run_dir / "instructions.txt").write_text(report_assembly.instructions_for(profile) if assembly_mode else instructions_for(profile), encoding="utf-8")
    if not assembly_mode:
        write_json(run_dir / "output_schema.json", output_schema(profile))
    try:
        if download:
            if snapshot_path is not None:
                raise ValueError("Choose --download or --snapshot, not both")
            user_agent = os.environ.get("SEC_USER_AGENT", "").strip()
            if "@" not in user_agent:
                raise ValueError("SEC_USER_AGENT requires a real contact email")
            filing = discover_filing(report["cik"], user_agent, report["form"], report["accession"])
            if any(filing[key] != report[key] for key in (
                "cik", "form", "accession", "filing_date", "document", "source_url",
            )) or filing["report_date"] != report["period_end"]:
                raise ValueError("SEC discovery disagrees with pinned report")
            snapshot_path = save_snapshot(ticker, fetch(filing["source_url"], user_agent), filing)
        # Resolve once to an explicit path before any subsequent processing.
        if snapshot_path is None:
            snapshot_path = resolve_cached_snapshot(
                ticker, form="10-Q", accession=report["accession"],
            )
        _, metadata = load_latest_snapshot(ticker, form="10-Q", accession=report["accession"],
                                           snapshot_path=snapshot_path)
        sections = prepare_sections(ticker, form="10-Q", accession=report["accession"],
                                    snapshot_path=snapshot_path)
        evidence = build_report_evidence(sections, metadata, profile=profile)
        save_sections(ticker, sections)
        process_ticker(ticker)
        write_json(run_dir / "source.json", {**metadata, "snapshot_path": str(Path(snapshot_path).resolve())})
        write_json(run_dir / "evidence.json", evidence)
        write_json(run_dir / "sections.json", sections)
        if client is None and not os.environ.get("OPENAI_API_KEY", "").strip():
            raise ValueError("OPENAI_API_KEY is unavailable")
        manifest["live_model_call_attempted"] = client is None
        manifest["status"] = "generating"
        write_json(run_dir / "run.json", manifest)
        if assembly_mode:
            generated, generation = report_assembly.generate(evidence, profile, client=client, model=model,
                save=lambda name, value: write_json(run_dir / name, value))
        else:
            generated, generation = generate_report(evidence, client=client, model=model, profile=profile)
        write_json(run_dir / "generated.json", generated)
        write_json(run_dir / "generation.json", generation)
        (run_dir / "summary.md").write_text(render_report(generated, evidence), encoding="utf-8")
        # Evaluation fixture is loaded only after generation and is never model input.
        write_json(run_dir / "ground_truth.json", load_report_dataset(profile))
        evaluation = reevaluate(run_dir, profile=profile)
        write_json(run_dir / "review_template.json", {
            item["id"]: {"status": "pending_manual_review", "reviewer": "", "rationale": "",
                         "evidence_ids": list(dict.fromkeys(item["evidence_ids"])), "rubric": item["rubric"]}
            for item in evaluation["manual_reviews"]
        })
        manifest["status"] = "completed_pending_review" if evaluation["automatic_pass"] else "automatic_checks_failed"
        manifest["overall_pass"] = evaluation["overall_pass"]
        write_json(run_dir / "run.json", manifest)
        return run_dir, evaluation
    except Exception as exc:
        manifest.update(status="incomplete", error_type=type(exc).__name__)
        write_json(run_dir / "run.json", manifest)
        # Exceptions may contain HTTP headers; never persist or print their text.
        raise RuntimeError(f"Quarterly report incomplete ({type(exc).__name__}); artifacts: {run_dir}") from None


def run_banking(*, snapshot_path=None, client=None, model=MODEL, reports_dir=None):
    """One bounded M006 attempt using the shared generate() and raw-response saver.

    Live calls additionally require the completed offline gate and an exclusive
    attempt ledger. There is no retry or SEC acquisition path.
    """
    import hashlib
    from src.analytics.jpm_extraction import extract_jpm
    from src.evaluation.ground_truth import load_dataset
    from src.evaluation.jpm_ground_truth import verify_sources
    from src.evaluation.report_evaluation import evaluate_financials, evaluate_banking_response, evaluate_banking_report
    from src.analytics.investor_report import build_banking_presentation, render_banking_main, render_banking_details, digest
    from src.evaluation.investor_report import evaluate_banking_presentation
    os.chdir(ROOT); load_dotenv(ROOT/'.env')
    if client is None:
        gate = load_dataset(ROOT/'data/m006-step4/offline_checks.json')
        if not gate.get('tests_passed') or gate.get('regressions_passed') != 5 or not gate.get('historical_integrity_pass'):
            raise ValueError('Completed offline verification is required')
        if any(hashlib.sha256((ROOT/p).read_bytes()).hexdigest() != sha for p, sha in gate['code_sha256'].items()):
            raise ValueError('Code changed after offline verification')
        if (ROOT/'data/m006-step4/live_attempt.json').exists():
            raise ValueError('The single authorized JPM live attempt is already consumed')
    output = Path(reports_dir or ROOT/'evals/reports/m006/ai') / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'_'+uuid4().hex[:8])
    output.mkdir(parents=True, exist_ok=False)
    def save(name, data):
        with (output/name).open('x', encoding='utf-8', newline='\n') as stream:
            stream.write(json.dumps(data, indent=2, ensure_ascii=False)+'\n')
        if name == 'raw_llm_text.json':
            with (output/'raw_output.txt').open('xb') as stream: stream.write(data.encode('utf-8'))
    initial = {'profile': 'jpm_2026_q2', 'generation_mode': report_assembly.MODE, 'model': model,
        'prompt_version': 'm006-assembly-v1', 'live_model_call_attempted': False, 'status': 'preflight_started'}
    save('run.initial.json', initial)
    attempted = False
    try:
        payload, metadata = load_latest_snapshot('JPM', form='10-Q', accession='0001628280-26-054343', snapshot_path=snapshot_path)
        extraction = extract_jpm(payload, metadata)
        gt = load_dataset(ROOT/'evals/ground_truth/jpm_2026_q2.json'); s = gt['source_snapshot']
        original = verify_sources(gt, payload, metadata, (ROOT/s['filing_detail_path']).read_bytes(),
                                  load_dataset(ROOT/s['filing_detail_metadata_path']))
        evidence = extraction['evidence']; prepared = report_assembly.prepare(evidence, 'jpm_2026_q2')
        financial = evaluate_financials(prepared['financial_foundation'], extraction, gt, payload=payload, metadata=metadata)
        if not original['source_verified'] or not financial['automatic_pass']: raise ValueError('Financial/source preflight failed')
        allowed = report_assembly.allowed_span_ids(prepared, 'jpm_2026_q2')
        schema = report_assembly.schema_for('jpm_2026_q2', allowed)
        # Strict schema is checked offline and retained before any model call.
        save('preflight.json', {'source': original, 'financial': financial, 'eligible_topic_counts': {k:len(v) for k,v in allowed.items()}, 'schema_strict': schema['strict']})
        save('source.json', metadata); save('extraction.json', extraction); save('evidence.json', evidence)
        save('profile.json', get_profile('jpm_2026_q2'))
        with (output/'instructions.txt').open('x', encoding='utf-8') as f: f.write(report_assembly.instructions_for('jpm_2026_q2'))
        if client is None and not os.environ.get('OPENAI_API_KEY', '').strip():
            save('run.json', {**initial, 'status':'credentials_unavailable'}); return output, None
        if client is None:
            with (ROOT/'data/m006-step4/live_attempt.json').open('x', encoding='utf-8') as f:
                json.dump({'run_directory': str(output), 'attempt_count': 1, 'model': model}, f)
        attempted = client is None
        save('attempt.json', {'live_model_call_attempted': attempted, 'generation_attempt_count': 1})
        def validate(raw):
            result = evaluate_banking_response(raw, evidence, extraction, gt, payload=payload, metadata=metadata)
            save('response_evaluation.json', result)
            return result
        report, generation = report_assembly.generate(evidence, 'jpm_2026_q2', client=client, model=model, save=save, validate_raw=validate)
        raw = load_dataset(output/'raw_llm.json')
        evaluation = evaluate_banking_report(report, raw, evidence, extraction, gt, payload=payload, metadata=metadata)
        save('evaluation.json', evaluation)
        if not evaluation['automatic_pass']: raise ValueError('Assembled report evaluation failed')
        view = build_banking_presentation(report, raw, extraction, payload, metadata)
        main = render_banking_main(report, view); detail = render_banking_details(report, view)
        presentation = evaluate_banking_presentation(report, raw, extraction, view, main, detail,
            payload=payload, metadata=metadata, evaluation=evaluation)
        save('presentation_evaluation.json', presentation)
        if not presentation['automatic_pass']: raise ValueError('Presentation evaluation failed')
        save('generated.json', report); save('generation.json', generation); save('presentation.json', view)
        for name, text in (('report.md', main), ('supporting_detail.md', detail)):
            with (output/name).open('xb') as f: f.write(text.encode('utf-8'))
        save('review_template.json', {'status':'pending_manual_review', 'reviewer':'', 'rationale':'',
            'report_sha256':digest(main.encode()), 'supporting_detail_sha256':digest(detail.encode()),
            'criteria':['30-second comprehension and clarity', 'faithful emphasis and comparisons', 'narrative context and citations', 'formatting and completeness']})
        save('semantic_review_template.json', {n:{'status':'pending_manual_review','reviewer':'','rationale':'',
            'evidence_ids':[c['evidence_id'] for c in next(note for note in report['notes'] if note['id']==n)['citations']]}
            for n in get_profile('jpm_2026_q2')['topics']})
        save('run.json', {**initial, 'live_model_call_attempted':attempted, 'status':'completed_pending_review', 'overall_pass':False, **generation})
        return output, evaluation
    except Exception as exc:
        save('run.json', {**initial, 'live_model_call_attempted':attempted, 'status':'failed_preserved',
            'error_type':type(exc).__name__, 'overall_pass':False})
        return output, None


def cli_summary(run_dir, result, profile=None):
    """Project explicit evaluator contracts into the existing CLI display schema.

    JPM separates financial and narrative diagnostics; MSFT/CAT expose financial
    counters at the top level. This does not adapt or change evaluation gates.
    """
    def require(condition, field):
        if not condition: raise ValueError('Missing or invalid ' + field)

    require(isinstance(result, dict), 'evaluation object')
    version = result.get('evaluation_version')
    require(version in ('m003-eval-v1', 'm005-eval-v3', 'm006-ai-eval-v1'), 'evaluation_version')
    banking = version == 'm006-ai-eval-v1'
    if profile is not None:
        expected = ('m006-ai-eval-v1' if profile == 'jpm_2026_q2' else
                    'm005-eval-v3' if profile == 'cat_2026_q1' else 'm003-eval-v1')
        require(version == expected, 'profile/evaluation_version agreement')
    for field in ('automatic_pass', 'overall_pass'):
        require(type(result.get(field)) is bool, field)
    require(not result['overall_pass'] or result['automatic_pass'], 'overall_pass gate consistency')
    financial = result
    if banking:
        financial = result.get('financial')
        require(isinstance(financial, dict), 'financial object')
        require(financial.get('evaluation_version') == 'm006-financial-eval-v1', 'financial.evaluation_version')
        require(type(financial.get('automatic_pass')) is bool, 'financial.automatic_pass')
        narrative = result.get('narrative')
        require(isinstance(narrative, dict) and type(narrative.get('automatic_pass')) is bool, 'narrative.automatic_pass')
        for field in ('source_context_pass', 'assembled_response_match'):
            require(type(result.get(field)) is bool, field)
        require(result['automatic_pass'] == (financial['automatic_pass'] and narrative['automatic_pass']
            and result['source_context_pass'] and result['assembled_response_match']), 'banking gate consistency')
    summary = {'run_dir': str(run_dir)}
    for field in ('financial_values', 'yoy_changes', 'table_evidence_support'):
        counter = financial.get(field)
        require(isinstance(counter, dict) and set(counter) == {'passed', 'total'}
            and type(counter['passed']) is int and type(counter['total']) is int
            and 0 <= counter['passed'] <= counter['total'], field)
        summary[field] = counter
    reviews = result.get('manual_reviews')
    require(isinstance(reviews, list) and bool(reviews), 'manual_reviews')
    require(all(isinstance(r, dict) and isinstance(r.get('id'), str) and r['id']
        and isinstance(r.get('status'), str) and r['status'] for r in reviews), 'manual review entries')
    require(len({r['id'] for r in reviews}) == len(reviews), 'unique manual review IDs')
    summary.update(automatic_pass=result['automatic_pass'], overall_pass=result['overall_pass'],
        manual_reviews={r['id']:r['status'] for r in reviews})
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=tuple(PROFILES), default=None, help="Filing profile; defaults to approved M002, inferred from saved source for re-evaluation")
    parser.add_argument("--snapshot", type=Path, help="Exact cached HTML snapshot (no SEC request)")
    parser.add_argument("--download", action="store_true", help="Fetch the pinned accession from SEC")
    parser.add_argument("--generation-mode", choices=("legacy", report_assembly.MODE), default="legacy")
    parser.add_argument("--model", default=MODEL)
    parser.add_argument("--evaluate-run", type=Path, help="Re-evaluate saved output without model/SEC calls")
    parser.add_argument("--reviews", type=Path, help="Manual review JSON keyed by the three case IDs")
    args = parser.parse_args(argv)
    if args.reviews and not args.evaluate_run:
        parser.error("--reviews requires --evaluate-run")
    if args.evaluate_run and (args.download or args.snapshot):
        parser.error("Re-evaluation does not accept source download/selection options")
    try:
        if args.evaluate_run:
            run_dir = args.evaluate_run
            reviews = json.loads(args.reviews.read_text(encoding="utf-8")) if args.reviews else None
            result = reevaluate(run_dir, reviews=reviews, profile=args.profile)
        else:
            run_dir, result = run_baseline(snapshot_path=args.snapshot, download=args.download, model=args.model, profile=args.profile or DEFAULT_PROFILE, generation_mode=args.generation_mode)
    except (RuntimeError, ValueError, OSError) as exc:
        print(f"Quarterly report could not complete ({type(exc).__name__}). Check the latest run.json and local configuration.", file=sys.stderr)
        return 1
    try:
        summary = cli_summary(run_dir, result, args.profile)
    except ValueError as exc:
        print('Invalid evaluation result contract: ' + str(exc), file=sys.stderr)
        return 1
    print(json.dumps(summary, indent=2))
    return 0 if result["overall_pass"] else (2 if result["automatic_pass"] else 1)


if __name__ == "__main__":
    sys.exit(main())
