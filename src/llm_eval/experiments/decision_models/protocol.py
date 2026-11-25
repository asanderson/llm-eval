"""Prepare matched campaign arms, freeze fixed live outcomes, and compare paired tasks."""
import argparse
import json
from collections import defaultdict
from pathlib import Path
from random import Random

from llm_eval.common import read_json, write_json
from llm_eval.core.contracts import identifier
from llm_eval.orchestration.planner import resolve_paths
from llm_eval.report import quantile
from llm_eval.runner import load_suite
from .evaluation import candidate_fingerprint, generation_settings
from .metrics import average, first_measured
from .workload import selected_tasks


def prepare(case, keywords, inventory, hardware, mode, split, out, replay=None, task_ids=None, fixed_only=False):
    case = Path(case).resolve()
    config = resolve_paths(read_json(case)['parameters'], case.parent)
    config['split'] = split
    config.pop('replay', None)
    if task_ids is not None:
        config['task_ids'] = task_ids
    selected_tasks(load_suite(config['suite']), config)
    if replay:
        config['replay'] = str(Path(replay).resolve())
    if (mode == 'replay') != bool(replay):
        raise ValueError('Supply --replay exactly when preparing replay mode')
    if fixed_only and mode != 'live':
        raise ValueError('--fixed-only is for live outcome collection')
    routers = {'routed': config['router'], 'keyword': read_json(keywords)}
    if routers['keyword'].get('kind') != 'category':
        raise ValueError('The keyword arm needs a category router')
    if mode == 'decision' and routers['routed']['kind'] == 'systemone':
        original = routers['routed']
        routers['reversed-criteria'] = {**original, 'criteria': dict(reversed(original['criteria'].items()))}
    if fixed_only:
        routers = {}
    if mode != 'decision':
        for candidate in config['candidates']:
            routers['fixed-' + identifier(candidate)] = {'kind': 'fixed', 'choice': candidate}
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    for arm, router in routers.items():
        params = {**config, 'router': router}
        if arm.startswith('fixed-'):
            params['policy'] = {'objective': config.get('policy', {}).get('objective', {})}
        write_json(out / (arm + '.json'), {'id': arm, 'parameters': params})
    selection = {'id': 'decision-models', 'version': 1, 'mode': mode,
                 'cases': [arm + '.json' for arm in routers], 'hardware_configs': [hardware]}
    write_json(out / 'campaign.json', {
        'schema_version': 2, 'id': 'routing-' + split + '-' + mode,
        'inventory': str(Path(inventory).resolve()), 'phases': [{'id': 'study', 'experiments': [selection]}],
    })


def load_arms(directory):
    """Read the latest attempt of each arm using the scheduler's recorded paths."""
    directory = Path(directory).resolve()
    plan = read_json(directory / 'plan.json')
    state = read_json(directory / 'campaign.json')
    arms = {}
    for job in plan['jobs']:
        arm = job['case_id']
        if job['experiment_id'] != 'decision-models' or arm in arms:
            raise ValueError('Expected a single decision-models job per arm')
        attempts = state['jobs'][job['job_id']]['attempts']
        if not attempts:
            raise ValueError('No recorded attempt for ' + arm)
        path = (directory / attempts[-1]['output']).resolve()
        if not path.is_relative_to(directory):
            raise ValueError('Attempt path escapes the campaign')
        meta = read_json(path / 'routing-metadata.json')
        if meta['status'] == 'running':
            raise ValueError('Finish the campaign before comparing arms')
        config = meta['config']
        rows = [json.loads(line) for line in (path / 'requests.jsonl').read_text(encoding='utf-8').splitlines() if line]
        arms[arm] = {'mode': meta['mode'], 'tasks': first_measured(rows), 'config': config,
                     'suite_sha256': meta['suite_sha256'], 'policy_sha256': meta['policy_sha256'],
                     'hardware_config_id': job['hardware_config_id'], 'synthetic': meta['synthetic'],
                     'code_revision': plan['code_revision']}
    if not arms:
        raise ValueError('Empty campaign')
    return arms


def cohort(arm):
    config = arm['config']
    return {'suite_sha256': arm['suite_sha256'], 'hardware_config_id': arm['hardware_config_id'],
            'split': config.get('split'), 'synthetic': arm['synthetic'], 'generation': generation_settings(config),
            'candidate_fingerprints': {k: candidate_fingerprint(v) for k, v in config['candidates'].items()}}


def freeze(arms):
    first = next(iter(arms.values()))
    common = cohort(first)
    result = {**common, 'code_revision': first['code_revision'], 'rows': []}
    for candidate in common['candidate_fingerprints']:
        arm = arms.get('fixed-' + candidate)
        if (not arm or cohort(arm) != common or arm['mode'] != 'live'
                or arm['config']['router'] != {'kind': 'fixed', 'choice': candidate}):
            raise ValueError('Missing or mismatched fixed live arm: ' + candidate)
        for task, row in sorted(arm['tasks'].items()):
            if row['status'] != 'ok' or row.get('selected_model') != candidate or row.get('fallback_used'):
                continue
            quality = row.get('quality_pass')
            result['rows'].append({'task_id': task, 'candidate': candidate, 'prompt_sha256': row['prompt_sha256'],
                                   'quality': int(quality) if isinstance(quality, bool) else None,
                                   'latency_s': row.get('generation_s'), 'cost_usd': row.get('cost_usd')})
    return result


def observations(row, mode):
    replay = mode == 'replay'
    quality = row.get('quality') if replay else row.get('quality_pass')
    return {'quality': int(quality) if isinstance(quality, bool) else quality,
            'end_to_end_s': row.get('estimated_end_to_end_s' if replay else 'elapsed_s'),
            'api_usd': row.get('estimated_total_cost_usd' if replay else 'total_cost_usd')}


def paired_mean(differences, families):
    """Resample intact families with replacement and retain the task-weighted paired mean."""
    interval = None
    groups = defaultdict(list)
    for family, delta in zip(families, differences):
        groups[family].append(delta)
    blocks = list(groups.values())
    if len(blocks) >= 2:
        random = Random(1)
        draws = []
        for _ in range(1000):
            sample = random.choices(blocks, k=len(blocks))
            draws.append(sum(sum(block) for block in sample) / sum(len(block) for block in sample))
        interval = [quantile(draws, .025), quantile(draws, .975)]
    return {'tasks': len(differences), 'mean_difference': average(differences), 'families': len(blocks), 'paired_family_bootstrap_95': interval}


def compare(arms, live=None):
    routed = arms['routed']
    if routed['mode'] not in {'live', 'replay'}:
        raise ValueError('Compare downstream replay or live arms')
    labels = list(arms)
    if live is not None:
        if routed['mode'] != 'replay' or set(live) != set(arms):
            raise ValueError('Pair every replay arm with its matching live arm')
        for name, arm in live.items():
            ref = arms[name]
            if (arm['mode'] != 'live' or cohort(arm) != cohort(ref)
                    or arm['config']['router'] != ref['config']['router']
                    or list(arm['config']['router'].get('criteria', {})) != list(ref['config']['router'].get('criteria', {}))
                    or arm['policy_sha256'] != ref['policy_sha256']):
                raise ValueError('Replay and live settings differ for ' + name)
    if any(cohort(arm) != cohort(routed) or arm['mode'] != routed['mode'] for arm in arms.values()):
        raise ValueError('Cannot pair different suites, splits, candidates, hardware, or generation settings')
    selected = live if live is not None else arms
    task_ids = sorted(set().union(*(arm['tasks'] for arm in selected.values())))
    panels = []
    for task in task_ids:
        values = {}
        prompt_hashes = set()
        families = set()
        for mode_arms in (arms, live) if live is not None else (arms,):
            for name, arm in mode_arms.items():
                row = arm['tasks'].get(task)
                if row is not None:
                    prompt_hashes.add(row['prompt_sha256'])
                    families.add(row.get('task_family', task))
                key = arm['mode'] + '/' + name
                ok = row and row['status'] == 'ok'
                values[key] = {'status': row['status'] if row else 'absent',
                               'selected_model': row.get('selected_model') if row else None,
                               'abstained': row.get('abstained') if row else None,
                               'fallback_used': row.get('fallback_used') if row else None,
                               'router_s': row.get('router_s') if row else None,
                               'oracle_regret': row.get('oracle_regret') if row else None,
                               **(observations(row, arm['mode']) if ok else {})}
        if len(prompt_hashes) != 1 or len(families) != 1:
            raise ValueError('Paired prompt hash mismatch: ' + task)
        panels.append({'task_id': task, 'family': families.pop(), 'prompt_sha256': prompt_hashes.pop(), 'arms': values})
    pairs = [(routed['mode'] + '/routed', routed['mode'] + '/' + other) for other in labels if other != 'routed']
    if live is not None:
        pairs.extend([('live/' + name, 'replay/' + name) for name in labels])
        pairs.extend([('live/routed', 'live/' + other) for other in labels if other != 'routed'])
    comparisons = {}
    for metric in ('quality', 'end_to_end_s', 'api_usd'):
        complete = [task for task in panels if all(a.get(metric) is not None for a in task['arms'].values())]
        shared = [task['arms'] for task in complete]
        families = [task['family'] for task in complete]
        comparisons[metric] = {
            'common_tasks': len(shared),
            'common_task_means': {name: average([panel[name][metric] for panel in shared])
                                  for name in panels[0]['arms']} if panels else {},
            'differences': [{'arm': name, 'reference': reference,
                             **paired_mean([p[name][metric] - p[reference][metric] for p in shared], families)}
                            for name, reference in pairs]}
    tradeoffs = {}
    for resource in ('end_to_end_s', 'api_usd'):
        common = [p for p in panels if all(a.get('quality') is not None and a.get(resource) is not None
                                            for a in p['arms'].values())]
        tradeoffs[resource] = {'common_tasks': len(common), 'means': {
            name: {key: average([task['arms'][name][key] for task in common]) for key in ('quality', resource)}
            for name in panels[0]['arms']} if panels else {}}
    coverage = {}
    if panels:
        for name in panels[0]['arms']:
            entries = [task['arms'][name] for task in panels]
            coverage[name] = {'tasks': len(entries), 'successful_tasks': sum(e['status'] == 'ok' for e in entries),
                              'unknown_api_cost_tasks': sum(e.get('api_usd') is None for e in entries),
                              'fallback_tasks': sum(bool(e['fallback_used']) for e in entries),
                              'abstentions': sum(bool(e['abstained']) for e in entries)}
    return {'quality_resource_tradeoffs': tradeoffs, 'coverage': coverage, 'unit': 'first measured repetition per task', 'cohort': cohort(routed), 'candidate_tasks': len(task_ids),
            'comparisons': comparisons, 'tasks': panels}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    prepare_cmd = commands.add_parser('prepare')
    for key in ('case', 'keywords', 'inventory', 'hardware', 'out'):
        prepare_cmd.add_argument('--' + key, required=True)
    prepare_cmd.add_argument('--mode', choices=['decision', 'replay', 'live'], required=True)
    prepare_cmd.add_argument('--split', choices=['development', 'test'], required=True)
    prepare_cmd.add_argument('--fixed-only', action='store_true')
    prepare_cmd.add_argument('--task-ids', nargs='+')
    prepare_cmd.add_argument('--replay')
    for command in ('freeze', 'compare'):
        cmd = commands.add_parser(command)
        cmd.add_argument('--campaign-dir', required=True)
        cmd.add_argument('--out', required=True)
        if command == 'compare':
            cmd.add_argument('--paired-live')
    args = vars(parser.parse_args())
    command = args.pop('command')
    if command == 'prepare':
        prepare(**args)
    else:
        arms = load_arms(args['campaign_dir'])
        result = freeze(arms) if command == 'freeze' else compare(arms, load_arms(args['paired_live']) if args['paired_live'] else None)
        write_json(args['out'], result)


if __name__ == '__main__':
    main()
