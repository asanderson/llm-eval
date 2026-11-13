"""Versioned worker protocol usable from native Linux, Windows and WSL."""
import base64
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from llm_eval.common import read_json, environment_kind
from llm_eval.core.contracts import atomic_json
from .resources import reserve, release, lock_root
from .planner import revision


def execute(payload):
    from llm_eval.experiments import get_experiment
    from llm_eval.telemetry import host_snapshot
    job=payload['job'];out=Path(payload['output']);root=Path(payload['root'])
    if hasattr(signal,'SIGBREAK'):
        signal.signal(signal.SIGBREAK,lambda *a: (_ for _ in ()).throw(KeyboardInterrupt()))
    atomic_json(out/'host.json',host_snapshot())
    try:
        result=get_experiment(job['experiment_id']).execute(job,out,root)
    except KeyboardInterrupt:
        result={'status':'cancelled'}
    except BaseException as exc:
        result={'status':'failed','error_type':type(exc).__name__}
    result.update(finished_unix=time.time(),attempt_id=payload['owner'])
    atomic_json(out/'result.json',result)


def stop_child(child):
    if child.poll() is not None:return
    try:
        child.send_signal(signal.CTRL_BREAK_EVENT if os.name=='nt' else signal.SIGINT)
        child.wait(timeout=15)
    except (subprocess.TimeoutExpired, OSError):
        try:
            import psutil
            parent=psutil.Process(child.pid)
            tree=parent.children(recursive=True)+[parent]
            for p in tree:
                try:p.terminate()
                except psutil.Error:pass
            _,alive=psutil.wait_procs(tree,timeout=5)
            for p in alive:
                try:p.kill()
                except psutil.Error:pass
        except (ImportError,ProcessLookupError):child.kill()
        child.wait(timeout=10)


def _transferable(path):
    """A job.json that cannot be read as a JSON object naming its experiment refuses the transfer; one of an experiment whose
    plugin exports `data_policy` decides by that policy; any other job.json allows it, as before. The error names the path."""
    from llm_eval.experiments import REGISTRY, data_policy, plugin_hook
    try:job=read_json(path)
    except (OSError,ValueError,RecursionError):job=None
    name=job.get('experiment_id') if isinstance(job,dict) else None
    if not isinstance(name,str) or not name:raise ValueError('Collection refused by data policy: '+str(path))
    if name in REGISTRY and plugin_hook(name,'data_policy') and not data_policy(name,job)['transfer']:
        raise ValueError('Collection refused by data policy: '+str(path))


def _transfer_gate(directory):
    """Every job.json at or above `directory`, at any depth up to the file-system root, decides whether bytes under it may
    leave this host: a nearer job.json cannot override a refusing one above it."""
    for candidate in [directory,*directory.parents]:
        if (candidate/'job.json').is_file():_transferable(candidate/'job.json')


def handle(p):
    action=p['action']
    if action in {'reserve','release'}:
        target=p['target'];owner=p['owner']
        root=lock_root(target)
        if action=='reserve':reserve(root,target['physical_host_id'],owner)
        else:
            try:release(root,target['physical_host_id'],owner)
            except ValueError:return {'ok':False,'reason':'different_owner'}
        return {'ok':True}
    out=Path(p['output']).expanduser().resolve()
    if action=='setup':
        root=Path(p['root'])
        if revision(root)!=p['code_revision']:raise ValueError('Worker code revision mismatch')
        from llm_eval.core.hardware import limits
        bounds=limits(p['hardware'],root)
        out.parent.mkdir(parents=True,exist_ok=True)
        args=[sys.executable,str(root/'scripts/setup.py'),'--non-interactive','--platform',p['platform'],
              '--os',p['hardware']['os_id'],'--prefix',str(out),'--hardware-profile',p['hardware']['hardware_profile'],
              '--jobs',str(min(8,bounds['threads']))]
        if p['with_livebench']:args.append('--with-livebench')
        with out.with_suffix('.setup.log').open('w',encoding='utf-8') as log:
            result=subprocess.run(args,stdout=log,stderr=subprocess.STDOUT,timeout=7000)
        return {'status':'succeeded' if result.returncode==0 else 'failed'}
    if action=='status':
        active=(out/'active').exists()
        if active and (out/'result.json').exists() and (out/'heartbeat.json').exists():
            import psutil
            heartbeat=read_json(out/'heartbeat.json')
            try:
                proc=psutil.Process(heartbeat['pid'])
                active=proc.is_running() and proc.status()!=psutil.STATUS_ZOMBIE and abs(proc.create_time()-heartbeat['process_started'])<.01
            except psutil.NoSuchProcess:active=False
        return {'active':active,'result':read_json(out/'result.json') if (out/'result.json').exists() else None,
                'heartbeat':read_json(out/'heartbeat.json') if (out/'heartbeat.json').exists() else None}
    if action=='cancel':
        atomic_json(out/'cancel.json',{'cancel':True});return {'ok':True}
    if action=='file-chunk':
        path=(out/p['path']).resolve()
        if not path.is_relative_to(out) or path.is_symlink():raise ValueError('Unsafe artifact path')
        if type(p['offset']) is not int or p['offset']<0:raise ValueError('Invalid artifact offset')
        _transfer_gate(path.parent)
        with path.open('rb') as f:
            f.seek(p['offset']);data=f.read(4*1024*1024)
        return {'data':base64.b64encode(data).decode()}
    if action=='collect':
        _transfer_gate(out)
        from llm_eval.common import sha256_file
        files=[]
        for path in sorted(out.rglob('*')):
            if path.is_symlink():raise ValueError('Symlink in result bundle')
            if not path.is_file() or path.name in {'worker.log','execution.json'}:continue
            if path.name=='job.json':_transferable(path)      # a listing that holds a refused attempt is refused as a whole
            files.append({'path':path.relative_to(out).as_posix(),'sha256':sha256_file(path),'bytes':path.stat().st_size})
            if len(files)>100000:raise ValueError('Artifact inventory exceeds limit')
        return {'files':files}
    if action!='run':raise ValueError('Unknown worker action')
    # Check supervision dependencies before reserving or creating a child.
    import psutil
    root=Path(p['root']).resolve();job=p['job'];target=job['target']
    synthetic=job['parameters'].get('synthetic',False)
    from llm_eval.common import sha256_file
    for file in job.get('input_files',[]):
        if sha256_file(file['path'])!=file['sha256']:raise ValueError('Worker input hash mismatch')
    if revision(root)!=p['code_revision']:raise ValueError('Worker code revision mismatch')
    from llm_eval.experiments import data_policy
    if not data_policy(job.get('experiment_id'),job)['admit']:raise ValueError('Data policy refused the job')
    if not synthetic:
        if subprocess.run(['git','-C',str(root),'diff','--quiet','HEAD']).returncode:
            raise ValueError('Worker checkout contains uncommitted code changes')
        from llm_eval.runner import validate_host
        from llm_eval.experiments import get_experiment
        need=getattr(get_experiment(job['experiment_id']),'host_requirements',None)
        gpu=need(job['parameters'],job['mode']).get('gpu',True) if need else True
        validate_host({'hardware_profile':job['hardware']['hardware_profile']},root,require_gpu=gpu)
        if environment_kind()!=job['hardware']['os_id']:raise ValueError('Worker OS does not match selected hardware configuration')
        if 'wsl2' in environment_kind() and not target.get('lock_root'):
            raise ValueError('WSL requires a lock_root shared with the Windows host worker')
    reserve(lock_root(target),target['physical_host_id'],p['owner'])
    out.mkdir(parents=True,exist_ok=True)
    if (out/'result.json').exists():return read_json(out/'result.json')
    # A duplicate run cannot start a second child, including after transport loss.
    (out/'active').mkdir()
    atomic_json(out/'job.json',job);atomic_json(out/'execution.json',p)
    env=os.environ.copy();env['PYTHONPATH']=str(root/'src')
    for name in ('GH_TOKEN','GITHUB_TOKEN','LLM_EVAL_PUBLISH_TOKEN'):
        env.pop(name,None)
    with (out/'worker.log').open('w',encoding='utf-8') as log:
        child=subprocess.Popen([sys.executable,'-m','llm_eval.orchestration.worker','--execute',str(out/'execution.json')],
                               env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=os.name!='nt',
                               creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name=='nt' else 0)
        try:
            try:process_started=psutil.Process(child.pid).create_time()
            except psutil.NoSuchProcess:process_started=None
            while child.poll() is None:
                atomic_json(out/'heartbeat.json',{'pid':child.pid,'process_started':process_started,'unix':time.time(),'owner':p['owner']})
                if (out/'cancel.json').exists():stop_child(child)
                time.sleep(.2)
            if not (out/'result.json').exists():
                atomic_json(out/'result.json',{'status':'cancelled' if (out/'cancel.json').exists() else 'failed','error_type':'WorkerExited','returncode':child.returncode})
        finally:
            stop_child(child)
            (out/'active').rmdir()
    return read_json(out/'result.json')


def main():
    if len(sys.argv)==3 and sys.argv[1]=='--execute':
        execute(read_json(sys.argv[2]));return
    try:
        payload=json.loads(sys.stdin.read(16*1024*1024))
        result=handle(payload)
    except BaseException as exc:
        result={'error':type(exc).__name__}
        if 'payload' in locals() and payload.get('action') == 'run':
            active = Path(payload['output'])/'active'
            if not active.exists(): result={'status':'blocked','error_type':type(exc).__name__}
    print(json.dumps(result,allow_nan=False))

if __name__=='__main__':main()
