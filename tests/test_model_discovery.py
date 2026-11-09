"""Offline tests for scripts/model_discovery.py.

Every upstream is scripted by FakeNet: livebench.ai (the page, asset-manifest.json, a main script carrying both
release lists, LiveBench's model registries and the averaging code's weights literal, and the v1 and 2.0 release
files), Hugging Face listings, model info and revision answers. The fixture files are hand-authored in the shapes the
CI probe recorded from the real site on 2026-11-08; the script excerpts below are copied from the real bundle
(main.1e1ce12d.js) with the lists and registries cut down. The calibration tables are built from the rows recorded in
catalog/livebench-evidence.json; their sha256 cannot equal the recorded one, so each run uses a fixture root whose
copy of the evidence file carries the fixture hashes. The production check (sha256 of the served file ==
source_sha256) is unchanged.
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
SITE = 'https://livebench.ai/'
HF = 'https://huggingface.co/api/models'
# Set by GitHub Actions in every step; the runner's own values must never leak into a fixture run.
GITHUB_RUN_VARS = ('GITHUB_RUN_ID', 'GITHUB_SERVER_URL', 'GITHUB_REPOSITORY')
SCRIPT = 'static/js/main.1e1ce12d.js'          # the fixture's served and reviewed main script
NEWEST = '20261025'                             # the newest 2.0 release of the fixture site
NEWEST_DATE = '2026-10-25'

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
    'site': {'main_script': SCRIPT, 'reviewed_on': TODAY},
    'publishers': FIXTURE_PUBLISHERS,
    'decisions': [{'key': key, 'decision': 'not_open_weight', 'decided_on': TODAY,
                   'reason': f'{family}: closed API family with no published weights (fixture copy of the seeded entry)'}
                  for key, family in SEEDED],
}
# Fixture roots carry their own scorer file: only RELEASES is read (with ast), and its dates never move.
FIXTURE_RELEASES = ('2025-04-25', '2025-05-30', '2026-06-25')


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
# LiveBench 2.0: one column per suite, and the weights the 20261025 categories.json carries.
SUITES = {'Long Agentic': ['long_agentic'], 'Reasoning': ['reasoning'], 'Coding': ['coding'], 'Browser': ['browser'],
          'Data Analysis': ['data_analysis'], 'Research': ['research'], 'Design': ['design']}
WEIGHTS = {'Long Agentic': 2.0, 'Coding': 1.5, 'Design': 1.5}


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


def table(categories, rows, extra=(), crlf=False):
    """A CSV like livebench.ai serves: the model column first (no organization column), then the tasks."""
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


def suites_json(weights=WEIGHTS):
    doc = {k: list(v) for k, v in SUITES.items()}
    if weights is not None:
        doc['_overall_weights'] = dict(weights)
    return as_json(doc)


def recorded_rows(release):
    return [(r['leaderboard_model_id'], dict(r['category_scores'])) for r in EVIDENCE['recommendations'] if r['release'] == release]


FILLERS = [(f'filler-model-{i:02d}', 20.0 + i) for i in range(6)]
TABLE_2025_04 = table(CATS_2025_04, recorded_rows('2025-04-25') + FILLERS)
TABLE_2025_05 = table(CATS_2025_05, recorded_rows('2025-05-30') + FILLERS)
TABLE_2026_06 = table(CATS_2026, [('deepseek-v4.1-flash', 81.11), ('glm-5.3-flash', 71.59)] + FILLERS)

# The default newest release: closed families on top, then rows the catalog already knows; nothing is reportable.
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


# --- the main script ---------------------------------------------------------------------------
def entry(name, organization='Fixture Lab', openweight=None, huggingface=None, variants=None, **extra):
    """A registry entry as the minified bundle writes it: unquoted keys, !0 for true."""
    fields = [f'displayName:"{name.title()}"', f'organization:"{organization}"', 'url:"https://example.org/"']
    if huggingface:
        fields.append(f'huggingface:"{huggingface}"')
    if openweight is not None:
        fields.append('openweight:' + ('!0' if openweight else '!1'))
    fields += [f'{k}:{v}' for k, v in extra.items()]
    if variants:
        fields.append('variants:[' + ','.join('{' + ','.join(f'{k}:{v}' for k, v in var.items()) + '}' for var in variants) + ']')
    return f'"{name}":{{{",".join(fields)}}}'


def hf(repo):
    return f'https://huggingface.co/{repo}'


# The 2.0 registry of the fixture bundle, shaped like the real one (gn in main.1e1ce12d.js). It changes no default
# outcome: the closed entry is a seeded closed family, the links name known repositories.
FIXTURE_REGISTRY = [
    entry('claude-opus-5', 'Anthropic', effort='"max"', reasoner='!0'),
    entry('glm-5.3-flash', 'Z.AI', True, hf('zai-org/GLM-5.3-Flash'), reasoner='!0'),
    entry('deepseek-v4.1-flash', 'DeepSeek', True, effort='"max"'),
    entry('gemma-4-31b-it', 'Google', True, hf('google/gemma-4-31B-it')),
]
# The older registry for v1 ids (fa in the real bundle), with a variants list as it has.
FIXTURE_V1_REGISTRY = [
    entry('glm-5.3', 'Z.AI', True, hf('zai-org/GLM-5.3')),
    entry('chatgpt-4o-latest', 'OpenAI', variants=[{'rawName': '"chatgpt-4o-latest-0903"', 'displayName': '"ChatGPT-4o"'}]),
]
V1_RELEASES = ['2025-04-02', '2025-04-25', '2025-05-30', '2026-01-08', '2026-06-25']
V2_RELEASES = ['20261014', NEWEST]


def suite_order_js(order):
    """rn() of the real main.1e1ce12d.js, verbatim but for the list: it orders a 2.0 release's suites."""
    return ('an=[' + ','.join(f'"{s}"' for s in order) + '];function rn(e){const t=e=>{const t=an.indexOf(e);return '
            't<0?an.length:t},n={};return Object.keys(e||{}).sort((e,n)=>t(e)-t(n)).forEach(t=>{n[t]=e[t]}),n}')


def main_script(v1, v2, registry, v1_registry, weights_literal=True, before='', after='',
                suite_order=md.REVIEWED_SUITE_ORDER):
    """A bundle carrying the shapes the run reads: the code around the release lists, the suite order and the
    averaging code are copied from the real main.1e1ce12d.js (identifiers as minified there); registries and lists
    are the fixture's."""
    v1_list = ','.join(f'"{d}"' for d in v1)
    v2_list = ','.join(f'"{d}"' for d in v2)
    weights = ('const kn="_overall_weights";function Nn(e){const{[kn]:t,...n}=e||{},a={};return Object.entries(t||{})'
               '.forEach(([e,t])=>{const r=Number(t);e in n&&isFinite(r)&&r>0&&(a[e]=r)}),{categories:n,weights:a}}'
               if weights_literal else 'function Nn(e){return{categories:e,weights:{}}}')
    return (
        '/*! For license information please see main.1e1ce12d.js.LICENSE.txt */(()=>{var e={766:function(e){e.exports={}}};'
        + before
        + 'const tn={Qwen:"#7C3AED"},nn=e=>tn[e]||"#7A8AA8",' + (suite_order_js(suite_order) if suite_order else 'an=[]')
        + ';const mn=(e,t,n)=>{if(!t)return"-";const a=t.map(t=>parseFloat(e[t])).filter(e=>!isNaN(e)),r=a.length>0?'
          'a.reduce((e,t)=>e+t,0)/a.length:NaN;return isNaN(r)?"-":n?r.toFixed(n):r},gn={' + ','.join(registry) + '},vn={};'
        + f'Qt={{tablejoin:"table join"}},Yt=[{v2_list}],Jt="undefined"!==typeof window&&/^\\/new(\\/(index\\.html)?)?$/'
          '.test(window.location.pathname)?[...Yt]:Yt,Xt=e=>`${e.slice(0,4)}-${e.slice(4,6)}-${e.slice(6,8)}`,'
          f'Zt="25 October 2026",en=[...[{v1_list}].map(e=>({{id:e,label:e,gen:"v1"}})),...Jt.map(e=>({{id:e,label:Xt(e),'
          'gen:"v2"}))];if(new Set(en.map(e=>e.label)).size!==en.length)throw new Error("Two releases share a date on '
          'the timeline (v1 RELEASES vs 2.0 RELEASE_LABELS)");'
        + weights
        + 'const Sn=(e,t)=>e&&null!=e[t]?e[t]:1;const pa=e=>fn().parse(e,{header:!0,dynamicTyping:!0,skipEmptyLines:!0})'
          '.data.filter(e=>e.model);const ha=(e,t,n)=>{if(!t)return"-"},fa={' + ','.join(v1_registry) + '},ma={};'
          'fetch(`./v1/table_${a}.csv?v=1793398874`);fetch(`./data/${e}/table.csv?v=1793398874`);'
        + after + '})();'
    ).encode('utf-8')


def index_html(src='./static/js/main.1e1ce12d.js'):
    return ('<!doctype html><html lang="en" data-theme="light"><head><meta charset="utf-8"/><title>LiveBench 2.0 - A '
            f'challenging, contamination-free long-horizon AI benchmark</title><script defer="defer" src="{src}"></script>'
            '<link href="./static/css/main.b6172137.css" rel="stylesheet"></head><body><noscript>You need to enable '
            'JavaScript to run this app.</noscript><div id="root"></div></body></html>').encode('utf-8')


def asset_manifest(main='./static/js/main.1e1ce12d.js'):
    return as_json({'files': {'main.css': './static/css/main.b6172137.css', 'main.js': main,
                              'static/js/453.309372f5.chunk.js': './static/js/453.309372f5.chunk.js',
                              'index.html': './index.html'},
                    'entrypoints': ['static/css/main.b6172137.css', 'static/js/main.1e1ce12d.js']})


NOT_FOUND_PAGE = b'<!DOCTYPE html><html><head><title>Page not found</title></head><body>404</body></html>'
TYPES = {'.csv': 'text/csv; charset=utf-8', '.json': 'application/json; charset=utf-8',
         '.js': 'application/javascript; charset=utf-8', '': 'text/html; charset=utf-8'}


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
    """Scripted upstream: livebench.ai (page, manifest, main script, release files) and a fake Hugging Face."""

    def __init__(self, rows=DEFAULT_ROWS, categories=None):
        self.v1, self.v2 = list(V1_RELEASES), list(V2_RELEASES)
        self.registry, self.v1_registry = list(FIXTURE_REGISTRY), list(FIXTURE_V1_REGISTRY)
        self.weights_literal, self.script_before, self.script_after = True, '', ''
        self.suite_order = md.REVIEWED_SUITE_ORDER  # the list rn() orders the suites by; None leaves it out
        self.script_bytes = None              # bytes replacing the generated main script
        self.index, self.manifest = index_html(), asset_manifest()
        self.files = {                        # livebench.ai path (no leading slash) -> bytes; anything else is 404
            'v1/table_2025_04_25.csv': TABLE_2025_04, 'v1/categories_2025_04_25.json': as_json(CATS_2025_04),
            'v1/table_2025_05_30.csv': TABLE_2025_05, 'v1/categories_2025_05_30.json': as_json(CATS_2025_05),
            'v1/table_2026_06_25.csv': TABLE_2026_06, 'v1/categories_2026_06_25.json': as_json(CATS_2026),
            'v1/cost_2026_06_25.csv': b'model,cost\nx,1\n',
            'data/20261014/table.csv': table(SUITES, DEFAULT_ROWS), 'data/20261014/categories.json': suites_json(None),
            f'data/{NEWEST}/table.csv': table(categories or SUITES, rows), f'data/{NEWEST}/categories.json': suites_json(),
            f'data/{NEWEST}/notes.json': as_json(['Every suite counts equally.']),
        }
        self.types = {}                       # path -> content type, overriding the type by extension
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

    def add_model(self, repo, listed=True, **kw):
        self.infos[repo.casefold()] = model_info(repo, **kw)
        if listed:
            self.listings.setdefault(repo.split('/')[0], []).append(repo)
        return self.infos[repo.casefold()]

    def add_release(self, rid, rows=DEFAULT_ROWS, categories=True, weights=WEIGHTS):
        """A newer 2.0 release on the timeline, with its table and (unless categories=False) its categories file."""
        self.v2.append(rid)
        self.files[f'data/{rid}/table.csv'] = table(SUITES, rows)
        if categories:
            self.files[f'data/{rid}/categories.json'] = suites_json(weights)

    def head_table(self):
        return self.files[f'data/{NEWEST}/table.csv']

    # -- fixture root ------------------------------------------------------------------------
    def root(self, tmp, evidence=None, benchmarks=None, decisions=(), publishers=(), discovery=None, releases_extra=(),
             latest=NEWEST_DATE):
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
        # The fixture site has caught up with the newest release unless a test says otherwise (the real evidence still
        # records 2026-06-25, so the real nightly raises the new-release notice until the owner records 2.0).
        ev['latest_release'] = latest
        # The real evidence also records 2.0 rows (livebench.ai/data/...). The fixture site's 2.0 tables are its own
        # (DEFAULT_ROWS), so those rows are dropped here; tests that need a recorded 2.0 row add one themselves.
        ev['recommendations'] = [rec for rec in ev['recommendations'] if '/data/' not in rec['source_table']]
        for rec in ev['recommendations']:
            name = rec['source_table'].rsplit('/', 1)[1]
            rec['source_sha256'] = hashlib.sha256(self.files[f'v1/{name}']).hexdigest()
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

    # -- the site ----------------------------------------------------------------------------
    def site(self):
        script = self.script_bytes if self.script_bytes is not None else main_script(
            self.v1, self.v2, self.registry, self.v1_registry, self.weights_literal, self.script_before, self.script_after,
            self.suite_order)
        return {'': self.index, 'asset-manifest.json': self.manifest, SCRIPT: script, **self.files}

    def net(self):
        return FakeNet(self)


class FakeNet:
    def __init__(self, world):
        self.world = world
        self.site = world.site()
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
        if cap is not None and len(body) > cap:
            raise md.ShapeError(f'response over {cap} bytes', got=f'more than {cap} bytes')
        return md.Reply(url, 200, headers, body)

    def route(self, url):
        w, p = self.world, urllib.parse.urlsplit(url)
        if p.hostname == 'livebench.ai':
            assert not p.query, url                  # release files are read without the site's ?v= cache-buster
            path = p.path[1:]
            if path not in self.site:
                raise md.HttpStatus(404, url)        # the real site answers unknown paths with a 404 page
            ext = os.path.splitext(path)[1]
            return {'content-type': w.types.get(path, TYPES.get(ext, 'text/plain'))}, self.site[path]
        assert p.hostname == 'huggingface.co', url
        if p.path == '/api/models':
            q = urllib.parse.parse_qs(p.query)
            org, start = q['author'][0], int(q.get('cursor', ['0'])[0])
            assert q['limit'] == [str(md.LISTING_LIMIT)], url
            ids = [i for o, names in w.listings.items() if o.casefold() == org.casefold() for i in names]
            size = w.page_size or len(ids) or 1
            page = ids[start:start + size]
            headers = {'content-type': 'application/json'}
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

    def site_paths(self):
        return [urllib.parse.urlsplit(u).path for u in self.calls if u.startswith(SITE)]


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

    @staticmethod
    def catalogue(root, *models):
        """Append (id, repo, upstream_metadata or None) entries to the fixture root's catalog/models.json."""
        path = root / 'catalog/models.json'
        doc = json.loads(path.read_text(encoding='utf-8'))
        doc['models'] += [{'id': cid, 'upstream_repo': repo, 'status': 'candidate', 'parameters_b': None,
                           'upstream_metadata': meta} for cid, repo, meta in models]
        path.write_text(json.dumps(doc, indent=2) + '\n', encoding='utf-8')
        return root

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

    def discovery(self, world, registry=False, **root_kw):
        """A Discovery with its local inputs loaded, for resolving single rows against the fake Hugging Face (with
        registry=True, also the fixture bundle's registries, ranked for the newest release)."""
        d = md.Discovery(world.net(), self.root(world, **root_kw), TODAY_DATE)
        d.local = md.load_local(d.root, TODAY_DATE)
        if registry:
            d.registry = md.parse_registries(world.site()[SCRIPT].decode('utf-8'))
            d.registry.rank([r[0] for r in csv.reader(io.StringIO(world.head_table().decode('utf-8')))][1:])
        return d


def row(lb_id, overall=50.0, rank=1):
    return md.Row(lb_id, 2, {'Reasoning': overall}, overall=overall, rank=rank, number=1)


def world_rows(world):
    text = world.head_table().decode('utf-8')
    return [(r[0],) for r in list(csv.reader(io.StringIO(text)))[1:]]


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
        self.assertRegex(local.site.main_script, r'^static/js/[A-Za-z0-9_.-]+\.js$')
        self.assertRegex(local.site.reviewed_on, r'^\d{4}-\d{2}-\d{2}$')
        self.assertNotIn('leaderboard', DISCOVERY)          # the Averaging.js commit pin is gone with the GitHub source
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

    def test_the_site_review_record_is_validated(self):
        cases = [({'main_script': 'static/js/main.1e1ce12d.js'}, 'site.reviewed_on'),
                 ({'main_script': '/static/js/main.js', 'reviewed_on': TODAY}, 'site.main_script'),
                 ({'main_script': 'https://cdn.example/main.js', 'reviewed_on': TODAY}, 'site.main_script'),
                 ({'main_script': SCRIPT, 'reviewed_on': '2026-11-10'}, 'site.reviewed_on: later than today'),
                 ({'main_script': SCRIPT, 'reviewed_on': TODAY, 'commit': 'x'}, 'site.commit: unknown field')]
        for site, needle in cases:
            with self.subTest(site=site):
                result = self.run_world(World(), discovery={**FIXTURE_DISCOVERY, 'site': site})
                self.assertEqual(result.code, 2)
                self.assertEqual(result.net.calls, [])
                self.assertIn(needle, result.failure)
        old = {k: v for k, v in FIXTURE_DISCOVERY.items() if k != 'site'}
        old['leaderboard'] = {'averaging_reviewed_revision': REVIEWED}
        result = self.run_world(World(), discovery=old)
        self.assertEqual(result.code, 2)
        self.assertIn('leaderboard: unknown field', result.failure)
        self.assertIn('site: expected {main_script, reviewed_on}', result.failure)

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
        self.assertEqual(EVIDENCE['latest_release'], '2026-10-25')
        self.assertEqual(len({r['meaning'] for r in EVIDENCE['recommendations']}), 1)
        self.assertEqual(len(EVIDENCE['recommendations']), 7)
        # The recorded GitHub blobs map to the same bytes on livebench.ai/v1/.
        self.assertEqual(sorted({r.site_path for r in local.evidence.recommendations}),
                         ['v1/table_2025_04_25.csv', 'v1/table_2025_05_30.csv'])

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

    def test_the_evidence_parser_accepts_livebench_ai_source_tables(self):
        by_id = {m['id']: md.CatalogModel(m['id'], m['upstream_repo'], m['status'], None, None) for m in MODELS['models']}
        ev = json.loads(json.dumps(EVIDENCE))
        ev['recommendations'][0]['source_table'] = 'https://livebench.ai/v1/table_2025_04_25.csv'
        ev['recommendations'].append({**ev['recommendations'][0], 'leaderboard_model_id': 'qwen3.8-27b',
                                      'model_id': 'qwen38-27b', 'release': NEWEST_DATE,
                                      'source_table': f'https://livebench.ai/data/{NEWEST}/table.csv'})
        parsed = md.parse_evidence(ev, by_id)
        self.assertEqual([(r.site_path, r.generation) for r in parsed.recommendations][::5],
                         [('v1/table_2025_04_25.csv', 'v1'), (f'data/{NEWEST}/table.csv', '2.0')])
        self.assertEqual(parsed.revision, REVIEWED)   # still pins the GitHub-form URLs that remain
        # leaderboard_revision is required to equal the commit of GitHub-form URLs only
        for rec in ev['recommendations']:
            if rec['source_table'].startswith('https://github.com/'):
                rec['source_table'] = 'https://livebench.ai/v1/' + rec['source_table'].rsplit('/', 1)[1]
        ev['leaderboard_revision'] = 'f' * 40
        self.assertEqual(md.parse_evidence(ev, by_id).repo, None)
        del ev['leaderboard_revision']
        self.assertIsNone(md.parse_evidence(ev, by_id).revision)
        for bad in ('https://livebench.ai/table_2025_04_25.csv', 'https://livebench.ai/v1/table_2025_04_25.csv?v=1',
                    'http://livebench.ai/v1/table_2025_04_25.csv', 'https://www.livebench.ai/v1/table_2025_04_25.csv',
                    'https://livebench.ai/data/2026-10-25/table.csv', 'https://livebench.ai/data/20261332/table.csv'):
            with self.subTest(bad=bad), self.assertRaises(md.ConfigError) as ctx:
                md.parse_evidence({**ev, 'recommendations': [{**ev['recommendations'][0], 'source_table': bad}]}, by_id)
            self.assertIn('recommendations[0].source_table', str(ctx.exception))

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
        self.assertEqual(md.ALLOWED_HOSTS, ('huggingface.co', 'livebench.ai'))
        self.assertEqual((md.SITE_URL, md.WEIGHTS_KEY), ('https://livebench.ai/', '_overall_weights'))
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
        self.assertIn(BENCH['reference_release'], releases)
        # latest_release records the 2.0 release 2026-10-25 for discovery; the pinned scorer lane does not run 2.0
        self.assertNotIn(EVIDENCE['latest_release'], releases)
        self.assertNotIn(NEWEST_DATE, FIXTURE_RELEASES)    # the new-release tests rely on the fixture scorer file
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
        for url in ('https://api.github.com/repos/LiveBench/new-livebench/commits/HEAD', 'https://example.com/x',
                    'http://livebench.ai/v1/table_2026_06_25.csv', 'https://www.livebench.ai/',
                    'https://raw.githubusercontent.com/LiveBench/new-livebench/main/x', 'https://user@huggingface.co/api',
                    'https://huggingface.co:8443/api', 'https://livebench.ai.evil.net/x', 'https://cdn.livebench.ai/x'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                net.get(url)
        self.assertEqual(net.opener.requests, [])

    def test_tokens_go_only_to_their_own_host(self):
        env = {'GITHUB_TOKEN': 'gh-secret', 'HF_TOKEN': 'hf-secret'}      # both set on every Actions runner
        net = self.net(FakeResponse(), FakeResponse(), FakeResponse(), env=env)
        net.get('https://huggingface.co/api/models/a/b')
        net.get('https://livebench.ai/v1/table_2026_06_25.csv')
        net.get('https://livebench.ai/')
        (hf_req, _), *site = net.opener.requests
        self.assertEqual(hf_req.get_header('Authorization'), 'Bearer hf-secret')
        self.assertEqual(hf_req.get_header('User-agent'), 'llm-eval model_discovery')
        for req, _ in site:
            self.assertIsNone(req.get_header('Authorization'))   # no token ever goes to the leaderboard site
            self.assertEqual(req.get_header('Accept'), '*/*')
            self.assertEqual(req.get_header('User-agent'), 'llm-eval model_discovery')
        self.assertNotIn('gh-secret', repr(vars(net)))           # the GitHub token is not even read
        empty = self.net(FakeResponse(), env={'HF_TOKEN': ''})
        empty.get('https://huggingface.co/api/models/a/b')
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
        # www.livebench.ai answers 301 to livebench.ai: another host, refused (the run only ever asks livebench.ai)
        site = urllib.request.Request('https://livebench.ai/v1/table_2026_06_25.csv')
        with self.assertRaises(md.ShapeError):
            handler.redirect_request(site, io.BytesIO(), 301, 'moved', email.message.Message(), 'https://www.livebench.ai/v1/x')

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
        url = 'https://livebench.ai/asset-manifest.json'
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

    def test_a_403_is_final_on_every_host(self):
        # The GitHub rate-limit retry went with the GitHub source: a 403 is a final status wherever it comes from.
        for url in ('https://huggingface.co/api/models/a/b', 'https://livebench.ai/v1/table_2026_06_25.csv'):
            net = self.net(http_error(url, 403, {'x-ratelimit-remaining': '0', 'Retry-After': '5'}))
            with self.subTest(url=url), self.assertRaises(md.HttpStatus) as ctx:
                net.get(url)
            self.assertEqual((ctx.exception.code, net.sleeps), (403, []))

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


# --- the leaderboard site: main script, release lists, registry --------------------------------------
REAL_LISTS = ('Yt=["20261014","20261025"],Jt="undefined"!==typeof window&&/^\\/new(\\/(index\\.html)?)?$/.test(window.'
              'location.pathname)?[...Yt]:Yt,Xt=e=>`${e.slice(0,4)}-${e.slice(4,6)}-${e.slice(6,8)}`,Zt="25 October '
              '2026",en=[...["2024-06-24","2024-07-26","2024-08-31","2024-11-25","2025-04-02","2025-04-25","2025-05-30",'
              '"2025-11-25","2025-12-23","2026-01-08","2026-06-25"].map(e=>({id:e,label:e,gen:"v1"})),...Jt.map(e=>({id:e,'
              'label:Xt(e),gen:"v2"}))];if(new Set(en.map(e=>e.label)).size!==en.length)throw new Error("Two releases '
              'share a date on the timeline (v1 RELEASES vs 2.0 RELEASE_LABELS)");')
# Two entries of the real 2.0 registry (gn) and one of the real v1 registry (fa), verbatim from main.1e1ce12d.js.
REAL_REGISTRY = ('gn={"beam-1.0":{displayName:"Beam 1.0",organization:"Reflection AI",url:"https://reflection.ai/",'
                 'huggingface:"https://huggingface.co/reflection/Beam-1.0-501B-A23B",openweight:!0,effort:"max",reasoner:!0},'
                 '"claude-fable-5.1":{displayName:"Claude Fable 5.1",organization:"Anthropic",url:"https://www.anthropic.'
                 'com/news/claude-fable-5-1",effort:"max",reasoner:!0}},vn={},yn={};'
                 'fa={"claude-sonnet-5-5-xhigh-effort":{url:"https://platform.claude.com/docs/en/models/sonnet-5-5/overview"'
                 ',organization:"Anthropic",displayName:"Claude Sonnet 5.5 xHigh Effort",reasoner:!0,variants:[{rawName:'
                 '"claude-sonnet-5-5-max-effort",displayName:"Claude Sonnet 5.5 Max Effort"}]},"glm-5.3":{url:"https://z.ai",'
                 'organization:"Z.AI",displayName:"GLM-5.3",openweight:!0,reasoner:!0,huggingface:"https://huggingface.co/'
                 'zai-org/GLM-5.3"}},ma={};')

# rn() of the real bundle with what precedes it, verbatim from main.1e1ce12d.js.
REAL_SUITE_ORDER = ('Muse:"#0D9488"},nn=e=>tn[e]||"#7A8AA8",an=["Long Agentic","Design","Coding","Browser","Data Analysis",'
                    '"Research","Reasoning"];function rn(e){const t=e=>{const t=an.indexOf(e);return t<0?an.length:t},n={};'
                    'return Object.keys(e||{}).sort((e,n)=>t(e)-t(n)).forEach(t=>{n[t]=e[t]}),n}const on={Design:"Dsn"}')


class SiteTest(Base):
    def test_the_suite_order_of_the_real_bundle(self):
        self.assertEqual(md.parse_suite_order(REAL_SUITE_ORDER), list(md.REVIEWED_SUITE_ORDER))
        renamed = REAL_SUITE_ORDER.replace('an', 'Q$').replace('rn(', 'k9(')
        self.assertEqual(md.parse_suite_order(renamed), list(md.REVIEWED_SUITE_ORDER))   # minified names change
        moved = REAL_SUITE_ORDER.replace('"Long Agentic","Design"', '"Design","Long Agentic"')
        self.assertEqual(md.parse_suite_order(moved)[:2], ['Design', 'Long Agentic'])
        twice = REAL_SUITE_ORDER + ';' + REAL_SUITE_ORDER.replace('an', 'bn').replace('"Design",', '')
        for text in ('', REAL_SUITE_ORDER.replace('t<0?an.length:t', 't'), twice):
            with self.subTest(text=text[:40]):
                self.assertIsNone(md.parse_suite_order(text))
        self.assertEqual(md.parse_suite_order(REAL_SUITE_ORDER + ';' + REAL_SUITE_ORDER), list(md.REVIEWED_SUITE_ORDER))
        # unknown suites go last in their own order, as the site's stable sort leaves them
        self.assertEqual(md.site_order(['Zeta', 'Reasoning', 'Alpha', 'Long Agentic'], md.REVIEWED_SUITE_ORDER),
                         ['Long Agentic', 'Reasoning', 'Zeta', 'Alpha'])

    def test_the_release_lists_of_the_real_bundle(self):
        timeline = md.parse_release_lists(REAL_LISTS)
        self.assertEqual([r.id for r in timeline if r.generation == 'v1'][-3:], ['2025-12-23', '2026-01-08', '2026-06-25'])
        self.assertEqual([(r.id, r.date, r.generation) for r in timeline if r.generation == '2.0'],
                         [('20261014', '2026-10-14', '2.0'), ('20261025', '2026-10-25', '2.0')])
        self.assertEqual(len(timeline), 13)
        self.assertEqual([r.date for r in timeline], sorted(r.date for r in timeline))
        newest = timeline[-1]
        self.assertEqual((newest.table_path, newest.categories_path), ('data/20261025/table.csv', 'data/20261025/categories.json'))
        v1 = timeline[-3]
        self.assertEqual((v1.table_path, v1.categories_path), ('v1/table_2026_06_25.csv', 'v1/categories_2026_06_25.json'))

    def test_release_lists_must_each_be_found_exactly_once(self):
        renamed = REAL_LISTS.replace('Yt', 'Q9').replace('Jt', 'Zz').replace('Xt', 'P_').replace('en=', 'k$=')
        self.assertEqual(len(md.parse_release_lists(renamed)), 13)       # minified names change between builds
        cases = {
            'no v1 list': REAL_LISTS.replace('gen:"v1"', 'gen:"old"'),
            'two v1 lists': REAL_LISTS + '["2027-01-01"].map(e=>({id:e,label:e,gen:"v1"}));',
            'no 2.0 map': REAL_LISTS.replace('gen:"v2"', 'gen:"new"'),
            'no 2.0 list': REAL_LISTS.replace('Yt=["20261014","20261025"]', 'Yt=window.releases'),
            'ambiguous 2.0 lists': REAL_LISTS + 'const Ab=["20251201"];',
            'a v1 id that is no date': REAL_LISTS.replace('"2025-11-25"', '"2025-11-31"'),
            'a 2.0 id that is no date': REAL_LISTS.replace('"20261014"', '"20261314"'),
            'two releases on one date': REAL_LISTS.replace('"2026-06-25"', '"2026-10-25"'),
        }
        for name, text in cases.items():
            with self.subTest(name=name), self.assertRaises(md.ShapeError):
                md.parse_release_lists(text)

    def test_the_registry_of_the_real_bundle(self):
        reg = md.parse_registries(REAL_REGISTRY)
        self.assertIsNone(reg.problem)
        self.assertEqual([sorted(t) for t in reg.tables], [['beam-1.0', 'claude-fable-5.1'],
                                                          ['claude-sonnet-5-5-max-effort', 'claude-sonnet-5-5-xhigh-effort', 'glm-5.3']])
        reg.rank(['claude-fable-5.1', 'beam-1.0', 'glm-5.3'])
        self.assertEqual((reg.order, reg.coverage), ([0, 1], [2, 1]))
        beam = reg.get('beam-1.0')
        self.assertEqual((beam.openweight, beam.link), (True, 'reflection/Beam-1.0-501B-A23B'))
        fable = reg.get('claude-fable-5.1')
        self.assertEqual((fable.openweight, fable.link), (False, None))      # no openweight key: LiveBench lists it closed
        self.assertEqual(reg.counts(), (2, 1, 1))
        self.assertIsNone(reg.get('no-such-id'))
        self.assertIsNone(reg.get('glm-5.3'))          # only the v1 registry holds it: a 2.0 row never borrows it
        reg.rank(['claude-sonnet-5-5-max-effort', 'glm-5.3'])
        variant = reg.get('claude-sonnet-5-5-max-effort')
        self.assertEqual((variant.openweight, variant.variant_of), (False, 'claude-sonnet-5-5-xhigh-effort'))

    def test_registry_precedence_variants_and_links(self):
        js = ('gn={"minimax-m3":{openweight:!0},"open-v":{openweight:!0,huggingface:"https://huggingface.co/Acme/Open-V",'
              'variants:[{rawName:"open-v-closed",openweight:!1},{rawName:"open-v-max"}]},'
              '"odd-link":{openweight:!0,huggingface:"https://huggingface.co/Acme/Odd/tree/main"}};'
              'fa={"minimax-m3":{displayName:"MiniMax M3"},"only-v1":{openweight:!0}};')
        reg = md.parse_registries(js)
        reg.rank(['minimax-m3', 'open-v', 'odd-link'])            # the 2.0 release's ids: the 2.0 registry is its own
        self.assertTrue(reg.get('minimax-m3').openweight)
        self.assertIsNone(reg.get('only-v1'))                    # an id only the other registry holds: no entry
        self.assertEqual(reg.get('open-v-max').link, 'Acme/Open-V')            # a variant inherits the link
        self.assertEqual((reg.get('open-v-closed').openweight, reg.get('open-v-closed').link), (False, 'Acme/Open-V'))
        odd = reg.get('odd-link')
        self.assertEqual((odd.link, odd.link_raw), (None, 'https://huggingface.co/Acme/Odd/tree/main'))
        reg.rank(['minimax-m3', 'only-v1', 'x', 'y'])            # a v1 release: the v1 registry (2 of 4 ids) is its own
        self.assertEqual(reg.order, [1, 0])
        self.assertFalse(reg.get('minimax-m3').openweight)       # the v1 registry lists it closed
        self.assertTrue(reg.get('only-v1').openweight)
        self.assertIsNone(reg.get('open-v-max'))                 # a 2.0 entry never answers for a v1 row

    def test_a_registry_whose_first_key_the_minifier_left_unquoted(self):
        # The real bundle writes identifier-shaped ids unquoted (gn has inkling:{...}, fa azerogpt:{...}): a new such
        # id sorted first must not hide the registry (every openweight mark would then lie outside it).
        inkling = 'inkling:{displayName:"Inkling",organization:"Muse",openweight:!0,huggingface:"https://huggingface.co/muse/Inkling"},'
        for name, js in (('identifier', REAL_REGISTRY.replace('gn={', 'gn={' + inkling)),
                         ('number', REAL_REGISTRY.replace('fa={', 'fa={7:{displayName:"Seven",openweight:!0},'))):
            with self.subTest(name=name):
                reg = md.parse_registries(js)
                self.assertIsNone(reg.problem)
                self.assertEqual(len(reg.tables), 2)
        reg = md.parse_registries(REAL_REGISTRY.replace('gn={', 'gn={' + inkling))
        reg.rank(['inkling', 'beam-1.0'])
        self.assertEqual(reg.get('inkling').link, 'muse/Inkling')
        self.assertEqual(md.parse_registries(REAL_REGISTRY.replace('fa={', 'fa={7:{openweight:!0},')).tables[1]['7'].openweight, True)
        # Code around a registry is passed over: only the registry itself must be plain data.
        js = 'const M={state:{open:!0},render:function(){const gn={"a":{openweight:!0}};return gn}};'
        reg = md.parse_registries(js)
        self.assertIsNone(reg.problem)
        self.assertEqual([sorted(t) for t in reg.tables], [['a']])

    def test_a_missing_or_unparseable_registry_is_a_problem_never_an_error(self):
        cases = {
            'no registry': ('gn={"a":{displayName:"A"}};', 'no model registry'),
            'not plain data': ('gn={"a":{openweight:!0,url:n.url}};', 'does not parse'),
            'a spread': ('gn={"a":{openweight:!0,...base}};', 'does not parse'),
            'outside every registry': ('gn={"a":{openweight:!0}};function f(){return{openweight:!0}}', 'outside'),
            'never closes': ('gn={"a":{openweight:!0}', 'never closes'),
            'an identifier key, not plain data': ('gn={a:{openweight:!0,url:n.url}};', 'does not parse'),
        }
        for name, (js, needle) in cases.items():
            with self.subTest(name=name):
                reg = md.parse_registries(js)
                self.assertIn(needle, reg.problem)
                self.assertEqual(reg.tables, [])
                self.assertIsNone(reg.get('a'))

    def test_js_literals(self):
        self.assertEqual(md.parse_js_literal('{"a-b":{x:"\\xd7 \\u2014 \\u{1F600}",y:!0,z:!1,n:-1.5e2,l:[1,"t",null],t:true}}'),
                         {'a-b': {'x': '× — 😀', 'y': True, 'z': False, 'n': -150.0, 'l': [1.0, 't', None], 't': True}})
        self.assertEqual(md.parse_js_literal("{a:'it\\'s',b:[]}"), {'a': "it's", 'b': []})
        for text in ('{a:b}', '{a:`x`}', '{a:1,,b:2}', '{a:1', '{a:1}}', '{a:function(){}}', '[1 2]'):
            with self.subTest(text=text), self.assertRaises((ValueError, IndexError)):
                md.parse_js_literal(text)
        self.assertEqual(md.balanced_end('x={"}":{a:"{"}},y', 2), len('x={"}":{a:"{"}}'))
        self.assertIsNone(md.balanced_end('{a:{b:1}', 0))

    def test_the_main_script_comes_from_the_manifest_and_must_be_the_page_s(self):
        world = World()
        result = self.run_world(world)
        self.assertEqual(result.code, 0, result.failure)
        self.assertEqual(result.net.site_paths()[:3], ['/', '/asset-manifest.json', '/' + SCRIPT])
        self.assertEqual(result.data['sources']['main_script']['path'], SCRIPT)
        cases = [
            ('manifest names another script', lambda w: setattr(w, 'manifest', asset_manifest('./static/js/main.ffff0000.js')),
             'index.html loading the main script asset-manifest.json names (static/js/main.ffff0000.js)'),
            ('page loads another script', lambda w: setattr(w, 'index', index_html('./static/js/main.ffff0000.js')),
             'Got: `script src ./static/js/main.ffff0000.js`'),
            ('manifest names another host', lambda w: setattr(w, 'manifest', asset_manifest('https://cdn.example.net/main.js')),
             'asset-manifest.json files["main.js"]'),
            ('no manifest', lambda w: setattr(w, 'manifest', None), 'asset manifest at https://livebench.ai/asset-manifest.json'),
            ('manifest as HTML', lambda w: w.types.update({'asset-manifest.json': 'text/html'}), 'application/json from'),
        ]
        for name, change, needle in cases:
            with self.subTest(name=name):
                world = World()
                change(world)
                if world.manifest is None:
                    world.manifest = b''
                    world.files['asset-manifest.json'] = None
                net = world.net()
                if world.files.get('asset-manifest.json', b'') is None:
                    del net.site['asset-manifest.json']
                result = self.run_world(world, net=net)
                self.assertEqual(result.code, 2, result.failure)
                self.assertIn('- Stage: `leaderboard site`', result.failure)
                self.assertIn(needle, result.failure)
                self.assertFalse(any('huggingface.co' in u for u in result.net.calls))

    def test_the_weights_literal_must_be_in_the_main_script(self):
        world = World()
        world.weights_literal = False
        result = self.run_world(world)
        self.assertEqual(result.code, 2)
        self.assertIn('the averaging code\'s "_overall_weights" literal in static/js/main.1e1ce12d.js', result.failure)

    def test_a_broken_release_list_fails_the_run(self):
        for change in (lambda w: setattr(w, 'v2', ['20261014', '20261332']), lambda w: setattr(w, 'v1', V1_RELEASES + ['2026-10-25']),
                       lambda w: setattr(w, 'script_after', 'const Xy=["20990101"];')):
            world = World()
            change(world)
            with self.subTest():
                result = self.run_world(world)
                self.assertEqual(result.code, 2)
                self.assertIn('- Stage: `leaderboard site`', result.failure)

    def test_the_run_adds_2_0_suites_in_the_order_the_main_script_gives(self):
        # 472.6 / 8 = 59.075 exactly: the summation order decides the last digit (ParsingTest has the arithmetic)
        rounding = ('zz-rounding', {'Long Agentic': 25.8, 'Reasoning': 25.3, 'Coding': 73.0, 'Browser': '',
                                    'Data Analysis': 96.6, 'Research': 43.2, 'Design': 97.6})
        world = World([rounding] + DEFAULT_ROWS)
        result = self.run_world(world)
        self.assertEqual(result.code, 0, result.failure)
        self.assertEqual(result.rows['zz-rounding']['overall'], 59.08)
        self.assertEqual(result.data['sources']['suite_order'], list(md.REVIEWED_SUITE_ORDER))
        self.assertNotIn("the site's suite order", result.issue)
        world.suite_order = list(SUITES)           # a deploy whose rn() keeps the categories.json order
        result = self.run_world(world)
        self.assertEqual(result.rows['zz-rounding']['overall'], 59.07)
        world.suite_order = None                   # not found: the reviewed script's order, and a warning
        result = self.run_world(world)
        self.assertEqual((result.code, result.rows['zz-rounding']['overall']), (0, 59.08))
        self.assertIsNone(result.data['sources']['suite_order'])
        self.assertIn("- Warning: the site's suite order (the list its rn() sorts the suites by) was not found in "
                      "`static/js/main.1e1ce12d.js`; overalls add the suites in the order of the reviewed script (Long "
                      "Agentic, Design, Coding, Browser, Data Analysis, Research, Reasoning), so one can differ from "
                      "the site's in the last digit.", result.issue)
        result = self.run_world(world, '--release', '2026-06-25')     # a v1 release adds no suites: no warning
        self.assertNotIn("the site's suite order", result.issue)

    def test_html_and_missing_release_files(self):
        world = World()
        world.types[f'data/{NEWEST}/table.csv'] = 'text/html; charset=utf-8'
        world.files[f'data/{NEWEST}/table.csv'] = NOT_FOUND_PAGE
        result = self.run_world(world)
        self.assertEqual(result.code, 2)
        self.assertIn('text/csv from https://livebench.ai/data/20261025/table.csv', result.failure)
        world = World()
        world.files[f'data/{NEWEST}/categories.json'] = NOT_FOUND_PAGE         # an HTML body served as JSON
        result = self.run_world(world)
        self.assertEqual(result.code, 2)
        self.assertIn('content-type application/json, body <!DOCTYPE html>', result.failure)
        # A release whose table answers 404 is not analysed: the previous one is (here the latest recorded one).
        world = World()
        world.add_release('20261107')
        del world.files['data/20261107/table.csv']
        result = self.run_world(world)
        self.assertEqual(result.code, 0, result.failure)
        self.assertEqual(result.data['release']['id'], NEWEST)
        self.assertIn('release 2026-11-07 (2.0, id 20261107) is on the site\'s timeline, but `data/20261107/table.csv` '
                      'answers HTTP 404; not analysed', result.issue)


# --- tables, categories, aggregation ------------------------------------------------------------
class ParsingTest(Base):
    CATS = {'Math': ['m1', 'm2', 'm3', 'm4'], 'Coding': ['c1']}

    def scored(self, text, cats=None, generation='v1', weights=None):
        raw = md.read_csv(text.encode('utf-8') if isinstance(text, str) else text, 'u')
        return md.score_table(raw, cats or self.CATS, generation, weights)

    def test_csv_shape(self):
        text = '﻿Model ,m1,m2,m3,m4,c1,notes\r\n"a,b",10,20,30,40,50,x\r\nplain,1,2,3,4,5,y\r\n'
        scored, partial, extras = self.scored(text)
        self.assertEqual([r.id for r in scored], ['a,b', 'plain'])
        self.assertEqual(extras, ['notes'])
        self.assertEqual([(r.line, r.number) for r in scored], [(2, 1), (3, 2)])
        multi = 'model,m1,m2,m3,m4,c1,notes\n"first",1,2,3,4,5,"two\nlines"\nsecond,1,2,3,4,5,z\n'
        self.assertEqual([(r.line, r.number) for r in sorted(self.scored(multi)[0], key=lambda r: r.id)], [(2, 1), (4, 2)])
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
               'ragged row': 'model,m1,m2,m3,m4,c1\nx,10,2,3,4\n',
               'an HTML page': NOT_FOUND_PAGE.decode('utf-8')}
        for name, text in bad.items():
            with self.subTest(name=name), self.assertRaises(md.ShapeError):
                self.scored(text)
        with self.assertRaises(md.ShapeError) as ctx:
            self.scored('model,m1,m2,m3,c1\nx,1,2,3,4\n')
        self.assertIn('m4', str(ctx.exception))
        with self.assertRaises(md.ShapeError):
            md.read_csv(b'model,m1\n\xff\xfe,1\n', 'u')

    def test_categories_shape(self):
        self.assertEqual(md.parse_categories(b'{"A": ["t1", "t2"], "B": ["t3"]}', 'u'), ({'A': ['t1', 't2'], 'B': ['t3']}, {}, []))
        for text in (b'[["t1"]]', b'{"A": []}', b'{"A": ["t1", 2]}', b'{"A": ["t1"], "B": ["t1"]}', b'{}', b'not json',
                     NOT_FOUND_PAGE, b'{"A": ["t1"], "_overall_weights": {"A": 2}}'):     # v1 categories carry no weights
            with self.subTest(text=text), self.assertRaises(md.ShapeError):
                md.parse_categories(text, 'u')

    def test_2_0_categories_and_weights(self):
        cats, weights, ignored = md.parse_categories(suites_json(), 'u', '2.0')
        self.assertEqual((cats, weights, ignored), (SUITES, WEIGHTS, []))
        self.assertEqual(md.parse_categories(suites_json(None), 'u', '2.0'), (SUITES, {}, []))
        doc = {**SUITES, '_overall_weights': {'Coding': 3, 'Design': 0, 'Browser': -1, 'Agentic': 2}}
        cats, weights, ignored = md.parse_categories(as_json(doc), 'u', '2.0')
        self.assertEqual(weights, {'Coding': 3.0})                    # non-positive and unknown suites are ignored
        self.assertEqual(ignored, [('Design', 0, 'not positive'), ('Browser', -1, 'not positive'),
                                   ('Agentic', 2, 'not a suite of this file')])
        for bad in ({**SUITES, '_notes': ['x']}, {**SUITES, '_overall_weights': {'Coding': '2'}},
                    {**SUITES, '_overall_weights': {'Coding': True}}, {**SUITES, '_overall_weights': {'Coding': None}},
                    {**SUITES, '_overall_weights': [2]}, {'_overall_weights': {}}):
            with self.subTest(bad=bad), self.assertRaises(md.ShapeError):
                md.parse_categories(as_json(bad), 'u', '2.0')
        for literal in (b'NaN', b'Infinity', b'-Infinity'):        # Python's json reads these; they are no finite number
            with self.subTest(literal=literal), self.assertRaises(md.ShapeError) as ctx:
                md.parse_categories(b'{"Coding": ["coding"], "_overall_weights": {"Coding": ' + literal + b'}}', 'u', '2.0')
            self.assertIn('finite numbers in _overall_weights', str(ctx.exception))

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

    SUITE_HEADER = 'model,long_agentic,reasoning,coding,browser,data_analysis,research,design\n'

    def site_overall(self, cells, weights=WEIGHTS, cats=None):
        scored, partial, _ = self.scored(self.SUITE_HEADER + 'x,' + cells + '\n', cats or SUITES, '2.0', weights)
        return (scored or partial)[0]

    def test_2_0_overall_is_the_site_s_weighted_suite_mean(self):
        # Real row of data/20261025/table.csv (claude-fable-5.1), hand-computed with the 20261025 weights:
        # (77.9*2 + 91.7 + 97.7*1.5 + 89.8 + 80.3 + 82.0 + 83.4*1.5) / (2 + 1 + 1.5 + 1 + 1 + 1 + 1.5) = 771.25 / 9
        r = self.site_overall('77.9,91.7,97.7,89.8,80.3,82.0,83.4')
        self.assertEqual(r.overall, 85.69)
        self.assertEqual(r.categories['Coding'], 97.7)
        # every suite x1 (20261014 has no weights): the plain mean of the seven suites, 602.8 / 7 = 86.114...
        self.assertEqual(self.site_overall('77.9,91.7,97.7,89.8,80.3,82.0,83.4', weights={}).overall, 86.11)
        # missing suites are left out of numerator and denominator alike: n/a and blank cells
        # (90 + 60*1.5 + 80 + 80) / (1 + 1.5 + 1 + 1) = 340 / 4.5 = 75.555...
        r = self.site_overall('n/a,90,60,,80,80,')
        self.assertEqual((r.overall, r.missing_tasks, r.missing_label()), (75.56, 3, '3 of 7 suites missing'))
        self.assertEqual(self.site_overall('100,0,0,0,0,0,0').overall, round(200 / 9, 2))   # 22.22: the weight counts
        self.assertEqual(self.site_overall('100,,,,,,').overall, 100.0)   # one suite with a score is an overall
        r = self.site_overall(',,,,,,')
        self.assertIsNone(r.overall)                                       # no suite with a score: no overall
        # non-positive and unknown-suite weights were dropped by parse_categories; a weight of 1 is the plain mean
        self.assertEqual(self.site_overall('50,100,100,100,100,100,100', weights={'Long Agentic': 1.0}).overall, 92.86)
        # a suite of several columns is the mean of those that hold a number
        cats = {'A': ['long_agentic', 'reasoning'], 'B': ['coding', 'browser', 'data_analysis', 'research', 'design']}
        r = self.site_overall('10,30,n/a,50,50,50,50', weights={'A': 3.0}, cats=cats)
        self.assertEqual((r.categories['A'], r.categories['B'], r.overall), (20.0, 50.0, 27.5))

    def test_2_0_rounding_is_javascript_tofixed(self):
        # toFixed rounds the exact binary value half up: 1.125 is exact, so 1.13 (Python's round() gives 1.12);
        # 2.675 is really 2.67499999..., so 2.67 (a decimal-string rounding would give 2.68).
        self.assertEqual(md.js_fixed2(1.125), 1.13)
        self.assertEqual(round(1.125, 2), 1.12)
        self.assertEqual(md.js_fixed2(2.675), 2.67)
        self.assertEqual(md.js_fixed2(0.125), 0.13)
        self.assertEqual(md.js_fixed2(85.69444444444444), 85.69)
        self.assertEqual(self.site_overall('1.25,1.0,,,,,', weights={}).overall, 1.13)     # (1.25 + 1.0) / 2 = 1.125
        self.assertEqual(self.site_overall('2.675,,,,,,', weights={}).overall, 2.67)
        # Ranking uses the rounded overall, as the site shows it: 70.001 and 69.996 tie at 70.00.
        scored, _, _ = self.scored(self.SUITE_HEADER + 'b,' + ','.join(['70.001'] * 7) + '\na,' + ','.join(['69.996'] * 7)
                                   + '\n', SUITES, '2.0', WEIGHTS)
        self.assertEqual([(r.id, r.overall, r.rank) for r in scored], [('a', 70.0, 1), ('b', 70.0, 1)])
        # JavaScript adds left to right; Python 3.12's sum() compensates: js_mean must not
        self.assertEqual(md.js_mean([0.1] * 10), 0.9999999999999999 / 10)

    def test_2_0_suites_are_added_in_the_site_s_order(self):
        # The exact weighted mean of this row is 472.6 / 8 = 59.075. Added in the site's order (rn(): Long Agentic,
        # Design, Coding, Browser, Data Analysis, Research, Reasoning) the sum rounds to 59.08, as the site shows;
        # added in categories.json order it is 59.074999... and rounds to 59.07.
        cells = '25.8,25.3,73.0,,96.6,43.2,97.6'
        self.assertEqual(self.site_overall(cells).overall, 59.08)
        raw = md.read_csv((self.SUITE_HEADER + 'x,' + cells + '\n').encode('utf-8'), 'u')
        self.assertEqual(md.score_table(raw, SUITES, '2.0', WEIGHTS, display=list(SUITES))[0][0].overall, 59.07)
        # every suite x1 takes the same order (the site's plain mean runs over Object.entries of the sorted suites):
        # 54.1 + 50.0 + 68.0 + 80.2 added A to D is 252.3 (/ 4 = 63.075 -> 63.08), added D to A 252.29999... (-> 63.07)
        raw = md.read_csv(b'model,a,b,c,d\nx,54.1,50.0,68.0,80.2\n', 'u')
        cats = {'D': ['d'], 'C': ['c'], 'B': ['b'], 'A': ['a']}
        self.assertEqual([md.score_table(raw, cats, '2.0', {}, display=order)[0][0].overall
                          for order in (['A', 'B', 'C', 'D'], ['D', 'C', 'B', 'A'])], [63.08, 63.07])

    def test_recorded_evidence_reproduces_offline(self):
        overalls = []
        for rec in EVIDENCE['recommendations']:
            values = list(rec['category_scores'].values())
            if '/data/' in rec['source_table']:      # 2.0: weighted mean of the suites, as the site averages
                weights = [WEIGHTS.get(s, 1.0) for s in rec['category_scores']]
                mean = sum(v * w for v, w in zip(values, weights)) / sum(weights)
            else:
                mean = sum(values) / len(values)
            self.assertLessEqual(abs(mean - rec['overall']), md.OVERALL_TOL, rec['leaderboard_model_id'])
            overalls.append((rec['overall'], len(values)))
        self.assertEqual(overalls, [(47.52, 6), (55.51, 6), (60.53, 7), (45.92, 6), (56.64, 6), (50.23, 7), (46.5, 7)])
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

    def test_hugging_face_s_doubled_u8_count_only_widens_the_packed_range(self):
        # At the catalog's pinned revision ff433f54 Hugging Face now reports U8 = 112,764,911,616 for
        # Nemotron-3-Super-120B-NVFP4 (the catalog records 56,382,455,808, exactly half); total and the float counts
        # are unchanged. The packed rule must stay fail-safe with the reported counts.
        recorded = BY_ID['nemotron-super-120b']['upstream_metadata']['safetensors']
        self.assertEqual(recorded['parameters']['U8'], 56_382_455_808)
        reported = {'parameters': {**recorded['parameters'], 'U8': 112_764_911_616}, 'total': recorded['total']}
        names = md.tokens(BY_ID['nemotron-super-120b']['upstream_repo'], 'nvidia')
        old, new = (md.parameter_count(st, names, self.B) for st in (recorded, reported))
        self.assertEqual((old.kind, old.value), ('packed', 120_000_000_000))
        self.assertEqual((new.kind, new.value, new.problem), ('packed', 120_000_000_000, None))   # 120b still verifies
        self.assertEqual(new.lower, old.lower)
        self.assertEqual((round(old.upper / 1e9, 2), round(new.upper / 1e9, 2)), (123.61, 236.38))
        # An unnamed packed repository with the doubled count gets the wider range, never a tighter fit claim.
        old, new = (md.parameter_count(st, ['nemotron', 'super'], self.B) for st in (recorded, reported))
        self.assertGreater(new.upper, old.upper)
        self.assertEqual((old.cls, old.problem, new.cls, new.problem), (None, 'size_unverified', None, 'size_unverified'))
        small = {'parameters': {'BF16': 1_000_000_000, 'U8': 39_000_000_000}, 'total': 40_000_000_000}
        doubled = {'parameters': {'BF16': 1_000_000_000, 'U8': 78_000_000_000}, 'total': 40_000_000_000}
        self.assertEqual(md.parameter_count(small, ['foo'], self.B).cls, 'offload')            # 40-79 B
        self.assertEqual(md.parameter_count(doubled, ['foo'], self.B).problem, 'size_unverified')   # 40-157 B


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
        self.assertEqual([(c['table'], c['url'], c['categories'], c['rows']) for c in cal],
                         [('table_2025_04_25.csv', 'https://livebench.ai/v1/table_2025_04_25.csv', 'categories_2025_04_25.json', 4),
                          ('table_2025_05_30.csv', 'https://livebench.ai/v1/table_2025_05_30.csv', 'categories_2025_05_30.json', 1)])
        self.assertIn('calibration 5/5 recorded v1 rows reproduced, HF anchors 4/4, matcher canary 4/4', result.issue)
        # the recorded GitHub blob URLs are read at livebench.ai/v1/: the GitHub API is never asked
        self.assertFalse(any('github' in u for u in result.net.calls))

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
        world.files['v1/table_2025_04_25.csv'] = TABLE_2025_04.replace(b'filler-model-00', b'filler-model-99')
        self.assert_calibration_failure(self.run_world(world, root=root), 'with the recorded sha256')

        world = World()
        world.files['v1/table_2025_04_25.csv'] = table(CATS_2025_04, recorded_rows('2025-04-25')[1:] + FILLERS)
        self.assert_calibration_failure(self.run_world(world), 'is not in the table')

        world = World()
        rows = recorded_rows('2025-04-25')
        lb_id, scores = rows[0]
        spec = dict(scores)
        spec['zebra_puzzle'] = repr(scores['Reasoning'] + 0.02)
        world.files['v1/table_2025_04_25.csv'] = table(CATS_2025_04, [(lb_id, spec)] + rows[1:] + FILLERS)
        self.assert_calibration_failure(self.run_world(world), 'no categories file on livebench.ai/v1/ reproduces')

        world = World()
        root = self.root(world)
        del world.files['v1/table_2025_05_30.csv']
        self.assert_calibration_failure(self.run_world(world, root=root),
                                        'the recorded table table_2025_05_30.csv at https://livebench.ai/v1/table_2025_05_30.csv')

    def test_categories_fallback(self):
        world = World()
        del world.files['v1/categories_2025_04_25.json']
        world.files['v1/categories_2025_04_02.json'] = as_json(CATS_2025_04)    # 2025-04-02 is on the v1 timeline
        result = self.run_world(world)
        self.assertEqual(result.code, 0, result.failure)
        self.assertEqual(result.data['calibration'][0]['categories'], 'categories_2025_04_02.json')
        self.assertIn('categories file `categories_2025_04_02.json` (fallback)', result.step)
        world = World()
        del world.files['v1/categories_2025_04_25.json']
        self.assert_calibration_failure(self.run_world(world), 'reproduces the recorded scores of table_2025_04_25.csv')

    def test_taxonomy_against_the_real_benchmarks_file(self):
        self.assertIn('IF', CATS_2026)   # the passing default world names Instruction Following 'IF'
        world = World()
        moved = {k: list(v) for k, v in CATS_2026.items()}
        moved['Coding'].append(moved['Language'].pop())
        world.files['v1/categories_2026_06_25.json'] = as_json(moved)
        result = self.run_world(world)
        self.assert_calibration_failure(result, 'task partition of catalog/benchmarks.json')
        # The fix names both files together, and the diff says what moved.
        for needle in ('- What to do: livebench.ai serves this file unversioned. If LiveBench changed it, record the '
                       'new partition in catalog/benchmarks.json together with catalog/livebench-evidence.json',
                       'tasks moved typos (Language → Coding)'):
            self.assertIn(needle, result.failure)
        self.assertIn('What to do: livebench.ai serves this file unversioned', result.step)

        def move_typos(doc):
            by_name = {c['name']: c for c in doc['categories']}
            by_name['Language']['livebench_tasks'].remove('typos')
            by_name['Coding']['livebench_tasks'].append('typos')
        result = self.run_world(world, benchmarks=move_typos)        # benchmarks.json records the new partition
        self.assertEqual(result.code, 0, result.failure)
        self.assertEqual(result.data['taxonomy']['file'], 'v1/categories_2026_06_25.json')

    def test_the_reference_release_must_be_a_v1_release(self):
        result = self.run_world(World(), benchmarks=lambda doc: doc.update(reference_release=NEWEST_DATE))
        self.assert_calibration_failure(result, '2.0 suites are another taxonomy')

    def test_the_excluded_example_check_is_soft(self):
        world = World()
        world.files['v1/table_2026_06_25.csv'] = table(CATS_2026, FILLERS)
        result = self.run_world(world)
        self.assertEqual((result.code, result.outputs['complete']), (0, 'true'))
        self.assertIn('overall 71.59 recorded for `zai-org/GLM-5.3-Flash`', result.step)
        self.assertIn('overall 81.11 recorded', result.step)
        self.assertNotIn('71.59', result.issue.split('Not raised')[0].replace('71.59, rank', ''))

    def test_a_recorded_2_0_row_is_checked_softly(self):
        def add_v2(ev):
            ev['recommendations'].append({**ev['recommendations'][0], 'model_id': 'qwen38-27b',
                                          'leaderboard_model_id': 'qwen3.8-27b-thinking', 'release': NEWEST_DATE,
                                          'overall': 68.0, 'category_scores': {k: 68.0 for k in SUITES},
                                          'source_table': f'https://livebench.ai/data/{NEWEST}/table.csv',
                                          'source_sha256': hashlib.sha256(World().head_table()).hexdigest()})
        result = self.run_world(World(), evidence=add_v2)
        self.assertEqual(result.code, 0, result.failure)
        self.assertEqual(result.data['soft_calibration'], [{'table': f'data/{NEWEST}/table.csv', 'rows': 1, 'status': 'reproduced'}])
        self.assertIn('calibration 5/5 recorded v1 rows', result.issue)
        world = World([('new-row-1', 99.0)] + DEFAULT_ROWS)          # LiveBench added a row: other bytes, a warning only
        result = self.run_world(world, evidence=add_v2)
        self.assertEqual(result.code, 0, result.failure)
        self.assertEqual(result.data['soft_calibration'][0]['status'], 'changed')
        self.assertIn(f'recorded 2.0 rows of `data/{NEWEST}/table.csv` not re-checked: livebench.ai now serves other bytes',
                      result.step)

    def test_a_recorded_2_0_row_that_no_longer_reproduces_is_a_warning(self):
        # Unequal suites, so the weights matter: the site's weighted mean is 650 / 9 = 72.22, the plain mean that
        # notes.json describes 470 / 7 = 67.14. Same bytes, a recorded overall that differs: soft, but said.
        spec = {'Long Agentic': 90.0, 'Coding': 90.0, 'Design': 90.0, 'Reasoning': 50.0, 'Browser': 50.0,
                'Data Analysis': 50.0, 'Research': 50.0}
        world = World([(r[0], spec) if r[0] == 'qwen3.8-27b-thinking' else r for r in DEFAULT_ROWS])

        def recorded(overall):
            def add(ev):
                ev['recommendations'].append({**ev['recommendations'][0], 'model_id': 'qwen38-27b',
                                              'leaderboard_model_id': 'qwen3.8-27b-thinking', 'release': NEWEST_DATE,
                                              'overall': overall, 'category_scores': dict(spec),
                                              'source_table': f'https://livebench.ai/data/{NEWEST}/table.csv',
                                              'source_sha256': hashlib.sha256(world.head_table()).hexdigest()})
            return add
        result = self.run_world(world, evidence=recorded(72.22))
        self.assertEqual(result.code, 0, result.failure)
        self.assertEqual(result.data['soft_calibration'][0]['status'], 'reproduced')
        self.assertNotIn('do not reproduce', result.step)
        result = self.run_world(world, evidence=recorded(67.14))
        self.assertEqual((result.code, result.outputs['complete']), (0, 'true'), result.failure)
        self.assertEqual(result.data['soft_calibration'], [{'table': f'data/{NEWEST}/table.csv', 'rows': 1, 'status': 'differs'}])
        self.assertIn(f'- `data/{NEWEST}/table.csv` (2.0, soft): 1 recorded rows, differs.', result.step)
        self.assertIn(f'recorded 2.0 rows of `data/{NEWEST}/table.csv` do not reproduce: `qwen3.8-27b-thinking: overall '
                      '72.220000, recorded 67.14`', result.step)

    def test_hf_anchors(self):
        result = self.run_world(World())
        self.assertEqual([a['class'] for a in result.data['anchors']], ['float', 'packed', 'packed', 'float'])
        self.assertEqual([a['int_changes'] for a in result.data['anchors']], [[], [], [], []])
        for field, value in (('sha', 'a' * 40), ('total', 1), ('float count', 1), ('dtype set', 1), ('no safetensors', None)):
            with self.subTest(field=field):
                world = World()
                key = next(k for k in world.revisions if k[0] == 'nvidia/nvidia-nemotron-3-super-120b-a12b-nvfp4')
                doc = world.revisions[key]
                if field == 'sha':
                    doc['sha'] = value
                elif field == 'total':
                    doc['safetensors']['total'] = value
                elif field == 'float count':
                    doc['safetensors']['parameters']['BF16'] += value
                elif field == 'dtype set':
                    doc['safetensors']['parameters']['I8'] = value
                else:
                    doc['safetensors'] = None
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

    def test_an_integer_count_hugging_face_now_reports_differently_is_a_header_warning(self):
        # What the CI probe found on 2026-11-08: U8 doubled at the pinned Nemotron revision, everything else unchanged.
        world = World()
        key = next(k for k in world.revisions if k[0] == 'nvidia/nvidia-nemotron-3-super-120b-a12b-nvfp4')
        world.revisions[key]['safetensors']['parameters']['U8'] = 112_764_911_616
        result = self.run_world(world)
        self.assertEqual((result.code, result.outputs['complete']), (0, 'true'), result.failure)
        warning = ('Hugging Face now reports U8 = 112764911616 at the recorded revision of '
                   '`nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-NVFP4` (`ff433f5493e2`); catalog records 56382455808; '
                   'packed size ranges use the reported counts.')
        self.assertIn('- Warning: ' + warning, result.issue)
        self.assertIn('integer counts differ: U8 112764911616 (recorded 56382455808)', result.step)
        self.assertEqual(result.data['anchors'][1]['int_changes'],
                         [{'dtype': 'U8', 'reported': 112_764_911_616, 'recorded': 56_382_455_808}])
        # an anchor whose reported counts no longer classify as packed is a shape change
        world = World()
        key = next(k for k in world.revisions if k[0] == 'openai/gpt-oss-120b')
        world.revisions[key]['safetensors']['parameters']['U8'] = 0
        result = self.run_world(world)
        self.assertEqual(result.code, 2)
        self.assertIn('anchor gpt-oss-120b classified as a packed checkpoint', result.failure)


# --- release discovery ----------------------------------------------------------------------------
class ReleaseDiscoveryTest(Base):
    def test_the_newest_release_with_both_files(self):
        world = World()
        world.add_release('20261105')
        world.add_release('20261107', DEFAULT_ROWS[:5], categories=False)
        result = self.run_world(world)
        self.assertEqual(result.code, 0, result.failure)
        self.assertEqual((result.data['release']['id'], result.data['release']['generation']), ('20261105', '2.0'))
        self.assertEqual(result.data['release']['table'], 'https://livebench.ai/data/20261105/table.csv')
        self.assertIn('`data/20261107/table.csv` (5 rows) has no categories file yet; not analysed.', result.issue)
        self.assertNotIn('release_without_categories', json.dumps(result.data['notices']))
        self.assertEqual([n['kind'] for n in result.data['notices']], ['new_release'])

        world.files['data/20261107/table.csv'] = table(SUITES, DEFAULT_ROWS[:20])
        result = self.run_world(world)
        self.assertEqual(result.outputs['reportable'], 'true')
        self.assertEqual([n['kind'] for n in result.data['notices']], ['release_without_categories', 'new_release'])
        self.assertIn('`data/20261107/table.csv` has 20 data rows on livebench.ai and `data/20261107/categories.json` '
                      'answers HTTP 404.', result.issue)
        # release files are read without the site's ?v= cache-buster (FakeNet refuses a query on livebench.ai)
        self.assertTrue(all('?' not in u for u in result.net.calls if u.startswith(SITE)))

    def test_an_in_progress_release_falls_back(self):
        world = World()
        world.add_release('20261107', DEFAULT_ROWS[:19])
        result = self.run_world(world)
        self.assertEqual(result.data['release']['id'], NEWEST)
        self.assertIn('release 2026-11-07 looks in progress (19 scored rows); analysing 2026-10-25', result.issue)
        world.files['data/20261107/table.csv'] = table(SUITES, DEFAULT_ROWS[:md.MIN_RELEASE_ROWS])
        result = self.run_world(world)                     # exactly MIN_RELEASE_ROWS scored rows: analysed
        self.assertEqual(result.code, 0, result.failure)
        self.assertEqual((result.data['release']['id'], result.data['release']['scored_rows']), ('20261107', 20))
        self.assertEqual([n['kind'] for n in result.data['notices']], ['new_release'])
        self.assertNotIn('looks in progress', result.issue)

    def test_the_recorded_latest_release_must_stay_on_the_timeline(self):
        world = World()
        world.v1 = [d for d in V1_RELEASES if d != '2026-06-25']
        result = self.run_world(world, latest='2026-06-25')
        self.assertEqual(result.code, 2)
        self.assertIn('leaderboard layout changed', result.failure)
        world = World()
        del world.files[f'data/{NEWEST}/table.csv']
        result = self.run_world(world)                       # nothing on or after latest_release loads
        self.assertEqual(result.code, 2)
        self.assertIn('a release on or after 2026-10-25 with at least 20 scored rows', result.failure)

    def test_site_status_codes(self):
        world = World()
        world.errors[SITE] = 500
        result = self.run_world(world)
        self.assertEqual(result.code, 1)
        self.assertIn('Network failure at `leaderboard site`', result.step)
        world = World()
        world.errors[SITE + f'data/{NEWEST}/table.csv'] = 403
        result = self.run_world(world)
        self.assertEqual(result.code, 1)

    def test_release_forces_a_release(self):
        world = World()
        for flag, rid in (('20261014', '20261014'), ('2026-10-14', '20261014'), ('2026-06-25', '2026-06-25')):
            with self.subTest(flag=flag):
                result = self.run_world(world, '--release', flag)
                self.assertEqual(result.code, 0, result.failure)
                self.assertEqual(result.data['release']['id'], rid)
                self.assertIn('is analysed because --release named it (a forced run never touches the tracking issue)',
                              result.issue)
                # Reported (issue body, step summary, artifact), but never offered to the issue steps: the issue
                # tracks the newest release, and an older release's marker would re-announce every entry next night.
                self.assertTrue(result.data['complete'])
                self.assertEqual(result.outputs, {'complete': 'false', 'reportable': 'false', 'new': 'false'})
        result = self.run_world(world, '--release', '2026-06-25')
        self.assertEqual(result.data['release']['generation'], 'v1')
        self.assertIn('the two-level mean', result.issue)
        self.assertIn('it has only 8 scored rows (in progress?)', result.issue)     # analysed anyway, and said so
        self.assertEqual(result.data['notices'], [])        # 2026-06-25 is older than latest_release
        for flag in ('2026-10-15', '20260625'):             # not on the timeline; 20260625 is no 2.0 id
            with self.subTest(flag=flag):
                result = self.run_world(world, '--release', flag)
                self.assertEqual(result.code, 2)
                self.assertIn(f'--release {flag} is not on the livebench.ai timeline (v1: 2025-04-02', result.failure)
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as ctx:
            md.main(['--release', 'latest'], net=world.net(), root=self.root(world))
        self.assertEqual(ctx.exception.code, 2)
        world = World()
        world.v1.append('2026-07-01')                        # on the timeline, files missing
        result = self.run_world(world, '--release', '2026-07-01')
        self.assertEqual(result.code, 2)
        self.assertIn('forced with --release', result.failure)
        self.assertIn('HTTP 404 for /v1/table_2026_07_01.csv', result.failure)


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

    def test_the_canary_resolves_a_linked_id_as_the_walk_does(self):
        # The owner catalogued a registry-linked candidate (deepseek-v4-flash -> its -0731 checkpoint) and recorded the
        # stanza; strict matching alone would name the sibling DeepSeek-V4-Flash. The walk follows the link, so must
        # the canary: no exit 2 every night.
        def world_with(link):
            world = World([('deepseek-v4-flash', 95.0)] + DEFAULT_ROWS)
            if link:
                world.registry.append(entry('deepseek-v4-flash', 'DeepSeek', True, hf(link)))
            world.listings['deepseek-ai'] += ['deepseek-ai/DeepSeek-V4-Flash', 'deepseek-ai/DeepSeek-V4-Flash-0731']
            return world

        def run(world):
            def add(ev):
                ev['recommendations'].append({**ev['recommendations'][0], 'model_id': 'deepseek-v4-flash-0731',
                                              'leaderboard_model_id': 'deepseek-v4-flash', 'release': NEWEST_DATE,
                                              'overall': 95.0, 'category_scores': {k: 95.0 for k in SUITES},
                                              'source_table': f'https://livebench.ai/data/{NEWEST}/table.csv',
                                              'source_sha256': hashlib.sha256(world.head_table()).hexdigest()})
            root = self.catalogue(self.root(world, evidence=add),
                                  ('deepseek-v4-flash-0731', 'deepseek-ai/DeepSeek-V4-Flash-0731', None))
            return self.run_world(world, root=root)
        result = run(world_with('deepseek-ai/DeepSeek-V4-Flash-0731'))
        self.assertEqual(result.code, 0, result.failure)
        flash = next(c for c in result.data['canary'] if c['id'] == 'deepseek-v4-flash')
        self.assertEqual((flash['result'], flash['tier']), ('deepseek-ai/DeepSeek-V4-Flash-0731', 'linked'))
        self.assertIn("- `deepseek-v4-flash` → `deepseek-ai/DeepSeek-V4-Flash-0731` (LiveBench's registry link)", result.step)
        self.assertEqual(result.outcome('deepseek-v4-flash'), 'known:evidence')
        self.assertNotIn('matcher canary: ', result.issue)
        # a link that disagrees with the catalog is LiveBench's data, not the matcher: a warning, the evidence decides
        result = run(world_with('deepseek-ai/DeepSeek-V4-Flash'))
        self.assertEqual(result.code, 0, result.failure)
        self.assertIn("- Warning: matcher canary: LiveBench's registry links `deepseek-ai/DeepSeek-V4-Flash` for "
                      "`deepseek-v4-flash`; the catalog records `deepseek-ai/DeepSeek-V4-Flash-0731`", result.issue)
        self.assertEqual(result.outcome('deepseek-v4-flash'), 'known:evidence')
        # without a link the strict matcher still decides, and naming the sibling still fails the run
        result = run(world_with(None))
        self.assertEqual(result.code, 2)
        self.assertIn('the strict matcher names deepseek-ai/DeepSeek-V4-Flash', result.failure)


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
        # google is never listed: LiveBench's registry links gemma-4-31b-it's repository, which needs no name match
        self.assertEqual(set(authors), {'deepseek-ai', 'zai-org', 'microsoft', 'mistralai', 'Qwen', 'meta-llama',
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
        # v1 (the two-level mean): a row with a whole category missing has no overall; it is listed, never ranked.
        hi = {'Reasoning': 95.0, 'Coding': 95.0}           # five whole categories missing: no overall
        world = World()
        world.files['v1/table_2026_06_25.csv'] = table(CATS_2026, [('hi-partial', hi), ('lo-partial', {'Reasoning': 1.0})]
                                                       + DEFAULT_ROWS)
        result = self.run_world(world, '--release', '2026-06-25')
        self.assertEqual(result.code, 0, result.failure)
        self.assertEqual(result.data['cutoff'], 43.0)
        self.assertEqual(result.data['partial'], [{'id': 'hi-partial', 'partial_mean': 95.0, 'available': 2, 'of': 7}])
        self.assertNotIn('hi-partial', result.rows)          # not ranked, not walked
        self.assertNotIn('lo-partial', result.rows)
        self.assertEqual(result.data['release']['scored_rows'], len(DEFAULT_ROWS))
        self.assertIn('**Partial rows (1)**', result.issue)
        self.assertIn('- `hi-partial`: partial (2 of 7 categories), partial mean 95.00 (not an overall)', result.issue)
        self.assertNotIn('lo-partial', result.issue)

    def test_2_0_weights_decide_the_ranking_end_to_end(self):
        # a: strong where the 20261025 weights are (Long Agentic x2, Coding and Design x1.5); b: everywhere else.
        heavy, light = ('Long Agentic', 'Coding', 'Design'), ('Reasoning', 'Browser', 'Data Analysis', 'Research')
        a = ('zz-weighted-a', {**{k: 90.0 for k in heavy}, **{k: 50.0 for k in light}})
        b = ('zz-weighted-b', {**{k: 50.0 for k in heavy}, **{k: 90.0 for k in light}})
        world = World([a, b] + DEFAULT_ROWS)
        world.files['data/20261014/table.csv'] = table(SUITES, [a, b] + DEFAULT_ROWS)       # 20261014: no weights
        result = self.run_world(world)
        self.assertEqual(result.code, 0, result.failure)
        # (90*2 + 50 + 90*1.5 + 50 + 50 + 50 + 90*1.5) / 9 = 72.22 at rank 6; (50*2 + 90 + ...) / 9 = 67.78 at rank 10
        self.assertEqual([(result.rows[k]['overall'], result.rows[k]['rank']) for k in ('zz-weighted-a', 'zz-weighted-b')],
                         [(72.22, 6), (67.78, 10)])
        self.assertIn("- Overall per the site's averaging code (reviewed 2026-11-08): weighted mean of the suites with a "
                      "score; weights `Long Agentic` ×2, `Coding` ×1.5, `Design` ×1.5, the rest ×1; rounded to 2 "
                      "decimals as the site shows it.", result.issue)
        result = self.run_world(world, '--release', '20261014')
        self.assertEqual(result.code, 0, result.failure)
        # every suite x1: 470 / 7 = 67.14 and 510 / 7 = 72.86, the other way round
        self.assertEqual([(result.rows[k]['overall'], result.rows[k]['rank']) for k in ('zz-weighted-b', 'zz-weighted-a')],
                         [(72.86, 6), (67.14, 10)])
        self.assertIn("- Overall per the site's averaging code (reviewed 2026-11-08): mean of the suites with a score "
                      "(every suite ×1); rounded to 2 decimals as the site shows it.", result.issue)
        self.assertNotIn('two-level mean', result.issue)

    def test_a_2_0_row_with_missing_suites_is_scored_from_the_suites_it_has(self):
        # 2.0 (the site's rule): missing suites are left out; only a row with no suite score at all has no overall.
        world = World([('some-suites', {'Reasoning': 95.0, 'Coding': 95.0}), ('no-suites', {})] + DEFAULT_ROWS)
        result = self.run_world(world)
        self.assertEqual(result.code, 0, result.failure)
        self.assertEqual((result.rows['some-suites']['overall'], result.rows['some-suites']['missing_tasks']), (95.0, 5))
        self.assertEqual(result.outcome('some-suites'), 'look:unknown_publisher')
        self.assertNotIn('no-suites', result.rows)
        self.assertEqual(result.data['partial'], [])        # no partial mean to list
        self.assertEqual(result.data['release']['scored_rows'], len(DEFAULT_ROWS) + 1)

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
        self.assertIn('Best catalogued model in 2026-10-25: `gemma4-31b` (`gemma-4-31b-it`) 82.00, rank 5/', result.issue)
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


# --- LiveBench's registry as a matching hint -----------------------------------------------------------
class RegistryHintTest(Base):
    def test_a_linked_repository_in_an_allowlisted_org_is_verified_as_a_match(self):
        world = World([('deepseek-v4-flash', 95.0), ('deepseek-v4-flash-max', 94.5), ('glm-5.9', 94.0),
                       ('qwen4-moved', 93.5), ('qwen4-rejected', 93.0)] + DEFAULT_ROWS)
        world.registry += [
            entry('deepseek-v4-flash', 'DeepSeek', True, hf('deepseek-ai/DeepSeek-V4-Flash-0731'),
                  variants=[{'rawName': '"deepseek-v4-flash-max"', 'displayName': '"DeepSeek V4 Flash Max"'}]),
            entry('glm-5.9', 'Z.AI', True, hf('zai-org/GLM-5.9-Gone')),
            entry('qwen4-moved', 'Qwen', True, hf('Qwen/Qwen4-Moved')),
            entry('qwen4-rejected', 'Qwen', True, hf('Qwen/Qwen4-Rejected')),
        ]
        world.add_model('deepseek-ai/DeepSeek-V4-Flash-0731', total=40_000_000_000, listed=False)   # no name match
        world.add_model('Qwen/Qwen4-Moved', canonical='someone/Qwen4-Moved', listed=False)
        world.add_model('Qwen/Qwen4-Rejected', listed=False)
        rejected = {'key': 'hf:Qwen/Qwen4-Rejected', 'decision': 'rejected', 'reason': 'Reviewed by the owner',
                    'decided_on': '2026-10-01'}
        result = self.run_world(world, decisions=[rejected])
        self.assertEqual(result.code, 0, result.failure)
        self.assertEqual({k: result.outcome(k) for k in ('deepseek-v4-flash', 'deepseek-v4-flash-max', 'glm-5.9',
                                                         'qwen4-moved', 'qwen4-rejected')},
                         {'deepseek-v4-flash': 'candidate', 'deepseek-v4-flash-max': 'variant:candidate',
                          'glm-5.9': 'look:info_unreadable', 'qwen4-moved': 'look:moved_outside_publisher',
                          'qwen4-rejected': 'decided:rejected'})
        flash = result.rows['deepseek-v4-flash']
        self.assertEqual((flash['repo'], flash['match']['tier']), ('deepseek-ai/DeepSeek-V4-Flash-0731', 'linked'))
        self.assertEqual(flash['registry'], {'openweight': True, 'link': 'deepseek-ai/DeepSeek-V4-Flash-0731', 'variant_of': None})
        self.assertEqual(result.rows['deepseek-v4-flash-max']['registry']['variant_of'], 'deepseek-v4-flash')
        self.assertIn('- Match: LiveBench links this repository (its registry entry for `deepseek-v4-flash`), not matched '
                      'by name; org `deepseek-ai` is an allowlisted publisher org via prefix `deepseek-`.', result.issue)
        self.assertNotIn('unique among 0 repos', result.issue)
        self.assertNotIn('Qwen/Qwen4-Rejected', result.net.infos_fetched())       # hf: decisions apply before model info
        self.assertIn('zai-org/GLM-5.9-Gone', result.net.infos_fetched())

    def test_a_renamed_linked_repository_is_checked_under_the_name_hugging_face_answers(self):
        # Model info for a link LiveBench spells with an old name answers with the repository's current id: the
        # catalog, hf: decisions and the one-place-per-repository rule apply to that id, as for an alias target.
        world = World([('qwen-fixture-27b', 97.0), ('qwenx', 96.0), ('qwen5-preview', 95.0), ('qwen5-9b', 94.0)] + DEFAULT_ROWS)
        world.registry += [entry('qwen-fixture-27b', 'Qwen', True, hf('Qwen/Qwen3.8-27B-Preview')),
                           entry('qwenx', 'Qwen', True, hf('Qwen/QwenX-Old')),
                           entry('qwen5-preview', 'Qwen', True, hf('Qwen/Qwen5-9B-Preview'))]
        world.add_model('Qwen/Qwen3.8-27B-Preview', canonical='Qwen/Qwen3.8-27B', listed=False)   # catalogued
        world.add_model('Qwen/QwenX-Old', canonical='Qwen/QwenX-New', listed=False)
        world.add_model('Qwen/Qwen5-9B-Preview', canonical='Qwen/Qwen5-9B', total=9_000_000_000, listed=False)
        world.add_model('Qwen/Qwen5-9B', total=9_000_000_000)
        rejected = {'key': 'hf:Qwen/QwenX-New', 'decision': 'rejected', 'reason': 'Reviewed by the owner',
                    'decided_on': '2026-10-01'}
        result = self.run_world(world, decisions=[rejected])
        self.assertEqual(result.code, 0, result.failure)
        self.assertEqual({k: result.outcome(k) for k in ('qwen-fixture-27b', 'qwenx', 'qwen5-preview', 'qwen5-9b')},
                         {'qwen-fixture-27b': 'known:catalog', 'qwenx': 'decided:rejected', 'qwen5-preview': 'candidate',
                          'qwen5-9b': 'variant:candidate'})
        self.assertEqual([result.rows[k]['repo'] for k in ('qwen-fixture-27b', 'qwenx', 'qwen5-preview')],
                         ['Qwen/Qwen3.8-27B', 'Qwen/QwenX-New', 'Qwen/Qwen5-9B'])
        self.assertEqual(result.rows['qwen5-9b']['variant_of'], 'qwen5-preview')      # one place for one repository
        self.assertIn('not matched by name; org `Qwen` is an allowlisted publisher org via prefix `qwen`; Hugging Face '
                      'answers `Qwen/Qwen5-9B-Preview` as `Qwen/Qwen5-9B` (renamed); size token `9b`', result.issue)
        self.assertIn({'key': 'hf:Qwen/Qwen5-9B', 'decision': 'rejected', 'reason': 'TODO', 'decided_on': TODAY,
                       'release': NEWEST_DATE}, snippets(result.issue))

    def test_a_link_outside_the_publisher_orgs_is_never_a_candidate(self):
        world = World([('beam-1.0', 95.0), ('qwen-x-1', 94.0), ('qwen-x-2', 93.0), ('qwen-x-3', 92.0)] + DEFAULT_ROWS)
        world.registry += [entry('beam-1.0', 'Reflection AI', True, hf('reflection/Beam-1.0-501B-A23B'), effort='"max"'),
                           entry('qwen-x-1', 'Someone', True, hf('someone/Qwen-X-1')),
                           entry('qwen-x-2', 'Someone', True, hf('someone/Qwen-X-2')),
                           entry('qwen-x-3', 'Someone', True, hf('someone/Qwen-X-3'))]
        world.add_model('someone/Qwen-X-1')
        reason = {'reason': 'Reviewed by the owner', 'decided_on': '2026-10-01'}
        decisions = [{'key': 'hf:someone/Qwen-X-2', 'decision': 'rejected', **reason},
                     {'key': 'lb:qwen-x-3', 'decision': 'not_open_weight', **reason}]
        result = self.run_world(world, decisions=decisions)
        self.assertEqual(result.code, 0, result.failure)
        self.assertEqual({k: result.outcome(k) for k in ('beam-1.0', 'qwen-x-1', 'qwen-x-2', 'qwen-x-3')},
                         {'beam-1.0': 'look:linked_outside_publisher', 'qwen-x-1': 'look:linked_outside_publisher',
                          'qwen-x-2': 'decided:rejected', 'qwen-x-3': 'decided:not_open_weight'})
        self.assertTrue(result.rows['beam-1.0']['counts'])
        self.assertEqual(result.rows['qwen-x-3']['note'], 'LiveBench links someone/Qwen-X-3, outside the publisher\'s orgs')
        self.assertEqual(result.net.infos_fetched(), [])                       # never verified: no model-info request
        self.assertIn('LiveBench links `reflection/Beam-1.0-501B-A23B`; no publisher entry matches this id.', result.issue)
        self.assertIn('LiveBench links `someone/Qwen-X-1`; the publisher\'s orgs are `Qwen`.', result.issue)
        found = [s for s in snippets(result.issue) if s.get('key') == 'hf:reflection/Beam-1.0-501B-A23B']
        self.assertEqual([s['decision'] for s in found], ['rejected'])

    def test_an_entry_without_openweight_is_listed_as_closed(self):
        world = World([('gpt-6-astra', 99.0), ('mistral-large-4', 98.0), ('qwen4-closed', 97.0), ('qwen3.8-27b', 96.0),
                       ('step-closed', 95.5)] + DEFAULT_ROWS)
        world.registry += [entry('gpt-6-astra', 'OpenAI', effort='"max"'), entry('mistral-large-4', 'Mistral AI'),
                           entry('qwen4-closed', 'Qwen'), entry('qwen3.8-27b', 'Qwen', openweight=False),
                           entry('step-closed', 'StepFun')]
        world.add_model('Qwen/Qwen4-Closed', total=30_000_000_000)
        world.add_model('stepfun-ai/Step-Closed', private=True)
        result = self.run_world(world)
        self.assertEqual(result.code, 0, result.failure)
        self.assertEqual({k: result.outcome(k) for k in ('gpt-6-astra', 'mistral-large-4', 'qwen4-closed', 'qwen3.8-27b',
                                                         'step-closed')},
                         {'gpt-6-astra': 'closed:livebench_closed', 'mistral-large-4': 'closed:livebench_closed',
                          'qwen4-closed': 'look:weights_may_be_public', 'qwen3.8-27b': 'known:catalog',
                          'step-closed': 'closed:livebench_closed'})
        self.assertEqual([k for k in ('gpt-6-astra', 'mistral-large-4', 'step-closed') if result.rows[k]['counts']], [])
        self.assertTrue(result.rows['qwen4-closed']['counts'])
        self.assertTrue(result.rows['qwen3.8-27b']['counts'])
        self.assertIn('LiveBench\'s registry lists it without openweight', result.rows['qwen3.8-27b']['note'])
        self.assertIn('**LiveBench marks it closed (3)**', result.issue)
        self.assertIn('- `gpt-6-astra` 99.00: LiveBench marks it closed (its registry entry has no `openweight`)', result.issue)
        self.assertIn('LiveBench\'s registry lists it without `openweight`; strict match `Qwen/Qwen4-Closed`', result.issue)
        self.assertIn('strict match stepfun-ai/Step-Closed: info:private', result.rows['step-closed']['note'])
        self.assertIn('Qwen/Qwen4-Closed', result.net.infos_fetched())    # a strict match is verified, as a decision's

    def test_registries_whose_first_id_is_unquoted_are_used(self):
        world = World()
        world.registry.insert(0, 'inkling:{displayName:"Inkling",organization:"Muse",url:"https://example.org/",openweight:!0}')
        world.v1_registry.insert(0, 'azerogpt:{displayName:"AzeroGPT",organization:"Fixture Lab",openweight:!0}')
        result = self.run_world(world)
        self.assertEqual(result.code, 0, result.failure)
        self.assertNotIn("model registry is not used", result.issue)
        self.assertEqual(result.data['sources']['registry']['entries'], [5, 4])
        self.assertEqual(result.rows['gemma-4-31b-it']['registry']['link'], 'google/gemma-4-31B-it')
        self.assertNotIn('google', result.net.authors())          # the link is still read: no listing needed

    def test_a_missing_or_unparseable_registry_falls_back_to_the_name_rules(self):
        for registry, needle in (([], '`no model registry (no openweight:!0 entry) in the main script`'),
                                 (['"x":{openweight:!0,url:n.url}'], 'does not parse')):
            with self.subTest(needle=needle):
                world = World()
                world.registry, world.v1_registry = registry, []
                result = self.run_world(world)
                self.assertEqual((result.code, result.outputs['complete']), (0, 'true'), result.failure)
                self.assertIn("- Warning: LiveBench's model registry is not used: ", result.issue)
                self.assertIn(needle, result.issue)
                self.assertIn('matching uses the name rules alone.', result.issue)
                self.assertIn('LiveBench model registry not used (see the warning)', result.issue)
                self.assertEqual(result.outcome('gemma-4-31b-it'), 'known:catalog')     # by name now
                self.assertIn('google', result.net.authors())
                self.assertIsNone(result.rows['gemma-4-31b-it'].get('registry'))

    def test_the_release_s_own_registry_wins(self):
        world = World([('minimax-m3', 95.0)] + DEFAULT_ROWS)
        world.registry.append(entry('minimax-m3', 'MiniMax', True))          # the 2.0 registry: open weight, no link
        world.v1_registry.append(entry('minimax-m3', 'MiniMax'))             # the v1 registry lists it closed
        world.add_model('MiniMaxAI/MiniMax-M3', total=30_000_000_000)
        result = self.run_world(world)
        self.assertEqual(result.code, 0, result.failure)
        self.assertEqual(result.outcome('minimax-m3'), 'candidate')          # matched by name, as an open-weight entry
        self.assertEqual(result.data['sources']['registry']['order'], [0, 1])
        self.assertIn('LiveBench model registry: 5 entries holding 5 of the release\'s 25 ids (the site shows only '
                      'those 5 rows, so its ranks can differ), 4 open weight, 2 with a Hugging Face link', result.issue)

    def test_a_row_never_takes_the_other_generation_s_registry_entry(self):
        # v1 2026-06-25 lists deepseek-v4-flash; the v1 registry has no entry for it, the 2.0 one links its 0731
        # checkpoint. The site shows that v1 row with no registry entry (in fact not at all): the 0731 link must not
        # attribute June's scores to the 0731 repository, nor merge the row into the real 0731 row's.
        world = World()
        world.registry.append(entry('deepseek-v4-flash', 'DeepSeek', True, hf('deepseek-ai/DeepSeek-V4-Flash-0731')))
        world.v1_registry += [entry('deepseek-v4-flash-0731', 'DeepSeek', True, hf('deepseek-ai/DeepSeek-V4-Flash-0731')),
                              entry('qwen3.8-27b-thinking', 'Qwen', True)]
        world.files['v1/table_2026_06_25.csv'] = table(CATS_2026, [('deepseek-v4-flash', 80.0), ('deepseek-v4-flash-0731', 79.0),
                                                                   ('glm-5.3', 78.0), ('qwen3.8-27b-thinking', 77.0)] + FILLERS)
        world.add_model('deepseek-ai/DeepSeek-V4-Flash', total=40_000_000_000)
        world.add_model('deepseek-ai/DeepSeek-V4-Flash-0731', total=40_000_000_000)
        world.add_model('zai-org/GLM-5.3', total=750_000_000_000)
        result = self.run_world(world, '--release', '2026-06-25')
        self.assertEqual(result.code, 0, result.failure)
        self.assertEqual(result.data['sources']['registry']['order'], [1, 0])     # 3 of the table's ids: its own
        flash, linked = result.rows['deepseek-v4-flash'], result.rows['deepseek-v4-flash-0731']
        self.assertEqual((flash['outcome'], flash['repo'], flash['match']['tier']), ('candidate', 'deepseek-ai/DeepSeek-V4-Flash', 'exact'))
        self.assertIsNone(flash.get('registry'))
        self.assertEqual((linked['outcome'], linked['repo'], linked['match']['tier']),
                         ('candidate', 'deepseek-ai/DeepSeek-V4-Flash-0731', 'linked'))
        self.assertNotIn('its registry entry for `deepseek-v4-flash`)', result.issue)


class NoticeTest(Base):
    def test_a_new_release(self):
        result = self.run_world(World(), latest='2026-06-25')
        self.assertEqual(result.outputs['reportable'], 'true')
        self.assertIn('LiveBench publishes release 2026-10-25 (LiveBench 2.0, id `20261025`, 24 scored rows) on '
                      'livebench.ai; catalog/livebench-evidence.json still records latest_release 2026-06-25.', result.issue)
        self.assertIn('2026-10-25 is not in `src/llm_eval/livebench.py` RELEASES', result.issue)
        self.assertIn("Its suites are LiveBench 2.0's own taxonomy, never compared with catalog/benchmarks.json: "
                      '`Long Agentic`, `Reasoning`, `Coding`, `Browser`, `Data Analysis`, `Research`, `Design`; overall: '
                      'weighted mean of the suites with a score; weights `Long Agentic` ×2, `Coding` ×1.5, `Design` ×1.5, '
                      'the rest ×1.', result.issue)
        self.assertNotIn('the same partition', result.issue)
        result = self.run_world(World(), latest='2026-06-25', releases_extra=(NEWEST_DATE,))
        self.assertIn('2026-10-25 is in `src/llm_eval/livebench.py` RELEASES', result.issue)
        result = self.run_world(World())                     # latest_release records 2026-10-25: the decision is made
        self.assertEqual(result.code, 0, result.failure)
        self.assertEqual((result.outputs['reportable'], result.data['notices']), ('false', []))
        # a newer v1 release is compared with catalog/benchmarks.json, as before
        result = self.run_world(World(), '--release', '2026-06-25', latest='2026-01-08')
        self.assertEqual(result.code, 0, result.failure)
        self.assertIn('LiveBench publishes release 2026-06-25 (v1, 8 scored rows) on livebench.ai', result.issue)
        self.assertIn('7 categories / 23 tasks: the same partition', result.issue)

    def test_a_changed_site_script_is_a_notice_and_withholds_nothing(self):
        reviewed = 'static/js/main.0000aaaa.js'
        discovery = {**FIXTURE_DISCOVERY, 'site': {'main_script': reviewed, 'reviewed_on': '2026-11-01'}}
        result = self.run_world(pool_world(), decisions=[ALIAS], discovery=discovery)
        self.assertEqual(result.code, 0, result.failure)
        self.assertEqual([n['kind'] for n in result.data['notices']], ['site_code_changed'])
        self.assertIn('notice:site_code_changed:static/js/main.1e1ce12d.js', result.data['keys'])
        self.assertIn('the averaging code was reviewed in `static/js/main.0000aaaa.js` (on 2026-11-01); re-read the '
                      'weights rule in `static/js/main.1e1ce12d.js` ([script](https://livebench.ai/static/js/main.1e1ce12d.js)) '
                      'and update `site` once it still holds.', result.issue)
        self.assertIn('Clears when `site.main_script` in catalog/model-discovery.json names the served script', result.issue)
        self.assertIn('site code **changed**: `static/js/main.1e1ce12d.js` served, `static/js/main.0000aaaa.js` reviewed',
                      result.issue)
        self.assertIn('### Candidates (1)', result.issue)          # candidates are not withheld
        self.assertIn('#### `qwen4-80b` →', result.issue)
        result = self.run_world(pool_world(), decisions=[ALIAS])   # the reviewed script is served: no notice
        self.assertEqual(result.data['notices'], [])
        self.assertIn('site code `static/js/main.1e1ce12d.js` as reviewed on 2026-11-08', result.issue)


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
        self.assertIn('> ' + md.DISCLAIMER.format(release=NEWEST_DATE), body)
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
            if url.startswith(SITE):                     # the page, the main script and the release's files only
                self.assertRegex(url, r'^https://livebench\.ai/(static/js/main\.1e1ce12d\.js|data/20261025/(table\.csv|'
                                      r'categories\.json))?$')
            elif 'huggingface.co' in url:
                self.assertRegex(url, r'/(tree|revision|blob)/[0-9a-f]{40}')
            else:
                self.fail(url)
        self.assertNotIn('github.com', body)
        for sha in re.findall(r'sha256 `([^`]*)`', body):
            self.assertRegex(sha, r'^[0-9a-f]{64}$')
        self.assertIn('- Leaderboard row: [`data/20261025/table.csv`](https://livebench.ai/data/20261025/table.csv) row 7 '
                      '(line 8) on [livebench.ai](https://livebench.ai/); variant `qwen4-80b-thinking` 69.50.', body)
        found = snippets(body)
        self.assertEqual(len(found), 6)   # reject + upstream_metadata + evidence stanza, and three look snippets
        decisions = [s for s in found if 'decision' in s]
        self.assertEqual(len(decisions), 4)
        meta = next(s for s in found if set(s) == {'id', 'sha', 'gated', 'safetensors'})
        self.assertEqual(meta['id'], 'Qwen/Qwen4-80B')
        stanza = next(s for s in found if 'leaderboard_model_id' in s)
        self.assertEqual(stanza['meaning'], EVIDENCE['recommendations'][0]['meaning'])
        self.assertEqual(stanza['source_sha256'], result.data['release']['table_sha256'])
        self.assertEqual(stanza['source_table'], f'https://livebench.ai/data/{NEWEST}/table.csv')
        self.assertIn('livebench.ai serves no versioned history: `source_sha256` identifies the bytes read.', body)
        self.assertNotIn('pinned to head', body)
        # Pasted as it is (with its model_id), the stanza is valid evidence: no commit to move.
        by_id = {m['id']: md.CatalogModel(m['id'], m['upstream_repo'], m['status'], None, None) for m in MODELS['models']}
        ev = json.loads(json.dumps(EVIDENCE))
        ev['recommendations'].append({**stanza, 'model_id': 'qwen38-27b'})
        parsed = md.parse_evidence(ev, by_id)
        self.assertEqual((parsed.recommendations[-1].site_path, parsed.recommendations[-1].generation),
                         (f'data/{NEWEST}/table.csv', '2.0'))
        self.assertEqual(parsed.revision, REVIEWED)
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
        self.assertIn('Best catalogued model in 2026-10-25: `llama33-70b` (`llama-3.3-70b-instruct`) 65.00, rank 9/', body)
        self.assertIn('- `deepseek-v4-max` 78.00 → `deepseek-ai/DeepSeek-V4-Max`: Q4_K_M 374.95 / IQ2_XS 180.44 GiB: '
                      'would fit 70 GiB only at 0.90 bits per weight or fewer; not a catalog tier', body)
        self.assertIn('| 2026-10-25 | 70.00 | 7/21 | +5.00 |', body)

    def test_nothing_reportable_keeps_the_header_and_the_collapsed_lists(self):
        result = self.run_world(World())
        self.assertIn(md.NOTHING_NEEDED.format(n=10, release=NEWEST_DATE), result.issue)
        self.assertNotIn('### Candidates', result.issue)
        self.assertIn('<details><summary>Not raised (', result.issue)
        self.assertIn('<!-- model-discovery-state v1 ', result.issue)
        self.assertTrue(result.comment.startswith('No unreviewed model among the 10 best entries of LiveBench release '
                                                  '2026-10-25 (2.0, livebench.ai table sha256 `'), result.comment)
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
        world.files[f'data/{NEWEST}/table.csv'] = b'id,x\na,1\n'
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
        world.add_release('20261105', DEFAULT_ROWS, categories=False)
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
        state = {'release': NEWEST_DATE, 'id': NEWEST, 'script': SCRIPT, 'table_sha256': 'a' * 64,
                 'keys': ['cand:x|o/x', 'look:y|no_repo'], 'on': TODAY}
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
        world.files[f'data/{NEWEST}/table.csv'] = b'id,x\na,1\n'
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

    def test_a_2_0_evidence_stanza_with_a_missing_suite_parses_and_reproduces(self):
        # A 2.0 row with an n/a and a blank suite is scored from the others and can be a candidate. Its stanza, filled
        # in as the issue says, must be valid evidence that the next run re-checks: no null score, no crash.
        spec = {**{name: 70.0 for name in SUITES}, 'Long Agentic': 'n/a', 'Browser': ''}
        world = World([('qwen4-80b', spec)] + DEFAULT_ROWS)
        world.add_model('Qwen/Qwen4-80B', total=80_400_000_000)
        first = self.run_world(world)
        self.assertEqual(first.code, 0, first.failure)
        self.assertEqual(first.outcome('qwen4-80b'), 'candidate')
        found = snippets(first.issue)
        stanza = next(s for s in found if 'leaderboard_model_id' in s)
        meta = next(s for s in found if set(s) == {'id', 'sha', 'gated', 'safetensors'})
        self.assertEqual(stanza['category_scores'], {k: 70.0 for k in SUITES if k not in ('Long Agentic', 'Browser')})
        self.assertEqual(stanza['overall'], 70.0)
        self.assertIn('`category_scores` leaves out `Long Agentic`, `Browser`: the row has no score there, and the '
                      'overall averages the suites it has.', first.issue)

        def root_with(scores):
            def add(ev):
                ev['recommendations'].append({**stanza, 'model_id': 'qwen4-80b-fixture', 'category_scores': scores})
            return self.catalogue(self.root(world, evidence=add), ('qwen4-80b-fixture', 'Qwen/Qwen4-80B', meta))
        second = self.run_world(world, root=root_with(stanza['category_scores']))
        self.assertEqual(second.code, 0, second.failure)
        self.assertEqual(second.data['soft_calibration'], [{'table': f'data/{NEWEST}/table.csv', 'rows': 1, 'status': 'reproduced'}])
        self.assertEqual(second.outcome('qwen4-80b'), 'known:evidence')
        self.assertNotIn('do not reproduce', second.step)
        # A recorded score for a suite the row has no score in is a soft mismatch, never a crash (exit 3).
        third = self.run_world(world, root=root_with({**stanza['category_scores'], 'Long Agentic': 70.0}))
        self.assertEqual(third.code, 0, third.failure)
        self.assertEqual(third.data['soft_calibration'][0]['status'], 'differs')
        self.assertIn('qwen4-80b: long agentic has no score in the table, recorded 70.000000', third.step)


class FailureTest(Base):
    PREVIOUS = ('_Refreshed by the nightly model discovery ([run 1](https://github.com/o/r/actions/runs/1))._\n\n'
                '## LiveBench model discovery\n\nold candidates\n\n'
                '<!-- model-discovery-state v1 ' + base64.urlsafe_b64encode(json.dumps({'keys': [], 'on': '2026-11-01'}).encode()).decode() + ' -->\n')

    def test_a_shape_error(self):
        world = World()
        world.files[f'data/{NEWEST}/table.csv'] = b'id,x\n' + b'a' * 400 + b'\n'
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
        net.fail['livebench.ai/v1/'] = md.NetworkError('livebench.ai/v1/table_2025_04_25.csv: TimeoutError after 5 attempts')
        result = self.run_world(world, net=net)
        self.assertEqual(result.code, 1)
        self.assertIn('Network failure at `calibration`', result.step)
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
        world.files[f'data/{NEWEST}/table.csv'] = b'name,score\nalpha,1\nbeta,2\n'   # a shape the run refuses
        result = self.run_world(world, '--probe')
        self.assertEqual(result.code, 0, result.stderr)
        self.assertEqual(result.outputs, {'complete': 'false', 'reportable': 'false', 'new': 'false'})
        self.assertIsNone(result.issue)
        self.assertIsNone(result.comment)
        self.assertIsNone(result.failure)
        step = result.step
        for needle in ('- page https://livebench.ai/: HTTP 200, content-type `text/html; charset=utf-8`',
                       'files["main.js"] `./static/js/main.1e1ce12d.js`',
                       '- main script `static/js/main.1e1ce12d.js` (agrees with index.html)', 'reviewed script '
                       '`static/js/main.1e1ce12d.js` (the same); `"_overall_weights"` literal present; suite order '
                       '`Long Agentic, Design, Coding, Browser, Data Analysis, Research, Reasoning` (as reviewed)',
                       '- v1 release list: 5 releases: `2025-04-02, 2025-04-25, 2025-05-30, 2026-01-08, 2026-06-25`',
                       '- 2.0 release list: 2 releases: `20261014, 20261025`',
                       '- model registry 1: 4 entries (+0 variants), 3 with openweight, 2 of them with a huggingface link',
                       '- model registry 2: 2 entries (+1 variants), 1 with openweight',
                       '- v1/table_2025_04_25.csv: HTTP 200', 'equal to the recorded source_sha256',
                       '- newest 2.0 release 20261025: `data/20261025/table.csv`', 'header `name,score`; 2 rows',
                       '_overall_weights `{"Coding":1.5,"Design":1.5,"Long Agentic":2.0}`',
                       '- unknown /no-such-page: HTTP 404', 'listing google', 'anchor nemotron-super-120b revision',
                       'counts that differ (reported, recorded): `none`'):
            self.assertIn(needle, step)
        net = world.net()
        net.fail['livebench.ai'] = md.NetworkError('down')
        result = self.run_world(world, '--probe', net=net)
        self.assertEqual(result.code, 1)
        self.assertEqual(result.outputs['complete'], 'false')

    def test_the_probe_reports_shapes_the_run_would_refuse(self):
        world = World()
        root = self.root(world, discovery={**FIXTURE_DISCOVERY, 'site': {'main_script': 'static/js/main.0000aaaa.js',
                                                                         'reviewed_on': TODAY}})
        world.registry.append('"broken":{openweight:!0,url:n.url}')
        world.files['v1/table_2025_05_30.csv'] = TABLE_2025_05 + b'changed'
        key = next(k for k in world.revisions if k[0] == 'nvidia/nvidia-nemotron-3-super-120b-a12b-nvfp4')
        world.revisions[key]['safetensors']['parameters']['U8'] = 112_764_911_616
        net = world.net()
        net.site['asset-manifest.json'] = asset_manifest('./static/js/main.ffff0000.js')
        result = self.run_world(world, '--probe', net=net, root=root)
        self.assertEqual(result.code, 0, result.stderr)
        step = result.step
        self.assertIn('- main script: unreadable (ShapeError): `expected index.html loading the main script', step)
        self.assertIn('DIFFERS from the recorded source_sha256', step)
        self.assertIn('counts that differ (reported, recorded): `{"U8":[112764911616,56382455808]}`', step)
        self.assertTrue(all(u.startswith(SITE) for u in result.net.calls if 'livebench' in u))
        self.assertFalse(any('github.com' in u for u in result.net.calls))
        world = World()
        world.registry.append('"broken":{openweight:!0,url:n.url}')
        result = self.run_world(world, '--probe')
        self.assertIn('- model registry: not usable: `the registry object at offset', result.step)
        self.assertIn("reviewed script `static/js/main.1e1ce12d.js` (the same)", result.step)

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
            # a forced release never touches the issue (the script also writes complete=false for one)
            self.assertIn("(github.event_name == 'workflow_dispatch' && inputs.update_issue && inputs.release == '')", cond)
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
                     '--json', '--github-output', '--record', '--probe', '--release'):
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

    def test_the_release_input_and_the_leaderboard_site(self):
        dispatch = re.search(r'^  workflow_dispatch:\n(.*?)(?=^\S)', self.TEXT, re.S | re.M).group(1)
        release = re.search(r'^      release:\n((?:        .*\n)+)', dispatch, re.M).group(1)
        self.assertIn('type: string', release)
        self.assertIn('default: ""', release)
        self.assertIn('empty = newest', release)
        self.assertIn('A forced release never touches the tracking issue', release)
        discover = self.block('Discover')
        # the input reaches the script through an env var, never interpolated into the shell text
        self.assertIn("RELEASE: ${{ github.event_name == 'workflow_dispatch' && inputs.release || '' }}", discover)
        self.assertIn('if [ -n "$RELEASE" ]; then args+=(--release "$RELEASE"); fi', discover)
        self.assertNotIn('${{ inputs.release }}', discover.split('run: |', 1)[1])
        # nothing reads api.github.com any more: no GITHUB_TOKEN for the script (the issue steps keep GH_TOKEN)
        self.assertNotIn('GITHUB_TOKEN:', discover)
        self.assertIn('HF_TOKEN: ${{ secrets.HF_TOKEN }}', discover)
        self.assertNotIn('Probe the leaderboard site', self.TEXT)        # the temporary probe step is gone
        self.assertNotIn('www.livebench.ai', self.TEXT)
        self.assertIn('livebench.ai', self.TEXT.split('\non:', 1)[0])     # the header comment names the source

    def test_the_run_deadline_ends_the_reads_before_the_job_timeout(self):
        minutes = int(re.search(r'^    timeout-minutes: (\d+)$', self.TEXT, re.M).group(1))
        # five minutes are left for checkout, the offline tests, the issue reads and writes and the upload
        self.assertLessEqual(md.RUN_DEADLINE + 5 * 60, minutes * 60)


if __name__ == '__main__':
    unittest.main()
