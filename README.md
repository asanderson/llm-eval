# llm-eval

## Contents

| Topic | Documents |
|---|---|
| [Experiments](#experiments) | [Hardware fit](experiments/hardware-fit/README.md) · [Model offloading](experiments/model-offloading/README.md) · [Decision models](experiments/decision-models/README.md) · [Legal models](experiments/legal-models/README.md) ([walkthrough](docs/LEGAL_MODELS_WALKTHROUGH.md)) · [Add a new experiment](docs/NEW_EXPERIMENT.md) |
| Summary | [Measured results](#measured-results) by hardware, workload and runtime |
| Models | [Model catalog](docs/MODELS.md) · [Model origins and US models](docs/MODELS.md#model-origins) · [Candidate models from Ollama, Hugging Face and LM Studio](docs/MODEL_CANDIDATES.md) · [LiveBench integration](docs/LIVEBENCH.md) · [Nightly model discovery](docs/MODEL_DISCOVERY.md) · catalogs: [models](catalog/models.json), [artifact pins](catalog/model-artifacts.json), [origins](catalog/model-origins.json) |
| Model platforms | [Setup and compatibility of every platform](docs/PLATFORMS.md): [Ollama](docs/PLATFORMS.md#ollama) · [LM Studio](docs/PLATFORMS.md#lm-studio) · [KoboldCpp](docs/PLATFORMS.md#koboldcpp) · [llama.cpp and ik_llama.cpp](docs/PLATFORMS.md#llamacpp-and-ik_llamacpp) · [KTransformers](docs/PLATFORMS.md#ktransformers) · [vLLM](docs/PLATFORMS.md#vllm) · [Hugging Face Accelerate](docs/PLATFORMS.md#hugging-face-accelerate) · [AirLLM](docs/PLATFORMS.md#airllm) · [Strata](docs/PLATFORMS.md#strata) |
| Hardware configurations | [Hardware configurations](docs/HARDWARE.md): [raider-windows](docs/HARDWARE.md#raider-windows) · [raider-wsl](docs/HARDWARE.md#raider-wsl) · [raider-ubuntu](docs/HARDWARE.md#raider-ubuntu) |
| [Running experiments](#start-here) | [Readiness checker](docs/READINESS.md) · [Campaigns, inventories, SSH and recovery](docs/CAMPAIGNS.md) · walkthroughs for [native Windows 11](docs/WINDOWS_RAIDER_WALKTHROUGH.md), [WSL2 / Ubuntu 26.04](docs/WSL_RAIDER_WALKTHROUGH.md) and [native Ubuntu 26.04](docs/UBUNTU_RAIDER_WALKTHROUGH.md) · [Original platform workflows](docs/WORKFLOWS.md) |
| Results | [Experiment results](docs/results/README.md) · [Results index](docs/results/index/README.md) · [Setup evidence](docs/results/index/recommended/README.md) · [Report generation and results pull requests](docs/RESULTS.md) |
| Reference | [Methodology](docs/METHODOLOGY.md) · [Validation record](docs/VALIDATION.md) · [Security](docs/SECURITY.md) |

## Experiments

Test which language models run on a given computer, how long they take to answer, and what their answers get right. The published results include real runs on an MSI Raider laptop and labeled fixtures for checking the software.

| Experiment | What it evaluates | Guide |
|---|---|---|
| Hardware fit | Projects whether an artifact can fit in GPU memory and measures placement evidence, device memory and completion under load | [Hardware fit guide](experiments/hardware-fit/README.md) |
| Model offloading | Quality, latency, throughput, and CPU/GPU/disk placement for models exceeding GPU VRAM | [Original experiment and model catalog](experiments/model-offloading/README.md) |
| Decision models | Accuracy and latency of decision models (one choice question per task over named criteria, through Ollama's SystemOne API), replay selection quality, and the live quality, latency and API cost of the generators they route to. Formerly `llm-routing` | [Decision models guide](experiments/decision-models/README.md) |
| Legal models | Retrieval of applicable law and source-grounded draft screening memos for human review, over a fictional jurisdiction; fictional fixture suite only; four runs on the Windows host and four in WSL2 published (generation and workflow on a served model, score, fixture retrieval), human review pending. Formerly `legal-benchmark` | [Legal models guide](experiments/legal-models/README.md) |

The original target is the MSI Raider 18 HX AI with RTX 5090 Laptop 24 GiB, 64 GiB RAM, and native Ubuntu, native Windows, or WSL. Additional machines use their own profiles and execution targets. **Fixture tests are not real hardware benchmarks.** See the [validation record](docs/VALIDATION.md) for hardware acceptance gates.

<a id="executive-summary"></a>

## Measured results

<!-- summary-recommended:start -->

### What ran on this hardware?

Every published job appears once below, grouped by hardware configuration and experiment. Within each experiment, find the model and harness alphabetically, then its runs newest first. Each publication time and job ID links to its source report.

Jump to [raider-wsl](#runs-raider-wsl) · [raider-windows](#runs-raider-windows) · [raider-ubuntu](#runs-raider-ubuntu).

| Experiment and hardware | Evidence available | Read the runs |
|---|---|---|
| [hardware-fit · raider-wsl](#runs-raider-wsl-hardware-fit) | 11 model runs, 2 projections (1 failed) | [Evidence and reproduction](docs/results/index/recommended/raider-wsl/hardware-fit.md) |
| [decision-models · raider-wsl](#runs-raider-wsl-decision-models) | 22 model runs | [Evidence and reproduction](docs/results/index/recommended/raider-wsl/decision-models.md) |
| [model-offloading · raider-wsl](#runs-raider-wsl-model-offloading) | 54 model runs (2 failed) | [Evidence and reproduction](docs/results/index/recommended/raider-wsl/model-offloading.md) |
| [legal-models · raider-wsl](#runs-raider-wsl-legal-models) | 1 fixture, 2 measured model runs, 1 rescore | [Evidence and reproduction](docs/results/index/recommended/raider-wsl/legal-models.md) |
| [model-offloading · raider-windows](#runs-raider-windows-model-offloading) | 106 model runs (6 failed) | [Evidence and reproduction](docs/results/index/recommended/raider-windows/model-offloading.md) |
| [legal-models · raider-windows](#runs-raider-windows-legal-models) | 1 fixture, 2 measured model runs, 1 rescore | [Evidence and reproduction](docs/results/index/recommended/raider-windows/legal-models.md) |
| [decision-models · raider-windows](#runs-raider-windows-decision-models) | 4 model runs | [Evidence and reproduction](docs/results/index/recommended/raider-windows/decision-models.md) |
| [decision-models · raider-ubuntu](#runs-raider-ubuntu-decision-models) | 1 fixture | [Evidence and reproduction](docs/results/index/recommended/raider-ubuntu/decision-models.md) |

**Human review is pending** in 6 published legal jobs on fictional matters. See the [review denominators](docs/results/index/recommended/raider-wsl/legal-models.md#legal-evaluation).

Native Ubuntu on the Raider has fixture coverage only. A measured result there is still open.

<a id="runs-raider-wsl"></a>

#### raider-wsl

93 published jobs · windows-11-wsl2-ubuntu-26.04 · NVIDIA GeForce RTX 5090 Laptop GPU (24 GiB)

<a id="runs-raider-wsl-decision-models"></a>

##### decision-models

| Model | Harness | Mode | Status | Workload | Completed | Checks passed | Wall time (median s) | Publication / job |
|---|---|---|---|---|---|---|---|---|
| llm-eval-clef-flash:locked | Ollama | decision | succeeded | 2 tasks × 3 measured attempts | 6/6 | 6/6 | 0.0453 | [2026-11-24T22:46:34.923711+00:00 · routing-decision-models-1-0701e943af0c](docs/results/decision-models/campaign-20261124T224634Z-f70bba1c-routing-decision-models-1/README.md) |
| llm-eval-clef-flash:locked | Ollama | decision | succeeded | 2 tasks × 3 measured attempts | 6/6 | 6/6 | 0.0554 | [2026-11-24T22:41:17.740366+00:00 · routing-decision-models-1-0701e943af0c](docs/results/decision-models/campaign-20261124T224117Z-ce08f5a6-routing-decision-models-1/README.md) |
| llm-eval-clef:locked | Ollama | decision | succeeded | 2 tasks × 3 measured attempts | 6/6 | 6/6 | 0.441 | [2026-11-24T22:46:34.923711+00:00 · routing-decision-models-1-cff82f501cf5](docs/results/decision-models/campaign-20261124T224634Z-f70bba1c-routing-decision-models-1/README.md) |
| llm-eval-clef:locked | Ollama | decision | succeeded | 2 tasks × 3 measured attempts | 6/6 | 6/6 | 0.534 | [2026-11-24T22:41:17.740366+00:00 · routing-decision-models-1-cff82f501cf5](docs/results/decision-models/campaign-20261124T224117Z-ce08f5a6-routing-decision-models-1/README.md) |
| llm-eval-d1-omni:locked | Ollama | decision | succeeded | 2 tasks × 3 measured attempts | 6/6 | 6/6 | 0.0131 | [2026-11-24T22:46:34.923711+00:00 · routing-decision-models-1-473146c3e729](docs/results/decision-models/campaign-20261124T224634Z-f70bba1c-routing-decision-models-1/README.md) |
| llm-eval-d1-omni:locked | Ollama | decision | succeeded | 2 tasks × 3 measured attempts | 6/6 | 6/6 | 0.0379 | [2026-11-24T22:41:17.740366+00:00 · routing-decision-models-1-473146c3e729](docs/results/decision-models/campaign-20261124T224117Z-ce08f5a6-routing-decision-models-1/README.md) |
| llm-eval-d1:locked | Ollama | decision | succeeded | 2 tasks × 3 measured attempts | 6/6 | 6/6 | 0.0119 | [2026-11-24T22:46:34.923711+00:00 · routing-decision-models-1-b72471bb152f](docs/results/decision-models/campaign-20261124T224634Z-f70bba1c-routing-decision-models-1/README.md) |
| llm-eval-d1:locked | Ollama | decision | succeeded | 2 tasks × 3 measured attempts | 6/6 | 6/6 | 0.0177 | [2026-11-24T22:41:17.740366+00:00 · routing-decision-models-1-b72471bb152f](docs/results/decision-models/campaign-20261124T224117Z-ce08f5a6-routing-decision-models-1/README.md) |
| llm-eval-laya:locked | Ollama | decision | succeeded | 2 tasks × 3 measured attempts | 6/6 | 6/6 | 0.0179 | [2026-11-24T22:46:34.923711+00:00 · routing-decision-models-1-8f34219dcce9](docs/results/decision-models/campaign-20261124T224634Z-f70bba1c-routing-decision-models-1/README.md) |
| llm-eval-laya:locked | Ollama | decision | succeeded | 2 tasks × 3 measured attempts | 6/6 | 6/6 | 0.0141 | [2026-11-24T22:41:17.740366+00:00 · routing-decision-models-1-8f34219dcce9](docs/results/decision-models/campaign-20261124T224117Z-ce08f5a6-routing-decision-models-1/README.md) |
| llm-eval-nimble-v3:locked | Ollama | decision | succeeded | 2 tasks × 3 measured attempts | 6/6 | 6/6 | 0.0442 | [2026-11-24T22:46:34.923711+00:00 · routing-decision-models-1-2cfe79fef460](docs/results/decision-models/campaign-20261124T224634Z-f70bba1c-routing-decision-models-1/README.md) |
| llm-eval-nimble-v3:locked | Ollama | decision | succeeded | 2 tasks × 3 measured attempts | 6/6 | 6/6 | 0.055 | [2026-11-24T22:41:17.740366+00:00 · routing-decision-models-1-2cfe79fef460](docs/results/decision-models/campaign-20261124T224117Z-ce08f5a6-routing-decision-models-1/README.md) |
| llm-eval-nimble:locked | Ollama | decision | succeeded | 2 tasks × 3 measured attempts | 6/6 | 6/6 | 0.0514 | [2026-11-24T22:46:34.923711+00:00 · routing-decision-models-1-ac901abb4fcd](docs/results/decision-models/campaign-20261124T224634Z-f70bba1c-routing-decision-models-1/README.md) |
| llm-eval-nimble:locked | Ollama | decision | succeeded | 2 tasks × 3 measured attempts | 6/6 | 6/6 | 0.0519 | [2026-11-24T22:41:17.740366+00:00 · routing-decision-models-1-ac901abb4fcd](docs/results/decision-models/campaign-20261124T224117Z-ce08f5a6-routing-decision-models-1/README.md) |
| llm-eval-nimble:locked | Ollama | decision | succeeded | 2 tasks × 3 measured attempts | 6/6 | 6/6 | 0.0526 | [2026-11-18T05:10:19.056084+00:00 · routing-llm-routing-1-ac901abb4fcd](docs/results/llm-routing/campaign-20261118T051019Z-d72bad77-routing-llm-routing-1/README.md) |
| llm-eval-pplx-decider:locked | Ollama | decision | succeeded | 2 tasks × 3 measured attempts | 6/6 | 6/6 | 0.104 | [2026-11-24T22:46:34.923711+00:00 · routing-decision-models-1-efcc2160debc](docs/results/decision-models/campaign-20261124T224634Z-f70bba1c-routing-decision-models-1/README.md) |
| llm-eval-pplx-decider:locked | Ollama | decision | succeeded | 2 tasks × 3 measured attempts | 6/6 | 6/6 | 0.103 | [2026-11-24T22:41:17.740366+00:00 · routing-decision-models-1-efcc2160debc](docs/results/decision-models/campaign-20261124T224117Z-ce08f5a6-routing-decision-models-1/README.md) |
| llm-eval-tev1-0.8b:locked | Ollama | decision | succeeded | 2 tasks × 3 measured attempts | 6/6 | 6/6 | 0.017 | [2026-11-24T22:46:34.923711+00:00 · routing-decision-models-1-49a41a2986fd](docs/results/decision-models/campaign-20261124T224634Z-f70bba1c-routing-decision-models-1/README.md) |
| llm-eval-tev1-0.8b:locked | Ollama | decision | succeeded | 2 tasks × 3 measured attempts | 6/6 | 6/6 | 0.0147 | [2026-11-24T22:41:17.740366+00:00 · routing-decision-models-1-49a41a2986fd](docs/results/decision-models/campaign-20261124T224117Z-ce08f5a6-routing-decision-models-1/README.md) |
| llm-eval-tev1:locked | Ollama | decision | succeeded | 2 tasks × 3 measured attempts | 6/6 | 6/6 | 0.0311 | [2026-11-24T22:46:34.923711+00:00 · routing-decision-models-1-c6e41214da48](docs/results/decision-models/campaign-20261124T224634Z-f70bba1c-routing-decision-models-1/README.md) |
| llm-eval-tev1:locked | Ollama | decision | succeeded | 2 tasks × 3 measured attempts | 6/6 | 6/6 | 0.0265 | [2026-11-24T22:41:17.740366+00:00 · routing-decision-models-1-c6e41214da48](docs/results/decision-models/campaign-20261124T224117Z-ce08f5a6-routing-decision-models-1/README.md) |
| llm-eval-tev1:locked | Ollama | decision | succeeded | 2 tasks × 3 measured attempts | 6/6 | 6/6 | 0.0249 | [2026-11-18T05:10:19.056084+00:00 · routing-llm-routing-1-c6e41214da48](docs/results/llm-routing/campaign-20261118T051019Z-d72bad77-routing-llm-routing-1/README.md) |

[Run settings and experiment details](docs/results/index/recommended/raider-wsl/decision-models.md).

<a id="runs-raider-wsl-hardware-fit"></a>

##### hardware-fit

| Model | Harness | Mode | Status | Workload | Completed | Checks passed | First text (median s) | Input / configured context (tokens) | Placement evidence | Publication / job |
|---|---|---|---|---|---|---|---|---|---|---|
| inkling2-mini-26b-iq4_nl | KoboldCpp | measured | succeeded | 9 tasks × 3 measured attempts | 27/27 | 27/27 | 6.48 | 15–44 / 8192 | 49 of 49 layers reported on GPU | [2026-11-24T22:52:10.518917+00:00 · fit-hardware-fit-1-681665f3272a](docs/results/hardware-fit/campaign-20261124T225210Z-e801df32-fit-hardware-fit-1/README.md) |
| inkling2-mini-26b-iq4_nl | LM Studio | measured | succeeded | 9 tasks × 3 measured attempts | 27/27 | 27/27 | 1.72 | 27–56 / 8192 | fit inferred from device memory, layer count unknown | [2026-11-24T23:22:44.997235+00:00 · fit-hardware-fit-1-971aedbccee6](docs/results/hardware-fit/campaign-20261124T232244Z-86c68e03-fit-hardware-fit-1/README.md) |
| inkling2-mini-26b-iq4_nl | Ollama | measured | failed | 9 tasks × 3 measured attempts | 0/27 | 0/27 | not recorded | not recorded / 8192 | failed before any request completed | [2026-11-24T23:08:11.066043+00:00 · fit-hardware-fit-1-9aa57a544a52](docs/results/hardware-fit/campaign-20261124T230811Z-0fa376ca-fit-hardware-fit-1/README.md) |
| measured-models-gguf | projection | projection | succeeded | capacity estimates | no model call | unscored | not recorded | not recorded / not recorded | capacity estimate | [2026-11-23T06:01:20.669483+00:00 · fit-hardware-fit-1-350a43aad20a](docs/results/hardware-fit/campaign-20261123T060120Z-252fece8-fit-hardware-fit-1/README.md) |
| measured-models-gguf-as-found | projection | projection | succeeded | capacity estimates | no model call | unscored | not recorded | not recorded / not recorded | capacity estimate | [2026-11-23T06:01:20.669483+00:00 · fit-hardware-fit-1-f008c633e429](docs/results/hardware-fit/campaign-20261123T060120Z-252fece8-fit-hardware-fit-1/README.md) |
| muse-glimmer-30b-kquant-17gb-q4_k_m | KoboldCpp | measured | succeeded | 9 tasks × 3 measured attempts | 27/27 | 18/27 | 0.524 | 22–45 / 8192 | 53 of 53 layers reported on GPU | [2026-11-24T22:52:10.518917+00:00 · fit-hardware-fit-1-2672aee4239f](docs/results/hardware-fit/campaign-20261124T225210Z-e801df32-fit-hardware-fit-1/README.md) |
| muse-glimmer-30b-kquant-17gb-q4_k_m | LM Studio | measured | succeeded | 9 tasks × 3 measured attempts | 27/27 | 24/27 | 4.13 | 68–91 / 8192 | fit inferred from device memory, layer count unknown | [2026-11-24T23:22:44.997235+00:00 · fit-hardware-fit-1-54cda96c277e](docs/results/hardware-fit/campaign-20261124T232244Z-86c68e03-fit-hardware-fit-1/README.md) |
| muse-glimmer-30b-kquant-17gb-q4_k_m | Ollama | measured | succeeded | 9 tasks × 3 measured attempts | 27/27 | 24/27 | 4.05 | 68–91 / 8192 | 53 of 53 layers reported on GPU | [2026-11-24T23:08:11.066043+00:00 · fit-hardware-fit-1-82d35f1d737c](docs/results/hardware-fit/campaign-20261124T230811Z-0fa376ca-fit-hardware-fit-1/README.md) |
| qwen38-27b-ud-q4_k_xl | KoboldCpp | measured | succeeded | 9 tasks × 3 measured attempts | 27/27 | 24/27 | 2.96 | 23–45 / 8192 | 66 of 66 layers reported on GPU | [2026-11-24T22:52:10.518917+00:00 · fit-hardware-fit-1-1479e5e031a5](docs/results/hardware-fit/campaign-20261124T225210Z-e801df32-fit-hardware-fit-1/README.md) |
| qwen38-27b-ud-q4_k_xl | KoboldCpp | measured | succeeded | 9 tasks × 3 measured attempts | 27/27 | 24/27 | 2.78 | 23–45 / 8192 | 66 of 66 layers reported on GPU | [2026-11-23T06:04:54.502356+00:00 · fit-hardware-fit-1-1479e5e031a5](docs/results/hardware-fit/campaign-20261123T060454Z-d3e0de27-fit-hardware-fit-1/README.md) |
| qwen38-27b-ud-q4_k_xl | LM Studio | measured | succeeded | 9 tasks × 3 measured attempts | 27/27 | 24/27 | 0.886 | 66–88 / 8192 | fit inferred from device memory, layer count unknown | [2026-11-23T12:06:32.733902+00:00 · fit-hardware-fit-1-4b1c74ff0cbf](docs/results/hardware-fit/campaign-20261123T120632Z-53d7833d-fit-hardware-fit-1/README.md) |
| qwen38-27b-ud-q4_k_xl | Ollama | measured | succeeded | 9 tasks × 3 measured attempts | 27/27 | 24/27 | 1.87 | 66–88 / 8192 | 66 of 66 layers reported on GPU | [2026-11-24T23:08:11.066043+00:00 · fit-hardware-fit-1-aca7cd52ca80](docs/results/hardware-fit/campaign-20261124T230811Z-0fa376ca-fit-hardware-fit-1/README.md) |
| qwen38-27b-ud-q4_k_xl | Ollama | measured | succeeded | 9 tasks × 3 measured attempts | 27/27 | 24/27 | 1.88 | 66–88 / 8192 | 66 of 66 layers reported on GPU | [2026-11-23T12:06:32.733902+00:00 · fit-hardware-fit-1-aca7cd52ca80](docs/results/hardware-fit/campaign-20261123T120632Z-53d7833d-fit-hardware-fit-1/README.md) |

[Run settings and experiment details](docs/results/index/recommended/raider-wsl/hardware-fit.md).

<a id="runs-raider-wsl-legal-models"></a>

##### legal-models

| Model | Harness | Mode | Status | Workload | Completed | Checks passed | First text (median s) | Publication / job |
|---|---|---|---|---|---|---|---|---|
| fixture | fixture | retrieval · fixture | succeeded | 16 fictional matters | not recorded | 39/56 | not recorded | [2026-11-18T06:48:54.008458+00:00 · retrieval-legal-benchmark-1-5aef2f285d5d](docs/results/legal-benchmark/campaign-20261118T064854Z-6746b621-retrieval-legal-benchmark-1/README.md) |
| llm-eval-kimi-linear-48b:locked | Ollama | score · score-only | succeeded | 16 fictional matters | not recorded | 0/32 | not recorded | [2026-11-18T07:17:04.491102+00:00 · score-legal-benchmark-1-ff60ca399ae0](docs/results/legal-benchmark/campaign-20261118T071704Z-9ee36cc3-score-legal-benchmark-1/README.md) |
| llm-eval-kimi-linear-48b:locked | Ollama | generation · measured | succeeded | 16 fictional matters | not recorded | 0/32 | not recorded | [2026-11-18T06:48:54.008458+00:00 · generation-legal-benchmark-1-727308bd9fb4](docs/results/legal-benchmark/campaign-20261118T064854Z-6746b621-generation-legal-benchmark-1/README.md) |
| llm-eval-kimi-linear-48b:locked | Ollama | workflow · measured | succeeded | 16 fictional matters | not recorded | 0/32 | not recorded | [2026-11-18T06:48:54.008458+00:00 · workflow-legal-benchmark-1-00efc50ea670](docs/results/legal-benchmark/campaign-20261118T064854Z-6746b621-workflow-legal-benchmark-1/README.md) |

[Run settings and experiment details](docs/results/index/recommended/raider-wsl/legal-models.md).

<a id="runs-raider-wsl-model-offloading"></a>

##### model-offloading

| Model | Harness | Mode | Status | Workload | Completed | Checks passed | First text (median s) | Publication / job |
|---|---|---|---|---|---|---|---|---|
| deepseek-r1-32b | KoboldCpp | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 6/27 | 87 | [2026-11-17T08:03:18.282801+00:00 · offload-model-offloading-1-be7755f6bfa6](docs/results/model-offloading/campaign-20261117T080318Z-29021cec-offload-model-offloading-1/README.md) |
| deepseek-r1-32b | LM Studio | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 6/27 | 95.6 | [2026-11-22T03:52:37.115669+00:00 · offload-model-offloading-1-10419522d3de](docs/results/model-offloading/campaign-20261122T035237Z-c1de26ec-offload-model-offloading-1/README.md) |
| deepseek-r1-32b | Ollama | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 3/27 | 82.7 | [2026-11-17T08:03:18.282801+00:00 · offload-model-offloading-1-09645320a4dd](docs/results/model-offloading/campaign-20261117T080318Z-29021cec-offload-model-offloading-1/README.md) |
| deepseek-r1-70b | KoboldCpp | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 3/27 | 133 | [2026-11-17T22:09:44.960621+00:00 · offload-model-offloading-1-4f5a36938fca](docs/results/model-offloading/campaign-20261117T220944Z-fb65881a-offload-model-offloading-1/README.md) |
| deepseek-r1-70b | LM Studio | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 3/27 | 150 | [2026-11-22T10:10:18.265305+00:00 · offload-model-offloading-1-9eda56ea4102](docs/results/model-offloading/campaign-20261122T101018Z-e2ea6a6f-offload-model-offloading-1/README.md) |
| deepseek-r1-70b | Ollama | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 6/27 | 148 | [2026-11-17T22:09:44.960621+00:00 · offload-model-offloading-1-2321c8a27cbf](docs/results/model-offloading/campaign-20261117T220944Z-fb65881a-offload-model-offloading-1/README.md) |
| gemma3-27b | KoboldCpp | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 18/27 | 0.524 | [2026-11-17T07:37:53.627878+00:00 · offload-model-offloading-1-3c527ba7186d](docs/results/model-offloading/campaign-20261117T073753Z-bee9d8ce-offload-model-offloading-1/README.md) |
| gemma3-27b | LM Studio | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 18/27 | 0.746 | [2026-11-22T00:48:54.495143+00:00 · offload-model-offloading-1-097e8d2fdfb9](docs/results/model-offloading/campaign-20261122T004854Z-df06d9cb-offload-model-offloading-1/README.md) |
| gemma3-27b | Ollama | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 18/27 | 0.604 | [2026-11-17T07:37:53.627878+00:00 · offload-model-offloading-1-192aa0635cfc](docs/results/model-offloading/campaign-20261117T073753Z-bee9d8ce-offload-model-offloading-1/README.md) |
| gemma4-26b-moe | KoboldCpp | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 21/27 | 0.523 | [2026-11-18T05:04:51.044818+00:00 · offload-model-offloading-1-44b1e0ca0edb](docs/results/model-offloading/campaign-20261118T050451Z-60d1fe39-offload-model-offloading-1/README.md) |
| gemma4-26b-moe | LM Studio | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 21/27 | 14.2 | [2026-11-22T14:37:02.810790+00:00 · offload-model-offloading-1-d6bed139f905](docs/results/model-offloading/campaign-20261122T143702Z-f61498fb-offload-model-offloading-1/README.md) |
| gemma4-26b-moe | Ollama | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 24/27 | 12.5 | [2026-11-23T10:47:21.531863+00:00 · offload-model-offloading-1-a5de5a44d6b9](docs/results/model-offloading/campaign-20261123T104721Z-e2a3aa26-offload-model-offloading-1/README.md) |
| gemma4-26b-moe | Ollama | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 24/27 | 12.5 | [2026-11-18T12:06:58.177136+00:00 · offload-model-offloading-1-a5de5a44d6b9](docs/results/model-offloading/campaign-20261118T120658Z-2f4fa5af-offload-model-offloading-1/README.md) |
| gemma4-26b-moe | Ollama | category-smoke | failed | not recorded | not recorded | unscored | not recorded | [2026-11-18T05:04:51.044818+00:00 · offload-model-offloading-1-a5de5a44d6b9](docs/results/model-offloading/campaign-20261118T050451Z-60d1fe39-offload-model-offloading-1/README.md) |
| gemma4-31b | KoboldCpp | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 21/27 | 0.524 | [2026-11-17T05:29:08.767878+00:00 · offload-model-offloading-1-9729952f4b4b](docs/results/model-offloading/campaign-20261117T052908Z-16a250ab-offload-model-offloading-1/README.md) |
| gemma4-31b | LM Studio | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 24/27 | 52.6 | [2026-11-22T03:01:32.201045+00:00 · offload-model-offloading-1-3f1d0d5d9170](docs/results/model-offloading/campaign-20261122T030132Z-4cfa054c-offload-model-offloading-1/README.md) |
| gemma4-31b | Ollama | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 24/27 | 50.3 | [2026-11-17T05:29:08.767878+00:00 · offload-model-offloading-1-3a3ebc52dbf6](docs/results/model-offloading/campaign-20261117T052908Z-16a250ab-offload-model-offloading-1/README.md) |
| kimi-dev-72b | KoboldCpp | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 0/27 | 0.626 | [2026-11-18T01:48:08.266672+00:00 · offload-model-offloading-1-2357915b8f64](docs/results/model-offloading/campaign-20261118T014808Z-cc8eec8c-offload-model-offloading-1/README.md) |
| kimi-dev-72b | LM Studio | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 0/27 | 0.577 | [2026-11-22T12:48:04.925010+00:00 · offload-model-offloading-1-e5b59b4414ba](docs/results/model-offloading/campaign-20261122T124804Z-80069b0a-offload-model-offloading-1/README.md) |
| kimi-dev-72b | Ollama | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 0/27 | 0.473 | [2026-11-18T09:18:47.453461+00:00 · offload-model-offloading-1-83cefbf471c1](docs/results/model-offloading/campaign-20261118T091847Z-e5ed63b4-offload-model-offloading-1/README.md) |
| kimi-dev-72b | Ollama | category-smoke | failed | 9 tasks × 3 measured attempts | 27/27 | 0/27 | 0.474 | [2026-11-18T01:48:08.266672+00:00 · offload-model-offloading-1-83cefbf471c1](docs/results/model-offloading/campaign-20261118T014808Z-cc8eec8c-offload-model-offloading-1/README.md) |
| kimi-linear-48b | KoboldCpp | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 24/27 | 0.524 | [2026-11-17T04:38:57.176908+00:00 · offload-model-offloading-1-0663edde83e7](docs/results/model-offloading/campaign-20261117T043857Z-d2cbbd81-offload-model-offloading-1/README.md) |
| kimi-linear-48b | LM Studio | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 24/27 | 0.0948 | [2026-11-22T00:17:56.525316+00:00 · offload-model-offloading-1-271b4a18bdab](docs/results/model-offloading/campaign-20261122T001756Z-e1adff6b-offload-model-offloading-1/README.md) |
| kimi-linear-48b | Ollama | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 24/27 | 0.0915 | [2026-11-17T04:38:57.176908+00:00 · offload-model-offloading-1-1ae17d24547e](docs/results/model-offloading/campaign-20261117T043857Z-d2cbbd81-offload-model-offloading-1/README.md) |
| laguna-xs21 | KoboldCpp | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 3/27 | 0.531 | [2026-11-17T06:17:20.323277+00:00 · offload-model-offloading-1-29fef6a4c03e](docs/results/model-offloading/campaign-20261117T061720Z-22ef705a-offload-model-offloading-1/README.md) |
| laguna-xs21 | LM Studio | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 15/27 | 15.4 | [2026-11-22T08:09:15.198976+00:00 · offload-model-offloading-1-763cbda33c3c](docs/results/model-offloading/campaign-20261122T080915Z-a8f825b0-offload-model-offloading-1/README.md) |
| laguna-xs21 | Ollama | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 21/27 | 15 | [2026-11-17T06:17:20.323277+00:00 · offload-model-offloading-1-e08cf58f281b](docs/results/model-offloading/campaign-20261117T061720Z-22ef705a-offload-model-offloading-1/README.md) |
| llama3-70b | KoboldCpp | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 15/27 | 0.566 | [2026-11-17T21:37:17.798254+00:00 · offload-model-offloading-1-cf340a409611](docs/results/model-offloading/campaign-20261117T213717Z-0797f5e5-offload-model-offloading-1/README.md) |
| llama3-70b | LM Studio | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 15/27 | 0.446 | [2026-11-22T09:47:09.688631+00:00 · offload-model-offloading-1-d4a0e8e8470a](docs/results/model-offloading/campaign-20261122T094709Z-cbbdfa68-offload-model-offloading-1/README.md) |
| llama3-70b | Ollama | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 15/27 | 0.383 | [2026-11-17T21:37:17.798254+00:00 · offload-model-offloading-1-a40c31013f27](docs/results/model-offloading/campaign-20261117T213717Z-0797f5e5-offload-model-offloading-1/README.md) |
| llama31-70b | KoboldCpp | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 12/27 | 0.566 | [2026-11-17T20:27:20.288013+00:00 · offload-model-offloading-1-1466120223c6](docs/results/model-offloading/campaign-20261117T202720Z-89dcd579-offload-model-offloading-1/README.md) |
| llama31-70b | LM Studio | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 0/27 | 0.888 | [2026-11-22T09:24:00.424942+00:00 · offload-model-offloading-1-10e3fa786966](docs/results/model-offloading/campaign-20261122T092400Z-30894afc-offload-model-offloading-1/README.md) |
| llama31-70b | Ollama | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 0/27 | 0.767 | [2026-11-17T20:27:20.288013+00:00 · offload-model-offloading-1-52df5e5eccae](docs/results/model-offloading/campaign-20261117T202720Z-89dcd579-offload-model-offloading-1/README.md) |
| llama33-70b | KoboldCpp | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 15/27 | 0.565 | [2026-11-17T21:03:08.664966+00:00 · offload-model-offloading-1-10b30d53fd20](docs/results/model-offloading/campaign-20261117T210308Z-f839a69f-offload-model-offloading-1/README.md) |
| llama33-70b | LM Studio | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 15/27 | 0.447 | [2026-11-22T09:00:27.097149+00:00 · offload-model-offloading-1-c705435db276](docs/results/model-offloading/campaign-20261122T090027Z-2fbb4fe0-offload-model-offloading-1/README.md) |
| llama33-70b | Ollama | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 15/27 | 0.386 | [2026-11-17T21:03:08.664966+00:00 · offload-model-offloading-1-bd49a015ccb1](docs/results/model-offloading/campaign-20261117T210308Z-f839a69f-offload-model-offloading-1/README.md) |
| mistral-small31 | KoboldCpp | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 6/27 | 0.544 | [2026-11-17T19:50:01.642107+00:00 · offload-model-offloading-1-4fdd4a317ab7](docs/results/model-offloading/campaign-20261117T195001Z-d94a644a-offload-model-offloading-1/README.md) |
| mistral-small31 | LM Studio | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 6/27 | 0.422 | [2026-11-22T12:21:21.407264+00:00 · offload-model-offloading-1-0c83a717d527](docs/results/model-offloading/campaign-20261122T122121Z-ad75034c-offload-model-offloading-1/README.md) |
| mistral-small31 | Ollama | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 6/27 | 0.357 | [2026-11-17T19:50:01.642107+00:00 · offload-model-offloading-1-6415edfa1ed2](docs/results/model-offloading/campaign-20261117T195001Z-d94a644a-offload-model-offloading-1/README.md) |
| nemotron-nano-30b | KoboldCpp | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 3/27 | 0.525 | [2026-11-17T06:46:06.438005+00:00 · offload-model-offloading-1-28129d927ca2](docs/results/model-offloading/campaign-20261117T064606Z-ca04bbea-offload-model-offloading-1/README.md) |
| nemotron-nano-30b | LM Studio | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 24/27 | 4.99 | [2026-11-22T00:33:48.737507+00:00 · offload-model-offloading-1-04df176a7bbb](docs/results/model-offloading/campaign-20261122T003348Z-8d8d894b-offload-model-offloading-1/README.md) |
| nemotron-nano-30b | Ollama | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 24/27 | 2.39 | [2026-11-17T06:46:06.438005+00:00 · offload-model-offloading-1-94b0edd74bf6](docs/results/model-offloading/campaign-20261117T064606Z-ca04bbea-offload-model-offloading-1/README.md) |
| nemotron-super-49b | KoboldCpp | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 15/27 | 188 | [2026-11-17T15:25:29.656314+00:00 · offload-model-offloading-1-3143d7ff5534](docs/results/model-offloading/campaign-20261117T152529Z-a4c8f742-offload-model-offloading-1/README.md) |
| nemotron-super-49b | LM Studio | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 12/27 | 228 | [2026-11-22T05:19:19.283193+00:00 · offload-model-offloading-1-fa9dc87abb1d](docs/results/model-offloading/campaign-20261122T051919Z-18802dd7-offload-model-offloading-1/README.md) |
| nemotron-super-49b | Ollama | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 12/27 | 164 | [2026-11-17T15:25:29.656314+00:00 · offload-model-offloading-1-d4bf061daedb](docs/results/model-offloading/campaign-20261117T152529Z-a4c8f742-offload-model-offloading-1/README.md) |
| phi4-reasoning-plus | KoboldCpp | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 15/27 | 0.524 | [2026-11-17T10:16:36.611138+00:00 · offload-model-offloading-1-26eb342f820d](docs/results/model-offloading/campaign-20261117T101636Z-6ef57688-offload-model-offloading-1/README.md) |
| phi4-reasoning-plus | LM Studio | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 0/27 | 0.467 | [2026-11-22T01:22:51.901483+00:00 · offload-model-offloading-1-3f84789d43f0](docs/results/model-offloading/campaign-20261122T012251Z-02ce34e6-offload-model-offloading-1/README.md) |
| phi4-reasoning-plus | Ollama | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 0/27 | 0.396 | [2026-11-17T10:16:36.611138+00:00 · offload-model-offloading-1-9a6470999bac](docs/results/model-offloading/campaign-20261117T101636Z-6ef57688-offload-model-offloading-1/README.md) |
| qwen35-35b-moe | KoboldCpp | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 18/27 | 0.636 | [2026-11-17T07:05:52.741538+00:00 · offload-model-offloading-1-2c78be84112a](docs/results/model-offloading/campaign-20261117T070552Z-eb1d47f8-offload-model-offloading-1/README.md) |
| qwen35-35b-moe | LM Studio | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 27/27 | 7.48 | [2026-11-22T08:39:21.689539+00:00 · offload-model-offloading-1-2c1d7fe5267e](docs/results/model-offloading/campaign-20261122T083921Z-1f20982a-offload-model-offloading-1/README.md) |
| qwen35-35b-moe | Ollama | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 21/27 | 13.2 | [2026-11-17T07:05:52.741538+00:00 · offload-model-offloading-1-117277261757](docs/results/model-offloading/campaign-20261117T070552Z-eb1d47f8-offload-model-offloading-1/README.md) |
| qwen38-27b | KoboldCpp | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 24/27 | 23.5 | [2026-11-17T04:47:26.017294+00:00 · offload-model-offloading-1-60da8e110b61](docs/results/model-offloading/campaign-20261117T044726Z-01d2a5a1-offload-model-offloading-1/README.md) |
| qwen38-27b | LM Studio | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 24/27 | 7.25 | [2026-11-22T01:07:25.413237+00:00 · offload-model-offloading-1-14e1a00935ac](docs/results/model-offloading/campaign-20261122T010725Z-569a049b-offload-model-offloading-1/README.md) |
| qwen38-27b | Ollama | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 24/27 | 16.1 | [2026-11-17T04:47:26.017294+00:00 · offload-model-offloading-1-f310d5966d5c](docs/results/model-offloading/campaign-20261117T044726Z-01d2a5a1-offload-model-offloading-1/README.md) |

[Run settings and experiment details](docs/results/index/recommended/raider-wsl/model-offloading.md).

<a id="runs-raider-windows"></a>

#### raider-windows

114 published jobs · windows-11-native · NVIDIA GeForce RTX 5090 Laptop GPU (24 GiB)

<a id="runs-raider-windows-decision-models"></a>

##### decision-models

| Model | Harness | Mode | Status | Workload | Completed | Checks passed | Wall time (median s) | Publication / job |
|---|---|---|---|---|---|---|---|---|
| llm-eval-nimble:locked | Ollama | decision | succeeded | 2 tasks × 3 measured attempts | 6/6 | 6/6 | 0.0602 | [2026-11-15T13:04:20.975155+00:00 · routing-llm-routing-1-389a241fd7b8](docs/results/llm-routing/campaign-20261115T130420Z-a4e6c761-routing-llm-routing-1/README.md) |
| llm-eval-nimble:locked | Ollama | decision | succeeded | 2 tasks × 3 measured attempts | 6/6 | 6/6 | 0.0496 | [2026-11-08T03:57:38.117849+00:00 · routing-llm-routing-1-389a241fd7b8](docs/results/llm-routing/campaign-20261108T035738Z-332b0246-routing-llm-routing-1/README.md) |
| llm-eval-tev1:locked | Ollama | decision | succeeded | 2 tasks × 3 measured attempts | 6/6 | 6/6 | 0.0412 | [2026-11-15T13:04:20.975155+00:00 · routing-llm-routing-1-25eff864a7d1](docs/results/llm-routing/campaign-20261115T130420Z-a4e6c761-routing-llm-routing-1/README.md) |
| llm-eval-tev1:locked | Ollama | decision | succeeded | 2 tasks × 3 measured attempts | 6/6 | 6/6 | 0.0284 | [2026-11-08T03:57:38.117849+00:00 · routing-llm-routing-1-25eff864a7d1](docs/results/llm-routing/campaign-20261108T035738Z-332b0246-routing-llm-routing-1/README.md) |

[Run settings and experiment details](docs/results/index/recommended/raider-windows/decision-models.md).

<a id="runs-raider-windows-legal-models"></a>

##### legal-models

| Model | Harness | Mode | Status | Workload | Completed | Checks passed | First text (median s) | Publication / job |
|---|---|---|---|---|---|---|---|---|
| fixture | fixture | retrieval · fixture | succeeded | 16 fictional matters | not recorded | 39/56 | not recorded | [2026-11-15T13:37:29.207211+00:00 · retrieval-legal-benchmark-1-a051474dea68](docs/results/legal-benchmark/campaign-20261115T133729Z-ff84f63f-retrieval-legal-benchmark-1/README.md) |
| llm-eval-kimi-linear-48b:locked | Ollama | score · score-only | succeeded | 16 fictional matters | not recorded | 0/32 | not recorded | [2026-11-15T14:00:33.662753+00:00 · score-legal-benchmark-1-29d5acead93f](docs/results/legal-benchmark/campaign-20261115T140033Z-ed2177f1-score-legal-benchmark-1/README.md) |
| llm-eval-kimi-linear-48b:locked | Ollama | generation · measured | succeeded | 16 fictional matters | not recorded | 0/32 | not recorded | [2026-11-15T13:37:29.207211+00:00 · generation-legal-benchmark-1-282ef17525cf](docs/results/legal-benchmark/campaign-20261115T133729Z-ff84f63f-generation-legal-benchmark-1/README.md) |
| llm-eval-kimi-linear-48b:locked | Ollama | workflow · measured | succeeded | 16 fictional matters | not recorded | 0/32 | not recorded | [2026-11-15T13:37:29.207211+00:00 · workflow-legal-benchmark-1-047c18a9ef19](docs/results/legal-benchmark/campaign-20261115T133729Z-ff84f63f-workflow-legal-benchmark-1/README.md) |

[Run settings and experiment details](docs/results/index/recommended/raider-windows/legal-models.md).

<a id="runs-raider-windows-model-offloading"></a>

##### model-offloading

| Model | Harness | Mode | Status | Workload | Completed | Checks passed | First text (median s) | Publication / job |
|---|---|---|---|---|---|---|---|---|
| deepseek-r1-32b | KoboldCpp | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 6/27 | 104 | [2026-11-15T23:02:00.194999+00:00 · offload-model-offloading-1-f98a74d7c1d6](docs/results/model-offloading/campaign-20261115T230200Z-261eec44-offload-model-offloading-1/README.md) |
| deepseek-r1-32b | KoboldCpp | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 6/27 | 82.4 | [2026-11-09T11:12:25.555879+00:00 · offload-model-offloading-1-f98a74d7c1d6](docs/results/model-offloading/campaign-20261109T111225Z-8bf20361-offload-model-offloading-1/README.md) |
| deepseek-r1-32b | LM Studio | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 6/27 | 105 | [2026-11-15T23:02:00.194999+00:00 · offload-model-offloading-1-8cd707175ee0](docs/results/model-offloading/campaign-20261115T230200Z-261eec44-offload-model-offloading-1/README.md) |
| deepseek-r1-32b | LM Studio | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 3/27 | 105 | [2026-11-09T11:12:25.555879+00:00 · offload-model-offloading-1-8cd707175ee0](docs/results/model-offloading/campaign-20261109T111225Z-8bf20361-offload-model-offloading-1/README.md) |
| deepseek-r1-32b | Ollama | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 3/27 | 89.8 | [2026-11-15T23:02:00.194999+00:00 · offload-model-offloading-1-a5f32470b1c5](docs/results/model-offloading/campaign-20261115T230200Z-261eec44-offload-model-offloading-1/README.md) |
| deepseek-r1-32b | Ollama | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 3/27 | 83.3 | [2026-11-09T11:12:25.555879+00:00 · offload-model-offloading-1-a5f32470b1c5](docs/results/model-offloading/campaign-20261109T111225Z-8bf20361-offload-model-offloading-1/README.md) |
| deepseek-r1-32b | Ollama | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 3/27 | 83.2 | [2026-11-08T14:06:51.610167+00:00 · offload-model-offloading-1-db17c5930ec0](docs/results/model-offloading/campaign-20261108T140651Z-a0b0cfdf-offload-model-offloading-1/README.md) |
| deepseek-r1-32b | Ollama | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 0/27 | 27.9 | [2026-11-08T03:57:38.117849+00:00 · offload-model-offloading-1-db17c5930ec0](docs/results/model-offloading/campaign-20261108T035738Z-332b0246-offload-model-offloading-1/README.md) |
| deepseek-r1-32b | Ollama | category-smoke | failed | 9 tasks × 3 measured attempts | 0/27 | 0/27 | not recorded | [2026-11-08T03:53:31.395544+00:00 · offload-model-offloading-1-db17c5930ec0](docs/results/model-offloading/campaign-20261108T035331Z-833eafe8-offload-model-offloading-1/README.md) |
| deepseek-r1-70b | KoboldCpp | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 3/27 | 144 | [2026-11-16T02:50:21.753757+00:00 · offload-model-offloading-1-0bb8048f47a6](docs/results/model-offloading/campaign-20261116T025021Z-920ba116-offload-model-offloading-1/README.md) |
| deepseek-r1-70b | KoboldCpp | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 3/27 | 143 | [2026-11-10T14:26:45.241321+00:00 · offload-model-offloading-1-0bb8048f47a6](docs/results/model-offloading/campaign-20261110T142645Z-46f987f0-offload-model-offloading-1/README.md) |
| deepseek-r1-70b | LM Studio | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 3/27 | 150 | [2026-11-16T02:50:21.753757+00:00 · offload-model-offloading-1-f3eeb54d9350](docs/results/model-offloading/campaign-20261116T025021Z-920ba116-offload-model-offloading-1/README.md) |
| deepseek-r1-70b | LM Studio | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 6/27 | 149 | [2026-11-10T14:26:45.241321+00:00 · offload-model-offloading-1-f3eeb54d9350](docs/results/model-offloading/campaign-20261110T142645Z-46f987f0-offload-model-offloading-1/README.md) |
| deepseek-r1-70b | Ollama | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 6/27 | 112 | [2026-11-16T02:50:21.753757+00:00 · offload-model-offloading-1-7a0671b05227](docs/results/model-offloading/campaign-20261116T025021Z-920ba116-offload-model-offloading-1/README.md) |
| deepseek-r1-70b | Ollama | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 6/27 | 112 | [2026-11-10T14:26:45.241321+00:00 · offload-model-offloading-1-7a0671b05227](docs/results/model-offloading/campaign-20261110T142645Z-46f987f0-offload-model-offloading-1/README.md) |
| gemma3-27b | KoboldCpp | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 18/27 | 0.566 | [2026-11-15T19:38:35.149051+00:00 · offload-model-offloading-1-0eaa61bbc9e3](docs/results/model-offloading/campaign-20261115T193835Z-720b0164-offload-model-offloading-1/README.md) |
| gemma3-27b | KoboldCpp | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 18/27 | 0.574 | [2026-11-09T17:14:30.068263+00:00 · offload-model-offloading-1-0eaa61bbc9e3](docs/results/model-offloading/campaign-20261109T171430Z-c1c4ab49-offload-model-offloading-1/README.md) |
| gemma3-27b | LM Studio | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 18/27 | 0.833 | [2026-11-15T19:38:35.149051+00:00 · offload-model-offloading-1-ad850e1a7450](docs/results/model-offloading/campaign-20261115T193835Z-720b0164-offload-model-offloading-1/README.md) |
| gemma3-27b | LM Studio | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 18/27 | 0.798 | [2026-11-09T17:14:30.068263+00:00 · offload-model-offloading-1-ad850e1a7450](docs/results/model-offloading/campaign-20261109T171430Z-c1c4ab49-offload-model-offloading-1/README.md) |
| gemma3-27b | Ollama | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 18/27 | 0.62 | [2026-11-15T19:38:35.149051+00:00 · offload-model-offloading-1-9a75229f3b0d](docs/results/model-offloading/campaign-20261115T193835Z-720b0164-offload-model-offloading-1/README.md) |
| gemma3-27b | Ollama | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 18/27 | 0.612 | [2026-11-09T17:14:30.068263+00:00 · offload-model-offloading-1-9a75229f3b0d](docs/results/model-offloading/campaign-20261109T171430Z-c1c4ab49-offload-model-offloading-1/README.md) |
| gemma4-26b-moe | KoboldCpp | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 21/27 | 0.582 | [2026-11-15T16:11:12.164523+00:00 · offload-model-offloading-1-38ffad82cecc](docs/results/model-offloading/campaign-20261115T161112Z-fff50610-offload-model-offloading-1/README.md) |
| gemma4-26b-moe | KoboldCpp | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 21/27 | 0.576 | [2026-11-11T11:02:34.257275+00:00 · offload-model-offloading-1-38ffad82cecc](docs/results/model-offloading/campaign-20261111T110234Z-68c0f219-offload-model-offloading-1/README.md) |
| gemma4-26b-moe | LM Studio | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 21/27 | 14.1 | [2026-11-15T16:11:12.164523+00:00 · offload-model-offloading-1-a02fb7d85449](docs/results/model-offloading/campaign-20261115T161112Z-fff50610-offload-model-offloading-1/README.md) |
| gemma4-26b-moe | LM Studio | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 21/27 | 14.2 | [2026-11-11T11:02:34.257275+00:00 · offload-model-offloading-1-a02fb7d85449](docs/results/model-offloading/campaign-20261111T110234Z-68c0f219-offload-model-offloading-1/README.md) |
| gemma4-26b-moe | Ollama | category-smoke | failed | not recorded | not recorded | unscored | not recorded | [2026-11-15T16:11:12.164523+00:00 · offload-model-offloading-1-f39ebde89ef6](docs/results/model-offloading/campaign-20261115T161112Z-fff50610-offload-model-offloading-1/README.md) |
| gemma4-26b-moe | Ollama | category-smoke | failed | not recorded | not recorded | unscored | not recorded | [2026-11-11T11:02:34.257275+00:00 · offload-model-offloading-1-f39ebde89ef6](docs/results/model-offloading/campaign-20261111T110234Z-68c0f219-offload-model-offloading-1/README.md) |
| gemma4-31b | KoboldCpp | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 21/27 | 0.581 | [2026-11-15T14:36:06.640631+00:00 · offload-model-offloading-1-44feab011446](docs/results/model-offloading/campaign-20261115T143606Z-03f6333f-offload-model-offloading-1/README.md) |
| gemma4-31b | KoboldCpp | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 21/27 | 0.582 | [2026-11-09T15:43:41.594209+00:00 · offload-model-offloading-1-44feab011446](docs/results/model-offloading/campaign-20261109T154341Z-1e8d354f-offload-model-offloading-1/README.md) |
| gemma4-31b | LM Studio | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 24/27 | 58.4 | [2026-11-15T14:36:06.640631+00:00 · offload-model-offloading-1-814628ba9504](docs/results/model-offloading/campaign-20261115T143606Z-03f6333f-offload-model-offloading-1/README.md) |
| gemma4-31b | LM Studio | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 24/27 | 59.7 | [2026-11-09T15:43:41.594209+00:00 · offload-model-offloading-1-814628ba9504](docs/results/model-offloading/campaign-20261109T154341Z-1e8d354f-offload-model-offloading-1/README.md) |
| gemma4-31b | Ollama | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 24/27 | 49.9 | [2026-11-15T14:36:06.640631+00:00 · offload-model-offloading-1-19937807a7ec](docs/results/model-offloading/campaign-20261115T143606Z-03f6333f-offload-model-offloading-1/README.md) |
| gemma4-31b | Ollama | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 24/27 | 51.3 | [2026-11-09T18:02:47.256496+00:00 · offload-model-offloading-1-19937807a7ec](docs/results/model-offloading/campaign-20261109T180247Z-c38f462b-offload-model-offloading-1/README.md) |
| gemma4-31b | Ollama | category-smoke | failed | 9 tasks × 3 measured attempts | 27/27 | 24/27 | 51.2 | [2026-11-09T15:43:41.594209+00:00 · offload-model-offloading-1-19937807a7ec](docs/results/model-offloading/campaign-20261109T154341Z-1e8d354f-offload-model-offloading-1/README.md) |
| kimi-dev-72b | KoboldCpp | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 0/27 | 0.666 | [2026-11-16T08:06:05.272633+00:00 · offload-model-offloading-1-7274223fc38b](docs/results/model-offloading/campaign-20261116T080605Z-9fa41c54-offload-model-offloading-1/README.md) |
| kimi-dev-72b | KoboldCpp | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 0/27 | 0.646 | [2026-11-10T19:41:47.897604+00:00 · offload-model-offloading-1-7274223fc38b](docs/results/model-offloading/campaign-20261110T194147Z-d3ca2090-offload-model-offloading-1/README.md) |
| kimi-dev-72b | LM Studio | category-smoke | failed | 9 tasks × 3 measured attempts | 27/27 | 0/27 | 0.566 | [2026-11-16T08:06:05.272633+00:00 · offload-model-offloading-1-d23d1c519653](docs/results/model-offloading/campaign-20261116T080605Z-9fa41c54-offload-model-offloading-1/README.md) |
| kimi-dev-72b | LM Studio | category-smoke | failed | 9 tasks × 3 measured attempts | 27/27 | 0/27 | 0.572 | [2026-11-10T19:41:47.897604+00:00 · offload-model-offloading-1-d23d1c519653](docs/results/model-offloading/campaign-20261110T194147Z-d3ca2090-offload-model-offloading-1/README.md) |
| kimi-dev-72b | Ollama | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 0/27 | 0.468 | [2026-11-16T08:06:05.272633+00:00 · offload-model-offloading-1-d5ee683b6c7c](docs/results/model-offloading/campaign-20261116T080605Z-9fa41c54-offload-model-offloading-1/README.md) |
| kimi-dev-72b | Ollama | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 0/27 | 0.475 | [2026-11-10T19:41:47.897604+00:00 · offload-model-offloading-1-d5ee683b6c7c](docs/results/model-offloading/campaign-20261110T194147Z-d3ca2090-offload-model-offloading-1/README.md) |
| kimi-linear-48b | KoboldCpp | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 24/27 | 0.574 | [2026-11-15T14:02:13.970774+00:00 · offload-model-offloading-1-82c7918309af](docs/results/model-offloading/campaign-20261115T140213Z-85f189ba-offload-model-offloading-1/README.md) |
| kimi-linear-48b | KoboldCpp | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 24/27 | 0.571 | [2026-11-10T11:13:00.463564+00:00 · offload-model-offloading-1-82c7918309af](docs/results/model-offloading/campaign-20261110T111300Z-172c453b-offload-model-offloading-1/README.md) |
| kimi-linear-48b | LM Studio | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 24/27 | 0.0946 | [2026-11-15T14:02:13.970774+00:00 · offload-model-offloading-1-fdca39ed8f98](docs/results/model-offloading/campaign-20261115T140213Z-85f189ba-offload-model-offloading-1/README.md) |
| kimi-linear-48b | LM Studio | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 24/27 | 0.0922 | [2026-11-10T11:13:00.463564+00:00 · offload-model-offloading-1-fdca39ed8f98](docs/results/model-offloading/campaign-20261110T111300Z-172c453b-offload-model-offloading-1/README.md) |
| kimi-linear-48b | Ollama | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 24/27 | 0.0937 | [2026-11-15T14:02:13.970774+00:00 · offload-model-offloading-1-400d91c422e5](docs/results/model-offloading/campaign-20261115T140213Z-85f189ba-offload-model-offloading-1/README.md) |
| kimi-linear-48b | Ollama | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 24/27 | 0.1 | [2026-11-10T11:13:00.463564+00:00 · offload-model-offloading-1-400d91c422e5](docs/results/model-offloading/campaign-20261110T111300Z-172c453b-offload-model-offloading-1/README.md) |
| laguna-xs21 | KoboldCpp | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 3/27 | 0.579 | [2026-11-15T16:40:43.760423+00:00 · offload-model-offloading-1-935056637371](docs/results/model-offloading/campaign-20261115T164043Z-6fc5883d-offload-model-offloading-1/README.md) |
| laguna-xs21 | KoboldCpp | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 3/27 | 0.581 | [2026-11-10T10:27:03.750807+00:00 · offload-model-offloading-1-935056637371](docs/results/model-offloading/campaign-20261110T102703Z-ee68ff15-offload-model-offloading-1/README.md) |
| laguna-xs21 | LM Studio | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 12/27 | 15.3 | [2026-11-15T16:40:43.760423+00:00 · offload-model-offloading-1-de7260ca9c77](docs/results/model-offloading/campaign-20261115T164043Z-6fc5883d-offload-model-offloading-1/README.md) |
| laguna-xs21 | LM Studio | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 15/27 | 15.5 | [2026-11-10T10:27:03.750807+00:00 · offload-model-offloading-1-de7260ca9c77](docs/results/model-offloading/campaign-20261110T102703Z-ee68ff15-offload-model-offloading-1/README.md) |
| laguna-xs21 | Ollama | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 15/27 | 12.1 | [2026-11-15T16:40:43.760423+00:00 · offload-model-offloading-1-2506bfe7a950](docs/results/model-offloading/campaign-20261115T164043Z-6fc5883d-offload-model-offloading-1/README.md) |
| laguna-xs21 | Ollama | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 15/27 | 11.9 | [2026-11-10T10:27:03.750807+00:00 · offload-model-offloading-1-2506bfe7a950](docs/results/model-offloading/campaign-20261110T102703Z-ee68ff15-offload-model-offloading-1/README.md) |
| llama3-70b | KoboldCpp | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 15/27 | 0.615 | [2026-11-15T21:52:31.111711+00:00 · offload-model-offloading-1-c2e750a5613c](docs/results/model-offloading/campaign-20261115T215231Z-b6016170-offload-model-offloading-1/README.md) |
| llama3-70b | KoboldCpp | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 15/27 | 0.61 | [2026-11-10T13:07:29.736928+00:00 · offload-model-offloading-1-c2e750a5613c](docs/results/model-offloading/campaign-20261110T130729Z-161fd0ce-offload-model-offloading-1/README.md) |
| llama3-70b | LM Studio | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 15/27 | 0.477 | [2026-11-15T21:52:31.111711+00:00 · offload-model-offloading-1-efa5ea7463d1](docs/results/model-offloading/campaign-20261115T215231Z-b6016170-offload-model-offloading-1/README.md) |
| llama3-70b | LM Studio | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 15/27 | 0.455 | [2026-11-10T13:07:29.736928+00:00 · offload-model-offloading-1-efa5ea7463d1](docs/results/model-offloading/campaign-20261110T130729Z-161fd0ce-offload-model-offloading-1/README.md) |
| llama3-70b | Ollama | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 15/27 | 0.462 | [2026-11-15T21:52:31.111711+00:00 · offload-model-offloading-1-fcb1df403f7f](docs/results/model-offloading/campaign-20261115T215231Z-b6016170-offload-model-offloading-1/README.md) |
| llama3-70b | Ollama | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 15/27 | 0.396 | [2026-11-10T13:07:29.736928+00:00 · offload-model-offloading-1-fcb1df403f7f](docs/results/model-offloading/campaign-20261110T130729Z-161fd0ce-offload-model-offloading-1/README.md) |
| llama31-70b | KoboldCpp | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 12/27 | 0.606 | [2026-11-15T21:05:03.224807+00:00 · offload-model-offloading-1-b9f131a1a9c3](docs/results/model-offloading/campaign-20261115T210503Z-4b066e90-offload-model-offloading-1/README.md) |
| llama31-70b | KoboldCpp | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 12/27 | 0.609 | [2026-11-10T12:23:14.550777+00:00 · offload-model-offloading-1-b9f131a1a9c3](docs/results/model-offloading/campaign-20261110T122314Z-d7f8e7e5-offload-model-offloading-1/README.md) |
| llama31-70b | LM Studio | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 0/27 | 0.92 | [2026-11-15T21:05:03.224807+00:00 · offload-model-offloading-1-c10fd55e6c38](docs/results/model-offloading/campaign-20261115T210503Z-4b066e90-offload-model-offloading-1/README.md) |
| llama31-70b | LM Studio | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 0/27 | 0.891 | [2026-11-10T12:23:14.550777+00:00 · offload-model-offloading-1-c10fd55e6c38](docs/results/model-offloading/campaign-20261110T122314Z-d7f8e7e5-offload-model-offloading-1/README.md) |
| llama31-70b | Ollama | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 0/27 | 0.783 | [2026-11-15T21:05:03.224807+00:00 · offload-model-offloading-1-ca78ec6a2979](docs/results/model-offloading/campaign-20261115T210503Z-4b066e90-offload-model-offloading-1/README.md) |
| llama31-70b | Ollama | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 0/27 | 0.756 | [2026-11-10T12:23:14.550777+00:00 · offload-model-offloading-1-ca78ec6a2979](docs/results/model-offloading/campaign-20261110T122314Z-d7f8e7e5-offload-model-offloading-1/README.md) |
| llama33-70b | KoboldCpp | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 15/27 | 0.614 | [2026-11-15T20:15:25.393388+00:00 · offload-model-offloading-1-2974ef96487f](docs/results/model-offloading/campaign-20261115T201525Z-d393f04a-offload-model-offloading-1/README.md) |
| llama33-70b | KoboldCpp | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 15/27 | 0.615 | [2026-11-10T11:36:59.213334+00:00 · offload-model-offloading-1-2974ef96487f](docs/results/model-offloading/campaign-20261110T113659Z-f9bb2ca8-offload-model-offloading-1/README.md) |
| llama33-70b | LM Studio | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 15/27 | 0.479 | [2026-11-15T20:15:25.393388+00:00 · offload-model-offloading-1-0390c62a7124](docs/results/model-offloading/campaign-20261115T201525Z-d393f04a-offload-model-offloading-1/README.md) |
| llama33-70b | LM Studio | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 15/27 | 0.455 | [2026-11-10T11:36:59.213334+00:00 · offload-model-offloading-1-0390c62a7124](docs/results/model-offloading/campaign-20261110T113659Z-f9bb2ca8-offload-model-offloading-1/README.md) |
| llama33-70b | Ollama | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 15/27 | 0.414 | [2026-11-15T20:15:25.393388+00:00 · offload-model-offloading-1-691c92382f24](docs/results/model-offloading/campaign-20261115T201525Z-d393f04a-offload-model-offloading-1/README.md) |
| llama33-70b | Ollama | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 15/27 | 0.394 | [2026-11-10T11:36:59.213334+00:00 · offload-model-offloading-1-691c92382f24](docs/results/model-offloading/campaign-20261110T113659Z-f9bb2ca8-offload-model-offloading-1/README.md) |
| mistral-small31 | KoboldCpp | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 6/27 | 0.583 | [2026-11-15T18:49:31.853876+00:00 · offload-model-offloading-1-129abf22eb9d](docs/results/model-offloading/campaign-20261115T184931Z-b2407d9b-offload-model-offloading-1/README.md) |
| mistral-small31 | KoboldCpp | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 6/27 | 0.583 | [2026-11-10T08:34:34.409387+00:00 · offload-model-offloading-1-129abf22eb9d](docs/results/model-offloading/campaign-20261110T083434Z-6ad3fdfe-offload-model-offloading-1/README.md) |
| mistral-small31 | LM Studio | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 6/27 | 0.46 | [2026-11-15T18:49:31.853876+00:00 · offload-model-offloading-1-d7be41a213b0](docs/results/model-offloading/campaign-20261115T184931Z-b2407d9b-offload-model-offloading-1/README.md) |
| mistral-small31 | LM Studio | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 6/27 | 0.451 | [2026-11-10T08:34:34.409387+00:00 · offload-model-offloading-1-d7be41a213b0](docs/results/model-offloading/campaign-20261110T083434Z-6ad3fdfe-offload-model-offloading-1/README.md) |
| mistral-small31 | Ollama | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 6/27 | 0.369 | [2026-11-15T18:49:31.853876+00:00 · offload-model-offloading-1-7fe65a7e7e83](docs/results/model-offloading/campaign-20261115T184931Z-b2407d9b-offload-model-offloading-1/README.md) |
| mistral-small31 | Ollama | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 6/27 | 0.363 | [2026-11-10T08:34:34.409387+00:00 · offload-model-offloading-1-7fe65a7e7e83](docs/results/model-offloading/campaign-20261110T083434Z-6ad3fdfe-offload-model-offloading-1/README.md) |
| nemotron-nano-30b | KoboldCpp | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 3/27 | 0.58 | [2026-11-15T17:29:56.449469+00:00 · offload-model-offloading-1-d181c9d1571a](docs/results/model-offloading/campaign-20261115T172956Z-1be0350b-offload-model-offloading-1/README.md) |
| nemotron-nano-30b | KoboldCpp | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 3/27 | 0.582 | [2026-11-09T17:49:15.300387+00:00 · offload-model-offloading-1-d181c9d1571a](docs/results/model-offloading/campaign-20261109T174915Z-128e3dcf-offload-model-offloading-1/README.md) |
| nemotron-nano-30b | LM Studio | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 24/27 | 4.53 | [2026-11-15T17:29:56.449469+00:00 · offload-model-offloading-1-efb881da8017](docs/results/model-offloading/campaign-20261115T172956Z-1be0350b-offload-model-offloading-1/README.md) |
| nemotron-nano-30b | LM Studio | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 24/27 | 4.3 | [2026-11-09T17:49:15.300387+00:00 · offload-model-offloading-1-efb881da8017](docs/results/model-offloading/campaign-20261109T174915Z-128e3dcf-offload-model-offloading-1/README.md) |
| nemotron-nano-30b | Ollama | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 24/27 | 2.27 | [2026-11-15T17:29:56.449469+00:00 · offload-model-offloading-1-0ea783c16fdf](docs/results/model-offloading/campaign-20261115T172956Z-1be0350b-offload-model-offloading-1/README.md) |
| nemotron-nano-30b | Ollama | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 24/27 | 2.22 | [2026-11-09T17:49:15.300387+00:00 · offload-model-offloading-1-0ea783c16fdf](docs/results/model-offloading/campaign-20261109T174915Z-128e3dcf-offload-model-offloading-1/README.md) |
| nemotron-super-49b | KoboldCpp | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 15/27 | 181 | [2026-11-16T20:10:01.097584+00:00 · offload-model-offloading-1-e10f80682fcb](docs/results/model-offloading/campaign-20261116T201001Z-56cd5073-offload-model-offloading-1/README.md) |
| nemotron-super-49b | KoboldCpp | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 15/27 | 182 | [2026-11-09T18:48:09.860085+00:00 · offload-model-offloading-1-e10f80682fcb](docs/results/model-offloading/campaign-20261109T184809Z-c073d721-offload-model-offloading-1/README.md) |
| nemotron-super-49b | LM Studio | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 9/27 | 192 | [2026-11-16T20:10:01.097584+00:00 · offload-model-offloading-1-39784eb03258](docs/results/model-offloading/campaign-20261116T201001Z-56cd5073-offload-model-offloading-1/README.md) |
| nemotron-super-49b | LM Studio | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 12/27 | 219 | [2026-11-09T18:48:09.860085+00:00 · offload-model-offloading-1-39784eb03258](docs/results/model-offloading/campaign-20261109T184809Z-c073d721-offload-model-offloading-1/README.md) |
| nemotron-super-49b | Ollama | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 12/27 | 144 | [2026-11-16T20:10:01.097584+00:00 · offload-model-offloading-1-f8f3b4e3e15b](docs/results/model-offloading/campaign-20261116T201001Z-56cd5073-offload-model-offloading-1/README.md) |
| nemotron-super-49b | Ollama | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 12/27 | 144 | [2026-11-09T18:48:09.860085+00:00 · offload-model-offloading-1-f8f3b4e3e15b](docs/results/model-offloading/campaign-20261109T184809Z-c073d721-offload-model-offloading-1/README.md) |
| phi4-reasoning-plus | KoboldCpp | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 15/27 | 0.574 | [2026-11-16T13:32:13.817510+00:00 · offload-model-offloading-1-daebf80475d1](docs/results/model-offloading/campaign-20261116T133213Z-8dbe93fd-offload-model-offloading-1/README.md) |
| phi4-reasoning-plus | KoboldCpp | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 15/27 | 0.584 | [2026-11-10T01:40:22.002998+00:00 · offload-model-offloading-1-daebf80475d1](docs/results/model-offloading/campaign-20261110T014022Z-9e4b4e08-offload-model-offloading-1/README.md) |
| phi4-reasoning-plus | LM Studio | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 0/27 | 0.488 | [2026-11-16T13:32:13.817510+00:00 · offload-model-offloading-1-dbb471ed01d8](docs/results/model-offloading/campaign-20261116T133213Z-8dbe93fd-offload-model-offloading-1/README.md) |
| phi4-reasoning-plus | LM Studio | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 0/27 | 0.494 | [2026-11-10T01:40:22.002998+00:00 · offload-model-offloading-1-dbb471ed01d8](docs/results/model-offloading/campaign-20261110T014022Z-9e4b4e08-offload-model-offloading-1/README.md) |
| phi4-reasoning-plus | Ollama | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 0/27 | 0.404 | [2026-11-16T13:32:13.817510+00:00 · offload-model-offloading-1-7f239688f788](docs/results/model-offloading/campaign-20261116T133213Z-8dbe93fd-offload-model-offloading-1/README.md) |
| phi4-reasoning-plus | Ollama | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 0/27 | 0.396 | [2026-11-10T01:40:22.002998+00:00 · offload-model-offloading-1-7f239688f788](docs/results/model-offloading/campaign-20261110T014022Z-9e4b4e08-offload-model-offloading-1/README.md) |
| qwen35-35b-moe | KoboldCpp | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 18/27 | 0.573 | [2026-11-15T18:00:32.957722+00:00 · offload-model-offloading-1-3440c611be06](docs/results/model-offloading/campaign-20261115T180032Z-22d1b837-offload-model-offloading-1/README.md) |
| qwen35-35b-moe | KoboldCpp | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 18/27 | 0.581 | [2026-11-10T09:45:56.493890+00:00 · offload-model-offloading-1-3440c611be06](docs/results/model-offloading/campaign-20261110T094556Z-ba2a02ce-offload-model-offloading-1/README.md) |
| qwen35-35b-moe | LM Studio | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 21/27 | 7.65 | [2026-11-15T18:00:32.957722+00:00 · offload-model-offloading-1-dccf5345b081](docs/results/model-offloading/campaign-20261115T180032Z-22d1b837-offload-model-offloading-1/README.md) |
| qwen35-35b-moe | LM Studio | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 24/27 | 7.08 | [2026-11-10T09:45:56.493890+00:00 · offload-model-offloading-1-dccf5345b081](docs/results/model-offloading/campaign-20261110T094556Z-ba2a02ce-offload-model-offloading-1/README.md) |
| qwen35-35b-moe | Ollama | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 21/27 | 12 | [2026-11-15T18:00:32.957722+00:00 · offload-model-offloading-1-11dcd9c81ae3](docs/results/model-offloading/campaign-20261115T180032Z-22d1b837-offload-model-offloading-1/README.md) |
| qwen35-35b-moe | Ollama | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 21/27 | 11.3 | [2026-11-10T09:45:56.493890+00:00 · offload-model-offloading-1-11dcd9c81ae3](docs/results/model-offloading/campaign-20261110T094556Z-ba2a02ce-offload-model-offloading-1/README.md) |
| qwen38-27b | KoboldCpp | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 24/27 | 24.3 | [2026-11-15T22:24:22.141203+00:00 · offload-model-offloading-1-a9c9aeebbc4d](docs/results/model-offloading/campaign-20261115T222422Z-7671e746-offload-model-offloading-1/README.md) |
| qwen38-27b | KoboldCpp | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 24/27 | 23.7 | [2026-11-09T14:52:55.092230+00:00 · offload-model-offloading-1-a9c9aeebbc4d](docs/results/model-offloading/campaign-20261109T145255Z-9e9ae761-offload-model-offloading-1/README.md) |
| qwen38-27b | LM Studio | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 24/27 | 7.46 | [2026-11-15T22:24:22.141203+00:00 · offload-model-offloading-1-fac3127225ae](docs/results/model-offloading/campaign-20261115T222422Z-7671e746-offload-model-offloading-1/README.md) |
| qwen38-27b | LM Studio | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 24/27 | 7.27 | [2026-11-09T14:52:55.092230+00:00 · offload-model-offloading-1-fac3127225ae](docs/results/model-offloading/campaign-20261109T145255Z-9e9ae761-offload-model-offloading-1/README.md) |
| qwen38-27b | Ollama | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 24/27 | 17.2 | [2026-11-15T22:24:22.141203+00:00 · offload-model-offloading-1-e1feb0ce918f](docs/results/model-offloading/campaign-20261115T222422Z-7671e746-offload-model-offloading-1/README.md) |
| qwen38-27b | Ollama | category-smoke | succeeded | 9 tasks × 3 measured attempts | 27/27 | 24/27 | 16.6 | [2026-11-09T14:52:55.092230+00:00 · offload-model-offloading-1-e1feb0ce918f](docs/results/model-offloading/campaign-20261109T145255Z-9e9ae761-offload-model-offloading-1/README.md) |

[Run settings and experiment details](docs/results/index/recommended/raider-windows/model-offloading.md).

<a id="runs-raider-ubuntu"></a>

#### raider-ubuntu

1 published job · ubuntu-26.04-native · NVIDIA GeForce RTX 5090 Laptop GPU (24 GiB)

<a id="runs-raider-ubuntu-decision-models"></a>

##### decision-models

| Model | Harness | Mode | Status | Workload | Completed | Checks passed | Wall time (median s) | Publication / job |
|---|---|---|---|---|---|---|---|---|
| category | category | decision · fixture | succeeded | 2 tasks × 1 measured attempts | 2/2 | 2/2 | 3.39e-05 | [2026-11-08T01:38:14.202071+00:00 · routing-llm-routing-1-290257f5d5ab](docs/results/llm-routing/campaign-20261108T013814Z-7ff2610d-routing-llm-routing-1/README.md) |

[Run settings and experiment details](docs/results/index/recommended/raider-ubuntu/decision-models.md).

[Browse by model, date or runtime](docs/results/index/README.md) · [US model results](docs/results/index/origin/us.md).

<!-- summary-recommended:end -->

## Start here

- **Choosing a local model?** Start with the [measured results](#measured-results) and check which runtime, prompt length and hardware were tested.
- **Running a test?** [Reproduce a published run](docs/REPRODUCE.md) or [contribute a result on another machine](docs/HARDWARE_PARTICIPATION.md).
- **Comparing results?** Open the [matched settings and download links](docs/results/index/recommended/README.md), or browse [individual runs by model or date](docs/results/index/README.md).

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
