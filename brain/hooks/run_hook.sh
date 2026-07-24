#!/bin/bash
# Claude Code / Cursor hook launcher — Shared/Code brain → local brain_api.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

export BRAIN_BACKEND="${BRAIN_BACKEND:-api}"
export BRAIN_API_URL="${BRAIN_API_URL:-http://127.0.0.1:8787}"
export BRAIN_API_KEY="${BRAIN_API_KEY:-local-dev-key}"
export PYTHONPATH="${REPO_ROOT}${PYTHONPATH:+:$PYTHONPATH}"

if [[ $# -lt 1 ]]; then
  echo "usage: run_hook.sh <hook_script.py>" >&2
  exit 2
fi

HOOK="$1"
shift
if [[ "$HOOK" != /* ]]; then
  HOOK="$SCRIPT_DIR/$HOOK"
fi

if [[ -n "${VIRTUAL_ENV:-}" && -x "${VIRTUAL_ENV}/bin/python" ]]; then
  PYTHON="${VIRTUAL_ENV}/bin/python"
elif [[ -x "${REPO_ROOT}/.venv/bin/python" ]]; then
  PYTHON="${REPO_ROOT}/.venv/bin/python"
elif [[ -x "${HOME}/Documents/AI/.venv/bin/python" ]]; then
  PYTHON="${HOME}/Documents/AI/.venv/bin/python"
else
  PYTHON="$(command -v python3)"
fi

exec "$PYTHON" "$HOOK" "$@"
