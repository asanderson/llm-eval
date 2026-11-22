"""Offline tests for scripts/model_pins.py: the pin file, the checks on a fixture tree, the network layer and the workflow.

The scripted Hugging Face is derived from whatever catalog/model-artifacts.json and catalog/models.json hold today, so
the tests hold on a bump pull request (and in the nightly workflow right after --apply), not only on the pins they were
written against.
"""
import ast
import contextlib
import copy
import datetime as dt
import email.message
import http.client
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import sys
import tempfile
import unittest
from unittest import mock
import urllib.error
import urllib.request
import urllib.response

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location('model_pins', ROOT / 'scripts' / 'model_pins.py')
mp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mp)

# The script never imports the harness; this test does, to check the download manifest with the harness's own validator.
if importlib.util.find_spec('llm_eval') is None:      # the nightly job runs this file with a bare python3
    sys.path.insert(0, str(ROOT / 'src'))
from llm_eval.model_download import validate_download_spec  # noqa: E402

PINS_PATH = ROOT / 'catalog' / 'model-artifacts.json'
PINS = json.loads(PINS_PATH.read_text(encoding='utf-8'))
ARTIFACTS = PINS['artifacts']
MODELS = json.loads((ROOT / 'catalog' / 'models.json').read_text(encoding='utf-8'))['models']
CATALOG = {m['id']: m for m in MODELS}
DISCOVERY = json.loads((ROOT / 'catalog' / 'model-discovery.json').read_text(encoding='utf-8'))
FIRST, SECOND = ARTIFACTS[0], ARTIFACTS[1]
ORG = FIRST['base_model'].split('/')[0]
SINCE = dt.date.fromisoformat(PINS['new_models_since'])
# A run date no real check will stamp, so `checked_on` shows whether a run wrote it.
TODAY = '2099-06-15'
NEW, NEWER_STILL, ELSEWHERE = 'a' * 40, 'b' * 40, 'c' * 40      # commits no repository pins
OLDER_RUN, NEWER_RUN = '2026-11-08T03:53:31.395544+00:00', '2026-11-17T08:03:18.123456+00:00'


def day(offset):
    """The date `offset` days after new_models_since, as Hugging Face spells createdAt."""
    return (SINCE + dt.timedelta(days=offset)).isoformat() + 'T08:00:00.000Z'


def name(entry, kind='artifact'):
    return f"`{entry['model_id']}` {kind}"


def lfs_file(path, size, sha256):
    return {'type': 'file', 'oid': 'f' * 40, 'size': size, 'lfs': {'oid': sha256, 'size': size, 'pointerSize': 136}, 'path': path}


def tree_listing(files):
    """A tree answer in the shape Hugging Face serves: a directory, plain files and the given files in Git LFS."""
    return ([{'type': 'directory', 'oid': 'd' * 40, 'size': 0, 'path': 'another-precision'},
             {'type': 'file', 'oid': 'e' * 40, 'size': 3899, 'path': '.gitattributes'},
             {'type': 'file', 'oid': 'e' * 40, 'size': 15894, 'path': 'README.md'}]
            + [lfs_file(f['path'], f['bytes'], f['sha256']) for f in files])


def offload_job(model_id, repo, revision, model_file, suffix=' (tokenizer embedded in locked GGUF)'):
    """One job of a published model-offloading bundle, reduced to the fields the reader uses and a few it ignores."""
    return {'case_id': model_id + '-ollama', 'mode': 'category-smoke',
            'parameters': {'config': {'model_id': model_id, 'platform': 'ollama', 'backend_version': '0.0.0',
                                      'tokenizer_revision': f'{repo}@{revision}{suffix}', 'launch': {'model_file': model_file}},
                           'server_mode': 'external'}}


def bundle(root, folder, created, jobs, experiment='model-offloading', manifest=None):
    path = root / 'docs/results' / experiment / folder
    path.mkdir(parents=True)
    (path / 'manifest.json').write_text(json.dumps({'schema_version': 2, 'experiment_id': experiment, 'created_utc': created,
                                                    **(manifest or {})}), encoding='utf-8')
    (path / 'resolved-config.json').write_text(json.dumps({'experiment': {}, 'jobs': jobs, 'input_hashes': {}}), encoding='utf-8')
    return path


def pins_of(root):
    return json.loads((root / 'catalog/model-artifacts.json').read_text(encoding='utf-8'))


def by_name(result):
    return {r.name: r for r in result['rows']}


class FakeNet:
    """Scripted Hugging Face derived from the pins and the catalog: every repository starts at its pinned commit."""

    def __init__(self, pins=PINS):
        self.heads, self.trees, self.listings, self.errors, self.asked = {}, {}, {}, {}, []
        for entry in pins['artifacts']:
            self.heads[entry['source_repo']] = entry['source_revision']
            if entry['model_id'] in CATALOG:
                self.heads[CATALOG[entry['model_id']]['upstream_repo']] = CATALOG[entry['model_id']]['source_revision']

    def revision(self, repo):
        self.asked.append(('revision', repo))
        if repo in self.errors:
            raise self.errors[repo]
        if repo not in self.heads:
            raise mp.HttpStatus(404, f'https://huggingface.co/api/models/{repo}/revision/main')
        return {'id': repo, 'sha': self.heads[repo], 'private': False}

    def tree(self, repo, revision):
        self.asked.append(('tree', repo, revision))
        return self.trees[(repo, revision)]

    def newest_models(self, org, limit):
        self.asked.append(('newest', org, limit))
        if org in self.errors:
            raise self.errors[org]
        return self.listings.get(org, [])

    def move(self, entry, head=NEW, files=None):
        """The artifact repository of `entry` gets a new head commit that publishes `files` (default: the pinned ones)."""
        self.heads[entry['source_repo']] = head
        self.trees[(entry['source_repo'], head)] = tree_listing(entry['files'] if files is None else files)


class Base(unittest.TestCase):
    def fixture(self, edit=None, decisions=(), bundles=True):
        """A repository root in a temporary directory: the real catalog/models.json, the pin file (after `edit`), the
        discovery file with the given decisions, and a small published results tree. Removed after the test."""
        tmp = tempfile.TemporaryDirectory(prefix='model-pins-')
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / 'catalog').mkdir()
        shutil.copyfile(ROOT / 'catalog/models.json', root / 'catalog/models.json')
        shutil.copyfile(PINS_PATH, root / 'catalog/model-artifacts.json')
        if edit:
            pins = copy.deepcopy(PINS)
            edit(pins)
            (root / 'catalog/model-artifacts.json').write_bytes((json.dumps(pins, indent=2) + '\n').encode('utf-8'))
        (root / 'catalog/model-discovery.json').write_text(json.dumps({**DISCOVERY, 'decisions': list(decisions)}), encoding='utf-8')
        if bundles:
            # FIRST was measured twice, last at its pinned revision; SECOND once, at its pinned revision.
            bundle(root, 'campaign-older', OLDER_RUN,
                   [offload_job(FIRST['model_id'], FIRST['source_repo'], ELSEWHERE, FIRST['files'][0]['path'])])
            bundle(root, 'campaign-newer', NEWER_RUN,
                   [offload_job(e['model_id'], e['source_repo'], e['source_revision'], e['files'][0]['path']) for e in (FIRST, SECOND)])
        return root

    def run_check(self, root, net=None, apply=True):
        return mp.run(net if net is not None else FakeNet(pins_of(root)), root, apply, TODAY)


# --- the tracked pin file -------------------------------------------------------------------------------
class RealPinFileTest(unittest.TestCase):
    """catalog/model-artifacts.json as shipped. The nightly job runs this right after --apply, before it opens the pull request."""

    def test_the_file_is_the_serialization_the_check_writes(self):
        data = PINS_PATH.read_bytes()
        self.assertNotIn(b'\r', data)
        self.assertEqual(data.decode('ascii'), json.dumps(PINS, indent=2) + '\n')
        self.assertEqual(list(PINS), ['schema_version', 'checked_on', 'scope', 'new_models_since', 'artifacts'])
        self.assertEqual(PINS['schema_version'], 1)
        for key in ('checked_on', 'new_models_since'):
            self.assertEqual(dt.date.fromisoformat(PINS[key]).isoformat(), PINS[key], key)
        self.assertIn('docs/MODELS.md', PINS['scope'])

    def test_every_pin_names_a_catalog_model_in_catalog_order_with_a_full_revision_and_hashed_files(self):
        ids = [entry['model_id'] for entry in ARTIFACTS]
        self.assertEqual(ids, [m['id'] for m in MODELS if m['id'] in ids])      # catalog ids, catalog order, each once
        self.assertTrue(ids)
        for entry in ARTIFACTS:
            with self.subTest(entry['model_id']):
                self.assertEqual(list(entry), ['model_id', 'base_model', 'source_repo', 'source_revision', 'precision', 'files'])
                # A run refuses a lock whose base model is not the catalog entry's upstream_repo.
                self.assertEqual(entry['base_model'], CATALOG[entry['model_id']]['upstream_repo'])
                self.assertRegex(entry['source_repo'], r'\A[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9_.-]+\Z')
                self.assertRegex(entry['source_revision'], r'\A[0-9a-f]{40}\Z')
                self.assertTrue(entry['precision'] and entry['precision'] == entry['precision'].strip())
                self.assertTrue(entry['files'])
                paths = [f['path'] for f in entry['files']]
                self.assertEqual(len(set(paths)), len(paths))
                for f in entry['files']:
                    self.assertEqual(list(f), ['path', 'bytes', 'sha256'])
                    # An exact relative path: the download manifest passes it as an include pattern.
                    self.assertRegex(f['path'], r'\A[A-Za-z0-9_.-]+(/[A-Za-z0-9_.-]+)*\Z')
                    self.assertNotIn('..', f['path'].split('/'))
                    self.assertTrue(isinstance(f['bytes'], int) and not isinstance(f['bytes'], bool) and f['bytes'] > 0)
                    self.assertRegex(f['sha256'], r'\A[0-9a-f]{64}\Z')

    def test_the_published_results_of_this_checkout_are_readable(self):
        measured = mp.published_use(ROOT)
        for model, (created, repo, revision, model_file) in measured.items():
            with self.subTest(model):
                self.assertRegex(created, r'\A\d{4}-\d{2}-\d{2}T')
                self.assertRegex(repo, r'\A[\w.-]+/[\w.-]+\Z')
                self.assertRegex(revision, r'\A[0-9a-f]{40}\Z')
                self.assertIsInstance(model_file, str)
        if any((ROOT / mp.PUBLISHED).glob('*/resolved-config.json')):
            self.assertTrue(measured)


# --- pure rules -------------------------------------------------------------------------------------------
class RulesTest(Base):
    def test_md_code_renders_nothing_of_what_it_is_given(self):
        self.assertEqual(mp.md_code('org/name'), '`org/name`')
        self.assertEqual(mp.md_code('a|b'), '`a\\|b`')
        self.assertEqual(mp.md_code('a`b\r\nc\td'), '`abc d`')
        self.assertEqual(mp.md_code('  '), '`(empty)`')
        self.assertEqual(mp.md_code(None), '`None`')
        self.assertEqual(mp.md_code('x​y\x07z'), '`xyz`')      # format and control characters are dropped
        capped = mp.md_code('x' * 500)
        self.assertEqual(len(capped), mp.STRING_CAP + 2)
        self.assertTrue(capped.endswith('…`'))
        self.assertEqual(len(mp.md_code('x' * 500, mp.EXCERPT_CAP)), mp.EXCERPT_CAP + 2)

    def test_tables_show_twelve_characters_of_a_full_commit(self):
        self.assertEqual(mp.short('0123456789abcdef' * 2 + '01234567'), '0123456789ab')
        self.assertEqual(mp.short('main'), 'main')
        self.assertEqual(mp.short(None), 'None')

    def test_a_revision_answer_must_name_a_full_lowercase_commit(self):
        self.assertEqual(mp.head_sha({'id': 'a/b', 'sha': NEW}), NEW)
        for doc in ({'sha': 'A' * 40}, {'sha': 'a' * 39}, {'sha': 'a' * 40 + '\n'}, {'sha': 'main'}, {'sha': None}, {}, [], None,
                    {'sha': 'a' * 41}):
            with self.subTest(doc=doc), self.assertRaises(mp.UpstreamError):
                mp.head_sha(doc)

    def test_a_tree_listing_gives_size_and_lfs_sha256_per_file(self):
        listing = tree_listing([{'path': 'dir/model-00001-of-00002.gguf', 'bytes': 7, 'sha256': '1' * 64}])
        files = mp.tree_files(listing)
        self.assertEqual(sorted(files), ['.gitattributes', 'README.md', 'dir/model-00001-of-00002.gguf'])      # no directory
        self.assertEqual(mp.file_identity(files['dir/model-00001-of-00002.gguf']), (7, '1' * 64))
        self.assertEqual(mp.file_identity(files['README.md']), (15894, None))      # not in Git LFS: no content hash
        # The LFS object describes the content: its size is the one recorded, whatever the entry's own size says.
        self.assertEqual(mp.file_identity({'type': 'file', 'path': 'x', 'size': 136, 'lfs': {'oid': '2' * 64, 'size': 9}}), (9, '2' * 64))
        for entries in (None, {}, 'x', [None], ['x'], [{'path': 'x'}], [{'type': 'file'}], [{'type': 'file', 'path': 7}]):
            with self.subTest(entries=entries), self.assertRaises(mp.UpstreamError):
                mp.tree_files(entries)
        for entry in ({'path': 'x', 'size': 1, 'lfs': {'oid': 'A' * 64, 'size': 1}}, {'path': 'x', 'size': 1, 'lfs': {'oid': '1' * 63, 'size': 1}},
                      {'path': 'x', 'size': 1, 'lfs': {'oid': 5, 'size': 1}}, {'path': 'x', 'lfs': {'oid': '1' * 64, 'size': '9'}},
                      {'path': 'x', 'lfs': {'oid': '1' * 64, 'size': True}}, {'path': 'x', 'lfs': {'oid': '1' * 64, 'size': -1}},
                      {'path': 'x', 'lfs': {'oid': '1' * 64}}, {'path': 'x'}, {'path': 'x', 'size': 1.5}):
            with self.subTest(entry=entry), self.assertRaises(mp.UpstreamError):
                mp.file_identity(entry)

    def test_an_org_listing_gives_repository_and_creation_date(self):
        entries = [{'id': 'nvidia/New-9B', 'createdAt': '2026-12-01T10:11:12.000Z', 'likes': 3},
                   {'id': 'NVIDIA/Other', 'createdAt': '2026-11-30T00:00:00.000Z'},
                   {'id': 'someone-else/New-9B', 'createdAt': '2026-12-02T00:00:00.000Z'}]
        self.assertEqual(mp.listed_models(entries, 'nvidia'), [('nvidia/New-9B', '2026-12-01'), ('NVIDIA/Other', '2026-11-30')])
        self.assertEqual(mp.listed_models([], 'nvidia'), [])
        for bad in (None, {}, [None], [{'createdAt': '2026-12-01'}], [{'id': 'no-slash', 'createdAt': '2026-12-01'}],
                    [{'id': 'nvidia/x y', 'createdAt': '2026-12-01'}], [{'id': 'nvidia/x\n', 'createdAt': '2026-12-01'}],
                    [{'id': 'nvidia/x'}], [{'id': 'nvidia/x', 'createdAt': 'yesterday'}], [{'id': 'nvidia/x', 'createdAt': 20261201}]):
            with self.subTest(bad=bad), self.assertRaises(mp.UpstreamError):
                mp.listed_models(bad, 'nvidia')

    def test_hf_decisions_match_as_the_discovery_script_documents(self):
        decisions = mp.hf_decisions({'decisions': [
            {'key': 'lb:qwen4-80b', 'decision': 'rejected'},
            {'key': 'hf:Qwen/Qwen4-80B', 'decision': 'rejected'},
            {'key': 'hf:Qwen/Qwen4-*', 'decision': 'deferred', 'until': '2027-01-31'},
            {'key': 'hf:Qwen/Qwen4-Coder*', 'decision': 'rejected'},
            {'key': 5}, 'not an object']})
        self.assertEqual([d['key'] for d in decisions], ['hf:Qwen/Qwen4-80B', 'hf:Qwen/Qwen4-*', 'hf:Qwen/Qwen4-Coder*'])
        key = lambda repo: (mp.decision_for(repo, decisions) or {}).get('key')
        self.assertEqual(key('qwen/QWEN4-80b'), 'hf:Qwen/Qwen4-80B')                    # that repository, case-insensitive
        self.assertEqual(key('Qwen/Qwen4-80B-Instruct'), 'hf:Qwen/Qwen4-*')             # a family: the name starts with the prefix
        self.assertEqual(key('Qwen/Qwen4-Coder-32B'), 'hf:Qwen/Qwen4-Coder*')           # the longest prefix decides
        self.assertIsNone(key('Qwen/Qwen5-80B'))
        self.assertIsNone(key('Other/Qwen4-80B'))                                       # a family never leaves its org
        self.assertIsNone(key('qwen4-80b/x'))                                           # an lb: key names no repository
        self.assertEqual(mp.hf_decisions({}), [])
        self.assertEqual(mp.hf_decisions({'decisions': None}), [])

    def test_the_next_page_of_a_listing_is_the_rel_next_link(self):
        url = 'https://huggingface.co/api/models/a/b/tree/main?recursive=true&cursor=abc%3D'
        self.assertEqual(mp.next_link(f'<{url}>; rel="next"'), url)
        self.assertEqual(mp.next_link(f'<https://huggingface.co/first>; rel="first", <{url}>; rel="next"'), url)
        self.assertIsNone(mp.next_link('<https://huggingface.co/x>; rel="prev"'))
        self.assertIsNone(mp.next_link(None))

    def test_published_use_reads_the_newest_measurement_of_each_model_and_skips_other_shapes(self):
        root = self.fixture(bundles=False)
        self.assertEqual(mp.published_use(root), {})      # no published results at all
        bundle(root, 'campaign-1', OLDER_RUN, [offload_job('model-a', 'org/A-GGUF', NEW, 'a-Q8_0.gguf'),
                                               offload_job('model-b', 'org/B-GGUF', NEW, 'b.gguf')])
        # The walkthroughs spell the text after the revision in two ways; only the prefix is read.
        bundle(root, 'campaign-2', NEWER_RUN, [offload_job('model-a', 'org/A-GGUF', NEWER_STILL, 'sub/a-00001-of-00002.gguf',
                                                           suffix=' (embedded GGUF tokenizer)'),
                                               offload_job('model-a', 'org/A-GGUF', NEWER_STILL, 'sub/a-00001-of-00002.gguf'),
                                               {'case_id': 'no-parameters'}, {'parameters': {'config': {'model_id': 'model-c'}}},
                                               {'parameters': {'config': {'model_id': 'model-d', 'tokenizer_revision': 'REPLACE_WITH_EXACT_REVISION'}}},
                                               {'parameters': {'config': {'model_id': 'model-e', 'tokenizer_revision': 'org/E-GGUF@main (branch)'}}},
                                               {'parameters': {'router': {'model': 'llm-eval-nimble:locked', 'model_revision': '6' * 64}}},
                                               'not a job'])
        # A legal-shaped bundle (projected manifest, identity instead of config), also when it sits in this directory.
        legal_job = {'case_id': 'generation', 'parameters': {'cohorts': ['7' * 64], 'data_class': 'public-synthetic',
                                                             'identity': {'harness': 'ollama', 'model': 'llm-eval-model-a:locked'}}}
        for experiment in ('model-offloading', 'legal-benchmark'):
            bundle(root, 'campaign-legal', '2026-12-31T00:00:00+00:00', [legal_job], experiment=experiment,
                   manifest={'canonical_bytes': 1, 'cohorts': 2, 'projection': {}})
        # Bundles the reader cannot date or parse are skipped, never fatal.
        (bundle(root, 'campaign-undated', NEWER_RUN, [offload_job('model-f', 'org/F-GGUF', NEW, 'f.gguf')]) / 'manifest.json').unlink()
        (bundle(root, 'campaign-broken', NEWER_RUN, []) / 'resolved-config.json').write_text('{not json', encoding='utf-8')
        bundle(root, 'campaign-odd', NEWER_RUN, {'jobs': 'are not a list'})
        bundle(root, 'campaign-odd-date', 'last week', [offload_job('model-g', 'org/G-GUFF', NEW, 'g.gguf')])
        bundle(root, 'campaign-routing', '2026-12-31T00:00:00+00:00', [offload_job('model-h', 'org/H-GGUF', NEW, 'h.gguf')],
               experiment='llm-routing')
        self.assertEqual(mp.published_use(root), {'model-a': (NEWER_RUN, 'org/A-GGUF', NEWER_STILL, 'sub/a-00001-of-00002.gguf'),
                                                  'model-b': (OLDER_RUN, 'org/B-GGUF', NEW, 'b.gguf')})


# --- the checks on a fixture repository ---------------------------------------------------------------------
class CheckTest(Base):
    def test_nothing_newer_leaves_every_file_alone(self):
        root = self.fixture()
        before = {p: p.read_bytes() for p in root.rglob('*') if p.is_file()}
        net = FakeNet()
        result = self.run_check(root, net)
        self.assertEqual({p: p.read_bytes() for p in root.rglob('*') if p.is_file()}, before)      # checked_on included
        self.assertFalse(result['changed'] or result['applied'])
        self.assertEqual((result['touched'], result['manual'], result['failures'], result['moved']), ([], [], [], []))
        self.assertTrue(all(r.status == 'current' for r in result['rows']), [(r.name, r.status, r.detail) for r in result['rows']])
        # The fixed row order: every artifact pin, then every publisher snapshot, each in the order of the pin file.
        self.assertEqual([r.name for r in result['rows']],
                         [name(e) for e in ARTIFACTS] + [name(e, 'publisher snapshot') for e in ARTIFACTS])
        rows = by_name(result)
        first = rows[name(FIRST)]
        self.assertEqual((first.pinned, first.latest, first.policy), (FIRST['source_revision'][:12], FIRST['source_revision'][:12], 'bump'))
        snapshot = rows[name(FIRST, 'publisher snapshot')]
        revision = CATALOG[FIRST['model_id']]['source_revision']
        self.assertEqual((snapshot.pinned, snapshot.latest, snapshot.policy, snapshot.detail), (revision[:12], revision[:12], 'report', ''))
        # One revision lookup per artifact repository and per publisher repository, one listing per publisher org.
        orgs = list(dict.fromkeys(e['base_model'].split('/')[0] for e in ARTIFACTS))
        self.assertEqual(net.asked, [('revision', e['source_repo']) for e in ARTIFACTS]
                         + [('revision', e['base_model']) for e in ARTIFACTS] + [('newest', org, 50) for org in orgs])

    def test_a_moved_repository_with_unchanged_files_is_bumped(self):
        root = self.fixture()
        net = FakeNet()
        net.move(FIRST)
        result = self.run_check(root, net)
        self.assertTrue(result['changed'] and result['applied'])
        self.assertEqual(result['touched'], ['catalog/model-artifacts.json'])
        row = by_name(result)[name(FIRST)]
        self.assertEqual((row.status, row.changed, row.pinned, row.latest), ('bump', True, FIRST['source_revision'][:12], NEW[:12]))
        self.assertTrue(row.detail.startswith('repository moved; pinned files unchanged'), row.detail)
        self.assertEqual(result['moved'], [row])
        self.assertEqual((result['manual'], result['failures']), ([], []))
        written = pins_of(root)
        self.assertEqual(written['artifacts'][0], {**FIRST, 'source_revision': NEW})      # sizes and hashes as they were
        self.assertEqual(written['artifacts'][1:], ARTIFACTS[1:])
        self.assertEqual({k: v for k, v in written.items() if k not in ('artifacts', 'checked_on')},
                         {k: v for k, v in PINS.items() if k not in ('artifacts', 'checked_on')})
        self.assertEqual(net.asked[1], ('tree', FIRST['source_repo'], NEW))      # the files are read at the new commit

    def test_changed_weights_are_bumped_with_their_new_size_and_hash_and_called_a_different_cohort(self):
        def two_files(pins):
            pins['artifacts'][0]['files'] = [{'path': 'split/model-00001-of-00002.gguf', 'bytes': 11, 'sha256': '1' * 64},
                                             {'path': 'split/model-00002-of-00002.gguf', 'bytes': 22, 'sha256': '2' * 64}]
        published = [{'path': 'split/model-00001-of-00002.gguf', 'bytes': 11, 'sha256': '1' * 64},      # this part is unchanged
                     {'path': 'split/model-00002-of-00002.gguf', 'bytes': 23, 'sha256': '3' * 64}]
        for apply in (False, True):
            with self.subTest(apply=apply):
                root = self.fixture(edit=two_files)
                before = (root / 'catalog/model-artifacts.json').read_bytes()
                net = FakeNet(pins_of(root))
                net.move(FIRST, files=published)
                result = self.run_check(root, net, apply=apply)
                row = by_name(result)[name(FIRST)]
                self.assertEqual((row.status, row.changed, row.latest), ('bump', apply, NEW[:12]))
                self.assertTrue(row.detail.startswith('weights changed (`split/model-00002-of-00002.gguf`): results measured with '
                                                      'the pinned revision are a different cohort'), row.detail)
                self.assertTrue(result['changed'])
                self.assertEqual(result['applied'], apply)
                if apply:
                    entry = pins_of(root)['artifacts'][0]
                    self.assertEqual((entry['source_revision'], entry['files']), (NEW, published))
                else:      # report mode: found, not written
                    self.assertEqual((root / 'catalog/model-artifacts.json').read_bytes(), before)
                    self.assertEqual(result['touched'], [])
                    self.assertIn('| bump available |', mp.markdown_summary(result))

    def test_a_pinned_file_that_is_no_longer_published_is_a_manual_decision_and_the_pin_stays(self):
        root = self.fixture()
        before = (root / 'catalog/model-artifacts.json').read_bytes()
        net = FakeNet()
        net.move(FIRST, files=[{'path': 'renamed-' + FIRST['files'][0]['path'], 'bytes': 1, 'sha256': '4' * 64}])
        net.move(SECOND, head=NEWER_STILL)      # another pin moves in the same run and is still written
        result = self.run_check(root, net)
        row = by_name(result)[name(FIRST)]
        self.assertEqual((row.status, row.changed, row.latest), ('manual', False, NEW[:12]))
        self.assertTrue(row.detail.startswith(f"file no longer published at `{NEW[:12]}`: `{FIRST['files'][0]['path']}`"), row.detail)
        self.assertEqual(result['manual'], [row])
        written = pins_of(root)
        self.assertEqual(written['artifacts'][0], FIRST)
        self.assertEqual(written['artifacts'][1]['source_revision'], NEWER_STILL)
        self.assertNotEqual((root / 'catalog/model-artifacts.json').read_bytes(), before)

    def test_a_file_without_an_lfs_sha256_cannot_be_verified_and_is_a_manual_decision(self):
        root = self.fixture()
        before = (root / 'catalog/model-artifacts.json').read_bytes()
        net = FakeNet()
        net.move(FIRST)
        for entry in net.trees[(FIRST['source_repo'], NEW)]:
            if entry['path'] == FIRST['files'][0]['path']:
                del entry['lfs']      # published as a plain Git file: the listing carries no content hash
        result = self.run_check(root, net)
        row = by_name(result)[name(FIRST)]
        self.assertEqual((row.status, row.changed), ('manual', False))
        self.assertTrue(row.detail.startswith(f"no Git LFS sha256 at `{NEW[:12]}` for `{FIRST['files'][0]['path']}`: "
                                              'the content cannot be verified'), row.detail)
        self.assertFalse(result['changed'])
        self.assertEqual((root / 'catalog/model-artifacts.json').read_bytes(), before)

    def test_the_artifact_row_says_whether_the_pin_is_the_last_measured_revision(self):
        root = self.fixture()
        rows = by_name(self.run_check(root))
        measured = f"last measured: `{FIRST['source_revision'][:12]}` on {NEWER_RUN[:10]} "
        self.assertEqual(rows[name(FIRST)].detail, measured + '(the pinned revision)')
        self.assertEqual(rows[name(ARTIFACTS[2])].detail, '')      # pinned, never published: fine, and no row for it
        self.assertFalse(any(r.name.endswith('published use') for r in rows.values()))

        def repinned(pins):      # the pin moved on an earlier night; the published results still hold the old revision
            pins['artifacts'][0]['source_revision'] = NEW
            pins['artifacts'][1]['source_repo'] = 'someone/Other-GGUF'
        root = self.fixture(edit=repinned)
        net = FakeNet(pins_of(root))
        rows = by_name(self.run_check(root, net))
        self.assertEqual((rows[name(FIRST)].status, rows[name(FIRST)].detail), ('current', measured + '(not the pinned revision)'))
        self.assertEqual(rows[name(SECOND)].detail, f"last measured: `{SECOND['source_revision'][:12]}` on {NEWER_RUN[:10]} "
                                                    f"(in `{SECOND['source_repo']}`, not the pinned repository)")
        # A bump keeps the note about the pin it replaces.
        root = self.fixture()
        net = FakeNet()
        net.move(FIRST)
        row = by_name(self.run_check(root, net))[name(FIRST)]
        self.assertEqual(row.detail, 'repository moved; pinned files unchanged; ' + measured + '(the pinned revision)')

    def test_a_measured_model_without_a_pin_is_a_manual_decision(self):
        def unpin_first(pins):
            del pins['artifacts'][0]
        root = self.fixture(edit=unpin_first)
        result = self.run_check(root)
        row = by_name(result)[name(FIRST, 'published use')]
        self.assertEqual((row.status, row.policy, row.pinned, row.latest), ('manual', 'report', 'not pinned', FIRST['source_revision'][:12]))
        self.assertEqual(row.detail, f"measured in published results but not pinned (repository `{FIRST['source_repo']}`, "
                                     f"file `{FIRST['files'][0]['path']}`, last measured on {NEWER_RUN[:10]})")
        self.assertEqual(result['manual'], [row])
        self.assertFalse(result['changed'])
        # Its place in the order: after the artifact pins, before the publisher snapshots.
        names = [r.name for r in result['rows']]
        self.assertEqual(names.index(row.name), len(ARTIFACTS) - 1)
        self.assertNotIn(name(FIRST), names)
        self.assertNotIn(name(FIRST, 'publisher snapshot'), names)      # publisher snapshots are followed for pinned models

    def test_a_moved_publisher_repository_is_reported_and_the_catalog_is_never_rewritten(self):
        root = self.fixture()
        before = {p: p.read_bytes() for p in root.rglob('*') if p.is_file()}
        net = FakeNet()
        net.heads[FIRST['base_model']] = NEW
        result = self.run_check(root, net)
        row = by_name(result)[name(FIRST, 'publisher snapshot')]
        self.assertEqual((row.status, row.changed, row.policy), ('manual', False, 'report'))
        self.assertEqual((row.pinned, row.latest), (CATALOG[FIRST['model_id']]['source_revision'][:12], NEW[:12]))
        self.assertEqual(row.detail, 'publisher repository moved; the catalog pin is reviewed by hand '
                                     '(docs/MODELS.md, upstream_metadata, discovery anchors)')
        self.assertEqual(result['manual'], [row])
        self.assertFalse(result['changed'])
        self.assertEqual({p: p.read_bytes() for p in root.rglob('*') if p.is_file()}, before)

    def test_a_base_model_that_is_not_the_catalog_upstream_repo_is_a_manual_decision(self):
        def other_base(pins):
            pins['artifacts'][0]['base_model'] = 'someone/Another-Model'
            pins['artifacts'][1]['model_id'] = 'not-a-catalog-id'
        root = self.fixture(edit=other_base)
        net = FakeNet(pins_of(root))
        result = self.run_check(root, net)
        rows = by_name(result)
        row = rows[name(FIRST, 'base model')]
        self.assertEqual((row.status, row.pinned, row.latest), ('manual', 'someone/Another-Model', CATALOG[FIRST['model_id']]['upstream_repo']))
        self.assertEqual(row.detail, 'base_model is not the catalog upstream_repo; a run would refuse the lock')
        # The catalog's own repository is still followed for that model.
        self.assertEqual(rows[name(FIRST, 'publisher snapshot')].status, 'current')
        self.assertIn(('revision', CATALOG[FIRST['model_id']]['upstream_repo']), net.asked)
        unknown = rows['`not-a-catalog-id` base model']
        self.assertEqual((unknown.status, unknown.latest), ('manual', 'not in the catalog'))
        self.assertIn('catalog/models.json does not have', unknown.detail)
        self.assertNotIn('`not-a-catalog-id` publisher snapshot', rows)
        # The renamed pin also leaves the model that the published results measured without one.
        self.assertEqual([r.name for r in result['manual']], [name(SECOND, 'published use'), row.name, unknown.name])
        self.assertEqual(result['failures'], [])

    def test_a_repository_hugging_face_does_not_serve_is_a_manual_decision_and_other_statuses_are_failures(self):
        for code in mp.GONE_STATUSES:
            with self.subTest(code=code):
                root = self.fixture()
                before = (root / 'catalog/model-artifacts.json').read_bytes()
                net = FakeNet()
                net.errors[FIRST['source_repo']] = mp.HttpStatus(code, 'https://huggingface.co/api/models/x/y/revision/main')
                net.errors[SECOND['base_model']] = mp.HttpStatus(code, 'https://huggingface.co/api/models/x/y/revision/main')
                result = self.run_check(root, net)
                rows = by_name(result)
                for row in (rows[name(FIRST)], rows[name(SECOND, 'publisher snapshot')]):
                    self.assertEqual((row.status, row.latest), ('manual', f'HTTP {code}'))
                    self.assertIn('does not serve the repository', row.detail)
                self.assertIn('last measured', rows[name(FIRST)].detail)
                self.assertEqual(result['failures'], [])
                self.assertEqual((root / 'catalog/model-artifacts.json').read_bytes(), before)
        self.assertEqual(mp.GONE_STATUSES, (401, 403, 404, 410))
        for code in (400, 429, 500):
            with self.subTest(code=code):
                net = FakeNet()
                net.errors[FIRST['source_repo']] = mp.HttpStatus(code, 'https://huggingface.co/api/models/x/y/revision/main')
                result = self.run_check(self.fixture(), net)
                self.assertEqual([r.name for r in result['failures']], [name(FIRST)])
                self.assertEqual(result['manual'], [])

    def test_a_failed_lookup_is_a_row_and_the_rows_that_resolved_are_still_written(self):
        root = self.fixture()
        net = FakeNet()
        net.errors[FIRST['source_repo']] = mp.UpstreamError('huggingface.co/api/models/x/y/revision/main: HTTP 503 after 5 attempts')
        net.errors[SECOND['base_model']] = KeyError('sha')      # any exception is a row, never a crash
        net.errors[ORG] = TimeoutError('timed out')
        net.move(SECOND)
        result = self.run_check(root, net)
        rows = by_name(result)
        self.assertEqual([r.name for r in result['failures']], [name(FIRST), name(SECOND, 'publisher snapshot'), f'new models from `{ORG}`'])
        self.assertEqual((rows[name(FIRST)].latest, rows[name(FIRST)].detail),
                         (None, '`huggingface.co/api/models/x/y/revision/main: HTTP 503 after 5 attempts`'))
        self.assertEqual(rows[name(SECOND, 'publisher snapshot')].detail, "`KeyError: 'sha'`")
        self.assertEqual(rows[f'new models from `{ORG}`'].detail, '`TimeoutError: timed out`')
        self.assertEqual(sum(r.status == 'failed' for r in result['rows']), 3)      # every other row resolved
        self.assertEqual(sum(r.status == 'current' for r in result['rows']), 2 * len(ARTIFACTS) - 3)
        self.assertTrue(result['applied'])
        written = pins_of(root)
        self.assertEqual(written['artifacts'][0], FIRST)                             # the failed pin stays
        self.assertEqual(written['artifacts'][1]['source_revision'], NEW)            # the resolved bump is written
        summary = mp.markdown_summary(result)
        self.assertIn(f'| {name(FIRST)} | `{FIRST["source_revision"][:12]}` | `?` | failed | ', summary)
        self.assertIn('### Failed lookups', summary)
        self.assertIn('this run does not close the tracking issue', summary)
        self.assertIn('### Failed lookups', mp.markdown_summary(result, issue=True))

    def test_a_tree_that_cannot_be_read_fails_the_row_and_leaves_the_entry_whole(self):
        def two_files(pins):
            pins['artifacts'][0]['files'].append({'path': 'second.gguf', 'bytes': 5, 'sha256': '5' * 64})
        for broken in ('no tree', 'bad oid', 'bad size'):
            with self.subTest(broken=broken):
                root = self.fixture(edit=two_files)
                before = (root / 'catalog/model-artifacts.json').read_bytes()
                net = FakeNet(pins_of(root))
                net.move(FIRST, files=[FIRST['files'][0], {'path': 'second.gguf', 'bytes': 6, 'sha256': '6' * 64}])
                tree = net.trees[(FIRST['source_repo'], NEW)]
                if broken == 'no tree':
                    del net.trees[(FIRST['source_repo'], NEW)]
                elif broken == 'bad oid':
                    tree[-1]['lfs']['oid'] = 'not a sha256'
                else:
                    tree[-1]['lfs']['size'] = '6'
                result = self.run_check(root, net)
                self.assertEqual([r.name for r in result['failures']], [name(FIRST)])
                # The first file resolved, the second did not: nothing of the entry moved.
                self.assertFalse(result['changed'])
                self.assertEqual((root / 'catalog/model-artifacts.json').read_bytes(), before)

    def test_new_models_honour_the_catalog_recorded_decisions_and_new_models_since(self):
        in_catalog = [m['upstream_repo'] for m in MODELS if m['upstream_repo'].split('/')[0].casefold() == ORG.casefold()]
        decisions = [{'key': f'hf:{ORG}/Decided-9B', 'decision': 'rejected', 'reason': 'x', 'decided_on': '2026-11-22'},
                     {'key': f'hf:{ORG}/Family-*', 'decision': 'rejected', 'reason': 'x', 'decided_on': '2026-11-22'},
                     {'key': f'hf:{ORG}/Waiting-9B', 'decision': 'deferred', 'until': TODAY, 'reason': 'x', 'decided_on': '2026-11-22'},
                     {'key': f'hf:{ORG}/Overdue-9B', 'decision': 'deferred', 'until': '2099-06-14', 'reason': 'x', 'decided_on': '2026-11-22'},
                     {'key': f'lb:{ORG}/Brand-New-9B'.lower(), 'decision': 'rejected', 'reason': 'x', 'decided_on': '2026-11-22'}]
        listing = ([{'id': f'{ORG}/Brand-New-9B', 'createdAt': day(9)},
                    {'id': f'{ORG}/On-The-Day-9B', 'createdAt': day(0)},
                    {'id': f'{ORG}/Day-Before-9B', 'createdAt': day(-1)},
                    {'id': f'{ORG}/DECIDED-9b', 'createdAt': day(8)},
                    {'id': f'{ORG}/Family-9B-Instruct', 'createdAt': day(7)},
                    {'id': f'{ORG}/Waiting-9B', 'createdAt': day(6)},
                    {'id': f'{ORG}/Overdue-9B', 'createdAt': day(5)},
                    {'id': 'someone-else/Brand-New-9B', 'createdAt': day(9)}]
                   + [{'id': repo.swapcase(), 'createdAt': day(4)} for repo in in_catalog])
        root = self.fixture(decisions=decisions)
        before = {p: p.read_bytes() for p in root.rglob('*') if p.is_file()}
        net = FakeNet()
        net.listings[ORG] = listing
        result = self.run_check(root, net)
        new = [r for r in result['rows'] if r.name.startswith('new model')]
        self.assertEqual([(r.name, r.status, r.policy, r.pinned, r.latest, r.detail) for r in new], [
            (f'new model `{ORG}/Brand-New-9B`', 'manual', 'report', 'none', day(9)[:10],
             f'created {day(9)[:10]}; not in the catalog and no recorded decision'),
            (f'new model `{ORG}/On-The-Day-9B`', 'manual', 'report', 'none', day(0)[:10],
             f'created {day(0)[:10]}; not in the catalog and no recorded decision'),
            (f'new model `{ORG}/Overdue-9B`', 'manual', 'report', 'none', day(5)[:10],
             f'created {day(5)[:10]}; not in the catalog; its recorded deferral ended on `2099-06-14`')])
        self.assertEqual((result['manual'], result['new_models'], result['failures']), (new, new, []))
        self.assertEqual(result['rows'][-3:], new)      # after every artifact and publisher row
        self.assertFalse(result['changed'])
        self.assertEqual({p: p.read_bytes() for p in root.rglob('*') if p.is_file()}, before)
        summary = mp.markdown_summary(result, issue=True)
        self.assertIn('`new_models_since` in `catalog/model-artifacts.json` is moved past its creation date', summary)
        self.assertIn('"LiveBench models needing a catalog decision"', summary)      # the issue that judges size and license
        self.assertIn('docs/MODEL_DISCOVERY.md', summary)

    def test_a_full_listing_that_never_reaches_new_models_since_says_that_older_repositories_were_not_read(self):
        root = self.fixture()
        net = FakeNet()
        net.listings[ORG] = [{'id': f'{ORG}/Recent-{i}', 'createdAt': day(60 - i)} for i in range(mp.NEW_MODELS_LIMIT)]
        result = self.run_check(root, net)
        row = result['rows'][-1]
        self.assertEqual((row.name, row.status, row.pinned, row.latest), (f'new models from `{ORG}`', 'manual', f"since {PINS['new_models_since']}", '50 listed'))
        self.assertIn('older ones were not read', row.detail)
        self.assertEqual(len(result['new_models']), mp.NEW_MODELS_LIMIT + 1)
        # A full listing whose oldest entry predates the date read everything that matters.
        net.listings[ORG][-1]['createdAt'] = day(-1)
        result = self.run_check(root, net)
        self.assertEqual(len(result['new_models']), mp.NEW_MODELS_LIMIT - 1)
        self.assertFalse(any(r.name.startswith('new models from') for r in result['rows']))
        self.assertEqual(mp.NEW_MODELS_LIMIT, 50)

    def test_new_models_since_must_be_a_date(self):
        def no_date(pins):
            pins['new_models_since'] = 'last week'
        root = self.fixture(edit=no_date)
        net = FakeNet()
        result = self.run_check(root, net)
        self.assertEqual([(r.name, r.status) for r in result['rows'][2 * len(ARTIFACTS):]], [('new models', 'failed')])
        self.assertFalse(any(call[0] == 'newest' for call in net.asked))

    def test_apply_writes_lf_json_that_round_trips_and_stamps_checked_on_only_on_change(self):
        root = self.fixture()
        net = FakeNet()
        net.move(FIRST)
        self.run_check(root, net)
        data = (root / 'catalog/model-artifacts.json').read_bytes()
        self.assertNotIn(b'\r', data)
        self.assertTrue(data.endswith(b'}\n') and not data.endswith(b'\n\n'))
        written = json.loads(data)
        self.assertEqual(data.decode('ascii'), json.dumps(written, indent=2) + '\n')
        self.assertEqual(list(written), list(PINS))
        self.assertEqual(written['checked_on'], TODAY)
        self.assertEqual(written['new_models_since'], PINS['new_models_since'])
        # The same upstream on the next night: the pin is current, and the file, its date included, stays as it is.
        result = mp.run(net, root, True, '2099-06-16')
        self.assertFalse(result['changed'])
        self.assertEqual((root / 'catalog/model-artifacts.json').read_bytes(), data)
        self.assertEqual(by_name(result)[name(FIRST)].status, 'current')

    def test_report_mode_never_writes(self):
        root = self.fixture()
        before = {p: p.read_bytes() for p in root.rglob('*') if p.is_file()}
        net = FakeNet()
        net.move(FIRST)
        net.heads[SECOND['base_model']] = NEW
        result = self.run_check(root, net, apply=False)
        self.assertTrue(result['changed'])
        self.assertFalse(result['applied'])
        self.assertEqual(result['touched'], [])
        self.assertFalse(any(r.changed for r in result['rows']))
        self.assertEqual({p: p.read_bytes() for p in root.rglob('*') if p.is_file()}, before)

    def test_apply_writes_nothing_but_the_pin_file(self):
        root = self.fixture()
        before = {p: p.read_bytes() for p in root.rglob('*') if p.is_file()}
        net = FakeNet()
        for entry in ARTIFACTS:
            net.move(entry)
            net.heads[entry['base_model']] = NEWER_STILL
        net.listings[ORG] = [{'id': f'{ORG}/Brand-New-9B', 'createdAt': day(1)}]
        result = self.run_check(root, net)
        self.assertEqual(len(result['moved']), len(ARTIFACTS))
        after = {p: p.read_bytes() for p in root.rglob('*') if p.is_file()}
        self.assertEqual(sorted(after), sorted(before))
        self.assertEqual([p.relative_to(root).as_posix() for p in before if after[p] != before[p]], ['catalog/model-artifacts.json'])
        self.assertTrue(all(e['source_revision'] == NEW for e in pins_of(root)['artifacts']))


class SummaryTest(Base):
    def moved_and_undecided(self, apply=True):
        root = self.fixture()
        net = FakeNet()
        net.move(FIRST)
        net.heads[SECOND['base_model']] = NEWER_STILL
        net.listings[ORG] = [{'id': f'{ORG}/Brand-New-9B', 'createdAt': day(3)}]
        return self.run_check(root, net, apply=apply)

    def test_the_pull_request_body_states_what_moved_and_what_it_means_for_the_next_run(self):
        summary = mp.markdown_summary(self.moved_and_undecided())
        lines = summary.splitlines()
        self.assertEqual(lines[:4], ['## Model pin check', '', '| Pin | Pinned | Upstream | Status | Detail |', '|---|---|---|---|---|'])
        table = [line for line in lines if line.startswith('| ')][1:]
        self.assertEqual(len(table), 2 * len(ARTIFACTS) + 1)
        self.assertEqual(table[0], f"| {name(FIRST)} | `{FIRST['source_revision'][:12]}` | `{NEW[:12]}` | bumped | repository moved; "
                                   f"pinned files unchanged; last measured: `{FIRST['source_revision'][:12]}` on {NEWER_RUN[:10]} "
                                   '(the pinned revision) |')
        self.assertIn(f"| {name(ARTIFACTS[2])} | `{ARTIFACTS[2]['source_revision'][:12]}` | `{ARTIFACTS[2]['source_revision'][:12]}` | current |  |", table)
        self.assertIn(f"| {name(SECOND, 'publisher snapshot')} | `{CATALOG[SECOND['model_id']]['source_revision'][:12]}` | `{NEWER_STILL[:12]}` "
                      f'| manual | {mp.PUBLISHER_MOVED} |', table)
        self.assertEqual(table[-1], f'| new model `{ORG}/Brand-New-9B` | `none` | `{day(3)[:10]}` | manual | created {day(3)[:10]}; '
                                    'not in the catalog and no recorded decision |')
        for line in table:      # five cells, whatever a cell holds
            self.assertEqual(len(re.findall(r'(?<!\\)\|', line)), 6, line)
        self.assertEqual([line for line in lines if line.startswith('#')],
                         ['## Model pin check', '### What moved and what it means for the next run', '### Needs a manual decision'])
        moved = summary.split('### What moved and what it means for the next run\n', 1)[1].split('\n###', 1)[0]
        self.assertIn(f"- **{name(FIRST)}**: `{FIRST['source_revision'][:12]}` to `{NEW[:12]}`: repository moved; pinned files unchanged", moved)
        # Stated plainly: a new cohort, published results keep their revision, a bound legal role is re-qualified.
        self.assertIn('A changed artifact revision is a new cohort.', moved)
        self.assertIn('Published results keep their recorded revision; nothing under `docs/results/` is rewritten.', moved)
        self.assertIn('must be re-qualified', moved)
        self.assertIn('`python scripts/model_pins.py --download-spec FILE`', moved)
        self.assertIn('Rewritten: `catalog/model-artifacts.json`.', moved)
        decisions = summary.split('### Needs a manual decision\n', 1)[1]
        self.assertIn(f"- **{name(SECOND, 'publisher snapshot')}**: pinned `{CATALOG[SECOND['model_id']]['source_revision'][:12]}`, "
                      f'upstream `{NEWER_STILL[:12]}`: {mp.PUBLISHER_MOVED}', decisions)
        self.assertIn(f'- **new model `{ORG}/Brand-New-9B`**: pinned `none`, upstream `{day(3)[:10]}`: ', decisions)
        self.assertNotIn('Failed lookups', summary)
        self.assertTrue(summary.endswith('\n') and not summary.endswith('\n\n'))
        self.assertNotIn('—', summary)

    def test_the_issue_body_carries_the_same_table_and_decisions_without_the_section_about_the_diff(self):
        result = self.moved_and_undecided()
        summary, issue = mp.markdown_summary(result), mp.markdown_summary(result, issue=True)
        table = lambda text: [line for line in text.splitlines() if line.startswith('|')]
        self.assertEqual(table(issue), table(summary))
        self.assertIn('### Needs a manual decision', issue)
        self.assertEqual(issue.split('### Needs a manual decision', 1)[1], summary.split('### Needs a manual decision', 1)[1])
        self.assertNotIn('What moved', issue)
        self.assertNotIn('Rewritten', issue)

    def test_a_report_run_names_the_bumps_it_did_not_write(self):
        summary = mp.markdown_summary(self.moved_and_undecided(apply=False))
        self.assertIn(f"| {name(FIRST)} | `{FIRST['source_revision'][:12]}` | `{NEW[:12]}` | bump available | ", summary)
        self.assertIn('### What moved and what it means for the next run', summary)
        self.assertNotIn('Rewritten', summary)
        self.assertNotIn('| bumped |', summary)

    def test_a_quiet_run_is_a_table_and_nothing_else(self):
        result = self.run_check(self.fixture())
        for text in (mp.markdown_summary(result), mp.markdown_summary(result, issue=True)):
            self.assertEqual(text.count('\n'), 4 + len(result['rows']))
            self.assertNotIn('###', text)

    def test_a_hostile_repository_id_is_never_rendered(self):
        hostile = f'{ORG}/x`|<img src=x onerror=alert(1)>\n## Injected heading\n| a | b |\n@someone [link](https://example.com)'
        root = self.fixture()
        net = FakeNet()
        net.listings[ORG] = [{'id': f'{ORG}/Brand-New-9B', 'createdAt': day(2)}, {'id': hostile, 'createdAt': day(3)}]
        result = self.run_check(root, net)
        row = result['rows'][-1]
        # The listing is not what this check assumes: no repository of it is reported, and the lookup is a failed row.
        self.assertEqual((row.name, row.status, row.latest), (f'new models from `{ORG}`', 'failed', None))
        self.assertFalse(any(r.name.startswith('new model `') for r in result['rows']))
        # Its text is one code span: no backtick, line break or unescaped pipe inside it.
        self.assertRegex(row.detail, r'\A`[^`\r\n]*`\Z')
        self.assertIn('expected listing entries with an org/name id', row.detail)
        self.assertNotRegex(row.detail, r'(?<!\\)\|')
        self.assertLessEqual(len(row.detail), mp.EXCERPT_CAP + 2 + row.detail.count('\\|'))
        for text in (mp.markdown_summary(result), mp.markdown_summary(result, issue=True)):
            lines = text.splitlines()
            self.assertEqual([line for line in lines if line.startswith('#')], ['## Model pin check', '### Failed lookups'])
            self.assertFalse(any(line.startswith(('| a', '@someone')) for line in lines))
            for line in lines:
                if line.startswith('| '):
                    self.assertEqual(len(re.findall(r'(?<!\\)\|', line)), 6, line)
                # Outside the code spans nothing of the id is left.
                self.assertNotRegex(re.sub(r'`[^`]*`', '', line), r'<img|Injected|example\.com|@someone')

    def test_valid_ids_with_markdown_characters_and_other_upstream_text_stay_inside_code_spans(self):
        root = self.fixture()
        net = FakeNet()
        net.listings[ORG] = [{'id': f'{ORG}/__init__', 'createdAt': day(2)}, {'id': f'{ORG}/www.example.com', 'createdAt': day(2)}]
        net.heads[FIRST['source_repo']] = 'abc`|\n<b>bold</b> | x'      # a revision answer whose sha is not a commit
        net.move(SECOND)
        net.trees[(SECOND['source_repo'], NEW)].append({'type': 'file', 'path': '`|<b>bold</b>\n| x', 'size': 1})      # never printed
        result = self.run_check(root, net)
        rows = by_name(result)
        self.assertEqual(rows[f'new model `{ORG}/__init__`'].status, 'manual')
        self.assertEqual(rows[f'new model `{ORG}/www.example.com`'].status, 'manual')
        self.assertEqual(rows[name(FIRST)].status, 'failed')
        self.assertRegex(rows[name(FIRST)].detail, r'\A`[^`\r\n]*`\Z')
        self.assertEqual(pins_of(root)['artifacts'][0], FIRST)
        self.assertEqual(rows[name(SECOND)].status, 'bump')
        for text in (mp.markdown_summary(result), mp.markdown_summary(result, issue=True)):
            for line in text.splitlines():
                if line.startswith('| '):
                    self.assertEqual(len(re.findall(r'(?<!\\)\|', line)), 6, line)
                self.assertNotRegex(re.sub(r'`[^`]*`', '', line), r'<b>|__init__|www\.example\.com')


# --- the download manifest -------------------------------------------------------------------------------------
class DownloadSpecTest(Base):
    def spec(self, *args, root=ROOT):
        tmp = tempfile.TemporaryDirectory(prefix='model-pins-')
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / 'download.json'
        net = mock.Mock(spec_set=[])      # --download-spec makes no request: any call on this object raises
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = mp.main(['--download-spec', str(path), *args], net=net, root=root)
        return code, path, out.getvalue()

    def test_the_manifest_passes_the_harness_validator_once_the_license_is_accepted(self):
        before = PINS_PATH.read_bytes()
        code, path, out = self.spec()
        self.assertEqual(code, 0)
        self.assertIn(f'{len(ARTIFACTS)} pinned artifact(s) written', out)
        data = path.read_bytes()
        self.assertNotIn(b'\r', data)
        manifest = json.loads(data)
        self.assertEqual(data.decode('ascii'), json.dumps(manifest, indent=2) + '\n')
        example = json.loads((ROOT / 'configs/workflows/download.example.json').read_text(encoding='utf-8'))
        self.assertEqual(list(manifest), list(example))
        self.assertEqual(len(manifest['models']), len(ARTIFACTS))
        for entry, pin in zip(manifest['models'], ARTIFACTS):
            self.assertEqual(list(entry), list(example['models'][0]))      # the shape of download.example.json
            self.assertEqual(entry, {'model_id': pin['model_id'], 'source_repo': pin['source_repo'],
                                     'source_revision': pin['source_revision'], 'precision': pin['precision'],
                                     'include': [f['path'] for f in pin['files']],
                                     'artifact_root': f"models/{pin['model_id']}",
                                     'artifact_lock': f"artifacts/{pin['model_id']}.lock.json", 'accept_license': False})
        # The operator reviews the license first: as written, the harness refuses the manifest.
        with self.assertRaisesRegex(ValueError, 'accept_license=true only after reviewing'):
            validate_download_spec(ROOT, path)
        for entry in manifest['models']:
            entry['accept_license'] = True
        path.write_text(json.dumps(manifest), encoding='utf-8')
        accepted = validate_download_spec(ROOT, path)
        self.assertEqual([e['model_id'] for e in accepted], [pin['model_id'] for pin in ARTIFACTS])
        # The harness binds each download to the catalog's base model, which is the pin's.
        self.assertEqual([e['base_model_repo'] for e in accepted], [pin['base_model'] for pin in ARTIFACTS])
        self.assertEqual(PINS_PATH.read_bytes(), before)

    def test_models_selects_pinned_ids_and_keeps_the_order_of_the_pin_file(self):
        chosen = [ARTIFACTS[-1]['model_id'], FIRST['model_id']]
        code, path, out = self.spec('--models', f' {chosen[0]} , {chosen[1]},')
        self.assertEqual(code, 0)
        manifest = json.loads(path.read_text(encoding='utf-8'))
        self.assertEqual([e['model_id'] for e in manifest['models']], [FIRST['model_id'], ARTIFACTS[-1]['model_id']])
        for entry in manifest['models']:
            entry['accept_license'] = True
        path.write_text(json.dumps(manifest), encoding='utf-8')
        self.assertEqual(len(validate_download_spec(ROOT, path, selected=chosen)), 2)      # as setup passes its --models

    def test_an_unknown_id_or_a_mixed_command_exits_2_with_a_message_and_writes_nothing(self):
        unpinned = next(m['id'] for m in MODELS if m['id'] not in {e['model_id'] for e in ARTIFACTS})
        cases = [(['--download-spec', 'FILE', '--models', f"{FIRST['model_id']},{unpinned},nonsense"],
                  f'no artifact pin in catalog/model-artifacts.json for: {unpinned}, nonsense'),
                 (['--download-spec', 'FILE', '--models', ' , '], '--models names no model id'),
                 (['--download-spec', 'FILE', '--apply'], 'runs no check'),
                 (['--download-spec', 'FILE', '--summary', 'OTHER'], 'runs no check'),
                 (['--models', FIRST['model_id']], '--models needs --download-spec')]
        for argv, message in cases:
            with self.subTest(argv=argv), tempfile.TemporaryDirectory(prefix='model-pins-') as tmp:
                argv = [str(Path(tmp) / a) if a in ('FILE', 'OTHER') else a for a in argv]
                err = io.StringIO()
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err), self.assertRaises(SystemExit) as ctx:
                    mp.main(argv, net=mock.Mock(spec_set=[]), root=ROOT)
                self.assertEqual(ctx.exception.code, 2)
                self.assertIn(message, err.getvalue())
                self.assertEqual(list(Path(tmp).iterdir()), [])


# --- main: outputs the workflow branches on ---------------------------------------------------------------------
class MainTest(Base):
    """The three step outputs: `changed` opens the bump pull request, `manual` refreshes the issue, and the issue closes
    only when `manual` and `failed` are both false."""

    def main(self, net, *flags, env=True):
        root = self.fixture()
        out = root.parent / (root.name + '-github-output.txt')
        self.addCleanup(lambda: out.unlink(missing_ok=True))
        stdout, stderr = io.StringIO(), io.StringIO()
        environ = {'GITHUB_OUTPUT': str(out)} if env else {}
        with mock.patch.dict(os.environ, environ), contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            if not env:
                os.environ.pop('GITHUB_OUTPUT', None)
            code = mp.main(['--github-output', *flags], net=net, root=root, today=TODAY)
        outputs = dict(line.split('=', 1) for line in out.read_text(encoding='utf-8').split()) if out.exists() else None
        return code, outputs, stdout.getvalue(), stderr.getvalue(), root

    def moved(self):
        net = FakeNet()
        net.move(FIRST)
        return net

    def test_a_report_run_announces_no_change(self):
        code, outputs, stdout, _, root = self.main(self.moved())
        self.assertEqual((code, outputs), (0, {'changed': 'false', 'manual': 'false', 'failed': 'false'}))
        self.assertEqual(pins_of(root), PINS)
        self.assertRegex(stdout, re.escape(name(FIRST)) + r'\s+' + FIRST['source_revision'][:12] + r' -> ' + NEW[:12] + r'\s+bump available')

    def test_an_apply_run_announces_the_change(self):
        code, outputs, stdout, _, root = self.main(self.moved(), '--apply')
        self.assertEqual((code, outputs), (0, {'changed': 'true', 'manual': 'false', 'failed': 'false'}))
        self.assertEqual(pins_of(root)['checked_on'], TODAY)
        self.assertRegex(stdout, re.escape(name(FIRST)) + r'.* bumped  \(repository moved; pinned files unchanged')
        self.assertEqual(len(stdout.splitlines()), 2 * len(ARTIFACTS))

    def test_a_run_with_nothing_to_decide_says_so_and_lets_the_issue_close(self):
        code, outputs, _, stderr, _ = self.main(FakeNet(), '--apply')
        self.assertEqual((code, outputs, stderr), (0, {'changed': 'false', 'manual': 'false', 'failed': 'false'}, ''))

    def test_an_open_decision_is_announced_with_and_without_apply(self):
        for flags in ((), ('--apply',)):
            net = FakeNet()
            net.heads[FIRST['base_model']] = NEW
            code, outputs, _, _, _ = self.main(net, *flags)
            self.assertEqual((code, outputs), (0, {'changed': 'false', 'manual': 'true', 'failed': 'false'}))

    def test_a_failed_lookup_is_announced_so_the_issue_is_not_closed_on_a_guess(self):
        net = FakeNet()
        net.errors[FIRST['source_repo']] = mp.UpstreamError('down')
        code, outputs, _, stderr, _ = self.main(net, '--apply')
        self.assertEqual((code, outputs), (0, {'changed': 'false', 'manual': 'false', 'failed': 'true'}))
        self.assertEqual(stderr, '1 lookup(s) failed\n')
        code, outputs, _, _, _ = self.main(net, '--apply', '--strict')
        self.assertEqual((code, outputs), (1, {'changed': 'false', 'manual': 'false', 'failed': 'true'}))
        self.assertEqual(self.main(FakeNet(), '--strict')[0], 0)

    def test_the_bodies_are_written_with_lf_and_nothing_is_written_without_github_output(self):
        root = self.fixture()
        net = self.moved()
        net.heads[SECOND['base_model']] = NEW
        with mock.patch.dict(os.environ), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            os.environ.pop('GITHUB_OUTPUT', None)
            code = mp.main(['--apply', '--summary', str(root / 'summary.md'), '--issue-summary', str(root / 'issue.md'),
                            '--github-output'], net=net, root=root, today=TODAY)
        self.assertEqual(code, 0)
        summary, issue = (root / 'summary.md').read_bytes(), (root / 'issue.md').read_bytes()
        self.assertNotIn(b'\r', summary + issue)
        self.assertIn(b'### What moved and what it means for the next run', summary)
        self.assertNotIn(b'What moved', issue)
        self.assertIn(b'### Needs a manual decision', issue)
        self.assertEqual(sorted(p.name for p in root.iterdir()), ['catalog', 'docs', 'issue.md', 'summary.md'])

    def test_the_default_date_is_the_utc_date(self):
        root = self.fixture()
        with contextlib.redirect_stdout(io.StringIO()):
            mp.main(['--apply'], net=self.moved(), root=root)
        stamped = dt.date.fromisoformat(pins_of(root)['checked_on'])
        self.assertLessEqual(abs((stamped - dt.datetime.now(dt.timezone.utc).date()).days), 1)

    def test_the_script_imports_only_the_standard_library(self):
        tree = ast.parse((ROOT / 'scripts/model_pins.py').read_text(encoding='utf-8'))
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names |= {a.name.split('.')[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom):
                names.add((node.module or '').split('.')[0])
        self.assertNotIn('llm_eval', names)      # the nightly job runs it with a bare python3, without the package
        self.assertTrue(names <= set(sys.stdlib_module_names), names - set(sys.stdlib_module_names))


# --- the network layer ------------------------------------------------------------------------------------------
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


def http_error(url, code, headers=None, body=b'{"error": "nope"}'):
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


class NetTest(unittest.TestCase):
    URL = 'https://huggingface.co/api/models/a/b/revision/main'

    def net(self, *script, env=None):
        net = mp.Net(env=env or {})
        net.opener = FakeOpener(*script)
        net.sleeps = []
        net.sleep = net.sleeps.append
        return net

    def test_constants(self):
        self.assertEqual((mp.ALLOWED_HOSTS, mp.USER_AGENT), (('huggingface.co',), 'llm-eval model_pins'))
        self.assertEqual((mp.RETRIES, mp.RETRY_STATUSES, mp.RETRY_AFTER_CAP, mp.RETRY_STEP, mp.TIMEOUT), (5, (429, 500, 502, 503, 504), 120, 10, 60))
        self.assertEqual((mp.RUN_DEADLINE, mp.MAX_REDIRECTS), (15 * 60, 5))

    def test_only_https_to_hugging_face(self):
        net = self.net()
        for url in ('https://api.github.com/repos/a/b', 'https://livebench.ai/', 'https://example.com/x', 'http://huggingface.co/api/models/a/b',
                    'https://user@huggingface.co/api', 'https://user:secret@huggingface.co/api', 'https://huggingface.co:8443/api',
                    'https://huggingface.co.evil.net/x', 'https://cdn-lfs.huggingface.co/x', 'https://www.huggingface.co/api', 'ftp://huggingface.co/x'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                net.get(url)
        self.assertEqual(net.opener.requests, [])

    def test_the_token_is_sent_only_when_set(self):
        env = {'GITHUB_TOKEN': 'gh-secret', 'HF_TOKEN': 'hf-secret'}      # both are set on an Actions runner
        net = self.net(FakeResponse(b'{"sha": "x"}'), env=env)
        self.assertEqual(net.get(self.URL)[1], {'sha': 'x'})
        (req, timeout), = net.opener.requests
        self.assertEqual(req.get_header('Authorization'), 'Bearer hf-secret')
        self.assertEqual(req.get_header('User-agent'), 'llm-eval model_pins')
        self.assertEqual(req.get_header('Accept'), 'application/json')
        self.assertEqual((req.get_method(), timeout), ('GET', 60))
        self.assertNotIn('gh-secret', repr(vars(net)))      # the GitHub token is not even read
        for env in ({}, {'HF_TOKEN': ''}):
            net = self.net(FakeResponse(), env=env)
            net.get(self.URL)
            self.assertIsNone(net.opener.requests[0][0].get_header('Authorization'))
        with mock.patch.dict(os.environ, {'HF_TOKEN': 'from-the-environment'}):
            self.assertEqual(mp.Net().token, 'from-the-environment')

    def test_redirects_stay_on_the_same_https_host(self):
        handler = mp.SameHostRedirect()
        self.assertEqual(handler.max_redirections, 5)
        req = urllib.request.Request(self.URL, headers={'Authorization': 'Bearer x'})
        same = handler.redirect_request(req, io.BytesIO(), 307, 'moved', email.message.Message(), 'https://huggingface.co/api/models/a/c/revision/main')
        self.assertEqual(same.full_url, 'https://huggingface.co/api/models/a/c/revision/main')
        for target in ('https://cdn-lfs.example.net/a/b', 'http://huggingface.co/api/models/a/c', 'https://huggingface.co.evil.net/x',
                       'https://huggingface.co:8443/api/models/a/c'):
            with self.subTest(target=target), self.assertRaises(mp.UpstreamError) as ctx:
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
        renamed = 'https://huggingface.co/api/models/a/renamed/revision/main'
        upstream = Upstream((307, renamed, b''), (200, None, b'{"id": "a/renamed"}'))
        net = mp.Net(env={'HF_TOKEN': 'hf-secret'})
        net.opener = urllib.request.build_opener(mp.SameHostRedirect, upstream)
        self.assertEqual(net.get(self.URL)[1], {'id': 'a/renamed'})
        self.assertEqual(upstream.seen, [(self.URL, 'Bearer hf-secret'), (renamed, 'Bearer hf-secret')])
        upstream = Upstream((302, 'https://cdn-lfs.example.org/a/b', b''))
        net.opener = urllib.request.build_opener(mp.SameHostRedirect, upstream)
        with self.assertRaises(mp.UpstreamError) as ctx:
            net.get(self.URL)
        self.assertIn('unexpected redirect to cdn-lfs.example.org', str(ctx.exception))
        self.assertEqual(len(upstream.seen), 1)      # the token never reaches the other host

    def test_429_and_5xx_are_retried_with_retry_after_as_seconds_or_date_up_to_the_cap(self):
        net = self.net(http_error(self.URL, 429, {'Retry-After': '7'}), http_error(self.URL, 503, {'Retry-After': '999'}),
                       http_error(self.URL, 500, {'Retry-After': 'Sun, 08 Nov 2026 12:00:30 GMT'}),
                       http_error(self.URL, 502, {'Retry-After': 'not a date'}), FakeResponse(b'[]'))
        net.now = lambda: dt.datetime(2026, 11, 8, 12, 0, 0, tzinfo=dt.timezone.utc)
        self.assertEqual(net.get(self.URL)[1], [])
        self.assertEqual(net.sleeps, [7, 120, 30, 40])
        net = self.net(*[http_error(self.URL, 504)] * 5)
        with self.assertRaises(mp.UpstreamError) as ctx:
            net.get(self.URL)
        self.assertNotIsInstance(ctx.exception, mp.HttpStatus)
        self.assertEqual(str(ctx.exception), 'huggingface.co/api/models/a/b/revision/main: HTTP 504 after 5 attempts')
        self.assertEqual((net.sleeps, len(net.opener.requests)), ([10, 20, 30, 40], 5))

    def test_other_statuses_are_final(self):
        for code in (400, 401, 403, 404, 410):
            net = self.net(http_error(self.URL, code, {'Retry-After': '5'}))
            with self.subTest(code=code), self.assertRaises(mp.HttpStatus) as ctx:
                net.get(self.URL)
            self.assertEqual((ctx.exception.code, ctx.exception.url, net.sleeps), (code, self.URL, []))
            self.assertEqual(str(ctx.exception), f'HTTP {code} for {self.URL}')

    def test_transport_errors_are_retried_then_reported(self):
        net = self.net(urllib.error.URLError('down'), TimeoutError(), ConnectionResetError(), http.client.RemoteDisconnected('closed'),
                       FakeResponse(b'{"ok": true}'))
        self.assertEqual(net.get(self.URL)[1], {'ok': True})
        self.assertEqual(net.sleeps, [10, 20, 30, 40])
        net = self.net(*[urllib.error.URLError('down')] * 5)
        with self.assertRaises(mp.UpstreamError) as ctx:
            net.get(self.URL)
        self.assertIn('URLError after 5 attempts', str(ctx.exception))

    def test_the_run_deadline_ends_retries_and_bounds_every_attempt(self):
        clock = [0.0]
        net = self.net(*[http_error(self.URL, 429, {'Retry-After': '120'})] * 5)
        net.clock, net.deadline = (lambda: clock[0]), 300.0
        net.sleep = lambda s: (net.sleeps.append(s), clock.__setitem__(0, clock[0] + s))
        with self.assertRaises(mp.UpstreamError) as ctx:
            net.get(self.URL)
        self.assertIn('HTTP 429; no time left before the run deadline of 900 s', str(ctx.exception))
        self.assertEqual((net.sleeps, len(net.opener.requests)), ([120, 120], 3))      # a third sleep would end at 360
        net = self.net(FakeResponse())
        net.clock, net.deadline = (lambda: 1000.0), 1000.0
        with self.assertRaises(mp.UpstreamError):
            net.get(self.URL)
        self.assertEqual(net.opener.requests, [])
        net = self.net(FakeResponse())
        net.clock, net.deadline = (lambda: 990.0), 1000.0
        net.get(self.URL)
        self.assertEqual(net.opener.requests[0][1], 10.0)      # no attempt outlives the deadline
        start = mp.Net(env={})
        self.assertAlmostEqual(start.deadline - start.clock(), mp.RUN_DEADLINE, delta=5)

    def test_a_body_that_is_not_json_or_is_too_large_is_an_upstream_error(self):
        for body in (b'<html>busy</html>', b'\xff\xfe', b''):
            net = self.net(FakeResponse(body))
            with self.subTest(body=body), self.assertRaises(mp.UpstreamError) as ctx:
                net.get(self.URL)
            self.assertIn('the response is not JSON', str(ctx.exception))
        with mock.patch.object(mp, 'MAX_BODY_BYTES', 100):
            net = self.net(FakeResponse(b'"' + b'x' * 100 + b'"'))
            with self.assertRaises(mp.UpstreamError) as ctx:
                net.get(self.URL)
            self.assertIn('response over 100 bytes', str(ctx.exception))
            self.assertEqual(self.net(FakeResponse(b'"' + b'x' * 98 + b'"')).get(self.URL)[1], 'x' * 98)
        self.assertEqual(net.sleeps, [])

    def test_the_three_views_ask_the_documented_endpoints(self):
        net = self.net(FakeResponse(b'{"sha": "abc"}'), FakeResponse(b'[{"id": "nvidia/x"}]'))
        self.assertEqual(net.revision('bartowski/Some_Model-3.1-GGUF'), {'sha': 'abc'})
        self.assertEqual(net.newest_models('nvidia', 50), [{'id': 'nvidia/x'}])
        self.assertEqual([req.full_url for req, _ in net.opener.requests],
                         ['https://huggingface.co/api/models/bartowski/Some_Model-3.1-GGUF/revision/main',
                          'https://huggingface.co/api/models?author=nvidia&sort=createdAt&direction=-1&limit=50'])
        # Whatever a pin file holds, a repository id cannot leave the path it belongs in.
        net = self.net(FakeResponse(), FakeResponse(b'[]'))
        net.revision('a/b?x=1#y z')
        net.tree('a/b', 'main/../../x')
        self.assertEqual([req.full_url for req, _ in net.opener.requests],
                         ['https://huggingface.co/api/models/a/b%3Fx%3D1%23y%20z/revision/main',
                          'https://huggingface.co/api/models/a/b/tree/main%2F..%2F..%2Fx?recursive=true'])

    def test_a_tree_follows_its_next_pages_and_only_on_hugging_face(self):
        first = f'https://huggingface.co/api/models/a/b/tree/{NEW}?recursive=true'
        second = first + '&cursor=abc%3D'
        net = self.net(FakeResponse(b'[{"path": "one"}]', headers={'Link': f'<{second}>; rel="next"'}), FakeResponse(b'[{"path": "two"}]'))
        self.assertEqual(net.tree('a/b', NEW), [{'path': 'one'}, {'path': 'two'}])
        self.assertEqual([req.full_url for req, _ in net.opener.requests], [first, second])
        net = self.net(FakeResponse(b'[]', headers={'Link': '<https://example.com/next>; rel="next"'}), env={'HF_TOKEN': 'hf-secret'})
        with self.assertRaises(ValueError):
            net.tree('a/b', NEW)
        self.assertEqual(len(net.opener.requests), 1)      # the other host is never asked
        net = self.net(FakeResponse(b'{"error": "not a list"}'))
        with self.assertRaises(mp.UpstreamError):
            net.tree('a/b', NEW)
        net = self.net(*[FakeResponse(b'[]', headers={'Link': f'<{second}>; rel="next"'}) for _ in range(mp.MAX_TREE_PAGES + 1)])
        with self.assertRaises(mp.UpstreamError) as ctx:
            net.tree('a/b', NEW)
        self.assertIn(f'more than {mp.MAX_TREE_PAGES} pages', str(ctx.exception))
        self.assertEqual(len(net.opener.requests), mp.MAX_TREE_PAGES)


# --- the workflow and the documents -------------------------------------------------------------------------------
class WorkflowTest(unittest.TestCase):
    """.github/workflows/model-pins.yml: when it runs, what it may write and how it reads the script's outputs."""

    TEXT = (ROOT / '.github/workflows/model-pins.yml').read_text(encoding='utf-8')
    PINS = (ROOT / '.github/workflows/upstream-pins.yml').read_text(encoding='utf-8')
    DISCOVERY = (ROOT / '.github/workflows/model-discovery.yml').read_text(encoding='utf-8')
    DEPENDABOT = (ROOT / '.github/dependabot.yml').read_text(encoding='utf-8')

    def step(self, name):
        start = self.TEXT.index(f'      - name: {name}\n')
        end = self.TEXT.find('\n      - name: ', start)
        return self.TEXT[start:] if end < 0 else self.TEXT[start:end]

    def test_it_runs_after_the_other_nightly_jobs_under_its_own_names(self):
        self.assertEqual(re.findall(r'cron: "([^"]+)"', self.TEXT), ['17 7 * * *'])
        others = [re.search(r'cron: "([^"]+)"', text).group(1) for text in (self.PINS, self.DISCOVERY)]
        others += re.findall(r'cronjob: "([^"]+)"', self.DEPENDABOT)
        self.assertGreaterEqual(len(others), 3)
        for other in others:
            minute, hour, *rest = other.split()
            self.assertEqual(rest, ['*', '*', '*'], other)                 # nightly, like this job
            self.assertLess((int(hour), int(minute)), (7, 17), other)      # this job is the last of the night
        triggers = re.search(r'^on:\n((?:  .*\n)+)', self.TEXT, re.M).group(1)
        self.assertEqual([line for line in triggers.splitlines() if not line.startswith('    ')], ['  schedule:', '  workflow_dispatch:'])
        perms = re.search(r'^permissions:\n((?:  .*\n)+)', self.TEXT, re.M).group(1)
        self.assertEqual(sorted(line.strip() for line in perms.splitlines()), ['contents: write', 'issues: write', 'pull-requests: write'])
        self.assertIn('\nconcurrency:\n  group: model-pins\n  cancel-in-progress: false\n', self.TEXT)

        def names(text):
            return dict(re.findall(r'^  (BRANCH|PR_TITLE|ISSUE_TITLE): (.+)$', text, re.M))
        mine, theirs = names(self.TEXT), names(self.PINS)
        self.assertEqual(mine, {'BRANCH': 'auto/model-pins', 'PR_TITLE': '"Bump pinned model artifact revisions"',
                                'ISSUE_TITLE': '"Model versions needing a manual decision"'})
        # The upstream pin check finds its pull request by branch and its issue by title: nothing is shared with it.
        self.assertEqual(sorted(theirs), sorted(mine))
        for key in mine:
            self.assertNotEqual(mine[key], theirs[key], key)
        self.assertNotIn('group: model-pins', self.PINS + self.DISCOVERY)
        self.assertNotIn(mine['ISSUE_TITLE'], self.DISCOVERY)
        label = re.search(r'^  ISSUE_LABEL: (\S+)$', self.TEXT, re.M).group(1)
        self.assertEqual(label, 'model-pins')
        self.assertNotIn(f'ISSUE_LABEL: {label}', self.DISCOVERY)

    def test_the_checkout_is_pinned_and_can_start_ci_on_the_pull_request(self):
        uses = re.findall(r'uses: (\S+)', self.TEXT)
        checkout = re.search(r'actions/checkout@([0-9a-f]{40})', self.PINS).group(1)
        self.assertEqual(uses, [f'actions/checkout@{checkout}'])      # the one action, at the commit the other workflows pin
        before_steps = self.TEXT.split('      - name:', 1)[0]
        self.assertIn('          token: ${{ secrets.UPSTREAM_BUMP_TOKEN || secrets.GITHUB_TOKEN }}\n', before_steps)
        self.assertNotIn('pip install', self.TEXT)      # the script and its tests run on the runner's own python3
        self.assertNotIn('setup-python', self.TEXT)
        minutes = int(re.search(r'^    timeout-minutes: (\d+)', self.TEXT, re.M).group(1))
        # five minutes are left for the checkout, the offline tests, the push and the issue calls
        self.assertLessEqual(mp.RUN_DEADLINE + 5 * 60, minutes * 60)

    def test_the_resolve_step_runs_the_script_with_flags_it_has(self):
        resolve = self.step('Resolve the model pins and apply the bumps')
        command = 'python3 scripts/model_pins.py --apply --summary /tmp/summary.md --issue-summary /tmp/issue.md --github-output'
        self.assertIn(f'          {command}\n', resolve)
        args = mp.parser().parse_args(shlex.split(command)[2:])
        self.assertEqual((args.apply, args.summary, args.issue_summary, args.github_output, args.strict, args.download_spec),
                         (True, '/tmp/summary.md', '/tmp/issue.md', True, False, None))
        self.assertIn('        id: resolve\n', resolve)
        self.assertIn('          HF_TOKEN: ${{ secrets.HF_TOKEN }}', resolve)
        self.assertNotIn('GITHUB_TOKEN', resolve)      # the script reads Hugging Face only
        self.assertIn('cat /tmp/summary.md >> "$GITHUB_STEP_SUMMARY"', resolve)
        checks = self.step('Run the offline checks CI would')
        self.assertIn("\n        if: steps.resolve.outputs.changed == 'true'\n", checks)
        self.assertIn("python3 -m unittest discover -s tests -p 'test_model_pins.py' -v", checks)
        self.assertLess(self.TEXT.index('- name: Run the offline checks CI would'),
                        self.TEXT.index('- name: Open or refresh the bump pull request'))

    def test_the_pull_request_comes_from_one_branch_and_is_pushed_only_when_its_tree_differs(self):
        pr = self.step('Open or refresh the bump pull request')
        self.assertIn("\n        if: steps.resolve.outputs.changed == 'true'\n", pr)
        self.assertIn('GH_TOKEN: ${{ secrets.UPSTREAM_BUMP_TOKEN || secrets.GITHUB_TOKEN }}', pr)
        self.assertIn('git checkout -B "$BRANCH"\n', pr)
        self.assertIn('git commit -am "$PR_TITLE"\n', pr)
        self.assertRegex(pr, r'if git fetch -q origin "\$BRANCH" 2>/dev/null \\\n +&& \[ "\$\(git rev-parse "origin/\$BRANCH\^\{tree\}"\)" = '
                             r'"\$\(git rev-parse \'HEAD\^\{tree\}\'\)" \]; then\n +echo "PR branch already up to date\."\n +else\n +'
                             r'git push --force origin "\$BRANCH"\n +fi\n')
        self.assertEqual(self.TEXT.count('git push'), 1)
        self.assertIn('existing="$(gh pr list --head "$BRANCH" --base "$BASE" --state open --json number --jq \'.[0].number\')"', pr)
        self.assertIn('gh pr edit "$existing" --title "$PR_TITLE" --body-file /tmp/summary.md', pr)
        self.assertIn('gh pr create --head "$BRANCH" --base "$BASE" --title "$PR_TITLE" --body-file /tmp/summary.md', pr)
        self.assertEqual(self.TEXT.count('gh pr create'), 1)

    def test_the_issue_is_refreshed_on_a_decision_and_closed_only_after_a_run_without_failed_lookups(self):
        read = self.step('Read the tracking issue')
        refresh = self.step('Refresh the tracking issue with what needs a manual decision')
        close = self.step('Close the tracking issue once nothing needs a manual decision')
        self.assertIn("\n        if: steps.resolve.outputs.manual == 'true'\n", refresh)
        self.assertIn("\n        if: steps.resolve.outputs.manual == 'false' && steps.resolve.outputs.failed == 'false'\n", close)
        self.assertNotIn('\n        if:', read)
        for text in (read, refresh, close):
            self.assertIn('          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}\n', text)      # the issue's author is github-actions[bot]
            self.assertNotIn('UPSTREAM_BUMP_TOKEN', text)
        for text in (refresh, close):
            self.assertIn('          NUMBER: ${{ steps.issue.outputs.number }}\n          STATE: ${{ steps.issue.outputs.state }}\n', text)
        self.assertIn('{ printf \'_%s_\\n\\n\' "$note"; cat /tmp/issue.md; } > /tmp/issue-body.md', refresh)
        self.assertIn('open)   gh issue edit "$NUMBER" --body-file /tmp/issue-body.md', refresh)
        self.assertIn('closed) gh issue reopen "$NUMBER"\n                    gh issue edit "$NUMBER" --body-file /tmp/issue-body.md', refresh)
        self.assertIn('*)      gh issue create --title "$ISSUE_TITLE" --body-file /tmp/issue-body.md --label "$ISSUE_LABEL" ;;', refresh)
        self.assertIn('          if [ "$STATE" = "open" ]; then\n            gh issue close "$NUMBER" --comment ', close)
        self.assertEqual((self.TEXT.count('gh issue close'), self.TEXT.count('gh issue create')), (1, 1))
        self.assertLess(self.TEXT.index('- name: Read the tracking issue'), self.TEXT.index('- name: Refresh the tracking issue'))

    def test_the_tracking_issue_is_one_the_workflow_created(self):
        read = self.step('Read the tracking issue')
        self.assertNotIn('--search', self.TEXT)      # matches anyone's issue by title, and the search index lags
        self.assertNotIn('gh issue list', self.TEXT)
        self.assertEqual(read.count('gh api "repos/$GITHUB_REPOSITORY/issues?state='), 2)
        self.assertEqual(read.count('&labels=$ISSUE_LABEL&'), 2)
        mine = re.search(r"^\s*mine='([^']*)'$", read, re.M).group(1)
        self.assertIn('.user.login == "github-actions[bot]"', mine)
        self.assertIn('.title == env.ISSUE_TITLE', mine)
        self.assertIn('.pull_request == null', mine)
        # The filter of the model discovery workflow, which runs it every night.
        self.assertEqual(mine, re.search(r"^\s*mine='([^']*)'$", self.DISCOVERY, re.M).group(1))
        tails = re.findall(r'--jq "\$mine \| ([^"]*)"', read)
        self.assertEqual(tails, ['.[0].number // empty', 'sort_by(.closed_at) | last | .number // empty'])
        self.assertIn('echo "number=$number" >> "$GITHUB_OUTPUT"\n          echo "state=$state" >> "$GITHUB_OUTPUT"\n', read)

    def test_the_header_says_what_is_checked_what_is_never_touched_and_how_the_nightly_jobs_relate(self):
        header, body = self.TEXT.split('\non:\n', 1)
        self.assertTrue(all(line.startswith('#') or not line for line in header.splitlines()[1:]))
        for phrase in ('catalog/model-artifacts.json', 'Never touched: catalog/models.json', 'docs/results/', 'upstream-pins.yml (06:17 UTC)',
                       'Dependabot', 'model-discovery.yml', '(06:47 UTC)', 'at 07:17 UTC', 'UPSTREAM_BUMP_TOKEN', 'HF_TOKEN is optional',
                       'docs/MODELS.md'):
            self.assertIn(phrase, header)
        # The times the header quotes are the other jobs' own.
        self.assertIn('cron: "17 6 * * *"', self.PINS)
        self.assertIn('cron: "47 6 * * *"', self.DISCOVERY)
        self.assertEqual(set(re.findall(r'cronjob: "([^"]+)"', self.DEPENDABOT)), {'17 6 * * *'})
        # Below its header the workflow names no repository file but the script and its test module.
        self.assertEqual(sorted(set(re.findall(r'\b(?:catalog|docs|scripts|tests|src)/[\w./-]+', body))), ['scripts/model_pins.py'])
        self.assertIn('model-pins.yml', self.PINS.split('\non:\n', 1)[0])      # the upstream pin check points here

    def test_documented_commands_parse_and_the_documents_name_the_job_as_the_workflow_runs_it(self):
        documented = []
        for path in sorted((ROOT / 'docs').glob('*.md')):
            for found in re.findall(r'scripts/model_pins\.py((?: +(?:--[a-z-]+|[\w./,-]+))*)', path.read_text(encoding='utf-8')):
                documented.append((path.name, found))
        self.assertEqual({doc for doc, _ in documented}, {'MODELS.md', 'WORKFLOWS.md'})
        for doc in ('MODELS.md', 'WORKFLOWS.md'):      # each names the nightly command and the manifest command
            self.assertIn((doc, ' --apply'), documented)
            self.assertTrue(any(d == doc and found.startswith(' --download-spec ') for d, found in documented), doc)
        for doc, found in documented:
            with self.subTest(doc=doc, command=found):
                mp.parser().parse_args(shlex.split(found))      # exits 2 on a flag the script does not have
        workflows = (ROOT / 'docs/WORKFLOWS.md').read_text(encoding='utf-8')
        self.assertIn('Four nightly jobs', workflows)
        self.assertNotIn('Three nightly jobs', workflows)
        for text in (workflows, (ROOT / 'docs/MODELS.md').read_text(encoding='utf-8')):
            self.assertIn('(`.github/workflows/model-pins.yml`, 07:17 UTC', text)
            self.assertIn('"Model versions needing a manual decision"', text)
            self.assertIn('`auto/model-pins`', text)
        self.assertIn('[MODELS.md](MODELS.md#artifact-pins)', (ROOT / 'docs/MODEL_DISCOVERY.md').read_text(encoding='utf-8'))
        self.assertIn('\n## Artifact pins\n', (ROOT / 'docs/MODELS.md').read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
