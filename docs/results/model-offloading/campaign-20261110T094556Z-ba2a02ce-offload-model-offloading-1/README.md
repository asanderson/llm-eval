# model-offloading results

Status: **complete**. Synthetic fixtures: **false**.

Campaign: `matrix-qwen35-35b-moe`. Experiment run: `offload-model-offloading-1`. Measured code: `e64ec842608c30a6b4cba9f44b1711cc5e53ca19`.

[Raw measurements](raw/measurements.jsonl.gz) · [JSON summary](summary.json) · [CSV summary](summary.csv) · [Manifest](manifest.json) · [Resolved configuration](resolved-config.json)

## Configuration coverage

| Case | Hardware | OS | Harness | Model | Status |
|---|---|---|---|---|---|
| qwen35-35b-moe-koboldcpp | raider-windows | windows-11-native | koboldcpp | qwen35-35b-moe | succeeded |
| qwen35-35b-moe-lmstudio | raider-windows | windows-11-native | lmstudio | qwen35-35b-moe | succeeded |
| qwen35-35b-moe-ollama | raider-windows | windows-11-native | ollama | qwen35-35b-moe | succeeded |

## Measurements by harness and model

| Harness | Model | Category | Requests | Errors or missing | Quality passes | Decision accuracy | Median seconds | Output tokens/s | Job |
|---|---|---|---:|---:|---:|---:|---:|---:|---|
| koboldcpp | qwen35-35b-moe | coding | 9 | 0 | 6/9 | unavailable | 0.5838 | 12.04 | `3440c611be06` |
| koboldcpp | qwen35-35b-moe | math | 9 | 0 | 9/9 | unavailable | 0.6918 | 9.42 | `3440c611be06` |
| koboldcpp | qwen35-35b-moe | reasoning | 9 | 0 | 3/9 | unavailable | 0.6872 | 9.572 | `3440c611be06` |
| lmstudio | qwen35-35b-moe | coding | 9 | 0 | 9/9 | unavailable | 10.85 | 38.73 | `dccf5345b081` |
| lmstudio | qwen35-35b-moe | math | 9 | 0 | 9/9 | unavailable | 6.987 | 43.56 | `dccf5345b081` |
| lmstudio | qwen35-35b-moe | reasoning | 9 | 0 | 6/9 | unavailable | 8.57 | 43.06 | `dccf5345b081` |
| ollama | qwen35-35b-moe | coding | 9 | 0 | 6/9 | unavailable | 13.64 | 30.06 | `11dcd9c81ae3` |
| ollama | qwen35-35b-moe | math | 9 | 0 | 9/9 | unavailable | 10.42 | 29.86 | `11dcd9c81ae3` |
| ollama | qwen35-35b-moe | reasoning | 9 | 0 | 6/9 | unavailable | 10.02 | 29.95 | `11dcd9c81ae3` |

![Request latency](../../../../diagrams/results/model-offloading/campaign-20261110T094556Z-ba2a02ce-offload-model-offloading-1/latency.png)

## Interpretation and reproduction

Warmups and superseded attempts remain in raw data and are excluded from summaries. Each job/category is a separate cohort. Missing values remain unknown. Replay cost and generation latency are estimates; an offline oracle is an upper bound. LiveBench upstream grades are exported separately as judgment and benchmark summary records, not relabeled as local smoke scores.

Use the measured code revision and resolved configuration to reconstruct the campaign with your local artifact paths and credential references. Verify the recorded input hashes. Run `llm-eval plan --campaign YOUR_CAMPAIGN.json` before `llm-eval run --campaign YOUR_CAMPAIGN.json`. Synthetic results do not establish model quality or hardware performance.
