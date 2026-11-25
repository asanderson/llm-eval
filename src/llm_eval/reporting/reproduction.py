"""Read the provenance for one published job without starting a server or downloading weights."""
import gzip
import json
from pathlib import Path

from llm_eval.artifacts import verify_artifact
from llm_eval.common import digest, read_json
from llm_eval.experiments import canonical
from .index import identity


# Only settings needed to reconstruct a public run. Paths and host-specific setup are supplied locally.
RUN_SETTINGS = (
    'model_id', 'platform', 'protocol', 'backend_version', 'tokenizer_revision', 'chat_template_sha256',
    'lane', 'context_tokens', 'max_output_tokens', 'temperature', 'seed', 'repeats', 'warmups',
    'concurrency', 'gpu_budget_gib', 'ram_budget_gib', 'telemetry_interval_s', 'cache_condition',
    'reasoning_mode', 'speculative_decoding', 'launch', 'request_options',
)


def result_inputs(bundle, job_id=None, artifact_dir=None):
    """List jobs, or extract the specified job's latest-attempt inputs from the published evidence."""
    bundle = Path(bundle)
    manifest = read_json(bundle / 'manifest.json')
    resolved = read_json(bundle / 'resolved-config.json')
    result = {'publication_id': manifest['publication_id'], 'experiment': canonical(manifest['experiment_id']),
              'measured_revision': manifest['code_revision']}
    jobs = resolved['jobs']
    if job_id is None:
        if artifact_dir is not None:
            raise ValueError('Select one --job before verifying an artifact directory')
        result['jobs'] = [{'job_id': job['job_id'], 'case': job['case_id'], 'mode': job['mode'],
                           'hardware_configuration': job['hardware_config_id']} for job in jobs]
        return result

    job = next((j for j in jobs if j['job_id'] == job_id), None)
    if job is None:
        raise ValueError('Unknown job in this bundle. List its jobs by omitting --job.')
    params = job['parameters']
    harness, model = identity(job)
    result.update(job_id=job_id, case=job['case_id'], mode=job['mode'], hardware_configuration=job['hardware_config_id'],
                  os=job['hardware'].get('os_id'), harness=harness, model=model)
    if result['experiment'] == 'legal-models':
        if artifact_dir is not None:
            raise ValueError('The public legal projection contains no reusable artifact lock')
        result.update(execution_kind=params.get('execution_kind'), data_class=params.get('data_class'),
                      cohort_digests=params.get('cohorts', []), guide='docs/LEGAL_MODELS_WALKTHROUGH.md')
        return result

    config = params.get('config', {})
    result['settings'] = {k: config[k] for k in RUN_SETTINGS if k in config}
    if 'router' in params:
        router = params['router']
        result['router'] = {k: router[k] for k in ('kind', 'model', 'model_revision', 'platform') if k in router}
        result['candidates'] = {name: {k: candidate[k] for k in ('platform', 'model', 'model_revision',
                                'backend_version', 'quantization', 'template_sha256') if k in candidate}
                                for name, candidate in params.get('candidates', {}).items()}
        result['settings'].update({k: params[k] for k in ('warmups', 'repeats') if k in params})
    result['categories'] = params.get('categories', [])
    result['configuration_source'] = 'resolved-config.json'
    artifacts, suites = {}, set()
    with gzip.open(bundle / 'raw' / 'measurements.jsonl.gz', 'rt', encoding='utf-8') as source:
        for line in source:
            row = json.loads(line)
            if row['job_id'] != job_id or row['record_type'] != 'metadata' or not row.get('latest_attempt'):
                continue
            data = row['data']
            if data.get('suite_sha256'):
                suites.add((data.get('category') or '', data['suite_sha256']))
            if 'artifact' in data and isinstance(data['artifact'], dict):
                lock = data['artifact']
                key = digest(lock)
                if key != data.get('artifact_sha256'):
                    raise ValueError('Published artifact lock does not match its recorded digest')
                artifacts[key] = lock
    result['suite_hashes'] = [{'category': category or None, 'sha256': sha} for category, sha in sorted(suites)]
    result['artifact_locks'] = [{'lock_sha256': key, 'lock': artifacts[key]} for key in sorted(artifacts)]
    if artifact_dir is not None:
        if len(artifacts) != 1:
            raise ValueError('Verification requires one unambiguous published artifact lock for this job')
        result['verified_weight_bytes'] = verify_artifact(Path(artifact_dir), next(iter(artifacts.values())),
                                                         require_over_vram=False)
    return result
