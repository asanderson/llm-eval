# model-offloading results

Status: **complete**. Synthetic fixtures: **false**.

Campaign: `matrix-wsl-kimi-linear-48b`. Experiment run: `offload-model-offloading-1`. Measured code: `7e4606827cde8d9af4ccbb0c2ec8473d8d8049ce`.

[Raw measurements](raw/measurements.jsonl.gz) · [JSON summary](summary.json) · [CSV summary](summary.csv) · [Manifest](manifest.json) · [Resolved configuration](resolved-config.json)

## Configuration coverage

| Case | Hardware | OS | Harness | Model | Status |
|---|---|---|---|---|---|
| kimi-linear-48b-koboldcpp | raider-wsl | windows-11-wsl2-ubuntu-26.04 | koboldcpp | kimi-linear-48b | succeeded |
| kimi-linear-48b-ollama | raider-wsl | windows-11-wsl2-ubuntu-26.04 | ollama | kimi-linear-48b | succeeded |

## Measurements by harness and model

| Harness | Model | Category | Requests | Errors or missing | Quality passes | Decision accuracy | Median seconds | Output tokens/s | Job |
|---|---|---|---:|---:|---:|---:|---:|---:|---|
| koboldcpp | kimi-linear-48b | coding | 9 | 0 | 9/9 | unavailable | 0.5245 | 3.817 | `0663edde83e7` |
| koboldcpp | kimi-linear-48b | math | 9 | 0 | 9/9 | unavailable | 0.5245 | 3.813 | `0663edde83e7` |
| koboldcpp | kimi-linear-48b | reasoning | 9 | 0 | 6/9 | unavailable | 0.5252 | 4.929 | `0663edde83e7` |
| ollama | kimi-linear-48b | coding | 9 | 0 | 9/9 | unavailable | 0.1486 | 15.69 | `1ae17d24547e` |
| ollama | kimi-linear-48b | math | 9 | 0 | 9/9 | unavailable | 0.1301 | 15.37 | `1ae17d24547e` |
| ollama | kimi-linear-48b | reasoning | 9 | 0 | 6/9 | unavailable | 0.1702 | 17.9 | `1ae17d24547e` |

![Request latency](../../../../diagrams/results/model-offloading/campaign-20261117T043857Z-d2cbbd81-offload-model-offloading-1/latency.png)

## Interpretation and reproduction

Warmups and superseded attempts remain in raw data and are excluded from summaries. Each job/category is a separate cohort. Missing values remain unknown. Replay cost and generation latency are estimates; an offline oracle is an upper bound. LiveBench upstream grades are exported separately as judgment and benchmark summary records, not relabeled as local smoke scores.

Use the measured code revision and resolved configuration to reconstruct the campaign with your local artifact paths and credential references. Verify the recorded input hashes. Run `llm-eval plan --campaign YOUR_CAMPAIGN.json` before `llm-eval run --campaign YOUR_CAMPAIGN.json`. Synthetic results do not establish model quality or hardware performance.
