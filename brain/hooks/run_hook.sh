#!/bin/bash
# Claude Code / Cursor hook launcher — Shared/Code brain clients.
# Loads brain/.env so hooks hit the same API as MCP (e.g. Mac Studio).
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PKG_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$PKG_DIR/.." && pwd)"

ENV_FILE="${PKG_DIR}/.env"
if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi

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
else
  PYTHON="$(command -v python3)"
fi

exec "$PYTHON" "$HOOK" "$@"
