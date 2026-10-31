"""Read-only CAT diagnostic; writes a new output, never re-evaluates in place."""
import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.ai.report_assembly import assemble, prepare
from src.analytics.report_evidence import build_report_evidence
from src.analytics.report_profiles import profile_for_accession
from src.evaluation.report_evaluation import evaluate_report


def diagnose(run, output_root):
    run, output_root = Path(run).resolve(), Path(output_root).resolve()
    if run == output_root or run.is_relative_to(output_root) or output_root.is_relative_to(run):
        raise ValueError('Diagnostic output must be separate from the input run')
    blobs = {p.name: p.read_bytes() for p in run.iterdir() if p.is_file()}
    hashes = {name: hashlib.sha256(value).hexdigest() for name, value in blobs.items()}
    read = lambda name: json.loads(blobs[name].decode('utf-8'))
    source = read('source.json')
    profile = profile_for_accession(source['accession'])
    if profile != 'cat_2026_q1':
        raise ValueError('This diagnostic supports only the pinned M005 CAT run')
    evidence = read('evidence.json')
    if evidence != build_report_evidence(read('sections.json'), source, profile=profile):
        raise ValueError('Source/evidence reconstruction failed')
    if prepare(evidence, profile) != read('assembly_inputs.json'):
        raise ValueError('Source/registry reconstruction failed')
    if json.loads(read('raw_llm_text.json')) != read('raw_llm.json'):
        raise ValueError('Raw narrative records disagree')
    report = read('generated.json')
    assembly_error = None
    try:
        rebuilt = assemble(read('raw_llm.json'), evidence, profile, read('assembly_inputs.json'))
        if rebuilt != report:
            raise ValueError('Saved report differs from reconstructed assembly')
    except ValueError as exc:
        if not str(exc).startswith('Unsupported narrative monetary units:'):
            raise
        assembly_error = str(exc)
    result = evaluate_report(report, evidence, read('ground_truth.json'),
        source_sha256=source['sha256'], profile=profile,
        reviews=read('review.json') if 'review.json' in blobs else None)
    # Snapshot every input file, including any existing human review records.
    if hashes != {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in run.iterdir() if p.is_file()}:
        raise ValueError('Input changed during diagnostic')
    output = output_root / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '_' + uuid4().hex[:8])
    output.mkdir(parents=True, exist_ok=False)
    diagnostic = {'diagnostic_version': 'm005-unit-diagnostic-v1', 'profile': profile,
        'input_directory': str(run), 'input_sha256': hashes,
        'saved_evaluation_version': read('evaluation.json')['evaluation_version'],
        'saved_automatic_pass': read('evaluation.json')['automatic_pass'],
        'assembly_rejected': assembly_error is not None, 'assembly_error': assembly_error,
        'current_automatic_pass': result['automatic_pass'], 'current_overall_pass': result['overall_pass'],
        'historical_inputs_unchanged': True, 'human_reviews_modified': False}
    for name, data in (('evaluation.json', result), ('diagnostic.json', diagnostic)):
        (output / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return output, diagnostic


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--output-root', type=Path, default=ROOT / 'evals/reports/m005/unit-diagnostics')
    args = parser.parse_args(argv)
    output, diagnostic = diagnose(args.run, args.output_root)
    print(json.dumps({'output_directory': str(output), **{k: diagnostic[k] for k in (
        'assembly_rejected', 'current_automatic_pass', 'current_overall_pass', 'historical_inputs_unchanged')}}, indent=2))
    return 0 if diagnostic['current_automatic_pass'] else 1


if __name__ == '__main__':
    sys.exit(main())
