"""Shared contracts of the legal benchmark: suite lock v1, matter and authority manifests, candidate output v1.

Everything here reads, validates and hashes local files only. Nothing is written, fetched or executed, so the
planner can call it freely. Documents are untrusted content: they are data to quote and anchor, never instructions.
"""
from __future__ import annotations

import datetime
import hashlib
import json
from pathlib import Path, PurePosixPath
import re

from llm_eval.common import sha256_file
from llm_eval.core.contracts import fields, identifier

LOCK_VERSION = 1
OUTPUT_VERSION = 1
DATA_CLASSES = ('public-synthetic', 'public-benchmark', 'private-matter')
EXECUTION_KINDS = ('fixture', 'model-run', 'score-only')
PURPOSES = ('matters', 'corpus', 'rubric')
OPTIONAL_PURPOSES = ('collection', 'visibility', 'oracle', 'review', 'dataset_lock')      # at most one file each
SOURCE_PURPOSE = 'source'                                              # original bytes of ingested files
MAX_SOURCE_FILES = 2000
MAX_SUITE_BYTES = 256 * 1024 * 1024
POSTURES = {'screening': 'candidate-output-v1', 'retrieval': 'retrieval-result-v1'}
PARSE_STATUSES = ('ok', 'partial', 'unsupported', 'encrypted', 'corrupt')
LOCATOR_KINDS = ('text', 'email-body', 'pdf-page', 'docx-paragraph')
SOURCE_ROLES = ('evidence', 'authority', 'prior_brief', 'template')
# `invalidated`: a treatment (for example overruled) that makes an authority unusable whatever the date.
AUTHORITY_STATUSES = ('in_force', 'superseded', 'repealed', 'unknown', 'invalidated')
RECOMMENDATIONS = ('charge', 'decline', 'defer')
ELEMENT_STATUSES = ('supported', 'contradicted', 'negated', 'missing')
CLAIM_STATUSES = ('supported', 'qualified', 'insufficient')
SOURCE_SETS = ('candidate', 'oracle', 'grader', 'review')
ADVERSE_STATUSES = ('established', 'not_established')
VARIANTS = ('base', 'paired')
FLAG_CODES = ('untrusted_instruction_in_source', 'insufficient_authority', 'insufficient_evidence', 'authority_validity_unknown')
INSUFFICIENCY_FLAGS = FLAG_CODES[1:]
REFERENCE_ERRORS = ('fabricated_citation', 'unknown_version', 'pinpoint_mismatch', 'unknown_span')
# The only suite keys candidate-side code may receive: no rubric, no paths, no key a later package adds.
CANDIDATE_KEYS = ('lock', 'lock_sha256', 'corpus', 'matters')
MAX_SOURCE_BYTES = 8 * 1024 * 1024
MAX_ITEMS = 64             # entries per list of a candidate output
MAX_TEXT = 2000            # characters per free-text string
MAX_OUTPUT_BYTES = 262144  # serialized candidate output
# File names the generic report builder exports from an attempt directory at any depth (reporting/experiment.py).
RESERVED_REPORT_NAMES = frozenset({'requests.jsonl', 'telemetry.json', 'load-telemetry.json', 'replay-outcomes.json', 'job.json',
                                   'result.json', 'metadata.json', 'host.json', 'routing-metadata.json', 'livebench-run.json'})
REVISION = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]{0,63}')
REASON_CODE = re.compile(r'[a-z0-9][a-z0-9_.-]{0,63}')


def text_digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def iso_date(value, name):
    if not isinstance(value, str):
        raise ValueError(name + ' must be an ISO date')
    try:
        return datetime.date.fromisoformat(value)
    except ValueError:
        raise ValueError(name + ' must be an ISO date') from None


def _unique(values, what):
    seen = set()
    for value in values:
        if value in seen:
            raise ValueError(f'Duplicate {what}: {value}')
        seen.add(value)
    return seen


def _strings(value, name, allow_empty=False):
    if not isinstance(value, list) or any(not isinstance(x, str) or not x for x in value) or (not value and not allow_empty):
        raise ValueError(name + ' must be a list of nonempty strings')
    return value


def _text(value, name, limit=MAX_TEXT):
    if not isinstance(value, str) or not value or len(value) > limit:
        raise ValueError(f'{name} must be a nonempty string of at most {limit} characters')
    return value


def _version(value, message):
    if type(value) is not int or value != 1:
        raise ValueError(message)


def read_json_strict(path):
    """(object, sha256): the bytes are read once, and the digest is the digest of exactly the bytes parsed."""
    data = Path(path).read_bytes()

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('Duplicate JSON key: ' + key)
            result[key] = value
        return result
    try:
        value = json.loads(data.decode('utf-8'), object_pairs_hook=pairs)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ValueError('Invalid JSON: ' + Path(path).name) from None
    return value, hashlib.sha256(data).hexdigest()


MAX_PATH_CHARS = 1000
MAX_PATH_PART_CHARS = 255


def _relative(relative):
    """The one validator of a suite-relative path (lock entries, collected files, dataset files, upstream paths): a
    normalised relative POSIX path without traversal, drive, alternate data stream (`:` in any component) or empty and
    dot components, within the length limits. Returns it unchanged."""
    if not isinstance(relative, str) or not relative or '\\' in relative:
        raise ValueError('Suite paths must be relative POSIX paths')
    pure = PurePosixPath(relative)
    if not pure.parts or pure.is_absolute() or '..' in pure.parts or ':' in pure.parts[0]:
        raise ValueError('Suite path escapes the lock directory: ' + relative)
    if pure.as_posix() != relative or any(':' in part for part in pure.parts):
        raise ValueError('Suite paths must be normalised relative POSIX paths without streams: ' + relative)
    if len(relative) > MAX_PATH_CHARS or any(len(part) > MAX_PATH_PART_CHARS for part in pure.parts):
        raise ValueError('Suite path is too long: ' + relative[:100])
    return relative


def _inside(root, relative):
    """Resolve a lock-relative POSIX path; reject absolute paths, traversal and links that leave the lock directory."""
    pure = PurePosixPath(_relative(relative))
    path = (root / Path(*pure.parts)).resolve()
    if not path.is_relative_to(root):
        raise ValueError('Suite path escapes the lock directory: ' + relative)
    return path


def make_lock(directory, *, benchmark_id, revision, split_id, data_class, jurisdiction_profile, manifests, sources=()):
    """Lock contents for the files of `directory`; `manifests` maps each purpose to a relative path. `sources` are
    lock-relative POSIX paths of original files, each locked with purpose `source`, in sorted order."""
    directory = Path(directory).resolve()
    if set(PURPOSES) - set(manifests) or set(manifests) - set(PURPOSES) - set(OPTIONAL_PURPOSES):
        raise ValueError('A suite needs exactly these manifests: ' + ', '.join(PURPOSES) + ' (optional: ' + ', '.join(OPTIONAL_PURPOSES) + ')')
    files = []
    named = [(purpose, manifests[purpose]) for purpose in PURPOSES + OPTIONAL_PURPOSES if purpose in manifests]
    for purpose, relative in named + [(SOURCE_PURPOSE, relative) for relative in sorted(set(sources))]:
        path = _inside(directory, relative)
        files.append({'path': relative, 'size': path.stat().st_size, 'sha256': sha256_file(path), 'purpose': purpose})
    return {'schema_version': LOCK_VERSION, 'benchmark_id': benchmark_id, 'revision': revision, 'split_id': split_id,
            'data_class': data_class, 'jurisdiction_profile': jurisdiction_profile, 'matter_manifest': manifests['matters'],
            'corpus_manifest': manifests['corpus'], 'rubric_manifest': manifests['rubric'], 'source_files': files}


def _verify_lock(lock_path):
    """(lock, {single purpose: verified absolute path}, SHA-256 of the lock bytes that were parsed, every verified path in
    lock order). Raises when the lock is malformed, unsafe or stale."""
    lock_path = Path(lock_path).resolve()
    root = lock_path.parent
    lock, digest = read_json_strict(lock_path)
    names = ['schema_version', 'benchmark_id', 'revision', 'split_id', 'data_class', 'jurisdiction_profile',
             'matter_manifest', 'corpus_manifest', 'rubric_manifest', 'source_files']
    fields(lock, names, names)
    if type(lock['schema_version']) is not int or lock['schema_version'] != LOCK_VERSION:
        raise ValueError('Suite lock schema_version must be 1')
    for key in ('benchmark_id', 'split_id', 'jurisdiction_profile'):
        identifier(lock[key])
    if not isinstance(lock['revision'], str) or not REVISION.fullmatch(lock['revision']):
        raise ValueError('Suite lock needs a revision')
    if lock['data_class'] not in DATA_CLASSES:
        raise ValueError('Unknown suite data_class')
    if not isinstance(lock['source_files'], list) or not lock['source_files']:
        raise ValueError('Suite lock lists no source files')
    single, sources, total = [], 0, 0
    for entry in lock['source_files']:      # shape and counts first: nothing is hashed for a lock that breaks a limit
        fields(entry, ['path', 'size', 'sha256', 'purpose'], ['path', 'size', 'sha256', 'purpose'])
        if not isinstance(entry['purpose'], str) or entry['purpose'] not in PURPOSES + OPTIONAL_PURPOSES + (SOURCE_PURPOSE,):
            raise ValueError('Unknown suite file purpose: ' + str(entry['purpose']))
        if entry['purpose'] == SOURCE_PURPOSE:
            sources += 1
        elif entry['purpose'] in single:
            raise ValueError('Duplicate suite file purpose: ' + entry['purpose'])
        else:
            single.append(entry['purpose'])
        if type(entry['size']) is not int or entry['size'] < 0:      # a negative size would lower the total checked below
            raise ValueError('Suite file size is invalid or above the limit: ' + str(entry['path']))
        total += entry['size']
    if sources > MAX_SOURCE_FILES:
        raise ValueError(f'Suite lock lists more than {MAX_SOURCE_FILES} source files')
    if total > MAX_SUITE_BYTES:
        raise ValueError(f'Suite files exceed {MAX_SUITE_BYTES} bytes in total')
    paths, ordered = {}, []
    for entry in lock['source_files']:
        path = _inside(root, entry['path'])
        if path in ordered:
            raise ValueError('Duplicate suite file path: ' + entry['path'])
        if not path.is_file():
            raise ValueError('Suite file is missing: ' + entry['path'])
        size = path.stat().st_size
        if type(entry['size']) is not int or size > MAX_SOURCE_BYTES:
            raise ValueError('Suite file size is invalid or above the limit: ' + entry['path'])
        if size != entry['size'] or sha256_file(path) != entry['sha256']:
            raise ValueError('Suite lock is stale: ' + entry['path'] + ' changed after it was locked')
        ordered.append(path)
        if entry['purpose'] != SOURCE_PURPOSE:
            paths[entry['purpose']] = path
    if set(PURPOSES) - set(paths):
        raise ValueError('Suite lock must list matters, corpus and rubric files')
    for purpose, key in (('matters', 'matter_manifest'), ('corpus', 'corpus_manifest'), ('rubric', 'rubric_manifest')):
        if _inside(root, lock[key]) != paths[purpose]:
            raise ValueError(key + ' does not match the locked ' + purpose + ' file')
    if ('collection' in paths) != ('visibility' in paths):
        raise ValueError('Suite needs both a collection and a visibility manifest')
    if ('oracle' in paths or 'review' in paths) and 'collection' not in paths:
        raise ValueError('An oracle or review manifest needs a collection manifest')
    if sources and 'collection' not in paths and 'dataset_lock' not in paths:
        raise ValueError('Source files need a collection or a dataset lock')
    if lock['data_class'] == 'public-benchmark' and 'dataset_lock' not in paths:
        raise ValueError('A public-benchmark suite needs a dataset lock')
    if 'dataset_lock' in paths and lock['data_class'] != 'public-benchmark':
        raise ValueError('A dataset lock belongs to a public-benchmark suite')
    return lock, paths, digest, ordered


def _read_lock(lock_path):
    """(lock, {purpose: verified absolute path} in lock order, SHA-256 of the lock bytes that were parsed).
    Original files (purpose `source`) are verified too but are not in the purpose map. Raises when the lock is
    malformed, unsafe or stale."""
    return _verify_lock(lock_path)[:3]


def lock_files(lock_path):
    """(lock, {purpose: verified absolute path}). Raises when the lock is malformed, unsafe or stale."""
    lock, paths, _ = _read_lock(lock_path)
    return lock, paths


def pinned_files(lock_path):
    """Every verified file the lock lists, originals included, in lock order."""
    return _verify_lock(lock_path)[3]


# Optional keys that package B writes and package C interprets. Here they are type-checked only and have no meaning.
OPTIONAL_CORPUS_KEYS = ('policy', 'availability_cutoff')
OPTIONAL_AUTHORITY_KEYS = ('original_sha256', 'jurisdiction', 'court', 'weight', 'aliases', 'snapshot', 'review', 'status_as_of')


def _optional_authority_keys(a):
    if 'original_sha256' in a and not (isinstance(a['original_sha256'], str) and re.fullmatch(r'[0-9a-f]{64}', a['original_sha256'])):
        raise ValueError('original_sha256 must be 64 lowercase hex characters')
    if 'jurisdiction' in a:
        identifier(a['jurisdiction'])
    if a.get('court') is not None:
        identifier(a['court'])
    if 'weight' in a and a['weight'] not in ('controlling', 'persuasive'):
        raise ValueError('Authority weight must be controlling or persuasive')
    if 'aliases' in a:
        _unique(_strings(a['aliases'], 'aliases', True), 'alias')
        for alias in a['aliases']:
            _text(alias, 'An alias')
    for key in ('snapshot', 'review'):
        if a.get(key) is not None and not isinstance(a[key], dict):
            raise ValueError(key + ' must be an object or null')
    if a.get('status_as_of') is not None:
        iso_date(a['status_as_of'], 'status_as_of')


def validate_corpus(corpus, lock):
    names = ['schema_version', 'data_class', 'jurisdiction_profile', 'source_set', 'venues', 'authorities']
    fields(corpus, names + list(OPTIONAL_CORPUS_KEYS), names)
    _version(corpus['schema_version'], 'Unsupported corpus manifest version')
    if corpus['source_set'] != SOURCE_SETS[0]:
        raise ValueError('The corpus manifest must be the candidate source set')
    if 'policy' in corpus and not isinstance(corpus['policy'], dict):
        raise ValueError('The corpus policy must be an object')
    if 'availability_cutoff' in corpus:
        iso_date(corpus['availability_cutoff'], 'availability_cutoff')
    venues = _unique(_strings(corpus['venues'], 'venues'), 'venue')
    if not isinstance(corpus['authorities'], list):
        raise ValueError('authorities must be a list')
    keys = set()
    for a in corpus['authorities']:
        names = ['authority_id', 'version', 'citation', 'title', 'issuer', 'authority_type', 'relates_to', 'venues', 'effective_from',
                 'effective_to', 'status', 'pinpoint', 'text', 'text_sha256', 'elements']
        fields(a, names + list(OPTIONAL_AUTHORITY_KEYS), [n for n in names if n != 'relates_to'])
        identifier(a['authority_id']); identifier(a['version'])
        for key in ('citation', 'title', 'issuer'):
            _text(a[key], 'Authority ' + key)
        _text(a['pinpoint'], 'Authority pinpoint', 100)      # the output cites a pinpoint as an identifier of at most 100 characters
        _optional_authority_keys(a)
        if (a['authority_id'], a['version']) in keys:
            raise ValueError('Duplicate authority version: ' + a['authority_id'] + '@' + a['version'])
        keys.add((a['authority_id'], a['version']))
        if a['authority_type'] not in ('offence', 'exemption'):
            raise ValueError('Unknown authority_type')
        if a['status'] not in AUTHORITY_STATUSES:
            raise ValueError('Unknown authority status')
        if set(_strings(a['venues'], 'authority venues')) - venues:
            raise ValueError('Authority names an undeclared venue')
        start = iso_date(a['effective_from'], 'effective_from')
        if a['effective_to'] is not None and iso_date(a['effective_to'], 'effective_to') <= start:
            raise ValueError('effective_to must be after effective_from')
        if not isinstance(a['text'], str) or text_digest(a['text']) != a['text_sha256']:
            raise ValueError('Authority text does not match its digest: ' + a['authority_id'] + '@' + a['version'])
        if not isinstance(a['elements'], list) or not a['elements']:
            raise ValueError('An authority needs at least one element')
        for e in a['elements']:
            fields(e, ['element_id', 'description', 'terms', 'negating_terms'], ['element_id', 'description', 'terms'])
            identifier(e['element_id']); _strings(e['terms'], 'terms'); _strings(e.get('negating_terms', []), 'negating_terms', True)
            _text(e['description'], 'Element description')
        _unique([e['element_id'] for e in a['elements']], 'element in ' + a['authority_id'])
    for a in corpus['authorities']:
        if a['authority_type'] == 'exemption' and a.get('relates_to') not in {k[0] for k in keys}:
            raise ValueError('An exemption must relate to a known authority')
    return keys


SOURCE_KEYS = ('source_id', 'role', 'version', 'kind', 'spans')
OPTIONAL_SOURCE_KEYS = ('original_sha256', 'original_bytes', 'media_type', 'parent_source_id', 'attachments', 'email', 'parse',
                        'source_set', 'excluded_matters')
SPAN_KEYS = ('span_id', 'text', 'text_sha256')
OPTIONAL_SPAN_KEYS = ('locator', 'quoted', 'revision', 'comments')
SHA256 = re.compile(r'[0-9a-f]{64}')
MEDIA_TYPE = re.compile(r'[a-z0-9][a-z0-9.+-]{0,63}/[a-z0-9][a-z0-9.+-]{0,99}')


def _count(value, name, low=0):
    if type(value) is not int or value < low:
        raise ValueError(f'{name} must be an integer of at least {low}')
    return value


def _locator(locator):
    if not isinstance(locator, dict) or locator.get('kind') not in LOCATOR_KINDS:
        raise ValueError('Unknown span locator kind')
    keys = {'text': ['paragraph', 'start', 'end'], 'email-body': ['part', 'start', 'end'], 'pdf-page': ['page', 'bbox'],
            'docx-paragraph': ['section', 'paragraph']}[locator['kind']]
    fields(locator, ['kind'] + keys, ['kind'] + keys)
    if 'start' in keys and _count(locator['end'], 'Locator end') < _count(locator['start'], 'Locator start'):
        raise ValueError('Locator end must not precede its start')
    if locator['kind'] == 'text':
        _count(locator['paragraph'], 'Locator paragraph', 1)
    elif locator['kind'] == 'email-body':
        if not isinstance(locator['part'], str) or not re.fullmatch(r'subject|[1-9][0-9]{0,5}', locator['part']):
            raise ValueError("Locator part must be 'subject' or a part number")
    elif locator['kind'] == 'pdf-page':
        _count(locator['page'], 'Locator page', 1)
        box = locator['bbox']
        if box is not None and (not isinstance(box, list) or len(box) != 4 or
                                any(type(x) not in (int, float) or x != x or x in (float('inf'), float('-inf')) for x in box)):
            raise ValueError('Locator bbox must be four numbers or null')
    else:
        _count(locator['section'], 'Locator section'); _count(locator['paragraph'], 'Locator paragraph')


def _optional_source_keys(s):
    if 'original_sha256' in s and not (isinstance(s['original_sha256'], str) and SHA256.fullmatch(s['original_sha256'])):
        raise ValueError('original_sha256 must be 64 lowercase hex characters')
    if 'original_bytes' in s:
        _count(s['original_bytes'], 'original_bytes')
    if 'media_type' in s and not (isinstance(s['media_type'], str) and MEDIA_TYPE.fullmatch(s['media_type'])):
        raise ValueError('media_type must be a lowercase media type')
    if s.get('parent_source_id') is not None:
        identifier(s['parent_source_id'])
    if 'attachments' in s:
        if not isinstance(s['attachments'], list):
            raise ValueError('attachments must be a list of source ids')
        _unique([identifier(a) for a in s['attachments']], 'attachment')
    if 'email' in s:
        email = fields(s['email'], ['message_id', 'thread_id', 'sender_role', 'date'], ['message_id', 'thread_id', 'sender_role', 'date'])
        if email['message_id'] is not None:
            _text(email['message_id'], 'message_id')
        if email['thread_id'] is not None:
            identifier(email['thread_id'])
        identifier(email['sender_role'])
        if email['date'] is not None:
            try:
                zoned = isinstance(email['date'], str) and datetime.datetime.fromisoformat(email['date']).tzinfo is not None
            except ValueError:
                zoned = False
            if not zoned:
                raise ValueError('An email date must be ISO 8601 with an offset, or null')
    if 'parse' in s:
        parse = fields(s['parse'], ['status', 'confidence', 'missing_pages', 'ocr_required_pages', 'reason_codes'],
                       ['status', 'confidence', 'missing_pages', 'ocr_required_pages', 'reason_codes'])
        if parse['status'] not in PARSE_STATUSES:
            raise ValueError('Unknown parse status')
        if parse['confidence'] is not None and (type(parse['confidence']) not in (int, float) or not 0 <= parse['confidence'] <= 1):
            raise ValueError('Parse confidence must be a number from 0 to 1, or null')
        for key in ('missing_pages', 'ocr_required_pages'):
            if not isinstance(parse[key], list):
                raise ValueError(key + ' must be a list of page numbers')
            _unique([_count(page, key, 1) for page in parse[key]], 'page in ' + key)
        codes = parse['reason_codes']
        if not isinstance(codes, list) or any(not isinstance(c, str) or not REASON_CODE.fullmatch(c) for c in codes):
            raise ValueError('Parse reason_codes must be a list of reason codes')
    if 'source_set' in s and s['source_set'] not in SOURCE_SETS:
        raise ValueError('Unknown source set: ' + str(s['source_set']))
    if 'excluded_matters' in s:
        excluded = s['excluded_matters']
        if not isinstance(excluded, list) or [identifier(m) for m in excluded] != sorted(set(excluded)):
            raise ValueError('excluded_matters must be a sorted list of distinct matter ids')


def _source(s, spans, sources, extra=()):
    """One source record: required and optional keys. Adds its span ids to `spans` and its id to `sources`."""
    fields(s, list(SOURCE_KEYS) + list(OPTIONAL_SOURCE_KEYS) + list(extra), SOURCE_KEYS)
    identifier(s['source_id'])
    if s['source_id'] in sources:
        raise ValueError('Duplicate source: ' + s['source_id'])
    sources.add(s['source_id'])
    if s['role'] not in SOURCE_ROLES:
        raise ValueError('Unknown source role')
    _text(s['version'], 'A source version'); _text(s['kind'], 'A source kind')
    _optional_source_keys(s)
    if not isinstance(s['spans'], list) or not s['spans']:
        raise ValueError('A source needs at least one span')
    for span in s['spans']:
        fields(span, list(SPAN_KEYS) + list(OPTIONAL_SPAN_KEYS), SPAN_KEYS)
        if not isinstance(span['span_id'], str) or not span['span_id'].startswith(s['source_id'] + '#'):
            raise ValueError('A span anchor must start with its source id')
        if span['span_id'] in spans:
            raise ValueError('Duplicate span: ' + span['span_id'])
        if not isinstance(span['text'], str) or text_digest(span['text']) != span['text_sha256']:
            raise ValueError('Span text does not match its digest: ' + span['span_id'])
        if 'locator' in span:
            _locator(span['locator'])
        if 'quoted' in span and not isinstance(span['quoted'], bool):
            raise ValueError('quoted must be true or false')
        if 'revision' in span and span['revision'] not in ('inserted', 'deleted'):
            raise ValueError('A span revision must be inserted or deleted')
        if 'comments' in span:
            if not isinstance(span['comments'], list):
                raise ValueError('comments must be a list of strings')
            for comment in span['comments']:
                _text(comment, 'A comment')
        spans.add(span['span_id'])


def validate_matters(matters, lock):
    fields(matters, ['schema_version', 'data_class', 'jurisdiction_profile', 'source_set', 'matters', 'shared_sources'],
           ['schema_version', 'data_class', 'jurisdiction_profile', 'source_set', 'matters'])
    _version(matters['schema_version'], 'Unsupported matters manifest version')
    if matters['source_set'] != SOURCE_SETS[0]:
        raise ValueError('The matter manifest must be the candidate source set')
    if not isinstance(matters['matters'], list):
        raise ValueError('matters must be a list')
    ids, spans, sources, records = set(), {}, set(), []
    for m in matters['matters']:
        names = ['matter_id', 'family_id', 'operative_date', 'venue', 'posture', 'question', 'output_schema', 'sources']
        fields(m, names, names)
        identifier(m['matter_id']); identifier(m['family_id']); iso_date(m['operative_date'], 'operative_date')
        if m['matter_id'] in ids:
            raise ValueError('Duplicate matter: ' + m['matter_id'])
        ids.add(m['matter_id'])
        if not isinstance(m['posture'], str) or m['posture'] not in POSTURES or m['output_schema'] != POSTURES[m['posture']]:
            raise ValueError('Unsupported posture or output schema')
        _text(m['question'], 'A matter question')
        if not isinstance(m['sources'], list) or (not m['sources'] and m['posture'] != 'retrieval'):
            raise ValueError('A matter needs at least one source')
        spans[m['matter_id']] = set()
        for s in m['sources']:
            _source(s, spans[m['matter_id']], sources)
            records.append(s)
    shared = matters.get('shared_sources', [])
    if not isinstance(shared, list):
        raise ValueError('shared_sources must be a list')
    shared_spans = set()
    for s in shared:
        _source(s, shared_spans, sources)
        records.append(s)
    for s in records:      # one manifest per source set: a candidate file never holds a source of another set
        if s.get('source_set', SOURCE_SETS[0]) != SOURCE_SETS[0]:
            raise ValueError('The matter manifest holds candidate sources only: ' + s['source_id'])
        if set(s.get('excluded_matters', [])) - ids:
            raise ValueError('excluded_matters names an unknown matter: ' + s['source_id'])
    return spans


def _pair(value, what):
    if not isinstance(value, list) or len(value) != 2 or not all(isinstance(x, str) for x in value):
        raise ValueError(what + ' must be an [authority_id, version] pair')
    return tuple(value)


def _key(pair):
    return pair[0] + '@' + pair[1]


RETRIEVAL_ENTRY_KEYS = ('matter_id', 'scenario', 'variant', 'upstream_id', 'upstream_labels', 'gold_spans')


def _retrieval_entry(g, spans, shared):
    """Rubric entry of a `retrieval` matter: upstream id and labels (grader set only) and the gold span ids."""
    fields(g, RETRIEVAL_ENTRY_KEYS, RETRIEVAL_ENTRY_KEYS)
    identifier(g['scenario'])
    if g['variant'] not in VARIANTS:
        raise ValueError('Unknown gold variant: ' + g['matter_id'])
    _text(g['upstream_id'], 'upstream_id', 200)
    labels = g['upstream_labels']
    if not isinstance(labels, dict) or any(not isinstance(k, str) or not isinstance(v, list) or
                                           any(not isinstance(x, str) or len(x) > MAX_TEXT for x in v) for k, v in labels.items()):
        raise ValueError(f'upstream_labels must be an object of string lists of at most {MAX_TEXT} characters each: ' + g['matter_id'])
    gold = _strings(g['gold_spans'], 'gold_spans')
    _unique(gold, 'gold span')
    if set(gold) - spans[g['matter_id']] - shared:
        raise ValueError('Rubric names an unknown span: ' + g['matter_id'])


def validate_rubric(rubric, spans, authority_keys, corpus, *, roles, shared=frozenset(), retrieval=frozenset()):
    """`roles` maps each matter id to {span_id: source role} in document order (the order of `matters.json`).
    `shared`: span ids of `shared_sources`; `retrieval`: ids of the matters with posture `retrieval`."""
    fields(rubric, ['schema_version', 'data_class', 'jurisdiction_profile', 'source_set', 'rubric_version', 'matters', 'import_nonce'],
           ['schema_version', 'data_class', 'jurisdiction_profile', 'source_set', 'rubric_version', 'matters'])
    _version(rubric['schema_version'], 'Unsupported rubric manifest version')
    if rubric['source_set'] != SOURCE_SETS[2]:
        raise ValueError('The rubric manifest must be the grader source set')
    _text(rubric['rubric_version'], 'rubric_version')
    if 'import_nonce' in rubric and not (isinstance(rubric['import_nonce'], str) and re.fullmatch(r'[0-9a-f]{32}', rubric['import_nonce'])):
        raise ValueError('import_nonce must be 32 lowercase hex characters')
    if not isinstance(rubric['matters'], list):
        raise ValueError('The rubric needs a list of matters')
    elements = {(a['authority_id'], a['version']): {e['element_id'] for e in a['elements']} for a in corpus['authorities']}
    seen = set()
    for g in rubric['matters']:
        if isinstance(g, dict) and g.get('matter_id') in retrieval:
            if g['matter_id'] in seen:
                raise ValueError('Rubric entry for an unknown or repeated matter: ' + str(g['matter_id']))
            seen.add(g['matter_id'])
            _retrieval_entry(g, spans, shared)
            continue
        names = ['matter_id', 'scenario', 'variant', 'recommendation', 'controlling_authority', 'ineligible_versions', 'elements',
                 'conflict_elements', 'missing_elements', 'established_exemptions', 'injection_span_ids', 'evidence_spans',
                 'exemption_spans', 'reference_passages']
        fields(g, names, names)
        if not isinstance(g['matter_id'], str) or g['matter_id'] not in spans or g['matter_id'] in seen:
            raise ValueError('Rubric entry for an unknown or repeated matter: ' + str(g['matter_id']))
        seen.add(g['matter_id'])
        identifier(g['scenario'])
        if g['variant'] not in VARIANTS:
            raise ValueError('Unknown gold variant: ' + g['matter_id'])
        if g['recommendation'] not in RECOMMENDATIONS:
            raise ValueError('Unknown gold recommendation')
        if not isinstance(g['elements'], dict):
            raise ValueError('Gold elements must be an object: ' + g['matter_id'])
        exemptions = [_pair(v, 'An established exemption') for v in g['established_exemptions']]
        cited = [_pair(v, 'An ineligible version') for v in g['ineligible_versions']] + exemptions
        controlling = None
        if g['controlling_authority'] is not None:
            controlling = _pair(g['controlling_authority'], 'The controlling authority')
            cited.append(controlling)
            if set(g['elements']) != elements.get(controlling, set()):
                raise ValueError('Gold elements do not match the controlling authority: ' + g['matter_id'])
        elif g['elements']:
            raise ValueError('Gold elements need a controlling authority: ' + g['matter_id'])
        if set(cited) - authority_keys:
            raise ValueError('Rubric cites an unknown authority version: ' + g['matter_id'])
        if set(g['elements'].values()) - set(ELEMENT_STATUSES):
            raise ValueError('Unknown gold element status')
        for key, status in (('conflict_elements', 'contradicted'), ('missing_elements', 'missing')):
            if sorted(_strings(g[key], key, True)) != sorted(e for e, s in g['elements'].items() if s == status):
                raise ValueError(f'Gold {key} must be exactly the elements with status {status}: ' + g['matter_id'])
        order = roles[g['matter_id']]
        evidence = {span for span, role in order.items() if role == 'evidence'}
        if set(_strings(g['injection_span_ids'], 'injection_span_ids', True)) - spans[g['matter_id']]:
            raise ValueError('Rubric names an unknown span: ' + g['matter_id'])
        material = set(g['injection_span_ids'])

        def anchored(ids, what):
            if set(_strings(ids, what, True)) - evidence:
                raise ValueError('Rubric evidence spans must be evidence spans of the matter: ' + g['matter_id'])
            material.update(ids)
            return ids
        if not isinstance(g['evidence_spans'], dict) or set(g['evidence_spans']) != set(g['elements']):
            raise ValueError('Gold evidence_spans must name exactly the gold elements: ' + g['matter_id'])
        for element, status in g['elements'].items():
            polarity = fields(g['evidence_spans'][element], ['support', 'adverse'], ['support', 'adverse'])
            support, adverse = anchored(polarity['support'], 'support'), anchored(polarity['adverse'], 'adverse')
            if not {'supported': support and not adverse, 'negated': adverse, 'contradicted': support and adverse,
                    'missing': not support and not adverse}[status]:
                raise ValueError('Gold evidence spans do not match the element status: ' + g['matter_id'] + ' ' + element)
        if not isinstance(g['exemption_spans'], dict) or set(g['exemption_spans']) != {_key(e) for e in exemptions}:
            raise ValueError('Gold exemption_spans must name exactly the established exemptions: ' + g['matter_id'])
        for ids in g['exemption_spans'].values():
            if not anchored(ids, 'exemption spans'):
                raise ValueError('An established exemption needs evidence spans: ' + g['matter_id'])
        passages = fields(g['reference_passages'], ['evidence', 'authorities', 'adverse'], ['evidence', 'authorities', 'adverse'])
        _strings(passages['adverse'], 'reference adverse authorities', True)
        if passages['evidence'] != [span for span in order if span in material]:
            raise ValueError('Reference evidence must be the gold-material and injection spans in document order: ' + g['matter_id'])
        if passages['authorities'] != ([_key(controlling)] if controlling else []):
            raise ValueError('Reference authorities must be the controlling authority: ' + g['matter_id'])
    if seen != set(spans):
        raise ValueError('Every matter needs exactly one rubric entry')


def load_suite(lock_path):
    """Fully verified suite: lock, digest of the lock (which pins every dependency), the three manifests and the optional
    collection, visibility, oracle, review and dataset manifests. Each JSON file is parsed from the bytes whose digest
    equals its lock entry; original files are verified by digest and listed in `originals`."""
    return _load_suite(lock_path)


def _load_suite(lock_path, *, gates=True):
    """`gates=False` is for the import tool only: it checks a suite it has just written, before an operator verified it."""
    lock, paths, lock_sha256 = _read_lock(lock_path)
    manifests, file_sha256 = {}, {}
    for entry in lock['source_files']:
        if entry['purpose'] == SOURCE_PURPOSE:
            continue
        value, digest = read_json_strict(paths[entry['purpose']])
        if digest != entry['sha256']:
            raise ValueError('Suite lock is stale: ' + entry['path'] + ' changed after it was locked')
        manifests[entry['purpose']] = value
        file_sha256[PurePosixPath(entry['path']).as_posix()] = digest
    dataset = None
    if 'dataset_lock' in manifests:
        from . import benchmarks
        try:
            dataset = benchmarks.validate_dataset(manifests['dataset_lock'], rubric=manifests['rubric'])
        except (TypeError, AttributeError, KeyError, IndexError):
            raise ValueError('Malformed suite manifest: dataset_lock') from None
        if gates:      # before anything else: an edited and relocked import must name the gate it reopened
            entries = {e['path']: e['sha256'] for e in lock['source_files'] if e['purpose'] in PURPOSES + (SOURCE_PURPOSE,)}
            blocked = benchmarks.blocked_gates(dataset, entries)
            if blocked:
                raise ValueError('Dataset import gate is blocked: ' + ', '.join(blocked))
    corpus, matters, rubric = manifests['corpus'], manifests['matters'], manifests['rubric']
    for name in ('corpus', 'matters', 'rubric', 'collection', 'oracle', 'review'):
        if name in manifests:
            _classified(manifests[name], lock, name)

    def checked(purpose, check):
        try:
            return check()
        except (TypeError, AttributeError, KeyError, IndexError):
            raise ValueError('Malformed suite manifest: ' + purpose) from None

    def venues():
        for m in matters['matters']:
            if m['venue'] not in set(corpus['venues']):
                raise ValueError('Matter names an undeclared venue: ' + m['matter_id'])
        return {m['matter_id']: {span['span_id']: s['role'] for s in m['sources'] for span in s['spans']} for m in matters['matters']}
    keys = checked('corpus', lambda: validate_corpus(corpus, lock))
    spans = checked('matters', lambda: validate_matters(matters, lock))
    roles = checked('matters', venues)
    shared = checked('matters', lambda: {span['span_id'] for s in matters.get('shared_sources', []) for span in s['spans']})
    retrieval = {m['matter_id'] for m in matters['matters'] if m['posture'] == 'retrieval'}
    checked('rubric', lambda: validate_rubric(rubric, spans, keys, corpus, roles=roles, shared=shared, retrieval=retrieval))
    root = Path(lock_path).resolve().parent
    suite = {'lock': lock, 'lock_sha256': lock_sha256, 'file_sha256': file_sha256, 'paths': paths, 'corpus': corpus,
             'matters': matters, 'rubric': rubric, 'collection': manifests.get('collection'), 'visibility': manifests.get('visibility'),
             'oracle': manifests.get('oracle'), 'review': manifests.get('review'), 'dataset': dataset,
             'originals': {e['sha256']: _inside(root, e['path']) for e in lock['source_files'] if e['purpose'] == SOURCE_PURPOSE}}
    checked('collection', lambda: _anchors(suite))
    if suite['collection'] is not None:      # the generated manifests must follow from the authored ones, also after a hand relock
        from . import ingest
        problems = checked('collection', lambda: ingest._generated_problems(suite))
        if problems:
            raise ValueError('Suite anchors do not verify: ' + '; '.join(problems[:10]))
    return suite


def _classified(manifest, lock, name):
    """A manifest that declares the lock's version, data class and jurisdiction profile."""
    if not isinstance(manifest, dict) or type(manifest.get('schema_version')) is not int or manifest['schema_version'] != 1:
        raise ValueError('Unsupported ' + name + ' manifest version')
    if manifest.get('data_class') != lock['data_class']:
        raise ValueError('Conflicting data classification between the lock and the ' + name + ' manifest')
    if manifest.get('jurisdiction_profile') != lock['jurisdiction_profile']:
        raise ValueError('Conflicting jurisdiction profile between the lock and the ' + name + ' manifest')


def _root_source(source, by_id):
    """The root of the `parent_source_id` chain of `source` among `by_id`, or None when the chain is broken or cyclic."""
    root, depth = source, 0
    while root.get('parent_source_id') is not None:
        depth += 1
        if root['parent_source_id'] not in by_id or depth > len(by_id):
            return None
        root = by_id[root['parent_source_id']]
    return root


def _anchors(suite):
    """Load-time cross-checks of anchored sources: originals pinned, parses complete, visibility as the operator declared it,
    every source in the manifest of its set, oracle and review sources tied to a matter of the suite or to none."""
    from . import ingest
    lock, matters = suite['lock'], suite['matters']
    matter_ids = {m['matter_id'] for m in matters['matters']}
    placed = [(SOURCE_SETS[0], s) for m in matters['matters'] for s in m['sources']]
    placed += [(SOURCE_SETS[0], s) for s in matters.get('shared_sources', [])]
    ids = {s['source_id'] for _, s in placed}
    for purpose in ('oracle', 'review'):
        manifest = suite[purpose]
        if manifest is None:
            continue
        names = ['schema_version', 'data_class', 'jurisdiction_profile', 'source_set', 'sources']
        fields(manifest, names, names)
        if manifest['source_set'] != purpose or not isinstance(manifest['sources'], list):
            raise ValueError(f'The {purpose} manifest must be the {purpose} source set')
        for s in manifest['sources']:
            _source(s, set(), ids, extra=('matter_id',))      # a source id is unique across all manifests
            if 'matter_id' not in s or (s['matter_id'] is not None and s['matter_id'] not in matter_ids):
                raise ValueError(f'A source of the {purpose} manifest must name a matter of the suite or null: ' + s['source_id'])
            if set(s.get('excluded_matters', [])) - matter_ids:
                raise ValueError('excluded_matters names an unknown matter: ' + s['source_id'])
            placed.append((purpose, s))
    pinned = {e['path']: e['sha256'] for e in lock['source_files'] if e['purpose'] == SOURCE_PURPOSE}
    rules = None
    if suite['collection'] is not None:
        collection = ingest.validate_collection(suite['collection'])
        visibility = ingest.validate_visibility(suite['visibility'], collection)
        rules = {}
        for f in collection['files']:
            if f['path'] not in pinned:
                raise ValueError('Unresolved anchor: original file is not pinned: ' + f['path'])
            if f['namespace'] != 'authority':      # the root source id of a collected file follows from its pinned bytes
                root_id = ingest.source_id(f['namespace'], pinned[f['path']], '', f.get('matter_id', ''))
                rules.setdefault(root_id, visibility[f['path']])
        for a in suite['corpus']['authorities']:
            if 'original_sha256' in a and a['original_sha256'] not in suite['originals']:
                raise ValueError('Unresolved anchor: original file is not pinned: ' + a['authority_id'] + '@' + a['version'])
    by_id = {s['source_id']: s for _, s in placed}
    for manifest_set, s in placed:
        stamped = (s.get('source_set', SOURCE_SETS[0]), s.get('excluded_matters', []))
        if 'original_sha256' not in s:
            # An inline span is its own anchor in a fixture suite; a release suite needs originals. private-matter suites
            # load (every mode refuses them with its own message) and are not checked by this rule.
            if lock['data_class'] == 'public-benchmark':
                raise ValueError('Unresolved anchor: inline source in a release suite: ' + s['source_id'])
        else:
            root = _root_source(s, by_id)
            if root is None:
                raise ValueError('Unresolved anchor: ' + s['source_id'])
            if root.get('original_sha256') not in suite['originals']:
                raise ValueError('Unresolved anchor: original file is not pinned: ' + s['source_id'])
            if s.get('parse', {}).get('status') != 'ok' or any('locator' not in span for span in s['spans']):
                raise ValueError('Unresolved anchor: ' + s['source_id'])
            if rules is not None and rules.get(root['source_id']) != stamped:
                raise ValueError('Source visibility differs from the visibility manifest: ' + s['source_id'])
        if stamped[0] != manifest_set:
            raise ValueError(f'The {manifest_set} manifest holds {manifest_set} sources only: ' + s['source_id'])
        if suite['dataset'] is not None and stamped[1]:      # an imported corpus is shared by every matter of the suite
            raise ValueError('An imported source excludes no matter: ' + s['source_id'])


def candidate_view(suite):
    """The only suite object candidate-side code may receive: lock, lock digest, corpus and matters. The lock in the view
    lists only the candidate files (matters and corpus): the size and digest of the rubric, of the oracle and review
    manifests and of every original are not candidate data. `lock_sha256` stays the digest of the full suite lock, not of
    the filtered `view['lock']`, so the view's lock must not be re-verified against it."""
    view = {key: suite[key] for key in CANDIDATE_KEYS}
    view['lock'] = {**suite['lock'], 'source_files': [f for f in suite['lock']['source_files'] if f['purpose'] in ('matters', 'corpus')]}
    return view


def _identifier(value, name):
    if not isinstance(value, str) or not 1 <= len(value) <= 100:
        raise ValueError(name + ' must be a string of 1 to 100 characters')
    return value


def _items(value, name):
    if not isinstance(value, list) or len(value) > MAX_ITEMS or any(not isinstance(item, dict) for item in value):
        raise ValueError(f'{name} must be a list of at most {MAX_ITEMS} objects')
    return value


def _span_ids(value, name):
    if not isinstance(value, list) or len(value) > MAX_ITEMS:
        raise ValueError(f'{name} must be a list of at most {MAX_ITEMS} span ids')
    for span_id in value:
        _identifier(span_id, name)
    return value


def validate_structure(output, matter):
    """Candidate output v1 without the corpus: keys, types, bounds, enumerations, uniqueness. Raises only ValueError."""
    try:
        return _structure(output, matter)
    except (TypeError, AttributeError, KeyError):
        raise ValueError('Malformed candidate output') from None


def _structure(output, matter):
    names = ['schema_version', 'matter_id', 'recommendation', 'issues', 'elements', 'claims', 'material_conflicts',
             'adverse_authorities', 'missing_information', 'verification_flags', 'review_required']
    fields(output, names, names)
    if len(json.dumps(output, sort_keys=True).encode()) > MAX_OUTPUT_BYTES:
        raise ValueError(f'Candidate output exceeds {MAX_OUTPUT_BYTES} bytes')
    if type(output['schema_version']) is not int or output['schema_version'] != OUTPUT_VERSION or output['matter_id'] != matter['matter_id']:
        raise ValueError('Output version or matter mismatch')
    if output['recommendation'] not in RECOMMENDATIONS:
        raise ValueError('Unknown recommendation')
    if output['review_required'] is not True:
        raise ValueError('review_required must be true')
    for name in names[3:10]:
        _items(output[name], name)
    for issue in output['issues']:
        fields(issue, ['issue_id', 'question', 'authority_id', 'version'], ['issue_id', 'question'])
        _identifier(issue['issue_id'], 'issue_id'); _text(issue['question'], 'question')
        if ('authority_id' in issue) != ('version' in issue):
            raise ValueError('An issue names authority_id and version together or neither')
        if 'authority_id' in issue:
            _identifier(issue['authority_id'], 'authority_id'); _identifier(issue['version'], 'version')
    elements = set()
    for element in output['elements']:
        fields(element, ['element_id', 'status', 'evidence_span_ids', 'adverse_span_ids'],
               ['element_id', 'status', 'evidence_span_ids', 'adverse_span_ids'])
        if _identifier(element['element_id'], 'element_id') in elements:
            raise ValueError('Duplicate element in output: ' + element['element_id'])
        elements.add(element['element_id'])
        if element['status'] not in ELEMENT_STATUSES:
            raise ValueError('Unknown element status')
        _span_ids(element['evidence_span_ids'], 'evidence_span_ids'); _span_ids(element['adverse_span_ids'], 'adverse_span_ids')
    claims = set()
    for claim in output['claims']:
        fields(claim, ['claim_id', 'proposition', 'authority_id', 'version', 'pinpoint', 'status', 'reason_codes'],
               ['claim_id', 'proposition', 'authority_id', 'version', 'pinpoint', 'status', 'reason_codes'])
        if _identifier(claim['claim_id'], 'claim_id') in claims:
            raise ValueError('Duplicate claim in output: ' + claim['claim_id'])
        claims.add(claim['claim_id'])
        _text(claim['proposition'], 'proposition')
        for key in ('authority_id', 'version', 'pinpoint'):
            _identifier(claim[key], key)
        if claim['status'] not in CLAIM_STATUSES:
            raise ValueError('Unknown claim status')
        codes = claim['reason_codes']
        if not isinstance(codes, list) or len(codes) > 16 or any(not isinstance(c, str) or not REASON_CODE.fullmatch(c) for c in codes):
            raise ValueError('reason_codes must be a list of at most 16 reason codes')
    for conflict in output['material_conflicts']:
        fields(conflict, ['element_id', 'span_ids'], ['element_id', 'span_ids'])
        _identifier(conflict['element_id'], 'element_id'); _span_ids(conflict['span_ids'], 'span_ids')
    adverse_keys = set()
    for adverse in output['adverse_authorities']:
        fields(adverse, ['authority_id', 'version', 'pinpoint', 'status', 'evidence_span_ids'],
               ['authority_id', 'version', 'pinpoint', 'status', 'evidence_span_ids'])
        for key in ('authority_id', 'version', 'pinpoint'):
            _identifier(adverse[key], key)
        if (adverse['authority_id'], adverse['version']) in adverse_keys:
            raise ValueError('Duplicate adverse authority in output: ' + adverse['authority_id'] + '@' + adverse['version'])
        adverse_keys.add((adverse['authority_id'], adverse['version']))
        if adverse['status'] not in ADVERSE_STATUSES:
            raise ValueError('Unknown adverse authority status')
        _span_ids(adverse['evidence_span_ids'], 'evidence_span_ids')
    for missing in output['missing_information']:
        fields(missing, ['element_id', 'needed'], ['element_id', 'needed'])
        _identifier(missing['element_id'], 'element_id'); _text(missing['needed'], 'needed')
    for flag in output['verification_flags']:
        fields(flag, ['code', 'span_id'], ['code'])
        if not isinstance(flag['code'], str) or flag['code'] not in FLAG_CODES:
            raise ValueError('Unknown verification flag code')
        if 'span_id' in flag:
            _identifier(flag['span_id'], 'span_id')
        elif flag['code'] == FLAG_CODES[0]:
            raise ValueError('An untrusted instruction flag needs a span_id')
    return output


def reference_errors(output, matter, corpus):
    """[{code, locator: {list, index}}] for every reference of a structurally valid output that does not resolve, in output
    order. Only spans of role `evidence` sources of the matter anchor a finding."""
    spans = {span['span_id'] for s in matter['sources'] if s['role'] == 'evidence' for span in s['spans']}
    versions = {(a['authority_id'], a['version']): a for a in corpus['authorities']}
    known = {a['authority_id'] for a in corpus['authorities']}
    errors = []

    def add(code, name, index):
        errors.append({'code': code, 'locator': {'list': name, 'index': index}})

    def citation(item, name, index):
        record = versions.get((item['authority_id'], item['version']))
        if item['authority_id'] not in known:
            add('fabricated_citation', name, index)
        elif record is None:
            add('unknown_version', name, index)
        elif 'pinpoint' in item and item['pinpoint'] != record['pinpoint']:
            add('pinpoint_mismatch', name, index)

    def anchors(ids, name, index):
        for span_id in ids:
            if span_id not in spans:
                add('unknown_span', name, index)

    for i, issue in enumerate(output['issues']):
        if 'authority_id' in issue:
            citation(issue, 'issues', i)
    for i, element in enumerate(output['elements']):
        anchors(element['evidence_span_ids'] + element['adverse_span_ids'], 'elements', i)
    for i, claim in enumerate(output['claims']):
        citation(claim, 'claims', i)
    for i, conflict in enumerate(output['material_conflicts']):
        anchors(conflict['span_ids'], 'material_conflicts', i)
    for i, adverse in enumerate(output['adverse_authorities']):
        citation(adverse, 'adverse_authorities', i)
        anchors(adverse['evidence_span_ids'], 'adverse_authorities', i)
    for i, flag in enumerate(output['verification_flags']):
        if 'span_id' in flag:
            anchors([flag['span_id']], 'verification_flags', i)
    return errors


def validate_references(output, matter, corpus):
    errors = reference_errors(output, matter, corpus)
    if errors and errors[0]['code'] == 'unknown_span':
        raise ValueError('Output cites an evidence span that is not in the matter')
    if errors:
        raise ValueError('Output cites an authority version or pinpoint that is not in the corpus')
    return output


def validate_output(output, matter, corpus):
    """Candidate output v1 for one matter. Every anchor and citation must resolve; a human review is always required."""
    return validate_references(validate_structure(output, matter), matter, corpus)


def private_file(output, relative):
    """Path of a private attempt file under `local/`, after creating its parent directories. The generic report builder
    exports files by name at any depth, so a private file never takes a name it scans."""
    if not isinstance(relative, str) or not relative or '\\' in relative or ':' in relative:
        raise ValueError('A private file needs a relative POSIX path')
    pure = PurePosixPath(relative)
    if not pure.parts or pure.is_absolute() or '..' in pure.parts:
        raise ValueError('A private file needs a relative POSIX path')
    if pure.name in RESERVED_REPORT_NAMES or (pure.suffix == '.jsonl' and 'model_judgment' in pure.parts) or \
            (pure.suffix == '.csv' and 'reports' in pure.parts):
        raise ValueError('Reserved report file name: ' + pure.name)
    path = Path(output) / 'local' / Path(*pure.parts)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path
