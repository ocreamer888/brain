#!/usr/bin/env python3
"""Replay queued memory writes from durable hook spool."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from brain.hooks.spool import replay_once, metrics


def main() -> int:
    stats = replay_once()
    m = metrics()
    print(
        json.dumps(
            {
                "replayed": stats.replayed,
                "remaining": m["queue_size"],
                "oldest_age_sec": m["oldest_age_sec"],
                "moved_to_dlq": stats.moved_to_dlq,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
