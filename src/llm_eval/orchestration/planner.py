"""Resolve experiment matrices without installs, launches or downloads."""
from __future__ import annotations

import copy
from pathlib import Path
import subprocess

from llm_eval.common import read_json, sha256_file
from llm_eval.core.contracts import fields, identifier, integer, no_credentials, config_hash
from llm_eval.experiments import get_experiment

PATH_KEYS = {'suite', 'artifact_root', 'artifact_lock', 'offload_dir', 'installation_state', 'replay', 'data', 'benchmark_registry'}


def resolve_paths(value, directory):
    if isinstance(value, dict):
        return {k: str((directory / v).resolve()) if k in PATH_KEYS and isinstance(v, str)
                else resolve_paths(v, directory) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve_paths(v, directory) for v in value]
    return value


def revision(root):
    p = subprocess.run(['git', '-C', str(root), 'rev-parse', 'HEAD'], capture_output=True, text=True, check=True)
    return p.stdout.strip()


def compile_campaign(path, root, max_parallel_jobs=None):
    path, root = Path(path).resolve(), Path(root).resolve()
    c = read_json(path)
    fields(c, {'schema_version', 'id', 'inventory', 'execution', 'phases', 'reporting'},
           ['schema_version', 'id', 'inventory', 'phases'])
    if c['schema_version'] != 2:
        raise ValueError('Campaign schema_version must be 2')
    identifier(c['id']); no_credentials(c)
    inv_path = (path.parent / c['inventory']).resolve()
    inv = read_json(inv_path)
    fields(inv, {'targets', 'hardware_configs'}, ['targets', 'hardware_configs']); no_credentials(inv)
    execution = {'max_parallel_jobs': 1, 'measurement_isolation': 'physical-host', 'on_failure': 'continue-independent', **c.get('execution', {})}
    fields(execution, {'max_parallel_jobs', 'measurement_isolation', 'on_failure', 'api_budget_usd'})
    if max_parallel_jobs is not None:
        execution['max_parallel_jobs'] = max_parallel_jobs
    integer(execution['max_parallel_jobs'], 'max_parallel_jobs', high=256)
    if execution['measurement_isolation'] != 'physical-host':
        raise ValueError('Only isolated physical-host scheduling is supported')
    if execution['on_failure'] not in {'continue-independent', 'fail-fast'}:
        raise ValueError('Invalid on_failure policy')
    inputs = {str(path): sha256_file(path), str(inv_path): sha256_file(inv_path)}
    phases, jobs, experiments = {}, [], []
    if not isinstance(c['phases'], list) or not c['phases']:
        raise ValueError('Campaign needs at least one phase')
    for phase in c['phases']:
        fields(phase, {'id', 'depends_on', 'experiments'}, ['id', 'experiments'])
        phase_id = identifier(phase['id'])
        if phase_id in phases or not phase['experiments']:
            raise ValueError('Duplicate phase or empty experiments')
        deps = phase.get('depends_on', [])
        if not isinstance(deps, list) or any(d not in phases for d in deps):
            raise ValueError('Phase dependencies must reference earlier phases')
        phase_jobs = []
        for index, selection in enumerate(phase['experiments']):
            fields(selection, {'id', 'version', 'mode', 'cases', 'hardware_configs'}, ['id', 'version', 'cases', 'hardware_configs'])
            experiment = get_experiment(selection['id'])
            manifest = experiment.MANIFEST
            mode = selection.get('mode', manifest['modes'][0])
            if selection['version'] != manifest['version'] or mode not in manifest['modes']:
                raise ValueError('Unsupported experiment version or mode')
            if not selection['cases'] or not selection['hardware_configs']:
                raise ValueError('Empty experiment selection')
            run_id = f'{phase_id}-{selection["id"]}-{index + 1}'
            exp = {'experiment_run_id': run_id, 'experiment_id': selection['id'], 'version': selection['version'], 'mode': mode, 'job_ids': []}
            experiments.append(exp)
            bundle = root / 'experiments' / selection['id'] / 'experiment.json'
            bundled = read_json(bundle)
            inputs[str(bundle)] = sha256_file(bundle)
            seen = set()
            for case_name in selection['cases']:
                case_ref = bundled.get('cases', {}).get(case_name, case_name)
                case_path = (bundle.parent / case_ref).resolve() if case_name in bundled.get('cases', {}) else (path.parent / case_ref).resolve()
                case = read_json(case_path)
                inputs[str(case_path)] = sha256_file(case_path)
                case_id = identifier(case.get('id', case_path.stem))
                fields(case, {'id', 'parameters'}, ['parameters'])
                params = resolve_paths(case['parameters'], case_path.parent)
                if isinstance(params.get('config'), str):
                    config_path = (case_path.parent / params['config']).resolve()
                    params['config'] = resolve_paths(read_json(config_path), config_path.parent)
                    inputs[str(config_path)] = sha256_file(config_path)
                no_credentials(params)
                for hardware_id in selection['hardware_configs']:
                    identifier(hardware_id)
                    if hardware_id not in inv['hardware_configs']:
                        raise ValueError('Unknown hardware configuration: ' + hardware_id)
                    hardware = copy.deepcopy(inv['hardware_configs'][hardware_id])
                    fields(hardware, {'target', 'hardware_profile', 'os_id', 'overrides', 'attestation'}, ['target', 'hardware_profile', 'os_id'])
                    target_id = identifier(hardware['target'])
                    if target_id not in inv['targets']:
                        raise ValueError('Unknown execution target')
                    target = copy.deepcopy(inv['targets'][target_id])
                    fields(target, {'transport', 'physical_host_id', 'host', 'python', 'repo_root', 'work_root', 'path_mappings', 'lock_root', 'available', 'resource_hosts', 'max_collection_bytes'}, ['transport', 'physical_host_id'])
                    identifier(target['physical_host_id'])
                    if target['transport'] not in {'local', 'ssh'}:
                        raise ValueError('Transport must be local or ssh')
                    if target['transport'] == 'ssh' and not all(target.get(k) for k in ('host', 'python', 'repo_root', 'work_root')):
                        raise ValueError('SSH targets require host, python, repo_root and work_root')
                    profile_path = root / 'configs/hardware' / (identifier(hardware['hardware_profile']) + '.json')
                    profile = read_json(profile_path); inputs[str(profile_path)] = sha256_file(profile_path)
                    bound = copy.deepcopy(params)
                    if 'config' in bound:
                        overrides = hardware.get('overrides', {})
                        fields(overrides, {'ram_budget_gib', 'gpu_budget_gib', 'context_tokens', 'max_output_tokens', 'launch'})
                        bound['config'].update(overrides, hardware_profile=hardware['hardware_profile'], os_id=hardware['os_id'])
                        if hardware.get('attestation'):
                            bound['config']['hardware_attestation'] = hardware['attestation']
                    reason = experiment.validate(bound, root, mode)
                    signature = [case_id, hardware_id]
                    if tuple(signature) in seen:
                        raise ValueError('Duplicate case/hardware selection')
                    seen.add(tuple(signature))
                    jid = f'{run_id}-{config_hash(signature)[:12]}'
                    job = {'schema_version': 2, 'job_id': jid, 'experiment_run_id': run_id, 'experiment_id': selection['id'],
                           'experiment_version': selection['version'], 'mode': mode, 'case_id': case_id,
                           'hardware_config_id': hardware_id, 'hardware': hardware, 'hardware_profile': profile,
                           'target_id': target_id, 'target': target, 'parameters': bound,
                           'depends_on': [j for d in deps for j in phases[d]],
                           'resources': sorted(set([target['physical_host_id'], *target.get('resource_hosts', [])])),
                           'status': 'skipped' if reason else 'planned', 'reason': reason}
                    if target.get('available') is False and not reason:
                        job.update(status='blocked', reason='target_unavailable')
                    job['config_sha256'] = config_hash(job)
                    jobs.append(job); phase_jobs.append(jid); exp['job_ids'].append(jid)
            phases[phase_id] = phase_jobs
    def hash_inputs(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key in PATH_KEYS and isinstance(item, str) and Path(item).is_file(): inputs[item] = sha256_file(item)
                else: hash_inputs(item)
        elif isinstance(value, list):
            for item in value: hash_inputs(item)
    for job in jobs:
        before=set(inputs)
        hash_inputs(job['parameters'])
        job['input_files']=[{'path':p,'sha256':sha} for p,sha in inputs.items() if p in set(inputs)-before]
        # Include shared workload files even when another job already recorded them.
        def job_files(value):
            if isinstance(value,dict):
                for key,item in value.items():
                    if key in PATH_KEYS and isinstance(item,str) and Path(item).is_file():
                        if not any(f['path']==item for f in job['input_files']):job['input_files'].append({'path':item,'sha256':sha256_file(item)})
                    else:job_files(item)
            elif isinstance(value,list):
                for item in value:job_files(item)
        job_files(job['parameters'])
        for candidate in job['parameters'].get('candidates',{}).values():
            if candidate.get('target_id'):
                role_target=inv['targets'][candidate['target_id']]
                job['resources'].append(identifier(role_target['physical_host_id']))
        job['resources']=sorted(set(job['resources']))
    total_api_reservation = sum(j['parameters'].get('budget_usd', 0) for j in jobs if j['status'] != 'skipped')
    if 'api_budget_usd' in execution:
        from llm_eval.common import finite_number
        finite_number(execution['api_budget_usd'], 'api_budget_usd', 0)
        if total_api_reservation > execution['api_budget_usd']:raise ValueError('Sum of job API budgets exceeds the campaign cap')
    reporting = c.get('reporting', {'on_experiment_end': True})
    fields(reporting, {'on_experiment_end', 'raw_format', 'summary_formats', 'publish', 'include_outputs', 'max_artifact_bytes'})
    if reporting.get('raw_format', 'jsonl.gz') != 'jsonl.gz':raise ValueError('raw_format must be jsonl.gz')
    if set(reporting.get('summary_formats', ['markdown','json','csv'])) != {'markdown','json','csv'}:raise ValueError('Reports require markdown, json and csv summaries')
    publication=reporting.get('publish',{})
    fields(publication, {'mode','repository','base_branch','docs_root'})
    if publication.get('mode','none') not in {'none','pull-request'}:raise ValueError('Invalid publication mode')
    if publication.get('docs_root','docs/results') != 'docs/results':raise ValueError('Results destination must be docs/results')
    integer(reporting.get('max_artifact_bytes', 40*1024*1024), 'max_artifact_bytes', high=500*1024*1024)
    plan = {'schema_version': 2, 'campaign_id': c['id'], 'source': str(path), 'root': str(root),
            'code_revision': revision(root), 'total_api_reservation_usd': total_api_reservation, 'inputs': inputs, 'execution': execution, 'reporting': reporting,
            'experiments': experiments, 'jobs': jobs, 'targets': inv['targets']}
    plan['plan_sha256'] = config_hash(plan)
    return plan
