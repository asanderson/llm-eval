# model-offloading results

Status: **complete**. Synthetic fixtures: **false**.

Campaign: `matrix-wsl-gemma3-27b`. Experiment run: `offload-model-offloading-1`. Measured code: `7e4606827cde8d9af4ccbb0c2ec8473d8d8049ce`.

[Raw measurements](raw/measurements.jsonl.gz) · [JSON summary](summary.json) · [CSV summary](summary.csv) · [Manifest](manifest.json) · [Resolved configuration](resolved-config.json)

## Configuration coverage

| Case | Hardware | OS | Harness | Model | Status |
|---|---|---|---|---|---|
| gemma3-27b-koboldcpp | raider-wsl | windows-11-wsl2-ubuntu-26.04 | koboldcpp | gemma3-27b | succeeded |
| gemma3-27b-ollama | raider-wsl | windows-11-wsl2-ubuntu-26.04 | ollama | gemma3-27b | succeeded |

## Measurements by harness and model

| Harness | Model | Category | Requests | Errors or missing | Quality passes | Decision accuracy | Median seconds | Output tokens/s | Job |
|---|---|---|---:|---:|---:|---:|---:|---:|---|
| koboldcpp | gemma3-27b | coding | 9 | 0 | 9/9 | unavailable | 1.42 | 2.816 | `3c527ba7186d` |
| koboldcpp | gemma3-27b | math | 9 | 0 | 6/9 | unavailable | 1.033 | 2.964 | `3c527ba7186d` |
| koboldcpp | gemma3-27b | reasoning | 9 | 0 | 3/9 | unavailable | 3.753 | 3.464 | `3c527ba7186d` |
| ollama | gemma3-27b | coding | 9 | 0 | 9/9 | unavailable | 1.405 | 2.847 | `192aa0635cfc` |
| ollama | gemma3-27b | math | 9 | 0 | 6/9 | unavailable | 1.132 | 2.688 | `192aa0635cfc` |
| ollama | gemma3-27b | reasoning | 9 | 0 | 3/9 | unavailable | 3.777 | 3.442 | `192aa0635cfc` |

![Request latency](../../../../diagrams/results/model-offloading/campaign-20261117T073753Z-bee9d8ce-offload-model-offloading-1/latency.png)

## Interpretation and reproduction

Warmups and superseded attempts remain in raw data and are excluded from summaries. Each job/category is a separate cohort. Missing values remain unknown. Replay cost and generation latency are estimates; an offline oracle is an upper bound. LiveBench upstream grades are exported separately as judgment and benchmark summary records, not relabeled as local smoke scores.

Use the measured code revision and resolved configuration to reconstruct the campaign with your local artifact paths and credential references. Verify the recorded input hashes. Run `llm-eval plan --campaign YOUR_CAMPAIGN.json` before `llm-eval run --campaign YOUR_CAMPAIGN.json`. Synthetic results do not establish model quality or hardware performance.
