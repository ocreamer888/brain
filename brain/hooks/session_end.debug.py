#!/usr/bin/env python3
"""
DEBUG: Capture what Claude Code actually sends to the Stop hook.
Run this temporarily to understand the hook contract.
"""
import sys
import json
from pathlib import Path
from datetime import datetime, timezone

DEBUG_FILE = Path(__file__).parent / "stop_hook_debug.log"

try:
    # Read everything from stdin
    raw_stdin = sys.stdin.read()

    # Log raw input
    with open(DEBUG_FILE, "a") as f:
        f.write(f"\n=== Stop Hook Call at {datetime.now(timezone.utc).isoformat()} ===\n")
        f.write(f"Raw stdin length: {len(raw_stdin)} bytes\n")
        f.write(f"Raw stdin:\n{raw_stdin}\n")

        # Try to parse as JSON
        if raw_stdin.strip():
            try:
                data = json.loads(raw_stdin)
                f.write(f"\nParsed JSON keys: {list(data.keys())}\n")
                f.write(json.dumps(data, indent=2))
            except Exception as e:
                f.write(f"\nFailed to parse JSON: {e}\n")
        else:
            f.write("\nStdin is empty\n")

    print(f"[DEBUG] Stop hook logged to {DEBUG_FILE}", file=sys.stderr)

except Exception as e:
    print(f"[DEBUG] Error: {e}", file=sys.stderr)
