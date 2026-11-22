"""Measured mode: one artifact served with every layer requested on the GPU, and the evidence that it stayed inside VRAM.

The run itself mirrors model-offloading (installation state, one runner run per category suite). Added here: a refusal
before any launch when the weights exceed the free VRAM, a sampler that also covers the model load, the placement the
backend logged, and a verdict that fails a run that left VRAM."""
import http.client
import json
from pathlib import Path

from llm_eval import runner
from llm_eval.adapters import endpoint_parts
from llm_eval.common import read_json
from llm_eval.core import hardware
from llm_eval.core.contracts import atomic_json
from . import evidence

BENCHMARK = 'category-smoke'
CAVEAT = ('The VRAM counter is device-wide (every process counts) and sampled, so a short peak can be missed. Placement is what '
          'the backend logged or reported, not a per-layer measurement.')
READINGS = ('weight_bytes', 'weight_mib', 'gpu_name', 'total_mib', 'reserve_mib', 'baseline_used_mib', 'peak_used_mib', 'gpu_rise_mib',
            'capacity_ok', 'rise_ok', 'placement', *evidence.LOG_KEYS, 'ollama_size_bytes', 'ollama_size_vram_bytes', 'error_type')


def ollama_ps(port, timeout=5):
    """Ollama's own account of the models it holds (GET /api/ps on the managed loopback server), or None on any failure."""
    connection = http.client.HTTPConnection('127.0.0.1', port, timeout=timeout)
    try:
        connection.request('GET', '/api/ps')
        response = connection.getresponse()
        body = response.read(1024 * 1024)
        return json.loads(body) if response.status == 200 else None
    except (OSError, http.client.HTTPException, ValueError):
        return None
    finally:
        connection.close()


def _run(suites, config, output, root, synthetic):
    """One runner run per suite, as model-offloading does; the status each run recorded."""
    statuses = []
    for index, suite in enumerate(suites):
        config['suite'] = suite
        config_path = output / ('resolved-run-' + str(index) + '.json')
        atomic_json(config_path, config)
        result = runner.run(config_path, root, output / 'measurements', synthetic=synthetic)
        statuses.append(read_json(result / 'metadata.json')['status'])
    return statuses


def _status(statuses):
    return 'succeeded' if all(s == 'completed' for s in statuses) else 'skipped' if all(s == 'skipped' for s in statuses) else 'failed'


def execute(job, output, root):
    """Run the category suites against one artifact and record whether it stayed inside GPU VRAM.

    For a real run, once the artifact is verified, `fit/metadata.json` is written in every outcome, also when the launch or
    a run raises: the worker keeps only the class name of an exception, so what was observed is recorded first."""
    case = job['parameters']
    config = dict(case['config'])
    synthetic = case.get('synthetic', False)
    state_path = case.get('installation_state') or root / '.platforms' / config['os_id'] / config['platform'] / 'state.json'
    state = read_json(state_path) if Path(state_path).exists() else {}
    categories = case.get('categories', [])
    catalog = {c['id']: c for c in read_json(root / 'catalog/benchmarks.json')['categories']}
    suites = [str(root / catalog[c]['local_suite']) for c in categories] if categories else [config['suite']]
    launch, thresholds = config.get('launch', {}), case.get('fit', {})
    record = {'experiment': 'hardware-fit', 'record': 'fit-evidence', 'schema_version': 1, 'synthetic': synthetic,
              'verdict': 'not_assessed', 'reason': None,
              'requested': {'platform': config['platform'], 'gpu_layers': launch.get('gpu_layers'), 'gpu_offload': launch.get('gpu_offload'),
                            'context_tokens': config['context_tokens'], 'threads': launch.get('threads')},
              'min_gpu_weight_fraction': thresholds.get('min_gpu_weight_fraction', evidence.MIN_GPU_WEIGHT_FRACTION),
              'require_layer_evidence': thresholds.get('require_layer_evidence', False),
              **dict.fromkeys(READINGS), 'evidence_basis': [], 'caveat': CAVEAT}
    if synthetic:      # a fixture endpoint says nothing about VRAM: no gate, no backend of our own, no verdict
        statuses = _run(suites, config, output, root, True)
        atomic_json(output / 'fit/metadata.json', record)
        return {'status': _status(statuses), 'result_path': 'measurements', 'benchmark': BENCHMARK}
    from llm_eval import telemetry
    from llm_eval.artifacts import verify_artifact
    from llm_eval.launch import managed_backend
    runner.validate_config(config, root)
    runner.validate_host(config, root)
    profile = job.get('hardware_profile') or hardware.profile(config, root)
    weight_bytes = verify_artifact(config['artifact_root'], read_json(config['artifact_lock']), False, profile['gpu']['vram_gib'])
    device = evidence.device(telemetry.gpu_snapshot(), profile['gpu']['name']) or {}
    total_mib, baseline_mib = device.get('total_mib'), device.get('used_mib')
    reserve_mib = profile['gpu'].get('initial_reserve_gib', 0) * 1024
    record.update(weight_bytes=weight_bytes, weight_mib=weight_bytes / 2 ** 20, gpu_name=device.get('name'), total_mib=total_mib,
                  reserve_mib=reserve_mib, baseline_used_mib=baseline_mib)
    refusal = ('gpu_memory_unobserved' if total_mib is None or baseline_mib is None else
               'artifact_exceeds_free_vram' if evidence.exceeds_free_vram(weight_bytes, total_mib, reserve_mib, baseline_mib) else None)
    if refusal:      # no backend is started: the weights alone cannot be placed, or there is no reading to judge a run by
        record.update(reason=refusal, verdict='not_in_vram' if refusal == 'artifact_exceeds_free_vram' else 'not_assessed')
        atomic_json(output / 'fit/metadata.json', record)
        return {'status': 'failed', 'reason': refusal}
    sampler = telemetry.Sampler(interval=config.get('telemetry_interval_s', 1.0))
    statuses, ps, error = [], None, None
    try:
        with sampler:      # entered before the backend, so the model load is sampled too
            with managed_backend(config, state, output / 'backend'):
                statuses = _run(suites, config, output, root, False)
                if config['platform'] == 'ollama':
                    ps = ollama_ps(endpoint_parts(config['endpoint']).port or 80)
                try:
                    sampler.sample()      # one reading while the backend still holds the model, whatever the tick phase
                except (OSError, RuntimeError):
                    pass
    except BaseException as exc:
        error = type(exc).__name__
        raise
    finally:
        log_path = output / 'backend/backend.log'
        log = evidence.parse_backend_log(log_path.read_text(encoding='utf-8', errors='replace') if log_path.is_file() else '')
        memory = evidence.served_model_memory(ps, config['served_model'])
        peak_mib = evidence.peak_used_mib(sampler.samples, device['index'])
        record.update(log, peak_used_mib=peak_mib, ollama_size_bytes=memory['size'], ollama_size_vram_bytes=memory['size_vram'], error_type=error,
                      evidence_basis=[name for name, present in (('gpu_telemetry', peak_mib is not None),
                                                                 ('backend_log', any(v is not None for v in log.values())),
                                                                 ('ollama_ps', None not in memory.values())) if present])
        if error:      # the run did not reach its end: what was observed is kept, no verdict is drawn from it
            record.update(reason='run_incomplete')
        else:
            result = evidence.verdict(record['weight_mib'], total_mib, reserve_mib, baseline_mib, peak_mib, log, memory,
                                      record['min_gpu_weight_fraction'], record['require_layer_evidence'])
            record.update({k: result[k] for k in ('capacity_ok', 'placement', 'gpu_rise_mib', 'rise_ok', 'reason')},
                          verdict='in_vram' if result['in_vram'] else 'not_in_vram')
        atomic_json(output / 'fit/telemetry.json', sampler.samples)
        atomic_json(output / 'fit/metadata.json', record)
    status = _status(statuses)
    if status == 'succeeded' and record['verdict'] != 'in_vram':
        return {'status': 'failed', 'reason': record['reason'], 'result_path': 'measurements', 'benchmark': BENCHMARK}
    return {'status': status, 'result_path': 'measurements', 'benchmark': BENCHMARK}

