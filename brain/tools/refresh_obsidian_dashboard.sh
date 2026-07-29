#!/usr/bin/env bash
# Refresh Obsidian dashboard JSON into the vault (default: repo vault/).
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
VAULT="${OBSIDIAN_VAULT:-${OBSIDIAN_VAULT_PATH:-$REPO_ROOT/vault}}"
cd "$REPO_ROOT"

if [[ -z "${BRAIN_API_KEY:-}" ]]; then
  echo "BRAIN_API_KEY not set" >&2
  exit 2
fi

mkdir -p "$VAULT/dashboards"
python3 brain/tools/export_metrics_obsidian.py --out "$VAULT/dashboards/brain-dashboard-data.json"
echo "obsidian dashboard data refreshed → $VAULT/dashboards/brain-dashboard-data.json"
