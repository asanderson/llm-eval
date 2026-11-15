# model-offloading results

Status: **complete**. Synthetic fixtures: **false**.

Campaign: `matrix-kimi-linear-48b`. Experiment run: `offload-model-offloading-1`. Measured code: `e69e23c502609a24da6b89744c32be3ea65f5fbd`.

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
| koboldcpp | kimi-linear-48b | coding | 9 | 0 | 9/9 | unavailable | 0.5687 | 3.541 | `82c7918309af` |
| koboldcpp | kimi-linear-48b | math | 9 | 0 | 9/9 | unavailable | 0.5797 | 3.45 | `82c7918309af` |
| koboldcpp | kimi-linear-48b | reasoning | 9 | 0 | 6/9 | unavailable | 0.5825 | 5.132 | `82c7918309af` |
| lmstudio | kimi-linear-48b | coding | 9 | 0 | 9/9 | unavailable | 0.147 | 15.76 | `fdca39ed8f98` |
| lmstudio | kimi-linear-48b | math | 9 | 0 | 9/9 | unavailable | 0.1293 | 15.46 | `fdca39ed8f98` |
| lmstudio | kimi-linear-48b | reasoning | 9 | 0 | 6/9 | unavailable | 0.325 | 21.54 | `fdca39ed8f98` |
| ollama | kimi-linear-48b | coding | 9 | 0 | 9/9 | unavailable | 0.1408 | 16.84 | `400d91c422e5` |
| ollama | kimi-linear-48b | math | 9 | 0 | 9/9 | unavailable | 0.1283 | 15.58 | `400d91c422e5` |
| ollama | kimi-linear-48b | reasoning | 9 | 0 | 6/9 | unavailable | 0.1634 | 18.36 | `400d91c422e5` |

![Request latency](../../../../diagrams/results/model-offloading/campaign-20261115T140213Z-85f189ba-offload-model-offloading-1/latency.png)

## Interpretation and reproduction

Warmups and superseded attempts remain in raw data and are excluded from summaries. Each job/category is a separate cohort. Missing values remain unknown. Replay cost and generation latency are estimates; an offline oracle is an upper bound. LiveBench upstream grades are exported separately as judgment and benchmark summary records, not relabeled as local smoke scores.

Use the measured code revision and resolved configuration to reconstruct the campaign with your local artifact paths and credential references. Verify the recorded input hashes. Run `llm-eval plan --campaign YOUR_CAMPAIGN.json` before `llm-eval run --campaign YOUR_CAMPAIGN.json`. Synthetic results do not establish model quality or hardware performance.
