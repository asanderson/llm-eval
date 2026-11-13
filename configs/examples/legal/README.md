# Legal benchmark: qualification, evaluation, scoring and routing replay

Example campaign files for the three-experiment flow of the `legal-benchmark` experiment. Nothing in this directory is a measurement: every number, revision and endpoint is a placeholder or a fixture default, an example value is not a measurement, and no result produced from these files has been recorded here.

Their physical host id is `raider`. `llm-eval plan --campaign <file>` is read-only and may be run anywhere; `setup`, `run` and `resume` are for the operator on the target host, one campaign at a time.

## Files

| File | What it is |
|---|---|
| `inventory.json` | The Raider as one local target (Windows 11 native), the same shape as `configs/examples/raider-windows/inventory.json` |
| `inventory-separate-service.json` | The same, with a role served on another physical host; see "A role on another host" below. No campaign here uses it |
| `qualification-campaign.json`, `legal-offload-case.json`, `legal-offload-run.json` | `model-offloading` over the legal-shaped workload `experiments/legal-benchmark/workloads/qualification/legal-shaped.json`, external serving. Plans as shipped |
| `evaluation-campaign.json`, `retrieval-case.json`, `generation-case.json`, `workflow-case.json` | The frozen legal evaluation: `retrieval` (a fixture run), then `generation`, then `workflow`. External, GPU-served roles on a loopback endpoint with placeholder revisions and `"qualification": null`. Plans as shipped; a run stops at the placeholder revisions |
| `score-campaign.json`, `score-case.json` | Template: `score` over the output manifest of an earlier generation or workflow attempt. Does not plan until `REPLACE_WITH_...` is filled |
| `routing-replay-campaign.json`, `routing-replay-case.json` | Template: an `llm-routing` `replay` over an exported routing suite and a verified replay manifest. Does not plan until `REPLACE_WITH_...` is filled |

Every campaign file has `"publish": {"mode": "none"}`.

## Order of the stages

1. **Qualify serving.** Plan, set up and run `qualification-campaign.json` with the exact model, backend build, template and placement filled in `legal-offload-run.json`. Then freeze a locked serving profile from that one attempt, naming every id and attesting the placement you observed:

   ```
   python -m llm_eval.experiments.legal_benchmark.profiles freeze --campaign-dir <campaign dir> --job-id <job id> --attempt-id <attempt id> --observed-placement gpu_layers=20 --output serving-profile.json
   ```

   Nothing picks "the newest" campaign, job, attempt or measurement. A profile whose probe is not `passed` cannot qualify a role.
2. **Bind the roles.** Copy the profile next to the case and set `"qualification": {"serving_profile": "serving-profile.json"}` in the role; platform, backend version, artifact, quantization, template, tokenizer, context, output budget and placement of the role must equal the profile's. The planner pins the file by digest; a changed byte stops the coordinator and the worker. The phase dependency only orders jobs; the profile is always passed by name.
3. **Evaluate.** Plan and run `evaluation-campaign.json`.
4. **Score.** Fill `score-case.json` with the attempt's `local/output-manifest.json`, then plan and run `score-campaign.json`.
5. **Routing replay (optional).** Export the routing suite of an approved fixture suite, build the replay manifest from scored attempts, and verify it:

   ```
   python -m llm_eval.experiments.legal_benchmark.routing export --suite <suite.lock.json> --output routing-suite.json
   python -m llm_eval.experiments.legal_benchmark.routing replay --suite <suite.lock.json> --routing-suite routing-suite.json --attempt <attempt dir> --candidates candidates.json --output replay.json
   python -m llm_eval.experiments.legal_benchmark.routing verify --suite <suite.lock.json> --replay replay.json --routing-suite routing-suite.json --candidates candidates.json --attempt <attempt dir>
   ```

   `verify` takes the same `--attempt` directories and rebuilds the manifest from their pinned outputs. Run `routing verify` before any replay campaign: the routing experiment itself checks only the suite hash, the candidate fingerprints and duplicates, and would accept a manifest built before a rubric or scorer change. Then fill `routing-replay-case.json` and plan `routing-replay-campaign.json`.

A selector threshold also needs a calibration: run a routed attempt (no threshold) and an attempt of its fallback arm on `original-packets`, `routing calibrate` them, and name the record, the suite and both output manifests in the case's `selector.calibration` block (`calibration_file`, `suite`, `routed.output_manifest`, `fallback.output_manifest`); planning re-derives the record from those attempts.

Exports are allowed only for the suites listed in `experiments/legal-benchmark/approved-suites.json` (the two shipped fixture suites). A relocked copy of a shipped suite is refused, whatever its `data_class` says.

## A role on another host

A role served on another physical host names it in `resource_host`. Its `endpoint` must still be a loopback address: legal roles are local, so the operator reaches the other host through a local forward (an SSH tunnel to `127.0.0.1`, for example), and the profile it binds to must have been frozen on that host. The job then reserves that host only if the inventory lists it under `resource_hosts` of the job's target **and** has a target entry whose `physical_host_id` is that host (`inventory-separate-service.json` shows both). Without the reservation the legal run refuses to start (`Role host is not reserved by this job`); without the target entry the scheduler refuses to reserve it. The full physical-host lock and the shared Windows and WSL `lock_root` are unchanged.

## Operator rules nothing checks

- A served selector on the Raider beside the generator makes two large models active at once, which breaks the rule of a single active large model per Raider. Nothing in the code checks this: serve the selector elsewhere, or keep it small.
- `setup` on `qualification-campaign.json` installs the serving runtime its run file names, and `run` takes the `raider` lock, exactly like the `configs/examples/raider-*` campaigns. Run one campaign at a time on the Raider.
- The generation and workflow roles here are the qualification run's model, platform, endpoint and budgets, so a profile frozen from that run can bind once the placeholders and the role's template, tokenizer, artifact and quantization are filled with the profile's values.

## Publication

A routing or offload bundle built from a legal export cannot be published: its benchmark names (`legal-routing`, `legal-shaped`) start with `legal-`, which the legal plugin claims, so `publish-results` finds a second experiment identity in the bundle and refuses it. Local reports are unaffected. No legal result bundle is published by this effort.
