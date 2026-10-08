# Experiment campaigns

The existing `run --config` commands and platform scripts remain supported. Campaigns select versioned experiments, named cases, hardware configurations and phase dependencies. Cases can evaluate the same model with different placement settings.

Use `python -m llm_eval experiments list` and `python -m llm_eval plan --campaign FILE`. A plan performs no installation, model download or inference. Paths resolve relative to their declaring JSON files. Inventory files contain `targets` and `hardware_configs` objects keyed by stable identifiers. An experiment case is `{"id":"case-name","parameters":{...}}`.

`model-offloading` accepts a `config` path to an existing run config, `server_mode` (managed or external), and optional `installation_state`. The original smoke and LiveBench integrations retain their existing provenance and grading rules.

The orchestration and routing additions are delivered as an ordered PR series. Each follow-up describes its execution and validation support.
