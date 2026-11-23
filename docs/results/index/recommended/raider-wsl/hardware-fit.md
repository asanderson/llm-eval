# Recommended setup, harness and model: hardware-fit on raider-wsl

[Recommended setups](../README.md) · [Results index](../../README.md) · [Executive summary](../../../README.md)

Generated from the published bundles by `llm-eval index-results`; do not edit by hand. 3 published result(s) for this experiment and hardware configuration; 1 harness and model combination(s) are ranked.

## Recommendation

| | |
|---|---|
| Harness | [koboldcpp](../../harness/koboldcpp.md) |
| Model | [qwen38-27b-ud-q4_k_xl](../../model/qwen38-27b-ud-q4_k_xl.md) |
| Operating system | windows-11-wsl2-ubuntu-26.04 |
| Checks passed | 24/27 |
| Median wall time per request (s) | 2.78 |
| Output tokens per second | 27.2 |
| Measured | [2026-11-23](../../../hardware-fit/campaign-20261123T060454Z-d3e0de27-fit-hardware-fit-1/README.md) |

This is the best-ranked combination of the results index for this pair. Ranked by share of checks passed (correct decisions for routing experiments, quality checks otherwise), then lower median wall time per request, then higher output tokens per second. Each harness and model combination is represented by its newest measured run that succeeded; synthetic fixtures, failed runs and runs without scored checks are not ranked. Wall time and token rate are the median of the category medians. Where a model repeats among the best combinations, a second table ranks the models, each by its best combination.

It is a statement about the published runs on this hardware configuration, not about the model or the harness in general. The checks are small deterministic checks, the runs can differ in more than the harness and the model (each report states its conditions), and the recommendation changes when a newer run of a combination is published.

## Setup of the recommended run

Read from the resolved configuration of the run's report. To reproduce it, use the measured code revision named in that report.

| Setting | Value |
|---|---|
| Harness version | 1.124.2 |
| Model file | Qwen3.8-27B-UD-Q4_K_XL.gguf |
| GPU layers requested | 999 |
| CPU threads | 16 |
| Lane | control |
| Context tokens | 8192 |
| Output cap (tokens) | 2048 |
| Temperature | 0.0 |
| Seed | 20261005 |
| Warm-ups per task | 1 |
| Measured repetitions per task | 3 |
| Request deadline (s) | 900 |
| RAM budget (GiB) | 46 |
| GPU budget (GiB) | 22 |
| Model artifact and tokenizer revision | unsloth/Qwen3.8-27B-GGUF@4ca720788d1e01f1bff70c033e0d0028fd02e502 (tokenizer embedded in locked GGUF) |
| Chat template SHA-256 | 12827f24b742ea4e80cdc12dbcf9622227056b9f797252a3149263d4f9aaadce |
| Reasoning mode | model default; OpenAI-protocol harnesses may return reasoning inline in content |
| Placement notes | Requested every layer on the GPU (launch.gpu_layers 999), 16 CPU threads, context 8192. Observed placement is in the backend log and in fit/metadata.json of the attempt. |
| NVIDIA driver | 610.74 |
| OS build | 10.0.26300 (Windows host; guest kernel 6.18.33.2-microsoft-standard-WSL2) |
| WSL version | 2.7.12.0, kernel 6.18.33.2-microsoft-standard-WSL2 |
| WSL guest memory | guest MemTotal 51.0 GiB at the start of this run; swap 0 MiB (see wsl_config) |

## Published results of this pair

| Date | Experiment | Hardware | Harness | Model | Case | Output cap | Status | Requests | Errors | Median wall s | Output tok/s | Quality | Decisions | Report |
|---|---|---|---|---|---|---:|---|---:|---:|---:|---:|---:|---:|---|
| [2026-11-23](../../date/2026-11-23.md) | [hardware-fit](../../experiment/hardware-fit.md) | [raider-wsl](../../hardware/raider-wsl.md) | [koboldcpp](../../harness/koboldcpp.md) | [qwen38-27b-ud-q4_k_xl](../../model/qwen38-27b-ud-q4_k_xl.md) | qwen38-27b-ud-q4_k_xl-koboldcpp | 2048 | succeeded | 27 | 0 | 2.58–3.07 | 26.9–27.4 | 24/27 | – | [report](../../../hardware-fit/campaign-20261123T060454Z-d3e0de27-fit-hardware-fit-1/README.md) |
| [2026-11-23](../../date/2026-11-23.md) | [hardware-fit](../../experiment/hardware-fit.md) | [raider-wsl](../../hardware/raider-wsl.md) | [projection](../../harness/projection.md) | [measured-models-gguf](../../model/measured-models-gguf.md) | projection-measured-models | – | succeeded | 430 | 0 | – | – | – | – | [report](../../../hardware-fit/campaign-20261123T060120Z-252fece8-fit-hardware-fit-1/README.md) |
| [2026-11-23](../../date/2026-11-23.md) | [hardware-fit](../../experiment/hardware-fit.md) | [raider-wsl](../../hardware/raider-wsl.md) | [projection](../../harness/projection.md) | [measured-models-gguf-as-found](../../model/measured-models-gguf-as-found.md) | projection-measured-models-as-found | – | succeeded | 430 | 0 | – | – | – | – | [report](../../../hardware-fit/campaign-20261123T060120Z-252fece8-fit-hardware-fit-1/README.md) |
