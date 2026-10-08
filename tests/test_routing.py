import json
from pathlib import Path
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch, Mock
from llm_eval.adapters import configured_endpoint
from llm_eval.common import digest, read_json, write_json
from llm_eval.experiments.llm_routing.decision import decide
from llm_eval.experiments.llm_routing.evaluation import execute, candidate_fingerprint

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
            with patch('llm_eval.experiments.llm_routing.evaluation.HTTPAdapter') as adapter:
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
            with patch('llm_eval.experiments.llm_routing.evaluation.HTTPAdapter',side_effect=adapters):
                execute(job,p/'out',p)
            row=json.loads((p/'out/requests.jsonl').read_text())
            self.assertEqual(row['status'],'ok');self.assertTrue(row['fallback_used'])
            self.assertTrue(row['quality_pass'])
            self.assertEqual(row['selected_model'],'large');self.assertEqual(len(row['generation_attempts']),2)
            self.assertAlmostEqual(read_json(p/'out/routing-metadata.json')['cost_charged_or_reserved_usd'],1.271)

if __name__=='__main__':unittest.main()
