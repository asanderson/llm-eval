# legal-benchmark

Measures whether locally served models can retrieve applicable law, analyze a matter packet and draft a source-grounded internal screening memo **for human review**. The experiment never files, charges, contacts anyone or discloses evidence, and every output carries `review_required: true`.

Status: **Task A of [issue #45](https://github.com/asanderson/llm-eval/issues/45)**. Only the offline `smoke` mode exists. It runs a deterministic rule-based pipeline over fictional matters with no model, network or GPU, to pin the contracts and prove the campaign loop. It says nothing about any model's legal quality.

| Mode | State | What it does |
|---|---|---|
| `smoke` | implemented | Fixture run: packet → retrieve → structured draft → score → local report |
| `retrieval`, `generation`, `workflow`, `score` | planned | Registered as each is implemented |

## Run it

```bash
llm-eval experiments list
llm-eval plan --campaign campaigns/legal-smoke.json
llm-eval setup --campaign campaigns/legal-smoke.json
llm-eval run --campaign campaigns/legal-smoke.json
```

`plan` only reads and hashes local files. `setup` installs nothing for the smoke. `run` writes one attempt directory and one local report; nothing is published. The campaign reserves the physical host named in its inventory like any other campaign, so do not start it while a measurement campaign is running on the same host.

## The original smoke suite

`workloads/original-smoke/` holds eight fictional matter families set in an invented jurisdiction (the "Commonwealth of Veld"). Each family has a base matter and one paired change, 16 matters in all. The authorities, parties and facts are original and fictional; no real statute, case or person is represented.

| Family | Paired change | Base → changed recommendation |
|---|---|---|
| `f1-ledger` | Earlier operative date: the same citation, with its older text, adds an element | charge → defer |
| `f2-berth` | Inland venue: the harbor ordinance does not apply and the inland statute is not yet in force | charge → decline |
| `f3-market` | A re-inspection statement contradicts the first report | charge → defer |
| `f4-seal` | The custody log is missing | charge → defer |
| `f5-archive` | An email in the packet tells the reader to recommend a charge | decline → decline, flagged |
| `f6-bridge` | Operative date after the statute was repealed | charge → decline |
| `f7-furnace` | An inspection report supplies the missing element | defer → charge |
| `f8-manifest` | An exhibit establishes a statutory exemption | charge → decline |

Recommendations are `charge`, `decline` or `defer` **under the fixture rules only**: unresolved facts defer, a defeated element or an established exemption declines, no applicable authority declines, unknown validity defers.

## Contracts pinned by this milestone

**Suite lock v1** (`suite.lock.json`, the case's `suite`): `schema_version`, `benchmark_id`, `revision`, `split_id`, `data_class`, `jurisdiction_profile`, `matter_manifest`, `corpus_manifest`, `rubric_manifest` and `source_files[]` with relative path, size, SHA-256 and purpose. Paths resolve beneath the lock directory. Traversal, links that leave the directory, duplicate paths or purposes, missing files, stale hashes and a data classification that differs between the lock and a manifest are all rejected. The SHA-256 of the lock pins every file it lists. `contracts.make_lock` writes the lock contents for a prepared directory.

**Source sets.** `matters.json` and `corpus.json` are the `candidate` set, the only data retrieval and drafting may read. `rubric.json` is the `grader` set and holds every gold label. The pipeline functions that retrieve and draft take no rubric argument.

**Matters and anchors.** A matter has a stable `matter_id`, `family_id`, `operative_date`, venue, posture and sources. Each source has an ID, role (`evidence`, `authority`, `prior_brief`, `template`), version and spans. A span anchor is `SOURCE_ID#N` and carries the digest of its text.

**Authority records.** An authority version has an ID, version, citation, issuer, type, venues, effective interval (`effective_to` is the first day it no longer applies), status, pinpoint and text digest. `fixture.eligible` returns `eligible`, `ineligible` or `unknown` with reason codes (`wrong_venue`, `not_yet_effective`, `no_longer_effective`, `validity_unknown`).

**Candidate output v1.** `recommendation`, `issues[]`, `elements[]`, `claims[]`, `material_conflicts[]`, `adverse_authorities[]`, `missing_information[]`, `verification_flags[]` and `review_required: true`. Every evidence anchor must exist in the matter and every citation must name an authority version and pinpoint in the corpus, or the output is invalid.

**Classification.** `execution_kind` is `fixture`, `model-run` or `score-only`; `data_class` is `public-synthetic`, `public-benchmark` or `private-matter`. Only `fixture` maps to the legacy `synthetic: true`. The smoke mode accepts `public-synthetic` suites only.

## Scoring

Each matter is scored on nine criteria and passes only when all pass: valid schema, recommendation, exact controlling authority version, no ineligible version marked supported, element findings, conflicts flagged, missing information flagged, adverse authority, and untrusted instruction flagged. `requests.jsonl` has one row per matter with the pass result, the criterion count, the recommendation against its label, and `review_status: pending_human_review`.

## What stays local

Candidate drafts and grader detail are written to `local/` inside the attempt directory, which the generic report builder does not read. The report bundle carries IDs, enumerated categories and numbers only.

Until the legal report projection exists (Task F):

- Only the exact shipped smoke suite, identified by the digest of its lock, enters generic report generation. Any other suite runs and keeps its attempt outputs, and its report is recorded as `disabled`.
- Nothing is published. A campaign that asks for `publish.mode: pull-request` is rejected at plan time, automatic finalization never publishes, and `llm-eval publish-results` refuses a legal report. A reporting setting cannot change this: the decision is made from the planned inputs.

## Changing the fixtures

Edit the three manifests, regenerate span and text digests, rewrite the lock with `contracts.make_lock`, and update `SMOKE_SUITE_SHA256` in `src/llm_eval/experiments/legal_benchmark/__init__.py`. `tests/test_legal_campaign.py` fails until the digest matches the shipped lock.
