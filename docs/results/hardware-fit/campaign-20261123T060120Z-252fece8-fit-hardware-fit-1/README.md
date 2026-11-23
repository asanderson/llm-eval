# hardware-fit results

Status: **complete**. Synthetic fixtures: **false**.

Campaign: `fit-wsl-projection`. Experiment run: `fit-hardware-fit-1`. Measured code: `2695cba457664b269921edfcf5afa430e2222330`.

[Raw measurements](raw/measurements.jsonl.gz) · [JSON summary](summary.json) · [CSV summary](summary.csv) · [Manifest](manifest.json) · [Resolved configuration](resolved-config.json)

## Configuration coverage

| Case | Hardware | OS | Harness | Model | Status |
|---|---|---|---|---|---|
| projection-measured-models | raider-wsl | windows-11-wsl2-ubuntu-26.04 | projection | measured-models-gguf | succeeded |
| projection-measured-models-as-found | raider-wsl | windows-11-wsl2-ubuntu-26.04 | projection | measured-models-gguf-as-found | succeeded |

## Measurements by harness and model

| Harness | Model | Category | Requests | Errors or missing | Quality passes | Decision accuracy | Median seconds | Output tokens/s | Job |
|---|---|---|---:|---:|---:|---:|---:|---:|---|
| projection | measured-models-gguf | exceeds-vram | 247 | 0 | unavailable | unavailable | unavailable | unavailable | `350a43aad20a` |
| projection | measured-models-gguf | fits | 183 | 0 | unavailable | unavailable | unavailable | unavailable | `350a43aad20a` |
| projection | measured-models-gguf-as-found | exceeds-disk | 162 | 0 | unavailable | unavailable | unavailable | unavailable | `f008c633e429` |
| projection | measured-models-gguf-as-found | exceeds-vram | 268 | 0 | unavailable | unavailable | unavailable | unavailable | `f008c633e429` |

![Request latency](../../../../diagrams/results/hardware-fit/campaign-20261123T060120Z-252fece8-fit-hardware-fit-1/latency.png)

## Interpretation and reproduction

Warmups and superseded attempts remain in raw data and are excluded from summaries. Each job/category is a separate cohort. Missing values remain unknown. Replay cost and generation latency are estimates; an offline oracle is an upper bound. LiveBench upstream grades are exported separately as judgment and benchmark summary records, not relabeled as local smoke scores.

Use the measured code revision and resolved configuration to reconstruct the campaign with your local artifact paths and credential references. Verify the recorded input hashes. Run `llm-eval plan --campaign YOUR_CAMPAIGN.json` before `llm-eval run --campaign YOUR_CAMPAIGN.json`. Synthetic results do not establish model quality or hardware performance.
