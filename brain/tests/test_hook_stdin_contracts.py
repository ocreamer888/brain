"""
Hook stdin contract tests — verify that golden fixture JSON matches the keys
that brain/hooks/session_end.py reads from context, and that save_session_summary
runs correctly when fed the fixture payload.

Purpose: detect version drift in the Claude Code hook payload shape.  When
Anthropic changes what fields the Stop event provides, update the fixture;
CI will then catch every downstream caller that relied on the old shape.

Reads the actual hook source with regex to extract context.get() calls so the
extracted keys stay authoritative without hard-coding them here.
"""

import json
import re
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "hooks"
HOOK_FILE = Path(__file__).parent.parent / "hooks" / "session_end.py"

# Keys the current hook reads via context.get(...) — derived by reading source.
# Update this set (and the fixture) when the hook changes.
_EXPECTED_CONTEXT_KEYS = {
    "session_id",
    "transcript_path",
    "cwd",
    "ended_at",
}


def _extract_context_keys_from_source() -> set[str]:
    """Parse hook source for context.get('key') patterns at runtime."""
    src = HOOK_FILE.read_text()
    return set(re.findall(r'context\.get\(\s*["\'](\w+)["\']', src))


class TestSessionEndMinimalFixture:
    def setup_method(self):
        self.fixture_path = FIXTURES_DIR / "session_end_minimal.json"
        self.payload = json.loads(self.fixture_path.read_text())

    def test_fixture_file_is_valid_json(self):
        assert isinstance(self.payload, dict)

    def test_fixture_contains_all_expected_keys(self):
        missing = _EXPECTED_CONTEXT_KEYS - set(self.payload.keys())
        assert not missing, (
            f"Fixture is missing keys that session_end.py reads: {missing}\n"
            f"  fixture keys: {set(self.payload.keys())}\n"
            f"  expected keys: {_EXPECTED_CONTEXT_KEYS}"
        )

    def test_hook_source_context_keys_match_expected_set(self):
        """Catch new context.get() calls added to hook without updating fixture."""
        source_keys = _extract_context_keys_from_source()
        drift = source_keys - _EXPECTED_CONTEXT_KEYS
        assert not drift, (
            f"session_end.py reads keys not in _EXPECTED_CONTEXT_KEYS: {drift}\n"
            "  Update _EXPECTED_CONTEXT_KEYS and the fixture file to match."
        )

    def test_fixture_session_id_is_string(self):
        assert isinstance(self.payload["session_id"], str)
        assert self.payload["session_id"]

    def test_fixture_ended_at_looks_like_iso8601(self):
        ended = self.payload["ended_at"]
        assert "T" in ended and ended.endswith("+00:00") or ended.endswith("Z"), (
            f"ended_at {ended!r} does not look like an ISO-8601 timestamp"
        )


class TestSaveSessionSummaryContract:
    """Verify save_session_summary runs through its happy path with mock backend."""

    def test_save_session_summary_with_fixture_payload(self):
        fixture_path = FIXTURES_DIR / "session_end_minimal.json"
        payload = json.loads(fixture_path.read_text())

        fake_summary = {
            "summary": "Session covered hook contract testing.",
            "decisions": ["Use golden fixtures"],
            "next_steps": ["Add CI job"],
        }

        with (
            patch("brain.core.session_ingest.summarize_session", return_value=fake_summary),
            patch("brain.core.session_ingest.save_memory_fn") as mock_save,
        ):
            from brain.core.session_ingest import save_session_summary

            save_session_summary(
                messages=[{"role": "user", "content": "test"}],
                project="AI",
                session_id=payload["session_id"],
                ended_at=payload["ended_at"],
            )

        mock_save.assert_called_once()
        kw = mock_save.call_args[1]
        assert kw["memory_type"] == "project_context"
        assert "session_summary" in kw["tags"]
        assert payload["ended_at"][:10] in kw["title"]

    def test_save_session_summary_survives_summarize_failure(self):
        """Hook must not propagate summarize_session exceptions."""
        with (
            patch("brain.core.session_ingest.summarize_session", side_effect=RuntimeError("llm down")),
            patch("brain.core.session_ingest.save_memory_fn") as mock_save,
        ):
            from brain.core.session_ingest import save_session_summary

            save_session_summary(
                messages=[],
                project="AI",
                session_id="sess-fail",
                ended_at="2026-04-11T10:00:00+00:00",
            )

        mock_save.assert_not_called()
