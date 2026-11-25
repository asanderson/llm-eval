"""Generate measured context tiers and summarize their frozen VRAM predictions."""
import argparse
from collections import defaultdict
import gzip
import json
from pathlib import Path

from llm_eval.common import GIB, read_json, sha256_file, write_json
from llm_eval.core.contracts import fields, identifier, integer
from llm_eval.orchestration.planner import resolve_paths
from . import projection


def check_probe(probe, config):
    fields(probe, {'target_prompt_tokens', 'tolerance_tokens'}, ['target_prompt_tokens', 'tolerance_tokens'])
    target = integer(probe['target_prompt_tokens'], 'target_prompt_tokens', 1, config['context_tokens'])
    tolerance = integer(probe['tolerance_tokens'], 'tolerance_tokens', 0, target - 1)
    if target + tolerance + config['max_output_tokens'] > config['context_tokens']:
        raise ValueError('Context probe must reserve the entire output budget above its target and tolerance')


def prompt_usage(paths, config, probe=None):
    """Backend counts from successful measured requests only. Missing counts remain visible."""
    prompts, outputs, totals = [], [], []
    requests = successful = warmups_ok = in_band = unreadable = 0
    for path in paths:
        with path.open(encoding='utf-8') as handle:
            for line in handle:
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:  # An interrupted writer can leave its final row unfinished.
                    unreadable += 1
                    continue
                if row['warmup']:
                    warmups_ok += row['status'] == 'ok'
                    continue
                requests += 1
                if row['status'] != 'ok':
                    continue
                successful += 1
                prompt, output = row.get('prompt_tokens'), row.get('completion_tokens')
                if type(prompt) is int and prompt > 0:
                    prompts.append(prompt)
                if type(output) is int and output >= 0:
                    outputs.append(output)
                if type(prompt) is int and prompt > 0 and type(output) is int and output >= 0:
                    totals.append(prompt + output)
                    if probe and abs(prompt - probe['target_prompt_tokens']) <= probe['tolerance_tokens'] and (
                            0 < output <= config['max_output_tokens'] and prompt + config['max_output_tokens'] <= config['context_tokens']):
                        in_band += 1
    return {'configured_context_tokens': config['context_tokens'], 'reserved_output_tokens': config['max_output_tokens'],
            'measured_requests': requests, 'successful_requests': successful, 'successful_warmups': warmups_ok,
            'unreadable_rows': unreadable, 'prompt_counted_requests': len(prompts),
            'completion_counted_requests': len(outputs), 'prompt_tokens_min': min(prompts, default=None),
            'prompt_tokens_max': max(prompts, default=None), 'completion_tokens_min': min(outputs, default=None),
            'completion_tokens_max': max(outputs, default=None), 'total_tokens_max': max(totals, default=None),
            'probe': {**probe, 'requests_in_band': in_band, 'passed': requests > 0 and in_band == requests and unreadable == 0} if probe else None}


def frozen_prediction(spec, config, profile, lock):
    """Project VRAM from a candidate with exactly the verified weight files, using only pre-run assumptions."""
    fields(spec, {'data', 'candidate_id', 'policy'}, ['data', 'candidate_id'])
    candidates = projection.load_candidates(spec['data'])
    if candidates.get('synthetic'):
        raise ValueError('A VRAM prediction requires a real candidate set')
    candidate = next((c for c in candidates['candidates'] if c['id'] == spec['candidate_id']), None)
    if not candidate or candidate['model_id'] != config['model_id']:
        raise ValueError('Prediction candidate must match the measured model')
    weights = sorted((f['bytes'], f['sha256']) for f in lock['files'] if f['weight'])
    if weights != sorted((f['bytes'], f['sha256']) for f in candidate['files']):
        raise ValueError('Prediction candidate weight hashes and sizes differ from the locked artifact')
    model = next(m for m in candidates['models'] if m['model_id'] == candidate['model_id'])
    policy = projection.effective_policy(spec.get('policy', {}), profile['cpu']['threads'])
    required = projection.vram_needs(candidate['weight_bytes'], model, config['context_tokens'], policy)['vram_required']
    available = (profile['gpu']['vram_gib'] - profile['gpu'].get('initial_reserve_gib', 0) - policy['gpu_baseline_gib']) * GIB
    return {'candidate_id': candidate['id'], 'candidate_set_id': candidates['id'], 'candidate_set_sha256': sha256_file(spec['data']),
            'policy': policy, 'predicted_vram_fit': required <= available, 'predicted_headroom_mib': (available - required) / 2**20}


def compare_prediction(record):
    prediction = record.get('prediction')
    if prediction is None:
        return
    kind = record['fit_class']
    observed = True if kind == 'backend_confirmed' else False if kind in ('capacity_failure', 'placement_failure') else None
    # A partial placement or unsuccessful serving path never measured the predicted fully resident footprint.
    comparable_peak = kind == 'backend_confirmed' or (
        record.get('reason') == 'vram_reserve_exceeded' and record['placement'] in ('all_layers_on_gpu', 'reported_in_vram'))
    headroom = record.get('headroom_mib')
    prediction.update(false_fit=prediction['predicted_vram_fit'] and not observed if observed is not None else None,
                      headroom_error_mib=headroom - prediction['predicted_headroom_mib'] if comparable_peak and headroom is not None else None)


def _latest(records):
    seen = set()
    for row in records:
        if not row['latest_attempt'] or row['source_file'] not in ('fit/metadata.json', 'metadata.json'):
            continue
        if row['data'].get('record') not in ('fit-evidence', 'fit-projection'):
            continue
        key = row['job_id'], row['attempt_id'], row['source_file']
        if key not in seen:
            seen.add(key)
            yield row


def _runtime_summary(records):
    by_runtime = defaultdict(list)
    for row in records:
        record = row['data']
        if record['record'] == 'fit-evidence' and not record.get('synthetic'):
            runtime = record['requested']['platform'], record.get('backend_version')
            by_runtime[runtime].append(record.get('prediction') or {})
    result = []
    for (platform, version), rows in sorted(by_runtime.items(), key=lambda item: (item[0][0], item[0][1] or '')):
        errors = [p['headroom_error_mib'] for p in rows if p.get('headroom_error_mib') is not None]
        predicted_fit = [p for p in rows if p.get('predicted_vram_fit') and p.get('false_fit') is not None]
        result.append({'platform': platform, 'backend_version': version, 'attempts': len(rows),
                       'matched_predictions': sum(bool(p) for p in rows), 'assessed_predicted_fits': len(predicted_fit),
                       'false_fits': sum(p['false_fit'] for p in predicted_fit), 'headroom_error_pairs': len(errors),
                       'mean_headroom_error_mib': sum(errors) / len(errors) if errors else None,
                       'mean_absolute_headroom_error_mib': sum(abs(e) for e in errors) / len(errors) if errors else None})
    return result


def summarize(paths):
    """Aggregate latest evidence from generic report bundles, counting each attempt once."""
    def records():
        for path in paths:
            with gzip.open(path, 'rt', encoding='utf-8') as stream:
                for line in stream:
                    yield json.loads(line)
    return _runtime_summary(_latest(records()))


def report_supplement(records):
    """Reader-facing coverage from sanitized public rows. Only scalar evidence fields enter the supplement."""
    latest = list(_latest(records))
    jobs = []
    for row in latest:
        data = row['data']
        usage = data.get('prompt_usage') or {}
        projected = data['record'] == 'fit-projection'
        jobs.append({'job': row['job_id'], 'fit_class': 'projected' if projected else data.get('fit_class', 'legacy_record'),
                     'synthetic': bool(data.get('synthetic')), 'failure_stage': data.get('failure_stage'), 'reason': data.get('reason'),
                     'configured_context_tokens': data.get('context_tokens') if projected else data['requested'].get('context_tokens'),
                     'prompt_tokens_min': usage.get('prompt_tokens_min'), 'prompt_tokens_max': usage.get('prompt_tokens_max'),
                     'prompt_counted_requests': usage.get('prompt_counted_requests'), 'measured_requests': usage.get('measured_requests'),
                     'headroom_mib': data.get('headroom_mib')})
    by_runtime = _runtime_summary(latest)
    lines = ['## Hardware fit evidence', '',
             '| Job | Classification | Failure stage and reason | Configured window | Observed prompt tokens | Counted / measured | Peak headroom (MiB) |',
             '|---|---|---|---:|---:|---:|---:|']
    for j in jobs:
        label = j['fit_class'].replace('_', ' ') + (' (synthetic)' if j['synthetic'] else '')
        failure = ' / '.join(x for x in (j['failure_stage'], j['reason']) if x) or '—'
        prompt = f"{j['prompt_tokens_min']}–{j['prompt_tokens_max']}" if j['prompt_tokens_min'] is not None else '—'
        count = f"{j['prompt_counted_requests']} / {j['measured_requests']}" if j['measured_requests'] is not None else '—'
        headroom = '—' if j['headroom_mib'] is None else f"{j['headroom_mib']:.1f}"
        lines.append(f"| {j['job']} | {label} | {failure} | {j['configured_context_tokens']} | {prompt} | {count} | {headroom} |")
    if not jobs:
        lines.append('| — | No fit evidence recorded | — | — | — | — | — |')
    if by_runtime:
        lines.extend(['', '### Frozen VRAM predictions by runtime', '',
                      '| Runtime | Matched / attempts | False fits / assessed predicted fits | Headroom error pairs | Mean error (MiB) | Mean absolute error (MiB) |',
                      '|---|---:|---:|---:|---:|---:|'])
        for r in by_runtime:
            runtime = r['platform'] + ' ' + str(r['backend_version'] or '(version unrecorded)').replace('|', r'\|').replace('\n', ' ')
            mean, absolute = r['mean_headroom_error_mib'], r['mean_absolute_headroom_error_mib']
            error = '—' if mean is None else f'{mean:.1f}'
            magnitude = '—' if absolute is None else f'{absolute:.1f}'
            lines.append(f"| {runtime} | {r['matched_predictions']} / {r['attempts']} | {r['false_fits']} / {r['assessed_predicted_fits']} | "
                         f"{r['headroom_error_pairs']} | {error} | {magnitude} |")
        lines.extend(['', 'Headroom error equals observed minus predicted after-reserve headroom. False fits require a measured capacity or placement failure. '
                      'Only backend-confirmed passes and attributable failures enter the assessed denominator.'])
    return {'jobs': jobs, 'by_runtime': by_runtime}, '\n'.join(lines) + '\n\n'


def prepare(case_path, inventory, hardware_id, directory, output_tokens=128, tolerance=64):
    """Plan one isolated, cold measured job per increasing prompt tier; stop the sweep on failure."""
    case = read_json(case_path)['parameters']
    if case.get('synthetic') or case['server_mode'] != 'managed':
        raise ValueError('Choose a real managed measured case')
    params = resolve_paths(case, case_path.resolve().parent)
    if isinstance(params['config'], str):
        source = case_path.resolve().parent / params['config']
        config = resolve_paths(read_json(source), source.parent)
    else:
        config = params['config']
    hardware = read_json(inventory)['hardware_configs'][identifier(hardware_id)]
    overrides = hardware.get('overrides', {})
    if {'max_output_tokens', 'context_tokens'} & overrides.keys():
        raise ValueError('Remove context and output overrides from the study inventory so each tier controls its budget')
    maximum = integer(config['context_tokens'], 'context_tokens', 512, 1048576)
    integer(output_tokens, 'output_tokens', 1, min(8192, maximum - 1))
    integer(tolerance, 'tolerance_tokens', 0, min(256, (maximum - output_tokens - 1) // 2))
    limit = maximum - output_tokens - tolerance
    targets = {t for t in (2048, 4096) if t < limit}
    boundary = 8192
    while boundary < maximum:
        if boundary - output_tokens - tolerance > 4096:
            targets.add(boundary - output_tokens - tolerance)
        boundary *= 2
    targets.add(limit)
    directory.mkdir(parents=True, exist_ok=False)
    phases = []
    params.pop('categories', None)
    for target in sorted(targets):
        case_id = f'prompt-{target}'
        suite = case_id + '-suite.json'
        write_json(directory / suite, {'benchmark': 'fit-context-boundary', 'category': 'context-boundary',
                   'tasks': [{'id': case_id, 'messages': [{'role': 'user', 'content':
                            'Read the following words and then reply OK.\n' + ' blue' * max(1, target - 32)}]}]})
        # Prompt construction is deterministic. Its actual count is measured by the serving tokenizer.
        run = {**config, 'context_tokens': target + tolerance + output_tokens, 'max_output_tokens': output_tokens,
               'warmups': 0, 'repeats': 1, 'suite': suite, 'request_usage': True,
               'cache_condition': 'fresh managed launch; one request at this tier'}
        params_at_target = {**params, 'config': run, 'context_probe': {'target_prompt_tokens': target, 'tolerance_tokens': tolerance}}
        write_json(directory / (case_id + '.json'), {'id': case_id, 'parameters': params_at_target})
        phases.append({'id': case_id, 'depends_on': [phases[-1]['id']] if phases else [], 'experiments': [
            {'id': 'hardware-fit', 'version': 1, 'mode': 'measured', 'cases': [case_id + '.json'], 'hardware_configs': [hardware_id]}]})
    path = directory / 'campaign.json'
    write_json(path, {'schema_version': 2, 'id': 'fit-context-boundary', 'inventory': str(inventory.resolve()),
                      'execution': {'max_parallel_jobs': 1, 'on_failure': 'fail-fast'}, 'phases': phases})
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    generate = commands.add_parser('prepare', help='generate increasing context tiers from a pinned measured case')
    for name in ('case', 'inventory', 'out'):
        generate.add_argument('--' + name, required=True, type=Path)
    generate.add_argument('--hardware', required=True)
    generate.add_argument('--output-tokens', type=int, default=128)
    generate.add_argument('--tolerance', type=int, default=64)
    summary = commands.add_parser('summarize', help='summarize predictions from exported raw/measurements.jsonl.gz files')
    summary.add_argument('files', nargs='+', type=Path)
    args = parser.parse_args()
    if args.command == 'prepare':
        print(prepare(args.case, args.inventory, args.hardware, args.out, args.output_tokens, args.tolerance))
    else:
        print(json.dumps(summarize(args.files), indent=2))


if __name__ == '__main__':
    main()
