# Experiment reports and results pull requests

At the conclusion of an experiment run, the coordinator generates one report covering all its selected cases and hardware configurations. Failed/cancelled runs produce incomplete reports. A phase waiting for an OS or disconnected worker remains unfinished. Finalization runs when safe for local measurement isolation; remote experiments can finish/report while other remote workers continue.

```bash
python scripts/report_experiment.py --experiment-dir results/campaign-ID/experiments/RUN_ID
python scripts/report_experiment.py --experiment-dir results/campaign-ID/experiments/RUN_ID --publish-pr
llm-eval publish-results --input results/campaign-ID/experiments/RUN_ID/report --dry-run
llm-eval publish-results --input results/campaign-ID/experiments/RUN_ID/report
```

Install the `reporting` extra for PNG chart rendering. Legacy `llm-eval report --input DIR` still reads v1 measurement directories. Campaign reports use a separate versioned envelope; historical results are not rewritten.

First-time contributors can prepare a local results branch, review it, and open a pull request from a personal fork. See [Contributing a measurement or reporting a failure](../CONTRIBUTING.md).

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

The [results overview](results/README.md) links findings to the measured workload, hardware, execution class and supporting jobs. The [setup evidence](results/index/recommended/README.md) pages distinguish direct comparisons within a matched protocol from evidence that can only support a single observation. Hardware-fit estimates, measured service timings, synthetic checks and legal cohorts each have their own interpretation. See the [reproduction guide](REPRODUCE.md) to inspect a bundle and check its recorded inputs.

Run `llm-eval index-results` to regenerate `docs/results/index/`, including hardware, experiment, harness, model and date pages, the setup evidence and comparison manifests. The command also updates summary charts under `diagrams/results/summary/`, the three generated blocks of the results README, and the findings block of the repository README. The publisher stages these changes with the bundle. Both README summaries list every published job by hardware configuration and experiment. A model and harness can appear more than once when the archive contains reruns. The status, evidence type, publication date and job ID identify each observation.

## Verify a fresh clone

```bash
python -m llm_eval verify-results
```

The command checks the file inventory of every committed bundle, including charts, and compares checkout bytes to the Git object IDs in HEAD. It validates each manifest fingerprint and every file SHA-256. A nonzero exit identifies the first unexpected change. This verifies the published bytes. It does not establish the accuracy of a measurement or recover an unavailable model or runtime.

At archive revision `ee8c7b56f09adc9ef83007ecd27534e33175b928`, 95 manifests listed 744 files. **493 files matched their manifest directly.** Another **251 files in 87 bundles** had been hashed with CRLF before Git committed LF. Restoring CRLF reproduced all 251 original SHA-256 values. The [versioned compatibility map](result-integrity-v1.json) records each exact path, original SHA-256, committed blob ID, and checkout SHA-256, and pins the historical manifest objects. The verifier checks the map's own digest and accepts only these exact historical pairs. The other eight bundles had zero discrepancies. Historical manifests, raw records and charts retain their original bytes.

New public reports serialize JSON, Markdown and CSV with UTF-8 and LF. Both contribution routes check the exact staged and committed files against the validated manifest before any push. Newly prepared reports receive no historical exception. If an unpublished report from an older harness fails the blob check, rebuild the local report from its experiment directory with `llm-eval report --input EXPERIMENT_DIR`, inspect the regenerated export, and retry.

Raw records retain warmups and every attempt. Summaries use the latest attempt of each job and exclude warmups. Synthetic measurements remain explicitly labeled. Upstream LiveBench judgments and CSV reports are separate raw record types; their scores are not recomputed as smoke-test pass rates. Report fingerprints and compressed exports are deterministic for unchanged source artifacts.

Decision accuracy measures the router's choice independently of a later generator failure. End-to-end success and answer pass rates retain those failures in their denominators. Latency percentiles describe successful requests, with error/missing counts alongside them.

Default exports omit credentials, endpoint/private path fields and prompt/answer bodies. `reporting.include_outputs: true` keeps the body fields (`messages`, `prompt`, `output`, `text`, `response`, `question`, `answer`, `choices`, `explanation`, `reasoning`, `completion`) in the raw records of the generic scan; no workload publication policy is consulted, and credentials, endpoints and private path fields are removed either way. It changes nothing for an experiment with a report projection, such as `legal-models`. The manifest records removed fields. Preserve the original local artifacts; the public export is intentionally sanitized. Review results PRs before merging.

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

The publisher validates staged and committed bundle files against the manifest, checks a configurable size limit (40 MiB by default), creates an isolated Git worktree, commits only the result bundle, the generated index and charts, and the generated blocks of the results README and the repository README, pushes `results/EXPERIMENT/PUBLICATION`, and opens a PR. Incomplete runs open draft PRs. It never merges the PR or overwrites the user's working tree.

A retry finds an already pushed branch/open PR. Changed results add a commit to the same open results branch; an amendment after merge gets a new fingerprint-suffixed branch. Index regeneration preserves other reports from the current base. Conflicts outside the generated index, charts and README blocks stop publication for review; a conflicting README is taken from the base and its blocks are regenerated. Pushes never force-update a shared branch.

Network/authentication failures retain the full local report, mark publication failed/pending, and can be retried with `publish-results` without rerunning models. Oversized bundles also remain local; the script never silently drops raw data or chooses an external upload service. Measurement success remains distinct from publication status.

## Legal models reports

**Eight legal result bundles have been published, none automatically.** Four are the `generation`, `workflow`, `score` and `retrieval` runs of the approved public-synthetic fixture suite `legal-original-smoke` on the Windows host, run on 2026-11-15 and published on 2026-11-17. The other four are the same four runs in WSL2 on the same machine, run on 2026-11-18; the conditions of their serving are in the [results README](results/README.md#legal-benchmark-in-wsl2-of-2026-11-18). The [legal-models index](results/index/experiment/legal-models.md) lists all eight. Each needed its own authorization of the run, recorded from the operator's written instruction. No bundle holds private matter. Human review of their outputs is pending. A correction from that review is a new bundle with its own authorization and pull request. The plan stays as written: "No authorization to access private matter inputs or publish a results bundle is implied by this plan." The rules are stated once, in the [experiment README](../experiments/legal-models/README.md#classification-gates-and-the-report-projection); this section quotes them or links to them, and the [walkthrough](LEGAL_MODELS_WALKTHROUGH.md) shows where each applies.

**Projection instead of the generic scan.** A `legal-models` report is built by the plugin's `report_projection`, never by the scan of the attempt directories described above; `reporting.include_outputs` changes nothing for it.

> A legal report is the projection, never the generic scan: a strict recursive allowlist of enumerated categories, opaque ids, hashes, versioned numbers, approved settings, coverage and coarse status.

**Layout.** `report/` holds `publication.json` and `bundle/`; the seven bundle files (`README.md`, `manifest.json`, `summary.json`, `summary.csv`, `resolved-config.json`, `legal-summary.json`, `raw/measurements.jsonl.gz`) are under `bundle/docs/results/legal-models/PUBLICATION_ID/`. There is no chart and no benchmark summary.

**Exact fixture export and reduced projection.** Which rows leave, and how a suite outside the approved list is reduced, is stated under "The projection" in the README.

> Per-matter rows leave for the `smoke` mode only: exactly, for an approved suite with `fixture_export` (its matter ids and `expected_choice` are fixture data), and reduced otherwise (ids replaced by salted pseudonyms from `projection-salt` beside `experiment.json`, which never enters a bundle; scenarios become `all`; decision, quality, hash and token keys dropped; the strings of the lock omitted).

**Small cohorts.** The rule is in the README under "Small cohorts" (`MIN_COHORT`: fewer than 5 distinct matters).

> Differencing is not prevented: two reduced runs over overlapping subsets (five matters and the same five plus a sixth) can be subtracted to give the sixth matter's result.

**Canonical bytes.** The legal plugin specifies the byte format of its projection under "The projection" in the experiment README. Both generic and projected publications verify staged and committed Git blobs. `verify-results` checks the published archive against the historical compatibility map described above.

**Cohorts and the index.** `llm-eval index-results` classifies each job of a projected bundle as `fixture`, `measured` (execution kind `model-run`) or `score-only`; a bundle with more than one experiment identity is `invalid`, and a bundle of a projected experiment without the projection is `legacy`; neither is ranked. Legal results stay out of the generic top-combinations ranking (`GENERIC_RANKING = False`) and appear in their own "Results by class and cohort" section, one row per job: the row lists every cohort of the job, and its count is the job's total over all of them, because the summary rows of a job name no cohort. Per-cohort numbers are in the linked report. What a cohort covers is listed under "The projection" in the README.

**Classification and gates.** One classification (`approved`, `declared`, `refused`) decides what a legal job may do, and six gates enforce it; see the README and the messages in the [walkthrough](LEGAL_MODELS_WALKTHROUGH.md#trust-boundaries).

**Manual publication.** `publish.mode: pull-request` is refused at plan time for a legal campaign (`automatic_publication_unavailable`). `llm-eval publish-results` publishes a legal report only when `reporting.verify_publication` passes; its codes, in the order it checks them: `provenance_missing`, `legacy_report`, `plan_changed`, `unverified`, `not_approved`, `not_approved_upstream`, `receipt_mismatch`, `bundle_mismatch`, `not_authorized`. The README states each check under "Publication".

> A report manifest's own labels authorize nothing.

**Bundles of other experiments.** A routing or offload bundle built from a legal export is refused by `publish-results` when it carries a legal benchmark name (`Publication identity mismatch: the bundle carries a legal benchmark name`) or legal content the plugin recognises (`Publication identity mismatch: the bundle carries content of legal-models (<class>)`), and a report below a campaign directory whose record names the legal experiment is refused too (`Publication identity mismatch: the campaign record names legal-models`). The legal benchmark names are the plugin's own (`legal-smoke`, `legal-routing`, `legal-shaped` and the benchmark ids of approved suites): a public legal benchmark under a generic experiment, such as a `model-offloading` or `decision-models` bundle that measures `LegalBench`, is publishable, and a bundle that carries one of the plugin's own names or other legal content is refused. The content check has limits: see [Known limits](VALIDATION.md#known-limits).

**Two behaviour changes outside the legal models experiment.** They are listed in [VALIDATION.md](VALIDATION.md#behaviour-outside-the-legal-models-experiment): generic bundles with legal marks are refused, and a `job.json` without `experiment_id` at or above a collected path refuses collection.

**Threat model.** As the README states it:

> The gates stop mistakes, lazy relabels and partial edits by an operator, and let no unapproved or private suite's numbers out through this code without a deliberate forgery of several files. They do not stop a person who rewrites every file by hand.

> Review of the publication pull request is the remaining control.
