# model-offloading results

Status: **complete**. Synthetic fixtures: **false**.

Campaign: `matrix-wsl-qwen38-27b`. Experiment run: `offload-model-offloading-1`. Measured code: `7e4606827cde8d9af4ccbb0c2ec8473d8d8049ce`.

[Raw measurements](raw/measurements.jsonl.gz) · [JSON summary](summary.json) · [CSV summary](summary.csv) · [Manifest](manifest.json) · [Resolved configuration](resolved-config.json)

## Configuration coverage

| Case | Hardware | OS | Harness | Model | Status |
|---|---|---|---|---|---|
| qwen38-27b-koboldcpp | raider-wsl | windows-11-wsl2-ubuntu-26.04 | koboldcpp | qwen38-27b | succeeded |
| qwen38-27b-ollama | raider-wsl | windows-11-wsl2-ubuntu-26.04 | ollama | qwen38-27b | succeeded |

## Measurements by harness and model

| Harness | Model | Category | Requests | Errors or missing | Quality passes | Decision accuracy | Median seconds | Output tokens/s | Job |
|---|---|---|---:|---:|---:|---:|---:|---:|---|
| koboldcpp | qwen38-27b | coding | 9 | 0 | 9/9 | unavailable | 25.27 | 3.59 | `60da8e110b61` |
| koboldcpp | qwen38-27b | math | 9 | 0 | 9/9 | unavailable | 19.35 | 3.358 | `60da8e110b61` |
| koboldcpp | qwen38-27b | reasoning | 9 | 0 | 6/9 | unavailable | 25.21 | 3.491 | `60da8e110b61` |
| ollama | qwen38-27b | coding | 9 | 0 | 9/9 | unavailable | 18.25 | 3.654 | `f310d5966d5c` |
| ollama | qwen38-27b | math | 9 | 0 | 9/9 | unavailable | 15.63 | 3.647 | `f310d5966d5c` |
| ollama | qwen38-27b | reasoning | 9 | 0 | 6/9 | unavailable | 16.41 | 3.651 | `f310d5966d5c` |

![Request latency](../../../../diagrams/results/model-offloading/campaign-20261117T044726Z-01d2a5a1-offload-model-offloading-1/latency.png)

## Interpretation and reproduction

Warmups and superseded attempts remain in raw data and are excluded from summaries. Each job/category is a separate cohort. Missing values remain unknown. Replay cost and generation latency are estimates; an offline oracle is an upper bound. LiveBench upstream grades are exported separately as judgment and benchmark summary records, not relabeled as local smoke scores.

Use the measured code revision and resolved configuration to reconstruct the campaign with your local artifact paths and credential references. Verify the recorded input hashes. Run `llm-eval plan --campaign YOUR_CAMPAIGN.json` before `llm-eval run --campaign YOUR_CAMPAIGN.json`. Synthetic results do not establish model quality or hardware performance.
