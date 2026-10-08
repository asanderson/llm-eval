"""Deduplicate and prepare campaign runtime environments before measurement."""
from pathlib import Path
import uuid

from .resources import reserve, release, lock_root
from .transport import rpc, map_paths


def setup_campaign(plan):
    seen=set();failed=False
    for job in plan['jobs']:
        if job['status']=='skipped':continue
        target=job['target'];params=map_paths(job['parameters'],target,plan['root'])
        platforms=[params['config']['platform']] if 'config' in params else [params.get('router',{}).get('platform','ollama')]
        for platform in platforms:
            if platform not in {'ollama','llama.cpp','ik_llama.cpp','ktransformers','koboldcpp','vllm','strata','accelerate','airllm'}:continue
            root=target.get('repo_root',plan['root'])
            state=params.get('installation_state')
            prefix=str(Path(state).parent) if state else root.rstrip('/\\')+'/.platforms/'+job['hardware']['os_id']+'/'+platform
            key=(job['target_id'],platform,job['hardware']['hardware_profile'],prefix,job['mode']=='livebench')
            if key in seen:continue
            seen.add(key);owner=uuid.uuid4().hex
            try:
                reserve(lock_root()/'coordinator',target['physical_host_id'],owner)
                rpc(target,{'action':'reserve','target':target,'owner':owner},plan['root'])
                result=rpc(target,{'action':'setup','root':root,'output':prefix,'platform':platform,
                                  'code_revision':plan['code_revision'],'hardware':job['hardware'],
                                  'with_livebench':job['mode']=='livebench'},plan['root'],timeout=7200)
                print(job['target_id'],platform,result['status'])
                failed |= result['status']!='succeeded'
            except (OSError,ValueError,RuntimeError):
                failed=True;print(job['target_id'],platform,'setup failed')
            finally:
                try:rpc(target,{'action':'release','target':target,'owner':owner},plan['root'])
                except (OSError,RuntimeError,ValueError):pass
                try:release(lock_root()/'coordinator',target['physical_host_id'],owner)
                except ValueError:pass
    return int(failed)
