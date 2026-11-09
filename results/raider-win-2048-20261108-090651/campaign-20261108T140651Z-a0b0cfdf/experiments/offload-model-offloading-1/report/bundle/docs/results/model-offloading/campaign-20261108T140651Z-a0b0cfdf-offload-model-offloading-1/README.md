# model-offloading results

Status: **complete**. Synthetic fixtures: **false**.

Campaign: `raider-windows-offload-2048`. Experiment run: `offload-model-offloading-1`. Measured code: `3fc8f649b2d5756dc3db2dcaa6142f40e719512b`.

[Raw measurements](raw/measurements.jsonl.gz) · [JSON summary](summary.json) · [CSV summary](summary.csv) · [Manifest](manifest.json) · [Resolved configuration](resolved-config.json)

## Configuration coverage

| Case | Hardware | OS | Platform or router | Status |
|---|---|---|---|---|
| deepseek-r1-32b-q8 | raider-windows | windows-11-native | ollama | succeeded |

## Measurements

| Job | Category | Requests | Errors or missing | Decision accuracy | Median seconds |
|---|---|---:|---:|---:|---:|
| offload-model-offloading-1-db17c5930ec0 | coding | 9 | 0 | unavailable | 119.8 |
| offload-model-offloading-1-db17c5930ec0 | math | 9 | 0 | unavailable | 70.28 |
| offload-model-offloading-1-db17c5930ec0 | reasoning | 9 | 0 | unavailable | 88.09 |

![Request latency](../../../../diagrams/results/model-offloading/campaign-20261108T140651Z-a0b0cfdf-offload-model-offloading-1/latency.png)

## Interpretation and reproduction

Warmups and superseded attempts remain in raw data and are excluded from summaries. Each job/category is a separate cohort. Missing values remain unknown. Replay cost and generation latency are estimates; an offline oracle is an upper bound. LiveBench upstream grades are exported separately as judgment and benchmark summary records, not relabeled as local smoke scores.

Use the measured code revision and resolved configuration to reconstruct the campaign with your local artifact paths and credential references. Verify the recorded input hashes. Run `llm-eval plan --campaign YOUR_CAMPAIGN.json` before `llm-eval run --campaign YOUR_CAMPAIGN.json`. Synthetic results do not establish model quality or hardware performance.
