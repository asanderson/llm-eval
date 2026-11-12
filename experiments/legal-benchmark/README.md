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

Matter, source and span ids are opaque: `<family_id>-a` and `<family_id>-b` (which of the two is the base matter varies by family), `<matter_id>-s<n>` and `<source_id>#<n>`. Source kinds (`report`, `statement`, `record`, `message`) each occur in at least three families. Nothing a candidate sees names the scenario, the variant or the expected answer.

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

**Suite lock v1** (`suite.lock.json`, the case's `suite`): `schema_version`, `benchmark_id`, `revision`, `split_id`, `data_class`, `jurisdiction_profile`, `matter_manifest`, `corpus_manifest`, `rubric_manifest` and `source_files[]` with relative path, size, SHA-256 and purpose. Paths resolve beneath the lock directory. Traversal, links that leave the directory, duplicate paths or purposes, missing files, stale hashes and a data classification that differs between the lock and a manifest are all rejected. `schema_version` must be the integer 1, `revision` matches `[A-Za-z0-9][A-Za-z0-9._-]{0,63}`, and a duplicated JSON key in the lock or a manifest is an error. Each manifest is parsed from the very bytes whose digest the lock records, and a wrong JSON type anywhere is a `ValueError`, never a traceback. The SHA-256 of the lock pins every file it lists. `contracts.make_lock` returns the lock contents for a prepared directory as a dict; the caller writes it.

**Source sets.** `matters.json` and `corpus.json` are the `candidate` set, the only data retrieval and drafting may read. `rubric.json` is the `grader` set and holds every gold label. The pipeline functions that retrieve and draft take no rubric argument, and `contracts.candidate_view(suite)` (lock, lock digest, corpus and matters; its lock lists only the matter and corpus files, without the size and digest of the rubric; `lock_sha256` is still the digest of the full suite lock, not of the filtered `view['lock']`, so the view's lock must not be re-verified against it) is the only suite object candidate-side code receives.

**Matters and anchors.** A matter has a stable `matter_id`, `family_id`, `operative_date`, venue, posture and sources. Each source has an ID, role (`evidence`, `authority`, `prior_brief`, `template`), version, `kind` (required, free text, read by no code) and spans. A span anchor is `SOURCE_ID#N` and carries the digest of its text. Only spans of `evidence` sources anchor a finding.

**Authority records.** An authority version has an ID, version, citation, issuer, type, venues, effective interval (`effective_to` is the first day it no longer applies), status (`in_force`, `superseded`, `repealed`, `unknown`, `invalidated`), pinpoint and text digest. `fixture.eligible` returns `eligible`, `ineligible` or `unknown` with reason codes (`wrong_venue`, `not_yet_effective`, `no_longer_effective`, `obsolete_status` for `invalidated`, `validity_unknown`); `fixture.decide` is the one decision the drafter, the scorer and `fixture.check_gold` share. The corpus also accepts the optional keys `policy` and `availability_cutoff` and, per authority, `original_sha256`, `jurisdiction`, `court`, `weight`, `aliases`, `snapshot`, `review` and `status_as_of`; they are type-checked and otherwise ignored until later milestones give them a meaning.

**Rubric.** Each gold entry also carries `variant` (`base` or `paired`), `evidence_spans` (per element, the spans that support and the spans that negate it), `exemption_spans` (the evidence of each established exemption) and `reference_passages`, the reviewed oracle list of the matter: the gold-material and injection spans in document order, the controlling authority version, and every eligible exemption relating to it whether established or not. The rubric must be self-consistent: conflict and missing elements match the element statuses, span polarity matches each status, and `fixture.check_gold` requires the gold authorities to be eligible for their matter.

**Candidate output v1.** `recommendation`, `issues[]`, `elements[]`, `claims[]`, `material_conflicts[]`, `adverse_authorities[]`, `missing_information[]`, `verification_flags[]` and `review_required: true`. Validation has two parts. `contracts.validate_structure` checks keys, types, bounds (at most 64 entries per list, 2,000 characters per free-text string, 256 KiB serialized), enumerations, unique element and claim ids, and the closed set of flag codes (`untrusted_instruction_in_source` with a `span_id`, `insufficient_authority`, `insufficient_evidence`, `authority_validity_unknown`); it decides `schema_valid`. `contracts.reference_errors` lists every citation and anchor that does not resolve (`fabricated_citation`, `unknown_version`, `pinpoint_mismatch`, `unknown_span`); these are scored, not treated as an unparsable output. `contracts.validate_output` requires both, and the reference drafter uses it.

**Classification.** `execution_kind` is `fixture`, `model-run` or `score-only`; `data_class` is `public-synthetic`, `public-benchmark` or `private-matter`. Only `fixture` maps to the legacy `synthetic: true`. The smoke mode accepts `public-synthetic` suites only.

## Scoring

Each matter is scored on fourteen criteria (`fixture.CRITERIA`) and passes only when all pass: valid schema, recommendation, exact controlling authority version, no ineligible version marked supported, element findings, conflicts flagged, missing information flagged, adverse authority, untrusted instruction flagged, and the five added with the rubric keys: `evidence_grounding` (every finding cites only gold spans of its polarity, enough for its status), `claim_status` (each claim states the status the eligibility decision implies), `citations_resolve`, `pinpoints_correct`, and `insufficiency_flagged` (exactly the expected `insufficient_authority` and `insufficient_evidence` flags). An output that fails the structure check scores `False` on all fourteen, so every row has the same denominator. `requests.jsonl` has one row per matter (`arm: smoke`, zero-based `repetition`) with the pass result, the criterion count, the recommendation against its label, and `review_status: pending_human_review`.

## Known limits of the smoke scorer

- An adverse exemption with status `not_established` may cite any evidence span of the matter; only an `established` exemption is held to its gold spans.
- An issue that cites an eligible authority which does not govern the matter is not penalised: the relevance of secondary issues is not scored.
- Proposition text is not scored. Whether a proposition is semantically supported by the cited authority is a separate rubric dimension that needs validated human or judge scoring.
- Within a family the member with more sources is usually the paired one, and both three-source matters are gold `decline`. Source counts are therefore a weak proxy for the label, which only a larger reviewed fixture set removes.

## What stays local

Candidate drafts and grader detail (`local/candidate-outputs.jsonl`, `local/score-detail.jsonl`) are written to `local/` inside the attempt directory. The generic report builder scans the attempt directory by file name at any depth, so `local/` is private by naming rule, not by directory: every private file is created through `contracts.private_file`, which refuses a name that builder exports, and `execute` refuses an attempt directory below a directory named `model_judgment` or `reports`. This holds until the legal report projection (Task F) replaces the generic scan. The report bundle carries IDs, enumerated categories and numbers only.

`execute` loads the suite once and requires the digest of the lock bytes it parsed to equal the digest the planner recorded for the case's `suite`; the lock pins the manifests. A suite changed after planning fails before anything is written, even when it was relocked consistently.

Until the legal report projection exists (Task F):

- Only the exact shipped smoke suite, identified by the digest of its lock both as planned and as read from disk, enters generic report generation. Any other suite runs and keeps its attempt outputs, and its report is recorded as `disabled`.
- Nothing is published. A campaign that asks for `publish.mode: pull-request` is rejected at plan time, automatic finalization never publishes, and `llm-eval publish-results` refuses a legal report, also one relabelled as another experiment: it checks every identity the bundle carries, including its paths, the raw records, the benchmark names of the raw rows and the summaries (a `legal-` prefix in any letter case claims the bundle), and that each planned job's mode is a mode of its experiment, and it needs the raw archive. A reporting setting cannot change this: the decision is made from the planned inputs. The legacy `llm-eval report` skips legal attempts.

## Changing the fixtures

Edit the three manifests, regenerate span and text digests, write the dict that `contracts.make_lock` returns as the new lock (LF line endings), and update `SMOKE_SUITE_SHA256` in `src/llm_eval/experiments/legal_benchmark/__init__.py`. `tests/test_legal_campaign.py` fails until the digest matches the shipped lock.
