"""Offline tests for scripts/upstream_pins.py: policy, parsers and a full bump on a fixture tree.

The scripted upstream is derived from whatever the catalog currently pins, so the
tests hold on a bump PR (and in the nightly workflow right after --apply), not
only on the catalog state they were written against.
"""
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import tempfile
import unittest
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


class FakeNet:
    """Scripted upstream derived from the catalog: PyPI, GitHub releases, winget manifests, release assets."""

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
        self.pypi_versions['torch'] = (self.torch_next, '>=3.10')
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
            # ik_llama.cpp publishes no releases: /releases/latest is a 404
        }
        self.llama_next = PLATFORMS['llama.cpp']['revision'] if current else 'a' * 40
        self.tags = {('ggml-org/llama.cpp', 'b7100'): self.llama_next}
        self.heads = {'Niko1221/Strata': PLATFORMS['strata']['revision'] if current else 'c' * 40,
                      'LiveBench/LiveBench': CATALOG['livebench']['revision'],
                      'ikawrakow/ik_llama.cpp': PLATFORMS['ik_llama.cpp']['revision'] if current else 'd' * 40}
        self.winget = [PINNED_LMSTUDIO, '0.3.9'] if current else ['0.3.9', PINNED_LMSTUDIO, NEXT_LMSTUDIO, 'not-a-version']

    def pypi(self, name):
        return self.pypi_versions[name]

    def torch_index_has(self, index_url, version):
        assert index_url.startswith('https://download.pytorch.org/whl/')
        return version == self.torch_next

    def release(self, repo):
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
    (tmp / 'README.md').write_text(f'Still says LM Studio {PINNED_LMSTUDIO} here.\n', encoding='utf-8')
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
        self.assertEqual(p['ik_llama.cpp']['revision'], PLATFORMS['ik_llama.cpp']['revision'])   # no releases: reported only
        self.assertEqual(p['strata']['revision'], PLATFORMS['strata']['revision'])
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
        self.assertEqual(result['stale'], ['README.md'])
        self.assertEqual(sorted(r.name for r in result['manual']),
                         ['accelerate transformers', 'airllm transformers', 'ik_llama.cpp', 'strata'])
        self.assertEqual(result['failures'], [])
        summary = up.markdown_summary(result)
        self.assertIn(f"| ollama | `{PLATFORMS['ollama']['version']}` | `{net.ollama_next}` | bumped |", summary)
        self.assertIn('| livebench |', summary)
        self.assertIn('no GitHub release', summary)
        self.assertIn('Needs a manual decision', summary)
        self.assertIn('`README.md`', summary)

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


if __name__ == '__main__':
    unittest.main()
