# model-offloading results

Status: **complete**. Synthetic fixtures: **false**.

Campaign: `matrix-wsl-gemma3-27b`. Experiment run: `offload-model-offloading-1`. Measured code: `7e4606827cde8d9af4ccbb0c2ec8473d8d8049ce`.

[Raw measurements](raw/measurements.jsonl.gz) · [JSON summary](summary.json) · [CSV summary](summary.csv) · [Manifest](manifest.json) · [Resolved configuration](resolved-config.json)

## Configuration coverage

| Case | Hardware | OS | Harness | Model | Status |
|---|---|---|---|---|---|
| gemma3-27b-lmstudio | raider-wsl | windows-11-wsl2-ubuntu-26.04 | lmstudio | gemma3-27b | succeeded |

## Measurements by harness and model

| Harness | Model | Category | Requests | Errors or missing | Quality passes | Decision accuracy | Median seconds | Output tokens/s | Job |
|---|---|---|---:|---:|---:|---:|---:|---:|---|
| lmstudio | gemma3-27b | coding | 9 | 0 | 9/9 | unavailable | 1.699 | 2.355 | `097e8d2fdfb9` |
| lmstudio | gemma3-27b | math | 9 | 0 | 6/9 | unavailable | 1.514 | 2.207 | `097e8d2fdfb9` |
| lmstudio | gemma3-27b | reasoning | 9 | 0 | 3/9 | unavailable | 15.29 | 2.812 | `097e8d2fdfb9` |

![Request latency](../../../../diagrams/results/model-offloading/campaign-20261122T004854Z-df06d9cb-offload-model-offloading-1/latency.png)

## Interpretation and reproduction

Warmups and superseded attempts remain in raw data and are excluded from summaries. Each job/category is a separate cohort. Missing values remain unknown. Replay cost and generation latency are estimates; an offline oracle is an upper bound. LiveBench upstream grades are exported separately as judgment and benchmark summary records, not relabeled as local smoke scores.

Use the measured code revision and resolved configuration to reconstruct the campaign with your local artifact paths and credential references. Verify the recorded input hashes. Run `llm-eval plan --campaign YOUR_CAMPAIGN.json` before `llm-eval run --campaign YOUR_CAMPAIGN.json`. Synthetic results do not establish model quality or hardware performance.
