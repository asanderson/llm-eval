"""Interactive and non-interactive setup/run entry points, shared by every OS wrapper."""
from __future__ import annotations

import argparse
import contextlib
import datetime
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import uuid

from .artifacts import verify_artifact
from .common import environment_kind, read_json, sha256_file, write_json
from .launch import launch_spec, managed_backend
from .livebench import run_livebench
from .provision import OS_IDS, execute_install, install_plan, invoke
from .report import write_report
from .runner import run, validate_config, validate_host


class Prompts:
    def __init__(self, interactive):self.interactive=interactive

    def value(self, label, value=None, default=None, choices=None, required=False):
        if value is not None:
            if choices and value not in choices:raise ValueError('Invalid '+label)
            return value
        if self.interactive:
            if choices:print('\n'+label+':\n'+'\n'.join(f'  {i+1}. {v}' for i,v in enumerate(choices)))
            suffix=f' [{default}]' if default is not None else ''
            value=input(label+suffix+': ').strip()
            if choices and value.isdigit() and 1<=int(value)<=len(choices):value=choices[int(value)-1]
            if not value:value=default
        else:value=default
        if required and (value is None or value==''):raise ValueError('Missing '+label+'; supply its CLI option or use --interactive')
        if choices and value is not None and value not in choices:raise ValueError('Invalid '+label)
        return value

    def yes(self,label,value=None,default=False):
        if value is not None:return value
        answer=self.value(label,None,'yes' if default else 'no',choices=['yes','no'])
        return answer=='yes'


def csv_selection(value, choices):
    selected=list(choices) if value=='all' else list(dict.fromkeys(x.strip() for x in value.split(',') if x.strip()))
    if not selected or set(selected)-set(choices):raise ValueError('Unknown or empty selection: '+value)
    return selected


def parser_for(action):
    p=argparse.ArgumentParser(description=f'{action.capitalize()} local LLM evaluation platforms; no-argument use opens a terminal wizard')
    p.add_argument('--project-root',type=Path,default=Path(__file__).resolve().parents[2])
    mode=p.add_mutually_exclusive_group()
    mode.add_argument('--interactive',action='store_true')
    mode.add_argument('--non-interactive',action='store_true')
    p.add_argument('--dry-run',action='store_true',help='Print a plan; no install, server launch, download, or evaluation')
    p.add_argument('--platform')
    p.add_argument('--os',choices=OS_IDS)
    p.add_argument('--prefix',type=Path,help='Installation directory; default .platforms/OS/PLATFORM')
    p.add_argument('--models',help='Comma-separated catalog IDs; run sequentially with matching configs')
    p.add_argument('--categories',help='Comma-separated category IDs, or all')
    if action=='setup':
        p.add_argument('--python',help='Backend Python 3.11–3.13 interpreter')
        p.add_argument('--jobs',type=int)
        p.add_argument('--cuda-arch')
        p.add_argument('--hardware-profile',default='msi-raider-18-hx-ai')
        p.add_argument('--revision',help='Override a source recipe with a full commit SHA')
        p.add_argument('--package',action='append',help='Override Python recipe with exact name==version; repeat for each package')
        p.add_argument('--with-livebench',action=argparse.BooleanOptionalAction,default=None)
        p.add_argument('--build-livebench-image',help='Build a local Docker grading image with this tag; requires --with-livebench')
        p.add_argument('--download-spec',type=Path,help='Optional explicit model-download JSON manifest; see docs/WORKFLOWS.md')
    else:
        p.add_argument('--config',type=Path,action='append',help='Existing complete run configuration; repeat for multiple models')
        p.add_argument('--benchmark',choices=['category-smoke','livebench'])
        p.add_argument('--server-mode',choices=['managed','external'])
        p.add_argument('--output',type=Path,default=Path('results'))
        for name in ['context','max-tokens','warmups','repeats','threads','gpu-layers','port','timeout','load-timeout']:
            p.add_argument('--'+name,type=int)
        p.add_argument('--ram-budget',type=float)
        p.add_argument('--vram-budget',type=float)
        p.add_argument('--artifact-root',type=Path)
        p.add_argument('--artifact-lock',type=Path)
        p.add_argument('--model-file',help='GGUF path relative to artifact root')
        p.add_argument('--template-file',type=Path,help='File containing the actual active chat template, for its SHA256')
        p.add_argument('--hardware-attestation',type=Path,help='JSON observations: driver, BIOS, power profile, MUX, SSD placement')
        p.add_argument('--backend-version')
        p.add_argument('--tokenizer-revision')
        p.add_argument('--placement-notes')
        p.add_argument('--served-model')
        p.add_argument('--endpoint',help='Full literal-loopback endpoint for an existing external server')
        p.add_argument('--launch-options',type=Path,help='JSON object of platform-specific launch fields; no shell text')
        p.add_argument('--save-outputs',action=argparse.BooleanOptionalAction,default=None)
        p.add_argument('--reviewed-airllm-source',action=argparse.BooleanOptionalAction,default=None)
        p.add_argument('--reviewed-model-code',action=argparse.BooleanOptionalAction,default=None)
        p.add_argument('--reviewed-strata-config',action=argparse.BooleanOptionalAction,default=None)
        p.add_argument('--allow-disk-offload',action=argparse.BooleanOptionalAction,default=None)
        p.add_argument('--lane',choices=['offload','control','disk'])
        p.add_argument('--dtype',choices=['auto','bfloat16','float16','float32'])
        p.add_argument('--continue-on-error',action='store_true')
        p.add_argument('--livebench-data',type=Path,help='Local root containing live_bench/CATEGORY/TASK/question.jsonl')
        p.add_argument('--livebench-release',default='2026-06-25')
        p.add_argument('--livebench-image',help='Local Docker grading image tag or ID')
        p.add_argument('--allow-agentic-execution',action='store_true',help='Explicitly enable upstream Docker agent/build execution')
    return p


def resolve_paths(c,config_file):
    for key in ('suite','artifact_root','artifact_lock','offload_dir'):
        if c.get(key):
            path=Path(c[key]).expanduser()
            c[key]=str(path.resolve() if path.is_absolute() else (config_file.parent/path).resolve())
    return c


def build_config(args, prompts, root, engine, model, state, config_file=None):
    os_id=args.os
    if config_file:
        c=resolve_paths(read_json(config_file),config_file.resolve())
        if (c['model_id'],c['platform'],c['os_id'])!=(model['id'],engine['id'],os_id):
            raise ValueError('Configuration model/platform/OS does not match the selected experiment')
    else:
        c=read_json(root/f'configs/runs/{engine["id"]}.example.json')
        profile=read_json(root/f'configs/os/{os_id}.json')
        c.update(model_id=model['id'],os_id=os_id,context_tokens=model['default_context_tokens'],
                 gpu_budget_gib=profile['vram_budget_gib'],ram_budget_gib=profile['ram_budget_gib'])
        if model['status']=='control':c['lane']='control'
        for key,flag in [('artifact_root','artifact_root'),('artifact_lock','artifact_lock')]:
            c[key]=str(Path(prompts.value('--'+flag.replace('_','-'),getattr(args,flag),required=True)).expanduser().resolve())
        c['offload_dir']=str(Path(args.output).resolve()/'offload'/model['id'])
        c['backend_version']=prompts.value('--backend-version',args.backend_version,state.get('backend_version'),required=True)
        lock=read_json(c['artifact_lock']) if Path(c['artifact_lock']).exists() else {}
        c['tokenizer_revision']=prompts.value('--tokenizer-revision',args.tokenizer_revision,lock.get('source_revision'),required=True)
        template=prompts.value('--template-file',args.template_file,required=True)
        c['chat_template_sha256']=sha256_file(Path(template).expanduser())
        c['placement_notes']=prompts.value('--placement-notes',args.placement_notes,required=True)
        attestation=prompts.value('--hardware-attestation',args.hardware_attestation,required=True)
        c['hardware_attestation']=read_json(Path(attestation).expanduser())
        if c['protocol']!='worker':
            c['served_model']=prompts.value('--served-model',args.served_model,model['id'],required=True)
        c['launch']={}
        if engine['id'] in {'llama.cpp','ik_llama.cpp','koboldcpp','ollama'} and args.server_mode=='managed':
            c['launch']['model_file']=prompts.value('--model-file',args.model_file,required=True)
        if engine['id'] in {'ktransformers','strata'} and args.server_mode=='managed':
            opts=prompts.value('--launch-options',args.launch_options,required=True)
            c['launch'].update(read_json(Path(opts).expanduser()))
    for arg,key in [('context','context_tokens'),('max_tokens','max_output_tokens'),('repeats','repeats'),('warmups','warmups'),
                    ('timeout','timeout_s'),('load_timeout','load_timeout_s'),('ram_budget','ram_budget_gib'),('vram_budget','gpu_budget_gib'),
                    ('backend_version','backend_version'),('tokenizer_revision','tokenizer_revision'),('placement_notes','placement_notes'),
                    ('served_model','served_model'),('save_outputs','save_outputs')]:
        if getattr(args,arg,None) is not None:c[key]=getattr(args,arg)
    for arg in ['reviewed_airllm_source','reviewed_model_code','reviewed_strata_config','allow_disk_offload','lane','dtype']:
        if getattr(args,arg,None) is not None:c[arg]=getattr(args,arg)
    if not config_file and engine['id']=='airllm':
        c['reviewed_airllm_source']=prompts.yes('Have you reviewed the pinned AirLLM loader? (--reviewed-airllm-source)',args.reviewed_airllm_source)
    if not config_file and engine['id']=='strata':
        c['reviewed_strata_config']=prompts.yes('Have you reviewed the prepared Strata engine configuration? (--reviewed-strata-config)',args.reviewed_strata_config)
    for arg in ['artifact_root','artifact_lock']:
        if getattr(args,arg,None):c[arg]=str(getattr(args,arg).expanduser().resolve())
    if args.template_file:c['chat_template_sha256']=sha256_file(args.template_file)
    if args.hardware_attestation:c['hardware_attestation']=read_json(args.hardware_attestation)
    c.setdefault('launch',{})
    if args.launch_options:c['launch'].update(read_json(args.launch_options))
    for arg in ['threads','gpu_layers','model_file']:
        if getattr(args,arg,None) is not None:c['launch'][arg]=getattr(args,arg)
    if prompts.interactive:
        c['save_outputs']=prompts.yes(model['id']+': --save-outputs',args.save_outputs,c.get('save_outputs',False))
        for arg,key in [('context','context_tokens'),('max_tokens','max_output_tokens'),('repeats','repeats'),('warmups','warmups')]:
            c[key]=int(prompts.value(model['id']+': --'+arg.replace('_','-'),getattr(args,arg),c[key]))
        for arg,default in [('threads',16),('gpu_layers',20)]:
            if arg=='gpu_layers' and engine['id'] not in {'llama.cpp','ik_llama.cpp','koboldcpp','ollama'}:continue
            c['launch'][arg]=int(prompts.value(model['id']+': --'+arg.replace('_','-'),getattr(args,arg),c['launch'].get(arg,default)))
    if c['protocol']!='worker':
        port=args.port or (11434 if engine['id']=='ollama' else 8100)
        if not 1024<=port<=65535:raise ValueError('Select a port from 1024 to 65535')
        if args.server_mode=='managed':
            c['endpoint']=f'http://127.0.0.1:{port}'+('/api/chat' if engine['id']=='ollama' else '/v1/chat/completions')
        elif args.endpoint:c['endpoint']=args.endpoint
        elif not config_file:c['endpoint']=prompts.value('--endpoint',required=True)
    if state and c['protocol']=='worker':c['worker_python']=state['python']
    return c


def setup_action(args,prompts,root,engines,models,categories):
    default_model='qwen38-flash-next-strata' if args.platform=='strata' else 'llama33-70b'
    args.models=prompts.value('--models (comma-separated catalog IDs)',args.models,default_model)
    selected=csv_selection(args.models,models)
    if any(models[m]['status']=='excluded' or m in engines[args.platform].get('blocked_models',[]) for m in selected):
        raise ValueError('Selected setup model is excluded or blocked on this platform')
    selected_categories=csv_selection(prompts.value('--categories',args.categories,'all'),categories)
    py=prompts.value('--python',args.python,sys.executable)
    jobs=int(prompts.value('--jobs',args.jobs,8))
    with_lb=prompts.yes('--with-livebench',args.with_livebench)
    if prompts.interactive:
        if with_lb:args.build_livebench_image=prompts.value('--build-livebench-image (optional Docker image tag)',args.build_livebench_image)
        download=prompts.value('--download-spec (optional model download manifest)',args.download_spec)
        args.download_spec=Path(download).expanduser() if download else None
    plan=install_plan(root,args.platform,args.os,args.prefix,py,jobs,args.cuda_arch,args.revision,args.package,with_lb,hardware_profile=args.hardware_profile)
    if args.build_livebench_image and not with_lb:raise ValueError('--build-livebench-image requires --with-livebench')
    plan['selected_models']=selected;plan['selected_categories']=selected_categories
    plan['download_spec']=str(args.download_spec.resolve()) if args.download_spec else None
    plan['grading_image_tag']=args.build_livebench_image
    if args.download_spec:
        from .model_download import validate_download_spec
        plan['model_downloads']=validate_download_spec(root,args.download_spec,selected)
    print(json.dumps(plan,indent=2))
    if args.dry_run:return 0
    if prompts.interactive and not prompts.yes('Install this displayed plan?',default=True):return 0
    state_file=execute_install(plan,root)
    if args.download_spec:
        from .model_download import download_with_environment
        download_with_environment(root,plan,args.download_spec)
    if args.build_livebench_image:
        state=read_json(state_file)
        invoke(['docker','build','--label','org.llm-eval.livebench.revision='+state['livebench_revision'],
                '-f',str(root/'containers/livebench/Dockerfile'),'-t',args.build_livebench_image,state['livebench_source']])
    write_json(args.prefix/'preferences.json',{'models':selected,'categories':selected_categories})
    print('Installed platform state:',state_file)
    return 0


def run_action(args,prompts,root,engines,models,categories):
    config_files={}
    for path in args.config or []:
        c=read_json(path)
        if c['model_id'] in config_files:raise ValueError('Only one config per model is allowed in a session')
        config_files[c['model_id']]=path
    prefs=read_json(args.prefix/'preferences.json') if (args.prefix/'preferences.json').exists() else {}
    defaults=','.join(config_files) or ','.join(prefs.get('models',[])) or ('qwen38-flash-next-strata' if args.platform=='strata' else 'llama33-70b')
    selected=csv_selection(prompts.value('--models (comma-separated catalog IDs)',args.models,defaults),models)
    if len(selected)>1 and any(getattr(args,k) for k in ['artifact_root','artifact_lock','model_file','template_file','served_model']):
        raise ValueError('For multiple models, use one --config per model instead of shared artifact/model options')
    args.benchmark=prompts.value('--benchmark',args.benchmark,'category-smoke',['category-smoke','livebench'])
    chosen=csv_selection(prompts.value('--categories',args.categories,','.join(prefs.get('categories',[])) or 'all'),categories)
    args.server_mode=prompts.value('--server-mode',args.server_mode,'managed',['managed','external'])
    if args.benchmark=='livebench':
        args.livebench_data=Path(prompts.value('--livebench-data',args.livebench_data,required=True)).expanduser().resolve()
        args.livebench_image=prompts.value('--livebench-image',args.livebench_image,required=True)
        if 'agentic_coding' in chosen and prompts.interactive:
            args.allow_agentic_execution=prompts.yes('Allow upstream Docker agent/build execution?',True if args.allow_agentic_execution else None)
    state_file=args.prefix/'state.json'
    state=read_json(state_file) if state_file.exists() else {}
    if args.server_mode=='managed' and not state and not args.dry_run:
        raise ValueError('Run setup first, or select --server-mode external')
    if state and state.get('status')!='installed':raise ValueError('Platform installation has not completed')
    stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8]
    session=args.output.resolve()/('session-'+stamp)
    runs=[]
    for model_id in selected:
        model=models[model_id];engine=engines[args.platform]
        if model['status']=='excluded' or model_id in engine.get('blocked_models',[]):
            runs.append({'model':model_id,'status':'skipped','reason':'excluded model or unsupported architecture'});continue
        if model.get('task_family')=='safety':
            raise ValueError('Safeguard models use workloads/safety-policy.json through the core run CLI, not general LiveBench categories')
        c=build_config(args,prompts,root,engine,model,state,config_files.get(model_id))
        c['suite']=str(root/categories[chosen[0]]['local_suite'])
        validate_config(c,root,synthetic=args.dry_run)
        if args.dry_run:
            plan={'model':model_id,'benchmark':args.benchmark,'categories':chosen,'config':c,'status':'planned'}
            if state and args.server_mode=='managed':plan['backend']=launch_spec(c,state,session/model_id/'backend')
            if args.benchmark=='livebench':
                plan['livebench']=run_livebench(c,state,chosen,args.livebench_data,args.livebench_release,
                                                session/(model_id+'-livebench'),image=args.livebench_image,
                                                allow_agentic=args.allow_agentic_execution,dry_run=True)
            runs.append(plan);continue
        lock=read_json(c['artifact_lock'])
        if lock.get('base_model_repo')!=model['upstream_repo']:raise ValueError('Locked artifact does not match the selected base model')
        verify_artifact(c['artifact_root'],lock,c['lane']!='control')
        host=validate_host(c,root)
        model_dir=session/model_id
        model_dir.mkdir(parents=True,exist_ok=True)
        backend=managed_backend(c,state,model_dir/'backend') if args.server_mode=='managed' else contextlib.nullcontext()
        try:
            if args.benchmark=='livebench':
                result=run_livebench(c,state,chosen,args.livebench_data,args.livebench_release,
                                     session/(model_id+'-livebench'),image=args.livebench_image,
                                     allow_agentic=args.allow_agentic_execution,backend=backend,host=host)
                runs.append({'model':model_id,'benchmark':'livebench-upstream','status':'completed','output':str(result)})
            else:
                with backend:
                    for category in chosen:
                        c['suite']=str(root/categories[category]['local_suite'])
                        config_path=model_dir/(category+'.json');write_json(config_path,c)
                        result=run(config_path,root,model_dir/'measurements')
                        status=read_json(result/'metadata.json')['status']
                        runs.append({'model':model_id,'category':category,'benchmark':'category-smoke','status':status,'output':str(result)})
                        if status not in {'completed','skipped'} and not args.continue_on_error:
                            raise RuntimeError('Evaluation failed; inspect run metadata and the backend log')
        except Exception as exc:
            runs.append({'model':model_id,'status':'failed','error_type':type(exc).__name__})
            write_json(session/'session.json',{'runs':runs})
            if not args.continue_on_error:raise
    if args.dry_run:print(json.dumps({'dry_run':True,'runs':runs},indent=2));return 0
    write_json(session/'session.json',{'runs':runs})
    if args.benchmark=='category-smoke':write_report(session,session/'report')
    print('Session results:',session)
    return int(any(r['status'] in {'failed','completed_with_errors'} for r in runs))


def main(action=None,argv=None):
    if action is None:
        if len(sys.argv)<2 or sys.argv[1] not in {'setup','run'}:raise SystemExit('Usage: python -m llm_eval.workflow setup|run [options]')
        action=sys.argv[1];argv=sys.argv[2:]
    incoming = list(sys.argv[1:] if argv is None else argv)
    if '--campaign' in incoming:
        from .orchestration.cli import main as campaign_main
        incoming = [x for x in incoming if x not in {'--non-interactive','--interactive'}]
        return campaign_main([action, *incoming])
    if '--campaign-wizard' in incoming or (('--interactive' in incoming or (not incoming and sys.stdin.isatty())) and not any(x in incoming for x in ('--config','--platform','--os','--models'))):
        from .orchestration.cli import interactive
        return interactive(Path(__file__).resolve().parents[2], action)
    parser=parser_for(action);args=parser.parse_args(argv)
    prompts=Prompts(args.interactive or (not args.non_interactive and sys.stdin.isatty()))
    try:
        root=args.project_root.resolve()
        engines={p['id']:p for p in read_json(root/'catalog/platforms.json')['platforms']}
        models={m['id']:m for m in read_json(root/'catalog/models.json')['models']}
        categories={c['id']:c for c in read_json(root/'catalog/benchmarks.json')['categories']}
        if action=='run' and args.config:
            initial=read_json(args.config[0]);args.platform=args.platform or initial['platform'];args.os=args.os or initial['os_id']
        print('Platforms: '+', '.join(engines),file=sys.stderr)
        if prompts.interactive:
            print('Models: '+', '.join(m for m in models if models[m]['status']!='excluded'))
            print('Categories: '+', '.join(categories))
        args.platform=prompts.value('--platform',args.platform,choices=list(engines),required=True)
        detected=environment_kind();default_os=detected if detected in OS_IDS else None
        args.os=prompts.value('--os',args.os,default_os,list(OS_IDS),required=True)
        if engines[args.platform]['os_support'][args.os]=='unsupported':
            raise ValueError(f'{args.platform} has no supported native setup on {args.os}; use the Linux or WSL wrapper')
        args.prefix=Path(prompts.value('--prefix',args.prefix,root/'.platforms'/args.os/args.platform)).expanduser().resolve()
        if action=='setup':return setup_action(args,prompts,root,engines,models,categories)
        return run_action(args,prompts,root,engines,models,categories)
    except (ValueError,KeyError,OSError,RuntimeError,subprocess.CalledProcessError,subprocess.TimeoutExpired) as exc:
        parser.exit(2,f'{type(exc).__name__}: {exc}\n')
    except (KeyboardInterrupt,EOFError):parser.exit(130,'Cancelled.\n')


if __name__=='__main__':raise SystemExit(main())
