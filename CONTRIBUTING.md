# Contribute a result or report a failed reproduction

A first contribution can be a reproducible failure, a measurement on a supported machine, or a reference run for a new device. Use a GitHub fork for a public measurement. Keep local campaign directories, credentials and private workloads on your machine.

## Try the reporting workflow

1. Fork [asanderson/llm-eval](https://github.com/asanderson/llm-eval) on GitHub. Clone your fork and add the project as a read-only source. Substitute your account for `YOUR_ACCOUNT`.

   ```bash
   git clone https://github.com/YOUR_ACCOUNT/llm-eval.git
   cd llm-eval
   git remote add upstream https://github.com/asanderson/llm-eval.git
   python -m pip install -e ".[telemetry,reporting]"
   python -m llm_eval verify-results
   ```

2. Run the synthetic decision-models fixture on Python 3.11 or newer. It exercises planning, the worker and report generation without model weights or a paid service.

   ```bash
   python -m llm_eval plan --campaign campaigns/routing-smoke.json
   python -m llm_eval run --campaign campaigns/routing-smoke.json
   ```

   The command prints `Campaign results: results/campaign-…`. In that directory, open `campaign.json`, find the run under `reports`, and append its `report` path to the campaign directory. The result ends in `experiments/RUN_ID/report`. The fixture tests the workflow locally. Its speed and choices do not measure a model.

3. For a measurement, choose a published job and use its workload, hardware, engine, model artifact, placement, warmup and repeat settings. Identify every deliberate difference. Follow the [reproduction guide](docs/REPRODUCE.md) and the [hardware participation guide](docs/HARDWARE_PARTICIPATION.md) for new devices. Leave automatic publication disabled in your campaign. Run the saved campaign and locate its report as in step 2.

## Review and submit a public measurement

Replace `REPORT` with the report directory from your own run. Inspect `REPORT/publication.json` for the destination. Open the README, resolved configuration, summaries and decompressed raw archive under `REPORT/bundle/`. Review free-form fields for identifying details. The default generic export drops prompt and output bodies. Keep `reporting.include_outputs` disabled when sharing would disclose inputs or answers.

```bash
python -m llm_eval publish-results --input REPORT --dry-run
python -m llm_eval publish-results --input REPORT --prepare-fork YOUR_ACCOUNT/llm-eval
```

Preparation reads the configured base branch from `upstream`, regenerates the results pages, verifies the staged files and commit, and creates a local branch. Your current branch and uncommitted work stay in place. The printed receipt includes `branch`, `commit`, `push`, `compare_url` and `draft`. This step needs Git read access to upstream. You can inspect the prepared commit before signing in to GitHub.

1. Run `git show --stat COMMIT` and `git diff COMMIT^ COMMIT` with the printed commit. Check the published report and generated pages. Inspect ignored local files separately if you are diagnosing a failure.
2. Run the exact printed `git push origin …` command to send the reviewed commit to your fork. Authenticate to Git with your own account. Upstream write access is unnecessary.
3. Open the printed comparison URL. Confirm the base repository is `asanderson/llm-eval`, its branch matches the receipt, and the head is the results branch on your fork. Select **Create draft pull request** if `draft` is true. Include the publication ID, report fingerprint, measured revision, reference job, what matched, differences, request counts, and failures or missing data. Submit for review.

Legal-model reports have a separately authorized destination. Fork preparation is disabled for these reports. Follow the [legal publication workflow](docs/RESULTS.md#legal-models-reports) for an approved fictional suite.

## When a step fails

A failed run can establish a constraint another contributor needs to know. Keep the local campaign and report so you can reproduce the failure or retry publication without starting a model again. If you cannot produce a suitable public bundle, open a [result or reproduction issue](https://github.com/asanderson/llm-eval/issues/new?template=result-or-reproduction.yml). Include the source report or job, public device and software details, the sanitized command, and the first actionable error. For a new type of hardware, describe the reference measurement and diagnostics you can collect.
