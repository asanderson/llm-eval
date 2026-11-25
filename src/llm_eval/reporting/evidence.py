"""Read only published evidence. Preserve the distinction between observed requests and planned settings."""
from __future__ import annotations

import gzip
import json
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from statistics import median


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


@dataclass
class Evidence:
    requests: list = field(default_factory=list)
    suites: dict = field(default_factory=dict)
    artifacts: set = field(default_factory=set)
    paging: dict = field(default_factory=dict)
    fit: dict = field(default_factory=dict)
    legal: dict = field(default_factory=dict)
    peaks: dict = field(default_factory=dict)

    def read(self, record):
        data = record.get('data') or {}
        kind = record.get('record_type')
        if kind == 'request' and data.get('warmup') is False:
            self.requests.append(data)
        elif kind == 'telemetry':
            used = [g['used_mib'] for g in data.get('gpus') or [] if number(g.get('used_mib'))]
            for key, value in (('backend_rss_gib', data.get('backend_tree_rss_gib')),
                               ('gpu_gib', sum(used) / 1024 if used else None)):
                if number(value):
                    self.peaks[key] = max(self.peaks.get(key, 0), value)
        elif kind == 'metadata':
            if data.get('record') == 'fit-evidence':
                self.fit = data
            if data.get('suite_sha256'):
                self.suites.setdefault(data.get('category') or 'all', set()).add(data['suite_sha256'])
            if isinstance((data.get('memory_assessment') or {}).get('paging_observed'), bool):
                self.paging[data.get('category') or 'all'] = data['memory_assessment']['paging_observed']
            if data.get('artifact_sha256'):
                self.artifacts.add(data['artifact_sha256'])
            if 'matters' in data and 'data_class' in data:
                self.legal = data

    def measured(self):
        tasks = Counter((r.get('benchmark'), r.get('category'), r.get('task_id')) for r in self.requests)
        complete_ids = bool(tasks) and all(task for _, _, task in tasks)
        successful = [r for r in self.requests if r.get('status') == 'ok']
        prompts = [r.get('prompt_tokens') if r.get('prompt_tokens') is not None else
                   (r.get('router_usage') or {}).get('input_tokens') for r in successful]
        prompts = [v for v in prompts if number(v)]
        task_times = defaultdict(list)
        for r in successful:
            if r.get('task_id') and r.get('prompt_sha256') and number(r.get('elapsed_s')):
                task_times[(r.get('benchmark'), r.get('category'), r['task_id'], r['prompt_sha256'])].append(r['elapsed_s'])
        output_tokens = [r['completion_tokens'] for r in successful if number(r.get('completion_tokens'))]

        def midpoint(key):
            values = [r[key] for r in successful if number(r.get(key))]
            return median(values) if values else None
        return {
            'task_wall_medians': {task: median(values) for task, values in task_times.items()},
            'tasks': len(tasks) if complete_ids else None, 'repeat_range': sorted(set(tasks.values())) if complete_ids else [],
            'observations': len(self.requests), 'completed': len(successful) if tasks else None,
            'prompt_range': [min(prompts), max(prompts)] if prompts else [], 'prompt_n': len(prompts),
            'output_range': [min(output_tokens), max(output_tokens)] if output_tokens else [],
            'visible_s': midpoint('first_visible_s'), 'decode_tps': midpoint('backend_decode_tps'),
            'wall_s': midpoint('elapsed_s'), 'fit': self.fit,
            'artifacts': sorted(self.artifacts), 'suites': {k: sorted(v) for k, v in self.suites.items()},
        }


def read_bundle(bundle):
    jobs = defaultdict(Evidence)
    path = bundle / 'raw/measurements.jsonl.gz'
    if path.exists():
        with gzip.open(path, 'rt', encoding='utf-8') as lines:
            for line in lines:
                record = json.loads(line)
                if record.get('latest_attempt') is True:
                    jobs[record.get('job_id')].read(record)
    return jobs


def comparison_controls(manifest, job, raw, record):
    """A comparison changes the model package within a single deployment and publication.

    Keep the complete remaining configuration, exact suite and prompt identities, repeat schedule, and scorer code.
    A digest can only be issued for a complete measured smoke run with a pinned model and all required settings.
    """
    if manifest.get('synthetic') is not False or not record['ranked'] or record['synthetic'] or record['status'] != 'succeeded' or not record['score']:
        return None
    if (not raw.requests or record['requests'] != len(raw.requests) or record['score'][1] != len(raw.requests)
            or not all(r.get('status') == 'ok' and r.get('synthetic') is False for r in raw.requests)):
        return None
    rev = manifest.get('code_revision', '')
    if not re.fullmatch(r'(?:[0-9a-f]{40}|[0-9a-f]{64})', rev or '') or not job.get('experiment_version') or not record['os']:
        return None
    suites = {k: sorted(v) for k, v in raw.suites.items()}
    if not suites or any(len(v) != 1 or not re.fullmatch('[a-f0-9]{64}', v[0]) for v in suites.values()):
        return None
    schedule = []
    for r in raw.requests:
        if (not all(r.get(k) for k in ('task_id', 'category', 'benchmark'))
                or not re.fullmatch('[a-f0-9]{64}', r.get('prompt_sha256') or '')
                or type(r.get('repetition')) is not int):
            return None
        schedule.append((r['benchmark'], r['category'], r['task_id'], r['prompt_sha256'], r['repetition']))
    if len(set(schedule)) != len(schedule):
        return None
    params = dict(job.get('parameters') or {})
    if record['experiment'] == 'decision-models' and record['mode'] == 'decision':
        router = dict(params.get('router') or {})
        if (router.get('kind') != 'systemone' or not router.get('criteria') or not router.get('instructions')
                or not re.fullmatch('[a-f0-9]{64}', router.get('model_revision') or '')):
            return None
        router.pop('model_revision')
        router.pop('model', None)
        params['router'] = router
        timing = params
        metric = 'decision_correct'
        question = 'router label agreement on identical prompts'
    elif (record['experiment'], record['mode']) in (('model-offloading', 'category-smoke'), ('hardware-fit', 'measured')):
        if any(s[0] != 'category-smoke' for s in schedule):
            return None
        config = dict(params.get('config') or {})
        required = ('platform', 'protocol', 'backend_version', 'context_tokens', 'max_output_tokens', 'temperature',
                    'seed', 'concurrency', 'lane', 'reasoning_mode', 'cache_condition', 'speculative_decoding',
                    'request_options', 'launch', 'tokenizer_revision', 'chat_template_sha256', 'ram_budget_gib', 'gpu_budget_gib')
        if (any(config.get(k) is None for k in required) or not isinstance(config['launch'], dict)
                or len(raw.artifacts) != 1 or set(raw.paging) != set(suites)
                or not re.fullmatch('[a-f0-9]{64}', next(iter(raw.artifacts))) or set(suites) != {s[1] for s in schedule}):
            return None
        # Model file, bundled tokenizer and template are part of the model package under test.
        for key in ('model_id', 'served_model', 'tokenizer_revision', 'chat_template_sha256'):
            config.pop(key, None)
        config['launch'] = dict(config['launch'])
        config['launch'].pop('model_file', None)
        params.pop('identity', None)
        params['config'] = timing = config
        metric = 'quality_pass'
        question = 'smoke checks for model packages under the same recorded resource budget'
    else:
        return None
    if (type(timing.get('repeats')) is not int or type(timing.get('warmups')) is not int
            or any(n != timing['repeats'] for n in Counter(s[:4] for s in schedule).values())
            or not all(isinstance(r.get(metric), bool) for r in raw.requests)
            or sum(r[metric] for r in raw.requests) != record['score'][0]):
        return None
    return {
        'version': 1, 'question': question, 'experiment': record['experiment'], 'experiment_version': job['experiment_version'],
        'mode': record['mode'], 'code_revision': rev, 'publication': record['publication'], 'hardware': job.get('hardware'),
        'hardware_config_id': record['hardware'], 'target': job.get('target'), 'harness': record['harness'],
        'check': metric, 'reported_paging_by_category': raw.paging, 'parameters': params, 'suites': suites, 'measured_schedule': sorted(schedule),
    }
