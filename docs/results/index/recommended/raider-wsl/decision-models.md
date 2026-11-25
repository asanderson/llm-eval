# Recommended setup, harness and model: decision-models on raider-wsl

[Recommended setups](../README.md) · [Results index](../../README.md) · [Executive summary](../../../README.md)

Generated from the published bundles by `llm-eval index-results`; do not edit by hand. 22 published result(s) for this experiment and hardware configuration; 10 harness and model combination(s) are ranked.

## Recommendation

| | |
|---|---|
| Harness | [ollama](../../harness/ollama.md) |
| Model | [llm-eval-d1:locked](../../model/llm-eval-d1-locked.md) |
| Operating system | windows-11-wsl2-ubuntu-26.04 |
| Checks passed | 6/6 |
| Median wall time per request (s) | 0.0119 |
| Output tokens per second | – |
| Measured | [2026-11-24](../../../decision-models/campaign-20261124T224634Z-f70bba1c-routing-decision-models-1/README.md) |

This is the best-ranked combination of the results index for this pair. Ranked by share of checks passed (correct decisions for decision models, quality checks otherwise), then lower median wall time per request, then higher output tokens per second. Each harness and model combination is represented by its newest measured run that succeeded; synthetic fixtures, failed runs and runs without scored checks are not ranked. Wall time and token rate are the median of the category medians. Where a model repeats among the best combinations, a second table ranks the models, each by its best combination.

10 combinations pass the same share of checks as the recommended one; the order among them is by median wall time, then by output rate.

It is a statement about the published runs on this hardware configuration, not about the model or the harness in general. The checks are small deterministic checks, the runs can differ in more than the harness and the model (each report states its conditions), and the recommendation changes when a newer run of a combination is published.

## Setup of the recommended run

Read from the resolved configuration of the run's report. To reproduce it, use the measured code revision named in that report.

| Setting | Value |
|---|---|
| Router instructions | Choose the category that best describes the user request. |
| Router kind | systemone |
| Router model | llm-eval-d1:locked |
| Router model_revision | 8c2d9ddae4413c38b183644320b6f4bca4c5f629ae9e5104c3b13a150ed85e7e |
| Router platform | ollama |
| Router timeout_s | 300 |

## Best 5 combinations

| Rank | Harness | Model | Checks passed | Median wall s | Output tok/s | Run |
|---:|---|---|---:|---:|---:|---|
| 1 | [ollama](../../harness/ollama.md) | [llm-eval-d1:locked](../../model/llm-eval-d1-locked.md) | 6/6 | 0.0119 | – | [2026-11-24](../../../decision-models/campaign-20261124T224634Z-f70bba1c-routing-decision-models-1/README.md) |
| 2 | [ollama](../../harness/ollama.md) | [llm-eval-laya:locked](../../model/llm-eval-laya-locked.md) | 6/6 | 0.0136 | – | [2026-11-24](../../../decision-models/campaign-20261124T224634Z-f70bba1c-routing-decision-models-1/README.md) |
| 3 | [ollama](../../harness/ollama.md) | [llm-eval-d1-omni:locked](../../model/llm-eval-d1-omni-locked.md) | 6/6 | 0.0146 | – | [2026-11-24](../../../decision-models/campaign-20261124T224634Z-f70bba1c-routing-decision-models-1/README.md) |
| 4 | [ollama](../../harness/ollama.md) | [llm-eval-tev1-0.8b:locked](../../model/llm-eval-tev1-0.8b-locked.md) | 6/6 | 0.017 | – | [2026-11-24](../../../decision-models/campaign-20261124T224634Z-f70bba1c-routing-decision-models-1/README.md) |
| 5 | [ollama](../../harness/ollama.md) | [llm-eval-tev1:locked](../../model/llm-eval-tev1-locked.md) | 6/6 | 0.0311 | – | [2026-11-24](../../../decision-models/campaign-20261124T224634Z-f70bba1c-routing-decision-models-1/README.md) |

## Published results of this pair

| Date | Experiment | Hardware | Harness | Model | Case | Output cap | Status | Requests | Errors | Median wall s | Output tok/s | Quality | Decisions | Report |
|---|---|---|---|---|---|---:|---|---:|---:|---:|---:|---:|---:|---|
| [2026-11-24](../../date/2026-11-24.md) | [decision-models](../../experiment/decision-models.md) | [raider-wsl](../../hardware/raider-wsl.md) | [ollama](../../harness/ollama.md) | [llm-eval-clef-flash:locked](../../model/llm-eval-clef-flash-locked.md) | ollama-clef-flash | – | succeeded | 6 | 0 | 0.042–0.0454 | – | – | 6/6 | [report](../../../decision-models/campaign-20261124T224634Z-f70bba1c-routing-decision-models-1/README.md) |
| [2026-11-24](../../date/2026-11-24.md) | [decision-models](../../experiment/decision-models.md) | [raider-wsl](../../hardware/raider-wsl.md) | [ollama](../../harness/ollama.md) | [llm-eval-clef:locked](../../model/llm-eval-clef-locked.md) | ollama-clef | – | succeeded | 6 | 0 | 0.314–0.483 | – | – | 6/6 | [report](../../../decision-models/campaign-20261124T224634Z-f70bba1c-routing-decision-models-1/README.md) |
| [2026-11-24](../../date/2026-11-24.md) | [decision-models](../../experiment/decision-models.md) | [raider-wsl](../../hardware/raider-wsl.md) | [ollama](../../harness/ollama.md) | [llm-eval-d1-omni:locked](../../model/llm-eval-d1-omni-locked.md) | ollama-d1-omni | – | succeeded | 6 | 0 | 0.0121–0.0171 | – | – | 6/6 | [report](../../../decision-models/campaign-20261124T224634Z-f70bba1c-routing-decision-models-1/README.md) |
| [2026-11-24](../../date/2026-11-24.md) | [decision-models](../../experiment/decision-models.md) | [raider-wsl](../../hardware/raider-wsl.md) | [ollama](../../harness/ollama.md) | [llm-eval-d1:locked](../../model/llm-eval-d1-locked.md) | ollama-d1 | – | succeeded | 6 | 0 | 0.0117–0.0121 | – | – | 6/6 | [report](../../../decision-models/campaign-20261124T224634Z-f70bba1c-routing-decision-models-1/README.md) |
| [2026-11-24](../../date/2026-11-24.md) | [decision-models](../../experiment/decision-models.md) | [raider-wsl](../../hardware/raider-wsl.md) | [ollama](../../harness/ollama.md) | [llm-eval-laya:locked](../../model/llm-eval-laya-locked.md) | ollama-laya | – | succeeded | 6 | 0 | 0.00842–0.0188 | – | – | 6/6 | [report](../../../decision-models/campaign-20261124T224634Z-f70bba1c-routing-decision-models-1/README.md) |
| [2026-11-24](../../date/2026-11-24.md) | [decision-models](../../experiment/decision-models.md) | [raider-wsl](../../hardware/raider-wsl.md) | [ollama](../../harness/ollama.md) | [llm-eval-nimble-v3:locked](../../model/llm-eval-nimble-v3-locked.md) | ollama-nimble-v3 | – | succeeded | 6 | 0 | 0.0432–0.0446 | – | – | 6/6 | [report](../../../decision-models/campaign-20261124T224634Z-f70bba1c-routing-decision-models-1/README.md) |
| [2026-11-24](../../date/2026-11-24.md) | [decision-models](../../experiment/decision-models.md) | [raider-wsl](../../hardware/raider-wsl.md) | [ollama](../../harness/ollama.md) | [llm-eval-nimble:locked](../../model/llm-eval-nimble-locked.md) | ollama-nimble | – | succeeded | 6 | 0 | 0.0505–0.0523 | – | – | 6/6 | [report](../../../decision-models/campaign-20261124T224634Z-f70bba1c-routing-decision-models-1/README.md) |
| [2026-11-24](../../date/2026-11-24.md) | [decision-models](../../experiment/decision-models.md) | [raider-wsl](../../hardware/raider-wsl.md) | [ollama](../../harness/ollama.md) | [llm-eval-pplx-decider:locked](../../model/llm-eval-pplx-decider-locked.md) | ollama-pplx-decider | – | succeeded | 6 | 0 | 0.094–0.104 | – | – | 6/6 | [report](../../../decision-models/campaign-20261124T224634Z-f70bba1c-routing-decision-models-1/README.md) |
| [2026-11-24](../../date/2026-11-24.md) | [decision-models](../../experiment/decision-models.md) | [raider-wsl](../../hardware/raider-wsl.md) | [ollama](../../harness/ollama.md) | [llm-eval-tev1-0.8b:locked](../../model/llm-eval-tev1-0.8b-locked.md) | ollama-tev1-0.8b | – | succeeded | 6 | 0 | 0.0168–0.0173 | – | – | 6/6 | [report](../../../decision-models/campaign-20261124T224634Z-f70bba1c-routing-decision-models-1/README.md) |
| [2026-11-24](../../date/2026-11-24.md) | [decision-models](../../experiment/decision-models.md) | [raider-wsl](../../hardware/raider-wsl.md) | [ollama](../../harness/ollama.md) | [llm-eval-tev1:locked](../../model/llm-eval-tev1-locked.md) | ollama-tev1 | – | succeeded | 6 | 0 | 0.0308–0.0315 | – | – | 6/6 | [report](../../../decision-models/campaign-20261124T224634Z-f70bba1c-routing-decision-models-1/README.md) |
| [2026-11-24](../../date/2026-11-24.md) | [decision-models](../../experiment/decision-models.md) | [raider-wsl](../../hardware/raider-wsl.md) | [ollama](../../harness/ollama.md) | [llm-eval-clef-flash:locked](../../model/llm-eval-clef-flash-locked.md) | ollama-clef-flash | – | succeeded | 6 | 0 | 0.0542–0.0557 | – | – | 6/6 | [report](../../../decision-models/campaign-20261124T224117Z-ce08f5a6-routing-decision-models-1/README.md) |
| [2026-11-24](../../date/2026-11-24.md) | [decision-models](../../experiment/decision-models.md) | [raider-wsl](../../hardware/raider-wsl.md) | [ollama](../../harness/ollama.md) | [llm-eval-clef:locked](../../model/llm-eval-clef-locked.md) | ollama-clef | – | succeeded | 6 | 0 | 0.504–0.566 | – | – | 6/6 | [report](../../../decision-models/campaign-20261124T224117Z-ce08f5a6-routing-decision-models-1/README.md) |
| [2026-11-24](../../date/2026-11-24.md) | [decision-models](../../experiment/decision-models.md) | [raider-wsl](../../hardware/raider-wsl.md) | [ollama](../../harness/ollama.md) | [llm-eval-d1-omni:locked](../../model/llm-eval-d1-omni-locked.md) | ollama-d1-omni | – | succeeded | 6 | 0 | 0.0345–0.0398 | – | – | 6/6 | [report](../../../decision-models/campaign-20261124T224117Z-ce08f5a6-routing-decision-models-1/README.md) |
| [2026-11-24](../../date/2026-11-24.md) | [decision-models](../../experiment/decision-models.md) | [raider-wsl](../../hardware/raider-wsl.md) | [ollama](../../harness/ollama.md) | [llm-eval-d1:locked](../../model/llm-eval-d1-locked.md) | ollama-d1 | – | succeeded | 6 | 0 | 0.014–0.0192 | – | – | 6/6 | [report](../../../decision-models/campaign-20261124T224117Z-ce08f5a6-routing-decision-models-1/README.md) |
| [2026-11-24](../../date/2026-11-24.md) | [decision-models](../../experiment/decision-models.md) | [raider-wsl](../../hardware/raider-wsl.md) | [ollama](../../harness/ollama.md) | [llm-eval-laya:locked](../../model/llm-eval-laya-locked.md) | ollama-laya | – | succeeded | 6 | 0 | 0.0138–0.0145 | – | – | 6/6 | [report](../../../decision-models/campaign-20261124T224117Z-ce08f5a6-routing-decision-models-1/README.md) |
| [2026-11-24](../../date/2026-11-24.md) | [decision-models](../../experiment/decision-models.md) | [raider-wsl](../../hardware/raider-wsl.md) | [ollama](../../harness/ollama.md) | [llm-eval-nimble-v3:locked](../../model/llm-eval-nimble-v3-locked.md) | ollama-nimble-v3 | – | succeeded | 6 | 0 | 0.055–0.0552 | – | – | 6/6 | [report](../../../decision-models/campaign-20261124T224117Z-ce08f5a6-routing-decision-models-1/README.md) |
| [2026-11-24](../../date/2026-11-24.md) | [decision-models](../../experiment/decision-models.md) | [raider-wsl](../../hardware/raider-wsl.md) | [ollama](../../harness/ollama.md) | [llm-eval-nimble:locked](../../model/llm-eval-nimble-locked.md) | ollama-nimble | – | succeeded | 6 | 0 | 0.0444–0.0527 | – | – | 6/6 | [report](../../../decision-models/campaign-20261124T224117Z-ce08f5a6-routing-decision-models-1/README.md) |
| [2026-11-24](../../date/2026-11-24.md) | [decision-models](../../experiment/decision-models.md) | [raider-wsl](../../hardware/raider-wsl.md) | [ollama](../../harness/ollama.md) | [llm-eval-pplx-decider:locked](../../model/llm-eval-pplx-decider-locked.md) | ollama-pplx-decider | – | succeeded | 6 | 0 | 0.0896–0.107 | – | – | 6/6 | [report](../../../decision-models/campaign-20261124T224117Z-ce08f5a6-routing-decision-models-1/README.md) |
| [2026-11-24](../../date/2026-11-24.md) | [decision-models](../../experiment/decision-models.md) | [raider-wsl](../../hardware/raider-wsl.md) | [ollama](../../harness/ollama.md) | [llm-eval-tev1-0.8b:locked](../../model/llm-eval-tev1-0.8b-locked.md) | ollama-tev1-0.8b | – | succeeded | 6 | 0 | 0.013–0.0234 | – | – | 6/6 | [report](../../../decision-models/campaign-20261124T224117Z-ce08f5a6-routing-decision-models-1/README.md) |
| [2026-11-24](../../date/2026-11-24.md) | [decision-models](../../experiment/decision-models.md) | [raider-wsl](../../hardware/raider-wsl.md) | [ollama](../../harness/ollama.md) | [llm-eval-tev1:locked](../../model/llm-eval-tev1-locked.md) | ollama-tev1 | – | succeeded | 6 | 0 | 0.0265–0.0281 | – | – | 6/6 | [report](../../../decision-models/campaign-20261124T224117Z-ce08f5a6-routing-decision-models-1/README.md) |
| [2026-11-18](../../date/2026-11-18.md) | [decision-models](../../experiment/decision-models.md) | [raider-wsl](../../hardware/raider-wsl.md) | [ollama](../../harness/ollama.md) | [llm-eval-nimble:locked](../../model/llm-eval-nimble-locked.md) | ollama-nimble | – | succeeded | 6 | 0 | 0.0507–0.0554 | – | – | 6/6 | [report](../../../llm-routing/campaign-20261118T051019Z-d72bad77-routing-llm-routing-1/README.md) |
| [2026-11-18](../../date/2026-11-18.md) | [decision-models](../../experiment/decision-models.md) | [raider-wsl](../../hardware/raider-wsl.md) | [ollama](../../harness/ollama.md) | [llm-eval-tev1:locked](../../model/llm-eval-tev1-locked.md) | ollama-tev1 | – | succeeded | 6 | 0 | 0.0245–0.0261 | – | – | 6/6 | [report](../../../llm-routing/campaign-20261118T051019Z-d72bad77-routing-llm-routing-1/README.md) |
