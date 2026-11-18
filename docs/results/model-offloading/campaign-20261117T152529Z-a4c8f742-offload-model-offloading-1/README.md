# model-offloading results

Status: **complete**. Synthetic fixtures: **false**.

Campaign: `matrix-wsl-nemotron-super-49b`. Experiment run: `offload-model-offloading-1`. Measured code: `7e4606827cde8d9af4ccbb0c2ec8473d8d8049ce`.

[Raw measurements](raw/measurements.jsonl.gz) · [JSON summary](summary.json) · [CSV summary](summary.csv) · [Manifest](manifest.json) · [Resolved configuration](resolved-config.json)

## Configuration coverage

| Case | Hardware | OS | Harness | Model | Status |
|---|---|---|---|---|---|
| nemotron-super-49b-koboldcpp | raider-wsl | windows-11-wsl2-ubuntu-26.04 | koboldcpp | nemotron-super-49b | succeeded |
| nemotron-super-49b-ollama | raider-wsl | windows-11-wsl2-ubuntu-26.04 | ollama | nemotron-super-49b | succeeded |

## Measurements by harness and model

| Harness | Model | Category | Requests | Errors or missing | Quality passes | Decision accuracy | Median seconds | Output tokens/s | Job |
|---|---|---|---:|---:|---:|---:|---:|---:|---|
| koboldcpp | nemotron-super-49b | coding | 9 | 0 | 6/9 | unavailable | 173.9 | 2.876 | `3143d7ff5534` |
| koboldcpp | nemotron-super-49b | math | 9 | 0 | 3/9 | unavailable | 228.5 | 2.971 | `3143d7ff5534` |
| koboldcpp | nemotron-super-49b | reasoning | 9 | 0 | 6/9 | unavailable | 189.2 | 2.936 | `3143d7ff5534` |
| ollama | nemotron-super-49b | coding | 9 | 0 | 6/9 | unavailable | 135.9 | 3.037 | `d4bf061daedb` |
| ollama | nemotron-super-49b | math | 9 | 0 | 0/9 | unavailable | 280.6 | 3.008 | `d4bf061daedb` |
| ollama | nemotron-super-49b | reasoning | 9 | 0 | 6/9 | unavailable | 164.5 | 3.026 | `d4bf061daedb` |

![Request latency](../../../../diagrams/results/model-offloading/campaign-20261117T152529Z-a4c8f742-offload-model-offloading-1/latency.png)

## Interpretation and reproduction

Warmups and superseded attempts remain in raw data and are excluded from summaries. Each job/category is a separate cohort. Missing values remain unknown. Replay cost and generation latency are estimates; an offline oracle is an upper bound. LiveBench upstream grades are exported separately as judgment and benchmark summary records, not relabeled as local smoke scores.

Use the measured code revision and resolved configuration to reconstruct the campaign with your local artifact paths and credential references. Verify the recorded input hashes. Run `llm-eval plan --campaign YOUR_CAMPAIGN.json` before `llm-eval run --campaign YOUR_CAMPAIGN.json`. Synthetic results do not establish model quality or hardware performance.
