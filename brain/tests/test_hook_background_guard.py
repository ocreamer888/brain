"""V-08 — the Stop hook must be integration-testable without destroying data.

`session_end.py` spawns `run_reflect.py` (POST /reflect, which DELETES memories)
and `run_cleanup.py` (BVH/title dedup with real delete_memories, plus noise
auto-delete every 20th session). Both always target the real API. Before this
guard there was no way to exercise the hook's own logic without risking a live
consolidation pass — a verification run triggered one and escaped damage only
because the API happened to be rate-limited at that moment.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from brain.hooks import background  # noqa: E402

_SESSION_END = Path(__file__).resolve().parents[1] / "hooks" / "session_end.py"


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on", "  1  "])
def test_guard_recognised_truthy_values(monkeypatch, value):
    monkeypatch.setenv("BRAIN_SKIP_BACKGROUND_JOBS", value)
    assert background.skip_background_jobs() is True


@pytest.mark.parametrize("value", ["", "0", "false", "no", "off", "garbage"])
def test_guard_defaults_to_running_jobs(monkeypatch, value):
    """Unset or non-truthy means normal operation — the guard is opt-IN."""
    monkeypatch.setenv("BRAIN_SKIP_BACKGROUND_JOBS", value)
    assert background.skip_background_jobs() is False


def test_guard_absent_means_jobs_run(monkeypatch):
    monkeypatch.delenv("BRAIN_SKIP_BACKGROUND_JOBS", raising=False)
    assert background.skip_background_jobs() is False


def test_spawn_suppressed_when_guard_set(monkeypatch):
    calls = []
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: calls.append(a))
    monkeypatch.setenv("BRAIN_SKIP_BACKGROUND_JOBS", "1")

    assert background.spawn_background("Reflection", ["/bin/true"]) is False
    assert calls == [], "Popen must not be called when the guard is set"


def test_spawn_runs_when_guard_unset(monkeypatch):
    """The teeth: without the guard the job really is spawned."""
    calls = []
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: calls.append(a))
    monkeypatch.delenv("BRAIN_SKIP_BACKGROUND_JOBS", raising=False)

    assert background.spawn_background("Reflection", ["/bin/true"]) is True
    assert len(calls) == 1, "guard must not suppress jobs by default"


def test_session_end_routes_destructive_jobs_through_the_guard():
    """Structural: a regression to a bare Popen for reflect/cleanup must be caught.

    Both destructive spawns must go through spawn_background. The remaining bare
    Popen calls are the already env-gated opt-in jobs (auto-ingest, fact extract,
    eval), which are non-destructive.
    """
    src = _SESSION_END.read_text()
    assert "from brain.hooks.background import spawn_background" in src
    for script, label in (("run_reflect.py", "Reflection"), ("run_cleanup.py", "Cleanup")):
        idx = src.index(script)
        window = src[idx : idx + 400]
        assert "spawn_background(" in window, (
            f"{script} must be spawned via spawn_background so it can be suppressed; "
            "a bare subprocess.Popen here reintroduces V-08"
        )
        assert label in window
