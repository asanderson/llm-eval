# llm-routing results

Status: **complete**. Synthetic fixtures: **false**.

Campaign: `raider-wsl-routing-rerun`. Experiment run: `routing-llm-routing-1`. Measured code: `7e4606827cde8d9af4ccbb0c2ec8473d8d8049ce`.

[Raw measurements](raw/measurements.jsonl.gz) · [JSON summary](summary.json) · [CSV summary](summary.csv) · [Manifest](manifest.json) · [Resolved configuration](resolved-config.json)

## Configuration coverage

| Case | Hardware | OS | Harness | Model | Status |
|---|---|---|---|---|---|
| ollama-nimble | raider-wsl | windows-11-wsl2-ubuntu-26.04 | ollama | llm-eval-nimble:locked | succeeded |
| ollama-tev1 | raider-wsl | windows-11-wsl2-ubuntu-26.04 | ollama | llm-eval-tev1:locked | succeeded |

## Measurements by harness and model

| Harness | Model | Category | Requests | Errors or missing | Quality passes | Decision accuracy | Median seconds | Output tokens/s | Job |
|---|---|---|---:|---:|---:|---:|---:|---:|---|
| ollama | llm-eval-nimble:locked | coding | 3 | 0 | unavailable | 1 | 0.05543 | unavailable | `ac901abb4fcd` |
| ollama | llm-eval-nimble:locked | math | 3 | 0 | unavailable | 1 | 0.05068 | unavailable | `ac901abb4fcd` |
| ollama | llm-eval-tev1:locked | coding | 3 | 0 | unavailable | 1 | 0.02609 | unavailable | `c6e41214da48` |
| ollama | llm-eval-tev1:locked | math | 3 | 0 | unavailable | 1 | 0.02448 | unavailable | `c6e41214da48` |

![Request latency](../../../../diagrams/results/llm-routing/campaign-20261118T051019Z-d72bad77-routing-llm-routing-1/latency.png)

## Interpretation and reproduction

Warmups and superseded attempts remain in raw data and are excluded from summaries. Each job/category is a separate cohort. Missing values remain unknown. Replay cost and generation latency are estimates; an offline oracle is an upper bound. LiveBench upstream grades are exported separately as judgment and benchmark summary records, not relabeled as local smoke scores.

Use the measured code revision and resolved configuration to reconstruct the campaign with your local artifact paths and credential references. Verify the recorded input hashes. Run `llm-eval plan --campaign YOUR_CAMPAIGN.json` before `llm-eval run --campaign YOUR_CAMPAIGN.json`. Synthetic results do not establish model quality or hardware performance.
