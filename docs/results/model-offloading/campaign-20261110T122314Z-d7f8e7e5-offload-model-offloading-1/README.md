# model-offloading results

Status: **complete**. Synthetic fixtures: **false**.

Campaign: `matrix-llama31-70b`. Experiment run: `offload-model-offloading-1`. Measured code: `e64ec842608c30a6b4cba9f44b1711cc5e53ca19`.

[Raw measurements](raw/measurements.jsonl.gz) · [JSON summary](summary.json) · [CSV summary](summary.csv) · [Manifest](manifest.json) · [Resolved configuration](resolved-config.json)

## Configuration coverage

| Case | Hardware | OS | Harness | Model | Status |
|---|---|---|---|---|---|
| llama31-70b-koboldcpp | raider-windows | windows-11-native | koboldcpp | llama31-70b | succeeded |
| llama31-70b-lmstudio | raider-windows | windows-11-native | lmstudio | llama31-70b | succeeded |
| llama31-70b-ollama | raider-windows | windows-11-native | ollama | llama31-70b | succeeded |

## Measurements by harness and model

| Harness | Model | Category | Requests | Errors or missing | Quality passes | Decision accuracy | Median seconds | Output tokens/s | Job |
|---|---|---|---:|---:|---:|---:|---:|---:|---|
| koboldcpp | llama31-70b | coding | 9 | 0 | 6/9 | unavailable | 2.471 | 2.428 | `b9f131a1a9c3` |
| koboldcpp | llama31-70b | math | 9 | 0 | 3/9 | unavailable | 3.212 | 2.491 | `b9f131a1a9c3` |
| koboldcpp | llama31-70b | reasoning | 9 | 0 | 3/9 | unavailable | 1.357 | 2.211 | `b9f131a1a9c3` |
| lmstudio | llama31-70b | coding | 9 | 0 | 0/9 | unavailable | 9.65 | 2.277 | `c10fd55e6c38` |
| lmstudio | llama31-70b | math | 9 | 0 | 0/9 | unavailable | 10.54 | 2.279 | `c10fd55e6c38` |
| lmstudio | llama31-70b | reasoning | 9 | 0 | 0/9 | unavailable | 13.6 | 2.279 | `c10fd55e6c38` |
| ollama | llama31-70b | coding | 9 | 0 | 0/9 | unavailable | 8.27 | 2.664 | `ca78ec6a2979` |
| ollama | llama31-70b | math | 9 | 0 | 0/9 | unavailable | 8.999 | 2.668 | `ca78ec6a2979` |
| ollama | llama31-70b | reasoning | 9 | 0 | 0/9 | unavailable | 12.72 | 2.673 | `ca78ec6a2979` |

![Request latency](../../../../diagrams/results/model-offloading/campaign-20261110T122314Z-d7f8e7e5-offload-model-offloading-1/latency.png)

## Interpretation and reproduction

Warmups and superseded attempts remain in raw data and are excluded from summaries. Each job/category is a separate cohort. Missing values remain unknown. Replay cost and generation latency are estimates; an offline oracle is an upper bound. LiveBench upstream grades are exported separately as judgment and benchmark summary records, not relabeled as local smoke scores.

Use the measured code revision and resolved configuration to reconstruct the campaign with your local artifact paths and credential references. Verify the recorded input hashes. Run `llm-eval plan --campaign YOUR_CAMPAIGN.json` before `llm-eval run --campaign YOUR_CAMPAIGN.json`. Synthetic results do not establish model quality or hardware performance.
