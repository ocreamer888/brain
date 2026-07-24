import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from brain.bootstrap.ingest_claude_code_lib import _derive_session_title


def test_title_uses_first_user_message():
    record = {
        "project": "AI",
        "text": "Claude Code session: AI | Ended: 2026-05-02 | [user] how do I fix CORS in Next.js? | [assistant] Use the cors package",
        "metadata": {"timestamp": "2026-05-02T10:00:00+00:00"},
    }
    title = _derive_session_title(record, "abc-123")
    assert title == "how do I fix CORS in Next.js? — AI"
    assert "abc-123" not in title
    assert "Session" not in title


def test_title_truncates_long_user_message():
    long_msg = "a" * 100
    record = {
        "project": "AI",
        "text": f"Claude Code session: AI | [user] {long_msg} | [assistant] ok",
        "metadata": {"timestamp": "2026-05-02T10:00:00+00:00"},
    }
    title = _derive_session_title(record, "abc")
    assert len(title) <= 100  # 80 chars + " — AI" margin
    assert title.endswith("... — AI")


def test_title_falls_back_to_date_when_no_user_message():
    record = {
        "project": "sicop",
        "text": "Claude Code session: sicop | Ended: 2026-05-02 | Total messages: 5",
        "metadata": {"timestamp": "2026-05-02T10:00:00+00:00"},
    }
    title = _derive_session_title(record, "abc-123")
    assert title == "Session 2026-05-02 — sicop"
    assert "abc-123" not in title


def test_title_collapses_whitespace_in_user_message():
    record = {
        "project": "owelign",
        "text": "Claude Code session: owelign | [user] let's\n\nbuild\n\nthis | [assistant] ok",
        "metadata": {"timestamp": "2026-05-03T10:00:00+00:00"},
    }
    title = _derive_session_title(record, "xyz")
    assert title == "let's build this — owelign"
    assert "\n" not in title
