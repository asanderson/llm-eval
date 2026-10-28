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

    def __init__(self, version=PINNED, daemon_running=False, server_running=False, import_exit=0, load_exit=0):
        self.calls = []
        self.version, self.daemon_running, self.server_running = version, daemon_running, server_running
        self.import_exit, self.load_exit = import_exit, load_exit

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

    def run_serve(self, tmp, fake, argv=None):
        with patch.object(lmstudio.subprocess, 'run', side_effect=fake), patch.object(lmstudio.time, 'sleep', side_effect=KeyboardInterrupt), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
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
                                        'load llm-eval/abc123/model.gguf', 'server start'])
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
