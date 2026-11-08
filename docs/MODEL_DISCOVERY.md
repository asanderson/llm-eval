# LiveBench model discovery

`scripts/model_discovery.py` reads the newest LiveBench release every night and raises, in one tracking issue, the high-scoring open-weight models that could be self-hosted on the target laptop and that the catalog has not reviewed. It is a report: it never edits the repository. Decisions are recorded by hand in [catalog/model-discovery.json](../catalog/model-discovery.json) or by adding the model to [catalog/models.json](../catalog/models.json).

The leaderboard source is [livebench.ai](https://livebench.ai/) itself. The GitHub repository `LiveBench/new-livebench` that the evidence files cite answers 404 since 2026-11-08; the tables it held are served byte-identical at `livebench.ai/v1/`, which is where calibration now checks them.

## What runs and when

The [model discovery workflow](../.github/workflows/model-discovery.yml) runs:

| Trigger | Touches the issue | Notes |
|---|---|---|
| Schedule, 06:47 UTC (30 minutes after the upstream pin check and Dependabot) | yes | Counts towards the repeated-failure block |
| Push to `main` that changes `catalog/model-discovery.json`, `catalog/models.json`, `catalog/livebench-evidence.json`, `catalog/benchmarks.json`, the script or the workflow | yes | A recorded decision is reflected without waiting for the night |
| Pull request that changes the script, the workflow, `catalog/model-discovery.json`, `catalog/livebench-evidence.json`, `catalog/benchmarks.json` or `tests/test_model_discovery.py` | **no** | Runs against the real upstreams, so a changed evidence file or task partition is calibrated before it merges; read the step summary and the `model-discovery` artifact (raw responses included) |
| `workflow_dispatch` | only with `update_issue` (default true) and an empty `release` | `probe=true` prints the upstream shapes and never touches the issue; `release` (empty = newest) analyses that release instead, e.g. `2026-06-25` (v1) or `20261014` (2.0), and never touches the issue either (the script writes `complete=false`, and the issue steps also require an empty `release`): the issue tracks the newest release, and an older release's marker would make the next nightly announce every entry again. Its report is in the step summary and the artifact |

The job first runs the offline tests, then the script with `contents: read`, `issues: write` and `actions: read`. It needs no personal access token: the default `GITHUB_TOKEN` only edits the issue (the issue steps' `GH_TOKEN`); the script itself reads only livebench.ai, which gets no token at all, and the Hugging Face API, which gets the optional `HF_TOKEN` secret (it raises the rate limit).

Locally, `python3 scripts/model_discovery.py` prints a plain report and writes nothing. `--help` lists the output flags; `--release ID` forces a release.

## What a listed line claims

A candidate in the issue makes four claims, each with a source:

1. LiveBench published this overall and these category (or suite) scores for this leaderboard id in release R: a link to the release table on livebench.ai with the row number, and the table's sha256 in the header. livebench.ai serves no versioned history, so the sha256 is what identifies the bytes read.
2. The id resolves to this Hugging Face repository, in an org the owner listed as the model's official publisher: either strictly and uniquely by name, or because LiveBench's own model registry links exactly this repository (the line says which).
3. The repository, at the linked revision, is public, has safetensors weights and carries license metadata (quoted, not interpreted; the license file still needs review).
4. The parameter count comes from the safetensors metadata at that revision, and the fit class is the catalog's planning arithmetic on it.

What a score does **not** mean, as every issue body states:

> Scores are LiveBench's published scores for the source checkpoints in release R. They rank models only within that release; they are not comparable with other releases (including the older-release scores in catalog/livebench-evidence.json) and are not local, quantized or engine-specific results. LiveBench may have served a model through a hosted provider at its own precision and reasoning settings. Fit is planning arithmetic (GiB = 2^30 bytes) on the published parameter count, for weights only. Nothing here edits the catalog: adding a model still needs review of its license file, a real artifact, engine architecture support and measured fit.

## How a run reaches its result

1. **Local inputs** are validated before any network access (exit 2 on any problem): the catalog, the evidence file, `catalog/benchmarks.json`, the decisions file and the budgets.
2. **The leaderboard site.** `https://livebench.ai/asset-manifest.json` names the page's main script (`files["main.js"]`, today `static/js/main.1e1ce12d.js`); `index.html` must load exactly that script. The script carries both release lists, LiveBench's model registry and the averaging code. Every livebench.ai file must have its expected media type (`text/csv`, `application/json`, JavaScript, HTML for the page): the site answers unknown paths with a 404 page, and an HTML body where a table belongs is a shape error, never data. Redirects are followed only on the same https host (`www.livebench.ai` redirects to `livebench.ai` and is never asked). Release files are fetched without the site's `?v=` cache-buster.
3. **Release discovery** (below): the timeline of v1 and 2.0 releases; the evidence `latest_release` must still be on it.
4. **Calibration**, every night, before anything is scored:
   - each evidence table is read at `https://livebench.ai/v1/<its file name>` (a recorded GitHub blob URL is mapped by its file name) and must have its recorded sha256;
   - a v1 categories file (its own release's `v1/categories_YYYY_MM_DD.json` first, then the other v1 releases', nearest first) must reproduce every recorded row: category scores within 1e-6, the overall within 0.005 + 1e-9 of the recorded two-decimal value (a tolerance, because JavaScript `toFixed` and Python `round` differ at .xx5; the tightest recorded case is 47.515028 against 47.52);
   - `v1/categories_<reference_release>.json` must have exactly the task partition of `catalog/benchmarks.json` (7 sets, 23 tasks; names ignored);
   - soft: the two `excluded_latest_examples` scores (71.59, 81.11) must appear in the 2026-06-25 table; a miss is a step-summary warning only;
   - soft: a recorded 2.0 row (one added from a candidate's stanza) is re-checked only while the table still has its recorded sha256, since 2.0 tables grow as LiveBench adds rows; other bytes are a step-summary warning.
5. **Hugging Face anchors**: the revision answers for `qwen38-27b`, `nemotron-super-120b`, `gpt-oss-120b` and `llama33-70b` must match their catalog `upstream_metadata`: the id, the sha, `safetensors.total`, the set of dtypes and every float count exactly. An integer count (U8, I8, U32, …) that differs is a header warning, not a failure: Hugging Face now reports U8 = 112,764,911,616 at the pinned Nemotron-3-Super NVFP4 revision where the catalog records 56,382,455,808, with everything else unchanged. Packed size ranges use the reported counts, which only widens them (the `120b` name still verifies; an unnamed packed repository gets a wider range and never a tighter fit claim). A different `gated` value is a warning only.
6. **Scoring** of the analysis release R (below).
7. **Matcher canary**: each evidence id is resolved as the walk would resolve it with the known set disabled: the repository the release's own LiveBench registry links (inside the publisher's orgs), else the strict matcher over its publisher's listing. A strict match naming a repository other than the catalog's fails the run; a registry link that disagrees with the catalog is a header warning (LiveBench's data, not the matcher; the evidence keeps deciding the row); the four name-equal ids becoming ambiguous or unmatched is a header warning.
8. **The walk** described below.

## Releases, generations and averaging

livebench.ai has no directory listing: the release lists live in the main script. The v1 list is an inline array mapped to `gen:"v1"` entries; the 2.0 ids are the one assigned array of quoted `YYYYMMDD` ids that the `gen:"v2"` map uses (it labels them `YYYY-MM-DD`). Each must be found exactly once; ids must be calendar dates; and dates must be unique across both lists, as the site itself asserts. The minified identifiers change on every build, so the run never anchors on them. A layout change here is an exit 2 with the failure block, by design.

| Generation | Files | Columns | Overall |
|---|---|---|---|
| v1 | `v1/table_YYYY_MM_DD.csv`, `v1/categories_YYYY_MM_DD.json` | `model`, then the tasks (alphabetical) | the two-level mean: tasks averaged within each category, then every category equally; a row with a whole category missing gets no overall ("partial") and is not ranked. Calibrated against the recorded rows. |
| 2.0 | `data/YYYYMMDD/table.csv`, `data/YYYYMMDD/categories.json` | `model`, then one column per suite (`long_agentic`, `reasoning`, `coding`, `browser`, `data_analysis`, `research`, `design`) | the site's averaging code: each suite is the mean of its columns that hold a number (`n/a` and blank cells are left out); the overall is the weighted mean of the suites with a score, the weight from `_overall_weights` in `categories.json` when that suite exists and the value is finite and above 0, else 1; rounded to 2 decimals as JavaScript `toFixed(2)` does (exact binary value, half up). A row with no suite score has no overall. |

The 2.0 rule is the one in the reviewed main script (`Nn`, `En` and `zn` in `main.1e1ce12d.js`, read 2026-11-08), which is what the leaderboard displays. For 20261025 its weights are Long Agentic ×2, Coding ×1.5 and Design ×1.5, although that release's `notes.json` still says "Every suite counts equally": the code wins, and the issue header states the weights used. The site adds the suites in its display order (`rn()` sorts them by their place in a list of suite names, today Long Agentic, Design, Coding, Browser, Data Analysis, Research, Reasoning; unknown suites last), and so does the run: with a missing suite the summation order can move an exact .xx5 overall across the rounding boundary (59.075 is 59.08 on the site, 59.07 when added in `categories.json` order). The list is read from the main script each night; when it cannot be found, the reviewed script's list is used and the header says so. Ranking uses the rounded overall, so rows the site shows with the same overall tie. The 2.0 averaging cannot be calibrated against recorded scores (none exist); it is unit-tested against hand-computed values instead. A `categories.json` key starting with `_` other than `_overall_weights`, a weight that is not a finite number, or a v1 categories file with any `_` key is a shape error; weights for unknown suites or not above 0 are ignored (as the site's code does) and named in a header note. 2.0 suites are a different taxonomy from `catalog/benchmarks.json` and are never compared with it.

The **analysis release R** is the newest release on the timeline whose table and categories file both load and that has at least 20 scored rows. A newer release with fewer is reported as "looks in progress" and the previous one is analysed; a release on the timeline whose table answers 404 is a header note; a table of 20 or more rows without its categories file is a notice. R must not be older than the evidence `latest_release`. Only R is scored and ranked; rows LiveBench adds to R are picked up the next night. `--release` (and the dispatch input) analyses the named release instead, even one with fewer than 20 rows or older than `latest_release`, and says so in the header.

## Selection: the pool of ten

Scores are comparable only within one release, so there is no absolute threshold. Rows of R are walked from the top. P* is the set of walked rows that could be self-hosted open-weight models; rows resolving to the same repository count once (the others are listed as variants). The walk stops when P* has 10 entries and the next row's overall is below the 10th entry's: ties at the 10th place are included. The cutoff is that 10th overall (or the lowest P* overall when the table runs out). Rows after the cutoff cost no Hugging Face request.

| Counts towards P* | Does not count |
|---|---|
| new verified candidates | too-large rows (catalogued or new) |
| every "needs a look" row | excluded catalog entries and `excluded_latest_examples` |
| catalogued rows with status candidate, conditional or control that are not too large | `not_open_weight` rows, and rows LiveBench's registry lists as closed |
| `rejected` and `deferred` rows | repositories without weights yet, private or disabled |
| | partial rows |

So the issue closes once the owner has reviewed the ten best self-hostable entries.

## Matching: strict, official orgs only

A leaderboard id is resolved in this order: an `lb:` decision; an evidence `leaderboard_model_id` (known, offline); an `alias` target; LiveBench's registry entry for the id (below); the publisher by the longest prefix in `catalog/model-discovery.json`; the strict matcher over the complete listings of that publisher's orgs.

Names are tokenized (lowercased, `3_3` read as `3.3`, split on `-`, `_`, blanks and `/`, up to two leading org tokens dropped on both sides). A repository matches when its tokens equal the id's, or contain them in order with only `instruct`, `it`, `chat`, `hf`, `bf16`, `fp16` or `f16` left over (and a size or active-parameter token when the id names no size). Anything else left over disqualifies it: versions, dates, `base`, `pt`, `thinking`, quantization tokens. Only when nothing matches, up to two trailing reasoning or serving tokens (`-high`, `-thinking`, `-non-thinking`, `-32k`, `-turbo`, …) are stripped and the match retried; such a match says so, and a stripped `-turbo` adds that LiveBench scored a hosted serving variant. More than one match is "ambiguous"; precision siblings collapse to the repository without a precision token, else to the `-BF16` one.

The matched repository's model info must then show: an id still inside the publisher's orgs, a public and enabled repository, at least one `.safetensors` file, a size consistent with a size token in the name (0.90 to 1.15 of it, skipped for `8x7b` or `17b-16e` style names), and license metadata. When model info answers with another id (the repository was renamed, say a registry link spelling the old name), the catalog and `hf:` decisions are checked again under that id, the issue names it and says it was renamed, and rows reaching it by either name take one place in the pool. Gated repositories pass and are labelled "terms must be accepted". A `base_model` link is never followed and never suppresses a finetune.

### LiveBench's model registry as a hint

The main script also carries LiveBench's own registry of the models it lists (an object for the 2.0 ids and an older one for v1 ids; entries such as `"glm-5.3":{…,openweight:!0,huggingface:"https://huggingface.co/zai-org/GLM-5.3"}`, some with `variants:[{rawName, …}]`, which inherit their entry's link as the site does). Only R's own registry is consulted, the one that holds the most ids of R (on the recorded data each table's own registry holds nearly all of its ids and the other one a handful): the site reads each generation's registry for its own rows and never the other's, and it shows no row without an entry there (the header then says so, as its ranks can differ). A v1 row never takes a 2.0 entry's link, nor the reverse. It is a hint, never a source of claims on its own:

| Registry entry for the row's id | Effect |
|---|---|
| `openweight:!0` with a `huggingface:` link into an org of the row's publisher | that repository is the match candidate ("LiveBench links this repository"), verified exactly like a strict match: model info, identity, public, weights, size gate, license, fit, `hf:` decisions |
| `openweight:!0` with a link outside the publisher's orgs (or no publisher entry for the id) | "needs a look" (`linked_outside_publisher`): never a candidate, no model-info request; add a publisher entry when that org is the official publisher, or reject the `hf:` key |
| `openweight:!0` without a link | the strict name rules |
| no `openweight` | "LiveBench marks it closed": not in the pool, listed under "Not raised", like a `not_open_weight` decision; a catalogued model is still listed as known, and a strict match in an allowlisted org becomes "weights may be public" (unless it is private, has no weights yet, is too large or is decided) |
| no entry | the strict name rules |

`lb:` decisions come first, so the seeded `not_open_weight` entries keep covering v1 ids and rows without registry entries. When the registry is missing or does not parse (a registry object that is not plain data, or an `openweight:!0` outside every registry object read; code around a registry is passed over, and an entry the minifier left unquoted, `inkling:{…}`, is read like a quoted one), the header carries a warning and matching uses the name rules alone; the run does not fail.

**Deliberate misses.** Recall is traded for precise claims. Date-coded ids (`mistral-small-2503` against `Mistral-Small-3.1-24B-Instruct-2503`), marketing names and publishers without an entry are not matched by name; each one appears under "Needs a look" with a snippet, never silently (unless LiveBench's registry lists it as closed). Recover one with an `alias` decision naming the reviewed repository, or by adding a publisher entry for its official org.

## Parameter count and fit

For a float checkpoint (integer elements at most 1% of the total) P is `safetensors.total`. For a packed checkpoint (NVFP4, MXFP4) the metadata gives a range: the total as the lower bound, and the float elements plus 2× the 8-bit and 8× the 32-bit integer elements as the upper bound (Nemotron-3-Super-120B-NVFP4 with the catalog's counts: 67.23–123.61 B, with the counts Hugging Face reports now: 67.23–236.38 B; gpt-oss-120b: 116.83–231.49 B). A single size token in the repository name inside 0.90 × lower … 1.05 × upper is taken as P; without one, a range whose two bounds fall into one fit class gets that class, and its label names the precisions at each bound when they differ; anything else is "needs a look". Sizes are never read from model cards.

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
{"key": "hf:Qwen/Qwen4-80B", "decision": "rejected", "reason": "Architecture not supported by any catalog engine yet", "decided_on": "2026-11-08", "release": "2026-10-25"}
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
| `not_open_weight` (`lb:` keys only) | suppressed; does not take a place in the pool; rows without a publisher make no request | a unique strict match (or a registry link) appears in an allowlisted org: "weights may now be public" |
| `alias` (exact `lb:` keys only) | the row resolves to `target`, still verified by model info; a catalog `upstream_repo` as target makes the row "this is catalog model X" | the target answers 401/403/404, is private or disabled, or moved outside the publisher's orgs |

An `hf:` key applies to the repository however the row reached it, an `alias` target or a registry link included. An `lb:` key never hides a catalogued model: a row that resolves to an evidence id or a catalog repository is listed as known even when an expired deferral or a `not_open_weight` prefix covers it, with a note naming that entry (remove it); a `not_open_weight` row whose match turns out to be public but too large is listed as too large, with the same note.

A key is refused when it is redundant: an `hf:` key equal to a catalog `upstream_repo`, or an `lb:` key equal to an evidence `leaderboard_model_id`. Publisher entries (`prefixes`, lowercase and unique; `hf_orgs`) record the owner's judgement that an org is the model's official publisher; every catalog org must be covered. The seeded `not_open_weight` entries (Claude, Gemini, GPT-4/GPT-5, ChatGPT, o1/o3/o4, Grok 3/4) say in their reason that they await the owner's confirmation; `grok-2` is deliberately absent because its weights are published and catalogued.

The `site` record (`{"main_script": "static/js/main.1e1ce12d.js", "reviewed_on": "2026-11-08"}`) names the main script whose averaging code the owner read; it is validated like the rest of the file.

## Adding the model to the catalog instead

A candidate's snippet block also carries its `upstream_metadata` (id, sha, gated, safetensors, in the catalog's schema) and a ready `catalog/livebench-evidence.json` recommendation with the release, overall, category (or suite) scores, the table's livebench.ai URL as `source_table` (`https://livebench.ai/data/YYYYMMDD/table.csv` or `https://livebench.ai/v1/table_YYYY_MM_DD.csv`), its sha256 and the shared `meaning` string. The evidence parser accepts both livebench.ai forms next to the recorded GitHub blob URLs; `leaderboard_revision` only pins the GitHub-form URLs. Adding the model to `catalog/models.json` (and, when it is chosen for its score, the recommendation) is the decision: the next run lists it as known. A recorded 2.0 row is re-checked softly (see calibration). It still needs the license file, a real artifact, engine architecture support and measured fit reviewed, as for every catalog entry ([MODELS.md](MODELS.md)).

## Notices and how they clear

Each notice keeps the issue open on its own.

| Notice | Raised when | Clears when |
|---|---|---|
| New LiveBench release | the analysed release is newer than the evidence `latest_release`; for a v1 release it lists the category and task changes against `catalog/benchmarks.json`, for a 2.0 release its suites and weights (never compared with benchmarks.json), and whether `src/llm_eval/livebench.py` `RELEASES` holds its date | `latest_release` in `catalog/livebench-evidence.json` records it (with `checked_on`, `catalog/benchmarks.json`, `catalog/installers.json` `livebench.release`, `RELEASES` and [LIVEBENCH.md](LIVEBENCH.md) as the checklist) |
| Leaderboard site code changed | the served main script is not the one `site.main_script` names; it names both. Candidates are **not** withheld: the bundle changes on every deploy, and the run still requires the `"_overall_weights"` literal and checks every categories file's weights | the owner re-reads the weights rule in the new script and sets `site.main_script` (and `site.reviewed_on`) |
| Release without a categories file | a table on the timeline, newer than the analysed release, has 20 or more rows and its categories file answers 404 (fewer rows is a header note) | the categories file appears or the release goes |
| Catalog repo renamed / no longer on Hugging Face | a catalog `upstream_repo` is missing from its org's listing and its model info names another id, or answers 401/403/404 | `catalog/models.json` is updated or the repository is back |

A changed task partition of the reference release is no longer a notice: livebench.ai serves one unversioned copy of `v1/categories_<reference_release>.json`, so a change fails calibration (exit 2). The failure says what to do: record the new partition in `catalog/benchmarks.json` together with `catalog/livebench-evidence.json` (`latest_release`, `checked_on` and the recorded rows of that release) in one change.

## The tracking issue

The issue is titled "LiveBench models needing a catalog decision" and labelled `model-discovery`. The workflow uses only an issue it created itself (author `github-actions[bot]`, with the label, which only collaborators can apply), read from the issues endpoint rather than search; an issue anyone else opens with the same title is ignored. A complete run with something to decide refreshes the body (reopening a closed issue rather than creating a duplicate) and comments with the entries that are new since the last refresh, because body edits send no notification. A hidden state marker at the end of the body drives only that "new" flag; it never hides a row. A complete run with nothing to decide writes the final body and closes the issue.

## Red runs

A run fails (red, no issue update) when a source cannot be read (exit 1) or no longer has the assumed shape, or a local input is invalid (exit 2); the step summary names the stage, what was expected and what was found, and, where the fix is known, what to do. The site's script is a minified bundle: a rebuild that moves the release lists or the averaging code out of the shapes above turns the run red with the failure block rather than letting it read the wrong lists. GitHub's failed-run email is the first signal. All network reads of a run share a 15-minute deadline, below the job's 20-minute timeout: a run that cannot finish its reads in time (a throttled or very slow upstream) fails with a network error instead of being cancelled, because a cancelled run never reaches the repeated-failure block. After 3 consecutive failed scheduled runs, the issue body gets a "Problems reading sources" block on top, noting the date of the last good refresh, with the previous candidates kept below it; a comment is posted once, on the third failure. The next complete run replaces the body.

## First deployment

1. Merge the pull request; harness-tests validates the decisions file and its `site` record on every pull request, and the pull request's own run shows the result against real data in its step summary.
2. Run the workflow by hand with `probe=true`. The digest shows the page and manifest, the main script and whether it is the reviewed one, both release lists with their counts, the registries (entries, `openweight`, links), the calibration tables' sha256 against the evidence, the newest 2.0 table's header, row count, categories keys and weights, an unknown path's status, and the Hugging Face listing, model-info and anchor shapes (integer counts that now differ are listed). Fix any mismatch with the shapes below.
3. Run it with `update_issue=false` and check the step summary: calibration 5/5, anchors 4/4 (with the expected U8 warning), the canary, the registry counts and a plausible walk.
4. Let the schedule run. The first refresh is a one-time backlog of at most about ten named rows plus notices (including the new-release notice until `latest_release` records the 2.0 release).

## Shape assumptions

| Source | Assumed shape | Confidence |
|---|---|---|
| `livebench.ai/asset-manifest.json` and `/` | `{"files": {"main.js": "./static/js/main.<hash>.js", …}}`; `index.html` loads that one main script | high (create-react-app layout, recorded 2026-11-08) |
| Main script release lists | `[…"YYYY-MM-DD"…].map(e=>({id:e,label:e,gen:"v1"}))` once; one assigned `["YYYYMMDD", …]` array, used by the single `gen:"v2"` map | medium: a minified bundle; any change is an exit 2 |
| Main script averaging code | contains the `"_overall_weights"` literal; the rule above as read on 2026-11-08 | medium; the served script's name is compared with `site.main_script` every night |
| Main script registry | plain-data object literals `X={"id":{…},…}` (or `X={id:{…},…}`) holding the `openweight:!0` entries | medium; only a matching hint, so a change is a warning |
| v1 files | `v1/table_YYYY_MM_DD.csv` (text/csv; `model`, then tasks), `v1/categories_YYYY_MM_DD.json` (application/json; `{category: [task, …]}`); byte-identical to the recorded GitHub blobs | high (sha256-checked nightly for the recorded tables) |
| 2.0 files | `data/YYYYMMDD/table.csv` (`model`, then one column per suite; 0–100, `n/a` or blank), `data/YYYYMMDD/categories.json` (`{suite: [column]}` plus optional `_overall_weights`) | high for the shape; the files are not versioned |
| Unknown paths | HTTP 404 with an HTML page | high |
| Hugging Face listing | `GET /api/models?author=ORG&limit=1000`, paginated by `Link: rel="next"`; every catalog repository of the org must appear | medium-high |
| Hugging Face model info | `id`, `sha`, `private`, `siblings`, `gated`, `cardData`, `tags`, `safetensors{parameters, total}` | high for the `upstream_metadata` subset (integer dtype counts excepted, see the anchors); medium for `disabled` |

## Known limitations

- livebench.ai serves no versioned history. A run identifies what it read by sha256, but a table read yesterday cannot be fetched again if LiveBench replaces it; 2.0 tables grow in place as rows are added.
- The release lists, the averaging code and the registry are read out of a minified bundle. A rebuild that changes their shapes fails the run (exit 2) until the parser is updated; the weights rule itself is trusted from the reviewed script, and a new script name is a notice until the owner re-reads it.
- The 2.0 averaging is implemented from the site's code and unit-tested against hand-computed values; it is not calibrated against recorded scores, because none exist.
- Recall is traded for precise claims: strict names, official orgs only, packed checkpoints sized only when the name agrees with the metadata range. The misses that matter are named under "Needs a look", not hidden; rows LiveBench's registry lists as closed are listed but take no place in the pool.
- LiveBench's registry is trusted only to point at a repository inside an allowlisted org, which is then verified; a wrong `openweight` flag can hide an open model as "closed" until a strict match appears.
- Only the newest release is ranked. A strong model that LiveBench has not evaluated is invisible until it is; partial v1 rows wait until LiveBench completes them.
- The license gate runs after the fit: a too-large repository without license metadata is listed as too large, not as needing a look.
- Fit is planning arithmetic only.
