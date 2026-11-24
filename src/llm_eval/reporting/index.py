"""Navigable indexes and the generated parts of the results README over the published bundles in docs/results.

Every bundle (docs/results/EXPERIMENT/PUBLICATION/) carries manifest.json, resolved-config.json, summary.json and its
raw measurements. From those this writes:

- docs/results/index/: one page per hardware configuration, experiment, harness, model and UTC date, plus an overview;
- docs/results/index/recommended/: the recommended setup, harness and model per hardware configuration and experiment
  (`recommend.py`);
- diagrams/results/summary/: one comparison chart per experiment and hardware configuration;
- the three marked blocks of docs/results/README.md: the top combinations with their charts (executive summary),
  the navigation matrices, and the list of published reports. Text outside the markers is hand-written and kept;
- the marked block of the repository README: the recommended model per platform, experiment and hardware configuration.

A bundle published under the former id of a renamed experiment is indexed under the experiment's current id. A model's
origin (catalog/model-origins.json) decides whether it is ranked among the US models.
"""
from __future__ import annotations

import gzip
import html
import json
import math
import re
import shutil
import statistics
from collections import defaultdict
from pathlib import Path

from llm_eval.experiments import canonical

TOP_START, TOP_END = '<!-- results-top:start -->', '<!-- results-top:end -->'
START, END = '<!-- results-index:start -->', '<!-- results-index:end -->'
LIST_START, LIST_END = '<!-- results-list:start -->', '<!-- results-list:end -->'
SUMMARY_START, SUMMARY_END = '<!-- summary-recommended:start -->', '<!-- summary-recommended:end -->'
ORIGINS = 'catalog/model-origins.json'
# (id, title, guide) of each experiment, in the order the repository README lists them.
EXPERIMENTS = (('hardware-fit', 'Hardware fit', 'experiments/hardware-fit/README.md'),
               ('model-offloading', 'Model offloading', 'experiments/model-offloading/README.md'),
               ('decision-models', 'Decision models', 'experiments/decision-models/README.md'),
               ('legal-models', 'Legal models', 'experiments/legal-models/README.md'))
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
RECOMMENDED = 'Recommended setup, harness and model per hardware configuration and experiment: [recommended setups]({link}).'
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


def _peaks(bundle):
    """{job_id: peak backend RSS and GPU memory in GiB} from the telemetry of each job's latest attempt."""
    raw, peaks = bundle / 'raw/measurements.jsonl.gz', defaultdict(dict)
    if not raw.exists():
        return peaks
    with gzip.open(raw, 'rt', encoding='utf-8') as lines:
        for line in lines:
            record = json.loads(line)
            if record.get('record_type') != 'telemetry' or not record.get('latest_attempt'):
                continue
            data, peak = record.get('data') or {}, peaks[record.get('job_id')]
            gpus = [g.get('used_mib') for g in data.get('gpus') or [] if g.get('used_mib') is not None]
            for key, value in (('backend_rss_gib', data.get('backend_tree_rss_gib')), ('gpu_gib', sum(gpus) / 1024 if gpus else None)):
                if value is not None:
                    peak[key] = max(peak.get(key, 0), value)
    return peaks


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
        peaks = _peaks(bundle)
        names = _identities(manifest, resolved)
        for job in resolved.get('jobs', []):
            rows = [r for r in summary if r.get('job_id') == job['job_id']]
            harness, model = identity(job)
            parameters = job.get('parameters') or {}
            config = parameters.get('config') or {}
            kind, rankable = _classified(names, manifest, job)
            records.append({
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
                'backend_rss_gib': peaks[job['job_id']].get('backend_rss_gib'), 'gpu_gib': peaks[job['job_id']].get('gpu_gib'),
                'report': f"{bundle.parent.name}/{bundle.name}/README.md",
                'execution_kind': parameters.get('execution_kind'), 'data_class': parameters.get('data_class'),
                'cohorts': list(parameters['cohorts']) if isinstance(parameters.get('cohorts'), list) else [],
                'class': kind, 'ranked': rankable, 'origin': origin.get(model),
            })
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


RANKING_RULE = ('Ranked by share of checks passed (correct decisions for decision models, quality checks otherwise), '
                'then lower median wall time per request, then higher output tokens per second. Each harness and model '
                'combination is represented by its newest measured run that succeeded; synthetic fixtures, failed runs and '
                'runs without scored checks are not ranked. Wall time and token rate are the median of the category medians. Where a model '
                'repeats among the best combinations, a second table ranks the models, each by its best combination.')
CHART_NOTE = ('Chart: every ranked combination, best-ranked model first, one color per harness. Each panel has its own '
              'axis; wall time is on a log scale. Exact values are in the tables of this page and in the linked reports.')
US_RULE = ('US models only, by the same ranking: models whose developer, and the developer of every base model they were '
           'fine-tuned, distilled or pruned from, are headquartered in the United States ([model origins]({link})).')


def us_model(record):
    """Whether the record's model is a US model by catalog/model-origins.json; a model without an origin record is not."""
    return bool((record.get('origin') or {}).get('us'))


def ranked(records, keep=None):
    """{(experiment, hardware): every rankable harness and model combination, best first}; `keep(record)`, when given,
    narrows the records first (for example to US models)."""
    newest = {}
    for r in records:      # records arrive newest first
        if not r.get('ranked', True) or r['synthetic'] or r['status'] != 'succeeded' or not r['score']:
            continue
        if keep and not keep(r):
            continue
        newest.setdefault((r['experiment'], r['hardware'], r['harness'], r['model']), r)
    groups = defaultdict(list)
    for (experiment, hardware, _, _), r in newest.items():
        groups[(experiment, hardware)].append(r)

    def order(r):
        return (-r['score'][0] / r['score'][1], r['wall_mid'] if r['wall_mid'] is not None else float('inf'),
                -(r['tokens_mid'] or 0), r['harness'], r['model'])
    return {key: sorted(groups[key], key=order) for key in sorted(groups)}


TOP_LIMIT = 5      # rows of the ranking per experiment and hardware configuration


def top_combinations(records, limit=TOP_LIMIT, keep=None):
    """{(experiment, hardware): best `limit` records}, one record per harness and model combination."""
    return {key: chosen[:limit] for key, chosen in ranked(records, keep).items()}


def top_models(records, limit=TOP_LIMIT, keep=None):
    """{(experiment, hardware): best `limit` records}, one per model: the model's best harness and model combination."""
    out = {}
    for key, chosen in ranked(records, keep).items():
        best = {}
        for r in chosen:      # best combination first, so a model keeps its best harness
            best.setdefault(r['model'], r)
        out[key] = list(best.values())[:limit]
    return out


def ranking(records, index_prefix, report_prefix, limit=TOP_LIMIT, charts=None):
    """Top combinations per experiment and hardware configuration, and the top models where a model repeats among them;
    `charts` maps such a pair to an image link."""
    lines = [f'### Top {limit} harness and model combinations per experiment and hardware configuration', '', RANKING_RULE,
             'Each pair then ranks US models alone. ' + US_RULE.format(link=report_prefix + '../MODELS.md#model-origins')]
    pairs = list(dict.fromkeys((r['experiment'], r['hardware']) for r in records if r.get('ranked', True)))      # newest result first
    best, models = top_combinations(records, limit), top_models(records, limit)
    us_best, us_models, every = top_combinations(records, limit, us_model), top_models(records, limit, us_model), ranked(records)

    def row(rank, r, first, second, *more):
        return (f"| {rank} | {first} | {second} | " + ''.join(f'{cell} | ' for cell in more) + f"{r['score'][0]}/{r['score'][1]} | "
                f"{_cell(None if r['wall_mid'] is None else format(r['wall_mid'], '.3g'))} | "
                f"{_cell(None if r['tokens_mid'] is None else format(r['tokens_mid'], '.3g'))} | "
                f"[{r['date']}{' cap ' + str(r['output_cap']) if r['output_cap'] else ''}]({report_prefix}{r['report']}) |")
    for experiment, hardware in pairs:
        lines += ['', f"**{_link('experiment', experiment, index_prefix)} on {_link('hardware', hardware, index_prefix)}**", '']
        chosen = best.get((experiment, hardware))
        if not chosen:
            lines.append('No measured run with scored checks has been published yet.')
            continue
        lines += ['| Rank | Harness | Model | Checks passed | Median wall s | Output tok/s | Run |', '|---:|---|---|---:|---:|---:|---|']
        lines += [row(rank, r, _link('harness', r['harness'], index_prefix), _link('model', r['model'], index_prefix))
                  for rank, r in enumerate(chosen, 1)]
        if models[(experiment, hardware)] != chosen:      # a model repeats among the best combinations: rank the models too
            lines += ['', f'Top {limit} models, each on its best-ranked harness:', '',
                      '| Rank | Model | Harness | Checks passed | Median wall s | Output tok/s | Run |', '|---:|---|---|---:|---:|---:|---|']
            lines += [row(rank, r, _link('model', r['model'], index_prefix), _link('harness', r['harness'], index_prefix))
                      for rank, r in enumerate(models[(experiment, hardware)], 1)]
        lines += ['', f'Top {limit} harness and model combinations of US models:', '']
        us = us_best.get((experiment, hardware))
        if us:
            lines += ['| Rank | Harness | Model | Developer | Checks passed | Median wall s | Output tok/s | Run |',
                      '|---:|---|---|---|---:|---:|---:|---|']
            lines += [row(rank, r, _link('harness', r['harness'], index_prefix), _link('model', r['model'], index_prefix),
                          _cell(lineage(r['origin']))) for rank, r in enumerate(us, 1)]
            if us_models[(experiment, hardware)] != us:      # a US model repeats: rank the US models too
                lines += ['', f'Top {limit} US models, each on its best-ranked harness:', '',
                          '| Rank | Model | Harness | Developer | Checks passed | Median wall s | Output tok/s | Run |',
                          '|---:|---|---|---|---:|---:|---:|---|']
                lines += [row(rank, r, _link('model', r['model'], index_prefix), _link('harness', r['harness'], index_prefix),
                              _cell(lineage(r['origin']))) for rank, r in enumerate(us_models[(experiment, hardware)], 1)]
        else:
            lines.append('No measured run of a US model with scored checks has been published for this pair.')
        shown = list(dict.fromkeys(r['model'] for r in chosen if not r.get('origin')))      # of the combinations in the first table
        others = len({r['model'] for r in every[(experiment, hardware)] if not r.get('origin')} - set(shown))
        if shown or others:
            lines += ['', 'Origin not recorded, so not ranked among US models: ' + ', '.join(f'`{_cell(m)}`' for m in shown) +
                      (('; and ' if shown else '') + f'{others} more model(s) ranked below the top {limit}' if others else '') + '.']
        if (charts or {}).get((experiment, hardware)):
            lines += ['', f"![{experiment} on {hardware}: harness and model combinations compared]({charts[(experiment, hardware)]})", '', CHART_NOTE]
    return '\n'.join(lines)


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


def summary(records):
    """The recommended model per platform, experiment and hardware configuration, for the repository README: one table per
    hardware configuration (newest result first), one row per experiment, one column per platform with a ranked run. A cell
    names the best-ranked model on that platform and, on a second line, the best-ranked US model."""
    every, us = ranked(records), ranked(records, us_model)
    index, results = 'docs/results/index/', 'docs/results/'
    known = [e for e, _, _ in EXPERIMENTS]
    titles = {e: (title, guide) for e, title, guide in EXPERIMENTS}
    order = list(PLATFORMS)

    def best(chosen, harness):
        return next((r for r in chosen if r['harness'] == harness), None)

    def text(r):
        wall = '' if r['wall_mid'] is None else f", {format(r['wall_mid'], '.3g')} s"
        return f"{_link('model', r['model'], index)} [{r['score'][0]}/{r['score'][1]}{wall}]({results}{r['report']})"
    lines = ['Generated by `llm-eval index-results` from the published bundles; do not edit between the markers. Each cell is '
             'the best-ranked model on that platform: checks passed and median wall time per request, linked to the report of '
             'its run, which records the run configuration. The second line is the best-ranked US model (developer and base '
             'models from the United States). "–" means no measured run with scored checks on that platform. The ranking is '
             f'the one of the [results]({results}README.md); the [recommended setups]({index}recommended/README.md) pages give '
             'the configuration of the best-ranked run of each experiment and hardware configuration.']
    for hardware in dict.fromkeys(r['hardware'] for r in records):      # records arrive newest first
        here = [r for r in records if r['hardware'] == hardware]
        harnesses = sorted({r['harness'] for (_, h), chosen in every.items() if h == hardware for r in chosen},
                           key=lambda h: (order.index(h) if h in order else len(order), h))
        lines += ['', f"**{_link('hardware', hardware, index)}**", '']
        if not harnesses:
            lines.append('No measured run with scored checks has been published for this hardware configuration yet.')
            continue
        lines += ['| Experiment | ' + ' | '.join(_cell(PLATFORMS.get(h, h)) for h in harnesses) + ' |', '|---|' + '---|' * len(harnesses)]
        experiments = known + sorted({r['experiment'] for r in here} - set(known))
        unranked = []
        for experiment in experiments:
            title, guide = titles.get(experiment, (experiment, None))
            name = f'[{_cell(title)}]({guide})' if guide else _cell(title)
            chosen, chosen_us = every.get((experiment, hardware), []), us.get((experiment, hardware), [])
            if not chosen and any(r['experiment'] == experiment for r in here):
                unranked.append(name)
            cells = []
            for harness in harnesses:
                top = best(chosen, harness)
                if top is None:
                    cells.append('–')
                    continue
                top_us = best(chosen_us, harness)
                cells.append(text(top) + '<br>US: ' + (text(top_us) if top_us else 'none measured'))
            lines.append(f'| {name} | ' + ' | '.join(cells) + ' |')
        if unranked:
            lines += ['', 'Published here but not ranked (fixture runs only, or results published by class and cohort): '
                      + ', '.join(unranked) + '.']
    return '\n'.join(lines)


def overview(records, index_prefix, report_prefix):
    """Top combinations, then the navigation, then the results by class and cohort (when there are any)."""
    cohorts = cohort_results(records, index_prefix, report_prefix)
    return ranking(records, index_prefix, report_prefix) + '\n\n' + navigation(records, index_prefix, report_prefix) + \
        ('\n\n' + cohorts if cohorts else '')


def listing(root):
    """One row per published report, newest first; a report published under a renamed experiment's former id is listed
    under the current id (its link keeps the path it was published at)."""
    results, rows = Path(root) / 'docs/results', []
    for path in results.glob('*/*/manifest.json'):
        m, link = _read(path), (path.parent / 'README.md').relative_to(results).as_posix()
        synthetic = ', '.join(sorted(m.get('execution_kinds') or [])) if 'projection' in m else m['synthetic']
        rows.append((m['created_utc'], f"| {_cell(canonical(m['experiment_id']))} | {_cell(m['created_utc'])} | {_cell(m['status'])} | {_cell(synthetic)} | [Report]({link}) |"))
    return '\n'.join([LEGACY_LIST_HEADER, '|---|---|---|---|---|'] + [row for _, row in sorted(rows, reverse=True)])


def write_charts(root, records):
    """Redraw the summary charts; {(experiment, hardware): link relative to docs/results}. Needs the reporting extra."""
    from . import charts
    directory, links = Path(root) / CHARTS, {}
    if directory.exists():
        shutil.rmtree(directory)
    if not charts.available():
        return links
    for (experiment, hardware), chosen in ranked(records).items():
        if len(chosen) < 2:      # a single combination is a number, not a comparison
            continue
        name = f"{slug(experiment)}-{slug(hardware)}.png"
        charts.summary_chart(chosen, directory / name, f"{experiment} on {hardware}: newest succeeded run of each harness and model")
        links[(experiment, hardware)] = f"../../{CHARTS}/{name}"
    return links


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
    from .recommend import write_recommendations      # imported here: that module imports this one
    write_recommendations(root, records, index)
    readme = results / 'README.md'
    text = readme.read_text(encoding='utf-8') if readme.exists() else ''
    if not text or (LEGACY_LIST_HEADER in text and LIST_START not in text):      # absent, or the fully generated list of earlier versions
        text = SKELETON
    if TOP_START in text and TOP_END in text:
        text = _fill(text, TOP_START, TOP_END, ranking(records, 'index/', '', charts=write_charts(root, records)))
    cohorts = cohort_results(records, 'index/', '')
    text = _fill(text, START, END, navigation(records, 'index/', '') + ('\n\n' + cohorts if cohorts else '') +
                 '\n\nFull table and per-category pages: [results index](index/README.md). ' + RECOMMENDED.format(link='index/recommended/README.md'))
    text = _fill(text, LIST_START, LIST_END, listing(root))
    save(readme, text)
    top = root / 'README.md'      # the repository README: only its marked block is generated
    if top.is_file():
        text = top.read_text(encoding='utf-8')
        if SUMMARY_START in text and SUMMARY_END in text:
            save(top, _fill(text, SUMMARY_START, SUMMARY_END, summary(records)))
    return len(records)
