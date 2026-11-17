# model-offloading results

Status: **complete**. Synthetic fixtures: **false**.

Campaign: `matrix-deepseek-r1-32b`. Experiment run: `offload-model-offloading-1`. Measured code: `4c11da3344793596cf51aa0b4b979c56f35fe36b`.

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
| koboldcpp | deepseek-r1-32b | coding | 9 | 0 | 6/9 | unavailable | 114.5 | 3.487 | `f98a74d7c1d6` |
| koboldcpp | deepseek-r1-32b | math | 9 | 0 | 0/9 | unavailable | 72.15 | 3.493 | `f98a74d7c1d6` |
| koboldcpp | deepseek-r1-32b | reasoning | 9 | 0 | 0/9 | unavailable | 112.7 | 3.303 | `f98a74d7c1d6` |
| lmstudio | deepseek-r1-32b | coding | 9 | 0 | 3/9 | unavailable | 120.9 | 2.595 | `8cd707175ee0` |
| lmstudio | deepseek-r1-32b | math | 9 | 0 | 0/9 | unavailable | 99.69 | 2.598 | `8cd707175ee0` |
| lmstudio | deepseek-r1-32b | reasoning | 9 | 0 | 3/9 | unavailable | 167.8 | 2.593 | `8cd707175ee0` |
| ollama | deepseek-r1-32b | coding | 9 | 0 | 3/9 | unavailable | 137.9 | 3.119 | `a5f32470b1c5` |
| ollama | deepseek-r1-32b | math | 9 | 0 | 0/9 | unavailable | 74.33 | 3.325 | `a5f32470b1c5` |
| ollama | deepseek-r1-32b | reasoning | 9 | 0 | 0/9 | unavailable | 95.15 | 3.207 | `a5f32470b1c5` |

![Request latency](../../../../diagrams/results/model-offloading/campaign-20261115T230200Z-261eec44-offload-model-offloading-1/latency.png)

## Interpretation and reproduction

Warmups and superseded attempts remain in raw data and are excluded from summaries. Each job/category is a separate cohort. Missing values remain unknown. Replay cost and generation latency are estimates; an offline oracle is an upper bound. LiveBench upstream grades are exported separately as judgment and benchmark summary records, not relabeled as local smoke scores.

Use the measured code revision and resolved configuration to reconstruct the campaign with your local artifact paths and credential references. Verify the recorded input hashes. Run `llm-eval plan --campaign YOUR_CAMPAIGN.json` before `llm-eval run --campaign YOUR_CAMPAIGN.json`. Synthetic results do not establish model quality or hardware performance.
