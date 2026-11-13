"""The legal examples plan without side effects, and the legal documents say what the code does.

Nothing here starts a campaign: planning is read-only, and every command line the documents show is only parsed by the
real argument parser, never executed. The host and human gates the documents describe stay open: their checklists are
checked to be present and unticked.
"""
import argparse
import contextlib
import importlib
import importlib.util
import io
import os
import re
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest.mock import patch

from llm_eval import readiness
from llm_eval.common import read_json
from llm_eval.orchestration import planner
from llm_eval.orchestration.planner import compile_campaign
import llm_eval.experiments.legal_benchmark as legal
from llm_eval.experiments.legal_benchmark import profiles, reporting

ROOT = Path(__file__).resolve().parents[1]
X = ROOT / 'experiments/legal-benchmark'
EXAMPLES = ROOT / 'configs/examples/legal'
HOSTS = {'windows': 'windows-11-native', 'wsl': 'windows-11-wsl2-ubuntu-26.04', 'ubuntu': 'ubuntu-26.04-native'}
# The two template campaigns of package E: their cases name REPLACE_WITH_... input files, so they do not plan.
TEMPLATES = {'score-campaign.json': (ValueError, 'Output manifest not found'),
             'routing-replay-campaign.json': (FileNotFoundError, 'REPLACE_WITH_EXPORTED_ROUTING_SUITE')}
WALKTHROUGH = ROOT / 'docs/LEGAL_BENCHMARK_WALKTHROUGH.md'
VALIDATION = ROOT / 'docs/VALIDATION.md'
NEW_EXPERIMENT = ROOT / 'docs/NEW_EXPERIMENT.md'
X_README = X / 'README.md'
DIAGRAM = ROOT / 'diagrams/legal-benchmark-workflow'
# Documents this package adds or changes.
DOCUMENTS = ('docs/LEGAL_BENCHMARK_WALKTHROUGH.md', 'docs/NEW_EXPERIMENT.md', 'docs/RESULTS.md', 'docs/VALIDATION.md', 'docs/READINESS.md',
             'README.md', 'experiments/legal-benchmark/README.md', 'configs/examples/legal/README.md', 'diagrams/legal-benchmark-workflow.md')
# The legal part of each document (None: the whole document).
LEGAL_PARTS = {'docs/LEGAL_BENCHMARK_WALKTHROUGH.md': None, 'docs/VALIDATION.md': '## Legal benchmark (issue 45)',
               'docs/RESULTS.md': '## Legal benchmark reports', 'docs/READINESS.md': '## Legal benchmark campaigns',
               'configs/examples/legal/README.md': None}
# Every optional plugin attribute the shared code reads from the legal plugin.
HOOKS = ('input_files', 'setup_platforms', 'reporting_policy', 'host_requirements', 'data_policy', 'attempt_receipt', 'report_projection',
         'verify_publication', 'claims_benchmark', 'claims_bundle', 'PROTECTED_PATHS', 'GENERIC_RANKING')
STAGES = ('Offload calibration', 'Locked serving profile', 'Routing calibration and replay', 'Frozen legal evaluation', 'Local report')
# Gated plan requirements: one key phrase per row of the table in docs/VALIDATION.md and per item of the walkthrough.
GATED = ('Managed serving', 'hosted decision arm', 'Tev1 and Nimble', 'verifier cascade', 'DOCX, PDF and OCR', 'five gates',
         'eCFR, LegalReasonBench and Harvey', '12 calibration and 24 evaluation', 'policy profile', 'Validated human or judge scoring',
         'Publication of any legal result', 'private pilot')
GATE_SECTIONS = ((WALKTHROUGH, None, '## Human rubric review checklist'), (VALIDATION, '## Legal benchmark (issue 45)', '### Independent engineer review'),
                 (VALIDATION, '## Legal benchmark (issue 45)', '### Qualified legal reviewer'),
                 (VALIDATION, '## Legal benchmark (issue 45)', '### Target-host acceptance'))
HOST_CELLS = ('Windows 11 native', 'WSL2 Ubuntu 26.04', 'Native Ubuntu 26.04')
# Sentences copied verbatim from the plan of issue 45, which is not part of the repository: the documents may quote them.
PLAN_SENTENCES = ('No authorization to access private matter inputs or publish a results bundle is implied by this plan.',
                  'Do not run models on actual prosecution decisions or automate filing, charging, contact or evidence disclosure.',
                  'No public results promotion from private inputs, even aggregate metrics.', 'Run one campaign at a time on the Raider.',
                  'Software smoke is complete at A, the public pilot only when A–G gates are evidenced, and a private pilot is a separate decision.')
PLAN_QUOTES = PLAN_SENTENCES + (
    'Proposed first measurements and stop criteria', 'No fabricated or ineligible authority may be marked supported in fixture acceptance',
    'Require explicit external versus managed mode.',
    'An optional hosted Jev arm requires separately approved public-only inputs, a pinned endpoint/model and the same calibration/abstention checks.',
    'Start with a rule and fixed model, add Tev1/Nimble SystemOne after protocol and memory qualification.',
    'Only then compare generators or a verifier cascade.', 'Enable DOCX/PDF text extraction only through optional pinned dependencies.',
    'Make scan/OCR a deliberate later capability with original-page anchoring and human verification of material excerpts.',
    'First import one released public diagnostic only after dataset bytes, license, jurisdiction, split and grader expectations are verified.',
    'Prefer a temporal eCFR release if accessible.', 'Keep LegalReasonBench/Harvey packet imports as optional separate adapters.',
    'Use a proposed 12 calibration matter families and 24 untouched evaluation families, balanced across supported, contradicted and incomplete '
    'scenarios, with matched dated/venue/evidence variants.',
    'Use a counsel-supplied policy profile for any operative jurisdiction or prosecutorial standard.',
    'Treat semantic entailment, admissibility, defense arguments and sufficiency as separate rubric dimensions requiring validated human/judge scoring.',
    'Phase 3 private matter requires its own operator and counsel approval, local-only staging, and an independently tested publication/transport gate.')
# Messages the code builds at run time around an experiment id, mapped to the fixed part a document's message must contain.
BUILT = {'Publication is not available for legal-benchmark: automatic_publication_unavailable': 'Publication is not available for ',
         'Publication is not available for legal-benchmark: <code>': 'Publication is not available for ',
         'Publication identity mismatch: the bundle carries content of legal-benchmark (<class>)': 'Publication identity mismatch: the bundle carries content of ',
         'Publication identity mismatch: the bundle carries content of legal-benchmark (text file)': 'Publication identity mismatch: the bundle carries content of ',
         'Publication identity mismatch: the campaign record names legal-benchmark': 'Publication identity mismatch: the campaign record names '}
LEGAL_DOCUMENTS = ('docs/LEGAL_BENCHMARK_WALKTHROUGH.md', 'experiments/legal-benchmark/README.md', 'configs/examples/legal/README.md')
ENTRY = re.compile(r'(llm-eval |python -m llm_eval|python scripts/readiness\.py|bash scripts/readiness\.sh|powershell -NoProfile -File \.\\scripts\\readiness\.ps1)')
# A number next to a rate or score word reads as a measurement.
MEASURED = re.compile(r'\d[\d.,]*\s*(?:tok/s|tokens? per second|seconds?\b)|(?:tok/s|tokens per second|accuracy|latency)\D{0,30}\d', re.I)
TICKED = re.compile(r'^\s*(?:[-*+]|\d+[.)])\s*\[\s*[xX✓✔]\s*\]', re.M)
# A closed list of phrasings that would record a human gate as passed. It catches "approved", "signed off", "accepted",
# "passed" or "reviewed" followed, within the sentence, by "on" or "by" and a date or a capitalised name; it does not catch
# every possible wording (for example "the review is complete").
GATE_CLAIM = re.compile(r'\b(?i:approved|signed off|accepted|passed|reviewed)\b[^.\n]{0,40}?\b(on|by)\s+(\d{4}-\d{2}-\d{2}|[A-Z][a-z]+)')
NUMBER_WORDS = {'three': 3, 'four': 4, 'five': 5, 'six': 6, 'ten': 10}


def text(path):
    return Path(path).read_text(encoding='utf-8')


def source():
    """The package source, plus the test modules and their names (a document may name a test)."""
    files = sorted((ROOT / 'src/llm_eval').rglob('*.py')) + sorted((ROOT / 'tests').glob('test_*.py'))
    return '\n'.join([text(p) for p in files] + [p.stem for p in files])


def section(document, heading):
    """The lines of one `## ` section (with its subsections), from its heading to the next `## ` heading."""
    lines = text(document).splitlines()
    start = lines.index(heading)
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith('## ')), len(lines))
    return '\n'.join(lines[start:end])


def subsection(body, heading):
    lines = body.splitlines()
    start = lines.index(heading)
    end = next((i for i in range(start + 1, len(lines)) if re.match(r'#{2,3} ', lines[i])), len(lines))
    return '\n'.join(lines[start:end])


def legal_part(name):
    heading = LEGAL_PARTS[name]
    return text(ROOT / name) if heading is None else section(ROOT / name, heading)


def fences(body):
    """(language, first line index, lines) of every fenced block of a text."""
    lines, out, i = body.splitlines(), [], 0
    while i < len(lines):
        match = re.match(r'\s*```(\w*)\s*$', lines[i])
        if match:
            end = next(j for j in range(i + 1, len(lines)) if lines[j].strip().startswith('```'))
            out.append((match.group(1), i, lines[i + 1:end]))
            i = end
        i += 1
    return out


def prose(body):
    """The lines of a text outside its fenced blocks."""
    inside, out = False, []
    for line in body.splitlines():
        if re.match(r'\s*```', line):
            inside = not inside
            continue
        if not inside:
            out.append(line)
    return out


def slug(heading):
    value = heading.strip().lower().replace('`', '')
    value = re.sub(r'[^\w\- ]', '', value)
    return value.replace(' ', '-')


def anchors(path):
    return {slug(re.sub(r'^#+ ', '', l)) for l in prose(text(path)) if re.match(r'#{1,6} ', l)}


def commands(body):
    """(command line, inline) of every documented command: fenced lines of any language (with `$ ` or `PS> ` prompts and
    `\\` continuations) and inline code spans that start with an entry point."""
    found = []
    for _, _, lines in fences(body):
        joined = []
        for line in lines:
            if joined and joined[-1].endswith('\\'):
                joined[-1] = joined[-1][:-1] + ' ' + line.strip()
            else:
                joined.append(line.strip())
        for line in joined:
            line = re.sub(r'^(\$|PS>)\s+', '', line)
            if ENTRY.match(line):
                found.append((line, False))
    for span in re.findall(r'`([^`\n]+)`', '\n'.join(prose(body))):
        if re.match(r'(llm-eval |python -m llm_eval)', span + ' '):
            found.append((span, True))
    return found


def example_campaigns():
    found = sorted(EXAMPLES.rglob('*campaign.json'))
    return [ROOT / 'campaigns/legal-smoke.json'] + [p for p in found if not (p.parent == EXAMPLES and p.name in TEMPLATES)]


def listing():
    """The repository's top level and every directory planning could write to: configurations, experiments, campaigns, results."""
    paths = [p for p in ROOT.iterdir() if p.name != '.git']
    for name in ('configs', 'experiments', 'campaigns', 'results'):
        if (ROOT / name).is_dir():
            paths += list((ROOT / name).rglob('*'))
    return sorted(p.relative_to(ROOT).as_posix() for p in paths)


def generic_targets(host):
    return read_json(ROOT / 'configs/examples' / ('raider-' + host) / 'inventory.json')['targets']


class Parsed(Exception):
    """Raised by the patched parser after a command line parsed: nothing behind the parser runs."""


def parse(argv):
    """Parse one documented command line with the real parser of its entry point; never execute it. Optional-argument
    brackets of a usage line (`[--flag VALUE]`) are dropped first."""
    original = argparse.ArgumentParser.parse_args

    def stop(self, args=None, namespace=None):
        raise Parsed(original(self, args, namespace))
    argv = argv.replace('[', ' ').replace(']', ' ')
    words = shlex.split(argv.replace('\\', '/') if argv.startswith('powershell') else argv)
    if words[:1] == ['llm-eval']:
        words = ['python', '-m', 'llm_eval'] + words[1:]
    if words[:2] == ['bash', 'scripts/readiness.sh'] or words[:4] == ['powershell', '-NoProfile', '-File', './scripts/readiness.ps1']:
        return readiness.parser().parse_args(words[2:] if words[0] == 'bash' else words[4:])
    if words[:2] == ['python', 'scripts/readiness.py']:
        return readiness.parser().parse_args(words[2:])
    if words[:2] != ['python', '-m']:
        raise AssertionError('Not a documented entry point: ' + argv)
    module, args = words[2], words[3:]
    if module == 'llm_eval':      # the real dispatch of the entry point to its campaign, reporting or legacy parser
        from llm_eval.cli import main

        def run():
            with patch.object(sys, 'argv', ['llm-eval', *args]):
                main()
    elif module.startswith('llm_eval.experiments.legal_benchmark.'):
        run = lambda: importlib.import_module(module).main(args)
    else:
        raise AssertionError('Not a documented entry point: ' + argv)
    with patch.object(argparse.ArgumentParser, 'parse_args', stop), contextlib.redirect_stdout(io.StringIO()):
        try:
            run()
        except Parsed as parsed:
            return parsed.args[0]
    raise AssertionError('The parser did not run: ' + argv)


class ExampleTests(unittest.TestCase):
    def test_every_legal_example_campaign_plans_without_publication(self):
        campaigns = example_campaigns()
        self.assertEqual(len(campaigns), 6)      # the smoke, the two shipped examples that plan, and the three per-host campaigns
        host = generic_targets('windows')['raider']['physical_host_id']
        before = listing()
        for path in campaigns:
            with self.subTest(path.relative_to(ROOT).as_posix()):
                plan = compile_campaign(path, ROOT)
                self.assertEqual(plan['reporting'].get('publish', {}).get('mode', 'none'), 'none')
                self.assertTrue(plan['jobs'])
                for job in plan['jobs']:      # the same host lock as every other Raider campaign
                    self.assertEqual(job['resources'], [host])
        for name, (error, message) in TEMPLATES.items():
            with self.subTest(name):
                self.assertEqual(read_json(EXAMPLES / name)['reporting']['publish']['mode'], 'none')
                with self.assertRaisesRegex(error, re.escape(message)):
                    compile_campaign(EXAMPLES / name, ROOT)
        self.assertEqual(listing(), before)

    def test_inventories_mirror_the_generic_raider_inventories(self):
        for host in HOSTS:
            with self.subTest(host):
                mine = read_json(EXAMPLES / ('raider-' + host) / 'inventory.json')
                theirs = read_json(ROOT / 'configs/examples' / ('raider-' + host) / 'inventory.json')
                self.assertEqual(mine['targets'], theirs['targets'])      # target name, physical_host_id and lock_root
                self.assertEqual(mine['hardware_configs'], theirs['hardware_configs'])
        # Windows native and WSL: one host id; the WSL lock directory is the one its walkthrough tells the operator to share.
        self.assertEqual(generic_targets('windows')['raider']['physical_host_id'], generic_targets('wsl')['raider']['physical_host_id'])
        # The stage files at the top of the directory use the generic Windows target too.
        self.assertEqual(read_json(EXAMPLES / 'inventory.json')['targets'], generic_targets('windows'))
        separate = read_json(EXAMPLES / 'inventory-separate-service.json')['targets']['raider']
        self.assertEqual({k: v for k, v in separate.items() if k != 'resource_hosts'}, generic_targets('windows')['raider'])

    def test_per_host_examples_follow_the_shipped_evaluation(self):
        shipped = read_json(EXAMPLES / 'evaluation-campaign.json')
        for host, os_id in HOSTS.items():
            with self.subTest(host):
                directory = EXAMPLES / ('raider-' + host)
                self.assertEqual(sorted(p.name for p in directory.iterdir()), ['inventory.json', 'legal-evaluation-campaign.json'])
                for p in directory.iterdir():
                    self.assertNotIn(b'\r', p.read_bytes())
                campaign = read_json(directory / 'legal-evaluation-campaign.json')
                self.assertEqual(campaign['reporting']['publish']['mode'], 'none')
                self.assertEqual([(p['id'], p.get('depends_on')) for p in campaign['phases']], [(p['id'], p.get('depends_on')) for p in shipped['phases']])
                plan = compile_campaign(directory / 'legal-evaluation-campaign.json', ROOT)
                self.assertEqual([(j['mode'], j['hardware']['os_id'], j['hardware_config_id']) for j in plan['jobs']],
                                 [(m, os_id, 'raider-' + host) for m in ('retrieval', 'generation', 'workflow')])
                for job in plan['jobs']:
                    self.assertEqual(Path(job['parameters']['suite']), (X / 'workloads/original-smoke/suite.lock.json').resolve())
                    for role in job['parameters'].get('roles', {}).values():
                        self.assertIn('REPLACE_WITH_', role['model_revision'])      # check_revisions stops a run before any request
                        with self.assertRaisesRegex(ValueError, 'Record the exact loaded model revision before evaluating'):
                            profiles.check_revisions({'generator': role})
                        self.assertRegex(role['endpoint'], r'^http://127\.0\.0\.1:\d+/')

    def test_existing_example_campaigns_are_untouched(self):
        for host, os_id in HOSTS.items():
            selection = readiness.select(readiness.parser().parse_args(['--campaign', str(ROOT / 'configs/examples' / ('raider-' + host) / 'campaign.json')]), ROOT)
            self.assertEqual(selection['os_id'], os_id)
            self.assertEqual([name for name, _ in selection['runtimes']], ['ollama'])
        plan = compile_campaign(ROOT / 'campaigns/routing-smoke.json', ROOT)
        self.assertEqual([(j['experiment_id'], j['mode'], j['status'], j['parameters'].get('synthetic')) for j in plan['jobs']],
                         [('llm-routing', 'decision', 'planned', True)])
        self.assertEqual(plan['reporting'], {'on_experiment_end': True})

    def test_readiness_derives_no_runtime_for_legal_jobs(self):
        for host, os_id in HOSTS.items():
            with self.subTest(host):
                path = EXAMPLES / ('raider-' + host) / 'legal-evaluation-campaign.json'
                selection = readiness.select(readiness.parser().parse_args(['--campaign', str(path)]), ROOT)
                self.assertEqual((selection['os_id'], selection['runtimes']), (os_id, {}))
                self.assertTrue(selection['needs_gpu'])      # the generation roles are GPU-served
        selection = readiness.select(readiness.parser().parse_args(['--campaign', str(ROOT / 'campaigns/legal-smoke.json')]), ROOT)
        self.assertEqual((selection['runtimes'], selection['needs_gpu']), ({}, False))

    def test_base_install_has_no_new_requirement(self):
        project = tomllib.loads(text(ROOT / 'pyproject.toml'))['project']
        self.assertEqual(project['dependencies'], [])
        self.assertEqual(sorted(project['optional-dependencies']), ['reporting', 'telemetry'])
        # A child interpreter: in this process the modules are imported already, so blocking the names here would prove nothing.
        code = ('import sys\n'
                "for name in ('psutil', 'matplotlib', 'pypdf', 'docx'):\n"
                '    sys.modules[name] = None\n'
                'import importlib, pkgutil\n'
                'import llm_eval.experiments.legal_benchmark as package\n'
                'names = sorted(m.name for m in pkgutil.iter_modules(package.__path__))\n'
                'for name in names:\n'
                "    importlib.import_module(package.__name__ + '.' + name)\n"
                "print(' '.join(names))\n")
        env = {**os.environ, 'PYTHONPATH': str(ROOT / 'src')}
        done = subprocess.run([sys.executable, '-c', code], cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn('reporting', done.stdout.split())
        self.assertIn('workflow', done.stdout.split())

    def test_planning_needs_no_network(self):
        def refuse(*args, **kwargs):
            raise AssertionError('planning opened a socket')
        with patch.object(socket, 'socket', refuse), patch.object(socket, 'create_connection', refuse):
            for path in example_campaigns():
                with self.subTest(path.relative_to(ROOT).as_posix()):
                    compile_campaign(path, ROOT)


class DocumentationTests(unittest.TestCase):
    def test_mode_table_and_hook_table_match_the_code(self):
        readme = text(X_README)
        rows = re.findall(r'^\| `([a-z]+)` \| ([a-z ]+) \| (.+) \|$', readme, re.M)
        self.assertEqual([m for m, _, _ in rows], legal.MANIFEST['modes'])
        self.assertEqual({state for _, state, _ in rows}, {'implemented'})
        # The report clause of each row, against what reporting_policy gives for a planned job of the mode.
        for mode, _, what in rows:
            if mode == 'smoke':
                self.assertTrue(what.endswith('→ local report'), what)
            else:
                self.assertTrue(what.endswith('. Local report: cohort aggregates only'), what)
        planned = compile_campaign(ROOT / 'campaigns/legal-smoke.json', ROOT)['jobs'] + compile_campaign(EXAMPLES / 'evaluation-campaign.json', ROOT)['jobs']
        self.assertEqual(sorted(j['mode'] for j in planned), ['generation', 'retrieval', 'smoke', 'workflow'])
        for job in planned:
            policy = reporting.reporting_policy([job])
            self.assertEqual((job['mode'], policy['report'], policy['publish']), (job['mode'], True, False))
        self.assertIs(legal.MODE_MODULES['score'], 'grading')      # score reports through the same projection (PAIRED_MODES)
        self.assertIn('score', reporting.PAIRED_MODES)
        self.assertNotIn('Task A', readme)
        guide = text(NEW_EXPERIMENT)
        table = re.findall(r'^\| `(\w+)', guide, re.M)
        for hook in HOOKS:
            self.assertTrue(hasattr(legal, hook), hook)
            self.assertIn(hook, table)
        # Every optional attribute the shared code reads from a plugin has its row (no hook is silently undocumented).
        shared = '\n'.join(text(p) for p in sorted((ROOT / 'src/llm_eval').rglob('*.py')) if 'legal_benchmark' not in p.parts)
        read = set(re.findall(r"plugin_hook\([^,()]+(?:\([^()]*\))?[^,()]*,\s*'(\w+)'\)", shared))
        read |= set(re.findall(r"getattr\(get_experiment\([^()]*\),\s*'(\w+)'", shared))
        self.assertTrue(read)
        self.assertLessEqual(read, set(HOOKS) | {'data_policy'})
        self.assertLessEqual(read, set(table))
        for key in planner.PATH_KEYS:
            self.assertIn('`' + key + '`', guide, key)

    def test_walkthrough_names_every_stage_output_and_control(self):
        walkthrough = text(WALKTHROUGH)
        for phrase in (*STAGES, 'serving-profile', 'output-manifest', 'routing calibrate', 'routing verify', 'approved-suites.json',
                       'llm-eval status', 'llm-eval resume', 'llm-eval cancel', '--retry-failed', 'fictional', 'raider` host lock',
                       '![Legal benchmark stages from offload calibration to the local report.](../diagrams/legal-benchmark-workflow.png)'):
            self.assertIn(phrase, walkthrough)
        for heading in ('## What this walkthrough runs', '## Status, resume and cancel', '## Roles', '## Source permissions', '## Trust boundaries',
                        '## Human rubric review checklist', '## Repeatable acceptance command sequence', '## What is not covered'):
            self.assertIn(heading, walkthrough.splitlines())
        for sentence in PLAN_SENTENCES[:4]:
            self.assertIn(sentence, walkthrough)

    def test_every_documented_command_line_parses(self):
        found = {name: commands(text(ROOT / name)) for name in DOCUMENTS}
        legal_lines = [line for name in ('docs/LEGAL_BENCHMARK_WALKTHROUGH.md', 'configs/examples/legal/README.md') for line, _ in found[name]]
        self.assertGreater(len(legal_lines), 25)
        for name, lines in found.items():
            for line, inline in lines:
                with self.subTest(document=name, line=line):
                    if inline and ' --' not in line:      # a command named in prose: its subcommand must exist
                        with self.assertRaises(SystemExit) as stopped, contextlib.redirect_stdout(io.StringIO()):
                            parse(line + ' --help')
                        self.assertEqual(stopped.exception.code, 0)
                        continue
                    parse(line)
                    if name in LEGAL_DOCUMENTS or 'legal' in line:      # what a legal command line may not do
                        self.assertNotIn('--publish-pr', line)
                        words = shlex.split(line.replace('\\', '/'))
                        for flag, value in zip(words, words[1:]):
                            if flag in ('--output', '--json-output'):
                                self.assertFalse(value.startswith(('results', 'docs/results', './results', './docs/results')), line)
        for command in ('profiles freeze', 'routing export', 'routing replay', 'routing verify', 'routing evaluate', 'routing calibrate',
                        'grading packet', 'llm-eval plan', 'llm-eval setup', 'llm-eval run', 'llm-eval status',
                        'llm-eval resume', 'llm-eval cancel', 'llm-eval report', 'bash scripts/readiness.sh'):
            self.assertTrue(any(command in l for l in legal_lines), command)
        for name in LEGAL_PARTS:      # no documented shell line edits an inventory or its host id
            for _, _, lines in fences(legal_part(name)):
                for line in lines:
                    self.assertNotRegex(line, r'inventory\.json|physical_host_id|lock_root', (name, line))

    def test_documented_codes_and_messages_exist_in_the_code(self):
        code = source()
        readme = text(X_README)
        headings = {re.sub(r'^#+ ', '', l) for name in DOCUMENTS for l in prose(text(ROOT / name)) if re.match(r'#{1,6} ', l)}
        for name in DOCUMENTS:
            body = '\n'.join(prose(text(ROOT / name)))
            for token in sorted(set(re.findall(r'`([a-z][a-z0-9]*(?:_[a-z0-9]+)+)(?=[`:.\s(])', body))):
                with self.subTest(document=name, token=token):
                    self.assertTrue(re.search(r'\b' + re.escape(token) + r'\b', code), token)
            # Not checked: command lines (they contain `--`) and the unittest result lines quoted as evidence (`Ran N tests ...`, `OK ...`).
            messages = {m for m in re.findall(r'`([A-Z][^`]* [^`]*)`', body) if '--' not in m and not re.match(r'Ran \d+ tests|OK\b', m)}
            for message in sorted(messages):
                with self.subTest(document=name, message=message):
                    fixed = BUILT.get(message, message.split('<')[0])
                    self.assertTrue(fixed.strip())
                    self.assertTrue(fixed in code, fixed)
            for quoted in sorted(set(re.findall(r'"([A-Z][^"\n]+)"', re.sub(r'`[^`\n]*`', '', body)))):
                if len(quoted.split()) < 3:
                    continue
                with self.subTest(document=name, quoted=quoted):
                    self.assertTrue(quoted in code or quoted in readme or quoted in PLAN_QUOTES or quoted in headings, quoted)
            for words in re.findall(r'fewer than (\w+) distinct matters', body):
                self.assertEqual(int(words) if words.isdigit() else NUMBER_WORDS[words], reporting.MIN_COHORT, name)
            for line in body.splitlines():      # the publication codes, wherever several are listed, in the order the code checks them
                listed = [c for c in re.findall(r'`(\w+)`', line) if c in reporting.PUBLICATION]
                if len(listed) >= 3:
                    self.assertEqual(listed, [c for c in reporting.PUBLICATION if c in listed], (name, line))

    def test_quotes_are_verbatim(self):
        readme = text(X_README)
        for name in DOCUMENTS:
            if name == 'experiments/legal-benchmark/README.md':
                continue
            body = text(ROOT / name)
            for quote in re.findall(r'^\s*> (.+)$', body, re.M):      # block quotes are quotes of the experiment README
                with self.subTest(document=name, quote=quote[:60]):
                    self.assertIn(quote, readme)
            for sentence in PLAN_SENTENCES:      # wherever a plan sentence starts, the whole sentence follows byte for byte
                prefix = ' '.join(sentence.split()[:3])
                for match in re.finditer(re.escape(prefix), body):
                    with self.subTest(document=name, sentence=prefix):
                        self.assertEqual(body[match.start():match.start() + len(sentence)], sentence)

    def test_documents_mark_host_measurements_pending(self):
        walkthrough = text(WALKTHROUGH)
        self.assertIn('Host measurements are pending.', walkthrough)
        for name in LEGAL_PARTS:
            part = legal_part(name)
            lines = part.splitlines()
            for language, start, block in fences(part):
                if any(re.search(r'\d', l) for l in block):
                    with self.subTest(document=name, block=start):
                        self.assertTrue(any('illustrative' in l.lower() for l in lines[max(0, start - 3):start]), lines[max(0, start - 3):start])
            for line in prose(part):
                with self.subTest(document=name, line=line[:60]):
                    self.assertNotRegex(line, MEASURED)
        legal_section = section(VALIDATION, '## Legal benchmark (issue 45)')
        hosts = subsection(legal_section, '### Host readiness and acceptance')
        rows = [l for l in hosts.splitlines() if l.startswith('|') and not l.startswith(('| Host cell', '|---'))]
        self.assertEqual([r.split('|')[1].strip() for r in rows], list(HOST_CELLS))
        for row in rows:
            cells = [c.strip() for c in row.strip('|').split('|')][1:]
            self.assertEqual((len(cells), set(cells)), (4, {'`not run`'}), row)
        measured = subsection(legal_section, '### What was not measured')
        rows = [l for l in measured.splitlines() if l.startswith('|') and not l.startswith(('| Stage', '|---'))]
        self.assertEqual([r.split('|')[1].strip() for r in rows], ['Windows fit', 'Retrieval and drafting', 'Routing', 'WSL2 and native Ubuntu 26.04'])
        for row in rows:
            self.assertEqual(row.split('|')[2].strip(), 'pending (host)', row)

    def test_gate_checklists_are_present_and_unchecked(self):
        for name in DOCUMENTS:
            body = text(ROOT / name)
            self.assertIsNone(TICKED.search(body), name)
            self.assertIsNone(re.search(r'<input[^>]*\bchecked\b', body, re.I), name)
        for document, outer, heading in GATE_SECTIONS:
            body = section(document, heading) if outer is None else subsection(section(document, outer), heading)
            items = [l for l in body.splitlines() if re.match(r'\s*(?:[-*+]|\d+[.)])\s', l)]
            with self.subTest(heading):
                self.assertGreaterEqual(len(items), 4)
                for item in items:
                    self.assertTrue(item.startswith('- [ ] '), item)
                for line in prose(body):
                    self.assertNotRegex(line, GATE_CLAIM)
        legal_section = section(VALIDATION, '## Legal benchmark (issue 45)')
        self.assertIn('single active large model', subsection(legal_section, '### Target-host acceptance'))
        self.assertIn('reviewer_token', section(WALKTHROUGH, '## Human rubric review checklist'))
        self.assertIn(PLAN_SENTENCES[4], legal_section)

    def test_gated_plan_requirements_are_listed_by_name(self):
        legal_section = section(VALIDATION, '## Legal benchmark (issue 45)')
        table = subsection(legal_section, '### Gated plan requirements')
        rows = [l for l in table.splitlines() if l.startswith('| ') and not l.startswith('| Plan requirement') and not l.startswith('|---')]
        self.assertEqual(len(rows), len(GATED))
        for phrase, row in zip(GATED, rows):
            self.assertIn(phrase, row)
            quoted = re.findall(r'"([^"]+)"', row.split('|')[2])
            self.assertTrue(quoted and all(q in PLAN_QUOTES for q in quoted), row)
        uncovered = section(WALKTHROUGH, '## What is not covered')
        for phrase in GATED:
            self.assertIn(phrase, uncovered)
        self.assertIs(profiles.MANAGED_SERVING_ENABLED, False)
        with self.assertRaisesRegex(ValueError, 'Managed serving of legal roles is gated'):
            profiles.validate_role({'role': 'generator', 'serving': 'managed', 'capability': 'chat', 'platform': 'ollama', 'model': 'm',
                                    'model_revision': 'r'}, 'generator')

    def test_relative_links_and_anchors_resolve(self):
        for name in DOCUMENTS:
            path = ROOT / name
            for target in re.findall(r'\]\(([^)\s]+)\)', '\n'.join(prose(text(path)))):
                if re.match(r'[a-z]+:', target):
                    continue
                with self.subTest(document=name, link=target):
                    file, _, fragment = target.partition('#')
                    resolved = (path.parent / file) if file else path
                    self.assertTrue(resolved.exists())
                    if fragment:
                        self.assertIn(fragment, anchors(resolved))

    def test_no_matter_id_of_an_approved_suite_appears(self):
        ids = set()
        for lock in ('original-smoke', 'original-packets'):
            ids |= {m['matter_id'] for m in read_json(X / 'workloads' / lock / 'matters.json')['matters']}
        self.assertGreater(len(ids), 10)
        for name in DOCUMENTS:
            body = text(ROOT / name)
            for matter in sorted(ids):
                self.assertNotRegex(body, r'(?<![\w-])' + re.escape(matter) + r'(?![\w-])', name)

    def test_diagram_source_and_rendering_exist(self):
        source_text = text(DIAGRAM.with_suffix('.md'))
        self.assertEqual(source_text.count('```mermaid'), 1)
        self.assertIn('flowchart TD', source_text)
        self.assertIn('[View PNG rendering](legal-benchmark-workflow.png).', source_text)
        for stage in STAGES:
            self.assertIn(stage, source_text)
        edges = set(re.findall(r'^\s+(\w+) -\.?-> (\w+)$', source_text, re.M))
        # The profile goes straight to the evaluation; stage 3 is optional and feeds only the calibration file; the output
        # manifest feeds score; the replay manifest feeds nothing in the evaluation.
        self.assertLessEqual({('locked', 'evaluation'), ('locked', 'routing'), ('routing', 'calibration'), ('routing', 'replay'),
                              ('calibration', 'evaluation'), ('manifest', 'score')}, edges)
        self.assertNotIn(('replay', 'evaluation'), edges)
        self.assertIn('calibration -.-> evaluation', source_text)
        self.assertRegex(source_text, r'routing\["[^"]*optional')
        data = DIAGRAM.with_suffix('.png').read_bytes()
        self.assertTrue(data.startswith(b'\x89PNG\r\n\x1a\n'))
        for name in DOCUMENTS:
            if name.endswith('.md') and not name.startswith('diagrams/'):
                self.assertNotIn('```mermaid', text(ROOT / name), name)
        if importlib.util.find_spec('matplotlib') is None:
            self.skipTest('matplotlib is not installed (the reporting extra); the rendering was not compared')
        # Re-render into a temporary copy: the Mermaid source byte for byte, the PNG pixel for pixel within a small
        # tolerance (font rasterisation differs slightly between matplotlib builds).
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp)
            (copy / 'scripts').mkdir()
            (copy / 'diagrams').mkdir()
            shutil.copy(ROOT / 'scripts/render_legal_diagram.py', copy / 'scripts')
            done = subprocess.run([sys.executable, str(copy / 'scripts/render_legal_diagram.py')], capture_output=True, text=True, timeout=300)
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertEqual((copy / 'diagrams/legal-benchmark-workflow.md').read_bytes(), DIAGRAM.with_suffix('.md').read_bytes())
            import matplotlib.image
            committed = matplotlib.image.imread(str(DIAGRAM.with_suffix('.png')))
            rendered = matplotlib.image.imread(str(copy / 'diagrams/legal-benchmark-workflow.png'))
            self.assertEqual(committed.shape, rendered.shape)
            self.assertLess(float(abs(committed - rendered).mean()), 0.02)

    def test_pinned_documentation_rows_survive(self):
        # tests.test_upstream_pins reads the LM Studio row of docs/READINESS.md; the acceptance sequence runs that module too.
        version = read_json(ROOT / 'catalog/installers.json')['platforms']['lmstudio']['version']
        readiness_doc = text(ROOT / 'docs/READINESS.md')
        self.assertIn('`ElementLabs.LMStudio --version ' + version + '`', readiness_doc)
        self.assertEqual(readiness_doc.count('ElementLabs.LMStudio --version'), 1)
        self.assertIn('llm-eval run --config FILE', text(ROOT / 'README.md'))      # the legacy entry point stays documented


if __name__ == '__main__':
    unittest.main()
