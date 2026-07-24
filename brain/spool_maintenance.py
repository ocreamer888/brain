#!/usr/bin/env python3
"""Prune old spool and DLQ records by age."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from brain.hooks.spool import metrics, prune


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--max-age-days", type=int, default=14)
    args = p.parse_args()

    before = metrics()
    removed = prune(max_age_days=args.max_age_days)
    after = metrics()

    print(
        json.dumps(
            {
                "max_age_days": args.max_age_days,
                "before": before,
                "removed": removed,
                "after": after,
            },
            ensure_ascii=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
