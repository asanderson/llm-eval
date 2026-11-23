#!/usr/bin/env python3
"""Nightly check of catalog/model-artifacts.json against Hugging Face, with optional bump.

  python3 scripts/model_pins.py                       report only
  python3 scripts/model_pins.py --apply               rewrite catalog/model-artifacts.json where a pin moved
  python3 scripts/model_pins.py --summary FILE        write the Markdown pull request body
  python3 scripts/model_pins.py --issue-summary FILE  write the tracking-issue body (same pin table and
                                                      decisions, without the section about the PR's diff)
  python3 scripts/model_pins.py --github-output       append changed=/manual=/failed= to $GITHUB_OUTPUT
  python3 scripts/model_pins.py --strict              exit 1 when any lookup failed
  python3 scripts/model_pins.py --download-spec FILE [--models ID,ID]
                                                      no network: write a download manifest for the pinned
                                                      artifacts (all of them, or the named catalog ids)

catalog/model-artifacts.json pins the quantized artifact each measured catalog model
loads in the next run: the artifact repository, a full commit of it, the precision and
the selected files with their size and sha256. A run still loads what the operator's
artifact lock names. --download-spec turns the pins into the manifest that
scripts/setup.py --download-spec consumes; accept_license is written false, so the
operator reviews the license before the manifest is accepted.

What moves automatically (policy "bump"):
  * an artifact pin: to the head commit of its repository, when every pinned file is
    still published there with a Git LFS sha256. The sizes and hashes listed at that
    commit are recorded, and the row says whether the pinned files are unchanged or
    the weights changed.

What is only reported (policy "report"); each of these needs a manual decision:
  * a pinned file that the head commit no longer publishes, or publishes without a
    Git LFS sha256 (the content cannot be verified); the pin stays;
  * a repository Hugging Face answers 401, 403, 404 or 410 for;
  * a model that the published model-offloading results measured and that has no pin;
  * a publisher repository (upstream_repo in catalog/models.json) that moved past the
    catalog source_revision, and a pin whose base_model is not that upstream_repo.
    catalog/models.json is never rewritten;
  * a repository that a publisher org of a pinned model created on or after
    new_models_since, when it is not a catalog upstream_repo and no hf: decision in
    catalog/model-discovery.json covers it. Size and license are not judged here:
    that is the model discovery issue (docs/MODEL_DISCOVERY.md).

Network goes through one Net object so tests can run offline with a fake: https GET
to huggingface.co only. HF_TOKEN, when set, authenticates those requests.
"""
import argparse
import datetime as dt
import email.utils
import http.client
import json
import os
import pathlib
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
PINS_FILE = "catalog/model-artifacts.json"
MODELS_FILE = "catalog/models.json"
DISCOVERY_FILE = "catalog/model-discovery.json"
# Published bundles of the experiment whose jobs name the artifact they loaded.
PUBLISHED = "docs/results/model-offloading"

HF_HOST = "huggingface.co"
ALLOWED_HOSTS = (HF_HOST,)
USER_AGENT = "llm-eval model_pins"
RETRIES = 5
RETRY_STATUSES = (429, 500, 502, 503, 504)
RETRY_AFTER_CAP = 120
RETRY_STEP = 10
TIMEOUT = 60
RUN_DEADLINE = 15 * 60            # seconds of network time per run; below the workflow's 20-minute job timeout
MAX_REDIRECTS = 5
MAX_BODY_BYTES = 16 * 2**20
MAX_TREE_PAGES = 20
NEW_MODELS_LIMIT = 50             # newest repositories read per publisher org
# The repository is not there for this caller. Unauthenticated Hugging Face answers 401 for a missing repository.
GONE_STATUSES = (401, 403, 404, 410)
STRING_CAP = 120
EXCERPT_CAP = 200
BODY_CAP = 60_000                 # GitHub refuses a pull request or issue body above 65,536 characters

REPO_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9_.-]+")
ORG_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*")
SHA_RE = re.compile(r"[0-9a-f]{40}")
SHA256_RE = re.compile(r"[0-9a-f]{64}")
DATE_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
# tokenizer_revision of a published model-offloading job: "<repo>@<40 hex> (...)". The text after the revision varies.
MEASURED_RE = re.compile(r"^([\w.-]+/[\w.-]+)@([0-9a-f]{40})")

GONE = ("Hugging Face does not serve the repository to this run (gone, renamed, private or gated, or the token was "
        "refused); nothing is changed")
PUBLISHER_MOVED = ("publisher repository moved; the catalog pin is reviewed by hand "
                   "(docs/MODELS.md, upstream_metadata, discovery anchors)")
MOVED_NOTE = (
    "A changed artifact revision is a new cohort. The next run loads the new revision, and its results belong to a "
    "different cohort from the results measured at the old one, even when the pinned files are byte-identical: the "
    "artifact lock records the revision and is part of the cohort. Published results keep their recorded revision; "
    "nothing under `docs/results/` is rewritten. A legal role bound to the old artifact stays bound to it: before "
    "the role uses the new revision it must be re-qualified, because its locked serving profile records the lock "
    "digest and the source revision of the artifact it was measured with. An artifact that is already downloaded "
    "and locked at the old revision still runs and stays the old cohort. The new pin reaches a run through "
    "`python scripts/model_pins.py --download-spec FILE` (`docs/MODELS.md`).")
NEW_MODELS_NOTE = (
    "A new model stays listed until it is added to `catalog/models.json`, an `hf:` decision in "
    "`catalog/model-discovery.json` covers it, or `new_models_since` in `catalog/model-artifacts.json` is moved past "
    "its creation date. This check does not judge size or license: the model discovery issue \"LiveBench models "
    "needing a catalog decision\" does that for the models LiveBench ranks (`docs/MODEL_DISCOVERY.md`).")
FAILED_NOTE = "A failed lookup settles nothing: the pin stays as it is, and this run does not close the tracking issue."
CUT_NOTE = ("This report was cut to fit the size GitHub accepts. The log of the run and a local "
            "`python3 scripts/model_pins.py` print every row.")


# --- sanitization: every string that upstream controls reaches a report only through md_code -----------
def _clean(value) -> str:
    """CR, LF and backticks removed; other whitespace collapsed; control and format characters dropped."""
    out = []
    for ch in str(value):
        if ch in "\r\n`":
            continue
        if ch.isspace():
            out.append(" ")
        elif unicodedata.category(ch) not in ("Cc", "Cf", "Co", "Cs"):
            out.append(ch)
    return re.sub(r" +", " ", "".join(out)).strip()


def md_code(value, cap=STRING_CAP) -> str:
    """Render a string so that nothing in it can render: one code span, at most `cap` characters."""
    text = _clean(value)
    if len(text) > cap:
        text = text[:cap - 1] + "…"
    text = text.replace("|", "\\|")
    return f"`{text}`" if text else "`(empty)`"


def short(revision) -> str:
    """The 12-character form of a full commit, as the tables show it; anything else as it is."""
    return revision[:12] if isinstance(revision, str) and SHA_RE.fullmatch(revision) else str(revision)


# --- network ------------------------------------------------------------------------------------------
class UpstreamError(Exception):
    """Hugging Face could not be read, or answered in a shape this check does not assume."""


class HttpStatus(UpstreamError):
    """A final non-2xx status; callers decide what each code means."""

    def __init__(self, code, url):
        super().__init__(f"HTTP {code} for {url}")
        self.code, self.url = code, url


class SameHostRedirect(urllib.request.HTTPRedirectHandler):
    """Follow at most MAX_REDIRECTS redirects, and only to https on the same host (urllib forwards Authorization)."""
    max_redirections = MAX_REDIRECTS

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        old, new = urllib.parse.urlsplit(req.full_url), urllib.parse.urlsplit(newurl)
        try:                           # the target passes the check every request passes: no userinfo, no other port
            Net.check_url(newurl)
            same = new.hostname == old.hostname and new.port == old.port
        except ValueError:
            same = False
        if not same:
            raise UpstreamError(f"unexpected redirect to {new.hostname or '?'} (HTTP {code})")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def next_link(header):
    """The rel="next" target of a Link header, or None."""
    for m in re.finditer(r"<([^>]*)>\s*((?:;[^,<]*)*)", header or ""):
        if re.search(r";\s*rel=\"?next\"?", m.group(2)):
            return m.group(1)
    return None


class Net:
    """The only code that touches the network. Tests replace it with a scripted fake.

    Every request of a run shares one deadline (RUN_DEADLINE from the start): once it has passed, or a retry would
    sleep past it, the request fails and its row is reported as failed, instead of the job being cancelled."""

    def __init__(self, env=None):
        env = os.environ if env is None else env
        self.token = env.get("HF_TOKEN") or ""
        self.opener = urllib.request.build_opener(SameHostRedirect)
        self.sleep = time.sleep
        self.clock = time.monotonic
        self.deadline = self.clock() + RUN_DEADLINE
        self.now = lambda: dt.datetime.now(dt.timezone.utc)

    @staticmethod
    def check_url(url):
        parts = urllib.parse.urlsplit(url)
        if parts.scheme != "https" or parts.hostname not in ALLOWED_HOSTS or parts.port not in (None, 443) \
                or parts.username or parts.password:
            raise ValueError(f"refusing to fetch {url!r}: only https to {', '.join(ALLOWED_HOSTS)}")
        return parts

    def headers(self):
        headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
        if self.token:                 # check_url admits huggingface.co only, so the token goes nowhere else
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def retry_delay(self, headers, attempt):
        """Retry-After as seconds or as an HTTP date, at most RETRY_AFTER_CAP; without one, RETRY_STEP per attempt."""
        value = (headers.get("Retry-After") or "").strip() if headers is not None else ""
        if value:
            seconds = None
            if value.isdigit():
                seconds = int(value)
            else:
                try:
                    when = email.utils.parsedate_to_datetime(value)
                    if when.tzinfo is None:
                        when = when.replace(tzinfo=dt.timezone.utc)
                    seconds = (when - self.now()).total_seconds()
                except (TypeError, ValueError, IndexError):
                    seconds = None
            if seconds is not None:
                return min(max(seconds, 0), RETRY_AFTER_CAP)
        return RETRY_STEP * attempt

    def _read(self, resp):
        chunks, size = [], 0
        while True:
            if self.clock() >= self.deadline:
                raise TimeoutError("run deadline passed while reading")
            chunk = resp.read(min(1 << 20, MAX_BODY_BYTES + 1 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
            if size > MAX_BODY_BYTES:
                raise UpstreamError(f"response over {MAX_BODY_BYTES} bytes")
        return b"".join(chunks)

    def get(self, url):
        """(response headers, parsed JSON body) of one GET; 429 and 5xx are retried within the run deadline."""
        parts = self.check_url(url)
        where, last = f"{parts.hostname}{parts.path}", "no attempt"
        out_of_time = f"no time left before the run deadline of {RUN_DEADLINE} s"
        for attempt in range(1, RETRIES + 1):
            remaining = self.deadline - self.clock()
            if remaining <= 0:
                raise UpstreamError(f"{where}: {last}; {out_of_time}")
            req = urllib.request.Request(url, headers=self.headers())
            try:
                with self.opener.open(req, timeout=min(TIMEOUT, remaining)) as resp:
                    body, headers = self._read(resp), resp.headers
            except urllib.error.HTTPError as exc:
                if exc.code not in RETRY_STATUSES:
                    raise HttpStatus(exc.code, url) from None
                last, delay = f"HTTP {exc.code}", self.retry_delay(exc.headers, attempt)
            except (OSError, http.client.HTTPException) as exc:
                # Transport faults: URLError, timeouts, resets, TLS errors, malformed status lines, incomplete reads.
                last, delay = type(exc).__name__, RETRY_STEP * attempt
            else:
                try:
                    return headers, json.loads(body.decode("utf-8"))
                except ValueError:
                    raise UpstreamError(f"{where}: the response is not JSON") from None
            if attempt < RETRIES:
                if self.clock() + delay >= self.deadline:
                    raise UpstreamError(f"{where}: {last}; {out_of_time}")
                self.sleep(delay)
        raise UpstreamError(f"{where}: {last} after {RETRIES} attempts")

    # --- Hugging Face views used by the checks ---------------------------------
    def revision(self, repo: str) -> dict:
        """Model info at the head of the default branch; the checks read its `sha`."""
        return self.get(f"https://{HF_HOST}/api/models/{urllib.parse.quote(repo, safe='/')}/revision/main")[1]

    def tree(self, repo: str, revision: str) -> list:
        """Every entry of the repository at `revision`, following the rel="next" pages."""
        url = (f"https://{HF_HOST}/api/models/{urllib.parse.quote(repo, safe='/')}/tree/"
               f"{urllib.parse.quote(revision, safe='')}?recursive=true")
        entries, pages = [], 0
        while url:
            if pages >= MAX_TREE_PAGES:
                raise UpstreamError(f"the file listing of {repo} has more than {MAX_TREE_PAGES} pages")
            headers, page = self.get(url)
            pages += 1
            if not isinstance(page, list):
                raise UpstreamError(f"expected a JSON array of files from {url}")
            entries += page
            url = next_link(headers.get("Link"))
        return entries

    def newest_models(self, org: str, limit: int) -> list:
        """The `limit` most recently created repositories of one org, newest first."""
        query = urllib.parse.urlencode({"author": org, "sort": "createdAt", "direction": -1, "limit": limit})
        return self.get(f"https://{HF_HOST}/api/models?{query}")[1]


# --- upstream values are validated before use -------------------------------------------------------------
def head_sha(doc) -> str:
    """The commit a revision answer names, once it is a full 40-hex sha."""
    sha = doc.get("sha") if isinstance(doc, dict) else None
    if not isinstance(sha, str) or not SHA_RE.fullmatch(sha):
        raise UpstreamError(f"expected a 40-hex sha in the revision answer; got {sha!r}")
    return sha


def tree_files(entries) -> dict:
    """path -> entry of the files in a tree listing."""
    if not isinstance(entries, list):
        raise UpstreamError(f"expected a list of tree entries; got {type(entries).__name__}")
    files = {}
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str) or not isinstance(entry.get("type"), str):
            raise UpstreamError(f"expected tree entries with a type and a path; got {entry!r}")
        if entry["type"] == "file":
            files[entry["path"]] = entry
    return files


def file_identity(entry: dict):
    """(bytes, sha256) of one listed file. The sha256 is the Git LFS object id; None for a file outside Git LFS,
    whose listing carries no content hash."""
    lfs = entry.get("lfs") if isinstance(entry.get("lfs"), dict) else {}
    oid = lfs.get("oid")
    if oid is None:
        size = entry.get("size")
    elif isinstance(oid, str) and SHA256_RE.fullmatch(oid):
        size = lfs.get("size")
    else:
        raise UpstreamError(f"expected a 64-hex lfs.oid for {entry['path']!r}; got {oid!r}")
    if not isinstance(size, int) or isinstance(size, bool) or size < 0:
        raise UpstreamError(f"expected a byte count for {entry['path']!r}; got {size!r}")
    return size, oid


def listed_models(entries, org: str) -> list:
    """(repository id, creation date) of every listed repository of `org`, in the listed order."""
    if not isinstance(entries, list):
        raise UpstreamError(f"expected a list of models; got {type(entries).__name__}")
    listed = []
    for entry in entries:
        repo = entry.get("id") if isinstance(entry, dict) else None
        if not isinstance(repo, str) or not REPO_RE.fullmatch(repo):
            raise UpstreamError(f"expected listing entries with an org/name id; got {repo!r}")
        created = entry.get("createdAt")
        if not isinstance(created, str) or not DATE_RE.fullmatch(created[:10]):
            raise UpstreamError(f"expected a createdAt date for {repo}; got {created!r}")
        if repo.split("/")[0].casefold() == org.casefold():
            listed.append((repo, created[:10]))
    return listed


# --- local inputs ------------------------------------------------------------------------------------------
def _dig(value, *keys):
    for key in keys:
        value = value.get(key) if isinstance(value, dict) else None
    return value


def published_use(root: pathlib.Path) -> dict:
    """model id -> (created_utc, artifact repository, revision, model file) of its newest published measurement.

    Read from the tracked model-offloading bundles: resolved-config.json names what each job loaded
    (config.tokenizer_revision starts with "<repo>@<40 hex>"), manifest.json dates the bundle (created_utc, one UTC
    spelling in every bundle, so the newest is the greatest text). A bundle or a job of another shape is skipped."""
    newest = {}
    for config in sorted((root / PUBLISHED).glob("*/resolved-config.json")):
        try:
            created = _dig(json.loads((config.parent / "manifest.json").read_text(encoding="utf-8")), "created_utc")
            jobs = _dig(json.loads(config.read_text(encoding="utf-8")), "jobs")
        except (OSError, ValueError):
            continue
        if not isinstance(created, str) or not DATE_RE.fullmatch(created[:10]) or not isinstance(jobs, list):
            continue
        for job in jobs:
            model = _dig(job, "parameters", "config", "model_id")
            found = MEASURED_RE.match(str(_dig(job, "parameters", "config", "tokenizer_revision") or ""))
            if isinstance(model, str) and found and (model not in newest or created > newest[model][0]):
                newest[model] = (created, found.group(1), found.group(2),
                                 _dig(job, "parameters", "config", "launch", "model_file"))
    return newest


def hf_decisions(doc) -> list:
    """The decisions of catalog/model-discovery.json whose key names a Hugging Face repository or family."""
    return [d for d in _dig(doc, "decisions") or []
            if isinstance(d, dict) and isinstance(d.get("key"), str) and d["key"].startswith("hf:")]


def decision_for(repo: str, decisions: list):
    """The hf: decision that covers `repo`, as scripts/model_discovery.py matches them (docs/MODEL_DISCOVERY.md):
    its exact key, else the longest name prefix of an hf:<org>/<name prefix>* key of the same org; case-insensitive."""
    key = repo.casefold()
    org, _, name = key.partition("/")
    best = None
    for decision in decisions:
        body = decision["key"][3:].casefold()
        if body == key:
            return decision
        if body.endswith("*"):
            family_org, _, prefix = body[:-1].partition("/")
            if family_org == org and name.startswith(prefix) and (best is None or len(prefix) > best[0]):
                best = (len(prefix), decision)
    return best[1] if best else None


# --- checks -------------------------------------------------------------------------------------------------
class Row:
    def __init__(self, name, pinned, policy):
        self.name, self.pinned, self.policy = name, pinned, policy
        self.latest, self.status, self.detail = None, "pending", ""
        self.changed = False
        self.org = None               # the publisher org of a new-model row; a long report counts such rows per org

    def done(self, latest, status, detail=""):
        self.latest, self.status, self.detail = latest, status, detail
        return self


def failed(row: Row, exc: Exception) -> Row:
    """A lookup that raised: its text reaches the reports as one code span, whatever upstream put in it."""
    text = str(exc) if isinstance(exc, UpstreamError) else f"{type(exc).__name__}: {exc}"
    return row.done(None, "failed", md_code(text, EXCERPT_CAP))


def joined(*parts) -> str:
    return "; ".join(part for part in parts if part)


def paths(names) -> str:
    return ", ".join(md_code(name, EXCERPT_CAP) for name in names)


def head_commit(net: Net, repo, row: Row):
    """The head commit of `repo`; None, with `row` marked manual, when Hugging Face does not serve the repository."""
    if not isinstance(repo, str) or not REPO_RE.fullmatch(repo):
        raise ValueError(f"not an org/name repository id: {repo!r}")
    try:
        return head_sha(net.revision(repo))
    except HttpStatus as exc:
        if exc.code not in GONE_STATUSES:
            raise
        row.done(f"HTTP {exc.code}", "manual", GONE)
        return None


def measured_note(entry: dict, measured: dict) -> str:
    """Whether the pin is the revision that the newest published measurement of the model loaded."""
    last = measured.get(entry.get("model_id"))
    if last is None:
        return ""
    created, repo, revision, _ = last
    if repo != entry.get("source_repo"):
        how = f"in {md_code(repo)}, not the pinned repository"
    else:
        how = "the pinned revision" if revision == entry.get("source_revision") else "not the pinned revision"
    return f"last measured: {md_code(short(revision))} on {created[:10]} ({how})"


def bump_artifact(net: Net, entry: dict, measured: dict, rows: list):
    """One artifact pin: follow the head commit of its repository while every pinned file is still published there."""
    row = Row(f"{md_code(entry.get('model_id'))} artifact", short(entry.get("source_revision")), "bump")
    rows.append(row)
    try:
        note = measured_note(entry, measured)
        repo, files = entry["source_repo"], entry["files"]
        head = head_commit(net, repo, row)
        if head is None:
            row.detail = joined(row.detail, note)
            return
        if head == entry["source_revision"]:
            row.done(short(head), "current", note)
            return
        listed = tree_files(net.tree(repo, head))
        missing = [f["path"] for f in files if f["path"] not in listed]
        if missing:
            row.done(short(head), "manual",
                     joined(f"file no longer published at {md_code(short(head))}: {paths(missing)}", note))
            return
        found = {f["path"]: file_identity(listed[f["path"]]) for f in files}
        unhashed = [path for path, (_, sha256) in found.items() if sha256 is None]
        if unhashed:
            row.done(short(head), "manual", joined(f"no Git LFS sha256 at {md_code(short(head))} for {paths(unhashed)}: "
                                                    "the content cannot be verified", note))
            return
        changed = [f["path"] for f in files if found[f["path"]] != (f["bytes"], f["sha256"])]
        detail = (f"weights changed ({paths(changed)}): results measured with the pinned revision are a different cohort"
                  if changed else "repository moved; pinned files unchanged")
        # Every value is resolved: only now is the entry rewritten, so a failed lookup never leaves half an entry.
        entry["source_revision"] = head
        for f in files:
            f["bytes"], f["sha256"] = found[f["path"]]
        row.done(short(head), "bump", joined(detail, note))
        row.changed = True
    except Exception as exc:  # noqa: BLE001 - reported, never fatal
        failed(row, exc)


def report_unpinned(pins: dict, measured: dict, rows: list):
    """A model that the published results measured and that has no pin: nothing tracked names what its next run loads."""
    pinned = {entry.get("model_id") for entry in pins["artifacts"]}
    for model in sorted(set(measured) - pinned):
        created, repo, revision, model_file = measured[model]
        where = f"repository {md_code(repo)}" + (f", file {md_code(model_file, EXCERPT_CAP)}" if isinstance(model_file, str) else "")
        rows.append(Row(f"{md_code(model)} published use", "not pinned", "report").done(
            short(revision), "manual",
            f"measured in published results but not pinned ({where}, last measured on {created[:10]})"))


def report_publisher(net: Net, entry: dict, catalog: dict, rows: list):
    """The publisher snapshot behind one pinned model. Drift is reported; catalog/models.json is never rewritten."""
    model_id, base = entry.get("model_id"), entry.get("base_model")
    model = catalog.get(model_id)
    if model is None:
        rows.append(Row(f"{md_code(model_id)} base model", str(base), "report").done(
            "not in the catalog", "manual", f"the pin names a model id that {MODELS_FILE} does not have"))
        return
    if base != model.get("upstream_repo"):
        rows.append(Row(f"{md_code(model_id)} base model", str(base), "report").done(
            str(model.get("upstream_repo")), "manual",
            "base_model is not the catalog upstream_repo; a run would refuse the lock"))
    row = Row(f"{md_code(model_id)} publisher snapshot", short(model.get("source_revision")), "report")
    rows.append(row)
    try:
        head = head_commit(net, model.get("upstream_repo"), row)
        if head is None:
            return
        if head == model.get("source_revision"):
            row.done(short(head), "current")
        else:
            row.done(short(head), "manual", PUBLISHER_MOVED)
    except Exception as exc:  # noqa: BLE001
        failed(row, exc)


def report_new_models(net: Net, pins: dict, catalog: dict, decisions: list, today: str, rows: list):
    """Repositories that the publisher orgs of the pinned models created since new_models_since and that the owner
    has not reviewed: neither a catalog upstream_repo nor covered by an hf: decision that still holds."""
    since = pins.get("new_models_since")
    if not isinstance(since, str) or not DATE_RE.fullmatch(since):
        rows.append(Row("new models", str(since), "report").done(
            None, "failed", f"new_models_since in {PINS_FILE} is not a YYYY-MM-DD date"))
        return
    known = {str(model.get("upstream_repo")).casefold() for model in catalog.values()}
    orgs = []
    for entry in pins["artifacts"]:
        org = str(entry.get("base_model")).split("/")[0]
        if org.casefold() not in {seen.casefold() for seen in orgs}:
            orgs.append(org)
    for org in orgs:
        try:
            if not ORG_RE.fullmatch(org):
                raise ValueError(f"not a Hugging Face org name: {org!r}")
            entries = net.newest_models(org, NEW_MODELS_LIMIT)
            listing = listed_models(entries, org)
        except Exception as exc:  # noqa: BLE001
            rows.append(failed(Row(f"new models from {md_code(org)}", f"since {since}", "report"), exc))
            continue
        for repo, created in listing:
            if created < since or repo.casefold() in known:
                continue
            decision = decision_for(repo, decisions)
            if decision is None:
                detail = f"created {created}; not in the catalog and no recorded decision"
            elif decision.get("decision") == "deferred" and isinstance(decision.get("until"), str) and decision["until"] < today:
                # A deferral holds until its date (docs/MODEL_DISCOVERY.md); after it the repository is raised again.
                detail = f"created {created}; not in the catalog; its recorded deferral ended on {md_code(decision['until'])}"
            else:
                continue
            rows.append(Row(f"new model {md_code(repo)}", "none", "report").done(created, "manual", detail))
            rows[-1].org = org
        if len(entries) >= NEW_MODELS_LIMIT and listing and min(created for _, created in listing) >= since:
            rows.append(Row(f"new models from {md_code(org)}", f"since {since}", "report").done(
                f"{NEW_MODELS_LIMIT} listed", "manual",
                f"the {NEW_MODELS_LIMIT} newest repositories were all created on or after {since}, so older ones "
                f"were not read; move new_models_since forward in {PINS_FILE} once these are reviewed"))


def run(net: Net, root: pathlib.Path, apply: bool, today: str):
    pins_path = root / PINS_FILE
    pins = json.loads(pins_path.read_text(encoding="utf-8"))
    before = json.dumps(pins, indent=2)
    catalog = {model["id"]: model for model in json.loads((root / MODELS_FILE).read_text(encoding="utf-8"))["models"]}
    decisions = hf_decisions(json.loads((root / DISCOVERY_FILE).read_text(encoding="utf-8")))
    measured = published_use(root)
    rows, touched = [], []

    for entry in pins["artifacts"]:
        bump_artifact(net, entry, measured, rows)
    moved = [row for row in rows if row.status == "bump"]
    report_unpinned(pins, measured, rows)
    for entry in pins["artifacts"]:
        report_publisher(net, entry, catalog, rows)
    first_new = len(rows)
    report_new_models(net, pins, catalog, decisions, today, rows)
    new_models = [row for row in rows[first_new:] if row.status == "manual"]

    changed = json.dumps(pins, indent=2) != before
    if not apply:  # report mode: nothing was bumped, only found
        for row in rows:
            row.changed = False
    if changed:
        pins["checked_on"] = today
        if apply:
            pins_path.write_text(json.dumps(pins, indent=2) + "\n", encoding="utf-8", newline="\n")
            touched.append(PINS_FILE)
    manual = [row for row in rows if row.status == "manual"]
    failures = [row for row in rows if row.status == "failed"]
    return {"rows": rows, "changed": changed, "applied": apply and changed, "touched": touched,
            "manual": manual, "failures": failures, "moved": moved, "new_models": new_models}


def counted_per_org(rows: list) -> list:
    """`rows` with the new-model rows of each publisher org replaced by one row that counts them."""
    groups = {}
    for row in rows:
        if row.org is not None:
            groups.setdefault(row.org, []).append(row.latest)
    out = []
    for row in rows:
        if row.org is None:
            out.append(row)
        elif row.org in groups:
            created = sorted(groups.pop(row.org))
            out.append(Row(f"{len(created)} new models from {md_code(row.org)}", "none", "report").done(
                f"{len(created)} new", "manual",
                f"{len(created)} repositories created from {created[0]} to {created[-1]} are not in the catalog and "
                "have no recorded decision; this report is too long to name each: the log of the run and a local "
                "`python3 scripts/model_pins.py` list them"))
    return out


def summary_text(result: dict, issue: bool, rows: list) -> str:
    manual = [r for r in rows if r.status == "manual"]
    lines = ["## Model pin check", "", "| Pin | Pinned | Upstream | Status | Detail |", "|---|---|---|---|---|"]
    for r in rows:
        status = {"bump": "bumped" if r.changed else "bump available"}.get(r.status, r.status)
        lines.append(f"| {r.name} | {md_code(r.pinned)} | {md_code(r.latest or '?')} | {status} | {r.detail} |")
    if result["moved"] and not issue:
        lines += ["", "### What moved and what it means for the next run", ""]
        lines += [f"- **{r.name}**: {md_code(r.pinned)} to {md_code(r.latest)}: {r.detail}" for r in result["moved"]]
        lines += ["", MOVED_NOTE]
        if result["touched"]:
            lines += ["", "Rewritten: " + ", ".join(f"`{rel}`" for rel in result["touched"]) + "."]
    if manual:
        lines += ["", "### Needs a manual decision", ""]
        lines += [f"- **{r.name}**: pinned {md_code(r.pinned)}, upstream {md_code(r.latest or '?')}: {r.detail}"
                  for r in manual]
        if result["new_models"]:
            lines += ["", NEW_MODELS_NOTE]
    if result["failures"]:
        lines += ["", "### Failed lookups", ""] + [f"- **{r.name}**: {r.detail}" for r in result["failures"]]
        lines += ["", FAILED_NOTE]
    return "\n".join(lines) + "\n"


def markdown_summary(result: dict, issue: bool = False) -> str:
    """The pull request body; with issue=True the tracking-issue body, which leaves out the section that only
    describes the pull request's diff.

    At most BODY_CAP characters, because GitHub refuses a longer body and the nightly job would then fail every
    night: a report above the cap counts the new models per publisher org instead of naming each one, and a report
    that is still above it is cut at a line end."""
    text = summary_text(result, issue, result["rows"])
    if len(text) > BODY_CAP:
        text = summary_text(result, issue, counted_per_org(result["rows"]))
    if len(text) > BODY_CAP:
        kept = text[:BODY_CAP - len(CUT_NOTE) - 2]
        text = kept[:kept.rfind("\n") + 1] + "\n" + CUT_NOTE + "\n"
    return text


def download_spec(pins: dict, selected=None) -> dict:
    """A download manifest in the shape of configs/workflows/download.example.json for the pinned artifacts, or for
    the `selected` catalog ids. accept_license is false: llm_eval.model_download refuses the manifest until the
    operator has reviewed the license and set it."""
    pinned = [entry["model_id"] for entry in pins["artifacts"]]
    if selected is not None:
        if not selected:
            raise ValueError("--models names no model id")
        unknown = [model for model in selected if model not in pinned]
        if unknown:
            raise ValueError(f"no artifact pin in {PINS_FILE} for: {', '.join(unknown)}")
    return {"models": [{"model_id": entry["model_id"], "source_repo": entry["source_repo"],
                        "source_revision": entry["source_revision"], "precision": entry["precision"],
                        "include": [f["path"] for f in entry["files"]],
                        "artifact_root": f"models/{entry['model_id']}",
                        "artifact_lock": f"artifacts/{entry['model_id']}.lock.json",
                        "accept_license": False}
                       for entry in pins["artifacts"] if selected is None or entry["model_id"] in selected]}


# --- CLI ----------------------------------------------------------------------------------------------------
def write(path, text):
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)      # configs/local/ of the documented command is absent in a fresh clone
    path.write_text(text, encoding="utf-8", newline="\n")


def emit(text, stream=None):
    """Print without failing on a console whose encoding lacks a character (cp1252 on Windows)."""
    stream = stream or sys.stdout
    encoding = getattr(stream, "encoding", None) or "utf-8"
    stream.write(text.encode(encoding, errors="replace").decode(encoding, errors="replace") + "\n")
    stream.flush()


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="rewrite catalog/model-artifacts.json where a pin moved")
    ap.add_argument("--summary", metavar="FILE", help="write the Markdown pull request body here")
    ap.add_argument("--issue-summary", metavar="FILE", help="write the Markdown tracking-issue body here")
    ap.add_argument("--github-output", action="store_true", help="append changed=/manual=/failed= to $GITHUB_OUTPUT")
    ap.add_argument("--strict", action="store_true", help="exit 1 if any lookup failed")
    ap.add_argument("--download-spec", metavar="FILE",
                    help="no network: write a download manifest for the pinned artifacts here")
    ap.add_argument("--models", metavar="ID,ID", help="with --download-spec: only these catalog model ids")
    return ap


def main(argv=None, net=None, root=ROOT, today=None) -> int:
    ap = parser()
    args = ap.parse_args(argv)
    if args.download_spec:
        if args.apply or args.summary or args.issue_summary or args.github_output or args.strict:
            ap.error("--download-spec writes a manifest and runs no check: it combines with --models only")
        pins = json.loads((pathlib.Path(root) / PINS_FILE).read_text(encoding="utf-8"))
        selected = None if args.models is None else [model.strip() for model in args.models.split(",") if model.strip()]
        try:
            manifest = download_spec(pins, selected)
        except ValueError as exc:
            ap.error(str(exc))
        write(args.download_spec, json.dumps(manifest, indent=2) + "\n")
        emit(f"{len(manifest['models'])} pinned artifact(s) written to {args.download_spec}; "
             "accept_license is false until the license is reviewed")
        return 0
    if args.models is not None:
        ap.error("--models needs --download-spec")
    result = run(net if net is not None else Net(), pathlib.Path(root), args.apply,
                 today or dt.datetime.now(dt.timezone.utc).date().isoformat())
    for r in result["rows"]:
        verdict = "bumped" if r.changed else {"bump": "bump available"}.get(r.status, r.status)
        emit(f"{r.name:44} {r.pinned:>16} -> {str(r.latest):<16} {verdict}" + (f"  ({r.detail})" if r.detail else ""))
    if args.summary:
        write(args.summary, markdown_summary(result))
    if args.issue_summary:
        write(args.issue_summary, markdown_summary(result, issue=True))
    if args.github_output and os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8", newline="\n") as fh:
            fh.write(f"changed={'true' if result['applied'] else 'false'}\n")
            fh.write(f"manual={'true' if result['manual'] else 'false'}\n")
            fh.write(f"failed={'true' if result['failures'] else 'false'}\n")
    if result["failures"]:
        emit(f"{len(result['failures'])} lookup(s) failed", sys.stderr)
        return 1 if args.strict else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
