# LiveBench model discovery

`scripts/model_discovery.py` reads the newest LiveBench release every night and raises, in one tracking issue, the high-scoring open-weight models that could be self-hosted on the target laptop and that the catalog has not reviewed. It is a report: it never edits the repository. Decisions are recorded by hand in [catalog/model-discovery.json](../catalog/model-discovery.json) or by adding the model to [catalog/models.json](../catalog/models.json).

## What runs and when

The [model discovery workflow](../.github/workflows/model-discovery.yml) runs:

| Trigger | Touches the issue | Notes |
|---|---|---|
| Schedule, 06:47 UTC (30 minutes after the upstream pin check and Dependabot) | yes | Counts towards the repeated-failure block |
| Push to `main` that changes `catalog/model-discovery.json`, `catalog/models.json`, `catalog/livebench-evidence.json`, `catalog/benchmarks.json`, the script or the workflow | yes | A recorded decision is reflected without waiting for the night |
| Pull request that changes the script, the workflow, `catalog/model-discovery.json`, `catalog/livebench-evidence.json`, `catalog/benchmarks.json` or `tests/test_model_discovery.py` | **no** | Runs against the real upstreams, so a re-pinned evidence file or a new task partition is calibrated before it merges; read the step summary and the `model-discovery` artifact (raw responses included) |
| `workflow_dispatch` | only with `update_issue` (default true) | `probe=true` prints the upstream shapes and never touches the issue |

The job first runs the offline tests, then the script with `contents: read`, `issues: write` and `actions: read`. It needs no personal access token: the default `GITHUB_TOKEN` reads the GitHub API and edits the issue. An optional `HF_TOKEN` secret raises the Hugging Face rate limit.

Locally, `python3 scripts/model_discovery.py` prints a plain report and writes nothing. `--help` lists the output flags.

## What a listed line claims

A candidate in the issue makes four claims, each with a pinned source:

1. LiveBench published this overall and these category scores for this leaderboard id in release R: a link to the table line at the leaderboard repository's 40-hex HEAD commit, with the table's sha256 and git blob sha.
2. The id resolves strictly and uniquely to this Hugging Face repository, in an org the owner listed as the model's official publisher.
3. The repository, at the linked revision, is public, has safetensors weights and carries license metadata (quoted, not interpreted; the license file still needs review).
4. The parameter count comes from the safetensors metadata at that revision, and the fit class is the catalog's planning arithmetic on it.

What a score does **not** mean, as every issue body states:

> Scores are LiveBench's published scores for the source checkpoints in release R. They rank models only within that release; they are not comparable with other releases (including the older-release scores in catalog/livebench-evidence.json) and are not local, quantized or engine-specific results. LiveBench may have served a model through a hosted provider at its own precision and reasoning settings. Fit is planning arithmetic (GiB = 2^30 bytes) on the published parameter count, for weights only. Nothing here edits the catalog: adding a model still needs review of its license file, a real artifact, engine architecture support and measured fit.

## How a run reaches its result

1. **Local inputs** are validated before any network access (exit 2 on any problem): the catalog, the evidence file, `catalog/benchmarks.json`, the decisions file and the budgets. The leaderboard repository and its reviewed commit are derived from the evidence `source_table` URLs; they must all name one repository at `leaderboard_revision`.
2. **Leaderboard reads** go through the GitHub git API (commits, trees, blobs). Every blob's git sha1 is recomputed and must equal its tree entry.
3. **Calibration**, every night, before anything is scored:
   - each evidence table at the reviewed commit must have its recorded sha256;
   - a categories file at that commit (its own release's first, then the nearest dates) must reproduce every recorded row: category scores within 1e-6, the overall within 0.005 + 1e-9 of the recorded two-decimal value (a tolerance, because JavaScript `toFixed` and Python `round` differ at .xx5; the tightest recorded case is 47.515028 against 47.52);
   - `categories_2026_06_25.json` at that commit must have exactly the task partition of `catalog/benchmarks.json` (7 sets, 23 tasks; names ignored);
   - soft: the two `excluded_latest_examples` scores (71.59, 81.11) must appear in the 2026-06-25 table; a miss is a step-summary warning only.
4. **Hugging Face anchors**: the revision answers for `qwen38-27b`, `nemotron-super-120b`, `gpt-oss-120b` and `llama33-70b` must equal their catalog `upstream_metadata` (id, sha, safetensors). A different `gated` value is a warning only.
5. **Scoring** of the analysis release R with the documented two-level mean: tasks are averaged within each category, then categories are averaged with equal weight. A row with a whole category missing gets no overall ("partial") and is not ranked.
6. **Matcher canary**: each evidence id is matched against its publisher's listing with the known set disabled. Resolving to a repository other than the catalog's fails the run; the four name-equal ids becoming ambiguous or unmatched is a header warning.
7. **The walk** described below.

## Selection: the pool of ten

Scores are comparable only within one release, so there is no absolute threshold. Rows of R are walked from the top. P* is the set of walked rows that could be self-hosted open-weight models; rows resolving to the same repository count once (the others are listed as variants). The walk stops when P* has 10 entries and the next row's overall is below the 10th entry's: ties at the 10th place are included. The cutoff is that 10th overall (or the lowest P* overall when the table runs out). Rows after the cutoff cost no Hugging Face request.

| Counts towards P* | Does not count |
|---|---|
| new verified candidates | too-large rows (catalogued or new) |
| every "needs a look" row | excluded catalog entries and `excluded_latest_examples` |
| catalogued rows with status candidate, conditional or control that are not too large | `not_open_weight` rows |
| `rejected` and `deferred` rows | repositories without weights yet, private or disabled |
| | partial rows |

So the issue closes once the owner has reviewed the ten best self-hostable entries.

## Matching: strict, official orgs only

A leaderboard id is resolved in this order: an `lb:` decision; an evidence `leaderboard_model_id` (known, offline); an `alias` target; the publisher by the longest prefix in `catalog/model-discovery.json`; the strict matcher over the complete listings of that publisher's orgs.

Names are tokenized (lowercased, `3_3` read as `3.3`, split on `-`, `_`, blanks and `/`, up to two leading org tokens dropped on both sides). A repository matches when its tokens equal the id's, or contain them in order with only `instruct`, `it`, `chat`, `hf`, `bf16`, `fp16` or `f16` left over (and a size or active-parameter token when the id names no size). Anything else left over disqualifies it: versions, dates, `base`, `pt`, `thinking`, quantization tokens. Only when nothing matches, up to two trailing reasoning or serving tokens (`-high`, `-thinking`, `-non-thinking`, `-32k`, `-turbo`, …) are stripped and the match retried; such a match says so, and a stripped `-turbo` adds that LiveBench scored a hosted serving variant. More than one match is "ambiguous"; precision siblings collapse to the repository without a precision token, else to the `-BF16` one.

The matched repository's model info must then show: an id still inside the publisher's orgs, a public and enabled repository, at least one `.safetensors` file, a size consistent with a size token in the name (0.90 to 1.15 of it, skipped for `8x7b` or `17b-16e` style names), and license metadata. Gated repositories pass and are labelled "terms must be accepted". A `base_model` link is never followed and never suppresses a finetune.

**Deliberate misses.** Recall is traded for precise claims. Date-coded ids (`mistral-small-2503` against `Mistral-Small-3.1-24B-Instruct-2503`), marketing names and publishers without an entry are not matched; each one appears under "Needs a look" with a snippet, never silently. Recover one with an `alias` decision naming the reviewed repository, or by adding a publisher entry for its official org.

## Parameter count and fit

For a float checkpoint (integer elements at most 1% of the total) P is `safetensors.total`. For a packed checkpoint (NVFP4, MXFP4) the metadata gives a range: the total as the lower bound, and the float elements plus 2× the 8-bit and 8× the 32-bit integer elements as the upper bound (Nemotron-3-Super-120B-NVFP4: 67.23–123.61 B; gpt-oss-120b: 116.83–231.49 B). A single size token in the repository name inside 0.90 × lower … 1.05 × upper is taken as P; without one, a range whose two bounds fall into one fit class gets that class, and its label names the precisions at each bound when they differ; anything else is "needs a look". Sizes are never read from model cards.

Planning GiB = P × bits / 8 / 2^30, the same formula as `llm_eval.catalog.estimate_weights`, with the catalog's planning bits (Q4_K_M 4.8, Q5_K_M 5.7, Q6_K 6.6, Q8_0 8.5, BF16 16; IQ2_XS 2.31 is shown for too-large rows only). The budgets are read from the configs: V = 24 GiB VRAM, W = 46 GiB (the WSL RAM budget), M = 52 + 22 − 4 = 70 GiB (native RAM and VRAM budgets less a 4 GiB working-set reserve, the largest whole GiB that keeps Qwen3.5-122B at 69.90 GiB inside M).

| Class | Rule | Parameter range |
|---|---|---|
| too_large | Q4_K_M > 70 GiB | above 125,269,879,466 |
| high_memory | 46 < Q4_K_M ≤ 70 GiB | 82,320,206,507 – 125,269,879,466 |
| offload | Q4_K_M ≤ 46 and BF16 > 24 GiB | 12,884,901,889 – 82,320,206,506 |
| control_only | BF16 ≤ 24 GiB | up to 12,884,901,888 |

A too-large row shows its Q4_K_M and IQ2_XS GiB and the bits per weight at which it would fit the 70 GiB budget (M × 8 × 2^30 / P; 1.88 for a 320 B model, 4.63 for a 130 B one). This is planning arithmetic for weights only. KV cache, activations, staging, duplicated host weights, loader peaks, dense-versus-MoE decode cost and engine support are not verified; choosing a precision stays the owner's call.

## Recording a decision

Append an entry to `decisions` in `catalog/model-discovery.json`. Every candidate and every "needs a look" row in the issue carries a ready snippet whose `reason` is `TODO`: harness-tests refuses `TODO` (also as a substring) and empty reasons, so a snippet pasted unedited fails CI until the reason is real.

```json
{"key": "hf:Qwen/Qwen4-80B", "decision": "rejected", "reason": "Architecture not supported by any catalog engine yet", "decided_on": "2026-11-08", "release": "2026-06-25"}
```

Fields: `key`, `decision`, `reason`, `decided_on` (ISO date, at most tomorrow) are required; `until` is required for (and only allowed on) `deferred`, `target` for `alias`; `release` is informational.

| Key form | Matches |
|---|---|
| `lb:<id>` | that exact leaderboard id |
| `lb:<prefix>*` | ids starting with the prefix (at least 2 characters) |
| `hf:<org>/<name>` | that repository (case-insensitive) |
| `hf:<org>/<name prefix>*` | repositories of that org whose name starts with the prefix (a family: `-Instruct`, `-Thinking`, …) |

| Decision | Effect | Raised again when |
|---|---|---|
| `rejected` | suppressed; still takes its place in the pool of ten | never |
| `deferred` | suppressed until `until` (after `decided_on`, at most 365 days later); takes its place in the pool | after `until`, as "deferral expired" |
| `not_open_weight` (`lb:` keys only) | suppressed; does not take a place in the pool; rows without a publisher make no request | a unique strict match appears in an allowlisted org: "weights may now be public" |
| `alias` (exact `lb:` keys only) | the row resolves to `target`, still verified by model info; a catalog `upstream_repo` as target makes the row "this is catalog model X" | the target answers 401/403/404, is private or disabled, or moved outside the publisher's orgs |

An `hf:` key applies to the repository however the row reached it, an `alias` target included. An `lb:` key never hides a catalogued model: a row that resolves to an evidence id or a catalog repository is listed as known even when an expired deferral or a `not_open_weight` prefix covers it, with a note naming that entry (remove it); a `not_open_weight` row whose match turns out to be public but too large is listed as too large, with the same note.

A key is refused when it is redundant: an `hf:` key equal to a catalog `upstream_repo`, or an `lb:` key equal to an evidence `leaderboard_model_id`. Publisher entries (`prefixes`, lowercase and unique; `hf_orgs`) record the owner's judgement that an org is the model's official publisher; every catalog org must be covered. The seeded `not_open_weight` entries (Claude, Gemini, GPT-4/GPT-5, ChatGPT, o1/o3/o4, Grok 3/4) say in their reason that they await the owner's confirmation; `grok-2` is deliberately absent because its weights are published and catalogued.

## Adding the model to the catalog instead

A candidate's snippet block also carries its `upstream_metadata` (id, sha, gated, safetensors, in the catalog's schema) and a ready `catalog/livebench-evidence.json` recommendation with the release, overall, category scores, the table URL at the pinned head commit, its sha256 and the shared `meaning` string. Adding the model to `catalog/models.json` (and, when it is chosen for its score, the recommendation) is the decision: the next run lists it as known. The recommendation's `source_table` is pinned to the head commit of the run, while every recommendation must name one commit, `leaderboard_revision`: when the two differ, add the recommendation only together with moving `leaderboard_revision` and every existing `source_table` URL to that commit, after checking that each existing table still has its recorded `source_sha256` there (calibration checks them). Pasted alone, it fails local validation and every run; the snippet says so when it applies. It still needs the license file, a real artifact, engine architecture support and measured fit reviewed, as for every catalog entry ([MODELS.md](MODELS.md)).

## Notices and how they clear

Each notice keeps the issue open on its own.

| Notice | Raised when | Clears when |
|---|---|---|
| New LiveBench release | the analysed release is newer than the evidence `latest_release`; lists the category and task changes against `catalog/benchmarks.json` and whether `src/llm_eval/livebench.py` `RELEASES` holds it | `latest_release` in `catalog/livebench-evidence.json` records it (with `leaderboard_revision`, `checked_on`, `catalog/benchmarks.json`, `catalog/installers.json` `livebench.release`, `RELEASES` and [LIVEBENCH.md](LIVEBENCH.md) as the checklist) |
| Averaging code changed | the blob of `src/Table/Averaging.js` at head differs from the one at `leaderboard.averaging_reviewed_revision`, or the file is gone; the Candidates section lists nothing meanwhile (the names stay in the step summary and the artifact) | the aggregation is re-checked and `averaging_reviewed_revision` names a commit with the head blob |
| Task partition changed | the analysed release is the reference release and its categories file at head no longer has the partition of `catalog/benchmarks.json` | `catalog/benchmarks.json` records the new partition and, in the same change, `leaderboard_revision` and every `source_table` URL in `catalog/livebench-evidence.json` name a commit that has it, each table still matching its `source_sha256` there. Calibration checks `catalog/benchmarks.json` against the categories file at `leaderboard_revision`, so editing `catalog/benchmarks.json` alone fails every run |
| Release without a categories file | a table newer than every release has 20 or more rows and no categories file (fewer rows is a header note) | the categories file appears or the table goes |
| Catalog repo renamed / no longer on Hugging Face | a catalog `upstream_repo` is missing from its org's listing and its model info names another id, or answers 401/403/404 | `catalog/models.json` is updated or the repository is back |

The analysed release is the newest one (table and categories file both present) with at least 20 scored rows; a newer release with fewer is reported as "looks in progress" and the previous one is analysed.

## The tracking issue

The issue is titled "LiveBench models needing a catalog decision" and labelled `model-discovery`. The workflow uses only an issue it created itself (author `github-actions[bot]`, with the label, which only collaborators can apply), read from the issues endpoint rather than search; an issue anyone else opens with the same title is ignored. A complete run with something to decide refreshes the body (reopening a closed issue rather than creating a duplicate) and comments with the entries that are new since the last refresh, because body edits send no notification. A hidden state marker at the end of the body drives only that "new" flag; it never hides a row. A complete run with nothing to decide writes the final body and closes the issue.

## Red runs

A run fails (red, no issue update) when a source cannot be read (exit 1) or no longer has the assumed shape, or a local input is invalid (exit 2); the step summary names the stage, what was expected and what was found. GitHub's failed-run email is the first signal. All network reads of a run share a 15-minute deadline, below the job's 20-minute timeout: a run that cannot finish its reads in time (a throttled or very slow upstream) fails with a network error instead of being cancelled, because a cancelled run never reaches the repeated-failure block. After 3 consecutive failed scheduled runs, the issue body gets a "Problems reading sources" block on top, noting the date of the last good refresh, with the previous candidates kept below it; a comment is posted once, on the third failure. The next complete run replaces the body.

## First deployment

1. Merge the pull request that adds the pipeline; harness-tests validates the seeded decisions file on every pull request, and the owner reviews the seeded publishers and closed-family decisions there. The pull request's own run shows the result against real data in its step summary.
2. Run the workflow by hand with `probe=true`. Compare the digest and the raw artifact with the shapes below; fix any mismatch (the CSV `model` column, the 2025 categories files, the Hugging Face listing `limit` and `Link` behaviour).
3. Run it with `update_issue=false` and check the step summary: calibration 5/5, anchors 4/4, the canary, and a plausible walk.
4. Let the schedule run. The first refresh is a one-time backlog of at most about ten named rows plus notices.

## Shape assumptions

| Source | Assumed shape | Confidence |
|---|---|---|
| Leaderboard commits and trees (GitHub git API) | `{sha, commit: {tree: {sha}, committer: {date}}}`; non-truncated trees; `public/table_YYYY_MM_DD.csv` and `public/categories_YYYY_MM_DD.json`; `src/Table/Averaging.js` | API high; layout medium-high (the evidence cites these paths) |
| Blobs | base64 content whose length and git sha1 match | high |
| Release table | UTF-8 CSV, exactly one `model` column, one column per task id as spelled in the categories file, cells 0–100 or a missing marker, one row per id | medium; proven or refuted nightly by calibration |
| Categories file | `{category: [task, …]}`, each task in one category | medium-high |
| Hugging Face listing | `GET /api/models?author=ORG&limit=1000`, paginated by `Link: rel="next"`; every catalog repository of the org must appear | medium-high |
| Hugging Face model info | `id`, `sha`, `private`, `siblings`, `gated`, `cardData`, `tags`, `safetensors{parameters, total}` | high for the `upstream_metadata` subset; medium for `disabled` |

## Known limitations

- Recall is traded for precise claims: strict names, official orgs only, packed checkpoints sized only when the name agrees with the metadata range. The misses that matter are named under "Needs a look", not hidden.
- Only the newest release is ranked. A strong model that LiveBench has not evaluated is invisible until it is; partial rows wait until LiveBench completes them.
- Any change to Averaging.js, even a cosmetic one, withholds candidates until `averaging_reviewed_revision` is bumped.
- Calibration depends on the reviewed commit's blobs staying reachable. A history rewrite at LiveBench turns every run red until the evidence is re-pinned.
- The license gate runs after the fit: a too-large repository without license metadata is listed as too large, not as needing a look.
- Fit is planning arithmetic only.
