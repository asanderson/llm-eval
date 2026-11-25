"""Select a frozen workload partition before making any requests."""
from llm_eval.common import digest


def selected_tasks(suite, case):
    tasks = suite['tasks']
    split = case.get('split')
    if split is not None or any('split' in task for task in tasks):
        if split not in {'development', 'test'}:
            raise ValueError('Select development or test for a partitioned workload')
        seen = {}
        for task in tasks:
            partition = task.get('split')
            if partition not in {'development', 'test'}:
                raise ValueError('Every task needs a development or test split')
            for field in ('family', 'source', 'prompt'):
                key = digest(task['messages']) if field == 'prompt' else task.get(field)
                if not isinstance(key, str) or not key:
                    raise ValueError('Partitioned task missing ' + field)
                if seen.setdefault((field, key), partition) != partition:
                    raise ValueError(f'{field} appears in both workload splits: {key}')
        tasks = [task for task in tasks if task['split'] == split]
    if 'task_ids' in case:
        ids = case['task_ids']
        if (not isinstance(ids, list) or not all(isinstance(i, str) for i in ids)
                or len(ids) != len(set(ids)) or set(ids) - {task['id'] for task in tasks}):
            raise ValueError('task_ids must be unique IDs from the selected split')
        ids = set(ids)
        tasks = [task for task in tasks if task['id'] in ids]
    if not tasks:
        raise ValueError('Selected workload is empty')
    return tasks
