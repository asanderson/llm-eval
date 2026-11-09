"""Legal benchmark experiment: retrieval, evidence-grounded analysis and draft screening memos for human review.

Only the offline `smoke` mode is registered so far: a deterministic fixture pipeline over fictional matters with
no model, network or GPU. Later modes (retrieval, generation, workflow, score) are added as they are implemented.
"""
from __future__ import annotations

import json
from pathlib import Path
import time

from llm_eval.common import sha256_file
from llm_eval.core.contracts import atomic_json, fields, integer

from .contracts import load_suite, lock_files

MANIFEST = {'id': 'legal-benchmark', 'version': 1, 'modes': ['smoke'],
            'description': 'Legal retrieval, evidence-grounded analysis and draft screening memos for human review'}
BENCHMARK = 'legal-smoke'
# SHA-256 of experiments/legal-benchmark/workloads/original-smoke/suite.lock.json. The lock pins every suite file,
# so this one digest identifies the exact public-original suite that may enter generic report generation.
SMOKE_SUITE_SHA256 = '4764c1d4d8b3443827f535b621509bbf55d44724f2247121577d108b663938aa'
REPORTING_DISABLED = ('legal-benchmark reports are limited to the public-original smoke suite, and its results are not '
                      'published, until the legal report projection is implemented')


def validate(case, root, mode='smoke'):
    """Side-effect-free: reads and hashes the declared suite, nothing else."""
    if mode not in MANIFEST['modes']:
        raise ValueError('Unsupported legal-benchmark mode: ' + str(mode))
    fields(case, {'suite', 'synthetic', 'top_k'}, ['suite', 'synthetic'])
    integer(case.get('top_k', 3), 'top_k', high=50)
    suite = load_suite(case['suite'])
    # smoke runs the fixture pipeline: execution_kind `fixture`, the only kind that maps to legacy `synthetic: true`.
    if case['synthetic'] is not True:
        raise ValueError('The smoke mode is a fixture run and must declare synthetic: true')
    if suite['lock']['data_class'] != 'public-synthetic':
        raise ValueError('The smoke mode accepts public-synthetic suites only')
    return None


def input_files(parameters, root, mode):
    """Every file the suite lock pins, so planner, resume and worker all check the same bytes."""
    _, paths = lock_files(parameters['suite'])
    return [str(path) for path in paths.values()]


def setup_platforms(parameters, mode):
    """Serving platforms to install before a run. The fixture pipeline needs none."""
    return []


def _is_smoke_suite(job):
    suite = job.get('parameters', {}).get('suite')
    recorded = {f['path']: f['sha256'] for f in job.get('input_files', [])}
    return job.get('mode') == 'smoke' and job['parameters'].get('synthetic') is True and recorded.get(suite) == SMOKE_SUITE_SHA256


def reporting_policy(jobs):
    """What the generic reporting layer may do with these jobs. Decided from the planned inputs, never from a
    campaign's reporting settings or a report's own labels."""
    allowed = bool(jobs) and all(_is_smoke_suite(job) for job in jobs)
    return {'report': allowed, 'publish': False, 'reason': REPORTING_DISABLED}


def execute(job, output, root):
    from . import fixture
    parameters = job['parameters']
    validate(parameters, root, job['mode'])      # re-verifies every locked byte: a suite changed after planning fails here
    suite = load_suite(parameters['suite'])
    output = Path(output)
    if (output / 'requests.jsonl').exists():
        raise ValueError('This attempt already has request records')
    gold = {g['matter_id']: g for g in suite['rubric']['matters']}
    rows, drafts, details = [], [], []
    for matter in suite['matters']['matters']:
        started = time.perf_counter()
        candidate = fixture.draft(matter, suite['corpus'], parameters.get('top_k', 3))
        elapsed = time.perf_counter() - started
        criteria = fixture.score(candidate, matter, gold[matter['matter_id']], suite['corpus'])
        expected = gold[matter['matter_id']]['recommendation']
        rows.append({'task_id': matter['matter_id'], 'family_id': matter['family_id'], 'category': gold[matter['matter_id']]['scenario'],
                     'benchmark': BENCHMARK, 'status': 'ok', 'repetition': 1, 'warmup': False, 'synthetic': True,
                     'execution_kind': 'fixture', 'data_class': suite['lock']['data_class'], 'elapsed_s': elapsed,
                     'parse_status': 'valid' if criteria['schema_valid'] else 'invalid', 'review_status': 'pending_human_review',
                     'expected_choice': expected, 'choice': candidate['recommendation'], 'decision_correct': candidate['recommendation'] == expected,
                     'quality_check_applicable': True, 'quality_pass': all(criteria.values()),
                     'criteria_passed': sum(criteria.values()), 'criteria_total': len(criteria)})
        drafts.append(candidate)
        details.append({'matter_id': matter['matter_id'], 'criteria': criteria})
    # Candidate drafts and grader detail stay under local/, which the generic report builder does not read.
    (output / 'local').mkdir(parents=True, exist_ok=True)
    for name, items in (('requests.jsonl', rows), ('local/candidate-outputs.jsonl', drafts), ('local/score-detail.jsonl', details)):
        (output / name).write_text(''.join(json.dumps(item, sort_keys=True) + '\n' for item in items), encoding='utf-8', newline='\n')
    lock = suite['lock']
    atomic_json(output / 'metadata.json', {
        'schema_version': 1, 'experiment': MANIFEST['id'], 'mode': job['mode'], 'execution_kind': 'fixture', 'synthetic': True,
        'data_class': lock['data_class'], 'benchmark_id': lock['benchmark_id'], 'suite_revision': lock['revision'],
        'split_id': lock['split_id'], 'jurisdiction_profile': lock['jurisdiction_profile'], 'suite_lock_sha256': suite['lock_sha256'],
        'rubric_version': suite['rubric']['rubric_version'], 'matters': len(rows), 'families': len({r['family_id'] for r in rows}),
        'all_pass': sum(r['quality_pass'] for r in rows), 'review_required': True})
    return {'status': 'succeeded', 'result_path': '.', 'benchmark': BENCHMARK}
