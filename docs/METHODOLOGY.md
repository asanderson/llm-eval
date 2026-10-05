# Experimental methodology

## Questions and lanes

1. Can this exact model artifact run with weights larger than the **24 GiB physical VRAM**, while the machine stays within **64 GiB physical RAM**?
2. What quality is preserved at that precision, and what are prompt-processing and sustained generation latency?
3. Which placement, engine, and OS give the best result on this actual laptop?

Use separate lanes: **offload** (weights exceed VRAM; no paging-dependent operation), **control** (weights may fit VRAM), **disk** (explicit weight streaming/offload). Strata's intrinsic PLE lookup is recorded separately; it is not equivalent to OS swap or streaming all model layers from disk. A smaller quantization that fits VRAM is useful but does not satisfy the offload criterion. A BF16 version of a small model is a precision/capacity experiment, not evidence that BF16 is the fastest way to run it.

`lock` calculates selected weight-file bytes, and a real offload run refuses artifacts <=24 GiB. This is a screening rule: serialized tensor layout, runtime conversion, and resident allocations differ. A directory containing duplicate precisions can make that check meaningless, so one selected variant per directory is mandatory. Exact source commit and SHA256 record provenance, not model safety.

## Hardware and OS controls

Record BIOS, NVIDIA driver, Windows build or Linux kernel, CUDA runtime/toolkit, engine build options, GPU power limit, AC state, MSI performance/fan mode, MUX/hybrid mode, SSD location/filesystem/free space, thermal state, and actual RAM speed. The configuration is the **Laptop** 5090 with 24 GiB, not the desktop 5090. Keep iGPU display use consistent. No AVX-512 or AMX assumptions for the 285HX; sweep 7, 8, 15, and 23 workers and discover P/E affinity before testing pinning. More threads need not be faster.

Run native Ubuntu directly on hardware, native Windows directly on hardware, and WSL2 as a distinct guest. WSL's RAM limit and Windows host allocations must be recorded. Initial `.wslconfig` experiment suggestion:

```ini
[wsl2]
memory=52GB
processors=24
```

Applying this requires shutting down WSL and restarting it; this project does not do that automatically. It can terminate other WSL work. Record existing swap policy rather than silently disabling it. Use the WSL ext4 filesystem, with its VHDX on the SN7100, and avoid `/mnt/c` for active weights. Run a **46 GiB CPU-weight-budget lane on all three OSes** for matched comparisons; compare native 52 GiB separately as best-achievable capacity. `max_memory` is a loader hint, not a process-wide memory limiter.

For WSL, collect Windows host memory alongside guest memory. Guest `psutil` cannot establish that Windows plus WSL stayed under 64 GiB. GPU power/clock sensors may be unavailable through WSL. Missing readings are null, not zero. Sources: [Microsoft WSL configuration](https://learn.microsoft.com/windows/wsl/wsl-config), [NVIDIA CUDA on WSL](https://docs.nvidia.com/cuda/wsl-user-guide/), [Intel CPU specifications](https://www.intel.com/content/www/us/en/products/sku/242297/intel-core-ultra-9-processor-285hx-36m-cache-up-to-5-50-ghz/specifications.html).

## Reproducible model and engine setup

Pin source model revision, quantized artifact revision, tokenizer, chat template, backend version/commit, conversion tools, dependencies, and generation parameters. Keep the exact same GGUF across engines that support it. An IQ, K-quant, MXFP4, NVFP4, FP8, and BF16 run are separate precision cohorts, even when a nominal bit count is similar. Different model checkpoints are never treated as engine speed comparisons.

The catalog pins original model metadata to public Hugging Face revisions. It does **not** pretend those revisions identify a community quantization. Select and hash that artifact separately. External server identity and active placement are operator attestations; the harness cannot prove what a separately started process loaded. Save backend startup information locally to verify tensor placement and quantized CPU kernels.

Record effective CPU threads, expert placement, GPU layers, KV type/location, prefill batch, context, cache settings, speculative decoding, and reasoning mode. Disable speculation for the initial controlled comparison; add a separate tuned lane afterward. Reasoning tokens can dominate apparent speed: preserve provider-native format and report visible-answer latency independently when available. gpt-oss requires Harmony. A safety classifier is not scored as a coding assistant.

## Workload schedule

1. **Compatibility smoke:** one prompt per supported cell; record unsupported/OOM/loader/format problems. Unknown support is not success.
2. **4K/8K baseline:** one request at a time, one warmup and at least three measured repetitions per task. Increase to 5–10 after a configuration is stable. Review output for correctness.
3. **Context sweep:** 4K, 8K, 16K, 32K configured context. Keep prompt+output within the model's native limit; Llama 3 70B is capped at 8K. Use actual tokenizer counts, not character approximations. `context-retrieval.json` labels character sizes honestly; select an appropriate subset for each run. Servers that silently truncate must be configured to reject overflow before a result is accepted.
4. **Thread/placement sweep:** change one control at a time. Record cache/expert hit rates from the backend where available. The harness does not currently automate these sweeps.
5. **Thermal stability:** run the chosen workload for 15–30 minutes on AC and inspect steady-state clocks, power, temperature, throughput, and memory. Run order should be randomized or alternated; allow thermal recovery between settings.
6. **Quality evaluation:** add licensed, versioned real task suites and human review. For coding, an isolated EvalPlus or SWE-bench environment is an extension, not currently implemented. Never execute generated code in the benchmark harness or a trusted host environment.

Repeated identical prompts may hit prefix caches. Set and record a cache policy; either disable prompt reuse on the server for uncached-prefill experiments or label the test cached. Warmup != cold-start measurement. Cold-load comparisons require an explicitly controlled fresh process and disk-cache state; do not call OS cache-dropping commands or reboot automatically.

## Metric definitions

| Field | Meaning |
|---|---|
| `client_request_wall_s` | Parent-observed request round trip, including worker IPC or API overhead |
| `elapsed_s` | API round trip for HTTP adapters; synchronized `generate()` interval including prefill for direct-library workers |
| `first_output_s` | First nonempty streamed content or reasoning delta; role-only frames do not count |
| `first_visible_s` | First visible content delta; separate from initial reasoning output |
| `output_tokens_per_wall_second` | Backend/count-confirmed generated tokens divided by `elapsed_s`; includes prefill, not a pure decode rate |
| `backend_decode_tps` | Only populated from an explicit backend decode count/duration |
| `backend_prefill_tps` | Only populated from an explicit backend prompt count/duration; prefix caching changes interpretation |
| `backend_load_s` | Ollama-reported load time when provided |
| `worker_load_s` | Direct-library model initialization time; separate from per-request measurements |
| `quality_pass` | Tiny deterministic smoke check; null for unscored prompts; not a claim of coding quality |

Streaming chunks are not tokens. Missing usage means unknown token throughput, never a characters/4 estimate. Direct-library adapters do not stream and therefore report TTFT and pure decode rates as null. They may decode raw reasoning into the text; do not compare their visible-answer metric to structured streaming without an architecture-aware parser.

Telemetry samples are approximate peaks. Process-tree RSS can double-count shared pages; system memory and disk counters include other apps. NVIDIA memory is device-wide. The runner records observed paging separately, and reports keep those runs in separate cohorts. It does not automatically stop an externally managed server on memory pressure. Monitor the laptop and start with conservative budgets.

Reports exclude warmups, keep failures in denominators, and group by model artifact, engine version, OS, task, precision/configuration, context, suite, template, driver/kernel, and paging observation. Median/p95 with three runs are descriptive only, not statistically robust confidence estimates. Do not rank different workloads or model families by raw tokens/s alone: tokenizers differ and shorter wrong answers can be faster.

## Category and LiveBench lanes

Seven original three-question category suites support early functionality and performance checks. They are not statistically broad quality evaluations and do not reuse LiveBench's questions. Agentic Coding in category-smoke is a static planning proxy. `report/category-summary.*` aggregates raw requests within each category/configuration, excluding warmups; errors remain in the applicable quality-check denominator. Benchmark type and suite hash are part of the comparison cohort.

The optional upstream LiveBench workflow pins the scorer and hashes local questions and test cases. It records release/coverage separately and keeps upstream answers/judgments out of local smoke aggregation. Regular code grading is isolated; actual Agentic Coding requires an additional opt-in. Managed servers stop before regular grading to release RAM. LiveBench generation/scoring settings, full-text retention and missing performance telemetry differ from the smoke lane; see [LIVEBENCH.md](LIVEBENCH.md). Never compare historical and current release scores as one ranking or infer quantized quality from an unquantized source-model leaderboard row.
