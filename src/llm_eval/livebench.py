"""Explicit upstream LiveBench lane; never label local smoke checks as LiveBench."""
from __future__ import annotations

import datetime
import contextlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess

from .adapters import endpoint_parts
from .common import digest, read_json, sha256_file, write_json
from .provision import invoke

CATEGORY_PATHS = {'reasoning':'reasoning','coding':'coding','math':'math','data_analysis':'data_analysis',
                  'language':'language','instruction_following':'instruction_following','agentic_coding':'agentic_coding_v2'}
RELEASES = {'2024-06-24','2024-07-26','2024-08-31','2024-11-25','2025-04-02','2025-04-25',
            '2025-05-30','2025-11-25','2025-12-23','2026-01-08','2026-06-25'}


def question_manifest(data, categories, release):
    datetime.date.fromisoformat(release)
    if release not in RELEASES:raise ValueError('Release is not supported by the pinned LiveBench scorer')
    root=Path(data).resolve(); files=[]; counts={}; seen=set()
    def record(path, question_ids=None):
        if not path.resolve().is_relative_to(root) or path.is_symlink():
            raise ValueError('LiveBench data symlinks are not allowed')
        if path.stat().st_size>128*2**20:raise ValueError('Dataset file exceeds 128 MiB')
        entry={'path':path.relative_to(root).as_posix(),'sha256':sha256_file(path),'bytes':path.stat().st_size}
        if question_ids is not None:entry['eligible_question_ids']=question_ids
        files.append(entry)
    for category in categories:
        sub=CATEGORY_PATHS[category]
        if category=='agentic_coding' and not (root/'live_bench'/sub).exists():sub='agentic_coding'
        folder=root/'live_bench'/sub
        questions=sorted(folder.rglob('question.jsonl')) if folder.is_dir() else []
        count=0
        for path in questions:
            eligible=[]
            if not path.resolve().is_relative_to(root) or path.is_symlink():
                raise ValueError('LiveBench data symlinks are not allowed')
            if path.stat().st_size>128*2**20:raise ValueError('Question file exceeds 128 MiB')
            for line in path.read_text(encoding='utf-8').splitlines():
                if not line.strip():continue
                q=json.loads(line)
                allowed={category} if category!='agentic_coding' else {'agentic_coding','agentic_coding_v2'}
                if q.get('category') not in allowed:
                    raise ValueError('Question category does not match the selected dataset directory')
                qid=str(q['question_id']); key=(category,qid)
                if key in seen:raise ValueError('Duplicate LiveBench question ID within category')
                seen.add(key)
                added=str(q.get('livebench_release_date','')); removed=str(q.get('livebench_removal_date',''))
                if not re.fullmatch(r'\d{4}-\d{2}-\d{2}',added):raise ValueError('LiveBench question lacks a release date')
                if added in RELEASES and added<=release and (not removed or removed>release):
                    count+=1;eligible.append(qid)
            record(path,eligible)
            for tests in sorted(path.parent.glob('test_cases_*.jsonl')):
                record(tests)
        if not count:raise ValueError(f'No eligible local LiveBench questions for {category} in release {release}')
        counts[category]={'eligible_questions':count,'bench_name':'live_bench/'+sub}
    return {'release':release,'files':files,'categories':counts,
            'scope':'Local supplied question snapshot; coverage must be compared with the official release before claiming a full leaderboard-equivalent score.'}


def api_base(config):
    base=config.get('livebench_api_base')
    if not base:
        endpoint=endpoint_parts(config['endpoint'])
        if endpoint.path.endswith('/v1/chat/completions'):
            path=endpoint.path.removesuffix('/chat/completions')
        elif endpoint.path.endswith('/api/chat'):
            path=endpoint.path.removesuffix('/api/chat')+'/v1'
        else:
            raise ValueError('Set livebench_api_base for a nonstandard chat endpoint')
        base=endpoint._replace(path=path).geturl()
    parts=endpoint_parts(base)
    if not parts.path.rstrip('/').endswith('/v1'):raise ValueError('LiveBench API base must end in /v1')
    return base.rstrip('/')


def result_label(work):
    label=('local-'+Path(work).name+'-'+digest(str(Path(work).resolve()))[:12]).lower()
    if not re.fullmatch(r'[A-Za-z0-9_.-]+',label):raise ValueError('Unsafe LiveBench result label')
    return label


def result_coverage(source, manifest, label):
    """Require a finite judgment for each supplied eligible question, including zero scores."""
    coverage={}
    for category,info in manifest['categories'].items():
        record={'expected':0,'valid':0,'missing':0,'duplicates':0,'invalid':0,'execution_errors':0}
        for entry in manifest['files']:
            path=Path(entry['path'])
            if path.name!='question.jsonl' or not path.as_posix().startswith(info['bench_name']+'/'):continue
            expected=set(entry['eligible_question_ids']);record['expected']+=len(expected)
            judgments=Path(source)/'livebench/data'/path.parent/'model_judgment/ground_truth_judgment.jsonl'
            seen=set();valid=set()
            if judgments.is_file():
                if judgments.is_symlink():raise ValueError('Judgment symlinks are not accepted')
                with judgments.open(encoding='utf-8') as handle:
                    while line:=handle.readline(16*2**20+1):
                        if len(line)>16*2**20:raise ValueError('Judgment row exceeds size limit')
                        if not line.strip():continue
                        row=json.loads(line)
                        if str(row.get('model','')).lower()!=label:continue
                        qid=str(row.get('question_id',''))
                        if qid not in expected:continue
                        if qid in seen:record['duplicates']+=1
                        seen.add(qid)
                        score=row.get('score')
                        if (isinstance(score,bool) or not isinstance(score,(int,float))
                                or not math.isfinite(score) or not 0<=score<=1):
                            record['invalid']+=1;continue
                        if row.get('error') or row.get('eval_status') in {'api_error','eval_error','run_error','run_no_trajectory'}:
                            record['execution_errors']+=1;continue
                        valid.add(qid)
            record['valid']+=len(valid);record['missing']+=len(expected-seen)
        record['complete']=(record['expected']==record['valid'] and
                            not any(record[k] for k in ['missing','duplicates','invalid','execution_errors']))
        coverage[category]=record
    return coverage


def upstream_commands(config, state, manifest, work, categories, *, max_tokens, image=None):
    source=Path(work)/'source'; cwd=source/'livebench'; py=state['livebench_python']
    base=api_base(config);label=result_label(work)
    commands=[]
    for category in categories:
        bench=manifest['categories'][category]['bench_name']
        shared=['--bench-name',bench,'--question-source','jsonl','--livebench-release-option',manifest['release']]
        generation=[py,str(cwd/'gen_api_answer.py'),*shared,'--model',label,
                    '--model-display-name',label,'--api-base',base,'--model-provider-override','openai',
                    '--max-tokens',str(max_tokens),'--parallel','1','--no-incremental-grading']
        if category=='agentic_coding':generation+=['--agentic-parallel','1','--agentic-grading-parallel','1']
        commands.append({'phase':'generate','category':category,'argv':generation})
        # Regular grading runs in our isolated container. Agentic uses upstream's separate pipeline.
        if image:
            uid=f'{os.getuid()}:{os.getgid()}' if hasattr(os,'getuid') else '1000:1000'
            grading=['docker','run','--rm','--name',label+'-'+category,'--network','none','--read-only','--cap-drop','ALL',
                     '--security-opt','no-new-privileges','--pids-limit','256','--memory','8g','--cpus','8',
                     '--user',uid,'--tmpfs','/tmp:rw,nosuid,nodev,size=2g',
                     '--mount',f'type=bind,source={source.resolve()},target=/work/source,readonly',
                     '--workdir','/work/source/livebench','--env','PYTHONPATH=/work/source',
                     '--env','PYTHON_DOTENV_DISABLED=1','--env','MPLCONFIGDIR=/tmp/matplotlib']
            for entry in manifest['files']:
                path=Path(entry['path'])
                if path.name=='question.jsonl' and path.as_posix().startswith(bench+'/'):
                    directory=Path('livebench/data')/path.parent/'model_judgment'
                    grading+=['--mount',f'type=bind,source={(source/directory).resolve()},target=/work/source/{directory.as_posix()}']
            grading += [image,
                     'python','/work/source/livebench/gen_ground_truth_judgment.py',*shared,
                     '--model',label,'--model-display-name',label,'--parallel','1']
            # Agentic inference already performs task-specific container grading in upstream.
            if category!='agentic_coding':commands.append({'phase':'grade','category':category,'argv':grading})
        if category=='agentic_coding':
            # Upstream's incremental agent grader fills its cache, not final judgment JSONL.
            # This explicit opt-in phase orchestrates upstream Docker tests and exports judgments.
            commands.append({'phase':'agentic-grade','category':category,
                             'argv':[py,str(cwd/'gen_ground_truth_judgment.py'),*shared,
                                     '--model',label,'--model-display-name',label,'--parallel','1']})
        commands.append({'phase':'report','category':category,
                         'argv':[py,str(cwd/'show_livebench_result.py'),*shared,'--model-list',label]})
    return sorted(commands,key=lambda c: {'generate':0,'grade':1,'agentic-grade':1,'report':2}[c['phase']])


def run_livebench(config,state,categories,data,release,output,*,image,allow_agentic=False,dry_run=False,backend=None,host=None):
    if config['protocol']=='worker':
        raise ValueError('Upstream LiveBench requires an OpenAI-compatible server; Accelerate/AirLLM use category-smoke in this harness')
    if not state.get('livebench_source') or not state.get('livebench_python'):
        raise ValueError('Run platform setup with --with-livebench first')
    if 'agentic_coding' in categories and not allow_agentic:
        raise ValueError('Agentic Coding starts upstream-managed Docker build/agent workloads. Use --allow-agentic-execution after reviewing docs/LIVEBENCH.md.')
    if not image:raise ValueError('--livebench-image is required for isolated upstream grading')
    if ',' in str(Path(output).resolve()):raise ValueError('Docker mount paths must not contain commas')
    manifest=question_manifest(data,categories,release)
    commands=upstream_commands(config,state,manifest,output,categories,max_tokens=config['max_output_tokens'],image=image)
    if dry_run:return {'question_snapshot':manifest,'commands':commands}
    source=Path(state['livebench_source'])
    actual=invoke(['git','-C',source,'rev-parse','HEAD'],capture=True).stdout.strip()
    dirty=invoke(['git','-C',source,'status','--porcelain','--untracked-files=no'],capture=True).stdout.strip()
    if actual!=state['livebench_revision'] or dirty:raise ValueError('LiveBench source must match its clean pinned revision')
    # Resolve the tag once and execute the immutable local image ID.
    image_id=invoke(['docker','image','inspect','--format','{{.Id}}',image],capture=True).stdout.strip()
    if not re.fullmatch(r'sha256:[0-9a-f]{64}',image_id):raise ValueError('Cannot resolve LiveBench grading image')
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    copied=output/'source'
    shutil.copytree(source,copied,ignore=shutil.ignore_patterns('.git','.venv','data','.env','__pycache__'))
    label=result_label(output)
    # A unique model entry bypasses upstream preset aliases and preserves the exact local API name.
    # JSON is valid YAML, which is the format read by the pinned upstream config loader.
    local_model={'display_name':label,'api_name':{'openai':config['served_model']},
                 'default_provider':'openai','api_kwargs':{}}
    write_json(copied/'livebench/model/model_configs'/('llm_eval_'+label+'.yaml'),local_model)
    for entry in manifest['files']:
        src=Path(data)/entry['path']; dest=copied/'livebench/data'/entry['path']
        if sha256_file(src)!=entry['sha256']:raise ValueError('Question snapshot changed during preparation')
        dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(src,dest)
        if dest.name=='question.jsonl':(dest.parent/'model_judgment').mkdir(exist_ok=True)
    commands=upstream_commands(config,state,manifest,output,categories,max_tokens=config['max_output_tokens'],image=image_id)
    metadata={'benchmark':'livebench-upstream','status':'running','config':config,'host':host,'question_snapshot':manifest,
              'local_model_config':local_model,'local_model_config_sha256':digest(local_model),
              'upstream_revision':actual,'grader_image':image_id,'commands':commands,
              'agentic_execution':'upstream Docker agent/build pipeline' if allow_agentic else 'disabled',
              'score_comparability':'Unverified until exact question coverage, settings, and scorer match a published release; not automatically a leaderboard score.'}
    if config.get('artifact_lock'):
        metadata['artifact']=read_json(config['artifact_lock'])
        metadata['artifact_sha256']=digest(metadata['artifact'])
    write_json(output/'livebench-run.json',metadata)
    env=os.environ.copy()
    for k in list(env):
        if any(part in k.upper() for part in ('TOKEN','SECRET','PASSWORD','API_KEY')) or k.lower() in {'http_proxy','https_proxy','all_proxy'}:
            env.pop(k)
    api_key=os.environ.get(config.get('api_key_env',''),'local-unused')
    env.update(PYTHONPATH=str(copied),PYTHON_DOTENV_DISABLED='1',LIVEBENCH_API_KEY=api_key,
               OPENAI_API_KEY=api_key,HF_HUB_OFFLINE='1',HF_DATASETS_OFFLINE='1',HF_HUB_DISABLE_TELEMETRY='1')
    def execute(steps):
        for index,step in steps:
            with (output/f'{index:02d}-{step["category"]}-{step["phase"]}.log').open('w',encoding='utf-8') as log:
                try:
                    subprocess.run(step['argv'],cwd=copied/'livebench',env=env,stdout=log,stderr=subprocess.STDOUT,
                                   check=True,timeout=config.get('livebench_timeout_s',86400),shell=False)
                    if step['phase']=='report':
                        report=output/'reports'/step['category'];report.mkdir(parents=True,exist_ok=True)
                        for name in ['df_raw.csv','all_tasks.csv','all_groups.csv','latex_table.csv']:
                            csv_file=copied/'livebench'/name
                            if csv_file.is_file():
                                shutil.copyfile(csv_file,report/name)
                                csv_file.unlink()
                finally:
                    if step['phase']=='grade':
                        name=step['argv'][step['argv'].index('--name')+1]
                        subprocess.run(['docker','rm','-f',name],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                                       timeout=30,check=False,shell=False)
    try:
        with backend if backend is not None else contextlib.nullcontext():
            execute([(i,s) for i,s in enumerate(commands) if s['phase']=='generate'])
        # Release managed model memory before the CPU grading container starts.
        execute([(i,s) for i,s in enumerate(commands) if s['phase'] in {'grade','agentic-grade'}])
        metadata['coverage']=result_coverage(copied,manifest,label)
        if not all(c['complete'] for c in metadata['coverage'].values()):
            raise RuntimeError('LiveBench judgments are incomplete or contain execution errors; inspect coverage in livebench-run.json')
        execute([(i,s) for i,s in enumerate(commands) if s['phase']=='report'])
        metadata['status']='completed'
    except BaseException as exc:
        metadata.update(status='failed',error_type=type(exc).__name__)
        raise
    finally:write_json(output/'livebench-run.json',metadata)
    return output
