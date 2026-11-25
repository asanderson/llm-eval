# Recommended setup, harness and model: hardware-fit on raider-wsl

[Recommended setups](../README.md) · [Results index](../../README.md) · [Executive summary](../../../README.md)

Generated from the published bundles by `llm-eval index-results`; do not edit by hand. 13 published result(s) for this experiment and hardware configuration; 8 harness and model combination(s) are ranked.

## Recommendation

| | |
|---|---|
| Harness | [lmstudio](../../harness/lmstudio.md) |
| Model | [inkling2-mini-26b-iq4_nl](../../model/inkling2-mini-26b-iq4_nl.md) |
| Operating system | windows-11-wsl2-ubuntu-26.04 |
| Checks passed | 27/27 |
| Median wall time per request (s) | 1.75 |
| Output tokens per second | 54.3 |
| Measured | [2026-11-24](../../../hardware-fit/campaign-20261124T232244Z-86c68e03-fit-hardware-fit-1/README.md) |

This is the best-ranked combination of the results index for this pair. Ranked by share of checks passed (correct decisions for decision models, quality checks otherwise), then lower median wall time per request, then higher output tokens per second. Each harness and model combination is represented by its newest measured run that succeeded; synthetic fixtures, failed runs and runs without scored checks are not ranked. Wall time and token rate are the median of the category medians. Where a model repeats among the best combinations, a second table ranks the models, each by its best combination.

2 combinations pass the same share of checks as the recommended one; the order among them is by median wall time, then by output rate.

It is a statement about the published runs on this hardware configuration, not about the model or the harness in general. The checks are small deterministic checks, the runs can differ in more than the harness and the model (each report states its conditions), and the recommendation changes when a newer run of a combination is published.

## Setup of the recommended run

Read from the resolved configuration of the run's report. To reproduce it, use the measured code revision named in that report.

| Setting | Value |
|---|---|
| Harness version | 0.4.28+2 |
| Model file | Inkling-2-Mini-IQ4_NL.gguf |
| GPU share requested (ratio) | max |
| Import mode | symbolic-link |
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
| Model artifact and tokenizer revision | ggml-org/Inkling-2-Mini-GGUF@e8a2cecf0e78914f07cc27b9be711a9b2c7561d9 (tokenizer embedded in locked GGUF) |
| Chat template SHA-256 | 53a9035f3255945704b5857657cfb00c1165090c0641c4f782a0cbf268cc16dc |
| Reasoning mode | model default; OpenAI-protocol harnesses may return reasoning inline in content |
| Placement notes | Requested every layer on the GPU (launch.gpu_offload max; the thread count is the app default), context 8192. LM Studio 0.4.28+2 ran as the desktop app from LM-Studio-0.4.28-2-x64.AppImage under WSLg; observed AppImage SHA-256 a3e6cf8233697be0a8ad6871197b424242af3c5a346671aeed59959ed7eebf11 (the vendor publishes none). The managed launch keeps no placement lines in its log; the evidence is the VRAM telemetry in fit/metadata.json of the attempt. |
| NVIDIA driver | 610.74 |
| OS build | 10.0.26300 (Windows host; guest kernel 6.18.33.2-microsoft-standard-WSL2) |
| WSL version | 2.7.12.0, kernel 6.18.33.2-microsoft-standard-WSL2 |
| WSL guest memory | guest MemTotal 51.0 GiB at the start of this run; swap 0 MiB (see wsl_config) |

## Best combination on each harness

The rank is the position in the ranking of this pair.

| Rank | Harness | Model | Checks passed | Median wall s | Output tok/s | Run |
|---:|---|---|---:|---:|---:|---|
| 1 | [lmstudio](../../harness/lmstudio.md) | [inkling2-mini-26b-iq4_nl](../../model/inkling2-mini-26b-iq4_nl.md) | 27/27 | 1.75 | 54.3 | [2026-11-24](../../../hardware-fit/campaign-20261124T232244Z-86c68e03-fit-hardware-fit-1/README.md) |
| 2 | [koboldcpp](../../harness/koboldcpp.md) | [inkling2-mini-26b-iq4_nl](../../model/inkling2-mini-26b-iq4_nl.md) | 27/27 | 6.66 | 12.8 | [2026-11-24](../../../hardware-fit/campaign-20261124T225210Z-e801df32-fit-hardware-fit-1/README.md) |
| 4 | [ollama](../../harness/ollama.md) | [qwen38-27b-ud-q4_k_xl](../../model/qwen38-27b-ud-q4_k_xl.md) | 24/27 | 1.97 | 33.7 | [2026-11-24](../../../hardware-fit/campaign-20261124T230811Z-0fa376ca-fit-hardware-fit-1/README.md) |

## Best 5 combinations

| Rank | Harness | Model | Checks passed | Median wall s | Output tok/s | Run |
|---:|---|---|---:|---:|---:|---|
| 1 | [lmstudio](../../harness/lmstudio.md) | [inkling2-mini-26b-iq4_nl](../../model/inkling2-mini-26b-iq4_nl.md) | 27/27 | 1.75 | 54.3 | [2026-11-24](../../../hardware-fit/campaign-20261124T232244Z-86c68e03-fit-hardware-fit-1/README.md) |
| 2 | [koboldcpp](../../harness/koboldcpp.md) | [inkling2-mini-26b-iq4_nl](../../model/inkling2-mini-26b-iq4_nl.md) | 27/27 | 6.66 | 12.8 | [2026-11-24](../../../hardware-fit/campaign-20261124T225210Z-e801df32-fit-hardware-fit-1/README.md) |
| 3 | [lmstudio](../../harness/lmstudio.md) | [qwen38-27b-ud-q4_k_xl](../../model/qwen38-27b-ud-q4_k_xl.md) | 24/27 | 0.886 | 68.6 | [2026-11-23](../../../hardware-fit/campaign-20261123T120632Z-53d7833d-fit-hardware-fit-1/README.md) |
| 4 | [ollama](../../harness/ollama.md) | [qwen38-27b-ud-q4_k_xl](../../model/qwen38-27b-ud-q4_k_xl.md) | 24/27 | 1.97 | 33.7 | [2026-11-24](../../../hardware-fit/campaign-20261124T230811Z-0fa376ca-fit-hardware-fit-1/README.md) |
| 5 | [koboldcpp](../../harness/koboldcpp.md) | [qwen38-27b-ud-q4_k_xl](../../model/qwen38-27b-ud-q4_k_xl.md) | 24/27 | 3.04 | 27 | [2026-11-24](../../../hardware-fit/campaign-20261124T225210Z-e801df32-fit-hardware-fit-1/README.md) |

## Published results of this pair

| Date | Experiment | Hardware | Harness | Model | Case | Output cap | Status | Requests | Errors | Median wall s | Output tok/s | Quality | Decisions | Report |
|---|---|---|---|---|---|---:|---|---:|---:|---:|---:|---:|---:|---|
| [2026-11-24](../../date/2026-11-24.md) | [hardware-fit](../../experiment/hardware-fit.md) | [raider-wsl](../../hardware/raider-wsl.md) | [lmstudio](../../harness/lmstudio.md) | [inkling2-mini-26b-iq4_nl](../../model/inkling2-mini-26b-iq4_nl.md) | inkling2-mini-26b-iq4_nl-lmstudio | 2048 | succeeded | 27 | 0 | 1.46–2.04 | 53.5–55.3 | 27/27 | – | [report](../../../hardware-fit/campaign-20261124T232244Z-86c68e03-fit-hardware-fit-1/README.md) |
| [2026-11-24](../../date/2026-11-24.md) | [hardware-fit](../../experiment/hardware-fit.md) | [raider-wsl](../../hardware/raider-wsl.md) | [lmstudio](../../harness/lmstudio.md) | [muse-glimmer-30b-kquant-17gb-q4_k_m](../../model/muse-glimmer-30b-kquant-17gb-q4_k_m.md) | muse-glimmer-30b-kquant-17gb-q4_k_m-lmstudio | 2048 | succeeded | 27 | 0 | 2.96–6.84 | 35.4–35.7 | 24/27 | – | [report](../../../hardware-fit/campaign-20261124T232244Z-86c68e03-fit-hardware-fit-1/README.md) |
| [2026-11-24](../../date/2026-11-24.md) | [hardware-fit](../../experiment/hardware-fit.md) | [raider-wsl](../../hardware/raider-wsl.md) | [ollama](../../harness/ollama.md) | [inkling2-mini-26b-iq4_nl](../../model/inkling2-mini-26b-iq4_nl.md) | inkling2-mini-26b-iq4_nl-ollama | 2048 | failed | 27 | 27 | – | – | 0/27 | – | [report](../../../hardware-fit/campaign-20261124T230811Z-0fa376ca-fit-hardware-fit-1/README.md) |
| [2026-11-24](../../date/2026-11-24.md) | [hardware-fit](../../experiment/hardware-fit.md) | [raider-wsl](../../hardware/raider-wsl.md) | [ollama](../../harness/ollama.md) | [muse-glimmer-30b-kquant-17gb-q4_k_m](../../model/muse-glimmer-30b-kquant-17gb-q4_k_m.md) | muse-glimmer-30b-kquant-17gb-q4_k_m-ollama | 2048 | succeeded | 27 | 0 | 2.78–5.19 | 36.6–37.1 | 24/27 | – | [report](../../../hardware-fit/campaign-20261124T230811Z-0fa376ca-fit-hardware-fit-1/README.md) |
| [2026-11-24](../../date/2026-11-24.md) | [hardware-fit](../../experiment/hardware-fit.md) | [raider-wsl](../../hardware/raider-wsl.md) | [ollama](../../harness/ollama.md) | [qwen38-27b-ud-q4_k_xl](../../model/qwen38-27b-ud-q4_k_xl.md) | qwen38-27b-ud-q4_k_xl-ollama | 2048 | succeeded | 27 | 0 | 1.41–1.98 | 33.1–33.7 | 24/27 | – | [report](../../../hardware-fit/campaign-20261124T230811Z-0fa376ca-fit-hardware-fit-1/README.md) |
| [2026-11-24](../../date/2026-11-24.md) | [hardware-fit](../../experiment/hardware-fit.md) | [raider-wsl](../../hardware/raider-wsl.md) | [koboldcpp](../../harness/koboldcpp.md) | [inkling2-mini-26b-iq4_nl](../../model/inkling2-mini-26b-iq4_nl.md) | inkling2-mini-26b-iq4_nl-koboldcpp | 2048 | succeeded | 27 | 0 | 5.22–11.7 | 12.8–13 | 27/27 | – | [report](../../../hardware-fit/campaign-20261124T225210Z-e801df32-fit-hardware-fit-1/README.md) |
| [2026-11-24](../../date/2026-11-24.md) | [hardware-fit](../../experiment/hardware-fit.md) | [raider-wsl](../../hardware/raider-wsl.md) | [koboldcpp](../../harness/koboldcpp.md) | [muse-glimmer-30b-kquant-17gb-q4_k_m](../../model/muse-glimmer-30b-kquant-17gb-q4_k_m.md) | muse-glimmer-30b-kquant-17gb-q4_k_m-koboldcpp | 2048 | succeeded | 27 | 0 | 0.524–0.525 | 3.81–3.82 | 18/27 | – | [report](../../../hardware-fit/campaign-20261124T225210Z-e801df32-fit-hardware-fit-1/README.md) |
| [2026-11-24](../../date/2026-11-24.md) | [hardware-fit](../../experiment/hardware-fit.md) | [raider-wsl](../../hardware/raider-wsl.md) | [koboldcpp](../../harness/koboldcpp.md) | [qwen38-27b-ud-q4_k_xl](../../model/qwen38-27b-ud-q4_k_xl.md) | qwen38-27b-ud-q4_k_xl-koboldcpp | 2048 | succeeded | 27 | 0 | 2.76–3.72 | 27–27.7 | 24/27 | – | [report](../../../hardware-fit/campaign-20261124T225210Z-e801df32-fit-hardware-fit-1/README.md) |
| [2026-11-23](../../date/2026-11-23.md) | [hardware-fit](../../experiment/hardware-fit.md) | [raider-wsl](../../hardware/raider-wsl.md) | [lmstudio](../../harness/lmstudio.md) | [qwen38-27b-ud-q4_k_xl](../../model/qwen38-27b-ud-q4_k_xl.md) | qwen38-27b-ud-q4_k_xl-lmstudio | 2048 | succeeded | 27 | 0 | 0.753–0.968 | 61.6–69.1 | 24/27 | – | [report](../../../hardware-fit/campaign-20261123T120632Z-53d7833d-fit-hardware-fit-1/README.md) |
| [2026-11-23](../../date/2026-11-23.md) | [hardware-fit](../../experiment/hardware-fit.md) | [raider-wsl](../../hardware/raider-wsl.md) | [ollama](../../harness/ollama.md) | [qwen38-27b-ud-q4_k_xl](../../model/qwen38-27b-ud-q4_k_xl.md) | qwen38-27b-ud-q4_k_xl-ollama | 2048 | succeeded | 27 | 0 | 1.43–1.99 | 32.9–33.7 | 24/27 | – | [report](../../../hardware-fit/campaign-20261123T120632Z-53d7833d-fit-hardware-fit-1/README.md) |
| [2026-11-23](../../date/2026-11-23.md) | [hardware-fit](../../experiment/hardware-fit.md) | [raider-wsl](../../hardware/raider-wsl.md) | [koboldcpp](../../harness/koboldcpp.md) | [qwen38-27b-ud-q4_k_xl](../../model/qwen38-27b-ud-q4_k_xl.md) | qwen38-27b-ud-q4_k_xl-koboldcpp | 2048 | succeeded | 27 | 0 | 2.58–3.07 | 26.9–27.4 | 24/27 | – | [report](../../../hardware-fit/campaign-20261123T060454Z-d3e0de27-fit-hardware-fit-1/README.md) |
| [2026-11-23](../../date/2026-11-23.md) | [hardware-fit](../../experiment/hardware-fit.md) | [raider-wsl](../../hardware/raider-wsl.md) | [projection](../../harness/projection.md) | [measured-models-gguf](../../model/measured-models-gguf.md) | projection-measured-models | – | succeeded | 430 | 0 | – | – | – | – | [report](../../../hardware-fit/campaign-20261123T060120Z-252fece8-fit-hardware-fit-1/README.md) |
| [2026-11-23](../../date/2026-11-23.md) | [hardware-fit](../../experiment/hardware-fit.md) | [raider-wsl](../../hardware/raider-wsl.md) | [projection](../../harness/projection.md) | [measured-models-gguf-as-found](../../model/measured-models-gguf-as-found.md) | projection-measured-models-as-found | – | succeeded | 430 | 0 | – | – | – | – | [report](../../../hardware-fit/campaign-20261123T060120Z-252fece8-fit-hardware-fit-1/README.md) |
