"""Locked serving profiles, the approved-suites export gate, bounded routing between retrieval recipes, the routing suite
export and its replay manifest, and readiness for CPU-only legal jobs.

Every record, matter and suite used here is original and fictional. Nothing runs a model, a GPU or a serving harness: the
model-offloading attempts that `profiles.freeze` reads are hand-built fixtures in a temporary directory, the generator
and the SystemOne-shaped selector are scripted loopback servers on an ephemeral port, and every threshold comes from
fixture rows. None of the numbers here is a measurement.
"""
import copy
from fractions import Fraction
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
from pathlib import Path
import re
import shutil
import tempfile
import threading
import unittest
from unittest.mock import patch

from llm_eval.common import digest, read_json, sha256_file, write_json
from llm_eval.core.contracts import atomic_json
from llm_eval.experiments import get_experiment
from llm_eval.experiments import legal_benchmark as legal
from llm_eval.experiments.legal_benchmark import contracts, fixture, profiles, retrieval
from llm_eval.orchestration.planner import compile_campaign
from llm_eval.orchestration.scheduler import initialize, run_campaign

try:      # `unittest discover -s tests` puts tests/ on the path; a dotted module name imports through the namespace package
    from test_legal_workflow import ANALYSIS, FakeGenerator, generator, job_for, lines, subset_suite
except ImportError:
    from tests.test_legal_workflow import ANALYSIS, FakeGenerator, generator, job_for, lines, subset_suite

ROOT = Path(__file__).resolve().parents[1]
X = ROOT / 'experiments/legal-benchmark'
SMOKE = X / 'workloads/original-smoke/suite.lock.json'
PACKETS = X / 'workloads/original-packets/suite.lock.json'
EXAMPLES = ROOT / 'configs/examples/legal'
NO_GPU = patch('llm_eval.telemetry.gpu_snapshot', return_value=[])
HOST = 'legal-test-host'
CAMPAIGN_DIR = 'campaign-20261111T000000Z-0a1b2c3d'
JOB_ID = 'offload-model-offloading-1-0123456789ab'
ATTEMPT_ID = '0123456789abcdef0123456789abcdef'
MEASUREMENT = '20261111T000000Z-0a1b2c3d'
# `common.digest` of the shipped legal-shaped workload as `runner.load_suite` reads it: what a real offload measurement
# records as `suite_sha256`, and the only workload digests a profile binds with (exports of approved suites).
WORKLOAD_SHA256 = digest(json.loads((X / 'workloads/qualification/legal-shaped.json').read_text(encoding='utf-8')))


def routing():
    from llm_eval.experiments.legal_benchmark import routing as module
    return module


def grading():
    from llm_eval.experiments.legal_benchmark import grading as module
    return module


def workflow():
    from llm_eval.experiments.legal_benchmark import workflow as module
    return module


# Offload attempt fixtures ---------------------------------------------------------------------------------------------

def offload_metadata(**changes):
    """metadata.json of one measurement of a model-offloading attempt, in the shape `runner.run` writes. A fixture: the
    numbers are placeholders, not measurements."""
    value = {
        'schema_version': 1, 'harness_version': '0.3.0', 'synthetic': False, 'created_utc': '20261111T000000Z', 'status': 'completed',
        'config': {'platform': 'lmstudio', 'backend_version': '0.4.28+2', 'chat_template_sha256': '3' * 64, 'tokenizer_revision': 'tok-rev-1',
                   'placement_notes': 'Requested twenty layers; the actual placement is in C:\\models\\backend.log',
                   'hardware_attestation': {'os_build': '26100.4061', 'nvidia_driver': '610.74', 'paging': 'none',
                                            'model_path': 'C:\\models\\fixture.gguf', 'bios': 'Fixture BIOS sentence with spaces'},
                   'launch': {'gpu_layers': 20, 'threads': 8}, 'context_tokens': 4096, 'max_output_tokens': 1024,
                   'endpoint': 'http://127.0.0.1:1234/v1/chat/completions', 'backend_pid': 4242, 'os_id': 'windows-11-native'},
        'hardware_profile': read_json(ROOT / 'configs/hardware/msi-raider-18-hx-ai.json'),
        'host': {'node': 'fixture-host-name', 'environment_kind': 'windows-11-native'},
        'artifact': {'source_revision': '4' * 40, 'precision': 'Q8_0', 'files': [{'path': 'C:/models/fixture.gguf', 'sha256': '7' * 64}]},
        'artifact_sha256': '5' * 64,
        'telemetry': {'samples': 9, 'system_used_gib_peak': 41.2, 'swap_used_gib_peak': 0.0, 'backend_tree_rss_gib_peak': None,
                      'gpu_used_mib_peak': 12019},
        'memory_assessment': {'paging_observed': False, 'scope': 'system-wide counters'},
        'suite_sha256': WORKLOAD_SHA256, 'benchmark': 'legal-shaped', 'category': 'legal', 'measured_requests': 3}
    for key, item in changes.items():
        if item is None:
            value.pop(key, None)
        else:
            value[key] = item
    return value


def offload_rows(errors=0, finish='stop'):
    rows = [{'task_id': 'f1-ledger-a', 'warmup': True, 'repetition': 0, 'status': 'ok', 'output_tokens_per_wall_second': 99.0,
             'elapsed_s': 99.0, 'first_output_s': 99.0, 'finish_reason': finish}]
    for i, (tps, elapsed, first) in enumerate(((6.0, 7.5, 0.8), (7.0, 8.0, 1.0), (6.4, 7.75, 0.9))):
        status = 'error' if i < errors else 'ok'
        rows.append({'task_id': 'f1-ledger-a', 'warmup': False, 'repetition': i + 1, 'status': status, 'output_tokens_per_wall_second': tps,
                     'elapsed_s': elapsed, 'first_output_s': first, 'finish_reason': finish})
    return rows


def offload_attempt(root, *, synthetic=False, status='succeeded', measurements=(MEASUREMENT,), metadata=None, rows=None, host=None,
                    experiment='model-offloading', os_id='windows-11-native', telemetry=None, physical_host=HOST, result_status=None):
    """A campaign directory with one model-offloading job and one attempt, built by hand from dict fixtures; `plan_sha256` is
    the planner's digest of the plan."""
    campaign = Path(root) / CAMPAIGN_DIR
    rel = f'experiments/offload-model-offloading-1/jobs/{JOB_ID}/{ATTEMPT_ID}'
    job = {'schema_version': 2, 'job_id': JOB_ID, 'experiment_run_id': 'offload-model-offloading-1', 'experiment_id': experiment,
           'mode': 'category-smoke', 'case_id': 'legal-offload', 'hardware_config_id': 'native',
           'hardware': {'target': 'local', 'hardware_profile': 'msi-raider-18-hx-ai', 'os_id': os_id},
           'target': {'transport': 'local', 'physical_host_id': physical_host}, 'resources': [physical_host],
           'parameters': {'config': {'platform': 'lmstudio'}, 'server_mode': 'external', **({'synthetic': True} if synthetic else {})},
           'input_files': []}
    plan = {'schema_version': 2, 'campaign_id': 'offload-qualification', 'code_revision': '1' * 40, 'jobs': [job], 'root': '/fixture/root'}
    write_json(campaign / 'plan.json', {**plan, 'plan_sha256': digest(plan)})
    write_json(campaign / 'campaign.json', {'schema_version': 2, 'campaign_id': 'offload-qualification', 'status': 'succeeded', 'jobs': {
        JOB_ID: {'status': status, 'attempts': [{'attempt_id': ATTEMPT_ID, 'status': status, 'output': rel, 'worker_output': str(campaign / rel)}]}}})
    attempt = campaign / rel
    write_json(attempt / 'job.json', job)
    write_json(attempt / 'host.json', host if host is not None else {
        'node': 'fixture-host-name', 'environment_kind': os_id, 'ram_total_gib': 63.5,
        'gpus': [{'name': 'NVIDIA GeForce RTX 5090 Laptop GPU', 'driver_version': '610.74', 'total_mib': 24463}]})
    write_json(attempt / 'result.json', {'status': result_status or status, 'result_path': 'measurements', 'benchmark': 'category-smoke', 'attempt_id': ATTEMPT_ID})
    for name in measurements:
        directory = attempt / 'measurements' / name
        write_json(directory / 'metadata.json', metadata if metadata is not None else offload_metadata(synthetic=synthetic))
        (directory / 'requests.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in (rows if rows is not None else offload_rows())),
                                                  encoding='utf-8', newline='\n')
        write_json(directory / 'telemetry.json', telemetry if telemetry is not None else [])
    return campaign, attempt


def attested(**attestation):
    """Fixture metadata whose operator attestation is changed by `attestation` (a None value removes the key)."""
    metadata = offload_metadata()
    values = dict(metadata['config']['hardware_attestation'])
    for key, value in attestation.items():
        if value is None:
            values.pop(key, None)
        else:
            values[key] = value
    metadata['config'] = {**metadata['config'], 'hardware_attestation': values}
    return metadata


def bound_role(path, **changes):
    """A generator role that matches the fixture serving profile field by field."""
    value = generator(platform='lmstudio', backend_version='0.4.28+2', artifact_sha256='5' * 64, quantization='Q8_0', template_sha256='3' * 64,
                      tokenizer_revision='tok-rev-1', context_tokens=4096, max_output_tokens=1024, placement={'gpu_layers': 20},
                      model_revision='4' * 40, qualification={'serving_profile': str(path)})
    value.update(changes)
    return value


def frozen(root, **kwargs):
    campaign, _ = offload_attempt(root)
    profile = profiles.freeze(campaign, JOB_ID, ATTEMPT_ID, observed_placement={'gpu_layers': 20}, **kwargs)
    path = Path(root) / 'serving-profile.json'
    profiles.write_profile(profile, path)
    return profile, path


class TempCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name)
        gpu = patch('llm_eval.telemetry.gpu_snapshot', return_value=[])
        gpu.start()
        self.addCleanup(gpu.stop)

    def inventory(self, os_id='ubuntu-26.04-native', resource_hosts=None, service_target=False):
        local = {'transport': 'local', 'physical_host_id': HOST, 'lock_root': str(self.path / 'worker-locks')}
        if resource_hosts:
            local['resource_hosts'] = list(resource_hosts)
        targets = {'local': local}
        if service_target:
            targets['service'] = {'transport': 'local', 'physical_host_id': 'service-host', 'lock_root': str(self.path / 'worker-locks')}
        write_json(self.path / 'inventory.json', {'targets': targets, 'hardware_configs': {
            'native': {'target': 'local', 'hardware_profile': 'msi-raider-18-hx-ai', 'os_id': os_id}}})

    def plan(self, name, mode, parameters, os_id='ubuntu-26.04-native', **inventory):
        self.inventory(os_id, **inventory)
        write_json(self.path / f'{name}.json', {'id': name, 'parameters': parameters})
        write_json(self.path / f'{name}-campaign.json', {'schema_version': 2, 'id': name, 'inventory': 'inventory.json', 'phases': [
            {'id': 'legal', 'experiments': [{'id': 'legal-benchmark', 'version': 1, 'mode': mode, 'cases': [f'{name}.json'],
                                             'hardware_configs': ['native']}]}]})
        return compile_campaign(self.path / f'{name}-campaign.json', ROOT)

    def run_job(self, job, name):
        """The worker's order for one planned job, in-process: job.json, execute, result.json."""
        out = self.path / 'attempts' / name
        out.mkdir(parents=True)
        atomic_json(out / 'job.json', job)
        result = legal.execute(job, out, ROOT)
        atomic_json(out / 'result.json', {**result, 'attempt_id': out.name})
        return out


# 1. Approved suites ---------------------------------------------------------------------------------------------------

class ApprovalTests(TempCase):
    def test_approved_list_names_only_shipped_public_synthetic_locks(self):
        data = (X / 'approved-suites.json').read_bytes()
        self.assertNotIn(b'\r', data)
        self.assertEqual(data, (json.dumps(json.loads(data), indent=2, sort_keys=True) + '\n').encode())
        approved = contracts.approved_suites()
        shipped = {sha256_file(p): p for p in X.glob('workloads/*/suite.lock.json')}
        self.assertEqual(set(approved), {sha256_file(SMOKE), sha256_file(PACKETS)})
        for key, entry in approved.items():
            self.assertIn(key, shipped)
            lock = read_json(shipped[key])
            self.assertEqual((lock['data_class'], lock['benchmark_id'], entry), ('public-synthetic', entry['benchmark_id'],
                                                                                 {'benchmark_id': lock['benchmark_id'], 'fixture_export': True}))
        self.assertEqual(approved[sha256_file(SMOKE)]['benchmark_id'], 'legal-original-smoke')
        self.assertEqual(contracts.export_allowed(SMOKE), sha256_file(SMOKE))
        self.assertEqual(contracts.export_allowed(PACKETS), sha256_file(PACKETS))
        good = json.loads(data)
        key = sha256_file(SMOKE)
        for broken in ({**good, 'extra': 1}, {**good, 'schema_version': 2}, {'schema_version': 1, 'suites': {key.upper(): good['suites'][key]}},
                       {'schema_version': 1, 'suites': {key: {**good['suites'][key], 'fixture_export': 'yes'}}},
                       {'schema_version': 1, 'suites': {key: {**good['suites'][key], 'benchmark_id': 'Not An Id'}}},
                       {'schema_version': 1, 'suites': {key: {'benchmark_id': 'legal-original-smoke'}}},
                       {'schema_version': 1, 'suites': {key: {**good['suites'][key], 'off_host': True}}}):
            with self.subTest(broken=broken):
                write_json(self.path / 'experiments/legal-benchmark/approved-suites.json', broken)
                with self.assertRaises(ValueError):
                    contracts.approved_suites(self.path)
        (self.path / 'experiments/legal-benchmark/approved-suites.json').write_text('{"schema_version": 1, "schema_version": 1}', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'Duplicate JSON key'):
            contracts.approved_suites(self.path)
        # An entry that is not marked for fixture export, or names another benchmark, does not allow an export.
        for entry in ({'benchmark_id': 'legal-original-smoke', 'fixture_export': False}, {'benchmark_id': 'legal-other', 'fixture_export': True}):
            with self.subTest(entry=entry):
                with patch.object(contracts, 'approved_suites', return_value={key: entry}):
                    with self.assertRaisesRegex(ValueError, 'Export is limited to approved fixture suites'):
                        contracts.export_allowed(SMOKE)


# 2. Locked serving profiles -------------------------------------------------------------------------------------------

class ProfileTests(TempCase):
    def test_freeze_copies_identity_and_measured_fields_from_one_attempt(self):
        campaign, attempt = offload_attempt(self.path)
        profile = profiles.freeze(campaign, JOB_ID, ATTEMPT_ID, observed_placement={'gpu_layers': 20})
        measured = f'measurements/{MEASUREMENT}/'
        self.assertEqual(profile['source'], {
            'campaign_id': 'offload-qualification', 'campaign_dir': CAMPAIGN_DIR, 'plan_sha256': read_json(campaign / 'plan.json')['plan_sha256'],
            'experiment_run_id': 'offload-model-offloading-1', 'job_id': JOB_ID, 'attempt_id': ATTEMPT_ID, 'measurement': MEASUREMENT,
            'physical_host_id': HOST, 'hardware_profile': 'msi-raider-18-hx-ai', 'result_status': 'succeeded', 'measurement_status': 'completed',
            'files': [{'path': p, 'sha256': sha256_file(attempt / p)} for p in sorted(
                ['host.json', 'job.json', 'result.json', measured + 'metadata.json', measured + 'requests.jsonl', measured + 'telemetry.json'])]})
        self.assertEqual((profile['schema_version'], profile['kind'], profile['code_revision'], profile['harness_version']),
                         (1, 'legal-serving-profile', '1' * 40, '0.3.0'))
        self.assertEqual(profile['os'], {'os_id': {'value': 'windows-11-native', 'nature': 'declared'},
                                         'environment_kind': {'value': 'windows-11-native', 'nature': 'observed'},
                                         'os_build': {'value': '26100.4061', 'nature': 'attested'}})
        self.assertEqual(profile['driver'], {'value': '610.74', 'nature': 'observed'})
        self.assertEqual(profile['runtime'], {'platform': {'value': 'lmstudio', 'nature': 'declared'},
                                              'backend_version': {'value': '0.4.28+2', 'nature': 'attested'}})
        self.assertEqual(profile['artifact'], {'artifact_sha256': {'value': '5' * 64, 'nature': 'observed'},
                                               'source_revision': {'value': '4' * 40, 'nature': 'declared'},
                                               'quantization': {'value': 'Q8_0', 'nature': 'declared'}})
        self.assertEqual(profile['template'], {'chat_template_sha256': {'value': '3' * 64, 'nature': 'attested'},
                                               'tokenizer_revision': {'value': 'tok-rev-1', 'nature': 'attested'}})
        self.assertEqual(profile['placement'], {'requested': {'gpu_layers': 20, 'gpu_offload': None, 'threads': 8, 'context_tokens': 4096,
                                                              'max_output_tokens': 1024},
                                                'observed': {'value': {'gpu_layers': 20}, 'nature': 'attested'}})
        self.assertEqual(profile['memory'], {
            'reserve': {'host_reserve_gib': {'value': 12, 'nature': 'declared'}, 'gpu_reserve_gib': {'value': 2, 'nature': 'declared'}},
            'totals': {'host_ram_gib': {'value': 63.5, 'nature': 'observed'}, 'gpu_vram_mib': {'value': 24463, 'nature': 'observed'}},
            'peaks': {'system_used_gib': {'value': 41.2, 'nature': 'observed'}, 'swap_used_gib': {'value': 0.0, 'nature': 'observed'},
                      'backend_tree_rss_gib': {'value': None, 'nature': 'unavailable'}, 'gpu_used_mib': {'value': 12019, 'nature': 'observed'}},
            'paging_observed': {'value': False, 'nature': 'attested'}, 'reserve_checked': True})
        # Medians over the three non-warmup rows with status ok (hand-computed); the warmup row is excluded.
        self.assertEqual(profile['throughput'], {'requests': 3, 'errors': 0, 'truncated': 0,
                                                 'output_tokens_per_wall_second_median': {'value': 6.4, 'nature': 'observed'},
                                                 'elapsed_s_median': {'value': 7.75, 'nature': 'observed'},
                                                 'first_output_s_median': {'value': 0.9, 'nature': 'observed'}})
        self.assertEqual(profile['probe'], {'outcome': 'passed', 'reason_codes': []})
        self.assertEqual(profile['workload'], {'suite_sha256': WORKLOAD_SHA256, 'benchmark': 'legal-shaped'})
        # A failed job, request errors and observed paging each fail the probe, in the stated reason order.
        for name, kwargs, codes in (('failed', {'status': 'failed'}, ['job_not_succeeded']),
                                    ('errors', {'rows': offload_rows(errors=1)}, ['request_errors']),
                                    ('paging', {'metadata': attested(paging='observed')}, ['paging_observed']),
                                    ('all', {'status': 'failed', 'rows': offload_rows(errors=1), 'metadata': attested(paging='observed')},
                                     ['job_not_succeeded', 'request_errors', 'paging_observed'])):
            with self.subTest(name):
                campaign, _ = offload_attempt(self.path / name, **kwargs)
                probe = profiles.freeze(campaign, JOB_ID, ATTEMPT_ID, observed_placement={'gpu_layers': 20})['probe']
                self.assertEqual(probe, {'outcome': 'failed', 'reason_codes': codes})
        campaign, _ = offload_attempt(self.path / 'cut', rows=offload_rows(finish='length'))
        self.assertEqual(profiles.freeze(campaign, JOB_ID, ATTEMPT_ID, observed_placement={'gpu_layers': 20})['probe'],
                         {'outcome': 'inconclusive', 'reason_codes': ['all_responses_truncated']})
        # The attested driver is used only when host.json observed none.
        campaign, _ = offload_attempt(self.path / 'nodriver', host={'environment_kind': 'windows-11-native', 'gpus': []})
        self.assertEqual(profiles.freeze(campaign, JOB_ID, ATTEMPT_ID)['driver'], {'value': '610.74', 'nature': 'attested'})

    def test_freeze_needs_an_explicit_attempt(self):
        campaign, _ = offload_attempt(self.path)
        with self.assertRaises(TypeError):
            profiles.freeze(campaign, JOB_ID)      # no default attempt
        for job_id, attempt_id, message in ((JOB_ID, 'f' * 32, 'not an attempt of the job'), ('other-job', ATTEMPT_ID, 'Unknown job'),
                                            (JOB_ID, None, 'not an attempt of the job')):
            with self.subTest(job_id=job_id, attempt_id=attempt_id), self.assertRaisesRegex(ValueError, message):
                profiles.freeze(campaign, job_id, attempt_id)
        two, _ = offload_attempt(self.path / 'two', measurements=(MEASUREMENT, '20261111T000100Z-1b2c3d4e'))
        with self.assertRaisesRegex(ValueError, 'Name the measurement directory'):
            profiles.freeze(two, JOB_ID, ATTEMPT_ID)
        self.assertEqual(profiles.freeze(two, JOB_ID, ATTEMPT_ID, measurement='20261111T000100Z-1b2c3d4e')['source']['measurement'],
                         '20261111T000100Z-1b2c3d4e')
        with self.assertRaisesRegex(ValueError, 'Unknown measurement directory'):
            profiles.freeze(two, JOB_ID, ATTEMPT_ID, measurement='../escape')
        for name, kwargs, message in (('synthetic', {'synthetic': True}, 'A synthetic run cannot qualify a serving profile'),
                                      ('measured', {'metadata': offload_metadata(synthetic=True)}, 'A synthetic run cannot qualify a serving profile'),
                                      ('legal', {'experiment': 'legal-benchmark'}, 'not a model-offloading job'),
                                      ('running', {'status': 'running'}, 'The attempt has no finished result')):
            with self.subTest(name), self.assertRaisesRegex(ValueError, message):
                campaign, _ = offload_attempt(self.path / name, **kwargs)
                profiles.freeze(campaign, JOB_ID, ATTEMPT_ID)
        # The CLI requires all three ids.
        with self.assertRaises(SystemExit), patch('sys.stderr', io.StringIO()):
            profiles.main(['freeze', '--campaign-dir', str(campaign), '--job-id', JOB_ID, '--output', str(self.path / 'p.json')])
        good, _ = offload_attempt(self.path / 'cli')
        with patch('sys.stdout', io.StringIO()):
            self.assertEqual(profiles.main(['freeze', '--campaign-dir', str(good), '--job-id', JOB_ID, '--attempt-id', ATTEMPT_ID,
                                            '--observed-placement', 'gpu_layers=20,threads=8', '--output', str(self.path / 'cli.json')]), 0)
        self.assertEqual(profiles.load_profile(self.path / 'cli.json')[0]['placement']['observed'],
                         {'value': {'gpu_layers': 20, 'threads': 8}, 'nature': 'attested'})

    def test_unobserved_values_are_marked_unavailable(self):
        metadata = attested(paging=None)
        campaign, _ = offload_attempt(self.path, metadata=metadata)
        profile = profiles.freeze(campaign, JOB_ID, ATTEMPT_ID)
        self.assertEqual(profile['memory']['peaks']['backend_tree_rss_gib'], {'value': None, 'nature': 'unavailable'})
        self.assertEqual(profile['memory']['paging_observed'], {'value': None, 'nature': 'unavailable'})
        self.assertEqual(profile['placement']['observed'], {'value': None, 'nature': 'unavailable'})
        self.assertEqual(profile['probe'], {'outcome': 'inconclusive', 'reason_codes': ['paging_unknown', 'placement_unobserved']})
        campaign, _ = offload_attempt(self.path / 'attested')
        profile = profiles.freeze(campaign, JOB_ID, ATTEMPT_ID, observed_placement={'gpu_layers': 20})
        self.assertEqual(profile['placement']['observed'], {'value': {'gpu_layers': 20}, 'nature': 'attested'})
        self.assertEqual(profile['probe']['outcome'], 'passed')
        for bad in ({'layers': 20}, {'gpu_layers': 'twenty'}, {'gpu_layers': True}, {'gpu_layers': -1}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                profiles.freeze(campaign, JOB_ID, ATTEMPT_ID, observed_placement=bad)
        sparse = offload_metadata(telemetry={'samples': 0}, artifact_sha256=None, hardware_profile={'ram': {'installed_gib': 64}})
        sparse['config']['hardware_attestation'] = {'paging': 'none'}
        campaign, _ = offload_attempt(self.path / 'sparse', metadata=sparse, rows=[])
        profile = profiles.freeze(campaign, JOB_ID, ATTEMPT_ID)
        self.assertEqual(profile['probe'], {'outcome': 'inconclusive', 'reason_codes': ['placement_unobserved', 'no_measured_requests']})
        self.assertFalse(profile['memory']['reserve_checked'])
        for leaf in (profile['artifact']['artifact_sha256'], profile['memory']['reserve']['host_reserve_gib'], profile['memory']['peaks']['gpu_used_mib'],
                     profile['throughput']['elapsed_s_median']):
            self.assertEqual(leaf, {'value': None, 'nature': 'unavailable'})
        self.assertEqual((profile['throughput']['requests'], profile['throughput']['errors'], profile['throughput']['truncated']), (0, 0, 0))

    def test_attestation_keys_are_named_and_validated(self):
        attestation = {'os_build': 'build 26100', 'nvidia_driver': 'C:/drivers/610', 'model_path': 'C:\\models\\fixture.gguf',
                       'bios': 'Fixture BIOS sentence with spaces'}
        metadata = offload_metadata()
        metadata['config'] = {**metadata['config'], 'hardware_attestation': attestation}
        campaign, _ = offload_attempt(self.path, metadata=metadata, host={'environment_kind': 'windows-11-native', 'gpus': []})
        profile = profiles.freeze(campaign, JOB_ID, ATTEMPT_ID)
        self.assertEqual(profile['os']['os_build'], {'value': None, 'nature': 'unavailable'})
        self.assertEqual(profile['driver'], {'value': None, 'nature': 'unavailable'})
        text = json.dumps(profile)
        for leaked in ('fixture.gguf', 'Fixture BIOS', 'model_path', 'bios', 'drivers'):
            self.assertNotIn(leaked, text)
        metadata['config']['hardware_attestation'] = {'os_build': '26100.4061', 'nvidia_driver': '610.74'}
        campaign, _ = offload_attempt(self.path / 'good', metadata=metadata, host={'environment_kind': 'windows-11-native', 'gpus': []})
        profile = profiles.freeze(campaign, JOB_ID, ATTEMPT_ID)
        self.assertEqual((profile['os']['os_build'], profile['driver']), ({'value': '26100.4061', 'nature': 'attested'},
                                                                          {'value': '610.74', 'nature': 'attested'}))

    def test_profile_bytes_are_canonical_and_private_values_are_absent(self):
        profile, path = frozen(self.path)
        data = path.read_bytes()
        self.assertNotIn(b'\r', data)
        self.assertEqual(data, (json.dumps(profile, indent=2, sort_keys=True, ensure_ascii=False) + '\n').encode())
        self.assertEqual(profiles.write_profile(profile, self.path / 'again.json'), sha256_file(path))
        loaded, sha = profiles.load_profile(path)
        self.assertEqual((loaded, sha), (profile, sha256_file(path)))
        text = data.decode()
        for leaked in ('127.0.0.1', 'endpoint', '4242', 'backend_pid', 'fixture-host-name', '"node"', 'placement_notes', 'Requested twenty', 'C:',
                       str(self.path), 'fixture.gguf', '/fixture/root'):
            self.assertNotIn(leaked, text)
        for broken in ({**profile, 'extra': 1}, {**profile, 'kind': 'other'},
                       {**profile, 'driver': {'value': '610.74', 'nature': 'guessed'}},
                       {**profile, 'driver': {'value': '610.74', 'nature': 'unavailable'}},
                       {**profile, 'os': {**profile['os'], 'hostname': {'value': 'x', 'nature': 'observed'}}},
                       {**profile, 'driver': {'value': 'a sentence with spaces', 'nature': 'observed'}},
                       {**profile, 'probe': {'outcome': 'great', 'reason_codes': []}}):
            with self.subTest(broken=broken):
                write_json(self.path / 'broken.json', broken)
                with self.assertRaises(ValueError):
                    profiles.load_profile(self.path / 'broken.json')

    def test_role_must_match_its_locked_profile_and_a_failed_probe_is_refused(self):
        profile, path = frozen(self.path)
        role = bound_role(path)
        profiles.bind(role, profile)
        self.assertEqual(profiles.validate_role(role, 'generator')['qualification'], {'serving_profile': str(path)})
        profiles.bind({**role, 'max_output_tokens': 512}, profile)       # at most the profile's output budget
        for field, change in (('platform', {'platform': 'ollama'}), ('backend_version', {'backend_version': '0.4.29'}),
                              ('artifact_sha256', {'artifact_sha256': 'a' * 64}), ('quantization', {'quantization': 'Q4_K_M'}),
                              ('template_sha256', {'template_sha256': 'b' * 64}), ('tokenizer_revision', {'tokenizer_revision': 'tok-rev-2'}),
                              ('context_tokens', {'context_tokens': 8192}), ('max_output_tokens', {'max_output_tokens': 2048, 'context_tokens': 4096}),
                              ('placement', {'placement': {'gpu_layers': 30}}), ('placement', {'placement': {'gpu_layers': 20, 'threads': 4}}),
                              ('model_revision', {'model_revision': 'r1'})):
            with self.subTest(field=field, change=change):
                with self.assertRaisesRegex(ValueError, 'Role profile does not match its locked serving profile: ' + field):
                    profiles.bind({**role, **change}, profile)
                if field != 'max_output_tokens':
                    with self.assertRaisesRegex(ValueError, 'Role profile does not match its locked serving profile: ' + field):
                        profiles.validate_role({**role, **change}, 'generator')
        inconclusive = copy.deepcopy(profile)
        inconclusive['placement']['observed'] = {'value': None, 'nature': 'unavailable'}
        inconclusive['probe'] = {'outcome': 'inconclusive', 'reason_codes': ['placement_unobserved']}
        with self.assertRaisesRegex(ValueError, 'Locked serving profile did not pass its probe'):
            profiles.bind(role, inconclusive)
        campaign, _ = offload_attempt(self.path / 'unobserved')
        profiles.write_profile(profiles.freeze(campaign, JOB_ID, ATTEMPT_ID), self.path / 'unobserved.json')
        with self.assertRaisesRegex(ValueError, 'Locked serving profile did not pass its probe'):
            profiles.validate_role(bound_role(self.path / 'unobserved.json'), 'generator')
        for bad in ({'serving_profile': 1}, {'serving_profile': str(path), 'other': 1}, 'profile.json'):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                profiles.validate_role({**role, 'qualification': bad}, 'generator')
        with self.assertRaisesRegex(ValueError, 'Locked serving profile not found'):
            profiles.validate_role(bound_role(self.path / 'missing.json'), 'generator')

    def test_locked_profile_is_a_pinned_campaign_input(self):
        _, path = frozen(self.path)
        with FakeGenerator(respond=lambda body: json.dumps(fixture.draft(self.matter(body), self.suite['corpus']))) as fake:
            self.lock = subset_suite(self.path / 'suite', ('f1-ledger-a',))
            self.suite = contracts.load_suite(self.lock)
            role = bound_role('serving-profile.json', endpoint=fake.endpoint)
            plan = self.plan('qualified', 'generation', {'suite': 'suite/suite.lock.json', 'arms': ['lexical-eligible'], 'roles': {'generator': role}},
                             os_id='windows-11-native')
            (job,) = plan['jobs']
            recorded = {f['path']: f['sha256'] for f in job['input_files']}
            self.assertEqual(recorded[str(path.resolve())], sha256_file(path))
            self.assertEqual(plan['inputs'][str(path.resolve())], sha256_file(path))
            attempt = self.run_job(job, 'qualified')
        metadata = read_json(attempt / 'metadata.json')
        public = metadata['roles']['generator']
        self.assertEqual((public['qualified'], public['serving_profile_sha256']), (True, sha256_file(path)))
        stored = read_json(attempt / 'job.json')
        self.assertEqual(public['profile_sha256'], profiles.profile_digest(stored['parameters']['roles']['generator'], stored['input_files']))
        other = [{**f, 'sha256': 'f' * 64} if f['path'] == str(path.resolve()) else f for f in stored['input_files']]
        self.assertNotEqual(profiles.profile_digest(stored['parameters']['roles']['generator'], other), public['profile_sha256'])
        manifest = read_json(attempt / 'local/output-manifest.json')
        self.assertEqual(manifest['role_digests']['generator'], public['profile_sha256'])
        # The score mode recomputes the role view from the stored job and accepts the qualified source attempt.
        self.assertIsNone(legal.validate({'suite': str(self.lock), 'output_manifest': str(attempt / 'local/output-manifest.json')}, ROOT, 'score'))
        # Another OS than the profile's is refused at run time.
        with self.assertRaisesRegex(ValueError, 'Locked serving profile was measured on another OS'):
            profiles.check_job(job['parameters']['roles'], {**job, 'hardware': {**job['hardware'], 'os_id': 'ubuntu-26.04-native'}})
        # One changed byte: the coordinator and the worker refuse before any request.
        with patch('llm_eval.orchestration.resources.lock_root', return_value=self.path / 'locks'):
            directory = initialize(plan, self.path / 'out')
        path.write_bytes(path.read_bytes().replace(b'"passed"', b'"passed" '))
        with self.assertRaisesRegex(ValueError, 'Campaign input changed'):
            run_campaign(directory)
        from llm_eval.orchestration import worker
        with self.assertRaisesRegex(ValueError, 'Worker input hash mismatch'):
            worker.handle({'action': 'run', 'job': job, 'root': str(ROOT), 'output': str(self.path / 'worker'), 'owner': 'test',
                           'code_revision': plan['code_revision']})
        with self.assertRaisesRegex(ValueError, 'Locked serving profile differs from the planned input'):
            profiles.check_job(job['parameters']['roles'], job)

    def matter(self, body):
        content = body['messages'][1]['content']
        return next(m for m in self.suite['matters']['matters'] if 'MATTER ' + m['matter_id'] + '\n' in content)

    def test_role_host_must_be_reserved_by_the_job(self):
        from llm_eval.orchestration import scheduler
        role = generator(resource_host='service-host')
        parameters = {'suite': str(SMOKE), 'arms': ['no-context'], 'roles': {'generator': role}}
        (job,) = self.plan('unreserved', 'generation', parameters)['jobs']
        self.assertEqual(job['resources'], [HOST])
        with self.assertRaisesRegex(ValueError, 'Role host is not reserved by this job: generator'):
            profiles.check_job(job['parameters']['roles'], job)
        with self.assertRaisesRegex(ValueError, 'Role host is not reserved by this job: generator'):
            self.run_job(job, 'unreserved')
        self.assertFalse((self.path / 'attempts/unreserved/requests.jsonl').exists())
        plan = self.plan('reserved', 'generation', parameters, resource_hosts=['service-host'], service_target=True)
        (job,) = plan['jobs']
        self.assertEqual(job['resources'], [HOST, 'service-host'])
        profiles.check_job(job['parameters']['roles'], job)
        self.assertEqual([t['physical_host_id'] for t in scheduler._targets(job, plan)], [HOST, 'service-host'])
        plan = self.plan('no-target', 'generation', parameters, resource_hosts=['service-host'])
        (job,) = plan['jobs']
        profiles.check_job(job['parameters']['roles'], job)
        with self.assertRaisesRegex(ValueError, 'Every reserved resource host must have a target in this campaign'):
            scheduler._targets(job, plan)
        # A role on the job's own host needs nothing more than the job's own reservation.
        local = {'generator': generator()}
        profiles.check_job(local, {**job, 'resources': [HOST]})
        with self.assertRaisesRegex(ValueError, 'Role host is not reserved by this job: generator'):
            profiles.check_job(local, {**job, 'resources': []})
        # The retrieval mode makes the same check for its served roles.
        embedder = {'role': 'embedder', 'serving': 'external', 'capability': 'embedding', 'deployment_id': 'local-embedder', 'platform': 'fake',
                    'backend_version': '1', 'model': 'fake-embed', 'model_revision': 'r1', 'protocol': 'json', 'endpoint': 'http://127.0.0.1:9/v1/embed',
                    'accelerator': 'cpu', 'timeout_s': 5, 'dimensions': 8, 'resource_host': 'service-host'}
        (job,) = self.plan('retrieval', 'retrieval', {'suite': str(SMOKE), 'arms': ['dense'], 'roles': {'embedder': embedder}})['jobs']
        with self.assertRaisesRegex(ValueError, 'Role host is not reserved by this job: embedder'):
            self.run_job(job, 'retrieval')

    def test_legal_shaped_workload_matches_its_export_and_loads_as_a_task_suite(self):
        from llm_eval.runner import load_suite as load_task_suite
        shipped = X / 'workloads/qualification/legal-shaped.json'
        sha = profiles.export_workload(SMOKE, self.path / 'legal-shaped.json')
        self.assertEqual((self.path / 'legal-shaped.json').read_bytes(), shipped.read_bytes())
        self.assertEqual(sha, sha256_file(shipped))
        self.assertNotIn(b'\r', shipped.read_bytes())
        suite = load_task_suite(shipped)
        self.assertEqual((suite['benchmark'], suite['category'], suite['family']), ('legal-shaped', 'legal', 'general'))
        smoke = contracts.load_suite(SMOKE)
        self.assertEqual([t['id'] for t in suite['tasks']], sorted(m['matter_id'] for m in smoke['matters']['matters']))
        self.assertEqual({json.dumps(t['check']) for t in suite['tasks']}, {'{"type": "none"}'})
        view = contracts.candidate_view(smoke)
        first = smoke['matters']['matters'][0]
        expected = workflow().build_messages(first, retrieval.retrieve(view, first, 'lexical-eligible', {}))
        self.assertEqual(next(t for t in suite['tasks'] if t['id'] == first['matter_id'])['messages'], expected)
        text = shipped.read_text(encoding='utf-8')
        for g in smoke['rubric']['matters']:
            self.assertIsNone(re.search(r'"recommendation": "(charge|decline|defer)"', text))
            self.assertNotIn('"scenario"', text)
        with patch('sys.stdout', io.StringIO()):
            self.assertEqual(profiles.main(['workload', '--suite', str(SMOKE), '--output', str(self.path / 'cli.json')]), 0)
        self.assertEqual((self.path / 'cli.json').read_bytes(), shipped.read_bytes())


# 3. Bounded routing ---------------------------------------------------------------------------------------------------

class FakeSelector:
    """A scripted SystemOne-shaped decision endpoint (JSON reply with Content-Length, as tests/test_routing.py). It answers
    from `answer(body)`, which returns {'choice', 'probabilities'?}, and records every request body. A fixture."""

    def __init__(self, answer):
        self.requests = []
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                owner.requests.append(body)
                route = {'type': 'choice', **answer(body)}
                data = json.dumps({'answers': {'route': route}, 'usage': {'input_tokens': 5, 'output_tokens': 1}}).encode()
                self.send_response(200)
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.endpoint = f'http://127.0.0.1:{self.server.server_port}/v1/systemone'
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()


def selector_role(endpoint='http://127.0.0.1:9/v1/systemone', **changes):
    value = {'role': 'selector', 'serving': 'external', 'capability': 'decision', 'deployment_id': 'local-selector', 'platform': 'fake-decision',
             'backend_version': '1', 'model': 'fake-router', 'model_revision': 'r1', 'protocol': 'json', 'endpoint': endpoint, 'accelerator': 'cpu',
             'timeout_s': 5}
    value.update(changes)
    return value


CRITERIA = {'lexical': 'Matters with a statute and routine evidence', 'none': 'Matters that need no retrieved context',
            'insufficient_evidence': 'The evidence cannot support any recommendation', 'insufficient_authority': 'No listed authority governs'}
CATEGORY = {'router': {'kind': 'category', 'default_category': 'lexical', 'keywords': {'none': ['ferry']}},
            'policy': {'category_models': {'lexical': 'lexical-eligible', 'none': 'no-context'}, 'fallback': 'lexical-eligible',
                       'abstain_threshold': 0.0, 'require_confidence': False}, 'calibration': None}


def served(**policy):
    return {'router': {'kind': 'systemone', 'instructions': 'Choose the retrieval recipe for this matter.', 'criteria': dict(CRITERIA)},
            'policy': {'category_models': {'lexical': 'lexical-eligible', 'none': 'no-context'}, 'fallback': 'lexical-eligible',
                       'abstain_threshold': 0.0, 'require_confidence': False, **policy}, 'calibration': None}


def by_question(body, mapping, probabilities=None):
    text = body['state']['messages'][0]['content']
    choice = next((label for word, label in mapping.items() if word in text), 'lexical')
    reply = {'choice': choice}
    if probabilities is not None:      # the rest of the mass on one other label, so the choice keeps exactly `probabilities`
        rest = next(k for k in CRITERIA if k != choice)
        reply['probabilities'] = {k: probabilities if k == choice else round(1 - probabilities, 6) if k == rest else 0.0 for k in CRITERIA}
    return reply


class RoutedCase(TempCase):
    MATTERS = ('f1-ledger-a', 'f1-ledger-b', 'f8-manifest-a')      # gold charge, defer and decline

    def setUp(self):
        super().setUp()
        self.lock = subset_suite(self.path / 'suite', self.MATTERS, getattr(self, 'edit', None))
        self.suite = contracts.load_suite(self.lock)

    def respond(self, body):
        """The scripted generator: the reference drafter's output for the matter named in the prompt, limited to the listed
        authorities, with a fixed issue question (so a matter question never comes back in a reply). A fixture."""
        content = body['messages'][1]['content']
        matter = next(m for m in self.suite['matters']['matters'] if 'MATTER ' + m['matter_id'] + '\n' in content)
        if 'analysis v1' in body['messages'][0]['content']:
            return ANALYSIS(matter['matter_id'])
        output = fixture.draft(matter, self.suite['corpus'])
        listed = set(re.findall(r'^\[([a-z0-9-]+@[0-9]+)\] ', content, re.M))
        if listed:
            output['claims'] = [c for c in output['claims'] if c['authority_id'] + '@' + c['version'] in listed]
        for issue in output['issues']:
            issue['question'] = 'Fixture issue question'
        return json.dumps(output)

    def routed(self, selector, arms=('no-context', 'lexical-eligible'), name='routed', mode='generation', roles=None, selector_endpoint=None):
        """Plan and run one routed job in-process against the scripted generator; returns (attempt, job, generator requests)."""
        with FakeGenerator(respond=self.respond) as fake:
            served_roles = {'generator': generator(fake.endpoint), **(roles or {})}
            plan = self.plan(name, mode, {'suite': 'suite/suite.lock.json', 'arms': list(arms), 'roles': served_roles, 'selector': selector})
            (job,) = plan['jobs']
            attempt = self.run_job(job, name)
        return attempt, job, fake.requests


class RoutingTests(RoutedCase):
    def test_rule_and_fixed_selectors_route_between_retrieval_recipes(self):
        r = routing()
        fixed = {'router': {'kind': 'fixed', 'choice': 'lexical'}, 'policy': {'category_models': {'lexical': 'lexical-eligible'},
                                                                                 'fallback': 'no-context'}, 'calibration': None}
        attempt, job, requests = self.routed(fixed)
        rows = lines(attempt / 'requests.jsonl')
        self.assertEqual(len(requests), 3)      # one generation request per matter, to the selected arm only
        self.assertEqual([(x['task_id'], x['arm'], x['category'], x['routed'], x['route_choice'], x['route_selected'], x['route_fallback'],
                           x['route_confidence']) for x in rows],
                         [(m, 'routed', 'routed', True, 'lexical', 'lexical-eligible', False, None) for m in self.MATTERS])
        self.assertTrue(all(isinstance(x['router_s'], float) and x['router_s'] >= 0 for x in rows))
        self.assertTrue(all(x['status'] == 'ok' and x['quality_check_applicable'] for x in rows))
        self.assertFalse({'decision_correct', 'prompt_sha256', 'messages'} & {k for x in rows for k in x})
        results = lines(attempt / 'local/retrieval-results.jsonl')
        self.assertEqual([(x['arm'], x['result']['arm']) for x in results], [('routed', 'lexical-eligible')] * 3)
        self.assertEqual({d['arm'] for d in lines(attempt / 'local/score-detail.jsonl')}, {'routed'})
        metadata = read_json(attempt / 'metadata.json')
        self.assertEqual(metadata['arms'], ['no-context', 'lexical-eligible'])
        self.assertEqual(metadata['selector'], {'selector_sha256': r.selector_digest(fixed, {}, job['input_files']), 'router_kind': 'fixed',
                                                'calibration_sha256': None})
        self.assertEqual(list(metadata['telemetry']), ['routed'])
        self.assertEqual(metadata['execution_kind'], 'model-run')
        # A category rule reads the route-time message only.
        attempt, _, requests = self.routed(CATEGORY, name='category')
        rows = lines(attempt / 'requests.jsonl')
        self.assertEqual(len(requests), 3)
        self.assertEqual([(x['task_id'], x['route_choice'], x['route_selected']) for x in rows],
                         [('f1-ledger-a', 'lexical', 'lexical-eligible'), ('f1-ledger-b', 'lexical', 'lexical-eligible'), ('f8-manifest-a', 'none', 'no-context')])
        self.assertEqual([x['result']['arm'] for x in lines(attempt / 'local/retrieval-results.jsonl')], ['lexical-eligible', 'lexical-eligible', 'no-context'])
        self.assertNotEqual(r.selector_digest(CATEGORY, {}), r.selector_digest(fixed, {}))
        changed = copy.deepcopy(CATEGORY)
        changed['router']['keywords']['none'] = ['warehouse']
        self.assertNotEqual(r.selector_digest(changed, {}), r.selector_digest(CATEGORY, {}))
        self.assertEqual(r.router_for(CATEGORY, {}), CATEGORY['router'])
        # The route-time message: question, date, venue and evidence source counts; no text, label or outcome.
        matter = next(m for m in self.suite['matters']['matters'] if m['matter_id'] == 'f8-manifest-a')
        (message,) = r.route_messages(matter)
        self.assertEqual(message['role'], 'user')
        self.assertEqual(message['content'].split('\n'), ['QUESTION ' + matter['question'], 'OPERATIVE DATE ' + matter['operative_date'],
                                                          'VENUE ' + matter['venue'], 'EVIDENCE SOURCES record: 1, report: 1, statement: 1'])

    def test_insufficient_labels_defer_without_generation(self):
        r, g = routing(), grading()
        with FakeSelector(lambda body: by_question(body, {'warehouse': 'insufficient_evidence'})) as selector:
            attempt, job, requests = self.routed(served(), roles={'selector': selector_role(selector.endpoint)})
        self.assertEqual(len(selector.requests), 3)
        self.assertEqual(selector.requests[0]['questions']['route']['criteria'], CRITERIA)
        self.assertEqual(len(requests), 1)      # the two deferred matters send no generation request
        rows = {x['task_id']: x for x in lines(attempt / 'requests.jsonl')}
        for matter in ('f1-ledger-a', 'f1-ledger-b'):
            row = rows[matter]
            self.assertEqual((row['arm'], row['category'], row['status'], row['inference_status'], row['parse_status'], row['choice'],
                              row['author_choice'], row['forced_defer'], row['abstained'], row['grading_status'], row['quality_check_applicable'],
                              row['quality_pass'], row['criteria_passed'], row['critical_errors'], row['request_attempts']),
                             ('routed', 'routed-defer', 'ok', 'not_applicable', 'not_applicable', 'defer', None, True, False, 'scored', True,
                              False, 0, 0, 0))
            self.assertEqual((row['routed'], row['route_choice'], row['route_selected'], row['route_fallback'], row['reason_codes']),
                             (True, 'insufficient_evidence', None, False, ['insufficient_evidence']))
            self.assertNotIn('decision_correct', row)      # a decision with its correctness would publish the gold label
        self.assertEqual(rows['f8-manifest-a']['category'], 'routed')
        self.assertEqual(set(rows['f1-ledger-a']), set(rows['f8-manifest-a']))      # one key set for every routed row
        details = {d['matter_id']: d for d in lines(attempt / 'local/score-detail.jsonl')}
        for matter, gold, correct in (('f1-ledger-a', 'charge', False), ('f1-ledger-b', 'defer', True)):
            d = details[matter]
            self.assertEqual((d['grading_status'], d['choice'], d['errors'], d['selector_deferral'], d['gold_recommendation'], set(d['criteria'].values())),
                             ('scored', 'defer', [], 'insufficient_evidence', gold, {False}))
            self.assertEqual(r.outcome(d)['decision_correct'], correct)
            self.assertFalse(r.outcome(d)['all_pass'])
        outputs = {o['matter_id']: o for o in lines(attempt / 'local/candidate-outputs.jsonl')}
        self.assertEqual(outputs['f1-ledger-a'], {'matter_id': 'f1-ledger-a', 'arm': 'routed', 'repetition': 0, 'output': None, 'author_choice': None,
                                                  'choice': 'defer', 'reason_codes': ['insufficient_evidence'], 'selector_deferral': True})
        aggregate = g.aggregate(details.values())
        self.assertEqual((aggregate['all_pass']['n'], aggregate['all_pass']['missing']), (3, 0))      # deferrals stay in the denominator
        decisions = lines(attempt / 'local/route-decisions.jsonl')
        self.assertEqual([(d['matter_id'], d['action'], d['selector_abstained'], d['selected']) for d in decisions],
                         [('f1-ledger-a', 'defer', True, None), ('f1-ledger-b', 'defer', True, None), ('f8-manifest-a', 'route', False, 'lexical-eligible')])

    def test_score_keeps_selector_deferrals_as_scored_rows(self):
        with FakeSelector(lambda body: by_question(body, {'ferry': 'insufficient_authority'})) as selector:
            attempt, _, _ = self.routed(served(), roles={'selector': selector_role(selector.endpoint)})
        manifest = read_json(attempt / 'local/output-manifest.json')
        self.assertIn('local/route-decisions.jsonl', [f['path'] for f in manifest['files']])
        self.assertEqual([f['path'] for f in manifest['files']], sorted(f['path'] for f in manifest['files']))
        plan = self.plan('score', 'score', {'suite': 'suite/suite.lock.json', 'output_manifest': str(attempt / 'local/output-manifest.json')})
        (job,) = plan['jobs']
        # The plan records resolved paths; the temporary directory can be an 8.3 short name on Windows.
        self.assertIn(str((attempt / 'local/route-decisions.jsonl').resolve()), {f['path'] for f in job['input_files']})
        scored = self.run_job(job, 'score')
        source, rows = lines(attempt / 'requests.jsonl'), lines(scored / 'requests.jsonl')
        self.assertEqual(len(rows), len(source))
        self.assertEqual(sum(x['quality_check_applicable'] for x in rows), sum(x['quality_check_applicable'] for x in source))
        keys = ('task_id', 'arm', 'category', 'routed', 'route_choice', 'route_selected', 'route_fallback', 'route_confidence', 'router_s',
                'choice', 'forced_defer', 'quality_pass', 'criteria_passed', 'status')
        self.assertEqual([tuple(x[k] for k in keys) for x in rows], [tuple(x[k] for k in keys) for x in source])
        deferral = next(x for x in rows if x['category'] == 'routed-defer')
        self.assertEqual((deferral['task_id'], deferral['execution_kind'], deferral['reason_codes']), ('f8-manifest-a', 'score-only', ['insufficient_authority']))
        details = {d['matter_id']: d for d in lines(scored / 'local/score-detail.jsonl')}
        self.assertEqual((details['f8-manifest-a']['errors'], details['f8-manifest-a']['selector_deferral']), ([], 'insufficient_authority'))
        self.assertNotIn('schema_invalid', json.dumps(details['f8-manifest-a']))
        self.assertEqual(lines(scored / 'local/score-detail.jsonl'), lines(attempt / 'local/score-detail.jsonl'))
        # A routed manifest without its route-decision file, or an unrouted one with it, is refused.
        files = [f for f in manifest['files'] if f['path'] != 'local/route-decisions.jsonl']
        (attempt / 'local/output-manifest.json').write_text(json.dumps({**manifest, 'files': files}), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'Output manifest does not list the expected files'):
            legal.validate({'suite': str(self.lock), 'output_manifest': str(attempt / 'local/output-manifest.json')}, ROOT, 'score')

    def test_candidate_removal_falls_back_deterministically(self):
        r = routing()
        policy = {'category_models': {'lexical': 'lexical-eligible', 'none': 'no-context'}, 'fallback': 'no-context'}
        messages = [{'role': 'user', 'content': 'QUESTION about a ferry'}]
        router = {'kind': 'category', 'default_category': 'lexical', 'keywords': {'none': ['ferry']}}
        full = r.route(router, messages, policy, {'no-context': {}, 'lexical-eligible': {}}, ['no-context', 'lexical-eligible'])
        self.assertEqual((full['action'], full['selected'], full['fallback_used'], full['reason_codes']), ('route', 'no-context', False, []))
        for _ in range(2):      # the same answer every time
            removed = r.route(router, messages, {**policy, 'fallback': 'lexical-eligible'}, {'lexical-eligible': {}}, ['lexical-eligible'])
            self.assertEqual((removed['choice'], removed['action'], removed['selected'], removed['fallback_used'], removed['selector_abstained'],
                              removed['reason_codes']), ('none', 'route', 'lexical-eligible', True, False, ['candidate_unavailable']))
        self.assertEqual(set(removed), {'choice', 'selected', 'action', 'selector_abstained', 'fallback_used', 'reason_codes', 'router_s', 'confidence',
                                        'error_type'})
        # In a job: the fixed choice names an arm that is not a candidate of this job.
        fixed = {'router': {'kind': 'fixed', 'choice': 'lexical'}, 'policy': {'fallback': 'lexical-eligible'}, 'calibration': None}
        attempt, _, requests = self.routed(fixed)
        rows = lines(attempt / 'requests.jsonl')
        self.assertEqual(len(requests), 3)
        self.assertEqual({(x['route_selected'], x['route_fallback'], x['category'], tuple(c for c in x['reason_codes'] if c in r.REASONS)) for x in rows},
                         {('lexical-eligible', True, 'routed', ('candidate_unavailable',))})
        # A router that fails is a router error and takes the fallback; the row names the exception class only.
        broken = r.route({'kind': 'unknown'}, messages, policy, {'no-context': {}}, ['no-context'])
        self.assertEqual((broken['selected'], broken['fallback_used'], broken['reason_codes'], broken['error_type']),
                         ('no-context', True, ['router_error'], 'ValueError'))

    def test_missing_confidence_takes_the_fallback(self):
        r = routing()
        candidates = {'no-context': {}, 'lexical-eligible': {}}
        eligible = list(candidates)
        messages = [{'role': 'user', 'content': 'QUESTION about a ferry'}]
        with FakeSelector(lambda body: {'choice': 'none'}) as bare, FakeSelector(lambda body: by_question(body, {'ferry': 'none'}, 0.4)) as low, \
                FakeSelector(lambda body: by_question(body, {'ferry': 'none'}, 0.9)) as high:
            def router(fake):
                return r.router_for(served(), {'selector': selector_role(fake.endpoint)})
            allowed = frozenset([bare.endpoint, low.endpoint, high.endpoint])
            for policy in ({'require_confidence': True}, {'abstain_threshold': 0.6}):
                with self.subTest(policy=policy):
                    result = r.route(router(bare), messages, {**served(**policy)['policy']}, candidates, eligible, allowed)
                    self.assertEqual((result['choice'], result['selected'], result['fallback_used'], result['selector_abstained'], result['confidence'],
                                      result['reason_codes'], result['action']),
                                     ('none', 'lexical-eligible', True, True, None, ['missing_confidence'], 'route'))
            plain = r.route(router(bare), messages, served()['policy'], candidates, eligible, allowed)
            self.assertEqual((plain['selected'], plain['fallback_used'], plain['reason_codes']), ('no-context', False, []))
            below = r.route(router(low), messages, served(abstain_threshold=0.6)['policy'], candidates, eligible, allowed)
            self.assertEqual((below['selected'], below['fallback_used'], below['confidence'], below['reason_codes'], below['selector_abstained']),
                             ('lexical-eligible', True, 0.4, ['below_threshold'], True))
            above = r.route(router(high), messages, served(abstain_threshold=0.6)['policy'], candidates, eligible, allowed)
            self.assertEqual((above['selected'], above['fallback_used'], above['confidence'], above['reason_codes']), ('no-context', False, 0.9, []))

    def test_no_eligible_candidate_defers(self):
        r = routing()
        self.assertEqual(retrieval.available_arms(['dense', 'no-context'], {'backend': 'memory'}),
                         {'dense': 'capability_absent_embedding', 'no-context': None})
        selector = {'router': {'kind': 'fixed', 'choice': 'dense'}, 'policy': {'fallback': 'dense'}, 'calibration': None}
        attempt, _, requests = self.routed(selector, arms=('dense', 'no-context'))
        self.assertEqual(requests, [])
        rows = lines(attempt / 'requests.jsonl')
        self.assertEqual({(x['category'], x['route_selected'], tuple(x['reason_codes'])) for x in rows},
                         {('routed-defer', None, ('ineligible_candidate', 'no_eligible_candidate'))})
        for d in lines(attempt / 'local/score-detail.jsonl'):
            self.assertEqual(d['selector_deferral'], 'no_eligible_candidate')
            self.assertIsNone(r.outcome(d)['decision_correct'])
        self.assertEqual(r.route({'kind': 'fixed', 'choice': 'dense'}, [], {'fallback': 'dense'}, {}, [])['reason_codes'],
                         ['candidate_unavailable', 'no_eligible_candidate'])

    def test_router_rows_hold_hashes_not_inputs(self):
        r = routing()
        canary = 'Canary seventeen orange lanterns hum'

        def edit(matters, corpus, rubric):
            for m in matters['matters']:
                if m['matter_id'] == 'f8-manifest-a':
                    m['question'] = m['question'] + ' ' + canary
        self.lock = subset_suite(self.path / 'canary', self.MATTERS, edit)
        self.suite = contracts.load_suite(self.lock)
        with FakeSelector(lambda body: by_question(body, {'ferry': 'none'}, 0.9)) as selector, FakeGenerator(respond=self.respond) as fake:
            parameters = {'suite': 'canary/suite.lock.json', 'arms': ['no-context', 'lexical-eligible'], 'selector': served(),
                          'roles': {'generator': generator(fake.endpoint), 'selector': selector_role(selector.endpoint)}}
            (job,) = self.plan('canary', 'workflow', parameters)['jobs']
            attempt = self.run_job(job, 'canary')
        self.assertIn(canary, selector.requests[-1]['state']['messages'][0]['content'])      # the selector's own input
        checked = [p for p in attempt.rglob('*') if p.is_file() and 'memos' not in p.parts]      # a memo renders the question for review
        self.assertIn(attempt / 'local/route-decisions.jsonl', checked)
        for path in checked:
            self.assertNotIn(canary, path.read_text(encoding='utf-8'), path.name)
        matters = {m['matter_id']: m for m in self.suite['matters']['matters']}
        decisions = lines(attempt / 'local/route-decisions.jsonl')
        self.assertEqual({frozenset(d) for d in decisions}, {frozenset({'matter_id', 'repetition', 'messages_sha256', 'choice', 'selected', 'action',
                                                                        'selector_abstained', 'fallback_used', 'reason_codes', 'confidence', 'router_s'})})
        for d in decisions:
            self.assertEqual(d['messages_sha256'], digest(r.route_messages(matters[d['matter_id']])))
        self.assertEqual(next(d for d in decisions if d['matter_id'] == 'f8-manifest-a')['confidence'], 0.9)

    def test_thresholds_come_from_a_pinned_calibration_file(self):
        r = routing()
        packets, smoke = contracts.load_suite(PACKETS), contracts.load_suite(SMOKE)
        roles = {'generator': generator(), 'selector': selector_role()}
        honest, calibration = honest_calibration(self.path / 'calibration.json')
        threshold, other = honest['abstain_threshold'], 0.9 if honest['abstain_threshold'] == 0.5 else 0.5
        attempts = {side: calibration[side] for side in ('routed', 'fallback')}

        def plan(selector, plan_roles=roles, name='calibrated'):
            return self.plan(name, 'generation', {'suite': str(SMOKE), 'arms': ['no-context', 'lexical-eligible'], 'roles': plan_roles, 'selector': selector})
        (job,) = plan({**served(abstain_threshold=threshold), 'calibration': calibration})['jobs']
        recorded = {f['path'] for f in job['input_files']}
        self.assertIn(str((self.path / 'calibration.json').resolve()), recorded)
        self.assertTrue({str(p) for p in contracts.pinned_files(PACKETS)} <= recorded)
        pinned = workflow().inputs(job['parameters'], smoke, ROOT, 'generation')
        self.assertEqual(pinned[:len(contracts.pinned_files(PACKETS))], [str(p) for p in contracts.pinned_files(PACKETS)])
        for attempt in calibration_attempts():      # both calibration attempts: every file their manifests list, and result.json
            attempt = attempt.resolve()
            listed ={str(attempt / f['path']) for f in read_json(attempt / 'local/output-manifest.json')['files']} | {str(attempt / 'result.json')}
            self.assertTrue(listed <= set(pinned))
            self.assertTrue(listed | {str(attempt / 'local/output-manifest.json')} <= recorded)
        self.assertEqual(workflow().inputs({**job['parameters'], 'selector': CATEGORY}, None, ROOT, 'generation'), [])
        for selector, plan_roles, message in (
                (served(abstain_threshold=threshold), roles, 'A threshold needs a pinned calibration file'),
                ({**CATEGORY, 'policy': {**CATEGORY['policy'], 'abstain_threshold': threshold}, 'calibration': calibration}, {'generator': generator()},
                 'A threshold needs a selector that reports probabilities'),
                ({**served(abstain_threshold=other), 'calibration': calibration}, roles, 'Calibration record does not match the policy threshold'),
                (CATEGORY, roles, 'Only a served selector has a selector role')):
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                plan(selector, plan_roles)
        with self.assertRaisesRegex(ValueError, 'Only a served selector has a selector role'):      # a selector role without a selector
            self.plan('no-selector', 'generation', {'suite': str(SMOKE), 'arms': ['no-context'], 'roles': roles})
        # A record calibrated on the evaluation suite.
        r.write_calibration(calibration_record(smoke), self.path / 'on-smoke.json')
        with self.assertRaisesRegex(ValueError, 'Calibration record does not match its suite'):
            plan({**served(abstain_threshold=0.5), 'calibration': {'calibration_file': 'on-smoke.json', 'suite': str(PACKETS), **attempts}})
        with self.assertRaisesRegex(ValueError, 'Threshold was calibrated on evaluation data'):
            plan({**served(abstain_threshold=0.5), 'calibration': {'calibration_file': 'on-smoke.json', 'suite': str(SMOKE), **attempts}})
        # A suite that shares a family or a near duplicate with the evaluation suite: refused by the split check, and at plan
        # time already because a calibration suite must be an approved suite.
        for name, rename in (('family', False), ('near', True)):
            with self.subTest(overlap=name):
                lock = self.copy_with_split(name, rename)
                copy_suite = contracts.load_suite(lock)
                r.write_calibration(calibration_record(copy_suite), self.path / f'{name}.json')
                with self.assertRaisesRegex(ValueError, 'Threshold was calibrated on evaluation data'):
                    r.check_threshold(read_json(self.path / f'{name}.json'), smoke, copy_suite)
                with self.assertRaisesRegex(ValueError, 'Export is limited to approved fixture suites'):
                    plan({**served(abstain_threshold=0.5), 'calibration': {'calibration_file': f'{name}.json', 'suite': str(lock), **attempts}})
                audit = retrieval.audit_splits(copy_suite, smoke)
                self.assertTrue(audit['near_duplicates'] if rename else audit['shared_families'])
        # The record's own family list is never trusted alone.
        record = read_json(self.path / 'family.json')
        record['families'] = ['p9-none']
        with self.assertRaisesRegex(ValueError, 'Threshold was calibrated on evaluation data'):
            r.check_threshold(record, smoke, contracts.load_suite(self.copy_with_split('family-again', False)))
        r.check_threshold(read_json(self.path / 'calibration.json'), smoke, packets)
        # Each finding of the split audit refuses on its own (the smoke copies above share amendment pairs as well).
        clean = {'shared_families': [], 'shared_amendment_pairs': [], 'near_duplicates': []}
        for key, value in (('shared_families', ['p1-quay']), ('shared_amendment_pairs', ['vho-9-2']), ('near_duplicates', [['p1-quay-a', 'f1-ledger-a', 0.9]])):
            with self.subTest(audit=key), patch.object(retrieval, 'audit_splits', return_value={**clean, key: value}):
                with self.assertRaisesRegex(ValueError, 'Threshold was calibrated on evaluation data'):
                    r.check_threshold(read_json(self.path / 'calibration.json'), smoke, packets)
        with patch.object(retrieval, 'audit_splits', return_value=clean) as audit:
            r.check_threshold(read_json(self.path / 'calibration.json'), smoke, packets)
        audit.assert_called_once_with(packets, smoke)      # the audit always runs, on the loaded calibration suite

    def copy_with_split(self, name, rename_families):
        """A relocked copy of two smoke matters as another split; with `rename_families` the family ids differ but the text
        is the same (a near duplicate)."""
        directory = self.path / ('split-' + name)
        def edit(matters, corpus, rubric):      # noqa: E306
            if rename_families:
                for m in matters['matters']:
                    m['family_id'] = 'q' + m['family_id']
        lock = subset_suite(directory, ('f1-ledger-a', 'f1-ledger-b'), edit)
        value = read_json(lock)
        write_json(lock, contracts.make_lock(directory, benchmark_id=value['benchmark_id'], revision=value['revision'], split_id='calibration-copy',
                                             data_class=value['data_class'], jurisdiction_profile=value['jurisdiction_profile'],
                                             manifests={'matters': 'matters.json', 'corpus': 'corpus.json', 'rubric': 'rubric.json'}))
        return lock

    def test_served_selector_is_a_local_role_on_the_allowlist(self):
        r = routing()
        parameters = {'suite': str(SMOKE), 'arms': ['no-context', 'lexical-eligible'], 'selector': served()}
        with self.assertRaisesRegex(ValueError, 'A served selector needs the selector role'):
            self.plan('no-role', 'generation', {**parameters, 'roles': {'generator': generator()}})
        for network in ({'kind': 'hosted', 'allowed_hosts': ['api.example.com']}, {'kind': 'remote'}):
            with self.subTest(network=network), self.assertRaisesRegex(ValueError, 'Legal roles must be local: selector'):
                self.plan('hosted', 'generation', {**parameters, 'roles': {'generator': generator(), 'selector': selector_role(network=network)}})
        with FakeSelector(lambda body: {'choice': 'lexical'}) as fake:
            with self.assertRaisesRegex(ValueError, 'Endpoint is not on the job allowlist'):
                r.route(r.router_for(served(), {'selector': selector_role(fake.endpoint)}), [{'role': 'user', 'content': 'q'}], served()['policy'],
                        {'lexical-eligible': {}}, ['lexical-eligible'], frozenset())
            self.assertEqual(fake.requests, [])
            role = selector_role(fake.endpoint, accelerator='gpu')
            self.assertEqual(r.router_for(served(), {'selector': role}),
                             {'kind': 'systemone', 'model': 'fake-router', 'endpoint': fake.endpoint, 'instructions': served()['router']['instructions'],
                              'criteria': CRITERIA, 'timeout_s': 5, 'api_key_env': None})
            attempt, job, _ = self.routed(served(), roles={'selector': selector_role(fake.endpoint)})
        self.assertEqual(len(fake.requests), 3)
        self.assertIn(fake.endpoint, profiles.allowed_endpoints(job['parameters']['roles']))
        metadata = read_json(attempt / 'metadata.json')
        self.assertEqual(metadata['roles']['selector'], profiles.public_role(job['parameters']['roles']['selector'], job['input_files']))
        self.assertEqual(set(read_json(attempt / 'local/output-manifest.json')['role_digests']), {'generator', 'selector'})
        self.assertEqual(metadata['selector']['router_kind'], 'systemone')
        self.assertNotIn(fake.endpoint, json.dumps(metadata))

    def test_selector_labels_cannot_be_path_keys(self):
        from llm_eval.orchestration import planner
        self.assertTrue({'serving_profile', 'calibration_file'} <= planner.PATH_KEYS)
        # Shared edit H10: plans of the existing experiments (offload and routing examples, routing smoke) are byte-identical
        # with and without the two new path keys, resources and setup inputs included.
        old = planner.PATH_KEYS - {'serving_profile', 'calibration_file'}
        for campaign in (ROOT / 'campaigns/routing-smoke.json', ROOT / 'configs/examples/raider-windows/campaign.json',
                         ROOT / 'configs/examples/raider-wsl/campaign.json'):
            with self.subTest(campaign=campaign.name):
                new = compile_campaign(campaign, ROOT)
                with patch.object(planner, 'PATH_KEYS', old):
                    before = compile_campaign(campaign, ROOT)
                self.assertEqual(json.dumps(before, sort_keys=True), json.dumps(new, sort_keys=True))
        roles = {'generator': generator(), 'selector': selector_role()}
        for label in ('suite', 'calibration_file', 'serving_profile'):
            with self.subTest(criteria=label):
                selector = served()
                selector['router']['criteria'][label] = 'A label that the planner would rewrite into a path'
                with self.assertRaisesRegex(ValueError, 'A selector label cannot be a path key: ' + label):
                    self.plan('labels', 'generation', {'suite': str(SMOKE), 'arms': ['no-context', 'lexical-eligible'], 'roles': roles, 'selector': selector})
            with self.subTest(category_models=label):
                selector = copy.deepcopy(CATEGORY)
                selector['policy']['category_models'][label] = 'no-context'
                with self.assertRaisesRegex(ValueError, 'A selector label cannot be a path key: ' + label):
                    routing().validate_selector(selector, ['no-context', 'lexical-eligible'], {'generator': generator()}, contracts.load_suite(SMOKE))
        for bad, message in (({**CATEGORY, 'extra': 1}, 'Unknown fields'), ({**CATEGORY, 'policy': {**CATEGORY['policy'], 'fallback': 'dense'}}, 'fallback'),
                             ({**CATEGORY, 'policy': {**CATEGORY['policy'], 'category_models': {'lexical': 'reranked'}}}, 'category_models'),
                             ({**CATEGORY, 'policy': {k: v for k, v in CATEGORY['policy'].items() if k != 'fallback'}}, 'Missing fields: fallback'),
                             ({**CATEGORY, 'policy': {**CATEGORY['policy'], 'require_confidence': 'yes'}}, 'require_confidence'),
                             ({**CATEGORY, 'policy': {**CATEGORY['policy'], 'abstain_threshold': 1.5}}, 'abstain_threshold')):
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                routing().validate_selector(bad, ['no-context', 'lexical-eligible'], {'generator': generator()}, contracts.load_suite(SMOKE))
        missing = served()
        del missing['router']['criteria']['insufficient_authority']
        with self.assertRaisesRegex(ValueError, 'insufficient'):
            routing().validate_selector(missing, ['no-context'], {'selector': selector_role()}, contracts.load_suite(SMOKE))
        mapped = served()
        mapped['policy']['category_models']['insufficient_evidence'] = 'no-context'
        with self.assertRaisesRegex(ValueError, 'insufficient'):
            routing().validate_selector(mapped, ['no-context', 'lexical-eligible'], {'selector': selector_role()}, contracts.load_suite(SMOKE))
        with self.assertRaisesRegex(ValueError, 'The reference arm cannot be routed'):
            routing().validate_selector(CATEGORY, ['no-context', 'lexical-eligible', 'reference'], {}, contracts.load_suite(SMOKE))

    def test_risk_versus_coverage_is_reported_per_threshold(self):
        rows = [{'confidence': 0.9, 'decision_correct': True, 'false_charge': False, 'dangerous_commitment': False},
                {'confidence': 0.8, 'decision_correct': False, 'false_charge': True, 'dangerous_commitment': False},
                {'confidence': 0.7, 'decision_correct': True, 'false_charge': False, 'dangerous_commitment': False},
                {'confidence': 0.4, 'decision_correct': False, 'false_charge': False, 'dangerous_commitment': True},
                {'confidence': None, 'decision_correct': True, 'false_charge': False, 'dangerous_commitment': False}]
        self.assertEqual(routing().risk_coverage(rows, [0.95, 0.5, 0.7]), [
            {'threshold': 0.5, 'tasks': 5, 'covered': 3, 'coverage': 0.6, 'errors': 1, 'risk': 0.333333, 'unsafe_commitments': 1, 'unsafe_rate': 0.333333},
            {'threshold': 0.7, 'tasks': 5, 'covered': 3, 'coverage': 0.6, 'errors': 1, 'risk': 0.333333, 'unsafe_commitments': 1, 'unsafe_rate': 0.333333},
            {'threshold': 0.95, 'tasks': 5, 'covered': 0, 'coverage': 0.0, 'errors': 0, 'risk': None, 'unsafe_commitments': 0, 'unsafe_rate': None}])
        self.assertEqual(routing().risk_coverage([], [0.5]), [{'threshold': 0.5, 'tasks': 0, 'covered': 0, 'coverage': None, 'errors': 0, 'risk': None,
                                                              'unsafe_commitments': 0, 'unsafe_rate': None}])

    def test_calibration_is_deterministic_and_ties_take_the_lower_threshold(self):
        r = routing()
        packets = contracts.load_suite(PACKETS)
        # Totals: 0.5 -> 0 + 0.3 + 0.0 + 0 = 0.3; 0.7 -> 0 + 0.1 + 0.2 + 0 = 0.3 (a tie as decimal fractions; a float sum, or
        # Fraction of a binary float, would favour 0.7).
        rows = [{'task_id': 'p1-quay-a', 'family_id': 'p1-quay', 'confidence': 0.9, 'quality_routed': 0.0, 'quality_fallback': 0.0},
                {'task_id': 'p1-quay-b', 'family_id': 'p1-quay', 'confidence': 0.6, 'quality_routed': 0.3, 'quality_fallback': 0.1},
                {'task_id': 'p2-kiln-a', 'family_id': 'p2-kiln', 'confidence': 0.6, 'quality_routed': 0.0, 'quality_fallback': 0.2},
                {'task_id': 'p2-kiln-b', 'family_id': 'p2-kiln', 'confidence': None, 'quality_routed': 0.0, 'quality_fallback': 0.0}]
        for row in rows:
            row.update(action='route', route_reason=None, decision_correct=True, false_charge=False, dangerous_commitment=False, critical_errors=0)
        lineage = calibration_lineage()
        self.assertGreater(0.0 + 0.1 + 0.2 + 0.0, 0.0 + 0.3 + 0.0 + 0.0)
        self.assertGreater(Fraction(0.1) + Fraction(0.2), Fraction(0.3))
        record = r.calibrate(rows, [0.7, 0.5, 0.95], packets, lineage)
        self.assertEqual({k: record[k] for k in lineage}, lineage)
        self.assertEqual((record['schema_version'], record['kind'], record['abstain_threshold'], record['split_id'], record['suite_lock_sha256'],
                          record['families']), (1, 'legal-routing-calibration', 0.5, 'calibration', packets['lock_sha256'], ['p1-quay', 'p2-kiln']))
        self.assertEqual([x['threshold'] for x in record['risk_coverage']], [0.5, 0.7, 0.95])
        self.assertEqual(r.calibrate(list(reversed(rows)), [0.95, 0.5, 0.7], packets, lineage), record)
        sha = r.write_calibration(record, self.path / 'calibration.json')
        self.assertEqual(sha, sha256_file(self.path / 'calibration.json'))
        self.assertEqual((self.path / 'calibration.json').read_bytes(), (json.dumps(record, indent=2, sort_keys=True) + '\n').encode())
        for bad in ([0], [1.5], [True], []):
            with self.subTest(thresholds=bad), self.assertRaises(ValueError):
                r.calibrate(rows, bad, packets, lineage)
        # From attempts: a routed and a fallback attempt on the calibration suite, through the command.
        self.lock = PACKETS
        self.suite = packets
        with FakeSelector(lambda body: by_question(body, {'kiln': 'none'}, 0.8)) as selector, FakeGenerator(respond=self.respond) as fake:
            gen = generator(fake.endpoint)
            (routed,) = self.plan('cal-routed', 'generation', {'suite': str(PACKETS), 'arms': ['no-context', 'lexical-eligible'], 'selector': served(),
                                                               'roles': {'generator': gen, 'selector': selector_role(selector.endpoint)}})['jobs']
            (fallback,) = self.plan('cal-fallback', 'generation', {'suite': str(PACKETS), 'arms': ['lexical-eligible'], 'roles': {'generator': gen}})['jobs']
            (other,) = self.plan('cal-other', 'generation', {'suite': str(PACKETS), 'arms': ['lexical-eligible'],
                                                            'roles': {'generator': {**gen, 'model_revision': 'r2'}}})['jobs']
            routed, fallback, other = (self.run_job(j, n) for j, n in ((routed, 'cal-routed'), (fallback, 'cal-fallback'), (other, 'cal-other')))
        calibration_rows = r.calibration_rows(routed, fallback, 'lexical-eligible')
        self.assertEqual([x['task_id'] for x in calibration_rows], ['p1-quay-a', 'p1-quay-b', 'p2-kiln-a', 'p2-kiln-b'])
        self.assertEqual({x['confidence'] for x in calibration_rows}, {0.8})
        self.assertEqual(set(calibration_rows[0]), {'task_id', 'family_id', 'confidence', 'action', 'route_reason', 'quality_routed', 'quality_fallback',
                                                    'decision_correct', 'false_charge', 'dangerous_commitment', 'critical_errors'})
        self.assertEqual({(x['action'], x['route_reason']) for x in calibration_rows}, {('route', None)})
        with self.assertRaisesRegex(ValueError, 'The fallback attempt must run the routed policy fallback'):
            r.calibration_rows(routed, fallback, 'no-context')
        with self.assertRaisesRegex(ValueError, 'Calibration attempts are not comparable'):
            r.calibration_rows(routed, other, 'lexical-eligible')
        with patch('sys.stdout', io.StringIO()):
            self.assertEqual(r.main(['calibrate', '--suite', str(PACKETS), '--routed-attempt', str(routed), '--fallback-attempt', str(fallback),
                                     '--fallback-arm', 'lexical-eligible', '--thresholds', '0.5,0.9', '--output', str(self.path / 'cli.json')]), 0)
        cli = read_json(self.path / 'cli.json')
        self.assertEqual((cli['suite_lock_sha256'], cli['families'], [x['covered'] for x in cli['risk_coverage']]),
                         (packets['lock_sha256'], ['p1-quay', 'p2-kiln'], [4, 0]))
        job = read_json(routed / 'job.json')
        self.assertEqual({k: cli[k] for k in lineage}, {
            'selector_sha256': r.selector_identity(job['parameters']['selector'], job['parameters']['roles']),
            'routed_output_manifest_sha256': sha256_file(routed / 'local/output-manifest.json'),
            'fallback_output_manifest_sha256': sha256_file(fallback / 'local/output-manifest.json'),
            'generator_sha256': profiles.profile_digest(job['parameters']['roles']['generator'], job['input_files'])})


def calibration_attempts():
    """A routed attempt (served fixture selector, threshold 0) and an unrouted attempt of its fallback arm on the packet
    calibration suite, built once. Fixture replies only."""
    if 'calibration' not in _SHARED:
        directory = Path(tempfile.mkdtemp())
        unittest.addModuleCleanup(shutil.rmtree, directory, True)
        packets = contracts.load_suite(PACKETS)

        def respond(body):
            content = body['messages'][1]['content']
            matter = next(m for m in packets['matters']['matters'] if 'MATTER ' + m['matter_id'] + '\n' in content)
            output = fixture.draft(matter, packets['corpus'])
            listed = set(re.findall(r'^\[([a-z0-9-]+@[0-9]+)\] ', content, re.M))
            output['claims'] = [c for c in output['claims'] if c['authority_id'] + '@' + c['version'] in listed]
            return json.dumps(output)
        attempts = []
        with FakeSelector(lambda body: by_question(body, {'kiln': 'none'}, 0.8)) as selector, FakeGenerator(respond=respond) as fake, NO_GPU:
            for name, parameters in (('cal-routed', {'arms': ['no-context', 'lexical-eligible'], 'selector': served(),
                                                     'roles': {'generator': generator(fake.endpoint), 'selector': selector_role(selector.endpoint)}}),
                                     ('cal-fallback', {'arms': ['lexical-eligible'], 'roles': {'generator': generator(fake.endpoint)}})):
                job = job_for(PACKETS, parameters, job_id='legal-' + name)
                out = directory / name
                out.mkdir()
                atomic_json(out / 'job.json', job)
                result = legal.execute(job, out, ROOT)
                atomic_json(out / 'result.json', {**result, 'attempt_id': out.name})
                attempts.append(out)
        _SHARED['calibration'] = tuple(attempts)
    return _SHARED['calibration']


def honest_calibration(path, thresholds=(0.5, 0.9), edit=None):
    """(record, calibration block) of the shared calibration attempts, the record written to `path`."""
    r = routing()
    routed, fallback = calibration_attempts()
    rows = r.calibration_rows(routed, fallback, 'lexical-eligible')
    record = r.calibrate(rows, list(thresholds), contracts.load_suite(PACKETS), r.calibration_lineage(routed, fallback, 'lexical-eligible'))
    if edit:
        edit(record)
    write_json(path, record)
    return record, {'calibration_file': str(path), 'suite': str(PACKETS), 'routed': {'output_manifest': str(routed / 'local/output-manifest.json')},
                    'fallback': {'output_manifest': str(fallback / 'local/output-manifest.json')}}


def calibration_lineage(**changes):
    return {'selector_sha256': routing().selector_identity(served(), {'generator': generator(), 'selector': selector_role()}),
            'routed_output_manifest_sha256': 'a' * 64, 'fallback_output_manifest_sha256': 'b' * 64,
            'generator_sha256': profiles.bound_digest(generator()), **changes}


def calibration_record(suite, threshold=0.5, **lineage):
    """A calibration record over every matter of `suite`, for the served fixture selector and generator. Fixture rows."""
    rows = [{'task_id': m['matter_id'], 'family_id': m['family_id'], 'confidence': 0.9, 'action': 'route', 'route_reason': None,
             'quality_routed': 1.0, 'quality_fallback': 0.5, 'decision_correct': True, 'false_charge': False, 'dangerous_commitment': False,
             'critical_errors': 0} for m in sorted(suite['matters']['matters'], key=lambda m: m['matter_id'])]
    return routing().calibrate(rows, [threshold], suite, calibration_lineage(**lineage))


# 4. Routing suite export and replay -----------------------------------------------------------------------------------

_SHARED = {}


def smoke_attempt():
    """One generation attempt over the shipped smoke suite with two arms, built once for the replay tests."""
    if 'attempt' not in _SHARED:
        directory = Path(tempfile.mkdtemp())
        unittest.addModuleCleanup(shutil.rmtree, directory, True)
        _SHARED['attempt'] = generation_attempt(directory, 'smoke-source', SMOKE, ('no-context', 'lexical-eligible'))
    return _SHARED['attempt']


def generation_attempt(directory, name, lock, arms, overrides=None, parse_retries=1):
    suite = contracts.load_suite(lock)

    def respond(body):
        content = body['messages'][1]['content']
        matter = next(m for m in suite['matters']['matters'] if 'MATTER ' + m['matter_id'] + '\n' in content)
        if overrides and matter['matter_id'] in overrides:
            return overrides[matter['matter_id']]
        output = fixture.draft(matter, suite['corpus'])
        listed = set(re.findall(r'^\[([a-z0-9-]+@[0-9]+)\] ', content, re.M))
        output['claims'] = [c for c in output['claims'] if c['authority_id'] + '@' + c['version'] in listed]
        return json.dumps(output)
    with FakeGenerator(respond=respond) as fake, NO_GPU:
        job = job_for(lock, {'arms': list(arms), 'roles': {'generator': generator(fake.endpoint)}, 'parse_retries': parse_retries}, job_id='legal-' + name)
        out = Path(directory) / name
        out.mkdir(parents=True)
        atomic_json(out / 'job.json', job)
        result = legal.execute(job, out, ROOT)
        atomic_json(out / 'result.json', {**result, 'attempt_id': out.name})
    return out


CANDIDATE = {'model': 'fake-chat', 'model_revision': 'r1', 'platform': 'fake-chat', 'backend_version': '1.0', 'protocol': 'openai',
             'context_tokens': 8192, 'quantization': None, 'template_sha256': None}


def candidates(*arms):
    return {arm: dict(CANDIDATE) for arm in arms}


class ReplayCase(TempCase):
    def replay(self, arms=('no-context', 'lexical-eligible'), attempts=None):
        """The `export` and `replay` commands over the shipped smoke suite: (routing suite, manifest, sidecar, candidates file)."""
        r = routing()
        suite_path, manifest_path, candidates_path = self.path / 'routing-suite.json', self.path / 'replay.json', self.path / 'candidates.json'
        write_json(candidates_path, candidates(*arms))
        argv = ['replay', '--suite', str(SMOKE), '--routing-suite', str(suite_path), '--candidates', str(candidates_path), '--output', str(manifest_path)]
        for attempt in attempts or [smoke_attempt()]:
            argv += ['--attempt', str(attempt)]
        with patch('sys.stdout', io.StringIO()):
            self.assertEqual(r.main(['export', '--suite', str(SMOKE), '--output', str(suite_path)]), 0)
            self.assertEqual(r.main(argv), 0)
        return suite_path, manifest_path, self.path / 'replay.provenance.json', candidates_path


class ReplayTests(ReplayCase):
    def test_exported_suite_holds_route_time_inputs_and_loads_in_the_routing_experiment(self):
        from llm_eval.runner import load_suite as load_task_suite
        r = routing()
        sha = r.export_suite(SMOKE, self.path / 'routing-suite.json')
        data = (self.path / 'routing-suite.json').read_bytes()
        self.assertNotIn(b'\r', data)
        suite = load_task_suite(self.path / 'routing-suite.json')
        self.assertEqual(sha, digest(suite))
        smoke = contracts.load_suite(SMOKE)
        self.assertEqual(suite, r.route_tasks(smoke))
        self.assertEqual((set(suite), suite['benchmark'], suite['category']), ({'benchmark', 'category', 'tasks'}, 'legal-routing', 'legal'))
        self.assertEqual([t['id'] for t in suite['tasks']], sorted(m['matter_id'] for m in smoke['matters']['matters']))
        self.assertEqual({frozenset(t) for t in suite['tasks']}, {frozenset({'id', 'category', 'messages'})})
        matters = {m['matter_id']: m for m in smoke['matters']['matters']}
        for task in suite['tasks']:
            self.assertEqual(task['messages'], r.route_messages(matters[task['id']]))
        text = data.decode()
        for leaked in ('expected_choice', 'recommendation', 'charge"', 'scenario', 'quality', 'gold', 'rubric', 'span'):
            self.assertNotIn(leaked, text)
        for m in smoke['matters']['matters']:
            for span in (span for s in m['sources'] for span in s['spans']):
                self.assertNotIn(span['text'], text)

    def test_exports_need_an_approved_fixture_suite(self):
        r = routing()
        directory = self.path / 'copy'
        shutil.copytree(SMOKE.parent, directory)
        lock = read_json(directory / 'suite.lock.json')
        write_json(directory / 'suite.lock.json', contracts.make_lock(
            directory, benchmark_id=lock['benchmark_id'], revision='operator-copy-1', split_id=lock['split_id'], data_class='public-synthetic',
            jurisdiction_profile=lock['jurisdiction_profile'], manifests={'matters': 'matters.json', 'corpus': 'corpus.json', 'rubric': 'rubric.json'}))
        copy_lock = directory / 'suite.lock.json'
        self.assertEqual(contracts.load_suite(copy_lock)['lock']['data_class'], 'public-synthetic')
        for call in (lambda: r.export_suite(copy_lock, self.path / 'x.json'), lambda: profiles.export_workload(copy_lock, self.path / 'y.json')):
            with self.assertRaisesRegex(ValueError, 'Export is limited to approved fixture suites'):
                call()
        self.assertFalse((self.path / 'x.json').exists() or (self.path / 'y.json').exists())
        attempt = generation_attempt(self.path / 'attempts', 'copy-source', copy_lock, ('no-context', 'lexical-eligible'))
        write_json(self.path / 'candidates.json', candidates('no-context', 'lexical-eligible'))
        r.export_suite(SMOKE, self.path / 'routing-suite.json')
        stderr = io.StringIO()
        with patch('sys.stderr', stderr):
            self.assertEqual(r.main(['replay', '--suite', str(copy_lock), '--routing-suite', str(self.path / 'routing-suite.json'), '--attempt', str(attempt),
                                     '--candidates', str(self.path / 'candidates.json'), '--output', str(self.path / 'replay.json')]), 2)
            self.assertIn('Export is limited to approved fixture suites', stderr.getvalue())
            self.assertEqual(r.main(['replay', '--suite', str(SMOKE), '--routing-suite', str(self.path / 'routing-suite.json'), '--attempt', str(attempt),
                                     '--candidates', str(self.path / 'candidates.json'), '--output', str(self.path / 'replay.json')]), 2)
            self.assertIn('Stale replay scores', stderr.getvalue())
        self.assertFalse((self.path / 'replay.json').exists())
        write_json(self.path / 'strategies.json', {'schema_version': 1, 'objective': {'quality_weight': 1}, 'seed': 1, 'switching': None,
                                                   'strategies': [{'name': 'fixed:no-context'}, {'name': 'fixed:lexical-eligible'}]})
        before = sorted(p.relative_to(self.path).as_posix() for p in self.path.rglob('*'))
        stdout = io.StringIO()
        with patch('sys.stdout', stdout):
            self.assertEqual(r.main(['evaluate', '--suite', str(copy_lock), '--strategies', str(self.path / 'strategies.json'), '--attempt', str(attempt),
                                     '--candidates', str(self.path / 'candidates.json')]), 0)
        table = json.loads(stdout.getvalue())
        self.assertEqual([(x['strategy'], x['tasks'], x['covered']) for x in table], [('fixed:no-context', 16, 16), ('fixed:lexical-eligible', 16, 16)])
        self.assertEqual(sorted(p.relative_to(self.path).as_posix() for p in self.path.rglob('*')), before)

    def test_replay_manifest_validates_in_the_routing_experiment(self):
        from llm_eval.experiments import llm_routing
        from llm_eval.experiments.llm_routing.evaluation import execute as replay_execute
        suite_path, manifest_path, _, candidates_path = self.replay()
        manifest = read_json(manifest_path)
        self.assertEqual(set(manifest), {'suite_sha256', 'candidate_fingerprints', 'rows'})
        self.assertNotIn(b'\r', manifest_path.read_bytes())
        self.assertEqual(len(manifest['rows']), 32)
        self.assertEqual([(x['task_id'], x['candidate']) for x in manifest['rows']], sorted((x['task_id'], x['candidate']) for x in manifest['rows']))
        self.assertTrue(all(isinstance(x['quality'], float) and 0 <= x['quality'] <= 1 and x['cost_usd'] == 0 for x in manifest['rows']))
        case = {'suite': str(suite_path), 'replay': str(manifest_path), 'router': {'kind': 'fixed', 'choice': 'lexical-eligible'},
                'candidates': read_json(candidates_path), 'policy': {'fallback': 'no-context'}}
        self.assertIsNone(llm_routing.validate(case, ROOT, 'replay'))
        result = replay_execute({'mode': 'replay', 'parameters': case}, self.path / 'routing-attempt', ROOT)
        self.assertEqual(result['status'], 'succeeded')
        rows = lines(self.path / 'routing-attempt/requests.jsonl')
        self.assertEqual({(x['benchmark'], x['selected_model'], x['status']) for x in rows}, {('legal-routing', 'lexical-eligible', 'ok')})
        details = {d['matter_id']: d for d in lines(smoke_attempt() / 'local/score-detail.jsonl') if d['arm'] == 'lexical-eligible'}
        for row in rows:
            d = details[row['task_id']]
            self.assertEqual(row['quality'], round(sum(v is True for v in d['criteria'].values()) / 14, 6))

    def test_invalid_outputs_are_replayed_as_zero_quality(self):
        r = routing()
        attempt = generation_attempt(self.path / 'attempts', 'invalid', SMOKE, ('no-context',),
                                     overrides={'f1-ledger-a': 'not json at all', 'f2-berth-a': {'status': 500}}, parse_retries=0)
        rows = {x['task_id']: x for x in lines(attempt / 'requests.jsonl')}
        self.assertEqual((rows['f1-ledger-a']['status'], rows['f1-ledger-a']['criteria_passed'], rows['f2-berth-a']['status']), ('invalid', 0, 'error'))
        _, manifest_path, provenance_path, _ = self.replay(arms=('no-context',), attempts=[attempt])
        manifest = read_json(manifest_path)
        found = {x['task_id']: x for x in manifest['rows']}
        self.assertEqual(found['f1-ledger-a']['quality'], 0.0)
        self.assertNotIn('f2-berth-a', found)
        self.assertEqual(len(found), 15)
        tasks = r.route_tasks(contracts.load_suite(SMOKE))['tasks']
        (row,) = r.evaluate(manifest, tasks, [{'name': 'fixed:no-context'}], {}, outcomes=read_json(provenance_path)['outcomes'])
        self.assertEqual((row['tasks'], row['covered'], row['missing']), (16, 15, 1))

    def test_sidecar_carries_lock_scorer_and_attempt_provenance(self):
        g = grading()
        suite_path, manifest_path, provenance_path, _ = self.replay()
        provenance, manifest = read_json(provenance_path), read_json(manifest_path)
        self.assertNotIn(b'\r', provenance_path.read_bytes())
        smoke = contracts.load_suite(SMOKE)
        attempt = smoke_attempt()
        self.assertEqual({k: v for k, v in provenance.items() if k not in ('attempts', 'outcomes', 'generator', 'generator_sha256')}, {
            'schema_version': 1, 'kind': 'legal-routing-provenance', 'suite_lock_sha256': sha256_file(SMOKE), 'split_id': 'smoke',
            'rubric_version': smoke['rubric']['rubric_version'], 'scorer_fingerprint': g.scorer_fingerprint(smoke),
            'routing_suite_sha256': manifest['suite_sha256'], 'replay_manifest_sha256': digest(manifest), 'calibration': None})
        lineage = {'inference_job_id': 'legal-smoke-source', 'inference_attempt_id': attempt.name,
                   'output_manifest_sha256': sha256_file(attempt / 'local/output-manifest.json'), 'reviewer_fingerprint': None}
        self.assertEqual(provenance['attempts'], [{'candidate': c, **lineage} for c in ('lexical-eligible', 'no-context')])
        self.assertEqual(len(provenance['outcomes']), 32)
        self.assertEqual({frozenset(o) for o in provenance['outcomes']},
                         {frozenset({'task_id', 'candidate', 'decision_correct', 'false_charge', 'dangerous_commitment', 'all_pass', 'critical_errors'})})
        self.assertEqual({frozenset(x) for x in manifest['rows']}, {frozenset({'task_id', 'candidate', 'quality', 'latency_s', 'cost_usd'})})
        text = manifest_path.read_text(encoding='utf-8')
        for leaked in ('decision_correct', 'false_charge', 'all_pass', 'scorer', 'suite_lock', 'attempt'):
            self.assertNotIn(leaked, text)
        gold = {x['matter_id']: x['recommendation'] for x in smoke['rubric']['matters']}
        choices = {(d['matter_id'], d['arm']): d['choice'] for d in lines(attempt / 'local/score-detail.jsonl')}
        for o in provenance['outcomes']:
            self.assertEqual(o['decision_correct'], choices[(o['task_id'], o['candidate'])] == gold[o['task_id']])
        # A score attempt of the same outputs gives the same candidates, with the inference attempt as lineage and its timings.
        r = routing()
        job = job_for(SMOKE, {'output_manifest': str(attempt / 'local/output-manifest.json')}, mode='score', job_id='legal-score-of-source')
        scored = self.path / 'score'
        scored.mkdir()
        atomic_json(scored / 'job.json', job)
        legal.execute(job, scored, ROOT)
        source, rescored = r.rows_by_candidate(attempt), r.rows_by_candidate(scored)
        self.assertEqual(rescored, source)
        self.assertEqual(provenance['generator'], {k: CANDIDATE[k] for k in CANDIDATE})
        self.assertEqual(provenance['generator_sha256'], read_json(attempt / 'metadata.json')['roles']['generator']['profile_sha256'])
        self.assertEqual(rescored['no-context']['lineage'], {**lineage, 'scorer_fingerprint': g.scorer_fingerprint(smoke),
                                                             'suite_lock_sha256': sha256_file(SMOKE),
                                                             'generator_sha256': provenance['generator_sha256'], 'generator': provenance['generator']})

    def test_stale_orphan_and_duplicate_rows_are_rejected(self):
        r, g = routing(), grading()
        suite_path, manifest_path, provenance_path, candidates_path = self.replay()
        manifest, provenance = read_json(manifest_path), read_json(provenance_path)
        task_suite, smoke, pool = read_json(suite_path), contracts.load_suite(SMOKE), read_json(candidates_path)
        r.verify_replay(manifest, provenance, task_suite, pool, smoke)

        def resealed(m):
            return {**provenance, 'replay_manifest_sha256': digest(m)}
        orphan = {**manifest, 'rows': manifest['rows'] + [{'task_id': 'f9-none-a', 'candidate': 'no-context', 'quality': 1.0, 'latency_s': 1.0, 'cost_usd': 0}]}
        stranger = {**manifest, 'rows': manifest['rows'] + [{'task_id': 'f1-ledger-a', 'candidate': 'reranked', 'quality': 1.0, 'latency_s': 1.0, 'cost_usd': 0}]}
        duplicate = {**manifest, 'rows': manifest['rows'] + [manifest['rows'][0]]}
        cases = [({**manifest, 'suite_sha256': '0' * 64}, None, task_suite, pool, 'Replay suite hash mismatch'),
                 (manifest, None, {**task_suite, 'tasks': task_suite['tasks'][1:]}, pool, 'Replay suite hash mismatch'),
                 (manifest, None, task_suite, {**pool, 'no-context': {**pool['no-context'], 'model_revision': 'r2'}}, 'Replay candidate fingerprint mismatch'),
                 (orphan, resealed(orphan), task_suite, pool, 'Orphan replay row'),
                 (stranger, resealed(stranger), task_suite, pool, 'Orphan replay row'),
                 (duplicate, resealed(duplicate), task_suite, pool, 'Duplicate replay outcome'),
                 (manifest, {**provenance, 'outcomes': provenance['outcomes'] + provenance['outcomes'][:1]}, task_suite, pool, 'Duplicate replay outcome'),
                 (manifest, {**provenance, 'scorer_fingerprint': '0' * 64}, task_suite, pool, 'Stale replay scores'),
                 (manifest, {**provenance, 'suite_lock_sha256': '0' * 64}, task_suite, pool, 'Stale replay scores'),
                 ({**manifest, 'rows': manifest['rows'][1:]}, None, task_suite, pool, 'Stale replay scores'),
                 (manifest, {**provenance, 'attempts': [a for a in provenance['attempts'] if a['candidate'] != 'no-context']}, task_suite, pool,
                  'Replay row without an originating attempt'),
                 (manifest, {**provenance, 'generator': {**provenance['generator'], 'model_revision': 'r9'}}, task_suite, pool,
                  'Candidate does not match the fixed generator')]
        for m, p, t, c, message in cases:
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                r.verify_replay(m, p or provenance, t, c, smoke)
        with patch.object(g, 'SCORER_VERSION', 'legal-scorer-next'):      # a scorer change after the manifest was built
            with self.assertRaisesRegex(ValueError, 'Stale replay scores'):
                r.verify_replay(manifest, provenance, task_suite, pool, smoke)
        verify = ['verify', '--suite', str(SMOKE), '--replay', str(manifest_path), '--routing-suite', str(suite_path), '--candidates', str(candidates_path),
                  '--attempt', str(smoke_attempt())]
        write_json(self.path / 'strategies.json', {'schema_version': 1, 'objective': {}, 'seed': 1, 'switching': None, 'strategies': [{'name': 'fixed:no-context'}]})
        evaluate = ['evaluate', '--suite', str(SMOKE), '--strategies', str(self.path / 'strategies.json'), '--replay', str(manifest_path), '--routing-suite',
                    str(suite_path), '--candidates', str(candidates_path), '--attempt', str(smoke_attempt())]
        with patch('sys.stdout', io.StringIO()):
            self.assertEqual(r.main(verify), 0)
            self.assertEqual(r.main(evaluate), 0)
        stderr = io.StringIO()
        with patch.object(g, 'SCORER_VERSION', 'legal-scorer-next'), patch('sys.stderr', stderr), patch('sys.stdout', io.StringIO()) as out:
            self.assertEqual(r.main(verify), 2)
            self.assertEqual(r.main(evaluate), 2)
        self.assertEqual(stderr.getvalue().count('Stale replay scores'), 2)
        self.assertEqual(out.getvalue(), '')

    def test_fixed_rule_random_and_selector_are_compared_on_the_same_tasks(self):
        r = routing()
        manifest, tasks, outcomes = comparison()
        decisions = {'a': {'action': 'route', 'selected': 'lexical-eligible', 'fallback_used': False, 'confidence': 0.9, 'router_s': 0.01},
                     'b': {'action': 'defer', 'selected': None, 'fallback_used': False, 'confidence': None, 'router_s': 0.02},
                     'c': {'action': 'route', 'selected': 'no-context', 'fallback_used': False, 'confidence': 0.8, 'router_s': 0.03},
                     'd': {'action': 'route', 'selected': 'no-context', 'fallback_used': True, 'confidence': 0.3, 'router_s': 0.04}}
        strategies = [{'name': 'fixed:no-context'}, {'name': 'fixed:lexical-eligible'},
                      {'name': 'category', 'router': {'kind': 'category', 'default_category': 'fast', 'keywords': {'slow': ['beta']}},
                       'policy': {'category_models': {'fast': 'no-context', 'slow': 'lexical-eligible'}, 'fallback': 'no-context'}},
                      {'name': 'random-matched', 'match': 'category'},
                      {'name': 'selector', 'decisions': decisions, 'thresholds': [0.5]}]
        table = r.evaluate(manifest, tasks, strategies, {'quality_weight': 1}, seed=1, outcomes=outcomes)
        self.assertEqual([x['strategy'] for x in table], ['fixed:no-context', 'fixed:lexical-eligible', 'category', 'random-matched', 'selector'])
        columns = ('tasks', 'covered', 'missing', 'mean_quality', 'mean_latency_s', 'mean_utility', 'fallbacks', 'abstentions', 'unsafe_commitments',
                   'false_charge_rate', 'all_pass_rate')
        self.assertEqual([tuple(x[k] for k in columns) for x in table], [
            (4, 4, 0, 0.4375, 1.0, 0.4375, 0, 0, 2, 0.25, 0.25),
            (4, 3, 1, 0.833333, 3.0, 0.833333, 0, 0, 0, 0.0, 0.666667),
            (4, 4, 0, 0.5625, 1.5, 0.5625, 0, 0, 1, 0.0, 0.25),
            # Random(1) draws 0.134, 0.847, 0.764, 0.255 against the weight 0.25: only task a takes the slower candidate.
            (4, 4, 0, 0.5625, 1.5, 0.5625, 0, 0, 2, 0.25, 0.5),
            # The selector defers task b: a covered task with quality 0 and no generation time (latency over generated tasks only).
            (4, 4, 0, 0.5625, 1.666667, 0.5625, 1, 1, 1, 0.0, 0.5)])
        self.assertEqual(table[3]['mean_latency_s'], table[2]['mean_latency_s'])      # latency-matched
        again = r.evaluate(manifest, tasks, strategies, {'quality_weight': 1}, seed=1, outcomes=outcomes)      # the router time is measured
        self.assertEqual([{k: v for k, v in x.items() if k != 'router_s_median'} for x in again],
                         [{k: v for k, v in x.items() if k != 'router_s_median'} for x in table])
        self.assertEqual((table[0]['router_s_median'], table[3]['router_s_median'], table[4]['router_s_median']), (None, None, 0.025))
        self.assertIsInstance(table[2]['router_s_median'], float)
        self.assertEqual(table[4]['risk_coverage'], [{'threshold': 0.5, 'tasks': 4, 'covered': 2, 'coverage': 0.5, 'errors': 0, 'risk': 0.0,
                                                      'unsafe_commitments': 0, 'unsafe_rate': 0.0}])
        self.assertIsNone(table[0]['risk_coverage'])
        bare = r.evaluate(manifest, tasks, strategies[:1], {})
        self.assertEqual((bare[0]['unsafe_commitments'], bare[0]['false_charge_rate'], bare[0]['all_pass_rate']), (None, None, None))
        # A latency weight changes the order of two strategies.
        weighted = {x['strategy']: x['mean_utility'] for x in r.evaluate(manifest, tasks, strategies, {'quality_weight': 1, 'latency_weight': 0.2}, outcomes=outcomes)}
        self.assertGreater(table[1]['mean_utility'], table[2]['mean_utility'])
        self.assertEqual((weighted['fixed:lexical-eligible'], weighted['category']), (0.233333, 0.2625))
        # An unknown latency makes every metric of the random baseline unknown.
        unknown = {**manifest, 'rows': [{**x, 'latency_s': None} if (x['task_id'], x['candidate']) == ('a', 'lexical-eligible') else x for x in manifest['rows']]}
        (random_row,) = [x for x in r.evaluate(unknown, tasks, strategies, {}, outcomes=outcomes) if x['strategy'] == 'random-matched']
        self.assertEqual({k for k, v in random_row.items() if v is not None}, {'strategy', 'tasks'})
        # Candidates are recipes of one attempt; a routed attempt and any other grouping are refused.
        routed = self.path / 'routed'
        routed.mkdir()
        (routed / 'requests.jsonl').write_text(json.dumps({'task_id': 'f1-ledger-a', 'arm': 'routed', 'repetition': 0}) + '\n', encoding='utf-8')
        write_json(routed / 'metadata.json', {'experiment': 'legal-benchmark', 'mode': 'generation'})
        (routed / 'local').mkdir()
        (routed / 'local/score-detail.jsonl').write_text('', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'A routed attempt is not a candidate'):
            r.rows_by_candidate(routed)
        with self.assertRaisesRegex(ValueError, 'Unsupported candidate grouping: deployment'):
            r.rows_by_candidate(smoke_attempt(), by='deployment')
        self.assertEqual(set(r.rows_by_candidate(smoke_attempt())), {'no-context', 'lexical-eligible'})
        # The operator files are read with closed key sets.
        _, manifest_path, _, candidates_path = self.replay()
        good = {'schema_version': 1, 'objective': {'quality_weight': 1}, 'seed': 1, 'switching': None, 'strategies': [{'name': 'fixed:no-context'}]}
        for name, value in (('strategies-extra', {**good, 'extra': 1}), ('strategies-objective', {**good, 'objective': {'speed_weight': 1}}),
                            ('strategies-strategy', {**good, 'strategies': [{'name': 'fixed:no-context', 'router': {}}]}),
                            ('strategies-name', {**good, 'strategies': [{'name': 'oracle'}]}),
                            ('strategies-negative', {**good, 'objective': {'quality_weight': -1}})):
            with self.subTest(name):
                write_json(self.path / f'{name}.json', value)
                with patch('sys.stderr', io.StringIO()) as stderr, patch('sys.stdout', io.StringIO()):
                    self.assertEqual(r.main(['evaluate', '--suite', str(SMOKE), '--strategies', str(self.path / f'{name}.json'), '--replay', str(manifest_path),
                                             '--routing-suite', str(self.path / 'routing-suite.json'), '--candidates', str(candidates_path),
                                             '--attempt', str(smoke_attempt())]), 2)
                self.assertIn('Error:', stderr.getvalue())
        for name, value in (('candidates-extra', {'no-context': {**CANDIDATE, 'secret_path': 'x'}}), ('candidates-id', {'oracle': CANDIDATE}),
                            ('candidates-reference', {'reference': CANDIDATE}), ('candidates-missing', {'no-context': {'model': 'x'}})):
            with self.subTest(name):
                write_json(self.path / f'{name}.json', value)
                with patch('sys.stderr', io.StringIO()) as stderr:
                    self.assertEqual(r.main(['replay', '--suite', str(SMOKE), '--routing-suite', str(self.path / 'routing-suite.json'), '--attempt',
                                             str(smoke_attempt()), '--candidates', str(self.path / f'{name}.json'), '--output', str(self.path / 'x.json')]), 2)
                self.assertIn('Error:', stderr.getvalue())

    def test_switch_reprefill_and_fallback_counts(self):
        r = routing()
        manifest, tasks, outcomes = comparison()
        category = {'name': 'category', 'router': {'kind': 'category', 'default_category': 'fast', 'keywords': {'slow': ['beta']}},
                    'policy': {'category_models': {'fast': 'no-context', 'slow': 'lexical-eligible'}, 'fallback': 'no-context'}}
        tokens = {'a': 100, 'b': 200, 'c': 300, 'd': 400}
        switching = {'mode': 'switching', 'deployment_of': {'no-context': 'gen-a', 'lexical-eligible': 'gen-b'}, 'prompt_tokens': tokens}
        (row,) = r.evaluate(manifest, tasks, [category], {}, switching=switching)
        self.assertEqual((row['switches'], row['cold_switches'], row['reprefill_tokens'], row['fallbacks']), (2, 2, 500, 0))
        (row,) = r.evaluate(manifest, tasks, [category], {}, switching={**switching, 'mode': 'resident'})
        self.assertEqual((row['switches'], row['cold_switches'], row['reprefill_tokens']), (2, 0, 500))
        (row,) = r.evaluate(manifest, tasks, [category], {}, switching={**switching, 'prompt_tokens': {**tokens, 'c': None}})
        self.assertEqual((row['switches'], row['reprefill_tokens']), (2, None))
        same = {**switching, 'deployment_of': {'no-context': 'gen-a', 'lexical-eligible': 'gen-a'}}
        (row,) = r.evaluate(manifest, tasks, [category], {}, switching=same)
        self.assertEqual((row['switches'], row['cold_switches'], row['reprefill_tokens']), (0, 0, 0))
        (row,) = r.evaluate(manifest, tasks, [category], {})
        self.assertEqual((row['switches'], row['cold_switches'], row['reprefill_tokens']), (None, None, None))
        # The category rule routes through `route`: a removed candidate takes the fallback and is counted.
        removed = {**category, 'policy': {**category['policy'], 'category_models': {'fast': 'no-context', 'slow': 'dense'}}}
        (row,) = r.evaluate(manifest, tasks, [removed], {})
        self.assertEqual((row['fallbacks'], row['covered']), (1, 4))

    def test_routing_bundle_over_a_legal_export_is_unranked_and_unpublishable(self):
        from llm_eval.reporting import index
        from llm_eval.reporting.publish import publish_report
        suite_path, manifest_path, _, candidates_path = self.replay()
        write_json(self.path / 'routing-case.json', {'id': 'legal-replay', 'parameters': {
            'suite': 'routing-suite.json', 'replay': 'replay.json', 'router': {'kind': 'fixed', 'choice': 'lexical-eligible'},
            'candidates': read_json(candidates_path), 'policy': {'fallback': 'no-context'}}})
        self.inventory()
        write_json(self.path / 'routing-campaign.json', {'schema_version': 2, 'id': 'legal-replay', 'inventory': 'inventory.json', 'phases': [
            {'id': 'routing', 'experiments': [{'id': 'llm-routing', 'version': 1, 'mode': 'replay', 'cases': ['routing-case.json'],
                                               'hardware_configs': ['native']}]}]})
        plan = compile_campaign(self.path / 'routing-campaign.json', ROOT)

        def rpc(target, payload, root, timeout=60):
            if payload['action'] != 'run':
                return {'ok': True}
            out = Path(payload['output'])
            result = {**get_experiment(payload['job']['experiment_id']).execute(payload['job'], out, Path(payload['root'])), 'attempt_id': payload['owner']}
            atomic_json(out / 'result.json', result)
            return result
        with patch('llm_eval.orchestration.resources.lock_root', return_value=self.path / 'locks'), \
                patch('llm_eval.orchestration.transport.rpc', side_effect=rpc):
            directory = initialize(plan, self.path / 'out')
            run_campaign(directory)
        report = next(directory.glob('experiments/*/report'))
        with self.assertRaisesRegex(ValueError, 'Publication identity mismatch|legal'):
            publish_report(report, ROOT, dry_run=True)
        spec = read_json(report / 'publication.json')
        bundle = self.path / 'site' / spec['report_path']
        shutil.copytree(report / 'bundle' / spec['report_path'], bundle)
        records = index.collect(self.path / 'site')
        (record,) = records
        self.assertEqual((record['experiment'], record['synthetic'], record['status']), ('llm-routing', False, 'succeeded'))
        self.assertFalse(record['score'])
        self.assertEqual(index.ranked(records), {})
        for name in ('routing-replay-campaign.json', 'score-campaign.json'):
            self.assertEqual(read_json(EXAMPLES / name)['reporting']['publish']['mode'], 'none')


def comparison():
    """A hand-made replay manifest over four tasks and two recipes, with sidecar outcomes. Fixture numbers only."""
    tasks = [{'id': t, 'category': 'legal', 'messages': [{'role': 'user', 'content': 'QUESTION ' + word}]}
             for t, word in (('a', 'alpha'), ('b', 'beta'), ('c', 'gamma'), ('d', 'delta'))]
    rows = [('a', 'no-context', 0.5, 1.0), ('a', 'lexical-eligible', 1.0, 3.0), ('b', 'no-context', 0.0, 1.0), ('b', 'lexical-eligible', 0.5, 3.0),
            ('c', 'no-context', 1.0, 1.0), ('c', 'lexical-eligible', 1.0, 3.0), ('d', 'no-context', 0.25, 1.0)]
    manifest = {'suite_sha256': digest({'tasks': tasks}), 'candidate_fingerprints': {}, 'rows': [
        {'task_id': t, 'candidate': c, 'quality': q, 'latency_s': latency, 'cost_usd': 0} for t, c, q, latency in rows]}
    flags = {('a', 'no-context'): (True, False, False, False), ('a', 'lexical-eligible'): (True, False, False, True),
             ('b', 'no-context'): (False, True, False, False), ('b', 'lexical-eligible'): (False, False, False, False),
             ('c', 'no-context'): (True, False, False, True), ('c', 'lexical-eligible'): (True, False, False, True),
             ('d', 'no-context'): (False, False, True, False)}
    outcomes = [{'task_id': t, 'candidate': c, 'decision_correct': dc, 'false_charge': fc, 'dangerous_commitment': dm, 'all_pass': ap,
                 'critical_errors': 0} for (t, c), (dc, fc, dm, ap) in flags.items()]
    return manifest, tasks, outcomes


# 5. Readiness, setup and examples -------------------------------------------------------------------------------------

class ReadinessTests(TempCase):
    def args(self, *argv):
        from llm_eval import readiness
        return readiness.parser().parse_args(list(argv))

    def campaign(self, name, roles, selector=None):
        parameters = {'suite': str(SMOKE), 'arms': ['no-context', 'lexical-eligible'], 'roles': roles, **({'selector': selector} if selector else {})}
        self.plan(name, 'generation', parameters)
        return self.path / f'{name}-campaign.json'

    def test_cpu_only_legal_job_needs_no_gpu_and_other_plugins_are_unchanged(self):
        from llm_eval import readiness
        cpu = readiness.select(self.args('--campaign', str(self.campaign('cpu', {'generator': generator()}))), ROOT)
        self.assertEqual((cpu['runtimes'], cpu['needs_gpu'], cpu['os_id']), ({}, False, 'ubuntu-26.04-native'))
        gpu = readiness.select(self.args('--campaign', str(self.campaign('gpu', {'generator': generator(accelerator='gpu')}))), ROOT)
        self.assertEqual((gpu['runtimes'], gpu['needs_gpu']), ({}, True))
        selector = readiness.select(self.args('--campaign', str(self.campaign(
            'selector', {'generator': generator(), 'selector': selector_role(accelerator='gpu')}, served()))), ROOT)
        self.assertEqual((selector['runtimes'], selector['needs_gpu']), ({}, True))
        smoke = readiness.select(self.args('--campaign', str(ROOT / 'campaigns/legal-smoke.json')), ROOT)
        self.assertEqual((smoke['runtimes'], smoke['needs_gpu']), ({}, False))
        # The routing and offload examples resolve exactly as before the legal hook.
        for name in ('windows', 'ubuntu', 'wsl'):
            with self.subTest(name):
                selection = readiness.select(self.args('--campaign', str(ROOT / f'configs/examples/raider-{name}/campaign.json')), ROOT)
                self.assertEqual(([k[0] for k in selection['runtimes']], list(selection['runtimes'].values()), selection['needs_gpu']), (['ollama'], [False], True))
        routing_smoke = readiness.select(self.args('--campaign', str(ROOT / 'campaigns/routing-smoke.json')), ROOT)
        self.assertEqual((routing_smoke['runtimes'], routing_smoke['needs_gpu']), ({}, False))
        # A non-synthetic job of a plugin without the hook still counts, whatever its parameters say.
        jobs = [{'hardware_config_id': 'a', 'hardware': {'os_id': 'ubuntu-26.04-native', 'hardware_profile': 'msi-raider-18-hx-ai'}, 'target': {'transport': 'local'},
                 'parameters': {'router': {'kind': 'fixed'}, 'roles': {'generator': {'accelerator': 'cpu'}}}, 'mode': 'decision', 'experiment_id': 'llm-routing'}]
        with patch('llm_eval.orchestration.planner.compile_campaign', return_value={'jobs': jobs}):
            self.assertTrue(readiness.select(self.args('--campaign', 'c.json'), ROOT)['needs_gpu'])
            jobs[0]['parameters']['synthetic'] = True
            self.assertFalse(readiness.select(self.args('--campaign', 'c.json'), ROOT)['needs_gpu'])
        self.assertTrue(readiness.select(self.args('--campaign', str(EXAMPLES / 'evaluation-campaign.json'), '--hardware-config', 'raider-windows'), ROOT)['needs_gpu'])

    def test_setup_installs_nothing_for_legal_roles(self):
        from llm_eval.orchestration.setup import setup_campaign
        plan = self.plan('setup', 'generation', {'suite': str(SMOKE), 'arms': ['no-context'], 'roles': {'generator': generator(platform='ollama')}})
        with patch('llm_eval.orchestration.setup.rpc', side_effect=AssertionError('a legal campaign installs nothing')), \
                patch('llm_eval.orchestration.setup.reserve', side_effect=AssertionError('a legal campaign reserves nothing at setup')):
            self.assertEqual(setup_campaign(plan), 0)
        (job,) = plan['jobs']
        self.assertEqual(legal.setup_platforms(job['parameters'], 'generation'), [])
        self.assertEqual(legal.setup_platforms({'roles': {'generator': {'serving': 'managed', 'platform': 'ollama'},
                                                          'embedder': {'serving': 'managed', 'platform': 'llama.cpp'},
                                                          'analyst': {'serving': 'external', 'platform': 'vllm'}}}, 'workflow'), ['llama.cpp', 'ollama'])
        self.assertEqual(legal.setup_platforms({'suite': str(SMOKE), 'synthetic': True}, 'smoke'), [])
        self.assertFalse(profiles.MANAGED_SERVING_ENABLED)
        with self.assertRaisesRegex(ValueError, 'Managed serving of legal roles is gated'):
            self.plan('managed', 'generation', {'suite': str(SMOKE), 'arms': ['no-context'], 'roles': {'generator': generator(serving='managed')}})

    def test_cpu_only_roles_remain_model_runs(self):
        with self.assertRaisesRegex(ValueError, 'Only fixture runs may declare synthetic: true'):
            self.plan('synthetic', 'generation', {'suite': str(SMOKE), 'synthetic': True, 'arms': ['no-context'], 'roles': {'generator': generator()}})
        with FakeGenerator('not json') as fake:
            (job,) = self.plan('cpu', 'generation', {'suite': str(SMOKE), 'arms': ['no-context'], 'roles': {'generator': generator(fake.endpoint)},
                                                     'parse_retries': 0})['jobs']
            self.assertEqual(legal.host_requirements(job['parameters'], 'generation'), {'gpu': False})
            attempt = self.run_job(job, 'cpu')
        self.assertEqual({(x['execution_kind'], x['synthetic']) for x in lines(attempt / 'requests.jsonl')}, {('model-run', False)})
        self.assertEqual((read_json(attempt / 'metadata.json')['execution_kind'], read_json(attempt / 'metadata.json')['synthetic']), ('model-run', False))


class ExampleTests(TempCase):
    def test_legal_examples_plan_without_publication(self):
        names = sorted(p.name for p in EXAMPLES.iterdir())
        self.assertEqual(names, sorted(['README.md', 'inventory.json', 'inventory-separate-service.json', 'qualification-campaign.json', 'legal-offload-case.json',
                                        'legal-offload-run.json', 'evaluation-campaign.json', 'retrieval-case.json', 'generation-case.json', 'workflow-case.json',
                                        'score-campaign.json', 'score-case.json', 'routing-replay-campaign.json', 'routing-replay-case.json']))
        for name in names:
            self.assertNotIn(b'\r', (EXAMPLES / name).read_bytes(), name)
        campaigns = [n for n in names if n.endswith('-campaign.json')]
        for name in campaigns:
            self.assertEqual(read_json(EXAMPLES / name)['reporting']['publish']['mode'], 'none', name)
        qualification = compile_campaign(EXAMPLES / 'qualification-campaign.json', ROOT)
        (job,) = qualification['jobs']
        self.assertEqual((job['experiment_id'], job['parameters']['server_mode'], job['status']), ('model-offloading', 'external', 'planned'))
        self.assertEqual(Path(job['parameters']['config']['suite']), (X / 'workloads/qualification/legal-shaped.json').resolve())
        evaluation = compile_campaign(EXAMPLES / 'evaluation-campaign.json', ROOT)
        self.assertEqual([(j['experiment_id'], j['mode']) for j in evaluation['jobs']],
                         [('legal-benchmark', 'retrieval'), ('legal-benchmark', 'generation'), ('legal-benchmark', 'workflow')])
        self.assertEqual([j['parameters'].get('synthetic', False) for j in evaluation['jobs']], [True, False, False])
        self.assertEqual(evaluation['jobs'][1]['depends_on'], [evaluation['jobs'][0]['job_id']])
        self.assertEqual(evaluation['jobs'][2]['depends_on'], [evaluation['jobs'][1]['job_id']])
        for j in evaluation['jobs'][1:]:
            for role in j['parameters']['roles'].values():
                self.assertEqual((role['serving'], role['accelerator'], role['qualification']), ('external', 'gpu', None))
                self.assertRegex(role['endpoint'], r'^http://127\.0\.0\.1:\d+/')
                self.assertIn('REPLACE_WITH_', role['model_revision'])
        for name in ('score-case.json', 'routing-replay-case.json'):
            self.assertIn('REPLACE_WITH_', (EXAMPLES / name).read_text(encoding='utf-8'), name)
        for name in ('score-campaign.json', 'routing-replay-campaign.json'):
            with self.subTest(name), self.assertRaises((ValueError, OSError)):
                compile_campaign(EXAMPLES / name, ROOT)
        separate = read_json(EXAMPLES / 'inventory-separate-service.json')
        hosts = {t['physical_host_id'] for t in separate['targets'].values()}
        named = {h for t in separate['targets'].values() for h in t.get('resource_hosts', [])}
        self.assertTrue(named)
        self.assertTrue(named <= hosts)
        for name in campaigns:
            inventory = read_json(EXAMPLES / read_json(EXAMPLES / name)['inventory'])
            self.assertEqual({t['physical_host_id'] for t in inventory['targets'].values()}, {'raider'})
        readme = (EXAMPLES / 'README.md').read_text(encoding='utf-8')
        for phrase in ('routing verify', 'resource_hosts', 'cannot be published', 'not a measurement', 'plan'):
            self.assertIn(phrase, readme)

    def test_private_matter_suite_is_refused_by_every_mode(self):
        directory = self.path / 'private'
        shutil.copytree(SMOKE.parent, directory)
        for name in ('matters.json', 'corpus.json', 'rubric.json'):
            value = read_json(directory / name)
            value['data_class'] = 'private-matter'
            write_json(directory / name, value)
        lock = read_json(directory / 'suite.lock.json')
        write_json(directory / 'suite.lock.json', contracts.make_lock(
            directory, benchmark_id=lock['benchmark_id'], revision=lock['revision'], split_id=lock['split_id'], data_class='private-matter',
            jurisdiction_profile=lock['jurisdiction_profile'], manifests={'matters': 'matters.json', 'corpus': 'corpus.json', 'rubric': 'rubric.json'}))
        private = directory / 'suite.lock.json'
        self.assertEqual(contracts.load_suite(private)['lock']['data_class'], 'private-matter')
        roles = {'generator': generator()}
        for mode, parameters in (('retrieval', {'arms': ['lexical'], 'synthetic': True}), ('generation', {'arms': ['no-context'], 'roles': roles}),
                                 ('workflow', {'arms': ['no-context'], 'roles': roles, 'selector': CATEGORY}),
                                 ('score', {'output_manifest': str(self.path / 'missing.json')})):
            with self.subTest(mode=mode), self.assertRaisesRegex(ValueError, 'This mode does not accept private-matter suites'):
                self.plan('private-' + mode, mode, {'suite': str(private), **parameters})
        for call in (lambda: routing().export_suite(private, self.path / 'x.json'), lambda: profiles.export_workload(private, self.path / 'y.json')):
            with self.assertRaisesRegex(ValueError, 'Export is limited to approved fixture suites'):
                call()

    def test_examples_agree_with_their_readme(self):
        run = read_json(EXAMPLES / 'legal-offload-run.json')
        for name in ('generation-case.json', 'workflow-case.json'):
            role = read_json(EXAMPLES / name)['parameters']['roles']['generator']
            self.assertEqual((role['platform'], role['protocol'], role['endpoint'], role['context_tokens'], role['max_output_tokens']),
                             (run['platform'], run['protocol'], run['endpoint'], run['context_tokens'], run['max_output_tokens']), name)
        readme = (EXAMPLES / 'README.md').read_text(encoding='utf-8')
        for phrase in ('local forward', 'single active large model', 'raider` lock'):
            self.assertIn(phrase, readme)
        experiment = (X / 'README.md').read_text(encoding='utf-8')
        for phrase in ('refuses such bundles by content', 'selector_deferral', 'route_error_type', 'never public', 'not re-read', 'informational'):
            self.assertIn(phrase, experiment)


# 6. Review fixes ------------------------------------------------------------------------------------------------------

def linux_attempt(root, samples, **kwargs):
    metadata = attested(paging=None)
    metadata['config'] = {**metadata['config'], 'os_id': 'ubuntu-26.04-native'}
    return offload_attempt(root, os_id='ubuntu-26.04-native', telemetry=samples, metadata=metadata, **kwargs)


def swap(*values):
    return [{'swap_in_bytes': v, 'swap_out_bytes': 0} for v in values]


class ProfileFixTests(TempCase):
    def freeze(self, name, placement={'gpu_layers': 20}, **kwargs):
        campaign, _ = offload_attempt(self.path / name, **kwargs)
        return profiles.freeze(campaign, JOB_ID, ATTEMPT_ID, observed_placement=placement)

    def test_paging_is_observed_only_from_meaningful_swap_counters(self):
        for name, samples, leaf, probe in (('constant', swap(100, 100, 100), {'value': False, 'nature': 'observed'}, ('passed', [])),
                                          ('growing', swap(100, 100, 4096), {'value': True, 'nature': 'observed'}, ('failed', ['paging_observed'])),
                                          ('one', swap(100), {'value': None, 'nature': 'unavailable'}, ('inconclusive', ['paging_unknown'])),
                                          ('null', [{'swap_in_bytes': None, 'swap_out_bytes': None}] * 3, {'value': None, 'nature': 'unavailable'},
                                           ('inconclusive', ['paging_unknown']))):
            with self.subTest(name):
                campaign, _ = linux_attempt(self.path / name, samples)
                profile = profiles.freeze(campaign, JOB_ID, ATTEMPT_ID, observed_placement={'gpu_layers': 20})
                self.assertEqual((profile['memory']['paging_observed'], profile['probe']['outcome'], profile['probe']['reason_codes']), (leaf, *probe))
        # Windows: the swap counters are always zero, so they prove nothing, and the runner's own assessment is not evidence.
        metadata = attested(paging=None)
        metadata['memory_assessment'] = {'paging_observed': False}
        profile = self.freeze('windows', metadata=metadata, telemetry=swap(0, 0, 0))
        self.assertEqual((profile['memory']['paging_observed'], profile['probe']), ({'value': None, 'nature': 'unavailable'},
                                                                                  {'outcome': 'inconclusive', 'reason_codes': ['paging_unknown']}))
        for value, leaf, outcome in (('none', {'value': False, 'nature': 'attested'}, 'passed'), ('observed', {'value': True, 'nature': 'attested'}, 'failed'),
                                     ('maybe', {'value': None, 'nature': 'unavailable'}, 'inconclusive')):
            with self.subTest(attested=value):
                profile = self.freeze('attested-' + value, metadata=attested(paging=value), telemetry=swap(0, 0, 0))
                self.assertEqual((profile['memory']['paging_observed'], profile['probe']['outcome']), (leaf, outcome))

    def test_unavailable_and_placeholder_values_do_not_bind(self):
        metadata = offload_metadata()
        metadata['config'] = {**metadata['config'], 'chat_template_sha256': 'REPLACE_WITH_ACTUAL_TEMPLATE_SHA256',
                              'tokenizer_revision': 'REPLACE_WITH_EXACT_REVISION', 'backend_version': 'TODO-1'}
        profile = self.freeze('placeholders', metadata=metadata)
        for leaf in (profile['template']['chat_template_sha256'], profile['template']['tokenizer_revision'], profile['runtime']['backend_version']):
            self.assertEqual(leaf, {'value': None, 'nature': 'unavailable'})
        good = self.freeze('good')
        unavailable = {'value': None, 'nature': 'unavailable'}
        for field, group, role_key in (('platform', 'runtime', 'platform'), ('backend_version', 'runtime', 'backend_version'),
                                       ('artifact_sha256', 'artifact', 'artifact_sha256'), ('chat_template_sha256', 'template', 'template_sha256'),
                                       ('quantization', 'artifact', 'quantization'), ('tokenizer_revision', 'template', 'tokenizer_revision')):
            with self.subTest(field):
                broken = copy.deepcopy(good)
                broken[group][field] = unavailable
                with self.assertRaisesRegex(ValueError, field + ' is unavailable in the locked profile'):
                    profiles.bind(bound_role('x.json', **{role_key: None}), broken)
        with self.assertRaisesRegex(ValueError, 'does not match its locked serving profile: model_revision'):
            profiles.bind(bound_role('x.json', model_revision='5' * 40), good)
        profiles.bind(bound_role('x.json'), good)

    def test_non_chat_roles_bind(self):
        _, path = frozen(self.path)
        identity = {'platform': 'lmstudio', 'backend_version': '0.4.28+2', 'artifact_sha256': '5' * 64, 'quantization': 'Q8_0',
                    'template_sha256': '3' * 64, 'tokenizer_revision': 'tok-rev-1', 'model_revision': '4' * 40,
                    'qualification': {'serving_profile': str(path)}}
        embedder = {'role': 'embedder', 'serving': 'external', 'capability': 'embedding', 'deployment_id': 'local-embedder', 'model': 'fake-embed',
                    'protocol': 'json', 'endpoint': 'http://127.0.0.1:9/v1/embed', 'accelerator': 'cpu', 'timeout_s': 5, 'dimensions': 8, **identity}
        self.assertTrue(profiles.public_role(profiles.validate_role(embedder, 'embedder'))['qualified'])
        selector = selector_role(**identity)
        self.assertTrue(profiles.public_role(profiles.validate_role(selector, 'selector'))['qualified'])
        with self.assertRaisesRegex(ValueError, 'does not match its locked serving profile: platform'):
            profiles.validate_role({**selector, 'platform': 'other'}, 'selector')
        # The retrieval digests of a qualified embedder include the recorded profile digest, like `metadata.roles`.
        with FakeGenerator('not json') as fake:
            (job,) = self.plan('embedder', 'generation', {'suite': str(SMOKE), 'arms': ['no-context'], 'parse_retries': 0,
                                                          'roles': {'generator': generator(fake.endpoint), 'embedder': embedder}},
                               os_id='windows-11-native')['jobs']
            attempt = self.run_job(job, 'embedder')
        metadata = read_json(attempt / 'metadata.json')
        self.assertEqual(metadata['retrieval']['embedder_sha256'], metadata['roles']['embedder']['profile_sha256'])
        self.assertNotEqual(metadata['retrieval']['embedder_sha256'], profiles.profile_digest(job['parameters']['roles']['embedder']))

    def test_profile_is_bound_to_its_host(self):
        profile, path = frozen(self.path)
        self.assertEqual((profile['source']['physical_host_id'], profile['source']['hardware_profile']), (HOST, 'msi-raider-18-hx-ai'))
        sha = sha256_file(path)
        role = bound_role(path)
        job = {'input_files': [{'path': str(path), 'sha256': sha}], 'hardware': {'os_id': 'windows-11-native', 'hardware_profile': 'msi-raider-18-hx-ai'},
               'target': {'physical_host_id': HOST}, 'resources': [HOST, 'service-host']}
        profiles.check_job({'generator': role}, job)
        for change, message in (({'target': {'physical_host_id': 'other-host'}, 'resources': ['other-host']}, 'measured on another host'),
                                ({'hardware': {'os_id': 'windows-11-native', 'hardware_profile': 'other-profile'}}, 'measured on another hardware profile'),
                                ({'hardware': {'os_id': 'ubuntu-26.04-native', 'hardware_profile': 'msi-raider-18-hx-ai'}}, 'measured on another OS')):
            with self.subTest(message), self.assertRaisesRegex(ValueError, 'Locked serving profile was ' + message):
                profiles.check_job({'generator': role}, {**job, **change})
        # A role on a separately hosted service needs a profile frozen on that host; the job's own OS is not that host's.
        with self.assertRaisesRegex(ValueError, 'Locked serving profile was measured on another host'):
            profiles.check_job({'generator': {**role, 'resource_host': 'service-host'}}, job)
        campaign, _ = offload_attempt(self.path / 'service', physical_host='service-host')
        service = self.path / 'service-profile.json'
        profiles.write_profile(profiles.freeze(campaign, JOB_ID, ATTEMPT_ID, observed_placement={'gpu_layers': 20}), service)
        remote = bound_role(service, resource_host='service-host')
        profiles.check_job({'generator': remote}, {**job, 'input_files': [{'path': str(service), 'sha256': sha256_file(service)}],
                                                   'hardware': {'os_id': 'ubuntu-26.04-native', 'hardware_profile': 'msi-raider-18-hx-ai'}})
        # The declared OS must be the observed environment.
        campaign, _ = offload_attempt(self.path / 'wsl', host={'environment_kind': 'windows-11-wsl2-ubuntu-26.04', 'gpus': []})
        with self.assertRaisesRegex(ValueError, 'The declared OS and the observed environment disagree'):
            profiles.freeze(campaign, JOB_ID, ATTEMPT_ID)

    def test_zero_measured_requests_are_inconclusive(self):
        for name, rows in (('empty', []), ('warmups', [r for r in offload_rows() if r['warmup']]), ('errors', offload_rows(errors=3))):
            with self.subTest(name):
                probe = self.freeze(name, rows=rows)['probe']
                self.assertEqual(probe, {'outcome': 'failed', 'reason_codes': ['request_errors']} if name == 'errors'
                                 else {'outcome': 'inconclusive', 'reason_codes': ['no_measured_requests']})

    def test_a_hand_edited_probe_is_refused(self):
        profile = self.freeze('honest', placement=None)
        self.assertEqual(profile['probe']['outcome'], 'inconclusive')
        passing = self.freeze('passing')
        edits = [(profile, lambda p: p.update(probe={'outcome': 'passed', 'reason_codes': []})),
                 (profile, lambda p: (p['memory'].update(paging_observed={'value': None, 'nature': 'unavailable'}), p['throughput'].update(errors=3),
                                      p.update(probe={'outcome': 'passed', 'reason_codes': []}))),
                 (passing, lambda p: p['source'].update(result_status='failed')),
                 (passing, lambda p: p['throughput'].update(truncated=3))]
        for index, (base, edit) in enumerate(edits):
            with self.subTest(index):
                forged = copy.deepcopy(base)
                edit(forged)
                (self.path / 'forged.json').write_text(json.dumps(forged), encoding='utf-8')
                with self.assertRaisesRegex(ValueError, 'Serving profile probe does not follow from its values'):
                    profiles.load_profile(self.path / 'forged.json')

    def test_workload_must_be_an_approved_legal_shaped_export(self):
        for name, metadata in (('benchmark', offload_metadata(benchmark='category-smoke')), ('digest', offload_metadata(suite_sha256='9' * 64))):
            with self.subTest(name):
                profile = self.freeze(name, metadata=metadata)
                with self.assertRaisesRegex(ValueError, 'Locked serving profile was not measured on an approved legal-shaped workload'):
                    profiles.bind(bound_role('x.json'), profile)
        packets = digest(profiles.workload(PACKETS))
        profiles.bind(bound_role('x.json'), self.freeze('packets', metadata=offload_metadata(suite_sha256=packets)))
        self.assertEqual(sorted(profiles.approved_workloads()), sorted([packets, WORKLOAD_SHA256]))

    def test_freeze_reads_the_attempt_by_layout_and_checks_its_records(self):
        campaign, _ = offload_attempt(self.path / 'layout')
        state = read_json(campaign / 'campaign.json')
        state['jobs'][JOB_ID]['attempts'][0]['output'] = 'experiments\\offload-model-offloading-1\\jobs\\' + JOB_ID + '\\' + ATTEMPT_ID
        write_json(campaign / 'campaign.json', state)
        self.assertEqual(profiles.freeze(campaign, JOB_ID, ATTEMPT_ID, observed_placement={'gpu_layers': 20})['probe']['outcome'], 'passed')
        campaign, _ = offload_attempt(self.path / 'mixed', status='failed', result_status='succeeded')
        with self.assertRaisesRegex(ValueError, 'campaign record and result.json disagree'):
            profiles.freeze(campaign, JOB_ID, ATTEMPT_ID)
        campaign, _ = offload_attempt(self.path / 'plan')
        plan = read_json(campaign / 'plan.json')
        write_json(campaign / 'plan.json', {**plan, 'campaign_id': 'another-campaign'})
        with self.assertRaisesRegex(ValueError, 'plan.json does not match its plan_sha256'):
            profiles.freeze(campaign, JOB_ID, ATTEMPT_ID)
        self.assertEqual(self.freeze('moved', placement={'gpu_layers': 30})['probe'], {'outcome': 'failed', 'reason_codes': ['placement_mismatch']})

    def test_memory_reserves_are_checked_when_totals_are_known(self):
        for name, peaks, outcome in (('fits', {}, ('passed', [])), ('ram', {'system_used_gib_peak': 52.0}, ('failed', ['memory_reserve_exceeded'])),
                                     ('vram', {'gpu_used_mib_peak': 22500}, ('failed', ['memory_reserve_exceeded']))):
            with self.subTest(name):
                metadata = offload_metadata()
                metadata['telemetry'] = {**metadata['telemetry'], **peaks}
                profile = self.freeze(name, metadata=metadata)
                self.assertEqual(((profile['probe']['outcome'], profile['probe']['reason_codes']), profile['memory']['reserve_checked']), (outcome, True))
        profile = self.freeze('no-totals', host={'environment_kind': 'windows-11-native', 'gpus': [{'driver_version': '610.74'}]})
        self.assertEqual((profile['memory']['reserve_checked'], profile['memory']['totals']['host_ram_gib'], profile['probe']['outcome']),
                         (False, {'value': None, 'nature': 'unavailable'}, 'passed'))


class RoutingFixTests(RoutedCase):
    def test_router_error_is_a_route_key_and_confidence_is_rounded(self):
        answers = {'warehouse': {'choice': 'not-a-label'}}

        def answer(body):
            text = body['state']['messages'][0]['content']
            if 'warehouse' in text:
                return answers['warehouse']
            return {'choice': 'none', 'probabilities': {'none': 0.1234567, 'lexical': 0.8765433, 'insufficient_evidence': 0.0, 'insufficient_authority': 0.0}}
        with FakeSelector(answer) as selector:
            attempt, _, _ = self.routed(served(), roles={'selector': selector_role(selector.endpoint)})
        rows = {x['task_id']: x for x in lines(attempt / 'requests.jsonl')}
        failed = rows['f1-ledger-a']
        self.assertEqual((failed['status'], failed['error_type'], failed['route_error_type'], failed['route_fallback'], failed['route_selected']),
                         ('ok', None, 'ValueError', True, 'lexical-eligible'))
        self.assertEqual((rows['f8-manifest-a']['route_confidence'], rows['f8-manifest-a']['route_error_type']), (0.123457, None))
        self.assertEqual(len({frozenset(x) for x in rows.values()}), 1)

    def test_validate_refuses_unusable_confidence_and_labels(self):
        r, smoke = routing(), contracts.load_suite(SMOKE)
        arms = ['no-context', 'lexical-eligible']
        for selector in ({'router': {'kind': 'fixed', 'choice': 'lexical'}, 'policy': {'fallback': 'no-context', 'require_confidence': True}},
                         {**CATEGORY, 'policy': {**CATEGORY['policy'], 'require_confidence': True}}):
            with self.subTest(selector['router']['kind']), self.assertRaisesRegex(ValueError, 'require_confidence needs a selector that reports probabilities'):
                r.validate_selector(selector, arms, {}, smoke)
        for router in ({'kind': 'category', 'default_category': 'lexical', 'keywords': {'insufficient_evidence': ['ferry']}},
                       {'kind': 'category', 'default_category': 'insufficient_authority', 'keywords': {}},
                       {'kind': 'fixed', 'choice': 'insufficient_evidence'}):
            with self.subTest(router), self.assertRaisesRegex(ValueError, 'An in-process rule cannot use an insufficiency label'):
                r.validate_selector({**CATEGORY, 'router': router}, arms, {}, smoke)

    def test_calibration_follows_route_for_insufficiency_deferrals(self):
        r = routing()
        packets = contracts.load_suite(PACKETS)
        rows = [{'task_id': 't1', 'family_id': 'x1', 'confidence': 0.5, 'action': 'defer', 'route_reason': 'insufficient_evidence', 'quality_routed': 0.0,
                 'quality_fallback': 0.9, 'decision_correct': False, 'false_charge': False, 'dangerous_commitment': False, 'critical_errors': 0},
                {'task_id': 't2', 'family_id': 'x2', 'confidence': 0.9, 'action': 'route', 'route_reason': None, 'quality_routed': 0.8,
                 'quality_fallback': 0.5, 'decision_correct': True, 'false_charge': False, 'dangerous_commitment': False, 'critical_errors': 0}]
        # route() defers t1 at every threshold: 0.4 -> 0.0 + 0.8 = 0.8, 0.95 -> 0.0 + 0.5 = 0.5, so 0.4 wins. Crediting t1 by its
        # label confidence (covered at 0.4, fallback 0.9 at 0.95) would give 0.8 against 1.4 and pick 0.95.
        record = r.calibrate(rows, [0.4, 0.95], packets, calibration_lineage())
        self.assertEqual(record['abstain_threshold'], 0.4)
        self.assertEqual([x['covered'] for x in record['risk_coverage']], [1, 0])      # a deferral is never a covered commitment
        with self.assertRaisesRegex(ValueError, 'Calibration rows need'):
            r.calibrate([{k: v for k, v in rows[0].items() if k != 'action'}], [0.5], packets, calibration_lineage())

    def test_calibration_record_must_match_its_suite_and_selector(self):
        r = routing()
        packets, smoke = contracts.load_suite(PACKETS), contracts.load_suite(SMOKE)
        roles = {'generator': profiles.validate_role(generator(), 'generator'), 'selector': profiles.validate_role(selector_role(), 'selector')}
        good, block = honest_calibration(self.path / 'honest.json')

        def check(record, selector=None, suite=str(PACKETS)):
            write_json(self.path / 'record.json', record)
            selector = selector or served(abstain_threshold=record['abstain_threshold'])
            r.validate_selector({**selector, 'calibration': {**block, 'calibration_file': str(self.path / 'record.json'), 'suite': suite}},
                                ['no-context', 'lexical-eligible'], roles, smoke)
        check(good)
        # Every value can be copied from the case and the suite, and the record still does not follow from the attempts.
        families = sorted({m['family_id'] for m in packets['matters']['matters']})
        forged = {'schema_version': 1, 'kind': 'legal-routing-calibration', 'abstain_threshold': 0.4242, 'split_id': packets['lock']['split_id'],
                  'suite_lock_sha256': packets['lock_sha256'], 'families': families,
                  'risk_coverage': [{'threshold': 0.4242, 'tasks': 4, 'covered': 0, 'coverage': 0, 'errors': 0, 'risk': None, 'unsafe_commitments': 0,
                                     'unsafe_rate': None}],
                  'selector_sha256': r.selector_identity(served(), roles), 'routed_output_manifest_sha256': 'a' * 64,
                  'fallback_output_manifest_sha256': 'b' * 64, 'generator_sha256': profiles.bound_digest(roles['generator'])}
        edited = {**good, 'risk_coverage': [{**good['risk_coverage'][0], 'errors': good['risk_coverage'][0]['errors'] + 1}] + good['risk_coverage'][1:]}
        for name, record in (('forged', forged), ('edited risk', edited)):
            with self.subTest(name), self.assertRaisesRegex(ValueError, 'Calibration record does not follow from its calibration attempts'):
                check(record)
        with self.assertRaisesRegex(ValueError, 'Missing fields: fallback, routed'):      # the block must name both attempts
            r.validate_selector({**served(abstain_threshold=good['abstain_threshold']),
                                 'calibration': {'calibration_file': str(self.path / 'honest.json'), 'suite': str(PACKETS)}},
                                ['no-context', 'lexical-eligible'], roles, smoke)
        hand = {'schema_version': 1, 'kind': 'legal-routing-calibration', 'abstain_threshold': 0.4242, 'split_id': 'anything',
                'suite_lock_sha256': packets['lock_sha256'], 'families': ['zz-not-a-family'], 'risk_coverage': []}
        with self.assertRaises(ValueError):
            check(hand)
        changed_criteria = served(abstain_threshold=good['abstain_threshold'])
        changed_criteria['router']['criteria']['lexical'] = 'Another description'
        for name, record, selector, message in (
                ('split', {**good, 'split_id': 'other-split'}, None, 'Calibration record does not match its suite'),
                ('families', {**good, 'families': ['p1-quay']}, None, 'Calibration record does not match its suite'),
                ('threshold', {**good, 'abstain_threshold': 0.45}, None, 'not one of its calibrated thresholds'),
                ('tasks', {**good, 'risk_coverage': [{**e, 'tasks': 3} for e in good['risk_coverage']]}, None, 'Calibration record does not match its suite'),
                ('selector', good, changed_criteria, 'Calibration record belongs to another selector'),
                ('generator', {**good, 'generator_sha256': 'c' * 64}, None, 'Calibration record belongs to another generator'),
                ('lineage', {k: v for k, v in good.items() if k != 'routed_output_manifest_sha256'}, None, 'Missing fields')):
            with self.subTest(name), self.assertRaisesRegex(ValueError, message):
                check(record, selector)
        with self.assertRaisesRegex(ValueError, 'Export is limited to approved fixture suites'):
            check(good, suite=str(subset_suite(self.path / 'unapproved', ('f1-ledger-a',))))


class ReplayFixTests(ReplayCase):
    def copy_attempt(self, name):
        source = smoke_attempt()
        target = self.path / name / source.name
        shutil.copytree(source, target)
        return target

    def replay_from(self, attempt, tag, arms=('no-context', 'lexical-eligible')):
        out = self.path / tag
        out.mkdir()
        write_json(out / 'candidates.json', candidates(*arms))
        routing().export_suite(SMOKE, out / 'routing-suite.json')
        stderr = io.StringIO()
        with patch('sys.stdout', io.StringIO()), patch('sys.stderr', stderr):
            code = routing().main(['replay', '--suite', str(SMOKE), '--routing-suite', str(out / 'routing-suite.json'), '--attempt', str(attempt),
                                   '--candidates', str(out / 'candidates.json'), '--output', str(out / 'replay.json')])
        return code, stderr.getvalue(), out

    def test_replay_scores_come_from_pinned_outputs(self):
        _, _, original = self.replay_from(smoke_attempt(), 'original')
        edited = self.copy_attempt('detail')
        details = lines(edited / 'local/score-detail.jsonl')
        for d in details:
            d['criteria'] = {k: True for k in d['criteria']}
            d['choice'] = d['gold_recommendation']
        (edited / 'local/score-detail.jsonl').write_text(''.join(json.dumps(d) + '\n' for d in details), encoding='utf-8', newline='\n')
        code, _, out = self.replay_from(edited, 'detail-out')
        self.assertEqual(code, 0)
        self.assertEqual(read_json(out / 'replay.json'), read_json(original / 'replay.json'))      # recomputed from the pinned outputs
        self.assertEqual(read_json(out / 'replay.provenance.json')['outcomes'], read_json(original / 'replay.provenance.json')['outcomes'])
        for name, edit in (('timings', lambda rows: [{**x, 'usable_memo_s': 0.001} for x in rows]),
                           ('dropped', lambda rows: [x for x in rows if x['task_id'] != 'f2-berth-a'])):
            with self.subTest(name):
                changed = self.copy_attempt(name)
                rows = edit(lines(changed / 'requests.jsonl'))
                (changed / 'requests.jsonl').write_text(''.join(json.dumps(x) + '\n' for x in rows), encoding='utf-8', newline='\n')
                code, stderr, _ = self.replay_from(changed, name + '-out')
                self.assertEqual(code, 2)
                self.assertIn('Output manifest file changed: requests.jsonl', stderr)

    def test_replay_needs_one_fixed_generator(self):
        second = self.path / 'attempts2'
        revised = generation_attempt_with(second, 'r2-generator', SMOKE, ('lexical-eligible',), model_revision='r2')
        write_json(self.path / 'candidates.json', {'no-context': CANDIDATE, 'lexical-eligible': CANDIDATE})
        routing().export_suite(SMOKE, self.path / 'routing-suite.json')
        base = ['replay', '--suite', str(SMOKE), '--routing-suite', str(self.path / 'routing-suite.json'), '--candidates', str(self.path / 'candidates.json'),
                '--output', str(self.path / 'replay.json')]
        with patch('sys.stdout', io.StringIO()), patch('sys.stderr', io.StringIO()) as stderr:
            self.assertEqual(routing().main(base + ['--attempt', str(smoke_attempt()), '--attempt', str(revised)]), 2)
        self.assertIn('Replay attempts do not share one fixed generator', stderr.getvalue())
        write_json(self.path / 'candidates.json', {'no-context': {**CANDIDATE, 'model_revision': 'r9'}, 'lexical-eligible': CANDIDATE})
        with patch('sys.stdout', io.StringIO()), patch('sys.stderr', io.StringIO()) as stderr:
            self.assertEqual(routing().main(base + ['--attempt', str(smoke_attempt())]), 2)
        self.assertIn('Candidate does not match the fixed generator: no-context.model_revision', stderr.getvalue())

    def test_strategy_names_and_common_coverage(self):
        r = routing()
        tasks = [{'id': t, 'category': 'legal', 'messages': [{'role': 'user', 'content': 'QUESTION ' + t}]} for t in ('a', 'b', 'c', 'd')]
        rows = [('a', 'no-context', 1.0, 1.0), ('b', 'no-context', 1.0, 1.0), ('c', 'no-context', 0.5, 1.0),
                ('a', 'lexical', 0.9, 3.0), ('b', 'lexical', 0.9, 3.0), ('c', 'lexical', 0.9, 3.0), ('d', 'lexical', 0.2, 3.0)]
        manifest = {'suite_sha256': '0' * 64, 'candidate_fingerprints': {}, 'rows': [
            {'task_id': t, 'candidate': c, 'quality': q, 'latency_s': latency, 'cost_usd': 0} for t, c, q, latency in rows]}
        table = r.evaluate(manifest, tasks, [{'name': 'fixed:no-context'}, {'name': 'fixed:lexical'}], {'quality_weight': 1})
        self.assertEqual([(x['mean_quality'], x['common_tasks'], x['common_mean_quality'], x['common_mean_latency_s']) for x in table],
                         [(0.833333, 3, 0.833333, 1.0), (0.725, 3, 0.9, 3.0)])
        decisions = {t['id']: {'action': 'route', 'selected': 'reference', 'fallback_used': False, 'confidence': 0.9, 'router_s': 0.0} for t in tasks}
        for strategies, message in (([{'name': 'fixed:no-context'}, {'name': 'fixed:no-context'}], 'Duplicate strategy name'),
                                    ([{'name': 'selector', 'decisions': decisions}], 'The reference arm is not a routing candidate'),
                                    ([{'name': 'random-matched', 'match': 'nothing'}], 'random-matched names an unknown strategy')):
            with self.subTest(message), self.assertRaisesRegex(ValueError, message):
                r.evaluate(manifest, tasks, strategies, {})

    def test_sidecar_is_verified_against_its_attempts(self):
        r = routing()
        suite_path, manifest_path, provenance_path, candidates_path = self.replay()
        m, p = read_json(manifest_path), read_json(provenance_path)
        ts, smoke, pool, attempts = read_json(suite_path), contracts.load_suite(SMOKE), read_json(candidates_path), [smoke_attempt()]
        r.verify_replay(m, p, ts, pool, smoke, attempts)
        flipped = [dict(o, false_charge=False, dangerous_commitment=False, all_pass=True, decision_correct=True) for o in p['outcomes']]
        high = {**m, 'rows': [dict(x, quality=1.0) for x in m['rows']]}
        bad = {**m, 'rows': [dict(x, quality=7.5, latency_s=-3) for x in m['rows']]}
        for name, manifest, provenance, message in (
                ('flipped', m, {**p, 'outcomes': flipped}, 'Replay does not follow from its source attempts'),
                ('emptied', m, {**p, 'outcomes': []}, 'Replay outcomes do not match the replay rows'),
                ('extra', m, {**p, 'outcomes': p['outcomes'] + [dict(p['outcomes'][0], task_id='f9-none-a')]}, 'Replay outcomes do not match the replay rows'),
                ('attempt ids', m, {**p, 'attempts': [dict(a, inference_attempt_id='0' * 32) for a in p['attempts']]},
                 'Replay does not follow from its source attempts'),
                ('qualities', high, {**p, 'replay_manifest_sha256': digest(high)}, 'Replay does not follow from its source attempts'),
                ('ranges', bad, {**p, 'replay_manifest_sha256': digest(bad)}, 'Replay row values out of range'),
                ('calibration', m, {**p, 'calibration': 'anything'}, 'calibration')):
            with self.subTest(name), self.assertRaisesRegex(ValueError, message):
                r.verify_replay(manifest, provenance, ts, pool, smoke, attempts)
        # A calibration record named at replay time is recorded by digest and marks a selector evaluated on its families.
        record = calibration_record(smoke)
        sha = r.write_calibration(record, self.path / 'calibration.json')
        with patch('sys.stdout', io.StringIO()):
            self.assertEqual(r.main(['replay', '--suite', str(SMOKE), '--routing-suite', str(suite_path), '--attempt', str(smoke_attempt()),
                                     '--candidates', str(candidates_path), '--output', str(self.path / 'calibrated.json'),
                                     '--calibration', str(self.path / 'calibration.json')]), 0)
        self.assertEqual(read_json(self.path / 'calibrated.provenance.json')['calibration'], sha)
        decisions = {t['id']: {'action': 'route', 'selected': 'no-context', 'fallback_used': False, 'confidence': 0.9, 'router_s': 0.0} for t in ts['tasks']}
        families = {m_['matter_id']: m_['family_id'] for m_ in smoke['matters']['matters']}
        table = r.evaluate(m, ts['tasks'], [{'name': 'fixed:no-context'}, {'name': 'selector', 'decisions': decisions, 'thresholds': [0.5]}], {},
                           calibration=record, families=families)
        self.assertEqual([x['calibration_overlap'] for x in table], [None, True])

    def test_commands_refuse_scanned_and_repository_outputs(self):
        r = routing()
        suite_path, _, _, candidates_path = self.replay()
        campaign, _ = offload_attempt(self.path / 'offload')
        for target in (self.path / 'reports' / 'x.json', self.path / 'model_judgment' / 'x.json', ROOT / 'replay-output.json',
                       smoke_attempt() / 'extra' / 'x.json'):
            with self.subTest(target=str(target)):
                for argv in (['export', '--suite', str(SMOKE), '--output', str(target)],
                             ['replay', '--suite', str(SMOKE), '--routing-suite', str(suite_path), '--attempt', str(smoke_attempt()),
                              '--candidates', str(candidates_path), '--output', str(target)]):
                    with patch('sys.stderr', io.StringIO()) as stderr, patch('sys.stdout', io.StringIO()):
                        self.assertEqual(r.main(argv), 2)
                    self.assertIn('must not be written', stderr.getvalue())
                for argv in (['workload', '--suite', str(SMOKE), '--output', str(target)],
                             ['freeze', '--campaign-dir', str(campaign), '--job-id', JOB_ID, '--attempt-id', ATTEMPT_ID, '--output', str(target)]):
                    with patch('sys.stdout', io.StringIO()), self.assertRaisesRegex(ValueError, 'must not be written'):
                        profiles.main(argv)
                self.assertFalse(target.exists())
        self.assertFalse((ROOT / 'replay-output.json').exists())

    def test_small_review_items(self):
        r, g = routing(), grading()
        detail = {'grading_status': 'scored', 'choice': 'charge', 'gold_recommendation': 'charge', 'criteria': {k: True for k in fixture.CRITERIA},
                  'errors': [{'code': 'wrong_version', 'critical': True}], 'verifier_codes': [], 'reviewed_dimensions': {}, 'dismissed': ['wrong_version']}
        self.assertEqual(r.outcome(detail)['critical_errors'], 0)
        self.assertEqual(r.outcome({**detail, 'dismissed': []})['critical_errors'], 1)
        self.assertTrue(g.all_pass(detail))
        with self.assertRaisesRegex(ValueError, 'Approved suites file not found'):
            contracts.approved_suites(self.path)


class ReReviewTests(TempCase):
    def test_honest_calibration_plans_and_a_routed_threshold_run_is_refused(self):
        r = routing()
        record, block = honest_calibration(self.path / 'calibration.json')
        roles = {'generator': generator(), 'selector': selector_role()}
        (job,) = self.plan('honest', 'generation', {'suite': str(SMOKE), 'arms': ['no-context', 'lexical-eligible'], 'roles': roles,
                                                    'selector': {**served(abstain_threshold=record['abstain_threshold']), 'calibration': block}})['jobs']
        self.assertIn(str(Path(block['routed']['output_manifest']).resolve()), {f['path'] for f in job['input_files']})
        # Item 4: the routed calibration attempt must have run without a threshold or required confidence.
        routed, fallback = calibration_attempts()
        with FakeSelector(lambda body: by_question(body, {'kiln': 'none'}, 0.8)) as selector, FakeGenerator('{}') as fake, NO_GPU:
            job = job_for(PACKETS, {'arms': ['no-context', 'lexical-eligible'], 'selector': served(require_confidence=True), 'parse_retries': 0,
                                    'roles': {'generator': generator(fake.endpoint), 'selector': selector_role(selector.endpoint)}}, job_id='legal-confident')
            out = self.path / 'confident'
            out.mkdir()
            atomic_json(out / 'job.json', job)
            atomic_json(out / 'result.json', {**legal.execute(job, out, ROOT), 'attempt_id': out.name})
        for call in (lambda: r.calibration_rows(out, fallback, 'lexical-eligible'), lambda: r.calibration_lineage(out, fallback, 'lexical-eligible')):
            with self.assertRaisesRegex(ValueError, 'The routed calibration attempt must run without a threshold or required confidence'):
                call()

    def test_a_deferral_is_a_covered_task_with_quality_zero(self):
        tasks = [{'id': t, 'category': 'legal', 'messages': [{'role': 'user', 'content': 'QUESTION ' + t}]} for t in 'abcd']
        rows = [('a', 'A', 0.9), ('b', 'A', 0.9), ('c', 'A', 0.9), ('d', 'A', 0.1), ('a', 'B', 1.0), ('b', 'B', 1.0), ('c', 'B', 1.0), ('d', 'B', 0.0)]
        manifest = {'suite_sha256': '0' * 64, 'candidate_fingerprints': {}, 'rows': [
            {'task_id': t, 'candidate': c, 'quality': q, 'latency_s': 1.0, 'cost_usd': 0} for t, c, q in rows]}
        decisions = {t: {'action': 'route', 'selected': 'B', 'fallback_used': False, 'confidence': 0.9, 'router_s': 0.0} for t in 'abc'}
        decisions['d'] = {'action': 'defer', 'selected': None, 'fallback_used': False, 'confidence': 0.3, 'router_s': 0.0}
        table = routing().evaluate(manifest, tasks, [{'name': 'fixed:A'}, {'name': 'fixed:B'}, {'name': 'selector', 'decisions': decisions}], {})
        self.assertEqual([(x['strategy'], x['covered'], x['abstentions'], x['mean_quality'], x['common_tasks'], x['common_mean_quality'], x['mean_latency_s'])
                          for x in table], [('fixed:A', 4, 0, 0.7, 4, 0.7, 1.0), ('fixed:B', 4, 0, 0.75, 4, 0.75, 1.0), ('selector', 4, 1, 0.75, 4, 0.75, 1.0)])

    def test_the_sidecar_names_the_review_of_a_score_attempt(self):
        r, g = routing(), grading()
        source = smoke_attempt()
        manifest = str(source / 'local/output-manifest.json')
        packet = self.path / 'packet'
        g.main(['packet', '--output-manifest', manifest, '--output', str(packet)])
        items = read_json(packet / 'review-packet.json')['items']
        write_json(packet / 'review.json', {
            'schema_version': 1, 'kind': 'legal-review', 'reviewer': {'kind': 'human', 'reviewer_token': '0123456789abcdef0123456789abcdef', 'blind': True,
                                                                       'prompt_version': None},
            'rubric_version': 'original-smoke-rubric-2', 'packet_sha256': read_json(packet / 'review-key.json')['packet_sha256'],
            'verdicts': [{'item_id': i['item_id'], 'dimension': d, 'verdict': 'pass', 'critical': False} for i in items for d in g.PENDING_DIMENSIONS],
            'adjudications': [{'item_id': i['item_id'], 'code': c, 'upheld': True} for i in items for c in i['critical_codes']]})
        found = {}
        for name, extra in (('plain', {}), ('reviewed', {'review_file': str(packet / 'review.json'), 'review_key': str(packet / 'review-key.json')})):
            job = job_for(SMOKE, {'output_manifest': manifest, **extra}, mode='score', job_id='legal-score-' + name)
            out = self.path / name
            out.mkdir()
            atomic_json(out / 'job.json', job)
            legal.execute(job, out, ROOT)
            found[name] = r.rows_by_candidate(out)['no-context']['lineage']['reviewer_fingerprint']
        self.assertIsNone(found['plain'])
        self.assertRegex(found['reviewed'], r'\A[0-9a-f]{64}\Z')
        self.assertIn('reviewer_fingerprint', r.ATTEMPT_KEYS)

    def test_check_output_finds_repositories_and_folds_case(self):
        repository = self.path / 'checkout'
        (repository / 'nested/worktree').mkdir(parents=True)
        (repository / '.git').mkdir()
        (self.path / 'worktree-file').mkdir()
        (self.path / 'worktree-file/.git').write_text('gitdir: elsewhere\n', encoding='utf-8')
        for target in (repository / 'docs/results/x.json', repository / 'results/x.json', repository / 'nested/worktree/x.json',
                       self.path / 'worktree-file/x.json', self.path / 'Reports/x.json', self.path / 'MODEL_JUDGMENT/x.json'):
            with self.subTest(str(target)), self.assertRaisesRegex(ValueError, 'must not be written'):
                contracts.check_output(target)
        for target in (self.path / 'out/x.json', self.path / 'my-reports-2026/x.json'):
            self.assertEqual(contracts.check_output(target), target.resolve())

    def test_profile_review_details(self):
        # (a) paging cannot be observed where the swap counters mean nothing
        campaign, _ = offload_attempt(self.path / 'win', metadata=attested(paging=None))
        profile = profiles.freeze(campaign, JOB_ID, ATTEMPT_ID, observed_placement={'gpu_layers': 20})
        forged = copy.deepcopy(profile)
        forged['memory']['paging_observed'] = {'value': False, 'nature': 'observed'}
        forged['probe'] = {'outcome': 'passed', 'reason_codes': []}
        (self.path / 'forged.json').write_text(json.dumps(forged), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'Paging cannot be observed on windows-11-native'):
            profiles.load_profile(self.path / 'forged.json')
        # (b) a WSL guest cannot see the host paging its VM: it needs the attestation too
        wsl = 'windows-11-wsl2-ubuntu-26.04'
        for name, metadata, leaf in (('wsl', attested(paging=None), {'value': None, 'nature': 'unavailable'}),
                                     ('wsl-attested', attested(paging='none'), {'value': False, 'nature': 'attested'})):
            with self.subTest(name):
                campaign, _ = offload_attempt(self.path / name, os_id=wsl, telemetry=swap(1, 1, 1), metadata=metadata)
                self.assertEqual(profiles.freeze(campaign, JOB_ID, ATTEMPT_ID, observed_placement={'gpu_layers': 20})['memory']['paging_observed'], leaf)
        # (c) public metadata says when a qualification rests on attestation
        _, path = frozen(self.path / 'bound')
        public = profiles.public_role(profiles.validate_role(bound_role(path), 'generator'))
        self.assertEqual((public['qualified'], public['qualified_by_attestation']), (True, True))
        self.assertEqual(profiles.public_role(generator())['qualified_by_attestation'], False)
        # (d) placeholders are anchored and case-sensitive
        for value, leaf in (('mastodon-tok-2', 'mastodon-tok-2'), ('replace-me-1', 'replace-me-1'), ('REPLACE_WITH_REVISION', None), ('TODO-1', None)):
            with self.subTest(value=value):
                metadata = offload_metadata()
                metadata['config'] = {**metadata['config'], 'tokenizer_revision': value}
                campaign, _ = offload_attempt(self.path / ('tok-' + value), metadata=metadata)
                self.assertEqual(profiles.freeze(campaign, JOB_ID, ATTEMPT_ID)['template']['tokenizer_revision']['value'], leaf)
        # (e) a non-chat role needs no chat template or tokenizer revision to bind
        metadata = offload_metadata()
        metadata['config'] = {k: v for k, v in metadata['config'].items() if k not in ('chat_template_sha256', 'tokenizer_revision')}
        campaign, _ = offload_attempt(self.path / 'embed', metadata=metadata)
        embed_profile = self.path / 'embed-profile.json'
        profiles.write_profile(profiles.freeze(campaign, JOB_ID, ATTEMPT_ID, observed_placement={'gpu_layers': 20}), embed_profile)
        embedder = {'role': 'embedder', 'serving': 'external', 'capability': 'embedding', 'deployment_id': 'local-embedder', 'model': 'fake-embed',
                    'protocol': 'json', 'endpoint': 'http://127.0.0.1:9/v1/embed', 'accelerator': 'cpu', 'timeout_s': 5, 'dimensions': 8,
                    'platform': 'lmstudio', 'backend_version': '0.4.28+2', 'artifact_sha256': '5' * 64, 'quantization': 'Q8_0', 'model_revision': '4' * 40,
                    'qualification': {'serving_profile': str(embed_profile)}}
        self.assertTrue(profiles.public_role(profiles.validate_role(embedder, 'embedder'))['qualified'])
        with self.assertRaisesRegex(ValueError, 'chat_template_sha256 is unavailable in the locked profile'):
            profiles.validate_role(bound_role(embed_profile, template_sha256=None, tokenizer_revision=None), 'generator')
        # (f) the generator digest of a calibration record covers the generator's serving profile
        role = bound_role(path)
        self.assertEqual(profiles.bound_digest(role), profiles.profile_digest(role, [{'path': str(path), 'sha256': sha256_file(path)}]))
        self.assertNotEqual(profiles.bound_digest(role), profiles.profile_digest(role))


def generation_attempt_with(directory, name, lock, arms, **changes):
    """`generation_attempt` with a changed generator role (another model revision, for example)."""
    suite = contracts.load_suite(lock)

    def respond(body):
        content = body['messages'][1]['content']
        matter = next(m for m in suite['matters']['matters'] if 'MATTER ' + m['matter_id'] + '\n' in content)
        return json.dumps(fixture.draft(matter, suite['corpus']))
    with FakeGenerator(respond=respond) as fake, NO_GPU:
        job = job_for(lock, {'arms': list(arms), 'roles': {'generator': generator(fake.endpoint, **changes)}}, job_id='legal-' + name)
        out = Path(directory) / name
        out.mkdir(parents=True)
        atomic_json(out / 'job.json', job)
        result = legal.execute(job, out, ROOT)
        atomic_json(out / 'result.json', {**result, 'attempt_id': out.name})
    return out


if __name__ == '__main__':
    unittest.main()
