# Platform setup and compatibility

Use the [interactive/CLI installers and run scripts](WORKFLOWS.md) for the pinned recipes. This page explains compatibility and manual tuning. Install one pinned engine at a time in a separate checkout/environment. Keep a working driver before experimenting with model packages. Upstream OS support does not establish support for Ubuntu 26.04, Blackwell sm_120, every listed model, or every quantization kernel.

## OS matrix

| Platform | Ubuntu 26.04 native | Windows 11 native | Windows + WSL2 Ubuntu |
|---|---|---|---|
| llama.cpp | CUDA build path; validate selected model | CUDA build path | Conditional: WSL memory/IO |
| ik_llama.cpp | CPU/CUDA build path | CPU/CUDA build path | Conditional |
| KTransformers | Conditional model recipe and CPU kernels | **Upstream temporarily deprecated; skipped** | Conditional |
| Ollama | Native service | Native application/service | Conditional |
| KoboldCpp | Linux executable or build | Windows executable or build | Conditional |
| Accelerate | Conditional on Torch/model/quantization | Conditional on Torch/model/quantization | Conditional |
| AirLLM | Experimental, loader review required | Unverified, not claimed supported | Experimental |
| vLLM | Linux build/wheel path; validate Blackwell offload | **Unsupported upstream; skipped** | Conditional, pinned-memory path must be checked |
| Strata | Prebuilt path or manually prepared compatible toolkit | Native engine path | Conditional; audited installer disables KV streaming |

Primary evidence: [llama.cpp](https://github.com/ggml-org/llama.cpp), [ik_llama.cpp](https://github.com/ikawrakow/ik_llama.cpp), [KTransformers installation](https://github.com/kvcache-ai/ktransformers/blob/main/doc/en/install.md), [Ollama FAQ](https://docs.ollama.com/faq), [KoboldCpp](https://github.com/LostRuins/koboldcpp), [Accelerate offloading](https://huggingface.co/docs/accelerate/main/en/concept_guides/big_model_inference), [AirLLM](https://github.com/lyogavin/airllm), [vLLM GPU installation](https://docs.vllm.ai/en/latest/getting_started/installation/gpu/), [Strata audited setup](https://github.com/Niko1221/Strata/blob/6f32ec070f23ced9f50e704d854d775da52591ab/setup.py).

## NVIDIA and filesystem setup

Native Linux Blackwell uses NVIDIA's **open kernel modules**, plus its CUDA userspace stack. Ubuntu 26.04 is in NVIDIA's current qualification documentation. Use a coherent supported package-managed stack and retain signed-module/Secure Boot support. WSL uses the **Windows NVIDIA driver**: do not install a Linux NVIDIA kernel/display driver inside WSL. Toolkit/runtime requirements differ by backend; a toolkit qualified for Ubuntu 26.04 is not proof that a particular engine has been validated with it.

Sources: [NVIDIA open modules](https://download.nvidia.com/XFree86/Linux-x86_64/610.43.02/README/kernel_open.html), [CUDA Linux guide](https://docs.nvidia.com/cuda/cuda-installation-guide-linux/), [CUDA WSL guide](https://docs.nvidia.com/cuda/wsl-user-guide/). No driver installer is included in this project.

Use native Linux ext4/XFS or native Windows NTFS on the SN7100. For WSL, put models in its ext4 filesystem, with VHDX storage on the SN7100. Record the exact mount. Do not compare an ext4 run against `/mnt/c` without identifying the extra filesystem variable. Keep enough free space for the selected weights, converted artifacts, and temporary layer shards.

## llama.cpp and ik_llama.cpp

Clone the selected upstream, check out a **full commit**, and build with its documented CUDA option. For a current llama.cpp-style CMake build:

```bash
cmake -S . -B build -DGGML_CUDA=ON -DCMAKE_BUILD_TYPE=Release
cmake --build build --config Release -j 8
```

Use the matching host compiler/toolkit; Windows generally uses Visual Studio build tools. Executable placement differs on Windows. Verify the pinned binary's `--help`: fork flags can differ.

Illustrative llama.cpp start, from its checkout, with an already selected GGUF:

```bash
./build/bin/llama-server -m /path/to/model.gguf \
  --host 127.0.0.1 --port 8100 --ctx-size 8192 --parallel 1 \
  --gpu-layers auto --fit-target 2048 --threads 15
```

Confirm the context and placement actually selected by automatic fitting. For supported MoE architectures, compare `--cpu-moe` / `--n-cpu-moe` to automatic placement; these are not dense-model tuning flags. For ik_llama.cpp, consult its own `--fit` and tensor-placement documentation. Do not blindly enable repacking (`-rtr`) on a CPU/GPU hybrid run: the project warns that some formats then cannot use CUDA for those tensors.

Set `endpoint` to the full `/v1/chat/completions` URL and fill `backend_pid`, `backend_version`, `placement_notes`, and actual active template hash. Record the startup log's loaded GGUF and offloaded layers. The harness does not trust a server-reported name as proof of identity.

## Ollama

Disable cloud features for this local benchmark (`OLLAMA_NO_CLOUD=1`) and keep the service local. For controlled GGUF comparisons, import the **same file**, rather than assuming a similarly named registry tag has the same weights. An illustrative Modelfile:

```text
FROM /absolute/path/to/model.gguf
PARAMETER num_ctx 8192
PARAMETER num_predict 256
PARAMETER temperature 0
```

Create the model with `ollama create eval-model -f Modelfile`, record its digest and actual template (`ollama show eval-model --modelfile`), then set `served_model` to `eval-model`. Templates/default system prompts can differ from other engines; compare and align them. `ollama ps` reports CPU/GPU placement. Use the native `http://127.0.0.1:11434/api/chat` endpoint so the harness can capture prompt/eval counts and durations.

## KoboldCpp

Use a pinned official release or source build appropriate to your OS/GPU. Select the exact GGUF, CUDA backend, context 8192, and explicit GPU-layer/CPU-thread placement in its launcher. Bind to loopback, disable optional agents/tools, record all launcher options, and use its OpenAI-compatible `/v1/chat/completions` endpoint. Some versions do not provide streaming usage; `request_usage=false` is the example default. Missing usage stays unknown, not a fabricated token rate. Check actual endpoint behavior before running a full suite.

## KTransformers

Use the upstream **model-specific** Linux/WSL recipe and serving mode; recent source separates `kt-kernel` capabilities and integrations. Select an AVX2-capable path for the 285HX. AMX or AVX-512 server results do not predict this laptop's behavior. Check whether the exact architecture and CPU quantization are supported before selecting a checkpoint.

Expose the recipe's OpenAI-compatible endpoint, enter its full URL in the example, and record the kernel/serving integration versions separately in `placement_notes`. The managed launcher uses the SGLang KT integration and requires a model-specific method and CPU weight path; it does not claim every catalog model works. Native Windows is excluded under the documented upstream status, rather than silently substituted with WSL.

## vLLM

Use an upstream-supported Linux/WSL environment and PyTorch/CUDA build appropriate to sm_120. Native Windows is skipped. CPU offload does not imply CPU execution of those weights: it can involve GPU access/transfers each forward pass. Current upstream documentation describes both UVA and asynchronous prefetch approaches; use the pinned version's actual flags and quantization support.

Start the local server with the selected model, loopback host, one active sequence, explicit context, and reviewed CPU-offload settings. Typical controls to inspect are `--max-model-len`, `--max-num-seqs`, `--gpu-memory-utilization`, and `--cpu-offload-gb`. Do not turn `--cpu-offload-gb` into an assertion that the laptop has that much extra VRAM. Native quantized kernels and CPU-side storage must be verified for each model; dequantization can destroy the memory budget.

On WSL, consult the pinned version's `VLLM_WSL2_ENABLE_PIN_MEMORY` behavior before using UVA/offload. Do not automatically turn it on based solely on a generic recipe. Sources: [engine arguments](https://docs.vllm.ai/en/latest/configuration/engine_args/), [environment variables](https://docs.vllm.ai/en/latest/configuration/env_vars/).

## Hugging Face Accelerate

Install the project, a Blackwell-compatible PyTorch build, Transformers, and Accelerate in a dedicated environment; record exact installed versions. Point `worker_python` at that environment's Python executable and `artifact_root` at a complete local snapshot. The worker sets offline modes, loads with `device_map="auto"`, supplies explicit memory budgets, and uses local files only.

Choose `loader_class` appropriate to the model: `AutoModelForCausalLM`, `AutoModelForImageTextToText`, or `AutoModelForMultimodalLM`, if available in the pinned Transformers release. Text input is the initial scope; multimodal templates may require additional model-specific adaptation. `reviewed_model_code` defaults false. A model requiring custom code will fail until a pinned source review has been performed and the opt-in recorded.

Do not load unquantized 70B/120B weights into this machine while expecting the loader budget to make them small. Use a supported quantized checkpoint whose CPU-offload representation remains compact, or a feasible BF16 model such as the 26B/16B precision controls. A GGUF selected for llama.cpp is not interchangeable with this loader's native checkpoint.

The worker measures nonstreaming generation, including prefill. TTFT and pure decode throughput are null. The parent separately records process load time and end-to-end request wall time. `allow_disk_offload=true` requires `lane="disk"`.

## AirLLM

Use a separate environment containing the pinned AirLLM implementation, its required Transformers/PyTorch versions, and this harness. Review the loader and set `reviewed_airllm_source=true` only after that review. Set `worker_python`, complete local `artifact_root`, and a dedicated writable `offload_dir`. The worker calls AirLLM's `AutoModel.from_pretrained` and its ordinary `generate` API. This integration is implemented but **not GPU-tested** in this repository; library/API/model compatibility must pass the smoke gate.

AirLLM can create layer shards and requires additional disk capacity. Its example uses the disk lane. Do not treat a successful tiny-VRAM load as evidence of interactive speed or memory-only residency. Results have no TTFT because the ordinary call does not expose streamed timing to this adapter. Offline environment flags are not a security boundary; loader review and OS isolation still matter.

## Strata

The reviewed engine commit is `6f32ec070f23ced9f50e704d854d775da52591ab`. It targets Qwen3.8-Flash-Next and related prepared variants. The matrix skips other model families. Use the project's own setup for **IQ2_XS**, initially 8192 context, int8 KV, one request, 2048 MiB VRAM reserve, no vision/MCP, and loopback plus authentication. Verify option names against the pinned `setup.py --help`; record final `config.json` settings and all converted artifact hashes.

Ubuntu 26.04's official NVIDIA support does not fix this audited installer's automatic CUDA Toolkit allowlist (Ubuntu 22.04/24.04 only). A prebuilt engine can avoid needing a full toolkit; source builds need separately installed, compatible development tools. WSL KV streaming is disabled in the audited code. Start with short context and compare speculation on/off as separate lanes.

Strata uses a prepared model representation and an SSD-backed PLE lookup. Record original weights, conversion version, precision, pruned/retained experts, PLE layout, and MTP settings. The Coder variant with removed experts is not the same model as the full variant. A throughput comparison without these distinctions would be misleading.
