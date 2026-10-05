from __future__ import annotations

import hashlib
import json
import math
import os
import platform
import re
import subprocess
from pathlib import Path

GIB = 1024 ** 3


def read_json(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def digest(data):
    if not isinstance(data, bytes):
        data = json.dumps(data, sort_keys=True, ensure_ascii=False).encode()
    return hashlib.sha256(data).hexdigest()


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def command(args, timeout=10):
    try:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
        return proc.stdout.strip() if proc.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def environment_kind():
    if platform.system() == "Windows":
        try:
            build = int(platform.version().split(".")[2])
            return "windows-11-native" if build >= 22000 else "other"
        except (ValueError, IndexError):
            return "other"
    if platform.system() == "Linux":
        release = platform.release().lower()
        try:
            info = platform.freedesktop_os_release()
            if info.get("ID") == "ubuntu" and info.get("VERSION_ID") == "26.04":
                if "microsoft" in release or os.environ.get("WSL_INTEROP"):
                    return "windows-11-wsl2-ubuntu-26.04" if "wsl2" in release else "other"
                return "ubuntu-26.04-native"
        except OSError:
            pass
    return "other"


def finite_number(value, name, minimum=0, maximum=float("inf")):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be in [{minimum}, {maximum}]")
    return value


def require_revision(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-fA-F]{40}", value):
        raise ValueError("Pin source_revision to a full 40-character repository commit")


def safe_relative(root, relative):
    root = Path(root).resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise ValueError("Artifact path escapes its root")
    return path
