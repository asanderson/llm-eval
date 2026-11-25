# llm-eval

Test which language models run on a given computer, how long they take to answer, and what their answers get right. The published results include real runs on an MSI Raider laptop and labeled fixtures for checking the software.

- **Choosing a local model?** Start with the [measured results](#measured-results) and check which runtime, prompt length and hardware were tested.
- **Running a test?** [Reproduce a published run](docs/REPRODUCE.md) or [contribute a result on another machine](docs/HARDWARE_PARTICIPATION.md).
- **Comparing results?** Open the [matched settings and download links](docs/results/index/recommended/README.md), or browse [individual runs by model or date](docs/results/index/README.md).

<a id="executive-summary"></a>

## Measured results

<!-- summary-recommended:start -->

### What ran on this hardware?

**inkling2-mini-26b-iq4_nl** on raider-wsl (windows-11-wsl2-ubuntu-26.04). NVIDIA GeForce RTX 5090 Laptop GPU, 24 GiB of GPU memory. Each row is the latest published test of this artifact name on that runtime.

| Model and runtime | Job status | Completed | Checks passed | Prompt tokens observed | Time until text appears (median s) | Placement evidence | Source |
|---|---|---:|---:|---:|---:|---|---|
| inkling2-mini-26b-iq4_nl · KoboldCpp | succeeded | 27/27 | 27/27 | 15–44 | 6.48 | 49 of 49 layers reported on GPU | [Report](docs/results/hardware-fit/campaign-20261124T225210Z-e801df32-fit-hardware-fit-1/README.md) |
| inkling2-mini-26b-iq4_nl · LM Studio | succeeded | 27/27 | 27/27 | 27–56 | 1.72 | fit inferred from device memory, layer count unknown | [Report](docs/results/hardware-fit/campaign-20261124T232244Z-86c68e03-fit-hardware-fit-1/README.md) |
| inkling2-mini-26b-iq4_nl · Ollama | failed | 0/27 | 0/27 | not recorded | not recorded | failed before any request completed | [Report](docs/results/hardware-fit/campaign-20261124T230811Z-0fa376ca-fit-hardware-fit-1/README.md) |

Each run recorded 9 tasks × 3 measured attempts. The configured context window was 8192 tokens. The longest prompt with a recorded token count used 56 tokens. Checks refer to the published workload. Repeated attempts on one question count as one distinct task.

[Inspect the run settings, device memory and raw records](docs/results/index/recommended/raider-wsl/hardware-fit.md).

| Experiment and hardware | Evidence available | Read the runs |
|---|---|---|
| hardware-fit · raider-wsl | 11 model runs, 2 projections (1 failed) | [Evidence and reproduction](docs/results/index/recommended/raider-wsl/hardware-fit.md) |
| decision-models · raider-wsl | 22 model runs | [Evidence and reproduction](docs/results/index/recommended/raider-wsl/decision-models.md) |
| model-offloading · raider-wsl | 54 model runs (2 failed) | [Evidence and reproduction](docs/results/index/recommended/raider-wsl/model-offloading.md) |
| legal-models · raider-wsl | 1 fixture, 2 measured model runs, 1 rescore | [Evidence and reproduction](docs/results/index/recommended/raider-wsl/legal-models.md) |
| model-offloading · raider-windows | 106 model runs (6 failed) | [Evidence and reproduction](docs/results/index/recommended/raider-windows/model-offloading.md) |
| legal-models · raider-windows | 1 fixture, 2 measured model runs, 1 rescore | [Evidence and reproduction](docs/results/index/recommended/raider-windows/legal-models.md) |
| decision-models · raider-windows | 4 model runs | [Evidence and reproduction](docs/results/index/recommended/raider-windows/decision-models.md) |
| decision-models · raider-ubuntu | 1 fixture | [Evidence and reproduction](docs/results/index/recommended/raider-ubuntu/decision-models.md) |

**Human review is pending** in 6 published legal jobs on fictional matters. See the [review denominators](docs/results/index/recommended/raider-wsl/legal-models.md#legal-evaluation).

Native Ubuntu on the Raider has fixture coverage only. A measured result there is still open.

[Browse by model, date or runtime](docs/results/index/README.md) · [US model results](docs/results/index/origin/us.md).

<!-- summary-recommended:end -->

## Contents

| Topic | Documents |
|---|---|
| Summary | [Measured results](#measured-results) by hardware, workload and runtime |
| Experiments | [Hardware fit](experiments/hardware-fit/README.md) · [Model offloading](experiments/model-offloading/README.md) · [Decision models](experiments/decision-models/README.md) · [Legal models](experiments/legal-models/README.md) ([walkthrough](docs/LEGAL_MODELS_WALKTHROUGH.md)) · [Add a new experiment](docs/NEW_EXPERIMENT.md) |
| Models | [Model catalog](docs/MODELS.md) · [Model origins and US models](docs/MODELS.md#model-origins) · [Candidate models from Ollama, Hugging Face and LM Studio](docs/MODEL_CANDIDATES.md) · [LiveBench integration](docs/LIVEBENCH.md) · [Nightly model discovery](docs/MODEL_DISCOVERY.md) · catalogs: [models](catalog/models.json), [artifact pins](catalog/model-artifacts.json), [origins](catalog/model-origins.json) |
| Model platforms | [Setup and compatibility of every platform](docs/PLATFORMS.md): [Ollama](docs/PLATFORMS.md#ollama) · [LM Studio](docs/PLATFORMS.md#lm-studio) · [KoboldCpp](docs/PLATFORMS.md#koboldcpp) · [llama.cpp and ik_llama.cpp](docs/PLATFORMS.md#llamacpp-and-ik_llamacpp) · [KTransformers](docs/PLATFORMS.md#ktransformers) · [vLLM](docs/PLATFORMS.md#vllm) · [Hugging Face Accelerate](docs/PLATFORMS.md#hugging-face-accelerate) · [AirLLM](docs/PLATFORMS.md#airllm) · [Strata](docs/PLATFORMS.md#strata) |
| Hardware configurations | [Hardware configurations](docs/HARDWARE.md): [raider-windows](docs/HARDWARE.md#raider-windows) · [raider-wsl](docs/HARDWARE.md#raider-wsl) · [raider-ubuntu](docs/HARDWARE.md#raider-ubuntu) |
| Running experiments | [Readiness checker](docs/READINESS.md) · [Campaigns, inventories, SSH and recovery](docs/CAMPAIGNS.md) · walkthroughs for [native Windows 11](docs/WINDOWS_RAIDER_WALKTHROUGH.md), [WSL2 / Ubuntu 26.04](docs/WSL_RAIDER_WALKTHROUGH.md) and [native Ubuntu 26.04](docs/UBUNTU_RAIDER_WALKTHROUGH.md) · [Original platform workflows](docs/WORKFLOWS.md) |
| Results | [Experiment results](docs/results/README.md) · [Results index](docs/results/index/README.md) · [Setup evidence](docs/results/index/recommended/README.md) · [Report generation and results pull requests](docs/RESULTS.md) |
| Reference | [Methodology](docs/METHODOLOGY.md) · [Validation record](docs/VALIDATION.md) · [Security](docs/SECURITY.md) |

## Experiments

| Experiment | What it evaluates | Guide |
|---|---|---|
| Hardware fit | Projects whether an artifact can fit in GPU memory and measures placement evidence, device memory and completion under load | [Hardware fit guide](experiments/hardware-fit/README.md) |
| Model offloading | Quality, latency, throughput, and CPU/GPU/disk placement for models exceeding GPU VRAM | [Original experiment and model catalog](experiments/model-offloading/README.md) |
| Decision models | Accuracy and latency of decision models (one choice question per task over named criteria, through Ollama's SystemOne API), replay selection quality, and the live quality, latency and API cost of the generators they route to. Formerly `llm-routing` | [Decision models guide](experiments/decision-models/README.md) |
| Legal models | Retrieval of applicable law and source-grounded draft screening memos for human review, over a fictional jurisdiction; fictional fixture suite only; four runs on the Windows host and four in WSL2 published (generation and workflow on a served model, score, fixture retrieval), human review pending. Formerly `legal-benchmark` | [Legal models guide](experiments/legal-models/README.md) |

The original target is the MSI Raider 18 HX AI with RTX 5090 Laptop 24 GiB, 64 GiB RAM, and native Ubuntu, native Windows, or WSL. Additional machines use their own profiles and execution targets. **Fixture tests are not real hardware benchmarks.** See the [validation record](docs/VALIDATION.md) for hardware acceptance gates.

## Start here

Run the [readiness checker](docs/READINESS.md) on the test host to find missing tools/libraries and install supported prerequisites after prompting: `powershell -NoProfile -File .\scripts\readiness.ps1` on native Windows, or `bash scripts/readiness.sh` on Ubuntu/WSL. Use `--check-only` for an audit or `--campaign FILE` to derive requirements from your experiments.

For a complete combined model-offloading and decision-models campaign on the MSI Raider, choose your OS. Each walkthrough covers installation, model preparation, plan, setup, run, status, resume, reports and results PRs, with labeled example output.

| Platform | Walkthrough | Campaign files |
|---|---|---|
| Native Windows 11 | [PowerShell](docs/WINDOWS_RAIDER_WALKTHROUGH.md) | [raider-windows](configs/examples/raider-windows/) |
| WSL2 / Ubuntu 26.04 | [Bash with Windows host preparation](docs/WSL_RAIDER_WALKTHROUGH.md) | [raider-wsl](configs/examples/raider-wsl/) |
| Native Ubuntu 26.04 | [Bash](docs/UBUNTU_RAIDER_WALKTHROUGH.md) | [raider-ubuntu](configs/examples/raider-ubuntu/) |

```bash
python -m pip install -e ".[telemetry,reporting]"
python -m llm_eval experiments list
python -m llm_eval plan --campaign campaigns/routing-smoke.json
python -m llm_eval run --campaign campaigns/routing-smoke.json
```

The smoke campaign is a labeled synthetic decision-models fixture: a keyword category router, no model. It runs without model downloads or paid API calls and generates a local report. It does not publish a PR.

For the campaign wizard:

```bash
python scripts/setup.py --interactive
python scripts/run.py --interactive
```

For real experiments, copy and complete the [combined campaign example](campaigns/offload-and-routing.example.json), hardware inventory and experiment cases in `configs/local/`. The example enables automatic results PRs; configure GitHub credentials before publication. Inspect the plan before running it.

```bash
llm-eval plan --campaign configs/local/campaign.json
llm-eval setup --campaign configs/local/campaign.json
llm-eval run --campaign configs/local/campaign.json --max-parallel-jobs 1
llm-eval run --campaign configs/local/campaign.json --max-parallel-jobs 2
llm-eval status --campaign-dir results/campaign-EXAMPLE
llm-eval resume --campaign-dir results/campaign-EXAMPLE
```

Parallel jobs share a resource scheduler. Isolated measurements sharing a physical host run serially; Windows and WSL on the same laptop share one resource identity. Separate boot environments are resumed in their respective OS sessions. The harness does not reboot machines.

![Campaign architecture](diagrams/campaign-architecture.png)

## Experiment results

The [results documentation](docs/results/README.md) contains reviewed experiment reports, raw measurement exports, JSON/CSV summaries and embedded PNG charts. Each experiment run can automatically generate and push a results branch and open a PR for review. Reports are merged using the repository's normal review process.

```bash
python scripts/report_experiment.py --experiment-dir results/campaign-EXAMPLE/experiments/EXPERIMENT_RUN --publish-pr
llm-eval publish-results --input results/campaign-EXAMPLE/experiments/EXPERIMENT_RUN/report --dry-run
```

## Documentation

Every document is listed under [Contents](#contents). The [legal models walkthrough](docs/LEGAL_MODELS_WALKTHROUGH.md) covers offload calibration, the locked serving profile, routing calibration and replay, the frozen legal evaluation and the local report.

Existing `llm-eval run --config FILE`, `scripts/run.py --config FILE`, and platform/OS wrappers remain supported. Their original installation and local-inference defaults remain in place. Source, workloads and experiment settings must be pinned for meaningful comparisons.
