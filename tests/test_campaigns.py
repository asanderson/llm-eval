import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from llm_eval.common import read_json, write_json
from llm_eval.core.contracts import REPLACE_ATTEMPTS, atomic_json, integer
from llm_eval.orchestration.planner import compile_campaign

ROOT = Path(__file__).resolve().parents[1]


class CampaignPlanningTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)
        write_json(self.path/'inventory.json', {
            'targets': {'local': {'transport': 'local', 'physical_host_id': 'raider'}},
            'hardware_configs': {'native': {'target':'local','hardware_profile':'msi-raider-18-hx-ai','os_id':'ubuntu-26.04-native'}}})
        for name in ('a','b'):
            write_json(self.path/(name+'.json'), {'id':name,'parameters':{'config':str(ROOT/'configs/runs/ollama.example.json')}})
        self.campaign = {'schema_version':2,'id':'test','inventory':'inventory.json','phases':[
            {'id':'first','experiments':[{'id':'model-offloading','version':1,'cases':['a.json','b.json'],'hardware_configs':['native']}]},
            {'id':'second','depends_on':['first'],'experiments':[{'id':'model-offloading','version':1,'cases':['a.json'],'hardware_configs':['native']}]}]}

    def compile(self):
        write_json(self.path/'campaign.json', self.campaign)
        return compile_campaign(self.path/'campaign.json',ROOT)

    def test_same_model_distinct_cases_and_dependencies(self):
        plan = self.compile()
        self.assertEqual(len(plan['jobs']),3)
        self.assertEqual(len({j['job_id'] for j in plan['jobs']}),3)
        self.assertEqual(plan['jobs'][2]['depends_on'],[j['job_id'] for j in plan['jobs'][:2]])
        self.assertEqual(plan,self.compile())
        self.assertTrue(Path(plan['jobs'][0]['parameters']['config']['suite']).is_absolute())
        self.assertFalse((self.path/'results').exists())

    def test_unknown_fields_and_cycles_fail(self):
        self.campaign['extra'] = True
        with self.assertRaisesRegex(ValueError,'Unknown fields'): self.compile()
        del self.campaign['extra']
        self.campaign['phases'][0]['depends_on']=['second']
        with self.assertRaisesRegex(ValueError,'earlier phases'): self.compile()

    def test_duplicate_case_and_secret_rejected(self):
        self.campaign['phases'][0]['experiments'][0]['cases']=['a.json','a.json']
        with self.assertRaisesRegex(ValueError,'Duplicate case'): self.compile()
        self.campaign['phases'][0]['experiments'][0]['cases']=['a.json']
        c=read_json(self.path/'a.json');c['parameters']['api_key']='secret'
        write_json(self.path/'a.json',c)
        with self.assertRaisesRegex(ValueError,'credential'): self.compile()

    def test_atomic_json_and_integer(self):
        path=self.path/'state.json';atomic_json(path,{'ok':1})
        self.assertEqual(read_json(path),{'ok':1})
        with self.assertRaises(ValueError): integer(True,'count')

    def test_atomic_json_retries_a_replace_that_a_windows_reader_blocks(self):
        directory=self.path/'beat';directory.mkdir();path=directory/'state.json'
        real=os.replace;calls=[]
        def blocked(source,target):
            calls.append(target)
            if len(calls)<3:raise PermissionError(13,'Access is denied')
            real(source,target)
        with patch('llm_eval.core.contracts.WINDOWS',True),patch('llm_eval.core.contracts.time.sleep') as sleep,patch('llm_eval.core.contracts.os.replace',side_effect=blocked):
            atomic_json(path,{'ok':2})
        self.assertEqual(read_json(path),{'ok':2})
        self.assertEqual((len(calls),sleep.call_count),(3,2))
        self.assertEqual([p.name for p in directory.iterdir()],['state.json'])      # no temporary file is left behind

    def test_a_replace_that_stays_refused_raises_and_leaves_no_temporary_file(self):
        directory=self.path/'beat';directory.mkdir()
        with patch('llm_eval.core.contracts.WINDOWS',True),patch('llm_eval.core.contracts.time.sleep'),patch('llm_eval.core.contracts.os.replace',side_effect=PermissionError(13,'Access is denied')) as replace:
            with self.assertRaises(PermissionError):atomic_json(directory/'state.json',{'ok':3})
        self.assertEqual(replace.call_count,REPLACE_ATTEMPTS)
        self.assertEqual(list(directory.iterdir()),[])

    def test_off_windows_a_refused_replace_raises_at_once(self):
        directory=self.path/'beat';directory.mkdir()
        with patch('llm_eval.core.contracts.WINDOWS',False),patch('llm_eval.core.contracts.os.replace',side_effect=PermissionError(13,'Permission denied')) as replace:
            with self.assertRaises(PermissionError):atomic_json(directory/'state.json',{'ok':4})
        self.assertEqual(replace.call_count,1)

if __name__ == '__main__': unittest.main()
