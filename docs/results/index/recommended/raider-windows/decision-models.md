# Recommended setup, harness and model: decision-models on raider-windows

[Recommended setups](../README.md) · [Results index](../../README.md) · [Executive summary](../../../README.md)

Generated from the published bundles by `llm-eval index-results`; do not edit by hand. 4 published result(s) for this experiment and hardware configuration; 2 harness and model combination(s) are ranked.

## Recommendation

| | |
|---|---|
| Harness | [ollama](../../harness/ollama.md) |
| Model | [llm-eval-tev1:locked](../../model/llm-eval-tev1-locked.md) |
| Operating system | windows-11-native |
| Checks passed | 6/6 |
| Median wall time per request (s) | 0.0367 |
| Output tokens per second | – |
| Measured | [2026-11-15](../../../llm-routing/campaign-20261115T130420Z-a4e6c761-routing-llm-routing-1/README.md) |

This is the best-ranked combination of the results index for this pair. Ranked by share of checks passed (correct decisions for decision models, quality checks otherwise), then lower median wall time per request, then higher output tokens per second. Each harness and model combination is represented by its newest measured run that succeeded; synthetic fixtures, failed runs and runs without scored checks are not ranked. Wall time and token rate are the median of the category medians. Where a model repeats among the best combinations, a second table ranks the models, each by its best combination.

2 combinations pass the same share of checks as the recommended one; the order among them is by median wall time, then by output rate.

It is a statement about the published runs on this hardware configuration, not about the model or the harness in general. The checks are small deterministic checks, the runs can differ in more than the harness and the model (each report states its conditions), and the recommendation changes when a newer run of a combination is published.

## Setup of the recommended run

Read from the resolved configuration of the run's report. To reproduce it, use the measured code revision named in that report.

| Setting | Value |
|---|---|
| Router instructions | Choose the category that best describes the user request. |
| Router kind | systemone |
| Router model | llm-eval-tev1:locked |
| Router model_revision | 7954dce22bc6c29c3b119656207681d12cb34434fed7caa086bfbc919bef0740 |
| Router platform | ollama |
| Router timeout_s | 300 |

## Best 2 combinations

| Rank | Harness | Model | Checks passed | Median wall s | Output tok/s | Run |
|---:|---|---|---:|---:|---:|---|
| 1 | [ollama](../../harness/ollama.md) | [llm-eval-tev1:locked](../../model/llm-eval-tev1-locked.md) | 6/6 | 0.0367 | – | [2026-11-15](../../../llm-routing/campaign-20261115T130420Z-a4e6c761-routing-llm-routing-1/README.md) |
| 2 | [ollama](../../harness/ollama.md) | [llm-eval-nimble:locked](../../model/llm-eval-nimble-locked.md) | 6/6 | 0.0602 | – | [2026-11-15](../../../llm-routing/campaign-20261115T130420Z-a4e6c761-routing-llm-routing-1/README.md) |

## Published results of this pair

| Date | Experiment | Hardware | Harness | Model | Case | Output cap | Status | Requests | Errors | Median wall s | Output tok/s | Quality | Decisions | Report |
|---|---|---|---|---|---|---:|---|---:|---:|---:|---:|---:|---:|---|
| [2026-11-15](../../date/2026-11-15.md) | [decision-models](../../experiment/decision-models.md) | [raider-windows](../../hardware/raider-windows.md) | [ollama](../../harness/ollama.md) | [llm-eval-nimble:locked](../../model/llm-eval-nimble-locked.md) | ollama-nimble | – | succeeded | 6 | 0 | 0.0594–0.061 | – | – | 6/6 | [report](../../../llm-routing/campaign-20261115T130420Z-a4e6c761-routing-llm-routing-1/README.md) |
| [2026-11-15](../../date/2026-11-15.md) | [decision-models](../../experiment/decision-models.md) | [raider-windows](../../hardware/raider-windows.md) | [ollama](../../harness/ollama.md) | [llm-eval-tev1:locked](../../model/llm-eval-tev1-locked.md) | ollama-tev1 | – | succeeded | 6 | 0 | 0.0287–0.0446 | – | – | 6/6 | [report](../../../llm-routing/campaign-20261115T130420Z-a4e6c761-routing-llm-routing-1/README.md) |
| [2026-11-08](../../date/2026-11-08.md) | [decision-models](../../experiment/decision-models.md) | [raider-windows](../../hardware/raider-windows.md) | [ollama](../../harness/ollama.md) | [llm-eval-nimble:locked](../../model/llm-eval-nimble-locked.md) | ollama-nimble | – | succeeded | 6 | 0 | 0.0495–0.0497 | – | – | 6/6 | [report](../../../llm-routing/campaign-20261108T035738Z-332b0246-routing-llm-routing-1/README.md) |
| [2026-11-08](../../date/2026-11-08.md) | [decision-models](../../experiment/decision-models.md) | [raider-windows](../../hardware/raider-windows.md) | [ollama](../../harness/ollama.md) | [llm-eval-tev1:locked](../../model/llm-eval-tev1-locked.md) | ollama-tev1 | – | succeeded | 6 | 0 | 0.0274–0.0291 | – | – | 6/6 | [report](../../../llm-routing/campaign-20261108T035738Z-332b0246-routing-llm-routing-1/README.md) |
