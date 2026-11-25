"""Matched offload protocol through the campaign planner, shared measurement runner and paired summaries."""
from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from llm_eval.common import read_json, sha256_file, write_json
from llm_eval.experiments import model_offloading as offload
from llm_eval.experiments.model_offloading import performance, quality
from llm_eval.livebench import question_manifest
from llm_eval.orchestration.planner import compile_campaign

ROOT = Path(__file__).resolve().parents[1]
CAMPAIGN = ROOT / 'experiments/model-offloading/matched/campaign.json'
WSL = 'windows-11-wsl2-ubuntu-26.04'
NATIVE = 'ubuntu-26.04-native'


class OffloadPerformance(unittest.TestCase):
    def test_plan_pins_workload_and_varies_only_layer_request(self):
        plan = compile_campaign(CAMPAIGN, ROOT)
        a, b = plan['jobs']
        self.assertEqual(a['mode'], 'matched-performance')
        self.assertEqual([a['status'], b['status']], ['planned', 'planned'])
        for job in (a, b):
            self.assertIn({'path': str(ROOT / performance.WORKLOAD), 'sha256': sha256_file(ROOT / performance.WORKLOAD)},
                          job['input_files'])
        configs = [deepcopy(j['parameters']['config']) for j in (a, b)]
        self.assertEqual([c['launch'].pop('gpu_layers') for c in configs], [20, 32])
        self.assertEqual(configs[0], configs[1])
        self.assertEqual((configs[0]['ram_budget_gib'], configs[0]['context_tokens']), (46, 16384))
        self.assertEqual(offload.input_files({}, ROOT, 'category-smoke'), [])

    def test_normal_runner_keeps_warmup_error_and_length_coverage_distinct(self):
        job = compile_campaign(CAMPAIGN, ROOT)['jobs'][0]
        case = job['parameters']
        case.update(server_mode='external', synthetic=True)
        case['config'].update(warmups=1, repeats=2)
        suite = read_json(ROOT / performance.WORKLOAD)
        task_counts = {t['messages'][0]['content']: (t['id'], 0) for t in suite['tasks']}

        def generate(_adapter, messages, max_tokens, seed, temperature):
            prompt = messages[0]['content']
            task, i = task_counts[prompt]
            task_counts[prompt] = (task, i+1)
            if task == 'short-input' and i == 2:
                raise TimeoutError('fixture')
            size = {'short-input': 25, 'long-input-4k': 4500, 'long-input-8k': None, 'sustained-output': 70}[task]
            tokens = (300 if i == 1 else 20) if task == 'sustained-output' else 2
            return {'text': 'visible', 'prompt_tokens': size, 'completion_tokens': tokens, 'elapsed_s': 1.0,
                    'first_visible_s': .2, 'first_output_s': .1, 'backend_decode_tps': 40 if i == 1 else 2,
                    'backend_prefill_tps': None, 'finish_reason': 'length' if i == 1 else None}

        with TemporaryDirectory() as temp, patch('llm_eval.runner.HTTPAdapter.generate', autospec=True, side_effect=generate):
            result = offload.execute(job, Path(temp), ROOT)
        self.assertEqual(result['status'], 'failed')
        summary = result['performance']
        self.assertTrue(summary['synthetic'])
        profiles = summary['workloads']
        self.assertEqual(profiles['short-input']['errors'], {'TimeoutError': 1})
        self.assertEqual(profiles['long-input-8k']['length_target']['unknown'], 2)
        self.assertEqual(profiles['long-input-4k']['length_target']['met'], 2)
        self.assertEqual(profiles['long-input-4k']['metrics']['backend_prefill_tps']['n'], 0)
        sustained = profiles['sustained-output']
        self.assertEqual((sustained['length_target']['met'], sustained['length_target']['below']), (1, 1))
        self.assertEqual(sustained['finish_reasons'], {'length': 1, 'unknown': 1})
        self.assertEqual(sustained['qualifying_metrics']['completion_tokens']['median'], 300)
        self.assertEqual(sustained['metrics']['completion_tokens']['median'], 160)
        self.assertEqual(len(sustained['warmup_client_wall_s']), 1)
        self.assertIsNone(summary['managed_backend_start_to_ready_s'])
        record = {'latest_attempt': True, 'record_type': 'metadata', 'source_file': 'result.json',
                  'attempt_id': 'fixture', 'data': result}
        data, markdown = offload.report_supplement([record, dict(record, latest_attempt=False)])
        self.assertEqual(len(data), 1)
        self.assertIn('long-input-8k | 0/2', markdown)
        self.assertEqual(offload.report_supplement([dict(record, data={})]), (None, ''))
        self.assertRaisesRegex(ValueError, 'real measurements', performance.compare, summary, summary, 'os')

    def test_swap_counters_host_scope_and_thermal_windows(self):
        def metadata(os_id, **attestation):
            return {'config': {'os_id': os_id, 'hardware_attestation': attestation}}
        partial = [{'swap_in_bytes': 0}, {'swap_in_bytes': 0}]
        idle = [dict(s, swap_out_bytes=0) for s in partial]
        moving = [idle[0], dict(idle[1], swap_out_bytes=100)]
        self.assertEqual(performance.swap_activity(partial), 'unknown')
        self.assertEqual(performance.swap_activity(idle[:1]), 'unknown')
        self.assertEqual(performance.swap_activity(idle), 'none_detected')
        self.assertEqual(performance.memory_summary(metadata(NATIVE), moving)['host_paging'], 'observed')
        self.assertEqual(performance.memory_summary(metadata('windows-11-native'), idle)['host_paging'], 'unknown')
        wsl = performance.memory_summary(metadata(WSL), moving)
        self.assertEqual((wsl['sampled_swap_activity'], wsl['host_paging']), ('observed', 'unknown'))
        self.assertEqual(performance.memory_summary(metadata(WSL, paging='none'), idle)['host_paging_source'],
                         'operator_attestation')
        samples = [{'monotonic_s': t, 'gpus': [{'index': '0', 'temperature_c': temp}, {'index': '1', 'temperature_c': 99}]}
                   for t, temp in ((0, 47), (60, 49), (895, 68), (900, 70))]
        thermal = performance.thermal_summary(samples, 0)
        self.assertEqual((thermal['sample_span_s'], thermal['first']['temperature_c']['median'],
                          thermal['last']['temperature_c']['median']), (900, 48, 69))
        self.assertEqual(thermal['last']['power_w']['n'], 0)

    def test_pairs_reject_confounders_and_keep_missing_metrics_null(self):
        task = {'id': 'sustained-output', 'messages': [{'role': 'user', 'content': 'x'}]}
        profile = performance.workload_summary(task, [{'task_id': task['id'], 'warmup': False, 'status': 'ok',
                                                     'completion_tokens': 55}], 1)
        left = {'schema_version': 1, 'benchmark': performance.BENCHMARK, 'synthetic': False,
                'controls': {'suite_sha256': 's', 'artifact_sha256': 'a', 'code_revision': 'c', 'physical_host_id': 'raider',
                             'config': {'ram_budget_gib': 46, 'platform': 'llama.cpp', 'hardware_profile': 'msi-raider-18-hx-ai'}},
                'launch': {'threads': 16, 'gpu_layers': 20}, 'os_id': NATIVE, 'job_id': 'a', 'status': 'completed',
                'workloads': {task['id']: profile}, 'placement_notes': '', 'memory': {}, 'worker_load_s': None,
                'managed_backend_start_to_ready_s': None, 'thermal': {}, 'hardware_attestation': {},
                'observed_placement': {'layers_offloaded': None, 'layers_total': None, 'model_loads': None}}
        right = deepcopy(left)
        right['launch']['gpu_layers'] = 32
        pair = performance.compare(left, right, 'gpu-layers')
        self.assertEqual(pair['layer_count_evidence'], 'requested_only')
        self.assertIsNone(pair['workloads']['sustained-output']['right_minus_left_median']['completion_tokens'])
        right['controls']['artifact_sha256'] = 'changed'
        self.assertRaisesRegex(ValueError, 'Mismatched controls', performance.compare, left, right, 'gpu-layers')
        right = deepcopy(left)
        right['os_id'] = WSL
        self.assertEqual(performance.compare(left, right, 'os')['axis'], 'os')
        for arm in (left, right):
            arm['observed_placement'].update(layers_offloaded=20, model_loads=1, layers_total=81)
        right['observed_placement']['layers_offloaded'] = 15
        self.assertRaisesRegex(ValueError, 'placement differs', performance.compare, left, right, 'os')
        right['observed_placement']['layers_offloaded'] = 20
        for arm in (left, right):
            arm['controls']['config']['ram_budget_gib'] = 52
        self.assertRaisesRegex(ValueError, '46 GiB', performance.compare, left, right, 'os')

    def test_quality_pair_rejoins_verified_items_and_rejects_missing_or_changed_coverage(self):
        with TemporaryDirectory() as temp:
            dirs = [Path(temp)/name for name in ('a', 'b')]
            for i, directory in enumerate(dirs):
                data = directory/'source/livebench/data'
                task = data/'live_bench/reasoning/example'
                task.mkdir(parents=True)
                question = {'category': 'reasoning', 'livebench_release_date': '2026-06-25'}
                (task/'question.jsonl').write_text('\n'.join(json.dumps(dict(question, question_id=n)) for n in (1,2)))
                judgment = task/'model_judgment/ground_truth_judgment.jsonl'
                judgment.parent.mkdir()
                judgment.write_text('\n'.join(json.dumps({'model': 'local', 'question_id': n, 'score': score})
                                              for n, score in ((1, i), (2, 1))))
                config = read_json(CAMPAIGN.parent/'run.json');config['launch']['gpu_layers'] = 20+i
                meta = {'status': 'completed', 'benchmark': 'livebench-upstream', 'question_snapshot':
                        question_manifest(data, ['reasoning'], '2026-06-25'), 'upstream_revision': 'rev', 'grader_image': 'img',
                        'artifact_sha256': 'lock', 'local_model_config': {'display_name': 'local'}, 'config': config}
                write_json(directory/'livebench-run.json', meta)
            pair = quality.compare(*dirs)
            self.assertEqual((pair['improved'], pair['tied'], pair['regressed']), (1,1,0))
            self.assertEqual(pair['supplied_task_coverage'], [{'category': 'reasoning', 'task': 'example', 'eligible': 2}])
            judgment.write_text('')
            self.assertRaisesRegex(ValueError, 'coverage', quality.compare, *dirs)


if __name__ == '__main__':
    unittest.main()
