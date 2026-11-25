"""Pair the item scores of two completed upstream LiveBench runs on one pinned snapshot."""
import argparse
from collections import Counter
import json
from pathlib import Path

from llm_eval.common import read_json
from llm_eval.livebench import question_manifest, result_coverage
from .performance import common_config


def scored_items(directory, meta):
    snapshot = meta['question_snapshot']
    source = directory / 'source'
    data = source / 'livebench/data'
    label = meta['local_model_config']['display_name']
    if (question_manifest(data, snapshot['categories'], snapshot['release']) != snapshot
            or not all(c['complete'] for c in result_coverage(source, snapshot, label).values())):
        raise ValueError('Question snapshot or judgment coverage differs from the completed run')
    items = {}
    for entry in snapshot['files']:
        if 'eligible_question_ids' not in entry or not entry['eligible_question_ids']:
            continue
        task = Path(entry['path']).parent
        eligible = set(entry['eligible_question_ids'])
        with (data / task / 'model_judgment/ground_truth_judgment.jsonl').open(encoding='utf-8') as handle:
            for line in handle:
                if line.strip():
                    row = json.loads(line)
                    qid = str(row['question_id'])
                    if str(row.get('model', '')).lower() == label and qid in eligible:
                        items[(task.parent.name, task.name, qid)] = row['score']
    return items


def compare(left, right):
    directories = [Path(left), Path(right)]
    runs = [read_json(d / 'livebench-run.json') for d in directories]
    for meta in runs:
        if (meta.get('benchmark') != 'livebench-upstream' or meta.get('status') != 'completed'
                or not meta.get('question_snapshot', {}).get('categories')):
            raise ValueError('Two completed upstream runs with eligible categories are required')
    for key in ('upstream_revision', 'grader_image', 'artifact_sha256', 'question_snapshot'):
        if not runs[0].get(key) or runs[0][key] != runs[1].get(key):
            raise ValueError('Quality pair differs in ' + key)
    configs = [meta['config'] for meta in runs]
    if (common_config(configs[0]) != common_config(configs[1]) or configs[0]['os_id'] != configs[1]['os_id']
            or runs[0].get('agentic_execution') != runs[1].get('agentic_execution')):
        raise ValueError('Quality placement pair differs in generation or execution settings')
    launches = [dict(meta['config']['launch']) for meta in runs]
    counts = [launch.pop('gpu_layers', None) for launch in launches]
    if not all(type(n) is int for n in counts) or counts[0] == counts[1] or launches[0] != launches[1]:
        raise ValueError('Quality placement pair must differ only in the requested GPU layer count among launch settings')
    a, b = [scored_items(d, m) for d, m in zip(directories, runs)]
    if not a or a.keys() != b.keys():
        raise ValueError('Eligible scored item sets differ or are empty')
    rows = [{'category': k[0], 'task': k[1], 'question_id': k[2], 'left': a[k], 'right': b[k],
             'right_minus_left': b[k] - a[k]} for k in sorted(a)]
    return {'release': runs[0]['question_snapshot']['release'], 'scorer_revision': runs[0]['upstream_revision'],
            'grader_image': runs[0]['grader_image'], 'artifact_sha256': runs[0]['artifact_sha256'],
            'requested_gpu_layers': counts, 'supplied_task_coverage': [
                {'category': category, 'task': task, 'eligible': n}
                for (category, task), n in sorted(Counter(k[:2] for k in a).items())],
            'improved': sum(a[k] < b[k] for k in a), 'tied': sum(a[k] == b[k] for k in a),
            'regressed': sum(a[k] > b[k] for k in a), 'items': rows}


def main(argv=None):
    parser = argparse.ArgumentParser(description='Compare two upstream quality run directories for a GPU-layer pair')
    parser.add_argument('left', type=Path)
    parser.add_argument('right', type=Path)
    args = parser.parse_args(argv)
    try:
        result = compare(args.left, args.right)
    except (KeyError, ValueError, OSError) as exc:
        parser.exit(2, f'Comparison unavailable: {exc}\n')
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
