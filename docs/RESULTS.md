# Experiment reports and results pull requests

At the conclusion of an experiment run, the coordinator generates one report covering all its selected cases and hardware configurations. Failed/cancelled runs produce incomplete reports. A phase waiting for an OS or disconnected worker remains unfinished. Finalization runs when safe for local measurement isolation; remote experiments can finish/report while other remote workers continue.

```bash
python scripts/report_experiment.py --experiment-dir results/campaign-ID/experiments/RUN_ID
python scripts/report_experiment.py --experiment-dir results/campaign-ID/experiments/RUN_ID --publish-pr
llm-eval publish-results --input results/campaign-ID/experiments/RUN_ID/report --dry-run
llm-eval publish-results --input results/campaign-ID/experiments/RUN_ID/report
```

Install the `reporting` extra for PNG chart rendering. Legacy `llm-eval report --input DIR` still reads v1 measurement directories. Campaign reports use a separate versioned envelope; historical results are not rewritten.

## Outputs

The local `report/bundle/` mirrors the eventual repository layout:

| Destination | Contents |
|---|---|
| `docs/results/EXPERIMENT/PUBLICATION/README.md` | Status, hardware/platform coverage, metrics, chart and reproduction guidance |
| `raw/measurements.jsonl.gz` | Per-request records, telemetry, grades, configuration/provenance and attempt outcomes |
| `summary.json`, `summary.csv` | Job/category cohorts, counts, missing/error coverage, latency percentiles, decision accuracy/F1/confusion and other applicable metrics |
| `benchmark-summary.json`, `benchmark-summary.csv` | Upstream benchmark score tables with their original job/source cohorts; empty when no upstream tables exist |
| `manifest.json`, `resolved-config.json` | Input/provenance hashes, export inventory, filtering, checksums and reproducibility settings |
| `diagrams/results/EXPERIMENT/PUBLICATION/latency.png` | Chart embedded directly in the report |

Raw records retain warmups and every attempt. Summaries use the latest attempt of each job and exclude warmups. Synthetic measurements remain explicitly labeled. Upstream LiveBench judgments and CSV reports are separate raw record types; their scores are not recomputed as smoke-test pass rates. Report fingerprints and compressed exports are deterministic for unchanged source artifacts.

Decision accuracy measures the router's choice independently of a later generator failure. End-to-end success and answer pass rates retain those failures in their denominators. Latency percentiles describe successful requests, with error/missing counts alongside them.

Default exports omit credentials, endpoint/private path fields and prompt/answer bodies. `reporting.include_outputs: true` includes retained bodies when the workload's publication policy permits it. The manifest records removed fields. Preserve the original local artifacts; the public export is intentionally sanitized. Review results PRs before merging.

## Automatic publication

Configure a campaign with:

```json
{
  "reporting": {
    "on_experiment_end": true,
    "raw_format": "jsonl.gz",
    "summary_formats": ["markdown", "json", "csv"],
    "publish": {
      "mode": "pull-request",
      "repository": "asanderson/llm-eval",
      "base_branch": "main",
      "docs_root": "docs/results"
    }
  }
}
```

Set `GH_TOKEN` or `GITHUB_TOKEN` in the coordinator environment with repository contents/pull-request permissions. Tokens are never saved in campaign JSON. Git and the GitHub API use these credentials; publication has no `gh` dependency. `origin` must match the configured repository. Measurement workers do not need GitHub publication credentials.

The publisher validates file inventory/checksums and a configurable size limit (40 MiB by default), creates an isolated Git worktree, commits only the result bundle and results index/README links, pushes `results/EXPERIMENT/PUBLICATION`, and opens a PR. Incomplete runs open draft PRs. It never merges the PR or overwrites the user's working tree.

A retry finds an already pushed branch/open PR. Changed results add a commit to the same open results branch; an amendment after merge gets a new fingerprint-suffixed branch. Index regeneration preserves other reports from the current base. Conflicts outside the generated index stop publication for review. Pushes never force-update a shared branch.

Network/authentication failures retain the full local report, mark publication failed/pending, and can be retried with `publish-results` without rerunning models. Oversized bundles also remain local; the script never silently drops raw data or chooses an external upload service. Measurement success remains distinct from publication status.
