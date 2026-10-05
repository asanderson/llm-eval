"""Artifact provenance. No network download or model code execution."""
from pathlib import Path

from .common import GIB, require_revision, safe_relative, sha256_file, write_json

WEIGHT_EXTENSIONS = {".gguf", ".safetensors", ".bin", ".pt", ".pth"}


def lock_artifact(root, source_repo, source_revision, precision, output):
    require_revision(source_revision)
    root = Path(root).resolve()
    if not root.is_dir():
        raise ValueError("Artifact root must be a directory containing only one selected model variant")
    if Path(output).resolve().is_relative_to(root):
        raise ValueError("Write the lock outside the artifact directory")
    files = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("Materialize artifact symlinks before hashing (copy files from the HF cache)")
        if path.is_file():
            if any(p.startswith(".") for p in path.relative_to(root).parts):
                continue
            files.append({"path": path.relative_to(root).as_posix(), "bytes": path.stat().st_size,
                          "sha256": sha256_file(path), "weight": path.suffix.lower() in WEIGHT_EXTENSIONS})
    weight_bytes = sum(f["bytes"] for f in files if f["weight"])
    if weight_bytes == 0:
        raise ValueError("No weight files found")
    manifest = {"schema_version": 1, "source_repo": source_repo, "source_revision": source_revision,
                "precision": precision, "weight_bytes": weight_bytes, "files": files}
    write_json(output, manifest)
    return manifest


def verify_artifact(root, manifest, require_over_vram=True, vram_gib=24):
    require_revision(manifest["source_revision"])
    seen = set()
    total = 0
    for entry in manifest["files"]:
        if entry["path"] in seen:
            raise ValueError("Duplicate artifact path")
        seen.add(entry["path"])
        path = safe_relative(root, entry["path"])
        if not path.is_file() or path.stat().st_size != entry["bytes"] or sha256_file(path) != entry["sha256"]:
            raise ValueError(f"Artifact verification failed: {entry['path']}")
        if entry["weight"]:
            total += entry["bytes"]
    if total != manifest["weight_bytes"] or total <= 0:
        raise ValueError("Incorrect weight byte total")
    actual = set()
    for path in Path(root).resolve().rglob("*"):
        relative = path.relative_to(Path(root).resolve())
        if path.is_symlink():
            raise ValueError("Artifact contains a symlink")
        if path.is_file() and not any(p.startswith(".") for p in relative.parts):
            actual.add(relative.as_posix())
    if actual != seen:
        raise ValueError("Artifact file inventory changed after locking")
    if require_over_vram and total <= vram_gib * GIB:
        raise ValueError("Selected weight artifact does not exceed physical GPU VRAM; use the control lane")
    return total
