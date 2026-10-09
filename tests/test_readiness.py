import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from llm_eval import readiness as r
from llm_eval.common import digest

ROOT = Path(__file__).resolve().parents[1]


class ConsentTests(unittest.TestCase):
    def run_checks(self, checks, **kwargs):
        with contextlib.redirect_stdout(io.StringIO()):
            return r.run_checks(checks, **kwargs)

    def test_decline_and_noninteractive_never_install(self):
        check = r.Check('missing', 'Missing dependency', lambda: (False, 'not installed'), [['installer']])
        for options in ({'interactive': True, 'input_fn': lambda _: ''}, {'interactive': False}, {'check_only': True, 'yes': True}):
            with self.subTest(options=options), patch.object(r.subprocess, 'run') as execute:
                result = self.run_checks([check], **options)
                self.assertFalse(result['ready'])
                execute.assert_not_called()

    def test_consent_rechecks_and_unblocks_dependent_installs(self):
        installed = set()
        checks = [r.Check('a', 'Tool A', lambda: ('a' in installed, ''), [['install-a']]),
                  r.Check('b', 'Tool B', lambda: ('b' in installed, ''), [['install-b']], ('a',))]
        def execute(argv, **kwargs):
            self.assertFalse(kwargs['shell'])
            installed.add(argv[0][-1]); return subprocess.CompletedProcess(argv, 0)
        with patch.object(r.subprocess, 'run', side_effect=execute) as run, patch.object(r, 'refresh_path'):
            result = self.run_checks(checks, interactive=True, input_fn=lambda _: 'yes')
        self.assertTrue(result['ready']); self.assertEqual(run.call_count, 2)
        self.assertEqual([x['status'] for x in result['before']], ['missing', 'missing'])
        self.assertEqual([x['status'] for x in result['checks']], ['pass', 'pass'])

    def test_failed_installer_blocks_dependents_and_keeps_independent_work(self):
        checks = [r.Check('a', 'A', lambda: (False, ''), [['fail']]),
                  r.Check('b', 'B', lambda: (False, ''), [['never']], ('a',)),
                  r.Check('c', 'C', lambda: (False, ''), [['independent']])]
        with patch.object(r.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1)) as run:
            result = self.run_checks(checks, yes=True)
        self.assertFalse(result['ready'])
        self.assertEqual([a['status'] for a in result['actions']], ['failed', 'blocked', 'failed'])
        self.assertEqual([call.args[0][0] for call in run.call_args_list], ['fail', 'independent'])

    def test_zero_exit_is_not_enough_and_no_repeat_installs_for_present_tools(self):
        checks = [r.Check('ok', 'Present', lambda: (True, ''), [['never']]),
                  r.Check('missing', 'Missing', lambda: (False, ''), [['pretend-success']])]
        with patch.object(r.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)) as run:
            result = self.run_checks(checks, yes=True)
        self.assertFalse(result['ready']); self.assertEqual(run.call_count, 1)
        self.assertEqual(result['actions'][0]['status'], 'verification_failed')

    def test_missing_optional_manager_does_not_fail_an_otherwise_ready_host(self):
        result = self.run_checks([r.Check('manager', 'Optional manager', lambda: (False, ''), required=False)], check_only=True)
        self.assertTrue(result['ready'])


class SelectionTests(unittest.TestCase):
    def args(self, *argv): return r.parser().parse_args(list(argv))

    def test_three_raider_campaigns_deduplicate_one_runtime(self):
        for name, os_id in [('windows', 'windows-11-native'), ('ubuntu', 'ubuntu-26.04-native'), ('wsl', 'windows-11-wsl2-ubuntu-26.04')]:
            selection = r.select(self.args('--campaign', str(ROOT/f'configs/examples/raider-{name}/campaign.json')), ROOT)
            self.assertEqual(selection['os_id'], os_id)
            self.assertEqual(list(selection['runtimes'].values()), [False])
            self.assertEqual(next(iter(selection['runtimes']))[0], 'ollama')

    def test_multi_host_selection_and_remote_target_are_not_silently_local(self):
        jobs = [{'hardware_config_id': 'a', 'hardware': {'os_id': 'ubuntu-26.04-native', 'hardware_profile': 'msi-raider-18-hx-ai'},
                 'target': {'transport': 'ssh'}, 'parameters': {}, 'mode': 'decision'},
                {'hardware_config_id': 'b'}]
        with patch('llm_eval.orchestration.planner.compile_campaign', return_value={'jobs': jobs}):
            with self.assertRaisesRegex(ValueError, 'Select one'): r.select(self.args('--campaign', 'c.json'), ROOT)
            with self.assertRaisesRegex(ValueError, 'test host'): r.select(self.args('--campaign', 'c.json', '--hardware-config', 'a'), ROOT)

    def test_synthetic_campaign_needs_no_engine_or_gpu(self):
        selection = r.select(self.args('--campaign', str(ROOT/'campaigns/routing-smoke.json')), ROOT)
        self.assertEqual(selection['runtimes'], {})
        self.assertFalse(selection['needs_gpu'])

    def test_ollama_does_not_require_build_tools_or_docker(self):
        selection = r.select(self.args('--platform', 'ollama', '--os', 'ubuntu-26.04-native'), ROOT)
        checks = r.build_checks(ROOT, selection)
        self.assertFalse({'compiler', 'cuda', 'cmake', 'docker-cli'} & {c.id for c in checks})

    def test_multiple_engines_keep_distinct_system_library_requirements(self):
        selection = r.select(self.args('--platform', 'llama.cpp', '--platform', 'vllm', '--os', 'ubuntu-26.04-native'), ROOT)
        with patch.object(r, 'cuda_linux_install', return_value=[]), patch.object(r, 'package_probe', return_value=(True, '')) as probe:
            checks = {c.id: c for c in r.build_checks(ROOT, selection)}
            for key in ('system-libraries', 'compiler', 'numa-build'): checks[key].inspect()
        requirements = [set(call.args[0]) for call in probe.call_args_list]
        self.assertIn('ca-certificates', requirements[0]); self.assertNotIn('libnuma-dev', requirements[0])
        self.assertIn('libcurl4-openssl-dev', requirements[1]); self.assertIn('libnuma-dev', requirements[2])

    def test_wsl_rejects_placeholder_locks_and_never_offers_linux_driver(self):
        selection = r.select(self.args('--campaign', str(ROOT/'configs/examples/raider-wsl/campaign.json')), ROOT)
        checks = r.build_checks(ROOT, selection)
        self.assertEqual(next(c for c in checks if c.id == 'wsl-lock').inspect()['status'], 'missing')
        self.assertEqual(next(c for c in checks if c.id == 'gpu').commands, [])
        with tempfile.TemporaryDirectory() as tmp:
            selection['target']['lock_root'] = tmp
            checks = r.build_checks(ROOT, selection)
            self.assertEqual(next(c for c in checks if c.id == 'wsl-lock').inspect()['status'], 'pass')

    def test_cuda_install_selects_only_toolkit_from_configured_repo(self):
        responses = [(True, 'cuda-drivers\ncuda-13-4\ncuda-toolkit-13-4\ncuda-toolkit-12-8'),
                     (True, 'Candidate: (none)'), (True, 'Candidate: 12.8.1')]
        with patch.object(r, 'probe_command', side_effect=responses):
            commands = r.cuda_linux_install()
        self.assertEqual(commands[-1][-1], 'cuda-toolkit-12-8')
        self.assertNotIn('cuda-drivers', str(commands))

    def test_native_windows_unsupported_engine_has_no_install_action(self):
        selection = r.select(self.args('--platform', 'vllm', '--os', 'windows-11-native'), ROOT)
        checks = r.build_checks(ROOT, selection)
        runtime = next(c for c in checks if c.id == 'runtime-0')
        self.assertEqual(runtime.commands, [])
        self.assertIn('Unsupported', runtime.inspect()['detail'])

    def test_os_mismatch_blocks_every_install_even_with_yes(self):
        fake = [r.Check('os', 'OS', lambda: (False, 'wrong host')),
                r.Check('dependency', 'Dependency', lambda: (False, ''), [['never-install']])]
        with patch.object(r, 'build_checks', return_value=fake), patch.object(r.subprocess, 'run') as run, contextlib.redirect_stdout(io.StringIO()):
            code = r.main(['--platform', 'ollama', '--os', 'ubuntu-26.04-native', '--yes'])
        self.assertEqual(code, 1); run.assert_not_called()


class RuntimeTests(unittest.TestCase):
    def test_matching_state_offers_dependency_repair_without_replacing_engine(self):
        with tempfile.TemporaryDirectory() as tmp:
            prefix = Path(tmp); backend_py = prefix/'python'; backend_py.write_text('fixture')
            selection = {'os_id': 'ubuntu-26.04-native', 'hardware_profile': 'msi-raider-18-hx-ai',
                         'runtimes': {('ollama', str(prefix)): False}, 'target': {}, 'needs_gpu': True}
            py = r.python_in(ROOT/'.venv', selection['os_id'])
            expected = r.expected_runtime_plan(ROOT, selection, 'ollama', prefix, False, py)
            state = {'status': 'installed', 'plan_sha256': digest(expected), 'python': str(backend_py)}
            state_file = prefix/'state.json'; state_file.write_text(json.dumps(state))
            runtime = next(c for c in r.build_checks(ROOT, selection) if c.id == 'runtime-0')
            self.assertTrue(any('zstandard==0.25.0' in c for c in runtime.commands))
            self.assertFalse(any('setup.py' in str(c) for c in runtime.commands))
            self.assertEqual(json.loads(state_file.read_text()), state)
            state['plan_sha256'] = 'different'; state_file.write_text(json.dumps(state))
            runtime = next(c for c in r.build_checks(ROOT, selection) if c.id == 'runtime-0')
            self.assertEqual(runtime.commands, [])

    def test_real_setup_plan_is_recognized_then_missing_executable_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            prefix = Path(tmp)/'runtime'; prefix.mkdir()
            py = r.python_in(ROOT/'.venv', 'ubuntu-26.04-native')
            command = [sys.executable, str(ROOT/'scripts/setup.py'), '--non-interactive', '--platform', 'ollama',
                       '--os', 'ubuntu-26.04-native', '--prefix', str(prefix), '--python', py, '--jobs', '8', '--dry-run']
            plan = json.loads(subprocess.check_output(command, cwd=ROOT, text=True))
            executable = prefix/'ollama'; executable.write_text('fixture')
            state = {'status': 'installed', 'plan': plan, 'plan_sha256': digest(plan), 'python': 'fixture-python', 'executable': str(executable)}
            (prefix/'state.json').write_text(json.dumps(state))
            selection = {'os_id': 'ubuntu-26.04-native', 'hardware_profile': 'msi-raider-18-hx-ai'}
            with patch.object(r, 'probe_command', return_value=(True, 'ollama version 0.35.1')), patch.object(r, 'python_probe', return_value=(True, '')):
                self.assertTrue(r.runtime_probe(ROOT, selection, 'ollama', prefix, False, py)[0])
                executable.unlink()
                self.assertIn('executable missing', r.runtime_probe(ROOT, selection, 'ollama', prefix, False, py)[1])

    def test_bad_transitive_dependencies_do_not_pass_installed_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            prefix = Path(tmp); py = r.python_in(ROOT/'.venv', 'ubuntu-26.04-native')
            selection = {'os_id': 'ubuntu-26.04-native', 'hardware_profile': 'msi-raider-18-hx-ai'}
            plan = r.install_plan(ROOT, 'ollama', selection['os_id'], prefix, python=py)
            plan.update(selected_models=['llama33-70b'], selected_categories=[c['id'] for c in r.read_json(ROOT/'catalog/benchmarks.json')['categories']], download_spec=None, grading_image_tag=None)
            (prefix/'state.json').write_text(json.dumps({'status': 'installed', 'plan_sha256': digest(plan), 'python': 'fixture'}))
            with patch.object(r, 'probe_command', return_value=(False, 'package X requires missing Y')):
                ok, detail = r.runtime_probe(ROOT, selection, 'ollama', prefix, False, py)
            self.assertFalse(ok); self.assertIn('missing Y', detail)

    def test_cli_report_records_missing_dependency_and_nonzero_exit(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            report = Path(tmp)/'readiness.json'
            with patch.object(r, 'build_checks', return_value=[r.Check('missing', 'Missing library', lambda: (False, 'not installed'))]):
                code = r.main(['--os', 'ubuntu-26.04-native', '--check-only', '--json-output', str(report)])
            data = json.loads(report.read_text())
        self.assertEqual(code, 1); self.assertFalse(data['ready']); self.assertEqual(data['actions'], [])


class WrapperTests(unittest.TestCase):
    @unittest.skipUnless(os.name == 'nt', 'Windows PowerShell parser')
    def test_powershell_wrapper_parses(self):
        path = str(ROOT/'scripts/readiness.ps1').replace("'", "''")
        command = f"$tokens=$null; $errors=$null; [System.Management.Automation.Language.Parser]::ParseFile('{path}',[ref]$tokens,[ref]$errors) | Out-Null; if ($errors.Count) {{ $errors | Out-String | Write-Output; exit 1 }}"
        subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command', command], check=True)

    @unittest.skipIf(os.name == 'nt', 'Bash wrapper')
    def test_bash_wrapper_help_forwards_without_installing(self):
        subprocess.run(['bash', '-n', str(ROOT/'scripts/readiness.sh')], check=True)
        env = {**os.environ, 'LLM_EVAL_PYTHON': sys.executable}
        p = subprocess.run(['bash', str(ROOT/'scripts/readiness.sh'), '--help'], env=env, capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn('--check-only', p.stdout)


if __name__ == '__main__': unittest.main()
