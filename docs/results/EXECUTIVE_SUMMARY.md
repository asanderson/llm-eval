# Executive summary of local campaigns (2026-11-08)

Operator-written summary of the campaigns run on 2026-11-07/08 with `llm-eval-lab 0.3.0` at code revision `3fc8f64`. Raw measurements, per-job reports and resolved configurations live under the gitignored `results/` tree named in each section; nothing here has been published through a results PR. Figures are medians over measured (non-warmup) requests unless stated otherwise.

## Hardware config `raider-windows`

MSI Raider 18 HX AI A2XWJG, Intel Core Ultra 9 285HX, NVIDIA RTX 5090 Laptop (24,463 MiB, driver 610.74), 63.4 GiB RAM, Phison 2 TB NVMe (NTFS), Windows 11 Pro 10.0.26300, AC power, MSI Center "Best Performance", MUX in MSHybrid mode. Pinned Ollama 0.40.15 served privately on `127.0.0.1:11435` with one loaded model and one parallel request. VMware, the consumer Ollama tray app and Teams were closed before the measured runs.

### Campaign `raider-windows-combined` (offload 256-token cap + routing)

`results/raider-win-20261107-225737/campaign-20261108T035738Z-332b0246`, status succeeded, 3 jobs, 0 errors. A first attempt (`results/raider-win-20261107-225331/campaign-20261108T035331Z-833eafe8`) failed with 36 connection-refused requests because the private Ollama process was killed by hand while closing the consumer Ollama tray; it is operator error and carries no measurement.

#### Experiment `model-offloading` v1, mode `category-smoke`

DeepSeek-R1-Distill-Qwen-32B Q8_0 (34.8 GB GGUF, SHA256-locked), 20 of 65 layers on GPU, 4,096-token context, 256-token output cap, 3 repeats + 1 warmup per task, workload `original-text-smoke-v1`.

| Category | Requests | Wall s (median / p95) | First output s | Output tok/s | Finish reason | Quality |
|---|---:|---:|---:|---:|---|---:|
| coding | 9 | 73.9 / 73.9 | 0.90 | 3.47 | length 9/9 | 0/9 |
| math | 9 | 70.1 / 73.8 | 0.89 | 3.47 | length 9/9 | 0/9 |
| reasoning | 9 | 75.4 / 76.5 | 0.92 | 3.39 | length 9/9 | 0/9 |

Telemetry peaks: system RAM used 34.1 GiB, backend process tree RSS 24.6 GiB, GPU memory 12.1 GiB, GPU utilization 100 %, GPU power 39.5 W, GPU 47 °C, swap flat at 1.3 GiB with zero swap-in/out. Cold model load added 22.9 s to the first warmup.

Conclusion: throughput and memory numbers are valid and stable (p95 within 5 % of median). The quality column is uninformative: every request hit the 256-token cap inside the model's `<think>` block, so no answer was ever emitted. This is a configuration limit of the example case, not a model or harness defect.

#### Experiment `llm-routing` v1, mode `decision`

Routers `llm-eval-nimble:locked` and `llm-eval-tev1:locked` queried through the Ollama SystemOne API, 3 requests per category, workload `original-routing-smoke`.

| Router | Decisions | Accuracy | Macro F1 | Brier (median) | Router latency s (median / p95) |
|---|---:|---:|---:|---:|---:|
| Nimble (`389a241fd7b8`) | 6 | 1.00 | 1.00 | <0.0001 | 0.050 / 0.070 |
| Tev1 (`25eff864a7d1`) | 6 | 1.00 | 1.00 | 0.0010 | 0.028 / 0.052 |

Conclusion: both routers classify the coding/math smoke prompts perfectly with no abstentions or policy violations. Tev1 is roughly 1.8x faster; Nimble is better calibrated. Six labelled decisions per router is a smoke-level sample and does not establish routing quality on real traffic.

### Campaign `raider-windows-offload-2048` (offload, 2048-token cap)

`results/raider-win-2048-20261108-090651/campaign-20261108T140651Z-a0b0cfdf`, status succeeded, 1 job, 0 errors, 61 minutes wall time. Identical to the offload experiment above except `max_output_tokens` raised from 256 to 2,048.

#### Experiment `model-offloading` v1, mode `category-smoke`

| Category | Requests | Wall s (median / p95) | First output s | First visible s | Output tokens (median / max) | Output tok/s | Finish reason | Quality |
|---|---:|---:|---:|---:|---:|---:|---|---:|
| coding | 9 | 119.8 / 132.7 | 0.92 | 107.9 | 413 / 457 | 3.44 | stop 9/9 | 3/9 |
| math | 9 | 70.3 / 82.5 | 0.90 | 25.7 | 243 / 285 | 3.46 | stop 9/9 | 0/9 |
| reasoning | 9 | 88.1 / 112.5 | 0.92 | 83.2 | 304 / 388 | 3.45 | stop 9/9 | 0/9 |

Telemetry peaks: system RAM used 34.9 GiB, backend RSS 25.0 GiB, GPU memory 12.1 GiB, GPU utilization 94 %, GPU power 47.1 W, GPU 47 °C, swap 1.0 GiB with zero swap-in/out.

Conclusion: lifting the cap removed truncation entirely; the model stops on its own at 243 to 460 tokens, so the 2,048 budget is never approached and the run cost one hour rather than the projected four to five. Decode speed is unchanged at 3.45 tok/s, confirming the 256-token run's throughput figures. "First visible" (time until non-reasoning text appears) is the user-facing latency for a reasoning model and ranges from 26 s (math) to 108 s (coding). Quality is 3 of 27: a live reproduction of the arithmetic task shows the model computing the correct answer and returning `\boxed{3973}` inside a LaTeX walkthrough, which fails the suite's `exact` check against `3973`. The smoke suite's deterministic checks therefore measure instruction following, not correctness, for a chain-of-thought model; the suite's own `quality_scope` note says it is not a reasoning benchmark.

### Overall conclusion for `raider-windows`

- A 32B Q8_0 model is runnable with 20 GPU layers but is slow: about 3.45 output tokens per second and 70 to 120 s per short answer, with a 24 to 25 GiB resident backend and 35 GiB peak system RAM. No paging was observed on a 63.4 GiB host once VMware and other trays were closed.
- GPU power peaked at 39 to 47 W against a 95 W default limit and 100 % utilization, so decode is bound by the CPU/host-memory side of the split (45 of 65 layers on CPU), not by the GPU. More GPU layers or a smaller quantization is the obvious lever; the next experiment should sweep `num_gpu`.
- Both routing candidates are effectively free (tens of milliseconds) and perfectly accurate on the smoke set.
- The combined and 2048-token campaigns agree on every performance metric. The quality column should be read as zero-information for DeepSeek-R1 on `original-text-smoke-v1` until the suite either strips reasoning and tolerates trailing prose or a system prompt forces terse output.

## Hardware config `raider-ubuntu`

### Campaign `routing-smoke` (synthetic)

`results/campaign-20261108T013814Z-7ff2610d`, status succeeded, 1 job (`llm-routing` v1, mode `decision`), 2 synthetic requests (one per category), 0 errors. Declared for hardware config `raider-ubuntu` but executed with test fixtures only on the Windows host.

Conclusion: validates the harness end to end (plan, run, report, status) at zero cost. By design it establishes nothing about model quality or hardware performance, and no real `raider-ubuntu` measurements exist yet.

## Known tooling issues observed

- `scripts/readiness.ps1` reports Python as MISSING under Windows PowerShell 5.1 even when 3.12 is installed, because the embedded double quotes in its probe string are stripped (`NameError: name 'data_filter' is not defined`). Running `py -3.12 scripts/readiness.py` directly works. Not fixed.
- Killing any `ollama.exe` while a campaign runs, including the consumer tray app, can take the private pinned server with it and fails every outstanding request with connection refused.
