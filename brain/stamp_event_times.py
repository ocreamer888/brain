#!/usr/bin/env python3
"""One-time script: stamp event_time on facts that have none.

Passes:
  1. Claude Code sessions  → ended_at from session JSON
  2. Cursor/Perplexity     → 2025-07-01 (historical backup era)
  3. No session_id         → 2025-01-01 (oldest/least certain)

Idempotent — all UPDATEs include WHERE event_time IS NULL.
"""
from __future__ import annotations
import json, sqlite3, sys
from pathlib import Path

_CURSOR_STAMP   = "2025-07-01T00:00:00+00:00"
_NOSESS_STAMP   = "2025-01-01T00:00:00+00:00"
_FACT_TYPE      = '"fact"'

_DEFAULT_DB       = Path(__file__).resolve().parents[1] / "rust" / "brain.db"
_DEFAULT_SESSIONS = Path(__file__).resolve().parents[1] / "bootstrap" / "sessions_export"


def stamp(
    db_path: str | Path = _DEFAULT_DB,
    sessions_dir: str | Path = _DEFAULT_SESSIONS,
) -> dict[str, int]:
    db_path      = Path(db_path)
    sessions_dir = Path(sessions_dir)

    conn = sqlite3.connect(str(db_path), timeout=30)
    counts: dict[str, int] = {"sessions": 0, "cursor": 0, "nosess": 0}

    try:
        # Pass 1: Claude Code sessions
        for f in sessions_dir.glob("*.json"):
            try:
                data     = json.loads(f.read_text())
                sess_id  = data.get("session_id", "")
                ended_at = data.get("ended_at", "")
                if not sess_id or not ended_at:
                    continue
                cur = conn.execute(
                    "UPDATE memories SET event_time=? "
                    "WHERE type=? AND session_id=? AND event_time IS NULL",
                    (ended_at, _FACT_TYPE, sess_id),
                )
                counts["sessions"] += cur.rowcount
            except Exception:
                continue
        conn.commit()

        # Pass 2: remaining facts with a session_id (Cursor / Perplexity)
        cur = conn.execute(
            "UPDATE memories SET event_time=? "
            "WHERE type=? AND session_id!='' AND event_time IS NULL",
            (_CURSOR_STAMP, _FACT_TYPE),
        )
        counts["cursor"] = cur.rowcount
        conn.commit()

        # Pass 3: facts with no session_id
        cur = conn.execute(
            "UPDATE memories SET event_time=? "
            "WHERE type=? AND (session_id IS NULL OR session_id='') AND event_time IS NULL",
            (_NOSESS_STAMP, _FACT_TYPE),
        )
        counts["nosess"] = cur.rowcount
        conn.commit()

    finally:
        conn.close()

    return counts


def main() -> int:
    counts = stamp()
    total = sum(counts.values())
    print(f"[stamp] sessions={counts['sessions']} cursor={counts['cursor']} nosess={counts['nosess']} total={total}")
    remaining = sqlite3.connect(str(_DEFAULT_DB)).execute(
        "SELECT COUNT(*) FROM memories WHERE type=? AND event_time IS NULL",
        (_FACT_TYPE,)
    ).fetchone()[0]
    print(f"[stamp] facts still without event_time: {remaining}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
