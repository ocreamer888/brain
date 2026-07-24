#!/usr/bin/env bash
set -euo pipefail

ROOT="/Users/macm1air/Documents/AI"
cd "$ROOT"

if [[ -z "${BRAIN_API_KEY:-}" ]]; then
  echo "BRAIN_API_KEY not set" >&2
  exit 2
fi

python3 brain/tools/export_metrics_obsidian.py --out "dashboards/brain-dashboard-data.json"
echo "obsidian dashboard data refreshed"
