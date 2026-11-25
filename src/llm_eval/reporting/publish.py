"""Publish an immutable result bundle through a GitHub pull request."""
from __future__ import annotations
import contextlib
import gzip
import hashlib
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


def _inspect_bundle(report):
    report=Path(report);spec=read_json(report/'publication.json');bundle=report/'bundle'
    rel=Path(spec['report_path']);charts=Path(spec['chart_path'])
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._/-]*',spec['base_branch']) or '..' in spec['base_branch']:
        raise ValueError('Invalid publication base branch')
    if rel.is_absolute() or '..' in rel.parts or charts.is_absolute() or '..' in charts.parts:
        raise ValueError('Unsafe publication destination')
    if rel.parts[:2]!=('docs','results') or charts.parts[:2]!=('diagrams','results'):raise ValueError('Publication is restricted to result documentation')
    manifest_data=(bundle/rel/'manifest.json').read_bytes()
    manifest=json.loads(manifest_data)
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
    return spec,manifest,size,hashlib.sha256(manifest_data).hexdigest()


def validate_bundle(report):
    return _inspect_bundle(report)[:3]


def _blob(root,ref):
    """The bytes of one Git object, undecoded (the `git` helper decodes and strips)."""
    p=subprocess.run(['git','-C',str(root),'cat-file','blob',ref],capture_output=True,timeout=120)
    if p.returncode:raise RuntimeError('Git operation failed: cat-file (working tree and local report preserved)')
    return p.stdout


def _check_blobs(worktree,spec,manifest,manifest_sha,prefix,env):
    """Verify inventory and exact bytes in the index and the commit, including any per-run chart."""
    expected={**manifest['files'],(Path(spec['report_path'])/'manifest.json').as_posix():manifest_sha}
    roots=(spec['report_path'],spec['chart_path'])
    if prefix == ':':
        listed=git(worktree,'ls-files','--stage','--',*roots,env=env)
        inventory_error='Staged files differ from the manifest'
    else:
        listed=git(worktree,'ls-tree','-r',prefix[:-1],'--',*roots,env=env)
        inventory_error='Committed files differ from the manifest'
    inventory={}
    for line in listed.splitlines():
        metadata,name=line.split('\t',1)
        inventory[name]=metadata.split()[0]
    if set(inventory)!=set(expected) or any(mode!='100644' for mode in inventory.values()):
        raise ValueError(inventory_error)
    for name,sha in sorted(expected.items()):
        data=_blob(worktree,prefix+name)
        if hashlib.sha256(data).hexdigest()!=sha:
            raise ValueError('Committed bytes differ from the manifest: '+name)
        if name.endswith(('.md','.csv','.json')) and b'\r' in data:
            raise ValueError('Report text must use LF line endings: '+name)


def write_index(worktree):
    # The results README, its charts and the index pages are generated together from the published bundles.
    from .index import write_results_index
    write_results_index(worktree)
    readme=Path(worktree)/'README.md'
    text=readme.read_text(encoding='utf-8') if readme.exists() else '# llm-eval\n'
    if 'docs/results/README.md' not in text:
        readme.write_text(text+'\n## Experiment results\n\nSee the [experiment results](docs/results/README.md) for raw data, summaries and reproducible reports.\n',encoding='utf-8')


def _campaign_names(report):
    """Experiment identities the campaign record holds when the report sits anywhere below a campaign directory (the nearest
    directory above it that holds a `plan.json`, whatever the directories in between are called). In the standard layout
    (`<campaign>/experiments/<run>/report`) they are the plan's experiment and jobs of this run, the experiment record, and
    each attempt's job.json and metadata.json; elsewhere below the campaign, the same of every run of the campaign. Empty for
    a report below no campaign."""
    campaign=next((d for d in report.parents if (d/'plan.json').is_file()),None)
    if campaign is None:return set()
    experiment_dir=report.parent
    run=experiment_dir.name if report.name=='report' and experiment_dir.parent.name=='experiments' and experiment_dir.parent.parent==campaign else None
    names=set()
    try:
        plan=read_json(campaign/'plan.json');state=read_json(campaign/'campaign.json') if (campaign/'campaign.json').is_file() else {}
        records=[experiment_dir/'experiment.json'] if run else sorted((campaign/'experiments').glob('*/experiment.json'))
        for path in records:
            if path.is_file():names.add(read_json(path).get('experiment_id'))
        names|={e.get('experiment_id') for e in plan.get('experiments',[]) if isinstance(e,dict) and run in (None,e.get('experiment_run_id'))}
        jobs=[j for j in plan.get('jobs',[]) if isinstance(j,dict) and run in (None,j.get('experiment_run_id'))]
        names|={j.get('experiment_id') for j in jobs}
        for job in jobs:
            for attempt in ((state.get('jobs') or {}).get(job.get('job_id')) or {}).get('attempts') or []:
                out=campaign/str(attempt.get('output',''))
                for name in ('job.json','metadata.json'):
                    if (out/name).is_file():
                        data=read_json(out/name)
                        if isinstance(data,dict):names|={data.get('experiment_id'),data.get('experiment')}
    except (OSError,ValueError,AttributeError,TypeError):
        raise ValueError('Malformed campaign record') from None
    from llm_eval.experiments import canonical, registered
    # Only experiment ids count (metadata holds other strings too), each by its current id: a renamed experiment's former id is the same experiment.
    return {canonical(n) for n in names if isinstance(n,str) and registered(n)}


@contextlib.contextmanager
def _private_ref(root,name):
    # A ref that lives for one publication: deleted when it ends, published or refused.
    try:yield name
    finally:git(root,'update-ref','-d',name,check=False)


def _check_remote(root, remote, repository, push=False):
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',repository):
        raise ValueError('Invalid publication repository')
    args=('remote','get-url',*(['--push','--all'] if push else []),remote)
    url=git(root,*args)
    allowed={'https://github.com/'+repository+'.git','https://github.com/'+repository,
             'git@github.com:'+repository+'.git','ssh://git@github.com/'+repository+'.git'}
    if url not in allowed:
        raise ValueError(remote+' does not match the publication repository '+repository)


def _commit_bundle(report,worktree,spec,manifest,manifest_sha,env):
    paths=[spec['report_path']]
    if (report/'bundle'/spec['chart_path']).exists():
        paths.append(spec['chart_path'])
    for relative in paths:
        shutil.copytree(report/'bundle'/relative,worktree/relative,dirs_exist_ok=True)
    write_index(worktree)
    generated=[path for path in ('docs/results/index','diagrams/results/summary')
               if (worktree/path).exists() or git(worktree,'ls-files','--',path,env=env)]
    git(worktree,'add','-f','-A','--',*paths,'docs/results/README.md','README.md',*generated,env=env)
    _check_blobs(worktree,spec,manifest,manifest_sha,':',env)
    changed=git(worktree,'diff','--cached','--quiet',env=env,check=False).returncode!=0
    merging=git(worktree,'rev-parse','--verify','MERGE_HEAD',env=env,check=False).returncode==0
    if changed or merging:
        git(worktree,'-c','user.name=llm-eval results','-c','user.email=llm-eval@users.noreply.github.com',
            'commit','-m','results: '+spec['publication_id'],env=env)
    head=git(worktree,'rev-parse','HEAD',env=env)
    _check_blobs(worktree,spec,manifest,manifest_sha,head+':',env)
    return head


def _prepare_fork(report,root,spec,manifest,manifest_sha,branch,fork):
    """Prepare a verified local branch from upstream for a contributor who can push only to their fork."""
    if fork.casefold()==spec['repository'].casefold():
        raise ValueError('Specify your own GitHub fork for --prepare-fork')
    _check_remote(root,'upstream',spec['repository'])
    _check_remote(root,'origin',fork,push=True)
    env={**os.environ,'GIT_TERMINAL_PROMPT':'0'}
    # A private ref per invocation also works in shallow clones and nonstandard fetch configurations.
    with tempfile.TemporaryDirectory(prefix='llm-eval-fork-') as tmp:
        worktree=Path(tmp)/'checkout'
        with _private_ref(root,'refs/llm-eval/'+Path(tmp).name) as base:
            git(root,'fetch','--no-tags','upstream','+refs/heads/'+spec['base_branch']+':'+base,env=env)
            if git(root,'ls-tree',base,'--',spec['report_path'],spec['chart_path'],env=env):
                raise ValueError('The publication ID already exists upstream. Submit a new run as a separate bundle.')
            git(root,'worktree','add','--detach',worktree,base,env=env)
            try:
                commit=_commit_bundle(report,worktree,spec,manifest,manifest_sha,env)
                ref='refs/heads/'+branch
                old=git(root,'rev-parse','--verify',ref,env=env,check=False)
                if old.returncode==0:
                    old=old.stdout.strip()
                    if (git(root,'rev-parse',old+'^{tree}',env=env)!=git(root,'rev-parse',commit+'^{tree}',env=env)
                        or git(root,'show','-s','--format=%P',old,env=env)!=git(root,'rev-parse',base,env=env)):
                        raise ValueError('A different local branch already uses this publication ID: '+branch)
                    commit=old
                else:
                    git(root,'update-ref',ref,commit,'',env=env)
            finally:
                git(root,'worktree','remove','--force',worktree,env=env,check=False)
    owner=fork.split('/')[0]
    return {'status':'prepared','branch':branch,'commit':commit,'base':spec['base_branch'],
            'push':'git push origin '+commit+':refs/heads/'+branch,
            'compare_url':'https://github.com/'+spec['repository']+'/compare/'+spec['base_branch']+'...'+owner+':'+branch+'?expand=1',
            'draft':spec['draft'],'report_path':spec['report_path'],'fingerprint':spec['report_fingerprint']}


def publish_report(report,root,dry_run=False,api=None,prepare_fork=None):
    report=Path(report).resolve();root=Path(root).resolve()
    spec,manifest,size,manifest_sha=_inspect_bundle(report)
    # Decided from every experiment identity the bundle carries, not from one label a caller could edit.
    from llm_eval.experiments import REGISTRY, canonical, get_experiment, plugin_hook, reporting_policy
    dest=report/'bundle'/spec['report_path'];raw=dest/'raw/measurements.jsonl.gz'
    if not raw.is_file():raise ValueError('Publication needs the raw measurements archive')
    # The generic build always writes both summaries; a projected (canonical) bundle has its plugin summary instead.
    for file in ('summary.json','legal-summary.json' if manifest.get('canonical_bytes') else 'benchmark-summary.json'):
        if not (dest/file).is_file():raise ValueError('Publication needs the report summary: '+file)
    try:records=[json.loads(line) for line in gzip.decompress(raw.read_bytes()).decode('utf-8').splitlines() if line]
    except (OSError,EOFError,UnicodeDecodeError,ValueError,RecursionError):raise ValueError('Malformed raw measurements archive') from None
    if not all(isinstance(r,dict) and isinstance(r.get('data',{}),dict) for r in records):raise ValueError('Malformed raw measurements archive')
    try:
        resolved=read_json(dest/'resolved-config.json');jobs=resolved['jobs']
        names={spec['experiment_id'],manifest['experiment_id'],resolved['experiment']['experiment_id'],*(j['experiment_id'] for j in jobs),
               Path(spec['report_path']).parts[2],Path(spec['chart_path']).parts[2]}
        benchmarks=[r.get('data',{}).get('benchmark') for r in records if r.get('record_type') in {'request','metadata'}]
        for file in ('summary.json','benchmark-summary.json'):
            if not (dest/file).is_file():continue      # a canonical bundle has no benchmark summary
            rows=read_json(dest/file)
            benchmarks+=[v for row in rows for v in (row.get('benchmark'),(row.get('data') if isinstance(row.get('data'),dict) else {}).get('benchmark'))]
        for r in records:
            if r.get('record_type')=='metadata':names|={v for v in (r.get('data',{}).get('experiment_id'),r.get('data',{}).get('experiment')) if isinstance(v,str)}
        if not all(isinstance(j,dict) and isinstance(j.get('experiment_id'),str) for j in jobs):raise TypeError
    except (IndexError,TypeError,KeyError,AttributeError):raise ValueError('Malformed publication bundle') from None
    for name in sorted(names,key=str):      # the name is not echoed: it is text from the bundle
        if canonical(name) not in REGISTRY:raise ValueError('Publication is not available for an unregistered experiment')
    names={canonical(n) for n in names}      # a renamed experiment's former id (a bundle of a campaign planned before the rename) is the same experiment
    claims={e:getattr(get_experiment(e),'claims_benchmark',None) for e in REGISTRY}
    claimed={e for e,claim in claims.items() if claim for b in benchmarks if isinstance(b,str) and claim(b)}
    if claimed-names:      # a benchmark name another experiment's plugin writes: its own refusal, before any verification
        raise ValueError('Publication identity mismatch: the bundle carries a legal benchmark name')
    for name in sorted(names,key=str):
        verify=plugin_hook(name,'verify_publication')
        if verify:      # the plugin rebuilds and verifies the bundle itself; a label never authorizes its export
            try:verify(report,root)
            except ValueError as exc:raise ValueError('Publication is not available for '+name+': '+str(exc)) from None
            continue
        policy=reporting_policy(name,[])
        if not policy['publish']:raise ValueError('Publication is not available for '+name+': '+policy['reason'])
    declared={m for e in REGISTRY for m in get_experiment(e).MANIFEST['modes']}
    for j in jobs:      # a planned job's mode belongs to its experiment: a relabelled job keeps the mode it ran in
        if j.get('mode') not in get_experiment(j['experiment_id']).MANIFEST['modes']:      # bundle text is echoed only if it is a mode
            raise ValueError('Publication identity mismatch: mode '+(j.get('mode') if j.get('mode') in declared else 'mode')+' is not a mode of '+j['experiment_id'])
    if len(names)>1:raise ValueError('Publication identity mismatch')
    if _campaign_names(report)-names:      # the campaign record this report sits in names another experiment
        raise ValueError('Publication identity mismatch: the campaign record names '+', '.join(sorted(_campaign_names(report)-names)))
    for name in sorted(REGISTRY):      # content another experiment's plugin recognises as its own, whatever the labels say
        claim=plugin_hook(name,'claims_bundle')
        found=claim(report,dest,manifest,resolved,records) if claim and name not in names else None
        if found:      # the class of the matched mark, never text from the bundle
            raise ValueError('Publication identity mismatch: the bundle carries content of '+name+' ('+(found if isinstance(found,str) else 'content')+')')
    branch='results/'+spec['experiment_id']+'/'+spec['publication_id']
    if prepare_fork and any(plugin_hook(name,'verify_publication') for name in names):
        raise ValueError('Fork preparation is unavailable for a restricted projection. Use its authorized upstream publication workflow.')
    if dry_run:return {'branch':branch,'bytes':size,'files':list(manifest['files']),'dry_run':True}
    expected_path=Path('docs/results')/spec['experiment_id']/spec['publication_id']
    expected_chart=Path('diagrams/results')/spec['experiment_id']/spec['publication_id']
    if (len(expected_path.parts)!=4 or expected_path.as_posix()!=spec['report_path']
        or expected_chart.as_posix()!=spec['chart_path'] or manifest['publication_id']!=spec['publication_id']):
        raise ValueError('Publication paths must identify one experiment run')
    git(root,'check-ref-format','--branch',branch)
    if prepare_fork:
        return _prepare_fork(report,root,spec,manifest,manifest_sha,branch,prepare_fork)
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
        _check_remote(root,'origin',spec['repository'])
        with tempfile.TemporaryDirectory(prefix='llm-eval-publish-') as tmp,_private_ref(root,'refs/llm-eval/publish-base') as private:
            temp=Path(tmp);worktree=temp/'checkout';env=os.environ.copy();env['GIT_TERMINAL_PROMPT']='0'
            if token:
                env['LLM_EVAL_PUBLISH_TOKEN']=token
                helper=temp/'askpass.py';helper.write_text("#!/usr/bin/env python3\nimport os,sys\nprint('x-access-token' if 'username' in sys.argv[-1].lower() else os.environ['LLM_EVAL_PUBLISH_TOKEN'])\n",encoding='utf-8');helper.chmod(0o700)
                if os.name=='nt':
                    wrapper=temp/'askpass.cmd';wrapper.write_text('@"'+sys.executable+'" "'+str(helper)+'" %*\r\n');env['GIT_ASKPASS']=str(wrapper)
                else:env['GIT_ASKPASS']=str(helper)
            git(root,'fetch','origin',spec['base_branch'],env=env)
            base='origin/'+spec['base_branch'];protected=[]
            for name in sorted(names,key=str):      # the approval must be committed on the remote base branch, not only local
                verify=plugin_hook(name,'verify_publication')
                if verify:
                    # an explicit refspec into a private ref: never the remote-tracking ref as found, which a local update-ref moves
                    git(root,'fetch','origin','+refs/heads/'+spec['base_branch']+':'+private,env=env)
                    try:verify(report,root,base=private)
                    except ValueError as exc:raise ValueError('Publication is not available for '+name+': '+str(exc)) from None
                    protected+=list(plugin_hook(name,'PROTECTED_PATHS') or ())
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
                        generated=('docs/results/index/','diagrams/results/summary/')
                        readmes=('docs/results/README.md','README.md')
                        if any(c not in readmes and not c.startswith(generated) for c in conflicts):
                            git(worktree,'merge','--abort',env=env,check=False);raise RuntimeError('Results branch needs conflict resolution')
                        for name in readmes:
                            if name in conflicts:
                                # A results branch only ever changes the generated blocks, so the base copy carries the
                                # hand-written text; the blocks are regenerated below.
                                git(worktree,'checkout','--theirs','--',name,env=env)
                head=_commit_bundle(report,worktree,spec,manifest,manifest_sha,env)
                if protected and git(worktree,'diff','--name-only',private,head,'--',*protected,env=env):
                    raise ValueError('Publication branch changes a protected file')
                git(worktree,'push','origin',head+':refs/heads/'+branch,env=env)
            finally:
                git(root,'worktree','remove','--force',worktree,env=env,check=False)
            body=(f"This experiment report adds raw measurements, JSON/CSV summaries, configuration coverage and PNG charts to the results documentation.\n\n"
                  f"Experiment: {manifest['experiment_id']}\nCampaign: {manifest['campaign_id']}\nStatus: {manifest['status']}\nSynthetic: {manifest['synthetic']}\n"
                  f"Measured code: {spec['code_revision']}\nReport: {spec['report_path']}/README.md\nRaw data: {spec['report_path']}/raw/measurements.jsonl.gz\n"
                  f"Validation: bundle size, staged and committed file inventories and SHA-256 digests checked before push.\nReproduction: use the measured revision and resolved-config.json to bind local artifacts, then run llm-eval plan/run --campaign YOUR_CAMPAIGN.json.\n\nReport fingerprint: {fingerprint}")
            if manifest.get('canonical_bytes'):      # a projected bundle: fixed sentences and projected values only
                body=(f"This experiment report adds a validated projection to the results documentation: cohort metrics with counts and intervals, JSON/CSV summaries, configuration coverage and a canonical raw archive.\n\n"
                      f"Experiment: {manifest['experiment_id']}\nCampaign: {manifest['campaign_id']}\nStatus: {manifest['status']}\n"
                      f"Execution classes: {', '.join(manifest['execution_kinds'])}\nData class: {manifest['data_class']}\nCohorts: {manifest['cohorts']}\n"
                      f"Measured code: {spec['code_revision']}\nReport: {spec['report_path']}/README.md\n"
                      f"Validation: the projection was rebuilt from the run receipt, the approved suite locks and the authorization; every staged and committed file was checked against the manifest before push.\nEvery output requires human review.\n\nReport fingerprint: {fingerprint}")
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
