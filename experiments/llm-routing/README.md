# LLM routing experiment

This experiment measures decision quality and the quality, latency and API cost of the selected generator. Version 1 supports `decision`, `replay` and `live` modes. It uses one active request per job and can participate in campaigns spanning multiple hardware configurations.

## Routers

- `fixed`: always select the configured `choice`; useful as a baseline.
- `category`: match configured `keywords` against the prompt, with a `default_category`. It never reads a task's reference label to choose a route.
- `systemone`: send named choice criteria to an Ollama/Jev-compatible `/v1/systemone` endpoint and validate the returned choice/probabilities. The [Ollama API announcement](https://ollama.com/blog/ollama-now-supports-jev-style-decision-models) documents this protocol. The existing installer pins Ollama 0.35.1.

[Nimble](cases/ollama-nimble.json) and [Tev1](cases/ollama-tev1.json) are templates. Prepare their local service/model yourself and replace `model_revision` with the actual loaded artifact digest. Templates do not establish that an external service loaded the claimed model; preserve operator attestations. No weights are downloaded automatically.

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
