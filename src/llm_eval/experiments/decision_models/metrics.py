"""Task-level decision scores and request-level timing, pooled within a job."""
from collections import Counter, defaultdict
from statistics import mean

from llm_eval.report import quantile


def first_measured(rows):
    """Select the first scheduled measured repetition, including a failed one."""
    first = {}
    for row in rows:
        if row.get('warmup'):
            continue
        task_id = row['task_id']
        if task_id not in first or row.get('repetition', 0) < first[task_id].get('repetition', 0):
            first[task_id] = row
    return first


def average(values):
    return mean(values) if values else None


def ratio(numerator, denominator):
    return numerator / denominator if denominator else None


def decision_metrics(rows):
    measured = [row for row in rows if not row.get('warmup')]
    tasks = list(first_measured(measured).values())
    labelled = [row for row in tasks if row.get('expected_choice') is not None]
    confusion = Counter((r['expected_choice'], r.get('choice')) for r in labelled)
    per_class = []
    for label in sorted({r['expected_choice'] for r in labelled}):
        hits = confusion[label, label]
        support = sum(n for (expected, _), n in confusion.items() if expected == label)
        predicted = sum(n for (_, choice), n in confusion.items() if choice == label)
        per_class.append({'label': label, 'tasks': support, 'recall': hits / support,
                          'f1': 2 * hits / (support + predicted)})
    probabilities = []
    brier = []
    for row in labelled:
        p = row.get('probabilities') or {}
        choice, expected = row.get('choice'), row['expected_choice']
        if choice in p and expected in p:
            probabilities.append((p[choice], choice == expected))
            brier.append(sum((value - int(label == expected)) ** 2 for label, value in p.items()))
    calibration = []
    for index in range(10):
        bucket = [(p, correct) for p, correct in probabilities if min(int(p * 10), 9) == index]
        calibration.append({'lower': index / 10, 'upper': (index + 1) / 10, 'tasks': len(bucket),
                            'mean_confidence': average([p for p, _ in bucket]),
                            'accuracy': average([int(correct) for _, correct in bucket])})
    sensitivity = []
    for threshold in (0, .5, .7, .9, .95, 1):
        accepted = [int(correct) for p, correct in probabilities if p >= threshold]
        sensitivity.append({'threshold': threshold, 'accepted_tasks': len(accepted),
                            'share_of_probability_tasks': ratio(len(accepted), len(probabilities)),
                            'accuracy': average(accepted)})
    accepted = [r for r in labelled if r.get('choice') is not None and not r.get('abstained')]
    successful = [r for r in measured if r.get('status') == 'ok']
    timing = {}
    for field in ('router_s', 'generation_s', 'elapsed_s', 'estimated_end_to_end_s'):
        population = measured if field == 'router_s' else successful
        values = [r[field] for r in population if r.get(field) is not None]
        timing[field] = {'requests': len(values), 'p50': quantile(values, .5), 'p95': quantile(values, .95)}
    return {
        'unique_tasks': len(tasks), 'measured_requests': len(measured), 'labelled_tasks': len(labelled),
        'first_request_status': dict(Counter(r.get('status', 'unknown') for r in tasks)),
        'request_status': dict(Counter(r.get('status', 'unknown') for r in measured)),
        'tasks_without_choice': sum(r.get('choice') is None for r in labelled),
        'decision_accuracy': ratio(sum(r.get('choice') == r['expected_choice'] for r in labelled), len(labelled)),
        'macro_f1': average([c['f1'] for c in per_class]), 'per_class': per_class,
        'confusion': [{'expected': a, 'predicted': b, 'count': n}
                      for (a, b), n in sorted(confusion.items(), key=lambda pair: (pair[0][0], pair[0][1] or ''))],
        'probability_tasks': len(probabilities), 'mean_multiclass_brier': average(brier),
        'reliability_bins': calibration, 'threshold_sensitivity': sensitivity,
        'accepted_labelled_tasks': len(accepted), 'accepted_share': ratio(len(accepted), len(labelled)),
        'accepted_accuracy': average([int(r['choice'] == r['expected_choice']) for r in accepted]),
        'abstentions': sum(bool(r.get('abstained')) for r in tasks),
        'fallback_tasks': sum(bool(r.get('fallback_used')) for r in tasks),
        'fallback_answers_passed': sum(bool(r.get('fallback_used')) and r.get('quality_pass') is True for r in tasks),
        'timing_all_measured_repetitions': timing,
    }


def decision_report(records):
    groups = defaultdict(list)
    for record in records:
        if record['record_type'] == 'request' and record['latest_attempt']:
            row = record['data']
            if row.get('task_id') is not None and not row.get('warmup'):
                groups[record['job_id'], row.get('benchmark', 'routing')].append(row)
    return [{'job_id': job, 'benchmark': benchmark, **decision_metrics(rows)}
            for (job, benchmark), rows in sorted(groups.items())]


def report_supplement(records):
    pooled = decision_report(records)
    if not pooled:
        return None, ''
    names = {r['job_id']: r['data'].get('case_id', r['job_id']) for r in records
             if r['latest_attempt'] and r.get('source_file') == 'job.json'}
    lines = ['## Pooled decision scores', '',
             'Scores use the first measured request per unique task. Timing includes all measured repetitions. '
             '[Confusion, per-class recall, calibration and coverage](decision-models-summary.json)', '',
             '| Case | Unique tasks | Measured requests | Accuracy | Macro-F1 | Mean Brier | Probability-bearing tasks |',
             '|---|---:|---:|---:|---:|---:|---:|']

    def score(value):
        return 'unavailable' if value is None else f'{value:.4g}'

    for r in pooled:
        lines.append(f"| {names.get(r['job_id'], r['job_id'])} | {r['unique_tasks']} | {r['measured_requests']} | "
                     f"{score(r['decision_accuracy'])} | {score(r['macro_f1'])} | {score(r['mean_multiclass_brier'])} | "
                     f"{r['probability_tasks']} |")
    return pooled, '\n'.join(lines) + '\n\n'
