# model-offloading results

Status: **complete**. Synthetic fixtures: **false**.

Campaign: `matrix-nemotron-nano-30b`. Experiment run: `offload-model-offloading-1`. Measured code: `e69e23c502609a24da6b89744c32be3ea65f5fbd`.

[Raw measurements](raw/measurements.jsonl.gz) · [JSON summary](summary.json) · [CSV summary](summary.csv) · [Manifest](manifest.json) · [Resolved configuration](resolved-config.json)

## Configuration coverage

| Case | Hardware | OS | Harness | Model | Status |
|---|---|---|---|---|---|
| nemotron-nano-30b-koboldcpp | raider-windows | windows-11-native | koboldcpp | nemotron-nano-30b | succeeded |
| nemotron-nano-30b-lmstudio | raider-windows | windows-11-native | lmstudio | nemotron-nano-30b | succeeded |
| nemotron-nano-30b-ollama | raider-windows | windows-11-native | ollama | nemotron-nano-30b | succeeded |

## Measurements by harness and model

| Harness | Model | Category | Requests | Errors or missing | Quality passes | Decision accuracy | Median seconds | Output tokens/s | Job |
|---|---|---|---:|---:|---:|---:|---:|---:|---|
| koboldcpp | nemotron-nano-30b | coding | 9 | 0 | 3/9 | unavailable | 0.5819 | 3.527 | `d181c9d1571a` |
| koboldcpp | nemotron-nano-30b | math | 9 | 0 | 0/9 | unavailable | 1.102 | 22.29 | `d181c9d1571a` |
| koboldcpp | nemotron-nano-30b | reasoning | 9 | 0 | 0/9 | unavailable | 2.045 | 25.92 | `d181c9d1571a` |
| lmstudio | nemotron-nano-30b | coding | 9 | 0 | 9/9 | unavailable | 4.625 | 14.44 | `efb881da8017` |
| lmstudio | nemotron-nano-30b | math | 9 | 0 | 9/9 | unavailable | 4.587 | 14.39 | `efb881da8017` |
| lmstudio | nemotron-nano-30b | reasoning | 9 | 0 | 6/9 | unavailable | 6.883 | 14.51 | `efb881da8017` |
| ollama | nemotron-nano-30b | coding | 9 | 0 | 9/9 | unavailable | 2.469 | 29.57 | `0ea783c16fdf` |
| ollama | nemotron-nano-30b | math | 9 | 0 | 9/9 | unavailable | 2.124 | 28.74 | `0ea783c16fdf` |
| ollama | nemotron-nano-30b | reasoning | 9 | 0 | 6/9 | unavailable | 3.089 | 29.51 | `0ea783c16fdf` |

![Request latency](../../../../diagrams/results/model-offloading/campaign-20261115T172956Z-1be0350b-offload-model-offloading-1/latency.png)

## Interpretation and reproduction

Warmups and superseded attempts remain in raw data and are excluded from summaries. Each job/category is a separate cohort. Missing values remain unknown. Replay cost and generation latency are estimates; an offline oracle is an upper bound. LiveBench upstream grades are exported separately as judgment and benchmark summary records, not relabeled as local smoke scores.

Use the measured code revision and resolved configuration to reconstruct the campaign with your local artifact paths and credential references. Verify the recorded input hashes. Run `llm-eval plan --campaign YOUR_CAMPAIGN.json` before `llm-eval run --campaign YOUR_CAMPAIGN.json`. Synthetic results do not establish model quality or hardware performance.
