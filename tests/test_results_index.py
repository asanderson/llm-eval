import gzip
import json
import re
import tempfile
import unittest
from pathlib import Path

from llm_eval.reporting.index import (END, LIST_END, LIST_START, START, SUMMARY_END, SUMMARY_START, TOP_END, TOP_START, collect,
                                      identity, lineage, matched, origins, slug, us_model, write_results_index)


def bundle(root, experiment, publication, created, jobs, summary, synthetic=False):
    dest = root / 'docs/results' / experiment / publication
    dest.mkdir(parents=True)
    (root / 'docs/REPRODUCE.md').touch()
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
        bundle(self.root, 'decision-models', 'campaign-a-routing', '2026-11-08T03:57:38+00:00',
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
        self.assertEqual(pages, ['README.md', 'date/2026-11-08.md', 'date/2026-11-09.md', 'experiment/decision-models.md',
                                 'experiment/model-offloading.md', 'hardware/raider-ubuntu.md', 'hardware/raider-windows.md',
                                 'harness/koboldcpp.md', 'harness/ollama.md', 'model/deepseek-r1-32b.md',
                                 'model/llm-eval-nimble-locked.md', 'origin/us.md', 'recommended/README.md',
                                 'recommended/raider-ubuntu/decision-models.md', 'recommended/raider-windows/model-offloading.md'])
        for page in [*index.rglob('*.md'), self.summary]:
            for target in re.findall(r'\]\(([^)#]+)\)', page.read_text(encoding='utf-8')):
                self.assertTrue((page.parent / target).resolve().is_file(), f'{page.name}: {target}')
        kobold = (index / 'harness/koboldcpp.md').read_text(encoding='utf-8')
        self.assertIn('1 published result(s)', kobold)
        self.assertNotIn('campaign-b-offload', kobold)
        self.assertIn('failed', kobold)
        self.assertIn('succeeded (synthetic)', (index / 'experiment/decision-models.md').read_text(encoding='utf-8'))

    def test_executive_summary_block_is_replaced_and_the_narrative_kept(self):
        write_results_index(self.root)
        text = self.summary.read_text(encoding='utf-8')
        self.assertTrue(text.startswith('# Results\n\nintro\n\n' + TOP_START))
        self.assertIn(TOP_END + '\n\nconclusions stay\n\n' + START, text)
        self.assertIn(END + '\n\nnarrative stays\n\n' + LIST_START, text)
        self.assertTrue(text.endswith(LIST_END + '\n'))
        # The top block covers hardware, followed by navigation and the publication list.
        top, rest = text.split(TOP_END)
        self.assertIn('### What ran on this hardware?', top)
        self.assertNotIn('models by harness', top)
        self.assertIn('[Report](model-offloading/campaign-b-offload/README.md)', rest.split(LIST_START)[1])
        self.assertNotIn('stale', text)
        self.assertIn('### model-offloading: models by harness', text)
        # experiments are ordered by their newest result: offloading ran on 2026-11-09, routing on 2026-11-08
        self.assertLess(text.index('### model-offloading: models by harness'), text.index('### decision-models: models by harness'))
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

    def test_both_hardware_summaries_list_every_job_with_its_source_and_status(self):
        # The same job ID can be published again; two models can use the same harness on one host.
        bundle(self.root, 'hardware-fit', 'fit-repeat', '2026-11-10T11:00:00+00:00',
               [offload_job('b1', 'ollama', 'deepseek-r1-32b', mode='measured', _status='failed'),
                offload_job('p1', 'projection', 'fit-candidates', mode='projection'),
                offload_job('other', 'ollama', 'another-model', mode='measured')], [])
        root_readme = self.root / 'README.md'
        root_readme.write_text(f'{SUMMARY_START}\n{SUMMARY_END}\n', encoding='utf-8')
        write_results_index(self.root)

        expected = [
            ('raider-ubuntu', 'decision-models', 'llm-eval-nimble:locked', 'Ollama', 'decision · fixture', 'succeeded', 'campaign-a-routing', 'r1'),
            ('raider-windows', 'model-offloading', 'deepseek-r1-32b', 'Ollama', 'category-smoke', 'succeeded', 'campaign-b-offload', 'b1'),
            ('raider-windows', 'model-offloading', 'deepseek-r1-32b', 'Ollama', 'category-smoke', 'succeeded', 'campaign-a-offload', 'a1'),
            ('raider-windows', 'model-offloading', 'deepseek-r1-32b', 'KoboldCpp', 'category-smoke', 'failed', 'campaign-a-offload', 'a2'),
            ('raider-windows', 'hardware-fit', 'deepseek-r1-32b', 'Ollama', 'measured', 'failed', 'fit-repeat', 'b1'),
            ('raider-windows', 'hardware-fit', 'fit-candidates', 'projection', 'projection', 'succeeded', 'fit-repeat', 'p1'),
            ('raider-windows', 'hardware-fit', 'another-model', 'Ollama', 'measured', 'succeeded', 'fit-repeat', 'other'),
        ]
        for path, start, end in ((root_readme, SUMMARY_START, SUMMARY_END), (self.summary, TOP_START, TOP_END)):
            block = path.read_text(encoding='utf-8').split(start)[1].split(end)[0]
            links = re.findall(r'\]\(#(runs-[^)]+)\)', block)
            self.assertCountEqual(links, re.findall(r'<a id="([^"]+)"></a>', block))
            actual = []
            hardware = experiment = None
            for line in block.splitlines():
                if line.startswith('#### '):
                    hardware = line[5:]
                elif line.startswith('##### '):
                    experiment = line[6:]
                match = re.search(r'\| \[[^\]]+ · ([^\]]+)\]\(([^)]+/README\.md)\) \|$', line)
                if match:
                    job_id, report = match.groups()
                    self.assertTrue((path.parent / report).is_file())
                    model, harness, mode, status = line.split(' | ')[:4]
                    actual.append((hardware, experiment, model.removeprefix('| '), harness, mode, status,
                                   Path(report).parent.name, job_id))
            self.assertCountEqual(actual, expected)

    def test_incomplete_historical_metadata_is_displayed_as_an_observation(self):
        records = collect(self.root)
        self.assertEqual(matched(records), {})
        write_results_index(self.root)
        page = (self.root / 'docs/results/index/recommended/raider-windows/model-offloading.md').read_text(encoding='utf-8')
        self.assertIn('No two successful model packages have complete matching controls', page)
        self.assertIn('deepseek-r1-32b · koboldcpp | category-smoke · failed', page)
        self.assertIn('not recorded | not recorded | 0/9', page)
        self.assertNotIn('| Rank |', page)

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
                self.assertLess(text.index('## Executive summary'), text.index('### What ran on this hardware?'))
                self.assertLess(text.index('## Results index'), text.index('### Browse by category'))
                self.assertLess(text.index('## All published reports'), text.index('campaign-a-routing/README.md)', text.index(LIST_START)))


def legal_job(job_id, kind, harness='fixture', model='fixture', mode='smoke', cohort='a' * 64, os_id='ubuntu-26.04-native', hardware='legal-host',
              experiment='legal-models'):
    return {'job_id': job_id, 'experiment_id': experiment, 'experiment_version': 1, 'mode': mode, 'case_id': job_id,
            'hardware_config_id': hardware, 'hardware': {'os_id': os_id, 'hardware_profile': 'msi-raider-18-hx-ai'},
            'parameters': {'synthetic': kind == 'fixture', 'execution_kind': kind, 'data_class': 'public-synthetic',
                           'identity': {'harness': harness, 'model': model}, 'cohorts': [cohort]}, 'input_files': [{'sha256': 'b' * 64}]}


def legal_bundle(root, publication, created, jobs, summary, projection=True, experiment='legal-models'):
    """A legal bundle as the projection writes it: the marker, the execution kinds and public job descriptions; `experiment`
    is the id it was published under (`legal-benchmark` before the rename of 2026-11-24)."""
    dest = root / 'docs/results' / experiment / publication
    dest.mkdir(parents=True)
    (root / 'docs/REPRODUCE.md').touch()
    (dest / 'README.md').write_text('# report\n', encoding='utf-8')
    manifest = {'experiment_id': experiment, 'publication_id': publication, 'campaign_id': 'fixture', 'created_utc': created,
                'status': 'complete', 'synthetic': any(j['parameters'].get('synthetic') for j in jobs),
                'coverage': [{'job_id': j['job_id'], 'status': 'succeeded'} for j in jobs]}
    if projection:
        manifest.update(projection={'id': 'legal-projection', 'version': 1}, canonical_bytes=1,
                        execution_kinds=sorted({j['parameters']['execution_kind'] for j in jobs}))
    (dest / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
    (dest / 'resolved-config.json').write_text(json.dumps({'experiment': {'experiment_id': experiment}, 'jobs': jobs}), encoding='utf-8')
    (dest / 'summary.json').write_text(json.dumps(summary), encoding='utf-8')
    return dest


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
        legal = {r['case']: r for r in records if r['experiment'] == 'legal-models'}
        self.assertEqual({k: (r['execution_kind'], r['data_class'], r['cohorts'], r['class'], r['ranked'], r['synthetic'], r['harness'])
                          for k, r in legal.items()},
                         {'l1': ('fixture', 'public-synthetic', ['c' * 64], 'fixture', False, True, 'fixture'),
                          'l2': ('model-run', 'public-synthetic', ['d' * 64], 'measured', False, False, 'ollama'),
                          'l3': ('score-only', 'public-synthetic', ['e' * 64], 'score-only', False, False, 'ollama')})
        offload = next(r for r in records if r['experiment'] == 'model-offloading')
        self.assertEqual({k: offload[k] for k in ('execution_kind', 'data_class', 'cohorts', 'class', 'ranked')},
                         {'execution_kind': None, 'data_class': None, 'cohorts': [], 'class': None, 'ranked': True})
        self.assertIsNone(offload['comparison'])

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
                if 'campaign-l-legal' in line and line.startswith('|'):
                    self.assertTrue(any(word in line for word in ('fixture', 'measured', 'score-only')), (page.name, line))
                    self.assertNotIn('(synthetic)', line)
        listing = next(line for line in readme.splitlines() if 'campaign-l-legal' in line and '[Report]' in line)
        self.assertIn('| fixture, model-run, score-only |', listing)
        self.assertTrue((index / 'experiment/legal-models.md').is_file())

    def test_legal_runs_are_visible_and_never_enter_generic_comparisons(self):
        self.add_legal()
        self.assertTrue(all(r['comparison'] is None for r in collect(self.root) if r['class']))
        write_results_index(self.root)
        page = (self.root / 'docs/results/index/recommended/legal-host/legal-models.md').read_text(encoding='utf-8')
        self.assertNotIn('Matched model comparisons', page)
        self.assertIn('score-only', page)

    def test_relabelled_or_legacy_legal_bundles_are_not_ranked(self):
        bundle(self.root, 'decision-models', 'campaign-r-routing', '2026-11-09T03:57:38+00:00',
               [{'job_id': 'r2', 'mode': 'decision', 'case_id': 'ollama-nimble', 'hardware_config_id': 'raider-ubuntu',
                 'hardware': {'os_id': 'ubuntu-26.04-native'},
                 'parameters': {'router': {'kind': 'systemone', 'platform': 'ollama', 'model': 'llm-eval-nimble:locked'}}}],
               [row('r2', 'coding', 0.05, None, decisions=0.5)])
        # Newer and perfect, but the manifest says decision-models while the resolved jobs say legal-models.
        relabelled = legal_bundle(self.root, 'campaign-x-legal', '2026-11-12T03:57:38+00:00',
                                  [{**legal_job('x1', 'model-run', hardware='raider-ubuntu'),
                                    'parameters': {'router': {'kind': 'systemone', 'platform': 'ollama', 'model': 'llm-eval-nimble:locked'}}}],
                                  [row('x1', 'coding', 0.01, None, decisions=1.0)], projection=False)
        manifest = json.loads((relabelled / 'manifest.json').read_text(encoding='utf-8'))
        (relabelled / 'manifest.json').write_text(json.dumps({**manifest, 'experiment_id': 'decision-models'}), encoding='utf-8')
        relabelled.rename(self.root / 'docs/results/decision-models/campaign-x-legal')
        legal_bundle(self.root, 'campaign-y-legal', '2026-11-12T04:00:00+00:00', [legal_job('y1', 'model-run', 'ollama', 'q')],
                     [row('y1', 'all', 0.01, None, quality=1.0)], projection=False)
        records = collect(self.root)
        by_case = {r['case']: r for r in records}
        self.assertEqual((by_case['x1']['class'], by_case['x1']['ranked'], by_case['x1']['experiment']), ('invalid', False, 'decision-models'))
        self.assertEqual((by_case['y1']['class'], by_case['y1']['ranked']), ('legacy', False))
        self.assertIsNone(by_case['x1']['comparison'])
        self.assertIsNone(by_case['y1']['comparison'])

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


class EvidencePageTests(unittest.TestCase):
    setUp = ResultsIndexTests.setUp

    def test_generated_setup_pages_are_deterministic_and_discard_stale_pages(self):
        directory = self.root / 'docs/results/index/recommended'
        stale = directory / 'removed-host/stale.md'
        stale.parent.mkdir(parents=True)
        stale.touch()
        write_results_index(self.root)
        self.assertFalse(stale.exists())
        before = {p: p.read_bytes() for p in directory.rglob('*') if p.is_file()}
        write_results_index(self.root)
        self.assertEqual({p: p.read_bytes() for p in directory.rglob('*') if p.is_file()}, before)
        self.assertIn('[setup evidence](index/recommended/README.md)', self.summary.read_text(encoding='utf-8'))

    def test_latest_attempt_with_warmups_and_failed_requests(self):
        bundle_path = self.root / 'docs/results/model-offloading/campaign-b-offload'
        (bundle_path / 'raw').mkdir()
        data = {'status': 'ok', 'task_id': 'a', 'category': 'math', 'warmup': False, 'prompt_tokens': 7,
                'first_visible_s': 0.7, 'elapsed_s': 1.2, 'completion_tokens': 2}
        with gzip.open(bundle_path / 'raw/measurements.jsonl.gz', 'wt') as out:
            for latest, edits in [(True, {}), (True, {'status': 'error', 'task_id': 'b', 'prompt_tokens': 400}),
                                  (True, {'warmup': True, 'task_id': 'warmup'}), (False, {'prompt_tokens': 999})]:
                out.write(json.dumps({'job_id': 'b1', 'record_type': 'request', 'latest_attempt': latest, 'data': {**data, **edits}}) + '\n')
        record = collect(self.root)[0]
        obs = record['observation']
        self.assertEqual((obs['tasks'], obs['repeat_range'], obs['completed'], obs['observations']), (2, [1], 1, 2))
        self.assertEqual((obs['prompt_range'], obs['output_range'], obs['visible_s']), ([7, 7], [2, 2], 0.7))


class ComparisonTests(unittest.TestCase):
    def setUp(self):
        from llm_eval.reporting.evidence import Evidence
        self.manifest = {'synthetic': False, 'publication_id': 'publication', 'code_revision': '1' * 40}
        self.config = {'platform': 'ollama', 'protocol': 'ollama', 'backend_version': '1.0',
                       'context_tokens': 4096, 'max_output_tokens': 128, 'temperature': 0, 'seed': 7, 'concurrency': 1,
                       'lane': 'offload', 'reasoning_mode': 'default', 'cache_condition': 'warm', 'speculative_decoding': 'disabled',
                       'ram_budget_gib': 46, 'gpu_budget_gib': 22, 'request_options': {}, 'launch': {'gpu_layers': 20, 'model_file': 'a.gguf'}, 'tokenizer_revision': 'locked',
                       'chat_template_sha256': '2' * 64, 'repeats': 2, 'warmups': 1}
        self.job = {'experiment_version': 1, 'hardware': {'os_id': 'ubuntu'}, 'parameters': {'config': self.config}}
        self.row = {'ranked': True, 'synthetic': False, 'status': 'succeeded', 'score': (2, 2), 'requests': 2,
                    'os': 'ubuntu', 'hardware': 'h1', 'harness': 'ollama', 'experiment': 'model-offloading',
                    'mode': 'category-smoke', 'publication': 'publication', 'model': 'a', 'job_id': 'a'}
        self.raw = Evidence(requests=[{'status': 'ok', 'synthetic': False, 'task_id': 't', 'category': 'math',
                            'benchmark': 'category-smoke', 'prompt_sha256': '3' * 64, 'repetition': i, 'quality_pass': True}
                            for i in (1, 2)], suites={'math': {'4' * 64}}, artifacts={'5' * 64}, paging={'math': False})

    def key(self):
        from llm_eval.common import digest
        from llm_eval.reporting.evidence import comparison_controls
        controls = comparison_controls(self.manifest, self.job, self.raw, self.row)
        return digest(controls) if controls is not None else None

    def test_controls_fix_workload_protocol_settings_paging_and_publication(self):
        expected = self.key()
        self.assertIsNotNone(expected)
        for mapping, field, updated in (
                (self.config, 'max_output_tokens', 256), (self.config, 'context_tokens', 8192),
                (self.config, 'cache_condition', 'cold'), (self.config, 'protocol', 'openai'),
                (self.config['launch'], 'gpu_layers', 12), (self.config, 'seed', 8),
                (self.raw.paging, 'math', True), (self.raw.suites, 'math', {'7' * 64}),
                (self.raw.requests[0], 'prompt_sha256', '7' * 64), (self.raw.requests[1], 'task_id', 'other'),
                (self.raw.requests[1], 'repetition', 1), (self.manifest, 'code_revision', '6' * 40),
                (self.row, 'publication', 'another bundle'), (self.row, 'mode', 'decision'),
                (self.row, 'harness', 'other'), (self.row, 'status', 'failed'), (self.row, 'synthetic', True)):
            with self.subTest(field=field, updated=updated):
                original = mapping[field]
                mapping[field] = updated
                self.assertNotEqual(self.key(), expected)
                mapping[field] = original

    def test_incomplete_vintage_runs_are_never_cohorted(self):
        for mapping, field in ((self.config, 'protocol'), (self.config, 'request_options'), (self.config, 'temperature'),
                               (self.config, 'repeats'), (self.manifest, 'code_revision'), (self.raw.requests[0], 'task_id'),
                               (self.raw.requests[0], 'prompt_sha256'), (self.raw.requests[0], 'synthetic')):
            with self.subTest(field=field):
                original = mapping.pop(field)
                self.assertIsNone(self.key())
                mapping[field] = original
        self.raw.artifacts.clear()
        self.assertIsNone(self.key())

    def test_only_the_model_package_may_change_and_a_singleton_has_no_comparator(self):
        a = {**self.row, 'comparison': self.key()}
        self.assertEqual(matched([a]), {})
        self.config.update(model_id='b', tokenizer_revision='b tokenizer', chat_template_sha256='b' * 64)
        self.config['launch']['model_file'] = 'b.gguf'
        self.raw.artifacts = {'b' * 64}
        b = {**self.row, 'comparison': self.key(), 'job_id': 'b', 'model': 'b'}
        self.assertEqual(a['comparison'], b['comparison'])
        self.assertEqual(list(matched([b, a]).values()), [[a, b]])
        self.assertEqual(matched([a, {**a, 'job_id': 'rerun'}]), {})


ORIGINS = {
    'schema_version': 1, 'checked_on': '2026-11-23', 'rule': 'fixture',
    'organizations': {'US Lab': {'country': 'US'}, 'Elsewhere': {'country': 'CN'}, 'Unchecked': {'country': None}},
    'models': {'us-model': {'developer': 'US Lab', 'bases': ['US Lab']}, 'us-on-foreign-base': {'developer': 'US Lab', 'bases': ['Elsewhere']},
               'foreign-model': {'developer': 'Elsewhere'}, 'unchecked-model': {'developer': 'Unchecked'}},
    'aliases': {'us-model-q4': 'us-model'},
}


class RenamedExperimentAndUsModelTests(unittest.TestCase):
    """Bundles of the experiment's former id `llm-routing`, the US-only ranking and the repository README summary."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        (self.root / 'catalog').mkdir()
        (self.root / 'catalog/model-origins.json').write_text(json.dumps(ORIGINS), encoding='utf-8')
        jobs, rows = [], []
        for i, (platform, model, quality, median) in enumerate([
                ('ollama', 'foreign-model', 1.0, 5.0), ('ollama', 'us-on-foreign-base', 1.0, 1.0), ('lmstudio', 'us-model-q4', 2 / 3, 2.0),
                ('ollama', 'us-model', 2 / 3, 3.0), ('koboldcpp', 'unchecked-model', 1.0, 0.5), ('lmstudio', 'nowhere-model', 1.0, 0.4)]):
            jobs.append(offload_job(f'j{i}', platform, model))
            rows.append(row(f'j{i}', 'coding', median, 10.0, quality=quality))
        bundle(self.root, 'model-offloading', 'campaign-o-offload', '2026-11-20T00:00:00+00:00', jobs, rows)
        bundle(self.root, 'llm-routing', 'campaign-l-routing', '2026-11-19T00:00:00+00:00',      # published under the former id
               [{'job_id': 'r1', 'experiment_id': 'llm-routing', 'mode': 'decision', 'case_id': 'ollama-tev1',
                 'hardware_config_id': 'raider-windows', 'hardware': {'os_id': 'windows-11-native'},
                 'parameters': {'router': {'kind': 'systemone', 'platform': 'ollama', 'model': 'llm-eval-tev1:locked'}}}],
               [row('r1', 'coding', 0.04, None, decisions=1.0)])

    def test_a_bundle_of_the_former_id_is_indexed_under_the_current_id(self):
        routing = next(r for r in collect(self.root) if r['case'] == 'ollama-tev1')
        self.assertEqual((routing['experiment'], routing['class'], routing['report']),
                         ('decision-models', None, 'llm-routing/campaign-l-routing/README.md'))
        write_results_index(self.root)
        index = self.root / 'docs/results/index'
        self.assertTrue((index / 'experiment/decision-models.md').is_file())
        self.assertFalse((index / 'experiment/llm-routing.md').exists())
        self.assertTrue((index / 'recommended/raider-windows/decision-models.md').is_file())
        text = (self.root / 'docs/results/README.md').read_text(encoding='utf-8')
        self.assertIn('[Evidence and reproduction](index/recommended/raider-windows/decision-models.md)', text)
        listed = next(line for line in text.splitlines() if '[Report](llm-routing/campaign-l-routing/README.md)' in line)
        self.assertTrue(listed.startswith('| decision-models | 2026-11-19T00:00:00+00:00 |'), listed)      # the link keeps its path

    def test_us_model_filter_preserves_lineage_and_all_runs(self):
        records = collect(self.root)
        self.assertEqual({r['model'] for r in records if us_model(r)}, {'us-model-q4', 'us-model'})
        self.assertEqual([lineage(next(r for r in records if r['model'] == m)['origin']) for m in
                          ('us-model-q4', 'us-on-foreign-base', 'nowhere-model')], ['US Lab', 'US Lab on Elsewhere base', 'not recorded'])
        write_results_index(self.root)
        page = (self.root / 'docs/results/index/origin/us.md').read_text(encoding='utf-8')
        self.assertIn('[us-model-q4]', page)
        self.assertNotIn('[unknown-model]', page)
        self.assertNotIn('[foreign-model]', page)
        self.assertNotIn('| Rank |', page)

    def test_readme_markers_preserve_outside_text(self):
        path = self.root / 'README.md'
        path.write_text(f'# Project\n\n{SUMMARY_START}\nold\n{SUMMARY_END}\n\nkept\n', encoding='utf-8')
        write_results_index(self.root)
        after = path.read_text(encoding='utf-8')
        self.assertTrue(after.endswith(f'{SUMMARY_END}\n\nkept\n'))
        self.assertIn('Evidence and reproduction', after)
        self.assertNotIn('\nold\n', after)
        path.write_text('# Project without markers\n', encoding='utf-8')
        write_results_index(self.root)
        self.assertEqual(path.read_text(encoding='utf-8'), '# Project without markers\n')


class LegalRenameIndexTests(unittest.TestCase):
    def test_a_legal_bundle_published_under_the_former_id_is_indexed_under_the_current_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            legal_bundle(root, 'campaign-old-smoke-legal-benchmark-1', '2026-11-18T00:00:00+00:00',
                         [legal_job('old1', 'fixture', experiment='legal-benchmark')], [], experiment='legal-benchmark')
            legal_bundle(root, 'campaign-new-smoke-legal-models-1', '2026-11-24T00:00:00+00:00', [legal_job('new1', 'fixture')], [])
            records = collect(root)
            self.assertEqual({(r['case'], r['experiment'], r['class'], r['ranked']) for r in records},
                             {('old1', 'legal-models', 'fixture', False), ('new1', 'legal-models', 'fixture', False)})
            write_results_index(root)
            index = root / 'docs/results/index'
            self.assertTrue((index / 'experiment/legal-models.md').is_file())
            self.assertFalse((index / 'experiment/legal-benchmark.md').exists())
            page = (index / 'experiment/legal-models.md').read_text(encoding='utf-8')
            self.assertIn('legal-benchmark/campaign-old-smoke-legal-benchmark-1/README.md', page)      # the old bundle keeps its path
            self.assertIn('legal-models/campaign-new-smoke-legal-models-1/README.md', page)


class ModelOriginsCatalogTests(unittest.TestCase):
    def test_every_entry_names_a_recorded_organization_and_a_source(self):
        root = Path(__file__).resolve().parents[1]
        data = json.loads((root / 'catalog/model-origins.json').read_text(encoding='utf-8'))
        organizations = data['organizations']
        for name, org in organizations.items():
            with self.subTest(organization=name):
                if org['country'] is None:
                    self.assertTrue(org['note'])
                else:
                    self.assertRegex(org['country'], r'^[A-Z]{2}$')
                    self.assertTrue(org['source'].startswith('https://'))
        for model, entry in data['models'].items():
            with self.subTest(model=model):
                self.assertIn(entry['developer'], organizations)
                self.assertLessEqual(set(entry.get('bases', [])), set(organizations))
                self.assertTrue(entry['source'].startswith('https://'))
        for alias, model in data['aliases'].items():
            self.assertIn(model, data['models'])
            self.assertNotIn(alias, data['models'])
        catalogued = {m['id'] for m in json.loads((root / 'catalog/models.json').read_text(encoding='utf-8'))['models']}
        self.assertEqual(sorted(catalogued - set(data['models'])), [])      # every catalogued model has an origin
        known = origins(root)
        self.assertEqual([m for m in ('nemotron-nano-30b', 'gemma4-26b-moe', 'phi4-reasoning-plus', 'nemotron-super-49b') if not known[m]['us']], [])
        self.assertEqual([m for m in ('deepseek-r1-70b', 'qwen38-27b-ud-q4_k_xl', 'llm-eval-nimble:locked', 'mistral-small31') if known[m]['us']], [])


if __name__ == '__main__':
    unittest.main()
