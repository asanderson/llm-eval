"""Durable campaign execution. Jobs and attempts have independent identities."""
from __future__ import annotations

import datetime
from pathlib import Path
import uuid

from llm_eval.common import read_json
from llm_eval.core.contracts import atomic_json, TERMINAL
from llm_eval.experiments import get_experiment


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def initialize(plan, output):
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    directory = Path(output).resolve() / ('campaign-' + stamp + '-' + uuid.uuid4().hex[:8])
    directory.mkdir(parents=True)
    atomic_json(directory / 'plan.json', plan)
    state = {'schema_version': 2, 'campaign_id': plan['campaign_id'], 'created_utc': utc_now(),
             'status': 'ready', 'jobs': {j['job_id']: {'status': j['status'], 'reason': j['reason'], 'attempts': []} for j in plan['jobs']},
             'reports': {}}
    atomic_json(directory / 'campaign.json', state)
    for exp in plan['experiments']:
        atomic_json(directory / 'experiments' / exp['experiment_run_id'] / 'experiment.json',
                    {**exp, 'campaign_id': plan['campaign_id'], 'code_revision': plan['code_revision']})
    return directory


def run_campaign(directory):
    directory = Path(directory).resolve()
    plan = read_json(directory / 'plan.json')
    state = read_json(directory / 'campaign.json')
    state['status'] = 'running'
    for job in plan['jobs']:
        record = state['jobs'][job['job_id']]
        if record['status'] in TERMINAL:
            continue
        if any(state['jobs'][d]['status'] != 'succeeded' for d in job['depends_on']):
            record.update(status='blocked', reason='dependency_not_succeeded')
            continue
        if job['target']['transport'] != 'local':
            record.update(status='blocked', reason='remote_executor_required')
            continue
        aid = uuid.uuid4().hex
        out = directory / 'experiments' / job['experiment_run_id'] / 'jobs' / job['job_id'] / aid
        out.mkdir(parents=True)
        attempt = {'attempt_id': aid, 'status': 'running', 'started_utc': utc_now(), 'output': str(out.relative_to(directory))}
        record['attempts'].append(attempt); record['status'] = 'running'
        atomic_json(out / 'job.json', job); atomic_json(directory / 'campaign.json', state)
        try:
            result = get_experiment(job['experiment_id']).execute(job, out, Path(plan['root']))
        except KeyboardInterrupt:
            result = {'status': 'cancelled'}
        except Exception as exc:
            result = {'status': 'failed', 'error_type': type(exc).__name__}
        result.update(finished_utc=utc_now(), attempt_id=aid)
        atomic_json(out / 'result.json', result)
        attempt.update(result); record['status'] = result['status']
        atomic_json(directory / 'campaign.json', state)
        if result['status'] == 'cancelled' or (result['status'] == 'failed' and plan['execution']['on_failure'] == 'fail-fast'):
            break
    statuses = {r['status'] for r in state['jobs'].values()}
    state['status'] = 'succeeded' if statuses <= {'succeeded', 'skipped'} else 'incomplete'
    atomic_json(directory / 'campaign.json', state)
    return 0 if state['status'] == 'succeeded' else 1
