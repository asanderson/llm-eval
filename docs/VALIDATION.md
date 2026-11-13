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
- LM Studio (`lmstudio`) was added as the tenth platform: catalog/installer pins, all three OS wrapper pairs (60 wrappers, 28 eligible dry-run pairs), the `lms` supervisor with scripted-CLI tests for import/load/serve ordering, reuse of an existing daemon or import, version-mismatch and foreign-server aborts, cleanup after failed loads, readiness checks (pinned WinGet build on Windows only), and the 870-cell matrix. No LM Studio installation, daemon or model load has been executed in this container.
- Follow-up regressions cover per-model interactive defaults, case-sensitive local model routing, IPv6/prefixed API endpoints, complete finite judgment coverage (including valid zero scores), missing-result failure despite zero subprocess exit codes, and separate per-category CSV retention. All 36 Linux/WSL wrappers executed locally in dry-run mode from a path containing spaces. The pinned upstream model-config loader/API-name resolver was also exercised directly with a temporary local mapping; full LiveBench execution remains untested.

## Not measured or certified

- No access to the user's MSI laptop, physical RTX 5090 Laptop GPU, BIOS, driver, power profile, or SSD mounts.
- No real model inference, OOM/VRAM/RAM qualification, thermal run, or model-quality ranking.
- No native Windows/WSL execution in the development container; CI only exercises the portable harness, not GPU engines.
- No comprehensive security audit of the other nine engines is implied by their inclusion. LM Studio is a closed-source binary installed by the operator; only its MIT CLI is invoked.
- Accelerate/AirLLM workers are optional implementations that require their dependencies and per-model smoke tests. Multimodal inputs are not implemented; generated-code execution is confined to the explicit upstream LiveBench lane.
- Engine setup, explicit manifest downloads and managed server lifecycle are implemented but were not executed against real engines/GPU models in this development container. No target OS installation, driver change, OS tuning, cold-cache reset or concurrency sweep has been performed.
- Optional upstream LiveBench dependencies, Docker image, public question coverage and agentic task execution have not been validated end-to-end here. Upstream API/argument checks use the pinned source; orchestration tests use mocks. Installer pins are not a certification of current wheels or all model architectures.
- No empirical claim that any 120B candidate meets the 64 GiB RAM budget; these remain conditional.

## Acceptance gate on the laptop

For each claimed successful cell, retain: exact artifacts/revisions, engine/dependency versions, active template, observed OS/hardware, startup placement log, successful format/quality smoke, actual prompt/output token counts, stable repeated timings, RAM/VRAM peaks and paging status. WSL additionally requires Windows host memory observations. Explicitly classify missing sensors and unsupported combinations.

A benchmark request reaching an endpoint is not proof of the requested backend, model, quantization, or offload placement. Verify those facts independently from local startup/configuration evidence. The harness labels them as operator attestations.

## Legal benchmark (issue 45)

Recorded 2026-11-13, on the development host, for the `legal-benchmark` experiment and its [walkthrough](LEGAL_BENCHMARK_WALKTHROUGH.md). The statements and counts of the sections above are historical and unchanged. No model was served, no GPU was used, no campaign was set up or run on a target host, and no number produced by these checks is a measurement: every value in the legal tests comes from original fictional fixtures and a deterministic stand-in generator behind a scripted loopback test server. Host measurements are pending.

"No authorization to access private matter inputs or publish a results bundle is implied by this plan." "Do not run models on actual prosecution decisions or automate filing, charging, contact or evidence disclosure." "No public results promotion from private inputs, even aggregate metrics." "Run one campaign at a time on the Raider."

### What was verified and how

- CPU-only unit tests with fake loopback endpoints (`ThreadingHTTPServer` on `127.0.0.1` with an ephemeral port), temporary campaign directories, synthetic hosts and temporary Git repositories with a simulated GitHub API. Command, from the repository root, on Windows 11 with Python 3.12 and the repository's existing `.venv` (telemetry and reporting extras already installed; `pip install` was not run): `python -m unittest discover -s tests -v`. Final lines: `Ran 624 tests in 347.668s` and `OK (skipped=2)`.
- The same suite with `TEMP` and `TMP` set to an 8.3 short name of a shallow directory, as the Windows CI runner provides: `Ran 624 tests in 348.521s` and `OK (skipped=2)`.
- Skipped cases (both runs): `test_model_discovery.WorkflowTest.test_the_tracking_issue_is_one_the_workflow_created` ("jq is not installed; the filter text is checked above") and `test_readiness.WrapperTests.test_bash_wrapper_help_forwards_without_installing` ("Bash wrapper", skipped on Windows by design). Known failures: none.
- The workflow's matrix command `python -m llm_eval matrix --output OUTSIDE_DIR/matrix.csv` (a directory outside the repository): exit status 0, 930 combinations written.
- `python -m llm_eval experiments list` lists `legal-benchmark` with the modes `smoke`, `retrieval`, `generation`, `workflow` and `score`; `llm-eval plan` of `campaigns/legal-smoke.json` and of `configs/examples/legal/raider-windows/legal-evaluation-campaign.json` prints the plan and creates no file.
- `tests/test_legal_examples.py` checks, for the documents and examples of this section:
  - every legal example campaign plans with `publish.mode` `none`, without creating a file or opening a socket, and reserves exactly the host id of the generic Raider inventory; the two templates are refused with the code's message;
  - each per-host inventory has the target entry of `configs/examples/raider-<os>/inventory.json`; the existing Raider examples and `campaigns/routing-smoke.json` resolve as before; readiness infers no runtime for legal jobs;
  - the base install has no dependency, and every legal module imports without `psutil`, `matplotlib`, `pypdf` or `docx`;
  - the experiment README's mode table matches the registered modes and the report behaviour, and the hook table and path keys match the code;
  - every backticked snake_case token and every backticked or quoted message of the changed documents exists in the source, the experiment README or the plan sentences the test lists (messages built at run time by their fixed part);
  - every command line in a fence or inline parses with the real parser and is not executed; none publishes, writes under `docs/results` or `results`, or edits an inventory;
  - relative links and `#` anchors resolve; every block quote occurs verbatim in the experiment README; the four plan sentences are never paraphrased;
  - no box is ticked in any changed document; the human-gate sections hold only empty boxes and no line that reads as a recorded approval or acceptance (a closed pattern list: it catches "approved", "signed off", "accepted on", "passed on" or "reviewed on" followed by a date or a capitalised name, not every possible wording);
  - every host cell reads `not run`, every measurement row says pending, no legal prose line pairs a number with a rate or score word, and every fenced block with a digit is introduced as illustrative;
  - the diagram has the edges of the walkthrough, and re-rendering it gives the committed Mermaid source byte for byte and a PNG of the same size that differs by less than 2 % per pixel on average (skipped without matplotlib).
- Not run here: the repository's CI matrix (Ubuntu and Windows, Python 3.11, 3.12 and 3.13; the pull request runs it), Linux, Python 3.11 and 3.13, `python -m pip install -e ".[telemetry,reporting]"` in a fresh environment.

No test downloads anything or calls a paid API, and operators who skip the legal benchmark need nothing new: `pyproject.toml` still has `dependencies = []` and exactly the `telemetry` and `reporting` extras.

### Behaviour outside the legal benchmark

Two changes reach the other experiments; both are refusals. A generic bundle of any experiment is refused by `publish-results` when it carries category `legal`, a benchmark name that starts with `legal` after normalisation (which includes `LegalBench`), a legal task id, or legal row or manifest keys (`Publication identity mismatch: the bundle carries content of legal-benchmark (<class>)`). A worker refuses remote collection of a path when a `job.json` at or above it does not name its experiment (`Collection refused by data policy: <path>`). The published bundles of the other experiments are not changed, re-hashed or blob-checked. A report the generic layer may not build is recorded as `disabled` with its reason (`Report generation is disabled` when built by hand).

### What was not measured

Every comparison of the plan's "Proposed first measurements and stop criteria" is a host measurement and is pending. Parts of two rows are not host measurements; they were delivered as code or fixtures, or are gated for another reason.

| Stage | State | Delivered as code or fixtures | Gated for another reason |
|---|---|---|---|
| Windows fit | pending (host) | none | none |
| Retrieval and drafting | pending (host) | "No fabricated or ineligible authority may be marked supported in fixture acceptance": `test_scorer_rejects_ungrounded_and_misstated_outputs`, `test_reference_failures_are_scored_not_schema_errors`, `test_fabricated_citation_is_a_critical_error_not_a_parse_failure`. Paired wrong-version and unsupported-claim rates, all-pass, per-axis results, abstention, uncertainty and failures: `grading.aggregate`, `grading.paired_difference` and `legal-summary.json` (the numbers need a served generator). Critical errors escalate to review: a row with a critical error stays `pending_human_review` until every critical code is adjudicated | The 12 calibration and 24 evaluation matter families (fixture authoring; their gold rubric is the qualified legal reviewer's pilot rubric). The adjudication itself is a human gate |
| Routing | pending (host) | "no increase in material unsafe commitment" at "an agreed quality floor": `routing.risk_coverage` and the unsafe-commitment columns of `routing.evaluate` (the comparison needs measured candidates) | A selector adoption decision needs measured candidates on held-out matters |
| WSL2 and native Ubuntu 26.04 | pending (host) | none | none |

The shipped suites are two small disjoint fixture splits, `original-smoke` (8 families, `split_id: smoke`) and `original-packets` (2 families, `split_id: calibration`); they are not the plan's evaluation set.

### Host readiness and acceptance

| Host cell | Readiness | Offload qualification | Legal evaluation | Sustained load probe |
|---|---|---|---|---|
| Windows 11 native | `not run` | `not run` | `not run` | `not run` |
| WSL2 Ubuntu 26.04 | `not run` | `not run` | `not run` | `not run` |
| Native Ubuntu 26.04 | `not run` | `not run` | `not run` | `not run` |

The offload harness records no structured observed placement, so a locked serving profile carries the placement as an operator attestation (`nature: attested`, from `profiles freeze --observed-placement`); an unattested profile is `inconclusive` (`placement_unobserved`) and cannot qualify a role, and an attested placement that differs from the requested one fails it (`placement_mismatch`). On Windows 11 native and in WSL, paging needs the operator attestation too (`paging_unknown` without it). Every qualified role is therefore `qualified_by_attestation: true`.


Host locks, as the code has them: the legal examples name the target `raider` with `physical_host_id: raider`, like every other Raider example, so their campaigns and the other Raider campaigns exclude each other. The coordinator's reservation always uses the default lock directory of the account that runs it and ignores the target's `lock_root` (`orchestration/scheduler.py`, `orchestration/setup.py`); the worker's reservation uses the target's `lock_root`. Across native Windows and WSL only the worker lock coordinates, and only when both inventories name the same physical directory, as [the WSL walkthrough](WSL_RAIDER_WALKTHROUGH.md#share-the-windows-physical-host-reservation) describes.

### Gated plan requirements

| Plan requirement | Plan sentence | Gated by | Reason | What lifts it |
|---|---|---|---|---|
| Managed serving of legal roles | "Require explicit external versus managed mode." | package C, `profiles.MANAGED_SERVING_ENABLED` (`False`) | `managed` is refused at plan time (`Managed serving of legal roles is gated`); this effort may not launch a serving harness. Settled by the integration owner: the gate stays | A reviewed change that binds a role's launch settings to the shared launcher and flips the constant |
| The hosted decision arm | "An optional hosted Jev arm requires separately approved public-only inputs, a pinned endpoint/model and the same calibration/abstention checks." | package E | Every legal role is local (`Legal roles must be local`) and requests go only to the job's allowlist; an approval typed into a case by its author is not a separate approval | An approved-list entry with an explicit off-host flag (a reviewed change) and a pinned selector role |
| Tev1 and Nimble selectors | "Start with a rule and fixed model, add Tev1/Nimble SystemOne after protocol and memory qualification." | package E | They need served selectors after protocol and memory qualification; the `systemone` router kind is tested against a loopback fake only | Target-host qualification of the selectors |
| A generator comparison and a verifier cascade | "Only then compare generators or a verifier cascade." | package E | They need measured candidates; no verifier cascade is built | Measured candidates on the target host |
| Real DOCX, PDF and OCR backends | "Enable DOCX/PDF text extraction only through optional pinned dependencies." "Make scan/OCR a deliberate later capability with original-page anchoring and human verification of material excerpts." | package B | No backend is pinned in `capabilities.json`; such files are `unsupported` and scanned pages block the lock | A backend pinned with its exact version, as a reviewed change |
| A real public dataset import with its five gates (`bytes`, `license`, `jurisdiction`, `split`, `grader_parity`) | "First import one released public diagnostic only after dataset bytes, license, jurisdiction, split and grader expectations are verified." | package B | Nothing is downloaded; a suite with an unverified gate does not load | An operator verifies each gate on real local bytes (`benchmarks gate`, `benchmarks parity`) |
| The eCFR, LegalReasonBench and Harvey adapters | "Prefer a temporal eCFR release if accessible." "Keep LegalReasonBench/Harvey packet imports as optional separate adapters." | package B | Registered and gated: their release formats cannot be verified offline | Verification against real release bytes |
| The 12 calibration and 24 evaluation matter families | "Use a proposed 12 calibration matter families and 24 untouched evaluation families, balanced across supported, contradicted and incomplete scenarios, with matched dated/venue/evidence variants." | package B, qualified legal reviewer | Their gold rubric is the pilot rubric. Settled by the integration owner: the two small splits ship, these sets stay gated | Authoring and approval by the qualified legal reviewer |
| A counsel-supplied policy profile for a real jurisdiction | "Use a counsel-supplied policy profile for any operative jurisdiction or prosecutorial standard." | package C | Only the fictional fixture policy is built in; any other corpus does not load without a profile | Counsel supplies and reviews the profile |
| Validated human or judge scoring | "Treat semantic entailment, admissibility, defense arguments and sufficiency as separate rubric dimensions requiring validated human/judge scoring." | package D | The four semantic dimensions stay `pending`; no judge model is called | A validated review process (review files of a qualified reviewer, or a validated judge) |
| Publication of any legal result bundle | "No authorization to access private matter inputs or publish a results bundle is implied by this plan." | package F | No publication is authorized by the plan | A separately authorized `reporting authorize` step and a reviewed pull request |
| Any private pilot | "Phase 3 private matter requires its own operator and counsel approval, local-only staging, and an independently tested publication/transport gate." | the plan | A private pilot is a separate decision | That separate decision |

Two further questions were settled by the integration owner and are built: a bundle of another experiment that carries a legal benchmark name is refused by `publish_report`; the plan drift check refuses a changed stored plan (`Campaign plan changed; create a new campaign`) and nothing else, so campaigns of the other experiments written before it resume and report as before.

### Known limits

The limits of the gates are stated in the [experiment README](../experiments/legal-benchmark/README.md#classification-gates-and-the-report-projection). Quoted from it:

> A consistent forgery of `campaign.json` together with the attempt files and the output manifest also passes the receipt checks.

> Authentication of `plan.json` with a key is not built.

> Differencing is not prevented: two reduced runs over overlapping subsets (five matters and the same five plus a sixth) can be subtracted to give the sixth matter's result.

> An unreserved role `resource_host` is refused at run start, not at plan time.

> An attempt in a campaign written before this package therefore cannot be scored, replayed or used for calibration in place (copy it out, or re-run it); a smoke campaign of that age still resumes and gets its local report, and cannot be published.

One limit recorded by the review of the publication gates and not in the README: a replay export with renamed ids and a foreign `suite_sha256` is not recognised as legal content by `publish-results`.

### Independent engineer review

Open. Nothing in this repository records this review.

- [ ] Data separation between the candidate, oracle, grader and review sets (the candidate view, retrieval of shared sources, the reference arm, the verifier without the rubric).
- [ ] Remote transfer and collection gates (plan time, scheduler, worker, both sides of collection, the `job.json` rule).
- [ ] Publication gates and authorization (`verify_publication` in order, the upstream approved list, receipts, the rebuilt bundle, the authorization file, protected paths).
- [ ] Attempt semantics: resume, retries, score lineage (output manifests, receipts, review binding).
- [ ] Canonical bytes on a Windows-to-Git path (LF, `-text` for `*.gz`, the staged and committed blob checks).

### Qualified legal reviewer

Open. Nothing in this repository records this review.

- [ ] The pilot gold rubric, including the 12 calibration and 24 evaluation matter families that are not authored yet.
- [ ] Authority snapshots and the policy profile of any corpus that is not the fictional fixture.
- [ ] Material-error adjudication (one adjudication per critical code of each reviewed item).
- [ ] Memo evaluation (the [human rubric review checklist](LEGAL_BENCHMARK_WALKTHROUGH.md#human-rubric-review-checklist), per memo).

### Target-host acceptance

Open, per host cell (Windows 11 native, WSL2 Ubuntu 26.04, native Ubuntu 26.04).

- [ ] Readiness recorded per host, with the JSON report kept.
- [ ] On Windows PowerShell 5.1, the documented Python readiness fallback (`python scripts/readiness.py`) used if the probe misreports Python.
- [ ] LM Studio artifacts preimported and readiness awaited before any measurement that uses LM Studio.
- [ ] AC power, a fixed MUX and fan profile, recorded.
- [ ] Cold and warm conditions separated.
- [ ] One campaign at a time on the Raider.
- [ ] A single active large model per Raider: every chat and selector role of a job names the same deployment on that host (the software does not enforce this).
- [ ] The observed placement attested when the serving profile is frozen.
- [ ] Every role qualified by a locked serving profile whose probe passed.
- [ ] Missing or skipped host cells marked explicitly in the table above.

The plan's condition for the pilots, quoted from issue 45: "Software smoke is complete at A, the public pilot only when A–G gates are evidenced, and a private pilot is a separate decision." None of these gates is evidenced here.
