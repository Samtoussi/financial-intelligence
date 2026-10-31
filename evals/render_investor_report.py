"""Render a saved, reviewed quarterly report offline without rewriting its inputs."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.analytics.investor_report import write_presentation


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--output-root', type=Path, default=ROOT / 'evals/reports/m004')
    parser.add_argument('--pending-review-draft', action='store_true',
                        help='M005 only: render an automatically passing draft with human reviews visibly pending')
    args = parser.parse_args(argv)
    try:
        directory, result = write_presentation(args.run, args.output_root,
                                             allow_pending_review=args.pending_review_draft)
    except (ValueError, OSError) as exc:
        print(f'M004 presentation blocked: {exc}', file=sys.stderr)
        return 1
    print(json.dumps({'output_directory': str(directory), **result}, indent=2))
    return 2  # Automatic checks passed; M004 human review is still pending.


if __name__ == '__main__':
    sys.exit(main())
