# model-offloading results

Status: **complete**. Synthetic fixtures: **false**.

Campaign: `matrix-wsl-llama3-70b`. Experiment run: `offload-model-offloading-1`. Measured code: `7e4606827cde8d9af4ccbb0c2ec8473d8d8049ce`.

[Raw measurements](raw/measurements.jsonl.gz) · [JSON summary](summary.json) · [CSV summary](summary.csv) · [Manifest](manifest.json) · [Resolved configuration](resolved-config.json)

## Configuration coverage

| Case | Hardware | OS | Harness | Model | Status |
|---|---|---|---|---|---|
| llama3-70b-koboldcpp | raider-wsl | windows-11-wsl2-ubuntu-26.04 | koboldcpp | llama3-70b | succeeded |
| llama3-70b-ollama | raider-wsl | windows-11-wsl2-ubuntu-26.04 | ollama | llama3-70b | succeeded |

## Measurements by harness and model

| Harness | Model | Category | Requests | Errors or missing | Quality passes | Decision accuracy | Median seconds | Output tokens/s | Job |
|---|---|---|---:|---:|---:|---:|---:|---:|---|
| koboldcpp | llama3-70b | coding | 9 | 0 | 6/9 | unavailable | 2.5 | 2.4 | `cf340a409611` |
| koboldcpp | llama3-70b | math | 9 | 0 | 6/9 | unavailable | 0.9529 | 2.102 | `cf340a409611` |
| koboldcpp | llama3-70b | reasoning | 9 | 0 | 3/9 | unavailable | 1.339 | 2.241 | `cf340a409611` |
| ollama | llama3-70b | coding | 9 | 0 | 6/9 | unavailable | 2.271 | 2.635 | `a40c31013f27` |
| ollama | llama3-70b | math | 9 | 0 | 6/9 | unavailable | 0.7661 | 2.628 | `a40c31013f27` |
| ollama | llama3-70b | reasoning | 9 | 0 | 3/9 | unavailable | 1.14 | 2.626 | `a40c31013f27` |

![Request latency](../../../../diagrams/results/model-offloading/campaign-20261117T213717Z-0797f5e5-offload-model-offloading-1/latency.png)

## Interpretation and reproduction

Warmups and superseded attempts remain in raw data and are excluded from summaries. Each job/category is a separate cohort. Missing values remain unknown. Replay cost and generation latency are estimates; an offline oracle is an upper bound. LiveBench upstream grades are exported separately as judgment and benchmark summary records, not relabeled as local smoke scores.

Use the measured code revision and resolved configuration to reconstruct the campaign with your local artifact paths and credential references. Verify the recorded input hashes. Run `llm-eval plan --campaign YOUR_CAMPAIGN.json` before `llm-eval run --campaign YOUR_CAMPAIGN.json`. Synthetic results do not establish model quality or hardware performance.
