# model-offloading results

Status: **complete**. Synthetic fixtures: **false**.

Campaign: `matrix-mistral-small31`. Experiment run: `offload-model-offloading-1`. Measured code: `e64ec842608c30a6b4cba9f44b1711cc5e53ca19`.

[Raw measurements](raw/measurements.jsonl.gz) · [JSON summary](summary.json) · [CSV summary](summary.csv) · [Manifest](manifest.json) · [Resolved configuration](resolved-config.json)

## Configuration coverage

| Case | Hardware | OS | Harness | Model | Status |
|---|---|---|---|---|---|
| mistral-small31-koboldcpp | raider-windows | windows-11-native | koboldcpp | mistral-small31 | succeeded |
| mistral-small31-lmstudio | raider-windows | windows-11-native | lmstudio | mistral-small31 | succeeded |
| mistral-small31-ollama | raider-windows | windows-11-native | ollama | mistral-small31 | succeeded |

## Measurements by harness and model

| Harness | Model | Category | Requests | Errors or missing | Quality passes | Decision accuracy | Median seconds | Output tokens/s | Job |
|---|---|---|---:|---:|---:|---:|---:|---:|---|
| koboldcpp | mistral-small31 | coding | 9 | 0 | 0/9 | unavailable | 9.244 | 2.813 | `129abf22eb9d` |
| koboldcpp | mistral-small31 | math | 9 | 0 | 3/9 | unavailable | 6.102 | 2.786 | `129abf22eb9d` |
| koboldcpp | mistral-small31 | reasoning | 9 | 0 | 3/9 | unavailable | 1.262 | 2.378 | `129abf22eb9d` |
| lmstudio | mistral-small31 | coding | 9 | 0 | 0/9 | unavailable | 4.298 | 2.327 | `d7be41a213b0` |
| lmstudio | mistral-small31 | math | 9 | 0 | 3/9 | unavailable | 7.297 | 2.328 | `d7be41a213b0` |
| lmstudio | mistral-small31 | reasoning | 9 | 0 | 3/9 | unavailable | 1.301 | 2.307 | `d7be41a213b0` |
| ollama | mistral-small31 | coding | 9 | 0 | 0/9 | unavailable | 2.426 | 2.866 | `7fe65a7e7e83` |
| ollama | mistral-small31 | math | 9 | 0 | 3/9 | unavailable | 5.864 | 2.899 | `7fe65a7e7e83` |
| ollama | mistral-small31 | reasoning | 9 | 0 | 3/9 | unavailable | 1.037 | 2.893 | `7fe65a7e7e83` |

![Request latency](../../../../diagrams/results/model-offloading/campaign-20261110T083434Z-6ad3fdfe-offload-model-offloading-1/latency.png)

## Interpretation and reproduction

Warmups and superseded attempts remain in raw data and are excluded from summaries. Each job/category is a separate cohort. Missing values remain unknown. Replay cost and generation latency are estimates; an offline oracle is an upper bound. LiveBench upstream grades are exported separately as judgment and benchmark summary records, not relabeled as local smoke scores.

Use the measured code revision and resolved configuration to reconstruct the campaign with your local artifact paths and credential references. Verify the recorded input hashes. Run `llm-eval plan --campaign YOUR_CAMPAIGN.json` before `llm-eval run --campaign YOUR_CAMPAIGN.json`. Synthetic results do not establish model quality or hardware performance.
