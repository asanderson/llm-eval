"""A Markdown screening memo for local human review, rendered only from a fully validated candidate output.

Every string that comes from the matter, the corpus or the model passes through `ingest.escape` exactly once; no raw
link, image or HTML is emitted. Author text, sourced claims and reviewer conclusions are three separate sections, and
anchors (span ids, `authority_id@version` with pinpoint) are plain text.
"""
from __future__ import annotations

from . import authority, contracts
from .ingest import escape

BANNER = 'DRAFT FOR HUMAN REVIEW. Not a filing, charging or disclosure decision.'
CLAIMS_NOTE = 'Deterministic checks only. Support of the proposition is not assessed.'
SECTIONS = ('Question', 'Facts and limitations', 'Elements and alternatives', 'Defense and adverse evidence', 'Authorities',
            'Missing evidence', 'Proposed disposition', 'Sourced claims', 'Reviewer conclusions')
NONE = 'None.'
VERDICTS = ('checks_passed', 'unverified', 'rejected')


def _ids(values):
    return ', '.join(escape(v) for v in values) if values else 'none'


def _anchor(item):
    return escape(item['authority_id'] + '@' + item['version'])


def render_memo(output, matter, corpus, verification, disposition) -> str:
    contracts.validate_output(output, matter, corpus)      # structure and references: a memo only from fully validated JSON
    versions = {(a['authority_id'], a['version']): a for a in corpus['authorities']}
    issues = [i for i in output['issues'] if 'authority_id' in i]
    first = issues[0] if issues else None
    verdicts = {c['claim_id']: c for c in (verification or {}).get('claims', [])}
    out = [BANNER, '']

    def section(name, lines):
        out.extend(['## ' + name, *(lines or [NONE]), ''])
    section('Question', [escape(matter['question']), 'Matter ' + escape(matter['matter_id']) + '; operative date ' + escape(matter['operative_date'])
                         + '; venue ' + escape(matter['venue']) + '.'])
    facts = ['- Element ' + escape(e['element_id']) + ': ' + escape(e['status']) + '; evidence ' + _ids(e['evidence_span_ids'])
             + '; adverse ' + _ids(e['adverse_span_ids']) for e in output['elements']]
    limits = ['- Limitation, missing ' + escape(m['element_id']) + ': ' + escape(m['needed']) for m in output['missing_information']]
    limits += ['- Limitation, flag ' + escape(f['code']) + (' at ' + escape(f['span_id']) if 'span_id' in f else '') for f in output['verification_flags']]
    section('Facts and limitations', facts + limits)
    elements = []
    if first is not None:
        elements.append('First issue ' + escape(first['issue_id']) + ' (' + _anchor(first) + '): ' + escape(first['question']))
    elements += ['- ' + escape(e['element_id']) + ': ' + escape(e['status']) for e in output['elements']]
    alternatives = ['- Alternative offence issue ' + escape(i['issue_id']) + ' (' + _anchor(i) + '): ' + escape(i['question'])
                    for i in issues[1:] if i.get('kind') == 'offence']
    alternatives += ['- Alternative: exemption not established ' + _anchor(a) + ', pinpoint ' + escape(a['pinpoint'])
                     for a in output['adverse_authorities'] if a['status'] == 'not_established']
    section('Elements and alternatives', elements + (['Alternatives:'] + alternatives if alternatives else []))
    defense = ['- Defence issue ' + escape(i['issue_id']) + (' (' + _anchor(i) + ')' if 'authority_id' in i else '') + ': ' + escape(i['question'])
               for i in output['issues'] if i.get('kind') == 'defence']
    defense += ['- Adverse evidence for ' + escape(e['element_id']) + ': ' + _ids(e['adverse_span_ids']) for e in output['elements'] if e['adverse_span_ids']]
    defense += ['- Material conflict on ' + escape(c['element_id']) + ': ' + _ids(c['span_ids']) for c in output['material_conflicts']]
    defense += ['- Established exemption ' + _anchor(a) + ', pinpoint ' + escape(a['pinpoint']) + '; evidence ' + _ids(a['evidence_span_ids'])
                for a in output['adverse_authorities'] if a['status'] == 'established']
    section('Defense and adverse evidence', defense)
    cited, seen = [], set()
    for item in issues + output['claims'] + output['adverse_authorities']:
        key = (item['authority_id'], item['version'])
        if key not in seen:
            seen.add(key)
            cited.append(versions[key])
    lines = []
    for record in cited:
        decision, codes = authority.decide(record, matter, corpus)
        weight = authority.weight(record, authority.query_for(matter, corpus), authority.policy_for(corpus))
        lines.append('- ' + _anchor(record) + ', pinpoint ' + escape(record['pinpoint']) + ': ' + escape(weight) + '; eligibility '
                     + escape(decision) + ('; ' + _ids(codes) if codes else ''))
    section('Authorities', lines)
    section('Missing evidence', ['- ' + escape(m['element_id']) + ': ' + escape(m['needed']) for m in output['missing_information']])
    section('Proposed disposition', ['Author recommendation: ' + escape(str(disposition.get('author_choice'))),
                                     'Harness choice: ' + escape(str(disposition.get('choice'))),
                                     'Reason codes: ' + _ids(disposition.get('reason_codes') or [])])
    claims = [CLAIMS_NOTE]
    for c in output['claims']:
        checked = verdicts.get(c['claim_id'], {})
        verdict = checked.get('verdict', 'unverified')
        if verdict not in VERDICTS:
            raise ValueError('Unknown verifier verdict')
        claims.append('- ' + escape(c['claim_id']) + ' [`' + verdict + '`] ' + escape(c['proposition'])
                      + ' (' + _anchor(c) + ', pinpoint ' + escape(c['pinpoint']) + '; author status ' + escape(c['status'])
                      + '; check codes ' + _ids(checked.get('reason_codes', [])) + ')')
    section('Sourced claims', claims)
    section('Reviewer conclusions', ['`review_status: pending_human_review`'])
    return '\n'.join(out)
