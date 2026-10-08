"""Publish an immutable result bundle through a GitHub pull request."""
from __future__ import annotations
import http.client
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from urllib.parse import urlencode

from llm_eval.common import read_json, sha256_file
from llm_eval.core.contracts import atomic_json
from llm_eval.orchestration.resources import ProcessLock


class GitHub:
    def __init__(self, repository, token):
        if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',repository):raise ValueError('Invalid repository')
        if not token:raise ValueError('Set GH_TOKEN or GITHUB_TOKEN to publish results')
        self.repository=repository;self.token=token
    def request(self,method,path,body=None):
        conn=http.client.HTTPSConnection('api.github.com',timeout=30)
        try:
            conn.request(method,'/repos/'+self.repository+path,body=json.dumps(body).encode() if body is not None else None,
                         headers={'Authorization':'Bearer '+self.token,'Accept':'application/vnd.github+json','User-Agent':'llm-eval','Content-Type':'application/json'})
            response=conn.getresponse();data=response.read(8*1024*1024+1)
            if response.status not in {200,201}:raise RuntimeError('GitHub publication HTTP status '+str(response.status))
            if len(data)>8*1024*1024:raise ValueError('GitHub response too large')
            return json.loads(data)
        finally:conn.close()
    def find(self,branch):
        matches=self.request('GET','/pulls?'+urlencode({'head':self.repository.split('/')[0]+':'+branch,'state':'all','per_page':100}))
        return next((p for p in matches if p['state']=='open'),matches[0] if matches else None)


def git(root,*args,env=None,check=True):
    p=subprocess.run(['git','-C',str(root),*map(str,args)],capture_output=True,text=True,env=env,timeout=120)
    if check and p.returncode:raise RuntimeError('Git operation failed: '+str(args[0])+' (working tree and local report preserved)')
    return p.stdout.strip() if check else p


def validate_bundle(report):
    report=Path(report);spec=read_json(report/'publication.json');bundle=report/'bundle'
    rel=Path(spec['report_path']);charts=Path(spec['chart_path'])
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._/-]*',spec['base_branch']) or '..' in spec['base_branch']:
        raise ValueError('Invalid publication base branch')
    if rel.is_absolute() or '..' in rel.parts or charts.is_absolute() or '..' in charts.parts:
        raise ValueError('Unsafe publication destination')
    if rel.parts[:2]!=('docs','results') or charts.parts[:2]!=('diagrams','results'):raise ValueError('Publication is restricted to result documentation')
    manifest=read_json(bundle/rel/'manifest.json')
    if manifest['report_fingerprint']!=spec['report_fingerprint']:raise ValueError('Report fingerprint mismatch')
    from llm_eval.common import digest
    if digest({k:v for k,v in manifest.items() if k!='report_fingerprint'})!=manifest['report_fingerprint']:raise ValueError('Manifest integrity failure')
    expected=set(manifest['files'])|{(rel/'manifest.json').as_posix()};actual=set();size=0
    for path in bundle.rglob('*'):
        if path.is_symlink():raise ValueError('Symlink in publication bundle')
        if not path.is_file():continue
        name=path.relative_to(bundle).as_posix();actual.add(name);size+=path.stat().st_size
        if not (path.is_relative_to(bundle/rel) or path.is_relative_to(bundle/charts)):raise ValueError('Unexpected publication path')
        if name in manifest['files'] and sha256_file(path)!=manifest['files'][name]:raise ValueError('Report file integrity failure')
    if actual!=expected:raise ValueError('Report file inventory changed')
    if size>spec['max_artifact_bytes']:raise ValueError('Report exceeds artifact-size limit; complete local bundle retained')
    return spec,manifest,size


def write_index(worktree):
    root=Path(worktree)/'docs/results';rows=[]
    for path in sorted(root.glob('*/*/manifest.json')):
        m=read_json(path);link=(path.parent/'README.md').relative_to(root).as_posix()
        rows.append(f"| {m['experiment_id']} | {m['created_utc']} | {m['status']} | {m['synthetic']} | [Report]({link}) |")
    root.mkdir(parents=True,exist_ok=True)
    (root/'README.md').write_text('# Experiment results\n\nEach report includes raw measurements, summaries and reproducibility metadata. Synthetic fixtures are explicitly labeled.\n\n| Experiment | Run time UTC | Status | Synthetic | Results |\n|---|---|---|---|---|\n'+'\n'.join(rows)+'\n',encoding='utf-8')
    readme=Path(worktree)/'README.md'
    text=readme.read_text(encoding='utf-8') if readme.exists() else '# llm-eval\n'
    if 'docs/results/README.md' not in text:
        readme.write_text(text+'\n## Experiment results\n\nSee the [experiment results](docs/results/README.md) for raw data, summaries and reproducible reports.\n',encoding='utf-8')


def publish_report(report,root,dry_run=False,api=None):
    report=Path(report).resolve();root=Path(root).resolve()
    spec,manifest,size=validate_bundle(report)
    branch='results/'+spec['experiment_id']+'/'+spec['publication_id']
    if dry_run:return {'branch':branch,'bytes':size,'files':list(manifest['files']),'dry_run':True}
    lock=ProcessLock(report/'.publish.lock');lock.acquire()
    try:
        token=os.environ.get('GH_TOKEN') or os.environ.get('GITHUB_TOKEN')
        api=api or GitHub(spec['repository'],token)
        fingerprint=spec['report_fingerprint'];existing=api.find(branch)
        if existing and existing['state']!='open':
            if existing.get('merged_at') and ('Report fingerprint: '+fingerprint) in (existing.get('body') or ''):
                receipt={'url':existing['html_url'],'branch':branch,'fingerprint':fingerprint,'status':'merged'}
                atomic_json(report/'publication-state.json',receipt);return receipt
            branch+='-'+fingerprint[:12];existing=api.find(branch)
        remote=git(root,'remote','get-url','origin')
        allowed={'https://github.com/'+spec['repository']+'.git','https://github.com/'+spec['repository'],
                 'git@github.com:'+spec['repository']+'.git'}
        if remote not in allowed:raise ValueError('origin does not match the publication repository')
        with tempfile.TemporaryDirectory(prefix='llm-eval-publish-') as tmp:
            temp=Path(tmp);worktree=temp/'checkout';env=os.environ.copy();env['GIT_TERMINAL_PROMPT']='0'
            if token:
                env['LLM_EVAL_PUBLISH_TOKEN']=token
                helper=temp/'askpass.py';helper.write_text("#!/usr/bin/env python3\nimport os,sys\nprint('x-access-token' if 'username' in sys.argv[-1].lower() else os.environ['LLM_EVAL_PUBLISH_TOKEN'])\n",encoding='utf-8');helper.chmod(0o700)
                if os.name=='nt':
                    wrapper=temp/'askpass.cmd';wrapper.write_text('@"'+sys.executable+'" "'+str(helper)+'" %*\r\n');env['GIT_ASKPASS']=str(wrapper)
                else:env['GIT_ASKPASS']=str(helper)
            git(root,'fetch','origin',spec['base_branch'],env=env)
            base='origin/'+spec['base_branch']
            found=git(root,'ls-remote','--heads','origin',branch,env=env)
            if found:
                git(root,'fetch','origin',branch,env=env);start='origin/'+branch
            else:start=base
            git(root,'worktree','add','--detach',worktree,start,env=env)
            try:
                if found:
                    merge=git(worktree,'merge','--no-commit','--no-ff',base,env=env,check=False)
                    if merge.returncode:
                        conflicts=git(worktree,'diff','--name-only','--diff-filter=U',env=env).splitlines()
                        if conflicts!=['docs/results/README.md']:
                            git(worktree,'merge','--abort',env=env,check=False);raise RuntimeError('Results branch needs conflict resolution')
                for relative in [spec['report_path'],spec['chart_path']]:
                    shutil.copytree(report/'bundle'/relative,worktree/relative,dirs_exist_ok=True)
                write_index(worktree)
                git(worktree,'add','-f','--',spec['report_path'],spec['chart_path'],'docs/results/README.md','README.md',env=env)
                changed=git(worktree,'diff','--cached','--quiet',env=env,check=False).returncode!=0
                merging=git(worktree,'rev-parse','--verify','MERGE_HEAD',env=env,check=False).returncode==0
                if changed or merging:
                    git(worktree,'-c','user.name=llm-eval results','-c','user.email=llm-eval@users.noreply.github.com','commit','-m','results: '+spec['publication_id'],env=env)
                head=git(worktree,'rev-parse','HEAD',env=env)
                git(worktree,'push','origin','HEAD:refs/heads/'+branch,env=env)
            finally:
                git(root,'worktree','remove','--force',worktree,env=env,check=False)
            body=(f"This experiment report adds raw measurements, JSON/CSV summaries, configuration coverage and PNG charts to the results documentation.\n\n"
                  f"Experiment: {manifest['experiment_id']}\nCampaign: {manifest['campaign_id']}\nStatus: {manifest['status']}\nSynthetic: {manifest['synthetic']}\n"
                  f"Measured code: {spec['code_revision']}\nReport: {spec['report_path']}/README.md\nRaw data: {spec['report_path']}/raw/measurements.jsonl.gz\n"
                  f"Validation: bundle checksums, file inventory and size checked before push.\nReproduction: use the measured revision and resolved-config.json to bind local artifacts, then run llm-eval plan/run --campaign YOUR_CAMPAIGN.json.\n\nReport fingerprint: {fingerprint}")
            existing=api.find(branch) # Recover a previous push/PR race without duplicating the PR.
            if existing and existing['state']=='open':
                pr=api.request('PATCH','/pulls/'+str(existing['number']),{'body':body})
            else:
                pr=api.request('POST','/pulls',{'head':branch,'base':spec['base_branch'],'title':'results: '+spec['publication_id'],'body':body,'draft':spec['draft']})
            receipt={'url':pr['html_url'],'branch':branch,'commit':head,'fingerprint':fingerprint,'status':'open'}
            atomic_json(report/'publication-state.json',receipt);return receipt
    except Exception as exc:
        atomic_json(report/'publication-error.json',{'status':'pending','error_type':type(exc).__name__})
        raise
    finally:lock.close()
