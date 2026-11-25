# decision-models results

Status: **complete**. Synthetic fixtures: **false**.

Campaign: `raider-wsl-decision-models-2026-11-24`. Experiment run: `routing-decision-models-1`. Measured code: `ce08c168fac5bbd7eff09b8356c036c35e7ce106`.

[Raw measurements](raw/measurements.jsonl.gz) · [JSON summary](summary.json) · [CSV summary](summary.csv) · [Manifest](manifest.json) · [Resolved configuration](resolved-config.json)

## Configuration coverage

| Case | Hardware | OS | Harness | Model | Status |
|---|---|---|---|---|---|
| ollama-clef-flash | raider-wsl | windows-11-wsl2-ubuntu-26.04 | ollama | llm-eval-clef-flash:locked | succeeded |
| ollama-clef | raider-wsl | windows-11-wsl2-ubuntu-26.04 | ollama | llm-eval-clef:locked | succeeded |
| ollama-d1-omni | raider-wsl | windows-11-wsl2-ubuntu-26.04 | ollama | llm-eval-d1-omni:locked | succeeded |
| ollama-d1 | raider-wsl | windows-11-wsl2-ubuntu-26.04 | ollama | llm-eval-d1:locked | succeeded |
| ollama-laya | raider-wsl | windows-11-wsl2-ubuntu-26.04 | ollama | llm-eval-laya:locked | succeeded |
| ollama-nimble-v3 | raider-wsl | windows-11-wsl2-ubuntu-26.04 | ollama | llm-eval-nimble-v3:locked | succeeded |
| ollama-nimble | raider-wsl | windows-11-wsl2-ubuntu-26.04 | ollama | llm-eval-nimble:locked | succeeded |
| ollama-pplx-decider | raider-wsl | windows-11-wsl2-ubuntu-26.04 | ollama | llm-eval-pplx-decider:locked | succeeded |
| ollama-tev1-0.8b | raider-wsl | windows-11-wsl2-ubuntu-26.04 | ollama | llm-eval-tev1-0.8b:locked | succeeded |
| ollama-tev1 | raider-wsl | windows-11-wsl2-ubuntu-26.04 | ollama | llm-eval-tev1:locked | succeeded |

## Measurements by harness and model

| Harness | Model | Category | Requests | Errors or missing | Quality passes | Decision accuracy | Median seconds | Output tokens/s | Job |
|---|---|---|---:|---:|---:|---:|---:|---:|---|
| ollama | llm-eval-clef-flash:locked | coding | 3 | 0 | unavailable | 1 | 0.05568 | unavailable | `0701e943af0c` |
| ollama | llm-eval-clef-flash:locked | math | 3 | 0 | unavailable | 1 | 0.05416 | unavailable | `0701e943af0c` |
| ollama | llm-eval-clef:locked | coding | 3 | 0 | unavailable | 1 | 0.5036 | unavailable | `cff82f501cf5` |
| ollama | llm-eval-clef:locked | math | 3 | 0 | unavailable | 1 | 0.5659 | unavailable | `cff82f501cf5` |
| ollama | llm-eval-d1-omni:locked | coding | 3 | 0 | unavailable | 1 | 0.03978 | unavailable | `473146c3e729` |
| ollama | llm-eval-d1-omni:locked | math | 3 | 0 | unavailable | 1 | 0.03448 | unavailable | `473146c3e729` |
| ollama | llm-eval-d1:locked | coding | 3 | 0 | unavailable | 1 | 0.01916 | unavailable | `b72471bb152f` |
| ollama | llm-eval-d1:locked | math | 3 | 0 | unavailable | 1 | 0.01399 | unavailable | `b72471bb152f` |
| ollama | llm-eval-laya:locked | coding | 3 | 0 | unavailable | 1 | 0.01451 | unavailable | `8f34219dcce9` |
| ollama | llm-eval-laya:locked | math | 3 | 0 | unavailable | 1 | 0.01382 | unavailable | `8f34219dcce9` |
| ollama | llm-eval-nimble-v3:locked | coding | 3 | 0 | unavailable | 1 | 0.05496 | unavailable | `2cfe79fef460` |
| ollama | llm-eval-nimble-v3:locked | math | 3 | 0 | unavailable | 1 | 0.05515 | unavailable | `2cfe79fef460` |
| ollama | llm-eval-nimble:locked | coding | 3 | 0 | unavailable | 1 | 0.05269 | unavailable | `ac901abb4fcd` |
| ollama | llm-eval-nimble:locked | math | 3 | 0 | unavailable | 1 | 0.0444 | unavailable | `ac901abb4fcd` |
| ollama | llm-eval-pplx-decider:locked | coding | 3 | 0 | unavailable | 1 | 0.08961 | unavailable | `efcc2160debc` |
| ollama | llm-eval-pplx-decider:locked | math | 3 | 0 | unavailable | 1 | 0.1067 | unavailable | `efcc2160debc` |
| ollama | llm-eval-tev1-0.8b:locked | coding | 3 | 0 | unavailable | 1 | 0.02339 | unavailable | `49a41a2986fd` |
| ollama | llm-eval-tev1-0.8b:locked | math | 3 | 0 | unavailable | 1 | 0.01296 | unavailable | `49a41a2986fd` |
| ollama | llm-eval-tev1:locked | coding | 3 | 0 | unavailable | 1 | 0.02807 | unavailable | `c6e41214da48` |
| ollama | llm-eval-tev1:locked | math | 3 | 0 | unavailable | 1 | 0.02651 | unavailable | `c6e41214da48` |

![Request latency](../../../../diagrams/results/decision-models/campaign-20261124T224117Z-ce08f5a6-routing-decision-models-1/latency.png)

## Interpretation and reproduction

Warmups and superseded attempts remain in raw data and are excluded from summaries. Each job/category is a separate cohort. Missing values remain unknown. Replay cost and generation latency are estimates; an offline oracle is an upper bound. LiveBench upstream grades are exported separately as judgment and benchmark summary records, not relabeled as local smoke scores.

Use the measured code revision and resolved configuration to reconstruct the campaign with your local artifact paths and credential references. Verify the recorded input hashes. Run `llm-eval plan --campaign YOUR_CAMPAIGN.json` before `llm-eval run --campaign YOUR_CAMPAIGN.json`. Synthetic results do not establish model quality or hardware performance.
