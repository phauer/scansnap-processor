#!/bin/bash
# Rebuild .venv after a Homebrew Python upgrade (the venv's python symlink points at
# a versioned Cellar path that disappears), then restart the watcher.
set -euo pipefail

REPO="$(cd "$(dirname "$0")" && pwd)"
# Prefer the stable opt path, which survives patch upgrades.
PYTHON="${PYTHON:-/opt/homebrew/opt/python@3.14/bin/python3.14}"
[[ -x "$PYTHON" ]] || PYTHON="$(command -v python3.14)"

rm -rf "$REPO/.venv"
"$PYTHON" -m venv "$REPO/.venv"
"$REPO/.venv/bin/pip" install -r "$REPO/requirements.txt"
"$REPO/.venv/bin/python" -c "import array, ocrmac, pymupdf"
"$REPO/restart-watcher.sh"
