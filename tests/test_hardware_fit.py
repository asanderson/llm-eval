"""The hardware-fit experiment: projected and measured fit of a model artifact inside GPU VRAM.

Everything here is offline and deterministic: fixture candidate sets, fixture backend logs, patched GPU readings, a
loopback fixture server and temporary directories with temporary lock roots. No model is served and no GPU is read.
"""
import contextlib
import copy
import gzip
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from llm_eval import readiness
from llm_eval.common import GIB, read_json, sha256_file, write_json
from llm_eval.experiments import REGISTRY, list_experiments
from llm_eval.experiments import hardware_fit as fit
from llm_eval.experiments.hardware_fit import evidence, measured, projection, study
from llm_eval.orchestration import worker
from llm_eval.orchestration.planner import compile_campaign, revision
from llm_eval.orchestration.scheduler import initialize, run_campaign
from llm_eval.orchestration.setup import setup_campaign
from llm_eval.reporting.experiment import build_report, sanitize
from llm_eval.reporting.index import collect, top_combinations, write_results_index
from llm_eval.reporting.publish import publish_report, validate_bundle

ROOT = Path(__file__).resolve().parents[1]
X = ROOT / 'experiments/hardware-fit'
SMOKE = X / 'candidates/smoke.json'
REAL = X / 'candidates/measured-models-gguf.json'
RAIDER = {'hardware_profile': 'msi-raider-18-hx-ai', 'os_id': 'ubuntu-26.04-native'}
GPU_NAME = 'NVIDIA GeForce RTX 5090 Laptop GPU'
MODEL = {'model_id': 'm', 'parameters': 8_000_000_000, 'kv_elements_per_token': 65536, 'trained_context_tokens': 32768}
# The limits of the Raider profile on a native OS: 24 GiB VRAM with 2 GiB reserved, 24 threads, 52 GiB RAM budget.
VIEW = {'vram_gib': 24, 'vram_reserve_gib': 2, 'cpu_threads': 24, 'ram_budget_gib': 52, 'disk_free_gib': 500}
IDENTITY = {'harness': 'projection', 'model': 'smoke'}


def policy(**changes):
    return projection.effective_policy(changes, VIEW['cpu_threads'])


def tree(directory):
    """Every path below a directory with the bytes of each file: what a side-effect check compares."""
    return {p.relative_to(directory).as_posix(): p.read_bytes() if p.is_file() else None for p in sorted(Path(directory).rglob('*'))}


def raw_records(report):
    spec = read_json(report / 'publication.json')
    data = gzip.decompress((report / 'bundle' / spec['report_path'] / 'raw/measurements.jsonl.gz').read_bytes())
    return [json.loads(line) for line in data.decode('utf-8').splitlines() if line]


class TempCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name).resolve()      # plans record resolved paths; a Windows runner's temp directory is a short name

    def candidates(self, edit=None, name='set.json'):
        """A copy of the smoke candidate set in the temp directory, edited by `edit(data)`."""
        data = read_json(SMOKE)
        if edit:
            edit(data)
        write_json(self.path / name, data)
        return self.path / name

    def plan(self, mode, cases, os_id='ubuntu-26.04-native'):
        """Plan a temporary campaign over `cases` (bundle aliases, or parameters written as case files) on a test host."""
        write_json(self.path / 'inventory.json', {
            'targets': {'local': {'transport': 'local', 'physical_host_id': 'hardware-fit-test-host', 'lock_root': str(self.path / 'worker-locks')}},
            'hardware_configs': {'native': {'target': 'local', 'hardware_profile': 'msi-raider-18-hx-ai', 'os_id': os_id}}})
        names = []
        for index, case in enumerate(cases):
            if isinstance(case, str):
                names.append(case)
            else:
                write_json(self.path / f'case-{index}.json', {'id': f'case-{index}', 'parameters': case})
                names.append(f'case-{index}.json')
        write_json(self.path / 'campaign.json', {'schema_version': 2, 'id': 'fit-test', 'inventory': 'inventory.json', 'phases': [
            {'id': 'fit', 'experiments': [{'id': 'hardware-fit', 'version': 1, 'mode': mode, 'cases': names, 'hardware_configs': ['native']}]}]})
        return compile_campaign(self.path / 'campaign.json', ROOT)

    def report(self, job, attempt, status='succeeded'):
        """A generic report over one finished attempt directory, built as the scheduler builds it (pattern: tests/test_reporting.py)."""
        job = {'job_id': 'job', 'experiment_id': 'hardware-fit', 'experiment_run_id': 'fit', 'case_id': 'fixture', 'hardware_config_id': 'fixture-raider',
               'status': 'planned', 'reason': None, **job}
        plan = {'campaign_id': 'fit-fixture', 'root': str(ROOT), 'code_revision': revision(ROOT), 'inputs': {}, 'jobs': [job],
                'experiments': [{'experiment_id': 'hardware-fit', 'experiment_run_id': 'fit', 'job_ids': ['job']}], 'reporting': {'on_experiment_end': True}}
        campaign = initialize(plan, self.path / 'campaigns')
        rel = 'experiments/fit/jobs/job/attempt'
        shutil.copytree(attempt, campaign / rel)
        write_json(campaign / rel / 'job.json', job)
        state = read_json(campaign / 'campaign.json')
        state['jobs']['job'] = {'status': status, 'attempts': [{'attempt_id': 'attempt', 'output': rel, 'status': status}]}
        write_json(campaign / 'campaign.json', state)
        return build_report(campaign / 'experiments/fit')

    def template(self):
        """The case path of a byte copy of the shipped measured template, laid out in the temp directory as in the checkout.

        Planned from the checkout, the template's artifact lock is <checkout>/artifacts/selected.lock.json: the file the
        model-offloading guide tells an operator to write. A test must not depend on it."""
        case = 'experiments/hardware-fit/cases/measured-ollama.json'
        for name in (case, 'experiments/hardware-fit/runs/ollama.example.json', REAL.relative_to(ROOT), 'workloads/smoke.json'):
            (self.path / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, self.path / name)
        return case


class CandidateSetTests(TempCase):
    def test_shipped_sets_load(self):
        smoke, real = projection.load_candidates(SMOKE), projection.load_candidates(REAL)
        self.assertEqual((smoke['id'], smoke['synthetic'], len(smoke['models']), len(smoke['candidates'])), ('smoke', True, 2, 5))
        self.assertEqual((real['id'], len(real['models']), len(real['candidates'])), ('measured-models-gguf', 17, 430))
        self.assertNotIn('synthetic', real)
        for name in ('smoke.json', 'measured-models-gguf.json'):      # the planner hashes these bytes: one spelling on every OS
            self.assertNotIn(b'\r', (X / 'candidates' / name).read_bytes(), name)

    def test_smoke_set_is_fictional(self):
        smoke = projection.load_candidates(SMOKE)
        catalog = {m['id'] for m in read_json(ROOT / 'catalog/models.json')['models']}
        for model in smoke['models']:
            self.assertNotIn(model['model_id'], catalog)
            self.assertTrue(model['base_model'].startswith('fictional-lab/') and model['source_repo'].startswith('fictional-lab/'))

    def test_measured_models_set_matches_the_catalog_and_is_well_formed(self):
        real = projection.load_candidates(REAL)
        catalog = {m['id']: m for m in read_json(ROOT / 'catalog/models.json')['models']}
        per_model = {m['model_id']: [c for c in real['candidates'] if c['model_id'] == m['model_id']] for m in real['models']}
        for model in real['models']:
            with self.subTest(model['model_id']):
                self.assertIn(model['model_id'], catalog)
                self.assertEqual(model['base_model'], catalog[model['model_id']]['upstream_repo'])
                self.assertTrue(per_model[model['model_id']])
                # The parameter count llama.cpp printed is within 6 % of the catalog's published figure.
                self.assertAlmostEqual(model['parameters'] / 1e9 / catalog[model['model_id']]['parameters_b'], 1, delta=0.06)
        for candidate in real['candidates']:
            with self.subTest(candidate['id']):      # the label a measured case uses: the model id and the quantization in lower case
                self.assertEqual(candidate['id'], candidate['model_id'] + '-' + candidate['quantization'].lower())
                for file in candidate['files']:
                    self.assertTrue(file['path'].endswith('.gguf'))
        # Sizes are artifact sizes, not planning arithmetic: bits per weight span the published quantization range.
        bits = [c['weight_bytes'] * 8 / next(m for m in real['models'] if m['model_id'] == c['model_id'])['parameters']
                for c in real['candidates']]
        self.assertGreater(min(bits), 1)
        self.assertLess(max(bits), 17)

    def test_each_malformed_set_is_refused(self):
        def edit(path, value):
            def apply(data):
                target = data
                for key in path[:-1]:
                    target = target[key]
                if value is KeyError:
                    del target[path[-1]]
                else:
                    target[path[-1]] = value
            return apply
        first = read_json(SMOKE)['candidates'][0]
        cases = [
            ('duplicate candidate id', edit(('candidates', 1, 'id'), first['id']), 'Duplicate candidate id: fixture-small-7b-q4_k_m'),
            ('duplicate model id', edit(('models', 1, 'model_id'), 'fixture-small-7b'), 'Duplicate model_id in candidate set: fixture-small-7b'),
            ('undeclared model', edit(('candidates', 0, 'model_id'), 'fixture-other'), 'names an undeclared model_id'),
            ('model id shape', edit(('candidates', 0, 'model_id'), ['fixture-small-7b']), 'names an undeclared model_id'),
            ('byte sum', edit(('candidates', 4, 'weight_bytes'), 32212254721), 'weight_bytes does not equal the sum of its files'),
            ('revision', edit(('models', 0, 'source_revision'), 'main'), 'Pin source_revision to a full 40-character repository commit'),
            ('sha256', edit(('candidates', 0, 'files', 0, 'sha256'), 'A' * 64), 'sha256 must be 64 lowercase hexadecimal digits'),
            ('unknown key', edit(('family',), 'x'), 'Unknown fields: family'),
            ('unknown model key', edit(('models', 0, 'license'), 'x'), 'Unknown fields: license'),
            ('unknown candidate key', edit(('candidates', 0, 'bits'), 4), 'Unknown fields: bits'),
            ('unknown file key', edit(('candidates', 0, 'files', 0, 'weight'), True), 'Unknown fields: weight'),
            ('missing key', edit(('size_basis',), KeyError), 'Missing fields: size_basis'),
            ('missing model key', edit(('models', 0, 'layers'), KeyError), 'Missing fields: layers'),
            ('schema version', edit(('schema_version',), 2), 'Candidate set schema_version must be 1'),
            ('boolean schema version', edit(('schema_version',), True), 'Candidate set schema_version must be 1'),
            ('fractional schema version', edit(('schema_version',), 1.0), 'Candidate set schema_version must be 1'),
            ('set id', edit(('id',), 'Smoke'), 'Expected a lowercase identifier'),
            ('candidate id', edit(('candidates', 0, 'id'), 'has space'), 'Expected a lowercase identifier'),
            ('date', edit(('retrieved_on',), '22 November 2026'), 'retrieved_on must be a date written as YYYY-MM-DD'),
            ('impossible date', edit(('retrieved_on',), '2026-13-40'), 'retrieved_on must be a date written as YYYY-MM-DD'),
            ('empty text', edit(('description',), ' '), 'description must be a non-empty string'),
            ('synthetic flag', edit(('synthetic',), 'yes'), 'synthetic must be true or false'),
            ('repository', edit(('models', 0, 'source_repo'), 'no-organisation'), 'source_repo must be a repository id written as ORG/NAME'),
            ('zero parameters', edit(('models', 0, 'parameters'), 0), r'parameters must be in \[1, '),
            ('fractional layers', edit(('models', 0, 'layers'), 32.5), 'layers must be an integer'),
            ('boolean bytes', edit(('candidates', 0, 'files', 0, 'bytes'), True), 'bytes must be a finite number'),
            ('negative window', edit(('models', 0, 'sliding_window_tokens'), -1), r'sliding_window_tokens must be in \[0, '),
            ('parent path', edit(('candidates', 0, 'files', 0, 'path'), '../x.gguf'), 'must be a relative POSIX path without ..'),
            ('absolute path', edit(('candidates', 0, 'files', 0, 'path'), '/models/x.gguf'), 'must be a relative POSIX path without ..'),
            ('windows path', edit(('candidates', 0, 'files', 0, 'path'), 'split\\x.gguf'), 'must be a relative POSIX path without ..'),
            ('drive path', edit(('candidates', 0, 'files', 0, 'path'), 'C:/x.gguf'), 'must be a relative POSIX path without ..'),
            ('path not in normal form', edit(('candidates', 0, 'files', 0, 'path'), './x.gguf'), 'must be a relative POSIX path without ..'),
            ('directory path', edit(('candidates', 0, 'files', 0, 'path'), '.'), 'must be a relative POSIX path without ..'),
            ('blank path', edit(('candidates', 0, 'files', 0, 'path'), ' '), 'must be a relative POSIX path without ..'),
            ('empty path', edit(('candidates', 0, 'files', 0, 'path'), ''), 'must be a relative POSIX path without ..'),
            ('repeated file', edit(('candidates', 4, 'files', 1, 'path'), 'split/fixture-large-30b-Q8_0-00001-of-00002.gguf'), 'lists a file twice'),
            ('no files', edit(('candidates', 0, 'files'), []), 'needs at least one file'),
            ('no models', edit(('models',), []), 'Candidate set needs at least one model'),
            ('no candidates', edit(('candidates',), []), 'Candidate set needs at least one candidate'),
            ('quantization', edit(('candidates', 0, 'quantization'), ''), 'quantization must be a non-empty string'),
        ]
        for name, change, message in cases:
            with self.subTest(name):
                with self.assertRaisesRegex(ValueError, message):
                    projection.load_candidates(self.candidates(change))
        write_json(self.path / 'list.json', [])
        with self.assertRaisesRegex(ValueError, 'Expected an object'):
            projection.load_candidates(self.path / 'list.json')


class ProjectionArithmeticTests(TempCase):
    def fit(self, weight_gib, view=None, context=8192, model=None, **changes):
        return projection.fit(int(weight_gib * GIB), model or MODEL, {**VIEW, **(view or {})}, context, policy(**changes))

    def test_needs_of_a_fitting_artifact(self):
        needs = self.fit(10)
        # 65536 key and value elements per token x 8192 tokens x 2 bytes is exactly 1 GiB.
        self.assertEqual(needs['kv_bytes'], GIB)
        self.assertEqual(needs['compute_bytes'], GIB)
        self.assertEqual(needs['vram_required'], 12 * GIB)
        self.assertEqual(needs['vram_available'], 22 * GIB)
        self.assertEqual(needs['ram_required'], 8 * GIB)
        self.assertEqual(needs['disk_required'], 30 * GIB)
        self.assertAlmostEqual(needs['bits_per_weight'], 10.73741824)
        self.assertEqual(needs['limits'], [])

    def test_vram_limit_and_its_boundary(self):
        self.assertEqual(self.fit(20)['limits'], [])      # 20 + 1 + 1 GiB equals the 22 GiB that remain after the reserve
        self.assertEqual(self.fit(20, gpu_baseline_gib=0.5)['limits'], ['vram'])
        self.assertEqual(self.fit(20.5)['limits'], ['vram'])
        self.assertEqual(self.fit(20, view={'vram_reserve_gib': 0})['vram_available'], 24 * GIB)
        self.assertEqual(self.fit(20, compute_buffer_gib=2.5)['limits'], ['vram'])
        # f32 cache entries double the cache: 20 + 2 + 1 GiB.
        self.assertEqual(self.fit(20, kv_bytes_per_element=4)['kv_bytes'], 2 * GIB)
        self.assertEqual(self.fit(20, kv_bytes_per_element=4)['limits'], ['vram'])

    def test_ram_limit(self):
        self.assertEqual(self.fit(10, host_ram_weight_fraction=1.0)['ram_required'], 18 * GIB)
        self.assertEqual(self.fit(10, host_ram_weight_fraction=1.0)['limits'], [])
        self.assertEqual(self.fit(10, host_ram_weight_fraction=1.0, host_ram_overhead_gib=42)['limits'], [])      # exactly 52 GiB
        self.assertEqual(self.fit(10, host_ram_weight_fraction=1.0, host_ram_overhead_gib=42.5)['limits'], ['ram'])
        self.assertEqual(self.fit(10, view={'ram_budget_gib': 7})['limits'], ['ram'])

    def test_disk_limit(self):
        self.assertEqual(self.fit(10, view={'disk_free_gib': 30})['limits'], [])      # two copies and 10 GiB of headroom
        self.assertEqual(self.fit(10, view={'disk_free_gib': 29.9})['limits'], ['disk'])
        self.assertEqual(self.fit(10, view={'disk_free_gib': 29.9}, disk_copies=1)['disk_required'], 20 * GIB)
        self.assertEqual(self.fit(10, view={'disk_free_gib': 29.9}, disk_headroom_gib=0)['limits'], [])

    def test_cpu_limit(self):
        self.assertEqual(policy()['threads'], 16)      # unset: the launch default, min(16, profile threads)
        self.assertEqual(projection.effective_policy({}, 8)['threads'], 8)
        self.assertEqual(self.fit(10, threads=24)['limits'], [])
        self.assertEqual(self.fit(10, threads=25)['limits'], ['cpu'])

    def test_context_limit(self):
        self.assertEqual(self.fit(10, context=32768)['limits'], [])
        self.assertEqual(self.fit(10, context=32768)['kv_bytes'], 4 * GIB)
        self.assertEqual(self.fit(1, context=32769)['limits'], ['context'])

    def test_limits_are_listed_in_one_order(self):
        needs = self.fit(30, view={'disk_free_gib': 25, 'ram_budget_gib': 4}, context=65536, threads=32)
        self.assertEqual(needs['limits'], ['vram', 'ram', 'disk', 'cpu', 'context'])
        rows = projection.project({'models': [MODEL], 'candidates': [{'id': 'c', 'model_id': 'm', 'quantization': 'Q8_0', 'weight_bytes': 30 * GIB}]},
                                  {**VIEW, 'disk_free_gib': 25}, 8192, policy())
        self.assertEqual((rows[0]['category'], rows[0]['limits'], rows[0]['fits']), ('exceeds-vram', ['vram', 'disk'], False))

    def rows(self, weights, models=None, **changes):
        """Project `{candidate id: (model id, weight GiB)}` and return the rows by candidate id."""
        models = models or {'m': 8_000_000_000}
        data = {'models': [{**MODEL, 'model_id': name, 'parameters': parameters} for name, parameters in models.items()],
                'candidates': [{'id': cid, 'model_id': model, 'quantization': 'Q', 'weight_bytes': int(weight * GIB)}
                               for cid, (model, weight) in weights.items()]}
        rows = projection.project(data, VIEW, 8192, policy(**changes))
        self.assertEqual([r['task_id'] for r in rows], sorted(weights))
        return {r['task_id']: r for r in rows}

    def test_row_values_are_rounded_gib_and_bits(self):
        row = self.rows({'c': ('m', 10)})['c']
        self.assertEqual(row, {      # no quality_pass key: a projection carries no scored check and must not enter the measured ranking
            'task_id': 'c', 'category': 'fits', 'benchmark': 'fit-projection', 'status': 'ok', 'warmup': False, 'repetition': 0,
            'synthetic': False, 'elapsed_s': None, 'quality_check_applicable': False, 'model_id': 'm', 'quantization': 'Q',
            'parameters_b': 8.0, 'bits_per_weight': 10.7374, 'weight_gib': 10.0, 'kv_cache_gib': 1.0, 'compute_buffer_gib': 1.0,
            'vram_required_gib': 12.0, 'vram_available_gib': 22.0, 'vram_headroom_gib': 10.0, 'ram_required_gib': 8.0,
            'disk_required_gib': 30.0, 'limits': [], 'fits': True, 'model_best': True, 'rank': 1})
        self.assertEqual(self.rows({'c': ('m', 20.5)})['c']['vram_headroom_gib'], -0.5)

    def test_a_models_best_is_its_most_precise_fit(self):
        rows = self.rows({'m-q3': ('m', 3.5), 'm-q5': ('m', 5), 'm-q8': ('m', 8), 'm-f16': ('m', 21)})
        self.assertEqual({k: (r['fits'], r['model_best'], r['rank']) for k, r in rows.items()},
                         {'m-q3': (True, False, None), 'm-q5': (True, False, None), 'm-q8': (True, True, 1), 'm-f16': (False, False, None)})

    def test_shortlist_orders_larger_models_first_then_precision_then_id(self):
        models = {'big': 30_000_000_000, 'twin-a': 12_000_000_000, 'twin-b': 12_000_000_000, 'twin-c': 12_000_000_000, 'small': 7_000_000_000}
        rows = self.rows({'big-q4': ('big', 17), 'big-q8': ('big', 30), 'small-q8': ('small', 7.5), 'small-q4': ('small', 4.25),
                          'twin-a-q6': ('twin-a', 9), 'twin-b-q8': ('twin-b', 12), 'twin-c-q8': ('twin-c', 12)}, models)
        self.assertEqual(sorted((r['rank'], k) for k, r in rows.items() if r['rank']),
                         [(1, 'big-q4'), (2, 'twin-b-q8'), (3, 'twin-c-q8'), (4, 'twin-a-q6'), (5, 'small-q8')])
        self.assertEqual({k for k, r in rows.items() if r['model_best']}, {'big-q4', 'twin-b-q8', 'twin-c-q8', 'twin-a-q6', 'small-q8'})

    def test_equal_candidates_of_one_model_tie_on_id(self):
        rows = self.rows({'m-b': ('m', 8), 'm-a': ('m', 8)})
        self.assertEqual((rows['m-a']['model_best'], rows['m-a']['rank'], rows['m-b']['model_best'], rows['m-b']['rank']), (True, 1, False, None))

    def test_minimum_bits_per_weight_lists_but_never_shortlists(self):
        weights = {'m-q2': ('m', 2.5), 'm-q3': ('m', 3.5)}      # 2.68 and 3.76 bits per weight of 8e9 parameters
        rows = self.rows(weights)
        self.assertEqual([(r['fits'], r['model_best'], r['rank']) for r in rows.values()], [(True, False, None)] * 2)
        self.assertEqual(self.rows(weights, min_bits_per_weight=3.5)['m-q3']['rank'], 1)
        rows = self.rows(weights, min_bits_per_weight=0)
        self.assertEqual((rows['m-q3']['rank'], rows['m-q2']['rank']), (1, None))
        # The floor itself is shortlisted: 4 GiB of weights for 2^33 parameters are exactly 4 bits per weight.
        exact = {'m': 8 * GIB}
        self.assertEqual(self.rows({'m-q4': ('m', 4)}, exact)['m-q4']['rank'], 1)
        self.assertIsNone(self.rows({'m-q4': ('m', 3.999)}, exact)['m-q4']['rank'])

    def test_shortlist_length_cuts_the_ranks_not_the_bests(self):
        models = {'a': 9_000_000_000, 'b': 8_000_000_000, 'c': 7_000_000_000}
        weights = {'a-q8': ('a', 9), 'b-q8': ('b', 8), 'c-q8': ('c', 7)}
        rows = self.rows(weights, models, shortlist=2)
        self.assertEqual([(k, r['model_best'], r['rank']) for k, r in rows.items()], [('a-q8', True, 1), ('b-q8', True, 2), ('c-q8', True, None)])

    def test_policy_defaults_and_validation(self):
        self.assertEqual(projection.check_policy({}), {
            'kv_bytes_per_element': 2, 'compute_buffer_gib': 1.0, 'gpu_baseline_gib': 0.0, 'host_ram_overhead_gib': 8.0,
            'host_ram_weight_fraction': 0.0, 'disk_copies': 2, 'disk_headroom_gib': 10.0, 'threads': None, 'min_bits_per_weight': 4.0,
            'shortlist': 10})
        self.assertEqual(projection.check_policy({'threads': None, 'shortlist': 3})['shortlist'], 3)
        # The four allowances end at one pebibyte, so their byte counts stay finite numbers that JSON can carry.
        for key in ('compute_buffer_gib', 'gpu_baseline_gib', 'host_ram_overhead_gib', 'disk_headroom_gib'):
            with self.subTest(key=key):
                self.assertEqual(projection.check_policy({key: 2 ** 20})[key], 2 ** 20)
                for value in (2 ** 20 + 1, 1e300):
                    with self.assertRaisesRegex(ValueError, 'policy.' + key + r' must be in \[0, 1048576\]'):
                        projection.check_policy({key: value})
        for change, message in (({'kv_bits': 16}, 'Unknown fields: kv_bits'), ({'kv_bytes_per_element': 0}, r'policy.kv_bytes_per_element must be in \[0.5, 4\]'),
                                ({'kv_bytes_per_element': 8}, r'policy.kv_bytes_per_element must be in \[0.5, 4\]'),
                                ({'compute_buffer_gib': -1}, r'policy.compute_buffer_gib must be in \[0, 1048576\]'),
                                ({'compute_buffer_gib': float('nan')}, 'policy.compute_buffer_gib must be a finite number'),
                                ({'gpu_baseline_gib': '1'}, 'policy.gpu_baseline_gib must be a finite number'),
                                ({'host_ram_overhead_gib': -0.1}, 'policy.host_ram_overhead_gib must be in'),
                                ({'host_ram_weight_fraction': 1.5}, r'policy.host_ram_weight_fraction must be in \[0, 1\]'),
                                ({'disk_copies': 0}, r'policy.disk_copies must be in \[1, 16\]'), ({'disk_copies': 1.5}, 'policy.disk_copies must be an integer'),
                                ({'disk_headroom_gib': None}, 'policy.disk_headroom_gib must be a finite number'),
                                ({'threads': 0}, r'policy.threads must be in \[1, 4096\]'), ({'threads': True}, 'policy.threads must be a finite number'),
                                ({'min_bits_per_weight': -1}, r'policy.min_bits_per_weight must be in \[0, 64\]'),
                                ({'shortlist': 0}, r'policy.shortlist must be in \[1, 1000\]'), ({'shortlist': 2.0}, 'policy.shortlist must be an integer')):
            with self.subTest(change=change):
                with self.assertRaisesRegex(ValueError, message):
                    projection.check_policy(change)
        with self.assertRaisesRegex(ValueError, 'Expected an object'):
            projection.check_policy([])

    def job(self, **parameters):
        return {'mode': 'projection', 'hardware': {'hardware_profile': 'msi-raider-18-hx-ai', 'os_id': 'ubuntu-26.04-native'},
                'parameters': parameters}

    def test_hardware_view_comes_from_the_bound_profile(self):
        view = projection.hardware_view(self.job(disk_free_gib=800), ROOT)
        self.assertEqual(view, {'hardware_profile': 'msi-raider-18-hx-ai', 'os_id': 'ubuntu-26.04-native',
                                'gpu_name': 'NVIDIA GeForce RTX 5090 Laptop GPU', 'vram_gib': 24, 'vram_reserve_gib': 2, 'cpu_threads': 24,
                                'ram_installed_gib': 64, 'ram_budget_gib': 52, 'disk_free_gib': 800, 'disk_basis': 'declared'})
        wsl = self.job(disk_free_gib=800)
        wsl['hardware']['os_id'] = 'windows-11-wsl2-ubuntu-26.04'
        self.assertEqual(projection.hardware_view(wsl, ROOT)['ram_budget_gib'], 46)      # the profile's limit for the WSL guest
        # The planned profile content wins over the file for the GPU and the installed RAM; a profile without a reserve has none.
        planned = self.job(disk_free_gib=1)
        planned['hardware_profile'] = {'gpu': {'name': 'Fixture GPU', 'vram_gib': 16}, 'ram': {'installed_gib': 32}}
        view = projection.hardware_view(planned, ROOT)
        self.assertEqual((view['gpu_name'], view['vram_gib'], view['vram_reserve_gib'], view['ram_installed_gib']), ('Fixture GPU', 16, 0, 32))

    def test_disk_is_measured_only_when_none_is_declared(self):
        missing = self.path / 'models' / 'not-created' / 'yet'
        calls = []

        def usage(path):
            calls.append(Path(path))
            return SimpleNamespace(total=1000 * GIB, used=250 * GIB, free=750 * GIB + 512)
        with patch('llm_eval.experiments.hardware_fit.projection.shutil.disk_usage', side_effect=usage):
            view = projection.hardware_view(self.job(artifact_root=str(missing)), ROOT)
            self.assertEqual((view['disk_basis'], view['disk_free_gib']), ('measured', (750 * GIB + 512) / GIB))
            self.assertEqual(calls, [self.path])      # the nearest existing ancestor of a directory that does not exist yet
            view = projection.hardware_view(self.job(artifact_root=str(missing), disk_free_gib=12.5), ROOT)
            self.assertEqual((view['disk_basis'], view['disk_free_gib']), ('declared', 12.5))
            self.assertEqual(len(calls), 1)      # a declared value is never overridden by a measurement
        self.assertFalse((self.path / 'models').exists())


LOG_PARTIAL = """\
llama_prepare_model_devices: using device CUDA0 (NVIDIA GeForce RTX 5090 Laptop GPU) (0000:01:00.0) - 23151 MiB free
llama_model_loader: loaded meta data with 40 key-value pairs and 808 tensors from model.gguf (version GGUF V3 (latest))
print_info: file format = GGUF V3 (latest)
print_info: file size   = 26.73 GiB (8.50 BPW)
print_info: n_ctx_train           = 131072
print_info: n_layer               = 62
print_info: n_swa                 = 1024
print_info: model params          = 27.01 B
load_tensors: loading model tensors, this can take a while... (mmap = true)
load_tensors: offloading 20 repeating layers to GPU
load_tensors: offloaded 20/63 layers to GPU
load_tensors:        CUDA0 model buffer size =  9378.46 MiB
load_tensors:    CUDA_Host model buffer size = 19421.02 MiB
llama_context: n_ctx         = 4352
llama_kv_cache:        CPU KV buffer size =   238.00 MiB
llama_kv_cache:      CUDA0 KV buffer size =   102.00 MiB
llama_kv_cache: size =  340.00 MiB (  4352 cells,  10 layers,  1/1 seqs), K (f16):  170.00 MiB, V (f16):  170.00 MiB
llama_kv_cache:        CPU KV buffer size =   442.00 MiB
llama_kv_cache:      CUDA0 KV buffer size =   234.00 MiB
llama_kv_cache: size =  676.00 MiB (  1664 cells,  52 layers,  1/1 seqs), K (f16):  338.00 MiB, V (f16):  338.00 MiB
sched_reserve: reserving ...
sched_reserve:      CUDA0 compute buffer size =   554.01 MiB
sched_reserve:  CUDA_Host compute buffer size =    38.02 MiB
main: server is listening on http://127.0.0.1:8100
"""
LOG_FULL = """\
llama_prepare_model_devices: using device CUDA0 (NVIDIA GeForce RTX 5090 Laptop GPU) (0000:01:00.0) - 23151 MiB free
print_info: n_layer               = 62
load_tensors: offloading 62 repeating layers to GPU
load_tensors: offloading output layer to GPU
load_tensors: offloaded 63/63 layers to GPU
load_tensors:        CUDA0 model buffer size = 15480.25 MiB
load_tensors:   CPU_Mapped model buffer size =   525.13 MiB
llama_kv_cache:      CUDA0 KV buffer size =   340.00 MiB
llama_kv_cache:      CUDA0 KV buffer size =   676.00 MiB
sched_reserve:      CUDA0 compute buffer size =   554.01 MiB
sched_reserve:        CPU compute buffer size =    38.02 MiB
"""
# Ollama wraps the same llama.cpp lines in its own log lines. Here it loads the model twice: the figures are those of the
# last load, and the first load, which left layers and cache on the CPU, is counted as a partial load.
LOG_OLLAMA = """\
time=2026-11-22T10:00:00.000-06:00 level=INFO source=routes.go:1298 msg="Listening on 127.0.0.1:11434 (version 0.40.17)"
time=2026-11-22T10:00:05.000-06:00 level=INFO source=server.go:105 msg="system memory" total="63.5 GiB" free="48.1 GiB"
llama_prepare_model_devices: using device CUDA0 (NVIDIA GeForce RTX 5090 Laptop GPU) (0000:01:00.0) - 23151 MiB free
print_info: n_layer               = 64
load_tensors: offloaded 40/65 layers to GPU
load_tensors:        CUDA0 model buffer size = 10000.00 MiB
load_tensors:    CUDA_Host model buffer size =  6800.00 MiB
llama_kv_cache:        CPU KV buffer size =   104.00 MiB
llama_kv_cache:      CUDA0 KV buffer size =   168.00 MiB
sched_reserve:      CUDA0 compute buffer size =   525.00 MiB
time=2026-11-22T10:06:00.000-06:00 level=INFO source=sched.go:518 msg="updated VRAM based on existing loaded models"
llama_prepare_model_devices: using device CUDA0 (NVIDIA GeForce RTX 5090 Laptop GPU) (0000:01:00.0) - 22890 MiB free
print_info: n_layer               = 64
load_tensors: offloaded 65/65 layers to GPU
load_tensors:        CUDA0 model buffer size = 16700.50 MiB
load_tensors:   CPU_Mapped model buffer size =   100.25 MiB
llama_kv_cache:      CUDA0 KV buffer size =   272.00 MiB
sched_reserve:      CUDA0 compute buffer size =   525.00 MiB
sched_reserve:      CUDA0 compute buffer size =   530.00 MiB
[GIN] 2026/11/22 - 10:06:30 | 200 |  12.5s |  127.0.0.1 | POST  "/api/chat"
"""
# The managed LM Studio launch logs only its supervisor's line: the output of the model load is not kept.
LOG_LMSTUDIO = 'lmstudio supervisor: llm-eval/1a2b3c4d5e6f/model.gguf loaded as fit:locked; server on 127.0.0.1:1234\n'
NO_LOG = dict.fromkeys(('layers_offloaded', 'layers_total', 'model_layers', 'model_loads', 'partial_loads', 'gpu_model_buffer_mib',
                        'host_model_buffer_mib', 'gpu_kv_buffer_mib', 'cpu_kv_buffer_mib', 'gpu_compute_buffer_mib', 'device_free_mib_at_load'))


class EvidenceTests(unittest.TestCase):
    def test_partial_offload_with_split_kv_caches(self):
        self.assertEqual(evidence.parse_backend_log(LOG_PARTIAL), {
            'layers_offloaded': 20, 'layers_total': 63, 'model_layers': 62, 'model_loads': 1, 'partial_loads': 1,
            'gpu_model_buffer_mib': 9378.46, 'host_model_buffer_mib': 19421.02, 'gpu_kv_buffer_mib': 336.0, 'cpu_kv_buffer_mib': 680.0,
            'gpu_compute_buffer_mib': 554.01, 'device_free_mib_at_load': 23151.0})

    def test_full_offload(self):
        parsed = evidence.parse_backend_log(LOG_FULL)
        self.assertEqual((parsed['layers_offloaded'], parsed['layers_total'], parsed['model_layers']), (63, 63, 62))
        self.assertEqual((parsed['model_loads'], parsed['partial_loads']), (1, 0))
        self.assertEqual((parsed['gpu_model_buffer_mib'], parsed['host_model_buffer_mib']), (15480.25, 525.13))
        self.assertEqual((parsed['gpu_kv_buffer_mib'], parsed['cpu_kv_buffer_mib']), (1016.0, None))      # no CPU cache line at all
        self.assertEqual(parsed['gpu_compute_buffer_mib'], 554.01)      # the host's compute buffer is not GPU memory

    def test_a_reloaded_model_gives_the_last_loads_figures_and_counts_the_partial_load(self):
        parsed = evidence.parse_backend_log(LOG_OLLAMA)
        self.assertEqual(parsed, {
            'layers_offloaded': 65, 'layers_total': 65, 'model_layers': 64, 'model_loads': 2, 'partial_loads': 1,
            'gpu_model_buffer_mib': 16700.5, 'host_model_buffer_mib': 100.25, 'gpu_kv_buffer_mib': 272.0, 'cpu_kv_buffer_mib': None,
            'gpu_compute_buffer_mib': 530.0, 'device_free_mib_at_load': 22890.0})
        crlf = evidence.parse_backend_log(LOG_OLLAMA.replace('\n', '\r\n'))      # a log written on Windows
        self.assertEqual(crlf, parsed)
        # Requests answered between the two loads ran with 25 layers on the CPU: the run did not stay inside VRAM.
        self.assertEqual(evidence.placement(parsed, {'size': None, 'size_vram': None}), 'layers_on_cpu')
        # Each load is judged by its own lines: a CPU cache buffer makes a load partial although its layer line is complete.
        first, second = LOG_OLLAMA.split('time=2026-11-22T10:06:00', 1)
        swapped = evidence.parse_backend_log(second + first.replace('offloaded 40/65', 'offloaded 65/65'))
        self.assertEqual((swapped['model_loads'], swapped['partial_loads'], swapped['cpu_kv_buffer_mib']), (2, 1, 104.0))
        twice = evidence.parse_backend_log(LOG_FULL + LOG_FULL)
        self.assertEqual((twice['model_loads'], twice['partial_loads']), (2, 0))
        self.assertEqual(evidence.placement(twice, {'size': None, 'size_vram': None}), 'all_layers_on_gpu')

    def test_logs_without_placement_lines_give_nulls(self):
        for name, text in (('empty', ''), ('lmstudio supervisor', LOG_LMSTUDIO), ('other text', 'offloaded layers to GPU: all\nn_layer_norm = 3\n')):
            with self.subTest(name):
                self.assertEqual(evidence.parse_backend_log(text), NO_LOG)
        # Buffer lines of a build that prints no layer line are still read (one load is assumed).
        partial = evidence.parse_backend_log('llama_kv_cache:      CUDA0 KV buffer size =   102.00 MiB\n')
        self.assertEqual(partial, {**NO_LOG, 'gpu_kv_buffer_mib': 102.0})

    def test_ollama_ps_reports_the_served_model(self):
        payload = {'models': [{'name': 'other:latest', 'model': 'other:latest', 'size': 5, 'size_vram': 5},
                              {'name': 'fit:locked', 'model': 'fit:locked', 'size': 17_000_000_000, 'size_vram': 16_000_000_000}]}
        self.assertEqual(evidence.served_model_memory(payload, 'fit:locked'), {'size': 17_000_000_000, 'size_vram': 16_000_000_000})
        self.assertEqual(evidence.served_model_memory({'models': [{'name': 'fit:latest', 'size': 7, 'size_vram': 7}]}, 'fit'),
                         {'size': 7, 'size_vram': 7})      # Ollama adds the default tag to a name without one
        for name, value in (('no reply', None), ('not an object', []), ('no models', {'models': []}), ('other model', {'models': [payload['models'][0]]}),
                            ('sizes missing', {'models': [{'name': 'fit:locked'}]}), ('sizes not numbers', {'models': [{'name': 'fit:locked', 'size': 'x', 'size_vram': True}]}),
                            ('models not a list', {'models': {'name': 'fit:locked'}})):
            with self.subTest(name):
                self.assertEqual(evidence.served_model_memory(value, 'fit:locked'), {'size': None, 'size_vram': None})

    def test_device_selection_and_sampled_peak(self):
        rows = [{'index': '0', 'name': 'Intel Arc', 'total_mib': 8000.0, 'used_mib': 10.0},
                {'index': '1', 'name': 'NVIDIA GeForce RTX 5090 Laptop GPU', 'total_mib': 24463.0, 'used_mib': 1000.0},
                {'index': '2', 'name': 'NVIDIA GeForce RTX 5090 Laptop GPU', 'total_mib': 24463.0, 'used_mib': 5.0}]
        # The row with the index the launch selects, when it carries the profile name: never another card of that name.
        self.assertEqual(evidence.device(rows, 'NVIDIA GeForce RTX 5090 Laptop GPU', 1)['used_mib'], 1000.0)
        self.assertEqual(evidence.device(rows, 'NVIDIA GeForce RTX 5090 Laptop GPU', 2)['used_mib'], 5.0)
        self.assertEqual(evidence.device(rows, 'NVIDIA GeForce RTX 5090 Laptop GPU', '2')['index'], '2')
        self.assertIsNone(evidence.device(rows, 'NVIDIA GeForce RTX 5090 Laptop GPU'))      # index 0, the default, is another card
        self.assertIsNone(evidence.device(rows, 'NVIDIA GeForce RTX 5090 Laptop GPU', 3))
        self.assertIsNone(evidence.device(rows, 'NVIDIA GeForce RTX 5090 Laptop GPU', '1,2'))
        self.assertEqual(evidence.device(rows, 'Intel Arc')['total_mib'], 8000.0)
        self.assertIsNone(evidence.device(rows, 'NVIDIA GeForce RTX 4090', 1))
        self.assertIsNone(evidence.device([], 'NVIDIA GeForce RTX 5090 Laptop GPU'))
        samples = [{'gpus': rows}, {'gpus': []}, {'gpus': [{'index': '1', 'used_mib': None}]}, {'sensor_error': 'OSError', 'gpus': []},
                   {'gpus': [{'index': '0', 'used_mib': 7000.0}, {'index': '1', 'used_mib': 17500.5}]}, {'gpus': [{'index': '1', 'used_mib': 16000.0}]}]
        self.assertEqual(evidence.peak_used_mib(samples, '1'), 17500.5)      # that device only, missing readings skipped
        self.assertIsNone(evidence.peak_used_mib(samples, '3'))
        self.assertIsNone(evidence.peak_used_mib([], '1'))

    def test_free_vram_gate(self):
        # 24463 MiB total, 2048 MiB reserved, 1000 MiB in use before the launch: 21415 MiB can be asked for.
        self.assertFalse(evidence.exceeds_free_vram(21415 * 2 ** 20, 24463.0, 2048, 1000.0))
        self.assertTrue(evidence.exceeds_free_vram(21415 * 2 ** 20 + 1, 24463.0, 2048, 1000.0))
        self.assertTrue(evidence.exceeds_free_vram(16 * GIB, 24463.0, 2048, 20000.0))

    def verdict(self, log=None, ps=None, **changes):
        values = {'weight_mib': 16384.0, 'total_mib': 24463.0, 'reserve_mib': 2048, 'baseline_used_mib': 1000.0, 'peak_used_mib': 18500.0,
                  'log': {**NO_LOG, **(log or {})}, 'ps': ps or {'size': None, 'size_vram': None}, **changes}
        return evidence.verdict(**values)

    def test_verdict_of_a_run_inside_vram(self):
        full = {'layers_offloaded': 63, 'layers_total': 63}
        self.assertEqual(self.verdict(full), {'capacity_ok': True, 'placement': 'all_layers_on_gpu', 'gpu_rise_mib': 17500.0, 'rise_ok': True,
                                              'in_vram': True, 'reason': None})
        self.assertEqual(self.verdict(full, peak_used_mib=22415.0)['in_vram'], True)      # exactly total minus reserve
        self.assertEqual(self.verdict({**full, 'cpu_kv_buffer_mib': 0.0})['placement'], 'all_layers_on_gpu')
        reported = self.verdict(ps={'size': 17_000_000_000, 'size_vram': 17_000_000_000}, require_layer_evidence=True)
        self.assertEqual((reported['placement'], reported['in_vram'], reported['reason']), ('reported_in_vram', True, None))
        unobserved = self.verdict()
        self.assertEqual((unobserved['placement'], unobserved['in_vram'], unobserved['reason']), ('unobserved', True, None))

    def test_each_reason_a_run_is_not_inside_vram(self):
        full = {'layers_offloaded': 63, 'layers_total': 63}
        cases = [
            ('peak above total minus reserve', dict(log=full, peak_used_mib=22415.5), 'all_layers_on_gpu', 'vram_reserve_exceeded'),
            ('fewer layers than the model has', dict(log={'layers_offloaded': 20, 'layers_total': 63}), 'layers_on_cpu', 'layers_on_cpu'),
            ('cache on the CPU', dict(log={**full, 'cpu_kv_buffer_mib': 238.0}), 'layers_on_cpu', 'layers_on_cpu'),
            ('cache on the CPU, no layer line', dict(log={'cpu_kv_buffer_mib': 238.0}), 'layers_on_cpu', 'layers_on_cpu'),
            ('an earlier load left layers on the CPU', dict(log={**full, 'model_loads': 2, 'partial_loads': 1}), 'layers_on_cpu', 'layers_on_cpu'),
            ('ollama reports part in RAM', dict(ps={'size': 17_000_000_000, 'size_vram': 9_000_000_000}), 'reported_partly_in_ram', 'layers_on_cpu'),
            ('GPU use rose by less than the weights', dict(log=full, peak_used_mib=14000.0), 'all_layers_on_gpu', 'gpu_use_below_weights'),
            ('no placement evidence where it is required', dict(require_layer_evidence=True), 'unobserved', 'placement_unobserved'),
            ('no GPU reading during the run', dict(log=full, peak_used_mib=None), 'all_layers_on_gpu', 'gpu_memory_unobserved'),
        ]
        for name, changes, placement, reason in cases:
            with self.subTest(name):
                result = self.verdict(**changes)
                self.assertEqual((result['placement'], result['in_vram'], result['reason']), (placement, False, reason))
        # The reasons are checked in one order: capacity, placement, rise, missing placement evidence.
        both = self.verdict(log={'layers_offloaded': 20, 'layers_total': 63}, peak_used_mib=23000.0)
        self.assertEqual((both['capacity_ok'], both['reason']), (False, 'vram_reserve_exceeded'))
        low = self.verdict(log={'layers_offloaded': 20, 'layers_total': 63}, peak_used_mib=9000.0)
        self.assertEqual((low['rise_ok'], low['reason']), (False, 'layers_on_cpu'))
        quiet = self.verdict(peak_used_mib=9000.0, require_layer_evidence=True)
        self.assertEqual((quiet['rise_ok'], quiet['reason']), (False, 'gpu_use_below_weights'))

    def test_rise_threshold_and_layer_line_precedence(self):
        full = {'layers_offloaded': 63, 'layers_total': 63}
        # 80 % of 16384 MiB is 13107.2 MiB above the 1000 MiB baseline.
        self.assertTrue(self.verdict(full, peak_used_mib=14108.0)['rise_ok'])
        self.assertFalse(self.verdict(full, peak_used_mib=14107.0)['rise_ok'])
        self.assertTrue(self.verdict(full, peak_used_mib=9200.0, min_gpu_weight_fraction=0.5)['in_vram'])
        self.assertTrue(self.verdict(full, peak_used_mib=1000.0, min_gpu_weight_fraction=0)['in_vram'])
        # A layer line decides before what Ollama reports; a line that claims more layers than exist decides nothing.
        ps = {'size': 17_000_000_000, 'size_vram': 9_000_000_000}
        self.assertEqual(self.verdict(full, ps=ps)['placement'], 'all_layers_on_gpu')
        self.assertEqual(self.verdict({'layers_offloaded': 64, 'layers_total': 63})['placement'], 'unobserved')
        self.assertEqual(self.verdict({'layers_offloaded': 64, 'layers_total': 63}, ps=ps)['placement'], 'unobserved')


class RegistrationTests(unittest.TestCase):
    def test_registered_with_projection_as_the_default_mode(self):
        self.assertEqual(REGISTRY['hardware-fit'], 'llm_eval.experiments.hardware_fit')
        self.assertIn(fit.MANIFEST, list_experiments())
        bundled = read_json(X / 'experiment.json')
        self.assertEqual((bundled['id'], bundled['version'], bundled['modes']), (fit.MANIFEST['id'], fit.MANIFEST['version'], fit.MANIFEST['modes']))
        self.assertEqual((fit.MANIFEST['id'], fit.MANIFEST['version'], fit.MANIFEST['modes']), ('hardware-fit', 1, ['projection', 'measured']))
        self.assertEqual(sorted(bundled['cases']), ['measured-ollama', 'projection-measured-models', 'projection-smoke'])
        for alias, relative in bundled['cases'].items():
            self.assertEqual(read_json(X / relative)['id'], alias)
        shipped = [X / 'experiment.json', *sorted((X / 'cases').iterdir()), *sorted((X / 'runs').iterdir()), ROOT / 'campaigns/hardware-fit-smoke.json',
                   ROOT / 'configs/examples/hardware-fit/raider-windows-projection.json']
        for path in shipped:
            self.assertNotIn(b'\r', path.read_bytes(), path.name)

    def test_hooks(self):
        self.assertEqual(fit.host_requirements({}, 'projection'), {'gpu': False})
        self.assertEqual(fit.host_requirements({}, 'measured'), {'gpu': True})
        self.assertEqual(fit.setup_platforms({}, 'projection'), [])
        self.assertEqual(fit.setup_platforms({'config': {'platform': 'koboldcpp'}}, 'measured'), ['koboldcpp'])
        # The generic report includes the hardware evidence and prediction supplement.
        table = re.findall(r'^\| `(\w+)', (ROOT / 'docs/NEW_EXPERIMENT.md').read_text(encoding='utf-8'), re.M)
        self.assertEqual(sorted(name for name in table if hasattr(fit, name)), ['host_requirements', 'report_supplement', 'setup_platforms'])

    def test_package_imports_without_optional_dependencies(self):
        # A child interpreter: in this process the modules are imported already (pattern: tests/test_legal_examples.py).
        code = ('import sys\n'
                "for name in ('psutil', 'matplotlib'):\n"
                '    sys.modules[name] = None\n'
                'import importlib, pkgutil\n'
                'import llm_eval.experiments.hardware_fit as package\n'
                'names = sorted(m.name for m in pkgutil.iter_modules(package.__path__))\n'
                'for name in names:\n'
                "    importlib.import_module(package.__name__ + '.' + name)\n"
                "print(' '.join(names))\n")
        env = {**os.environ, 'PYTHONPATH': str(ROOT / 'src')}
        done = subprocess.run([sys.executable, '-c', code], cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout.split(), ['evidence', 'measured', 'projection', 'study'])


class ProjectionValidationTests(TempCase):
    def case(self, **changes):
        case = {'identity': dict(IDENTITY), 'data': str(SMOKE), 'context_tokens': 8192, 'disk_free_gib': 500, 'synthetic': True, **changes}
        return {k: v for k, v in case.items() if v is not KeyError}

    def test_valid_cases_plan_and_are_not_changed(self):
        real = {'harness': 'projection', 'model': 'measured-models-gguf'}
        for name, case in (('smoke', self.case()), ('real set, declared disk', self.case(identity=real, data=str(REAL), synthetic=False)),
                           ('real set, measured disk', self.case(identity=real, data=str(REAL), synthetic=KeyError, disk_free_gib=KeyError,
                                                                 artifact_root=str(self.path / 'models'))),
                           ('real set as a fixture run', self.case(data=str(REAL))),
                           ('both disk inputs', self.case(artifact_root=str(self.path))),
                           ('policy', self.case(policy={'threads': None, 'min_bits_per_weight': 0, 'kv_bytes_per_element': 4}))):
            with self.subTest(name):
                before = copy.deepcopy(case)
                self.assertIsNone(fit.validate(case, ROOT, 'projection'))
                self.assertEqual(case, before)
        self.assertIsNone(fit.validate(self.case(), ROOT))      # projection is the default mode

    def test_each_invalid_case_is_refused(self):
        cases = [
            ('unknown key', dict(candidates={}), 'Unknown fields: candidates'),
            ('no identity', dict(identity=KeyError), 'Missing fields: identity'),
            ('no data', dict(data=KeyError), 'Missing fields: data'),
            ('no context', dict(context_tokens=KeyError), 'Missing fields: context_tokens'),
            ('identity without a model', dict(identity={'harness': 'projection'}), 'Missing fields: model'),
            ('identity with another key', dict(identity={**IDENTITY, 'quantization': 'q4'}), 'Unknown fields: quantization'),
            ('identity not an object', dict(identity='projection/smoke'), 'Expected an object'),
            ('model label', dict(identity={'harness': 'projection', 'model': 'Smoke Set'}), 'Expected a lowercase identifier'),
            ('harness', dict(identity={'harness': 'ollama', 'model': 'smoke'}), 'identity.harness must be projection for a projection case'),
            ('synthetic flag', dict(synthetic='true'), 'synthetic must be true or false'),
            ('context below', dict(context_tokens=256), r'context_tokens must be in \[512, 1048576\]'),
            ('context above', dict(context_tokens=2097152), r'context_tokens must be in \[512, 1048576\]'),
            ('context fraction', dict(context_tokens=8192.5), 'context_tokens must be an integer'),
            ('disk zero', dict(disk_free_gib=0), 'disk_free_gib must be greater than 0'),
            ('disk negative', dict(disk_free_gib=-5), r'disk_free_gib must be in \[0, inf\]'),
            ('disk text', dict(disk_free_gib='800'), 'disk_free_gib must be a finite number'),
            ('artifact root', dict(artifact_root=5), 'artifact_root must be a directory path'),
            ('synthetic without a declared disk', dict(disk_free_gib=KeyError, artifact_root=str(self.path)), 'A synthetic projection declares disk_free_gib'),
            ('no disk input', dict(disk_free_gib=KeyError, synthetic=False, data=str(REAL)),
             'Declare disk_free_gib or artifact_root so free disk space is known'),
            ('policy key', dict(policy={'kv_bits': 16}), 'Unknown fields: kv_bits'),
            ('policy value', dict(policy={'shortlist': 0}), r'policy.shortlist must be in \[1, 1000\]'),
            ('policy shape', dict(policy=[]), 'Expected an object'),
            ('data absent', dict(data=str(self.path / 'absent.json')), 'data must name an existing candidate set file'),
            ('data not a path', dict(data=7), 'data must name an existing candidate set file'),
            ('data malformed', dict(data=str(self.candidates(lambda d: d.update(schema_version=3)))), 'Candidate set schema_version must be 1'),
            ('synthetic set in a real case', dict(synthetic=False), 'A synthetic candidate set needs a synthetic case'),
            ('synthetic set, flag absent', dict(synthetic=KeyError), 'A synthetic candidate set needs a synthetic case'),
            # Shapes that a shared check does not expect are reported as an invalid case too, never as another exception type.
            ('context beyond float range', dict(context_tokens=10 ** 400), 'Invalid hardware-fit case: OverflowError'),
            ('disk beyond float range', dict(disk_free_gib=10 ** 400), 'Invalid hardware-fit case: OverflowError'),
            ('policy value beyond float range', dict(policy={'compute_buffer_gib': 10 ** 400}), 'Invalid hardware-fit case: OverflowError'),
            ('candidate model id shape', dict(data=str(self.candidates(lambda d: d['candidates'][0].update(model_id={'id': 'fixture-small-7b'}), 'shape.json'))),
             'names an undeclared model_id'),
        ]
        for name, changes, message in cases:
            with self.subTest(name):
                with self.assertRaisesRegex(ValueError, message):
                    fit.validate(self.case(**changes), ROOT, 'projection')
        with self.assertRaisesRegex(ValueError, 'Expected an object'):
            fit.validate([], ROOT, 'projection')
        with self.assertRaisesRegex(ValueError, 'Unsupported hardware-fit mode'):
            fit.validate(self.case(), ROOT, 'replay')


class MeasuredCase(TempCase):
    def setUp(self):
        super().setUp()
        gpu = patch('llm_eval.telemetry.gpu_snapshot', return_value=[])      # no test reads the real GPU
        gpu.start()
        self.addCleanup(gpu.stop)

    def config(self, **changes):
        """The shipped run-config template as the planner hands it to the plugin: absolute paths, bound to the Raider profile."""
        config = read_json(X / 'runs/ollama.example.json')
        config.update(suite=str(ROOT / 'workloads/smoke.json'), artifact_root=str(self.path / 'artifact'),
                      artifact_lock=str(self.path / 'artifact.lock.json'), offload_dir=str(self.path / 'offload'), **RAIDER)
        config.update(changes)
        return config

    def case(self, config=None, **changes):
        case = {'identity': {'harness': 'ollama', 'model': 'qwen38-27b-q4_k_m'}, 'config': config or self.config(), 'server_mode': 'managed', **changes}
        return {k: v for k, v in case.items() if v is not KeyError}

    def lock(self, weight_bytes, precision='Q4_K_M'):
        lock = {'schema_version': 1, 'source_repo': 'fictional-lab/fixture-GGUF', 'source_revision': '1' * 40, 'precision': precision,
                'weight_bytes': weight_bytes, 'files': [], 'base_model_repo': 'fictional-lab/fixture'}
        write_json(self.path / 'artifact.lock.json', lock)
        return lock


class MeasuredValidationTests(MeasuredCase):
    def other(self, platform, launch, **config):
        return self.case(self.config(platform=platform, protocol='openai', endpoint='http://127.0.0.1:8100/v1/chat/completions', launch=launch, **config),
                         identity={'harness': platform, 'model': 'qwen38-27b-q4_k_m'})

    def test_valid_cases_plan_and_are_not_changed(self):
        launch = self.config()['launch']
        self.lock(22 * GIB)      # exactly the VRAM budget of the profile: 24 GiB minus the 2 GiB reserve
        cases = [('template', self.case()), ('categories and thresholds', self.case(categories=['reasoning', 'math'],
                                                                                    fit={'min_gpu_weight_fraction': 0.5, 'require_layer_evidence': True})),
                 ('empty extra arguments', self.case(self.config(launch={**launch, 'extra_args': []}))),
                 ('fixture run', self.case(server_mode='external', synthetic=True)),
                 ('installation state', self.case(installation_state=str(self.path / 'state.json'))),
                 ('llama.cpp', self.other('llama.cpp', launch)), ('ik_llama.cpp', self.other('ik_llama.cpp', launch)),
                 ('koboldcpp', self.other('koboldcpp', launch)), ('lmstudio', self.other('lmstudio', {'model_file': 'm.gguf', 'gpu_offload': 'max'}))]
        for name, case in cases:
            with self.subTest(name):
                before = copy.deepcopy(case)
                self.assertIsNone(fit.validate(case, ROOT, 'measured'))
                self.assertEqual(case, before)

    def test_each_invalid_case_is_refused(self):
        launch = self.config()['launch']
        label = 'qwen38-27b-q4_k_m'
        cases = [
            ('unknown key', self.case(livebench={}), 'Unknown fields: livebench'),
            ('no server mode', self.case(server_mode=KeyError), 'Missing fields: server_mode'),
            ('no identity', self.case(identity=KeyError), 'Missing fields: identity'),
            ('model label', self.case(identity={'harness': 'ollama', 'model': 'Q4'}), 'Expected a lowercase identifier'),
            ('synthetic flag', self.case(synthetic=1), 'synthetic must be true or false'),
            ('server mode', self.case(server_mode='auto'), 'server_mode must be managed or external'),
            ('server mode shape', self.case(server_mode=['managed']), 'server_mode must be managed or external'),
            ('config as a path', self.case('run.json'), 'Resolved hardware-fit config must be an object'),
            ('model outside the catalog', self.case(self.config(model_id='not-in-catalog')), 'Unknown platform or model'),
            ('context above the catalog limit', self.case(self.config(context_tokens=65536)), "Context exceeds this catalog's initial validation limit"),
            ('offload lane', self.case(self.config(lane='offload')), 'hardware-fit measures in-VRAM artifacts: set lane to control'),
            ('no lane', self.case({k: v for k, v in self.config().items() if k != 'lane'}), 'hardware-fit measures in-VRAM artifacts: set lane to control'),
            ('platform', self.other('vllm', launch),
             'hardware-fit does not measure platform vllm in this version; supported: ik_llama.cpp, koboldcpp, llama.cpp, lmstudio, ollama'),
            ('harness', self.case(identity={'harness': 'koboldcpp', 'model': label}), 'identity.harness must equal config.platform'),
            ('label without a quantization', self.case(identity={'harness': 'ollama', 'model': 'qwen38-27b'}),
             'identity.model must be config.model_id followed by the quantization, for example qwen38-27b-ud-q4_k_xl'),
            ('label with an empty quantization', self.case(identity={'harness': 'ollama', 'model': 'qwen38-27b-'}),
             'identity.model must be config.model_id followed by the quantization'),
            ('label of another model', self.case(identity={'harness': 'ollama', 'model': 'gemma3-27b-q4_k_m'}), 'identity.model must be config.model_id'),
            ('no served model', self.case({k: v for k, v in self.config().items() if k != 'served_model'}), 'served_model must name the model the backend serves'),
            ('served model shape', self.case(self.config(served_model=7)), 'served_model must name the model the backend serves'),
            ('empty served model', self.case(self.config(served_model='')), 'served_model must name the model the backend serves'),
            ('launch default layers', self.case(self.config(launch={k: v for k, v in launch.items() if k != 'gpu_layers'})), 'set launch.gpu_layers to 999'),
            ('some layers', self.case(self.config(launch={**launch, 'gpu_layers': 20})), 'hardware-fit asks for every layer on the GPU: set launch.gpu_layers to 999'),
            ('engine default layers', self.case(self.config(launch={**launch, 'gpu_layers': -1})), 'set launch.gpu_layers to 999'),
            ('layers as text', self.case(self.config(launch={**launch, 'gpu_layers': '999'})), 'set launch.gpu_layers to 999'),
            ('layers as a fraction', self.case(self.config(launch={**launch, 'gpu_layers': 999.0})), 'set launch.gpu_layers to 999'),
            ('no launch', self.case({k: v for k, v in self.config().items() if k != 'launch'}), 'set launch.gpu_layers to 999'),
            ('lmstudio ratio', self.other('lmstudio', {'model_file': 'm.gguf', 'gpu_offload': '0.5'}), 'set launch.gpu_offload to max'),
            ('lmstudio layer count', self.other('lmstudio', {'model_file': 'm.gguf', 'gpu_layers': 999}), 'set launch.gpu_offload to max'),
            ('extra arguments', self.case(self.config(launch={**launch, 'extra_args': ['--no-kv-offload']})),
             'hardware-fit refuses launch.extra_args: they can override placement and context'),
            ('no categories', self.case(categories=[]), 'categories must be a non-empty list of category ids of catalog/benchmarks.json'),
            ('unknown category', self.case(categories=['reasoning', 'poetry']), 'categories must be a non-empty list of category ids'),
            ('categories as text', self.case(categories='math'), 'categories must be a non-empty list of category ids'),
            ('category shape', self.case(categories=[['math']]), 'categories must be a non-empty list of category ids'),
            ('installation state', self.case(installation_state=5), 'installation_state must be a file path'),
            ('managed fixture run', self.case(synthetic=True), 'Synthetic hardware-fit uses an explicit external fixture endpoint'),
            ('external real run', self.case(server_mode='external'), 'hardware-fit evidence needs the log of a backend it owns: set server_mode to managed'),
            ('threshold key', self.case(fit={'min_vram': 1}), 'Unknown fields: min_vram'),
            ('threshold value', self.case(fit={'min_gpu_weight_fraction': 1.5}), r'fit.min_gpu_weight_fraction must be in \[0, 1\]'),
            ('threshold flag', self.case(fit={'require_layer_evidence': 'yes'}), 'fit.require_layer_evidence must be true or false'),
            ('thresholds shape', self.case(fit=[]), 'Expected an object'),
            # Shapes that the shared run-config check does not expect are reported as an invalid case, never as another exception type.
            ('launch as text', self.case(self.config(launch='gpu_layers=999')), 'Invalid hardware-fit case: AttributeError'),
            ('launch as a list', self.case(self.config(launch=[999])), 'Invalid hardware-fit case: AttributeError'),
            ('lane shape', self.case(self.config(lane=['control'])), 'Invalid hardware-fit case: TypeError'),
            ('platform shape', self.case(self.config(platform=['ollama'])), 'Invalid hardware-fit case: TypeError'),
            ('run config without repeats', self.case({k: v for k, v in self.config().items() if k != 'repeats'}),
             "Invalid hardware-fit case: KeyError: 'repeats'"),
            ('threshold beyond float range', self.case(fit={'min_gpu_weight_fraction': 10 ** 400}), 'Invalid hardware-fit case: OverflowError'),
        ]
        for name, case, message in cases:
            with self.subTest(name):
                with self.assertRaisesRegex(ValueError, message):
                    fit.validate(case, ROOT, 'measured')

    def test_the_label_names_the_locked_precision(self):
        q8 = self.case(identity={'harness': 'ollama', 'model': 'qwen38-27b-q8_0'})
        self.assertIsNone(fit.validate(q8, ROOT, 'measured'))      # no lock file yet: only the shape of the label is checked
        self.lock(16 * GIB)      # precision Q4_K_M
        self.assertIsNone(fit.validate(self.case(), ROOT, 'measured'))
        for name, label in (('another quantization', 'qwen38-27b-q8_0'), ('a longer label', 'qwen38-27b-q4_k_m-v2'), ('a shorter label', 'qwen38-27b-q4')):
            with self.subTest(name):
                with self.assertRaisesRegex(ValueError, 'followed by the precision of the artifact lock in lower case: qwen38-27b-q4_k_m$'):
                    fit.validate(self.case(identity={'harness': 'ollama', 'model': label}), ROOT, 'measured')
        self.assertIsNone(fit.validate(self.case(identity={'harness': 'ollama', 'model': 'qwen38-27b-q8_0'}, server_mode='external', synthetic=True),
                                       ROOT, 'measured'))      # a fixture run reads no lock
        # The label of the shipped template is the id of a shipped candidate, and the lock of that artifact carries its quantization.
        label = read_json(X / 'cases/measured-ollama.json')['parameters']['identity']['model']
        (candidate,) = [c for c in read_json(REAL)['candidates'] if c['id'] == label]
        self.lock(candidate['weight_bytes'], candidate['quantization'])
        self.assertIsNone(fit.validate(self.case(identity={'harness': 'ollama', 'model': label}), ROOT, 'measured'))
        write_json(self.path / 'artifact.lock.json', {'weight_bytes': 16 * GIB})      # a lock without a precision names no artifact
        with self.assertRaisesRegex(ValueError, 'followed by the precision of the artifact lock in lower case: qwen38-27b-$'):
            fit.validate(self.case(), ROOT, 'measured')

    def test_skip_reasons(self):
        excluded = self.case(self.config(model_id='grok-1'), identity={'harness': 'ollama', 'model': 'grok-1-q4_k_m'})
        self.assertEqual(fit.validate(excluded, ROOT, 'measured'), 'unsupported_os_or_excluded_model')
        self.assertIsNone(fit.validate(self.case(), ROOT, 'measured'))      # no lock file yet: nothing to compare
        self.lock(22 * GIB + 1)      # one byte above the 22 GiB the profile leaves after its reserve
        self.assertEqual(fit.validate(self.case(), ROOT, 'measured'), 'artifact_exceeds_gpu_vram_budget')
        self.assertIsNone(fit.validate(self.case(server_mode='external', synthetic=True), ROOT, 'measured'))      # a fixture run places no weights
        with self.assertRaisesRegex(ValueError, 'set lane to control'):      # an invalid configuration is an error, not a skip
            fit.validate(self.case(self.config(lane='disk')), ROOT, 'measured')
        self.assertEqual(fit.execute({'mode': 'measured', 'hardware': dict(RAIDER), 'parameters': self.case()}, self.path / 'attempt', ROOT),
                         {'status': 'skipped', 'reason': 'artifact_exceeds_gpu_vram_budget'})
        self.assertEqual(list((self.path / 'attempt').iterdir()), [])
        for name, lock in (('no weight', {'files': []}), ('weight as text', {'weight_bytes': '16 GiB'}), ('not an object', [])):
            with self.subTest(name):
                write_json(self.path / 'artifact.lock.json', lock)
                with self.assertRaisesRegex(ValueError, 'artifact_lock weight_bytes must be a finite number'):
                    fit.validate(self.case(), ROOT, 'measured')


class ProjectionExecuteTests(TempCase):
    def job(self, **parameters):
        return {'mode': 'projection', 'hardware': dict(RAIDER),
                'parameters': {'identity': dict(IDENTITY), 'data': str(SMOKE), 'context_tokens': 8192, 'disk_free_gib': 500, 'synthetic': True, **parameters}}

    def rows(self, out):
        return [json.loads(line) for line in (out / 'requests.jsonl').read_text(encoding='utf-8').splitlines()]

    def test_fixture_projection_writes_rows_metadata_and_a_table(self):
        out = self.path / 'attempt' / 'new'      # the attempt directory is created when absent
        shipped = tree(X)
        result = fit.execute(self.job(), out, ROOT)
        self.assertEqual(result, {'status': 'succeeded', 'result_path': '.', 'benchmark': 'fit-projection', 'candidates': 5, 'fits': 4})
        self.assertEqual(sorted(p.name for p in out.iterdir()), ['fit-projection.md', 'metadata.json', 'requests.jsonl'])
        rows = self.rows(out)
        self.assertEqual({r['task_id']: (r['category'], r['model_best'], r['rank']) for r in rows}, {
            'fixture-large-30b-q3_k_s': ('fits', False, None), 'fixture-large-30b-q4_k_m': ('fits', True, 1),
            'fixture-large-30b-q8_0': ('exceeds-vram', False, None), 'fixture-small-7b-q4_k_m': ('fits', False, None),
            'fixture-small-7b-q8_0': ('fits', True, 2)})
        self.assertEqual([r['task_id'] for r in rows], sorted(r['task_id'] for r in rows))
        large = rows[1]      # 17 GiB of weights, 3 GiB of cache at 8192 tokens and 1 GiB of buffers against 22 GiB
        self.assertEqual((large['weight_gib'], large['kv_cache_gib'], large['compute_buffer_gib'], large['vram_required_gib'], large['vram_available_gib'],
                          large['vram_headroom_gib'], large['bits_per_weight'], large['parameters_b'], large['quantization']),
                         (17.0, 3.0, 1.0, 21.0, 22.0, 1.0, 4.8676, 30.0, 'Q4_K_M'))
        self.assertEqual((rows[2]['limits'], rows[2]['fits'], rows[2]['vram_headroom_gib']), (['vram'], False, -12.0))
        for row in rows:
            self.assertEqual((row['benchmark'], row['status'], row['warmup'], row['repetition'], row['synthetic'], row['elapsed_s'], row['quality_check_applicable']),
                             ('fit-projection', 'ok', False, 0, True, None, False))
        metadata = read_json(out / 'metadata.json')
        self.assertEqual({k: metadata[k] for k in ('experiment', 'record', 'schema_version', 'synthetic', 'context_tokens', 'observed')},
                         {'experiment': 'hardware-fit', 'record': 'fit-projection', 'schema_version': 1, 'synthetic': True, 'context_tokens': 8192,
                          'observed': None})
        self.assertEqual(metadata['candidate_set'], {'id': 'smoke', 'retrieved_on': '2026-11-22', 'sha256': sha256_file(SMOKE), 'model_count': 2,
                                                     'candidate_count': 5})
        self.assertEqual(metadata['policy'], policy())
        self.assertEqual(metadata['hardware'], {**RAIDER, 'gpu_name': GPU_NAME, 'vram_gib': 24, 'vram_reserve_gib': 2, 'cpu_threads': 24,
                                                'ram_installed_gib': 64, 'ram_budget_gib': 52, 'disk_free_gib': 500, 'disk_basis': 'declared'})
        self.assertEqual(metadata['counts'], {'fits': 4, 'exceeds-vram': 1, 'exceeds-ram': 0, 'exceeds-disk': 0, 'exceeds-cpu': 0, 'exceeds-context': 0})
        self.assertEqual(metadata['shortlist'], [
            {'rank': 1, 'id': 'fixture-large-30b-q4_k_m', 'model_id': 'fixture-large-30b', 'quantization': 'Q4_K_M', 'parameters_b': 30.0,
             'bits_per_weight': 4.8676, 'weight_gib': 17.0, 'vram_required_gib': 21.0, 'vram_headroom_gib': 1.0},
            {'rank': 2, 'id': 'fixture-small-7b-q8_0', 'model_id': 'fixture-small-7b', 'quantization': 'Q8_0', 'parameters_b': 7.0,
             'bits_per_weight': 9.2035, 'weight_gib': 7.5, 'vram_required_gib': 9.5, 'vram_headroom_gib': 12.5}])
        self.assertIn('not measured', metadata['caveat'])
        self.assertIn('not a quality measurement', metadata['caveat'])
        table = (out / 'fit-projection.md').read_text(encoding='utf-8')
        self.assertIn(metadata['caveat'], table)
        self.assertIn('| 1 | fixture-large-30b-q4_k_m | fixture-large-30b | Q4_K_M | 30.0 | 4.8676 | 17.0 | 21.0 | 1.0 |', table)
        self.assertIn('| exceeds-vram | 1 |', table)
        self.assertIn('500 GiB free disk (declared)', table)
        for name in ('requests.jsonl', 'metadata.json', 'fit-projection.md'):
            self.assertNotIn(b'\r', (out / name).read_bytes(), name)
        # Nothing is written outside the attempt directory, and the report's sanitiser drops and rewrites nothing.
        self.assertEqual(tree(X), shipped)
        self.assertEqual([p.name for p in self.path.iterdir()], ['attempt'])
        removed = set()
        self.assertEqual(sanitize(rows + [metadata, result], removed), rows + [metadata, result])
        self.assertEqual(removed, set())

    def test_same_inputs_give_the_same_bytes(self):
        for name in ('first', 'second'):
            fit.execute(self.job(policy={'shortlist': 1}), self.path / name, ROOT)
        self.assertEqual(tree(self.path / 'first'), tree(self.path / 'second'))
        self.assertEqual(len((self.path / 'first/requests.jsonl').read_bytes().splitlines()), 5)

    def test_real_projection_over_the_measured_models_on_the_raider_profile(self):
        host = {'gpus': [{'index': '0', 'name': GPU_NAME, 'driver_version': '999.99', 'total_mib': 24463.0, 'used_mib': 1200.0}],
                'psutil_available': True, 'ram_total_gib': 63.438612, 'logical_cpus': 24, 'system': 'Windows'}
        job = self.job(data=str(REAL), synthetic=False, identity={'harness': 'projection', 'model': 'measured-models-gguf'})
        with patch('llm_eval.telemetry.host_snapshot', return_value=host) as snapshot:
            result = fit.execute(job, self.path / 'out', ROOT)
        snapshot.assert_called_once_with()
        self.assertEqual(result, {'status': 'succeeded', 'result_path': '.', 'benchmark': 'fit-projection', 'candidates': 430, 'fits': 221})
        metadata = read_json(self.path / 'out/metadata.json')
        self.assertEqual(metadata['observed'], {'gpus': [{'name': GPU_NAME, 'total_mib': 24463.0}], 'ram_total_gib': 63.4386, 'logical_cpus': 24})
        self.assertEqual((metadata['synthetic'], metadata['counts']['fits'], metadata['counts']['exceeds-vram']), (False, 221, 209))
        # One candidate per model that has a fit of at least 4 bits per weight, larger models first. A projection, not a result.
        self.assertEqual([entry['id'] for entry in metadata['shortlist']], [
            'qwen35-35b-moe-q4_k_m', 'laguna-xs21-q4_1', 'deepseek-r1-32b-q4_k_m', 'nemotron-nano-30b-q4_k_s', 'qwen38-27b-ud-q6_k',
            'gemma3-27b-q4_1', 'gemma4-26b-moe-q5_k_l', 'mistral-small31-q6_k_l', 'phi4-reasoning-plus-q8_0'])
        rows = self.rows(self.path / 'out')
        self.assertEqual(len(rows), 430)
        self.assertTrue(all(r['vram_required_gib'] <= r['vram_available_gib'] for r in rows if r['fits']))
        self.assertFalse(any(r['synthetic'] for r in rows))
        removed = set()
        self.assertEqual(sanitize(metadata, removed), metadata)      # also: no key named host
        self.assertEqual(removed, set())
        with patch('llm_eval.telemetry.host_snapshot', return_value={'gpus': [], 'psutil_available': False}):      # no nvidia-smi, no psutil
            fit.execute(job, self.path / 'bare', ROOT)
        self.assertEqual(read_json(self.path / 'bare/metadata.json')['observed'], {'gpus': [], 'ram_total_gib': None, 'logical_cpus': None})

    def test_a_projection_in_which_nothing_fits_still_succeeds(self):
        result = fit.execute(self.job(policy={'gpu_baseline_gib': 22}), self.path / 'out', ROOT)      # no VRAM left after reserve and baseline
        self.assertEqual(result, {'status': 'succeeded', 'result_path': '.', 'benchmark': 'fit-projection', 'candidates': 5, 'fits': 0})
        metadata = read_json(self.path / 'out/metadata.json')
        self.assertEqual((metadata['counts']['fits'], metadata['counts']['exceeds-vram'], metadata['shortlist']), (0, 5, []))
        self.assertIn('No candidate fits every limit at or above the minimum bits per weight.', (self.path / 'out/fit-projection.md').read_text(encoding='utf-8'))
        self.assertTrue(all(r['rank'] is None and not r['model_best'] for r in self.rows(self.path / 'out')))

    def test_other_limits_reach_the_rows(self):
        fit.execute(self.job(policy={'threads': 32}), self.path / 'cpu', ROOT)
        self.assertEqual(read_json(self.path / 'cpu/metadata.json')['counts'], {'fits': 0, 'exceeds-vram': 1, 'exceeds-ram': 0, 'exceeds-disk': 0,
                                                                              'exceeds-cpu': 4, 'exceeds-context': 0})
        fit.execute(self.job(disk_free_gib=30), self.path / 'disk', ROOT)      # two copies and 10 GiB of headroom: at most 10 GiB of weights
        self.assertEqual({r['task_id']: r['category'] for r in self.rows(self.path / 'disk')}, {
            'fixture-large-30b-q3_k_s': 'exceeds-disk', 'fixture-large-30b-q4_k_m': 'exceeds-disk', 'fixture-large-30b-q8_0': 'exceeds-vram',
            'fixture-small-7b-q4_k_m': 'fits', 'fixture-small-7b-q8_0': 'fits'})
        fit.execute(self.job(context_tokens=65536), self.path / 'context', ROOT)      # above the 32768 tokens the small model was trained for
        self.assertEqual({r['task_id']: r['limits'] for r in self.rows(self.path / 'context')}, {
            'fixture-large-30b-q3_k_s': ['vram'], 'fixture-large-30b-q4_k_m': ['vram'], 'fixture-large-30b-q8_0': ['vram'],
            'fixture-small-7b-q4_k_m': ['context'], 'fixture-small-7b-q8_0': ['context']})
        wsl = self.job(policy={'host_ram_overhead_gib': 48})
        wsl['hardware']['os_id'] = 'windows-11-wsl2-ubuntu-26.04'      # the profile's RAM budget is 46 GiB in the WSL guest, 52 GiB natively
        fit.execute(wsl, self.path / 'wsl', ROOT)
        self.assertEqual(read_json(self.path / 'wsl/metadata.json')['counts']['exceeds-ram'], 4)
        fit.execute(self.job(policy={'host_ram_overhead_gib': 48}), self.path / 'native', ROOT)
        self.assertEqual(read_json(self.path / 'native/metadata.json')['counts']['exceeds-ram'], 0)

    def test_execute_validates_again(self):
        with self.assertRaisesRegex(ValueError, r'context_tokens must be in \[512, 1048576\]'):
            fit.execute(self.job(context_tokens=1), self.path / 'out', ROOT)
        with self.assertRaisesRegex(ValueError, 'Unsupported hardware-fit mode'):
            fit.execute({**self.job(), 'mode': 'live'}, self.path / 'out', ROOT)
        self.assertEqual(list((self.path / 'out').iterdir()), [])


class Fixture(BaseHTTPRequestHandler):
    """A loopback stand-in for an Ollama server: a fixed streamed answer and a scripted reply to /api/ps."""
    protocol_version = 'HTTP/1.1'
    posts = gets = 0
    ps = {'models': [{'name': 'fit:locked', 'model': 'fit:locked', 'size': 17_500_000_000, 'size_vram': 17_500_000_000}]}
    ps_status = 200

    def log_message(self, *args):
        pass

    def do_POST(self):
        self.rfile.read(int(self.headers['Content-Length']))
        type(self).posts += 1
        events = [{'message': {'content': '42'}}, {'done': True, 'done_reason': 'stop', 'prompt_eval_count': 12, 'eval_count': 4,
                                                   'eval_duration': 2_000_000_000, 'prompt_eval_duration': 1_000_000_000, 'load_duration': 0}]
        self.send_response(200)
        self.send_header('Content-Type', 'application/x-ndjson')
        self.send_header('Connection', 'close')
        self.end_headers()
        self.wfile.write('\n'.join(json.dumps(e) for e in events).encode() + b'\n')
        self.wfile.flush()
        self.close_connection = True

    def do_GET(self):
        type(self).gets += 1
        body = self.ps if isinstance(self.ps, bytes) else json.dumps(self.ps).encode()
        self.send_response(self.ps_status if self.path == '/api/ps' else 404)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Connection', 'close')
        self.end_headers()
        self.wfile.write(body)
        self.close_connection = True


class MeasuredRunTests(MeasuredCase):
    def setUp(self):
        super().setUp()
        self.handler = type('PerTestFixture', (Fixture,), {})
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), self.handler)
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.endpoint = f'http://127.0.0.1:{self.server.server_port}/api/chat'

    def job(self, case):
        return {'mode': 'measured', 'hardware': dict(RAIDER), 'parameters': case}

    def real_case(self, weight_bytes=16 * GIB, config=None, **changes):
        """A case that passes the real-run checks: a lock of the given weight and exact provenance values."""
        self.locked = self.lock(weight_bytes)
        values = {'endpoint': self.endpoint, 'served_model': 'fit:locked', 'backend_version': '0.40.17', 'tokenizer_revision': 'fixture-revision',
                  'chat_template_sha256': 'c' * 64, 'placement_notes': 'every layer requested on the GPU, 16 threads',
                  'hardware_attestation': {'power': 'fixture'}, **(config or {})}
        return self.case(self.config(**values), **changes)

    def run_real(self, case, used=(1000.0, 18500.0), log=LOG_FULL, statuses=('completed',), failure=None, readings=None, out='attempt', rows=None):
        """Execute a real measured job with scripted GPU readings (before, while loaded), a scripted backend and a scripted runner.

        `readings` replaces the one-card readings: the rows of every reading, or a function of whether the model is loaded."""
        self.events, self.out, loaded, runs = [], self.path / out, [], []

        def snapshot():
            self.events.append('reading')
            if readings is not None:
                return readings(bool(loaded)) if callable(readings) else readings
            return [{'index': '0', 'name': GPU_NAME, 'driver_version': '999.99', 'total_mib': 24463.0, 'used_mib': used[1] if loaded else used[0],
                     'utilization_pct': 0.0, 'power_w': None, 'temperature_c': None, 'sm_clock_mhz': None}]

        @contextlib.contextmanager
        def backend(config, state, workdir):
            self.events.append('backend start')
            workdir.mkdir(parents=True)
            (workdir / 'backend.log').write_text(log, encoding='utf-8')
            if failure:
                raise failure
            loaded.append(True)
            try:
                yield
            finally:
                loaded.clear()
                self.events.append('backend stop')

        def run(config_path, root, output, synthetic=False):
            self.events.append('run')
            status = statuses[len(runs)]
            runs.append((read_json(config_path), synthetic))
            if not isinstance(status, str):
                raise status
            write_json(Path(output) / f'run-{len(runs)}' / 'metadata.json', {'status': status})
            request_rows = rows if rows is not None else [
                {'status': 'ok' if status == 'completed' else 'error', 'warmup': False, 'prompt_tokens': 30, 'completion_tokens': 2}]
            if status != 'skipped':
                (Path(output) / f'run-{len(runs)}' / 'requests.jsonl').write_text(
                    ''.join(json.dumps(r) + '\n' for r in request_rows), encoding='utf-8')
            return Path(output) / f'run-{len(runs)}'
        host = {'psutil_available': True, 'gpus': [{'name': GPU_NAME}], 'ac_connected': True}
        self.runs = runs
        with patch('llm_eval.telemetry.gpu_snapshot', side_effect=snapshot), patch('llm_eval.launch.managed_backend', side_effect=backend) as self.launched, \
                patch('llm_eval.runner.run', side_effect=run) as self.ran, patch('llm_eval.runner.environment_kind', return_value=RAIDER['os_id']), \
                patch('llm_eval.runner.host_snapshot', return_value=host), \
                patch('llm_eval.artifacts.verify_artifact', return_value=self.locked['weight_bytes']) as self.verified:
            return fit.execute(self.job(case), self.out, ROOT)

    def evidence(self, *keys):
        record = read_json(self.out / 'fit/metadata.json')
        return {k: record[k] for k in keys} if keys else record

    def test_fixture_run_against_a_loopback_server(self):
        config = self.config(endpoint=self.endpoint, served_model='fixture', repeats=1, warmups=0)
        case = self.case(config, server_mode='external', synthetic=True, categories=['math', 'coding'])
        planned = copy.deepcopy(case)
        with patch('llm_eval.launch.managed_backend', side_effect=AssertionError('a fixture run starts no backend')):
            result = fit.execute(self.job(case), self.path / 'attempt', ROOT)
        self.assertEqual(result, {'status': 'succeeded', 'result_path': 'measurements', 'benchmark': 'category-smoke'})
        self.assertEqual((self.handler.posts, self.handler.gets), (6, 0))      # two category suites of three tasks, one request each
        out = self.path / 'attempt'
        self.assertEqual(sorted(p.name for p in out.iterdir()), ['fit', 'measurements', 'resolved-run-0.json', 'resolved-run-1.json'])
        self.assertEqual([Path(read_json(out / f'resolved-run-{i}.json')['suite']) for i in range(2)],
                         [ROOT / 'workloads/categories/math.json', ROOT / 'workloads/categories/coding.json'])
        runs = [read_json(run / 'metadata.json') for run in (out / 'measurements').iterdir()]
        self.assertEqual(sorted((m['category'], m['status'], m['synthetic'], m['measured_requests']) for m in runs),
                         [('coding', 'completed', True, 3), ('math', 'completed', True, 3)])
        self.out = out
        self.assertEqual(self.evidence('experiment', 'record', 'schema_version', 'synthetic', 'verdict', 'reason', 'requested', 'evidence_basis', 'peak_used_mib'), {
            'experiment': 'hardware-fit', 'record': 'fit-evidence', 'schema_version': 1, 'synthetic': True, 'verdict': 'not_assessed', 'reason': None,
            'requested': {'platform': 'ollama', 'gpu_layers': 999, 'gpu_offload': None, 'context_tokens': 8192, 'threads': 16},
            'evidence_basis': [], 'peak_used_mib': None})
        self.assertEqual([p.name for p in (out / 'fit').iterdir()], ['metadata.json'])      # no telemetry of its own
        self.assertEqual(case, planned)      # the planned parameters are not changed by the run

    def test_a_run_inside_vram_succeeds_with_its_evidence(self):
        case = self.real_case()
        result = self.run_real(case)
        self.assertEqual(result, {'status': 'succeeded', 'result_path': 'measurements', 'benchmark': 'category-smoke'})
        self.verified.assert_called_once_with(case['config']['artifact_root'], self.locked, False, 24)
        self.assertEqual(self.launched.call_args.args[2], self.out / 'backend')
        self.assertEqual((self.launched.call_count, [(r[0]['suite'], r[1]) for r in self.runs]), (1, [(case['config']['suite'], False)]))
        # Readings: the baseline and the sampler's first before the backend starts, one while it holds the model, the last after it stopped.
        start, stop = self.events.index('backend start'), self.events.index('backend stop')
        self.assertGreaterEqual(self.events[:start].count('reading'), 2)
        self.assertIn('reading', self.events[self.events.index('run'):stop])
        self.assertEqual(self.events[-1], 'reading')
        record = self.evidence()
        self.assertEqual({k: record[k] for k in (
            'experiment', 'record', 'synthetic', 'verdict', 'reason', 'weight_bytes', 'weight_mib', 'gpu_name', 'total_mib', 'reserve_mib', 'baseline_used_mib',
            'peak_used_mib', 'gpu_rise_mib', 'capacity_ok', 'rise_ok', 'placement', 'layers_offloaded', 'layers_total', 'model_layers', 'model_loads',
            'partial_loads', 'gpu_model_buffer_mib', 'cpu_kv_buffer_mib', 'ollama_size_bytes', 'ollama_size_vram_bytes', 'error_type', 'evidence_basis',
            'min_gpu_weight_fraction', 'require_layer_evidence')}, {
            'experiment': 'hardware-fit', 'record': 'fit-evidence', 'synthetic': False, 'verdict': 'in_vram', 'reason': None, 'weight_bytes': 16 * GIB,
            'weight_mib': 16384.0, 'gpu_name': GPU_NAME, 'total_mib': 24463.0, 'reserve_mib': 2048, 'baseline_used_mib': 1000.0, 'peak_used_mib': 18500.0,
            'gpu_rise_mib': 17500.0, 'capacity_ok': True, 'rise_ok': True, 'placement': 'all_layers_on_gpu', 'layers_offloaded': 63, 'layers_total': 63,
            'model_layers': 62, 'model_loads': 1, 'partial_loads': 0, 'gpu_model_buffer_mib': 15480.25, 'cpu_kv_buffer_mib': None,
            'ollama_size_bytes': 17_500_000_000,
            'ollama_size_vram_bytes': 17_500_000_000, 'error_type': None, 'evidence_basis': ['gpu_telemetry', 'backend_log', 'ollama_ps'],
            'min_gpu_weight_fraction': 0.8, 'require_layer_evidence': False})
        self.assertEqual(record['fit_class'], 'backend_confirmed')
        self.assertEqual((record['headroom_mib'], record['sampler_interval_s']), (24463 - 2048 - 18500, 1.0))
        self.assertEqual(record['prompt_usage']['prompt_tokens_min'], 30)
        self.assertEqual(self.handler.gets, 1)
        samples = read_json(self.out / 'fit/telemetry.json')
        self.assertTrue(isinstance(samples, list) and all(isinstance(s, dict) and 'gpus' in s for s in samples))
        self.assertEqual(max(g['used_mib'] for s in samples for g in s['gpus']), 18500.0)
        # The generic report exports both evidence files unchanged, the bundle passes the publication checks, and the index reads the peak.
        report = self.report({'mode': 'measured', 'hardware': dict(RAIDER), 'parameters': case}, self.out)
        self.assertTrue(publish_report(report, ROOT, dry_run=True)['dry_run'])
        records = raw_records(report)
        self.assertEqual(next(r['data'] for r in records if r['source_file'] == 'fit/metadata.json'), record)
        self.assertEqual([r['data'] for r in records if r['source_file'] == 'fit/telemetry.json'], samples)
        supplement, markdown = fit.report_supplement(records + [{**r, 'latest_attempt': False} for r in records])
        self.assertEqual(len(supplement['jobs']), 1)
        self.assertIn('backend confirmed', markdown)
        self.assertIn('30–30', markdown)
        self.assertEqual(supplement['by_runtime'][0]['attempts'], 1)
        bundle = report / 'bundle' / read_json(report / 'publication.json')['report_path']
        self.assertEqual(read_json(bundle / 'hardware-fit-summary.json'), supplement)
        self.assertIn('backend confirmed', (bundle / 'README.md').read_text(encoding='utf-8'))
        (indexed,) = collect(report / 'bundle')
        self.assertEqual((indexed['experiment'], indexed['harness'], indexed['model'], indexed['status'], indexed['synthetic'], indexed['gpu_gib']),
                         ('hardware-fit', 'ollama', 'qwen38-27b-q4_k_m', 'succeeded', False, 18500.0 / 1024))

    def test_weights_above_the_free_vram_fail_before_any_launch(self):
        result = self.run_real(self.real_case(), used=(20000.0, 20000.0))      # 24463 - 2048 - 20000 MiB is less than 16 GiB of weights
        self.assertEqual(result, {'status': 'failed', 'reason': 'artifact_exceeds_free_vram'})
        self.launched.assert_not_called()
        self.ran.assert_not_called()
        self.assertEqual(self.events, ['reading'])
        self.assertEqual(self.evidence('verdict', 'reason', 'weight_mib', 'total_mib', 'reserve_mib', 'baseline_used_mib', 'peak_used_mib', 'evidence_basis'), {
            'verdict': 'not_in_vram', 'reason': 'artifact_exceeds_free_vram', 'weight_mib': 16384.0, 'total_mib': 24463.0, 'reserve_mib': 2048,
            'baseline_used_mib': 20000.0, 'peak_used_mib': None, 'evidence_basis': []})
        self.assertEqual([p.relative_to(self.out).as_posix() for p in sorted(self.out.rglob('*'))], ['fit', 'fit/metadata.json'])
        # 21415 MiB are free after the reserve and the 1000 MiB baseline: weights of exactly that size are still launched.
        self.assertEqual(self.run_real(self.real_case(21415 * 2 ** 20), used=(1000.0, 22400.0), out='boundary')['status'], 'succeeded')
        # The reserve counts before the launch too: 24463 - 6500 MiB would hold the 16384 MiB of weights, 24463 - 2048 - 6500 MiB do not.
        self.assertEqual(self.run_real(self.real_case(), used=(6500.0, 6500.0), out='reserve'), {'status': 'failed', 'reason': 'artifact_exceeds_free_vram'})
        self.launched.assert_not_called()

    def test_the_card_the_launch_selects_is_the_one_judged(self):
        def cards(loaded):      # two cards of the profile's model: another job holds 20000 MiB on the first, the launch selects the second
            return [{'index': '0', 'name': GPU_NAME, 'total_mib': 24463.0, 'used_mib': 20000.0},
                    {'index': '1', 'name': GPU_NAME, 'total_mib': 24463.0, 'used_mib': 18500.0 if loaded else 1000.0}]
        second = {'launch': {**self.config()['launch'], 'gpu': 1}}
        self.assertEqual(self.run_real(self.real_case(config=second), readings=cards)['status'], 'succeeded')
        self.assertEqual(self.evidence('verdict', 'baseline_used_mib', 'peak_used_mib', 'gpu_rise_mib'),
                         {'verdict': 'in_vram', 'baseline_used_mib': 1000.0, 'peak_used_mib': 18500.0, 'gpu_rise_mib': 17500.0})
        # Without launch.gpu the engine sees the first card only, and that card has no room for the weights.
        self.assertEqual(self.run_real(self.real_case(), readings=cards, out='first'), {'status': 'failed', 'reason': 'artifact_exceeds_free_vram'})
        self.assertEqual(self.evidence('baseline_used_mib'), {'baseline_used_mib': 20000.0})
        self.launched.assert_not_called()

    def test_the_rise_threshold_of_the_case_is_used(self):
        # VRAM use rises by 10000 MiB for 16384 MiB of weights: below the default share of 0.8, above a declared share of 0.5.
        self.assertEqual(self.run_real(self.real_case(), used=(1000.0, 11000.0))['reason'], 'gpu_use_below_weights')
        result = self.run_real(self.real_case(fit={'min_gpu_weight_fraction': 0.5}), used=(1000.0, 11000.0), out='declared')
        self.assertEqual(result['status'], 'succeeded')
        self.assertEqual(self.evidence('verdict', 'rise_ok', 'gpu_rise_mib', 'min_gpu_weight_fraction'),
                         {'verdict': 'in_vram', 'rise_ok': True, 'gpu_rise_mib': 10000.0, 'min_gpu_weight_fraction': 0.5})

    def test_no_gpu_reading_fails_before_any_launch(self):
        other = [{'index': '0', 'name': 'NVIDIA GeForce RTX 4090', 'total_mib': 24564.0, 'used_mib': 500.0}]
        unread = [{'index': '0', 'name': GPU_NAME, 'total_mib': 24463.0, 'used_mib': None}]
        elsewhere = [*other, {'index': '1', 'name': GPU_NAME, 'total_mib': 24463.0, 'used_mib': 1000.0}]      # the launch selects index 0
        for name, readings in (('nvidia-smi gave nothing', []), ('another GPU', other), ('memory not reported', unread),
                               ('the profile GPU at another index', elsewhere)):
            with self.subTest(name):
                result = self.run_real(self.real_case(), readings=readings, out=name.replace(' ', '-'))
                self.assertEqual(result, {'status': 'failed', 'reason': 'gpu_memory_unobserved'})
                self.launched.assert_not_called()
                self.assertEqual(self.evidence('verdict', 'reason', 'baseline_used_mib'), {'verdict': 'not_assessed', 'reason': 'gpu_memory_unobserved',
                                                                                         'baseline_used_mib': None})

    def test_a_run_that_left_vram_fails_with_the_reason(self):
        cases = [('layers on the CPU', dict(log=LOG_PARTIAL), 'layers_on_cpu', 'layers_on_cpu'),
                 ('a reload after a load that left layers on the CPU', dict(log=LOG_OLLAMA), 'layers_on_cpu', 'layers_on_cpu'),
                 ('peak above total minus reserve', dict(used=(1000.0, 22500.0)), 'all_layers_on_gpu', 'vram_reserve_exceeded'),
                 ('memory use did not rise', dict(used=(1000.0, 1200.0)), 'all_layers_on_gpu', 'gpu_use_below_weights'),
                 ('ollama reports part in RAM', dict(log=''), 'reported_partly_in_ram', 'layers_on_cpu')]
        self.handler.ps = {'models': [{'name': 'fit:locked', 'size': 17_500_000_000, 'size_vram': 9_000_000_000}]}
        for index, (name, changes, placement, reason) in enumerate(cases):
            with self.subTest(name):
                result = self.run_real(self.real_case(), out=f'attempt-{index}', **changes)
                self.assertEqual(result, {'status': 'failed', 'reason': reason, 'result_path': 'measurements', 'benchmark': 'category-smoke'})
                self.assertEqual(self.evidence('verdict', 'reason', 'placement', 'error_type'),
                                 {'verdict': 'not_assessed' if reason == 'gpu_use_below_weights' else 'not_in_vram',
                                  'reason': reason, 'placement': placement, 'error_type': None})
                self.assertEqual(self.launched.call_count, 1)      # the run happened: the verdict is drawn afterwards
        self.assertEqual(self.evidence('evidence_basis', 'layers_offloaded', 'ollama_size_vram_bytes'),
                         {'evidence_basis': ['gpu_telemetry', 'ollama_ps'], 'layers_offloaded': None, 'ollama_size_vram_bytes': 9_000_000_000})

    def test_runner_statuses_decide_before_the_verdict(self):
        case = self.real_case(categories=['reasoning', 'math'])
        result = self.run_real(case, statuses=('completed', 'completed_with_errors'))
        self.assertEqual(result, {'status': 'failed', 'reason': 'requests_incomplete', 'result_path': 'measurements', 'benchmark': 'category-smoke'})
        self.assertEqual([Path(r[0]['suite']).name for r in self.runs], ['reasoning.json', 'math.json'])
        self.assertEqual(self.launched.call_count, 1)      # one backend, one workdir, for every suite of the job
        self.assertEqual(self.evidence('fit_class', 'failure_stage'), {'fit_class': 'inconclusive', 'failure_stage': 'request'})
        self.assertEqual(self.run_real(case, statuses=('skipped', 'skipped'), out='skipped')['status'], 'skipped')
        # An incomplete suite can retain its raw layer readings without establishing a fit verdict.
        result = self.run_real(case, statuses=('completed', 'completed_with_errors'), log=LOG_PARTIAL, out='both')
        self.assertEqual(result['reason'], 'requests_incomplete')
        self.assertEqual(self.evidence('verdict', 'partial_loads'), {'verdict': 'not_assessed', 'partial_loads': 1})
        self.assertEqual(self.run_real(case, statuses=('skipped', 'skipped'), log=LOG_PARTIAL, out='skipped-partial')['status'], 'skipped')

    def test_lmstudio_rests_on_telemetry_unless_layer_evidence_is_required(self):
        config = dict(platform='lmstudio', protocol='openai', endpoint=self.endpoint.replace('/api/chat', '/v1/chat/completions'),
                      launch={'model_file': 'm.gguf', 'gpu_offload': 'max'})
        identity = {'harness': 'lmstudio', 'model': 'qwen38-27b-q4_k_m'}
        result = self.run_real(self.real_case(config=config, identity=identity), log=LOG_LMSTUDIO)
        self.assertEqual(result['status'], 'succeeded')
        self.assertEqual(self.evidence('verdict', 'placement', 'evidence_basis', 'ollama_size_bytes', 'requested'), {
            'verdict': 'in_vram', 'placement': 'unobserved', 'evidence_basis': ['gpu_telemetry'], 'ollama_size_bytes': None,
            'requested': {'platform': 'lmstudio', 'gpu_layers': None, 'gpu_offload': 'max', 'context_tokens': 8192, 'threads': None}})
        self.assertEqual(self.evidence('fit_class'), {'fit_class': 'telemetry_consistent'})
        self.assertEqual(self.handler.gets, 0)      # /api/ps is asked of Ollama only
        strict = self.real_case(config=config, identity=identity, fit={'require_layer_evidence': True})
        self.assertEqual(self.run_real(strict, log=LOG_LMSTUDIO, out='strict'),
                         {'status': 'failed', 'reason': 'placement_unobserved', 'result_path': 'measurements', 'benchmark': 'category-smoke'})
        self.assertEqual(self.evidence('verdict', 'require_layer_evidence'), {'verdict': 'not_assessed', 'require_layer_evidence': True})

    def test_an_unanswered_ollama_status_is_recorded_as_null(self):
        port = self.server.server_port
        self.assertEqual(measured.ollama_ps(port), Fixture.ps)
        for name, change in (('http error', {'ps_status': 500}), ('not json', {'ps': b'<html>busy</html>'}), ('not an object', {'ps': ['fit:locked']}),
                             ('another model', {'ps': {'models': [{'name': 'other:latest', 'size': 1, 'size_vram': 1}]}})):
            with self.subTest(name):
                for key, value in {'ps_status': 200, **change}.items():
                    setattr(self.handler, key, value)
                result = self.run_real(self.real_case(), out=name.replace(' ', '-'))
                self.assertEqual(result['status'], 'succeeded')      # the layer line of the log decides
                self.assertEqual(self.evidence('ollama_size_bytes', 'ollama_size_vram_bytes', 'evidence_basis'),
                                 {'ollama_size_bytes': None, 'ollama_size_vram_bytes': None, 'evidence_basis': ['gpu_telemetry', 'backend_log']})
        self.handler.ps_status = 500
        self.assertIsNone(measured.ollama_ps(port))
        self.handler.ps_status, self.handler.ps = 200, b'{"models": '
        self.assertIsNone(measured.ollama_ps(port))

    def test_explicit_gpu_allocation_failure_is_distinct_from_loader_failure(self):
        log = 'ggml_backend_cuda_buffer_type_alloc_buffer: allocating 17000.00 MiB on device 0: cudaMalloc failed: out of memory\n'
        with self.assertRaisesRegex(RuntimeError, 'Backend exited during startup'):
            self.run_real(self.real_case(), failure=RuntimeError('Backend exited during startup; inspect its local log'), log=log)
        self.ran.assert_not_called()
        self.assertEqual(self.evidence('verdict', 'reason', 'error_type', 'baseline_used_mib', 'peak_used_mib', 'placement', 'evidence_basis'), {
            'verdict': 'not_in_vram', 'reason': 'gpu_out_of_memory', 'error_type': 'RuntimeError', 'baseline_used_mib': 1000.0, 'peak_used_mib': 1000.0,
            'placement': None, 'evidence_basis': ['gpu_telemetry', 'backend_log']})
        self.assertIsInstance(read_json(self.out / 'fit/telemetry.json'), list)

    def test_loader_diagnostic_precedes_low_gpu_rise(self):
        cause = "llama_model_load: error loading model: unknown model architecture: 'inkling2_loop'"
        failed = self.run_real(self.real_case(), log=cause, statuses=('completed_with_errors',), used=(1000, 1200))
        self.assertEqual((failed['status'], failed['reason']), ('failed', 'unsupported_model_architecture'))
        self.assertEqual(self.evidence('verdict', 'fit_class', 'failure_stage', 'rise_ok'), {
            'verdict': 'not_assessed', 'fit_class': 'loader_failure', 'failure_stage': 'model_load', 'rise_ok': None})
        # Without a diagnostic, identical measurements only show an unsuccessful request.
        self.run_real(self.real_case(), log='', statuses=('completed_with_errors',), used=(1000, 1200), out='unknown')
        self.assertEqual(self.evidence('fit_class', 'failure_stage'), {'fit_class': 'inconclusive', 'failure_stage': 'request'})

    def test_context_probe_requires_each_measured_request_to_exercise_the_target(self):
        probe = {'target_prompt_tokens': 4096, 'tolerance_tokens': 32}
        case = self.real_case(context_probe=probe)
        row = {'warmup': False, 'status': 'ok', 'prompt_tokens': 4080, 'completion_tokens': 15}
        warmup = {**row, 'warmup': True, 'prompt_tokens': 7}
        success = self.run_real(case, rows=[warmup, row, {**row, 'prompt_tokens': 4128}])
        self.assertEqual(success['status'], 'succeeded')
        usage = self.evidence()['prompt_usage']
        self.assertEqual((usage['configured_context_tokens'], usage['prompt_tokens_min'], usage['prompt_tokens_max'],
                          usage['total_tokens_max'], usage['probe']['requests_in_band']), (8192, 4080, 4128, 4143, 2))
        for i, bad in enumerate(({'prompt_tokens': 56}, {'prompt_tokens': None}, {'completion_tokens': None},
                                 {'completion_tokens': 0}, {'completion_tokens': 257})):
            fail = self.run_real(case, rows=[row, {**row, **bad}], out=f'short-{i}')
            self.assertEqual(fail, {'status': 'failed', 'reason': 'context_target_unverified', 'result_path': 'measurements',
                                    'benchmark': 'fit-context-boundary'})
            self.assertFalse(self.evidence()['prompt_usage']['probe']['passed'])

    def test_an_interrupt_stops_the_backend_and_keeps_the_evidence(self):
        with self.assertRaises(KeyboardInterrupt):
            self.run_real(self.real_case(), statuses=(KeyboardInterrupt(),), out='interrupted')
        stop = self.events.index('backend stop')      # the backend's context manager ran before the interrupt left execute
        self.assertEqual(self.events[stop + 1:], ['reading'])
        self.assertEqual(self.evidence('verdict', 'reason', 'error_type', 'layers_offloaded'),
                         {'verdict': 'not_assessed', 'reason': 'run_incomplete', 'error_type': 'KeyboardInterrupt', 'layers_offloaded': 63})


class ContextStudyTests(MeasuredCase):
    def test_prepare_compiles_all_tiers_and_freezes_each_prompt(self):
        inventory = ROOT / 'configs/targets/local.example.json'
        source = X / 'cases/measured-ollama.json'
        directory = self.path / 'boundary'
        path = study.prepare(source, inventory, 'raider-ubuntu', directory)
        jobs = compile_campaign(path, ROOT)['jobs']
        self.assertEqual([j['case_id'] for j in jobs], ['prompt-2048', 'prompt-4096', 'prompt-8000'])
        previous = None
        for job in jobs:
            params = job['parameters']
            target = params['context_probe']['target_prompt_tokens']
            self.assertEqual(params['config']['context_tokens'], target + 64 + 128)
            self.assertEqual((params['config']['warmups'], params['config']['repeats']), (0, 1))
            self.assertEqual(job['depends_on'], [previous] if previous else [])
            previous = job['job_id']
            suite = Path(params['config']['suite'])
            self.assertIn({'path': str(suite), 'sha256': sha256_file(suite)}, job['input_files'])
            self.assertEqual(read_json(suite)['tasks'][0]['messages'][0]['content'].count(' blue'), target - 32)
        with self.assertRaises(FileExistsError):
            study.prepare(source, inventory, 'raider-ubuntu', directory)
        with self.assertRaisesRegex(ValueError, 'reserve the entire output'):
            fit.validate(self.case(context_probe={'target_prompt_tokens': 8000, 'tolerance_tokens': 64}), ROOT, 'measured')

    def test_frozen_prediction_and_false_fit_counts_use_matched_artifacts_and_assessed_runs(self):
        source = projection.load_candidates(REAL)
        candidate = next(c for c in source['candidates'] if c['id'] == 'qwen38-27b-ud-q4_k_xl')
        spec = {'data': str(REAL), 'candidate_id': candidate['id'], 'policy': {'gpu_baseline_gib': 1.5}}
        profile = read_json(ROOT / 'configs/hardware/msi-raider-18-hx-ai.json')
        lock = {'files': [{**f, 'weight': True} for f in candidate['files']]}
        predicted = study.frozen_prediction(spec, self.config(), profile, lock)
        self.assertTrue(predicted['predicted_vram_fit'])
        lock['files'][0]['sha256'] = 'd' * 64
        with self.assertRaisesRegex(ValueError, 'hashes and sizes differ'):
            study.frozen_prediction(spec, self.config(), profile, lock)
        raw = self.path / 'measurements.jsonl.gz'
        with gzip.open(raw, 'wt', encoding='utf-8') as out:
            for i, kind in enumerate(('backend_confirmed', 'capacity_failure', 'placement_failure', 'loader_failure', 'telemetry_consistent')):
                record = {'record': 'fit-evidence', 'fit_class': kind, 'prediction': dict(predicted), 'headroom_mib': predicted['predicted_headroom_mib'] - 100,
                          'placement': 'all_layers_on_gpu', 'requested': {'platform': 'ollama'}, 'backend_version': '1.0'}
                study.compare_prediction(record)
                out.write(json.dumps({'source_file': 'fit/metadata.json', 'latest_attempt': True, 'job_id': str(i),
                                      'attempt_id': str(i), 'data': record}) + '\n')
        stats, = study.summarize([raw, raw])
        self.assertEqual((stats['attempts'], stats['matched_predictions'], stats['assessed_predicted_fits'], stats['false_fits'],
                          stats['mean_headroom_error_mib'], stats['mean_absolute_headroom_error_mib']), (5, 5, 3, 2, -100, 100))

    def test_cache_types_and_compute_attribution(self):
        self.assertEqual(evidence.cache_types(LOG_PARTIAL), [('f16', 'f16')])
        process = SimpleNamespace(children=lambda recursive: [SimpleNamespace(pid=11)])
        with patch('llm_eval.telemetry.psutil', SimpleNamespace(Process=lambda _: process, Error=ValueError)):
            for csv, expected in [('10, 1500\n11, 10240\n12, 30', 30), ('11, 8000', 0),
                                  ('2001, 1700', None), ('10, [N/A]', None)]:
                with self.subTest(csv), patch('llm_eval.common.command', return_value=csv):
                    self.assertEqual(evidence.other_compute_memory('0', 10), expected)


class PreflightTests(TempCase):
    def handle(self, job, gpus=()):
        """The worker's `run` action up to the child process, on a scripted host (pattern: tests/test_legal_workflow.py)."""
        host = {'psutil_available': True, 'gpus': list(gpus), 'ac_connected': True}
        child = patch('subprocess.Popen').start()
        self.addCleanup(patch.stopall)
        child.return_value.pid = os.getpid()
        child.return_value.poll.return_value = 0
        child.return_value.returncode = 0
        job = {**job, 'target': {'transport': 'local', 'physical_host_id': 'hardware-fit-test-host'}}
        with patch.object(worker, 'revision', return_value='rev'), patch.object(worker, 'environment_kind', return_value=job['hardware']['os_id']), \
                patch.object(worker, 'reserve'), patch('subprocess.run', return_value=subprocess.CompletedProcess([], 0)), \
                patch('llm_eval.runner.host_snapshot', return_value=host):
            return worker.handle({'action': 'run', 'job': job, 'root': str(ROOT), 'output': str(self.path / 'out' / job['job_id']),
                                  'owner': 'test-owner', 'code_revision': 'rev'})

    def test_a_real_projection_needs_no_gpu_and_a_measured_run_needs_the_profile_gpu(self):
        (projected,) = compile_campaign(ROOT / 'configs/examples/hardware-fit/raider-windows-projection.json', ROOT)['jobs']
        (run,) = self.plan('measured', [self.template()])['jobs']      # planned first: `handle` replaces the process launcher
        self.assertNotIn('synthetic', projected['parameters'])
        # The scripted host has no GPU. Preflight passes and the (scripted) child is started; it writes no result.
        self.assertEqual(self.handle(projected)['error_type'], 'WorkerExited')
        with self.assertRaisesRegex(ValueError, 'Expected hardware-profile NVIDIA GPU was not detected'):
            self.handle(run)
        self.assertEqual(self.handle(run, gpus=[{'name': GPU_NAME}])['error_type'], 'WorkerExited')


class CampaignTests(TempCase):
    SMOKE_CAMPAIGN = ROOT / 'campaigns/hardware-fit-smoke.json'
    RAIDER_CAMPAIGN = ROOT / 'configs/examples/hardware-fit/raider-windows-projection.json'

    def test_shipped_campaigns_plan_offline_without_side_effects(self):
        watched = ('experiments/hardware-fit', 'configs/examples/hardware-fit', 'campaigns')
        before = {name: tree(ROOT / name) for name in watched}

        def refuse(*args, **kwargs):
            raise AssertionError('planning opened a socket')
        with patch.object(socket, 'socket', refuse), patch.object(socket, 'create_connection', refuse):
            smoke_plan, raider_plan = compile_campaign(self.SMOKE_CAMPAIGN, ROOT), compile_campaign(self.RAIDER_CAMPAIGN, ROOT)
        (smoke,), (raider,) = smoke_plan['jobs'], raider_plan['jobs']
        self.assertEqual({name: tree(ROOT / name) for name in watched}, before)
        self.assertEqual((smoke['experiment_id'], smoke['mode'], smoke['status'], smoke['case_id'], smoke['hardware_config_id'], smoke['parameters']['synthetic']),
                         ('hardware-fit', 'projection', 'planned', 'projection-smoke', 'raider-ubuntu', True))
        self.assertEqual(Path(smoke['parameters']['data']), SMOKE.resolve())
        self.assertEqual([(Path(f['path']), f['sha256']) for f in smoke['input_files']], [(SMOKE.resolve(), sha256_file(SMOKE))])
        self.assertEqual(smoke_plan['reporting'], {'on_experiment_end': True})
        # The same inventory and hardware configuration as the routing smoke, so both smokes bind the same profile and host.
        routing = compile_campaign(ROOT / 'campaigns/routing-smoke.json', ROOT)['jobs'][0]
        self.assertEqual((smoke['hardware'], smoke['target'], smoke['resources']), (routing['hardware'], routing['target'], routing['resources']))
        self.assertEqual((raider['experiment_id'], raider['mode'], raider['status'], raider['case_id'], raider['hardware_config_id'], raider['hardware']['os_id']),
                         ('hardware-fit', 'projection', 'planned', 'projection-measured-models', 'raider-windows', 'windows-11-native'))
        self.assertNotIn('synthetic', raider['parameters'])
        self.assertEqual(raider['parameters']['identity'], {'harness': 'projection', 'model': 'measured-models-gguf'})
        self.assertEqual((Path(raider['parameters']['data']), Path(raider['parameters']['artifact_root'])), (REAL.resolve(), (ROOT / 'models').resolve()))
        self.assertEqual([Path(f['path']) for f in raider['input_files']], [REAL.resolve()])      # the candidate set is pinned; the directory is not
        self.assertEqual(raider_plan['reporting']['publish']['mode'], 'none')
        self.assertEqual(raider['hardware_profile']['gpu']['vram_gib'], 24)

    def test_readiness_and_setup_follow_the_hooks(self):
        template = self.plan('measured', [self.template()])
        for path, os_id in ((self.SMOKE_CAMPAIGN, 'ubuntu-26.04-native'), (self.RAIDER_CAMPAIGN, 'windows-11-native')):
            selection = readiness.select(readiness.parser().parse_args(['--campaign', str(path)]), ROOT)
            self.assertEqual((selection['os_id'], selection['runtimes'], selection['needs_gpu']), (os_id, {}, False))
            with patch('llm_eval.orchestration.setup.rpc', side_effect=AssertionError('a projection installs nothing')), \
                    patch('llm_eval.orchestration.setup.reserve', side_effect=AssertionError('a projection reserves nothing for setup')):
                self.assertEqual(setup_campaign(compile_campaign(path, ROOT)), 0)
        selection = readiness.select(readiness.parser().parse_args(['--campaign', str(self.path / 'campaign.json')]), ROOT)
        self.assertEqual(([name for name, _ in selection['runtimes']], selection['needs_gpu']), (['ollama'], True))
        calls = []

        def rpc(target, payload, root, timeout=60):
            calls.append((payload['action'], payload.get('platform')))
            return {'status': 'succeeded'}
        with patch('llm_eval.orchestration.setup.rpc', side_effect=rpc), patch('llm_eval.orchestration.setup.reserve'), \
                patch('llm_eval.orchestration.setup.release'), patch('builtins.print'):
            self.assertEqual(setup_campaign(template), 0)
        self.assertIn(('setup', 'ollama'), calls)

    def test_measured_template_plans_and_refuses_to_run_with_placeholders(self):
        (job,) = self.plan('measured', [self.template()])['jobs']
        self.assertEqual((job['status'], job['reason'], job['mode'], job['case_id']), ('planned', None, 'measured', 'measured-ollama'))
        config = job['parameters']['config']
        self.assertEqual((config['platform'], config['model_id'], config['lane'], config['launch']['gpu_layers'], config['hardware_profile'], config['os_id']),
                         ('ollama', 'qwen38-27b', 'control', 999, 'msi-raider-18-hx-ai', 'ubuntu-26.04-native'))
        self.assertEqual(job['parameters']['identity'], {'harness': 'ollama', 'model': 'qwen38-27b-ud-q4_k_xl'})
        # The template's relative paths lead to the checkout's own directories: three levels above the run config.
        self.assertEqual((Path(config['suite']), Path(config['artifact_lock'])),
                         (self.path / 'workloads/smoke.json', self.path / 'artifacts/selected.lock.json'))
        for key in ('served_model', 'backend_version', 'tokenizer_revision', 'chat_template_sha256', 'placement_notes'):
            self.assertIn('REPLACE_WITH_', config[key])
        self.assertIn('REPLACE_WITH_', config['launch']['model_file'])
        with patch('llm_eval.launch.managed_backend', side_effect=AssertionError('a template starts no backend')):
            with self.assertRaisesRegex(ValueError, 'Record an exact backend_version before benchmarking'):
                fit.execute(job, self.path / 'attempt', ROOT)
        # A lock an operator wrote for an artifact above VRAM, as the model-offloading guide describes, skips the job at plan time.
        write_json(self.path / 'artifacts/selected.lock.json', {'weight_bytes': 29047086048, 'precision': 'UD-Q4_K_XL'})
        (skipped,) = self.plan('measured', [self.template()])['jobs']
        self.assertEqual((skipped['status'], skipped['reason']), ('skipped', 'artifact_exceeds_gpu_vram_budget'))

    def test_locked_weights_above_the_vram_budget_are_skipped_at_plan_time(self):
        config = read_json(X / 'runs/ollama.example.json')
        config.update(suite=str(ROOT / 'workloads/smoke.json'), artifact_lock='selected.lock.json')
        write_json(self.path / 'run.json', config)
        case = {'identity': {'harness': 'ollama', 'model': 'qwen38-27b-q8_0'}, 'config': 'run.json', 'server_mode': 'managed'}
        write_json(self.path / 'selected.lock.json', {'weight_bytes': 29047086048, 'precision': 'Q8_0'})      # the Q8_0 artifact of the published offload runs
        (job,) = self.plan('measured', [case])['jobs']
        self.assertEqual((job['status'], job['reason']), ('skipped', 'artifact_exceeds_gpu_vram_budget'))
        write_json(self.path / 'selected.lock.json', {'weight_bytes': 16 * GIB, 'precision': 'Q8_0'})
        (job,) = self.plan('measured', [case])['jobs']
        self.assertEqual((job['status'], job['reason']), ('planned', None))

    def test_smoke_campaign_runs_through_the_real_worker_to_a_publishable_report(self):
        inventory = read_json(ROOT / 'configs/targets/local.example.json')
        inventory['targets']['raider']['lock_root'] = str(self.path / 'worker-locks')      # never the real host reservation
        write_json(self.path / 'inventory.json', inventory)
        campaign = read_json(self.SMOKE_CAMPAIGN)
        campaign['inventory'] = 'inventory.json'
        write_json(self.path / 'campaign.json', campaign)
        plan = compile_campaign(self.path / 'campaign.json', ROOT)
        with patch('llm_eval.orchestration.resources.lock_root', return_value=self.path / 'coordinator-locks'):
            directory = initialize(plan, self.path / 'run')
            self.assertEqual(run_campaign(directory), 0)
            self.assertEqual(run_campaign(directory), 0)      # a resume adds nothing
        state = read_json(directory / 'campaign.json')
        self.assertEqual(state['status'], 'succeeded')
        (job,) = state['jobs'].values()
        (attempt,) = job['attempts']
        self.assertEqual({k: attempt[k] for k in ('status', 'result_path', 'benchmark', 'candidates', 'fits')},
                         {'status': 'succeeded', 'result_path': '.', 'benchmark': 'fit-projection', 'candidates': 5, 'fits': 4})
        out = directory / attempt['output']
        self.assertTrue((out / 'fit-projection.md').is_file())
        (receipt,) = state['reports'].values()
        self.assertEqual(receipt['status'], 'generated')
        report = directory / receipt['report']
        spec, manifest, _ = validate_bundle(report)
        self.assertEqual((manifest['experiment_id'], manifest['status'], manifest['synthetic']), ('hardware-fit', 'complete', True))
        self.assertTrue(publish_report(report, ROOT, dry_run=True)['dry_run'])
        dest = report / 'bundle' / spec['report_path']
        self.assertEqual([(r['category'], r['benchmark'], r['requests'], r['successful_requests'], r['quality_check_n'], r['decision_labelled_n'])
                          for r in read_json(dest / 'summary.json')],
                         [('exceeds-vram', 'fit-projection', 1, 1, 0, 0), ('fits', 'fit-projection', 4, 4, 0, 0)])
        self.assertIn('| projection | smoke | fits | 4 | 0 | unavailable | unavailable | unavailable | unavailable |', (dest / 'README.md').read_text(encoding='utf-8'))
        # Every row and the whole metadata reach the raw archive as written: no key is dropped or rewritten by the report.
        records = raw_records(report)
        self.assertEqual([r['data'] for r in records if r['record_type'] == 'request'],
                         [json.loads(line) for line in (out / 'requests.jsonl').read_text(encoding='utf-8').splitlines()])
        self.assertEqual(next(r['data'] for r in records if r['source_file'] == 'metadata.json'), read_json(out / 'metadata.json'))
        self.assertFalse(any(r['source_file'] == 'fit-projection.md' for r in records))
        (indexed,) = collect(report / 'bundle')
        self.assertEqual((indexed['experiment'], indexed['mode'], indexed['harness'], indexed['model'], indexed['hardware'], indexed['status'],
                          indexed['synthetic'], indexed['requests'], indexed['score']),
                         ('hardware-fit', 'projection', 'projection', 'smoke', 'raider-ubuntu', 'succeeded', True, 5, None))


class ResultsIndexTests(TempCase):
    def bundle(self, publication, created, jobs, summary, synthetic=False):
        """A published bundle as the index reads it (pattern: tests/test_results_index.py)."""
        dest = self.path / 'docs/results/hardware-fit' / publication
        dest.mkdir(parents=True)
        (dest / 'README.md').write_text('# report\n', encoding='utf-8')
        write_json(dest / 'manifest.json', {'experiment_id': 'hardware-fit', 'publication_id': publication, 'campaign_id': 'fixture', 'created_utc': created,
                                            'status': 'complete', 'synthetic': synthetic,
                                            'coverage': [{'job_id': j['job_id'], 'status': j.pop('_status', 'succeeded')} for j in jobs]})
        write_json(dest / 'resolved-config.json', {'jobs': jobs})
        write_json(dest / 'summary.json', summary)

    def test_published_bundles_are_collected_and_only_measured_runs_rank(self):
        def job(job_id, mode, harness, model, **parameters):
            return {'job_id': job_id, 'mode': mode, 'case_id': model, 'hardware_config_id': 'raider-windows', 'hardware': {'os_id': 'windows-11-native'},
                    'parameters': {'identity': {'harness': harness, 'model': model}, **parameters}}

        def row(job_id, category, requests, median=None, rate=None, quality=None):
            return {'job_id': job_id, 'category': category, 'requests': requests, 'errors_or_missing': 0, 'elapsed_s_median': median,
                    'output_tokens_per_wall_second_median': rate, 'quality_pass_rate': quality, 'quality_check_n': requests if quality is not None else 0,
                    'decision_accuracy': None, 'decision_labelled_n': 0}
        config = {'platform': 'ollama', 'model_id': 'qwen38-27b', 'max_output_tokens': 256}
        self.bundle('campaign-a-fit', '2026-11-22T10:00:00+00:00', [job('p1', 'projection', 'projection', 'measured-models-gguf', context_tokens=8192)],
                    [row('p1', 'fits', 218), row('p1', 'exceeds-vram', 212)])
        self.bundle('campaign-b-fit', '2026-11-23T10:00:00+00:00',
                    [job('m1', 'measured', 'ollama', 'qwen38-27b-q4_k_m', config=config), job('m2', 'measured', 'ollama', 'qwen38-27b-q5_k_m', config=config),
                     {**job('m3', 'measured', 'ollama', 'qwen38-27b-q6_k', config=config), '_status': 'failed'}],
                    [row('m1', 'math', 9, 2.0, 60.0, 7 / 9), row('m2', 'math', 9, 2.5, 50.0, 8 / 9), row('m3', 'math', 9, 9.0, 5.0, 1.0)])
        records = collect(self.path)
        by_model = {r['model']: r for r in records}
        self.assertEqual(sorted(by_model), ['measured-models-gguf', 'qwen38-27b-q4_k_m', 'qwen38-27b-q5_k_m', 'qwen38-27b-q6_k'])
        projected = by_model['measured-models-gguf']
        self.assertEqual((projected['experiment'], projected['harness'], projected['mode'], projected['requests'], projected['score'], projected['quality']),
                         ('hardware-fit', 'projection', 'projection', 430, None, None))
        self.assertEqual((by_model['qwen38-27b-q4_k_m']['harness'], by_model['qwen38-27b-q4_k_m']['output_cap'], by_model['qwen38-27b-q4_k_m']['quality']),
                         ('ollama', 256, '7/9'))
        # Quantizations of one model rank separately; the projection (no scored check) and the failed run do not rank.
        top = top_combinations(records)
        self.assertEqual(list(top), [('hardware-fit', 'raider-windows')])
        self.assertEqual([r['model'] for r in top[('hardware-fit', 'raider-windows')]], ['qwen38-27b-q5_k_m', 'qwen38-27b-q4_k_m'])
        self.assertEqual(write_results_index(self.path), 4)
        index = self.path / 'docs/results/index'
        for page in ('experiment/hardware-fit.md', 'harness/projection.md', 'harness/ollama.md', 'model/measured-models-gguf.md',
                     'model/qwen38-27b-q4_k_m.md', 'hardware/raider-windows.md'):
            self.assertTrue((index / page).is_file(), page)
        summary = (self.path / 'docs/results/README.md').read_text(encoding='utf-8')
        self.assertIn('### hardware-fit: models by harness', summary)
        self.assertIn('| 1 | [ollama](index/harness/ollama.md) | [qwen38-27b-q5_k_m](index/model/qwen38-27b-q5_k_m.md) | 8/9 |', summary)


if __name__ == '__main__':
    unittest.main()
