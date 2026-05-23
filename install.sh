#!/usr/bin/env bash
# Jade one-command installer — Linux & macOS.
#
#   From a clone:   bash install.sh
#   One-liner:      curl -LsSf https://raw.githubusercontent.com/gahitchi/aicompanion/main/install.sh | bash
#
# This is a thin bootstrap: it just locates the repo and a python3, then hands
# off to installer/setup.py, which does the real work (uv, deps, Ollama, model,
# autostart, smoke test). Pass-through flags go to setup.py, e.g.:
#   bash install.sh --model qwen2.5:3b-instruct
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || true)"
if [[ -n "${SCRIPT_DIR}" && -f "${SCRIPT_DIR}/installer/setup.py" ]]; then
    REPO="$SCRIPT_DIR"
else
    REPO="${JADE_HOME:-$HOME/.jade-companion}"
    if [[ ! -d "$REPO/.git" ]]; then
        command -v git >/dev/null || { echo "git is required to fetch Jade." >&2; exit 1; }
        echo "Cloning Jade into $REPO ..."
        git clone --depth 1 https://github.com/gahitchi/aicompanion "$REPO"
    fi
fi

PY="$(command -v python3 || command -v python || true)"
if [[ -z "$PY" ]]; then
    echo "Python 3 is required to bootstrap. Install it and re-run." >&2
    exit 1
fi

exec "$PY" "$REPO/installer/setup.py" "$@"
