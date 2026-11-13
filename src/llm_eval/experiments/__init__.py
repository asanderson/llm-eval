"""Experiment registry. Plugins own validation, execution and metrics."""
from importlib import import_module

REGISTRY = {
    'model-offloading': 'llm_eval.experiments.model_offloading',
    'llm-routing': 'llm_eval.experiments.llm_routing',
    'legal-benchmark': 'llm_eval.experiments.legal_benchmark',
}


def get_experiment(name):
    if name not in REGISTRY:
        raise ValueError('Unknown experiment: ' + str(name))
    return import_module(REGISTRY[name])


def reporting_policy(experiment_id, jobs):
    """What generic reporting may do with these jobs. A plugin restricts it by exporting `reporting_policy(jobs)`;
    experiments without the hook, and unknown ids, keep the unrestricted behavior."""
    hook = getattr(get_experiment(experiment_id), 'reporting_policy', None) if experiment_id in REGISTRY else None
    return hook(jobs) if hook else {'report': True, 'publish': True, 'reason': None}


def plugin_hook(experiment_id, name):
    """An optional attribute of a registered plugin, or None."""
    return getattr(get_experiment(experiment_id), name, None) if experiment_id in REGISTRY else None


def data_policy(experiment_id, job):
    """Whether a job may run and whether its data may leave the host. Plugins without the hook are unrestricted."""
    hook = plugin_hook(experiment_id, 'data_policy')
    return hook(job) if hook else {'admit': True, 'transfer': True, 'reason': None}


def list_experiments():
    return [get_experiment(name).MANIFEST for name in REGISTRY]
