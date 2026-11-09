import json
import re
import tempfile
import unittest
from pathlib import Path

from llm_eval.reporting.index import END, START, collect, identity, slug, top_combinations, write_results_index


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
        self.summary = self.root / 'docs/results/EXECUTIVE_SUMMARY.md'
        self.summary.write_text(f'# Summary\n\nintro\n\n{START}\nstale\n{END}\n\nnarrative stays\n', encoding='utf-8')

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
        self.assertTrue(text.startswith('# Summary\n\nintro\n\n' + START))
        self.assertTrue(text.endswith(END + '\n\nnarrative stays\n'))
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
        self.assertIn(heading, (self.root / 'docs/results/index/README.md').read_text(encoding='utf-8'))

    def test_results_readme_lists_newest_first(self):
        from llm_eval.reporting.publish import write_index
        write_index(self.root)
        rows = [line for line in (self.root / 'docs/results/README.md').read_text(encoding='utf-8').splitlines() if '[Report]' in line]
        self.assertEqual([line.split('](')[1].split('/')[1] for line in rows],
                         ['campaign-b-offload', 'campaign-a-offload', 'campaign-a-routing'])

    def test_a_summary_without_markers_is_left_alone(self):
        self.summary.write_text('# Summary\n\nhand written\n', encoding='utf-8')
        write_results_index(self.root)
        self.assertEqual(self.summary.read_text(encoding='utf-8'), '# Summary\n\nhand written\n')


if __name__ == '__main__':
    unittest.main()
