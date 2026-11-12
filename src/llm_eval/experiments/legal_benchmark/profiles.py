"""Role profile v1: one shape for every served role of the legal benchmark, and the job's endpoint allowlist.

A role is reached only through an explicit, pinned profile. `serving` must be declared; `managed` is recognised and
gated; `in-process` exists only for the deterministic fixture embedder and reranker. Every served role is local:
the allowlist is computed from the planned job, and `json_request` is the only opener of embedding and rerank requests.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import re
import statistics
import sys

from llm_eval import adapters
from llm_eval.common import digest, finite_number, sha256_file
from llm_eval.core.contracts import fields, identifier, integer, no_credentials

ROLES = ('generator', 'analyst', 'embedder', 'reranker', 'selector')
CAPABILITY = {'generator': 'chat', 'analyst': 'chat', 'embedder': 'embedding', 'reranker': 'rerank', 'selector': 'decision'}
MANAGED_SERVING_ENABLED = False
SERVING = ('external', 'managed', 'in-process')
IN_PROCESS_PLATFORMS = {'embedder': 'fixture-hash', 'reranker': 'fixture-overlap'}
IN_PROCESS_KEYS = ('role', 'serving', 'platform', 'model', 'model_revision', 'capability', 'dimensions')
PROFILE_KEYS = ('role', 'serving', 'capability', 'deployment_id', 'platform', 'backend_version', 'model', 'model_revision',
                'artifact_sha256', 'template_sha256', 'quantization', 'tokenizer_revision', 'protocol', 'endpoint', 'network',
                'api_key_env', 'context_tokens', 'max_output_tokens', 'dimensions', 'timeout_s', 'connect_timeout_s', 'accelerator',
                'placement', 'resource_host', 'qualification')
# Transport details: they decide where a request goes, not what answers it, so they are not part of the identity.
UNDIGESTED = ('endpoint', 'network', 'api_key_env', 'timeout_s', 'connect_timeout_s')
PUBLIC_KEYS = ('role', 'serving', 'capability', 'platform', 'backend_version', 'model', 'model_revision', 'artifact_sha256',
               'quantization', 'protocol', 'accelerator', 'context_tokens', 'max_output_tokens', 'dimensions')
HEX64 = re.compile(r'[0-9a-f]{64}')
ENV_NAME = re.compile(r'[A-Z_][A-Z0-9_]{0,127}')


def _string(profile, key):
    if not isinstance(profile.get(key), str) or not profile[key]:
        raise ValueError(f'A role profile needs a nonempty {key}')


def validate_role(profile, role) -> dict:
    """The validated profile of `role`. Raises ValueError."""
    if role not in ROLES:
        raise ValueError('Unknown legal role: ' + str(role))
    if not isinstance(profile, dict):
        raise ValueError('A role profile must be an object')
    no_credentials(profile)
    fields(profile, PROFILE_KEYS)
    if profile.get('role') != role:
        raise ValueError('A role profile must name its role: ' + role)
    if 'serving' not in profile:
        raise ValueError('A role profile must declare serving')
    serving = profile['serving']
    if serving not in SERVING:
        raise ValueError('Unknown serving mode of a legal role: ' + str(serving))
    if serving == 'managed' and not MANAGED_SERVING_ENABLED:
        raise ValueError('Managed serving of legal roles is gated: qualify with model-offloading and declare serving: external')
    if profile.get('capability') != CAPABILITY[role]:
        raise ValueError(f'The {role} role needs capability {CAPABILITY[role]}')
    for key in ('platform', 'model', 'model_revision'):
        _string(profile, key)
    if role == 'embedder':
        if 'dimensions' not in profile:
            raise ValueError('An embedder profile needs dimensions')
        integer(profile['dimensions'], 'dimensions', 8, 8192)
    elif 'dimensions' in profile:
        raise ValueError('Only an embedder profile has dimensions')
    if serving == 'in-process':
        if IN_PROCESS_PLATFORMS.get(role) != profile['platform']:
            raise ValueError('In-process serving is only the fixture embedder (fixture-hash) and reranker (fixture-overlap)')
        fields(profile, IN_PROCESS_KEYS)
        return dict(profile)
    required = ['deployment_id', 'backend_version', 'protocol', 'endpoint', 'accelerator', 'timeout_s']
    if CAPABILITY[role] == 'chat':
        required += ['context_tokens', 'max_output_tokens']
    fields(profile, PROFILE_KEYS, required)
    identifier(profile['deployment_id'])
    _string(profile, 'backend_version')
    for key in ('artifact_sha256', 'template_sha256'):
        if profile.get(key) is not None and not (isinstance(profile[key], str) and HEX64.fullmatch(profile[key])):
            raise ValueError(key + ' must be 64 lowercase hex characters or null')
    for key in ('quantization', 'tokenizer_revision'):
        if profile.get(key) is not None and not isinstance(profile[key], str):
            raise ValueError(key + ' must be a string or null')
    if profile['protocol'] not in (('openai', 'ollama') if CAPABILITY[role] == 'chat' else ('json',)):
        raise ValueError('Unsupported protocol for the ' + role + ' role')
    network = profile.get('network')
    if network is not None and (not isinstance(network, dict) or network.get('kind', 'local') != 'local'):
        raise ValueError('Legal roles must be local: ' + role)      # the only rule that keeps matter text on the host
    adapters.configured_endpoint(profile['endpoint'], network)
    if 'api_key_env' in profile and not (isinstance(profile['api_key_env'], str) and ENV_NAME.fullmatch(profile['api_key_env'])):
        raise ValueError('api_key_env must name an environment variable')
    if CAPABILITY[role] == 'chat':
        integer(profile['context_tokens'], 'context_tokens', 1, 10_000_000)
        integer(profile['max_output_tokens'], 'max_output_tokens', 1, 10_000_000)
        if profile['max_output_tokens'] >= profile['context_tokens']:
            raise ValueError('max_output_tokens must be below context_tokens')
    elif 'context_tokens' in profile or 'max_output_tokens' in profile:
        raise ValueError('Only chat roles have context and output budgets')
    finite_number(profile['timeout_s'], 'timeout_s', 0.1, 3600)
    finite_number(profile.get('connect_timeout_s', 10), 'connect_timeout_s', 0.1, 30)
    if profile['accelerator'] not in ('cpu', 'gpu'):
        raise ValueError('accelerator must be cpu or gpu')
    if profile.get('placement') is not None:
        fields(profile['placement'], ['gpu_layers', 'gpu_offload', 'threads'])
        for key, value in profile['placement'].items():
            if value is not None:
                finite_number(value, 'placement ' + key, 0)
    if 'resource_host' in profile:
        identifier(profile['resource_host'])
    qualification = profile.get('qualification')
    if qualification is not None:
        # The locked serving profile is named explicitly and pinned by the planner (`serving_profile` is a path key);
        # nothing reads "the last result". Every mode that validates its roles therefore binds them.
        fields(qualification, ['serving_profile'], ['serving_profile'])
        if not isinstance(qualification['serving_profile'], str) or not qualification['serving_profile']:
            raise ValueError('qualification.serving_profile must be a path string')
        bind(profile, load_profile(qualification['serving_profile'])[0])
    return dict(profile)


def _serving_profile_sha256(profile, input_files):
    qualification = profile.get('qualification')
    if not isinstance(qualification, dict) or not isinstance(qualification.get('serving_profile'), str):
        return None
    recorded = {f['path']: f['sha256'] for f in input_files}
    return recorded.get(qualification['serving_profile'])


def profile_digest(profile, input_files=()) -> str:
    """Stable identity of a role: everything but the transport details. The qualification enters by the digest that the
    job's `input_files` recorded for it, so the file is never re-read and the digest can be recomputed from `job.json`."""
    identity = {k: v for k, v in profile.items() if k not in UNDIGESTED}
    identity['qualification'] = {'serving_profile_sha256': _serving_profile_sha256(profile, input_files)}
    return digest(identity)


def _attested_qualification(profile):
    """True when the bound profile's paging or placement is attested rather than observed; None when it cannot be read."""
    try:
        serving, _ = load_profile(profile['qualification']['serving_profile'])
    except ValueError:
        return None
    return serving['memory']['paging_observed']['nature'] == 'attested' or serving['placement']['observed']['nature'] == 'attested'


def public_role(profile, input_files=()) -> dict:
    """The metadata view of a role: identity only, no endpoint, host, path or environment name. A bound role is
    `qualified` and names its locked serving profile by the digest the job's `input_files` recorded; `qualified_by_attestation`
    says that the qualification rests on an operator attestation (paging or placement), so it is never presented as measured."""
    qualified = isinstance(profile.get('qualification'), dict)
    return {'profile_sha256': profile_digest(profile, input_files), **{k: profile.get(k) for k in PUBLIC_KEYS}, 'qualified': qualified,
            'qualified_by_attestation': _attested_qualification(profile) if qualified else False,
            'serving_profile_sha256': _serving_profile_sha256(profile, input_files) if qualified else None}


def bound_digest(profile) -> str:
    """`profile_digest` with the serving profile's current file digest as its recorded input: the identity of a role,
    serving profile included, where no job's `input_files` exist yet (plan time)."""
    qualification = profile.get('qualification')
    if not isinstance(qualification, dict) or not isinstance(qualification.get('serving_profile'), str):
        return profile_digest(profile)
    path = Path(qualification['serving_profile'])
    return profile_digest(profile, [{'path': qualification['serving_profile'], 'sha256': sha256_file(path)}] if path.is_file() else [])


def allowed_endpoints(roles) -> frozenset:
    """The endpoints of the served roles of a job, computed once from its planned parameters."""
    return frozenset(p['endpoint'] for p in (roles or {}).values()
                     if isinstance(p, dict) and p.get('serving') == 'external' and isinstance(p.get('endpoint'), str))


def require_allowed(endpoint, allowed) -> None:
    if endpoint not in allowed:
        raise ValueError('Endpoint is not on the job allowlist')


def json_request(profile, payload, allowed) -> object:
    """One bounded JSON request to an allowlisted local endpoint; the only connection this experiment's roles open."""
    require_allowed(profile.get('endpoint'), allowed)
    events = adapters.request_events(profile['endpoint'], payload, 'json', profile['timeout_s'], profile.get('api_key_env'))
    try:
        return next(events)
    finally:
        events.close()


TOKEN_SAFETY = 1.5        # model tokens per whitespace token, used by the context guards


def adapter_config(profile) -> dict:
    """The shared `adapters.HTTPAdapter` config of a chat role: both deadlines, usage requested, tool calls refused. No
    `network` key (legal roles are local) and no `request_options` (the payload is the adapter's)."""
    return {'protocol': profile['protocol'], 'endpoint': profile['endpoint'], 'api_key_env': profile.get('api_key_env'),
            'served_model': profile['model'], 'timeout_s': profile['timeout_s'], 'connect_timeout_s': profile.get('connect_timeout_s', 10),
            'context_tokens': profile['context_tokens'], 'request_usage': True, 'refuse_tool_calls': True}


def check_revisions(roles) -> None:
    for profile in (roles or {}).values():
        for key in ('model_revision', 'backend_version'):
            value = str(profile.get(key, ''))
            if 'REPLACE' in value or 'TODO' in value:
                raise ValueError('Record the exact loaded model revision before evaluating')


# Locked serving profile v1 --------------------------------------------------------------------------------------------
#
# Frozen from exactly one attempt of one `model-offloading` job that the operator names. Each measured or attested leaf
# is {"value", "nature"}; a value that is missing, or a placeholder (`REPLACE...`, `TODO`), is `unavailable` and is never
# estimated. Free text, paths, endpoints, PIDs and host names of the offload result are never copied. The probe outcome
# is a function of the profile's own values (`_probe`), so a profile whose outcome does not follow from them is refused.

SERVING_KIND = 'legal-serving-profile'
NATURES = ('observed', 'attested', 'declared', 'unavailable')
PROBE_OUTCOMES = ('passed', 'failed', 'inconclusive')
FAILED_REASONS = ('job_not_succeeded', 'request_errors', 'paging_observed', 'placement_mismatch', 'memory_reserve_exceeded')
INCONCLUSIVE_REASONS = ('paging_unknown', 'placement_unobserved', 'all_responses_truncated', 'no_measured_requests')
PROBE_REASONS = FAILED_REASONS + INCONCLUSIVE_REASONS
PLACEMENT_KEYS = ('gpu_layers', 'gpu_offload', 'threads')
REQUESTED_KEYS = PLACEMENT_KEYS + ('context_tokens', 'max_output_tokens')
TOKEN = re.compile(r'[A-Za-z0-9][A-Za-z0-9._+-]{0,63}')      # one attested or declared token: no space, path separator or colon
PLACEHOLDER = re.compile(r'(REPLACE_WITH_|TODO)')      # anchored and case-sensitive: `mastodon-tok-2` is a real value
ATTEMPT = re.compile(r'[0-9a-f]{32}')
REVISION40 = re.compile(r'[0-9a-f]{40}')
# The operator's attestation of paging (key `paging` of `hardware_attestation`): `none` or `observed`.
PAGING_ATTESTATION = {'none': False, 'observed': True}
# psutil reports no swap-in or swap-out counters on Windows (always 0), and a WSL guest's counters cannot see the host
# paging the VM: on both, sampled counters prove nothing and paging needs the operator's attestation.
SWAP_UNOBSERVABLE = ('windows-11-native', 'windows-11-wsl2-ubuntu-26.04')
SWAP_COUNTERS = ('swap_in_bytes', 'swap_out_bytes')
LEAF_GROUPS = {'os': ('os_id', 'environment_kind', 'os_build'), 'runtime': ('platform', 'backend_version'),
               'artifact': ('artifact_sha256', 'source_revision', 'quantization'), 'template': ('chat_template_sha256', 'tokenizer_revision')}
PEAKS = {'system_used_gib': 'system_used_gib_peak', 'swap_used_gib': 'swap_used_gib_peak', 'backend_tree_rss_gib': 'backend_tree_rss_gib_peak',
         'gpu_used_mib': 'gpu_used_mib_peak'}
TOTALS = ('host_ram_gib', 'gpu_vram_mib')
MEDIANS = ('output_tokens_per_wall_second', 'elapsed_s', 'first_output_s')
SERVING_KEYS = ('schema_version', 'kind', 'source', 'code_revision', 'harness_version', 'os', 'driver', 'runtime', 'artifact', 'template',
                'placement', 'memory', 'throughput', 'probe', 'workload')
SOURCE_KEYS = ('campaign_id', 'campaign_dir', 'plan_sha256', 'experiment_run_id', 'job_id', 'attempt_id', 'measurement', 'physical_host_id',
               'hardware_profile', 'result_status', 'measurement_status', 'files')
MEMORY_KEYS = ('reserve', 'totals', 'peaks', 'paging_observed', 'reserve_checked')
# Profile values a role must not bind to while they are unavailable: (field, group).
BIND_REQUIRED = (('platform', 'runtime'), ('backend_version', 'runtime'), ('artifact_sha256', 'artifact'), ('chat_template_sha256', 'template'),
                 ('quantization', 'artifact'), ('tokenizer_revision', 'template'), ('source_revision', 'artifact'))
CHAT_ONLY = ('chat_template_sha256', 'tokenizer_revision')      # an embedder, reranker or selector has no chat template
WORKLOAD_BENCHMARK = 'legal-shaped'


def _number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else None


def _token(value):
    return value if isinstance(value, str) and TOKEN.fullmatch(value) and not PLACEHOLDER.match(value) else None


def _hex64(value):
    return value if isinstance(value, str) and HEX64.fullmatch(value) else None


def _leaf(value, nature):
    return {'value': None, 'nature': 'unavailable'} if value is None else {'value': value, 'nature': nature}


def _object(value):
    return value if isinstance(value, dict) else {}


def _read(path):
    from .contracts import read_json_strict
    try:
        value = read_json_strict(path)[0]
    except OSError:
        raise ValueError('Offload attempt file is missing: ' + Path(path).name) from None
    if not isinstance(value, dict):
        raise ValueError('Malformed offload attempt file: ' + Path(path).name)
    return value


def _rows(path):
    from .contracts import read_jsonl
    try:
        rows = read_jsonl(path)
    except OSError:
        raise ValueError('Offload attempt file is missing: ' + Path(path).name) from None
    if not all(isinstance(r, dict) for r in rows):
        raise ValueError('Malformed offload request rows')
    return rows


def _samples(path):
    from .contracts import read_json_strict
    try:
        value = read_json_strict(path)[0]
    except OSError:
        raise ValueError('Offload attempt file is missing: telemetry.json') from None
    return [s for s in value if isinstance(s, dict)] if isinstance(value, list) else []


def _median(values):
    found = [v for v in (_number(x) for x in values) if v is not None]
    return round(float(statistics.median(found)), 6) if found else None


def _placement(observed):
    if observed is None:
        return {'value': None, 'nature': 'unavailable'}
    fields(observed, PLACEMENT_KEYS)
    if not observed:
        raise ValueError('An attested placement names at least one of: ' + ', '.join(PLACEMENT_KEYS))
    for key, value in observed.items():
        if _number(value) is None or value < 0:
            raise ValueError('An attested placement value must be a number at least 0: ' + key)
    return {'value': {k: observed[k] for k in PLACEMENT_KEYS if k in observed}, 'nature': 'attested'}


def _paging(samples, os_id, attestation):
    """Paging from the sampled swap counters where they mean something (at least two non-null samples of one counter, not
    on Windows); else the operator's attestation; else unavailable. The runner's `memory_assessment` is not evidence: it
    reports no paging whenever the counters do not grow, also where they never grow."""
    if os_id is not None and os_id not in SWAP_UNOBSERVABLE:
        series = [[_number(s.get(c)) for s in samples if _number(s.get(c)) is not None] for c in SWAP_COUNTERS]
        series = [values for values in series if len(values) >= 2]
        if series:
            return _leaf(any(values[-1] > values[0] for values in series), 'observed')
    attested = attestation.get('paging')
    return _leaf(PAGING_ATTESTATION.get(attested) if isinstance(attested, str) else None, 'attested')


def _reserve(memory):
    """(checked, exceeded): peak system memory against host RAM minus `host_reserve_gib`, peak GPU memory against VRAM
    minus `gpu_reserve_gib`. Checked only when every value of both comparisons is available."""
    value = lambda group, key: memory[group][key]['value']      # noqa: E731
    checks = [(value('peaks', 'system_used_gib'), value('totals', 'host_ram_gib'), value('reserve', 'host_reserve_gib'), 1),
              (value('peaks', 'gpu_used_mib'), value('totals', 'gpu_vram_mib'), value('reserve', 'gpu_reserve_gib'), 1024)]
    known = [c for c in checks if all(v is not None for v in c[:3])]
    return len(known) == len(checks), any(peak > total - reserve * factor for peak, total, reserve, factor in known)


def _probe(profile):
    """(outcome, reason codes in PROBE_REASONS order), computed from the profile's own values only."""
    source, throughput, memory, placement = profile['source'], profile['throughput'], profile['memory'], profile['placement']
    reasons = []
    if source['result_status'] != 'succeeded' or source['measurement_status'] != 'completed':
        reasons.append('job_not_succeeded')
    if throughput['errors']:
        reasons.append('request_errors')
    if memory['paging_observed']['value'] is True:
        reasons.append('paging_observed')
    observed = placement['observed']['value']
    if observed and any(placement['requested'].get(k) is not None and placement['requested'][k] != v for k, v in observed.items()):
        reasons.append('placement_mismatch')
    if _reserve(memory)[1]:
        reasons.append('memory_reserve_exceeded')
    if reasons:
        return 'failed', reasons
    if memory['paging_observed']['value'] is None:
        reasons.append('paging_unknown')
    if observed is None:
        reasons.append('placement_unobserved')
    ok = throughput['requests'] - throughput['errors']
    if ok == 0:
        reasons.append('no_measured_requests')
    elif throughput['truncated'] == ok:
        reasons.append('all_responses_truncated')
    return ('inconclusive' if reasons else 'passed'), sorted(reasons, key=PROBE_REASONS.index)


def freeze(campaign_dir, job_id, attempt_id, measurement=None, observed_placement=None) -> dict:
    """Locked serving profile v1 of one named attempt of one `model-offloading` job. Raises ValueError. There is no default
    that picks the newest campaign, job, attempt or measurement."""
    campaign = Path(campaign_dir).resolve()
    plan, state = _read(campaign / 'plan.json'), _read(campaign / 'campaign.json')
    if 'plan_sha256' in plan and digest({k: v for k, v in plan.items() if k != 'plan_sha256'}) != plan['plan_sha256']:
        raise ValueError('plan.json does not match its plan_sha256')
    job = next((j for j in plan.get('jobs', []) if isinstance(j, dict) and j.get('job_id') == job_id), None)
    if job is None:
        raise ValueError('Unknown job of this campaign: ' + str(job_id))
    if job.get('experiment_id') != 'model-offloading':
        raise ValueError('The job is not a model-offloading job')
    if _object(job.get('parameters')).get('synthetic'):
        raise ValueError('A synthetic run cannot qualify a serving profile')
    record = _object(_object(state.get('jobs')).get(job_id))
    attempt = next((a for a in record.get('attempts', []) if isinstance(a, dict) and a.get('attempt_id') == attempt_id), None)
    if attempt is None or not isinstance(attempt_id, str) or not ATTEMPT.fullmatch(attempt_id):
        raise ValueError('The attempt id is not an attempt of the job')
    if attempt.get('status') not in ('succeeded', 'failed'):
        raise ValueError('The attempt has no finished result: ' + str(attempt.get('status')))
    # The scheduler's layout, never a stored path string (Windows and WSL write different separators).
    directory = campaign / 'experiments' / identifier(job.get('experiment_run_id')) / 'jobs' / identifier(job_id) / attempt_id
    if not directory.is_dir():
        raise ValueError('The attempt directory is missing')
    stored, host, result = _read(directory / 'job.json'), _read(directory / 'host.json'), _read(directory / 'result.json')
    if stored.get('job_id') != job_id or stored.get('experiment_id') != 'model-offloading':
        raise ValueError('The attempt belongs to another job')
    if _object(stored.get('parameters')).get('synthetic'):
        raise ValueError('A synthetic run cannot qualify a serving profile')
    if result.get('status') != attempt.get('status'):
        raise ValueError('The campaign record and result.json disagree on the attempt status')
    names = sorted(p.name for p in (directory / 'measurements').iterdir() if p.is_dir()) if (directory / 'measurements').is_dir() else []
    if measurement is None:
        if len(names) != 1:
            raise ValueError('Name the measurement directory' if names else 'The attempt has no measurement directory')
        measurement = names[0]
    if measurement not in names:
        raise ValueError('Unknown measurement directory: ' + str(measurement))
    measured = directory / 'measurements' / measurement
    metadata, rows, samples = _read(measured / 'metadata.json'), _rows(measured / 'requests.jsonl'), _samples(measured / 'telemetry.json')
    if metadata.get('synthetic') is not False:
        raise ValueError('A synthetic run cannot qualify a serving profile')
    os_id, environment = _token(_object(job.get('hardware')).get('os_id')), _token(host.get('environment_kind'))
    if os_id and environment and os_id != environment:
        raise ValueError('The declared OS and the observed environment disagree')
    config = _object(metadata.get('config'))
    # A free-form operator dict: exactly three keys are read, each one token; nothing else of it is copied.
    attestation = _object(config.get('hardware_attestation'))
    launch, artifact, hardware = _object(config.get('launch')), _object(metadata.get('artifact')), _object(metadata.get('hardware_profile'))
    peaks = _object(metadata.get('telemetry'))
    gpus = [g for g in host.get('gpus', []) if isinstance(g, dict)] if isinstance(host.get('gpus'), list) else []
    observed_driver = _token(gpus[0].get('driver_version')) if gpus else None
    offload = launch.get('gpu_offload')
    requested = {'gpu_layers': _number(launch.get('gpu_layers')), 'gpu_offload': _number(offload) if _number(offload) is not None else _token(offload),
                 'threads': _number(launch.get('threads')), 'context_tokens': _number(config.get('context_tokens')),
                 'max_output_tokens': _number(config.get('max_output_tokens'))}
    measured_rows = [r for r in rows if r.get('warmup') is not True]
    ok = [r for r in measured_rows if r.get('status') == 'ok']
    files = sorted(['job.json', 'host.json', 'result.json'] + [f'measurements/{measurement}/{n}' for n in ('metadata.json', 'requests.jsonl', 'telemetry.json')])
    revision = plan.get('code_revision')
    memory = {'reserve': {'host_reserve_gib': _leaf(_number(hardware.get('host_reserve_gib')), 'declared'),
                          'gpu_reserve_gib': _leaf(_number(_object(hardware.get('gpu')).get('initial_reserve_gib')), 'declared')},
              'totals': {'host_ram_gib': _leaf(_number(host.get('ram_total_gib')), 'observed'),
                         'gpu_vram_mib': _leaf(_number(gpus[0].get('total_mib')) if gpus else None, 'observed')},
              'peaks': {name: _leaf(_number(peaks.get(key)), 'observed') for name, key in PEAKS.items()},
              'paging_observed': _paging(samples, os_id, attestation)}
    memory['reserve_checked'] = _reserve(memory)[0]
    profile = {
        'schema_version': 1, 'kind': SERVING_KIND,
        'source': {'campaign_id': identifier(plan.get('campaign_id')), 'campaign_dir': campaign.name, 'plan_sha256': _hex64(plan.get('plan_sha256')),
                   'experiment_run_id': identifier(job.get('experiment_run_id')), 'job_id': identifier(job_id), 'attempt_id': attempt_id,
                   'measurement': measurement, 'physical_host_id': identifier(_object(job.get('target')).get('physical_host_id')),
                   'hardware_profile': identifier(_object(job.get('hardware')).get('hardware_profile')),
                   'result_status': _token(result.get('status')), 'measurement_status': _token(metadata.get('status')),
                   'files': [{'path': p, 'sha256': sha256_file(directory / p)} for p in files]},
        'code_revision': revision if isinstance(revision, str) and REVISION40.fullmatch(revision) else None,
        'harness_version': _token(metadata.get('harness_version')),
        'os': {'os_id': _leaf(os_id, 'declared'), 'environment_kind': _leaf(environment, 'observed'),
               'os_build': _leaf(_token(attestation.get('os_build')), 'attested')},
        'driver': _leaf(observed_driver, 'observed') if observed_driver else _leaf(_token(attestation.get('nvidia_driver')), 'attested'),
        'runtime': {'platform': _leaf(_token(config.get('platform')), 'declared'),
                    'backend_version': _leaf(_token(config.get('backend_version')), 'attested')},
        'artifact': {'artifact_sha256': _leaf(_hex64(metadata.get('artifact_sha256')), 'observed'),
                     'source_revision': _leaf(_token(artifact.get('source_revision')), 'declared'),
                     'quantization': _leaf(_token(artifact.get('precision')), 'declared')},
        'template': {'chat_template_sha256': _leaf(_hex64(config.get('chat_template_sha256')), 'attested'),
                     'tokenizer_revision': _leaf(_token(config.get('tokenizer_revision')), 'attested')},
        'placement': {'requested': requested, 'observed': _placement(observed_placement)},
        'memory': memory,
        'throughput': {'requests': len(measured_rows), 'errors': len(measured_rows) - len(ok),
                       'truncated': sum(r.get('finish_reason') == 'length' for r in ok),
                       **{name + '_median': _leaf(_median(r.get(name) for r in ok), 'observed') for name in MEDIANS}},
        'workload': {'suite_sha256': _hex64(metadata.get('suite_sha256')), 'benchmark': _token(metadata.get('benchmark'))}}
    outcome, reasons = _probe(profile)
    profile['probe'] = {'outcome': outcome, 'reason_codes': reasons}
    return {k: profile[k] for k in SERVING_KEYS}


def _check_leaf(leaf, where, kind=None):
    fields(leaf, ['value', 'nature'], ['value', 'nature'])
    if leaf['nature'] not in NATURES:
        raise ValueError('Unknown nature of a serving profile value: ' + where)
    if (leaf['nature'] == 'unavailable') != (leaf['value'] is None):
        raise ValueError('An unavailable serving profile value is null, and only it: ' + where)
    value = leaf['value']
    if value is None:
        return
    if kind == 'placement':
        _placement(value)
    elif kind == 'bool':
        if type(value) is not bool:
            raise ValueError('Serving profile value must be true or false: ' + where)
    elif isinstance(value, str):
        if _token(value) is None:
            raise ValueError('Serving profile value must be one token: ' + where)
    elif _number(value) is None:
        raise ValueError('Serving profile value must be a token or a number: ' + where)


def validate_profile(profile) -> dict:
    """Closed-key validation of locked serving profile v1; the probe must follow from the profile's values. Raises."""
    try:
        fields(profile, SERVING_KEYS, SERVING_KEYS)
        if type(profile['schema_version']) is not int or profile['schema_version'] != 1 or profile['kind'] != SERVING_KIND:
            raise ValueError('Not a locked serving profile v1')
        source = profile['source']
        fields(source, SOURCE_KEYS, SOURCE_KEYS)
        for key in ('campaign_id', 'experiment_run_id', 'job_id', 'physical_host_id', 'hardware_profile'):
            identifier(source[key])
        if not all(isinstance(source[k], str) for k in ('attempt_id', 'measurement', 'campaign_dir')) or not ATTEMPT.fullmatch(source['attempt_id']) \
                or not TOKEN.fullmatch(source['measurement']) or not TOKEN.fullmatch(source['campaign_dir']):
            raise ValueError('Malformed serving profile source')
        if source['plan_sha256'] is not None and _hex64(source['plan_sha256']) is None:
            raise ValueError('Malformed serving profile source')
        for key in ('result_status', 'measurement_status'):
            if source[key] is not None and _token(source[key]) is None:
                raise ValueError('Malformed serving profile source')
        if not isinstance(source['files'], list):
            raise ValueError('Malformed serving profile source files')
        for f in source['files']:
            fields(f, ['path', 'sha256'], ['path', 'sha256'])
            if _hex64(f['sha256']) is None or not isinstance(f['path'], str):
                raise ValueError('Malformed serving profile source file')
        for key in ('code_revision', 'harness_version'):
            if profile[key] is not None and _token(profile[key]) is None:
                raise ValueError('Malformed serving profile ' + key)
        for group, keys in LEAF_GROUPS.items():
            fields(profile[group], keys, keys)
            for key in keys:
                _check_leaf(profile[group][key], group + '.' + key)
        _check_leaf(profile['driver'], 'driver')
        placement = profile['placement']
        fields(placement, ['requested', 'observed'], ['requested', 'observed'])
        fields(placement['requested'], REQUESTED_KEYS, REQUESTED_KEYS)
        for key, value in placement['requested'].items():
            if value is not None and _number(value) is None and _token(value) is None:
                raise ValueError('Malformed requested placement: ' + key)
        _check_leaf(placement['observed'], 'placement.observed', 'placement')
        memory = profile['memory']
        fields(memory, MEMORY_KEYS, MEMORY_KEYS)
        fields(memory['reserve'], ['host_reserve_gib', 'gpu_reserve_gib'], ['host_reserve_gib', 'gpu_reserve_gib'])
        fields(memory['totals'], TOTALS, TOTALS)
        fields(memory['peaks'], PEAKS, PEAKS)
        for group in ('reserve', 'totals', 'peaks'):
            for key, leaf in memory[group].items():
                _check_leaf(leaf, 'memory.' + key)
        _check_leaf(memory['paging_observed'], 'memory.paging_observed', 'bool')
        os_id = profile['os']['os_id']['value']
        if memory['paging_observed']['nature'] == 'observed' and os_id in SWAP_UNOBSERVABLE:
            raise ValueError('Paging cannot be observed on ' + os_id)
        if memory['reserve_checked'] is not _reserve(memory)[0]:
            raise ValueError('Serving profile probe does not follow from its values')
        throughput = profile['throughput']
        medians = [name + '_median' for name in MEDIANS]
        fields(throughput, ['requests', 'errors', 'truncated', *medians], ['requests', 'errors', 'truncated', *medians])
        integer(throughput['requests'], 'requests', 0, 10_000_000)
        integer(throughput['errors'], 'errors', 0, throughput['requests'])
        integer(throughput['truncated'], 'truncated', 0, throughput['requests'] - throughput['errors'])
        for name in medians:
            _check_leaf(throughput[name], name)
        workload = profile['workload']
        fields(workload, ['suite_sha256', 'benchmark'], ['suite_sha256', 'benchmark'])
        if (workload['suite_sha256'] is not None and _hex64(workload['suite_sha256']) is None) or \
                (workload['benchmark'] is not None and _token(workload['benchmark']) is None):
            raise ValueError('Malformed serving profile workload')
        probe = profile['probe']
        fields(probe, ['outcome', 'reason_codes'], ['outcome', 'reason_codes'])
        if probe['outcome'] not in PROBE_OUTCOMES or not isinstance(probe['reason_codes'], list):
            raise ValueError('Malformed serving profile probe')
        outcome, reasons = _probe(profile)
        if probe['outcome'] != outcome or probe['reason_codes'] != reasons:
            raise ValueError('Serving profile probe does not follow from its values')
    except (TypeError, AttributeError, KeyError):
        raise ValueError('Malformed locked serving profile') from None
    return profile


def write_profile(profile, path) -> str:
    """Canonical LF JSON (sorted keys, two-space indent), written atomically; returns the SHA-256 of the file."""
    from .contracts import write_text_atomic
    validate_profile(profile)
    write_text_atomic(path, json.dumps(profile, indent=2, sort_keys=True, ensure_ascii=False) + '\n')
    return sha256_file(path)


def load_profile(path) -> tuple[dict, str]:
    """(profile, SHA-256 of the bytes parsed) after closed-key validation."""
    from .contracts import read_json_strict
    try:
        profile, sha = read_json_strict(path)
    except OSError:
        raise ValueError('Locked serving profile not found') from None
    return validate_profile(profile), sha


def bind(role_profile, serving_profile) -> None:
    """The role must be exactly what the locked profile qualified, on an approved legal-shaped workload, and the probe
    must have passed. Context and output budgets are compared for chat roles only."""
    def mismatch(field):
        raise ValueError('Role profile does not match its locked serving profile: ' + field)
    s = serving_profile
    chat = CAPABILITY.get(role_profile.get('role')) == 'chat'
    for field, group in BIND_REQUIRED:
        if (chat or field not in CHAT_ONLY) and s[group][field]['value'] is None:
            raise ValueError(field + ' is unavailable in the locked profile')
    requested = s['placement']['requested']
    compared = [('platform', s['runtime']['platform']['value']), ('backend_version', s['runtime']['backend_version']['value']),
                ('artifact_sha256', s['artifact']['artifact_sha256']['value']), ('quantization', s['artifact']['quantization']['value']),
                ('model_revision', s['artifact']['source_revision']['value'])]
    if chat:      # the chat template and tokenizer bind chat roles only
        compared[4:4] = [('template_sha256', s['template']['chat_template_sha256']['value']),
                         ('tokenizer_revision', s['template']['tokenizer_revision']['value'])]
    for field, value in compared:
        if role_profile.get(field) != value:
            mismatch(field)
    if chat:
        if role_profile.get('context_tokens') != requested['context_tokens']:
            mismatch('context_tokens')
        limit = requested['max_output_tokens']
        if _number(role_profile.get('max_output_tokens')) is None or _number(limit) is None or role_profile['max_output_tokens'] > limit:
            mismatch('max_output_tokens')
    for key, value in (role_profile.get('placement') or {}).items():
        if value is not None and requested.get(key) != value:
            mismatch('placement')
    if s['workload']['benchmark'] != WORKLOAD_BENCHMARK or s['workload']['suite_sha256'] not in approved_workloads():
        raise ValueError('Locked serving profile was not measured on an approved legal-shaped workload')
    if s['probe']['outcome'] != 'passed':
        raise ValueError('Locked serving profile did not pass its probe')


def check_job(roles, job) -> None:
    """Run-time checks of the roles against the planned job. A qualified role runs from the profile bytes the planner
    pinned, on the physical host its profile was measured on; on the job's own host also with the job's hardware profile
    and OS (a separately hosted service's OS is not part of the job). Every externally served role's host is reserved."""
    recorded = {f['path']: f['sha256'] for f in job.get('input_files', [])}
    target = _object(job.get('target')).get('physical_host_id')
    for name, role in sorted((roles or {}).items()):
        host = role.get('resource_host') or target
        qualification = role.get('qualification')
        if isinstance(qualification, dict):
            profile, sha = load_profile(qualification['serving_profile'])
            if recorded.get(qualification['serving_profile']) != sha:
                raise ValueError('Locked serving profile differs from the planned input')
            if profile['source']['physical_host_id'] != host:
                raise ValueError('Locked serving profile was measured on another host')
            if host == target:
                if _object(job.get('hardware')).get('hardware_profile') != profile['source']['hardware_profile']:
                    raise ValueError('Locked serving profile was measured on another hardware profile')
                if _object(job.get('hardware')).get('os_id') != profile['os']['os_id']['value']:
                    raise ValueError('Locked serving profile was measured on another OS')
        if role.get('serving') == 'external':
            if host is None or host not in (job.get('resources') or []):
                raise ValueError('Role host is not reserved by this job: ' + name)


def workload(lock_path, arm='lexical-eligible', settings=None) -> dict:
    """The legal-shaped task suite of an approved fixture suite: every matter's full draft prompt of `arm`."""
    from . import contracts, retrieval
    from .workflow import build_messages
    contracts.export_allowed(lock_path)
    suite = contracts.load_suite(lock_path)
    view = contracts.candidate_view(suite)
    tasks = [{'id': m['matter_id'], 'category': 'legal', 'messages': build_messages(m, retrieval.retrieve(view, m, arm, settings or {})),
              'check': {'type': 'none'}} for m in sorted(view['matters']['matters'], key=lambda m: m['matter_id'])]
    return {'benchmark': WORKLOAD_BENCHMARK, 'category': 'legal', 'family': 'general', 'tasks': tasks}


_WORKLOADS = {}


def approved_workloads() -> dict:
    """{common.digest of the default legal-shaped export: benchmark id} of every approved suite: the only workload
    digests a locked serving profile binds with. Computed once per approved list."""
    from . import contracts
    approved = contracts.approved_suites()
    key = tuple(sorted(approved))
    if key not in _WORKLOADS:
        root = Path(__file__).resolve().parents[4] / 'experiments/legal-benchmark/workloads'
        locks = {sha256_file(p): p for p in sorted(root.glob('*/suite.lock.json'))}
        _WORKLOADS[key] = {digest(workload(locks[k])): approved[k]['benchmark_id'] for k in key if k in locks}
    return dict(_WORKLOADS[key])


def export_workload(lock_path, path, arm='lexical-eligible', settings=None) -> str:
    """Write the legal-shaped workload for qualifying serving settings with `model-offloading`. It holds matter text, so
    it exists only for approved fixture suites. Returns the file's SHA-256."""
    from .contracts import write_text_atomic
    write_text_atomic(path, json.dumps(workload(lock_path, arm, settings), indent=2, ensure_ascii=False) + '\n')
    return sha256_file(path)


def _placement_flag(text):
    found = {}
    for item in text.split(','):
        key, sep, value = item.partition('=')
        key = key.strip()
        if not sep or key in found:
            raise ValueError('--observed-placement takes KEY=NUMBER[,KEY=NUMBER]')
        try:
            found[key] = int(value) if re.fullmatch(r'\s*\d+\s*', value) else float(value)
        except ValueError:
            raise ValueError('--observed-placement takes KEY=NUMBER[,KEY=NUMBER]') from None
    return found


def main(argv=None) -> int:
    from .contracts import check_output
    parser = argparse.ArgumentParser(prog='python -m llm_eval.experiments.legal_benchmark.profiles')
    commands = parser.add_subparsers(dest='command', required=True)
    freezing = commands.add_parser('freeze', help='freeze a locked serving profile from one named model-offloading attempt')
    freezing.add_argument('--campaign-dir', required=True)
    freezing.add_argument('--job-id', required=True)
    freezing.add_argument('--attempt-id', required=True)
    freezing.add_argument('--measurement')
    freezing.add_argument('--observed-placement', help='attested placement, for example gpu_layers=20,threads=8')
    freezing.add_argument('--output', required=True)
    export = commands.add_parser('workload', help='export the legal-shaped workload of an approved fixture suite')
    export.add_argument('--suite', required=True)
    export.add_argument('--output', required=True)
    args = parser.parse_args(argv)
    if args.command == 'freeze':
        check_output(args.output, 'The serving profile')
        observed = _placement_flag(args.observed_placement) if args.observed_placement else None
        sha = write_profile(freeze(args.campaign_dir, args.job_id, args.attempt_id, args.measurement, observed), args.output)
    else:
        check_output(args.output, 'The workload')
        sha = export_workload(args.suite, args.output)
    print(sha)
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except ValueError as exc:
        print('Error: ' + str(exc), file=sys.stderr)
        raise SystemExit(2) from None
