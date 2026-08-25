"""A9c — deployment parity between the canonical repo and the live hook tree.

The Claude Code hooks in ``~/.claude/settings.json`` execute from
``$BRAIN_LIVE_HOOK_TREE`` (default ``~/Documents/AI``), not from this repo. Those
scripts do ``sys.path.insert(0, Path(__file__).parent.parent.parent)``, which
resolves to that tree's root — so ``from brain.api_client import ...`` inside a
hook loads *that* tree's copy, never this one.

Consequence: editing this repo alone changes MCP-originated saves and silently
leaves hook-originated saves (PostToolUse, session_end — where most golden-path
saves happen) running the old code. The base spec's Success Criterion 1 tests
exactly that path.

**V-16:** the required sync set is **AST-derived** at test time from
:data:`~deploy_parity_trace.HOOK_ENTRY_POINTS`, not a hand-maintained checklist.
Optional :data:`SYNC_SET_REASONS` only improves failure messages.

Skips entirely when the live tree is absent (CI, a fresh clone, another machine),
so it is a guard where it can be one and a no-op everywhere else.
"""
from __future__ import annotations

import filecmp
import os
import sys
from pathlib import Path

import pytest

_TESTS_DIR = Path(__file__).resolve().parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

from deploy_parity_trace import (
    EXCLUDED,
    HOOK_ENTRY_POINTS,
    derive_sync_set,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]

# Human-readable context for known files. AST-derived files without an entry here
# still sync — the message falls back to a generic reason.
SYNC_SET_REASONS: dict[str, str] = {
    "brain/api_client.py": "auto_entities gate + _maybe_extract_entities; without it hooks never extract",
    "brain/ingest/entity_extractor.py": "the extractor itself; absent from the live tree before this ship",
    "brain/ingest/__init__.py": "PEP 562 lazy package init; the eager version costs ~2s of torch per hook process",
    "brain/ingest/transcript.py": "Claude JSONL normalize + groundedness gate; without it recycling invents textbook memories",
    "brain/ingest/payloads.py": "forbid_knowledge_type guard imported by post_tool_use + session_ingest; without it hooks ImportError on every save",
    "brain/hooks/spool.py": "D5 replay fix; without it a spooled save re-extracts on every retry",
    "brain/core/memory.py": "accepts auto_entities; without it BRAIN_BACKEND=python raises TypeError",
    "brain/core/summarizer.py": "format_transcript via normalize; temperature 0; no invent-next-steps prompt",
    "brain/core/session_ingest.py": "substantive-transcript skip + groundedness filter on recycling writes",
    "brain/hooks/session_end.py": "Stop hook entry point; delegates recycling to session_ingest",
    "brain/hooks/post_tool_use.py": "PostToolUse entry point; the main golden-path save site",
    "brain/hooks/background.py": "spawn_background guard imported by session_end (V-08)",
    "brain/hooks/action_state.py": "PostToolUse error/edit pairing state; without it action capture regresses",
    "brain/hooks/corpus_barrier.py": "confidence barrier gate before hook saves",
    "brain/hooks/session_start.py": "detect_project + PROJECT_DIR_MAP used on every hook save",
    "brain/core/db.py": "python-backend SQLite path imported by brain.core.memory",
    "brain/core/embedder.py": "python-backend embed path imported by brain.core.memory",
}

_DEFAULT_REASON = "transitive brain import from hook entry point (AST-derived)"


def _sync_reason(rel: str) -> str:
    return SYNC_SET_REASONS.get(rel, _DEFAULT_REASON)


def _live_tree() -> Path | None:
    root = Path(
        os.environ.get("BRAIN_LIVE_HOOK_TREE", Path.home() / "Documents" / "AI")
    )
    return root if (root / "brain" / "api_client.py").exists() else None


@pytest.fixture(scope="module")
def live_tree() -> Path:
    tree = _live_tree()
    if tree is None:
        pytest.skip("live hook tree not present on this machine")
    return tree


@pytest.fixture(scope="module")
def sync_set() -> set[str]:
    return derive_sync_set(_REPO_ROOT)


def test_hook_entry_points_seed_required_hooks() -> None:
    """INV-DEPLOY-01 teeth: emptying HOOK_ENTRY_POINTS must fail (not vacuously pass)."""
    assert "brain/hooks/session_end.py" in HOOK_ENTRY_POINTS
    assert "brain/hooks/post_tool_use.py" in HOOK_ENTRY_POINTS
    assert len(HOOK_ENTRY_POINTS) >= 2


def test_derive_sync_set_includes_hook_entry_points(sync_set: set[str]) -> None:
    """V-16 teeth: entry points are always required even if nothing imports them."""
    for rel in HOOK_ENTRY_POINTS:
        assert rel in sync_set, f"{rel} missing from AST-derived sync set"


def test_derive_sync_set_excludes_documented_drift(sync_set: set[str]) -> None:
    assert not (sync_set & EXCLUDED)


def test_derive_sync_set_teeth_empty_entry_points() -> None:
    """V-16 teeth: with no entry points, session_end is not auto-required."""
    # session_end is only a seed — nothing else imports it.
    from deploy_parity_trace import derive_sync_set as _derive

    original = HOOK_ENTRY_POINTS
    try:
        import deploy_parity_trace as trace_mod

        trace_mod.HOOK_ENTRY_POINTS = ()
        derived = _derive(_REPO_ROOT)
        assert "brain/hooks/session_end.py" not in derived
    finally:
        import deploy_parity_trace as trace_mod

        trace_mod.HOOK_ENTRY_POINTS = original


def test_derived_files_exist_in_repo(sync_set: set[str]) -> None:
    missing = [r for r in sync_set if not (_REPO_ROOT / r).is_file()]
    assert not missing, f"AST-derived sync set references missing repo files: {missing}"


@pytest.mark.parametrize("rel", sorted(derive_sync_set(_REPO_ROOT)), ids=lambda r: r.replace("/", "."))
def test_sync_set_matches_live_hook_tree(live_tree: Path, rel: str) -> None:
    """Each AST-derived file must be byte-identical in the live hook tree."""
    src, dst = _REPO_ROOT / rel, live_tree / rel
    reason = _sync_reason(rel)
    assert src.exists(), f"{rel} missing from this repo"
    assert dst.exists(), (
        f"{rel} missing from the live hook tree — hooks are running without it.\n"
        f"Reason it matters: {reason}\n"
        f"Fix: cp {src} {dst}"
    )
    assert filecmp.cmp(src, dst, shallow=False), (
        f"{rel} differs between this repo and the live hook tree.\n"
        f"Reason it matters: {reason}\n"
        f"Fix: cp {src} {dst}"
    )
