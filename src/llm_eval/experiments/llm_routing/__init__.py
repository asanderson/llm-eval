"""Routing experiment contract and preflight validation."""
from pathlib import Path
from llm_eval.core.contracts import fields, integer
from llm_eval.common import finite_number, read_json
from llm_eval.adapters import configured_endpoint
from llm_eval.runner import load_suite

MANIFEST={'id':'llm-routing','version':1,'modes':['decision','replay','live'],
          'description':'Decision quality and downstream routing quality, latency and cost'}


def validate(case, root, mode='decision'):
    fields(case, {'suite','router','candidates','replay','policy','repeats','warmups','synthetic','save_outputs',
                  'budget_usd','max_output_tokens','seed','temperature','request_concurrency'}, ['suite','router'])
    integer(case.get('repeats',1),'repeats',high=100)
    integer(case.get('warmups',0),'warmups',low=0,high=20)
    integer(case.get('max_output_tokens',256),'max_output_tokens',high=8192)
    integer(case.get('request_concurrency',1),'request_concurrency',high=1)
    integer(case.get('seed',1),'seed',low=0,high=2**31-1)
    finite_number(case.get('temperature',0),'temperature',0,2)
    finite_number(case.get('budget_usd',0),'budget_usd',0)
    suite=load_suite(case['suite']);router=case['router']
    fields(router, {'kind','choice','default_category','keywords','platform','model','model_revision','endpoint',
                    'instructions','criteria','timeout_s','api_key_env','network','pricing','context_tokens'}, ['kind'])
    if router['kind']=='fixed':
        if not isinstance(router.get('choice'),str):raise ValueError('Fixed router needs a choice')
    elif router['kind']=='category':
        if not router.get('default_category'):raise ValueError('Category router needs default_category')
        for terms in router.get('keywords',{}).values():
            if not isinstance(terms,list) or any(not isinstance(x,str) or not x for x in terms):raise ValueError('Keywords must be nonempty strings')
    elif router['kind']=='systemone':
        for k in ('model','model_revision','endpoint','instructions','criteria'):
            if not router.get(k):raise ValueError('SystemOne router missing '+k)
        if not isinstance(router['criteria'],dict) or any(not isinstance(x,str) for x in router['criteria'].values()):raise ValueError('Choice criteria must be named descriptions')
        configured_endpoint(router['endpoint'],router.get('network'))
        finite_number(router.get('timeout_s',60),'timeout_s',.1,3600)
    else:raise ValueError('Unknown router kind')
    candidates=case.get('candidates',{})
    if mode!='decision' and not candidates:raise ValueError('Routing requires a candidate pool')
    for cid,c in candidates.items():
        fields(c, {'model','model_revision','platform','backend_version','protocol','endpoint','network','api_key_env',
                   'context_tokens','timeout_s','pricing','request_options','request_usage','quantization','template_sha256',
                   'target_id','backend_pid'}, ['model','model_revision','platform'])
        if mode=='live':
            if c.get('protocol') not in {'ollama','openai'}:raise ValueError('Live candidate protocol must be ollama or openai')
            configured_endpoint(c['endpoint'],c.get('network'))
            integer(c['context_tokens'],'context_tokens',low=512,high=1048576)
            finite_number(c.get('timeout_s',60),'timeout_s',.1,3600)
            if case.get('max_output_tokens',256)>=c['context_tokens']:raise ValueError('Output budget exceeds candidate context')
    for d in [router,*candidates.values()]:
        if d.get('network',{}).get('kind')=='hosted':
            if not case.get('budget_usd'):raise ValueError('Hosted deployments require a nonzero per-job budget_usd')
            integer(d['context_tokens'],'context_tokens',low=512,high=1048576)
            for k in ('input_per_million','output_per_million'):finite_number(d['pricing'][k],k,0)
    policy=case.get('policy',{})
    fields(policy, {'category_models','benchmark_registry','objective','fallback','abstain_threshold'})
    finite_number(policy.get('abstain_threshold',0),'abstain_threshold',0,1)
    fields(policy.get('objective',{}),{'quality_weight','latency_weight','cost_weight'})
    for k,v in policy.get('objective',{}).items():finite_number(v,k,0)
    if policy.get('fallback') and policy['fallback'] not in candidates:raise ValueError('Unknown fallback candidate')
    for t in suite['tasks']:
        if 'eligible_candidates' in t and (not t['eligible_candidates'] or set(t['eligible_candidates'])-set(candidates)):raise ValueError('Unknown eligible candidate')
    if mode=='replay':
        from .evaluation import corpus_index, candidate_fingerprint
        corpus=read_json(case['replay']);corpus_index(corpus,suite)
        for cid,c in candidates.items():
            if corpus.get('candidate_fingerprints',{}).get(cid)!=candidate_fingerprint(c):raise ValueError('Replay candidate fingerprint mismatch')
        for row in corpus['rows']:
            for k in ('quality','latency_s','cost_usd'):
                if row.get(k) is not None:finite_number(row[k],k,0,1 if k=='quality' else float('inf'))
    return None


def execute(job, output, root):
    validate(job['parameters'],root,job['mode'])
    from .evaluation import execute as evaluate
    return evaluate(job,output,root)
