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


def _classify(record, stage, status, log, memory, log_text):
    """Label the observed execution stage before drawing a placement or capacity conclusion."""
    error = record['error_type']
    usage = record['prompt_usage']
    if error or status != 'succeeded':
        record.update(failure_stage=stage, reason='run_incomplete' if error else 'requests_incomplete')
        if usage['successful_requests'] or usage['successful_warmups'] or error in ('KeyboardInterrupt', 'SystemExit'):
            return
        cause = evidence.load_failure(log_text)
        if cause:
            if 'backend_log' not in record['evidence_basis']:
                record['evidence_basis'].append('backend_log')
            if cause == 'gpu_out_of_memory':
                record.update(reason=cause, verdict='not_in_vram', fit_class='capacity_failure', failure_stage='gpu_allocation')
            else:
                record.update(reason=cause, fit_class='loader_failure', failure_stage='model_load')
        return
    result = evidence.verdict(record['weight_mib'], record['total_mib'], record['reserve_mib'], record['baseline_used_mib'],
                              record['peak_used_mib'], log, memory, record['min_gpu_weight_fraction'], record['require_layer_evidence'])
    record.update({key: result[key] for key in ('capacity_ok', 'placement', 'gpu_rise_mib', 'rise_ok', 'reason')})
    if usage['probe'] and not usage['probe']['passed']:
        record.update(reason='context_target_unverified', failure_stage='context_probe')
    elif not usage['successful_requests']:
        record.update(reason='no_measured_requests', failure_stage='request')
    elif result['in_vram']:
        record.update(verdict='in_vram', fit_class='telemetry_consistent' if result['placement'] == 'unobserved' else 'backend_confirmed')
    else:
        record['failure_stage'] = 'fit_check'
        if result['reason'] in ('vram_reserve_exceeded', 'layers_on_cpu'):
            kind = 'placement_failure' if result['reason'] == 'layers_on_cpu' else 'capacity_failure'
            record.update(verdict='not_in_vram', fit_class=kind)


def execute(job, output, root):
    """Run the category suites against one artifact and record whether it stayed inside GPU VRAM.

    For a real run, once the artifact is verified, `fit/metadata.json` is written in every outcome, also when the launch or
    a run raises: the worker keeps only the class name of an exception, so what was observed is recorded first."""
    from . import study
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
    probe = case.get('context_probe')
    benchmark = 'fit-context-boundary' if probe else BENCHMARK
    record.update(fit_class='inconclusive', failure_stage=None, backend_version=config.get('backend_version'),
                  sampler_interval_s=config.get('telemetry_interval_s', 1.0), cache_types=[], other_compute_mib_after_requests=None,
                  headroom_mib=None, prediction=None, prompt_usage=study.prompt_usage([], config, probe))

    def usage():
        return study.prompt_usage((output / 'measurements').glob('*/requests.jsonl'), config, probe)

    if synthetic:      # a fixture endpoint says nothing about VRAM: no gate, no backend of our own, no verdict
        statuses = _run(suites, config, output, root, True)
        record['prompt_usage'] = usage()
        status = _status(statuses)
        if probe and status == 'succeeded' and not record['prompt_usage']['probe']['passed']:
            record.update(reason='context_target_unverified', failure_stage='context_probe')
            status = 'failed'
        atomic_json(output / 'fit/metadata.json', record)
        return {'status': status, 'result_path': 'measurements', 'benchmark': benchmark}
    from llm_eval import telemetry
    from llm_eval.artifacts import verify_artifact
    from llm_eval.launch import managed_backend
    runner.validate_config(config, root)
    runner.validate_host(config, root)
    profile = job.get('hardware_profile') or hardware.profile(config, root)
    lock = read_json(config['artifact_lock'])
    if 'prediction' in case:
        record['prediction'] = study.frozen_prediction(case['prediction'], config, profile, lock)
    weight_bytes = verify_artifact(config['artifact_root'], lock, False, profile['gpu']['vram_gib'])
    device = evidence.device(telemetry.gpu_snapshot(), profile['gpu']['name'], launch.get('gpu', 0)) or {}
    total_mib, baseline_mib = device.get('total_mib'), device.get('used_mib')
    reserve_mib = profile['gpu'].get('initial_reserve_gib', 0) * 1024
    record.update(weight_bytes=weight_bytes, weight_mib=weight_bytes / 2 ** 20, gpu_name=device.get('name'), total_mib=total_mib,
                  reserve_mib=reserve_mib, baseline_used_mib=baseline_mib)
    refusal = ('gpu_memory_unobserved' if total_mib is None or baseline_mib is None else
               'artifact_exceeds_free_vram' if evidence.exceeds_free_vram(weight_bytes, total_mib, reserve_mib, baseline_mib) else None)
    if refusal:      # no backend is started: the weights alone cannot be placed, or there is no reading to judge a run by
        record.update(reason=refusal, failure_stage='preflight')
        if refusal == 'artifact_exceeds_free_vram':
            record.update(fit_class='capacity_failure', verdict='not_in_vram')
        study.compare_prediction(record)
        atomic_json(output / 'fit/metadata.json', record)
        return {'status': 'failed', 'reason': refusal}
    sampler = telemetry.Sampler(interval=config.get('telemetry_interval_s', 1.0))
    statuses, ps, error = [], None, None
    stage = 'backend_startup'
    try:
        with sampler:      # entered before the backend, so the model load is sampled too
            with managed_backend(config, state, output / 'backend'):
                stage = 'request'
                statuses = _run(suites, config, output, root, False)
                if config['platform'] == 'ollama':
                    ps = ollama_ps(endpoint_parts(config['endpoint']).port or 80)
                record['other_compute_mib_after_requests'] = evidence.other_compute_memory(device['index'], config.get('backend_pid'))
                try:
                    sampler.sample()      # one reading while the backend still holds the model, whatever the tick phase
                except (OSError, RuntimeError):
                    pass
    except BaseException as exc:
        error = type(exc).__name__
        raise
    finally:
        log_path = output / 'backend/backend.log'
        log_text = log_path.read_text(encoding='utf-8', errors='replace') if log_path.is_file() else ''
        log = evidence.parse_backend_log(log_text)
        record['cache_types'] = [{'key': k, 'value': v} for k, v in evidence.cache_types(log_text)]
        record['prompt_usage'] = usage()
        memory = evidence.served_model_memory(ps, config['served_model'])
        peak_mib = evidence.peak_used_mib(sampler.samples, device['index'])
        record.update(log, peak_used_mib=peak_mib, ollama_size_bytes=memory['size'], ollama_size_vram_bytes=memory['size_vram'], error_type=error,
                      evidence_basis=[name for name, present in (('gpu_telemetry', peak_mib is not None),
                                                                 ('backend_log', any(v is not None for v in log.values())),
                                                                 ('ollama_ps', None not in memory.values())) if present])
        if peak_mib is not None:
            record['headroom_mib'] = total_mib - reserve_mib - peak_mib
        _classify(record, stage, _status(statuses), log, memory, log_text)
        study.compare_prediction(record)
        atomic_json(output / 'fit/telemetry.json', sampler.samples)
        atomic_json(output / 'fit/metadata.json', record)
    status = _status(statuses)
    if status == 'succeeded' and record['verdict'] != 'in_vram':
        status = 'failed'
    result = {'status': status, 'result_path': 'measurements', 'benchmark': benchmark}
    if status == 'failed':
        result['reason'] = record['reason']
    return result
