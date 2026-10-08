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
        p.add_argument('--platform')
        p.add_argument('--os')
        p.add_argument('--project-root', type=Path, default=argparse.SUPPRESS)
    for name in ('status', 'resume', 'cancel'):
        p = sub.add_parser(name); p.add_argument('--campaign-dir', type=Path, required=True)
        if name == 'resume':
            p.add_argument('--retry-failed', action='store_true')
            p.add_argument('--enable-target', action='append', default=[], help='Admit a previously unavailable target after bringing it online')
    args = parser.parse_args(argv)
    try:
        if args.command == 'experiments':
            print(json.dumps(list_experiments(), indent=2)); return 0
        if args.command in {'status', 'resume', 'cancel'}:
            if args.command == 'status':
                print(json.dumps(read_json(args.campaign_dir / 'campaign.json'), indent=2)); return 0
            if args.command == 'cancel':
                atomic_json(args.campaign_dir / 'cancel.json', {'cancel': True}); return 0
            return run_campaign(args.campaign_dir, args.retry_failed, args.enable_target)
        plan = compile_campaign(args.campaign, args.project_root, args.max_parallel_jobs)
        for job in plan['jobs']:
            platform = job['parameters'].get('config', {}).get('platform') or job['parameters'].get('router', {}).get('platform')
            if args.platform and platform != args.platform: raise ValueError('Campaign conflicts with wrapper platform')
            if args.os and job['hardware']['os_id'] != args.os: raise ValueError('Campaign conflicts with wrapper OS')
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


def interactive(root, action='run'):
    import os
    from llm_eval.core.contracts import identifier
    registry={x['id']:x for x in list_experiments()}
    def choose(label,options,default=None):
        print(label+': '+', '.join(options))
        value=input('Selection ['+(default or options[0])+']: ').strip() or default or options[0]
        values=[v.strip() for v in value.split(',')]
        if not values or any(v not in options for v in values):raise ValueError('Unknown selection')
        return list(dict.fromkeys(values))
    experiments=choose('Experiments',list(registry))
    inventory=Path(input('Inventory JSON [configs/targets/local.example.json]: ').strip() or 'configs/targets/local.example.json').resolve()
    inv=read_json(inventory)
    selections=[]
    for name in experiments:
        manifest=read_json(Path(root)/'experiments'/name/'experiment.json')
        cases=list(manifest['cases'])
        if cases: selected=choose(name+' cases',cases)
        else:selected=[str(Path(x.strip()).resolve()) for x in input('Case JSON paths, comma separated: ').split(',')]
        mode=choose(name+' mode',registry[name]['modes'])[0]
        hardware=choose(name+' hardware configurations',list(inv['hardware_configs']))
        selections.append({'id':name,'version':registry[name]['version'],'mode':mode,'cases':selected,'hardware_configs':hardware})
    parallel=int(input('Maximum parallel experiment jobs [1]: ').strip() or '1')
    sequential=input('Run experiments in sequence? [Y/n]: ').strip().lower()!='n'
    phases=[]
    for i,selection in enumerate(selections):
        phases.append({'id':'phase-'+str(i+1),'experiments':[selection],
                       'depends_on':['phase-'+str(i)] if sequential and i else []})
    path=Path(input('Save campaign [configs/local/campaign.json]: ').strip() or 'configs/local/campaign.json').resolve()
    if path.exists():raise ValueError('Choose a new campaign filename; existing configuration was preserved')
    campaign={'schema_version':2,'id':identifier(path.stem),'inventory':os.path.relpath(inventory,path.parent),
              'execution':{'max_parallel_jobs':parallel},'phases':phases,'reporting':{'on_experiment_end':True}}
    if input('Automatically push results pull requests? [y/N]: ').strip().lower() in {'y','yes'}:
        campaign['reporting']['publish']={'mode':'pull-request','repository':'asanderson/llm-eval','base_branch':'main'}
    atomic_json(path,campaign)
    plan=compile_campaign(path,root);print(json.dumps(plan,indent=2))
    if input(action.capitalize()+' this campaign? [y/N]: ').strip().lower() not in {'y','yes'}:return 0
    if action=='setup':
        from .setup import setup_campaign
        return setup_campaign(plan)
    return run_campaign(initialize(plan,Path('results')))
