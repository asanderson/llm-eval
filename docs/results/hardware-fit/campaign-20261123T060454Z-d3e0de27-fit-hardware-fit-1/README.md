# hardware-fit results

Status: **complete**. Synthetic fixtures: **false**.

Campaign: `fit-wsl-measured-qwen38-27b-ud-q4_k_xl`. Experiment run: `fit-hardware-fit-1`. Measured code: `2695cba457664b269921edfcf5afa430e2222330`.

[Raw measurements](raw/measurements.jsonl.gz) · [JSON summary](summary.json) · [CSV summary](summary.csv) · [Manifest](manifest.json) · [Resolved configuration](resolved-config.json)

## Configuration coverage

| Case | Hardware | OS | Harness | Model | Status |
|---|---|---|---|---|---|
| qwen38-27b-ud-q4_k_xl-koboldcpp | raider-wsl | windows-11-wsl2-ubuntu-26.04 | koboldcpp | qwen38-27b-ud-q4_k_xl | succeeded |

## Measurements by harness and model

| Harness | Model | Category | Requests | Errors or missing | Quality passes | Decision accuracy | Median seconds | Output tokens/s | Job |
|---|---|---|---:|---:|---:|---:|---:|---:|---|
| koboldcpp | qwen38-27b-ud-q4_k_xl | coding | 9 | 0 | 9/9 | unavailable | 2.579 | 26.92 | `1479e5e031a5` |
| koboldcpp | qwen38-27b-ud-q4_k_xl | math | 9 | 0 | 9/9 | unavailable | 2.776 | 27.17 | `1479e5e031a5` |
| koboldcpp | qwen38-27b-ud-q4_k_xl | reasoning | 9 | 0 | 6/9 | unavailable | 3.066 | 27.37 | `1479e5e031a5` |

![Request latency](../../../../diagrams/results/hardware-fit/campaign-20261123T060454Z-d3e0de27-fit-hardware-fit-1/latency.png)

## Interpretation and reproduction

Warmups and superseded attempts remain in raw data and are excluded from summaries. Each job/category is a separate cohort. Missing values remain unknown. Replay cost and generation latency are estimates; an offline oracle is an upper bound. LiveBench upstream grades are exported separately as judgment and benchmark summary records, not relabeled as local smoke scores.

Use the measured code revision and resolved configuration to reconstruct the campaign with your local artifact paths and credential references. Verify the recorded input hashes. Run `llm-eval plan --campaign YOUR_CAMPAIGN.json` before `llm-eval run --campaign YOUR_CAMPAIGN.json`. Synthetic results do not establish model quality or hardware performance.
