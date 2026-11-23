# Candidate models from Ollama, Hugging Face and LM Studio

Review of 2026-11-23. Until this review, candidates reached the experiments two ways: the [nightly LiveBench discovery](MODEL_DISCOVERY.md), which raises LiveBench-scored models published by an allowlisted Hugging Face organization, and, for decision models, Ollama's launch post of 2026-09-29. This review also read the [Ollama library](https://ollama.com/library) (with its [decision-model search](https://ollama.com/search?q=decision)), [Hugging Face](https://huggingface.co/models) (its API, by organization and by name) and [LM Studio's model catalog](https://lmstudio.ai/models).

Nothing here is measured. Weight sizes are the catalog's planning arithmetic on the parameter count that Hugging Face publishes (GiB = 2^30 bytes, weights only, about 4.9 bits per weight for Q4_K_M and 8.5 for Q8_0), compared with the MSI Raider's 24 GiB of VRAM and 63.4 GiB of RAM (51 GiB in the WSL2 guest); KV cache, activations and loader peaks come on top. A US model is one whose developer and base models are all from organizations headquartered in the United States ([model origins](MODELS.md#model-origins)). A candidate still needs the catalog's review before it runs: license file, a pinned artifact, engine support and measured fit ([what the status means](MODELS.md#what-the-status-means)).

## Why these models were missing

**Only two decision models.** The decision-models experiment (then `llm-routing`) was written on 2026-10-08 from Ollama's [launch post](https://ollama.com/blog/ollama-now-supports-jev-style-decision-models), which named three models: `nimble` (9B, Bespoke Labs), `tev1` (4B, Together AI) and `tev1:0.8b`. Case templates were written for `nimble` and `tev1` only, and no source the repository reads lists decision models since: LiveBench does not score them, so the nightly discovery never raises one. On 2026-11-23 Ollama's library lists twelve official decision models ([table below](#decision-models)); every one is now a case template except `strands-decider`, which runs only with MLX on Apple silicon.

**Mistral.** The catalog has one Mistral AI model, Mistral Small 3.1 24B, added from the LiveBench review as a bf16 capacity test. It was measured on every harness on Windows and in WSL2 and passes 6 of 27 checks at 2.3 to 2.9 output tokens per second, so it never reaches a top-five table. Newer Mistral releases did not enter the catalog: the nightly discovery raises only models that LiveBench scores and matches them by name, which date-coded Mistral ids escape (they are listed for a manual look instead), and Mistral Large 4 (1T parameters, 52B active) was rejected as too large on 2026-11-10. Mistral AI is headquartered in Paris, so no Mistral model is a US model.

**Thinking Machines Lab.** Its open-weight models on Hugging Face (organization `thinkingmachines`, all Apache 2.0) are Inkling (952B, 2026-07-14), Inkling Small (266B, 2026-07-27), Inkling 2 Small (594B, 2026-11-04) and Inkling 2 Mini (26.4B with 5.4B active, 2026-11-17). Inkling and Inkling 2 Small are far beyond 87 GiB of VRAM and RAM at any precision; Inkling Small needs about 62 GiB even at 2 bits per weight. Inkling 2 Mini appeared after the catalog's last review of 2026-11-08, and `thinkingmachines` is not an organization the discovery allowlists. It is the strongest new US candidate for hardware fit.

**Beam, Muse and Ornith.**

- *Beam* is Reflection AI's (New York) Beam 1.0: 501B parameters, 23B active, Apache 2.0, on Hugging Face as [`reflection/Beam-1.0-501B-A23B`](https://huggingface.co/reflection/Beam-1.0-501B-A23B) since 2026-10-07. Ollama offers only `beam:cloud` and LM Studio only its cloud. Even at 2 bits per weight it needs about 117 GiB, so it cannot run on the Raider; a hosted deployment would be a hosted arm, which the local experiments do not use.
- *Muse* is Meta's: [Muse Glimmer 30B](https://huggingface.co/meta-models/Muse-Glimmer-30B) (29.8B, Apache 2.0, 2026-08-09; Ollama `muse-glimmer:30b`; in LM Studio's catalog) and Muse Spark Open (816B, 42B active, Muse Model License with limited commercial terms), which Ollama and LM Studio serve only from their clouds. Muse Glimmer is published under `meta-models`, not under `meta-llama`, the Meta organization the discovery allowlists, so it was never matched. It is a US model that fits in VRAM at 4 bits.
- *Ornith* is Ornith AI's (formerly DeepReinforce) Ornith-1.5 family: 9B, 35B-A3B, 122B and 397B, MIT license, on Hugging Face under [`ornith-ai`](https://huggingface.co/ornith-ai) from 2026-08-18 to 2026-10-20, and on Ollama as `ornith-1.5`. Ornith-1.5-35B-A3B has exactly the parameter count of Qwen3.5-35B-A3B (35,951,822,704) and Ornith-1.5-122B that of Qwen3.5-122B-A10B (125,086,497,008), which points to Qwen 3.5 bases, although the model cards name none. The developer's headquarters were not verified, so it is not counted as a US model.

## Hardware fit

Models whose weights fit in 24 GiB of VRAM with room for the KV cache.

| Model | Developer | US model | Parameters | Q4_K_M | Q8_0 | License | Where |
|---|---|---|---:|---:|---:|---|---|
| Inkling 2 Mini | Thinking Machines Lab | yes | 26.4B (5.4B active) | 15.1 GiB | 26.1 GiB | Apache 2.0 | [Hugging Face](https://huggingface.co/thinkingmachines/Inkling-2-Mini) (GGUF from unsloth, ggml-org, lmstudio-community and bartowski) · Ollama `inkling-2-mini` · LM Studio |
| Muse Glimmer 30B | Meta | yes | 29.8B | 17.0 GiB | 29.5 GiB | Apache 2.0 | [Hugging Face](https://huggingface.co/meta-models/Muse-Glimmer-30B) (GGUF in `meta-models/Muse-Glimmer-30B-GGUF`) · Ollama `muse-glimmer:30b` · LM Studio |
| Nemotron 3 Nano 30B (catalogued) | NVIDIA | yes | 31.6B (3B active) | 18.0 GiB | 31.2 GiB | NVIDIA Nemotron Open Model License | [Hugging Face](https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16) · LM Studio |
| gpt-oss-20b (catalogued control) | OpenAI | yes | 20.9B | 11.9 GiB | 20.7 GiB | Apache 2.0 | [Hugging Face](https://huggingface.co/openai/gpt-oss-20b) · LM Studio |
| Gemma 4 26B A4B and 31B (catalogued) | Google | yes | 25.8B and 31.3B | 14.7 and 17.8 GiB | 25.5 and 30.9 GiB | Apache 2.0 | [Hugging Face](https://huggingface.co/google/gemma-4-26B-A4B-it) · LM Studio |
| Ornith-1.5-35B-A3B | Ornith AI | no (not verified) | 36.0B (3B active) | 20.5 GiB | 35.6 GiB | MIT | [Hugging Face](https://huggingface.co/ornith-ai/Ornith-1.5-35B-A3B) (GGUF in `ornith-ai/Ornith-1.5-35B-A3B-GGUF`) · Ollama `ornith-1.5:35b` |
| Ornith-1.5-9B | Ornith AI | no (not verified) | 9.7B | 5.5 GiB | 9.6 GiB | MIT | [Hugging Face](https://huggingface.co/ornith-ai/Ornith-1.5-9B) · Ollama `ornith-1.5:9b` |
| Devstral Small 2 24B | Mistral AI | no | 24.0B | 13.7 GiB | 23.8 GiB | Apache 2.0 | [Hugging Face](https://huggingface.co/mistralai/Devstral-Small-2-24B-Instruct-2512) · Ollama `devstral-small-2` · LM Studio |
| Magistral Small 24B, Ministral 3 (3B, 8B, 14B) | Mistral AI | no | 24B; 3B to 14B | – | – | Apache 2.0 | Ollama `magistral`, `ministral-3` · LM Studio |

LM Studio's catalog also lists US models whose parameter counts were not read for this review: Granite 4.1 (3B, 8B, 30B; IBM), Olmo 3 (7B, 32B; Ai2), Rnj-1 8B (Essential AI), LFM2-24B-A2B (Liquid AI) and Nemotron 3 Nano Omni 30B (NVIDIA). Their base models have to be checked before they count as US models.

## Model offloading

Models whose weights exceed 24 GiB of VRAM but fit in VRAM and RAM together.

| Model | Developer | US model | Precision and weights | Note |
|---|---|---|---|---|
| Inkling 2 Mini | Thinking Machines Lab | yes | Q8_0 26.1 GiB; BF16 49.2 GiB | The same model as in hardware fit: a precision comparison across the VRAM boundary |
| Muse Glimmer 30B | Meta | yes | Q8_0 29.5 GiB; BF16 55.5 GiB | BF16 exceeds the 51 GiB WSL2 guest |
| Ornith-1.5-35B-A3B | Ornith AI | no (not verified) | Q8_0 35.6 GiB | 3B active: a sparse split like Qwen3.5 35B A3B, which leads the WSL2 offload ranking |
| Mistral Small 4 119B | Mistral AI | no | Q3 at about 3.9 bits 54.2 GiB; Q4_K_M 68.1 GiB | [Hugging Face](https://huggingface.co/mistralai/Mistral-Small-4-119B-2603), Apache 2.0; native Windows only: it exceeds the WSL2 guest |
| Nemotron 3 Super 120B, gpt-oss-120b, Laguna S 2.1 118B (catalogued, conditional) | NVIDIA, OpenAI, Poolside | yes | see the [catalog](MODELS.md) | Already catalogued; not yet measured |

## Decision models

Official decision models of the Ollama library on 2026-11-23. The harness serves decision models through Ollama's SystemOne endpoint (`/v1/systemone`), and the pinned Ollama 0.40.17 meets every minimum version listed. LM Studio's catalog lists no decision model. Each runnable model has a case template in the [decision models experiment](../experiments/decision-models/README.md#decision-models-and-case-templates).

| Ollama tag | Developer | Base model | Sizes | US model | Note |
|---|---|---|---|---|---|
| `nimble` | Bespoke Labs | Qwen3.5-9B | 9B | no | Measured on Windows and WSL2 (6 of 6 decisions) |
| `tev1` | Together AI | Qwen3.5 | 4B, 0.8B | no | 4B measured on Windows and WSL2 (6 of 6); 0.8B not yet |
| `nimble-v3` | Bespoke Labs | Qwen3.5-9B | 9B | no | Ollama 0.40.4 or later; CC BY-NC 4.0, noncommercial use only |
| `pplx-decider` | Perplexity | Qwen3.8-27B | 27B | no | Text, JSON and images |
| `pplx-decider-flash` | Perplexity | Qwen3.5-4B | 4B | no | Distilled from `pplx-decider` |
| `clef` | Cloudflare | Qwen3.8-27B | 27B | no | Also served from Ollama's cloud (`clef:cloud`) |
| `clef-flash` | Cloudflare | Qwen3.5-9B | 9B | no | |
| `d1` | Liquid AI | LFM2.5-VL-3B | 3B, 2B | yes | The only US decision models in the library, with `d1-omni` |
| `d1-omni` | Liquid AI | LFM2.5-Encoder-350M | 600M, 2B | yes | Images and short English speech too |
| `autotrust-jev` | AutoTrust | not stated | 9B, 35B | not recorded | |
| `laya` | Convai Innovations | ModernBERT-large | 421M; 322M multilingual | not recorded | Ollama 0.40.0 or later; an encoder with no text generation |
| `strands-decider` | Strands Agents | Qwen3.5-2B-Base | 2B | no | MLX on Apple silicon only: not runnable on the Raider, so no template |

Community uploads with a decision tag (for example `aminroudaki/decisio-v3` and `nsru/winit`) are not official listings and were not reviewed.

## Legal benchmark

The legal benchmark serves its roles with models from the same catalog; its published runs use `kimi-linear-48b` (Moonshot AI), which is not a US model. US models that the offload and hardware-fit runs measured or that this review found (Nemotron 3 Nano 30B, the Gemma 4 models, gpt-oss-20b, Inkling 2 Mini, Muse Glimmer 30B) are the candidates for a US-only legal run.

## Too large for the Raider

| Model | Developer | Parameters | Smallest weights considered |
|---|---|---|---|
| Beam 1.0 | Reflection AI | 501B (23B active) | 116.7 GiB at 2 bits |
| Muse Spark Open | Meta | 816B (42B active) | cloud only on Ollama and LM Studio |
| Inkling 2 Small | Thinking Machines Lab | 594B | 138.3 GiB at 2 bits |
| Inkling | Thinking Machines Lab | 952B | 221.7 GiB at 2 bits |
| Mistral Large 4 | Mistral AI | 1T (52B active) | rejected on 2026-11-10 |
| Ornith-1.5-397B | Ornith AI | 403.4B | 93.9 GiB at 2 bits |

## Repeating the review

1. Ollama: the [decision search](https://ollama.com/search?q=decision) and the [newest library models](https://ollama.com/library?sort=newest); each model page names its developer, base model, sizes and minimum Ollama version.
2. Hugging Face: `https://huggingface.co/api/models?author=ORG&sort=createdAt&direction=-1` for each publisher, and `https://huggingface.co/api/models/REPO` for the parameter count (`safetensors.total`), license and base model (`cardData.base_model`) of a candidate.
3. LM Studio: the [model catalog](https://lmstudio.ai/models), local and cloud entries.
4. Record each decision as the [catalog](MODELS.md) does, and each new model's origin in [`catalog/model-origins.json`](../catalog/model-origins.json).
