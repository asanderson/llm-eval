"""Export measured records, derive summaries, and finalize experiment runs."""
from __future__ import annotations
import csv
import gzip
import hashlib
import io
import json
import os
from collections import defaultdict
from pathlib import Path
import shutil
import statistics
import tempfile
import zlib

from llm_eval.common import read_json, digest, sha256_file
from llm_eval.core.contracts import atomic_json, TERMINAL, identifier
from llm_eval.report import quantile, safe_cell
from .index import identity
from llm_eval.experiments import plugin_hook, reporting_policy

PRIVATE={'api_key','password','secret','token','access_token','authorization','endpoint','host','repo_root','work_root',
         'root','prefix','artifact_root','artifact_lock','offload_dir','installation_state','worker_python','python',
         'path_mappings','lock_root','source','commands','argv','env','backend_pid','pid','hostname','username'}
BODIES={'messages','prompt','output','text','response','question','answer','choices','explanation','reasoning','completion'}


def sanitize(value, removed, include_outputs=False):
    if isinstance(value,dict):
        out={}
        for k,v in value.items():
            if k.lower() in PRIVATE or k.endswith('_env') or (not include_outputs and k.lower() in BODIES):
                removed.add(k);continue
            out[k]=sanitize(v,removed,include_outputs)
        return out
    if isinstance(value,list):return [sanitize(v,removed,include_outputs) for v in value]
    if isinstance(value,str) and (value.startswith('/') or (len(value)>2 and value[1]==':' and value[2] in '/\\')):
        removed.add('absolute_path_values');return '[local path omitted]'
    return value


def summaries(records):
    groups=defaultdict(list)
    for r in records:
        if r['record_type']!='request' or not r['latest_attempt'] or r['data'].get('warmup'):continue
        data=r['data'];key=(r['job_id'],data.get('category','unspecified'),data.get('benchmark','unspecified'))
        groups[key].append(data)
    result=[]
    for (job,category,benchmark),rows in sorted(groups.items()):
        ok=[r for r in rows if r.get('status')=='ok']
        record={'job_id':job,'category':category,'benchmark':benchmark,'synthetic':any(r.get('synthetic') for r in rows),
                'requests':len(rows),'successful_requests':len(ok),'errors_or_missing':len(rows)-len(ok)}
        for key in ['elapsed_s','router_s','generation_s','first_output_s','first_visible_s','output_tokens_per_wall_second',
                    'quality','oracle_regret','brier_score','estimated_generation_s','estimated_cost_usd']:
            values=[r[key] for r in ok if type(r.get(key)) in {int,float}]
            record[key+'_n']=len(values);record[key+'_median']=statistics.median(values) if values else None
            record[key+'_p95']=quantile(values,.95)
        labelled=[r for r in rows if r.get('expected_choice') is not None]
        record['decision_accuracy']=sum(r.get('decision_correct') is True for r in labelled)/len(labelled) if labelled else None
        record['decision_labelled_n']=len(labelled)
        checks=[r for r in rows if r.get('quality_check_applicable',r.get('quality_pass') is not None)]
        record['quality_pass_rate']=sum(r.get('quality_pass') is True and r.get('status')=='ok' for r in checks)/len(checks) if checks else None
        record['quality_check_n']=len(checks)
        record['abstentions']=sum(r.get('abstained',False) for r in rows)
        record['policy_violations']=sum(r.get('policy_violation',False) for r in rows)
        confusion=defaultdict(int)
        for r in labelled:confusion[(r['expected_choice'],r.get('choice') or '<invalid>')]+=1
        record['confusion']= [{'expected':a,'predicted':b,'count':n} for (a,b),n in sorted(confusion.items())]
        f1=[]
        for label in sorted({r['expected_choice'] for r in labelled}):
            tp=confusion[(label,label)];fp=sum(n for (a,b),n in confusion.items() if b==label and a!=label)
            fn=sum(n for (a,b),n in confusion.items() if a==label and b!=label)
            f1.append(2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else 0)
        record['macro_f1']=statistics.mean(f1) if f1 else None
        record['known_api_cost_usd']=sum((r.get('cost_usd') or 0)+(r.get('router_cost_usd') or 0) for r in rows)
        result.append(record)
    return result


def chart(rows,path,names=None):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    n=max(1,len(rows));fig,ax=plt.subplots(figsize=(9,max(2.5,n*.45)))
    values=[r.get('elapsed_s_median') for r in rows]
    ax.barh(range(len(rows)),[v or 0 for v in values],color='#3265a8')
    labels=[(names or {}).get(r['job_id'],r['job_id'][-12:])+' / '+r['category'] for r in rows]
    ax.set_yticks(range(len(rows)),labels);ax.invert_yaxis()
    ax.set_xlabel('Median successful request wall time (seconds)')
    ax.set_title('Experiment measurements'+(' — synthetic fixtures' if any(r['synthetic'] for r in rows) else ''))
    if not rows:ax.text(.5,.5,'No comparable request measurements',ha='center',transform=ax.transAxes)
    for i,v in enumerate(values):
        if v is None:ax.text(0,i,' unavailable',va='center')
    fig.tight_layout();path.parent.mkdir(parents=True,exist_ok=True)
    fig.savefig(path,dpi=130,metadata={'Software':'llm-eval'});plt.close(fig)


def canonical_json(value):
    """The one byte form of a JSON file in a projected bundle: sorted keys, two-space indent, UTF-8, LF, final newline."""
    return (json.dumps(value,indent=2,sort_keys=True,ensure_ascii=False,allow_nan=False)+'\n').encode('utf-8')


def canonical_csv(rows,fieldnames):
    """CSV with LF line ends, UTF-8; empty bytes without fields."""
    buffer=io.StringIO()
    if fieldnames:
        writer=csv.DictWriter(buffer,fieldnames=fieldnames,lineterminator='\n');writer.writeheader();writer.writerows(rows)
    return buffer.getvalue().encode('utf-8')


def canonical_gzip(data):
    """GZIP with a fixed header (no name, time 0, unknown OS) and stored deflate blocks: the bytes depend on `data` only,
    not on the platform, the Python version or the zlib build."""
    data=bytes(data);blocks=[data[i:i+65535] for i in range(0,len(data),65535)] or [b''];out=bytearray(b'\x1f\x8b\x08\x00\x00\x00\x00\x00\x00\xff')
    for i,block in enumerate(blocks):
        out+=bytes([1 if i==len(blocks)-1 else 0])+len(block).to_bytes(2,'little')+(len(block)^0xffff).to_bytes(2,'little')+block
    return bytes(out+zlib.crc32(data).to_bytes(4,'little')+(len(data)&0xffffffff).to_bytes(4,'little'))


def projected_bundle(experiment_dir,project):
    """({bundle path: bytes}, publication.json bytes) of a plugin projection, in memory: README.md, manifest.json, summary.json,
    summary.csv, resolved-config.json, the projection's extra files and raw/measurements.jsonl.gz, all canonical. No chart."""
    experiment_dir=Path(experiment_dir).resolve();campaign_dir=experiment_dir.parents[1]
    exp=read_json(experiment_dir/'experiment.json');plan=read_json(campaign_dir/'plan.json');state=read_json(campaign_dir/'campaign.json')
    p=project(campaign_dir,plan,state,exp);config=plan['reporting']
    publication_id=campaign_dir.name+'-'+identifier(exp['experiment_run_id'])
    rel=Path('docs/results')/identifier(exp['experiment_id'])/publication_id
    chart_rel=Path('diagrams/results')/exp['experiment_id']/publication_id/'latency.png'
    records,summary=p['records'],p['summary']
    raw=('\n'.join(json.dumps(r,sort_keys=True,ensure_ascii=False,allow_nan=False) for r in records)+'\n').encode()
    flat=[{k:safe_cell(json.dumps(v) if isinstance(v,(dict,list)) else v) for k,v in r.items()} for r in summary]
    named={'README.md':p['readme'].encode('utf-8'),'raw/measurements.jsonl.gz':canonical_gzip(raw),'summary.json':canonical_json(summary),
           'summary.csv':canonical_csv(flat,list(summary[0]) if summary else []),
           'resolved-config.json':canonical_json({'experiment':p['experiment'],'jobs':p['jobs'],'input_hashes':p['input_hashes']}),
           **{name:canonical_json(value) for name,value in p['files'].items()}}
    files={(rel/name).as_posix():named[name] for name in sorted(named)}
    complete=all(x['status'] in {'succeeded','skipped'} for x in p['coverage'])
    manifest={'schema_version':2,'experiment_id':exp['experiment_id'],'experiment_run_id':exp['experiment_run_id'],
              'publication_id':publication_id,'campaign_id':plan['campaign_id'],'created_utc':state['created_utc'],
              'code_revision':plan['code_revision'],'status':'complete' if complete else 'incomplete','synthetic':p['manifest']['synthetic'],
              'coverage':p['coverage'],'raw_records':len(records),'removed_fields':[],
              'files':{name:hashlib.sha256(data).hexdigest() for name,data in files.items()},
              **{k:v for k,v in p['manifest'].items() if k!='synthetic'}}
    manifest['report_fingerprint']=digest(manifest)
    files[(rel/'manifest.json').as_posix()]=canonical_json(manifest)
    publication=canonical_json({'repository':config.get('publish',{}).get('repository','asanderson/llm-eval'),
                                'base_branch':config.get('publish',{}).get('base_branch','main'),'report_path':rel.as_posix(),'chart_path':chart_rel.parent.as_posix(),
                                'report_fingerprint':manifest['report_fingerprint'],'experiment_id':exp['experiment_id'],'publication_id':publication_id,
                                'draft':not complete,'max_artifact_bytes':config.get('max_artifact_bytes',40*1024*1024),'code_revision':plan['code_revision']})
    return files,publication


def _write_projected(experiment_dir,files,publication):
    """Write a projected bundle byte for byte and swap it in as the generic report is swapped in."""
    report=experiment_dir/'report'
    temporary=Path(tempfile.mkdtemp(prefix='.report-',dir=experiment_dir))
    try:
        for name,data in files.items():
            path=temporary/'bundle'/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
        (temporary/'publication.json').write_bytes(publication)
        if (report/'publication-state.json').exists():shutil.copy2(report/'publication-state.json',temporary/'publication-state.json')
        old=experiment_dir/'.previous-report'
        if old.exists():shutil.rmtree(old)
        if report.exists():os.replace(report,old)
        os.replace(temporary,report)
        if old.exists():shutil.rmtree(old)
        return report
    finally:
        if temporary.exists():shutil.rmtree(temporary)


def build_report(experiment_dir):
    experiment_dir=Path(experiment_dir).resolve();campaign_dir=experiment_dir.parents[1]
    exp=read_json(experiment_dir/'experiment.json');plan=read_json(campaign_dir/'plan.json');state=read_json(campaign_dir/'campaign.json')
    config=plan['reporting'];removed=set();records=[];coverage=[]
    selected=[j for j in plan['jobs'] if j['job_id'] in exp['job_ids']];policy=reporting_policy(exp['experiment_id'],selected)
    if any(j.get('experiment_id',exp['experiment_id'])!=exp['experiment_id'] for j in selected):raise ValueError('Experiment identity does not match its planned jobs')
    if not policy['report']:raise ValueError('Report generation is disabled: '+policy['reason'])
    project=plugin_hook(exp['experiment_id'],'report_projection')
    if project:return _write_projected(experiment_dir,*projected_bundle(experiment_dir,project))      # before any generic scan
    for jid in exp['job_ids']:
        job_state=state['jobs'][jid]
        coverage.append({'job_id':jid,'status':job_state['status'],'reason':job_state.get('reason'),'attempts':len(job_state['attempts'])})
        for i,attempt in enumerate(job_state['attempts']):
            base=(campaign_dir/attempt['output']).resolve()
            if not base.is_relative_to(campaign_dir):raise ValueError('Attempt path escapes campaign')
            for path in sorted(base.rglob('*')):
                if path.is_symlink():raise ValueError('Symlink in measurement directory')
                if not path.is_file():continue
                if path.name in {'execution.json','heartbeat.json','cancel.json'}:continue
                kind=None;items=[]
                if path.name=='requests.jsonl':
                    kind='request';items=[json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line]
                elif path.name=='telemetry.json' or path.name=='load-telemetry.json':kind='telemetry';items=read_json(path)
                elif path.name=='replay-outcomes.json':kind='replay_corpus';items=[read_json(path)]
                elif path.name in {'job.json','result.json','metadata.json','host.json','routing-metadata.json','livebench-run.json'}:kind='metadata';items=[read_json(path)]
                elif path.suffix=='.jsonl' and 'model_judgment' in path.parts:
                    kind='judgment';items=[json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line]
                elif path.suffix=='.csv' and 'reports' in path.parts:
                    kind='benchmark_summary'
                    with path.open(encoding='utf-8',newline='') as f:items=list(csv.DictReader(f))
                if kind:
                    for item in items:
                        records.append({'job_id':jid,'attempt_id':attempt['attempt_id'],'latest_attempt':i==len(job_state['attempts'])-1,
                                        'record_type':kind,'source_file':path.relative_to(base).as_posix(),
                                        'data':sanitize(item,removed,config.get('include_outputs',False))})
    summary=summaries(records)
    publication_id=campaign_dir.name+'-'+identifier(exp['experiment_run_id'])
    rel=Path('docs/results')/identifier(exp['experiment_id'])/publication_id
    chart_rel=Path('diagrams/results')/exp['experiment_id']/publication_id/'latency.png'
    report=experiment_dir/'report'
    temporary=Path(tempfile.mkdtemp(prefix='.report-',dir=experiment_dir));bundle=temporary/'bundle';dest=bundle/rel
    dest.mkdir(parents=True)
    try:
        raw=('\n'.join(json.dumps(r,sort_keys=True,ensure_ascii=False,allow_nan=False) for r in records)+'\n').encode()
        (dest/'raw').mkdir();(dest/'raw/measurements.jsonl.gz').write_bytes(gzip.compress(raw,mtime=0))
        atomic_json(dest/'summary.json',summary)
        benchmark_rows=[{'job_id':r['job_id'],'source_file':r['source_file'],'data':r['data']} for r in records
                        if r['record_type']=='benchmark_summary' and r['latest_attempt']]
        atomic_json(dest/'benchmark-summary.json',benchmark_rows)
        flattened=[{'job_id':r['job_id'],'source_file':r['source_file'],**r['data']} for r in benchmark_rows]
        with (dest/'benchmark-summary.csv').open('w',encoding='utf-8',newline='') as f:
            if flattened:
                writer=csv.DictWriter(f,fieldnames=sorted({k for r in flattened for k in r}));writer.writeheader()
                writer.writerows({k:safe_cell(v) for k,v in r.items()} for r in flattened)
        with (dest/'summary.csv').open('w',encoding='utf-8',newline='') as f:
            if summary:
                writer=csv.DictWriter(f,fieldnames=list(summary[0]));writer.writeheader()
                writer.writerows({k:safe_cell(json.dumps(v) if isinstance(v,(dict,list)) else v) for k,v in r.items()} for r in summary)
        jobs=[j for j in plan['jobs'] if j['job_id'] in exp['job_ids']]
        atomic_json(dest/'resolved-config.json',sanitize({'experiment':exp,'jobs':jobs,'input_hashes':list(plan['inputs'].values())},removed,False))
        chart(summary,bundle/chart_rel,{j['job_id']:' / '.join(identity(j)) for j in jobs})
        complete=all(x['status'] in {'succeeded','skipped'} for x in coverage)
        synthetic=any(j['parameters'].get('synthetic') for j in jobs)
        status='complete' if complete else 'incomplete'
        metrics=['| Harness | Model | Category | Requests | Errors or missing | Quality passes | Decision accuracy | Median seconds | Output tokens/s | Job |','|---|---|---|---:|---:|---:|---:|---:|---:|---|']
        who={j['job_id']:identity(j) for j in jobs}
        for row in sorted(summary,key=lambda r:(*who.get(r['job_id'],('unknown','unknown')),r['category'])):
            def fmt(v):return 'unavailable' if v is None else f'{v:.4g}'
            harness,model=who.get(row['job_id'],('unknown','unknown'))
            passes='unavailable' if not row['quality_check_n'] else f"{round(row['quality_pass_rate']*row['quality_check_n'])}/{row['quality_check_n']}"
            metrics.append(f"| {harness} | {model} | {row['category']} | {row['requests']} | {row['errors_or_missing']} | {passes} | {fmt(row['decision_accuracy'])} | {fmt(row['elapsed_s_median'])} | {fmt(row['output_tokens_per_wall_second_median'])} | `{row['job_id'][-12:]}` |")
        image=os.path.relpath(chart_rel,rel).replace(os.sep,'/')
        text=f"# {exp['experiment_id']} results\n\nStatus: **{status}**. Synthetic fixtures: **{str(synthetic).lower()}**.\n\n"
        text+=f"Campaign: `{plan['campaign_id']}`. Experiment run: `{exp['experiment_run_id']}`. Measured code: `{plan['code_revision']}`.\n\n"
        text+='[Raw measurements](raw/measurements.jsonl.gz) · [JSON summary](summary.json) · [CSV summary](summary.csv) · [Manifest](manifest.json) · [Resolved configuration](resolved-config.json)\n\n'
        if benchmark_rows:
            text+='Upstream benchmark score tables: [JSON](benchmark-summary.json) · [CSV](benchmark-summary.csv). Each source cohort is retained separately.\n\n'
        text+='## Configuration coverage\n\n| Case | Hardware | OS | Harness | Model | Status |\n|---|---|---|---|---|---|\n'
        for j in sorted(jobs,key=identity):
            harness,model=identity(j)
            text+=f"| {j['case_id']} | {j['hardware_config_id']} | {j['hardware']['os_id']} | {harness} | {model} | {state['jobs'][j['job_id']]['status']} |\n"
        text+='\n## Measurements by harness and model\n\n'+'\n'.join(metrics)+f'\n\n![Request latency]({image})\n\n'
        text+='## Interpretation and reproduction\n\nWarmups and superseded attempts remain in raw data and are excluded from summaries. Each job/category is a separate cohort. Missing values remain unknown. Replay cost and generation latency are estimates; an offline oracle is an upper bound. LiveBench upstream grades are exported separately as judgment and benchmark summary records, not relabeled as local smoke scores.\n\n'
        text+='Use the measured code revision and resolved configuration to reconstruct the campaign with your local artifact paths and credential references. Verify the recorded input hashes. Run `llm-eval plan --campaign YOUR_CAMPAIGN.json` before `llm-eval run --campaign YOUR_CAMPAIGN.json`. Synthetic results do not establish model quality or hardware performance.\n'
        (dest/'README.md').write_text(text,encoding='utf-8')
        manifest={'schema_version':2,'experiment_id':exp['experiment_id'],'experiment_run_id':exp['experiment_run_id'],
                  'publication_id':publication_id,'campaign_id':plan['campaign_id'],'created_utc':state['created_utc'],
                  'code_revision':plan['code_revision'],'status':status,'synthetic':synthetic,'coverage':coverage,
                  'raw_records':len(records),'removed_fields':sorted(removed),
                  'files':{p.relative_to(bundle).as_posix():sha256_file(p) for p in sorted(bundle.rglob('*')) if p.is_file()}}
        manifest['report_fingerprint']=digest(manifest)
        atomic_json(dest/'manifest.json',manifest)
        atomic_json(temporary/'publication.json',{'repository':config.get('publish',{}).get('repository','asanderson/llm-eval'),
                    'base_branch':config.get('publish',{}).get('base_branch','main'),'report_path':rel.as_posix(),'chart_path':chart_rel.parent.as_posix(),
                    'report_fingerprint':manifest['report_fingerprint'],'experiment_id':exp['experiment_id'],'publication_id':publication_id,
                    'draft':not complete,'max_artifact_bytes':config.get('max_artifact_bytes',40*1024*1024),'code_revision':plan['code_revision']})
        # Preserve the last publication receipt across deterministic regeneration.
        if (report/'publication-state.json').exists():shutil.copy2(report/'publication-state.json',temporary/'publication-state.json')
        old=experiment_dir/'.previous-report'
        if old.exists():shutil.rmtree(old)
        if report.exists():os.replace(report,old)
        os.replace(temporary,report)
        if old.exists():shutil.rmtree(old)
        return report
    finally:
        if temporary.exists():shutil.rmtree(temporary)


def finalize_campaign(directory, coordinator_locked=False):
    if coordinator_locked:return _finalize_campaign(directory)
    from llm_eval.orchestration.resources import ProcessLock
    lock=ProcessLock(Path(directory)/'.coordinator.lock');lock.acquire()
    try:return _finalize_campaign(directory)
    finally:lock.close()


def _finalize_campaign(directory):
    directory=Path(directory);plan=read_json(directory/'plan.json');state=read_json(directory/'campaign.json')
    for exp in plan['experiments']:
        if not all(state['jobs'][j]['status'] in TERMINAL for j in exp['job_ids']):continue
        signature=digest([state['jobs'][j] for j in exp['job_ids']])
        prior=state['reports'].get(exp['experiment_run_id'],{})
        if prior.get('result_signature')==signature and prior.get('status') in {'generated','published'}:continue
        policy=reporting_policy(exp['experiment_id'],[j for j in plan['jobs'] if j['job_id'] in exp['job_ids']])
        if not policy['report']:
            # Not a failure: the attempt outputs stay local and no report bundle is written for these inputs.
            state['reports'][exp['experiment_run_id']]={'status':'disabled','reason':policy['reason'],'result_signature':signature}
            atomic_json(directory/'campaign.json',state);continue
        try:
            report=build_report(directory/'experiments'/exp['experiment_run_id'])
            receipt={'status':'generated','report':str(report.relative_to(directory))}
            if plan['reporting'].get('publish',{}).get('mode')=='pull-request' and policy['publish']:
                from .publish import publish_report
                publication=publish_report(report,Path(plan['root']))
                receipt.update(status='published',pull_request=publication['url'])
        except Exception as exc:
            receipt={'status':'failed','error_type':type(exc).__name__}
        receipt['result_signature']=signature
        state['reports'][exp['experiment_run_id']]=receipt
        atomic_json(directory/'campaign.json',state)
    return state['reports']
