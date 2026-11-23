# hardware-fit results

Status: **complete**. Synthetic fixtures: **false**.

Campaign: `fit-wsl-measured2-qwen38-27b-ud-q4_k_xl`. Experiment run: `fit-hardware-fit-1`. Measured code: `2695cba457664b269921edfcf5afa430e2222330`.

[Raw measurements](raw/measurements.jsonl.gz) · [JSON summary](summary.json) · [CSV summary](summary.csv) · [Manifest](manifest.json) · [Resolved configuration](resolved-config.json)

## Configuration coverage

| Case | Hardware | OS | Harness | Model | Status |
|---|---|---|---|---|---|
| qwen38-27b-ud-q4_k_xl-lmstudio | raider-wsl | windows-11-wsl2-ubuntu-26.04 | lmstudio | qwen38-27b-ud-q4_k_xl | succeeded |
| qwen38-27b-ud-q4_k_xl-ollama | raider-wsl | windows-11-wsl2-ubuntu-26.04 | ollama | qwen38-27b-ud-q4_k_xl | succeeded |

## Measurements by harness and model

| Harness | Model | Category | Requests | Errors or missing | Quality passes | Decision accuracy | Median seconds | Output tokens/s | Job |
|---|---|---|---:|---:|---:|---:|---:|---:|---|
| lmstudio | qwen38-27b-ud-q4_k_xl | coding | 9 | 0 | 9/9 | unavailable | 0.7535 | 61.56 | `4b1c74ff0cbf` |
| lmstudio | qwen38-27b-ud-q4_k_xl | math | 9 | 0 | 9/9 | unavailable | 0.9677 | 69.07 | `4b1c74ff0cbf` |
| lmstudio | qwen38-27b-ud-q4_k_xl | reasoning | 9 | 0 | 6/9 | unavailable | 0.8864 | 68.59 | `4b1c74ff0cbf` |
| ollama | qwen38-27b-ud-q4_k_xl | coding | 9 | 0 | 9/9 | unavailable | 1.985 | 33.74 | `aca7cd52ca80` |
| ollama | qwen38-27b-ud-q4_k_xl | math | 9 | 0 | 9/9 | unavailable | 1.968 | 33.62 | `aca7cd52ca80` |
| ollama | qwen38-27b-ud-q4_k_xl | reasoning | 9 | 0 | 6/9 | unavailable | 1.428 | 32.9 | `aca7cd52ca80` |

![Request latency](../../../../diagrams/results/hardware-fit/campaign-20261123T120632Z-53d7833d-fit-hardware-fit-1/latency.png)

## Interpretation and reproduction

Warmups and superseded attempts remain in raw data and are excluded from summaries. Each job/category is a separate cohort. Missing values remain unknown. Replay cost and generation latency are estimates; an offline oracle is an upper bound. LiveBench upstream grades are exported separately as judgment and benchmark summary records, not relabeled as local smoke scores.

Use the measured code revision and resolved configuration to reconstruct the campaign with your local artifact paths and credential references. Verify the recorded input hashes. Run `llm-eval plan --campaign YOUR_CAMPAIGN.json` before `llm-eval run --campaign YOUR_CAMPAIGN.json`. Synthetic results do not establish model quality or hardware performance.
