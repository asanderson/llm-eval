"""Role profile v1: one shape for every served role of the legal benchmark, and the job's endpoint allowlist.

A role is reached only through an explicit, pinned profile. `serving` must be declared; `managed` is recognised and
gated; `in-process` exists only for the deterministic fixture embedder and reranker. Every served role is local:
the allowlist is computed from the planned job, and `json_request` is the only opener of embedding and rerank requests.
"""
from __future__ import annotations

import re

from llm_eval import adapters
from llm_eval.common import digest, finite_number
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
    if profile.get('qualification') is not None:
        raise ValueError('Role qualification is not available yet')
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


def public_role(profile) -> dict:
    """The metadata view of a role: identity only, no endpoint, host, path or environment name."""
    return {'profile_sha256': profile_digest(profile), **{k: profile.get(k) for k in PUBLIC_KEYS}, 'qualified': False,
            'serving_profile_sha256': None}


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
