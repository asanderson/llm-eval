# llm-routing results

Status: **complete**. Synthetic fixtures: **false**.

Campaign: `raider-windows-combined`. Experiment run: `routing-llm-routing-1`. Measured code: `3fc8f649b2d5756dc3db2dcaa6142f40e719512b`.

[Raw measurements](raw/measurements.jsonl.gz) · [JSON summary](summary.json) · [CSV summary](summary.csv) · [Manifest](manifest.json) · [Resolved configuration](resolved-config.json)

## Configuration coverage

| Case | Hardware | OS | Platform or router | Status |
|---|---|---|---|---|
| ollama-nimble | raider-windows | windows-11-native | llm-eval-nimble:locked | succeeded |
| ollama-tev1 | raider-windows | windows-11-native | llm-eval-tev1:locked | succeeded |

## Measurements

| Job | Category | Requests | Errors or missing | Decision accuracy | Median seconds |
|---|---|---:|---:|---:|---:|
| routing-llm-routing-1-25eff864a7d1 | coding | 3 | 0 | 1 | 0.02739 |
| routing-llm-routing-1-25eff864a7d1 | math | 3 | 0 | 1 | 0.02906 |
| routing-llm-routing-1-389a241fd7b8 | coding | 3 | 0 | 1 | 0.04955 |
| routing-llm-routing-1-389a241fd7b8 | math | 3 | 0 | 1 | 0.04965 |

![Request latency](../../../../diagrams/results/llm-routing/campaign-20261108T035738Z-332b0246-routing-llm-routing-1/latency.png)

## Interpretation and reproduction

Warmups and superseded attempts remain in raw data and are excluded from summaries. Each job/category is a separate cohort. Missing values remain unknown. Replay cost and generation latency are estimates; an offline oracle is an upper bound. LiveBench upstream grades are exported separately as judgment and benchmark summary records, not relabeled as local smoke scores.

Use the measured code revision and resolved configuration to reconstruct the campaign with your local artifact paths and credential references. Verify the recorded input hashes. Run `llm-eval plan --campaign YOUR_CAMPAIGN.json` before `llm-eval run --campaign YOUR_CAMPAIGN.json`. Synthetic results do not establish model quality or hardware performance.
