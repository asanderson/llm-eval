# Add an experiment

1. Create `experiments/YOUR-ID/experiment.json`, a README, case configurations and any experiment-specific workloads. The manifest declares `id`, integer `version`, `modes` and a mapping of case aliases to JSON paths.
2. Create `src/llm_eval/experiments/YOUR_MODULE/__init__.py`. Export `MANIFEST`, `validate(case, root, mode)` and `execute(job, output, root)`. Register the module in `llm_eval.experiments.REGISTRY`.
3. Validate parameters without network calls or mutations. Return an explicit skip reason only for unsupported combinations; raise for invalid configuration.
4. Execute within the supplied attempt directory. Return a terminal result (`succeeded`, `failed`, `skipped`, `cancelled`). Never manage another job's processes or overwrite another attempt.
5. Emit `requests.jsonl` with task/category IDs, status, repetition, warmup/synthetic labels and applicable measured values; use metadata/telemetry files for provenance. Preserve null for unavailable measurements. Register a custom exporter/summary if your experiment's metrics do not fit the shared report fields.
6. Add deterministic protocol/metric fixtures and an example campaign. Keep optional runtime dependencies isolated. Verify your new experiment with the existing campaign planner, scheduler and report workflow.

## Optional plugin hooks

A plugin module may also export any of these. Experiments that do not export them keep the default behavior.

| Hook | Called by | Purpose |
|---|---|---|
| `input_files(parameters, root, mode)` | planner | Further files the job depends on, for example everything a suite lock pins. They are hashed into the plan and the job, so planner, resume and worker check the same bytes. |
| `setup_platforms(parameters, mode)` | `setup` | Serving platforms to install. Return an empty list when the job needs none. Without the hook the platform comes from `config.platform`, else `router.platform`, else `ollama`. |
| `reporting_policy(jobs)` | report generation, finalization, publication, planner | Returns `{'report': bool, 'publish': bool, 'reason': str}`. Decide it from the planned jobs, never from reporting settings. `report: false` records the report as `disabled`; `publish: false` rejects `publish.mode: pull-request` at plan time and refuses `publish-results`. |
| `host_requirements(parameters, mode)` | worker preflight, readiness | Returns `{'gpu': bool}` for a job that is not synthetic. `gpu: false` lets worker preflight skip the hardware-profile GPU check (every other preflight check still runs) and lets `readiness.select` count the job as needing no GPU. Without the hook every non-synthetic job needs the GPU. |
| `data_policy(job)` | planner, scheduler, worker (run and collection) | Returns at least `{'admit': bool, 'transfer': bool, 'reason': str}`. `admit: false` refuses the job at plan time (`Job is not admitted by the data policy of <job>: <reason>`), fails it in the scheduler with reason `data_policy` before any attempt, and makes the worker refuse it (`Data policy refused the job`). `transfer: false` refuses an SSH target at plan time and refuses remote collection on both sides. Without the hook everything is admitted and transferable. |
| `attempt_receipt(directory)` | scheduler, when an attempt finishes | Returns a dict merged into the attempt's record in `campaign.json` (the legal plugin records `file_sha256` and `output_manifest_sha256`). |
| `report_projection(campaign_dir, plan, state, exp)` | report generation | Returns the projected report (records, summary, README, extra files, manifest keys). When present it replaces the generic scan of the attempt directories completely; the bundle is written as canonical bytes and has no chart. |
| `verify_publication(report, root, base=None)` | `publish-results` | Raises `ValueError(<reason code>)` unless the bundle may be published. When present it replaces the `reporting_policy` publication check for that experiment. |
| `claims_benchmark(name)` | `publish-results` (identity check) | True for a benchmark name the plugin writes. A bundle of another experiment that carries such a name is refused. |
| `claims_bundle(report, dest, manifest, resolved, records)` | `publish-results` (identity check) | Returns the class of a content mark (a string) when a bundle of another experiment carries this plugin's content, else a false value. The bundle is refused, naming only the class. |
| `PROTECTED_PATHS` | `publish-results` | Repository paths a publication branch must not change relative to the fetched base branch (`Publication branch changes a protected file`). |
| `GENERIC_RANKING` | results index | `False` keeps the experiment's results out of the generic top-combinations ranking. |

`legal-benchmark` uses every hook in this table; see [its README](../experiments/legal-benchmark/README.md) and the [legal benchmark walkthrough](LEGAL_BENCHMARK_WALKTHROUGH.md).

## Frozen inputs: path keys

The planner resolves the value of every key named in `planner.PATH_KEYS`, at any depth of a case's `parameters`, relative to the case file, and, when the resolved value names an existing file, hashes that file into the plan and the job; a value that names no file is resolved but not pinned, and the experiment's own validation decides whether that is an error. The names are `suite`, `artifact_root`, `artifact_lock`, `offload_dir`, `installation_state`, `replay`, `data`, `benchmark_registry`, `output_manifest`, `review_file`, `review_key`, `serving_profile` and `calibration_file`. An experiment uses them for frozen inputs: a suite lock, an output manifest of an earlier attempt, a review file and its key, a locked serving profile, a calibration record. **A path key is rewritten at any depth**, so its name must never be usable as an operator-chosen label (a router label, a category, a criterion name): such a value would be turned into an absolute path and pinned as a file.

The scheduler consumes job/resource contracts and does not branch on experiment names. A new experiment should not need scheduler or CLI parsing changes. The initial worker assumes a version-matched prepared checkout, profile-based host checks, and whole-host measurement isolation. Extend those capabilities explicitly when a new experiment needs a different execution model.
