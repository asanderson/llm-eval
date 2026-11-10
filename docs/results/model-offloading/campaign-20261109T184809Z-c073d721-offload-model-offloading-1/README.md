# model-offloading results

Status: **complete**. Synthetic fixtures: **false**.

Campaign: `matrix-nemotron-super-49b`. Experiment run: `offload-model-offloading-1`. Measured code: `e64ec842608c30a6b4cba9f44b1711cc5e53ca19`.

[Raw measurements](raw/measurements.jsonl.gz) · [JSON summary](summary.json) · [CSV summary](summary.csv) · [Manifest](manifest.json) · [Resolved configuration](resolved-config.json)

## Configuration coverage

| Case | Hardware | OS | Harness | Model | Status |
|---|---|---|---|---|---|
| nemotron-super-49b-koboldcpp | raider-windows | windows-11-native | koboldcpp | nemotron-super-49b | succeeded |
| nemotron-super-49b-lmstudio | raider-windows | windows-11-native | lmstudio | nemotron-super-49b | succeeded |
| nemotron-super-49b-ollama | raider-windows | windows-11-native | ollama | nemotron-super-49b | succeeded |

## Measurements by harness and model

| Harness | Model | Category | Requests | Errors or missing | Quality passes | Decision accuracy | Median seconds | Output tokens/s | Job |
|---|---|---|---:|---:|---:|---:|---:|---:|---|
| koboldcpp | nemotron-super-49b | coding | 9 | 0 | 6/9 | unavailable | 172.8 | 2.956 | `e10f80682fcb` |
| koboldcpp | nemotron-super-49b | math | 9 | 0 | 3/9 | unavailable | 265.3 | 3.015 | `e10f80682fcb` |
| koboldcpp | nemotron-super-49b | reasoning | 9 | 0 | 6/9 | unavailable | 175.9 | 3.029 | `e10f80682fcb` |
| lmstudio | nemotron-super-49b | coding | 9 | 0 | 6/9 | unavailable | 193.1 | 2.652 | `39784eb03258` |
| lmstudio | nemotron-super-49b | math | 9 | 0 | 0/9 | unavailable | 303.5 | 2.639 | `39784eb03258` |
| lmstudio | nemotron-super-49b | reasoning | 9 | 0 | 6/9 | unavailable | 220.3 | 2.652 | `39784eb03258` |
| ollama | nemotron-super-49b | coding | 9 | 0 | 6/9 | unavailable | 131.2 | 3.07 | `f8f3b4e3e15b` |
| ollama | nemotron-super-49b | math | 9 | 0 | 0/9 | unavailable | 259.8 | 3.068 | `f8f3b4e3e15b` |
| ollama | nemotron-super-49b | reasoning | 9 | 0 | 6/9 | unavailable | 158 | 3.052 | `f8f3b4e3e15b` |

![Request latency](../../../../diagrams/results/model-offloading/campaign-20261109T184809Z-c073d721-offload-model-offloading-1/latency.png)

## Interpretation and reproduction

Warmups and superseded attempts remain in raw data and are excluded from summaries. Each job/category is a separate cohort. Missing values remain unknown. Replay cost and generation latency are estimates; an offline oracle is an upper bound. LiveBench upstream grades are exported separately as judgment and benchmark summary records, not relabeled as local smoke scores.

Use the measured code revision and resolved configuration to reconstruct the campaign with your local artifact paths and credential references. Verify the recorded input hashes. Run `llm-eval plan --campaign YOUR_CAMPAIGN.json` before `llm-eval run --campaign YOUR_CAMPAIGN.json`. Synthetic results do not establish model quality or hardware performance.
