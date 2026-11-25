# legal-models on raider-wsl

[Setup evidence](../README.md) · [Results index](../../README.md)

## Legal evaluation

The unit is a fictional matter within one arm. Rates and denominators come from the public cohort summaries. Each stage has its own eligible matters. A missing review has no reviewed score.

| Run / class | Arm | Exact-version recall (mean, n) | Citations resolve (rate, n) | All deterministic checks (rate, n) | Human-reviewed all-pass (rate, n) |
|---|---|---|---|---|---|
| 2026-11-18 score (score-only) | lexical-eligible | 1, n=14 | 0, n=16 | 0, n=16 | pending, n=0 |
| 2026-11-18 score (score-only) | no-context | 0, n=14 | 0, n=16 | 0, n=16 | pending, n=0 |
| 2026-11-18 retrieval (fixture) | filters-only | 1, n=14 | unavailable | unavailable | unavailable |
| 2026-11-18 retrieval (fixture) | lexical | 1, n=14 | unavailable | unavailable | unavailable |
| 2026-11-18 retrieval (fixture) | lexical-eligible | 1, n=14 | unavailable | unavailable | unavailable |
| 2026-11-18 retrieval (fixture) | no-context | 0, n=14 | unavailable | unavailable | unavailable |
| 2026-11-18 generation (measured) | lexical-eligible | 1, n=14 | 0, n=16 | 0, n=16 | pending, n=0 |
| 2026-11-18 generation (measured) | no-context | 0, n=14 | 0, n=16 | 0, n=16 | pending, n=0 |
| 2026-11-18 workflow (measured) | lexical-eligible | 1, n=14 | 0, n=16 | 0, n=16 | pending, n=0 |
| 2026-11-18 workflow (measured) | no-context | 0, n=14 | 0, n=16 | 0, n=16 | pending, n=0 |

## Reproduce a run

Choose a dated report in the table. The manifest pins the code revision. Config records the planned job, input hashes and launch settings. CSV contains category summaries. Raw contains the published measurements. Some older bundles omit artifacts or runtime details. Local paths have been removed.

[Read the reproduction recipe](../../../../REPRODUCE.md) · [Download the comparison manifest](legal-models.json).

For the newest listed job (legal-score) run this from the repository root.

```sh
llm-eval result-inputs --input docs/results/legal-benchmark/campaign-20261118T071704Z-9ee36cc3-score-legal-benchmark-1 --job score-legal-benchmark-1-ff60ca399ae0
```

## Run history

One row per published job, newest first. A completed request can still fail its check. Output-cap and reload conditions can differ between rows. Use a matched group for a controlled comparison. Projection rows count candidate settings. Legal jobs expose aggregate evidence by cohort.

| Date | Model / runtime | Mode and status | Actual workload | Completed | Checks passed | Median wall s | First visible text s | Backend decode tok/s | Evidence |
|---|---|---|---|---:|---:|---:|---:|---:|---|
| 2026-11-18 | llm-eval-kimi-linear-48b:locked · ollama | score-only · succeeded | 16 fictional matters | not recorded | 0/32 | not recorded | not recorded | not recorded | [Report](../../../legal-benchmark/campaign-20261118T071704Z-9ee36cc3-score-legal-benchmark-1/README.md) · [Config](../../../legal-benchmark/campaign-20261118T071704Z-9ee36cc3-score-legal-benchmark-1/resolved-config.json) · [Manifest](../../../legal-benchmark/campaign-20261118T071704Z-9ee36cc3-score-legal-benchmark-1/manifest.json) · [CSV](../../../legal-benchmark/campaign-20261118T071704Z-9ee36cc3-score-legal-benchmark-1/summary.csv) · [Raw](../../../legal-benchmark/campaign-20261118T071704Z-9ee36cc3-score-legal-benchmark-1/raw/measurements.jsonl.gz) · [Cohorts](../../../legal-benchmark/campaign-20261118T071704Z-9ee36cc3-score-legal-benchmark-1/legal-summary.json) |
| 2026-11-18 | fixture · fixture | fixture · succeeded | 16 fictional matters | not recorded | 39/56 | not recorded | not recorded | not recorded | [Report](../../../legal-benchmark/campaign-20261118T064854Z-6746b621-retrieval-legal-benchmark-1/README.md) · [Config](../../../legal-benchmark/campaign-20261118T064854Z-6746b621-retrieval-legal-benchmark-1/resolved-config.json) · [Manifest](../../../legal-benchmark/campaign-20261118T064854Z-6746b621-retrieval-legal-benchmark-1/manifest.json) · [CSV](../../../legal-benchmark/campaign-20261118T064854Z-6746b621-retrieval-legal-benchmark-1/summary.csv) · [Raw](../../../legal-benchmark/campaign-20261118T064854Z-6746b621-retrieval-legal-benchmark-1/raw/measurements.jsonl.gz) · [Cohorts](../../../legal-benchmark/campaign-20261118T064854Z-6746b621-retrieval-legal-benchmark-1/legal-summary.json) |
| 2026-11-18 | llm-eval-kimi-linear-48b:locked · ollama | measured · succeeded | 16 fictional matters | not recorded | 0/32 | not recorded | not recorded | not recorded | [Report](../../../legal-benchmark/campaign-20261118T064854Z-6746b621-generation-legal-benchmark-1/README.md) · [Config](../../../legal-benchmark/campaign-20261118T064854Z-6746b621-generation-legal-benchmark-1/resolved-config.json) · [Manifest](../../../legal-benchmark/campaign-20261118T064854Z-6746b621-generation-legal-benchmark-1/manifest.json) · [CSV](../../../legal-benchmark/campaign-20261118T064854Z-6746b621-generation-legal-benchmark-1/summary.csv) · [Raw](../../../legal-benchmark/campaign-20261118T064854Z-6746b621-generation-legal-benchmark-1/raw/measurements.jsonl.gz) · [Cohorts](../../../legal-benchmark/campaign-20261118T064854Z-6746b621-generation-legal-benchmark-1/legal-summary.json) |
| 2026-11-18 | llm-eval-kimi-linear-48b:locked · ollama | measured · succeeded | 16 fictional matters | not recorded | 0/32 | not recorded | not recorded | not recorded | [Report](../../../legal-benchmark/campaign-20261118T064854Z-6746b621-workflow-legal-benchmark-1/README.md) · [Config](../../../legal-benchmark/campaign-20261118T064854Z-6746b621-workflow-legal-benchmark-1/resolved-config.json) · [Manifest](../../../legal-benchmark/campaign-20261118T064854Z-6746b621-workflow-legal-benchmark-1/manifest.json) · [CSV](../../../legal-benchmark/campaign-20261118T064854Z-6746b621-workflow-legal-benchmark-1/summary.csv) · [Raw](../../../legal-benchmark/campaign-20261118T064854Z-6746b621-workflow-legal-benchmark-1/raw/measurements.jsonl.gz) · [Cohorts](../../../legal-benchmark/campaign-20261118T064854Z-6746b621-workflow-legal-benchmark-1/legal-summary.json) |
