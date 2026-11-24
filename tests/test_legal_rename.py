"""The legal experiment was `legal-benchmark` until 2026-11-23, when it became `legal-models`. Attempts, manifests, reports
and published bundles of that time carry the former id: the plugin must still read them as its own, still claim content
that carries the former id, and keep cohort digests comparable across the rename."""
import tempfile
import unittest
from pathlib import Path

from llm_eval.common import read_json, write_json
from llm_eval.experiments import RENAMED, canonical, get_experiment, list_experiments, plugin_hook
from llm_eval.experiments.legal_models import contracts, reporting

ROOT = Path(__file__).resolve().parents[1]


class LegalModelsRenameTests(unittest.TestCase):
    def test_the_former_id_resolves_to_the_plugin_but_is_not_listed(self):
        self.assertEqual(RENAMED['legal-benchmark'], 'legal-models')
        self.assertIs(get_experiment('legal-benchmark'), get_experiment('legal-models'))
        self.assertEqual((canonical('legal-benchmark'), get_experiment('legal-models').MANIFEST['id']), ('legal-models', 'legal-models'))
        self.assertIs(plugin_hook('legal-benchmark', 'verify_publication'), plugin_hook('legal-models', 'verify_publication'))
        self.assertNotIn('legal-benchmark', [m['id'] for m in list_experiments()])
        self.assertEqual((contracts.EXPERIMENT_ID, contracts.EXPERIMENT_IDS), ('legal-models', ('legal-models', 'legal-benchmark')))

    def test_a_campaign_must_name_the_current_id(self):
        from llm_eval.orchestration.planner import compile_campaign
        with tempfile.TemporaryDirectory() as tmp:
            campaign = read_json(ROOT / 'campaigns/legal-smoke.json')
            campaign['inventory'] = str(ROOT / 'configs/targets/local.example.json')
            current = Path(tmp) / 'current.json'
            write_json(current, campaign)
            plan = compile_campaign(current, ROOT)
            self.assertEqual({j['experiment_id'] for j in plan['jobs']}, {'legal-models'})
            self.assertTrue(all(j['job_id'].startswith('legal-legal-models-1-') for j in plan['jobs']))
            campaign['phases'][0]['experiments'][0]['id'] = 'legal-benchmark'
            former = Path(tmp) / 'former.json'
            write_json(former, campaign)
            with self.assertRaisesRegex(ValueError, 'Experiment legal-benchmark was renamed legal-models: use the new id in the campaign'):
                compile_campaign(former, ROOT)

    def test_cohort_digests_do_not_change_with_the_rename(self):
        job = {'mode': 'generation', 'hardware': {'os_id': 'windows-11-native', 'hardware_profile': 'msi-raider-18-hx-ai'}}
        metadata = {'experiment': 'legal-models', 'execution_kind': 'model-run', 'data_class': 'public-synthetic',
                    'benchmark_id': 'legal-original-smoke', 'suite_lock_sha256': 'a' * 64,
                    'roles': {'generator': {'profile_sha256': 'b' * 64, 'model': 'm', 'model_revision': 'r'}}}
        current, former = reporting.cohort(job, metadata, 'direct'), reporting.cohort(job, {**metadata, 'experiment': 'legal-benchmark'}, 'direct')
        self.assertEqual(current, former)      # the same settings before and after the rename are one cohort
        self.assertEqual(current[0]['experiment'], 'legal-benchmark')
        self.assertNotEqual(reporting.cohort(job, {**metadata, 'experiment': 'model-offloading'}, 'direct')[1], current[1])

    def test_a_report_is_headed_with_the_id_its_campaign_was_planned_with(self):
        generic = {'campaign_id': 'fixture', 'experiment_run_id': 'legal-run', 'code_revision': 'a' * 40}
        manifest = {'execution_kinds': ['fixture'], 'data_class': 'public-synthetic', 'cohorts': 0}
        former = reporting._readme(generic, manifest, [], [], [], [], False, 'legal-benchmark')
        current = reporting._readme(generic, manifest, [], [], [], [], False, 'legal-models')
        self.assertEqual(former.splitlines()[0], '# legal-benchmark results')      # as before the rename
        self.assertEqual(current.splitlines()[0], '# legal-models results')
        self.assertEqual(former.replace('legal-benchmark', 'legal-models'), current)      # nothing else differs

    def test_the_former_id_stays_a_mark_of_legal_content(self):
        markers = reporting._text_markers(reporting._markers())
        self.assertIn('legal-models', markers)
        self.assertIn('legal-benchmark', markers)      # a generic bundle carrying the former id is still refused


if __name__ == '__main__':
    unittest.main()
