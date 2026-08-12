#!/bin/bash
# Wrapper so launchd can spawn an Apple-signed shell rather than the ad-hoc binary directly.
# Env vars (BRAIN_DB_PATH, BRAIN_ONNX_PATH, …) come from the plist or the shell environment.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BINARY="${BRAIN_API_BIN:-$SCRIPT_DIR/target/release/brain_api}"

if [[ ! -x "$BINARY" ]]; then
  echo "brain_api not found or not executable: $BINARY" >&2
  echo "Build with: (cd \"$SCRIPT_DIR\" && cargo build --release)" >&2
  echo "Or set BRAIN_API_BIN to an existing brain_api binary." >&2
  exit 1
fi

exec "$BINARY"
