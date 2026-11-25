# Matched offloading on the Raider

This campaign measures the cost of changing GPU placement for one oversized Llama 3.3 70B Q4_K_M artifact on one physical laptop. Its two managed llama.cpp jobs request 20 and 32 GPU layers, 16 CPU threads, a 16,384-token context, a 1,024-token output cap, 22 GiB VRAM and a 46 GiB CPU-weight budget. Each job warms each prompt once, then sends it three more times sequentially. Both arms request disabled prompt caching. Confirm the loaded placement, cache policy and build in the server log. These are proposed settings. The linked earlier run supplies artifact provenance. [Prior run](../../../docs/results/model-offloading/campaign-20261122T090027Z-2fbb4fe0-offload-model-offloading-1/README.md)

| Workload | Request | Observation |
|---|---|---|
| Short interactive | Find a seal number in a single ledger entry | Time until first visible text, total client time and actual response length |
| Long input, 4K and 8K | Find that same number in fixed 360-entry and 720-entry ledgers | Backend prompt tokens, first visible text and backend prefill rate. The named targets require at least 4,096 and 8,192 **reported** prompt tokens respectively. |
| Sustained output | Write forty numbered, sentence-length museum volunteer tips | Actual output tokens, visible characters, stop reason and backend decode rate. The sustained group requires at least 256 reported completion tokens. |

The fixture fixes the exact input bytes. Tokenization and template overhead vary by backend, and cached-prefix accounting can affect prompt counts. Preserve the requested and observed lengths. A model that stops early or spends its budget on hidden reasoning contributes to the outcome counts. The sustained target counts generated tokens including backend-accounted reasoning. Check visible characters, first visible latency and finish reason alongside it. These probes carry no quality grade. [Workload](../workloads/matched-v1.json)

## Run a placement pair

1. Install the harness with telemetry. In a clean checkout, plan the shipped example. Planning needs neither a GPU nor model weights.

   ```bash
   python -m llm_eval plan --campaign experiments/model-offloading/matched/campaign.json
   ```

2. Copy `experiments/model-offloading/matched` to `configs/local/matched`. Materialize the single `Llama-3.3-70B-Instruct-Q4_K_M.gguf` file from `bartowski/Llama-3.3-70B-Instruct-GGUF` at `b6c5c9f176f3279204034e1d16d393105e95cb88` under `configs/local/matched/models/llama33-70b-q4km/`, subject to the model terms. Create the lock. Set the active chat template SHA-256 and actual hardware attestation in your local `run.json`. Update `suite` to the absolute path of `experiments/model-offloading/workloads/matched-v1.json` for standalone use. Campaign mode always pins that versioned workload from the checkout.

   ```bash
   python -m llm_eval lock --root configs/local/matched/models/llama33-70b-q4km \
     --source-repo bartowski/Llama-3.3-70B-Instruct-GGUF \
     --source-revision b6c5c9f176f3279204034e1d16d393105e95cb88 \
     --base-model meta-llama/Llama-3.3-70B-Instruct --precision Q4_K_M \
     --output configs/local/matched/artifacts/llama33-70b-q4km.lock.json
   python scripts/setup.py --non-interactive --platform llama.cpp --os ubuntu-26.04-native \
     --models llama33-70b --revision b1b770d90d94cad9e9ea5b993bdbc383a522fb28 \
     --with-livebench --build-livebench-image llm-eval-livebench:2026-06-25
   python -m llm_eval run --campaign configs/local/matched/campaign.json --output results
   ```

   Setup requires the platform build dependencies and Docker for the optional quality lane. For performance alone, omit the two LiveBench flags. Choose a new installation prefix if an existing one's setup plan differs, then set the case's `installation_state` to that prefix's `state.json`.

3. Use the two named attempt `result.json` paths under `experiments/<run>/jobs/<job>/<attempt>/` in the campaign directory in the order you intend. The comparison prints JSON. The standard experiment report links `model-offloading-summary.json` and shows workload timing and token coverage for the latest attempt of each job.

   ```bash
   python -m llm_eval.experiments.model_offloading.performance --axis gpu-layers \
     "$LAYER20_RESULT" "$LAYER32_RESULT" > results/placement-pair.json
   ```

4. Repeat in reverse order in a separate session after bringing the laptop back to the same starting temperature. Reverse the two hardware IDs in the local campaign. Fix power/fan mode, AC supply, MUX, model storage and background load. For cold-load measurements start a fresh managed process and record file-cache state per session. `managed_backend_start_to_ready_s` includes server readiness and preparation. A lazy engine can load weights on the first warmup. Worker load time, backend-reported load time, warmup wall times and warm request metrics are separate observations.

For a thermal trial, use the measured per-request times to set `repeats` for a 15–30 minute run per arm. Verify the realized `thermal.sample_span_s`. The attempt records first- and last-minute temperature, power and SM-clock distributions for the selected GPU, plus the timestamped `telemetry.json` covering all prompts and warmups. Check the trace for drift and throttling and repeat each arm with the same repetition count. A short trace cannot establish thermal steady state.

## Compare operating systems and memory pressure

Boot each OS separately on the **same physical laptop**. Use the same checkout, GGUF lock, template, backend revision, context, prompts, power mode, disk, thread count and one layer count from the placement pair. Set the same physical host ID in both inventories. Update the local inventory and run configuration to the actual OS and update its driver/build attestation. WSL and native Windows workers must share a host-visible scheduler lock directory. Then use the same comparison command with `--axis os`. Examine the two OS-specific attestations for differences in drivers, power mode or storage before attributing a difference to the OS. Changing engine, artifact or quantization introduces another intervention. For a smaller, fully GPU-resident user alternative use a separately verified hardware-fit result. [Hardware fit](../../hardware-fit/README.md)

On this Raider, **46 GiB is the CPU-weight planning budget** on both arms. The WSL guest cap is separately configured to 52 GiB within 64 GiB of physical RAM. Preserve the remaining space for Windows, runtime buffers, KV cache and other allocations. A native run using the larger 52 GiB weight budget answers a separate capacity question.

Collect Windows host memory and page-out counters throughout the WSL run. For example, run this in English-language Windows PowerShell before the campaign and stop it after inference finishes. Use localized counter names if necessary.

```powershell
Get-Counter -Counter '\Memory\Available MBytes','\Memory\Committed Bytes','\Memory\Pages Output/sec' `
  -SampleInterval 1 -Continuous | Export-Counter -Path .\wsl-host-memory.blg -FileFormat BLG
```

Keep the trace, host timestamps and guest run times together. The attempt summary reports guest swap separately from Windows host paging. Supply `hardware_attestation.paging` (`none` or `observed`) only when independently supported for the relevant host and interval, and optionally record `windows_host_used_gib_peak` from that host. For a trace reviewed after the run, retain it as a sidecar and report its finding separately from the immutable attempt. Missing sensors or one swap sample leave the paging result unknown. Page traffic and sampled peaks are system-wide. A successful load alone cannot establish resident operation.

## Read the performance result

Report the artifact and suite hashes, declared layer split, logged layer counts, and coverage for **each** workload. Each metric has the count, minimum, median, interpolated p95 and maximum across successful measured requests. Three repeats provide a pilot, so retain the raw samples. `first_output_s` may include a reasoning delta. `first_visible_s` measures first streamed content. Nonstreaming workers can supply client wall time even when first visible time is unavailable. Client throughput divides backend-reported completion tokens by the whole client request time. Backend prefill and decode rates require explicit backend timing. Unknown values have a null median and zero observations.

The pair tool checks pinned artifact, protocol, source revision, model/template/tokenizer and common run settings. It returns right-minus-left median differences, counts and stop reasons. For the longer prompts and sustained generation it computes deltas only over samples that reached the named token target. A missed target or absent timing can therefore leave a delta null. Read failed/unattempted counts alongside successful timing samples. A single observed model load per arm permits a check of the logged layer counts. Otherwise the result labels the split as requested only. The OS comparison requires equal launch settings and, on the Raider WSL pair, equal 46 GiB budgets.

## Pinned upstream quality pair

Use the same verified model/placement as each performance arm. The example selects the v1 **2026-06-25** release, scorer **1d1006a0d10ece52c2e706f8a208a659b5bbb96f**, regular reasoning and mathematics, 16,384 context tokens and a 1,024-token answer cap. Its score describes this local snapshot and budget. Prepare the local question and test files once using the upstream downloader linked in the quality guide, then retain the dataset revision or file manifest with the run. Supply the same data directory and local image ID for both arms. [Data layout and download](../../../docs/LIVEBENCH.md#running-upstream-livebench)

```bash
IMAGE_ID=$(docker image inspect --format '{{.Id}}' llm-eval-livebench:2026-06-25)
for layers in 20 32; do
  python scripts/run.py --non-interactive --config configs/local/matched/run.json \
    --server-mode managed --benchmark livebench --categories reasoning,math \
    --livebench-release 2026-06-25 --livebench-data "$LIVEBENCH_DATA" \
    --livebench-image "$IMAGE_ID" --context 16384 --max-tokens 1024 \
    --threads 16 --gpu-layers "$layers" --output "results/quality-layers-$layers"
done
```

Use one fixed upstream dataset snapshot containing `live_bench/reasoning/*/question.jsonl` and `live_bench/math/*/question.jsonl`. Regular inference and isolated judging are separate stages. Each `livebench-run.json` records the exact questions, eligible IDs, test-case hashes, scorer revision, immutable grading image and judgment coverage. Upstream sampling follows question settings and scorer defaults. Record the actual category/task counts and the `valid/expected` coverage. Join completed judgments across the two runs by category, task and question ID to report each paired score difference, improvements, ties and regressions. Report partial coverage as such. Keep latency and decoding evidence in the matched performance pair.

Pass the two directories containing `livebench-run.json`. The command rechecks the question/test hashes and judgment coverage, checks artifact, scorer, image, settings and requested layer counts, then emits the item IDs and differences without answer text.

```bash
python -m llm_eval.experiments.model_offloading.quality \
  "$LIVEBENCH_LAYER20_DIR" "$LIVEBENCH_LAYER32_DIR" > results/quality-pair.json
```
