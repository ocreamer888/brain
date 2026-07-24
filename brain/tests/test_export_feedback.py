"""Export script produces JSONL lines matching the Phase 7 export shape."""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture()
def sample_db(tmp_path):
    db = tmp_path / "t.db"
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
    conn.execute(
        "INSERT INTO feedback_events VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            "e1",
            "2026-01-01T00:00:00+00:00",
            "accepted",
            None,
            None,
            None,
            None,
            "mcp",
            "{}",
            None,
        ),
    )
    conn.commit()
    conn.close()
    return db


def test_export_feedback_jsonl_shape(sample_db: Path):
    script = Path(__file__).resolve().parents[1] / "tools" / "export_feedback.py"
    out = subprocess.run(
        [sys.executable, str(script), "--db", str(sample_db)],
        capture_output=True,
        text=True,
        check=True,
    )
    line = json.loads(out.stdout.strip())
    assert line["schema_version"] == 1
    assert line["event_type"] == "accepted"
    assert line["source"] == "mcp"
    assert line["payload"] == {}


def test_export_feedback_handles_missing_feedback_table(tmp_path):
    db = tmp_path / "t.db"
    conn = sqlite3.connect(str(db))
    conn.execute("CREATE TABLE other_table (id TEXT)")
    conn.commit()
    conn.close()

    script = Path(__file__).resolve().parents[1] / "tools" / "export_feedback.py"
    out = subprocess.run(
        [sys.executable, str(script), "--db", str(db)],
        capture_output=True,
        text=True,
    )
    assert out.returncode == 0
    assert out.stdout.strip() == ""
    assert "table not found" in out.stderr
