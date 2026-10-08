# Add an experiment

1. Create `experiments/YOUR-ID/experiment.json`, a README, case configurations and any experiment-specific workloads. The manifest declares `id`, integer `version`, `modes` and a mapping of case aliases to JSON paths.
2. Create `src/llm_eval/experiments/YOUR_MODULE/__init__.py`. Export `MANIFEST`, `validate(case, root, mode)` and `execute(job, output, root)`. Register the module in `llm_eval.experiments.REGISTRY`.
3. Validate parameters without network calls or mutations. Return an explicit skip reason only for unsupported combinations; raise for invalid configuration.
4. Execute within the supplied attempt directory. Return a terminal result (`succeeded`, `failed`, `skipped`, `cancelled`). Never manage another job's processes or overwrite another attempt.
5. Emit `requests.jsonl` with task/category IDs, status, repetition, warmup/synthetic labels and applicable measured values; use metadata/telemetry files for provenance. Preserve null for unavailable measurements. Register a custom exporter/summary if your experiment's metrics do not fit the shared report fields.
6. Add deterministic protocol/metric fixtures and an example campaign. Keep optional runtime dependencies isolated. Verify your new experiment with the existing campaign planner, scheduler and report workflow.

The scheduler consumes job/resource contracts and does not branch on experiment names. A new experiment should not need scheduler or CLI parsing changes. The initial worker assumes a version-matched prepared checkout, profile-based host checks, and whole-host measurement isolation. Extend those capabilities explicitly when a new experiment needs a different execution model.
