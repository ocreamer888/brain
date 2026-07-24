#!/usr/bin/env python3
"""Emit core Rust-brain runtime health and lag metrics as JSON."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from brain.api_client import get_stats  # noqa: E402
from brain.hooks.spool import metrics as spool_metrics  # noqa: E402


def main() -> int:
    out = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "api": {},
        "spool": {},
        "status": "ok",
    }
    try:
        out["api"] = get_stats()
    except Exception as e:
        out["status"] = "degraded"
        out["api_error"] = str(e)

    try:
        out["spool"] = spool_metrics()
    except Exception as e:
        out["status"] = "degraded"
        out["spool_error"] = str(e)

    print(json.dumps(out, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
