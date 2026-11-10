# model-offloading results

Status: **complete**. Synthetic fixtures: **false**.

Campaign: `matrix-llama3-70b`. Experiment run: `offload-model-offloading-1`. Measured code: `e64ec842608c30a6b4cba9f44b1711cc5e53ca19`.

[Raw measurements](raw/measurements.jsonl.gz) · [JSON summary](summary.json) · [CSV summary](summary.csv) · [Manifest](manifest.json) · [Resolved configuration](resolved-config.json)

## Configuration coverage

| Case | Hardware | OS | Harness | Model | Status |
|---|---|---|---|---|---|
| llama3-70b-koboldcpp | raider-windows | windows-11-native | koboldcpp | llama3-70b | succeeded |
| llama3-70b-lmstudio | raider-windows | windows-11-native | lmstudio | llama3-70b | succeeded |
| llama3-70b-ollama | raider-windows | windows-11-native | ollama | llama3-70b | succeeded |

## Measurements by harness and model

| Harness | Model | Category | Requests | Errors or missing | Quality passes | Decision accuracy | Median seconds | Output tokens/s | Job |
|---|---|---|---:|---:|---:|---:|---:|---:|---|
| koboldcpp | llama3-70b | coding | 9 | 0 | 6/9 | unavailable | 2.489 | 2.411 | `c2e750a5613c` |
| koboldcpp | llama3-70b | math | 9 | 0 | 6/9 | unavailable | 0.9983 | 2.053 | `c2e750a5613c` |
| koboldcpp | llama3-70b | reasoning | 9 | 0 | 3/9 | unavailable | 1.343 | 2.234 | `c2e750a5613c` |
| lmstudio | llama3-70b | coding | 9 | 0 | 6/9 | unavailable | 2.648 | 2.266 | `efa5ea7463d1` |
| lmstudio | llama3-70b | math | 9 | 0 | 6/9 | unavailable | 0.8917 | 2.268 | `efa5ea7463d1` |
| lmstudio | llama3-70b | reasoning | 9 | 0 | 3/9 | unavailable | 1.324 | 2.266 | `efa5ea7463d1` |
| ollama | llama3-70b | coding | 9 | 0 | 6/9 | unavailable | 2.352 | 2.646 | `fcb1df403f7f` |
| ollama | llama3-70b | math | 9 | 0 | 6/9 | unavailable | 0.7731 | 2.622 | `fcb1df403f7f` |
| ollama | llama3-70b | reasoning | 9 | 0 | 3/9 | unavailable | 1.133 | 2.679 | `fcb1df403f7f` |

![Request latency](../../../../diagrams/results/model-offloading/campaign-20261110T130729Z-161fd0ce-offload-model-offloading-1/latency.png)

## Interpretation and reproduction

Warmups and superseded attempts remain in raw data and are excluded from summaries. Each job/category is a separate cohort. Missing values remain unknown. Replay cost and generation latency are estimates; an offline oracle is an upper bound. LiveBench upstream grades are exported separately as judgment and benchmark summary records, not relabeled as local smoke scores.

Use the measured code revision and resolved configuration to reconstruct the campaign with your local artifact paths and credential references. Verify the recorded input hashes. Run `llm-eval plan --campaign YOUR_CAMPAIGN.json` before `llm-eval run --campaign YOUR_CAMPAIGN.json`. Synthetic results do not establish model quality or hardware performance.
