#!/usr/bin/env bash
# Thin wrapper around brain/harness/supervisor.py
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PY="${ROOT}/.venv/bin/python"
if [[ ! -x "$PY" ]]; then
  PY="${PYTHON:-python3}"
fi
exec "$PY" "${ROOT}/brain/harness/supervisor.py" "$@"
