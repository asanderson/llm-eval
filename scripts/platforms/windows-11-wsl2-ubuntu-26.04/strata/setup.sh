#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
exec "${LLM_EVAL_PYTHON:-python3}" "$SCRIPT_DIR/../../../setup.py" --platform 'strata' --os 'windows-11-wsl2-ubuntu-26.04' "$@"
