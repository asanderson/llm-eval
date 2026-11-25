# Prioritized model evaluation catalog

Checked 2026-10-05. **No performance winner has been measured on the target laptop.** Rankings prioritize useful experiments and architectural fit, not an asserted universal model leaderboard. Laguna is interpreted as Poolside; Kimi as Moonshot AI.

The target precision is part of the recommendation. Q4 versions of many 27–35B models fit VRAM; their Q8/BF16 variants deliberately test overflow. Such tests answer a capacity/precision question, not necessarily the fastest deployment question. Estimates below are planning values from parameter count and approximate storage bits; exact selected artifacts, tensor precision, KV, staging, host duplication, and load-time expansion determine real usage. GiB uses 2^30 bytes.

## NVIDIA

| Priority | Model / primary evidence | Initial precision | Planning weights GiB | Status | Why evaluate / limitation |
|---|---|---|---:|---|---|
| 1 | [nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16](https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16) | GGUF Q8_0 | 29.69 | candidate | Small active MoE; Q8 tests RAM offload while Q4 is a separate in-VRAM control. Hybrid architecture needs engine validation. |
| 2 | [nvidia/Llama-3_3-Nemotron-Super-49B-v1_5](https://huggingface.co/nvidia/Llama-3_3-Nemotron-Super-49B-v1_5) | GGUF Q5_K_M | 32.51 | candidate | Dense/NAS comparison; CPU fallback can dominate. Model-card remote-code path needs review. |
| 3 | [nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-NVFP4](https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-NVFP4) | NVFP4 or separately tracked GGUF Q4 | 62.86 | conditional | Upper-budget experiment. Official NVFP4 deployment targets B200/DGX Spark; laptop offload is NOT vendor-validated. GGUF and NVFP4 results are separate cohorts. |
| 4 | [nvidia/NVIDIA-Nemotron-3.5-Super-VL-120B-A12B-BF16](https://huggingface.co/nvidia/NVIDIA-Nemotron-3.5-Super-VL-120B-A12B-BF16) | GGUF Q4_K_M | 69.54 | conditional | LiveBench 2026-10-25 candidate (overall 50.23, rank 28/32). Vision-language hybrid Mamba-2/MoE/attention with a C-RADIO encoder (`nemotron_h_omni`, remote code); text-only here. No GGUF or llama.cpp support verified; Q4_K_M sits at the native budget ceiling. |
| 5 | [nvidia/NVIDIA-Nemotron-3.5-Super-VL-120B-A12B-NVFP4](https://huggingface.co/nvidia/NVIDIA-Nemotron-3.5-Super-VL-120B-A12B-NVFP4) | NVFP4 or separately tracked GGUF Q4 | 62.86 | conditional | Official NVFP4 build of the entry above (overall 46.50, rank 30/32). Vendor deployment targets vLLM/SGLang on Blackwell; no engine here is verified to load it. Parameter count is the repo name's 120B. |

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
| 4 | [meta-models/Muse-Glimmer-30B](https://huggingface.co/meta-models/Muse-Glimmer-30B) | GGUF Q8_0 | 27.61 | candidate | Dense 30B agent model with a perception encoder; text-only here, so the parameter count is the language model's (27.85B in the GGUF files) and leaves out the 1.9B encoder, which the GGUF repositories ship as separate mmproj files. Q8_0 exceeds VRAM by a small margin. The publisher's own 4-bit KQuant GGUF files fit in VRAM and are hardware-fit candidates. Found by the candidate review of 2026-11-23, not by LiveBench discovery: it is published under meta-models, not meta-llama. |

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

## Thinking Machines Lab

| Priority | Model / primary evidence | Initial precision | Planning weights GiB | Status | Why evaluate / limitation |
|---|---|---|---:|---|---|
| 1 | [thinkingmachines/Inkling-2-Mini](https://huggingface.co/thinkingmachines/Inkling-2-Mini) | GGUF Q8_0 | 26.12 | candidate | Looped mixture-of-experts transformer: 12 of its 24 layers run three passes per token (3.4B parameters active, 5.4B effective per token by the model card). Q8_0 exceeds VRAM by a small margin; 4-bit GGUF files fit in VRAM and are hardware-fit candidates. Engine support is new: KoboldCpp 1.125.1 is the first pinned version that loads it, and its release notes say to use the ggml-org GGUF files. The same notes report a known issue on CUDA with partial offload and large prompts, where the output can be corrupted (llama.cpp issues 32710 and 32778), and name --no-op-offload as the mitigation; that is the Q8_0 offload case, not hardware fit, where every layer is on the GPU. Ollama's release notes announce the model in 0.40.17, the pinned version, for Apple silicon only, with PC support to follow in a later release; in WSL2 that version does not load the GGUF file (unknown model architecture, hardware-fit job of 2026-11-24). The official checkpoint is distributed in mixed NVFP4 and MXFP8 precisions (about 20 GB). Found by the candidate review of 2026-11-23. |

## What the status means

- **candidate:** a plausible initial experiment at the stated precision; engine/kernel/format and actual working-set validation remain required.
- **conditional:** high memory pressure, architecture/quantization dependencies, or a specialist task; no guarantee of fit or acceptable speed.
- **control:** useful reference that does not meet the >24GiB serialized-weight criterion.
- **excluded:** not recommended under this laptop budget. Recorded so the absence is explicit.

**xAI:** no three qualifying models were verified. Grok-1 is 314B and its raw Q4 weights alone exceed the machine budget. Grok-2's published artifact/deployment is also far beyond it. No third qualifying release is invented. Extremely low-bit speculative conversions and SSD streaming do not establish effective use within the requested memory budget.

**OpenAI:** gpt-oss-120b is the main over-VRAM candidate. gpt-oss-safeguard-120b is a separate safety classifier, not a second general coding assistant. gpt-oss-20b is a useful in-VRAM control, not a qualifying third large model. Harmony formatting is required.

**Kimi:** Kimi-Linear and Kimi-Dev are the strongest direct candidates here. Kimi-VL is a BF16 specialist comparison. Kimi K2/K3 total weights are excluded from the practical resident-memory shortlist even though their active parameter counts are smaller.

**Strata:** the extra Qwen3.8-Flash-Next entry preserves its specialized test track without replacing the three general Qwen candidates. Its reviewed engine supports this family, not every arbitrary GGUF. It has a model-specific expert/PLE layout and quantization/conversion path; document changes before attempting cross-engine quality equivalence.

## Model origins

[`catalog/model-origins.json`](../catalog/model-origins.json) records, for the catalogued models and for each model id the published results use, the organization that released the model and the organizations whose base models it was fine-tuned, distilled or pruned from; and for each organization, the country of its headquarters with a source. A **US model** is one whose developer and base-model developers are all headquartered in the United States. A quantization by a third party (an Unsloth or bartowski GGUF, for example) does not change a model's origin, and an alias maps a result id such as `qwen38-27b-ud-q4_k_xl` or `llm-eval-nimble:locked` to its model.

The [results](results/README.md) rank the US models in tables of their own for each experiment and hardware configuration, and the [executive summary](../README.md#executive-summary) names the best US model on each platform. A model without an entry is not ranked among the US models, and the results flag it as origin not recorded: by name when it is among the five best combinations of its experiment and hardware configuration, by count below them. A model whose developer or base-model developer has no recorded country is not ranked among them either. Two classifications to know: DeepSeek R1 Distill Llama 70B is not a US model although its base is Meta's (DeepSeek released it), and the decision models of Bespoke Labs, Together AI, Perplexity and Cloudflare are fine-tuned from Qwen bases, so none of them is a US model although each developer is a US company. Of the decision models measured so far, only `d1` and `d1-omni` of Liquid AI, on its own base models, are US models; `laya` has no origin entry. Poolside's headquarters are recorded as San Francisco, as Wikipedia lists them; Sifted reported a move to Paris in 2023.

Record the origin of every model added to the catalog or measured under a new id, with the source of each fact. The [candidate review](MODEL_CANDIDATES.md) lists the origin of the candidates found on Ollama, Hugging Face and LM Studio.

## Licenses and revisions

| Catalog ID | Model license / terms | Original model snapshot |
|---|---|---|
| `nemotron-nano-30b` | NVIDIA Nemotron Open Model License | `bf77c3174f68ad409e1c2aa60daeb46e32d1c606` |
| `nemotron-super-49b` | NVIDIA Open Model License; Llama 3.3 terms also referenced | `420ba7d28211abf116b8b103ab700d92619daf98` |
| `nemotron-super-120b` | NVIDIA Nemotron Open Model License | `ff433f5493e25d631c9f12b5d55c674229923d02` |
| `nemotron-super-vl-120b` | OpenMDW-1.1 (linked from the model card; no LICENSE file at the revision) | `fb0ee0bc6b3f70342afd8d84cb80dbadbaa8a1fe` |
| `nemotron-super-vl-120b-nvfp4` | OpenMDW-1.1 (linked from the model card; no LICENSE file at the revision) | `da5b2650a835292c678994a1fa3fb653250fb508` |
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
| `muse-glimmer-30b` | Apache-2.0 (LICENSE and USAGE_POLICY.md in the repository) | `1297fd7dfeac4598948a5d15886968435c81c2b7` |
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
| `inkling2-mini-26b` | Apache-2.0 (no LICENSE file at the revision; the card links the publisher's Model Acceptable Use Policy) | `7a67ae2314b44ef05c87fd1d4d311c58aaeb18f6` |

Repository IDs and metadata revisions were resolved through the official publishers' public Hugging Face API. They identify source-model snapshots, **not a chosen community GGUF**. Quantized artifact paths/revisions remain unfilled in `catalog/models.json`; the artifact selected for each measured model is pinned separately, in `catalog/model-artifacts.json` ([Artifact pins](#artifact-pins)). Do not manufacture filenames or assume a precision exists on every backend.

Kimi-Dev's [LICENSE.md](https://huggingface.co/moonshotai/Kimi-Dev-72B/blob/main/LICENSE.md) retains the upstream Qwen license condition. [Poolside's official collection](https://huggingface.co/poolside/collections) distinguishes Apache-licensed XS.2 from OpenMDW-licensed 2.1 releases. [NVIDIA's 49B card](https://huggingface.co/nvidia/Llama-3_3-Nemotron-Super-49B-v1_5) also references Llama terms. Metadata labels alone are insufficient to replace review of actual model license files.

## Artifact pins

[catalog/model-artifacts.json](../catalog/model-artifacts.json) pins the quantized artifact that each measured catalog model loads in the next run. It is separate from the table above: those revisions stay snapshots of the publishers' repositories, and no run loads them.

| Field | Meaning |
|---|---|
| `model_id` | Catalog ID. Entries follow the catalog order. |
| `base_model` | The catalog `upstream_repo`. A run refuses an artifact lock whose base model is another repository. |
| `source_repo`, `source_revision` | The artifact repository on Hugging Face and one full 40-character commit of it. |
| `precision` | The selected quantization. |
| `files` | The selected files, each with `path`, `bytes` and `sha256` as Hugging Face lists them at that commit. A split GGUF lists every part. |

The 17 entries were seeded on 2026-11-22 from the published `model-offloading` results. Each seeded entry equals the artifact lock that those runs recorded: repository, revision, precision, file paths, sizes and SHA-256. The top-level `checked_on` is the date of the last check that moved a pin. `new_models_since` is the date from which new publisher repositories are reported.

No run reads the pin file, and it starts no download. A run loads what the operator's artifact lock names, as before. The pins reach a run through a download manifest:

```bash
python scripts/model_pins.py --download-spec configs/local/download.json --models deepseek-r1-32b
```

The command makes no network request. It writes a manifest in the shape of [download.example.json](../configs/workflows/download.example.json): the pinned repository, revision and precision, the exact pinned file paths as `include`, `models/<model_id>` as the artifact directory and `artifacts/<model_id>.lock.json` as the lock. Without `--models` it lists every pinned model. An ID without a pin ends the command with exit code 2. `accept_license` is written as `false`, so setup refuses the manifest until the operator has reviewed the model and quantization licenses and set it to `true`. Setup also refuses a manifest that lists a model it was not asked to set up, so pass the same IDs to both commands. [WORKFLOWS.md](WORKFLOWS.md#models-conversion-and-run-configuration) describes the setup step. The lock that setup writes hashes the downloaded files itself. Nothing compares that lock with the pin automatically; both carry `bytes` and `sha256` per file for that comparison.

### Nightly model pin check

The model pin check (`.github/workflows/model-pins.yml`, 07:17 UTC) runs `scripts/model_pins.py --apply`. It asks the Hugging Face API for the head commit of every pinned artifact repository, for the file listing at that commit when it differs from the pin, for the head commit of every pinned model's publisher repository, and for the 50 newest repositories of each publisher org. It writes `catalog/model-artifacts.json` and no other file, and opens or refreshes one pull request from the branch `auto/model-pins`, titled "Bump pinned model artifact revisions". What needs a decision is also kept in the issue "Model versions needing a manual decision".

| Finding | What the check does |
|---|---|
| The artifact repository has another head commit, and every pinned file is listed there with a Git LFS SHA-256 | Bump: `source_revision` moves to that commit and the listed sizes and hashes are recorded. The row says "repository moved; pinned files unchanged" when sizes and hashes are equal, and "weights changed" with the file names when they are not. |
| A pinned file is not listed at that commit, or is listed without a Git LFS SHA-256 | Manual decision. The pin stays. |
| Hugging Face answers 401, 403, 404 or 410 for an artifact or publisher repository | Manual decision. Nothing is changed. |
| The published `model-offloading` results measured a model that has no pin | Manual decision. |
| The publisher repository has a head commit other than the catalog `source_revision` | Manual decision. `catalog/models.json` is never rewritten: that revision is tied to `upstream_metadata`, to the table above and to the anchors of [model discovery](MODEL_DISCOVERY.md), and is reviewed by hand. |
| `base_model` is not the catalog `upstream_repo`, or `model_id` is not a catalog ID | Manual decision. |
| A publisher org of a pinned model created a repository on or after `new_models_since` that is not a catalog `upstream_repo` and that no `hf:` decision in `catalog/model-discovery.json` covers | Manual decision, one row per repository. |
| A lookup fails: the network, another HTTP status, or an answer in an unexpected shape | The row is reported as failed and the other rows still resolve. A run with a failed lookup does not close the issue. |

`checked_on` is stamped only when a pin moved, so a night without a bump leaves the file byte-identical. While a bump pull request stays open, each later night finds the same bump with a new date and pushes the branch again.

An `hf:` key matches as [MODEL_DISCOVERY.md](MODEL_DISCOVERY.md#recording-a-decision) documents: the exact repository, or a name prefix within the same org. A deferral counts until its `until` date. The list of new repositories judges neither size nor license; the model discovery issue does that for the models LiveBench ranks. A repository leaves the list when it is added to the catalog, when a decision covers it, or when `new_models_since` is moved past its creation date. The check reads the 50 newest repositories of each org. When all 50 were created on or after `new_models_since`, it reports that older ones were not read. GitHub refuses a pull request or issue body above 65,536 characters, so a report above 60,000 characters counts the new repositories per org instead of naming each one; the log of the run and a local run of the script name them.

A moved artifact pin changes what the next run loads. A changed artifact revision is a new cohort, also when the pinned files are byte-identical: the artifact lock records the revision, and the digest of the lock is part of the cohort key. Results of the next run are therefore a different cohort from the results measured at the old revision. Published results keep the revision they recorded; the check never writes under `docs/results/`. For a model with published results, the artifact row names its newest published measurement by short revision and date and says whether that is the pinned revision. An artifact that is already downloaded and locked at the old revision still runs and stays the old cohort.

The check does not cover:

- The decision models of the decision-models experiment. They are pulled from the Ollama registry and are identified by a digest that the operator records.
- The legal serving profile. A legal role is bound to a locked serving profile, which records the digest of an artifact lock and its source revision. A moved pin does not change that profile; a role that should use the new revision needs re-qualification.
- Catalog models without a pin. The check follows the artifact and the publisher repository of pinned models only.

Run `python3 scripts/model_pins.py` locally for a report without writing anything. On 2026-11-22 one report run against the real Hugging Face API resolved every row without a failed lookup: sixteen pins were current, one artifact repository had moved with its pinned file unchanged, and two publisher repositories had moved. The `--apply` path has run only against the scripted Hugging Face of `tests/test_model_pins.py`. Those tests check the shell steps of the workflow as text and execute none of them; the workflow had not run on GitHub when this was written.

## Initial experiment order

1. Llama 3.3 70B Q4_K_M: compare the same GGUF on llama.cpp, ik_llama.cpp, Ollama import, KoboldCpp, and LM Studio import.
2. Qwen3.5 35B-A3B Q8_0 and Gemma 4 31B Q8_0: sparse-versus-dense architecture experiments, each compared only against itself across engines.
3. Laguna XS 2.1 Q8/FP8 and Kimi-Linear Q6: expand after architecture support is verified.
4. Strata IQ2_XS reference: capture PLE IO, expert cache, CPU threads, speculation, and quality; add other engines only after equivalent architecture/artifacts work.
5. gpt-oss-120b, Laguna S, Nemotron Super 120B, and Qwen 122B: conditional high-memory lane with short initial context. Never begin with an unquantized 120B checkpoint on this machine.

A model that returns tokens is not automatically a successful candidate: report correctness, supported tasks, RAM/VRAM peaks, paging, TTFT where available, and sustained performance.

## LiveBench-informed additions

Five additional entries from DeepSeek, Z.AI, Mistral AI and Microsoft bring the catalog to 29; the two Nemotron 3.5 Super VL entries accepted from the 2026-10-25 LiveBench 2.0 discovery issue bring it to 31; Muse Glimmer 30B and Inkling 2 Mini, added on 2026-11-24 from the [candidate review](MODEL_CANDIDATES.md) to be measured in hardware fit, bring it to 33. See the [recommendation table and release-specific evidence](LIVEBENCH.md#additional-providers-and-models) for DeepSeek R1 Distill 32B Q8 / 70B Q4, Mistral Small 3.1 BF16, Phi-4 Reasoning Plus BF16 and conditional GLM-4.5-Air Q4. The BF16 selections are precision/capacity tests; their smaller quantizations are controls. The historical published scores guide candidate selection and are not local measurements or comparable across releases. All five remain blocked on the currently audited Strata reference lane.

New candidates are raised by the [model discovery](MODEL_DISCOVERY.md) issue; adding one still needs review of its license file, a real artifact, engine architecture support and measured fit. The `LiveBench/new-livebench` GitHub links in the evidence files are no longer reachable; the recorded tables are verified byte for byte (sha256) on `livebench.ai/v1/` instead.
