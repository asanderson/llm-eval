# model-offloading results

Status: **complete**. Synthetic fixtures: **false**.

Campaign: `matrix-wsl-deepseek-r1-70b`. Experiment run: `offload-model-offloading-1`. Measured code: `7e4606827cde8d9af4ccbb0c2ec8473d8d8049ce`.

[Raw measurements](raw/measurements.jsonl.gz) · [JSON summary](summary.json) · [CSV summary](summary.csv) · [Manifest](manifest.json) · [Resolved configuration](resolved-config.json)

## Configuration coverage

| Case | Hardware | OS | Harness | Model | Status |
|---|---|---|---|---|---|
| deepseek-r1-70b-koboldcpp | raider-wsl | windows-11-wsl2-ubuntu-26.04 | koboldcpp | deepseek-r1-70b | succeeded |
| deepseek-r1-70b-ollama | raider-wsl | windows-11-wsl2-ubuntu-26.04 | ollama | deepseek-r1-70b | succeeded |

## Measurements by harness and model

| Harness | Model | Category | Requests | Errors or missing | Quality passes | Decision accuracy | Median seconds | Output tokens/s | Job |
|---|---|---|---:|---:|---:|---:|---:|---:|---|
| koboldcpp | deepseek-r1-70b | coding | 9 | 0 | 0/9 | unavailable | 160.3 | 2.585 | `4f5a36938fca` |
| koboldcpp | deepseek-r1-70b | math | 9 | 0 | 0/9 | unavailable | 94.91 | 2.592 | `4f5a36938fca` |
| koboldcpp | deepseek-r1-70b | reasoning | 9 | 0 | 3/9 | unavailable | 185.1 | 2.575 | `4f5a36938fca` |
| ollama | deepseek-r1-70b | coding | 9 | 0 | 3/9 | unavailable | 235.3 | 2.616 | `2321c8a27cbf` |
| ollama | deepseek-r1-70b | math | 9 | 0 | 0/9 | unavailable | 92.89 | 2.627 | `2321c8a27cbf` |
| ollama | deepseek-r1-70b | reasoning | 9 | 0 | 3/9 | unavailable | 186.5 | 2.628 | `2321c8a27cbf` |

![Request latency](../../../../diagrams/results/model-offloading/campaign-20261117T220944Z-fb65881a-offload-model-offloading-1/latency.png)

## Interpretation and reproduction

Warmups and superseded attempts remain in raw data and are excluded from summaries. Each job/category is a separate cohort. Missing values remain unknown. Replay cost and generation latency are estimates; an offline oracle is an upper bound. LiveBench upstream grades are exported separately as judgment and benchmark summary records, not relabeled as local smoke scores.

Use the measured code revision and resolved configuration to reconstruct the campaign with your local artifact paths and credential references. Verify the recorded input hashes. Run `llm-eval plan --campaign YOUR_CAMPAIGN.json` before `llm-eval run --campaign YOUR_CAMPAIGN.json`. Synthetic results do not establish model quality or hardware performance.
