#!/usr/bin/env python3
"""Export brain observability metrics in Prometheus text format."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from collections import defaultdict


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--out", default="brain/tmp/brain.prom")
    p.add_argument("--probe-cmd", default=f"{sys.executable} brain/tools/brain_observability_probe.py")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    proc = subprocess.run(args.probe_cmd.split(" "), capture_output=True, text=True)
    if proc.returncode != 0:
        print(proc.stderr.strip(), file=sys.stderr)
        return proc.returncode

    data = json.loads(proc.stdout.strip())
    api = data.get("api", {})
    spool = data.get("spool", {})
    status = 1 if data.get("status") == "ok" else 0

    lines = [
        "# HELP brain_status_ok 1 if probe status is ok",
        "# TYPE brain_status_ok gauge",
        f"brain_status_ok {status}",
        "# HELP brain_total_memories Total memories in Rust brain",
        "# TYPE brain_total_memories gauge",
        f"brain_total_memories {int(api.get('total_memories', 0))}",
        "# HELP brain_total_sessions Total sessions in Rust brain",
        "# TYPE brain_total_sessions gauge",
        f"brain_total_sessions {int(api.get('total_sessions', 0))}",
        "# HELP brain_spool_queue_size Spool queue size",
        "# TYPE brain_spool_queue_size gauge",
        f"brain_spool_queue_size {int(spool.get('queue_size', 0))}",
        "# HELP brain_spool_oldest_age_seconds Oldest queued event age",
        "# TYPE brain_spool_oldest_age_seconds gauge",
        f"brain_spool_oldest_age_seconds {int(spool.get('oldest_age_sec', 0))}",
    ]
    # Per-source queued backlog (best-effort parse from spool file)
    source_counts: dict[str, int] = defaultdict(int)
    spool_path = Path("brain/hooks/spool/memory_spool.jsonl")
    if spool_path.exists():
        for line in spool_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            src = (
                rec.get("payload", {}).get("source")
                or rec.get("payload", {}).get("memory_source")
                or "unknown"
            )
            source_counts[src] += 1
    lines.extend(
        [
            "# HELP brain_spool_queue_by_source Spool queue size by source",
            "# TYPE brain_spool_queue_by_source gauge",
        ]
    )
    for src, count in sorted(source_counts.items()):
        safe = str(src).replace('"', '\\"')
        lines.append(f'brain_spool_queue_by_source{{source="{safe}"}} {int(count)}')
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(str(out_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
