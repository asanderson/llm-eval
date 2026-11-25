import argparse
import json
from pathlib import Path
from llm_eval.report import write_report
from .experiment import build_report, finalize_campaign
from .publish import publish_report
from .index import write_results_index


def main(argv):
    parser=argparse.ArgumentParser(description='Experiment reports and results pull requests')
    parser.add_argument('command',choices=['report','publish-results','index-results','verify-results','result-inputs'])
    parser.add_argument('--input',type=Path,default=Path('results'))
    parser.add_argument('--output',type=Path,default=Path('results/report'))
    parser.add_argument('--project-root',type=Path,default=Path(__file__).resolve().parents[3])
    parser.add_argument('--include-synthetic',action='store_true')
    parser.add_argument('--publish-pr',action='store_true')
    parser.add_argument('--dry-run',action='store_true')
    parser.add_argument('--prepare-fork',metavar='OWNER/REPO',help='Prepare a verified local branch for a fork pull request')
    parser.add_argument('--job',help='Job ID in a published bundle')
    parser.add_argument('--artifact-dir',type=Path,help='Directory holding a local artifact to verify')
    args=parser.parse_args(argv)
    try:
        if args.prepare_fork and (args.command!='publish-results' or args.dry_run):
            raise ValueError('Use --prepare-fork with publish-results after the publication dry run')
        if args.command=='verify-results':
            from .integrity import verify_results
            print(json.dumps(verify_results(args.project_root),indent=2));return 0
        if args.command=='result-inputs':
            from .reproduction import result_inputs
            print(json.dumps(result_inputs(args.input,args.job,args.artifact_dir),indent=2));return 0
        if args.command=='index-results':
            print(f'Indexed {write_results_index(args.project_root)} published results under docs/results/index');return 0
        if args.command=='publish-results':
            print(json.dumps(publish_report(args.input,args.project_root,args.dry_run,prepare_fork=args.prepare_fork),indent=2));return 0
        if (args.input/'experiment.json').exists():
            report=build_report(args.input);print('Experiment report:',report)
            if args.publish_pr:print(json.dumps(publish_report(report,args.project_root,args.dry_run),indent=2))
        elif (args.input/'campaign.json').exists():
            if args.dry_run or args.publish_pr:
                raise ValueError('Select an experiment directory for explicit publication or publication dry-run')
            print(json.dumps(finalize_campaign(args.input),indent=2))
        else:
            if args.publish_pr:raise ValueError('Publication requires a versioned experiment report')
            rows=write_report(args.input,args.output,args.include_synthetic);print(f'Wrote {len(rows)} cohorts to {args.output}')
        return 0
    except (ValueError,KeyError,OSError,RuntimeError) as exc:parser.exit(2,f'{type(exc).__name__}: {exc}\n')
