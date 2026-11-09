import copy
import gzip
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from llm_eval.common import read_json, sha256_file, write_json
from llm_eval.core.contracts import atomic_json
from llm_eval.experiments import REGISTRY, get_experiment, list_experiments, reporting_policy
from llm_eval.experiments import legal_benchmark as legal
from llm_eval.experiments.legal_benchmark import contracts, fixture
from llm_eval.orchestration import worker
from llm_eval.orchestration.planner import compile_campaign
from llm_eval.orchestration.scheduler import initialize, run_campaign
from llm_eval.orchestration.setup import setup_campaign
from llm_eval.reporting.experiment import build_report, finalize_campaign
from llm_eval.reporting.publish import publish_report

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

    def test_registered_with_the_smoke_mode_only(self):
        self.assertEqual(REGISTRY['legal-benchmark'], 'llm_eval.experiments.legal_benchmark')
        self.assertIn(legal.MANIFEST, list_experiments())
        bundled = read_json(ROOT / 'experiments/legal-benchmark/experiment.json')
        self.assertEqual((bundled['id'], bundled['version'], bundled['modes']), ('legal-benchmark', 1, ['smoke']))
        self.assertEqual(legal.MANIFEST['modes'], ['smoke'])
        # The digest that admits a suite to generic reporting is the shipped lock, which pins every suite file.
        self.assertEqual(sha256_file(LOCK), legal.SMOKE_SUITE_SHA256)

    def test_eight_families_each_with_a_base_case_and_one_paired_change(self):
        families = {}
        for m in self.matters.values():
            families.setdefault(m['family_id'], []).append(m['matter_id'])
        self.assertEqual(len(families), 8)
        self.assertTrue(all(len(ids) == 2 and sum(i.endswith('-base') for i in ids) == 1 for ids in families.values()))
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

    def test_reference_pipeline_passes_every_criterion_on_every_matter(self):
        for matter_id in self.matters:
            with self.subTest(matter=matter_id):
                criteria = self.score(self.draft(matter_id), matter_id)
                self.assertEqual(len(criteria), 9)
                self.assertTrue(all(criteria.values()), criteria)

    def test_paired_changes_flip_or_hold_the_recommendation_as_designed(self):
        got = {m: self.draft(m)['recommendation'] for m in self.matters}
        self.assertEqual((got['f1-ledger-base'], got['f1-ledger-earlier-date']), ('charge', 'defer'))      # same citation, older text
        self.assertEqual((got['f2-berth-base'], got['f2-berth-inland-venue']), ('charge', 'decline'))       # wrong venue
        self.assertEqual((got['f6-bridge-base'], got['f6-bridge-after-repeal']), ('charge', 'decline'))     # repealed
        self.assertEqual((got['f3-market-base'], got['f3-market-reinspection']), ('charge', 'defer'))       # contradiction
        self.assertEqual((got['f8-manifest-base'], got['f8-manifest-written-order']), ('charge', 'decline'))  # exemption established
        earlier = self.draft('f1-ledger-earlier-date')
        self.assertEqual([(c['version'], c['status'], c['reason_codes']) for c in earlier['claims']],
                         [('2019', 'supported', []), ('2024', 'insufficient', ['not_yet_effective'])])
        inland = self.draft('f2-berth-inland-venue')
        self.assertEqual({c['authority_id']: c['reason_codes'] for c in inland['claims']},
                         {'vho-3-1': ['wrong_venue'], 'vsc-30-2': ['not_yet_effective']})
        self.assertIn({'code': 'insufficient_authority'}, inland['verification_flags'])

    def test_an_instruction_inside_a_document_is_flagged_and_changes_nothing_else(self):
        base, attacked = self.draft('f5-archive-base'), self.draft('f5-archive-embedded-instruction')
        self.assertEqual(attacked['verification_flags'],
                         [{'code': 'untrusted_instruction_in_source', 'span_id': 'f5-archive-embedded-instruction-email#1'}])
        self.assertEqual(base['verification_flags'], [])
        self.assertEqual((attacked['recommendation'], attacked['review_required']), ('decline', True))
        strip = lambda d: {k: v for k, v in d.items() if k not in ('matter_id', 'verification_flags', 'elements')}      # noqa: E731
        self.assertEqual(strip(base), strip(attacked))
        self.assertEqual([e['status'] for e in base['elements']], [e['status'] for e in attacked['elements']])

    def test_scorer_rejects_wrong_versions_fabricated_citations_and_wrong_calls(self):
        good = self.draft('f1-ledger-base')
        wrong_version = copy.deepcopy(good)
        for claim in wrong_version['claims']:
            claim['status'] = 'supported'      # also endorses the superseded 2019 text
        self.assertFalse(self.score(wrong_version, 'f1-ledger-base')['no_ineligible_version_supported'])
        fabricated = copy.deepcopy(good)
        fabricated['claims'][0].update(authority_id='vsc-99-9')
        self.assertEqual(self.score(fabricated, 'f1-ledger-base'), {'schema_valid': False})
        unanchored = copy.deepcopy(good)
        unanchored['elements'][0]['evidence_span_ids'] = ['f1-ledger-base-report#99']
        self.assertEqual(self.score(unanchored, 'f1-ledger-base'), {'schema_valid': False})
        wrong_call = copy.deepcopy(good)
        wrong_call['recommendation'] = 'decline'
        criteria = self.score(wrong_call, 'f1-ledger-base')
        self.assertEqual([k for k, v in criteria.items() if not v], ['recommendation'])
        unreviewed = copy.deepcopy(good)
        unreviewed['review_required'] = False
        self.assertEqual(self.score(unreviewed, 'f1-ledger-base'), {'schema_valid': False})

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
        output = fixture.draft(self.matters['f3-market-base'], corpus)
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
        self.campaign['phases'][0]['experiments'][0]['mode'] = 'generation'
        with self.assertRaisesRegex(ValueError, 'Unsupported experiment version or mode'):
            self.plan()
        self.campaign['phases'][0]['experiments'][0]['mode'] = 'smoke'
        with self.assertRaisesRegex(ValueError, 'Unsupported legal-benchmark mode'):
            legal.validate(self.case['parameters'], ROOT, 'workflow')
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


if __name__ == '__main__':
    unittest.main()
