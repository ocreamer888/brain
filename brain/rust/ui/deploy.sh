#!/usr/bin/env bash
# Build the React dashboard and hot-swap it into the supervised brain_api binary.
# Run from any directory.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUST_DIR="$SCRIPT_DIR/.."

# Cursor agent shells may inject CARGO_TARGET_DIR into a sandbox cache.
# Launchd runs brain/rust/target/release/brain_api — force that path.
unset CARGO_TARGET_DIR
export CARGO_TARGET_DIR="$RUST_DIR/target"

echo "==> Clearing stale build assets (preserving runtime data)..."
# vite emptyOutDir is off so eval_dashboard.json survives; clear old hashed
# assets ourselves so they don't accumulate across builds.
rm -rf "$RUST_DIR/static/assets"

echo "==> Building React dashboard..."
cd "$SCRIPT_DIR"
npm run build

echo "==> Compiling brain_api with embedded assets..."
cd "$RUST_DIR"
cargo build --release --bin brain_api

echo "==> Restarting supervised brain_api..."
launchctl kickstart -k "gui/$(id -u)/com.brain.api" || true

echo "==> Verifying..."
for i in $(seq 1 10); do
  sleep 2
  HTTP=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8787/health 2>/dev/null || echo "000")
  [ "$HTTP" = "200" ] && break
  echo "    waiting... ($i/10)"
done
if [ "$HTTP" = "200" ]; then
  echo "    /health → 200 OK"
  echo "    Dashboard: http://127.0.0.1:8787/"
else
  echo "    ERROR: /health returned $HTTP"
  exit 1
fi
