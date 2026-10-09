# llm-eval

A reproducible lab for running **versioned LLM experiments** across hardware configurations, operating systems, inference platforms, and explicitly configured hosted models. Campaigns select one or more experiments and execute their cases serially or in parallel on independent resources.

| Experiment | What it evaluates | Guide |
|---|---|---|
| Model offloading | Quality, latency, throughput, and CPU/GPU/disk placement for models exceeding GPU VRAM | [Original experiment and model catalog](experiments/model-offloading/README.md) |
| LLM routing | Decision accuracy, replay selection quality, and live downstream quality/latency/API cost | [Routing guide](experiments/llm-routing/README.md) |

The original target is the MSI Raider 18 HX AI with RTX 5090 Laptop 24 GiB, 64 GiB RAM, and native Ubuntu, native Windows, or WSL. Additional machines use their own profiles and execution targets. **Fixture tests are not real hardware benchmarks.** See the [validation record](docs/VALIDATION.md) for hardware acceptance gates.

## Start here

Run the [readiness checker](docs/READINESS.md) on the test host to find missing tools/libraries and install supported prerequisites after prompting: `powershell -NoProfile -File .\scripts\readiness.ps1` on native Windows, or `bash scripts/readiness.sh` on Ubuntu/WSL. Use `--check-only` for an audit or `--campaign FILE` to derive requirements from your experiments.

For a complete combined model-offloading and routing campaign on the MSI Raider, choose your OS. Each walkthrough covers installation, model preparation, plan, setup, run, status, resume, reports and results PRs, with labeled example output.

| Platform | Walkthrough | Campaign files |
|---|---|---|
| Native Windows 11 | [PowerShell](docs/WINDOWS_RAIDER_WALKTHROUGH.md) | [raider-windows](configs/examples/raider-windows/) |
| WSL2 / Ubuntu 26.04 | [Bash with Windows host preparation](docs/WSL_RAIDER_WALKTHROUGH.md) | [raider-wsl](configs/examples/raider-wsl/) |
| Native Ubuntu 26.04 | [Bash](docs/UBUNTU_RAIDER_WALKTHROUGH.md) | [raider-ubuntu](configs/examples/raider-ubuntu/) |

```bash
python -m pip install -e ".[telemetry,reporting]"
python -m llm_eval experiments list
python -m llm_eval plan --campaign campaigns/routing-smoke.json
python -m llm_eval run --campaign campaigns/routing-smoke.json
```

The smoke campaign is a labeled synthetic category-routing fixture. It runs without model downloads or paid API calls and generates a local report. It does not publish a PR.

For the campaign wizard:

```bash
python scripts/setup.py --interactive
python scripts/run.py --interactive
```

For real experiments, copy and complete the [combined campaign example](campaigns/offload-and-routing.example.json), hardware inventory and experiment cases in `configs/local/`. The example enables automatic results PRs; configure GitHub credentials before publication. Inspect the plan before running it.

```bash
llm-eval plan --campaign configs/local/campaign.json
llm-eval setup --campaign configs/local/campaign.json
llm-eval run --campaign configs/local/campaign.json --max-parallel-jobs 1
llm-eval run --campaign configs/local/campaign.json --max-parallel-jobs 2
llm-eval status --campaign-dir results/campaign-EXAMPLE
llm-eval resume --campaign-dir results/campaign-EXAMPLE
```

Parallel jobs share a resource scheduler. Isolated measurements sharing a physical host run serially; Windows and WSL on the same laptop share one resource identity. Separate boot environments are resumed in their respective OS sessions. The harness does not reboot machines.

![Campaign architecture](diagrams/campaign-architecture.png)

## Experiment results

The [results documentation](docs/results/README.md) contains reviewed experiment reports, raw measurement exports, JSON/CSV summaries and embedded PNG charts. Each experiment run can automatically generate and push a results branch and open a PR for review. Reports are merged using the repository's normal review process.

```bash
python scripts/report_experiment.py --experiment-dir results/campaign-EXAMPLE/experiments/EXPERIMENT_RUN --publish-pr
llm-eval publish-results --input results/campaign-EXAMPLE/experiments/EXPERIMENT_RUN/report --dry-run
```

## Documentation

- [Campaigns, hardware inventories, SSH execution and recovery](docs/CAMPAIGNS.md)
- [Report generation and results pull requests](docs/RESULTS.md)
- [Add a new experiment](docs/NEW_EXPERIMENT.md)
- [Original platform setup/run workflows](docs/WORKFLOWS.md)
- [LiveBench integration](docs/LIVEBENCH.md)
- [Model catalog](docs/MODELS.md), [platforms](docs/PLATFORMS.md), [methodology](docs/METHODOLOGY.md), [security](docs/SECURITY.md)

Existing `llm-eval run --config FILE`, `scripts/run.py --config FILE`, and platform/OS wrappers remain supported. Their original installation and local-inference defaults remain in place. Source, workloads and experiment settings must be pinned for meaningful comparisons.
