"""Hardware fit: the model artifact that best fits one hardware configuration without leaving GPU VRAM.

The in-VRAM counterpart of model-offloading, which requires weights larger than VRAM. `projection` computes, from a frozen
candidate set and the bound hardware profile, what each artifact needs and which fit. `measured` runs one artifact with
every layer requested on the GPU and fails a run that did not stay inside VRAM."""
from pathlib import Path

from llm_eval import runner
from llm_eval.common import GIB, finite_number, read_json
from llm_eval.core import hardware
from llm_eval.core.contracts import fields, identifier, integer
from . import evidence, measured, projection

MANIFEST = {'id': 'hardware-fit', 'version': 1, 'modes': ['projection', 'measured'],
            'description': 'Best-fitting model artifact for a hardware configuration, with weights, cache and buffers inside GPU VRAM'}

# The platforms this version measures: the launch field that asks each for every layer on the GPU, and the value that does.
FULL_GPU = {'llama.cpp': ('gpu_layers', 999), 'ik_llama.cpp': ('gpu_layers', 999), 'koboldcpp': ('gpu_layers', 999),
            'ollama': ('gpu_layers', 999), 'lmstudio': ('gpu_offload', 'max')}


def _identity(case):
    """(harness, model) under which the results index lists the job; read there from the planned parameters."""
    identity = fields(case['identity'], {'harness', 'model'}, ['harness', 'model'])
    return identifier(identity['harness']), identifier(identity['model'])


def _synthetic(case):
    if not isinstance(case.get('synthetic', False), bool):
        raise ValueError('synthetic must be true or false')
    return case.get('synthetic', False)


def _projection(case):
    fields(case, {'identity', 'data', 'context_tokens', 'disk_free_gib', 'artifact_root', 'policy', 'synthetic'},
           ['identity', 'data', 'context_tokens'])
    if _identity(case)[0] != 'projection':
        raise ValueError('identity.harness must be projection for a projection case')
    synthetic = _synthetic(case)
    integer(case['context_tokens'], 'context_tokens', 512, 1048576)
    if 'disk_free_gib' in case and finite_number(case['disk_free_gib'], 'disk_free_gib') <= 0:
        raise ValueError('disk_free_gib must be greater than 0')
    if 'artifact_root' in case and not isinstance(case['artifact_root'], str):
        raise ValueError('artifact_root must be a directory path')
    if synthetic and 'disk_free_gib' not in case:      # a measured value would make a fixture run depend on its host
        raise ValueError('A synthetic projection declares disk_free_gib')
    if 'disk_free_gib' not in case and 'artifact_root' not in case:
        raise ValueError('Declare disk_free_gib or artifact_root so free disk space is known')
    projection.check_policy(case.get('policy', {}))
    if not isinstance(case['data'], str) or not Path(case['data']).is_file():
        raise ValueError('data must name an existing candidate set file')
    if projection.load_candidates(case['data']).get('synthetic') and not synthetic:
        raise ValueError('A synthetic candidate set needs a synthetic case')
    return None


def _measured(case, root):
    fields(case, {'identity', 'config', 'server_mode', 'categories', 'installation_state', 'fit', 'synthetic'},
           ['identity', 'config', 'server_mode'])
    harness, label = _identity(case)
    synthetic = _synthetic(case)
    if case['server_mode'] not in ('external', 'managed'):
        raise ValueError('server_mode must be managed or external')
    config = case['config']
    if not isinstance(config, dict):
        raise ValueError('Resolved hardware-fit config must be an object')
    engine, model = runner.validate_config(config, root, synthetic=True)
    if config.get('lane') != 'control':      # the only lane in which the runner accepts weights of at most VRAM size
        raise ValueError('hardware-fit measures in-VRAM artifacts: set lane to control')
    platform = config['platform']
    if platform not in FULL_GPU:
        raise ValueError('hardware-fit does not measure platform ' + platform + ' in this version; supported: ' + ', '.join(sorted(FULL_GPU)))
    if harness != platform:
        raise ValueError('identity.harness must equal config.platform')
    if not label.startswith(config['model_id'] + '-'):      # quantizations of one model must rank separately
        raise ValueError('identity.model must be config.model_id followed by the quantization, for example qwen38-27b-q4_k_m')
    launch = config.get('launch', {})
    field, value = FULL_GPU[platform]
    if not isinstance(launch, dict) or type(launch.get(field)) is not type(value) or launch[field] != value:
        raise ValueError('hardware-fit asks for every layer on the GPU: set launch.' + field + ' to ' + str(value))
    if launch.get('extra_args'):
        raise ValueError('hardware-fit refuses launch.extra_args: they can override placement and context')
    if 'categories' in case:
        known = [c['id'] for c in read_json(root / 'catalog/benchmarks.json')['categories']]
        if not isinstance(case['categories'], list) or not case['categories'] or any(c not in known for c in case['categories']):
            raise ValueError('categories must be a non-empty list of category ids of catalog/benchmarks.json')
    if 'installation_state' in case and not isinstance(case['installation_state'], str):
        raise ValueError('installation_state must be a file path')
    if synthetic and case['server_mode'] == 'managed':
        raise ValueError('Synthetic hardware-fit uses an explicit external fixture endpoint')
    if not synthetic and case['server_mode'] != 'managed':
        raise ValueError('hardware-fit evidence needs the log of a backend it owns: set server_mode to managed')
    thresholds = fields(case.get('fit', {}), {'min_gpu_weight_fraction', 'require_layer_evidence'})
    finite_number(thresholds.get('min_gpu_weight_fraction', evidence.MIN_GPU_WEIGHT_FRACTION), 'fit.min_gpu_weight_fraction', 0, 1)
    if not isinstance(thresholds.get('require_layer_evidence', False), bool):
        raise ValueError('fit.require_layer_evidence must be true or false')
    if engine['os_support'][config['os_id']] == 'unsupported' or model['status'] == 'excluded' or model['id'] in engine.get('blocked_models', []):
        return 'unsupported_os_or_excluded_model'
    lock = config.get('artifact_lock')
    if not synthetic and isinstance(lock, str) and Path(lock).is_file():
        # Weights alone above the VRAM budget cannot fit, whatever the cache and the buffers need.
        locked = read_json(lock)
        weight_bytes = integer(locked.get('weight_bytes') if isinstance(locked, dict) else None, 'artifact_lock weight_bytes', 1, 2 ** 63 - 1)
        if weight_bytes > hardware.limits(config, root)['gpu_budget_gib'] * GIB:
            return 'artifact_exceeds_gpu_vram_budget'
    return None


def validate(case, root, mode='projection'):
    """Offline check of one case. Raises for an invalid configuration; returns a reason only for a combination that cannot
    run (unsupported OS, excluded or blocked model) or cannot fit (locked weights above the VRAM budget)."""
    if mode == 'projection':
        return _projection(case)
    if mode == 'measured':
        return _measured(case, Path(root))
    raise ValueError('Unsupported hardware-fit mode')


def execute(job, output, root):
    output, root = Path(output), Path(root)
    output.mkdir(parents=True, exist_ok=True)
    reason = validate(job['parameters'], root, job['mode'])
    if reason:
        return {'status': 'skipped', 'reason': reason}
    return (projection if job['mode'] == 'projection' else measured).execute(job, output, root)


def host_requirements(parameters, mode):
    """A projection reads no GPU; a measured run needs the GPU of the hardware profile."""
    return {'gpu': mode == 'measured'}


def setup_platforms(parameters, mode):
    """A projection installs nothing; a measured run needs the platform of its run config."""
    return [parameters['config']['platform']] if mode == 'measured' else []
