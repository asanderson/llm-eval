"""Experiment registry. Plugins own validation, execution and metrics."""
from importlib import import_module

REGISTRY = {
    'model-offloading': 'llm_eval.experiments.model_offloading',
    'llm-routing': 'llm_eval.experiments.llm_routing',
}


def get_experiment(name):
    if name not in REGISTRY:
        raise ValueError('Unknown experiment: ' + str(name))
    return import_module(REGISTRY[name])


def list_experiments():
    return [get_experiment(name).MANIFEST for name in REGISTRY]
