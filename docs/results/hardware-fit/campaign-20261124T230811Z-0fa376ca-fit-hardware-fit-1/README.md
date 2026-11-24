# hardware-fit results

Status: **incomplete**. Synthetic fixtures: **false**.

Campaign: `fit-wsl-us-ollama`. Experiment run: `fit-hardware-fit-1`. Measured code: `ce08c168fac5bbd7eff09b8356c036c35e7ce106`.

[Raw measurements](raw/measurements.jsonl.gz) · [JSON summary](summary.json) · [CSV summary](summary.csv) · [Manifest](manifest.json) · [Resolved configuration](resolved-config.json)

## Configuration coverage

| Case | Hardware | OS | Harness | Model | Status |
|---|---|---|---|---|---|
| inkling2-mini-26b-iq4_nl-ollama | raider-wsl | windows-11-wsl2-ubuntu-26.04 | ollama | inkling2-mini-26b-iq4_nl | failed |
| muse-glimmer-30b-kquant-17gb-q4_k_m-ollama | raider-wsl | windows-11-wsl2-ubuntu-26.04 | ollama | muse-glimmer-30b-kquant-17gb-q4_k_m | succeeded |
| qwen38-27b-ud-q4_k_xl-ollama | raider-wsl | windows-11-wsl2-ubuntu-26.04 | ollama | qwen38-27b-ud-q4_k_xl | succeeded |

## Measurements by harness and model

| Harness | Model | Category | Requests | Errors or missing | Quality passes | Decision accuracy | Median seconds | Output tokens/s | Job |
|---|---|---|---:|---:|---:|---:|---:|---:|---|
| ollama | inkling2-mini-26b-iq4_nl | coding | 9 | 9 | 0/9 | unavailable | unavailable | unavailable | `9aa57a544a52` |
| ollama | inkling2-mini-26b-iq4_nl | math | 9 | 9 | 0/9 | unavailable | unavailable | unavailable | `9aa57a544a52` |
| ollama | inkling2-mini-26b-iq4_nl | reasoning | 9 | 9 | 0/9 | unavailable | unavailable | unavailable | `9aa57a544a52` |
| ollama | muse-glimmer-30b-kquant-17gb-q4_k_m | coding | 9 | 0 | 9/9 | unavailable | 4.073 | 37.07 | `82d35f1d737c` |
| ollama | muse-glimmer-30b-kquant-17gb-q4_k_m | math | 9 | 0 | 9/9 | unavailable | 2.779 | 36.64 | `82d35f1d737c` |
| ollama | muse-glimmer-30b-kquant-17gb-q4_k_m | reasoning | 9 | 0 | 6/9 | unavailable | 5.186 | 37.14 | `82d35f1d737c` |
| ollama | qwen38-27b-ud-q4_k_xl | coding | 9 | 0 | 9/9 | unavailable | 1.981 | 33.71 | `aca7cd52ca80` |
| ollama | qwen38-27b-ud-q4_k_xl | math | 9 | 0 | 9/9 | unavailable | 1.97 | 33.67 | `aca7cd52ca80` |
| ollama | qwen38-27b-ud-q4_k_xl | reasoning | 9 | 0 | 6/9 | unavailable | 1.411 | 33.06 | `aca7cd52ca80` |

![Request latency](../../../../diagrams/results/hardware-fit/campaign-20261124T230811Z-0fa376ca-fit-hardware-fit-1/latency.png)

## Interpretation and reproduction

Warmups and superseded attempts remain in raw data and are excluded from summaries. Each job/category is a separate cohort. Missing values remain unknown. Replay cost and generation latency are estimates; an offline oracle is an upper bound. LiveBench upstream grades are exported separately as judgment and benchmark summary records, not relabeled as local smoke scores.

Use the measured code revision and resolved configuration to reconstruct the campaign with your local artifact paths and credential references. Verify the recorded input hashes. Run `llm-eval plan --campaign YOUR_CAMPAIGN.json` before `llm-eval run --campaign YOUR_CAMPAIGN.json`. Synthetic results do not establish model quality or hardware performance.
