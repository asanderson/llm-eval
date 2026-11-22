# model-offloading results

Status: **complete**. Synthetic fixtures: **false**.

Campaign: `matrix-wsl-qwen35-35b-moe`. Experiment run: `offload-model-offloading-1`. Measured code: `7e4606827cde8d9af4ccbb0c2ec8473d8d8049ce`.

[Raw measurements](raw/measurements.jsonl.gz) · [JSON summary](summary.json) · [CSV summary](summary.csv) · [Manifest](manifest.json) · [Resolved configuration](resolved-config.json)

## Configuration coverage

| Case | Hardware | OS | Harness | Model | Status |
|---|---|---|---|---|---|
| qwen35-35b-moe-lmstudio | raider-wsl | windows-11-wsl2-ubuntu-26.04 | lmstudio | qwen35-35b-moe | succeeded |

## Measurements by harness and model

| Harness | Model | Category | Requests | Errors or missing | Quality passes | Decision accuracy | Median seconds | Output tokens/s | Job |
|---|---|---|---:|---:|---:|---:|---:|---:|---|
| lmstudio | qwen35-35b-moe | coding | 9 | 0 | 9/9 | unavailable | 9.406 | 40.66 | `2c1d7fe5267e` |
| lmstudio | qwen35-35b-moe | math | 9 | 0 | 9/9 | unavailable | 6.022 | 42.63 | `2c1d7fe5267e` |
| lmstudio | qwen35-35b-moe | reasoning | 9 | 0 | 9/9 | unavailable | 8.317 | 42.41 | `2c1d7fe5267e` |

![Request latency](../../../../diagrams/results/model-offloading/campaign-20261122T083921Z-1f20982a-offload-model-offloading-1/latency.png)

## Interpretation and reproduction

Warmups and superseded attempts remain in raw data and are excluded from summaries. Each job/category is a separate cohort. Missing values remain unknown. Replay cost and generation latency are estimates; an offline oracle is an upper bound. LiveBench upstream grades are exported separately as judgment and benchmark summary records, not relabeled as local smoke scores.

Use the measured code revision and resolved configuration to reconstruct the campaign with your local artifact paths and credential references. Verify the recorded input hashes. Run `llm-eval plan --campaign YOUR_CAMPAIGN.json` before `llm-eval run --campaign YOUR_CAMPAIGN.json`. Synthetic results do not establish model quality or hardware performance.
