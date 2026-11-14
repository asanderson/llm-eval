import copy
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from llm_eval.common import read_json
from llm_eval.core.contracts import atomic_json
from llm_eval.core.hardware import limits
from llm_eval.orchestration.planner import revision
from llm_eval.orchestration.resources import reserve, release, ProcessLock
from llm_eval.orchestration.scheduler import initialize, run_campaign
from llm_eval.orchestration.transport import map_paths, collect

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
                active=0;peak=0;mutex=threading.Lock();overlapped=threading.Event()
                # Jobs on separate hosts must overlap however long the scheduler takes to
                # submit the second one (its campaign/job writes are slow on Windows
                # runners), so hold each run until a second run arrives. A shared host
                # must never overlap; a short hold there gives a wrong scheduler the chance.
                hold=30 if expected==2 else .15
                def rpc(target,payload,root,timeout=60):
                    nonlocal active,peak
                    if payload['action']=='run':
                        with mutex:
                            active+=1;peak=max(peak,active)
                            if active>=2:overlapped.set()
                        overlapped.wait(hold)
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

    def test_coordinator_reservation_follows_a_local_targets_lock_root(self):
        from llm_eval.orchestration import scheduler
        from llm_eval.orchestration.resources import coordinator_root, lock_root
        with tempfile.TemporaryDirectory() as temp:
            target={'transport':'local','physical_host_id':'host','lock_root':str(Path(temp)/'shared')}
            job={'job_id':'0','target':target,'resources':['host']};plan={'root':str(ROOT),'jobs':[job]};calls=[]
            def rpc(target,p,root,timeout=60):calls.append(p['action']);return {'ok':True}
            # Two accounts or environments of one machine (native Windows and WSL) whose inventories name one shared directory.
            with patch('llm_eval.orchestration.transport.rpc',side_effect=rpc):
                with patch.object(Path,'home',return_value=Path(temp)/'home-a'):
                    scheduler._reserve(job,{'attempt_id':'one'},plan)
                with patch.object(Path,'home',return_value=Path(temp)/'home-b'):
                    with self.assertRaisesRegex(BlockingIOError,'Resource reserved'):
                        scheduler._reserve(job,{'attempt_id':'two'},plan)
                    self.assertEqual(calls,['reserve'])      # the second coordinator is refused before it asks the worker
                    scheduler._release(job,{'attempt_id':'one'},plan)
                    scheduler._reserve(job,{'attempt_id':'two'},plan)
            self.assertFalse((Path(temp)/'home-a').exists() or (Path(temp)/'home-b').exists())
            with patch.object(Path,'home',return_value=Path(temp)/'home-a'):
                default=lock_root()/'coordinator'
                self.assertEqual(default,Path(temp)/'home-a/.cache/llm-eval/locks/coordinator')
                self.assertEqual(coordinator_root(target),Path(temp)/'shared/coordinator')
                self.assertEqual(coordinator_root({'transport':'local','physical_host_id':'host'}),default)
                # A remote target's lock_root is a path on the remote host: the coordinator keeps its own directory.
                self.assertEqual(coordinator_root({'transport':'ssh','physical_host_id':'host','lock_root':'/remote/locks'}),default)

    def test_profile_limits_and_remote_paths(self):
        self.assertEqual(limits({'os_id':'windows-11-wsl2-ubuntu-26.04'},ROOT)['ram_budget_gib'],46)
        self.assertEqual(map_paths({'artifact':'/models/x','suite':'/repo/workloads/a'},
                                   {'repo_root':'D:/repo','path_mappings':{'/models':'E:/weights'}},'/repo'),
                         {'artifact':'E:/weights/x','suite':'D:/repo/workloads/a'})

    def test_lost_reservation_intent_recovers_without_duplicate_run(self):
        with tempfile.TemporaryDirectory() as temp:
            connected=False;owners=[];runs=[]
            def rpc(target,p,root,timeout=60):
                if p['action']=='reserve':owners.append(p['owner'])
                if not connected:raise ConnectionError('reply lost after reservation')
                if p['action']=='run':runs.append(p['owner']);return {'status':'succeeded'}
                return {'ok':True}
            with patch('llm_eval.orchestration.resources.lock_root',return_value=Path(temp)/'locks'),patch('llm_eval.orchestration.transport.rpc',side_effect=rpc):
                directory=initialize(self.plan(['a']),temp)
                self.assertEqual(run_campaign(directory),1)
                record=read_json(directory/'campaign.json')['jobs']['0']
                self.assertEqual(record['status'],'lost')
                self.assertEqual(record['attempts'][0]['attempt_id'],owners[0])
                self.assertEqual(record['attempts'][0]['stage'],'reserving')
                connected=True
                self.assertEqual(run_campaign(directory),0)
                self.assertEqual(len(runs),1)
                self.assertNotEqual(runs[0],owners[0])

    def test_chunked_artifact_collection_checks_hashes_and_resumes(self):
        from llm_eval.orchestration.worker import handle
        with tempfile.TemporaryDirectory() as temp:
            source=Path(temp)/'source';destination=Path(temp)/'destination';source.mkdir()
            data=b'x'*(5*1024*1024)+b'end';(source/'large.bin').write_bytes(data)
            (source/'empty.jsonl').touch();calls=[]
            def rpc(target,p,root,timeout=60):calls.append(p['action']);return handle(p)
            with patch('llm_eval.orchestration.transport.rpc',side_effect=rpc):
                collect({},source,ROOT,destination)
                self.assertEqual((destination/'large.bin').read_bytes(),data)
                self.assertEqual(calls.count('file-chunk'),2)
                calls.clear();collect({},source,ROOT,destination)
                self.assertEqual(calls,['collect'])
                with self.assertRaisesRegex(ValueError,'cap'):
                    collect({'max_collection_bytes':1},source,ROOT,destination)
                with self.assertRaisesRegex(ValueError,'Unsafe'):
                    handle({'action':'file-chunk','output':str(source),'path':'../outside','offset':0})

    def test_resume_enables_boot_target_without_changing_plan(self):
        with tempfile.TemporaryDirectory() as temp:
            plan=self.plan(['a']);job=plan['jobs'][0];job['target_id']='native'
            job['target']['available']=False;job['status']='blocked'
            plan['targets']={'native':job['target']}
            with patch('llm_eval.orchestration.resources.lock_root',return_value=Path(temp)/'locks'),patch('llm_eval.orchestration.transport.rpc',return_value={'status':'succeeded'}):
                directory=initialize(plan,temp)
                self.assertEqual(run_campaign(directory),1)
                self.assertEqual(run_campaign(directory,enable_targets=['native']),0)
                self.assertEqual(read_json(directory/'plan.json'),plan)

    def test_missing_supervision_dependency_fails_before_child_start(self):
        import sys
        from llm_eval.orchestration.worker import handle
        with tempfile.TemporaryDirectory() as temp,patch.dict(sys.modules,{'psutil':None}),patch('subprocess.Popen') as child:
            with self.assertRaises(ImportError):handle({'action':'run','output':temp})
            child.assert_not_called();self.assertFalse((Path(temp)/'active').exists())

if __name__=='__main__':unittest.main()
