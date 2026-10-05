# Security and privacy

The harness binds no public service. HTTP clients accept only literal loopback addresses, use no environment proxy, do not follow redirects, have a wall-clock deadline and response limits, and never execute returned tools or code. Endpoint URLs cannot contain credentials. Set `api_key_env` to the name of a local environment variable; do not put a secret in JSON. Backend error bodies are omitted because they can echo prompts or keys.

Results store hashes and metrics by default, not generated text. `save_outputs=true` explicitly stores answers, which may contain prompt data. Configurations, paths, hardware observations, and timing metadata are still sensitive in some environments. Keep results private until reviewed; they are ignored by git. Workloads committed here are original synthetic text. Do not publish private prompts, tokens, model weights, or logs with credentials.

Model artifacts are downloaded separately, under the owner's credentials and license acceptance. The harness does not install software, run shell commands embedded in catalogs, fetch arbitrary model code, or execute generated programs. Pin backend dependencies and review their native/Python loaders. Hugging Face `trust_remote_code` is disabled in the Accelerate worker unless `reviewed_model_code=true`; offline mode is not a sandbox and local custom code still executes if enabled.

AirLLM's internal loaders are version-dependent. Its worker requires `reviewed_airllm_source=true` before loading. That flag is an attestation, not an automatic audit. Run experimental model loaders under a separate unprivileged account/container with access only to model files and a dedicated cache. Review legacy pickle-bearing weight formats before use; prefer safetensors/GGUF where the engine supports them. Native parsers can still have vulnerabilities.

Local workers omit common secret-bearing environment variables and set Hugging Face offline/telemetry controls. This is defense in depth, not complete environment sanitization or network isolation. Use OS-level egress controls for sensitive workloads. Maintain the earlier Strata restrictions: loopback binding, API authentication, no unreviewed MCP/vision input, and verified model/engine downloads.

Do not assume free/open-source software makes every model permissively licensed. The catalog records Apache/MIT and model-specific terms separately, including Meta, NVIDIA, Gemma 3, Grok 2, OpenMDW, and the inherited Qwen condition on Kimi-Dev. No claim of FIPS, FedRAMP, or other certification is made by this project.
