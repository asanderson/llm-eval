import copy
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from llm_eval.common import read_json
from llm_eval.core.contracts import atomic_json
from llm_eval.core.hardware import limits
from llm_eval.orchestration.planner import revision
from llm_eval.orchestration.resources import reserve, release, ProcessLock
from llm_eval.orchestration.scheduler import initialize, run_campaign
from llm_eval.orchestration.transport import map_paths

ROOT=Path(__file__).resolve().parents[1]

class OrchestrationTests(unittest.TestCase):
    def plan(self,hosts):
        jobs=[]
        for i,host in enumerate(hosts):
            jobs.append({'job_id':str(i),'experiment_run_id':'run','experiment_id':'llm-routing','mode':'decision',
                         'parameters':{'synthetic':True},'target':{'transport':'local','physical_host_id':host},
                         'resources':[host],'status':'planned','reason':None,'depends_on':[]})
        return {'campaign_id':'test','root':str(ROOT),'code_revision':revision(ROOT),'inputs':{},
                'jobs':jobs,'experiments':[{'experiment_run_id':'run','experiment_id':'llm-routing','job_ids':[j['job_id'] for j in jobs]}],
                'execution':{'max_parallel_jobs':3,'on_failure':'continue-independent'},'reporting':{'on_experiment_end':False}}

    def test_parallel_hosts_and_serial_shared_host(self):
        for hosts,expected in [(['a','a'],1),(['a','b'],2)]:
            with self.subTest(hosts=hosts),tempfile.TemporaryDirectory() as temp:
                active=0;peak=0;mutex=threading.Lock()
                def rpc(target,payload,root,timeout=60):
                    nonlocal active,peak
                    if payload['action']=='run':
                        with mutex:active+=1;peak=max(peak,active)
                        time.sleep(.15)
                        with mutex:active-=1
                        return {'status':'succeeded'}
                    return {'ok':True}
                with patch('llm_eval.orchestration.resources.lock_root',return_value=Path(temp)/'locks'),patch('llm_eval.orchestration.transport.rpc',side_effect=rpc):
                    directory=initialize(self.plan(hosts),temp)
                    self.assertEqual(run_campaign(directory),0)
                    self.assertEqual(peak,expected)
                    self.assertEqual(run_campaign(directory),0)
                    self.assertTrue(all(len(r['attempts'])==1 for r in read_json(directory/'campaign.json')['jobs'].values()))

    def test_lost_worker_is_not_reexecuted(self):
        with tempfile.TemporaryDirectory() as temp:
            calls=[]
            def rpc(target,p,root,timeout=60):
                calls.append(p['action'])
                if p['action']=='run':raise ConnectionError('disconnected')
                if p['action']=='status':return {'result':None,'active':True}
                return {'ok':True}
            with patch('llm_eval.orchestration.resources.lock_root',return_value=Path(temp)/'locks'),patch('llm_eval.orchestration.transport.rpc',side_effect=rpc):
                directory=initialize(self.plan(['a']),temp)
                self.assertEqual(run_campaign(directory),1)
                self.assertEqual(run_campaign(directory),1)
                self.assertEqual(calls.count('run'),1)
                self.assertEqual(read_json(directory/'campaign.json')['jobs']['0']['status'],'lost')

    def test_failure_blocks_dependency(self):
        with tempfile.TemporaryDirectory() as temp:
            plan=self.plan(['a','b']);plan['jobs'][1]['depends_on']=['0']
            def rpc(target,p,root,timeout=60):return {'status':'failed'} if p['action']=='run' else {'ok':True}
            with patch('llm_eval.orchestration.resources.lock_root',return_value=Path(temp)/'locks'),patch('llm_eval.orchestration.transport.rpc',side_effect=rpc):
                directory=initialize(plan,temp);self.assertEqual(run_campaign(directory),1)
                self.assertEqual(read_json(directory/'campaign.json')['jobs']['1']['status'],'blocked')

    def test_reservations_require_owner_and_process_lock_recovers(self):
        with tempfile.TemporaryDirectory() as temp:
            reserve(temp,'gpu','one')
            with self.assertRaises(BlockingIOError):reserve(temp,'gpu','two')
            with self.assertRaises(ValueError):release(temp,'gpu','two')
            release(temp,'gpu','one');reserve(temp,'gpu','two')
            a=ProcessLock(Path(temp)/'controller');b=ProcessLock(Path(temp)/'controller')
            a.acquire()
            with self.assertRaises(BlockingIOError):b.acquire()
            a.close();b.acquire();b.close()

    def test_profile_limits_and_remote_paths(self):
        self.assertEqual(limits({'os_id':'windows-11-wsl2-ubuntu-26.04'},ROOT)['ram_budget_gib'],46)
        self.assertEqual(map_paths({'artifact':'/models/x','suite':'/repo/workloads/a'},
                                   {'repo_root':'D:/repo','path_mappings':{'/models':'E:/weights'}},'/repo'),
                         {'artifact':'E:/weights/x','suite':'D:/repo/workloads/a'})

if __name__=='__main__':unittest.main()
