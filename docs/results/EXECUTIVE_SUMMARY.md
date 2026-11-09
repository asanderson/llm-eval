# Executive summary of results

Operator-written conclusions over the published result bundles in this directory. The index below is generated from the bundles (`llm-eval index-results`): it opens with the three best harness and model combinations per experiment for each hardware configuration, then links to every result by hardware configuration, experiment, harness, model and date. The narrative that follows is organized the same way: experiment, then harness, then model. Figures are medians over measured (non-warmup) requests unless stated otherwise; per-campaign detail, raw measurements and resolved configurations are in each linked report.

## Results index

<!-- results-index:start -->

### Top 3 harness and model combinations per experiment and hardware configuration

Ranked by share of checks passed (correct decisions for routing experiments, quality checks otherwise), then lower median wall time per request, then higher output tokens per second. Each harness and model combination is represented by its newest measured run that succeeded; synthetic fixtures, failed runs and runs without scored checks are not ranked. Wall time and token rate are the median of the category medians.

**[llm-routing](index/experiment/llm-routing.md) on [raider-ubuntu](index/hardware/raider-ubuntu.md)**

No measured run with scored checks has been published yet.

**[llm-routing](index/experiment/llm-routing.md) on [raider-windows](index/hardware/raider-windows.md)**

| Rank | Harness | Model | Checks passed | Median wall s | Output tok/s | Run |
|---:|---|---|---:|---:|---:|---|
| 1 | [ollama](index/harness/ollama.md) | [llm-eval-tev1:locked](index/model/llm-eval-tev1-locked.md) | 6/6 | 0.0282 | – | [2026-11-08](llm-routing/campaign-20261108T035738Z-332b0246-routing-llm-routing-1/README.md) |
| 2 | [ollama](index/harness/ollama.md) | [llm-eval-nimble:locked](index/model/llm-eval-nimble-locked.md) | 6/6 | 0.0496 | – | [2026-11-08](llm-routing/campaign-20261108T035738Z-332b0246-routing-llm-routing-1/README.md) |

**[model-offloading](index/experiment/model-offloading.md) on [raider-windows](index/hardware/raider-windows.md)**

| Rank | Harness | Model | Checks passed | Median wall s | Output tok/s | Run |
|---:|---|---|---:|---:|---:|---|
| 1 | [ollama](index/harness/ollama.md) | [nemotron-nano-30b](index/model/nemotron-nano-30b.md) | 24/27 | 2.46 | 29.9 | [2026-11-09 cap 2048](model-offloading/campaign-20261109T174915Z-128e3dcf-offload-model-offloading-1/README.md) |
| 2 | [lmstudio](index/harness/lmstudio.md) | [nemotron-nano-30b](index/model/nemotron-nano-30b.md) | 24/27 | 4.5 | 14.7 | [2026-11-09 cap 2048](model-offloading/campaign-20261109T174915Z-128e3dcf-offload-model-offloading-1/README.md) |
| 3 | [lmstudio](index/harness/lmstudio.md) | [qwen38-27b](index/model/qwen38-27b.md) | 24/27 | 7.75 | 6.4 | [2026-11-09 cap 2048](model-offloading/campaign-20261109T145255Z-9e9ae761-offload-model-offloading-1/README.md) |

### Browse by category

| Category | Indexes (results) |
|---|---|
| Hardware configuration | [raider-ubuntu](index/hardware/raider-ubuntu.md) (1) · [raider-windows](index/hardware/raider-windows.md) (21) |
| Experiment | [llm-routing](index/experiment/llm-routing.md) (3) · [model-offloading](index/experiment/model-offloading.md) (19) |
| Harness | [category](index/harness/category.md) (1) · [koboldcpp](index/harness/koboldcpp.md) (5) · [lmstudio](index/harness/lmstudio.md) (5) · [ollama](index/harness/ollama.md) (11) |
| Model | [category](index/model/category.md) (1) · [deepseek-r1-32b](index/model/deepseek-r1-32b.md) (6) · [gemma3-27b](index/model/gemma3-27b.md) (3) · [gemma4-31b](index/model/gemma4-31b.md) (4) · [llm-eval-nimble:locked](index/model/llm-eval-nimble-locked.md) (1) · [llm-eval-tev1:locked](index/model/llm-eval-tev1-locked.md) (1) · [nemotron-nano-30b](index/model/nemotron-nano-30b.md) (3) · [qwen38-27b](index/model/qwen38-27b.md) (3) |
| Date (UTC) | [2026-11-09](index/date/2026-11-09.md) (16) · [2026-11-08](index/date/2026-11-08.md) (6) |

### llm-routing: models by harness

Each cell links to the report of every published run of that model on that harness, newest first.

| Model | [category](index/harness/category.md) | [ollama](index/harness/ollama.md) |
|---|---|---|
| [category](index/model/category.md) | [2026-11-08 raider-ubuntu synthetic](llm-routing/campaign-20261108T013814Z-7ff2610d-routing-llm-routing-1/README.md) | – |
| [llm-eval-nimble:locked](index/model/llm-eval-nimble-locked.md) | – | [2026-11-08 raider-windows](llm-routing/campaign-20261108T035738Z-332b0246-routing-llm-routing-1/README.md) |
| [llm-eval-tev1:locked](index/model/llm-eval-tev1-locked.md) | – | [2026-11-08 raider-windows](llm-routing/campaign-20261108T035738Z-332b0246-routing-llm-routing-1/README.md) |

### model-offloading: models by harness

Each cell links to the report of every published run of that model on that harness, newest first.

| Model | [koboldcpp](index/harness/koboldcpp.md) | [lmstudio](index/harness/lmstudio.md) | [ollama](index/harness/ollama.md) |
|---|---|---|---|
| [deepseek-r1-32b](index/model/deepseek-r1-32b.md) | [2026-11-09 raider-windows cap 2048](model-offloading/campaign-20261109T111225Z-8bf20361-offload-model-offloading-1/README.md) | [2026-11-09 raider-windows cap 2048](model-offloading/campaign-20261109T111225Z-8bf20361-offload-model-offloading-1/README.md) | [2026-11-09 raider-windows cap 2048](model-offloading/campaign-20261109T111225Z-8bf20361-offload-model-offloading-1/README.md)<br>[2026-11-08 raider-windows cap 2048](model-offloading/campaign-20261108T140651Z-a0b0cfdf-offload-model-offloading-1/README.md)<br>[2026-11-08 raider-windows cap 256](model-offloading/campaign-20261108T035738Z-332b0246-offload-model-offloading-1/README.md)<br>[2026-11-08 raider-windows cap 256 failed](model-offloading/campaign-20261108T035331Z-833eafe8-offload-model-offloading-1/README.md) |
| [gemma3-27b](index/model/gemma3-27b.md) | [2026-11-09 raider-windows cap 2048](model-offloading/campaign-20261109T171430Z-c1c4ab49-offload-model-offloading-1/README.md) | [2026-11-09 raider-windows cap 2048](model-offloading/campaign-20261109T171430Z-c1c4ab49-offload-model-offloading-1/README.md) | [2026-11-09 raider-windows cap 2048](model-offloading/campaign-20261109T171430Z-c1c4ab49-offload-model-offloading-1/README.md) |
| [gemma4-31b](index/model/gemma4-31b.md) | [2026-11-09 raider-windows cap 2048](model-offloading/campaign-20261109T154341Z-1e8d354f-offload-model-offloading-1/README.md) | [2026-11-09 raider-windows cap 2048](model-offloading/campaign-20261109T154341Z-1e8d354f-offload-model-offloading-1/README.md) | [2026-11-09 raider-windows cap 2048](model-offloading/campaign-20261109T180247Z-c38f462b-offload-model-offloading-1/README.md)<br>[2026-11-09 raider-windows cap 2048 failed](model-offloading/campaign-20261109T154341Z-1e8d354f-offload-model-offloading-1/README.md) |
| [nemotron-nano-30b](index/model/nemotron-nano-30b.md) | [2026-11-09 raider-windows cap 2048](model-offloading/campaign-20261109T174915Z-128e3dcf-offload-model-offloading-1/README.md) | [2026-11-09 raider-windows cap 2048](model-offloading/campaign-20261109T174915Z-128e3dcf-offload-model-offloading-1/README.md) | [2026-11-09 raider-windows cap 2048](model-offloading/campaign-20261109T174915Z-128e3dcf-offload-model-offloading-1/README.md) |
| [qwen38-27b](index/model/qwen38-27b.md) | [2026-11-09 raider-windows cap 2048](model-offloading/campaign-20261109T145255Z-9e9ae761-offload-model-offloading-1/README.md) | [2026-11-09 raider-windows cap 2048](model-offloading/campaign-20261109T145255Z-9e9ae761-offload-model-offloading-1/README.md) | [2026-11-09 raider-windows cap 2048](model-offloading/campaign-20261109T145255Z-9e9ae761-offload-model-offloading-1/README.md) |

Full table and per-category pages: [results index](index/README.md).

<!-- results-index:end -->

## Results by experiment, harness and model

### Experiment `model-offloading` (mode `category-smoke`)

Model quality, performance and memory placement of an over-VRAM model on one serving harness. Workload: three short-answer tasks in each of the reasoning, coding and math categories, 3 repeats plus 1 warmup per task, 4,096-token context, one request at a time.

#### Harness: Ollama 0.40.15

Pinned archive install, private server on loopback, one loaded model, one parallel request.

##### Model: `deepseek-r1-32b` (DeepSeek-R1-Distill-Qwen-32B Q8_0, 34.8 GB GGUF, SHA256-locked)

Hardware configuration `raider-windows`, 20 of 65 layers on GPU, 16 CPU threads. The 2026-11-08 runs used a hand-started private server; the 2026-11-09 run used a harness-managed one.

| Run (UTC) | Output cap | Category | Requests | Wall s (median / p95) | First output s | First visible s | Output tokens (median / max) | Output tok/s | Finish reason | Quality |
|---|---:|---|---:|---:|---:|---:|---:|---:|---|---:|
| [2026-11-08 03:57](model-offloading/campaign-20261108T035738Z-332b0246-offload-model-offloading-1/README.md) | 256 | coding | 9 | 73.9 / 73.9 | 0.90 | – | 256 / 256 | 3.47 | length 9/9 | 0/9 |
| | 256 | math | 9 | 70.1 / 73.8 | 0.89 | 25.6 | 243 / 256 | 3.47 | stop 6/9, length 3/9 | 0/9 |
| | 256 | reasoning | 9 | 75.4 / 76.5 | 0.92 | 30.2 (3 of 9) | 256 / 256 | 3.39 | length 9/9 | 0/9 |
| [2026-11-08 14:06](model-offloading/campaign-20261108T140651Z-a0b0cfdf-offload-model-offloading-1/README.md) | 2,048 | coding | 9 | 119.8 / 132.7 | 0.92 | 107.9 | 413 / 457 | 3.44 | stop 9/9 | 3/9 |
| | 2,048 | math | 9 | 70.3 / 82.5 | 0.90 | 25.7 | 243 / 285 | 3.46 | stop 9/9 | 0/9 |
| | 2,048 | reasoning | 9 | 88.1 / 112.5 | 0.92 | 83.2 | 304 / 388 | 3.45 | stop 9/9 | 0/9 |
| [2026-11-09 11:12](model-offloading/campaign-20261109T111225Z-8bf20361-offload-model-offloading-1/README.md) | 2,048 | coding | 9 | 119.7 / 134.7 | 0.92 | 107.8 | 413 / 457 | 3.44 | stop 9/9 | 3/9 |
| | 2,048 | math | 9 | 70.4 / 82.7 | 0.90 | 25.8 | 243 / 285 | 3.44 | stop 9/9 | 0/9 |
| | 2,048 | reasoning | 9 | 88.2 / 112.5 | 0.92 | 83.3 | 304 / 388 | 3.45 | stop 9/9 | 0/9 |

| Run | Peak system RAM | Backend RSS | Peak GPU memory | GPU utilization | GPU power | GPU temperature | Swap used (in/out) |
|---|---:|---:|---:|---:|---:|---:|---|
| 256 cap | 34.1 GiB | 24.6 GiB | 11.8 GiB | 100 % | 39.5 W | 47 °C | 1.3 GiB (0 / 0) |
| 2,048 cap | 34.9 GiB | 25.0 GiB | 11.8 GiB | 94 % | 47.1 W | 47 °C | 1.0 GiB (0 / 0) |
| 2,048 cap, 2026-11-09 | 37.4 GiB | 25.0 GiB | 11.8 GiB | 95 % | 43.5 W | 47 °C | 0.8 GiB (0 / 0) |

- **Throughput is stable and cap-independent**: about 3.45 output tokens per second in both runs. Cold model load added 22.9 s to the first warmup.
- **The 256 cap truncates most answers.** 21 of 27 requests ended with `length` and 15 never produced visible text, their budget spent inside the model's `<think>` block. The six math requests that finished naturally still failed the exact checks.
- **At 2,048 the model stops on its own** after 243 to 460 tokens. "First visible" (time until non-reasoning text) is the user-facing latency: 26 s for math, 108 s for coding.
- **Quality 3/27 is an instruction-following score, not correctness.** A live reproduction of the arithmetic task returned the right answer as `\boxed{3973}` inside a LaTeX walkthrough, which fails the suite's `exact` check against `3973`. The suite's own `quality_scope` says it is not a reasoning benchmark.
- **The result reproduces.** The 2026-11-09 run used a harness-managed Ollama server instead of a hand-started one and landed within 1 % of the 2026-11-08 run on every latency and throughput figure, with the same three quality passes.
- An [earlier attempt](model-offloading/campaign-20261108T035331Z-833eafe8-offload-model-offloading-1/README.md) on 2026-11-08 03:53 failed with 36 connection-refused requests because the private Ollama process was ended by hand. It is operator error and carries no measurement.

##### Model: `qwen38-27b` (Qwen3.8-27B Q8_0, 29.0 GB GGUF, SHA256-locked)

Hardware configuration `raider-windows`, 20 of 66 layers on GPU (confirmed in the backend log), 16 CPU threads, harness-managed server.

| Run (UTC) | Output cap | Category | Requests | Wall s (median / p95) | First output s | First visible s | Output tokens (median / max) | Output tok/s | Finish reason | Quality |
|---|---:|---|---:|---:|---:|---:|---:|---:|---|---:|
| [2026-11-09 14:52](model-offloading/campaign-20261109T145255Z-9e9ae761-offload-model-offloading-1/README.md) | 2,048 | coding | 9 | 18.7 / 22.5 | 0.41 | 18.4 | 67 / 80 | 3.58 | stop 9/9 | 9/9 |
| | 2,048 | math | 9 | 16.0 / 22.5 | 0.42 | 15.8 | 57 / 80 | 3.55 | stop 9/9 | 9/9 |
| | 2,048 | reasoning | 9 | 16.8 / 26.9 | 0.42 | 16.6 | 60 / 96 | 3.56 | stop 9/9 | 6/9 |

- **Same token rate as DeepSeek-R1-32B, a fifth of the wait.** About 3.56 output tokens per second, but answers take 57 to 67 tokens instead of 243 to 413, so a short answer arrives in 16 to 19 s.
- **Quality 24/27.** The one failing task, `reasoning-logic`, fails on all three repeats.

##### Model: `gemma3-27b` (gemma-3-27b-it Q8_0, 28.7 GB GGUF, SHA256-locked)

Hardware configuration `raider-windows`, 20 of 63 layers on GPU (confirmed in the backend log), 16 CPU threads, harness-managed server.

| Run (UTC) | Output cap | Category | Requests | Wall s (median / p95) | First output s | First visible s | Output tokens (median / max) | Output tok/s | Finish reason | Quality |
|---|---:|---|---:|---:|---:|---:|---:|---:|---|---:|
| [2026-11-09 17:14](model-offloading/campaign-20261109T171430Z-c1c4ab49-offload-model-offloading-1/README.md) | 2,048 | coding | 9 | 1.4 / 2.3 | 0.61 | 0.6 | 4 / 7 | 2.83 | stop 9/9 | 9/9 |
| | 2,048 | math | 9 | 1.2 / 38.6 | 0.63 | 0.6 | 3 / 136 | 2.55 | stop 9/9 | 6/9 |
| | 2,048 | reasoning | 9 | 3.9 / 10.6 | 0.61 | 0.6 | 13 / 37 | 3.33 | stop 9/9 | 3/9 |

- **Answers in one to four seconds.** The model does not reason before answering: a typical answer is 3 to 13 tokens, so wall time is mostly the 0.6 s to the first token. One math task occasionally runs to 136 tokens and 39 s, which sets the p95.
- **Token rate is not comparable with the reasoning models.** With answers this short the rate is dominated by time to first token; read wall time instead.
- **Quality 18/27.** Three tasks fail on every repeat: `math-arithmetic`, `reasoning-logic` and `reasoning-navigation`.

##### Model: `nemotron-nano-30b` (Nemotron-3-Nano-30B-A3B Q8_0, 33.6 GB GGUF, SHA256-locked)

Hardware configuration `raider-windows`, 20 of 53 layers on GPU (confirmed in the backend log), 16 CPU threads, harness-managed server. Mixture-of-experts model: about 3B of its 30B parameters are active per token.

| Run (UTC) | Output cap | Category | Requests | Wall s (median / p95) | First output s | First visible s | Output tokens (median / max) | Output tok/s | Finish reason | Quality |
|---|---:|---|---:|---:|---:|---:|---:|---:|---|---:|
| [2026-11-09 17:49](model-offloading/campaign-20261109T174915Z-128e3dcf-offload-model-offloading-1/README.md) | 2,048 | coding | 9 | 2.5 / 6.2 | 0.11 | 2.4 | 73 / 187 | 29.97 | stop 9/9 | 9/9 |
| | 2,048 | math | 9 | 2.1 / 2.3 | 0.11 | 2.0 | 62 / 66 | 29.63 | stop 9/9 | 9/9 |
| | 2,048 | reasoning | 9 | 3.1 / 3.3 | 0.11 | 3.0 | 92 / 97 | 29.89 | stop 9/9 | 6/9 |

- **About 30 output tokens per second with most of the model in RAM**, eight to nine times the dense models of similar size on the same split. Answers arrive in 2 to 3 s including a short reasoning step.
- **Quality 24/27**, the same single failing task as Qwen 3.8 27B and Gemma 4 31B (`reasoning-logic`).
- **First run on the fixed request timeout.** The 31.3 GiB model loaded on the first request without the warmup failure seen with Gemma 4 31B.

##### Model: `gemma4-31b` (gemma-4-31B-it Q8_0, 32.6 GB GGUF, SHA256-locked)

Hardware configuration `raider-windows`, 20 of 61 layers on GPU (confirmed in the backend log), 16 CPU threads, harness-managed server. This is a rerun: in the [15:43 campaign](model-offloading/campaign-20261109T154341Z-1e8d354f-offload-model-offloading-1/README.md) the warmup request timed out while the model was still loading, which marked the job failed although its 27 measured requests succeeded. That harness defect was fixed before this run.

| Run (UTC) | Output cap | Category | Requests | Wall s (median / p95) | First output s | First visible s | Output tokens (median / max) | Output tok/s | Finish reason | Quality |
|---|---:|---|---:|---:|---:|---:|---:|---:|---|---:|
| [2026-11-09 18:02](model-offloading/campaign-20261109T180247Z-c38f462b-offload-model-offloading-1/README.md) | 2,048 | coding | 9 | 53.9 / 60.2 | 1.62 | 53.3 | 178 / 198 | 3.30 | stop 9/9 | 9/9 |
| | 2,048 | math | 9 | 39.8 / 88.1 | 1.62 | 39.5 | 131 / 291 | 3.29 | stop 9/9 | 9/9 |
| | 2,048 | reasoning | 9 | 48.2 / 55.9 | 1.62 | 47.9 | 159 / 184 | 3.29 | stop 9/9 | 6/9 |

- **Reasons before answering**: 131 to 178 output tokens per answer at 3.30 tokens per second, so a short answer takes 40 to 54 s.
- **Quality 24/27**, with `reasoning-logic` failing on every repeat.
- **The rerun reproduces the flagged run**: every latency, throughput and quality figure is within 0.1 of the failed-warmup job in the earlier campaign.

#### Harness: KoboldCpp 1.124.2

Pinned prebuilt CUDA binary, started by the harness on loopback with `--usecublas --gpulayers 20 --threads 16`, OpenAI-compatible chat endpoint.

##### Model: `deepseek-r1-32b` (same SHA256-locked GGUF)

Hardware configuration `raider-windows`, 20 of 65 layers on GPU (confirmed in the backend log), 16 CPU threads.

| Run (UTC) | Output cap | Category | Requests | Wall s (median / p95) | First output s | First visible s | Output tokens (median / max) | Output tok/s | Finish reason | Quality |
|---|---:|---|---:|---:|---:|---:|---:|---:|---|---:|
| [2026-11-09 11:12](model-offloading/campaign-20261109T111225Z-8bf20361-offload-model-offloading-1/README.md) | 2,048 | coding | 9 | 114.0 / 131.7 | 1.09 | 105.7 | 398 / 460 | 3.49 | stop 9/9 | 6/9 |
| | 2,048 | math | 9 | 72.4 / 81.6 | 1.09 | 28.4 | 252 / 285 | 3.49 | stop 9/9 | 0/9 |
| | 2,048 | reasoning | 9 | 87.0 / 111.1 | 1.09 | 82.4 | 304 / 388 | 3.49 | stop 9/9 | 0/9 |

- **Same speed as Ollama.** 3.49 output tokens per second against 3.44, a 1.5 % difference, with the same 20-layer split and the same GPU memory.
- **Reasoning is reported separately** over the OpenAI-compatible endpoint, and token counts come from backend usage, so first-visible latency and throughput are directly comparable with Ollama.

##### Model: `qwen38-27b` (Qwen3.8-27B Q8_0, 29.0 GB GGUF, SHA256-locked)

Hardware configuration `raider-windows`, 20 of 66 layers on GPU (confirmed in the backend log), 16 CPU threads.

| Run (UTC) | Output cap | Category | Requests | Wall s (median / p95) | First output s | First visible s | Output tokens (median / max) | Output tok/s | Finish reason | Quality |
|---|---:|---|---:|---:|---:|---:|---:|---:|---|---:|
| [2026-11-09 14:52](model-offloading/campaign-20261109T145255Z-9e9ae761-offload-model-offloading-1/README.md) | 2,048 | coding | 9 | 25.9 / 31.3 | 0.59 | 25.6 | 91 / 111 | 3.54 | stop 9/9 | 9/9 |
| | 2,048 | math | 9 | 19.7 / 21.3 | 2.12 | 18.8 | 65 / 75 | 3.31 | stop 9/9 | 9/9 |
| | 2,048 | reasoning | 9 | 25.0 / 30.5 | 0.89 | 24.4 | 88 / 107 | 3.51 | stop 9/9 | 6/9 |

- **Same token rate as Ollama, longer answers.** 3.31 to 3.54 output tokens per second, but 65 to 91 tokens per answer against 57 to 67, so each answer takes 4 to 8 s longer.
- **A different prompt reaches the model.** KoboldCpp counted 33 prompt tokens where Ollama and LM Studio counted 76: its chat-completions adapter builds the prompt itself instead of using the template embedded in the GGUF. That is the likely reason for the longer reasoning.

##### Model: `gemma3-27b` (gemma-3-27b-it Q8_0, 28.7 GB GGUF, SHA256-locked)

Hardware configuration `raider-windows`, 20 of 63 layers on GPU (confirmed in the backend log), 16 CPU threads.

| Run (UTC) | Output cap | Category | Requests | Wall s (median / p95) | First output s | First visible s | Output tokens (median / max) | Output tok/s | Finish reason | Quality |
|---|---:|---|---:|---:|---:|---:|---:|---:|---|---:|
| [2026-11-09 17:14](model-offloading/campaign-20261109T171430Z-c1c4ab49-offload-model-offloading-1/README.md) | 2,048 | coding | 9 | 1.3 / 2.2 | 0.57 | 0.6 | 4 / 7 | 3.10 | stop 9/9 | 9/9 |
| | 2,048 | math | 9 | 1.1 / 53.9 | 0.57 | 0.6 | 3 / 194 | 2.90 | stop 9/9 | 6/9 |
| | 2,048 | reasoning | 9 | 3.8 / 10.5 | 0.58 | 0.6 | 13 / 37 | 3.39 | stop 9/9 | 3/9 |

- **Same behavior as Ollama**: same prompt token counts, same answer lengths, same three failing tasks, wall times within 0.1 s.
- **Lower GPU utilization peak** (49 % against 86 %) with the same GPU memory. The cause is not established; with answers this short the one-second sampler sees little sustained load.

##### Model: `nemotron-nano-30b` (Nemotron-3-Nano-30B-A3B Q8_0, 33.6 GB GGUF, SHA256-locked)

Hardware configuration `raider-windows`, 20 of 53 layers on GPU (confirmed in the backend log), 16 CPU threads.

| Run (UTC) | Output cap | Category | Requests | Wall s (median / p95) | First output s | First visible s | Output tokens (median / max) | Output tok/s | Finish reason | Quality |
|---|---:|---|---:|---:|---:|---:|---:|---:|---|---:|
| [2026-11-09 17:49](model-offloading/campaign-20261109T174915Z-128e3dcf-offload-model-offloading-1/README.md) | 2,048 | coding | 9 | 0.6 / 7.1 | 0.58 | 0.6 | 2 / 196 | 3.53 | stop 9/9 | 3/9 |
| | 2,048 | math | 9 | 1.1 / 2.3 | 0.58 | 0.6 | 25 / 45 | 19.73 | stop 9/9 | 0/9 |
| | 2,048 | reasoning | 9 | 2.1 / 3.6 | 0.58 | 0.6 | 53 / 88 | 25.65 | stop 9/9 | 0/9 |

- **Quality collapses to 3/27 on the same weights.** No reasoning is reported separately, and math and reasoning answers are 25 to 53 tokens of visible text where the checks expect a bare answer. KoboldCpp counted 7 fewer prompt tokens than the other two harnesses, so its own chat adapter is the likely cause; outputs are not saved, so this was not confirmed by reading them.
- **Token rate is lower on paper** (3.5 to 25.7 tokens per second) because most answers are too short to measure a rate.

##### Model: `gemma4-31b` (gemma-4-31B-it Q8_0, 32.6 GB GGUF, SHA256-locked)

Hardware configuration `raider-windows`, 20 of 61 layers on GPU (confirmed in the backend log), 16 CPU threads.

| Run (UTC) | Output cap | Category | Requests | Wall s (median / p95) | First output s | First visible s | Output tokens (median / max) | Output tok/s | Finish reason | Quality |
|---|---:|---|---:|---:|---:|---:|---:|---:|---|---:|
| [2026-11-09 15:43](model-offloading/campaign-20261109T154341Z-1e8d354f-offload-model-offloading-1/README.md) | 2,048 | coding | 9 | 1.1 / 2.0 | 0.59 | 0.6 | 3 / 6 | 2.68 | stop 9/9 | 9/9 |
| | 2,048 | math | 9 | 0.8 / 1.4 | 0.58 | 0.6 | 2 / 4 | 2.45 | stop 9/9 | 9/9 |
| | 2,048 | reasoning | 9 | 0.8 / 3.8 | 0.58 | 0.6 | 2 / 12 | 2.63 | stop 9/9 | 3/9 |

- **The model answers without reasoning.** No reasoning text is reported and answers are 2 to 3 tokens, so each takes about one second: roughly 50 times faster than on Ollama for the same weights and the same GPU split.
- **One more task fails**: 21/27, with `reasoning-navigation` failing in addition to `reasoning-logic`.
- **Token rate is not meaningful** at this answer length. KoboldCpp counted 3 fewer prompt tokens than the other two harnesses: its chat adapter builds the prompt itself, which is the likely reason reasoning is not triggered.

#### Harness: LM Studio 0.4.28+2

Desktop app with its bundled llama.cpp runtime, model imported by hard link and loaded by the harness through `lms`, OpenAI-compatible chat endpoint. LM Studio takes GPU placement as a ratio; the run requested 0.308 (20 of 65 layers).

##### Model: `deepseek-r1-32b` (same SHA256-locked GGUF)

Hardware configuration `raider-windows`, GPU offload ratio 0.308. The layer count LM Studio actually placed is not in its log; peak GPU memory matches the other two harnesses.

| Run (UTC) | Output cap | Category | Requests | Wall s (median / p95) | First output s | First visible s | Output tokens (median / max) | Output tok/s | Finish reason | Quality |
|---|---:|---|---:|---:|---:|---:|---:|---:|---|---:|
| [2026-11-09 11:12](model-offloading/campaign-20261109T111225Z-8bf20361-offload-model-offloading-1/README.md) | 2,048 | coding | 9 | 145.5 / 165.0 | 1.20 | 134.7 | 378 / 428 | 2.60 | stop 9/9 | 0/9 |
| | 2,048 | math | 9 | 99.5 / 115.7 | 1.18 | 36.4 | 259 / 301 | 2.60 | stop 9/9 | 0/9 |
| | 2,048 | reasoning | 9 | 139.7 / 290.0 | 1.19 | 138.9 | 363 / 749 | 2.60 | stop 9/9 | 3/9 |

- **About 25 % slower than the other two harnesses**: 2.60 output tokens per second against 3.44 to 3.49, on the same weights and the same GPU memory.
- **Much more host memory.** The backend process tree peaked at 35.7 GiB resident against 23.7 to 25.0 GiB, roughly the whole 32.4 GiB file plus runtime, and system RAM peaked at 46.9 GiB. Peak GPU utilization was 34 % against 95 to 100 %. The cause is not established; thread count and memory-mapping defaults were left at LM Studio's own values, which is the likely place to look.
- **Longer answers on reasoning tasks.** One request ran to 749 tokens and 290 s, which sets the p95.

##### Model: `qwen38-27b` (Qwen3.8-27B Q8_0, 29.0 GB GGUF, SHA256-locked)

Hardware configuration `raider-windows`, GPU offload ratio 0.303 (20 of 66 layers requested; the placed layer count is not in the log). This is the second attempt: the first failed before any request because LM Studio had not yet indexed the freshly imported file.

| Run (UTC) | Output cap | Category | Requests | Wall s (median / p95) | First output s | First visible s | Output tokens (median / max) | Output tok/s | Finish reason | Quality |
|---|---:|---|---:|---:|---:|---:|---:|---:|---|---:|
| [2026-11-09 14:52](model-offloading/campaign-20261109T145255Z-9e9ae761-offload-model-offloading-1/README.md) | 2,048 | coding | 9 | 7.7 / 18.8 | 0.54 | 7.3 | 48 / 111 | 5.93 | stop 9/9 | 9/9 |
| | 2,048 | math | 9 | 7.2 / 11.6 | 0.55 | 6.8 | 48 / 80 | 6.80 | stop 9/9 | 9/9 |
| | 2,048 | reasoning | 9 | 9.1 / 13.5 | 0.55 | 9.1 | 51 / 86 | 6.40 | stop 9/9 | 6/9 |

- **Fastest harness for this model**: 5.9 to 6.8 output tokens per second against about 3.5 on the other two, the reverse of the DeepSeek-R1-32B result. Token counts were cross-checked against output length, so the rate is real. The cause is not established.
- **Still the most host memory.** Backend 33.1 GiB resident against 20.4 to 23.4 GiB, peak system RAM 44.0 GiB, and about 0.5 GiB more GPU memory than the other two.

##### Model: `gemma3-27b` (gemma-3-27b-it Q8_0, 28.7 GB GGUF, SHA256-locked)

Hardware configuration `raider-windows`, GPU offload ratio 0.317 (20 of 63 layers requested; the placed layer count is not in the log).

| Run (UTC) | Output cap | Category | Requests | Wall s (median / p95) | First output s | First visible s | Output tokens (median / max) | Output tok/s | Finish reason | Quality |
|---|---:|---|---:|---:|---:|---:|---:|---:|---|---:|
| [2026-11-09 17:14](model-offloading/campaign-20261109T171430Z-c1c4ab49-offload-model-offloading-1/README.md) | 2,048 | coding | 9 | 1.9 / 3.0 | 0.80 | 0.8 | 4 / 7 | 2.11 | stop 9/9 | 9/9 |
| | 2,048 | math | 9 | 1.6 / 48.3 | 0.80 | 0.8 | 3 / 133 | 1.98 | stop 9/9 | 6/9 |
| | 2,048 | reasoning | 9 | 23.8 / 34.2 | 0.79 | 0.8 | 65 / 94 | 2.73 | stop 9/9 | 3/9 |

- **Longer reasoning-category answers.** 65 tokens and 23.8 s at the median against 13 tokens and 3.9 s on the other two harnesses; coding and math match them. Quality is unchanged, so the extra text does not help.
- **About 8 GiB more host memory**: 28.9 GiB resident against 20.1 to 20.6 GiB, again roughly the whole model file.

##### Model: `nemotron-nano-30b` (Nemotron-3-Nano-30B-A3B Q8_0, 33.6 GB GGUF, SHA256-locked)

Hardware configuration `raider-windows`, GPU offload ratio 0.377 (20 of 53 layers requested; the placed layer count is not in the log).

| Run (UTC) | Output cap | Category | Requests | Wall s (median / p95) | First output s | First visible s | Output tokens (median / max) | Output tok/s | Finish reason | Quality |
|---|---:|---|---:|---:|---:|---:|---:|---:|---|---:|
| [2026-11-09 17:49](model-offloading/campaign-20261109T174915Z-128e3dcf-offload-model-offloading-1/README.md) | 2,048 | coding | 9 | 4.3 / 12.9 | 0.16 | 4.2 | 63 / 192 | 14.74 | stop 9/9 | 9/9 |
| | 2,048 | math | 9 | 4.5 / 5.8 | 0.16 | 4.3 | 66 / 85 | 14.68 | stop 9/9 | 9/9 |
| | 2,048 | reasoning | 9 | 6.8 / 9.1 | 0.16 | 6.7 | 100 / 135 | 14.69 | stop 9/9 | 6/9 |

- **Little or no GPU offload happened.** Peak GPU memory was 2,048 MiB for the whole job against 14.6 to 14.9 GiB on the other two harnesses, and the backend held 33.9 GiB of RAM, the whole model. The requested ratio of 0.377 was accepted without an error. The cause is not established.
- **Half the Ollama token rate**: 14.7 tokens per second against 29.8, consistent with running on CPU. Quality is the same 24/27.

##### Model: `gemma4-31b` (gemma-4-31B-it Q8_0, 32.6 GB GGUF, SHA256-locked)

Hardware configuration `raider-windows`, GPU offload ratio 0.328 (20 of 61 layers requested; the placed layer count is not in the log).

| Run (UTC) | Output cap | Category | Requests | Wall s (median / p95) | First output s | First visible s | Output tokens (median / max) | Output tok/s | Finish reason | Quality |
|---|---:|---|---:|---:|---:|---:|---:|---:|---|---:|
| [2026-11-09 15:43](model-offloading/campaign-20261109T154341Z-1e8d354f-offload-model-offloading-1/README.md) | 2,048 | coding | 9 | 65.9 / 89.0 | 2.17 | 65.1 | 163 / 220 | 2.48 | stop 9/9 | 9/9 |
| | 2,048 | math | 9 | 52.3 / 162.3 | 2.17 | 51.9 | 129 / 401 | 2.47 | stop 9/9 | 9/9 |
| | 2,048 | reasoning | 9 | 59.7 / 73.1 | 2.15 | 59.3 | 148 / 181 | 2.48 | stop 9/9 | 6/9 |

- **Slower than Ollama**: 2.48 output tokens per second against 3.30, the same direction as DeepSeek-R1-32B and the opposite of Qwen 3.8 27B. Answers take 52 to 66 s; one math request ran to 401 tokens and 162 s.
- **About 10 GiB more host memory**: 34.8 GiB resident against 22.8 to 24.6 GiB. Quality matches Ollama at 24/27.

#### `deepseek-r1-32b` across harnesses (2026-11-09, 2,048 cap, same GGUF, same 20-layer split)

| Harness | Output tok/s | Wall s (coding / math / reasoning) | First visible s (coding / math / reasoning) | Backend RSS | Peak system RAM | Peak GPU memory | Peak GPU utilization | Peak GPU power | Errors | Quality |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Ollama 0.40.15 | 3.44 | 119.7 / 70.4 / 88.2 | 107.8 / 25.8 / 83.3 | 25.0 GiB | 37.4 GiB | 12,063 MiB | 95 % | 43.5 W | 0/27 | 3/27 |
| KoboldCpp 1.124.2 | 3.49 | 114.0 / 72.4 / 87.0 | 105.7 / 28.4 / 82.4 | 23.7 GiB | 36.3 GiB | 12,161 MiB | 100 % | 44.8 W | 0/27 | 6/27 |
| LM Studio 0.4.28+2 | 2.60 | 145.5 / 99.5 / 139.7 | 134.7 / 36.4 / 138.9 | 35.7 GiB | 46.9 GiB | 12,103 MiB | 34 % | 36.2 W | 0/27 | 3/27 |

- **All three harnesses serve the over-VRAM model without errors or paging.** No swap-in or swap-out was recorded in any job.
- **Ollama and KoboldCpp are interchangeable on speed and memory** for this model. LM Studio at its defaults costs a quarter of the throughput and about 11 GiB more RAM.
- **Quality differences between harnesses are formatting, not capability.** Passes come in whole tasks: Ollama passes one coding task, KoboldCpp passes two, LM Studio passes one reasoning task, each on all three repeats. The weights are identical, so the spread reflects how each harness's template and sampling defaults shape the final line that the `exact` check reads.

#### `qwen38-27b` across harnesses (2026-11-09, 2,048 cap, same GGUF, 20 of 66 layers requested)

| Harness | Output tok/s | Wall s (coding / math / reasoning) | Output tokens per answer (coding / math / reasoning) | Backend RSS | Peak system RAM | Peak GPU memory | Peak GPU utilization | Peak GPU power | Errors | Quality |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Ollama 0.40.15 | 3.56 | 18.7 / 16.0 / 16.8 | 67 / 57 / 60 | 23.4 GiB | 35.1 GiB | 9,849 MiB | 90 % | 47.2 W | 0/27 | 24/27 |
| KoboldCpp 1.124.2 | 3.51 | 25.9 / 19.7 / 25.0 | 91 / 65 / 88 | 20.4 GiB | 31.9 GiB | 10,152 MiB | 87 % | 44.9 W | 0/27 | 24/27 |
| LM Studio 0.4.28+2 | 6.40 | 7.7 / 7.2 / 9.1 | 48 / 48 / 51 | 33.1 GiB | 44.0 GiB | 10,581 MiB | 100 % | 38.8 W | 0/27 | 24/27 |

- **Quality is identical on all three harnesses**: 24/27, with the same task failing everywhere. Unlike DeepSeek-R1-32B, this model ends with the bare answer the `exact` check expects.
- **Harness ranking is model-dependent.** LM Studio is the slowest of the three for DeepSeek-R1-32B and the fastest for Qwen 3.8 27B, so no harness can be called faster in general from these two models.
- **No paging** in any job.

#### `gemma3-27b` across harnesses (2026-11-09, 2,048 cap, same GGUF, 20 of 63 layers requested)

| Harness | Output tok/s | Wall s (coding / math / reasoning) | Output tokens per answer (coding / math / reasoning) | Backend RSS | Peak system RAM | Peak GPU memory | Peak GPU utilization | Peak GPU power | Errors | Quality |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Ollama 0.40.15 | 2.83 | 1.4 / 1.2 / 3.9 | 4 / 3 / 13 | 20.6 GiB | 32.4 GiB | 11,222 MiB | 86 % | 47.6 W | 0/27 | 18/27 |
| KoboldCpp 1.124.2 | 3.18 | 1.3 / 1.1 / 3.8 | 4 / 3 / 13 | 20.1 GiB | 32.0 GiB | 11,512 MiB | 49 % | 44.2 W | 0/27 | 18/27 |
| LM Studio 0.4.28+2 | 2.11 | 1.9 / 1.6 / 23.8 | 4 / 3 / 65 | 28.9 GiB | 40.0 GiB | 11,267 MiB | 57 % | 38.1 W | 0/27 | 18/27 |

- **The fastest model to answer so far, and the least accurate of the non-DeepSeek models**: one to four seconds per answer on Ollama and KoboldCpp, 18/27 on every harness.
- **Ollama and KoboldCpp are interchangeable** for this model. LM Studio costs about 20 s on reasoning-category answers and about 8 GiB of RAM.
- **No errors and no paging** in any job.

#### `nemotron-nano-30b` across harnesses (2026-11-09, 2,048 cap, same GGUF, 20 of 53 layers requested)

| Harness | Output tok/s | Wall s (coding / math / reasoning) | Output tokens per answer (coding / math / reasoning) | Backend RSS | Peak system RAM | Peak GPU memory | Peak GPU utilization | Peak GPU power | Errors | Quality |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Ollama 0.40.15 | 29.82 | 2.5 / 2.1 / 3.1 | 73 / 62 / 92 | 20.7 GiB | 32.4 GiB | 14,634 MiB | 92 % | 51.6 W | 0/27 | 24/27 |
| KoboldCpp 1.124.2 | 19.73 | 0.6 / 1.1 / 2.1 | 2 / 25 / 53 | 19.9 GiB | 31.7 GiB | 14,884 MiB | 83 % | 48.3 W | 0/27 | 3/27 |
| LM Studio 0.4.28+2 | 14.71 | 4.3 / 4.5 / 6.8 | 63 / 66 / 100 | 33.9 GiB | 44.9 GiB | 2,048 MiB | 93 % | 34.2 W | 0/27 | 24/27 |

- **Fastest model measured that still passes 24/27**: 2 to 3 s per answer on Ollama.
- **Harness choice changes the result more than for any other model so far.** Ollama is fast and accurate, LM Studio is accurate but ran without the GPU, and KoboldCpp fails almost every check.
- **No errors and no paging** in any job.

#### `gemma4-31b` across harnesses (2026-11-09, 2,048 cap, same GGUF, 20 of 61 layers requested)

| Harness | Output tok/s | Wall s (coding / math / reasoning) | Output tokens per answer (coding / math / reasoning) | Backend RSS | Peak system RAM | Peak GPU memory | Peak GPU utilization | Peak GPU power | Errors | Quality |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Ollama 0.40.15 | 3.30 | 53.9 / 39.8 / 48.2 | 178 / 131 / 159 | 24.6 GiB | 36.2 GiB | 12,884 MiB | 94 % | 46.5 W | 0/27 | 24/27 |
| KoboldCpp 1.124.2 | 2.63 | 1.1 / 0.8 / 0.8 | 3 / 2 / 2 | 22.8 GiB | 34.3 GiB | 13,228 MiB | 92 % | 44.1 W | 0/27 | 21/27 |
| LM Studio 0.4.28+2 | 2.48 | 65.9 / 52.3 / 59.7 | 163 / 129 / 148 | 34.8 GiB | 46.1 GiB | 12,929 MiB | 100 % | 37.0 W | 0/27 | 24/27 |

- **Whether the model reasons depends on the harness.** Ollama and LM Studio trigger reasoning and pass 24/27 in 40 to 66 s per answer; KoboldCpp does not, answers in about a second and passes 21/27.
- **For a reasoning run, Ollama is a third faster than LM Studio** and uses about 10 GiB less RAM.
- **No errors and no paging** in the measured requests of any job.

### Experiment `llm-routing` (mode `decision`)

A router model picks the category of each prompt; decisions are scored against labels. Workload `original-routing-smoke`, 3 requests in each of the coding and math categories.

#### Harness: Ollama 0.40.15 (SystemOne API)

##### Models: `llm-eval-nimble:locked` and `llm-eval-tev1:locked`

Hardware configuration `raider-windows`, [run of 2026-11-08 03:57](llm-routing/campaign-20261108T035738Z-332b0246-routing-llm-routing-1/README.md).

| Model | Decisions | Accuracy | Macro F1 | Brier (median) | Router latency s (median / p95) |
|---|---:|---:|---:|---:|---:|
| `llm-eval-nimble:locked` | 6 | 1.00 | 1.00 | <0.0001 | 0.050 / 0.070 |
| `llm-eval-tev1:locked` | 6 | 1.00 | 1.00 | 0.0010 | 0.028 / 0.052 |

Both routers classify the smoke prompts perfectly with no abstentions or policy violations. Tev1 is roughly 1.8x faster; Nimble is better calibrated. Six labelled decisions per router is a smoke-level sample and does not establish routing quality on real traffic.

#### Harness: built-in `category` router (synthetic fixture)

Declared for hardware configuration `raider-ubuntu`, [run of 2026-11-08 01:38](llm-routing/campaign-20261108T013814Z-7ff2610d-routing-llm-routing-1/README.md): 2 synthetic requests, 0 errors. It validates the harness end to end (plan, run, report, status) at zero cost and establishes nothing about model quality or hardware performance. No real `raider-ubuntu` measurements exist yet.

## Conclusions by hardware configuration

### `raider-windows`

MSI Raider 18 HX AI A2XWJG, Intel Core Ultra 9 285HX, NVIDIA RTX 5090 Laptop (24,463 MiB, driver 610.74), 63.4 GiB RAM, Phison 2 TB NVMe (NTFS), Windows 11 Pro 10.0.26300, AC power, MSI Center "Best Performance", MUX in MSHybrid mode. VMware, the consumer Ollama tray app and Teams were closed before the measured runs.

- A 32B Q8_0 model is runnable with 20 GPU layers but slow: about 3.45 output tokens per second and 70 to 120 s per short answer on Ollama and KoboldCpp, with a 24 to 25 GiB resident backend and 35 to 37 GiB peak system RAM. No paging was observed on a 63.4 GiB host.
- Harness choice matters less than placement for that model, with one exception: LM Studio at its defaults delivered 2.60 tokens per second and used about 11 GiB more RAM than the other two.
- Qwen 3.8 27B Q8_0 with the same 20-layer split answers the smoke tasks in 7 to 26 s and passes 24 of 27 checks on every harness. Against DeepSeek-R1-32B it has the same or higher token rate, far fewer tokens per answer and about 2 GiB less GPU memory.
- **Best measured combination: Nemotron 3 Nano 30B on Ollama.** About 30 output tokens per second with 20 of 53 layers on GPU, 2 to 3 s per answer, 24 of 27 checks. Its mixture-of-experts design activates about 3B parameters per token, which is why it is eight to nine times faster than the dense models on the same split.
- Gemma 4 31B Q8_0 reasons before answering on Ollama and LM Studio: 24 of 27 checks at 40 to 66 s per answer. Gemma 3 27B Q8_0 answers in 1 to 4 s without reasoning and passes 18 of 27 on every harness.
- **The harness is not a neutral wrapper.** KoboldCpp builds its own chat prompt: Gemma 4 31B then skips reasoning (about one second per answer, 21 of 27) and Nemotron 3 Nano 30B drops to 3 of 27. LM Studio accepted the offload ratio for Nemotron 3 Nano 30B but used only 2,048 MiB of GPU memory and ran at half the Ollama token rate. Ollama is the only harness that gave the expected behavior for all five models.
- LM Studio always holds roughly the whole model file in RAM (29 to 36 GiB resident) where Ollama and KoboldCpp hold 20 to 25 GiB. It was faster than them only for Qwen 3.8 27B.
- GPU power peaked at 39 to 47 W against a 95 W default limit, so decode is bound by the CPU and host-memory side of the split (45 of 65 layers on CPU), not by the GPU. More GPU layers or a smaller quantization is the obvious lever; a `gpu_layers` sweep is the next experiment.
- Both routing candidates cost tens of milliseconds and are perfectly accurate on the smoke set.
- The three Ollama runs agree on every performance metric. Read the quality column as zero-information for DeepSeek-R1 on the smoke suites until a check tolerant of trailing prose, or a system prompt forcing terse output, is in place.
- Three harnesses and five offload models have published results so far. The remaining catalog candidates are being run on the same three harnesses and appear in the index as their bundles are published.

### `raider-ubuntu`

Synthetic fixture run only. No conclusions.

## Known tooling issues observed

- `scripts/readiness.ps1` reports Python as MISSING under Windows PowerShell 5.1 even when 3.12 is installed, because the embedded double quotes in its probe string are stripped. Running `py -3.12 scripts/readiness.py` directly works. The `model-downloader` readiness check likewise reports MISSING with `huggingface-hub==2.4.0` installed.
- Report bundles are written with CRLF line endings on Windows while `.gitattributes` normalizes them to LF, so `manifest.json` SHA256 values do not match the committed files.
- The managed LM Studio launcher imports a GGUF and loads it immediately. LM Studio indexes new files asynchronously, so the first load of a freshly imported model can fail with "Model not found"; a retry succeeds. Importing ahead of the campaign avoids it.
- Until 2026-11-09 the request client limited every socket read to 30 s. Ollama loads the model on the first request, and the 29 s load of Gemma 4 31B made the warmup request time out, which marked that job failed although its measured requests succeeded. The limit now applies to the connect only, and the job was rerun.
- LM Studio does not report how many layers it placed on the GPU. For Nemotron 3 Nano 30B it accepted a ratio of 0.377 and used almost no GPU memory, so a requested ratio is not evidence of placement; compare peak GPU memory instead.
- Ending any `ollama.exe` while a campaign runs, including the consumer tray app, can take the private pinned server with it and fails every outstanding request with connection refused.
