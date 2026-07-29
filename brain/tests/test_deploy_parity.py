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

A9c originally prescribed a two-file ``cp``. Tracing the hooks' transitive import
graph showed that list was incomplete: six files participate. This test pins the
real set so the sync cannot rot silently.

Skips entirely when the live tree is absent (CI, a fresh clone, another machine),
so it is a guard where it can be one and a no-op everywhere else.
"""
from __future__ import annotations

import filecmp
import os
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]

# Every file that must be byte-identical in the live hook tree, and why.
SYNC_SET: dict[str, str] = {
    "brain/api_client.py": "auto_entities gate + _maybe_extract_entities; without it hooks never extract",
    "brain/ingest/entity_extractor.py": "the extractor itself; absent from the live tree before this ship",
    "brain/ingest/__init__.py": "PEP 562 lazy package init; the eager version costs ~2s of torch per hook process",
    "brain/ingest/fact_curator.py": "auto_entities=False on the fact path; without it facts double-extract",
    "brain/hooks/spool.py": "D5 replay fix; without it a spooled save re-extracts on every retry",
    "brain/core/memory.py": "accepts auto_entities; without it BRAIN_BACKEND=python raises TypeError",
}

# Deliberately NOT synced, with the reason. Guards against someone "helpfully"
# widening the set: these diverge for reasons unrelated to this ship.
EXCLUDED: dict[str, str] = {
    "brain/config.py": "pre-existing OBSIDIAN_VAULT divergence; each tree's vault path is correct for itself",
    "brain/tools/mcp_eval.py": "not on the hook import path; affects eval runs only",
}


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


@pytest.mark.parametrize("rel", sorted(SYNC_SET), ids=lambda r: r.replace("/", "."))
def test_sync_set_matches_live_hook_tree(live_tree: Path, rel: str) -> None:
    """Each synced file must be byte-identical in the live hook tree."""
    src, dst = _REPO_ROOT / rel, live_tree / rel
    assert src.exists(), f"{rel} missing from this repo"
    assert dst.exists(), (
        f"{rel} missing from the live hook tree — hooks are running without it.\n"
        f"Reason it matters: {SYNC_SET[rel]}\n"
        f"Fix: cp {src} {dst}"
    )
    assert filecmp.cmp(src, dst, shallow=False), (
        f"{rel} differs between this repo and the live hook tree.\n"
        f"Reason it matters: {SYNC_SET[rel]}\n"
        f"Fix: cp {src} {dst}"
    )


def test_excluded_files_are_documented() -> None:
    """SYNC_SET and EXCLUDED must not overlap — a file is one or the other."""
    assert not (set(SYNC_SET) & set(EXCLUDED))


def test_sync_set_files_exist_in_repo() -> None:
    """Catches a rename in this repo that would silently drop a file from the set."""
    missing = [r for r in SYNC_SET if not (_REPO_ROOT / r).exists()]
    assert not missing, f"SYNC_SET references files that no longer exist: {missing}"
