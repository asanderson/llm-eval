#!/usr/bin/env python3
"""Nightly LiveBench model discovery: newest release -> high-scoring self-hosted
open-weight models the catalog has not reviewed -> one tracking issue.

  python3 scripts/model_discovery.py                         plain report on stdout; writes no files
  python3 scripts/model_discovery.py --issue-summary FILE    issue body (complete runs only)
  python3 scripts/model_discovery.py --comment FILE          "new since the last refresh" or the close comment
  python3 scripts/model_discovery.py --previous-issue FILE   current issue body (its state marker drives new=)
  python3 scripts/model_discovery.py --failure-summary FILE  issue body with a failure block (failed runs only)
  python3 scripts/model_discovery.py --step-summary FILE     always written (appended)
  python3 scripts/model_discovery.py --json FILE             machine-readable results
  python3 scripts/model_discovery.py --github-output         append complete=/reportable=/new= to $GITHUB_OUTPUT
  python3 scripts/model_discovery.py --record DIR            save raw responses (never request headers)
  python3 scripts/model_discovery.py --release ID            analyse this release (v1 YYYY-MM-DD, 2.0 YYYYMMDD)
  python3 scripts/model_discovery.py --probe                 print upstream shapes; enforces nothing

What a run does (docs/MODEL_DISCOVERY.md):
  1. validates catalog/models.json, catalog/livebench-evidence.json, catalog/benchmarks.json,
     catalog/model-discovery.json and the laptop budgets before any network access;
  2. reads livebench.ai: the page's main script (named by asset-manifest.json and index.html) carries
     both release lists (v1 and 2.0) and LiveBench's model registry; release files are read from
     /v1/ and /data/<id>/ and identified by their sha256 (the site serves no versioned history);
  3. calibrates the CSV parser and the two-level mean against the rows recorded in
     catalog/livebench-evidence.json (hash-pinned v1 tables), and the Hugging Face metadata shape
     against four catalog models;
  4. scores the newest release (2.0: the site's weighted suite mean), walks it from the top until the
     10 best entries that could be self-hosted open-weight models are seen (ties included), resolves
     each strictly to a repository of an owner-approved publisher org (or the repository LiveBench's
     registry links, inside those orgs) and sizes it with the catalog arithmetic.

It never writes inside the repository. Exit codes: 0 complete (or a probe), 1 network
failure, 2 upstream shape changed or invalid local input, 3 unexpected internal error.
HF_TOKEN (optional) authenticates huggingface.co; no token is ever sent to livebench.ai.
"""
import argparse
import ast
import base64
import collections
import csv
import dataclasses
import datetime as dt
import decimal
import email.utils
import hashlib
import http.client
import io
import json
import math
import os
import pathlib
import re
import sys
import time
import traceback
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]

# --- constants (each pinned by tests/test_model_discovery.py) --------------------------------
POOL_SIZE = 10
MIN_RELEASE_ROWS = 20
MAX_MODEL_INFO = 40
MAX_LISTING_PAGES = 20            # per org
MAX_LISTING_PAGES_RUN = 80        # per run
LISTING_LIMIT = 1000
WORKING_SET_RESERVE_GIB = 4
PRECISION_BITS = {"Q4_K_M": 4.8, "Q5_K_M": 5.7, "Q6_K": 6.6, "Q8_0": 8.5, "BF16": 16}
INFO_BITS = {"IQ2_XS": 2.31}      # shown for too-large rows only
INT_SHARE_MAX = 0.01
SIZE_RATIO = (0.90, 1.15)
PACKED_NAME_RANGE = (0.90, 1.05)
OVERALL_TOL = 0.005 + 1e-9
CATEGORY_TOL = 1e-6
SCORE_RANGE = (0.0, 100.0)
MAX_TABLE_BYTES = 8 * 2**20
MAX_BODY_BYTES = 32 * 2**20
RETRIES = 5
RETRY_AFTER_CAP = 120
RETRY_STEP = 10
TIMEOUT = 60
RUN_DEADLINE = 15 * 60            # seconds of network time per run; below the workflow's 20-minute job timeout
MAX_REDIRECTS = 5
RECORD_BODY_CAP = 4 * 2**20
RECORD_TOTAL_CAP = 64 * 2**20
ISSUE_BODY_CAP = 60_000
STRING_CAP = 120
EXCERPT_CAP = 200
LIST_CAP = 30
MARKER_CAP = 32 * 1024
FAILURE_STREAK = 3
DEFERRAL_MAX_DAYS = 365
HF_ANCHORS = ("qwen38-27b", "nemotron-super-120b", "gpt-oss-120b", "llama33-70b")
ANCHOR_CLASSES = {"qwen38-27b": "float", "nemotron-super-120b": "packed", "gpt-oss-120b": "packed", "llama33-70b": "float"}
CANARY_ORGS = ("deepseek-ai", "zai-org", "microsoft", "mistralai", "nvidia")   # derived at run time; a test pins the derivation

HF_HOST = "huggingface.co"
LIVEBENCH_SITE = "livebench.ai"
SITE_URL = f"https://{LIVEBENCH_SITE}/"
ALLOWED_HOSTS = (HF_HOST, LIVEBENCH_SITE)
USER_AGENT = "llm-eval model_discovery"
RETRY_STATUSES = (429, 500, 502, 503, 504)
SITE_TYPES = {"html": ("text/html",), "json": ("application/json",), "csv": ("text/csv",),
              "js": ("application/javascript", "text/javascript")}
WEIGHTS_KEY = "_overall_weights"
# The order the site adds a 2.0 release's suites in: rn() sorts them by their index in this list (unknown suites last),
# and the averaging code sums in that order, which can move an overall across a .xx5 rounding boundary. Read from
# the main script each run; this is the list of the reviewed script (main.1e1ce12d.js), used when it cannot be read.
REVIEWED_SUITE_ORDER = ("Long Agentic", "Design", "Coding", "Browser", "Data Analysis", "Research", "Reasoning")
GENERATIONS = ("v1", "2.0")

HARDWARE_CONFIG = "configs/hardware/msi-raider-18-hx-ai.json"
WSL_PROFILE = "windows-11-wsl2-ubuntu-26.04"
NATIVE_PROFILE = "configs/os/ubuntu-26.04-native.json"
SCORER_SOURCE = "src/llm_eval/livebench.py"
DISCOVERY_FILE = "catalog/model-discovery.json"

ALLOWED_EXTRAS = frozenset({"instruct", "it", "chat", "hf", "bf16", "fp16", "f16"})
STRIP_TOKENS = frozenset({"high", "medium", "low", "minimal", "xhigh", "thinking", "nothinking", "nonthinking",
                          "nothink", "think", "turbo"})
PRECISION_TOKENS = frozenset({"bf16", "fp16", "f16", "fp32", "fp8", "f8", "fp4", "nvfp4", "mxfp4", "int4", "int8",
                              "w4a16", "w8a8", "awq", "gptq", "gguf", "exl2", "mlx", "onnx", "4bit", "8bit",
                              "dynamic", "quantized"})
INT_DTYPES = ("U8", "I8", "U16", "I16", "U32", "I32", "U64", "I64", "BOOL")
MISSING_MARKERS = frozenset({"", "-", "nan", "null", "none", "n/a"})
CATEGORY_FOLDS = {"if": "instruction following", "math": "mathematics"}
DECISION_TYPES = ("rejected", "deferred", "not_open_weight", "alias")
DECISION_FIELDS = ("key", "decision", "reason", "decided_on", "until", "target", "release")
RUNNABLE_STATUSES = ("candidate", "conditional", "control")
FIT_CLASSES = ("control_only", "offload", "high_memory", "too_large")

REPO_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9_.-]+$")
ORG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
NAME_PREFIX_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# Accepted catalog/livebench-evidence.json source_table forms: the recorded GitHub blobs (that repository answers 404
# since 2026-11-08; the same bytes are served at livebench.ai/v1/) and the two livebench.ai forms.
GITHUB_TABLE_RE = re.compile(r"^https://github\.com/([^/]+/[^/]+)/blob/([0-9a-f]{40})/public/(table_(\d{4})_(\d{2})_(\d{2})\.csv)$")
SITE_V1_TABLE_RE = re.compile(r"^https://livebench\.ai/v1/(table_(\d{4})_(\d{2})_(\d{2})\.csv)$")
SITE_V2_TABLE_RE = re.compile(r"^https://livebench\.ai/data/((\d{4})(\d{2})(\d{2}))/table\.csv$")
SCRIPT_PATH_RE = re.compile(r"^static/js/[A-Za-z0-9_.-]+\.js$")
V1_ID_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
V2_ID_RE = re.compile(r"^\d{8}$")
# The release lists of the main script, anchored on the gen:"v1" / gen:"v2" maps and the quoted shapes, never on the
# minified identifiers (they change between builds). v1: an inline list mapped to gen:"v1"; 2.0: the one assigned
# array of quoted YYYYMMDD ids (the gen:"v2" map reaches it through an identifier, so it is matched by its shape).
JS_ID = r"[A-Za-z_$][\w$]*"
V1_LIST_RE = re.compile(r'\[((?:"\d{4}-\d{2}-\d{2}",)*"\d{4}-\d{2}-\d{2}")\]\.map\(\(?(' + JS_ID + r')\)?=>\(\{id:\2,label:\2,gen:"v1"\}\)\)')
V2_MAP_RE = re.compile(r'\.map\(\(?(' + JS_ID + r')\)?=>\(\{id:\1,label:' + JS_ID + r'\(\1\),gen:"v2"\}\)\)')
V2_LIST_RE = re.compile(r'(?<![\w$.])' + JS_ID + r'=\[((?:"\d{8}",)*"\d{8}")\]')
GEN_RE = re.compile(r'gen:"(v1|v2)"')
# An object literal assigned to an identifier whose first value is an object; the minifier leaves an identifier-shaped
# (or numeric) key unquoted, so the first key may be quoted, an identifier or a number.
REGISTRY_START_RE = re.compile(r'(?<![\w$.])' + JS_ID + r'=(?=\{(?:"[^"\\]+"|' + JS_ID + r'|\d+):\{)')
OPENWEIGHT_MARK = "openweight:!0"
# rn() of the reviewed script: X=["Long Agentic",...];function rn(e){const t=e=>{const t=X.indexOf(e);return t<0?
# X.length:t}...: the list of quoted suite names whose index orders the suites, unknown ones last.
SUITE_ORDER_RE = re.compile(r'(?<![\w$.])(' + JS_ID + r')=\[((?:"[^"\\]+",)*"[^"\\]+")\][;,][^;]{0,160}?(?<![\w$.])\1'
                            r'\.indexOf\(' + JS_ID + r'\);return ' + JS_ID + r'<0\?\1\.length:')
HF_LINK_RE = re.compile(r"^https://huggingface\.co/([A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9_.-]+)/?$")
SIZE_RE = re.compile(r"^\d+(\.\d+)?b$")
ACTIVE_RE = re.compile(r"^a\d+(\.\d+)?b$")
EXPERT_RE = re.compile(r"^\d+e$")
MULTI_RE = re.compile(r"^\d+x\d+b$")
BUDGET_RE = re.compile(r"^\d+k$")
NUMBER_RE = re.compile(r"^[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?$")
TABLE_NAME_RE = re.compile(r"^table_(\d{4})_(\d{2})_(\d{2})\.csv$")
LICENSE_FILE_RE = re.compile(r"^(LICENSE(\.md|\.txt)?|LICENCE[A-Za-z0-9._-]*)$", re.I)
SAFE_FILE_RE = re.compile(r"^[A-Za-z0-9._-]+$")
SCRIPT_SRC_RE = re.compile(r"""<script\b[^>]*?\bsrc=["']([^"']+)["']""", re.I)
MARKER_RE = re.compile(r"<!-- model-discovery-state v1 ([A-Za-z0-9_=-]*) -->")
FAILURE_BLOCK_RE = re.compile(r"### Problems reading sources\n.*?<!-- model-discovery-failure-end -->\n*", re.S)

DISCLAIMER = (
    "Scores are LiveBench's published scores for the source checkpoints in release {release}. They rank models only "
    "within that release; they are not comparable with other releases (including the older-release scores in "
    "catalog/livebench-evidence.json) and are not local, quantized or engine-specific results. LiveBench may have "
    "served a model through a hosted provider at its own precision and reasoning settings. Fit is planning "
    "arithmetic (GiB = 2^30 bytes) on the published parameter count, for weights only. Nothing here edits the "
    "catalog: adding a model still needs review of its license file, a real artifact, engine architecture support "
    "and measured fit.")
PLANNING_CAVEAT = (
    "Planning arithmetic on the published parameter count, weights only. KV cache, activations, staging, duplicated "
    "host weights, loader peaks, dense-vs-MoE decode cost and engine architecture support are not verified.")
NOTHING_NEEDED = ("Nothing needs a decision: the {n} best entries of {release} that could be self-hosted are all "
                  "catalogued or decided.")
LOOK_WORDS = {
    "unknown_publisher": "no publisher entry in catalog/model-discovery.json matches this leaderboard id",
    "no_repo": "no repository of the publisher's orgs matches the leaderboard id strictly",
    "ambiguous": "more than one repository of the publisher's orgs matches strictly",
    "size_unverified": "the parameter count cannot be verified from the safetensors metadata",
    "size_mismatch": "the size in the name disagrees with the safetensors parameter count",
    "no_license": "the repository carries no license metadata",
    "info_unreadable": "Hugging Face did not answer the model-info request for the matched repository",
    "moved_outside_publisher": "the repository now resolves outside the publisher's orgs",
    "not_checked": "not checked: the model-info budget of this run was spent",
    "deferral_expired": "the recorded deferral has expired",
    "weights_may_be_public": "recorded (or listed by LiveBench) as not open weight, but a repository of an allowlisted org now matches",
    "linked_outside_publisher": "LiveBench's registry links a Hugging Face repository outside the publisher's allowlisted orgs",
    "alias_target_unavailable": "the alias target is unavailable (unreadable, private, disabled or outside the publisher's orgs)",
}


# --- errors --------------------------------------------------------------------------------
class DiscoveryError(Exception):
    exit_code = 3


class ConfigError(DiscoveryError):
    """Invalid local input (exit 2)."""
    exit_code = 2


class ShapeError(DiscoveryError):
    """An upstream source no longer has the shape the pipeline assumes (exit 2)."""
    exit_code = 2

    def __init__(self, expected, got="", stage=None, fix=""):
        super().__init__(f"expected {expected}; got {got}" if got else str(expected))
        self.expected, self.got, self.stage, self.fix = str(expected), str(got), stage, str(fix)


class NetworkError(DiscoveryError):
    """Upstream unreachable after the retries (exit 1)."""
    exit_code = 1


class HttpStatus(NetworkError):
    """A final non-2xx status; callers decide what each code means."""

    def __init__(self, code, url):
        super().__init__(f"HTTP {code} for {url}")
        self.code, self.url = code, url


# --- sanitization ----------------------------------------------------------------------------
def _clean(value):
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


def md_code(value, cap=STRING_CAP):
    """Render an upstream string so that nothing in it can render: one code span, at most `cap` characters."""
    text = _clean(value)
    if len(text) > cap:
        text = text[:cap - 1] + "…"
    text = text.replace("|", "\\|")
    return f"`{text}`" if text else "`(empty)`"


def plain(value, cap=STRING_CAP):
    """Terminal-safe: control characters removed, cut to `cap`."""
    text = _clean(value)
    return text if len(text) <= cap else text[:cap - 1] + "…"


def excerpt(data, cap=EXCERPT_CAP):
    if isinstance(data, bytes):
        data = data.decode("utf-8", errors="replace")
    text = _clean(data)
    return text if len(text) <= cap else text[:cap - 1] + "…"


def iso_date(value):
    if not isinstance(value, str) or not DATE_RE.match(value):
        raise ValueError("not an ISO date")
    return dt.date.fromisoformat(value)


def fmt(x, digits=2):
    return "n/a" if x is None else f"{x:.{digits}f}"


def gib(parameters, bits):
    """Planning GiB of weights, identical to llm_eval.catalog.estimate_weights (parameters in units, not billions)."""
    return parameters * bits / 8 / 2**30


def compact(obj):
    return json.dumps(obj, separators=(",", ":"), sort_keys=True, ensure_ascii=True)


def snippet(obj):
    return json.dumps(obj, ensure_ascii=True)


# --- network ---------------------------------------------------------------------------------
@dataclasses.dataclass
class Reply:
    url: str
    status: int
    headers: dict
    body: bytes

    def json(self):
        try:
            return json.loads(self.body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise ShapeError(f"a JSON response from {self.url}", got=excerpt(self.body)) from None


class SameHostRedirect(urllib.request.HTTPRedirectHandler):
    """Follow at most MAX_REDIRECTS redirects, and only to https on the same host (urllib forwards Authorization)."""
    max_redirections = MAX_REDIRECTS

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        old, new = urllib.parse.urlsplit(req.full_url), urllib.parse.urlsplit(newurl)
        if new.scheme != "https" or new.hostname != old.hostname or new.port != old.port:
            raise ShapeError(f"unexpected redirect to {new.hostname or '?'}", got=f"HTTP {code}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _lower_headers(headers):
    return {k.lower(): v for k, v in (headers.items() if headers is not None else [])}


class Net:
    """The only code that touches the network. Tests replace it with a scripted fake.

    Every request of a run shares one deadline (RUN_DEADLINE from the start): once it has passed, or a retry would
    sleep past it, the request fails with NetworkError (exit 1) instead of the job being cancelled at its timeout."""

    def __init__(self, record_dir=None, env=None):
        env = os.environ if env is None else env
        self.tokens = {HF_HOST: env.get("HF_TOKEN") or ""}       # never a token for livebench.ai
        self.opener = urllib.request.build_opener(SameHostRedirect)
        self.sleep = time.sleep
        self.clock = time.monotonic
        self.deadline = self.clock() + RUN_DEADLINE
        self.now = lambda: dt.datetime.now(dt.timezone.utc)
        self.counts = collections.Counter()
        self.record_dir = pathlib.Path(record_dir) if record_dir else None
        self.recorded_bytes = 0
        self.index = []

    @staticmethod
    def check_url(url):
        parts = urllib.parse.urlsplit(url)
        if parts.scheme != "https" or parts.hostname not in ALLOWED_HOSTS or parts.port not in (None, 443) \
                or parts.username or parts.password:
            raise ValueError(f"refusing to fetch {url!r}: only https to {', '.join(ALLOWED_HOSTS)}")
        return parts

    def headers_for(self, host):
        accept = {HF_HOST: "application/json"}.get(host, "*/*")
        headers = {"User-Agent": USER_AGENT, "Accept": accept}
        if self.tokens.get(host):
            headers["Authorization"] = f"Bearer {self.tokens[host]}"
        return headers

    def retry_delay(self, headers, attempt):
        value = (headers.get("retry-after") or "").strip()
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

    def _read(self, resp, cap):
        chunks, size = [], 0
        while True:
            if self.clock() >= self.deadline:
                raise TimeoutError("run deadline passed while reading")
            chunk = resp.read(min(1 << 20, cap + 1 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
            if size > cap:
                raise ShapeError(f"response over {cap} bytes", got=f"more than {cap} bytes")
        return b"".join(chunks)

    def past_deadline(self, host, path, last):
        return NetworkError(f"{host}{path}: {last}; no time left before the run deadline of {RUN_DEADLINE} s")

    def get(self, url, cap=MAX_BODY_BYTES):
        parts = self.check_url(url)
        host = parts.hostname
        last = "no attempt"
        for attempt in range(1, RETRIES + 1):
            remaining = self.deadline - self.clock()
            if remaining <= 0:
                raise self.past_deadline(host, parts.path, last)
            self.counts[host] += 1
            req = urllib.request.Request(url, headers=self.headers_for(host))
            try:
                with self.opener.open(req, timeout=min(TIMEOUT, remaining)) as resp:
                    body = self._read(resp, cap)
                    status, headers = resp.status, _lower_headers(resp.headers)
            except urllib.error.HTTPError as exc:
                headers = _lower_headers(exc.headers)
                try:
                    body = exc.read(RECORD_BODY_CAP) if exc.fp is not None else b""
                except (OSError, ValueError, http.client.HTTPException):
                    body = b""
                self.record(url, exc.code, headers, body)
                if exc.code not in RETRY_STATUSES:
                    raise HttpStatus(exc.code, url) from None
                last, delay = f"HTTP {exc.code}", self.retry_delay(headers, attempt)
            except (OSError, http.client.HTTPException) as exc:
                # Transport faults: URLError (connect phase), timeouts, resets, TLS errors (ssl.SSLError), malformed
                # status lines (BadStatusLine, LineTooLong), IncompleteRead and other socket errors from
                # getresponse() or read(), which urllib does not wrap.
                last, delay = type(exc).__name__, RETRY_STEP * attempt
            else:
                # Outside the try: a fault writing the --record directory is local, never retried as a network fault.
                self.record(url, status, headers, body)
                return Reply(url, status, headers, body)
            if attempt < RETRIES:
                if self.clock() + delay >= self.deadline:
                    raise self.past_deadline(host, parts.path, last)
                self.sleep(delay)
        raise NetworkError(f"{host}{parts.path}: {last} after {RETRIES} attempts")

    def record(self, url, status, headers, body):
        if not self.record_dir:
            return
        self.record_dir.mkdir(parents=True, exist_ok=True)
        number = len(self.index) + 1
        entry = {"url": url, "status": status, "content_type": headers.get("content-type"),
                 "link": headers.get("link"), "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest(),
                 "file": None}
        if len(body) <= RECORD_BODY_CAP and self.recorded_bytes + len(body) <= RECORD_TOTAL_CAP:
            name = f"{number:04d}.body"
            (self.record_dir / name).write_bytes(body)
            self.recorded_bytes += len(body)
            entry["file"] = name
        self.index.append(entry)
        (self.record_dir / "index.json").write_text(json.dumps(self.index, indent=2) + "\n", encoding="utf-8",
                                                    newline="\n")


# --- local inputs (validated before any network access) -----------------------------------
@dataclasses.dataclass
class CatalogModel:
    id: str
    repo: str
    status: str
    parameters_b: object
    metadata: object


@dataclasses.dataclass
class Recommendation:
    model_id: str
    lb_id: str
    release: str
    overall: float
    category_scores: dict
    source_table: str
    site_path: str          # the bytes on livebench.ai: v1/table_YYYY_MM_DD.csv or data/YYYYMMDD/table.csv
    sha256: str
    generation: str         # v1 | 2.0

    @property
    def table_name(self):
        return self.site_path.split("/", 1)[1]


@dataclasses.dataclass
class Evidence:
    repo: str
    revision: str
    latest_release: str
    recommendations: list
    excluded: list
    meaning: str


@dataclasses.dataclass
class Benchmarks:
    reference_release: str
    categories: dict
    partition: frozenset


@dataclasses.dataclass
class Budgets:
    vram: float      # V
    wsl: float       # W
    native: float    # M
    native_ram: float


@dataclasses.dataclass
class SiteReview:
    main_script: str      # the main script whose averaging code the owner read
    reviewed_on: str


@dataclasses.dataclass
class Publisher:
    prefixes: tuple
    orgs: tuple


def partition(categories):
    return frozenset(frozenset(tasks) for tasks in categories.values())


def fold_category(name):
    key = " ".join(str(name).casefold().split())
    return CATEGORY_FOLDS.get(key, key)


def _read_json(root, rel):
    try:
        return json.loads((root / rel).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ConfigError(f"{rel}: cannot read ({type(exc).__name__}: {exc})") from None


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def parse_models(doc):
    if not isinstance(doc, dict) or not isinstance(doc.get("models"), list):
        raise ConfigError("catalog/models.json: expected an object with a models list")
    models = []
    for i, m in enumerate(doc["models"]):
        where = f"catalog/models.json models[{i}]"
        if not isinstance(m, dict) or not isinstance(m.get("id"), str):
            raise ConfigError(f"{where}: id must be a string")
        if not isinstance(m.get("upstream_repo"), str) or not REPO_RE.match(m["upstream_repo"]):
            raise ConfigError(f"{where}.upstream_repo: expected org/name")
        if m.get("status") not in ("candidate", "conditional", "control", "excluded"):
            raise ConfigError(f"{where}.status: unknown status")
        if m.get("parameters_b") is not None and not _number(m["parameters_b"]):
            raise ConfigError(f"{where}.parameters_b: expected a number or null")
        meta = m.get("upstream_metadata")
        if meta is not None:
            if not isinstance(meta, dict) or set(meta) != {"id", "sha", "gated", "safetensors"}:
                raise ConfigError(f"{where}.upstream_metadata: expected exactly id, sha, gated, safetensors")
            if not isinstance(meta["id"], str) or not REPO_RE.match(meta["id"]) or not SHA_RE.match(str(meta["sha"])):
                raise ConfigError(f"{where}.upstream_metadata: id must be org/name and sha 40 lowercase hex")
            if meta["safetensors"] is not None and _safetensors(meta["safetensors"]) is None:
                raise ConfigError(f"{where}.upstream_metadata.safetensors: expected {{parameters: {{DTYPE: count}}, total}}")
        models.append(CatalogModel(m["id"], m["upstream_repo"], m["status"], m.get("parameters_b"), meta))
    if len({m.id for m in models}) != len(models):
        raise ConfigError("catalog/models.json: duplicate model id")
    return models


def parse_source_table(url):
    """(site path, generation, GitHub repo or None, GitHub commit or None, table date) of an evidence source_table,
    or None when the URL has none of the accepted forms."""
    url = str(url)
    m = GITHUB_TABLE_RE.match(url)
    if m:
        return f"v1/{m.group(3)}", "v1", m.group(1), m.group(2), "-".join(m.group(4, 5, 6))
    m = SITE_V1_TABLE_RE.match(url)
    if m:
        return f"v1/{m.group(1)}", "v1", None, None, "-".join(m.group(2, 3, 4))
    m = SITE_V2_TABLE_RE.match(url)
    if m:
        return f"data/{m.group(1)}/table.csv", "2.0", None, None, "-".join(m.group(2, 3, 4))
    return None


def parse_evidence(doc, models_by_id):
    rel = "catalog/livebench-evidence.json"
    if not isinstance(doc, dict) or not isinstance(doc.get("recommendations"), list) or not doc["recommendations"]:
        raise ConfigError(f"{rel}: expected a non-empty recommendations list")
    revision = doc.get("leaderboard_revision")
    if revision is not None and (not isinstance(revision, str) or not SHA_RE.match(revision)):
        raise ConfigError(f"{rel}: leaderboard_revision must be 40 lowercase hex")
    try:
        latest = iso_date(doc.get("latest_release")).isoformat()
    except ValueError:
        raise ConfigError(f"{rel}: latest_release must be an ISO date") from None
    repos, commits, recs, meanings = set(), set(), [], set()
    for i, r in enumerate(doc["recommendations"]):
        where = f"{rel} recommendations[{i}]"
        if not isinstance(r, dict):
            raise ConfigError(f"{where}: expected an object")
        source = parse_source_table(r.get("source_table", ""))
        if source is None:
            raise ConfigError(f"{where}.source_table: expected https://livebench.ai/v1/table_YYYY_MM_DD.csv, "
                              "https://livebench.ai/data/YYYYMMDD/table.csv or "
                              "https://github.com/OWNER/REPO/blob/<40 hex>/public/table_YYYY_MM_DD.csv")
        site_path, generation, repo, commit, table_date = source
        try:
            dt.date.fromisoformat(table_date)
        except ValueError:
            name = site_path.rsplit("/", 1)[1] if generation == "v1" else site_path.split("/")[1]
            raise ConfigError(f"{where}.source_table: {name} does not name a calendar date") from None
        if repo is not None:
            repos.add(repo)
            commits.add(commit)
        if r.get("model_id") not in models_by_id:
            raise ConfigError(f"{where}.model_id: not a catalog/models.json id")
        if not isinstance(r.get("leaderboard_model_id"), str) or not r["leaderboard_model_id"]:
            raise ConfigError(f"{where}.leaderboard_model_id: expected a non-empty string")
        if not _number(r.get("overall")):
            raise ConfigError(f"{where}.overall: expected a number")
        scores = r.get("category_scores")
        if not isinstance(scores, dict) or not scores or not all(_number(v) for v in scores.values()):
            raise ConfigError(f"{where}.category_scores: expected {{category: number}}")
        if not isinstance(r.get("source_sha256"), str) or not SHA256_RE.match(r["source_sha256"]):
            raise ConfigError(f"{where}.source_sha256: expected 64 lowercase hex")
        try:
            release = iso_date(r.get("release")).isoformat()
        except ValueError:
            raise ConfigError(f"{where}.release: expected an ISO date") from None
        meanings.add(r.get("meaning"))
        recs.append(Recommendation(r["model_id"], r["leaderboard_model_id"], release, float(r["overall"]),
                                   dict(scores), r["source_table"], site_path, r["source_sha256"], generation))
    if len(repos) > 1:
        raise ConfigError(f"{rel}: source_table URLs name more than one repository ({', '.join(sorted(repos))})")
    repo = repos.pop() if repos else None
    if repo is not None and not REPO_RE.match(repo):
        raise ConfigError(f"{rel}: source_table repository {repo!r} is not OWNER/REPO")
    # leaderboard_revision pins the GitHub-form URLs only; livebench.ai URLs are identified by source_sha256 alone.
    if commits and commits != {revision}:
        raise ConfigError(f"{rel}: source_table commits {', '.join(sorted(commits))} differ from leaderboard_revision {revision}")
    if len(meanings) != 1 or not isinstance(next(iter(meanings)), str) or not next(iter(meanings)).strip():
        raise ConfigError(f"{rel}: every recommendation must carry the same non-empty meaning string")
    if len({r.lb_id for r in recs}) != len(recs):
        raise ConfigError(f"{rel}: duplicate leaderboard_model_id")
    excluded = []
    for i, e in enumerate(doc.get("excluded_latest_examples") or []):
        where = f"{rel} excluded_latest_examples[{i}]"
        if not isinstance(e, dict) or not isinstance(e.get("model"), str) or not REPO_RE.match(e["model"]):
            raise ConfigError(f"{where}.model: expected org/name")
        if not _number(e.get("score")):
            raise ConfigError(f"{where}.score: expected a number")
        try:
            release = iso_date(e.get("release")).isoformat()
        except ValueError:
            raise ConfigError(f"{where}.release: expected an ISO date") from None
        excluded.append({"model": e["model"], "release": release, "score": float(e["score"])})
    return Evidence(repo, revision, latest, recs, excluded, meanings.pop())


def parse_benchmarks(doc):
    rel = "catalog/benchmarks.json"
    try:
        reference = iso_date(doc.get("reference_release")).isoformat()
    except (ValueError, AttributeError):
        raise ConfigError(f"{rel}: reference_release must be an ISO date") from None
    cats = {}
    for i, c in enumerate(doc.get("categories") or []):
        tasks = c.get("livebench_tasks") if isinstance(c, dict) else None
        if not isinstance(c.get("name"), str) or not isinstance(tasks, list) or not tasks \
                or not all(isinstance(t, str) and t for t in tasks):
            raise ConfigError(f"{rel} categories[{i}]: expected a name and a non-empty livebench_tasks list")
        cats[c["name"]] = list(tasks)
    if not cats or sum(len(t) for t in cats.values()) != len({t for ts in cats.values() for t in ts}):
        raise ConfigError(f"{rel}: categories must partition distinct tasks")
    return Benchmarks(reference, cats, partition(cats))


def derive_budgets(hardware, native):
    try:
        vram = hardware["gpu"]["vram_gib"]
        wsl = hardware["os_limits"][WSL_PROFILE]["ram_budget_gib"]
        ram, vram_budget = native["ram_budget_gib"], native["vram_budget_gib"]
    except (KeyError, TypeError):
        raise ConfigError(f"{HARDWARE_CONFIG} / {NATIVE_PROFILE}: missing a GPU, WSL or native budget field") from None
    if not all(_number(v) for v in (vram, wsl, ram, vram_budget)):
        raise ConfigError(f"{HARDWARE_CONFIG} / {NATIVE_PROFILE}: budgets must be numbers")
    return Budgets(vram, wsl, ram + vram_budget - WORKING_SET_RESERVE_GIB, ram)


def scorer_releases(path):
    """RELEASES of src/llm_eval/livebench.py, read with ast (never imported); None when not found."""
    try:
        tree = ast.parse(pathlib.Path(path).read_text(encoding="utf-8"))
    except (OSError, SyntaxError, ValueError):
        return None
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "RELEASES" for t in node.targets):
            try:
                value = ast.literal_eval(node.value)
            except ValueError:
                return None
            if isinstance(value, (set, frozenset, list, tuple)) and all(isinstance(v, str) for v in value):
                return frozenset(value)
            return None
    return None


def _todo(text):
    return "todo" in str(text).casefold()


def key_kind(key):
    """('lb', id, False) | ('lb', prefix, True) | ('hf', repo, False) | ('hf', (org, name prefix), True) | None"""
    if not isinstance(key, str):
        return None
    if key.startswith("lb:"):
        body = key[3:]
        if body.endswith("*"):
            prefix = body[:-1]
            return ("lb", prefix, True) if len(prefix) >= 2 and "*" not in prefix else None
        return ("lb", body, False) if body and "*" not in body else None
    if key.startswith("hf:"):
        body = key[3:]
        if body.endswith("*"):
            org, _, name = body[:-1].partition("/")
            return ("hf", (org, name), True) if ORG_RE.match(org) and NAME_PREFIX_RE.match(name) else None
        return ("hf", body, False) if REPO_RE.match(body) else None
    return None


def decision_errors(decisions, catalog_repos, evidence_ids, today):
    """Every problem of a decisions list; messages name the index and the field."""
    errors, seen = [], set()
    if not isinstance(decisions, list):
        return ["decisions: expected a list"]
    for i, d in enumerate(decisions):
        at = f"decisions[{i}]"
        if not isinstance(d, dict):
            errors.append(f"{at}: expected an object")
            continue
        for field in d:
            if field not in DECISION_FIELDS:
                errors.append(f"{at}.{field}: unknown field")
        for field in ("key", "decision", "reason", "decided_on"):
            if field not in d:
                errors.append(f"{at}.{field}: required")
        kind = key_kind(d.get("key"))
        if "key" in d and kind is None:
            errors.append(f"{at}.key: expected lb:<id>, lb:<prefix of 2+ characters>*, hf:<org>/<name> or hf:<org>/<name prefix>*")
        decision = d.get("decision")
        if "decision" in d and decision not in DECISION_TYPES:
            errors.append(f"{at}.decision: expected one of {', '.join(DECISION_TYPES)}")
        if "reason" in d and (not isinstance(d["reason"], str) or not d["reason"].strip() or _todo(d["reason"])):
            errors.append(f"{at}.reason: write the real reason (empty or TODO is refused)")
        decided = None
        if "decided_on" in d:
            try:
                decided = iso_date(d["decided_on"])
                if decided > today + dt.timedelta(days=1):
                    errors.append(f"{at}.decided_on: later than today + 1 day")
            except ValueError:
                errors.append(f"{at}.decided_on: expected an ISO date")
        if "release" in d:
            try:
                iso_date(d["release"])
            except ValueError:
                errors.append(f"{at}.release: expected an ISO date")
        if decision == "deferred":
            if "until" not in d:
                errors.append(f"{at}.until: required for deferred")
            else:
                try:
                    until = iso_date(d["until"])
                    if decided and not decided < until <= decided + dt.timedelta(days=DEFERRAL_MAX_DAYS):
                        errors.append(f"{at}.until: must be after decided_on and at most {DEFERRAL_MAX_DAYS} days later")
                except ValueError:
                    errors.append(f"{at}.until: expected an ISO date")
        elif "until" in d:
            errors.append(f"{at}.until: only deferred decisions take until")
        if decision == "alias":
            target = d.get("target")
            if not isinstance(target, str) or not REPO_RE.match(target) or _todo(target):
                errors.append(f"{at}.target: expected an org/name Hugging Face repository (TODO is refused)")
        elif "target" in d:
            errors.append(f"{at}.target: only alias decisions take target")
        if kind:
            if decision in ("not_open_weight", "alias") and kind[0] != "lb":
                errors.append(f"{at}.key: {decision} takes lb: keys only")
            if decision == "alias" and kind[2]:
                errors.append(f"{at}.key: alias takes an exact lb: key, not a prefix")
            norm = (kind[0], kind[2], str(kind[1]).casefold() if kind[0] == "hf" else kind[1])
            if kind[0] == "hf" and kind[2]:
                norm = ("hf", True, (kind[1][0].casefold(), kind[1][1].casefold()))
            if norm in seen:
                errors.append(f"{at}.key: duplicate key")
            seen.add(norm)
            if kind[0] == "hf" and not kind[2] and kind[1].casefold() in catalog_repos:
                errors.append(f"{at}.key: redundant: the repository is already in catalog/models.json")
            if kind[0] == "lb" and not kind[2] and kind[1] in evidence_ids:
                errors.append(f"{at}.key: redundant: the id is already an evidence leaderboard_model_id")
    return errors


def parse_discovery(doc, models, evidence, today):
    rel = DISCOVERY_FILE
    if not isinstance(doc, dict):
        raise ConfigError(f"{rel}: expected an object")
    errors = [f"{field}: unknown field" for field in doc if field not in ("schema_version", "site", "publishers", "decisions")]
    if doc.get("schema_version") != 1:
        errors.append("schema_version: expected 1")
    site = doc.get("site")
    if not isinstance(site, dict):
        errors.append("site: expected {main_script, reviewed_on}")
        site = {}
    errors += [f"site.{field}: unknown field" for field in site if field not in ("main_script", "reviewed_on")]
    script = site.get("main_script")
    if not isinstance(script, str) or not SCRIPT_PATH_RE.match(script):
        errors.append("site.main_script: expected the reviewed script's path, static/js/<name>.js")
    try:
        reviewed_on = iso_date(site.get("reviewed_on"))
        if reviewed_on > today + dt.timedelta(days=1):
            errors.append("site.reviewed_on: later than today + 1 day")
    except ValueError:
        errors.append("site.reviewed_on: expected an ISO date")
        reviewed_on = None
    publishers, seen_prefixes = [], set()
    if not isinstance(doc.get("publishers"), list) or not doc["publishers"]:
        errors.append("publishers: expected a non-empty list")
    for i, p in enumerate(doc.get("publishers") or []):
        at = f"publishers[{i}]"
        if not isinstance(p, dict) or set(p) != {"prefixes", "hf_orgs"}:
            errors.append(f"{at}: expected exactly prefixes and hf_orgs")
            continue
        prefixes, orgs = p["prefixes"], p["hf_orgs"]
        if not isinstance(prefixes, list) or not prefixes:
            errors.append(f"{at}.prefixes: expected a non-empty list")
            prefixes = []
        for prefix in prefixes:
            if not isinstance(prefix, str) or not prefix or prefix != prefix.lower() or prefix.strip() != prefix:
                errors.append(f"{at}.prefixes: {prefix!r} must be a non-empty lowercase string")
            elif prefix in seen_prefixes:
                errors.append(f"{at}.prefixes: {prefix!r} appears more than once")
            seen_prefixes.add(prefix)
        if not isinstance(orgs, list) or not orgs or not all(isinstance(o, str) and ORG_RE.match(o) for o in orgs):
            errors.append(f"{at}.hf_orgs: expected a non-empty list of Hugging Face org names")
            orgs = []
        publishers.append(Publisher(tuple(x for x in prefixes if isinstance(x, str)), tuple(orgs)))
    covered = {o.casefold() for p in publishers for o in p.orgs}
    for org in sorted({m.repo.split("/")[0] for m in models}, key=str.casefold):
        if org.casefold() not in covered:
            errors.append(f"publishers: no entry lists the catalog org {org!r}")
    catalog_repos = {m.repo.casefold() for m in models}
    evidence_ids = {r.lb_id for r in evidence.recommendations}
    errors += decision_errors(doc.get("decisions", []), catalog_repos, evidence_ids, today)
    if errors:
        raise ConfigError(f"{rel}: " + "; ".join(errors))
    return SiteReview(script, reviewed_on.isoformat()), publishers, Decisions(doc.get("decisions", []))


class Decisions:
    def __init__(self, entries):
        self.entries = list(entries)
        self.lb_exact, self.lb_prefix, self.hf_exact, self.hf_family = {}, [], {}, []
        for d in self.entries:
            source, value, wildcard = key_kind(d["key"])
            if source == "lb" and wildcard:
                self.lb_prefix.append((value, d))
            elif source == "lb":
                self.lb_exact[value] = d
            elif wildcard:
                self.hf_family.append((value[0].casefold(), value[1].casefold(), d))
            else:
                self.hf_exact[value.casefold()] = d

    def for_lb(self, lb_id):
        if lb_id in self.lb_exact:
            return self.lb_exact[lb_id]
        hits = [(len(p), d) for p, d in self.lb_prefix if lb_id.startswith(p)]
        return max(hits, key=lambda h: h[0])[1] if hits else None

    def for_repo(self, repo):
        if repo.casefold() in self.hf_exact:
            return self.hf_exact[repo.casefold()]
        org, _, name = repo.casefold().partition("/")
        hits = [(len(p), d) for o, p, d in self.hf_family if o == org and name.startswith(p)]
        return max(hits, key=lambda h: h[0])[1] if hits else None


@dataclasses.dataclass
class Local:
    root: pathlib.Path
    today: dt.date
    models: list
    evidence: Evidence
    benchmarks: Benchmarks
    budgets: Budgets
    releases: object
    site: SiteReview
    publishers: list
    decisions: Decisions

    def __post_init__(self):
        self.by_id = {m.id: m for m in self.models}
        self.by_repo = {m.repo.casefold(): m for m in self.models}
        self.evidence_by_lb = {r.lb_id: r for r in self.evidence.recommendations}
        self.excluded_by_repo = {e["model"].casefold(): e for e in self.evidence.excluded}

    def publisher(self, lb_id):
        """(publisher, prefix) by the longest prefix of the leaderboard id, or (None, None)."""
        key, best = lb_id.casefold(), (None, None)
        for p in self.publishers:
            for prefix in p.prefixes:
                if key.startswith(prefix) and (best[1] is None or len(prefix) > len(best[1])):
                    best = (p, prefix)
        return best

    def all_orgs(self):
        return tuple(o for p in self.publishers for o in p.orgs)


def load_local(root, today):
    root = pathlib.Path(root)
    models = parse_models(_read_json(root, "catalog/models.json"))
    by_id = {m.id: m for m in models}
    evidence = parse_evidence(_read_json(root, "catalog/livebench-evidence.json"), by_id)
    benchmarks = parse_benchmarks(_read_json(root, "catalog/benchmarks.json"))
    budgets = derive_budgets(_read_json(root, HARDWARE_CONFIG), _read_json(root, NATIVE_PROFILE))
    for anchor in HF_ANCHORS:
        if anchor not in by_id or not by_id[anchor].metadata or not by_id[anchor].metadata.get("safetensors"):
            raise ConfigError(f"catalog/models.json: HF anchor {anchor} needs upstream_metadata with safetensors")
    site, publishers, decisions = parse_discovery(_read_json(root, DISCOVERY_FILE), models, evidence, today)
    return Local(root, today, models, evidence, benchmarks, budgets, scorer_releases(root / SCORER_SOURCE),
                 site, publishers, decisions)


def _safetensors(value):
    """{'parameters': {DTYPE: int}, 'total': int} or None when the block is absent or malformed."""
    if not isinstance(value, dict):
        return None
    params, total = value.get("parameters"), value.get("total")
    if not isinstance(params, dict) or not params or not isinstance(total, int) or isinstance(total, bool) or total <= 0:
        return None
    if not all(isinstance(k, str) and isinstance(v, int) and not isinstance(v, bool) and v >= 0 for k, v in params.items()):
        return None
    return value


# --- livebench.ai: the page, its main script, the release lists and the model registry ------------
@dataclasses.dataclass(frozen=True)
class SiteRelease:
    """One release on the site's timeline."""
    id: str             # v1: YYYY-MM-DD; 2.0: YYYYMMDD
    date: str           # ISO date (a 2.0 id formatted as the site labels it)
    generation: str     # v1 | 2.0

    @property
    def table_path(self):
        if self.generation == "v1":
            return f"v1/table_{self.date.replace('-', '_')}.csv"
        return f"data/{self.id}/table.csv"

    @property
    def categories_path(self):
        if self.generation == "v1":
            return f"v1/categories_{self.date.replace('-', '_')}.json"
        return f"data/{self.id}/categories.json"

    @property
    def label(self):
        return f"{self.date} (v1)" if self.generation == "v1" else f"{self.date} (2.0, id {self.id})"


def media_type(headers):
    return str(headers.get("content-type") or "").split(";", 1)[0].strip().lower()


def looks_html(body):
    return body[:1024].lstrip().lower().startswith((b"<!doctype", b"<html"))


def script_path(src):
    """The site-root-relative path of a same-site script reference (static/js/<name>.js), or None."""
    try:
        parts = urllib.parse.urlsplit(urllib.parse.urljoin(SITE_URL, str(src)))
    except ValueError:
        return None
    path = parts.path.lstrip("/")
    if parts.scheme != "https" or parts.hostname != LIVEBENCH_SITE or parts.port or parts.query or parts.fragment \
            or not SCRIPT_PATH_RE.match(path):
        return None
    return path


def parse_release_lists(text):
    """The timeline [SiteRelease] (sorted by date) of the main script's v1 and 2.0 release lists.

    Each list must be found exactly once; ids must be calendar dates; dates must be unique across both lists (the
    site itself throws "Two releases share a date on the timeline" otherwise)."""
    gens = GEN_RE.findall(text)
    v1 = V1_LIST_RE.findall(text)
    if len(v1) != 1 or gens.count("v1") != 1:
        raise ShapeError('exactly one v1 release list ["YYYY-MM-DD", ...].map(e=>({id:e,label:e,gen:"v1"})) in the '
                         "main script", got=f'{len(v1)} such lists, {gens.count("v1")} gen:"v1" maps')
    maps, v2 = V2_MAP_RE.findall(text), V2_LIST_RE.findall(text)
    if len(maps) != 1 or gens.count("v2") != 1:
        raise ShapeError('exactly one 2.0 release map .map(e=>({id:e,label:f(e),gen:"v2"})) in the main script',
                         got=f'{len(maps)} such maps, {gens.count("v2")} gen:"v2" maps')
    if len(v2) != 1:
        raise ShapeError('exactly one assigned list of quoted 2.0 release ids X=["YYYYMMDD", ...] in the main script',
                         got=f"{len(v2)} such lists" + (": " + excerpt(", ".join(v2)) if v2 else ""))
    timeline = []
    for generation, body in (("v1", v1[0][0]), ("2.0", v2[0])):
        for rid in re.findall(r'"([^"]*)"', body):
            date = rid if generation == "v1" else f"{rid[:4]}-{rid[4:6]}-{rid[6:]}"
            try:
                dt.date.fromisoformat(date)
            except ValueError:
                raise ShapeError(f"{generation} release ids that are calendar dates", got=excerpt(rid)) from None
            timeline.append(SiteRelease(rid, date, generation))
    dates = collections.Counter(r.date for r in timeline)
    twice = sorted(d for d, n in dates.items() if n > 1)
    if twice:
        raise ShapeError("one release per date on the timeline (v1 and 2.0 lists together)",
                         got=excerpt(", ".join(twice)) + " listed more than once")
    return sorted(timeline, key=lambda r: r.date)


def parse_suite_order(text):
    """The site's list of suite names that orders a 2.0 release's suites (rn() in the reviewed script), or None when
    the main script does not hold exactly one."""
    found = {tuple(js_string(t) for t in re.findall(r'"[^"\\]+"', m.group(2))) for m in SUITE_ORDER_RE.finditer(text)}
    return list(found.pop()) if len(found) == 1 else None


def site_order(names, display):
    """`names` as the site's rn() orders them: by their first index in `display`, the others last in their own order."""
    index = {}
    for i, name in enumerate(display):
        index.setdefault(name, i)
    return sorted(names, key=lambda n: index.get(n, len(display)))


def balanced_end(text, start):
    """Index just past the bracket closing text[start] ('{' or '['), skipping quoted strings; None if unbalanced."""
    depth, i, quote, n = 0, start, None, len(text)
    while i < n:
        c = text[i]
        if quote:
            if c == "\\":
                i += 2
                continue
            if c == quote:
                quote = None
        elif c in "\"'`":
            quote = c
        elif c in "{[(":
            depth += 1
        elif c in "}])":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return None


JS_TOKEN_RE = re.compile(r"""\s*(?:(?P<str>"(?:[^"\\\n]|\\.)*"|'(?:[^'\\\n]|\\.)*')|(?P<bang>![01])"""
                         r"""|(?P<num>-?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)|(?P<id>[A-Za-z_$][\w$]*)|(?P<p>[{}\[\]:,]))""",
                         re.S)
JS_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f", "v": "\v", "0": "\0"}


def js_string(token):
    """The value of a quoted JavaScript string literal (\\xHH, \\uHHHH, \\u{H...} and single-character escapes)."""
    body, out, i = token[1:-1], [], 0
    while i < len(body):
        c = body[i]
        if c != "\\":
            out.append(c)
            i += 1
            continue
        nxt = body[i + 1]
        if nxt == "x":
            out.append(chr(int(body[i + 2:i + 4], 16)))
            i += 4
        elif nxt == "u" and body[i + 2:i + 3] == "{":
            close = body.index("}", i)
            out.append(chr(int(body[i + 3:close], 16)))
            i = close + 1
        elif nxt == "u":
            out.append(chr(int(body[i + 2:i + 6], 16)))
            i += 6
        else:
            out.append(JS_ESCAPES.get(nxt, nxt))
            i += 2
    return "".join(out)


def parse_js_literal(text):
    """A JavaScript object/array literal of plain data (strings, numbers, !0/!1, true/false/null, nested objects and
    arrays) as Python values. Anything else (functions, identifiers, spreads, template literals) is a ValueError."""
    tokens_, pos = [], 0
    while pos < len(text):
        m = JS_TOKEN_RE.match(text, pos)
        if not m or m.end() == pos:
            if not text[pos:].strip():
                break
            raise ValueError(f"unexpected {text[pos:pos + 20]!r}")
        tokens_.append((m.lastgroup, m.group(m.lastgroup)))
        pos = m.end()
    i = 0

    def take():
        nonlocal i
        if i >= len(tokens_):
            raise ValueError("unexpected end")
        i += 1
        return tokens_[i - 1]

    def value(depth):
        nonlocal i
        if depth > 32:
            raise ValueError("nested too deeply")
        kind, tok = take()
        if kind == "str":
            return js_string(tok)
        if kind == "bang":
            return tok == "!0"
        if kind == "num":
            return float(tok)
        if kind == "id":
            if tok in ("true", "false", "null"):
                return {"true": True, "false": False, "null": None}[tok]
            raise ValueError(f"identifier {tok}")
        if tok == "{":
            out = {}
            while True:
                kind, tok = take()
                if tok == "}":
                    return out
                if kind not in ("str", "id", "num"):
                    raise ValueError(f"key {tok!r}")
                key = js_string(tok) if kind == "str" else tok
                if take()[1] != ":":
                    raise ValueError("expected ':'")
                out[key] = value(depth + 1)
                kind, tok = take()
                if tok == "}":
                    return out
                if tok != ",":
                    raise ValueError("expected ',' or '}'")
        if tok == "[":
            out = []
            while True:
                if i < len(tokens_) and tokens_[i][1] == "]":
                    i += 1
                    return out
                out.append(value(depth + 1))
                kind, tok = take()
                if tok == "]":
                    return out
                if tok != ",":
                    raise ValueError("expected ',' or ']'")
        raise ValueError(f"unexpected {tok!r}")

    result = value(0)
    if i != len(tokens_):
        raise ValueError("trailing tokens")
    return result


def js_truthy(value):
    return bool(value) and not (isinstance(value, float) and math.isnan(value))


@dataclasses.dataclass(frozen=True)
class RegistryEntry:
    id: str
    openweight: bool
    link: object            # "org/name" from huggingface: https://huggingface.co/org/name, or None
    link_raw: object        # a huggingface: value that is not such a URL (never used to name a repository)
    variant_of: object = None


def registry_entries(doc):
    """{id: RegistryEntry} of one registry object, variants included as the site builds them: a variant's rawName
    inherits its entry's fields (huggingface included) and overrides openweight when it sets one; entries win over
    variants of the same name."""
    if not isinstance(doc, dict) or not doc:
        raise ValueError("not an object of entries")

    def entry(name, openweight, hf, parent=None):
        link = HF_LINK_RE.match(hf) if isinstance(hf, str) else None
        return RegistryEntry(name, js_truthy(openweight), link.group(1) if link else None,
                             hf if isinstance(hf, str) and not link else None, parent)
    out, variants = {}, {}
    for name, value in doc.items():
        if not isinstance(value, dict):
            raise ValueError(f"entry {name!r} is not an object")
        out[name] = entry(name, value.get("openweight"), value.get("huggingface"))
        found = value.get("variants")
        if found is None:
            continue
        if not isinstance(found, list):
            raise ValueError(f"variants of {name!r} is not a list")
        for v in found:
            if not isinstance(v, dict) or not isinstance(v.get("rawName"), str) or not v["rawName"]:
                raise ValueError(f"a variant of {name!r} has no rawName")
            ow = v.get("openweight") if v.get("openweight") is not None else value.get("openweight")
            variants[v["rawName"]] = entry(v["rawName"], ow, value.get("huggingface"), name)
    return {**variants, **out}


@dataclasses.dataclass
class Registry:
    """LiveBench's model registries in the main script (an object for the 2.0 ids and an older one for v1 ids).

    Only the analysed release's own registry is consulted, as the site consults only its generation's registry for
    a row (and shows no row without an entry there). A matching hint only: when it is missing or does not parse,
    matching uses the name rules alone."""
    tables: list            # [{id: RegistryEntry}] in script order
    sizes: list             # characters of each object literal
    problem: object = None  # why the registry is not used, or None
    order: list = dataclasses.field(default_factory=list)
    coverage: list = dataclasses.field(default_factory=list)

    def rank(self, ids):
        """The release's own registry is the one that holds the most of its ids (first in `order`)."""
        ids = set(ids)
        self.coverage = [len(ids & set(t)) for t in self.tables]
        self.order = sorted(range(len(self.tables)), key=lambda k: (-self.coverage[k], k))

    def get(self, lb_id):
        """The entry of the release's own registry, or None: the other generation's entry for the same id is never
        used (a v1 id it lacks would otherwise borrow a 2.0 entry's link, and the reverse)."""
        if not self.tables:
            return None
        return self.tables[(self.order or [0])[0]].get(lb_id)

    def counts(self):
        """(entries, open weight, linked) of the registry consulted first."""
        if not self.tables:
            return 0, 0, 0
        t = self.tables[(self.order or [0])[0]]
        return len(t), sum(e.openweight for e in t.values()), sum(bool(e.openweight and e.link) for e in t.values())


def parse_registries(text):
    """Registry of every `X={"id":{...},...}` (or `X={id:{...},...}`) object literal in the main script that holds
    `openweight:!0` entries and parses as plain data of entries.

    An object that holds such entries but does not parse (code around a registry, say) is passed over; only an
    `openweight:!0` left outside every registry read makes the registry unusable: Registry([], [], problem), a header
    warning, never a run failure (as is a script with no registry)."""
    marks = [m.start() for m in re.finditer(re.escape(OPENWEIGHT_MARK), text)]
    if not marks:
        return Registry([], [], f"no model registry (no `{OPENWEIGHT_MARK}` entry) in the main script")
    tables, sizes, spans, failures = [], [], [], []
    for m in REGISTRY_START_RE.finditer(text):
        start = m.end()
        if any(a <= start < b for a, b in spans):     # inside a registry already read
            continue
        end = balanced_end(text, start)
        if end is None:
            failures.append((start, len(text), f"the object literal at offset {start} of the main script never closes"))
            continue
        if OPENWEIGHT_MARK not in text[start:end]:
            continue
        try:
            tables.append(registry_entries(parse_js_literal(text[start:end])))
        except (ValueError, IndexError, OverflowError) as exc:
            failures.append((start, end, f"the registry object at offset {start} of the main script does not parse "
                                         f"({excerpt(exc, 80)})"))
            continue
        sizes.append(end - start)
        spans.append((start, end))
    outside = [p for p in marks if not any(a <= p < b for a, b in spans)]
    if outside:
        why = next((msg for a, b, msg in failures if any(a <= p < b for p in outside)), None)
        return Registry([], [], why or f"{len(outside)} of {len(marks)} `{OPENWEIGHT_MARK}` entries lie outside the "
                                       "registry objects read")
    return Registry(tables, sizes)


class Site:
    """https://livebench.ai/, read without any token. Every file must have its expected media type: a 404 page or
    any other HTML body where a CSV or JSON file belongs is a shape error, never data."""

    def __init__(self, net):
        self.net, self.cache = net, {}

    def url(self, path):
        return SITE_URL + path

    def get(self, path, kind, cap=MAX_BODY_BYTES):
        if path in self.cache:
            return self.cache[path]
        url = self.url(path)
        reply = self.net.get(url, cap=cap)
        mtype = media_type(reply.headers)
        if mtype not in SITE_TYPES[kind] or (kind != "html" and looks_html(reply.body)):
            raise ShapeError(f"{' or '.join(SITE_TYPES[kind])} from {url}",
                             got=f"content-type {mtype or 'none'}, body " + excerpt(reply.body[:120]))
        self.cache[path] = reply
        return reply

    def text(self, path, kind, cap=MAX_BODY_BYTES):
        try:
            return self.get(path, kind, cap).body.decode("utf-8")
        except UnicodeDecodeError:
            raise ShapeError(f"UTF-8 text from {self.url(path)}", got="bytes that are not UTF-8") from None

    def required(self, path, kind, what):
        """A file the site layout must have: a 404 or 410 means the layout changed (exit 2), not a network fault."""
        try:
            return self.get(path, kind)
        except HttpStatus as exc:
            if exc.code in (404, 410):
                raise ShapeError(f"{what} at {self.url(path)} (leaderboard site layout changed?)",
                                 got=f"HTTP {exc.code}") from None
            raise

    def main_script(self):
        """(path, text) of the main script: asset-manifest.json files["main.js"], which index.html must load."""
        self.required("", "html", "the leaderboard page")
        page = self.text("", "html")
        manifest = self.required("asset-manifest.json", "json", "the build's asset manifest").json()
        named = manifest.get("files", {}).get("main.js") if isinstance(manifest, dict) and \
            isinstance(manifest.get("files"), dict) else None
        path = script_path(named) if isinstance(named, str) else None
        if path is None:
            raise ShapeError('asset-manifest.json files["main.js"] naming a same-site static/js/<name>.js script',
                             got=excerpt(compact(manifest)[:200] if isinstance(manifest, (dict, list)) else manifest))
        srcs = SCRIPT_SRC_RE.findall(page)
        mains = [script_path(s) or s for s in srcs if urllib.parse.urlsplit(s).path.rsplit("/", 1)[-1].startswith("main.")]
        if mains != [path]:
            raise ShapeError(f"index.html loading the main script asset-manifest.json names ({path})",
                             got="script src " + excerpt(", ".join(srcs) or "none"))
        self.required(path, "js", "the main script")
        return path, self.text(path, "js")


# --- tables, categories, scoring ---------------------------------------------------------------
@dataclasses.dataclass
class RawTable:
    url: str
    header: list
    model_col: int
    rows: list          # (id, cells, first physical line, data row number)

    def header_excerpt(self):
        return excerpt(",".join(self.header))


def read_csv(data, url):
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise ShapeError(f"a UTF-8 CSV at {url}", got="bytes that are not UTF-8") from None
    if text.startswith("\ufeff"):
        text = text[1:]
    reader = csv.reader(io.StringIO(text, newline=""))
    header, rows, seen, previous = None, [], set(), 0
    try:
        for record in reader:
            first, previous = previous + 1, reader.line_num
            if not record or all(not cell.strip() for cell in record):
                continue
            if header is None:
                header = record
                continue
            rows.append((record, first))
    except csv.Error as exc:
        raise ShapeError(f"a readable CSV at {url}", got=f"csv error at line {reader.line_num}: {exc}") from None
    if header is None:
        raise ShapeError(f"a CSV header at {url}", got="an empty file")
    model_cols = [i for i, h in enumerate(header) if h.strip().casefold() == "model"]
    if len(model_cols) != 1:
        raise ShapeError(f"exactly one 'model' column at {url}", got=f"{len(model_cols)} in header " + excerpt(",".join(header)))
    out = []
    for number, (record, line) in enumerate(rows, 1):
        if len(record) != len(header):
            raise ShapeError(f"rows of {len(header)} cells at {url}", got=f"{len(record)} cells at line {line}")
        lb_id = record[model_cols[0]]
        if not lb_id.strip():
            raise ShapeError(f"a model id on every row at {url}", got=f"an empty id at line {line}")
        if lb_id in seen:
            raise ShapeError(f"one row per model id at {url}", got=f"a second row for {lb_id} at line {line}")
        seen.add(lb_id)
        out.append((lb_id, record, line, number))
    return RawTable(url, header, model_cols[0], out)


def parse_categories(data, url, generation="v1"):
    """(categories, weights, ignored weights) of a categories file.

    v1: {category: [task, ...]}. 2.0: {suite: [column, ...], "_overall_weights": {suite: number}}, the weights read as
    the site's code reads them: kept for an existing suite with a finite weight > 0 (else ignored and reported);
    a weight that is not a finite number, or any other key starting with "_", is a shape error."""
    try:
        doc = json.loads(data.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        raise ShapeError(f"a JSON categories file at {url}", got=excerpt(data)) from None
    if not isinstance(doc, dict) or not doc:
        raise ShapeError(f"a JSON object {{category: [task, ...]}} at {url}", got=type(doc).__name__)
    raw_weights = None
    for name in doc:
        if name.startswith("_"):
            if name != WEIGHTS_KEY or generation != "2.0":
                allowed = f"no key starting with _ other than {WEIGHTS_KEY}" if generation == "2.0" else \
                    "no key starting with _ (v1 categories carry no weights)"
                raise ShapeError(f"{allowed} at {url}", got=excerpt(name))
            raw_weights = doc[name]
    categories = {k: v for k, v in doc.items() if not k.startswith("_")}
    if not categories:
        raise ShapeError(f"at least one category at {url}", got="none")
    seen = set()
    for name, tasks in categories.items():
        if not isinstance(tasks, list) or not tasks or not all(isinstance(t, str) and t for t in tasks):
            raise ShapeError(f"a non-empty list of task ids per category at {url}", got=excerpt(f"{name}: {compact(tasks)}"))
        for task in tasks:
            if task in seen:
                raise ShapeError(f"each task in one category at {url}", got=excerpt(f"{task} appears twice"))
            seen.add(task)
    weights, ignored = {}, []
    if raw_weights is not None:
        if not isinstance(raw_weights, dict):
            raise ShapeError(f"{WEIGHTS_KEY} as an object {{suite: number}} at {url}", got=type(raw_weights).__name__)
        for name, w in raw_weights.items():
            if not _number(w):
                raise ShapeError(f"finite numbers in {WEIGHTS_KEY} at {url}", got=excerpt(f"{name}: {w!r}"))
            if name not in categories:
                ignored.append((name, w, "not a suite of this file"))
            elif w <= 0:
                ignored.append((name, w, "not positive"))
            else:
                weights[name] = float(w)
    return {name: list(tasks) for name, tasks in categories.items()}, weights, ignored


@dataclasses.dataclass
class Row:
    id: str
    line: int
    categories: dict          # category -> mean or None
    overall: object = None
    partial_mean: object = None
    missing_tasks: int = 0
    total_tasks: int = 0
    rank: object = None
    number: int = 0           # data row of the CSV (1 = the row after the header)
    unit: str = "tasks"       # "suites" for 2.0 tables (one column per suite)

    @property
    def available(self):
        return sum(v is not None for v in self.categories.values())

    def missing_label(self):
        return f"{self.missing_tasks} of {self.total_tasks} {self.unit} missing" if self.missing_tasks else ""

    def partial_label(self):
        return f"partial ({self.available} of {len(self.categories)} categories)"


def parse_cell(text, url, line, column):
    value = text.strip()
    if value.casefold() in MISSING_MARKERS:
        return None
    if not NUMBER_RE.match(value):
        raise ShapeError(f"decimal scores in [0, 100] at {url}", got=excerpt(f"{value!r} in {column} at line {line}"))
    number = float(value)
    if not math.isfinite(number) or not SCORE_RANGE[0] <= number <= SCORE_RANGE[1]:
        raise ShapeError(f"decimal scores in [0, 100] at {url}", got=excerpt(f"{value} in {column} at line {line}"))
    return number


def js_fixed2(x):
    """JavaScript x.toFixed(2) read back with parseFloat: the exact binary value rounded half up (Python's round()
    and "%.2f" round half to even), so 1.125 gives 1.13 and 2.675 (really 2.67499999...) gives 2.67."""
    return float(decimal.Decimal(x).quantize(decimal.Decimal("0.01"), rounding=decimal.ROUND_HALF_UP))


def js_mean(values):
    """values.reduce((a, b) => a + b) / values.length, added left to right as JavaScript does (Python 3.12's sum()
    compensates rounding errors, which can move a mean across a .xx5 rounding boundary)."""
    total = 0.0
    for v in values:
        total += v
    return total / len(values)


def score_row_site(lb_id, line, values, categories, weights, order=None):
    """A 2.0 row as the site's averaging code scores it: each suite is the mean of its columns that hold a number;
    the overall is the weighted mean of the suites with a score (weight from _overall_weights, else 1), added in the
    site's suite order (`order`, see site_order) and rounded to 2 decimals as toFixed(2). A row with no suite score
    has no overall."""
    cats, missing, total = {}, 0, 0
    for name, cols in categories.items():
        present = [values[c] for c in cols if values[c] is not None]
        total += len(cols)
        missing += len(cols) - len(present)
        cats[name] = js_mean(present) if present else None
    row = Row(lb_id, line, cats, missing_tasks=missing, total_tasks=total, unit="suites")
    num = den = 0.0
    for name in order or categories:
        w = weights.get(name, 1)
        if cats[name] is not None and w > 0:
            num += cats[name] * w
            den += w
    if den > 0:
        row.overall = js_fixed2(num / den)
    return row


def score_row(lb_id, line, values, categories):
    cats, missing, total = {}, 0, 0
    for name, tasks in categories.items():
        present = [values[t] for t in tasks if values[t] is not None]
        total += len(tasks)
        missing += len(tasks) - len(present)
        cats[name] = sum(present) / len(present) if present else None
    row = Row(lb_id, line, cats, missing_tasks=missing, total_tasks=total)
    present = [v for v in cats.values() if v is not None]
    if len(present) == len(cats):
        row.overall = sum(present) / len(cats)
    elif present:
        row.partial_mean = sum(present) / len(present)
    return row


def score_table(raw, categories, generation="v1", weights=None, display=REVIEWED_SUITE_ORDER):
    """Rows ranked by (overall desc, id asc) with standard competition ranks; partial rows after them.

    v1: the two-level mean (a whole category missing gives no overall). 2.0: the site's weighted suite mean, the
    suites added in the order the site's list `display` gives them."""
    columns = {}
    for i, h in enumerate(raw.header):
        name = h.strip()
        if name in columns:
            if any(name in tasks for tasks in categories.values()):
                raise ShapeError(f"one column per task at {raw.url}", got=excerpt(f"{name} twice in " + raw.header_excerpt()))
            continue
        columns[name] = i
    for tasks in categories.values():
        for task in tasks:
            if task not in columns:
                raise ShapeError(f"task column {task} at {raw.url}", got="header " + raw.header_excerpt())
    tasks = [t for ts in categories.values() for t in ts]
    order = site_order(categories, display)
    rows, values_seen = [], []
    for lb_id, record, line, number in raw.rows:
        values = {t: parse_cell(record[columns[t]], raw.url, line, t) for t in tasks}
        values_seen += [v for v in values.values() if v is not None]
        row = (score_row_site(lb_id, line, values, categories, weights or {}, order) if generation == "2.0"
               else score_row(lb_id, line, values, categories))
        row.number = number
        rows.append(row)
    if values_seen and max(values_seen) <= 1.0:
        raise ShapeError(f"percent-scale scores (0-100) at {raw.url}", got="every cell at most 1.0 (fraction scale?)")
    scored = sorted((r for r in rows if r.overall is not None), key=lambda r: (-r.overall, r.id))
    for i, r in enumerate(scored):   # standard competition rank: ties share the best rank
        r.rank = scored[i - 1].rank if i and r.overall == scored[i - 1].overall else i + 1
    partial = [r for r in rows if r.overall is None]
    extras = [h for i, h in enumerate(raw.header) if i != raw.model_col and h.strip() not in set(tasks)]
    return scored, partial, extras


@dataclasses.dataclass
class Release:
    entry: SiteRelease
    table_sha256: str
    cats_sha256: str
    categories: dict
    weights: dict             # 2.0 suite weights in use (empty: every suite x1; always empty for v1)
    ignored_weights: list     # (suite, value, why) entries of _overall_weights the site's code ignores
    scored: list
    partial: list
    extras: list

    @property
    def date(self):
        return self.entry.date

    @property
    def id(self):
        return self.entry.id

    @property
    def generation(self):
        return self.entry.generation

    @property
    def table_url(self):
        return SITE_URL + self.entry.table_path

    @property
    def cats_url(self):
        return SITE_URL + self.entry.categories_path

    @property
    def task_count(self):
        return sum(len(t) for t in self.categories.values())

    def taxonomy(self):
        if self.generation == "2.0":
            return f"{len(self.categories)} suites / {self.task_count} columns"
        return f"{len(self.categories)} categories / {self.task_count} tasks"

    def averaging(self, reviewed_on=None):
        """The rule the overall follows, as the issue header states it."""
        if self.generation == "v1":
            return ("Overall: the two-level mean (task means within each category, then every category equally), "
                    "calibrated against the recorded rows")
        return (f"Overall per the site's averaging code (reviewed {reviewed_on}): " + weights_text(self.weights, list(self.categories))
                + "; rounded to 2 decimals as the site shows it")


def weights_text(weights, suites, quote=None):
    """The site's own description (Cn in the reviewed script): which suites weigh other than 1."""
    quote = quote or md_code
    heavy = [s for s in suites if weights.get(s, 1) != 1]
    if not heavy:
        return "mean of the suites with a score (every suite ×1)"
    return ("weighted mean of the suites with a score; weights " + ", ".join(f"{quote(s)} ×{weights[s]:g}" for s in heavy)
            + ", the rest ×1")


# --- strict matcher (the only route to naming a repository) -------------------------------
def tokens(name, org):
    """Normalized tokens of a leaderboard id or repo name, with at most 2 leading org tokens removed."""
    base = re.sub(r"(?<=\d)_(?=\d)", ".", name.rsplit("/", 1)[-1].lower())
    toks = [t for t in re.split(r"[-_\s/]+", base) if t]
    org_tokens = {t for t in re.split(r"[-_]", org.lower()) if t}
    stripped = 0
    while toks and stripped < 2 and toks[0] in org_tokens:
        toks.pop(0)
        stripped += 1
    return toks


def stem(toks):
    toks = list(toks)
    while toks and toks[-1] in PRECISION_TOKENS:
        toks.pop()
    return tuple(toks)


def has_size(toks):
    return any(SIZE_RE.match(t) for t in toks)


def compare(tl, th, allow_size):
    """('exact', []) | ('relaxed', leftover tokens of the repo) | None."""
    if not tl:
        return None
    if th == tl:
        return "exact", []
    left, j = [], 0
    for t in th:
        if j < len(tl) and t == tl[j]:
            j += 1
        else:
            left.append(t)
    if j < len(tl):
        return None
    for t in left:
        if t in ALLOWED_EXTRAS or (allow_size and (SIZE_RE.match(t) or ACTIVE_RE.match(t))):
            continue
        return None
    return "relaxed", left


def strip_trailing(tl):
    """Stage 2: strip once at most 2 trailing reasoning/serving/budget tokens."""
    if len(tl) > 2 and tl[-2] in ("non", "no") and tl[-1] == "thinking":
        return tl[:-2], tl[-2:]
    out, stripped = list(tl), []
    while len(stripped) < 2 and len(out) > 1 and (out[-1] in STRIP_TOKENS or BUDGET_RE.match(out[-1])):
        stripped.insert(0, out.pop())
    return out, stripped


@dataclasses.dataclass
class Match:
    repo: str
    org: str
    tier: str            # exact | relaxed | alias
    extras: list
    stage: int
    stripped: list
    pool_size: int


def collapse_siblings(cands):
    """Precision siblings (same org, same stem) collapse to the one without a precision token, else the -BF16 one."""
    groups = {}
    for m in cands:
        groups.setdefault((m.org.casefold(), stem(tokens(m.repo, m.org))), []).append(m)
    out = []
    for group in groups.values():
        if len(group) > 1:
            bare = [m for m in group if stem(tokens(m.repo, m.org)) == tuple(tokens(m.repo, m.org))]
            bf16 = [m for m in group if tokens(m.repo, m.org)[-1:] == ["bf16"]]
            group = bare if len(bare) == 1 else bf16 if len(bf16) == 1 else group
        out += group
    return out


def strict_match(lb_id, orgs, listing):
    """('match', Match, pool) | ('ambiguous', [Match], pool) | ('no_repo', None, pool)."""
    pool = [(org, repo) for org in orgs for repo in listing(org)]
    for stage in (1, 2):
        cands = []
        for org, repo in pool:
            tl, stripped = tokens(lb_id, org), []
            if stage == 2:
                tl, stripped = strip_trailing(tl)
                if not stripped:
                    continue
            hit = compare(tl, tokens(repo, org), allow_size=stage == 1 and not has_size(tl))
            if hit:
                cands.append(Match(repo, org, hit[0], hit[1], stage, stripped, len(pool)))
        cands = collapse_siblings(cands)
        if len(cands) == 1:
            return "match", cands[0], len(pool)
        if cands:
            return "ambiguous", cands, len(pool)
    return "no_repo", None, len(pool)


# --- parameter count and fit -------------------------------------------------------------------
@dataclasses.dataclass
class Params:
    kind: str                 # float | packed | none
    value: object = None      # P, when verified
    lower: object = None
    upper: object = None
    cls: object = None        # fit class when only the packed range is known
    problem: object = None    # size_unverified | size_mismatch
    int_share: object = None
    dtypes: tuple = ()
    name_token: object = None


def fit_class(parameters, budgets):
    q4 = gib(parameters, PRECISION_BITS["Q4_K_M"])
    if q4 > budgets.native:
        return "too_large"
    if q4 > budgets.wsl:
        return "high_memory"
    if gib(parameters, PRECISION_BITS["BF16"]) > budgets.vram:
        return "offload"
    return "control_only"


def parameter_count(safetensors, name_tokens, budgets):
    st = _safetensors(safetensors)
    if st is None:
        return Params("none", problem="size_unverified")
    p, total = st["parameters"], st["total"]
    ints = sum(p.get(k, 0) for k in INT_DTYPES)
    floats = sum(v for k, v in p.items() if k not in INT_DTYPES)
    share = ints / total
    dtypes = tuple(sorted(p, key=lambda k: (-p[k], k)))
    if share <= INT_SHARE_MAX:
        return Params("float", value=total, int_share=share, dtypes=dtypes)
    upper = (floats + 2 * (p.get("U8", 0) + p.get("I8", 0)) + 8 * (p.get("U32", 0) + p.get("I32", 0))
             + sum(p.get(k, 0) for k in ("U16", "I16", "U64", "I64", "BOOL")))
    out = Params("packed", lower=total, upper=upper, int_share=share, dtypes=dtypes)
    sizes = [t for t in name_tokens if SIZE_RE.match(t)]
    if len(sizes) == 1:
        out.name_token = sizes[0]
        n = float(sizes[0][:-1]) * 1e9
        if PACKED_NAME_RANGE[0] * total <= n <= PACKED_NAME_RANGE[1] * upper:
            out.value = int(round(n))
        else:
            out.problem = "size_mismatch"
        return out
    low, high = fit_class(total, budgets), fit_class(upper, budgets)
    if low == high:
        out.cls = low
    else:
        out.problem = "size_unverified"
    return out


def size_gate(lb_tokens, repo_tokens, parameters):
    """None when the size-token gate does not apply, else (ok, token, ratio)."""
    def blocked(toks):
        return any(EXPERT_RE.match(t) or MULTI_RE.match(t) for t in toks)
    sl, sh = [t for t in lb_tokens if SIZE_RE.match(t)], [t for t in repo_tokens if SIZE_RE.match(t)]
    if blocked(lb_tokens) or blocked(repo_tokens) or len(sl) > 1 or len(sh) > 1 or not sl + sh:
        return None
    result = None
    for token in sorted(set(sl + sh)):
        ratio = parameters / (float(token[:-1]) * 1e9)
        result = (SIZE_RATIO[0] <= ratio <= SIZE_RATIO[1], token, ratio)
        if not result[0]:
            return result
    return result


@dataclasses.dataclass
class Fit:
    cls: str
    gib: dict                 # precision -> GiB (empty when only a packed range class is known)
    label: str


def bits_to_fit(parameters, budget_gib):
    """The largest bits per weight at which `parameters` weights fit in `budget_gib` (the inverse of gib())."""
    return budget_gib * 8 * 2**30 / parameters


def fit_for(parameters, budgets):
    sizes = {k: gib(parameters, b) for k, b in PRECISION_BITS.items()}
    sizes.update({k: gib(parameters, b) for k, b in INFO_BITS.items()})
    cls = fit_class(parameters, budgets)
    return Fit(cls, sizes, fit_label(cls, budgets, parameters))


def range_fit(cls, lower, upper, budgets):
    """Fit of a packed checkpoint known only by its parameter range; both bounds fall in class `cls`."""
    return Fit(cls, {}, fit_label(cls, budgets, lower, upper))


def fit_label(cls, budgets, lower, upper=None):
    """Label of a fit class for P = lower, or for every P in [lower, upper] (a packed range)."""
    upper = lower if upper is None else upper
    if cls == "too_large":
        most, least = f"{bits_to_fit(lower, budgets.native):.2f}", f"{bits_to_fit(upper, budgets.native):.2f}"
        bits = most if most == least else f"{least}–{most}"
        return (f"would fit {budgets.native:g} GiB only at {bits} bits per weight or fewer"
                + ("" if most == least else ", depending on P within the packed range") + "; not a catalog tier")
    if cls == "high_memory":
        return (f"conditional high-memory tier: native {budgets.native_ram:g} GiB profiles only, start at 4K context; "
                "KV and loader peaks unverified")
    if cls == "offload":
        def within(p):
            return [k for k, b in PRECISION_BITS.items() if budgets.vram < gib(p, b) <= budgets.wsl]
        low, high = within(lower), within(upper)
        head = f"over {budgets.vram:g} GiB and within {budgets.wsl:g} GiB at "
        if low == high:   # G is linear in P: inside the band at both bounds means inside it over the whole range
            return head + (", ".join(low) or "none of the listed precisions") + (
                "" if lower == upper else " over the whole packed range")
        return (head + f"{', '.join(low) or 'none'} at the lower bound and {', '.join(high) or 'none'} at the upper "
                "bound; which precision applies depends on P within the packed range")
    return f"in-VRAM control at every listed precision; does not meet the >{budgets.vram:g} GiB criterion"


# --- Hugging Face model info -------------------------------------------------------------------
@dataclasses.dataclass
class ModelInfo:
    id: str
    sha: str
    private: bool
    disabled: bool
    gated: object
    siblings: list
    card: dict
    tags: list
    created: str
    safetensors: object
    keys: list

    @property
    def org(self):
        return self.id.split("/", 1)[0]

    def licenses(self):
        lic = self.card.get("license")
        values = [lic] if isinstance(lic, str) else [x for x in lic if isinstance(x, str)] if isinstance(lic, list) else []
        values = [v for v in values if v.strip()]
        return values or [t.split(":", 1)[1] for t in self.tags if t.startswith("license:") and t[8:].strip()]

    def license_text(self):
        values = self.licenses()
        text = ", ".join(values)
        if any(v.strip().casefold() == "other" for v in values):
            extra = [str(self.card.get(k)) for k in ("license_name", "license_link") if isinstance(self.card.get(k), str)]
            text += (" (" + "; ".join(extra) + ")") if extra else ""
        return text

    def license_file(self):
        for name in self.siblings:
            if "/" not in name and LICENSE_FILE_RE.match(name) and SAFE_FILE_RE.match(name):
                return name
        return None

    def weights(self):
        return sum(1 for s in self.siblings if s.lower().endswith(".safetensors"))

    def gated_label(self):
        if self.gated in (False, None):
            return "no"
        value = "gated" if self.gated is True else str(self.gated)
        return f"{value}, terms must be accepted"

    def metadata(self):
        return {"id": self.id, "sha": self.sha, "gated": self.gated, "safetensors": self.safetensors}


def parse_info(doc, url):
    if not isinstance(doc, dict):
        raise ShapeError(f"a model-info object from {url}", got=type(doc).__name__)
    if not isinstance(doc.get("id"), str) or not REPO_RE.match(doc["id"]) or not isinstance(doc.get("sha"), str) \
            or not SHA_RE.match(doc["sha"]):
        raise ShapeError(f"model info with an org/name id and a 40-hex sha from {url}",
                         got=excerpt(f"id {doc.get('id')!r}, sha {doc.get('sha')!r}"))
    if not isinstance(doc.get("siblings"), list):
        raise ShapeError(f"model info with a siblings list from {url}", got=type(doc.get("siblings")).__name__)
    if not isinstance(doc.get("private"), bool):
        raise ShapeError(f"model info with a boolean private flag from {url}", got=excerpt(repr(doc.get("private"))))
    siblings = [s["rfilename"] for s in doc["siblings"] if isinstance(s, dict) and isinstance(s.get("rfilename"), str)]
    card = doc.get("cardData") if isinstance(doc.get("cardData"), dict) else {}
    tags = [t for t in doc.get("tags") or [] if isinstance(t, str)]
    created = str(doc.get("createdAt") or "")[:10]
    return ModelInfo(doc["id"], doc["sha"], doc["private"], doc.get("disabled") is True, doc.get("gated", False),
                     siblings, card, tags, created if DATE_RE.match(created) else "", doc.get("safetensors"),
                     sorted(str(k) for k in doc))


def next_link(header):
    for m in re.finditer(r"<([^>]*)>\s*((?:;[^,<]*)*)", header or ""):
        if re.search(r";\s*rel=\"?next\"?", m.group(2)):
            return m.group(1)
    return None


# --- outcomes and notices ----------------------------------------------------------------------
@dataclasses.dataclass(eq=False)
class Outcome:
    row: Row
    kind: str                 # candidate | look | known | decided | closed | info | variant
    reason: str
    counts: bool = False
    repo: object = None
    catalog: object = None    # CatalogModel
    example: object = None    # excluded_latest_examples entry
    publisher: object = None
    prefix: object = None
    match: object = None
    info: object = None
    params: object = None
    fit: object = None
    gate: object = None
    decision: object = None
    found: list = dataclasses.field(default_factory=list)
    found_total: int = 0
    pool_size: int = 0
    status: object = None
    underlying: str = ""
    note: str = ""
    variants: list = dataclasses.field(default_factory=list)
    variant_of: object = None
    hint: object = None       # the LiveBench registry entry of the row, when there is one

    @property
    def reportable(self):
        return self.kind in ("candidate", "look")

    def key(self):
        if self.kind == "candidate":
            return f"cand:{self.row.id}|{self.repo}"
        if self.kind == "look":
            return f"look:{self.row.id}|{self.reason}"
        return None

    def label(self):
        return f"{self.kind}:{self.reason}" if self.kind not in ("candidate",) else "candidate"


@dataclasses.dataclass
class Notice:
    kind: str
    detail: str
    title: str
    lines: list
    clears: str

    def key(self):
        return f"notice:{self.kind}:{self.detail}"


def count_rows(data):
    """Data rows of a CSV that is not analysed (no categories file): tolerant, never raises."""
    text = data.decode("utf-8", errors="replace").lstrip("\ufeff")
    try:
        rows = [r for r in csv.reader(io.StringIO(text, newline="")) if r and any(c.strip() for c in r)]
    except csv.Error:
        rows = [line for line in text.splitlines() if line.strip()]
    return max(len(rows) - 1, 0)


class Discovery:
    def __init__(self, net, root, today, release=None):
        self.net, self.root, self.today = net, pathlib.Path(root), today
        self.forced = release              # a --release id, or None (the newest release)
        self.stage = "local inputs"
        self.local = self.site = self.release = self.script = self.registry = self.suite_order = None
        self.timeline = []
        self.complete = False
        self.header_notes, self.header_warnings, self.warnings, self.notices = [], [], [], []
        self.calibration, self.soft_calibration, self.anchors, self.canary_results = [], [], [], []
        self.taxonomy = self.excluded_check = None
        self.canary_score = (0, 0)
        self.listings, self.listing_pages = {}, 0
        self.info_cache, self.info_calls = {}, 0
        self.limits_hit = []
        self.outcomes, self.pool, self.partial_listed = [], [], []
        self.cutoff, self.below, self.best = None, 0, None

    # .. pipeline ..........................................................................
    def run(self):
        self.local = load_local(self.root, self.today)
        self.site = Site(self.net)
        self.stage = "leaderboard site"
        self.read_site()
        self.stage = "release discovery"
        self.discover_releases()
        self.stage = "calibration"
        self.calibrate()
        self.stage = "Hugging Face anchors"
        self.check_anchors()
        self.stage = "release table"
        self.pick_release()
        self.stage = "notices"
        self.static_notices()
        self.stage = "matcher canary"
        self.canary()
        self.stage = "walk"
        self.walk()
        self.stage = "rendering"
        self.complete = True
        return self

    def read_site(self):
        path, text = self.site.main_script()
        body = self.site.get(path, "js").body
        self.script = {"path": path, "url": SITE_URL + path, "sha256": hashlib.sha256(body).hexdigest(),
                       "bytes": len(body)}
        self.timeline = parse_release_lists(text)
        if f'"{WEIGHTS_KEY}"' not in text:
            raise ShapeError(f'the averaging code\'s "{WEIGHTS_KEY}" literal in {path}', got="no such literal")
        self.suite_order = parse_suite_order(text)
        self.registry = parse_registries(text)
        if self.registry.problem:
            self.header_warnings.append(f"LiveBench's model registry is not used: {md_code(self.registry.problem, EXCERPT_CAP)}"
                                        "; matching uses the name rules alone.")

    def entry(self, date):
        return next((r for r in self.timeline if r.date == date), None)

    def discover_releases(self):
        latest = self.local.evidence.latest_release
        if self.entry(latest) is None:
            raise ShapeError(f"release {latest} (latest_release in catalog/livebench-evidence.json) on the "
                             "livebench.ai timeline: leaderboard layout changed",
                             got="timeline " + excerpt(", ".join(r.id for r in self.timeline)))
        if self.forced is not None:
            self.forced_entry()

    def forced_entry(self):
        """The timeline entry --release names: v1 YYYY-MM-DD, or a 2.0 release as YYYYMMDD or YYYY-MM-DD."""
        rid = self.forced
        found = None
        if V2_ID_RE.match(rid):
            found = next((r for r in self.timeline if r.generation == "2.0" and r.id == rid), None)
        elif V1_ID_RE.match(rid):
            found = self.entry(rid)
        if found is None:
            v1 = ", ".join(r.id for r in self.timeline if r.generation == "v1")
            v2 = ", ".join(r.id for r in self.timeline if r.generation == "2.0")
            raise ConfigError(f"--release {plain(rid, 40)} is not on the livebench.ai timeline (v1: {v1}; 2.0: {v2})")
        return found

    def load_release(self, entry):
        table_url, cats_url = SITE_URL + entry.table_path, SITE_URL + entry.categories_path
        table_bytes = self.site.get(entry.table_path, "csv", cap=MAX_TABLE_BYTES).body
        cat_bytes = self.site.get(entry.categories_path, "json", cap=MAX_TABLE_BYTES).body
        categories, weights, ignored = parse_categories(cat_bytes, cats_url, entry.generation)
        scored, partial, extras = score_table(read_csv(table_bytes, table_url), categories, entry.generation, weights,
                                              self.suite_order or REVIEWED_SUITE_ORDER)
        return Release(entry, hashlib.sha256(table_bytes).hexdigest(), hashlib.sha256(cat_bytes).hexdigest(),
                       categories, weights, ignored, scored, partial, extras)

    def pick_release(self):
        if self.forced is not None:
            entry = self.forced_entry()
            try:
                self.release = self.load_release(entry)
            except HttpStatus as exc:
                if exc.code not in (404, 410):
                    raise
                raise ShapeError(f"the table and categories files of release {entry.label} (forced with --release)",
                                 got=f"HTTP {exc.code} for {urllib.parse.urlsplit(exc.url).path}") from None
            n = len(self.release.scored)
            self.header_notes.append(f"release {entry.date} is analysed because --release named it (a forced run never "
                                     "touches the tracking issue)"
                                     + (f"; it has only {n} scored rows (in progress?)" if n < MIN_RELEASE_ROWS else ""))
        else:
            self.pick_newest()
        self.registry.rank([r.id for r in self.release.scored + self.release.partial])
        if self.release.generation == "2.0" and self.suite_order is None:
            self.header_warnings.append(
                f"the site's suite order (the list its rn() sorts the suites by) was not found in `{self.script['path']}`; "
                "overalls add the suites in the order of the reviewed script (" + ", ".join(REVIEWED_SUITE_ORDER)
                + "), so one can differ from the site's in the last digit.")
        if self.release.ignored_weights:
            self.header_notes.append("weights the site's code ignores in `" + self.release.entry.categories_path + "`: "
                                     + ", ".join(f"{md_code(n)} = {w!r} ({why})" for n, w, why in self.release.ignored_weights))

    def pick_newest(self):
        latest, waiting = self.local.evidence.latest_release, []
        for entry in reversed(self.timeline):
            if entry.date < latest:
                break
            try:
                table = self.site.get(entry.table_path, "csv", cap=MAX_TABLE_BYTES)
            except HttpStatus as exc:
                if exc.code not in (404, 410):
                    raise
                self.header_notes.append(f"release {entry.label} is on the site's timeline, but `{entry.table_path}` "
                                         f"answers HTTP {exc.code}; not analysed")
                continue
            try:
                self.site.get(entry.categories_path, "json", cap=MAX_TABLE_BYTES)
            except HttpStatus as exc:
                if exc.code not in (404, 410):
                    raise
                rows = count_rows(table.body)
                if rows >= MIN_RELEASE_ROWS:
                    self.notices.append(Notice(
                        "release_without_categories", entry.date,
                        f"Release {entry.date} published without a categories file; not analysed (layout change?)",
                        [f"`{entry.table_path}` has {rows} data rows on livebench.ai and `{entry.categories_path}` "
                         f"answers HTTP {exc.code}."],
                        "Clears when LiveBench publishes the categories file (the release is then analysed) or "
                        "removes the release."))
                else:
                    self.header_notes.append(f"`{entry.table_path}` ({rows} rows) has no categories file yet; not analysed.")
                continue
            release = self.load_release(entry)
            if len(release.scored) >= MIN_RELEASE_ROWS:
                self.release = release
                break
            waiting.append((entry.date, len(release.scored)))
        if self.release is None:
            raise ShapeError(f"a release on or after {latest} with at least {MIN_RELEASE_ROWS} scored rows",
                             got=", ".join(f"{d}: {n} scored rows" for d, n in waiting) or "no release loaded")
        for date, n in waiting:
            self.header_notes.append(f"release {date} looks in progress ({n} scored rows); analysing {self.release.date}")

    # .. calibration ..........................................................................
    def site_file(self, path, kind, what):
        """Bytes of a release file calibration needs; a missing one is a calibration failure."""
        try:
            return self.site.get(path, kind, cap=MAX_TABLE_BYTES).body
        except HttpStatus as exc:
            if exc.code in (404, 410):
                raise ShapeError(f"calibration failed: {what} at {SITE_URL}{path}", got=f"HTTP {exc.code}") from None
            raise

    def calibrate(self):
        ev = self.local.evidence
        v1_dates = [r.date for r in self.timeline if r.generation == "v1"]
        groups = {}
        for rec in ev.recommendations:
            groups.setdefault(rec.site_path, []).append(rec)
        for path, recs in groups.items():
            if recs[0].generation == "2.0":
                self.check_recorded_v2(path, recs)
                continue
            name, url = recs[0].table_name, SITE_URL + path
            data = self.site_file(path, "csv", f"the recorded table {name}")
            digest = hashlib.sha256(data).hexdigest()
            if digest != recs[0].sha256:
                raise ShapeError(f"calibration failed: {url} with the recorded sha256 {recs[0].sha256}", got=f"sha256 {digest}")
            raw = read_csv(data, url)
            own = "-".join(TABLE_NAME_RE.match(name).groups())
            order = [own] + sorted((d for d in v1_dates if d != own),
                                   key=lambda d: (abs((dt.date.fromisoformat(d) - dt.date.fromisoformat(own)).days), d))
            first_problem, used = None, None
            for cdate in order:
                cpath = f"v1/categories_{cdate.replace('-', '_')}.json"
                try:
                    cbytes = self.site.get(cpath, "json", cap=MAX_TABLE_BYTES).body
                except HttpStatus as exc:
                    if exc.code not in (404, 410):
                        raise
                    first_problem = first_problem or f"{cpath}: HTTP {exc.code}"
                    continue
                categories, _, _ = parse_categories(cbytes, SITE_URL + cpath)
                header = {h.strip() for h in raw.header}
                missing = [t for ts in categories.values() for t in ts if t not in header]
                if missing:
                    first_problem = first_problem or f"{cpath}: task {missing[0]} is not a column"
                    continue
                scored, partial, _ = score_table(raw, categories)
                problem, names_differ = reproduces(scored + partial, recs)
                if problem is None:
                    used = (cpath.split("/", 1)[1], names_differ)
                    break
                first_problem = first_problem or f"{cpath}: {problem}"
            if used is None:
                raise ShapeError(f"calibration failed: no categories file on livebench.ai/v1/ reproduces the recorded "
                                 f"scores of {name}", got=first_problem or "no categories files")
            self.calibration.append({"table": name, "url": url, "sha256": digest, "categories": used[0],
                                     "rows": len(recs), "fallback": used[0] != f"categories_{own.replace('-', '_')}.json",
                                     "names_differ": used[1]})
        bench = self.local.benchmarks
        ref = self.entry(bench.reference_release)
        if ref is None or ref.generation != "v1":
            raise ShapeError(f"catalog/benchmarks.json reference_release {bench.reference_release} as a v1 release on the "
                             "livebench.ai timeline (2.0 suites are another taxonomy, never compared with benchmarks.json)",
                             got="not on the timeline" if ref is None else "a 2.0 release")
        url = SITE_URL + ref.categories_path
        reference, _, _ = parse_categories(self.site_file(ref.categories_path, "json", "the reference categories"), url)
        if partition(reference) != bench.partition:
            raise ShapeError(f"calibration failed: {url} with the task partition of catalog/benchmarks.json "
                             f"({len(bench.partition)} sets, {sum(len(s) for s in bench.partition)} tasks)",
                             got=partition_diff(reference, bench.categories),
                             fix="livebench.ai serves this file unversioned. If LiveBench changed it, record the new "
                                 "partition in catalog/benchmarks.json together with catalog/livebench-evidence.json "
                                 "(latest_release, checked_on and the recorded rows of that release) in one change; "
                                 "editing either file alone leaves them disagreeing.")
        self.taxonomy = {"file": ref.categories_path, "url": url, "sets": len(bench.partition),
                         "tasks": sum(len(s) for s in bench.partition)}
        self.check_excluded_examples()

    def check_recorded_v2(self, path, recs):
        """Soft: a recorded 2.0 row. 2.0 tables are not versioned and grow as LiveBench adds rows, so other bytes are
        a warning, never a failure; the same bytes must reproduce the recorded scores with the site's averaging."""
        url, entry = SITE_URL + path, None
        date = "-".join(SITE_V2_TABLE_RE.match(url).group(2, 3, 4))
        result = {"table": path, "rows": len(recs), "status": None}
        self.soft_calibration.append(result)
        entry = next((r for r in self.timeline if r.generation == "2.0" and r.date == date), None)
        try:
            if entry is None:
                raise ShapeError(f"release {date} on the timeline", got="absent")
            data = self.site.get(path, "csv", cap=MAX_TABLE_BYTES).body
            digest = hashlib.sha256(data).hexdigest()
            if digest != recs[0].sha256:
                result["status"] = "changed"
                self.warnings.append(f"recorded 2.0 rows of `{path}` not re-checked: livebench.ai now serves other bytes "
                                     f"(sha256 `{digest}`, recorded `{recs[0].sha256}`); 2.0 tables are not versioned")
                return
            release = self.load_release(entry)
            problem, _ = reproduces(release.scored + release.partial, recs)
        except (ShapeError, HttpStatus) as exc:
            result["status"] = "unreadable"
            self.warnings.append(f"recorded 2.0 rows of `{path}` not re-checked: {md_code(exc, EXCERPT_CAP)}")
            return
        result["status"] = "reproduced" if problem is None else "differs"
        if problem:
            self.warnings.append(f"recorded 2.0 rows of `{path}` do not reproduce: {md_code(problem, EXCERPT_CAP)}")

    def check_excluded_examples(self):
        """Soft: the evidence's excluded examples' scores still appear in their release table on livebench.ai."""
        self.excluded_check, scored = [], {}
        for ex in self.local.evidence.excluded:
            date = ex["release"]
            try:
                entry = self.entry(date)
                if entry is None:
                    raise ShapeError(f"release {date} on the livebench.ai timeline", got="absent")
                if date not in scored:
                    scored[date] = self.load_release(entry).scored
                hits = [r for r in scored[date] if abs(r.overall - ex["score"]) <= OVERALL_TOL]
            except (ShapeError, HttpStatus) as exc:
                self.warnings.append(f"excluded-example check for {md_code(ex['model'])} not run: {md_code(exc, EXCERPT_CAP)}")
                self.excluded_check.append({"model": ex["model"], "score": ex["score"], "found": None})
                continue
            if not hits:
                self.warnings.append(f"no row of the {date} table on livebench.ai has the overall {ex['score']:.2f} "
                                     f"recorded for {md_code(ex['model'])}")
            self.excluded_check.append({"model": ex["model"], "score": ex["score"], "found": hits[0].id if hits else None})

    def check_anchors(self):
        for cid in HF_ANCHORS:
            model = self.local.by_id[cid]
            meta = model.metadata
            url = f"https://{HF_HOST}/api/models/{urllib.parse.quote(model.repo, safe='/')}/revision/{meta['sha']}"
            try:
                doc = self.net.get(url).json()
            except HttpStatus as exc:
                if exc.code in (401, 403, 404):
                    raise ShapeError(f"Hugging Face anchor {cid} ({model.repo}) readable at {meta['sha'][:12]}",
                                     got=f"HTTP {exc.code}") from None
                raise
            if not isinstance(doc, dict):
                raise ShapeError("Hugging Face metadata shape changed: a model-info object", got=type(doc).__name__)
            recorded, reported = meta["safetensors"], _safetensors(doc.get("safetensors"))
            # id, sha, total, the set of dtypes and every float count must be as recorded; an integer count may differ
            # (Hugging Face changed how it counts packed U8 elements at unchanged revisions): a warning only.
            same = (str(doc.get("id", "")).casefold() == model.repo.casefold() and doc.get("sha") == meta["sha"]
                    and reported is not None and reported["total"] == recorded["total"]
                    and set(reported["parameters"]) == set(recorded["parameters"])
                    and all(reported["parameters"][k] == v for k, v in recorded["parameters"].items() if k not in INT_DTYPES))
            if not same:
                raise ShapeError(f"Hugging Face metadata shape changed: {cid} revision {meta['sha'][:12]} with the "
                                 "id, sha, safetensors total, dtypes and float counts recorded in catalog/models.json",
                                 got=excerpt(compact({k: doc.get(k) for k in ("id", "sha", "safetensors")})))
            int_changes = [(k, reported["parameters"][k], v) for k, v in sorted(recorded["parameters"].items())
                           if k in INT_DTYPES and reported["parameters"][k] != v]
            for k, now, then in int_changes:
                self.header_warnings.append(
                    f"Hugging Face now reports {k} = {now} at the recorded revision of {md_code(model.repo)} "
                    f"(`{meta['sha'][:12]}`); catalog records {then}; packed size ranges use the reported counts.")
            names = tokens(model.repo, model.repo.split("/")[0])
            kinds = {parameter_count(st, names, self.local.budgets).kind for st in (recorded, reported)}
            if kinds != {ANCHOR_CLASSES[cid]}:
                raise ShapeError(f"anchor {cid} classified as a {ANCHOR_CLASSES[cid]} checkpoint",
                                 got=" / ".join(sorted(kinds)) + " (recorded / reported counts)")
            note = ""
            if doc.get("gated") != meta["gated"]:
                note = f"gated is {doc.get('gated')!r}, catalog records {meta['gated']!r}"
                self.warnings.append(f"HF anchor `{cid}`: {md_code(note)} (a repo-level setting; not a shape change)")
            self.anchors.append({"catalog_id": cid, "repo": model.repo, "sha": meta["sha"], "class": ANCHOR_CLASSES[cid],
                                 "note": note, "int_changes": [{"dtype": k, "reported": a, "recorded": b}
                                                               for k, a, b in int_changes]})

    # .. notices that need no Hugging Face ...................................................
    def static_notices(self):
        ev, r = self.local.evidence, self.release
        if r.date > ev.latest_release:
            releases = self.local.releases
            scorer = ("scorer support unknown (RELEASES not found in src/llm_eval/livebench.py)" if releases is None
                      else f"{r.date} is in `src/llm_eval/livebench.py` RELEASES: the pinned scorer lane can run it"
                      if r.date in releases else
                      f"{r.date} is not in `src/llm_eval/livebench.py` RELEASES: the pinned scorer lane cannot run it yet")
            gen = "v1" if r.generation == "v1" else f"LiveBench 2.0, id `{r.id}`"
            lines = [f"LiveBench publishes release {r.date} ({gen}, {len(r.scored)} scored rows) on livebench.ai; "
                     f"catalog/livebench-evidence.json still records latest_release {ev.latest_release}. Releases are "
                     "different test sets: keep every recorded score labelled with its own release."]
            if r.generation == "v1":
                lines.append("Categories and tasks against catalog/benchmarks.json: "
                             + partition_diff(r.categories, self.local.benchmarks.categories, markdown=True))
            else:
                lines.append("Its suites are LiveBench 2.0's own taxonomy, never compared with catalog/benchmarks.json: "
                             + ", ".join(md_code(c) for c in r.categories) + "; overall: "
                             + weights_text(r.weights, list(r.categories)) + ".")
            lines += [scorer,
                      "Checklist: catalog/livebench-evidence.json `latest_release` / `checked_on`; "
                      "catalog/benchmarks.json `reference_release` / categories; catalog/installers.json `livebench.release`; "
                      "`RELEASES` in src/llm_eval/livebench.py; docs/LIVEBENCH.md."]
            self.notices.append(Notice("new_release", r.date, f"New LiveBench release {r.date}", lines,
                                       "Clears when catalog/livebench-evidence.json `latest_release` records it: that edit is the decision."))
        reviewed, served = self.local.site.main_script, self.script["path"]
        if served != reviewed:
            self.notices.append(Notice(
                "site_code_changed", served, "Leaderboard site code changed",
                [f"the averaging code was reviewed in {md_code(reviewed)} (on {self.local.site.reviewed_on}); re-read the "
                 f"weights rule in {md_code(served)} ([script]({SITE_URL}{served})) and update `site` once it still "
                 "holds. Candidates are not withheld: the site's bundle changes on every deploy, and the run still "
                 f"requires the `{WEIGHTS_KEY}` literal and checks every categories file's weights."],
                "Clears when `site.main_script` in catalog/model-discovery.json names the served script (with "
                "`site.reviewed_on` the date it was re-read)."))


    # .. Hugging Face ............................................................................
    def fetch_info(self, repo):
        """ModelInfo, or the status code for 401/403/404/410 (unauthenticated HF answers 401 for missing repos)."""
        url = f"https://{HF_HOST}/api/models/{urllib.parse.quote(repo, safe='/')}"
        try:
            return parse_info(self.net.get(url).json(), url)
        except HttpStatus as exc:
            if exc.code in (401, 403, 404, 410):
                return exc.code
            raise

    def model_info(self, repo):
        key = repo.casefold()
        if key not in self.info_cache:
            if self.info_calls >= MAX_MODEL_INFO:
                if "model info" not in self.limits_hit:
                    self.limits_hit.append("model info")
                return None
            self.info_calls += 1
            self.info_cache[key] = self.fetch_info(repo)
        return self.info_cache[key]

    def listing(self, org):
        key = org.casefold()
        if key in self.listings:
            return self.listings[key]
        url = f"https://{HF_HOST}/api/models?author={urllib.parse.quote(org, safe='')}&limit={LISTING_LIMIT}"
        ids, pages = [], 0
        while url:
            if pages >= MAX_LISTING_PAGES or self.listing_pages >= MAX_LISTING_PAGES_RUN:
                self.limits_hit.append(f"listing pages ({org})")
                raise ShapeError(f"a complete listing of {org} within {MAX_LISTING_PAGES} pages per org and "
                                 f"{MAX_LISTING_PAGES_RUN} per run", got=f"{pages} pages of {org}, {self.listing_pages} in this run")
            reply = self.net.get(url)
            pages += 1
            self.listing_pages += 1
            doc = reply.json()
            if not isinstance(doc, list):
                raise ShapeError(f"a JSON array of models from {url}", got=type(doc).__name__)
            for e in doc:
                if not isinstance(e, dict) or not isinstance(e.get("id"), str) or not REPO_RE.match(e["id"]):
                    raise ShapeError(f"listing entries with an org/name id from {url}", got=excerpt(compact(e)))
                if e["id"].split("/")[0].casefold() == key:
                    ids.append(e["id"])
            nxt = next_link(reply.headers.get("link"))
            if len(doc) == LISTING_LIMIT and not nxt:
                raise ShapeError(f"a next link after a full page of {LISTING_LIMIT} entries from {url}", got="no rel=next link")
            if nxt and not nxt.startswith(f"https://{HF_HOST}/"):
                raise ShapeError(f"a next link on https://{HF_HOST}/", got=excerpt(nxt))
            url = nxt
        self.listings[key] = ids
        self.listing_guard(org, ids)
        return ids

    def listing_guard(self, org, ids):
        present = {i.casefold() for i in ids}
        for model in self.local.models:
            if model.repo.split("/")[0].casefold() != org.casefold() or model.repo.casefold() in present:
                continue
            info = self.fetch_info(model.repo)
            if isinstance(info, int):
                self.notices.append(Notice("catalog_repo_gone", model.repo, f"Catalog repo {model.repo} no longer on Hugging Face",
                                           [f"`{model.id}` (`{model.repo}`) is missing from the {org} listing and its model "
                                            f"info answers HTTP {info}."],
                                           "Clears when the repository is back or catalog/models.json is updated."))
            elif info.id.casefold() == model.repo.casefold():
                raise ShapeError(f"a complete Hugging Face listing of {org}", got=f"{model.repo} exists but is not listed")
            else:
                self.notices.append(Notice("catalog_repo_renamed", model.repo, f"Catalog repo {model.repo} renamed",
                                           [f"`{model.id}`: catalog repo renamed to {md_code(info.id)} on Hugging Face."],
                                           "Clears when catalog/models.json records the new repository id."))

    # .. matcher canary .......................................................................
    def canary(self):
        ok = total = 0
        for rec in self.local.evidence.recommendations:
            model = self.local.by_id[rec.model_id]
            org = model.repo.split("/")[0]
            name_equal = tokens(rec.lb_id, org) == tokens(model.repo, org)
            total += name_equal
            pub, _ = self.local.publisher(rec.lb_id)
            if pub is None:
                self.header_warnings.append(f"matcher canary: {md_code(rec.lb_id)} has no publisher entry")
                self.canary_results.append({"id": rec.lb_id, "expected": model.repo, "result": "no publisher", "tier": None,
                                            "name_equal": name_equal})
                continue
            # As the walk would resolve the id: the repository LiveBench's registry links (the release's own
            # registry), else the strict matcher's answer.
            hint = self.registry.get(rec.lb_id) if self.registry else None
            status, found, _ = self.locate(rec.lb_id, pub, hint)
            named = status in ("match", "outside")
            if named and found.repo.casefold() != model.repo.casefold():
                if found.tier != "linked":
                    raise ShapeError(f"matcher canary: {rec.lb_id} resolving to the catalog repo {model.repo}",
                                     got=f"the strict matcher names {found.repo}")
                # LiveBench's data, not the matcher, disagrees; the evidence keeps deciding the row.
                self.header_warnings.append(f"matcher canary: LiveBench's registry links {md_code(found.repo)} for "
                                            f"{md_code(rec.lb_id)}; the catalog records {md_code(model.repo)}")
            elif status == "match":
                ok += name_equal
            elif name_equal:
                self.header_warnings.append(f"matcher canary: {md_code(rec.lb_id)} is now {status} (expected {md_code(model.repo)})")
            self.canary_results.append({"id": rec.lb_id, "expected": model.repo, "result": found.repo if named else status,
                                        "tier": found.tier if named else None, "name_equal": name_equal})
        self.canary_score = (ok, total)

    # .. walk .....................................................................................
    def walk(self):
        by_repo, rows = {}, self.release.scored
        for i, row in enumerate(rows):
            if len(self.pool) >= POOL_SIZE and row.overall < self.pool[POOL_SIZE - 1].row.overall - 1e-9:
                self.below = len(rows) - i
                break
            o = self.resolve(row)
            if o.counts and o.repo:
                entry = by_repo.get(o.repo.casefold())
                if entry is not None:
                    o.variant_of, o.counts, o.kind = entry, False, "variant"
                    entry.variants.append(o)
                    self.outcomes.append(o)
                    continue
                by_repo[o.repo.casefold()] = o
            if o.counts:
                self.pool.append(o)
            self.outcomes.append(o)
        if self.pool:
            self.cutoff = self.pool[min(POOL_SIZE, len(self.pool)) - 1].row.overall
        self.partial_listed = [r for r in self.release.partial if r.partial_mean is not None
                               and (self.cutoff is None or r.partial_mean >= self.cutoff - 1e-9)]
        catalogued = [o for o in self.outcomes if o.kind == "known" and o.catalog and o.catalog.status != "excluded"]
        if catalogued:
            self.best = catalogued[0]
        else:
            for row in rows[len(self.outcomes):]:
                rec = self.local.evidence_by_lb.get(row.id)
                if rec and self.local.by_id[rec.model_id].status != "excluded":
                    self.best = Outcome(row, "known", "evidence", repo=self.local.by_id[rec.model_id].repo,
                                        catalog=self.local.by_id[rec.model_id])
                    break

    def resolve(self, row):
        L = self.local
        d = L.decisions.for_lb(row.id)
        kind = d["decision"] if d is not None else None
        pub, prefix = L.publisher(row.id)
        hint = self.registry.get(row.id) if self.registry else None
        o = self.resolve_with(row, d, kind, pub, prefix, hint)
        o.hint = hint
        return o

    def resolve_with(self, row, d, kind, pub, prefix, hint):
        L = self.local
        if kind == "alias":
            return self.alias(row, d, pub, prefix)
        if kind == "rejected":
            return Outcome(row, "decided", "rejected", counts=True, decision=d)
        if kind == "deferred" and self.today <= iso_date(d["until"]):
            return Outcome(row, "decided", "deferred", counts=True, decision=d)
        if kind == "not_open_weight" and pub is None:
            note = (f"LiveBench's registry lists it as open weight (links {hint.link})" if hint and hint.openweight
                    and hint.link else "LiveBench's registry lists it as open weight" if hint and hint.openweight else "")
            return Outcome(row, "decided", "not_open_weight", decision=d, note=note)
        # Left: no lb: decision, an expired deferral, or not_open_weight with a publisher. A row that resolves to a
        # known model is known whatever such a decision (or LiveBench's registry) says: catalogued models are never
        # raised or shadowed.
        rec = L.evidence_by_lb.get(row.id)
        if rec:
            model = L.by_id[rec.model_id]
            return self.stale(self.known(row, "evidence", model.repo, model), d)
        if kind == "deferred":
            if pub is not None:
                status, found, _ = self.locate(row.id, pub, hint)
                known = self.known_repo(found.repo) if status in ("match", "outside") else None
                if known:
                    return self.stale(self.known(row, known[0], found.repo, known[1], known[2], match=found), d)
            return Outcome(row, "look", "deferral_expired", counts=True, decision=d, publisher=pub, prefix=prefix)
        if kind is None and hint is not None and not hint.openweight:
            return self.closed(row, pub, prefix)
        if pub is None:
            if hint is not None and hint.link:
                return self.linked_outside(row, hint.link, None, None)
            return Outcome(row, "look", "unknown_publisher", counts=True)
        status, found, pool = self.locate(row.id, pub, hint)
        if status == "outside":
            if kind == "not_open_weight":
                known = self.known_repo(found.repo)
                if known:
                    return self.stale(self.known(row, known[0], found.repo, known[1], known[2], match=found), d)
                return Outcome(row, "decided", "not_open_weight", decision=d,
                               note=f"LiveBench links {found.repo}, outside the publisher's orgs")
            return self.linked_outside(row, found.repo, pub, prefix)
        if kind == "not_open_weight":
            if status != "match":
                return Outcome(row, "decided", "not_open_weight", decision=d, pool_size=pool)
            o = self.evaluate(row, found, pub, prefix)
            if o.reportable:
                o.underlying, o.kind, o.reason, o.counts, o.decision = o.label(), "look", "weights_may_be_public", True, d
                return o
            if o.kind == "known" or o.reason == "too_large":   # catalogued, or public weights: the decision is stale
                return self.stale(o, d)
            return Outcome(row, "decided", "not_open_weight", decision=d, repo=found.repo,
                           note=f"strict match {found.repo}: {o.label()}")
        if status == "ambiguous":
            return Outcome(row, "look", "ambiguous", counts=True, publisher=pub, prefix=prefix, found=found[:5],
                           found_total=len(found), pool_size=pool)
        if status == "no_repo":
            return Outcome(row, "look", "no_repo", counts=True, publisher=pub, prefix=prefix, pool_size=pool)
        return self.evaluate(row, found, pub, prefix)

    def locate(self, lb_id, pub, hint):
        """The repository a leaderboard id names: the one LiveBench's registry links (an open-weight entry with a
        huggingface: link), else the strict matcher's answer. ('match', Match, pool) | ('ambiguous', [Match], pool) |
        ('no_repo', None, pool) | ('outside', Match, 0) for a link outside the publisher's orgs."""
        if hint is not None and hint.openweight and hint.link:
            org = hint.link.split("/")[0]
            m = Match(hint.link, org, "linked", [], 0, [], 0)
            inside = org.casefold() in {o.casefold() for o in pub.orgs}
            return ("match" if inside else "outside"), m, 0
        return strict_match(lb_id, pub.orgs, self.listing)

    def closed(self, row, pub, prefix):
        """A row LiveBench's registry lists without openweight: like a not_open_weight decision, it takes no place in
        the pool, unless it is catalogued or a strict match in an allowlisted org exists ("weights may be public")."""
        why = "LiveBench's registry lists it without openweight"
        if pub is None:
            return Outcome(row, "closed", "livebench_closed")
        status, found, pool = strict_match(row.id, pub.orgs, self.listing)
        if status != "match":
            return Outcome(row, "closed", "livebench_closed", publisher=pub, prefix=prefix, pool_size=pool)
        o = self.evaluate(row, found, pub, prefix)
        if o.reportable:
            o.underlying, o.kind, o.reason, o.counts = o.label(), "look", "weights_may_be_public", True
            o.note = why
            return o
        if o.kind == "known" or o.reason == "too_large":
            o.note = f"{why}; the row resolves to {o.repo} ({o.label()})"
            return o
        return Outcome(row, "closed", "livebench_closed", repo=found.repo, publisher=pub, prefix=prefix,
                       note=f"strict match {found.repo}: {o.label()}")

    def linked_outside(self, row, repo, pub, prefix):
        """LiveBench links a repository outside the publisher's orgs (or the row has no publisher): never a candidate."""
        match = Match(repo, repo.split("/")[0], "linked", [], 0, [], 0)
        found = self.known_repo(repo)
        if found:
            return self.known(row, found[0], repo, found[1], found[2], match=match)
        base = {"repo": repo, "match": match, "publisher": pub, "prefix": prefix}
        return self.repo_decision(row, repo, base) or Outcome(row, "look", "linked_outside_publisher", counts=True, **base)


    @staticmethod
    def stale(o, d):
        """`o` with a note that the lb: decision `d` (when there is one) no longer decides the row."""
        if d is not None:
            o.note = f"{d['key']} ({d['decision']}) no longer applies: the row resolves to {o.repo} ({o.label()})"
        return o

    def known_repo(self, repo):
        L, key = self.local, repo.casefold()
        if key in L.by_repo:
            return "catalog", L.by_repo[key], None
        if key in L.excluded_by_repo:
            return "excluded_example", None, L.excluded_by_repo[key]
        org = repo.split("/")[0]
        own = stem(tokens(repo, org))
        for model in L.models:
            if model.repo.split("/")[0].casefold() == org.casefold() and stem(tokens(model.repo, org)) == own:
                return "precision_sibling", model, None
        for ex in L.evidence.excluded:
            if ex["model"].split("/")[0].casefold() == org.casefold() and stem(tokens(ex["model"], org)) == own:
                return "precision_sibling", None, ex
        return None

    def catalog_fit(self, model):
        meta = model.metadata or {}
        if meta.get("safetensors"):
            params = parameter_count(meta["safetensors"], tokens(model.repo, model.repo.split("/")[0]), self.local.budgets)
            if params.value:
                return params, fit_for(params.value, self.local.budgets)
            if params.cls:
                return params, range_fit(params.cls, params.lower, params.upper, self.local.budgets)
        if model.parameters_b:
            value = int(round(model.parameters_b * 1e9))
            return Params("catalog", value=value), fit_for(value, self.local.budgets)
        return None, None

    def known(self, row, kind, repo, model=None, example=None, match=None, decision=None):
        o = Outcome(row, "known", kind, repo=repo, catalog=model, example=example, match=match, decision=decision)
        if model is not None:
            o.params, o.fit = self.catalog_fit(model)
            o.counts = model.status in RUNNABLE_STATUSES and (o.fit is None or o.fit.cls != "too_large")
        return o

    def evaluate(self, row, match, pub, prefix):
        found = self.known_repo(match.repo)
        if found:
            kind, model, example = found
            return self.known(row, kind, match.repo, model, example, match=match)
        base = {"repo": match.repo, "match": match, "publisher": pub, "prefix": prefix, "pool_size": match.pool_size}
        decided = self.repo_decision(row, match.repo, base)
        if decided:
            return decided
        info = self.model_info(match.repo)
        if info is None:
            return Outcome(row, "look", "not_checked", counts=True, **base)
        if isinstance(info, int):
            return Outcome(row, "look", "info_unreadable", counts=True, status=info, **base)
        if info.id.casefold() != match.repo.casefold():
            # Hugging Face serves the repository under another name (renamed: a registry link, say, spells the old
            # one): the catalog and hf: decisions are checked again under that name, as for an alias target.
            found = self.known_repo(info.id)
            if found:
                kind, model, example = found
                return self.known(row, kind, info.id, model, example, match=match)
            base["repo"] = info.id
            decided = self.repo_decision(row, info.id, base)
            if decided:
                return decided
        return self.gates(row, info, base, pub.orgs)

    def alias(self, row, d, pub, prefix):
        target = d["target"]
        found = self.known_repo(target)
        if found and found[0] == "catalog":
            return self.known(row, "alias_to_catalog", target, found[1], decision=d)
        match = Match(target, target.split("/")[0], "alias", [], 0, [], 0)
        base = {"repo": target, "match": match, "publisher": pub, "prefix": prefix, "decision": d}
        decided = self.repo_decision(row, target, base)   # hf: decisions apply to an alias target as to a match
        if decided:
            return decided
        info = self.model_info(target)
        if info is None:
            return Outcome(row, "look", "not_checked", counts=True, **base)
        orgs = pub.orgs if pub else self.local.all_orgs()
        if isinstance(info, int) or info.private or info.disabled or info.org.casefold() not in {o.casefold() for o in orgs}:
            return Outcome(row, "look", "alias_target_unavailable", counts=True, info=None if isinstance(info, int) else info,
                           status=info if isinstance(info, int) else None, **base)
        found = self.known_repo(info.id)
        if found:
            kind = "alias_to_catalog" if found[0] == "catalog" else found[0]
            return self.known(row, kind, info.id, found[1], found[2], match=match, decision=d)
        base["repo"] = info.id
        return self.repo_decision(row, info.id, base) or self.gates(row, info, base, orgs)

    def repo_decision(self, row, repo, base):
        """The outcome of the hf: decision covering `repo`, or None when there is none."""
        d = self.local.decisions.for_repo(repo)
        if d is None:
            return None
        base = {**base, "decision": d}
        if d["decision"] == "rejected" or self.today <= iso_date(d["until"]):
            return Outcome(row, "decided", d["decision"], counts=True, **base)
        return Outcome(row, "look", "deferral_expired", counts=True, **base)

    def gates(self, row, info, base, orgs):
        b = self.local.budgets
        o = Outcome(row, "info", "", info=info, **base)
        if info.org.casefold() not in {x.casefold() for x in orgs}:
            o.kind, o.reason, o.counts = "look", "moved_outside_publisher", True
            return o
        if info.private or info.disabled:
            o.reason = "private" if info.private else "disabled"
            return o
        if not info.weights():
            o.reason = "no_weights_yet"
            return o
        name_tokens = tokens(info.id, info.org)
        o.params = parameter_count(info.safetensors, name_tokens, b)
        if o.params.kind == "float":
            o.gate = size_gate(tokens(row.id, info.org), name_tokens, o.params.value)
            if o.gate and not o.gate[0]:
                o.kind, o.reason, o.counts = "look", "size_mismatch", True
                return o
        if o.params.problem:
            o.kind, o.reason, o.counts = "look", o.params.problem, True
            return o
        o.fit = (fit_for(o.params.value, b) if o.params.value
                 else range_fit(o.params.cls, o.params.lower, o.params.upper, b))
        if o.fit.cls == "too_large":
            o.reason = "too_large"
            return o
        if not info.licenses():
            o.kind, o.reason, o.counts = "look", "no_license", True
            return o
        o.kind, o.reason, o.counts = "candidate", "candidate", True
        return o

    # .. results .................................................................................
    def listed_candidates(self):
        return [o for o in self.outcomes if o.kind == "candidate"]

    def looks(self):
        return [o for o in self.outcomes if o.kind == "look"]

    @property
    def reportable(self):
        return bool(self.notices or self.looks() or any(o.kind == "candidate" for o in self.outcomes))

    def keys(self):
        keys = [o.key() for o in self.listed_candidates()] + [o.key() for o in self.looks()]
        return sorted(set(keys + [n.key() for n in self.notices]))


def reproduces(rows, recs):
    """(None, names_differ) when every recorded row is reproduced, else (problem, names_differ)."""
    by_id, names_differ = {r.id: r for r in rows}, False
    for rec in recs:
        row = by_id.get(rec.lb_id)
        if row is None:
            return f"{rec.lb_id} is not in the table", names_differ
        if row.overall is None:
            return f"{rec.lb_id}: {row.partial_label()}", names_differ
        recorded = {fold_category(k): v for k, v in rec.category_scores.items()}
        every = {fold_category(k): v for k, v in row.categories.items()}
        unscored = [k for k in recorded if k in every and every[k] is None]
        if unscored:            # a 2.0 suite the row has no score in (v1 rows with one have no overall)
            return f"{rec.lb_id}: {unscored[0]} has no score in the table, recorded {recorded[unscored[0]]:.6f}", names_differ
        computed = {k: v for k, v in every.items() if v is not None}
        if set(recorded) == set(computed):
            for k, v in recorded.items():
                if abs(computed[k] - v) > CATEGORY_TOL:
                    return f"{rec.lb_id}: {k} {computed[k]:.6f}, recorded {v:.6f}", names_differ
        else:
            names_differ = True
            a, b = sorted(recorded.values()), sorted(computed.values())
            if len(a) != len(b) or any(abs(x - y) > CATEGORY_TOL for x, y in zip(a, b)):
                return f"{rec.lb_id}: category scores differ (category names differ too)", names_differ
        if abs(row.overall - rec.overall) > OVERALL_TOL:
            return f"{rec.lb_id}: overall {row.overall:.6f}, recorded {rec.overall:.2f}", names_differ
    return None, names_differ


def partition_diff(categories, reference, markdown=False):
    """Category and task differences of `categories` against `reference` ({name: tasks}); names are folded."""
    q = md_code if markdown else (lambda s: str(s))
    new = {fold_category(k): (k, set(v)) for k, v in categories.items()}
    old = {fold_category(k): (k, set(v)) for k, v in reference.items()}
    where_new = {t: k for k, (_, ts) in new.items() for t in ts}
    where_old = {t: k for k, (_, ts) in old.items() for t in ts}
    parts = []
    added = [new[k][0] for k in new if k not in old]
    removed = [old[k][0] for k in old if k not in new]
    if added:
        parts.append("categories added " + ", ".join(q(x) for x in added))
    if removed:
        parts.append("categories removed " + ", ".join(q(x) for x in removed))
    tasks_added = sorted(t for t in where_new if t not in where_old)
    tasks_removed = sorted(t for t in where_old if t not in where_new)
    moved = sorted(t for t in where_new if t in where_old and where_new[t] != where_old[t])
    if tasks_added:
        parts.append("tasks added " + ", ".join(q(t) for t in tasks_added))
    if tasks_removed:
        parts.append("tasks removed " + ", ".join(q(t) for t in tasks_removed))
    if moved:
        parts.append("tasks moved " + ", ".join(f"{q(t)} ({q(old[where_old[t]][0])} → {q(new[where_new[t]][0])})" for t in moved))
    count = f"{len(categories)} categories / {sum(len(v) for v in categories.values())} tasks"
    return (count + ": " + "; ".join(parts)) if parts else count + ": the same partition"


# --- state marker ------------------------------------------------------------------------------
def encode_marker(state):
    keys = list(state.get("keys", []))
    while True:
        payload = base64.urlsafe_b64encode(compact({**state, "keys": keys}).encode("utf-8")).decode("ascii")
        marker = f"<!-- model-discovery-state v1 {payload} -->"
        if len(marker) <= MARKER_CAP or not keys:
            return marker
        keys = keys[:len(keys) * 3 // 4]   # over the cap: fewer keys only means more of them count as new


def decode_marker(body):
    """The previous state, or None when the marker is missing, corrupt or oversized (everything then counts as new)."""
    matches = MARKER_RE.findall(body or "")
    if not matches or len(matches[-1]) > MARKER_CAP:
        return None
    try:
        state = json.loads(base64.urlsafe_b64decode(matches[-1].encode("ascii")).decode("utf-8"))
    except (ValueError, UnicodeDecodeError, RecursionError):   # RecursionError: a deeply nested payload
        return None
    if not isinstance(state, dict) or not isinstance(state.get("keys"), list) or not all(isinstance(k, str) for k in state["keys"]):
        return None
    return state


def run_reference(env=None):
    env = os.environ if env is None else env
    run_id, server, repo = env.get("GITHUB_RUN_ID", ""), env.get("GITHUB_SERVER_URL", ""), env.get("GITHUB_REPOSITORY", "")
    if run_id.isdigit() and re.match(r"^https://[A-Za-z0-9.-]+$", server) and REPO_RE.match(repo):
        return f"[run {run_id}]({server}/{repo}/actions/runs/{run_id})"
    return "this run"


# --- rendering ---------------------------------------------------------------------------------
def hf_tree(repo, sha):
    return f"https://huggingface.co/{repo}/tree/{sha}"


def hf_revision(repo, sha):
    return f"https://huggingface.co/api/models/{repo}/revision/{sha}"


class Report:
    """Every Markdown output of a run. Upstream strings only ever pass through md_code()."""

    def __init__(self, d, previous_body=""):
        self.d, self.previous = d, decode_marker(previous_body)
        self.previous_keys = set(self.previous["keys"]) if self.previous else set()
        self.keys = d.keys() if d.complete else []
        self.new_keys = [k for k in self.keys if k not in self.previous_keys]

    def is_new(self, key):
        return key in self.new_keys

    # .. header ......................................................................................
    def header(self):
        d, ev, r = self.d, self.d.local.evidence, self.d.release
        cal_rows = sum(c["rows"] for c in d.calibration)
        cal_total = sum(1 for rec in ev.recommendations if rec.generation == "v1")
        ok, total = d.canary_score
        site, script = d.local.site, d.script
        code = (f"site code `{script['path']}` as reviewed on {site.reviewed_on}" if script["path"] == site.main_script
                else f"site code **changed**: `{script['path']}` served, `{site.main_script}` reviewed")
        gen = "v1" if r.generation == "v1" else f"LiveBench 2.0, id `{r.id}`"
        lines = [
            f"- Leaderboard: [livebench.ai]({SITE_URL}), main script [`{script['path']}`]({script['url']}) (sha256 "
            f"`{script['sha256']}`). livebench.ai serves no versioned history; the sha256 values identify the bytes read.",
            f"- Analysis release **{r.date}** ({gen}; {len(r.scored)} scored rows; catalog evidence records "
            f"{ev.latest_release}).",
            f"- Table [`{r.entry.table_path}`]({r.table_url}), sha256 `{r.table_sha256}`; categories "
            f"[`{r.entry.categories_path}`]({r.cats_url}), sha256 `{r.cats_sha256}`, {r.taxonomy()}.",
            f"- {r.averaging(site.reviewed_on)}.",
            f"- Checks: calibration {cal_rows}/{cal_total} recorded v1 rows reproduced, HF anchors "
            f"{len(d.anchors)}/{len(HF_ANCHORS)}, matcher canary {ok}/{total}; {code}; {self.registry_text()}.",
            f"- Selection: the {POOL_SIZE} highest-scoring entries of {r.date} that could be self-hosted open-weight "
            f"models (ties included; cutoff overall {fmt(d.cutoff)}).",
        ]
        if d.best:
            b = d.best
            lines.append(f"- Best catalogued model in {r.date}: `{b.catalog.id}` ({md_code(b.row.id)}) "
                         f"{fmt(b.row.overall)}, rank {b.row.rank}/{len(r.scored)}.")
        else:
            lines.append(f"- Best catalogued model in {r.date}: none listed in {r.date} among the walked rows.")
        lines += [f"- Note: {n}" for n in d.header_notes]
        lines += [f"- Warning: {w}" for w in d.header_warnings]
        return lines

    def registry_text(self):
        reg, r = self.d.registry, self.d.release
        if reg is None or reg.problem:
            return "LiveBench model registry not used (see the warning)"
        entries, open_, linked = reg.counts()
        held = reg.coverage[reg.order[0]] if reg.order else 0
        rows = len(r.scored) + len(r.partial)
        hidden = (f" (the site shows only those {held} rows, so its ranks can differ)" if held < rows else "")
        return (f"LiveBench model registry: {entries} entries holding {held} of the release's {rows} ids{hidden}, "
                f"{open_} open weight, {linked} with a Hugging Face link")

    def disclaimer(self):
        return "> " + DISCLAIMER.format(release=self.d.release.date)

    # .. candidates ...............................................................................
    def row_table(self, o):
        d, r = self.d, self.d.release
        cats = list(r.categories)
        delta = fmt(o.row.overall - d.best.row.overall) if d.best else "n/a"
        if d.best and not delta.startswith("-"):
            delta = "+" + delta
        head = ["Release", "Overall", "Rank", "Δ vs best catalogued"] + [md_code(c) for c in cats] + [
            "Tasks" if r.generation == "v1" else "Suites"]
        values = [r.date, fmt(o.row.overall), f"{o.row.rank}/{len(r.scored)}", delta]
        values += [fmt(o.row.categories[c]) for c in cats] + [o.row.missing_label() or "all present"]
        return ["| " + " | ".join(head) + " |", "|" + "---|" * len(head), "| " + " | ".join(values) + " |"]

    def row_citation(self, row):
        r = self.d.release
        return f"[`{r.entry.table_path}`]({r.table_url}) row {row.number} (line {row.line})"

    def match_text(self, o):
        m = o.match
        if m.tier == "linked":   # LiveBench's own registry names the repository: no name match, no uniqueness check
            text = (f"Match: LiveBench links this repository (its registry entry for {md_code(o.row.id)}), not "
                    f"matched by name; org {md_code(m.org)} is an allowlisted publisher org"
                    + (f" via prefix {md_code(o.prefix)}" if o.prefix else ""))
        elif m.tier == "alias":   # no name match and no uniqueness check ran: the owner's alias names the repository
            org = o.info.org if o.info else m.org
            text = (f"Match: set by the alias decision {md_code(o.decision['key'])}, not by name; model info places "
                    f"the repository in the publisher org {md_code(org)}")
        else:
            if m.stage == 2:
                how = f"after stripping `-{'-'.join(m.stripped)}`"
                if "turbo" in m.stripped:
                    how += ("; LiveBench scored a hosted serving variant (-turbo), not the source checkpoint")
            else:
                how = "exact" if m.tier == "exact" else "relaxed (" + ", ".join(f"+{md_code(x)}" for x in m.extras) + ")"
            text = f"Match: {how}"
            if o.prefix:
                text += f"; org {md_code(m.org)} via prefix {md_code(o.prefix)}, unique among {m.pool_size} repos"
        if o.repo and m.repo.casefold() != o.repo.casefold():
            text += f"; Hugging Face answers {md_code(m.repo)} as {md_code(o.repo)} (renamed)"
        if o.gate:
            ok, token, ratio = o.gate
            text += f"; size token {md_code(token)} vs {o.params.value / 1e9:.2f}B ({(ratio - 1) * 100:+.1f}%)"
        return text + "."

    def params_text(self, o):
        p = o.params
        if p.kind == "float":
            return f"Parameters: {p.value:,} from safetensors metadata ({', '.join(md_code(x) for x in p.dtypes)})."
        rng = f"{p.lower / 1e9:.2f}–{p.upper / 1e9:.2f} B"
        if p.value:
            return (f"Parameters: {p.value:,} from the repo name, consistent with the packed safetensors range {rng} "
                    f"(integer share {p.int_share * 100:.1f}%).")
        return (f"Parameters: not pinned; packed safetensors range {rng} (integer share {p.int_share * 100:.1f}%), "
                "both bounds in the same fit class.")

    def fit_text(self, o):
        f = o.fit
        if f.gib:
            sizes = " / ".join(f"{k} {f.gib[k]:.2f}" for k in PRECISION_BITS)
            return f"Fit (planning, weights only): {sizes} GiB → **{f.cls}**: {f.label}. {PLANNING_CAVEAT}"
        p = o.params
        return (f"Fit (planning, weights only): Q4_K_M {gib(p.lower, 4.8):.2f}–{gib(p.upper, 4.8):.2f} GiB over the "
                f"packed range → **{f.cls}**: {f.label}. {PLANNING_CAVEAT}")

    def open_weights_text(self, o):
        i = o.info
        lic_file = i.license_file()
        lic = (f"yes ([{lic_file}](https://huggingface.co/{i.id}/blob/{i.sha}/{lic_file}))" if lic_file else "no")
        return (f"Open weights: [HF API @ {i.sha[:12]}]({hf_revision(i.id, i.sha)}), public, gated: "
                f"{md_code(i.gated_label())}, license {md_code(i.license_text())} (metadata label; review the license "
                f"file), LICENSE file at this revision: {lic}, {i.weights()} safetensors files"
                + (f", created {i.created}" if i.created else "") + ".")

    def candidate(self, o):
        d, r, i = self.d, self.d.release, o.info
        new = " (new since last refresh)" if self.is_new(o.key()) else ""
        out = [f"#### {md_code(o.row.id)} → [{md_code(i.id)}]({hf_tree(i.id, i.sha)}){new}", ""]
        out += self.row_table(o) + [""]
        variants = "".join(f"; variant {md_code(v.row.id)} {fmt(v.row.overall)}" for v in o.variants)
        out += [f"- Leaderboard row: {self.row_citation(o.row)} on [livebench.ai]({SITE_URL}){variants}.",
                f"- {self.open_weights_text(o)}", f"- {self.match_text(o)}", f"- {self.params_text(o)}",
                f"- {self.fit_text(o)}", ""]
        reject = {"key": f"hf:{i.id}", "decision": "rejected", "reason": "TODO", "decided_on": d.today.isoformat(),
                  "release": r.date}
        # Only the suites with a score: a 2.0 row with a blank or n/a suite is scored from the others, and the evidence
        # parser takes numbers only.
        scores = {k: v for k, v in o.row.categories.items() if v is not None}
        unscored = [k for k, v in o.row.categories.items() if v is None]
        stanza = {"model_id": "TODO", "leaderboard_model_id": o.row.id, "release": r.date,
                  "overall": round(o.row.overall, 2), "category_scores": scores,
                  "source_table": r.table_url, "source_sha256": r.table_sha256, "meaning": d.local.evidence.meaning}
        stanza_note = ("Set `model_id` to its catalog/models.json id. livebench.ai serves no versioned history: "
                       "`source_sha256` identifies the bytes read.")
        if unscored:
            stanza_note += (" `category_scores` leaves out " + ", ".join(md_code(k) for k in unscored)
                            + ": the row has no score there, and the overall averages the suites it has.")
        if r.generation == "2.0":
            stanza_note += (" A 2.0 table grows as LiveBench adds rows, so every run re-checks a recorded 2.0 row "
                            "softly: other bytes are a step-summary warning, never a failure.")
        out += ["<details><summary>Decision snippets</summary>", "",
                "Reject: append to `decisions` in catalog/model-discovery.json. Pasting it unedited fails CI until "
                "the reason is real.", "", "```json", snippet(reject), "```", "",
                "Or add it to catalog/models.json after reviewing its license file, a real artifact, engine "
                "architecture support and measured fit; its `upstream_metadata`:", "",
                "```json", json.dumps(i.metadata(), indent=2, ensure_ascii=True), "```", "",
                "and a catalog/livebench-evidence.json recommendation:", "",
                "```json", json.dumps(stanza, indent=2, ensure_ascii=True), "```", "", stanza_note, "",
                "</details>", ""]
        return out

    # .. needs a look ........................................................................
    def look_snippet(self, o):
        d, r = self.d, self.d.release
        base = {"reason": "TODO", "decided_on": d.today.isoformat(), "release": r.date}
        if o.reason in ("ambiguous", "alias_target_unavailable"):
            return {"key": f"lb:{o.row.id}", "decision": "alias", "target": "TODO", **base}, \
                "Replace the target with the reviewed repository" + (
                    " (replace the existing alias entry)." if o.reason == "alias_target_unavailable" else ".")
        if o.reason == "linked_outside_publisher":
            return {"key": f"hf:{o.repo}", "decision": "rejected", **base}, (
                "Or, when the linked org is the model's official publisher, add a publisher entry for it to "
                "catalog/model-discovery.json (the repository is then verified as a candidate).")
        if o.reason in ("no_repo", "unknown_publisher"):
            note = "Or add a publisher entry (prefix and official Hugging Face org) to catalog/model-discovery.json."
            if o.reason == "no_repo":
                note = ("Or record an `alias` naming the reviewed repository, or add a publisher entry for its "
                        "official Hugging Face org.")
            return {"key": f"lb:{o.row.id}", "decision": "not_open_weight", **base}, note
        key = o.decision["key"] if o.reason == "deferral_expired" else (f"hf:{o.repo}" if o.repo else f"lb:{o.row.id}")
        note = "Or record `\"decision\": \"deferred\"` with an `until` date (at most 365 days after decided_on)."
        if o.reason == "deferral_expired":
            note += " Replace the expired entry."
        return {"key": key, "decision": "rejected", **base}, note

    def look_found(self, o):
        if o.reason == "ambiguous":
            shown = ", ".join(f"{md_code(m.repo)}" + (f" (+{' +'.join(m.extras)})" if m.extras else "") for m in o.found)
            more = f" and {o.found_total - len(o.found)} more" if o.found_total > len(o.found) else ""
            return f" Candidates: {shown}{more}."
        if o.reason == "no_repo" and o.publisher:
            return f" Orgs {', '.join(md_code(x) for x in o.publisher.orgs)} list {o.pool_size} repos."
        if o.reason in ("info_unreadable", "alias_target_unavailable") and o.status:
            return f" {md_code(o.repo)} answered HTTP {o.status}."
        if o.reason == "deferral_expired":
            return f" {md_code(o.decision['key'])} was deferred until {o.decision['until']}: {md_code(o.decision['reason'])}."
        if o.reason == "weights_may_be_public":
            what = (f"{md_code(o.decision['key'])} recorded not_open_weight" if o.decision
                    else "LiveBench's registry lists it without `openweight`")
            return f" {what}; strict match {md_code(o.repo)} ({o.underlying})."
        if o.reason == "linked_outside_publisher":
            orgs = (f"the publisher's orgs are {', '.join(md_code(x) for x in o.publisher.orgs)}" if o.publisher
                    else "no publisher entry matches this id")
            return f" LiveBench links {md_code(o.repo)}; {orgs}."
        if o.reason == "size_mismatch" and o.params:
            p = o.params
            if p.kind == "float" and o.gate:
                return f" Size token {md_code(o.gate[1])} vs {p.value / 1e9:.2f}B verified."
            if p.kind == "packed":
                return f" Name size {md_code(p.name_token)} is outside the packed range {p.lower / 1e9:.2f}–{p.upper / 1e9:.2f} B."
        if o.reason == "size_unverified" and o.params and o.params.kind == "packed":
            p = o.params
            return f" Packed range {p.lower / 1e9:.2f}–{p.upper / 1e9:.2f} B spans two fit classes."
        if o.repo and o.reason != "unknown_publisher":
            return f" Repository {md_code(o.repo)}."
        return ""

    def look(self, o, details=True):
        r = self.d.release
        new = " (new since last refresh)" if self.is_new(o.key()) else ""
        out = [f"- {md_code(o.row.id)} {fmt(o.row.overall)}, rank {o.row.rank}/{len(r.scored)}: "
               f"**{o.reason}**: {LOOK_WORDS[o.reason]}.{self.look_found(o)}{new}"]
        if details:
            snip, note = self.look_snippet(o)
            out += ["", "  <details><summary>Decision snippet</summary>", "", "  ```json", "  " + snippet(snip),
                    "  ```", "", f"  {note}", "", "  </details>", ""]
        return out

    # .. not raised ....................................................................................
    def not_raised(self, cap):
        d = self.d
        def capped(title, items):
            if not items:
                return []
            shown = items[:cap]
            out = [f"**{title} ({len(items)})**", ""] + [f"- {x}" for x in shown]
            if len(items) > len(shown):
                out.append(f"- and {len(items) - len(shown)} more in the run artifact")
            return out + [""]
        known, decided, closed, large, unavailable = [], [], [], [], []
        for o in d.outcomes:
            if o.kind == "variant":
                continue
            variants = "".join(f"; variant {md_code(v.row.id)} {fmt(v.row.overall)}" for v in o.variants)
            name = f"{md_code(o.row.id)} {fmt(o.row.overall)}" + (f" → {md_code(o.repo)}" if o.repo else "")
            if o.kind == "known":
                if o.catalog:
                    via = {"catalog": "its upstream_repo", "evidence": "the evidence leaderboard id",
                           "alias_to_catalog": "an alias decision", "precision_sibling": "a precision sibling of its upstream_repo"}
                    what = (f"catalog `{o.catalog.id}` ({o.catalog.status}" + (f", {o.fit.cls}" if o.fit else "")
                            + f") via {via.get(o.reason, o.reason)}")
                else:
                    what = (("precision sibling of " if o.reason == "precision_sibling" else "")
                            + f"excluded example {md_code(o.example['model'])}, too large per the evidence")
                stripped = ""
                if o.match and o.match.stage == 2:
                    stripped = f"; matched after stripping `-{'-'.join(o.match.stripped)}`" + (
                        " (LiveBench scored a hosted serving variant, not the source checkpoint)"
                        if "turbo" in o.match.stripped else "")
                note = f"; {md_code(o.note, EXCERPT_CAP)}" if o.note else ""
                known.append(f"{name}: {what}{stripped}; " + ("in the pool" if o.counts else "not in the pool")
                             + note + variants)
            elif o.kind == "decided":
                note = f"; {md_code(o.note)}" if o.note else ""
                until = f" until {o.decision['until']}" if o.reason == "deferred" else ""
                decided.append(f"{name}: {o.reason}{until} ({md_code(o.decision['key'])}): {md_code(o.decision['reason'])}{note}{variants}")
            elif o.kind == "closed":
                note = f"; {md_code(o.note)}" if o.note else ""
                closed.append(f"{name}: LiveBench marks it closed (its registry entry has no `openweight`){note}")
            elif o.kind == "info" and o.reason == "too_large":
                g = o.fit.gib
                size = (f"Q4_K_M {g['Q4_K_M']:.2f} / IQ2_XS {g['IQ2_XS']:.2f} GiB" if g else "packed range too large")
                large.append(f"{name}: {size}: {o.fit.label}" + (f"; {md_code(o.note, EXCERPT_CAP)}" if o.note else ""))
            elif o.kind == "info":
                unavailable.append(f"{name}: {o.reason}")
        partial = [f"{md_code(r.id)}: {r.partial_label()}, partial mean {fmt(r.partial_mean)} (not an overall)"
                   for r in d.partial_listed]
        out = capped("Known", known) + capped("Decided", decided) + capped("LiveBench marks it closed", closed)
        out += capped("Open weights but too large", large)
        out += capped("No weights yet, private or disabled", unavailable) + capped("Partial rows", partial)
        out += [f"**Below the cutoff**: {d.below} rows.", ""]
        total = len(known) + len(decided) + len(closed) + len(large) + len(unavailable) + len(partial) + d.below
        return total, out

    # .. issue body .....................................................................................
    def notice_lines(self, n):
        new = " (new since last refresh)" if self.is_new(n.key()) else ""
        return [f"#### {n.title}{new}", ""] + [f"- {line}" for line in n.lines] + [f"- {n.clears}", ""]

    def issue(self, level=0):
        d, r = self.d, self.d.release
        caps = (LIST_CAP, 10, 3, 0, 0, 0)
        cap, look_details, look_rows = caps[level], level < 4, level < 5
        out = ["## LiveBench model discovery", ""] + self.header() + ["", self.disclaimer(), ""]
        if d.reportable:
            out += [f"### Notices ({len(d.notices)})", ""]
            for n in d.notices:
                out += self.notice_lines(n)
            candidates = d.listed_candidates()
            out += [f"### Candidates ({len(candidates)})", ""]
            for o in candidates:
                out += self.candidate(o)
            looks = d.looks()
            out += [f"### Needs a look ({len(looks)})", ""]
            if look_rows:
                for o in looks:
                    out += self.look(o, details=look_details)
            else:
                counts = collections.Counter(o.reason for o in looks)
                out += [f"- **{k}**: {v} rows" for k, v in sorted(counts.items())]
                out += ["", "Every row with its reason is in the run artifact (discovery.json)."]
            out.append("")
        else:
            out += [NOTHING_NEEDED.format(n=POOL_SIZE, release=r.date), ""]
        total, lines = self.not_raised(cap)
        out += [f"<details><summary>Not raised ({total})</summary>", ""] + lines + ["</details>", "",
                "How to record a decision: see `docs/MODEL_DISCOVERY.md`.", "",
                encode_marker({"release": r.date, "id": r.id, "script": d.script["path"],
                               "table_sha256": r.table_sha256, "keys": self.keys, "on": d.today.isoformat()}), ""]
        return "\n".join(out)

    def issue_body(self):
        body = ""
        for level in range(6):
            body = self.issue(level)
            if len(body) <= ISSUE_BODY_CAP:
                return body
        return body

    def comment(self):
        d, r = self.d, self.d.release
        if not d.reportable:
            gen = "v1" if r.generation == "v1" else "2.0"
            return (f"No unreviewed model among the {POOL_SIZE} best entries of LiveBench release {r.date} "
                    f"({gen}, livebench.ai table sha256 `{r.table_sha256[:12]}`) that could be self-hosted needs a "
                    f"decision, and no notice is open ({run_reference()}); closing.\n")
        if not self.new_keys:
            return None
        lines = ["New since the last refresh:", ""]
        for o in d.listed_candidates():
            if self.is_new(o.key()):
                lines.append(f"- candidate {md_code(o.row.id)} → {md_code(o.repo)} ({fmt(o.row.overall)}, rank {o.row.rank}/{len(r.scored)})")
        for o in d.looks():
            if self.is_new(o.key()):
                lines.append(f"- needs a look: {md_code(o.row.id)} ({o.reason})")
        for n in d.notices:
            if self.is_new(n.key()):
                lines.append(f"- notice: {n.title}")
        return "\n".join(lines) + "\n"

    # .. step summary ......................................................................................
    def step_summary(self, error=None):
        d = self.d
        out = ["## LiveBench model discovery: step summary", ""]
        if error is not None:
            out += [failure_line(error, d.stage), ""]
        if d.complete:
            out += self.header() + [""]
        if d.script:
            out += ["### Leaderboard site", "",
                    f"- Main script `{d.script['path']}` ({d.script['bytes']} bytes, sha256 `{d.script['sha256']}`); "
                    f"reviewed `{d.local.site.main_script}` on {d.local.site.reviewed_on}.",
                    "- Timeline: v1 " + (", ".join(r.id for r in d.timeline if r.generation == "v1") or "none")
                    + "; 2.0 " + (", ".join(r.id for r in d.timeline if r.generation == "2.0") or "none") + "."]
            if d.registry is not None:
                if d.registry.problem:
                    out.append(f"- Model registry not used: {md_code(d.registry.problem, EXCERPT_CAP)}.")
                else:
                    sizes = ", ".join(f"{len(t)} entries" + (f" ({d.registry.coverage[k]} of this release's ids)"
                                                             if d.registry.coverage else "")
                                      for k, t in enumerate(d.registry.tables))
                    out.append(f"- Model registries: {sizes}.")
            out.append("")
        if d.calibration or d.taxonomy:
            out += ["### Calibration", "", f"- Tolerances: category {CATEGORY_TOL:g}, overall {OVERALL_TOL:.9f}."]
            for c in d.calibration:
                out.append(f"- [`{c['table']}`]({c['url']}): sha256 `{c['sha256']}` as recorded; categories file "
                           f"`{c['categories']}`" + (" (fallback)" if c["fallback"] else "")
                           + (", category names differ" if c["names_differ"] else "")
                           + f"; {c['rows']} recorded rows reproduced.")
            for c in d.soft_calibration:
                out.append(f"- `{c['table']}` (2.0, soft): {c['rows']} recorded rows, {c['status']}.")
            if d.taxonomy:
                out.append(f"- Taxonomy: [`{d.taxonomy['file']}`]({d.taxonomy['url']}) has the partition of "
                           f"catalog/benchmarks.json ({d.taxonomy['sets']} sets, {d.taxonomy['tasks']} tasks).")
            for x in d.excluded_check or []:
                out.append(f"- Excluded example {md_code(x['model'])} {x['score']:.2f}: "
                           + (f"row {md_code(x['found'])}" if x["found"] else "not found (soft check)") + ".")
            out.append("")
        if d.anchors:
            out += ["### Hugging Face anchors", ""] + [
                f"- `{a['catalog_id']}` {md_code(a['repo'])} @ `{a['sha'][:12]}`: id, sha, safetensors total, dtypes and "
                "float counts as recorded" + ("; integer counts differ: " + ", ".join(
                    f"{c['dtype']} {c['reported']} (recorded {c['recorded']})" for c in a["int_changes"])
                    if a["int_changes"] else "") + f"; {a['class']}"
                + (f"; {md_code(a['note'])}" if a["note"] else "") for a in d.anchors] + [""]
        if d.canary_results:
            out += ["### Matcher canary", ""] + [
                f"- {md_code(c['id'])} → {md_code(c['result'])}" + (" (LiveBench's registry link)" if c["tier"] == "linked" else "")
                + (" (name-equal)" if c["name_equal"] else " (not name-equal; a miss is expected)")
                for c in d.canary_results] + [""]
        if d.warnings or d.header_warnings:
            out += ["### Warnings", ""] + [f"- {w}" for w in d.header_warnings + d.warnings] + [""]
        if d.outcomes:
            out += [f"### Walked rows ({len(d.outcomes)})", "", "| Rank | Id | Overall | Outcome | Repo | Detail |", "|---|---|---|---|---|---|"]
            for o in d.outcomes:
                detail = o.note or o.underlying or (f"variant of {o.variant_of.row.id}" if o.variant_of else "")
                out.append(f"| {o.row.rank} | {md_code(o.row.id)} | {fmt(o.row.overall)} | {o.label()} | "
                           f"{md_code(o.repo) if o.repo else ''} | {md_code(detail) if detail else ''} |")
            out += ["", f"Below the cutoff: {d.below} rows. Partial rows listed: {len(d.partial_listed)}.", ""]
        if d.release and d.release.extras:
            out += ["Table columns ignored: " + ", ".join(md_code(x) for x in d.release.extras[:40]), ""]
        counts = getattr(d.net, "counts", {})
        out += ["### Limits and requests", "",
                "- Requests: " + (", ".join(f"{h} {n}" for h, n in sorted(counts.items())) or "none") + ".",
                f"- Model-info lookups {d.info_calls} of {MAX_MODEL_INFO}; listing pages {d.listing_pages} of {MAX_LISTING_PAGES_RUN}.",
                "- Limits hit: " + (", ".join(d.limits_hit) or "none") + ".", ""]
        return "\n".join(out)


def failure_line(error, stage):
    stage = getattr(error, "stage", None) or stage
    if isinstance(error, ShapeError):
        return (f"Upstream shape changed at {md_code(stage)}: expected {md_code(error.expected, EXCERPT_CAP)}; "
                f"got {md_code(error.got or 'n/a', EXCERPT_CAP)}" + (f". What to do: {error.fix}" if error.fix else ""))
    if isinstance(error, ConfigError):
        return f"Invalid local input at {md_code(stage)}: {md_code(error, EXCERPT_CAP)}"
    if isinstance(error, NetworkError):
        return f"Network failure at {md_code(stage)}: {md_code(error, EXCERPT_CAP)}"
    return f"Unexpected internal error at {md_code(stage)}: {type(error).__name__}"


def failure_body(error, stage, previous_body, today):
    state = decode_marker(previous_body)
    since = state.get("on") if state and isinstance(state.get("on"), str) and DATE_RE.match(state["on"]) else None
    stage = getattr(error, "stage", None) or stage
    if isinstance(error, ShapeError):
        expected, got = error.expected, error.got or "n/a"
    elif isinstance(error, (ConfigError, NetworkError)):
        expected, got = type(error).__name__, str(error)
    else:
        expected, got = "no internal error", type(error).__name__
    lines = ["### Problems reading sources", "",
             f"- Stage: {md_code(stage)}",
             f"- Expected: {md_code(expected, EXCERPT_CAP)}",
             f"- Got: {md_code(got, EXCERPT_CAP)}"]
    if isinstance(error, ShapeError) and error.fix:      # our own text, never upstream content
        lines.append(f"- What to do: {error.fix}")
    lines += [f"- Run: {run_reference()} on {today.isoformat()}",
              "- Nothing below was refreshed since " + (since or "the last good run (date unknown)") + ".",
              "", "<!-- model-discovery-failure-end -->", ""]
    rest = FAILURE_BLOCK_RE.sub("", previous_body or "").strip("\n")
    return "\n".join(lines) + ("\n" + rest + "\n" if rest else "")


def to_json(d, report, error=None):
    def outcome(o):
        x = {"rank": o.row.rank, "id": o.row.id, "overall": o.row.overall, "line": o.row.line, "row": o.row.number,
             "outcome": o.kind,
             "reason": o.reason, "repo": o.repo, "counts": o.counts, "catalog_id": o.catalog.id if o.catalog else None,
             "categories": o.row.categories, "missing_tasks": o.row.missing_tasks, "note": o.note or o.underlying or None,
             "variant_of": o.variant_of.row.id if o.variant_of else None,
             "decision": o.decision["key"] if o.decision else None}
        if o.match:
            x["match"] = {"tier": o.match.tier, "extras": o.match.extras, "stage": o.match.stage,
                          "stripped": o.match.stripped, "org": o.match.org}
        if o.found:
            x["candidates"] = [m.repo for m in o.found]
        if o.hint:
            x["registry"] = {"openweight": o.hint.openweight, "link": o.hint.link, "variant_of": o.hint.variant_of}
        if o.info:
            x["hf"] = {"id": o.info.id, "sha": o.info.sha, "gated": o.info.gated, "license": o.info.licenses(),
                       "safetensors_files": o.info.weights()}
        if o.params:
            x["parameters"] = dataclasses.asdict(o.params)
        if o.fit:
            x["fit"] = {"class": o.fit.cls, "gib": o.fit.gib}
        return x
    r = d.release
    return {
        "complete": d.complete, "reportable": d.complete and d.reportable, "new": bool(report and report.new_keys),
        "today": d.today.isoformat(), "stage": d.stage,
        "error": None if error is None else {"type": type(error).__name__, "stage": getattr(error, "stage", None) or d.stage,
                                             "message": str(error) if isinstance(error, DiscoveryError) else None},
        "sources": {"site": SITE_URL, "main_script": d.script,
                    "reviewed_script": dataclasses.asdict(d.local.site) if d.local else None,
                    "timeline": [dataclasses.asdict(t) for t in d.timeline], "suite_order": d.suite_order,
                    "registry": None if d.registry is None else {
                        "problem": d.registry.problem, "entries": [len(t) for t in d.registry.tables],
                        "coverage": d.registry.coverage, "order": d.registry.order}},
        "release": None if r is None else {"id": r.id, "date": r.date, "generation": r.generation,
                                           "table": r.table_url, "table_sha256": r.table_sha256,
                                           "categories_file": r.cats_url, "categories_sha256": r.cats_sha256,
                                           "categories": r.categories, "weights": r.weights,
                                           "ignored_weights": r.ignored_weights,
                                           "scored_rows": len(r.scored), "extra_columns": r.extras},
        "calibration": d.calibration, "soft_calibration": d.soft_calibration, "taxonomy": d.taxonomy,
        "excluded_examples": d.excluded_check, "anchors": d.anchors, "canary": d.canary_results,
        "warnings": d.header_warnings + d.warnings, "header_notes": d.header_notes,
        "notices": [{"kind": n.kind, "detail": n.detail, "title": n.title} for n in d.notices],
        "cutoff": d.cutoff, "below_cutoff": d.below,
        "rows": [outcome(o) for o in d.outcomes],
        "partial": [{"id": p.id, "partial_mean": p.partial_mean, "available": p.available, "of": len(p.categories)}
                    for p in d.partial_listed],
        "keys": report.keys if report else [], "new_keys": report.new_keys if report else [],
        "requests": dict(getattr(d.net, "counts", {})), "model_info_lookups": d.info_calls,
        "listing_pages": d.listing_pages, "limits_hit": d.limits_hit,
    }


def plain_report(d):
    r = d.release
    lines = [f"LiveBench model discovery: livebench.ai release {r.date} ({r.generation}, {len(r.scored)} scored rows), "
             f"cutoff {fmt(d.cutoff)}"]
    lines += [f"note: {plain(n, 300)}" for n in d.header_notes]
    lines += [f"warning: {plain(w, 300)}" for w in d.header_warnings + d.warnings]
    lines += [f"NOTICE {n.kind}: {plain(n.title)}" for n in d.notices]
    for o in d.outcomes:
        lines.append(f"{o.row.rank:>4} {plain(o.row.id, 48):48} {fmt(o.row.overall):>6}  {o.label():34} {plain(o.repo or '')}")
    lines.append(f"below the cutoff: {d.below}; reportable: {'yes' if d.reportable else 'no'}")
    return "\n".join(lines)


# --- probe (first-deploy validation; enforces nothing) ------------------------------------------
def probe(net, root, today, lines):
    """A digest of what livebench.ai and Hugging Face serve, in the shapes the run relies on. It reports and never
    enforces: only a network failure (exit 1) ends it early."""
    local = load_local(root, today)
    ev = local.evidence
    site = Site(net)

    def part(title, fn):
        try:
            fn()
        except HttpStatus as exc:
            lines.append(f"- {title}: HTTP {exc.code}")
        except NetworkError:
            raise
        except Exception as exc:  # noqa: BLE001 - the probe reports, it never enforces
            detail = f": {md_code(str(exc), 300)}" if isinstance(exc, DiscoveryError) else ""
            lines.append(f"- {title}: unreadable ({type(exc).__name__}){detail}")

    def describe(reply):
        return (f"HTTP {reply.status}, content-type {md_code(reply.headers.get('content-type'))}, "
                f"{len(reply.body)} bytes, sha256 `{hashlib.sha256(reply.body).hexdigest()}`")

    state = {}

    def page():
        reply = net.get(SITE_URL)
        srcs = SCRIPT_SRC_RE.findall(reply.body.decode("utf-8", errors="replace"))
        lines.append(f"- page {SITE_URL}: {describe(reply)}; script src {md_code(', '.join(srcs) or 'none', 600)}")

    def manifest():
        reply = net.get(SITE_URL + "asset-manifest.json")
        doc = reply.json()
        files = doc.get("files") if isinstance(doc, dict) else None
        main = files.get("main.js") if isinstance(files, dict) else None
        lines.append(f"- asset-manifest.json: {describe(reply)}; files[\"main.js\"] {md_code(main)}")

    def script():
        path, text = site.main_script()
        state["text"] = text
        body = site.get(path, "js").body
        literal = f'"{WEIGHTS_KEY}"'
        order = parse_suite_order(text)
        lines.append(f"- main script `{path}` (agrees with index.html): {len(body)} bytes, sha256 "
                     f"`{hashlib.sha256(body).hexdigest()}`; reviewed script `{local.site.main_script}` "
                     f"({'the same' if path == local.site.main_script else 'DIFFERENT'}); "
                     f"`{literal}` literal {'present' if literal in text else 'ABSENT'}; suite order "
                     + (md_code(", ".join(order), 400) + (" (as reviewed)" if tuple(order) == REVIEWED_SUITE_ORDER else
                                                          " (DIFFERS from the reviewed order)") if order else "NOT FOUND"))

    def releases():
        timeline = parse_release_lists(state.get("text", ""))
        state["timeline"] = timeline
        for gen in GENERATIONS:
            ids = [r.id for r in timeline if r.generation == gen]
            lines.append(f"- {gen} release list: {len(ids)} releases: {md_code(', '.join(ids), 1000)}")

    def registry():
        reg = parse_registries(state.get("text", ""))
        if reg.problem:
            lines.append(f"- model registry: not usable: {md_code(reg.problem, 300)}")
            return
        for k, table in enumerate(reg.tables):
            entries = [e for e in table.values() if e.variant_of is None]
            lines.append(f"- model registry {k + 1}: {len(entries)} entries (+{len(table) - len(entries)} variants), "
                         f"{sum(e.openweight for e in entries)} with openweight, "
                         f"{sum(bool(e.openweight and e.link) for e in entries)} of them with a huggingface link, "
                         f"{sum(bool(e.link_raw) for e in entries)} links that are not a repository URL")

    def calibration_tables():
        for path in sorted({r.site_path for r in ev.recommendations}):
            recorded = next(r.sha256 for r in ev.recommendations if r.site_path == path)
            try:
                reply = net.get(SITE_URL + path, cap=MAX_TABLE_BYTES)
            except HttpStatus as exc:
                lines.append(f"- {path}: HTTP {exc.code}")
                continue
            same = hashlib.sha256(reply.body).hexdigest() == recorded
            lines.append(f"- {path}: {describe(reply)}; "
                         + ("equal to the recorded source_sha256" if same else f"DIFFERS from the recorded source_sha256 `{recorded}`"))

    def newest_v2():
        v2 = [r for r in state.get("timeline", []) if r.generation == "2.0"]
        if not v2:
            lines.append("- newest 2.0 release: none on the timeline")
            return
        entry = v2[-1]
        reply = net.get(SITE_URL + entry.table_path, cap=MAX_TABLE_BYTES)
        text = reply.body.decode("utf-8", errors="replace").lstrip("﻿")
        rows = [r for r in csv.reader(io.StringIO(text, newline="")) if r]
        lines.append(f"- newest 2.0 release {entry.id}: `{entry.table_path}` {describe(reply)}; header "
                     f"{md_code(','.join(rows[0]) if rows else '', 600)}; {max(len(rows) - 1, 0)} rows")
        reply = net.get(SITE_URL + entry.categories_path, cap=MAX_TABLE_BYTES)
        doc = reply.json()
        keys = ", ".join(f"{k} ({len(v) if isinstance(v, (list, dict)) else type(v).__name__})" for k, v in doc.items()) \
            if isinstance(doc, dict) else type(doc).__name__
        weights = doc.get(WEIGHTS_KEY) if isinstance(doc, dict) else None
        lines.append(f"- `{entry.categories_path}`: {describe(reply)}; keys {md_code(keys, 600)}; "
                     f"{WEIGHTS_KEY} {md_code(compact(weights) if weights is not None else 'absent', 400)}")

    def unknown():
        for path in ("no-such-page", "v1/table_1999_01_01.csv"):
            try:
                reply = net.get(SITE_URL + path)
            except HttpStatus as exc:
                lines.append(f"- unknown /{path}: HTTP {exc.code}")
                continue
            lines.append(f"- unknown /{path}: {describe(reply)} (a page where 404 was expected)")

    def listing(org):
        def go():
            reply = net.get(f"https://{HF_HOST}/api/models?author={org}&limit={LISTING_LIMIT}")
            doc = reply.json()
            first = sorted(doc[0]) if isinstance(doc, list) and doc and isinstance(doc[0], dict) else []
            lines.append(f"- listing {org}: {len(doc) if isinstance(doc, list) else type(doc).__name__} entries, "
                         f"Link next {'present' if next_link(reply.headers.get('link')) else 'absent'}, first entry keys {md_code(', '.join(first), 400)}")
        return go

    def info():
        model = local.by_id[HF_ANCHORS[0]]
        doc = net.get(f"https://{HF_HOST}/api/models/{model.repo}").json()
        lines.append(f"- model info {md_code(model.repo)}: keys {md_code(', '.join(sorted(doc)), 600)}; safetensors "
                     f"{'present' if 'safetensors' in doc else 'absent'}")

    def anchor():
        for cid in HF_ANCHORS[1:3]:
            model = local.by_id[cid]
            meta = model.metadata
            doc = net.get(f"https://{HF_HOST}/api/models/{model.repo}/revision/{meta['sha']}").json()
            st = doc.get("safetensors") if isinstance(doc.get("safetensors"), dict) else {}
            params = st.get("parameters") if isinstance(st.get("parameters"), dict) else {}
            diff = {k: [params.get(k), v] for k, v in meta["safetensors"]["parameters"].items() if params.get(k) != v}
            same = {"sha": doc.get("sha") == meta["sha"], "gated": doc.get("gated") == meta["gated"],
                    "total": st.get("total") == meta["safetensors"]["total"],
                    "dtypes": set(params) == set(meta["safetensors"]["parameters"])}
            lines.append(f"- anchor {cid} revision: id {md_code(doc.get('id'))}, equal to the catalog: {md_code(compact(same))}; "
                         f"counts that differ (reported, recorded): {md_code(compact(diff) if diff else 'none', 400)}")

    for title, fn in (("site page", page), ("asset manifest", manifest), ("main script", script),
                      ("release lists", releases), ("model registry", registry),
                      ("calibration tables", calibration_tables), ("newest 2.0 release", newest_v2),
                      ("unknown paths", unknown), ("listing google", listing("google")),
                      ("listing deepseek-ai", listing("deepseek-ai")), ("model info", info), ("anchors", anchor)):
        part(title, fn)
    return 0


# --- CLI -----------------------------------------------------------------------------------------------
def write(path, text):
    pathlib.Path(path).write_text(text, encoding="utf-8", newline="\n")


def emit(text, stream=None):
    """Print without failing on a console whose encoding lacks a character (cp1252 on Windows)."""
    stream = stream or sys.stdout
    encoding = getattr(stream, "encoding", None) or "utf-8"
    stream.write(text.encode(encoding, errors="replace").decode(encoding, errors="replace") + "\n")
    stream.flush()


def main(argv=None, net=None, root=ROOT):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--issue-summary", metavar="FILE", help="issue body; written only on a complete run")
    ap.add_argument("--comment", metavar="FILE", help="'new since the last refresh' list, or the close comment")
    ap.add_argument("--previous-issue", metavar="FILE", help="the current issue body (its state marker drives new=)")
    ap.add_argument("--failure-summary", metavar="FILE", help="issue body with a failure block; written on failure")
    ap.add_argument("--step-summary", metavar="FILE", help="Markdown run summary; always written (appended)")
    ap.add_argument("--json", metavar="FILE", help="machine-readable results")
    ap.add_argument("--github-output", action="store_true", help="append complete=/reportable=/new= to $GITHUB_OUTPUT")
    ap.add_argument("--record", metavar="DIR", help="save raw responses and an index (never request headers)")
    ap.add_argument("--today", metavar="YYYY-MM-DD", help="date override (tests)")
    ap.add_argument("--release", metavar="ID", help="analyse this release instead of the newest one: v1 YYYY-MM-DD, "
                                                     "or 2.0 YYYYMMDD / YYYY-MM-DD (manual runs; writes complete=false "
                                                     "to $GITHUB_OUTPUT, so the tracking issue is never touched)")
    ap.add_argument("--probe", action="store_true", help="print upstream shapes; enforces nothing; never touches the issue")
    args = ap.parse_args(argv)
    if args.release is not None:
        args.release = args.release.strip()
        if not (V1_ID_RE.match(args.release) or V2_ID_RE.match(args.release)):
            ap.error("--release expects a v1 release YYYY-MM-DD or a 2.0 release YYYYMMDD (or its YYYY-MM-DD date)")
    try:
        today = dt.date.fromisoformat(args.today) if args.today else dt.datetime.now(dt.timezone.utc).date()
    except ValueError:
        ap.error("--today expects YYYY-MM-DD")
    previous_body = ""
    if args.previous_issue:
        try:
            previous_body = pathlib.Path(args.previous_issue).read_text(encoding="utf-8", errors="replace")
        except OSError:
            previous_body = ""
    net = net if net is not None else Net(record_dir=args.record)
    d, report, error, code = Discovery(net, root, today, release=args.release or None), None, None, 0
    probe_lines = []
    try:
        if args.probe:
            d.stage = "probe"
            code = probe(net, root, today, probe_lines)
        else:
            d.run()
            report = Report(d, previous_body)
            emit(plain_report(d))
            if args.issue_summary:
                write(args.issue_summary, report.issue_body())
            comment = report.comment()
            if args.comment and comment:
                write(args.comment, comment)
    except DiscoveryError as exc:
        error, code = exc, exc.exit_code
    except Exception as exc:  # noqa: BLE001 - exit 3 names the type only (messages can carry upstream text)
        error, code = exc, 3
        d.complete = False
        emit("".join(traceback.format_tb(exc.__traceback__)), sys.stderr)
    finally:
        if error is not None:
            d.complete = False
            emit(f"model discovery failed: {plain(failure_line(error, d.stage), 400)}", sys.stderr)
            if args.failure_summary:
                try:
                    body = failure_body(error, d.stage, previous_body, today)
                except Exception:  # noqa: BLE001 - the failure block must be written; drop the unreadable previous body
                    body = failure_body(error, d.stage, "", today)
                write(args.failure_summary, body)
        # A forced release is a look at another release: like the probe, it never refreshes or closes the issue (the
        # issue tracks the newest release, and its marker would make the next nightly re-announce every entry).
        complete = d.complete and error is None and not args.probe and not args.release
        reportable = complete and d.reportable
        new = bool(complete and report and report.new_keys)
        if args.step_summary:
            if args.probe:
                text = "## LiveBench model discovery: probe\n\n" + "\n".join(probe_lines) + "\n"
                if error is not None:
                    text += "\n" + failure_line(error, d.stage) + "\n"
            else:
                text = (report or Report(d)).step_summary(error) if d.local or error else ""
            with open(args.step_summary, "a", encoding="utf-8", newline="\n") as fh:
                fh.write(text + "\n")
        if args.probe:
            emit("\n".join(plain(x, 2000) for x in probe_lines))
        if args.json:
            write(args.json, json.dumps(to_json(d, report, error), indent=2, default=str) + "\n")
        if args.github_output and os.environ.get("GITHUB_OUTPUT"):
            with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8", newline="\n") as fh:
                fh.write(f"complete={str(complete).lower()}\nreportable={str(reportable).lower()}\nnew={str(new).lower()}\n")
    return code


if __name__ == "__main__":
    sys.exit(main())
