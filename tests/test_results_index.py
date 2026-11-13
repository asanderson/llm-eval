import gzip
import json
import re
import tempfile
import unittest
from pathlib import Path

from llm_eval.reporting.index import (END, LIST_END, LIST_START, START, TOP_END, TOP_START, collect, identity, slug,
                                      top_combinations, write_results_index)


def bundle(root, experiment, publication, created, jobs, summary, synthetic=False):
    dest = root / 'docs/results' / experiment / publication
    dest.mkdir(parents=True)
    (dest / 'README.md').write_text('# report\n', encoding='utf-8')
    (dest / 'manifest.json').write_text(json.dumps({
        'experiment_id': experiment, 'publication_id': publication, 'campaign_id': 'fixture', 'created_utc': created,
        'status': 'complete', 'synthetic': synthetic,
        'coverage': [{'job_id': j['job_id'], 'status': j.pop('_status', 'succeeded')} for j in jobs]}), encoding='utf-8')
    (dest / 'resolved-config.json').write_text(json.dumps({'jobs': jobs}), encoding='utf-8')
    (dest / 'summary.json').write_text(json.dumps(summary), encoding='utf-8')


def offload_job(job_id, platform, model, cap=2048, **extra):
    return {'job_id': job_id, 'mode': 'category-smoke', 'case_id': f'{model}-{platform}', 'hardware_config_id': 'raider-windows',
            'hardware': {'os_id': 'windows-11-native'},
            'parameters': {'config': {'platform': platform, 'model_id': model, 'max_output_tokens': cap}}, **extra}


def row(job_id, category, median, rate, quality=None, decisions=None):
    return {'job_id': job_id, 'category': category, 'requests': 9, 'errors_or_missing': 0, 'elapsed_s_median': median,
            'output_tokens_per_wall_second_median': rate, 'quality_pass_rate': quality, 'quality_check_n': 9 if quality is not None else 0,
            'decision_accuracy': decisions, 'decision_labelled_n': 9 if decisions is not None else 0}


class ResultsIndexTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        bundle(self.root, 'model-offloading', 'campaign-a-offload', '2026-11-08T14:06:51+00:00',
               [offload_job('a1', 'ollama', 'deepseek-r1-32b'), offload_job('a2', 'koboldcpp', 'deepseek-r1-32b', _status='failed')],
               [row('a1', 'coding', 119.8, 3.44, quality=1 / 3), row('a1', 'math', 70.3, 3.46, quality=0.0),
                row('a2', 'coding', 60.0, 5.0, quality=1.0)])
        bundle(self.root, 'model-offloading', 'campaign-b-offload', '2026-11-09T11:12:25+00:00',
               [offload_job('b1', 'ollama', 'deepseek-r1-32b', cap=256)], [row('b1', 'math', 70.1, 3.47, quality=0.0)])
        bundle(self.root, 'llm-routing', 'campaign-a-routing', '2026-11-08T03:57:38+00:00',
               [{'job_id': 'r1', 'mode': 'decision', 'case_id': 'ollama-nimble', 'hardware_config_id': 'raider-ubuntu',
                 'hardware': {'os_id': 'ubuntu-26.04-native'},
                 'parameters': {'router': {'kind': 'systemone', 'platform': 'ollama', 'model': 'llm-eval-nimble:locked'}}}],
               [row('r1', 'coding', 0.05, None, decisions=1.0)], synthetic=True)
        self.summary = self.root / 'docs/results/README.md'
        self.summary.write_text(f'# Results\n\nintro\n\n{TOP_START}\nstale\n{TOP_END}\n\nconclusions stay\n\n{START}\nstale\n{END}\n\n'
                                f'narrative stays\n\n{LIST_START}\nstale\n{LIST_END}\n', encoding='utf-8')

    def test_identity_and_slug(self):
        self.assertEqual(identity(offload_job('x', 'lmstudio', 'qwen38-27b')), ('lmstudio', 'qwen38-27b'))
        self.assertEqual(identity({'parameters': {'router': {'kind': 'fixed'}}}), ('fixed', 'fixed'))
        self.assertEqual(identity({}), ('unknown', 'unknown'))
        self.assertEqual(slug('llm-eval-nimble:locked'), 'llm-eval-nimble-locked')
        self.assertEqual(slug('::'), 'unknown')

    def test_records_aggregate_each_published_job(self):
        records = collect(self.root)
        self.assertEqual([r['publication'] for r in records], ['campaign-b-offload', 'campaign-a-offload', 'campaign-a-offload', 'campaign-a-routing'])
        ollama = next(r for r in records if r['case'] == 'deepseek-r1-32b-ollama' and r['output_cap'] == 2048)
        self.assertEqual((ollama['requests'], ollama['errors'], ollama['wall_s'], ollama['tokens_per_s'], ollama['quality']),
                         (18, 0, '70.3–120', '3.44–3.46', '3/18'))
        self.assertEqual((ollama['date'], ollama['hardware'], ollama['harness'], ollama['model'], ollama['status']),
                         ('2026-11-08', 'raider-windows', 'ollama', 'deepseek-r1-32b', 'succeeded'))
        routing = records[-1]
        self.assertEqual((routing['harness'], routing['model'], routing['decisions'], routing['quality'], routing['synthetic']),
                         ('ollama', 'llm-eval-nimble:locked', '9/9', None, True))
        self.assertEqual(next(r for r in records if r['harness'] == 'koboldcpp')['status'], 'failed')

    def test_pages_cover_every_category_and_every_link_resolves(self):
        index = self.root / 'docs/results/index'
        (index / 'model').mkdir(parents=True)
        (index / 'model/removed-model.md').write_text('stale', encoding='utf-8')
        self.assertEqual(write_results_index(self.root), 4)
        pages = sorted(p.relative_to(index).as_posix() for p in index.rglob('*.md'))
        self.assertEqual(pages, ['README.md', 'date/2026-11-08.md', 'date/2026-11-09.md', 'experiment/llm-routing.md',
                                 'experiment/model-offloading.md', 'hardware/raider-ubuntu.md', 'hardware/raider-windows.md',
                                 'harness/koboldcpp.md', 'harness/ollama.md', 'model/deepseek-r1-32b.md',
                                 'model/llm-eval-nimble-locked.md'])
        for page in [*index.rglob('*.md'), self.summary]:
            for target in re.findall(r'\]\(([^)#]+)\)', page.read_text(encoding='utf-8')):
                self.assertTrue((page.parent / target).resolve().is_file(), f'{page.name}: {target}')
        kobold = (index / 'harness/koboldcpp.md').read_text(encoding='utf-8')
        self.assertIn('1 published result(s)', kobold)
        self.assertNotIn('campaign-b-offload', kobold)
        self.assertIn('failed', kobold)
        self.assertIn('succeeded (synthetic)', (index / 'experiment/llm-routing.md').read_text(encoding='utf-8'))

    def test_executive_summary_block_is_replaced_and_the_narrative_kept(self):
        write_results_index(self.root)
        text = self.summary.read_text(encoding='utf-8')
        self.assertTrue(text.startswith('# Results\n\nintro\n\n' + TOP_START))
        self.assertIn(TOP_END + '\n\nconclusions stay\n\n' + START, text)
        self.assertIn(END + '\n\nnarrative stays\n\n' + LIST_START, text)
        self.assertTrue(text.endswith(LIST_END + '\n'))
        # each block holds its own part: ranking on top, navigation in the middle, the report list last
        top, rest = text.split(TOP_END)
        self.assertIn('### Top 3 harness and model combinations', top)
        self.assertNotIn('models by harness', top)
        self.assertIn('[Report](model-offloading/campaign-b-offload/README.md)', rest.split(LIST_START)[1])
        self.assertNotIn('stale', text)
        self.assertIn('### model-offloading: models by harness', text)
        # experiments are ordered by their newest result: offloading ran on 2026-11-09, routing on 2026-11-08
        self.assertLess(text.index('### model-offloading: models by harness'), text.index('### llm-routing: models by harness'))
        self.assertLess(text.index('**[model-offloading](index/experiment/model-offloading.md) on'),
                        text.index('**[llm-routing](index/experiment/llm-routing.md) on'))
        # newest run first inside a matrix cell; category pages are linked relative to docs/results
        line = next(line for line in text.splitlines() if line.startswith('| [deepseek-r1-32b](index/model/deepseek-r1-32b.md)'))
        koboldcpp, cell = [c.strip() for c in line.strip('|').split(' | ')[1:]]      # harness columns are alphabetical
        self.assertIn('campaign-a-offload', koboldcpp)
        self.assertIn('failed', koboldcpp)
        self.assertLess(cell.index('campaign-b-offload'), cell.index('campaign-a-offload'))
        self.assertIn('[2026-11-09 raider-windows cap 256](model-offloading/campaign-b-offload/README.md)', cell)
        self.assertIn('(index/hardware/raider-windows.md)', text)
        before = text
        write_results_index(self.root)
        self.assertEqual(self.summary.read_text(encoding='utf-8'), before)

    def test_top_combinations_rank_by_checks_then_latency_per_experiment_and_hardware(self):
        bundle(self.root, 'model-offloading', 'campaign-c-offload', '2026-11-09T14:52:55+00:00',
               [offload_job('c1', 'ollama', 'qwen38-27b'), offload_job('c2', 'lmstudio', 'qwen38-27b'),
                offload_job('c3', 'koboldcpp', 'gemma4-31b'), offload_job('c4', 'koboldcpp', 'qwen38-27b'),
                offload_job('c5', 'lmstudio', 'unscored')],
               [row('c1', 'coding', 18.7, 3.58, quality=1.0), row('c1', 'math', 16.0, 3.55, quality=1.0),
                row('c2', 'coding', 7.7, 5.93, quality=1.0), row('c2', 'math', 7.2, 6.8, quality=1.0),
                row('c3', 'coding', 1.1, 2.68, quality=8 / 9), row('c4', 'coding', 25.9, 3.54, quality=7 / 9),
                row('c5', 'coding', 0.5, 9.0)])
        best = top_combinations(collect(self.root))
        self.assertEqual(sorted(best), [('model-offloading', 'raider-windows')])      # the only routing run is synthetic
        self.assertEqual([(r['harness'], r['model'], r['score']) for r in best[('model-offloading', 'raider-windows')]],
                         [('lmstudio', 'qwen38-27b', (18, 18)), ('ollama', 'qwen38-27b', (18, 18)), ('koboldcpp', 'gemma4-31b', (8, 9))])
        # A combination is judged on its newest succeeded run: ollama/deepseek is the 0/9 rerun, not the older 3/18.
        every = top_combinations(collect(self.root), limit=10)[('model-offloading', 'raider-windows')]
        self.assertEqual([(r['harness'], r['model'], r['publication']) for r in every][3:],
                         [('koboldcpp', 'qwen38-27b', 'campaign-c-offload'), ('ollama', 'deepseek-r1-32b', 'campaign-b-offload')])
        write_results_index(self.root)
        text = self.summary.read_text(encoding='utf-8')
        heading = '### Top 3 harness and model combinations per experiment and hardware configuration'
        self.assertLess(text.index(heading), text.index('### Browse by category'))
        self.assertIn('| 1 | [lmstudio](index/harness/lmstudio.md) | [qwen38-27b](index/model/qwen38-27b.md) | 18/18 | 7.45 | 6.37 | '
                      '[2026-11-09 cap 2048](model-offloading/campaign-c-offload/README.md) |', text)
        self.assertIn('**[llm-routing](index/experiment/llm-routing.md) on [raider-ubuntu](index/hardware/raider-ubuntu.md)**'
                      '\n\n'
                      'No measured run with scored checks has been published yet.', text)
        overview = (self.root / 'docs/results/index/README.md').read_text(encoding='utf-8')
        self.assertIn(heading, overview)
        # four ranked combinations are a comparison: the summary gets a chart, the index page does not repeat it
        chart = self.root / 'diagrams/results/summary/model-offloading-raider-windows.png'
        self.assertTrue(chart.read_bytes().startswith(b'\x89PNG'))
        self.assertIn('](../../diagrams/results/summary/model-offloading-raider-windows.png)', text)
        self.assertNotIn('.png', overview)
        self.assertEqual([p.name for p in chart.parent.iterdir()], [chart.name])      # routing has nothing to compare

    def test_results_readme_lists_newest_first(self):
        from llm_eval.reporting.publish import write_index
        write_index(self.root)
        rows = [line for line in (self.root / 'docs/results/README.md').read_text(encoding='utf-8').splitlines() if '[Report]' in line]
        self.assertEqual([line.split('](')[1].split('/')[1] for line in rows],
                         ['campaign-b-offload', 'campaign-a-offload', 'campaign-a-routing'])

    def test_peak_memory_comes_from_the_latest_attempt_telemetry(self):
        raw = self.root / 'docs/results/model-offloading/campaign-b-offload/raw'
        raw.mkdir()
        samples = [(True, 20.5, 9000), (True, 24.6, 12084), (False, 99.0, 99999)]
        with gzip.open(raw / 'measurements.jsonl.gz', 'wt', encoding='utf-8') as out:
            out.write(json.dumps({'record_type': 'request', 'job_id': 'b1', 'latest_attempt': True, 'data': {}}) + '\n')
            for latest, rss, used in samples:
                out.write(json.dumps({'record_type': 'telemetry', 'job_id': 'b1', 'latest_attempt': latest,
                                      'data': {'backend_tree_rss_gib': rss, 'gpus': [{'used_mib': used}]}}) + '\n')
        records = collect(self.root)
        self.assertEqual((records[0]['backend_rss_gib'], round(records[0]['gpu_gib'], 2)), (24.6, 11.8))
        self.assertEqual((records[1]['backend_rss_gib'], records[1]['gpu_gib']), (None, None))

    def test_a_readme_without_markers_is_left_alone(self):
        self.summary.write_text('# Results\n\nhand written\n', encoding='utf-8')
        write_results_index(self.root)
        self.assertEqual(self.summary.read_text(encoding='utf-8'), '# Results\n\nhand written\n')

    def test_a_missing_or_legacy_generated_readme_gets_the_marked_skeleton(self):
        legacy = '# Experiment results\n\n| Experiment | Run time UTC | Status | Synthetic | Results |\n|---|---|---|---|---|\n'
        for before in (None, legacy):
            with self.subTest(before=before):
                self.summary.unlink()
                if before:
                    self.summary.write_text(before, encoding='utf-8')
                write_results_index(self.root)
                text = self.summary.read_text(encoding='utf-8')
                self.assertLess(text.index('## Executive summary'), text.index('### Top 3 harness and model combinations'))
                self.assertLess(text.index('## Results index'), text.index('### Browse by category'))
                self.assertLess(text.index('## All published reports'), text.index('campaign-a-routing/README.md)', text.index(LIST_START)))


def legal_job(job_id, kind, harness='fixture', model='fixture', mode='smoke', cohort='a' * 64, os_id='ubuntu-26.04-native', hardware='legal-host'):
    return {'job_id': job_id, 'experiment_id': 'legal-benchmark', 'experiment_version': 1, 'mode': mode, 'case_id': job_id,
            'hardware_config_id': hardware, 'hardware': {'os_id': os_id, 'hardware_profile': 'msi-raider-18-hx-ai'},
            'parameters': {'synthetic': kind == 'fixture', 'execution_kind': kind, 'data_class': 'public-synthetic',
                           'identity': {'harness': harness, 'model': model}, 'cohorts': [cohort]}, 'input_files': [{'sha256': 'b' * 64}]}


def legal_bundle(root, publication, created, jobs, summary, projection=True):
    """A legal bundle as the projection writes it: the marker, the execution kinds and public job descriptions."""
    dest = root / 'docs/results/legal-benchmark' / publication
    dest.mkdir(parents=True)
    (dest / 'README.md').write_text('# report\n', encoding='utf-8')
    manifest = {'experiment_id': 'legal-benchmark', 'publication_id': publication, 'campaign_id': 'fixture', 'created_utc': created,
                'status': 'complete', 'synthetic': any(j['parameters'].get('synthetic') for j in jobs),
                'coverage': [{'job_id': j['job_id'], 'status': 'succeeded'} for j in jobs]}
    if projection:
        manifest.update(projection={'id': 'legal-projection', 'version': 1}, canonical_bytes=1,
                        execution_kinds=sorted({j['parameters']['execution_kind'] for j in jobs}))
    (dest / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
    (dest / 'resolved-config.json').write_text(json.dumps({'experiment': {'experiment_id': 'legal-benchmark'}, 'jobs': jobs}), encoding='utf-8')
    (dest / 'summary.json').write_text(json.dumps(summary), encoding='utf-8')
    return dest


def without_legal(text):
    """A generated page without what the legal records add: their rows, sections and cohort table, the browse-by counts and
    the per-page result count (both count every record)."""
    kept, skipping, browse = [], False, False
    for line in text.split('\n'):
        if line.startswith('#'):
            skipping = 'legal-benchmark' in line or 'Results by class and cohort' in line
            browse = line == '### Browse by category'
        if line.startswith(('<!--', 'Full table and per-category pages')):      # the end of a generated section
            skipping = False
        if browse and line.startswith('|'):
            continue
        if skipping or 'campaign-l-legal' in line or 'published result(s)' in line:
            continue
        kept.append(line)
    return kept


class LegalIndexTests(unittest.TestCase):
    """The cohort-aware index: legal results by class and cohort, never ranked with other experiments."""
    setUp = ResultsIndexTests.setUp

    def add_legal(self):
        legal_bundle(self.root, 'campaign-l-legal', '2026-11-10T09:00:00+00:00',
                     [legal_job('l1', 'fixture', cohort='c' * 64),
                      legal_job('l2', 'model-run', 'ollama', 'deepseek-r1-32b', mode='generation', cohort='d' * 64, os_id='windows-11-native',
                                hardware='raider-windows'),
                      legal_job('l3', 'score-only', 'ollama', 'deepseek-r1-32b', mode='score', cohort='e' * 64)],
                     [row('l1', 'all', 0.01, None, quality=1.0), row('l2', 'lexical-eligible', 5.0, 30.0, quality=1.0),
                      row('l3', 'lexical-eligible', None, None, quality=1.0)])

    def test_identity_and_cohort_fingerprint_are_parsed_for_legal_jobs(self):
        self.assertEqual(identity(legal_job('x', 'model-run', 'llama.cpp', 'qwen3:27b')), ('llama.cpp', 'qwen3:27b'))
        self.assertEqual(identity({'parameters': {'identity': {}}}), ('unknown', 'unknown'))
        self.add_legal()
        records = collect(self.root)
        legal = {r['case']: r for r in records if r['experiment'] == 'legal-benchmark'}
        self.assertEqual({k: (r['execution_kind'], r['data_class'], r['cohorts'], r['class'], r['ranked'], r['synthetic'], r['harness'])
                          for k, r in legal.items()},
                         {'l1': ('fixture', 'public-synthetic', ['c' * 64], 'fixture', False, True, 'fixture'),
                          'l2': ('model-run', 'public-synthetic', ['d' * 64], 'measured', False, False, 'ollama'),
                          'l3': ('score-only', 'public-synthetic', ['e' * 64], 'score-only', False, False, 'ollama')})
        offload = next(r for r in records if r['experiment'] == 'model-offloading')
        self.assertEqual({k: offload[k] for k in ('execution_kind', 'data_class', 'cohorts', 'class', 'ranked')},
                         {'execution_kind': None, 'data_class': None, 'cohorts': [], 'class': None, 'ranked': True})
        self.assertEqual(list(offload), ['date', 'created', 'experiment', 'mode', 'campaign', 'publication', 'hardware', 'os', 'harness', 'model',
                                         'case', 'status', 'synthetic', 'output_cap', 'requests', 'errors', 'wall_s', 'tokens_per_s', 'quality',
                                         'decisions', 'score', 'wall_mid', 'tokens_mid', 'backend_rss_gib', 'gpu_gib', 'report',
                                         'execution_kind', 'data_class', 'cohorts', 'class', 'ranked'])

    def test_a_job_with_several_cohorts_gets_one_row_with_the_job_total(self):
        # The summary rows are per arm and name no cohort, so the count beside a cohort digest would not be that cohort's.
        from llm_eval.reporting.index import cohort_results
        job = legal_job('m1', 'model-run', 'ollama', 'deepseek-r1-32b', mode='retrieval')
        job['parameters']['cohorts'] = ['1' * 64, '2' * 64]
        legal_bundle(self.root, 'campaign-m-legal', '2026-11-11T09:00:00+00:00', [job],
                     [row('m1', 'lexical-eligible', 5.0, 30.0, quality=1.0), row('m1', 'no-context', 5.0, 30.0, quality=0.0)])
        text = cohort_results(collect(self.root), '', '../')
        rows = [line for line in text.splitlines() if 'retrieval' in line]
        self.assertEqual(len(rows), 1)
        self.assertIn('1' * 12 + ', ' + '2' * 12, rows[0])
        self.assertIn('| 9/18 |', rows[0])
        self.assertIn('| Checks passed, all cohorts of the job |', text)

    def test_legal_results_are_listed_by_class_cohort_os_and_runtime(self):
        from llm_eval.reporting.index import cohort_results
        self.assertEqual(cohort_results(collect(self.root), '', '../'), '')
        self.add_legal()
        write_results_index(self.root)
        index = self.root / 'docs/results/index'
        text = cohort_results(collect(self.root), '', '../')
        for title, cohort in (('Fixture runs', 'c' * 12), ('Measured runs', 'd' * 12), ('Score-only runs', 'e' * 12)):
            self.assertIn(title, text)
            self.assertIn(cohort, text)
        self.assertLess(text.index('Fixture runs'), text.index('Measured runs'))
        self.assertLess(text.index('Measured runs'), text.index('Score-only runs'))
        self.assertIn('windows-11-native', text)
        self.assertIn('[ollama](harness/ollama.md)', text)
        overview = (index / 'README.md').read_text(encoding='utf-8')
        readme = self.summary.read_text(encoding='utf-8')
        self.assertIn(text, overview)
        self.assertIn(cohort_results(collect(self.root), 'index/', ''), readme.split(START)[1].split(END)[0])
        for page in [*index.rglob('*.md'), self.summary]:
            for line in page.read_text(encoding='utf-8').splitlines():
                if 'campaign-l-legal' in line:
                    self.assertTrue(any(word in line for word in ('fixture', 'measured', 'score-only')), (page.name, line))
                    self.assertNotIn('(synthetic)', line)
        listing = next(line for line in readme.splitlines() if 'campaign-l-legal' in line and '[Report]' in line)
        self.assertIn('| fixture, model-run, score-only |', listing)
        self.assertTrue((index / 'experiment/legal-benchmark.md').is_file())

    def test_legal_records_never_enter_top_combinations(self):
        self.add_legal()
        records = collect(self.root)
        self.assertTrue(any(r['experiment'] == 'legal-benchmark' and not r['synthetic'] and r['status'] == 'succeeded' and r['score'] for r in records))
        self.assertFalse(any(r['experiment'] == 'legal-benchmark' for chosen in top_combinations(records, 10).values() for r in chosen))
        write_results_index(self.root)
        top = self.summary.read_text(encoding='utf-8').split(TOP_START)[1].split(TOP_END)[0]
        self.assertNotIn('legal-benchmark', top)
        self.assertNotIn('campaign-l-legal', top)
        self.assertNotIn('legal-host', top)
        charts = self.root / 'diagrams/results/summary'
        self.assertFalse(charts.exists() and any('legal' in p.name for p in charts.iterdir()))

    def test_fixture_or_incomparable_rubric_cannot_displace_a_ranked_result(self):
        bundle(self.root, 'model-offloading', 'campaign-c-offload', '2026-11-09T14:52:55+00:00',
               [offload_job('c1', 'ollama', 'qwen38-27b'), offload_job('c2', 'lmstudio', 'qwen38-27b')],
               [row('c1', 'coding', 18.7, 3.58, quality=0.5), row('c2', 'coding', 7.7, 5.93, quality=1.0)])

        def best():
            return [(r['harness'], r['model'], r['publication']) for r in top_combinations(collect(self.root), 10)[('model-offloading', 'raider-windows')]]
        before = best()
        # Newer legal records on the same hardware, harness and model, with perfect checks: a fixture and an incomparable rubric.
        legal_bundle(self.root, 'campaign-m-legal', '2026-11-11T09:00:00+00:00',
                     [legal_job('m1', 'fixture', 'ollama', 'qwen38-27b', hardware='raider-windows'),
                      legal_job('m2', 'model-run', 'ollama', 'qwen38-27b', mode='generation', hardware='raider-windows')],
                     [row('m1', 'all', 0.001, 99.0, quality=1.0), row('m2', 'lexical-eligible', 0.001, 99.0, quality=1.0)])
        self.assertEqual(best(), before)
        self.assertEqual(sorted(top_combinations(collect(self.root), 10)), [('model-offloading', 'raider-windows')])

    def test_relabelled_or_legacy_legal_bundles_are_not_ranked(self):
        bundle(self.root, 'llm-routing', 'campaign-r-routing', '2026-11-09T03:57:38+00:00',
               [{'job_id': 'r2', 'mode': 'decision', 'case_id': 'ollama-nimble', 'hardware_config_id': 'raider-ubuntu',
                 'hardware': {'os_id': 'ubuntu-26.04-native'},
                 'parameters': {'router': {'kind': 'systemone', 'platform': 'ollama', 'model': 'llm-eval-nimble:locked'}}}],
               [row('r2', 'coding', 0.05, None, decisions=0.5)])
        self.assertEqual([r['publication'] for r in top_combinations(collect(self.root))[('llm-routing', 'raider-ubuntu')]], ['campaign-r-routing'])
        # Newer and perfect, but the manifest says llm-routing while the resolved jobs say legal-benchmark.
        relabelled = legal_bundle(self.root, 'campaign-x-legal', '2026-11-12T03:57:38+00:00',
                                  [{**legal_job('x1', 'model-run', hardware='raider-ubuntu'),
                                    'parameters': {'router': {'kind': 'systemone', 'platform': 'ollama', 'model': 'llm-eval-nimble:locked'}}}],
                                  [row('x1', 'coding', 0.01, None, decisions=1.0)], projection=False)
        manifest = json.loads((relabelled / 'manifest.json').read_text(encoding='utf-8'))
        (relabelled / 'manifest.json').write_text(json.dumps({**manifest, 'experiment_id': 'llm-routing'}), encoding='utf-8')
        relabelled.rename(self.root / 'docs/results/llm-routing/campaign-x-legal')
        legal_bundle(self.root, 'campaign-y-legal', '2026-11-12T04:00:00+00:00', [legal_job('y1', 'model-run', 'ollama', 'q')],
                     [row('y1', 'all', 0.01, None, quality=1.0)], projection=False)
        records = collect(self.root)
        by_case = {r['case']: r for r in records}
        self.assertEqual((by_case['x1']['class'], by_case['x1']['ranked'], by_case['x1']['experiment']), ('invalid', False, 'llm-routing'))
        self.assertEqual((by_case['y1']['class'], by_case['y1']['ranked']), ('legacy', False))
        self.assertEqual([r['publication'] for r in top_combinations(records)[('llm-routing', 'raider-ubuntu')]], ['campaign-r-routing'])

    def test_offload_and_routing_output_is_identical_with_and_without_a_legal_bundle(self):
        def outputs():
            write_results_index(self.root)
            return {p.relative_to(self.root).as_posix(): p.read_bytes() for p in sorted(self.root.rglob('*'))
                    if p.is_file() and ('docs/results/index/' in p.as_posix() or '/diagrams/' in p.as_posix() or p == self.summary)}
        bundle(self.root, 'model-offloading', 'campaign-c-offload', '2026-11-09T14:52:55+00:00',
               [offload_job('c1', 'ollama', 'qwen38-27b'), offload_job('c2', 'lmstudio', 'qwen38-27b'), offload_job('c3', 'koboldcpp', 'gemma4-31b')],
               [row('c1', 'coding', 18.7, 3.58, quality=1.0), row('c2', 'coding', 7.7, 5.93, quality=1.0), row('c3', 'coding', 1.1, 2.68, quality=8 / 9)])
        before, records_before = outputs(), collect(self.root)
        self.add_legal()
        after, records_after = outputs(), collect(self.root)
        self.assertEqual([r for r in records_after if r['experiment'] != 'legal-benchmark'], records_before)
        readme = 'docs/results/README.md'
        self.assertEqual(after[readme].decode().split(TOP_START)[1].split(TOP_END)[0], before[readme].decode().split(TOP_START)[1].split(TOP_END)[0])
        charts = {k for k in before if k.endswith('.png')}
        self.assertTrue(charts)
        self.assertEqual({k: after[k] for k in after if k.endswith('.png')}, {k: before[k] for k in charts})
        for name, data in before.items():
            if not name.endswith('.png'):
                with self.subTest(page=name):
                    self.assertEqual(without_legal(after[name].decode()), without_legal(data.decode()))
        self.assertEqual(sorted(set(after) - set(before)),
                         ['docs/results/index/date/2026-11-10.md', 'docs/results/index/experiment/legal-benchmark.md',
                          'docs/results/index/hardware/legal-host.md', 'docs/results/index/harness/fixture.md', 'docs/results/index/model/fixture.md'])

    def test_hostile_values_of_a_projected_bundle_are_rendered_inert(self):
        hostile = legal_job('h1', 'model-run', 'h](javascript:alert(1))', 'm\n| x |', mode='generation\n## INJECTED\n<script>x</script>',
                            os_id='<img src=x onerror=alert(1)>', cohort='A' * 12 + '<b>')
        dest = legal_bundle(self.root, 'campaign-h-legal', '2026-11-10T09:00:00+00:00', [hostile],
                            [{**row('h1', 'lexical-eligible', 5.0, 30.0, quality=1e308), 'quality_check_n': 10 ** 20}])
        manifest = json.loads((dest / 'manifest.json').read_text(encoding='utf-8'))
        (dest / 'manifest.json').write_text(json.dumps({**manifest, 'status': 'ok\n\n<script>alert(1)</script>'}), encoding='utf-8')
        records = collect(self.root)      # no OverflowError
        (record,) = [r for r in records if r['case'] == 'h1']
        self.assertIsNone(record['quality'])
        write_results_index(self.root)
        for page in [*(self.root / 'docs/results/index').rglob('*.md'), self.summary]:
            text = page.read_text(encoding='utf-8')
            for raw in ('<script>', '<img', '<b>', '\n## INJECTED', 'm\n| x |'):
                self.assertNotIn(raw, text, page.name)


if __name__ == '__main__':
    unittest.main()
