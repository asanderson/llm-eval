# model-offloading results

Status: **incomplete**. Synthetic fixtures: **false**.

Campaign: `matrix-gemma4-26b-moe`. Experiment run: `offload-model-offloading-1`. Measured code: `e64ec842608c30a6b4cba9f44b1711cc5e53ca19`.

[Raw measurements](raw/measurements.jsonl.gz) · [JSON summary](summary.json) · [CSV summary](summary.csv) · [Manifest](manifest.json) · [Resolved configuration](resolved-config.json)

## Configuration coverage

| Case | Hardware | OS | Harness | Model | Status |
|---|---|---|---|---|---|
| gemma4-26b-moe-koboldcpp | raider-windows | windows-11-native | koboldcpp | gemma4-26b-moe | succeeded |
| gemma4-26b-moe-lmstudio | raider-windows | windows-11-native | lmstudio | gemma4-26b-moe | succeeded |
| gemma4-26b-moe-ollama | raider-windows | windows-11-native | ollama | gemma4-26b-moe | failed |

## Measurements by harness and model

| Harness | Model | Category | Requests | Errors or missing | Quality passes | Decision accuracy | Median seconds | Output tokens/s | Job |
|---|---|---|---:|---:|---:|---:|---:|---:|---|
| koboldcpp | gemma4-26b-moe | coding | 9 | 0 | 9/9 | unavailable | 0.5904 | 5.216 | `38ffad82cecc` |
| koboldcpp | gemma4-26b-moe | math | 9 | 0 | 9/9 | unavailable | 0.5912 | 3.384 | `38ffad82cecc` |
| koboldcpp | gemma4-26b-moe | reasoning | 9 | 0 | 3/9 | unavailable | 0.5748 | 3.533 | `38ffad82cecc` |
| lmstudio | gemma4-26b-moe | coding | 9 | 0 | 9/9 | unavailable | 14.58 | 13.57 | `a02fb7d85449` |
| lmstudio | gemma4-26b-moe | math | 9 | 0 | 9/9 | unavailable | 14.74 | 13.59 | `a02fb7d85449` |
| lmstudio | gemma4-26b-moe | reasoning | 9 | 0 | 3/9 | unavailable | 13.48 | 13.57 | `a02fb7d85449` |

![Request latency](../../../../diagrams/results/model-offloading/campaign-20261111T110234Z-68c0f219-offload-model-offloading-1/latency.png)

## Interpretation and reproduction

Warmups and superseded attempts remain in raw data and are excluded from summaries. Each job/category is a separate cohort. Missing values remain unknown. Replay cost and generation latency are estimates; an offline oracle is an upper bound. LiveBench upstream grades are exported separately as judgment and benchmark summary records, not relabeled as local smoke scores.

Use the measured code revision and resolved configuration to reconstruct the campaign with your local artifact paths and credential references. Verify the recorded input hashes. Run `llm-eval plan --campaign YOUR_CAMPAIGN.json` before `llm-eval run --campaign YOUR_CAMPAIGN.json`. Synthetic results do not establish model quality or hardware performance.
