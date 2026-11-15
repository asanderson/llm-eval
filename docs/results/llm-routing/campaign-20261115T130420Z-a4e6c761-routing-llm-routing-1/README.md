# llm-routing results

Status: **complete**. Synthetic fixtures: **false**.

Campaign: `raider-windows-routing-rerun`. Experiment run: `routing-llm-routing-1`. Measured code: `e69e23c502609a24da6b89744c32be3ea65f5fbd`.

[Raw measurements](raw/measurements.jsonl.gz) · [JSON summary](summary.json) · [CSV summary](summary.csv) · [Manifest](manifest.json) · [Resolved configuration](resolved-config.json)

## Configuration coverage

| Case | Hardware | OS | Harness | Model | Status |
|---|---|---|---|---|---|
| ollama-nimble | raider-windows | windows-11-native | ollama | llm-eval-nimble:locked | succeeded |
| ollama-tev1 | raider-windows | windows-11-native | ollama | llm-eval-tev1:locked | succeeded |

## Measurements by harness and model

| Harness | Model | Category | Requests | Errors or missing | Quality passes | Decision accuracy | Median seconds | Output tokens/s | Job |
|---|---|---|---:|---:|---:|---:|---:|---:|---|
| ollama | llm-eval-nimble:locked | coding | 3 | 0 | unavailable | 1 | 0.06103 | unavailable | `389a241fd7b8` |
| ollama | llm-eval-nimble:locked | math | 3 | 0 | unavailable | 1 | 0.05944 | unavailable | `389a241fd7b8` |
| ollama | llm-eval-tev1:locked | coding | 3 | 0 | unavailable | 1 | 0.02872 | unavailable | `25eff864a7d1` |
| ollama | llm-eval-tev1:locked | math | 3 | 0 | unavailable | 1 | 0.04462 | unavailable | `25eff864a7d1` |

![Request latency](../../../../diagrams/results/llm-routing/campaign-20261115T130420Z-a4e6c761-routing-llm-routing-1/latency.png)

## Interpretation and reproduction

Warmups and superseded attempts remain in raw data and are excluded from summaries. Each job/category is a separate cohort. Missing values remain unknown. Replay cost and generation latency are estimates; an offline oracle is an upper bound. LiveBench upstream grades are exported separately as judgment and benchmark summary records, not relabeled as local smoke scores.

Use the measured code revision and resolved configuration to reconstruct the campaign with your local artifact paths and credential references. Verify the recorded input hashes. Run `llm-eval plan --campaign YOUR_CAMPAIGN.json` before `llm-eval run --campaign YOUR_CAMPAIGN.json`. Synthetic results do not establish model quality or hardware performance.
