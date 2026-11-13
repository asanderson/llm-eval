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

Each report lists its configuration coverage and measurements **by harness and model** (the serving platform and the model it serves or routes with); the opaque job ID is kept as the last column.

## Navigating published results

[`docs/results/README.md`](results/README.md) is the entry point. It opens with the executive summary (the three best harness and model combinations per experiment for each hardware configuration, a comparison chart for each, and the conclusions per hardware configuration), followed by the navigation index, the detailed results and the list of published reports.

`llm-eval index-results` regenerates everything derived from the published bundles: `docs/results/index/` (one page per hardware configuration, experiment, harness, model and UTC date, and an overview), the summary charts in `diagrams/results/summary/` (one per experiment and hardware configuration with at least two ranked combinations; needs the `reporting` extra), and three marked blocks of the results README: `results-top` (ranking and charts), `results-index` (browse links and a models-by-harness matrix per experiment whose cells link to every published run) and `results-list` (every report, newest first). Text outside the `<!-- results-*:start -->` and `<!-- results-*:end -->` markers is hand-written and left untouched. The publisher runs the same step, so a results PR carries the updated indexes. Never edit the generated pages by hand.

Raw records retain warmups and every attempt. Summaries use the latest attempt of each job and exclude warmups. Synthetic measurements remain explicitly labeled. Upstream LiveBench judgments and CSV reports are separate raw record types; their scores are not recomputed as smoke-test pass rates. Report fingerprints and compressed exports are deterministic for unchanged source artifacts.

Decision accuracy measures the router's choice independently of a later generator failure. End-to-end success and answer pass rates retain those failures in their denominators. Latency percentiles describe successful requests, with error/missing counts alongside them.

Default exports omit credentials, endpoint/private path fields and prompt/answer bodies. `reporting.include_outputs: true` keeps the body fields (`messages`, `prompt`, `output`, `text`, `response`, `question`, `answer`, `choices`, `explanation`, `reasoning`, `completion`) in the raw records of the generic scan; no workload publication policy is consulted, and credentials, endpoints and private path fields are removed either way. It changes nothing for an experiment with a report projection, such as `legal-benchmark`. The manifest records removed fields. Preserve the original local artifacts; the public export is intentionally sanitized. Review results PRs before merging.

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

## Legal benchmark reports

**No legal result bundle has been published, and none is published automatically.** "No authorization to access private matter inputs or publish a results bundle is implied by this plan." The rules are stated once, in the [experiment README](../experiments/legal-benchmark/README.md#classification-gates-and-the-report-projection); this section quotes them or links to them, and the [walkthrough](LEGAL_BENCHMARK_WALKTHROUGH.md) shows where each applies.

**Projection instead of the generic scan.** A `legal-benchmark` report is built by the plugin's `report_projection`, never by the scan of the attempt directories described above; `reporting.include_outputs` changes nothing for it.

> A legal report is the projection, never the generic scan: a strict recursive allowlist of enumerated categories, opaque ids, hashes, versioned numbers, approved settings, coverage and coarse status.

**Layout.** `report/` holds `publication.json` and `bundle/`; the seven bundle files (`README.md`, `manifest.json`, `summary.json`, `summary.csv`, `resolved-config.json`, `legal-summary.json`, `raw/measurements.jsonl.gz`) are under `bundle/docs/results/legal-benchmark/PUBLICATION_ID/`. There is no chart and no benchmark summary.

**Exact fixture export and reduced projection.** Which rows leave, and how a suite outside the approved list is reduced, is stated under "The projection" in the README.

> Per-matter rows leave for the `smoke` mode only: exactly, for an approved suite with `fixture_export` (its matter ids and `expected_choice` are fixture data), and reduced otherwise (ids replaced by salted pseudonyms from `projection-salt` beside `experiment.json`, which never enters a bundle; scenarios become `all`; decision, quality, hash and token keys dropped; the strings of the lock omitted).

**Small cohorts.** The rule is in the README under "Small cohorts" (`MIN_COHORT`: fewer than 5 distinct matters).

> Differencing is not prevented: two reduced runs over overlapping subsets (five matters and the same five plus a sixth) can be subtracted to give the sixth matter's result.

**Canonical bytes.** The byte format and the staged and committed blob checks, which apply to projected bundles only, are stated under "The projection" and "Publication" in the README; the historical bundles of the other experiments are not blob-checked.

**Cohorts and the index.** `llm-eval index-results` classifies each job of a projected bundle as `fixture`, `measured` (execution kind `model-run`) or `score-only`; a bundle with more than one experiment identity is `invalid`, and a bundle of a projected experiment without the projection is `legacy`; neither is ranked. Legal results stay out of the generic top-combinations ranking (`GENERIC_RANKING = False`) and appear in their own "Results by class and cohort" section. What a cohort covers is listed under "The projection" in the README.

**Classification and gates.** One classification (`approved`, `declared`, `refused`) decides what a legal job may do, and six gates enforce it; see the README and the messages in the [walkthrough](LEGAL_BENCHMARK_WALKTHROUGH.md#trust-boundaries).

**Manual publication.** `publish.mode: pull-request` is refused at plan time for a legal campaign (`automatic_publication_unavailable`). `llm-eval publish-results` publishes a legal report only when `reporting.verify_publication` passes; its codes, in the order it checks them: `provenance_missing`, `legacy_report`, `plan_changed`, `unverified`, `not_approved`, `not_approved_upstream`, `receipt_mismatch`, `bundle_mismatch`, `not_authorized`. The README states each check under "Publication".

> A report manifest's own labels authorize nothing.

**Bundles of other experiments.** A routing or offload bundle built from a legal export is refused by `publish-results` when it carries a legal benchmark name (`Publication identity mismatch: the bundle carries a legal benchmark name`) or legal content the plugin recognises (`Publication identity mismatch: the bundle carries content of legal-benchmark (<class>)`), and a report below a campaign directory whose record names the legal experiment is refused too (`Publication identity mismatch: the campaign record names legal-benchmark`). The content check has limits: see [Known limits](VALIDATION.md#known-limits).

**Two behaviour changes outside the legal benchmark.** They are listed in [VALIDATION.md](VALIDATION.md#behaviour-outside-the-legal-benchmark): generic bundles with legal marks are refused, and a `job.json` without `experiment_id` at or above a collected path refuses collection.

**Threat model.** As the README states it:

> The gates stop mistakes, lazy relabels and partial edits by an operator, and let no unapproved or private suite's numbers out through this code without a deliberate forgery of several files. They do not stop a person who rewrites every file by hand.

> Review of the publication pull request is the remaining control.
