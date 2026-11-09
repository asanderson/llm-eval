# Results index

Generated from the published bundles by `llm-eval index-results`; do not edit by hand. Ranges are the lowest and highest category medians of a job. Quality and decision counts are passes over applicable checks.

## Navigate

### Top 3 harness and model combinations per experiment and hardware configuration

Ranked by share of checks passed (correct decisions for routing experiments, quality checks otherwise), then lower median wall time per request, then higher output tokens per second. Each harness and model combination is represented by its newest measured run that succeeded; synthetic fixtures, failed runs and runs without scored checks are not ranked. Wall time and token rate are the median of the category medians.

**[llm-routing](experiment/llm-routing.md) on [raider-ubuntu](hardware/raider-ubuntu.md)**

No measured run with scored checks has been published yet.

**[llm-routing](experiment/llm-routing.md) on [raider-windows](hardware/raider-windows.md)**

| Rank | Harness | Model | Checks passed | Median wall s | Output tok/s | Run |
|---:|---|---|---:|---:|---:|---|
| 1 | [ollama](harness/ollama.md) | [llm-eval-tev1:locked](model/llm-eval-tev1-locked.md) | 6/6 | 0.0282 | – | [2026-11-08](../llm-routing/campaign-20261108T035738Z-332b0246-routing-llm-routing-1/README.md) |
| 2 | [ollama](harness/ollama.md) | [llm-eval-nimble:locked](model/llm-eval-nimble-locked.md) | 6/6 | 0.0496 | – | [2026-11-08](../llm-routing/campaign-20261108T035738Z-332b0246-routing-llm-routing-1/README.md) |

**[model-offloading](experiment/model-offloading.md) on [raider-windows](hardware/raider-windows.md)**

| Rank | Harness | Model | Checks passed | Median wall s | Output tok/s | Run |
|---:|---|---|---:|---:|---:|---|
| 1 | [lmstudio](harness/lmstudio.md) | [qwen38-27b](model/qwen38-27b.md) | 24/27 | 7.75 | 6.4 | [2026-11-09 cap 2048](../model-offloading/campaign-20261109T145255Z-9e9ae761-offload-model-offloading-1/README.md) |
| 2 | [ollama](harness/ollama.md) | [qwen38-27b](model/qwen38-27b.md) | 24/27 | 16.8 | 3.56 | [2026-11-09 cap 2048](../model-offloading/campaign-20261109T145255Z-9e9ae761-offload-model-offloading-1/README.md) |
| 3 | [koboldcpp](harness/koboldcpp.md) | [qwen38-27b](model/qwen38-27b.md) | 24/27 | 25 | 3.51 | [2026-11-09 cap 2048](../model-offloading/campaign-20261109T145255Z-9e9ae761-offload-model-offloading-1/README.md) |

### Browse by category

| Category | Indexes (results) |
|---|---|
| Hardware configuration | [raider-ubuntu](hardware/raider-ubuntu.md) (1) · [raider-windows](hardware/raider-windows.md) (11) |
| Experiment | [llm-routing](experiment/llm-routing.md) (3) · [model-offloading](experiment/model-offloading.md) (9) |
| Harness | [category](harness/category.md) (1) · [koboldcpp](harness/koboldcpp.md) (2) · [lmstudio](harness/lmstudio.md) (2) · [ollama](harness/ollama.md) (7) |
| Model | [category](model/category.md) (1) · [deepseek-r1-32b](model/deepseek-r1-32b.md) (6) · [llm-eval-nimble:locked](model/llm-eval-nimble-locked.md) (1) · [llm-eval-tev1:locked](model/llm-eval-tev1-locked.md) (1) · [qwen38-27b](model/qwen38-27b.md) (3) |
| Date (UTC) | [2026-11-09](date/2026-11-09.md) (6) · [2026-11-08](date/2026-11-08.md) (6) |

### llm-routing: models by harness

Each cell links to the report of every published run of that model on that harness, newest first.

| Model | [category](harness/category.md) | [ollama](harness/ollama.md) |
|---|---|---|
| [category](model/category.md) | [2026-11-08 raider-ubuntu synthetic](../llm-routing/campaign-20261108T013814Z-7ff2610d-routing-llm-routing-1/README.md) | – |
| [llm-eval-nimble:locked](model/llm-eval-nimble-locked.md) | – | [2026-11-08 raider-windows](../llm-routing/campaign-20261108T035738Z-332b0246-routing-llm-routing-1/README.md) |
| [llm-eval-tev1:locked](model/llm-eval-tev1-locked.md) | – | [2026-11-08 raider-windows](../llm-routing/campaign-20261108T035738Z-332b0246-routing-llm-routing-1/README.md) |

### model-offloading: models by harness

Each cell links to the report of every published run of that model on that harness, newest first.

| Model | [koboldcpp](harness/koboldcpp.md) | [lmstudio](harness/lmstudio.md) | [ollama](harness/ollama.md) |
|---|---|---|---|
| [deepseek-r1-32b](model/deepseek-r1-32b.md) | [2026-11-09 raider-windows cap 2048](../model-offloading/campaign-20261109T111225Z-8bf20361-offload-model-offloading-1/README.md) | [2026-11-09 raider-windows cap 2048](../model-offloading/campaign-20261109T111225Z-8bf20361-offload-model-offloading-1/README.md) | [2026-11-09 raider-windows cap 2048](../model-offloading/campaign-20261109T111225Z-8bf20361-offload-model-offloading-1/README.md)<br>[2026-11-08 raider-windows cap 2048](../model-offloading/campaign-20261108T140651Z-a0b0cfdf-offload-model-offloading-1/README.md)<br>[2026-11-08 raider-windows cap 256](../model-offloading/campaign-20261108T035738Z-332b0246-offload-model-offloading-1/README.md)<br>[2026-11-08 raider-windows cap 256 failed](../model-offloading/campaign-20261108T035331Z-833eafe8-offload-model-offloading-1/README.md) |
| [qwen38-27b](model/qwen38-27b.md) | [2026-11-09 raider-windows cap 2048](../model-offloading/campaign-20261109T145255Z-9e9ae761-offload-model-offloading-1/README.md) | [2026-11-09 raider-windows cap 2048](../model-offloading/campaign-20261109T145255Z-9e9ae761-offload-model-offloading-1/README.md) | [2026-11-09 raider-windows cap 2048](../model-offloading/campaign-20261109T145255Z-9e9ae761-offload-model-offloading-1/README.md) |

## All results

| Date | Experiment | Hardware | Harness | Model | Case | Output cap | Status | Requests | Errors | Median wall s | Output tok/s | Quality | Decisions | Report |
|---|---|---|---|---|---|---:|---|---:|---:|---:|---:|---:|---:|---|
| [2026-11-09](date/2026-11-09.md) | [model-offloading](experiment/model-offloading.md) | [raider-windows](hardware/raider-windows.md) | [koboldcpp](harness/koboldcpp.md) | [qwen38-27b](model/qwen38-27b.md) | qwen38-27b-koboldcpp | 2048 | succeeded | 27 | 0 | 19.7–25.9 | 3.31–3.54 | 24/27 | – | [report](../model-offloading/campaign-20261109T145255Z-9e9ae761-offload-model-offloading-1/README.md) |
| [2026-11-09](date/2026-11-09.md) | [model-offloading](experiment/model-offloading.md) | [raider-windows](hardware/raider-windows.md) | [lmstudio](harness/lmstudio.md) | [qwen38-27b](model/qwen38-27b.md) | qwen38-27b-lmstudio | 2048 | succeeded | 27 | 0 | 7.22–9.13 | 5.93–6.8 | 24/27 | – | [report](../model-offloading/campaign-20261109T145255Z-9e9ae761-offload-model-offloading-1/README.md) |
| [2026-11-09](date/2026-11-09.md) | [model-offloading](experiment/model-offloading.md) | [raider-windows](hardware/raider-windows.md) | [ollama](harness/ollama.md) | [qwen38-27b](model/qwen38-27b.md) | qwen38-27b-ollama | 2048 | succeeded | 27 | 0 | 16–18.7 | 3.55–3.58 | 24/27 | – | [report](../model-offloading/campaign-20261109T145255Z-9e9ae761-offload-model-offloading-1/README.md) |
| [2026-11-09](date/2026-11-09.md) | [model-offloading](experiment/model-offloading.md) | [raider-windows](hardware/raider-windows.md) | [koboldcpp](harness/koboldcpp.md) | [deepseek-r1-32b](model/deepseek-r1-32b.md) | deepseek-r1-32b-koboldcpp | 2048 | succeeded | 27 | 0 | 72.4–114 | 3.49 | 6/27 | – | [report](../model-offloading/campaign-20261109T111225Z-8bf20361-offload-model-offloading-1/README.md) |
| [2026-11-09](date/2026-11-09.md) | [model-offloading](experiment/model-offloading.md) | [raider-windows](hardware/raider-windows.md) | [lmstudio](harness/lmstudio.md) | [deepseek-r1-32b](model/deepseek-r1-32b.md) | deepseek-r1-32b-lmstudio | 2048 | succeeded | 27 | 0 | 99.5–145 | 2.6 | 3/27 | – | [report](../model-offloading/campaign-20261109T111225Z-8bf20361-offload-model-offloading-1/README.md) |
| [2026-11-09](date/2026-11-09.md) | [model-offloading](experiment/model-offloading.md) | [raider-windows](hardware/raider-windows.md) | [ollama](harness/ollama.md) | [deepseek-r1-32b](model/deepseek-r1-32b.md) | deepseek-r1-32b-ollama | 2048 | succeeded | 27 | 0 | 70.4–120 | 3.44–3.45 | 3/27 | – | [report](../model-offloading/campaign-20261109T111225Z-8bf20361-offload-model-offloading-1/README.md) |
| [2026-11-08](date/2026-11-08.md) | [model-offloading](experiment/model-offloading.md) | [raider-windows](hardware/raider-windows.md) | [ollama](harness/ollama.md) | [deepseek-r1-32b](model/deepseek-r1-32b.md) | deepseek-r1-32b-q8 | 2048 | succeeded | 27 | 0 | 70.3–120 | 3.44–3.46 | 3/27 | – | [report](../model-offloading/campaign-20261108T140651Z-a0b0cfdf-offload-model-offloading-1/README.md) |
| [2026-11-08](date/2026-11-08.md) | [llm-routing](experiment/llm-routing.md) | [raider-windows](hardware/raider-windows.md) | [ollama](harness/ollama.md) | [llm-eval-nimble:locked](model/llm-eval-nimble-locked.md) | ollama-nimble | – | succeeded | 6 | 0 | 0.0495–0.0497 | – | – | 6/6 | [report](../llm-routing/campaign-20261108T035738Z-332b0246-routing-llm-routing-1/README.md) |
| [2026-11-08](date/2026-11-08.md) | [llm-routing](experiment/llm-routing.md) | [raider-windows](hardware/raider-windows.md) | [ollama](harness/ollama.md) | [llm-eval-tev1:locked](model/llm-eval-tev1-locked.md) | ollama-tev1 | – | succeeded | 6 | 0 | 0.0274–0.0291 | – | – | 6/6 | [report](../llm-routing/campaign-20261108T035738Z-332b0246-routing-llm-routing-1/README.md) |
| [2026-11-08](date/2026-11-08.md) | [model-offloading](experiment/model-offloading.md) | [raider-windows](hardware/raider-windows.md) | [ollama](harness/ollama.md) | [deepseek-r1-32b](model/deepseek-r1-32b.md) | deepseek-r1-32b-q8 | 256 | succeeded | 27 | 0 | 70.1–75.4 | 3.39–3.47 | 0/27 | – | [report](../model-offloading/campaign-20261108T035738Z-332b0246-offload-model-offloading-1/README.md) |
| [2026-11-08](date/2026-11-08.md) | [model-offloading](experiment/model-offloading.md) | [raider-windows](hardware/raider-windows.md) | [ollama](harness/ollama.md) | [deepseek-r1-32b](model/deepseek-r1-32b.md) | deepseek-r1-32b-q8 | 256 | failed | 27 | 27 | – | – | 0/27 | – | [report](../model-offloading/campaign-20261108T035331Z-833eafe8-offload-model-offloading-1/README.md) |
| [2026-11-08](date/2026-11-08.md) | [llm-routing](experiment/llm-routing.md) | [raider-ubuntu](hardware/raider-ubuntu.md) | [category](harness/category.md) | [category](model/category.md) | category-smoke | – | succeeded (synthetic) | 2 | 0 | 1.81e-05–4.97e-05 | – | – | 2/2 | [report](../llm-routing/campaign-20261108T013814Z-7ff2610d-routing-llm-routing-1/README.md) |
