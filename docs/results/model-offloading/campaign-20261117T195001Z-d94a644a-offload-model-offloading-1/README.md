# model-offloading results

Status: **complete**. Synthetic fixtures: **false**.

Campaign: `matrix-wsl-mistral-small31`. Experiment run: `offload-model-offloading-1`. Measured code: `7e4606827cde8d9af4ccbb0c2ec8473d8d8049ce`.

[Raw measurements](raw/measurements.jsonl.gz) · [JSON summary](summary.json) · [CSV summary](summary.csv) · [Manifest](manifest.json) · [Resolved configuration](resolved-config.json)

## Configuration coverage

| Case | Hardware | OS | Harness | Model | Status |
|---|---|---|---|---|---|
| mistral-small31-koboldcpp | raider-wsl | windows-11-wsl2-ubuntu-26.04 | koboldcpp | mistral-small31 | succeeded |
| mistral-small31-ollama | raider-wsl | windows-11-wsl2-ubuntu-26.04 | ollama | mistral-small31 | succeeded |

## Measurements by harness and model

| Harness | Model | Category | Requests | Errors or missing | Quality passes | Decision accuracy | Median seconds | Output tokens/s | Job |
|---|---|---|---:|---:|---:|---:|---:|---:|---|
| koboldcpp | mistral-small31 | coding | 9 | 0 | 0/9 | unavailable | 9.394 | 2.768 | `4fdd4a317ab7` |
| koboldcpp | mistral-small31 | math | 9 | 0 | 3/9 | unavailable | 6.128 | 2.774 | `4fdd4a317ab7` |
| koboldcpp | mistral-small31 | reasoning | 9 | 0 | 3/9 | unavailable | 1.236 | 2.428 | `4fdd4a317ab7` |
| ollama | mistral-small31 | coding | 9 | 0 | 0/9 | unavailable | 2.465 | 2.84 | `6415edfa1ed2` |
| ollama | mistral-small31 | math | 9 | 0 | 3/9 | unavailable | 5.963 | 2.85 | `6415edfa1ed2` |
| ollama | mistral-small31 | reasoning | 9 | 0 | 3/9 | unavailable | 1.068 | 2.838 | `6415edfa1ed2` |

![Request latency](../../../../diagrams/results/model-offloading/campaign-20261117T195001Z-d94a644a-offload-model-offloading-1/latency.png)

## Interpretation and reproduction

Warmups and superseded attempts remain in raw data and are excluded from summaries. Each job/category is a separate cohort. Missing values remain unknown. Replay cost and generation latency are estimates; an offline oracle is an upper bound. LiveBench upstream grades are exported separately as judgment and benchmark summary records, not relabeled as local smoke scores.

Use the measured code revision and resolved configuration to reconstruct the campaign with your local artifact paths and credential references. Verify the recorded input hashes. Run `llm-eval plan --campaign YOUR_CAMPAIGN.json` before `llm-eval run --campaign YOUR_CAMPAIGN.json`. Synthetic results do not establish model quality or hardware performance.
