import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import zipfile

from llm_eval.common import read_json, write_json
from llm_eval.launch import launch_spec, wait_port
from llm_eval.livebench import question_manifest, run_livebench, upstream_commands
from llm_eval.model_download import validate_download_spec
from llm_eval.provision import OS_IDS, extract_archive, https_download, install_plan
from llm_eval.report import summarize, write_report
from llm_eval.runner import grade, load_suite, validate_host
from llm_eval.workflow import Prompts, main

ROOT = Path(__file__).resolve().parents[1]


class WorkflowTests(unittest.TestCase):
    def test_multiple_models_and_categories_run_sequentially(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);configs=[];events=[]
            for model in ['deepseek-r1-32b','deepseek-r1-70b']:
                c=read_json(ROOT/'configs/runs/llama.cpp.example.json')
                c.update(model_id=model,backend_version='a'*40,tokenizer_revision='b'*40,
                         chat_template_sha256='c'*64,placement_notes='fixture placement',
                         hardware_attestation={'fixture':True},artifact_root=tmp,
                         artifact_lock=str(folder/(model+'.lock.json')))
                base='deepseek-ai/DeepSeek-R1-Distill-'+('Qwen-32B' if model.endswith('32b') else 'Llama-70B')
                write_json(c['artifact_lock'],{'base_model_repo':base})
                path=folder/(model+'.json');write_json(path,c);configs+=['--config',str(path)]
            write_json(folder/'prefix/state.json',{'status':'installed','fixture':True})
            @contextlib.contextmanager
            def backend(c,state,path):
                events.append(('start',c['model_id']))
                try:yield
                finally:events.append(('stop',c['model_id']))
            def evaluate(path,root,output):
                c=read_json(path);events.append(('run',c['model_id'],Path(c['suite']).stem))
                result=output/Path(c['suite']).stem
                write_json(result/'metadata.json',{'status':'completed','synthetic':False})
                return result
            with patch('llm_eval.runner.environment_kind',return_value=OS_IDS[0]), \
                    patch('llm_eval.workflow.verify_artifact'),patch('llm_eval.workflow.validate_host',return_value={}), \
                    patch('llm_eval.workflow.managed_backend',side_effect=backend),patch('llm_eval.workflow.run',side_effect=evaluate), \
                    contextlib.redirect_stdout(io.StringIO()):
                code=main('run',['--non-interactive',*configs,'--prefix',str(folder/'prefix'),
                                 '--categories','reasoning,math','--output',str(folder/'results')])
            self.assertEqual(code,0)
            self.assertEqual([e[0] for e in events],['start','run','run','stop','start','run','run','stop'])
            manifest=next((folder/'results').glob('session-*/session.json'))
            self.assertEqual(len(read_json(manifest)['runs']),4)

    def test_every_platform_os_has_setup_and_run_wrapper(self):
        platforms = read_json(ROOT / 'catalog/platforms.json')['platforms']
        for platform in platforms:
            for os_id in OS_IDS:
                with self.subTest(platform=platform['id'], os=os_id):
                    suffix = '.ps1' if os_id == 'windows-11-native' else '.sh'
                    for action in ('setup', 'run'):
                        wrapper = ROOT / 'scripts/platforms' / os_id / platform['id'] / (action + suffix)
                        content = wrapper.read_text()
                        self.assertIn(platform['id'], content)
                        self.assertIn(os_id, content)
                        self.assertIn(action + '.py', content)
                    if platform['os_support'][os_id] == 'unsupported':
                        with self.assertRaisesRegex(ValueError, 'unsupported'):
                            install_plan(ROOT, platform['id'], os_id, ROOT / '.not-created')
                    else:
                        plan = install_plan(ROOT, platform['id'], os_id, ROOT / '.not-created')
                        self.assertEqual(plan['cuda_arch'], '120')
        self.assertFalse((ROOT / '.not-created').exists())

    def test_noninteractive_setup_dry_run_is_side_effect_free(self):
        with tempfile.TemporaryDirectory() as tmp, patch('builtins.input', side_effect=AssertionError('unexpected prompt')), \
                patch('llm_eval.workflow.execute_install') as install, contextlib.redirect_stdout(io.StringIO()) as output:
            result = main('setup', ['--non-interactive', '--dry-run', '--platform', 'llama.cpp', '--os', OS_IDS[0],
                                    '--prefix', tmp + '/new', '--categories', 'reasoning,coding'])
            plan = json.loads(output.getvalue())
            self.assertEqual(result, 0)
            self.assertEqual(plan['selected_categories'], ['reasoning', 'coding'])
            self.assertFalse(Path(tmp, 'new').exists())
            install.assert_not_called()

    def test_noninteractive_missing_platform_fails_without_prompt(self):
        with patch('builtins.input', side_effect=AssertionError('unexpected prompt')), \
                contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as exc:
            main('setup', ['--non-interactive', '--dry-run'])
        self.assertEqual(exc.exception.code, 2)

    def test_interactive_selections_and_invalid_arguments(self):
        with patch('builtins.input', side_effect=['2', '', 'yes']), contextlib.redirect_stdout(io.StringIO()):
            p = Prompts(True)
            self.assertEqual(p.value('platform', choices=['a', 'b']), 'b')
            self.assertEqual(p.value('context', default=4096), 4096)
            self.assertTrue(p.yes('save'))
        with self.assertRaises(ValueError):
            Prompts(False).value('platform', value='c', choices=['a', 'b'])
        with self.assertRaises(ValueError):
            install_plan(ROOT, 'llama.cpp', OS_IDS[0], '/unused', revision='main')
        with self.assertRaises(ValueError):
            install_plan(ROOT, 'vllm', OS_IDS[0], '/unused', packages=['vllm>=1'])

    def test_run_dry_plan_all_supported_platform_os_pairs(self):
        for platform in read_json(ROOT / 'catalog/platforms.json')['platforms']:
            for os_id in OS_IDS:
                if platform['os_support'][os_id] == 'unsupported':
                    continue
                with self.subTest(platform=platform['id'], os=os_id), tempfile.TemporaryDirectory() as tmp:
                    config = read_json(ROOT / f'configs/runs/{platform["id"]}.example.json')
                    config.update(os_id=os_id, ram_budget_gib=46)
                    path = Path(tmp) / 'config.json'
                    write_json(path, config)
                    with contextlib.redirect_stdout(io.StringIO()) as out, patch('builtins.input', side_effect=AssertionError):
                        code = main('run', ['--non-interactive', '--dry-run', '--config', str(path),
                                            '--prefix', tmp + '/missing', '--categories', 'math,instruction_following'])
                    result = json.loads(out.getvalue())
                    self.assertEqual(code, 0)
                    self.assertEqual(result['runs'][0]['categories'], ['math', 'instruction_following'])
                    self.assertFalse(Path(tmp, 'missing').exists())

    def test_categories_have_original_deterministic_checks(self):
        categories = read_json(ROOT / 'catalog/benchmarks.json')['categories']
        self.assertEqual(len(categories), 7)
        self.assertEqual(sum(len(c['livebench_tasks']) for c in categories), 23)
        for category in categories:
            suite = load_suite(ROOT / category['local_suite'])
            self.assertEqual(suite['category'], category['id'])
            self.assertEqual(suite['benchmark'], 'category-smoke')
            for task in suite['tasks']:
                value = task['check']['expected']
                text = json.dumps(value) if task['check']['type'] == 'json_equal' else value
                self.assertTrue(grade(text, task))

    def test_host_preflight_rejects_missing_gpu_and_battery(self):
        config = {'hardware_profile': 'msi-raider-18-hx-ai'}
        with self.assertRaisesRegex(ValueError, 'NVIDIA GPU'):
            validate_host(config, ROOT, {'psutil_available': True, 'gpus': []})
        with self.assertRaisesRegex(ValueError, 'AC power'):
            validate_host(config, ROOT, {'psutil_available': True, 'gpus': [{'name': 'NVIDIA GeForce RTX 5090 Laptop GPU'}], 'ac_connected': False})


class InstallSafetyTests(unittest.TestCase):
    def test_archive_paths_and_symlinks_rejected(self):
        for name, symlink in [('../escaped', False), ('/absolute', False), ('C:/escape', False), ('link', True)]:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                archive = Path(tmp) / 'asset.zip'
                with zipfile.ZipFile(archive, 'w') as z:
                    info = zipfile.ZipInfo(name)
                    if symlink:
                        info.external_attr = (stat.S_IFLNK | 0o777) << 16
                    z.writestr(info, 'bad')
                with self.assertRaises(ValueError):
                    extract_archive(archive, Path(tmp) / 'output')
                self.assertFalse(Path(tmp, 'escaped').exists())

    def test_verified_download_preserves_other_partial_and_rejects_tamper(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / 'asset'
            existing = Path(tmp) / 'asset.partial'
            existing.write_bytes(b'owned by another operation')
            stream = io.BytesIO(b'payload')
            stream.url = 'https://example.invalid/asset'
            with patch('urllib.request.urlopen', return_value=stream):
                with self.assertRaisesRegex(ValueError, 'SHA256'):
                    https_download(stream.url, 'a' * 64, dest)
            self.assertFalse(dest.exists())
            self.assertEqual(existing.read_bytes(), b'owned by another operation')
            stream = io.BytesIO(b'payload')
            stream.url = 'https://example.invalid/asset'
            with patch('urllib.request.urlopen', return_value=stream):
                https_download(stream.url, hashlib.sha256(b'payload').hexdigest(), dest)
            self.assertEqual(dest.read_bytes(), b'payload')

    def test_model_download_requires_revision_license_and_narrow_selection(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'download.json'
            entry = dict(model_id='phi4-reasoning-plus', source_repo='microsoft/Phi-4-reasoning-plus',
                         source_revision='a' * 40, precision='BF16', artifact_root=tmp + '/model',
                         artifact_lock=tmp + '/lock.json', include=['*.safetensors', '*.json'], accept_license=True)
            write_json(path, {'models': [entry]})
            self.assertEqual(len(validate_download_spec(ROOT, path)), 1)
            for change in [dict(source_revision='main'), dict(accept_license=False), dict(include=['*']),
                           dict(artifact_lock=tmp + '/model/lock.json')]:
                write_json(path, {'models': [{**entry, **change}]})
                with self.assertRaises(ValueError):
                    validate_download_spec(ROOT, path)
            write_json(path, {'models': [entry, {**entry, 'model_id': 'mistral-small31', 'artifact_root': tmp + '/model/child'}]})
            with self.assertRaisesRegex(ValueError, 'overlap'):
                validate_download_spec(ROOT, path)


class LaunchTests(unittest.TestCase):
    def config(self, tmp, platform='llama.cpp'):
        c = read_json(ROOT / f'configs/runs/{platform}.example.json')
        c.update(artifact_root=tmp, served_model='local-model')
        c['launch'] = {'model_file': 'model.gguf', 'threads': 16, 'gpu_layers': 20}
        state = {'plan': {'platform': platform, 'os_id': c['os_id'], 'prefix': tmp},
                 'python': 'python', 'executable': 'engine', 'source': tmp}
        Path(tmp, 'model.gguf').write_bytes(b'fixture')
        return c, state

    def test_launch_rejects_network_override_and_outside_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            c, state = self.config(tmp)
            spec = launch_spec(c, state, tmp)
            self.assertIn('127.0.0.1', spec['argv'])
            self.assertEqual(spec['env']['CPUINFER_ENABLE_AMX'], 'OFF')
            c['launch']['extra_args'] = ['--host=0.0.0.0']
            with self.assertRaisesRegex(ValueError, 'override'):
                launch_spec(c, state, tmp)
            c['launch']['extra_args'] = []
            c['launch']['model_file'] = '../other.gguf'
            with self.assertRaises(ValueError):
                launch_spec(c, state, tmp)

    def test_strata_plan_never_includes_secret(self):
        with tempfile.TemporaryDirectory() as tmp:
            c, state = self.config(tmp, 'strata')
            c.update(reviewed_strata_config=True, api_key_env='LLM_EVAL_TEST_KEY')
            c['launch']['strata_config'] = 'strata.json'
            state['executable'] = str(Path(tmp) / 'engine')
            write_json(Path(tmp) / 'strata.json', {'exe': state['executable']})
            with patch.dict(os.environ, {'LLM_EVAL_TEST_KEY': 'secret-value'}):
                spec = launch_spec(c, state, tmp)
            self.assertNotIn('secret-value', json.dumps(spec))

    def test_readiness_checks_http_and_passes_auth(self):
        process = Mock()
        process.poll.return_value = None
        conn = Mock()
        conn.getresponse.return_value.status = 200
        with patch('llm_eval.launch.http.client.HTTPConnection', return_value=conn):
            wait_port(process, 8100, 1, headers={'Authorization': 'Bearer fixture'})
        conn.request.assert_called_once_with('GET', '/v1/models', headers={'Authorization': 'Bearer fixture'})
        process.poll.return_value = 2
        with self.assertRaisesRegex(RuntimeError, 'exited'):
            wait_port(process, 8100, 1)


class LiveBenchTests(unittest.TestCase):
    def data(self, tmp, category='coding'):
        folder = Path(tmp) / 'data/live_bench' / category / 'task'
        folder.mkdir(parents=True)
        q = {'question_id': 1, 'category': category, 'livebench_release_date': '2026-06-25', 'livebench_removal_date': ''}
        (folder / 'question.jsonl').write_text(json.dumps(q) + '\n')
        (folder / 'test_cases_1.jsonl').write_text('{"question_id":1}\n')
        return Path(tmp) / 'data', folder

    def state(self, tmp):
        source = Path(tmp) / 'upstream'
        (source / 'livebench').mkdir(parents=True)
        (source / 'livebench/gen_api_answer.py').write_text('# pinned fixture\n')
        return {'livebench_source': str(source), 'livebench_python': 'python', 'livebench_revision': 'a' * 40}

    def test_snapshot_counts_tests_and_rejects_empty_or_duplicate(self):
        with tempfile.TemporaryDirectory() as tmp:
            data, folder = self.data(tmp)
            manifest = question_manifest(data, ['coding'], '2026-06-25')
            self.assertEqual(len(manifest['files']), 2)
            self.assertEqual(manifest['categories']['coding']['eligible_questions'], 1)
            with self.assertRaisesRegex(ValueError, 'No eligible'):
                question_manifest(data, ['math'], '2026-06-25')
            path = folder / 'question.jsonl'
            path.write_text(path.read_text() * 2)
            with self.assertRaisesRegex(ValueError, 'Duplicate'):
                question_manifest(data, ['coding'], '2026-06-25')

    def test_commands_disable_host_grading_and_isolate_container(self):
        with tempfile.TemporaryDirectory() as tmp:
            data, _ = self.data(tmp)
            manifest = question_manifest(data, ['coding'], '2026-06-25')
            config = {'endpoint': 'http://127.0.0.1:8100/v1/chat/completions', 'served_model': 'local'}
            commands = upstream_commands(config, {'livebench_python': 'python'}, manifest, Path(tmp) / 'run', ['coding'], max_tokens=512, image='grader')
            generation, grading, report = commands
            self.assertIn('--no-incremental-grading', generation['argv'])
            self.assertNotIn('--grading-parallel', generation['argv'])
            self.assertIn('none', grading['argv'])
            self.assertIn('--read-only', grading['argv'])
            self.assertTrue(any(x.endswith('target=/work/source,readonly') for x in grading['argv']))
            self.assertFalse(any('docker.sock' in x for x in grading['argv']))
            self.assertEqual(report['phase'], 'report')

    def test_agentic_and_worker_gates(self):
        with self.assertRaisesRegex(ValueError, 'OpenAI-compatible'):
            run_livebench({'protocol': 'worker'}, {}, [], '/unused', '2026-06-25', '/unused', image='grader', dry_run=True)
        with self.assertRaisesRegex(ValueError, 'allow-agentic-execution'):
            run_livebench({'protocol': 'openai'}, {'livebench_source': 's', 'livebench_python': 'p'}, ['agentic_coding'],
                          '/unused', '2026-06-25', '/unused', image='grader', dry_run=True)
        with tempfile.TemporaryDirectory() as tmp:
            data,folder=self.data(tmp,'agentic_coding')
            config={'protocol':'openai','endpoint':'http://127.0.0.1:8100/v1/chat/completions',
                    'served_model':'local','max_output_tokens':512}
            plan=run_livebench(config,self.state(tmp),['agentic_coding'],data,'2026-06-25',Path(tmp)/'run',
                               image='grader',allow_agentic=True,dry_run=True)
            self.assertEqual([c['phase'] for c in plan['commands']],['generate','agentic-grade','report'])
            path=folder/'question.jsonl';q=json.loads(path.read_text());q['category']='coding';path.write_text(json.dumps(q)+'\n')
            with self.assertRaisesRegex(ValueError,'category does not match'):
                question_manifest(data,['agentic_coding'],'2026-06-25')

    def test_managed_model_stops_before_grading_and_snapshot_is_copied(self):
        with tempfile.TemporaryDirectory() as tmp:
            data, _ = self.data(tmp)
            state = self.state(tmp)
            out = Path(tmp) / 'run'
            events = []
            @contextlib.contextmanager
            def backend():
                events.append('start')
                try:
                    yield
                finally:
                    events.append('stop')
            def invocation(argv, **kwargs):
                return SimpleNamespace(stdout=('a' * 40 if 'rev-parse' in argv else '' if 'status' in argv else 'sha256:' + 'b' * 64))
            def execute(argv, **kwargs):
                if argv[:2] == ['docker', 'run']:
                    events.append('grade')
                elif any(str(x).endswith('gen_api_answer.py') for x in argv):
                    events.append('generate')
                self.assertFalse(kwargs['shell'])
                return SimpleNamespace(returncode=0)
            config = {'protocol': 'openai', 'endpoint': 'http://127.0.0.1:8100/v1/chat/completions',
                      'served_model': 'local', 'max_output_tokens': 512}
            with patch('llm_eval.livebench.invoke', side_effect=invocation), patch('llm_eval.livebench.subprocess.run', side_effect=execute):
                run_livebench(config, state, ['coding'], data, '2026-06-25', out, image='grader', backend=backend())
            self.assertEqual(events, ['start', 'generate', 'stop', 'grade'])
            self.assertTrue((out / 'source/livebench/data/live_bench/coding/task/test_cases_1.jsonl').exists())
            self.assertEqual(read_json(out / 'livebench-run.json')['status'], 'completed')

    def test_category_reports_weight_raw_requests_and_keep_benchmark_lanes_separate(self):
        with tempfile.TemporaryDirectory() as tmp:
            for benchmark in ['category-smoke', 'other']:
                folder = Path(tmp) / benchmark
                folder.mkdir()
                write_json(folder / 'metadata.json', {'synthetic': False, 'suite_sha256': 'a',
                           'benchmark': benchmark, 'category': 'coding', 'config':
                           {'model_id': 'x', 'platform': 'p', 'os_id': 'o', 'context_tokens': 4096}})
                rows = [{'task_id': 'a', 'warmup': False, 'status': 'ok', 'elapsed_s': 2, 'quality_pass': True, 'quality_check_applicable': True},
                        {'task_id': 'b', 'warmup': False, 'status': 'error', 'quality_check_applicable': True},
                        {'task_id': 'b', 'warmup': True, 'status': 'ok', 'quality_pass': True}]
                (folder / 'requests.jsonl').write_text('\n'.join(map(json.dumps, rows)))
            records = summarize(tmp, group_by='category')
            self.assertEqual(len(records), 2)
            self.assertTrue(all(r['requests'] == 2 and r['errors'] == 1 and r['smoke_check_pass_rate'] == .5 for r in records))
            write_report(tmp, Path(tmp) / 'report')
            self.assertTrue((Path(tmp) / 'report/category-summary.csv').exists())


if __name__ == '__main__':
    unittest.main()
