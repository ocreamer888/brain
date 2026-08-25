"""Background-job spawning for hooks, with a test/suppression guard.

Lives in its own module because `session_end.py` is a *script* — its body runs at
import time, so anything defined there cannot be unit-tested. See V-08 in
docs/superpowers/specs/2026-07-28-durable-entity-linking-verification-findings.md.
"""
from __future__ import annotations

import os
import subprocess
import sys

_TRUTHY = {"1", "true", "yes", "on"}


def skip_background_jobs() -> bool:
    """True when background maintenance must not run (``BRAIN_SKIP_BACKGROUND_JOBS``).

    The Stop hook otherwise spawns ``run_reflect.py`` (``POST /reflect``, which
    DELETES memories during consolidation — its log shows -12/-7/-4 entries) and
    ``run_cleanup.py`` (BVH/title dedup with real ``delete_memories`` calls, plus
    noise auto-delete every 20th session). Both always target the real API:
    ``_base_url()`` ignores where the script lives.

    That made the hook impossible to integration-test without risking production
    data — a verification run triggered a real consolidation pass and only avoided
    deleting anything because the API happened to be rate-limited at that moment.

    Set this to exercise the hook's own logic (transcript parsing, summary save,
    edit-group flush) with the destructive maintenance suppressed.
    """
    return os.environ.get("BRAIN_SKIP_BACKGROUND_JOBS", "").strip().lower() in _TRUTHY


def spawn_background(label: str, args: list[str], **popen_kw) -> bool:
    """Spawn a detached background job unless suppressed. True if actually spawned."""
    if skip_background_jobs():
        print(f"[BRAIN] {label} skipped (BRAIN_SKIP_BACKGROUND_JOBS).", file=sys.stderr)
        return False
    subprocess.Popen(args, **popen_kw)
    print(f"[BRAIN] {label} scheduled in background.", file=sys.stderr)
    return True
