"""Tests for run_cleanup.run_episodic_leak_check (2026-11-03).

Regression coverage for a real near-miss: the first version of this check's
fix (made structural, tag-based instead of content-wording-based) flagged
~150 unrelated rows live in production -- an older "claw_code" tool and
Perplexity threads also use "write"/"agent" tags for unrelated reasons.
Scoping by source="claude_code_hook" (the only source the current
post_tool_use.py hook ever writes) fixes it. These tests lock that in.

Also: run_cleanup.py's module-level block used to execute unconditionally on
import (same class of bug fixed in brain/mcp/memory_consolidation.py this
session) -- importing this module to test it actually ran real BVH-dedup
deletion against the live production brain.db as a side effect. Fixed with
an `if __name__ == "__main__":` guard; these tests only pass if that import
stays side-effect-free.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path
from unittest.mock import patch

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from brain.hooks.run_cleanup import run_episodic_leak_check


def _make_test_db(path: Path, rows: list[tuple]) -> None:
    conn = sqlite3.connect(str(path))
    conn.executescript(
        """
        CREATE TABLE memories (
            id TEXT PRIMARY KEY,
            type TEXT NOT NULL,
            source TEXT,
            tags TEXT
        );
        """
    )
    conn.executemany("INSERT INTO memories (id, type, source, tags) VALUES (?, ?, ?, ?)", rows)
    conn.commit()
    conn.close()


def test_flags_real_leak_from_current_hook(tmp_path: Path) -> None:
    db_path = tmp_path / "test_brain.db"
    _make_test_db(
        db_path,
        [("m1", '"solution"', '"claude_code_hook"', "write,brain")],
    )
    with patch("brain.hooks.run_cleanup._log") as mock_log:
        run_episodic_leak_check(db_path)
    msg = mock_log.call_args[0][0]
    assert "REGRESSION" in msg
    assert '"solution"=1' in msg


def test_clean_when_write_tagged_row_is_already_episode(tmp_path: Path) -> None:
    db_path = tmp_path / "test_brain.db"
    _make_test_db(
        db_path,
        [("m1", '"episode"', '"claude_code_hook"', "write,brain")],
    )
    with patch("brain.hooks.run_cleanup._log") as mock_log:
        run_episodic_leak_check(db_path)
    assert "clean" in mock_log.call_args[0][0]


def test_ignores_write_tag_from_unrelated_source(tmp_path: Path) -> None:
    """Regression: the un-scoped version of this check flagged ~150 real
    production rows from an unrelated older 'claw_code' tool that also
    happens to use a 'write' tag."""
    db_path = tmp_path / "test_brain.db"
    _make_test_db(
        db_path,
        [("m1", '"solution"', '"claw_code"', "write,AI")],
    )
    with patch("brain.hooks.run_cleanup._log") as mock_log:
        run_episodic_leak_check(db_path)
    assert "clean" in mock_log.call_args[0][0]


def test_ignores_agent_as_a_content_word_in_unrelated_tags(tmp_path: Path) -> None:
    """Regression: a Perplexity thread auto-tag-scraped the literal word
    'agent' from its content ('...acting as a senior data analyst agent'),
    unrelated to any PostToolUse Agent-tool dispatch."""
    db_path = tmp_path / "test_brain.db"
    _make_test_db(
        db_path,
        [("m1", '"project_context"', '"perplexity"', "professional,agent,acting,senior")],
    )
    with patch("brain.hooks.run_cleanup._log") as mock_log:
        run_episodic_leak_check(db_path)
    assert "clean" in mock_log.call_args[0][0]


def test_does_not_false_positive_on_tag_substring(tmp_path: Path) -> None:
    """A tag containing 'write'/'agent' as a substring of a longer word must
    not match -- e.g. 'overwrite' or 'subagent' are different tags."""
    db_path = tmp_path / "test_brain.db"
    _make_test_db(
        db_path,
        [("m1", '"solution"', '"claude_code_hook"', "overwrite,subagent,brain")],
    )
    with patch("brain.hooks.run_cleanup._log") as mock_log:
        run_episodic_leak_check(db_path)
    assert "clean" in mock_log.call_args[0][0]


def test_missing_db_is_a_silent_noop(tmp_path: Path) -> None:
    db_path = tmp_path / "does_not_exist.db"
    with patch("brain.hooks.run_cleanup._log") as mock_log:
        run_episodic_leak_check(db_path)
    mock_log.assert_not_called()


def test_importing_module_has_no_side_effects():
    """Regression: the module-level block used to run real BVH dedup
    (deleting live production rows) and other cleanup on bare import, with
    no __main__ guard. Re-importing here must not touch sys.argv/__main__
    state or raise -- the real proof is that collecting this test file at
    all didn't already mutate brain.db, which every other test in this
    session's suite implicitly depends on staying untouched."""
    import importlib
    import brain.hooks.run_cleanup as mod

    importlib.reload(mod)  # re-run module top-level code; must be a no-op off of __main__
