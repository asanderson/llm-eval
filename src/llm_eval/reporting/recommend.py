"""Recommended setup, harness and model per hardware configuration and experiment, derived from the published results.

`llm-eval index-results` writes one page per (hardware configuration, experiment) pair under
docs/results/index/recommended/HARDWARE/EXPERIMENT.md and an overview beside them. A recommendation is the best-ranked
harness and model combination of the pair, by the ranking of `index.ranked`, together with the configuration of that run
as its bundle's resolved configuration records it. A pair without a ranked run gets a page that says why. Nothing is typed
by hand and every value of a bundle is rendered through `index._cell`, so a hostile value stays inert text.
"""
from __future__ import annotations

import json
from pathlib import Path

from .index import RANKING_RULE, TOP_LIMIT, _cell, _link, _read, identity, ranked, slug, table

DIRECTORY = 'recommended'      # below docs/results/index, so a publication stages these pages with the index
NOTE = 'Generated from the published bundles by `llm-eval index-results`; do not edit by hand.'
SCOPE = ('It is a statement about the published runs on this hardware configuration, not about the model or the harness in '
         'general. The checks are small deterministic checks, the runs can differ in more than the harness and the model '
         '(each report states its conditions), and the recommendation changes when a newer run of a combination is published.')
# (label, key) of the run configuration, in the order they are shown. A key the run does not carry gives no row.
CONFIG = (('Lane', 'lane'), ('Context tokens', 'context_tokens'), ('Output cap (tokens)', 'max_output_tokens'),
          ('Temperature', 'temperature'), ('Seed', 'seed'), ('Warm-ups per task', 'warmups'),
          ('Measured repetitions per task', 'repeats'), ('Request deadline (s)', 'timeout_s'),
          ('RAM budget (GiB)', 'ram_budget_gib'), ('GPU budget (GiB)', 'gpu_budget_gib'),
          ('Model artifact and tokenizer revision', 'tokenizer_revision'), ('Chat template SHA-256', 'chat_template_sha256'),
          ('Reasoning mode', 'reasoning_mode'), ('Request options', 'request_options'), ('Placement notes', 'placement_notes'))
LAUNCH = (('Model file', 'model_file'), ('GPU layers requested', 'gpu_layers'), ('GPU share requested (ratio)', 'gpu_offload'),
          ('CPU threads', 'threads'), ('Import mode', 'import_mode'))
ATTESTED = (('NVIDIA driver', 'nvidia_driver'), ('OS build', 'os_build'), ('WSL version', 'wsl_version'), ('WSL guest memory', 'wsl_memory_cap'))


def _job(root, record):
    """The planned job behind an index record, from the resolved configuration of its bundle; None when it is not found."""
    bundle = Path(root) / 'docs/results' / Path(record['report']).parent
    for job in _read(bundle / 'resolved-config.json').get('jobs', []):
        if (job.get('case_id') == record['case'] and job.get('hardware_config_id', 'unknown') == record['hardware']
                and identity(job) == (record['harness'], record['model'])):
            return job
    return None


def _value(value):
    """One setting as text: objects as compact JSON, None and empty values as no value."""
    if value is None or value == '' or value == {} or value == []:
        return None
    return json.dumps(value, sort_keys=True, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value)


def settings(job):
    """[(label, text)] of the configuration a run recorded: the run configuration with its launch and attested settings, or
    the router of a routing job. Empty for a job that carries neither."""
    parameters = (job or {}).get('parameters') or {}
    config, router = parameters.get('config'), parameters.get('router')
    rows = []
    if isinstance(config, dict):
        launch = config.get('launch') if isinstance(config.get('launch'), dict) else {}
        attested = config.get('hardware_attestation') if isinstance(config.get('hardware_attestation'), dict) else {}
        rows += [('Harness version', config.get('backend_version'))]
        rows += [(label, launch.get(key)) for label, key in LAUNCH]
        rows += [(label, config.get(key)) for label, key in CONFIG]
        rows += [(label, attested.get(key)) for label, key in ATTESTED]
    elif isinstance(router, dict):
        rows += [('Router ' + str(key), value) for key, value in sorted(router.items(), key=lambda item: str(item[0]))
                 if not isinstance(value, (dict, list))]
    return [(label, text) for label, text in ((label, _value(value)) for label, value in rows) if text is not None]


def _number(value):
    return _cell(None if value is None else format(value, '.3g'))


def _rows(chosen, first, index_prefix, report_prefix, start=1):
    """Ranking rows; `first` is the leading column, 'harness' or 'model'."""
    second = 'model' if first == 'harness' else 'harness'
    return [f"| {rank} | {_link(first, r[first], index_prefix)} | {_link(second, r[second], index_prefix)} | "
            f"{r['score'][0]}/{r['score'][1]} | {_number(r['wall_mid'])} | {_number(r['tokens_mid'])} | "
            f"[{r['date']}]({report_prefix}{r['report']}) |" for rank, r in enumerate(chosen, start)]


def _why_unranked(chosen):
    """One sentence: why no run of the pair is ranked."""
    if all(not r.get('ranked', True) for r in chosen):
        return 'The results of this experiment are published by class and cohort and are not ranked.'
    if all(r['synthetic'] for r in chosen):
        return 'Every published run of this pair is a synthetic fixture, which measures no model.'
    return 'No run of this pair has succeeded with scored checks.'


def page(root, experiment, hardware, records, order):
    """The page of one pair: `records` are its published results, newest first; `order` its ranked combinations, best first."""
    index_prefix, report_prefix = '../../', '../../../'
    lines = [f'# Recommended setup, harness and model: {_cell(experiment)} on {_cell(hardware)}', '',
             '[Recommended setups](../README.md) · [Results index](../../README.md) · [Executive summary](../../../README.md)', '',
             f'{NOTE} {len(records)} published result(s) for this experiment and hardware configuration; '
             f'{len(order)} harness and model combination(s) are ranked.']
    if not order:
        lines += ['', '## No recommendation', '', _why_unranked(records) + ' Its published results are listed below.']
    else:
        best = order[0]
        job = _job(root, best)
        tied = sum(1 for r in order if r['score'][0] * best['score'][1] == best['score'][0] * r['score'][1])
        lines += ['', '## Recommendation', '', '| | |', '|---|---|',
                  f"| Harness | {_link('harness', best['harness'], index_prefix)} |",
                  f"| Model | {_link('model', best['model'], index_prefix)} |",
                  f"| Operating system | {_cell(best['os'])} |",
                  f"| Checks passed | {best['score'][0]}/{best['score'][1]} |",
                  f"| Median wall time per request (s) | {_number(best['wall_mid'])} |",
                  f"| Output tokens per second | {_number(best['tokens_mid'])} |",
                  f"| Measured | [{best['date']}]({report_prefix}{best['report']}) |",
                  '', 'This is the best-ranked combination of the results index for this pair. ' + RANKING_RULE]
        if tied > 1:
            lines += ['', f'{tied} combinations pass the same share of checks as the recommended one; the order among them is by '
                          'median wall time, then by output rate.']
        lines += ['', SCOPE]
        rows = settings(job)
        if rows:
            lines += ['', '## Setup of the recommended run', '',
                      "Read from the resolved configuration of the run's report. To reproduce it, use the measured code revision "
                      'named in that report.', '', '| Setting | Value |', '|---|---|']
            lines += [f'| {label} | {_cell(text)} |' for label, text in rows]
        per_harness = {}
        for r in order:      # best first, so each harness keeps its best combination
            per_harness.setdefault(r['harness'], r)
        if len(per_harness) > 1:
            lines += ['', '## Best combination on each harness', '',
                      'The rank is the position in the ranking of this pair.', '',
                      '| Rank | Harness | Model | Checks passed | Median wall s | Output tok/s | Run |', '|---:|---|---|---:|---:|---:|---|']
            for r in per_harness.values():
                lines += _rows([r], 'harness', index_prefix, report_prefix, start=order.index(r) + 1)
        if len(order) > 1:
            lines += ['', f'## Best {min(TOP_LIMIT, len(order))} combinations', '',
                      '| Rank | Harness | Model | Checks passed | Median wall s | Output tok/s | Run |', '|---:|---|---|---:|---:|---:|---|']
            lines += _rows(order[:TOP_LIMIT], 'harness', index_prefix, report_prefix)
    lines += ['', '## Published results of this pair', '', table(records, index_prefix, report_prefix)]
    return '\n'.join(lines) + '\n'


def overview(records, order):
    """The overview of every pair, one section per experiment (newest result first) and one row per hardware configuration."""
    lines = ['# Recommended setups', '', '[Results index](../README.md) · [Executive summary](../../README.md)', '',
             f'{NOTE} One page per hardware configuration and experiment: the best-ranked harness and model combination of the '
             'results index and the configuration of that run. ' + RANKING_RULE]
    for experiment in dict.fromkeys(r['experiment'] for r in records):      # records arrive newest first
        lines += ['', f'## {_cell(experiment)}', '',
                  '| Hardware configuration | Harness | Model | Checks passed | Median wall s | Output tok/s | Page |',
                  '|---|---|---|---:|---:|---:|---|']
        for hardware in sorted({r['hardware'] for r in records if r['experiment'] == experiment}):
            link = f"[recommended setup]({slug(hardware)}/{slug(experiment)}.md)"
            chosen = order.get((experiment, hardware))
            if not chosen:
                lines.append(f"| {_link('hardware', hardware, '../')} | – | – | – | – | – | {link} (no recommendation) |")
                continue
            best = chosen[0]
            lines.append(f"| {_link('hardware', hardware, '../')} | {_link('harness', best['harness'], '../')} | "
                         f"{_link('model', best['model'], '../')} | {best['score'][0]}/{best['score'][1]} | "
                         f"{_number(best['wall_mid'])} | {_number(best['tokens_mid'])} | {link} |")
    return '\n'.join(lines) + '\n'


def write_recommendations(root, records, index):
    """Write the overview and one page per pair below `index`/recommended; returns the number of pair pages."""
    directory, order = Path(index) / DIRECTORY, ranked(records)
    pairs = sorted({(r['experiment'], r['hardware']) for r in records})

    def save(path, text):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8', newline='\n')

    save(directory / 'README.md', overview(records, order))
    for experiment, hardware in pairs:
        chosen = [r for r in records if r['experiment'] == experiment and r['hardware'] == hardware]
        save(directory / slug(hardware) / (slug(experiment) + '.md'), page(root, experiment, hardware, chosen, order.get((experiment, hardware), [])))
    return len(pairs)
