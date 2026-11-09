# model-offloading results

Status: **complete**. Synthetic fixtures: **false**.

Campaign: `matrix-gemma4-31b`. Experiment run: `offload-model-offloading-1`. Measured code: `0d1144c391964a75dac4353d3525ec8a84c994de`.

[Raw measurements](raw/measurements.jsonl.gz) · [JSON summary](summary.json) · [CSV summary](summary.csv) · [Manifest](manifest.json) · [Resolved configuration](resolved-config.json)

## Configuration coverage

| Case | Hardware | OS | Harness | Model | Status |
|---|---|---|---|---|---|
| gemma4-31b-ollama | raider-windows | windows-11-native | ollama | gemma4-31b | succeeded |

## Measurements by harness and model

| Harness | Model | Category | Requests | Errors or missing | Quality passes | Decision accuracy | Median seconds | Output tokens/s | Job |
|---|---|---|---:|---:|---:|---:|---:|---:|---|
| ollama | gemma4-31b | coding | 9 | 0 | 9/9 | unavailable | 53.89 | 3.296 | `19937807a7ec` |
| ollama | gemma4-31b | math | 9 | 0 | 9/9 | unavailable | 39.8 | 3.292 | `19937807a7ec` |
| ollama | gemma4-31b | reasoning | 9 | 0 | 6/9 | unavailable | 48.24 | 3.294 | `19937807a7ec` |

![Request latency](../../../../diagrams/results/model-offloading/campaign-20261109T180247Z-c38f462b-offload-model-offloading-1/latency.png)

## Interpretation and reproduction

Warmups and superseded attempts remain in raw data and are excluded from summaries. Each job/category is a separate cohort. Missing values remain unknown. Replay cost and generation latency are estimates; an offline oracle is an upper bound. LiveBench upstream grades are exported separately as judgment and benchmark summary records, not relabeled as local smoke scores.

Use the measured code revision and resolved configuration to reconstruct the campaign with your local artifact paths and credential references. Verify the recorded input hashes. Run `llm-eval plan --campaign YOUR_CAMPAIGN.json` before `llm-eval run --campaign YOUR_CAMPAIGN.json`. Synthetic results do not establish model quality or hardware performance.
