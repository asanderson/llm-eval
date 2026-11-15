# model-offloading results

Status: **complete**. Synthetic fixtures: **false**.

Campaign: `matrix-llama33-70b`. Experiment run: `offload-model-offloading-1`. Measured code: `e69e23c502609a24da6b89744c32be3ea65f5fbd`.

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
| koboldcpp | llama33-70b | coding | 9 | 0 | 6/9 | unavailable | 2.633 | 2.279 | `2974ef96487f` |
| koboldcpp | llama33-70b | math | 9 | 0 | 6/9 | unavailable | 1.091 | 2.048 | `2974ef96487f` |
| koboldcpp | llama33-70b | reasoning | 9 | 0 | 3/9 | unavailable | 1.387 | 2.163 | `2974ef96487f` |
| lmstudio | llama33-70b | coding | 9 | 0 | 6/9 | unavailable | 2.767 | 2.081 | `0390c62a7124` |
| lmstudio | llama33-70b | math | 9 | 0 | 6/9 | unavailable | 0.932 | 2.15 | `0390c62a7124` |
| lmstudio | llama33-70b | reasoning | 9 | 0 | 3/9 | unavailable | 1.367 | 2.156 | `0390c62a7124` |
| ollama | llama33-70b | coding | 9 | 0 | 6/9 | unavailable | 2.36 | 2.47 | `691c92382f24` |
| ollama | llama33-70b | math | 9 | 0 | 6/9 | unavailable | 0.8154 | 2.474 | `691c92382f24` |
| ollama | llama33-70b | reasoning | 9 | 0 | 3/9 | unavailable | 1.162 | 2.601 | `691c92382f24` |

![Request latency](../../../../diagrams/results/model-offloading/campaign-20261115T201525Z-d393f04a-offload-model-offloading-1/latency.png)

## Interpretation and reproduction

Warmups and superseded attempts remain in raw data and are excluded from summaries. Each job/category is a separate cohort. Missing values remain unknown. Replay cost and generation latency are estimates; an offline oracle is an upper bound. LiveBench upstream grades are exported separately as judgment and benchmark summary records, not relabeled as local smoke scores.

Use the measured code revision and resolved configuration to reconstruct the campaign with your local artifact paths and credential references. Verify the recorded input hashes. Run `llm-eval plan --campaign YOUR_CAMPAIGN.json` before `llm-eval run --campaign YOUR_CAMPAIGN.json`. Synthetic results do not establish model quality or hardware performance.
