"""Routing experiment contract; adapters implement decision, replay and live modes."""
MANIFEST = {'id': 'llm-routing', 'version': 1, 'modes': ['decision', 'replay', 'live'],
            'description': 'Decision quality and downstream routing quality, latency and cost'}


def validate(case, root):
    from llm_eval.core.contracts import fields
    fields(case, {'suite', 'router', 'candidates', 'replay', 'policy', 'repeats', 'warmups',
                  'synthetic', 'save_outputs', 'budget_usd', 'max_output_tokens', 'seed', 'temperature',
                  'request_concurrency'}, ['suite', 'router'])
    return None


def execute(job, output, root):
    from .evaluation import execute as evaluate
    return evaluate(job, output, root)
