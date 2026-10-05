# Prioritized model evaluation catalog

Checked 2026-10-05. **No performance winner has been measured on the target laptop.** Rankings prioritize useful experiments and architectural fit, not an asserted universal model leaderboard. Laguna is interpreted as Poolside; Kimi as Moonshot AI.

The target precision is part of the recommendation. Q4 versions of many 27–35B models fit VRAM; their Q8/BF16 variants deliberately test overflow. Such tests answer a capacity/precision question, not necessarily the fastest deployment question. Estimates below are planning values from parameter count and approximate storage bits; exact selected artifacts, tensor precision, KV, staging, host duplication, and load-time expansion determine real usage. GiB uses 2^30 bytes.

## NVIDIA

| Priority | Model / primary evidence | Initial precision | Planning weights GiB | Status | Why evaluate / limitation |
|---|---|---|---:|---|---|
| 1 | [nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16](https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16) | GGUF Q8_0 | 29.69 | candidate | Small active MoE; Q8 tests RAM offload while Q4 is a separate in-VRAM control. Hybrid architecture needs engine validation. |
| 2 | [nvidia/Llama-3_3-Nemotron-Super-49B-v1_5](https://huggingface.co/nvidia/Llama-3_3-Nemotron-Super-49B-v1_5) | GGUF Q5_K_M | 32.51 | candidate | Dense/NAS comparison; CPU fallback can dominate. Model-card remote-code path needs review. |
| 3 | [nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-NVFP4](https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-NVFP4) | NVFP4 or separately tracked GGUF Q4 | 62.86 | conditional | Upper-budget experiment. Official NVFP4 deployment targets B200/DGX Spark; laptop offload is NOT vendor-validated. GGUF and NVFP4 results are separate cohorts. |

## OpenAI

| Priority | Model / primary evidence | Initial precision | Planning weights GiB | Status | Why evaluate / limitation |
|---|---|---|---:|---|---|
| 1 | [openai/gpt-oss-120b](https://huggingface.co/openai/gpt-oss-120b) | MXFP4 (native or GGUF preservation) | 61.29 | conditional | Requires verified native MXFP4 offload without full BF16 expansion or excessive duplicate host weights. Harmony template required. |
| 2 | [openai/gpt-oss-safeguard-120b](https://huggingface.co/openai/gpt-oss-safeguard-120b) | MXFP4 | 61.29 | conditional | Safety classifier only; score in safety-policy suite, never in a general coding leaderboard. Same high-memory caveats as gpt-oss-120b. |
| 3 | [openai/gpt-oss-20b](https://huggingface.co/openai/gpt-oss-20b) | MXFP4 | 11.0 | control | Efficient local baseline normally fits within VRAM. Does NOT satisfy the >24GiB weight criterion. Do not inflate precision solely to invent a third qualifying model. |

## xAI

| Priority | Model / primary evidence | Initial precision | Planning weights GiB | Status | Why evaluate / limitation |
|---|---|---|---:|---|---|
| 1 | [xai-org/grok-1](https://huggingface.co/xai-org/grok-1) | Q4 hypothetical | 146.22 | excluded | 146GiB raw Q4 lower bound already exceeds combined physical memory; no practical validated configuration for this laptop. |
| 2 | [xai-org/grok-2](https://huggingface.co/xai-org/grok-2) | Published FP8 checkpoint | ~500GB published artifact | excluded | Published artifact is about 500GB and documented deployment uses eight GPUs >40GB each. |

## Google

| Priority | Model / primary evidence | Initial precision | Planning weights GiB | Status | Why evaluate / limitation |
|---|---|---|---:|---|---|
| 1 | [google/gemma-4-31B-it](https://huggingface.co/google/gemma-4-31B-it) | GGUF Q8_0 | 30.38 | candidate | Modern dense model; Q8 weight placement is a moderate offload workload. Text-only first; confirm engine architecture support. |
| 2 | [google/gemma-4-26B-A4B-it](https://huggingface.co/google/gemma-4-26B-A4B-it) | BF16 | 46.94 | candidate | BF16 is intentionally a capacity/precision comparison. Low-bit variants generally fit VRAM and belong in the control lane; do not describe BF16 as fastest. |
| 3 | [google/gemma-3-27b-it](https://huggingface.co/google/gemma-3-27b-it) | GGUF Q8_0 | 26.72 | candidate | Older dense regression anchor; text-only suite and exact chat template. Model-specific license rather than Apache. |

## Meta

| Priority | Model / primary evidence | Initial precision | Planning weights GiB | Status | Why evaluate / limitation |
|---|---|---|---:|---|---|
| 1 | [meta-llama/Llama-3.3-70B-Instruct](https://huggingface.co/meta-llama/Llama-3.3-70B-Instruct) | GGUF Q4_K_M | 39.12 | candidate | Primary broadly supported dense offload anchor; compare same GGUF bytes across the four GGUF-oriented runtimes. |
| 2 | [meta-llama/Llama-3.1-70B-Instruct](https://huggingface.co/meta-llama/Llama-3.1-70B-Instruct) | GGUF Q4_K_M | 39.12 | candidate | Earlier checkpoint for quality/performance regression. Dense CPU work will be bandwidth-sensitive. |
| 3 | [meta-llama/Meta-Llama-3-70B-Instruct](https://huggingface.co/meta-llama/Meta-Llama-3-70B-Instruct) | GGUF Q4_K_M | 39.12 | candidate | Older control with 8K native context: cap total prompt plus output at 8192, and do not run 16K/32K sweeps. |

## Laguna (Poolside)

| Priority | Model / primary evidence | Initial precision | Planning weights GiB | Status | Why evaluate / limitation |
|---|---|---|---:|---|---|
| 1 | [poolside/Laguna-XS-2.1](https://huggingface.co/poolside/Laguna-XS-2.1) | GGUF Q8_0 or FP8 | 32.65 | candidate | Preferred Laguna starting point; small active set. GGUF and FP8 are different precision/backend cohorts. |
| 2 | [poolside/Laguna-XS.2](https://huggingface.co/poolside/Laguna-XS.2) | GGUF Q8_0 or FP8 | 32.65 | candidate | Earlier distinct checkpoint gives a permissive-license comparison. Verify backend architecture support. |
| 3 | [poolside/Laguna-S-2.1](https://huggingface.co/poolside/Laguna-S-2.1) | GGUF Q4_K_M | 65.94 | conditional | High-capacity sparse candidate; require measured working set and native quantized CPU path. M.1 is deliberately omitted as too large. |

## Kimi (Moonshot)

| Priority | Model / primary evidence | Initial precision | Planning weights GiB | Status | Why evaluate / limitation |
|---|---|---|---:|---|---|
| 1 | [moonshotai/Kimi-Linear-48B-A3B-Instruct](https://huggingface.co/moonshotai/Kimi-Linear-48B-A3B-Instruct) | GGUF Q6_K | 36.88 | candidate | Small active set and linear-attention design; Q6 exceeds VRAM more clearly than borderline Q4. Model architecture support is a gate. |
| 2 | [moonshotai/Kimi-Dev-72B](https://huggingface.co/moonshotai/Kimi-Dev-72B) | GGUF Q4_K_M | 40.23 | candidate | Coding-focused dense checkpoint; evaluate task quality separately from throughput. Model LICENSE.md preserves Qwen conditions. |
| 3 | [moonshotai/Kimi-VL-A3B-Thinking-2506](https://huggingface.co/moonshotai/Kimi-VL-A3B-Thinking-2506) | BF16 | 29.8 | conditional | Capacity/precision and multimodal specialist, not a general coding replacement. Text-only first; multimodal loader/custom code may require review. |

## Qwen

| Priority | Model / primary evidence | Initial precision | Planning weights GiB | Status | Why evaluate / limitation |
|---|---|---|---:|---|---|
| 1 | [Qwen/Qwen3.8-27B](https://huggingface.co/Qwen/Qwen3.8-27B) | GGUF Q8_0 | 27.51 | candidate | Modern moderate dense offload candidate; use its own chat template and reasoning settings. |
| 2 | [Qwen/Qwen3.5-35B-A3B](https://huggingface.co/Qwen/Qwen3.5-35B-A3B) | GGUF Q8_0 | 34.63 | candidate | Strong architectural fit hypothesis for sparse CPU/GPU split; low-bit variants are useful in-VRAM controls, not qualifying offload runs. |
| 3 | [Qwen/Qwen3.5-122B-A10B](https://huggingface.co/Qwen/Qwen3.5-122B-A10B) | GGUF Q4_K_M | 68.17 | conditional | High-memory tier. Require host memory <=52GiB in native profiles and avoid duplicate weights or dequantization. Start at 4K context. |
| Strata reference | [Qwen/Qwen3.8-Flash-Next](https://huggingface.co/Qwen/Qwen3.8-Flash-Next) | Strata IQ2_XS; exact GSQ/RCO conversion recorded separately | conversion-specific | conditional | Additional Strata reference, not an invented fourth top-three slot. Reviewed Strata documents ~35.5GB expert RAM for IQ2_XS, GPU dense/cache allocations and SSD lookup table. Full original checkpoint is much larger; count all files and conversion steps. PLE SSD lookup is intrinsic and must be recorded. |

## What the status means

- **candidate:** a plausible initial experiment at the stated precision; engine/kernel/format and actual working-set validation remain required.
- **conditional:** high memory pressure, architecture/quantization dependencies, or a specialist task; no guarantee of fit or acceptable speed.
- **control:** useful reference that does not meet the >24GiB serialized-weight criterion.
- **excluded:** not recommended under this laptop budget. Recorded so the absence is explicit.

**xAI:** no three qualifying models were verified. Grok-1 is 314B and its raw Q4 weights alone exceed the machine budget. Grok-2's published artifact/deployment is also far beyond it. No third qualifying release is invented. Extremely low-bit speculative conversions and SSD streaming do not establish effective use within the requested memory budget.

**OpenAI:** gpt-oss-120b is the main over-VRAM candidate. gpt-oss-safeguard-120b is a separate safety classifier, not a second general coding assistant. gpt-oss-20b is a useful in-VRAM control, not a qualifying third large model. Harmony formatting is required.

**Kimi:** Kimi-Linear and Kimi-Dev are the strongest direct candidates here. Kimi-VL is a BF16 specialist comparison. Kimi K2/K3 total weights are excluded from the practical resident-memory shortlist even though their active parameter counts are smaller.

**Strata:** the extra Qwen3.8-Flash-Next entry preserves its specialized test track without replacing the three general Qwen candidates. Its reviewed engine supports this family, not every arbitrary GGUF. It has a model-specific expert/PLE layout and quantization/conversion path; document changes before attempting cross-engine quality equivalence.

## Licenses and revisions

| Catalog ID | Model license / terms | Original model snapshot |
|---|---|---|
| `nemotron-nano-30b` | NVIDIA Nemotron Open Model License | `bf77c3174f68ad409e1c2aa60daeb46e32d1c606` |
| `nemotron-super-49b` | NVIDIA Open Model License; Llama 3.3 terms also referenced | `420ba7d28211abf116b8b103ab700d92619daf98` |
| `nemotron-super-120b` | NVIDIA Nemotron Open Model License | `ff433f5493e25d631c9f12b5d55c674229923d02` |
| `gpt-oss-120b` | Apache-2.0 | `b5c939de8f754692c1647ca79fbf85e8c1e70f8a` |
| `gpt-oss-safeguard-120b` | Apache-2.0 | `3c7391182603991a904031244e7822488c67796d` |
| `gpt-oss-20b` | Apache-2.0 | `6cee5e81ee83917806bbde320786a8fb61efebee` |
| `grok-1` | Apache-2.0 | `5de83eb225f49624b424f1c8aa74f96983b5885c` |
| `grok-2` | Grok 2 Community License | `daf4395a80ad177386cfe39641b64fc12b1d70ed` |
| `gemma4-31b` | Apache-2.0 | `842da3794eaa0b77d5f08bae87a17459d91ff475` |
| `gemma4-26b-moe` | Apache-2.0 | `4d7ae4984b7db7de8f8457170b3f1a419ee76d52` |
| `gemma3-27b` | Gemma Terms of Use | `005ad3404e59d6023443cb575daa05336842228a` |
| `llama33-70b` | Llama 3.3 Community License | `6f6073b423013f6a7d4d9f39144961bfbfbc386b` |
| `llama31-70b` | Llama 3.1 Community License | `1605565b47bb9346c5515c34102e054115b4f98b` |
| `llama3-70b` | Llama 3 Community License | `50fd307e57011801c7833c87efa1984ddf2db42f` |
| `laguna-xs21` | OpenMDW-1.1 | `c5f36269bbdbd3f27fddc9a9f9dbae0cf2cf57db` |
| `laguna-xs2` | Apache-2.0 | `a397bde04501591d0ac3d74a5d9d0a4ec298ffb8` |
| `laguna-s21` | OpenMDW-1.1 | `0f573140834b11cfac0c2af97a101a7a69a13e22` |
| `kimi-linear-48b` | MIT | `e1df551a447157d4658b573f9a695d57658590e9` |
| `kimi-dev-72b` | MIT subject to upstream Qwen license agreement | `8791d7981945752a51f692d66f2bbfb3573c9722` |
| `kimi-vl-16b` | MIT | `aa1730989e7558695b44ee493623e03bd325a994` |
| `qwen38-27b` | Apache-2.0 | `1d4bf0f2ff6012fd82039f2fa52739d0dd7c60c0` |
| `qwen35-35b-moe` | Apache-2.0 | `59d61f3ce65a6d9863b86d2e96597125219dc754` |
| `qwen35-122b-moe` | Apache-2.0 | `dc4d348443bc740c68e2d77492492c11606384d5` |
| `qwen38-flash-next-strata` | Apache-2.0 (verify quantization artifact terms) | `de4b8e4d43b917e7706784d8bb445c9af86a3540` |

Repository IDs and metadata revisions were resolved through the official publishers' public Hugging Face API. They identify source-model snapshots, **not a chosen community GGUF**. Quantized artifact paths/revisions remain unfilled until an actual compatible artifact is selected; do not manufacture filenames or assume a precision exists on every backend.

Kimi-Dev's [LICENSE.md](https://huggingface.co/moonshotai/Kimi-Dev-72B/blob/main/LICENSE.md) retains the upstream Qwen license condition. [Poolside's official collection](https://huggingface.co/poolside/collections) distinguishes Apache-licensed XS.2 from OpenMDW-licensed 2.1 releases. [NVIDIA's 49B card](https://huggingface.co/nvidia/Llama-3_3-Nemotron-Super-49B-v1_5) also references Llama terms. Metadata labels alone are insufficient to replace review of actual model license files.

## Initial experiment order

1. Llama 3.3 70B Q4_K_M: compare the same GGUF on llama.cpp, ik_llama.cpp, Ollama import, and KoboldCpp.
2. Qwen3.5 35B-A3B Q8_0 and Gemma 4 31B Q8_0: sparse-versus-dense architecture experiments, each compared only against itself across engines.
3. Laguna XS 2.1 Q8/FP8 and Kimi-Linear Q6: expand after architecture support is verified.
4. Strata IQ2_XS reference: capture PLE IO, expert cache, CPU threads, speculation, and quality; add other engines only after equivalent architecture/artifacts work.
5. gpt-oss-120b, Laguna S, Nemotron Super 120B, and Qwen 122B: conditional high-memory lane with short initial context. Never begin with an unquantized 120B checkpoint on this machine.

A model that returns tokens is not automatically a successful candidate: report correctness, supported tasks, RAM/VRAM peaks, paging, TTFT where available, and sustained performance.
