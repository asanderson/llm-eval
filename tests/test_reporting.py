import copy
import gzip
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from llm_eval.common import read_json, write_json
from llm_eval.orchestration.scheduler import initialize
from llm_eval.orchestration.planner import revision
from llm_eval.reporting.experiment import build_report, summaries
from llm_eval.reporting.publish import publish_report, validate_bundle, git as real_git

ROOT=Path(__file__).resolve().parents[1]

class FakeGitHub:
    def __init__(self):self.pr=None;self.created=0;self.fail=False
    def find(self,branch):return self.pr
    def request(self,method,path,body):
        if self.fail:self.fail=False;raise ConnectionError('fixture failure after push')
        if method=='POST':self.created+=1
        self.pr={'state':'open','number':1,'html_url':'https://github.com/asanderson/llm-eval/pull/fixture','body':body['body']}
        return self.pr

class ReportingTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        job={'job_id':'job','experiment_id':'llm-routing','experiment_run_id':'routing','case_id':'fixed','mode':'decision',
             'hardware_config_id':'fixture','hardware':{'os_id':'fixture'},'parameters':{'synthetic':True,'router':{'kind':'fixed'}},'status':'planned','reason':None}
        plan={'campaign_id':'fixture','root':str(ROOT),'code_revision':revision(ROOT),'inputs':{},'jobs':[job],
              'experiments':[{'experiment_id':'llm-routing','experiment_run_id':'routing','job_ids':['job']}],
              'reporting':{'on_experiment_end':True}}
        self.campaign=initialize(plan,self.root);state=read_json(self.campaign/'campaign.json')
        rel='experiments/routing/jobs/job/attempt';out=self.campaign/rel;out.mkdir(parents=True)
        rows=[{'category':'math','benchmark':'fixture','status':'ok','warmup':False,'synthetic':True,'expected_choice':'math','choice':'math','decision_correct':True,'elapsed_s':2,'output':'private text'},
              {'category':'math','benchmark':'fixture','status':'error','warmup':False,'synthetic':True,'expected_choice':'math','elapsed_s':4},
              {'category':'math','benchmark':'fixture','status':'ok','warmup':True,'synthetic':True,'elapsed_s':999}]
        (out/'requests.jsonl').write_text('\n'.join(json.dumps(r) for r in rows)+'\n')
        write_json(out/'job.json',job);write_json(out/'metadata.json',{'api_key':'not-a-real-secret','endpoint':'http://private.example','config':{'model':'fixture'}})
        (out/'reports').mkdir();(out/'reports/scores.csv').write_text('release,score\nfixture-release,0\n')
        state['jobs']['job']={'status':'failed','attempts':[{'attempt_id':'attempt','output':rel,'status':'failed'}]};state['status']='incomplete'
        write_json(self.campaign/'campaign.json',state)
        self.experiment=self.campaign/'experiments/routing'
        self.report=build_report(self.experiment)

    def test_raw_summary_and_deterministic_export(self):
        spec,manifest,size=validate_bundle(self.report);dest=self.report/'bundle'/spec['report_path']
        rows=read_json(dest/'summary.json');self.assertEqual(rows[0]['requests'],2)
        self.assertEqual(rows[0]['decision_accuracy'],.5);self.assertEqual(rows[0]['elapsed_s_median'],2)
        raw=gzip.decompress((dest/'raw/measurements.jsonl.gz').read_bytes()).decode()
        self.assertNotIn('private text',raw);self.assertNotIn('not-a-real-secret',raw);self.assertNotIn('private.example',raw)
        self.assertEqual(manifest['status'],'incomplete')
        self.assertEqual(read_json(dest/'benchmark-summary.json')[0]['data']['score'],'0')
        fingerprint=spec['report_fingerprint'];build_report(self.experiment)
        self.assertEqual(validate_bundle(self.report)[0]['report_fingerprint'],fingerprint)

    def test_size_tamper_and_dry_run(self):
        self.assertTrue(publish_report(self.report,ROOT,dry_run=True)['dry_run'])
        spec=read_json(self.report/'publication.json');spec['max_artifact_bytes']=1;write_json(self.report/'publication.json',spec)
        with self.assertRaisesRegex(ValueError,'size'):validate_bundle(self.report)
        spec['max_artifact_bytes']=10000000;write_json(self.report/'publication.json',spec)
        (self.report/'bundle'/spec['report_path']/'summary.csv').write_text('tampered')
        with self.assertRaisesRegex(ValueError,'integrity'):validate_bundle(self.report)

    def test_push_failure_recovery_and_existing_pr_reuse(self):
        bare=self.root/'remote.git';repo=self.root/'repo'
        def run(*args):subprocess.run(args,check=True,capture_output=True)
        run('git','init','--bare',str(bare));run('git','init','-b','main',str(repo))
        (repo/'README.md').write_text('# Test repository\n')
        run('git','-C',str(repo),'add','README.md');run('git','-C',str(repo),'-c','user.name=Fixture','-c','user.email=fixture@example.com','commit','-m','initial')
        run('git','-C',str(repo),'remote','add','origin',str(bare));run('git','-C',str(repo),'push','-u','origin','main')
        api=FakeGitHub();api.fail=True
        def fixture_git(root,*args,**kwargs):
            if args==('remote','get-url','origin'):return 'https://github.com/asanderson/llm-eval.git'
            return real_git(root,*args,**kwargs)
        with patch('llm_eval.reporting.publish.git',side_effect=fixture_git),patch.dict(os.environ,{'GH_TOKEN':'','GITHUB_TOKEN':''}):
            with self.assertRaises(ConnectionError):publish_report(self.report,repo,api=api)
            first=publish_report(self.report,repo,api=api)
            second=publish_report(self.report,repo,api=api)
        self.assertEqual(api.created,1);self.assertEqual(first['commit'],second['commit'])
        self.assertEqual(real_git(repo,'status','--porcelain'),'')
        self.assertTrue(read_json(self.report/'publication.json')['draft'])

    def test_real_local_worker_finishes_and_generates_report(self):
        from llm_eval.orchestration.planner import compile_campaign
        from llm_eval.orchestration.scheduler import run_campaign
        inventory=read_json(ROOT/'configs/targets/local.example.json')
        inventory['targets']['raider']['lock_root']=str(self.root/'worker-locks')
        write_json(self.root/'inventory.json',inventory)
        campaign=read_json(ROOT/'campaigns/routing-smoke.json');campaign['inventory']='inventory.json'
        write_json(self.root/'campaign.json',campaign)
        plan=compile_campaign(self.root/'campaign.json',ROOT)
        with patch('llm_eval.orchestration.resources.lock_root',return_value=self.root/'coordinator-locks'):
            directory=initialize(plan,self.root/'real-worker')
            self.assertEqual(run_campaign(directory),0)
            self.assertEqual(run_campaign(directory),0)
        state=read_json(directory/'campaign.json')
        self.assertEqual(state['status'],'succeeded')
        self.assertEqual(len(next(iter(state['jobs'].values()))['attempts']),1)
        receipt=next(iter(state['reports'].values()))
        self.assertEqual(receipt['status'],'generated')
        self.assertEqual(validate_bundle(directory/receipt['report'])[1]['status'],'complete')

if __name__=='__main__':unittest.main()
