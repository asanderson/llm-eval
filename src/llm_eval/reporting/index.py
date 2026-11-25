"""Regenerate navigation, evidence cards and within-publication comparisons from published bundles."""
from __future__ import annotations

import html
import json
import math
import re
import shutil
import statistics
from collections import defaultdict
from pathlib import Path

from llm_eval.common import digest
from llm_eval.experiments import canonical
from . import evidence

TOP_START, TOP_END = '<!-- results-top:start -->', '<!-- results-top:end -->'
START, END = '<!-- results-index:start -->', '<!-- results-index:end -->'
LIST_START, LIST_END = '<!-- results-list:start -->', '<!-- results-list:end -->'
SUMMARY_START, SUMMARY_END = '<!-- summary-recommended:start -->', '<!-- summary-recommended:end -->'
ORIGINS = 'catalog/model-origins.json'
PLATFORMS = {'ollama': 'Ollama', 'lmstudio': 'LM Studio', 'koboldcpp': 'KoboldCpp', 'llama.cpp': 'llama.cpp',
             'ik_llama.cpp': 'ik_llama.cpp', 'ktransformers': 'KTransformers', 'vllm': 'vLLM', 'accelerate': 'Accelerate',
             'airllm': 'AirLLM', 'strata': 'Strata'}      # display names, in the order the summary columns take
LEGACY_LIST_HEADER = '| Experiment | Run time UTC | Status | Synthetic | Results |'
SKELETON = f"""# Experiment results

Each report includes raw measurements, summaries and reproducibility metadata. Synthetic fixtures are explicitly labeled. Newest results are listed first.

## Executive summary

{TOP_START}
{TOP_END}

## Results index

{START}
{END}

## All published reports

{LIST_START}
{LIST_END}
"""
CHARTS = 'diagrams/results/summary'
RECOMMENDED = 'Inspect workloads, placement and reproducibility details in the [setup evidence]({link}).'
CATEGORIES = (('hardware', 'Hardware configuration'), ('experiment', 'Experiment'), ('harness', 'Harness'),
              ('model', 'Model'), ('date', 'Date (UTC)'))


def slug(value):
    return re.sub(r'[^a-z0-9._-]+', '-', str(value).lower()).strip('-') or 'unknown'


def identity(job):
    """(harness, model) of a planned job: the serving platform and the model it serves or routes with."""
    parameters = job.get('parameters') or {}
    if isinstance(parameters.get('identity'), dict):      # a projected job names its harness and model explicitly
        return parameters['identity'].get('harness', 'unknown'), parameters['identity'].get('model', 'unknown')
    config, router = parameters.get('config') or {}, parameters.get('router') or {}
    if config:
        return config.get('platform', 'unknown'), config.get('model_id', 'unknown')
    return router.get('platform') or router.get('kind', 'unknown'), router.get('model') or router.get('kind', 'unknown')


def _read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def origins(root):
    """{model id as the results name it: {'developer', 'bases', 'us'}} from catalog/model-origins.json, aliases included;
    {} when the file is absent. `us` is True only when the developer and every base model's developer are organizations
    the file places in the United States."""
    path = Path(root) / ORIGINS
    if not path.is_file():
        return {}
    data = _read(path)
    countries = {name: org.get('country') for name, org in data['organizations'].items()}
    out = {}
    for model, entry in data['models'].items():
        bases = list(entry.get('bases') or [])
        out[model] = {'developer': entry['developer'], 'bases': bases,
                      'us': all(countries.get(org) == 'US' for org in [entry['developer'], *bases])}
    for alias, model in (data.get('aliases') or {}).items():
        out[alias] = out[model]
    return out


def lineage(origin):
    """The developer of a model and the developers of its base models, as one cell."""
    if not origin:
        return 'not recorded'
    others = [org for org in dict.fromkeys(origin['bases']) if org != origin['developer']]      # its own base adds nothing
    return origin['developer'] + (' on ' + ', '.join(others) + ' base' if others else '')


def _span(values):
    values = [v for v in values if isinstance(v, (int, float)) and not isinstance(v, bool)]
    if not values:
        return None
    low, high = min(values), max(values)
    return f'{low:.3g}' if f'{low:.3g}' == f'{high:.3g}' else f'{low:.3g}–{high:.3g}'


def _counts(rows, rate, count):
    total = sum(r.get(count) or 0 for r in rows)
    if not total:
        return None
    passed = sum((r.get(rate) or 0) * (r.get(count) or 0) for r in rows)
    if not math.isfinite(passed):      # a hostile bundle's numbers: no count rather than an OverflowError
        return None
    return round(passed), total


def _ratio(rows, rate, count):
    counts = _counts(rows, rate, count)
    return None if counts is None else f"{counts[0]}/{counts[1]}"


def _middle(values):
    values = [v for v in values if isinstance(v, (int, float)) and not isinstance(v, bool)]
    return statistics.median(values) if values else None


KINDS = {'fixture': 'fixture', 'model-run': 'measured', 'score-only': 'score-only'}
CLASSES = (('fixture', 'Fixture runs'), ('measured', 'Measured runs'), ('score-only', 'Score-only runs'), ('invalid', 'Invalid bundles'),
           ('legacy', 'Legacy bundles'))


def _identities(manifest, resolved):
    """Every experiment identity a bundle carries, as `publish_report` collects them, each by its current id."""
    experiment = resolved.get('experiment') if isinstance(resolved.get('experiment'), dict) else {}
    names = {manifest.get('experiment_id'), experiment.get('experiment_id'),
             *(j.get('experiment_id') for j in resolved.get('jobs', []) if isinstance(j, dict))}
    return {canonical(str(n)) for n in names if n is not None}


def _classified(names, manifest, job):
    """(class, ranked) of one job: `class` is None for a bundle of an experiment without a report projection."""
    from llm_eval.experiments import plugin_hook
    if len(names) > 1:
        kind = 'invalid'
    elif 'projection' in manifest:
        kind = KINDS.get((job.get('parameters') or {}).get('execution_kind'), 'invalid')
    else:
        kind = 'legacy' if plugin_hook(next(iter(names)), 'report_projection') else None
    generic = all(plugin_hook(n, 'GENERIC_RANKING') is not False for n in names)
    return kind, kind not in ('invalid', 'legacy') and generic


def collect(root):
    """One record per published job, newest first."""
    results = Path(root) / 'docs/results'
    records, origin = [], origins(root)
    for manifest_path in sorted(results.glob('*/*/manifest.json')):
        bundle = manifest_path.parent
        manifest, resolved = _read(manifest_path), _read(bundle / 'resolved-config.json')
        summary = _read(bundle / 'summary.json') if (bundle / 'summary.json').exists() else []
        coverage = {c['job_id']: c for c in manifest.get('coverage', [])}
        observations = evidence.read_bundle(bundle)
        legal_path = bundle / 'legal-summary.json'
        legal_rows = _read(legal_path).get('cohorts', []) if legal_path.is_file() else []
        downloads = [name for name in ('resolved-config.json', 'manifest.json', 'summary.csv', 'raw/measurements.jsonl.gz',
                                       'legal-summary.json') if (bundle / name).is_file()]
        names = _identities(manifest, resolved)
        for job in resolved.get('jobs', []):
            rows = [r for r in summary if r.get('job_id') == job['job_id']]
            harness, model = identity(job)
            parameters = job.get('parameters') or {}
            config = parameters.get('config') or {}
            kind, rankable = _classified(names, manifest, job)
            raw = observations[job['job_id']]
            record = {
                'date': manifest['created_utc'][:10], 'created': manifest['created_utc'],
                'experiment': canonical(manifest['experiment_id']), 'mode': job.get('mode'),
                'campaign': manifest.get('campaign_id'), 'publication': manifest['publication_id'],
                'hardware': job.get('hardware_config_id', 'unknown'), 'os': (job.get('hardware') or {}).get('os_id'),
                'harness': harness, 'model': model, 'case': job.get('case_id'),
                'status': (coverage.get(job['job_id']) or {}).get('status', manifest.get('status')),
                'synthetic': bool(parameters.get('synthetic')) if 'projection' in manifest else bool(manifest.get('synthetic')),
                'output_cap': config.get('max_output_tokens'),
                'requests': sum(r.get('requests') or 0 for r in rows),
                'errors': sum(r.get('errors_or_missing') or 0 for r in rows),
                'wall_s': _span(r.get('elapsed_s_median') for r in rows),
                'tokens_per_s': _span(r.get('output_tokens_per_wall_second_median') for r in rows),
                'quality': _ratio(rows, 'quality_pass_rate', 'quality_check_n'),
                'decisions': _ratio(rows, 'decision_accuracy', 'decision_labelled_n'),
                # Ranking inputs: correct decisions where the experiment labels them, otherwise quality passes.
                'score': _counts(rows, 'decision_accuracy', 'decision_labelled_n') or _counts(rows, 'quality_pass_rate', 'quality_check_n'),
                'wall_mid': _middle(r.get('elapsed_s_median') for r in rows),
                'tokens_mid': _middle(r.get('output_tokens_per_wall_second_median') for r in rows),
                'backend_rss_gib': raw.peaks.get('backend_rss_gib'), 'gpu_gib': raw.peaks.get('gpu_gib'),
                'report': f"{bundle.parent.name}/{bundle.name}/README.md",
                'execution_kind': parameters.get('execution_kind'), 'data_class': parameters.get('data_class'),
                'cohorts': list(parameters['cohorts']) if isinstance(parameters.get('cohorts'), list) else [],
                'class': kind, 'ranked': rankable, 'origin': origin.get(model),
                'job_id': job['job_id'], 'downloads': downloads, 'revision': manifest.get('code_revision'),
                'context': config.get('context_tokens'), 'protocol': config.get('protocol') or (parameters.get('router') or {}).get('kind'),
                'backend_version': config.get('backend_version'), 'gpu': (job.get('hardware_profile') or {}).get('gpu') or {},
                'reason': (coverage.get(job['job_id']) or {}).get('reason'), 'observation': raw.measured(),
                'legal': raw.legal, 'legal_rows': [l for l in legal_rows if l.get('job_id') == job['job_id']],
                'launch': config.get('launch') or {}, 'config_sha256': job.get('config_sha256'),
                'model_revision': (parameters.get('router') or {}).get('model_revision'),
            }
            controls = evidence.comparison_controls(manifest, job, raw, record)
            record['comparison'] = digest(controls) if controls else None
            record['controls'] = controls
            records.append(record)
    records.sort(key=lambda r: (r['experiment'], r['hardware'], r['harness'], r['model'], str(r['case'])))
    records.sort(key=lambda r: r['created'], reverse=True)
    return records


def _cell(value):
    """A table cell: line breaks become spaces and `&`, `<`, `>`, `[`, `]` and `|` are escaped, so a value is inert text. No
    value of the published bundles holds one of these characters but `|`, so their cells are unchanged."""
    if value is None:
        return '–'
    text = ' '.join(str(value).splitlines())
    return html.escape(text, quote=False).replace('[', '\\[').replace(']', '\\]').replace('|', '\\|')


def _link(category, value, index_prefix):
    return f"[{_cell(value)}]({index_prefix}{category}/{slug(value)}.md)"


def table(records, index_prefix, report_prefix):
    lines = ['| Date | Experiment | Hardware | Harness | Model | Case | Output cap | Status | Requests | Errors | '
             'Median wall s | Output tok/s | Quality | Decisions | Report |',
             '|---|---|---|---|---|---|---:|---|---:|---:|---:|---:|---:|---:|---|']
    for r in records:
        status = _cell(r['status']) + (f" ({r['class']})" if r.get('class') else ' (synthetic)' if r['synthetic'] else '')
        lines.append('| ' + ' | '.join([
            _link('date', r['date'], index_prefix), _link('experiment', r['experiment'], index_prefix),
            _link('hardware', r['hardware'], index_prefix), _link('harness', r['harness'], index_prefix),
            _link('model', r['model'], index_prefix), _cell(r['case']), _cell(r['output_cap']), status,
            str(r['requests']), str(r['errors']), _cell(r['wall_s']), _cell(r['tokens_per_s']), _cell(r['quality']),
            _cell(r['decisions']), f"[report]({report_prefix}{r['report']})"]) + ' |')
    return '\n'.join(lines)


def us_model(record):
    return bool((record.get('origin') or {}).get('us'))


def matched(records):
    """Comparable model packages with the same complete controls. Keep every run, ordered by model."""
    groups = defaultdict(list)
    for r in records:
        if r.get('comparison'):
            groups[r['comparison']].append(r)
    return {key: sorted(group, key=lambda r: (r['model'], r['job_id'])) for key, group in sorted(groups.items())
            if len({r['model'] for r in group}) > 1}


def navigation(records, index_prefix, report_prefix):
    """Browse-by links and one harness-by-model matrix per experiment, newest results first."""
    lines = ['### Browse by category', '', '| Category | Indexes (results) |', '|---|---|']
    for category, title in CATEGORIES:
        counts = defaultdict(int)
        for r in records:
            counts[r[category]] += 1
        values = sorted(counts, reverse=category == 'date')
        lines.append(f"| {title} | " + ' · '.join(f"{_link(category, v, index_prefix)} ({counts[v]})" for v in values) + ' |')
    several_hardware = len({r['hardware'] for r in records}) > 1
    for experiment in dict.fromkeys(r['experiment'] for r in records):      # records arrive newest first
        chosen = [r for r in records if r['experiment'] == experiment]
        harnesses = sorted({r['harness'] for r in chosen})
        lines += ['', f"### {_cell(experiment)}: models by harness", '',
                  'Each cell links to the report of every published run of that model on that harness, newest first. '
                  'Models are ordered by their newest run.', '',
                  '| Model | ' + ' | '.join(_link('harness', h, index_prefix) for h in harnesses) + ' |',
                  '|---|' + '---|' * len(harnesses)]
        for model in dict.fromkeys(r['model'] for r in chosen):
            cells = []
            for harness in harnesses:
                runs = [r for r in chosen if r['model'] == model and r['harness'] == harness]
                cells.append('<br>'.join(
                    f"[{r['date']}{' ' + _cell(r['hardware']) if several_hardware else ''}"
                    f"{' cap ' + str(r['output_cap']) if r['output_cap'] else ''}"
                    f"{' ' + r['class'] if r.get('class') else ' synthetic' if r['synthetic'] else ''}"
                    f"{'' if r['status'] == 'succeeded' else ' ' + _cell(r['status'])}]"
                    f"({report_prefix}{r['report']})" for r in runs) or '–')
            lines.append(f"| {_link('model', model, index_prefix)} | " + ' | '.join(cells) + ' |')
    return '\n'.join(lines)


def cohort_results(records, index_prefix, report_prefix):
    """Results of experiments with a report projection, one table per class (fixture, measured, score-only, then invalid and
    legacy bundles), one row per job with every cohort of the job. The summary rows of a job name no cohort, so the count
    is the job's total and is shown once, not beside each cohort. Empty when no record has a class."""
    classed = [r for r in records if r.get('class')]
    if not classed:
        return ''
    lines = ['### Results by class and cohort', '', 'These results are not ranked with other experiments. Two runs are comparable '
             'only when their cohort digests are equal; fixture and score-only runs do not measure a model.']
    for name, title in CLASSES:
        chosen = [r for r in classed if r['class'] == name]
        if not chosen:
            continue
        lines += ['', f'**{title}** ({name})', '',
                  '| Experiment | Cohorts | Mode | OS | Harness | Model | Status | Checks passed, all cohorts of the job | Run |',
                  '|---|---|---|---|---|---|---|---:|---|']
        for r in chosen:
            lines.append('| ' + ' | '.join([
                _link('experiment', r['experiment'], index_prefix), _cell(', '.join(str(c)[:12] for c in r['cohorts']) or None), _cell(r['mode']),
                _cell(r['os']), _link('harness', r['harness'], index_prefix), _link('model', r['model'], index_prefix),
                f"{_cell(r['status'])} ({name})", _cell(r['quality']), f"[{r['date']}]({report_prefix}{r['report']})"]) + ' |')
    return '\n'.join(lines)


def overview(records, index_prefix, report_prefix):
    cohorts = cohort_results(records, index_prefix, report_prefix)
    return navigation(records, index_prefix, report_prefix) + ('\n\n' + cohorts if cohorts else '')


def listing(root):
    """One row per published report, newest first; a report published under a renamed experiment's former id is listed
    under the current id (its link keeps the path it was published at)."""
    results, rows = Path(root) / 'docs/results', []
    for path in results.glob('*/*/manifest.json'):
        m, link = _read(path), (path.parent / 'README.md').relative_to(results).as_posix()
        synthetic = ', '.join(sorted(m.get('execution_kinds') or [])) if 'projection' in m else m['synthetic']
        rows.append((m['created_utc'], f"| {_cell(canonical(m['experiment_id']))} | {_cell(m['created_utc'])} | {_cell(m['status'])} | {_cell(synthetic)} | [Report]({link}) |"))
    return '\n'.join(['| Experiment | Publication time UTC | Status | Synthetic flag or execution kinds | Results |', '|---|---|---|---|---|'] + [row for _, row in sorted(rows, reverse=True)])


def _fill(text, start, end, body):
    if start not in text or end not in text:
        return text
    head, rest = text.split(start, 1)
    return f"{head}{start}\n\n{body}\n\n{end}{rest.split(end, 1)[1]}"


def write_results_index(root):
    """Regenerate docs/results/index, the summary charts and the marked blocks of the results README; returns the record count."""
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
    save(index / 'README.md', '# Results index\n\n' + note + '\n\n' + RECOMMENDED.format(link='recommended/README.md') +
         '\n\n## Navigate\n\n' + overview(records, '', '../') + '\n\n## All results\n\n' + table(records, '', '../') + '\n')
    for category, title in CATEGORIES:
        for value in sorted({r[category] for r in records}):
            chosen = [r for r in records if r[category] == value]
            save(index / category / (slug(value) + '.md'),
                 f"# {title}: {_cell(value)}\n\n[Results index](../README.md) · [Executive summary](../../README.md)\n\n"
                 f"{len(chosen)} published result(s). {note}\n\n" + table(chosen, '../', '../../') + '\n')
    from .recommend import highlights, write_evidence
    write_evidence(root, records, index)
    readme = results / 'README.md'
    text = readme.read_text(encoding='utf-8') if readme.exists() else ''
    if not text or (LEGACY_LIST_HEADER in text and LIST_START not in text):      # absent, or the fully generated list of earlier versions
        text = SKELETON
    if TOP_START in text and TOP_END in text:
        text = _fill(text, TOP_START, TOP_END, highlights(records, 'index/', ''))
    cohorts = cohort_results(records, 'index/', '')
    text = _fill(text, START, END, navigation(records, 'index/', '') + ('\n\n' + cohorts if cohorts else '') +
                 '\n\nFull table and per-category pages: [results index](index/README.md). ' + RECOMMENDED.format(link='index/recommended/README.md'))
    text = _fill(text, LIST_START, LIST_END, listing(root))
    save(readme, text)
    top = root / 'README.md'      # the repository README: only its marked block is generated
    if top.is_file():
        text = top.read_text(encoding='utf-8')
        if SUMMARY_START in text and SUMMARY_END in text:
            save(top, _fill(text, SUMMARY_START, SUMMARY_END, highlights(records, 'docs/results/index/', 'docs/results/')))
    return len(records)
