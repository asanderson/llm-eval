"""Original model-offload methodology exposed as an experiment."""
import contextlib
from pathlib import Path

from llm_eval.common import read_json
from llm_eval.core.contracts import fields, atomic_json
from llm_eval import runner

MANIFEST = {'id': 'model-offloading', 'version': 1,
            'modes': ['category-smoke', 'livebench'],
            'description': 'Model quality, performance and memory placement across serving platforms'}


def validate(case, root, mode=None):
    fields(case, {'config', 'server_mode', 'installation_state', 'categories', 'livebench', 'synthetic'}, ['config'])
    if case.get('server_mode', 'external') not in {'external', 'managed'}:
        raise ValueError('server_mode must be managed or external')
    if not isinstance(case['config'], dict):
        raise ValueError('Resolved offload config must be an object')
    engine, model = runner.validate_config(case['config'], root, synthetic=True)
    if engine['os_support'][case['config']['os_id']] == 'unsupported' or model['status'] == 'excluded' or model['id'] in engine.get('blocked_models', []):
        return 'unsupported_os_or_excluded_model'
    return None


def execute(job, output, root):
    from llm_eval.launch import managed_backend
    from llm_eval.livebench import run_livebench
    case = job['parameters']
    config = dict(case['config'])
    output = Path(output)
    state_path = case.get('installation_state') or Path(root)/'.platforms'/config['os_id']/config['platform']/'state.json'
    state = read_json(state_path) if Path(state_path).exists() else {}
    synthetic = case.get('synthetic', False)
    if not synthetic:
        runner.validate_config(config, root)
        runner.validate_host(config, root)
        from llm_eval.artifacts import verify_artifact
        lock = read_json(config['artifact_lock'])
        verify_artifact(config['artifact_root'], lock, config.get('lane') != 'control',
                        read_json(Path(root) / 'configs/hardware' / (config['hardware_profile'] + '.json'))['gpu']['vram_gib'])
    if synthetic:
        raise ValueError('Synthetic offload requires a fixture HTTP endpoint; use legacy test fixtures directly')
    backend = managed_backend(config, state, output / 'backend') if case.get('server_mode') == 'managed' else contextlib.nullcontext()
    if job['mode'] == 'livebench':
        lb = case.get('livebench', {})
        with contextlib.ExitStack():
            result = run_livebench(config, state, case.get('categories', []), lb['data'], lb['release'],
                                   output / 'livebench', image=lb['image'], allow_agentic=lb.get('allow_agentic', False), backend=backend)
        return {'status': 'succeeded', 'result_path': str(result.relative_to(output)), 'benchmark': 'livebench-upstream'}
    atomic_json(output / 'resolved-run.json', config)
    with backend:
        # managed_backend may add backend_pid or worker_python.
        atomic_json(output / 'resolved-run.json', config)
        result = runner.run(output / 'resolved-run.json', root, output / 'measurements')
    meta = read_json(result / 'metadata.json')
    status = {'completed': 'succeeded', 'skipped': 'skipped'}.get(meta['status'], 'failed')
    return {'status': status, 'result_path': str(result.relative_to(output)), 'benchmark': meta.get('benchmark')}
