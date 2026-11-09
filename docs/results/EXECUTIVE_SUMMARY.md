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
| 1 | [lmstudio](index/harness/lmstudio.md) | [qwen38-27b](index/model/qwen38-27b.md) | 24/27 | 7.75 | 6.4 | [2026-11-09 cap 2048](model-offloading/campaign-20261109T145255Z-9e9ae761-offload-model-offloading-1/README.md) |
| 2 | [ollama](index/harness/ollama.md) | [qwen38-27b](index/model/qwen38-27b.md) | 24/27 | 16.8 | 3.56 | [2026-11-09 cap 2048](model-offloading/campaign-20261109T145255Z-9e9ae761-offload-model-offloading-1/README.md) |
| 3 | [koboldcpp](index/harness/koboldcpp.md) | [qwen38-27b](index/model/qwen38-27b.md) | 24/27 | 25 | 3.51 | [2026-11-09 cap 2048](model-offloading/campaign-20261109T145255Z-9e9ae761-offload-model-offloading-1/README.md) |

### Browse by category

| Category | Indexes (results) |
|---|---|
| Hardware configuration | [raider-ubuntu](index/hardware/raider-ubuntu.md) (1) · [raider-windows](index/hardware/raider-windows.md) (11) |
| Experiment | [llm-routing](index/experiment/llm-routing.md) (3) · [model-offloading](index/experiment/model-offloading.md) (9) |
| Harness | [category](index/harness/category.md) (1) · [koboldcpp](index/harness/koboldcpp.md) (2) · [lmstudio](index/harness/lmstudio.md) (2) · [ollama](index/harness/ollama.md) (7) |
| Model | [category](index/model/category.md) (1) · [deepseek-r1-32b](index/model/deepseek-r1-32b.md) (6) · [llm-eval-nimble:locked](index/model/llm-eval-nimble-locked.md) (1) · [llm-eval-tev1:locked](index/model/llm-eval-tev1-locked.md) (1) · [qwen38-27b](index/model/qwen38-27b.md) (3) |
| Date (UTC) | [2026-11-09](index/date/2026-11-09.md) (6) · [2026-11-08](index/date/2026-11-08.md) (6) |

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
- Qwen 3.8 27B Q8_0 with the same 20-layer split answers the smoke tasks in 7 to 26 s and passes 24 of 27 checks on every harness. It is the better fit for this machine of the two models measured: same or higher token rate, far fewer tokens per answer, about 2 GiB less GPU memory.
- LM Studio always holds roughly the whole model file in RAM (33 to 36 GiB resident) where Ollama and KoboldCpp hold 20 to 25 GiB. Its speed relative to them flipped between the two models.
- GPU power peaked at 39 to 47 W against a 95 W default limit, so decode is bound by the CPU and host-memory side of the split (45 of 65 layers on CPU), not by the GPU. More GPU layers or a smaller quantization is the obvious lever; a `gpu_layers` sweep is the next experiment.
- Both routing candidates cost tens of milliseconds and are perfectly accurate on the smoke set.
- The three Ollama runs agree on every performance metric. Read the quality column as zero-information for DeepSeek-R1 on the smoke suites until a check tolerant of trailing prose, or a system prompt forcing terse output, is in place.
- Three harnesses and two offload models have published results so far. The remaining catalog candidates are being run on the same three harnesses and appear in the index as their bundles are published.

### `raider-ubuntu`

Synthetic fixture run only. No conclusions.

## Known tooling issues observed

- `scripts/readiness.ps1` reports Python as MISSING under Windows PowerShell 5.1 even when 3.12 is installed, because the embedded double quotes in its probe string are stripped. Running `py -3.12 scripts/readiness.py` directly works. The `model-downloader` readiness check likewise reports MISSING with `huggingface-hub==2.4.0` installed.
- Report bundles are written with CRLF line endings on Windows while `.gitattributes` normalizes them to LF, so `manifest.json` SHA256 values do not match the committed files.
- The managed LM Studio launcher imports a GGUF and loads it immediately. LM Studio indexes new files asynchronously, so the first load of a freshly imported model can fail with "Model not found"; a retry succeeds. Importing ahead of the campaign avoids it.
- Ending any `ollama.exe` while a campaign runs, including the consumer tray app, can take the private pinned server with it and fails every outstanding request with connection refused.
