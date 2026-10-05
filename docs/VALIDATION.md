# Validation status

## Completed locally

- Public repository cloned from initial commit `71a0dbc5ed06cc4d37f5ea54af3cdd285b43ad7b`; existing MIT license preserved.
- Candidate metadata and immutable original-model revisions retrieved from official publisher Hugging Face repositories; exact quantized artifacts still require selection.
- Core package installs as an editable Python package with no inference dependencies.
- Final local validation: **16 tests passed** under Python 3.12.14; telemetry path exercised with psutil 7.2.2. CLI config preparation, inventory, matrix generation (648 cells), empty reporting, bytecode compilation, and whitespace checks passed. The development container is Ubuntu 24.04 without an NVIDIA GPU; it is not the target laptop.
- Unit/integration tests use a loopback HTTP server and synthetic files. They exercise SSE and NDJSON parsing, reasoning versus visible timing, missing usage, truncated streams, redirects, deadlines, artifact hashing/tampering, traversal rejection, matrix exclusions, warmups, synthetic-result exclusion, and report grouping.
- CI is configured for Python 3.11/3.12/3.13 on Linux and Windows. Configuration is not a claim that GitHub CI has already run.

## Not measured or certified

- No access to the user's MSI laptop, physical RTX 5090 Laptop GPU, BIOS, driver, power profile, or SSD mounts.
- No real model inference, OOM/VRAM/RAM qualification, thermal run, or model-quality ranking.
- No native Windows/WSL execution in the development container; CI only exercises the portable harness, not GPU engines.
- No comprehensive security audit of the other eight engines is implied by their inclusion.
- Accelerate/AirLLM workers are optional implementations that require their dependencies and per-model smoke tests. Multimodal inputs and generated-code execution are not implemented.
- No automatic model download, license acceptance, engine build/install, driver change, OS tuning, backend lifecycle management for servers, cold-cache reset, or concurrency sweep.
- No empirical claim that any 120B candidate meets the 64 GiB RAM budget; these remain conditional.

## Acceptance gate on the laptop

For each claimed successful cell, retain: exact artifacts/revisions, engine/dependency versions, active template, observed OS/hardware, startup placement log, successful format/quality smoke, actual prompt/output token counts, stable repeated timings, RAM/VRAM peaks and paging status. WSL additionally requires Windows host memory observations. Explicitly classify missing sensors and unsupported combinations.

A benchmark request reaching an endpoint is not proof of the requested backend, model, quantization, or offload placement. Verify those facts independently from local startup/configuration evidence. The harness labels them as operator attestations.
