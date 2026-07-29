#!/usr/bin/env bash
# Package-root shim → tools/refresh_obsidian_dashboard.sh
set -euo pipefail
exec "$(cd "$(dirname "$0")" && pwd)/tools/refresh_obsidian_dashboard.sh" "$@"
