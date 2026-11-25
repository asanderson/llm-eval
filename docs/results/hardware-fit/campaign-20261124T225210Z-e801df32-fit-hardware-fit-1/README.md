# hardware-fit results

Status: **complete**. Synthetic fixtures: **false**.

Campaign: `fit-wsl-us-koboldcpp`. Experiment run: `fit-hardware-fit-1`. Measured code: `ce08c168fac5bbd7eff09b8356c036c35e7ce106`.

[Raw measurements](raw/measurements.jsonl.gz) · [JSON summary](summary.json) · [CSV summary](summary.csv) · [Manifest](manifest.json) · [Resolved configuration](resolved-config.json)

## Configuration coverage

| Case | Hardware | OS | Harness | Model | Status |
|---|---|---|---|---|---|
| inkling2-mini-26b-iq4_nl-koboldcpp | raider-wsl | windows-11-wsl2-ubuntu-26.04 | koboldcpp | inkling2-mini-26b-iq4_nl | succeeded |
| muse-glimmer-30b-kquant-17gb-q4_k_m-koboldcpp | raider-wsl | windows-11-wsl2-ubuntu-26.04 | koboldcpp | muse-glimmer-30b-kquant-17gb-q4_k_m | succeeded |
| qwen38-27b-ud-q4_k_xl-koboldcpp | raider-wsl | windows-11-wsl2-ubuntu-26.04 | koboldcpp | qwen38-27b-ud-q4_k_xl | succeeded |

## Measurements by harness and model

| Harness | Model | Category | Requests | Errors or missing | Quality passes | Decision accuracy | Median seconds | Output tokens/s | Job |
|---|---|---|---:|---:|---:|---:|---:|---:|---|
| koboldcpp | inkling2-mini-26b-iq4_nl | coding | 9 | 0 | 9/9 | unavailable | 6.662 | 12.79 | `681665f3272a` |
| koboldcpp | inkling2-mini-26b-iq4_nl | math | 9 | 0 | 9/9 | unavailable | 5.218 | 13 | `681665f3272a` |
| koboldcpp | inkling2-mini-26b-iq4_nl | reasoning | 9 | 0 | 9/9 | unavailable | 11.75 | 12.8 | `681665f3272a` |
| koboldcpp | muse-glimmer-30b-kquant-17gb-q4_k_m | coding | 9 | 0 | 9/9 | unavailable | 0.5241 | 3.816 | `2672aee4239f` |
| koboldcpp | muse-glimmer-30b-kquant-17gb-q4_k_m | math | 9 | 0 | 6/9 | unavailable | 0.525 | 3.81 | `2672aee4239f` |
| koboldcpp | muse-glimmer-30b-kquant-17gb-q4_k_m | reasoning | 9 | 0 | 3/9 | unavailable | 0.5241 | 3.82 | `2672aee4239f` |
| koboldcpp | qwen38-27b-ud-q4_k_xl | coding | 9 | 0 | 9/9 | unavailable | 3.723 | 27.66 | `1479e5e031a5` |
| koboldcpp | qwen38-27b-ud-q4_k_xl | math | 9 | 0 | 9/9 | unavailable | 2.762 | 26.96 | `1479e5e031a5` |
| koboldcpp | qwen38-27b-ud-q4_k_xl | reasoning | 9 | 0 | 6/9 | unavailable | 3.044 | 26.95 | `1479e5e031a5` |

![Request latency](../../../../diagrams/results/hardware-fit/campaign-20261124T225210Z-e801df32-fit-hardware-fit-1/latency.png)

## Interpretation and reproduction

Warmups and superseded attempts remain in raw data and are excluded from summaries. Each job/category is a separate cohort. Missing values remain unknown. Replay cost and generation latency are estimates; an offline oracle is an upper bound. LiveBench upstream grades are exported separately as judgment and benchmark summary records, not relabeled as local smoke scores.

Use the measured code revision and resolved configuration to reconstruct the campaign with your local artifact paths and credential references. Verify the recorded input hashes. Run `llm-eval plan --campaign YOUR_CAMPAIGN.json` before `llm-eval run --campaign YOUR_CAMPAIGN.json`. Synthetic results do not establish model quality or hardware performance.
