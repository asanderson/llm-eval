#!/usr/bin/env bash
# Works before the harness or a supported Python has been installed.
set -euo pipefail
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
REPO="$(dirname "$SCRIPT_DIR")"
CHECK_ONLY=0
ASSUME_YES=0
HELP=0
for argument in "$@"; do
    case "$argument" in
        --check-only) CHECK_ONLY=1 ;;
        --yes) ASSUME_YES=1 ;;
        --help|-h) HELP=1 ;;
    esac
done
if (( CHECK_ONLY && ASSUME_YES )); then
    printf '%s\n' '--check-only and --yes are mutually exclusive.' >&2
    exit 2
fi
compatible() {
    "$1" -c 'import sys,venv,ensurepip,ssl,tarfile; assert (3,11)<=sys.version_info[:2]<=(3,13); assert sys.maxsize>2**32; assert hasattr(tarfile,"data_filter")' >/dev/null 2>&1
}
for candidate in "${LLM_EVAL_PYTHON:-}" "$REPO/.venv/bin/python" python3.12 python3.13 python3.11 python3; do
    if [[ -n "$candidate" ]] && compatible "$candidate"; then
        exec "$candidate" "$SCRIPT_DIR/readiness.py" "$@"
    fi
done
printf '%s\n' '[MISSING] Python 3.11-3.13 with venv/pip/TLS.'
if (( HELP )); then
    printf '%s\n' 'readiness.sh [--platform NAME | --campaign FILE] [--check-only | --yes] [--json-output FILE]'
    printf '%s\n' 'See docs/READINESS.md; the complete CLI help is available after Python bootstrap.'
    exit 0
fi
if (( CHECK_ONLY )); then
    printf '%s\n' 'Full dependency inspection needs Python. Rerun without --check-only to offer its installation.'
    exit 1
fi
if [[ ! -r /etc/os-release ]]; then
    printf '%s\n' 'Use the native Windows readiness.ps1 or an Ubuntu 26.04 host.' >&2
    exit 2
fi
. /etc/os-release
if [[ "$ID" != ubuntu || "$VERSION_ID" != 26.04 ]]; then
    printf '%s\n' 'Automatic bootstrap is supported on Ubuntu 26.04 (native or WSL2).' >&2
    exit 2
fi
if [[ "$(uname -m)" != x86_64 ]]; then
    printf '%s\n' 'The current installer recipes require x86-64 hardware.' >&2
    exit 2
fi
BOOTSTRAP="$REPO/.readiness-bootstrap"
printf '%s\n' 'Proposed bootstrap: apt-get update; apt-get install --no-install-recommends python3 python3-venv ca-certificates;'
printf 'create %s; install uv there; use uv to install user-local Python 3.12.\n' "$BOOTSTRAP"
if (( ! ASSUME_YES )); then
    if [[ ! -t 0 ]]; then
        printf '%s\n' 'No interactive terminal: no installation. Use --yes for explicit unattended consent.'
        exit 1
    fi
    read -r -p 'Install this bootstrap now? [y/N] ' answer || answer=n
    case "$answer" in y|Y|yes|YES) ;; *) exit 1 ;; esac
fi
PRIVILEGE=()
if (( EUID != 0 )); then PRIVILEGE=(sudo); fi
"${PRIVILEGE[@]}" apt-get update
"${PRIVILEGE[@]}" apt-get install -y --no-install-recommends python3 python3-venv ca-certificates
if [[ -e "$BOOTSTRAP" && ! -f "$BOOTSTRAP/pyvenv.cfg" ]]; then
    printf '%s\n' 'Conflicting bootstrap directory; preserve it and choose a clean checkout.' >&2
    exit 1
fi
python3 -m venv "$BOOTSTRAP"
"$BOOTSTRAP/bin/python" -m pip install uv
"$BOOTSTRAP/bin/uv" python install 3.12
PYTHON312="$("$BOOTSTRAP/bin/uv" python find 3.12)"
compatible "$PYTHON312"
exec "$PYTHON312" "$SCRIPT_DIR/readiness.py" "$@"
