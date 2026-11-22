# model-offloading results

Status: **complete**. Synthetic fixtures: **false**.

Campaign: `matrix-wsl-kimi-dev-72b`. Experiment run: `offload-model-offloading-1`. Measured code: `7e4606827cde8d9af4ccbb0c2ec8473d8d8049ce`.

[Raw measurements](raw/measurements.jsonl.gz) · [JSON summary](summary.json) · [CSV summary](summary.csv) · [Manifest](manifest.json) · [Resolved configuration](resolved-config.json)

## Configuration coverage

| Case | Hardware | OS | Harness | Model | Status |
|---|---|---|---|---|---|
| kimi-dev-72b-lmstudio | raider-wsl | windows-11-wsl2-ubuntu-26.04 | lmstudio | kimi-dev-72b | succeeded |

## Measurements by harness and model

| Harness | Model | Category | Requests | Errors or missing | Quality passes | Decision accuracy | Median seconds | Output tokens/s | Job |
|---|---|---|---:|---:|---:|---:|---:|---:|---|
| lmstudio | kimi-dev-72b | coding | 9 | 0 | 0/9 | unavailable | 149.9 | 1.904 | `e5b59b4414ba` |
| lmstudio | kimi-dev-72b | math | 9 | 0 | 0/9 | unavailable | 114.6 | 1.906 | `e5b59b4414ba` |
| lmstudio | kimi-dev-72b | reasoning | 9 | 0 | 0/9 | unavailable | 110.8 | 1.912 | `e5b59b4414ba` |

![Request latency](../../../../diagrams/results/model-offloading/campaign-20261122T124804Z-80069b0a-offload-model-offloading-1/latency.png)

## Interpretation and reproduction

Warmups and superseded attempts remain in raw data and are excluded from summaries. Each job/category is a separate cohort. Missing values remain unknown. Replay cost and generation latency are estimates; an offline oracle is an upper bound. LiveBench upstream grades are exported separately as judgment and benchmark summary records, not relabeled as local smoke scores.

Use the measured code revision and resolved configuration to reconstruct the campaign with your local artifact paths and credential references. Verify the recorded input hashes. Run `llm-eval plan --campaign YOUR_CAMPAIGN.json` before `llm-eval run --campaign YOUR_CAMPAIGN.json`. Synthetic results do not establish model quality or hardware performance.
