# model-offloading results

Status: **complete**. Synthetic fixtures: **false**.

Campaign: `matrix-wsl-deepseek-r1-32b`. Experiment run: `offload-model-offloading-1`. Measured code: `7e4606827cde8d9af4ccbb0c2ec8473d8d8049ce`.

[Raw measurements](raw/measurements.jsonl.gz) · [JSON summary](summary.json) · [CSV summary](summary.csv) · [Manifest](manifest.json) · [Resolved configuration](resolved-config.json)

## Configuration coverage

| Case | Hardware | OS | Harness | Model | Status |
|---|---|---|---|---|---|
| deepseek-r1-32b-koboldcpp | raider-wsl | windows-11-wsl2-ubuntu-26.04 | koboldcpp | deepseek-r1-32b | succeeded |
| deepseek-r1-32b-ollama | raider-wsl | windows-11-wsl2-ubuntu-26.04 | ollama | deepseek-r1-32b | succeeded |

## Measurements by harness and model

| Harness | Model | Category | Requests | Errors or missing | Quality passes | Decision accuracy | Median seconds | Output tokens/s | Job |
|---|---|---|---:|---:|---:|---:|---:|---:|---|
| koboldcpp | deepseek-r1-32b | coding | 9 | 0 | 6/9 | unavailable | 117.3 | 3.377 | `be7755f6bfa6` |
| koboldcpp | deepseek-r1-32b | math | 9 | 0 | 0/9 | unavailable | 71.78 | 3.383 | `be7755f6bfa6` |
| koboldcpp | deepseek-r1-32b | reasoning | 9 | 0 | 0/9 | unavailable | 91.72 | 3.368 | `be7755f6bfa6` |
| ollama | deepseek-r1-32b | coding | 9 | 0 | 3/9 | unavailable | 115.8 | 3.464 | `09645320a4dd` |
| ollama | deepseek-r1-32b | math | 9 | 0 | 0/9 | unavailable | 70.09 | 3.47 | `09645320a4dd` |
| ollama | deepseek-r1-32b | reasoning | 9 | 0 | 0/9 | unavailable | 87.63 | 3.469 | `09645320a4dd` |

![Request latency](../../../../diagrams/results/model-offloading/campaign-20261117T080318Z-29021cec-offload-model-offloading-1/latency.png)

## Interpretation and reproduction

Warmups and superseded attempts remain in raw data and are excluded from summaries. Each job/category is a separate cohort. Missing values remain unknown. Replay cost and generation latency are estimates; an offline oracle is an upper bound. LiveBench upstream grades are exported separately as judgment and benchmark summary records, not relabeled as local smoke scores.

Use the measured code revision and resolved configuration to reconstruct the campaign with your local artifact paths and credential references. Verify the recorded input hashes. Run `llm-eval plan --campaign YOUR_CAMPAIGN.json` before `llm-eval run --campaign YOUR_CAMPAIGN.json`. Synthetic results do not establish model quality or hardware performance.
