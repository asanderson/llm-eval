"""Legal benchmark experiment: retrieval, evidence-grounded analysis and draft screening memos for human review.

Registered modes: `smoke` (a deterministic fixture pipeline over fictional matters with no model, network or GPU),
`retrieval` (the retrieval arms and their metrics), `generation` (one direct draft request per matter and arm),
`workflow` (analyse, draft, verify and at most one bounded revision) and `score` (grade the stored outputs of an
earlier attempt into a new attempt, CPU only). Each mode is a module that exports `PARAMETERS`, `execution_kind`, `check`, optionally `inputs`, and `run`.
"""
from __future__ import annotations

from importlib import import_module
import json
from pathlib import Path

from llm_eval.core.contracts import fields

from . import fixture
from .contracts import load_suite, pinned_files

MODE_MODULES = {'smoke': 'fixture', 'retrieval': 'retrieval', 'generation': 'workflow', 'workflow': 'workflow', 'score': 'grading'}
MANIFEST = {'id': 'legal-benchmark', 'version': 1, 'modes': list(MODE_MODULES),
            'description': 'Legal retrieval, evidence-grounded analysis and draft screening memos for human review'}
BENCHMARK = 'legal-smoke'
# Legal results stay out of the generic top-combinations ranking of the results index (read through `plugin_hook`).
GENERIC_RANKING = False
# Directory names the generic report builder tests on the absolute path of every file it scans.
SCANNED_DIRECTORIES = ('model_judgment', 'reports')


def _module(mode):
    """The module that implements `mode`."""
    return import_module('.' + MODE_MODULES[mode], __name__)


def host_requirements(parameters, mode):
    """Explicit host requirement of a job that is not a fixture. Read by the worker (and by readiness after package E)."""
    module = _module(mode)
    return module.host(parameters, mode) if hasattr(module, 'host') else {'gpu': True}


def job_status(rows):
    """One rule for every mode: a job fails only when it has no row or every row is an error. Rows with status
    `error` or `missing` are results."""
    return 'failed' if not rows or all(r.get('status') == 'error' for r in rows) else 'succeeded'


def _parameters(case, mode):
    if not isinstance(mode, str) or mode not in MODE_MODULES:
        raise ValueError('Unsupported legal-benchmark mode: ' + str(mode))
    allowed, required = _module(mode).PARAMETERS[mode]
    fields(case, {'suite', 'synthetic', *allowed}, ['suite', *required])
    if not isinstance(case['suite'], str):
        raise ValueError('The legal-benchmark suite must be a path string')


def _admit(case, suite, root, mode):
    """The checks of a loaded suite that `validate` and `execute` share."""
    module = _module(mode)
    # Only execution_kind `fixture` maps to legacy `synthetic: true`; a model run over fictional facts is a measurement.
    if module.execution_kind(case, mode) == 'fixture':
        if case.get('synthetic') is not True:
            raise ValueError('The smoke mode is a fixture run and must declare synthetic: true' if mode == 'smoke'
                             else 'A fixture run must declare synthetic: true')
    elif case.get('synthetic', False) is not False:
        raise ValueError('Only fixture runs may declare synthetic: true')
    data_class = suite['lock']['data_class']
    if mode == 'smoke' and data_class != 'public-synthetic':
        raise ValueError('The smoke mode accepts public-synthetic suites only')
    if data_class == 'private-matter':
        raise ValueError('This mode does not accept private-matter suites')
    fixture.check_gold(suite)      # every mode: no mode plans on gold that its own eligibility rule contradicts
    return module.check(case, suite, root, mode)


def validate(case, root, mode='smoke'):
    """Side-effect-free: reads and hashes the declared suite, nothing else."""
    _parameters(case, mode)
    return _admit(case, load_suite(case['suite']), root, mode)


def input_files(parameters, root, mode):
    """Every file the suite lock pins, plus the mode's own inputs, so planner, resume and worker check the same bytes."""
    files = [str(path) for path in pinned_files(parameters['suite'])]
    module = _module(mode)
    if hasattr(module, 'inputs'):
        files += [str(path) for path in module.inputs(parameters, load_suite(parameters['suite']), root, mode)]
    return files


def setup_platforms(parameters, mode):
    """Serving platforms to install before a run, derived from the roles: only a role with `serving: managed` needs one.
    Managed serving is gated at plan time, so a legal campaign installs nothing and never infers an Ollama install."""
    roles = parameters.get('roles') if isinstance(parameters.get('roles'), dict) else {}
    return sorted({p['platform'] for p in roles.values() if isinstance(p, dict) and p.get('serving') == 'managed' and isinstance(p.get('platform'), str)})


def _planned_suite(job):
    """The suite loaded once and bound to the plan: the lock bytes parsed must have the digest the planner recorded for
    `parameters.suite`, and the lock pins every other suite file by content."""
    suite = load_suite(job['parameters']['suite'])
    planned = {f['path']: f['sha256'] for f in job.get('input_files', [])}
    if planned.get(job['parameters']['suite']) != suite['lock_sha256']:
        raise ValueError('Suite differs from the planned input')
    return suite


def data_policy(job):
    """Whether a job may run here and whether its data may leave the host: the one classification of `reporting.classify`."""
    from . import reporting
    return reporting.data_policy(job)


def reporting_policy(jobs):
    """What the generic reporting layer may do with these jobs: a local projected report, never automatic publication.
    Decided from the planned inputs, never from a campaign's reporting settings or a report's own labels."""
    from . import reporting
    return reporting.reporting_policy(jobs)


def report_projection(campaign_dir, plan, state, exp, **options):
    """The strict allowlisted projection that replaces the generic raw scan for this experiment."""
    from . import reporting
    return reporting.project(campaign_dir, plan, state, exp, **options)


def verify_publication(report, root, base=None):
    """The publication gate: ValueError(<reason code>) unless the bundle is the authorized projection of approved inputs."""
    from . import reporting
    return reporting.verify_publication(report, root, base)


def claims_bundle(report, dest, manifest, resolved, records):
    """True when a bundle of another experiment carries legal content (by content, not by name)."""
    from . import reporting
    return reporting.claims_bundle(report, dest, manifest, resolved, records)


def attempt_receipt(directory):
    """What the coordinator records about a finished attempt: its output-manifest digest."""
    from . import reporting
    return reporting.attempt_receipt(directory)


def claims_benchmark(name):
    """True for a benchmark name this plugin writes (`legal-smoke` and every later `legal-*` export). A bundle of another
    experiment that carries such a name has a second identity and is refused by `publish_report`. The name is compared after
    NFKC normalisation, case folding and removal of `-`, `_` and spaces: `LEGAL_smoke`, ` legal smoke` and fullwidth letters
    are claimed too."""
    import re
    import unicodedata
    return re.sub(r'[-_\s]', '', unicodedata.normalize('NFKC', str(name)).casefold()).startswith('legal')


# Files a publication branch must not change: the reviewed approved list decides what may be published.
PROTECTED_PATHS = ('experiments/legal-benchmark/approved-suites.json',)


def execute(job, output, root):
    parameters, mode = job['parameters'], job['mode']
    _parameters(parameters, mode)
    suite = _planned_suite(job)      # the only load of the run: a suite changed after planning, even relocked, fails here
    _admit(parameters, suite, root, mode)
    output = Path(output)
    scanned = sorted(set(SCANNED_DIRECTORIES) & set(output.resolve().parts))
    if scanned:
        raise ValueError('Attempt path has a directory name the generic report scans: ' + scanned[0])
    if (output / 'requests.jsonl').exists():
        raise ValueError('This attempt already has request records')
    output.mkdir(parents=True, exist_ok=True)
    result = _module(mode).run(job, suite, output, root)
    rows = [json.loads(line) for line in (output / 'requests.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
    return {**result, 'status': job_status(rows)}
