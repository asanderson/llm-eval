#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
exec "${LLM_EVAL_PYTHON:-python3}" "$SCRIPT_DIR/../../../run.py" --platform 'vllm' --os 'ubuntu-26.04-native' "$@"
