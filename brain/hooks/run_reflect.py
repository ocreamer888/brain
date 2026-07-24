#!/usr/bin/env python3
"""
Background reflection runner — called by session_end hook.
Runs /reflect with a long timeout, logs result.
"""
import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from brain.api_client import _base_url, _headers, get_stats

LOG = Path(__file__).parent / "reflect.log"

try:
    before = get_stats().get("total_memories", 0)

    req = urllib.request.Request(
        url=f"{_base_url()}/reflect",
        data=b"{}",
        method="POST",
        headers=_headers(),
    )
    with urllib.request.urlopen(req, timeout=300) as resp:
        result = json.loads(resp.read().decode("utf-8"))

    after = get_stats().get("total_memories", before)
    msg = f"Reflection done: {before} -> {after} ({after - before:+d})\n"
    with LOG.open("a", encoding="utf-8") as f:
        f.write(msg)

except Exception as e:
    with LOG.open("a", encoding="utf-8") as f:
        f.write(f"Reflection failed: {e}\n")
