# Validation status

## Experiment campaign implementation

The v0.3 campaign refactor adds experiment contracts, dependency scheduling, local/SSH workers, persistent host ownership, decision/replay/live routing, report generation, and results PR publication. Local validation under Python 3.12 passes **63 tests**, including a real local worker with automatic reporting, supervision dependency preflight, parallel independent hosts versus serial shared hosts, lost-run and lost-reservation recovery, unavailable-target admission, chunked artifact integrity, routing protocol/budget/fallback checks, deterministic sanitized reporting, and real temporary Git worktree/push recovery with a simulated GitHub API.

A real local worker process completes the synthetic routing campaign and produces JSON/CSV/raw gzip/Markdown/PNG outputs. The combined offload/routing example resolves into three jobs. Report and architecture PNGs were inspected. These checks do not contact paid providers or generate model-quality rankings.

The Linux/Windows Python 3.11/3.12/3.13 CI matrix includes the telemetry and reporting extras. Real NVIDIA hardware, native Windows/WSL GPU execution, two physical SSH hosts, actual SystemOne model inference, and paid-provider billing/rate-limit behavior remain operator acceptance gates. Live routing currently uses deterministic checks; full upstream LiveBench grading remains in the original offload lane, while routing replay accepts fingerprint-bound externally graded outcomes.

Before claiming a multi-host study, verify no overlap for shared physical IDs; concurrent work on independent machines; disconnect/reconnect collection without duplicate requests; cancellation and owned-process cleanup; Windows/WSL shared locks; and a complete result PR against the intended repository using operator credentials. The publisher's network/auth failure path is covered by a local Git integration test, not a real credentials-bearing result publication.

## Completed locally

- Public repository cloned from initial commit `71a0dbc5ed06cc4d37f5ea54af3cdd285b43ad7b`; existing MIT license preserved.
- Candidate metadata and immutable original-model revisions retrieved from official publisher Hugging Face repositories; exact quantized artifacts still require selection.
- Core package installs as an editable Python package with no inference dependencies.
- Final local validation: **40 tests passed** under Python 3.12.14; telemetry path exercised with psutil 7.2.2. CLI config preparation, inventory, matrix generation (783 cells), empty reporting, bytecode compilation, and whitespace checks passed. The development container is Ubuntu 24.04 without an NVIDIA GPU; it is not the target laptop.
- Unit/integration tests use a loopback HTTP server and synthetic files. They exercise SSE and NDJSON parsing, reasoning versus visible timing, missing usage, truncated streams, redirects, deadlines, artifact hashing/tampering, traversal rejection, matrix exclusions, warmups, synthetic-result exclusion, and report grouping.
- Added workflow tests cover all 54 wrappers and 25 eligible OS/platform dry-run pairs (two native Windows pairs explicitly rejected), interactive/CLI selection, immutable pins, download checksum failure, archive traversal/symlinks, explicit model download manifests, loopback launch controls, authenticated readiness, secret-free plans, host preflight, category aggregation, LiveBench dataset/test-case hashing, agent/worker gates, no host incremental grading, and managed-server shutdown before isolated grading.
- The merged [PR #3 CI run](https://github.com/asanderson/llm-eval/actions/runs/37376533080) passed all six Linux/Windows Python 3.11/3.12/3.13 jobs. The follow-up fixes add real Bash/PowerShell wrapper dry-run execution to that matrix; this remains CPU-only harness testing.
- Follow-up regressions cover per-model interactive defaults, case-sensitive local model routing, IPv6/prefixed API endpoints, complete finite judgment coverage (including valid zero scores), missing-result failure despite zero subprocess exit codes, and separate per-category CSV retention. All 36 Linux/WSL wrappers executed locally in dry-run mode from a path containing spaces. The pinned upstream model-config loader/API-name resolver was also exercised directly with a temporary local mapping; full LiveBench execution remains untested.

## Not measured or certified

- No access to the user's MSI laptop, physical RTX 5090 Laptop GPU, BIOS, driver, power profile, or SSD mounts.
- No real model inference, OOM/VRAM/RAM qualification, thermal run, or model-quality ranking.
- No native Windows/WSL execution in the development container; CI only exercises the portable harness, not GPU engines.
- No comprehensive security audit of the other eight engines is implied by their inclusion.
- Accelerate/AirLLM workers are optional implementations that require their dependencies and per-model smoke tests. Multimodal inputs are not implemented; generated-code execution is confined to the explicit upstream LiveBench lane.
- Engine setup, explicit manifest downloads and managed server lifecycle are implemented but were not executed against real engines/GPU models in this development container. No target OS installation, driver change, OS tuning, cold-cache reset or concurrency sweep has been performed.
- Optional upstream LiveBench dependencies, Docker image, public question coverage and agentic task execution have not been validated end-to-end here. Upstream API/argument checks use the pinned source; orchestration tests use mocks. Installer pins are not a certification of current wheels or all model architectures.
- No empirical claim that any 120B candidate meets the 64 GiB RAM budget; these remain conditional.

## Acceptance gate on the laptop

For each claimed successful cell, retain: exact artifacts/revisions, engine/dependency versions, active template, observed OS/hardware, startup placement log, successful format/quality smoke, actual prompt/output token counts, stable repeated timings, RAM/VRAM peaks and paging status. WSL additionally requires Windows host memory observations. Explicitly classify missing sensors and unsupported combinations.

A benchmark request reaching an endpoint is not proof of the requested backend, model, quantization, or offload placement. Verify those facts independently from local startup/configuration evidence. The harness labels them as operator attestations.
