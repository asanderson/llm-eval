# Recommended setups

[Results index](../README.md) · [Executive summary](../../README.md)

Generated from the published bundles by `llm-eval index-results`; do not edit by hand. One page per hardware configuration and experiment: the best-ranked harness and model combination of the results index and the configuration of that run. Ranked by share of checks passed (correct decisions for routing experiments, quality checks otherwise), then lower median wall time per request, then higher output tokens per second. Each harness and model combination is represented by its newest measured run that succeeded; synthetic fixtures, failed runs and runs without scored checks are not ranked. Wall time and token rate are the median of the category medians. Where a model repeats among the best combinations, a second table ranks the models, each by its best combination.

## hardware-fit

| Hardware configuration | Harness | Model | Checks passed | Median wall s | Output tok/s | Page |
|---|---|---|---:|---:|---:|---|
| [raider-wsl](../hardware/raider-wsl.md) | [koboldcpp](../harness/koboldcpp.md) | [qwen38-27b-ud-q4_k_xl](../model/qwen38-27b-ud-q4_k_xl.md) | 24/27 | 2.78 | 27.2 | [recommended setup](raider-wsl/hardware-fit.md) |

## model-offloading

| Hardware configuration | Harness | Model | Checks passed | Median wall s | Output tok/s | Page |
|---|---|---|---:|---:|---:|---|
| [raider-windows](../hardware/raider-windows.md) | [ollama](../harness/ollama.md) | [kimi-linear-48b](../model/kimi-linear-48b.md) | 24/27 | 0.141 | 16.8 | [recommended setup](raider-windows/model-offloading.md) |
| [raider-wsl](../hardware/raider-wsl.md) | [lmstudio](../harness/lmstudio.md) | [qwen35-35b-moe](../model/qwen35-35b-moe.md) | 27/27 | 8.32 | 42.4 | [recommended setup](raider-wsl/model-offloading.md) |

## legal-benchmark

| Hardware configuration | Harness | Model | Checks passed | Median wall s | Output tok/s | Page |
|---|---|---|---:|---:|---:|---|
| [raider-windows](../hardware/raider-windows.md) | – | – | – | – | – | [recommended setup](raider-windows/legal-benchmark.md) (no recommendation) |
| [raider-wsl](../hardware/raider-wsl.md) | – | – | – | – | – | [recommended setup](raider-wsl/legal-benchmark.md) (no recommendation) |

## llm-routing

| Hardware configuration | Harness | Model | Checks passed | Median wall s | Output tok/s | Page |
|---|---|---|---:|---:|---:|---|
| [raider-ubuntu](../hardware/raider-ubuntu.md) | – | – | – | – | – | [recommended setup](raider-ubuntu/llm-routing.md) (no recommendation) |
| [raider-windows](../hardware/raider-windows.md) | [ollama](../harness/ollama.md) | [llm-eval-tev1:locked](../model/llm-eval-tev1-locked.md) | 6/6 | 0.0367 | – | [recommended setup](raider-windows/llm-routing.md) |
| [raider-wsl](../hardware/raider-wsl.md) | [ollama](../harness/ollama.md) | [llm-eval-tev1:locked](../model/llm-eval-tev1-locked.md) | 6/6 | 0.0253 | – | [recommended setup](raider-wsl/llm-routing.md) |
