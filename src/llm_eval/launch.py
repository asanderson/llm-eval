"""Owned backend lifecycle for local benchmark runs."""
from __future__ import annotations

import contextlib
import http.client
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import time

from .adapters import endpoint_parts
from .common import read_json, safe_relative


def launch_spec(config, state, workdir):
    from .core.hardware import limits
    bounds = limits(config)
    platform=config['platform']
    if state['plan']['platform']!=platform or state['plan']['os_id']!=config['os_id']:
        raise ValueError('Installation state does not match the run platform/OS')
    launch=config.get('launch',{})
    url=endpoint_parts(config['endpoint']) if config['protocol']!='worker' else None
    host=url.hostname if url else '127.0.0.1'
    if host!='127.0.0.1':
        raise ValueError('Managed servers use 127.0.0.1; use --server-mode external for another loopback address')
    port=url.port or 80 if url else 8100
    py=state['python']; exe=state.get('executable'); root=Path(config['artifact_root']).resolve()
    def local(name,default=None):
        value=launch.get(name,default)
        if not value:raise ValueError(f'launch.{name} must identify an artifact path')
        p=Path(value)
        p=p.resolve() if p.is_absolute() else safe_relative(root,value)
        if not p.is_relative_to(root) or not p.exists():
            raise ValueError(f'launch.{name} must exist inside the locked artifact root')
        return str(p)
    ctx=str(config['context_tokens']); threads=str(launch.get('threads',min(16,bounds['threads']))); layers=str(launch.get('gpu_layers',20))
    if not threads.isdigit() or not 1<=int(threads)<=bounds['threads']:
        raise ValueError('launch.threads exceeds hardware profile capacity')
    if not layers.lstrip('-').isdigit() or not -1<=int(layers)<=999:
        raise ValueError('launch.gpu_layers must be -1 (engine-specific, often all layers) or 0–999')
    env={ 'CUDA_VISIBLE_DEVICES':str(launch.get('gpu',0)), 'OMP_NUM_THREADS':threads,'MKL_NUM_THREADS':threads,
          'HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1',
          'HF_HUB_DISABLE_TELEMETRY':'1','DO_NOT_TRACK':'1','VLLM_NO_USAGE_STATS':'1',
          'CPUINFER_CPU_INSTRUCT':'AVX2','CPUINFER_ENABLE_AMX':'OFF','KT_RAWINT4_BACKEND':'avx2','KT_KERNEL_CPU_VARIANT':'avx2'}
    commands=[]; cwd=str(workdir)
    if platform in {'accelerate','airllm'}:
        return {'argv':None,'env':env,'cwd':cwd,'prepare':[]}
    if platform in {'llama.cpp','ik_llama.cpp'}:
        argv=[exe,'-m',local('model_file'),'--host',host,'--port',str(port),'-c',ctx,'-ngl',layers,
              '-t',threads,'--parallel','1','--alias',config['served_model']]
    elif platform=='koboldcpp':
        argv=[exe,'--model',local('model_file'),'--host',host,'--port',str(port),'--contextsize',ctx,
              '--gpulayers',layers,'--threads',threads,'--usecublas','--skiplauncher']
    elif platform=='ollama':
        env.update(OLLAMA_HOST=f'{host}:{port}',OLLAMA_NO_CLOUD='1',OLLAMA_NUM_PARALLEL='1',
                   OLLAMA_MAX_LOADED_MODELS='1',OLLAMA_MODELS=str(Path(state['plan']['prefix'])/'ollama-models'))
        model_file=local('model_file')
        # JSON quoting also handles backslashes and spaces in Windows paths.
        modelfile='FROM '+json.dumps(model_file)+'\nPARAMETER num_ctx '+ctx+'\nPARAMETER num_gpu '+layers+'\nPARAMETER num_thread '+threads+'\n'
        commands=[{'file':str(Path(workdir)/'Modelfile'),'content':modelfile,
                   'argv':[exe,'create',config['served_model'],'-f',str(Path(workdir)/'Modelfile')]}]
        argv=[exe,'serve']
    elif platform=='vllm':
        argv=[py,'-m','vllm.entrypoints.openai.api_server','--model',local('model_dir','.'),
              '--served-model-name',config['served_model'],'--host',host,'--port',str(port),
              '--max-model-len',ctx,'--max-num-seqs','1','--gpu-memory-utilization',str(config['gpu_budget_gib']/bounds['gpu_total_gib']),
              '--cpu-offload-gb',str(launch.get('cpu_offload_gb',32))]
        if config.get('reviewed_model_code'):argv.append('--trust-remote-code')
    elif platform=='ktransformers':
        method=launch.get('kt_method')
        if method not in {'BF16','FP8','GPTQ_INT4','RAWINT4','LLAMAFILE'}:
            raise ValueError('Select an AVX2-compatible launch.kt_method and matching artifact representation')
        argv=[py,'-m','sglang.launch_server','--model',local('model_dir','.'),
              '--kt-weight-path',local('kt_weight_path','.'),'--kt-method',method,'--kt-cpuinfer',threads,
              '--kt-threadpool-count','1','--kt-num-gpu-experts',str(launch.get('gpu_experts',2)),
              '--host',host,'--port',str(port),'--served-model-name',config['served_model'],
              '--context-length',ctx,'--max-running-requests','1','--mem-fraction-static',str(config['gpu_budget_gib']/bounds['gpu_total_gib']),
              '--attention-backend',launch.get('attention_backend','triton'),'--disable-shared-experts-fusion']
        if config.get('reviewed_model_code'):argv.append('--trust-remote-code')
    elif platform=='strata':
        engine_config=local('strata_config')
        prepared=read_json(engine_config)
        # Upstream configs can select an executable: only use this installation's verified build.
        if Path(prepared.get('exe','')).resolve()!=Path(exe).resolve():
            raise ValueError('Strata config.exe must point to the executable in installation state')
        if not config.get('reviewed_strata_config'):
            raise ValueError('Review prepared Strata engine arguments and set reviewed_strata_config=true')
        argv=[py,str(Path(state['source'])/'serve/server.py'),'--config',engine_config,'--host',host,'--port',str(port)]
        if config.get('api_key_env'):
            key=os.environ.get(config['api_key_env'])
            if not key:raise ValueError('Strata API key environment variable is unset')
    else:raise ValueError('No launch recipe for platform')
    extra=launch.get('extra_args',[])
    if not isinstance(extra,list) or any(not isinstance(v,str) or '\x00' in v for v in extra):
        raise ValueError('launch.extra_args must be a JSON array of strings')
    protected={'--host','--port','--listen','--bind','--model','--model-path','--model_path','-m',
               '--served-model-name','--alias','--api-key','--api_key','--trust-remote-code','--config','--script',
               '--mcp-config','--before-load','--open','--websearch'}
    if any(v.split('=',1)[0] in protected for v in extra):
        raise ValueError('Extra engine arguments cannot override controlled model, network, or execution options')
    argv.extend(extra)
    return {'argv':argv,'cwd':cwd,'env':env,'prepare':commands,'port':port}


def stop_owned(process):
    try:
        if os.name=='nt':
            if process.poll() is not None:return
            import psutil
            parent=psutil.Process(process.pid)
            children=parent.children(recursive=True)
            for child in children:child.terminate()
            parent.terminate()
            _,alive=psutil.wait_procs([parent,*children],timeout=5)
            for p in alive:p.kill()
        else:
            os.killpg(process.pid,signal.SIGTERM)
            try:process.wait(timeout=5)
            except subprocess.TimeoutExpired:pass
            # The parent can exit before its children; close the owned group too.
            try:os.killpg(process.pid,signal.SIGKILL)
            except ProcessLookupError:pass
        process.wait(timeout=10)
    except ProcessLookupError:pass


def wait_port(process, port, timeout, readiness_path='/v1/models', headers=None):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        if process.poll() is not None:raise RuntimeError('Backend exited during startup; inspect its local log')
        connection=http.client.HTTPConnection('127.0.0.1',port,timeout=1)
        try:
            connection.request('GET',readiness_path,headers=headers or {})
            response=connection.getresponse()
            response.read(1024*1024)
            if response.status==200:return
        except (OSError,http.client.HTTPException):pass
        finally:connection.close()
        time.sleep(.25)
    raise TimeoutError('Backend startup deadline exceeded')


@contextlib.contextmanager
def managed_backend(config, state, workdir):
    workdir=Path(workdir);workdir.mkdir(parents=True,exist_ok=True)
    spec=launch_spec(config,state,workdir)
    if spec['argv'] is None:
        config['worker_python']=state['python']
        yield
        return
    with socket.socket() as check:
        if check.connect_ex(('127.0.0.1',spec['port']))==0:
            raise ValueError('Selected port is already in use; stop that server or choose another port')
    env=os.environ.copy();env.update(spec['env'])
    if config['platform']=='strata' and config.get('api_key_env'):
        env['STRATA_API_KEY']=os.environ[config['api_key_env']]
    # Inference is local; proxy environment settings must not redirect benchmark requests.
    for k in list(env):
        if k.lower() in {'http_proxy','https_proxy','all_proxy'}:env.pop(k)
    process=None
    with (workdir/'backend.log').open('w',encoding='utf-8') as log:
        try:
            process=subprocess.Popen(spec['argv'],cwd=spec['cwd'],env=env,stdout=log,stderr=subprocess.STDOUT,
                                     start_new_session=os.name!='nt',shell=False)
            config['backend_pid']=process.pid
            key=os.environ.get(config.get('api_key_env',''))
            wait_port(process,spec['port'],config.get('load_timeout_s',900),
                      '/api/tags' if config['platform']=='ollama' else '/v1/models',
                      {'Authorization':'Bearer '+key} if key else {})
            for action in spec['prepare']:
                Path(action['file']).write_text(action['content'],encoding='utf-8')
                subprocess.run(action['argv'],env=env,check=True,stdout=log,stderr=subprocess.STDOUT,
                               timeout=config.get('load_timeout_s',900),shell=False)
            yield
        finally:
            if process is not None:stop_owned(process)
