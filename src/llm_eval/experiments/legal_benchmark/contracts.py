"""Shared contracts of the legal benchmark: suite lock v1, matter and authority manifests, candidate output v1.

Everything here reads, validates and hashes local files only. Nothing is written, fetched or executed, so the
planner can call it freely. Documents are untrusted content: they are data to quote and anchor, never instructions.
"""
from __future__ import annotations

import datetime
import hashlib
from pathlib import Path, PurePosixPath

from llm_eval.common import read_json, sha256_file
from llm_eval.core.contracts import fields, identifier

LOCK_VERSION = 1
OUTPUT_VERSION = 1
DATA_CLASSES = ('public-synthetic', 'public-benchmark', 'private-matter')
EXECUTION_KINDS = ('fixture', 'model-run', 'score-only')
PURPOSES = ('matters', 'corpus', 'rubric')
SOURCE_ROLES = ('evidence', 'authority', 'prior_brief', 'template')
AUTHORITY_STATUSES = ('in_force', 'superseded', 'repealed', 'unknown')
RECOMMENDATIONS = ('charge', 'decline', 'defer')
ELEMENT_STATUSES = ('supported', 'contradicted', 'negated', 'missing')
CLAIM_STATUSES = ('supported', 'qualified', 'insufficient')
MAX_SOURCE_BYTES = 8 * 1024 * 1024


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


def _inside(root, relative):
    """Resolve a lock-relative POSIX path; reject absolute paths, traversal and links that leave the lock directory."""
    if not isinstance(relative, str) or not relative or '\\' in relative:
        raise ValueError('Suite paths must be relative POSIX paths')
    pure = PurePosixPath(relative)
    if pure.is_absolute() or '..' in pure.parts or ':' in pure.parts[0]:
        raise ValueError('Suite path escapes the lock directory: ' + relative)
    path = (root / Path(*pure.parts)).resolve()
    if not path.is_relative_to(root):
        raise ValueError('Suite path escapes the lock directory: ' + relative)
    return path


def make_lock(directory, *, benchmark_id, revision, split_id, data_class, jurisdiction_profile, manifests):
    """Lock contents for the files of `directory`; `manifests` maps each purpose to a relative path."""
    directory = Path(directory).resolve()
    if set(manifests) != set(PURPOSES):
        raise ValueError('A suite needs exactly these manifests: ' + ', '.join(PURPOSES))
    files = []
    for purpose in PURPOSES:
        path = _inside(directory, manifests[purpose])
        files.append({'path': manifests[purpose], 'size': path.stat().st_size, 'sha256': sha256_file(path), 'purpose': purpose})
    return {'schema_version': LOCK_VERSION, 'benchmark_id': benchmark_id, 'revision': revision, 'split_id': split_id,
            'data_class': data_class, 'jurisdiction_profile': jurisdiction_profile, 'matter_manifest': manifests['matters'],
            'corpus_manifest': manifests['corpus'], 'rubric_manifest': manifests['rubric'], 'source_files': files}


def lock_files(lock_path):
    """(lock, {purpose: verified absolute path}). Raises when the lock is malformed, unsafe or stale."""
    lock_path = Path(lock_path).resolve()
    root = lock_path.parent
    lock = read_json(lock_path)
    names = ['schema_version', 'benchmark_id', 'revision', 'split_id', 'data_class', 'jurisdiction_profile',
             'matter_manifest', 'corpus_manifest', 'rubric_manifest', 'source_files']
    fields(lock, names, names)
    if lock['schema_version'] != LOCK_VERSION:
        raise ValueError('Suite lock schema_version must be 1')
    for key in ('benchmark_id', 'split_id', 'jurisdiction_profile'):
        identifier(lock[key])
    if not isinstance(lock['revision'], str) or not lock['revision']:
        raise ValueError('Suite lock needs a revision')
    if lock['data_class'] not in DATA_CLASSES:
        raise ValueError('Unknown suite data_class')
    if not isinstance(lock['source_files'], list) or not lock['source_files']:
        raise ValueError('Suite lock lists no source files')
    paths = {}
    for entry in lock['source_files']:
        fields(entry, ['path', 'size', 'sha256', 'purpose'], ['path', 'size', 'sha256', 'purpose'])
        if entry['purpose'] not in PURPOSES:
            raise ValueError('Unknown suite file purpose: ' + str(entry['purpose']))
        if entry['purpose'] in paths:
            raise ValueError('Duplicate suite file purpose: ' + entry['purpose'])
        path = _inside(root, entry['path'])
        if path in paths.values():
            raise ValueError('Duplicate suite file path: ' + entry['path'])
        if not path.is_file():
            raise ValueError('Suite file is missing: ' + entry['path'])
        size = path.stat().st_size
        if type(entry['size']) is not int or size > MAX_SOURCE_BYTES:
            raise ValueError('Suite file size is invalid or above the limit: ' + entry['path'])
        if size != entry['size'] or sha256_file(path) != entry['sha256']:
            raise ValueError('Suite lock is stale: ' + entry['path'] + ' changed after it was locked')
        paths[entry['purpose']] = path
    if set(paths) != set(PURPOSES):
        raise ValueError('Suite lock must list matters, corpus and rubric files')
    for purpose, key in (('matters', 'matter_manifest'), ('corpus', 'corpus_manifest'), ('rubric', 'rubric_manifest')):
        if _inside(root, lock[key]) != paths[purpose]:
            raise ValueError(key + ' does not match the locked ' + purpose + ' file')
    return lock, paths


def validate_corpus(corpus, lock):
    fields(corpus, ['schema_version', 'data_class', 'jurisdiction_profile', 'source_set', 'venues', 'authorities'],
           ['schema_version', 'data_class', 'jurisdiction_profile', 'source_set', 'venues', 'authorities'])
    if corpus['source_set'] != 'candidate':
        raise ValueError('The corpus manifest must be the candidate source set')
    venues = _unique(_strings(corpus['venues'], 'venues'), 'venue')
    keys = set()
    for a in corpus['authorities']:
        names = ['authority_id', 'version', 'citation', 'title', 'issuer', 'authority_type', 'relates_to', 'venues', 'effective_from',
                 'effective_to', 'status', 'pinpoint', 'text', 'text_sha256', 'elements']
        fields(a, names, [n for n in names if n != 'relates_to'])
        identifier(a['authority_id']); identifier(a['version'])
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
        if text_digest(a['text']) != a['text_sha256']:
            raise ValueError('Authority text does not match its digest: ' + a['authority_id'] + '@' + a['version'])
        _unique([e.get('element_id') for e in a['elements']], 'element in ' + a['authority_id'])
        if not a['elements']:
            raise ValueError('An authority needs at least one element')
        for e in a['elements']:
            fields(e, ['element_id', 'description', 'terms', 'negating_terms'], ['element_id', 'description', 'terms'])
            identifier(e['element_id']); _strings(e['terms'], 'terms'); _strings(e.get('negating_terms', []), 'negating_terms', True)
    for a in corpus['authorities']:
        if a['authority_type'] == 'exemption' and a.get('relates_to') not in {k[0] for k in keys}:
            raise ValueError('An exemption must relate to a known authority')
    return keys


def validate_matters(matters, lock):
    fields(matters, ['schema_version', 'data_class', 'jurisdiction_profile', 'source_set', 'matters'],
           ['schema_version', 'data_class', 'jurisdiction_profile', 'source_set', 'matters'])
    if matters['source_set'] != 'candidate':
        raise ValueError('The matter manifest must be the candidate source set')
    ids, spans, sources = set(), {}, set()
    for m in matters['matters']:
        names = ['matter_id', 'family_id', 'operative_date', 'venue', 'posture', 'question', 'output_schema', 'sources']
        fields(m, names, names)
        identifier(m['matter_id']); identifier(m['family_id']); iso_date(m['operative_date'], 'operative_date')
        if m['matter_id'] in ids:
            raise ValueError('Duplicate matter: ' + m['matter_id'])
        ids.add(m['matter_id'])
        if m['posture'] != 'screening' or m['output_schema'] != 'candidate-output-v1':
            raise ValueError('Unsupported posture or output schema')
        if not m['sources']:
            raise ValueError('A matter needs at least one source')
        spans[m['matter_id']] = set()
        for s in m['sources']:
            fields(s, ['source_id', 'role', 'version', 'kind', 'spans'], ['source_id', 'role', 'version', 'kind', 'spans'])
            identifier(s['source_id'])
            if s['source_id'] in sources:
                raise ValueError('Duplicate source: ' + s['source_id'])
            sources.add(s['source_id'])
            if s['role'] not in SOURCE_ROLES:
                raise ValueError('Unknown source role')
            if not s['spans']:
                raise ValueError('A source needs at least one span')
            for span in s['spans']:
                fields(span, ['span_id', 'text', 'text_sha256'], ['span_id', 'text', 'text_sha256'])
                if not isinstance(span['span_id'], str) or not span['span_id'].startswith(s['source_id'] + '#'):
                    raise ValueError('A span anchor must start with its source id')
                if span['span_id'] in spans[m['matter_id']]:
                    raise ValueError('Duplicate span: ' + span['span_id'])
                if not isinstance(span['text'], str) or text_digest(span['text']) != span['text_sha256']:
                    raise ValueError('Span text does not match its digest: ' + span['span_id'])
                spans[m['matter_id']].add(span['span_id'])
    return spans


def validate_rubric(rubric, spans, authority_keys, corpus):
    fields(rubric, ['schema_version', 'data_class', 'jurisdiction_profile', 'source_set', 'rubric_version', 'matters'],
           ['schema_version', 'data_class', 'jurisdiction_profile', 'source_set', 'rubric_version', 'matters'])
    if rubric['source_set'] != 'grader':
        raise ValueError('The rubric manifest must be the grader source set')
    elements = {(a['authority_id'], a['version']): {e['element_id'] for e in a['elements']} for a in corpus['authorities']}
    seen = set()
    for g in rubric['matters']:
        names = ['matter_id', 'scenario', 'recommendation', 'controlling_authority', 'ineligible_versions', 'elements',
                 'conflict_elements', 'missing_elements', 'established_exemptions', 'injection_span_ids']
        fields(g, names, names)
        if g['matter_id'] not in spans or g['matter_id'] in seen:
            raise ValueError('Rubric entry for an unknown or repeated matter: ' + str(g['matter_id']))
        seen.add(g['matter_id'])
        identifier(g['scenario'])
        if g['recommendation'] not in RECOMMENDATIONS:
            raise ValueError('Unknown gold recommendation')
        cited = [tuple(v) for v in g['ineligible_versions']] + [tuple(v) for v in g['established_exemptions']]
        if g['controlling_authority'] is not None:
            cited.append(tuple(g['controlling_authority']))
            if set(g['elements']) != elements.get(tuple(g['controlling_authority']), set()):
                raise ValueError('Gold elements do not match the controlling authority: ' + g['matter_id'])
        elif g['elements']:
            raise ValueError('Gold elements need a controlling authority: ' + g['matter_id'])
        if set(cited) - authority_keys:
            raise ValueError('Rubric cites an unknown authority version: ' + g['matter_id'])
        if set(g['elements'].values()) - set(ELEMENT_STATUSES):
            raise ValueError('Unknown gold element status')
        if set(g['injection_span_ids']) - spans[g['matter_id']]:
            raise ValueError('Rubric names an unknown span: ' + g['matter_id'])
    if seen != set(spans):
        raise ValueError('Every matter needs exactly one rubric entry')


def load_suite(lock_path):
    """Fully verified suite: lock, digest of the lock (which pins every dependency) and the three manifests."""
    lock, paths = lock_files(lock_path)
    corpus, matters, rubric = read_json(paths['corpus']), read_json(paths['matters']), read_json(paths['rubric'])
    for name, manifest in (('corpus', corpus), ('matters', matters), ('rubric', rubric)):
        if not isinstance(manifest, dict) or manifest.get('schema_version') != 1:
            raise ValueError('Unsupported ' + name + ' manifest version')
        if manifest.get('data_class') != lock['data_class']:
            raise ValueError('Conflicting data classification between the lock and the ' + name + ' manifest')
        if manifest.get('jurisdiction_profile') != lock['jurisdiction_profile']:
            raise ValueError('Conflicting jurisdiction profile between the lock and the ' + name + ' manifest')
    keys = validate_corpus(corpus, lock)
    spans = validate_matters(matters, lock)
    venues = set(corpus['venues'])
    for m in matters['matters']:
        if m['venue'] not in venues:
            raise ValueError('Matter names an undeclared venue: ' + m['matter_id'])
    validate_rubric(rubric, spans, keys, corpus)
    return {'lock': lock, 'lock_sha256': sha256_file(lock_path), 'paths': paths, 'corpus': corpus, 'matters': matters, 'rubric': rubric}


def validate_output(output, matter, corpus):
    """Candidate output v1 for one matter. Every anchor and citation must resolve; a human review is always required."""
    names = ['schema_version', 'matter_id', 'recommendation', 'issues', 'elements', 'claims', 'material_conflicts',
             'adverse_authorities', 'missing_information', 'verification_flags', 'review_required']
    fields(output, names, names)
    if output['schema_version'] != OUTPUT_VERSION or output['matter_id'] != matter['matter_id']:
        raise ValueError('Output version or matter mismatch')
    if output['recommendation'] not in RECOMMENDATIONS:
        raise ValueError('Unknown recommendation')
    if output['review_required'] is not True:
        raise ValueError('review_required must be true')
    spans = {span['span_id'] for s in matter['sources'] for span in s['spans']}
    versions = {(a['authority_id'], a['version']): a for a in corpus['authorities']}

    def anchors(ids):
        if not isinstance(ids, list) or set(ids) - spans:
            raise ValueError('Output cites an evidence span that is not in the matter')

    def citation(item):
        authority = versions.get((item.get('authority_id'), item.get('version')))
        if authority is None or item.get('pinpoint') != authority['pinpoint']:
            raise ValueError('Output cites an authority version or pinpoint that is not in the corpus')

    for issue in output['issues']:
        fields(issue, ['issue_id', 'question', 'authority_id', 'version'], ['issue_id', 'question'])
    for element in output['elements']:
        fields(element, ['element_id', 'status', 'evidence_span_ids', 'adverse_span_ids'],
               ['element_id', 'status', 'evidence_span_ids', 'adverse_span_ids'])
        if element['status'] not in ELEMENT_STATUSES:
            raise ValueError('Unknown element status')
        anchors(element['evidence_span_ids']); anchors(element['adverse_span_ids'])
    for claim in output['claims']:
        fields(claim, ['claim_id', 'proposition', 'authority_id', 'version', 'pinpoint', 'status', 'reason_codes'],
               ['claim_id', 'proposition', 'authority_id', 'version', 'pinpoint', 'status', 'reason_codes'])
        if claim['status'] not in CLAIM_STATUSES:
            raise ValueError('Unknown claim status')
        citation(claim)
    for conflict in output['material_conflicts']:
        fields(conflict, ['element_id', 'span_ids'], ['element_id', 'span_ids'])
        anchors(conflict['span_ids'])
    for adverse in output['adverse_authorities']:
        fields(adverse, ['authority_id', 'version', 'pinpoint', 'status', 'evidence_span_ids'],
               ['authority_id', 'version', 'pinpoint', 'status', 'evidence_span_ids'])
        citation(adverse); anchors(adverse['evidence_span_ids'])
    for missing in output['missing_information']:
        fields(missing, ['element_id', 'needed'], ['element_id', 'needed'])
    for flag in output['verification_flags']:
        fields(flag, ['code', 'span_id'], ['code'])
        identifier(flag['code'].replace('_', '-'))
        if 'span_id' in flag:
            anchors([flag['span_id']])
    return output
