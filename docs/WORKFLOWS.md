# Interactive setup and evaluation workflows

The [native Windows MSI Raider walkthrough](WINDOWS_RAIDER_WALKTHROUGH.md) follows a combined model-offloading and decision-routing campaign from installation through results PRs, including example terminal output and resume behavior.

With no legacy platform/config selection, `--interactive` opens the experiment campaign wizard. It selects experiments, cases, hardware configurations, phase ordering, concurrency and report publication. `--campaign FILE` runs a saved campaign through either script. Explicit legacy platform/config selections retain the workflows below. See [CAMPAIGNS.md](CAMPAIGNS.md) for local/SSH workers and [RESULTS.md](RESULTS.md) for automatic report PRs.

Use `python scripts/setup.py` and `python scripts/run.py` from the repository root. In a terminal they prompt for missing selections; use `--interactive` to force the wizard or `--non-interactive` for automation. **Every exposed option has a CLI argument**; run `--help` for the full list. Platform-specific setup/run wrappers supply platform and OS defaults and forward all remaining arguments. These are implementation-tested recipes, **not GPU-qualified installations**.

## Prerequisites and scope

Install [Python 3.11–3.13](https://www.python.org/downloads/) and the harness first, in a virtual environment:

```bash
python -m venv .venv
# Ubuntu / WSL: source .venv/bin/activate
# PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -e ".[telemetry]"
```

Use that interpreter for the scripts. `--python /path/to/python3.12` selects the interpreter used for the separate backend environments. Ubuntu's default interpreter may be newer than a backend's supported wheels; the scripts enforce 3.11–3.13 for those environments instead of modifying system Python. The shell wrappers honor `LLM_EVAL_PYTHON` as the path to the harness interpreter.

All engines need a working [NVIDIA driver](https://www.nvidia.com/en-us/drivers/) for the RTX 5090 **Laptop**. Source recipes also require [Git](https://git-scm.com/downloads/), [CMake](https://cmake.org/download/), a [CUDA toolkit](https://developer.nvidia.com/cuda-toolkit-archive) with `sm_120` support, and a compatible C++ compiler. Native Windows source builds should run in an x64 [Visual Studio Build Tools](https://visualstudio.microsoft.com/downloads/#build-tools-for-visual-studio-2022) developer shell. Linux needs the development compiler/toolchain and Python's venv support. LiveBench source installation additionally requires Git; grading image builds require Docker. `--dry-run` can preview another OS; actual installation rejects a mismatched host OS.

No script installs a driver/OS, requests administrator privileges, changes Secure Boot, edits firmware, partitions disks, changes the WSL memory cap, or modifies power settings. Follow [PLATFORMS.md](PLATFORMS.md) for driver and filesystem preparation. WSL wrappers run **inside the Ubuntu 26.04 guest** and use the Windows NVIDIA host driver. Keep model/offload data on the SN7100; within WSL prefer its ext4 filesystem over `/mnt/c`.

## Scripts for all platforms and operating systems

Each linked directory contains both setup and run scripts (`.sh` for Linux/WSL, `.ps1` for native Windows). The two unsupported Windows pairs have wrappers that fail with a clear explanation; they do not silently launch WSL. Script presence does not certify every catalog model or format.

| Platform | Ubuntu 26.04 native | Windows 11 native | Windows + WSL2 Ubuntu 26.04 |
|---|---|---|---|
| llama.cpp | [setup](../scripts/platforms/ubuntu-26.04-native/llama.cpp/setup.sh) · [run](../scripts/platforms/ubuntu-26.04-native/llama.cpp/run.sh) | [setup](../scripts/platforms/windows-11-native/llama.cpp/setup.ps1) · [run](../scripts/platforms/windows-11-native/llama.cpp/run.ps1) | [setup](../scripts/platforms/windows-11-wsl2-ubuntu-26.04/llama.cpp/setup.sh) · [run](../scripts/platforms/windows-11-wsl2-ubuntu-26.04/llama.cpp/run.sh) |
| ik_llama.cpp | [setup](../scripts/platforms/ubuntu-26.04-native/ik_llama.cpp/setup.sh) · [run](../scripts/platforms/ubuntu-26.04-native/ik_llama.cpp/run.sh) | [setup](../scripts/platforms/windows-11-native/ik_llama.cpp/setup.ps1) · [run](../scripts/platforms/windows-11-native/ik_llama.cpp/run.ps1) | [setup](../scripts/platforms/windows-11-wsl2-ubuntu-26.04/ik_llama.cpp/setup.sh) · [run](../scripts/platforms/windows-11-wsl2-ubuntu-26.04/ik_llama.cpp/run.sh) |
| ktransformers | [setup](../scripts/platforms/ubuntu-26.04-native/ktransformers/setup.sh) · [run](../scripts/platforms/ubuntu-26.04-native/ktransformers/run.sh) | [setup](../scripts/platforms/windows-11-native/ktransformers/setup.ps1) · [run](../scripts/platforms/windows-11-native/ktransformers/run.ps1) — unsupported | [setup](../scripts/platforms/windows-11-wsl2-ubuntu-26.04/ktransformers/setup.sh) · [run](../scripts/platforms/windows-11-wsl2-ubuntu-26.04/ktransformers/run.sh) |
| ollama | [setup](../scripts/platforms/ubuntu-26.04-native/ollama/setup.sh) · [run](../scripts/platforms/ubuntu-26.04-native/ollama/run.sh) | [setup](../scripts/platforms/windows-11-native/ollama/setup.ps1) · [run](../scripts/platforms/windows-11-native/ollama/run.ps1) | [setup](../scripts/platforms/windows-11-wsl2-ubuntu-26.04/ollama/setup.sh) · [run](../scripts/platforms/windows-11-wsl2-ubuntu-26.04/ollama/run.sh) |
| koboldcpp | [setup](../scripts/platforms/ubuntu-26.04-native/koboldcpp/setup.sh) · [run](../scripts/platforms/ubuntu-26.04-native/koboldcpp/run.sh) | [setup](../scripts/platforms/windows-11-native/koboldcpp/setup.ps1) · [run](../scripts/platforms/windows-11-native/koboldcpp/run.ps1) | [setup](../scripts/platforms/windows-11-wsl2-ubuntu-26.04/koboldcpp/setup.sh) · [run](../scripts/platforms/windows-11-wsl2-ubuntu-26.04/koboldcpp/run.sh) |
| accelerate | [setup](../scripts/platforms/ubuntu-26.04-native/accelerate/setup.sh) · [run](../scripts/platforms/ubuntu-26.04-native/accelerate/run.sh) | [setup](../scripts/platforms/windows-11-native/accelerate/setup.ps1) · [run](../scripts/platforms/windows-11-native/accelerate/run.ps1) | [setup](../scripts/platforms/windows-11-wsl2-ubuntu-26.04/accelerate/setup.sh) · [run](../scripts/platforms/windows-11-wsl2-ubuntu-26.04/accelerate/run.sh) |
| airllm | [setup](../scripts/platforms/ubuntu-26.04-native/airllm/setup.sh) · [run](../scripts/platforms/ubuntu-26.04-native/airllm/run.sh) | [setup](../scripts/platforms/windows-11-native/airllm/setup.ps1) · [run](../scripts/platforms/windows-11-native/airllm/run.ps1) | [setup](../scripts/platforms/windows-11-wsl2-ubuntu-26.04/airllm/setup.sh) · [run](../scripts/platforms/windows-11-wsl2-ubuntu-26.04/airllm/run.sh) |
| vllm | [setup](../scripts/platforms/ubuntu-26.04-native/vllm/setup.sh) · [run](../scripts/platforms/ubuntu-26.04-native/vllm/run.sh) | [setup](../scripts/platforms/windows-11-native/vllm/setup.ps1) · [run](../scripts/platforms/windows-11-native/vllm/run.ps1) — unsupported | [setup](../scripts/platforms/windows-11-wsl2-ubuntu-26.04/vllm/setup.sh) · [run](../scripts/platforms/windows-11-wsl2-ubuntu-26.04/vllm/run.sh) |
| strata | [setup](../scripts/platforms/ubuntu-26.04-native/strata/setup.sh) · [run](../scripts/platforms/ubuntu-26.04-native/strata/run.sh) | [setup](../scripts/platforms/windows-11-native/strata/setup.ps1) · [run](../scripts/platforms/windows-11-native/strata/run.ps1) | [setup](../scripts/platforms/windows-11-wsl2-ubuntu-26.04/strata/setup.sh) · [run](../scripts/platforms/windows-11-wsl2-ubuntu-26.04/strata/run.sh) |

### Interactive examples

```bash
python scripts/setup.py --interactive
python scripts/run.py --interactive
# Or preselect the platform and OS:
./scripts/platforms/ubuntu-26.04-native/llama.cpp/setup.sh --interactive
./scripts/platforms/ubuntu-26.04-native/llama.cpp/run.sh --interactive
```

```powershell
.\scripts\platforms\windows-11-native\llama.cpp\setup.ps1 --interactive
.\scripts\platforms\windows-11-native\llama.cpp\run.ps1 --interactive
```

The setup wizard selects a platform, OS, prefix, model IDs, category IDs, Python, build jobs, optional LiveBench support/image, and optional download manifest, then displays the installation plan. Model/category selections are saved as run defaults; **selecting a model alone does not download its weights**. A download requires an explicit manifest naming revision, files, destination, and license acknowledgement.

The run wizard selects models, category-smoke versus upstream LiveBench, categories, managed/external server mode, context/output limits, repetitions, threads, GPU layers, and output retention. With no config it asks for artifact provenance and hardware observations too. A model selector accepts comma-separated IDs printed by the wizard. Categories accept comma-separated IDs or `all`. For repeatability, keep completed per-model configurations in ignored `configs/local/` and pass them with `--config`; values can be overridden with flags. Interactive tuning defaults come from each selected model's own config (or its example/catalog defaults when creating one). Pressing Enter preserves that value, including context, repetitions, thread/layer placement and output retention. Explicit CLI options override those defaults for every selected model.

### Non-interactive examples

Preview setup without any writes/downloads:

```bash
python scripts/setup.py --non-interactive --dry-run \
  --platform llama.cpp --os ubuntu-26.04-native \
  --models deepseek-r1-32b,deepseek-r1-70b --categories reasoning,coding,math --jobs 8
```

Remove `--dry-run` to execute. This builds the pinned engine, creates its environment, and writes state under `.platforms/OS/PLATFORM/`. Source builds use CUDA architecture 120. Native Windows example:

```powershell
python scripts/setup.py --non-interactive --platform koboldcpp --os windows-11-native --models deepseek-r1-32b --categories all
```

Run one prepared model:

```bash
python scripts/run.py --non-interactive --config configs/local/deepseek-32b.json \
  --benchmark category-smoke --categories reasoning,coding,math \
  --context 8192 --max-tokens 512 --repeats 3 --warmups 1 \
  --threads 16 --gpu-layers 20 --output results
```

Run multiple prepared models **sequentially**, unloading the managed server between models:

```bash
python scripts/run.py --non-interactive \
  --config configs/local/deepseek-32b.json --config configs/local/deepseek-70b.json \
  --models deepseek-r1-32b,deepseek-r1-70b --categories all --continue-on-error
```

One invocation selects one platform and OS. Each config must match those selections and its model; configurations contain different artifact roots, locks, and placement. Shared artifact overrides are rejected for multiple models. Run separate sessions to compare platforms or OSes. Reuse the same eligible artifact, template and benchmark settings where possible.

`--non-interactive` never reads stdin. Missing required provenance/configuration fails with an actionable error. `--dry-run` prints a plan without installing, downloading, starting a server, or evaluating. It permits placeholder provenance for reviewing examples, so dry-run success does not imply a usable model. `--continue-on-error` continues after execution failures and returns a failing status if any fail; invalid global configuration still fails immediately. Exit codes: 0 success/plan/skips, 1 completed session with failed evaluations, 2 configuration/setup error or an evaluation stopped on failure, 130 cancellation.

## Installer recipes and state

Exact source revisions, package pins and release-asset SHA256 values live in [catalog/installers.json](../catalog/installers.json). They were selected on 2026-10-05 and must pass the target-laptop gate.

| Platform | Setup implementation | Managed run |
|---|---|---|
| llama.cpp / ik_llama.cpp | Clean immutable Git checkout, submodules, CMake CUDA build | `llama-server` with a locked GGUF, explicit context/layers/threads and loopback |
| KTransformers | Dedicated `kt-kernel` + `sglang-kt` environment; AVX2 selection and runtime check | SGLang's KT server with explicit method, CPU weight path, expert count and thread count |
| Ollama | SHA256-verified official archive extracted into the prefix | Private local service; import the selected GGUF through a generated Modelfile; cloud features disabled |
| KoboldCpp | SHA256-verified official executable | CUDA executable, explicit model/layers/context, no launcher UI |
| Accelerate | Pinned CUDA PyTorch, Transformers and Accelerate | Existing isolated worker, offline local model load and memory budgets |
| AirLLM | Pinned CUDA PyTorch, Transformers, Accelerate and AirLLM | Existing layer-streaming worker; explicit loader review and disk lane |
| vLLM | Dedicated pinned vLLM environment with its resolved PyTorch requirements | Local OpenAI server, one sequence, explicit CPU offload/context/VRAM fraction |
| Strata | Pinned source, pinned upstream requirements, portable AVX2/CUDA build | Local Python server using a reviewed prepared configuration and this prefix's engine executable |

Each prefix stores `installation-plan.json`, `state.json`, dependency freeze, optional LiveBench source/environment/freeze, and selection preferences. A repeated identical successful plan is reused. A different plan requires a new `--prefix`; existing source modifications are not discarded. Failed engine installs leave diagnostic state. Optional downloads/image builds can be retried; engine state can already be installed while an optional step has failed. No global services or login startup entries are registered. The Ollama artifact cache is private to the prefix and may require an additional copy of the model.

Python direct dependencies are version-pinned where the recipe controls them, and installed dependencies are captured. This is **not a fully hash-locked transitive supply chain**: package builds, wheels, source submodules and Docker base/dependency resolution require review. `--revision FULL_40_HEX_SHA` overrides a source recipe; repeated `--package name==version` replaces a Python recipe's package list. Use a fresh prefix and record why. Broad ranges/branches are rejected. A successful CUDA import does not validate every sm_120 quantization kernel; perform a real inference smoke test.

## Models, conversion, and run configuration

Copy a [run example](../configs/runs/) to `configs/local/`, fill all `REPLACE_...` values, and set the OS-specific RAM budget. The existing core command can prepare a starting configuration:

```bash
python -m llm_eval prepare --platform llama.cpp --model deepseek-r1-32b \
  --os ubuntu-26.04-native --output configs/local/deepseek-32b.json
```

Relative `artifact_root`, `artifact_lock`, `offload_dir` and `suite` paths resolve **relative to the config file**. Use absolute paths when moving an example. `launch.model_file`, model directories and prepared Strata configuration resolve inside the locked artifact root. Record the exact loaded tokenizer revision, template hash, backend version, placement, and hardware observations; examples intentionally fail real-run preflight.

To download explicitly during setup, copy [download.example.json](../configs/workflows/download.example.json), choose one immutable artifact repository/revision and its needed files, review its license, set `accept_license=true`, and use:

```bash
python scripts/setup.py --non-interactive --platform accelerate --os ubuntu-26.04-native \
  --models phi4-reasoning-plus --download-spec configs/local/download.json
```

Download destinations in that manifest resolve relative to the **current working directory**. A separate environment runs Hugging Face's pinned downloader, then hashes the artifact. Use `HF_TOKEN` in your local environment for gated access; never put it in JSON or CLI arguments. The manifest rejects mutable revisions, blanket repository globs, overlapping model directories, unacknowledged licenses, and locks placed inside the model directory. Select all GGUF shards or all required native checkpoint/config/tokenizer files for **one representation**; narrow patterns such as `*Q8_0*.gguf` or `*.safetensors` are supported. Downloads can be large; inspect total bytes and disk space first. The manifest does not perform quantization/conversion. Reuse existing artifacts with `llm_eval lock` instead if preferred.

GGUF runtimes and native Transformers runtimes require different representations; a GGUF is not a native checkpoint. Native BF16 70B weights do not meet a RAM-resident 64 GiB plan just because the config asks for offload. Lower-bit variants must actually remain compact in the selected CPU/GPU path.

### Platform launch fields

Use `--launch-options path.json` or a `launch` object in the run config. Examples are in [configs/workflows/](../configs/workflows/).

| Platform | Required launch fields / meaningful controls |
|---|---|
| llama.cpp, ik_llama.cpp, KoboldCpp, Ollama | `model_file` relative to artifact root; `threads` (1–24), `gpu_layers` (use explicit placement initially) |
| KTransformers | `model_dir`, `kt_weight_path` inside the artifact root; `kt_method` matching prepared weights (`BF16`, `FP8`, `GPTQ_INT4`, `RAWINT4`, or model-specific `LLAMAFILE`); `gpu_experts`, `threads`, `attention_backend` |
| vLLM | `model_dir` (default `.`), `cpu_offload_gb`; config `gpu_budget_gib` drives a fraction of the 24 GiB GPU |
| Strata | `strata_config`, plus config `reviewed_strata_config=true`; prepared file's absolute `exe` must equal installation state's `executable` |
| Accelerate / AirLLM | Worker `launch.threads` sets PyTorch/OMP/MKL thread counts; no HTTP server; use worker `dtype`, `loader_class`, reviewed-code/loader flags, and `allow_disk_offload` with `lane="disk"` where required |

KT's AVX2 path is supported by its [current tutorial](https://github.com/kvcache-ai/ktransformers/blob/a5d7ad90479c9e8bdee491c16bfd563fa9d70262/doc/en/kt-kernel/AVX2-Tutorial.md); it does not establish support for all models or wheels. The launcher forces AVX2 and disables AMX. Do not borrow AMX/AVX-512 server tuning for the 285HX. Thread count is configurable; test P-core-aware and mixed-core placement separately using the measured topology.

**Strata preparation remains model-specific.** Its setup wrapper builds the engine and dependencies. Prepare Qwen3.8-Flash-Next IQ2_XS using the [pinned upstream model guide](https://github.com/Niko1221/Strata/blob/6f32ec070f23ced9f50e704d854d775da52591ab/docs/MODELS.md) and reviewed conversion tools. This project does not run upstream's broad installer/download/update hooks automatically. Put the prepared files and reviewed server JSON within the artifact root; make `exe`, `cwd`, tokenizer and engine file paths absolute, point `exe` to this build, disable vision/MCP, record PLE and speculation settings, then hash the complete artifact directory. Engine arguments and referenced files are operator-reviewed, not automatically constrained by generic `--context`/`--threads` flags; configure those in the prepared JSON and keep the run metadata consistent. Only the catalog's Strata reference is eligible. Set `api_key_env` to a local secret variable and use loopback.

Managed servers use `127.0.0.1`; occupied ports cause an error. Startup waits for the backend HTTP readiness endpoint, preserves logs, and terminates the process it owns after a run or failure. Local worker environments come from installation state. Workers reload for each category run, and their load time is separate from inference time. On Windows, normal cleanup terminates the observed process tree; abrupt parent/system termination can leave children that require manual cleanup. Never kill unrelated inference processes.

`--server-mode external` uses a server you started and never stops it. Set its exact endpoint and PID in the config; verify loaded model, template and placement independently. `launch.extra_args` accepts an argument array for reviewed engine tuning, not a shell command; controlled network/model/execution options cannot be overridden there. This filter is not a general sandbox for untrusted engine flags.

## Results and memory limits

Sessions are placed under `results/session-TIMESTAMP-ID/`, with per-model/category run configs, metadata, request/telemetry files, backend logs, `session.json`, and `report/summary.*` plus `report/category-summary.*`. Warmups are excluded; category summaries aggregate raw measured requests and retain failed checks in their denominator. They keep incompatible settings/artifacts/benchmarks in separate cohorts. The README report card remains a manually reviewed summary, not an automatically published leaderboard.

Start at 4K/8K context, one request, a 22 GiB VRAM planning ceiling, and CPU-weight budgets of 52 GiB native / 46 GiB WSL (52 GiB guest cap). These are controls/attestations, **not universal hard process limits**; third-party servers may exceed them during loading or execution. Inspect real startup placement and telemetry. Stop on uncontrolled paging/OOM; record failed fits rather than claiming the SSD solved them. LiveBench agent containers add another working set; see [LIVEBENCH.md](LIVEBENCH.md). Real runs verify artifact hashes, selected OS, target NVIDIA GPU, telemetry availability and AC power before managed server startup. Native/WSL sensor limits and unknown AC state still require operator observations.

See [SECURITY.md](SECURITY.md), [METHODOLOGY.md](METHODOLOGY.md), and [VALIDATION.md](VALIDATION.md) for interpretation and remaining target-hardware gates.
