from __future__ import annotations

import datetime
import json
import os
from pathlib import Path
import re
import time
import uuid

from . import __version__
from .adapters import HTTPAdapter
from .artifacts import verify_artifact
from .common import digest, environment_kind, finite_number, read_json, write_json
from .local_adapter import LocalAdapter
from .telemetry import Sampler, host_snapshot


def validate_config(c, root, synthetic=False):
    if any(k.lower() in {"api_key", "token", "password", "secret"} for k in c):
        raise ValueError("Do not put credentials in run files; use api_key_env")
    engines = {p["id"]: p for p in read_json(root / "catalog/platforms.json")["platforms"]}
    models = {m["id"]: m for m in read_json(root / "catalog/models.json")["models"]}
    if c.get("platform") not in engines or c.get("model_id") not in models:
        raise ValueError("Unknown platform or model; add an evidence-backed catalog entry first")
    engine, model = engines[c["platform"]], models[c["model_id"]]
    profile_id = c.get("hardware_profile", "msi-raider-18-hx-ai")
    if not re.fullmatch(r"[a-z0-9-]+", profile_id):
        raise ValueError("Invalid hardware profile identifier")
    hardware = read_json(root / ("configs/hardware/" + profile_id + ".json"))
    from .core.hardware import limits
    bounds = limits(c, root)
    max_gpu, max_ram = bounds["gpu_budget_gib"], bounds["ram_budget_gib"]
    if c.get("os_id") not in engine["os_support"]:
        raise ValueError("Unknown OS profile")
    if c.get("protocol") != engine["protocol"]:
        raise ValueError("Adapter protocol does not match catalog platform")
    for key, low, high in (("context_tokens", 512, 1048576), ("max_output_tokens", 1, 8192),
                           ("repeats", 1, 100), ("warmups", 0, 20), ("timeout_s", 1, 3600),
                           ("temperature", 0, 2), ("seed", 0, 2**31 - 1),
                           ("ram_budget_gib", 1, max_ram), ("gpu_budget_gib", 1, max_gpu)):
        finite_number(c[key], key, low, high)
    for key in ("context_tokens", "max_output_tokens", "repeats", "warmups", "seed"):
        if not isinstance(c[key], int):
            raise ValueError(f"{key} must be an integer")
    if c["context_tokens"] > model["max_context_for_initial_plan"]:
        raise ValueError("Context exceeds this catalog's initial validation limit")
    if c["max_output_tokens"] >= c["context_tokens"]:
        raise ValueError("Output budget leaves no room for the prompt")
    if c.get("concurrency", 1) != 1:
        raise ValueError("Initial harness measures one active request; concurrency requires a separate experiment")
    if c.get("lane", "offload") not in {"offload", "control", "disk"}:
        raise ValueError("Invalid evaluation lane")
    finite_number(c.get("telemetry_interval_s", 1.0), "telemetry_interval_s", .25, 30)
    finite_number(c.get("load_timeout_s", 600), "load_timeout_s", 1, 3600)
    threads=c.get('launch',{}).get('threads', min(16, bounds['threads']))
    if not isinstance(threads,int) or not 1<=threads<=bounds['threads']:
        raise ValueError('launch.threads exceeds hardware profile capacity')
    if c.get("allow_disk_offload", False) and c.get("lane") != "disk":
        raise ValueError("Disk-offload experiments require the disk lane")
    if not synthetic:
        for key in ("backend_version", "tokenizer_revision", "chat_template_sha256", "placement_notes"):
            if not c.get(key) or "REPLACE" in c[key] or "TODO" in c[key]:
                raise ValueError(f"Record an exact {key} before benchmarking")
        if not re.fullmatch(r"[0-9a-f]{64}", c["chat_template_sha256"]):
            raise ValueError("Record SHA256 of the actual chat template")
        if environment_kind() != c["os_id"]:
            raise ValueError("Detected environment does not match selected OS profile")
        if not c.get("hardware_attestation"):
            raise ValueError("Record BIOS/power/MUX/SSD/driver observations in hardware_attestation")
    return engine, model


def grade(text, task):
    """Small deterministic smoke checks; never execute generated code."""
    kind = task.get("check", {}).get("type", "none")
    expected = task.get("check", {}).get("expected")
    if kind == "none":
        return None
    if kind == "exact":
        return text.strip() == expected
    if kind == "json_equal":
        try:
            return json.loads(text.strip()) == expected
        except (ValueError, TypeError):
            return False
    raise ValueError("Unknown quality check")


def load_suite(path):
    suite = read_json(path)
    ids = set()
    for task in suite["tasks"]:
        if task["id"] in ids or not task["messages"]:
            raise ValueError("Duplicate task ID or empty messages")
        ids.add(task["id"])
        for m in task["messages"]:
            if m.get("role") not in {"system", "user", "assistant"} or not isinstance(m.get("content"), str):
                raise ValueError("Only text chat messages are supported")
        grade("", task)
    if not ids:
        raise ValueError("Empty suite")
    return suite


def validate_host(c, root, host=None):
    host = host if host is not None else host_snapshot()
    hardware = read_json(Path(root) / ('configs/hardware/' + c.get('hardware_profile', 'msi-raider-18-hx-ai') + '.json'))
    if not host['psutil_available']:
        raise ValueError('Install the telemetry extra for real hardware runs')
    if not any(hardware['gpu']['name'] in g['name'] for g in host['gpus']):
        raise ValueError('Expected hardware-profile NVIDIA GPU was not detected')
    if host.get('ac_connected') is False:
        raise ValueError('Connect AC power before a performance run')
    return host


def run(config_path, root, output, synthetic=False):
    config_path, root = Path(config_path).resolve(), Path(root).resolve()
    c = read_json(config_path)
    engine, model = validate_config(c, root, synthetic)
    # Resolve file paths once, before passing the same absolute values into the child process.
    for key in ("suite", "artifact_root", "artifact_lock", "offload_dir"):
        if c.get(key):
            p = Path(c[key]).expanduser()
            c[key] = str(p.resolve() if p.is_absolute() else (config_path.parent / p).resolve())
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = Path(output) / (stamp + "-" + uuid.uuid4().hex[:8])
    out.mkdir(parents=True, exist_ok=False)
    metadata = {"schema_version": 1, "harness_version": __version__, "synthetic": synthetic,
                "created_utc": stamp, "status": "preflight", "config": c,
                "config_sha256": digest(c), "hardware_profile": read_json(root / ("configs/hardware/" + c.get("hardware_profile", "msi-raider-18-hx-ai") + ".json")),
                "os_profile": read_json(root / ("configs/os/" + c["os_id"] + ".json")),
                "host": host_snapshot(), "catalog_model": model,
                "provenance_note": "Backend version, loaded model identity, actual precision and placement are operator attestations; file hashes alone do not prove what an external server loaded."}
    write_json(out / "metadata.json", metadata)
    if (engine["os_support"][c["os_id"]] == "unsupported" or model["status"] == "excluded"
            or model["id"] in engine.get("blocked_models", [])):
        metadata.update(status="skipped", skip_reason="unsupported_os_or_excluded_model")
        write_json(out / "metadata.json", metadata)
        return out
    suite = load_suite(c["suite"])
    metadata["suite_sha256"] = digest(suite)
    metadata["benchmark"] = suite.get("benchmark", "local-smoke")
    metadata["category"] = suite.get("category", "smoke")
    if suite.get("family", "general") != "safety" and model["task_family"] == "safety":
        raise ValueError("Safeguard models require the safety-policy suite")
    if not synthetic:
        lock = read_json(c["artifact_lock"])
        if lock.get("base_model_repo") != model["upstream_repo"]:
            raise ValueError("Artifact base model does not match the selected catalog entry")
        verify_artifact(c["artifact_root"], lock, c.get("lane", "offload") != "control",
                        metadata["hardware_profile"]["gpu"]["vram_gib"])
        metadata["artifact"] = lock
        metadata["artifact_sha256"] = digest(lock)
        if model["status"] == "control" and c.get("lane") != "control":
            raise ValueError("This catalog model belongs in the control lane")
        validate_host(c, root, metadata['host'])
    write_json(out / "metadata.json", metadata)
    adapter = None
    rows = []
    try:
        if c["protocol"] == "worker":
            worker_config = out / "worker-config.json"
            write_json(worker_config, c)
            with Sampler(interval=c.get("telemetry_interval_s", 1.0)) as load_sampler:
                adapter = LocalAdapter(c, worker_config)
            metadata["worker_load_s"] = adapter.load_s
            metadata["worker_versions"] = adapter.backend_versions
            metadata["worker_load_telemetry"] = load_sampler.summary()
            write_json(out / "load-telemetry.json", load_sampler.samples)
            backend_pid = adapter.process.pid
        else:
            adapter = HTTPAdapter(c)
            backend_pid = c.get("backend_pid")
        with Sampler(backend_pid=backend_pid, interval=c.get("telemetry_interval_s", 1.0)) as sampler:
            with open(out / "requests.jsonl", "w", encoding="utf-8") as handle:
                for task in suite["tasks"]:
                    for repetition in range(c["warmups"] + c["repeats"]):
                        row = {"task_id": task["id"], "prompt_sha256": digest(task["messages"]),
                               "category": task.get("category", metadata["category"]),
                               "benchmark": metadata["benchmark"],
                               "warmup": repetition < c["warmups"], "repetition": repetition,
                               "synthetic": synthetic, "status": "ok",
                               "quality_check_applicable": task.get("check", {}).get("type", "none") != "none"}
                        begin = time.perf_counter()
                        try:
                            response = adapter.generate(task["messages"], c["max_output_tokens"], c["seed"], c["temperature"])
                            text = response.pop("text")
                            row.update(response, output_sha256=digest(text.encode()), output_chars=len(text),
                                       quality_pass=grade(text, task), client_request_wall_s=time.perf_counter() - begin)
                            if c.get("save_outputs", False):
                                row["output"] = text
                            if response["prompt_tokens"] is not None and response["completion_tokens"] is not None:
                                if response["prompt_tokens"] + response["completion_tokens"] > c["context_tokens"]:
                                    row.update(status="invalid", error_type="ContextBudgetExceeded")
                        except Exception as exc:
                            row.update(status="error", error_type=type(exc).__name__, elapsed_s=time.perf_counter() - begin)
                        rows.append(row)
                        handle.write(json.dumps(row, allow_nan=False) + "\n")
                        handle.flush()
                        if row["status"] == "error" and c["protocol"] == "worker":
                            raise RuntimeError("Local worker failed; remaining requests cancelled")
        metadata["telemetry"] = sampler.summary()
        paging = False
        for field in ("swap_in_bytes", "swap_out_bytes"):
            values = [s[field] for s in sampler.samples if s.get(field) is not None]
            paging = paging or (len(values) > 1 and values[-1] > values[0])
        installed_ram = metadata["hardware_profile"]["ram"]["installed_gib"]
        metadata["memory_assessment"] = {
            "paging_observed": paging,
            "scope": "system-wide counters; other processes can cause paging",
            "installed_ram_gib": installed_ram,
            "fits_within_installed_ram": "unverified" if "wsl2" in c["os_id"] else (
                "sampled_host_use_below_installed_ram" if metadata["telemetry"].get("system_used_gib_peak") is not None
                and metadata["telemetry"]["system_used_gib_peak"] < installed_ram and not paging else "not_demonstrated"),
            "note": "Windows host telemetry is required separately for WSL; no low-RAM certification is inferred from successful loading."}
        write_json(out / "telemetry.json", sampler.samples)
        metadata["status"] = "completed" if all(r["status"] == "ok" for r in rows) else "completed_with_errors"
    except Exception as exc:
        metadata.update(status="failed", error_type=type(exc).__name__)
    finally:
        if isinstance(adapter, LocalAdapter):
            adapter.close()
        metadata["measured_requests"] = sum(not r["warmup"] for r in rows)
        write_json(out / "metadata.json", metadata)
    return out
