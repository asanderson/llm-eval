# model-offloading results

Status: **complete**. Synthetic fixtures: **false**.

Campaign: `matrix-deepseek-r1-70b`. Experiment run: `offload-model-offloading-1`. Measured code: `4c11da3344793596cf51aa0b4b979c56f35fe36b`.

[Raw measurements](raw/measurements.jsonl.gz) · [JSON summary](summary.json) · [CSV summary](summary.csv) · [Manifest](manifest.json) · [Resolved configuration](resolved-config.json)

## Configuration coverage

| Case | Hardware | OS | Harness | Model | Status |
|---|---|---|---|---|---|
| deepseek-r1-70b-koboldcpp | raider-windows | windows-11-native | koboldcpp | deepseek-r1-70b | succeeded |
| deepseek-r1-70b-lmstudio | raider-windows | windows-11-native | lmstudio | deepseek-r1-70b | succeeded |
| deepseek-r1-70b-ollama | raider-windows | windows-11-native | ollama | deepseek-r1-70b | succeeded |

## Measurements by harness and model

| Harness | Model | Category | Requests | Errors or missing | Quality passes | Decision accuracy | Median seconds | Output tokens/s | Job |
|---|---|---|---:|---:|---:|---:|---:|---:|---|
| koboldcpp | deepseek-r1-70b | coding | 9 | 0 | 3/9 | unavailable | 183.5 | 2.631 | `0bb8048f47a6` |
| koboldcpp | deepseek-r1-70b | math | 9 | 0 | 0/9 | unavailable | 92.4 | 2.641 | `0bb8048f47a6` |
| koboldcpp | deepseek-r1-70b | reasoning | 9 | 0 | 0/9 | unavailable | 180 | 2.631 | `0bb8048f47a6` |
| lmstudio | deepseek-r1-70b | coding | 9 | 0 | 3/9 | unavailable | 209.8 | 2.26 | `f3eeb54d9350` |
| lmstudio | deepseek-r1-70b | math | 9 | 0 | 0/9 | unavailable | 115.3 | 2.272 | `f3eeb54d9350` |
| lmstudio | deepseek-r1-70b | reasoning | 9 | 0 | 0/9 | unavailable | 207.1 | 2.268 | `f3eeb54d9350` |
| ollama | deepseek-r1-70b | coding | 9 | 0 | 3/9 | unavailable | 175.7 | 2.659 | `7a0671b05227` |
| ollama | deepseek-r1-70b | math | 9 | 0 | 0/9 | unavailable | 91.33 | 2.671 | `7a0671b05227` |
| ollama | deepseek-r1-70b | reasoning | 9 | 0 | 3/9 | unavailable | 180.7 | 2.662 | `7a0671b05227` |

![Request latency](../../../../diagrams/results/model-offloading/campaign-20261116T025021Z-920ba116-offload-model-offloading-1/latency.png)

## Interpretation and reproduction

Warmups and superseded attempts remain in raw data and are excluded from summaries. Each job/category is a separate cohort. Missing values remain unknown. Replay cost and generation latency are estimates; an offline oracle is an upper bound. LiveBench upstream grades are exported separately as judgment and benchmark summary records, not relabeled as local smoke scores.

Use the measured code revision and resolved configuration to reconstruct the campaign with your local artifact paths and credential references. Verify the recorded input hashes. Run `llm-eval plan --campaign YOUR_CAMPAIGN.json` before `llm-eval run --campaign YOUR_CAMPAIGN.json`. Synthetic results do not establish model quality or hardware performance.
