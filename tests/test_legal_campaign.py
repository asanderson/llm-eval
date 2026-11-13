import copy
import gzip
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from llm_eval.common import digest, read_json, sha256_file, write_json
from llm_eval.core.contracts import atomic_json
from llm_eval.experiments import REGISTRY, get_experiment, list_experiments, reporting_policy
from llm_eval.experiments import legal_benchmark as legal
from llm_eval.experiments.legal_benchmark import contracts, fixture
from llm_eval.orchestration import worker
from llm_eval.orchestration.planner import compile_campaign
from llm_eval.orchestration.scheduler import initialize, run_campaign
from llm_eval.orchestration.setup import setup_campaign
from llm_eval.report import summarize
from llm_eval.reporting.experiment import build_report, finalize_campaign
from llm_eval.reporting.publish import publish_report, validate_bundle

ROOT = Path(__file__).resolve().parents[1]
SUITE = ROOT / 'experiments/legal-benchmark/workloads/original-smoke'
LOCK = SUITE / 'suite.lock.json'
EVIDENCE_SENTENCE = 'The purser admits he knew the count was lower.'


def relock(directory, **changes):
    """Rewrite the lock of a copied suite after its files were edited on purpose."""
    lock = read_json(directory / 'suite.lock.json')
    new = contracts.make_lock(directory, benchmark_id=lock['benchmark_id'], revision=lock['revision'], split_id=lock['split_id'],
                              data_class=lock['data_class'], jurisdiction_profile=lock['jurisdiction_profile'],
                              manifests={'matters': 'matters.json', 'corpus': 'corpus.json', 'rubric': 'rubric.json'})
    new.update(changes)
    write_json(directory / 'suite.lock.json', new)
    return directory / 'suite.lock.json'


class LegalFixtureTests(unittest.TestCase):
    def setUp(self):
        self.suite = contracts.load_suite(LOCK)
        self.matters = {m['matter_id']: m for m in self.suite['matters']['matters']}
        self.gold = {g['matter_id']: g for g in self.suite['rubric']['matters']}

    def draft(self, matter_id):
        return fixture.draft(self.matters[matter_id], self.suite['corpus'])

    def score(self, output, matter_id):
        return fixture.score(output, self.matters[matter_id], self.gold[matter_id], self.suite['corpus'])

    def test_registered_with_the_five_modes(self):
        self.assertEqual(REGISTRY['legal-benchmark'], 'llm_eval.experiments.legal_benchmark')
        self.assertIn(legal.MANIFEST, list_experiments())
        bundled = read_json(ROOT / 'experiments/legal-benchmark/experiment.json')
        self.assertEqual((bundled['id'], bundled['version'], bundled['modes']), ('legal-benchmark', 1, ['smoke', 'retrieval', 'generation', 'workflow', 'score']))
        self.assertEqual(legal.MANIFEST['modes'], ['smoke', 'retrieval', 'generation', 'workflow', 'score'])
        # The digest that admits a suite to generic reporting is the shipped lock, which pins every suite file.
        self.assertEqual(sha256_file(LOCK), legal.SMOKE_SUITE_SHA256)
        self.assertEqual((self.suite['lock']['revision'], self.suite['rubric']['rubric_version']), ('2026-11-11.1', 'original-smoke-rubric-2'))

    def test_eight_families_each_with_a_base_case_and_one_paired_change(self):
        families = {}
        for m in self.matters.values():
            families.setdefault(m['family_id'], []).append(m['matter_id'])
        self.assertEqual(len(families), 8)
        self.assertTrue(all(len(ids) == 2 and sorted(self.gold[i]['variant'] for i in ids) == ['base', 'paired']
                            for ids in families.values()))
        self.assertEqual({g['recommendation'] for g in self.gold.values()}, {'charge', 'decline', 'defer'})
        self.assertEqual({g['scenario'] for g in self.gold.values()},
                         {'authority-version', 'venue', 'contradiction', 'missing-evidence', 'prompt-injection', 'repeal',
                          'evidence-added', 'adverse-authority'})
        self.assertEqual(self.suite['lock']['data_class'], 'public-synthetic')

    def test_labels_stay_out_of_candidate_inputs(self):
        self.assertEqual((self.suite['matters']['source_set'], self.suite['corpus']['source_set'], self.suite['rubric']['source_set']),
                         ('candidate', 'candidate', 'grader'))
        candidate_text = (SUITE / 'matters.json').read_text(encoding='utf-8') + (SUITE / 'corpus.json').read_text(encoding='utf-8')
        for label in ('"recommendation"', '"scenario"', '"controlling_authority"', '"ineligible_versions"', '"injection_span_ids"'):
            self.assertNotIn(label, candidate_text)
        # draft and retrieve take candidate inputs only: neither accepts a rubric argument
        self.assertEqual(fixture.draft.__code__.co_varnames[:3], ('matter', 'corpus', 'top_k'))

    def test_candidate_identifiers_carry_no_label(self):
        ids, kinds = [], {}
        for m in self.matters.values():
            ids.append(m['matter_id'])
            for s in m['sources']:
                ids.append(s['source_id'])
                ids.extend(span['span_id'] for span in s['spans'])
                kinds.setdefault(s['kind'], set()).add(m['family_id'])
        for i in ids:
            self.assertRegex(i, r'\Af[1-8]-[a-z]+-[ab](-s[0-9]+(#[0-9]+)?)?\Z')
        words = {t for g in self.gold.values() for t in g['scenario'].split('-')} | set(contracts.RECOMMENDATIONS) | {'base', 'paired'}
        leaks = [(i, w) for i in ids for w in words if w in i]
        self.assertEqual(leaks, [])
        self.assertEqual({g['matter_id'][-1] for g in self.gold.values() if g['variant'] == 'base'}, {'a', 'b'})
        self.assertEqual(set(kinds), {'report', 'statement', 'record', 'message'})
        self.assertTrue(all(len(families) >= 3 for families in kinds.values()), kinds)

    def test_reference_pipeline_passes_every_criterion_on_every_matter(self):
        self.assertEqual(len(fixture.CRITERIA), 14)
        for matter_id in self.matters:
            with self.subTest(matter=matter_id):
                criteria = self.score(self.draft(matter_id), matter_id)
                self.assertEqual(set(criteria), set(fixture.CRITERIA))
                self.assertTrue(all(criteria.values()), criteria)

    def test_paired_changes_flip_or_hold_the_recommendation_as_designed(self):
        got = {m: self.draft(m)['recommendation'] for m in self.matters}
        self.assertEqual((got['f1-ledger-a'], got['f1-ledger-b']), ('charge', 'defer'))      # same citation, older text
        self.assertEqual((got['f2-berth-b'], got['f2-berth-a']), ('charge', 'decline'))       # wrong venue
        self.assertEqual((got['f6-bridge-a'], got['f6-bridge-b']), ('charge', 'decline'))     # repealed
        self.assertEqual((got['f3-market-b'], got['f3-market-a']), ('charge', 'defer'))       # contradiction
        self.assertEqual((got['f8-manifest-b'], got['f8-manifest-a']), ('charge', 'decline'))  # exemption established
        earlier = self.draft('f1-ledger-b')
        self.assertEqual([(c['version'], c['status'], c['reason_codes']) for c in earlier['claims']],
                         [('2019', 'supported', []), ('2024', 'insufficient', ['not_yet_effective'])])
        inland = self.draft('f2-berth-a')
        self.assertEqual({c['authority_id']: c['reason_codes'] for c in inland['claims']},
                         {'vho-3-1': ['wrong_venue'], 'vsc-30-2': ['not_yet_effective']})
        self.assertIn({'code': 'insufficient_authority'}, inland['verification_flags'])

    def test_an_instruction_inside_a_document_is_flagged_and_changes_nothing_else(self):
        base, attacked = self.draft('f5-archive-b'), self.draft('f5-archive-a')
        self.assertEqual(attacked['verification_flags'],
                         [{'code': 'untrusted_instruction_in_source', 'span_id': 'f5-archive-a-s3#1'}])
        self.assertEqual(base['verification_flags'], [])
        self.assertEqual((attacked['recommendation'], attacked['review_required']), ('decline', True))
        strip = lambda d: {k: v for k, v in d.items() if k not in ('matter_id', 'verification_flags', 'elements')}      # noqa: E731
        self.assertEqual(strip(base), strip(attacked))
        self.assertEqual([e['status'] for e in base['elements']], [e['status'] for e in attacked['elements']])

    def test_scorer_rejects_wrong_versions_fabricated_citations_and_wrong_calls(self):
        good = self.draft('f1-ledger-a')
        wrong_version = copy.deepcopy(good)
        for claim in wrong_version['claims']:
            claim['status'] = 'supported'      # also endorses the superseded 2019 text
        self.assertFalse(self.score(wrong_version, 'f1-ledger-a')['no_ineligible_version_supported'])
        # A fabricated citation or an unanchored element is scored, not a schema error.
        fabricated = copy.deepcopy(good)
        fabricated['claims'][0].update(authority_id='vsc-99-9')
        criteria = self.score(fabricated, 'f1-ledger-a')
        self.assertEqual((criteria['schema_valid'], criteria['citations_resolve']), (True, False))
        unanchored = copy.deepcopy(good)
        unanchored['elements'][0]['evidence_span_ids'] = ['f1-ledger-a-s1#99']
        criteria = self.score(unanchored, 'f1-ledger-a')
        self.assertEqual((criteria['schema_valid'], criteria['evidence_grounding']), (True, False))
        wrong_call = copy.deepcopy(good)
        wrong_call['recommendation'] = 'decline'
        criteria = self.score(wrong_call, 'f1-ledger-a')
        self.assertEqual([k for k, v in criteria.items() if not v], ['recommendation'])
        unreviewed = copy.deepcopy(good)
        unreviewed['review_required'] = False
        self.assertEqual(self.score(unreviewed, 'f1-ledger-a'), {name: False for name in fixture.CRITERIA})

    def failed(self, output, matter_id):
        criteria = self.score(output, matter_id)
        self.assertEqual(set(criteria), set(fixture.CRITERIA))
        return {name for name, passed in criteria.items() if not passed}

    def test_scorer_rejects_ungrounded_and_misstated_outputs(self):
        def ungrounded(d):
            for e in d['elements']:
                e['evidence_span_ids'], e['adverse_span_ids'] = [], []
            next(c for c in d['claims'] if c['version'] == '2019')['status'] = 'qualified'

        def unrelated_span(d):
            for e in d['elements']:
                e['evidence_span_ids'] = ['f8-manifest-a-s3#1']      # the exhibit: material to the exemption only

        def swapped(d):
            e = next(e for e in d['elements'] if e['status'] == 'contradicted')
            e['evidence_span_ids'], e['adverse_span_ids'] = e['adverse_span_ids'], e['evidence_span_ids']

        def claim(authority_id, version, pinpoint):
            return lambda d: d['claims'].append({'claim_id': 'c9', 'proposition': 'The cited text governs the matter.', 'authority_id': authority_id,
                                                 'version': version, 'pinpoint': pinpoint, 'status': 'supported', 'reason_codes': []})

        def empty(d):
            for key in ('issues', 'elements', 'claims', 'material_conflicts', 'adverse_authorities', 'missing_information', 'verification_flags'):
                d[key] = []
            d['recommendation'] = 'decline'

        def unflagged(d):
            d['verification_flags'] = [f for f in d['verification_flags'] if f['code'] != 'insufficient_evidence']

        def dropped_exemption(d):      # the eligible, not established exemption silently left out
            d['adverse_authorities'] = []
            d['claims'] = [c for c in d['claims'] if c['authority_id'] != 'vsc-45-6']

        cases = [
            ('ungrounded, superseded version qualified', 'f1-ledger-a', ungrounded, {'evidence_grounding', 'claim_status'}),
            ('every element on one unrelated span', 'f8-manifest-a', unrelated_span, {'evidence_grounding'}),
            ('contradicted element with swapped spans', 'f3-market-a', swapped, {'evidence_grounding'}),
            ('unrelated statute supported', 'f1-ledger-a', claim('vsc-27-5', '2021', 's27.5(1)'), {'claim_status'}),
            ('repealed version supported', 'f6-bridge-b', claim('vsc-33-9', '2015', 's33.9(1)'), {'claim_status', 'no_ineligible_version_supported'}),
            ('exemption established without evidence', 'f8-manifest-a',
             lambda d: d['adverse_authorities'][0].update(evidence_span_ids=[]), {'evidence_grounding'}),
            ('material conflict without spans', 'f3-market-a', lambda d: d['material_conflicts'][0].update(span_ids=[]), {'evidence_grounding'}),
            ('everything empty after the repeal', 'f6-bridge-b', empty, {'insufficiency_flagged'}),
            ('everything empty in the inland venue', 'f2-berth-a', empty, {'insufficiency_flagged'}),
            ('insufficient evidence not flagged', 'f1-ledger-b', unflagged, {'insufficiency_flagged'}),
            ('eligible exemption dropped', 'f8-manifest-b', dropped_exemption, {'adverse_authority'}),
            ('second issue on a superseded version', 'f1-ledger-a',
             lambda d: d['issues'].append({'issue_id': 'i2', 'question': 'Which version governs?', 'authority_id': 'vsc-12-4', 'version': '2019'}),
             {'authority_version'}),
        ]
        for name, matter_id, change, expected in cases:
            with self.subTest(name):
                output = self.draft(matter_id)
                change(output)
                failed = self.failed(output, matter_id)
                self.assertNotIn('schema_valid', failed)
                self.assertTrue(expected <= failed, failed)
        self.assertEqual(self.gold['f1-ledger-b']['recommendation'], 'defer')
        with self.subTest('an issue on an eligible exemption stays allowed'):
            output = self.draft('f8-manifest-b')
            output['issues'].append({'issue_id': 'i2', 'question': 'Does the exemption apply?', 'authority_id': 'vsc-45-6', 'version': '2018'})
            self.assertEqual(self.failed(output, 'f8-manifest-b'), set())

    def test_scorer_compares_injection_flags_with_the_spans_shown(self):
        matter, gold, corpus = self.matters['f5-archive-a'], self.gold['f5-archive-a'], self.suite['corpus']
        flagged = self.draft('f5-archive-a')
        unflagged = copy.deepcopy(flagged)
        unflagged['verification_flags'] = []
        shown = {span['span_id'] for s in matter['sources'] for span in s['spans']} - {'f5-archive-a-s3#1'}
        self.assertFalse(fixture.score(flagged, matter, gold, corpus, shown=shown)['untrusted_instruction_flagged'])
        self.assertTrue(fixture.score(unflagged, matter, gold, corpus, shown=shown)['untrusted_instruction_flagged'])
        self.assertEqual(fixture.score(flagged, matter, gold, corpus, shown=None), fixture.score(flagged, matter, gold, corpus))
        self.assertTrue(all(fixture.score(flagged, matter, gold, corpus, shown=None).values()))
        self.assertFalse(fixture.score(unflagged, matter, gold, corpus, shown=None)['untrusted_instruction_flagged'])

    def test_material_conflict_cites_both_polarities(self):
        # The shipped rubric cannot express this case: its only contradicted element (f3-market-a `unstamped`) has exactly one
        # support and one adverse span, so any two distinct spans of it already cover both. Build the case in memory.
        matter, gold = copy.deepcopy(self.matters['f3-market-a']), copy.deepcopy(self.gold['f3-market-a'])
        text = 'A second report repeats that the measure was unstamped.'
        matter['sources'][0]['spans'].append({'span_id': 'f3-market-a-s1#2', 'text': text, 'text_sha256': contracts.text_digest(text)})
        gold['evidence_spans']['unstamped']['support'].append('f3-market-a-s1#2')
        output = fixture.draft(matter, self.suite['corpus'])
        self.assertTrue(all(fixture.score(output, matter, gold, self.suite['corpus']).values()))
        output['material_conflicts'][0]['span_ids'] = ['f3-market-a-s1#1', 'f3-market-a-s1#2']      # two support spans, no adverse
        criteria = fixture.score(output, matter, gold, self.suite['corpus'])
        self.assertEqual((criteria['schema_valid'], criteria['evidence_grounding']), (True, False))

    def test_scorer_is_total_and_keeps_its_denominator(self):
        def duplicated(d):
            first = d['elements'][0]
            d['elements'].insert(0, dict(first, status='missing', evidence_span_ids=[], adverse_span_ids=[]))

        cases = [
            ('issue authority without version', 'f1-ledger-a', lambda d: d['issues'][0].pop('version')),
            ('instruction flag without span', 'f5-archive-a', lambda d: d['verification_flags'][0].pop('span_id')),
            ('flag code outside the closed set', 'f1-ledger-a', lambda d: d['verification_flags'].append({'code': 'recommend_charge'})),
            ('list as element id', 'f1-ledger-a', lambda d: d['elements'][0].update(element_id=['removal'])),
            ('mixed-type conflict ids', 'f3-market-a', lambda d: d['material_conflicts'].append({'element_id': 7, 'span_ids': []})),
            ('element listed twice', 'f1-ledger-a', duplicated),
            ('established exemption listed again as not established', 'f8-manifest-a',
             lambda d: d['adverse_authorities'].append(dict(d['adverse_authorities'][0], status='not_established', evidence_span_ids=[]))),
            ('identical adverse authority listed twice', 'f8-manifest-b', lambda d: d['adverse_authorities'].append(dict(d['adverse_authorities'][0]))),
        ]
        for name, matter_id, change in cases:
            with self.subTest(name):
                output = self.draft(matter_id)
                change(output)
                with self.assertRaises(ValueError):
                    contracts.validate_structure(output, self.matters[matter_id])
                self.assertEqual(self.score(output, matter_id), {name: False for name in fixture.CRITERIA})
                self.assertEqual(len(self.score(output, matter_id)), 14)
        output = self.draft('f8-manifest-a')
        output['adverse_authorities'].append(dict(output['adverse_authorities'][0]))
        with self.assertRaisesRegex(ValueError, 'Duplicate adverse authority in output: vsc-45-6@2018'):
            contracts.validate_structure(output, self.matters['f8-manifest-a'])

    def test_reference_failures_are_scored_not_schema_errors(self):
        cases = [
            ('fabricated authority in an issue', lambda d: d['issues'][0].update(authority_id='vsc-99-9'), 'fabricated_citation', 'citations_resolve'),
            ('fabricated authority in a claim', lambda d: d['claims'][1].update(authority_id='vsc-99-9'), 'fabricated_citation', 'citations_resolve'),
            ('unknown version', lambda d: d['claims'][1].update(version='2099'), 'unknown_version', 'citations_resolve'),
            ('wrong pinpoint', lambda d: d['claims'][1].update(pinpoint='s12.4(9)'), 'pinpoint_mismatch', 'pinpoints_correct'),
            ('span of another matter', lambda d: d['elements'][0].update(evidence_span_ids=['f1-ledger-b-s1#1']), 'unknown_span', 'evidence_grounding'),
        ]
        matter, corpus = self.matters['f1-ledger-a'], self.suite['corpus']
        for name, change, code, criterion in cases:
            with self.subTest(name):
                output = self.draft('f1-ledger-a')
                change(output)
                self.assertIs(contracts.validate_structure(output, matter), output)
                with self.assertRaises(ValueError):
                    contracts.validate_output(output, matter, corpus)
                self.assertEqual([e['code'] for e in contracts.reference_errors(output, matter, corpus)], [code])
                criteria = self.score(output, 'f1-ledger-a')
                self.assertEqual((criteria['schema_valid'], criteria[criterion]), (True, False))
        output = self.draft('f1-ledger-a')
        output['issues'][0]['authority_id'] = 'vsc-99-9'
        self.assertEqual(contracts.reference_errors(output, matter, corpus),
                         [{'code': 'fabricated_citation', 'locator': {'list': 'issues', 'index': 0}}])
        self.assertEqual(contracts.reference_errors(self.draft('f1-ledger-a'), matter, corpus), [])

    def test_candidate_output_is_bounded_and_typed(self):
        matter = self.matters['f1-ledger-a']

        def oversized(d):
            n, text = contracts.MAX_ITEMS, 'x' * contracts.MAX_TEXT
            d['issues'] = [{'issue_id': f'i{i}', 'question': text} for i in range(n)]
            d['claims'] = [dict(d['claims'][1], claim_id=f'c{i}', proposition=text) for i in range(n)]
            d['missing_information'] = [{'element_id': 'removal', 'needed': text} for _ in range(n)]

        cases = [
            ('65 claims', lambda d: d.update(claims=[dict(d['claims'][1], claim_id=f'c{i}') for i in range(65)])),
            ('2,001 character proposition', lambda d: d['claims'][0].update(proposition='x' * 2001)),
            ('dict as claim id', lambda d: d['claims'][0].update(claim_id={'id': 'c1'})),
            ('string as reason codes', lambda d: d['claims'][0].update(reason_codes='no_longer_effective')),
            ('above the serialized size bound', oversized),
        ]
        for name, change in cases:
            with self.subTest(name):
                output = self.draft('f1-ledger-a')
                change(output)
                with self.assertRaises(ValueError):
                    contracts.validate_structure(output, matter)
                self.assertFalse(any(self.score(output, 'f1-ledger-a').values()))
        # Only spans of role `evidence` anchor a finding; a prior brief does not.
        briefed = copy.deepcopy(matter)
        text = 'An earlier memo concluded that the crates were removed.'
        briefed['sources'].append({'source_id': 'f1-ledger-a-s3', 'role': 'prior_brief', 'version': '1', 'kind': 'report',
                                   'spans': [{'span_id': 'f1-ledger-a-s3#1', 'text': text, 'text_sha256': contracts.text_digest(text)}]})
        output = fixture.draft(briefed, self.suite['corpus'])
        output['elements'][0]['evidence_span_ids'] = ['f1-ledger-a-s3#1']
        self.assertEqual([e['code'] for e in contracts.reference_errors(output, briefed, self.suite['corpus'])], ['unknown_span'])

    def test_reference_passages_do_not_depend_on_gold_conclusions(self):
        for matter_id, g in self.gold.items():
            with self.subTest(matter=matter_id):
                order = [span['span_id'] for s in self.matters[matter_id]['sources'] for span in s['spans']]
                evidence = g['reference_passages']['evidence']
                self.assertEqual(evidence, sorted(evidence, key=order.index))
                material = {i for spans in g['evidence_spans'].values() for i in spans['support'] + spans['adverse']}
                material |= {i for spans in g['exemption_spans'].values() for i in spans} | set(g['injection_span_ids'])
                self.assertEqual(set(evidence), material)
        a, b = self.gold['f8-manifest-a']['reference_passages'], self.gold['f8-manifest-b']['reference_passages']
        self.assertEqual((a['authorities'], a['adverse']), (b['authorities'], b['adverse']))
        self.assertEqual(a['adverse'], ['vsc-45-6@2018'])
        with tempfile.TemporaryDirectory() as tmp:
            for name, change in (('adverse omits an eligible exemption', lambda p: p.update(adverse=[])),
                                 ('exemption listed as authority', lambda p: p.update(authorities=p['authorities'] + p['adverse'], adverse=[]))):
                with self.subTest(name):
                    directory = Path(tmp) / name.replace(' ', '-')
                    shutil.copytree(SUITE, directory)
                    rubric = read_json(directory / 'rubric.json')
                    change(next(g for g in rubric['matters'] if g['matter_id'] == 'f8-manifest-b')['reference_passages'])
                    write_json(directory / 'rubric.json', rubric)
                    lock = relock(directory)
                    with self.assertRaises(ValueError):
                        fixture.check_gold(contracts.load_suite(lock))
                    with self.assertRaises(ValueError):
                        legal.validate({'suite': str(lock), 'synthetic': True}, ROOT)

    def test_eligibility_boundaries_and_unknown_validity(self):
        authority = {'venues': ['veld-central'], 'effective_from': '2024-03-01', 'effective_to': '2025-01-01', 'status': 'in_force'}
        check = lambda day, venue='veld-central', **kw: fixture.eligible({**authority, **kw}, {'operative_date': day, 'venue': venue})      # noqa: E731
        self.assertEqual(check('2024-03-01'), ('eligible', []))                         # first day applies
        self.assertEqual(check('2024-02-29'), ('ineligible', ['not_yet_effective']))
        self.assertEqual(check('2024-12-31'), ('eligible', []))
        self.assertEqual(check('2025-01-01'), ('ineligible', ['no_longer_effective']))  # effective_to is exclusive
        self.assertEqual(check('2023-01-01', 'veld-harbor'), ('ineligible', ['wrong_venue', 'not_yet_effective']))
        self.assertEqual(check('2024-06-01', status='unknown'), ('unknown', ['validity_unknown']))
        corpus = copy.deepcopy(self.suite['corpus'])
        next(a for a in corpus['authorities'] if a['authority_id'] == 'vsc-18-7')['status'] = 'unknown'
        output = fixture.draft(self.matters['f3-market-b'], corpus)
        self.assertEqual((output['recommendation'], output['claims'][0]['status']), ('defer', 'qualified'))
        self.assertIn({'code': 'authority_validity_unknown'}, output['verification_flags'])


class SuiteLockTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name) / 'suite'
        shutil.copytree(SUITE, self.dir)
        self.lock = self.dir / 'suite.lock.json'

    def edit(self, name, change):
        value = read_json(self.dir / name)
        change(value)
        write_json(self.dir / name, value)

    def test_a_copied_suite_loads_and_a_changed_byte_makes_the_lock_stale(self):
        self.assertEqual(contracts.load_suite(self.lock)['lock_sha256'], legal.SMOKE_SUITE_SHA256)
        with (self.dir / 'matters.json').open('a', encoding='utf-8') as handle:
            handle.write(' ')
        with self.assertRaisesRegex(ValueError, 'stale'):
            contracts.load_suite(self.lock)

    def test_malformed_and_unsafe_locks_are_rejected(self):
        original = read_json(self.lock)
        cases = {
            'Unknown fields': lambda l: l.update(extra=True),
            'Missing fields': lambda l: l.pop('revision'),
            'schema_version': lambda l: l.update(schema_version=2),
            'data_class': lambda l: l.update(data_class='secret'),
            'escapes': lambda l: l['source_files'][0].update(path='../matters.json'),
            'relative POSIX': lambda l: l['source_files'][0].update(path='..\\matters.json'),
            'Duplicate suite file purpose': lambda l: l['source_files'].append(dict(l['source_files'][0])),
            'Duplicate suite file path': lambda l: l['source_files'][1].update(path=l['source_files'][0]['path']),
            'missing': lambda l: l['source_files'][0].update(path='absent.json'),
            'purpose': lambda l: l['source_files'][0].update(purpose='notes'),
            'does not match': lambda l: l.update(matter_manifest='corpus.json'),
            'lists no source files': lambda l: l.update(source_files=[]),
        }
        for message, change in cases.items():
            with self.subTest(message=message):
                lock = copy.deepcopy(original)
                change(lock)
                write_json(self.lock, lock)
                with self.assertRaisesRegex(ValueError, message):
                    contracts.load_suite(self.lock)
        self.lock.write_text('{not json', encoding='utf-8')
        with self.assertRaises(ValueError):
            contracts.load_suite(self.lock)

    def test_a_link_that_leaves_the_lock_directory_is_rejected(self):
        outside = self.dir.parent / 'outside.json'
        shutil.copy(self.dir / 'matters.json', outside)
        (self.dir / 'matters.json').unlink()
        try:
            os.symlink(outside, self.dir / 'matters.json')
        except (OSError, NotImplementedError):
            self.skipTest('symbolic links are not available to this user')
        with self.assertRaisesRegex(ValueError, 'escapes'):
            contracts.load_suite(self.lock)

    def test_conflicting_classification_duplicates_and_dangling_references_are_rejected(self):
        self.edit('rubric.json', lambda r: r.update(data_class='private-matter'))
        with self.assertRaisesRegex(ValueError, 'Conflicting data classification'):
            contracts.load_suite(relock(self.dir))
        self.edit('rubric.json', lambda r: r.update(data_class='public-synthetic'))
        self.assertTrue(contracts.load_suite(relock(self.dir)))
        changes = {
            'Duplicate matter': ('matters.json', lambda m: m['matters'].append(copy.deepcopy(m['matters'][0]))),
            'does not match its digest': ('matters.json', lambda m: m['matters'][0]['sources'][0]['spans'][0].update(text='edited')),
            'must start with its source id': ('matters.json', lambda m: m['matters'][0]['sources'][0]['spans'][0].update(span_id='x#1')),
            'Duplicate authority version': ('corpus.json', lambda c: c['authorities'].append(copy.deepcopy(c['authorities'][0]))),
            'undeclared venue': ('matters.json', lambda m: m['matters'][0].update(venue='elsewhere')),
            'exactly one rubric entry': ('rubric.json', lambda r: r['matters'].pop()),
            'unknown authority version': ('rubric.json', lambda r: r['matters'][0]['ineligible_versions'].append(['vsc-12-4', '1999'])),
            'grader source set': ('rubric.json', lambda r: r.update(source_set='candidate')),
        }
        for message, (name, change) in changes.items():
            with self.subTest(message=message):
                shutil.rmtree(self.dir)
                shutil.copytree(SUITE, self.dir)
                self.edit(name, change)
                with self.assertRaisesRegex(ValueError, message):
                    contracts.load_suite(relock(self.dir))

    def fresh(self):
        shutil.rmtree(self.dir)
        shutil.copytree(SUITE, self.dir)

    def authority(self, corpus, authority_id='vsc-18-7'):
        return next(a for a in corpus['authorities'] if a['authority_id'] == authority_id)

    def test_malformed_types_duplicates_and_versions_are_value_errors(self):
        loaded = contracts.load_suite(self.lock)
        self.assertEqual(loaded['file_sha256'], {name: sha256_file(self.dir / name) for name in ('matters.json', 'corpus.json', 'rubric.json')})
        self.assertEqual(loaded['lock_sha256'], sha256_file(self.lock))
        manifests = {
            'numeric question': ('matters.json', lambda m: m['matters'][0].update(question=5), 'A matter question must be a nonempty string'),
            'numeric span text': ('matters.json', lambda m: m['matters'][0]['sources'][0]['spans'][0].update(text=5),
                                  'Span text does not match its digest'),
            'manifest schema_version true': ('matters.json', lambda m: m.update(schema_version=True), 'Unsupported matters manifest version'),
            'numeric title': ('corpus.json', lambda c: c['authorities'][0].update(title=5), 'Authority title must be a nonempty string'),
            'pinpoint above 100 characters': ('corpus.json', lambda c: c['authorities'][0].update(pinpoint='s' * 101),
                                              'Authority pinpoint must be a nonempty string of at most 100 characters'),
            'numeric authority text': ('corpus.json', lambda c: c['authorities'][0].update(text=5), 'Authority text does not match its digest'),
            'string elements': ('corpus.json', lambda c: c['authorities'][0].update(elements='removal'), 'An authority needs at least one element'),
            'authorities: 5': ('corpus.json', lambda c: c.update(authorities=5), 'authorities must be a list'),
            'list gold elements': ('rubric.json', lambda r: r['matters'][0].update(elements=['removal']), 'Gold elements must be an object'),
        }
        for name, (file_name, change, message) in manifests.items():
            with self.subTest(name):
                self.fresh()
                self.edit(file_name, change)
                with self.assertRaisesRegex(ValueError, message):
                    contracts.load_suite(relock(self.dir))
        with self.subTest('pinpoint of exactly 100 characters'):
            self.fresh()
            self.edit('corpus.json', lambda c: c['authorities'][0].update(pinpoint='s' * 100))
            contracts.load_suite(relock(self.dir))
        locks = {
            'path "."': (lambda l: l['source_files'][0].update(path='.'), 'Suite path escapes the lock directory: .'),
            'lock schema_version true': (lambda l: l.update(schema_version=True), 'Suite lock schema_version must be 1'),
            'revision with a space': (lambda l: l.update(revision='2026 11'), 'Suite lock needs a revision'),
            'revision with a newline': (lambda l: l.update(revision='2026-11\n# heading'), 'Suite lock needs a revision'),
            'whitespace revision': (lambda l: l.update(revision='  '), 'Suite lock needs a revision'),
        }
        for name, (change, message) in locks.items():
            with self.subTest(name):
                self.fresh()
                self.edit('suite.lock.json', change)
                with self.assertRaisesRegex(ValueError, message):
                    contracts.load_suite(self.lock)
        with self.subTest('duplicated key'):
            self.fresh()
            text = (self.dir / 'matters.json').read_text(encoding='utf-8')
            (self.dir / 'matters.json').write_text(text.replace('"schema_version": 1,', '"schema_version": 1,\n  "schema_version": 1,', 1),
                                                   encoding='utf-8', newline='\n')
            with self.assertRaisesRegex(ValueError, 'Duplicate JSON key: schema_version'):
                contracts.load_suite(relock(self.dir))
            self.fresh()
            text = self.lock.read_text(encoding='utf-8')
            self.lock.write_text(text.replace('"split_id": "smoke",', '"split_id": "smoke",\n  "split_id": "other",', 1), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'Duplicate JSON key: split_id'):
                contracts.load_suite(self.lock)

    def test_optional_corpus_keys_are_type_checked_and_given_meaning(self):
        optional = {'original_sha256': 'a' * 64, 'jurisdiction': 'veld-fictional-v1', 'court': None, 'weight': 'controlling',
                    'aliases': ['VSC 18.7', 'Measures Act'], 'snapshot': {'id': 's1', 'published': '2025-01-01'}, 'review': {'reviewer_role': 'fixture', 'reviewed_on': '2025-01-01'},
                    'status_as_of': '2025-01-01'}

        def everything(c):
            c.update(policy={'policy_id': 'fixture-test', 'version': '1', 'effective_to_inclusive': False}, availability_cutoff='2026-01-01')
            for a in c['authorities']:
                a.update(optional)

        self.edit('corpus.json', everything)
        suite, shipped = contracts.load_suite(relock(self.dir)), contracts.load_suite(LOCK)
        for matter in shipped['matters']['matters']:
            self.assertEqual(fixture.draft(matter, suite['corpus']), fixture.draft(matter, shipped['corpus']))
        self.edit('corpus.json', lambda c: self.authority(c).update(court='veld-high-court', weight='persuasive', snapshot={'id': 's2', 'published': '2025-06-01'},
                                                                     review=None, status_as_of=None))
        contracts.load_suite(relock(self.dir))
        wrong = [('policy', []), ('availability_cutoff', 'soon'), ('original_sha256', 'A' * 64), ('original_sha256', 'a' * 63),
                 ('jurisdiction', 'Veld'), ('court', 5), ('weight', 'binding'), ('aliases', ['x', 'x']), ('aliases', ['']),
                 ('aliases', 'x'), ('snapshot', 'x'), ('review', []), ('status_as_of', '2025-13-01'),
                 ('snapshot', {'id': 's1'}), ('snapshot', {'id': 's1', 'published': 'soon'}), ('review', {'reviewer_role': 'fixture'})]
        for key, value in wrong:
            with self.subTest(key=key, value=value):
                self.fresh()
                top = key in ('policy', 'availability_cutoff')
                self.edit('corpus.json', lambda c: (c if top else self.authority(c)).update({key: value}))
                with self.assertRaises(ValueError):
                    contracts.load_suite(relock(self.dir))
        self.fresh()
        self.edit('corpus.json', lambda c: self.authority(c).update(treatment='overruled'))
        with self.assertRaisesRegex(ValueError, 'Unknown fields'):
            contracts.load_suite(relock(self.dir))
        self.fresh()
        self.edit('corpus.json', lambda c: self.authority(c).update(status='invalidated'))
        suite = contracts.load_suite(relock(self.dir))
        matter = next(m for m in suite['matters']['matters'] if m['matter_id'] == 'f3-market-b')
        self.assertEqual(fixture.eligible(self.authority(suite['corpus']), matter), ('ineligible', ['obsolete_status']))

    def test_rubric_must_be_self_consistent(self):
        def entry(r, matter_id='f1-ledger-a'):
            return next(g for g in r['matters'] if g['matter_id'] == matter_id)

        cases = [
            ('unknown conflict element', 'rubric.json', lambda r: entry(r, 'f3-market-a')['conflict_elements'].append('ghost'),
             'Gold conflict_elements must be exactly the elements with status contradicted: f3-market-a'),
            ('gold authority not eligible', 'matters.json',
             lambda m: next(x for x in m['matters'] if x['matter_id'] == 'f1-ledger-a').update(operative_date='2023-11-02'),
             'Gold authority is not eligible for its matter: f1-ledger-a'),
            ('evidence span of another matter', 'rubric.json', lambda r: entry(r)['evidence_spans']['removal'].update(support=['f1-ledger-b-s1#1']),
             'Rubric evidence spans must be evidence spans of the matter: f1-ledger-a'),
            ('supported element with an adverse span', 'rubric.json',
             lambda r: entry(r)['evidence_spans']['removal'].update(adverse=['f1-ledger-a-s1#1']),
             'Gold evidence spans do not match the element status: f1-ledger-a removal'),
            ('missing variant', 'rubric.json', lambda r: entry(r).pop('variant'), 'Missing fields: variant'),
        ]
        for name, file_name, change, message in cases:
            with self.subTest(name):
                self.fresh()
                self.edit(file_name, change)
                with self.assertRaisesRegex(ValueError, message):
                    fixture.check_gold(contracts.load_suite(relock(self.dir)))

    def test_gold_ineligible_version_must_not_be_eligible(self):
        self.edit('rubric.json', lambda r: next(g for g in r['matters'] if g['matter_id'] == 'f1-ledger-a')['ineligible_versions'].append(
            ['vsc-12-4', '2024']))
        suite = contracts.load_suite(relock(self.dir))
        with self.assertRaisesRegex(ValueError, 'A gold ineligible version is eligible for its matter: f1-ledger-a'):
            fixture.check_gold(suite)

    def test_exemption_spans_name_exactly_the_established_exemptions(self):
        def entry(r, matter_id):
            return next(g for g in r['matters'] if g['matter_id'] == matter_id)

        cases = [
            ('key for an exemption that is not established', lambda r: entry(r, 'f8-manifest-b')['exemption_spans'].update(
                {'vsc-45-6@2018': ['f8-manifest-b-s1#1']}), 'Gold exemption_spans must name exactly the established exemptions: f8-manifest-b'),
            ('established exemption without a key', lambda r: entry(r, 'f8-manifest-a').update(exemption_spans={}),
             'Gold exemption_spans must name exactly the established exemptions: f8-manifest-a'),
            ('empty span list', lambda r: entry(r, 'f8-manifest-a')['exemption_spans'].update({'vsc-45-6@2018': []}),
             'An established exemption needs evidence spans: f8-manifest-a'),
            ('span outside the evidence of the matter', lambda r: entry(r, 'f8-manifest-a')['exemption_spans'].update(
                {'vsc-45-6@2018': ['f8-manifest-b-s1#1']}), 'Rubric evidence spans must be evidence spans of the matter: f8-manifest-a'),
        ]
        for name, change, message in cases:
            with self.subTest(name):
                self.fresh()
                self.edit('rubric.json', change)
                with self.assertRaisesRegex(ValueError, message):
                    contracts.load_suite(relock(self.dir))

    def test_candidate_view_holds_no_grader_data(self):
        suite = contracts.load_suite(self.lock)
        view = contracts.candidate_view(suite)
        self.assertEqual(set(view), set(contracts.CANDIDATE_KEYS))
        # No grader file metadata: the lock in the view lists only the candidate files.
        self.assertEqual([(f['purpose'], f['path']) for f in view['lock']['source_files']], [('matters', 'matters.json'), ('corpus', 'corpus.json')])
        self.assertEqual({k: v for k, v in view['lock'].items() if k != 'source_files'},
                         {k: v for k, v in suite['lock'].items() if k != 'source_files'})
        self.assertEqual(len(suite['lock']['source_files']), 3)      # the suite itself is not changed
        text = json.dumps(view)
        rubric_entry = next(f for f in suite['lock']['source_files'] if f['purpose'] == 'rubric')
        self.assertNotIn(rubric_entry['sha256'], text)

        def strings(value):      # every string value; key names such as "venue" are schema, not labels
            if isinstance(value, dict):
                return {s for v in value.values() for s in strings(v)}
            if isinstance(value, list):
                return {s for v in value for s in strings(v)}
            return {value} if isinstance(value, str) else set()

        self.assertFalse({g['scenario'] for g in suite['rubric']['matters']} & strings(view))
        self.assertNotIn(suite['rubric']['rubric_version'], text)
        gold_keys = {k for g in suite['rubric']['matters'] for k in g} - {'matter_id', 'elements'}
        self.assertEqual([k for k in sorted(gold_keys) if '"' + k + '"' in text], [])
        matter = view['matters']['matters'][0]
        self.assertEqual(fixture.draft(matter, view['corpus']), fixture.draft(suite['matters']['matters'][0], suite['corpus']))

    def test_private_files_cannot_take_reserved_report_names(self):
        out = self.dir.parent / 'attempt'
        for relative in ('metadata.json', 'x/requests.jsonl', 'model_judgment/a.jsonl', 'reports/a.csv', '../a.json', '/a.json'):
            with self.subTest(relative=relative), self.assertRaises(ValueError):
                contracts.private_file(out, relative)
        path = contracts.private_file(out, 'score-detail.jsonl')
        self.assertEqual(path, out / 'local' / 'score-detail.jsonl')
        self.assertTrue(path.parent.is_dir())
        attempt = self.dir.parent / 'model_judgment' / 'attempt'
        job = {'mode': 'smoke', 'parameters': {'suite': str(self.lock), 'synthetic': True},
               'input_files': [{'path': str(self.lock), 'sha256': sha256_file(self.lock)}]}
        with self.assertRaisesRegex(ValueError, 'directory name the generic report scans'):
            legal.execute(job, attempt, ROOT)
        self.assertFalse(attempt.exists())


class LegalCampaignTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name)
        self.suite = self.path / 'suite'
        shutil.copytree(SUITE, self.suite)
        write_json(self.path / 'inventory.json', {
            'targets': {'local': {'transport': 'local', 'physical_host_id': 'legal-test-host', 'lock_root': str(self.path / 'worker-locks')}},
            'hardware_configs': {'native': {'target': 'local', 'hardware_profile': 'msi-raider-18-hx-ai', 'os_id': 'ubuntu-26.04-native'}}})
        self.case = {'id': 'copied-smoke', 'parameters': {'suite': 'suite/suite.lock.json', 'synthetic': True}}
        self.campaign = {'schema_version': 2, 'id': 'legal-test', 'inventory': 'inventory.json', 'phases': [
            {'id': 'legal', 'experiments': [{'id': 'legal-benchmark', 'version': 1, 'mode': 'smoke', 'cases': ['case.json'],
                                             'hardware_configs': ['native']}]}]}

    def plan(self):
        write_json(self.path / 'case.json', self.case)
        write_json(self.path / 'campaign.json', self.campaign)
        return compile_campaign(self.path / 'campaign.json', ROOT)

    def run_local(self, plan):
        """Run through the real scheduler with the worker call made in-process (no child process, no network)."""
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

    def test_shipped_campaign_plans_one_fixture_job_without_side_effects(self):
        before = sorted(p.as_posix() for p in (ROOT / 'experiments/legal-benchmark').rglob('*'))
        plan = compile_campaign(ROOT / 'campaigns/legal-smoke.json', ROOT)
        self.assertEqual(before, sorted(p.as_posix() for p in (ROOT / 'experiments/legal-benchmark').rglob('*')))
        (job,) = plan['jobs']
        self.assertEqual((job['status'], job['experiment_id'], job['mode'], job['case_id'], job['parameters']['synthetic']),
                         ('planned', 'legal-benchmark', 'smoke', 'smoke', True))
        self.assertEqual(sorted(Path(f['path']).name for f in job['input_files']),
                         ['corpus.json', 'matters.json', 'rubric.json', 'suite.lock.json'])
        self.assertTrue(all(plan['inputs'][f['path']] == f['sha256'] for f in job['input_files']))
        self.assertEqual(plan['reporting'].get('publish', {}).get('mode', 'none'), 'none')
        self.assertEqual(plan, compile_campaign(ROOT / 'campaigns/legal-smoke.json', ROOT))
        self.plan()
        self.assertEqual(sorted(p.name for p in self.path.iterdir()), ['campaign.json', 'case.json', 'inventory.json', 'suite'])

    def test_invalid_cases_modes_and_private_data_are_rejected_at_plan(self):
        self.campaign['phases'][0]['experiments'][0]['mode'] = 'live-review'
        with self.assertRaisesRegex(ValueError, 'Unsupported experiment version or mode'):
            self.plan()
        self.campaign['phases'][0]['experiments'][0]['mode'] = 'smoke'
        with self.assertRaisesRegex(ValueError, 'Unsupported legal-benchmark mode'):
            legal.validate(self.case['parameters'], ROOT, 'draft')
        for parameters, message in (({'suite': 'suite/suite.lock.json', 'synthetic': False}, 'synthetic: true'),
                                    ({'suite': 'suite/suite.lock.json'}, 'Missing fields'),
                                    ({'suite': 'suite/suite.lock.json', 'synthetic': True, 'endpoint': 'http://127.0.0.1:1'}, 'Unknown fields'),
                                    ({'suite': 'suite/suite.lock.json', 'synthetic': True, 'top_k': 0}, 'top_k')):
            with self.subTest(parameters=parameters):
                self.case['parameters'] = parameters
                with self.assertRaisesRegex(ValueError, message):
                    self.plan()
        self.case['parameters'] = {'suite': 'suite/suite.lock.json', 'synthetic': True}
        for name in ('matters.json', 'corpus.json', 'rubric.json'):
            value = read_json(self.suite / name)
            value['data_class'] = 'private-matter'
            write_json(self.suite / name, value)
        relock(self.suite, data_class='private-matter')
        with self.assertRaisesRegex(ValueError, 'public-synthetic suites only'):
            self.plan()

    def test_campaign_runs_scores_and_reports_locally_and_resume_adds_nothing(self):
        self.case['parameters']['suite'] = str(LOCK)      # the exact shipped suite: the only one admitted to reporting
        directory, code = self.run_local(self.plan())
        self.assertEqual(code, 0)
        state = read_json(directory / 'campaign.json')
        (record,) = state['jobs'].values()
        self.assertEqual((state['status'], record['status'], len(record['attempts'])), ('succeeded', 'succeeded', 1))
        attempt = directory / record['attempts'][0]['output']
        rows = [json.loads(line) for line in (attempt / 'requests.jsonl').read_text(encoding='utf-8').splitlines()]
        self.assertEqual(len(rows), 16)
        self.assertEqual(len({r['family_id'] for r in rows}), 8)
        self.assertTrue(all(r['synthetic'] and r['execution_kind'] == 'fixture' and r['status'] == 'ok' and r['quality_pass']
                            and r['decision_correct'] and r['review_status'] == 'pending_human_review' for r in rows))
        self.assertEqual({(r['repetition'], r['arm'], r['criteria_total'], r['criteria_passed']) for r in rows}, {(0, 'smoke', 14, 14)})
        details = [json.loads(line) for line in (attempt / 'local/score-detail.jsonl').read_text(encoding='utf-8').splitlines()]
        self.assertEqual([set(d) for d in details], [{'matter_id', 'family_id', 'arm', 'repetition', 'status', 'grading_status', 'criteria',
                                                       'errors', 'pending_dimensions', 'reviewed_dimensions', 'adjudicated',
                                                       'gold_recommendation', 'choice', 'author_choice', 'complete'}] * 16)
        self.assertTrue(all(d['arm'] == 'smoke' and d['repetition'] == 0 and d['grading_status'] == 'scored' and d['errors'] == []
                            and d['choice'] == d['author_choice'] == d['gold_recommendation'] and set(d['criteria']) == set(fixture.CRITERIA)
                            for d in details))
        self.assertEqual(sorted(d['matter_id'] for d in details if not d['complete']),
                         ['f1-ledger-b', 'f3-market-a', 'f4-seal-b', 'f7-furnace-a'])
        metadata = read_json(attempt / 'metadata.json')
        self.assertEqual((metadata['suite_lock_sha256'], metadata['matters'], metadata['all_pass'], metadata['review_required']),
                         (legal.SMOKE_SUITE_SHA256, 16, 16, True))
        (receipt,) = state['reports'].values()
        self.assertEqual(receipt['status'], 'generated')      # one local report, nothing published
        self.assertNotIn('pull_request', receipt)
        report = directory / receipt['report']
        bundle = next((report / 'bundle/docs/results/legal-benchmark').iterdir())
        manifest = read_json(bundle / 'manifest.json')
        self.assertEqual((manifest['status'], manifest['synthetic']), ('complete', True))
        summary = read_json(bundle / 'summary.json')
        self.assertEqual(sum(r['requests'] for r in summary), 16)
        self.assertTrue(all(r['decision_accuracy'] == 1 and r['quality_pass_rate'] == 1 and r['synthetic'] for r in summary))
        # Drafts and grader detail stay in the attempt; no evidence text reaches the report bundle.
        self.assertIn(EVIDENCE_SENTENCE, (attempt / 'local/candidate-outputs.jsonl').read_text(encoding='utf-8') +
                      (SUITE / 'matters.json').read_text(encoding='utf-8'))
        raw = gzip.decompress((bundle / 'raw/measurements.jsonl.gz').read_bytes()).decode()
        for leaked in (EVIDENCE_SENTENCE, 'candidate-outputs', 'score-detail', '"claims"'):
            self.assertNotIn(leaked, raw)
        with patch('llm_eval.orchestration.resources.lock_root', return_value=self.path / 'locks'), \
                patch('llm_eval.orchestration.transport.rpc', side_effect=AssertionError('a finished job must not run again')):
            self.assertEqual(run_campaign(directory), 0)
        resumed = read_json(directory / 'campaign.json')
        self.assertEqual(len(next(iter(resumed['jobs'].values()))['attempts']), 1)
        self.assertEqual(len((attempt / 'requests.jsonl').read_text(encoding='utf-8').splitlines()), 16)
        with self.assertRaisesRegex(ValueError, 'already has request records'):
            legal.execute(read_json(attempt / 'job.json'), attempt, ROOT)

    def test_suite_bytes_changed_after_planning_fail_at_every_layer(self):
        plan = self.plan()
        with patch('llm_eval.orchestration.resources.lock_root', return_value=self.path / 'locks'):
            directory = initialize(plan, self.path / 'out')
        with (self.suite / 'rubric.json').open('a', encoding='utf-8') as handle:
            handle.write(' ')
        with self.assertRaisesRegex(ValueError, 'Campaign input changed'):      # coordinator, on run and on resume
            run_campaign(directory)
        job = plan['jobs'][0]
        with self.assertRaisesRegex(ValueError, 'Worker input hash mismatch'):     # worker, before any child starts
            worker.handle({'action': 'run', 'job': job, 'root': str(ROOT), 'output': str(self.path / 'attempt'),
                           'owner': 'test', 'code_revision': plan['code_revision']})
        self.assertFalse((self.path / 'attempt').exists())
        with self.assertRaisesRegex(ValueError, 'stale'):                           # plugin, when it re-verifies the lock
            legal.execute(job, self.path / 'attempt', ROOT)
        self.assertFalse((self.path / 'attempt').exists())

    def test_relocked_suite_after_planning_fails_in_the_plugin(self):
        plan = self.plan()
        (job,) = plan['jobs']
        # A path mapping may spell the same file differently; the lookup uses the unmodified string, so this still runs.
        planned = job['parameters']['suite']
        spelled = copy.deepcopy(job)
        spelled['parameters']['suite'] = str(Path(planned).parent) + '/./' + Path(planned).name
        for f in spelled['input_files']:
            if f['path'] == planned:
                f['path'] = spelled['parameters']['suite']
        self.assertEqual(legal.execute(spelled, self.path / 'spelled', ROOT)['status'], 'succeeded')
        listed = copy.deepcopy(job)
        listed['parameters']['suite'] = [planned]      # a hand-built job: a ValueError, never a TypeError
        with self.assertRaisesRegex(ValueError, 'suite must be a path string'):
            legal.execute(listed, self.path / 'listed', ROOT)
        with self.assertRaisesRegex(ValueError, 'suite must be a path string'):
            legal.validate(listed['parameters'], ROOT)
        self.assertFalse((self.path / 'listed').exists())
        # A consistent relock after planning: every byte matches the new lock, but not the plan.
        rubric = read_json(self.suite / 'rubric.json')
        rubric['matters'][0]['recommendation'] = 'defer'
        write_json(self.suite / 'rubric.json', rubric)
        relock(self.suite)
        self.assertTrue(contracts.load_suite(self.suite / 'suite.lock.json'))
        with self.assertRaisesRegex(ValueError, 'Suite differs from the planned input'):
            legal.execute(job, self.path / 'attempt', ROOT)
        self.assertFalse((self.path / 'attempt').exists())

    def test_report_policy_reads_the_lock_on_disk(self):
        relock(self.suite, revision='operator-copy')
        lock = str(self.suite / 'suite.lock.json')
        claimed = {'mode': 'smoke', 'parameters': {'suite': lock, 'synthetic': True},
                   'input_files': [{'path': lock, 'sha256': legal.SMOKE_SUITE_SHA256}]}
        self.assertFalse(legal.reporting_policy([claimed])['report'])
        for suite in (str(self.path / 'absent.lock.json'), ['not', 'a', 'path']):
            missing = {**claimed, 'parameters': {'suite': suite, 'synthetic': True}}
            self.assertFalse(legal.reporting_policy([missing])['report'])
        shipped = compile_campaign(ROOT / 'campaigns/legal-smoke.json', ROOT)
        self.assertTrue(legal.reporting_policy(shipped['jobs'])['report'])

    def test_setup_installs_nothing_for_the_smoke_and_keeps_the_default_for_other_experiments(self):
        with patch('llm_eval.orchestration.setup.rpc', side_effect=AssertionError('the smoke needs no install')), \
                patch('llm_eval.orchestration.setup.reserve', side_effect=AssertionError('the smoke reserves nothing')):
            self.assertEqual(setup_campaign(self.plan()), 0)
        calls = []
        def rpc(target, payload, root, timeout=60):      # noqa: E306
            calls.append((payload['action'], payload.get('platform')))
            return {'status': 'succeeded'}
        routing = compile_campaign(ROOT / 'campaigns/routing-smoke.json', ROOT)
        with patch('llm_eval.orchestration.setup.rpc', side_effect=rpc), patch('llm_eval.orchestration.setup.reserve'), \
                patch('llm_eval.orchestration.setup.release'), patch('builtins.print'):
            self.assertEqual(setup_campaign(routing), 0)
        self.assertIn(('setup', 'ollama'), calls)      # an experiment without the hook keeps the earlier default

    def test_only_the_shipped_suite_is_reported_and_nothing_is_published(self):
        shipped = compile_campaign(ROOT / 'campaigns/legal-smoke.json', ROOT)
        self.assertEqual({k: v for k, v in reporting_policy('legal-benchmark', shipped['jobs']).items() if k != 'reason'},
                         {'report': True, 'publish': False})
        self.assertEqual(reporting_policy('llm-routing', [])['publish'], True)
        self.assertEqual(reporting_policy('legal-benchmark', [])['report'], False)
        # A copied suite with one changed revision is a different suite: it runs, but no report bundle is written.
        relock(self.suite, revision='operator-copy')
        self.campaign['reporting'] = {'on_experiment_end': True, 'include_outputs': True}
        plan = self.plan()
        self.assertEqual(reporting_policy('legal-benchmark', plan['jobs'])['report'], False)
        directory, code = self.run_local(plan)
        self.assertEqual(code, 0)
        state = read_json(directory / 'campaign.json')
        (receipt,) = state['reports'].values()
        self.assertEqual(receipt['status'], 'disabled')
        experiment = directory / 'experiments' / plan['experiments'][0]['experiment_run_id']
        self.assertFalse((experiment / 'report').exists())
        with self.assertRaisesRegex(ValueError, 'Report generation is disabled'):      # the manual command hits the same check
            build_report(experiment)
        self.assertEqual(next(iter(finalize_campaign(directory).values()))['status'], 'disabled')
        self.assertFalse((experiment / 'report').exists())

    def test_publication_is_rejected_at_plan_at_finalize_and_by_the_manual_command(self):
        self.campaign['reporting'] = {'publish': {'mode': 'pull-request', 'repository': 'asanderson/llm-eval'}}
        with self.assertRaisesRegex(ValueError, 'Publication is not available for legal-benchmark'):
            self.plan()
        self.campaign['reporting'] = {'on_experiment_end': True}
        self.case['parameters']['suite'] = str(LOCK)
        plan = self.plan()
        directory, code = self.run_local(plan)
        self.assertEqual(code, 0)
        report = directory / next(iter(read_json(directory / 'campaign.json')['reports'].values()))['report']
        for dry_run in (True, False):
            with self.subTest(dry_run=dry_run), self.assertRaisesRegex(ValueError, 'Publication is not available for legal-benchmark'):
                publish_report(report, ROOT, dry_run=dry_run, api=object())
        # A plan edited after the fact to ask for a pull request still publishes nothing.
        stored = read_json(directory / 'plan.json')
        stored['reporting'] = {'on_experiment_end': True, 'publish': {'mode': 'pull-request'}, 'include_outputs': True}
        write_json(directory / 'plan.json', stored)
        state = read_json(directory / 'campaign.json')
        state['reports'] = {}
        write_json(directory / 'campaign.json', state)
        with patch('llm_eval.reporting.publish.publish_report', side_effect=AssertionError('must not publish')):
            (receipt,) = finalize_campaign(directory).values()
        self.assertEqual(receipt['status'], 'generated')
        self.assertNotIn('pull_request', receipt)
        # Relabelling the bundle as another experiment does not help: its manifest and resolved jobs still say legal.
        spec = read_json(report / 'publication.json')
        spec['experiment_id'] = 'llm-routing'
        write_json(report / 'publication.json', spec)
        with self.assertRaisesRegex(ValueError, 'Publication is not available for legal-benchmark'):
            publish_report(report, ROOT, dry_run=True)


class LegalGuardTests(unittest.TestCase):
    """The smallest hooks in the shared reporting paths that keep a legal result out of generic publication."""
    setUp = LegalCampaignTests.setUp
    plan = LegalCampaignTests.plan
    run_local = LegalCampaignTests.run_local

    def shipped_report(self):
        self.case['parameters']['suite'] = str(LOCK)
        directory, code = self.run_local(self.plan())
        self.assertEqual(code, 0)
        receipt = next(iter(read_json(directory / 'campaign.json')['reports'].values()))
        self.assertEqual(receipt['status'], 'generated')
        return directory / receipt['report']

    @staticmethod
    def relabel(report, name, raw=None):
        """Edit only files inside the report directory, then recompute the manifest so the bundle stays self-consistent."""
        spec = read_json(report / 'publication.json')
        bundle = report / 'bundle'
        dest = bundle / spec['report_path']
        resolved = read_json(dest / 'resolved-config.json')
        resolved['experiment']['experiment_id'] = name
        for job in resolved['jobs']:
            job['experiment_id'] = name
        write_json(dest / 'resolved-config.json', resolved)
        archive = dest / 'raw/measurements.jsonl.gz'
        if raw == 'delete':
            archive.unlink()
        elif raw == 'drop-metadata':
            lines = gzip.decompress(archive.read_bytes()).decode().splitlines()
            kept = [line for line in lines if line and json.loads(line)['record_type'] != 'metadata']
            archive.write_bytes(gzip.compress(('\n'.join(kept) + '\n').encode(), mtime=0))
        manifest = read_json(dest / 'manifest.json')
        manifest.pop('report_fingerprint')
        manifest['experiment_id'] = name
        manifest['files'] = {p.relative_to(bundle).as_posix(): sha256_file(p) for p in sorted(bundle.rglob('*'))
                             if p.is_file() and p != dest / 'manifest.json'}
        manifest['report_fingerprint'] = digest(manifest)
        write_json(dest / 'manifest.json', manifest)
        spec.update(experiment_id=name, report_fingerprint=manifest['report_fingerprint'])
        write_json(report / 'publication.json', spec)

    @staticmethod
    def remanifest(report):
        spec = read_json(report / 'publication.json')
        bundle = report / 'bundle'
        dest = bundle / spec['report_path']
        manifest = read_json(dest / 'manifest.json')
        manifest.pop('report_fingerprint')
        manifest['experiment_id'] = spec['experiment_id']
        manifest['files'] = {p.relative_to(bundle).as_posix(): sha256_file(p) for p in sorted(bundle.rglob('*'))
                             if p.is_file() and p != dest / 'manifest.json'}
        manifest['report_fingerprint'] = digest(manifest)
        write_json(dest / 'manifest.json', manifest)
        spec['report_fingerprint'] = manifest['report_fingerprint']
        write_json(report / 'publication.json', spec)

    DELETE = object()

    @classmethod
    def move_and_relabel(cls, report, name, *, raw_benchmark, summary_benchmark, mode=None, drop_metadata=False):
        """A consistent relabel: the bundle and chart move to `name`, every id says `name`, the raw metadata ids too, and the
        benchmark names in the raw rows and the summaries are rewritten (or deleted with DELETE)."""
        spec = read_json(report / 'publication.json')
        bundle = report / 'bundle'
        for key in ('report_path', 'chart_path'):
            old = Path(spec[key])
            new = Path(*old.parts[:2], name, *old.parts[3:])
            (bundle / new).parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(bundle / old), str(bundle / new))
            shutil.rmtree(bundle / Path(*old.parts[:3]))
            spec[key] = new.as_posix()
        spec['experiment_id'] = name
        write_json(report / 'publication.json', spec)
        dest = bundle / spec['report_path']

        def rename(data, value):
            if 'benchmark' in data:
                if value is cls.DELETE:
                    data.pop('benchmark')
                else:
                    data['benchmark'] = value
        resolved = read_json(dest / 'resolved-config.json')
        resolved['experiment']['experiment_id'] = name
        for job in resolved['jobs']:
            job['experiment_id'] = name
            job['mode'] = mode or job['mode']
        write_json(dest / 'resolved-config.json', resolved)
        archive = dest / 'raw/measurements.jsonl.gz'
        records = []
        for line in gzip.decompress(archive.read_bytes()).decode().splitlines():
            record = json.loads(line)
            if record['record_type'] == 'metadata':
                if drop_metadata:
                    continue
                for key in ('experiment', 'experiment_id'):
                    if key in record['data']:
                        record['data'][key] = name
            rename(record['data'], raw_benchmark)
            records.append(json.dumps(record, sort_keys=True))
        archive.write_bytes(gzip.compress(('\n'.join(records) + '\n').encode(), mtime=0))
        for file_name in ('summary.json', 'benchmark-summary.json'):
            rows = read_json(dest / file_name)
            for row in rows:
                rename(row, summary_benchmark)
                rename(row.get('data', {}), summary_benchmark)
            write_json(dest / file_name, rows)
        cls.remanifest(report)

    def test_relabelled_report_is_refused_by_publish_results(self):
        report = self.shipped_report()
        pristine = report.parent / 'pristine-report'
        shutil.copytree(report, pristine)
        cases = [('every label edited', 'llm-routing', None, 'Publication'),
                 ('metadata records removed from the raw archive', 'llm-routing', 'drop-metadata', 'Publication'),
                 ('raw archive deleted', 'llm-routing', 'delete', 'raw measurements archive'),
                 ('relabelled to an unregistered id', 'unregistered-fixture', None, 'unregistered experiment')]
        for name, label, raw, message in cases:
            with self.subTest(name):
                shutil.rmtree(report)
                shutil.copytree(pristine, report)
                self.relabel(report, label, raw)
                validate_bundle(report)      # the edited bundle is internally consistent
                with self.assertRaisesRegex(ValueError, message):
                    publish_report(report, ROOT, dry_run=True)
        legal_refusal = 'Publication is not available for legal-benchmark'
        mode_refusal = 'Publication identity mismatch: mode smoke is not a mode of llm-routing'
        # Each case is caught by exactly one check: the job mode, the normalised claim, the raw request rows, the summaries.
        moved = [('consistent relabel, benchmark renamed', dict(raw_benchmark='routing-smoke', summary_benchmark='routing-smoke'), mode_refusal),
                 ('consistent relabel, benchmark deleted', dict(raw_benchmark=self.DELETE, summary_benchmark=self.DELETE), mode_refusal),
                 ('benchmark in upper case, routing mode', dict(raw_benchmark='LEGAL-smoke', summary_benchmark='LEGAL-smoke', mode='decision'),
                  legal_refusal),
                 ('benchmark with a leading space, routing mode', dict(raw_benchmark=' legal-smoke', summary_benchmark=' legal-smoke',
                                                                       mode='decision'), legal_refusal),
                 ('only the raw request rows say legal-smoke', dict(raw_benchmark='legal-smoke', summary_benchmark='routing-smoke',
                                                                    mode='decision', drop_metadata=True), legal_refusal),
                 ('only the summaries say legal-smoke', dict(raw_benchmark='routing-smoke', summary_benchmark='legal-smoke', mode='decision'),
                  legal_refusal)]
        for name, change, message in moved:
            with self.subTest(name):
                shutil.rmtree(report)
                shutil.copytree(pristine, report)
                self.move_and_relabel(report, 'llm-routing', **change)
                spec = read_json(report / 'publication.json')
                self.assertTrue(spec['report_path'].startswith('docs/results/llm-routing/'))
                validate_bundle(report)
                with self.assertRaisesRegex(ValueError, message):
                    publish_report(report, ROOT, dry_run=True)

    def test_malformed_bundles_are_value_errors(self):
        report = self.shipped_report()
        pristine = report.parent / 'pristine-report'
        shutil.copytree(report, pristine)

        def short_path(r):
            spec = read_json(r / 'publication.json')
            bundle = r / 'bundle'
            shutil.move(str(bundle / spec['report_path']), str(bundle / 'moved'))
            shutil.rmtree(bundle / 'docs')
            (bundle / 'docs').mkdir()
            shutil.move(str(bundle / 'moved'), str(bundle / 'docs/results'))
            spec['report_path'] = 'docs/results'
            write_json(r / 'publication.json', spec)
            self.remanifest(r)

        def list_id(r):
            spec = read_json(r / 'publication.json')
            spec['experiment_id'] = ['legal-benchmark']
            write_json(r / 'publication.json', spec)

        def archive(r, data):
            spec = read_json(r / 'publication.json')
            path = r / 'bundle' / spec['report_path'] / 'raw/measurements.jsonl.gz'
            path.write_bytes(data(path.read_bytes()))
            self.remanifest(r)

        def summary_missing(r, name):
            spec = read_json(r / 'publication.json')
            (r / 'bundle' / spec['report_path'] / name).unlink()
            self.remanifest(r)

        cases = [('report path with two parts', short_path, 'Malformed publication bundle'),
                 ('list as experiment id', list_id, 'Malformed publication bundle'),
                 ('raw line that is not an object', lambda r: archive(r, lambda b: gzip.compress(gzip.decompress(b) + b'[1, 2]\n', mtime=0)),
                  'Malformed raw measurements archive'),
                 ('corrupt gzip', lambda r: archive(r, lambda b: b'not a gzip stream'), 'Malformed raw measurements archive'),
                 ('raw line nested too deep', lambda r: archive(r, lambda b: gzip.compress(gzip.decompress(b) + b'[' * 100000 + b']' * 100000 + b'\n',
                                                                                          mtime=0)), 'Malformed raw measurements archive'),
                 ('summary.json missing', lambda r: summary_missing(r, 'summary.json'), 'Publication needs the report summary: summary.json'),
                 ('benchmark-summary.json missing', lambda r: summary_missing(r, 'benchmark-summary.json'),
                  'Publication needs the report summary: benchmark-summary.json')]
        for name, change, message in cases:
            with self.subTest(name):
                shutil.rmtree(report)
                shutil.copytree(pristine, report)
                change(report)
                with self.assertRaisesRegex(ValueError, message):
                    publish_report(report, ROOT, dry_run=True)

    def test_legacy_report_ignores_legal_attempts(self):
        tree = self.path / 'tree'
        legacy = tree / 'legacy'
        legacy.mkdir(parents=True)
        config = dict(model_id='x', platform='llama.cpp', os_id='ubuntu', context_tokens=4096, backend_version='1', lane='offload')
        write_json(legacy / 'metadata.json', {'synthetic': False, 'config': config, 'suite_sha256': 'a'})
        rows = [{'task_id': 'a', 'warmup': w, 'status': 'ok', 'elapsed_s': v, 'quality_pass': True} for w, v in [(True, 999), (False, 2)]]
        (legacy / 'requests.jsonl').write_text('\n'.join(json.dumps(r) for r in rows))
        (job,) = self.plan()['jobs']
        legal.execute(job, tree / 'legal', ROOT)
        for synthetic in (True, False):
            if not synthetic:
                metadata = read_json(tree / 'legal/metadata.json')
                metadata['synthetic'] = False
                write_json(tree / 'legal/metadata.json', metadata)
            for include in (False, True):
                with self.subTest(legal_synthetic=synthetic, include_synthetic=include):
                    cohorts = summarize(tree, include_synthetic=include)
                    self.assertEqual([(c['model'], c['task'], c['requests']) for c in cohorts], [('x', 'a', 1)])
                    self.assertNotIn('f1-ledger', json.dumps(cohorts))

    def test_relabelled_experiment_record_cannot_build_a_report(self):
        relock(self.suite, revision='operator-copy')
        plan = self.plan()
        directory, code = self.run_local(plan)
        self.assertEqual(code, 0)
        experiment = directory / 'experiments' / plan['experiments'][0]['experiment_run_id']
        record = read_json(experiment / 'experiment.json')
        record['experiment_id'] = 'llm-routing'
        write_json(experiment / 'experiment.json', record)
        with self.assertRaisesRegex(ValueError, 'Experiment identity does not match its planned jobs'):
            build_report(experiment)
        self.assertFalse((experiment / 'report').exists())


if __name__ == '__main__':
    unittest.main()
