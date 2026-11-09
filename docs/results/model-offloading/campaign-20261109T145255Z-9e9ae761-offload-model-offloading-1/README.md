# model-offloading results

Status: **complete**. Synthetic fixtures: **false**.

Campaign: `matrix-qwen38-27b`. Experiment run: `offload-model-offloading-1`. Measured code: `22875f4287b73f06d0539b5af605bc5fb1fb706d`.

[Raw measurements](raw/measurements.jsonl.gz) · [JSON summary](summary.json) · [CSV summary](summary.csv) · [Manifest](manifest.json) · [Resolved configuration](resolved-config.json)

## Configuration coverage

| Case | Hardware | OS | Harness | Model | Status |
|---|---|---|---|---|---|
| qwen38-27b-koboldcpp | raider-windows | windows-11-native | koboldcpp | qwen38-27b | succeeded |
| qwen38-27b-lmstudio | raider-windows | windows-11-native | lmstudio | qwen38-27b | succeeded |
| qwen38-27b-ollama | raider-windows | windows-11-native | ollama | qwen38-27b | succeeded |

## Measurements by harness and model

| Harness | Model | Category | Requests | Errors or missing | Quality passes | Decision accuracy | Median seconds | Output tokens/s | Job |
|---|---|---|---:|---:|---:|---:|---:|---:|---|
| koboldcpp | qwen38-27b | coding | 9 | 0 | 9/9 | unavailable | 25.86 | 3.537 | `a9c9aeebbc4d` |
| koboldcpp | qwen38-27b | math | 9 | 0 | 9/9 | unavailable | 19.65 | 3.307 | `a9c9aeebbc4d` |
| koboldcpp | qwen38-27b | reasoning | 9 | 0 | 6/9 | unavailable | 25 | 3.51 | `a9c9aeebbc4d` |
| lmstudio | qwen38-27b | coding | 9 | 0 | 9/9 | unavailable | 7.747 | 5.933 | `fac3127225ae` |
| lmstudio | qwen38-27b | math | 9 | 0 | 9/9 | unavailable | 7.222 | 6.804 | `fac3127225ae` |
| lmstudio | qwen38-27b | reasoning | 9 | 0 | 6/9 | unavailable | 9.133 | 6.403 | `fac3127225ae` |
| ollama | qwen38-27b | coding | 9 | 0 | 9/9 | unavailable | 18.69 | 3.577 | `e1feb0ce918f` |
| ollama | qwen38-27b | math | 9 | 0 | 9/9 | unavailable | 16.05 | 3.552 | `e1feb0ce918f` |
| ollama | qwen38-27b | reasoning | 9 | 0 | 6/9 | unavailable | 16.83 | 3.565 | `e1feb0ce918f` |

![Request latency](../../../../diagrams/results/model-offloading/campaign-20261109T145255Z-9e9ae761-offload-model-offloading-1/latency.png)

## Interpretation and reproduction

Warmups and superseded attempts remain in raw data and are excluded from summaries. Each job/category is a separate cohort. Missing values remain unknown. Replay cost and generation latency are estimates; an offline oracle is an upper bound. LiveBench upstream grades are exported separately as judgment and benchmark summary records, not relabeled as local smoke scores.

Use the measured code revision and resolved configuration to reconstruct the campaign with your local artifact paths and credential references. Verify the recorded input hashes. Run `llm-eval plan --campaign YOUR_CAMPAIGN.json` before `llm-eval run --campaign YOUR_CAMPAIGN.json`. Synthetic results do not establish model quality or hardware performance.
