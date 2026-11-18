# model-offloading results

Status: **incomplete**. Synthetic fixtures: **false**.

Campaign: `matrix-wsl-kimi-dev-72b`. Experiment run: `offload-model-offloading-1`. Measured code: `7e4606827cde8d9af4ccbb0c2ec8473d8d8049ce`.

[Raw measurements](raw/measurements.jsonl.gz) · [JSON summary](summary.json) · [CSV summary](summary.csv) · [Manifest](manifest.json) · [Resolved configuration](resolved-config.json)

## Configuration coverage

| Case | Hardware | OS | Harness | Model | Status |
|---|---|---|---|---|---|
| kimi-dev-72b-koboldcpp | raider-wsl | windows-11-wsl2-ubuntu-26.04 | koboldcpp | kimi-dev-72b | succeeded |
| kimi-dev-72b-ollama | raider-wsl | windows-11-wsl2-ubuntu-26.04 | ollama | kimi-dev-72b | failed |

## Measurements by harness and model

| Harness | Model | Category | Requests | Errors or missing | Quality passes | Decision accuracy | Median seconds | Output tokens/s | Job |
|---|---|---|---:|---:|---:|---:|---:|---:|---|
| koboldcpp | kimi-dev-72b | coding | 9 | 0 | 0/9 | unavailable | 157.4 | 2.275 | `2357915b8f64` |
| koboldcpp | kimi-dev-72b | math | 9 | 0 | 0/9 | unavailable | 111.6 | 2.266 | `2357915b8f64` |
| koboldcpp | kimi-dev-72b | reasoning | 9 | 0 | 0/9 | unavailable | 101.4 | 2.234 | `2357915b8f64` |
| ollama | kimi-dev-72b | coding | 9 | 0 | 0/9 | unavailable | 201.7 | 2.31 | `83cefbf471c1` |
| ollama | kimi-dev-72b | math | 9 | 0 | 0/9 | unavailable | 94.96 | 2.316 | `83cefbf471c1` |
| ollama | kimi-dev-72b | reasoning | 9 | 0 | 0/9 | unavailable | 88.51 | 2.327 | `83cefbf471c1` |

![Request latency](../../../../diagrams/results/model-offloading/campaign-20261118T014808Z-cc8eec8c-offload-model-offloading-1/latency.png)

## Interpretation and reproduction

Warmups and superseded attempts remain in raw data and are excluded from summaries. Each job/category is a separate cohort. Missing values remain unknown. Replay cost and generation latency are estimates; an offline oracle is an upper bound. LiveBench upstream grades are exported separately as judgment and benchmark summary records, not relabeled as local smoke scores.

Use the measured code revision and resolved configuration to reconstruct the campaign with your local artifact paths and credential references. Verify the recorded input hashes. Run `llm-eval plan --campaign YOUR_CAMPAIGN.json` before `llm-eval run --campaign YOUR_CAMPAIGN.json`. Synthetic results do not establish model quality or hardware performance.
