import csv
import json
import statistics
from collections import defaultdict
from pathlib import Path

from .common import digest, read_json, write_json


def quantile(values, q):
    values = sorted(values)
    if not values:
        return None
    position = (len(values) - 1) * q
    low = int(position)
    high = min(low + 1, len(values) - 1)
    return values[low] + (values[high] - values[low]) * (position - low)


def summarize(root, include_synthetic=False, group_by="task"):
    if group_by not in {"task", "category"}:
        raise ValueError("Group by task or category")
    groups = defaultdict(list)
    descriptions = {}
    for path in sorted(Path(root).rglob("metadata.json")):
        meta = read_json(path)
        if meta.get("synthetic") and not include_synthetic:
            continue
        requests = path.parent / "requests.jsonl"
        if not requests.exists():
            continue
        c = meta["config"]
        for line in requests.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            if row["warmup"]:
                continue
            # All run controls are retained except measurement repetition/count and output location.
            cohort = {k: v for k, v in c.items() if k not in {"repeats", "warmups", "save_outputs", "backend_pid", "artifact_root", "artifact_lock", "offload_dir", "endpoint", "api_key_env"}}
            category = row.get("category", meta.get("category", "smoke"))
            benchmark = row.get("benchmark", meta.get("benchmark", "local-smoke"))
            cohort.update(artifact=meta.get("artifact_sha256"), suite=meta["suite_sha256"],
                          task=row["task_id"] if group_by == "task" else category,
                          category=category, benchmark=benchmark, group_by=group_by, synthetic=meta["synthetic"],
                          paging=meta.get("memory_assessment", {}).get("paging_observed"),
                          hardware=meta.get("hardware_profile", {}).get("id"),
                          host_driver=[g.get("driver_version") for g in meta.get("host", {}).get("gpus", [])],
                          host_kernel=meta.get("host", {}).get("release"))
            key = digest(cohort)
            groups[key].append(row)
            descriptions[key] = {"cohort": key[:12], "model": c["model_id"], "platform": c["platform"],
                                 "os": c["os_id"], "lane": c.get("lane", "offload"),
                                 "task": row["task_id"] if group_by == "task" else "all",
                                 "category": category, "benchmark": benchmark,
                                 "context": c["context_tokens"], "synthetic": meta["synthetic"],
                                 "paging_observed": meta.get("memory_assessment", {}).get("paging_observed")}
    summaries = []
    for key, rows in groups.items():
        ok = [r for r in rows if r["status"] == "ok"]
        record = {**descriptions[key], "requests": len(rows), "errors": len(rows) - len(ok)}
        for metric in ("elapsed_s", "client_request_wall_s", "first_output_s", "first_visible_s",
                       "output_tokens_per_wall_second", "backend_decode_tps", "backend_prefill_tps"):
            values = [r[metric] for r in ok if r.get(metric) is not None]
            record[metric + "_median"] = statistics.median(values) if values else None
            record[metric + "_p95"] = quantile(values, .95)
            record[metric + "_n"] = len(values)
        checks = [r.get("quality_pass") is True and r["status"] == "ok" for r in rows
                  if r.get("quality_check_applicable", r.get("quality_pass") is not None)]
        record["smoke_check_pass_rate"] = sum(checks) / len(checks) if checks else None
        record["smoke_check_n"] = len(checks)
        summaries.append(record)
    return summaries


def safe_cell(value):
    if isinstance(value, str) and value[:1] in {"=", "+", "-", "@"}:
        return "'" + value
    return value


def write_report(root, output, include_synthetic=False):
    rows = summarize(root, include_synthetic)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    write_json(output / "summary.json", rows)
    with open(output / "summary.csv", "w", encoding="utf-8", newline="") as f:
        if rows:
            writer = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")
            writer.writeheader()
            writer.writerows({k: safe_cell(v) for k, v in r.items()} for r in rows)
    categories = summarize(root, include_synthetic, "category")
    write_json(output / "category-summary.json", categories)
    with open(output / "category-summary.csv", "w", encoding="utf-8", newline="") as f:
        if categories:
            writer = csv.DictWriter(f, fieldnames=list(categories[0]), lineterminator="\n")
            writer.writeheader()
            writer.writerows({k: safe_cell(v) for k, v in r.items()} for r in categories)
    return rows
