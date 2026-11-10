# model-offloading results

Status: **complete**. Synthetic fixtures: **false**.

Campaign: `matrix-phi4-reasoning-plus`. Experiment run: `offload-model-offloading-1`. Measured code: `e64ec842608c30a6b4cba9f44b1711cc5e53ca19`.

[Raw measurements](raw/measurements.jsonl.gz) · [JSON summary](summary.json) · [CSV summary](summary.csv) · [Manifest](manifest.json) · [Resolved configuration](resolved-config.json)

## Configuration coverage

| Case | Hardware | OS | Harness | Model | Status |
|---|---|---|---|---|---|
| phi4-reasoning-plus-koboldcpp | raider-windows | windows-11-native | koboldcpp | phi4-reasoning-plus | succeeded |
| phi4-reasoning-plus-lmstudio | raider-windows | windows-11-native | lmstudio | phi4-reasoning-plus | succeeded |
| phi4-reasoning-plus-ollama | raider-windows | windows-11-native | ollama | phi4-reasoning-plus | succeeded |

## Measurements by harness and model

| Harness | Model | Category | Requests | Errors or missing | Quality passes | Decision accuracy | Median seconds | Output tokens/s | Job |
|---|---|---|---:|---:|---:|---:|---:|---:|---|
| koboldcpp | phi4-reasoning-plus | coding | 9 | 0 | 6/9 | unavailable | 0.601 | 3.358 | `daebf80475d1` |
| koboldcpp | phi4-reasoning-plus | math | 9 | 0 | 6/9 | unavailable | 0.5989 | 3.353 | `daebf80475d1` |
| koboldcpp | phi4-reasoning-plus | reasoning | 9 | 0 | 3/9 | unavailable | 392.5 | 5.217 | `daebf80475d1` |
| lmstudio | phi4-reasoning-plus | coding | 9 | 0 | 0/9 | unavailable | 47.2 | 4.253 | `dbb471ed01d8` |
| lmstudio | phi4-reasoning-plus | math | 9 | 0 | 0/9 | unavailable | 68.16 | 4.255 | `dbb471ed01d8` |
| lmstudio | phi4-reasoning-plus | reasoning | 9 | 0 | 0/9 | unavailable | 413.5 | 4.186 | `dbb471ed01d8` |
| ollama | phi4-reasoning-plus | coding | 9 | 0 | 0/9 | unavailable | 394.1 | 5.196 | `7f239688f788` |
| ollama | phi4-reasoning-plus | math | 9 | 0 | 0/9 | unavailable | 392.1 | 5.223 | `7f239688f788` |
| ollama | phi4-reasoning-plus | reasoning | 9 | 0 | 0/9 | unavailable | 393.7 | 5.202 | `7f239688f788` |

![Request latency](../../../../diagrams/results/model-offloading/campaign-20261110T014022Z-9e4b4e08-offload-model-offloading-1/latency.png)

## Interpretation and reproduction

Warmups and superseded attempts remain in raw data and are excluded from summaries. Each job/category is a separate cohort. Missing values remain unknown. Replay cost and generation latency are estimates; an offline oracle is an upper bound. LiveBench upstream grades are exported separately as judgment and benchmark summary records, not relabeled as local smoke scores.

Use the measured code revision and resolved configuration to reconstruct the campaign with your local artifact paths and credential references. Verify the recorded input hashes. Run `llm-eval plan --campaign YOUR_CAMPAIGN.json` before `llm-eval run --campaign YOUR_CAMPAIGN.json`. Synthetic results do not establish model quality or hardware performance.
