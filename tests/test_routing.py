import json
from pathlib import Path
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch, Mock
from llm_eval.adapters import configured_endpoint
from llm_eval.common import digest, read_json, write_json
from llm_eval.experiments.decision_models.decision import decide
from llm_eval.experiments.decision_models.evaluation import execute, candidate_fingerprint

class RoutingTests(unittest.TestCase):
    def test_systemone_protocol_and_probabilities(self):
        seen=[]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*a):pass
            def do_POST(self):
                seen.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
                data=json.dumps({'answers':{'route':{'type':'choice','choice':'code','probabilities':{'code':.9,'general':.1}}}}).encode()
                self.send_response(200);self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        t=threading.Thread(target=server.serve_forever);t.start()
        try:
            result=decide({'kind':'systemone','model':'fixture','instructions':'Choose','criteria':{'code':'coding','general':'general'},
                           'endpoint':f'http://127.0.0.1:{server.server_port}/v1/systemone'},[{'role':'user','content':'write Python'}])
            self.assertEqual(result['choice'],'code');self.assertEqual(seen[0]['questions']['route']['type'],'choice')
        finally:server.shutdown();server.server_close();t.join()

    def test_replay_oracle_and_missing_coverage(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)
            suite={'tasks':[{'id':'a','messages':[{'role':'user','content':'question'}],'expected_choice':'small'}]}
            candidates={n:{'model':n,'model_revision':'r1','platform':'fixture'} for n in ['small','large']}
            corpus={'suite_sha256':digest(suite),'candidate_fingerprints':{k:candidate_fingerprint(v) for k,v in candidates.items()},
                    'rows':[{'task_id':'a','candidate':n,'quality':q,'cost_usd':0,'latency_s':1} for n,q in [('small',.5),('large',1)]]}
            write_json(p/'suite.json',suite);write_json(p/'corpus.json',corpus)
            job={'mode':'replay','parameters':{'suite':str(p/'suite.json'),'router':{'kind':'fixed','choice':'small'},'candidates':candidates,'replay':str(p/'corpus.json'),'synthetic':True}}
            execute(job,p/'out',p)
            row=json.loads((p/'out/requests.jsonl').read_text())
            self.assertEqual(row['oracle_regret'],.5)
            self.assertEqual(read_json(p/'out/routing-metadata.json')['baseline']['best_fixed_candidate'],'large')
            corpus['rows']=[];write_json(p/'corpus.json',corpus)
            execute(job,p/'missing',p)
            self.assertEqual(json.loads((p/'missing/requests.jsonl').read_text())['status'],'missing')

    def test_category_baseline_reads_prompt_not_ground_truth(self):
        self.assertEqual(decide({'kind':'category','default_category':'general','keywords':{'code':['python']}},
                                [{'role':'user','content':'Write Python'}])['choice'],'code')

    def test_hosted_budget_prevents_request(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp);write_json(p/'suite.json',{'tasks':[{'id':'a','messages':[{'role':'user','content':'q'}]}]})
            candidate={'model':'x','network':{'kind':'hosted'},'context_tokens':1000,'pricing':{'input_per_million':1000,'output_per_million':1000}}
            job={'mode':'live','parameters':{'suite':str(p/'suite.json'),'router':{'kind':'fixed','choice':'x'},'candidates':{'x':candidate},'budget_usd':.01}}
            with patch('llm_eval.experiments.decision_models.evaluation.HTTPAdapter') as adapter:
                execute(job,p/'out',p);adapter.assert_not_called()
            self.assertEqual(json.loads((p/'out/requests.jsonl').read_text())['status'],'budget_exhausted')

    def test_remote_network_requires_explicit_host_and_tls(self):
        with self.assertRaises(ValueError):configured_endpoint('https://api.example.com/v1')
        with self.assertRaises(ValueError):configured_endpoint('http://api.example.com/v1',{'kind':'hosted','allowed_hosts':['api.example.com']})
        self.assertEqual(configured_endpoint('https://api.example.com/v1',{'kind':'hosted','allowed_hosts':['api.example.com']}).hostname,'api.example.com')

    def test_live_fallback_retains_uncertain_cost_and_attempts(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp);write_json(p/'suite.json',{'tasks':[{'id':'a','messages':[{'role':'user','content':'q'}],
                                                          'check':{'type':'exact','expected':'yes'}}]})
            candidates={name:{'model':name,'network':{'kind':'hosted'},'context_tokens':1000,
                              'pricing':{'input_per_million':1000,'output_per_million':1000}} for name in ['small','large']}
            job={'mode':'live','parameters':{'suite':str(p/'suite.json'),'router':{'kind':'fixed','choice':'small'},
                                            'policy':{'fallback':'large'},'candidates':candidates,'budget_usd':3}}
            response={'text':'yes','elapsed_s':1,'prompt_tokens':10,'completion_tokens':5}
            adapters=[Mock(generate=Mock(side_effect=TimeoutError('fixture'))),Mock(generate=Mock(return_value=response))]
            with patch('llm_eval.experiments.decision_models.evaluation.HTTPAdapter',side_effect=adapters):
                execute(job,p/'out',p)
            row=json.loads((p/'out/requests.jsonl').read_text())
            self.assertEqual(row['status'],'ok');self.assertTrue(row['fallback_used'])
            self.assertTrue(row['quality_pass'])
            self.assertEqual(row['selected_model'],'large');self.assertEqual(len(row['generation_attempts']),2)
            self.assertAlmostEqual(read_json(p/'out/routing-metadata.json')['cost_charged_or_reserved_usd'],1.271)


class HeldOutStudyTests(unittest.TestCase):
    root = Path(__file__).resolve().parents[1]
    examples = root / 'experiments' / 'decision-models'

    def test_pooled_f1_counts_first_attempt_even_when_repeats_disagree(self):
        from llm_eval.experiments.decision_models.metrics import decision_report, report_supplement
        rows = [
            {'task_id': 'a', 'category': 'coding', 'expected_choice': 'coding', 'choice': 'coding',
             'probabilities': {'coding': .8, 'math': .2}},
            {'task_id': 'b', 'category': 'math', 'expected_choice': 'math', 'choice': 'coding',
             'probabilities': {'coding': .8, 'math': .2}},
            {'task_id': 'b', 'category': 'math', 'expected_choice': 'math', 'choice': 'math', 'repetition': 2},
        ]
        records = [{'job_id': 'job', 'record_type': 'request', 'latest_attempt': True,
                    'data': {'status': 'ok', 'router_s': .2, 'repetition': 1, **r}} for r in rows]
        records += [{**records[0], 'latest_attempt': False},
                    {**records[0], 'data': {**records[0]['data'], 'warmup': True, 'repetition': 0}}]
        report = decision_report(records)[0]
        self.assertEqual((report['unique_tasks'], report['measured_requests'], report['decision_accuracy']), (2, 3, .5))
        self.assertAlmostEqual(report['macro_f1'], 1 / 3)
        self.assertIn('decision-models-summary.json', report_supplement(records)[1])
        self.assertEqual(report_supplement([]), (None, ''))
        self.assertAlmostEqual(report['mean_multiclass_brier'], .68)
        self.assertEqual([r['recall'] for r in report['per_class']], [1, 0])
        self.assertEqual(report['reliability_bins'][8]['accuracy'], .5)
        self.assertEqual(report['timing_all_measured_repetitions']['router_s']['requests'], 3)
        self.assertEqual(report['threshold_sensitivity'][-1]['accepted_tasks'], 0)
        records[0]['data'].update(status='error', choice=None, probabilities=None)
        failed = decision_report(records)[0]
        self.assertEqual((failed['decision_accuracy'], failed['tasks_without_choice'], failed['probability_tasks']), (0, 1, 1))

    def test_abstained_choice_is_scored_separately_from_fallback_success(self):
        from llm_eval.experiments.decision_models.metrics import decision_metrics
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            write_json(path/'suite.json', {'tasks': [{'id': 't', 'expected_choice': 'math',
                       'messages': [{'role':'user','content':'2+2?'}], 'check': {'type':'exact','expected':'4'}}]})
            case = {'suite': str(path/'suite.json'), 'router': {'kind': 'systemone'},
                    'policy': {'category_models': {'math':'cheap','general':'cheap'}, 'abstain_threshold': .8, 'fallback': 'strong'},
                    'candidates': {c: {'model': c} for c in ('cheap','strong')}}
            decision = {'choice': 'math', 'probabilities': {'math': .6, 'general': .4}, 'router_s': .02}
            with patch('llm_eval.experiments.decision_models.evaluation.decide', return_value=decision), \
                 patch('llm_eval.experiments.decision_models.evaluation.HTTPAdapter') as adapter:
                adapter.return_value.generate.return_value={'text':'4','elapsed_s':1,'prompt_tokens':4,'completion_tokens':1}
                execute({'mode':'live','parameters':case}, path/'out', path)
            row = json.loads((path/'out/requests.jsonl').read_text())
            report = decision_metrics([row])
            self.assertEqual((row['selected_model'], report['abstentions'], report['fallback_answers_passed']), ('strong', 1, 1))
            self.assertEqual(report['decision_accuracy'], 1)
            self.assertEqual(report['accepted_share'], 0)
            self.assertIsNone(report['accepted_accuracy'])

    def test_split_selection_rejects_cross_partition_leaks_and_subset_ids(self):
        from copy import deepcopy
        from llm_eval.experiments.decision_models.workload import selected_tasks
        suite = read_json(self.examples / 'workloads/family-split.json')
        test = selected_tasks(suite, {'split': 'test'})
        self.assertEqual(len(test), 24)
        for field, message in [('family', 'family'), ('source', 'source'), ('messages', 'prompt')]:
            bad = deepcopy(suite)
            bad['tasks'][-1][field] = bad['tasks'][0][field]
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, message):
                selected_tasks(bad, {'split': 'test'})
        with self.assertRaisesRegex(ValueError, 'task_ids'):
            selected_tasks(suite, {'split': 'test', 'task_ids': [suite['tasks'][0]['id']]})
        with self.assertRaisesRegex(ValueError, 'Select'):
            selected_tasks(suite, {})

    def test_prepare_compiles_each_arm_and_keeps_original_criteria_order(self):
        from llm_eval.experiments.decision_models.protocol import prepare
        from llm_eval.orchestration.planner import compile_campaign
        with tempfile.TemporaryDirectory() as directory:
            for mode in ('decision', 'live', 'replay'):
                fixture = mode == 'replay'
                case = 'family-replay-fixture.json' if fixture else 'family-study.example.json'
                out = Path(directory) / mode
                prepare(self.examples / 'cases' / case, self.examples / 'workloads/keyword-router.json',
                        self.root / 'configs/targets/local.example.json', 'raider-ubuntu', mode, 'test', out,
                        self.examples / 'workloads/family-split.fixture-replay.json' if fixture else None)
                plan = compile_campaign(out / 'campaign.json', self.root)
                arms = {j['case_id']: j['parameters'] for j in plan['jobs']}
                if mode == 'decision':
                    self.assertEqual(list(arms['reversed-criteria']['router']['criteria']),
                                     list(reversed(arms['routed']['router']['criteria'])))
                else:
                    self.assertEqual(set(arms), {'routed', 'keyword', 'fixed-cheap', 'fixed-strong'})
                    self.assertNotIn('fallback', arms['fixed-cheap']['policy'])
                self.assertTrue(all(p['split'] == 'test' for p in arms.values()))

    def test_freeze_and_compare_require_matched_prompts_and_report_missing_cost(self):
        from copy import deepcopy
        from llm_eval.experiments.decision_models.protocol import compare, freeze
        names = ('cheap', 'strong')
        candidates = {name: {'model': name, 'model_revision': 'r1', 'platform': 'fixture'} for name in names}
        arms = {}
        for arm_name, choice in (('fixed-cheap', 'cheap'), ('fixed-strong', 'strong'), ('routed', 'strong'), ('keyword', 'cheap')):
            config = {'router': {'kind': 'fixed', 'choice': choice}, 'candidates': candidates, 'split': 'test'}
            tasks = {str(i): {'status': 'ok', 'selected_model': choice, 'prompt_sha256': str(i), 'task_family': str(i),
                              'quality_pass': i == 1 or choice == 'strong', 'elapsed_s': 2, 'generation_s': 1.5,
                              'cost_usd': 0, 'total_cost_usd': 0} for i in range(3)}
            arms[arm_name] = {'mode': 'live', 'hardware_config_id': 'fixture', 'config': config, 'synthetic': True,
                              'suite_sha256': 'suite', 'policy_sha256': 'policy', 'code_revision': 'rev', 'tasks': tasks}
        arms['fixed-cheap']['tasks']['0']['status'] = 'error'
        fixed = freeze(arms)
        self.assertEqual(len(fixed['rows']), 5)
        self.assertEqual(fixed['generation']['seed'], 1)
        self.assertTrue(fixed['synthetic'])
        replay = deepcopy(arms)
        for arm in replay.values():
            arm['mode'] = 'replay'
            for row in arm['tasks'].values():
                row.update(quality=row['quality_pass'], estimated_total_cost_usd=0, estimated_end_to_end_s=1.75)
        arms['routed']['tasks']['1']['total_cost_usd'] = None
        paired = compare(replay, arms)
        self.assertEqual(paired['coverage']['live/routed']['unknown_api_cost_tasks'], 1)
        self.assertEqual(paired['comparisons']['quality']['common_tasks'], 2)
        self.assertEqual(paired['comparisons']['api_usd']['common_tasks'], 1)
        self.assertEqual(paired['quality_resource_tradeoffs']['api_usd']['common_tasks'], 1)
        self.assertEqual(paired['comparisons']['end_to_end_s']['common_task_means']['replay/routed'], 1.75)
        arms['routed']['tasks']['1']['prompt_sha256'] = 'other'
        with self.assertRaisesRegex(ValueError, 'prompt hash'):
            compare(replay, arms)
        arms['routed']['config']['seed'] = 3
        with self.assertRaisesRegex(ValueError, 'settings differ'):
            compare(replay, arms)

    def test_incomplete_utilities_do_not_erase_other_common_tasks(self):
        from llm_eval.experiments.decision_models.evaluation import baseline_scores
        rows = {('a','x'): {'quality': 1}, ('b','x'): {'quality': None}, ('a','y'): {'quality': .7}, ('b','y'): {'quality': .1}}
        result = baseline_scores(rows, [{'id':'a'}, {'id':'b'}], ['x','y'], {})
        self.assertEqual((result['common_coverage_tasks'], result['best_fixed_candidate']), (1, 'x'))
        self.assertEqual(result['candidate_utility']['y'], .7)


class RenamedExperimentTests(unittest.TestCase):
    """The experiment was `llm-routing` until it became `decision-models`."""
    def test_the_former_id_resolves_to_the_plugin_but_is_not_listed(self):
        from llm_eval.experiments import canonical, get_experiment, list_experiments, plugin_hook, registered
        self.assertIs(get_experiment('llm-routing'),get_experiment('decision-models'))
        self.assertEqual((canonical('llm-routing'),canonical('decision-models'),canonical('model-offloading')),
                         ('decision-models','decision-models','model-offloading'))
        self.assertTrue(registered('llm-routing'));self.assertFalse(registered('no-such-experiment'))
        self.assertEqual(plugin_hook('llm-routing','MANIFEST')['id'],'decision-models')
        self.assertEqual([m['id'] for m in list_experiments()].count('decision-models'),1)
        self.assertNotIn('llm-routing',[m['id'] for m in list_experiments()])
        with self.assertRaisesRegex(ValueError,'Unknown experiment'):get_experiment('no-such-experiment')

    def test_a_campaign_must_name_the_current_id(self):
        from llm_eval.orchestration.planner import compile_campaign
        root=Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            campaign=read_json(root/'campaigns/routing-smoke.json')
            campaign['inventory']=str(root/'configs/targets/local.example.json')
            current=Path(tmp)/'current.json';write_json(current,campaign)
            plan=compile_campaign(current,root)
            self.assertEqual({j['experiment_id'] for j in plan['jobs']},{'decision-models'})
            self.assertTrue(all(j['job_id'].startswith('routing-decision-models-1-') for j in plan['jobs']))
            campaign['phases'][0]['experiments'][0]['id']='llm-routing'
            former=Path(tmp)/'former.json';write_json(former,campaign)
            with self.assertRaisesRegex(ValueError,'Experiment llm-routing was renamed decision-models: use the new id in the campaign'):
                compile_campaign(former,root)

if __name__=='__main__':unittest.main()
