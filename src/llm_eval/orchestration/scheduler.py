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


def _targets(job, plan):
    by_host={t['physical_host_id']:t for t in plan.get('targets',{}).values()}
    by_host.update({j['target']['physical_host_id']:j['target'] for j in plan['jobs']})
    by_host[job['target']['physical_host_id']]=job['target']
    if set(job['resources'])-set(by_host):
        raise ValueError('Every reserved resource host must have a target in this campaign')
    return [by_host[h] for h in job['resources']]


def _reserve(job, attempt, plan):
    from .resources import reserve, lock_root
    from .transport import rpc
    owner=attempt['attempt_id']
    # The caller journals this intent first. A lost reply may have acquired the
    # worker reservation, so retain its owner until cleanup is confirmed.
    for target in _targets(job,plan):
        reserve(lock_root()/ 'coordinator',target['physical_host_id'],owner)
        rpc(target,{'action':'reserve','target':target,'owner':owner},plan['root'])


def _release(job, attempt, plan):
    from .resources import release, lock_root
    from .transport import rpc
    for target in reversed(_targets(job,plan)):
        rpc(target,{'action':'release','target':target,'owner':attempt['attempt_id']},plan['root'])
        try:release(lock_root()/ 'coordinator',target['physical_host_id'],attempt['attempt_id'])
        except ValueError:pass  # A completed reservation may already have been released and reassigned.


def _execute(job, attempt, plan, directory):
    from .transport import rpc, map_paths, collect
    target=job['target'];out=directory/attempt['output']
    payload={'action':'run','job':map_paths(job,target,plan['root']),
             'root':target.get('repo_root',plan['root']) if target['transport']=='ssh' else plan['root'],
             'output':attempt['worker_output'],'owner':attempt['attempt_id'],'code_revision':plan['code_revision']}
    try:
        result=rpc(target,payload,plan['root'],timeout=172800)
        if target['transport']=='ssh':collect(target,attempt['worker_output'],plan['root'],out)
        _release(job,attempt,plan)
        return result
    except BaseException as exc:
        # The child might still be running. Retain reservations and reconcile on resume.
        return {'status':'lost','error_type':type(exc).__name__}


def _reconcile(job, attempt, plan, directory):
    from .transport import rpc, collect
    try:
        if attempt.get('stage')=='reserving':
            # No run RPC can precede the durable submitted stage.
            _release(job,attempt,plan)
            return {'status':'blocked','reason':'reservation_recovered','stage':'released'}
        reply=rpc(job['target'],{'action':'status','output':attempt['worker_output']},plan['root'])
        if reply['result'] and not reply.get('active'):
            if job['target']['transport']=='ssh':
                collect(job['target'],attempt['worker_output'],plan['root'],directory/attempt['output'])
            _release(job,attempt,plan)
            return reply['result']
    except (OSError,ValueError,RuntimeError):pass
    return {'status':'lost','reason':'worker_completion_not_confirmed'}


def run_campaign(directory, retry_failed=False, enable_targets=()):
    import concurrent.futures
    import time
    from .resources import reserve, release, lock_root
    from .transport import rpc
    from .planner import revision
    from llm_eval.common import sha256_file
    directory=Path(directory).resolve()
    plan=read_json(directory/'plan.json');state=read_json(directory/'campaign.json')
    if set(enable_targets)-set(plan.get('targets',{})):raise ValueError('Unknown target to enable')
    if revision(plan['root'])!=plan['code_revision']:
        raise ValueError('Resume requires the measured harness revision')
    for path,sha in plan['inputs'].items():
        if sha256_file(path)!=sha:raise ValueError('Campaign input changed; create a new campaign')
    coordinator_owner=uuid.uuid4().hex
    from .resources import ProcessLock
    coordinator = ProcessLock(directory/'.coordinator.lock')
    coordinator.acquire()
    active={};held=set();stop=False;cancel_sent=set()
    jobs={j['job_id']:j for j in plan['jobs']}
    def save(): atomic_json(directory/'campaign.json',state)
    try:
        state['enabled_targets']=sorted(set(state.get('enabled_targets',[]))|set(enable_targets))
        for jid,record in state['jobs'].items():
            if record['status'] in {'running','lost'} and record['attempts']:
                result=_reconcile(jobs[jid],record['attempts'][-1],plan,directory)
                record['attempts'][-1].update(result);record['status']=result['status']
            elif retry_failed and record['status'] in {'failed','cancelled'}:
                record['status']='planned'
        if retry_failed and (directory/'cancel.json').exists():(directory/'cancel.json').unlink()
        state['status']='running';save()
        with concurrent.futures.ThreadPoolExecutor(max_workers=plan['execution']['max_parallel_jobs']) as pool:
            while True:
                cancelled=(directory/'cancel.json').exists()
                if cancelled:
                    stop=True
                    for jid,record in state['jobs'].items():
                        if record['status'] in {'planned','blocked'}:record['status']='cancelled'
                    for future,(job,attempt) in active.items():
                        if job['job_id'] not in cancel_sent:
                            try:
                                rpc(job['target'],{'action':'cancel','output':attempt['worker_output']},plan['root'])
                                cancel_sent.add(job['job_id'])
                            except (OSError,RuntimeError):pass
                if not stop:
                    for job in plan['jobs']:
                        record=state['jobs'][job['job_id']]
                        if record['status'] not in {'planned','blocked'}:continue
                        if job['target'].get('available') is False and job.get('target_id') not in state['enabled_targets']:continue
                        if len(active)>=plan['execution']['max_parallel_jobs']:break
                        if any(state['jobs'][d]['status'] not in {'succeeded','skipped'} for d in job['depends_on']):
                            record.update(status='blocked',reason='dependency_not_succeeded');continue
                        if held.intersection(job['resources']):continue
                        aid=uuid.uuid4().hex
                        rel=Path('experiments')/job['experiment_run_id']/'jobs'/job['job_id']/aid
                        remote=str(directory/rel)
                        if job['target']['transport']=='ssh':
                            remote=job['target']['work_root'].rstrip('/\\')+'/'+directory.name+'/'+rel.as_posix()
                        attempt={'attempt_id':aid,'status':'running','stage':'reserving','started_utc':utc_now(),'output':str(rel),'worker_output':remote}
                        record['attempts'].append(attempt);record.update(status='running',reason=None)
                        save()
                        try:_reserve(job,attempt,plan)
                        except (OSError,RuntimeError,ValueError) as exc:
                            result=_reconcile(job,attempt,plan,directory)
                            attempt.update(result,error_type=type(exc).__name__)
                            record.update(status=result['status'],reason=type(exc).__name__)
                            save();continue
                        (directory/rel).mkdir(parents=True,exist_ok=True)
                        atomic_json(directory/rel/'job.json',job)
                        attempt['stage']='submitted'
                        held.update(job['resources']);save()
                        active[pool.submit(_execute,job,attempt,plan,directory)]=(job,attempt)
                if not active:break
                try:
                    done,_=concurrent.futures.wait(active,timeout=.25,return_when=concurrent.futures.FIRST_COMPLETED)
                except KeyboardInterrupt:
                    atomic_json(directory/'cancel.json', {'cancel': True})
                    continue
                for future in done:
                    job,attempt=active.pop(future);result=future.result()
                    attempt.update(result,finished_utc=utc_now())
                    state['jobs'][job['job_id']]['status']=result['status']
                    held.difference_update(job['resources'])
                    if result['status']=='failed' and plan['execution']['on_failure']=='fail-fast':stop=True
                    if result['status']=='blocked':stop=True
                    save()
                if not any(j['target']['transport']=='local' for j,a in active.values()):
                    from llm_eval.reporting.experiment import finalize_campaign
                    if plan['reporting'].get('on_experiment_end',True):
                        finalize_campaign(directory,coordinator_locked=True)
                        state['reports']=read_json(directory/'campaign.json')['reports']
                save()
        statuses={r['status'] for r in state['jobs'].values()}
        state['status']='succeeded' if statuses<={'succeeded','skipped'} else 'cancelled' if 'cancelled' in statuses else 'incomplete'
        save()
        # Added by the reporting layer; legacy reader remains independent.
        try:
            from llm_eval.reporting.experiment import finalize_campaign
        except ImportError:
            finalize_campaign=None
        if finalize_campaign and plan['reporting'].get('on_experiment_end',True):
            finalize_campaign(directory,coordinator_locked=True)
            state['reports']=read_json(directory/'campaign.json')['reports']
        reporting_failed=any(r['status']=='failed' for r in state['reports'].values())
        return 0 if state['status']=='succeeded' and not reporting_failed else 130 if state['status']=='cancelled' else 1
    except KeyboardInterrupt:
        atomic_json(directory/'cancel.json',{'cancel':True})
        for job,attempt in active.values():
            try:rpc(job['target'],{'action':'cancel','output':attempt['worker_output']},plan['root'])
            except (OSError,RuntimeError):pass
        raise
    finally:
        coordinator.close()
