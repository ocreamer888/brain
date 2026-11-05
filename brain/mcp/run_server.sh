#!/bin/bash
# Portable MCP launcher — repo root is two levels above this script (brain/mcp/).
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PKG_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$PKG_DIR/.." && pwd)"
cd "$REPO_ROOT"

# Load brain/.env (single source for MCP client → API URL/key).
# Values in .env override Cursor mcp.json env for the same keys.
ENV_FILE="${PKG_DIR}/.env"
if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi

export BRAIN_BACKEND="${BRAIN_BACKEND:-api}"
export BRAIN_API_KEY="${BRAIN_API_KEY:-local-dev-key}"
export BRAIN_API_URL="${BRAIN_API_URL:-http://127.0.0.1:8787}"
export PYTHONPATH="${REPO_ROOT}${PYTHONPATH:+:$PYTHONPATH}"

# Prefer active venv, then this repo's .venv, then python3 on PATH.
if [[ -n "${VIRTUAL_ENV:-}" && -x "${VIRTUAL_ENV}/bin/python" ]]; then
  PYTHON="${VIRTUAL_ENV}/bin/python"
elif [[ -x "${REPO_ROOT}/.venv/bin/python" ]]; then
  PYTHON="${REPO_ROOT}/.venv/bin/python"
else
  PYTHON="$(command -v python3)"
fi

exec "$PYTHON" -m brain.mcp.server
