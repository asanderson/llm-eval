# Hardware fit: the best model artifact that stays inside GPU VRAM

`hardware-fit` answers one question for one hardware configuration: which model artifact (a model at one quantization) is the best fit when the weights, the key and value cache and the compute buffers must all stay inside GPU VRAM and no layer may be placed on the CPU.

It is the counterpart of [model offloading](../model-offloading/README.md). That experiment requires weights larger than VRAM and measures the split between GPU and RAM. This one refuses that regime: a run that leaves VRAM fails.

| Mode | Needs | What it produces |
|---|---|---|
| `projection` (default) | No GPU and no model files | For every candidate artifact: the VRAM, RAM and disk it needs, the limits it exceeds, and a shortlist. A projection, never a measurement. |
| `measured` | The GPU of the hardware profile, a locked artifact, an installed harness | One artifact served with every layer requested on the GPU, the category suites of model offloading, and the evidence that the run stayed inside VRAM. |

A succeeded `measured` job is ranked by the results index like any other measured run. The best-ranked combination of `hardware-fit` on a hardware configuration is the measured best fit, and the recommended setup page of that pair shows it. Projection rows carry no scored check, so a projection never enters that ranking.

## The hardware configuration

A job is bound to a hardware configuration of the campaign inventory, which names a hardware profile under `configs/hardware/` and an OS. The experiment reads these values from it:

| Resource | Source |
|---|---|
| GPU and VRAM | `gpu.name`, `gpu.vram_gib` and `gpu.initial_reserve_gib` of the profile. The reserve is VRAM that must stay free. |
| CPU | `cpu.threads` of the profile. |
| RAM | The RAM budget of the profile for the OS: `os_limits.<os>.ram_budget_gib`, else `ram.installed_gib` minus `host_reserve_gib`. |
| Disk | `disk_free_gib` of the case. Without it, the free space of the volume that holds `artifact_root`, measured when the job runs. |

A hardware profile carries storage capacity, not free space, so free disk space comes from the case. Another machine needs its own profile file and an inventory entry; the experiment has no hardware constants of its own.

## Projection

For every candidate artifact, with `GIB` = 2^30 bytes:

```text
kv_bytes       = kv_elements_per_token * context_tokens * kv_bytes_per_element
vram_required  = weight_bytes + kv_bytes + compute_buffer_gib * GIB
vram_available = (vram_gib - vram_reserve_gib - gpu_baseline_gib) * GIB
ram_required   = host_ram_overhead_gib * GIB + host_ram_weight_fraction * weight_bytes
disk_required  = weight_bytes * disk_copies + disk_headroom_gib * GIB
bits_per_weight = weight_bytes * 8 / parameters
```

An artifact exceeds `vram` when `vram_required` is above `vram_available`, `ram` when `ram_required` is above the RAM budget, `disk` when `disk_required` is above the free disk space, `cpu` when the launch threads are above the profile's threads, and `context` when `context_tokens` is above the context the model was trained with. It fits when it exceeds nothing. The verdict of a row is `fits` or `exceeds-` followed by the first exceeded limit in that order.

The policy values are planning assumptions. A case overrides any of them under `policy`:

| Policy key | Default | Meaning |
|---|---:|---|
| `kv_bytes_per_element` | 2 | Precision of the key and value cache. 2 is f16, the engines' default. |
| `compute_buffer_gib` | 1.0 | Allowance for the engine's compute and scratch buffers on the GPU. |
| `gpu_baseline_gib` | 0.0 | VRAM that other programs hold, on top of the profile reserve. Add the difference when `gpu.vram_gib` of the profile is larger than the total the card reports. |
| `host_ram_overhead_gib` | 8.0 | RAM for the OS, the harness and the engine process. |
| `host_ram_weight_fraction` | 0.0 | Share of the weights a loader stages in RAM. 1.0 for a loader that reads all weights into RAM first. |
| `disk_copies` | 2 | The artifact plus one import copy. Ollama imports a copy; a harness that links the file needs 1. |
| `disk_headroom_gib` | 10.0 | Free space that must remain after the copies. |
| `threads` | unset | Launch threads. Unset is the launch default, the smaller of 16 and the profile's threads. |
| `min_bits_per_weight` | 4.0 | Quantizations below this are listed but never shortlisted. 0 disables the floor. |
| `shortlist` | 10 | Number of ranked entries. |

**Shortlist.** Among the artifacts that fit and have at least `min_bits_per_weight`, each model's best is the one with the most bits per weight. The shortlist orders those by parameter count, larger first, then by bits per weight, then by id. This order is a planning heuristic: it prefers the larger model and then the higher precision. It is not a quality measurement, and it is the order in which to measure, not the answer.

**Case parameters.**

| Parameter | Meaning |
|---|---|
| `identity` | `{"harness": "projection", "model": LABEL}`. The results index lists the job under this harness and model label; name the candidate set. |
| `data` | The candidate set file. The planner hashes it into the plan. |
| `context_tokens` | Context length the projection is computed for, 512 to 1048576. |
| `disk_free_gib` | Declared free disk space. Required for a synthetic case. |
| `artifact_root` | Directory where artifacts are stored. Used to measure free disk space when `disk_free_gib` is absent. |
| `policy` | Overrides of the policy defaults. |
| `synthetic` | `true` for a fixture case. A synthetic candidate set needs a synthetic case. |

**Outputs** in the attempt directory:

- `requests.jsonl`: one row per candidate, sorted by id. The `category` is the verdict, so the report counts the candidates per verdict. Each row carries `weight_gib`, `kv_cache_gib`, `compute_buffer_gib`, `vram_required_gib`, `vram_available_gib`, `vram_headroom_gib`, `ram_required_gib`, `disk_required_gib`, `bits_per_weight`, `parameters_b`, `limits`, `fits`, `model_best` and `rank`.
- `metadata.json`: the hardware values used, the effective policy, the candidate set id with its SHA-256, the count per verdict, the shortlist, and for a run that is not synthetic what the host itself reports (GPU names with total memory, RAM, logical CPUs) for comparison with the profile.
- `fit-projection.md`: the shortlist and the counts as a table for the operator. The generic report does not export this file; the published bundle carries the rows and the metadata.

The report of a projection is the generic one and has no wording of its own for this mode. It lists the verdict counts under the heading "Measurements by harness and model" in a column named "Requests", links the rows as "Raw measurements" and embeds its request latency chart, although the rows carry no latency. Every one of these rows is projected; the caveat that says so is in the exported metadata.

A projection in which nothing fits still succeeds: "nothing fits" is a result.

## Candidate sets

A candidate set is a frozen JSON file: models with their architecture facts, and artifacts with real byte sizes.

| File | Content |
|---|---|
| [candidates/measured-models-gguf.json](candidates/measured-models-gguf.json) | 430 GGUF artifacts of the 17 catalog models that have published model-offloading results: every quantization their artifact repositories list at the revision those runs measured. |
| [candidates/smoke.json](candidates/smoke.json) | A fictional fixture: two invented models and five invented artifacts with round sizes. It is marked synthetic and only a synthetic case may use it. |

How `measured-models-gguf.json` was built, on 2026-11-22:

- **Sizes and hashes** come from the Hugging Face file listing of each artifact repository at the pinned revision (`https://huggingface.co/api/models/REPO/tree/REVISION?recursive=true`): the byte size and the Git LFS SHA-256 of every file. No file name is invented.
- **Architecture facts** are the values llama.cpp printed when it loaded the measured artifact of the model in the published model-offloading runs: the layer count, the trained context, the sliding window and the parameter count. The key and value elements per token are the bytes of cache the engine allocated per context cell, summed over its caches and divided by two (f16 elements). Layers that keep no cache are therefore not counted: only 16 of the 64 layers of `qwen38-27b` keep one. The layer count is the engine's `n_layer`. The engine's placement line counts more than that: the output layer, and for the two `qwen35`-family models one layer more, so it reads "66/66 layers" for the 64 layers of `qwen38-27b`. These facts do not depend on the quantization.
- **Left out:** projector, importance-matrix and `mtp` files, which are not model weights, and split sets whose parts are ambiguous in the listing.

The loader refuses a set with an unknown key, a duplicate id, a candidate of an undeclared model, a revision that is not a full commit, a hash that is not a SHA-256, a file path that is not a relative path to a file, or a `weight_bytes` that is not the sum of its files.

## Measured

One job measures one artifact on one harness. The case has the shape of a model-offloading case with three differences that the validation enforces:

- **Lane.** The run config has `lane` `control`. Every other lane makes the runner refuse weights that do not exceed VRAM.
- **Placement.** Every layer is requested on the GPU: `launch.gpu_layers` 999 for `llama.cpp`, `ik_llama.cpp`, `koboldcpp` and `ollama`, and `launch.gpu_offload` `max` for `lmstudio`. Other platforms are refused in this version. `launch.extra_args` is refused, because extra arguments can override placement and context.
- **Server.** A real run uses `server_mode` `managed`, because the evidence needs the log of a backend the harness owns. A synthetic run uses an external fixture endpoint.

`identity.harness` must equal the platform of the run config. `identity.model` must be the catalog model id followed by the quantization in lower case, so that two quantizations of one model rank separately. That is the candidate id of the set, for example `qwen38-27b-ud-q4_k_xl`. Once the artifact lock exists, the label must end in the lock's `precision` in lower case, so lock the artifact with `--precision` set to the candidate's quantization (`UD-Q4_K_XL` here). [cases/measured-ollama.json](cases/measured-ollama.json) with [runs/ollama.example.json](runs/ollama.example.json) is a template; its placeholders are refused until an operator fills them from a locked artifact.

**Before a job is planned.** When the artifact lock exists and its weights alone are above the VRAM budget (VRAM minus the reserve), the job is planned as skipped with the reason `artifact_exceeds_gpu_vram_budget`.

**Before a backend is started.** The harness checks the run config and the host, verifies the artifact against its lock and reads the GPU: the `nvidia-smi` row with the index that `launch.gpu` selects (0 when unset). When the weights alone are above the VRAM that is free on that card at that moment after the reserve, the job fails with `artifact_exceeds_free_vram` and no backend is started. When that row does not carry the profile's GPU name or reports no memory figures, the job fails with `gpu_memory_unobserved`. A host on which no card carries the profile's GPU name fails earlier, in the host check.

**During the run.** A sampler reads the device-wide VRAM use from before the launch to after the last request, so the model load is covered. The category suites run through the same runner as model offloading. For Ollama, the harness also asks the server what it holds (`size` and `size_vram` of `/api/ps`).

**After the run.** The harness reads the placement lines that llama.cpp prints into the backend log (KoboldCpp and Ollama embed it): the layers offloaded out of the total, the model, cache and compute buffer sizes per device. The recorded sizes are those of the last model load. When the backend loaded the model more than once, every load is judged, because requests answered by an earlier load ran with that load's placement. Then the harness draws the verdict:

| Check | Rule | Reason when it fails |
|---|---|---|
| Capacity | The sampled peak stayed at or below the device total minus the reserve. | `vram_reserve_exceeded` |
| Placement | Every model load in the log shows every layer offloaded and no cache buffer on the CPU. Without a layer line, Ollama reports the whole model in VRAM. | `layers_on_cpu` |
| Rise | VRAM use rose by at least `fit.min_gpu_weight_fraction` (default 0.8) of the weights between the reading before the launch and the peak. | `gpu_use_below_weights` |
| Evidence | With `fit.require_layer_evidence` true, a run without any placement report fails. | `placement_unobserved` |

A run whose requests all completed but whose verdict is not `in_vram` returns `failed` with the reason, so it is not ranked.

Once the artifact is verified against its lock, the evidence is written to `fit/metadata.json` in every outcome, also when the launch fails. The samples are written to `fit/telemetry.json` when a launch was attempted, so a job refused before the launch has no sample file. A job that ends earlier leaves no evidence file: a job skipped when it runs, a placeholder left in the run config, a failed host check, or an artifact that does not match its lock. Both files are exported into the published bundle.

## Running

The software smoke plans and runs on any machine. It uses the fictional candidate set and is labelled synthetic:

```bash
python -m llm_eval plan --campaign campaigns/hardware-fit-smoke.json
python -m llm_eval run --campaign campaigns/hardware-fit-smoke.json
```

The projection for the MSI Raider on native Windows uses the real candidate set. It needs no GPU, but it is a real job: the worker checks that the host OS matches the hardware configuration, that the checkout is clean and that the machine is on AC power. Its case, [cases/projection-measured-models.json](cases/projection-measured-models.json), declares `gpu_baseline_gib` 2.06. That is the sum of two amounts the profile does not carry. The Windows desktop of that laptop held 1994 MiB (1.95 GiB) of VRAM before the measured run of 2026-11-22 that [docs/VALIDATION.md](../../docs/VALIDATION.md) records. And the profile's nominal 24 GiB is 113 MiB (0.11 GiB) more than the 24463 MiB the card reports. The measured capacity check uses the reported total and counts every process on the card, so a projection that leaves either amount out shortlists artifacts that a measured run then fails. On your host, set it to the memory `nvidia-smi` shows in use before a run, plus the difference between `gpu.vram_gib` and the total it shows.

```bash
python -m llm_eval plan --campaign configs/examples/hardware-fit/raider-windows-projection.json
python -m llm_eval run --campaign configs/examples/hardware-fit/raider-windows-projection.json
```

A measured campaign needs what a model-offloading campaign needs: an installed harness, a downloaded and locked artifact, and a run config with the exact backend version, tokenizer revision, chat template hash, placement notes and hardware attestation. Take the artifact from the projection's shortlist, copy the template case and run config, and fill them from the lock.

## Limits

- **The published measured results cover three artifacts, one per model.** They are from WSL2: `qwen38-27b` at UD-Q4_K_XL on KoboldCpp, Ollama and LM Studio on 2026-11-23, with two projections ([results](../../docs/results/README.md#hardware-fit-on-ollama-and-lm-studio-in-wsl2-of-2026-11-23)), and `muse-glimmer-30b` at KQuant Q4_K_M and `inkling2-mini-26b` at IQ4_NL on the same three harnesses on 2026-11-24 ([results](../../docs/results/README.md#hardware-fit-of-muse-glimmer-30b-and-inkling-2-mini-in-wsl2-of-2026-11-24)). The measured best fit of the results index therefore compares three models at one quantization each, not the quantizations of a model, and the two newer models are not in the candidate set of the projection. No result is published for native Windows or native Ubuntu; the native Windows runs that [docs/VALIDATION.md](../../docs/VALIDATION.md#hardware-fit) records are validation runs.
- **A model the engine cannot load reads as `not_in_vram`.** When the backend starts but every request fails because the engine does not know the model's architecture, the rise check fails and the evidence record carries the verdict `not_in_vram` with the reason `gpu_use_below_weights`. Request records keep the type of the error, not its message, so the cause is only in the backend log (Inkling 2 Mini on Ollama 0.40.17, 2026-11-24).
- **In WSL2 the measured free disk space can be virtual.** The guest's filesystem is a virtual disk that grows on a Windows volume, and it reports its own free space, not that volume's. When the Windows volume is the real limit, declare `disk_free_gib` or point `artifact_root` at a directory on that volume.
- **The profile's VRAM is the nominal size.** The projection subtracts from `gpu.vram_gib` of the profile; the measured capacity check subtracts from the total the card reports, which can be smaller. The difference belongs in `gpu_baseline_gib`.
- **The cache estimate is an upper bound for some models.** It counts every layer's key and value elements for the whole context. Layers with a sliding window keep less, so the projection overestimates the cache of such models (the candidate set records `sliding_window_tokens`) and can call an artifact too large that would fit.
- **The compute buffer is a declared constant.** Engines size it from the batch size, the context and the architecture. A measured run records the size the engine printed.
- **A projection is not a measurement.** It says what should fit under the declared policy. Only a measured run shows that an artifact stayed inside VRAM and what it scores.
- **The shortlist order is a heuristic.** It does not use any quality score.
- **The VRAM counter is device-wide and sampled.** Every process on the GPU counts, and a peak shorter than the sampling interval can be missed. The capacity rule therefore keeps the profile reserve free instead of testing for an exact fit.
- **Placement is what the backend reported.** It is read from log lines and from Ollama's own account, not measured per layer. Only buffers on a numbered CUDA device count as GPU memory.
- **One card is judged.** The evidence reads the `nvidia-smi` row with the index of `launch.gpu`. `nvidia-smi` numbers cards in bus order and CUDA can number unequal cards differently, so check the index on a host with more than one card. A model spread over several cards is not assessed.
- **A managed LM Studio launch keeps no placement lines.** The backend log of a managed launch holds the supervisor's line only, not the output of LM Studio's model load. The verdict of such a run rests on the capacity and rise checks unless `fit.require_layer_evidence` is set, in which case the run fails as `placement_unobserved`.
- **Paging on Windows is not ruled out by the counter alone.** The NVIDIA driver can move allocations into shared system memory when dedicated VRAM is exhausted. Keeping the reserve free is the guard against that; the harness does not read shared GPU memory.
