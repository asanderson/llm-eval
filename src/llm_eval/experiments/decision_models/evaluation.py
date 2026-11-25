"""Decision, replay and live measurements with explicit missing data."""
from __future__ import annotations
import json
from pathlib import Path
import time
from llm_eval.adapters import HTTPAdapter
from llm_eval.common import digest, read_json
from llm_eval.core.contracts import atomic_json
from llm_eval.runner import load_suite, grade
from llm_eval.telemetry import Sampler
from .decision import decide, select
from .workload import selected_tasks


def utility(quality, latency, cost, objective):
    if quality is None:return None
    if objective.get('latency_weight',0) and latency is None:return None
    if objective.get('cost_weight',0) and cost is None:return None
    return quality*objective.get('quality_weight',1)-(latency or 0)*objective.get('latency_weight',0)-(cost or 0)*objective.get('cost_weight',0)


def corpus_index(corpus, suite):
    if corpus['suite_sha256']!=digest(suite):raise ValueError('Replay suite hash mismatch')
    result={}
    for row in corpus['rows']:
        key=(row['task_id'],row['candidate'])
        if key in result:raise ValueError('Duplicate replay outcome')
        result[key]=row
    return result


def candidate_fingerprint(candidate):
    return digest({k:v for k,v in candidate.items() if k not in {'endpoint','api_key_env','network','backend_pid','timeout_s'}})


def budget_reservation(candidate, output_tokens):
    if candidate.get('network',{}).get('kind')!='hosted':return 0
    price=candidate['pricing']
    return (candidate['context_tokens']*price['input_per_million']+output_tokens*price['output_per_million'])/1e6


def actual_cost(candidate, usage):
    if candidate.get('network',{}).get('kind')!='hosted':return 0
    if usage.get('prompt_tokens') is None or usage.get('completion_tokens') is None:return None
    price=candidate['pricing']
    return (usage['prompt_tokens']*price['input_per_million']+usage['completion_tokens']*price['output_per_million'])/1e6


def generation_settings(config):
    return {'max_output_tokens': config.get('max_output_tokens', 256), 'temperature': config.get('temperature', 0),
            'seed': config.get('seed', 1)}


def baseline_scores(rows, tasks, candidates, objective):
    by_candidate = {candidate: [] for candidate in candidates}
    for task in tasks:
        eligible = task.get('eligible_candidates', candidates)
        if not all(candidate in eligible for candidate in candidates):
            continue
        values = {}
        for candidate in candidates:
            row = rows.get((task['id'], candidate), {})
            values[candidate] = utility(row.get('quality'), row.get('latency_s'), row.get('cost_usd'), objective)
        if all(value is not None for value in values.values()):
            for candidate, value in values.items():
                by_candidate[candidate].append(value)
    scores = {c: sum(values) / len(values) if values else None for c, values in by_candidate.items()}
    available = {c: v for c, v in scores.items() if v is not None}
    return {'common_coverage_tasks': len(next(iter(by_candidate.values()), [])), 'candidate_utility': scores,
            'best_fixed_candidate': max(available, key=available.get) if available else None, 'oracle_is_deployable': False}


def execute(job, output, root):
    case=job['parameters'];output=Path(output);output.mkdir(parents=True,exist_ok=True)
    suite=load_suite(case['suite']);mode=job['mode'];router=case['router']
    tasks=selected_tasks(suite,case)
    candidates=case.get('candidates',{});policy=dict(case.get('policy',{}));objective=policy.get('objective',{})
    # A fixed generator chooses a deployment ID. A separate topic label is outside its vocabulary.
    direct_generator = (mode != 'decision' and router['kind'] == 'fixed' and router['choice'] in candidates
                        and not policy.get('category_models') and not policy.get('benchmark_registry'))
    if policy.get('benchmark_registry'):
        registry=read_json(policy['benchmark_registry'])
        if not registry.get('release') or not registry.get('source'):raise ValueError('Benchmark registry needs release and source provenance')
        policy['category_models']={category:max({c:v for c,v in scores.items() if c in candidates},key=lambda c:scores[c])
                                   for category,scores in registry['categories'].items()}
    replay={};baseline=None
    if mode=='replay':
        corpus=read_json(case['replay']);replay=corpus_index(corpus,suite)
        if corpus.get('hardware_config_id') is not None and corpus['hardware_config_id']!=job.get('hardware_config_id'):
            raise ValueError('Replay hardware configuration mismatch')
        for cid,c in candidates.items():
            if corpus['candidate_fingerprints'].get(cid)!=candidate_fingerprint(c):raise ValueError('Replay candidate fingerprint mismatch')
        baseline=baseline_scores(replay,tasks,candidates,objective)
        atomic_json(output/'replay-outcomes.json',corpus)
    meta={'schema_version':2,'experiment_id':'decision-models','mode':mode,'config':case,
          'suite_sha256':digest(suite),'synthetic':case.get('synthetic',False),'benchmark':suite.get('benchmark','routing'),
          'policy_sha256':digest(policy),'criteria_order':list(router.get('criteria',{})),'status':'running','baseline':baseline}
    atomic_json(output/'routing-metadata.json',meta)
    charged=0;rows=[];started=time.perf_counter()
    with Sampler(interval=.5) as sampler, (output/'requests.jsonl').open('w',encoding='utf-8') as handle:
        for task in tasks:
            for rep in range(case.get('warmups',0)+case.get('repeats',1)):
                begin=time.perf_counter()
                expected = task.get('expected_choice')
                if direct_generator and expected not in candidates:
                    expected = None
                row={'task_id':task['id'],'category':task.get('category','unspecified'),'benchmark':meta['benchmark'],
                     'warmup':rep<case.get('warmups',0),'repetition':rep,'synthetic':meta['synthetic'],
                     'prompt_sha256':digest(task['messages']),'status':'ok','mode':mode,
                     'quality_check_applicable':task.get('check',{}).get('type','none')!='none',
                     'expected_choice':expected}
                if 'family' in task:
                    row['task_family']=task['family']
                try:
                    router_reservation=budget_reservation(router,64)
                    if router_reservation and charged+router_reservation>case.get('budget_usd',0):
                        row['status']='budget_exhausted';raise ValueError('Router API budget exhausted')
                    charged+=router_reservation
                    decision=decide(router,task['messages']);row.update(decision)
                    usage=decision.get('router_usage') or {}
                    router_cost=actual_cost(router,{'prompt_tokens':usage.get('input_tokens'),'completion_tokens':usage.get('output_tokens')})
                    row['router_cost_usd']=router_cost
                    probabilities=decision.get('probabilities')
                    row['abstained']=bool(probabilities and probabilities[decision['choice']] < policy.get('abstain_threshold',0))
                    if router_cost is not None:charged+=router_cost-router_reservation
                    if expected is not None:
                        row.update(expected_choice=task['expected_choice'],decision_correct=decision['choice']==task['expected_choice'])
                        if probabilities and task['expected_choice'] in probabilities:
                            row['brier_score']=sum((v-int(c==task['expected_choice']))**2 for c,v in probabilities.items())
                    if mode!='decision':
                        selected=select(decision,policy,candidates);row['abstained']=selected is None
                        if selected is None:selected=policy.get('fallback')
                        row['fallback_used']=row['abstained'] and selected in candidates
                        if selected not in candidates:raise ValueError('No eligible route or fallback')
                        eligible=task.get('eligible_candidates',list(candidates))
                        if selected not in eligible:
                            row['policy_violation']=True;raise ValueError('Ineligible route')
                        row['selected_model']=selected
                        if mode=='replay':
                            measured=replay.get((task['id'],selected))
                            if measured is None:row.update(status='missing',missing_reason='candidate_outcome_unavailable')
                            else:
                                row.update(quality=measured.get('quality'),estimated_generation_s=measured.get('latency_s'),estimated_cost_usd=measured.get('cost_usd'))
                                generation_s=measured.get('latency_s');cost=measured.get('cost_usd')
                                row['estimated_end_to_end_s']=decision['router_s']+generation_s if generation_s is not None else None
                                row['estimated_total_cost_usd']=router_cost+cost if router_cost is not None and cost is not None else None
                                selected_utility=utility(measured.get('quality'),measured.get('latency_s'),measured.get('cost_usd'),objective)
                                outcomes=[replay.get((task['id'],c)) for c in eligible]
                                values=[utility(v.get('quality'),v.get('latency_s'),v.get('cost_usd'),objective) for v in outcomes if v]
                                row['utility']=selected_utility
                                row['oracle_regret']=max(values)-selected_utility if len(values)==len(eligible) and values and all(v is not None for v in values) and selected_utility is not None else None
                        else:
                            choices=[selected]
                            fallback=policy.get('fallback')
                            if fallback and fallback!=selected and fallback in eligible:choices.append(fallback)
                            attempts=[]
                            for candidate_id in choices:
                                row['fallback_used']=row['abstained'] or candidate_id!=selected
                                candidate=candidates[candidate_id];max_tokens=case.get('max_output_tokens',256)
                                reservation=budget_reservation(candidate,max_tokens)
                                if charged+reservation>case.get('budget_usd',0) and reservation:
                                    row['status']='budget_exhausted';raise ValueError('API budget exhausted')
                                charged+=reservation
                                generation_start=time.perf_counter()
                                try:
                                    response=HTTPAdapter({'timeout_s':60,**candidate,'served_model':candidate['model']}).generate(task['messages'],max_tokens,case.get('seed',1),case.get('temperature',0))
                                except Exception as exc:
                                    attempts.append({'model':candidate_id,'status':'error','error_type':type(exc).__name__,'elapsed_s':time.perf_counter()-generation_start,'reserved_usd':reservation})
                                    row['generation_attempts']=attempts
                                    if candidate_id==choices[-1]:raise
                                    continue
                                cost=actual_cost(candidate,response)
                                if cost is not None:charged+=cost-reservation
                                unknown_attempt_cost=any(candidates[a['model']].get('network',{}).get('kind')=='hosted' for a in attempts)
                                row['total_cost_usd']=(router_cost+cost if not unknown_attempt_cost and router_cost is not None and cost is not None else None)
                                attempts.append({'model':candidate_id,'status':'ok','elapsed_s':response['elapsed_s'],'cost_usd':cost})
                                row.update(generation_attempts=attempts,selected_model=candidate_id,
                                           generation_s=sum(x['elapsed_s'] for x in attempts),cost_usd=cost,cost_reserved_usd=reservation if cost is None else 0,
                                           prompt_tokens=response['prompt_tokens'],completion_tokens=response['completion_tokens'],
                                           first_output_s=response.get('first_output_s'),first_visible_s=response.get('first_visible_s'),
                                           backend_load_s=response.get('backend_load_s'),backend_decode_tps=response.get('backend_decode_tps'),
                                           output_sha256=digest(response['text'].encode()),quality_pass=grade(response['text'],task))
                                if case.get('save_outputs'):row['output']=response['text']
                                break
                    row['elapsed_s']=time.perf_counter()-begin
                except Exception as exc:
                    if row['status']=='ok':row['status']='error'
                    row.update(error_type=type(exc).__name__,elapsed_s=time.perf_counter()-begin)
                rows.append(row);handle.write(json.dumps(row,allow_nan=False)+'\n');handle.flush()
    atomic_json(output/'telemetry.json',sampler.samples)
    meta.update(status='completed' if all(r['status']=='ok' for r in rows) else 'completed_with_errors',
                wall_s=time.perf_counter()-started,cost_charged_or_reserved_usd=charged,telemetry=sampler.summary())
    atomic_json(output/'routing-metadata.json',meta)
    return {'status':'succeeded' if meta['status']=='completed' else 'failed','result_path':'.','cost_charged_or_reserved_usd':charged}
