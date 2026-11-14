"""Package F: one data classification, the six transport and publication gates, the strict legal projection, canonical bundle
bytes. Nothing is published: publication runs against temporary Git repositories and a fake API. No private-matter data
exists: a private or unverified suite is a relabelled or edited copy of the fictional smoke suite."""
import contextlib
import copy
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid
from unittest.mock import patch

from llm_eval.common import digest, read_json, sha256_file, write_json
from llm_eval.core.contracts import atomic_json, config_hash
from llm_eval.experiments import get_experiment
from llm_eval.experiments import legal_benchmark as legal
from llm_eval.experiments.legal_benchmark import contracts, fixture, grading, retrieval
from llm_eval.experiments.legal_benchmark import reporting as lr
from llm_eval.orchestration import scheduler, worker
from llm_eval.orchestration.planner import compile_campaign, revision
from llm_eval.orchestration.scheduler import initialize, run_campaign
from llm_eval.reporting import experiment as rexp
from llm_eval.reporting.experiment import build_report, canonical_csv, canonical_gzip, canonical_json, finalize_campaign
from llm_eval.reporting.publish import git as real_git, publish_report, validate_bundle
from tests.test_legal_workflow import ANALYSIS, FakeGenerator, generator, subset_suite
from tests.test_reporting import FakeGitHub

ROOT = Path(__file__).resolve().parents[1]
SUITE = ROOT / 'experiments/legal-benchmark/workloads/original-smoke'
LOCK = SUITE / 'suite.lock.json'
PACKETS = ROOT / 'experiments/legal-benchmark/workloads/original-packets/suite.lock.json'
CANARY = 'CANARY7f3a91'
SSH = {'transport': 'ssh', 'physical_host_id': 'remote-test-host', 'host': 'remote-test-alias', 'python': 'python3',
       'repo_root': '/srv/llm-eval', 'work_root': '/srv/work'}
BUNDLE_FILES = ['README.md', 'legal-summary.json', 'manifest.json', 'raw/measurements.jsonl.gz', 'resolved-config.json', 'summary.csv',
                'summary.json']


def lines(path):
    return [json.loads(line) for line in Path(path).read_text(encoding='utf-8').splitlines() if line.strip()]


def tree(directory):
    return {p.relative_to(directory).as_posix(): sha256_file(p) for p in sorted(Path(directory).rglob('*')) if p.is_file()}



def write_plan(directory, plan):
    """Write an edited stored plan with its digest recomputed (the plan-drift check refuses a stale one)."""
    from llm_eval.core.contracts import config_hash
    write_json(Path(directory) / 'plan.json', {**plan, 'plan_sha256': config_hash({k: v for k, v in plan.items() if k != 'plan_sha256'})})

def relocked(source, directory, data_class=None, **lock_changes):
    """A copy of a suite, relabelled to `data_class` if given and relocked: a different suite with a consistent lock."""
    shutil.copytree(Path(source).parent, directory)
    lock = read_json(directory / 'suite.lock.json')
    if data_class:
        for name in ('matters.json', 'corpus.json', 'rubric.json'):
            value = read_json(directory / name)
            value['data_class'] = data_class
            write_json(directory / name, value)
    new = contracts.make_lock(directory, benchmark_id=lock['benchmark_id'], revision=lock_changes.pop('revision', 'operator-copy'),
                              split_id=lock['split_id'], data_class=data_class or lock['data_class'],
                              jurisdiction_profile=lock['jurisdiction_profile'],
                              manifests={'matters': 'matters.json', 'corpus': 'corpus.json', 'rubric': 'rubric.json'})
    new.update(lock_changes)
    write_json(directory / 'suite.lock.json', new)
    return directory / 'suite.lock.json'


def bundle_dir(report):
    spec = read_json(report / 'publication.json')
    return report / 'bundle' / spec['report_path'], spec


def raw_records(report):
    dest, _ = bundle_dir(report)
    return [json.loads(line) for line in gzip.decompress((dest / 'raw/measurements.jsonl.gz').read_bytes()).decode().splitlines() if line]


def all_bytes(directory):
    return b''.join(p.read_bytes() for p in sorted(Path(directory).rglob('*')) if p.is_file()) + \
        '\n'.join(p.relative_to(directory).as_posix() for p in sorted(Path(directory).rglob('*'))).encode()


def cli(*argv):
    """`llm-eval report|publish-results ...` in-process: (exit code, stdout + stderr)."""
    from llm_eval.reporting.cli import main
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = main(list(argv))
        except SystemExit as exc:
            code = exc.code
    return code, out.getvalue() + err.getvalue()


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name)
        gpu = patch('llm_eval.telemetry.gpu_snapshot', return_value=[])
        gpu.start()
        self.addCleanup(gpu.stop)
        write_json(self.path / 'inventory.json', {
            'targets': {'local': {'transport': 'local', 'physical_host_id': 'legal-test-host', 'lock_root': str(self.path / 'worker-locks')},
                        'remote': SSH},
            'hardware_configs': {'native': {'target': 'local', 'hardware_profile': 'msi-raider-18-hx-ai', 'os_id': 'ubuntu-26.04-native'},
                                 'remote': {'target': 'remote', 'hardware_profile': 'msi-raider-18-hx-ai', 'os_id': 'ubuntu-26.04-native'}}})

    def plan(self, name, mode='smoke', parameters=None, hardware='native', reporting=None, phase='legal', case_id=None):
        parameters = {'suite': str(LOCK), 'synthetic': True} if parameters is None else parameters
        write_json(self.path / f'{name}.json', {'id': case_id or name, 'parameters': parameters})
        campaign = {'schema_version': 2, 'id': name, 'inventory': 'inventory.json', 'phases': [
            {'id': phase, 'experiments': [{'id': 'legal-benchmark', 'version': 1, 'mode': mode, 'cases': [f'{name}.json'],
                                           'hardware_configs': [hardware]}]}]}
        if reporting is not None:
            campaign['reporting'] = reporting
        write_json(self.path / f'{name}-campaign.json', campaign)
        return compile_campaign(self.path / f'{name}-campaign.json', ROOT)

    def rpc(self, target, payload, root, timeout=60):
        if payload['action'] != 'run':
            return {'ok': True}
        out = Path(payload['output'])
        result = {**get_experiment(payload['job']['experiment_id']).execute(payload['job'], out, Path(payload['root'])),
                  'attempt_id': payload['owner']}
        atomic_json(out / 'result.json', result)
        return result

    def run_plan(self, plan, name='out', rpc=None):
        with patch('llm_eval.orchestration.resources.lock_root', return_value=self.path / 'locks'), \
                patch('llm_eval.orchestration.transport.rpc', side_effect=rpc or self.rpc):
            directory = initialize(plan, self.path / name)
            code = run_campaign(directory)
        return directory, code

    def resume(self, directory, rpc=None, **options):
        with patch('llm_eval.orchestration.resources.lock_root', return_value=self.path / 'locks'), \
                patch('llm_eval.orchestration.transport.rpc', side_effect=rpc or self.rpc):
            return run_campaign(directory, **options)

    def smoke(self, lock=LOCK, name='smoke', **plan_options):
        directory, code = self.run_plan(self.plan(name, parameters={'suite': str(lock), 'synthetic': True}, **plan_options), name)
        self.assertEqual(code, 0)
        return directory

    @staticmethod
    def receipt(directory):
        (receipt,) = read_json(directory / 'campaign.json')['reports'].values()
        return receipt

    def report(self, directory):
        receipt = self.receipt(directory)
        self.assertEqual(receipt['status'], 'generated', receipt)
        return directory / receipt['report']

    @staticmethod
    def experiment_dir(directory):
        (exp,) = read_json(directory / 'plan.json')['experiments']
        return directory / 'experiments' / exp['experiment_run_id']

    @staticmethod
    def attempt(directory, index=0):
        state = read_json(directory / 'campaign.json')
        record = list(state['jobs'].values())[index]
        return directory / record['attempts'][-1]['output']

    def refinalize(self, directory):
        state = read_json(directory / 'campaign.json')
        state['reports'] = {}
        write_json(directory / 'campaign.json', state)
        return next(iter(finalize_campaign(directory).values()))

    @staticmethod
    def rereceipt(directory):
        """Record the current attempt files in campaign.json, as the coordinator does when an attempt finishes (for a test that
        edits attempt files on purpose and wants a report from them)."""
        state = read_json(directory / 'campaign.json')
        for record in state['jobs'].values():
            for attempt in record['attempts']:
                attempt.update(lr.attempt_receipt(directory / attempt['output']))
        write_json(directory / 'campaign.json', state)

    def copy(self, name='copy', data_class=None, **changes):
        return relocked(LOCK, self.path / name, data_class, **changes)

    def authorize(self, directory):
        exp = self.experiment_dir(directory).name
        return lr.authorize(directory, exp, 'test-reviewer', confirm=lambda text: True)

    # A temporary repository and a fake API -------------------------------------------------------------------------

    def repository(self, autocrlf='false', attributes=None, approved=None):
        bare, repo = self.path / 'remote.git', self.path / 'repo'

        def run(*args):
            subprocess.run(args, check=True, capture_output=True)
        run('git', 'init', '--bare', str(bare))
        run('git', 'init', '-b', 'main', str(repo))
        run('git', '-C', str(repo), 'config', 'core.autocrlf', autocrlf)
        (repo / '.gitattributes').write_bytes(attributes if attributes is not None else (ROOT / '.gitattributes').read_bytes())
        (repo / 'README.md').write_text('# Test repository\n', encoding='utf-8', newline='\n')
        target = repo / contracts.APPROVED_SUITES
        target.parent.mkdir(parents=True)
        target.write_bytes(approved if approved is not None else (ROOT / contracts.APPROVED_SUITES).read_bytes())
        run('git', '-C', str(repo), 'add', '-A')
        run('git', '-C', str(repo), '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.com', 'commit', '-m', 'initial')
        run('git', '-C', str(repo), 'remote', 'add', 'origin', str(bare))
        run('git', '-C', str(repo), 'push', '-u', 'origin', 'main')
        return repo, bare

    @staticmethod
    def publish(report, repo, api, dry_run=False):
        def fixture_git(root, *args, **kwargs):
            if args == ('remote', 'get-url', 'origin'):
                return 'https://github.com/asanderson/llm-eval.git'
            return real_git(root, *args, **kwargs)
        with patch('llm_eval.reporting.publish.git', side_effect=fixture_git), patch.dict(os.environ, {'GH_TOKEN': '', 'GITHUB_TOKEN': ''}):
            return publish_report(report, repo, dry_run=dry_run, api=api)


class RecordingGitHub(FakeGitHub):
    def __init__(self):
        super().__init__()
        self.bodies = []

    def request(self, method, path, body):
        self.bodies.append({'method': method, **body})
        return super().request(method, path, body)


# 1. Classification and the six gates ----------------------------------------------------------------------------------

class GateTests(Base):
    def test_classification_is_derived_from_planned_inputs_only(self):
        shipped = compile_campaign(ROOT / 'campaigns/legal-smoke.json', ROOT)['jobs'][0]
        self.assertEqual({k: lr.classify(shipped)[k] for k in ('level', 'verified', 'approved', 'fixture_export', 'data_class', 'execution_kind')},
                         {'level': 'approved', 'verified': True, 'approved': True, 'fixture_export': True, 'data_class': 'public-synthetic',
                          'execution_kind': 'fixture'})
        packets = {'mode': 'retrieval', 'parameters': {'suite': str(PACKETS), 'synthetic': True, 'arms': ['lexical']},
                   'input_files': [{'path': str(PACKETS), 'sha256': sha256_file(PACKETS)}]}
        self.assertEqual(lr.classify(packets)['level'], 'approved')
        copy_lock = self.copy()
        (job,) = self.plan('copy', parameters={'suite': str(copy_lock), 'synthetic': True})['jobs']
        self.assertEqual((lr.classify(job)['level'], lr.classify(job)['reason']), ('declared', 'not_approved'))
        # A label on the job or its parameters is not an input of the classification.
        labelled = {**copy.deepcopy(job), 'public': True, 'approved': True, 'data_class': 'public-synthetic'}
        labelled['parameters'].update(public=True)
        self.assertEqual(lr.classify(labelled)['level'], 'declared')
        refused = []
        edited = copy.deepcopy(job)
        edited['input_files'] = [{**f, 'sha256': '0' * 64} if f['path'] == job['parameters']['suite'] else f for f in edited['input_files']]
        refused.append(('edited planned digest', edited, 'planned_digest_mismatch'))
        missing = copy.deepcopy(job)
        missing['parameters']['suite'] = str(self.path / 'absent.lock.json')
        refused.append(('missing lock', missing, 'lock_missing'))
        unknown = {**copy.deepcopy(job), 'mode': 'live-review'}
        refused.append(('unknown mode', unknown, 'unknown_mode'))
        listed = copy.deepcopy(job)
        listed['parameters']['suite'] = [job['parameters']['suite']]
        refused.append(('suite not a path string', listed, 'lock_missing'))
        for name, value, reason in refused:
            with self.subTest(name):
                found = lr.classify(value)
                self.assertEqual((found['level'], found['verified'], found['reason']), ('refused', False, reason))
                self.assertFalse(lr.data_policy(value)['admit'])
        # The same lock path relocked after planning: the plan still names the old digest.
        rubric = read_json(copy_lock.parent / 'rubric.json')
        rubric['matters'][0]['recommendation'] = 'defer'
        write_json(copy_lock.parent / 'rubric.json', rubric)
        relocked_lock = read_json(copy_lock)
        write_json(copy_lock, {**contracts.make_lock(copy_lock.parent, benchmark_id=relocked_lock['benchmark_id'], revision='operator-copy',
                                                     split_id=relocked_lock['split_id'], data_class='public-synthetic',
                                                     jurisdiction_profile=relocked_lock['jurisdiction_profile'],
                                                     manifests={'matters': 'matters.json', 'corpus': 'corpus.json', 'rubric': 'rubric.json'})})
        found = lr.classify(job)
        self.assertEqual((found['level'], found['verified'], found['reason']), ('refused', False, 'planned_digest_mismatch'))
        # A stale pinned file under an unchanged lock.
        stale = self.copy('stale')
        (job2,) = self.plan('stale', parameters={'suite': str(stale), 'synthetic': True})['jobs']
        with (stale.parent / 'corpus.json').open('a', encoding='utf-8') as handle:
            handle.write(' ')
        self.assertEqual(lr.classify(job2)['reason'], 'lock_invalid')
        # Private class: verified and refused by class.
        private = self.copy('private', 'private-matter')
        job3 = {**copy.deepcopy(job), 'parameters': {'suite': str(private), 'synthetic': True},
                'input_files': [{'path': str(private), 'sha256': sha256_file(private)}]}
        self.assertEqual({k: lr.classify(job3)[k] for k in ('level', 'verified', 'reason', 'data_class')},
                         {'level': 'refused', 'verified': True, 'reason': 'private_matter', 'data_class': 'private-matter'})
        # The approved list of another root approves for that root only.
        other = self.path / 'root'
        target = other / contracts.APPROVED_SUITES
        target.parent.mkdir(parents=True)
        approved = read_json(ROOT / contracts.APPROVED_SUITES)
        third = self.copy('third')
        (job4,) = self.plan('third', parameters={'suite': str(third), 'synthetic': True})['jobs']
        approved['suites'][sha256_file(third)] = {'benchmark_id': 'legal-original-smoke', 'fixture_export': False}
        write_json(target, approved)
        self.assertEqual((lr.classify(job4, other)['level'], lr.classify(job4, other)['fixture_export']), ('approved', False))
        self.assertEqual(lr.classify(job4)['level'], 'declared')
        self.assertEqual(lr.reporting_policy([job4])['publish'], False)

    def test_private_or_unverified_job_is_stopped_before_reservation_and_rpc(self):
        # At plan time: a job the plugin's validation accepts but the classification refuses (here the approved list cannot be read).
        with patch.object(contracts, 'approved_suites', side_effect=ValueError('Approved suites file not found')), \
                self.assertRaisesRegex(ValueError, 'Job is not admitted by the data policy of .*: not_approved'):
            self.plan('unreadable-approvals')
        for name in ('private', 'unverified'):
            with self.subTest(name):
                plan = self.plan('base-' + name, parameters={'suite': str(self.copy('base-' + name)), 'synthetic': True})
                with patch('llm_eval.orchestration.resources.lock_root', return_value=self.path / 'locks'):
                    directory = initialize(plan, self.path / ('out-' + name))
                stored = read_json(directory / 'plan.json')
                job = stored['jobs'][0]
                lock = self.copy(name, 'private-matter') if name == 'private' else self.path / 'absent' / 'suite.lock.json'
                job['parameters']['suite'] = str(lock)
                job['input_files'] = [{'path': str(lock), 'sha256': sha256_file(lock) if lock.is_file() else '0' * 64}]
                job['target'] = dict(SSH)
                stored['plan_sha256'] = config_hash({k: v for k, v in stored.items() if k != 'plan_sha256'})
                write_json(directory / 'plan.json', stored)
                calls = []
                self.assertEqual(self.resume(directory, rpc=lambda target, payload, root, timeout=60: calls.append(payload['action'])), 1)
                self.assertEqual(calls, [])
                record = read_json(directory / 'campaign.json')['jobs'][job['job_id']]
                self.assertEqual((record['status'], record['reason'], record['attempts']), ('failed', 'data_policy', []))
                self.assertFalse((directory / 'experiments' / job['experiment_run_id'] / 'jobs').exists())

    def test_declared_suite_runs_locally_but_is_not_transferred(self):
        lock = self.copy()
        directory = self.smoke(lock, 'declared')
        report = self.report(directory)
        rows = [r['data'] for r in raw_records(report) if r['record_type'] == 'request']
        self.assertEqual(len(rows), 16)
        self.assertFalse(any('expected_choice' in r or 'choice' in r or 'quality_pass' in r for r in rows))
        with self.assertRaisesRegex(ValueError, 'Remote execution is not available'):
            self.plan('declared-remote', parameters={'suite': str(lock), 'synthetic': True}, hardware='remote')
        plan = self.plan('declared-stored', parameters={'suite': str(lock), 'synthetic': True})
        with patch('llm_eval.orchestration.resources.lock_root', return_value=self.path / 'locks'):
            stored_dir = initialize(plan, self.path / 'out-stored')
        stored = read_json(stored_dir / 'plan.json')
        stored['jobs'][0]['target'] = dict(SSH)
        stored['plan_sha256'] = config_hash({k: v for k, v in stored.items() if k != 'plan_sha256'})
        write_json(stored_dir / 'plan.json', stored)
        calls = []
        self.assertEqual(self.resume(stored_dir, rpc=lambda target, payload, root, timeout=60: calls.append(payload['action'])), 1)
        self.assertEqual(calls, [])
        record = read_json(stored_dir / 'campaign.json')['jobs'][stored['jobs'][0]['job_id']]
        self.assertEqual((record['status'], record['reason']), ('failed', 'data_policy'))

    def test_stored_plan_drift_is_detected(self):
        plan = self.plan('drift')
        with patch('llm_eval.orchestration.resources.lock_root', return_value=self.path / 'locks'):
            directory = initialize(plan, self.path / 'out-drift')
        stored = read_json(directory / 'plan.json')
        stored['reporting'] = {'on_experiment_end': True, 'include_outputs': True}
        write_json(directory / 'plan.json', stored)
        with self.assertRaisesRegex(ValueError, 'Campaign plan changed'):
            self.resume(directory)
        self.assertEqual(read_json(directory / 'campaign.json')['status'], 'ready')      # refused before anything ran
        # A hand-built plan without the digest runs, and enabling a target changes campaign.json, not the plan.
        job = {'job_id': '0', 'experiment_run_id': 'run', 'experiment_id': 'llm-routing', 'mode': 'decision', 'parameters': {'synthetic': True},
               'target': {'transport': 'local', 'physical_host_id': 'a', 'available': False}, 'target_id': 'native', 'resources': ['a'],
               'status': 'blocked', 'reason': None, 'depends_on': []}
        hand = {'campaign_id': 'test', 'root': str(ROOT), 'code_revision': revision(ROOT), 'inputs': {}, 'jobs': [job],
                'targets': {'native': job['target']}, 'experiments': [{'experiment_run_id': 'run', 'experiment_id': 'llm-routing', 'job_ids': ['0']}],
                'execution': {'max_parallel_jobs': 1, 'on_failure': 'continue-independent'}, 'reporting': {'on_experiment_end': False}}
        for with_digest in (False, True):
            with self.subTest(with_digest=with_digest):
                value = copy.deepcopy(hand)
                if with_digest:
                    value['plan_sha256'] = config_hash(value)
                with patch('llm_eval.orchestration.resources.lock_root', return_value=self.path / 'locks'):
                    hand_dir = initialize(value, self.path / ('hand-' + str(with_digest)))
                ok = lambda target, payload, root, timeout=60: {'status': 'succeeded'} if payload['action'] == 'run' else {'ok': True}  # noqa: E731
                self.assertEqual(self.resume(hand_dir, rpc=ok), 1)
                self.assertEqual(self.resume(hand_dir, rpc=ok, enable_targets=['native']), 0)
                self.assertEqual(read_json(hand_dir / 'plan.json'), value)

    def test_campaigns_written_before_the_drift_check_resume_and_report(self):
        """Campaign directories of model-offloading and llm-routing written without the drift check resume and report exactly
        as a run of the same campaign from start to finish without it."""
        for name in ('a', 'b'):
            write_json(self.path / (name + '.json'), {'id': name, 'parameters': {'config': str(ROOT / 'configs/runs/ollama.example.json')}})
        write_json(self.path / 'fixed-inventory.json', {'targets': {'local': {'transport': 'local', 'physical_host_id': 'fixture-host'}},
                                                        'hardware_configs': {'native': {'target': 'local', 'hardware_profile': 'msi-raider-18-hx-ai',
                                                                                        'os_id': 'ubuntu-26.04-native'}}})
        campaigns = {
            'model-offloading': {'schema_version': 2, 'id': 'offload', 'inventory': 'fixed-inventory.json', 'phases': [
                {'id': 'offload', 'experiments': [{'id': 'model-offloading', 'version': 1, 'cases': ['a.json', 'b.json'], 'hardware_configs': ['native']}]}]},
            'llm-routing': {'schema_version': 2, 'id': 'routing', 'inventory': 'fixed-inventory.json', 'phases': [
                {'id': 'routing', 'experiments': [{'id': 'llm-routing', 'version': 1, 'mode': 'decision', 'cases': ['category-smoke'],
                                                   'hardware_configs': ['native']}]},
                {'id': 'again', 'depends_on': ['routing'], 'experiments': [{'id': 'llm-routing', 'version': 1, 'mode': 'decision',
                                                                            'cases': ['category-smoke'], 'hardware_configs': ['native']}]}]}}

        def rpc(stop):
            def call(target, payload, root, timeout=60):
                if payload['action'] != 'run':
                    return {'ok': True}
                out = Path(payload['output'])
                rows = [{'task_id': 't', 'category': 'math', 'benchmark': 'fixture', 'status': 'ok', 'warmup': False, 'elapsed_s': 1.5,
                         'quality_pass': True}]
                (out / 'requests.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in rows), encoding='utf-8', newline='\n')
                write_json(out / 'metadata.json', {'experiment_id': payload['job']['experiment_id'], 'config': {'model': 'fixture'}})
                if stop:      # stop the campaign after its first job
                    atomic_json(out.parents[4] / 'cancel.json', {'cancel': True})
                return {'status': 'succeeded'}
            return call

        def ids(count):
            return iter([uuid.UUID(int=i) for i in range(count)])

        def run(directory, stop, sequence, **options):
            with patch('llm_eval.orchestration.resources.lock_root', return_value=self.path / 'locks'), \
                    patch('llm_eval.orchestration.transport.rpc', side_effect=rpc(stop)), \
                    patch('llm_eval.orchestration.scheduler.utc_now', return_value='2026-11-12T00:00:00+00:00'), \
                    patch('llm_eval.orchestration.scheduler.uuid.uuid4', side_effect=list(sequence)):
                return run_campaign(directory, **options)

        def outcome(directory):
            text = (directory / 'campaign.json').read_text(encoding='utf-8')
            for spelling in sorted({str(directory.resolve()), str(directory)}, key=len, reverse=True):      # an 8.3 temp name or the long one
                text = text.replace(json.dumps(spelling)[1:-1], '<campaign>')
            state = json.loads(text)
            # result_signature digests the job states, whose worker_output is the absolute path; the states are compared above.
            reports = {k: {x: v for x, v in r.items() if x != 'result_signature'} for k, r in state['reports'].items()}
            fingerprints = {k: validate_bundle(directory / r['report'])[1]['report_fingerprint'] for k, r in state['reports'].items()}
            files = {k: v for k, v in tree(directory / 'experiments').items() if '/report/' not in k}
            return state['jobs'], reports, fingerprints, files

        for experiment, campaign in campaigns.items():
            with self.subTest(experiment):
                write_json(self.path / f'{experiment}.json', campaign)
                plan = compile_campaign(self.path / f'{experiment}.json', ROOT)
                self.assertIn('plan_sha256', plan)
                with patch('llm_eval.orchestration.scheduler.utc_now', return_value='2026-11-12T00:00:00+00:00'):
                    directory = initialize(plan, self.path / ('first-' + experiment))
                reference = self.path / ('reference-' + experiment) / directory.name
                shutil.copytree(directory, reference)
                a, b, c = (uuid.UUID(int=i) for i in (101, 102, 103))
                with patch('llm_eval.orchestration.scheduler._plan_unchanged', lambda plan: None):      # the code before the hook
                    self.assertEqual(run(directory, True, [a, b]), 130)
                    self.assertEqual(run(reference, False, [a, b, c]), 0)
                self.assertEqual(run(directory, False, [a, c], retry_failed=True), 0)      # with the drift check in place
                self.assertEqual(outcome(directory), outcome(reference))
                self.assertTrue(all(r['status'] == 'generated' for r in read_json(directory / 'campaign.json')['reports'].values()))

    def test_worker_startup_refuses_a_private_job(self):
        (job,) = self.plan('worker', parameters={'suite': str(self.copy()), 'synthetic': True})['jobs']
        private = self.copy('private', 'private-matter')
        job['parameters']['suite'] = str(private)
        job['input_files'] = [{'path': str(private), 'sha256': sha256_file(private)}]
        payload = {'action': 'run', 'job': job, 'root': str(ROOT), 'output': str(self.path / 'attempt'), 'owner': 'test',
                   'code_revision': revision(ROOT)}
        real = subprocess.Popen

        def popen(args, *rest, **options):      # git still runs; no worker child may start
            if args[0] != 'git':
                raise AssertionError('no child')
            return real(args, *rest, **options)
        with patch('llm_eval.orchestration.worker.reserve', side_effect=AssertionError('no reservation')), \
                patch('subprocess.Popen', side_effect=popen):
            with self.assertRaisesRegex(ValueError, 'Data policy refused the job'):
                worker.handle(payload)
            changed = copy.deepcopy(payload)
            changed['job']['input_files'][0]['sha256'] = '0' * 64
            with self.assertRaisesRegex(ValueError, 'Worker input hash mismatch'):
                worker.handle(changed)
            other = copy.deepcopy(payload)
            other['code_revision'] = '0' * 40
            with self.assertRaisesRegex(ValueError, 'Worker code revision mismatch'):
                worker.handle(other)
        self.assertFalse((self.path / 'attempt').exists())

    def test_remote_collect_is_refused_on_both_sides(self):
        lock = self.copy()
        plan = self.plan('collect', parameters={'suite': str(lock), 'synthetic': True})
        (job,) = plan['jobs']
        remote = {**copy.deepcopy(job), 'target': dict(SSH), 'resources': ['remote-test-host']}
        attempt = {'attempt_id': 'a' * 32, 'output': 'experiments/x/jobs/y/' + 'a' * 32, 'worker_output': '/srv/work/x', 'stage': 'submitted'}
        collected = []

        def rpc(target, payload, root, timeout=60):
            if payload['action'] == 'run':
                return {'status': 'succeeded'}
            if payload['action'] == 'status':
                return {'result': {'status': 'succeeded'}, 'active': False}
            return {'ok': True}
        with patch('llm_eval.orchestration.resources.lock_root', return_value=self.path / 'locks'), \
                patch('llm_eval.orchestration.transport.rpc', side_effect=rpc), \
                patch('llm_eval.orchestration.transport.collect', side_effect=lambda *a, **k: collected.append(a)):
            executed = scheduler._execute(remote, dict(attempt), {**plan, 'targets': {}}, self.path)
            reconciled = scheduler._reconcile(remote, dict(attempt), {**plan, 'targets': {}}, self.path)
            routing = {'job_id': 'r', 'experiment_id': 'llm-routing', 'mode': 'decision', 'parameters': {'synthetic': True},
                       'target': dict(SSH), 'resources': ['remote-test-host']}
            routed = scheduler._execute(routing, dict(attempt), {**plan, 'targets': {}}, self.path)
        self.assertEqual((executed['status'], executed['collect']), ('succeeded', 'refused'))
        self.assertEqual((reconciled['status'], reconciled['collect']), ('succeeded', 'refused'))
        self.assertNotIn('collect', routed)
        self.assertEqual(len(collected), 1)      # the routing job only
        # The worker refuses to list or return the bytes of a non-transferable attempt, from any directory around it.
        parent = self.path / 'work' / 'jobs'
        directory = parent / ('b' * 32)
        (directory / 'local').mkdir(parents=True)
        atomic_json(directory / 'job.json', job)
        (directory / 'local/candidate-outputs.jsonl').write_text(CANARY + '\n', encoding='utf-8')
        (directory / 'requests.jsonl').write_text('{}\n', encoding='utf-8')
        calls = [{'action': 'collect', 'output': str(directory)}, {'action': 'collect', 'output': str(directory / 'local')},
                 {'action': 'file-chunk', 'output': str(directory), 'path': 'local/candidate-outputs.jsonl', 'offset': 0},
                 {'action': 'collect', 'output': str(parent)},
                 {'action': 'file-chunk', 'output': str(parent), 'path': directory.name + '/local/candidate-outputs.jsonl', 'offset': 0}]
        for call in calls:
            with self.subTest(call=call), self.assertRaisesRegex(ValueError, 'Collection refused by data policy') as raised:
                worker.handle(call)
            self.assertNotIn(CANARY, str(raised.exception))
            self.assertNotIn('candidate-outputs', str(raised.exception))
        routing_dir = self.path / 'routing-work' / 'jobs' / ('c' * 32)
        (routing_dir / 'local').mkdir(parents=True)
        atomic_json(routing_dir / 'job.json', {'job_id': 'r', 'experiment_id': 'llm-routing', 'mode': 'decision', 'parameters': {'synthetic': True}})
        (routing_dir / 'local/x.jsonl').write_text('{}\n', encoding='utf-8')
        plain = self.path / 'plain'
        plain.mkdir()
        (plain / 'x.bin').write_bytes(b'x')
        for target, name in ((routing_dir, 'local/x.jsonl'), (routing_dir.parent, routing_dir.name + '/local/x.jsonl'), (plain, 'x.bin')):
            with self.subTest(target=target.name):
                self.assertTrue(worker.handle({'action': 'collect', 'output': str(target)})['files'])
                self.assertTrue(worker.handle({'action': 'file-chunk', 'output': str(target), 'path': name, 'offset': 0})['data'])

    def test_finalize_records_a_safe_reason_and_keeps_local_artifacts(self):
        directory = self.smoke(self.copy(), 'finalize', reporting={'on_experiment_end': False})
        attempt = self.attempt(directory)
        before = tree(attempt)
        stored = read_json(directory / 'plan.json')
        private = self.copy('private', 'private-matter')
        stored['jobs'][0]['parameters']['suite'] = str(private)
        stored['jobs'][0]['input_files'] = [{'path': str(private), 'sha256': sha256_file(private)}]
        write_plan(directory, stored)
        receipt = self.refinalize(directory)
        self.assertEqual({k: receipt[k] for k in ('status', 'reason')}, {'status': 'disabled', 'reason': 'private_matter'})
        self.assertEqual(tree(attempt), before)
        self.assertFalse((self.experiment_dir(directory) / 'report').exists())
        # A projection failure is a failed receipt with the error type only; the attempt stays as it was.
        other = self.smoke(LOCK, 'broken')
        attempt = self.attempt(other)
        rows = lines(attempt / 'requests.jsonl')
        rows[0]['category'] = 'A sentence about the matter.'
        (attempt / 'requests.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in rows), encoding='utf-8', newline='\n')
        before = tree(attempt)
        receipt = self.refinalize(other)
        self.assertEqual({k: receipt[k] for k in ('status', 'error_type')}, {'status': 'failed', 'error_type': 'ProjectionRejected'})
        self.assertEqual(tree(attempt), before)

    def test_include_outputs_cannot_override_policy(self):
        directory = self.smoke(LOCK, 'outputs', reporting={'on_experiment_end': True, 'include_outputs': True})
        report = self.report(directory)
        dest, _ = bundle_dir(report)
        exported = {name: (dest / name).read_bytes() for name in BUNDLE_FILES}
        self.assertNotIn(b'candidate-outputs', b''.join(exported.values()))
        self.assertNotIn(b'"claims"', gzip.decompress(exported['raw/measurements.jsonl.gz']))
        stored = read_json(directory / 'plan.json')
        stored['reporting'] = {'on_experiment_end': True}
        write_plan(directory, stored)
        self.refinalize(directory)
        self.assertEqual({name: (dest / name).read_bytes() for name in BUNDLE_FILES}, exported)      # the setting changes nothing
        stored['reporting'] = {'on_experiment_end': True, 'include_outputs': True, 'publish': {'mode': 'pull-request'}}
        stored['jobs'][0]['parameters']['suite'] = str(self.copy('private', 'private-matter'))
        write_plan(directory, stored)
        self.assertEqual(self.refinalize(directory)['status'], 'disabled')
        self.assertEqual(lr.reporting_policy(stored['jobs'])['include_outputs'], False)

    def test_other_experiments_are_admitted_collected_and_published_as_before(self):
        write_json(self.path / 'routing-inventory.json', {'targets': {'remote': SSH}, 'hardware_configs': {
            'remote': {'target': 'remote', 'hardware_profile': 'msi-raider-18-hx-ai', 'os_id': 'ubuntu-26.04-native'}}})
        write_json(self.path / 'routing.json', {'schema_version': 2, 'id': 'routing', 'inventory': 'routing-inventory.json', 'phases': [
            {'id': 'routing', 'experiments': [{'id': 'llm-routing', 'version': 1, 'mode': 'decision', 'cases': ['category-smoke'],
                                               'hardware_configs': ['remote']}]}]})
        plan = compile_campaign(self.path / 'routing.json', ROOT)
        self.assertEqual(plan['jobs'][0]['status'], 'planned')
        collected = []

        def rpc(target, payload, root, timeout=60):
            return {'status': 'succeeded'} if payload['action'] == 'run' else {'ok': True}
        with patch('llm_eval.orchestration.resources.lock_root', return_value=self.path / 'locks'), \
                patch('llm_eval.orchestration.transport.rpc', side_effect=rpc), \
                patch('llm_eval.orchestration.transport.collect', side_effect=lambda *a, **k: collected.append(a[1])):
            directory = initialize(plan, self.path / 'routing-out')
            self.assertEqual(run_campaign(directory), 0)
        (record,) = read_json(directory / 'campaign.json')['jobs'].values()
        self.assertEqual((record['status'], len(collected)), ('succeeded', 1))
        self.assertNotIn('collect', record['attempts'][0])
        self.assertTrue(publish_report(self.report(directory), ROOT, dry_run=True)['dry_run'])


# 2. The projection ----------------------------------------------------------------------------------------------------

class ProjectionTests(Base):
    def test_projection_runs_before_any_generic_scan_chart_or_metadata(self):
        directory = self.smoke(LOCK, 'order', reporting={'on_experiment_end': False})
        experiment = self.experiment_dir(directory)
        boom = AssertionError('the generic path was used')
        with patch.object(Path, 'rglob', side_effect=boom), patch('llm_eval.reporting.experiment.chart', side_effect=boom), \
                patch('llm_eval.reporting.experiment.sanitize', side_effect=boom), patch.dict(sys.modules, {'matplotlib': None}):
            report = build_report(experiment)
        dest, spec = bundle_dir(report)
        self.assertEqual(sorted(p.relative_to(dest).as_posix() for p in dest.rglob('*') if p.is_file()), BUNDLE_FILES)
        self.assertEqual(sorted(p.name for p in (report / 'bundle').iterdir()), ['docs'])      # no chart directory
        attempt = self.attempt(directory)
        for target in ('attempt', 'requests.jsonl'):
            with self.subTest(link=target):
                moved = self.path / ('real-' + target)
                victim = attempt if target == 'attempt' else attempt / 'requests.jsonl'
                shutil.move(str(victim), str(moved))
                try:
                    os.symlink(moved, victim, target_is_directory=target == 'attempt')
                except (OSError, NotImplementedError):
                    shutil.move(str(moved), str(victim))
                    self.skipTest('symbolic links are not available on this platform')
                try:
                    with self.assertRaisesRegex(lr.ProjectionRejected, 'symlink'):
                        build_report(experiment)
                finally:
                    os.unlink(victim)
                    shutil.move(str(moved), str(victim))

    def test_unexpected_keys_nested_fields_and_free_text_are_rejected(self):
        directory = self.smoke(LOCK, 'strict')
        attempt = self.attempt(directory)
        rows0, meta0 = (attempt / 'requests.jsonl').read_text(encoding='utf-8'), (attempt / 'metadata.json').read_text(encoding='utf-8')
        pristine = {name: (attempt / name).read_bytes() for name in ('requests.jsonl', 'metadata.json')}
        role = {'profile_sha256': '1' * 64, 'role': 'generator', 'serving': 'external', 'capability': 'chat', 'platform': 'llama.cpp',
                'backend_version': '1', 'model': 'qwen3:27b', 'model_revision': 'r1', 'artifact_sha256': None, 'quantization': None,
                'protocol': 'openai', 'accelerator': 'gpu', 'context_tokens': 8192, 'max_output_tokens': 1024, 'dimensions': None,
                'qualified': False, 'qualified_by_attestation': False, 'serving_profile_sha256': None}
        cases = [('extra row key', lambda r, m: r[0].update({CANARY: 1})),
                 ('nested object in a row', lambda r, m: r[0].update(elapsed_s={'value': 1})),
                 ('sentence as category', lambda r, m: r[0].update(category='The accused admitted it.')),
                 ('path as error type', lambda r, m: r[0].update(error_type='C:/Users/alice/trace.log')),
                 ('rooted model path', lambda r, m: m.update(roles={'generator': {**role, 'model': 'C:/Users/alice/models/qwen.gguf'}})),
                 ('absolute model path', lambda r, m: m.update(roles={'generator': {**role, 'model': '/models/x'}})),
                 ('reason code outside the closed set', lambda r, m: r[0].update(reason_codes=['made_up_reason'])),
                 ('nested metadata key', lambda r, m: m.update(retrieval={'backend': 'memory', 'top_k': 3, 'token_budget': 9, 'tokenizer': 't',
                                                                          'chunking': 'span', 'index_fingerprint': None, 'embedder_sha256': None,
                                                                          'reranker_sha256': None, 'note': CANARY}))]
        for name, change in cases:
            with self.subTest(name):
                rows, meta = [json.loads(line) for line in rows0.splitlines()], json.loads(meta0)
                change(rows, meta)
                (attempt / 'requests.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in rows), encoding='utf-8', newline='\n')
                write_json(attempt / 'metadata.json', meta)
                shutil.rmtree(self.experiment_dir(directory) / 'report', ignore_errors=True)
                receipt = self.refinalize(directory)
                self.assertEqual({k: receipt.get(k) for k in ('status', 'error_type')}, {'status': 'failed', 'error_type': 'ProjectionRejected'})
                self.assertFalse((self.experiment_dir(directory) / 'report').exists())
                with self.assertRaises(lr.ProjectionRejected) as raised:
                    build_report(self.experiment_dir(directory))
                self.assertNotIn(CANARY, str(raised.exception))
                code, output = cli('report', '--input', str(self.experiment_dir(directory)))
                self.assertEqual(code, 2)
                self.assertIn('ProjectionRejected', output)
                for leaked in (CANARY, 'alice', 'accused', '/models/x', 'made_up_reason'):
                    self.assertNotIn(leaked, output)
        for name, data in pristine.items():      # the bytes the receipt names
            (attempt / name).write_bytes(data)
        self.assertEqual(self.refinalize(directory)['status'], 'generated')

    def test_private_detail_stays_local(self):
        directory = self.smoke(self.copy(), 'private-detail')
        attempt = self.attempt(directory)
        write_json(attempt / 'local/metadata.json', {'schema_version': 1, 'note': CANARY})
        (attempt / 'local/x').mkdir()
        (attempt / 'local/x/requests.jsonl').write_text(json.dumps({'task_id': CANARY}) + '\n', encoding='utf-8')
        report = self.report(directory) if self.refinalize(directory)['status'] == 'generated' else None
        self.assertIsNotNone(report)
        write_json(attempt / 'host.json', {'node': CANARY + '-host', 'environment_kind': 'ubuntu-26.04-native'})
        (attempt / 'worker.log').write_text('worker ' + CANARY + '\n', encoding='utf-8')
        self.assertEqual(self.refinalize(directory)['status'], 'generated')
        exported = all_bytes(report / 'bundle') + (report / 'publication.json').read_bytes() + \
            gzip.decompress((bundle_dir(report)[0] / 'raw/measurements.jsonl.gz').read_bytes())
        # Every string value of the private files, except the closed vocabulary that is public by design (criterion names,
        # error codes, review dimensions, statuses), stays local: matter, family and span ids, propositions, questions, answers.
        vocabulary = set(fixture.CRITERIA) | set(grading.REASONS) | set(grading.PENDING_DIMENSIONS) | set(contracts.RECOMMENDATIONS) | \
            {'smoke', 'scored', 'ok', 'supported', 'qualified', 'insufficient', 'offence', 'defence', 'established', 'not_established'}

        def strings(value):
            if isinstance(value, str):
                yield value
            elif isinstance(value, dict):
                for v in value.values():
                    yield from strings(v)
            elif isinstance(value, list):
                for v in value:
                    yield from strings(v)
        checked = 0
        for name in ('local/candidate-outputs.jsonl', 'local/score-detail.jsonl'):
            for record in lines(attempt / name):
                for text in strings(record):
                    if text not in vocabulary and len(text) >= 8:
                        checked += 1
                        self.assertNotIn(json.dumps(text).encode(), exported, name)
        self.assertGreater(checked, 100)
        job = read_json(attempt / 'job.json')
        for text in (job['parameters']['suite'], str(ROOT), job['target']['physical_host_id'], job['target']['lock_root']):
            self.assertNotIn(text.encode(), exported)
        for leaked in (CANARY, 'candidate-outputs', 'score-detail', '"claims"', 'The purser admits he knew the count was lower.'):
            self.assertNotIn(leaked.encode(), exported)
        salt = (self.experiment_dir(directory) / 'projection-salt').read_text(encoding='ascii').strip()
        self.assertRegex(salt, '^[0-9a-f]{32}$')
        self.assertNotIn(salt.encode(), exported)

    def test_score_detail_is_validated_before_any_number_leaves(self):
        directory = self.smoke(LOCK, 'detail')
        attempt = self.attempt(directory)
        original = (attempt / 'local/score-detail.jsonl').read_text(encoding='utf-8')
        report = self.report(directory)
        legal_summary = read_json(bundle_dir(report)[0] / 'legal-summary.json')
        (entry,) = legal_summary['cohorts']
        self.assertEqual(set(entry['metrics']), set(lr.ROW_METRICS) | set(grading.METRICS))
        self.assertEqual(entry['metrics']['all_pass']['value'], 1.0)
        self.assertEqual(entry['metrics']['all_pass']['n'], 16)
        cases = [('extra criterion key', lambda d: d['criteria'].update({CANARY: True})),
                 ('unknown error code', lambda d: d.update(errors=[{'code': CANARY.lower(), 'critical': True}])),
                 ('sentence as gold recommendation', lambda d: d.update(gold_recommendation='Charge the purser.')),
                 ('extra record key', lambda d: d.update(comment='a grader comment'))]
        for name, change in cases:
            with self.subTest(name):
                details = [json.loads(line) for line in original.splitlines()]
                change(details[0])
                (attempt / 'local/score-detail.jsonl').write_text(''.join(json.dumps(d) + '\n' for d in details), encoding='utf-8')
                with self.assertRaisesRegex(lr.ProjectionRejected, 'score_detail') as raised:
                    build_report(self.experiment_dir(directory))
                self.assertNotIn(CANARY, str(raised.exception))
        (attempt / 'local/score-detail.jsonl').unlink()
        with self.assertRaisesRegex(lr.ProjectionRejected, 'score_detail'):
            build_report(self.experiment_dir(directory))

    def test_exact_fixture_export_needs_the_approved_policy(self):
        shipped = raw_records(self.report(self.smoke(LOCK, 'exact')))
        rows = [r['data'] for r in shipped if r['record_type'] == 'request']
        self.assertEqual(sorted(r['task_id'] for r in rows)[:2], ['f1-ledger-a', 'f1-ledger-b'])
        self.assertTrue(all('expected_choice' in r and r['category'] != 'all' for r in rows))
        reduced = [r['data'] for r in raw_records(self.report(self.smoke(self.copy(), 'reduced'))) if r['record_type'] == 'request']
        self.assertTrue(all(len(r['task_id']) == 16 and 'expected_choice' not in r and r['category'] == 'all' for r in reduced))

    def test_reduced_projection_hides_the_answer_key(self):
        lock = self.copy()
        directory = self.smoke(lock, 'answer-key')
        report = self.report(directory)
        records = raw_records(report)
        rows = [r['data'] for r in records if r['record_type'] == 'request']
        forbidden = {'expected_choice', 'choice', 'author_choice', 'decision_correct', 'abstained', 'forced_defer', 'insufficiency_flags',
                     'quality_check_applicable', 'quality_pass', 'criteria_passed', 'criteria_total', 'critical_errors', 'pending_dimensions',
                     'reason_codes', 'prompt_sha256', 'output_sha256', 'evidence_sha256', 'prompt_tokens', 'completion_tokens', 'route_choice',
                     'route_selected', *retrieval.PUBLIC_METRICS}
        self.assertFalse(any(forbidden & set(r) for r in rows))
        suite = contracts.load_suite(lock)
        ids = [m['matter_id'] for m in suite['matters']['matters']] + [m['family_id'] for m in suite['matters']['matters']]
        guesses = {hashlib.sha256(x.encode()).hexdigest()[:16] for i in ids for x in (i, suite['lock_sha256'] + ':' + i, LOCK.read_text() + i)}
        guesses |= {digest(r)[:16] for r in lines(self.attempt(directory) / 'requests.jsonl')}
        pseudonyms = {r['task_id'] for r in rows} | {r['family_id'] for r in rows}
        self.assertEqual(len({r['task_id'] for r in rows}), 16)
        self.assertFalse(pseudonyms & guesses)
        self.assertFalse(pseudonyms & set(ids))
        self.assertEqual([r['task_id'] for r in rows], sorted(r['task_id'] for r in rows))      # pseudonym order, not matter order
        meta = next(r['data'] for r in records if r['record_type'] == 'metadata')
        self.assertTrue(all(meta.get(k) is None for k in lr.AUTHOR_KEYS))
        rebuilt = raw_records(build_report(self.experiment_dir(directory)))
        self.assertEqual({r['data']['task_id'] for r in rebuilt if r['record_type'] == 'request'}, {r['task_id'] for r in rows})
        second = raw_records(self.report(self.smoke(lock, 'answer-key-2')))
        self.assertFalse({r['data']['task_id'] for r in second if r['record_type'] == 'request'} & {r['task_id'] for r in rows})
        legal_summary = read_json(bundle_dir(report)[0] / 'legal-summary.json')
        self.assertEqual(legal_summary['cohorts'][0]['metrics']['all_pass']['n'], 16)
        self.assertIsNone(legal_summary['cohorts'][0]['cohort']['suite_revision'])

    def test_projection_bytes_do_not_depend_on_the_hash_seed(self):
        directory = self.smoke(self.copy(), 'seed', reporting={'on_experiment_end': False})
        experiment = self.experiment_dir(directory)
        script = ('import sys,json,hashlib\nfrom pathlib import Path\nfrom llm_eval.reporting.experiment import build_report\n'
                  'r=build_report(sys.argv[1])\nprint(json.dumps({p.relative_to(r).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() '
                  'for p in sorted(r.rglob("*")) if p.is_file()}))\n')
        found = []
        for seed in ('1', '4242'):
            env = {**os.environ, 'PYTHONHASHSEED': seed, 'PYTHONPATH': str(ROOT / 'src')}
            p = subprocess.run([sys.executable, '-c', script, str(experiment)], capture_output=True, text=True, env=env, timeout=600, check=True)
            found.append(json.loads(p.stdout))
        self.assertEqual(found[0], found[1])
        self.assertIn('publication.json', found[0])


# 3. Publication -------------------------------------------------------------------------------------------------------

class PublicationTests(Base):
    def test_publication_needs_projection_approval_receipt_and_authorization(self):
        directory = self.smoke(LOCK, 'gates')
        report = self.report(directory)

        def refused(code, target=None):
            with self.assertRaisesRegex(ValueError, f'Publication is not available for legal-benchmark: {code}$'):
                publish_report(target or report, ROOT, dry_run=True)
            with self.assertRaisesRegex(ValueError, f'^{code}$'):
                lr.verify_publication(target or report, ROOT)
        refused('not_authorized')
        self.authorize(directory)
        self.assertTrue(publish_report(report, ROOT, dry_run=True)['dry_run'])
        moved = self.path / 'elsewhere' / 'report'
        shutil.copytree(report, moved)
        refused('provenance_missing', moved)
        with patch('llm_eval.reporting.experiment.plugin_hook', return_value=None):      # the generic path: a legacy legal bundle
            legacy = build_report(self.experiment_dir(directory))
        refused('legacy_report', legacy)
        self.refinalize(directory)
        attempt = self.attempt(directory)
        metadata = read_json(attempt / 'metadata.json')
        write_json(attempt / 'metadata.json', {**metadata, 'suite_lock_sha256': '0' * 64})
        refused('receipt_mismatch')
        write_json(attempt / 'metadata.json', metadata)
        state = read_json(directory / 'campaign.json')
        record = next(iter(state['jobs'].values()))['attempts'][-1]
        record['status'] = 'failed'
        write_json(directory / 'campaign.json', state)
        refused('receipt_mismatch')
        record['status'] = 'succeeded'
        write_json(directory / 'campaign.json', state)
        dest, spec = bundle_dir(report)
        original = (dest / 'summary.csv').read_bytes()
        (dest / 'summary.csv').unlink()      # a missing file: only the inventory comparison sees it
        with self.assertRaisesRegex(ValueError, '^bundle_mismatch$'):
            lr.verify_publication(report, ROOT)
        (dest / 'summary.csv').write_bytes(original + b'x\n')      # the plugin gate alone, before any manifest is recomputed
        with self.assertRaisesRegex(ValueError, '^bundle_mismatch$'):
            lr.verify_publication(report, ROOT)
        self.remanifest(report)
        refused('bundle_mismatch')
        (dest / 'summary.csv').write_bytes(original)
        self.remanifest(report)
        self.assertTrue(publish_report(report, ROOT, dry_run=True)['dry_run'])
        for name, lock in (('not_approved', self.copy('declared')), ('unverified', self.copy('later'))):
            with self.subTest(name):
                other = self.smoke(lock, name)
                self.authorize_by_hand(other)
                if name == 'unverified':
                    with (lock.parent / 'rubric.json').open('a', encoding='utf-8') as handle:
                        handle.write(' ')
                refused(name, self.report(other))

    def authorize_by_hand(self, directory):
        """What a script that only writes the authorization file produces: a file that names this report's fingerprint."""
        report = self.report(directory)
        spec = read_json(report / 'publication.json')
        plan = read_json(directory / 'plan.json')
        exp = self.experiment_dir(directory).name
        locks = sorted({f['sha256'] for j in plan['jobs'] for f in j['input_files'] if f['path'] == j['parameters']['suite']})
        write_json(directory / lr.AUTHORIZATION, {'schema_version': 1, 'experiment_run_id': exp, 'report_fingerprint': spec['report_fingerprint'],
                                                  'suite_lock_sha256': locks, 'repository': spec['repository'], 'base_branch': spec['base_branch'],
                                                  'approved_by': 'script', 'approved_utc': '2026-11-12T00:00:00+00:00'})

    @staticmethod
    def remanifest(report):
        """Recompute the manifest hashes and the fingerprint of an edited bundle, as a forger would."""
        dest, spec = bundle_dir(report)
        manifest = read_json(dest / 'manifest.json')
        manifest.pop('report_fingerprint')
        manifest['files'] = {name: hashlib.sha256((report / 'bundle' / name).read_bytes()).hexdigest() for name in manifest['files']}
        manifest['report_fingerprint'] = digest(manifest)
        (dest / 'manifest.json').write_bytes(canonical_json(manifest))
        spec['report_fingerprint'] = manifest['report_fingerprint']
        (report / 'publication.json').write_bytes(canonical_json(spec))

    def test_approval_must_be_committed_on_the_base_branch(self):
        # The installed package approves the shipped smoke suite; the base branch of the publication repository does not.
        directory = self.smoke(LOCK, 'upstream')
        report = self.report(directory)
        upstream = read_json(ROOT / contracts.APPROVED_SUITES)
        upstream['suites'].pop(sha256_file(LOCK))
        repo, bare = self.repository(approved=(json.dumps(upstream, indent=2) + '\n').encode())
        self.authorize(directory)
        self.assertTrue(publish_report(report, repo, dry_run=True)['dry_run'])      # the local checks pass
        api = RecordingGitHub()
        with self.assertRaisesRegex(ValueError, 'not_approved_upstream'):
            self.publish(report, repo, api)
        self.assertEqual(api.created, 0)
        self.assertEqual(real_git(repo, 'worktree', 'list').count('\n'), 0)      # only the main worktree
        self.assertEqual(subprocess.run(['git', '-C', str(bare), 'for-each-ref', '--format=%(refname:short)', 'refs/heads'], capture_output=True, text=True).stdout.split(), ['main'])
        self.assertEqual(read_json(report / 'publication-error.json'), {'status': 'pending', 'error_type': 'ValueError'})
        self.assertFalse((report / 'publication-state.json').exists())

    def test_authorization_needs_confirmation_and_binds_the_destination(self):
        directory = self.smoke(LOCK, 'authorize')
        report = self.report(directory)
        exp = self.experiment_dir(directory).name
        with patch('sys.stdin', io.StringIO('')), self.assertRaisesRegex(ValueError, 'interactive terminal'):
            lr.authorize(directory, exp, 'test-reviewer')
        shown = []
        with self.assertRaisesRegex(ValueError, 'not confirmed'):
            lr.authorize(directory, exp, 'test-reviewer', confirm=lambda text: shown.append(text) or False)
        self.assertFalse((directory / lr.AUTHORIZATION).exists())
        for part in (exp, 'asanderson/llm-eval', 'main', 'fixture', 'legal-original-smoke', 'public-synthetic', 'legal-summary.json'):
            self.assertIn(part, shown[0])
        with self.assertRaises(ValueError):
            lr.authorize(directory, exp, 'Not An Identifier', confirm=lambda text: True)
        path = self.authorize(directory)
        self.assertEqual(set(read_json(path)), {'schema_version', 'experiment_run_id', 'report_fingerprint', 'suite_lock_sha256', 'repository',
                                                'base_branch', 'approved_by', 'approved_utc'})
        lr.verify_publication(report, ROOT)
        pristine = (report / 'publication.json').read_bytes()
        for key, value in (('repository', 'someone/else'), ('base_branch', 'release'), ('draft', True), ('publication_id', 'x'),
                           ('code_revision', '0' * 40)):
            with self.subTest(publication=key):
                (report / 'publication.json').write_bytes(canonical_json({**json.loads(pristine), key: value}))
                with self.assertRaisesRegex(ValueError, '^bundle_mismatch$'):
                    lr.verify_publication(report, ROOT)
        (report / 'publication.json').write_bytes(pristine)
        plan0 = read_json(directory / 'plan.json')
        for key, change in (('repository', lambda p: p['reporting'].update(publish={'repository': 'someone/else'})),
                            ('base_branch', lambda p: p['reporting'].update(publish={'base_branch': 'release'})),
                            ('code_revision', lambda p: p.update(code_revision='0' * 40))):
            with self.subTest(plan=key):
                plan = copy.deepcopy(plan0)
                change(plan)
                write_plan(directory, plan)
                if key == 'code_revision':      # the experiment record names the measured code too
                    record = read_json(self.experiment_dir(directory) / 'experiment.json')
                    write_json(self.experiment_dir(directory) / 'experiment.json', {**record, 'code_revision': '0' * 40})
                build_report(self.experiment_dir(directory))      # the rebuilt bundle agrees with the edited plan
                with self.assertRaisesRegex(ValueError, '^not_authorized$'):
                    lr.verify_publication(report, ROOT)
        write_json(directory / 'plan.json', plan0)

    def test_projected_bundle_passes_a_dry_run_publication(self):
        directory = self.smoke(LOCK, 'dry')
        report = self.report(directory)
        self.authorize(directory)
        result = publish_report(report, ROOT, dry_run=True)
        dest, spec = bundle_dir(report)
        manifest = read_json(dest / 'manifest.json')
        self.assertEqual(sorted(result['files']), sorted(spec['report_path'] + '/' + n for n in BUNDLE_FILES if n != 'manifest.json'))
        self.assertEqual(result['files'], list(manifest['files']))
        self.assertEqual(read_json(dest / 'resolved-config.json')['experiment']['experiment_id'], 'legal-benchmark')
        self.assertEqual((manifest['projection'], manifest['canonical_bytes'], manifest['execution_kinds'], manifest['data_class']),
                         (lr.PROJECTION, 1, ['fixture'], 'public-synthetic'))
        code, output = cli('publish-results', '--input', str(report), '--project-root', str(ROOT), '--dry-run')
        self.assertEqual(code, 0)
        self.assertIn('"dry_run": true', output)

    def test_a_public_label_in_the_manifest_cannot_authorize_export(self):
        for name, lock in (('declared', self.copy()), ('approved', LOCK)):
            with self.subTest(name):
                directory = self.smoke(lock, name)
                report = self.report(directory)
                dest, spec = bundle_dir(report)
                manifest = read_json(dest / 'manifest.json')
                manifest.pop('report_fingerprint')
                manifest.update(public=True, approved=True, publish=True, data_class='public-synthetic')
                manifest['report_fingerprint'] = digest(manifest)
                (dest / 'manifest.json').write_bytes(canonical_json(manifest))
                (report / 'publication.json').write_bytes(canonical_json({**spec, 'report_fingerprint': manifest['report_fingerprint']}))
                validate_bundle(report)
                with self.assertRaisesRegex(ValueError, 'not_approved' if name == 'declared' else 'bundle_mismatch|not_authorized'):
                    publish_report(report, ROOT, dry_run=True)

    def test_forged_tampered_and_legacy_reports_are_rejected(self):
        directory = self.smoke(LOCK, 'forged')
        report = self.report(directory)
        self.authorize(directory)
        with patch('llm_eval.reporting.experiment.plugin_hook', return_value=None):
            legacy = build_report(self.experiment_dir(directory))
        with self.assertRaisesRegex(ValueError, 'legacy_report'):
            publish_report(legacy, ROOT, dry_run=True)
        report = build_report(self.experiment_dir(directory))
        dest, _ = bundle_dir(report)
        summary = read_json(dest / 'summary.json')
        summary[0]['quality_pass_rate'] = 0.5
        (dest / 'summary.json').write_bytes(canonical_json(summary))
        PublicationTests.remanifest(report)
        validate_bundle(report)
        with self.assertRaisesRegex(ValueError, 'bundle_mismatch'):
            publish_report(report, ROOT, dry_run=True)
        report = build_report(self.experiment_dir(directory))
        self.assertTrue(publish_report(report, ROOT, dry_run=True)['dry_run'])
        copied = self.path / 'copied' / 'experiments' / report.parent.name / 'report'
        shutil.copytree(report, copied)
        with self.assertRaisesRegex(ValueError, 'provenance_missing'):
            publish_report(copied, ROOT, dry_run=True)
        renamed = directory.parent / ('campaign-renamed-' + CANARY.lower())
        os.replace(directory, renamed)
        with self.assertRaisesRegex(ValueError, 'provenance_missing'):
            publish_report(renamed / report.relative_to(directory), ROOT, dry_run=True)

    def test_automatic_publication_stays_refused_at_plan_and_finalize(self):
        with self.assertRaisesRegex(ValueError, 'Publication is not available for legal-benchmark: automatic_publication_unavailable'):
            self.plan('automatic', reporting={'publish': {'mode': 'pull-request', 'repository': 'asanderson/llm-eval'}})
        directory = self.smoke(LOCK, 'automatic')
        self.authorize(directory)
        stored = read_json(directory / 'plan.json')
        stored['reporting'] = {'on_experiment_end': True, 'publish': {'mode': 'pull-request'}}
        write_plan(directory, stored)
        with patch('llm_eval.reporting.publish.publish_report', side_effect=AssertionError('must not publish')):
            receipt = self.refinalize(directory)
        self.assertEqual(receipt['status'], 'generated')
        self.assertNotIn('pull_request', receipt)
        for name in sorted((ROOT / 'configs/examples/legal').glob('*campaign*.json')):
            self.assertEqual(read_json(name).get('reporting', {}).get('publish', {}).get('mode', 'none'), 'none', name.name)

    def test_dry_run_tampering_and_crash_retry_are_idempotent(self):
        directory = self.smoke(LOCK, 'retry')
        report = self.report(directory)
        self.authorize(directory)
        repo, bare = self.repository()
        self.assertTrue(self.publish(report, repo, None, dry_run=True)['dry_run'])
        api = RecordingGitHub()
        api.fail = True
        with self.assertRaises(ConnectionError):
            self.publish(report, repo, api)
        first = self.publish(report, repo, api)
        second = self.publish(report, repo, api)
        self.assertEqual(api.created, 1)
        self.assertEqual(first['commit'], second['commit'])
        self.assertEqual(real_git(repo, 'status', '--porcelain'), '')
        body = api.bodies[-1]['body']
        for part in ('Execution classes: fixture', 'Data class: public-synthetic', 'Cohorts: 1', 'Report fingerprint: '):
            self.assertIn(part, body)
        self.assertNotIn('chart', body.lower())
        self.assertNotIn('PNG', body)
        dest, spec = bundle_dir(report)
        original = (dest / 'README.md').read_bytes()
        (dest / 'README.md').write_bytes(original + b'edited\n')
        with self.assertRaisesRegex(ValueError, 'integrity'):
            self.publish(report, repo, api)
        (dest / 'README.md').write_bytes(original)
        # A stale file left under the report path by an earlier push is never committed unseen.
        branch = first['branch']
        clone = self.path / 'clone'
        subprocess.run(['git', 'clone', '-q', '-b', branch, str(bare), str(clone)], check=True, capture_output=True)
        (clone / spec['report_path'] / 'stale.json').write_text('{}\n', encoding='utf-8')
        subprocess.run(['git', '-C', str(clone), 'add', '-A'], check=True, capture_output=True)
        subprocess.run(['git', '-C', str(clone), '-c', 'user.name=x', '-c', 'user.email=x@example.com', 'commit', '-q', '-m', 'stale'],
                       check=True, capture_output=True)
        subprocess.run(['git', '-C', str(clone), 'push', '-q', 'origin', branch], check=True, capture_output=True)
        with self.assertRaisesRegex(ValueError, 'Staged files differ from the manifest'):
            self.publish(report, repo, api)
        self.assertEqual(api.created, 1)


# 4. Canonical bytes ---------------------------------------------------------------------------------------------------

class BytesTests(Base):
    def test_bundle_bytes_are_canonical_and_deterministic(self):
        directory = self.smoke(LOCK, 'bytes')
        report = self.report(directory)
        dest, spec = bundle_dir(report)
        first = {name: (dest / name).read_bytes() for name in BUNDLE_FILES}
        build_report(self.experiment_dir(directory))
        self.assertEqual({name: (dest / name).read_bytes() for name in BUNDLE_FILES}, first)
        for name, data in first.items():
            self.assertNotIn(b'\r', data if not name.endswith('.gz') else gzip.decompress(data), name)
        for name in ('summary.json', 'legal-summary.json', 'resolved-config.json', 'manifest.json'):
            self.assertEqual(first[name], canonical_json(json.loads(first[name])), name)
        self.assertEqual((report / 'publication.json').read_bytes(), canonical_json(read_json(report / 'publication.json')))
        summary = json.loads(first['summary.json'])
        import csv
        parsed = list(csv.DictReader(io.StringIO(first['summary.csv'].decode('utf-8'), newline='')))
        header = first['summary.csv'].splitlines()[0].decode().split(',')      # the generic summary's column order
        self.assertEqual((sorted(header), len(parsed)), (sorted(summary[0]), len(summary)))
        self.assertEqual(first['summary.csv'], canonical_csv(parsed, header))      # the bytes are the canonical writer's
        raw = gzip.decompress(first['raw/measurements.jsonl.gz'])
        self.assertEqual(first['raw/measurements.jsonl.gz'], canonical_gzip(raw))
        self.assertTrue(first['raw/measurements.jsonl.gz'].startswith(bytes.fromhex('1f8b08000000000000ff')))
        manifest = json.loads(first['manifest.json'])
        self.assertEqual(manifest['files'], {spec['report_path'] + '/' + n: hashlib.sha256(first[n]).hexdigest() for n in BUNDLE_FILES if n != 'manifest.json'})
        for data in (b'', b'x', bytes(range(256)) * 600):      # empty, one block, more than one block of 65,535 bytes
            with self.subTest(size=len(data)):
                packed = canonical_gzip(data)
                self.assertEqual(gzip.decompress(packed), data)
                blocks, offset = [], 10
                while True:
                    final, size = packed[offset], int.from_bytes(packed[offset + 1:offset + 3], 'little')
                    self.assertEqual(int.from_bytes(packed[offset + 3:offset + 5], 'little'), size ^ 0xffff)
                    blocks.append(size)
                    offset += 5 + size
                    if final:
                        break
                self.assertEqual(sum(blocks), len(data))
                self.assertTrue(all(b <= 65535 for b in blocks))
                self.assertEqual(len(packed), offset + 8)
        self.assertEqual(canonical_csv([{'a': 1, 'b': 'x,y'}], ['a', 'b']), b'a,b\n1,"x,y"\n')
        self.assertEqual(canonical_json({'b': 1, 'a': 'é'}), '{\n  "a": "é",\n  "b": 1\n}\n'.encode())

    def test_windows_to_git_path_keeps_every_blob_equal_to_the_manifest(self):
        directory = self.smoke(LOCK, 'crlf')
        report = self.report(directory)
        self.authorize(directory)
        repo, bare = self.repository(autocrlf='true')
        api = RecordingGitHub()
        result = self.publish(report, repo, api)
        dest, spec = bundle_dir(report)
        manifest = read_json(dest / 'manifest.json')
        expected = {**manifest['files'], spec['report_path'] + '/manifest.json': sha256_file(dest / 'manifest.json')}
        for name, sha in expected.items():
            blob = subprocess.run(['git', '-C', str(bare), 'cat-file', 'blob', result['branch'] + ':' + name], capture_output=True, check=True).stdout
            self.assertEqual(hashlib.sha256(blob).hexdigest(), sha, name)
        listed = subprocess.run(['git', '-C', str(bare), 'ls-tree', '-r', '--name-only', result['branch'], '--', spec['report_path']],
                                capture_output=True, text=True, check=True).stdout.split()
        self.assertEqual(sorted(listed), sorted(expected))

    def test_mismatched_bytes_abort_before_push_without_a_new_receipt(self):
        directory = self.smoke(LOCK, 'mismatch')
        report = self.report(directory)
        self.authorize(directory)
        repo, bare = self.repository(autocrlf='true', attributes=b'* -text\n')      # an attributes policy that converts nothing
        from llm_eval.reporting import publish as module
        original = module.write_index
        dest, spec = bundle_dir(report)

        def crlf(worktree):
            original(worktree)
            path = Path(worktree) / spec['report_path'] / 'README.md'
            path.write_bytes(path.read_bytes().replace(b'\n', b'\r\n'))
        api = RecordingGitHub()
        with patch('llm_eval.reporting.publish.write_index', side_effect=crlf), \
                self.assertRaisesRegex(ValueError, 'Committed bytes differ from the manifest: .*README.md'):
            self.publish(report, repo, api)
        self.assertEqual(api.created, 0)
        self.assertEqual(subprocess.run(['git', '-C', str(bare), 'for-each-ref', '--format=%(refname:short)', 'refs/heads'], capture_output=True, text=True).stdout.split(), ['main'])
        self.assertFalse((report / 'publication-state.json').exists())
        self.assertEqual(read_json(report / 'publication-error.json'), {'status': 'pending', 'error_type': 'ValueError'})
        self.assertEqual(read_json(dest / 'manifest.json')['report_fingerprint'], read_json(report / 'publication.json')['report_fingerprint'])


# 5. Cohorts -----------------------------------------------------------------------------------------------------------

def role(name='generator', **changes):
    value = generator(role=name, **changes) if name in ('generator', 'analyst') else changes
    return value


class CohortCase(Base):
    MATTERS = ('f1-ledger-a', 'f1-ledger-b')

    def setUp(self):
        super().setUp()
        self.lock = subset_suite(self.path / 'subset', self.MATTERS)
        self.suite = contracts.load_suite(self.lock)
        self.replies = {}

    def respond(self, body):
        content = body['messages'][1]['content']
        matter = next(m for m in self.suite['matters']['matters'] if 'MATTER ' + m['matter_id'] + '\n' in content)
        if 'analysis v1' in body['messages'][0]['content']:
            return ANALYSIS(matter['matter_id'])
        import re
        output = fixture.draft(matter, self.suite['corpus'])
        listed = set(re.findall(r'^\[([a-z0-9-]+@[0-9]+)\] ', content, re.M))
        if listed:
            output['claims'] = [c for c in output['claims'] if c['authority_id'] + '@' + c['version'] in listed]
        return self.replies.get(matter['matter_id'], json.dumps(output))

    def run_mode(self, name, mode, parameters, lock=None):
        with FakeGenerator(respond=self.respond) as fake:
            parameters = json.loads(json.dumps(parameters).replace('FAKE_ENDPOINT', fake.endpoint))
            directory, code = self.run_plan(self.plan(name, mode, {'suite': str(lock or self.lock), **parameters}), name)
        self.assertEqual(code, 0)
        return directory

    def metadata(self, name, mode, parameters):
        directory = self.run_mode(name, mode, parameters)
        return read_json(directory / 'plan.json')['jobs'][0], read_json(self.attempt(directory) / 'metadata.json')


class CohortTests(CohortCase):
    def test_cohort_covers_every_term_of_the_plan_row(self):
        directory = self.run_mode('terms', 'generation', {'arms': ['lexical-eligible'], 'roles': {'generator': generator('FAKE_ENDPOINT')}})
        job = read_json(directory / 'plan.json')['jobs'][0]
        metadata = read_json(self.attempt(directory) / 'metadata.json')
        _, base = lr.cohort(job, metadata, 'lexical-eligible')
        from llm_eval.experiments.legal_benchmark import profiles

        def role_change(**changes):
            def apply(j, m):
                profile = {**j['parameters']['roles']['generator'], **changes}
                m['roles']['generator'] = profiles.public_role(profile, j['input_files'])
            return apply
        terms = [('GGUF digest, same model and revision', role_change(artifact_sha256='5' * 64)), ('quantization', role_change(quantization='Q8_0')),
                 ('adapter platform', role_change(platform='lmstudio')), ('adapter protocol', role_change(protocol='ollama')),
                 ('chat template of the generator', role_change(template_sha256='3' * 64)),
                 ('prompt template', lambda j, m: m.update(template_sha256='4' * 64)), ('arm', None),
                 ('OS', lambda j, m: j['hardware'].update(os_id='windows-11-native')), ('placement', role_change(placement={'gpu_layers': 20})),
                 ('context', role_change(context_tokens=4096))]
        for name, change in terms:
            with self.subTest(name):
                j, m = copy.deepcopy(job), copy.deepcopy(metadata)
                if change:
                    change(j, m)
                self.assertNotEqual(lr.cohort(j, m, 'no-context' if name == 'arm' else 'lexical-eligible')[1], base)
        self.assertEqual(lr.cohort(copy.deepcopy(job), copy.deepcopy(metadata), 'lexical-eligible')[1], base)

    def test_result_changing_parameters_change_the_cohort(self):
        from tests.test_legal_retrieval import EMBEDDER, RERANKER
        generation = {'arms': ['lexical-eligible'], 'roles': {'generator': generator('FAKE_ENDPOINT')}}
        base_job, base_meta = self.metadata('base', 'generation', generation)
        base = lr.cohort(base_job, base_meta, 'lexical-eligible')[1]
        retrieval_base = {'synthetic': True, 'arms': ['lexical', 'dense', 'reranked']}
        r_job, r_meta = self.metadata('r-base', 'retrieval', {**retrieval_base, 'roles': {'embedder': EMBEDDER, 'reranker': RERANKER}})
        changes = [('top_k', 'generation', {**generation, 'top_k': 3}), ('token_budget', 'generation', {**generation, 'token_budget': 600}),
                   ('backend', 'generation', {**generation, 'backend': 'fts5' if retrieval.fts5_available() else 'auto'}),
                   ('seed', 'generation', {**generation, 'seed': 2}), ('temperature', 'generation', {**generation, 'temperature': 0.5}),
                   ('parse_retries', 'generation', {**generation, 'parse_retries': 0}), ('repeats', 'generation', {**generation, 'repeats': 2}),
                   ('max_output_tokens', 'generation', {**generation, 'max_output_tokens': 512}),
                   ('analyst role', 'workflow', {**generation, 'roles': {**generation['roles'], 'analyst': generator('FAKE_ENDPOINT', role='analyst')}})]
        for name, mode, parameters in changes:
            with self.subTest(name):
                if name == 'backend' and not retrieval.fts5_available():
                    self.skipTest('no FTS5 backend on this Python')
                job, meta = self.metadata(name.replace(' ', '-').replace('_', '-'), mode, parameters)
                self.assertNotEqual(lr.cohort(job, meta, 'lexical-eligible')[1], base)
        r_base = {arm: lr.cohort(r_job, r_meta, arm)[1] for arm in ('lexical', 'dense', 'reranked')}
        for name, roles in (('embedder role', {'embedder': {**EMBEDDER, 'model_revision': '2'}, 'reranker': RERANKER}),
                            ('reranker role', {'embedder': EMBEDDER, 'reranker': {**RERANKER, 'model_revision': '2'}})):
            with self.subTest(name):
                job, meta = self.metadata(name.replace(' ', '-'), 'retrieval', {**retrieval_base, 'roles': roles})
                for arm in ('lexical', 'dense', 'reranked'):
                    self.assertNotEqual(lr.cohort(job, meta, arm)[1], r_base[arm], arm)
        with self.subTest('selector'):
            from tests.test_legal_routing import CATEGORY
            job, meta = self.metadata('routed', 'generation', {'arms': ['no-context', 'lexical-eligible'], 'roles': generation['roles'],
                                                               'selector': CATEGORY})
            routed = lr.cohort(job, meta, 'routed')[1]
            self.assertNotEqual(routed, base)
            plain_job, plain_meta = self.metadata('unrouted', 'generation', {'arms': ['no-context', 'lexical-eligible'], 'roles': generation['roles']})
            self.assertNotIn(routed, {lr.cohort(plain_job, plain_meta, arm)[1] for arm in ('no-context', 'lexical-eligible')})
        with self.subTest('serving-profile qualification'):
            from llm_eval.experiments.legal_benchmark import profiles
            qualified = copy.deepcopy(base_meta)
            profile = {**base_job['parameters']['roles']['generator'], 'qualification': {'serving_profile': str(self.path / 'profile.json')}}
            write_json(self.path / 'profile.json', {'fixture': True})
            qualified['roles']['generator'] = profiles.public_role(profile, [{'path': str(self.path / 'profile.json'), 'sha256': '9' * 64}])
            self.assertNotEqual(lr.cohort(base_job, qualified, 'lexical-eligible')[1], base)
        with self.subTest('score jobs'):
            source = self.run_mode('source', 'generation', generation)
            other = self.run_mode('source-2', 'generation', {**generation, 'roles': {'generator': generator('FAKE_ENDPOINT', model='other-chat')}})
            digests = []
            for name, attempt in (('score-1', self.attempt(source)), ('score-2', self.attempt(other))):
                scored = self.run_mode(name, 'score', {'output_manifest': str(attempt / 'local/output-manifest.json')})
                digests.append(lr.cohort(read_json(scored / 'plan.json')['jobs'][0], read_json(self.attempt(scored) / 'metadata.json'),
                                         'lexical-eligible')[1])
            self.assertNotEqual(digests[0], digests[1])
            job, meta = read_json(scored / 'plan.json')['jobs'][0], read_json(self.attempt(scored) / 'metadata.json')
            self.assertNotEqual(lr.cohort(job, {**meta, 'reviewer_fingerprint': '8' * 64}, 'lexical-eligible')[1], digests[1])

    def test_scores_carry_counts_intervals_and_missing(self):
        report = self.report(self.smoke(LOCK, 'counts'))
        (entry,) = read_json(bundle_dir(report)[0] / 'legal-summary.json')['cohorts']
        for name, metric in entry['metrics'].items():
            self.assertEqual(set(metric), {'value', 'n', 'low', 'high', 'missing'}, name)
        all_pass = entry['metrics']['all_pass']
        self.assertEqual((all_pass['n'], all_pass['missing']), (16, 0))
        self.assertIsNotNone(all_pass['low'])      # eight families: the family bootstrap gives an interval
        self.assertLessEqual(all_pass['low'], all_pass['value'])
        self.assertEqual(entry['metrics']['status.ok'], {'value': 16, 'n': 16, 'low': None, 'high': None, 'missing': 0})
        self.assertEqual(entry['metrics']['retrieval.evidence_recall_at_5'], {'value': None, 'n': 0, 'low': None, 'high': None, 'missing': 16})
        for name in ('missing.pending', 'missing.unavailable', 'missing.no_response'):
            self.assertEqual(entry['metrics'][name]['value'], 0)
        self.assertEqual(entry['run_status'], 'complete')

    def test_paired_differences_and_confusion_are_in_the_summary(self):
        directory = self.run_mode('paired', 'generation', {'arms': ['no-context', 'lexical-eligible', 'reference'],
                                                           'roles': {'generator': generator('FAKE_ENDPOINT')}})
        legal_summary = read_json(bundle_dir(self.report(directory))[0] / 'legal-summary.json')
        self.assertEqual([c['arm'] for c in legal_summary['cohorts']], ['lexical-eligible', 'no-context', 'reference'])
        for metric in lr.PAIRED_METRICS:
            pairs = [(p['arm_a'], p['arm_b']) for p in legal_summary['paired'] if p['metric'] == metric]
            self.assertEqual(pairs, [('no-context', 'lexical-eligible'), ('no-context', 'reference'), ('lexical-eligible', 'reference')])
        for entry in legal_summary['cohorts']:
            names = set(entry['metrics'])
            self.assertTrue({f'confusion.{g}.{a}' for g in contracts.RECOMMENDATIONS for a in contracts.RECOMMENDATIONS} <= names)
            self.assertTrue({f'workflow_confusion.{g}.{a}' for g in contracts.RECOMMENDATIONS for a in contracts.RECOMMENDATIONS} <= names)
            self.assertTrue({'error.' + c for c in grading.REASONS} | {'critical_errors', 'critical_unreviewed'} <= names)
        rows = [r for r in raw_records(self.report(directory)) if r['record_type'] == 'request']
        self.assertEqual(rows, [])      # a model-run mode publishes cohort aggregates, never per-matter rows

    def test_generic_and_legal_pass_rates_agree(self):
        self.lock = LOCK
        self.suite = contracts.load_suite(LOCK)
        self.replies = {'f3-market-a': 'not a memo at all'}
        directory = self.run_mode('agree', 'generation', {'arms': ['lexical-eligible'], 'roles': {'generator': generator('FAKE_ENDPOINT')}}, lock=LOCK)

        def rates(report):
            dest, _ = bundle_dir(report)
            summary = [r for r in read_json(dest / 'summary.json') if r['category'] == 'lexical-eligible']
            checks = sum(r['quality_check_n'] for r in summary)
            passes = sum(round(r['quality_pass_rate'] * r['quality_check_n']) for r in summary if r['quality_pass_rate'] is not None)
            (entry,) = read_json(dest / 'legal-summary.json')['cohorts']
            return passes / checks, entry['metrics']['all_pass']['value'], checks, entry['metrics']['all_pass']['n']
        generic, legal_rate, checks, n = rates(self.report(directory))
        self.assertEqual((round(generic, 6), checks), (legal_rate, n))
        self.assertLess(legal_rate, 1.0)
        (cohort,) = read_json(bundle_dir(self.report(directory))[0] / 'legal-summary.json')['cohorts']
        self.assertEqual((cohort['metrics']['status.invalid']['value'], cohort['run_status']), (1, 'complete'))      # an incorrect answer
        # A row whose grading is pending lowers neither rate: it leaves both denominators.
        attempt = self.attempt(directory)
        rows, details = lines(attempt / 'requests.jsonl'), lines(attempt / 'local/score-detail.jsonl')
        target = next(i for i, d in enumerate(details) if d['grading_status'] == 'scored' and grading.all_pass(d))
        details[target]['grading_status'] = 'pending'
        rows[target].update(grading_status='pending', quality_check_applicable=False, quality_pass=None, criteria_passed=None)
        (attempt / 'requests.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in rows), encoding='utf-8', newline='\n')
        (attempt / 'local/score-detail.jsonl').write_text(''.join(json.dumps(d) + '\n' for d in details), encoding='utf-8', newline='\n')
        self.rereceipt(directory)      # the edit is deliberate: record it as the coordinator would
        generic2, legal2, checks2, n2 = rates(build_report(self.experiment_dir(directory)))
        self.assertEqual((round(generic2, 6), checks2, n2), (legal2, checks - 1, n - 1))
        # Retrieval: no grading metric, no paired entry, and the generic pass rate is the exact-version pass rate.
        retrieved = self.run_mode('retrieval', 'retrieval', {'synthetic': True, 'arms': ['lexical', 'lexical-eligible', 'reference']}, lock=LOCK)
        dest, _ = bundle_dir(self.report(retrieved))
        legal_summary = read_json(dest / 'legal-summary.json')
        self.assertEqual(legal_summary['paired'], [])
        self.assertTrue(all(set(c['metrics']) == set(lr.ROW_METRICS) for c in legal_summary['cohorts']))
        source = lines(self.attempt(retrieved) / 'requests.jsonl')
        for row in read_json(dest / 'summary.json'):
            applicable = [r for r in source if r['arm'] == row['category'] and r['exact_version_recall'] is not None]
            expected = sum(r['exact_version_recall'] == 1.0 and r['ineligible_version_leakage'] in (0, None) for r in applicable) / len(applicable) \
                if applicable else None
            self.assertEqual(row['quality_pass_rate'], expected, row['category'])
        # A reduced projection: no quality rate in the generic summary; the legal summary keeps all_pass.
        reduced = self.run_mode('reduced', 'generation', {'arms': ['lexical-eligible'], 'roles': {'generator': generator('FAKE_ENDPOINT')}},
                                lock=subset_suite(self.path / 'reduced-suite', self.MATTERS))
        dest, _ = bundle_dir(self.report(reduced))
        self.assertTrue(all(r['quality_pass_rate'] is None and r['benchmark'] == 'unspecified' for r in read_json(dest / 'summary.json')))
        cohort = read_json(dest / 'legal-summary.json')['cohorts'][0]      # two matters: below the minimum, the whole cohort
        self.assertEqual((cohort['suppressed'], cohort['metrics']['all_pass']), (True, lr.SMALL_METRIC))


# 6. Canaries ----------------------------------------------------------------------------------------------------------

class CanaryTests(Base):
    def scan(self, *texts):
        for text in texts:
            self.assertNotIn(CANARY.lower(), (text.decode('utf-8', 'replace') if isinstance(text, bytes) else str(text)).lower())

    def test_canaries_never_cross_any_boundary(self):
        # Fail closed at plan: identifiers.
        for name, options in (('case id', {'case_id': CANARY}), ('phase id', {'phase': CANARY})):
            with self.subTest(name), self.assertRaises(ValueError) as raised:
                self.plan('canary-' + name.replace(' ', '-'), **options)
            self.scan(str(raised.exception))
        # Fail closed at plan: a role model that is a path.
        with self.subTest('role model'):
            try:
                plan = self.plan('model', 'generation', {'suite': str(LOCK), 'arms': ['no-context'],
                                                         'roles': {'generator': generator(model='C:/' + CANARY + '/qwen.gguf')}})
            except ValueError as exc:
                self.scan(str(exc))
            else:
                directory, _ = self.run_plan(plan, 'model')
                self.scan(json.dumps(read_json(directory / 'campaign.json')))
                report = directory / 'experiments'
                self.assertFalse(any(report.glob('*/report')))
        # Absent: the suite revision of a relocked copy (a reduced projection omits the strings of the lock).
        lock = self.copy('canary-suite', revision=CANARY)
        directory = self.smoke(lock, 'canary-revision')
        report = self.report(directory)
        self.scan(all_bytes(report / 'bundle'), gzip.decompress((bundle_dir(report)[0] / 'raw/measurements.jsonl.gz').read_bytes()),
                  (report / 'publication.json').read_bytes(), (directory / 'campaign.json').read_bytes())
        # An approved run with canaries in every local place; then everything that can cross a boundary is scanned.
        directory = self.smoke(LOCK, 'canary-local')
        attempt = self.attempt(directory)
        (attempt / (CANARY + '.json')).write_text('{}\n', encoding='utf-8')
        (attempt / 'local' / (CANARY + '.jsonl')).write_text('{}\n', encoding='utf-8')
        (attempt / 'local/requests.jsonl').write_text(json.dumps({'task_id': CANARY, 'category': CANARY}) + '\n', encoding='utf-8')
        (attempt / 'worker.log').write_text(CANARY + '\n', encoding='utf-8')
        write_json(attempt / 'host.json', {'node': CANARY})
        self.assertEqual(self.refinalize(directory)['status'], 'generated')
        self.authorize(directory)
        report = self.report(directory)
        code, output = cli('report', '--input', str(directory))
        self.assertEqual(code, 0)
        code2, output2 = cli('publish-results', '--input', str(report), '--project-root', str(ROOT), '--dry-run')
        self.assertEqual(code2, 0)
        repo, bare = self.repository()
        api = RecordingGitHub()
        result = self.publish(report, repo, api)
        log = subprocess.run(['git', '-C', str(bare), 'log', '--format=%B', result['branch']], capture_output=True, text=True, check=True).stdout
        self.scan(all_bytes(report / 'bundle'), gzip.decompress((bundle_dir(report)[0] / 'raw/measurements.jsonl.gz').read_bytes()),
                  (report / 'publication.json').read_bytes(), (directory / 'campaign.json').read_bytes(), output, output2,
                  json.dumps(api.bodies), result['branch'], log)
        # Fail closed: score detail, rows, metadata, exceptions; and no message carries the canary.
        details0 = (attempt / 'local/score-detail.jsonl').read_text(encoding='utf-8')
        rows0, meta0 = (attempt / 'requests.jsonl').read_text(encoding='utf-8'), (attempt / 'metadata.json').read_text(encoding='utf-8')
        pristine = {name: (attempt / name).read_bytes() for name in ('requests.jsonl', 'metadata.json', 'local/score-detail.jsonl')}

        def edit(name, original, change):
            def apply():
                if name == 'metadata.json':
                    value = json.loads(original)
                    change(value)
                    write_json(attempt / name, value)
                    return
                values = [json.loads(line) for line in original.splitlines()]
                change(values[0])
                (attempt / name).write_text(''.join(json.dumps(v) + '\n' for v in values), encoding='utf-8')
            return apply
        failing = [('criterion key', edit('local/score-detail.jsonl', details0, lambda d: d['criteria'].update({CANARY: True}))),
                   ('error code', edit('local/score-detail.jsonl', details0, lambda d: d.update(errors=[{'code': CANARY, 'critical': True}]))),
                   ('gold recommendation', edit('local/score-detail.jsonl', details0, lambda d: d.update(gold_recommendation=CANARY))),
                   ('row key', edit('requests.jsonl', rows0, lambda r: r.update({CANARY: 1}))),
                   ('row category', edit('requests.jsonl', rows0, lambda r: r.update(category=CANARY))),
                   ('nested metadata', edit('metadata.json', meta0, lambda m: m.update(roles={'generator': {'note': CANARY}})))]
        for name, apply in failing:
            with self.subTest(name):
                apply()
                receipt = self.refinalize(directory)
                self.assertEqual((receipt['status'], receipt['error_type']), ('failed', 'ProjectionRejected'))
                code, output = cli('report', '--input', str(self.experiment_dir(directory)))
                self.assertEqual(code, 2)
                self.scan(output, json.dumps(receipt), (directory / 'campaign.json').read_bytes())
                for file_name, data in pristine.items():      # the bytes the receipt names
                    (attempt / file_name).write_bytes(data)
        with self.subTest('exception message'):
            with patch('llm_eval.experiments.legal_benchmark.grading.aggregate', side_effect=RuntimeError(CANARY)):
                receipt = self.refinalize(directory)
                code, output = cli('report', '--input', str(self.experiment_dir(directory)))
            self.assertEqual((receipt['status'], receipt['error_type'], code), ('failed', 'ProjectionRejected', 2))
            self.scan(output, json.dumps(receipt))
        self.assertEqual(self.refinalize(directory)['status'], 'generated')
        # Fail closed: every field of publication.json, and the campaign directory name.
        pristine = (report / 'publication.json').read_bytes()
        for key, value in json.loads(pristine).items():
            if not isinstance(value, str):      # `draft` and `max_artifact_bytes` cannot carry text
                continue
            with self.subTest(publication=key):
                (report / 'publication.json').write_bytes(canonical_json({**json.loads(pristine), key: CANARY}))
                code, output = cli('publish-results', '--input', str(report), '--project-root', str(ROOT), '--dry-run')
                self.assertEqual(code, 2)
                self.scan(output)
        (report / 'publication.json').write_bytes(pristine)
        experiment = self.experiment_dir(directory)
        renamed = directory.parent / ('campaign-' + CANARY)
        os.replace(directory, renamed)
        code, output = cli('publish-results', '--input', str(renamed / report.relative_to(directory)), '--project-root', str(ROOT), '--dry-run')
        self.assertEqual(code, 2)
        self.scan(output)
        with self.assertRaises(lr.ProjectionRejected) as raised:
            build_report(renamed / experiment.relative_to(directory))
        self.scan(str(raised.exception))

    def test_staged_bundle_and_diff_pass_allowlist_and_canary_scan(self):
        directory = self.smoke(LOCK, 'staged')
        attempt = self.attempt(directory)
        (attempt / 'local' / (CANARY + '.txt')).write_text(CANARY, encoding='utf-8')
        self.assertEqual(self.refinalize(directory)['status'], 'generated')
        report = self.report(directory)
        self.authorize(directory)
        repo, bare = self.repository()
        result = self.publish(report, repo, RecordingGitHub())
        dest, spec = bundle_dir(report)
        changed = subprocess.run(['git', '-C', str(bare), 'diff', '--name-only', 'main', result['branch']], capture_output=True, text=True,
                                 check=True).stdout.split()
        allowed = (spec['report_path'] + '/', 'docs/results/index/', 'diagrams/results/summary/')
        self.assertTrue(changed)
        for name in changed:
            self.assertTrue(name.startswith(allowed) or name in ('docs/results/README.md', 'README.md'), name)
            blob = subprocess.run(['git', '-C', str(bare), 'cat-file', 'blob', result['branch'] + ':' + name], capture_output=True, check=True).stdout
            self.scan(blob if not name.endswith('.gz') else gzip.decompress(blob))
        diff = subprocess.run(['git', '-C', str(bare), 'diff', 'main', result['branch']], capture_output=True, check=True).stdout
        self.scan(diff)
        self.assertEqual(sorted(n[len(spec['report_path']) + 1:] for n in changed if n.startswith(spec['report_path'] + '/')), BUNDLE_FILES)

    def test_remote_private_denial_with_a_fake_transport(self):
        from llm_eval.orchestration.transport import collect
        (job,) = self.plan('remote', parameters={'suite': str(self.copy()), 'synthetic': True})['jobs']
        private = self.copy('private', 'private-matter')
        job['parameters']['suite'] = str(private)
        job['input_files'] = [{'path': str(private), 'sha256': sha256_file(private)}]
        attempt = self.path / 'worker' / ('d' * 32)
        (attempt / 'local').mkdir(parents=True)
        atomic_json(attempt / 'job.json', job)
        (attempt / 'local/candidate-outputs.jsonl').write_text(CANARY + '\n', encoding='utf-8')
        replies = []

        def rpc(target, payload, root, timeout=60):
            try:
                reply = worker.handle(payload)
            except BaseException as exc:      # the worker's own reply for an exception
                reply = {'error': type(exc).__name__}
                replies.append(reply)
                raise RuntimeError('Worker rejected request: ' + reply['error'])
            replies.append(reply)
            return reply
        destination = self.path / 'coordinator'
        with patch('llm_eval.orchestration.transport.rpc', side_effect=rpc):
            with self.assertRaisesRegex(RuntimeError, 'Worker rejected request: ValueError'):
                collect(SSH, attempt, ROOT, destination)
            with self.assertRaisesRegex(RuntimeError, 'Worker rejected request'):
                rpc(SSH, {'action': 'run', 'job': job, 'root': str(ROOT), 'output': str(attempt / 'run'), 'owner': 'o',
                          'code_revision': revision(ROOT)}, ROOT)
        self.assertFalse(destination.exists() and any(destination.iterdir()))
        self.scan(json.dumps(replies))


# 7. Gaps the earlier packages left (F-must-close) ----------------------------------------------------------------------

class ContentTests(Base):
    """Must-close A.1, A.2 and B.9: a bundle of another experiment built from a legal export is refused by content."""

    def routing_bundle(self, suite_file, name='content'):
        case = {'suite': suite_file, 'synthetic': True, 'router': {'kind': 'fixed', 'choice': 'lexical-eligible'}}
        write_json(self.path / f'{name}-case.json', {'id': name, 'parameters': case})
        write_json(self.path / f'{name}-campaign.json', {'schema_version': 2, 'id': name, 'inventory': 'inventory.json', 'phases': [
            {'id': 'routing', 'experiments': [{'id': 'llm-routing', 'version': 1, 'mode': 'decision', 'cases': [f'{name}-case.json'],
                                               'hardware_configs': ['native']}]}]})
        directory, _ = self.run_plan(compile_campaign(self.path / f'{name}-campaign.json', ROOT), name)
        return directory / self.receipt(directory)['report']

    def test_bundles_of_other_experiments_built_from_legal_exports_are_refused(self):
        from llm_eval.experiments.legal_benchmark import profiles, routing
        exported = routing.route_tasks(contracts.load_suite(LOCK))
        # Neither the benchmark name nor the category `legal` decides the renamed cases: the content does (task id, then pinned input).
        anonymous = [{**t, 'id': 'q' + str(i), 'category': 'general'} for i, t in enumerate(exported['tasks'])]
        for name, benchmark, tasks, message in (('renamed', 'routing-fixture', None, r'carries content of legal-benchmark \(task id\)$'),
                                                ('anonymous', 'routing-fixture', anonymous, r'carries content of legal-benchmark \(pinned input\)$'),
                                                ('underscored', 'legal_routing', None, 'carries a legal benchmark name'),
                                                ('joined', 'legalrouting', None, 'carries a legal benchmark name')):
            with self.subTest(name=name, benchmark=benchmark):
                path = self.path / f'{name}-suite.json'
                write_json(path, {**exported, 'benchmark': benchmark, 'tasks': tasks or exported['tasks']})      # the approved export's tasks, renamed
                report = self.routing_bundle(str(path), name=name)
                with self.assertRaisesRegex(ValueError, message):
                    publish_report(report, ROOT, dry_run=True)
        # A workload export renamed for model-offloading: refused by its task list, whatever the benchmark is called.
        workload = profiles.workload(LOCK)
        renamed = self.path / 'workload.json'
        write_json(renamed, {**workload, 'benchmark': 'category-smoke'})
        self.assertIsNone(lr.claims_bundle(self.path / 'nowhere' / 'report', self.path, {}, {}, []))
        self.assertTrue(lr._legal_file(renamed, lr._markers()))
        # Rows of approved matters in category legal, or the text markers of the exports, in any bundle.
        rows = [{'record_type': 'request', 'data': {'task_id': 'f1-ledger-a', 'category': 'legal'}}]
        self.assertTrue(lr.claims_bundle(self.path / 'x' / 'report', self.path, {}, {}, rows))
        self.assertTrue(lr.claims_bundle(self.path / 'x' / 'report', self.path, {}, {}, [{'record_type': 'request', 'data': {
            'messages': [{'role': 'user', 'content': exported['tasks'][0]['messages'][0]['content']}]}}]))
        self.assertTrue(lr.claims_bundle(self.path / 'x' / 'report', self.path, {}, {}, [{'record_type': 'request', 'data': {
            'prompt': workload['tasks'][0]['messages'][-1]['content']}}]))
        self.assertTrue(lr.claims_bundle(self.path / 'x' / 'report', self.path, {}, {'input_hashes': [sha256_file(LOCK)]}, []))
        # A replay manifest of legal matters (per-matter gold-derived quality): never public.
        replay = self.path / 'replay.json'
        write_json(replay, {'suite_sha256': '0' * 64, 'candidate_fingerprints': {},
                            'rows': [{'task_id': 'f1-ledger-a', 'candidate': 'no-context', 'quality': 1.0, 'latency_s': 1.0, 'cost_usd': 0}]})
        self.assertTrue(lr._legal_file(replay, lr._markers()))
        # The routing experiment's own bundle publishes as before.
        report = self.routing_bundle(str(ROOT / 'experiments/llm-routing/workloads/decisions.json'), name='own')
        self.assertTrue(publish_report(report, ROOT, dry_run=True)['dry_run'])

    def test_a_campaign_moved_under_a_scanned_directory_is_refused(self):
        """Must-close A.4: the scanned-directory rule holds on the coordinator's path too."""
        directory = self.smoke(LOCK, 'moved', reporting={'on_experiment_end': False})
        for scanned in ('reports', 'Model_Judgment'):
            with self.subTest(scanned=scanned):
                target = self.path / scanned / directory.name
                target.parent.mkdir(exist_ok=True)
                shutil.copytree(directory, target)
                with self.assertRaisesRegex(lr.ProjectionRejected, 'scanned_directory'):
                    build_report(self.experiment_dir(target))
                self.assertFalse((self.experiment_dir(target) / 'report').exists())


class LineageTests(CohortCase):
    """Must-close C.11: the output manifest of an attempt is bound to the coordinator's campaign record."""

    def test_output_manifest_is_bound_to_the_campaign_record(self):
        self.lock, self.suite = LOCK, contracts.load_suite(LOCK)      # an approved suite: publication is reachable
        source = self.run_mode('bound', 'generation', {'arms': ['lexical-eligible'], 'roles': {'generator': generator('FAKE_ENDPOINT')}})
        record = next(iter(read_json(source / 'campaign.json')['jobs'].values()))['attempts'][-1]
        attempt = source / record['output']
        self.assertEqual(record['output_manifest_sha256'], sha256_file(attempt / 'local/output-manifest.json'))
        scored = self.run_mode('scored', 'score', {'output_manifest': str(attempt / 'local/output-manifest.json')})
        self.assertEqual(self.receipt(scored)['status'], 'generated')
        # A fully consistent forgery inside the campaign layout: an output and its row edited, the manifest resealed.
        manifest = read_json(attempt / 'local/output-manifest.json')
        outputs = lines(attempt / 'local/candidate-outputs.jsonl')
        outputs[0]['output'] = {**outputs[0]['output'], 'recommendation': 'decline'}
        (attempt / 'local/candidate-outputs.jsonl').write_text(''.join(json.dumps(o, sort_keys=True) + '\n' for o in outputs), encoding='utf-8',
                                                                newline='\n')
        for f in manifest['files']:
            target = attempt / f['path']
            f.update(size=target.stat().st_size, sha256=sha256_file(target))
        (attempt / 'local/output-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8', newline='\n')
        with self.assertRaisesRegex(ValueError, 'Output manifest differs from the campaign record'):
            grading.score_records({'output_manifest': str(attempt / 'local/output-manifest.json')}, self.suite)
        with self.assertRaisesRegex(ValueError, 'Output manifest differs from the campaign record'):
            self.plan('forged-score', 'score', {'suite': str(self.lock), 'output_manifest': str(attempt / 'local/output-manifest.json')})
        # The same attempt copied out of its campaign layout has no record to check against (the earlier packages' behaviour).
        loose = self.path / 'loose' / attempt.name
        shutil.copytree(attempt, loose)
        self.assertTrue(grading.score_records({'output_manifest': str(loose / 'local/output-manifest.json')}, self.suite))
        # Publication: verified with the record intact; a record without the manifest digest is exactly a receipt mismatch.
        clean = self.run_mode('clean', 'generation', {'arms': ['lexical-eligible'], 'roles': {'generator': generator('FAKE_ENDPOINT')}})
        report = self.report(clean)
        self.authorize(clean)
        lr.verify_publication(report, ROOT)
        state = read_json(clean / 'campaign.json')
        next(iter(state['jobs'].values()))['attempts'][-1].pop('output_manifest_sha256')
        write_json(clean / 'campaign.json', state)
        with self.assertRaisesRegex(ValueError, '^receipt_mismatch$'):
            lr.verify_publication(report, ROOT)

    def test_routed_deferrals_error_rows_and_reference_arm_project(self):
        """Must-close B.7 and B.8: deferral rows, error rows and reference-arm rows project as cohort aggregates."""
        from tests.test_legal_routing import FakeSelector, by_question, selector_role, served
        self.lock, self.suite = LOCK, contracts.load_suite(LOCK)      # approved: no cohort is below the minimum size
        self.replies = {'f1-ledger-b': {'status': 500}}
        with FakeSelector(lambda body: by_question(body, {'warehouse': 'insufficient_evidence'})) as selector:
            directory = self.run_mode('routed', 'generation', {'arms': ['no-context', 'lexical-eligible'], 'selector': served(),
                                                               'roles': {'generator': generator('FAKE_ENDPOINT'),
                                                                         'selector': selector_role(selector.endpoint)}})
        (entry,) = read_json(bundle_dir(self.report(directory))[0] / 'legal-summary.json')['cohorts']
        self.assertEqual(entry['arm'], 'routed')
        self.assertGreater(entry['metrics']['rate.selector_deferral']['value'], 0)
        self.assertEqual(entry['cohort']['selector_sha256'], read_json(self.attempt(directory) / 'metadata.json')['selector']['selector_sha256'])
        self.replies = {'f1-ledger-a': {'status': 500}}
        directory = self.run_mode('errors', 'generation', {'arms': ['lexical-eligible', 'reference'], 'roles': {'generator': generator('FAKE_ENDPOINT')}})
        cohorts = {c['arm']: c for c in read_json(bundle_dir(self.report(directory))[0] / 'legal-summary.json')['cohorts']}
        self.assertEqual(cohorts['lexical-eligible']['metrics']['status.error']['value'], 1)
        self.assertEqual(cohorts['lexical-eligible']['run_status'], 'incomplete')
        self.assertEqual({k: cohorts['reference']['metrics']['all_pass'][k] for k in ('n', 'missing')}, {'n': 15, 'missing': 1})      # graded here
        summary = {r['category']: r for r in read_json(bundle_dir(self.report(directory))[0] / 'summary.json')}
        self.assertEqual(summary['reference']['quality_check_n'], 0)      # the generic summary does not


# 8. Review fixes (fixlist-F) -------------------------------------------------------------------------------------------

def relabel(report, target, experiment='llm-routing', mode='decision', benchmark='smoke', category=None, rename_ids=False):
    """A legal report rewritten by hand into a bundle of another experiment: copied to `target`, every label and the benchmark
    renamed, the projection marker, canonical flag, input hashes and job input files stripped, a benchmark summary added,
    hashes and fingerprint recomputed. The bundle is self-consistent (`validate_bundle` passes)."""
    shutil.copytree(report, target)
    dest, spec = bundle_dir(target)
    records = []
    for r in [json.loads(line) for line in gzip.decompress((dest / 'raw/measurements.jsonl.gz').read_bytes()).decode().splitlines() if line]:
        data = r['data']
        if r['record_type'] == 'metadata':
            data.update(experiment=experiment, benchmark_id=benchmark)
        else:
            data['benchmark'] = benchmark
            if category:
                data['category'] = category
            if rename_ids:
                data['task_id'] = 't' + hashlib.sha256(data['task_id'].encode()).hexdigest()[:6]
        records.append(r)
    rel = Path('docs/results') / experiment / Path(spec['report_path']).name
    (target / 'bundle' / rel).parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(dest), str(target / 'bundle' / rel))
    shutil.rmtree(target / 'bundle/docs/results/legal-benchmark')
    dest = target / 'bundle' / rel
    (dest / 'raw/measurements.jsonl.gz').write_bytes(gzip.compress(('\n'.join(json.dumps(r) for r in records) + '\n').encode(), mtime=0))
    resolved = read_json(dest / 'resolved-config.json')
    resolved['experiment']['experiment_id'] = experiment
    resolved['input_hashes'] = []
    for job in resolved['jobs']:
        job.update(experiment_id=experiment, mode=mode, input_files=[])
    write_json(dest / 'resolved-config.json', resolved)
    summary = [{**row, 'benchmark': benchmark} for row in read_json(dest / 'summary.json')]
    write_json(dest / 'summary.json', summary)
    write_json(dest / 'benchmark-summary.json', summary)
    manifest = read_json(dest / 'manifest.json')
    for key in ('report_fingerprint', 'projection', 'canonical_bytes'):
        manifest.pop(key)
    manifest['experiment_id'] = experiment
    manifest['files'] = {p.relative_to(target / 'bundle').as_posix(): sha256_file(p) for p in sorted(dest.rglob('*')) if p.is_file() and p.name != 'manifest.json'}
    manifest['report_fingerprint'] = digest(manifest)
    write_json(dest / 'manifest.json', manifest)
    spec.update(report_path=rel.as_posix(), chart_path=(Path('diagrams/results') / experiment / rel.name).as_posix(), experiment_id=experiment,
                report_fingerprint=manifest['report_fingerprint'])
    write_json(target / 'publication.json', spec)
    validate_bundle(target)
    return target


def strip_structure(report, files=(), manifest_keys=(), row_keys=()):
    """Remove legal files, manifest keys or row keys from a relabelled bundle and recompute its hashes."""
    dest, spec = bundle_dir(report)
    for name in files:
        (dest / name).unlink()
    records = [json.loads(line) for line in gzip.decompress((dest / 'raw/measurements.jsonl.gz').read_bytes()).decode().splitlines() if line]
    for r in records:
        for key in row_keys:
            r['data'].pop(key, None)
    (dest / 'raw/measurements.jsonl.gz').write_bytes(gzip.compress(('\n'.join(json.dumps(r) for r in records) + '\n').encode(), mtime=0))
    manifest = read_json(dest / 'manifest.json')
    for key in ('report_fingerprint', *manifest_keys):
        manifest.pop(key, None)
    manifest['files'] = {p.relative_to(report / 'bundle').as_posix(): sha256_file(p) for p in sorted(dest.rglob('*')) if p.is_file() and p.name != 'manifest.json'}
    manifest['report_fingerprint'] = digest(manifest)
    write_json(dest / 'manifest.json', manifest)
    write_json(report / 'publication.json', {**spec, 'report_fingerprint': manifest['report_fingerprint']})
    return report


class RelabelTests(CohortCase):
    """Fix 1 (C1): a hand-relabelled legal bundle is refused, inside and outside its campaign layout."""

    def refused(self, report, pattern='Publication'):
        with self.assertRaisesRegex(ValueError, pattern):
            publish_report(report, ROOT, dry_run=True)

    def test_relabelled_approved_smoke_is_refused(self):
        report = self.report(self.smoke(LOCK, 'relabel'))
        out = self.path / 'x'
        self.refused(relabel(report, out / 'routing' / 'report'))
        self.refused(relabel(report, out / 'offload' / 'report', experiment='model-offloading', mode='category-smoke'))
        self.refused(relabel(report, out / 'legal-category' / 'report', category='legal', rename_ids=True))
        self.refused(relabel(report, out / 'legal-underscore' / 'report', benchmark='legal_smoke', rename_ids=True))
        self.refused(relabel(report, out / 'fullwidth' / 'report', benchmark='ｌegal-smoke', rename_ids=True))
        # Each structural claim alone: the other legal traces removed from the bundle first.
        bare = relabel(report, out / 'ids' / 'report', category='general')
        self.refused(strip_structure(bare, row_keys=('family_id', 'review_status', 'expected_choice')), 'carries content of legal-benchmark')
        renamed = relabel(report, out / 'family' / 'report', category='general', rename_ids=True)
        self.refused(strip_structure(renamed, row_keys=('review_status', 'expected_choice')), 'carries content of legal-benchmark')

    def test_relabelled_declared_bundles_are_refused(self):
        report = self.report(self.smoke(self.copy('cp'), 'declared'))
        self.refused(relabel(report, self.path / 'x' / 'smoke' / 'report'))
        generation = self.run_mode('generation', 'generation', {'arms': ['no-context', 'lexical-eligible'], 'roles': {'generator': generator('FAKE_ENDPOINT')}})
        relabelled = relabel(self.report(generation), self.path / 'x' / 'generation' / 'report')
        self.refused(relabelled, 'carries content of legal-benchmark')      # legal-summary.json alone is a claim
        self.assertTrue(lr.claims_bundle(relabelled, bundle_dir(relabelled)[0], {}, {}, []))

    def test_relabel_inside_the_campaign_layout_is_refused_by_the_campaign_record(self):
        directory = self.smoke(LOCK, 'inplace')
        report = self.report(directory)
        relabelled = relabel(report, self.path / 'tmp' / 'report', category='general', rename_ids=True)
        strip_structure(relabelled, row_keys=('family_id', 'review_status', 'expected_choice'))
        shutil.rmtree(report)
        shutil.copytree(relabelled, report)
        with self.assertRaisesRegex(ValueError, 'Publication is not available for legal-benchmark|Publication identity mismatch'):
            publish_report(report, ROOT, dry_run=True)

    def test_structural_claims_have_no_false_positive_on_other_experiments(self):
        from tests.test_reporting import ReportingTests
        case = ReportingTests('test_raw_summary_and_deterministic_export')
        case.setUp()
        self.addCleanup(case.tmp.cleanup)
        self.assertTrue(publish_report(case.report, ROOT, dry_run=True)['dry_run'])
        dest, _ = bundle_dir(case.report)
        self.assertFalse(lr.claims_bundle(case.report, dest, read_json(dest / 'manifest.json'), read_json(dest / 'resolved-config.json'),
                                          raw_records(case.report)))
        self.assertFalse(legal.claims_benchmark('original-routing-smoke'))
        self.assertTrue(legal.claims_benchmark('ＬＥＧＡＬ smoke'))
        self.assertTrue(legal.claims_benchmark(' Legal_Smoke'))


class ReceiptTests(CohortCase):
    """Fixes 2, 3, 4 and 10: plan drift and unbound files at report and publication time; lineage of score jobs."""

    def test_plan_edit_after_a_declared_run_is_refused(self):
        lock = self.copy('cp')
        directory = self.smoke(lock, 'declared')
        plan = read_json(directory / 'plan.json')
        job = plan['jobs'][0]
        job['parameters']['suite'] = str(LOCK)
        job['input_files'] = [{**f, 'path': str(LOCK), 'sha256': sha256_file(LOCK)} if Path(f['path']).resolve() == lock.resolve() else f
                             for f in job['input_files']]      # the plan records resolved paths (an 8.3 temp name is expanded)
        write_json(directory / 'plan.json', plan)      # the digest left stale
        attempt = self.attempt(directory)
        meta = read_json(attempt / 'metadata.json')
        write_json(attempt / 'metadata.json', {**meta, 'suite_lock_sha256': sha256_file(LOCK)})
        self.assertEqual(lr.classify(job)['level'], 'approved')
        with self.assertRaisesRegex(lr.ProjectionRejected, '^plan_changed$'):
            build_report(self.experiment_dir(directory))
        with self.assertRaisesRegex(ValueError, '^plan_changed$'):
            lr.verify_publication(self.report(directory), ROOT)
        # A forger who also recomputes the digest: the exact export compares the metadata with the lock it names.
        plan['plan_sha256'] = config_hash({k: v for k, v in plan.items() if k != 'plan_sha256'})
        write_json(directory / 'plan.json', plan)
        with self.assertRaisesRegex(lr.ProjectionRejected, '^metadata$'):
            build_report(self.experiment_dir(directory))
        # The key deleted: a legal job's plan always has it.
        plan.pop('plan_sha256')
        write_json(directory / 'plan.json', plan)
        with self.assertRaisesRegex(lr.ProjectionRejected, '^plan_changed$'):
            build_report(self.experiment_dir(directory))

    def test_every_file_the_projection_reads_is_bound_by_the_receipt(self):
        self.lock, self.suite = LOCK, contracts.load_suite(LOCK)
        directory = self.run_mode('bound', 'generation', {'arms': ['lexical-eligible'], 'roles': {'generator': generator('FAKE_ENDPOINT')}}, lock=LOCK)
        record = next(iter(read_json(directory / 'campaign.json')['jobs'].values()))['attempts'][-1]
        attempt = directory / record['output']
        self.assertEqual(record['file_sha256'], {name: sha256_file(attempt / name) for name in ('local/score-detail.jsonl', 'metadata.json', 'requests.jsonl')})
        self.assertNotIn('suite_lock_sha256', record)      # bound through the digest of metadata.json, which names it
        details = lines(attempt / 'local/score-detail.jsonl')
        for d in details:
            d['criteria'] = {k: False for k in d['criteria']}
        (attempt / 'local/score-detail.jsonl').write_text(''.join(json.dumps(d) + '\n' for d in details), encoding='utf-8', newline='\n')
        with self.assertRaisesRegex(lr.ProjectionRejected, '^receipt_mismatch$'):
            build_report(self.experiment_dir(directory))
        smoke = self.smoke(LOCK, 'smoke')
        attempt = self.attempt(smoke)
        self.assertIn('requests.jsonl', next(iter(read_json(smoke / 'campaign.json')['jobs'].values()))['attempts'][-1]['file_sha256'])
        rows = lines(attempt / 'requests.jsonl')
        for r in rows:
            r['choice'] = 'charge'
        (attempt / 'requests.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in rows), encoding='utf-8', newline='\n')
        with self.assertRaisesRegex(lr.ProjectionRejected, '^receipt_mismatch$'):
            build_report(self.experiment_dir(smoke))
        # Publication refuses a record without the file digests.
        clean = self.smoke(LOCK, 'clean')
        self.authorize(clean)
        report = self.report(clean)
        lr.verify_publication(report, ROOT)
        state = read_json(clean / 'campaign.json')
        next(iter(state['jobs'].values()))['attempts'][-1].pop('file_sha256')
        write_json(clean / 'campaign.json', state)
        with self.assertRaisesRegex(ValueError, '^receipt_mismatch$'):
            lr.verify_publication(report, ROOT)

    def test_a_score_job_publishes_only_over_a_recorded_source(self):
        self.lock, self.suite = LOCK, contracts.load_suite(LOCK)
        gen = {'arms': ['lexical-eligible'], 'roles': {'generator': generator('FAKE_ENDPOINT')}}
        source = self.attempt(self.run_mode('source', 'generation', gen, lock=LOCK))
        loose = self.path / 'loose' / source.name
        shutil.copytree(source, loose)
        scored = self.run_mode('scored', 'score', {'output_manifest': str(loose / 'local/output-manifest.json')}, lock=LOCK)      # local: allowed
        self.assertEqual(self.receipt(scored)['status'], 'generated')
        PublicationTests.authorize_by_hand(self, scored)
        with self.assertRaisesRegex(ValueError, '^receipt_mismatch$'):
            lr.verify_publication(self.report(scored), ROOT)
        recorded = self.run_mode('recorded', 'score', {'output_manifest': str(source / 'local/output-manifest.json')}, lock=LOCK)
        self.authorize(recorded)
        lr.verify_publication(self.report(recorded), ROOT)

    def test_campaigns_written_before_this_package(self):
        self.lock, self.suite = LOCK, contracts.load_suite(LOCK)
        source = self.run_mode('old', 'generation', {'arms': ['lexical-eligible'], 'roles': {'generator': generator('FAKE_ENDPOINT')}}, lock=LOCK)
        state = read_json(source / 'campaign.json')
        record = next(iter(state['jobs'].values()))['attempts'][-1]
        for key in ('output_manifest_sha256', 'file_sha256'):
            record.pop(key)
        write_json(source / 'campaign.json', state)
        with self.assertRaisesRegex(ValueError, r'^Campaign record has no output-manifest digest \(campaign written before this check\)$'):
            grading.score_records({'output_manifest': str(source / record['output'] / 'local/output-manifest.json')}, self.suite)
        # A smoke campaign directory without any receipt: resume does not crash, and the local report is produced.
        smoke = self.smoke(LOCK, 'old-smoke', reporting={'on_experiment_end': False})
        state = read_json(smoke / 'campaign.json')
        for record in (a for j in state['jobs'].values() for a in j['attempts']):
            for key in ('file_sha256', 'suite_lock_sha256', 'output_manifest_sha256'):
                record.pop(key, None)
        state['reports'] = {}
        write_json(smoke / 'campaign.json', state)
        self.assertEqual(self.resume(smoke), 0)
        self.assertEqual(next(iter(finalize_campaign(smoke).values()))['status'], 'generated')
        PublicationTests.authorize_by_hand(self, smoke)
        with self.assertRaisesRegex(ValueError, '^receipt_mismatch$'):      # but it cannot be published: no receipt binds its files
            lr.verify_publication(self.report(smoke), ROOT)


class SourceOfTruthTests(Base):
    """Fix 5 (I4): the approved list is the installed package's; the upstream check reads a private, freshly fetched ref."""

    def test_a_crafted_root_approves_nothing(self):
        lock = self.copy('cp')
        directory = self.smoke(lock, 'declared')
        report = self.report(directory)
        crafted = self.path / 'crafted'
        approved = read_json(ROOT / contracts.APPROVED_SUITES)
        approved['suites'][sha256_file(lock)] = {'benchmark_id': 'legal-original-smoke', 'fixture_export': True}
        (crafted / contracts.APPROVED_SUITES).parent.mkdir(parents=True)
        write_json(crafted / contracts.APPROVED_SUITES, approved)
        PublicationTests.authorize_by_hand(self, directory)
        with self.assertRaisesRegex(ValueError, 'not_approved$'):
            publish_report(report, crafted, dry_run=True)

    def test_a_moved_local_origin_ref_approves_nothing(self):
        directory = self.smoke(LOCK, 'moved')
        report = self.report(directory)
        self.authorize(directory)
        upstream = read_json(ROOT / contracts.APPROVED_SUITES)
        upstream['suites'].pop(sha256_file(LOCK))      # the remote base branch does not approve the smoke suite
        repo, bare = self.repository(approved=(json.dumps(upstream, indent=2) + '\n').encode())
        write_json(repo / contracts.APPROVED_SUITES, read_json(ROOT / contracts.APPROVED_SUITES))
        g = lambda *a: subprocess.run(['git', '-C', str(repo), *a], check=True, capture_output=True, text=True).stdout.strip()  # noqa: E731
        g('add', '-A')
        g('-c', 'user.name=x', '-c', 'user.email=x@example.com', 'commit', '-m', 'approve locally')
        g('update-ref', 'refs/remotes/origin/main', 'HEAD')
        g('config', '--unset-all', 'remote.origin.fetch')
        api = RecordingGitHub()
        with self.assertRaisesRegex(ValueError, 'not_approved_upstream'):
            self.publish(report, repo, api)
        self.assertEqual(api.created, 0)

    def test_a_results_branch_that_changes_the_approved_list_is_refused(self):
        directory = self.smoke(LOCK, 'changes')
        report = self.report(directory)
        self.authorize(directory)
        repo, bare = self.repository()
        extra = read_json(ROOT / contracts.APPROVED_SUITES)
        extra['suites']['f' * 64] = {'benchmark_id': 'legal-original-smoke', 'fixture_export': True}
        write_json(repo / contracts.APPROVED_SUITES, extra)
        g = lambda *a: subprocess.run(['git', '-C', str(repo), *a], check=True, capture_output=True, text=True).stdout.strip()  # noqa: E731
        g('add', '-A')
        g('-c', 'user.name=x', '-c', 'user.email=x@example.com', 'commit', '-m', 'widen the list')
        g('update-ref', 'refs/remotes/origin/main', 'HEAD')      # the worktree starts from this local ref
        g('config', '--unset-all', 'remote.origin.fetch')
        api = RecordingGitHub()
        with self.assertRaisesRegex(ValueError, 'Publication branch changes a protected file'):
            self.publish(report, repo, api)
        self.assertEqual(api.created, 0)


class ExportContentTests(Base):
    """Fix 6 (I5): an export is recognised task by task, whatever its order, count, ids, categories or markers."""
    routing_bundle = ContentTests.routing_bundle

    def test_transformed_routing_exports_are_refused(self):
        from llm_eval.experiments.legal_benchmark import routing
        exported = routing.route_tasks(contracts.load_suite(LOCK))
        tasks = exported['tasks']
        variants = {
            'reordered': list(reversed(tasks)),
            'one dropped': tasks[1:],
            'one non-legal task added': tasks + [{'id': 'extra', 'category': 'general', 'messages': [{'role': 'user', 'content': 'hello'}]}],
            'category renamed, ids renamed': [{**t, 'id': 'q' + str(i), 'category': 'law'} for i, t in enumerate(tasks)],
            'markers stripped': [{**t, 'messages': [{**m, 'content': m['content'].replace('QUESTION ', 'Q: ').replace('OPERATIVE DATE ', 'DATE: ')}
                                                    for m in t['messages']]} for t in tasks][:3] + tasks[3:],
        }
        for i, (name, value) in enumerate(variants.items()):
            with self.subTest(name):
                path = self.path / f'v{i}-suite.json'
                write_json(path, {**exported, 'benchmark': 'routing-fixture', 'tasks': value})
                with self.assertRaisesRegex(ValueError, 'carries content of legal-benchmark'):
                    publish_report(self.routing_bundle(str(path), name=f'v{i}'), ROOT, dry_run=True)

    def test_transformed_workload_exports_and_replays_are_legal_files(self):
        from llm_eval.experiments.legal_benchmark import profiles, routing
        workload = profiles.workload(LOCK)
        markers = lr._markers()
        for name, tasks in (('reordered', list(reversed(workload['tasks']))), ('one task', workload['tasks'][:1]),
                            ('ids renamed', [{**t, 'id': 'w' + str(i)} for i, t in enumerate(workload['tasks'])]),
                            ('markers stripped, ids kept', [{**t, 'messages': [{**m, 'content': m['content'].replace('<<<BEGIN ', '[[ ')} for m in t['messages']]}
                                                            for t in workload['tasks']])):
            with self.subTest(name):
                path = self.path / (name.replace(' ', '-') + '.json')
                write_json(path, {**workload, 'benchmark': 'category-smoke', 'tasks': tasks})
                self.assertTrue(lr._legal_file(path, markers))
        export = self.path / 'routing-export.json'
        routing.export_suite(LOCK, export)
        from llm_eval.runner import load_suite as load_task_suite
        replay = self.path / 'replay.json'
        write_json(replay, {'suite_sha256': digest(load_task_suite(export)), 'candidate_fingerprints': {},
                            'rows': [{'task_id': 'q1', 'candidate': 'no-context', 'quality': 1.0, 'latency_s': 1.0, 'cost_usd': 0}]})
        self.assertTrue(lr._legal_file(replay, markers))

    def test_a_model_offloading_bundle_from_a_renamed_workload_is_refused(self):
        from llm_eval.experiments.legal_benchmark import profiles
        workload = profiles.workload(LOCK)
        write_json(self.path / 'workload.json', {**workload, 'benchmark': 'category-smoke', 'tasks': list(reversed(workload['tasks']))})
        config = read_json(ROOT / 'configs/runs/ollama.example.json')
        config['suite'] = str(self.path / 'workload.json')
        write_json(self.path / 'offload-config.json', config)
        write_json(self.path / 'offload-case.json', {'id': 'offload', 'parameters': {'config': 'offload-config.json'}})
        write_json(self.path / 'offload-campaign.json', {'schema_version': 2, 'id': 'offload', 'inventory': 'inventory.json', 'phases': [
            {'id': 'offload', 'experiments': [{'id': 'model-offloading', 'version': 1, 'cases': ['offload-case.json'], 'hardware_configs': ['native']}]}]})
        plan = compile_campaign(self.path / 'offload-campaign.json', ROOT)

        def rpc(target, payload, root, timeout=60):      # a fake offload worker: generic rows, no legal label in them
            if payload['action'] != 'run':
                return {'ok': True}
            out = Path(payload['output'])
            (out / 'requests.jsonl').write_text(json.dumps({'task_id': 'x1', 'category': 'general', 'status': 'ok', 'warmup': False,
                                                            'elapsed_s': 1.0}) + '\n', encoding='utf-8')
            write_json(out / 'metadata.json', {'config': {'model': 'fixture'}})
            return {'status': 'succeeded'}
        directory, _ = self.run_plan(plan, 'offload', rpc=rpc)
        with self.assertRaisesRegex(ValueError, 'carries content of legal-benchmark'):
            publish_report(directory / self.receipt(directory)['report'], ROOT, dry_run=True)


class CohortSizeTests(CohortCase):
    """Fix 7 (I7): a projection that is not an exact fixture export suppresses metrics of fewer than five matters."""
    SIZES = {1: ('f1-ledger-a',), 2: ('f1-ledger-a', 'f8-manifest-a'), 4: ('f1-ledger-a', 'f1-ledger-b', 'f2-berth-a', 'f8-manifest-a'),
             5: ('f1-ledger-a', 'f1-ledger-b', 'f2-berth-a', 'f3-market-a', 'f8-manifest-a')}

    def test_small_cohorts_are_suppressed(self):
        for size, matters in self.SIZES.items():
            with self.subTest(matters=size):
                lock = subset_suite(self.path / f'subset-{size}', matters)
                report = self.report(self.smoke(lock, f'size-{size}'))
                dest, _ = bundle_dir(report)
                (entry,) = read_json(dest / 'legal-summary.json')['cohorts']
                metrics = entry['metrics']
                meta = next(r['data'] for r in raw_records(report) if r['record_type'] == 'metadata')
                self.assertIsNone(meta['all_pass'])
                if size < lr.MIN_COHORT:      # fixlist-F2 B2: the whole cohort, in one shape with no number in it
                    self.assertTrue(entry['suppressed'])
                    self.assertTrue(all(m == lr.SMALL_METRIC for m in metrics.values()))
                else:
                    self.assertFalse(entry['suppressed'])
                    self.assertEqual(metrics['all_pass']['n'], 5)
                    self.assertIsNotNone(metrics['all_pass']['value'])
                    self.assertNotIn('suppressed', metrics['all_pass'])
                    gold = {g['matter_id']: g['recommendation'] for g in contracts.load_suite(lock)['rubric']['matters']}
                    for g in contracts.RECOMMENDATIONS:      # a cell is suppressed when its gold class has fewer than five matters
                        cell = metrics[f'confusion.{g}.{g}']
                        self.assertEqual(cell['value'] is None, sum(v == g for v in gold.values()) < lr.MIN_COHORT, g)

    def test_small_paired_differences_are_suppressed_and_exact_exports_are_exempt(self):
        directory = self.run_mode('paired', 'generation', {'arms': ['no-context', 'lexical-eligible'], 'roles': {'generator': generator('FAKE_ENDPOINT')}})
        paired = read_json(bundle_dir(self.report(directory))[0] / 'legal-summary.json')['paired']
        self.assertTrue(paired)
        self.assertTrue(all({k: p[k] for k in lr.SMALL_PAIRED} == lr.SMALL_PAIRED and 'suppressed' not in p for p in paired))
        lock = subset_suite(self.path / 'five', self.SIZES[5])
        self.suite = contracts.load_suite(lock)      # the scripted generator answers for these matters
        directory = self.run_mode('paired-5', 'generation', {'arms': ['no-context', 'lexical-eligible'], 'roles': {'generator': generator('FAKE_ENDPOINT')}},
                                  lock=lock)
        paired = read_json(bundle_dir(self.report(directory))[0] / 'legal-summary.json')['paired']
        self.assertTrue(all(p['mean'] is not None and 'suppressed' not in p for p in paired))
        report = self.report(self.smoke(LOCK, 'exact'))
        (entry,) = read_json(bundle_dir(report)[0] / 'legal-summary.json')['cohorts']
        self.assertFalse(any('suppressed' in m for m in entry['metrics'].values()))      # the answer key is public by design


class SchemaTests(Base):
    """Fixes 8 (allowlist survivors), 11, 13 and 14."""

    def test_leaf_types_are_strict(self):
        v = lr.validate_projection
        for value, schema in ((float('nan'), lr.NUMBER), (float('inf'), lr.NUMBER), (10 ** 16, lr.NUMBER), (-1, lr.COUNT), (10 ** 300, lr.COUNT),
                              (True, lr.COUNT), (1, lr.BOOL), ({'b': 1}, lr._object({'a': lr.COUNT})),
                              ({'Generator': lr.ROLE}, ('map', lr._enum(*lr.workflow.ROLE_SET), lr.COUNT)),
                              ({'arm\n': 1}, ('map', lr.ARM, lr.COUNT))):
            with self.subTest(value=repr(value)[:40]), self.assertRaises(lr.ProjectionRejected):
                v(value, schema)
        with self.assertRaisesRegex(lr.ProjectionRejected, r'^request\.status$'):
            row = {'task_id': 'a', 'family_id': 'a', 'category': 'a', 'benchmark': 'a', 'arm': 'smoke', 'repetition': 0, 'warmup': False,
                   'synthetic': True, 'execution_kind': 'fixture', 'data_class': 'public-synthetic'}
            v(row, lr.REQUEST, 'request')

    def edit_rows(self, attempt, change, name='requests.jsonl'):
        rows = lines(attempt / name)
        change(rows[0])
        (attempt / name).write_text(''.join(json.dumps(r) + '\n' for r in rows), encoding='utf-8', newline='\n')

    def test_each_projection_check_fires(self):
        directory = self.smoke(LOCK, 'checks', reporting={'on_experiment_end': False})
        attempt = self.attempt(directory)
        experiment = self.experiment_dir(directory)
        rows0, meta0 = (attempt / 'requests.jsonl').read_bytes(), (attempt / 'metadata.json').read_bytes()
        cases = [('row data class', lambda: self.edit_rows(attempt, lambda r: r.update(data_class='public-benchmark')), '^request$'),
                 ('row task id outside the suite', lambda: self.edit_rows(attempt, lambda r: r.update(task_id='f9-unknown-a')), r'^request\.task_id$'),
                 ('row category not a scenario', lambda: self.edit_rows(attempt, lambda r: r.update(category='all')), r'^request\.category$'),
                 ('metadata suite digest', lambda: write_json(attempt / 'metadata.json', {**json.loads(meta0), 'suite_lock_sha256': '0' * 64}), '^metadata$'),
                 ('metadata revision of the exact export', lambda: write_json(attempt / 'metadata.json', {**json.loads(meta0), 'suite_revision': 'other'}),
                  '^metadata$'),
                 ('repetition out of range', lambda: self.edit_rows(attempt, lambda r: r.update(repetition=10 ** 300)), r'^request\.repetition$'),
                 ('duplicate key in a row', lambda: (attempt / 'requests.jsonl').write_bytes(rows0.replace(b'{', b'{"category": "x", ', 1)), '^request$'),
                 ('duplicate key in metadata', lambda: (attempt / 'metadata.json').write_bytes(meta0.replace(b'{', b'{"mode": "smoke", ', 1)), '^metadata$'),
                 ('a path in the attempt output', None, '^attempt_path$'),
                 ('prompt digest in a row', lambda: self.edit_rows(attempt, lambda r: r.update(prompt_sha256='0' * 64)), r'^request\.<unknown key>$')]
        for name, change, pattern in cases:
            with self.subTest(name):
                if change is None:
                    state = read_json(directory / 'campaign.json')
                    original = json.dumps(state)
                    next(iter(state['jobs'].values()))['attempts'][-1]['output'] = 'experiments/../../outside'
                    write_json(directory / 'campaign.json', state)
                else:
                    change()
                try:
                    with self.assertRaisesRegex(lr.ProjectionRejected, pattern):
                        build_report(experiment)
                finally:
                    (attempt / 'requests.jsonl').write_bytes(rows0)
                    (attempt / 'metadata.json').write_bytes(meta0)
                    if change is None:
                        write_json(directory / 'campaign.json', json.loads(original))
        report = build_report(experiment)
        rows = [r['data'] for r in raw_records(report) if r['record_type'] == 'request']
        self.assertFalse(any({'decision_correct', 'prompt_sha256', 'evidence_sha256'} & set(r) for r in rows))
        self.assertTrue(all(r['decision_accuracy'] == 1 for r in read_json(bundle_dir(report)[0] / 'summary.json')))      # computed inside

    def test_reduced_projection_covers_the_whole_run(self):
        copy_lock = self.copy('cp')
        write_json(self.path / 'a.json', {'id': 'approved', 'parameters': {'suite': str(LOCK), 'synthetic': True}})
        write_json(self.path / 'b.json', {'id': 'declared', 'parameters': {'suite': str(copy_lock), 'synthetic': True}})
        write_json(self.path / 'two.json', {'schema_version': 2, 'id': 'two', 'inventory': 'inventory.json', 'phases': [
            {'id': 'legal', 'experiments': [{'id': 'legal-benchmark', 'version': 1, 'mode': 'smoke', 'cases': ['a.json', 'b.json'],
                                             'hardware_configs': ['native']}]}]})
        directory, code = self.run_plan(compile_campaign(self.path / 'two.json', ROOT), 'two')
        self.assertEqual(code, 0)
        rows = [r['data'] for r in raw_records(self.report(directory)) if r['record_type'] == 'request']
        self.assertEqual(len(rows), 32)
        self.assertTrue(all(len(r['task_id']) == 16 and 'expected_choice' not in r for r in rows))      # the approved job too
        summary = read_json(bundle_dir(self.report(directory))[0] / 'summary.json')
        self.assertTrue(all(r['benchmark'] in ('legal-smoke', 'unspecified') for r in summary))

    def test_error_types_are_an_enumeration(self):
        self.assertEqual(lr.public_error_type('Exfil' + CANARY + 'A' * 40), 'error')
        self.assertEqual(lr.public_error_type('TimeoutError'), 'TimeoutError')
        self.assertEqual(lr.public_error_type(None), None)

    def test_the_mode_mismatch_message_echoes_no_bundle_text(self):
        from tests.test_reporting import ReportingTests
        case = ReportingTests('test_raw_summary_and_deterministic_export')
        case.setUp()
        self.addCleanup(case.tmp.cleanup)
        dest, spec = bundle_dir(case.report)
        resolved = read_json(dest / 'resolved-config.json')
        for name, mode in ((CANARY, 'mode'), ('smoke', 'smoke')):      # text from the bundle versus a mode another experiment declares
            with self.subTest(mode=name):
                for job in resolved['jobs']:
                    job['mode'] = name
                write_json(dest / 'resolved-config.json', resolved)
                PublicationTests.remanifest(case.report)
                with self.assertRaisesRegex(ValueError, f'Publication identity mismatch: mode {mode} is not a mode of llm-routing') as raised:
                    publish_report(case.report, ROOT, dry_run=True)
                self.assertNotIn(CANARY, str(raised.exception))


class GateDetailTests(Base):
    """Fix 8 (gate survivors), 9 and 17."""

    def test_an_approved_entry_must_name_the_lock_benchmark(self):
        (job,) = self.plan('bench', parameters={'suite': str(LOCK), 'synthetic': True})['jobs']
        root = self.path / 'root'
        approved = read_json(ROOT / contracts.APPROVED_SUITES)
        approved['suites'][sha256_file(LOCK)]['benchmark_id'] = 'legal-other'
        (root / contracts.APPROVED_SUITES).parent.mkdir(parents=True)
        write_json(root / contracts.APPROVED_SUITES, approved)
        self.assertEqual(lr.classify(job, root)['level'], 'declared')

    def test_a_blocked_dataset_gate_is_refused(self):
        from tests.test_legal_ingest import AdapterTests
        out = AdapterTests.imported(self)
        lock = out / 'suite.lock.json'
        job = {'mode': 'retrieval', 'parameters': {'suite': str(lock), 'synthetic': True, 'arms': ['lexical']},
               'input_files': [{'path': str(lock), 'sha256': sha256_file(lock)}]}
        found = lr.classify(job)
        self.assertEqual((found['level'], found['verified'], found['reason'], found['data_class']),
                         ('refused', True, 'dataset_gate_blocked', 'public-benchmark'))

    def test_the_worker_gate_has_no_depth_limit(self):
        (job,) = self.plan('deep', parameters={'suite': str(self.copy()), 'synthetic': True})['jobs']
        attempt = self.path / 'worker' / ('d' * 32)
        for depth in (6, 9):
            with self.subTest(depth=depth):
                deep = attempt.joinpath('local', *['x'] * (depth - 1))
                deep.mkdir(parents=True, exist_ok=True)
                atomic_json(attempt / 'job.json', job)
                (deep / 'f.jsonl').write_text(CANARY, encoding='utf-8')
                relative = (deep / 'f.jsonl').relative_to(attempt).as_posix()
                for call in ({'action': 'file-chunk', 'output': str(attempt), 'path': relative, 'offset': 0},
                             {'action': 'file-chunk', 'output': str(deep), 'path': 'f.jsonl', 'offset': 0}, {'action': 'collect', 'output': str(deep)}):
                    with self.assertRaisesRegex(ValueError, 'Collection refused by data policy'):
                        worker.handle(call)

    def test_an_unreadable_job_file_refuses_the_transfer(self):
        plain = self.path / 'routing-attempt'
        plain.mkdir()
        (plain / 'x.bin').write_bytes(b'x')
        for text in ('[1, 2]', '{"job_id": "x"}', '{"experiment_id": "legal-benchmark", '):      # not a job object with an experiment
            with self.subTest(job=text):
                (plain / 'job.json').write_text(text, encoding='utf-8')
                with self.assertRaisesRegex(ValueError, 'Collection refused by data policy: .*job.json'):
                    worker.handle({'action': 'collect', 'output': str(plain)})
        write_json(plain / 'job.json', {'job_id': 'r', 'experiment_id': 'llm-routing'})      # a valid generic job collects as before
        self.assertEqual(sorted(f['path'] for f in worker.handle({'action': 'collect', 'output': str(plain)})['files']), ['job.json', 'x.bin'])

    def test_markers_fail_closed_and_codes_are_closed(self):
        with patch.object(contracts, 'approved_suites', side_effect=OSError('broken')):
            lr._MARKERS.clear()
            with self.assertRaisesRegex(ValueError, '^Approved legal suites cannot be read$'):
                lr.claims_bundle(self.path / 'report', self.path, {}, {}, [])
        lr._MARKERS.clear()
        self.assertEqual(set(lr.PUBLICATION), {'provenance_missing', 'legacy_report', 'plan_changed', 'unverified', 'not_approved',
                                               'not_approved_upstream', 'receipt_mismatch', 'bundle_mismatch', 'not_authorized'})
        self.assertNotIn('publish', lr.data_policy({}))

    def test_the_committed_blob_is_checked_after_the_commit(self):
        directory = self.smoke(LOCK, 'race')
        report = self.report(directory)
        self.authorize(directory)
        repo, bare = self.repository(attributes=b'* -text\n')
        dest, spec = bundle_dir(report)

        def racing(root, *args, **kwargs):      # a writer that changes a staged file between the staged check and the commit
            if args == ('remote', 'get-url', 'origin'):
                return 'https://github.com/asanderson/llm-eval.git'
            if args[:1] == ('-c',) and 'commit' in args:
                path = Path(root) / spec['report_path'] / 'README.md'
                path.write_bytes(path.read_bytes() + b'\r\n')
                real_git(root, 'add', '--', spec['report_path'], env=kwargs.get('env'))
            return real_git(root, *args, **kwargs)
        with patch('llm_eval.reporting.publish.git', side_effect=racing), patch.dict(os.environ, {'GH_TOKEN': '', 'GITHUB_TOKEN': ''}), \
                self.assertRaisesRegex(ValueError, 'Committed bytes differ from the manifest: .*README.md'):
            publish_report(report, repo, api=RecordingGitHub())
        self.assertEqual(subprocess.run(['git', '-C', str(bare), 'for-each-ref', '--format=%(refname:short)', 'refs/heads'], capture_output=True,
                                        text=True).stdout.split(), ['main'])


# 9. Second review round (fixlist-F2) ----------------------------------------------------------------------------------

def scrub(report):
    """Rewrite every remaining legal trace of a relabelled bundle by hand: README replaced, job ids, benchmark and experiment
    names replaced in every text file and in the raw archive, the legal summary and the structural keys removed, task ids
    renamed. The result is what a person who rewrites the whole bundle produces."""
    dest, spec = bundle_dir(report)
    names = ((b'legal-original-smoke', b'smoke'), (b'legal-benchmark', b'llm-routing'), (b'legal-smoke', b'smoke'))

    def clean(data):
        for old, new in names:
            data = data.replace(old, new)
        return data
    spec = json.loads(clean(json.dumps(spec).encode()).decode())      # the run id in the report directory and publication id
    if report / 'bundle' / spec['report_path'] != dest:
        shutil.move(str(dest), str(report / 'bundle' / spec['report_path']))
        dest = report / 'bundle' / spec['report_path']
    (dest / 'legal-summary.json').unlink(missing_ok=True)
    (dest / 'README.md').write_text('# report\n', encoding='utf-8')
    records = []
    for line in gzip.decompress((dest / 'raw/measurements.jsonl.gz').read_bytes()).decode().splitlines():
        if not line:
            continue
        r = json.loads(clean(line.encode()).decode())
        for key in ('family_id', 'review_status', 'suite_lock_sha256', 'expected_choice'):
            r['data'].pop(key, None)
        if r['record_type'] == 'request':
            r['data']['task_id'] = 't' + hashlib.sha256(r['data']['task_id'].encode()).hexdigest()[:6]
            r['data']['category'] = 'general'
        records.append(r)
    (dest / 'raw/measurements.jsonl.gz').write_bytes(gzip.compress(('\n'.join(json.dumps(r) for r in records) + '\n').encode(), mtime=0))
    for name in ('summary.json', 'summary.csv', 'benchmark-summary.json', 'resolved-config.json'):
        if (dest / name).exists():
            (dest / name).write_bytes(clean((dest / name).read_bytes()))
    manifest = json.loads(clean((dest / 'manifest.json').read_bytes()).decode())
    for key in ('report_fingerprint', 'projection', 'canonical_bytes', 'execution_kinds', 'data_class', 'suite_lock_sha256', 'cohorts'):
        manifest.pop(key, None)
    manifest['files'] = {p.relative_to(report / 'bundle').as_posix(): sha256_file(p) for p in sorted(dest.rglob('*')) if p.is_file() and p.name != 'manifest.json'}
    manifest['report_fingerprint'] = digest(manifest)
    write_json(dest / 'manifest.json', manifest)
    write_json(report / 'publication.json', {**spec, 'report_fingerprint': manifest['report_fingerprint']})
    validate_bundle(report)
    return report


def generic_bundle(test):
    """The routing fixture report of tests/test_reporting.py: a bundle of another experiment that publishes."""
    from tests.test_reporting import ReportingTests
    case = ReportingTests('test_raw_summary_and_deterministic_export')
    case.setUp()
    test.addCleanup(case.tmp.cleanup)
    return case.report


def edit_generic(report, rows=None, manifest=None):
    """Change the rows or the manifest of a generic bundle and recompute its hashes."""
    dest, spec = bundle_dir(report)
    if rows:
        records = raw_records(report)
        for r in records:
            if r['record_type'] == 'request':
                rows(r['data'])
        (dest / 'raw/measurements.jsonl.gz').write_bytes(gzip.compress(('\n'.join(json.dumps(r) for r in records) + '\n').encode(), mtime=0))
    data = read_json(dest / 'manifest.json')
    if manifest:
        manifest(data)
    data.pop('report_fingerprint')
    data['files'] = {name: hashlib.sha256((report / 'bundle' / name).read_bytes()).hexdigest() for name in data['files']}
    data['report_fingerprint'] = digest(data)
    write_json(dest / 'manifest.json', data)
    write_json(report / 'publication.json', {**spec, 'report_fingerprint': data['report_fingerprint']})
    return report


def generic_report(directory, experiment, mode, rows, metadata=None):
    """A report of `model-offloading` or `llm-routing` built as tests/test_reporting.py builds one: one finished attempt with `rows`."""
    job = {'job_id': 'job', 'experiment_id': experiment, 'experiment_run_id': 'run', 'case_id': 'fixed', 'mode': mode,
           'hardware_config_id': 'fixture', 'hardware': {'os_id': 'fixture'}, 'parameters': {'synthetic': True, 'router': {'kind': 'fixed'}},
           'status': 'planned', 'reason': None}
    plan = {'campaign_id': 'fixture', 'root': str(ROOT), 'code_revision': revision(ROOT), 'inputs': {}, 'jobs': [job],
            'experiments': [{'experiment_id': experiment, 'experiment_run_id': 'run', 'job_ids': ['job']}], 'reporting': {'on_experiment_end': True}}
    campaign = initialize(plan, directory)
    state = read_json(campaign / 'campaign.json')
    out = campaign / 'experiments/run/jobs/job/attempt'
    out.mkdir(parents=True)
    (out / 'requests.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in rows), encoding='utf-8')
    write_json(out / 'job.json', job)
    write_json(out / 'metadata.json', metadata or {'config': {'model': 'fixture'}})
    state['jobs']['job'] = {'status': 'succeeded', 'attempts': [{'attempt_id': 'attempt', 'output': 'experiments/run/jobs/job/attempt',
                                                                 'status': 'succeeded'}]}
    write_json(campaign / 'campaign.json', state)
    return build_report(campaign / 'experiments/run')


class PublicLegalBenchmarkTests(unittest.TestCase):
    """Owner decision of 2026-11-13: a generic bundle that measures a public legal benchmark (LegalBench, say) publishes; only this
    plugin's own benchmark names and legal content refuse it."""
    GENERIC = (('model-offloading', 'category-smoke'), ('llm-routing', 'decision'))

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name)

    def report(self, name, experiment, mode, metadata=None, **row):
        rows = [{'task_id': 't1', 'category': 'math', 'benchmark': 'fixture', 'status': 'ok', 'warmup': False, 'synthetic': True,
                 'elapsed_s': 2, **row}]
        return generic_report(self.path / name, experiment, mode, rows, metadata)

    def test_public_legal_benchmarks_publish_under_the_generic_experiments(self):
        cases = [*({'benchmark': b} for b in ('LegalBench', 'legalbench', 'legal-bench', 'legalese-quiz')),
                 *({'category': c} for c in ('legal', 'Legal Reasoning')),
                 {'benchmark': 'LegalBench', 'category': 'legal'}]
        for experiment, mode in self.GENERIC:
            for i, row in enumerate(cases):
                with self.subTest(experiment=experiment, **row):
                    report = self.report(f'{experiment}-{i}', experiment, mode, **row)
                    self.assertTrue(publish_report(report, ROOT, dry_run=True)['dry_run'])

    def test_this_plugins_benchmark_names_and_legal_content_are_still_refused(self):
        name = '^Publication identity mismatch: the bundle carries a legal benchmark name$'
        cases = [({'benchmark': 'LEGAL_smoke'}, None, name), ({'benchmark': 'legal-original-smoke'}, None, name),
                 ({'benchmark': 'legal_routing', 'category': 'legal'}, None, name), ({'benchmark': 'ｌｅｇａｌ-shaped'}, None, name),
                 ({'task_id': 'F1 Ledger A', 'benchmark': 'LegalBench'}, None, r'carries content of legal-benchmark \(task id\)$'),
                 ({'family_id': 'fam', 'category': 'legal'}, None, r'carries content of legal-benchmark \(row key\)$'),
                 ({}, {'config': {'model': 'fixture'}, 'suite_lock_sha256': 'x'}, r'carries content of legal-benchmark \(row key\)$')]
        for experiment, mode in self.GENERIC:
            for i, (row, metadata, message) in enumerate(cases):
                with self.subTest(experiment=experiment, row=row, metadata=metadata):
                    report = self.report(f'{experiment}-{i}', experiment, mode, metadata, **row)
                    with self.assertRaisesRegex(ValueError, message):
                        publish_report(report, ROOT, dry_run=True)
        report = edit_generic(self.report('manifest', 'model-offloading', 'category-smoke'), manifest=lambda m: m.update(cohorts=1))
        with self.assertRaisesRegex(ValueError, r'carries content of legal-benchmark \(manifest key\)$'):
            publish_report(report, ROOT, dry_run=True)

    def test_only_the_names_this_plugin_writes_are_claimed(self):
        approved = {e['benchmark_id'] for e in contracts.approved_suites().values()}
        self.assertEqual(approved, {'legal-original-smoke', 'legal-original-packets'})
        for name in ('legal-smoke', 'LEGAL_smoke', ' legal smoke', 'ｌｅｇａｌ－ｓｍｏｋｅ', 'legal_routing', 'legalrouting', 'legal-shaped',
                     *approved):
            with self.subTest(claimed=name):
                self.assertTrue(legal.claims_benchmark(name))
                self.assertEqual(lr.claims_bundle(self.path / 'x' / 'report', self.path, {}, {},
                                                  [{'record_type': 'request', 'data': {'benchmark': name}}]), 'benchmark name')
                self.assertEqual(lr.claims_bundle(self.path / 'x' / 'report', self.path, {}, {},
                                                  [{'record_type': 'metadata', 'data': {'benchmark_id': name}}]), 'benchmark name')
        for name in ('LegalBench', 'legalbench', 'legal-bench', 'legalese-quiz', 'legal', 'legal-benchmark-x', 'routing-fixture', None):
            with self.subTest(not_claimed=name):
                self.assertFalse(legal.claims_benchmark(name))
                self.assertIsNone(lr.claims_bundle(self.path / 'x' / 'report', self.path, {}, {},
                                                   [{'record_type': 'request', 'data': {'benchmark': name, 'benchmark_id': name}}]))
        for category in ('legal', 'Legal', 'LEGAL', 'Legal Reasoning'):      # a category is no mark by itself
            with self.subTest(category=category):
                self.assertIsNone(lr.claims_bundle(self.path / 'x' / 'report', self.path, {}, {},
                                                   [{'record_type': 'request', 'data': {'category': category}}]))

    def test_the_claim_fails_closed_when_the_approved_list_cannot_be_read(self):
        with patch.object(contracts, 'approved_suites', side_effect=OSError('unreadable')):
            for name in ('LegalBench', 'legal-smoke'):
                with self.subTest(name=name), self.assertRaisesRegex(ValueError, '^Approved legal suites cannot be read$'):
                    legal.claims_benchmark(name)


class SecondRelabelTests(CohortCase):
    """B1 and B3: the cheapest relabels the re-review found are refused; the campaign record is found by walking up."""

    def refused(self, report, pattern='Publication identity mismatch'):
        with self.assertRaisesRegex(ValueError, pattern):
            publish_report(report, ROOT, dry_run=True)

    def test_the_cheapest_relabels_are_refused_by_their_text(self):
        report = self.report(self.smoke(LOCK, 'cheap'))
        relabelled = strip_structure(relabel(report, self.path / 'x' / 'smoke' / 'report', benchmark='smoke', rename_ids=True),
                                     files=('legal-summary.json',), manifest_keys=('execution_kinds', 'data_class', 'suite_lock_sha256', 'cohorts'),
                                     row_keys=('family_id', 'review_status', 'suite_lock_sha256'))
        self.refused(relabelled, r'carries content of legal-benchmark \(text file\)')      # README.md and summary.csv
        generation = self.run_mode('gen', 'generation', {'arms': ['no-context', 'lexical-eligible'], 'roles': {'generator': generator('FAKE_ENDPOINT')}})
        relabelled = strip_structure(relabel(self.report(generation), self.path / 'x' / 'generation' / 'report'), files=('legal-summary.json',),
                                     manifest_keys=('execution_kinds', 'data_class', 'suite_lock_sha256', 'cohorts'), row_keys=('suite_lock_sha256',))
        self.refused(relabelled, r'carries content of legal-benchmark \(text file\)')

    def test_a_scrubbed_bundle_is_refused_anywhere_inside_its_campaign(self):
        directory = self.smoke(LOCK, 'scrub')
        report = self.report(directory)
        scrubbed = scrub(relabel(report, self.path / 'tmp' / 'report', benchmark='smoke', rename_ids=True))
        self.assertTrue(publish_report(scrubbed, ROOT, dry_run=True)['dry_run'])      # outside any campaign: the documented residual
        off = directory / 'experiments' / report.parent.name / 'copy' / 'report'
        shutil.copytree(scrubbed, off)
        self.refused(off, 'the campaign record names legal-benchmark')
        renamed = self.path / 'renamed-campaign'
        shutil.copytree(directory, renamed)
        shutil.rmtree(renamed / 'experiments' / report.parent.name / 'report')
        shutil.copytree(scrubbed, renamed / 'experiments' / report.parent.name / 'report')
        (renamed / 'experiments').rename(renamed / 'Experiments2')
        self.refused(renamed / 'Experiments2' / report.parent.name / 'report', 'the campaign record names legal-benchmark')
        # The plan and the experiment record relabelled too: the attempts' own job.json still name the experiment.
        inplace = directory / 'experiments' / report.parent.name / 'report'
        shutil.rmtree(inplace)
        shutil.copytree(scrubbed, inplace)
        plan = read_json(directory / 'plan.json')
        text = json.dumps(plan).replace('"experiment_id": "legal-benchmark"', '"experiment_id": "llm-routing"')
        write_plan(directory, json.loads(text))
        record = read_json(inplace.parent / 'experiment.json')
        write_json(inplace.parent / 'experiment.json', {**record, 'experiment_id': 'llm-routing'})
        self.refused(inplace, 'the campaign record names legal-benchmark')
        for name in ('job.json', 'metadata.json'):      # each attempt file alone is enough
            with self.subTest(attempt_file=name):
                attempt = self.attempt(directory)
                kept = (attempt / name).read_bytes()
                other = 'metadata.json' if name == 'job.json' else 'job.json'
                stash = (attempt / other).read_bytes()
                (attempt / other).unlink()
                try:
                    self.refused(inplace, 'the campaign record names legal-benchmark')
                finally:
                    (attempt / other).write_bytes(stash)
                self.assertEqual((attempt / name).read_bytes(), kept)

    def test_each_structural_claim_alone_refuses_a_generic_bundle(self):
        cases = [*((f'manifest key {k}', None, (lambda m, k=k: m.update({k: 1})), 'manifest key') for k in
                   ('projection', 'execution_kinds', 'data_class', 'suite_lock_sha256', 'cohorts')),      # canonical_bytes changes the required files
                 *((f'row key {k}', (lambda r, k=k: r.update({k: 'x'})), None, 'row key') for k in
                   ('family_id', 'review_status', 'suite_lock_sha256', 'route_choice', 'route_fallback')),
                 ('task id spelled otherwise', lambda r: r.update(task_id='F1 Ledger A'), None, 'task id')]
        for name, rows, manifest, marker in cases:
            with self.subTest(name):
                report = edit_generic(generic_bundle(self), rows, manifest)
                with self.assertRaisesRegex(ValueError, rf'carries content of legal-benchmark \({marker}\)$'):
                    publish_report(report, ROOT, dry_run=True)
        report = edit_generic(generic_bundle(self), lambda r: r.update(benchmark='LEGAL_original smoke'))
        with self.assertRaisesRegex(ValueError, '^Publication identity mismatch: the bundle carries a legal benchmark name$'):
            publish_report(report, ROOT, dry_run=True)
        # A public legal benchmark, or a row in category legal, is no mark by itself (owner decision 2026-11-13).
        report = edit_generic(generic_bundle(self), lambda r: r.update(benchmark='LegalBench ' + CANARY, category='Legal'))
        self.assertTrue(publish_report(report, ROOT, dry_run=True)['dry_run'])
        self.assertTrue(publish_report(edit_generic(generic_bundle(self)), ROOT, dry_run=True)['dry_run'])      # unchanged: publishes

    def test_the_exact_smoke_export_key_set_is_pinned(self):
        self.assertEqual(lr.SMOKE_EXPORT_KEYS, ('task_id', 'family_id', 'category', 'benchmark', 'arm', 'repetition', 'warmup', 'synthetic',
                                                'execution_kind', 'data_class', 'status', 'elapsed_s', 'parse_status', 'review_status',
                                                'expected_choice', 'choice', 'quality_check_applicable', 'quality_pass', 'criteria_passed',
                                                'criteria_total'))
        rows = [r['data'] for r in raw_records(self.report(self.smoke(LOCK, 'keys'))) if r['record_type'] == 'request']
        self.assertEqual({k for r in rows for k in r}, set(lr.SMOKE_EXPORT_KEYS))


class SmallCohortTests(CohortCase):
    """B2: a reduced cohort of fewer than five matters publishes nothing that depends on its matters' labels or outcomes."""

    def public(self, directory):
        dest, _ = bundle_dir(self.report(directory))
        legal_summary = read_json(dest / 'legal-summary.json')
        for c in legal_summary['cohorts']:      # the cohort identity names the suite, which differs between the two runs
            for key in ('cohort', 'cohort_sha256', 'job_id'):      # the suite and the case name differ between the two runs
                c.pop(key)
        return legal_summary, read_json(dest / 'summary.json')

    def run_one(self, name, matter, mode='generation', replies=None):
        lock = subset_suite(self.path / ('suite-' + name), (matter,))
        self.lock, self.suite, self.replies = lock, contracts.load_suite(lock), replies or {}
        parameters = {'synthetic': True, 'arms': ['lexical', 'lexical-eligible']} if mode == 'retrieval' else \
            {'arms': ['lexical-eligible'], 'roles': {'generator': generator('FAKE_ENDPOINT')}}
        return self.public(self.run_mode(name, mode, parameters, lock=lock))

    def test_one_matter_cohorts_publish_nothing_that_depends_on_the_matter(self):
        gold = {g['matter_id']: g['recommendation'] for g in contracts.load_suite(LOCK)['rubric']['matters']}
        charge = next(m for m, g in sorted(gold.items()) if g == 'charge')
        decline = next(m for m, g in sorted(gold.items()) if g == 'decline')
        for mode in ('generation', 'retrieval'):
            with self.subTest(mode=mode):
                a, b = self.run_one(mode + '-charge', charge, mode), self.run_one(mode + '-decline', decline, mode)
                self.assertEqual(a, b)
                (cohort, *_) = a[0]['cohorts']
                self.assertTrue(cohort['suppressed'])
                self.assertIsNone(cohort['run_status'])
                self.assertTrue(all(m == {'value': None, 'n': None, 'low': None, 'high': None, 'missing': None} for m in cohort['metrics'].values()))
                names = set(lr.ROW_METRICS) | (set(grading.METRICS) if mode == 'generation' else set())
                self.assertEqual(set(cohort['metrics']), names)
                self.assertEqual(a[1], [])      # the generic summary has no row for the cohort either
        good, garbage = self.run_one('good', charge), self.run_one('garbage', charge, replies={charge: 'not a memo'})
        self.assertEqual(good, garbage)

    def test_paired_differences_of_small_cohorts_carry_no_number(self):
        directory = self.run_mode('paired', 'generation', {'arms': ['no-context', 'lexical-eligible'], 'roles': {'generator': generator('FAKE_ENDPOINT')}})
        paired = read_json(bundle_dir(self.report(directory))[0] / 'legal-summary.json')['paired']
        self.assertTrue(paired)
        self.assertTrue(all({k: p[k] for k in ('mean', 'n', 'low', 'high', 'missing')} == dict.fromkeys(('mean', 'n', 'low', 'high', 'missing'))
                            and 'suppressed' not in p for p in paired))


class WorkerAndRefTests(Base):
    """C2 and C3."""

    def test_every_job_file_above_decides(self):
        (job,) = self.plan('w', parameters={'suite': str(self.copy()), 'synthetic': True})['jobs']      # declared: not transferable
        attempt = self.path / 'w' / ('d' * 32)
        (attempt / 'local/sub').mkdir(parents=True)
        atomic_json(attempt / 'job.json', job)
        (attempt / 'local/sub/secret.jsonl').write_text(CANARY, encoding='utf-8')
        write_json(attempt / 'local/sub/job.json', {'experiment_id': 'llm-routing', 'job_id': 'x'})      # a nearer generic job planted
        for call in ({'action': 'file-chunk', 'output': str(attempt), 'path': 'local/sub/secret.jsonl', 'offset': 0},
                     {'action': 'collect', 'output': str(attempt / 'local/sub')}):
            with self.subTest(call=call['action']), self.assertRaisesRegex(ValueError, 'Collection refused by data policy: .*' + 'd' * 32):
                worker.handle(call)
        (attempt / 'local/sub/job.json').unlink()
        (attempt / 'job.json').write_text('{"job_id": "x", "mode": "smo', encoding='utf-8')      # truncated: no experiment name
        with self.assertRaisesRegex(ValueError, 'Collection refused by data policy'):
            worker.handle({'action': 'file-chunk', 'output': str(attempt), 'path': 'local/sub/secret.jsonl', 'offset': 0})
        generic = self.path / 'g' / ('e' * 32)
        (generic / 'local').mkdir(parents=True)
        write_json(generic / 'job.json', {'experiment_id': 'llm-routing', 'job_id': 'r'})
        (generic / 'local/x.jsonl').write_text('{}\n', encoding='utf-8')
        self.assertEqual(sorted(f['path'] for f in worker.handle({'action': 'collect', 'output': str(generic)})['files']), ['job.json', 'local/x.jsonl'])

    def test_the_private_base_ref_is_deleted(self):
        directory = self.smoke(LOCK, 'ref')
        report = self.report(directory)
        self.authorize(directory)
        upstream = read_json(ROOT / contracts.APPROVED_SUITES)
        upstream['suites'].pop(sha256_file(LOCK))      # first the remote base branch does not approve the smoke suite
        repo, bare = self.repository(approved=(json.dumps(upstream, indent=2) + '\n').encode())

        def git(*args):
            return subprocess.run(['git', '-C', str(repo), *args], check=True, capture_output=True, text=True).stdout
        with self.assertRaisesRegex(ValueError, 'not_approved_upstream'):      # refused after the private ref was fetched
            self.publish(report, repo, RecordingGitHub())
        self.assertEqual(git('for-each-ref', '--format=%(refname)', 'refs/llm-eval'), '')
        (repo / contracts.APPROVED_SUITES).write_bytes((ROOT / contracts.APPROVED_SUITES).read_bytes())      # then it does
        git('add', '-A')
        git('-c', 'user.name=x', '-c', 'user.email=x@example.com', 'commit', '-m', 'approve')
        git('push', 'origin', 'main')
        self.publish(report, repo, RecordingGitHub())
        self.assertEqual(git('for-each-ref', '--format=%(refname)', 'refs/llm-eval'), '')


if __name__ == '__main__':
    unittest.main()
