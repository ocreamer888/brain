"""Tests for backfill_bad_data.py — runs against in-memory SQLite."""
import sys, sqlite3
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import pytest


def _make_db(tmp_path):
    """Create minimal brain.db schema with representative bad data."""
    db = tmp_path / "brain.db"
    conn = sqlite3.connect(str(db))
    conn.executescript("""
        CREATE TABLE memories (
            id TEXT PRIMARY KEY,
            content TEXT NOT NULL,
            type TEXT NOT NULL,
            project TEXT NOT NULL DEFAULT 'general',
            timestamp TEXT NOT NULL DEFAULT '2026-01-01T00:00:00+00:00',
            title TEXT,
            embedding BLOB,
            source TEXT NOT NULL DEFAULT 'test',
            tags TEXT NOT NULL DEFAULT '',
            session_id TEXT NOT NULL DEFAULT '',
            importance REAL NOT NULL DEFAULT 0.5,
            salience REAL NOT NULL DEFAULT 0.5
        );
        CREATE VIRTUAL TABLE memories_fts USING fts5(
            id UNINDEXED, content, title,
            tokenize='porter ascii'
        );
        -- NOTE: the Rust store persists `type` JSON-encoded (with quotes), e.g. "conversation".
        -- The backfill queries match that form, so the fixture must mirror it exactly.
        INSERT INTO memories VALUES ('c1','Claude Code session: AI | Ended: 2026-05-01','"conversation"','AI','2026-05-01T10:00:00+00:00','Claude Code — 90748205-f28a-45ae',NULL,'claude_code_session','','',0.6,0.5);
        INSERT INTO memories_fts(rowid,id,content,title) SELECT rowid,id,content,title FROM memories WHERE id='c1';

        INSERT INTO memories VALUES ('p1','Ran command: git status','"pattern"','AI','2026-05-02T10:00:00+00:00','Bash · AI',NULL,'claw_code','','',0.5,0.5);
        INSERT INTO memories_fts(rowid,id,content,title) SELECT rowid,id,content,title FROM memories WHERE id='p1';

        INSERT INTO memories VALUES ('s1','Edited /some/file.py: x = 1\n','"solution"','AI','2026-05-03T10:00:00+00:00','Edit · AI',NULL,'claw_code','','',0.5,0.5);
        INSERT INTO memories_fts(rowid,id,content,title) SELECT rowid,id,content,title FROM memories WHERE id='s1';

        INSERT INTO memories VALUES ('s2','Wrote /some/file.py','"solution"','AI','2026-05-03T11:00:00+00:00','Write · AI',NULL,'claw_code','','',0.5,0.5);
        INSERT INTO memories_fts(rowid,id,content,title) SELECT rowid,id,content,title FROM memories WHERE id='s2';

        INSERT INTO memories VALUES ('pc1','Worked on brain retrieval. Decisions: Use RRF.','"project_context"','AI','2026-05-04T10:00:00+00:00','Session 2026-05-04 — AI',NULL,'claude_code_session','','',0.6,0.5);
        INSERT INTO memories_fts(rowid,id,content,title) SELECT rowid,id,content,title FROM memories WHERE id='pc1';
    """)
    conn.close()
    return db


def test_conversation_titles_fixed(tmp_path):
    db = _make_db(tmp_path)
    from brain.tools.backfill_bad_data import run_backfill
    stats = run_backfill(db_path=db, dry_run=False)
    conn = sqlite3.connect(str(db))
    row = conn.execute("SELECT title FROM memories WHERE id='c1'").fetchone()
    conn.close()
    assert row is not None
    assert "90748205" not in row[0]
    assert "2026-05-01" in row[0]
    assert "AI" in row[0]
    assert stats.conversations_retitled >= 1


def test_bash_log_patterns_deleted(tmp_path):
    db = _make_db(tmp_path)
    from brain.tools.backfill_bad_data import run_backfill
    run_backfill(db_path=db, dry_run=False)
    conn = sqlite3.connect(str(db))
    row = conn.execute("SELECT id FROM memories WHERE id='p1'").fetchone()
    fts_row = conn.execute("SELECT id FROM memories_fts WHERE id='p1'").fetchone()
    conn.close()
    assert row is None, "bash log pattern must be deleted from memories"
    assert fts_row is None, "bash log pattern must be deleted from memories_fts"


def test_file_edit_solutions_deleted(tmp_path):
    db = _make_db(tmp_path)
    from brain.tools.backfill_bad_data import run_backfill
    run_backfill(db_path=db, dry_run=False)
    conn = sqlite3.connect(str(db))
    row = conn.execute("SELECT id FROM memories WHERE id='s1'").fetchone()
    fts_row = conn.execute("SELECT id FROM memories_fts WHERE id='s1'").fetchone()
    conn.close()
    assert row is None
    assert fts_row is None


def test_write_hook_solutions_deleted(tmp_path):
    db = _make_db(tmp_path)
    from brain.tools.backfill_bad_data import run_backfill
    run_backfill(db_path=db, dry_run=False)
    conn = sqlite3.connect(str(db))
    row = conn.execute("SELECT id FROM memories WHERE id='s2'").fetchone()
    conn.close()
    assert row is None


def test_good_project_context_untouched(tmp_path):
    db = _make_db(tmp_path)
    from brain.tools.backfill_bad_data import run_backfill
    run_backfill(db_path=db, dry_run=False)
    conn = sqlite3.connect(str(db))
    row = conn.execute("SELECT title FROM memories WHERE id='pc1'").fetchone()
    conn.close()
    assert row is not None
    assert row[0] == "Session 2026-05-04 — AI"


def test_dry_run_makes_no_changes(tmp_path):
    db = _make_db(tmp_path)
    from brain.tools.backfill_bad_data import run_backfill
    run_backfill(db_path=db, dry_run=True)
    conn = sqlite3.connect(str(db))
    count = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
    conn.close()
    assert count == 5, "dry_run must not change anything"
