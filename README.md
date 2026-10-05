# llm-eval

A reproducible lab for evaluating **local LLMs larger than GPU VRAM** across inference platforms, hardware, and operating systems. Initial target: **MSI Raider 18 HX AI A2XWJG-069US**, RTX 5090 **Laptop** 24 GiB, Intel Core Ultra 9 285HX (8P + 16E), 64 GiB DDR5-6400, factory 2 TB NVMe plus WD_BLACK SN7100 4 TB Gen4.

**Status: benchmark harness and researched experiment plan, not measured laptop results.** The test suite uses small local fixtures. No large model has been downloaded or benchmarked by this project yet. Source evidence was checked on **2026-10-05**. Recommendations are hypotheses to test, not a measured quality/performance ranking.

## Scope

Nine platforms: **llama.cpp, ik_llama.cpp, KTransformers, Ollama, KoboldCpp, Hugging Face Accelerate, AirLLM, vLLM, and Strata**.

Three environments: **native Ubuntu 26.04**, **native Windows 11 Pro**, and **Windows 11 Pro + WSL2 + Ubuntu 26.04**. Native Windows means no WSL, Linux container, or compatibility layer. WSL measurements remain a separate environment even though their user space is Ubuntu.

The catalog has **24 entries**: 21 prioritized selections across seven providers (including an OpenAI in-VRAM control), two xAI exclusions, and an additional Strata reference model. It deliberately does not invent three qualifying releases for every provider. Downloadable weights do not automatically have an OSI-style software license; model-specific terms are recorded separately.

## Start here

Use Python 3.11–3.13 in an isolated environment. The core harness has no runtime dependencies; `psutil` is required for real hardware runs. Install backend packages in separate environments, using versions validated for Blackwell and your OS. Installing the harness does not install any engine, download weights, or change GPU drivers.

```bash
git clone https://github.com/asanderson/llm-eval.git
cd llm-eval
python -m venv .venv
# Ubuntu/WSL: source .venv/bin/activate
# PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -e ".[telemetry]"
python -m llm_eval catalog
python -m llm_eval matrix --output results/matrix.csv
python -m llm_eval inventory --output results/inventory.json
python -m llm_eval prepare --platform llama.cpp --model llama33-70b \
  --os ubuntu-26.04-native --output configs/runs/my-run.json
python -m unittest discover -s tests -v
```

Commands assume the repository is the current directory. Otherwise set `--project-root /path/to/llm-eval` before the subcommand. Source-only testing also works with `PYTHONPATH=src`.

1. Read [model recommendations](docs/MODELS.md), [platform setup](docs/PLATFORMS.md), and [methodology](docs/METHODOLOGY.md).
2. Select one exact model/quantization variant and download it separately after reviewing its license. Keep only that variant in its artifact directory. Pin the download to an immutable commit. Do not download every precision from a repository.
3. Hash the materialized files. For community quantizations, record both the quantization repository and the original model:

   ```bash
   python -m llm_eval lock --root models/selected-artifact \
     --source-repo PUBLISHER/EXACT-QUANT-REPO \
     --source-revision FULL_40_CHARACTER_COMMIT \
     --base-model meta-llama/Llama-3.3-70B-Instruct \
     --precision Q4_K_M --output artifacts/selected.lock.json
   ```

4. Copy the appropriate `configs/runs/*.example.json` to a local run file in the same directory. Fill the `REPLACE_...` values, hardware observations, paths, engine version, active chat-template SHA256, and placement settings. Choose an OS profile. Do not commit credentials or private output.
5. For server platforms, start **one local backend** and record its PID. Set the full endpoint path and actual served model name. For Accelerate/AirLLM, the harness starts a local worker in `worker_python` if supplied; install the project and backend dependencies in that interpreter first.
6. Run and summarize:

   ```bash
   python -m llm_eval run --config configs/runs/my-run.json --output results
   python -m llm_eval report --input results --output results/report
   ```

An unsupported platform/OS/model combination is recorded as skipped. Example files intentionally fail real-run preflight until provenance and setup details are filled. `--synthetic` is only for harness fixtures; its outputs are excluded from normal reports.

## What is implemented

| Capability | Implementation |
|---|---|
| Platform adapters | OpenAI-compatible SSE for llama.cpp, ik_llama.cpp, KTransformers, KoboldCpp, vLLM, Strata; native Ollama NDJSON; isolated Python workers for Accelerate and AirLLM |
| Latency | Full request time; first streamed output and first visible text separately; worker generation time and client wall time separately |
| Throughput | Backend-reported token counts; whole-request output tokens/s; backend prefill/decode rates only when explicitly reported |
| Memory and device telemetry | Optional `psutil` system RAM/swap/process-tree RSS; NVIDIA CLI memory, utilization, power, temperature, clocks; missing data remain unknown |
| Reproducibility | Model file hashes, source revision, engine version, template/tokenizer identity, OS/driver observations, run config, suite hashes |
| Quality | Original deterministic arithmetic, structured-output, code-reading, and retrieval checks; unscored coding/reasoning prompts; separate safety-policy suite |
| Reporting | JSONL requests, JSON metadata/telemetry, grouped JSON and CSV summaries; warmups excluded; incompatible cohorts kept separate |
| Security defaults | Literal loopback endpoints, no redirects, bounded responses/deadlines, credentials only via environment references, no generated-code execution, no model download/install hooks |

**Limits:** engine installation is manual; model/engine support is not inferred from an OpenAI-compatible API. GPU tests are pending. Direct-library workers use nonstreaming `generate`, so TTFT and isolated decode rate are unavailable there. The initial harness is single-request, text-only, and does not execute generated code, score full SWE-bench/EvalPlus, or measure automated cold boots. See [validation status](docs/VALIDATION.md).

## Initial experiment priorities

Start with **Llama 3.3 70B Q4_K_M** as a broadly supported dense offload anchor; **Qwen3.5 35B-A3B Q8_0** as a sparse candidate; **Gemma 4 31B Q8_0** as a moderate dense candidate; and **Laguna XS 2.1 Q8_0** where backend support is verified. Run Strata's **Qwen3.8-Flash-Next IQ2_XS** separately, then attempt equivalent-model comparisons only where another engine supports the same architecture and conversion.

Begin at 4K/8K configured context, one active request, 22 GiB GPU budget, and 52 GiB native CPU-weight budget. WSL's initial CPU-weight budget is 46 GiB with a 52 GiB guest cap. These are planning ceilings, not guarantees; kernel buffers, KV cache, loader peaks, and Windows host memory still need measurement. Run a matched 46 GiB native lane for fair OS comparisons.

The 120B class is conditional. No catalog entry promises that the sum of RAM and VRAM is a single usable allocation. Weights that expand to BF16, duplicate in RAM, or rely on uncontrolled paging can invalidate the configuration.

## Repository layout

- `catalog/`: evidence, licenses, upstream revisions, candidate status, platform/OS support.
- `configs/hardware/`, `configs/os/`, `configs/runs/`: physical machine, OS budgets, editable experiments.
- `src/llm_eval/`: adapters, provenance, runner, telemetry, reporting, CLI.
- `workloads/`: original public smoke and context fixtures.
- `docs/`: model selection, setup, methodology, security, validation.
- `tests/`: loopback protocol, timeout, tampering, matrix, and reporting tests.

The project's existing MIT license is preserved. Backend and model licenses remain independent.
