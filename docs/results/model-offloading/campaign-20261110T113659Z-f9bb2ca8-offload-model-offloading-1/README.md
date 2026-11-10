# model-offloading results

Status: **complete**. Synthetic fixtures: **false**.

Campaign: `matrix-llama33-70b`. Experiment run: `offload-model-offloading-1`. Measured code: `e64ec842608c30a6b4cba9f44b1711cc5e53ca19`.

[Raw measurements](raw/measurements.jsonl.gz) · [JSON summary](summary.json) · [CSV summary](summary.csv) · [Manifest](manifest.json) · [Resolved configuration](resolved-config.json)

## Configuration coverage

| Case | Hardware | OS | Harness | Model | Status |
|---|---|---|---|---|---|
| llama33-70b-koboldcpp | raider-windows | windows-11-native | koboldcpp | llama33-70b | succeeded |
| llama33-70b-lmstudio | raider-windows | windows-11-native | lmstudio | llama33-70b | succeeded |
| llama33-70b-ollama | raider-windows | windows-11-native | ollama | llama33-70b | succeeded |

## Measurements by harness and model

| Harness | Model | Category | Requests | Errors or missing | Quality passes | Decision accuracy | Median seconds | Output tokens/s | Job |
|---|---|---|---:|---:|---:|---:|---:|---:|---|
| koboldcpp | llama33-70b | coding | 9 | 0 | 6/9 | unavailable | 2.525 | 2.376 | `2974ef96487f` |
| koboldcpp | llama33-70b | math | 9 | 0 | 6/9 | unavailable | 0.9942 | 2.049 | `2974ef96487f` |
| koboldcpp | llama33-70b | reasoning | 9 | 0 | 3/9 | unavailable | 1.351 | 2.221 | `2974ef96487f` |
| lmstudio | llama33-70b | coding | 9 | 0 | 6/9 | unavailable | 2.651 | 2.263 | `0390c62a7124` |
| lmstudio | llama33-70b | math | 9 | 0 | 6/9 | unavailable | 0.893 | 2.262 | `0390c62a7124` |
| lmstudio | llama33-70b | reasoning | 9 | 0 | 3/9 | unavailable | 1.34 | 2.26 | `0390c62a7124` |
| ollama | llama33-70b | coding | 9 | 0 | 6/9 | unavailable | 2.283 | 2.617 | `691c92382f24` |
| ollama | llama33-70b | math | 9 | 0 | 6/9 | unavailable | 0.758 | 2.654 | `691c92382f24` |
| ollama | llama33-70b | reasoning | 9 | 0 | 3/9 | unavailable | 1.14 | 2.658 | `691c92382f24` |

![Request latency](../../../../diagrams/results/model-offloading/campaign-20261110T113659Z-f9bb2ca8-offload-model-offloading-1/latency.png)

## Interpretation and reproduction

Warmups and superseded attempts remain in raw data and are excluded from summaries. Each job/category is a separate cohort. Missing values remain unknown. Replay cost and generation latency are estimates; an offline oracle is an upper bound. LiveBench upstream grades are exported separately as judgment and benchmark summary records, not relabeled as local smoke scores.

Use the measured code revision and resolved configuration to reconstruct the campaign with your local artifact paths and credential references. Verify the recorded input hashes. Run `llm-eval plan --campaign YOUR_CAMPAIGN.json` before `llm-eval run --campaign YOUR_CAMPAIGN.json`. Synthetic results do not establish model quality or hardware performance.
