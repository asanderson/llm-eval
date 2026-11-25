# hardware-fit results

Status: **complete**. Synthetic fixtures: **false**.

Campaign: `fit-wsl-us-lmstudio`. Experiment run: `fit-hardware-fit-1`. Measured code: `ce08c168fac5bbd7eff09b8356c036c35e7ce106`.

[Raw measurements](raw/measurements.jsonl.gz) · [JSON summary](summary.json) · [CSV summary](summary.csv) · [Manifest](manifest.json) · [Resolved configuration](resolved-config.json)

## Configuration coverage

| Case | Hardware | OS | Harness | Model | Status |
|---|---|---|---|---|---|
| inkling2-mini-26b-iq4_nl-lmstudio | raider-wsl | windows-11-wsl2-ubuntu-26.04 | lmstudio | inkling2-mini-26b-iq4_nl | succeeded |
| muse-glimmer-30b-kquant-17gb-q4_k_m-lmstudio | raider-wsl | windows-11-wsl2-ubuntu-26.04 | lmstudio | muse-glimmer-30b-kquant-17gb-q4_k_m | succeeded |

## Measurements by harness and model

| Harness | Model | Category | Requests | Errors or missing | Quality passes | Decision accuracy | Median seconds | Output tokens/s | Job |
|---|---|---|---:|---:|---:|---:|---:|---:|---|
| lmstudio | inkling2-mini-26b-iq4_nl | coding | 9 | 0 | 9/9 | unavailable | 1.75 | 54.28 | `971aedbccee6` |
| lmstudio | inkling2-mini-26b-iq4_nl | math | 9 | 0 | 9/9 | unavailable | 1.459 | 53.46 | `971aedbccee6` |
| lmstudio | inkling2-mini-26b-iq4_nl | reasoning | 9 | 0 | 9/9 | unavailable | 2.042 | 55.33 | `971aedbccee6` |
| lmstudio | muse-glimmer-30b-kquant-17gb-q4_k_m | coding | 9 | 0 | 9/9 | unavailable | 4.158 | 35.59 | `54cda96c277e` |
| lmstudio | muse-glimmer-30b-kquant-17gb-q4_k_m | math | 9 | 0 | 9/9 | unavailable | 2.964 | 35.42 | `54cda96c277e` |
| lmstudio | muse-glimmer-30b-kquant-17gb-q4_k_m | reasoning | 9 | 0 | 6/9 | unavailable | 6.843 | 35.73 | `54cda96c277e` |

![Request latency](../../../../diagrams/results/hardware-fit/campaign-20261124T232244Z-86c68e03-fit-hardware-fit-1/latency.png)

## Interpretation and reproduction

Warmups and superseded attempts remain in raw data and are excluded from summaries. Each job/category is a separate cohort. Missing values remain unknown. Replay cost and generation latency are estimates; an offline oracle is an upper bound. LiveBench upstream grades are exported separately as judgment and benchmark summary records, not relabeled as local smoke scores.

Use the measured code revision and resolved configuration to reconstruct the campaign with your local artifact paths and credential references. Verify the recorded input hashes. Run `llm-eval plan --campaign YOUR_CAMPAIGN.json` before `llm-eval run --campaign YOUR_CAMPAIGN.json`. Synthetic results do not establish model quality or hardware performance.
