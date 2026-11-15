# model-offloading results

Status: **complete**. Synthetic fixtures: **false**.

Campaign: `matrix-laguna-xs21`. Experiment run: `offload-model-offloading-1`. Measured code: `e69e23c502609a24da6b89744c32be3ea65f5fbd`.

[Raw measurements](raw/measurements.jsonl.gz) · [JSON summary](summary.json) · [CSV summary](summary.csv) · [Manifest](manifest.json) · [Resolved configuration](resolved-config.json)

## Configuration coverage

| Case | Hardware | OS | Harness | Model | Status |
|---|---|---|---|---|---|
| laguna-xs21-koboldcpp | raider-windows | windows-11-native | koboldcpp | laguna-xs21 | succeeded |
| laguna-xs21-lmstudio | raider-windows | windows-11-native | lmstudio | laguna-xs21 | succeeded |
| laguna-xs21-ollama | raider-windows | windows-11-native | ollama | laguna-xs21 | succeeded |

## Measurements by harness and model

| Harness | Model | Category | Requests | Errors or missing | Quality passes | Decision accuracy | Median seconds | Output tokens/s | Job |
|---|---|---|---:|---:|---:|---:|---:|---:|---|
| koboldcpp | laguna-xs21 | coding | 9 | 0 | 3/9 | unavailable | 0.5956 | 10.58 | `935056637371` |
| koboldcpp | laguna-xs21 | math | 9 | 0 | 0/9 | unavailable | 4.735 | 28.7 | `935056637371` |
| koboldcpp | laguna-xs21 | reasoning | 9 | 0 | 0/9 | unavailable | 1.403 | 24.94 | `935056637371` |
| lmstudio | laguna-xs21 | coding | 9 | 0 | 9/9 | unavailable | 13.09 | 27.31 | `de7260ca9c77` |
| lmstudio | laguna-xs21 | math | 9 | 0 | 0/9 | unavailable | 31.39 | 26.65 | `de7260ca9c77` |
| lmstudio | laguna-xs21 | reasoning | 9 | 0 | 3/9 | unavailable | 15.35 | 27.22 | `de7260ca9c77` |
| ollama | laguna-xs21 | coding | 9 | 0 | 9/9 | unavailable | 10.16 | 32.16 | `2506bfe7a950` |
| ollama | laguna-xs21 | math | 9 | 0 | 3/9 | unavailable | 29.13 | 30.62 | `2506bfe7a950` |
| ollama | laguna-xs21 | reasoning | 9 | 0 | 3/9 | unavailable | 14.7 | 31.55 | `2506bfe7a950` |

![Request latency](../../../../diagrams/results/model-offloading/campaign-20261115T164043Z-6fc5883d-offload-model-offloading-1/latency.png)

## Interpretation and reproduction

Warmups and superseded attempts remain in raw data and are excluded from summaries. Each job/category is a separate cohort. Missing values remain unknown. Replay cost and generation latency are estimates; an offline oracle is an upper bound. LiveBench upstream grades are exported separately as judgment and benchmark summary records, not relabeled as local smoke scores.

Use the measured code revision and resolved configuration to reconstruct the campaign with your local artifact paths and credential references. Verify the recorded input hashes. Run `llm-eval plan --campaign YOUR_CAMPAIGN.json` before `llm-eval run --campaign YOUR_CAMPAIGN.json`. Synthetic results do not establish model quality or hardware performance.
