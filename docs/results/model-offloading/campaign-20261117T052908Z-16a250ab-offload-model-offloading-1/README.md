# model-offloading results

Status: **complete**. Synthetic fixtures: **false**.

Campaign: `matrix-wsl-gemma4-31b`. Experiment run: `offload-model-offloading-1`. Measured code: `7e4606827cde8d9af4ccbb0c2ec8473d8d8049ce`.

[Raw measurements](raw/measurements.jsonl.gz) · [JSON summary](summary.json) · [CSV summary](summary.csv) · [Manifest](manifest.json) · [Resolved configuration](resolved-config.json)

## Configuration coverage

| Case | Hardware | OS | Harness | Model | Status |
|---|---|---|---|---|---|
| gemma4-31b-koboldcpp | raider-wsl | windows-11-wsl2-ubuntu-26.04 | koboldcpp | gemma4-31b | succeeded |
| gemma4-31b-ollama | raider-wsl | windows-11-wsl2-ubuntu-26.04 | ollama | gemma4-31b | succeeded |

## Measurements by harness and model

| Harness | Model | Category | Requests | Errors or missing | Quality passes | Decision accuracy | Median seconds | Output tokens/s | Job |
|---|---|---|---:|---:|---:|---:|---:|---:|---|
| koboldcpp | gemma4-31b | coding | 9 | 0 | 9/9 | unavailable | 1.133 | 2.647 | `9729952f4b4b` |
| koboldcpp | gemma4-31b | math | 9 | 0 | 9/9 | unavailable | 0.8089 | 2.534 | `9729952f4b4b` |
| koboldcpp | gemma4-31b | reasoning | 9 | 0 | 3/9 | unavailable | 0.8911 | 2.294 | `9729952f4b4b` |
| ollama | gemma4-31b | coding | 9 | 0 | 9/9 | unavailable | 53.13 | 3.357 | `3a3ebc52dbf6` |
| ollama | gemma4-31b | math | 9 | 0 | 9/9 | unavailable | 38.88 | 3.362 | `3a3ebc52dbf6` |
| ollama | gemma4-31b | reasoning | 9 | 0 | 6/9 | unavailable | 44.84 | 3.36 | `3a3ebc52dbf6` |

![Request latency](../../../../diagrams/results/model-offloading/campaign-20261117T052908Z-16a250ab-offload-model-offloading-1/latency.png)

## Interpretation and reproduction

Warmups and superseded attempts remain in raw data and are excluded from summaries. Each job/category is a separate cohort. Missing values remain unknown. Replay cost and generation latency are estimates; an offline oracle is an upper bound. LiveBench upstream grades are exported separately as judgment and benchmark summary records, not relabeled as local smoke scores.

Use the measured code revision and resolved configuration to reconstruct the campaign with your local artifact paths and credential references. Verify the recorded input hashes. Run `llm-eval plan --campaign YOUR_CAMPAIGN.json` before `llm-eval run --campaign YOUR_CAMPAIGN.json`. Synthetic results do not establish model quality or hardware performance.
