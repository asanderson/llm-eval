"""Campaign CLI, shared by the public entry point and compatibility scripts."""
import argparse
import json
from pathlib import Path

from llm_eval.common import read_json
from llm_eval.core.contracts import atomic_json
from llm_eval.experiments import list_experiments
from .planner import compile_campaign
from .scheduler import initialize, run_campaign


def main(argv, root=None):
    parser = argparse.ArgumentParser(description='Run reproducible experiment campaigns')
    parser.add_argument('--project-root', type=Path, default=root or Path(__file__).resolve().parents[3])
    sub = parser.add_subparsers(dest='command', required=True)
    e = sub.add_parser('experiments'); e.add_argument('action', choices=['list'])
    for name in ('plan', 'run', 'setup'):
        p = sub.add_parser(name)
        p.add_argument('--campaign', required=True, type=Path)
        p.add_argument('--max-parallel-jobs', type=int)
        p.add_argument('--output', type=Path, default=Path('results'))
        p.add_argument('--dry-run', action='store_true')
    for name in ('status', 'resume', 'cancel'):
        p = sub.add_parser(name); p.add_argument('--campaign-dir', type=Path, required=True)
        if name == 'resume': p.add_argument('--retry-failed', action='store_true')
    args = parser.parse_args(argv)
    try:
        if args.command == 'experiments':
            print(json.dumps(list_experiments(), indent=2)); return 0
        if args.command in {'status', 'resume', 'cancel'}:
            if args.command == 'status':
                print(json.dumps(read_json(args.campaign_dir / 'campaign.json'), indent=2)); return 0
            if args.command == 'cancel':
                atomic_json(args.campaign_dir / 'cancel.json', {'cancel': True}); return 0
            return run_campaign(args.campaign_dir, args.retry_failed)
        plan = compile_campaign(args.campaign, args.project_root, args.max_parallel_jobs)
        if args.command == 'plan' or args.dry_run:
            print(json.dumps(plan, indent=2)); return 0
        if args.command == 'setup':
            from .setup import setup_campaign
            return setup_campaign(plan)
        directory = initialize(plan, args.output)
        print('Campaign results:', directory)
        return run_campaign(directory)
    except (ValueError, KeyError, OSError, RuntimeError) as exc:
        parser.exit(2, f'{type(exc).__name__}: {exc}\n')


def interactive(root):
    print('Available experiments: ' + ', '.join(x['id'] for x in list_experiments()))
    path = input('Campaign JSON path: ').strip()
    if not path:
        raise ValueError('Supply a campaign file')
    parallel = int(input('Maximum parallel jobs [1]: ').strip() or '1')
    plan = compile_campaign(path, root, parallel)
    print(json.dumps(plan, indent=2))
    if input('Run this campaign? [y/N]: ').strip().lower() not in {'y', 'yes'}:
        return 0
    return run_campaign(initialize(plan, Path('results')))
