"""Offline tests for scripts/upstream_pins.py: policy, parsers and a full bump on a fixture tree."""
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location('upstream_pins', ROOT / 'scripts' / 'upstream_pins.py')
up = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(up)

CATALOG = json.loads((ROOT / 'catalog' / 'installers.json').read_text(encoding='utf-8'))
PINNED_LMSTUDIO = CATALOG['platforms']['lmstudio']['version']
WINGET_YAML = """PackageIdentifier: ElementLabs.LMStudio
PackageVersion: 0.4.27+2
ReleaseDate: 2026-10-20
Installers:
- Architecture: x86
  InstallerUrl: https://installers.lmstudio.ai/win32/ia32/0.4.27-2/LM-Studio-0.4.27-2-ia32.exe
  InstallerSha256: 1111111111111111111111111111111111111111111111111111111111111111
- Architecture: x64
  InstallerUrl: https://installers.lmstudio.ai/win32/x64/0.4.27-2/LM-Studio-0.4.27-2-x64.exe
  InstallerSha256: ABCDEF0123456789ABCDEF0123456789ABCDEF0123456789ABCDEF0123456789
ManifestType: installer
"""


class FakeNet:
    """Scripted upstream: PyPI, GitHub releases, winget manifests, release assets."""

    def __init__(self, current=False):
        p = CATALOG['platforms']
        pin = lambda s: s.split('==', 1)[1]  # noqa: E731
        if current:
            self.pypi_versions = {}
            for group in (CATALOG['harness_packages'], CATALOG['archive_packages'], [CATALOG['model_download_package']],
                          *[r['packages'] for r in p.values() if r.get('kind') == 'pip']):
                for entry in group:
                    self.pypi_versions[entry.split('==')[0]] = (pin(entry), '>=3.9')
            self.pypi_versions['torch'] = (p['accelerate']['torch'], '>=3.10')
            self.releases = {
                'ollama/ollama': {'tag_name': 'v' + p['ollama']['version'], 'assets': []},
                'LostRuins/koboldcpp': {'tag_name': 'v' + p['koboldcpp']['version'], 'assets': []},
                'ggml-org/llama.cpp': {'tag_name': 'b7000'}, 'ikawrakow/ik_llama.cpp': {'tag_name': 'v1'}}
            self.tags = {('ggml-org/llama.cpp', 'b7000'): p['llama.cpp']['revision'],
                         ('ikawrakow/ik_llama.cpp', 'v1'): p['ik_llama.cpp']['revision']}
            self.heads = {'Niko1221/Strata': p['strata']['revision'], 'LiveBench/LiveBench': CATALOG['livebench']['revision']}
            self.winget = [PINNED_LMSTUDIO, '0.3.9']
            return
        self.pypi_versions = {
            'psutil': ('7.2.2', '>=3.6'), 'zstandard': ('0.25.0', '>=3.9'),
            'kt-kernel': ('0.7.2', '>=3.10'), 'sglang-kt': ('0.7.2', '>=3.10'),
            'transformers': ('5.21.0', '>=3.12'),          # drops the 3.11 floor: manual
            'accelerate': ('1.15.0', '>=3.10.0'), 'sentencepiece': ('0.2.2', '>=3.9'),
            'airllm': ('4.0.0', None), 'vllm': ('0.32.0', '<3.15,>=3.11'),
            'huggingface-hub': ('2.3.0', '>=3.10.0'), 'torch': ('2.10.0', '>=3.10'),
        }
        self.sizes = {'ollama-linux-amd64.tar.zst': 10, 'ollama-windows-amd64.zip': 11, 'koboldcpp-linux-x64': 5, 'koboldcpp.exe': 6}
        asset = lambda repo, tag, name: {'name': name, 'size': self.sizes.get(name, 1),  # noqa: E731
                                         'browser_download_url': f'https://github.com/{repo}/releases/download/{tag}/{name}'}
        self.releases = {
            'ollama/ollama': {'tag_name': 'v0.36.0', 'assets': [asset('ollama/ollama', 'v0.36.0', n) for n in
                              ('ollama-linux-amd64.tar.zst', 'ollama-windows-amd64.zip', 'sha256sum.txt')]},
            'LostRuins/koboldcpp': {'tag_name': 'v1.123', 'assets': [asset('LostRuins/koboldcpp', 'v1.123', n) for n in
                                    ('koboldcpp-linux-x64', 'koboldcpp.exe')]},
            'ggml-org/llama.cpp': {'tag_name': 'b7100'},
            'ikawrakow/ik_llama.cpp': {'tag_name': 'v1'},
        }
        self.tags = {('ggml-org/llama.cpp', 'b7100'): 'a' * 40, ('ikawrakow/ik_llama.cpp', 'v1'): p['ik_llama.cpp']['revision']}
        self.heads = {'Niko1221/Strata': 'c' * 40, 'LiveBench/LiveBench': CATALOG['livebench']['revision']}
        self.winget = ['0.3.9', PINNED_LMSTUDIO, '0.4.27+2', 'not-a-version']
        self.hashed = []

    def pypi(self, name):
        return self.pypi_versions[name]

    def torch_index_has(self, index_url, version):
        assert index_url.startswith('https://download.pytorch.org/whl/')
        return version == '2.10.0'

    def release(self, repo):
        return self.releases[repo]

    def tag_commit(self, repo, tag):
        return self.tags[(repo, tag)]

    def head_commit(self, repo):
        return self.heads[repo]

    def winget_versions(self):
        return self.winget

    def winget_installer_yaml(self, version):
        assert version == '0.4.27+2'
        return WINGET_YAML

    def text(self, url):
        assert url.endswith('/v0.36.0/sha256sum.txt')
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
        self.assertTrue(up.newer('0.4.27+1', '0.4.26+4'))
        self.assertTrue(up.newer('0.4.26+5', '0.4.26+4'))
        self.assertTrue(up.newer('1.123', '1.122.1'))
        self.assertTrue(up.newer('v0.36.0', '0.35.1'))
        self.assertTrue(up.newer('2.10.0', '2.9.1'))
        self.assertFalse(up.newer('0.35.1', '0.35.1'))
        self.assertFalse(up.newer('0.35.0', '0.35.1'))

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
        p = CATALOG['platforms']
        for entry in (*CATALOG['harness_packages'], *CATALOG['archive_packages'], CATALOG['model_download_package'],
                      *[x for r in p.values() if r.get('kind') == 'pip' for x in r['packages']]):
            self.assertRegex(entry, up.PIN)
        for name in ('ollama', 'koboldcpp'):
            for asset in p[name]['assets'].values():
                self.assertTrue(asset['url'].endswith('/' + asset['filename']), asset['url'])
                self.assertIn(f"/v{p[name]['version']}/", asset['url'])
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
        self.assertEqual(cat['harness_packages'], ['psutil==7.2.2'])
        self.assertEqual(p['ktransformers']['packages'], ['kt-kernel==0.7.2', 'sglang-kt==0.7.2'])
        self.assertEqual(p['vllm']['packages'], ['vllm==0.32.0'])
        self.assertEqual(cat['model_download_package'], 'huggingface-hub==2.3.0')
        self.assertIn('transformers==5.18.0', p['accelerate']['packages'])   # python floor: untouched
        self.assertIn('sentencepiece==0.2.2', p['airllm']['packages'])
        self.assertEqual((p['accelerate']['torch'], p['airllm']['torch']), ('2.10.0', '2.10.0'))
        self.assertEqual(p['ollama']['version'], '0.36.0')
        self.assertEqual(p['ollama']['assets']['linux'], {
            'url': 'https://github.com/ollama/ollama/releases/download/v0.36.0/ollama-linux-amd64.tar.zst',
            'sha256': '1' * 64, 'bytes': 10, 'filename': 'ollama-linux-amd64.tar.zst'})
        self.assertEqual(p['ollama']['assets']['windows']['sha256'], '2' * 64)
        self.assertEqual(p['koboldcpp']['version'], '1.123')
        win = p['koboldcpp']['assets']['windows']
        self.assertEqual((win['bytes'], win['sha256']), (6, hashlib.sha256(win['url'].encode()).hexdigest()))
        self.assertEqual(sorted(u.rsplit('/', 1)[1] for u in net.hashed), ['koboldcpp-linux-x64', 'koboldcpp.exe'])
        self.assertEqual(p['llama.cpp']['revision'], 'a' * 40)
        self.assertEqual(p['ik_llama.cpp']['revision'], CATALOG['platforms']['ik_llama.cpp']['revision'])
        self.assertEqual(p['strata']['revision'], CATALOG['platforms']['strata']['revision'])
        lm = p['lmstudio']
        self.assertEqual((lm['version'], lm['release_date']), ('0.4.27+2', '2026-10-20'))
        self.assertEqual(lm['assets']['windows']['sha256'], 'abcdef0123456789' * 4)
        self.assertEqual(lm['assets']['windows']['url'], 'https://installers.lmstudio.ai/win32/x64/0.4.27-2/LM-Studio-0.4.27-2-x64.exe')
        self.assertEqual(lm['assets']['linux']['filename'], 'LM-Studio-0.4.27-2-x64.AppImage')
        self.assertIsNone(lm['assets']['linux']['sha256'])
        self.assertIn('0.4.27%2B2', lm['assets']['windows']['sha256_source'])
        for rel in up.LMSTUDIO_MENTIONS:
            doc = (root / rel).read_text(encoding='utf-8')
            self.assertIn('0.4.27+2', doc)
            self.assertNotIn(PINNED_LMSTUDIO, doc)
        self.assertEqual(result['touched'], ['catalog/installers.json', *up.LMSTUDIO_MENTIONS])
        self.assertEqual(result['stale'], ['README.md'])
        self.assertEqual(sorted(r.name for r in result['manual']), ['accelerate transformers', 'airllm transformers', 'strata'])
        self.assertEqual(result['failures'], [])
        summary = up.markdown_summary(result)
        self.assertIn('| ollama | `0.35.1` | `0.36.0` | bumped |', summary)
        self.assertIn('| livebench |', summary)
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
        net.releases.pop('ollama/ollama')   # resolver raises KeyError
        before = (root / 'catalog/installers.json').read_bytes()
        result = up.run(net, root, apply=False, today='2026-10-28')
        self.assertTrue(result['changed'])
        self.assertFalse(result['applied'])
        self.assertEqual((root / 'catalog/installers.json').read_bytes(), before)
        self.assertEqual([r.name for r in result['failures']], ['ollama'])


if __name__ == '__main__':
    unittest.main()
