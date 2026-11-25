"""Warm, single-request offload measurements using the shared runner's recorded observations."""
import argparse
from collections import Counter
import json
from pathlib import Path
from statistics import median

from llm_eval.common import digest, read_json
from llm_eval.experiments.hardware_fit.evidence import parse_backend_log
from llm_eval.report import quantile

BENCHMARK = 'matched-offload-v1'
WORKLOAD = Path('experiments/model-offloading/workloads/matched-v1.json')
METRICS = ('prompt_tokens', 'completion_tokens', 'output_chars', 'reasoning_chars',
           'first_output_s', 'first_visible_s', 'client_request_wall_s', 'client_output_tps',
           'backend_prefill_tps', 'backend_decode_tps', 'backend_load_s')
LENGTH_TARGETS = {'long-input-4k': ('prompt_tokens', 4096), 'long-input-8k': ('prompt_tokens', 8192), 'sustained-output': ('completion_tokens', 256)}


def distribution(values):
    return {'n': len(values), 'min': min(values) if values else None,
            'median': median(values) if values else None, 'p95': quantile(values, .95),
            'max': max(values) if values else None}


def metrics_for(rows):
    return {key: distribution([r[key] for r in rows if r.get(key) is not None]) for key in METRICS}


def workload_summary(task, rows, repeats):
    measured = [r for r in rows if r['task_id'] == task['id'] and not r['warmup']]
    ok = [dict(r) for r in measured if r['status'] == 'ok']
    for row in ok:
        wall = row.get('client_request_wall_s')
        tokens = row.get('completion_tokens')
        if wall and tokens is not None:
            row['client_output_tps'] = tokens / wall
    result = {'prompt_sha256': digest(task['messages']),
              'input_text_chars': sum(len(m['content']) for m in task['messages']),
              'warmup_client_wall_s': [r.get('client_request_wall_s') for r in rows if r['task_id'] == task['id'] and r['warmup']],
              'planned_requests': repeats, 'measured_requests': len(measured), 'successful_requests': len(ok),
              'unattempted_requests': repeats - len(measured),
              'errors': dict(Counter(r.get('error_type', r['status']) for r in measured if r['status'] != 'ok')),
              'finish_reasons': dict(Counter(r.get('finish_reason') or 'unknown' for r in ok)),
              'empty_visible_responses': sum(r.get('output_chars') == 0 for r in ok),
              'token_count_sources': dict(Counter(r.get('token_count_source') or 'unknown' for r in ok)),
              'metrics': metrics_for(ok)}
    if task['id'] in LENGTH_TARGETS:
        key, minimum = LENGTH_TARGETS[task['id']]
        qualifying = [r for r in ok if r.get(key) is not None and r[key] >= minimum]
        result['qualifying_metrics'] = metrics_for(qualifying)
        values = [r[key] for r in ok if r.get(key) is not None]
        result['length_target'] = {'metric': key, 'min_tokens': minimum,
                                   'met': len(qualifying),
                                   'below': sum(v < minimum for v in values), 'unknown': len(ok) - len(values)}
    return result


def swap_activity(samples):
    """An increase in either counter shows activity. Ruling it out needs both monotonic counters."""
    complete = True
    for key in ('swap_in_bytes', 'swap_out_bytes'):
        values = [sample[key] for sample in samples if sample.get(key) is not None]
        changes = [b - a for a, b in zip(values, values[1:])]
        if any(d > 0 for d in changes):
            return 'observed'
        complete = complete and len(values) == len(samples) and bool(changes) and all(d == 0 for d in changes)
    return 'none_detected' if complete else 'unknown'


def thermal_summary(samples, gpu_index):
    timed = [r for r in samples if r.get('monotonic_s') is not None]
    span = timed[-1]['monotonic_s'] - timed[0]['monotonic_s'] if len(timed) >= 2 else None
    result = {'sample_span_s': span, 'gpu_index': str(gpu_index), 'window_s': 60}
    for window in ('first', 'last'):
        group = [r for r in timed if (r['monotonic_s'] - timed[0]['monotonic_s'] if window == 'first'
                                     else timed[-1]['monotonic_s'] - r['monotonic_s']) <= 60]
        gpu = [g for r in group for g in r.get('gpus', []) if str(g.get('index')) == str(gpu_index)]
        result[window] = {key: distribution([g[key] for g in gpu if g.get(key) is not None])
                          for key in ('temperature_c', 'power_w', 'sm_clock_mhz')}
    return result


def memory_summary(metadata, samples):
    config = metadata['config']
    os_id = config['os_id']
    wsl = 'wsl2' in os_id
    observed = swap_activity(samples) if os_id != 'windows-11-native' else 'unknown'
    attestation = config.get('hardware_attestation', {})
    attested = attestation.get('paging')
    host = observed if not wsl else 'unknown'
    source = 'host_swap_counters' if host != 'unknown' else None
    if attested in ('none', 'observed') and (host == 'unknown' or attested == 'observed'):
        host, source = attested, 'operator_attestation'
    return {'sample_scope': 'wsl_guest' if wsl else 'host', 'sampled_swap_activity': observed,
            'host_paging': host, 'host_paging_source': source,
            'windows_host_used_gib_peak_attested': attestation.get('windows_host_used_gib_peak') if wsl else None,
            'telemetry': metadata.get('telemetry', {})}


def common_config(config):
    # The lock binds the local bytes. Paths, PIDs and ephemeral server addresses vary between boots.
    excluded = {'suite', 'artifact_root', 'artifact_lock', 'offload_dir', 'backend_pid', 'endpoint',
                'worker_python', 'hardware_attestation', 'placement_notes', 'os_id', 'launch', 'api_key_env'}
    return {k: v for k, v in config.items() if k not in excluded}


def attempt_summary(job, directory, suite, log_file, revision):
    directory = Path(directory)
    metadata = read_json(directory / 'metadata.json')
    config = metadata['config']
    requests = directory / 'requests.jsonl'
    rows = []
    if requests.exists():
        with requests.open(encoding='utf-8') as handle:
            rows = [json.loads(line) for line in handle if line.strip()]
    telemetry = directory / 'telemetry.json'
    samples = read_json(telemetry) if telemetry.exists() else []
    facts = parse_backend_log(log_file.read_text(encoding='utf-8', errors='replace') if log_file.exists() else '')
    return {'schema_version': 1, 'benchmark': BENCHMARK, 'synthetic': metadata['synthetic'],
            'job_id': job['job_id'], 'status': metadata['status'], 'os_id': config['os_id'],
            'launch': config.get('launch', {}), 'placement_notes': config.get('placement_notes'),
            'observed_placement': {key: facts[key] for key in ('layers_offloaded', 'layers_total', 'model_loads',
                                                               'gpu_model_buffer_mib', 'host_model_buffer_mib')},
            'hardware_attestation': config.get('hardware_attestation', {}),
            'controls': {'physical_host_id': job['target']['physical_host_id'], 'code_revision': revision,
                         'hardware_profile_sha256': digest(metadata['hardware_profile']), 'harness_version': metadata['harness_version'],
                         'server_mode': job['parameters'].get('server_mode', 'external'), 'suite_sha256': metadata.get('suite_sha256'),
                         'artifact_sha256': metadata.get('artifact_sha256'),
                         'config': common_config(config)},
            'memory': memory_summary(metadata, samples), 'worker_load_s': metadata.get('worker_load_s'),
            'thermal': thermal_summary(samples, config.get('launch', {}).get('gpu', 0)),
            'workloads': {t['id']: workload_summary(t, rows, config['repeats']) for t in suite['tasks']}}


def compare(left, right, axis):
    """Compare declared single-factor settings, retaining failures, coverage and placement observations."""
    for arm in (left, right):
        if arm.get('benchmark') != BENCHMARK or arm.get('schema_version') != 1:
            raise ValueError('Both attempts must contain matched-offload-v1 summaries')
        if arm['synthetic'] or not all(arm['controls'].get(k) for k in ('artifact_sha256', 'suite_sha256', 'code_revision', 'physical_host_id')):
            raise ValueError('Comparison requires real measurements with pinned artifact, workload, host and revision')
    if left['controls'] != right['controls']:
        raise ValueError('Mismatched controls (artifact, hardware, workload, software or run settings)')
    launches = [dict(arm['launch']) for arm in (left, right)]
    observed = [arm['observed_placement'] for arm in (left, right)]
    layer_counts = [p['layers_offloaded'] for p in observed]
    stable = all(p['model_loads'] == 1 and p['layers_offloaded'] is not None for p in observed)
    if axis == 'gpu-layers':
        attestations = [{k: v for k, v in arm['hardware_attestation'].items()
                         if k not in ('paging', 'windows_host_used_gib_peak')} for arm in (left, right)]
        if attestations[0] != attestations[1]:
            raise ValueError('Same-OS placement comparison needs matching hardware settings and driver')
        layers = [launch.pop('gpu_layers', None) for launch in launches]
        if (left['os_id'] != right['os_id'] or launches[0] != launches[1] or
                not all(type(n) is int for n in layers) or layers[0] == layers[1]):
            raise ValueError('A GPU-layer pair must change only the requested GPU layer count on one OS')
        if stable and layer_counts != layers:
            raise ValueError('Logged GPU layer counts differ from the requested placement pair')
        if left['controls']['config']['platform'] not in ('llama.cpp', 'ik_llama.cpp', 'ollama', 'koboldcpp'):
            raise ValueError('GPU-layer comparison requires a backend with a gpu_layers launch setting')
    elif axis == 'os':
        if left['os_id'] == right['os_id'] or launches[0] != launches[1]:
            raise ValueError('An OS pair must change OS and keep the launch settings fixed')
        if stable and (layer_counts[0] != layer_counts[1] or observed[0]['layers_total'] != observed[1]['layers_total']):
            raise ValueError('Logged GPU layer placement differs across the OS pair')
        config = left['controls']['config']
        if (config.get('hardware_profile') == 'msi-raider-18-hx-ai' and
                any('wsl2' in arm['os_id'] for arm in (left, right)) and config['ram_budget_gib'] != 46):
            raise ValueError('The matched WSL OS comparison uses the 46 GiB host-weight budget')
    else:
        raise ValueError('Unknown comparison axis')
    comparison = {}
    for name, a in left['workloads'].items():
        b = right['workloads'][name]
        if a['prompt_sha256'] != b['prompt_sha256']:
            raise ValueError('Workload prompts differ')
        group = 'qualifying_metrics' if name in LENGTH_TARGETS else 'metrics'
        comparison[name] = {'left': a, 'right': b, 'delta_basis': group, 'right_minus_left_median': {
            key: b[group][key]['median'] - m['median']
            if m['n'] and b[group][key]['n'] else None for key, m in a[group].items()}}
    return {'benchmark': BENCHMARK, 'axis': axis, 'controls': left['controls'],
            'layer_count_evidence': 'one_logged_load_per_arm' if stable else 'requested_only',
            'arms': [{k: arm[k] for k in ('job_id', 'status', 'os_id', 'launch', 'placement_notes',
                                          'observed_placement', 'hardware_attestation', 'memory', 'thermal',
                                          'managed_backend_start_to_ready_s', 'worker_load_s')} for arm in (left, right)],
            'workloads': comparison}


def main(argv=None):
    parser = argparse.ArgumentParser(description='Compare two matched-performance attempt result.json files')
    parser.add_argument('--axis', choices=('gpu-layers', 'os'), required=True)
    parser.add_argument('left', type=Path)
    parser.add_argument('right', type=Path)
    args = parser.parse_args(argv)
    try:
        result = compare(read_json(args.left)['performance'], read_json(args.right)['performance'], args.axis)
    except (KeyError, ValueError, OSError) as exc:
        parser.exit(2, f'Comparison unavailable: {exc}\n')
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
