# model-offloading results

Status: **complete**. Synthetic fixtures: **false**.

Campaign: `matrix-wsl-llama33-70b`. Experiment run: `offload-model-offloading-1`. Measured code: `7e4606827cde8d9af4ccbb0c2ec8473d8d8049ce`.

[Raw measurements](raw/measurements.jsonl.gz) · [JSON summary](summary.json) · [CSV summary](summary.csv) · [Manifest](manifest.json) · [Resolved configuration](resolved-config.json)

## Configuration coverage

| Case | Hardware | OS | Harness | Model | Status |
|---|---|---|---|---|---|
| llama33-70b-koboldcpp | raider-wsl | windows-11-wsl2-ubuntu-26.04 | koboldcpp | llama33-70b | succeeded |
| llama33-70b-ollama | raider-wsl | windows-11-wsl2-ubuntu-26.04 | ollama | llama33-70b | succeeded |

## Measurements by harness and model

| Harness | Model | Category | Requests | Errors or missing | Quality passes | Decision accuracy | Median seconds | Output tokens/s | Job |
|---|---|---|---:|---:|---:|---:|---:|---:|---|
| koboldcpp | llama33-70b | coding | 9 | 0 | 6/9 | unavailable | 2.516 | 2.384 | `10b30d53fd20` |
| koboldcpp | llama33-70b | math | 9 | 0 | 6/9 | unavailable | 0.9522 | 2.104 | `10b30d53fd20` |
| koboldcpp | llama33-70b | reasoning | 9 | 0 | 3/9 | unavailable | 1.336 | 2.245 | `10b30d53fd20` |
| ollama | llama33-70b | coding | 9 | 0 | 6/9 | unavailable | 2.311 | 2.616 | `bd49a015ccb1` |
| ollama | llama33-70b | math | 9 | 0 | 6/9 | unavailable | 0.7714 | 2.632 | `bd49a015ccb1` |
| ollama | llama33-70b | reasoning | 9 | 0 | 3/9 | unavailable | 1.143 | 2.627 | `bd49a015ccb1` |

![Request latency](../../../../diagrams/results/model-offloading/campaign-20261117T210308Z-f839a69f-offload-model-offloading-1/latency.png)

## Interpretation and reproduction

Warmups and superseded attempts remain in raw data and are excluded from summaries. Each job/category is a separate cohort. Missing values remain unknown. Replay cost and generation latency are estimates; an offline oracle is an upper bound. LiveBench upstream grades are exported separately as judgment and benchmark summary records, not relabeled as local smoke scores.

Use the measured code revision and resolved configuration to reconstruct the campaign with your local artifact paths and credential references. Verify the recorded input hashes. Run `llm-eval plan --campaign YOUR_CAMPAIGN.json` before `llm-eval run --campaign YOUR_CAMPAIGN.json`. Synthetic results do not establish model quality or hardware performance.
