import argparse
import csv
import json
from pathlib import Path
import sys

from .artifacts import lock_artifact
from .catalog import matrix, validate_catalog
from .common import read_json, write_json
from .report import write_report
from .runner import run
from .telemetry import host_snapshot


def main():
    campaign_commands = {'experiments', 'plan', 'setup', 'status', 'resume', 'cancel', 'publish-results'}
    if any(a in campaign_commands for a in sys.argv[1:]) or '--campaign' in sys.argv:
        from .orchestration.cli import main as campaign_main
        raise SystemExit(campaign_main(sys.argv[1:]))
    parser = argparse.ArgumentParser(description="Local LLM offload evaluation lab")
    parser.add_argument("--project-root", type=Path, default=Path.cwd(), help="Repository root containing catalog/ and configs/")
    sub = parser.add_subparsers(dest="command", required=True)
    cat = sub.add_parser("catalog", help="Show evidence-backed model candidates")
    cat.add_argument("--provider")
    mat = sub.add_parser("matrix", help="Generate all platform/model/OS eligibility combinations")
    mat.add_argument("--output", type=Path)
    inventory = sub.add_parser("inventory", help="Collect local hardware/OS observations")
    inventory.add_argument("--output", type=Path)
    prepare = sub.add_parser("prepare", help="Create a run config for a platform/model/OS; no installation or download")
    prepare.add_argument("--platform", required=True)
    prepare.add_argument("--model", required=True)
    prepare.add_argument("--os", required=True)
    prepare.add_argument("--output", type=Path, required=True)
    lock = sub.add_parser("lock", help="Hash an already downloaded, selected model artifact")
    lock.add_argument("--root", required=True, type=Path)
    lock.add_argument("--source-repo", required=True)
    lock.add_argument("--source-revision", required=True)
    lock.add_argument("--base-model", required=True, help="Original model repository, including for community quantizations")
    lock.add_argument("--precision", required=True)
    lock.add_argument("--output", required=True, type=Path)
    bench = sub.add_parser("run", help="Benchmark an explicitly configured local engine")
    bench.add_argument("--config", type=Path, required=True)
    bench.add_argument("--output", type=Path, default=Path("results"))
    bench.add_argument("--synthetic", action="store_true", help="Test fixtures only; results excluded from real reports")
    report = sub.add_parser("report", help="Write grouped JSON and CSV summaries")
    report.add_argument("--input", type=Path, default=Path("results"))
    report.add_argument("--output", type=Path, default=Path("results/report"))
    report.add_argument("--include-synthetic", action="store_true")
    args = parser.parse_args()
    try:
        if args.command == "catalog":
            data = validate_catalog(read_json(args.project_root / "catalog/models.json"))
            rows = data["models"]
            if args.provider:
                rows = [m for m in rows if args.provider.lower() in m["provider"].lower()]
            print(json.dumps(rows, indent=2))
        elif args.command == "matrix":
            rows = matrix(args.project_root)
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                with open(args.output, "w", encoding="utf-8", newline="") as f:
                    writer = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")
                    writer.writeheader()
                    writer.writerows(rows)
                print(f"Wrote {len(rows)} combinations to {args.output}")
            else:
                print(json.dumps(rows, indent=2))
        elif args.command == "inventory":
            data = host_snapshot()
            if args.output:
                write_json(args.output, data)
            print(json.dumps(data, indent=2))
        elif args.command == "prepare":
            engines = {p["id"]: p for p in read_json(args.project_root / "catalog/platforms.json")["platforms"]}
            models = {m["id"]: m for m in read_json(args.project_root / "catalog/models.json")["models"]}
            if args.platform not in engines or args.model not in models or args.os not in engines[args.platform]["os_support"]:
                raise ValueError("Unknown platform, model or OS")
            if args.output.exists():
                raise ValueError("Refusing to overwrite an existing run config")
            c = read_json(args.project_root / ("configs/runs/" + args.platform + ".example.json"))
            profile = read_json(args.project_root / ("configs/os/" + args.os + ".json"))
            c.update(model_id=args.model, os_id=args.os, ram_budget_gib=profile["ram_budget_gib"],
                     gpu_budget_gib=profile["vram_budget_gib"], context_tokens=models[args.model]["default_context_tokens"])
            c["lane"] = "control" if models[args.model]["status"] == "control" else c["lane"]
            suite = "safety-policy.json" if models[args.model]["task_family"] == "safety" else "smoke.json"
            # Absolute paths keep generated files valid outside configs/runs; nothing is downloaded.
            c["suite"] = str((args.project_root / "workloads" / suite).resolve())
            for key, path in (("artifact_root", "models/selected-artifact"), ("artifact_lock", "artifacts/selected.lock.json"), ("offload_dir", "offload")):
                c[key] = str((args.project_root / path).resolve())
            write_json(args.output, c)
            print(f"Prepared {args.output}; fill provenance and placement fields before running")
        elif args.command == "lock":
            data = lock_artifact(args.root, args.source_repo, args.source_revision, args.precision, args.output)
            data["base_model_repo"] = args.base_model
            write_json(args.output, data)
            print(f"Locked {len(data['files'])} files; {data['weight_bytes'] / 2**30:.2f} GiB weight artifacts")
        elif args.command == "run":
            out = run(args.config, args.project_root, args.output, args.synthetic)
            print(out)
            if read_json(out / "metadata.json")["status"] not in {"completed", "skipped"}:
                raise SystemExit(1)
        elif args.command == "report":
            rows = write_report(args.input, args.output, args.include_synthetic)
            print(f"Wrote {len(rows)} cohorts to {args.output}")
    except (ValueError, KeyError, OSError) as exc:
        parser.exit(2, f"{type(exc).__name__}: {exc}\n")
