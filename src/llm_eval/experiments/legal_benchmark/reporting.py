"""One data classification, the strict report projection and the publication gates of the legal benchmark.

`classify(job)` is the only source of what a legal job may do. It reads the planned job, the files that job pins and the
reviewed list of approved suites, and nothing else: no report label, manifest field, campaign setting, case field or
caller argument decides what may leave the host.

| Level | Condition | What it allows |
|---|---|---|
| `approved` | verified and in the approved list | local and SSH runs, collection, a local report, and (authorized) manual publication |
| `declared` | verified, labelled public by its own lock, not in the approved list | a local run and a local, reduced report |
| `refused` | `private-matter`, a blocked dataset gate, or not verified | nothing |

`project(...)` builds the only report a legal run gets: a strict recursive allowlist of enumerated categories, opaque ids,
hashes, versioned numbers, coverage and coarse status. Per-matter rows leave only for the smoke mode; the model-run modes
(`retrieval`, `generation`, `workflow`, `score`) publish cohort aggregates with counts and intervals, never per-matter rows.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import math
import re
import secrets
import subprocess
import sys
import tempfile
from pathlib import Path

from llm_eval.common import digest, sha256_file
from llm_eval.core.contracts import identifier

from . import MODE_MODULES, _module, authority, contracts, fixture, grading, retrieval, routing, workflow

PROJECTION = {'id': 'legal-projection', 'version': 1}
LEVELS = ('approved', 'declared', 'refused')
REASON_CODES = tuple(dict.fromkeys(authority.REASONS + retrieval.REASONS + workflow.REASONS + grading.REASONS + routing.REASONS))
STATUSES = ('ok', 'invalid', 'error', 'missing')      # a row status: an answer, an invalid answer, an execution failure, no answer
TIMINGS = ('elapsed_s', 'first_output_s', 'first_visible_s', 'usable_memo_s')
RATES = ('truncated', 'revised', 'route_fallback', 'selector_deferral')
ROW_METRICS = (*('status.' + s for s in STATUSES), *('retrieval.' + m for m in retrieval.PUBLIC_METRICS),
               *(f'{t}.{q}' for t in TIMINGS for q in ('median', 'p95')), *('rate.' + r for r in RATES))
CLASSIFICATION = ('approved', 'not_approved', 'unknown_mode', 'lock_missing', 'planned_digest_mismatch', 'lock_invalid', 'private_matter',
                  'dataset_gate_blocked')
# The reason codes of `verify_publication`, in the order its checks run.
PUBLICATION = ('provenance_missing', 'legacy_report', 'plan_changed', 'unverified', 'not_approved', 'not_approved_upstream', 'receipt_mismatch',
               'bundle_mismatch', 'not_authorized')
MIN_COHORT = 5      # a projection that is not an exact fixture export publishes no number over fewer distinct matters
# The files an attempt's receipt binds, as the projection reads them (`attempt_receipt`).
RECEIPT_FILES = ('requests.jsonl', 'metadata.json', 'local/score-detail.jsonl')
# Exception names the modes can record as `error_type`; any other name is published as `error`.
ERROR_TYPES = ('error', 'IncompleteStream', 'IntegrityFailure', 'ToolCallRefused', 'TimeoutError', 'ConnectionError', 'ConnectionRefusedError',
               'ConnectionResetError', 'ConnectionAbortedError', 'BrokenPipeError', 'RemoteDisconnected', 'IncompleteRead', 'BadStatusLine',
               'HTTPError', 'URLError', 'OSError', 'RuntimeError', 'ValueError', 'UnicodeDecodeError', 'JSONDecodeError')
# The keys an exact smoke export publishes per matter. The rows' own `decision_correct` stays local (with `choice` it is the
# per-matter correctness); the summary computes the decision accuracy inside the projection.
SMOKE_EXPORT_KEYS = ('task_id', 'family_id', 'category', 'benchmark', 'arm', 'repetition', 'warmup', 'synthetic', 'execution_kind', 'data_class',
                     'status', 'elapsed_s', 'parse_status', 'review_status', 'expected_choice', 'choice', 'quality_check_applicable', 'quality_pass',
                     'criteria_passed', 'criteria_total')
# Reasons a scheduler or the coordinator records on a job; any other value is reported as `other`.
JOB_REASONS = CLASSIFICATION + ('data_policy', 'dependency_not_succeeded', 'target_unavailable', 'reservation_recovered',
                                'worker_completion_not_confirmed')
GRADING_MODES = ('smoke', 'generation', 'workflow', 'score')
PAIRED_MODES = ('generation', 'workflow', 'score')
PAIRED_METRICS = ('all_pass', 'error.wrong_version', 'error.unsupportive_citation')
# Interval metrics: the per-record indicators of `grading` (bootstrap by matter family).
INTERVAL_METRICS = ('all_pass', *('criterion.' + c for c in fixture.CRITERIA), *('error.' + c for c in grading.REASONS))
# Strings an author of a suite lock writes. A reduced projection (a suite that is not approved) publishes none of them.
AUTHOR_KEYS = ('benchmark_id', 'suite_revision', 'split_id', 'jurisdiction_profile', 'rubric_version', 'policy_id', 'policy_version')
REDUCED_ROW_KEYS = ('task_id', 'family_id', 'category', 'benchmark', 'arm', 'repetition', 'warmup', 'synthetic', 'execution_kind', 'data_class',
                    'status', 'retrieval_status', 'inference_status', 'parse_status', 'verification_status', 'grading_status', 'review_status',
                    'error_type', 'elapsed_s', 'first_output_s', 'first_visible_s', 'usable_memo_s', 'output_tokens_per_wall_second',
                    'backend_prefill_tps', 'backend_decode_tps', 'backend_load_s', 'finish_reason', 'truncated', 'request_attempts',
                    'parse_attempts', 'first_parse_status', 'revised', 'routed', 'router_s')
SUMMARY_KEYS = ('category', 'benchmark', 'status', 'warmup', 'synthetic', 'elapsed_s', 'first_output_s', 'first_visible_s',
                'output_tokens_per_wall_second', 'router_s')
CAMPAIGN = re.compile(r'campaign-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}')
AUTHORIZATION = 'publication-authorization.json'
SALT = 'projection-salt'


class ProjectionRejected(ValueError):
    """The projection refused its input. The message is a schema position or a reason code, never a value from the data."""


# One classification ---------------------------------------------------------------------------------------------------

def classify(job, root=None) -> dict:
    """The authoritative data classification of one planned job. Never raises. `root` names the repository whose approved
    list applies (default: the one this package belongs to)."""
    out = {'level': 'refused', 'verified': False, 'data_class': None, 'execution_kind': None, 'suite_lock_sha256': None,
           'approved': False, 'fixture_export': False, 'reason': 'unknown_mode'}
    step = 'unknown_mode'
    try:
        mode, parameters = job.get('mode'), job.get('parameters')
        if not isinstance(mode, str) or mode not in MODE_MODULES or not isinstance(parameters, dict):
            return out
        out['execution_kind'] = _module(mode).execution_kind(parameters, mode)
        step = 'lock_missing'
        suite = parameters.get('suite')
        if not isinstance(suite, str) or not Path(suite).is_file():
            return {**out, 'reason': step}
        step = 'planned_digest_mismatch'
        planned = {f.get('path'): f.get('sha256') for f in job.get('input_files') or [] if isinstance(f, dict)}.get(suite)
        if not isinstance(planned, str) or sha256_file(suite) != planned:
            return {**out, 'reason': step}
        step = 'lock_invalid'
        lock, paths = contracts.lock_files(suite)      # every pinned file verified against the lock
        if sha256_file(suite) != planned:      # the lock bytes did not change while they were verified
            return {**out, 'reason': 'planned_digest_mismatch'}
        out.update(data_class=lock['data_class'], suite_lock_sha256=planned)
        if lock['data_class'] == 'private-matter':
            return {**out, 'verified': True, 'reason': 'private_matter'}
        if lock['data_class'] == 'public-benchmark':      # the dataset gates themselves, not the text of a load error
            from . import benchmarks
            dataset = benchmarks.validate_dataset(contracts.read_json_strict(paths['dataset_lock'])[0],
                                                  rubric=contracts.read_json_strict(paths['rubric'])[0])
            entries = {e['path']: e['sha256'] for e in lock['source_files'] if e['purpose'] in contracts.PURPOSES + (contracts.SOURCE_PURPOSE,)}
            if benchmarks.blocked_gates(dataset, entries):
                return {**out, 'verified': True, 'reason': 'dataset_gate_blocked'}
            contracts.load_suite(suite)
        step = 'not_approved'
        entry = contracts.approved_suites(root).get(planned)
        approved = entry is not None and entry['benchmark_id'] == lock['benchmark_id']
        return {**out, 'verified': True, 'level': 'approved' if approved else 'declared', 'approved': approved,
                'fixture_export': bool(approved and entry['fixture_export']), 'reason': 'approved' if approved else 'not_approved',
                'lock': {k: lock[k] for k in ('benchmark_id', 'revision', 'split_id', 'jurisdiction_profile')}}
    except Exception:
        return {**out, 'verified': False, 'level': 'refused', 'approved': False, 'fixture_export': False, 'reason': step}


def data_policy(job, root=None) -> dict:
    c = classify(job, root)
    return {'admit': c['level'] != 'refused', 'transfer': c['level'] == 'approved', 'report': c['level'] != 'refused',
            'level': c['level'], 'data_class': c['data_class'], 'execution_kind': c['execution_kind'], 'reason': c['reason']}


def reporting_policy(jobs) -> dict:
    """Generic reporting of legal jobs: a local projected report when every job is reportable; automatic publication never."""
    jobs = list(jobs)
    policies = [data_policy(j) for j in jobs]
    failing = next((p['reason'] for p in policies if not p['report']), None)
    return {'report': bool(jobs) and failing is None, 'publish': False, 'include_outputs': False,
            'reason': failing or ('no_jobs' if not jobs else 'automatic_publication_unavailable')}


def _file(path):
    return path.is_file() and not path.is_symlink()


def attempt_receipt(directory) -> dict:
    """What the coordinator records about a finished attempt, when it finishes: the digests of the files the projection reads
    (`file_sha256`, which binds `metadata.json` and so the suite lock it names) and, for a generation or workflow attempt, the
    digest of its output manifest (`output_manifest_sha256`)."""
    directory = Path(directory)
    receipt = {'file_sha256': {name: sha256_file(directory / name) for name in sorted(RECEIPT_FILES) if _file(directory / name)}}
    if _file(directory / 'local/output-manifest.json'):
        receipt['output_manifest_sha256'] = sha256_file(directory / 'local/output-manifest.json')
    return receipt


def public_error_type(value):
    """An exception name the modes write, else the literal `error`."""
    return None if value is None else value if value in ERROR_TYPES else 'error'


def plan_unchanged(plan):
    """Drift of the stored plan: its digest must match, and a plan that holds a legal job always has one (the planner has
    always written it)."""
    from llm_eval.core.contracts import config_hash
    if 'plan_sha256' not in plan:
        return not any(isinstance(j, dict) and j.get('experiment_id') == 'legal-benchmark' for j in plan.get('jobs') or [])
    return config_hash({k: v for k, v in plan.items() if k != 'plan_sha256'}) == plan['plan_sha256']


# Cohort identity ------------------------------------------------------------------------------------------------------

def cohort(job, metadata, arm) -> tuple[dict, str]:
    """(cohort, cohort_sha256) of one arm of a job: built only from the planned job and the attempt metadata."""
    roles = metadata.get('roles') if isinstance(metadata.get('roles'), dict) else {}
    generator = roles.get('generator') if isinstance(roles.get('generator'), dict) else {}
    hardware = job.get('hardware') if isinstance(job.get('hardware'), dict) else {}
    selector = metadata.get('selector') if isinstance(metadata.get('selector'), dict) else None
    value = {'experiment': metadata.get('experiment'), 'mode': job.get('mode'), 'execution_kind': metadata.get('execution_kind'),
             'data_class': metadata.get('data_class'),
             **{k: metadata.get(k) for k in ('benchmark_id', 'suite_revision', 'suite_lock_sha256', 'split_id', 'jurisdiction_profile',
                                             'policy_id', 'policy_version', 'rubric_version', 'scorer_version', 'scorer_fingerprint',
                                             'reviewer_fingerprint')},
             'arm': arm, 'retrieval_sha256': digest(metadata['retrieval']) if metadata.get('retrieval') is not None else None,
             'selector_sha256': selector.get('selector_sha256') if selector else None,
             'role_digests': {name: (p or {}).get('profile_sha256') for name, p in sorted(roles.items())},
             **{k: generator.get(k) for k in ('model', 'model_revision', 'artifact_sha256', 'quantization', 'platform', 'backend_version',
                                              'protocol')},
             'prompt_template_sha256': metadata.get('template_sha256'),
             'generation_sha256': digest(metadata['generation']) if metadata.get('generation') is not None else None,
             'os_id': hardware.get('os_id'), 'hardware_profile': hardware.get('hardware_profile'),
             **{k: generator.get(k) for k in ('accelerator', 'context_tokens', 'max_output_tokens')}}
    return value, digest(value)


# The schema -----------------------------------------------------------------------------------------------------------

_NAME = r'[A-Za-z0-9][A-Za-z0-9._+-]{0,63}'
PATTERNS = {'identifier': re.compile(r'[a-z0-9][a-z0-9._-]{0,99}'), 'sha256': re.compile(r'[0-9a-f]{64}'), 'hex16': re.compile(r'[0-9a-f]{16}'),
            'hex32': re.compile(r'[0-9a-f]{32}'), 'version': re.compile(f'{_NAME}(?:/{_NAME})?(?::{_NAME})?'),
            'error_type': re.compile(r'[A-Za-z][A-Za-z0-9]{0,63}'), 'revision': re.compile(r'[0-9a-f]{40}'),
            'utc': re.compile(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,6})?\+00:00'),
            'publication': re.compile(CAMPAIGN.pattern + r'-[a-z0-9][a-z0-9._-]{0,99}')}


def _enum(*values):
    return ('enum', tuple(values))


def _p(name):
    return ('pattern', name)


def _null(node):
    return ('null', node)


def _list(node):
    return ('list', node)


def _object(fields, required=None):
    return ('object', fields, frozenset(fields if required is None else required))


NUMBER, COUNT, BOOL, ID, SHA = ('number',), ('count',), ('bool',), _p('identifier'), _p('sha256')
MAX_NUMBER, MAX_COUNT = 1e15, 10 ** 9
ARM = _enum('smoke', *retrieval.ARMS, 'routed')
CHOICE = _null(_enum(*contracts.RECOMMENDATIONS))
STATUS_ID = _null(ID)
REQUEST = _object({
    'task_id': ID, 'family_id': ID, 'category': ID, 'benchmark': ID, 'arm': ARM, 'repetition': COUNT, 'warmup': BOOL, 'synthetic': BOOL,
    'execution_kind': _enum(*contracts.EXECUTION_KINDS), 'data_class': _enum(*contracts.DATA_CLASSES), 'status': _enum(*STATUSES),
    **{k: STATUS_ID for k in ('retrieval_status', 'inference_status', 'parse_status', 'verification_status', 'grading_status', 'review_status',
                              'first_parse_status', 'token_count_source')},
    'reason_codes': _list(_enum(*REASON_CODES)), 'error_type': _null(_p('error_type')),
    'expected_choice': CHOICE, 'choice': CHOICE, 'author_choice': CHOICE,
    **{k: _null(BOOL) for k in ('abstained', 'forced_defer', 'quality_pass', 'truncated', 'revised', 'route_fallback')},
    'insufficiency_flags': _null(_list(_enum(*contracts.INSUFFICIENCY_FLAGS))), 'quality_check_applicable': BOOL,
    **{k: _null(COUNT) for k in ('criteria_passed', 'criteria_total', 'critical_errors', 'prompt_tokens', 'completion_tokens', 'reasoning_chars',
                                 'request_attempts', 'parse_attempts')},
    'pending_dimensions': _list(_enum(*grading.PENDING_DIMENSIONS)),
    **{k: _null(NUMBER) for k in (*retrieval.PUBLIC_METRICS, *TIMINGS, 'output_tokens_per_wall_second', 'backend_prefill_tps',
                                  'backend_decode_tps', 'backend_load_s', 'route_confidence', 'router_s')},
    'finish_reason': _null(_enum('stop', 'length', 'other', 'unknown')),
    **{k: _null(SHA) for k in ('output_sha256', 'output_manifest_sha256', 'scorer_fingerprint', 'reviewer_fingerprint')},
    'routed': BOOL, 'route_choice': _null(ID), 'route_selected': _null(_enum(*retrieval.ARMS)), 'route_error_type': _null(_p('error_type')),
    'inference_job_id': _null(ID), 'inference_attempt_id': _null(ID)},
    ('task_id', 'family_id', 'category', 'benchmark', 'arm', 'repetition', 'warmup', 'synthetic', 'execution_kind', 'data_class', 'status'))
# What an attempt row may hold (the smoke mode also writes `decision_correct`) and what a published row may hold (never it).
PUBLIC_REQUEST = REQUEST
REQUEST = _object({**PUBLIC_REQUEST[1], 'decision_correct': _null(BOOL)}, PUBLIC_REQUEST[2])
PUBLIC_REQUEST = _object({**PUBLIC_REQUEST[1], 'error_type': _null(_enum(*ERROR_TYPES)), 'route_error_type': _null(_enum(*ERROR_TYPES))},
                         PUBLIC_REQUEST[2])
VERSION = _null(_p('version'))
ROLE = _object({'profile_sha256': SHA, 'role': _enum(*workflow.ROLE_SET), 'serving': ID, 'capability': ID, 'platform': VERSION,
                'backend_version': VERSION, 'model': VERSION, 'model_revision': VERSION, 'artifact_sha256': _null(SHA), 'quantization': VERSION,
                'protocol': _null(ID), 'accelerator': _null(_enum('cpu', 'gpu')), 'context_tokens': _null(COUNT), 'max_output_tokens': _null(COUNT),
                'dimensions': _null(COUNT), 'qualified': BOOL, 'qualified_by_attestation': BOOL, 'serving_profile_sha256': _null(SHA)})
TELEMETRY = _object({'memory_scope': _enum('host', 'wsl_guest'), **{k: _null(NUMBER) for k in (
    'system_used_gib_peak', 'swap_used_gib_peak', 'gpu_used_mib_peak', 'gpu_power_w_peak', 'gpu_temperature_c_peak')},
    'disk_read_bytes': _null(COUNT), 'samples': COUNT})
METADATA = _object({
    'schema_version': COUNT, 'experiment': _enum('legal-benchmark'), 'mode': _enum(*MODE_MODULES), 'execution_kind': _enum(*contracts.EXECUTION_KINDS),
    'synthetic': BOOL, 'data_class': _enum(*contracts.DATA_CLASSES), 'benchmark_id': _null(ID), 'suite_revision': VERSION, 'split_id': _null(ID),
    'jurisdiction_profile': _null(ID), 'suite_lock_sha256': SHA, 'rubric_version': VERSION, 'scorer_version': VERSION, 'policy_id': _null(ID),
    'policy_version': VERSION, 'template_sha256': _null(SHA), 'arms': _list(ARM),
    'retrieval': _object({'backend': ID, 'top_k': COUNT, 'token_budget': COUNT, 'tokenizer': ID, 'chunking': ID, 'index_fingerprint': _null(SHA),
                          'embedder_sha256': _null(SHA), 'reranker_sha256': _null(SHA)}),
    'generation': _object({'seed': COUNT, 'temperature': NUMBER, 'parse_retries': COUNT, 'repeats': COUNT, 'max_output_tokens': COUNT}),
    'selector': _null(_object({'selector_sha256': SHA, 'router_kind': ID, 'calibration_sha256': _null(SHA)})),
    'roles': ('map', _enum(*workflow.ROLE_SET), ROLE), 'matters': COUNT, 'families': COUNT, 'rows': COUNT, 'all_pass': _null(COUNT),
    'review_required': BOOL, 'inference': _object({'job_id': ID, 'attempt_id': ID, 'output_manifest_sha256': SHA}),
    'scorer_fingerprint': _null(SHA), 'reviewer_fingerprint': _null(SHA), 'telemetry': ('map', ARM, TELEMETRY),
    'unavailable': _list(_enum('host_ram', 'guest_ram', 'vram', 'disk_reads', 'power', 'temperatures', 'pinned_allocations', 'per_drive_ssd_io',
                               'reasoning_tokens'))},
    ('schema_version', 'experiment', 'mode', 'execution_kind', 'synthetic', 'data_class', 'suite_lock_sha256'))
DETAIL = _object({
    'matter_id': ID, 'family_id': ID, 'arm': ARM, 'repetition': COUNT, 'status': ID, 'grading_status': ID,
    'criteria': _object({c: _null(BOOL) for c in fixture.CRITERIA}),
    'errors': _list(_object({'code': _enum(*grading.REASONS), 'critical': BOOL})), 'verifier_codes': _list(_enum(*grading.REASONS)),
    'pending_dimensions': _list(_enum(*grading.PENDING_DIMENSIONS)), 'reviewed_dimensions': ('map', _enum(*grading.PENDING_DIMENSIONS), _enum('pass', 'fail')),
    'adjudicated': _list(_enum(*grading.CRITICAL)), 'dismissed': _list(_enum(*grading.CRITICAL)), 'gold_recommendation': CHOICE, 'choice': CHOICE,
    'author_choice': CHOICE, 'complete': _null(BOOL), 'selector_deferral': _enum(*contracts.INSUFFICIENCY_FLAGS, *routing.REASONS)},
    ('matter_id', 'family_id', 'arm', 'repetition', 'status', 'grading_status', 'criteria', 'errors', 'pending_dimensions', 'reviewed_dimensions',
     'adjudicated', 'gold_recommendation', 'choice', 'author_choice', 'complete'))
METRIC_NAMES = ROW_METRICS + grading.METRICS
METRIC = _object({'value': _null(NUMBER), 'n': _null(COUNT), 'low': _null(NUMBER), 'high': _null(NUMBER), 'missing': _null(COUNT),
                  'suppressed': COUNT}, ('value', 'n', 'low', 'high', 'missing'))
# Every metric and paired difference of a reduced cohort of fewer than MIN_COHORT matters: presence, absence and counts carry nothing.
SMALL_METRIC = {'value': None, 'n': None, 'low': None, 'high': None, 'missing': None}
SMALL_PAIRED = {'mean': None, 'n': None, 'low': None, 'high': None, 'missing': None}
COHORT = _object({
    'experiment': _null(_enum('legal-benchmark')), 'mode': _enum(*MODE_MODULES), 'execution_kind': _null(_enum(*contracts.EXECUTION_KINDS)),
    'data_class': _null(_enum(*contracts.DATA_CLASSES)), 'benchmark_id': _null(ID), 'suite_revision': VERSION, 'suite_lock_sha256': _null(SHA),
    'split_id': _null(ID), 'jurisdiction_profile': _null(ID), 'policy_id': _null(ID), 'policy_version': VERSION, 'rubric_version': VERSION,
    'scorer_version': VERSION, 'scorer_fingerprint': _null(SHA), 'reviewer_fingerprint': _null(SHA), 'arm': ARM, 'retrieval_sha256': _null(SHA),
    'selector_sha256': _null(SHA), 'role_digests': ('map', _enum(*workflow.ROLE_SET), _null(SHA)), 'model': VERSION, 'model_revision': VERSION,
    'artifact_sha256': _null(SHA), 'quantization': VERSION, 'platform': VERSION, 'backend_version': VERSION, 'protocol': _null(ID),
    'prompt_template_sha256': _null(SHA), 'generation_sha256': _null(SHA), 'os_id': _null(ID), 'hardware_profile': _null(ID),
    'accelerator': _null(_enum('cpu', 'gpu')), 'context_tokens': _null(COUNT), 'max_output_tokens': _null(COUNT)})
LEGAL_SUMMARY = _object({
    'schema_version': COUNT,
    'cohorts': _list(_object({'job_id': ID, 'arm': ARM, 'cohort_sha256': SHA, 'cohort': COHORT, 'suppressed': BOOL,
                              'run_status': _null(_enum('complete', 'incomplete')), 'metrics': ('map', _enum(*METRIC_NAMES), METRIC)})),
    'paired': _list(_object({'job_id': ID, 'arm_a': ARM, 'arm_b': ARM, 'metric': _enum(*PAIRED_METRICS), 'mean': _null(NUMBER), 'n': _null(COUNT),
                             'low': _null(NUMBER), 'high': _null(NUMBER), 'missing': _null(COUNT), 'suppressed': COUNT},
                            ('job_id', 'arm_a', 'arm_b', 'metric', 'mean', 'n', 'low', 'high', 'missing')))})
COVERAGE = _object({'job_id': ID, 'status': ID, 'reason': _null(ID), 'attempts': COUNT})
PUBLIC_JOB = _object({
    'job_id': ID, 'experiment_id': _enum('legal-benchmark'), 'experiment_version': COUNT, 'mode': _enum(*MODE_MODULES), 'case_id': ID,
    'hardware_config_id': ID, 'hardware': _object({'os_id': ID, 'hardware_profile': ID}),
    'parameters': _object({'synthetic': BOOL, 'execution_kind': _enum(*contracts.EXECUTION_KINDS), 'data_class': _enum(*contracts.DATA_CLASSES),
                           'identity': _object({'harness': _p('version'), 'model': _p('version')}), 'cohorts': _list(SHA)}),
    'input_files': _list(_object({'sha256': SHA}))})
EXPERIMENT = _object({'experiment_run_id': ID, 'experiment_id': _enum('legal-benchmark'), 'version': COUNT, 'mode': _enum(*MODE_MODULES),
                      'job_ids': _list(ID), 'campaign_id': ID, 'code_revision': _p('revision')})
RECORD = _object({'job_id': ID, 'attempt_id': ID, 'latest_attempt': BOOL, 'record_type': _enum('request', 'metadata'),
                  'source_file': _enum('requests.jsonl', 'metadata.json'), 'data': ('record',)})
_STAT = {f'{k}_{q}': _null(NUMBER) for k in ('elapsed_s', 'router_s', 'generation_s', 'first_output_s', 'first_visible_s',
                                              'output_tokens_per_wall_second', 'quality', 'oracle_regret', 'brier_score',
                                              'estimated_generation_s', 'estimated_cost_usd') for q in ('median', 'p95')}
SUMMARY = _object({
    'job_id': ID, 'category': ID, 'benchmark': ID, 'synthetic': BOOL, 'requests': COUNT, 'successful_requests': COUNT, 'errors_or_missing': COUNT,
    **{k.replace('_median', '_n'): COUNT for k in _STAT if k.endswith('_median')}, **_STAT, 'decision_accuracy': _null(NUMBER),
    'decision_labelled_n': COUNT, 'quality_pass_rate': _null(NUMBER), 'quality_check_n': COUNT, 'abstentions': COUNT, 'policy_violations': COUNT,
    'confusion': _list(_object({'expected': _enum(*contracts.RECOMMENDATIONS), 'predicted': _enum(*contracts.RECOMMENDATIONS, '<invalid>'),
                                'count': COUNT})),
    'macro_f1': _null(NUMBER), 'known_api_cost_usd': NUMBER})
MANIFEST = _object({'projection': _object({'id': _enum(PROJECTION['id']), 'version': COUNT}), 'canonical_bytes': COUNT, 'synthetic': BOOL,
                    'execution_kinds': _list(_enum(*contracts.EXECUTION_KINDS)), 'data_class': _enum(*contracts.DATA_CLASSES),
                    'suite_lock_sha256': _list(SHA), 'cohorts': COUNT})
GENERIC = _object({'campaign_id': ID, 'experiment_run_id': ID, 'publication_id': _p('publication'), 'created_utc': _p('utc'),
                   'code_revision': _p('revision'), 'coverage': _list(COVERAGE)})


def _reject(path):
    raise ProjectionRejected(path)


def validate_projection(value, schema, path='$') -> None:
    """Strict recursive allowlist: every key is named by the schema, every leaf matches its type. The error names the schema
    position only (`request.category`, `request.<unknown key>`), never a key or a value of the data."""
    kind = schema[0]
    if kind == 'null':
        if value is not None:
            validate_projection(value, schema[1], path)
    elif kind == 'enum':
        if not isinstance(value, str) or value not in schema[1]:
            _reject(path)
    elif kind == 'pattern':
        if not isinstance(value, str) or not PATTERNS[schema[1]].fullmatch(value):
            _reject(path)
    elif kind == 'number':      # finite and bounded: a published number is never a channel for an arbitrary integer
        if type(value) not in (int, float) or not math.isfinite(value) or abs(value) > MAX_NUMBER:
            _reject(path)
    elif kind == 'count':
        if type(value) is not int or not 0 <= value <= MAX_COUNT:
            _reject(path)
    elif kind == 'bool':
        if type(value) is not bool:
            _reject(path)
    elif kind == 'list':
        if not isinstance(value, list):
            _reject(path)
        for item in value:
            validate_projection(item, schema[1], path + '[]')
    elif kind == 'object':
        if not isinstance(value, dict):
            _reject(path)
        for key in value:
            if not isinstance(key, str) or key not in schema[1]:
                _reject(path + '.<unknown key>')
        for key in sorted(schema[2]):
            if key not in value:
                _reject(path + '.' + key)
        for key, node in schema[1].items():
            if key in value:
                validate_projection(value[key], node, path + '.' + key)
    elif kind == 'map':
        if not isinstance(value, dict):
            _reject(path)
        for key, item in value.items():
            validate_projection(key, schema[1], path + '.<key>')
            validate_projection(item, schema[2], path + '.<value>')
    elif kind == 'record':
        _reject(path)      # a record's data is checked by its own record type (see `_validate_record`)
    else:
        _reject(path)


def _validate_record(record):
    validate_projection({**record, 'data': None}, _object({**RECORD[1], 'data': ('null', ('bool',))}), 'record')
    validate_projection(record['data'], PUBLIC_REQUEST if record['record_type'] == 'request' else METADATA,
                        'request' if record['record_type'] == 'request' else 'metadata')
    if (record['record_type'] == 'request') != (record['source_file'] == 'requests.jsonl'):
        _reject('record.source_file')


# The projection -------------------------------------------------------------------------------------------------------

def _no_links(campaign_dir, path):
    """No component from the campaign directory down to `path` is a symbolic link."""
    relative = Path(path).relative_to(campaign_dir)
    current = Path(campaign_dir)
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ProjectionRejected('symlink')


def _read(campaign_dir, path, what):
    """The bytes of a file the projection reads, or None when it does not exist; no link on the way down to it."""
    _no_links(campaign_dir, path)
    if not path.is_file():
        return None
    try:
        return path.read_bytes()
    except OSError:
        raise ProjectionRejected(what) from None


def _pairs(items):
    found = {}
    for key, value in items:
        if key in found:
            raise ValueError('duplicate key')
        found[key] = value
    return found


def _constant(name):
    raise ValueError('not a JSON number')


def _loads_strict(text):
    """`json.loads` that refuses duplicate keys and NaN or infinite constants (the reader `verify_publication` uses)."""
    return json.loads(text, object_pairs_hook=_pairs, parse_constant=_constant)


def _json_lines(data, what):
    try:
        return [_loads_strict(line) for line in data.decode('utf-8').splitlines() if line.strip()]
    except (ValueError, UnicodeDecodeError, RecursionError):
        raise ProjectionRejected(what) from None


def _json(data, what):
    try:
        return _loads_strict(data.decode('utf-8'))
    except (ValueError, UnicodeDecodeError, RecursionError):
        raise ProjectionRejected(what) from None


def _salt(experiment_dir, create):
    path = Path(experiment_dir) / SALT
    if path.is_symlink():
        raise ProjectionRejected('symlink')
    if path.is_file():
        value = path.read_text(encoding='ascii').strip()
        if not PATTERNS['hex32'].fullmatch(value):
            raise ProjectionRejected('salt')
        return value
    if not create:
        raise ProjectionRejected('salt')
    value = secrets.token_hex(16)
    contracts.write_text_atomic(path, value + '\n')
    return value


def _pseudonym(salt, value):
    return hashlib.sha256((salt + ':' + value).encode()).hexdigest()[:16]


def _metric(value=None, n=0, missing=0, low=None, high=None):
    return {'value': value, 'n': n, 'low': low, 'high': high, 'missing': missing}


def _suppressed(metric):
    """A metric over too few matters: no value, no count, no interval; `suppressed` keeps the size of what was withheld."""
    return {'value': None, 'n': 0, 'low': None, 'high': None, 'missing': metric['missing'], 'suppressed': metric['n']}


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def _nearest(values, q):
    ordered = sorted(values)
    return ordered[math.ceil(q * len(ordered)) - 1]


def _row_metrics(rows):
    """{metric: (entry, the matters it is computed over)}."""
    out = {}

    def ids(chosen):
        return {r['task_id'] for r in chosen}
    for s in STATUSES:
        out['status.' + s] = (_metric(sum(r['status'] == s for r in rows), len(rows)), ids(rows))
    for name in retrieval.PUBLIC_METRICS:
        chosen = [r for r in rows if _number(r.get(name))]
        values = [r[name] for r in chosen]
        out['retrieval.' + name] = (_metric(round(math.fsum(values) / len(values), 6) if values else None, len(values), len(rows) - len(values)),
                                    ids(chosen))
    ok = [r for r in rows if r['status'] == 'ok']
    for name in TIMINGS:
        chosen = [r for r in ok if _number(r.get(name))]
        values = [r[name] for r in chosen]
        for q, label in ((0.5, 'median'), (0.95, 'p95')):
            out[f'{name}.{label}'] = (_metric(round(float(_nearest(values, q)), 6) if values else None, len(values), len(rows) - len(values)),
                                      ids(chosen))
    for name in ('truncated', 'revised', 'route_fallback'):
        chosen = [r for r in rows if type(r.get(name)) is bool]
        values = [r[name] for r in chosen]
        out['rate.' + name] = (_metric(round(sum(values) / len(values), 6) if values else None, len(values), len(rows) - len(values)), ids(chosen))
    routed = [r for r in rows if r.get('routed') is True]
    deferred = sum(r['category'] == 'routed-defer' for r in routed)
    out['rate.selector_deferral'] = (_metric(round(deferred / len(routed), 6) if routed else None, len(routed), len(rows) - len(routed)),
                                     ids(routed))
    return out


def _denominator(name, details):
    """The score-detail records a `grading.aggregate` metric is computed over (its denominator), as `aggregate` defines them."""
    scored = [d for d in details if d['grading_status'] == 'scored']
    if name.startswith('missing.'):
        return details
    if name == 'all_pass_reviewed':
        return [d for d in scored if all(dim in d['reviewed_dimensions'] for dim in grading.PENDING_DIMENSIONS)]
    if name.endswith('_false_charge'):
        return [d for d in scored if d['gold_recommendation'] in ('decline', 'defer')]
    if name.endswith('_false_defer'):
        return [d for d in scored if d['complete'] and d['gold_recommendation'] != 'defer']
    if name.endswith('_dangerous_commitment'):
        return [d for d in scored if d['gold_recommendation'] == 'defer']
    if name.startswith(('confusion.', 'workflow_confusion.')):      # a cell is as small as its gold class
        gold = name.split('.')[1]
        return [d for d in scored if d['gold_recommendation'] == gold]
    return scored


def _grading_metrics(details):
    try:
        values = grading.aggregate(details)
    except ValueError:
        raise ProjectionRejected('score_detail') from None
    out = {name: _metric(entry['value'], entry['n'], entry['missing']) for name, entry in values.items()}
    scored = [d for d in details if d['grading_status'] == 'scored']
    for name in INTERVAL_METRICS:
        families = {}
        for d in scored:
            families.setdefault(d['family_id'], []).append(grading._indicator(d, name))
        interval = grading.bootstrap(families)
        if interval is not None:
            out[name]['low'], out[name]['high'] = interval
    return {name: (entry, {d['matter_id'] for d in _denominator(name, details)}) for name, entry in out.items()}


def _check_detail(d):
    validate_projection(d, DETAIL, 'score_detail')
    if set(d['criteria']) != set(fixture.CRITERIA):
        _reject('score_detail.criteria')


def _public_job(job, classification, metadata, cohorts):
    roles = (metadata or {}).get('roles') if isinstance((metadata or {}).get('roles'), dict) else {}
    if classification['execution_kind'] == 'fixture':
        identity = {'harness': 'fixture', 'model': 'fixture'}
    else:
        role = next((roles[r] for r in ('generator', 'embedder', 'reranker', 'selector') if isinstance(roles.get(r), dict)), {})
        identity = {'harness': role.get('platform') or 'unknown', 'model': role.get('model') or 'unknown'}
    hardware = job.get('hardware') if isinstance(job.get('hardware'), dict) else {}
    return {'job_id': job['job_id'], 'experiment_id': job.get('experiment_id'), 'experiment_version': job.get('experiment_version'),
            'mode': job['mode'], 'case_id': job.get('case_id'), 'hardware_config_id': job.get('hardware_config_id'),
            'hardware': {'os_id': hardware.get('os_id'), 'hardware_profile': hardware.get('hardware_profile')},
            'parameters': {'synthetic': classification['execution_kind'] == 'fixture', 'execution_kind': classification['execution_kind'],
                           'data_class': classification['data_class'], 'identity': identity, 'cohorts': sorted(set(cohorts))},
            'input_files': [{'sha256': f.get('sha256')} for f in job.get('input_files') or []]}


def _job_reason(reason):
    if reason is None:
        return None
    return reason if isinstance(reason, str) and reason in JOB_REASONS + REASON_CODES else 'other'


def project(campaign_dir, plan, state, exp, *, create_salt=True) -> dict:
    """The legal report of one experiment run, built only from validated inputs. Raises ProjectionRejected."""
    try:
        return _project(Path(campaign_dir).resolve(), plan, state, exp, create_salt)
    except ProjectionRejected:
        raise
    except Exception:      # any other failure: a code, never a message that could carry a value from the inputs
        raise ProjectionRejected('projection_failed') from None


def _exact_metadata(metadata, classification, suite):
    """An exact fixture export publishes the lock's own strings: the metadata must name exactly the lock and rubric it ran on."""
    from . import authority as policies
    lock = classification['lock']
    policy = policies.policy_or_none(suite['corpus'])
    expected = {'benchmark_id': lock['benchmark_id'], 'suite_revision': lock['revision'], 'split_id': lock['split_id'],
                'jurisdiction_profile': lock['jurisdiction_profile'], 'rubric_version': suite['rubric'].get('rubric_version'),
                'policy_id': policy['policy_id'] if policy else None, 'policy_version': policy['version'] if policy else None}
    if any(key in metadata and metadata[key] != value for key, value in expected.items()):
        raise ProjectionRejected('metadata')


def _bound(record, name, data):
    """A receipt that names the file binds its bytes."""
    recorded = (record.get('file_sha256') or {}) if isinstance(record.get('file_sha256'), dict) else {}
    if name in recorded and (data is None or hashlib.sha256(data).hexdigest() != recorded[name]):
        raise ProjectionRejected('receipt_mismatch')


def _project(campaign_dir, plan, state, exp, create_salt):
    from llm_eval.reporting.experiment import summaries
    entry = next((e for e in plan['experiments'] if e.get('experiment_run_id') == exp.get('experiment_run_id')), None)
    if entry is None or entry.get('experiment_id') != exp.get('experiment_id') or entry.get('job_ids') != exp.get('job_ids'):
        raise ProjectionRejected('experiment')
    if not plan_unchanged(plan):
        raise ProjectionRejected('plan_changed')
    planned = {j['job_id']: j for j in plan['jobs']}
    if any(jid not in planned for jid in entry['job_ids']):
        raise ProjectionRejected('experiment')
    jobs = [planned[jid] for jid in entry['job_ids']]
    if set(contracts.SCANNED_NAMES) & {part.casefold() for part in campaign_dir.parts}:
        raise ProjectionRejected('scanned_directory')      # the coordinator's path, not only the worker's
    experiment_dir = campaign_dir / 'experiments' / identifier(entry['experiment_run_id'])
    classes = {}
    for job in jobs:
        policy = data_policy(job)
        if not policy['report'] or job.get('experiment_id') != 'legal-benchmark':
            raise ProjectionRejected('not_reportable')
        classes[job['job_id']] = classify(job)
    reduced = not all(c['fixture_export'] for c in classes.values())      # one unexported suite reduces the whole run
    salt = _salt(experiment_dir, create_salt) if reduced else None
    records, cohorts, paired, summary_records, public_jobs, coverage = [], [], [], [], [], []
    small_jobs = set()      # jobs of a reduced projection with a cohort of fewer than MIN_COHORT matters: no generic summary row
    for job in jobs:
        c, jid, mode = classes[job['job_id']], job['job_id'], job['mode']
        exact = not reduced
        job_state = state['jobs'][jid]
        coverage.append({'job_id': jid, 'status': job_state['status'], 'reason': _job_reason(job_state.get('reason')),
                         'attempts': len(job_state['attempts'])})
        suite = contracts.load_suite(job['parameters']['suite']) if exact else None
        latest_rows, latest_metadata, latest_details = [], None, []
        for i, attempt in enumerate(job_state['attempts']):
            latest = i == len(job_state['attempts']) - 1
            base = campaign_dir / attempt['output']
            if not base.is_relative_to(campaign_dir):
                raise ProjectionRejected('attempt_path')
            _no_links(campaign_dir, base)      # before resolving: a linked attempt directory is a link, not an escape
            if not base.resolve().is_relative_to(campaign_dir):
                raise ProjectionRejected('attempt_path')
            data = _read(campaign_dir, base / 'metadata.json', 'metadata')
            metadata = _json(data, 'metadata') if data is not None else None
            if metadata is not None:
                validate_projection(metadata, METADATA, 'metadata')
                if metadata['mode'] != mode or metadata['suite_lock_sha256'] != c['suite_lock_sha256'] or \
                        metadata['data_class'] != c['data_class'] or metadata['execution_kind'] != c['execution_kind']:
                    raise ProjectionRejected('metadata')
                if exact:
                    _exact_metadata(metadata, c, suite)
            _bound(attempt, 'metadata.json', data)
            data = _read(campaign_dir, base / 'requests.jsonl', 'request')
            rows = _json_lines(data, 'request') if data is not None else []
            for row in rows:
                validate_projection(row, REQUEST, 'request')
                if row['data_class'] != c['data_class'] or row['execution_kind'] != c['execution_kind']:
                    raise ProjectionRejected('request')
                if exact and mode == 'smoke':
                    matters = {m['matter_id']: m['family_id'] for m in suite['matters']['matters']}
                    if row['task_id'] not in matters:
                        _reject('request.task_id')
                    if row['family_id'] != matters[row['task_id']]:
                        _reject('request.family_id')
                    if row['category'] not in {g['scenario'] for g in suite['rubric']['matters']}:
                        _reject('request.category')
            _bound(attempt, 'requests.jsonl', data)
            details = []
            if metadata is not None and mode in GRADING_MODES:
                data = _read(campaign_dir, base / 'local/score-detail.jsonl', 'score_detail')
                if data is None:
                    if latest:
                        raise ProjectionRejected('score_detail')
                else:
                    details = _json_lines(data, 'score_detail')
                    for d in details:
                        _check_detail(d)
                _bound(attempt, 'local/score-detail.jsonl', data)
            if latest:
                latest_rows, latest_metadata, latest_details = rows, metadata, details
            head = {'job_id': jid, 'attempt_id': attempt['attempt_id'], 'latest_attempt': latest}
            if metadata is not None:
                published = {k: (None if k in AUTHOR_KEYS and not exact else v) for k, v in metadata.items()}
                if not exact and 'all_pass' in published:
                    published['all_pass'] = None      # a pass count is a number over matters: in legal-summary.json, with the size rule
                records.append({**head, 'record_type': 'metadata', 'source_file': 'metadata.json', 'data': published})
            if mode == 'smoke':      # per-matter rows leave for the fixture smoke only; the model-run modes are aggregated
                if exact:
                    published = [{k: row[k] for k in SMOKE_EXPORT_KEYS if k in row} for row in rows]
                    summary_records += [{**head, 'record_type': 'request', 'data': dict(row)} for row in rows]      # correctness stays inside
                else:
                    published = [{k: (_pseudonym(salt, row[k]) if k in ('task_id', 'family_id') else 'all' if k == 'category'
                                      else public_error_type(row[k]) if k == 'error_type' else row[k])
                                  for k in REDUCED_ROW_KEYS if k in row} for row in rows]
                    published.sort(key=lambda r: (r['task_id'], r['arm'], r['repetition'], r['warmup']))
                    summary_records += [{**head, 'record_type': 'request', 'data': r} for r in published]
                records += [{**head, 'record_type': 'request', 'source_file': 'requests.jsonl', 'data': r} for r in published]
            else:
                for row in rows:
                    data = {k: row[k] for k in SUMMARY_KEYS if k in row}
                    if not exact:
                        data['benchmark'] = 'unspecified'
                    else:
                        data.update({k: row[k] for k in ('quality_check_applicable', 'quality_pass') if k in row})
                        if type(row.get('abstained')) is bool:
                            data['abstained'] = row['abstained']
                    summary_records.append({**head, 'record_type': 'request', 'data': data})
        digests = []
        if latest_metadata is not None:
            details = latest_details
            arms = ['smoke'] if mode == 'smoke' else ['routed'] if latest_metadata.get('selector') else list(latest_metadata.get('arms') or [])
            measured = [r for r in latest_rows if not r['warmup']]
            # An invalid answer is an incorrect answer, not an execution failure.
            complete = job_state['status'] == 'succeeded' and not any(r['status'] in ('error', 'missing') for r in measured)
            by_arm, small = {}, set()
            for arm in arms:
                rows_a = [r for r in measured if r['arm'] == arm]
                by_arm[arm] = [d for d in details if d['arm'] == arm]
                computed = _row_metrics(rows_a)
                if mode in GRADING_MODES:
                    computed.update(_grading_metrics(by_arm[arm]))
                value, sha = cohort(job, latest_metadata, arm)
                public = {k: (None if k in AUTHOR_KEYS and not exact else v) for k, v in value.items()}
                digests.append(sha)
                if reduced and len({r['task_id'] for r in rows_a} | {d['matter_id'] for d in by_arm[arm]}) < MIN_COHORT:
                    # Too few matters for any number: every metric the mode can produce, in one shape with no number in it.
                    small.add(arm)
                    names = ROW_METRICS + (grading.METRICS if mode in GRADING_MODES else ())
                    cohorts.append({'job_id': jid, 'arm': arm, 'cohort_sha256': sha, 'cohort': public, 'suppressed': True, 'run_status': None,
                                    'metrics': {name: dict(SMALL_METRIC) for name in names}})
                    continue
                metrics = {name: (_suppressed(m) if reduced and m['n'] and len(matters) < MIN_COHORT else m)
                           for name, (m, matters) in computed.items()}
                cohorts.append({'job_id': jid, 'arm': arm, 'cohort_sha256': sha, 'cohort': public, 'suppressed': False,
                                'run_status': 'complete' if complete else 'incomplete', 'metrics': metrics})
            if small:
                small_jobs.add(jid)
            if mode in PAIRED_MODES and not latest_metadata.get('selector'):
                for i, a in enumerate(arms):
                    for b in arms[i + 1:]:
                        both = {d['matter_id'] for d in by_arm[a] if d['grading_status'] == 'scored'} & \
                            {d['matter_id'] for d in by_arm[b] if d['grading_status'] == 'scored'}
                        for metric in PAIRED_METRICS:
                            try:
                                diff = grading.paired_difference(by_arm[a], by_arm[b], metric)
                            except ValueError:
                                raise ProjectionRejected('score_detail') from None
                            if a in small or b in small:
                                diff = dict(SMALL_PAIRED)
                            elif reduced and diff['n'] and len(both) < MIN_COHORT:
                                diff = {'mean': None, 'n': 0, 'low': None, 'high': None, 'missing': diff['missing'], 'suppressed': diff['n']}
                            paired.append({'job_id': jid, 'arm_a': a, 'arm_b': b, 'metric': metric, **diff})
        public_jobs.append(_public_job(job, c, latest_metadata, digests))
    cohorts.sort(key=lambda x: (x['job_id'], x['arm']))
    data_classes = sorted({c['data_class'] for c in classes.values()})
    if len(data_classes) != 1:
        raise ProjectionRejected('data_class')
    experiment = {'experiment_run_id': entry['experiment_run_id'], 'experiment_id': entry['experiment_id'], 'version': entry.get('version'),
                  'mode': entry.get('mode'), 'job_ids': list(entry['job_ids']), 'campaign_id': plan['campaign_id'],
                  'code_revision': plan['code_revision']}
    kinds = sorted({c['execution_kind'] for c in classes.values()})
    manifest = {'projection': dict(PROJECTION), 'canonical_bytes': 1, 'synthetic': any(k == 'fixture' for k in kinds), 'execution_kinds': kinds,
                'data_class': data_classes[0], 'suite_lock_sha256': sorted({c['suite_lock_sha256'] for c in classes.values()}),
                'cohorts': len(cohorts)}
    legal = {'schema_version': 1, 'cohorts': cohorts, 'paired': paired}
    summary = summaries([r for r in summary_records if r['job_id'] not in small_jobs])
    generic = {'campaign_id': plan['campaign_id'], 'experiment_run_id': entry['experiment_run_id'],
               'publication_id': campaign_dir.name + '-' + entry['experiment_run_id'], 'created_utc': state['created_utc'],
               'code_revision': plan['code_revision'], 'coverage': coverage}
    for record in records:
        _validate_record(record)
    for value, schema, where in ((legal, LEGAL_SUMMARY, 'legal_summary'), (experiment, EXPERIMENT, 'experiment'), (manifest, MANIFEST, 'manifest'),
                                 (generic, GENERIC, 'manifest'), (public_jobs, _list(PUBLIC_JOB), 'jobs'), (summary, _list(SUMMARY), 'summary')):
        validate_projection(value, schema, where)
    input_hashes = sorted({f['sha256'] for j in public_jobs for f in j['input_files']})
    readme = _readme(generic, manifest, coverage, public_jobs, cohorts, paired, reduced)
    return {'records': records, 'coverage': coverage, 'experiment': experiment, 'jobs': public_jobs, 'input_hashes': input_hashes,
            'files': {'legal-summary.json': legal}, 'manifest': manifest, 'readme': readme, 'summary': summary}


def _fmt(value):
    return 'unavailable' if value is None else str(value)


def _readme(generic, manifest, coverage, jobs, cohorts, paired, reduced):
    """Fixed sentences and projected values only."""
    status = 'complete' if all(c['status'] in ('succeeded', 'skipped') for c in coverage) else 'incomplete'
    modes = {j['job_id']: j for j in jobs}
    text = (f"# legal-benchmark results\n\nStatus: **{status}**. Execution classes: **{', '.join(manifest['execution_kinds'])}**. "
            f"Data class: **{manifest['data_class']}**. Cohorts: **{manifest['cohorts']}**.\n\n"
            f"Campaign: `{generic['campaign_id']}`. Experiment run: `{generic['experiment_run_id']}`. Measured code: `{generic['code_revision']}`.\n\n"
            '[Raw measurements](raw/measurements.jsonl.gz) · [JSON summary](summary.json) · [CSV summary](summary.csv) · '
            '[Legal summary](legal-summary.json) · [Manifest](manifest.json) · [Resolved configuration](resolved-config.json)\n\n'
            'Fixture runs do not measure a model. Every output requires human review. This bundle is a validated projection: it holds '
            'enumerated categories, opaque ids, hashes, versioned numbers, coverage and coarse status, and no document text, prompt, '
            'answer, citation, grader comment or path.\n\n')
    text += '## Configuration coverage\n\n| Job | Mode | OS | Execution kind | Status | Attempts | Reason |\n|---|---|---|---|---|---:|---|\n'
    for c in coverage:
        j = modes[c['job_id']]
        text += (f"| `{c['job_id']}` | {j['mode']} | {j['hardware']['os_id']} | {j['parameters']['execution_kind']} | {c['status']} | "
                 f"{c['attempts']} | {_fmt(c['reason'])} |\n")
    text += '\n## Cohorts\n\nEach job and arm is one cohort. Two runs are comparable only when their cohort digests are equal. Every score has its count; scores without a denominator are unavailable, and the missing scores are counted.\n'
    for c in cohorts:
        if c['suppressed']:
            text += (f"\n### Job `{c['job_id']}`, arm `{c['arm']}`\n\nCohort `{c['cohort_sha256'][:12]}`. This cohort of a reduced projection "
                     f"has fewer than {MIN_COHORT} matters: no score, count or run status is published.\n")
            continue
        text += (f"\n### Job `{c['job_id']}`, arm `{c['arm']}`\n\nCohort `{c['cohort_sha256'][:12]}`. Run status: **{c['run_status']}**.\n\n"
                 '| Metric | Value | Count | Low | High | Missing |\n|---|---:|---:|---:|---:|---:|\n')
        for name, m in c['metrics'].items():
            text += f"| {name} | {_fmt(m['value'])} | {m['n']} | {_fmt(m['low'])} | {_fmt(m['high'])} | {m['missing']} |\n"
    text += '\n## Paired differences\n\n'
    if paired:
        text += '| Job | Arm A | Arm B | Metric | Mean (A minus B) | Pairs | Low | High | Missing |\n|---|---|---|---|---:|---:|---:|---:|---:|\n'
        for p in paired:
            text += (f"| `{p['job_id']}` | {p['arm_a']} | {p['arm_b']} | {p['metric']} | {_fmt(p['mean'])} | {p['n']} | {_fmt(p['low'])} | "
                     f"{_fmt(p['high'])} | {p['missing']} |\n")
    else:
        text += 'No job of this run compares arms.\n'
    text += ('\n## Interpretation\n\nIntervals are bootstrap percentiles over matter families and are unavailable below six families. '
             'The legal summary grades every arm, the reference arm included; the generic summary excludes the reference arm, whose '
             'rows publish no number. For a retrieval job the generic quality pass rate is the exact-version pass rate and its cohort '
             'has no pass rate of its own. Per-matter rows are published for the fixture smoke mode only; the retrieval, generation, '
             'workflow and score modes publish cohort aggregates.')
    if reduced:
        text += (' This is a reduced projection of a suite that is not approved: identifiers are pseudonyms, decision and quality '
                 'values are aggregated, the generic summary has no quality pass rate, and the strings of the suite lock are omitted.')
    return text + '\n'


# Publication ----------------------------------------------------------------------------------------------------------

def _provenance(report):
    report = Path(report).resolve()
    experiment_dir = report.parent
    campaign = experiment_dir.parent.parent
    if report.name != 'report' or experiment_dir.parent.name != 'experiments' or not CAMPAIGN.fullmatch(campaign.name) or \
            not all((campaign / name).is_file() for name in ('plan.json', 'campaign.json')) or not (experiment_dir / 'experiment.json').is_file():
        raise ValueError('provenance_missing')
    return report, experiment_dir, campaign


def _strict(path, code):
    try:
        value, _ = contracts.read_json_strict(path)
    except (OSError, ValueError):
        raise ValueError(code) from None
    if not isinstance(value, dict):
        raise ValueError(code)
    return value


def _upstream(root, base):
    """The approved list as committed on `base` of the repository at `root`."""
    p = subprocess.run(['git', '-C', str(root), 'show', f'{base}:{contracts.APPROVED_SUITES}'], capture_output=True, timeout=120)
    if p.returncode:
        raise ValueError('not_approved_upstream')
    with tempfile.TemporaryDirectory(prefix='llm-eval-approved-') as tmp:
        path = Path(tmp) / contracts.APPROVED_SUITES
        path.parent.mkdir(parents=True)
        path.write_bytes(p.stdout)
        try:
            return contracts.approved_suites(tmp)
        except ValueError:
            raise ValueError('not_approved_upstream') from None


def _verify(report, root, base):
    """Checks 1 to 5 of `verify_publication`; returns what checks 6 and `authorize` need."""
    report, experiment_dir, campaign = _provenance(report)
    spec = _strict(report / 'publication.json', 'legacy_report')
    rel = spec.get('report_path')
    manifest = _strict(report / 'bundle' / rel / 'manifest.json', 'legacy_report') if isinstance(rel, str) else None
    if manifest is None or manifest.get('projection') != PROJECTION or manifest.get('canonical_bytes') != 1:
        raise ValueError('legacy_report')
    plan, state = _strict(campaign / 'plan.json', 'unverified'), _strict(campaign / 'campaign.json', 'receipt_mismatch')
    if not plan_unchanged(plan):
        raise ValueError('plan_changed')
    exp = _strict(experiment_dir / 'experiment.json', 'unverified')
    entry = next((e for e in plan.get('experiments') or [] if isinstance(e, dict) and e.get('experiment_run_id') == experiment_dir.name), None)
    if entry is None or entry.get('job_ids') != exp.get('job_ids') or not entry.get('job_ids'):
        raise ValueError('unverified')
    planned = {j.get('job_id'): j for j in plan.get('jobs') or [] if isinstance(j, dict)}
    jobs = [planned.get(jid) for jid in entry['job_ids']]
    if any(j is None for j in jobs):
        raise ValueError('unverified')
    # The installed package's own approved list, for this check and for the rebuild below alike; `root` names the repository
    # only for the upstream check, so a crafted directory approves nothing.
    classes = [classify(j) for j in jobs]
    for c in classes:
        if not c['verified']:
            raise ValueError('unverified')
        if c['level'] != 'approved':
            raise ValueError('not_approved')
    if base is not None:
        local, upstream = contracts.approved_suites(), _upstream(root, base)
        for c in classes:
            if upstream.get(c['suite_lock_sha256']) != local.get(c['suite_lock_sha256']):
                raise ValueError('not_approved_upstream')
    for job, c in zip(jobs, classes):
        attempts = ((state.get('jobs') or {}).get(job['job_id']) or {}).get('attempts') or []
        latest = attempts[-1] if attempts else None
        if not isinstance(latest, dict) or latest.get('status') != 'succeeded' or not isinstance(latest.get('output'), str):
            raise ValueError('receipt_mismatch')
        attempt = campaign / latest['output']
        try:
            metadata, _ = contracts.read_json_strict(attempt / 'metadata.json')
        except (OSError, ValueError):
            raise ValueError('receipt_mismatch') from None
        if not isinstance(metadata, dict) or metadata.get('suite_lock_sha256') != c['suite_lock_sha256'] or metadata.get('experiment') != 'legal-benchmark':
            raise ValueError('receipt_mismatch')
        # The coordinator's receipt binds the suite, every file the projection reads and the output manifest; publication
        # needs all of it (a campaign written before the receipt existed is reported locally, never published).
        now = attempt_receipt(attempt)
        if not latest.get('file_sha256') or \
                any(latest.get(k) != now.get(k) for k in ('file_sha256', 'output_manifest_sha256')):
            raise ValueError('receipt_mismatch')
        if job['mode'] == 'score':      # a score job publishes only over a source attempt a coordinator recorded
            try:
                manifest_path = Path(job['parameters']['output_manifest'])
                grading._recorded(manifest_path.parent.parent, sha256_file(manifest_path), required=True)
            except (OSError, ValueError, KeyError, TypeError):
                raise ValueError('receipt_mismatch') from None
    from llm_eval.reporting.experiment import projected_bundle

    def rebuild(*args):      # this plugin's own projection, without a new salt; shared code passes no plugin keyword
        return project(*args, create_salt=False)
    try:
        files, publication = projected_bundle(experiment_dir, rebuild)
    except (ProjectionRejected, OSError, KeyError, TypeError):
        raise ValueError('bundle_mismatch') from None
    bundle = report / 'bundle'
    found = {p.relative_to(bundle).as_posix(): p for p in bundle.rglob('*') if p.is_file() or p.is_symlink()}
    if set(found) != set(files) or any(p.is_symlink() or p.read_bytes() != files[name] for name, p in found.items()):
        raise ValueError('bundle_mismatch')
    if (report / 'publication.json').read_bytes() != publication:
        raise ValueError('bundle_mismatch')
    return {'experiment_run_id': experiment_dir.name, 'report_fingerprint': manifest.get('report_fingerprint'),
            'suite_lock_sha256': sorted({c['suite_lock_sha256'] for c in classes}), 'repository': spec.get('repository'),
            'base_branch': spec.get('base_branch'), 'campaign': campaign, 'files': sorted(files), 'classes': classes,
            'execution_kinds': sorted({c['execution_kind'] for c in classes})}


AUTHORIZED = ('experiment_run_id', 'report_fingerprint', 'suite_lock_sha256', 'repository', 'base_branch')


def verify_publication(report, root, base=None) -> None:
    """The publication gate of a legal report. Raises ValueError(<reason code>) unless the bundle is exactly the projection
    rebuilt from a run receipt over approved suite locks (approved on `base` too, when given) and an authorization binds it."""
    found = _verify(report, root, base)
    path = found['campaign'] / AUTHORIZATION
    try:
        authorization, _ = contracts.read_json_strict(path)
    except (OSError, ValueError):
        raise ValueError('not_authorized') from None
    if not isinstance(authorization, dict) or any(authorization.get(k) != found[k] for k in AUTHORIZED):
        raise ValueError('not_authorized')


def authorize(campaign_dir, experiment_run_id, approved_by, confirm=None) -> Path:
    """The separately authorized publication step: verify the report, show what would be published, ask for confirmation,
    then write `publication-authorization.json` in the campaign directory. `confirm(text) -> bool`; without it an interactive
    terminal must type the run id back."""
    identifier(experiment_run_id)
    identifier(approved_by)
    report = Path(campaign_dir).resolve() / 'experiments' / experiment_run_id / 'report'
    found = _verify(report, None, None)
    approved = contracts.approved_suites()
    text = (f"Experiment run: {found['experiment_run_id']}\nRepository: {found['repository']}\nBase branch: {found['base_branch']}\n"
            f"Execution kinds: {', '.join(found['execution_kinds'])}\nSuites:\n" +
            ''.join(f"  {c['suite_lock_sha256']} {approved[c['suite_lock_sha256']]['benchmark_id']} {c['data_class']}\n"
                    for c in {c['suite_lock_sha256']: c for c in found['classes']}.values()) +
            'Files:\n' + ''.join(f'  {name}\n' for name in found['files']) + f"Report fingerprint: {found['report_fingerprint']}\n")
    if confirm is None:
        if not sys.stdin.isatty():
            raise ValueError('Authorization needs an interactive terminal')
        print(text)
        accepted = input('Type the experiment run id to authorize its publication: ').strip() == experiment_run_id
    else:
        accepted = confirm(text) is True
    if not accepted:
        raise ValueError('Authorization was not confirmed')
    value = {'schema_version': 1, **{k: found[k] for k in AUTHORIZED}, 'approved_by': approved_by,
             'approved_utc': datetime.datetime.now(datetime.timezone.utc).isoformat()}
    path = found['campaign'] / AUTHORIZATION
    contracts.write_text_atomic(path, json.dumps(value, indent=2, sort_keys=True) + '\n')
    return path


# Bundles of other experiments built from legal exports ----------------------------------------------------------------

_MARKERS = {}


def _norm(value):
    """NFKC, case-folded, without `-`, `_` and spaces: `LEGAL_smoke`, `legal-smoke` and the fullwidth letters compare equal."""
    import unicodedata
    return re.sub(r'[-_\s]', '', unicodedata.normalize('NFKC', str(value)).casefold())


def _markers():
    """Fail-closed wrapper: generic publication never crashes on the legal plugin's suite data."""
    try:
        return _load_markers()
    except Exception:
        raise ValueError('Approved legal suites cannot be read') from None


def _load_markers():
    """{'files', 'tasks', 'task', 'suites', 'ids', 'benchmarks'} of every approved suite: lock and pinned file digests, the digest of the
    `tasks` list of each routing and workload export, the digest of each single task's messages (any order, any subset), the
    digest of each routing export as the routing experiment loads it (a replay manifest's `suite_sha256`), and its matter ids
    normalised."""
    approved = contracts.approved_suites()
    key = tuple(sorted(approved))
    if key not in _MARKERS:
        from . import profiles
        from llm_eval.runner import load_suite as load_task_suite
        files, tasks, task, suites, ids = set(), set(), set(), set(), set()
        workloads = Path(__file__).resolve().parents[4] / 'experiments/legal-benchmark/workloads'
        for lock in sorted(workloads.glob('*/suite.lock.json')):
            if sha256_file(lock) not in approved:
                continue
            suite = contracts.load_suite(lock)
            files |= {suite['lock_sha256'], *(sha256_file(p) for p in contracts.pinned_files(lock))}
            ids |= {_norm(m['matter_id']) for m in suite['matters']['matters']}
            for export in (routing.route_tasks(suite), profiles.workload(lock)):
                tasks.add(digest(export['tasks']))
                task |= {digest(t['messages']) for t in export['tasks']}
            with tempfile.TemporaryDirectory(prefix='llm-eval-export-') as tmp:
                path = Path(tmp) / 'routing-suite.json'
                path.write_text(json.dumps(routing.route_tasks(suite)), encoding='utf-8')
                suites.add(digest(load_task_suite(path)))
        _MARKERS[key] = {'files': frozenset(files), 'tasks': frozenset(tasks), 'task': frozenset(task), 'suites': frozenset(suites),
                         'ids': frozenset(ids), 'benchmarks': frozenset(e['benchmark_id'] for e in approved.values())}
    return _MARKERS[key]


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for k, v in value.items():
            yield from _strings(k)
            yield from _strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from _strings(v)


def _pinned_paths(value):
    from llm_eval.orchestration.planner import PATH_KEYS
    if isinstance(value, dict):
        for k, v in value.items():
            if k in PATH_KEYS and isinstance(v, str):
                yield v
            else:
                yield from _pinned_paths(v)
    elif isinstance(value, list):
        for v in value:
            yield from _pinned_paths(v)


def _legal_file(path, markers):
    path = Path(path)
    if not path.is_file() or path.stat().st_size > 64 * 1024 * 1024:
        return False
    if sha256_file(path) in markers['files']:
        return True
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError, UnicodeDecodeError, RecursionError):
        return False
    if not isinstance(value, dict):
        return False
    tasks = value.get('tasks')
    if isinstance(tasks, list) and (digest(tasks) in markers['tasks'] or
                                    any(isinstance(t, dict) and (digest(t.get('messages')) in markers['task'] or _norm(t.get('id')) in markers['ids'])
                                        for t in tasks)):
        return True
    if value.get('suite_sha256') in markers['suites']:      # a replay manifest over an approved routing export
        return True
    rows = value.get('rows')
    return isinstance(rows, list) and any(isinstance(r, dict) and _norm(r.get('task_id')) in markers['ids'] for r in rows)


# Row keys the routing experiment writes itself (its rows carry `router_s`); they claim nothing.
ROUTING_ROW_KEYS = frozenset({'router_s'})
MANIFEST_KEYS = ('projection', 'canonical_bytes', 'execution_kinds', 'data_class', 'suite_lock_sha256', 'cohorts')
ROW_KEYS = frozenset({'suite_lock_sha256', 'family_id', 'review_status', *routing.ROUTE_KEYS}) - ROUTING_ROW_KEYS


def _benchmark_names(markers):
    """The benchmark names this plugin writes: the smoke mode's, the routing and workload exports' and every approved suite's
    `benchmark_id`."""
    from . import BENCHMARK, profiles
    return {BENCHMARK, 'legal-routing', profiles.WORKLOAD_BENCHMARK, *markers['benchmarks']}


def claims_name(name):
    """True when `name`, compared by `_norm`, is a benchmark name this plugin writes; a public legal benchmark (`LegalBench`)
    is not. Fails closed as `_markers` does."""
    return _claimed(name, _markers())


def _claimed(name, markers):
    return _norm(name) in {_norm(n) for n in _benchmark_names(markers)}


def _text_markers(markers):
    """Strings only this plugin writes into a report's text files: the experiment id (also part of every legal job and run id),
    the benchmark names of the approved suites and exports, and the names of the legal cohort metrics. Compared after NFKC normalisation and case folding."""
    from . import MANIFEST
    names = {MANIFEST['id'], *_benchmark_names(markers)}
    names |= {m for m in ROW_METRICS if m.startswith(('retrieval.', 'usable_memo_s', 'rate.selector_deferral'))}
    names |= {m for m in grading.METRICS if len(m) >= 12}
    return tuple(sorted(n.casefold() for n in names))


def _text_files(dest):
    """Every text file of a bundle, the raw archive decompressed; binary files (charts) are skipped."""
    import gzip
    for path in sorted(Path(dest).rglob('*')):
        if not path.is_file() or path.is_symlink():
            continue
        data = path.read_bytes()
        if path.suffix == '.gz':
            try:
                data = gzip.decompress(data)
            except (OSError, EOFError):
                continue
        try:
            yield data.decode('utf-8')
        except UnicodeDecodeError:
            continue


def claims_bundle(report, dest, manifest, resolved, records):
    """The class of the first legal mark a bundle of another experiment carries, or None: `manifest key`, `legal summary`,
    `input file`, `row key`, `benchmark name`, `task id`, `export task`, `text marker`, `text file`, `pinned input`.
    The class names the kind of mark, never text from the bundle. A category is no mark by itself, and a benchmark name is one
    only when it is a name this plugin writes (`claims_name`): a public legal benchmark under another experiment publishes."""
    if isinstance(manifest, dict) and set(MANIFEST_KEYS) & set(manifest):
        return 'manifest key'
    if (Path(dest) / 'legal-summary.json').exists():
        return 'legal summary'
    markers = _markers()
    resolved = resolved if isinstance(resolved, dict) else {}
    hashes = set(v for v in resolved.get('input_hashes') or [] if isinstance(v, str))
    for job in resolved.get('jobs') or []:
        if isinstance(job, dict):
            hashes |= {f.get('sha256') for f in job.get('input_files') or [] if isinstance(f, dict)}
    if hashes & markers['files']:
        return 'input file'
    for r in records:
        data = r.get('data') if isinstance(r, dict) and isinstance(r.get('data'), dict) else {}
        if ROW_KEYS & set(data):
            return 'row key'      # row and metadata keys only this plugin writes
        if any(_claimed(data[k], markers) for k in ('benchmark', 'benchmark_id') if k in data):
            return 'benchmark name'
        if r.get('record_type') == 'request' and _norm(data.get('task_id')) in markers['ids']:
            return 'task id'
        if isinstance(data.get('messages'), list) and digest(data['messages']) in markers['task']:
            return 'export task'
        for s in _strings(data):
            if '<<<BEGIN ' in s or '<<<END ' in s or (s.startswith('QUESTION ') and '\nOPERATIVE DATE ' in s):
                return 'text marker'
    import unicodedata
    found = _text_markers(markers)
    for text in _text_files(dest):
        folded = unicodedata.normalize('NFKC', text).casefold()
        if any(marker in folded for marker in found):
            return 'text file'
    report = Path(report).resolve()
    campaign = report.parent.parent.parent
    if report.parent.parent.name == 'experiments' and (campaign / 'plan.json').is_file():
        try:
            plan = json.loads((campaign / 'plan.json').read_text(encoding='utf-8'))
            jobs = [j for j in plan.get('jobs') or [] if isinstance(j, dict) and j.get('experiment_run_id') == report.parent.name]
        except (OSError, ValueError, UnicodeDecodeError, AttributeError, RecursionError):
            jobs = []
        for job in jobs:
            for path in _pinned_paths(job.get('parameters')):
                if _legal_file(path, markers):
                    return 'pinned input'
            if {f.get('sha256') for f in job.get('input_files') or [] if isinstance(f, dict)} & markers['files']:
                return 'pinned input'
    return None


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog='python -m llm_eval.experiments.legal_benchmark.reporting',
                                     description='Authorize the publication of one verified legal report')
    sub = parser.add_subparsers(dest='command', required=True)
    command = sub.add_parser('authorize', help='verify a report, show what would be published and record the authorization')
    command.add_argument('--campaign-dir', required=True, type=Path)
    command.add_argument('--experiment-run', required=True)
    command.add_argument('--approved-by', required=True, help='an identifier of the approving role')
    args = parser.parse_args(argv)
    try:
        print(authorize(args.campaign_dir, args.experiment_run, args.approved_by))
        return 0
    except ValueError as exc:
        print(f'{type(exc).__name__}: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
