#!/bin/bash
cd /Users/abundancia888/Documents/AI
# Rust-primary default; override with BRAIN_BACKEND=python only for legacy Chroma.
export BRAIN_BACKEND="${BRAIN_BACKEND:-api}"
export BRAIN_API_KEY="${BRAIN_API_KEY:-local-dev-key}"
exec /Users/abundancia888/Documents/AI/.venv/bin/python -m brain.mcp.server
