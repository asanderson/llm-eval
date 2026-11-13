# Legal benchmark workflow

The five stages of the [legal benchmark walkthrough](../docs/LEGAL_BENCHMARK_WALKTHROUGH.md) and the explicit output of each. A phase dependency only orders jobs; the next stage names the output file in its case. Stage 3 is optional, and the frozen evaluation takes from it at most the calibration file (dashed edge).

```mermaid
flowchart TD
  offload["1. Offload calibration model-offloading category-smoke"]
  attempt["One succeeded offload attempt directory"]
  profile["2. Locked serving profile profiles freeze (placement attested)"]
  locked["serving-profile.json and its SHA-256"]
  routing["3. Routing calibration and replay (optional): legal-benchmark generation runs per recipe, routed and fallback"]
  calibration["routing calibrate: calibration file (optional)"]
  replay["routing export, replay, verify: routing suite, replay manifest, sidecar (local only)"]
  evaluation["4. Frozen legal evaluation retrieval, generation, workflow"]
  manifest["Attempts, private local/ detail, output-manifest.json"]
  score["score in a later campaign (names the output manifest)"]
  report["5. Local report llm-eval report (projection)"]
  bundle["Projected local bundle; no publication"]
  offload --> attempt
  attempt --> profile
  profile --> locked
  locked --> evaluation
  locked --> routing
  routing --> calibration
  routing --> replay
  calibration -.-> evaluation
  evaluation --> manifest
  manifest --> score
  evaluation --> report
  score --> report
  report --> bundle
```

[View PNG rendering](legal-benchmark-workflow.png).
