import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from brain.hooks.session_start import (
    extract_date,
    filter_session_summaries,
    build_query,
)


def test_extract_date_from_rfc3339():
    assert extract_date("2026-04-11T10:30:00+00:00") == "2026-04-11"


def test_extract_date_fallback():
    assert extract_date("") == "unknown"
    assert extract_date(None) == "unknown"


def test_filter_session_summaries_keeps_only_tagged():
    memories = [
        {"content": "summary A", "metadata": {"tags": "session_summary,AI", "timestamp": "2026-04-11T00:00:00Z"}},
        {"content": "unrelated", "metadata": {"tags": "bash,AI", "timestamp": "2026-04-10T00:00:00Z"}},
        {"content": "summary B", "metadata": {"tags": "session_summary,AI", "timestamp": "2026-04-09T00:00:00Z"}},
    ]
    result = filter_session_summaries(memories)
    assert len(result) == 2
    assert all("session_summary" in m["metadata"]["tags"] for m in result)


def test_filter_session_summaries_sorted_newest_first():
    memories = [
        {"content": "old", "metadata": {"tags": "session_summary", "timestamp": "2026-04-09T00:00:00Z"}},
        {"content": "new", "metadata": {"tags": "session_summary", "timestamp": "2026-04-11T00:00:00Z"}},
    ]
    result = filter_session_summaries(memories)
    assert result[0]["content"] == "new"


def test_build_query_uses_summary_text():
    summaries = [
        {"content": "Fixed session context in brain.", "metadata": {"timestamp": "2026-04-11T00:00:00Z"}},
    ]
    query = build_query(summaries, fallback="general")
    assert query == "Fixed session context in brain."


def test_build_query_falls_back_when_no_summaries():
    query = build_query([], fallback="general")
    assert query == "general"
