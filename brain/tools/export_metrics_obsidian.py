#!/usr/bin/env python3
"""Export brain metrics to JSON for an Obsidian DataviewJS dashboard."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from brain.api_client import get_stats  # noqa: E402
from brain.hooks.spool import metrics as spool_metrics, source_counts  # noqa: E402


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--out", default="dashboards/brain-dashboard-data.json")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    out = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "status": "ok",
        "api": {},
        "spool": {},
        "spool_by_source": {},
    }

    try:
        out["api"] = get_stats()
    except Exception as e:
        out["status"] = "degraded"
        out["api_error"] = str(e)

    try:
        out["spool"] = spool_metrics()
        out["spool_by_source"] = source_counts()
    except Exception as e:
        out["status"] = "degraded"
        out["spool_error"] = str(e)

    path = Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=2, ensure_ascii=True), encoding="utf-8")
    print(str(path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
