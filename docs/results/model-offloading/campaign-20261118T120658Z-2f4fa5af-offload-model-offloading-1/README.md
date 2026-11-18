# model-offloading results

Status: **complete**. Synthetic fixtures: **false**.

Campaign: `matrix-wsl-gemma4-26b-moe`. Experiment run: `offload-model-offloading-1`. Measured code: `61d1f30848bbaded8f120951dcbcb5810ec09b49`.

[Raw measurements](raw/measurements.jsonl.gz) · [JSON summary](summary.json) · [CSV summary](summary.csv) · [Manifest](manifest.json) · [Resolved configuration](resolved-config.json)

## Configuration coverage

| Case | Hardware | OS | Harness | Model | Status |
|---|---|---|---|---|---|
| gemma4-26b-moe-ollama | raider-wsl | windows-11-wsl2-ubuntu-26.04 | ollama | gemma4-26b-moe | succeeded |

## Measurements by harness and model

| Harness | Model | Category | Requests | Errors or missing | Quality passes | Decision accuracy | Median seconds | Output tokens/s | Job |
|---|---|---|---:|---:|---:|---:|---:|---:|---|
| ollama | gemma4-26b-moe | coding | 9 | 0 | 9/9 | unavailable | 14.85 | 15.87 | `a5de5a44d6b9` |
| ollama | gemma4-26b-moe | math | 9 | 0 | 9/9 | unavailable | 11.83 | 15.89 | `a5de5a44d6b9` |
| ollama | gemma4-26b-moe | reasoning | 9 | 0 | 6/9 | unavailable | 12.6 | 15.87 | `a5de5a44d6b9` |

![Request latency](../../../../diagrams/results/model-offloading/campaign-20261118T120658Z-2f4fa5af-offload-model-offloading-1/latency.png)

## Interpretation and reproduction

Warmups and superseded attempts remain in raw data and are excluded from summaries. Each job/category is a separate cohort. Missing values remain unknown. Replay cost and generation latency are estimates; an offline oracle is an upper bound. LiveBench upstream grades are exported separately as judgment and benchmark summary records, not relabeled as local smoke scores.

Use the measured code revision and resolved configuration to reconstruct the campaign with your local artifact paths and credential references. Verify the recorded input hashes. Run `llm-eval plan --campaign YOUR_CAMPAIGN.json` before `llm-eval run --campaign YOUR_CAMPAIGN.json`. Synthetic results do not establish model quality or hardware performance.
