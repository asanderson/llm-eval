"""Gated import of a released public benchmark into a legal suite, as an explicit operator step on local bytes.

`python -m llm_eval.experiments.legal_benchmark.benchmarks import --request FILE --output DIR`,
`... parity --dataset-lock FILE --native FILE`, `... gate --dataset-lock FILE --gate NAME --evidence ID --verified-by ID`.

Nothing is downloaded: the operator supplies the upstream bytes. An imported suite is `public-benchmark` and does not load
until five gates are verified: `bytes` (set by the import when every expected digest matches, and re-checked against the
pinned manifests and copies at every load), and `license`, `jurisdiction`, `split` and `grader_parity`, which an operator
sets after checking them (grader parity needs a matching parity run against the upstream scorer). "Treat unverified
licenses, data access and grader parity as blocked import gates."
"""
from __future__ import annotations

import argparse
import bisect
import datetime
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import shutil
import sys

from llm_eval.common import sha256_file
from llm_eval.core.contracts import fields, identifier

from . import contracts, ingest

GATES = ('bytes', 'license', 'jurisdiction', 'split', 'grader_parity')
ADAPTERS = {
    'legalbench-rag':          {'available': True,  'cohort': 'contract-privacy', 'reason': None},
    'ecfr-temporal':           {'available': False, 'cohort': 'us-federal-regulations', 'reason': 'release_format_unverified'},
    'legalreasonbench-sample': {'available': False, 'cohort': 'packet-memo', 'reason': 'release_format_unverified'},
    'harvey-public':           {'available': False, 'cohort': 'packet-memo', 'reason': 'release_format_unverified'},
}
ADAPTER_VERSION = '1'
LOCK_KEYS = ('schema_version', 'dataset_id', 'adapter', 'adapter_version', 'upstream', 'license', 'jurisdiction', 'split', 'protocol',
             'files', 'derived', 'gates', 'examples', 'parity')
UPSTREAM_KEYS = ('name', 'revision', 'source_date', 'publication_status', 'origin', 'annotation_origin')
REQUEST_KEYS = ('schema_version', 'adapter', 'source_dir', 'component', 'split', 'limit', 'expected_files', 'upstream', 'license',
                'jurisdiction')
GATE_KEYS = ('status', 'evidence', 'verified_by', 'verified_utc')
PARITY_STATUSES = ('not_run', 'match', 'mismatch')
PARITY_TOLERANCE = 1e-9
SPAN_CHARS = 1000
SAMPLE_KEYS = ('upstream_id', 'local_precision', 'local_recall', 'native_precision', 'native_recall', 'difference',
               'precision_denominator_empty', 'recall_denominator_empty')
# Identifier-like token: evidence ids, verifier ids, origins, license names. No spaces, so no free text.
TOKEN = re.compile(r'[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,199}')
UTC = '%Y-%m-%dT%H:%M:%SZ'


def _token(value, name):
    if not isinstance(value, str) or not TOKEN.fullmatch(value):
        raise ValueError(name + ' must be an identifier-like string')
    return value


def _utc(value, name):
    try:
        datetime.datetime.strptime(value, UTC)
    except (TypeError, ValueError):
        raise ValueError(name + ' must be a UTC timestamp YYYY-MM-DDTHH:MM:SSZ') from None
    return value


_relative = contracts._relative      # the one validator of a suite-relative path


def _sorted_paths(items, keys, name):
    if not isinstance(items, list):
        raise ValueError(name + ' must be a list')
    for item in items:
        fields(item, keys, keys)
        _relative(item['path'])
        if not isinstance(item['sha256'], str) or not contracts.SHA256.fullmatch(item['sha256']):
            raise ValueError(name + ' digests must be 64 lowercase hex characters')
        if 'size' in keys and (type(item['size']) is not int or item['size'] < 0):
            raise ValueError(name + ' sizes must be integers')
    paths = [item['path'] for item in items]
    if paths != sorted(set(paths)):
        raise ValueError(name + ' must be sorted by path without repeats')


def _upstream(upstream):
    fields(upstream, UPSTREAM_KEYS, UPSTREAM_KEYS)
    contracts._text(upstream['name'], 'upstream name', 200)
    if not isinstance(upstream['revision'], str) or not contracts.REVISION.fullmatch(upstream['revision']):
        raise ValueError('upstream revision must be a commit or release identifier')
    contracts.iso_date(upstream['source_date'], 'upstream source_date')
    identifier(upstream['publication_status'])
    _token(upstream['origin'], 'upstream origin'); _token(upstream['annotation_origin'], 'upstream annotation_origin')


def _license(value):
    fields(value, ['name', 'scope'], ['name', 'scope'])
    _token(value['name'], 'license name')
    contracts._unique([identifier(s) for s in contracts._strings(value['scope'], 'license scope')], 'license scope')


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def validate_dataset(dataset_lock, rubric=None):
    """Dataset lock v1 (closed keys). Returns the lock; ValueError when it is malformed. With `rubric` (the imported grader
    manifest) a parity sample must also name examples of the import."""
    lock = dataset_lock
    fields(lock, LOCK_KEYS, LOCK_KEYS)
    contracts._version(lock['schema_version'], 'Unsupported dataset lock version')
    identifier(lock['dataset_id'])
    if lock['adapter'] not in ADAPTERS:
        raise ValueError('Unknown dataset adapter: ' + str(lock['adapter']))
    if not isinstance(lock['adapter_version'], str) or not contracts.REVISION.fullmatch(lock['adapter_version']):
        raise ValueError('adapter_version must be a revision identifier')
    _upstream(lock['upstream'])
    _license(lock['license'])
    identifier(lock['jurisdiction']); identifier(lock['split'])
    protocol = fields(lock['protocol'], ['reduced', 'adaptations'], ['reduced', 'adaptations'])
    if not isinstance(protocol['reduced'], bool) or not isinstance(protocol['adaptations'], list):
        raise ValueError('protocol needs reduced (true or false) and a list of adaptations')
    contracts._unique([identifier(a) for a in protocol['adaptations']], 'adaptation')
    _sorted_paths(lock['files'], ['path', 'size', 'sha256'], 'files')
    _sorted_paths(lock['derived'], ['path', 'sha256'], 'derived')
    fields(lock['gates'], GATES, GATES)
    for name in GATES:
        gate = fields(lock['gates'][name], GATE_KEYS, GATE_KEYS)
        if gate['status'] == 'verified':
            _token(gate['evidence'], 'gate evidence'); _token(gate['verified_by'], 'gate verified_by'); _utc(gate['verified_utc'], 'gate verified_utc')
        elif gate['status'] == 'blocked':
            if any(gate[key] is not None for key in GATE_KEYS[1:]):
                raise ValueError('A blocked gate records no verification: ' + name)
        else:
            raise ValueError('A gate is verified or blocked: ' + name)
    keys = ['total', 'upstream_total', 'imported', 'rejected', 'missing']
    examples = fields(lock['examples'], keys, keys)
    for key in ('total', 'upstream_total', 'imported'):
        contracts._count(examples[key], 'examples ' + key)
    if examples['total'] > examples['upstream_total']:
        raise ValueError('examples upstream_total must be at least the examples considered')
    if not isinstance(examples['rejected'], list) or not isinstance(examples['missing'], list):
        raise ValueError('rejected and missing examples must be lists')
    for item in examples['rejected']:
        fields(item, ['upstream_id', 'reason_code'], ['upstream_id', 'reason_code'])
        contracts._text(item['upstream_id'], 'upstream_id', 200)
        if not isinstance(item['reason_code'], str) or not contracts.REASON_CODE.fullmatch(item['reason_code']):
            raise ValueError('A rejected example needs a reason code')
    for item in examples['missing']:
        fields(item, ['upstream_id', 'file_path'], ['upstream_id', 'file_path'])
        contracts._text(item['upstream_id'], 'upstream_id', 200); contracts._text(item['file_path'], 'file_path', 1000)
    if examples['imported'] + len(examples['rejected']) + len(examples['missing']) != examples['total']:
        raise ValueError('Every example is imported, rejected or missing')
    parity = fields(lock['parity'], ['scorer', 'sample', 'max_abs_difference', 'status'], ['scorer', 'sample', 'max_abs_difference', 'status'])
    if parity['status'] not in PARITY_STATUSES:
        raise ValueError('Unknown parity status')
    if parity['scorer'] is not None:
        _token(parity['scorer'], 'parity scorer')
    if not isinstance(parity['sample'], list):
        raise ValueError('The parity sample must be a list of examples')
    for row in parity['sample']:
        fields(row, SAMPLE_KEYS, SAMPLE_KEYS)
        contracts._text(row['upstream_id'], 'upstream_id', 200)
        if any(not isinstance(row[k], bool) for k in SAMPLE_KEYS[6:]) or \
                any(row[k] is not None and not _number(row[k]) for k in SAMPLE_KEYS[1:6]) or \
                (row['difference'] is not None and row['difference'] < 0):
            raise ValueError('A parity sample row needs numbers or null and two denominator flags')
        compared = []      # the row's own difference is recomputed from its values
        for metric in ('precision', 'recall'):
            local, native = row['local_' + metric], row['native_' + metric]
            if row[metric + '_denominator_empty'] != (local is None):
                raise ValueError('A parity sample row disagrees with its own values: ' + row['upstream_id'])
            if local is None:
                continue
            if native is None:
                raise ValueError('A parity sample row needs a native value for every compared metric: ' + row['upstream_id'])
            compared.append(abs(local - native))
        if row['difference'] != (max(compared) if compared else None):
            raise ValueError('A parity sample row disagrees with its own values: ' + row['upstream_id'])
    if parity['max_abs_difference'] is not None and (not _number(parity['max_abs_difference']) or parity['max_abs_difference'] < 0):
        raise ValueError('max_abs_difference must be a non-negative number or null')
    if parity['status'] == 'not_run' and (parity['scorer'] is not None or parity['sample'] or parity['max_abs_difference'] is not None):
        raise ValueError('A parity check that was not run records no result')
    differences = [row['difference'] for row in parity['sample'] if row['difference'] is not None]
    if parity['status'] != 'not_run' and parity['max_abs_difference'] != (max(differences) if differences else None):
        raise ValueError('max_abs_difference must be the largest sample difference')
    if parity['status'] == 'match' and (not differences or max(differences) > PARITY_TOLERANCE):
        raise ValueError('A matching parity record differs beyond the tolerance or compares nothing')
    if rubric is not None and parity['sample']:
        known = {g.get('upstream_id') for g in (rubric.get('matters') if isinstance(rubric, dict) else None) or [] if isinstance(g, dict)}
        for row in parity['sample']:
            if row['upstream_id'] not in known:
                raise ValueError('The parity sample names an example that is not in the import: ' + row['upstream_id'])
    return lock


def _rubric_beside(path):
    rubric = Path(path).parent / 'rubric.json'
    return contracts.read_json_strict(rubric)[0] if rubric.is_file() else None


def _read(path):
    value, _ = contracts.read_json_strict(path)
    try:
        return validate_dataset(value, rubric=_rubric_beside(path))
    except (TypeError, AttributeError, KeyError, IndexError):
        raise ValueError('Malformed dataset lock') from None


def verify_dataset(lock_path):
    """The validated dataset lock read from `lock_path`, for operator tools."""
    return _read(lock_path)


def blocked_gates(dataset_lock, suite_entries=None):
    """Names of the gates, in GATES order, that are not effectively verified: status `verified` and its condition holds."""
    blocked = []
    for name in GATES:
        ok = dataset_lock['gates'][name]['status'] == 'verified'
        if name == 'bytes' and ok and suite_entries is not None:
            derived = {d['path']: d['sha256'] for d in dataset_lock['derived']}
            upstream = {f['sha256'] for f in dataset_lock['files']}
            # an edited manifest, or a swapped copy of an upstream file, reopens the gate even after a consistent relock
            ok = all(suite_entries.get(path) == digest for path, digest in derived.items()) and \
                all(digest in upstream for path, digest in suite_entries.items() if path not in derived)
        if name == 'grader_parity' and ok:
            parity = dataset_lock['parity']
            ok = parity['status'] == 'match' and bool(parity['scorer']) and bool(parity['sample'])
        if not ok:
            blocked.append(name)
    return blocked


def _write(path, value):
    Path(path).write_bytes(ingest._dump(value))


def _request(request):
    fields(request, REQUEST_KEYS, REQUEST_KEYS)
    contracts._version(request['schema_version'], 'Unsupported import request version')
    if not isinstance(request['adapter'], str):
        raise ValueError('Unknown dataset adapter')
    if not isinstance(request['source_dir'], str) or not request['source_dir']:
        raise ValueError('source_dir must be a path string')
    identifier(request['component']); identifier(request['split']); identifier(request['jurisdiction'])
    if request['limit'] is not None and (type(request['limit']) is not int or request['limit'] < 1):
        raise ValueError('limit must be a positive integer or null')
    if not isinstance(request['expected_files'], list) or not request['expected_files']:
        raise ValueError('expected_files must list the upstream digests')
    for item in request['expected_files']:
        fields(item, ['path', 'sha256'], ['path', 'sha256'])
        _relative(item['path'])
        if not isinstance(item['sha256'], str) or not contracts.SHA256.fullmatch(item['sha256']):
            raise ValueError('expected file digests must be 64 lowercase hex characters')
    contracts._unique([item['path'] for item in request['expected_files']], 'expected file')
    _upstream(request['upstream'])
    _license(request['license'])


def _newline_map(decoded):
    """Offset in the decoded upstream text -> offset in the same text with line endings normalised to LF."""
    pairs = [i for i in range(len(decoded) - 1) if decoded[i] == '\r' and decoded[i + 1] == '\n'] if '\r\n' in decoded else []
    return lambda offset: offset - bisect.bisect_left(pairs, offset)


def _document(corpus_root, file_path):
    """Converted upstream corpus file, or a reason code for the examples that need it."""
    try:
        path = contracts._inside(corpus_root, file_path)
    except ValueError:
        return 'unsafe_path'
    # Each component must be spelled as its directory entry: on a case-insensitive file system a case variant would
    # otherwise open (and pin under another name) the real file.
    current = corpus_root
    for part in PurePosixPath(file_path).parts:
        try:
            names = os.listdir(current)
        except OSError:
            return 'missing'
        if part not in names:
            return 'unsafe_path' if part.casefold() in {name.casefold() for name in names} else 'missing'
        current = current / part
    if not path.is_file():
        return 'missing'
    raw = path.read_bytes()
    if len(raw) > contracts.MAX_SOURCE_BYTES:
        return 'document_too_large'
    try:
        decoded = raw.decode('utf-8')
    except UnicodeDecodeError:
        return 'invalid_utf8'
    text = decoded.replace('\r\n', '\n').replace('\r', '\n')
    segments = ingest._segments(text, limit=SPAN_CHARS)
    if not segments:
        return 'empty_document'
    if len(segments) > ingest.LIMITS['max_spans_per_source']:
        return 'document_too_large'
    digest = hashlib.sha256(raw).hexdigest()
    sid = ingest.source_id('evidence', digest)
    spans = [{'span_id': f'{sid}#{n}', 'text': text[s:e], 'text_sha256': contracts.text_digest(text[s:e]),
              'locator': {'kind': 'text', 'paragraph': n, 'start': s, 'end': e}} for n, (s, e, _) in enumerate(segments, 1)]
    record = {'source_id': sid, 'role': 'evidence', 'version': '1', 'kind': 'document', 'original_sha256': digest, 'original_bytes': len(raw),
              'media_type': 'text/plain', 'parent_source_id': None,
              'parse': {'status': 'ok', 'confidence': 1.0, 'missing_pages': [], 'ocr_required_pages': [], 'reason_codes': []},
              'source_set': 'candidate', 'excluded_matters': [], 'spans': spans}
    return {'raw': raw, 'decoded': decoded, 'text': text, 'map': _newline_map(decoded), 'record': record, 'sha256': digest}


def _snippets(test):
    """(query, [(file_path, start, end, answer)]) of an upstream test, or None when it does not have the assumed shape."""
    if not isinstance(test, dict) or not isinstance(test.get('snippets'), list) or not test['snippets']:
        return None
    snippets = []
    for snippet in test['snippets']:
        if not isinstance(snippet, dict) or not isinstance(snippet.get('file_path'), str) or not isinstance(snippet.get('answer'), str):
            return None
        span = snippet.get('span')
        if not isinstance(span, list) or len(span) != 2 or any(type(x) is not int for x in span):
            return None
        snippets.append((snippet['file_path'], span[0], span[1], snippet['answer']))
    return test.get('query'), snippets


def _legalbench_rag(source_dir, request):
    """Converted examples of the `legalbench-rag` layout: corpus/<component>/*.txt and benchmarks/<component>.json."""
    component = request['component']
    bench_relative = f'benchmarks/{component}.json'
    try:
        benchmark, bench_sha256 = contracts.read_json_strict(source_dir / 'benchmarks' / f'{component}.json')
    except OSError:
        raise ValueError('Benchmark file is missing: ' + bench_relative) from None
    if not isinstance(benchmark, dict) or not isinstance(benchmark.get('tests'), list):
        raise ValueError('Malformed benchmark file: ' + bench_relative)
    tests = benchmark['tests'][:request['limit']] if request['limit'] else benchmark['tests']
    corpus_root = (source_dir / 'corpus').resolve()
    documents, imported, rejected, missing = {}, [], [], []
    for index, test in enumerate(tests):
        upstream_id = f'{component}:{index}'
        parsed = _snippets(test)
        if parsed is None:
            rejected.append({'upstream_id': upstream_id, 'reason_code': 'malformed_example'})
            continue
        query, snippets = parsed
        if not isinstance(query, str) or not query.strip():
            rejected.append({'upstream_id': upstream_id, 'reason_code': 'empty_query'})
            continue
        if len(query) > contracts.MAX_TEXT:
            rejected.append({'upstream_id': upstream_id, 'reason_code': 'query_too_long'})
            continue
        for file_path, *_ in snippets:
            if file_path not in documents:
                documents[file_path] = _document(corpus_root, file_path)
        absent = [fp for fp, *_ in snippets if documents[fp] == 'missing']
        if absent:
            missing.append({'upstream_id': upstream_id, 'file_path': absent[0]})
            continue
        problem = next((documents[fp] for fp, *_ in snippets if isinstance(documents[fp], str)), None)
        if problem is None and any(not 0 <= start < end <= len(documents[fp]['decoded']) for fp, start, end, _ in snippets):
            problem = 'span_out_of_range'
        if problem is None and any(len(answer) > contracts.MAX_TEXT for *_, answer in snippets):
            problem = 'label_too_long'
        gold = []
        if problem is None:
            for fp, start, end, _ in snippets:
                doc = documents[fp]
                low, high = doc['map'](start), doc['map'](end)
                gold += [s['span_id'] for s in doc['record']['spans']
                         if s['locator']['start'] < high and low < s['locator']['end'] and s['span_id'] not in gold]
            if not gold:
                problem = 'no_overlapping_span'
        if problem is not None:
            rejected.append({'upstream_id': upstream_id, 'reason_code': problem})
            continue
        imported.append({'index': index, 'upstream_id': upstream_id, 'query': query, 'snippets': snippets, 'gold': gold})
    return benchmark, bench_sha256, tests, documents, imported, rejected, missing


def _repository_output(output, root):
    root = Path(root or ingest.ROOT).resolve()
    if output.is_relative_to(root) and not output.is_relative_to(root / 'configs' / 'local'):
        raise ValueError('Dataset imports must stay outside the repository tree')


def import_dataset(request_path, output_dir, root=None, nonce=None):
    """Convert operator-supplied upstream bytes into a `public-benchmark` suite under `output_dir`. Only the `bytes` gate can
    become verified here; every other gate is written blocked. Returns a summary report."""
    request_path = Path(request_path).resolve()
    request, _ = contracts.read_json_strict(request_path)
    try:
        _request(request)
    except (TypeError, AttributeError, KeyError):
        raise ValueError('Malformed import request') from None
    adapter = ADAPTERS.get(request['adapter'])
    if adapter is None:
        raise ValueError('Unknown dataset adapter: ' + request['adapter'])
    if not adapter['available']:
        raise ValueError(f"Adapter {request['adapter']} is gated: {adapter['reason']}")
    output = Path(output_dir).resolve()
    _repository_output(output, root)
    nonce = secrets.token_hex(16) if nonce is None else nonce
    if not isinstance(nonce, str) or not re.fullmatch(r'[0-9a-f]{32}', nonce):
        raise ValueError('nonce must be 32 lowercase hex characters')
    source_dir = (request_path.parent / request['source_dir']).resolve()
    component, jurisdiction, upstream = request['component'], request['jurisdiction'], request['upstream']
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError('The import output directory must be new or empty')
    benchmark, bench_sha256, tests, documents, imported, rejected, missing = _legalbench_rag(source_dir, request)

    used, matters, entries = {}, [], []
    for example in imported:
        for fp, *_ in example['snippets']:
            used.setdefault(fp, documents[fp])
        key = component + '\0' + str(example['index']) + '\0' + example['query']
        first = example['snippets'][0][0]
        matter_id = 'q-' + hashlib.sha256(key.encode('utf-8')).hexdigest()[:12]
        # Salted: the first snippet's file is the gold retrieval target, so an unsalted hash would name the answer document.
        family_id = 'd-' + hashlib.sha256((nonce + '\0' + first).encode('utf-8')).hexdigest()[:12]
        matters.append({'matter_id': matter_id, 'family_id': family_id, 'operative_date': upstream['source_date'], 'venue': 'unspecified',
                        'posture': 'retrieval', 'question': example['query'], 'output_schema': contracts.POSTURES['retrieval'], 'sources': []})
        entries.append({'matter_id': matter_id, 'scenario': component, 'variant': 'base', 'upstream_id': example['upstream_id'],
                        'upstream_labels': {'answers': [s[3] for s in example['snippets']],
                                            'ranges': [f'{fp}:{start}-{end}' for fp, start, end, _ in example['snippets']]},
                        'gold_spans': example['gold']})
    order = sorted(range(len(matters)), key=lambda i: matters[i]['matter_id'])
    shared, seen = [], set()
    for fp in sorted(used):
        record = used[fp]['record']
        for span in record['spans']:      # each span is exactly the slice of its file at its locator
            if used[fp]['text'][span['locator']['start']:span['locator']['end']] != span['text']:
                raise ValueError('Imported span does not match its file: ' + span['span_id'])
        if record['source_id'] not in seen:      # byte-identical files are one source
            seen.add(record['source_id'])
            shared.append(record)
    head = {'schema_version': 1, 'data_class': 'public-benchmark', 'jurisdiction_profile': jurisdiction}
    manifests = {
        'matters.json': {**head, 'source_set': 'candidate', 'matters': [matters[i] for i in order], 'shared_sources': shared},
        'corpus.json': {**head, 'source_set': 'candidate', 'venues': ['unspecified'], 'authorities': []},
        'rubric.json': {**head, 'source_set': 'grader', 'rubric_version': f"{request['adapter']}-{ADAPTER_VERSION}", 'import_nonce': nonce,
                        'matters': [entries[i] for i in order]},
    }
    if not shared:
        del manifests['matters.json']['shared_sources']
    data = {name: ingest._dump(value) for name, value in manifests.items()}
    for name, payload in data.items():
        if len(payload) > contracts.MAX_SOURCE_BYTES:
            raise ValueError('Generated manifest exceeds the per-file limit: ' + name)

    bench_file = source_dir / 'benchmarks' / f'{component}.json'
    files = [{'path': f'benchmarks/{component}.json', 'size': bench_file.stat().st_size, 'sha256': bench_sha256}]
    files += [{'path': 'corpus/' + fp, 'size': len(doc['raw']), 'sha256': doc['sha256']} for fp, doc in sorted(used.items())]
    files.sort(key=lambda f: f['path'])
    expected = {item['path']: item['sha256'] for item in request['expected_files']}

    def matches(relative, digest):
        try:
            path = contracts._inside(source_dir, relative)
            return path.is_file() and sha256_file(path) == digest
        except ValueError:
            return False
    bytes_verified = all(matches(p, d) for p, d in expected.items()) and all(expected.get(f['path']) == f['sha256'] for f in files)
    blocked = {'status': 'blocked', 'evidence': None, 'verified_by': None, 'verified_utc': None}
    gates = {name: dict(blocked) for name in GATES}
    if bytes_verified:
        gates['bytes'] = {'status': 'verified', 'evidence': 'expected-digests', 'verified_by': 'import-tool',
                          'verified_utc': datetime.datetime.now(datetime.timezone.utc).strftime(UTC)}
    dataset_id = f"{request['adapter']}-{component}-{request['split']}".replace('_', '-')
    dataset = {'schema_version': 1, 'dataset_id': dataset_id, 'adapter': request['adapter'], 'adapter_version': ADAPTER_VERSION,
               'upstream': upstream, 'license': request['license'], 'jurisdiction': jurisdiction, 'split': request['split'],
               'protocol': {'reduced': request['limit'] is not None or request['split'] == 'mini',
                            'adaptations': sorted(['no-operative-date', 'no-venue', 'paragraph-chunking-1000'] +
                                                  ([f"limit-{request['limit']}"] if request['limit'] is not None else []))},
               'files': files, 'derived': [{'path': name, 'sha256': hashlib.sha256(data[name]).hexdigest()} for name in sorted(data)],
               'gates': gates,
               'examples': {'total': len(tests), 'upstream_total': len(benchmark['tests']), 'imported': len(imported),
                            'rejected': rejected, 'missing': missing},
               'parity': {'scorer': None, 'sample': [], 'max_abs_difference': None, 'status': 'not_run'}}
    validate_dataset(dataset)

    # Written into a sibling staging directory and moved into place only when the finished suite verifies: a failed
    # import leaves nothing behind.
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = output.parent / f'.{output.name}.staging-{secrets.token_hex(4)}'
    staging.mkdir()
    try:
        copies = []
        for fp, doc in sorted(used.items()):      # byte for byte: these copies are what anchors every imported source
            target = contracts._inside(staging / 'originals', fp)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(doc['raw'])
            copies.append('originals/' + fp)
        for name, payload in data.items():
            (staging / name).write_bytes(payload)
        _write(staging / 'dataset.lock.json', dataset)
        lock = contracts.make_lock(staging, benchmark_id='legal-' + dataset_id, revision=upstream['revision'], split_id=request['split'],
                                   data_class='public-benchmark', jurisdiction_profile=jurisdiction,
                                   manifests={'matters': 'matters.json', 'corpus': 'corpus.json', 'rubric': 'rubric.json',
                                              'dataset_lock': 'dataset.lock.json'}, sources=copies)
        _write(staging / 'suite.lock.json', lock)
        problems = ingest.verify_anchors(contracts._load_suite(staging / 'suite.lock.json', gates=False))
        if problems:
            raise ValueError('Imported suite anchors do not verify: ' + '; '.join(problems[:10]))
        try:
            if output.exists():
                output.rmdir()
            staging.rename(output)
        except OSError:      # the output directory appeared, or was filled, after it was checked
            raise ValueError('The import output directory appeared during the import: ' + str(output)) from None
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    lock_path = output / 'suite.lock.json'
    return {'dataset_id': dataset_id, 'suite_lock': str(lock_path), 'examples': dataset['examples'],
            'gates': {name: gates[name]['status'] for name in GATES}, 'blocked': blocked_gates(dataset)}


def _merged(items):
    """{file_path: merged [start, end) intervals} of a list of {file_path, span: [start, end]}."""
    if not isinstance(items, list):
        raise ValueError('Ranges must be a list')
    per = {}
    for item in items:
        fields(item, ['file_path', 'span'], ['file_path', 'span'])
        span = item['span']
        if not isinstance(item['file_path'], str) or not isinstance(span, (list, tuple)) or len(span) != 2 or \
                any(type(x) is not int for x in span) or not 0 <= span[0] <= span[1]:
            raise ValueError('A range needs a file_path and a span [start, end]')
        per.setdefault(item['file_path'], []).append(tuple(span))
    merged = {}
    for path, intervals in per.items():
        out = []
        for start, end in sorted(intervals):
            if out and start <= out[-1][1]:
                out[-1][1] = max(out[-1][1], end)
            else:
                out.append([start, end])
        merged[path] = out
    return merged


def span_scores(retrieved, gold):
    """Character precision and recall of retrieved ranges against gold ranges (overlapping ranges count once). A value is
    None when its denominator is zero."""
    r, g = _merged(retrieved), _merged(gold)
    overlap = sum(max(0, min(a[1], b[1]) - max(a[0], b[0])) for path in r for a in r[path] for b in g.get(path, []))
    size_r = sum(e - s for spans in r.values() for s, e in spans)
    size_g = sum(e - s for spans in g.values() for s, e in spans)
    return {'precision': overlap / size_r if size_r else None, 'recall': overlap / size_g if size_g else None}


def _ranges(labels):
    gold = []
    for value in labels['ranges']:
        path, _, span = value.rpartition(':')
        start, _, end = span.partition('-')
        gold.append({'file_path': path, 'span': [int(start), int(end)]})
    return gold


def parity_check(dataset_lock_path, native_path):
    """Recompute span scores for the examples a native (upstream) scorer run reports, against the imported gold ranges, and
    record the comparison in the dataset lock. It does not set the gate."""
    path = Path(dataset_lock_path).resolve()
    lock = _read(path)
    derived = {d['path']: d['sha256'] for d in lock['derived']}
    rubric, digest = contracts.read_json_strict(path.parent / 'rubric.json')
    if derived.get('rubric.json') != digest:
        raise ValueError('The rubric differs from the imported manifest: rubric.json')
    gold = {g['upstream_id']: _ranges(g['upstream_labels']) for g in rubric['matters'] if 'upstream_id' in g}
    native, _ = contracts.read_json_strict(native_path)
    fields(native, ['scorer', 'examples'], ['scorer', 'examples'])
    _token(native['scorer'], 'native scorer')
    if not isinstance(native['examples'], list):
        raise ValueError('The native run needs a list of examples')
    sample, differences, mismatch, seen = [], [], False, set()
    for example in native['examples']:
        fields(example, ['upstream_id', 'retrieved', 'precision', 'recall'], ['upstream_id', 'retrieved', 'precision', 'recall'])
        upstream_id = example['upstream_id']
        if upstream_id not in gold or upstream_id in seen:
            raise ValueError('Native example is not in the import or is repeated: ' + str(upstream_id))
        seen.add(upstream_id)
        local = span_scores(example['retrieved'], gold[upstream_id])
        row = {'upstream_id': upstream_id, 'local_precision': local['precision'], 'local_recall': local['recall'],
               'native_precision': example['precision'] if _number(example['precision']) else None,
               'native_recall': example['recall'] if _number(example['recall']) else None, 'difference': None,
               'precision_denominator_empty': local['precision'] is None, 'recall_denominator_empty': local['recall'] is None}
        compared = []
        for metric in ('precision', 'recall'):      # a metric with an empty local denominator is not compared; the other is
            if local[metric] is None:
                continue
            native_value = example[metric]
            if isinstance(native_value, bool) or not _number(native_value):      # nothing to compare: no row can record it
                raise ValueError(f'Native example has no {metric} to compare: ' + upstream_id)
            compared.append(abs(local[metric] - native_value))
        if compared:
            row['difference'] = max(compared)
            differences.append(row['difference'])
            mismatch |= row['difference'] > PARITY_TOLERANCE
        sample.append(row)
    parity = {'scorer': native['scorer'], 'sample': sample, 'max_abs_difference': max(differences) if differences else None,
              'status': 'match' if differences and not mismatch else 'mismatch'}
    lock['parity'] = parity
    _write(path, validate_dataset(lock, rubric=rubric))
    return parity


def set_gate(dataset_lock_path, gate, *, evidence, verified_by, verified_utc):
    """Mark one operator gate verified. The suite lock must be rewritten afterwards, so the gate state is pinned."""
    path = Path(dataset_lock_path).resolve()
    lock = _read(path)
    if gate not in GATES:
        raise ValueError('Unknown dataset gate: ' + str(gate))
    if gate == 'bytes':
        raise ValueError('The bytes gate is set by the import')
    parity = lock['parity']
    if gate == 'grader_parity' and not (parity['status'] == 'match' and parity['scorer'] and parity['sample']):
        raise ValueError('Grader parity needs a matching parity run')
    lock['gates'][gate] = {'status': 'verified', 'evidence': evidence, 'verified_by': verified_by, 'verified_utc': verified_utc}
    _write(path, validate_dataset(lock))


def _relock(directory):
    """Rewrite suite.lock.json of an imported suite after its dataset lock changed (same header, same files)."""
    lock_path = Path(directory) / 'suite.lock.json'
    if not lock_path.is_file():
        return None
    old, _ = contracts.read_json_strict(lock_path)
    manifests = {e['purpose']: e['path'] for e in old['source_files'] if e['purpose'] != contracts.SOURCE_PURPOSE}
    sources = [e['path'] for e in old['source_files'] if e['purpose'] == contracts.SOURCE_PURPOSE]
    new = contracts.make_lock(directory, benchmark_id=old['benchmark_id'], revision=old['revision'], split_id=old['split_id'],
                              data_class=old['data_class'], jurisdiction_profile=old['jurisdiction_profile'], manifests=manifests, sources=sources)
    _write(lock_path, new)
    return lock_path


def main(argv=None):
    parser = argparse.ArgumentParser(prog='python -m llm_eval.experiments.legal_benchmark.benchmarks',
                                     description='Gated public-benchmark import on local bytes (nothing is downloaded).')
    commands = parser.add_subparsers(dest='command', required=True)
    run = commands.add_parser('import', help='convert an operator-supplied upstream copy')
    run.add_argument('--request', required=True)
    run.add_argument('--output', required=True)
    parity = commands.add_parser('parity', help='compare with offline native scorer output')
    parity.add_argument('--dataset-lock', required=True)
    parity.add_argument('--native', required=True)
    gate = commands.add_parser('gate', help='record an operator verification')
    gate.add_argument('--dataset-lock', required=True)
    gate.add_argument('--gate', required=True)
    gate.add_argument('--evidence', required=True)
    gate.add_argument('--verified-by', required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == 'import':
            result = import_dataset(args.request, args.output)
        elif args.command == 'parity':
            result = parity_check(args.dataset_lock, args.native)
            result = {'status': result['status'], 'max_abs_difference': result['max_abs_difference'],
                      'relocked': str(_relock(Path(args.dataset_lock).resolve().parent))}
        else:
            set_gate(args.dataset_lock, args.gate, evidence=args.evidence, verified_by=args.verified_by,
                     verified_utc=datetime.datetime.now(datetime.timezone.utc).strftime(UTC))
            result = {'gate': args.gate, 'status': 'verified', 'relocked': str(_relock(Path(args.dataset_lock).resolve().parent)),
                      'blocked': blocked_gates(verify_dataset(args.dataset_lock))}
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
