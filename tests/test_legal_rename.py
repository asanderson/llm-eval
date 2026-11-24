"""The legal experiment was `legal-benchmark` until 2026-11-24, when it became `legal-models`. Campaigns, attempts, output
manifests, reports and published bundles of that time carry the former id, and attempts name their suite by the path it had
then (`experiments/legal-benchmark/...`), which the rename removed. The plugin must still read all of them as its own,
still claim content that carries the former id, keep cohort digests comparable across the rename, and read an old attempt
through the suite its caller names."""
import io
import json
import re
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from llm_eval.common import read_json, sha256_file, write_json
from llm_eval.core.contracts import atomic_json
from llm_eval.experiments import RENAMED, canonical, get_experiment, list_experiments, plugin_hook
from llm_eval.experiments import legal_models as legal
from llm_eval.experiments.legal_models import contracts, fixture, reporting
from llm_eval.orchestration import worker
from llm_eval.reporting.experiment import build_report, projected_bundle
from llm_eval.reporting.publish import publish_report
from tests.test_legal_publication import Base, write_plan
from tests.test_legal_routing import PACKETS, SMOKE, TempCase, build_calibration_attempts, grading, routing, selector_role, served
from tests.test_legal_workflow import FakeGenerator, execute, generator, job_for

ROOT = Path(__file__).resolve().parents[1]
FORMER, CURRENT = 'legal-benchmark', 'legal-models'


class LegalModelsRenameTests(unittest.TestCase):
    def test_the_former_id_resolves_to_the_plugin_but_is_not_listed(self):
        self.assertEqual(RENAMED[FORMER], CURRENT)
        self.assertIs(get_experiment(FORMER), get_experiment(CURRENT))
        self.assertEqual((canonical(FORMER), get_experiment(CURRENT).MANIFEST['id']), (CURRENT, CURRENT))
        self.assertIs(plugin_hook(FORMER, 'verify_publication'), plugin_hook(CURRENT, 'verify_publication'))
        self.assertNotIn(FORMER, [m['id'] for m in list_experiments()])
        self.assertEqual((contracts.EXPERIMENT_ID, contracts.EXPERIMENT_IDS), (CURRENT, (CURRENT, FORMER)))

    def test_a_campaign_must_name_the_current_id(self):
        from llm_eval.orchestration.planner import compile_campaign
        with tempfile.TemporaryDirectory() as tmp:
            campaign = read_json(ROOT / 'campaigns/legal-smoke.json')
            campaign['inventory'] = str(ROOT / 'configs/targets/local.example.json')
            current = Path(tmp) / 'current.json'
            write_json(current, campaign)
            plan = compile_campaign(current, ROOT)
            self.assertEqual({j['experiment_id'] for j in plan['jobs']}, {CURRENT})
            self.assertTrue(all(j['job_id'].startswith('legal-legal-models-1-') for j in plan['jobs']))
            campaign['phases'][0]['experiments'][0]['id'] = FORMER
            former = Path(tmp) / 'former.json'
            write_json(former, campaign)
            with self.assertRaisesRegex(ValueError, 'Experiment legal-benchmark was renamed legal-models: use the new id in the campaign'):
                compile_campaign(former, ROOT)

    def test_cohort_digests_do_not_change_with_the_rename(self):
        job = {'mode': 'generation', 'hardware': {'os_id': 'windows-11-native', 'hardware_profile': 'msi-raider-18-hx-ai'}}
        metadata = {'experiment': CURRENT, 'execution_kind': 'model-run', 'data_class': 'public-synthetic',
                    'benchmark_id': 'legal-original-smoke', 'suite_lock_sha256': 'a' * 64,
                    'roles': {'generator': {'profile_sha256': 'b' * 64, 'model': 'm', 'model_revision': 'r'}}}
        current, former = reporting.cohort(job, metadata, 'direct'), reporting.cohort(job, {**metadata, 'experiment': FORMER}, 'direct')
        self.assertEqual(current, former)      # the same settings before and after the rename are one cohort
        self.assertEqual(current[0]['experiment'], FORMER)
        self.assertNotEqual(reporting.cohort(job, {**metadata, 'experiment': 'model-offloading'}, 'direct')[1], current[1])

    def test_a_report_is_headed_with_the_id_its_campaign_was_planned_with(self):
        generic = {'campaign_id': 'fixture', 'experiment_run_id': 'legal-run', 'code_revision': 'a' * 40}
        manifest = {'execution_kinds': ['fixture'], 'data_class': 'public-synthetic', 'cohorts': 0}
        former = reporting._readme(generic, manifest, [], [], [], [], False, FORMER)
        current = reporting._readme(generic, manifest, [], [], [], [], False, CURRENT)
        self.assertEqual(former.splitlines()[0], '# legal-benchmark results')      # as before the rename
        self.assertEqual(current.splitlines()[0], '# legal-models results')
        self.assertEqual(former.replace(FORMER, CURRENT), current)      # nothing else differs

    def test_the_former_id_stays_a_mark_of_legal_content(self):
        markers = reporting._text_markers(reporting._markers())
        self.assertIn(CURRENT, markers)
        self.assertIn(FORMER, markers)      # a generic bundle carrying the former id is still refused

    def test_a_stored_plan_without_a_digest_is_refused_for_either_id(self):
        for experiment in contracts.EXPERIMENT_IDS:      # a plan that holds a legal job has always had its digest
            self.assertFalse(reporting.plan_unchanged({'jobs': [{'experiment_id': experiment}]}), experiment)
        self.assertTrue(reporting.plan_unchanged({'jobs': [{'experiment_id': 'model-offloading'}]}))


class FormerIdCampaignTests(Base):
    """A campaign as one planned and run before the rename stores it, taken through the report and the publication gates."""

    def former_campaign(self, name):
        """A finished smoke campaign of the approved suite, rewritten to the former id wherever a campaign stores an id: the
        plan (experiment entry and job), the experiment record and the attempt's job and metadata. The plan digest and the
        attempt receipts are then recomputed, as their writers computed them."""
        directory = self.smoke(name=name, reporting={'on_experiment_end': False})
        plan = read_json(directory / 'plan.json')
        for item in plan['experiments'] + plan['jobs']:
            item['experiment_id'] = FORMER
        write_plan(directory, plan)
        experiment, attempt = self.experiment_dir(directory), self.attempt(directory)
        for path, key in ((experiment / 'experiment.json', 'experiment_id'), (attempt / 'job.json', 'experiment_id'), (attempt / 'metadata.json', 'experiment')):
            value = read_json(path)
            self.assertEqual(value[key], CURRENT, path.name)
            write_json(path, {**value, key: FORMER})
        self.rereceipt(directory)
        return directory, experiment

    def test_a_campaign_of_the_former_id_reports_and_passes_the_gates_under_that_id(self):
        directory, experiment = self.former_campaign('former')
        report = build_report(experiment)
        self.assertEqual([p.name for p in (report / 'bundle/docs/results').iterdir()], [FORMER])
        (bundle,) = (report / 'bundle/docs/results' / FORMER).iterdir()
        resolved = read_json(bundle / 'resolved-config.json')
        self.assertEqual((bundle / 'README.md').read_text(encoding='utf-8').splitlines()[0], '# legal-benchmark results')
        self.assertEqual((read_json(bundle / 'manifest.json')['experiment_id'], resolved['experiment']['experiment_id'],
                          {j['experiment_id'] for j in resolved['jobs']}), (FORMER, FORMER, {FORMER}))
        with self.assertRaisesRegex(ValueError, '^Publication is not available for legal-models: not_authorized$'):
            publish_report(report, ROOT, dry_run=True)
        self.authorize(directory)
        reporting.verify_publication(report, ROOT)
        self.assertEqual(publish_report(report, ROOT, dry_run=True)['branch'], 'results/legal-benchmark/' + bundle.name)
        # The same suite and settings under the current id are the same cohort: published results stay comparable.
        current = self.report(self.smoke(name='current'))
        self.assertEqual([p.name for p in (current / 'bundle/docs/results').iterdir()], [CURRENT])

        def cohorts(found):
            (summary,) = found.rglob('legal-summary.json')
            return sorted((c['arm'], c['cohort_sha256']) for c in read_json(summary)['cohorts'])
        self.assertEqual(cohorts(report), cohorts(current))
        self.assertEqual(len(cohorts(report)), 1)

    def test_a_run_whose_entry_and_job_carry_different_ids_is_refused(self):
        directory = self.smoke(name='mixed', reporting={'on_experiment_end': False})
        plan = read_json(directory / 'plan.json')
        plan['experiments'][0]['experiment_id'] = FORMER      # the entry alone: its job keeps the current id
        write_plan(directory, plan)
        experiment = self.experiment_dir(directory)
        write_json(experiment / 'experiment.json', {**read_json(experiment / 'experiment.json'), 'experiment_id': FORMER})
        with self.assertRaisesRegex(reporting.ProjectionRejected, '^not_reportable$'):
            reporting.project(directory, read_json(directory / 'plan.json'), read_json(directory / 'campaign.json'),
                              read_json(experiment / 'experiment.json'))
        # The call the publication gate makes to rebuild a bundle: no generic check stands in front of the projection there.
        with self.assertRaisesRegex(reporting.ProjectionRejected, '^not_reportable$'):
            projected_bundle(experiment, lambda *arguments: reporting.project(*arguments, create_salt=False))
        with self.assertRaisesRegex(ValueError, '^Experiment identity does not match its planned jobs$'):      # the generic check
            build_report(experiment)

    def test_an_attempt_that_wrote_the_other_id_is_refused(self):
        def projected(directory):
            return reporting.project(directory, read_json(directory / 'plan.json'), read_json(directory / 'campaign.json'),
                                     read_json(self.experiment_dir(directory) / 'experiment.json'))

        def rewrite(directory, experiment):
            metadata = self.attempt(directory) / 'metadata.json'
            write_json(metadata, {**read_json(metadata), 'experiment': experiment})
            self.rereceipt(directory)
        # Planned under the current id, the attempt names the former one.
        current = self.smoke(name='current-plan', reporting={'on_experiment_end': False})
        self.assertTrue(projected(current)['readme'].startswith('# legal-models results'))
        rewrite(current, FORMER)
        with self.assertRaisesRegex(reporting.ProjectionRejected, '^metadata$'):
            projected(current)
        # Stored as before the rename, reported and authorized; then the attempt names the current id.
        former, experiment = self.former_campaign('former-plan')
        report = build_report(experiment)
        self.authorize(former)
        reporting.verify_publication(report, ROOT)
        rewrite(former, CURRENT)
        with self.assertRaisesRegex(reporting.ProjectionRejected, '^metadata$'):
            projected(former)
        with self.assertRaisesRegex(ValueError, '^receipt_mismatch$'):
            reporting.verify_publication(report, ROOT)

    def test_the_worker_gate_applies_the_data_policy_to_a_job_of_the_former_id(self):
        for name, lock, allowed in (('declared', self.copy('declared'), False), ('approved', None, True)):
            parameters = {'synthetic': True, **({'suite': str(lock)} if lock else {'suite': str(SMOKE)})}
            (job,) = self.plan(name, parameters=parameters)['jobs']
            attempt = self.path / 'worker' / name
            attempt.mkdir(parents=True)
            atomic_json(attempt / 'job.json', {**job, 'experiment_id': FORMER})
            (attempt / 'f.jsonl').write_text('x', encoding='utf-8')
            with self.subTest(suite=name):
                if allowed:
                    files = worker.handle({'action': 'collect', 'output': str(attempt)})['files']
                    self.assertEqual(sorted(f['path'] for f in files), ['f.jsonl', 'job.json'])
                else:
                    with self.assertRaisesRegex(ValueError, 'Collection refused by data policy'):
                        worker.handle({'action': 'collect', 'output': str(attempt)})


def generation_attempt(directory, lock, experiment=FORMER):
    """One generation attempt of the arm `lexical-eligible`, written as the worker writes it and planned with the suite at
    `lock`. With the former id, the job and what the attempt writes (metadata, output manifest) carry that id, as an
    attempt made before the rename does."""
    suite = contracts.load_suite(lock)

    def respond(body):
        content = body['messages'][1]['content']
        matter = next(m for m in suite['matters']['matters'] if 'MATTER ' + m['matter_id'] + '\n' in content)
        output = fixture.draft(matter, suite['corpus'])
        listed = set(re.findall(r'^\[([a-z0-9-]+@[0-9]+)\] ', content, re.M))
        output['claims'] = [c for c in output['claims'] if c['authority_id'] + '@' + c['version'] in listed]
        return json.dumps(output)
    with FakeGenerator(respond=respond) as fake, patch.dict(legal.MANIFEST, {'id': experiment}):
        job = {**job_for(lock, {'arms': ['lexical-eligible'], 'roles': {'generator': generator(fake.endpoint)}}), 'experiment_id': experiment}
        result = execute(job, directory)
    if result['status'] != 'succeeded':
        raise AssertionError(result)
    return Path(directory)


class VanishedSuitePathTests(TempCase):
    """Attempts made before the rename name their suite by a path that no longer exists. A step that reads such an attempt
    takes the suite from its caller and binds it to the attempt by the lock digest."""

    def test_the_review_packet_and_a_score_job_read_an_attempt_of_before_the_rename(self):
        g, r = grading(), routing()
        shutil.copytree(SMOKE.parent, self.path / 'old-layout/original-smoke')
        attempt = generation_attempt(self.path / ('a' * 32), self.path / 'old-layout/original-smoke/suite.lock.json')
        shutil.rmtree(self.path / 'old-layout')      # as `experiments/legal-benchmark` after the rename
        manifest = attempt / 'local/output-manifest.json'
        self.assertEqual((read_json(attempt / 'job.json')['experiment_id'], read_json(attempt / 'metadata.json')['experiment'],
                          read_json(manifest)['experiment']), (FORMER, FORMER, FORMER))
        self.assertFalse(Path(read_json(attempt / 'job.json')['parameters']['suite']).exists())
        smoke = contracts.load_suite(SMOKE)      # the same suite at its current path: the same lock digest
        self.assertEqual(list(r.rows_by_candidate(attempt, suite=smoke)), ['lexical-eligible'])
        self.assertEqual(g.score_records({'output_manifest': str(manifest)}, smoke)[0]['experiment'], FORMER)
        review = self.path / 'review'
        with self.assertRaisesRegex(ValueError, 'Suite lock not found: name the suite the attempt ran on with --suite'):
            g.main(['packet', '--output-manifest', str(manifest), '--output', str(review)])
        with self.assertRaisesRegex(ValueError, 'Output manifest belongs to another suite'):
            g.main(['packet', '--output-manifest', str(manifest), '--output', str(review), '--suite', str(PACKETS)])
        self.assertFalse(review.exists())
        self.assertEqual(g.main(['packet', '--output-manifest', str(manifest), '--output', str(review), '--suite', str(SMOKE)]), 0)
        self.assertEqual(read_json(review / 'review-key.json')['output_manifest_sha256'], sha256_file(manifest))
        self.assertTrue((review / 'review-packet.json').is_file())
        # A score job of the current id grades the outputs of the former-id attempt.
        (job,) = self.plan('score', 'score', {'suite': str(SMOKE), 'output_manifest': str(manifest)})['jobs']
        scored = self.run_job(job, 'score')
        self.assertEqual((job['experiment_id'], read_json(scored / 'metadata.json')['experiment'], read_json(scored / 'result.json')['status']),
                         (CURRENT, CURRENT, 'succeeded'))

    def test_calibration_and_a_thresholded_plan_read_attempts_of_before_the_rename(self):
        r = routing()
        shutil.copytree(PACKETS.parent, self.path / 'old-layout/original-packets')
        routed, fallback = build_calibration_attempts(self.path / 'calibration', self.path / 'old-layout/original-packets/suite.lock.json')
        shutil.rmtree(self.path / 'old-layout')      # the path both attempts were planned with is gone
        packets = contracts.load_suite(PACKETS)
        with self.assertRaises(OSError):      # without a suite, only the planned path is known
            r.calibration_rows(routed, fallback, 'lexical-eligible')
        with self.assertRaisesRegex(ValueError, 'Output manifest belongs to another suite'):
            r.calibration_rows(routed, fallback, 'lexical-eligible', contracts.load_suite(SMOKE))
        rows = r.calibration_rows(routed, fallback, 'lexical-eligible', packets)
        self.assertEqual([x['task_id'] for x in rows], ['p1-quay-a', 'p1-quay-b', 'p2-kiln-a', 'p2-kiln-b'])
        record = r.calibrate(rows, [0.5, 0.9], packets, r.calibration_lineage(routed, fallback, 'lexical-eligible', packets))
        with patch('sys.stdout', io.StringIO()):      # the operator command, with the suite at its current path
            self.assertEqual(r.main(['calibrate', '--suite', str(PACKETS), '--routed-attempt', str(routed), '--fallback-attempt', str(fallback),
                                     '--fallback-arm', 'lexical-eligible', '--thresholds', '0.5,0.9', '--output', str(self.path / 'cli.json')]), 0)
        self.assertEqual(read_json(self.path / 'cli.json'), record)
        # A new case that pins this calibration plans: the record is recomputed from the two attempts through `packets`.
        write_json(self.path / 'calibration.json', record)
        block = {'calibration_file': str(self.path / 'calibration.json'), 'suite': str(PACKETS),
                 'routed': {'output_manifest': str(routed / 'local/output-manifest.json')},
                 'fallback': {'output_manifest': str(fallback / 'local/output-manifest.json')}}
        (job,) = self.plan('pinned', 'generation', {'suite': str(SMOKE), 'arms': ['no-context', 'lexical-eligible'],
                                                    'roles': {'generator': generator(), 'selector': selector_role()},
                                                    'selector': {**served(abstain_threshold=record['abstain_threshold']), 'calibration': block}})['jobs']
        self.assertEqual(job['experiment_id'], CURRENT)
        self.assertIn(str((routed / 'local/output-manifest.json').resolve()), {f['path'] for f in job['input_files']})


if __name__ == '__main__':
    unittest.main()
