# llm-eval

A reproducible lab for evaluating **local LLMs larger than GPU VRAM** across inference platforms, hardware, and operating systems. Initial target: **[MSI Raider 18 HX AI A2XWJG-069US][msi-spec]**, [RTX 5090 **Laptop**][nvidia-laptop] 24 GiB, [Intel Core Ultra 9 285HX][intel-cpu] (8P + 16E), 64 GiB DDR5-6400, factory 2 TB NVMe plus [WD_BLACK SN7100 4 TB Gen4][sn7100].

**Status: benchmark harness and researched experiment plan, not measured laptop results.** The test suite uses small local fixtures. No large model has been downloaded or benchmarked by this project yet. Source evidence was checked on **2026-10-05**. Recommendations are hypotheses to test, not a measured quality/performance ranking.

[Downloads](#downloads-and-setup-references) · [How it works](#how-the-evaluation-works) · [Quick start](#start-here) · [Setup/run scripts](docs/WORKFLOWS.md) · [LiveBench categories](docs/LIVEBENCH.md) · [Report card](#evaluation-report-card) · [Model links](#model-links)

## Scope

Nine platforms: **[llama.cpp][llama-cpp], [ik_llama.cpp][ik-llama], [KTransformers][ktransformers], [Ollama][ollama], [KoboldCpp][koboldcpp], [Hugging Face Accelerate][accelerate], [AirLLM][airllm], [vLLM][vllm], and [Strata][strata]**.

Three environments: **[native Ubuntu 26.04][ubuntu-download]**, **[native Windows 11 Pro][windows-download]**, and **[Windows 11 Pro][windows-download] + [WSL2][wsl-install] + [Ubuntu 26.04][ubuntu-download]**. Native Windows means no WSL, Linux container, or compatibility layer. WSL measurements remain a separate environment even though their user space is Ubuntu.

The [model catalog](catalog/models.json) has **29 entries**: the original 24 selections/reference exclusions plus five [LiveBench-informed additions](docs/LIVEBENCH.md#additional-providers-and-models) from DeepSeek, Z.AI, Mistral AI, and Microsoft. It deliberately does not invent three qualifying releases for every provider. Downloadable weights do not automatically have an OSI-style software license; model-specific terms are recorded in the [model recommendations](docs/MODELS.md). Browse the [complete model link directory](#model-links) below.

## Downloads and setup references

| Component | Official download or documentation | Selection for this project |
|---|---|---|
| Ubuntu 26.04 native | [Release images and checksums][ubuntu-download] | Use the Desktop **AMD64/x86-64** image for this Intel laptop; record the exact point release and kernel. |
| Windows 11 Pro native | [Windows 11 download and media creation][windows-download] | Choose x64 installation media and the Pro edition using your license. |
| Windows 11 + WSL2 | [Microsoft WSL installation][wsl-install]; [Ubuntu 26.04 WSL images][ubuntu-download] | Use the AMD64 `.wsl` image or select the matching distribution; record the WSL and guest versions. |
| NVIDIA GPU drivers | [Driver downloads][nvidia-drivers]; [Linux driver installation guide][nvidia-linux]; [CUDA on WSL guide][cuda-wsl] | Select the laptop GPU and OS. WSL uses the Windows host driver; do not install a Linux display driver inside WSL. |
| CUDA toolkit | [Versioned toolkit downloads][cuda-archive] | Use the version required by the selected backend; toolkit and GPU driver versions are separate observations. |
| MSI firmware and platform drivers | [Raider 18 HX AI support][msi-support] | Match the A2XWJG-069US hardware before choosing a package. |
| Python and environment | [Python downloads][python]; [venv documentation][venv]; [pip installation][pip] | Select Python 3.11–3.13 and isolate the harness from inference dependencies. |
| Command-line tools | [Git downloads][git]; [PowerShell installation][powershell] | Git is used in the clone example; PowerShell is one Windows shell option. |
| Build tools | [CMake](https://cmake.org/download/); [Visual Studio Build Tools](https://visualstudio.microsoft.com/downloads/#build-tools-for-visual-studio-2022) | Source recipes need a compiler/toolkit compatible with Blackwell. |
| LiveBench and grading | [Leaderboard][livebench]; [upstream code][livebench-code]; [published datasets][livebench-data]; [Docker Engine][docker]; [Docker Desktop][docker-desktop] | Optional upstream scoring uses a pinned scorer, supplied data snapshot and isolated regular grading. |
| Telemetry | [psutil documentation][psutil]; [NVIDIA System Management Interface][nvidia-smi] | The harness uses these to sample host and GPU observations. |
| Model files | [Hugging Face download guide][hf-download]; [model links](#model-links) | Download only the chosen variant at an immutable revision, then hash it with `llm_eval lock`. |

For platform-specific releases, build instructions, and dependencies, use the nine upstream project links in [Scope](#scope) and the project's [platform setup guide](docs/PLATFORMS.md). These links are starting points; record the actual versions used for each experiment.

## How the evaluation works

The harness validates a selected experiment, runs its workload, and records measurements. Unsupported catalog combinations are skipped; invalid configurations or artifacts fail preflight. The new [run scripts](docs/WORKFLOWS.md) can manage local servers or use an existing server; library adapters launch an isolated Python worker.

[View the evaluation workflow as a PNG](diagrams/evaluation-workflow.png).

HTTP adapters cover [llama.cpp][llama-cpp], [ik_llama.cpp][ik-llama], [KTransformers][ktransformers], [Ollama][ollama], [KoboldCpp][koboldcpp], [vLLM][vllm], and [Strata][strata]. Python workers cover [Accelerate][accelerate] and [AirLLM][airllm]. Reports exclude warmups and, by default, synthetic runs. Streaming timing and token accounting depend on what the backend actually exposes; see the [methodology](docs/METHODOLOGY.md).

### How models can exceed GPU VRAM

The inference runtime chooses weight placement and offload strategy; the evaluation harness observes it. This diagram shows possible data paths on the laptop, not a claim that every platform uses all paths.

[View the memory offload diagram as a PNG](diagrams/memory-offload.png).

With **CPU/GPU splitting**, some weights stay in system RAM and CPU kernels compute their layers or experts. With **layer or expert streaming**, a runtime transfers needed weights to the GPU; some configurations also fetch data from SSD during generation. The factory 2 TB drive remains available for the OS and other files; record the actual model/offload paths. SSD storage does not add RAM or VRAM, and these memory pools cannot simply be summed into one allocation. KV cache placement, temporary buffers, host copies, and disk traffic vary by backend. The Intel iGPU is part of the display configuration and is not an additional inference device in the current evaluation profiles.

Use the [memory budgets and disk-offload rules](docs/METHODOLOGY.md) to separate RAM-resident offload from disk-dependent runs. Under WSL2, the guest memory cap is inside the same physical 64 GiB, and Windows host memory must also be observed.

## Start here

Use [Python 3.11–3.13][python] in an isolated [virtual environment][venv]. The core harness has no runtime dependencies; [psutil][psutil] is required for real hardware runs. Install backend packages in separate environments, using versions validated for Blackwell and your OS. Installing the harness alone does not install an engine. Use the setup scripts below for an explicitly selected platform; optional model downloads require a manifest. GPU drivers remain operator-managed.

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

4. Copy the appropriate [run examples](configs/runs/) to a local run file in the same directory. Fill the `REPLACE_...` values, hardware observations, paths, engine version, active chat-template SHA256, and placement settings. Choose an OS profile. Do not commit credentials or private output.
5. For server platforms, start **one local backend** and record its PID. Set the full endpoint path and actual served model name. For [Accelerate][accelerate]/[AirLLM][airllm], the harness starts a local worker in `worker_python` if supplied; install the project and backend dependencies in that interpreter first.
6. Run and summarize:

   ```bash
   python -m llm_eval run --config configs/runs/my-run.json --output results
   python -m llm_eval report --input results --output results/report
   ```

An unsupported platform/OS/model combination is recorded as skipped. Example files intentionally fail real-run preflight until provenance and setup details are filled. `--synthetic` is only for harness fixtures; its outputs are excluded from normal reports.

## Setup and run scripts

After the harness installation above, use the terminal wizard:

```bash
python scripts/setup.py --interactive
python scripts/run.py --interactive
```

Or preview an automated setup and then run a completed per-model configuration:

```bash
python scripts/setup.py --non-interactive --dry-run \
  --platform llama.cpp --os ubuntu-26.04-native \
  --models deepseek-r1-32b --categories reasoning,coding,math

python scripts/run.py --non-interactive --config configs/local/deepseek-32b.json \
  --benchmark category-smoke --categories reasoning,coding,math \
  --context 8192 --max-tokens 512 --threads 16 --gpu-layers 20
```

Remove `--dry-run` from setup to install. The run example requires prepared and hashed weights plus a completed config. [WORKFLOWS.md](docs/WORKFLOWS.md) links all **54 setup/run wrappers**, documents the three OS paths, optional downloads, platform-specific fields, multi-model runs and CLI flags. Native Windows KTransformers/vLLM wrappers report unsupported; model-specific conversions and compatibility checks remain explicit.

## LiveBench categories

The [current LiveBench leaderboard][livebench] defines these seven categories for release **2026-06-25**. Use their IDs with `--categories`, or select `all`.

| Category | CLI ID | Local evaluation scope |
|---|---|---|
| Reasoning | `reasoning` | Original deterministic reasoning smoke checks |
| Coding | `coding` | Code reading and fix selection; no code execution |
| Agentic Coding | `agentic_coding` | Static planning proxy in smoke mode; upstream agent execution requires opt-in |
| Mathematics | `math` | Arithmetic, algebra and probability smoke checks |
| Data Analysis | `data_analysis` | Join, aggregation and ordering smoke checks |
| Language | `language` | Meaning, spelling and event-order smoke checks |
| Instruction Following | `instruction_following` | Exact output and structured formatting smoke checks |

`--benchmark category-smoke` works through all eligible platform adapters and records timings plus category summaries. These 21 original checks **do not produce LiveBench scores**. `--benchmark livebench` runs the [pinned upstream scorer][livebench-code] against a supplied dataset snapshot through compatible local servers, with isolated regular grading. See [LiveBench workflow, task mapping, diagrams and score limitations](docs/LIVEBENCH.md). Upstream answer files contain full text and use their own result format.

The leaderboard review adds **[DeepSeek R1 Distill 32B][model-deepseek-r1-32b] (Q8), [DeepSeek R1 Distill 70B][model-deepseek-r1-70b] (Q4), [Mistral Small 3.1][model-mistral-small31] (BF16), [Phi-4 Reasoning Plus][model-phi4-reasoning-plus] (BF16), and conditional [GLM-4.5-Air][model-glm45-air] (Q4)**. Their historical leaderboard releases are recorded individually; they are not presented as one current ranking. BF16 selections probe capacity/precision; lower-bit controls may be faster and fit VRAM.

## What is implemented

| Capability | Implementation |
|---|---|
| Platform adapters | OpenAI-compatible SSE for [llama.cpp][llama-cpp], [ik_llama.cpp][ik-llama], [KTransformers][ktransformers], [KoboldCpp][koboldcpp], [vLLM][vllm], [Strata][strata]; native [Ollama][ollama] NDJSON; isolated Python workers for [Accelerate][accelerate] and [AirLLM][airllm] |
| Latency | Full request time; first streamed output and first visible text separately; worker generation time and client wall time separately |
| Throughput | Backend-reported token counts; whole-request output tokens/s; backend prefill/decode rates only when explicitly reported |
| Memory and device telemetry | Optional [psutil][psutil] system RAM/swap/process-tree RSS; [NVIDIA CLI][nvidia-smi] memory, utilization, power, temperature, clocks; missing data remain unknown |
| Reproducibility | Model file hashes, source revision, engine version, template/tokenizer identity, OS/driver observations, run config, suite hashes |
| Quality | Seven original category smoke suites, existing smoke/context/safety suites; optional upstream LiveBench with isolated regular grading and separate agentic opt-in |
| Reporting | JSONL requests, JSON metadata/telemetry, task/category JSON and CSV summaries; warmups excluded; incompatible cohorts kept separate |
| Setup and lifecycle | Pinned per-platform environments/builds or verified release assets; optional explicit model downloads; managed loopback server or external mode |
| Security defaults | Literal loopback endpoints, bounded responses/deadlines, credentials via environment references, verified artifacts, no generated-code execution in smoke mode; explicit upstream/container execution lane |

**Limits:** setup recipes and launch plans are implemented but GPU installations and inference remain untested on the target laptop. Model/engine support is not inferred from API compatibility. Direct-library workers expose neither streaming TTFT nor isolated decode rate. Initial performance runs are single-request and text-only. Standalone [SWE-bench][swe-bench]/[EvalPlus][evalplus] integrations and automated cold boots are not implemented. Strata conversion and KT representation selection remain model-specific preparation steps. See [validation status](docs/VALIDATION.md).

## Initial experiment priorities

Start with **[Llama 3.3 70B Q4_K_M][model-llama33-70b]** as a broadly supported dense offload anchor; **[Qwen3.5 35B-A3B Q8_0][model-qwen35-35b-moe]** as a sparse candidate; **[Gemma 4 31B Q8_0][model-gemma4-31b]** as a moderate dense candidate; and **[Laguna XS 2.1 Q8_0][model-laguna-xs21]** where backend support is verified. Run [Strata][strata]'s **[Qwen3.8-Flash-Next IQ2_XS][model-qwen38-flash-next-strata]** separately, then attempt equivalent-model comparisons only where another engine supports the same architecture and conversion.

Begin at 4K/8K configured context, one active request, 22 GiB GPU budget, and 52 GiB native CPU-weight budget. WSL's initial CPU-weight budget is 46 GiB with a 52 GiB guest cap. These are planning ceilings, not guarantees; kernel buffers, KV cache, loader peaks, and Windows host memory still need measurement. Run a matched 46 GiB native lane for fair OS comparisons.

The 120B class is conditional. No catalog entry promises that the sum of RAM and VRAM is a single usable allocation. Weights that expand to BF16, duplicate in RAM, or rely on uncontrolled paging can invalidate the configuration.

## Evaluation report card

**No laptop evaluation results have been recorded yet.** The matrix below tracks execution status, not performance. Each measured result must identify one exact model artifact, precision, platform version, OS build, and context size; one successful model does not qualify every model on that platform. See the [783-combination eligibility matrix](docs/evaluation-matrix.csv) for individual model gates.

| Platform | Ubuntu 26.04 native | Windows 11 Pro native | Windows 11 Pro + WSL2 |
|---|---|---|---|
| [llama.cpp][llama-cpp] | Not run | Not run | Not run |
| [ik_llama.cpp][ik-llama] | Not run | Not run | Not run |
| [KTransformers][ktransformers] | Not run | Unsupported | Not run |
| [Ollama][ollama] | Not run | Not run | Not run |
| [KoboldCpp][koboldcpp] | Not run | Not run | Not run |
| [Hugging Face Accelerate][accelerate] | Not run | Not run | Not run |
| [AirLLM][airllm] | Not run | Not run | Not run |
| [vLLM][vllm] | Not run | Unsupported | Not run |
| [Strata][strata] | Not run | Not run | Not run |

**Status key:** Not run = no target-laptop measurements; Unsupported = blocked by the current native-OS catalog entry. Conditional and unverified combinations still require compatibility checks. Future entries should link to an individual run report and distinguish Passed, Failed, and Skipped; none implies a quality ranking by itself.

### Category results placeholder

Copy this table per exact model/artifact/platform/OS/context. **No scores or laptop timings have been measured.** Keep local smoke rates and upstream LiveBench results in separate columns; never use either to fill the other.

| Category | Smoke checks passed / measured requests | LiveBench score / release / question coverage | Median first output / output tokens/s | Status |
|---|---|---|---|---|
| Reasoning | — | — | — | Not run |
| Coding | — | — | — | Not run |
| Agentic Coding | — (planning proxy) | — (actual agent tasks) | — | Not run |
| Mathematics | — | — | — | Not run |
| Data Analysis | — | — | — | Not run |
| Language | — | — | — | Not run |
| Instruction Following | — | — | — | Not run |

Link the raw session, artifact lock, category report or upstream judgment files, scorer revision and settings before replacing placeholders. Upstream scores do not provide the core harness timing metrics automatically.

### Result template for each evaluated configuration

Copy this card for each model/precision/platform/OS/context combination. Replace a dash only with an observed result; use `unavailable` for a metric the backend or sensor cannot provide. Do not substitute estimates or synthetic runs for measured results.

| Field | Result placeholder |
|---|---|
| Model, source revision, quantization, artifact hash | — |
| Platform and dependency versions | — |
| OS build, kernel/WSL version, NVIDIA driver, hardware/power profile | — |
| Context limit, actual prompt/output tokens, workload, warmups/repeats | — |
| Run status and completed/error request counts | Not run |
| Quality checks passed / applicable measured requests | — |
| Median first output / first visible answer latency | — |
| Median whole-request output tokens/s | — |
| Backend prefill / decode tokens/s, when reported | — |
| Peak sampled GPU VRAM / system RAM / backend process-tree RSS | — |
| Paging, OOM/timeouts, temperature/power observations | — |
| Windows host memory observations for WSL | — |
| Raw run artifacts and generated report | — |
| Hardware-fit verdict and comparison notes | Not assessed |

Generate reports with `python -m llm_eval report --input results --output results/report`. Keep measured configurations separate as described in the [methodology](docs/METHODOLOGY.md). The report card is a manually maintained summary; the CLI does not update this README. Result files are ignored by Git by default, so review them for private data before publishing any evidence links.

## Model links

Official publisher repositories for all catalog entries are listed below. These pages provide model cards, terms, and original weights; a listed quantization in this evaluation plan may require a separately sourced conversion. Use the [full recommendations](docs/MODELS.md) for target precision, task suitability, memory limits, and pinned source revisions. **Conditional entries are unverified on this laptop; excluded entries are reference-only.**

| Provider | Model cards and source weights |
|---|---|
| NVIDIA | [NVIDIA-Nemotron-3-Nano-30B-A3B-BF16][model-nemotron-nano-30b]; [Llama-3_3-Nemotron-Super-49B-v1_5][model-nemotron-super-49b]; [NVIDIA-Nemotron-3-Super-120B-A12B-NVFP4][model-nemotron-super-120b] (conditional) |
| OpenAI | [gpt-oss-120b][model-gpt-oss-120b] (conditional); [gpt-oss-safeguard-120b][model-gpt-oss-safeguard-120b] (conditional); [gpt-oss-20b][model-gpt-oss-20b] (in-VRAM control) |
| xAI | [grok-1][model-grok-1] (excluded); [grok-2][model-grok-2] (excluded) |
| Google | [gemma-4-31B-it][model-gemma4-31b]; [gemma-4-26B-A4B-it][model-gemma4-26b-moe]; [gemma-3-27b-it][model-gemma3-27b] |
| Meta | [Llama-3.3-70B-Instruct][model-llama33-70b]; [Llama-3.1-70B-Instruct][model-llama31-70b]; [Meta-Llama-3-70B-Instruct][model-llama3-70b] |
| Laguna (Poolside) | [Laguna-XS-2.1][model-laguna-xs21]; [Laguna-XS.2][model-laguna-xs2]; [Laguna-S-2.1][model-laguna-s21] (conditional) |
| Kimi (Moonshot) | [Kimi-Linear-48B-A3B-Instruct][model-kimi-linear-48b]; [Kimi-Dev-72B][model-kimi-dev-72b]; [Kimi-VL-A3B-Thinking-2506][model-kimi-vl-16b] (conditional) |
| DeepSeek | [R1-Distill-Qwen-32B][model-deepseek-r1-32b]; [R1-Distill-Llama-70B][model-deepseek-r1-70b] |
| Z.AI | [GLM-4.5-Air][model-glm45-air] (conditional) |
| Mistral AI | [Mistral-Small-3.1-24B-Instruct-2503][model-mistral-small31] (BF16 capacity test) |
| Microsoft | [Phi-4-reasoning-plus][model-phi4-reasoning-plus] (BF16 capacity test) |
| Qwen | [Qwen3.8-27B][model-qwen38-27b]; [Qwen3.5-35B-A3B][model-qwen35-35b-moe]; [Qwen3.5-122B-A10B][model-qwen35-122b-moe] (conditional) |

Additional Strata reference: [Qwen3.8-Flash-Next][model-qwen38-flash-next-strata] with the [reviewed Strata model/conversion guide][strata-models]. Its IQ2_XS conversion is a separate artifact from the publisher's original checkpoint.

## Repository layout

- [catalog/](catalog/): evidence, licenses, upstream revisions, candidate status, platform/OS support.
- [configs/hardware/](configs/hardware/), [configs/os/](configs/os/), [configs/runs/](configs/runs/): physical machine, OS budgets, editable experiments.
- [src/llm_eval/](src/llm_eval/): adapters, provenance, runner, telemetry, reporting, CLI.
- [workloads/](workloads/): original public smoke, seven category suites and context fixtures.
- [scripts/](scripts/): interactive/CLI setup and run entry points; platform/OS wrappers.
- [containers/livebench/](containers/livebench/): regular upstream grading image recipe.
- [docs/](docs/): model selection, setup, methodology, security, validation.
- [tests/](tests/): loopback protocol, timeout, tampering, matrix, and reporting tests.

The project's existing [MIT license](LICENSE) is preserved. Backend and model licenses remain independent.

[msi-spec]: https://storage-asset.msi.com/excelSku/us/nb/Raider%2018%20HX%20AI%20A2XWJG-069US.pdf
[nvidia-laptop]: https://www.nvidia.com/en-us/geforce/laptops/50-series/
[intel-cpu]: https://www.intel.com/content/www/us/en/products/sku/242297/intel-core-ultra-9-processor-285hx-36m-cache-up-to-5-50-ghz/specifications.html
[sn7100]: https://www.sandisk.com/products/ssd/internal-ssd/wd-black-sn7100-nvme-internal-ssd
[ubuntu-download]: https://releases.ubuntu.com/26.04/
[windows-download]: https://www.microsoft.com/en-us/software-download/windows11
[wsl-install]: https://learn.microsoft.com/en-us/windows/wsl/install
[nvidia-drivers]: https://www.nvidia.com/en-us/drivers/
[nvidia-linux]: https://docs.nvidia.com/datacenter/tesla/driver-installation-guide/
[cuda-wsl]: https://docs.nvidia.com/cuda/wsl-user-guide/index.html
[cuda-archive]: https://developer.nvidia.com/cuda-toolkit-archive
[msi-support]: https://us.msi.com/Laptop/Raider-18-HX-AI-A2XWX/support
[python]: https://www.python.org/downloads/
[venv]: https://docs.python.org/3/library/venv.html
[pip]: https://pip.pypa.io/en/stable/installation/
[git]: https://git-scm.com/downloads/
[powershell]: https://learn.microsoft.com/en-us/powershell/scripting/install/install-powershell
[psutil]: https://psutil.io/
[nvidia-smi]: https://docs.nvidia.com/deploy/nvidia-smi/index.html
[hf-download]: https://huggingface.co/docs/huggingface_hub/guides/download
[swe-bench]: https://github.com/SWE-bench/SWE-bench
[evalplus]: https://github.com/evalplus/evalplus
[strata-models]: https://github.com/Niko1221/Strata/blob/6f32ec070f23ced9f50e704d854d775da52591ab/docs/MODELS.md
[llama-cpp]: https://github.com/ggml-org/llama.cpp
[ik-llama]: https://github.com/ikawrakow/ik_llama.cpp
[ktransformers]: https://github.com/kvcache-ai/ktransformers
[ollama]: https://github.com/ollama/ollama
[koboldcpp]: https://github.com/LostRuins/koboldcpp
[accelerate]: https://github.com/huggingface/accelerate
[airllm]: https://github.com/lyogavin/airllm
[vllm]: https://github.com/vllm-project/vllm
[strata]: https://github.com/Niko1221/Strata
[model-nemotron-nano-30b]: https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16
[model-nemotron-super-49b]: https://huggingface.co/nvidia/Llama-3_3-Nemotron-Super-49B-v1_5
[model-nemotron-super-120b]: https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-NVFP4
[model-gpt-oss-120b]: https://huggingface.co/openai/gpt-oss-120b
[model-gpt-oss-safeguard-120b]: https://huggingface.co/openai/gpt-oss-safeguard-120b
[model-gpt-oss-20b]: https://huggingface.co/openai/gpt-oss-20b
[model-grok-1]: https://huggingface.co/xai-org/grok-1
[model-grok-2]: https://huggingface.co/xai-org/grok-2
[model-gemma4-31b]: https://huggingface.co/google/gemma-4-31B-it
[model-gemma4-26b-moe]: https://huggingface.co/google/gemma-4-26B-A4B-it
[model-gemma3-27b]: https://huggingface.co/google/gemma-3-27b-it
[model-llama33-70b]: https://huggingface.co/meta-llama/Llama-3.3-70B-Instruct
[model-llama31-70b]: https://huggingface.co/meta-llama/Llama-3.1-70B-Instruct
[model-llama3-70b]: https://huggingface.co/meta-llama/Meta-Llama-3-70B-Instruct
[model-laguna-xs21]: https://huggingface.co/poolside/Laguna-XS-2.1
[model-laguna-xs2]: https://huggingface.co/poolside/Laguna-XS.2
[model-laguna-s21]: https://huggingface.co/poolside/Laguna-S-2.1
[model-kimi-linear-48b]: https://huggingface.co/moonshotai/Kimi-Linear-48B-A3B-Instruct
[model-kimi-dev-72b]: https://huggingface.co/moonshotai/Kimi-Dev-72B
[model-kimi-vl-16b]: https://huggingface.co/moonshotai/Kimi-VL-A3B-Thinking-2506
[model-qwen38-27b]: https://huggingface.co/Qwen/Qwen3.8-27B
[model-qwen35-35b-moe]: https://huggingface.co/Qwen/Qwen3.5-35B-A3B
[model-qwen35-122b-moe]: https://huggingface.co/Qwen/Qwen3.5-122B-A10B
[model-qwen38-flash-next-strata]: https://huggingface.co/Qwen/Qwen3.8-Flash-Next

[livebench]: https://livebench.ai/
[livebench-code]: https://github.com/LiveBench/LiveBench/tree/8f8e5c381a16e3f24257776edd53471fe86f8091
[livebench-data]: https://huggingface.co/livebench
[docker]: https://docs.docker.com/engine/install/
[docker-desktop]: https://docs.docker.com/desktop/setup/install/windows-install/
[model-deepseek-r1-32b]: https://huggingface.co/deepseek-ai/DeepSeek-R1-Distill-Qwen-32B
[model-deepseek-r1-70b]: https://huggingface.co/deepseek-ai/DeepSeek-R1-Distill-Llama-70B
[model-glm45-air]: https://huggingface.co/zai-org/GLM-4.5-Air
[model-mistral-small31]: https://huggingface.co/mistralai/Mistral-Small-3.1-24B-Instruct-2503
[model-phi4-reasoning-plus]: https://huggingface.co/microsoft/Phi-4-reasoning-plus
