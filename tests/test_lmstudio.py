import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from llm_eval import lmstudio
from llm_eval import readiness as r
from llm_eval.common import read_json, write_json
from llm_eval.launch import launch_spec
from llm_eval.provision import OS_IDS, install_plan, lms_executable

ROOT = Path(__file__).resolve().parents[1]
# The pinned app version lives in the catalog; the nightly upstream-pins bump moves it there.
PINNED = read_json(ROOT / 'catalog/installers.json')['platforms']['lmstudio']['version']


class FakeLms:
    """Scripted lms CLI: records argument arrays and answers status/version queries."""

    def __init__(self, version=PINNED, daemon_running=False, server_running=False, import_exit=0, load_exit=0, listed_after=0):
        self.calls = []
        self.version, self.daemon_running, self.server_running = version, daemon_running, server_running
        self.import_exit, self.load_exit = import_exit, load_exit
        # `lms ls` answers this many times without the new import before it lists it; None: it never lists it.
        self.listed_after, self.imported, self.listings = listed_after, False, 0

    def __call__(self, argv, **kwargs):
        self.calls.append(argv[1:])
        assert kwargs['shell'] is False
        command = ' '.join(argv[1:3])
        out = ''
        code = 0
        if command == 'daemon status':
            out = json.dumps({'status': 'running', 'pid': 7} if self.daemon_running else {'status': 'not-running'})
        elif command == 'daemon up':
            out = json.dumps({'status': 'running', 'pid': 7, 'isDaemon': True, 'version': self.version})
            self.daemon_running = True
        elif command == 'server status':
            out = json.dumps({'running': self.server_running, 'port': 1234})
        elif argv[1] == 'import':
            code = self.import_exit
            out = 'Target file already exists: x' if code else ''
            self.imported = True
        elif argv[1] == 'ls':      # the shape LM Studio 0.4.28 answers: one entry per indexed model
            self.listings += 1
            models = [{'type': 'embedding', 'modelKey': 'text-embedding-nomic-embed-text-v1.5',
                       'path': 'nomic-ai/nomic-embed-text-v1.5-GGUF/nomic-embed-text-v1.5.Q4_K_M.gguf'}]
            if self.imported and self.listed_after is not None and self.listings > self.listed_after:
                models.append({'type': 'llm', 'modelKey': 'abc123', 'path': 'llm-eval/abc123/model.gguf',
                               'indexedModelIdentifier': 'llm-eval/abc123/model.gguf'})
            out = json.dumps(models)
        elif argv[1] == 'load':
            code = self.load_exit
        elif command == 'server start':
            self.server_running = True
        return subprocess.CompletedProcess(argv, code, out, '')


class SupervisorTests(unittest.TestCase):
    def args(self, tmp, **extra):
        argv = ['serve', '--lms', 'lms', '--model-file', str(Path(tmp) / 'model.gguf'), '--artifact-id', 'abc123',
                '--identifier', 'eval-model', '--port', '1234', '--context-length', '8192', '--gpu', '0.5',
                '--state', str(Path(tmp) / 'state.json'), '--expected-version', PINNED]
        for key, value in extra.items():
            argv += ['--' + key.replace('_', '-'), value]
        return argv

    def run_serve(self, tmp, fake, argv=None, sleep=KeyboardInterrupt, stderr=None):
        """Run `serve` against a scripted lms. By default every sleep ends the run: the first one is the hold loop after
        the server started, because the scripted lms lists a new import at once."""
        with patch.object(lmstudio.subprocess, 'run', side_effect=fake), patch.object(lmstudio.time, 'sleep', side_effect=sleep), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(stderr or io.StringIO()):
            try:
                return lmstudio.main(argv or self.args(tmp))
            except KeyboardInterrupt:
                return 'held'

    def test_import_load_serve_then_cleanup_releases_only_what_it_started(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = FakeLms()
            self.assertEqual(self.run_serve(tmp, fake), 'held')
            commands = [' '.join(c[:2]) for c in fake.calls]
            self.assertEqual(commands, ['daemon status', 'daemon up', 'server status', 'import ' + str(Path(tmp) / 'model.gguf'),
                                        'ls --json', 'load llm-eval/abc123/model.gguf', 'server start'])
            load = next(c for c in fake.calls if c[0] == 'load')
            self.assertEqual(load[1:], ['llm-eval/abc123/model.gguf', '--identifier', 'eval-model', '--context-length', '8192',
                                        '--gpu', '0.5', '--parallel', '1', '--exact', '--yes'])
            self.assertIn('--symbolic-link', next(c for c in fake.calls if c[0] == 'import'))
            self.assertEqual(fake.calls[-1], ['server', 'start', '--port', '1234', '--bind', '127.0.0.1'])
            state = read_json(Path(tmp) / 'state.json')
            self.assertEqual(state, {'daemon_started': True, 'daemon_pid': 7, 'server_started': True, 'loaded': 'eval-model'})
            fake.calls.clear()
            with patch.object(lmstudio.subprocess, 'run', side_effect=fake):
                lmstudio.main(['cleanup', '--lms', 'lms', '--state', str(Path(tmp) / 'state.json')])
            self.assertEqual(fake.calls, [['unload', 'eval-model'], ['server', 'stop'], ['daemon', 'down']])
            self.assertFalse((Path(tmp) / 'state.json').exists())
            with patch.object(lmstudio.subprocess, 'run', side_effect=fake) as run:
                lmstudio.main(['cleanup', '--lms', 'lms', '--state', str(Path(tmp) / 'state.json')])
            self.assertEqual(run.call_count, 0)

    def test_existing_daemon_is_left_running_and_existing_import_is_reused(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = FakeLms(daemon_running=True, import_exit=1)
            self.assertEqual(self.run_serve(tmp, fake), 'held')
            self.assertFalse(read_json(Path(tmp) / 'state.json')['daemon_started'])
            fake.calls.clear()
            with patch.object(lmstudio.subprocess, 'run', side_effect=fake):
                lmstudio.main(['cleanup', '--lms', 'lms', '--state', str(Path(tmp) / 'state.json')])
            self.assertEqual(fake.calls, [['unload', 'eval-model'], ['server', 'stop']])

    def test_version_mismatch_and_foreign_server_abort_before_loading(self):
        for fake in (FakeLms(version='0.4.25+1'), FakeLms(server_running=True)):
            with self.subTest(version=fake.version, server=fake.server_running), tempfile.TemporaryDirectory() as tmp:
                self.assertEqual(self.run_serve(tmp, fake), 1)
                self.assertFalse(any(c[0] in {'import', 'load'} for c in fake.calls))
                self.assertFalse((Path(tmp) / 'state.json').exists())
                self.assertIn(['daemon', 'down'], fake.calls)

    def test_failed_load_cleans_up_and_extra_args_reach_lms_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = FakeLms(load_exit=1)
            self.assertEqual(self.run_serve(tmp, fake, self.args(tmp) + ['--flash-attention']), 1)
            load = next(c for c in fake.calls if c[0] == 'load')
            self.assertEqual(load[-1], '--flash-attention')
            self.assertNotIn(['server', 'start', '--port', '1234', '--bind', '127.0.0.1'], fake.calls)
            self.assertEqual(fake.calls[-1], ['daemon', 'down'])

    def test_load_waits_until_lm_studio_lists_the_import(self):
        # LM Studio indexes a new import asynchronously: `lms load --exact` at once can answer that no model has the path.
        for name, import_exit in (('new import', 0), ('existing import', 1)):
            with self.subTest(name), tempfile.TemporaryDirectory() as tmp, patch.object(lmstudio, 'LIST_POLL_S', 0.25):
                fake = FakeLms(import_exit=import_exit, listed_after=3)      # listed at the fourth check
                slept = []

                def sleep(seconds):
                    if seconds != 0.25:      # the hold loop after the server started
                        raise KeyboardInterrupt
                    slept.append(seconds)
                self.assertEqual(self.run_serve(tmp, fake, sleep=sleep), 'held')
                commands = [' '.join(c[:2]) for c in fake.calls]
                self.assertEqual(commands[3:], ['import ' + str(Path(tmp) / 'model.gguf')] + ['ls --json'] * 4 +
                                 ['load llm-eval/abc123/model.gguf', 'server start'])
                self.assertEqual(slept, [0.25] * 3)
                self.assertEqual(read_json(Path(tmp) / 'state.json')['loaded'], 'eval-model')

    def test_an_import_that_is_never_listed_fails_before_any_load_and_cleans_up(self):
        for name, extra, limit in (('the listing limit', {}, 3), ('a shorter load timeout', {'load_timeout': '2'}, 2)):
            with self.subTest(name), tempfile.TemporaryDirectory() as tmp, patch.object(lmstudio, 'LIST_TIMEOUT_S', 3), \
                    patch.object(lmstudio, 'LIST_POLL_S', 1.0):
                fake = FakeLms(listed_after=None)
                clock = [100.0]

                def sleep(seconds):
                    if seconds != 1.0:
                        raise KeyboardInterrupt
                    clock[0] += seconds
                err = io.StringIO()
                with patch.object(lmstudio.time, 'monotonic', side_effect=lambda: clock[0]):
                    self.assertEqual(self.run_serve(tmp, fake, self.args(tmp, **extra), sleep=sleep, stderr=err), 1)
                self.assertFalse(any(c[0] == 'load' for c in fake.calls))
                self.assertEqual(sum(c[0] == 'ls' for c in fake.calls), limit + 1)      # at 0, 1, ... and `limit` seconds
                self.assertIn(f'LM Studio did not list the imported model llm-eval/abc123/model.gguf within {limit} s', err.getvalue())
                self.assertNotIn(['server', 'start', '--port', '1234', '--bind', '127.0.0.1'], fake.calls)
                self.assertEqual(fake.calls[-1], ['daemon', 'down'])
                self.assertFalse((Path(tmp) / 'state.json').exists())

    def test_a_failed_or_slow_listing_counts_as_not_listed(self):
        key = 'llm-eval/abc123/model.gguf'
        answers = [subprocess.TimeoutExpired(['lms', 'ls'], 120), (1, 'error'), (0, 'not json'), (0, json.dumps([{'path': key}]))]

        def run(argv, timeout=900):
            self.assertEqual(argv, ['lms', 'ls', '--json'])
            answer = answers.pop(0)
            if isinstance(answer, BaseException):
                raise answer
            return answer
        with patch.object(lmstudio, 'run', side_effect=run), patch.object(lmstudio.time, 'sleep') as sleep:
            self.assertTrue(lmstudio.wait_until_listed('lms', key, 60))
        self.assertEqual((sleep.call_count, answers), (3, []))

    def test_listed_paths_reads_the_json_array_of_lms_ls(self):
        sample = [{'type': 'llm', 'modelKey': 'd44b7f92fe57', 'format': 'gguf', 'path': 'llm-eval/d44b7f92fe57/model-Q6_K.gguf',
                   'indexedModelIdentifier': 'llm-eval/d44b7f92fe57/model-Q6_K.gguf'},
                  {'type': 'embedding', 'modelKey': 'text-embedding-nomic-embed-text-v1.5',
                   'path': 'nomic-ai/nomic-embed-text-v1.5-GGUF/nomic-embed-text-v1.5.Q4_K_M.gguf'}]
        paths = {'llm-eval/d44b7f92fe57/model-Q6_K.gguf', 'nomic-ai/nomic-embed-text-v1.5-GGUF/nomic-embed-text-v1.5.Q4_K_M.gguf'}
        self.assertEqual(lmstudio.listed_paths(json.dumps(sample)), paths)
        self.assertEqual(lmstudio.listed_paths('[info] a notice before the answer\n' + json.dumps(sample)), paths)
        self.assertEqual(lmstudio.listed_paths(json.dumps([{'indexedModelIdentifier': 'llm-eval\\abc123\\model.gguf'}])),
                         {'llm-eval/abc123/model.gguf'})      # a Windows separator compares as the path `lms load` takes
        for text in ('', 'No models found', '[not json', json.dumps({'path': 'x'}), json.dumps(['x', 1, None]),
                     json.dumps([{'modelKey': 'abc123'}]), json.dumps([{'path': 7}])):
            with self.subTest(text=text):
                self.assertEqual(lmstudio.listed_paths(text), set())

    def test_gpu_offload_values(self):
        for value in ('off', 'max', '0', '1', '0.5'):
            self.assertEqual(lmstudio.gpu_offload(value), value)
        for value in ('20', '-0.1', 'auto', 'nan', ''):
            with self.subTest(value=value), self.assertRaises(ValueError):
                lmstudio.gpu_offload(value)


class LaunchAndSetupTests(unittest.TestCase):
    def test_launch_uses_supervisor_with_locked_hash_and_cleanup(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = read_json(ROOT / 'configs/runs/lmstudio.example.json')
            weights = Path(tmp) / 'model.gguf'
            weights.write_bytes(b'fixture')
            lock = Path(tmp) / 'lock.json'
            write_json(lock, {'files': [{'path': 'model.gguf', 'sha256': 'f' * 64}]})
            c.update(artifact_root=tmp, artifact_lock=str(lock), served_model='eval-model')
            c['launch'] = {'model_file': 'model.gguf', 'threads': 16, 'gpu_offload': 'max'}
            state = {'plan': {'platform': 'lmstudio', 'os_id': c['os_id'], 'prefix': tmp, 'recipe': {'version': PINNED}},
                     'python': 'python', 'executable': '/opt/lms'}
            spec = launch_spec(c, state, tmp)
            self.assertEqual(spec['argv'][:4], ['python', '-m', 'llm_eval.lmstudio', 'serve'])
            argv = spec['argv']
            self.assertEqual(argv[argv.index('--artifact-id') + 1], 'f' * 12)
            self.assertEqual(argv[argv.index('--port') + 1], '1234')
            self.assertEqual(argv[argv.index('--gpu') + 1], 'max')
            self.assertEqual(argv[argv.index('--expected-version') + 1], PINNED)
            self.assertEqual(spec['cleanup'][0][:4], ['python', '-m', 'llm_eval.lmstudio', 'cleanup'])
            self.assertEqual(spec['port'], 1234)
            c['launch']['extra_args'] = ['--ttl', '60']
            with self.assertRaisesRegex(ValueError, 'override'):
                launch_spec(c, state, tmp)
            c['launch'] = {'model_file': 'model.gguf', 'gpu_offload': '20'}
            with self.assertRaisesRegex(ValueError, 'gpu_offload'):
                launch_spec(c, state, tmp)

    def test_install_plan_declares_operator_installed_app_and_no_build_tools(self):
        for os_id in OS_IDS:
            plan = install_plan(ROOT, 'lmstudio', os_id, ROOT / '.not-created')
            self.assertEqual(plan['recipe']['kind'], 'lmstudio')
            self.assertTrue(any('LM Studio ' + PINNED in p for p in plan['prerequisites']))
            self.assertFalse(any('CMake' in p for p in plan['prerequisites']))
        self.assertFalse((ROOT / '.not-created').exists())

    def test_lms_executable_prefers_documented_user_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {'HOME': tmp, 'USERPROFILE': tmp}), patch('shutil.which', return_value=None):
                self.assertIsNone(lms_executable('ubuntu-26.04-native'))
                exe = Path(tmp) / '.lmstudio/bin/lms'
                exe.parent.mkdir(parents=True)
                exe.write_text('fixture')
                self.assertEqual(lms_executable('ubuntu-26.04-native'), exe)

    def test_readiness_offers_pinned_winget_only_on_windows(self):
        for os_id, expect_install in (('windows-11-native', True), ('ubuntu-26.04-native', False)):
            with self.subTest(os=os_id):
                selection = r.select(r.parser().parse_args(['--platform', 'lmstudio', '--os', os_id]), ROOT)
                checks = {c.id: c for c in r.build_checks(ROOT, selection)}
                self.assertFalse({'compiler', 'cuda', 'cmake'} & set(checks))
                app = checks['lmstudio-app']
                self.assertEqual(bool(app.commands), expect_install)
                if expect_install:
                    self.assertEqual(app.commands[0][:4], ['winget', 'install', '--id', 'ElementLabs.LMStudio'])
                    self.assertEqual(app.commands[0][-2:], ['--version', PINNED])
                self.assertIn('lmstudio-app', checks['runtime-0'].requires)
                with patch.object(r, 'lms_executable', return_value=None):
                    self.assertEqual(app.inspect()['status'], 'missing')


if __name__ == '__main__':
    unittest.main()
