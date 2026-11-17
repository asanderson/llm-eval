# model-offloading results

Status: **incomplete**. Synthetic fixtures: **false**.

Campaign: `matrix-kimi-dev-72b`. Experiment run: `offload-model-offloading-1`. Measured code: `4c11da3344793596cf51aa0b4b979c56f35fe36b`.

[Raw measurements](raw/measurements.jsonl.gz) · [JSON summary](summary.json) · [CSV summary](summary.csv) · [Manifest](manifest.json) · [Resolved configuration](resolved-config.json)

## Configuration coverage

| Case | Hardware | OS | Harness | Model | Status |
|---|---|---|---|---|---|
| kimi-dev-72b-koboldcpp | raider-windows | windows-11-native | koboldcpp | kimi-dev-72b | succeeded |
| kimi-dev-72b-lmstudio | raider-windows | windows-11-native | lmstudio | kimi-dev-72b | failed |
| kimi-dev-72b-ollama | raider-windows | windows-11-native | ollama | kimi-dev-72b | succeeded |

## Measurements by harness and model

| Harness | Model | Category | Requests | Errors or missing | Quality passes | Decision accuracy | Median seconds | Output tokens/s | Job |
|---|---|---|---:|---:|---:|---:|---:|---:|---|
| koboldcpp | kimi-dev-72b | coding | 9 | 0 | 0/9 | unavailable | 152.9 | 2.361 | `7274223fc38b` |
| koboldcpp | kimi-dev-72b | math | 9 | 0 | 0/9 | unavailable | 116.7 | 2.365 | `7274223fc38b` |
| koboldcpp | kimi-dev-72b | reasoning | 9 | 0 | 0/9 | unavailable | 86.93 | 2.366 | `7274223fc38b` |
| lmstudio | kimi-dev-72b | coding | 9 | 0 | 0/9 | unavailable | 206.1 | 1.878 | `d23d1c519653` |
| lmstudio | kimi-dev-72b | math | 9 | 0 | 0/9 | unavailable | 129.1 | 1.882 | `d23d1c519653` |
| lmstudio | kimi-dev-72b | reasoning | 9 | 0 | 0/9 | unavailable | 112.6 | 1.883 | `d23d1c519653` |
| ollama | kimi-dev-72b | coding | 9 | 0 | 0/9 | unavailable | 178.6 | 2.352 | `d5ee683b6c7c` |
| ollama | kimi-dev-72b | math | 9 | 0 | 0/9 | unavailable | 93.1 | 2.362 | `d5ee683b6c7c` |
| ollama | kimi-dev-72b | reasoning | 9 | 0 | 0/9 | unavailable | 87.19 | 2.363 | `d5ee683b6c7c` |

![Request latency](../../../../diagrams/results/model-offloading/campaign-20261116T080605Z-9fa41c54-offload-model-offloading-1/latency.png)

## Interpretation and reproduction

Warmups and superseded attempts remain in raw data and are excluded from summaries. Each job/category is a separate cohort. Missing values remain unknown. Replay cost and generation latency are estimates; an offline oracle is an upper bound. LiveBench upstream grades are exported separately as judgment and benchmark summary records, not relabeled as local smoke scores.

Use the measured code revision and resolved configuration to reconstruct the campaign with your local artifact paths and credential references. Verify the recorded input hashes. Run `llm-eval plan --campaign YOUR_CAMPAIGN.json` before `llm-eval run --campaign YOUR_CAMPAIGN.json`. Synthetic results do not establish model quality or hardware performance.
