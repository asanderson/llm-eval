# model-offloading results

Status: **complete**. Synthetic fixtures: **false**.

Campaign: `matrix-wsl-phi4-reasoning-plus`. Experiment run: `offload-model-offloading-1`. Measured code: `7e4606827cde8d9af4ccbb0c2ec8473d8d8049ce`.

[Raw measurements](raw/measurements.jsonl.gz) · [JSON summary](summary.json) · [CSV summary](summary.csv) · [Manifest](manifest.json) · [Resolved configuration](resolved-config.json)

## Configuration coverage

| Case | Hardware | OS | Harness | Model | Status |
|---|---|---|---|---|---|
| phi4-reasoning-plus-koboldcpp | raider-wsl | windows-11-wsl2-ubuntu-26.04 | koboldcpp | phi4-reasoning-plus | succeeded |
| phi4-reasoning-plus-ollama | raider-wsl | windows-11-wsl2-ubuntu-26.04 | ollama | phi4-reasoning-plus | succeeded |

## Measurements by harness and model

| Harness | Model | Category | Requests | Errors or missing | Quality passes | Decision accuracy | Median seconds | Output tokens/s | Job |
|---|---|---|---:|---:|---:|---:|---:|---:|---|
| koboldcpp | phi4-reasoning-plus | coding | 9 | 0 | 6/9 | unavailable | 0.5873 | 3.417 | `26eb342f820d` |
| koboldcpp | phi4-reasoning-plus | math | 9 | 0 | 6/9 | unavailable | 0.608 | 3.415 | `26eb342f820d` |
| koboldcpp | phi4-reasoning-plus | reasoning | 9 | 0 | 3/9 | unavailable | 398.5 | 5.117 | `26eb342f820d` |
| ollama | phi4-reasoning-plus | coding | 9 | 0 | 0/9 | unavailable | 396.7 | 5.163 | `9a6470999bac` |
| ollama | phi4-reasoning-plus | math | 9 | 0 | 0/9 | unavailable | 397.2 | 5.157 | `9a6470999bac` |
| ollama | phi4-reasoning-plus | reasoning | 9 | 0 | 0/9 | unavailable | 396.8 | 5.161 | `9a6470999bac` |

![Request latency](../../../../diagrams/results/model-offloading/campaign-20261117T101636Z-6ef57688-offload-model-offloading-1/latency.png)

## Interpretation and reproduction

Warmups and superseded attempts remain in raw data and are excluded from summaries. Each job/category is a separate cohort. Missing values remain unknown. Replay cost and generation latency are estimates; an offline oracle is an upper bound. LiveBench upstream grades are exported separately as judgment and benchmark summary records, not relabeled as local smoke scores.

Use the measured code revision and resolved configuration to reconstruct the campaign with your local artifact paths and credential references. Verify the recorded input hashes. Run `llm-eval plan --campaign YOUR_CAMPAIGN.json` before `llm-eval run --campaign YOUR_CAMPAIGN.json`. Synthetic results do not establish model quality or hardware performance.
