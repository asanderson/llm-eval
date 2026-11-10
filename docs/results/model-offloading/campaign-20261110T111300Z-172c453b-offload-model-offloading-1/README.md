# model-offloading results

Status: **complete**. Synthetic fixtures: **false**.

Campaign: `matrix-kimi-linear-48b`. Experiment run: `offload-model-offloading-1`. Measured code: `e64ec842608c30a6b4cba9f44b1711cc5e53ca19`.

[Raw measurements](raw/measurements.jsonl.gz) · [JSON summary](summary.json) · [CSV summary](summary.csv) · [Manifest](manifest.json) · [Resolved configuration](resolved-config.json)

## Configuration coverage

| Case | Hardware | OS | Harness | Model | Status |
|---|---|---|---|---|---|
| kimi-linear-48b-koboldcpp | raider-windows | windows-11-native | koboldcpp | kimi-linear-48b | succeeded |
| kimi-linear-48b-lmstudio | raider-windows | windows-11-native | lmstudio | kimi-linear-48b | succeeded |
| kimi-linear-48b-ollama | raider-windows | windows-11-native | ollama | kimi-linear-48b | succeeded |

## Measurements by harness and model

| Harness | Model | Category | Requests | Errors or missing | Quality passes | Decision accuracy | Median seconds | Output tokens/s | Job |
|---|---|---|---:|---:|---:|---:|---:|---:|---|
| koboldcpp | kimi-linear-48b | coding | 9 | 0 | 9/9 | unavailable | 0.5822 | 3.522 | `82c7918309af` |
| koboldcpp | kimi-linear-48b | math | 9 | 0 | 9/9 | unavailable | 0.5754 | 3.476 | `82c7918309af` |
| koboldcpp | kimi-linear-48b | reasoning | 9 | 0 | 6/9 | unavailable | 0.5706 | 5.239 | `82c7918309af` |
| lmstudio | kimi-linear-48b | coding | 9 | 0 | 9/9 | unavailable | 0.1337 | 16.45 | `fdca39ed8f98` |
| lmstudio | kimi-linear-48b | math | 9 | 0 | 9/9 | unavailable | 0.133 | 15.04 | `fdca39ed8f98` |
| lmstudio | kimi-linear-48b | reasoning | 9 | 0 | 6/9 | unavailable | 0.3399 | 20.6 | `fdca39ed8f98` |
| ollama | kimi-linear-48b | coding | 9 | 0 | 9/9 | unavailable | 0.1334 | 17.04 | `400d91c422e5` |
| ollama | kimi-linear-48b | math | 9 | 0 | 9/9 | unavailable | 0.116 | 17.25 | `400d91c422e5` |
| ollama | kimi-linear-48b | reasoning | 9 | 0 | 6/9 | unavailable | 0.1857 | 16.16 | `400d91c422e5` |

![Request latency](../../../../diagrams/results/model-offloading/campaign-20261110T111300Z-172c453b-offload-model-offloading-1/latency.png)

## Interpretation and reproduction

Warmups and superseded attempts remain in raw data and are excluded from summaries. Each job/category is a separate cohort. Missing values remain unknown. Replay cost and generation latency are estimates; an offline oracle is an upper bound. LiveBench upstream grades are exported separately as judgment and benchmark summary records, not relabeled as local smoke scores.

Use the measured code revision and resolved configuration to reconstruct the campaign with your local artifact paths and credential references. Verify the recorded input hashes. Run `llm-eval plan --campaign YOUR_CAMPAIGN.json` before `llm-eval run --campaign YOUR_CAMPAIGN.json`. Synthetic results do not establish model quality or hardware performance.
