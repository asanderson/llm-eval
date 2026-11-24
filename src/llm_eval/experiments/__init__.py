"""Experiment registry. Plugins own validation, execution and metrics."""
from importlib import import_module

REGISTRY = {
    'model-offloading': 'llm_eval.experiments.model_offloading',
    'decision-models': 'llm_eval.experiments.decision_models',
    'legal-models': 'llm_eval.experiments.legal_models',
    'hardware-fit': 'llm_eval.experiments.hardware_fit',
}
# The former id of a renamed experiment, mapped to its current id. Campaigns planned and bundles published before the
# rename carry the former id; their plugin, reports and published results resolve through this map. A new campaign
# names the current id: the planner refuses a former one.
RENAMED = {
    'llm-routing': 'decision-models',
    'legal-benchmark': 'legal-models',
}


def canonical(name):
    """The current id of an experiment: `name` itself unless it is the former id of a renamed experiment."""
    return RENAMED.get(name, name) if isinstance(name, str) else name


def get_experiment(name):
    name = canonical(name)
    if name not in REGISTRY:
        raise ValueError('Unknown experiment: ' + str(name))
    return import_module(REGISTRY[name])


def registered(name):
    """Whether `name` is the current or the former id of a registered experiment."""
    return canonical(name) in REGISTRY


def reporting_policy(experiment_id, jobs):
    """What generic reporting may do with these jobs. A plugin restricts it by exporting `reporting_policy(jobs)`;
    experiments without the hook, and unknown ids, keep the unrestricted behavior."""
    hook = getattr(get_experiment(experiment_id), 'reporting_policy', None) if registered(experiment_id) else None
    return hook(jobs) if hook else {'report': True, 'publish': True, 'reason': None}


def plugin_hook(experiment_id, name):
    """An optional attribute of a registered plugin, or None."""
    return getattr(get_experiment(experiment_id), name, None) if registered(experiment_id) else None


def data_policy(experiment_id, job):
    """Whether a job may run and whether its data may leave the host. Plugins without the hook are unrestricted."""
    hook = plugin_hook(experiment_id, 'data_policy')
    return hook(job) if hook else {'admit': True, 'transfer': True, 'reason': None}


def list_experiments():
    return [get_experiment(name).MANIFEST for name in REGISTRY]
