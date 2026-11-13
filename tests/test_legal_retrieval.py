"""Authority eligibility, retrieval arms, role profiles and the `retrieval` mode of the legal benchmark.

Every record, matter and suite built here is original and fictional. No model, network or GPU is used: the only
servers are loopback fakes started by the test on an ephemeral port.
"""
import copy
import importlib.util
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
from pathlib import Path
import re
import shutil
import tempfile
import threading
import unittest
from unittest.mock import patch

from llm_eval.common import digest, read_json, sha256_file, write_json
from llm_eval.core.contracts import atomic_json
from llm_eval.experiments import get_experiment
from llm_eval.experiments import legal_benchmark as legal
from llm_eval.experiments.legal_benchmark import authority, contracts, fixture, profiles, retrieval
from llm_eval.orchestration.planner import compile_campaign
from llm_eval.orchestration.scheduler import initialize, run_campaign

ROOT = Path(__file__).resolve().parents[1]
SUITE = ROOT / 'experiments/legal-benchmark/workloads/original-smoke'
LOCK = SUITE / 'suite.lock.json'
PACKETS = ROOT / 'experiments/legal-benchmark/workloads/original-packets/suite.lock.json'
EVIDENCE_SENTENCE = 'The purser admits he knew the count was lower.'
P = authority.DEFAULT_POLICY
EMBEDDER = {'role': 'embedder', 'serving': 'in-process', 'platform': 'fixture-hash', 'model': 'fixture-hash', 'model_revision': '1',
            'capability': 'embedding', 'dimensions': 64}
RERANKER = {'role': 'reranker', 'serving': 'in-process', 'platform': 'fixture-overlap', 'model': 'fixture-overlap', 'model_revision': '1',
            'capability': 'rerank'}
ROLES = {'embedder': EMBEDDER, 'reranker': RERANKER}
AUTHORITY_PASSAGE_KEYS = {'passage_id', 'namespace', 'authority_id', 'version', 'pinpoint', 'citation', 'title', 'issuer', 'venues',
                          'effective_from', 'effective_to', 'status', 'elements', 'text', 'text_sha256'}
SOURCE_PASSAGE_KEYS = {'passage_id', 'namespace', 'source_id', 'role', 'text', 'text_sha256'}
PUBLIC_METRICS = ('evidence_recall_at_5', 'authority_recall_at_5', 'evidence_ndcg_at_10', 'authority_ndcg_at_10', 'prompt_evidence_recall',
                  'prompt_authority_recall', 'exact_version_recall', 'ineligible_version_leakage', 'adverse_authority_coverage',
                  'retrieved_passages', 'retrieved_tokens')
ROW_KEYS = {'task_id', 'family_id', 'category', 'benchmark', 'arm', 'repetition', 'warmup', 'synthetic', 'execution_kind', 'data_class',
            'status', 'retrieval_status', 'inference_status', 'parse_status', 'verification_status', 'review_status', 'grading_status',
            'reason_codes', 'elapsed_s', 'quality_check_applicable', 'quality_pass', *PUBLIC_METRICS}
METADATA_KEYS = {'schema_version', 'experiment', 'mode', 'execution_kind', 'synthetic', 'data_class', 'benchmark_id', 'suite_revision',
                 'split_id', 'jurisdiction_profile', 'suite_lock_sha256', 'rubric_version', 'policy_id', 'policy_version', 'arms',
                 'retrieval', 'roles', 'matters', 'families', 'rows', 'review_required'}


def record(authority_id='vtc-1-1', version='2020', text='A person who fictionally misplaces a ledger commits an offence.', **changes):
    """An original, fictional authority version with a valid text digest."""
    value = {'authority_id': authority_id, 'version': version, 'citation': 'Veld Test Code ' + authority_id, 'title': 'Fictional test offence',
             'issuer': 'Assembly of Veld (fictional)', 'authority_type': 'offence', 'venues': ['veld-central'], 'effective_from': '2020-01-01',
             'effective_to': None, 'status': 'in_force', 'pinpoint': 's1(1)', 'text': text, 'text_sha256': contracts.text_digest(text),
             'elements': [{'element_id': 'act', 'description': 'Evidence of the act.', 'terms': ['misplaced the ledger']}]}
    value.update(changes)
    return value


def corpus(authorities, **changes):
    value = {'schema_version': 1, 'data_class': 'public-synthetic', 'jurisdiction_profile': 'veld-fictional-v1', 'source_set': 'candidate',
             'venues': ['veld-central', 'veld-harbor'], 'authorities': authorities}
    value.update(changes)
    return value


def source(source_id, texts, role='evidence', **changes):
    spans = [{'span_id': f'{source_id}#{i}', 'text': t, 'text_sha256': contracts.text_digest(t)} for i, t in enumerate(texts, 1)]
    return {'source_id': source_id, 'role': role, 'version': '1', 'kind': 'report', 'spans': spans, **changes}


def matter(matter_id='fx-a', day='2025-03-01', venue='veld-central', question='Does misplacing the ledger support a charge?',
           sources=None, family_id=None, posture='screening'):
    return {'matter_id': matter_id, 'family_id': family_id or matter_id.rsplit('-', 1)[0], 'operative_date': day, 'venue': venue,
            'posture': posture, 'question': question, 'output_schema': 'candidate-output-v1',
            'sources': sources if sources is not None else [source(matter_id + '-s1', ['The clerk misplaced the ledger on the stated date.'])]}


def suite_of(the_corpus, matters, rubric=(), data_class=None, **extra):
    data_class = data_class or the_corpus['data_class']
    lock = {'schema_version': 1, 'benchmark_id': 'legal-test-dict', 'revision': 't1', 'split_id': 'test', 'data_class': data_class,
            'jurisdiction_profile': 'veld-fictional-v1', 'source_files': []}
    manifest = {'schema_version': 1, 'data_class': data_class, 'jurisdiction_profile': 'veld-fictional-v1', 'source_set': 'candidate',
                'matters': list(matters)}
    manifest.update({k: v for k, v in extra.items() if k == 'shared_sources'})
    value = {'lock': lock, 'lock_sha256': 'a' * 64, 'corpus': the_corpus, 'matters': manifest,
             'rubric': {'rubric_version': 'test', 'matters': list(rubric)}}
    value.update({k: v for k, v in extra.items() if k != 'shared_sources'})
    return value


def query(day, venue='veld-central', jurisdiction=None, posture='screening', cutoff=None):
    return {'operative_date': day, 'venue': venue, 'jurisdiction': jurisdiction, 'posture': posture, 'availability_cutoff': cutoff}


def smoke():
    suite = contracts.load_suite(LOCK)
    return suite, {m['matter_id']: m for m in suite['matters']['matters']}, {g['matter_id']: g for g in suite['rubric']['matters']}


def ids(items):
    return [p['passage_id'] for p in items]


def relock(directory, **changes):
    lock = read_json(directory / 'suite.lock.json')
    new = contracts.make_lock(directory, benchmark_id=lock['benchmark_id'], revision=lock['revision'], split_id=lock['split_id'],
                              data_class=lock['data_class'], jurisdiction_profile=lock['jurisdiction_profile'],
                              manifests={'matters': 'matters.json', 'corpus': 'corpus.json', 'rubric': 'rubric.json'})
    new.update(changes)
    write_json(directory / 'suite.lock.json', new)
    return directory / 'suite.lock.json'


def job_for(lock, parameters, mode='retrieval'):
    # A planned job reserves the physical host of its target; served roles run on that host (package E's `check_job`).
    return {'mode': mode, 'parameters': {'suite': str(lock), **parameters}, 'target': {'transport': 'local', 'physical_host_id': 'legal-test-host'},
            'resources': ['legal-test-host'], 'hardware': {'hardware_profile': 'msi-raider-18-hx-ai', 'os_id': 'ubuntu-26.04-native'},
            'input_files': [{'path': str(lock), 'sha256': sha256_file(lock)}]}


def lines(path):
    return [json.loads(line) for line in Path(path).read_text(encoding='utf-8').splitlines()]


def external(role='embedder', port=9, **changes):
    capability = profiles.CAPABILITY[role]
    value = {'role': role, 'serving': 'external', 'capability': capability, 'deployment_id': 'local-' + role, 'platform': 'fake-' + role,
             'backend_version': '1.0', 'model': 'fake-' + role, 'model_revision': 'r1',
             'protocol': 'openai' if capability == 'chat' else 'json', 'endpoint': f'http://127.0.0.1:{port}/v1/' + role,
             'accelerator': 'cpu', 'timeout_s': 10}
    if capability == 'chat':
        value.update(context_tokens=8192, max_output_tokens=1024)
    if role == 'embedder':
        value['dimensions'] = 8
    value.update(changes)
    return value


class FakeServer:
    """A loopback JSON endpoint that records every request it receives."""

    def __init__(self, reply):
        self.requests = []
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                owner.requests.append({'path': self.path, 'payload': payload})
                data = json.dumps(reply(payload)).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.port = self.server.server_port
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()


class Exploding:
    """A rubric stand-in that fails on every access, so a test proves which functions never read the rubric."""

    def _fail(self, *args, **kwargs):
        raise AssertionError('the rubric was read')

    __getitem__ = __iter__ = __len__ = __contains__ = get = keys = items = values = _fail

    def __getattr__(self, name):
        raise AssertionError('the rubric was read')


class EligibilityTests(unittest.TestCase):
    def test_effective_date_boundaries_are_inclusive_then_exclusive(self):
        source = {'venues': ['veld-central'], 'effective_from': '2024-03-01', 'effective_to': '2025-01-01', 'status': 'in_force'}
        check = lambda day, policy=P: authority.eligible(source, query(day), policy)      # noqa: E731
        self.assertEqual(check('2024-02-29'), ('ineligible', ['not_yet_effective']))
        self.assertEqual(check('2024-03-01'), ('eligible', []))                          # first day applies
        self.assertEqual(check('2024-12-31'), ('eligible', []))                          # last day applies
        self.assertEqual(check('2025-01-01'), ('ineligible', ['no_longer_effective']))   # effective_to is the first day it no longer applies
        flipped = {**P, 'effective_from_inclusive': False, 'effective_to_inclusive': True}
        self.assertEqual(check('2024-03-01', flipped), ('ineligible', ['not_yet_effective']))
        self.assertEqual(check('2024-03-02', flipped), ('eligible', []))
        self.assertEqual(check('2025-01-01', flipped), ('eligible', []))
        self.assertEqual(check('2025-01-02', flipped), ('ineligible', ['no_longer_effective']))
        # The corpus policy is what `decide` applies.
        r = record(effective_from='2024-03-01', effective_to='2025-01-01')
        policy = {'policy_id': 'boundary-test', 'version': '1', 'effective_to_inclusive': True}
        self.assertEqual(authority.decide(r, matter(day='2025-01-01'), corpus([r])), ('ineligible', ['no_longer_effective']))
        self.assertEqual(authority.decide(r, matter(day='2025-01-01'), corpus([r], policy=policy)), ('eligible', []))

    def test_future_sources_are_unavailable_after_the_corpus_cutoff(self):
        cutoff = '2025-06-30'
        source = {'venues': ['veld-central'], 'effective_from': '2020-01-01', 'effective_to': '2026-01-01', 'status': 'in_force'}
        on_cutoff = {**source, 'snapshot': {'id': 'gazette-1', 'published': '2025-06-30'}}
        later = {**source, 'snapshot': {'id': 'gazette-2', 'published': '2025-07-01'}}
        self.assertEqual(authority.eligible(on_cutoff, query('2025-06-01', cutoff=cutoff), P), ('eligible', []))
        self.assertEqual(authority.eligible(later, query('2025-06-01', cutoff=cutoff), P), ('ineligible', ['not_yet_available']))
        self.assertEqual(authority.eligible(later, query('2025-06-01'), P), ('eligible', []))          # no cutoff: no leakage rule
        # Validity follows the operative date: published before the cutoff but not yet in force on the operative day.
        enacted = {**on_cutoff, 'effective_from': '2025-08-01'}
        self.assertEqual(authority.eligible(enacted, query('2025-07-15', cutoff=cutoff), P), ('ineligible', ['not_yet_effective']))
        # A missing snapshot with a cutoff is unknown in the pure rule and a load error for a record.
        self.assertEqual(authority.eligible(source, query('2025-06-01', cutoff=cutoff), P), ('unknown', ['availability_unverified']))
        r = record()
        with self.assertRaisesRegex(ValueError, 'An availability cutoff needs a publication snapshot: vtc-1-1@2020'):
            authority.validate_record(r, corpus([r], availability_cutoff=cutoff))
        with self.assertRaisesRegex(ValueError, 'An availability cutoff needs a publication snapshot'):
            contracts.validate_corpus(corpus([r], availability_cutoff=cutoff), {})
        # An open-ended version: the frozen corpus cannot show it was still in force after the cutoff.
        open_ended = {**on_cutoff, 'effective_to': None}
        self.assertEqual(authority.eligible(open_ended, query('2025-07-01', cutoff=cutoff), P), ('unknown', ['validity_unknown_after_cutoff']))
        self.assertEqual(authority.eligible(open_ended, query('2025-06-30', cutoff=cutoff), P), ('eligible', []))
        # After the cutoff the corpus knows only what was published by then. An end recorded without evidence dated on or
        # before the cutoff is not known: the version is unknown both before and after that recorded end.
        self.assertEqual(authority.eligible(on_cutoff, query('2025-07-15', cutoff=cutoff), P), ('unknown', ['validity_unknown_after_cutoff']))
        self.assertEqual(authority.eligible(on_cutoff, query('2026-02-01', cutoff=cutoff), P), ('unknown', ['validity_unknown_after_cutoff']))
        self.assertEqual(authority.eligible(on_cutoff, query('2026-02-01'), P), ('ineligible', ['no_longer_effective']))      # no cutoff
        self.assertEqual(authority.eligible(on_cutoff, query('2025-06-30', cutoff=cutoff), P), ('eligible', []))      # on the cutoff: unchanged
        # Evidence of the end dated on or before the cutoff (status_as_of): the ordinary interval rule applies.
        attested = {**on_cutoff, 'status_as_of': '2025-06-30'}
        self.assertEqual(authority.eligible(attested, query('2025-07-15', cutoff=cutoff), P), ('eligible', []))
        self.assertEqual(authority.eligible(attested, query('2026-02-01', cutoff=cutoff), P), ('ineligible', ['no_longer_effective']))
        self.assertEqual(authority.eligible({**on_cutoff, 'status_as_of': '2025-07-01'}, query('2026-02-01', cutoff=cutoff), P),
                         ('unknown', ['validity_unknown_after_cutoff']))      # evidence dated after the cutoff does not count
        ended = {**on_cutoff, 'effective_to': '2025-03-01'}      # an end on or before the cutoff had happened when the corpus froze
        self.assertEqual(authority.eligible(ended, query('2025-07-01', cutoff=cutoff), P), ('ineligible', ['no_longer_effective']))
        # Review probe p8b, cutoff 2024-01-01. Repealed, end recorded after the cutoff: known only with dated evidence.
        repealed = record('vtc-2-1', '2015', effective_from='2015-01-01', effective_to='2024-06-01', status='repealed',
                          snapshot={'id': 's', 'published': '2023-01-01'})
        for day in ('2024-03-01', '2024-06-01', '2025-01-01'):
            self.assertEqual(authority.decide(repealed, matter(day=day), corpus([repealed], availability_cutoff='2024-01-01')),
                             ('unknown', ['validity_unknown_after_cutoff']))
        known = {**repealed, 'status_as_of': '2023-12-01'}
        decided = [authority.decide(known, matter(day=d), corpus([known], availability_cutoff='2024-01-01'))
                   for d in ('2023-12-01', '2024-03-01', '2024-06-01', '2025-01-01')]
        self.assertEqual(decided, [('eligible', []), ('eligible', []), ('ineligible', ['no_longer_effective']), ('ineligible', ['no_longer_effective'])])
        # The paired amendment with a cutoff between the two versions (review probe p8).
        old = record('vtc-1-1', '2019', effective_from='2019-01-01', effective_to='2024-03-01', status='superseded',
                     snapshot={'id': 's2019', 'published': '2019-01-01'})
        new = record('vtc-1-1', '2024', effective_from='2024-03-01', snapshot={'id': 's2024', 'published': '2024-02-01'})
        amended = corpus([old, new], availability_cutoff='2024-01-01')
        late = matter(day='2025-06-10')
        self.assertEqual(authority.decide(old, late, amended), ('unknown', ['validity_unknown_after_cutoff']))
        self.assertEqual(authority.decide(new, late, amended), ('ineligible', ['not_yet_available']))
        shown = retrieval.retrieve(contracts.candidate_view(suite_of(amended, [late])), late, 'lexical-eligible', {})
        self.assertEqual([(a['passage_id'], a['eligibility']['decision']) for a in shown['authorities']], [('vtc-1-1@2019', 'unknown')])
        self.assertEqual(shown['excluded'], [{'passage_id': 'vtc-1-1@2024', 'reason_codes': ['not_yet_available']}])
        before = matter(day='2023-12-01')      # on or before the cutoff: unchanged
        self.assertEqual((authority.decide(old, before, amended), authority.decide(new, before, amended)),
                         (('eligible', []), ('ineligible', ['not_yet_effective', 'not_yet_available'])))
        between = matter(day='2024-02-01')      # after the cutoff, before the recorded end: the end is not known either way
        self.assertEqual(authority.decide(old, between, amended), ('unknown', ['validity_unknown_after_cutoff']))
        # A successor published on or before the cutoff makes the end known: v2019 is ineligible again and not shown.
        announced = record('vtc-1-1', '2024', effective_from='2024-03-01', snapshot={'id': 's2024', 'published': '2023-06-01'})
        succeeded = corpus([old, announced], availability_cutoff='2024-01-01')
        self.assertEqual(authority.decide(old, late, succeeded), ('ineligible', ['no_longer_effective']))
        self.assertEqual(authority.decide(old, between, succeeded), ('eligible', []))
        self.assertEqual(fixture.decide(old, late, succeeded), authority.decide(old, late, succeeded))
        self.assertEqual(authority.resolve_citation({'authority_id': 'vtc-1-1', 'version': '2019'}, succeeded, late)['decision'], 'ineligible')
        shown = retrieval.retrieve(contracts.candidate_view(suite_of(succeeded, [late])), late, 'lexical-eligible', {})
        self.assertNotIn('vtc-1-1@2019', ids(shown['authorities']))
        self.assertIn({'passage_id': 'vtc-1-1@2019', 'reason_codes': ['no_longer_effective']}, shown['excluded'])
        self.assertEqual(authority.decide(old, late, corpus([old], availability_cutoff='2024-01-01')), ('unknown', ['validity_unknown_after_cutoff']))
        dated = record(snapshot={'id': 'gazette-1', 'published': '2025-06-30'})
        self.assertEqual(authority.decide(dated, matter(day='2025-07-01'), corpus([dated], availability_cutoff=cutoff)),
                         ('unknown', ['validity_unknown_after_cutoff']))

    def test_wrong_venue_and_jurisdiction_are_ineligible(self):
        source = {'venues': ['veld-central'], 'effective_from': '2020-01-01', 'effective_to': None, 'status': 'in_force'}
        self.assertEqual(authority.eligible(source, query('2025-01-01', 'veld-harbor'), P), ('ineligible', ['wrong_venue']))
        foreign = {**source, 'jurisdiction': 'other-fictional-v1'}
        self.assertEqual(authority.eligible(foreign, query('2025-01-01', jurisdiction='veld-fictional-v1'), P),
                         ('ineligible', ['wrong_jurisdiction']))
        self.assertEqual(authority.eligible(foreign, query('2025-01-01', 'veld-harbor', jurisdiction='veld-fictional-v1'), P),
                         ('ineligible', ['wrong_jurisdiction', 'wrong_venue']))
        self.assertEqual(authority.eligible(foreign, query('2025-01-01'), P), ('eligible', []))      # no query jurisdiction: not checked
        self.assertEqual(authority.eligible(source, query('2025-01-01', jurisdiction='veld-fictional-v1'), P), ('eligible', []))
        r = record(jurisdiction='other-fictional-v1')
        self.assertEqual(authority.decide(r, matter(), corpus([r])), ('ineligible', ['wrong_jurisdiction']))
        # A policy for another jurisdiction is refused, never applied to this corpus under its own profile.
        policy = {'policy_id': 'other', 'version': '1', 'jurisdiction': 'other-fictional-v1'}
        with self.assertRaisesRegex(ValueError, 'The policy jurisdiction differs from the corpus jurisdiction profile'):
            contracts.validate_corpus(corpus([record()], policy=policy), {})
        with self.assertRaisesRegex(ValueError, 'The policy jurisdiction differs'):
            authority.decide(record(), matter(), corpus([record()], policy=policy))
        same = {**policy, 'jurisdiction': 'veld-fictional-v1'}
        self.assertEqual(authority.decide(record(), matter(), corpus([record()], policy=same)), ('eligible', []))
        self.assertEqual(authority.decide(record(), matter(venue='veld-harbor'), corpus([record()])), ('ineligible', ['wrong_venue']))

    def test_obsolete_status_and_uncertain_treatment(self):
        source = {'venues': ['veld-central'], 'effective_from': '2020-01-01', 'effective_to': None, 'status': 'invalidated'}
        for day in ('2020-01-01', '2024-06-01', '2031-12-31'):
            self.assertEqual(authority.eligible(source, query(day), P), ('ineligible', ['obsolete_status']))
        repealed = {**source, 'status': 'repealed'}
        self.assertEqual(authority.eligible(repealed, query('2024-06-01'), P), ('ineligible', ['obsolete_status']))
        for status in ('repealed', 'superseded'):
            r = record(status=status)
            with self.assertRaisesRegex(ValueError, 'An obsolete authority needs effective_to: vtc-1-1@2020'):
                authority.validate_record(r, corpus([r]))
            with self.assertRaisesRegex(ValueError, 'An obsolete authority needs effective_to'):
                contracts.validate_corpus(corpus([r]), {})
        closed = record(status='repealed', effective_to='2024-01-01')
        authority.validate_record(closed, corpus([closed]))
        self.assertEqual(authority.decide(closed, matter(day='2023-12-31'), corpus([closed])), ('eligible', []))
        unknown = {**source, 'status': 'unknown'}
        self.assertEqual(authority.eligible(unknown, query('2024-06-01'), P), ('unknown', ['validity_unknown']))
        strict = {**P, 'require_status_as_of': True}
        live = {**source, 'status': 'in_force'}
        self.assertEqual(authority.eligible(live, query('2024-06-01'), strict), ('unknown', ['treatment_unverified']))
        self.assertEqual(authority.eligible({**live, 'status_as_of': None}, query('2024-06-01'), strict), ('unknown', ['treatment_unverified']))
        self.assertEqual(authority.eligible({**live, 'status_as_of': '2024-05-31'}, query('2024-06-01'), strict), ('unknown', ['treatment_unverified']))
        self.assertEqual(authority.eligible({**live, 'status_as_of': '2024-06-01'}, query('2024-06-01'), strict), ('eligible', []))
        self.assertEqual(authority.eligible({**unknown, 'status_as_of': '2024-05-31'}, query('2024-06-01'), strict),
                         ('unknown', ['validity_unknown', 'treatment_unverified']))

    def test_controlling_and_persuasive_labels_follow_the_posture_profile(self):
        source = {'venues': ['veld-central'], 'effective_from': '2020-01-01', 'effective_to': None, 'status': 'in_force'}
        persuasive = {**source, 'weight': 'persuasive'}
        self.assertEqual(authority.weight(source, query('2025-01-01'), P), 'controlling')
        self.assertEqual(authority.weight(persuasive, query('2025-01-01'), P), 'persuasive')
        self.assertEqual(authority.eligible(persuasive, query('2025-01-01'), P), ('eligible', ['persuasive_only']))
        closed = {**P, 'postures': {'screening': {'persuasive_eligible': False}, 'retrieval': {'persuasive_eligible': True}}}
        self.assertEqual(authority.eligible(persuasive, query('2025-01-01'), closed), ('ineligible', ['persuasive_not_permitted']))
        self.assertEqual(authority.eligible(persuasive, query('2025-01-01', posture='retrieval'), closed), ('eligible', ['persuasive_only']))
        self.assertEqual(authority.eligible(source, query('2025-01-01'), closed), ('eligible', []))
        # A court outside the venue's binding courts is persuasive; inside them it controls.
        court = {**source, 'court': 'veld-high-court'}
        self.assertEqual(authority.eligible(court, query('2025-01-01'), P), ('eligible', ['persuasive_only']))
        binding = {**P, 'binding_courts': {'veld-central': ['veld-high-court']}}
        self.assertEqual(authority.weight(court, query('2025-01-01'), binding), 'controlling')
        self.assertEqual(authority.eligible(court, query('2025-01-01'), binding), ('eligible', []))
        self.assertEqual(authority.weight(court, query('2025-01-01', 'veld-harbor'), binding), 'persuasive')
        # A posture the policy does not list: the pure rule never raises, `query_for` does.
        self.assertEqual(authority.eligible(persuasive, query('2025-01-01', posture='appeal'), P), ('ineligible', ['persuasive_not_permitted']))
        self.assertEqual(authority.eligible(source, query('2025-01-01', posture='appeal'), P), ('eligible', []))
        with self.assertRaisesRegex(ValueError, 'Policy has no profile for posture: appeal'):
            authority.query_for(matter(posture='appeal'), corpus([record()]))

    def test_default_policy_is_limited_to_public_synthetic_corpora(self):
        reviewed = {'snapshot': {'id': 'gazette-1', 'published': '2025-01-01'}, 'status_as_of': '2025-01-01',
                    'review': {'reviewer_role': 'fixture-reviewer', 'reviewed_on': '2025-01-02'}}
        policy = {'policy_id': 'veld-reviewed', 'version': '1', 'review': {'reviewer_role': 'fixture-reviewer', 'reviewed_on': '2025-01-02'}}
        benchmark = corpus([record(**reviewed)], data_class='public-benchmark')
        with self.assertRaisesRegex(ValueError, 'A policy profile is required for this jurisdiction'):
            contracts.validate_corpus(benchmark, {})
        with self.assertRaisesRegex(ValueError, 'A policy profile is required for this jurisdiction'):
            authority.policy_for(benchmark)
        with self.assertRaisesRegex(ValueError, 'A reviewed corpus needs a reviewed policy'):
            contracts.validate_corpus({**benchmark, 'policy': {k: v for k, v in policy.items() if k != 'review'}}, {})
        contracts.validate_corpus({**benchmark, 'policy': policy}, {})
        for key in reviewed:
            with self.subTest(missing=key):
                partial = {k: v for k, v in reviewed.items() if k != key}
                with self.assertRaisesRegex(ValueError, 'A reviewed corpus needs snapshot, status_as_of and review: vtc-1-1@2020'):
                    contracts.validate_corpus(corpus([record(**partial)], data_class='public-benchmark', policy=policy), {})
        bare = corpus([], data_class='public-benchmark')
        contracts.validate_corpus(bare, {})      # no authority: loads without a policy...
        self.assertIsNone(authority.policy_or_none(bare))      # ...but the fixture default is not reported for it
        with self.assertRaisesRegex(ValueError, 'A policy profile is required for this jurisdiction'):
            authority.policy_for(bare)
        with self.assertRaisesRegex(ValueError, 'A policy profile is required for this jurisdiction'):
            authority.decide(record(), matter(), bare)
        self.assertEqual(authority.query_for(matter(posture='retrieval'), bare)['posture'], 'retrieval')
        self.assertEqual(authority.policy_for(corpus([record()])), P)
        self.assertEqual(authority.policy_or_none(corpus([record()])), P)
        for wrong in ({'version': '1'}, {'policy_id': 'p'}, {'policy_id': 'p', 'version': '1', 'fallback': 'x'},
                      {'policy_id': 'p', 'version': '1', 'effective_to_inclusive': 'yes'},
                      {'policy_id': 'p', 'version': '1', 'postures': {'screening': {}}},
                      {'policy_id': 'p', 'version': '1', 'binding_courts': {'veld-central': 'veld-high-court'}},
                      {'policy_id': 'p', 'version': '1', 'review': {'reviewer_role': 'x'}}):
            with self.subTest(policy=wrong), self.assertRaises(ValueError):
                contracts.validate_corpus(corpus([record()], policy=wrong), {})
        # The same corpus relabelled private-matter loads (no policy, no snapshots) and every mode refuses it.
        private = corpus([record()], data_class='private-matter')
        contracts.validate_corpus(private, {})
        loaded, _, _ = smoke()
        suite = copy.deepcopy(loaded)
        suite['lock']['data_class'] = 'private-matter'
        suite['corpus'] = {**suite['corpus'], 'data_class': 'private-matter'}
        contracts.validate_corpus(suite['corpus'], suite['lock'])
        with patch.object(legal, 'load_suite', return_value=suite):
            with self.assertRaisesRegex(ValueError, 'public-synthetic suites only'):
                legal.validate({'suite': 'dict', 'synthetic': True}, ROOT, 'smoke')
            with self.assertRaisesRegex(ValueError, 'This mode does not accept private-matter suites'):
                legal.validate({'suite': 'dict', 'synthetic': True, 'arms': ['lexical']}, ROOT, 'retrieval')

    def test_grader_and_pipeline_share_one_decision(self):
        policy = {'policy_id': 'shared-decision', 'version': '1', 'effective_to_inclusive': True,
                  'postures': {'screening': {'persuasive_eligible': False}, 'retrieval': {'persuasive_eligible': True}}}
        snapshot = {'id': 'gazette-1', 'published': '2024-12-01'}
        boundary = record('vtc-1-1', '2020', effective_to='2025-03-01', status='superseded', snapshot=snapshot,
                          status_as_of='2025-01-15')      # its end is attested before the cutoff
        persuasive = record('vtc-2-1', '2020', weight='persuasive', effective_to='2026-01-01', snapshot=snapshot)
        open_ended = record('vtc-3-1', '2020', snapshot=snapshot)
        the_corpus = corpus([boundary, persuasive, open_ended], policy=policy, availability_cutoff='2025-02-01')
        contracts.validate_corpus(the_corpus, {})
        m = matter(day='2025-03-01')
        expected = {('vtc-1-1', '2020'): ('eligible', []), ('vtc-2-1', '2020'): ('ineligible', ['persuasive_not_permitted']),
                    ('vtc-3-1', '2020'): ('unknown', ['validity_unknown_after_cutoff'])}
        suite = suite_of(the_corpus, [m])
        result = retrieval.retrieve(contracts.candidate_view(suite), m, 'lexical', {'top_k': 10})
        shown = {(a['authority_id'], a['version']): (a['eligibility']['decision'], a['eligibility']['reason_codes']) for a in result['authorities']}
        for r in the_corpus['authorities']:
            key = (r['authority_id'], r['version'])
            with self.subTest(authority=key):
                self.assertEqual(authority.decide(r, m, the_corpus), expected[key])
                self.assertEqual(fixture.decide(r, m, the_corpus), expected[key])
                resolved = authority.resolve_citation({'authority_id': key[0], 'version': key[1], 'pinpoint': 's1(1)'}, the_corpus, m)
                self.assertEqual((resolved['decision'], resolved['reason_codes']), expected[key])
                self.assertEqual(shown[key], expected[key])
        gold = {'matter_id': 'fx-a', 'scenario': 'test', 'variant': 'base', 'recommendation': 'charge', 'controlling_authority': ['vtc-1-1', '2020'],
                'ineligible_versions': [['vtc-2-1', '2020']], 'elements': {'act': 'supported'}, 'conflict_elements': [], 'missing_elements': [],
                'established_exemptions': [], 'injection_span_ids': [], 'evidence_spans': {'act': {'support': ['fx-a-s1#1'], 'adverse': []}},
                'exemption_spans': {}, 'reference_passages': {'evidence': ['fx-a-s1#1'], 'authorities': ['vtc-1-1@2020'], 'adverse': []}}
        fixture.check_gold(suite_of(the_corpus, [m], [gold]))
        with self.assertRaisesRegex(ValueError, 'Gold authority is not eligible for its matter: fx-a'):
            fixture.check_gold(suite_of(the_corpus, [m], [{**gold, 'controlling_authority': ['vtc-2-1', '2020'], 'ineligible_versions': []}]))
        with self.assertRaisesRegex(ValueError, 'A gold ineligible version is eligible'):
            fixture.check_gold(suite_of(the_corpus, [m], [{**gold, 'ineligible_versions': [['vtc-1-1', '2020']]}]))

        def claim(i, key, status):
            return {'claim_id': f'c{i}', 'proposition': 'The cited text governs.', 'authority_id': key[0], 'version': key[1],
                    'pinpoint': 's1(1)', 'status': status, 'reason_codes': []}
        output = {'schema_version': 1, 'matter_id': 'fx-a', 'recommendation': 'charge',
                  'issues': [{'issue_id': 'i1', 'question': m['question'], 'authority_id': 'vtc-1-1', 'version': '2020'}],
                  'elements': [{'element_id': 'act', 'status': 'supported', 'evidence_span_ids': ['fx-a-s1#1'], 'adverse_span_ids': []}],
                  'claims': [claim(1, ('vtc-1-1', '2020'), 'supported'), claim(2, ('vtc-2-1', '2020'), 'insufficient'),
                             claim(3, ('vtc-3-1', '2020'), 'qualified')],
                  'material_conflicts': [], 'adverse_authorities': [], 'missing_information': [], 'verification_flags': [], 'review_required': True}
        criteria = fixture.score(output, m, gold, the_corpus)
        self.assertTrue(criteria['claim_status'] and criteria['authority_version'], criteria)
        task_a = copy.deepcopy(output)      # the statuses Task A's policy-free rule would have implied
        task_a['claims'][0]['status'], task_a['claims'][1]['status'] = 'insufficient', 'qualified'
        self.assertFalse(fixture.score(task_a, m, gold, the_corpus)['claim_status'])

    def test_fixture_wrapper_keeps_task_a_results(self):
        source = {'venues': ['veld-central'], 'effective_from': '2024-03-01', 'effective_to': '2025-01-01', 'status': 'in_force'}
        check = lambda day, venue='veld-central', **kw: fixture.eligible({**source, **kw}, {'operative_date': day, 'venue': venue})      # noqa: E731
        self.assertEqual(check('2024-03-01'), ('eligible', []))
        self.assertEqual(check('2024-02-29'), ('ineligible', ['not_yet_effective']))
        self.assertEqual(check('2024-12-31'), ('eligible', []))
        self.assertEqual(check('2025-01-01'), ('ineligible', ['no_longer_effective']))
        self.assertEqual(check('2023-01-01', 'veld-harbor'), ('ineligible', ['wrong_venue', 'not_yet_effective']))
        self.assertEqual(check('2024-06-01', status='unknown'), ('unknown', ['validity_unknown']))
        self.assertEqual(check('2024-06-01', status='invalidated'), ('ineligible', ['obsolete_status']))
        self.assertEqual(check('2026-01-01', 'veld-harbor', status='invalidated'), ('ineligible', ['wrong_venue', 'no_longer_effective', 'obsolete_status']))
        # The shared decision gives the Task A answers on the shipped smoke corpus (no policy, no cutoff).
        suite, matters, _ = smoke()
        for m in matters.values():
            for r in suite['corpus']['authorities']:
                self.assertEqual(fixture.decide(r, m, suite['corpus']), fixture.eligible(r, m))


class CitationTests(unittest.TestCase):
    def test_citations_are_validated_again_at_resolution(self):
        suite, matters, _ = smoke()
        m, c = matters['f1-ledger-b'], suite['corpus']
        old = authority.resolve_citation({'authority_id': 'vsc-12-4', 'version': '2019', 'pinpoint': 's12.4(1)'}, c, m)
        self.assertEqual((old['resolved'], old['decision'], old['reason_codes'], old['weight']), (True, 'eligible', [], 'controlling'))
        self.assertEqual((old['authority']['authority_id'], old['authority']['version']), ('vsc-12-4', '2019'))
        new = authority.resolve_citation({'authority_id': 'vsc-12-4', 'version': '2024'}, c, m)
        self.assertEqual((new['resolved'], new['decision'], new['reason_codes']), (True, 'ineligible', ['not_yet_effective']))      # not support
        codes = []
        for item in ({'authority_id': 'vzz-9-9', 'version': '2019'}, {'authority_id': 'vsc-12-4', 'version': '2030'},
                     {'authority_id': 'vsc-12-4', 'version': '2019', 'pinpoint': 's12.4(9)'}):
            result = authority.resolve_citation(item, c, m)
            self.assertEqual((result['resolved'], result['decision'], result['weight']), (False, None, None))
            codes.extend(result['reason_codes'])
        self.assertEqual(codes, list(contracts.REFERENCE_ERRORS[:3]))
        self.assertIsNone(authority.resolve_citation({'authority_id': 'vzz-9-9', 'version': '2019'}, c, m)['authority'])
        mismatch = authority.resolve_citation({'authority_id': 'vsc-12-4', 'version': '2019', 'pinpoint': 's12.4(9)'}, c, m)
        self.assertEqual(mismatch['authority']['version'], '2019')      # the matched record, with no decision
        for item in ({'authority_id': ['vsc-12-4'], 'version': '2019'}, {'authority_id': 'vsc-12-4', 'version': 2019},
                     {'authority_id': 'vsc-12-4', 'version': '2019', 'pinpoint': None}, {'version': '2019'}, 'vsc-12-4@2019'):
            with self.subTest(item=item), self.assertRaisesRegex(ValueError, 'A citation needs string authority_id, version and pinpoint'):
                authority.resolve_citation(item, c, m)
        with self.assertRaisesRegex(ValueError, 'A citation must be a string'):
            authority.resolve_alias(['Veld Statutes Consolidated s12.4'], c, m)
        # Resolution decides again: it does not trust an earlier decision.
        with patch.object(authority, 'eligible', return_value=('ineligible', ['obsolete_status'])):
            self.assertEqual(authority.resolve_citation({'authority_id': 'vsc-12-4', 'version': '2019'}, c, m)['decision'], 'ineligible')
        # A claim that cites the ineligible version or an unknown authority is not support under the scorer either.
        output = fixture.draft(m, c)
        output['claims'][1]['status'] = 'supported'
        gold = {g['matter_id']: g for g in suite['rubric']['matters']}['f1-ledger-b']
        self.assertFalse(fixture.score(output, m, gold, c)['no_ineligible_version_supported'])

    def test_alias_collision_is_ambiguous_not_guessed(self):
        records = [
            record('vtc-1-1', '2019', citation='Veld Test Code s1', effective_to='2024-01-01', status='superseded'),
            record('vtc-1-1', '2024', citation='Veld Test Code s1', effective_from='2024-01-01'),
            record('vtc-2-1', '2020', aliases=['Ledger Act']), record('vtc-3-1', '2020', aliases=['Ledger Act']),
            record('vtc-4-1', '2010', citation='Old Code s5', effective_from='2010-01-01', effective_to='2015-01-01', status='superseded'),
            record('vtc-4-1', '2015', citation='Old Code s5', effective_from='2015-01-01', effective_to='2020-01-01', status='repealed'),
            record('vtc-5-1', '2010', citation='Doubt Code s7', effective_to='2012-01-01', status='superseded', effective_from='2010-01-01'),
            record('vtc-5-1', '2012', citation='Doubt Code s7', effective_from='2012-01-01', status='unknown'),
        ]
        c, m = corpus(records), matter(day='2025-03-01')
        resolve = lambda text: authority.resolve_alias(text, c, m)      # noqa: E731
        self.assertEqual(resolve('  veld test CODE s1 '), {'status': 'resolved', 'matches': [['vtc-1-1', '2024']]})
        self.assertEqual(resolve('ledger act'), {'status': 'ambiguous', 'matches': [['vtc-2-1', '2020'], ['vtc-3-1', '2020']]})
        self.assertEqual(resolve('Old Code s5'), {'status': 'ineligible', 'matches': [['vtc-4-1', '2010'], ['vtc-4-1', '2015']]})
        self.assertEqual(resolve('Doubt Code s7'), {'status': 'unverified', 'matches': [['vtc-5-1', '2012']]})
        self.assertEqual(resolve('Veld Test Code s9'), {'status': 'unknown', 'matches': []})
        self.assertEqual(resolve('Veld Test Code s1.1'), {'status': 'unknown', 'matches': []})      # no partial or prefix match
        self.assertEqual(resolve('Veld Test   Code\ts1'), resolve('Veld Test Code s1'))      # internal whitespace is collapsed
        # An alias shared by two authorities is ambiguous even when only one of them is eligible (review probe p11).
        shared = corpus([record('vsc-12', '2020', citation='VSC s12', aliases=['Code s12']),
                         record('vho-1', '2020', citation='VHO s1', aliases=['Code s12'], status='unknown'),
                         record('vsc-120', '2020', citation='VSC s120')])
        self.assertEqual(authority.resolve_alias('Code s12', shared, m), {'status': 'ambiguous', 'matches': [['vho-1', '2020'], ['vsc-12', '2020']]})
        self.assertEqual(authority.resolve_alias('VSC s12', shared, m), {'status': 'resolved', 'matches': [['vsc-12', '2020']]})

    def test_contrary_authority_is_surfaced(self):
        offence = record('vtc-1-1', '2020', title='Misplacing a ledger', text='A clerk who misplaces a ledger commits an offence.')
        exemption = lambda i, **kw: record(f'vtc-1-{i}', '2020', authority_type='exemption', relates_to='vtc-1-1',      # noqa: E731
                                           title='Excuse', text='An excuse applies on written leave.', **kw)
        eligible, doubtful, wrong_venue = exemption(2), exemption(3, status='unknown'), exemption(4, venues=['veld-harbor'])
        other = record('vtc-9-1', '2020', authority_type='exemption', relates_to='vtc-9-0', title='Other excuse', text='Unrelated excuse text.')
        c = corpus([wrong_venue, doubtful, offence, other, eligible])
        m = matter(question='Does a clerk misplacing a ledger support a charge?')
        found = authority.contrary(offence, c, m)
        self.assertEqual([(r['authority_id'], d) for r, d in found], [('vtc-1-2', 'eligible'), ('vtc-1-3', 'unknown')])
        result = retrieval.retrieve(contracts.candidate_view(suite_of(c, [m])), m, 'lexical-eligible', {'top_k': 1})
        self.assertEqual(ids(result['authorities']), ['vtc-1-1@2020'])
        self.assertEqual([(a['passage_id'], a['eligibility']['decision']) for a in result['adverse']],
                         [('vtc-1-2@2020', 'eligible'), ('vtc-1-3@2020', 'unknown')])
        self.assertIn('adverse_validity_unknown', result['reason_codes'])
        self.assertNotIn('vtc-1-4@2020', json.dumps(result['adverse']))
        self.assertEqual(result['excluded'], [{'passage_id': 'vtc-1-4@2020', 'reason_codes': ['wrong_venue']}])
        # Adverse authority is surfaced even past the budget, and the result says so.
        tight = retrieval.retrieve(contracts.candidate_view(suite_of(c, [m])), m, 'lexical-eligible', {'top_k': 1, 'token_budget': 10})
        self.assertEqual(ids(tight['adverse']), ['vtc-1-2@2020', 'vtc-1-3@2020'])
        self.assertEqual(tight['reason_codes'], ['adverse_over_budget', 'adverse_validity_unknown'])
        self.assertEqual(retrieval.retrieve(contracts.candidate_view(suite_of(c, [m])), m, 'no-context', {})['adverse'], [])


class RetrievalTests(unittest.TestCase):
    def setUp(self):
        self.suite, self.matters, self.gold = smoke()
        self.view = contracts.candidate_view(self.suite)

    def retrieve(self, matter_id, arm, **settings):
        reference = retrieval.reference_passages(self.suite, self.matters[matter_id]) if arm == 'reference' else None
        return retrieval.retrieve(self.view, self.matters[matter_id], arm, settings, reference)

    def measure(self, matter_id, arm, **settings):
        return retrieval.metrics(self.retrieve(matter_id, arm, **settings),
                                 retrieval.gold_targets(self.suite, self.matters[matter_id], self.gold[matter_id]))

    def test_lexical_ranking_has_stable_tie_breakers_and_explicit_budgets(self):
        twins = [record('vtc-2-1', '2020'), record('vtc-1-1', '2020')]      # identical documents, different ids
        m = matter()
        result = retrieval.retrieve(contracts.candidate_view(suite_of(corpus(twins), [m])), m, 'lexical', {})
        self.assertEqual([p for p, _ in result['ranked_authorities']], ['vtc-1-1@2020', 'vtc-2-1@2020'])
        self.assertEqual(result['ranked_authorities'][0][1], result['ranked_authorities'][1][1])
        self.assertGreater(result['ranked_authorities'][0][1], 0)
        # Shuffled manifest order gives the same result and the same fingerprint.
        for arm in ('lexical', 'lexical-eligible', 'filters-only'):
            with self.subTest(arm=arm):
                base = self.retrieve('f1-ledger-a', arm)
                shuffled = copy.deepcopy(self.view)
                shuffled['corpus']['authorities'].reverse()
                again = retrieval.retrieve(shuffled, self.matters['f1-ledger-a'], arm, {})
                self.assertEqual(again, base)
                self.assertEqual(json.dumps(again, sort_keys=True), json.dumps(base, sort_keys=True))
        # Budgets: reaching the limit ends that list only.
        words = lambda n, w='ledger': ' '.join([w] * n)      # noqa: E731
        auth = [record('vtc-1-1', '2020', text=words(10) + ' misplaced'), record('vtc-1-2', '2020', text=words(40) + ' misplaced'),
                record('vtc-1-3', '2020', text='misplaced ledger')]
        evidence = source('fx-a-s1', [words(5) + ' misplaced', words(30) + ' misplaced', 'misplaced ledger again'])
        brief = source('fx-a-s2', ['A short earlier note on a misplaced ledger.'], role='prior_brief')
        m = matter(sources=[evidence, brief], question='Was the ledger misplaced?')
        view = contracts.candidate_view(suite_of(corpus(auth), [m]))
        result = retrieval.retrieve(view, m, 'filters-only', {'token_budget': 30})
        self.assertEqual(ids(result['authorities']), ['vtc-1-1@2020'])            # vtc-1-2 does not fit: the list ends, vtc-1-3 is not taken
        self.assertEqual(ids(result['evidence']), ['fx-a-s1#1'])                  # 11 + 6 = 17 used; the 31-word span ends the evidence list
        self.assertEqual(ids(result['prior_briefs']), ['fx-a-s2#1'])              # prior briefs take what is left after evidence
        self.assertEqual(result['tokens'], 11 + 6 + 8)
        ranked = retrieval.retrieve(view, m, 'lexical-eligible', {'token_budget': 1200, 'top_k': 2})
        self.assertEqual((len(ranked['authorities']), len(ranked['evidence'])), (2, 2))      # top_k cuts each list separately
        self.assertEqual(len(ranked['ranked_authorities']), 3)                                # the full ranking stays for the metrics
        # A passage with score 0 is kept after the scored ones: the statement that negates `unattended`.
        archive = self.retrieve('f5-archive-a', 'lexical-eligible')
        scores = {p: s for p, s in archive['ranked_evidence']}
        self.assertEqual(scores['f5-archive-a-s2#1'], 0)
        self.assertIn('f5-archive-a-s2#1', ids(archive['evidence']))
        self.assertEqual(ids(archive['evidence'])[-1], 'f5-archive-a-s2#1')
        self.assertTrue(all(s > 0 for p, s in archive['ranked_evidence'][:-1]))

    def test_effective_date_flip_changes_the_exact_version(self):
        later, earlier = self.retrieve('f1-ledger-a', 'lexical-eligible'), self.retrieve('f1-ledger-b', 'lexical-eligible')
        self.assertIn('vsc-12-4@2024', ids(later['authorities']))
        self.assertNotIn('vsc-12-4@2019', ids(later['authorities']))
        self.assertIn({'passage_id': 'vsc-12-4@2019', 'reason_codes': ['no_longer_effective']}, later['excluded'])
        self.assertIn('vsc-12-4@2019', ids(earlier['authorities']))
        self.assertNotIn('vsc-12-4@2024', ids(earlier['authorities']))
        self.assertIn({'passage_id': 'vsc-12-4@2024', 'reason_codes': ['not_yet_effective']}, earlier['excluded'])
        for matter_id in ('f1-ledger-a', 'f1-ledger-b'):
            self.assertEqual(self.measure(matter_id, 'lexical-eligible')['exact_version_recall'], 1.0)
        both = self.retrieve('f1-ledger-b', 'lexical')      # annotated only: both versions shown, each with its own decision
        decisions = {a['passage_id']: a['eligibility']['decision'] for a in both['authorities']}
        self.assertEqual((decisions['vsc-12-4@2019'], decisions['vsc-12-4@2024']), ('eligible', 'ineligible'))
        self.assertEqual(both['excluded'], [])

    def test_filters_only_versus_ranked_on_paired_amended_law(self):
        leak = {arm: {m: self.measure(m, arm)['ineligible_version_leakage'] for m in self.matters} for arm in ('lexical', 'lexical-eligible', 'filters-only')}
        self.assertGreater(max(v for v in leak['lexical'].values() if v is not None), 0)
        self.assertGreater(leak['lexical']['f1-ledger-a'], 0)
        for arm in ('lexical-eligible', 'filters-only'):
            self.assertTrue(all(v in (0, None) for v in leak[arm].values()), leak[arm])
        for matter_id in ('f8-manifest-a', 'f8-manifest-b'):
            result = self.retrieve(matter_id, 'filters-only')
            self.assertEqual(ids(result['authorities']).index('vsc-45-2@2018'), 5)      # sixth by id, still shown: no top_k cut
            self.assertTrue(all(a['score'] is None for a in result['authorities']))
            self.assertEqual((result['ranked_authorities'], result['ranked_evidence']), ([], []))
            self.assertEqual(self.measure(matter_id, 'filters-only')['exact_version_recall'], 1.0)
            self.assertEqual(ids(self.retrieve(matter_id, 'filters-only', top_k=1)['authorities']), ids(result['authorities']))
            self.assertEqual(self.measure(matter_id, 'lexical-eligible')['exact_version_recall'], 1.0)

    def test_leakage_is_measured_against_the_gold_not_the_arm(self):
        with patch.object(authority, 'eligible', return_value=('eligible', [])):
            result = self.retrieve('f1-ledger-a', 'lexical-eligible')
            values = retrieval.metrics(result, retrieval.gold_targets(self.suite, self.matters['f1-ledger-a'], self.gold['f1-ledger-a']))
        self.assertIn('vsc-12-4@2019', ids(result['authorities']))
        self.assertGreater(values['ineligible_version_leakage'], 0)
        self.assertEqual(values['annotated_ineligible'], 0)
        honest = self.measure('f1-ledger-a', 'lexical')
        self.assertEqual(honest['annotated_ineligible'], 2)      # the superseded version and the harbor ordinance (score 0)

    def test_eligible_version_survives_top_k_one(self):
        for arm in ('lexical-eligible', 'dense', 'hybrid', 'reranked'):
            for matter_id, version in (('f1-ledger-a', '2024'), ('f1-ledger-b', '2019')):
                with self.subTest(arm=arm, matter=matter_id):
                    result = self.retrieve(matter_id, arm, top_k=1, roles=ROLES)
                    self.assertEqual(result['status'], 'ok')
                    self.assertEqual(ids(result['authorities']), ['vsc-12-4@' + version])

    def test_missing_authority_yields_an_empty_result_with_a_reason(self):
        inland = self.matters['f2-berth-a']
        mooring = [a for a in self.suite['corpus']['authorities'] if a['authority_id'] in ('vho-3-1', 'vsc-30-2')]
        view = contracts.candidate_view(suite_of({**self.suite['corpus'], 'authorities': mooring}, [inland]))
        for arm in ('filters-only', 'lexical', 'lexical-eligible', 'dense', 'hybrid', 'reranked'):
            with self.subTest(arm=arm):
                result = retrieval.retrieve(view, inland, arm, {'roles': ROLES})
                self.assertEqual((result['status'], result['authorities'], result['adverse']), ('ok', [], []))
                self.assertIn('no_eligible_authority', result['reason_codes'])
                self.assertEqual(sorted(ids(result['evidence'])), ['f2-berth-a-s1#1', 'f2-berth-a-s1#2'])
                self.assertEqual([e['passage_id'] for e in result['excluded']], ['vho-3-1@2020', 'vsc-30-2@2026'])
        # On the shipped suite the reference of this matter is empty: the oracle shows nothing, and that is not an error.
        reference = self.retrieve('f2-berth-a', 'reference')
        self.assertEqual((reference['status'], reference['authorities'], reference['evidence'], reference['adverse']), ('ok', [], [], []))
        self.assertIn('no_eligible_authority', reference['reason_codes'])
        values = self.measure('f2-berth-a', 'reference')
        self.assertEqual((values['exact_version_recall'], values['prompt_evidence_recall'], values['retrieved_passages']), (None, None, 0))
        self.assertEqual(self.retrieve('f6-bridge-b', 'reference')['evidence'], [])

    def test_section_numbers_are_whole_tokens(self):
        self.assertEqual(retrieval.tokens('Under S45.6(1) and s45.2, the 3 clerks.'), ['s45.6', 's45.2', 'clerks'])
        self.assertEqual(re.findall(r'[a-z0-9]+', 's45.6 s45.2')[::2], ['s45', 's45'])      # the old rule: both would tie on s45
        cited = [record('vtc-1-1', '2020', title='Manifest entries', text='An entry made under s45.2 of the manifest rules.'),
                 record('vtc-1-2', '2020', title='Manifest entries', text='An entry made under s45.6 of the manifest rules.')]
        m = matter(question='Does an entry under s45.6 support a charge?')
        result = retrieval.retrieve(contracts.candidate_view(suite_of(corpus(cited), [m])), m, 'lexical', {})
        (first, high), (second, low) = result['ranked_authorities']
        self.assertEqual((first, second), ('vtc-1-2@2020', 'vtc-1-1@2020'))
        self.assertGreater(high, low)

    def test_no_context_shows_the_packet_without_authorities(self):
        result = self.retrieve('f5-archive-a', 'no-context')
        self.assertEqual((result['status'], result['authorities'], result['adverse'], result['prior_briefs']), ('ok', [], [], []))
        self.assertEqual(ids(result['evidence']), ['f5-archive-a-s1#1', 'f5-archive-a-s2#1', 'f5-archive-a-s3#1'])
        self.assertTrue(all(e['score'] is None for e in result['evidence']))
        self.assertEqual((result['reason_codes'], result['excluded'], result['ranked_authorities']), ([], [], []))
        self.assertEqual(self.retrieve('f5-archive-a', 'no-context', top_k=1)['evidence'], result['evidence'])

    def test_fts5_is_used_only_after_a_capability_check(self):
        self.assertEqual(retrieval.resolve_backend(self.suite, 'auto'), ('memory', []))
        prepared = {**self.suite, 'collection': {'collection_id': 'fixture'}}
        with patch.object(retrieval, 'fts5_available', return_value=True):
            self.assertEqual(retrieval.resolve_backend(prepared, 'auto'), ('fts5', []))
            self.assertEqual(retrieval.resolve_backend(prepared, 'memory'), ('memory', []))
        with patch.object(retrieval, 'fts5_available', return_value=False):
            self.assertEqual(retrieval.resolve_backend(prepared, 'auto'), ('memory', ['fts5_absent_memory_used']))
            self.assertEqual(retrieval.resolve_backend(self.suite, 'fts5'), ('fts5', []))      # an explicit request is never replaced
            result = self.retrieve('f1-ledger-a', 'lexical', backend='fts5')
            self.assertEqual((result['status'], result['reason_codes'], result['authorities']), ('unavailable', ['capability_absent_fts5'], []))
            self.assertEqual(self.retrieve('f1-ledger-a', 'filters-only', backend='fts5')['status'], 'ok')
            self.assertEqual(retrieval.available_arms(['lexical', 'lexical-eligible', 'no-context', 'reference'], {'backend': 'fts5'}),
                             {'lexical': 'capability_absent_fts5', 'lexical-eligible': 'capability_absent_fts5', 'no-context': None, 'reference': None})
            self.assertEqual(retrieval.available_arms(['lexical'], {'backend': 'memory'}), {'lexical': None})
        with self.assertRaises(ValueError):
            retrieval.resolve_backend(self.suite, 'elastic')
        if not retrieval.fts5_available():
            self.skipTest('SQLite build has no FTS5')
        three = [record('vtc-1-1', '2020', title='Ledger', text='The ledger was misplaced by the clerk at the registry.'),
                 record('vtc-1-2', '2020', title='Furnace', text='A furnace guard was absent during the shift.'),
                 record('vtc-1-3', '2020', title='Ledger', text='Some text about a ledger.')]
        m = matter(question='Was the ledger misplaced by the clerk?')
        result = retrieval.retrieve(contracts.candidate_view(suite_of(corpus(three), [m])), m, 'lexical', {'backend': 'fts5'})
        self.assertEqual(result['status'], 'ok')
        self.assertEqual([p for p, _ in result['ranked_authorities']], ['vtc-1-1@2020', 'vtc-1-3@2020', 'vtc-1-2@2020'])
        scores = [s for _, s in result['ranked_authorities']]
        self.assertTrue(scores[0] > scores[1] > scores[2] == 0, scores)
        self.assertEqual(result['settings']['backend'], 'fts5')


    def test_the_memory_backend_works_without_sqlite(self):
        path = Path(retrieval.__file__)
        with patch.dict('sys.modules', {'sqlite3': None}):      # a Python built without sqlite3: importing it fails
            spec = importlib.util.spec_from_file_location('llm_eval.experiments.legal_benchmark._retrieval_without_sqlite', path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            self.assertFalse(module.fts5_available())
            self.assertEqual(module.resolve_backend({**self.suite, 'collection': {}}, 'auto'), ('memory', ['fts5_absent_memory_used']))
            result = module.retrieve(self.view, self.matters['f1-ledger-a'], 'lexical-eligible', {})
            self.assertEqual(result['status'], 'ok')
            self.assertEqual(module.retrieve(self.view, self.matters['f1-ledger-a'], 'lexical', {'backend': 'fts5'})['reason_codes'],
                             ['capability_absent_fts5'])
        self.assertEqual(ids(result['authorities']), ids(self.retrieve('f1-ledger-a', 'lexical-eligible')['authorities']))
        # The capability is probed once per process.
        with patch.object(retrieval, '_FTS5', None), patch.object(retrieval, '_probe_fts5', return_value=True) as probe:
            self.assertTrue(retrieval.fts5_available())
            self.assertTrue(retrieval.fts5_available())
            self.assertEqual(probe.call_count, 1)


class ArmTests(unittest.TestCase):
    def setUp(self):
        self.suite, self.matters, self.gold = smoke()
        self.view = contracts.candidate_view(self.suite)

    def test_dense_and_reranked_arms_are_unavailable_without_a_profile(self):
        m = self.matters['f1-ledger-a']
        for arm, code in (('dense', 'capability_absent_embedding'), ('hybrid', 'capability_absent_embedding'), ('reranked', 'capability_absent_reranker')):
            with self.subTest(arm=arm):
                result = retrieval.retrieve(self.view, m, arm, {})
                self.assertEqual((result['status'], result['reason_codes']), ('unavailable', [code]))
                self.assertEqual((result['authorities'], result['evidence'], result['ranked_authorities'], result['tokens']), ([], [], [], 0))
                only_other = retrieval.retrieve(self.view, m, arm, {'roles': {'reranker': RERANKER} if arm != 'reranked' else {'embedder': EMBEDDER}})
                self.assertEqual(only_other['status'], 'unavailable')      # never a fallback to lexical
        self.assertEqual(retrieval.available_arms(list(retrieval.ARMS), {}),
                         {'no-context': None, 'filters-only': None, 'lexical': None, 'lexical-eligible': None, 'dense': 'capability_absent_embedding',
                          'hybrid': 'capability_absent_embedding', 'reranked': 'capability_absent_reranker', 'reference': None})
        self.assertEqual(set(retrieval.available_arms(list(retrieval.ARMS), {'roles': ROLES}).values()), {None})
        self.assertIsNone(retrieval.embedder(None, frozenset()))
        self.assertIsNone(retrieval.reranker(None, frozenset()))

    def test_dense_lexical_and_hybrid_share_the_passage_budget(self):
        settings = {'top_k': 3, 'token_budget': 1200, 'roles': ROLES}
        for matter_id, m in self.matters.items():
            results = {arm: retrieval.retrieve(self.view, m, arm, settings) for arm in ('lexical-eligible', 'dense', 'hybrid')}
            with self.subTest(matter=matter_id):
                self.assertEqual({r['status'] for r in results.values()}, {'ok'})
                common = [{k: v for k, v in r['settings'].items() if k != 'embedder_sha256'} for r in results.values()]
                self.assertEqual(common[0], common[1])
                self.assertEqual(common[1], common[2])
                self.assertEqual({len(r['authorities']) for r in results.values()}, {min(3, len(results['dense']['ranked_authorities']))})
                self.assertEqual({len(r['evidence']) for r in results.values()}, {min(3, len(results['dense']['ranked_evidence']))})
                self.assertEqual(results['dense'], retrieval.retrieve(self.view, m, 'dense', settings))      # deterministic
                for r in results.values():
                    self.assertEqual([s for _, s in r['ranked_authorities']], sorted((s for _, s in r['ranked_authorities']), reverse=True))
                    self.assertTrue(all(round(s, 6) == s for _, s in r['ranked_authorities'] + r['ranked_evidence']))
        lexical = retrieval.retrieve(self.view, self.matters['f1-ledger-a'], 'lexical-eligible', settings)
        dense = retrieval.retrieve(self.view, self.matters['f1-ledger-a'], 'dense', settings)
        hybrid = retrieval.retrieve(self.view, self.matters['f1-ledger-a'], 'hybrid', settings)
        rank = lambda r: {p: i for i, (p, _) in enumerate(r['ranked_authorities'], 1)}      # noqa: E731
        fused = {p: round(math.fsum([1 / (60 + rank(lexical)[p]), 1 / (60 + rank(dense)[p])]), 6) for p in rank(lexical)}
        self.assertEqual(dict(hybrid['ranked_authorities']), fused)

    def test_embedding_settings_are_recorded(self):
        m = self.matters['f1-ledger-a']
        result = retrieval.retrieve(self.view, m, 'dense', {'roles': ROLES})
        self.assertEqual(result['settings'], {'top_k': 5, 'token_budget': 1200, 'backend': 'memory', 'tokenizer': 'legal-terms-1', 'chunking': 'span',
                                              'embedder_sha256': profiles.profile_digest(EMBEDDER), 'reranker_sha256': None})
        self.assertEqual(result['query_sha256'], digest(retrieval.tokens(m['question'])))
        wider = retrieval.retrieve(self.view, m, 'dense', {'roles': {'embedder': {**EMBEDDER, 'dimensions': 128}}})
        self.assertNotEqual(wider['index_fingerprint'], result['index_fingerprint'])
        reranked = retrieval.retrieve(self.view, m, 'reranked', {'roles': ROLES})
        self.assertEqual(reranked['settings']['reranker_sha256'], profiles.profile_digest(RERANKER))
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'attempt'
            job = job_for(LOCK, {'synthetic': True, 'arms': ['dense', 'reranked'], 'roles': ROLES, 'top_k': 4})
            self.assertEqual(legal.execute(job, out, ROOT)['status'], 'succeeded')
            metadata = read_json(out / 'metadata.json')
        roles = metadata['roles']
        self.assertEqual((roles['embedder']['model'], roles['embedder']['model_revision'], roles['embedder']['dimensions']), ('fixture-hash', '1', 64))
        self.assertEqual(roles['embedder']['profile_sha256'], profiles.profile_digest(EMBEDDER))
        self.assertEqual(set(roles['embedder']), {'profile_sha256', 'role', 'serving', 'capability', 'platform', 'backend_version', 'model', 'model_revision',
                                                  'artifact_sha256', 'quantization', 'protocol', 'accelerator', 'context_tokens', 'max_output_tokens',
                                                  'dimensions', 'qualified', 'qualified_by_attestation', 'serving_profile_sha256'})
        self.assertEqual(metadata['retrieval'], {**metadata['retrieval'], 'backend': 'memory', 'top_k': 4, 'token_budget': 1200, 'tokenizer': 'legal-terms-1',
                                                 'chunking': 'span', 'embedder_sha256': profiles.profile_digest(EMBEDDER),
                                                 'reranker_sha256': profiles.profile_digest(RERANKER)})
        self.assertRegex(metadata['retrieval']['index_fingerprint'], r'\A[0-9a-f]{64}\Z')

    def test_endpoint_embedder_talks_only_to_its_loopback_endpoint(self):
        state = {'dimensions': 8}

        def vectors(payload):
            return {'data': [{'embedding': [float((len(text) + i) % 5) for i in range(state['dimensions'])]} for text in payload['input']]}
        with FakeServer(vectors) as server, FakeServer(vectors) as bystander:
            profile = external('embedder', server.port)
            profiles.validate_role(profile, 'embedder')
            roles = {'embedder': profile}
            settings = {'roles': roles, 'allowed': profiles.allowed_endpoints(roles)}
            self.assertEqual(settings['allowed'], frozenset({profile['endpoint']}))
            m = self.matters['f1-ledger-a']
            result = retrieval.retrieve(self.view, m, 'dense', settings)
            self.assertEqual(result['status'], 'ok')
            self.assertGreaterEqual(len(server.requests), 1)
            self.assertEqual(server.requests[0]['path'], '/v1/embedder')
            self.assertEqual(set(server.requests[0]['payload']), {'model', 'input'})
            self.assertEqual(server.requests[0]['payload']['model'], 'fake-embedder')
            state['dimensions'] = 7      # a wrong vector length is an arm error, nothing else
            broken = retrieval.retrieve(self.view, m, 'dense', settings)
            self.assertEqual((broken['status'], broken['reason_codes'], broken['error_type']), ('error', ['embedding_error'], 'ValueError'))
            self.assertEqual((broken['authorities'], broken['evidence']), ([], []))
            # Through the mode: an endpoint role makes a model run, and a job whose every row is an error fails.
            with tempfile.TemporaryDirectory() as tmp:
                job = job_for(LOCK, {'synthetic': False, 'arms': ['dense'], 'roles': roles})
                result = legal.execute(job, Path(tmp) / 'attempt', ROOT)
                rows = lines(Path(tmp) / 'attempt/requests.jsonl')
            self.assertEqual(result['status'], 'failed')
            self.assertEqual({(r['status'], r['retrieval_status'], r['error_type'], r['execution_kind'], r['synthetic']) for r in rows},
                             {('error', 'error', 'ValueError', 'model-run', False)})
            self.assertEqual(bystander.requests, [])

    def test_endpoint_reranker_scores_are_applied_and_bad_replies_are_arm_errors(self):
        m = self.matters['f1-ledger-a']
        state = {'mode': 'reverse'}

        def scores(payload):
            n = len(payload['documents'])
            if state['mode'] == 'missing':
                return {'results': [{'index': i, 'relevance_score': 1.0} for i in range(n - 1)]}
            if state['mode'] == 'duplicate':
                return {'results': [{'index': 0, 'relevance_score': 1.0} for _ in range(n)]}
            return {'results': [{'index': i, 'relevance_score': float(i)} for i in range(n)]}      # the last document scores highest
        with FakeServer(scores) as server:
            profile = external('reranker', server.port)
            profiles.validate_role(profile, 'reranker')
            roles = {'reranker': profile}
            settings = {'roles': roles, 'allowed': profiles.allowed_endpoints(roles), 'top_k': 2}
            lexical = retrieval.retrieve(self.view, m, 'lexical-eligible', settings)
            result = retrieval.retrieve(self.view, m, 'reranked', settings)
            self.assertEqual(result['status'], 'ok')
            head = [p for p, _ in lexical['ranked_evidence']][:8]
            self.assertEqual([p for p, _ in result['ranked_evidence']][:len(head)], list(reversed(head)))      # the reply decides the order
            self.assertEqual({tuple(sorted(r['payload'])) for r in server.requests}, {('documents', 'model', 'query')})
            self.assertEqual(result['settings']['reranker_sha256'], profiles.profile_digest(profile))
            for mode in ('missing', 'duplicate'):
                with self.subTest(reply=mode):
                    state['mode'] = mode
                    broken = retrieval.retrieve(self.view, m, 'reranked', settings)
                    self.assertEqual((broken['status'], broken['reason_codes'], broken['error_type']), ('error', ['reranker_error'], 'ValueError'))
                    self.assertEqual((broken['authorities'], broken['evidence']), ([], []))
            # An endpoint outside the allowlist is an arm error for the reranker as for the embedder, not an exception.
            count = len(server.requests)
            for arm, role, code in (('reranked', profile, 'reranker_error'), ('dense', external('embedder', server.port), 'embedding_error')):
                with self.subTest(arm=arm):
                    refused = retrieval.retrieve(self.view, m, arm, {'roles': {role['role']: role}, 'allowed': frozenset()})
                    self.assertEqual((refused['status'], refused['reason_codes'], refused['error_type']), ('error', [code], 'ValueError'))
            self.assertEqual(len(server.requests), count)

    def test_lexical_failures_are_not_reported_as_embedding_errors(self):
        with patch.object(retrieval, '_bm25_memory', side_effect=KeyError('a lexical bug')):
            with self.assertRaises(KeyError):
                retrieval.retrieve(self.view, self.matters['f1-ledger-a'], 'hybrid', {'roles': ROLES})

    def test_reranked_ranking_keeps_the_bm25_tail(self):
        m = matter(sources=[source('fx-a-s1', ['The clerk misplaced the ledger %d.' % i for i in range(6)])])
        view = contracts.candidate_view(suite_of(corpus([record()]), [m]))
        targets = {'evidence': {'fx-a-s1#%d' % i for i in range(1, 7)}, 'authority': set(), 'ineligible': set(), 'adverse': set()}
        lexical = retrieval.retrieve(view, m, 'lexical-eligible', {'top_k': 1})
        reranked = retrieval.retrieve(view, m, 'reranked', {'top_k': 1, 'roles': {'reranker': RERANKER}})
        self.assertEqual(len(reranked['ranked_evidence']), 6)      # the reranked head of 4 * top_k, then the BM25 tail in BM25 order
        self.assertEqual([p for p, _ in reranked['ranked_evidence']][4:], [p for p, _ in lexical['ranked_evidence']
                                                                            if p not in [q for q, _ in reranked['ranked_evidence']][:4]])
        self.assertEqual(len(reranked['evidence']), 1)
        values = retrieval.metrics(reranked, targets)
        self.assertEqual((values['evidence_recall_at_5'], values['evidence_ndcg_at_10']), (round(5 / 6, 6), 1.0))
        # A head of only unknown versions does not hide an eligible version further down.
        doubtful = [record('vtc-1-%d' % i, '2020', status='unknown', text='The ledger misplaced ledger ledger by the clerk.') for i in range(1, 5)]
        live = record('vtc-2-1', '2020', title='Unrelated', text='A furnace without a guard.')
        view = contracts.candidate_view(suite_of(corpus(doubtful + [live]), [m]))
        result = retrieval.retrieve(view, m, 'reranked', {'top_k': 1, 'roles': {'reranker': RERANKER}})
        self.assertIn('vtc-2-1@2020', [p for p, _ in result['ranked_authorities']])
        self.assertNotIn('no_eligible_authority', result['reason_codes'])

    def test_unknown_exemption_among_the_authorities_is_flagged(self):
        offence = record('vtc-1-1', '2020', title='Misplacing a ledger', text='A clerk who misplaces a ledger commits an offence.')
        doubtful = record('vtc-1-2', '2020', authority_type='exemption', relates_to='vtc-1-1', status='unknown',
                          title='Ledger clerk excuse', text='A clerk misplacing a ledger on written leave is excused.')
        c = corpus([offence, doubtful])
        m = matter(question='Does a clerk misplacing a ledger support a charge?')
        result = retrieval.retrieve(contracts.candidate_view(suite_of(c, [m])), m, 'lexical-eligible', {})
        self.assertEqual(sorted(ids(result['authorities'])), ['vtc-1-1@2020', 'vtc-1-2@2020'])      # ranked in, so not repeated in adverse
        self.assertEqual(result['adverse'], [])
        self.assertIn('adverse_validity_unknown', result['reason_codes'])

    def test_unavailable_and_errored_rows_are_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            job = job_for(LOCK, {'synthetic': True, 'arms': ['dense', 'no-context']})
            result = legal.execute(job, Path(tmp) / 'attempt', ROOT)
            rows = lines(Path(tmp) / 'attempt/requests.jsonl')
        self.assertEqual(result['status'], 'succeeded')
        missing = [r for r in rows if r['arm'] == 'dense']
        self.assertEqual({(r['status'], r['retrieval_status'], r['grading_status'], r['quality_pass']) for r in missing},
                         {('missing', 'unavailable', 'not_applicable', None)})
        self.assertEqual({tuple(r['reason_codes']) for r in missing}, {('capability_absent_embedding',)})
        self.assertTrue(all(r[k] is None for r in missing for k in PUBLIC_METRICS))
        with tempfile.TemporaryDirectory() as tmp:
            result = legal.execute(job_for(LOCK, {'synthetic': True, 'arms': ['dense']}), Path(tmp) / 'attempt', ROOT)
        self.assertEqual(result['status'], 'succeeded')      # missing rows are results; only all-error or no row fails


class ProfileTests(unittest.TestCase):
    def test_serving_must_be_explicit_and_managed_is_gated(self):
        self.assertFalse(profiles.MANAGED_SERVING_ENABLED)
        profile = external('generator')
        self.assertEqual(profiles.validate_role(profile, 'generator'), profile)
        with self.assertRaisesRegex(ValueError, 'A role profile must declare serving'):
            profiles.validate_role({k: v for k, v in profile.items() if k != 'serving'}, 'generator')
        with self.assertRaisesRegex(ValueError, 'Managed serving of legal roles is gated: qualify with model-offloading and declare serving: external'):
            profiles.validate_role({**profile, 'serving': 'managed'}, 'generator')
        with self.assertRaises(ValueError):
            profiles.validate_role({'role': 'generator', 'serving': 'in-process', 'platform': 'fixture-hash', 'model': 'x', 'model_revision': '1',
                                    'capability': 'chat'}, 'generator')
        with self.assertRaises(ValueError):
            profiles.validate_role({**EMBEDDER, 'platform': 'fixture-overlap'}, 'embedder')
        with self.assertRaises(ValueError):
            profiles.validate_role({**EMBEDDER, 'endpoint': 'http://127.0.0.1:9/v1'}, 'embedder')      # in-process has no endpoint
        with self.assertRaisesRegex(ValueError, 'role'):
            profiles.validate_role(EMBEDDER, 'reranker')
        with self.assertRaises(ValueError):
            profiles.validate_role({**profile, 'serving': 'hosted'}, 'generator')
        with self.assertRaises(ValueError):
            profiles.validate_role({**profile, 'capability': 'embedding'}, 'generator')
        with self.assertRaises(ValueError):
            profiles.validate_role({**profile, 'max_output_tokens': 8192}, 'generator')      # must be below the context
        with self.assertRaises(ValueError):
            profiles.validate_role({k: v for k, v in profile.items() if k != 'accelerator'}, 'generator')
        # Package E: a qualification names a locked serving profile, which is loaded and bound (tests/test_legal_routing.py).
        with self.assertRaisesRegex(ValueError, 'Locked serving profile not found'):
            profiles.validate_role({**profile, 'qualification': {'serving_profile': 'q.json'}}, 'generator')
        self.assertEqual(profiles.validate_role({**profile, 'qualification': None}, 'generator')['qualification'], None)
        managed = {'suite': str(LOCK), 'arms': ['dense'], 'roles': {'embedder': {**external('embedder'), 'serving': 'managed'}}}
        with self.assertRaisesRegex(ValueError, 'Managed serving of legal roles is gated'):
            legal.validate({**managed, 'synthetic': False}, ROOT, 'retrieval')
        with self.assertRaisesRegex(ValueError, 'Record the exact loaded model revision before evaluating'):
            profiles.check_revisions({'embedder': {**EMBEDDER, 'model_revision': 'REPLACE-ME'}})
        with self.assertRaisesRegex(ValueError, 'Record the exact loaded model revision'):
            profiles.check_revisions({'generator': {**profile, 'backend_version': 'TODO'}})
        profiles.check_revisions(ROLES)

    def test_digest_ignores_endpoint_and_changes_with_identity_or_budget(self):
        profile = external('generator', 8080)
        base = profiles.profile_digest(profile)
        self.assertRegex(base, r'\A[0-9a-f]{64}\Z')
        for change in ({'endpoint': 'http://127.0.0.1:9090/v1/chat'}, {'network': {'kind': 'local'}}, {'api_key_env': 'LEGAL_TEST_KEY'},
                       {'timeout_s': 30}, {'connect_timeout_s': 5}):
            with self.subTest(same=change):
                self.assertEqual(profiles.profile_digest({**profile, **change}), base)
        for change in ({'model_revision': 'r2'}, {'model': 'other'}, {'backend_version': '1.1'}, {'platform': 'other'}, {'deployment_id': 'other'},
                       {'context_tokens': 4096}, {'max_output_tokens': 512}, {'quantization': 'q4'}, {'accelerator': 'gpu'},
                       {'placement': {'gpu_layers': 10, 'gpu_offload': None, 'threads': 8}}, {'artifact_sha256': 'b' * 64},
                       {'template_sha256': 'c' * 64}, {'tokenizer_revision': 't2'}, {'resource_host': 'other-host'}, {'protocol': 'ollama'}):
            with self.subTest(changed=change):
                self.assertNotEqual(profiles.profile_digest({**profile, **change}), base)
        qualified = {**profile, 'qualification': {'serving_profile': '/work/serving-profile.json'}}
        with patch('builtins.open', side_effect=AssertionError('the serving profile was opened')), \
                patch.object(Path, 'read_bytes', side_effect=AssertionError('the serving profile was opened')):
            first = profiles.profile_digest(qualified, [{'path': '/work/serving-profile.json', 'sha256': 'a' * 64}])
            second = profiles.profile_digest(qualified, [{'path': '/work/serving-profile.json', 'sha256': 'b' * 64}])
            unrecorded = profiles.profile_digest(qualified, [])
        self.assertEqual(len({first, second, base}), 3)
        self.assertEqual(unrecorded, base)       # no recorded digest: the same as no qualification
        self.assertEqual(profiles.profile_digest({**profile, 'qualification': None}), base)
        public = profiles.public_role(profile)
        self.assertEqual(public['profile_sha256'], base)
        self.assertEqual((public['qualified'], public['serving_profile_sha256'], public['quantization'], public['dimensions']), (False, None, None, None))
        self.assertNotIn('127.0.0.1', json.dumps(public))
        self.assertNotIn('LEGAL_TEST_KEY', json.dumps(profiles.public_role({**profile, 'api_key_env': 'LEGAL_TEST_KEY'})))

    def test_roles_sharing_a_deployment_keep_separate_identities(self):
        generator, analyst = external('generator', deployment_id='shared-box'), external('analyst', deployment_id='shared-box')
        profiles.validate_role(generator, 'generator')
        profiles.validate_role(analyst, 'analyst')
        self.assertNotEqual(profiles.profile_digest(generator), profiles.profile_digest(analyst))
        self.assertEqual((profiles.public_role(generator)['role'], profiles.public_role(analyst)['role']), ('generator', 'analyst'))
        self.assertEqual(profiles.allowed_endpoints({'generator': generator, 'analyst': analyst, 'embedder': EMBEDDER}),
                         frozenset({generator['endpoint'], analyst['endpoint']}))

    def test_non_local_roles_are_refused(self):
        for role in profiles.ROLES:
            for kind in ('hosted', 'remote'):
                with self.subTest(role=role, kind=kind):
                    profile = external(role, endpoint='https://api.example.test/v1', network={'kind': kind, 'allowed_hosts': ['api.example.test']})
                    with self.assertRaisesRegex(ValueError, 'Legal roles must be local: ' + role):
                        profiles.validate_role(profile, role)
            with self.subTest(role=role, kind='local'):
                profiles.validate_role(external(role, network={'kind': 'local'}), role)
                with self.assertRaises(ValueError):
                    profiles.validate_role(external(role, endpoint='http://192.0.2.10:8080/v1'), role)      # not loopback
        hosted = external('embedder', endpoint='https://api.example.test/v1', network={'kind': 'hosted', 'allowed_hosts': ['api.example.test']})
        with self.assertRaisesRegex(ValueError, 'Legal roles must be local: embedder'):
            legal.validate({'suite': str(LOCK), 'synthetic': False, 'arms': ['dense'], 'roles': {'embedder': hosted}}, ROOT, 'retrieval')

    def test_endpoint_outside_the_allowlist_is_refused(self):
        with FakeServer(lambda payload: {'data': []}) as server:
            profile = external('embedder', server.port)
            with self.assertRaisesRegex(ValueError, 'Endpoint is not on the job allowlist'):
                profiles.json_request(profile, {'model': 'x', 'input': []}, frozenset())
            with self.assertRaisesRegex(ValueError, 'Endpoint is not on the job allowlist'):
                retrieval.embedder(profile, allowed=frozenset())
            with self.assertRaisesRegex(ValueError, 'Endpoint is not on the job allowlist'):
                retrieval.reranker(external('reranker', server.port), allowed=frozenset({profile['endpoint']}))
            with self.assertRaisesRegex(ValueError, 'Endpoint is not on the job allowlist'):
                profiles.require_allowed('http://127.0.0.1:1/v1', frozenset({profile['endpoint']}))
            profiles.require_allowed(profile['endpoint'], frozenset({profile['endpoint']}))
            self.assertEqual(server.requests, [])
            self.assertEqual(profiles.json_request(profile, {'model': 'x', 'input': []}, frozenset({profile['endpoint']})), {'data': []})
            self.assertEqual(len(server.requests), 1)

    def test_request_options_and_credentials_are_rejected(self):
        profile = external('generator')
        with self.assertRaisesRegex(ValueError, 'Unknown fields: request_options'):
            profiles.validate_role({**profile, 'request_options': {'temperature': 0.9}}, 'generator')
        with self.assertRaisesRegex(ValueError, 'credential'):
            profiles.validate_role({**profile, 'api_key': 'not-a-real-key'}, 'generator')
        with self.assertRaises(ValueError):
            profiles.validate_role({**profile, 'api_key_env': 'not a variable name'}, 'generator')
        profiles.validate_role({**profile, 'api_key_env': 'LEGAL_TEST_KEY'}, 'generator')
        with self.assertRaisesRegex(ValueError, 'Unknown fields'):
            profiles.validate_role({**EMBEDDER, 'timeout_s': 10}, 'embedder')
        with self.assertRaises(ValueError):
            profiles.validate_role({**profile, 'endpoint': 'http://user:pw@127.0.0.1:9/v1'}, 'generator')
        for key, value in (('timeout_s', 0), ('timeout_s', 4000), ('connect_timeout_s', 31), ('dimensions', 4), ('accelerator', 'npu')):
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                profiles.validate_role({**external('embedder'), key: value}, 'embedder')


class IsolationTests(unittest.TestCase):
    def setUp(self):
        self.suite, self.matters, self.gold = smoke()

    def test_candidate_side_functions_never_touch_the_rubric(self):
        suite = {**self.suite, 'rubric': Exploding()}
        view = contracts.candidate_view(suite)
        for m in self.matters.values():
            self.assertTrue(retrieval.passages(view, m))
            for arm in retrieval.ARMS:
                if arm != 'reference':
                    self.assertEqual(retrieval.retrieve(view, m, arm, {'roles': ROLES})['status'], 'ok')
        self.assertEqual(set(retrieval.available_arms(list(retrieval.ARMS), {'roles': ROLES}).values()), {None})
        m = self.matters['f1-ledger-a']
        with self.assertRaises(AssertionError):
            retrieval.reference_passages(suite, m)
        with self.assertRaises(AssertionError):
            retrieval.gold_targets(suite, m, None)
        with self.assertRaises(AssertionError):
            retrieval.gold_targets(self.suite, m, Exploding())
        with self.assertRaisesRegex(ValueError, 'The reference arm needs the reference passages'):
            retrieval.retrieve(view, m, 'reference', {})
        with self.assertRaises(ValueError):      # only the reference arm receives the reference passages
            retrieval.retrieve(view, m, 'lexical', {}, retrieval.reference_passages(self.suite, m))
        self.assertEqual(retrieval.gold_targets(self.suite, m, None), retrieval.gold_targets(self.suite, m, self.gold['f1-ledger-a']))

    def test_prior_brief_is_ranked_for_other_families_only(self):
        brief_text = 'An earlier memo on a misplaced ledger concluded the matter.'
        shared = [source('fa-brief', [brief_text], role='prior_brief', excluded_matters=['fa-a', 'fa-b'], source_set='candidate')]
        own = source('fa-a-s2', ['A memo for this file on the misplaced ledger.'], role='prior_brief', excluded_matters=['fa-a', 'fa-b'])
        matters = [matter('fa-a', sources=[source('fa-a-s1', ['The clerk misplaced the ledger.']), own]),
                   matter('fa-b', sources=[source('fa-b-s1', ['The clerk kept the ledger.'])]),
                   matter('fb-a', sources=[source('fb-a-s1', ['A ledger was misplaced at the depot.'])])]
        rubric = [{'matter_id': m['matter_id'], 'reference_passages': {'evidence': [m['matter_id'] + '-s1#1'], 'authorities': ['vtc-1-1@2020'], 'adverse': []}}
                  for m in matters]
        suite = suite_of(corpus([record()]), matters, rubric, shared_sources=shared)
        view = contracts.candidate_view(suite)
        by_id = {m['matter_id']: m for m in matters}
        for matter_id, expected in (('fb-a', ['fa-brief#1']), ('fa-a', []), ('fa-b', [])):
            with self.subTest(matter=matter_id):
                m = by_id[matter_id]
                listed = [p['passage_id'] for p in retrieval.passages(view, m) if p['namespace'] == 'prior_brief']
                self.assertEqual(listed, expected)
                for arm in ('filters-only', 'lexical', 'lexical-eligible', 'dense', 'hybrid', 'reranked'):
                    result = retrieval.retrieve(view, m, arm, {'roles': ROLES})
                    self.assertEqual(ids(result['prior_briefs']), expected, arm)
                    self.assertFalse({'fa-brief#1', 'fa-a-s2#1'} & set(ids(result['evidence']) + ids(result['authorities'])))
                for arm in ('no-context', 'reference'):
                    reference = retrieval.reference_passages(suite, m) if arm == 'reference' else None
                    self.assertEqual(retrieval.retrieve(view, m, arm, {}, reference)['prior_briefs'], [])
        self.assertEqual(retrieval.retrieve(view, by_id['fb-a'], 'lexical', {})['prior_briefs'][0]['text'], brief_text)
        leaked = suite_of(corpus([record()]), matters, rubric, shared_sources=[{**shared[0], 'source_set': 'review'}])
        with self.assertRaises(ValueError):
            retrieval.passages(contracts.candidate_view(leaked), by_id['fb-a'])
        quoted = copy.deepcopy(matters[2])
        quoted['sources'][0]['spans'][0]['quoted'] = True
        self.assertEqual([p for p in retrieval.passages(view, quoted) if p['namespace'] == 'evidence'], [])

    def test_reference_arm_passes_passages_without_labels(self):
        view = contracts.candidate_view(self.suite)
        rubric_words = ['"' + k + '"' for g in self.gold.values() for k in g if k not in ('matter_id', 'elements')]
        rubric_words += ['"' + g['scenario'] + '"' for g in self.gold.values()] + ['"base"', '"paired"', self.suite['rubric']['rubric_version']]
        for matter_id, m in self.matters.items():
            with self.subTest(matter=matter_id):
                reference = retrieval.reference_passages(self.suite, m)
                self.assertEqual(list(reference), ['evidence', 'authorities', 'adverse'])
                for p in reference['authorities'] + reference['adverse']:
                    self.assertEqual(set(p), AUTHORITY_PASSAGE_KEYS)
                for p in reference['evidence']:
                    self.assertEqual(set(p), SOURCE_PASSAGE_KEYS)
                self.assertEqual(ids(reference['evidence']), self.gold[matter_id]['reference_passages']['evidence'])
                result = retrieval.retrieve(view, m, 'reference', {}, reference)
                text = json.dumps(result)
                self.assertEqual([w for w in rubric_words if w in text], [])
        injected = retrieval.retrieve(view, self.matters['f5-archive-a'], 'reference', {}, retrieval.reference_passages(self.suite, self.matters['f5-archive-a']))
        self.assertIn('f5-archive-a-s3#1', ids(injected['evidence']))
        a, b = (retrieval.retrieve(view, self.matters[i], 'reference', {}, retrieval.reference_passages(self.suite, self.matters[i]))
                for i in ('f8-manifest-a', 'f8-manifest-b'))
        self.assertEqual(ids(a['adverse']), ['vsc-45-6@2018'])
        self.assertEqual(ids(a['authorities']), ['vsc-45-2@2018'])
        differ = sorted(k for k in a if a[k] != b[k])
        self.assertEqual(differ, ['evidence', 'index_fingerprint', 'matter_id', 'tokens'])
        self.assertNotEqual(ids(a['evidence']), ids(b['evidence']))
        seal = self.matters['f4-seal-a']
        cut = retrieval.retrieve(view, seal, 'reference', {'top_k': 1}, retrieval.reference_passages(self.suite, seal))
        self.assertEqual(len(cut['evidence']), 3)
        retrieval.check({'suite': str(LOCK), 'synthetic': True, 'arms': ['reference'], 'token_budget': 1200}, self.suite, ROOT, 'retrieval')
        with self.assertRaisesRegex(ValueError, 'Reference passages exceed the token budget: f8-manifest-a'):
            retrieval.check({'suite': str(LOCK), 'synthetic': True, 'arms': ['reference'], 'token_budget': 64}, self.suite, ROOT, 'retrieval')
        retrieval.check({'suite': str(LOCK), 'synthetic': True, 'arms': ['lexical'], 'token_budget': 64}, self.suite, ROOT, 'retrieval')

    def test_passages_never_carry_drafter_terms(self):
        view = contracts.candidate_view(self.suite)
        for matter_id, m in self.matters.items():
            for arm in retrieval.ARMS:
                reference = retrieval.reference_passages(self.suite, m) if arm == 'reference' else None
                result = retrieval.retrieve(view, m, arm, {'roles': ROLES}, reference)
                text = json.dumps(result)
                self.assertNotIn('"terms"', text)
                self.assertNotIn('"negating_terms"', text)
                for a in result['authorities'] + result['adverse']:
                    self.assertTrue(a['elements'])
                    self.assertTrue(all(set(e) == {'element_id', 'description'} and e['description'] for e in a['elements']))
            self.assertNotIn('"terms"', json.dumps(retrieval.passages(view, m)))


class MetricsTests(unittest.TestCase):
    def test_recall_ndcg_version_leakage_and_adverse_coverage(self):
        gold_spans = ['e1', 'e2', 'e3', 'e4', 'e5', 'e6']
        targets = {'evidence': set(gold_spans), 'authority': {'c@1', 'x@1'}, 'ineligible': {'c@0'}, 'adverse': {'x@1'}}
        shown = lambda pid, decision='eligible': {'passage_id': pid, 'eligibility': {'decision': decision, 'reason_codes': []}}      # noqa: E731
        result = {'arm': 'lexical-eligible', 'authorities': [shown('c@0', 'ineligible'), shown('c@1')], 'adverse': [shown('x@1')],
                  'evidence': [{'passage_id': e} for e in gold_spans[:5]], 'prior_briefs': [],
                  'ranked_authorities': [['c@0', 3.0], ['c@1', 2.0], ['z@1', 1.0]],
                  'ranked_evidence': [[e, 1.0] for e in gold_spans] + [['n1', 0.5], ['n2', 0]], 'tokens': 100}
        values = retrieval.metrics(result, targets)
        self.assertEqual(set(values), set(PUBLIC_METRICS) | {'annotated_ineligible'})
        self.assertEqual(values, {
            'evidence_recall_at_5': round(5 / 6, 6), 'evidence_ndcg_at_10': 1.0, 'prompt_evidence_recall': round(5 / 6, 6),
            'authority_recall_at_5': 0.5, 'authority_ndcg_at_10': round((1 / math.log2(3)) / (1 + 1 / math.log2(3)), 6),
            'prompt_authority_recall': 1.0, 'exact_version_recall': 1.0, 'ineligible_version_leakage': round(1 / 3, 6),
            'annotated_ineligible': 1, 'adverse_authority_coverage': 1.0, 'retrieved_passages': 8, 'retrieved_tokens': 100})
        self.assertEqual(values['evidence_recall_at_5'], 0.833333)
        self.assertEqual(values['authority_ndcg_at_10'], 0.386853)
        # Unranked arm: rank metrics do not apply. Zero denominators are None; a true zero stays zero.
        none = {'evidence': set(), 'authority': set(), 'ineligible': set(), 'adverse': set()}
        empty = {'arm': 'filters-only', 'authorities': [], 'adverse': [], 'evidence': [], 'prior_briefs': [], 'ranked_authorities': [],
                 'ranked_evidence': [], 'tokens': 0}
        self.assertEqual(retrieval.metrics(empty, none), {k: None for k in PUBLIC_METRICS if not k.startswith('retrieved')} |
                         {'annotated_ineligible': 0, 'retrieved_passages': 0, 'retrieved_tokens': 0})
        wrong = {**empty, 'authorities': [shown('z@1')], 'evidence': [{'passage_id': 'n1'}], 'tokens': 20}
        zero = retrieval.metrics(wrong, targets)
        self.assertEqual((zero['exact_version_recall'], zero['prompt_authority_recall'], zero['ineligible_version_leakage'],
                          zero['prompt_evidence_recall'], zero['adverse_authority_coverage']), (0.0, 0.0, 0.0, 0.0, 0.0))
        self.assertEqual((zero['evidence_recall_at_5'], zero['evidence_ndcg_at_10'], zero['authority_recall_at_5'], zero['authority_ndcg_at_10']),
                         (None, None, None, None))
        self.assertIsNone(retrieval.metrics({**wrong, 'arm': 'lexical'}, {**targets, 'evidence': set()})['evidence_recall_at_5'])
        self.assertEqual(retrieval.metrics({**wrong, 'arm': 'lexical'}, targets)['evidence_recall_at_5'], 0.0)
        # A result that did not run is not a measured zero: every metric is None.
        for status in ('unavailable', 'error'):
            self.assertEqual(retrieval.metrics({**result, 'status': status}, targets), {k: None for k in retrieval.METRICS})
        self.assertEqual(retrieval.metrics({**result, 'status': 'ok'}, targets), values)
        # Gold targets of a shipped matter.
        suite, matters, gold = smoke()
        t = retrieval.gold_targets(suite, matters['f8-manifest-a'], gold['f8-manifest-a'])
        self.assertEqual(t, {'evidence': {'f8-manifest-a-s1#1', 'f8-manifest-a-s1#2', 'f8-manifest-a-s2#1', 'f8-manifest-a-s3#1'},
                             'authority': {'vsc-45-2@2018', 'vsc-45-6@2018'}, 'ineligible': set(), 'adverse': {'vsc-45-6@2018'}})
        retrieval_entry = {'matter_id': 'fx-a', 'scenario': 'upstream', 'variant': 'base', 'gold_spans': ['fx-a-s1#1']}
        self.assertEqual(retrieval.gold_targets(suite, matter(posture='retrieval'), retrieval_entry),
                         {'evidence': {'fx-a-s1#1'}, 'authority': set(), 'ineligible': set(), 'adverse': set()})


class SplitAuditTests(unittest.TestCase):
    def test_shared_families_amendment_pairs_and_near_duplicates_are_reported(self):
        statute = [record('vtc-1-1', '2019', effective_to='2024-01-01', status='superseded'), record('vtc-1-1', '2024', effective_from='2024-01-01'),
                   record('vtc-2-1', '2020'), record('vtc-3-1', '2020')]
        text = 'The clerk misplaced the ledger of the registry on the stated date after closing.'

        def entry(matter_id, controlling, ineligible=()):
            return {'matter_id': matter_id, 'controlling_authority': list(controlling), 'ineligible_versions': [list(v) for v in ineligible],
                    'established_exemptions': []}
        a = suite_of(corpus(statute), [matter('fa-a', sources=[source('fa-a-s1', [text])]), matter('fc-a', question='Was a furnace guard absent?',
                                                                                                      sources=[source('fc-a-s1', ['A guard was absent.'])])],
                     [entry('fa-a', ('vtc-1-1', '2024'), [('vtc-1-1', '2019')]), entry('fc-a', ('vtc-3-1', '2020'))])
        b = suite_of(corpus(statute), [matter('fz-b', family_id='fz', sources=[source('fz-b-s1', [text])]),
                                       matter('fc-b', question='Was the seal broken in custody overnight?', sources=[source('fc-b-s1', ['The seal was broken.'])]),
                                       matter('fd-a', question='Was the ledger misplaced?', sources=[source('fd-a-s1', [text + ' A second unrelated sentence follows here.'])])],
                     [entry('fz-b', ('vtc-1-1', '2019'), [('vtc-1-1', '2024')]), entry('fc-b', ('vtc-2-1', '2020')), entry('fd-a', ('vtc-2-1', '2020'))])
        audit = retrieval.audit_splits(a, b)
        self.assertEqual(audit['shared_families'], ['fc'])
        self.assertEqual(audit['shared_amendment_pairs'], ['vtc-1-1'])
        self.assertEqual(audit['near_duplicates'], [['fa-a', 'fz-b', 1.0]])
        disjoint = retrieval.audit_splits(a, suite_of(corpus(statute), [matter('fq-a', question='Was a bell rung at night?',
                                                                               sources=[source('fq-a-s1', ['A bell rang.'])])],
                                                      [entry('fq-a', ('vtc-2-1', '2020'))]))
        self.assertEqual(disjoint, {'shared_families': [], 'shared_amendment_pairs': [], 'near_duplicates': []})
        self.assertEqual(retrieval.audit_splits(b, a)['near_duplicates'], [['fz-b', 'fa-a', 1.0]])


class RetrievalCampaignTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name)
        self.suite = self.path / 'suite'
        shutil.copytree(SUITE, self.suite)
        write_json(self.path / 'inventory.json', {
            'targets': {'local': {'transport': 'local', 'physical_host_id': 'legal-test-host', 'lock_root': str(self.path / 'worker-locks')}},
            'hardware_configs': {'native': {'target': 'local', 'hardware_profile': 'msi-raider-18-hx-ai', 'os_id': 'ubuntu-26.04-native'}}})
        self.case = {'id': 'copied-retrieval', 'parameters': {'suite': 'suite/suite.lock.json', 'synthetic': True,
                                                              'arms': ['no-context', 'filters-only', 'lexical', 'lexical-eligible', 'reference']}}
        self.campaign = {'schema_version': 2, 'id': 'legal-retrieval-test', 'inventory': 'inventory.json', 'phases': [
            {'id': 'legal', 'experiments': [{'id': 'legal-benchmark', 'version': 1, 'mode': 'retrieval', 'cases': ['case.json'],
                                             'hardware_configs': ['native']}]}]}

    def plan(self):
        write_json(self.path / 'case.json', self.case)
        write_json(self.path / 'campaign.json', self.campaign)
        return compile_campaign(self.path / 'campaign.json', ROOT)

    def run_local(self, plan):
        def rpc(target, payload, root, timeout=60):
            if payload['action'] != 'run':
                return {'ok': True}
            out = Path(payload['output'])
            result = get_experiment(payload['job']['experiment_id']).execute(payload['job'], out, Path(payload['root']))
            atomic_json(out / 'result.json', result)
            return result
        with patch('llm_eval.orchestration.resources.lock_root', return_value=self.path / 'locks'), \
                patch('llm_eval.orchestration.transport.rpc', side_effect=rpc):
            directory = initialize(plan, self.path / 'out')
            return directory, run_campaign(directory)

    def private_copy(self):
        for name in ('matters.json', 'corpus.json', 'rubric.json'):
            value = read_json(self.suite / name)
            value['data_class'] = 'private-matter'
            write_json(self.suite / name, value)
        return relock(self.suite, data_class='private-matter')

    def test_retrieval_mode_plans_runs_and_writes_only_public_row_keys(self):
        self.assertEqual(legal.MANIFEST['modes'], ['smoke', 'retrieval', 'generation', 'workflow', 'score'])
        self.assertEqual(legal.MODE_MODULES, {'smoke': 'fixture', 'retrieval': 'retrieval', 'generation': 'workflow', 'workflow': 'workflow',
                                              'score': 'grading'})
        self.assertIs(legal._module('retrieval'), retrieval)
        shipped = read_json(ROOT / 'experiments/legal-benchmark/cases/retrieval.json')
        self.assertEqual(shipped, {'id': 'retrieval', 'parameters': {'suite': '../workloads/original-smoke/suite.lock.json', 'synthetic': True,
                                                                     'arms': ['no-context', 'filters-only', 'lexical', 'lexical-eligible', 'reference'],
                                                                     'top_k': 5, 'token_budget': 1200}})
        self.assertIsNone(legal.validate({**shipped['parameters'], 'suite': str(LOCK)}, ROOT, 'retrieval'))
        before = sorted(p.as_posix() for p in self.path.rglob('*'))
        plan = self.plan()
        after = sorted(p.as_posix() for p in self.path.rglob('*'))
        self.assertEqual(sorted(set(after) - set(before)), [(self.path / 'campaign.json').as_posix(), (self.path / 'case.json').as_posix()])
        (job,) = plan['jobs']
        self.assertEqual((job['status'], job['mode'], job['parameters']['synthetic']), ('planned', 'retrieval', True))
        self.assertEqual(sorted(Path(f['path']).name for f in job['input_files']), ['corpus.json', 'matters.json', 'rubric.json', 'suite.lock.json'])
        directory, code = self.run_local(plan)
        self.assertEqual(code, 0)
        state = read_json(directory / 'campaign.json')
        (record_,) = state['jobs'].values()
        self.assertEqual((state['status'], record_['status']), ('succeeded', 'succeeded'))
        attempt = directory / record_['attempts'][0]['output']
        rows = lines(attempt / 'requests.jsonl')
        self.assertEqual(len(rows), 16 * 5)
        self.assertEqual([(r['task_id'], r['arm']) for r in rows],
                         [(m, a) for m in sorted({r['task_id'] for r in rows}) for a in self.case['parameters']['arms']])
        self.assertEqual({frozenset(r) for r in rows}, {frozenset(ROW_KEYS)})
        known = set(retrieval.REASONS) | set(authority.REASONS)
        self.assertTrue(all(set(r['reason_codes']) <= known for r in rows))
        self.assertTrue(all(r['category'] == r['arm'] and r['benchmark'] == 'legal-original-smoke' and r['synthetic'] is True
                            and r['execution_kind'] == 'fixture' and r['status'] == 'ok' and r['grading_status'] == ('not_applicable' if r['arm'] == 'reference' else 'scored')
                            and r['repetition'] == 0 and r['warmup'] is False and r['inference_status'] == 'not_applicable' for r in rows))
        by = {(r['task_id'], r['arm']): r for r in rows}
        self.assertEqual(by[('f1-ledger-a', 'lexical-eligible')]['quality_pass'], True)
        self.assertEqual(by[('f1-ledger-a', 'lexical')]['quality_pass'], False)      # the superseded version leaks
        self.assertEqual((by[('f2-berth-a', 'reference')]['quality_check_applicable'], by[('f2-berth-a', 'reference')]['quality_pass']), (False, None))
        self.assertTrue(all(by[(m, 'reference')]['exact_version_recall'] is None for m, _ in by))      # reference rows publish no gold-derived number
        private = (attempt / 'local/retrieval-results.jsonl').read_text(encoding='utf-8')
        results = [json.loads(line) for line in private.splitlines()]
        self.assertEqual(len(results), 80)
        for leaked in ('"text"', '"citation"', '"title"', '"description"', EVIDENCE_SENTENCE):
            self.assertNotIn(leaked, private)
        self.assertEqual(set(results[0]['metrics']), set(PUBLIC_METRICS) | {'annotated_ineligible'})
        public = (attempt / 'requests.jsonl').read_text(encoding='utf-8') + (attempt / 'metadata.json').read_text(encoding='utf-8')
        for leaked in (EVIDENCE_SENTENCE, 'Veld Statutes Consolidated', '"recommendation"', 'authority-version', 'annotated_ineligible'):
            self.assertNotIn(leaked, public)
        metadata = read_json(attempt / 'metadata.json')
        self.assertEqual(set(metadata), METADATA_KEYS)
        self.assertEqual((metadata['mode'], metadata['execution_kind'], metadata['policy_id'], metadata['policy_version'], metadata['rows'],
                          metadata['matters'], metadata['families'], metadata['roles'], metadata['review_required']),
                         ('retrieval', 'fixture', 'fixture-default', '1', 80, 16, 8, {}, True))
        self.assertEqual(metadata['retrieval']['backend'], 'memory')
        (receipt,) = state['reports'].values()
        self.assertEqual(receipt['status'], 'disabled')

    def test_execution_kind_decides_the_synthetic_flag(self):
        fixture_arms = {'suite': str(LOCK), 'arms': ['lexical', 'dense'], 'roles': {'embedder': EMBEDDER}}
        with self.assertRaisesRegex(ValueError, 'A fixture run must declare synthetic: true'):
            legal.validate({**fixture_arms, 'synthetic': False}, ROOT, 'retrieval')
        with self.assertRaisesRegex(ValueError, 'A fixture run must declare synthetic: true'):
            legal.validate(fixture_arms, ROOT, 'retrieval')
        self.assertIsNone(legal.validate({**fixture_arms, 'synthetic': True}, ROOT, 'retrieval'))
        self.assertEqual(retrieval.execution_kind({**fixture_arms, 'synthetic': True}, 'retrieval'), 'fixture')
        served = {'suite': str(LOCK), 'arms': ['lexical', 'dense'], 'roles': {'embedder': external('embedder')}}
        with self.assertRaisesRegex(ValueError, 'Only fixture runs may declare synthetic: true'):
            legal.validate({**served, 'synthetic': True}, ROOT, 'retrieval')
        self.assertIsNone(legal.validate({**served, 'synthetic': False}, ROOT, 'retrieval'))
        self.assertIsNone(legal.validate(served, ROOT, 'retrieval'))
        self.assertEqual(retrieval.execution_kind(served, 'retrieval'), 'model-run')
        # A served role that no requested arm uses does not make a model run.
        self.assertEqual(retrieval.execution_kind({**served, 'arms': ['lexical']}, 'retrieval'), 'fixture')
        self.case['parameters']['synthetic'] = False
        with self.assertRaisesRegex(ValueError, 'A fixture run must declare synthetic: true'):
            self.plan()
        for wrong, message in (({'arms': []}, 'arms'), ({'arms': ['lexical', 'lexical']}, 'arms'), ({'arms': ['bm25']}, 'arms'),
                               ({'top_k': 0}, 'top_k'), ({'top_k': 51}, 'top_k'), ({'token_budget': 63}, 'token_budget'),
                               ({'backend': 'elastic'}, 'backend'), ({'roles': {'generator': external('generator')}}, 'roles'),
                               ({'endpoint': 'http://127.0.0.1:1'}, 'Unknown fields')):
            with self.subTest(wrong=wrong), self.assertRaisesRegex(ValueError, message):
                legal.validate({'suite': str(LOCK), 'synthetic': True, 'arms': ['lexical'], **wrong}, ROOT, 'retrieval')
        with self.assertRaisesRegex(ValueError, 'Missing fields: arms'):
            legal.validate({'suite': str(LOCK), 'synthetic': True}, ROOT, 'retrieval')

    def test_private_matter_suite_is_refused_by_the_retrieval_mode(self):
        lock = self.private_copy()
        self.assertEqual(contracts.load_suite(lock)['lock']['data_class'], 'private-matter')
        with self.assertRaisesRegex(ValueError, 'private-matter suites'):
            legal.validate({'suite': str(lock), 'synthetic': True, 'arms': ['lexical']}, ROOT, 'retrieval')
        with self.assertRaisesRegex(ValueError, 'private-matter suites'):
            self.plan()
        self.campaign['phases'][0]['experiments'][0]['mode'] = 'smoke'
        self.case['parameters'] = {'suite': 'suite/suite.lock.json', 'synthetic': True}
        with self.assertRaisesRegex(ValueError, 'public-synthetic suites only'):
            self.plan()
        job = job_for(lock, {'synthetic': True, 'arms': ['lexical']})
        with self.assertRaisesRegex(ValueError, 'private-matter suites'):
            legal.execute(job, self.path / 'attempt', ROOT)
        self.assertFalse((self.path / 'attempt').exists())

    def test_gold_is_checked_by_every_mode(self):
        loaded, _, _ = smoke()
        suite = copy.deepcopy(loaded)
        suite['corpus']['policy'] = {'policy_id': 'no-persuasive', 'version': '1',
                                     'postures': {'screening': {'persuasive_eligible': False}, 'retrieval': {'persuasive_eligible': True}}}
        next(a for a in suite['corpus']['authorities'] if a['authority_id'] == 'vsc-18-7')['weight'] = 'persuasive'
        contracts.validate_corpus(suite['corpus'], suite['lock'])
        with patch.object(legal, 'load_suite', return_value=suite):
            for mode, case in (('smoke', {'suite': 'dict', 'synthetic': True}), ('retrieval', {'suite': 'dict', 'synthetic': True, 'arms': ['lexical']})):
                with self.subTest(mode=mode), self.assertRaisesRegex(ValueError, 'Gold authority is not eligible for its matter: f3-market'):
                    legal.validate(case, ROOT, mode)
        # A retrieval-posture matter with a retrieval rubric entry (package B's shape) passes the gold check.
        upstream = matter('fr-a', posture='retrieval', question='Which passage describes the misplaced ledger?')
        entry = {'matter_id': 'fr-a', 'scenario': 'upstream', 'variant': 'base', 'upstream_id': 'u1', 'upstream_labels': {}, 'gold_spans': ['fr-a-s1#1']}
        mixed = copy.deepcopy(loaded)
        mixed['matters']['matters'].append(upstream)
        mixed['rubric']['matters'].append(entry)
        fixture.check_gold(mixed)
        with patch.object(legal, 'load_suite', return_value=mixed):
            self.assertIsNone(legal.validate({'suite': 'dict', 'synthetic': True, 'arms': ['lexical', 'reference']}, ROOT, 'retrieval'))
        reference = retrieval.reference_passages(mixed, upstream)
        self.assertEqual((ids(reference['evidence']), reference['authorities'], reference['adverse']), (['fr-a-s1#1'], [], []))

    def test_smoke_mode_needs_screening_matters(self):
        loaded, _, _ = smoke()
        mixed = copy.deepcopy(loaded)
        mixed['matters']['matters'].append(matter('fr-a', posture='retrieval'))
        mixed['rubric']['matters'].append({'matter_id': 'fr-a', 'scenario': 'upstream', 'variant': 'base', 'upstream_id': 'u1',
                                          'upstream_labels': {}, 'gold_spans': ['fr-a-s1#1']})
        with self.assertRaisesRegex(ValueError, 'The smoke mode needs screening matters'):
            fixture.check({'suite': 'dict', 'synthetic': True}, mixed, ROOT, 'smoke')
        with patch.object(legal, 'load_suite', return_value=mixed), self.assertRaisesRegex(ValueError, 'The smoke mode needs screening matters'):
            legal.validate({'suite': 'dict', 'synthetic': True}, ROOT, 'smoke')
        self.assertIsNone(fixture.check({'suite': 'dict', 'synthetic': True, 'top_k': 3}, loaded, ROOT, 'smoke'))
        with self.assertRaisesRegex(ValueError, 'top_k'):
            fixture.check({'suite': 'dict', 'synthetic': True, 'top_k': 0}, loaded, ROOT, 'smoke')
        self.assertEqual((fixture.PARAMETERS, fixture.execution_kind({}, 'smoke')), ({'smoke': ({'top_k'}, ('synthetic',))}, 'fixture'))

    def test_public_rows_carry_no_digest_of_the_shown_passages(self):
        arms = list(retrieval.ARMS)
        job = job_for(LOCK, {'synthetic': True, 'arms': arms, 'roles': ROLES})
        out = self.path / 'attempt'
        legal.execute(job, out, ROOT)
        rows, results = lines(out / 'requests.jsonl'), lines(out / 'local/retrieval-results.jsonl')
        self.assertEqual(len(rows), len(results))
        public = (out / 'requests.jsonl').read_text(encoding='utf-8') + (out / 'metadata.json').read_text(encoding='utf-8')
        self.assertNotIn('evidence_sha256', public)
        for row, result in zip(rows, results):
            self.assertEqual((row['task_id'], row['arm']), (result['matter_id'], result['arm']))
            shown = [p['passage_id'] for key in ('authorities', 'adverse', 'evidence', 'prior_briefs') for p in result[key]]
            self.assertEqual(result['evidence_sha256'], digest(shown))      # kept, privately
            self.assertNotIn(digest(shown), json.dumps(row))
            self.assertNotIn(digest(shown), public)
            self.assertEqual(set(row), ROW_KEYS)
            if row['arm'] == 'reference':      # every number of the row would be a function of the reference passages
                self.assertEqual({k: row[k] for k in PUBLIC_METRICS}, {k: None for k in PUBLIC_METRICS})
                self.assertEqual((row['quality_check_applicable'], row['quality_pass'], row['grading_status'], row['reason_codes']),
                                 (False, None, 'not_applicable', []))
                self.assertEqual(result['metrics']['retrieved_passages'], len(shown))      # the real values stay private
                self.assertEqual(result['metrics']['retrieved_tokens'], result['tokens'])
        reference = [r for r in rows if r['arm'] == 'reference']
        self.assertEqual(len(reference), 16)
        # Within the reference rows nothing varies with the matter's reference set.
        varying = {k for k in ROW_KEYS - {'task_id', 'family_id', 'elapsed_s'} if len({json.dumps(r[k]) for r in reference}) > 1}
        self.assertEqual(varying, set())
        self.assertTrue(any(r['retrieved_passages'] for r in rows if r['arm'] == 'lexical'))      # the other arms keep their metrics

    def test_unused_roles_are_neither_recorded_nor_allowed(self):
        served = external('embedder')
        params = {'synthetic': True, 'arms': ['lexical'], 'roles': {'embedder': served}}      # review probe p13
        self.assertIsNone(legal.validate({'suite': str(LOCK), **params}, ROOT, 'retrieval'))
        seen = []
        real = profiles.allowed_endpoints
        with patch.object(profiles, 'allowed_endpoints', side_effect=lambda roles: seen.append(roles) or real(roles)):
            legal.execute(job_for(LOCK, params), self.path / 'attempt', ROOT)
        metadata = read_json(self.path / 'attempt/metadata.json')
        self.assertEqual((metadata['roles'], metadata['retrieval']['embedder_sha256'], metadata['execution_kind']), ({}, None, 'fixture'))
        self.assertEqual(seen, [{}])

    def test_role_profiles_are_checked_before_the_execution_kind(self):
        no_serving = {k: v for k, v in external('embedder').items() if k != 'serving'}
        for synthetic in (True, False):
            with self.subTest(synthetic=synthetic), self.assertRaisesRegex(ValueError, 'A role profile must declare serving'):
                legal.validate({'suite': str(LOCK), 'synthetic': synthetic, 'arms': ['dense'], 'roles': {'embedder': no_serving}}, ROOT, 'retrieval')
        for arms in ([['dense']], [{'arm': 'dense'}], ['dense', 7]):
            with self.subTest(arms=arms), self.assertRaisesRegex(ValueError, 'arms'):
                legal.validate({'suite': str(LOCK), 'synthetic': True, 'arms': arms}, ROOT, 'retrieval')
        for mode in (['retrieval'], {'mode': 'smoke'}, None):
            with self.subTest(mode=mode), self.assertRaisesRegex(ValueError, 'Unsupported legal-benchmark mode'):
                legal.validate({'suite': str(LOCK), 'synthetic': True}, ROOT, mode)

    def test_a_benchmark_corpus_without_authorities_records_no_policy(self):
        loaded, _, _ = smoke()
        upstream = matter('fr-a', posture='retrieval', question='Which passage describes the misplaced ledger?')
        entry = {'matter_id': 'fr-a', 'scenario': 'upstream', 'variant': 'base', 'upstream_id': 'u1', 'upstream_labels': {}, 'gold_spans': ['fr-a-s1#1']}
        suite = copy.deepcopy(loaded)
        suite['lock']['data_class'] = 'public-benchmark'
        suite['corpus'] = {**suite['corpus'], 'data_class': 'public-benchmark', 'authorities': []}
        suite['matters']['matters'] = [upstream]
        suite['rubric']['matters'] = [entry]
        contracts.validate_corpus(suite['corpus'], suite['lock'])
        case = {'suite': 'dict', 'synthetic': True, 'arms': ['no-context', 'filters-only', 'lexical', 'reference']}
        with patch.object(legal, 'load_suite', return_value=suite), patch.object(legal, '_planned_suite', return_value=suite):
            self.assertIsNone(legal.validate(case, ROOT, 'retrieval'))
            result = legal.execute({'mode': 'retrieval', 'parameters': case, 'input_files': []}, self.path / 'attempt', ROOT)
        self.assertEqual(result['status'], 'succeeded')
        metadata = read_json(self.path / 'attempt/metadata.json')
        self.assertEqual((metadata['policy_id'], metadata['policy_version']), (None, None))
        results = lines(self.path / 'attempt/local/retrieval-results.jsonl')
        self.assertEqual({(r['policy_id'], r['policy_version']) for r in results}, {(None, None)})
        self.assertEqual({r['status'] for r in results}, {'ok'})

    @unittest.skipUnless(PACKETS.exists(), 'package B fixture suite is not on this branch')
    def test_ingested_packet_suite_runs_the_retrieval_mode(self):
        suite = contracts.load_suite(PACKETS)
        arms = ['no-context', 'filters-only', 'lexical', 'lexical-eligible', 'reference']
        job = job_for(PACKETS, {'synthetic': True, 'arms': arms})
        out = self.path / 'attempt'
        self.assertEqual(legal.execute(job, out, ROOT)['status'], 'succeeded')
        results = lines(out / 'local/retrieval-results.jsonl')
        metadata = read_json(out / 'metadata.json')
        self.assertEqual(metadata['policy_id'], suite['corpus']['policy']['policy_id'])
        cutoff = suite['corpus']['availability_cutoff']      # the suite's cutoff is in force for every matter
        self.assertTrue(cutoff)
        self.assertEqual({authority.query_for(m, suite['corpus'])['availability_cutoff'] for m in suite['matters']['matters']}, {cutoff})
        matters = suite['matters']['matters']
        shared = suite['matters'].get('shared_sources', [])
        quoted = {span['span_id'] for s in [*shared, *(s for m in matters for s in m['sources'])] for span in s['spans'] if span.get('quoted')}
        excluded = {(mid, span['span_id']) for s in [*shared, *(s for m in matters for s in m['sources'])]
                    for mid in s.get('excluded_matters', []) for span in s['spans']}
        candidate = {span['span_id'] for s in [*shared, *(s for m in matters for s in m['sources'])] for span in s['spans']}
        weights = {a['authority_id'] + '@' + a['version']: a.get('weight', 'controlling') for a in suite['corpus']['authorities']}
        persuasive_seen = 0
        for r in results:
            shown = [p['passage_id'] for key in ('authorities', 'adverse', 'evidence', 'prior_briefs') for p in r[key]]
            self.assertFalse(set(shown) & quoted, r['matter_id'])
            self.assertFalse({(r['matter_id'], p) for p in shown} & excluded, r['matter_id'])
            self.assertTrue(all(p in candidate or p in weights for p in shown))      # the review-set note is not a candidate passage
            for a in r['authorities'] + r['adverse']:
                if weights[a['passage_id']] == 'persuasive' and a['eligibility']['decision'] == 'eligible':
                    self.assertEqual(a['eligibility']['reason_codes'], ['persuasive_only'])
                    persuasive_seen += 1
        self.assertGreater(persuasive_seen, 0)


if __name__ == '__main__':
    unittest.main()
