# model-offloading results

Status: **complete**. Synthetic fixtures: **false**.

Campaign: `matrix-deepseek-r1-32b`. Experiment run: `offload-model-offloading-1`. Measured code: `46ebbf59b39d5dced9a885331fc55f25c388f122`.

[Raw measurements](raw/measurements.jsonl.gz) · [JSON summary](summary.json) · [CSV summary](summary.csv) · [Manifest](manifest.json) · [Resolved configuration](resolved-config.json)

## Configuration coverage

| Case | Hardware | OS | Harness | Model | Status |
|---|---|---|---|---|---|
| deepseek-r1-32b-koboldcpp | raider-windows | windows-11-native | koboldcpp | deepseek-r1-32b | succeeded |
| deepseek-r1-32b-lmstudio | raider-windows | windows-11-native | lmstudio | deepseek-r1-32b | succeeded |
| deepseek-r1-32b-ollama | raider-windows | windows-11-native | ollama | deepseek-r1-32b | succeeded |

## Measurements by harness and model

| Harness | Model | Category | Requests | Errors or missing | Quality passes | Decision accuracy | Median seconds | Output tokens/s | Job |
|---|---|---|---:|---:|---:|---:|---:|---:|---|
| koboldcpp | deepseek-r1-32b | coding | 9 | 0 | 6/9 | unavailable | 114 | 3.491 | `f98a74d7c1d6` |
| koboldcpp | deepseek-r1-32b | math | 9 | 0 | 0/9 | unavailable | 72.38 | 3.494 | `f98a74d7c1d6` |
| koboldcpp | deepseek-r1-32b | reasoning | 9 | 0 | 0/9 | unavailable | 87.01 | 3.494 | `f98a74d7c1d6` |
| lmstudio | deepseek-r1-32b | coding | 9 | 0 | 0/9 | unavailable | 145.5 | 2.598 | `8cd707175ee0` |
| lmstudio | deepseek-r1-32b | math | 9 | 0 | 0/9 | unavailable | 99.49 | 2.603 | `8cd707175ee0` |
| lmstudio | deepseek-r1-32b | reasoning | 9 | 0 | 3/9 | unavailable | 139.7 | 2.599 | `8cd707175ee0` |
| ollama | deepseek-r1-32b | coding | 9 | 0 | 3/9 | unavailable | 119.7 | 3.442 | `a5f32470b1c5` |
| ollama | deepseek-r1-32b | math | 9 | 0 | 0/9 | unavailable | 70.4 | 3.444 | `a5f32470b1c5` |
| ollama | deepseek-r1-32b | reasoning | 9 | 0 | 0/9 | unavailable | 88.24 | 3.452 | `a5f32470b1c5` |

![Request latency](../../../../diagrams/results/model-offloading/campaign-20261109T111225Z-8bf20361-offload-model-offloading-1/latency.png)

## Interpretation and reproduction

Warmups and superseded attempts remain in raw data and are excluded from summaries. Each job/category is a separate cohort. Missing values remain unknown. Replay cost and generation latency are estimates; an offline oracle is an upper bound. LiveBench upstream grades are exported separately as judgment and benchmark summary records, not relabeled as local smoke scores.

Use the measured code revision and resolved configuration to reconstruct the campaign with your local artifact paths and credential references. Verify the recorded input hashes. Run `llm-eval plan --campaign YOUR_CAMPAIGN.json` before `llm-eval run --campaign YOUR_CAMPAIGN.json`. Synthetic results do not establish model quality or hardware performance.
