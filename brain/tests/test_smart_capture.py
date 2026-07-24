"""Tests for Phase 10 Smart Action Capture: corpus barrier, action state, classification."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest


# --- Corpus Barrier ---

class TestBarrierForce:
    def test_below_target_is_zero(self):
        from brain.hooks.corpus_barrier import barrier_force
        assert barrier_force(0) == 0.0
        assert barrier_force(17_000) == 0.0
        assert barrier_force(18_000) == 0.0

    def test_at_max_is_k(self):
        from brain.hooks.corpus_barrier import barrier_force, K
        assert abs(barrier_force(25_000) - K) < 1e-6

    def test_above_max_capped(self):
        from brain.hooks.corpus_barrier import barrier_force, K
        assert abs(barrier_force(30_000) - K) < 1e-6

    def test_midpoint(self):
        from brain.hooks.corpus_barrier import barrier_force, K
        mid = 18_000 + (25_000 - 18_000) // 2  # 21500
        ratio = (mid - 18_000) / (25_000 - 18_000)
        expected = K * ratio ** 3
        assert abs(barrier_force(mid) - expected) < 1e-6

    def test_monotonically_increasing(self):
        from brain.hooks.corpus_barrier import barrier_force
        prev = 0.0
        for n in range(18_000, 26_000, 500):
            val = barrier_force(n)
            assert val >= prev
            prev = val


class TestShouldSave:
    def test_high_confidence_always_saves_below_target(self):
        from brain.hooks.corpus_barrier import should_save
        assert should_save(0.9, n=10_000) is True

    def test_low_confidence_fails_below_target(self):
        from brain.hooks.corpus_barrier import should_save
        assert should_save(0.1, n=10_000) is False

    def test_hard_cap_at_max(self):
        from brain.hooks.corpus_barrier import should_save
        assert should_save(0.99, n=25_000) is False
        assert should_save(1.0, n=25_000) is True

    def test_fail_open_on_api_error(self):
        from brain.hooks.corpus_barrier import should_save
        with patch("brain.api_client.get_stats", side_effect=Exception("down")):
            assert should_save(0.5) is True  # n=0 fallback


# --- Action State ---

class TestActionState:
    def setup_method(self):
        self._tmpdir = tempfile.mkdtemp()
        self._orig_state_file = None

    def _patch_state_file(self):
        import brain.hooks.action_state as mod
        self._orig_state_file = mod.STATE_FILE
        mod.STATE_FILE = Path(self._tmpdir) / "session_state.json"
        return mod

    def teardown_method(self):
        if self._orig_state_file is not None:
            import brain.hooks.action_state as mod
            mod.STATE_FILE = self._orig_state_file

    def test_load_empty_returns_default(self):
        mod = self._patch_state_file()
        state = mod.load_state()
        assert state["recent_errors"] == []
        assert state["tool_count"] == 0

    def test_save_and_load_round_trip(self):
        mod = self._patch_state_file()
        state = mod._empty_state()
        state["tool_count"] = 42
        mod.save_state(state)
        loaded = mod.load_state()
        assert loaded["tool_count"] == 42

    def test_clear_removes_file(self):
        mod = self._patch_state_file()
        mod.save_state(mod._empty_state())
        assert mod.STATE_FILE.exists()
        mod.clear_state()
        assert not mod.STATE_FILE.exists()

    def test_record_error_appends(self):
        mod = self._patch_state_file()
        state = mod._empty_state()
        state["tool_count"] = 5
        mod.record_error(state, "Bash", "ModuleNotFoundError: no module 'foo'", "python3 main.py")
        assert len(state["recent_errors"]) == 1
        assert "foo" in state["recent_errors"][0]["error_snippet"]

    def test_ring_buffer_capped(self):
        mod = self._patch_state_file()
        state = mod._empty_state()
        for i in range(10):
            state["tool_count"] = i
            mod.record_error(state, "Bash", f"error_{i}")
        assert len(state["recent_errors"]) == mod.MAX_RECENT_ERRORS

    def test_pop_matching_error_by_file_stem(self):
        mod = self._patch_state_file()
        state = mod._empty_state()
        state["tool_count"] = 5
        mod.record_error(state, "Bash", "File 'config.py', line 10: SyntaxError")
        state["tool_count"] = 8
        matched = mod.pop_matching_error(state, "/project/config.py")
        assert matched is not None
        assert "config.py" in matched["error_snippet"]
        assert len(state["recent_errors"]) == 0

    def test_pop_matching_error_proximity_fallback(self):
        mod = self._patch_state_file()
        state = mod._empty_state()
        state["tool_count"] = 10
        mod.record_error(state, "Bash", "some random error", "npm test")
        state["tool_count"] = 12  # within MAX_FIX_DISTANCE
        matched = mod.pop_matching_error(state, "/totally/unrelated.py")
        assert matched is not None

    def test_pop_matching_error_too_far(self):
        mod = self._patch_state_file()
        state = mod._empty_state()
        state["tool_count"] = 1
        mod.record_error(state, "Bash", "some error")
        state["tool_count"] = 20  # way past MAX_FIX_DISTANCE
        matched = mod.pop_matching_error(state, "/unrelated.py")
        assert matched is None


class TestEditGrouping:
    def test_record_and_flush(self):
        from brain.hooks.action_state import _empty_state, record_edit, flush_edit_groups, EDIT_FLUSH_THRESHOLD

        state = _empty_state()
        state["tool_count"] = 1
        record_edit(state, "/project/foo.py", "old code", "new code")
        record_edit(state, "/project/foo.py", "old2", "new2")
        assert len(state["edit_groups"]["/project/foo.py"]["changes"]) == 2

        # Not idle yet — should not flush
        state["tool_count"] = 2
        flushed = flush_edit_groups(state)
        assert flushed == []

        # Idle past threshold — should flush
        state["tool_count"] = 1 + 2 + EDIT_FLUSH_THRESHOLD + 1
        flushed = flush_edit_groups(state)
        assert len(flushed) == 1
        fp, content, title = flushed[0]
        assert "foo.py" in fp
        assert len(title) > 0 and len(title) <= 80
        assert "old code" in content or "foo.py" in content
        assert state["edit_groups"] == {}

    def test_flush_all_at_session_end(self):
        from brain.hooks.action_state import _empty_state, record_edit, flush_all_edit_groups

        state = _empty_state()
        state["tool_count"] = 1
        record_edit(state, "/a.py", "x", "y")
        record_edit(state, "/b.py", "p", "q")

        flushed = flush_all_edit_groups(state)
        assert len(flushed) == 2
        assert state["edit_groups"] == {}

    def test_multiple_files_tracked_separately(self):
        from brain.hooks.action_state import _empty_state, record_edit

        state = _empty_state()
        state["tool_count"] = 1
        record_edit(state, "/a.py", "x", "y")
        record_edit(state, "/b.py", "p", "q")
        record_edit(state, "/a.py", "x2", "y2")
        assert len(state["edit_groups"]) == 2
        assert len(state["edit_groups"]["/a.py"]["changes"]) == 2
        assert len(state["edit_groups"]["/b.py"]["changes"]) == 1


class TestLLMTitleFallback:
    def test_llm_title_fallback_on_api_error(self):
        from brain.hooks.post_tool_use import _llm_title
        with patch("brain.core.summarizer._openrouter_chat", side_effect=Exception("API down")):
            title = _llm_title("Fixed ModuleNotFoundError by adding import")
            assert title == "Fixed ModuleNotFoundError by adding import"[:80]
            assert len(title) <= 80

    def test_summarize_edit_group_fallback_on_api_error(self):
        from brain.hooks.action_state import _summarize_edit_group
        with patch("brain.core.summarizer._openrouter_chat", side_effect=Exception("API down")):
            title, content = _summarize_edit_group("/project/foo.py", ["- old → new"])
            assert "foo.py" in title
            assert "foo.py" in content


class TestPatternMatching:
    def test_is_error_response(self):
        from brain.hooks.action_state import is_error_response
        assert is_error_response("Traceback (most recent call last):")
        assert is_error_response("ModuleNotFoundError: No module named 'foo'")
        assert is_error_response("error: command failed with exit code 1")
        assert not is_error_response("Successfully compiled.")
        assert not is_error_response("3 files changed, 10 insertions")

    def test_is_skip_bash(self):
        from brain.hooks.action_state import is_skip_bash
        assert is_skip_bash("ls -la")
        assert is_skip_bash("git status")
        assert is_skip_bash("cat README.md")
        assert not is_skip_bash("python3 brain/tools/eval_suite.py --mcp")
        assert not is_skip_bash("npm test")

    def test_is_skip_file(self):
        from brain.hooks.action_state import is_skip_file
        assert is_skip_file("package-lock.json")
        assert is_skip_file("brain/__pycache__/config.cpython-313.pyc")
        assert is_skip_file("node_modules/express/index.js")
        assert not is_skip_file("brain/hooks/session_end.py")
        assert not is_skip_file("src/components/App.tsx")

    def test_is_test_pass(self):
        from brain.hooks.action_state import is_test_pass
        assert is_test_pass("6 passed in 8.24s")
        assert is_test_pass("Tests OK")
        assert is_test_pass("All green")
        assert not is_test_pass("FAILED brain/tests/test_foo.py")
        assert not is_test_pass("No tests ran")
