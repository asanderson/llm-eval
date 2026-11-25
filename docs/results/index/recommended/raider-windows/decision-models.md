# decision-models on raider-windows

[Setup evidence](../README.md) · [Results index](../../README.md)

**One recent run** · 2026-11-15 · llm-eval-nimble:locked on ollama. 2 tasks × 3 measured attempts. 6/6 requests completed and 6/6 checks passed.

Each check asks whether the router selected the expected label. The timing covers the decision. Downstream answer quality and end-to-end generation cost require a different experiment.

[Report](../../../llm-routing/campaign-20261115T130420Z-a4e6c761-routing-llm-routing-1/README.md) · [Config](../../../llm-routing/campaign-20261115T130420Z-a4e6c761-routing-llm-routing-1/resolved-config.json) · [CSV](../../../llm-routing/campaign-20261115T130420Z-a4e6c761-routing-llm-routing-1/summary.csv) · [Raw](../../../llm-routing/campaign-20261115T130420Z-a4e6c761-routing-llm-routing-1/raw/measurements.jsonl.gz)

## Matched model comparisons

A group changes the model package within one publication on one hardware configuration and runtime. The suite hashes, exact prompts, measured repetitions, scorer code and recorded request settings must match. The package includes its tokenizer and template. Failed jobs and runs with incomplete controls remain in the run history.

Times are descriptive. Host paging, model-specific defaults, cache reuse and independent sessions can be unobserved. Each row shows this run’s observed median among completed requests. Repeated prompts on one host do not establish uncertainty across machines or general model quality. The downloadable manifest contains each full comparison key and its inputs.

### ollama · 2026-11-15 · 018bb9abd028

Fixed workload and settings include 2 tasks × 3 measured attempts, protocol systemone, mode decision and hardware raider-windows. Backend version: not recorded. Comparison question: router label agreement on identical prompts.

| Model package | Completed | Checks passed | Wall time (median s) | Time until text appears (median s) | Backend decode (median tok/s) |
|---|---:|---:|---:|---:|---:|
| llm-eval-nimble:locked | 6/6 | 6/6 | 0.0602 | not recorded | not recorded |
| llm-eval-tev1:locked | 6/6 | 6/6 | 0.0412 | not recorded | not recorded |

Paired wall-time differences use llm-eval-nimble:locked as the alphabetically first reference. For each identical prompt, subtract the reference median from the other model’s median. The range spans the observed prompts. Negative values mean a shorter wait.

| Model package | Paired prompts | Median difference (s) | Observed range (s) |
|---|---:|---:|---:|
| llm-eval-tev1:locked | 2 | -0.0236 | -0.0323–-0.0148 |

### ollama · 2026-11-08 · 6c73b6de9709

Fixed workload and settings include 2 tasks × 3 measured attempts, protocol systemone, mode decision and hardware raider-windows. Backend version: not recorded. Comparison question: router label agreement on identical prompts.

| Model package | Completed | Checks passed | Wall time (median s) | Time until text appears (median s) | Backend decode (median tok/s) |
|---|---:|---:|---:|---:|---:|
| llm-eval-nimble:locked | 6/6 | 6/6 | 0.0496 | not recorded | not recorded |
| llm-eval-tev1:locked | 6/6 | 6/6 | 0.0284 | not recorded | not recorded |

Paired wall-time differences use llm-eval-nimble:locked as the alphabetically first reference. For each identical prompt, subtract the reference median from the other model’s median. The range spans the observed prompts. Negative values mean a shorter wait.

| Model package | Paired prompts | Median difference (s) | Observed range (s) |
|---|---:|---:|---:|
| llm-eval-tev1:locked | 2 | -0.0214 | -0.0222–-0.0206 |

## Reproduce a run

Choose a dated report in the table. The manifest pins the code revision. Config records the planned job, input hashes and launch settings. CSV contains category summaries. Raw contains the published measurements. Some older bundles omit artifacts or runtime details. Local paths have been removed.

[Read the reproduction recipe](../../../../REPRODUCE.md) · [Download the comparison manifest](decision-models.json).

For the newest listed job (ollama-nimble) run this from the repository root.

```sh
llm-eval result-inputs --input docs/results/llm-routing/campaign-20261115T130420Z-a4e6c761-routing-llm-routing-1 --job routing-llm-routing-1-389a241fd7b8
```

## Run history

One row per published job, newest first. A completed request can still fail its check. Output-cap and reload conditions can differ between rows. Use a matched group for a controlled comparison. Projection rows count candidate settings. Legal jobs expose aggregate evidence by cohort.

| Date | Model / runtime | Mode and status | Actual workload | Completed | Checks passed | Median wall s | First visible text s | Backend decode tok/s | Evidence |
|---|---|---|---|---:|---:|---:|---:|---:|---|
| 2026-11-15 | llm-eval-nimble:locked · ollama | decision · succeeded | 2 tasks × 3 measured attempts | 6/6 | 6/6 | 0.0602 | not recorded | not recorded | [Report](../../../llm-routing/campaign-20261115T130420Z-a4e6c761-routing-llm-routing-1/README.md) · [Config](../../../llm-routing/campaign-20261115T130420Z-a4e6c761-routing-llm-routing-1/resolved-config.json) · [Manifest](../../../llm-routing/campaign-20261115T130420Z-a4e6c761-routing-llm-routing-1/manifest.json) · [CSV](../../../llm-routing/campaign-20261115T130420Z-a4e6c761-routing-llm-routing-1/summary.csv) · [Raw](../../../llm-routing/campaign-20261115T130420Z-a4e6c761-routing-llm-routing-1/raw/measurements.jsonl.gz) |
| 2026-11-15 | llm-eval-tev1:locked · ollama | decision · succeeded | 2 tasks × 3 measured attempts | 6/6 | 6/6 | 0.0412 | not recorded | not recorded | [Report](../../../llm-routing/campaign-20261115T130420Z-a4e6c761-routing-llm-routing-1/README.md) · [Config](../../../llm-routing/campaign-20261115T130420Z-a4e6c761-routing-llm-routing-1/resolved-config.json) · [Manifest](../../../llm-routing/campaign-20261115T130420Z-a4e6c761-routing-llm-routing-1/manifest.json) · [CSV](../../../llm-routing/campaign-20261115T130420Z-a4e6c761-routing-llm-routing-1/summary.csv) · [Raw](../../../llm-routing/campaign-20261115T130420Z-a4e6c761-routing-llm-routing-1/raw/measurements.jsonl.gz) |
| 2026-11-08 | llm-eval-nimble:locked · ollama | decision · succeeded | 2 tasks × 3 measured attempts | 6/6 | 6/6 | 0.0496 | not recorded | not recorded | [Report](../../../llm-routing/campaign-20261108T035738Z-332b0246-routing-llm-routing-1/README.md) · [Config](../../../llm-routing/campaign-20261108T035738Z-332b0246-routing-llm-routing-1/resolved-config.json) · [Manifest](../../../llm-routing/campaign-20261108T035738Z-332b0246-routing-llm-routing-1/manifest.json) · [CSV](../../../llm-routing/campaign-20261108T035738Z-332b0246-routing-llm-routing-1/summary.csv) · [Raw](../../../llm-routing/campaign-20261108T035738Z-332b0246-routing-llm-routing-1/raw/measurements.jsonl.gz) |
| 2026-11-08 | llm-eval-tev1:locked · ollama | decision · succeeded | 2 tasks × 3 measured attempts | 6/6 | 6/6 | 0.0284 | not recorded | not recorded | [Report](../../../llm-routing/campaign-20261108T035738Z-332b0246-routing-llm-routing-1/README.md) · [Config](../../../llm-routing/campaign-20261108T035738Z-332b0246-routing-llm-routing-1/resolved-config.json) · [Manifest](../../../llm-routing/campaign-20261108T035738Z-332b0246-routing-llm-routing-1/manifest.json) · [CSV](../../../llm-routing/campaign-20261108T035738Z-332b0246-routing-llm-routing-1/summary.csv) · [Raw](../../../llm-routing/campaign-20261108T035738Z-332b0246-routing-llm-routing-1/raw/measurements.jsonl.gz) |
