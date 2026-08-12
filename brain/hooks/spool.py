#!/usr/bin/env python3
"""Durable local spool for failed API memory writes."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SPOOL_DIR = Path(__file__).resolve().parent / "spool"
SPOOL_FILE = SPOOL_DIR / "memory_spool.jsonl"
DLQ_FILE = SPOOL_DIR / "memory_spool_dlq.jsonl"
MAX_ATTEMPTS = 8


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _event_key(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def enqueue_memory(payload: dict[str, Any], error: str) -> str:
    SPOOL_DIR.mkdir(parents=True, exist_ok=True)
    key = _event_key(payload)
    record = {
        "idempotency_key": key,
        "queued_at": _now_iso(),
        "attempts": 0,
        "last_error": error,
        "payload": payload,
    }
    with SPOOL_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=True) + "\n")
    return key


@dataclass
class ReplayStats:
    replayed: int = 0
    remaining: int = 0
    moved_to_dlq: int = 0


def _read_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def metrics() -> dict[str, int]:
    records = _read_records(SPOOL_FILE)
    oldest_age_sec = 0
    if records:
        try:
            oldest = min(
                datetime.fromisoformat(r.get("queued_at", _now_iso()).replace("Z", "+00:00"))
                for r in records
            )
            oldest_age_sec = max(0, int((datetime.now(timezone.utc) - oldest).total_seconds()))
        except Exception:
            oldest_age_sec = 0
    return {"queue_size": len(records), "oldest_age_sec": oldest_age_sec}


def source_counts() -> dict[str, int]:
    counts: dict[str, int] = {}
    for rec in _read_records(SPOOL_FILE):
        src = (
            rec.get("payload", {}).get("source")
            or rec.get("payload", {}).get("memory_source")
            or "unknown"
        )
        counts[src] = counts.get(src, 0) + 1
    return counts


def _prune_path(path: Path, *, max_age_days: int) -> int:
    if not path.exists():
        return 0
    now = datetime.now(timezone.utc)
    keep: list[dict[str, Any]] = []
    removed = 0
    for rec in _read_records(path):
        ts_raw = rec.get("queued_at") or rec.get("last_attempt_at")
        if not ts_raw:
            keep.append(rec)
            continue
        try:
            ts = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
            age_days = (now - ts).total_seconds() / 86400.0
            if age_days > max_age_days:
                removed += 1
                continue
        except Exception:
            pass
        keep.append(rec)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for rec in keep:
            f.write(json.dumps(rec, ensure_ascii=True) + "\n")
    return removed


def prune(max_age_days: int = 14) -> dict[str, int]:
    removed_spool = _prune_path(SPOOL_FILE, max_age_days=max_age_days)
    removed_dlq = _prune_path(DLQ_FILE, max_age_days=max_age_days)
    return {"removed_spool": removed_spool, "removed_dlq": removed_dlq}


def replay_once() -> ReplayStats:
    from brain.api_client import save_memory_with_status

    records = _read_records(SPOOL_FILE)
    if not records:
        return ReplayStats()

    keep: list[dict[str, Any]] = []
    dlq: list[dict[str, Any]] = []
    replayed = 0

    for rec in records:
        # D5: spooled payloads predate extraction; re-extracting on every retry
        # (up to MAX_ATTEMPTS) would burn an LLM call per attempt. The backfill
        # picks these up instead.
        payload = {**rec.get("payload", {}), "auto_entities": False}
        attempts = int(rec.get("attempts", 0))
        try:
            save_memory_with_status(**payload)
            replayed += 1
        except Exception as e:  # non-fatal for the hook process
            rec["attempts"] = attempts + 1
            rec["last_error"] = str(e)
            rec["last_attempt_at"] = _now_iso()
            if rec["attempts"] >= MAX_ATTEMPTS:
                dlq.append(rec)
            else:
                keep.append(rec)

    SPOOL_DIR.mkdir(parents=True, exist_ok=True)
    with SPOOL_FILE.open("w", encoding="utf-8") as f:
        for rec in keep:
            f.write(json.dumps(rec, ensure_ascii=True) + "\n")
    if dlq:
        with DLQ_FILE.open("a", encoding="utf-8") as f:
            for rec in dlq:
                f.write(json.dumps(rec, ensure_ascii=True) + "\n")

    return ReplayStats(replayed=replayed, remaining=len(keep), moved_to_dlq=len(dlq))
