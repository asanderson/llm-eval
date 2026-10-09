# Check and install prerequisites on the test host

Run readiness **before setup or measurement**, on the machine and OS where the experiments will execute. It inventories required tools and libraries, lists missing or unusable dependencies, displays proposed commands, and asks `Install this now? [y/N]` for each supported installation. Answering `yes` installs that item and checks it again. A successful installer exit alone does not count as ready.

Use a Git checkout of this repository; a downloaded ZIP can bootstrap tools but must be replaced by a clone before campaigns can resolve their code revision. Run from its root. The entry scripts can start before the harness is installed:

| Test environment | Entry point |
|---|---|
| Native Windows 11 | `powershell -NoProfile -File .\scripts\readiness.ps1` |
| WSL2 with Ubuntu 26.04 | `bash scripts/readiness.sh` inside Ubuntu |
| Native Ubuntu 26.04 | `bash scripts/readiness.sh` |

Windows PowerShell 5.1 can run the bootstrap; the checker offers PowerShell 7.4+ for the documented workflows. If organizational execution policy prevents a local script from running, use an approved execution method; this script does not change policy. An already installed Python 3.11–3.13 can invoke `python scripts/readiness.py` directly. `LLM_EVAL_PYTHON` can select an executable for either wrapper.

## Check the combined Raider campaign

For the MSI Raider 18 HX AI with RTX 5090 Laptop 24 GiB and 64 GiB RAM, use the matching campaign. Each resolves one Ollama installation shared by the offloading case and both routing cases.

Native Windows:

```powershell
powershell -NoProfile -File .\scripts\readiness.ps1 --campaign configs/examples/raider-windows/campaign.json --json-output results/readiness-windows.json
```

Native Ubuntu:

```bash
bash scripts/readiness.sh --campaign configs/examples/raider-ubuntu/campaign.json --json-output results/readiness-ubuntu.json
```

WSL: first copy the six example JSON files into `configs/local/raider-wsl/` and replace `lock_root` in its inventory with the real Windows-shared directory as described in [the WSL walkthrough](WSL_RAIDER_WALKTHROUGH.md#share-the-windows-physical-host-reservation). Then run:

```bash
bash scripts/readiness.sh --campaign configs/local/raider-wsl/campaign.json --json-output results/readiness-wsl.json
```

To inspect WSL tools before configuring that directory, use `--platform ollama --os windows-11-wsl2-ubuntu-26.04`. It reports the missing shared lock without preventing independent tool installations. For standalone checks, `--lock-root /mnt/c/Users/YOU/.cache/llm-eval/locks` specifies an existing shared directory. With a campaign, the inventory itself must contain the correct path; readiness does not edit it. The checker can establish that the directory exists and is writable; you must confirm that the Windows inventory refers to the same physical directory and host ID.

## Controls and exit status

```bash
# Read-only probes: no installation, download or prompts.
bash scripts/readiness.sh --platform ollama --check-only --json-output results/readiness.json

# Explicit consent to supported installs; sudo/UAC or vendor UI may still appear.
bash scripts/readiness.sh --platform ollama --yes

# Source-build prerequisites are checked only for selected source engines.
bash scripts/readiness.sh --platform llama.cpp --platform ik_llama.cpp

# Add LiveBench's Python environment and Docker requirements.
bash scripts/readiness.sh --platform ollama --with-livebench

# Select one local hardware configuration in a larger campaign.
bash scripts/readiness.sh --campaign campaigns/my-campaign.json --hardware-config my-local-host

# A separate prefix for a standalone platform with a conflicting installation.
bash scripts/readiness.sh --platform ollama --prefix .platforms/my-new-ollama
```

Use the same options after the Windows `.ps1` entry point. `--campaign` derives platforms, prefixes, OS, hardware profile and LiveBench requirements from the real planner. Without a campaign, the default is Ollama on the detected OS with the MSI Raider profile; use `--hardware-profile ID` for another catalogued machine. `--os` must match the actual host for installations to be offered. Multiple campaign hardware configurations require an explicit selection. SSH targets are not installed from the coordinator: run readiness directly on the target with its platform, OS and hardware profile options. Hosted API deployments do not cause their server dependencies to be installed locally.

| Exit | Meaning |
|---|---|
| `0` | Every required tool/runtime check passed |
| `1` | Missing, declined, failed, incompatible or manually actionable prerequisite remains |
| `2` | Invalid selection/configuration or unsupported host |
| `130` | Interrupted; rerun to inspect partial installation state |

`--check-only` and `--yes` are mutually exclusive. Without a terminal and without `--yes`, the script reports gaps and declines installation. Optional findings, such as a missing package manager when all dependencies already exist, do not force exit 1. Installers never request an automatic reboot; complete a vendor-requested reboot yourself and rerun.

## What gets checked and installed

| Scope | Checks | Offered installation |
|---|---|---|
| Bootstrap | 64-bit Python 3.11–3.13, venv/ensurepip, TLS, secure tar extraction support | Windows: Python 3.12 through WinGet. Ubuntu/WSL: apt Python/venv/certificates, isolated uv bootstrap, user-local Python 3.12 |
| Harness | Git; importable harness, psutil and matplotlib in `.venv`; supported versions; `pip check` | Git through WinGet/apt; local virtual environment with `.[telemetry,reporting]` |
| Windows | PowerShell 7.4+, loadable Visual C++ runtime DLLs | Exact WinGet IDs for PowerShell and the x64 redistributable |
| Ubuntu/WSL | CA certificates, curl, OpenMP library packages | Ubuntu apt packages |
| Selected model platforms | Pinned Hugging Face downloader import/version | Catalogued package in `.venv` |
| GPU/hardware | Working `nvidia-smi`, configured GPU name/VRAM and OS-visible RAM | Driver/hardware issues receive instructions; no standalone GPU-driver installation |
| Source builds | CMake, C++ compiler/build tools, curl development package on Linux, `nvcc` support for the profile's CUDA architecture | WinGet CMake/MSVC tools; apt build packages; toolkit installation described below |
| vLLM/KTransformers on Linux | NUMA development/runtime packages and native extension compiler | apt packages; unsupported native Windows platforms stay blocked |
| Runtime | Pinned installation state, executable/dependency checks, package versions/imports and `pip check` inside its own environment | Existing `scripts/setup.py` recipes; matching existing environments can repair Python dependencies after consent |
| PyTorch runtimes | CUDA availability and a one-element CUDA arithmetic probe, plus backend imports | Pinned recipe packages; kernel failures remain failures |
| LiveBench | Pinned installation state, LiveBench environment dependency consistency, Docker CLI and daemon access | Runtime setup with LiveBench; Docker Desktop on Windows or Docker package on native Ubuntu |
| WSL | Shared reservation directory and advisory Linux-filesystem placement | Instructions to configure shared locks, WSL memory and Docker Desktop integration |

The Ollama combined campaign does **not** require CMake, MSVC/G++, a CUDA toolkit or Docker. It uses prebuilt Ollama plus the Windows/native Linux NVIDIA driver.

For source builds, Linux toolkit installation is offered only when an appropriate `cuda-toolkit-MAJOR-MINOR` candidate exists in an already configured apt repository. It never substitutes `cuda`, `cuda-drivers`, or a Linux driver package inside WSL. If no candidate exists, follow [NVIDIA's CUDA installation instructions](https://docs.nvidia.com/cuda/cuda-installation-guide-linux/index.html) for the actual distribution and rerun. The highest available toolkit is offered and `nvcc` architecture support is checked afterward; compiler/backend compatibility can still fail during setup. Windows uses WinGet's interactive CUDA installer so you can review its component choices, including any bundled driver component. The script does not configure third-party apt repositories or alter Secure Boot.

On WSL the GPU driver belongs to Windows: see [NVIDIA's WSL guidance](https://docs.nvidia.com/cuda/wsl-user-guide/index.html). For native Ubuntu follow [Ubuntu's NVIDIA driver guide](https://ubuntu.com/server/docs/how-to/graphics/install-nvidia-drivers/). Driver installation, a Docker daemon that needs starting, Windows App Installer repair, a conflicting runtime prefix, and BIOS/power changes remain explicit manual actions; the report stays not-ready where a required check fails.

Installation commands use argument arrays without shell interpolation. They run as the current user; only apt commands request sudo, and Windows installers may request UAC. WinGet package/source agreements are included in the displayed commands; `--yes` also consents to those agreements. System packages follow their configured repositories; engine versions and model-downloader versions follow `catalog/installers.json`. A Python bootstrap uses uv's current package and a Python 3.12 maintenance release. These host packages are not a fully hashed dependency lock.

The checker never deletes an existing environment, rewrites an installed runtime's state, or switches a conflicting prefix to another recipe. Python dependency repair updates its `pip-freeze.txt` after installation. Binary corruption or a broken/conflicting virtual environment needs a separate prefix/checkout. Do not install or repair dependencies while a campaign is active or awaiting resume: its revision and environment must remain stable.

## Example output and report

This is an illustrative excerpt, not output from the physical laptop:

```text
[PASS] os: Selected OS matches this host
  ubuntu-26.04-native
[PASS] git: Git
  git version <installed version>
[MISSING] harness: Local harness, telemetry and report libraries
  .../.venv/bin/python does not exist
[PASS] gpu: NVIDIA driver, configured GPU name and VRAM
  NVIDIA GeForce RTX 5090 Laptop GPU, <observed MiB>, <driver>
[MISSING] runtime-0: ollama pinned runtime at .../.platforms/ubuntu-26.04-native/ollama

Proposed installation for Local harness, telemetry and report libraries:
  ["<python>", "-m", "venv", "<repo>/.venv"]
  ["<repo>/.venv/bin/python", "-m", "pip", "install", "-e", "<repo>[telemetry,reporting]"]
Install this now? [y/N] yes
<installer output>
[INSTALLED] harness
```

After all requested installs, the checker repeats the probes and prints either `READY: selected tools and runtime dependencies passed.` or `NOT READY: <remaining check IDs>`. The optional JSON file contains `ready`, `before`, final `checks`, and `actions` with declined, blocked, failed or verification-failed outcomes. Probe details and commands are retained for diagnosis. Save it under ignored `results/`; it contains local paths and should be reviewed before publication. If no compatible Python exists, the OS wrapper reports/bootstrap-prompts on the console first; the structured report becomes available once Python can run the full checker.

Readiness is a prerequisite gate, **not** GPU/model certification. It does not download model weights, pull router models, start inference services, create artifact locks, acquire credentials, build a grading image, or fetch benchmark data. Continue the matching [Windows](WINDOWS_RAIDER_WALKTHROUGH.md), [WSL](WSL_RAIDER_WALKTHROUGH.md), or [Ubuntu](UBUNTU_RAIDER_WALKTHROUGH.md) guide to prepare those experiment inputs. An already verified runtime is reused by setup when its plan matches.

## Maintainer verification

The unit tests exercise consent, noninteractive/check-only behavior, installation failure and recheck semantics, OS mismatch, campaign selection, WSL handling, CUDA package selection, dependency inconsistency and recognition of the real setup plan. The repository's CI runs them on Windows and Linux with Python 3.11–3.13. Package installations, UAC, driver compatibility and the MSI GPU still require target-host acceptance; fixture tests do not certify them.

References: [WinGet install](https://learn.microsoft.com/en-us/windows/package-manager/winget/install), [uv-managed Python](https://docs.astral.sh/uv/guides/install-python/), and [Visual Studio build workloads](https://learn.microsoft.com/en-us/visualstudio/install/workload-component-id-vs-build-tools).
