"""Original model-offload methodology exposed as an experiment."""
import contextlib
import time
from pathlib import Path

from llm_eval.common import read_json
from llm_eval.core.contracts import fields, atomic_json
from llm_eval import runner

MANIFEST = {'id': 'model-offloading', 'version': 1,
            'modes': ['category-smoke', 'livebench', 'matched-performance'],
            'description': 'Model quality, performance and memory placement across serving platforms'}


def validate(case, root, mode=None):
    fields(case, {'config', 'server_mode', 'installation_state', 'categories', 'livebench', 'synthetic'}, ['config'])
    if case.get('server_mode', 'external') not in {'external', 'managed'}:
        raise ValueError('server_mode must be managed or external')
    if not isinstance(case['config'], dict):
        raise ValueError('Resolved offload config must be an object')
    engine, model = runner.validate_config(case['config'], root, synthetic=True)
    if mode == 'matched-performance':
        if 'categories' in case or 'livebench' in case:
            raise ValueError('matched-performance uses its versioned workload')
        if case['config']['context_tokens'] <= 8192 + case['config']['max_output_tokens'] or case['config']['max_output_tokens'] < 256:
            raise ValueError('matched-performance needs room for an 8K prompt plus the output budget, and at least 256 output tokens')
    if engine['os_support'][case['config']['os_id']] == 'unsupported' or model['status'] == 'excluded' or model['id'] in engine.get('blocked_models', []):
        return 'unsupported_os_or_excluded_model'
    return None


def input_files(case, root, mode):
    from .performance import WORKLOAD
    return [str(Path(root) / WORKLOAD)] if mode == 'matched-performance' else []


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
    if synthetic and case.get('server_mode') == 'managed':
        raise ValueError('Synthetic offload uses an explicit external fixture endpoint')
    backend = managed_backend(config, state, output / 'backend') if case.get('server_mode') == 'managed' else contextlib.nullcontext()
    if job['mode'] == 'livebench':
        lb = case.get('livebench', {})
        with contextlib.ExitStack():
            result = run_livebench(config, state, case.get('categories', []), lb['data'], lb['release'],
                                   output / 'livebench', image=lb['image'], allow_agentic=lb.get('allow_agentic', False), backend=backend)
        return {'status': 'succeeded', 'result_path': str(result.relative_to(output)), 'benchmark': 'livebench-upstream'}
    if job['mode'] == 'matched-performance':
        from llm_eval.orchestration.planner import revision
        from .performance import BENCHMARK, WORKLOAD, attempt_summary
        config['suite'] = str(Path(root) / WORKLOAD)
        begin = time.monotonic()
        with backend:
            ready_s = time.monotonic() - begin if case.get('server_mode') == 'managed' and config['protocol'] != 'worker' else None
            config_path = output / 'resolved-run-0.json'
            atomic_json(config_path, config)
            measurement = runner.run(config_path, root, output / 'measurements', synthetic=synthetic)
        summary = attempt_summary(job, measurement, read_json(config['suite']), output / 'backend' / 'backend.log', revision(root))
        summary['managed_backend_start_to_ready_s'] = ready_s
        status = {'completed': 'succeeded', 'skipped': 'skipped'}.get(summary['status'], 'failed')
        return {'status': status, 'result_path': 'measurements', 'benchmark': BENCHMARK, 'performance': summary}
    categories = case.get('categories', [])
    catalog = {c['id']: c for c in read_json(Path(root)/'catalog/benchmarks.json')['categories']}
    suites = [str(Path(root)/catalog[c]['local_suite']) for c in categories] if categories else [config['suite']]
    statuses = []
    with backend:
        for index, suite in enumerate(suites):
            config['suite'] = suite
            config_path = output / ('resolved-run-' + str(index) + '.json')
            atomic_json(config_path, config)
            result = runner.run(config_path, root, output / 'measurements', synthetic=synthetic)
            statuses.append(read_json(result / 'metadata.json')['status'])
    status = 'succeeded' if all(s == 'completed' for s in statuses) else 'skipped' if all(s == 'skipped' for s in statuses) else 'failed'
    return {'status': status, 'result_path': 'measurements', 'benchmark': 'category-smoke'}


def report_supplement(records):
    from .performance import BENCHMARK
    summaries = []
    for row in records:
        if row['latest_attempt'] and row['record_type'] == 'metadata' and Path(row['source_file']).name == 'result.json':
            value = row['data'].get('performance')
            if value and value.get('benchmark') == BENCHMARK:
                summaries.append({'attempt_id': row['attempt_id'], **value})
    if not summaries:
        return None, ''
    lines = ['## Matched offloading performance', '',
             'Medians exclude warmups and errors. Long-input and sustained-output rows use only samples meeting the token target. '
             'A dash indicates an unavailable observation.', '',
             '| Job | Workload | In group / planned | Prompt tokens | Output tokens | First visible s | Client wall s | Prefill tok/s | Decode tok/s |',
             '|---|---|---:|---:|---:|---:|---:|---:|---:|']
    for summary in summaries:
        for name, profile in summary['workloads'].items():
            group = profile.get('qualifying_metrics', profile['metrics'])
            count = profile.get('length_target', {}).get('met', profile['successful_requests'])
            values = [group[key]['median'] for key in ('prompt_tokens', 'completion_tokens', 'first_visible_s',
                                                        'client_request_wall_s', 'backend_prefill_tps', 'backend_decode_tps')]
            cells = [summary['job_id'], name, f"{count}/{profile['planned_requests']}",
                     *(f'{v:.3g}' if v is not None else '—' for v in values)]
            lines.append('| ' + ' | '.join(cells) + ' |')
    return summaries, '\n'.join(lines) + '\n\n'
