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

from . import fixture
from .contracts import load_suite, pinned_files, private_file

MANIFEST = {'id': 'legal-benchmark', 'version': 1, 'modes': ['smoke'],
            'description': 'Legal retrieval, evidence-grounded analysis and draft screening memos for human review'}
BENCHMARK = 'legal-smoke'
# SHA-256 of experiments/legal-benchmark/workloads/original-smoke/suite.lock.json. The lock pins every suite file,
# so this one digest identifies the exact public-original suite that may enter generic report generation.
SMOKE_SUITE_SHA256 = 'ad3c2e3a506a9730ff2ac55b82ac62fbb4d3e9ea37365e9aebea7a6222f6c6ae'
REPORTING_DISABLED = ('legal-benchmark reports are limited to the public-original smoke suite, and its results are not '
                      'published, until the legal report projection is implemented')
# Directory names the generic report builder tests on the absolute path of every file it scans.
SCANNED_DIRECTORIES = ('model_judgment', 'reports')


def _parameters(case, mode):
    if mode not in MANIFEST['modes']:
        raise ValueError('Unsupported legal-benchmark mode: ' + str(mode))
    fields(case, {'suite', 'synthetic', 'top_k'}, ['suite', 'synthetic'])
    if not isinstance(case['suite'], str):
        raise ValueError('The legal-benchmark suite must be a path string')
    integer(case.get('top_k', 3), 'top_k', high=50)


def _admit(case, suite):
    """The checks of a loaded suite that `validate` and `execute` share."""
    # smoke runs the fixture pipeline: execution_kind `fixture`, the only kind that maps to legacy `synthetic: true`.
    if case['synthetic'] is not True:
        raise ValueError('The smoke mode is a fixture run and must declare synthetic: true')
    if suite['lock']['data_class'] != 'public-synthetic':
        raise ValueError('The smoke mode accepts public-synthetic suites only')
    fixture.check_gold(suite)


def validate(case, root, mode='smoke'):
    """Side-effect-free: reads and hashes the declared suite, nothing else."""
    _parameters(case, mode)
    _admit(case, load_suite(case['suite']))
    return None


def input_files(parameters, root, mode):
    """Every file the suite lock pins, so planner, resume and worker all check the same bytes."""
    return [str(path) for path in pinned_files(parameters['suite'])]


def setup_platforms(parameters, mode):
    """Serving platforms to install before a run. The fixture pipeline needs none."""
    return []


def _planned_suite(job):
    """The suite loaded once and bound to the plan: the lock bytes parsed must have the digest the planner recorded for
    `parameters.suite`, and the lock pins every other suite file by content."""
    suite = load_suite(job['parameters']['suite'])
    planned = {f['path']: f['sha256'] for f in job.get('input_files', [])}
    if planned.get(job['parameters']['suite']) != suite['lock_sha256']:
        raise ValueError('Suite differs from the planned input')
    return suite


def _is_smoke_suite(job):
    parameters = job.get('parameters', {})
    suite = parameters.get('suite')
    if job.get('mode') != 'smoke' or parameters.get('synthetic') is not True or not isinstance(suite, str):
        return False
    recorded = {f['path']: f['sha256'] for f in job.get('input_files', [])}
    if recorded.get(suite) != SMOKE_SUITE_SHA256:
        return False
    try:      # the bytes on disk, not only the digest a job dict claims
        return sha256_file(suite) == SMOKE_SUITE_SHA256
    except OSError:
        return False


def reporting_policy(jobs):
    """What the generic reporting layer may do with these jobs. Decided from the planned inputs, never from a
    campaign's reporting settings or a report's own labels."""
    allowed = bool(jobs) and all(_is_smoke_suite(job) for job in jobs)
    return {'report': allowed, 'publish': False, 'reason': REPORTING_DISABLED}


def claims_benchmark(name):
    """True for a benchmark name this plugin writes (`legal-smoke` and every later `legal-*` export). A bundle of another
    experiment that carries such a name has a second identity and is refused by `publish_report`."""
    return str(name).strip().lower().startswith('legal-')      # normalised: `LEGAL-smoke` or ` legal-smoke` is still claimed


def execute(job, output, root):
    parameters = job['parameters']
    _parameters(parameters, job['mode'])
    suite = _planned_suite(job)      # the only load of the run: a suite changed after planning, even relocked, fails here
    _admit(parameters, suite)
    output = Path(output)
    scanned = sorted(set(SCANNED_DIRECTORIES) & set(output.resolve().parts))
    if scanned:
        raise ValueError('Attempt path has a directory name the generic report scans: ' + scanned[0])
    if (output / 'requests.jsonl').exists():
        raise ValueError('This attempt already has request records')
    gold = {g['matter_id']: g for g in suite['rubric']['matters']}
    rows, drafts, details = [], [], []
    for matter in suite['matters']['matters']:
        entry = gold[matter['matter_id']]
        started = time.perf_counter()
        candidate = fixture.draft(matter, suite['corpus'], parameters.get('top_k', 3))
        elapsed = time.perf_counter() - started
        criteria = fixture.score(candidate, matter, entry, suite['corpus'])
        expected = entry['recommendation']
        rows.append({'task_id': matter['matter_id'], 'family_id': matter['family_id'], 'category': entry['scenario'], 'arm': 'smoke',
                     'benchmark': BENCHMARK, 'status': 'ok', 'repetition': 0, 'warmup': False, 'synthetic': True,
                     'execution_kind': 'fixture', 'data_class': suite['lock']['data_class'], 'elapsed_s': elapsed,
                     'parse_status': 'valid' if criteria['schema_valid'] else 'invalid', 'review_status': 'pending_human_review',
                     'expected_choice': expected, 'choice': candidate['recommendation'], 'decision_correct': candidate['recommendation'] == expected,
                     'quality_check_applicable': True, 'quality_pass': all(criteria.values()),
                     'criteria_passed': sum(criteria.values()), 'criteria_total': len(fixture.CRITERIA)})
        drafts.append(candidate)
        details.append({'matter_id': matter['matter_id'], 'family_id': matter['family_id'], 'arm': 'smoke', 'repetition': 0, 'status': 'ok',
                        'grading_status': 'scored', 'criteria': criteria, 'errors': [], 'pending_dimensions': [], 'reviewed_dimensions': {},
                        'adjudicated': [], 'gold_recommendation': expected, 'choice': candidate['recommendation'],
                        'author_choice': candidate['recommendation'], 'complete': not entry['missing_elements'] and not entry['conflict_elements']})
    # Candidate drafts and grader detail stay under local/. The generic report builder exports files by name at any depth,
    # so local/ is private only because `private_file` never gives a file a name that builder scans.
    private = private_file(output, 'candidate-outputs.jsonl'), private_file(output, 'score-detail.jsonl')
    for path, items in ((output / 'requests.jsonl', rows), (private[0], drafts), (private[1], details)):
        path.write_text(''.join(json.dumps(item, sort_keys=True) + '\n' for item in items), encoding='utf-8', newline='\n')
    lock = suite['lock']
    atomic_json(output / 'metadata.json', {
        'schema_version': 1, 'experiment': MANIFEST['id'], 'mode': job['mode'], 'execution_kind': 'fixture', 'synthetic': True,
        'data_class': lock['data_class'], 'benchmark_id': lock['benchmark_id'], 'suite_revision': lock['revision'],
        'split_id': lock['split_id'], 'jurisdiction_profile': lock['jurisdiction_profile'], 'suite_lock_sha256': suite['lock_sha256'],
        'rubric_version': suite['rubric']['rubric_version'], 'matters': len(rows), 'families': len({r['family_id'] for r in rows}),
        'all_pass': sum(r['quality_pass'] for r in rows), 'review_required': True})
    return {'status': 'succeeded', 'result_path': '.', 'benchmark': BENCHMARK}
