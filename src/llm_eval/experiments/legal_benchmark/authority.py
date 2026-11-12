"""Authority eligibility: one deterministic rule against frozen metadata, and its single entry point `decide`.

Retrieval, citation resolution, the verifier and the grader all call `decide`, so an authority can never be eligible
for the pipeline and ineligible for the grader. `eligible` is a pure function of the dicts it is given; it reads every
optional key with `.get` and never raises for a missing one.
"""
from __future__ import annotations

import re

from llm_eval.core.contracts import fields, identifier

from .contracts import REVISION, iso_date

DECISIONS = ('eligible', 'ineligible', 'unknown')
REASONS = ('wrong_jurisdiction', 'wrong_venue', 'not_yet_effective', 'no_longer_effective', 'not_yet_available',
           'obsolete_status', 'persuasive_not_permitted',
           'validity_unknown', 'availability_unverified', 'validity_unknown_after_cutoff', 'treatment_unverified',
           'persuasive_only',
           'fabricated_citation', 'unknown_version', 'pinpoint_mismatch')
DEFAULT_POLICY = {'policy_id': 'fixture-default', 'version': '1', 'jurisdiction': None,
                  'effective_from_inclusive': True, 'effective_to_inclusive': False, 'require_status_as_of': False,
                  'postures': {'screening': {'persuasive_eligible': True}, 'retrieval': {'persuasive_eligible': True}},
                  'binding_courts': {}, 'review': None}
OBSOLETE = ('superseded', 'repealed')


def _key(record):
    return record['authority_id'] + '@' + record['version']


def _review(value, name):
    fields(value, ['reviewer_role', 'reviewed_on'], ['reviewer_role', 'reviewed_on'])
    identifier(value['reviewer_role'])
    iso_date(value['reviewed_on'], name + ' reviewed_on')


def validate_record(authority, corpus) -> None:
    """The meaning of the optional authority keys. Raises ValueError."""
    if authority.get('snapshot') is not None:
        fields(authority['snapshot'], ['id', 'published'], ['id', 'published'])
        identifier(authority['snapshot']['id'])
        iso_date(authority['snapshot']['published'], 'snapshot published')
    if authority.get('review') is not None:
        _review(authority['review'], 'review')
    if corpus.get('availability_cutoff') is not None and authority.get('snapshot') is None:
        raise ValueError('An availability cutoff needs a publication snapshot: ' + _key(authority))
    if corpus.get('data_class') == 'public-benchmark' and any(authority.get(k) is None for k in ('snapshot', 'status_as_of', 'review')):
        raise ValueError('A reviewed corpus needs snapshot, status_as_of and review: ' + _key(authority))
    if authority.get('status') in OBSOLETE and authority.get('effective_to') is None:
        raise ValueError('An obsolete authority needs effective_to: ' + _key(authority))


def validate_policy(policy, corpus) -> dict:
    """Policy v1 with every default filled in. Raises ValueError on unknown keys, wrong types or a missing review."""
    fields(policy, DEFAULT_POLICY, ['policy_id', 'version'])
    identifier(policy['policy_id'])
    if not isinstance(policy['version'], str) or not REVISION.fullmatch(policy['version']):
        raise ValueError('A policy version must be a revision string')
    value = {**DEFAULT_POLICY, **policy}
    if value['jurisdiction'] is not None:
        identifier(value['jurisdiction'])
        if value['jurisdiction'] != corpus.get('jurisdiction_profile'):      # a policy is never applied to another profile
            raise ValueError('The policy jurisdiction differs from the corpus jurisdiction profile')
    for key in ('effective_from_inclusive', 'effective_to_inclusive', 'require_status_as_of'):
        if type(value[key]) is not bool:
            raise ValueError('Policy ' + key + ' must be true or false')
    if not isinstance(value['postures'], dict):
        raise ValueError('Policy postures must be an object')
    for posture, profile in value['postures'].items():
        identifier(posture)
        fields(profile, ['persuasive_eligible'], ['persuasive_eligible'])
        if type(profile['persuasive_eligible']) is not bool:
            raise ValueError('persuasive_eligible must be true or false')
    if not isinstance(value['binding_courts'], dict):
        raise ValueError('Policy binding_courts must be an object')
    for venue, courts in value['binding_courts'].items():
        identifier(venue)
        if not isinstance(courts, list) or len(set(courts)) != len(courts):
            raise ValueError('Binding courts must be a list of distinct court identifiers')
        for court in courts:
            identifier(court)
    if value['review'] is not None:
        _review(value['review'], 'Policy review')
    elif corpus.get('data_class') == 'public-benchmark':
        raise ValueError('A reviewed corpus needs a reviewed policy')
    return value


def policy_or_none(corpus):
    """The corpus policy (defaults filled in), the default policy for a `public-synthetic` corpus, or None for a corpus
    that has no policy and no authority: there is nothing to decide, and the fixture default is not reported for it.
    Raises when a corpus with authorities needs a policy and has none."""
    if 'policy' in corpus:
        return validate_policy(corpus['policy'], corpus)
    if corpus.get('data_class') == 'public-synthetic':
        return DEFAULT_POLICY
    if not corpus.get('authorities'):
        return None
    raise ValueError('A policy profile is required for this jurisdiction')


def policy_for(corpus) -> dict:
    """The policy under which an authority of `corpus` is decided. Never a fallback: raises without one."""
    policy = policy_or_none(corpus)
    if policy is None:
        raise ValueError('A policy profile is required for this jurisdiction')
    return policy


def query_for(matter, corpus) -> dict:
    posture = matter.get('posture', 'screening')
    policy = policy_or_none(corpus)
    if policy is not None and posture not in policy['postures']:      # without a policy there is no authority to decide
        raise ValueError('Policy has no profile for posture: ' + str(posture))
    return {'operative_date': matter['operative_date'], 'venue': matter['venue'], 'jurisdiction': corpus['jurisdiction_profile'],
            'posture': posture, 'availability_cutoff': corpus.get('availability_cutoff')}


def weight(source, query, policy) -> str:
    if source.get('weight', 'controlling') == 'persuasive':
        return 'persuasive'
    court = source.get('court')
    if court is not None and court not in policy.get('binding_courts', {}).get(query['venue'], []):
        return 'persuasive'
    return 'controlling'


def _ordered(codes):
    return sorted(set(codes), key=REASONS.index)


def eligible(source, query, policy) -> tuple[str, list[str]]:
    """(decision, reason codes in REASONS order) for `source` under `query` and `policy`. It expects records and policies
    that were validated at suite load (`validate_record`, `validate_policy`); it is not a validator."""
    policy = {**DEFAULT_POLICY, **policy}
    day = iso_date(query['operative_date'], 'operative_date')
    cutoff = iso_date(query['availability_cutoff'], 'availability_cutoff') if query.get('availability_cutoff') else None
    start = iso_date(source['effective_from'], 'effective_from')
    end = iso_date(source['effective_to'], 'effective_to') if source.get('effective_to') is not None else None
    snapshot = source.get('snapshot')
    status = source.get('status')
    codes = []
    jurisdiction = query.get('jurisdiction')
    if jurisdiction is not None and source.get('jurisdiction', jurisdiction) != jurisdiction:
        codes.append('wrong_jurisdiction')
    if query['venue'] not in source['venues']:
        codes.append('wrong_venue')
    if day < start or (day == start and not policy['effective_from_inclusive']):
        codes.append('not_yet_effective')
    # After the cutoff the corpus knows only what was published on or before it. An end is known at the cutoff when it
    # lies on or before the cutoff, or when evidence dated on or before the cutoff records it: `status_as_of`, or the
    # snapshot of a successor version that starts on that day (`successor_published`, derived by `with_end_evidence`).
    after_cutoff = cutoff is not None and day > cutoff
    end_known = end is not None and (not after_cutoff or end <= cutoff or any(
        source.get(key) is not None and iso_date(source[key], key) <= cutoff for key in ('status_as_of', 'successor_published')))
    if end_known and (day > end or (day == end and not policy['effective_to_inclusive'])):
        codes.append('no_longer_effective')
    if cutoff is not None and isinstance(snapshot, dict) and iso_date(snapshot['published'], 'snapshot published') > cutoff:
        codes.append('not_yet_available')
    if status == 'invalidated' or (status in OBSOLETE and end is None):
        codes.append('obsolete_status')
    persuasive = weight(source, query, policy) == 'persuasive'
    if persuasive and not policy['postures'].get(query.get('posture'), {}).get('persuasive_eligible', False):
        codes.append('persuasive_not_permitted')
    if codes:
        return 'ineligible', _ordered(codes)
    if status == 'unknown':
        codes.append('validity_unknown')
    if cutoff is not None and snapshot is None:
        codes.append('availability_unverified')
    if after_cutoff and not end_known:      # open-ended, or an end the frozen corpus could not know
        codes.append('validity_unknown_after_cutoff')
    if policy['require_status_as_of']:
        as_of = source.get('status_as_of')
        if as_of is None or iso_date(as_of, 'status_as_of') < day:
            codes.append('treatment_unverified')
    if codes:
        return 'unknown', _ordered(codes)
    return ('eligible', ['persuasive_only']) if persuasive else ('eligible', [])


def with_end_evidence(record, corpus):
    """`record` plus the derived key `successor_published`: the earliest snapshot date of a version of the same authority
    that starts on the day `record` ends. Only with a cutoff; a loaded record cannot carry the key itself (closed fields)."""
    if corpus.get('availability_cutoff') is None or record.get('effective_to') is None:
        return record
    dates = sorted(a['snapshot']['published'] for a in corpus['authorities']
                   if a['authority_id'] == record['authority_id'] and a['effective_from'] == record['effective_to']
                   and isinstance(a.get('snapshot'), dict))
    return {**record, 'successor_published': dates[0]} if dates else record


def decide(record, matter, corpus) -> tuple[str, list[str]]:
    """THE eligibility decision of `record` for `matter` under the corpus policy."""
    return eligible(with_end_evidence(record, corpus), query_for(matter, corpus), policy_for(corpus))


def resolve_citation(item, corpus, matter) -> dict:
    """Second validation of a cited authority: existence, version and pinpoint, then the shared decision."""
    if not isinstance(item, dict) or not all(isinstance(item.get(k), str) for k in ('authority_id', 'version')) or \
            ('pinpoint' in item and not isinstance(item['pinpoint'], str)):
        raise ValueError('A citation needs string authority_id, version and pinpoint')
    versions = {(a['authority_id'], a['version']): a for a in corpus['authorities']}
    known = {a['authority_id'] for a in corpus['authorities']}
    record = versions.get((item['authority_id'], item['version']))

    def unresolved(code, found=None):
        return {'resolved': False, 'authority': found, 'decision': None, 'reason_codes': [code], 'weight': None}
    if item.get('authority_id') not in known:
        return unresolved('fabricated_citation')
    if record is None:
        return unresolved('unknown_version')
    if 'pinpoint' in item and item['pinpoint'] != record['pinpoint']:
        return unresolved('pinpoint_mismatch', record)
    decision, codes = decide(record, matter, corpus)
    return {'resolved': True, 'authority': record, 'decision': decision, 'reason_codes': codes,
            'weight': weight(record, query_for(matter, corpus), policy_for(corpus))}


def _fold(text):
    return re.sub(r'\s+', ' ', str(text).strip()).casefold()


def resolve_alias(text, corpus, matter) -> dict:
    """Exact (stripped, case-folded) match against citations and aliases. `matches` lists the records that carry the
    status: the eligible ones for `resolved` and `ambiguous`, the unknown ones for `unverified`, every match for
    `ineligible`, none for `unknown`. A collision is never resolved silently: when the eligible and unknown matches
    belong to more than one authority, the status is `ambiguous`. Internal whitespace is collapsed before matching."""
    if not isinstance(text, str):
        raise ValueError('A citation must be a string')
    key = _fold(text)
    found = sorted((a['authority_id'], a['version'], a) for a in corpus['authorities']
                   if key in {_fold(a['citation'])} | {_fold(x) for x in a.get('aliases', [])})
    decided = [(i, v, decide(a, matter, corpus)[0]) for i, v, a in found]
    live = [[i, v] for i, v, d in decided if d == 'eligible']
    doubtful = [[i, v] for i, v, d in decided if d == 'unknown']
    if len({i for i, _ in live + doubtful}) > 1:
        return {'status': 'ambiguous', 'matches': sorted(live + doubtful)}
    if len(live) == 1:
        return {'status': 'resolved', 'matches': live}
    if live:
        return {'status': 'ambiguous', 'matches': live}
    if doubtful:
        return {'status': 'unverified', 'matches': doubtful}
    if decided:
        return {'status': 'ineligible', 'matches': [[i, v] for i, v, _ in decided]}
    return {'status': 'unknown', 'matches': []}


def contrary(source, corpus, matter) -> list[tuple[dict, str]]:
    """Exemptions relating to `source` that are eligible or of unknown validity, with their decision, in identity order.
    Adverse authority of unknown validity might still defeat the charge, so it is surfaced, not dropped."""
    found = []
    for a in sorted(corpus['authorities'], key=lambda a: (a['authority_id'], a['version'])):
        if a['authority_type'] == 'exemption' and a.get('relates_to') == source['authority_id']:
            decision = decide(a, matter, corpus)[0]
            if decision in ('eligible', 'unknown'):
                found.append((a, decision))
    return found
