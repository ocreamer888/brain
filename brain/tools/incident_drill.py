#!/usr/bin/env python3
"""Guided incident drill helper for API-down and replay evidence capture."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from brain.hooks.spool import metrics as spool_metrics  # noqa: E402
from brain.tools.replay_spool import main as replay_main  # noqa: E402


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load(path: Path) -> dict:
    if not path.exists():
        return {"started_at": _now(), "events": []}
    return json.loads(path.read_text(encoding="utf-8"))


def _save(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=True), encoding="utf-8")


def log_event(path: Path, message: str) -> int:
    doc = _load(path)
    doc["events"].append({"ts": _now(), "message": message, "spool": spool_metrics()})
    _save(path, doc)
    print(f"logged: {message}")
    return 0


def replay_and_log(path: Path) -> int:
    rc = replay_main()
    doc = _load(path)
    doc["events"].append({"ts": _now(), "message": "replay_spool", "spool": spool_metrics()})
    _save(path, doc)
    return rc


def complete(path: Path) -> int:
    doc = _load(path)
    doc["completed_at"] = _now()
    _save(path, doc)
    print(path)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Incident drill helper")
    p.add_argument("--evidence", default="docs/deploy/incident-drill-evidence.json")
    sub = p.add_subparsers(dest="cmd", required=True)
    le = sub.add_parser("log")
    le.add_argument("--message", required=True)
    sub.add_parser("replay")
    sub.add_parser("complete")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    evidence = Path(args.evidence)
    if args.cmd == "log":
        return log_event(evidence, args.message)
    if args.cmd == "replay":
        return replay_and_log(evidence)
    return complete(evidence)


if __name__ == "__main__":
    raise SystemExit(main())
