"""One bounded JSON RPC over local stdio or OpenSSH. No credentials in payloads."""
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

MAX_TRANSFER = 128 * 1024 * 1024


def map_paths(value, target, root):
    mappings = {str(root): target.get('repo_root',str(root)), **target.get('path_mappings', {})}
    if isinstance(value, dict):
        return {k: map_paths(v,target,root) for k,v in value.items()}
    if isinstance(value,list):
        return [map_paths(v,target,root) for v in value]
    if isinstance(value,str):
        for source,dest in sorted(mappings.items(),key=lambda x:-len(x[0])):
            if value == source or value.startswith(source.rstrip('/')+'/'):
                return dest.rstrip('/\\')+value[len(source):]
    return value


def rpc(target, payload, root, timeout=60):
    env = os.environ.copy()
    for name in ('GH_TOKEN','GITHUB_TOKEN','LLM_EVAL_PUBLISH_TOKEN'):
        env.pop(name,None)
    env['PYTHONPATH'] = str(Path(root)/'src')
    if target['transport']=='local':
        argv=[sys.executable,'-m','llm_eval.orchestration.worker']
    else:
        host=target['host']; python=target['python']
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._@-]*',host) or not re.fullmatch(r'[A-Za-z0-9_/:.\\-]+',python):
            raise ValueError('Use an SSH config alias and a shell-safe Python executable path')
        argv=['ssh','-T','-o','BatchMode=yes','-o','ConnectTimeout=10',host,python,'-m','llm_eval.orchestration.worker']
    p=subprocess.run(argv,input=json.dumps(payload),capture_output=True,text=True,env=env,timeout=timeout)
    if p.returncode:
        raise ConnectionError('Worker transport failed; inspect worker state before retrying')
    if len(p.stdout)>MAX_TRANSFER*2:
        raise ValueError('Worker transfer exceeds limit; results remain on worker')
    reply=json.loads(p.stdout)
    if reply.get('error'):
        if reply['error']=='BlockingIOError': raise BlockingIOError('Worker resource busy')
        raise RuntimeError('Worker rejected request: '+reply['error'])
    return reply


def collect(target, output, root, destination):
    reply=rpc(target,{'action':'collect','output':str(output)},root)
    destination=Path(destination).resolve()
    total=sum(entry['bytes'] for entry in reply['files'])
    if total>target.get('max_collection_bytes',2*1024**3):
        raise ValueError('Worker collection exceeds configured cap; artifacts remain on worker')
    destination.mkdir(parents=True,exist_ok=True)
    import shutil
    if total>shutil.disk_usage(destination).free:
        raise ValueError('Insufficient disk space to collect worker artifacts')
    for entry in reply['files']:
        name=entry['path'];path=(destination/name).resolve()
        if not path.is_relative_to(destination) or '\\' in name or Path(name).is_absolute():
            raise ValueError('Unsafe worker artifact path')
        if path.is_file() and path.stat().st_size==entry['bytes']:
            from llm_eval.common import sha256_file
            if sha256_file(path)==entry['sha256']:continue
        path.parent.mkdir(parents=True,exist_ok=True)
        temp=path.with_name('.'+path.name+'.transfer');h=hashlib.sha256();offset=0
        with temp.open('wb') as handle:
            while offset<entry['bytes']:
                part=rpc(target,{'action':'file-chunk','output':str(output),'path':name,'offset':offset},root)
                data=base64.b64decode(part['data'],validate=True)
                if not data or len(data)>4*1024*1024 or offset+len(data)>entry['bytes']:
                    raise ValueError('Worker returned an invalid artifact chunk')
                handle.write(data);h.update(data);offset+=len(data)
        if h.hexdigest()!=entry['sha256']:raise ValueError('Worker artifact integrity failure')
        os.replace(temp,path)
    return reply
