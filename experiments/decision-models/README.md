# Decision models experiment

This experiment measures decision models: models that answer typed questions about a text (a choice from a list, a yes/no probability or a score on a rubric) with a probability for every allowed answer, instead of generating text. The harness asks one choice question per task, over named criteria, and scores the choice; yes/no and score questions are not asked yet. It measures decision accuracy and latency, and, when a decision routes a request, the quality, latency and API cost of the selected generator. Version 1 supports `decision`, `replay` and `live` modes. It uses one active request per job and can participate in campaigns spanning multiple hardware configurations.

Its id is `decision-models`; until 2026-11-23 it was `llm-routing`. Campaigns planned and results published under the former id keep it: their reports and published results resolve to this experiment, and the [results index](../../docs/results/README.md) lists them under the new id. A new campaign must name `decision-models`; the planner refuses the former id.

## Routers

- `fixed`: always select the configured `choice`; useful as a baseline.
- `category`: match configured `keywords` against the prompt, with a `default_category`. It never reads a task's reference label to choose a route.
- `systemone`: send named choice criteria to an Ollama/Jev-compatible `/v1/systemone` endpoint and validate the returned choice/probabilities. The [Ollama API announcement](https://ollama.com/blog/ollama-now-supports-jev-style-decision-models) documents this protocol. The installer catalog pins Ollama 0.40.17.

## Decision models and case templates

Each case below is a template for one decision model of the Ollama library. Prepare the local service and model yourself and replace `model_revision` with the actual loaded artifact digest. Templates do not establish that an external service loaded the claimed model; preserve operator attestations. No weights are downloaded automatically. The [candidate review](../../docs/MODEL_CANDIDATES.md#decision-models) lists the developer, base model, sizes and license of each and how they were found; the US column follows the [model origins](../../docs/MODELS.md#model-origins). The last column names the hardware configurations with published runs: the [WSL2 runs of 2026-11-24](../../docs/results/README.md#decision-models-in-wsl2-of-2026-11-24) cover all ten templates.

| Case | Ollama tag | Developer | Base model | US model | Published runs |
|---|---|---|---|---|---|
| [ollama-nimble](cases/ollama-nimble.json) | `nimble` | Bespoke Labs | Qwen3.5-9B | no | Windows and WSL2 |
| [ollama-tev1](cases/ollama-tev1.json) | `tev1` (4B) | Together AI | Qwen3.5 | no | Windows and WSL2 |
| [ollama-tev1-0.8b](cases/ollama-tev1-0.8b.json) | `tev1:0.8b` | Together AI | Qwen3.5 | no | WSL2 |
| [ollama-nimble-v3](cases/ollama-nimble-v3.json) | `nimble-v3` | Bespoke Labs | Qwen3.5-9B | no | WSL2; noncommercial license (CC BY-NC 4.0) |
| [ollama-pplx-decider](cases/ollama-pplx-decider.json) | `pplx-decider` (27B) | Perplexity | Qwen3.8-27B | no | WSL2 |
| [ollama-clef](cases/ollama-clef.json) | `clef` (27B) | Cloudflare | Qwen3.8-27B | no | WSL2; only partly on the GPU there |
| [ollama-clef-flash](cases/ollama-clef-flash.json) | `clef-flash` (9B) | Cloudflare | Qwen3.5-9B | no | WSL2 |
| [ollama-d1](cases/ollama-d1.json) | `d1` (3B) | Liquid AI | LFM2.5-VL-3B | yes | WSL2 |
| [ollama-d1-omni](cases/ollama-d1-omni.json) | `d1-omni` (600M) | Liquid AI | LFM2.5-Encoder-350M | yes | WSL2 |
| [ollama-laya](cases/ollama-laya.json) | `laya` (421M) | Convai Innovations | ModernBERT-large | not recorded | WSL2; Ollama 0.40.0 or later |

Three decision models of the library have no template, because Ollama publishes them for its MLX runner only, which needs Apple silicon: `strands-decider` (Strands Agents), `pplx-decider-flash` (Perplexity) and `autotrust-jev` (AutoTrust). On Linux, `ollama pull` refuses them with "this model requires MLX support, but the MLX runtime is not available" (Ollama 0.40.16 in WSL2, 2026-11-24). LM Studio's catalog lists no decision model, and the other platforms here have no SystemOne endpoint, so every decision model runs on Ollama.

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

## Held-out classification and downstream routing

The [authored pilot](workloads/family-split.json) has eight development tasks and 24 test tasks. Each split balances coding, math, general instruction following and requests that need clarification. The test questions include paraphrases, mixed intent, unfamiliar domains and requests with missing information. Each has a deterministic short-answer check. These original English questions and their source packets were written for this repository under its [MIT license](../../LICENSE). The source names identify editorial packets from the same author. Independent authors and natural user traffic would broaden the evidence.

Select `split: "development"` or `"test"` in the case. The runner checks that family IDs, source packet IDs and exact message hashes stay within one partition. The optional `task_ids` list selects a subset from that partition. Only messages reach the router or generator. The public test split supports a pilot with a frozen policy. For a confirmatory study, have another contributor hold back new families and their labels until the policy is frozen.

### Run the replay fixture

From the repository root with the package and reporting extra installed, these commands generate the keyword, routed, fixed-cheap and fixed-strong cases, run them on the same test prompts and write a paired comparison. The routed arm in this fixture deliberately uses the identical keyword rule. All downstream quality, latency and cost entries in the corpus are hand-set examples. The hardware name is the example inventory selection.

```sh
study=experiments/decision-models
protocol=llm_eval.experiments.decision_models.protocol
python -m "$protocol" prepare --mode replay --split test \
  --case "$study/cases/family-replay-fixture.json" \
  --replay "$study/workloads/family-split.fixture-replay.json" \
  --keywords "$study/workloads/keyword-router.json" \
  --inventory configs/targets/local.example.json --hardware raider-ubuntu --out /tmp/routing-fixture
llm-eval run --campaign /tmp/routing-fixture/campaign.json --output /tmp/routing-fixture-runs
python -m "$protocol" compare --campaign-dir /tmp/routing-fixture-runs/campaign-* --out /tmp/fixture-pairs.json
```

Use a fresh directory per campaign. Substitute the precise campaign directory printed by `run` when a results directory contains several runs.

### Collect a decision result and a separate downstream result

Copy [family-study.example.json](cases/family-study.example.json) next to the template. Set the three served model names and loaded revisions, the generator precision and runtime versions, and your actual inventory. Set the output cap and objective before collecting outcomes. The worked commands use the shell variables below. Keep every generated campaign and report with its code revision, suite hash and resolved settings.

```sh
study=experiments/decision-models
case_file="$study/cases/my-pinned-study.json"
protocol=llm_eval.experiments.decision_models.protocol
inventory=configs/targets/local.example.json
hardware=raider-ubuntu
prepare_study() {
  python -m "$protocol" prepare --case "$case_file" --keywords "$study/workloads/keyword-router.json" \
    --inventory "$inventory" --hardware "$hardware" "$@"
}
```

1. Run the decision experiment on development. Examine the reliability bins, accepted accuracy against coverage, and the reversed-criteria arm. Choose the threshold on development and freeze it together with the instructions, criterion order, category map, generator identities and keyword rules. Then run the same protocol on test, including its label-order sensitivity check. Report accuracy for the originally frozen order.

   ```sh
   prepare_study --mode decision --split development --out /tmp/decision-dev
   llm-eval run --campaign /tmp/decision-dev/campaign.json --output /tmp/dev-runs
   # After freezing the policy
   prepare_study --mode decision --split test --out /tmp/decision-test
   llm-eval run --campaign /tmp/decision-test/campaign.json --output /tmp/decision-runs
   ```

2. Collect each fixed generator on the same eligible test questions and deterministic rubric, with identical generation settings. Freeze the first measured generation for each candidate and task. Failed or ineligible generations leave holes in the corpus. A missing quality check or unavailable token billing stays unknown. The frozen corpus binds the suite, model fingerprints, hardware ID, split and generation settings. For human grading, blind the scorer to arm identity and record the rubric version and provenance before importing outcomes.

   ```sh
   prepare_study --mode live --fixed-only --split test --out /tmp/fixed-test
   llm-eval run --campaign /tmp/fixed-test/campaign.json --output /tmp/fixed-runs
   python -m "$protocol" freeze --campaign-dir /tmp/fixed-runs/campaign-* --out /tmp/measured-corpus.json
   prepare_study --mode replay --split test --replay /tmp/measured-corpus.json --out /tmp/replay-test
   llm-eval run --campaign /tmp/replay-test/campaign.json --output /tmp/replay-runs
   python -m "$protocol" compare --campaign-dir /tmp/replay-runs/campaign-* --out /tmp/replay-pairs.json
   ```

3. Select a stratified live subset from the replay panel. Record the selection rule and task IDs before live generation. Include agreements, disagreements, and abstentions where observed, covering the classes and baseline tradeoffs. The four IDs below illustrate the CLI. Replace them with the recorded selection or omit the filter to validate the full test set. Preserve the hardware and cache conditions, including service reloads and timeouts. For a decision-quality claim on the entire workload, use a representative sample or the full set. Disagreement-enriched subsets measure conditional performance.

   ```sh
   prepare_study --mode live --split test --out /tmp/live-test \
     --task-ids test-coding-1 test-math-2 test-general-3 test-clarify-4
   llm-eval run --campaign /tmp/live-test/campaign.json --output /tmp/live-runs
   python -m "$protocol" compare --campaign-dir /tmp/replay-runs/campaign-* \
     --paired-live /tmp/live-runs/campaign-* --out /tmp/paired-live.json
   ```

### Read the measures

| Output | Population and interpretation |
|---|---|
| `decision-models-summary.json` in the report | One row per job and benchmark. The first scheduled non-warmup repetition of each task supplies its decision, including failures. Confusion pools categories. Per-class recall and macro-F1 cover reference classes present in that cohort. A missing choice is a false negative. Direct fixed-generator arms have no classification score when the topic labels fall outside the candidate vocabulary. |
| Probability and deferral fields | Mean multiclass Brier sums squared class errors per task, then averages tasks with a known probability distribution and reference class. Ten reliability bins compare confidence in the actual choice with its accuracy, including confidence 1 in the last bin. The sensitivity curve uses only probability-bearing tasks. Accepted accuracy and share use the configured policy on all labelled tasks. Check the counts alongside each rate. |
| Timing and failures | Router p50/p95 uses measured router timings, including decisions followed by failed generation. End-to-end p50/p95 uses successful requests over all measured repetitions. Request-status counts include failures. The per-task panel retains abstentions and fallbacks. Raw live rows have attempt errors, backend-reported load times and generation durations. |
| Paired JSON from `compare` | For each metric, every displayed arm uses the same task IDs with known values in every arm. Inspect the candidate count and each arm's failures and unknown API costs. The quality–latency and quality–cost tables require joint coverage for each pair of metrics. The panel gives per-task scores, router overhead, selected generator and replay oracle regret. Replay end-to-end time adds the measured router and frozen generator durations. Live elapsed time includes all attempts. |
| Fixed and paired comparisons | `routing-metadata.json` names the best fixed generator by the declared utility on complete eligible coverage. Per-task regret uses the eligible generator utilities. Those utilities exclude router overhead. The paired JSON compares actual end-to-end time and total API charges independently of that generator-only objective. Differences subtract the named reference from the arm. Intervals use 1,000 seeded paired bootstrap draws over task families, keeping paraphrases together. One-family intervals stay unavailable. |

State the workload, fixed resource budget, achieved quality and coverage for each comparison. Local generator API charges are zero. Record metered energy separately when available. Accuracy, equal-budget superiority and generalization require a workload and sample size adequate for those claims.
