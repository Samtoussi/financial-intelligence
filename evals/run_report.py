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
from src.transformation.parse_filings import load_latest_snapshot
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
        _, metadata = load_latest_snapshot(ticker, form="10-Q", accession=report["accession"],
                                           snapshot_path=snapshot_path)
        # Resolve once to an explicit path before any subsequent processing.
        if snapshot_path is None:
            snapshot_path = ROOT / "data/raw/sec/filings" / ticker / report["accession"] / (
                datetime.fromisoformat(metadata["retrieved_at_utc"]).strftime("%Y%m%dT%H%M%SZ")
                + "_" + metadata["sha256"][:12] + ".html")
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
    print(json.dumps({"run_dir": str(run_dir), "financial_values": result["financial_values"],
                      "yoy_changes": result["yoy_changes"], "table_evidence_support": result["table_evidence_support"],
                      "automatic_pass": result["automatic_pass"], "overall_pass": result["overall_pass"],
                      "manual_reviews": {r["id"]: r["status"] for r in result["manual_reviews"]}}, indent=2))
    return 0 if result["overall_pass"] else (2 if result["automatic_pass"] else 1)


if __name__ == "__main__":
    sys.exit(main())
