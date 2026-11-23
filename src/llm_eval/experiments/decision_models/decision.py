"""Prompt-only decision adapters and explicit category-to-model policies."""
import math
import time
from llm_eval.adapters import request_events


def decide(router, messages):
    start=time.perf_counter();kind=router['kind']
    if kind=='fixed':return {'choice':router['choice'],'router_s':time.perf_counter()-start}
    if kind=='category':
        text='\n'.join(m['content'] for m in messages).casefold()
        category=router['default_category']
        for label,terms in router.get('keywords',{}).items():
            if any(term.casefold() in text for term in terms):category=label;break
        return {'choice':category,'router_s':time.perf_counter()-start}
    if kind!='systemone':raise ValueError('Unknown decision adapter')
    criteria=router['criteria']
    payload={'model':router['model'],'state':{'messages':messages},
             'questions':{'route':{'type':'choice','instructions':router['instructions'],'criteria':criteria}}}
    response=list(request_events(router['endpoint'],payload,'json',router.get('timeout_s',60),router.get('api_key_env'),router.get('network')))[0]
    answer=response['answers']['route']
    if answer.get('type')!='choice' or answer.get('choice') not in criteria:raise ValueError('Invalid decision choice')
    probabilities=answer.get('probabilities')
    if probabilities is not None:
        if set(probabilities)!=set(criteria) or any(type(v) not in {int,float} or not math.isfinite(v) or not 0<=v<=1 for v in probabilities.values()) or abs(sum(probabilities.values())-1)>.01:
            raise ValueError('Invalid decision probability distribution')
    return {'choice':answer['choice'],'probabilities':probabilities,'router_s':time.perf_counter()-start,'router_usage':response.get('usage')}


def select(decision, policy, candidates):
    choice=decision['choice'];p=decision.get('probabilities')
    if p and p[choice]<policy.get('abstain_threshold',0):return None
    chosen=policy.get('category_models',{}).get(choice,choice)
    return chosen if chosen in candidates else None
