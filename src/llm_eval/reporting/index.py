"""Navigable indexes over the published result bundles in docs/results.

Every bundle (docs/results/EXPERIMENT/PUBLICATION/) carries manifest.json, resolved-config.json and summary.json.
From those alone this writes docs/results/index/: one page per hardware configuration, experiment, harness, model
and UTC date, plus an overview with a harness-by-model matrix per experiment. The same overview is placed between
the results-index markers of docs/results/EXECUTIVE_SUMMARY.md when that file has them.
"""
from __future__ import annotations

import json
import re
import shutil
from collections import defaultdict
from pathlib import Path

START = '<!-- results-index:start -->'
END = '<!-- results-index:end -->'
CATEGORIES = (('hardware', 'Hardware configuration'), ('experiment', 'Experiment'), ('harness', 'Harness'),
              ('model', 'Model'), ('date', 'Date (UTC)'))


def slug(value):
    return re.sub(r'[^a-z0-9._-]+', '-', str(value).lower()).strip('-') or 'unknown'


def identity(job):
    """(harness, model) of a planned job: the serving platform and the model it serves or routes with."""
    parameters = job.get('parameters') or {}
    config, router = parameters.get('config') or {}, parameters.get('router') or {}
    if config:
        return config.get('platform', 'unknown'), config.get('model_id', 'unknown')
    return router.get('platform') or router.get('kind', 'unknown'), router.get('model') or router.get('kind', 'unknown')


def _read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def _span(values):
    values = [v for v in values if isinstance(v, (int, float)) and not isinstance(v, bool)]
    if not values:
        return None
    low, high = min(values), max(values)
    return f'{low:.3g}' if f'{low:.3g}' == f'{high:.3g}' else f'{low:.3g}–{high:.3g}'


def _ratio(rows, rate, count):
    total = sum(r.get(count) or 0 for r in rows)
    if not total:
        return None
    return f"{round(sum((r.get(rate) or 0) * (r.get(count) or 0) for r in rows))}/{total}"


def collect(root):
    """One record per published job, newest first."""
    results = Path(root) / 'docs/results'
    records = []
    for manifest_path in sorted(results.glob('*/*/manifest.json')):
        bundle = manifest_path.parent
        manifest, resolved = _read(manifest_path), _read(bundle / 'resolved-config.json')
        summary = _read(bundle / 'summary.json') if (bundle / 'summary.json').exists() else []
        coverage = {c['job_id']: c for c in manifest.get('coverage', [])}
        for job in resolved.get('jobs', []):
            rows = [r for r in summary if r.get('job_id') == job['job_id']]
            harness, model = identity(job)
            config = (job.get('parameters') or {}).get('config') or {}
            records.append({
                'date': manifest['created_utc'][:10], 'created': manifest['created_utc'],
                'experiment': manifest['experiment_id'], 'mode': job.get('mode'),
                'campaign': manifest.get('campaign_id'), 'publication': manifest['publication_id'],
                'hardware': job.get('hardware_config_id', 'unknown'), 'os': (job.get('hardware') or {}).get('os_id'),
                'harness': harness, 'model': model, 'case': job.get('case_id'),
                'status': (coverage.get(job['job_id']) or {}).get('status', manifest.get('status')),
                'synthetic': bool(manifest.get('synthetic')),
                'output_cap': config.get('max_output_tokens'),
                'requests': sum(r.get('requests') or 0 for r in rows),
                'errors': sum(r.get('errors_or_missing') or 0 for r in rows),
                'wall_s': _span(r.get('elapsed_s_median') for r in rows),
                'tokens_per_s': _span(r.get('output_tokens_per_wall_second_median') for r in rows),
                'quality': _ratio(rows, 'quality_pass_rate', 'quality_check_n'),
                'decisions': _ratio(rows, 'decision_accuracy', 'decision_labelled_n'),
                'report': f"{bundle.parent.name}/{bundle.name}/README.md",
            })
    records.sort(key=lambda r: (r['experiment'], r['hardware'], r['harness'], r['model'], str(r['case'])))
    records.sort(key=lambda r: r['created'], reverse=True)
    return records


def _cell(value):
    return '–' if value is None else str(value).replace('|', '\\|')


def _link(category, value, index_prefix):
    return f"[{_cell(value)}]({index_prefix}{category}/{slug(value)}.md)"


def table(records, index_prefix, report_prefix):
    lines = ['| Date | Experiment | Hardware | Harness | Model | Case | Output cap | Status | Requests | Errors | '
             'Median wall s | Output tok/s | Quality | Decisions | Report |',
             '|---|---|---|---|---|---|---:|---|---:|---:|---:|---:|---:|---:|---|']
    for r in records:
        status = _cell(r['status']) + (' (synthetic)' if r['synthetic'] else '')
        lines.append('| ' + ' | '.join([
            _link('date', r['date'], index_prefix), _link('experiment', r['experiment'], index_prefix),
            _link('hardware', r['hardware'], index_prefix), _link('harness', r['harness'], index_prefix),
            _link('model', r['model'], index_prefix), _cell(r['case']), _cell(r['output_cap']), status,
            str(r['requests']), str(r['errors']), _cell(r['wall_s']), _cell(r['tokens_per_s']), _cell(r['quality']),
            _cell(r['decisions']), f"[report]({report_prefix}{r['report']})"]) + ' |')
    return '\n'.join(lines)


def overview(records, index_prefix, report_prefix):
    """Browse-by links and one harness-by-model matrix per experiment."""
    lines = ['### Browse by category', '', '| Category | Indexes (results) |', '|---|---|']
    for category, title in CATEGORIES:
        counts = defaultdict(int)
        for r in records:
            counts[r[category]] += 1
        values = sorted(counts, reverse=category == 'date')
        lines.append(f"| {title} | " + ' · '.join(f"{_link(category, v, index_prefix)} ({counts[v]})" for v in values) + ' |')
    several_hardware = len({r['hardware'] for r in records}) > 1
    for experiment in sorted({r['experiment'] for r in records}):
        chosen = [r for r in records if r['experiment'] == experiment]
        harnesses = sorted({r['harness'] for r in chosen})
        lines += ['', f"### {experiment}: models by harness", '',
                  'Each cell links to the report of every published run of that model on that harness, newest first.', '',
                  '| Model | ' + ' | '.join(_link('harness', h, index_prefix) for h in harnesses) + ' |',
                  '|---|' + '---|' * len(harnesses)]
        for model in sorted({r['model'] for r in chosen}):
            cells = []
            for harness in harnesses:
                runs = [r for r in chosen if r['model'] == model and r['harness'] == harness]
                cells.append('<br>'.join(
                    f"[{r['date']}{' ' + r['hardware'] if several_hardware else ''}"
                    f"{' cap ' + str(r['output_cap']) if r['output_cap'] else ''}"
                    f"{' synthetic' if r['synthetic'] else ''}{'' if r['status'] == 'succeeded' else ' ' + _cell(r['status'])}]"
                    f"({report_prefix}{r['report']})" for r in runs) or '–')
            lines.append(f"| {_link('model', model, index_prefix)} | " + ' | '.join(cells) + ' |')
    return '\n'.join(lines)


def write_results_index(root):
    """Regenerate docs/results/index and the marked block of the executive summary; returns the record count."""
    root = Path(root)
    results, index = root / 'docs/results', root / 'docs/results/index'
    records = collect(root)
    if index.exists():
        shutil.rmtree(index)
    index.mkdir(parents=True)

    def save(path, text):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8', newline='\n')

    note = ('Generated from the published bundles by `llm-eval index-results`; do not edit by hand. Ranges are the '
            'lowest and highest category medians of a job. Quality and decision counts are passes over applicable checks.')
    save(index / 'README.md', '# Results index\n\n' + note + '\n\n## Navigate\n\n' + overview(records, '', '../') +
         '\n\n## All results\n\n' + table(records, '', '../') + '\n')
    for category, title in CATEGORIES:
        for value in sorted({r[category] for r in records}):
            chosen = [r for r in records if r[category] == value]
            save(index / category / (slug(value) + '.md'),
                 f"# {title}: {value}\n\n[Results index](../README.md) · [Executive summary](../../EXECUTIVE_SUMMARY.md)\n\n"
                 f"{len(chosen)} published result(s). {note}\n\n" + table(chosen, '../', '../../') + '\n')
    executive = results / 'EXECUTIVE_SUMMARY.md'
    if executive.exists():
        text = executive.read_text(encoding='utf-8')
        if START in text and END in text:
            head, rest = text.split(START, 1)
            tail = rest.split(END, 1)[1]
            block = (f"{START}\n\n{overview(records, 'index/', '')}\n\nFull table and per-category pages: "
                     f"[results index](index/README.md).\n\n{END}")
            save(executive, head + block + tail)
    return len(records)
