import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
import pytest
import json
import sqlite3
import tempfile
import os


SAMPLE_SQL = """
BEGIN;
CREATE TABLE ItemTable (key TEXT UNIQUE ON CONFLICT REPLACE, value BLOB);
INSERT OR IGNORE INTO 'ItemTable'(_rowid_, 'key', 'value') VALUES (1, 'composerData:abc123', '{"bubbles":[{"role":"user","content":"How do I fix CORS?"},{"role":"assistant","content":"Use cors package"}]}');
INSERT OR IGNORE INTO 'ItemTable'(_rowid_, 'key', 'value') VALUES (2, 'workbench.settings', '{"theme":"dark"}');
COMMIT;
"""


@pytest.fixture
def sample_db(tmp_path):
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(SAMPLE_SQL)
    conn.close()
    return db_path


def test_discover_chat_keys(sample_db):
    from brain.bootstrap.parse_sql import discover_chat_keys
    keys = discover_chat_keys(str(sample_db))
    assert len(keys) >= 1
    assert any("composerData" in k or "bubble" in k.lower() for k in keys)


def test_extract_messages_from_key(sample_db):
    from brain.bootstrap.parse_sql import extract_messages_from_row
    conn = sqlite3.connect(str(sample_db))
    value = conn.execute("SELECT value FROM ItemTable WHERE key = 'composerData:abc123'").fetchone()[0]
    conn.close()
    messages = extract_messages_from_row(value)
    assert len(messages) == 2
    assert messages[0]["role"] == "user"
    assert "CORS" in messages[0]["content"]


def test_extract_all_conversations(sample_db):
    from brain.bootstrap.parse_sql import extract_all_conversations
    convos = extract_all_conversations(str(sample_db))
    assert len(convos) >= 1
    assert "messages" in convos[0]
    assert "session_id" in convos[0]
