import gzip
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from llm_eval.common import digest
from llm_eval.reporting.reproduction import result_inputs


class ResultInputTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        self.bundle = root / 'bundle'
        (self.bundle / 'raw').mkdir(parents=True)
        self.weights = root / 'weights'
        self.weights.mkdir()
        content = b'example weights'
        (self.weights / 'example.gguf').write_bytes(content)
        self.lock = {'source_revision': 'a' * 40, 'weight_bytes': len(content),
                     'files': [{'path': 'example.gguf', 'bytes': len(content),
                                'sha256': hashlib.sha256(content).hexdigest(), 'weight': True}]}
        self.manifest = {'publication_id': 'example', 'experiment_id': 'hardware-fit', 'code_revision': 'b' * 40}
        self.job = {'case_id': 'tested', 'job_id': 'selected', 'mode': 'measured', 'parameters': {},
                    'hardware_config_id': 'example-host', 'hardware': {'os_id': 'ubuntu-26.04-native'}}
        self.write_config()
        self.metadata = {'artifact': self.lock, 'artifact_sha256': digest(self.lock),
                         'category': 'math', 'suite_sha256': 'c' * 64}
        self.write_rows()

    def write_config(self):
        for filename, contents in [('manifest.json', self.manifest), ('resolved-config.json', {'jobs': [self.job]})]:
            (self.bundle / filename).write_text(json.dumps(contents), encoding='utf-8')

    def write_rows(self):
        with gzip.open(self.bundle / 'raw/measurements.jsonl.gz', 'wt', encoding='utf-8') as out:
            row = {'record_type': 'metadata', 'latest_attempt': True, 'job_id': 'selected', 'data': self.metadata}
            for record in (row, row, {**row, 'latest_attempt': False, 'data': {'artifact': {}}},
                           {**row, 'job_id': 'other', 'data': {'artifact': {}}}):
                out.write(json.dumps(record) + '\n')

    def test_latest_selected_job_verifies_bytes_and_unique_inputs(self):
        self.assertEqual(result_inputs(self.bundle)['jobs'][0]['job_id'], 'selected')
        recipe = result_inputs(self.bundle, 'selected', self.weights)
        self.assertEqual(recipe['verified_weight_bytes'], self.lock['weight_bytes'])
        self.assertEqual(recipe['artifact_locks'], [{'lock_sha256': digest(self.lock), 'lock': self.lock}])
        self.assertEqual(recipe['suite_hashes'], [{'category': 'math', 'sha256': 'c' * 64}])
        (self.weights / 'example.gguf').write_bytes(b'wrong')
        with self.assertRaisesRegex(ValueError, 'Artifact verification failed'):
            result_inputs(self.bundle, 'selected', self.weights)

    def test_unknown_job_and_untrustworthy_lock_fail(self):
        with self.assertRaisesRegex(ValueError, 'Unknown job'):
            result_inputs(self.bundle, 'different')
        self.metadata['artifact_sha256'] = 'd' * 64
        self.write_rows()
        with self.assertRaisesRegex(ValueError, 'digest'):
            result_inputs(self.bundle, 'selected')

    def test_legal_projection_never_uses_generic_raw_artifact(self):
        self.manifest['experiment_id'] = 'legal-benchmark'
        self.job['parameters'] = {'cohorts': ['public-cohort'], 'execution_kind': 'model-run'}
        self.write_config()
        (self.bundle / 'raw/measurements.jsonl.gz').unlink()
        recipe = result_inputs(self.bundle, 'selected')
        self.assertEqual(recipe['cohort_digests'], ['public-cohort'])
        self.assertNotIn('artifact_locks', recipe)
        with self.assertRaisesRegex(ValueError, 'legal projection'):
            result_inputs(self.bundle, 'selected', self.weights)
