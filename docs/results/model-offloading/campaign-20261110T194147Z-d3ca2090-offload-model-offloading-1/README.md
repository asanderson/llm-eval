# model-offloading results

Status: **incomplete**. Synthetic fixtures: **false**.

Campaign: `matrix-kimi-dev-72b`. Experiment run: `offload-model-offloading-1`. Measured code: `e64ec842608c30a6b4cba9f44b1711cc5e53ca19`.

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
| koboldcpp | kimi-dev-72b | coding | 9 | 0 | 0/9 | unavailable | 153.3 | 2.358 | `7274223fc38b` |
| koboldcpp | kimi-dev-72b | math | 9 | 0 | 0/9 | unavailable | 116.8 | 2.36 | `7274223fc38b` |
| koboldcpp | kimi-dev-72b | reasoning | 9 | 0 | 0/9 | unavailable | 86.95 | 2.365 | `7274223fc38b` |
| lmstudio | kimi-dev-72b | coding | 9 | 0 | 0/9 | unavailable | 206 | 1.879 | `d23d1c519653` |
| lmstudio | kimi-dev-72b | math | 9 | 0 | 0/9 | unavailable | 128.9 | 1.885 | `d23d1c519653` |
| lmstudio | kimi-dev-72b | reasoning | 9 | 0 | 0/9 | unavailable | 112.5 | 1.885 | `d23d1c519653` |
| ollama | kimi-dev-72b | coding | 9 | 0 | 0/9 | unavailable | 178.5 | 2.353 | `d5ee683b6c7c` |
| ollama | kimi-dev-72b | math | 9 | 0 | 0/9 | unavailable | 93.04 | 2.362 | `d5ee683b6c7c` |
| ollama | kimi-dev-72b | reasoning | 9 | 0 | 0/9 | unavailable | 87.48 | 2.357 | `d5ee683b6c7c` |

![Request latency](../../../../diagrams/results/model-offloading/campaign-20261110T194147Z-d3ca2090-offload-model-offloading-1/latency.png)

## Interpretation and reproduction

Warmups and superseded attempts remain in raw data and are excluded from summaries. Each job/category is a separate cohort. Missing values remain unknown. Replay cost and generation latency are estimates; an offline oracle is an upper bound. LiveBench upstream grades are exported separately as judgment and benchmark summary records, not relabeled as local smoke scores.

Use the measured code revision and resolved configuration to reconstruct the campaign with your local artifact paths and credential references. Verify the recorded input hashes. Run `llm-eval plan --campaign YOUR_CAMPAIGN.json` before `llm-eval run --campaign YOUR_CAMPAIGN.json`. Synthetic results do not establish model quality or hardware performance.
