# Executive summary of results

Operator-written conclusions over the published result bundles in this directory. The index below is generated from the bundles (`llm-eval index-results`) and links to every result by hardware configuration, experiment, harness, model and date. The narrative that follows is organized the same way: experiment, then harness, then model. Figures are medians over measured (non-warmup) requests unless stated otherwise; per-campaign detail, raw measurements and resolved configurations are in each linked report.

## Results index

<!-- results-index:start -->

### Browse by category

| Category | Indexes (results) |
|---|---|
| Hardware configuration | [raider-ubuntu](index/hardware/raider-ubuntu.md) (1) · [raider-windows](index/hardware/raider-windows.md) (5) |
| Experiment | [llm-routing](index/experiment/llm-routing.md) (3) · [model-offloading](index/experiment/model-offloading.md) (3) |
| Harness | [category](index/harness/category.md) (1) · [ollama](index/harness/ollama.md) (5) |
| Model | [category](index/model/category.md) (1) · [deepseek-r1-32b](index/model/deepseek-r1-32b.md) (3) · [llm-eval-nimble:locked](index/model/llm-eval-nimble-locked.md) (1) · [llm-eval-tev1:locked](index/model/llm-eval-tev1-locked.md) (1) |
| Date (UTC) | [2026-11-08](index/date/2026-11-08.md) (6) |

### llm-routing: models by harness

Each cell links to the report of every published run of that model on that harness, newest first.

| Model | [category](index/harness/category.md) | [ollama](index/harness/ollama.md) |
|---|---|---|
| [category](index/model/category.md) | [2026-11-08 raider-ubuntu synthetic](llm-routing/campaign-20261108T013814Z-7ff2610d-routing-llm-routing-1/README.md) | – |
| [llm-eval-nimble:locked](index/model/llm-eval-nimble-locked.md) | – | [2026-11-08 raider-windows](llm-routing/campaign-20261108T035738Z-332b0246-routing-llm-routing-1/README.md) |
| [llm-eval-tev1:locked](index/model/llm-eval-tev1-locked.md) | – | [2026-11-08 raider-windows](llm-routing/campaign-20261108T035738Z-332b0246-routing-llm-routing-1/README.md) |

### model-offloading: models by harness

Each cell links to the report of every published run of that model on that harness, newest first.

| Model | [ollama](index/harness/ollama.md) |
|---|---|
| [deepseek-r1-32b](index/model/deepseek-r1-32b.md) | [2026-11-08 raider-windows cap 2048](model-offloading/campaign-20261108T140651Z-a0b0cfdf-offload-model-offloading-1/README.md)<br>[2026-11-08 raider-windows cap 256](model-offloading/campaign-20261108T035738Z-332b0246-offload-model-offloading-1/README.md)<br>[2026-11-08 raider-windows cap 256 failed](model-offloading/campaign-20261108T035331Z-833eafe8-offload-model-offloading-1/README.md) |

Full table and per-category pages: [results index](index/README.md).

<!-- results-index:end -->

## Results by experiment, harness and model

### Experiment `model-offloading` (mode `category-smoke`)

Model quality, performance and memory placement of an over-VRAM model on one serving harness. Workload: three short-answer tasks in each of the reasoning, coding and math categories, 3 repeats plus 1 warmup per task, 4,096-token context, one request at a time.

#### Harness: Ollama 0.40.15

Pinned archive install, private server on loopback, one loaded model, one parallel request.

##### Model: `deepseek-r1-32b` (DeepSeek-R1-Distill-Qwen-32B Q8_0, 34.8 GB GGUF, SHA256-locked)

Hardware configuration `raider-windows`, 20 of 65 layers on GPU, 16 CPU threads.

| Run (UTC) | Output cap | Category | Requests | Wall s (median / p95) | First output s | First visible s | Output tokens (median / max) | Output tok/s | Finish reason | Quality |
|---|---:|---|---:|---:|---:|---:|---:|---:|---|---:|
| [2026-11-08 03:57](model-offloading/campaign-20261108T035738Z-332b0246-offload-model-offloading-1/README.md) | 256 | coding | 9 | 73.9 / 73.9 | 0.90 | – | 256 / 256 | 3.47 | length 9/9 | 0/9 |
| | 256 | math | 9 | 70.1 / 73.8 | 0.89 | 25.6 | 243 / 256 | 3.47 | stop 6/9, length 3/9 | 0/9 |
| | 256 | reasoning | 9 | 75.4 / 76.5 | 0.92 | 30.2 (3 of 9) | 256 / 256 | 3.39 | length 9/9 | 0/9 |
| [2026-11-08 14:06](model-offloading/campaign-20261108T140651Z-a0b0cfdf-offload-model-offloading-1/README.md) | 2,048 | coding | 9 | 119.8 / 132.7 | 0.92 | 107.9 | 413 / 457 | 3.44 | stop 9/9 | 3/9 |
| | 2,048 | math | 9 | 70.3 / 82.5 | 0.90 | 25.7 | 243 / 285 | 3.46 | stop 9/9 | 0/9 |
| | 2,048 | reasoning | 9 | 88.1 / 112.5 | 0.92 | 83.2 | 304 / 388 | 3.45 | stop 9/9 | 0/9 |

| Run | Peak system RAM | Backend RSS | Peak GPU memory | GPU utilization | GPU power | GPU temperature | Swap used (in/out) |
|---|---:|---:|---:|---:|---:|---:|---|
| 256 cap | 34.1 GiB | 24.6 GiB | 12.1 GiB | 100 % | 39.5 W | 47 °C | 1.3 GiB (0 / 0) |
| 2,048 cap | 34.9 GiB | 25.0 GiB | 12.1 GiB | 94 % | 47.1 W | 47 °C | 1.0 GiB (0 / 0) |

- **Throughput is stable and cap-independent**: about 3.45 output tokens per second in both runs. Cold model load added 22.9 s to the first warmup.
- **The 256 cap truncates most answers.** 21 of 27 requests ended with `length` and 15 never produced visible text, their budget spent inside the model's `<think>` block. The six math requests that finished naturally still failed the exact checks.
- **At 2,048 the model stops on its own** after 243 to 460 tokens. "First visible" (time until non-reasoning text) is the user-facing latency: 26 s for math, 108 s for coding.
- **Quality 3/27 is an instruction-following score, not correctness.** A live reproduction of the arithmetic task returned the right answer as `\boxed{3973}` inside a LaTeX walkthrough, which fails the suite's `exact` check against `3973`. The suite's own `quality_scope` says it is not a reasoning benchmark.
- An [earlier attempt](model-offloading/campaign-20261108T035331Z-833eafe8-offload-model-offloading-1/README.md) on 2026-11-08 03:53 failed with 36 connection-refused requests because the private Ollama process was ended by hand. It is operator error and carries no measurement.

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

- A 32B Q8_0 model is runnable with 20 GPU layers but slow: about 3.45 output tokens per second and 70 to 120 s per short answer, with a 24 to 25 GiB resident backend and 35 GiB peak system RAM. No paging was observed on a 63.4 GiB host.
- GPU power peaked at 39 to 47 W against a 95 W default limit, so decode is bound by the CPU and host-memory side of the split (45 of 65 layers on CPU), not by the GPU. More GPU layers or a smaller quantization is the obvious lever; a `gpu_layers` sweep is the next experiment.
- Both routing candidates cost tens of milliseconds and are perfectly accurate on the smoke set.
- The two offload runs agree on every performance metric. Read the quality column as zero-information for DeepSeek-R1 on the smoke suites until a check tolerant of trailing prose, or a system prompt forcing terse output, is in place.
- Only Ollama and one offload model have published results so far. Other harnesses and models appear in the index as their bundles are published.

### `raider-ubuntu`

Synthetic fixture run only. No conclusions.

## Known tooling issues observed

- `scripts/readiness.ps1` reports Python as MISSING under Windows PowerShell 5.1 even when 3.12 is installed, because the embedded double quotes in its probe string are stripped. Running `py -3.12 scripts/readiness.py` directly works. The `model-downloader` readiness check likewise reports MISSING with `huggingface-hub==2.4.0` installed.
- Report bundles are written with CRLF line endings on Windows while `.gitattributes` normalizes them to LF, so `manifest.json` SHA256 values do not match the committed files.
- Ending any `ollama.exe` while a campaign runs, including the consumer tray app, can take the private pinned server with it and fails every outstanding request with connection refused.
