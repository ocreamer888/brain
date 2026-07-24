"""Incremental feedback digest checkpoint + markdown append."""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


@pytest.fixture()
def digest_setup(tmp_path):
    db = tmp_path / "brain.db"
    conn = sqlite3.connect(str(db))
    conn.execute(
        """
        CREATE TABLE feedback_events (
            id TEXT PRIMARY KEY,
            ts TEXT NOT NULL,
            event_type TEXT NOT NULL,
            memory_id TEXT,
            query TEXT,
            session_id TEXT,
            project TEXT,
            source TEXT NOT NULL,
            payload TEXT NOT NULL DEFAULT '{}',
            idempotency_key TEXT UNIQUE
        )
        """
    )
    # Timestamp must be recent so it falls inside the --bootstrap-hours window
    # regardless of when the test runs (avoids a wall-clock time-bomb).
    event_ts = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    conn.execute(
        "INSERT INTO feedback_events VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            "e1",
            event_ts,
            "accepted",
            "mem-aaa",
            "how do hooks work",
            None,
            "AI",
            "hook",
            "{}",
            None,
        ),
    )
    conn.commit()
    conn.close()
    state = tmp_path / "state.json"
    out = tmp_path / "digests"
    script = Path(__file__).resolve().parents[1] / "tools" / "feedback_digest.py"
    return {"db": db, "state": state, "out": out, "script": script, "ts": event_ts}


def test_digest_writes_markdown_and_checkpoint(digest_setup: dict):
    s = digest_setup
    subprocess.run(
        [
            sys.executable,
            str(s["script"]),
            "--db",
            str(s["db"]),
            "--state",
            str(s["state"]),
            "--out-dir",
            str(s["out"]),
            "--bootstrap-hours",
            "168",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    md = list(s["out"].glob("*.md"))
    assert len(md) == 1
    text = md[0].read_text(encoding="utf-8")
    assert "accepted" in text
    assert "hooks work" in text
    st = json.loads(s["state"].read_text(encoding="utf-8"))
    assert st["last_id"] == "e1"
    assert st["last_ts"] == s["ts"]


def test_digest_idempotent_second_run(digest_setup: dict):
    s = digest_setup
    cmd = [
        sys.executable,
        str(s["script"]),
        "--db",
        str(s["db"]),
        "--state",
        str(s["state"]),
        "--out-dir",
        str(s["out"]),
        "--bootstrap-hours",
        "168",
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    sz1 = sum(f.stat().st_size for f in s["out"].glob("*.md"))
    subprocess.run(cmd, check=True, capture_output=True)
    sz2 = sum(f.stat().st_size for f in s["out"].glob("*.md"))
    assert sz1 == sz2


def test_digest_handles_missing_feedback_table(tmp_path):
    db = tmp_path / "brain.db"
    conn = sqlite3.connect(str(db))
    conn.execute("CREATE TABLE other_table (id TEXT)")
    conn.commit()
    conn.close()

    state = tmp_path / "state.json"
    out = tmp_path / "digests"
    script = Path(__file__).resolve().parents[1] / "tools" / "feedback_digest.py"

    proc = subprocess.run(
        [
            sys.executable,
            str(script),
            "--db",
            str(db),
            "--state",
            str(state),
            "--out-dir",
            str(out),
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0
    assert "table not found" in proc.stderr
    assert state.is_file()
