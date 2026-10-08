import argparse
import json
from pathlib import Path
from llm_eval.report import write_report
from .experiment import build_report, finalize_campaign
from .publish import publish_report


def main(argv):
    parser=argparse.ArgumentParser(description='Experiment reports and results pull requests')
    parser.add_argument('command',choices=['report','publish-results'])
    parser.add_argument('--input',type=Path,default=Path('results'))
    parser.add_argument('--output',type=Path,default=Path('results/report'))
    parser.add_argument('--project-root',type=Path,default=Path(__file__).resolve().parents[3])
    parser.add_argument('--include-synthetic',action='store_true')
    parser.add_argument('--publish-pr',action='store_true')
    parser.add_argument('--dry-run',action='store_true')
    args=parser.parse_args(argv)
    try:
        if args.command=='publish-results':
            print(json.dumps(publish_report(args.input,args.project_root,args.dry_run),indent=2));return 0
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
