import sqlite3, json, os, tempfile, pytest
from pathlib import Path


def _make_db(tmp_path):
    db = tmp_path / "brain.db"
    conn = sqlite3.connect(str(db))
    conn.execute("""CREATE TABLE memories (
        id TEXT PRIMARY KEY, type TEXT, session_id TEXT NOT NULL DEFAULT '',
        event_time TEXT, timestamp TEXT NOT NULL DEFAULT ''
    )""")
    conn.execute("INSERT INTO memories VALUES ('f1','\"fact\"','sess-abc',NULL,'2026-05-01')")
    conn.execute("INSERT INTO memories VALUES ('f2','\"fact\"','unknown-id',NULL,'2026-05-01')")
    conn.execute("INSERT INTO memories VALUES ('f3','\"fact\"','',NULL,'2026-05-01')")
    conn.execute("INSERT INTO memories VALUES ('f4','\"fact\"','sess-abc','2026-03-01','2026-05-01')")  # already stamped
    conn.commit()
    conn.close()
    return db


def _make_sessions(tmp_path, session_id, ended_at):
    d = tmp_path / "sessions"
    d.mkdir(exist_ok=True)
    f = d / "sess.json"
    f.write_text(json.dumps({"session_id": session_id, "ended_at": ended_at, "messages": []}))
    return d


def test_session_facts_get_ended_at(tmp_path):
    db = _make_db(tmp_path)
    sessions_dir = _make_sessions(tmp_path, "sess-abc", "2026-04-10T12:00:00+00:00")
    from brain.tools.stamp_event_times import stamp
    counts = stamp(db_path=str(db), sessions_dir=sessions_dir)
    conn = sqlite3.connect(str(db))
    row = conn.execute("SELECT event_time FROM memories WHERE id='f1'").fetchone()
    assert row[0] == "2026-04-10T12:00:00+00:00"
    assert counts["sessions"] == 1


def test_cursor_facts_get_2025_07(tmp_path):
    db = _make_db(tmp_path)
    sessions_dir = _make_sessions(tmp_path, "sess-abc", "2026-04-10T12:00:00+00:00")
    from brain.tools.stamp_event_times import stamp
    stamp(db_path=str(db), sessions_dir=sessions_dir)
    conn = sqlite3.connect(str(db))
    row = conn.execute("SELECT event_time FROM memories WHERE id='f2'").fetchone()
    assert row[0].startswith("2025-07-01")


def test_no_session_id_gets_2025_01(tmp_path):
    db = _make_db(tmp_path)
    sessions_dir = _make_sessions(tmp_path, "sess-abc", "2026-04-10T12:00:00+00:00")
    from brain.tools.stamp_event_times import stamp
    stamp(db_path=str(db), sessions_dir=sessions_dir)
    conn = sqlite3.connect(str(db))
    row = conn.execute("SELECT event_time FROM memories WHERE id='f3'").fetchone()
    assert row[0].startswith("2025-01-01")


def test_already_stamped_untouched(tmp_path):
    db = _make_db(tmp_path)
    sessions_dir = _make_sessions(tmp_path, "sess-abc", "2026-04-10T12:00:00+00:00")
    from brain.tools.stamp_event_times import stamp
    stamp(db_path=str(db), sessions_dir=sessions_dir)
    conn = sqlite3.connect(str(db))
    row = conn.execute("SELECT event_time FROM memories WHERE id='f4'").fetchone()
    assert row[0] == "2026-03-01"  # unchanged
