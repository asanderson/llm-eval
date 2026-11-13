"""Bounded routing between retrieval recipes, the routing suite export and its replay manifest.

A selector chooses among allowlisted candidates (retrieval arms with one fixed generator) from route-time inputs only:
the question, the operative date, the venue and the count of evidence sources per kind of one matter of the candidate
view. Explicit insufficient-evidence and insufficient-authority labels defer without a generation request; a missing,
unusable or ineligible choice takes the safe deterministic fallback, or defers when the fallback is not eligible. A
served (`systemone`) selector is a local role on the job's endpoint allowlist. Router logs hold hashes, choices,
numbers and codes, never the messages.

The exported routing suite holds route-time inputs only; outcomes live in the replay manifest, and the legal lineage
(suite lock, scorer fingerprint, originating attempts, per-matter outcomes) in its local sidecar. Exports are limited to
approved fixture suites. A threshold is never a typed number: it comes from a pinned calibration record on a disjoint
calibration split. Numbers are `Fraction` or `math.fsum` results rounded to six decimals; every written list has a stated
order. The fixture replies used to test this module are fixtures, never measurements.
"""
from __future__ import annotations

import argparse
from collections import Counter
from fractions import Fraction
import json
import math
from pathlib import Path
import random
import statistics
import sys
import time

from llm_eval.common import digest, finite_number, sha256_file
from llm_eval.core.contracts import fields, identifier
from llm_eval.experiments.llm_routing.decision import decide, select
from llm_eval.experiments.llm_routing.evaluation import candidate_fingerprint, corpus_index, utility
from llm_eval.runner import load_suite as load_task_suite

from . import contracts, grading, profiles, retrieval

INSUFFICIENT = ('insufficient_evidence', 'insufficient_authority')
REASONS = ('router_error', 'missing_confidence', 'below_threshold', 'candidate_unavailable', 'ineligible_candidate',
           'no_eligible_candidate') + INSUFFICIENT
DEFERRALS = INSUFFICIENT + ('no_eligible_candidate',)
ROUTER_KEYS = {'fixed': ('kind', 'choice'), 'category': ('kind', 'default_category', 'keywords'), 'systemone': ('kind', 'instructions', 'criteria')}
POLICY_KEYS = ('category_models', 'fallback', 'abstain_threshold', 'require_confidence')
CALIBRATION_KEYS = ('calibration_file', 'suite', 'routed', 'fallback')      # routed / fallback: {'output_manifest'} of the two calibration attempts
CALIBRATION_LINEAGE_KEYS = ('selector_sha256', 'routed_output_manifest_sha256', 'fallback_output_manifest_sha256', 'generator_sha256')
CALIBRATION_RECORD_KEYS = ('schema_version', 'kind', 'abstain_threshold', 'split_id', 'suite_lock_sha256', 'families', 'risk_coverage',
                           *CALIBRATION_LINEAGE_KEYS)
RISK_KEYS = ('threshold', 'tasks', 'covered', 'coverage', 'errors', 'risk', 'unsafe_commitments', 'unsafe_rate')
CALIBRATION_ROW_KEYS = ('task_id', 'family_id', 'confidence', 'action', 'route_reason', 'quality_routed', 'quality_fallback')
CALIBRATION_KIND = 'legal-routing-calibration'
PROVENANCE_KIND = 'legal-routing-provenance'
PROVENANCE_KEYS = ('schema_version', 'kind', 'suite_lock_sha256', 'split_id', 'rubric_version', 'scorer_fingerprint', 'routing_suite_sha256',
                   'replay_manifest_sha256', 'generator_sha256', 'generator', 'attempts', 'outcomes', 'calibration')
ATTEMPT_KEYS = ('candidate', 'inference_job_id', 'inference_attempt_id', 'output_manifest_sha256', 'reviewer_fingerprint')
OUTCOME_KEYS = ('decision_correct', 'false_charge', 'dangerous_commitment', 'all_pass', 'critical_errors')
ROUTE_KEYS = ('routed', 'route_choice', 'route_selected', 'route_fallback', 'route_confidence', 'router_s', 'route_error_type')
DECISION_KEYS = ('matter_id', 'repetition', 'messages_sha256', 'choice', 'selected', 'action', 'selector_abstained', 'fallback_used',
                 'reason_codes', 'confidence', 'router_s')
# A recipe candidate of the `--candidates` file is exactly the fixed generator's identity (keys an `llm-routing` case accepts).
GENERATOR_FIELDS = ('model', 'model_revision', 'platform', 'backend_version', 'protocol', 'quantization', 'template_sha256', 'context_tokens')
CANDIDATE_KEYS = GENERATOR_FIELDS
OBJECTIVE_KEYS = ('quality_weight', 'latency_weight', 'cost_weight')
STRATEGY_FILE_KEYS = ('schema_version', 'objective', 'seed', 'switching', 'strategies')
SWITCHING_KEYS = ('mode', 'deployment_of', 'prompt_tokens')
CANDIDATE_ARMS = tuple(a for a in retrieval.ARMS if a != 'reference')      # the oracle arm is never a routing candidate


def _round(value):
    return None if value is None else round(float(value), 6)


def _ratio(numerator, denominator):
    return None if not denominator else _round(Fraction(numerator, denominator))


def _codes(found):
    return sorted(set(found), key=REASONS.index)


def _line(value):
    return ' '.join(str(value).split())


_jsonl = contracts.read_jsonl


def _write(path, value):
    contracts.write_text_atomic(path, json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + '\n')
    return sha256_file(path)


# Route-time inputs and the selector -----------------------------------------------------------------------------------

def route_messages(matter) -> list[dict]:
    """One user message with route-time inputs only. `matter` comes from the candidate view; no document text, label or
    outcome is read."""
    kinds = Counter(s['kind'] for s in matter['sources'] if s['role'] == 'evidence')
    counts = ', '.join(f'{kind}: {n}' for kind, n in sorted(kinds.items())) or 'none'
    lines = ['QUESTION ' + _line(matter['question']), 'OPERATIVE DATE ' + _line(matter['operative_date']), 'VENUE ' + _line(matter['venue']),
             'EVIDENCE SOURCES ' + counts]
    return [{'role': 'user', 'content': '\n'.join(lines)}]


def _label(value, path_keys):
    identifier(value)
    if value in path_keys:      # the planner would rewrite any string under such a key into a path, at any depth
        raise ValueError('A selector label cannot be a path key: ' + value)
    return value


def _text(value, name):
    if not isinstance(value, str) or not value.strip() or len(value) > contracts.MAX_TEXT:
        raise ValueError(f'{name} must be a nonempty string of at most {contracts.MAX_TEXT} characters')
    return value


def check_record(record) -> dict:
    """Closed-key validation of calibration record v1."""
    fields(record, CALIBRATION_RECORD_KEYS, CALIBRATION_RECORD_KEYS)
    if type(record['schema_version']) is not int or record['schema_version'] != 1 or record['kind'] != CALIBRATION_KIND:
        raise ValueError('Not a calibration record v1')
    finite_number(record['abstain_threshold'], 'abstain_threshold', 0, 1)
    if record['abstain_threshold'] <= 0:
        raise ValueError('A calibrated threshold is above 0')
    identifier(record['split_id'])
    if not isinstance(record['suite_lock_sha256'], str) or not contracts.HEX64.fullmatch(record['suite_lock_sha256']):
        raise ValueError('Calibration record needs the suite lock digest')
    if not isinstance(record['families'], list) or not record['families'] or record['families'] != sorted(set(record['families'])):
        raise ValueError('Calibration record needs its sorted families')
    for family in record['families']:
        identifier(family)
    if not isinstance(record['risk_coverage'], list) or not record['risk_coverage']:
        raise ValueError('Calibration record needs its risk-coverage table')
    for entry in record['risk_coverage']:
        fields(entry, RISK_KEYS, RISK_KEYS)
    if record['abstain_threshold'] not in [e['threshold'] for e in record['risk_coverage']]:
        raise ValueError('The calibration threshold is not one of its calibrated thresholds')
    for key in CALIBRATION_LINEAGE_KEYS:
        if not isinstance(record[key], str) or not contracts.HEX64.fullmatch(record[key]):
            raise ValueError('Calibration record needs its lineage digests: ' + key)
    return record


def validate_selector(selector, arms, roles, suite) -> None:
    """The `selector` parameter of a generation or workflow case, with its roles and its pinned calibration. Raises."""
    from llm_eval.orchestration.planner import PATH_KEYS
    fields(selector, ('router', 'policy', 'calibration'), ('router', 'policy'))
    router, policy, calibration = selector['router'], selector['policy'], selector.get('calibration')
    kind = router.get('kind') if isinstance(router, dict) else None
    if kind not in ROUTER_KEYS:
        raise ValueError('Unknown selector router kind: ' + str(kind))
    fields(router, ROUTER_KEYS[kind], ROUTER_KEYS[kind])
    if not isinstance(arms, list) or 'reference' in arms:
        raise ValueError('The reference arm cannot be routed')
    labels = []
    if kind == 'systemone':
        if 'selector' not in (roles or {}):
            raise ValueError('A served selector needs the selector role')
        _text(router['instructions'], 'instructions')
        criteria = router['criteria']
        if not isinstance(criteria, dict) or not criteria:
            raise ValueError('criteria must map labels to descriptions')
        for label, description in criteria.items():
            labels.append(label)
            _text(description, 'A criterion description')
        if set(INSUFFICIENT) - set(criteria):
            raise ValueError('criteria must hold both labels: ' + ', '.join(INSUFFICIENT))
    else:
        if 'selector' in (roles or {}):
            raise ValueError('Only a served selector has a selector role')
        rule = []
        if kind == 'fixed':
            rule.append(router['choice'])
        else:
            rule.append(router['default_category'])
            if not isinstance(router['keywords'], dict):
                raise ValueError('keywords must map labels to terms')
            for label, terms in router['keywords'].items():
                rule.append(label)
                if not isinstance(terms, list) or not terms:
                    raise ValueError('Keywords must be a nonempty list of terms')
                for term in terms:
                    _text(term, 'A keyword')
        if set(rule) & set(INSUFFICIENT):      # a rule that always defers some matters is not a selector decision
            raise ValueError('An in-process rule cannot use an insufficiency label')
        labels += rule
    fields(policy, POLICY_KEYS, ('fallback',))
    models = policy.get('category_models', {})
    if not isinstance(models, dict):
        raise ValueError('category_models must map labels to arms')
    for label, arm in models.items():
        labels.append(label)
        if label in INSUFFICIENT:
            raise ValueError('The insufficient labels defer and are never mapped: ' + label)
        if arm not in arms:
            raise ValueError('category_models must map labels to arms of this case: ' + str(label))
    for label in labels:
        _label(label, PATH_KEYS)
    if policy['fallback'] not in arms:
        raise ValueError('The fallback must be an arm of this case')
    threshold = policy.get('abstain_threshold', 0)
    finite_number(threshold, 'abstain_threshold', 0, 1)
    if type(policy.get('require_confidence', False)) is not bool:
        raise ValueError('require_confidence must be true or false')
    if policy.get('require_confidence') and kind != 'systemone':
        raise ValueError('require_confidence needs a selector that reports probabilities')
    if threshold > 0 and kind != 'systemone':
        raise ValueError('A threshold needs a selector that reports probabilities')
    if threshold > 0 and calibration is None:
        raise ValueError('A threshold needs a pinned calibration file')
    if calibration is not None:
        fields(calibration, CALIBRATION_KEYS, CALIBRATION_KEYS)
        if not all(isinstance(calibration[k], str) for k in ('calibration_file', 'suite')):
            raise ValueError('calibration_file and suite must be path strings')
        for side in ('routed', 'fallback'):
            fields(calibration[side], ['output_manifest'], ['output_manifest'])
            if not isinstance(calibration[side]['output_manifest'], str):
                raise ValueError('A calibration attempt is named by its output_manifest path')
        contracts.export_allowed(calibration['suite'])      # an approved fixture suite only: never a private or unreviewed split
        try:
            record, _ = contracts.read_json_strict(calibration['calibration_file'])
        except OSError:
            raise ValueError('Calibration file not found') from None
        check_record(record)
        if record['abstain_threshold'] != threshold:
            raise ValueError('Calibration record does not match the policy threshold')
        calibration_suite = contracts.load_suite(calibration['suite'])
        matters = calibration_suite['matters']['matters']
        if record['suite_lock_sha256'] != calibration_suite['lock_sha256'] or record['split_id'] != calibration_suite['lock']['split_id'] \
                or record['families'] != sorted({m['family_id'] for m in matters}) or any(e['tasks'] != len(matters) for e in record['risk_coverage']):
            raise ValueError('Calibration record does not match its suite')
        if record['selector_sha256'] != selector_identity(selector, roles):
            raise ValueError('Calibration record belongs to another selector')
        if 'generator' in (roles or {}) and record['generator_sha256'] != profiles.bound_digest(roles['generator']):
            raise ValueError('Calibration record belongs to another generator')
        check_threshold(record, suite, calibration_suite)
        # The record must be exactly what the two pinned calibration attempts give: a hand-written record is refused.
        routed, fallback = (Path(calibration[side]['output_manifest']).parent.parent for side in ('routed', 'fallback'))
        try:
            rows = calibration_rows(routed, fallback, policy['fallback'])
            lineage = calibration_lineage(routed, fallback, policy['fallback'])
            if lineage_suite(routed) != calibration_suite['lock_sha256']:
                raise ValueError('the calibration attempts ran on another suite')
            recomputed = calibrate(rows, [e['threshold'] for e in record['risk_coverage']], calibration_suite, lineage)
        except (ValueError, OSError, KeyError) as exc:
            raise ValueError('Calibration record does not follow from its calibration attempts: ' + (str(exc) if isinstance(exc, ValueError)
                                                                                                    else type(exc).__name__)) from None
        if recomputed != record:
            raise ValueError('Calibration record does not follow from its calibration attempts')


def selector_digest(selector, roles, input_files=()) -> str:
    """Identity of a selector: its router rule (all of it for an in-process rule; kind, criteria and instructions for a
    served one), its policy, the served role's profile digest and the recorded digest of its calibration file."""
    recorded = {f['path']: f['sha256'] for f in input_files}
    calibration = selector.get('calibration')
    role = (roles or {}).get('selector')
    return digest({'router': {k: selector['router'][k] for k in ROUTER_KEYS[selector['router']['kind']]}, 'policy': selector['policy'],
                   'selector_role': profiles.profile_digest(role, input_files) if role else None,
                   'calibration_sha256': recorded.get(calibration['calibration_file']) if calibration else None})


def selector_identity(selector, roles) -> str:
    """The selector a threshold was calibrated for: its router rule, its policy without the threshold settings, and the
    served role's profile digest. A calibration record carries it, and a job may use the record only with that selector."""
    role = (roles or {}).get('selector')
    policy = {k: v for k, v in selector['policy'].items() if k not in ('abstain_threshold', 'require_confidence')}
    return digest({'router': {k: selector['router'][k] for k in ROUTER_KEYS[selector['router']['kind']]}, 'policy': policy,
                   'selector_role': profiles.profile_digest(role) if role else None})


def router_for(selector, roles) -> dict:
    """The `decide` router: the in-process rule itself, or the served selector role's model and local endpoint."""
    router = selector['router']
    if router['kind'] != 'systemone':
        return router
    role = roles['selector']
    return {'kind': 'systemone', 'model': role['model'], 'endpoint': role['endpoint'], 'instructions': router['instructions'],
            'criteria': router['criteria'], 'timeout_s': role['timeout_s'], 'api_key_env': role.get('api_key_env')}


def route(router, messages, policy, candidates, eligible, allowed=frozenset()) -> dict:
    """One bounded routing decision. `candidates` are the allowlisted ids, `eligible` the ids allowed for this task.
    `selector_abstained` says that the selector did not commit; `error_type` names a router exception class."""
    if router.get('kind') == 'systemone':
        profiles.require_allowed(router['endpoint'], allowed)      # `decide` opens its own connection: this check puts it under the allowlist
    codes, selected, action, abstained, error_type, confidence, choice = [], None, 'route', False, None, None, None
    started = time.perf_counter()
    try:
        decision = decide(router, messages)
    except Exception as exc:      # the class name only: a message can echo a prompt
        decision, error_type = None, type(exc).__name__
        codes.append('router_error')
    router_s = decision['router_s'] if decision else time.perf_counter() - started
    if decision is not None:
        choice, probabilities = decision['choice'], decision.get('probabilities')
        confidence = probabilities.get(choice) if probabilities else None
        if choice in INSUFFICIENT:
            action, abstained = 'defer', True
            codes.append(choice)
        elif not probabilities and (policy.get('require_confidence') or policy.get('abstain_threshold', 0) > 0):
            abstained = True      # `select` would route a reply without probabilities as if it had passed the threshold
            codes.append('missing_confidence')
        else:
            selected = select(decision, policy, candidates)
            if selected is None:
                if probabilities and probabilities[choice] < policy.get('abstain_threshold', 0):
                    abstained = True
                    codes.append('below_threshold')
                else:
                    codes.append('candidate_unavailable')
            elif selected not in eligible:
                codes.append('ineligible_candidate')
                selected = None
    fallback = False
    if selected is None and action != 'defer':
        if policy.get('fallback') in candidates and policy.get('fallback') in eligible:
            selected, fallback = policy['fallback'], True
        else:
            action = 'defer'
            codes.append('no_eligible_candidate')
    return {'choice': choice, 'selected': selected, 'action': action, 'selector_abstained': abstained, 'fallback_used': fallback,
            'reason_codes': _codes(codes), 'router_s': router_s, 'confidence': confidence, 'error_type': error_type}


def decision_record(matter, repetition, messages, result) -> dict:
    """One line of `local/route-decisions.jsonl`: hashes, choices, numbers and codes, never the messages."""
    return {'matter_id': matter['matter_id'], 'repetition': repetition, 'messages_sha256': digest(messages),
            **{k: result[k] for k in DECISION_KEYS if k in result}, 'router_s': _round(result['router_s']), 'confidence': _round(result['confidence'])}


# Outcomes -------------------------------------------------------------------------------------------------------------

def outcome(record) -> dict:
    """The decision outcome of one score-detail record: correctness against the gold recommendation, the two unsafe
    commitments, the all-pass rule of `grading.aggregate` and the count of critical codes. `None` for a record that was
    not scored, and `decision_correct` is `None` for a selector deferral that no eligible candidate caused."""
    if record['grading_status'] != 'scored':
        return {k: None for k in OUTCOME_KEYS}
    choice, gold = record['choice'], record['gold_recommendation']
    correct = None if record.get('selector_deferral') == 'no_eligible_candidate' or choice is None or gold is None else choice == gold
    return {'decision_correct': correct, 'false_charge': choice == 'charge' and gold in ('decline', 'defer'),
            'dangerous_commitment': choice in ('charge', 'decline') and gold == 'defer',
            'all_pass': grading.all_pass(record), 'critical_errors': len(grading.standing_critical(record))}


def _combined(outcomes):
    """Repetitions of one task: correct and all-pass only when every repetition is, unsafe when any repetition is, critical
    codes summed; unknown when any repetition is unknown."""
    if not outcomes or any(o['decision_correct'] is None and o['all_pass'] is None for o in outcomes):
        return {k: None for k in OUTCOME_KEYS}

    def every(key):
        values = [o[key] for o in outcomes]
        return None if any(v is None for v in values) else all(values)

    def some(key):
        values = [o[key] for o in outcomes]
        return None if any(v is None for v in values) else any(values)
    critical = [o['critical_errors'] for o in outcomes]
    return {'decision_correct': every('decision_correct'), 'false_charge': some('false_charge'), 'dangerous_commitment': some('dangerous_commitment'),
            'all_pass': every('all_pass'), 'critical_errors': None if any(c is None for c in critical) else sum(critical)}


def _quality(details):
    """Mean over repetitions of criteria_passed / criteria_total, as a Fraction; None when no repetition was scored."""
    scored = [d for d in details if d['grading_status'] == 'scored']
    if not scored:
        return None
    return sum((Fraction(sum(v is True for v in d['criteria'].values()), len(d['criteria'])) for d in scored), Fraction(0)) / len(scored)


def _latency(row):
    for key in ('usable_memo_s', 'elapsed_s'):
        value = row.get(key) if row else None
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return value
    return None


def _pinned(attempt_dir, suite=None):
    """One generation, workflow or score attempt, read only through the output manifest it pins (or, for a score attempt,
    the manifest it scored): the manifest's identity, files and rows are checked as `grading._manifest` checks them, and
    the outputs are graded as the `score` mode grades them. The attempt's own `score-detail.jsonl` is never read."""
    attempt = Path(attempt_dir)
    metadata, _ = contracts.read_json_strict(attempt / 'metadata.json')
    if metadata.get('experiment') != 'legal-benchmark' or metadata.get('mode') not in ('generation', 'workflow', 'score'):
        raise ValueError('Not a scored legal generation, workflow or score attempt')
    job, _ = contracts.read_json_strict(attempt / 'job.json')
    if metadata['mode'] == 'score':
        parameters = {k: job['parameters'][k] for k in ('output_manifest', 'review_file', 'review_key') if k in job['parameters']}
    else:
        parameters = {'output_manifest': str(attempt / 'local/output-manifest.json')}
    source_job, _ = contracts.read_json_strict(Path(parameters['output_manifest']).parent.parent / 'job.json')
    suite = suite if suite is not None else contracts.load_suite(source_job['parameters']['suite'])
    manifest, source, manifest_sha, source_metadata, lineage, rows, details = grading.score_records(parameters, suite)
    if [(r['task_id'], r['arm'], r['repetition']) for r in rows] != [(d['matter_id'], d['arm'], d['repetition']) for d in details]:
        raise ValueError('The attempt files disagree on their rows')
    timings = {(r['task_id'], r['arm'], r['repetition']): r for r in _jsonl(source / 'requests.jsonl')}      # pinned by the manifest
    role = (source_job['parameters'].get('roles') or {}).get('generator') or {}
    return {'job': source_job, 'metadata': source_metadata, 'rows': rows, 'details': details, 'timings': timings,
            'lineage': {'inference_job_id': lineage['inference_job_id'], 'inference_attempt_id': lineage['inference_attempt_id'],
                        'output_manifest_sha256': manifest_sha, 'reviewer_fingerprint': lineage['reviewer_fingerprint'],
                        'scorer_fingerprint': lineage['scorer_fingerprint'],
                        'suite_lock_sha256': suite['lock_sha256'],
                        'generator_sha256': ((source_metadata.get('roles') or {}).get('generator') or {}).get('profile_sha256'),
                        'generator': {k: role.get(k) for k in GENERATOR_FIELDS}}}


def rows_by_candidate(attempt_dir, by='arm', suite=None) -> dict:
    """{candidate id: {'rows', 'outcomes', 'lineage'}} of one generation, workflow or score attempt, from its pinned outputs.
    The candidate id is the row's arm (a recipe id); the oracle `reference` arm is never a candidate and is skipped."""
    if by != 'arm':
        raise ValueError('Unsupported candidate grouping: ' + str(by))
    attempt = Path(attempt_dir)
    if (attempt / 'requests.jsonl').is_file() and any(r.get('arm') == 'routed' for r in _jsonl(attempt / 'requests.jsonl')):
        raise ValueError('A routed attempt is not a candidate')
    pinned = _pinned(attempt, suite)
    if pinned['job']['parameters'].get('selector') is not None:
        raise ValueError('A routed attempt is not a candidate')
    found = {}
    for row, d in zip(pinned['rows'], pinned['details']):
        if row['arm'] == 'reference':
            continue
        entry = found.setdefault(row['arm'], {'rows': [], 'details': {}, 'lineage': dict(pinned['lineage'])})
        scored = d['grading_status'] == 'scored'
        timed = pinned['timings'].get((row['task_id'], row['arm'], row['repetition']))
        entry['rows'].append({'task_id': row['task_id'], 'repetition': row['repetition'], 'status': row['status'], 'grading_status': d['grading_status'],
                              'criteria_passed': sum(v is True for v in d['criteria'].values()) if scored else None,
                              'criteria_total': len(d['criteria']), 'usable_memo_s': timed.get('usable_memo_s') if timed else None,
                              'elapsed_s': timed.get('elapsed_s') if timed else None})
        entry['details'].setdefault(row['task_id'], []).append(d)
    for entry in found.values():
        entry['outcomes'] = {task: _combined([outcome(d) for d in records]) for task, records in sorted(entry.pop('details').items())}
    return {k: found[k] for k in sorted(found)}


# Routing suite, replay manifest and sidecar ---------------------------------------------------------------------------

def route_tasks(suite) -> dict:
    """The routing suite of a legal suite: route-time messages only, tasks in matter-id order. Nothing is written."""
    view = contracts.candidate_view(suite)
    return {'benchmark': 'legal-routing', 'category': 'legal',
            'tasks': [{'id': m['matter_id'], 'category': 'legal', 'messages': route_messages(m)}
                      for m in sorted(view['matters']['matters'], key=lambda m: m['matter_id'])]}


def export_suite(lock_path, path) -> str:
    """Write the routing suite of an approved fixture suite; returns `common.digest` of the suite as `runner.load_suite`
    reads it (the replay contract's `suite_sha256`)."""
    contracts.export_allowed(lock_path)
    _write(path, route_tasks(contracts.load_suite(lock_path)))
    return digest(load_task_suite(path))


def build_replay(task_suite, candidates, scored) -> dict:
    """The replay manifest of the routing experiment: `suite_sha256`, `candidate_fingerprints` and one row per task and
    candidate that was scored, sorted by (task_id, candidate). A scored row without a valid output has quality 0.0."""
    if 'reference' in candidates:
        raise ValueError('The reference arm is not a routing candidate')
    rows = []
    for cid in sorted(candidates):
        entry = scored.get(cid)
        if entry is None:
            continue
        for task in task_suite['tasks']:
            reps = [x for x in entry['rows'] if x['task_id'] == task['id'] and x['grading_status'] == 'scored']
            if not reps:
                continue
            quality = sum((Fraction(x['criteria_passed'], x['criteria_total']) for x in reps), Fraction(0)) / len(reps)
            latencies = [_latency(x) for x in reps]
            latency = None if any(v is None for v in latencies) else _round(math.fsum(latencies) / len(latencies))
            rows.append({'task_id': task['id'], 'candidate': cid, 'quality': _round(quality), 'latency_s': latency, 'cost_usd': 0})
    rows.sort(key=lambda x: (x['task_id'], x['candidate']))
    return {'suite_sha256': digest(task_suite), 'candidate_fingerprints': {cid: candidate_fingerprint(candidates[cid]) for cid in sorted(candidates)},
            'rows': rows}


def _check_provenance(provenance):
    fields(provenance, PROVENANCE_KEYS, PROVENANCE_KEYS)
    if provenance['schema_version'] != 1 or provenance['kind'] != PROVENANCE_KIND:
        raise ValueError('Not a legal routing provenance v1')
    for a in provenance['attempts']:
        fields(a, ATTEMPT_KEYS, ATTEMPT_KEYS)
    for o in provenance['outcomes']:
        fields(o, ('task_id', 'candidate', *OUTCOME_KEYS), ('task_id', 'candidate', *OUTCOME_KEYS))
    fields(provenance['generator'], GENERATOR_FIELDS, GENERATOR_FIELDS)
    calibration = provenance['calibration']
    if calibration is not None and not (isinstance(calibration, str) and contracts.HEX64.fullmatch(calibration)):
        raise ValueError('The replay calibration must be null or the digest of a calibration record')
    return provenance


def write_provenance(path, provenance) -> None:
    """The local sidecar of a replay manifest (`<manifest stem>.provenance.json`), canonical LF JSON."""
    _check_provenance(provenance)
    _write(path, provenance)


def sidecar(manifest_path):
    path = Path(manifest_path)
    return path.with_name(path.stem + '.provenance.json')


def _generator_matches(candidates, generator):
    for cid in sorted(candidates):
        for key in GENERATOR_FIELDS:
            if candidates[cid].get(key) != generator.get(key):
                raise ValueError(f'Candidate does not match the fixed generator: {cid}.{key}')


def _in_range(row):
    def number(value, high=None):
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0 and (high is None or value <= high)
    return number(row.get('quality'), 1) and (row.get('latency_s') is None or number(row['latency_s'])) and number(row.get('cost_usd'))


def verify_replay(manifest, provenance, task_suite, candidates, suite, attempts=None) -> None:
    """Everything the routing experiment does not check: orphan rows, values out of range, stale scores, outcomes that do
    not match the rows, candidates that are not the fixed generator and the originating attempts. With `attempts`, the
    manifest and the sidecar must equal a fresh build from those attempts' pinned outputs."""
    _check_provenance(provenance)
    if manifest.get('suite_sha256') != digest(task_suite) or provenance['routing_suite_sha256'] != digest(task_suite):
        raise ValueError('Replay suite hash mismatch')
    fingerprints = manifest.get('candidate_fingerprints') or {}
    if set(fingerprints) != set(candidates) or any(fingerprints[c] != candidate_fingerprint(candidates[c]) for c in candidates):
        raise ValueError('Replay candidate fingerprint mismatch')
    tasks = {t['id'] for t in task_suite['tasks']}
    for row in manifest['rows']:
        if row.get('task_id') not in tasks or row.get('candidate') not in candidates:
            raise ValueError('Orphan replay row')
    corpus_index(manifest, task_suite)      # the routing experiment's own duplicate rule
    keys = [(o['task_id'], o['candidate']) for o in provenance['outcomes']]
    if len(set(keys)) != len(keys):
        raise ValueError('Duplicate replay outcome')
    if not all(_in_range(row) for row in manifest['rows']):
        raise ValueError('Replay row values out of range')
    if provenance['scorer_fingerprint'] != grading.scorer_fingerprint(suite) or provenance['suite_lock_sha256'] != suite['lock_sha256'] \
            or provenance['replay_manifest_sha256'] != digest(manifest):
        raise ValueError('Stale replay scores')
    if set(keys) != {(row['task_id'], row['candidate']) for row in manifest['rows']}:
        raise ValueError('Replay outcomes do not match the replay rows')
    _generator_matches(candidates, provenance['generator'])
    attempted = {a['candidate'] for a in provenance['attempts']}
    if any(row['candidate'] not in attempted for row in manifest['rows']):
        raise ValueError('Replay row without an originating attempt')
    if attempts is not None:
        scored = _scored(attempts, suite, candidates)
        rebuilt = build_replay(task_suite, candidates, scored)
        if rebuilt != manifest or _provenance(suite, task_suite, rebuilt, scored, provenance['calibration']) != provenance:
            raise ValueError('Replay does not follow from its source attempts')


def _scored(attempts, suite, candidates):
    """{candidate: rows_by_candidate entry} from the pinned outputs of source attempts on `suite`, with one fixed generator
    that every candidate names exactly."""
    entries = []
    for attempt in attempts:
        metadata, _ = contracts.read_json_strict(Path(attempt) / 'metadata.json')
        if metadata.get('suite_lock_sha256') != suite['lock_sha256'] or metadata.get('scorer_fingerprint') != grading.scorer_fingerprint(suite):
            raise ValueError('Stale replay scores')
        entries.append(rows_by_candidate(attempt, suite=suite))
    generators = {entry['lineage']['generator_sha256'] for found in entries for entry in found.values()}
    if len(generators) != 1 or None in generators:
        raise ValueError('Replay attempts do not share one fixed generator')
    scored = {}
    for found in entries:
        for cid, entry in found.items():
            if cid not in candidates:
                continue
            if cid in scored:
                raise ValueError('Duplicate replay outcome')
            scored[cid] = entry
    missing = sorted(set(candidates) - set(scored))
    if missing:
        raise ValueError('No source attempt holds candidate: ' + missing[0])
    _generator_matches(candidates, next(iter(scored.values()))['lineage']['generator'])
    return scored


def _outcome_rows(scored):
    return sorted(({'task_id': task, 'candidate': cid, **o} for cid, entry in scored.items() for task, o in entry['outcomes'].items()),
                  key=lambda o: (o['task_id'], o['candidate']))


def _provenance(suite, task_suite, manifest, scored, calibration=None):
    lineage = next(iter(scored.values()))['lineage']
    return {'schema_version': 1, 'kind': PROVENANCE_KIND, 'suite_lock_sha256': suite['lock_sha256'], 'split_id': suite['lock']['split_id'],
            'rubric_version': suite['rubric'].get('rubric_version'), 'scorer_fingerprint': grading.scorer_fingerprint(suite),
            'routing_suite_sha256': digest(task_suite), 'replay_manifest_sha256': digest(manifest),
            'generator_sha256': lineage['generator_sha256'], 'generator': dict(lineage['generator']),
            'attempts': [{'candidate': cid, **{k: scored[cid]['lineage'][k] for k in ATTEMPT_KEYS[1:]}} for cid in sorted(scored)],
            'outcomes': _outcome_rows(scored), 'calibration': calibration}


# Calibration ----------------------------------------------------------------------------------------------------------

def _thresholds(thresholds):
    if not isinstance(thresholds, (list, tuple)) or not thresholds:
        raise ValueError('Name at least one threshold')
    for t in thresholds:
        if isinstance(t, bool) or not isinstance(t, (int, float)) or not math.isfinite(t) or not 0 < t <= 1:
            raise ValueError('Thresholds are numbers above 0 and at most 1')
    return sorted(set(thresholds))


def _covered(row, threshold):
    """The one coverage rule of `risk_coverage`, `calibrate` and `evaluate`: a routed commitment (never a deferral) whose
    confidence reaches the threshold."""
    return row.get('action', 'route') != 'defer' and row['confidence'] is not None and row['confidence'] >= threshold


def risk_coverage(rows, thresholds) -> list[dict]:
    """Risk versus coverage of a probabilistic selector, one entry per threshold in ascending order."""
    found = []
    for t in sorted(set(thresholds)):
        covered = [r for r in rows if _covered(r, t)]
        errors = sum(r['decision_correct'] is False for r in covered)
        unsafe = sum(bool(r['false_charge']) or bool(r['dangerous_commitment']) for r in covered)
        found.append({'threshold': t, 'tasks': len(rows), 'covered': len(covered), 'coverage': _ratio(len(covered), len(rows)), 'errors': errors,
                      'risk': _ratio(errors, len(covered)), 'unsafe_commitments': unsafe, 'unsafe_rate': _ratio(unsafe, len(covered))})
    return found


def _decimal(value):
    """A six-decimal quality as an exact decimal fraction (never a binary float sum); None counts as 0."""
    return Fraction(0) if value is None else Fraction(str(value))


def calibrate(rows, thresholds, suite, lineage) -> dict:
    """Calibration record v1: the threshold with the highest total quality, where a row counts its routed quality when it
    is covered or when the routed run deferred it (`route` defers at every threshold), and its fallback quality otherwise;
    ties go to the lower threshold. `lineage` names the selector, the two output manifests and the generator."""
    ordered = _thresholds(thresholds)
    if not rows or any(set(CALIBRATION_ROW_KEYS) - set(r) for r in rows):
        raise ValueError('Calibration rows need: ' + ', '.join(CALIBRATION_ROW_KEYS))
    fields(lineage, CALIBRATION_LINEAGE_KEYS, CALIBRATION_LINEAGE_KEYS)
    best, total = None, None
    for t in ordered:
        value = sum((_decimal(r['quality_routed'] if r['action'] == 'defer' or _covered(r, t) else r['quality_fallback']) for r in rows), Fraction(0))
        if total is None or value > total:
            best, total = t, value
    return {'schema_version': 1, 'kind': CALIBRATION_KIND, 'abstain_threshold': best, 'split_id': suite['lock']['split_id'],
            'suite_lock_sha256': suite['lock_sha256'], 'families': sorted({r['family_id'] for r in rows}), 'risk_coverage': risk_coverage(rows, ordered),
            **{k: lineage[k] for k in CALIBRATION_LINEAGE_KEYS}}


def write_calibration(record, path) -> str:
    check_record(record)
    return _write(path, record)


def check_threshold(calibration, evaluation_suite, calibration_suite) -> None:
    """A threshold may not come from evaluation data: other lock, other split, no family of the evaluation suite, and
    the split audit of the pinned calibration suite finds no shared family, amendment pair or near duplicate."""
    families = {m['family_id'] for m in evaluation_suite['matters']['matters']}
    audit = retrieval.audit_splits(calibration_suite, evaluation_suite)
    if calibration_suite['lock_sha256'] == evaluation_suite['lock_sha256'] or calibration['suite_lock_sha256'] == evaluation_suite['lock_sha256'] \
            or calibration_suite['lock']['split_id'] == evaluation_suite['lock']['split_id'] or calibration['split_id'] == evaluation_suite['lock']['split_id'] \
            or set(calibration['families']) & families or audit['shared_families'] or audit['shared_amendment_pairs'] or audit['near_duplicates']:
        raise ValueError('Threshold was calibrated on evaluation data')


def _per_task(pinned, arm):
    """{task_id: (row list, quality Fraction or None, combined outcome)} of the pinned rows of `arm`, rows and score-detail
    records matched by (task, arm, repetition)."""
    found = {}
    for row, d in zip(pinned['rows'], pinned['details']):
        if (row['task_id'], row['arm'], row['repetition']) != (d['matter_id'], d['arm'], d['repetition']):
            raise ValueError('The attempt files disagree on their rows')
        if row['arm'] == arm:
            found.setdefault(row['task_id'], ([], []))
            found[row['task_id']][0].append(row)
            found[row['task_id']][1].append(d)
    return {task: (rs, _quality(ds), _combined([outcome(d) for d in ds])) for task, (rs, ds) in found.items()}


def _calibration_pair(routed_attempt, fallback_attempt, fallback_arm):
    routed, fallback = _pinned(routed_attempt), _pinned(fallback_attempt)
    selector = routed['job']['parameters'].get('selector')
    if selector is None or fallback['job']['parameters'].get('selector') is not None:
        raise ValueError('Calibration needs a routed attempt and an unrouted attempt of the fallback arm')
    if selector['policy'].get('abstain_threshold', 0) != 0 or selector['policy'].get('require_confidence', False):
        # With a threshold, a below-threshold row already took the fallback: its "routed" quality is no counterfactual.
        raise ValueError('The routed calibration attempt must run without a threshold or required confidence')
    if fallback_arm != selector['policy']['fallback']:
        raise ValueError('The fallback attempt must run the routed policy fallback')
    if fallback_arm not in (fallback['job']['parameters'].get('arms') or []):
        raise ValueError('Calibration needs a routed attempt and an unrouted attempt of the fallback arm')
    a, b = routed['lineage'], fallback['lineage']
    if a['suite_lock_sha256'] != b['suite_lock_sha256'] or a['scorer_fingerprint'] != b['scorer_fingerprint'] \
            or a['generator_sha256'] is None or a['generator_sha256'] != b['generator_sha256']:
        raise ValueError('Calibration attempts are not comparable')
    return routed, fallback


def calibration_lineage(routed_attempt, fallback_attempt, fallback_arm) -> dict:
    """The lineage a calibration record carries: the routed job's selector identity, both output manifest digests and the
    generator's profile digest."""
    routed, fallback = _calibration_pair(routed_attempt, fallback_attempt, fallback_arm)
    parameters = routed['job']['parameters']
    return {'selector_sha256': selector_identity(parameters['selector'], parameters['roles']),
            'routed_output_manifest_sha256': routed['lineage']['output_manifest_sha256'],
            'fallback_output_manifest_sha256': fallback['lineage']['output_manifest_sha256'],
            'generator_sha256': profiles.profile_digest(parameters['roles']['generator'], routed['job'].get('input_files', ()))}


def lineage_suite(attempt) -> str:
    """The suite lock digest the pinned outputs of a calibration attempt were scored on."""
    return _pinned(attempt)['lineage']['suite_lock_sha256']


def calibration_rows(routed_attempt, fallback_attempt, fallback_arm) -> list[dict]:
    """One row per task (task-id order) of a routed attempt and an unrouted attempt of the routed policy's fallback arm on
    the same calibration suite, from their pinned outputs. `action` and `route_reason` say whether the routed run deferred
    the task. With repetitions, `confidence` is the lowest one (None if any is None)."""
    routed, fallback = _calibration_pair(routed_attempt, fallback_attempt, fallback_arm)
    a, b = _per_task(routed, 'routed'), _per_task(fallback, fallback_arm)
    if set(a) != set(b):
        raise ValueError('Calibration attempts are not comparable')
    found = []
    for task in sorted(a):
        rows, quality, result = a[task]
        confidences = [r.get('route_confidence') for r in rows]
        deferred = all(r['category'] == 'routed-defer' for r in rows)
        reason = next((c for r in rows for c in r['reason_codes'] if c in DEFERRALS), None) if deferred else None
        found.append({'task_id': task, 'family_id': rows[0]['family_id'],
                      'confidence': None if any(c is None for c in confidences) else min(confidences),
                      'action': 'defer' if deferred else 'route', 'route_reason': reason,
                      'quality_routed': _round(quality) if quality is not None else None, 'quality_fallback': _round(b[task][1]) if b[task][1] is not None else None,
                      **{k: result[k] for k in ('decision_correct', 'false_charge', 'dangerous_commitment', 'critical_errors')}})
    return found


# Strategy comparison --------------------------------------------------------------------------------------------------

def _objective(objective):
    fields(objective, OBJECTIVE_KEYS)
    for key, value in objective.items():
        finite_number(value, key, 0)
    return {'quality_weight': objective.get('quality_weight', 1), 'latency_weight': objective.get('latency_weight', 0),
            'cost_weight': objective.get('cost_weight', 0)}


def _strategy(strategy, candidates):
    name = strategy.get('name') if isinstance(strategy, dict) else None
    if isinstance(name, str) and name.startswith('fixed:'):
        fields(strategy, ('name',), ('name',))
        if name[len('fixed:'):] == 'reference':
            raise ValueError('The reference arm is not a routing candidate')
        if name[len('fixed:'):] not in candidates:
            raise ValueError('Unknown fixed candidate: ' + name)
    elif name == 'category':
        fields(strategy, ('name', 'router', 'policy'), ('name', 'router', 'policy'))
        if strategy['router'].get('kind') != 'category':
            raise ValueError('A category strategy has a category router')
    elif name == 'random-matched':
        fields(strategy, ('name', 'match'), ('name', 'match'))
    elif name == 'selector':
        fields(strategy, ('name', 'decisions', 'thresholds'), ('name', 'decisions'))
        if not isinstance(strategy['decisions'], dict):
            raise ValueError('Selector decisions map task ids to route results')
        if any(isinstance(d, dict) and d.get('selected') == 'reference' for d in strategy['decisions'].values()):
            raise ValueError('The reference arm is not a routing candidate')
    else:
        raise ValueError('Unknown strategy: ' + str(name))
    return strategy


def _selections(strategy, tasks, candidates):
    """[(task_id, route-like result)] of a deterministic strategy, in task-id order."""
    if strategy['name'].startswith('fixed:'):
        chosen = strategy['name'][len('fixed:'):]
        return [(t['id'], {'action': 'route', 'selected': chosen, 'fallback_used': False, 'confidence': None, 'router_s': None}) for t in tasks]
    if strategy['name'] == 'category':
        pool = {c: {} for c in candidates}
        return [(t['id'], route(strategy['router'], t['messages'], strategy['policy'], pool, list(candidates))) for t in tasks]
    decisions = strategy['decisions']
    if set(decisions) != {t['id'] for t in tasks}:
        raise ValueError('Selector decisions do not cover the tasks')
    return [(t['id'], decisions[t['id']]) for t in tasks]


DEFERRAL_ROW = {'quality': 0.0, 'latency_s': None, 'cost_usd': 0, 'deferral': True}
DEFERRAL_OUTCOME = {'false_charge': False, 'dangerous_commitment': False, 'all_pass': False}


def _latencies(rows):
    return [r.get('latency_s') for r in rows if not r.get('deferral')]


def _utility(row, objective):
    return utility(row.get('quality'), 0.0 if row.get('deferral') else row.get('latency_s'), row.get('cost_usd'), objective)


METRIC_KEYS = ('covered', 'missing', 'mean_quality', 'mean_latency_s', 'mean_utility', 'router_s_median', 'fallbacks', 'abstentions', 'switches',
               'cold_switches', 'reprefill_tokens', 'unsafe_commitments', 'false_charge_rate', 'all_pass_rate', 'risk_coverage')
COMMON_KEYS = ('common_tasks', 'common_mean_quality', 'common_mean_latency_s', 'common_mean_utility')


def _empty(name, tasks):
    return {'strategy': name, 'tasks': len(tasks), **{k: None for k in METRIC_KEYS}, '_covered': None}


def _mean(values):
    values = list(values)
    return None if not values or any(v is None for v in values) else _round(math.fsum(values) / len(values))


def _metrics(name, tasks, selections, index, objective, switching, outcomes, thresholds=None):
    covered, missing, abstentions, fallbacks, timings, chain = [], 0, 0, 0, [], []
    for task_id, result in selections:
        if result.get('router_s') is not None:
            timings.append(result['router_s'])
        if result.get('fallback_used'):
            fallbacks += 1
        if result.get('action') == 'defer' or result.get('selected') is None:
            # A deferral is a covered task with quality 0 (its decision risk is reported separately): a strategy cannot raise
            # its means by deferring hard tasks. It ran no generation, so it has no latency.
            abstentions += 1
            covered.append((task_id, None, DEFERRAL_ROW))
            continue
        chain.append((task_id, result['selected']))
        row = index.get((task_id, result['selected']))
        if row is None:
            missing += 1
        else:
            covered.append((task_id, result['selected'], row))

    mean = _mean
    found = {'strategy': name, 'tasks': len(tasks), 'covered': len(covered), 'missing': missing,
             'mean_quality': mean(row.get('quality') for _, _, row in covered), 'mean_latency_s': mean(_latencies([row for _, _, row in covered])),
             'mean_utility': mean(_utility(row, objective) for _, _, row in covered),
             'router_s_median': _round(statistics.median(timings)) if timings else None, 'fallbacks': fallbacks, 'abstentions': abstentions,
             'switches': None, 'cold_switches': None, 'reprefill_tokens': None, 'unsafe_commitments': None, 'false_charge_rate': None,
             'all_pass_rate': None, 'risk_coverage': None, '_covered': covered}
    if switching is not None:
        deployments = switching['deployment_of']
        switched = [chain[i][0] for i in range(1, len(chain)) if deployments.get(chain[i][1]) != deployments.get(chain[i - 1][1])]
        tokens = [switching['prompt_tokens'].get(t) for t in switched]
        found.update(switches=len(switched), cold_switches=len(switched) if switching['mode'] == 'switching' else 0,
                     reprefill_tokens=None if any(n is None for n in tokens) else sum(tokens))
    if outcomes is not None:
        known = [DEFERRAL_OUTCOME if cid is None else outcomes.get((task_id, cid)) for task_id, cid, _ in covered]
        if all(o is not None for o in known):
            found.update(unsafe_commitments=sum(bool(o['false_charge']) or bool(o['dangerous_commitment']) for o in known),
                         false_charge_rate=_ratio(sum(o['false_charge'] is True for o in known), len(known)),
                         all_pass_rate=_ratio(sum(o['all_pass'] is True for o in known), len(known)))
        if thresholds:
            joined = []
            for task_id, result in selections:
                o = outcomes.get((task_id, result.get('selected'))) or {}
                joined.append({'confidence': result.get('confidence'), 'action': 'defer' if result.get('selected') is None else result.get('action', 'route'),
                               'decision_correct': o.get('decision_correct'), 'false_charge': o.get('false_charge'),
                               'dangerous_commitment': o.get('dangerous_commitment')})
            if any(j['confidence'] is not None for j in joined):
                found['risk_coverage'] = risk_coverage(joined, _thresholds(thresholds))
    return found


def evaluate(manifest, tasks, strategies, objective, seed=1, switching=None, outcomes=None, calibration=None, families=None) -> list[dict]:
    """Strategies compared on the same tasks from one replay manifest: fixed candidates, category rules (through
    `route`), a seeded cost/latency-matched random baseline and the bounded selector (from recorded route results). Each
    row also gives the means over the tasks every strategy covers (`common_*`), so a strategy that misses a hard task
    cannot look better on its own subset. With a calibration record and the task families, a selector row says whether
    it was evaluated on families it was calibrated on (`calibration_overlap`)."""
    tasks = sorted(tasks, key=lambda t: t['id'])
    objective = _objective(objective)
    index = {}
    for row in manifest['rows']:
        key = (row['task_id'], row['candidate'])
        if key in index:
            raise ValueError('Duplicate replay outcome')
        index[key] = row
    candidates = sorted(set(manifest.get('candidate_fingerprints') or {}) | {c for _, c in index})
    if switching is not None:
        fields(switching, SWITCHING_KEYS, SWITCHING_KEYS)
        if switching['mode'] not in ('resident', 'switching') or not isinstance(switching['deployment_of'], dict) \
                or not isinstance(switching['prompt_tokens'], dict):
            raise ValueError('switching needs a mode, deployment_of and prompt_tokens')
    by_outcome = None if outcomes is None else {(o['task_id'], o['candidate']): o for o in outcomes}
    checked = [_strategy(s, candidates) for s in strategies]
    names = [s['name'] for s in checked]
    if len(set(names)) != len(names):
        raise ValueError('Duplicate strategy name: ' + next(n for n in names if names.count(n) > 1))
    for s in checked:
        if s['name'] == 'random-matched' and (s['match'] not in names or s['match'] == 'random-matched'):
            raise ValueError('random-matched names an unknown strategy: ' + str(s['match']))
    found = {}
    for s in checked:
        if s['name'] != 'random-matched':
            found[s['name']] = _metrics(s['name'], tasks, _selections(s, tasks, candidates), index, objective, switching, by_outcome, s.get('thresholds'))
    for s in checked:
        if s['name'] != 'random-matched':
            continue
        target = found[s['match']]['mean_latency_s']
        means = {}
        for c in candidates:
            values = [row.get('latency_s') for (t, cid), row in index.items() if cid == c]
            means[c] = None if not values or any(v is None for v in values) else math.fsum(values) / len(values)
        if target is None or any(v is None for v in means.values()) or not means:
            found[s['name']] = _empty(s['name'], tasks)
            continue
        fast = min(candidates, key=lambda c: (means[c], c))
        slow = max(candidates, key=lambda c: (means[c], c))
        spread = means[slow] - means[fast]
        weight = 0.0 if spread <= 0 else min(1.0, max(0.0, (target - means[fast]) / spread))
        rng = random.Random(seed)
        selections = [(t['id'], {'action': 'route', 'selected': slow if rng.random() < weight else fast, 'fallback_used': False, 'confidence': None,
                                 'router_s': None}) for t in tasks]
        found[s['name']] = _metrics(s['name'], tasks, selections, index, objective, switching, by_outcome)
    sets = [{t for t, _, _ in found[n]['_covered']} for n in names if found[n]['_covered'] is not None]
    common = set.intersection(*sets) if sets else set()
    calibrated = set(calibration['families']) if calibration is not None else None
    rows = []
    for s in checked:
        row = found[s['name']]
        covered = row.pop('_covered')
        if covered is None:
            row.update({k: None for k in COMMON_KEYS})
        else:
            shared = [(t, c, r) for t, c, r in covered if t in common]
            row.update(common_tasks=len(common), common_mean_quality=_mean(r.get('quality') for _, _, r in shared),
                       common_mean_latency_s=_mean(_latencies([r for _, _, r in shared])),
                       common_mean_utility=_mean(_utility(r, objective) for _, _, r in shared))
        row['calibration_overlap'] = bool({families.get(t['id']) for t in tasks} & calibrated) \
            if calibrated is not None and families is not None and s['name'] == 'selector' and s.get('thresholds') else None
        rows.append(row)
    return rows


# Operator files and commands ------------------------------------------------------------------------------------------

def read_candidates(path) -> dict:
    """The `--candidates` file: {arm id: candidate}, in the shape of the `candidates` of an `llm-routing` case."""
    value, _ = contracts.read_json_strict(path)
    if not isinstance(value, dict) or not value:
        raise ValueError('The candidates file maps arm ids to candidates')
    for cid, candidate in value.items():
        if cid not in CANDIDATE_ARMS:
            raise ValueError('A recipe candidate is named by a retrieval arm: ' + str(cid))
        fields(candidate, CANDIDATE_KEYS, CANDIDATE_KEYS)      # exactly the fixed generator's identity
    return value


def read_strategies(path) -> dict:
    """The `--strategies` file: {schema_version: 1, objective, seed, switching, strategies}."""
    value, _ = contracts.read_json_strict(path)
    fields(value, STRATEGY_FILE_KEYS, STRATEGY_FILE_KEYS)
    if value['schema_version'] != 1 or not isinstance(value['strategies'], list) or type(value['seed']) is not int:
        raise ValueError('Malformed strategies file')
    _objective(value['objective'])
    return value


def _evaluate_attempts(suite, attempts, pool):
    task_suite = route_tasks(suite)
    scored = _scored(attempts, suite, pool)
    return task_suite, build_replay(task_suite, pool, scored), _outcome_rows(scored)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog='python -m llm_eval.experiments.legal_benchmark.routing')
    commands = parser.add_subparsers(dest='command', required=True)
    export = commands.add_parser('export', help='write the routing suite of an approved fixture suite')
    export.add_argument('--suite', required=True)
    export.add_argument('--output', required=True)
    replay = commands.add_parser('replay', help='write the replay manifest and its local provenance sidecar')
    replay.add_argument('--suite', required=True)
    replay.add_argument('--routing-suite', required=True)
    replay.add_argument('--attempt', action='append', required=True)
    replay.add_argument('--candidates', required=True)
    replay.add_argument('--output', required=True)
    replay.add_argument('--calibration', help='the calibration record whose threshold a selector strategy uses; its digest is recorded')
    verify = commands.add_parser('verify', help='verify a replay manifest and its sidecar before any llm-routing replay')
    verify.add_argument('--suite', required=True)
    verify.add_argument('--replay', required=True)
    verify.add_argument('--routing-suite', required=True)
    verify.add_argument('--candidates', required=True)
    verify.add_argument('--attempt', action='append', required=True, help='every source attempt the manifest was built from')
    compare = commands.add_parser('evaluate', help='compare fixed, rule, random and selector strategies on the same tasks')
    compare.add_argument('--suite', required=True)
    compare.add_argument('--strategies', required=True)
    compare.add_argument('--replay')
    compare.add_argument('--routing-suite')
    compare.add_argument('--attempt', action='append')
    compare.add_argument('--candidates', required=True)
    compare.add_argument('--calibration', help='the calibration record of a selector strategy, to mark overlap with its families')
    calibration = commands.add_parser('calibrate', help='calibrate a threshold on the calibration suite')
    calibration.add_argument('--suite', required=True)
    calibration.add_argument('--routed-attempt', required=True)
    calibration.add_argument('--fallback-attempt', required=True)
    calibration.add_argument('--fallback-arm', required=True)
    calibration.add_argument('--thresholds', required=True)
    calibration.add_argument('--output', required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == 'export':
            contracts.check_output(args.output, 'The routing suite')
            print(export_suite(args.suite, args.output))
        elif args.command == 'replay':
            contracts.check_output(args.output, 'The replay manifest')
            contracts.export_allowed(args.suite)
            suite, pool = contracts.load_suite(args.suite), read_candidates(args.candidates)
            task_suite = load_task_suite(args.routing_suite)
            if digest(task_suite) != digest(route_tasks(suite)):
                raise ValueError('Replay suite hash mismatch')
            calibration = None
            if args.calibration:
                record, calibration = contracts.read_json_strict(args.calibration)
                check_record(record)
            scored = _scored(args.attempt, suite, pool)
            manifest = build_replay(task_suite, pool, scored)
            write_provenance(sidecar(args.output), _provenance(suite, task_suite, manifest, scored, calibration))
            print(_write(args.output, manifest))
        elif args.command == 'verify':
            manifest, _ = contracts.read_json_strict(args.replay)
            provenance, _ = contracts.read_json_strict(sidecar(args.replay))
            verify_replay(manifest, provenance, load_task_suite(args.routing_suite), read_candidates(args.candidates), contracts.load_suite(args.suite),
                          args.attempt)
            print('verified')
        elif args.command == 'evaluate':
            suite, pool, strategies = contracts.load_suite(args.suite), read_candidates(args.candidates), read_strategies(args.strategies)
            record = provenance = None
            if args.replay:
                if not (args.routing_suite and args.attempt):
                    raise ValueError('evaluate --replay needs --routing-suite and the --attempt directories it was built from')
                manifest, _ = contracts.read_json_strict(args.replay)
                provenance, _ = contracts.read_json_strict(sidecar(args.replay))
                task_suite = load_task_suite(args.routing_suite)
                verify_replay(manifest, provenance, task_suite, pool, suite, args.attempt)
                outcomes = provenance['outcomes']
            elif args.attempt and not args.routing_suite:
                task_suite, manifest, outcomes = _evaluate_attempts(suite, args.attempt, pool)      # in memory: nothing is written
            else:
                raise ValueError('evaluate takes --replay with --routing-suite and --attempt, or --attempt')
            if args.calibration:
                record, sha = contracts.read_json_strict(args.calibration)
                check_record(record)
                if provenance is not None and provenance['calibration'] not in (None, sha):
                    raise ValueError('The calibration record is not the one the replay names')
            families = {m['matter_id']: m['family_id'] for m in suite['matters']['matters']}
            print(json.dumps(evaluate(manifest, task_suite['tasks'], strategies['strategies'], strategies['objective'], strategies['seed'],
                                      strategies['switching'], outcomes, record, families), indent=2, sort_keys=True))
        else:
            contracts.check_output(args.output, 'The calibration record')
            thresholds = [float(t) for t in args.thresholds.split(',')]
            suite = contracts.load_suite(args.suite)
            rows = calibration_rows(args.routed_attempt, args.fallback_attempt, args.fallback_arm)
            routed, _ = contracts.read_json_strict(Path(args.routed_attempt) / 'metadata.json')
            if routed.get('suite_lock_sha256') != suite['lock_sha256'] or {r['task_id'] for r in rows} != {m['matter_id'] for m in suite['matters']['matters']}:
                raise ValueError('Calibration attempts belong to another suite')
            lineage = calibration_lineage(args.routed_attempt, args.fallback_attempt, args.fallback_arm)
            print(write_calibration(calibrate(rows, thresholds, suite, lineage), args.output))
    except (ValueError, KeyError, OSError) as exc:
        print('Error: ' + (str(exc) if isinstance(exc, ValueError) else type(exc).__name__), file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
