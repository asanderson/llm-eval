"""Deterministic verifier, grader, aggregate metrics, blind review contract and the `score` mode.

`verify` is part of the evaluated workflow: it is handed the output, the matter, the corpus, the retrieval result and the
passage texts read back from the prompt, never a suite or a rubric, so it cannot provide its own gold grade. `grade` reads
the gold entry and decides eligibility only through `authority.decide` (inside `fixture.score`). Semantic entailment,
admissibility, defense arguments and sufficiency are never decided here: they stay pending until a validated human or
judge review supplies them. Rates are `Fraction` results rounded to six decimals; every written list has a stated order.
"""
from __future__ import annotations

import argparse
from fractions import Fraction
import json
import math
from pathlib import Path
import random
import re
import secrets
import sys

from llm_eval.common import digest, sha256_file
from llm_eval.core.contracts import atomic_json, fields, integer

from . import authority, contracts, fixture, profiles

SCORER_VERSION = 'legal-scorer-1'
CHECKS = ('schema', 'source_exists', 'version', 'pinpoint', 'scope', 'span_digest', 'quote_fidelity')
PENDING_DIMENSIONS = ('semantic_entailment', 'admissibility', 'defense_arguments', 'sufficiency')
REASONS = ('schema_invalid', 'fabricated_citation', 'unknown_version', 'pinpoint_mismatch', 'unknown_span', 'ineligible_version',
           'unverified_validity', 'out_of_scope_citation', 'unsupportive_citation', 'unsupported_charge', 'span_digest_mismatch',
           'quote_mismatch', 'wrong_version', 'false_charge', 'dangerous_commitment', 'absent_element')
CRITICAL = REASONS[:-1]                    # every code but absent_element
CHECK_OF = {'schema_invalid': 'schema', 'fabricated_citation': 'source_exists', 'unknown_version': 'source_exists',
            'unknown_span': 'source_exists', 'pinpoint_mismatch': 'pinpoint', 'ineligible_version': 'version',
            'unverified_validity': 'version', 'out_of_scope_citation': 'scope', 'unsupportive_citation': 'scope',
            'unsupported_charge': 'scope', 'span_digest_mismatch': 'span_digest', 'quote_mismatch': 'quote_fidelity'}
QUOTES = re.compile('"([^"]*)"|\u201c([^\u201c\u201d]*)\u201d|\u00ab([^\u00ab\u00bb]*)\u00bb|\u2018([^\u2018\u2019]*)\u2019(?!\\w)'
                    "|(?<!\\w)'([^']*)'(?!\\w)")      # an apostrophe inside a word opens or closes no quote
MIN_QUOTE = 12
HEX64 = re.compile(r'[0-9a-f]{64}')


def _ordered(codes):
    return sorted(set(codes), key=REASONS.index)


def _norm(text):
    return ' '.join(text.split())


def _key(item):
    return item['authority_id'] + '@' + item['version']


def verify(output, matter, corpus, evidence, shown=None) -> dict:
    """Deterministic checks of one structurally valid output: one verdict per material claim and per element."""
    checks = {name: True for name in CHECKS}
    try:
        contracts.validate_structure(output, matter)
    except ValueError:
        return {'status': 'failed', 'checks': {name: False for name in CHECKS}, 'claims': [], 'elements': [], 'critical': ['schema_invalid']}
    spans = {span['span_id']: span for s in matter['sources'] if s['role'] == 'evidence' for span in s['spans']}
    versions = {(a['authority_id'], a['version']): a for a in corpus['authorities']}
    context = evidence.get('arm') != 'no-context'
    listed = {p['passage_id'] for p in list(evidence['authorities']) + list(evidence['adverse'])}
    shown_spans = {p['passage_id'] for p in evidence['evidence']}
    stored = {p['passage_id']: p['text_sha256'] for p in evidence['evidence']}
    cited_issues = [i for i in output['issues'] if 'authority_id' in i]
    first = cited_issues[0] if cited_issues else None
    first_record = versions.get((first['authority_id'], first['version'])) if first else None
    found = []

    def cite(item):
        """Codes of one citation and its record (also for a pinpoint mismatch), with the shared decision."""
        resolved = authority.resolve_citation({k: item[k] for k in ('authority_id', 'version', 'pinpoint') if k in item}, corpus, matter)
        codes = [] if resolved['resolved'] else list(resolved['reason_codes'])
        record = resolved['authority']
        if record is None:
            return codes, None, None
        if context and _key(item) not in listed:
            codes.append('out_of_scope_citation')
        return codes, record, authority.decide(record, matter, corpus)[0]

    def anchors(ids):
        codes = []
        for span_id in ids:
            if span_id not in spans:
                codes.append('unknown_span')
                continue
            if context and span_id not in shown_spans:
                codes.append('out_of_scope_citation')
            if shown is not None:
                if span_id in shown and contracts.text_digest(shown[span_id]) != spans[span_id]['text_sha256']:
                    codes.append('span_digest_mismatch')
            elif span_id in stored and stored[span_id] != spans[span_id]['text_sha256']:
                codes.append('span_digest_mismatch')
        return codes

    for index, issue in enumerate(cited_issues):
        codes, record, decision = cite(issue)
        if index == 0 and record is not None:
            if decision == 'ineligible':
                codes.append('ineligible_version')
            elif decision == 'unknown' and output['recommendation'] == 'charge':
                codes.append('unverified_validity')
        found += codes

    def governs(record):
        return first_record is not None and ((record['authority_id'], record['version']) == (first_record['authority_id'], first_record['version'])
                                             or (record['authority_type'] == 'exemption' and record.get('relates_to') == first_record['authority_id']))
    claims = []
    for claim in output['claims']:
        codes, record, decision = cite(claim)
        if record is not None:
            if decision == 'ineligible' and claim['status'] != 'insufficient':
                codes.append('ineligible_version')
            if decision == 'unknown' and claim['status'] == 'supported':
                codes.append('unverified_validity')
            if claim['status'] == 'supported' and not governs(record):
                codes.append('unsupportive_citation')
            text = _norm(record['text'])
            for match in QUOTES.finditer(claim['proposition']):
                quoted = _norm(next(g for g in match.groups() if g is not None))
                if len(quoted) >= MIN_QUOTE and quoted not in text:
                    codes.append('quote_mismatch')
        claims.append({'claim_id': claim['claim_id'], 'codes': codes,
                       'locator': {'authority_id': claim['authority_id'], 'version': claim['version'], 'pinpoint': claim['pinpoint']}})
    charge = output['recommendation'] == 'charge'
    elements = []
    for element in output['elements']:
        codes = anchors(element['evidence_span_ids'] + element['adverse_span_ids'])
        if charge and (element['status'] in ('missing', 'contradicted') or (element['status'] == 'supported' and not element['evidence_span_ids'])):
            codes.append('unsupported_charge')
        elements.append({'element_id': element['element_id'], 'codes': codes,
                         'locator': {'span_ids': element['evidence_span_ids'] + element['adverse_span_ids']}})
    for adverse in output['adverse_authorities']:
        codes, record, decision = cite(adverse)
        if record is not None and adverse['status'] == 'established':
            if decision == 'ineligible':
                codes.append('ineligible_version')
            elif decision == 'unknown':
                codes.append('unverified_validity')
        found += codes + anchors(adverse['evidence_span_ids'])
    for conflict in output['material_conflicts']:
        found += anchors(conflict['span_ids'])
    for flag in output['verification_flags']:
        if 'span_id' in flag:
            found += anchors([flag['span_id']])
    if charge:
        eligible_first = first_record is not None and authority.decide(first_record, matter, corpus)[0] == 'eligible'
        if not eligible_first or not any(c['status'] == 'supported' and (c['authority_id'], c['version']) == (first['authority_id'], first['version'])
                                         for c in output['claims']):
            found.append('unsupported_charge')
        stated = {e['element_id']: e['status'] for e in output['elements']}
        if first_record is not None and any(stated.get(e['element_id']) != 'supported' for e in first_record['elements']):
            found.append('unsupported_charge')      # an element dropped from the output cannot make a charge pass
    every = found + [c for item in claims + elements for c in item['codes']]
    for code in every:
        checks[CHECK_OF[code]] = False

    def verdict(codes):
        return 'rejected' if any(c in CRITICAL for c in codes) else 'unverified' if codes else 'checks_passed'
    return {'status': 'passed' if all(checks.values()) else 'failed', 'checks': checks,
            'claims': [{'claim_id': c['claim_id'], 'verdict': verdict(c['codes']), 'reason_codes': _ordered(c['codes']), 'locator': c['locator']}
                       for c in claims],
            'elements': [{'element_id': e['element_id'], 'verdict': verdict(e['codes']), 'reason_codes': _ordered(e['codes']),
                          'locator': e['locator']} for e in elements],
            'critical': _ordered(c for c in every if c in CRITICAL)}


def _errors(output, matter, gold, corpus):
    """Grader errors, classified apart from the criteria. A fabricated authority and a real authority that does not
    support the claim are different codes and never stand for each other."""
    versions = {(a['authority_id'], a['version']): a for a in corpus['authorities']}
    known = {a['authority_id'] for a in corpus['authorities']}
    controlling = versions.get(tuple(gold['controlling_authority'])) if gold and gold.get('controlling_authority') else None
    ineligible = {tuple(v) for v in gold['ineligible_versions']} if gold else set()
    errors = []

    def add(code, locator):
        errors.append({'code': code, 'critical': code in CRITICAL, 'locator': locator})

    def citation(item, name, index, support):
        key = (item['authority_id'], item['version'])
        locator = {'list': name, 'index': index}
        if item['authority_id'] not in known:
            add('fabricated_citation', locator)
            return None
        if key not in versions:
            add('wrong_version', locator)      # the authority exists, the cited version does not
            return None
        if 'pinpoint' in item and item['pinpoint'] != versions[key]['pinpoint']:
            add('pinpoint_mismatch', locator)
        if support and key in ineligible:
            add('wrong_version', locator)
        return versions[key]
    cited = [(i, issue) for i, issue in enumerate(output['issues']) if 'authority_id' in issue]
    for position, (i, issue) in enumerate(cited):
        citation(issue, 'issues', i, support=position == 0)
        if position == 0 and controlling is not None and issue['authority_id'] == controlling['authority_id'] \
                and issue['version'] != controlling['version'] and (issue['authority_id'], issue['version']) in versions \
                and (issue['authority_id'], issue['version']) not in ineligible:
            add('wrong_version', {'list': 'issues', 'index': i})
    for i, claim in enumerate(output['claims']):
        record = citation(claim, 'claims', i, support=claim['status'] == 'supported')
        if record is not None and claim['status'] == 'supported' and gold is not None \
                and authority.decide(record, matter, corpus)[0] == 'eligible' and not fixture._governs(record, controlling):
            add('unsupportive_citation', {'list': 'claims', 'index': i})
    for i, adverse in enumerate(output['adverse_authorities']):
        citation(adverse, 'adverse_authorities', i, support=adverse['status'] == 'established')
    if gold is not None:
        present = {e['element_id'] for e in output['elements']}
        for element_id in sorted(gold['elements']):
            if element_id not in present:
                add('absent_element', {'element_id': element_id})
        author = output['recommendation']
        if author == 'charge' and gold['recommendation'] in ('decline', 'defer'):
            add('false_charge', None)
        if author in ('charge', 'decline') and gold['recommendation'] == 'defer':
            add('dangerous_commitment', None)
    return sorted(errors, key=lambda e: REASONS.index(e['code']))


def _review_of(review):
    review = review or {}
    verdicts = {d: v for d, v in (review.get('verdicts') or {}).items() if d in PENDING_DIMENSIONS}
    return verdicts, dict(review.get('adjudications') or {})


def grade(output, matter, gold, corpus, evidence=None, review=None) -> dict:
    """The grader's result for one output (None: a response without a structurally valid output). `gold is None` (no
    grader entry) is `pending`, never a zero. `review`: {'verdicts': {dimension: verdict}, 'adjudications': {code: upheld}}."""
    verdicts, adjudications = _review_of(review)
    base = {'pending_dimensions': [d for d in PENDING_DIMENSIONS if d not in verdicts], 'reviewed_dimensions': verdicts,
            'gold_recommendation': gold['recommendation'] if gold else None,
            'complete': (not gold['missing_elements'] and not gold['conflict_elements']) if gold else None}
    valid = output is not None
    if valid:
        try:
            contracts.validate_structure(output, matter)
        except ValueError:
            valid = False
    if gold is None:
        criteria = {name: None for name in fixture.CRITERIA}
        errors = []
        if valid:
            codes = {e['code'] for e in contracts.reference_errors(output, matter, corpus)}
            criteria.update(schema_valid=True, citations_resolve=not codes & {'fabricated_citation', 'unknown_version'},
                            pinpoints_correct='pinpoint_mismatch' not in codes)
            errors = _errors(output, matter, None, corpus)
        else:
            criteria.update(schema_valid=False, citations_resolve=False, pinpoints_correct=False)
            errors = [{'code': 'schema_invalid', 'critical': True, 'locator': None}]
        status = 'pending'
    elif not valid:
        criteria = {name: False for name in fixture.CRITERIA}
        errors = [{'code': 'schema_invalid', 'critical': True, 'locator': None}]
        status = 'scored'
    else:
        shown = [p['passage_id'] for p in evidence['evidence']] if evidence is not None else None
        criteria = fixture.score(output, matter, gold, corpus, shown)
        errors = _errors(output, matter, gold, corpus)
        status = 'scored'
    critical = _ordered(e['code'] for e in errors if e['critical'])
    return {'grading_status': status, 'criteria': criteria, 'errors': errors, **base,
            'adjudicated': [c for c in critical if c in adjudications]}


def scorer_fingerprint(suite) -> str:
    rubric = next((f['sha256'] for f in suite['lock']['source_files'] if f['purpose'] == 'rubric'), None)
    return digest({'scorer_version': SCORER_VERSION, 'criteria': list(fixture.CRITERIA), 'checks': list(CHECKS), 'reasons': list(REASONS),
                   'rubric_version': suite['rubric'].get('rubric_version'), 'rubric_sha256': rubric})


# One fault, one code: a nonexistent or ineligible cited version is the grader's wrong version.
FOLDED = {'unknown_version': 'wrong_version', 'ineligible_version': 'wrong_version'}


def critical_codes(graded, verified):
    """The distinct critical codes of a row, in REASONS order: the grader's critical errors and the verifier's critical codes
    for a scored row (the verifier's `unknown_version` counts as the grader's `wrong_version`, so one fault needs one
    adjudication); the verifier's codes alone for a row without a scored grade."""
    if graded is None or graded['grading_status'] != 'scored':
        return _ordered(verified)
    return _ordered([e['code'] for e in graded['errors'] if e['critical']] + [FOLDED.get(c, c) for c in verified])


def _standing(critical, adjudications):
    """Critical codes that stand: every code but those a review dismissed (`upheld: false`)."""
    return [c for c in critical if adjudications.get(c) is not False]


def review_status(graded, critical, review=None):
    verdicts, adjudications = _review_of(review)
    covered = all(d in verdicts for d in PENDING_DIMENSIONS)
    return 'reviewed' if covered and all(c in adjudications for c in critical) else 'pending_human_review'


def decision_fields(status, graded, verified, choice, review=None) -> dict:
    """The grading keys of a public row, by the row-state table of design 3.8. A row passes only when every criterion is
    true, no reviewed dimension failed and no critical code stands. `decision_correct` is never public: with `choice` it
    would publish the gold recommendation."""
    if status in ('error', 'missing') or graded is None:
        return {'grading_status': 'not_applicable', 'review_status': 'not_applicable', 'quality_check_applicable': False,
                'quality_pass': None, 'criteria_passed': None, 'critical_errors': None, 'pending_dimensions': []}
    _, adjudications = _review_of(review)
    scored = graded['grading_status'] == 'scored'
    critical = critical_codes(graded, verified)
    passed = scored and all(v is True for v in graded['criteria'].values()) and 'fail' not in graded['reviewed_dimensions'].values() \
        and not _standing(critical, adjudications)
    return {'grading_status': graded['grading_status'], 'review_status': review_status(graded, critical, review),
            'quality_check_applicable': scored, 'quality_pass': passed if scored else None,
            'criteria_passed': sum(v is True for v in graded['criteria'].values()) if scored else None,
            # Public: the verifier's critical codes only (a structural failure counts as schema_invalid). The grader's codes
            # depend on the gold; with the visible reason codes their count would give the gold away. The union stays private.
            'critical_errors': len(_ordered(verified)) if graded['criteria'].get('schema_valid') is not False else 1,
            'pending_dimensions': list(graded['pending_dimensions'])}


def detail(matter, arm, repetition, status, graded, verified, choice, author_choice, gold, review=None) -> dict:
    """Score-detail record v1. `errors` holds what `grade` found, as `{code, critical}` (distinct, REASONS order; the
    locators can hold model-written strings and are not written); `verifier_codes` holds the verifier's critical codes;
    `adjudicated` the critical codes a review adjudicated and `dismissed` those it dismissed (`upheld: false`)."""
    base = {'matter_id': matter['matter_id'], 'family_id': matter['family_id'], 'arm': arm, 'repetition': repetition, 'status': status,
            'verifier_codes': _ordered(verified), 'choice': choice, 'author_choice': author_choice}
    if graded is None:
        return {**base, 'grading_status': 'not_applicable', 'criteria': {name: None for name in fixture.CRITERIA}, 'errors': [],
                'pending_dimensions': [], 'reviewed_dimensions': {}, 'adjudicated': [], 'dismissed': [],
                'gold_recommendation': gold['recommendation'] if gold else None,
                'complete': (not gold['missing_elements'] and not gold['conflict_elements']) if gold else None}
    _, adjudications = _review_of(review)
    adjudicated = [c for c in critical_codes(graded, verified) if c in adjudications]
    return {**base, 'grading_status': graded['grading_status'], 'criteria': graded['criteria'],
            'errors': [{'code': c, 'critical': c in CRITICAL} for c in _ordered(e['code'] for e in graded['errors'])],
            'pending_dimensions': list(graded['pending_dimensions']), 'reviewed_dimensions': dict(graded['reviewed_dimensions']),
            'adjudicated': adjudicated, 'dismissed': [c for c in adjudicated if adjudications[c] is False],
            'gold_recommendation': graded['gold_recommendation'], 'complete': graded['complete']}


def deferral_fields() -> dict:
    """The status and grading keys of a selector-deferral row (design 3.8, last row): no request was sent, and the row is
    scored with nothing passed, so a selector cannot raise its pass rate by removing matters from the denominator."""
    return {'status': 'ok', 'retrieval_status': 'not_applicable', 'inference_status': 'not_applicable', 'parse_status': 'not_applicable',
            'verification_status': 'not_applicable', 'grading_status': 'scored', 'review_status': 'not_applicable',
            'quality_check_applicable': True, 'quality_pass': False, 'criteria_passed': 0, 'critical_errors': 0, 'pending_dimensions': []}


def deferral_detail(matter, arm, repetition, gold, reason) -> dict:
    """Score-detail record of a selector deferral: every criterion False, no error, the workflow choice `defer`, and the
    route reason under `selector_deferral` (an insufficiency label or `no_eligible_candidate`)."""
    return {'matter_id': matter['matter_id'], 'family_id': matter['family_id'], 'arm': arm, 'repetition': repetition, 'status': 'ok',
            'verifier_codes': [], 'choice': 'defer', 'author_choice': None, 'grading_status': 'scored',
            'criteria': {name: False for name in fixture.CRITERIA}, 'errors': [], 'pending_dimensions': [], 'reviewed_dimensions': {},
            'adjudicated': [], 'dismissed': [], 'gold_recommendation': gold['recommendation'] if gold else None,
            'complete': (not gold['missing_elements'] and not gold['conflict_elements']) if gold else None, 'selector_deferral': reason}


# Aggregate metrics ----------------------------------------------------------------------------------------------------

_CHOICES = contracts.RECOMMENDATIONS
METRICS = ('all_pass', 'all_pass_deterministic', 'all_pass_reviewed', *('criterion.' + c for c in fixture.CRITERIA), *('error.' + c for c in REASONS),
           'author_false_charge', 'workflow_false_charge', 'author_false_defer', 'workflow_false_defer', 'author_dangerous_commitment',
           'workflow_dangerous_commitment', 'abstention', 'forced_defer',
           *(f'confusion.{g}.{a}' for g in _CHOICES for a in _CHOICES + ('none',)), *(f'workflow_confusion.{g}.{c}' for g in _CHOICES for c in _CHOICES),
           'critical_errors', 'critical_unreviewed', 'missing.pending', 'missing.unavailable', 'missing.no_response')


def _rate(numerator, denominator):
    return None if not denominator else round(float(Fraction(numerator, denominator)), 6)


def _passes(d):
    return all(v is True for v in d['criteria'].values())


def _union(d):
    """The critical codes of a score-detail record: grader and verifier together, one fault counted once."""
    verified = d.get('verifier_codes', [])      # optional: the smoke mode's detail has neither key
    if d['grading_status'] != 'scored':
        return set(verified)
    return {e['code'] for e in d['errors'] if e['critical']} | {FOLDED.get(c, c) for c in verified}


def _clean(d):
    """No critical code stands: each is absent or was dismissed by a review."""
    return not _union(d) - set(d.get('dismissed', []))


def all_pass(d) -> bool:
    """The pass rule of `aggregate` for one score-detail record: every criterion, no standing critical code, no failed
    reviewed dimension."""
    return bool(_indicator(d, 'all_pass'))


def standing_critical(d) -> list:
    """The critical codes of a score-detail record that stand (grader and verifier together, minus dismissed ones)."""
    return _ordered(_union(d) - set(d.get('dismissed', [])))


def _indicator(d, metric):
    """1 or 0 for one record: `all_pass`, `criterion.<name>` or `error.<code>`."""
    if metric == 'all_pass':
        return int(_passes(d) and _clean(d) and 'fail' not in d['reviewed_dimensions'].values())
    kind, _, name = metric.partition('.')
    if kind == 'criterion' and name in fixture.CRITERIA:
        return int(d['criteria'].get(name) is True)
    if kind == 'error' and name in REASONS:
        return int(name in {e['code'] for e in d['errors']})
    raise ValueError('Unknown per-record metric: ' + str(metric))


def aggregate(details) -> dict:
    """{metric: {'value', 'n', 'missing'}} over the score-detail records of one arm. Only `scored` records are in a
    denominator; every other record is counted in `missing` and in exactly one of `missing.pending`, `missing.unavailable`
    and `missing.no_response`. A rate of zero over a positive `n` is 0.0; no denominator gives `value: None`. A pass needs
    every criterion, no failed review dimension and no standing critical code. `error.<code>` rates count the grader's
    errors only; `critical_errors` and `critical_unreviewed` count the grader's and the verifier's codes together."""
    details = list(details)
    keys = [(d['matter_id'], d['arm'], d['repetition']) for d in details]
    if len(set(keys)) != len(keys):
        raise ValueError('Duplicate score-detail record: ' + '/'.join(map(str, next(k for k in keys if keys.count(k) > 1))))
    if len({d['arm'] for d in details}) > 1:
        raise ValueError('aggregate takes the records of one arm')
    scored = [d for d in details if d['grading_status'] == 'scored']
    others = [d for d in details if d['grading_status'] != 'scored']
    pending = sum(d['grading_status'] == 'pending' for d in others)
    unavailable = sum(d['grading_status'] != 'pending' and d['status'] == 'missing' for d in others)
    missing = len(others)
    out = {}

    def put(name, records, test, extra=0):
        out[name] = {'value': _rate(sum(1 for d in records if test(d)), len(records)), 'n': len(records), 'missing': missing + extra}
    put('all_pass', scored, lambda d: _indicator(d, 'all_pass'))
    put('all_pass_deterministic', scored, lambda d: _passes(d) and _clean(d))
    full = [d for d in scored if all(dim in d['reviewed_dimensions'] for dim in PENDING_DIMENSIONS)]
    put('all_pass_reviewed', full, lambda d: _passes(d) and _clean(d) and set(d['reviewed_dimensions'].values()) == {'pass'},
        len(scored) - len(full))
    if len(full) < len(scored):
        out['all_pass_reviewed']['value'] = None      # undecided while any scored record waits for review
    for name in fixture.CRITERIA:
        put('criterion.' + name, scored, lambda d, name=name: d['criteria'].get(name) is True)
    for code in REASONS:
        put('error.' + code, scored, lambda d, code=code: code in {e['code'] for e in d['errors']})
    refused = [d for d in scored if d['gold_recommendation'] in ('decline', 'defer')]
    complete = [d for d in scored if d['complete'] and d['gold_recommendation'] != 'defer']
    deferred = [d for d in scored if d['gold_recommendation'] == 'defer']
    for prefix, key in (('author', 'author_choice'), ('workflow', 'choice')):
        put(prefix + '_false_charge', refused, lambda d, key=key: d[key] == 'charge')
        put(prefix + '_false_defer', complete, lambda d, key=key: d[key] == 'defer')
        put(prefix + '_dangerous_commitment', deferred, lambda d, key=key: d[key] in ('charge', 'decline'))
    put('abstention', scored, lambda d: d['author_choice'] == 'defer')
    put('forced_defer', scored, lambda d: d['choice'] == 'defer' and d['author_choice'] != 'defer')
    for g in _CHOICES:
        for a in _CHOICES + ('none',):
            out[f'confusion.{g}.{a}'] = {'value': sum(1 for d in scored if d['gold_recommendation'] == g and (d['author_choice'] or 'none') == a),
                                         'n': len(scored), 'missing': missing}
        for c in _CHOICES:
            out[f'workflow_confusion.{g}.{c}'] = {'value': sum(1 for d in scored if d['gold_recommendation'] == g and d['choice'] == c),
                                                  'n': len(scored), 'missing': missing}
    put('critical_errors', scored, lambda d: bool(_union(d)))
    put('critical_unreviewed', scored, lambda d: bool(_union(d) - set(d['adjudicated'])))
    for name, count in (('missing.pending', pending), ('missing.unavailable', unavailable), ('missing.no_response', missing - pending - unavailable)):
        out[name] = {'value': count, 'n': len(details), 'missing': 0}
    return {name: out[name] for name in METRICS}


def _resample(values_by_family, seed, samples):
    integer(samples, 'samples', 1, 10_000_000)
    families = sorted(values_by_family)
    rng = random.Random(seed)
    stats = []
    for _ in range(samples):
        drawn = rng.choices(families, k=len(families))
        total = sum((Fraction(v) for f in drawn for v in values_by_family[f]), Fraction(0))
        count = sum(len(values_by_family[f]) for f in drawn)
        stats.append(total / count)
    stats.sort()
    return round(float(stats[math.floor(0.025 * samples)]), 6), round(float(stats[math.ceil(0.975 * samples) - 1]), 6)


def bootstrap(values_by_family, seed=1, samples=1000, minimum=6):
    """Percentile interval of the pooled mean, resampling whole matter families. Only families with values count; None
    below `minimum` of them."""
    integer(samples, 'samples', 1, 10_000_000)
    present = {f: list(v) for f, v in values_by_family.items() if v}
    if len(present) < minimum:
        return None
    return _resample(present, seed, samples)


def paired_difference(details_a, details_b, metric='all_pass', seed=1, samples=1000, minimum=6) -> dict:
    """Mean per-family difference (a minus b) of a per-record indicator over records paired by (family, matter, repetition)
    in which both sides are scored, with a family bootstrap interval. Unpaired or unscored records count as missing."""
    integer(samples, 'samples', 1, 10_000_000)

    def index(details):
        found = {}
        for d in details:
            key = (d['family_id'], d['matter_id'], d['repetition'])
            if key in found:
                raise ValueError('Two records share a pairing key: ' + '/'.join(map(str, key)))
            found[key] = d
        return found
    a, b = index(details_a), index(details_b)
    pairs, missing = [], 0
    for key in sorted(set(a) | set(b)):
        if key in a and key in b and a[key]['grading_status'] == 'scored' and b[key]['grading_status'] == 'scored':
            pairs.append(key)
        else:
            missing += 1
    families = {}
    for key in pairs:
        families.setdefault(key[0], []).append(Fraction(_indicator(a[key], metric) - _indicator(b[key], metric)))
    means = {f: sum(v, Fraction(0)) / len(v) for f, v in families.items()}
    mean = round(float(sum(means.values(), Fraction(0)) / len(means)), 6) if means else None
    interval = _resample({f: [m] for f, m in means.items()}, seed, samples) if len(means) >= minimum else (None, None)
    return {'mean': mean, 'n': len(pairs), 'low': interval[0], 'high': interval[1], 'missing': missing}


# Blind review -------------------------------------------------------------------------------------------------------

TOKEN = re.compile(r'[0-9a-f]{32}')
ITEM_ID = re.compile(r'[0-9a-f]{16}')
REVIEW_KEYS = ('schema_version', 'kind', 'reviewer', 'rubric_version', 'packet_sha256', 'verdicts', 'adjudications')
KEY_KEYS = ('schema_version', 'kind', 'packet_sha256', 'output_manifest_sha256', 'order_seed', 'items')
KEY_ITEM_KEYS = ('item_id', 'matter_id', 'arm', 'repetition')


def _packet(entries, outputs):
    """The packet of `entries` (key items in packet order) over `outputs` ({(matter_id, arm, repetition): output record})."""
    return {'schema_version': 1, 'kind': 'legal-review-packet',
            'items': [{'item_id': e['item_id'], 'matter_id': e['matter_id'], 'output': outputs[(e['matter_id'], e['arm'], e['repetition'])]['output'],
                       'critical_codes': _ordered(outputs[(e['matter_id'], e['arm'], e['repetition'])]['critical_codes'])} for e in entries]}


def review_packet(outputs, output_manifest_sha256) -> tuple[dict, dict]:
    """(blind packet, private key table) of every structurally valid output of one output manifest. Item ids are drawn
    at random and the order from a secret seed; both live only in the key table, so the packet carries nothing from which
    an arm, model or deployment can be derived."""
    if not (isinstance(output_manifest_sha256, str) and HEX64.fullmatch(output_manifest_sha256)):
        raise ValueError('A review packet names the output manifest it was built from')
    valid = {(o['matter_id'], o['arm'], o['repetition']): o for o in outputs if o['output'] is not None}
    if len(valid) != len([o for o in outputs if o['output'] is not None]):
        raise ValueError('Two outputs share a review item')
    order_seed = secrets.randbits(63)
    ordered = sorted(valid.values(), key=lambda o: (o['matter_id'], o['arm'], o['repetition']))
    random.Random(order_seed).shuffle(ordered)
    ids = []
    while len(ids) < len(ordered):
        drawn = secrets.token_hex(8)
        if drawn not in ids:
            ids.append(drawn)
    entries = [{'item_id': item_id, 'matter_id': o['matter_id'], 'arm': o['arm'], 'repetition': o['repetition']} for item_id, o in zip(ids, ordered)]
    packet = _packet(entries, valid)
    return packet, {'schema_version': 1, 'kind': 'legal-review-key', 'packet_sha256': digest(packet), 'output_manifest_sha256': output_manifest_sha256,
                    'order_seed': order_seed, 'items': entries}


def _version_one(value, kind, what):
    if type(value.get('schema_version')) is not int or value['schema_version'] != 1 or value.get('kind') != kind:
        raise ValueError('Not a ' + what + ' v1')


def load_review(path, key_path) -> dict:
    """Review file v1 joined to its key table: {'reviewer', 'rubric_version', 'packet_sha256', 'output_manifest_sha256',
    'key', 'items': {(matter_id, arm, repetition): {'verdicts': {dimension: verdict}, 'adjudications': {code: upheld}}}}.
    Closed key sets, no free text. `upheld: true` means the error stands; `upheld: false` dismisses it."""
    review, _ = contracts.read_json_strict(path)
    key, _ = contracts.read_json_strict(key_path)
    fields(key, KEY_KEYS, KEY_KEYS)
    _version_one(key, 'legal-review-key', 'review key')
    if not isinstance(key['output_manifest_sha256'], str) or not HEX64.fullmatch(key['output_manifest_sha256']) \
            or type(key['order_seed']) is not int or not isinstance(key['items'], list):
        raise ValueError('Malformed review key')
    joined = {}
    for where in key['items']:
        fields(where, KEY_ITEM_KEYS, KEY_ITEM_KEYS)
        if not isinstance(where['item_id'], str) or not ITEM_ID.fullmatch(where['item_id']) or not isinstance(where['matter_id'], str) \
                or not isinstance(where['arm'], str) or type(where['repetition']) is not int or where['repetition'] < 0:
            raise ValueError('Malformed review key item')
        where_key = (where['matter_id'], where['arm'], where['repetition'])
        if where['item_id'] in joined or where_key in joined.values():
            raise ValueError('Review key repeats an item')
        joined[where['item_id']] = where_key
    fields(review, REVIEW_KEYS, REVIEW_KEYS)
    _version_one(review, 'legal-review', 'review file')
    reviewer = review['reviewer']
    fields(reviewer, ['kind', 'reviewer_token', 'blind', 'prompt_version'], ['kind', 'reviewer_token', 'blind'])
    if reviewer['kind'] not in ('human', 'judge') or reviewer['blind'] is not True:
        raise ValueError('A review is blind and by a human or a judge')
    if not isinstance(reviewer['reviewer_token'], str) or not TOKEN.fullmatch(reviewer['reviewer_token']):
        raise ValueError('reviewer_token must be 32 random hex characters from the operator registry')
    prompt = reviewer.get('prompt_version')
    if prompt is not None and not (isinstance(prompt, str) and contracts.REVISION.fullmatch(prompt)):
        raise ValueError('prompt_version must be a version string')
    if reviewer['kind'] == 'judge' and prompt is None:
        raise ValueError('A judge review needs its prompt_version')
    if not isinstance(review['rubric_version'], str) or not review['rubric_version']:
        raise ValueError('A review names its rubric_version')
    if review['packet_sha256'] != key['packet_sha256']:
        raise ValueError('Review belongs to another packet')
    items = {where: {'verdicts': {}, 'adjudications': {}} for where in joined.values()}
    for name, item_keys, value_key in (('verdicts', ('item_id', 'dimension', 'verdict', 'critical'), 'dimension'),
                                       ('adjudications', ('item_id', 'code', 'upheld'), 'code')):
        if not isinstance(review[name], list):
            raise ValueError('Review ' + name + ' must be a list')
        for entry in review[name]:
            fields(entry, item_keys, item_keys)
            if entry['item_id'] not in joined:
                raise ValueError('Review names an item that is not in its packet')
            target = items[joined[entry['item_id']]][name]
            if entry[value_key] in target:
                raise ValueError('Review repeats an entry: ' + str(entry[value_key]))
            if name == 'verdicts':
                if entry['dimension'] not in PENDING_DIMENSIONS or entry['verdict'] not in ('pass', 'fail') or type(entry['critical']) is not bool:
                    raise ValueError('Malformed review verdict')
                target[entry['dimension']] = entry['verdict']
            else:
                if entry['code'] not in CRITICAL or type(entry['upheld']) is not bool:
                    raise ValueError('Malformed review adjudication')
                target[entry['code']] = entry['upheld']
    return {'reviewer': dict(reviewer), 'rubric_version': review['rubric_version'], 'packet_sha256': review['packet_sha256'],
            'output_manifest_sha256': key['output_manifest_sha256'], 'key': key, 'items': items}


def reviewer_fingerprint(review) -> str | None:
    """Digest of the reviewer, the rubric version and the packet reviewed; None without a review."""
    return None if review is None else digest({'reviewer': review['reviewer'], 'rubric_version': review['rubric_version'],
                                               'packet_sha256': review['packet_sha256']})


def agreement(review_a, review_b) -> dict:
    """Agreement and Cohen's kappa of two reviews of one packet over their common (item_id, dimension) keys."""
    if review_a['packet_sha256'] != review_b['packet_sha256']:
        raise ValueError('The reviews belong to another packet')
    a = {(v['item_id'], v['dimension']): v for v in review_a['verdicts']}
    b = {(v['item_id'], v['dimension']): v for v in review_b['verdicts']}
    common = sorted(set(a) & set(b))
    n = len(common)
    if not n:
        return {'n': 0, 'agreement': None, 'kappa': None, 'critical_disagreements': []}
    observed = Fraction(sum(a[k]['verdict'] == b[k]['verdict'] for k in common), n)
    expected = sum((Fraction(sum(a[k]['verdict'] == label for k in common), n) * Fraction(sum(b[k]['verdict'] == label for k in common), n)
                    for label in ('pass', 'fail')), Fraction(0))
    return {'n': n, 'agreement': round(float(observed), 6),
            'kappa': None if expected == 1 else round(float((observed - expected) / (1 - expected)), 6),
            'critical_disagreements': [list(k) for k in common if a[k]['critical'] or b[k]['critical']]}


# The `score` mode -----------------------------------------------------------------------------------------------------

PARAMETERS = {'score': ({'output_manifest', 'review_file', 'review_key'}, ('output_manifest',))}
SOURCE_MODES = ('generation', 'workflow')
MANIFEST_KEYS = ('schema_version', 'kind', 'experiment', 'mode', 'job_id', 'attempt_id', 'suite_lock_sha256', 'data_class', 'execution_kind',
                 'template_sha256', 'role_digests', 'arms', 'outputs', 'files', 'result')
RESULT_KEYS = ('status', 'result_path', 'benchmark')
RESULT_EXTRA = ('finished_unix', 'attempt_id')      # what the worker adds after `execute` returns


def execution_kind(parameters, mode):
    return 'score-only'


def host(parameters, mode):
    """CPU only: scoring reads stored outputs and runs no model."""
    return {'gpu': False}


def _lines(path):
    return contracts.read_jsonl(path)


def _source(attempt):
    """The source attempt's rows, stored outputs, retrieval results, verifications and metadata, in row order."""
    rows = _lines(attempt / 'requests.jsonl')
    outputs, results, verifications = (_lines(attempt / 'local' / name)
                                       for name in ('candidate-outputs.jsonl', 'retrieval-results.jsonl', 'verification.jsonl'))
    metadata, _ = contracts.read_json_strict(attempt / 'metadata.json')
    keys = [(r['task_id'], r['arm'], r['repetition']) for r in rows]
    for records in (outputs, results, verifications):
        if [(x['matter_id'], x['arm'], x['repetition']) for x in records] != keys:
            raise ValueError('The source attempt files disagree on their rows')
    return rows, outputs, results, verifications, metadata


def _manifest(path, suite):
    """(manifest, source attempt directory, source job, manifest sha256) after the identity, lineage and byte checks.
    Only the manifest, `result.json`, `job.json` and the listed files are opened, and nothing is written."""
    from .workflow import MANIFEST_FILES, ROUTED_FILES, manifest_files
    if not isinstance(path, str):
        raise ValueError('output_manifest must be a path string')
    path = Path(path)
    try:
        manifest, sha = contracts.read_json_strict(path)
    except OSError:
        raise ValueError('Output manifest not found') from None
    fields(manifest, MANIFEST_KEYS, MANIFEST_KEYS)
    _version_one(manifest, 'legal-output-manifest', 'legal output manifest')
    if manifest['suite_lock_sha256'] != suite['lock_sha256']:
        raise ValueError('Output manifest belongs to another suite')

    def wrong(field):
        raise ValueError('Output manifest identity does not match its attempt: ' + field)
    if path.name != 'output-manifest.json' or path.parent.name != 'local':
        wrong('location')
    attempt = path.parent.parent
    if manifest['attempt_id'] != attempt.name:
        wrong('attempt_id')
    if manifest['experiment'] != 'legal-benchmark' or manifest['execution_kind'] != 'model-run':
        wrong('experiment')
    files = manifest['files']
    listed = [f.get('path') if isinstance(f, dict) else None for f in files] if isinstance(files, list) else None
    if listed not in (list(MANIFEST_FILES), list(ROUTED_FILES)):
        raise ValueError('Output manifest does not list the expected files')
    for f in files:
        fields(f, ['path', 'size', 'sha256'], ['path', 'size', 'sha256'])
        target = attempt / contracts._relative(f['path'])
        if not target.is_file() or target.is_symlink() or target.stat().st_size != f['size'] or sha256_file(target) != f['sha256']:
            raise ValueError('Output manifest file changed: ' + f['path'])
    try:
        result, _ = contracts.read_json_strict(attempt / 'result.json')
        job, _ = contracts.read_json_strict(attempt / 'job.json')
    except OSError:
        wrong('result')
    if not isinstance(result, dict) or result.get('attempt_id') != manifest['attempt_id']:
        wrong('attempt_id')
    if result.get('status') != 'succeeded':
        wrong('status')
    # result.json is written after the manifest, so its digest cannot be listed: the manifest records the result the run
    # returned, and result.json must hold exactly that plus what the worker adds.
    expected = manifest['result']
    if not isinstance(expected, dict) or set(expected) != set(RESULT_KEYS) or set(result) - set(RESULT_KEYS) - set(RESULT_EXTRA) \
            or any(result.get(k) != expected[k] for k in RESULT_KEYS) or expected['benchmark'] != suite['lock']['benchmark_id']:
        wrong('result')
    if job.get('experiment_id') != 'legal-benchmark':
        wrong('experiment_id')
    if job.get('job_id') != manifest['job_id']:
        wrong('job_id')
    if job.get('mode') != manifest['mode'] or manifest['mode'] not in SOURCE_MODES:
        wrong('mode')
    parameters, inputs = job.get('parameters') or {}, job.get('input_files') or []
    if listed != list(manifest_files(parameters)):      # a routed job lists its route decisions, and only a routed job does
        raise ValueError('Output manifest does not list the expected files')
    if {f['path']: f['sha256'] for f in inputs}.get(parameters.get('suite')) != manifest['suite_lock_sha256']:
        wrong('suite')
    roles = parameters.get('roles') if isinstance(parameters.get('roles'), dict) else {}
    if manifest['role_digests'] != {name: profiles.profile_digest(p, inputs) for name, p in roles.items()}:
        wrong('role_digests')
    rows, _, _, _, metadata = _source(attempt)
    if metadata.get('mode') != manifest['mode'] or metadata.get('experiment') != 'legal-benchmark':
        wrong('mode')
    if metadata.get('suite_lock_sha256') != manifest['suite_lock_sha256']:
        wrong('suite')
    if not len(rows) == manifest['outputs'] == metadata.get('rows'):
        wrong('outputs')
    arms, repeats = parameters.get('arms'), parameters.get('repeats', 1)
    if not isinstance(arms, list) or manifest['arms'] != arms or metadata.get('arms') != arms or type(repeats) is not int:
        wrong('arms')
    filed = ['routed'] if parameters.get('selector') is not None else arms      # rows of a routed job are filed under `routed`
    expected_rows = {(m['matter_id'], a, r) for m in suite['matters']['matters'] for a in filed for r in range(repeats)}
    if {(row['task_id'], row['arm'], row['repetition']) for row in rows} != expected_rows or len(rows) != len(expected_rows):
        wrong('rows')
    if metadata.get('roles') != {name: profiles.public_role(p, inputs) for name, p in roles.items()}:
        wrong('roles')
    if manifest['template_sha256'] != metadata.get('template_sha256'):
        wrong('template_sha256')
    if not manifest['data_class'] == metadata.get('data_class') == suite['lock']['data_class']:
        wrong('data_class')
    _recorded(attempt, sha)
    return manifest, attempt, job, sha


def _recorded(attempt, sha, required=False):
    """Where the coordinator's campaign record of the attempt is available (the attempt sits in its campaign layout
    `<campaign>/experiments/<run>/jobs/<job>/<attempt>`), the record must hold this output-manifest digest: every lineage file
    is written by whoever ran the attempt, the campaign record by the coordinator when the attempt finished. `required`
    (publication) also refuses an attempt outside such a layout."""
    attempt = Path(attempt).resolve()
    parents = attempt.parents
    if len(parents) < 5 or parents[1].name != 'jobs' or parents[3].name != 'experiments' or not (parents[4] / 'campaign.json').is_file():
        if required:
            raise ValueError('Output manifest is not in a campaign record')
        return
    try:
        state, _ = contracts.read_json_strict(parents[4] / 'campaign.json')
        attempts = state['jobs'][parents[0].name]['attempts']
    except (OSError, ValueError, KeyError, TypeError):
        raise ValueError('Output manifest is not in its campaign record') from None
    record = next((a for a in attempts if isinstance(a, dict) and a.get('attempt_id') == attempt.name), None)
    if record is None:
        raise ValueError('Output manifest is not in its campaign record')
    if 'output_manifest_sha256' not in record:
        raise ValueError('Campaign record has no output-manifest digest (campaign written before this check)')
    if record['output_manifest_sha256'] != sha:
        raise ValueError('Output manifest differs from the campaign record')


def _packet_outputs(attempt, suite, source=None):
    """{(matter_id, arm, repetition): {'output', 'critical_codes'}} for every structurally valid output of the attempt."""
    rows, outputs, results, verifications, _ = source or _source(attempt)
    matters = {m['matter_id']: m for m in suite['matters']['matters']}
    gold = {g['matter_id']: g for g in suite['rubric']['matters']}
    found = {}
    for row, stored, result, verified in zip(rows, outputs, results, verifications):
        if row['status'] != 'ok' or stored['output'] is None:      # a selector deferral has no output to review
            continue
        graded = grade(stored['output'], matters[row['task_id']], gold.get(row['task_id']), suite['corpus'], result['result'])
        found[(row['task_id'], row['arm'], row['repetition'])] = {
            'output': stored['output'], 'critical_codes': critical_codes(graded, verified['verification']['critical'] if verified['verification'] else [])}
    return found


def _review(parameters, suite, attempt, manifest_sha, source=None):
    """The review of a score job, bound to the outputs it reviewed: its key names the scored manifest, and the packet
    rebuilt from the scored outputs with the key's item ids and order has the digest the review and the key record."""
    if ('review_file' in parameters) != ('review_key' in parameters):
        raise ValueError('Declare review_file and review_key together or neither')
    if 'review_file' not in parameters:
        return None
    if not all(isinstance(parameters[k], str) for k in ('review_file', 'review_key')):
        raise ValueError('review_file and review_key must be path strings')
    review = load_review(parameters['review_file'], parameters['review_key'])
    if review['rubric_version'] != suite['rubric'].get('rubric_version'):
        raise ValueError('Review belongs to another rubric version')
    if review['output_manifest_sha256'] != manifest_sha:
        raise ValueError('Review key belongs to another output manifest')
    outputs = _packet_outputs(attempt, suite, source)
    entries = review['key']['items']
    if {(e['matter_id'], e['arm'], e['repetition']) for e in entries} != set(outputs) or digest(_packet(entries, outputs)) != review['packet_sha256']:
        raise ValueError('Review packet does not match the scored outputs')
    return review


def check(parameters, suite, root, mode):
    _, attempt, _, sha = _manifest(parameters['output_manifest'], suite)
    _review(parameters, suite, attempt, sha)
    return None


def inputs(parameters, suite, root, mode):
    """Every file the manifest lists and the source `result.json`, so planner, coordinator and worker check their bytes."""
    manifest, attempt, _, _ = _manifest(parameters['output_manifest'], suite)
    return [attempt / f['path'] for f in manifest['files']] + [attempt / 'result.json']


def score_records(parameters, suite):
    """(manifest, source attempt, manifest sha256, metadata, lineage, rows, score-detail records) of the outputs an output
    manifest pins, graded exactly as the `score` mode grades them. Every input is a file the manifest lists (after
    `_manifest` checked their digests), never the attempt's own score detail."""
    from .routing import DEFERRALS
    from .workflow import ROW_TIMING, withhold
    manifest, attempt, source_job, manifest_sha = _manifest(parameters['output_manifest'], suite)
    source = _source(attempt)
    review = _review(parameters, suite, attempt, manifest_sha, source)
    rows, outputs, results, verifications, metadata = source
    matters = {m['matter_id']: m for m in suite['matters']['matters']}
    gold = {g['matter_id']: g for g in suite['rubric']['matters']}
    lineage = {'inference_job_id': manifest['job_id'], 'inference_attempt_id': manifest['attempt_id'], 'output_manifest_sha256': manifest_sha,
               'scorer_fingerprint': scorer_fingerprint(suite), 'reviewer_fingerprint': reviewer_fingerprint(review)}
    new_rows, details = [], []
    for row, stored, result, verified in zip(rows, outputs, results, verifications):
        matter, entry = matters[row['task_id']], gold.get(row['task_id'])
        if stored.get('selector_deferral') is True:
            # Not graded (a missing output would be `schema_invalid`): the row and the record keep the deferral state, and
            # `category` and the route keys of a routed source row are copied with the row.
            reason = next((c for c in stored.get('reason_codes') or [] if c in DEFERRALS), None)
            if reason is None or stored.get('output') is not None:
                raise ValueError('Malformed selector deferral record: ' + str(row['task_id']))
            new_rows.append({**row, 'synthetic': False, 'execution_kind': 'score-only', **deferral_fields(), 'reason_codes': stored['reason_codes'],
                             'choice': 'defer', 'author_choice': None, 'abstained': False, 'forced_defer': True, 'insufficiency_flags': None,
                             'criteria_total': len(fixture.CRITERIA), **{k: None for k in ROW_TIMING}, **lineage})
            details.append(deferral_detail(matter, row['arm'], row['repetition'], entry, reason))
            continue
        item = review['items'].get((row['task_id'], row['arm'], row['repetition'])) if review else None
        status, verification = row['status'], verified['verification']
        critical = verification['critical'] if verification else []
        graded = grade(stored['output'], matter, entry, suite['corpus'], result['result'], item) if status in ('ok', 'invalid') else None
        author, choice = stored['author_choice'], stored['choice']
        flags = sorted({f['code'] for f in stored['output']['verification_flags'] if f['code'] in contracts.INSUFFICIENCY_FLAGS}) \
            if stored['output'] is not None else None
        new = {**row, 'synthetic': False, 'execution_kind': 'score-only', 'inference_status': 'not_applicable',
               'verification_status': verification['status'] if verification else 'not_applicable',
               **decision_fields(status, graded, critical, choice, item), 'reason_codes': stored['reason_codes'], 'choice': choice,
               'author_choice': author, 'abstained': author == 'defer',
               'forced_defer': None if status == 'error' else choice == 'defer' and author != 'defer',
               'insufficiency_flags': flags, 'criteria_total': len(fixture.CRITERIA), **{k: None for k in ROW_TIMING}, **lineage}
        new_rows.append(withhold(new, row['reason_codes']) if row['arm'] == 'reference' else new)
        details.append(detail(matter, row['arm'], row['repetition'], status, graded, critical, choice, author, entry, item))
    return manifest, attempt, manifest_sha, metadata, lineage, new_rows, details


def run(job, suite, output, root):
    """Grade the stored outputs of one inference attempt into a new attempt. Verification is copied, not re-run: the
    verifier is part of the evaluated workflow and its verdicts are observations of the inference attempt."""
    from . import MANIFEST, job_status
    parameters = job['parameters']
    _, attempt, _, _ = _manifest(parameters['output_manifest'], suite)
    output = Path(output)
    if output.resolve() == attempt.resolve() or output.resolve().is_relative_to(attempt.resolve()):
        raise ValueError('A score attempt is never written into its source attempt')
    manifest, attempt, manifest_sha, metadata, lineage, new_rows, details = score_records(parameters, suite)
    output.mkdir(parents=True, exist_ok=True)
    (output / 'requests.jsonl').write_text(''.join(json.dumps(r, sort_keys=True) + '\n' for r in new_rows), encoding='utf-8', newline='\n')
    contracts.private_file(output, 'score-detail.jsonl').write_text(''.join(json.dumps(d, sort_keys=True) + '\n' for d in details),
                                                                    encoding='utf-8', newline='\n')
    lock = suite['lock']
    atomic_json(output / 'metadata.json', {
        'schema_version': 1, 'experiment': MANIFEST['id'], 'mode': job['mode'], 'execution_kind': 'score-only', 'synthetic': False,
        'data_class': lock['data_class'], 'benchmark_id': lock['benchmark_id'], 'suite_revision': lock['revision'], 'split_id': lock['split_id'],
        'jurisdiction_profile': lock['jurisdiction_profile'], 'suite_lock_sha256': suite['lock_sha256'],
        'rubric_version': suite['rubric'].get('rubric_version'), 'scorer_version': SCORER_VERSION,
        **{k: metadata[k] for k in ('policy_id', 'policy_version', 'template_sha256', 'arms', 'retrieval', 'generation', 'selector', 'roles')},
        'matters': len({r['task_id'] for r in new_rows}), 'families': len({r['family_id'] for r in new_rows}), 'rows': len(new_rows),
        'all_pass': sum(r['quality_pass'] is True for r in new_rows), 'review_required': True,
        'scorer_fingerprint': lineage['scorer_fingerprint'], 'reviewer_fingerprint': lineage['reviewer_fingerprint'],
        'inference': {'job_id': manifest['job_id'], 'attempt_id': manifest['attempt_id'], 'output_manifest_sha256': manifest_sha}})
    return {'status': job_status(new_rows), 'result_path': '.', 'benchmark': lock['benchmark_id']}


SCANNED = contracts.SCANNED_NAMES      # directory names the generic report builder scans (legal_benchmark.SCANNED_DIRECTORIES)
_inside_attempt = contracts.inside_attempt


def main(argv=None):
    """`packet --output-manifest FILE --output DIR`: the blind review packet and its private key table, written outside
    any attempt directory, outside the repository and outside any directory the report builder scans."""
    parser = argparse.ArgumentParser(prog='python -m llm_eval.experiments.legal_benchmark.grading')
    commands = parser.add_subparsers(dest='command', required=True)
    packet = commands.add_parser('packet', help='write review-packet.json and review-key.json for one output manifest')
    packet.add_argument('--output-manifest', required=True)
    packet.add_argument('--output', required=True)
    args = parser.parse_args(argv)
    path = Path(args.output_manifest).resolve()
    try:
        source_job, _ = contracts.read_json_strict(path.parent.parent / 'job.json')
    except OSError:
        raise ValueError('Output manifest not found') from None
    suite = contracts.load_suite(source_job['parameters']['suite'])
    _, attempt, _, sha = _manifest(str(path), suite)
    out = Path(args.output).resolve()
    if out.is_relative_to(attempt.resolve()):
        raise ValueError('The review packet must not be written inside an attempt directory')
    contracts.check_output(out / 'review-packet.json', 'The review packet')      # the one rule of every operator command
    outputs = _packet_outputs(attempt, suite)
    review_packet_, key = review_packet([{'matter_id': m, 'arm': a, 'repetition': r, **v} for (m, a, r), v in outputs.items()], sha)
    atomic_json(out / 'review-packet.json', review_packet_)
    atomic_json(out / 'review-key.json', key)
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except ValueError as exc:
        print('Error: ' + str(exc), file=sys.stderr)
        raise SystemExit(2) from None
