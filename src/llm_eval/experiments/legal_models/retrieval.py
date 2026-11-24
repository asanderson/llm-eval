"""Retrieval arms, their metrics and the `retrieval` mode.

Candidate-side functions (`passages`, `retrieve`, `available_arms`) receive `contracts.candidate_view(suite)` and never
the rubric. Only `reference_passages`, `gold_targets` and the mode's `run` read the rubric. Every stored or sorted
float is rounded to six decimals after `math.fsum`, every ranking breaks ties on `passage_id`, and every written list
has a stated order, so the same bytes always give the same result.
"""
from __future__ import annotations

from contextlib import closing
from fractions import Fraction
import hashlib
import http.client
import json
import math
from pathlib import Path
import re
import time

from llm_eval.common import digest
from llm_eval.core.contracts import atomic_json, integer

from . import authority, contracts, profiles
from .fixture import STOPWORDS

ARMS = ('no-context', 'filters-only', 'lexical', 'lexical-eligible', 'dense', 'hybrid', 'reranked', 'reference')
RANKED_ARMS = ('lexical', 'lexical-eligible', 'dense', 'hybrid', 'reranked')
TOKENIZER = 'legal-terms-1'
REASONS = ('capability_absent_fts5', 'capability_absent_embedding', 'capability_absent_reranker', 'fts5_absent_memory_used',
           'no_eligible_authority', 'adverse_over_budget', 'adverse_validity_unknown', 'embedding_error', 'reranker_error')
BACKENDS = ('auto', 'memory', 'fts5')
CHUNKING = 'span'
LEXICAL_ARMS = ('lexical', 'lexical-eligible', 'hybrid', 'reranked')      # arms that need a lexical ranking
EMBEDDING_ARMS = ('dense', 'hybrid')
FILTERED_ARMS = ('filters-only', 'lexical-eligible', 'dense', 'hybrid', 'reranked')      # ineligible versions removed
K1, B, RRF = 1.2, 0.75, 60
TOKEN = re.compile(r'[a-z0-9]+(?:\.[0-9]+)*')
METRICS = ('evidence_recall_at_5', 'authority_recall_at_5', 'evidence_ndcg_at_10', 'authority_ndcg_at_10', 'prompt_evidence_recall',
           'prompt_authority_recall', 'exact_version_recall', 'ineligible_version_leakage', 'annotated_ineligible',
           'adverse_authority_coverage', 'retrieved_passages', 'retrieved_tokens')
PUBLIC_METRICS = tuple(m for m in METRICS if m != 'annotated_ineligible')      # measured with the rule under test: private only
PARAMETERS = {'retrieval': ({'arms', 'top_k', 'token_budget', 'backend', 'roles'}, ('arms',))}
ARM_ROLES = {'dense': 'embedder', 'hybrid': 'embedder', 'reranked': 'reranker'}
TRANSPORT_ERRORS = (OSError, ValueError, RuntimeError, KeyError, TypeError, IndexError, http.client.HTTPException)
_ORDER = REASONS + authority.REASONS


def codes(*items):
    """A reason-code list in the order of `REASONS` then `authority.REASONS`. A code outside both raises, so no code
    exists only as a literal."""
    found = set()
    for item in items:
        for code in ([item] if isinstance(item, str) else item):
            if code not in _ORDER:
                raise ValueError('Unexported reason code: ' + str(code))
            found.add(code)
    return sorted(found, key=_ORDER.index)


def tokens(text) -> list[str]:
    """Lowercased terms; a section number such as `s45.2` is one token. Stop words and one-character tokens are
    dropped, duplicates are kept."""
    return [t for t in TOKEN.findall(str(text).lower()) if t not in STOPWORDS and len(t) > 1]


def _round(value):
    return round(float(value), 6)


def _ratio(numerator, denominator):
    return None if not denominator else _round(Fraction(numerator, denominator))


def _authority_passage(a):
    return {'passage_id': a['authority_id'] + '@' + a['version'], 'namespace': 'authority', 'authority_id': a['authority_id'],
            'version': a['version'], 'pinpoint': a['pinpoint'], 'citation': a['citation'], 'title': a['title'], 'issuer': a['issuer'],
            'venues': list(a['venues']), 'effective_from': a['effective_from'], 'effective_to': a['effective_to'], 'status': a['status'],
            'elements': [{'element_id': e['element_id'], 'description': e['description']} for e in a['elements']],
            'text': a['text'], 'text_sha256': a['text_sha256']}


def _source_passage(s, span):
    return {'passage_id': span['span_id'], 'namespace': s['role'], 'source_id': s['source_id'], 'role': s['role'],
            'text': span['text'], 'text_sha256': span['text_sha256']}


def passages(view, matter) -> list[dict]:
    """Every candidate passage of `matter`: authority versions in identity order, then source spans in document order.
    A source excluded for this matter and a quoted span are not passages. Authority-role matter sources are not passages
    either: authorities come from the corpus manifest."""
    found = [_authority_passage(a) for a in sorted(view['corpus']['authorities'], key=lambda a: (a['authority_id'], a['version']))]
    for s in list(matter['sources']) + list(view['matters'].get('shared_sources', [])):
        if s.get('source_set', 'candidate') != 'candidate':
            raise ValueError('A candidate manifest holds a source of another source set: ' + str(s.get('source_id')))
        if matter['matter_id'] in s.get('excluded_matters', []) or s['role'] == 'authority':
            continue
        found.extend(_source_passage(s, span) for span in s['spans'] if not span.get('quoted', False))
    return found


def _entry(suite, matter):
    for g in suite['rubric']['matters']:
        if g['matter_id'] == matter['matter_id']:
            return g
    raise ValueError('No rubric entry for matter: ' + matter['matter_id'])


def _is_retrieval_entry(matter, entry):
    return matter.get('posture') == 'retrieval' or ('gold_spans' in entry and 'reference_passages' not in entry)


def reference_passages(suite, matter) -> dict:
    """The approved reference passages of one matter (the reviewed rubric key `reference_passages`), as candidate passages
    and nothing else: no status, recommendation, scenario, variant or element mapping. Called by `run`, never by `retrieve`.
    A matter without a controlling authority has an empty reference list; that is a valid oracle, not an error."""
    entry = _entry(suite, matter)
    available = {p['passage_id']: p for p in passages(contracts.candidate_view(suite), matter)}

    def pick(ids):
        missing = [i for i in ids if i not in available]
        if missing:
            raise ValueError('A reference passage is not a candidate passage of its matter: ' + missing[0])
        return [dict(available[i]) for i in ids]
    if _is_retrieval_entry(matter, entry):
        order = [p['passage_id'] for p in available.values() if p['namespace'] != 'authority']
        gold = set(entry.get('gold_spans', []))
        return {'evidence': pick([i for i in order if i in gold]), 'authorities': [], 'adverse': []}
    listed = entry['reference_passages']
    return {'evidence': pick(listed['evidence']), 'authorities': pick(listed['authorities']), 'adverse': pick(listed['adverse'])}


_FTS5 = None      # the probed capability, once per process (tests reset or patch it)


def _probe_fts5():
    try:
        import sqlite3      # imported lazily: a Python built without sqlite3 still runs the in-memory backend
    except ImportError:
        return False
    try:
        with closing(sqlite3.connect(':memory:')) as db:
            db.execute('CREATE VIRTUAL TABLE probe USING fts5(body)')
        return True
    except sqlite3.Error:
        return False


def fts5_available() -> bool:
    global _FTS5
    if _FTS5 is None:
        _FTS5 = _probe_fts5()
    return _FTS5


def resolve_backend(suite, requested='auto') -> tuple[str, list[str]]:
    """Called once per run. FTS5 for a prepared corpus when the build has it; the in-memory BM25 otherwise. An explicit
    choice is never replaced, and a fallback is recorded."""
    if requested not in BACKENDS:
        raise ValueError('Unknown retrieval backend: ' + str(requested))
    if requested != 'auto':
        return requested, []
    if suite.get('collection') is None:
        return 'memory', []
    return ('fts5', []) if fts5_available() else ('memory', codes('fts5_absent_memory_used'))


def _hash_vector(text, dimensions):
    vector = [0.0] * dimensions
    for token in tokens(text):
        h = hashlib.sha256(token.encode('utf-8')).hexdigest()
        vector[int(h[:8], 16) % dimensions] += 1.0 if int(h[8], 16) % 2 == 0 else -1.0
    norm = math.sqrt(math.fsum(x * x for x in vector))
    return [x / norm for x in vector] if norm else vector


def embedder(profile, allowed):
    """callable(list[str]) -> list[list[float]] for an embedder role, or None without one. An endpoint outside the job
    allowlist is refused here, before any connection."""
    if profile is None:
        return None
    dimensions = profile['dimensions']
    if profile['serving'] == 'in-process':
        return lambda texts: [_hash_vector(t, dimensions) for t in texts]
    profiles.require_allowed(profile.get('endpoint'), allowed)

    def embed(texts):
        reply = profiles.json_request(profile, {'model': profile['model'], 'input': list(texts)}, allowed)
        vectors = [item['embedding'] for item in reply['data']]
        if len(vectors) != len(texts) or any(not isinstance(v, list) or len(v) != dimensions for v in vectors):
            raise ValueError('Embedding reply has the wrong shape')
        for v in vectors:
            for x in v:
                if isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x):
                    raise ValueError('Embedding reply holds a value that is not a finite number')
        return [[float(x) for x in v] for v in vectors]
    return embed


def reranker(profile, allowed):
    """callable(query, list[str]) -> list[float] for a reranker role, or None without one."""
    if profile is None:
        return None
    if profile['serving'] == 'in-process':
        def overlap(query, texts):
            wanted = tokens(query)
            return [float(sum(1 for t in wanted if t in set(tokens(text)))) for text in texts]
        return overlap
    profiles.require_allowed(profile.get('endpoint'), allowed)

    def rerank(query, texts):
        reply = profiles.json_request(profile, {'model': profile['model'], 'query': query, 'documents': list(texts)}, allowed)
        scores = {}
        for item in reply['results']:
            index, value = item['index'], item['relevance_score']
            if type(index) is not int or not 0 <= index < len(texts) or index in scores or isinstance(value, bool) \
                    or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError('Rerank reply has the wrong shape')
            scores[index] = float(value)
        if len(scores) != len(texts):
            raise ValueError('Rerank reply has the wrong shape')
        return [scores[i] for i in range(len(texts))]
    return rerank


def _settings(settings):
    return {'top_k': settings.get('top_k', 5), 'token_budget': settings.get('token_budget', 1200), 'backend': settings.get('backend', 'memory'),
            'roles': settings.get('roles') or {}, 'allowed': settings.get('allowed', frozenset())}


def available_arms(arms, settings) -> dict:
    """{arm: None or the reason it cannot run with these settings}, decided without any request."""
    s = _settings(settings)
    result = {}
    for arm in arms:
        reason = None
        if arm in LEXICAL_ARMS and s['backend'] == 'fts5' and not fts5_available():
            reason = 'capability_absent_fts5'
        elif arm in EMBEDDING_ARMS and s['roles'].get('embedder') is None:
            reason = 'capability_absent_embedding'
        elif arm == 'reranked' and s['roles'].get('reranker') is None:
            reason = 'capability_absent_reranker'
        result[arm] = reason
    return result


def _document(p):
    return p['title'] + ' ' + p['text'] if p['namespace'] == 'authority' else p['text']


def _order(scored):
    return sorted(([pid, _round(score)] for pid, score in scored), key=lambda item: (-item[1], item[0]))


def _bm25_memory(docs, query):
    """[[passage_id, score]] by (-score, passage_id). Statistics per namespace list and per call."""
    if not docs:
        return []
    bags = [(p['passage_id'], tokens(_document(p))) for p in docs]
    n_docs = len(bags)
    average = math.fsum(len(t) for _, t in bags) / n_docs
    frequency = {}
    for _, terms in bags:
        for term in set(terms):
            frequency[term] = frequency.get(term, 0) + 1
    scored = []
    for pid, terms in bags:
        parts = []
        for term in query:
            tf = terms.count(term)
            if tf and average:
                idf = math.log(1 + (n_docs - frequency[term] + 0.5) / (frequency[term] + 0.5))
                parts.append(idf * tf * (K1 + 1) / (tf + K1 * (1 - B + B * len(terms) / average)))
        scored.append((pid, math.fsum(parts)))
    return _order(scored)


def _bm25_fts5(docs, query):
    if not docs:
        return []
    import sqlite3      # only reached after `fts5_available()`
    distinct = list(dict.fromkeys(query))
    found = {}
    with closing(sqlite3.connect(':memory:')) as db:
        db.execute('CREATE VIRTUAL TABLE p USING fts5(passage_id UNINDEXED, body, tokenize = "unicode61 tokenchars \'.\'")')
        db.executemany('INSERT INTO p (passage_id, body) VALUES (?, ?)', [(p['passage_id'], ' '.join(tokens(_document(p)))) for p in docs])
        if distinct:
            match = ' OR '.join('"' + t + '"' for t in distinct)
            for pid, value in db.execute('SELECT passage_id, bm25(p) FROM p WHERE p MATCH ?', (match,)):
                found[pid] = -value
    return _order((p['passage_id'], found.get(p['passage_id'], 0.0)) for p in docs)


def _cosine(a, b):
    na, nb = math.sqrt(math.fsum(x * x for x in a)), math.sqrt(math.fsum(x * x for x in b))
    return math.fsum(x * y for x, y in zip(a, b)) / (na * nb) if na and nb else 0.0


def _fuse(*rankings):
    scores = {}
    for ranking in rankings:
        for rank, (pid, _) in enumerate(ranking, 1):
            scores.setdefault(pid, []).append(1 / (RRF + rank))
    return _order((pid, math.fsum(parts)) for pid, parts in scores.items())


def _fingerprint(s, all_passages, arm):
    roles = s['roles']
    embed = profiles.profile_digest(roles['embedder']) if arm in EMBEDDING_ARMS and roles.get('embedder') else None
    rerank = profiles.profile_digest(roles['reranker']) if arm == 'reranked' and roles.get('reranker') else None
    index = {'tokenizer': TOKENIZER, 'backend': s['backend'], 'chunking': CHUNKING, 'embedder_sha256': embed, 'reranker_sha256': rerank,
             'passages': sorted([p['passage_id'], p['text_sha256']] for p in all_passages if p['namespace'] != 'template')}
    if s['backend'] == 'fts5' and fts5_available():
        import sqlite3
        index['sqlite_version'] = sqlite3.sqlite_version
    return embed, rerank, digest(index)


def _budget(items, left):
    taken = []
    for item in items:
        size = len(item['text'].split())
        if size > left:
            break
        taken.append(item)
        left -= size
    return taken, left


def retrieve(view, matter, arm, settings, reference=None) -> dict:
    """Retrieval result v1 of one arm for one matter: the evidence interface of the generation packages."""
    if arm not in ARMS:
        raise ValueError('Unknown retrieval arm: ' + str(arm))
    if arm == 'reference' and reference is None:
        raise ValueError('The reference arm needs the reference passages')
    if arm != 'reference' and reference is not None:
        raise ValueError('Only the reference arm receives the reference passages')
    s = _settings(settings)
    the_corpus = view['corpus']
    records = {(a['authority_id'], a['version']): a for a in the_corpus['authorities']}
    every = passages(view, matter)
    query = tokens(matter['question'])
    embed_sha, rerank_sha, fingerprint = _fingerprint(s, every, arm)
    result = {'schema_version': 1, 'matter_id': matter['matter_id'], 'arm': arm, 'status': 'ok', 'reason_codes': [],
              'query_sha256': digest(query), 'index_fingerprint': fingerprint,
              'settings': {'top_k': s['top_k'], 'token_budget': s['token_budget'], 'backend': s['backend'], 'tokenizer': TOKENIZER,
                           'chunking': CHUNKING, 'embedder_sha256': embed_sha, 'reranker_sha256': rerank_sha},
              'authorities': [], 'evidence': [], 'prior_briefs': [], 'adverse': [], 'excluded': [],
              'ranked_authorities': [], 'ranked_evidence': [], 'tokens': 0}
    absent = available_arms([arm], s)[arm]
    if absent:
        return {**result, 'status': 'unavailable', 'reason_codes': codes(absent)}
    reasons = []
    # Resolved once per call: the same policy and query as `authority.decide`, which `contrary` still calls.
    policy, q = authority.policy_or_none(the_corpus), authority.query_for(matter, the_corpus)
    decided = {}

    def annotate(p, score=None):
        key = (p['authority_id'], p['version'])
        if key not in decided:
            record = records[key]
            if policy is None:
                raise ValueError('A policy profile is required for this jurisdiction')
            decision, why = authority.eligible(authority.with_end_evidence(record, the_corpus), q, policy)
            decided[key] = {'decision': decision, 'reason_codes': codes(why)}, authority.weight(record, q, policy)
        eligibility, weight = decided[key]
        return {**p, 'score': score, 'eligibility': dict(eligibility, reason_codes=list(eligibility['reason_codes'])), 'weight': weight}
    own = {s_['source_id'] for s_ in matter['sources']}
    lists = {'authority': [p for p in every if p['namespace'] == 'authority'],
             'evidence': [p for p in every if p['namespace'] == 'evidence'],
             'prior_brief': [p for p in every if p['namespace'] == 'prior_brief']}
    by_id = {p['passage_id']: p for p in every}
    rankings = {}
    if arm in LEXICAL_ARMS:
        rank = _bm25_fts5 if s['backend'] == 'fts5' else _bm25_memory
        rankings['lexical'] = {name: rank(docs, query) for name, docs in lists.items()}
    if arm in EMBEDDING_ARMS:
        texts = [matter['question']] + [_document(p) for docs in lists.values() for p in docs]
        try:      # only the embedding request: a failure anywhere else is a bug, not an embedding error
            vectors = embedder(s['roles']['embedder'], s['allowed'])(texts)
        except TRANSPORT_ERRORS as exc:
            return {**result, 'status': 'error', 'reason_codes': codes('embedding_error'), 'error_type': type(exc).__name__}
        vector = dict(zip([p['passage_id'] for docs in lists.values() for p in docs], vectors[1:]))
        rankings['dense'] = {name: _order((p['passage_id'], _cosine(vectors[0], vector[p['passage_id']])) for p in docs)
                             for name, docs in lists.items()}

    excluded = []

    def eligible_only(ranking):
        kept = []
        for item in ranking:
            p = annotate(by_id[item[0]])
            if p['eligibility']['decision'] == 'ineligible':
                excluded.append({'passage_id': item[0], 'reason_codes': p['eligibility']['reason_codes']})
            else:
                kept.append(item)
        return kept
    filtered = arm in FILTERED_ARMS
    if arm in RANKED_ARMS:
        ranked = {}
        for name in lists:
            if arm in ('lexical', 'lexical-eligible'):
                r = rankings['lexical'][name]
            elif arm == 'dense':
                r = rankings['dense'][name]
            elif arm == 'hybrid':
                lexical = rankings['lexical'][name]
                dense = rankings['dense'][name]
                if name == 'authority':      # fused after the eligibility rule, so ranks count eligible versions only
                    lexical, dense = eligible_only(lexical), eligible_only(dense)
                r = _fuse(lexical, dense)
            else:
                r = rankings['lexical'][name]
            if name == 'authority' and filtered and arm != 'hybrid':
                r = eligible_only(r)
            ranked[name] = r
        if arm == 'reranked':
            try:      # the allowlist check and the rerank requests only
                score = reranker(s['roles']['reranker'], s['allowed'])
                values = {}
                for name in lists:
                    head = ranked[name][:4 * s['top_k']]
                    values[name] = score(matter['question'], [_document(by_id[pid]) for pid, _ in head]) if head else []
            except TRANSPORT_ERRORS as exc:
                return {**result, 'status': 'error', 'reason_codes': codes('reranker_error'), 'error_type': type(exc).__name__}
            for name in lists:
                head, tail = ranked[name][:4 * s['top_k']], ranked[name][4 * s['top_k']:]
                # The reranked head, then the BM25 tail that was not reranked, in BM25 order (with its BM25 scores).
                ranked[name] = _order((pid, value) for (pid, _), value in zip(head, values[name])) + tail
        result['ranked_authorities'], result['ranked_evidence'] = ranked['authority'], ranked['evidence']
        shown_auth = [annotate(by_id[pid], score) for pid, score in ranked['authority'][:s['top_k']]]
        shown_evidence = [{**by_id[pid], 'score': score} for pid, score in ranked['evidence'][:s['top_k']]]
        shown_briefs = [{**by_id[pid], 'score': score} for pid, score in ranked['prior_brief'][:s['top_k']]]
    elif arm == 'no-context':
        shown_auth, shown_briefs = [], []
        shown_evidence = [{**p, 'score': None} for p in lists['evidence'] if p['source_id'] in own]
    elif arm == 'filters-only':
        shown_auth = [annotate(by_id[pid]) for pid, _ in eligible_only([[p['passage_id'], None] for p in lists['authority']])]
        shown_evidence = [{**p, 'score': None} for p in lists['evidence']]
        shown_briefs = [{**p, 'score': None} for p in lists['prior_brief']]
    else:      # reference: the approved passages only, unranked and uncut by top_k
        shown_auth = [annotate(p) for p in reference['authorities']]
        shown_evidence = [{**p, 'score': None} for p in reference['evidence']]
        shown_briefs = []

    candidates = [pid for pid, _ in result['ranked_authorities']] if arm in RANKED_ARMS else [a['passage_id'] for a in shown_auth]
    if arm != 'no-context' and not any(annotate(by_id[pid])['eligibility']['decision'] == 'eligible' for pid in candidates):
        # No eligible authority at all among the arm's candidates: ineligible versions are not shown in its place;
        # versions of unknown validity stay, because unknown validity must be able to trigger a deferral.
        for a in shown_auth:
            if a['eligibility']['decision'] == 'ineligible':
                excluded.append({'passage_id': a['passage_id'], 'reason_codes': a['eligibility']['reason_codes']})
        shown_auth = [a for a in shown_auth if a['eligibility']['decision'] != 'ineligible']
        reasons.append('no_eligible_authority')

    left = s['token_budget']
    shown_auth, left = _budget(shown_auth, left)
    listed = {a['passage_id'] for a in shown_auth}
    adverse = []
    if arm == 'reference':
        adverse = [annotate(p) for p in reference['adverse'] if p['passage_id'] not in listed]
    elif arm != 'no-context':
        offence = next((a for a in shown_auth if a['eligibility']['decision'] == 'eligible'
                        and records[(a['authority_id'], a['version'])]['authority_type'] == 'offence'), None)
        if offence is not None:
            source = records[(offence['authority_id'], offence['version'])]
            adverse = [annotate(_authority_passage(r)) for r, _ in authority.contrary(source, the_corpus, matter)
                       if r['authority_id'] + '@' + r['version'] not in listed]
    size = sum(len(a['text'].split()) for a in adverse)
    if size > left:
        reasons.append('adverse_over_budget')
    left = max(0, left - size)
    ranked_in = [a for a in shown_auth if a['eligibility']['decision'] == 'unknown'
                 and records[(a['authority_id'], a['version'])]['authority_type'] == 'exemption']
    if ranked_in or any(a['eligibility']['decision'] == 'unknown' for a in adverse):
        reasons.append('adverse_validity_unknown')
    shown_evidence, left = _budget(shown_evidence, left)
    shown_briefs, left = _budget(shown_briefs, left)

    def ranks(items):
        return [{'rank': i, **item} for i, item in enumerate(items, 1)]
    result.update(authorities=ranks(shown_auth), adverse=ranks(adverse), evidence=ranks(shown_evidence), prior_briefs=ranks(shown_briefs),
                  excluded=sorted({e['passage_id']: e for e in excluded}.values(), key=lambda e: e['passage_id']),
                  reason_codes=codes(reasons),
                  tokens=sum(len(p['text'].split()) for p in shown_auth + adverse + shown_evidence + shown_briefs))
    return result


def gold_targets(suite, matter, gold) -> dict:
    """Gold id sets of one matter. `gold` is its rubric entry, or None to read it from the suite rubric."""
    entry = _entry(suite, matter) if gold is None else gold
    if _is_retrieval_entry(matter, entry):
        return {'evidence': set(entry.get('gold_spans', [])), 'authority': set(), 'ineligible': set(), 'adverse': set()}
    evidence = {i for spans in entry.get('evidence_spans', {}).values() for i in spans['support'] + spans['adverse']}
    evidence |= {i for spans in entry.get('exemption_spans', {}).values() for i in spans}
    key = lambda pair: pair[0] + '@' + pair[1]      # noqa: E731
    adverse = {key(p) for p in entry.get('established_exemptions', [])}
    controlling = {key(entry['controlling_authority'])} if entry.get('controlling_authority') else set()
    return {'evidence': evidence, 'authority': controlling | adverse,
            'ineligible': {key(p) for p in entry.get('ineligible_versions', [])}, 'adverse': adverse}


def _ndcg(ranking, gold):
    if not gold:
        return None
    dcg = math.fsum(1 / math.log2(i + 1) for i, (pid, _) in enumerate(ranking[:10], 1) if pid in gold)
    ideal = math.fsum(1 / math.log2(i + 1) for i in range(1, min(len(gold), 10) + 1))
    return _round(dcg / ideal)


def metrics(result, targets) -> dict:
    """The retrieval metrics of one result against its gold targets. None when a denominator is zero or the metric does
    not apply. Leakage is measured against the gold, never against the arm's own annotation. A result that did not run
    (`unavailable` or `error`) has no measured value: every metric is None."""
    if result.get('status', 'ok') != 'ok':
        return {k: None for k in METRICS}
    ranked = result['arm'] in RANKED_ARMS
    shown_auth = [a['passage_id'] for a in result['authorities'] + result['adverse']]
    shown_evidence = [e['passage_id'] for e in result['evidence']]
    controlling = targets['authority'] - targets['adverse']

    def at5(ranking, gold):
        return _ratio(len(gold & {pid for pid, _ in ranking[:5]}), len(gold)) if ranked else None
    return {
        'evidence_recall_at_5': at5(result['ranked_evidence'], targets['evidence']),
        'authority_recall_at_5': at5(result['ranked_authorities'], targets['authority']),
        'evidence_ndcg_at_10': _ndcg(result['ranked_evidence'], targets['evidence']) if ranked else None,
        'authority_ndcg_at_10': _ndcg(result['ranked_authorities'], targets['authority']) if ranked else None,
        'prompt_evidence_recall': _ratio(len(targets['evidence'] & set(shown_evidence)), len(targets['evidence'])),
        'prompt_authority_recall': _ratio(len(targets['authority'] & set(shown_auth)), len(targets['authority'])),
        'exact_version_recall': (1.0 if controlling <= set(shown_auth) else 0.0) if controlling else None,
        'ineligible_version_leakage': _ratio(sum(1 for p in shown_auth if p in targets['ineligible']), len(shown_auth)),
        'annotated_ineligible': sum(1 for a in result['authorities'] + result['adverse'] if a['eligibility']['decision'] == 'ineligible'),
        'adverse_authority_coverage': _ratio(len(targets['adverse'] & set(shown_auth)), len(targets['adverse'])),
        'retrieved_passages': len(shown_auth) + len(shown_evidence) + len(result['prior_briefs']),
        'retrieved_tokens': result['tokens'],
    }


def _shingles(text):
    words = tokens(text)
    return {tuple(words[i:i + 3]) for i in range(len(words) - 2)}


def audit_splits(suite_a, suite_b) -> dict:
    """Overlap between two suites by matter family, amendment pair and near-duplicate matter text, every list sorted."""
    def families(suite):
        return {m['family_id'] for m in suite['matters']['matters']}

    def gold_authorities(suite):
        found = set()
        for g in suite['rubric']['matters']:
            pairs = list(g.get('ineligible_versions', [])) + ([g['controlling_authority']] if g.get('controlling_authority') else [])
            found |= {p[0] for p in pairs}
        return found
    versions = {}
    for suite in (suite_a, suite_b):
        for a in suite['corpus']['authorities']:
            versions.setdefault(a['authority_id'], set()).add(a['version'])
    pairs = {i for i in gold_authorities(suite_a) & gold_authorities(suite_b) if len(versions.get(i, ())) > 1}

    def text(m):
        return ' '.join([m['question']] + [span['text'] for s in m['sources'] if s['role'] == 'evidence' for span in s['spans']])
    near = []
    shingled_b = [(m['matter_id'], _shingles(text(m))) for m in suite_b['matters']['matters']]
    for m in suite_a['matters']['matters']:
        a = _shingles(text(m))
        for other, b in shingled_b:
            if a | b:
                similarity = Fraction(len(a & b), len(a | b))
                if similarity >= Fraction(4, 5):
                    near.append([m['matter_id'], other, _round(similarity)])
    return {'shared_families': sorted(families(suite_a) & families(suite_b)), 'shared_amendment_pairs': sorted(pairs),
            'near_duplicates': sorted(near)}


# The `retrieval` mode -------------------------------------------------------------------------------------------------

def _served(parameters):
    """The role profiles a requested arm uses, by role name."""
    arms = parameters.get('arms') if isinstance(parameters.get('arms'), list) else []
    roles = parameters.get('roles') if isinstance(parameters.get('roles'), dict) else {}
    used = {ARM_ROLES[a] for a in arms if isinstance(a, str) and a in ARM_ROLES}
    return {r: roles[r] for r in sorted(used) if isinstance(roles.get(r), dict)}


def host(parameters, mode):
    """The explicit host requirement: the hardware-profile GPU only when a role of the job is GPU-served."""
    roles = parameters.get('roles') if isinstance(parameters.get('roles'), dict) else {}
    return {'gpu': any(isinstance(r, dict) and r.get('accelerator') == 'gpu' for r in roles.values())}


def execution_kind(parameters, mode):
    """`model-run` when a requested arm uses a served role (anything but the in-process fixtures); else `fixture`.
    The profiles are validated first, so a profile without `serving` is refused, not counted as a model run."""
    served = _served(parameters)
    for name, profile in served.items():
        profiles.validate_role(profile, name)
    return 'model-run' if any(p['serving'] != 'in-process' for p in served.values()) else 'fixture'


def _reference_size(reference):
    return sum(len(p['text'].split()) for key in ('authorities', 'adverse', 'evidence') for p in reference[key])


def check(parameters, suite, root, mode):
    arms = parameters['arms']
    if not isinstance(arms, list) or not arms or any(not isinstance(a, str) or a not in ARMS for a in arms) or len(set(arms)) != len(arms):
        raise ValueError('arms must be a nonempty list of distinct retrieval arms: ' + ', '.join(ARMS))
    integer(parameters.get('top_k', 5), 'top_k', 1, 50)
    budget = integer(parameters.get('token_budget', 1200), 'token_budget', 64, 32768)
    if parameters.get('backend', 'auto') not in BACKENDS:
        raise ValueError('backend must be auto, memory or fts5')
    roles = parameters.get('roles', {})
    if not isinstance(roles, dict) or set(roles) - {'embedder', 'reranker'}:
        raise ValueError('roles may hold only the embedder and reranker roles')
    for name, profile in sorted(roles.items()):
        profiles.validate_role(profile, name)
    matters = sorted(suite['matters']['matters'], key=lambda m: m['matter_id'])
    for m in matters:
        authority.query_for(m, suite['corpus'])
    if 'reference' in arms:
        for m in matters:
            if _reference_size(reference_passages(suite, m)) > budget:
                raise ValueError('Reference passages exceed the token budget: ' + m['matter_id'])
    return None


PRIVATE_FIELDS = ('text', 'citation', 'title')


def _private(result, values):
    def strip(p):
        p = {k: v for k, v in p.items() if k not in PRIVATE_FIELDS}
        if 'elements' in p:
            p['elements'] = [{'element_id': e['element_id']} for e in p['elements']]
        return p
    lists = ('authorities', 'evidence', 'prior_briefs', 'adverse')
    return {**{k: v for k, v in result.items() if k not in lists}, **{k: [strip(p) for p in result[k]] for k in lists}, 'metrics': values}


def run(job, suite, output, root):
    """Every requested arm for every matter, in matter-id order and the requested arm order. Grades the retrieval result
    (exact version and leakage); writes no score detail and no text to a public file."""
    from . import MANIFEST, job_status
    parameters = job['parameters']
    roles = _served(parameters)      # only the roles a requested arm uses: an unused role is neither recorded nor allowed
    profiles.check_revisions(roles)
    profiles.check_job(roles, job)
    allowed = profiles.allowed_endpoints(roles)
    view = contracts.candidate_view(suite)
    backend, backend_codes = resolve_backend(suite, parameters.get('backend', 'auto'))
    settings = {'top_k': parameters.get('top_k', 5), 'token_budget': parameters.get('token_budget', 1200), 'backend': backend,
                'roles': roles, 'allowed': allowed}
    kind = execution_kind(parameters, job['mode'])
    policy = authority.policy_or_none(suite['corpus'])      # None: no policy and no authority, so nothing was decided
    policy_id, policy_version = (policy['policy_id'], policy['version']) if policy else (None, None)
    lock = suite['lock']
    gold = {g['matter_id']: g for g in suite['rubric']['matters']}
    rows, results, fingerprints = [], [], []
    statuses = {'ok': 'ok', 'unavailable': 'missing', 'error': 'error'}
    for m in sorted(suite['matters']['matters'], key=lambda m: m['matter_id']):
        targets = gold_targets(suite, m, gold[m['matter_id']])
        for arm in parameters['arms']:
            started = time.perf_counter()
            reference = reference_passages(suite, m) if arm == 'reference' else None
            result = retrieve(view, m, arm, settings, reference)
            elapsed = time.perf_counter() - started
            result['reason_codes'] = codes(result['reason_codes'], backend_codes)
            ok = result['status'] == 'ok'
            values = metrics(result, targets)
            fingerprints.append(result['index_fingerprint'])
            shown = [p['passage_id'] for key in ('authorities', 'adverse', 'evidence', 'prior_briefs') for p in result[key]]
            # A reference row publishes no number: each would be a function of the reference passages (the oracle), and a
            # reader with the candidate files could recover them. The values stay in the private results file.
            oracle = arm == 'reference'
            public = {k: None for k in PUBLIC_METRICS} if oracle else {k: values[k] for k in PUBLIC_METRICS}
            applicable = not oracle and values['exact_version_recall'] is not None
            row = {'task_id': m['matter_id'], 'family_id': m['family_id'], 'category': arm, 'benchmark': lock['benchmark_id'], 'arm': arm,
                   'repetition': 0, 'warmup': False, 'synthetic': kind == 'fixture', 'execution_kind': kind, 'data_class': lock['data_class'],
                   'status': statuses[result['status']], 'retrieval_status': result['status'], 'inference_status': 'not_applicable',
                   'parse_status': 'not_applicable', 'verification_status': 'not_applicable', 'review_status': 'not_applicable',
                   'grading_status': 'scored' if ok and not oracle else 'not_applicable',
                   'reason_codes': codes(backend_codes) if oracle else result['reason_codes'], 'elapsed_s': elapsed,
                   **public, 'quality_check_applicable': applicable,
                   'quality_pass': (values['exact_version_recall'] == 1.0 and values['ineligible_version_leakage'] in (0, None)) if applicable else None}
            if result['status'] == 'error':
                row['error_type'] = result['error_type']
            rows.append(row)
            # The digest of the shown ids stays private: with the candidate files it would give the oracle away.
            results.append({**_private(result, values), 'evidence_sha256': digest(shown), 'policy_id': policy_id,
                            'policy_version': policy_version})
    output = Path(output)
    private = contracts.private_file(output, 'retrieval-results.jsonl')
    for path, items in ((output / 'requests.jsonl', rows), (private, results)):
        path.write_text(''.join(json.dumps(item, sort_keys=True) + '\n' for item in items), encoding='utf-8', newline='\n')
    embedder_profile, reranker_profile = roles.get('embedder'), roles.get('reranker')
    atomic_json(output / 'metadata.json', {
        'schema_version': 1, 'experiment': MANIFEST['id'], 'mode': job['mode'], 'execution_kind': kind, 'synthetic': kind == 'fixture',
        'data_class': lock['data_class'], 'benchmark_id': lock['benchmark_id'], 'suite_revision': lock['revision'], 'split_id': lock['split_id'],
        'jurisdiction_profile': lock['jurisdiction_profile'], 'suite_lock_sha256': suite['lock_sha256'],
        'rubric_version': suite['rubric'].get('rubric_version'), 'policy_id': policy_id, 'policy_version': policy_version,
        'arms': list(parameters['arms']),
        'retrieval': {'backend': backend, 'top_k': settings['top_k'], 'token_budget': settings['token_budget'], 'tokenizer': TOKENIZER,
                      'chunking': CHUNKING, 'index_fingerprint': digest(sorted(fingerprints)),
                      'embedder_sha256': profiles.profile_digest(embedder_profile, job.get('input_files', ())) if embedder_profile else None,
                      'reranker_sha256': profiles.profile_digest(reranker_profile, job.get('input_files', ())) if reranker_profile else None},
        'roles': {name: profiles.public_role(profile, job.get('input_files', ())) for name, profile in sorted(roles.items())},
        'matters': len({r['task_id'] for r in rows}), 'families': len({r['family_id'] for r in rows}), 'rows': len(rows),
        'review_required': True})
    return {'status': job_status(rows), 'result_path': '.', 'benchmark': lock['benchmark_id']}
