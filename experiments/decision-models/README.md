# Decision models experiment

This experiment measures decision models: models that answer typed questions about a text (a choice from a list, a yes/no probability or a score on a rubric) with a probability for every allowed answer, instead of generating text. The harness asks one choice question per task, over named criteria, and scores the choice; yes/no and score questions are not asked yet. It measures decision accuracy and latency, and, when a decision routes a request, the quality, latency and API cost of the selected generator. Version 1 supports `decision`, `replay` and `live` modes. It uses one active request per job and can participate in campaigns spanning multiple hardware configurations.

Its id is `decision-models`; until 2026-11-23 it was `llm-routing`. Campaigns planned and results published under the former id keep it: their reports and published results resolve to this experiment, and the [results index](../../docs/results/README.md) lists them under the new id. A new campaign must name `decision-models`; the planner refuses the former id.

## Routers

- `fixed`: always select the configured `choice`; useful as a baseline.
- `category`: match configured `keywords` against the prompt, with a `default_category`. It never reads a task's reference label to choose a route.
- `systemone`: send named choice criteria to an Ollama/Jev-compatible `/v1/systemone` endpoint and validate the returned choice/probabilities. The [Ollama API announcement](https://ollama.com/blog/ollama-now-supports-jev-style-decision-models) documents this protocol. The installer catalog pins Ollama 0.40.17.

## Decision models and case templates

Each case below is a template for one decision model of the Ollama library. Prepare the local service and model yourself and replace `model_revision` with the actual loaded artifact digest. Templates do not establish that an external service loaded the claimed model; preserve operator attestations. No weights are downloaded automatically. The [candidate review](../../docs/MODEL_CANDIDATES.md#decision-models) lists the developer, base model, sizes and license of each and how they were found; the US column follows the [model origins](../../docs/MODELS.md#model-origins).

| Case | Ollama tag | Developer | Base model | US model | Published runs |
|---|---|---|---|---|---|
| [ollama-nimble](cases/ollama-nimble.json) | `nimble` | Bespoke Labs | Qwen3.5-9B | no | Windows and WSL2 |
| [ollama-tev1](cases/ollama-tev1.json) | `tev1` (4B) | Together AI | Qwen3.5 | no | Windows and WSL2 |
| [ollama-tev1-0.8b](cases/ollama-tev1-0.8b.json) | `tev1:0.8b` | Together AI | Qwen3.5 | no | none |
| [ollama-nimble-v3](cases/ollama-nimble-v3.json) | `nimble-v3` | Bespoke Labs | Qwen3.5-9B | no | none; noncommercial license (CC BY-NC 4.0) |
| [ollama-pplx-decider](cases/ollama-pplx-decider.json) | `pplx-decider` (27B) | Perplexity | Qwen3.8-27B | no | none |
| [ollama-pplx-decider-flash](cases/ollama-pplx-decider-flash.json) | `pplx-decider-flash` (4B) | Perplexity | Qwen3.5-4B | no | none |
| [ollama-clef](cases/ollama-clef.json) | `clef` (27B) | Cloudflare | Qwen3.8-27B | no | none |
| [ollama-clef-flash](cases/ollama-clef-flash.json) | `clef-flash` (9B) | Cloudflare | Qwen3.5-9B | no | none |
| [ollama-d1](cases/ollama-d1.json) | `d1` (3B) | Liquid AI | LFM2.5-VL-3B | yes | none |
| [ollama-d1-omni](cases/ollama-d1-omni.json) | `d1-omni` (600M) | Liquid AI | LFM2.5-Encoder-350M | yes | none |
| [ollama-autotrust-jev](cases/ollama-autotrust-jev.json) | `autotrust-jev` (9B) | AutoTrust | Qwen3.5-9B | no | none |
| [ollama-laya](cases/ollama-laya.json) | `laya` (421M) | Convai Innovations | ModernBERT-large | not recorded | none; Ollama 0.40.0 or later |

`strands-decider` (Strands Agents) has no template: it runs only with MLX on Apple silicon. LM Studio's catalog lists no decision model, and the other platforms here have no SystemOne endpoint, so every decision model runs on Ollama.

The [category smoke case](cases/category-smoke.json) is deliberately synthetic. Its two original checks verify harness behavior; they are not LiveBench scores or model rankings.

## Case configuration

A case is `{"id":"my-case","parameters":{...}}`. Parameters include `suite`, `router`, `candidates`, `policy`, `repeats`, `warmups`, and optional generation/cost controls. Each task has an `id`, text `messages`, optional `category`, optional `expected_choice`, optional deterministic `check`, and optional `eligible_candidates`.

A router using SystemOne supplies `kind`, `model`, `model_revision`, `endpoint`, `instructions` and named `criteria`. Keep choice labels equal to candidate IDs, or use `policy.category_models` to map category labels to candidates. `policy.abstain_threshold` applies only when a probability distribution is available. A configured fallback may handle abstention or one failed generation; every generation attempt remains recorded.

A candidate declares `model`, `model_revision`, `platform`, and for live use: `protocol` (`ollama` or `openai`), `endpoint`, `context_tokens` and optional `timeout_s`, `api_key_env`, `quantization`, `template_sha256`, and `backend_version`. `target_id` associates an external self-hosted candidate with an inventory target for resource reservation.

Local HTTP endpoints remain literal loopback addresses. A hosted or remote deployment requires `network: {"kind":"hosted", "allowed_hosts":["api.example.com"]}` (or kind `remote`) and HTTPS. Hosted deployments also require `pricing: {"input_per_million":1, "output_per_million":2}` and a case `budget_usd`. These numbers are illustrative; configure the actual price/version. Prompt and output token usage is taken from the backend, not estimated from text length. Unknown usage remains unknown and retains its conservative budget reservation. Local cost fields cover API charges, not hardware or electricity cost.

## Replay corpus and baselines

A replay JSON contains `suite_sha256`, `candidate_fingerprints`, and `rows`. Each row identifies `task_id` and `candidate`, with `quality` in [0,1] and optional `latency_s` and `cost_usd`. Use `candidate_fingerprint` from the evaluation module to hash candidate identity/settings. Changing a candidate or suite invalidates its corpus binding. Missing outcomes produce missing-coverage records instead of zero scores.

`policy.objective` defines nonnegative `quality_weight`, `latency_weight` and `cost_weight`. Default utility is quality. The report records the best fixed candidate on common coverage and per-request regret against an offline oracle only when all eligible candidate outcomes needed for comparison exist. Oracle performance is an upper bound, not a deployable router.

`policy.benchmark_registry` can reference a frozen JSON with `release`, `source`, and `categories` mapping category names to candidate-score dictionaries. It derives the best eligible candidate per category. Benchmark scores are priors, not per-prompt truth. Use held-out evaluation tasks and record training/calibration provenance in your study. The harness does not crawl or silently update a leaderboard.

## Measurement boundaries

Live mode evaluates final answers with the existing deterministic exact/JSON checks when supplied. It does not execute generated code. The original offload experiment retains its upstream LiveBench grading integration. Routing replay can consume externally graded LiveBench outcomes after binding their exact suite and candidate fingerprints; live routing does not claim a full upstream LiveBench score automatically.

Worker telemetry records the executing host. External generator hardware may be unknown, and is not assigned the local router's GPU profile. Co-resident router/generator configurations reserve the whole host; their service's load/swap behavior affects observed end-to-end timing. Separate isolated and contention studies.
