#!/usr/bin/env python3
"""Nightly check of catalog/installers.json against upstream, with optional bump.

  python3 scripts/upstream_pins.py                       report only
  python3 scripts/upstream_pins.py --apply               rewrite the catalog (and docs that spell a pin)
  python3 scripts/upstream_pins.py --summary FILE        write a Markdown summary (the PR / issue body)
  python3 scripts/upstream_pins.py --github-output       append changed=/manual= to $GITHUB_OUTPUT
  python3 scripts/upstream_pins.py --strict              exit 1 when any resolver failed

What moves automatically (policy "bump"):
  * every exact PyPI pin (harness_packages, archive_packages, the pip recipes'
    packages, model_download_package): newest release on PyPI whose
    requires-python still admits the harness floor (3.11);
  * torch for the pip recipes that pin it: newest PyPI release that the pinned
    CUDA wheel index also serves;
  * ollama and koboldcpp: newest GitHub release; asset URLs follow the pinned
    filenames, byte counts come from the release metadata, sha256 from the
    release's checksum file when it publishes one (ollama) or from hashing the
    asset (koboldcpp);
  * llama.cpp and ik_llama.cpp: the commit behind the newest GitHub release
    tag (not branch HEAD, which moves many times a day); a repository that
    publishes no releases (ik_llama.cpp today) is treated like a
    reviewed-commit pin and only has its HEAD drift reported;
  * LM Studio: newest version in the winget-pkgs manifest tree; the Windows
    installer sha256 and release date come from that manifest, the Linux
    AppImage keeps sha256 null (the vendor publishes none).

What is only reported (policy "report"): Strata and LiveBench, which are
pinned to a reviewed commit, not a release; HEAD drift lands in the PR body
or, when nothing else changed, in a tracking issue.

Network goes through one Net object so tests can run offline with a fake.
GITHUB_TOKEN, when set, authenticates api.github.com calls (CI rate limits).
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import pathlib
import re
import sys
import time
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
CATALOG = ROOT / "catalog" / "installers.json"
PYTHON_FLOOR = (3, 11)
PIN = re.compile(r"^([A-Za-z0-9_.-]+)==([A-Za-z0-9.+_-]+)$")
GITHUB_REPO = re.compile(r"^https://github\.com/([^/]+/[^/]+?)(?:\.git)?$")
# Reviewed-commit pins: report HEAD drift, never rewrite.
REPORT_ONLY_SOURCES = ("strata", "livebench")
# Files outside the catalog that spell the LM Studio app version.
LMSTUDIO_MENTIONS = ("docs/PLATFORMS.md", "docs/READINESS.md")


def vtuple(version: str):
    """Order versions like 1.122.1, 0.7.0.post4, 0.4.26+4, b7000, v0.35.1."""
    cleaned = version.lstrip("vVbB")
    parts = []
    for piece in re.split(r"[.+-]", cleaned):
        m = re.match(r"^(post|rc|a|b|dev)?(\d+)$", piece)
        if m:
            parts.append((1 if m.group(1) in (None, "post") else 0, int(m.group(2))))
        elif piece:
            parts.append((0, piece))
    return tuple(parts)


def newer(candidate: str, pinned: str) -> bool:
    return vtuple(candidate) > vtuple(pinned)


def admits_python(requires_python, floor=PYTHON_FLOOR) -> bool:
    """True unless a '>=X.Y' / '>X.Y' specifier excludes the harness floor."""
    if not requires_python:
        return True
    for spec in requires_python.split(","):
        spec = spec.strip()
        m = re.match(r"^(>=|>)\s*(\d+)\.(\d+)", spec)
        if not m:
            continue
        bound = (int(m.group(2)), int(m.group(3)))
        if (m.group(1) == ">=" and floor < bound) or (m.group(1) == ">" and floor <= bound):
            return False
    return True


class Net:
    """All upstream access. Replaced by a fake in tests."""

    def __init__(self, token=None):
        self.token = token or os.environ.get("GITHUB_TOKEN")

    def _open(self, url, accept=None):
        headers = {"User-Agent": "llm-eval upstream_pins"}
        if accept:
            headers["Accept"] = accept
        if self.token and url.startswith("https://api.github.com/"):
            headers["Authorization"] = f"Bearer {self.token}"
        req = urllib.request.Request(url, headers=headers)
        for attempt in range(5):
            try:
                return urllib.request.urlopen(req, timeout=120)
            except urllib.error.HTTPError as exc:
                if exc.code not in (429, 502, 503) or attempt == 4:
                    raise
                time.sleep(int(exc.headers.get("Retry-After") or 10 * (attempt + 1)))
        raise AssertionError("unreachable")

    def text(self, url: str) -> str:
        with self._open(url) as resp:
            return resp.read().decode("utf-8")

    def json(self, url: str):
        with self._open(url, accept="application/vnd.github+json") as resp:
            return json.loads(resp.read().decode("utf-8"))

    def sha256_of(self, url: str):
        """Stream a release asset; returns (hex digest, byte count)."""
        digest, size = hashlib.sha256(), 0
        with self._open(url) as resp:
            while True:
                chunk = resp.read(1 << 20)
                if not chunk:
                    break
                digest.update(chunk)
                size += len(chunk)
        return digest.hexdigest(), size

    # --- upstream views used by the resolvers -------------------------------
    def pypi(self, name: str):
        info = self.json(f"https://pypi.org/pypi/{name}/json")["info"]
        return info["version"], info.get("requires_python")

    def torch_index_has(self, index_url: str, version: str) -> bool:
        listing = self.text(index_url.rstrip("/") + "/torch/")
        return f"torch-{version}+" in listing or f"torch-{version}-" in listing

    def release(self, repo: str) -> dict:
        return self.json(f"https://api.github.com/repos/{repo}/releases/latest")

    def tag_commit(self, repo: str, tag: str) -> str:
        ref = self.json(f"https://api.github.com/repos/{repo}/git/ref/tags/{tag}")["object"]
        if ref["type"] == "tag":  # annotated tag: one more hop to the commit
            ref = self.json(f"https://api.github.com/repos/{repo}/git/tags/{ref['sha']}")["object"]
        return ref["sha"]

    def head_commit(self, repo: str) -> str:
        return self.json(f"https://api.github.com/repos/{repo}/commits/HEAD")["sha"]

    def winget_versions(self, path="manifests/e/ElementLabs/LMStudio"):
        entries = self.json(f"https://api.github.com/repos/microsoft/winget-pkgs/contents/{path}")
        return [e["name"] for e in entries if e["type"] == "dir"]

    def winget_installer_yaml(self, version: str) -> str:
        quoted = urllib.request.quote(version, safe="")
        return self.text("https://raw.githubusercontent.com/microsoft/winget-pkgs/master/"
                         f"manifests/e/ElementLabs/LMStudio/{quoted}/ElementLabs.LMStudio.installer.yaml")


def parse_winget_installer(yaml_text: str):
    """(sha256 of the x64 installer, ReleaseDate) from a winget installer manifest (no PyYAML)."""
    date = re.search(r"^ReleaseDate:\s*['\"]?(\d{4}-\d{2}-\d{2})", yaml_text, re.M)
    sha = None
    for block in re.split(r"^\s*-\s+(?=Architecture:)", yaml_text, flags=re.M)[1:]:
        m = re.search(r"InstallerSha256:\s*([0-9A-Fa-f]{64})", block)
        if re.match(r"Architecture:\s*x64", block) and m:
            sha = m.group(1).lower()
            break
    if sha is None:  # single-installer manifest without a per-architecture list
        m = re.search(r"InstallerSha256:\s*([0-9A-Fa-f]{64})", yaml_text)
        sha = m.group(1).lower() if m else None
    return sha, (date.group(1) if date else None)


def checksum_lines(text: str) -> dict:
    """filename -> sha256 from a `sha256sum`-style listing (paths may carry ./)."""
    out = {}
    for line in text.splitlines():
        m = re.match(r"^([0-9A-Fa-f]{64})\s+\*?(?:\./)?(\S+)$", line.strip())
        if m:
            out[m.group(2)] = m.group(1).lower()
    return out


class Row:
    def __init__(self, name, pinned, policy):
        self.name, self.pinned, self.policy = name, pinned, policy
        self.latest, self.status, self.detail = None, "pending", ""
        self.changed = False

    def done(self, latest, status, detail=""):
        self.latest, self.status, self.detail = latest, status, detail
        return self


def resolve_pip_pin(net: Net, pin: str, row: Row):
    name, pinned = PIN.match(pin).groups()
    latest, requires = net.pypi(name)
    if not newer(latest, pinned):
        row.done(latest, "current")
        return pin
    if not admits_python(requires):
        row.done(latest, "manual", f"requires-python `{requires}` drops the harness floor {PYTHON_FLOOR[0]}.{PYTHON_FLOOR[1]}")
        return pin
    row.done(latest, "bump")
    return f"{name}=={latest}"


def bump_pip_lists(net: Net, catalog: dict, rows: list):
    """Rewrite every exact PyPI pin in place; returns True when any moved."""
    moved = False

    def visit(container, key, label):
        nonlocal moved
        value = container[key]
        if isinstance(value, str):
            row = Row(label, value.split("==", 1)[1], "bump")
            rows.append(row)
            try:
                new = resolve_pip_pin(net, value, row)
            except Exception as exc:  # noqa: BLE001 - reported, never fatal
                row.done(None, "failed", str(exc))
                return
            if new != value:
                container[key] = new
                row.changed = moved = True
            return
        for index, pin in enumerate(value):
            row = Row(f"{label} {pin.split('==', 1)[0]}", pin.split("==", 1)[1], "bump")
            rows.append(row)
            try:
                new = resolve_pip_pin(net, pin, row)
            except Exception as exc:  # noqa: BLE001
                row.done(None, "failed", str(exc))
                continue
            if new != pin:
                value[index] = new
                row.changed = moved = True

    visit(catalog, "harness_packages", "harness")
    visit(catalog, "archive_packages", "archive")
    for platform, recipe in catalog["platforms"].items():
        if recipe.get("kind") == "pip":
            visit(recipe, "packages", platform)
    visit(catalog, "model_download_package", "model download")
    return moved


def bump_torch(net: Net, catalog: dict, rows: list) -> bool:
    moved = False
    for platform, recipe in catalog["platforms"].items():
        if "torch" not in recipe:
            continue
        row = Row(f"{platform} torch", recipe["torch"], "bump")
        rows.append(row)
        try:
            latest, requires = net.pypi("torch")
            if not newer(latest, recipe["torch"]):
                row.done(latest, "current")
                continue
            if not admits_python(requires):
                row.done(latest, "manual", f"requires-python `{requires}` drops the harness floor")
                continue
            if not net.torch_index_has(recipe["torch_index"], latest):
                row.done(latest, "manual", f"not yet served by `{recipe['torch_index']}`")
                continue
            recipe["torch"] = latest
            row.done(latest, "bump")
            row.changed = moved = True
        except Exception as exc:  # noqa: BLE001
            row.done(None, "failed", str(exc))
    return moved


def bump_release_assets(net: Net, platform: str, recipe: dict, rows: list, checksum_asset=None) -> bool:
    """ollama / koboldcpp: newest release, same asset filenames, fresh bytes and sha256."""
    repo = GITHUB_REPO.match(recipe["assets"]["linux"]["url"].split("/releases/")[0]).group(1)
    row = Row(platform, recipe["version"], "bump")
    rows.append(row)
    try:
        release = net.release(repo)
        tag = release["tag_name"]
        version = tag.lstrip("v")
        if not newer(version, recipe["version"]):
            row.done(version, "current")
            return False
        by_name = {a["name"]: a for a in release.get("assets", [])}
        missing = [a["filename"] for a in recipe["assets"].values() if a["filename"] not in by_name]
        if missing:
            row.done(version, "manual", f"release {tag} lacks {', '.join(missing)}")
            return False
        published = {}
        if checksum_asset and checksum_asset in by_name:
            published = checksum_lines(net.text(by_name[checksum_asset]["browser_download_url"]))
        for os_id, asset in recipe["assets"].items():
            meta = by_name[asset["filename"]]
            url = meta["browser_download_url"]
            if asset["filename"] in published:
                sha, size = published[asset["filename"]], meta["size"]
            else:
                sha, size = net.sha256_of(url)
                if size != meta["size"]:
                    raise ValueError(f"{asset['filename']}: downloaded {size} bytes, release metadata says {meta['size']}")
            asset.update(url=url, sha256=sha, bytes=size)
        recipe["version"] = version
        row.done(version, "bump")
        row.changed = True
        return True
    except Exception as exc:  # noqa: BLE001
        row.done(None, "failed", str(exc))
        return False


def bump_release_revision(net: Net, platform: str, recipe: dict, rows: list) -> bool:
    """llama.cpp / ik_llama.cpp: the commit behind the newest release tag."""
    repo = GITHUB_REPO.match(recipe["repository"]).group(1)
    row = Row(platform, recipe["revision"][:12], "bump")
    rows.append(row)
    try:
        try:
            tag = net.release(repo)["tag_name"]
        except urllib.error.HTTPError as exc:
            if exc.code != 404:
                raise
            # No GitHub release to follow: behave like a reviewed-commit pin and only report HEAD drift.
            head = net.head_commit(repo)
            row.policy = "report"
            if head == recipe["revision"]:
                row.done(head[:12], "current")
            else:
                row.done(head[:12], "manual", "no GitHub release to follow; reviewed-commit pin, re-review before moving it")
            return False
        commit = net.tag_commit(repo, tag)
        if commit == recipe["revision"]:
            row.done(f"{tag} ({commit[:12]})", "current")
            return False
        recipe["revision"] = commit
        row.done(f"{tag} ({commit[:12]})", "bump")
        row.changed = True
        return True
    except Exception as exc:  # noqa: BLE001
        row.done(None, "failed", str(exc))
        return False


def report_head_drift(net: Net, label: str, source: dict, rows: list):
    repo = GITHUB_REPO.match(source["repository"]).group(1)
    row = Row(label, source["revision"][:12], "report")
    rows.append(row)
    try:
        head = net.head_commit(repo)
        if head == source["revision"]:
            row.done(head[:12], "current")
        else:
            row.done(head[:12], "manual", "reviewed-commit pin; re-review before moving it")
    except Exception as exc:  # noqa: BLE001
        row.done(None, "failed", str(exc))


def lmstudio_urls(recipe: dict, version: str) -> dict:
    """The vendor spells 0.4.26+4 as 0.4.26-4 in paths and filenames."""
    old, new = recipe["version"].replace("+", "-"), version.replace("+", "-")
    out = {}
    for os_id, asset in recipe["assets"].items():
        out[os_id] = {"url": asset["url"].replace(old, new), "filename": asset["filename"].replace(old, new)}
    return out


def bump_lmstudio(net: Net, recipe: dict, rows: list) -> bool:
    row = Row("lmstudio", recipe["version"], "bump")
    rows.append(row)
    try:
        versions = [v for v in net.winget_versions() if re.match(r"^\d+\.\d+\.\d+(\+\d+)?$", v)]
        latest = max(versions, key=vtuple)
        if not newer(latest, recipe["version"]):
            row.done(latest, "current")
            return False
        sha, date = parse_winget_installer(net.winget_installer_yaml(latest))
        if not sha:
            row.done(latest, "manual", "winget manifest carries no x64 InstallerSha256")
            return False
        urls = lmstudio_urls(recipe, latest)
        for os_id, asset in recipe["assets"].items():
            asset.update(urls[os_id])
        recipe["assets"]["windows"]["sha256"] = sha
        recipe["assets"]["windows"]["sha256_source"] = ("https://github.com/microsoft/winget-pkgs/blob/master/manifests/e/"
                                                        f"ElementLabs/LMStudio/{urllib.request.quote(latest, safe='')}/ElementLabs.LMStudio.installer.yaml")
        recipe["version"] = latest
        if date:
            recipe["release_date"] = date
        row.done(latest, "bump")
        row.changed = True
        return True
    except Exception as exc:  # noqa: BLE001
        row.done(None, "failed", str(exc))
        return False


def rewrite_mentions(root: pathlib.Path, old: str, new: str, files=LMSTUDIO_MENTIONS) -> list:
    changed = []
    for rel in files:
        path = root / rel
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        if old in text:
            path.write_text(text.replace(old, new), encoding="utf-8")
            changed.append(rel)
    return changed


# Files whose mention of a pin is about the resolver itself, not the pinned software.
MENTION_SKIP = ("scripts/upstream_pins.py", "tests/test_upstream_pins.py")


def stale_mentions(root: pathlib.Path, old: str, skip=MENTION_SKIP) -> list:
    """Tracked text files that still spell `old` after a bump (docs, README, tests, scripts, source).

    A test that fakes `ollama --version` with a literal, or a doc that quotes a version,
    is exactly what makes a bump pull request fail or lie; name it in the PR body.
    """
    hits = []
    for pattern in ("README.md", "docs/*.md", "tests/*.py", "src/**/*.py", "scripts/**/*.py", "scripts/**/*.sh", "scripts/**/*.ps1"):
        for path in sorted(root.glob(pattern)):
            rel = path.relative_to(root).as_posix()
            if rel in skip:
                continue
            if old in path.read_text(encoding="utf-8", errors="replace"):
                hits.append(rel)
    return hits


def run(net: Net, root: pathlib.Path, apply: bool, today: str):
    catalog_path = root / "catalog" / "installers.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    before = json.dumps(catalog, indent=2)
    rows, touched = [], []
    old_lmstudio = catalog["platforms"]["lmstudio"]["version"]

    bump_pip_lists(net, catalog, rows)
    bump_torch(net, catalog, rows)
    platforms = catalog["platforms"]
    bump_release_assets(net, "ollama", platforms["ollama"], rows, checksum_asset="sha256sum.txt")
    bump_release_assets(net, "koboldcpp", platforms["koboldcpp"], rows)
    for name in ("llama.cpp", "ik_llama.cpp"):
        bump_release_revision(net, name, platforms[name], rows)
    bump_lmstudio(net, platforms["lmstudio"], rows)
    report_head_drift(net, "strata", platforms["strata"], rows)
    report_head_drift(net, "livebench", catalog["livebench"], rows)

    after = json.dumps(catalog, indent=2)
    changed = after != before
    stale = []
    if not apply:  # report mode: nothing was bumped, only found
        for row in rows:
            row.changed = False
    if changed:
        catalog["checked_on"] = today
        if apply:
            catalog_path.write_text(json.dumps(catalog, indent=2) + "\n", encoding="utf-8")
            touched.append("catalog/installers.json")
            new_lmstudio = catalog["platforms"]["lmstudio"]["version"]
            if new_lmstudio != old_lmstudio:
                touched += rewrite_mentions(root, old_lmstudio, new_lmstudio)
            # Every replaced pin (version or revision) that a doc, test or script still spells out.
            replaced = sorted({r.pinned for r in rows if r.changed and len(r.pinned) >= 5})
            stale = [(rel, old) for old in replaced for rel in stale_mentions(root, old)]
    manual = [r for r in rows if r.status == "manual"]
    failures = [r for r in rows if r.status == "failed"]
    return {"rows": rows, "changed": changed, "applied": apply and changed, "touched": touched,
            "manual": manual, "failures": failures, "stale": stale}


def markdown_summary(result: dict) -> str:
    lines = ["## Upstream pin check", "", "| Pin | Pinned | Upstream | Result |", "|---|---|---|---|"]
    for r in result["rows"]:
        verdict = {"current": "current", "bump": "bumped" if r.changed else "bump available",
                   "manual": f"manual: {r.detail}", "failed": f"resolver failed: {r.detail}"}[r.status]
        lines.append(f"| {r.name} | `{r.pinned}` | `{r.latest or '?'}` | {verdict} |")
    if result["touched"]:
        lines += ["", "### Files rewritten", ""] + [f"- `{f}`" for f in result["touched"]]
        lines += ["", "Recipe pins only: the target-laptop gate (`docs/WORKFLOWS.md`) still decides whether a bump is usable.",
                  "koboldcpp hashes are computed from the downloaded assets; ollama hashes come from the release's `sha256sum.txt`."]
    if result["manual"]:
        lines += ["", "### Needs a manual decision", ""] + [f"- **{r.name}**: pinned `{r.pinned}`, upstream `{r.latest}`: {r.detail}" for r in result["manual"]]
    if result["stale"]:
        lines += ["", "### Still spells a replaced pin (refresh by hand, or a test will keep asserting the old one)", ""]
        lines += [f"- `{rel}`: still names `{old}`" for rel, old in result["stale"]]
    if result["failures"]:
        lines += ["", "### Resolver failures", ""] + [f"- **{r.name}**: {r.detail}" for r in result["failures"]]
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="rewrite catalog/installers.json and docs when upstream moved")
    ap.add_argument("--summary", metavar="FILE", help="write a Markdown summary here")
    ap.add_argument("--github-output", action="store_true", help="append changed=/manual= to $GITHUB_OUTPUT")
    ap.add_argument("--strict", action="store_true", help="exit 1 if any resolver failed")
    args = ap.parse_args()
    result = run(Net(), ROOT, args.apply, dt.date.today().isoformat())
    for r in result["rows"]:
        verdict = "bumped" if r.changed else {"bump": "bump available"}.get(r.status, r.status)
        print(f"{r.name:28} {r.pinned:>16} -> {str(r.latest):<16} {verdict}" + (f"  ({r.detail})" if r.detail else ""),
              flush=True)  # keep the table ahead of the stderr verdict in CI logs
    if args.summary:
        pathlib.Path(args.summary).write_text(markdown_summary(result), encoding="utf-8")
    if args.github_output and os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as fh:
            fh.write(f"changed={'true' if result['applied'] else 'false'}\n")
            fh.write(f"manual={'true' if result['manual'] else 'false'}\n")
    if result["failures"]:
        print(f"{len(result['failures'])} resolver(s) failed", file=sys.stderr)
        return 1 if args.strict else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
