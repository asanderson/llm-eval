# decision-models on raider-wsl

[Setup evidence](../README.md) · [Results index](../../README.md)

**One recent run** · 2026-11-24 · llm-eval-clef-flash:locked on ollama. 2 tasks × 3 measured attempts. 6/6 requests completed and 6/6 checks passed.

Each check asks whether the router selected the expected label. The timing covers the decision. Downstream answer quality and end-to-end generation cost require a different experiment.

[Report](../../../decision-models/campaign-20261124T224634Z-f70bba1c-routing-decision-models-1/README.md) · [Config](../../../decision-models/campaign-20261124T224634Z-f70bba1c-routing-decision-models-1/resolved-config.json) · [CSV](../../../decision-models/campaign-20261124T224634Z-f70bba1c-routing-decision-models-1/summary.csv) · [Raw](../../../decision-models/campaign-20261124T224634Z-f70bba1c-routing-decision-models-1/raw/measurements.jsonl.gz)

## Matched model comparisons

A group changes the model package within one publication on one hardware configuration and runtime. The suite hashes, exact prompts, measured repetitions, scorer code and recorded request settings must match. The package includes its tokenizer and template. Failed jobs and runs with incomplete controls remain in the run history.

Times are descriptive. Host paging, model-specific defaults, cache reuse and independent sessions can be unobserved. Each row shows this run’s observed median among completed requests. Repeated prompts on one host do not establish uncertainty across machines or general model quality. The downloadable manifest contains each full comparison key and its inputs.

### ollama · 2026-11-24 · e08f398039c5

Fixed workload and settings include 2 tasks × 3 measured attempts, protocol systemone, mode decision and hardware raider-wsl. Backend version: not recorded. Comparison question: router label agreement on identical prompts.

| Model package | Completed | Checks passed | Wall time (median s) | Time until text appears (median s) | Backend decode (median tok/s) |
|---|---:|---:|---:|---:|---:|
| llm-eval-clef-flash:locked | 6/6 | 6/6 | 0.0554 | not recorded | not recorded |
| llm-eval-clef:locked | 6/6 | 6/6 | 0.534 | not recorded | not recorded |
| llm-eval-d1-omni:locked | 6/6 | 6/6 | 0.0379 | not recorded | not recorded |
| llm-eval-d1:locked | 6/6 | 6/6 | 0.0177 | not recorded | not recorded |
| llm-eval-laya:locked | 6/6 | 6/6 | 0.0141 | not recorded | not recorded |
| llm-eval-nimble-v3:locked | 6/6 | 6/6 | 0.055 | not recorded | not recorded |
| llm-eval-nimble:locked | 6/6 | 6/6 | 0.0519 | not recorded | not recorded |
| llm-eval-pplx-decider:locked | 6/6 | 6/6 | 0.103 | not recorded | not recorded |
| llm-eval-tev1-0.8b:locked | 6/6 | 6/6 | 0.0147 | not recorded | not recorded |
| llm-eval-tev1:locked | 6/6 | 6/6 | 0.0265 | not recorded | not recorded |

Paired wall-time differences use llm-eval-clef-flash:locked as the alphabetically first reference. For each identical prompt, subtract the reference median from the other model’s median. The range spans the observed prompts. Negative values mean a shorter wait.

| Model package | Paired prompts | Median difference (s) | Observed range (s) |
|---|---:|---:|---:|
| llm-eval-clef:locked | 2 | 0.48 | 0.448–0.512 |
| llm-eval-d1-omni:locked | 2 | -0.0178 | -0.0197–-0.0159 |
| llm-eval-d1:locked | 2 | -0.0383 | -0.0402–-0.0365 |
| llm-eval-laya:locked | 2 | -0.0408 | -0.0412–-0.0403 |
| llm-eval-nimble-v3:locked | 2 | 0.000132 | -0.000725–0.000989 |
| llm-eval-nimble:locked | 2 | -0.00638 | -0.00976–-0.00299 |
| llm-eval-pplx-decider:locked | 2 | 0.0432 | 0.0339–0.0525 |
| llm-eval-tev1-0.8b:locked | 2 | -0.0368 | -0.0412–-0.0323 |
| llm-eval-tev1:locked | 2 | -0.0276 | -0.0277–-0.0276 |

### ollama · 2026-11-18 · e282ec3a85ba

Fixed workload and settings include 2 tasks × 3 measured attempts, protocol systemone, mode decision and hardware raider-wsl. Backend version: not recorded. Comparison question: router label agreement on identical prompts.

| Model package | Completed | Checks passed | Wall time (median s) | Time until text appears (median s) | Backend decode (median tok/s) |
|---|---:|---:|---:|---:|---:|
| llm-eval-nimble:locked | 6/6 | 6/6 | 0.0526 | not recorded | not recorded |
| llm-eval-tev1:locked | 6/6 | 6/6 | 0.0249 | not recorded | not recorded |

Paired wall-time differences use llm-eval-nimble:locked as the alphabetically first reference. For each identical prompt, subtract the reference median from the other model’s median. The range spans the observed prompts. Negative values mean a shorter wait.

| Model package | Paired prompts | Median difference (s) | Observed range (s) |
|---|---:|---:|---:|
| llm-eval-tev1:locked | 2 | -0.0278 | -0.0293–-0.0262 |

### ollama · 2026-11-24 · ef474d5f9f67

Fixed workload and settings include 2 tasks × 3 measured attempts, protocol systemone, mode decision and hardware raider-wsl. Backend version: not recorded. Comparison question: router label agreement on identical prompts.

| Model package | Completed | Checks passed | Wall time (median s) | Time until text appears (median s) | Backend decode (median tok/s) |
|---|---:|---:|---:|---:|---:|
| llm-eval-clef-flash:locked | 6/6 | 6/6 | 0.0453 | not recorded | not recorded |
| llm-eval-clef:locked | 6/6 | 6/6 | 0.441 | not recorded | not recorded |
| llm-eval-d1-omni:locked | 6/6 | 6/6 | 0.0131 | not recorded | not recorded |
| llm-eval-d1:locked | 6/6 | 6/6 | 0.0119 | not recorded | not recorded |
| llm-eval-laya:locked | 6/6 | 6/6 | 0.0179 | not recorded | not recorded |
| llm-eval-nimble-v3:locked | 6/6 | 6/6 | 0.0442 | not recorded | not recorded |
| llm-eval-nimble:locked | 6/6 | 6/6 | 0.0514 | not recorded | not recorded |
| llm-eval-pplx-decider:locked | 6/6 | 6/6 | 0.104 | not recorded | not recorded |
| llm-eval-tev1-0.8b:locked | 6/6 | 6/6 | 0.017 | not recorded | not recorded |
| llm-eval-tev1:locked | 6/6 | 6/6 | 0.0311 | not recorded | not recorded |

Paired wall-time differences use llm-eval-clef-flash:locked as the alphabetically first reference. For each identical prompt, subtract the reference median from the other model’s median. The range spans the observed prompts. Negative values mean a shorter wait.

| Model package | Paired prompts | Median difference (s) | Observed range (s) |
|---|---:|---:|---:|
| llm-eval-clef:locked | 2 | 0.355 | 0.269–0.441 |
| llm-eval-d1-omni:locked | 2 | -0.0291 | -0.0333–-0.0249 |
| llm-eval-d1:locked | 2 | -0.0318 | -0.0338–-0.0299 |
| llm-eval-laya:locked | 2 | -0.0301 | -0.037–-0.0232 |
| llm-eval-nimble-v3:locked | 2 | 0.000193 | -0.000834–0.00122 |
| llm-eval-nimble:locked | 2 | 0.00767 | 0.00502–0.0103 |
| llm-eval-pplx-decider:locked | 2 | 0.0555 | 0.052–0.059 |
| llm-eval-tev1-0.8b:locked | 2 | -0.0267 | -0.0287–-0.0247 |
| llm-eval-tev1:locked | 2 | -0.0126 | -0.014–-0.0112 |

## Reproduce a run

Choose a dated report in the table. The manifest pins the code revision. Config records the planned job, input hashes and launch settings. CSV contains category summaries. Raw contains the published measurements. Some older bundles omit artifacts or runtime details. Local paths have been removed.

[Read the reproduction recipe](../../../../REPRODUCE.md) · [Download the comparison manifest](decision-models.json).

For the newest listed job (ollama-clef-flash) run this from the repository root.

```sh
llm-eval result-inputs --input docs/results/decision-models/campaign-20261124T224634Z-f70bba1c-routing-decision-models-1 --job routing-decision-models-1-0701e943af0c
```

## Run history

One row per published job, newest first. A completed request can still fail its check. Output-cap and reload conditions can differ between rows. Use a matched group for a controlled comparison. Projection rows count candidate settings. Legal jobs expose aggregate evidence by cohort.

| Date | Model / runtime | Mode and status | Actual workload | Completed | Checks passed | Median wall s | First visible text s | Backend decode tok/s | Evidence |
|---|---|---|---|---:|---:|---:|---:|---:|---|
| 2026-11-24 | llm-eval-clef-flash:locked · ollama | decision · succeeded | 2 tasks × 3 measured attempts | 6/6 | 6/6 | 0.0453 | not recorded | not recorded | [Report](../../../decision-models/campaign-20261124T224634Z-f70bba1c-routing-decision-models-1/README.md) · [Config](../../../decision-models/campaign-20261124T224634Z-f70bba1c-routing-decision-models-1/resolved-config.json) · [Manifest](../../../decision-models/campaign-20261124T224634Z-f70bba1c-routing-decision-models-1/manifest.json) · [CSV](../../../decision-models/campaign-20261124T224634Z-f70bba1c-routing-decision-models-1/summary.csv) · [Raw](../../../decision-models/campaign-20261124T224634Z-f70bba1c-routing-decision-models-1/raw/measurements.jsonl.gz) |
| 2026-11-24 | llm-eval-clef:locked · ollama | decision · succeeded | 2 tasks × 3 measured attempts | 6/6 | 6/6 | 0.441 | not recorded | not recorded | [Report](../../../decision-models/campaign-20261124T224634Z-f70bba1c-routing-decision-models-1/README.md) · [Config](../../../decision-models/campaign-20261124T224634Z-f70bba1c-routing-decision-models-1/resolved-config.json) · [Manifest](../../../decision-models/campaign-20261124T224634Z-f70bba1c-routing-decision-models-1/manifest.json) · [CSV](../../../decision-models/campaign-20261124T224634Z-f70bba1c-routing-decision-models-1/summary.csv) · [Raw](../../../decision-models/campaign-20261124T224634Z-f70bba1c-routing-decision-models-1/raw/measurements.jsonl.gz) |
| 2026-11-24 | llm-eval-d1-omni:locked · ollama | decision · succeeded | 2 tasks × 3 measured attempts | 6/6 | 6/6 | 0.0131 | not recorded | not recorded | [Report](../../../decision-models/campaign-20261124T224634Z-f70bba1c-routing-decision-models-1/README.md) · [Config](../../../decision-models/campaign-20261124T224634Z-f70bba1c-routing-decision-models-1/resolved-config.json) · [Manifest](../../../decision-models/campaign-20261124T224634Z-f70bba1c-routing-decision-models-1/manifest.json) · [CSV](../../../decision-models/campaign-20261124T224634Z-f70bba1c-routing-decision-models-1/summary.csv) · [Raw](../../../decision-models/campaign-20261124T224634Z-f70bba1c-routing-decision-models-1/raw/measurements.jsonl.gz) |
| 2026-11-24 | llm-eval-d1:locked · ollama | decision · succeeded | 2 tasks × 3 measured attempts | 6/6 | 6/6 | 0.0119 | not recorded | not recorded | [Report](../../../decision-models/campaign-20261124T224634Z-f70bba1c-routing-decision-models-1/README.md) · [Config](../../../decision-models/campaign-20261124T224634Z-f70bba1c-routing-decision-models-1/resolved-config.json) · [Manifest](../../../decision-models/campaign-20261124T224634Z-f70bba1c-routing-decision-models-1/manifest.json) · [CSV](../../../decision-models/campaign-20261124T224634Z-f70bba1c-routing-decision-models-1/summary.csv) · [Raw](../../../decision-models/campaign-20261124T224634Z-f70bba1c-routing-decision-models-1/raw/measurements.jsonl.gz) |
| 2026-11-24 | llm-eval-laya:locked · ollama | decision · succeeded | 2 tasks × 3 measured attempts | 6/6 | 6/6 | 0.0179 | not recorded | not recorded | [Report](../../../decision-models/campaign-20261124T224634Z-f70bba1c-routing-decision-models-1/README.md) · [Config](../../../decision-models/campaign-20261124T224634Z-f70bba1c-routing-decision-models-1/resolved-config.json) · [Manifest](../../../decision-models/campaign-20261124T224634Z-f70bba1c-routing-decision-models-1/manifest.json) · [CSV](../../../decision-models/campaign-20261124T224634Z-f70bba1c-routing-decision-models-1/summary.csv) · [Raw](../../../decision-models/campaign-20261124T224634Z-f70bba1c-routing-decision-models-1/raw/measurements.jsonl.gz) |
| 2026-11-24 | llm-eval-nimble-v3:locked · ollama | decision · succeeded | 2 tasks × 3 measured attempts | 6/6 | 6/6 | 0.0442 | not recorded | not recorded | [Report](../../../decision-models/campaign-20261124T224634Z-f70bba1c-routing-decision-models-1/README.md) · [Config](../../../decision-models/campaign-20261124T224634Z-f70bba1c-routing-decision-models-1/resolved-config.json) · [Manifest](../../../decision-models/campaign-20261124T224634Z-f70bba1c-routing-decision-models-1/manifest.json) · [CSV](../../../decision-models/campaign-20261124T224634Z-f70bba1c-routing-decision-models-1/summary.csv) · [Raw](../../../decision-models/campaign-20261124T224634Z-f70bba1c-routing-decision-models-1/raw/measurements.jsonl.gz) |
| 2026-11-24 | llm-eval-nimble:locked · ollama | decision · succeeded | 2 tasks × 3 measured attempts | 6/6 | 6/6 | 0.0514 | not recorded | not recorded | [Report](../../../decision-models/campaign-20261124T224634Z-f70bba1c-routing-decision-models-1/README.md) · [Config](../../../decision-models/campaign-20261124T224634Z-f70bba1c-routing-decision-models-1/resolved-config.json) · [Manifest](../../../decision-models/campaign-20261124T224634Z-f70bba1c-routing-decision-models-1/manifest.json) · [CSV](../../../decision-models/campaign-20261124T224634Z-f70bba1c-routing-decision-models-1/summary.csv) · [Raw](../../../decision-models/campaign-20261124T224634Z-f70bba1c-routing-decision-models-1/raw/measurements.jsonl.gz) |
| 2026-11-24 | llm-eval-pplx-decider:locked · ollama | decision · succeeded | 2 tasks × 3 measured attempts | 6/6 | 6/6 | 0.104 | not recorded | not recorded | [Report](../../../decision-models/campaign-20261124T224634Z-f70bba1c-routing-decision-models-1/README.md) · [Config](../../../decision-models/campaign-20261124T224634Z-f70bba1c-routing-decision-models-1/resolved-config.json) · [Manifest](../../../decision-models/campaign-20261124T224634Z-f70bba1c-routing-decision-models-1/manifest.json) · [CSV](../../../decision-models/campaign-20261124T224634Z-f70bba1c-routing-decision-models-1/summary.csv) · [Raw](../../../decision-models/campaign-20261124T224634Z-f70bba1c-routing-decision-models-1/raw/measurements.jsonl.gz) |
| 2026-11-24 | llm-eval-tev1-0.8b:locked · ollama | decision · succeeded | 2 tasks × 3 measured attempts | 6/6 | 6/6 | 0.017 | not recorded | not recorded | [Report](../../../decision-models/campaign-20261124T224634Z-f70bba1c-routing-decision-models-1/README.md) · [Config](../../../decision-models/campaign-20261124T224634Z-f70bba1c-routing-decision-models-1/resolved-config.json) · [Manifest](../../../decision-models/campaign-20261124T224634Z-f70bba1c-routing-decision-models-1/manifest.json) · [CSV](../../../decision-models/campaign-20261124T224634Z-f70bba1c-routing-decision-models-1/summary.csv) · [Raw](../../../decision-models/campaign-20261124T224634Z-f70bba1c-routing-decision-models-1/raw/measurements.jsonl.gz) |
| 2026-11-24 | llm-eval-tev1:locked · ollama | decision · succeeded | 2 tasks × 3 measured attempts | 6/6 | 6/6 | 0.0311 | not recorded | not recorded | [Report](../../../decision-models/campaign-20261124T224634Z-f70bba1c-routing-decision-models-1/README.md) · [Config](../../../decision-models/campaign-20261124T224634Z-f70bba1c-routing-decision-models-1/resolved-config.json) · [Manifest](../../../decision-models/campaign-20261124T224634Z-f70bba1c-routing-decision-models-1/manifest.json) · [CSV](../../../decision-models/campaign-20261124T224634Z-f70bba1c-routing-decision-models-1/summary.csv) · [Raw](../../../decision-models/campaign-20261124T224634Z-f70bba1c-routing-decision-models-1/raw/measurements.jsonl.gz) |
| 2026-11-24 | llm-eval-clef-flash:locked · ollama | decision · succeeded | 2 tasks × 3 measured attempts | 6/6 | 6/6 | 0.0554 | not recorded | not recorded | [Report](../../../decision-models/campaign-20261124T224117Z-ce08f5a6-routing-decision-models-1/README.md) · [Config](../../../decision-models/campaign-20261124T224117Z-ce08f5a6-routing-decision-models-1/resolved-config.json) · [Manifest](../../../decision-models/campaign-20261124T224117Z-ce08f5a6-routing-decision-models-1/manifest.json) · [CSV](../../../decision-models/campaign-20261124T224117Z-ce08f5a6-routing-decision-models-1/summary.csv) · [Raw](../../../decision-models/campaign-20261124T224117Z-ce08f5a6-routing-decision-models-1/raw/measurements.jsonl.gz) |
| 2026-11-24 | llm-eval-clef:locked · ollama | decision · succeeded | 2 tasks × 3 measured attempts | 6/6 | 6/6 | 0.534 | not recorded | not recorded | [Report](../../../decision-models/campaign-20261124T224117Z-ce08f5a6-routing-decision-models-1/README.md) · [Config](../../../decision-models/campaign-20261124T224117Z-ce08f5a6-routing-decision-models-1/resolved-config.json) · [Manifest](../../../decision-models/campaign-20261124T224117Z-ce08f5a6-routing-decision-models-1/manifest.json) · [CSV](../../../decision-models/campaign-20261124T224117Z-ce08f5a6-routing-decision-models-1/summary.csv) · [Raw](../../../decision-models/campaign-20261124T224117Z-ce08f5a6-routing-decision-models-1/raw/measurements.jsonl.gz) |
| 2026-11-24 | llm-eval-d1-omni:locked · ollama | decision · succeeded | 2 tasks × 3 measured attempts | 6/6 | 6/6 | 0.0379 | not recorded | not recorded | [Report](../../../decision-models/campaign-20261124T224117Z-ce08f5a6-routing-decision-models-1/README.md) · [Config](../../../decision-models/campaign-20261124T224117Z-ce08f5a6-routing-decision-models-1/resolved-config.json) · [Manifest](../../../decision-models/campaign-20261124T224117Z-ce08f5a6-routing-decision-models-1/manifest.json) · [CSV](../../../decision-models/campaign-20261124T224117Z-ce08f5a6-routing-decision-models-1/summary.csv) · [Raw](../../../decision-models/campaign-20261124T224117Z-ce08f5a6-routing-decision-models-1/raw/measurements.jsonl.gz) |
| 2026-11-24 | llm-eval-d1:locked · ollama | decision · succeeded | 2 tasks × 3 measured attempts | 6/6 | 6/6 | 0.0177 | not recorded | not recorded | [Report](../../../decision-models/campaign-20261124T224117Z-ce08f5a6-routing-decision-models-1/README.md) · [Config](../../../decision-models/campaign-20261124T224117Z-ce08f5a6-routing-decision-models-1/resolved-config.json) · [Manifest](../../../decision-models/campaign-20261124T224117Z-ce08f5a6-routing-decision-models-1/manifest.json) · [CSV](../../../decision-models/campaign-20261124T224117Z-ce08f5a6-routing-decision-models-1/summary.csv) · [Raw](../../../decision-models/campaign-20261124T224117Z-ce08f5a6-routing-decision-models-1/raw/measurements.jsonl.gz) |
| 2026-11-24 | llm-eval-laya:locked · ollama | decision · succeeded | 2 tasks × 3 measured attempts | 6/6 | 6/6 | 0.0141 | not recorded | not recorded | [Report](../../../decision-models/campaign-20261124T224117Z-ce08f5a6-routing-decision-models-1/README.md) · [Config](../../../decision-models/campaign-20261124T224117Z-ce08f5a6-routing-decision-models-1/resolved-config.json) · [Manifest](../../../decision-models/campaign-20261124T224117Z-ce08f5a6-routing-decision-models-1/manifest.json) · [CSV](../../../decision-models/campaign-20261124T224117Z-ce08f5a6-routing-decision-models-1/summary.csv) · [Raw](../../../decision-models/campaign-20261124T224117Z-ce08f5a6-routing-decision-models-1/raw/measurements.jsonl.gz) |
| 2026-11-24 | llm-eval-nimble-v3:locked · ollama | decision · succeeded | 2 tasks × 3 measured attempts | 6/6 | 6/6 | 0.055 | not recorded | not recorded | [Report](../../../decision-models/campaign-20261124T224117Z-ce08f5a6-routing-decision-models-1/README.md) · [Config](../../../decision-models/campaign-20261124T224117Z-ce08f5a6-routing-decision-models-1/resolved-config.json) · [Manifest](../../../decision-models/campaign-20261124T224117Z-ce08f5a6-routing-decision-models-1/manifest.json) · [CSV](../../../decision-models/campaign-20261124T224117Z-ce08f5a6-routing-decision-models-1/summary.csv) · [Raw](../../../decision-models/campaign-20261124T224117Z-ce08f5a6-routing-decision-models-1/raw/measurements.jsonl.gz) |
| 2026-11-24 | llm-eval-nimble:locked · ollama | decision · succeeded | 2 tasks × 3 measured attempts | 6/6 | 6/6 | 0.0519 | not recorded | not recorded | [Report](../../../decision-models/campaign-20261124T224117Z-ce08f5a6-routing-decision-models-1/README.md) · [Config](../../../decision-models/campaign-20261124T224117Z-ce08f5a6-routing-decision-models-1/resolved-config.json) · [Manifest](../../../decision-models/campaign-20261124T224117Z-ce08f5a6-routing-decision-models-1/manifest.json) · [CSV](../../../decision-models/campaign-20261124T224117Z-ce08f5a6-routing-decision-models-1/summary.csv) · [Raw](../../../decision-models/campaign-20261124T224117Z-ce08f5a6-routing-decision-models-1/raw/measurements.jsonl.gz) |
| 2026-11-24 | llm-eval-pplx-decider:locked · ollama | decision · succeeded | 2 tasks × 3 measured attempts | 6/6 | 6/6 | 0.103 | not recorded | not recorded | [Report](../../../decision-models/campaign-20261124T224117Z-ce08f5a6-routing-decision-models-1/README.md) · [Config](../../../decision-models/campaign-20261124T224117Z-ce08f5a6-routing-decision-models-1/resolved-config.json) · [Manifest](../../../decision-models/campaign-20261124T224117Z-ce08f5a6-routing-decision-models-1/manifest.json) · [CSV](../../../decision-models/campaign-20261124T224117Z-ce08f5a6-routing-decision-models-1/summary.csv) · [Raw](../../../decision-models/campaign-20261124T224117Z-ce08f5a6-routing-decision-models-1/raw/measurements.jsonl.gz) |
| 2026-11-24 | llm-eval-tev1-0.8b:locked · ollama | decision · succeeded | 2 tasks × 3 measured attempts | 6/6 | 6/6 | 0.0147 | not recorded | not recorded | [Report](../../../decision-models/campaign-20261124T224117Z-ce08f5a6-routing-decision-models-1/README.md) · [Config](../../../decision-models/campaign-20261124T224117Z-ce08f5a6-routing-decision-models-1/resolved-config.json) · [Manifest](../../../decision-models/campaign-20261124T224117Z-ce08f5a6-routing-decision-models-1/manifest.json) · [CSV](../../../decision-models/campaign-20261124T224117Z-ce08f5a6-routing-decision-models-1/summary.csv) · [Raw](../../../decision-models/campaign-20261124T224117Z-ce08f5a6-routing-decision-models-1/raw/measurements.jsonl.gz) |
| 2026-11-24 | llm-eval-tev1:locked · ollama | decision · succeeded | 2 tasks × 3 measured attempts | 6/6 | 6/6 | 0.0265 | not recorded | not recorded | [Report](../../../decision-models/campaign-20261124T224117Z-ce08f5a6-routing-decision-models-1/README.md) · [Config](../../../decision-models/campaign-20261124T224117Z-ce08f5a6-routing-decision-models-1/resolved-config.json) · [Manifest](../../../decision-models/campaign-20261124T224117Z-ce08f5a6-routing-decision-models-1/manifest.json) · [CSV](../../../decision-models/campaign-20261124T224117Z-ce08f5a6-routing-decision-models-1/summary.csv) · [Raw](../../../decision-models/campaign-20261124T224117Z-ce08f5a6-routing-decision-models-1/raw/measurements.jsonl.gz) |
| 2026-11-18 | llm-eval-nimble:locked · ollama | decision · succeeded | 2 tasks × 3 measured attempts | 6/6 | 6/6 | 0.0526 | not recorded | not recorded | [Report](../../../llm-routing/campaign-20261118T051019Z-d72bad77-routing-llm-routing-1/README.md) · [Config](../../../llm-routing/campaign-20261118T051019Z-d72bad77-routing-llm-routing-1/resolved-config.json) · [Manifest](../../../llm-routing/campaign-20261118T051019Z-d72bad77-routing-llm-routing-1/manifest.json) · [CSV](../../../llm-routing/campaign-20261118T051019Z-d72bad77-routing-llm-routing-1/summary.csv) · [Raw](../../../llm-routing/campaign-20261118T051019Z-d72bad77-routing-llm-routing-1/raw/measurements.jsonl.gz) |
| 2026-11-18 | llm-eval-tev1:locked · ollama | decision · succeeded | 2 tasks × 3 measured attempts | 6/6 | 6/6 | 0.0249 | not recorded | not recorded | [Report](../../../llm-routing/campaign-20261118T051019Z-d72bad77-routing-llm-routing-1/README.md) · [Config](../../../llm-routing/campaign-20261118T051019Z-d72bad77-routing-llm-routing-1/resolved-config.json) · [Manifest](../../../llm-routing/campaign-20261118T051019Z-d72bad77-routing-llm-routing-1/manifest.json) · [CSV](../../../llm-routing/campaign-20261118T051019Z-d72bad77-routing-llm-routing-1/summary.csv) · [Raw](../../../llm-routing/campaign-20261118T051019Z-d72bad77-routing-llm-routing-1/raw/measurements.jsonl.gz) |
