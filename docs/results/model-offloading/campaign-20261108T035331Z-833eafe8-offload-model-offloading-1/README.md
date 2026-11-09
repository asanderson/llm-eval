# model-offloading results

Status: **incomplete**. Synthetic fixtures: **false**.

Campaign: `raider-windows-combined`. Experiment run: `offload-model-offloading-1`. Measured code: `3fc8f649b2d5756dc3db2dcaa6142f40e719512b`.

[Raw measurements](raw/measurements.jsonl.gz) · [JSON summary](summary.json) · [CSV summary](summary.csv) · [Manifest](manifest.json) · [Resolved configuration](resolved-config.json)

## Configuration coverage

| Case | Hardware | OS | Harness | Model | Status |
|---|---|---|---|---|---|
| deepseek-r1-32b-q8 | raider-windows | windows-11-native | ollama | deepseek-r1-32b | failed |

## Measurements by harness and model

| Harness | Model | Category | Requests | Errors or missing | Quality passes | Decision accuracy | Median seconds | Output tokens/s | Job |
|---|---|---|---:|---:|---:|---:|---:|---:|---|
| ollama | deepseek-r1-32b | coding | 9 | 9 | 0/9 | unavailable | unavailable | unavailable | `db17c5930ec0` |
| ollama | deepseek-r1-32b | math | 9 | 9 | 0/9 | unavailable | unavailable | unavailable | `db17c5930ec0` |
| ollama | deepseek-r1-32b | reasoning | 9 | 9 | 0/9 | unavailable | unavailable | unavailable | `db17c5930ec0` |

![Request latency](../../../../diagrams/results/model-offloading/campaign-20261108T035331Z-833eafe8-offload-model-offloading-1/latency.png)

## Interpretation and reproduction

Warmups and superseded attempts remain in raw data and are excluded from summaries. Each job/category is a separate cohort. Missing values remain unknown. Replay cost and generation latency are estimates; an offline oracle is an upper bound. LiveBench upstream grades are exported separately as judgment and benchmark summary records, not relabeled as local smoke scores.

Use the measured code revision and resolved configuration to reconstruct the campaign with your local artifact paths and credential references. Verify the recorded input hashes. Run `llm-eval plan --campaign YOUR_CAMPAIGN.json` before `llm-eval run --campaign YOUR_CAMPAIGN.json`. Synthetic results do not establish model quality or hardware performance.
