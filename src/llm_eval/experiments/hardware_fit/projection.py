"""Projected fit of candidate artifacts into the GPU VRAM of one hardware configuration.

Arithmetic over a frozen candidate set (artifact byte sizes and architecture facts) and the bound hardware profile, under
a declared policy. Nothing here loads a model or reads a GPU: the result is a projection, never a measurement, and the
shortlist order is a planning heuristic, not a quality ranking."""
import datetime
import json
from pathlib import Path, PurePosixPath
import re
import shutil

from llm_eval.common import GIB, finite_number, read_json, require_revision, sha256_file
from llm_eval.core import hardware
from llm_eval.core.contracts import fields, identifier, integer

BENCHMARK = 'fit-projection'
VERDICTS = ('fits', 'exceeds-vram', 'exceeds-ram', 'exceeds-disk', 'exceeds-cpu', 'exceeds-context')
CAVEAT = ('Projected from artifact byte sizes and a declared policy, not measured. The shortlist order (larger model first, '
          'then higher precision) is a planning heuristic, not a quality measurement.')

LARGEST_GIB = 2 ** 20      # one pebibyte: above any machine, and small enough that the byte count stays a finite number
# key: (default, lowest, highest, whole number). One planning assumption each; a case overrides any of them under `policy`.
POLICY = {
    'kv_bytes_per_element': (2, 0.5, 4, False),                 # f16 key and value cache, the engines' default; 4 is f32
    'compute_buffer_gib': (1.0, 0, LARGEST_GIB, False),         # allowance for the engine's compute and scratch buffers on the GPU
    'gpu_baseline_gib': (0.0, 0, LARGEST_GIB, False),           # VRAM other programs hold, and the profile's nominal VRAM above what the card reports
    'host_ram_overhead_gib': (8.0, 0, LARGEST_GIB, False),      # RAM for the OS, the harness and the engine process
    'host_ram_weight_fraction': (0.0, 0, 1, False),             # share of the weights a loader stages in RAM; 1.0 reads them all into RAM first
    'disk_copies': (2, 1, 16, True),                            # the artifact plus one harness import copy (Ollama imports a copy)
    'disk_headroom_gib': (10.0, 0, LARGEST_GIB, False),         # free space that must remain after the copies
    'threads': (None, 1, 4096, True),                           # launch threads; unset is the launch default, min(16, profile threads)
    'min_bits_per_weight': (4.0, 0, 64, False),                 # lower quantizations are listed but never shortlisted; 0 disables the floor
    'shortlist': (10, 1, 1000, True),                           # number of ranked entries
}

SET_KEYS = ('schema_version', 'id', 'retrieved_on', 'description', 'size_basis', 'architecture_basis', 'models', 'candidates')
MODEL_KEYS = ('model_id', 'base_model', 'architecture', 'parameters', 'layers', 'kv_elements_per_token', 'trained_context_tokens',
              'sliding_window_tokens', 'source_repo', 'source_revision')
CANDIDATE_KEYS = ('id', 'model_id', 'quantization', 'weight_bytes', 'files')
FILE_KEYS = ('path', 'bytes', 'sha256')
LARGEST = 2 ** 63 - 1


def _count(value, name, low=1):
    return integer(value, name, low, LARGEST)


def _text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(name + ' must be a non-empty string')


def _repository(value, name):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', value):
        raise ValueError(name + ' must be a repository id written as ORG/NAME')


def _file(entry, owner):
    """One artifact file: a path that names a file inside the repository it is listed from, a byte size and its SHA-256."""
    fields(entry, FILE_KEYS, FILE_KEYS)
    path = entry['path']
    if (not isinstance(path, str) or not PurePosixPath(path).name.strip() or '\\' in path or ':' in path or PurePosixPath(path).is_absolute()
            or '..' in PurePosixPath(path).parts or PurePosixPath(path).as_posix() != path):
        raise ValueError(owner + ' file path must be a relative POSIX path without ..')
    _count(entry['bytes'], owner + ' file bytes')
    if not isinstance(entry['sha256'], str) or not re.fullmatch(r'[0-9a-f]{64}', entry['sha256']):
        raise ValueError(owner + ' file sha256 must be 64 lowercase hexadecimal digits')


def load_candidates(path):
    """Read and check a candidate set: the frozen artifact sizes and architecture facts a projection is computed from."""
    data = fields(read_json(path), {*SET_KEYS, 'excluded', 'synthetic'}, SET_KEYS)
    if type(data['schema_version']) is not int or data['schema_version'] != 1:      # true and 1.0 equal 1 in Python
        raise ValueError('Candidate set schema_version must be 1')
    identifier(data['id'])
    try:
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', data['retrieved_on']):
            raise ValueError
        datetime.date.fromisoformat(data['retrieved_on'])
    except (TypeError, ValueError):
        raise ValueError('retrieved_on must be a date written as YYYY-MM-DD') from None
    for key in ('description', 'size_basis', 'architecture_basis', *(['excluded'] if 'excluded' in data else [])):
        _text(data[key], key)
    if not isinstance(data.get('synthetic', False), bool):
        raise ValueError('synthetic must be true or false')
    if not isinstance(data['models'], list) or not data['models']:
        raise ValueError('Candidate set needs at least one model')
    if not isinstance(data['candidates'], list) or not data['candidates']:
        raise ValueError('Candidate set needs at least one candidate')
    models = set()
    for model in data['models']:
        fields(model, MODEL_KEYS, MODEL_KEYS)
        name = identifier(model['model_id'])
        if name in models:
            raise ValueError('Duplicate model_id in candidate set: ' + name)
        models.add(name)
        _text(model['architecture'], name + ' architecture')
        for key in ('base_model', 'source_repo'):
            _repository(model[key], name + ' ' + key)
        for key in ('parameters', 'layers', 'kv_elements_per_token', 'trained_context_tokens'):
            _count(model[key], name + ' ' + key)
        _count(model['sliding_window_tokens'], name + ' sliding_window_tokens', 0)      # 0: the model has no sliding-window layers
        require_revision(model['source_revision'])
    candidates = set()
    for candidate in data['candidates']:
        fields(candidate, CANDIDATE_KEYS, CANDIDATE_KEYS)
        name = identifier(candidate['id'])
        if name in candidates:
            raise ValueError('Duplicate candidate id: ' + name)
        candidates.add(name)
        if not isinstance(candidate['model_id'], str) or candidate['model_id'] not in models:
            raise ValueError('Candidate ' + name + ' names an undeclared model_id')
        _text(candidate['quantization'], 'Candidate ' + name + ' quantization')
        _count(candidate['weight_bytes'], 'Candidate ' + name + ' weight_bytes')
        if not isinstance(candidate['files'], list) or not candidate['files']:
            raise ValueError('Candidate ' + name + ' needs at least one file')
        for entry in candidate['files']:
            _file(entry, 'Candidate ' + name)
        if len({f['path'] for f in candidate['files']}) != len(candidate['files']):
            raise ValueError('Candidate ' + name + ' lists a file twice')
        if candidate['weight_bytes'] != sum(f['bytes'] for f in candidate['files']):
            raise ValueError('Candidate ' + name + ' weight_bytes does not equal the sum of its files')
    return data


def check_policy(policy):
    """The declared defaults with a case's overrides, every value inside its range. `threads` may still be unset."""
    fields(policy, POLICY)
    checked = {}
    for key, (default, low, high, whole) in POLICY.items():
        checked[key] = policy.get(key, default)
        if not (key == 'threads' and checked[key] is None):
            (integer if whole else finite_number)(checked[key], 'policy.' + key, low, high)
    return checked


def effective_policy(policy, cpu_threads):
    """The checked policy with `threads` resolved: unset means the launch default, min(16, profile threads)."""
    effective = check_policy(policy)
    if effective['threads'] is None:
        effective['threads'] = min(16, cpu_threads)
    return effective


def free_disk_bytes(directory):
    """Free bytes of the volume that holds `directory`, read at its nearest existing ancestor: the directory need not exist yet."""
    path = Path(directory).resolve()
    while not path.exists() and path != path.parent:
        path = path.parent
    return shutil.disk_usage(path).free


def hardware_view(job, root):
    """The limits a projection checks against, from the hardware configuration the job is bound to. Free disk space is the
    declared value, or measured where the artifacts are stored only when none is declared."""
    parameters = job['parameters']
    bound = {'hardware_profile': job['hardware']['hardware_profile'], 'os_id': job['hardware']['os_id']}
    profile = job.get('hardware_profile') or hardware.profile(bound, root)
    limits = hardware.limits(bound, root)
    view = {**bound, 'gpu_name': profile['gpu']['name'], 'vram_gib': profile['gpu']['vram_gib'],
            'vram_reserve_gib': profile['gpu'].get('initial_reserve_gib', 0), 'cpu_threads': limits['threads'],
            'ram_installed_gib': profile['ram']['installed_gib'], 'ram_budget_gib': limits['ram_budget_gib']}
    if 'disk_free_gib' in parameters:
        view.update(disk_free_gib=parameters['disk_free_gib'], disk_basis='declared')
    else:
        view.update(disk_free_gib=free_disk_bytes(parameters['artifact_root']) / GIB, disk_basis='measured')
    return view


def fit(weight_bytes, model, view, context_tokens, policy):
    """Byte needs of one artifact at one context length, and the limits it exceeds in the order vram, ram, disk, cpu, context.

    The cache need is every layer's key and value elements for the whole context. Sliding-window layers keep less, so the
    figure is an overestimate for models that have them."""
    kv_bytes = model['kv_elements_per_token'] * context_tokens * policy['kv_bytes_per_element']
    needs = {'kv_bytes': kv_bytes, 'compute_bytes': policy['compute_buffer_gib'] * GIB,
             'vram_available': (view['vram_gib'] - view['vram_reserve_gib'] - policy['gpu_baseline_gib']) * GIB,
             'ram_required': policy['host_ram_overhead_gib'] * GIB + policy['host_ram_weight_fraction'] * weight_bytes,
             'disk_required': weight_bytes * policy['disk_copies'] + policy['disk_headroom_gib'] * GIB,
             'bits_per_weight': weight_bytes * 8 / model['parameters']}
    needs['vram_required'] = weight_bytes + kv_bytes + needs['compute_bytes']
    exceeded = (('vram', needs['vram_required'] > needs['vram_available']),
                ('ram', needs['ram_required'] > view['ram_budget_gib'] * GIB),
                ('disk', needs['disk_required'] > view['disk_free_gib'] * GIB),
                ('cpu', policy['threads'] > view['cpu_threads']),
                ('context', context_tokens > model['trained_context_tokens']))
    needs['limits'] = [name for name, over in exceeded if over]
    return needs


def _gib(value):
    return round(value / GIB, 4)


def project(candidate_set, view, context_tokens, policy, synthetic=False):
    """One row per candidate, sorted by id, with each model's best fit and its shortlist rank.

    A model's best is its fitting candidate of at least `min_bits_per_weight` with the most bits per weight. The shortlist
    orders those by parameter count, then bits per weight, then id, and is cut to `shortlist` entries. The rows carry no
    scored check on purpose: a projection must not enter the ranking of measured results."""
    models = {m['model_id']: m for m in candidate_set['models']}
    candidates = {c['id']: c for c in candidate_set['candidates']}
    needs = {name: fit(c['weight_bytes'], models[c['model_id']], view, context_tokens, policy) for name, c in candidates.items()}
    eligible = [name for name, n in needs.items() if not n['limits'] and n['bits_per_weight'] >= policy['min_bits_per_weight']]
    best = {}
    for name in sorted(eligible, key=lambda name: (-needs[name]['bits_per_weight'], -candidates[name]['weight_bytes'], name)):
        best.setdefault(candidates[name]['model_id'], name)
    order = sorted(best.values(), key=lambda name: (-models[candidates[name]['model_id']]['parameters'], -needs[name]['bits_per_weight'], name))
    ranks = {name: rank for rank, name in enumerate(order[:policy['shortlist']], 1)}
    bests = set(order)
    rows = []
    for name in sorted(candidates):
        candidate, n = candidates[name], needs[name]
        rows.append({
            'task_id': name, 'category': 'exceeds-' + n['limits'][0] if n['limits'] else 'fits', 'benchmark': BENCHMARK, 'status': 'ok',
            'warmup': False, 'repetition': 0, 'synthetic': synthetic, 'elapsed_s': None, 'quality_check_applicable': False,
            'model_id': candidate['model_id'], 'quantization': candidate['quantization'],
            'parameters_b': round(models[candidate['model_id']]['parameters'] / 1e9, 4), 'bits_per_weight': round(n['bits_per_weight'], 4),
            'weight_gib': _gib(candidate['weight_bytes']), 'kv_cache_gib': _gib(n['kv_bytes']), 'compute_buffer_gib': _gib(n['compute_bytes']),
            'vram_required_gib': _gib(n['vram_required']), 'vram_available_gib': _gib(n['vram_available']),
            'vram_headroom_gib': _gib(n['vram_available'] - n['vram_required']), 'ram_required_gib': _gib(n['ram_required']),
            'disk_required_gib': _gib(n['disk_required']), 'limits': n['limits'], 'fits': not n['limits'],
            'model_best': name in bests, 'rank': ranks.get(name)})
    return rows


def observed_hardware():
    """What this host reports, for comparison with the profile the projection used. Unavailable readings stay null."""
    from llm_eval.telemetry import host_snapshot
    snapshot = host_snapshot()
    ram = snapshot.get('ram_total_gib')
    return {'gpus': [{'name': g['name'], 'total_mib': g['total_mib']} for g in snapshot['gpus']],
            'ram_total_gib': None if ram is None else round(ram, 4), 'logical_cpus': snapshot.get('logical_cpus')}


def _table(metadata):
    """The shortlist and the verdict counts as Markdown, for the operator. The generic report does not export this file."""
    h, c = metadata['hardware'], metadata['candidate_set']
    lines = ['# Hardware fit projection', '', metadata['caveat'], '',
             f"Hardware configuration: `{h['hardware_profile']}` on `{h['os_id']}`: {h['gpu_name']}, {h['vram_gib']} GiB VRAM with "
             f"{h['vram_reserve_gib']} GiB reserved, {h['cpu_threads']} CPU threads, {h['ram_budget_gib']} GiB RAM budget, "
             f"{h['disk_free_gib']} GiB free disk ({h['disk_basis']}).", '',
             f"Candidate set: `{c['id']}`, retrieved {c['retrieved_on']}, {c['candidate_count']} candidates of {c['model_count']} models. "
             f"Context: {metadata['context_tokens']} tokens. Synthetic fixtures: {str(metadata['synthetic']).lower()}.", '',
             '## Verdicts', '', '| Verdict | Candidates |', '|---|---:|']
    lines += [f'| {verdict} | {count} |' for verdict, count in metadata['counts'].items()]
    lines += ['', '## Shortlist', '']
    if metadata['shortlist']:
        lines += ['| Rank | Candidate | Model | Quantization | Parameters (B) | Bits per weight | Weights GiB | VRAM required GiB | VRAM headroom GiB |',
                  '|---:|---|---|---|---:|---:|---:|---:|---:|']
        lines += [f"| {e['rank']} | {e['id']} | {e['model_id']} | {e['quantization']} | {e['parameters_b']} | {e['bits_per_weight']} | "
                  f"{e['weight_gib']} | {e['vram_required_gib']} | {e['vram_headroom_gib']} |" for e in metadata['shortlist']]
    else:
        lines.append('No candidate fits every limit at or above the minimum bits per weight.')
    lines += ['', '## Policy', '', '| Setting | Value |', '|---|---:|']
    lines += [f'| {key} | {value} |' for key, value in metadata['policy'].items()]
    return '\n'.join(lines) + '\n'


def execute(job, output, root):
    """Write the projection of one case: a row per candidate, the metadata with the shortlist, and a table for the operator."""
    case = job['parameters']
    synthetic = case.get('synthetic', False)
    candidate_set = load_candidates(case['data'])
    view = hardware_view(job, root)
    policy = effective_policy(case.get('policy', {}), view['cpu_threads'])
    rows = project(candidate_set, view, case['context_tokens'], policy, synthetic)
    with (output / 'requests.jsonl').open('w', encoding='utf-8', newline='\n') as handle:      # LF on every OS: same bytes for the same inputs
        for row in rows:
            handle.write(json.dumps(row, allow_nan=False) + '\n')
    shortlist = sorted((r for r in rows if r['rank']), key=lambda r: r['rank'])
    metadata = {
        'experiment': 'hardware-fit', 'record': BENCHMARK, 'schema_version': 1, 'synthetic': synthetic,
        'candidate_set': {'id': candidate_set['id'], 'retrieved_on': candidate_set['retrieved_on'], 'sha256': sha256_file(case['data']),
                          'model_count': len(candidate_set['models']), 'candidate_count': len(candidate_set['candidates'])},
        'context_tokens': case['context_tokens'], 'policy': policy,
        'hardware': {**view, 'disk_free_gib': round(view['disk_free_gib'], 4)},
        'observed': None if synthetic else observed_hardware(),
        'counts': {verdict: sum(r['category'] == verdict for r in rows) for verdict in VERDICTS},
        'shortlist': [{'rank': r['rank'], 'id': r['task_id'], **{k: r[k] for k in ('model_id', 'quantization', 'parameters_b', 'bits_per_weight',
                                                                              'weight_gib', 'vram_required_gib', 'vram_headroom_gib')}}
                      for r in shortlist],
        'caveat': CAVEAT}
    (output / 'metadata.json').write_text(json.dumps(metadata, indent=2, ensure_ascii=False, allow_nan=False) + '\n', encoding='utf-8', newline='\n')
    (output / 'fit-projection.md').write_text(_table(metadata), encoding='utf-8', newline='\n')
    return {'status': 'succeeded', 'result_path': '.', 'benchmark': BENCHMARK, 'candidates': len(rows), 'fits': metadata['counts']['fits']}
