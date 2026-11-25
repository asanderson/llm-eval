"""Reader-facing evidence cards, setup pages and machine-readable matched comparisons."""
from __future__ import annotations

import json
import os
import re
import shutil
from collections import Counter, defaultdict
from pathlib import Path
from statistics import median

from .index import CHARTS, PLATFORMS, _cell, _link, matched, slug, table, us_model

UNKNOWN = 'not recorded'
FIT = 'hardware-fit'


def value(v):
    if isinstance(v, float):
        v = int(v) if v.is_integer() else f'{v:.3g}'
    return UNKNOWN if v is None else _cell(v)


def span(values):
    if not values:
        return UNKNOWN
    return value(min(values)) if min(values) == max(values) else f'{value(min(values))}–{value(max(values))}'


def sources(r, prefix, names=('Report', 'Config', 'CSV', 'Raw')):
    files = {'Report': 'README.md', 'Config': 'resolved-config.json', 'CSV': 'summary.csv', 'Raw': 'raw/measurements.jsonl.gz',
             'Manifest': 'manifest.json', 'Cohorts': 'legal-summary.json'}
    base = prefix + r['report'].rsplit('/', 1)[0] + '/'
    return ' · '.join(f'[{name}]({base}{files[name]})' for name in names
                      if name == 'Report' or files[name] in r['downloads'])


def detail(r, index):
    return f"{index}recommended/{slug(r['hardware'])}/{slug(r['experiment'])}.md"


def placement(r):
    f = r['observation']['fit']
    if r['mode'] == 'projection':
        return 'capacity estimate'
    if f.get('fit_class') in ('capacity_failure', 'loader_failure'):
        return _cell(f['fit_class']).replace('_', ' ') + ' (' + _cell(f.get('reason')).replace('_', ' ') + ')'
    if r['status'] == 'failed' and r['observation']['completed'] == 0:
        return 'failed before any request completed'
    count, total = f.get('layers_offloaded'), f.get('layers_total')
    if count is not None and total is not None:
        return f'{value(count)} of {value(total)} layers reported on GPU'
    if f.get('placement') not in (None, 'unobserved'):
        return 'backend reported ' + _cell(f['placement']).replace('_', ' ')
    if f.get('verdict') == 'in_vram' and 'gpu_telemetry' in (f.get('evidence_basis') or []):
        return 'fit inferred from device memory, layer count unknown'
    return 'layer placement unknown'


def completion(r):
    obs = r['observation']
    if r['mode'] == 'projection':
        return 'no model call'
    return f"{obs['completed']}/{obs['observations']}" if obs['completed'] is not None else UNKNOWN


def checks(r):
    return _cell(r['decisions'] or r['quality'] or 'unscored')


def workload(r):
    obs = r['observation']
    if r['mode'] == 'projection':
        return 'capacity estimates'
    if r.get('legal') and r['legal'].get('matters') is not None:
        return f"{value(r['legal']['matters'])} fictional matters"
    if obs['tasks'] is None:
        return UNKNOWN
    return f"{obs['tasks']} tasks × {span(obs['repeat_range'])} measured attempts"


def fit_rows(records, prefix):
    lines = ['| Model and runtime | Job status | Completed | Checks passed | Prompt tokens observed | Time until text appears (median s) | Placement evidence | Source |',
             '|---|---|---:|---:|---:|---:|---|---|']
    for r in records:
        obs = r['observation']
        name = _cell(r['model']) + ' · ' + _cell(PLATFORMS.get(r['harness'], r['harness']))
        lines.append(f"| {name} | {_cell(r['status'])} | {completion(r)} | {checks(r)} | {span(obs['prompt_range'])} | "
                     f"{value(obs['visible_s'])} | {placement(r)} | {sources(r, prefix, ('Report',))} |")
    return lines


def featured_fit(records):
    """Choose a recently tested artifact with multiple evidence types. Include failures on its other runtimes."""
    groups = defaultdict(dict)
    for r in records:  # newest job first, including failed attempts
        if r['experiment'] == FIT and r['mode'] == 'measured' and not r['synthetic'] and r['class'] is None:
            groups[(r['hardware'], r['model'])].setdefault(r['harness'], r)
    if not groups:
        return []
    def coverage(group):
        return (max(r['date'] for r in group), len({placement(r) for r in group}), len(group), max(r['created'] for r in group))
    chosen = max((list(g.values()) for g in groups.values()), key=coverage)
    return sorted(chosen, key=lambda r: r['harness'])


def highlights(records, index, report_prefix):
    lines = ['### What ran on this hardware?', '']
    fit = featured_fit(records)
    if fit:
        r = fit[0]
        gpu = r['gpu']
        lines += [f"**{_cell(r['model'])}** on {_cell(r['hardware'])} ({_cell(r['os'])}). "
                  f"{value(gpu.get('name'))}, {value(gpu.get('vram_gib'))} GiB of GPU memory. "
                  'Each row is the latest published test of this artifact name on that runtime.', '']
        lines += fit_rows(fit, report_prefix)
        sizes = {workload(r) for r in fit}
        contexts = {r['context'] for r in fit}
        detail_line = ('Each run recorded ' + sizes.pop() + '. ') if len(sizes) == 1 and UNKNOWN not in sizes else ''
        if len(contexts) == 1 and None not in contexts:
            n = contexts.pop()
            detail_line += f'The configured context window was {value(n)} tokens. '
            prompts = [r['observation']['prompt_range'][-1] for r in fit if r['observation']['prompt_range']]
            if prompts and max(prompts) < n:
                detail_line += f'The longest prompt with a recorded token count used {value(max(prompts))} tokens. '
        lines += ['', detail_line + 'Checks refer to the published workload. Repeated attempts on one question count as one distinct task.',
                  '', f'[Inspect the run settings, device memory and raw records]({detail(r, index)}).', '']
    lines += ['| Experiment and hardware | Evidence available | Read the runs |', '|---|---|---|']
    for (experiment, hardware), group in pairs(records).items():
        mode_labels = {'measured': 'model run', 'category-smoke': 'model run', 'decision': 'model run',
                       'livebench': 'LiveBench job', 'live': 'live routing job', 'matched-performance': 'performance job',
                       'replay': 'replay job', 'projection': 'projection'}
        counts = Counter(r['class'] or ('fixture' if r['synthetic'] else mode_labels.get(r['mode'], 'job')) for r in group)
        names = {'measured': 'measured model run', 'score-only': 'rescore'}
        state = ', '.join(f'{n} {_cell(names.get(k, k))}' + ('s' if n != 1 else '') for k, n in sorted(counts.items()))
        failed = sum(r['status'] == 'failed' for r in group)
        state += f' ({failed} failed)' if failed else ''
        lines.append(f"| {_cell(experiment)} · {_cell(hardware)} | {state} | [Evidence and reproduction]({detail(group[0], index)}) |")
    pending = [r for r in records if any('all_pass_reviewed' in (row.get('metrics') or {}) for row in r['legal_rows'])
               and r['legal'].get('review_required') and not r['legal'].get('reviewer_fingerprint')]
    if pending:
        lines += ['', f"**Human review is pending** in {len(pending)} published legal jobs on fictional matters. "
                  f"See the [review denominators]({detail(pending[0], index)}#legal-evaluation)."]
    if any(r['hardware'] == 'raider-ubuntu' and r['synthetic'] for r in records) and all(
            r['synthetic'] or r['mode'] == 'projection' for r in records if r['hardware'] == 'raider-ubuntu'):
        lines += ['', 'Native Ubuntu on the Raider has fixture coverage only. A measured result there is still open.']
    lines += ['', f'[Browse by model, date or runtime]({index}README.md) · [US model results]({index}origin/us.md).']
    return '\n'.join(lines)


def pairs(records):
    groups = defaultdict(list)
    for r in records:
        groups[(r['experiment'], r['hardware'])].append(r)
    return groups


def matched_section(records):
    groups = matched(records)
    lines = ['## Matched model comparisons', '',
             'A group changes the model package within one publication on one hardware configuration and runtime. '
             'The suite hashes, exact prompts, measured repetitions, scorer code and recorded request settings must match. '
             'The package includes its tokenizer and template. Failed jobs and runs with incomplete controls remain in the run history.', '']
    if not groups:
        return lines + ['No two successful model packages have complete matching controls in these bundles.']
    lines += ['Times are descriptive. Host paging, model-specific defaults, cache reuse and independent sessions can be unobserved. '
              'Each row shows this run’s observed median among completed requests. Repeated prompts on one host do not establish '
              'uncertainty across machines or general model quality. The downloadable manifest contains each full comparison key and its inputs.']
    for key, group in groups.items():
        r = group[0]
        lines += ['', f"### {_cell(r['harness'])} · {_cell(r['date'])} · {key[:12]}", '',
                  f"Fixed workload and settings include {workload(r)}, protocol {value(r['protocol'])}, "
                  f"mode {value(r['mode'])} and hardware {value(r['hardware'])}. Backend version: {value(r['backend_version'])}. "
                  f"Comparison question: {_cell(r['controls']['question'])}.",
                  '', '| Model package | Completed | Checks passed | Wall time (median s) | Time until text appears (median s) | Backend decode (median tok/s) |',
                  '|---|---:|---:|---:|---:|---:|']
        for r in group:
            o = r['observation']
            lines.append(f"| {_cell(r['model'])} | {completion(r)} | {checks(r)} | {value(o['wall_s'])} | "
                         f"{value(o['visible_s'])} | {value(o['decode_tps'])} |")
        baseline = group[0]
        base_times = baseline['observation']['task_wall_medians']
        if base_times:
            lines += ['', f"Paired wall-time differences use {_cell(baseline['model'])} as the alphabetically first reference. "
                      'For each identical prompt, subtract the reference median from the other model’s median. '
                      'The range spans the observed prompts. Negative values mean a shorter wait.', '',
                      '| Model package | Paired prompts | Median difference (s) | Observed range (s) |',
                      '|---|---:|---:|---:|']
            for other in group[1:]:
                times = other['observation']['task_wall_medians']
                delta = [other_t - base_times[task] for task, other_t in times.items() if task in base_times]
                lines.append(f"| {_cell(other['model'])} | {len(delta)} | {value(median(delta) if delta else None)} | {span(delta)} |")
    return lines


def legal_section(records):
    lines = ['## Legal evaluation', '', 'The unit is a fictional matter within one arm. Rates and denominators come from the public '
             'cohort summaries. Each stage has its own eligible matters. A missing review has no reviewed score.', '',
             '| Run / class | Arm | Exact-version recall (mean, n) | Citations resolve (rate, n) | All deterministic checks (rate, n) | Human-reviewed all-pass (rate, n) |',
             '|---|---|---|---|---|---|']
    for r in records:
        for cohort in r['legal_rows']:
            metrics = cohort.get('metrics') or {}
            def measure(key):
                v = metrics.get(key) or {}
                if not v.get('n'):
                    return ('pending, n=0' if key == 'all_pass_reviewed' and key in metrics and r['legal'].get('review_required')
                            and not r['legal'].get('reviewer_fingerprint') else 'unavailable')
                return f"{value(v.get('value'))}, n={value(v['n'])}"
            cells = [measure(k) for k in ('retrieval.exact_version_recall', 'criterion.citations_resolve',
                                          'all_pass_deterministic', 'all_pass_reviewed')]
            lines.append(f"| {_cell(r['date'])} {_cell(r['mode'])} ({_cell(r['class'])}) | {_cell(cohort.get('arm'))} | " + ' | '.join(cells) + ' |')
    return lines


def fit_memory(records):
    lines = ['## Memory at the tested prompts', '', 'Device-wide memory includes other processes. The reserve is the minimum '
             'free memory the experiment requests. Each peak covers the whole job, across prompt lengths.', '',
             '| Date / model / runtime | Prompt tokens observed | Context window requested (tokens) | Peak used / total (MiB) | Reserve (MiB) | Fit verdict |',
             '|---|---:|---:|---:|---:|---|']
    for r in records:
        f = r['observation']['fit']
        if r['mode'] == 'projection':
            continue
        lines.append(f"| {_cell(r['date'])} · {_cell(r['model'])} · {_cell(r['harness'])} | {span(r['observation']['prompt_range'])} | "
                     f"{value(r['context'])} | {value(f.get('peak_used_mib'))} / {value(f.get('total_mib'))} | "
                     f"{value(f.get('reserve_mib'))} | {value(f.get('verdict'))} |")
    return lines


def fit_chart(records, path):
    """A job-level peak cannot be assigned to a particular prompt. Plot the observed range against job headroom."""
    points = []
    for r in records:
        f, prompt = r['observation']['fit'], r['observation']['prompt_range']
        if (r['status'] == 'succeeded' and not r['synthetic'] and prompt and
                all(isinstance(f.get(k), (int, float)) for k in ('total_mib', 'reserve_mib', 'peak_used_mib'))):
            points.append((prompt, (f['total_mib'] - f['peak_used_mib']) / 1024, f['reserve_mib'] / 1024,
                           bool(f.get('layers_total') and f.get('layers_offloaded') is not None)))
    if not points:
        return False
    from . import charts
    if not charts.available():
        return False
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(7.5, 3.8), layout='constrained')
    for known, marker, color, label in ((True, 'o', '#23537d', 'Layer count recorded'), (False, '^', '#9b5817', 'Layer count unknown')):
        values = [p for p in points if p[3] == known]
        if values:
            for (lo, hi), left, _, _ in values:
                ax.plot([lo, hi], [left, left], color=color, alpha=.65)
            ax.scatter([p[0][1] for p in values], [p[1] for p in values], marker=marker, color=color, label=label)
    for reserve in sorted({p[2] for p in points}):
        ax.axhline(reserve, color='#444', linestyle='--', label=f'Reserve {reserve:g} GiB')
    ax.set(xlabel='Observed prompt length range (tokens)', ylabel='GPU memory free at job peak (GiB)',
           title=f'Memory headroom across {len(points)} measured jobs')
    ax.legend(fontsize=8)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=150, metadata={'Software': 'llm-eval'})
    plt.close(fig)
    return True


def example(records, prefix):
    measured = next((r for r in records if not r['synthetic'] and r['class'] is None and r['mode'] != 'projection' and
                     r['status'] == 'succeeded' and r['observation']['tasks']), None)
    if not measured:
        if all(r['synthetic'] for r in records):
            return ['These runs exercised a synthetic fixture. A measured model run on this configuration is still open.']
        return []
    r, o = measured, measured['observation']
    lines = [f"**One recent run** · {_cell(r['date'])} · {_cell(r['model'])} on {_cell(r['harness'])}. "
             f"{workload(r)}. {completion(r)} requests completed and {checks(r)} checks passed."]
    if r['mode'] == 'decision':
        lines += ['', 'Each check asks whether the router selected the expected label. The timing covers the decision. '
                  'Downstream answer quality and end-to-end generation cost require a different experiment.']
    elif r['mode'] == 'category-smoke':
        lines += ['', f"The median time until text appeared was {value(o['visible_s'])} s. The observed prompts used "
                  f"{span(o['prompt_range'])} tokens and the outputs used {span(o['output_range'])} tokens. "
                  'The deterministic checks cover the short answers in this workload.']
    if r['mode'] == 'category-smoke':
        lines += ['', f"Requested context {value(r['context'])} tokens, output cap {value(r['output_cap'])} tokens. "
                  f"Requested GPU layers {value(r['launch'].get('gpu_layers'))}, GPU share {value(r['launch'].get('gpu_offload'))}. "
                  f"Observed placement: {placement(r)}."]
    return lines + ['', sources(r, prefix)]


def page(records, chart):
    r = records[0]
    base = '../../../'
    docs = '../../../../'
    lines = [f"# {_cell(r['experiment'])} on {_cell(r['hardware'])}", '',
             '[Setup evidence](../README.md) · [Results index](../../README.md)']
    if r['experiment'] == FIT:
        lines += ['', '## Can the model run here?', ''] + fit_rows([v for v in records if v['mode'] != 'projection'], base)
        lines += ['', *fit_memory(records)]
        if chart:
            lines += ['', f'![Free GPU memory at the sampled job peak across the short prompt ranges listed above.]({chart})']
    elif r['experiment'] != 'legal-models':
        lines += ['', *example(records, base)]
    if any(v['legal_rows'] for v in records):
        lines += ['', *legal_section(records)]
    if any(v['ranked'] and not v['synthetic'] for v in records):
        lines += ['', *matched_section(records)]
    lines += ['', '## Reproduce a run', '',
              'Choose a dated report in the table. The manifest pins the code revision. Config records the planned job, '
              'input hashes and launch settings. CSV contains category summaries. Raw contains the published measurements. '
              'Some older bundles omit artifacts or runtime details. Local paths have been removed.',
              '', f"[Read the reproduction recipe]({docs}REPRODUCE.md) · [Download the comparison manifest]({slug(r['experiment'])}.json).",
              ]
    bundle = 'docs/results/' + r['report'].rsplit('/', 1)[0]
    if re.fullmatch(r'[\w./-]+', bundle) and re.fullmatch(r'[\w.-]+', r['job_id']):
        lines += ['', f"For the newest listed job ({_cell(r['case'])}) run this from the repository root.", '',
                  '```sh', f"llm-eval result-inputs --input {bundle} --job {r['job_id']}", '```']
    lines += ['', '## Run history', '', 'One row per published job, newest first. A completed request can still fail its check. '
              'Output-cap and reload conditions can differ between rows. Use a matched group for a controlled comparison. '
              'Projection rows count candidate settings. Legal jobs expose aggregate evidence by cohort.', '',
              '| Date | Model / runtime | Mode and status | Actual workload | Completed | Checks passed | Median wall s | First visible text s | Backend decode tok/s | Evidence |',
              '|---|---|---|---|---:|---:|---:|---:|---:|---|']
    for v in records:
        o = v['observation']
        kind = v['class'] or ('fixture' if v['synthetic'] else v['mode'])
        lines.append(f"| {_cell(v['date'])} | {_cell(v['model'])} · {_cell(v['harness'])} | {_cell(kind)} · {_cell(v['status'])} | "
                     f"{workload(v)} | {completion(v)} | {checks(v)} | {value(o['wall_s'])} | {value(o['visible_s'])} | "
                     f"{value(o['decode_tps'])} | {sources(v, base, ('Report', 'Config', 'Manifest', 'CSV', 'Raw', 'Cohorts'))} |")
    return '\n'.join(lines) + '\n'


def manifest(records):
    return {'schema_version': 1, 'comparison_unit': 'model package within a single publication, workload and named runtime',
            'matched_groups': {key: {'controls': group[0]['controls'], 'job_ids': [r['job_id'] for r in group]}
                               for key, group in matched(records).items()},
            'jobs': [{'job_id': r['job_id'], 'report': r['report'], 'case': r['case'], 'model': r['model'], 'runtime': r['harness'],
                      'status': r['status'], 'code_revision': r['revision'], 'config_sha256': r['config_sha256'],
                      'artifact_sha256': r['observation']['artifacts'], 'router_revision': r['model_revision'],
                      'suite_sha256': r['observation']['suites'], 'observed_prompt_tokens': r['observation']['prompt_range'],
                      'observed_output_tokens': r['observation']['output_range'], 'cohort_digests': r['cohorts'],
                      'candidate_comparison_sha256': r['comparison']} for r in records]}


def write_evidence(root, records, index):
    directory = index / 'recommended'
    directory.mkdir(exist_ok=True)
    chart_dir = root / CHARTS
    if chart_dir.exists():
        shutil.rmtree(chart_dir)
    lines = ['# Setup evidence by hardware and experiment', '', '[Results index](../README.md)', '',
             '| Experiment | Hardware | Published jobs | Matched groups | Evidence |', '|---|---|---:|---:|---|']
    for (experiment, hardware), group in pairs(records).items():
        path = directory / slug(hardware) / (slug(experiment) + '.md')
        path.parent.mkdir(parents=True, exist_ok=True)
        chart = None
        if experiment == FIT:
            image = chart_dir / f'{slug(experiment)}-{slug(hardware)}.png'
            if fit_chart(group, image):
                chart = Path(os.path.relpath(image, path.parent)).as_posix()
        path.write_text(page(group, chart), encoding='utf-8', newline='\n')
        path.with_suffix('.json').write_text(json.dumps(manifest(group), indent=2, sort_keys=True) + '\n', encoding='utf-8', newline='\n')
        lines.append(f"| {_link('experiment', experiment, '../')} | {_link('hardware', hardware, '../')} | {len(group)} | "
                     f"{len(matched(group))} | [Results and reproduction]({path.relative_to(directory).as_posix()}) |")
    (directory / 'README.md').write_text('\n'.join(lines) + '\n', encoding='utf-8', newline='\n')
    origin = index / 'origin'
    origin.mkdir()
    (origin / 'us.md').write_text('# US model results\n\n[Results index](../README.md)\n\n'
        'Includes models with a recorded US developer and US developers for all base models. Runs are ordered by date.\n\n'
        + table([r for r in records if us_model(r)], '../', '../../') + '\n', encoding='utf-8', newline='\n')
