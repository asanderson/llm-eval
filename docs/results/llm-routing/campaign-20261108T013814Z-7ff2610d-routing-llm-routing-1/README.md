# llm-routing results

Status: **complete**. Synthetic fixtures: **true**.

Campaign: `routing-smoke`. Experiment run: `routing-llm-routing-1`. Measured code: `3fc8f649b2d5756dc3db2dcaa6142f40e719512b`.

[Raw measurements](raw/measurements.jsonl.gz) · [JSON summary](summary.json) · [CSV summary](summary.csv) · [Manifest](manifest.json) · [Resolved configuration](resolved-config.json)

## Configuration coverage

| Case | Hardware | OS | Harness | Model | Status |
|---|---|---|---|---|---|
| category-smoke | raider-ubuntu | ubuntu-26.04-native | category | category | succeeded |

## Measurements by harness and model

| Harness | Model | Category | Requests | Errors or missing | Quality passes | Decision accuracy | Median seconds | Output tokens/s | Job |
|---|---|---|---:|---:|---:|---:|---:|---:|---|
| category | category | coding | 1 | 0 | unavailable | 1 | 4.97e-05 | unavailable | `290257f5d5ab` |
| category | category | math | 1 | 0 | unavailable | 1 | 1.81e-05 | unavailable | `290257f5d5ab` |

![Request latency](../../../../diagrams/results/llm-routing/campaign-20261108T013814Z-7ff2610d-routing-llm-routing-1/latency.png)

## Interpretation and reproduction

Warmups and superseded attempts remain in raw data and are excluded from summaries. Each job/category is a separate cohort. Missing values remain unknown. Replay cost and generation latency are estimates; an offline oracle is an upper bound. LiveBench upstream grades are exported separately as judgment and benchmark summary records, not relabeled as local smoke scores.

Use the measured code revision and resolved configuration to reconstruct the campaign with your local artifact paths and credential references. Verify the recorded input hashes. Run `llm-eval plan --campaign YOUR_CAMPAIGN.json` before `llm-eval run --campaign YOUR_CAMPAIGN.json`. Synthetic results do not establish model quality or hardware performance.
