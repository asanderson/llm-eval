"""Offline tests for scripts/upstream_pins.py: policy, parsers and a full bump on a fixture tree.

The scripted upstream is derived from whatever the catalog currently pins, so the
tests hold on a bump PR (and in the nightly workflow right after --apply), not
only on the catalog state they were written against.
"""
import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import unittest
from unittest import mock
import urllib.error

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location('upstream_pins', ROOT / 'scripts' / 'upstream_pins.py')
up = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(up)

CATALOG = json.loads((ROOT / 'catalog' / 'installers.json').read_text(encoding='utf-8'))
PLATFORMS = CATALOG['platforms']
PINNED_LMSTUDIO = PLATFORMS['lmstudio']['version']


def pin_of(entry):
    return entry.split('==', 1)[1]


def bump(version):
    """The next version in the same style: last numeric run + 1 (0.7.0.post4 -> 0.7.0.post5, 0.4.26+4 -> 0.4.26+5)."""
    head, number = re.match(r'^(.*?)(\d+)$', version).groups()
    return f'{head}{int(number) + 1}'


NEXT_LMSTUDIO = bump(PINNED_LMSTUDIO)
NEXT_LMSTUDIO_PATH = NEXT_LMSTUDIO.replace('+', '-')
WINGET_YAML = f"""PackageIdentifier: ElementLabs.LMStudio
PackageVersion: {NEXT_LMSTUDIO}
ReleaseDate: 2026-10-20
Installers:
- Architecture: x86
  InstallerUrl: https://installers.lmstudio.ai/win32/ia32/{NEXT_LMSTUDIO_PATH}/LM-Studio-{NEXT_LMSTUDIO_PATH}-ia32.exe
  InstallerSha256: 1111111111111111111111111111111111111111111111111111111111111111
- Architecture: x64
  InstallerUrl: https://installers.lmstudio.ai/win32/x64/{NEXT_LMSTUDIO_PATH}/LM-Studio-{NEXT_LMSTUDIO_PATH}-x64.exe
  InstallerSha256: ABCDEF0123456789ABCDEF0123456789ABCDEF0123456789ABCDEF0123456789
ManifestType: installer
"""
# Pins the scripted upstream leaves at their current version.
STAYS_CURRENT = {'psutil', 'zstandard', 'accelerate', 'airllm'}
# Newer upstream, but its requires-python drops the harness floor: a manual decision.
PYTHON_FLOOR_BREAKER = 'transformers'


def every_pip_pin():
    groups = [CATALOG['harness_packages'], CATALOG['archive_packages'], [CATALOG['model_download_package']]]
    groups += [r['packages'] for r in PLATFORMS.values() if r.get('kind') == 'pip']
    return {entry.split('==')[0]: pin_of(entry) for group in groups for entry in group}


# The harness floor as a wheel file name spells it (cp311).
FLOOR_TAG = 'cp%d%d' % up.PYTHON_FLOOR


def torch_index_html(names):
    """A wheel listing in the shape download.pytorch.org serves: one PEP 503 anchor per line."""
    lines = ['<!DOCTYPE html>', '<html>', '  <body>', '    <h1>Links for torch</h1>']
    for name in names:
        href = 'https://download-r2.pytorch.org/whl/test/' + name.replace('+', '%2B') + '#sha256=' + '0' * 64
        lines.append(f'    <a href="{href}" data-upload-time="2026-04-27T17:39:29Z">{name}</a><br/>')
    lines += ['  </body>', '</html>', '<!--TIMESTAMP 1794276835-->']
    return '\n'.join(lines) + '\n'


class FakeNet:
    """Scripted upstream derived from the catalog: PyPI, the torch wheel index, GitHub, winget manifests, release assets."""

    def __init__(self, current=False):
        self.hashed = []
        self.pypi_versions = {}
        for name, pinned in every_pip_pin().items():
            if current or name in STAYS_CURRENT:
                self.pypi_versions[name] = (pinned, '>=3.9')
            elif name == PYTHON_FLOOR_BREAKER:
                self.pypi_versions[name] = (bump(pinned), '>=3.12')
            else:
                self.pypi_versions[name] = (bump(pinned), '<3.15,>=3.11')
        torch = PLATFORMS['accelerate']['torch']
        self.torch_next = torch if current else bump(torch)
        # What the recipes' own wheel index serves. PyPI has no torch entry: it is never asked.
        self.torch_served = [torch, self.torch_next]
        self.torch_served_by = {}   # variant -> its own served list, where one index must differ from the other
        self.listed = []
        self.asked_releases = []
        self.ollama_next = PLATFORMS['ollama']['version'] if current else bump(PLATFORMS['ollama']['version'])
        self.kobold_next = PLATFORMS['koboldcpp']['version'] if current else bump(PLATFORMS['koboldcpp']['version'])
        self.sizes = {'ollama-linux-amd64.tar.zst': 10, 'ollama-windows-amd64.zip': 11, 'koboldcpp-linux-x64': 5, 'koboldcpp.exe': 6}

        def asset(repo, tag, name):
            return {'name': name, 'size': self.sizes.get(name, 1),
                    'browser_download_url': f'https://github.com/{repo}/releases/download/{tag}/{name}'}
        ollama_tag, kobold_tag = 'v' + self.ollama_next, 'v' + self.kobold_next
        self.releases = {
            'ollama/ollama': {'tag_name': ollama_tag, 'assets': [asset('ollama/ollama', ollama_tag, n) for n in
                              ('ollama-linux-amd64.tar.zst', 'ollama-windows-amd64.zip', 'sha256sum.txt')]},
            'LostRuins/koboldcpp': {'tag_name': kobold_tag, 'assets': [asset('LostRuins/koboldcpp', kobold_tag, n) for n in
                                    ('koboldcpp-linux-x64', 'koboldcpp.exe')]},
            'ggml-org/llama.cpp': {'tag_name': 'b7100'},
            'Niko1221/Strata': {'tag_name': 'v9.9.9'},
            # ik_llama.cpp follows HEAD: /releases/latest is a 404 there and is never asked
        }
        self.llama_next = PLATFORMS['llama.cpp']['revision'] if current else 'a' * 40
        self.strata_next = PLATFORMS['strata']['revision'] if current else 'c' * 40
        self.ik_next = PLATFORMS['ik_llama.cpp']['revision'] if current else 'd' * 40
        self.tags = {('ggml-org/llama.cpp', 'b7100'): self.llama_next, ('Niko1221/Strata', 'v9.9.9'): self.strata_next}
        self.heads = {'LiveBench/LiveBench': CATALOG['livebench']['revision'], 'ikawrakow/ik_llama.cpp': self.ik_next}
        self.winget = [PINNED_LMSTUDIO, '0.3.9'] if current else ['0.3.9', PINNED_LMSTUDIO, NEXT_LMSTUDIO, 'not-a-version']

    def pypi(self, name):
        return self.pypi_versions[name]

    def torch_listing(self, index_url):
        assert index_url.startswith('https://download.pytorch.org/whl/')
        self.listed.append(index_url)
        variant = index_url.rsplit('/', 1)[1]
        return torch_index_html([f'torch-{version}+{variant}-{FLOOR_TAG}-{FLOOR_TAG}-{platform}.whl'
                                 for version in self.torch_served_by.get(variant, self.torch_served)
                                 for platform in ('manylinux_2_28_x86_64', 'win_amd64')])

    def release(self, repo):
        self.asked_releases.append(repo)
        if repo not in self.releases:
            raise urllib.error.HTTPError(f'https://api.github.com/repos/{repo}/releases/latest', 404, 'Not Found', {}, None)
        return self.releases[repo]

    def tag_commit(self, repo, tag):
        return self.tags[(repo, tag)]

    def head_commit(self, repo):
        return self.heads[repo]

    def winget_versions(self):
        return self.winget

    def winget_installer_yaml(self, version):
        assert version == NEXT_LMSTUDIO
        return WINGET_YAML

    def text(self, url):
        assert url.endswith(f'/v{self.ollama_next}/sha256sum.txt')
        return '%s  ./ollama-linux-amd64.tar.zst\n%s *ollama-windows-amd64.zip\n' % ('1' * 64, '2' * 64)

    def sha256_of(self, url):
        self.hashed.append(url)
        name = url.rsplit('/', 1)[1]
        return hashlib.sha256(url.encode()).hexdigest(), self.sizes[name]


def fixture_root():
    tmp = Path(tempfile.mkdtemp(prefix='upstream-pins-'))
    for rel in ('catalog/installers.json', 'docs/PLATFORMS.md', 'docs/READINESS.md', 'docs/WORKFLOWS.md'):
        (tmp / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / rel, tmp / rel)
    (tmp / 'README.md').write_text(f'Still says LM Studio {PINNED_LMSTUDIO} here.\n'
                                   f"Strata was reviewed at {PLATFORMS['strata']['revision']}.\n", encoding='utf-8')
    (tmp / 'tests').mkdir()
    (tmp / 'tests/test_fixture.py').write_text(f"FAKE = 'ollama version {PLATFORMS['ollama']['version']}'\n", encoding='utf-8')
    return tmp


class PolicyTest(unittest.TestCase):
    def test_version_order_covers_every_pin_style(self):
        self.assertTrue(up.newer('0.7.2', '0.7.0.post4'))
        self.assertTrue(up.newer('0.7.0.post5', '0.7.0.post4'))
        self.assertTrue(up.newer('0.4.27+1', '0.4.26+4'))
        self.assertTrue(up.newer('0.4.26+5', '0.4.26+4'))
        self.assertTrue(up.newer('1.123', '1.122.1'))
        self.assertTrue(up.newer('v0.36.0', '0.35.1'))
        self.assertTrue(up.newer('2.10.0', '2.9.1'))
        self.assertFalse(up.newer('0.35.1', '0.35.1'))
        self.assertFalse(up.newer('0.35.0', '0.35.1'))
        for pinned in every_pip_pin().values():
            self.assertTrue(up.newer(bump(pinned), pinned), pinned)

    def test_python_floor_guard(self):
        self.assertTrue(up.admits_python(None))
        self.assertTrue(up.admits_python('>=3.11'))
        self.assertTrue(up.admits_python('<3.15,>=3.11'))
        self.assertFalse(up.admits_python('>=3.12'))
        self.assertFalse(up.admits_python('>3.11'))
        self.assertTrue(up.admits_python('>3.10'))

    def test_checksum_and_winget_parsers(self):
        self.assertEqual(up.checksum_lines('%s  ./a.zip\n%s *b.exe\nnoise\n' % ('a' * 64, 'B' * 64)),
                         {'a.zip': 'a' * 64, 'b.exe': 'b' * 64})
        sha, date = up.parse_winget_installer(WINGET_YAML)
        self.assertEqual((sha, date), ('abcdef0123456789' * 4, '2026-10-20'))
        self.assertEqual(up.parse_winget_installer('InstallerSha256: ' + 'F' * 64 + '\n'), ('f' * 64, None))

    def test_served_torch_counts_final_releases_the_index_has_for_the_floor_on_both_platforms(self):
        tag = FLOOR_TAG
        near = f'cp{up.PYTHON_FLOOR[0]}{up.PYTHON_FLOOR[1] + 1}'
        listing = torch_index_html([
            # counted: a wheel for the floor on Windows and on Linux x86_64
            f'torch-2.9.1+cu128-{tag}-{tag}-manylinux_2_28_x86_64.whl', f'torch-2.9.1+cu128-{tag}-{tag}-win_amd64.whl',
            f'torch-2.10.0+cu128-{tag}-{tag}-manylinux_2_28_x86_64.whl', f'torch-2.10.0+cu128-{tag}-{tag}-win_amd64.whl',
            f'torch-2.0.1-{tag}-{tag}-manylinux_2_17_x86_64.manylinux2014_x86_64.whl', f'torch-2.0.1-{tag}-{tag}-win_amd64.whl',
            f'torch-2.0.0-{tag}-{tag}-linux_x86_64.whl', f'torch-2.0.0-1-{tag}-{tag}-win_amd64.whl',   # -1: a build tag
            # not counted: one platform only, another architecture, another Python, not a plain X.Y.Z release
            f'torch-2.12.0+cu128-{tag}-{tag}-manylinux_2_28_x86_64.whl',
            f'torch-2.13.0+cu128-{tag}-{tag}-win_amd64.whl',
            f'torch-2.14.0+cu128-{tag}-{tag}-manylinux_2_28_aarch64.whl', f'torch-2.14.0+cu128-{tag}-{tag}-win_amd64.whl',
            'torch-2.15.0+cu128-cp399-cp399-manylinux_2_28_x86_64.whl', 'torch-2.15.0+cu128-cp399-cp399-win_amd64.whl',
            f'torch-2.21.0+cu128-{near}-{near}-manylinux_2_28_x86_64.whl', f'torch-2.21.0+cu128-{near}-{near}-win_amd64.whl',   # the next Python up
            f'torch-2.16.0.dev20261101+cu128-{tag}-{tag}-manylinux_2_28_x86_64.whl',
            f'torch-2.16.0.dev20261101+cu128-{tag}-{tag}-win_amd64.whl',
            f'torch-2.17.0rc1+cu128-{tag}-{tag}-manylinux_2_28_x86_64.whl', f'torch-2.17.0rc1+cu128-{tag}-{tag}-win_amd64.whl',
            f'torch-2.18.0.post1-{tag}-{tag}-manylinux_2_28_x86_64.whl', f'torch-2.18.0.post1-{tag}-{tag}-win_amd64.whl',
            f'torch-2.19.0-{tag}-none-macosx_10_9_x86_64.whl', f'torch-2.19.0-{tag}-{tag}-win_amd64.whl',
            f'torch-2.20.0+cu128-{tag}-{tag}-manylinux_2_28_x86_64.whl', f'torch-2.20.0+cu128-{tag}-{tag}-win_arm64.whl',
        ])
        served = up.served_torch(listing)
        self.assertEqual(served, {'2.0.0', '2.0.1', '2.9.1', '2.10.0'})
        self.assertEqual(max(served, key=up.vtuple), '2.10.0')
        self.assertEqual(up.served_torch(listing, floor=(3, 99)), {'2.15.0'})
        self.assertEqual(up.served_torch(torch_index_html([])), set())

    def test_the_torch_listing_is_read_from_the_torch_page_of_the_index(self):
        net, asked = up.Net(), []
        net.text = lambda url: asked.append(url) or '<html></html>'
        net.torch_listing('https://download.pytorch.org/whl/cu128')
        net.torch_listing('https://download.pytorch.org/whl/cu128/')
        self.assertEqual(asked, ['https://download.pytorch.org/whl/cu128/torch/'] * 2)


class RealCatalogTest(unittest.TestCase):
    def test_every_pin_is_in_the_shape_the_resolver_expects(self):
        p = PLATFORMS
        for entry in (*CATALOG['harness_packages'], *CATALOG['archive_packages'], CATALOG['model_download_package'],
                      *[x for r in p.values() if r.get('kind') == 'pip' for x in r['packages']]):
            self.assertRegex(entry, up.PIN)
        for name in ('ollama', 'koboldcpp'):
            for asset in p[name]['assets'].values():
                self.assertTrue(asset['url'].endswith('/' + asset['filename']), asset['url'])
                self.assertIn(f"/v{p[name]['version']}/", asset['url'])
                self.assertRegex(asset['sha256'], r'^[0-9a-f]{64}$')
        for name in ('llama.cpp', 'ik_llama.cpp', 'strata'):
            self.assertRegex(p[name]['repository'], up.GITHUB_REPO)
            self.assertRegex(p[name]['revision'], r'^[0-9a-f]{40}$')
        self.assertRegex(CATALOG['livebench']['repository'], up.GITHUB_REPO)
        for name, recipe in p.items():
            if 'torch' in recipe:   # followed on the recipe's own download.pytorch.org wheel index, never on PyPI
                self.assertRegex(recipe['torch'], r'^\d+(\.\d+)+$', name)
                self.assertRegex(recipe['torch_index'], r'^https://download\.pytorch\.org/whl/[a-z0-9]+$', name)
        for asset in p['lmstudio']['assets'].values():
            self.assertIn(p['lmstudio']['version'].replace('+', '-'), asset['url'])
        for rel in up.LMSTUDIO_MENTIONS:
            self.assertIn(PINNED_LMSTUDIO, (ROOT / rel).read_text(encoding='utf-8'), rel)


class BumpTest(unittest.TestCase):
    def test_full_bump_rewrites_catalog_and_docs_and_reports_the_rest(self):
        root, net = fixture_root(), FakeNet()
        result = up.run(net, root, apply=True, today='2026-10-28')
        self.assertTrue(result['changed'] and result['applied'])
        text = (root / 'catalog/installers.json').read_text(encoding='utf-8')
        self.assertTrue(text.endswith('}\n'))
        cat = json.loads(text)
        self.assertEqual(json.dumps(cat, indent=2) + '\n', text)
        p = cat['platforms']
        self.assertEqual(cat['checked_on'], '2026-10-28')
        pins = every_pip_pin()
        self.assertEqual(cat['harness_packages'], [f"psutil=={pins['psutil']}"])
        self.assertEqual(p['ktransformers']['packages'], [f"kt-kernel=={bump(pins['kt-kernel'])}", f"sglang-kt=={bump(pins['sglang-kt'])}"])
        self.assertEqual(p['vllm']['packages'], [f"vllm=={bump(pins['vllm'])}"])
        self.assertEqual(cat['model_download_package'], f"huggingface-hub=={bump(pins['huggingface-hub'])}")
        self.assertIn(f"transformers=={pins['transformers']}", p['accelerate']['packages'])   # python floor: untouched
        self.assertIn(f"sentencepiece=={bump(pins['sentencepiece'])}", p['airllm']['packages'])
        self.assertEqual((p['accelerate']['torch'], p['airllm']['torch']), (net.torch_next, net.torch_next))
        self.assertEqual(p['ollama']['version'], net.ollama_next)
        self.assertEqual(p['ollama']['assets']['linux'], {
            'url': f'https://github.com/ollama/ollama/releases/download/v{net.ollama_next}/ollama-linux-amd64.tar.zst',
            'sha256': '1' * 64, 'bytes': 10, 'filename': 'ollama-linux-amd64.tar.zst'})
        self.assertEqual(p['ollama']['assets']['windows']['sha256'], '2' * 64)
        self.assertEqual(p['koboldcpp']['version'], net.kobold_next)
        win = p['koboldcpp']['assets']['windows']
        self.assertEqual((win['bytes'], win['sha256']), (6, hashlib.sha256(win['url'].encode()).hexdigest()))
        self.assertEqual(sorted(u.rsplit('/', 1)[1] for u in net.hashed), ['koboldcpp-linux-x64', 'koboldcpp.exe'])
        self.assertEqual(p['llama.cpp']['revision'], 'a' * 40)
        self.assertEqual(p['ik_llama.cpp']['revision'], 'd' * 40)   # no release upstream: the default branch HEAD
        self.assertEqual(p['strata']['revision'], 'c' * 40)         # the commit behind the newest release tag
        lm = p['lmstudio']
        self.assertEqual((lm['version'], lm['release_date']), (NEXT_LMSTUDIO, '2026-10-20'))
        self.assertEqual(lm['assets']['windows']['sha256'], 'abcdef0123456789' * 4)
        self.assertEqual(lm['assets']['windows']['url'],
                         f'https://installers.lmstudio.ai/win32/x64/{NEXT_LMSTUDIO_PATH}/LM-Studio-{NEXT_LMSTUDIO_PATH}-x64.exe')
        self.assertEqual(lm['assets']['linux']['filename'], f'LM-Studio-{NEXT_LMSTUDIO_PATH}-x64.AppImage')
        self.assertIsNone(lm['assets']['linux']['sha256'])
        self.assertIn(NEXT_LMSTUDIO.replace('+', '%2B'), lm['assets']['windows']['sha256_source'])
        for rel in up.LMSTUDIO_MENTIONS:
            doc = (root / rel).read_text(encoding='utf-8')
            self.assertIn(NEXT_LMSTUDIO, doc)
            self.assertNotIn(PINNED_LMSTUDIO, doc)
        self.assertEqual(result['touched'], ['catalog/installers.json', *up.LMSTUDIO_MENTIONS])
        self.assertIn(('README.md', PINNED_LMSTUDIO), result['stale'])
        self.assertIn(('README.md', PLATFORMS['strata']['revision'][:12]), result['stale'])
        self.assertIn(('tests/test_fixture.py', PLATFORMS['ollama']['version']), result['stale'])
        self.assertTrue(all(rel != 'tests/test_upstream_pins.py' for rel, _ in result['stale']), result['stale'])
        self.assertEqual(sorted(r.name for r in result['manual']), ['accelerate transformers', 'airllm transformers'])
        self.assertEqual(result['failures'], [])
        summary = up.markdown_summary(result)
        self.assertIn(f"| ollama | `{PLATFORMS['ollama']['version']}` | `{net.ollama_next}` | bumped |", summary)
        self.assertIn(f"| strata | `{PLATFORMS['strata']['revision'][:12]}` | `v9.9.9 (cccccccccccc)` | bumped |", summary)
        self.assertIn(f"| ik_llama.cpp | `{PLATFORMS['ik_llama.cpp']['revision'][:12]}` | `HEAD (dddddddddddd)` | bumped |", summary)
        self.assertIn('| livebench |', summary)
        self.assertIn('Needs a manual decision', summary)
        self.assertIn(f'- `README.md`: still names `{PINNED_LMSTUDIO}`', summary)
        self.assertIn('### Files rewritten', summary)
        # The tracking issue carries the same table and decisions, not the PR's diff sections.
        issue = up.markdown_summary(result, issue=True)
        self.assertIn(f"| ollama | `{PLATFORMS['ollama']['version']}` | `{net.ollama_next}` | bumped |", issue)
        self.assertIn('| livebench |', issue)
        self.assertIn('Needs a manual decision', issue)
        self.assertNotIn('Files rewritten', issue)
        self.assertNotIn('still names', issue)

    def test_nothing_newer_leaves_every_file_alone(self):
        root = fixture_root()
        before = {rel: (root / rel).read_bytes() for rel in ('catalog/installers.json', 'docs/PLATFORMS.md')}
        result = up.run(FakeNet(current=True), root, apply=True, today='2026-10-28')
        self.assertFalse(result['changed'])
        self.assertEqual(result['touched'], [])
        for rel, data in before.items():
            self.assertEqual((root / rel).read_bytes(), data)
        self.assertTrue(all(r.status == 'current' for r in result['rows']), [(r.name, r.status, r.detail) for r in result['rows']])

    def test_report_mode_never_writes_and_failures_are_rows_not_crashes(self):
        root, net = fixture_root(), FakeNet()
        net.pypi_versions.pop('vllm')   # resolver raises KeyError
        before = (root / 'catalog/installers.json').read_bytes()
        result = up.run(net, root, apply=False, today='2026-10-28')
        self.assertTrue(result['changed'])
        self.assertFalse(result['applied'])
        self.assertEqual((root / 'catalog/installers.json').read_bytes(), before)
        self.assertEqual([r.name for r in result['failures']], ['vllm vllm'])
        self.assertFalse(any(r.changed for r in result['rows']))

    def test_torch_follows_its_own_wheel_index_and_never_pypi(self):
        # PyPI moved on while the pinned CUDA index stayed put: not a bump, and not a decision to raise.
        root, net = fixture_root(), FakeNet(current=True)
        net.pypi_versions['torch'] = ('99.0.0', '>=3.10')
        result = up.run(net, root, apply=True, today='2026-10-28')
        self.assertFalse(result['changed'])
        self.assertEqual((result['manual'], result['failures']), ([], []))
        rows = {r.name: r for r in result['rows']}
        for name in ('accelerate', 'airllm'):
            self.assertEqual((rows[f'{name} torch'].latest, rows[f'{name} torch'].status), (PLATFORMS[name]['torch'], 'current'))
        self.assertEqual(set(net.listed), {PLATFORMS['accelerate']['torch_index'], PLATFORMS['airllm']['torch_index']})

    def test_a_torch_pin_ahead_of_its_index_is_a_manual_decision_never_a_downgrade(self):
        root, net = fixture_root(), FakeNet(current=True)
        path = root / 'catalog/installers.json'
        cat = json.loads(path.read_text(encoding='utf-8'))
        for name in ('accelerate', 'airllm'):
            cat['platforms'][name]['torch'] = bump(PLATFORMS[name]['torch'])
        path.write_text(json.dumps(cat, indent=2) + '\n', encoding='utf-8')
        before = path.read_bytes()
        result = up.run(net, root, apply=True, today='2026-10-28')
        self.assertEqual(sorted(r.name for r in result['manual']), ['accelerate torch', 'airllm torch'])
        self.assertTrue(all('newer than anything' in r.detail for r in result['manual']), [r.detail for r in result['manual']])
        self.assertEqual(result['failures'], [])
        self.assertEqual(path.read_bytes(), before)

    def test_the_newest_served_torch_is_picked_by_version_not_as_text(self):
        # 2.9.1 sorts after 2.10.0 as text and before it as a version.
        root, net = fixture_root(), FakeNet(current=True)
        path = root / 'catalog/installers.json'
        cat = json.loads(path.read_text(encoding='utf-8'))
        for name in ('accelerate', 'airllm'):
            cat['platforms'][name]['torch'] = '2.9.1'
        path.write_text(json.dumps(cat, indent=2) + '\n', encoding='utf-8')
        net.torch_served = ['2.9.1', '2.10.0']
        up.run(net, root, apply=True, today='2026-10-28')
        cat = json.loads(path.read_text(encoding='utf-8'))
        self.assertEqual([cat['platforms'][name]['torch'] for name in ('accelerate', 'airllm')], ['2.10.0', '2.10.0'])

    def test_each_recipe_follows_its_own_wheel_index(self):
        root, net = fixture_root(), FakeNet(current=True)
        path = root / 'catalog/installers.json'
        cat = json.loads(path.read_text(encoding='utf-8'))
        other = 'https://download.pytorch.org/whl/cu999'
        cat['platforms']['airllm']['torch_index'] = other
        path.write_text(json.dumps(cat, indent=2) + '\n', encoding='utf-8')
        ahead = bump(PLATFORMS['airllm']['torch'])
        net.torch_served_by['cu999'] = [PLATFORMS['airllm']['torch'], ahead]
        up.run(net, root, apply=True, today='2026-10-28')
        cat = json.loads(path.read_text(encoding='utf-8'))
        self.assertEqual((cat['platforms']['accelerate']['torch'], cat['platforms']['airllm']['torch']), (PLATFORMS['accelerate']['torch'], ahead))
        self.assertEqual((cat['platforms']['accelerate']['torch_index'], cat['platforms']['airllm']['torch_index']), (PLATFORMS['accelerate']['torch_index'], other))
        self.assertEqual(sorted(net.listed), sorted([PLATFORMS['accelerate']['torch_index'], other]))

    def test_an_index_with_no_torch_wheel_for_both_platforms_is_a_failure_row(self):
        root, net = fixture_root(), FakeNet()
        net.torch_served = []
        result = up.run(net, root, apply=False, today='2026-10-28')
        self.assertEqual(sorted(r.name for r in result['failures']), ['accelerate torch', 'airllm torch'])

    def test_a_head_follower_takes_the_branch_head_and_ignores_releases(self):
        root, net = fixture_root(), FakeNet()
        net.releases['ikawrakow/ik_llama.cpp'] = {'tag_name': 't0002'}   # a release, should one appear, must not win
        net.tags[('ikawrakow/ik_llama.cpp', 't0002')] = 'f' * 40
        up.run(net, root, apply=True, today='2026-10-28')
        cat = json.loads((root / 'catalog/installers.json').read_text(encoding='utf-8'))
        self.assertEqual(cat['platforms']['ik_llama.cpp']['revision'], 'd' * 40)
        self.assertNotIn('ikawrakow/ik_llama.cpp', net.asked_releases)

    def test_a_release_follower_without_a_release_keeps_its_pin_and_asks(self):
        root, net = fixture_root(), FakeNet()
        del net.releases['Niko1221/Strata']       # /releases/latest answers 404
        net.heads['Niko1221/Strata'] = 'e' * 40   # HEAD has moved, and is still not taken
        result = up.run(net, root, apply=True, today='2026-10-28')
        cat = json.loads((root / 'catalog/installers.json').read_text(encoding='utf-8'))
        self.assertEqual(cat['platforms']['strata']['revision'], PLATFORMS['strata']['revision'])
        strata = next(r for r in result['rows'] if r.name == 'strata')
        self.assertEqual((strata.status, strata.changed), ('manual', False))
        self.assertIn(strata, result['manual'])
        self.assertEqual(result['failures'], [])
        self.assertIn('manual: no GitHub release to follow', up.markdown_summary(result, issue=True))

    def test_a_release_lookup_error_other_than_404_is_a_failure_not_a_decision(self):
        for code in (403, 500):
            with self.subTest(code=code):
                root, net = fixture_root(), FakeNet()
                scripted = net.release

                def release(repo):
                    if repo == 'Niko1221/Strata':
                        raise urllib.error.HTTPError(f'https://api.github.com/repos/{repo}/releases/latest', code, 'Error', {}, None)
                    return scripted(repo)
                net.release = release
                result = up.run(net, root, apply=False, today='2026-10-28')
                self.assertEqual([r.name for r in result['failures']], ['strata'])
                self.assertNotIn('strata', [r.name for r in result['manual']])

    def test_a_release_tag_with_markup_characters_is_not_followed_and_never_reaches_the_reports(self):
        hostile = 'v1`|<x>@y'
        for repo, name, key in (('Niko1221/Strata', 'strata', 'revision'), ('ollama/ollama', 'ollama', 'version')):
            with self.subTest(repo=repo):
                root, net = fixture_root(), FakeNet()
                net.releases[repo] = dict(net.releases[repo], tag_name=hostile)
                net.tags[(repo, hostile)] = 'f' * 40
                result = up.run(net, root, apply=True, today='2026-10-28')
                self.assertEqual([r.name for r in result['failures']], [name])
                written = (root / 'catalog/installers.json').read_text(encoding='utf-8')
                self.assertEqual(json.loads(written)['platforms'][name][key], PLATFORMS[name][key])
                for text in (written, up.markdown_summary(result), up.markdown_summary(result, issue=True)):
                    self.assertNotIn('<x>', text)

    def test_release_tag_names_are_limited_to_characters_safe_in_the_catalog_a_url_and_markdown(self):
        for tag in ('v0.2.13', 'b7100', '0.4.26+4', 'v1_2-rc1', '7'):
            with self.subTest(accepted=tag):
                self.assertEqual(up.checked_tag({'tag_name': tag}), tag)
        for tag in ('', 'a/../x', 'release/1.0', 'v1 2', 'v1#x', 'v1?x', 'v1%2f', 'v1:x', 'v1\\x', '-v1', '.v1', '+v1',
                    '_v1', 'v1\n', 'v1\u00e9', 'v1`|<x>@y'):
            with self.subTest(rejected=tag):
                with self.assertRaises(ValueError):
                    up.checked_tag({'tag_name': tag})

    def test_livebench_head_drift_is_reported_as_a_decision_and_never_rewritten(self):
        root, net = fixture_root(), FakeNet(current=True)
        net.heads['LiveBench/LiveBench'] = 'e' * 40
        before = (root / 'catalog/installers.json').read_bytes()
        result = up.run(net, root, apply=True, today='2026-10-28')
        self.assertEqual([(r.name, r.latest) for r in result['manual']], [('livebench', 'e' * 12)])
        self.assertIn('reviewed-commit', result['manual'][0].detail)
        self.assertFalse(result['changed'])
        self.assertEqual((root / 'catalog/installers.json').read_bytes(), before)

    def test_a_torch_index_that_cannot_be_read_is_a_failure_row_and_keeps_the_pin(self):
        root, net = fixture_root(), FakeNet()

        def torch_listing(index_url):
            raise urllib.error.HTTPError(index_url + '/torch/', 404, 'Not Found', {}, None)
        net.torch_listing = torch_listing
        result = up.run(net, root, apply=True, today='2026-10-28')
        self.assertEqual(sorted(r.name for r in result['failures']), ['accelerate torch', 'airllm torch'])
        self.assertEqual([r.name for r in result['manual'] if r.name.endswith(' torch')], [])
        written = json.loads((root / 'catalog/installers.json').read_text(encoding='utf-8'))['platforms']
        for name in ('accelerate', 'airllm'):
            self.assertEqual(written[name]['torch'], PLATFORMS[name]['torch'])

    def test_a_recipe_without_a_wheel_index_is_a_failure_row_and_no_default_index_is_asked(self):
        root, net = fixture_root(), FakeNet()
        path = root / 'catalog/installers.json'
        cat = json.loads(path.read_text(encoding='utf-8'))
        del cat['platforms']['airllm']['torch_index']
        path.write_text(json.dumps(cat, indent=2) + '\n', encoding='utf-8')
        result = up.run(net, root, apply=True, today='2026-10-28')
        self.assertEqual([r.name for r in result['failures']], ['airllm torch'])
        self.assertEqual(net.listed, [PLATFORMS['accelerate']['torch_index']])
        written = json.loads(path.read_text(encoding='utf-8'))['platforms']
        self.assertEqual(written['airllm']['torch'], PLATFORMS['airllm']['torch'])
        self.assertEqual(written['accelerate']['torch'], net.torch_next)


class MainTest(unittest.TestCase):
    """The three step outputs the workflow branches on: `changed` opens the bump PR, `manual` refreshes the issue, and
    the issue closes only when `manual` and `failed` are both false."""

    def outputs(self, net, *extra):
        root = fixture_root()
        out = root / 'github-output.txt'
        with mock.patch.object(up, 'Net', lambda: net), mock.patch.object(up, 'ROOT', root), \
                mock.patch.object(sys, 'argv', ['upstream_pins.py', '--github-output', *extra]), \
                mock.patch.dict(os.environ, {'GITHUB_OUTPUT': str(out)}), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(up.main(), 0)
        return dict(line.split('=', 1) for line in out.read_text(encoding='utf-8').split())

    def test_a_report_run_announces_no_change_and_the_open_decision(self):
        self.assertEqual(self.outputs(FakeNet()), {'changed': 'false', 'manual': 'true', 'failed': 'false'})

    def test_an_apply_run_announces_the_change_and_the_open_decision(self):
        self.assertEqual(self.outputs(FakeNet(), '--apply'), {'changed': 'true', 'manual': 'true', 'failed': 'false'})

    def test_a_run_with_nothing_to_decide_says_so_and_lets_the_issue_close(self):
        self.assertEqual(self.outputs(FakeNet(current=True), '--apply'),
                         {'changed': 'false', 'manual': 'false', 'failed': 'false'})

    def test_a_failed_lookup_is_announced_so_the_issue_is_not_closed_on_a_guess(self):
        net = FakeNet(current=True)
        net.pypi_versions.pop('vllm')   # resolver raises KeyError
        self.assertEqual(self.outputs(net, '--apply'), {'changed': 'false', 'manual': 'false', 'failed': 'true'})

    def test_livebench_head_drift_alone_keeps_the_decision_open(self):
        net = FakeNet(current=True)
        net.heads['LiveBench/LiveBench'] = 'e' * 40
        self.assertEqual(self.outputs(net, '--apply'), {'changed': 'false', 'manual': 'true', 'failed': 'false'})


class WorkflowGateTest(unittest.TestCase):
    """How .github/workflows/upstream-pins.yml reads those outputs."""

    TEXT = (ROOT / '.github/workflows/upstream-pins.yml').read_text(encoding='utf-8')

    def step(self, name):
        start = self.TEXT.index(f'      - name: {name}\n')
        end = self.TEXT.find('\n      - name: ', start)
        return self.TEXT[start:] if end < 0 else self.TEXT[start:end]

    def test_the_issue_is_refreshed_on_a_decision_and_closed_only_after_a_run_without_failed_lookups(self):
        self.assertIn(' --github-output\n', self.step('Resolve upstream and apply the bumps'))
        self.assertIn("\n        if: steps.resolve.outputs.manual == 'true'\n",
                      self.step('Refresh the tracking issue with the pins that need a manual decision'))
        self.assertIn("\n        if: steps.resolve.outputs.manual == 'false' && steps.resolve.outputs.failed == 'false'\n",
                      self.step('Close the tracking issue once no pin needs a manual decision'))


if __name__ == '__main__':
    unittest.main()
