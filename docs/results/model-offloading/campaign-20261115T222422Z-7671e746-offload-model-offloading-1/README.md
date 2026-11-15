# model-offloading results

Status: **complete**. Synthetic fixtures: **false**.

Campaign: `matrix-qwen38-27b`. Experiment run: `offload-model-offloading-1`. Measured code: `4c11da3344793596cf51aa0b4b979c56f35fe36b`.

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
| koboldcpp | qwen38-27b | coding | 9 | 0 | 9/9 | unavailable | 26.2 | 3.486 | `a9c9aeebbc4d` |
| koboldcpp | qwen38-27b | math | 9 | 0 | 9/9 | unavailable | 20.34 | 3.278 | `a9c9aeebbc4d` |
| koboldcpp | qwen38-27b | reasoning | 9 | 0 | 6/9 | unavailable | 25.81 | 3.482 | `a9c9aeebbc4d` |
| lmstudio | qwen38-27b | coding | 9 | 0 | 9/9 | unavailable | 7.916 | 6.063 | `fac3127225ae` |
| lmstudio | qwen38-27b | math | 9 | 0 | 9/9 | unavailable | 7.017 | 6.99 | `fac3127225ae` |
| lmstudio | qwen38-27b | reasoning | 9 | 0 | 6/9 | unavailable | 8.079 | 6.444 | `fac3127225ae` |
| ollama | qwen38-27b | coding | 9 | 0 | 9/9 | unavailable | 19.46 | 3.381 | `e1feb0ce918f` |
| ollama | qwen38-27b | math | 9 | 0 | 9/9 | unavailable | 15.91 | 3.435 | `e1feb0ce918f` |
| ollama | qwen38-27b | reasoning | 9 | 0 | 6/9 | unavailable | 17.56 | 3.439 | `e1feb0ce918f` |

![Request latency](../../../../diagrams/results/model-offloading/campaign-20261115T222422Z-7671e746-offload-model-offloading-1/latency.png)

## Interpretation and reproduction

Warmups and superseded attempts remain in raw data and are excluded from summaries. Each job/category is a separate cohort. Missing values remain unknown. Replay cost and generation latency are estimates; an offline oracle is an upper bound. LiveBench upstream grades are exported separately as judgment and benchmark summary records, not relabeled as local smoke scores.

Use the measured code revision and resolved configuration to reconstruct the campaign with your local artifact paths and credential references. Verify the recorded input hashes. Run `llm-eval plan --campaign YOUR_CAMPAIGN.json` before `llm-eval run --campaign YOUR_CAMPAIGN.json`. Synthetic results do not establish model quality or hardware performance.
