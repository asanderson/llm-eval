# decision-models on raider-ubuntu

[Setup evidence](../README.md) · [Results index](../../README.md)

These runs exercised a synthetic fixture. A measured model run on this configuration is still open.

## Reproduce a run

Choose a dated report in the table. The manifest pins the code revision. Config records the planned job, input hashes and launch settings. CSV contains category summaries. Raw contains the published measurements. Some older bundles omit artifacts or runtime details. Local paths have been removed.

[Read the reproduction recipe](../../../../REPRODUCE.md) · [Download the comparison manifest](decision-models.json).

For the newest listed job (category-smoke) run this from the repository root.

```sh
llm-eval result-inputs --input docs/results/llm-routing/campaign-20261108T013814Z-7ff2610d-routing-llm-routing-1 --job routing-llm-routing-1-290257f5d5ab
```

## Run history

One row per published job, newest first. A completed request can still fail its check. Output-cap and reload conditions can differ between rows. Use a matched group for a controlled comparison. Projection rows count candidate settings. Legal jobs expose aggregate evidence by cohort.

| Date | Model / runtime | Mode and status | Actual workload | Completed | Checks passed | Median wall s | First visible text s | Backend decode tok/s | Evidence |
|---|---|---|---|---:|---:|---:|---:|---:|---|
| 2026-11-08 | category · category | fixture · succeeded | 2 tasks × 1 measured attempts | 2/2 | 2/2 | 3.39e-05 | not recorded | not recorded | [Report](../../../llm-routing/campaign-20261108T013814Z-7ff2610d-routing-llm-routing-1/README.md) · [Config](../../../llm-routing/campaign-20261108T013814Z-7ff2610d-routing-llm-routing-1/resolved-config.json) · [Manifest](../../../llm-routing/campaign-20261108T013814Z-7ff2610d-routing-llm-routing-1/manifest.json) · [CSV](../../../llm-routing/campaign-20261108T013814Z-7ff2610d-routing-llm-routing-1/summary.csv) · [Raw](../../../llm-routing/campaign-20261108T013814Z-7ff2610d-routing-llm-routing-1/raw/measurements.jsonl.gz) |
