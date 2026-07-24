#!/usr/bin/env bash
# Chain downstream brain steps after real-time capture (hooks/API).
# Prerequisite: BRAIN_DB_PATH (and API already ran during the day if using api mode).
#
# Usage (from repo root AI/):
#   bash brain/tools/brain_chain.sh              # digest + 7-day feedback JSONL
#   bash brain/tools/brain_chain.sh digest       # markdown digest only
#   bash brain/tools/brain_chain.sh export       # JSONL only (--since-days via 2nd arg)
#   bash brain/tools/brain_chain.sh health       # curl /health (BRAIN_API_URL)
#   bash brain/tools/brain_chain.sh backfill     # run checkpointed backfill orchestration
#
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

MODE="${1:-all}"
SINCE_DAYS="${2:-7}"

run_digest() {
  echo "==> feedback_digest.py"
  python3 brain/tools/feedback_digest.py
}

run_export() {
  local out="docs/feedback-digests/feedback-export-$(date -u +%Y-%m-%d).jsonl"
  mkdir -p docs/feedback-digests
  echo "==> export_feedback.py --since-days ${SINCE_DAYS} → ${out}"
  python3 brain/tools/export_feedback.py --since-days "${SINCE_DAYS}" > "${out}"
  echo "    wrote ${out}"
}

run_health() {
  local url="${BRAIN_API_URL:-http://127.0.0.1:8787}"
  echo "==> GET ${url}/health"
  curl -fsS "${url}/health" && echo "" || {
    echo "    (health check failed — is brain_api running?)" >&2
    return 1
  }
}

run_backfill() {
  echo "==> backfill_orchestrator.py"
  python3 brain/tools/backfill_orchestrator.py --no-llm
}

case "${MODE}" in
  digest) run_digest ;;
  export) run_export ;;
  health) run_health ;;
  backfill) run_backfill ;;
  all)
    run_digest
    run_export
    ;;
  *)
    echo "usage: $0 [all|digest|export|health|backfill] [since-days-for-export]" >&2
    exit 1
    ;;
esac
