"""Offline tests for scripts/model_discovery.py.

Every upstream is scripted by FakeNet: the GitHub git API of a fake leaderboard repository
(real git blob sha1s computed by the fixture builder), Hugging Face listings, model info and
revision answers. The calibration tables are built from the rows recorded in
catalog/livebench-evidence.json; their sha256 cannot equal the recorded one, so each run uses a
fixture root whose copy of the evidence file carries the fixture hashes. The production check
(sha256 of the fetched blob == source_sha256) is unchanged.
"""
import ast
import base64
import contextlib
import csv
import datetime as dt
import email.message
import errno
import hashlib
import http.client
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import shutil
import ssl
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import urllib.error
import urllib.parse
import urllib.request
import urllib.response

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location('model_discovery', ROOT / 'scripts' / 'model_discovery.py')
md = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(md)

TODAY = '2026-11-08'
TODAY_DATE = dt.date.fromisoformat(TODAY)
# The owner edits catalog/model-discovery.json by hand with real dates: tests of the real file validate it as of the
# real date (never earlier than TODAY); fixture runs use the frozen FIXTURE_DISCOVERY below and --today TODAY.
REAL_TODAY = max(TODAY_DATE, dt.datetime.now(dt.timezone.utc).date())
MODELS = json.loads((ROOT / 'catalog/models.json').read_text(encoding='utf-8'))
EVIDENCE = json.loads((ROOT / 'catalog/livebench-evidence.json').read_text(encoding='utf-8'))
BENCH = json.loads((ROOT / 'catalog/benchmarks.json').read_text(encoding='utf-8'))
DISCOVERY = json.loads((ROOT / 'catalog/model-discovery.json').read_text(encoding='utf-8'))
BY_ID = {m['id']: m for m in MODELS['models']}
REPO = 'LiveBench/new-livebench'
REVIEWED = EVIDENCE['leaderboard_revision']
HEAD = hashlib.sha1(b'fixture head commit').hexdigest()
GITHUB = f'https://api.github.com/repos/{REPO}'
HF = 'https://huggingface.co/api/models'
GITHUB_RUN_VARS = ('GITHUB_RUN_ID', 'GITHUB_SERVER_URL', 'GITHUB_REPOSITORY')   # set by GitHub Actions in every step

# A frozen copy of the seeded catalog/model-discovery.json, so that fixture runs never depend on the owner's edits.
FIXTURE_PUBLISHERS = [
    {'prefixes': ['deepseek-'], 'hf_orgs': ['deepseek-ai']},
    {'prefixes': ['qwen', 'qwq-'], 'hf_orgs': ['Qwen']},
    {'prefixes': ['glm-'], 'hf_orgs': ['zai-org']},
    {'prefixes': ['mistral-', 'magistral-', 'devstral-', 'ministral-', 'codestral-', 'mixtral-'], 'hf_orgs': ['mistralai']},
    {'prefixes': ['phi-'], 'hf_orgs': ['microsoft']},
    {'prefixes': ['gemma-'], 'hf_orgs': ['google']},
    {'prefixes': ['llama-', 'meta-llama-'], 'hf_orgs': ['meta-llama']},
    {'prefixes': ['nemotron-', 'nvidia-', 'llama-3.1-nemotron-', 'llama-3.3-nemotron-'], 'hf_orgs': ['nvidia']},
    {'prefixes': ['gpt-oss-'], 'hf_orgs': ['openai']},
    {'prefixes': ['kimi-'], 'hf_orgs': ['moonshotai']},
    {'prefixes': ['grok-'], 'hf_orgs': ['xai-org']},
    {'prefixes': ['laguna-'], 'hf_orgs': ['poolside']},
    {'prefixes': ['minimax-'], 'hf_orgs': ['MiniMaxAI']},
    {'prefixes': ['olmo-'], 'hf_orgs': ['allenai']},
    {'prefixes': ['granite-'], 'hf_orgs': ['ibm-granite']},
    {'prefixes': ['hunyuan-'], 'hf_orgs': ['tencent']},
    {'prefixes': ['ernie-'], 'hf_orgs': ['baidu']},
    {'prefixes': ['seed-oss-'], 'hf_orgs': ['ByteDance-Seed']},
    {'prefixes': ['step-'], 'hf_orgs': ['stepfun-ai']},
    {'prefixes': ['ling-', 'ring-'], 'hf_orgs': ['inclusionAI']},
    {'prefixes': ['longcat-'], 'hf_orgs': ['meituan-longcat']},
    {'prefixes': ['command-', 'aya-'], 'hf_orgs': ['CohereLabs']},
]
SEEDED = [('lb:claude*', 'Anthropic Claude'), ('lb:gemini*', 'Google Gemini'), ('lb:gpt-4*', 'OpenAI GPT-4'),
          ('lb:gpt-5*', 'OpenAI GPT-5'), ('lb:chatgpt*', 'OpenAI ChatGPT'), ('lb:o1*', 'OpenAI o1'), ('lb:o3*', 'OpenAI o3'),
          ('lb:o4*', 'OpenAI o4'), ('lb:grok-3*', 'xAI Grok 3'), ('lb:grok-4*', 'xAI Grok 4')]
SEEDED_KEYS = [key for key, _ in SEEDED]
FIXTURE_DISCOVERY = {
    'schema_version': 1,
    'leaderboard': {'averaging_reviewed_revision': REVIEWED},
    'publishers': FIXTURE_PUBLISHERS,
    'decisions': [{'key': key, 'decision': 'not_open_weight', 'decided_on': TODAY,
                   'reason': f'{family}: closed API family with no published weights (fixture copy of the seeded entry)'}
                  for key, family in SEEDED],
}
# Fixture roots carry their own scorer file: only RELEASES is read (with ast), and its dates never move.
FIXTURE_RELEASES = ('2025-04-25', '2025-05-30', '2026-06-25')


def git_sha(data):
    return hashlib.sha1(b'blob %d\0' % len(data) + data).hexdigest()


# --- fixture tables ---------------------------------------------------------------------------
CATS_2025_04 = {
    'Reasoning': ['web_of_lies_v3', 'zebra_puzzle', 'spatial'],
    'Coding': ['LCB_generation', 'coding_completion'],
    'Mathematics': ['AMPS_Hard', 'math_comp', 'olympiad'],
    'Data Analysis': ['tablejoin', 'tablereformat', 'cta'],
    'Language': ['connections', 'plot_unscrambling', 'typos'],
    'IF': ['paraphrase', 'simplify', 'story_generation', 'summarize'],
}
CATS_2025_05 = {**CATS_2025_04, 'Agentic Coding': ['javascript', 'typescript', 'python']}
CATS_2026 = {('IF' if c['id'] == 'instruction_following' else c['name']): list(c['livebench_tasks']) for c in BENCH['categories']}
AVERAGING = b'export function averageScores(rows) { /* category means, then equal category weight */ }\n'


def cells(categories, spec):
    """{task: text}: a number fills every task; a dict maps a category (or a task) to a number or a raw cell."""
    if not isinstance(spec, dict):
        spec = {name: spec for name in categories}
    out = {}
    for name, tasks in categories.items():
        for task in tasks:
            value = spec.get(task, spec.get(name, ''))
            out[task] = value if isinstance(value, str) else repr(float(value))
    return out


def table(categories, rows, extra=('organization',), crlf=False):
    tasks = [t for ts in categories.values() for t in ts]
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator='\r\n' if crlf else '\n')
    writer.writerow(['model', *extra, *tasks])
    for lb_id, spec in rows:
        c = cells(categories, spec)
        writer.writerow([lb_id, *['fixture' for _ in extra], *[c[t] for t in tasks]])
    return buf.getvalue().encode('utf-8')


def as_json(obj):
    return (json.dumps(obj, indent=2) + '\n').encode('utf-8')


def recorded_rows(release):
    return [(r['leaderboard_model_id'], dict(r['category_scores'])) for r in EVIDENCE['recommendations'] if r['release'] == release]


FILLERS = [(f'filler-model-{i:02d}', 20.0 + i) for i in range(6)]
TABLE_2025_04 = table(CATS_2025_04, recorded_rows('2025-04-25') + FILLERS, extra=())
TABLE_2025_05 = table(CATS_2025_05, recorded_rows('2025-05-30') + FILLERS, extra=())
REVIEWED_2026 = table(CATS_2026, [('deepseek-v4.1-flash', 81.11), ('glm-5.3-flash', 71.59)] + FILLERS)

# The default head release: closed families on top, then rows the catalog already knows; nothing is reportable.
DEFAULT_ROWS = [
    ('claude-opus-5', 90.0), ('gemini-3-pro', 88.0), ('gpt-5.5-high', 86.0), ('o3-pro', 85.0),
    ('deepseek-v4.1-flash', 81.11), ('glm-5.3-flash', 71.59), ('qwen3.8-flash-next', 70.0), ('qwen3.8-27b-thinking', 68.0),
    ('glm-4.5-air', 60.53), ('phi-4-reasoning-plus', 56.64), ('deepseek-r1-distill-llama-70b', 55.51),
    ('gpt-oss-120b-high', 55.0), ('deepseek-r1-distill-qwen-32b', 47.52), ('mistral-small-2503', 45.92),
    ('gemma-4-31b-it', 45.0), ('llama-3.3-70b-instruct', 44.0), ('kimi-linear-48b-a3b-instruct', 43.0),
    ('qwen3.5-35b-a3b', 43.0), ('nemotron-3-nano-30b-a3b', 40.0), ('laguna-xs.2', 39.0),
    ('llama-3.1-70b-instruct', 38.0), ('phi-4', 37.0), ('gemma-3-27b-it', 36.0), ('kimi-dev-72b', 35.0),
]

EXTRA_REPOS = {
    'deepseek-ai': ['DeepSeek-V4.1-Flash', 'DeepSeek-R1', 'DeepSeek-R1-Distill-Qwen-7B', 'DeepSeek-R1-Distill-Qwen-32B-FP8'],
    'zai-org': ['GLM-5.3-Flash', 'GLM-4.5-Air-FP8', 'GLM-4.5-Air-Base', 'GLM-4.5'],
    'microsoft': ['Phi-4-reasoning', 'Phi-4-reasoning-plus-onnx'],
    'mistralai': ['Mistral-Small-3.1-24B-Base-2503', 'Mistral-Small-24B-Instruct-2501'],
    'Qwen': ['Qwen3.8-27B-FP8', 'Qwen3.8-27B-Base', 'Qwen3-Max-Preview'],
    'openai': ['gpt-oss-safeguard-20b'],
    'google': ['gemma-4-31B', 'gemma-3-27b-pt'],
    'meta-llama': ['Llama-3.1-70B'],
    'nvidia': ['NVIDIA-Nemotron-3-Super-120B-A12B-BF16', 'NVIDIA-Nemotron-3-Super-120B-A12B-FP8'],
}


def model_info(repo, total=40_000_000_000, params=None, license='apache-2.0', private=False, disabled=None, gated=False,
               files=4, license_file='LICENSE', card=None, tags=None, canonical=None, created='2026-10-01T08:00:00.000Z'):
    siblings = [{'rfilename': 'config.json'}, {'rfilename': 'README.md'}]
    siblings += [{'rfilename': f'model-{i:05d}-of-{files:05d}.safetensors'} for i in range(1, files + 1)]
    if license_file:
        siblings.append({'rfilename': license_file})
    if card is None:
        card = {'license': license} if license else {}
    doc = {'id': canonical or repo, 'sha': hashlib.sha1(('rev ' + (canonical or repo)).encode()).hexdigest(),
           'private': private, 'gated': gated, 'siblings': siblings, 'cardData': card, 'tags': tags or [],
           'createdAt': created,
           'safetensors': {'parameters': params or {'BF16': total}, 'total': total} if total else None}
    if disabled is not None:
        doc['disabled'] = disabled
    return doc


class World:
    """Scripted upstream: one fake leaderboard repository (two commits) and a fake Hugging Face."""

    def __init__(self, rows=DEFAULT_ROWS, categories=None):
        self.reviewed_files = {
            'README.md': b'# fixture leaderboard\n',
            'public/table_2025_04_25.csv': TABLE_2025_04, 'public/categories_2025_04_25.json': as_json(CATS_2025_04),
            'public/table_2025_05_30.csv': TABLE_2025_05, 'public/categories_2025_05_30.json': as_json(CATS_2025_05),
            'public/table_2026_06_25.csv': REVIEWED_2026, 'public/categories_2026_06_25.json': as_json(CATS_2026),
            'src/Table/Averaging.js': AVERAGING, 'src/App.js': b'// app\n',
        }
        self.head_files = dict(self.reviewed_files)
        self.head_files['public/table_2026_06_25.csv'] = table(categories or CATS_2026, rows)
        self.head_date = '2026-11-07T12:00:00Z'
        self.listings = {}
        for m in MODELS['models']:
            org, name = m['upstream_repo'].split('/')
            self.listings.setdefault(org, []).append(m['upstream_repo'])
        for org, names in EXTRA_REPOS.items():
            self.listings.setdefault(org, []).extend(f'{org}/{n}' for n in names)
        self.infos = {}
        self.revisions = {}
        for cid in md.HF_ANCHORS:
            meta = BY_ID[cid]['upstream_metadata']
            self.revisions[(meta['id'].casefold(), meta['sha'])] = {
                'id': meta['id'], 'sha': meta['sha'], 'private': False, 'gated': meta['gated'],
                'siblings': [{'rfilename': 'model.safetensors'}], 'safetensors': json.loads(json.dumps(meta['safetensors']))}
        self.errors = {}
        self.page_size = None
        self.tree_patches = []      # callables (commit label, path, tree doc) -> tree doc
        self.site = {}              # livebench.ai path -> (headers, body); anything else answers 404

    def add_model(self, repo, listed=True, **kw):
        self.infos[repo.casefold()] = model_info(repo, **kw)
        if listed:
            self.listings.setdefault(repo.split('/')[0], []).append(repo)
        return self.infos[repo.casefold()]

    # -- fixture root ------------------------------------------------------------------------
    def root(self, tmp, evidence=None, benchmarks=None, decisions=(), publishers=(), discovery=None, releases_extra=()):
        for rel in ('catalog/models.json', 'catalog/benchmarks.json', md.HARDWARE_CONFIG, md.NATIVE_PROFILE):
            (tmp / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / rel, tmp / rel)
        (tmp / md.SCORER_SOURCE).parent.mkdir(parents=True, exist_ok=True)
        releases = sorted(set(FIXTURE_RELEASES) | set(releases_extra))
        (tmp / md.SCORER_SOURCE).write_text('"""Fixture scorer: only RELEASES is read, with ast."""\nRELEASES = {'
                                            + ', '.join(repr(r) for r in releases) + '}\n', encoding='utf-8')
        if benchmarks:
            doc = json.loads((tmp / 'catalog/benchmarks.json').read_text(encoding='utf-8'))
            benchmarks(doc)
            (tmp / 'catalog/benchmarks.json').write_text(json.dumps(doc, indent=2) + '\n', encoding='utf-8')
        ev = json.loads(json.dumps(EVIDENCE))
        for rec in ev['recommendations']:
            rec['source_sha256'] = hashlib.sha256(self.reviewed_files[rec['source_table'].split(REVIEWED + '/', 1)[1]]).hexdigest()
        if evidence:
            evidence(ev)
        (tmp / 'catalog/livebench-evidence.json').write_text(json.dumps(ev, indent=2) + '\n', encoding='utf-8')
        doc = json.loads(json.dumps(FIXTURE_DISCOVERY if discovery is None else discovery))
        doc['decisions'] = doc.get('decisions', []) + list(decisions)
        doc['publishers'] = doc.get('publishers', []) + list(publishers)
        covered = {o.casefold() for p in doc['publishers'] for o in p['hf_orgs']}
        for org in sorted({m['upstream_repo'].split('/')[0] for m in MODELS['models']}, key=str.casefold):
            if org.casefold() not in covered:     # an org the catalog gained after the fixture copy was frozen
                doc['publishers'].append({'prefixes': [f'fixture-org-{org.lower()}-'], 'hf_orgs': [org]})
        (tmp / md.DISCOVERY_FILE).write_text(json.dumps(doc, indent=2) + '\n', encoding='utf-8')
        return tmp

    # -- git objects -------------------------------------------------------------------------
    def build(self):
        self.trees, self.blobs, self.commits = {}, {}, {}
        for label, sha, files, date in (('reviewed', REVIEWED, self.reviewed_files, '2026-10-01T09:00:00Z'),
                                        ('head', HEAD, self.head_files, self.head_date)):
            tree = self._tree(label, '', files)
            self.commits[sha] = {'sha': sha, 'commit': {'tree': {'sha': tree}, 'committer': {'date': date}}}
        self.commits['HEAD'] = self.commits[HEAD]

    def _tree(self, label, path, files):
        entries, subdirs = {}, {}
        for name, data in files.items():
            first, _, rest = name.partition('/')
            if rest:
                subdirs.setdefault(first, {})[rest] = data
            else:
                sha = git_sha(data)
                self.blobs[sha] = data
                entries[first] = {'path': first, 'mode': '100644', 'type': 'blob', 'sha': sha, 'size': len(data)}
        for name, sub in subdirs.items():
            entries[name] = {'path': name, 'mode': '040000', 'type': 'tree',
                             'sha': self._tree(label, f'{path}{name}/', sub)}
        doc = {'truncated': False, 'tree': sorted(entries.values(), key=lambda e: e['path'])}
        for patch in self.tree_patches:
            doc = patch(label, path, doc)
        sha = hashlib.sha1((label + path + json.dumps(doc, sort_keys=True)).encode()).hexdigest()
        doc['sha'] = sha
        self.trees[sha] = doc
        return sha

    def net(self):
        self.build()
        return FakeNet(self)


class FakeNet:
    def __init__(self, world):
        self.world = world
        self.calls = []
        self.counts = {}
        self.fail = {}             # url substring -> exception instance

    def get(self, url, cap=None):
        md.Net.check_url(url)
        self.calls.append(url)
        host = urllib.parse.urlsplit(url).hostname
        self.counts[host] = self.counts.get(host, 0) + 1
        for part, exc in self.fail.items():
            if part in url:
                raise exc
        if url in self.world.errors:
            raise md.HttpStatus(self.world.errors[url], url)
        headers, payload = self.route(url)
        body = payload if isinstance(payload, bytes) else json.dumps(payload).encode('utf-8')
        return md.Reply(url, 200, headers, body)

    def route(self, url):
        w, p = self.world, urllib.parse.urlsplit(url)
        if p.hostname == 'api.github.com':
            m = re.match(r'^/repos/LiveBench/new-livebench/(commits|git/trees|git/blobs)/([^/]+)$', p.path)
            assert m, url
            kind, ref = m.groups()
            if kind == 'commits':
                if ref not in w.commits:
                    raise md.HttpStatus(422, url)
                return {}, w.commits[ref]
            if kind == 'git/trees':
                return {}, w.trees[ref]
            data = w.blobs[ref]
            content = base64.encodebytes(data).decode('ascii')
            return {}, {'sha': ref, 'size': len(data), 'encoding': 'base64', 'content': content}
        if p.hostname in ('livebench.ai', 'www.livebench.ai'):
            if p.path not in w.site:
                raise md.HttpStatus(404, url)
            return w.site[p.path]
        assert p.hostname == 'huggingface.co', url
        if p.path == '/api/models':
            q = urllib.parse.parse_qs(p.query)
            org, start = q['author'][0], int(q.get('cursor', ['0'])[0])
            assert q['limit'] == [str(md.LISTING_LIMIT)], url
            ids = [i for o, names in w.listings.items() if o.casefold() == org.casefold() for i in names]
            size = w.page_size or len(ids) or 1
            page = ids[start:start + size]
            headers = {}
            if start + size < len(ids):
                headers['link'] = f'<https://huggingface.co/api/models?author={org}&limit={md.LISTING_LIMIT}&cursor={start + size}>; rel="next"'
            return headers, [{'id': i, 'likes': 1, 'private': False} for i in page]
        m = re.match(r'^/api/models/(.+)/revision/([0-9a-f]{40})$', p.path)
        if m:
            return {}, w.revisions[(urllib.parse.unquote(m.group(1)).casefold(), m.group(2))]
        m = re.match(r'^/api/models/(.+)$', p.path)
        assert m, url
        repo = urllib.parse.unquote(m.group(1)).casefold()
        if repo not in w.infos:
            raise md.HttpStatus(401, url)    # unauthenticated Hugging Face answers 401 for a missing repo
        return {}, w.infos[repo]

    def authors(self):
        return [urllib.parse.parse_qs(urllib.parse.urlsplit(u).query)['author'][0] for u in self.calls
                if u.startswith(HF + '?')]

    def infos_fetched(self):
        return [urllib.parse.unquote(u[len(HF) + 1:]) for u in self.calls
                if u.startswith(HF + '/') and '/revision/' not in u]


class Result:
    def __init__(self, code, net, out):
        self.code, self.net, self.out = code, net, out

        def read(name):
            path = out / name
            return path.read_text(encoding='utf-8') if path.exists() else None
        self.issue, self.comment, self.failure = read('issue.md'), read('comment.md'), read('failure.md')
        self.step, self.stdout, self.stderr = read('step.md'), read('stdout.txt'), read('stderr.txt')
        self.data = json.loads(read('out.json')) if read('out.json') else None
        text = read('gh.txt') or ''
        self.outputs = dict(line.split('=', 1) for line in text.splitlines() if line)
        self.rows = {r['id']: r for r in (self.data or {}).get('rows', [])}

    def outcome(self, lb_id):
        r = self.rows[lb_id]
        return r['outcome'] if r['outcome'] == 'candidate' else f"{r['outcome']}:{r['reason']}"


class Base(unittest.TestCase):
    maxDiff = None

    def tmp(self):
        path = Path(tempfile.mkdtemp(prefix='model-discovery-'))
        self.addCleanup(shutil.rmtree, path, ignore_errors=True)
        return path

    def root(self, world, **kw):
        return world.root(self.tmp(), **kw)

    def run_world(self, world, *flags, root=None, previous=None, net=None, today=TODAY, env=None, **root_kw):
        root = root or self.root(world, **root_kw)
        out = self.tmp()
        args = ['--today', today, '--issue-summary', str(out / 'issue.md'), '--comment', str(out / 'comment.md'),
                '--failure-summary', str(out / 'failure.md'), '--step-summary', str(out / 'step.md'),
                '--json', str(out / 'out.json'), '--github-output', *flags]
        if previous is not None:
            (out / 'previous.md').write_text(previous, encoding='utf-8')
            args += ['--previous-issue', str(out / 'previous.md')]
        net = net or world.net()
        stdout, stderr = io.StringIO(), io.StringIO()
        with mock.patch.dict(os.environ, {'GITHUB_OUTPUT': str(out / 'gh.txt')}), \
                contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            for name in GITHUB_RUN_VARS:      # the runner's own run must not leak into the rendered run link
                os.environ.pop(name, None)
            os.environ.update(env or {})
            code = md.main(args, net=net, root=root)
        (out / 'stdout.txt').write_text(stdout.getvalue(), encoding='utf-8')
        (out / 'stderr.txt').write_text(stderr.getvalue(), encoding='utf-8')
        return Result(code, net, out)

    def discovery(self, world, **root_kw):
        """A Discovery with its local inputs loaded, for resolving single rows against the fake Hugging Face."""
        d = md.Discovery(world.net(), self.root(world, **root_kw), TODAY_DATE)
        d.local = md.load_local(d.root, TODAY_DATE)
        return d


def row(lb_id, overall=50.0, rank=1):
    return md.Row(lb_id, 2, {'Reasoning': overall}, overall=overall, rank=rank)


# --- local inputs ----------------------------------------------------------------------------
class LocalInputsTest(Base):
    def test_invalid_decisions_file_fails_before_any_network_access(self):
        world = World()
        bad = {'key': 'lb:foo', 'decision': 'ignore', 'reason': 'not a type', 'decided_on': TODAY}
        result = self.run_world(world, decisions=[bad])
        self.assertEqual(result.code, 2)
        self.assertEqual(result.net.calls, [])
        self.assertIsNone(result.issue)
        self.assertIn(f"decisions[{len(FIXTURE_DISCOVERY['decisions'])}].decision", result.failure)
        self.assertEqual(result.outputs, {'complete': 'false', 'reportable': 'false', 'new': 'false'})

    def test_the_real_discovery_file_validates(self):
        # As the nightly run does: the real file, on the real date. The owner adds decisions and edits reasons by
        # hand, so this checks properties (the seeded keys stay, every entry validates), never the exact contents.
        local = md.load_local(ROOT, REAL_TODAY)
        self.assertEqual(DISCOVERY['schema_version'], 1)
        self.assertRegex(local.averaging_revision, r'^[0-9a-f]{40}$')
        prefixes = [p for entry in DISCOVERY['publishers'] for p in entry['prefixes']]
        self.assertEqual(len(prefixes), len(set(prefixes)))
        self.assertTrue(all(p == p.lower() and p for p in prefixes))
        orgs = {o.casefold() for entry in DISCOVERY['publishers'] for o in entry['hf_orgs']}
        catalog_orgs = {m['upstream_repo'].split('/')[0] for m in MODELS['models']}
        self.assertTrue(catalog_orgs)
        self.assertTrue({o.casefold() for o in catalog_orgs} <= orgs)
        by_key = {d['key']: d for d in DISCOVERY['decisions']}
        for key in SEEDED_KEYS:
            self.assertEqual(by_key[key]['decision'], 'not_open_weight', key)
        self.assertNotIn('lb:grok-2*', by_key)   # grok-2 has open weights and is catalogued
        catalog = {m['upstream_repo'].casefold() for m in MODELS['models']}
        evidence = {r['leaderboard_model_id'] for r in EVIDENCE['recommendations']}
        for i, d in enumerate(DISCOVERY['decisions']):
            self.assertEqual(md.decision_errors([d], catalog, evidence, REAL_TODAY), [], f'decisions[{i}]')

    def test_fixture_roots_do_not_read_the_owner_edited_files(self):
        # A real decision dated after TODAY, as the issue snippets write them, must not break the fixture runs.
        later = {'key': 'hf:Qwen/Qwen4-Reviewed', 'decision': 'rejected', 'reason': 'Reviewed by the owner',
                 'decided_on': (TODAY_DATE + dt.timedelta(days=12)).isoformat()}
        with mock.patch.dict(DISCOVERY, {'decisions': DISCOVERY['decisions'] + [later]}):
            result = self.run_world(World())
        self.assertEqual(result.code, 0, result.failure)
        root = self.root(World(), releases_extra=('2026-10-30',))
        self.assertEqual(md.scorer_releases(root / md.SCORER_SOURCE), frozenset(FIXTURE_RELEASES + ('2026-10-30',)))
        self.assertEqual(md.scorer_releases(self.root(World()) / md.SCORER_SOURCE), frozenset(FIXTURE_RELEASES))

    def test_an_impossible_table_date_in_the_evidence_is_invalid_local_input(self):
        def impossible(ev):
            rec = ev['recommendations'][0]
            rec['source_table'] = re.sub(r'table_\d{4}_\d{2}_\d{2}\.csv$', 'table_2025_02_30.csv', rec['source_table'])
        result = self.run_world(World(), evidence=impossible)
        self.assertEqual(result.code, 2)
        self.assertEqual(result.net.calls, [])
        self.assertIn('recommendations[0].source_table: table_2025_02_30.csv does not name a calendar date', result.failure)

    def errors(self, decision, today=TODAY_DATE):
        catalog = {m['upstream_repo'].casefold() for m in MODELS['models']}
        evidence = {r['leaderboard_model_id'] for r in EVIDENCE['recommendations']}
        return md.decision_errors([decision], catalog, evidence, today)

    def test_the_decision_validator_names_index_and_field(self):
        ok = {'key': 'lb:foo-1', 'decision': 'rejected', 'reason': 'Reviewed: a hosted fine-tune', 'decided_on': TODAY}
        self.assertEqual(self.errors(ok), [])
        cases = [
            ({'key': 'xx:foo'}, 'decisions[0].key'),
            ({'key': 'lb:f*'}, 'decisions[0].key'),
            ({'decision': 'ignore'}, 'decisions[0].decision'),
            ({'reason': '  '}, 'decisions[0].reason'),
            ({'reason': 'TODO'}, 'decisions[0].reason'),
            ({'reason': 'todo later'}, 'decisions[0].reason'),
            ({'decision': 'deferred'}, 'decisions[0].until'),
            ({'decision': 'deferred', 'until': TODAY}, 'decisions[0].until'),
            ({'decision': 'deferred', 'until': '2027-11-09'}, 'decisions[0].until'),
            ({'decision': 'alias'}, 'decisions[0].target'),
            ({'decision': 'alias', 'target': 'Qwen/TODO'}, 'decisions[0].target'),
            ({'decision': 'alias', 'target': 'not a repo'}, 'decisions[0].target'),
            ({'key': 'hf:Qwen/Qwen3.8-27B'}, 'redundant'),
            ({'key': 'hf:qwen/QWEN3.8-27b'}, 'redundant'),
            ({'key': 'lb:glm-4.5-air'}, 'redundant'),
            ({'decided_on': '2026-11-10'}, 'decisions[0].decided_on'),
            ({'decision': 'not_open_weight', 'key': 'hf:Qwen/Qwen9'}, 'decisions[0].key'),
            ({'decision': 'alias', 'key': 'lb:foo*', 'target': 'Qwen/Qwen9'}, 'decisions[0].key'),
            ({'until': '2026-12-01'}, 'decisions[0].until'),
            ({'colour': 'red'}, 'decisions[0].colour'),
        ]
        for change, needle in cases:
            with self.subTest(change=change):
                errors = self.errors({**ok, **change})
                self.assertTrue(any(needle in e for e in errors), errors)
        self.assertEqual(self.errors({**ok, 'decided_on': '2026-11-09'}), [])   # today + 1 is allowed
        self.assertEqual(self.errors({**ok, 'decision': 'deferred', 'until': '2027-11-08'}), [])   # exactly 365 days
        dup = md.decision_errors([ok, dict(ok)], set(), set(), TODAY_DATE)
        self.assertTrue(any('decisions[1].key: duplicate' in e for e in dup), dup)
        dup = md.decision_errors([{**ok, 'key': 'hf:Qwen/A'}, {**ok, 'key': 'hf:qwen/a'}], set(), set(), TODAY_DATE)
        self.assertTrue(any('decisions[1].key: duplicate' in e for e in dup), dup)

    def test_evidence_derivation(self):
        world = World()
        local = md.load_local(self.root(world), TODAY_DATE)
        self.assertEqual((local.evidence.repo, local.evidence.revision), (REPO, 'caa4253c8a3aa93b5c7ec234e681d4f120a20240'))
        self.assertEqual(local.evidence.latest_release, '2026-06-25')
        self.assertEqual(len({r['meaning'] for r in EVIDENCE['recommendations']}), 1)
        self.assertEqual(len(EVIDENCE['recommendations']), 5)

        def two_repos(ev):
            ev['recommendations'][1]['source_table'] = ev['recommendations'][1]['source_table'].replace('LiveBench/new-livebench', 'LiveBench/other')

        def other_commit(ev):
            ev['leaderboard_revision'] = 'f' * 40

        def other_meaning(ev):
            ev['recommendations'][2]['meaning'] = 'something else'
        for change, needle in ((two_repos, 'more than one repository'), (other_commit, 'differ from leaderboard_revision'),
                               (other_meaning, 'same non-empty meaning')):
            with self.subTest(change=change.__name__):
                result = self.run_world(World(), evidence=change)
                self.assertEqual(result.code, 2)
                self.assertEqual(result.net.calls, [])
                self.assertIn(needle, result.failure)

    def test_budgets_precision_bits_and_planning_arithmetic_match_the_catalog(self):
        local = md.load_local(ROOT, REAL_TODAY)
        b = local.budgets
        self.assertEqual((b.vram, b.wsl, b.native), (24, 46, 70))
        bits = {}
        for m in MODELS['models']:
            for name in md.PRECISION_BITS:
                if m.get('target_precision', '') in (f'GGUF {name}', name, f'GGUF {name} or FP8'):
                    bits.setdefault(name, set()).add(m['planning_bits'])
        self.assertEqual({k: v for k, v in bits.items()}, {k: {v} for k, v in md.PRECISION_BITS.items()})
        sys.path.insert(0, str(ROOT / 'src'))
        try:
            from llm_eval.catalog import estimate_weights
        finally:
            sys.path.remove(str(ROOT / 'src'))
        for p in (12_884_901_888, 70.6e9, 125_086_497_008):
            for b_ in (2.31, 4.8, 16):
                self.assertAlmostEqual(md.gib(p, b_), estimate_weights(p / 1e9, b_), places=9)
        planned = [m for m in MODELS['models'] if m.get('parameters_b') is not None and m.get('planning_bits') is not None]
        self.assertTrue(planned)
        for m in planned:
            self.assertEqual(round(md.gib(m['parameters_b'] * 1e9, m['planning_bits']), 2), m['planning_weight_gib'], m['id'])

    def test_constants_are_pinned(self):
        self.assertEqual((md.POOL_SIZE, md.MIN_RELEASE_ROWS, md.MAX_MODEL_INFO), (10, 20, 40))
        self.assertEqual((md.MAX_LISTING_PAGES, md.MAX_LISTING_PAGES_RUN, md.LISTING_LIMIT), (20, 80, 1000))
        self.assertEqual(md.WORKING_SET_RESERVE_GIB, 4)
        self.assertEqual(md.PRECISION_BITS, {'Q4_K_M': 4.8, 'Q5_K_M': 5.7, 'Q6_K': 6.6, 'Q8_0': 8.5, 'BF16': 16})
        self.assertEqual(md.INFO_BITS, {'IQ2_XS': 2.31})
        self.assertEqual((md.INT_SHARE_MAX, md.SIZE_RATIO, md.PACKED_NAME_RANGE), (0.01, (0.90, 1.15), (0.90, 1.05)))
        self.assertEqual((md.OVERALL_TOL, md.CATEGORY_TOL, md.SCORE_RANGE), (0.005 + 1e-9, 1e-6, (0.0, 100.0)))
        self.assertEqual((md.MAX_TABLE_BYTES, md.MAX_BODY_BYTES), (8 * 2**20, 32 * 2**20))
        self.assertEqual((md.RETRIES, md.RETRY_AFTER_CAP, md.RETRY_STEP, md.TIMEOUT), (5, 120, 10, 60))
        self.assertEqual((md.ISSUE_BODY_CAP, md.STRING_CAP, md.LIST_CAP), (60_000, 120, 30))
        self.assertEqual((md.FAILURE_STREAK, md.DEFERRAL_MAX_DAYS), (3, 365))
        self.assertEqual(md.HF_ANCHORS, ('qwen38-27b', 'nemotron-super-120b', 'gpt-oss-120b', 'llama33-70b'))
        self.assertEqual(md.ALLOWED_HOSTS, ('api.github.com', 'huggingface.co', 'livebench.ai', 'www.livebench.ai'))
        self.assertEqual(md.RUN_DEADLINE, 15 * 60)
        local = md.load_local(ROOT, REAL_TODAY)
        derived = [local.publisher(r['leaderboard_model_id'])[0].orgs[0] for r in EVIDENCE['recommendations']]
        self.assertEqual(set(derived), set(md.CANARY_ORGS))
        # The 4 GiB reserve is the largest whole GiB that keeps every owner-accepted conditional entry inside M.
        widest = max(md.gib(BY_ID[i]['upstream_metadata']['safetensors']['total'], 4.8)
                     for i in ('gpt-oss-120b', 'glm45-air', 'laguna-s21', 'qwen35-122b-moe'))
        self.assertAlmostEqual(widest, 69.90, places=2)
        self.assertEqual(int(local.budgets.native + md.WORKING_SET_RESERVE_GIB - widest), md.WORKING_SET_RESERVE_GIB)

    def test_scorer_releases_are_read_with_ast_from_the_real_file(self):
        releases = md.scorer_releases(ROOT / md.SCORER_SOURCE)
        self.assertIsNotNone(releases)
        self.assertIn(EVIDENCE['latest_release'], releases)
        self.assertNotIn('2026-10-30', FIXTURE_RELEASES)    # the new-release tests rely on the fixture scorer file
        tmp = self.tmp()
        (tmp / 'livebench.py').write_text('OTHER = {1}\n', encoding='utf-8')
        self.assertIsNone(md.scorer_releases(tmp / 'livebench.py'))
        self.assertIsNone(md.scorer_releases(tmp / 'missing.py'))

    def test_the_script_imports_only_the_standard_library(self):
        tree = ast.parse((ROOT / 'scripts/model_discovery.py').read_text(encoding='utf-8'))
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names |= {a.name.split('.')[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom):
                names.add((node.module or '').split('.')[0])
        self.assertNotIn('llm_eval', names)
        self.assertTrue(names <= set(sys.stdlib_module_names), names - set(sys.stdlib_module_names))


# --- network layer ------------------------------------------------------------------------------
class FakeResponse:
    def __init__(self, body=b'{}', status=200, headers=None):
        self._body, self.status = io.BytesIO(body), status
        self.headers = email.message.Message()
        for k, v in (headers or {}).items():
            self.headers[k] = v

    def read(self, n=-1):
        return self._body.read(n)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def http_error(url, code, headers=None, body=b'{"message": "nope"}'):
    msg = email.message.Message()
    for k, v in (headers or {}).items():
        msg[k] = v
    return urllib.error.HTTPError(url, code, 'error', msg, io.BytesIO(body))


class FakeOpener:
    def __init__(self, *script):
        self.script, self.requests = list(script), []

    def open(self, req, timeout=None):
        self.requests.append((req, timeout))
        item = self.script.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


class NetTest(Base):
    def net(self, *script, **kw):
        net = md.Net(env=kw.pop('env', {}), **kw)
        net.opener = FakeOpener(*script)
        net.sleeps = []
        net.sleep = net.sleeps.append
        return net

    def test_only_https_to_the_allowed_hosts(self):
        net = self.net()
        for url in ('http://api.github.com/repos/x/y', 'https://example.com/x', 'http://livebench.ai/table_2026_06_25.csv',
                    'https://raw.githubusercontent.com/LiveBench/new-livebench/main/x', 'https://user@huggingface.co/api',
                    'https://huggingface.co:8443/api', 'https://livebench.ai.evil.net/x', 'https://cdn.livebench.ai/x'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                net.get(url)
        self.assertEqual(net.opener.requests, [])

    def test_tokens_go_only_to_their_own_host(self):
        net = self.net(FakeResponse(), FakeResponse(), env={'GITHUB_TOKEN': 'gh-secret', 'HF_TOKEN': 'hf-secret'})
        net.get('https://api.github.com/repos/a/b/commits/HEAD')
        net.get('https://huggingface.co/api/models/a/b')
        (gh, _), (hf, _) = net.opener.requests
        self.assertEqual(gh.get_header('Authorization'), 'Bearer gh-secret')
        self.assertEqual(hf.get_header('Authorization'), 'Bearer hf-secret')
        self.assertEqual(gh.get_header('User-agent'), 'llm-eval model_discovery')
        site = self.net(FakeResponse(), FakeResponse(), env={'GITHUB_TOKEN': 'gh-secret', 'HF_TOKEN': 'hf-secret'})
        site.get('https://livebench.ai/table_2026_06_25.csv')
        site.get('https://www.livebench.ai/')
        for req, _ in site.opener.requests:
            self.assertIsNone(req.get_header('Authorization'))   # no token ever goes to the leaderboard site
            self.assertEqual(req.get_header('Accept'), '*/*')
        empty = self.net(FakeResponse(), env={'GITHUB_TOKEN': '', 'HF_TOKEN': ''})
        empty.get('https://api.github.com/repos/a/b/commits/HEAD')
        self.assertIsNone(empty.opener.requests[0][0].get_header('Authorization'))
        self.assertEqual(empty.opener.requests[0][1], 60)

    def test_redirects_stay_on_the_same_https_host(self):
        handler = md.SameHostRedirect()
        self.assertEqual(handler.max_redirections, 5)
        req = urllib.request.Request('https://huggingface.co/api/models/a/b', headers={'Authorization': 'Bearer x'})
        same = handler.redirect_request(req, io.BytesIO(), 307, 'moved', email.message.Message(), 'https://huggingface.co/api/models/a/c')
        self.assertEqual(same.full_url, 'https://huggingface.co/api/models/a/c')
        for target in ('https://cdn.example.net/a/b', 'http://huggingface.co/api/models/a/c', 'https://huggingface.co.evil.net/x'):
            with self.subTest(target=target), self.assertRaises(md.ShapeError) as ctx:
                handler.redirect_request(req, io.BytesIO(), 302, 'found', email.message.Message(), target)
            self.assertIn('unexpected redirect to', str(ctx.exception))

    def test_redirects_through_the_urllib_opener(self):
        class Upstream(urllib.request.BaseHandler):
            handler_order = 100          # answers before the real HTTPS handler: no socket is opened

            def __init__(self, *answers):
                self.answers, self.seen = list(answers), []

            def https_open(self, req):
                self.seen.append((req.full_url, req.get_header('Authorization')))
                status, location, body = self.answers.pop(0)
                headers = email.message.Message()
                if location:
                    headers['Location'] = location
                resp = urllib.response.addinfourl(io.BytesIO(body), headers, req.full_url, status)
                resp.msg = 'answer'
                return resp
        url = 'https://huggingface.co/api/models/a/b'
        upstream = Upstream((307, 'https://huggingface.co/api/models/a/c', b''), (200, None, b'{"id": "a/c"}'))
        net = md.Net(env={'HF_TOKEN': 'hf-secret'})
        net.opener = urllib.request.build_opener(md.SameHostRedirect, upstream)
        self.assertEqual(net.get(url).json(), {'id': 'a/c'})
        self.assertEqual(upstream.seen, [(url, 'Bearer hf-secret'), ('https://huggingface.co/api/models/a/c', 'Bearer hf-secret')])
        upstream = Upstream((302, 'https://cdn-lfs.example.org/a/b', b''))
        net.opener = urllib.request.build_opener(md.SameHostRedirect, upstream)
        with self.assertRaises(md.ShapeError) as ctx:
            net.get(url)
        self.assertIn('unexpected redirect to cdn-lfs.example.org', str(ctx.exception))
        self.assertEqual(len(upstream.seen), 1)      # the token never reaches the other host

    def test_retry_after_seconds_http_date_and_cap(self):
        url = 'https://huggingface.co/api/models/a/b'
        net = self.net(http_error(url, 429, {'Retry-After': '7'}), http_error(url, 503, {'Retry-After': '999'}),
                       http_error(url, 503, {'Retry-After': 'Sun, 08 Nov 2026 12:00:30 GMT'}),
                       http_error(url, 502, {'Retry-After': 'not a date'}), FakeResponse(b'[]'))
        net.now = lambda: dt.datetime(2026, 11, 8, 12, 0, 0, tzinfo=dt.timezone.utc)
        self.assertEqual(net.get(url).body, b'[]')
        self.assertEqual(net.sleeps, [7, 120, 30, 40])
        self.assertEqual(net.counts['huggingface.co'], 5)

    def test_transport_errors_are_retried_then_raise_network_error(self):
        url = 'https://api.github.com/repos/a/b/commits/HEAD'
        net = self.net(urllib.error.URLError('down'), TimeoutError(), ConnectionResetError(), urllib.error.URLError('x'),
                       TimeoutError())
        with self.assertRaises(md.NetworkError) as ctx:
            net.get(url)
        self.assertNotIsInstance(ctx.exception, md.HttpStatus)
        self.assertEqual(net.sleeps, [10, 20, 30, 40])
        self.assertEqual(len(net.opener.requests), 5)

    def test_tls_status_line_and_socket_errors_are_retried(self):
        class BrokenRead(FakeResponse):
            def read(self, n=-1):
                raise ssl.SSLError(1, '[SSL: DECRYPTION_FAILED_OR_BAD_RECORD_MAC] decryption failed or bad record mac')
        url = 'https://huggingface.co/api/models/a/b'
        # urllib wraps only connect-phase errors in URLError: these come unwrapped from getresponse() or read().
        net = self.net(BrokenRead(), http.client.BadStatusLine('garbage'), http.client.LineTooLong('header line'),
                       http.client.RemoteDisconnected('closed'), FakeResponse(b'[]'))
        self.assertEqual(net.get(url).body, b'[]')
        self.assertEqual(net.sleeps, [10, 20, 30, 40])
        net = self.net(*[OSError(errno.EHOSTUNREACH, 'No route to host')] * 5)
        with self.assertRaises(md.NetworkError) as ctx:
            net.get(url)
        self.assertIn('OSError after 5 attempts', str(ctx.exception))
        self.assertEqual(len(net.opener.requests), 5)

    def test_a_record_directory_fault_is_not_retried_as_a_network_fault(self):
        net = self.net(FakeResponse(b'{}'), FakeResponse(b'{}'))
        net.record = mock.Mock(side_effect=OSError(errno.ENOSPC, 'No space left on device'))
        with self.assertRaises(OSError):
            net.get('https://huggingface.co/api/models/a/b')
        self.assertEqual((len(net.opener.requests), net.sleeps), (1, []))

    def test_the_run_deadline_ends_retries_with_a_network_error(self):
        url = 'https://huggingface.co/api/models/a/b'
        clock = [0.0]
        net = self.net(*[http_error(url, 429, {'Retry-After': '120'})] * 5)
        net.clock, net.deadline = (lambda: clock[0]), 300.0
        net.sleep = lambda s: (net.sleeps.append(s), clock.__setitem__(0, clock[0] + s))
        with self.assertRaises(md.NetworkError) as ctx:
            net.get(url)
        self.assertNotIsInstance(ctx.exception, md.HttpStatus)
        self.assertIn('HTTP 429; no time left before the run deadline of 900 s', str(ctx.exception))
        self.assertEqual((net.sleeps, len(net.opener.requests)), ([120, 120], 3))   # a third sleep would end at 360
        net = self.net(FakeResponse(b'{}'))
        net.clock, net.deadline = (lambda: 1000.0), 1000.0
        with self.assertRaises(md.NetworkError):
            net.get(url)
        self.assertEqual(net.opener.requests, [])
        net = self.net(FakeResponse(b'{}'))
        net.clock, net.deadline = (lambda: 990.0), 1000.0
        net.get(url)
        self.assertEqual(net.opener.requests[0][1], 10.0)     # no attempt outlives the deadline

    def test_github_rate_limit_403_is_retried_other_403_is_final(self):
        url = 'https://api.github.com/repos/a/b/commits/HEAD'
        net = self.net(http_error(url, 403, {'x-ratelimit-remaining': '0'}), FakeResponse(b'{"sha": 1}'))
        self.assertEqual(net.get(url).json(), {'sha': 1})
        self.assertEqual(net.sleeps, [10])
        net = self.net(http_error(url, 403))
        with self.assertRaises(md.HttpStatus) as ctx:
            net.get(url)
        self.assertEqual(ctx.exception.code, 403)
        hf = 'https://huggingface.co/api/models/a/b'
        net = self.net(http_error(hf, 403, {'x-ratelimit-remaining': '0'}))
        with self.assertRaises(md.HttpStatus):
            net.get(hf)
        self.assertEqual(net.sleeps, [])

    def test_a_body_over_its_cap_is_a_shape_error(self):
        net = self.net(FakeResponse(b'x' * 101))
        with self.assertRaises(md.ShapeError) as ctx:
            net.get('https://huggingface.co/api/models/a/b', cap=100)
        self.assertIn('response over 100 bytes', str(ctx.exception))
        net = self.net(FakeResponse(b'x' * 100))
        self.assertEqual(len(net.get('https://huggingface.co/api/models/a/b', cap=100).body), 100)

    def test_record_writes_bodies_and_an_index_but_no_request_headers(self):
        out = self.tmp() / 'raw'
        url = 'https://huggingface.co/api/models/a/b'
        net = self.net(FakeResponse(b'{"id": "a/b"}', headers={'Content-Type': 'application/json', 'Link': '<x>; rel="next"'}),
                       http_error(url + '/c', 404, body=b'gone'), record_dir=out,
                       env={'GITHUB_TOKEN': 'gh-secret', 'HF_TOKEN': 'hf-secret'})
        net.get(url)
        with self.assertRaises(md.HttpStatus):
            net.get(url + '/c')
        index = json.loads((out / 'index.json').read_text(encoding='utf-8'))
        self.assertEqual([e['status'] for e in index], [200, 404])
        self.assertEqual(set(index[0]), {'url', 'status', 'content_type', 'link', 'bytes', 'sha256', 'file'})
        self.assertEqual(index[0]['sha256'], hashlib.sha256(b'{"id": "a/b"}').hexdigest())
        self.assertEqual((out / index[0]['file']).read_bytes(), b'{"id": "a/b"}')
        for path in out.iterdir():
            text = path.read_text(encoding='utf-8', errors='replace')
            self.assertNotIn('secret', text)
            self.assertNotIn('Authorization', text)
            self.assertNotIn('User-Agent', text)


class GitBlobTest(Base):
    def test_blob_bytes_are_checked_against_the_tree_sha(self):
        data = b'model,a\n'
        self.assertEqual(md.git_blob_sha(data), '883d052f7e51626fa819180ad7e9371bb259a513')
        doc = {'sha': '883d052f7e51626fa819180ad7e9371bb259a513', 'size': 8, 'encoding': 'base64',
               'content': base64.encodebytes(data).decode('ascii')}
        self.assertEqual(md.verify_blob(doc, doc['sha'], 'u'), data)
        bad = [{**doc, 'content': base64.encodebytes(b'model,b\n').decode('ascii')},
               {**doc, 'encoding': 'utf-8', 'content': 'model,a\n'},
               {**doc, 'size': 9}]
        for case in bad:
            with self.subTest(case=case), self.assertRaises(md.ShapeError):
                md.verify_blob(case, doc['sha'], 'u')


# --- tables, categories, aggregation ------------------------------------------------------------
class ParsingTest(Base):
    CATS = {'Math': ['m1', 'm2', 'm3', 'm4'], 'Coding': ['c1']}

    def scored(self, text, cats=None):
        raw = md.read_csv(text.encode('utf-8') if isinstance(text, str) else text, 'u')
        return md.score_table(raw, cats or self.CATS)

    def test_csv_shape(self):
        text = '\ufeffModel ,m1,m2,m3,m4,c1,notes\r\n"a,b",10,20,30,40,50,x\r\nplain,1,2,3,4,5,y\r\n'
        scored, partial, extras = self.scored(text)
        self.assertEqual([r.id for r in scored], ['a,b', 'plain'])
        self.assertEqual(extras, ['notes'])
        self.assertEqual([r.line for r in scored], [2, 3])
        multi = 'model,m1,m2,m3,m4,c1,notes\n"first",1,2,3,4,5,"two\nlines"\nsecond,1,2,3,4,5,z\n'
        self.assertEqual([r.line for r in sorted(self.scored(multi)[0], key=lambda r: r.id)], [2, 4])
        for marker in ('', '-', 'NaN', 'null', 'None', 'n/a', ' N/A '):
            scored, _, _ = self.scored(f'model,m1,m2,m3,m4,c1\nx,{marker},20,30,40,50\n')
            self.assertEqual(scored[0].missing_tasks, 1, marker)
        for cell in ('101', '-3', 'abc', 'inf', '1_0'):
            with self.subTest(cell=cell), self.assertRaises(md.ShapeError):
                self.scored(f'model,m1,m2,m3,m4,c1\nx,{cell},20,30,40,50\n')
        bad = {'no model column': 'id,m1,m2,m3,m4,c1\nx,1,2,3,4,5\n',
               'two model columns': 'model,MODEL,m1,m2,m3,m4,c1\nx,y,1,2,3,4,5\n',
               'duplicate id': 'model,m1,m2,m3,m4,c1\nx,10,2,3,4,5\nx,10,2,3,4,5\n',
               'fraction scale': 'model,m1,m2,m3,m4,c1\nx,0.5,0.2,0.3,0.4,1.0\n',
               'ragged row': 'model,m1,m2,m3,m4,c1\nx,10,2,3,4\n'}
        for name, text in bad.items():
            with self.subTest(name=name), self.assertRaises(md.ShapeError):
                self.scored(text)
        with self.assertRaises(md.ShapeError) as ctx:
            self.scored('model,m1,m2,m3,c1\nx,1,2,3,4\n')
        self.assertIn('m4', str(ctx.exception))
        with self.assertRaises(md.ShapeError):
            md.read_csv(b'model,m1\n\xff\xfe,1\n', 'u')

    def test_categories_shape(self):
        self.assertEqual(md.parse_categories(b'{"A": ["t1", "t2"], "B": ["t3"]}', 'u'), {'A': ['t1', 't2'], 'B': ['t3']})
        for text in (b'[["t1"]]', b'{"A": []}', b'{"A": ["t1", 2]}', b'{"A": ["t1"], "B": ["t1"]}', b'{}', b'not json'):
            with self.subTest(text=text), self.assertRaises(md.ShapeError):
                md.parse_categories(text, 'u')

    def test_two_level_mean(self):
        scored, _, _ = self.scored('model,m1,m2,m3,m4,c1\nx,10,20,30,40,90\n')
        self.assertAlmostEqual(scored[0].overall, (25 + 90) / 2)
        self.assertNotAlmostEqual(scored[0].overall, (10 + 20 + 30 + 40 + 90) / 5)
        scored, _, _ = self.scored('model,m1,m2,m3,m4,c1\nx,10,,30,50,90\n')
        self.assertAlmostEqual(scored[0].categories['Math'], 30)
        self.assertEqual(scored[0].missing_label(), '1 of 5 tasks missing')
        scored, partial, _ = self.scored('model,m1,m2,m3,m4,c1\nx,10,20,30,40,\ny,1,2,3,4,5\n')
        self.assertEqual([r.id for r in scored], ['y'])
        self.assertIsNone(partial[0].overall)
        self.assertEqual(partial[0].partial_label(), 'partial (1 of 2 categories)')
        self.assertAlmostEqual(partial[0].partial_mean, 25)
        scored, _, _ = self.scored('model,m1,m2,m3,m4,c1\nb,10,10,10,10,10\na,10,10,10,10,10\nc,20,20,20,20,20\n'
                                   'd,5,5,5,5,5\n')
        # standard competition rank: the row after a two-way tie at rank 2 is rank 4 (dense rank would say 3)
        self.assertEqual([(r.id, r.rank) for r in scored], [('c', 1), ('a', 2), ('b', 2), ('d', 4)])

    def test_recorded_evidence_reproduces_offline(self):
        overalls = []
        for rec in EVIDENCE['recommendations']:
            values = list(rec['category_scores'].values())
            mean = sum(values) / len(values)
            self.assertLessEqual(abs(mean - rec['overall']), md.OVERALL_TOL, rec['leaderboard_model_id'])
            overalls.append((rec['overall'], len(values)))
        self.assertEqual(overalls, [(47.52, 6), (55.51, 6), (60.53, 7), (45.92, 6), (56.64, 6)])
        tightest = EVIDENCE['recommendations'][0]
        mean = sum(tightest['category_scores'].values()) / 6
        self.assertAlmostEqual(mean, 47.515028, places=6)
        self.assertAlmostEqual(tightest['overall'] - mean, 0.00497, places=5)
        self.assertGreater(tightest['overall'] - mean, 0.0049)


# --- strict matcher -----------------------------------------------------------------------------
def match(lb_id, repos, orgs=None):
    orgs = orgs or sorted({r.split('/')[0] for r in repos})
    return md.strict_match(lb_id, orgs, lambda org: [r for r in repos if r.split('/')[0] == org])


class MatcherTest(Base):
    def test_normalization(self):
        self.assertEqual(md.tokens('nvidia/Llama-3_3-Nemotron-Super-49B-v1_5', 'nvidia'),
                         ['llama', '3.3', 'nemotron', 'super', '49b', 'v1.5'])
        self.assertEqual(md.tokens('Qwen/Qwen3.5-35B-A3B', 'Qwen'), ['qwen3.5', '35b', 'a3b'])
        self.assertEqual(md.tokens('NVIDIA-Nemotron-3-Nano-30B-A3B-BF16', 'nvidia'), ['nemotron', '3', 'nano', '30b', 'a3b', 'bf16'])
        self.assertEqual(md.tokens('Meta-Llama-3-70B-Instruct', 'meta-llama'), ['3', '70b', 'instruct'])
        status, m, _ = match('llama-3-70b-instruct', ['meta-llama/Meta-Llama-3-70B-Instruct'])
        self.assertEqual((status, m.repo, m.tier), ('match', 'meta-llama/Meta-Llama-3-70B-Instruct', 'exact'))

    def test_strict_matcher_table(self):
        cases = [
            ('glm-4.5-air', ['zai-org/GLM-4.5-Air', 'zai-org/GLM-4.5-Air-FP8', 'zai-org/GLM-4.5-Air-Base'], 'zai-org/GLM-4.5-Air', 'exact', []),
            ('gemma-4-31b', ['google/gemma-4-31B-it'], 'google/gemma-4-31B-it', 'relaxed', ['it']),
            ('kimi-linear-48b-a3b', ['moonshotai/Kimi-Linear-48B-A3B-Instruct'], 'moonshotai/Kimi-Linear-48B-A3B-Instruct', 'relaxed', ['instruct']),
            ('nemotron-3-nano-30b-a3b', ['nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16'], 'nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16', 'relaxed', ['bf16']),
            ('qwen3.5-a3b', ['Qwen/Qwen3.5-35B-A3B'], 'Qwen/Qwen3.5-35B-A3B', 'relaxed', ['35b']),
        ]
        for lb_id, repos, repo, tier, extras in cases:
            with self.subTest(lb_id=lb_id):
                status, m, _ = match(lb_id, repos)
                self.assertEqual((status, m.repo, m.tier, m.extras, m.stage), ('match', repo, tier, extras, 1))
        status, _, _ = match('mistral-small-2503', ['mistralai/Mistral-Small-3.1-24B-Instruct-2503'])
        self.assertEqual(status, 'no_repo')
        for suffix in ('FP8', 'Base', 'pt', 'GGUF', 'onnx', 'reasoning', 'Thinking', 'AWQ', 'MLX', 'NVFP4', '2507'):
            with self.subTest(suffix=suffix):
                self.assertEqual(match('foo-7b', [f'acme/Foo-7B-{suffix}'])[0], 'no_repo')
        # a size or active-parameter extra only when the id has no size token, and only in stage 1
        self.assertEqual(match('foo-7b', ['acme/Foo-7B-13B'])[0], 'no_repo')
        self.assertEqual(match('foo-30b', ['acme/Foo-30B-A3B'])[0], 'no_repo')
        self.assertEqual(match('qwen3-30b', ['Qwen/Qwen3-30B-A3B'])[0], 'no_repo')
        self.assertEqual(match('foo-high', ['acme/Foo-7B'])[0], 'no_repo')
        self.assertEqual(match('foo-high', ['acme/Foo-A3B'])[0], 'no_repo')
        self.assertEqual(match('qwen4-80b', ['Qwen/Qwen4-80B-Thinking'])[0], 'no_repo')
        # stage 2 strips at most two trailing tokens
        self.assertEqual(match('qwen3-32b-thinking-high-32k', ['Qwen/Qwen3-32B'])[0], 'no_repo')

    def test_uniqueness(self):
        status, found, pool = match('llama-3.1-70b', ['meta-llama/Llama-3.1-70B', 'meta-llama/Llama-3.1-70B-Instruct'])
        self.assertEqual(status, 'ambiguous')
        self.assertEqual([(m.repo, m.extras) for m in found], [('meta-llama/Llama-3.1-70B', []), ('meta-llama/Llama-3.1-70B-Instruct', ['instruct'])])
        self.assertEqual(pool, 2)
        self.assertEqual(match('foo', ['acme/Foo-Instruct', 'acme/Foo-Chat'])[0], 'ambiguous')
        status, m, _ = match('foo-30b', ['acme/Foo-30B', 'acme/Foo-30B-BF16'])
        self.assertEqual((status, m.repo), ('match', 'acme/Foo-30B'))
        status, m, _ = match('foo-30b', ['acme/Foo-30B-BF16', 'acme/Foo-30B-FP16'])
        self.assertEqual((status, m.repo), ('match', 'acme/Foo-30B-BF16'))

    def test_stage_two_stripping_confirms(self):
        status, m, _ = match('gpt-oss-120b-high', ['openai/gpt-oss-120b', 'openai/gpt-oss-safeguard-120b'])
        self.assertEqual((status, m.repo, m.stage, m.stripped), ('match', 'openai/gpt-oss-120b', 2, ['high']))
        status, m, _ = match('qwen3.8-27b-thinking', ['Qwen/Qwen3.8-27B'])
        self.assertEqual((m.repo, m.stage), ('Qwen/Qwen3.8-27B', 2))
        status, m, _ = match('qwen3.8-27b-thinking', ['Qwen/Qwen3.8-27B', 'Qwen/Qwen3.8-27B-Thinking'])
        self.assertEqual((m.repo, m.stage), ('Qwen/Qwen3.8-27B-Thinking', 1))
        status, m, _ = match('qwen3-32b-non-thinking', ['Qwen/Qwen3-32B'])
        self.assertEqual((m.repo, m.stripped), ('Qwen/Qwen3-32B', ['non', 'thinking']))
        status, m, _ = match('qwen3-32b-thinking-32k', ['Qwen/Qwen3-32B'])
        self.assertEqual(m.stripped, ['thinking', '32k'])
        self.assertEqual(match('qwen3-max', ['Qwen/Qwen3', 'Qwen/Qwen3-Max-Preview'])[0], 'no_repo')
        world = World()
        world.add_model('Qwen/Qwen3.8-27B-Thinking', total=27_781_427_952)
        o = self.discovery(world).resolve(row('qwen3.8-27b-thinking'))
        self.assertEqual((o.kind, o.repo, o.match.stage), ('candidate', 'Qwen/Qwen3.8-27B-Thinking', 1))
        o = self.discovery(World()).resolve(row('qwen3.8-27b-thinking'))
        self.assertEqual((o.kind, o.reason, o.repo), ('known', 'catalog', 'Qwen/Qwen3.8-27B'))
        self.assertIn('after stripping `-thinking`', md.Report.match_text(None, md.Outcome(o.row, 'candidate', '', match=o.match)))
        d = self.discovery(World())
        o = d.resolve(row('llama-3.3-70b-instruct-turbo'))
        self.assertEqual((o.kind, o.reason, o.repo), ('known', 'catalog', 'meta-llama/Llama-3.3-70B-Instruct'))
        self.assertIn('hosted serving variant (-turbo)', md.Report.match_text(None, o))

    def test_publishers(self):
        d = self.discovery(World())
        pub, prefix = d.local.publisher('llama-3.3-nemotron-super-49b-v1.5')
        self.assertEqual((pub.orgs, prefix), (('nvidia',), 'llama-3.3-nemotron-'))
        o = d.resolve(row('llama-3.3-nemotron-super-49b-v1.5'))
        self.assertEqual((o.kind, o.reason, o.repo), ('known', 'catalog', 'nvidia/Llama-3_3-Nemotron-Super-49B-v1_5'))
        before = len(d.net.calls)
        for lb_id, reason in (('claude-x', 'not_open_weight'), ('gemini-y', 'not_open_weight'), ('zebra-1', 'unknown_publisher')):
            self.assertEqual(d.resolve(row(lb_id)).reason, reason)
        self.assertEqual(len(d.net.calls), before)
        world = World()
        world.listings['acme'] = ['acme/Acme-7B']
        world.listings['acme-labs'] = ['acme-labs/Acme-7B']
        d = self.discovery(world, publishers=[{'prefixes': ['acme-'], 'hf_orgs': ['acme', 'acme-labs']}])
        o = d.resolve(row('acme-7b'))
        self.assertEqual((o.kind, o.reason), ('look', 'ambiguous'))
        self.assertEqual([m.repo for m in o.found], ['acme/Acme-7B', 'acme-labs/Acme-7B'])


# --- parameter count and fit --------------------------------------------------------------------
class ParameterTest(Base):
    B = md.Budgets(24, 46, 70, 52)

    def test_fit_boundaries(self):
        for p, cls in ((12_884_901_888, 'control_only'), (12_884_901_889, 'offload'), (82_320_206_506, 'offload'),
                       (82_320_206_507, 'high_memory'), (125_269_879_466, 'high_memory'), (125_269_879_467, 'too_large')):
            self.assertEqual(md.fit_class(p, self.B), cls, p)
        fit = md.fit_for(320e9, self.B)
        self.assertEqual(fit.cls, 'too_large')
        self.assertEqual((round(fit.gib['Q4_K_M'], 2), round(fit.gib['IQ2_XS'], 2)), (178.81, 86.05))
        # too large: the bits per weight at which P fits M = 70 GiB (M * 8 * 2^30 / P), not a fixed range
        for p, bits in ((320e9, '1.88'), (130e9, '4.63'), (671e9, '0.90')):
            self.assertEqual(md.fit_for(p, self.B).label,
                             f'would fit 70 GiB only at {bits} bits per weight or fewer; not a catalog tier')
        self.assertAlmostEqual(md.gib(130e9, md.bits_to_fit(130e9, 70)), 70)
        self.assertEqual(md.range_fit('too_large', 130e9, 320e9, self.B).label,
                         'would fit 70 GiB only at 1.88–4.63 bits per weight or fewer, depending on P within the '
                         'packed range; not a catalog tier')

    def test_offload_labels_list_the_precisions_within_the_band(self):
        self.assertEqual(md.fit_for(40e9, self.B).label, 'over 24 GiB and within 46 GiB at Q5_K_M, Q6_K, Q8_0')
        # A class taken from a packed range only: the precisions at each bound, never "none of the listed precisions".
        self.assertEqual(md.range_fit('offload', 40e9, 79e9, self.B).label,
                         'over 24 GiB and within 46 GiB at Q5_K_M, Q6_K, Q8_0 at the lower bound and Q4_K_M at the '
                         'upper bound; which precision applies depends on P within the packed range')
        self.assertEqual(md.range_fit('offload', 30e9, 31e9, self.B).label,
                         'over 24 GiB and within 46 GiB at Q8_0 over the whole packed range')
        for lower in range(13, 82, 3):     # every offload P has at least one precision inside (V, W]
            for upper in (lower, lower + 1):
                with self.subTest(lower=lower, upper=upper):
                    self.assertNotIn('none', md.range_fit('offload', lower * 1e9, upper * 1e9, self.B).label)

    def test_the_real_catalog_through_the_parameter_rule(self):
        d = self.discovery(World())
        classes = {}
        for m in d.local.models:
            params, fit = d.catalog_fit(m)
            classes[m.id] = fit.cls if fit else None
        for m in MODELS['models']:
            if m['status'] == 'candidate':
                self.assertEqual(classes[m['id']], 'offload', m['id'])
            if m['status'] == 'conditional' and m['id'] != 'qwen38-flash-next-strata':
                self.assertIn(classes[m['id']], ('offload', 'high_memory'), m['id'])
        self.assertEqual(classes['qwen38-flash-next-strata'], 'too_large')
        self.assertEqual(classes['grok-1'], 'too_large')
        self.assertIsNone(classes['grok-2'])
        q = BY_ID['qwen35-122b-moe']['upstream_metadata']['safetensors']['total']
        self.assertEqual(round(md.gib(q, 4.8), 2), 69.90)
        self.assertLessEqual(md.gib(q, 4.8), 70)

    def test_parameter_rule(self):
        meta = lambda cid: BY_ID[cid]['upstream_metadata']['safetensors']
        names = lambda cid: md.tokens(BY_ID[cid]['upstream_repo'], BY_ID[cid]['upstream_repo'].split('/')[0])
        p = md.parameter_count(meta('qwen38-27b'), names('qwen38-27b'), self.B)
        self.assertEqual((p.kind, p.value), ('float', 27_781_427_952))
        p = md.parameter_count(meta('qwen38-flash-next-strata'), names('qwen38-flash-next-strata'), self.B)
        self.assertEqual((p.kind, p.value), ('float', 179_999_981_459))   # 35 I64 elements: still float
        p = md.parameter_count(meta('nemotron-super-120b'), names('nemotron-super-120b'), self.B)
        self.assertEqual((p.kind, p.value, round(p.int_share, 3)), ('packed', 120_000_000_000, 0.839))
        self.assertEqual((round(p.lower / 1e9, 2), round(p.upper / 1e9, 2)), (67.23, 123.61))
        p = md.parameter_count(meta('gpt-oss-120b'), names('gpt-oss-120b'), self.B)
        self.assertEqual((p.kind, round(p.int_share, 3), round(p.lower / 1e9, 2), round(p.upper / 1e9, 2)),
                         ('packed', 0.981, 116.83, 231.49))
        # no name size: both bounds in one class -> that class; bounds in two classes -> size_unverified
        p = md.parameter_count({'parameters': {'BF16': 1_000_000_000, 'U8': 39_000_000_000}, 'total': 40_000_000_000}, ['foo'], self.B)
        self.assertEqual((p.value, p.cls, p.problem, p.upper), (None, 'offload', None, 79_000_000_000))
        p = md.parameter_count({'parameters': {'BF16': 2_000_000_000, 'U8': 48_000_000_000}, 'total': 50_000_000_000}, ['foo'], self.B)
        self.assertEqual((p.value, p.cls, p.problem), (None, None, 'size_unverified'))   # 50-98B: offload..high_memory
        p = md.parameter_count({'parameters': {'BF16': 1_000_000_000, 'I32': 1_000_000_000}, 'total': 2_000_000_000}, ['foo'], self.B)
        self.assertEqual((p.upper, p.cls), (9_000_000_000, 'control_only'))   # 8x per 32-bit integer element
        p = md.parameter_count(meta('nemotron-super-120b'), ['nemotron', '3', 'super', '300b'], self.B)
        self.assertEqual(p.problem, 'size_mismatch')
        self.assertEqual(md.parameter_count(None, ['foo'], self.B).problem, 'size_unverified')

    def test_size_token_gate(self):
        self.assertEqual(md.size_gate(['foo', '40b'], ['foo', '40b'], 36e9)[0], True)
        self.assertEqual(md.size_gate(['foo', '40b'], ['foo', '40b'], 46e9)[0], True)
        self.assertEqual(md.size_gate(['foo', '40b'], ['foo', '40b'], 35.99e9)[0], False)
        self.assertEqual(md.size_gate(['foo', '40b'], ['foo', '40b'], 46.01e9)[0], False)
        self.assertEqual(md.size_gate(['foo', '40b'], ['foo', '40b'], 7.2e9)[0], False)
        self.assertIsNone(md.size_gate(['mixtral', '8x7b'], ['mixtral', '8x7b'], 46e9))
        self.assertIsNone(md.size_gate(['llama', '4', '17b', '16e'], ['llama', '4', '17b', '16e'], 109e9))
        self.assertIsNone(md.size_gate(['foo', '7b', '13b'], ['foo'], 7e9))
        self.assertIsNone(md.size_gate(['foo'], ['foo'], 7e9))


class GateTest(Base):
    def world(self):
        world = World()
        world.add_model('Qwen/Qwen4-40B', total=40_912_345_600, params={'BF16': 40_912_340_000, 'F32': 5_600})
        world.add_model('Qwen/Qwen4-Moved', canonical='someone/Qwen4-Moved')
        world.add_model('Qwen/Qwen4-Small-40B', total=7_200_000_000)
        world.add_model('Qwen/Qwen4-Edge-40B', total=36_000_000_000)
        world.add_model('Qwen/Qwen4-Over-40B', total=46_000_000_001)
        world.add_model('Qwen/Qwen4-MoE-8x7B', total=12_000_000_000)
        world.add_model('Qwen/Qwen4-Private', private=True)
        world.add_model('Qwen/Qwen4-Disabled', disabled=True)
        world.add_model('Qwen/Qwen4-Empty', files=0)
        world.add_model('Qwen/Qwen4-Nolicense', license=None)
        world.add_model('Qwen/Qwen4-Tagged', license=None, tags=['license:apache-2.0'])
        world.add_model('Qwen/Qwen4-Gated', gated='manual')
        world.add_model('Qwen/Qwen4-Packed', total=40_000_000_000, params={'BF16': 1_000_000_000, 'U8': 39_000_000_000})
        world.add_model('Qwen/Qwen4-Packed-Wide', total=70_000_000_000, params={'BF16': 1_000_000_000, 'U8': 69_000_000_000})
        world.add_model('Qwen/Qwen4-Packed-Named-300B', total=70_000_000_000, params={'BF16': 1_000_000_000, 'U8': 69_000_000_000})
        world.add_model('Qwen/Qwen4-Nometa', total=None)
        world.add_model('Qwen/Qwen4-Base-Of', card={'license': 'apache-2.0', 'base_model': 'Qwen/Qwen3.8-27B'})
        world.listings['Qwen'] += ['Qwen/Qwen4-Unreadable']
        return world

    def test_unreadable_model_info_keeps_the_run_complete(self):
        world = World([('qwen4-gone', 99.0), ('qwen4-hidden', 98.0)] + DEFAULT_ROWS)
        world.listings['Qwen'] += ['Qwen/Qwen4-Gone', 'Qwen/Qwen4-Hidden']
        world.errors[f'{HF}/Qwen/Qwen4-Gone'] = 404
        result = self.run_world(world)
        self.assertEqual((result.code, result.outputs['complete']), (0, 'true'))
        self.assertEqual((result.outcome('qwen4-gone'), result.outcome('qwen4-hidden')),
                         ('look:info_unreadable', 'look:info_unreadable'))
        self.assertIn('`Qwen/Qwen4-Gone` answered HTTP 404', result.issue)
        self.assertIn('`Qwen/Qwen4-Hidden` answered HTTP 401', result.issue)

    def outcome(self, d, lb_id):
        o = d.resolve(row(lb_id))
        return o.reason if o.kind != 'candidate' else 'candidate'

    def test_gates_and_identity(self):
        d = self.discovery(self.world())
        expect = {'qwen4-40b': 'candidate', 'qwen4-moved': 'moved_outside_publisher', 'qwen4-small-40b': 'size_mismatch',
                  'qwen4-edge-40b': 'candidate', 'qwen4-over-40b': 'size_mismatch', 'qwen4-moe-8x7b': 'candidate',
                  'qwen4-private': 'private', 'qwen4-disabled': 'disabled', 'qwen4-empty': 'no_weights_yet',
                  'qwen4-nolicense': 'no_license', 'qwen4-tagged': 'candidate', 'qwen4-gated': 'candidate',
                  'qwen4-packed': 'candidate', 'qwen4-packed-wide': 'size_unverified',
                  'qwen4-packed-named-300b': 'size_mismatch', 'qwen4-nometa': 'size_unverified', 'qwen4-base-of': 'candidate',
                  'qwen4-unreadable': 'info_unreadable'}
        self.assertEqual({k: self.outcome(d, k) for k in expect}, expect)
        gated = d.resolve(row('qwen4-gated'))
        self.assertEqual(gated.info.gated_label(), 'manual, terms must be accepted')
        o = d.resolve(row('qwen4-40b'))
        self.assertEqual((o.params.value, o.fit.cls, round(o.gate[2], 4)), (40_912_345_600, 'offload', 1.0228))
        packed = d.resolve(row('qwen4-packed'))
        self.assertEqual((packed.params.value, packed.fit.cls, packed.fit.gib), (None, 'offload', {}))
        self.assertEqual(packed.fit.label, 'over 24 GiB and within 46 GiB at Q5_K_M, Q6_K, Q8_0 at the lower bound and '
                                           'Q4_K_M at the upper bound; which precision applies depends on P within '
                                           'the packed range')
        text = md.Report.fit_text(None, packed)
        self.assertIn('Q4_K_M 22.35–44.14 GiB over the packed range → **offload**', text)
        self.assertNotIn('none of the listed precisions', text)
        self.assertNotIn('Qwen/Qwen3.8-27B', [u for u in d.net.infos_fetched()])   # base_model is never followed


# --- calibration and anchors --------------------------------------------------------------------
class CalibrationTest(Base):
    def test_calibration_passes_on_tables_built_from_the_evidence(self):
        result = self.run_world(World())
        self.assertEqual(result.code, 0, result.failure)
        self.assertEqual(result.outputs, {'complete': 'true', 'reportable': 'false', 'new': 'false'})
        cal = result.data['calibration']
        self.assertEqual([(c['table'], c['categories'], c['rows']) for c in cal],
                         [('table_2025_04_25.csv', 'categories_2025_04_25.json', 4), ('table_2025_05_30.csv', 'categories_2025_05_30.json', 1)])
        self.assertIn('calibration 5/5 recorded rows reproduced, HF anchors 4/4, matcher canary 4/4', result.issue)

    def assert_calibration_failure(self, result, needle):
        self.assertEqual(result.code, 2)
        self.assertIsNone(result.issue)
        self.assertTrue(result.failure.startswith('### Problems reading sources'), result.failure)
        self.assertIn('- Stage: `calibration`', result.failure)
        self.assertIn(needle, result.failure)
        self.assertIn('Upstream shape changed at `calibration`', result.step)
        self.assertEqual(result.outputs['complete'], 'false')

    def test_sha_mismatch_missing_row_and_shifted_cell_fail(self):
        world = World()
        root = self.root(world)
        world.reviewed_files['public/table_2025_04_25.csv'] = TABLE_2025_04.replace(b'filler-model-00', b'filler-model-99')
        self.assert_calibration_failure(self.run_world(world, root=root), 'sha256')

        world = World()
        world.reviewed_files['public/table_2025_04_25.csv'] = table(CATS_2025_04, recorded_rows('2025-04-25')[1:] + FILLERS, extra=())
        self.assert_calibration_failure(self.run_world(world), 'is not in the table')

        world = World()
        rows = recorded_rows('2025-04-25')
        lb_id, scores = rows[0]
        spec = dict(scores)
        spec['zebra_puzzle'] = repr(scores['Reasoning'] + 0.02)
        world.reviewed_files['public/table_2025_04_25.csv'] = table(CATS_2025_04, [(lb_id, spec)] + rows[1:] + FILLERS, extra=())
        self.assert_calibration_failure(self.run_world(world), 'no categories file at caa4253c8a3a reproduces')

    def test_categories_fallback(self):
        world = World()
        del world.reviewed_files['public/categories_2025_04_25.json']
        world.reviewed_files['public/categories_2025_04_02.json'] = as_json(CATS_2025_04)
        result = self.run_world(world)
        self.assertEqual(result.code, 0, result.failure)
        self.assertEqual(result.data['calibration'][0]['categories'], 'categories_2025_04_02.json')
        self.assertIn('categories file `categories_2025_04_02.json` (fallback)', result.step)
        world = World()
        del world.reviewed_files['public/categories_2025_04_25.json']
        self.assert_calibration_failure(self.run_world(world), 'reproduces the recorded scores of table_2025_04_25.csv')

    def test_taxonomy_against_the_real_benchmarks_file(self):
        self.assertIn('IF', CATS_2026)   # the passing default world names Instruction Following 'IF'
        world = World()
        moved = {k: list(v) for k, v in CATS_2026.items()}
        moved['Coding'].append(moved['Language'].pop())
        world.reviewed_files['public/categories_2026_06_25.json'] = as_json(moved)
        self.assert_calibration_failure(self.run_world(world), 'task partition of catalog/benchmarks.json')

    def test_the_excluded_example_check_is_soft(self):
        world = World()
        world.reviewed_files['public/table_2026_06_25.csv'] = table(CATS_2026, FILLERS)
        result = self.run_world(world)
        self.assertEqual((result.code, result.outputs['complete']), (0, 'true'))
        self.assertIn('overall 71.59 recorded for `zai-org/GLM-5.3-Flash`', result.step)
        self.assertIn('overall 81.11 recorded', result.step)
        self.assertNotIn('71.59', result.issue.split('Not raised')[0].replace('71.59, rank', ''))

    def test_hf_anchors(self):
        result = self.run_world(World())
        self.assertEqual([a['class'] for a in result.data['anchors']], ['float', 'packed', 'packed', 'float'])
        for field, value in (('sha', 'a' * 40), ('total', 1)):
            with self.subTest(field=field):
                world = World()
                key = next(k for k in world.revisions if k[0] == 'qwen/qwen3.8-27b')
                if field == 'sha':
                    world.revisions[key]['sha'] = value
                else:
                    world.revisions[key]['safetensors']['total'] = value
                result = self.run_world(world)
                self.assertEqual(result.code, 2)
                self.assertIn('Hugging Face metadata shape changed', result.failure)
        world = World()
        key = next(k for k in world.revisions if k[0] == 'meta-llama/llama-3.3-70b-instruct')
        world.revisions[key]['gated'] = 'auto'
        result = self.run_world(world)
        self.assertEqual(result.code, 0)
        self.assertIn('HF anchor `llama33-70b`', result.step)
        meta = BY_ID['qwen38-flash-next-strata']['upstream_metadata']['safetensors']
        self.assertEqual(meta['parameters']['I64'], 35)
        self.assertEqual(md.parameter_count(meta, [], ParameterTest.B).kind, 'float')


# --- release discovery ----------------------------------------------------------------------------
class ReleaseDiscoveryTest(Base):
    def test_newest_release_with_both_files(self):
        world = World()
        world.head_files['public/table_2026_10_30.csv'] = table(CATS_2026, DEFAULT_ROWS)
        world.head_files['public/categories_2026_10_30.json'] = as_json(CATS_2026)
        world.head_files['public/table_2026_02_30.csv'] = table(CATS_2026, DEFAULT_ROWS)   # not a date: ignored
        world.head_files['public/categories_2026_02_30.json'] = as_json(CATS_2026)
        world.head_files['public/table_latest.csv'] = b'model\n'
        world.head_files['public/table_2026_11_05.csv'] = table(CATS_2026, DEFAULT_ROWS[:5])
        result = self.run_world(world)
        self.assertEqual(result.code, 0, result.failure)
        self.assertEqual(result.data['release']['date'], '2026-10-30')
        self.assertIn('`table_2026_11_05.csv` (5 rows) has no categories file yet', result.issue)
        self.assertNotIn('release_without_categories', json.dumps(result.data['notices']))

        world.head_files['public/table_2026_11_05.csv'] = table(CATS_2026, DEFAULT_ROWS[:20])
        result = self.run_world(world)
        self.assertEqual(result.outputs['reportable'], 'true')
        self.assertEqual([n['kind'] for n in result.data['notices']], ['release_without_categories', 'new_release'])

    def test_an_in_progress_release_falls_back(self):
        world = World()
        world.head_files['public/table_2026_10_30.csv'] = table(CATS_2026, DEFAULT_ROWS[:19])
        world.head_files['public/categories_2026_10_30.json'] = as_json(CATS_2026)
        result = self.run_world(world)
        self.assertEqual(result.data['release']['date'], '2026-06-25')
        self.assertIn('release 2026-10-30 looks in progress (19 scored rows); analysing 2026-06-25', result.issue)
        world.head_files['public/table_2026_10_30.csv'] = table(CATS_2026, DEFAULT_ROWS[:md.MIN_RELEASE_ROWS])
        result = self.run_world(world)                     # exactly MIN_RELEASE_ROWS scored rows: analysed
        self.assertEqual(result.code, 0, result.failure)
        self.assertEqual((result.data['release']['date'], result.data['release']['scored_rows']), ('2026-10-30', 20))
        self.assertEqual([n['kind'] for n in result.data['notices']], ['new_release'])
        self.assertNotIn('looks in progress', result.issue)

    def test_layout_changes_exit_2(self):
        world = World()
        del world.head_files['public/categories_2026_06_25.json']
        result = self.run_world(world)
        self.assertEqual(result.code, 2)
        self.assertIn('leaderboard layout changed', result.failure)

        world = World()
        world.tree_patches.append(lambda label, path, doc: {**doc, 'truncated': True} if label == 'head' and path == 'public/' else doc)
        result = self.run_world(world)
        self.assertEqual(result.code, 2)
        self.assertIn('truncated', result.failure)

        world = World()
        for i in range(25):
            world.head_files[f'dir{i:02d}/x.txt'] = b'x'
        world.head_files = {k.replace('public/', 'data/'): v for k, v in world.head_files.items()}
        result = self.run_world(world)
        self.assertEqual(result.code, 2)
        self.assertIn('a public/ tree', result.failure)
        listed = re.search(r'Got: `entries ([^`]*)`', result.failure).group(1)
        self.assertEqual(len(listed.split(', ')), 20)

    def test_a_moved_repository_exits_2(self):
        world = World()
        world.errors[f'{GITHUB}/commits/HEAD'] = 404
        result = self.run_world(world)
        self.assertEqual(result.code, 2)
        self.assertIn('leaderboard repository moved or private', result.failure)
        world = World()
        world.errors[f'{GITHUB}/commits/HEAD'] = 500
        result = self.run_world(world)
        self.assertEqual(result.code, 1)


# --- Hugging Face listings and the canary ----------------------------------------------------------
class ListingTest(Base):
    def test_pagination_and_one_listing_per_org(self):
        world = World()
        world.page_size = 2
        result = self.run_world(world)
        self.assertEqual(result.code, 0, result.failure)
        self.assertTrue(any('cursor=' in u for u in result.net.calls))
        authors = result.net.authors()
        pages = {a: authors.count(a) for a in authors}
        self.assertEqual(pages['zai-org'], 3)    # GLM-4.5-Air + 4 extras = 5 ids, 2 per page
        firsts = [u for u in result.net.calls if u.startswith(HF + '?') and 'cursor=' not in u]
        self.assertEqual(len(firsts), len(set(firsts)))

    def test_a_full_page_without_next_link_exits_2(self):
        world = World()
        world.listings['zai-org'] = world.listings['zai-org'] + [f'zai-org/Filler-{i}' for i in range(1000 - len(world.listings['zai-org']))]
        result = self.run_world(world)
        self.assertEqual(result.code, 2)
        self.assertIn('a next link after a full page of 1000 entries', result.failure)

    def test_completeness_guard(self):
        world = World()
        world.listings['Qwen'].remove('Qwen/Qwen3.5-122B-A10B')
        world.add_model('Qwen/Qwen3.5-122B-A10B', listed=False)
        result = self.run_world(world)
        self.assertEqual(result.code, 2)
        self.assertIn('Qwen/Qwen3.5-122B-A10B exists but is not listed', result.failure)

        world = World()
        world.listings['Qwen'].remove('Qwen/Qwen3.5-122B-A10B')
        world.add_model('Qwen/Qwen3.5-122B-A10B', listed=False, canonical='Qwen/Qwen3.5-122B-A10B-Renamed')
        result = self.run_world(world)
        self.assertEqual((result.code, result.outputs['reportable']), (0, 'true'))
        self.assertIn('catalog repo renamed to `Qwen/Qwen3.5-122B-A10B-Renamed`', result.issue)

        world = World()
        world.listings['Qwen'].remove('Qwen/Qwen3.5-122B-A10B')
        result = self.run_world(world)
        self.assertEqual((result.code, result.outputs['reportable']), (0, 'true'))
        self.assertIn('Catalog repo Qwen/Qwen3.5-122B-A10B no longer on Hugging Face', result.issue)

    def test_matcher_canary(self):
        result = self.run_world(World())
        canary = {c['id']: c['result'] for c in result.data['canary']}
        self.assertEqual(canary, {'deepseek-r1-distill-qwen-32b': 'deepseek-ai/DeepSeek-R1-Distill-Qwen-32B',
                                  'deepseek-r1-distill-llama-70b': 'deepseek-ai/DeepSeek-R1-Distill-Llama-70B',
                                  'glm-4.5-air': 'zai-org/GLM-4.5-Air', 'mistral-small-2503': 'no_repo',
                                  'phi-4-reasoning-plus': 'microsoft/Phi-4-reasoning-plus'})
        world = World()
        world.listings['mistralai'].append('mistralai/Mistral-Small-2503')
        result = self.run_world(world)
        self.assertEqual(result.code, 2)
        self.assertIn('the strict matcher names mistralai/Mistral-Small-2503', result.failure)
        world = World()
        world.listings['zai-org'].append('zai-org/GLM-4.5-Air-Instruct')
        result = self.run_world(world)
        self.assertEqual(result.code, 0)
        self.assertIn('matcher canary 3/4', result.issue)
        self.assertIn('matcher canary: `glm-4.5-air` is now ambiguous', result.issue)


# --- the walk ------------------------------------------------------------------------------------
POOL_ROWS = [
    ('claude-opus-5', 90.0), ('gemini-3-pro', 89.0), ('gpt-5.5', 88.0),
    ('zz-model-9', 80.0), ('glm-5.3-flash', 79.0), ('deepseek-v4-max', 78.0),
    ('qwen4-80b', 70.0), ('qwen4-80b-thinking', 69.5), ('llama-3.3-70b-instruct', 65.0),
    ('meta-llama-3.1-70b-instruct', 62.0), ('qwen3-max', 60.0), ('llama-3.1-70b', 58.0), ('gemma-4-31b-it', 55.0),
    ('deepseek-r1-distill-qwen-32b', 50.0), ('phi-4-reasoning-plus', 49.0), ('kimi-dev-72b', 48.0), ('laguna-xs.2', 48.0),
    ('mistral-small-2503', 47.0), ('nemotron-3-nano-30b-a3b', 46.0), ('gpt-oss-20b', 45.0), ('olmo-3-32b', 40.0),
]
ALIAS = {'key': 'lb:meta-llama-3.1-70b-instruct', 'decision': 'alias', 'target': 'meta-llama/Llama-3.1-70B-Instruct',
         'reason': 'LiveBench spells the catalog Llama 3.1 70B Instruct with the org prefix', 'decided_on': TODAY}


def pool_world():
    world = World(POOL_ROWS)
    world.add_model('deepseek-ai/DeepSeek-V4-Max', total=671_000_000_000)
    world.add_model('Qwen/Qwen4-80B', total=80_400_000_000, license='apache-2.0')
    return world


class WalkTest(Base):
    def test_pool_walk(self):
        result = self.run_world(pool_world(), decisions=[ALIAS])
        self.assertEqual(result.code, 0, result.failure)
        got = {k: result.outcome(k) for k in result.rows}
        self.assertEqual(got, {
            'claude-opus-5': 'decided:not_open_weight', 'gemini-3-pro': 'decided:not_open_weight', 'gpt-5.5': 'decided:not_open_weight',
            'zz-model-9': 'look:unknown_publisher', 'glm-5.3-flash': 'known:excluded_example', 'deepseek-v4-max': 'info:too_large',
            'qwen4-80b': 'candidate', 'qwen4-80b-thinking': 'variant:candidate', 'llama-3.3-70b-instruct': 'known:catalog',
            'meta-llama-3.1-70b-instruct': 'known:alias_to_catalog', 'qwen3-max': 'look:no_repo', 'llama-3.1-70b': 'look:ambiguous',
            'gemma-4-31b-it': 'known:catalog', 'deepseek-r1-distill-qwen-32b': 'known:evidence', 'phi-4-reasoning-plus': 'known:evidence',
            'kimi-dev-72b': 'known:catalog', 'laguna-xs.2': 'known:catalog'})
        counted = [k for k, r in result.rows.items() if r['counts']]
        self.assertEqual(len(counted), 11)                       # a tie at the 10th place is included
        self.assertEqual((result.data['cutoff'], result.data['below_cutoff']), (48.0, 4))
        self.assertEqual(result.rows['qwen4-80b-thinking']['variant_of'], 'qwen4-80b')
        self.assertFalse(result.rows['glm-5.3-flash']['counts'])
        self.assertFalse(result.rows['deepseek-v4-max']['counts'])
        self.assertTrue(result.rows['zz-model-9']['counts'])
        candidates = {k for k, r in result.rows.items() if r['outcome'] == 'candidate'}
        looks = {k: r['reason'] for k, r in result.rows.items() if r['outcome'] == 'look'}
        self.assertEqual(candidates, {'qwen4-80b'})
        self.assertEqual(looks, {'zz-model-9': 'unknown_publisher', 'qwen3-max': 'no_repo', 'llama-3.1-70b': 'ambiguous'})
        authors = result.net.authors()
        self.assertEqual(len(authors), len(set(authors)))
        self.assertEqual(set(authors), {'deepseek-ai', 'zai-org', 'microsoft', 'mistralai', 'Qwen', 'meta-llama', 'google',
                                        'moonshotai', 'poolside'})
        self.assertNotIn('nvidia', authors)   # rows after the cutoff cost no request
        self.assertNotIn('openai', authors)
        self.assertEqual(sorted(result.net.infos_fetched()), ['Qwen/Qwen4-80B', 'deepseek-ai/DeepSeek-V4-Max'])
        self.assertIn('variant `qwen4-80b-thinking` 69.50', result.issue)
        self.assertEqual(result.outputs, {'complete': 'true', 'reportable': 'true', 'new': 'true'})

    def test_the_walk_stops_right_after_the_tenth_entry(self):
        # No tie at the 10th place: the 11th counting row, strictly lower, is below the cutoff and costs nothing.
        rows = [r for r in POOL_ROWS if r[0] != 'laguna-xs.2']
        rows.insert(rows.index(('mistral-small-2503', 47.0)), ('qwen4-7b', 47.5))
        world = World(rows)
        world.add_model('deepseek-ai/DeepSeek-V4-Max', total=671_000_000_000)
        world.add_model('Qwen/Qwen4-80B', total=80_400_000_000)
        world.add_model('Qwen/Qwen4-7B', total=7_600_000_000)
        result = self.run_world(world, decisions=[ALIAS])
        self.assertEqual(result.code, 0, result.failure)
        self.assertEqual(sum(r['counts'] for r in result.rows.values()), 10)
        self.assertEqual((result.data['cutoff'], result.data['below_cutoff']), (48.0, 5))
        self.assertNotIn('qwen4-7b', result.rows)
        self.assertNotIn('Qwen/Qwen4-7B', result.net.infos_fetched())
        self.assertNotIn('qwen4-7b', result.issue)

    def test_partial_rows_are_listed_only_at_or_above_the_cutoff(self):
        hi = {'Reasoning': 95.0, 'Coding': 95.0}           # five whole categories missing: no overall
        world = World([('hi-partial', hi), ('lo-partial', {'Reasoning': 1.0})] + DEFAULT_ROWS)
        result = self.run_world(world)
        self.assertEqual(result.code, 0, result.failure)
        self.assertEqual(result.data['cutoff'], 43.0)
        self.assertEqual(result.data['partial'], [{'id': 'hi-partial', 'partial_mean': 95.0, 'available': 2, 'of': 7}])
        self.assertNotIn('hi-partial', result.rows)          # not ranked, not walked
        self.assertNotIn('lo-partial', result.rows)
        self.assertEqual(result.data['release']['scored_rows'], len(DEFAULT_ROWS))
        self.assertIn('**Partial rows (1)**', result.issue)
        self.assertIn('- `hi-partial`: partial (2 of 7 categories), partial mean 95.00 (not an overall)', result.issue)
        self.assertNotIn('lo-partial', result.issue)

    def test_the_model_info_budget(self):
        ids = [f'qwen4-{i}0b' for i in range(1, 5)]
        world = World([(lb_id, 80.0 - i) for i, lb_id in enumerate(ids)] + DEFAULT_ROWS)
        for i in range(1, 5):
            world.add_model(f'Qwen/Qwen4-{i}0B', total=i * 10_000_000_000)
        with mock.patch.object(md, 'MAX_MODEL_INFO', 2):
            result = self.run_world(world)
        self.assertEqual(result.outputs['complete'], 'true')
        self.assertEqual([result.outcome(lb_id) for lb_id in ids],
                         ['candidate', 'candidate', 'look:not_checked', 'look:not_checked'])
        self.assertTrue(all(result.rows[lb_id]['counts'] for lb_id in ids))
        self.assertIn('model info', result.data['limits_hit'])
        self.assertEqual(len(result.net.infos_fetched()), 2)

    def test_decision_effects(self):
        world = World([('qwen4-14b', 99.0), ('qwen4-32b', 98.5), ('qwen4-8b', 98.0), ('secret-model-1', 97.5),
                       ('grok-4-fast', 97.0), ('nemotron-ultra-x', 96.5), ('nemotron-gone', 96.0),
                       ('qwen4-30b-instruct', 95.5), ('qwen4-30b-thinking', 95.0)] + DEFAULT_ROWS)
        world.add_model('xai-org/grok-4-fast', total=30_000_000_000)
        world.add_model('nvidia/Nemotron-Ultra-Repo', total=30_000_000_000, listed=False)
        world.add_model('Qwen/Qwen4-30B-Instruct', total=30_000_000_000)
        world.add_model('Qwen/Qwen4-30B-Thinking', total=30_000_000_000)
        reason = {'reason': 'Reviewed by the owner', 'decided_on': '2026-10-01'}
        decisions = [
            {'key': 'lb:qwen4-14b', 'decision': 'rejected', **reason},
            {'key': 'lb:qwen4-32b', 'decision': 'deferred', 'until': '2027-01-01', **reason},
            {'key': 'lb:qwen4-8b', 'decision': 'deferred', 'until': '2026-11-01', **reason},
            {'key': 'lb:secret-*', 'decision': 'not_open_weight', **reason},
            {'key': 'lb:nemotron-ultra-x', 'decision': 'alias', 'target': 'nvidia/Nemotron-Ultra-Repo', **reason},
            {'key': 'lb:nemotron-gone', 'decision': 'alias', 'target': 'nvidia/Gone-Model', **reason},
            {'key': 'hf:Qwen/Qwen4-30B*', 'decision': 'rejected', **reason},
        ]
        result = self.run_world(world, decisions=decisions)
        self.assertEqual(result.code, 0, result.failure)
        self.assertEqual({k: result.outcome(k) for k in [r[0] for r in world_rows(world)][:9]}, {
            'qwen4-14b': 'decided:rejected', 'qwen4-32b': 'decided:deferred', 'qwen4-8b': 'look:deferral_expired',
            'secret-model-1': 'decided:not_open_weight', 'grok-4-fast': 'look:weights_may_be_public',
            'nemotron-ultra-x': 'candidate', 'nemotron-gone': 'look:alias_target_unavailable',
            'qwen4-30b-instruct': 'decided:rejected', 'qwen4-30b-thinking': 'decided:rejected'})
        self.assertTrue(result.rows['qwen4-14b']['counts'] and result.rows['qwen4-32b']['counts'])
        self.assertFalse(result.rows['secret-model-1']['counts'])
        self.assertFalse([u for u in result.net.calls if 'secret' in u.casefold()])
        self.assertEqual(result.rows['nemotron-ultra-x']['match']['tier'], 'alias')
        self.assertNotIn('xai-org', result.net.authors()[:4])
        self.assertIn('nvidia/Gone-Model', result.net.infos_fetched())
        self.assertNotIn('Qwen/Qwen4-30B-Instruct', result.net.infos_fetched())   # hf: decisions apply before model info
        # The alias candidate was not matched by name: its Match line claims no uniqueness among the org's repos.
        line = next(l for l in result.issue.splitlines() if l.startswith('- Match:') and 'lb:nemotron-ultra-x' in l)
        self.assertEqual(line, '- Match: set by the alias decision `lb:nemotron-ultra-x`, not by name; model info '
                               'places the repository in the publisher org `nvidia`.')
        self.assertNotIn('unique among 0 repos', result.issue)

    def test_hf_decisions_apply_to_alias_targets(self):
        world = World([('nemotron-ultra-x', 99.0), ('nemotron-later-y', 98.0), ('nemotron-renamed-z', 97.0)]
                      + DEFAULT_ROWS)
        world.add_model('nvidia/Nemotron-Ultra-Repo', total=30_000_000_000, listed=False)
        world.add_model('nvidia/Nemotron-Later-Repo', total=30_000_000_000, listed=False)
        world.add_model('nvidia/Old-Name', total=30_000_000_000, listed=False, canonical='nvidia/Nemotron-New-Name')
        reason = {'reason': 'Reviewed by the owner', 'decided_on': '2026-10-01'}
        decisions = [
            {'key': 'lb:nemotron-ultra-x', 'decision': 'alias', 'target': 'nvidia/Nemotron-Ultra-Repo', **reason},
            {'key': 'lb:nemotron-later-y', 'decision': 'alias', 'target': 'nvidia/Nemotron-Later-Repo', **reason},
            {'key': 'lb:nemotron-renamed-z', 'decision': 'alias', 'target': 'nvidia/Old-Name', **reason},
            {'key': 'hf:nvidia/Nemotron-Ultra-Repo', 'decision': 'rejected', **reason},     # as the snippet offers it
            {'key': 'hf:nvidia/Nemotron-Later-Repo', 'decision': 'deferred', 'until': '2026-11-01', **reason},
            {'key': 'hf:nvidia/Nemotron-New*', 'decision': 'rejected', **reason},         # the canonical id
        ]
        result = self.run_world(world, decisions=decisions)
        self.assertEqual(result.code, 0, result.failure)
        self.assertEqual((result.outcome('nemotron-ultra-x'), result.outcome('nemotron-later-y'),
                          result.outcome('nemotron-renamed-z')),
                         ('decided:rejected', 'look:deferral_expired', 'decided:rejected'))
        self.assertEqual(result.rows['nemotron-ultra-x']['decision'], 'hf:nvidia/Nemotron-Ultra-Repo')
        self.assertTrue(result.rows['nemotron-ultra-x']['counts'])
        self.assertNotIn('nvidia/Nemotron-Ultra-Repo', result.net.infos_fetched())   # decided before model info
        self.assertIn('nvidia/Old-Name', result.net.infos_fetched())
        self.assertEqual(result.outputs['reportable'], 'true')                    # only the expired deferral
        self.assertEqual(result.data['keys'], ['look:nemotron-later-y|deferral_expired'])

    def test_lb_decisions_never_shadow_a_catalogued_model(self):
        reason = {'reason': 'Reviewed by the owner', 'decided_on': '2026-10-01'}
        # an lb: deferral left behind after the model was added to the catalog, once it expires
        world = World()
        result = self.run_world(world, decisions=[{'key': 'lb:gemma-4-31b-it', 'decision': 'deferred',
                                                   'until': '2026-11-01', **reason}])
        self.assertEqual(result.code, 0, result.failure)
        self.assertEqual(result.outcome('gemma-4-31b-it'), 'known:catalog')
        self.assertTrue(result.rows['gemma-4-31b-it']['counts'])
        self.assertIn('lb:gemma-4-31b-it (deferred) no longer applies', result.rows['gemma-4-31b-it']['note'])
        self.assertEqual(result.outputs, {'complete': 'true', 'reportable': 'false', 'new': 'false'})
        # not_open_weight prefixes covering a catalogued model and an evidence id
        world = World([('gemma-4-31b-it', 82.0)] + [r for r in DEFAULT_ROWS if r[0] != 'gemma-4-31b-it'])
        decisions = [{'key': 'lb:gemma-4*', 'decision': 'not_open_weight', **reason},
                     {'key': 'lb:mistral-small*', 'decision': 'not_open_weight', **reason}]
        result = self.run_world(world, decisions=decisions)
        self.assertEqual(result.code, 0, result.failure)
        self.assertEqual((result.outcome('gemma-4-31b-it'), result.outcome('mistral-small-2503')),
                         ('known:catalog', 'known:evidence'))
        self.assertTrue(result.rows['gemma-4-31b-it']['counts'] and result.rows['mistral-small-2503']['counts'])
        self.assertIn('Best catalogued model in 2026-06-25: `gemma4-31b` (`gemma-4-31b-it`) 82.00, rank 5/', result.issue)
        self.assertIn('`lb:gemma-4* (not_open_weight) no longer applies: the row resolves to google/gemma-4-31B-it '
                      '(known:catalog)`', result.issue)
        # a not_open_weight row whose strict match is public but too large is listed as too large
        world = pool_world()
        result = self.run_world(world, decisions=[ALIAS, {'key': 'lb:deepseek-v4*', 'decision': 'not_open_weight', **reason}])
        self.assertEqual(result.outcome('deepseek-v4-max'), 'info:too_large')
        self.assertFalse(result.rows['deepseek-v4-max']['counts'])
        self.assertIn('lb:deepseek-v4* (not_open_weight) no longer applies', result.rows['deepseek-v4-max']['note'])

    def test_the_known_set(self):
        world = World([('nemotron-3-super-120b-a12b-bf16', 99.0), ('llama-3.3-nemotron-70b-reward', 98.0), ('grok-1', 97.0),
                       ('grok-2', 96.0)] + DEFAULT_ROWS)
        world.listings['xai-org'] = ['xai-org/grok-1', 'xai-org/grok-2']
        world.add_model('nvidia/Llama-3.3-Nemotron-70B-Reward', total=70_553_706_496,
                        card={'license': 'other', 'license_name': 'nvidia-open-model-license', 'base_model': 'meta-llama/Llama-3.3-70B-Instruct'})
        result = self.run_world(world)
        self.assertEqual(result.outcome('nemotron-3-super-120b-a12b-bf16'), 'known:precision_sibling')
        self.assertEqual(result.rows['nemotron-3-super-120b-a12b-bf16']['catalog_id'], 'nemotron-super-120b')
        self.assertEqual(result.outcome('llama-3.3-nemotron-70b-reward'), 'candidate')   # a finetune is raised
        self.assertEqual(result.outcome('grok-1'), 'known:catalog')
        self.assertFalse(result.rows['grok-1']['counts'])   # excluded catalog entry (and too large)
        self.assertEqual(result.outcome('grok-2'), 'known:catalog')
        self.assertIsNone(result.rows['grok-2'].get('fit'))
        self.assertFalse(result.rows['grok-2']['counts'])   # excluded, with no size: excluded alone keeps it out
        self.assertEqual(result.outcome('glm-4.5-air'), 'known:evidence')
        self.assertEqual(result.outcome('glm-5.3-flash'), 'known:excluded_example')
        d = self.discovery(World())
        self.assertEqual(d.known_repo('qwen/QWEN3.8-27b')[0], 'catalog')
        self.assertIn('license `other (nvidia-open-model-license)`', result.issue)


def world_rows(world):
    text = world.head_files['public/table_2026_06_25.csv'].decode('utf-8')
    return [(r[0],) for r in list(csv.reader(io.StringIO(text)))[1:]]


class NoticeTest(Base):
    def new_release_world(self):
        world = World()
        world.head_files['public/table_2026_10_30.csv'] = table(CATS_2026, DEFAULT_ROWS)
        world.head_files['public/categories_2026_10_30.json'] = as_json(CATS_2026)
        return world

    def test_a_new_release(self):
        result = self.run_world(self.new_release_world())
        self.assertEqual(result.outputs['reportable'], 'true')
        self.assertIn('LiveBench publishes release 2026-10-30 (24 scored rows) at new-livebench@', result.issue)
        self.assertIn('2026-10-30 is not in `src/llm_eval/livebench.py` RELEASES', result.issue)
        self.assertIn('7 categories / 23 tasks: the same partition', result.issue)
        result = self.run_world(self.new_release_world(), releases_extra=('2026-10-30',))
        self.assertIn('2026-10-30 is in `src/llm_eval/livebench.py` RELEASES', result.issue)
        result = self.run_world(self.new_release_world(), evidence=lambda ev: ev.update(latest_release='2026-10-30'))
        self.assertEqual(result.code, 0, result.failure)
        self.assertEqual(result.outputs['reportable'], 'false')
        self.assertEqual(result.data['notices'], [])

    def test_averaging_change_withholds_candidates(self):
        world = pool_world()
        world.head_files['src/Table/Averaging.js'] = AVERAGING + b'// changed\n'
        result = self.run_world(world, decisions=[ALIAS])
        self.assertEqual(result.outputs['reportable'], 'true')
        self.assertIn('leaderboard averaging code changed since caa4253c8a3a', result.issue)
        self.assertIn(f'/compare/{REVIEWED}...{HEAD}', result.issue)
        self.assertIn('### Candidates (0)', result.issue)
        self.assertNotIn('Qwen4-80B', result.issue)
        self.assertNotIn('qwen4-80b ', result.issue)
        self.assertIn('Qwen/Qwen4-80B', result.step)
        self.assertEqual(result.outcome('qwen4-80b'), 'candidate')
        self.assertTrue(result.data['withheld'])
        world = World()
        del world.head_files['src/Table/Averaging.js']
        result = self.run_world(world)
        self.assertIn('Averaging.js is gone at head', result.issue)

    def test_categories_drift_for_the_reference_release(self):
        world = World()
        moved = {k: list(v) for k, v in CATS_2026.items()}
        moved['Coding'].append(moved['Language'].pop())
        world.head_files['public/categories_2026_06_25.json'] = as_json(moved)
        world.head_files['public/table_2026_06_25.csv'] = table(moved, DEFAULT_ROWS)
        result = self.run_world(world)
        self.assertEqual((result.code, result.outputs['reportable']), (0, 'true'))
        self.assertEqual([n['kind'] for n in result.data['notices']], ['categories_drift'])
        self.assertIn('tasks moved `typos` (`Language` → `Coding`)', result.issue)
        clears = next(l for l in result.issue.splitlines() if l.startswith('- Clears when catalog/benchmarks.json'))
        for needle in ('`leaderboard_revision`', 'every `source_table` URL', f'`{HEAD[:12]}`', '`source_sha256`',
                       'editing benchmarks.json alone fails every run'):
            self.assertIn(needle, clears)

        def move_typos(doc):
            by_name = {c['name']: c for c in doc['categories']}
            by_name['Language']['livebench_tasks'].remove('typos')
            by_name['Coding']['livebench_tasks'].append('typos')
        # benchmarks.json alone: calibration still reads the partition at leaderboard_revision, and says what to do
        result = self.run_world(world, benchmarks=move_typos)
        self.assertEqual(result.code, 2)
        self.assertIn('- Stage: `calibration`', result.failure)
        self.assertIn('re-pin leaderboard_revision when benchmarks.json changes', result.failure)

        def repin_to_head(ev):
            ev['leaderboard_revision'] = HEAD
            for rec in ev['recommendations']:
                rec['source_table'] = rec['source_table'].replace(f'/blob/{REVIEWED}/', f'/blob/{HEAD}/')
        # both, as the notice says: complete, and nothing left to decide
        result = self.run_world(world, benchmarks=move_typos, evidence=repin_to_head)
        self.assertEqual(result.code, 0, result.failure)
        self.assertEqual(result.data['sources']['reviewed'], HEAD)
        self.assertEqual((result.outputs['reportable'], result.data['notices']), ('false', []))


# --- outputs ---------------------------------------------------------------------------------------
def snippets(body):
    return [json.loads(m) for m in re.findall(r'```json\n(.*?)\n\s*```', body, re.S)]


def outside_code(body):
    body = re.sub(r'```.*?```', '', body, flags=re.S)
    return re.sub(r'`[^`\n]*`', '', body)


class RenderingTest(Base):
    def test_the_issue_body(self):
        result = self.run_world(pool_world(), decisions=[ALIAS])
        body = result.issue
        self.assertTrue(body.startswith('## LiveBench model discovery\n'))
        self.assertIn('> ' + md.DISCLAIMER.format(release='2026-06-25'), body)
        self.assertEqual(md.DISCLAIMER.format(release='R'), (
            "Scores are LiveBench's published scores for the source checkpoints in release R. They rank models only within "
            "that release; they are not comparable with other releases (including the older-release scores in "
            "catalog/livebench-evidence.json) and are not local, quantized or engine-specific results. LiveBench may have "
            "served a model through a hosted provider at its own precision and reasoning settings. Fit is planning "
            "arithmetic (GiB = 2^30 bytes) on the published parameter count, for weights only. Nothing here edits the "
            "catalog: adding a model still needs review of its license file, a real artifact, engine architecture "
            "support and measured fit."))
        for heading in ('### Notices (0)', '### Candidates (1)', '### Needs a look (3)', '<details><summary>Not raised (',
                        'How to record a decision: see `docs/MODEL_DISCOVERY.md`.'):
            self.assertIn(heading, body)
        self.assertLess(body.index('### Candidates'), body.index('### Needs a look'))
        urls = re.findall(r'\]\((https?://[^)]+)\)', body)
        self.assertTrue(urls)
        for url in urls:
            if 'github.com/LiveBench' in url:
                self.assertRegex(url, rf'/(tree|blob)/{HEAD}(/|$)')    # the head commit, never the reviewed one
                self.assertNotIn('/main/', url)
            elif 'huggingface.co' in url:
                self.assertRegex(url, r'/(tree|revision|blob)/[0-9a-f]{40}')
            else:
                self.fail(url)
        self.assertNotIn('blob/main', body)
        for sha in re.findall(r'sha256 `([^`]*)`', body):
            self.assertRegex(sha, r'^[0-9a-f]{64}$')
        self.assertIn('?plain=1#L8', body)
        found = snippets(body)
        self.assertEqual(len(found), 6)   # reject + upstream_metadata + evidence stanza, and three look snippets
        decisions = [s for s in found if 'decision' in s]
        self.assertEqual(len(decisions), 4)
        meta = next(s for s in found if set(s) == {'id', 'sha', 'gated', 'safetensors'})
        self.assertEqual(meta['id'], 'Qwen/Qwen4-80B')
        stanza = next(s for s in found if 'leaderboard_model_id' in s)
        self.assertEqual(stanza['meaning'], EVIDENCE['recommendations'][0]['meaning'])
        self.assertEqual(stanza['source_sha256'], result.data['release']['table_sha256'])
        self.assertEqual(stanza['source_table'], f'https://github.com/{REPO}/blob/{HEAD}/public/table_2026_06_25.csv')
        # The stanza names head, the evidence file one commit for every recommendation: the snippet says so.
        self.assertIn(f'Its `source_table` is pinned to head `{HEAD[:12]}`, but every recommendation must name one '
                      f'commit, `leaderboard_revision` (now `{REVIEWED[:12]}`): add it only together with moving '
                      f'`leaderboard_revision` and every existing `source_table` URL to `{HEAD[:12]}`', body)
        by_id = {m['id']: md.CatalogModel(m['id'], m['upstream_repo'], m['status'], None, None) for m in MODELS['models']}
        ev = json.loads(json.dumps(EVIDENCE))
        ev['recommendations'].append({**stanza, 'model_id': 'qwen38-27b'})
        with self.assertRaises(md.ConfigError) as ctx:      # pasted alone
            md.parse_evidence(ev, by_id)
        self.assertIn('differ from leaderboard_revision', str(ctx.exception))
        ev['leaderboard_revision'] = HEAD
        for rec in ev['recommendations']:
            rec['source_table'] = rec['source_table'].replace(f'/blob/{REVIEWED}/', f'/blob/{HEAD}/')
        self.assertEqual(md.parse_evidence(ev, by_id).revision, HEAD)   # with everything moved to head
        catalog = {m['upstream_repo'].casefold() for m in MODELS['models']}
        evidence = {r['leaderboard_model_id'] for r in EVIDENCE['recommendations']}
        for d in decisions:
            self.assertTrue(md.decision_errors([d], catalog, evidence, TODAY_DATE), d)    # TODO fails as pasted
            fixed = {**d, 'reason': 'Reviewed: not for this laptop'}
            if fixed.get('target') == 'TODO':
                fixed['target'] = 'meta-llama/Llama-3.1-70B-Instruct'
            self.assertEqual(md.decision_errors([fixed], catalog, evidence, TODAY_DATE), [], fixed)
        self.assertIn('Match: exact; org `Qwen` via prefix `qwen`, unique among', body)
        self.assertIn('Parameters: 80,400,000,000 from safetensors metadata (`BF16`).', body)
        self.assertIn('→ **offload**', body)
        self.assertIn(md.PLANNING_CAVEAT, body)
        self.assertIn('Best catalogued model in 2026-06-25: `llama33-70b` (`llama-3.3-70b-instruct`) 65.00, rank 9/', body)
        self.assertIn('- `deepseek-v4-max` 78.00 → `deepseek-ai/DeepSeek-V4-Max`: Q4_K_M 374.95 / IQ2_XS 180.44 GiB: '
                      'would fit 70 GiB only at 0.90 bits per weight or fewer; not a catalog tier', body)
        self.assertIn('| 2026-06-25 | 70.00 | 7/21 | +5.00 |', body)

    def test_nothing_reportable_keeps_the_header_and_the_collapsed_lists(self):
        result = self.run_world(World())
        self.assertIn(md.NOTHING_NEEDED.format(n=10, release='2026-06-25'), result.issue)
        self.assertNotIn('### Candidates', result.issue)
        self.assertIn('<details><summary>Not raised (', result.issue)
        self.assertIn('<!-- model-discovery-state v1 ', result.issue)
        self.assertTrue(result.comment.startswith('No unreviewed model among the 10 best entries of LiveBench release '
                                                  '2026-06-25 (new-livebench@'))
        self.assertIn('needs a decision, and no notice is open (this run); closing.', result.comment)

    def test_the_run_link_and_the_runners_environment(self):
        actions = {'GITHUB_ACTIONS': 'true', 'GITHUB_RUN_ID': '987654', 'GITHUB_SERVER_URL': 'https://github.com',
                   'GITHUB_REPOSITORY': 'asanderson/llm-eval', 'GITHUB_TOKEN': 'gh-secret', 'HF_TOKEN': 'hf-secret'}
        with mock.patch.dict(os.environ, actions):          # as on a GitHub Actions runner
            result = self.run_world(World())
        self.assertIn('no notice is open (this run); closing.', result.comment)
        run = {'GITHUB_RUN_ID': '123', 'GITHUB_SERVER_URL': 'https://github.com', 'GITHUB_REPOSITORY': 'o/r'}
        result = self.run_world(World(), env=run)
        self.assertIn('no notice is open ([run 123](https://github.com/o/r/actions/runs/123)); closing.', result.comment)
        world = World()
        world.head_files['public/table_2026_06_25.csv'] = b'id,x\na,1\n'
        result = self.run_world(world, env=run)
        self.assertIn('- Run: [run 123](https://github.com/o/r/actions/runs/123) on 2026-11-08', result.failure)
        self.assertEqual(md.run_reference({**run, 'GITHUB_RUN_ID': '12; rm'}), 'this run')

    def test_sanitization(self):
        nasty = '@owner <img src=x> |`x\n'
        long_id = 'zz-' + 'x' * 300
        world = World([(nasty, 99.0), (long_id, 98.0)] + DEFAULT_ROWS)
        result = self.run_world(world)
        body = result.issue
        self.assertIn('`@owner <img src=x> \\|x`', body)
        rest = outside_code(body)
        self.assertNotIn('@owner', rest)
        self.assertNotIn('<img', rest)
        line = next(l for l in body.splitlines() if '@owner' in l and l.startswith('- '))
        self.assertEqual(line.count('`') % 2, 0)
        bullet = next(l for l in body.splitlines() if l.startswith('- `zz-x'))
        span = re.match(r'- `([^`]*)`', bullet).group(1)
        self.assertEqual((len(span), span[-1]), (120, '…'))
        self.assertEqual(md.md_code('a\r\nb\tc  d|e`f'), '`ab c d\\|ef`')
        self.assertEqual(md.md_code('x' * 200), '`' + 'x' * 119 + '…`')
        self.assertEqual(md.md_code('\u202ex'), '`x`')
        self.assertIn(json.dumps('lb:' + nasty), body)          # the snippet keeps the exact id, JSON-escaped in a code block
        comment = result.comment                               # posted with gh issue comment: it notifies
        self.assertIn('- needs a look: `@owner <img src=x> \\|x` (unknown_publisher)', comment)
        rest = outside_code(comment)
        self.assertNotIn('@owner', rest)
        self.assertNotIn('<img', rest)
        for line in comment.splitlines():
            self.assertEqual(line.count('`') % 2, 0, line)
        long_line = next(l for l in comment.splitlines() if '`zz-x' in l)
        self.assertEqual(len(re.search(r'`([^`]*)`', long_line).group(1)), 120)

    def test_the_size_cap(self):
        rows = [(f'zz-unknown-{i:03d}', 60.0) for i in range(500)]
        rows = [(f'claude-v{i:02d}', 99.0 - i * 0.1) for i in range(40)] + [('qwen4-80b', 70.0)] + rows + DEFAULT_ROWS
        world = World(rows)
        world.add_model('Qwen/Qwen4-80B', total=80_400_000_000)
        world.head_files['public/table_2026_11_05.csv'] = table(CATS_2026, DEFAULT_ROWS)
        result = self.run_world(world)
        body = result.issue
        self.assertLessEqual(len(body), md.ISSUE_BODY_CAP)
        self.assertIn('#### `qwen4-80b` →', body)
        self.assertIn('Release 2026-11-05 published without a categories file', body)
        self.assertIn('more in the run artifact', body)
        self.assertIn('- **unknown_publisher**: 500 rows', body)
        self.assertEqual(sum(1 for r in result.data['rows'] if r['reason'] == 'unknown_publisher'), 500)
        self.assertNotIn('zz-unknown-499', body)          # look rows are summarised as counts last
        self.assertIn('discovery.json', body)


class MarkerTest(Base):
    def test_round_trip_and_new_keys(self):
        state = {'release': '2026-06-25', 'head': HEAD, 'table_sha256': 'a' * 64, 'keys': ['cand:x|o/x', 'look:y|no_repo'], 'on': TODAY}
        self.assertEqual(md.decode_marker('text\n' + md.encode_marker(state) + '\n'), state)
        self.assertIsNone(md.decode_marker('<!-- model-discovery-state v1 !!!! -->'))
        self.assertIsNone(md.decode_marker('<!-- model-discovery-state v1 ' + 'A' * (md.MARKER_CAP + 10) + ' -->'))
        self.assertIsNone(md.decode_marker(''))
        deep = '<!-- model-discovery-state v1 ' + base64.urlsafe_b64encode(b'[' * 20000).decode('ascii') + ' -->'
        self.assertLess(len(deep), md.MARKER_CAP)
        self.assertIsNone(md.decode_marker(deep))             # RecursionError inside json.loads: a corrupt marker
        big = {**state, 'keys': [f'look:{"x" * 200}-{i}|no_repo' for i in range(500)]}
        self.assertLessEqual(len(md.encode_marker(big)), md.MARKER_CAP)

        first = self.run_world(pool_world(), decisions=[ALIAS])
        self.assertEqual(first.outputs['new'], 'true')
        again = self.run_world(pool_world(), decisions=[ALIAS], previous=first.issue)
        self.assertEqual(again.outputs['new'], 'false')
        self.assertNotIn('(new since last refresh)', again.issue)
        self.assertIsNone(again.comment)
        prev = md.decode_marker(first.issue)
        partial = md.encode_marker({**prev, 'keys': [k for k in prev['keys'] if not k.startswith('cand:')]})
        third = self.run_world(pool_world(), decisions=[ALIAS], previous=partial)
        self.assertEqual(third.outputs['new'], 'true')
        self.assertEqual(third.data['new_keys'], ['cand:qwen4-80b|Qwen/Qwen4-80B'])
        self.assertIn('- candidate `qwen4-80b` → `Qwen/Qwen4-80B`', third.comment)
        self.assertNotIn('needs a look', third.comment)
        for corrupt in ('<!-- model-discovery-state v1 e30 -->', 'garbage'):
            r = self.run_world(pool_world(), decisions=[ALIAS], previous=corrupt)
            self.assertEqual(r.outputs['new'], 'true')
            self.assertEqual(r.data['new_keys'], r.data['keys'])
            self.assertEqual(strip_new(r.issue), strip_new(first.issue))
        r = self.run_world(pool_world(), decisions=[ALIAS], previous='body\n' + deep + '\n')
        self.assertEqual((r.code, r.outputs['new']), (0, 'true'))
        self.assertEqual(r.data['new_keys'], r.data['keys'])
        self.assertIn('## LiveBench model discovery: step summary', r.step)
        world = World()
        world.head_files['public/table_2026_06_25.csv'] = b'id,x\na,1\n'
        r = self.run_world(world, previous='old body\n' + deep + '\n')
        self.assertEqual((r.code, r.outputs['complete']), (2, 'false'))
        self.assertTrue(r.failure.startswith('### Problems reading sources'), r.failure)
        self.assertIn('Nothing below was refreshed since the last good run (date unknown).', r.failure)
        self.assertIn('Upstream shape changed at `release table`', r.step)
        self.assertIsNotNone(r.data)
        everything = md.encode_marker({**prev, 'keys': prev['keys'] + ['cand:zz-model-9|x/y', 'look:anything|no_repo']})
        r = self.run_world(pool_world(), decisions=[ALIAS], previous=everything)
        self.assertEqual(strip_new(r.issue), strip_new(first.issue))   # a marker never suppresses a row


def strip_new(body):
    body = body.replace(' (new since last refresh)', '')
    return md.MARKER_RE.sub('', body)


class RoundTripTest(Base):
    def test_a_filled_in_snippet_records_the_decision(self):
        world = World([('qwen4-80b', 99.0)] + DEFAULT_ROWS)
        world.add_model('Qwen/Qwen4-80B', total=80_400_000_000)
        first = self.run_world(world)
        self.assertEqual(first.outputs['reportable'], 'true')
        reject = next(s for s in snippets(first.issue) if s.get('decision') == 'rejected')
        reject['reason'] = 'Reviewed: architecture not yet supported by any catalog engine'
        second = self.run_world(world, decisions=[reject])
        self.assertEqual(second.code, 0, second.failure)
        self.assertEqual(second.outcome('qwen4-80b'), 'decided:rejected')
        self.assertEqual(second.outputs, {'complete': 'true', 'reportable': 'false', 'new': 'false'})
        self.assertTrue(second.comment.startswith('No unreviewed model among the 10 best entries'))
        self.assertIn('Reviewed: architecture not yet supported', second.issue)


class FailureTest(Base):
    PREVIOUS = ('_Refreshed by the nightly model discovery ([run 1](https://github.com/o/r/actions/runs/1))._\n\n'
                '## LiveBench model discovery\n\nold candidates\n\n'
                '<!-- model-discovery-state v1 ' + base64.urlsafe_b64encode(json.dumps({'keys': [], 'on': '2026-11-01'}).encode()).decode() + ' -->\n')

    def test_a_shape_error(self):
        world = World()
        world.head_files['public/table_2026_06_25.csv'] = b'id,x\n' + b'a' * 400 + b'\n'
        older = '### Problems reading sources\n\n- Stage: `old`\n\n<!-- model-discovery-failure-end -->\n\n' + self.PREVIOUS
        result = self.run_world(world, previous=older)
        self.assertEqual(result.code, 2)
        self.assertIsNone(result.issue)
        body = result.failure
        self.assertTrue(body.startswith('### Problems reading sources\n\n- Stage: `release table`\n- Expected: '), body)
        got = re.search(r'- Got: `([^`]*)`', body).group(1)
        self.assertLessEqual(len(got), md.EXCERPT_CAP)
        self.assertIn('Nothing below was refreshed since 2026-11-01.', body)
        self.assertEqual(body.count('### Problems reading sources'), 1)
        self.assertNotIn('Stage: `old`', body)
        self.assertIn('old candidates', body)
        self.assertIn('Upstream shape changed at `release table`', result.step)
        self.assertEqual(result.outputs['complete'], 'false')
        self.assertIn('model discovery failed', result.stderr)

    def test_network_and_unexpected_errors(self):
        world = World()
        net = world.net()
        net.fail['/git/trees/'] = md.NetworkError('api.github.com/repos/x: TimeoutError after 5 attempts')
        result = self.run_world(world, net=net)
        self.assertEqual(result.code, 1)
        self.assertIn('Network failure at `leaderboard trees`', result.step)
        self.assertTrue(result.failure.startswith('### Problems reading sources'))
        net = world.net()
        net.fail['/api/models?author='] = RuntimeError('upstream says <script>secret</script>')
        result = self.run_world(world, net=net)
        self.assertEqual(result.code, 3)
        self.assertIn('RuntimeError', result.failure)
        for text in (result.failure, result.step, result.stderr):
            self.assertNotIn('secret', text)
        self.assertIsNone(result.issue)

    def test_github_output_and_probe(self):
        result = self.run_world(World())
        self.assertEqual(list(result.outputs), ['complete', 'reportable', 'new'])
        self.assertTrue(all(v in ('true', 'false') for v in result.outputs.values()))
        world = World()
        world.head_files['public/table_2026_06_25.csv'] = b'name,score\nalpha,1\nbeta,2\n'
        result = self.run_world(world, '--probe')
        self.assertEqual(result.code, 0, result.stderr)
        self.assertEqual(result.outputs, {'complete': 'false', 'reportable': 'false', 'new': 'false'})
        self.assertIsNone(result.issue)
        self.assertIsNone(result.comment)
        self.assertIsNone(result.failure)
        self.assertIn('no model column', result.step)
        self.assertIn('listing google', result.step)
        self.assertIn('categories files at caa4253c8a3a', result.step)
        self.assertIn('anchor nemotron-super-120b revision', result.step)
        net = world.net()
        net.fail['api.github.com'] = md.NetworkError('down')
        result = self.run_world(world, '--probe', net=net)
        self.assertEqual(result.code, 1)
        self.assertEqual(result.outputs['complete'], 'false')

    def test_the_probe_reports_what_the_leaderboard_site_serves(self):
        world = World()
        html = (b'<!doctype html><html><head><script type="module" crossorigin src="/assets/index-abc123.js"></script>'
                b'<link rel="stylesheet" href="/assets/index-abc123.css"></head><body></body></html>')
        bundle = (b'const R=["2026-06-25","2025-05-30"];fetch(`/table_${d}.csv`);import("/assets/Table-def456.js");'
                  b'const c="categories_2026_06_25.json";')
        chunk = b'function Averaging(t){return t}'
        world.site = {'/': ({'content-type': 'text/html'}, html),
                      '/assets/index-abc123.js': ({'content-type': 'text/javascript'}, bundle),
                      '/assets/Table-def456.js': ({'content-type': 'text/javascript'}, chunk),
                      '/table_2025_04_25.csv': ({'content-type': 'text/csv'}, TABLE_2025_04),
                      '/table_2025_05_30.csv': ({'content-type': 'text/csv'}, TABLE_2025_05 + b'changed'),
                      '/categories_2026_06_25.json': ({'content-type': 'application/json'}, as_json(CATS_2026)),
                      '/no-such-page': ({'content-type': 'text/html'}, html)}
        net = world.net()
        result = self.run_world(world, '--probe', net=net)
        self.assertEqual(result.code, 0, result.stderr)
        step = result.step
        self.assertIn('scripts `/assets/index-abc123.js`', step)
        self.assertIn('release-file names `categories_2026_06_25.json`', step)
        self.assertIn('dates `2025-05-30, 2026-06-25, 2026_06_25`', step)
        self.assertIn('script `/assets/Table-def456.js`', step)            # chunks a script imports are followed
        self.assertIn('/table_2025_04_25.csv: HTTP 200', step)
        self.assertIn('equal to the recorded source_sha256', step)
        self.assertIn('/table_2025_05_30.csv: HTTP 200', step)
        self.assertIn('DIFFERS from the recorded source_sha256', step)
        self.assertIn('/public/table_2026_06_25.csv: HTTP 404', step)    # the root path missed, the public/ one is tried
        self.assertIn('unknown /table_1999_01_01.csv: HTTP 404', step)
        self.assertIn('unknown /no-such-page: HTTP 200', step)          # a single-page-app fallback shows up here
        self.assertIn('page https://www.livebench.ai/: HTTP 200', step)
        site_calls = [u for u in net.calls if 'livebench.ai' in u]
        self.assertTrue(all(u.startswith(('https://livebench.ai/', 'https://www.livebench.ai/')) for u in site_calls))

    def test_no_repository_writes(self):
        world = pool_world()
        root = self.root(world, decisions=[ALIAS])
        before = {p: p.read_bytes() for p in root.rglob('*') if p.is_file()}
        real = {p: p.read_bytes() for p in (ROOT / 'catalog').iterdir()}
        result = self.run_world(world, root=root)
        self.assertEqual(result.code, 0, result.failure)
        self.assertEqual({p: p.read_bytes() for p in root.rglob('*') if p.is_file()}, before)
        self.assertEqual({p: p.read_bytes() for p in (ROOT / 'catalog').iterdir()}, real)
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(io.StringIO()):
            code = md.main(['--today', TODAY], net=pool_world().net(), root=root)
        self.assertEqual(code, 0)
        self.assertIn('qwen4-80b', stdout.getvalue())
        self.assertEqual({p: p.read_bytes() for p in root.rglob('*') if p.is_file()}, before)


# --- workflow ----------------------------------------------------------------------------------------
class WorkflowTest(unittest.TestCase):
    TEXT = (ROOT / '.github/workflows/model-discovery.yml').read_text(encoding='utf-8')
    PINS = (ROOT / '.github/workflows/upstream-pins.yml').read_text(encoding='utf-8')

    def block(self, name):
        m = re.search(rf'^ {{6}}- name: {re.escape(name)}\n(.*?)(?=^ {{6}}- (?:name|uses):|\Z)', self.TEXT, re.S | re.M)
        self.assertIsNotNone(m, name)
        return m.group(1)

    def test_permissions_triggers_and_pins(self):
        perms = re.search(r'^permissions:\n((?:  .*\n)+)', self.TEXT, re.M).group(1)
        self.assertEqual(sorted(l.strip() for l in perms.splitlines()), ['actions: read', 'contents: read', 'issues: write'])
        self.assertNotIn('pull-requests', self.TEXT)
        for banned in ('git push', 'git commit', 'gh pr', 'contents: write'):
            self.assertNotIn(banned, self.TEXT)
        self.assertIn('- cron: "47 6 * * *"', self.TEXT)
        pins_cron = re.search(r'cron: "([^"]+)"', self.PINS).group(1)
        self.assertNotEqual(pins_cron, '47 6 * * *')
        push = re.search(r'^  push:\n(.*?)^  pull_request:', self.TEXT, re.S | re.M).group(1)
        for path in ('catalog/model-discovery.json', 'catalog/models.json', 'catalog/livebench-evidence.json',
                     'catalog/benchmarks.json', 'scripts/model_discovery.py', '.github/workflows/model-discovery.yml'):
            self.assertIn(f'- {path}', push)
        self.assertIn('branches: [main]', push)
        pr = re.search(r'^  pull_request:\n    paths:.*\n((?:      - .*\n)+)', self.TEXT, re.M).group(1)
        self.assertEqual(sorted(l.strip()[2:] for l in pr.splitlines()),
                         sorted(['scripts/model_discovery.py', '.github/workflows/model-discovery.yml',
                                 'catalog/model-discovery.json', 'catalog/livebench-evidence.json',
                                 'catalog/benchmarks.json', 'tests/test_model_discovery.py']))
        uses = re.findall(r'uses: (\S+)', self.TEXT)
        self.assertEqual(len(uses), 2)
        for u in uses:
            self.assertRegex(u, r'^[\w.-]+/[\w.-]+@[0-9a-f]{40}$')
        checkout = re.search(r'actions/checkout@([0-9a-f]{40})', self.PINS).group(1)
        self.assertIn(f'actions/checkout@{checkout}', self.TEXT)
        self.assertIn('actions/upload-artifact@cf430e030ddbb5b0abf93d22962f4752f3646cd9 # v7.0.2', self.TEXT)
        self.assertIn('leaderboard discovery', self.PINS.lower())

    def test_only_schedule_main_push_and_dispatch_touch_the_issue(self):
        for name in ('Refresh the tracking issue', 'Close the tracking issue'):
            cond = re.search(r'if: >-\n((?:\s{10}.*\n)+)', self.block(name)).group(1)
            self.assertNotIn('pull_request', cond)
            self.assertIn("github.event_name == 'schedule'", cond)
            self.assertIn("(github.event_name == 'push' && github.ref == 'refs/heads/main')", cond)
            self.assertIn("(github.event_name == 'workflow_dispatch' && inputs.update_issue)", cond)
            self.assertIn("steps.discover.outputs.complete == 'true'", cond)
        streak = self.block('Report repeated failures in the issue')
        self.assertIn("if: failure() && steps.discover.outcome == 'failure' && github.event_name == 'schedule'", streak)
        self.assertIn(f'FAILURE_STREAK: {md.FAILURE_STREAK}', streak)
        self.assertIn('index(false) // length', streak)
        for name in ('Refresh the tracking issue', 'Close the tracking issue', 'Report repeated failures in the issue',
                     'Read the tracking issue'):
            self.assertIn('GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}', self.block(name))
        discover = self.block('Discover')
        for flag in ('--previous-issue', '--issue-summary', '--comment', '--failure-summary', '--step-summary',
                     '--json', '--github-output', '--record', '--probe'):
            self.assertIn(flag, discover)
        self.assertIn("python3 -m unittest discover -s tests -p 'test_model_discovery.py' -v", self.TEXT)
        self.assertIn('ISSUE_TITLE: "LiveBench models needing a catalog decision"', self.TEXT)
        self.assertIn('retention-days: 14', self.TEXT)
        self.assertIn('if-no-files-found: ignore', self.TEXT)

    def test_the_tracking_issue_is_one_the_workflow_created(self):
        read = self.block('Read the tracking issue')
        self.assertNotIn('--search', read)          # matches anyone's issue by title, and the search index lags
        self.assertNotIn('gh issue list', read)
        self.assertEqual(read.count('gh api "repos/$GITHUB_REPOSITORY/issues?state='), 2)
        self.assertEqual(read.count('&labels=$ISSUE_LABEL&'), 2)
        mine = re.search(r"^\s*mine='([^']*)'$", read, re.M).group(1)
        self.assertIn('.user.login == "github-actions[bot]"', mine)
        self.assertIn('.title == env.ISSUE_TITLE', mine)
        self.assertIn('.pull_request == null', mine)
        tails = re.findall(r'--jq "\$mine \| ([^"]*)"', read)
        self.assertEqual(tails, ['.[0].number // empty', 'sort_by(.closed_at) | last | .number // empty'])
        jq = shutil.which('jq')
        if not jq:
            self.skipTest('jq is not installed; the filter text is checked above')
        title = 'LiveBench models needing a catalog decision'
        bot, stranger = {'login': 'github-actions[bot]'}, {'login': 'someone'}
        issues = [{'number': 9, 'title': title, 'user': stranger, 'closed_at': '2026-11-07T00:00:00Z'},
                  {'number': 8, 'title': title, 'user': bot, 'pull_request': {}, 'closed_at': '2026-11-06T00:00:00Z'},
                  {'number': 5, 'title': title, 'user': bot, 'closed_at': '2026-11-01T00:00:00Z'},
                  {'number': 3, 'title': title, 'user': bot, 'closed_at': '2026-10-01T00:00:00Z'},
                  {'number': 2, 'title': title + ' (copy)', 'user': bot, 'closed_at': '2026-11-08T00:00:00Z'}]
        env = {**os.environ, 'ISSUE_TITLE': title}
        for tail, expected in zip(tails, ('5', '5')):
            out = subprocess.run([jq, '-r', f'{mine} | {tail}'], input=json.dumps(issues), capture_output=True,
                                 text=True, encoding='utf-8', env=env, check=True).stdout.strip()
            self.assertEqual(out, expected, tail)
        out = subprocess.run([jq, '-r', f'{mine} | {tails[1]}'], input=json.dumps(issues[:2]), capture_output=True,
                             text=True, encoding='utf-8', env=env, check=True).stdout.strip()
        self.assertEqual(out, '')                   # only a stranger's issue: none, so the workflow creates its own

    def test_the_run_deadline_ends_the_reads_before_the_job_timeout(self):
        minutes = int(re.search(r'^    timeout-minutes: (\d+)$', self.TEXT, re.M).group(1))
        # five minutes are left for checkout, the offline tests, the issue reads and writes and the upload
        self.assertLessEqual(md.RUN_DEADLINE + 5 * 60, minutes * 60)


if __name__ == '__main__':
    unittest.main()
