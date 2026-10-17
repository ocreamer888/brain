"""Registered temporary breaks for teeth_check --auto-probe.

Each probe mutates one production file in a way that must fail the invariant's
tests, then is restored by teeth_check try/finally. Keep probes minimal.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class TeethProbe:
    invariant_id: str
    relative_file: str
    old: str
    new: str
    rationale: str


PROBES: dict[str, TeethProbe] = {
    "INV-HOOK-01": TeethProbe(
        invariant_id="INV-HOOK-01",
        relative_file="brain/hooks/background.py",
        old="    if skip_background_jobs():\n",
        new="    if False:  # BRAIN_FORGE_TEETH_PROBE — must fail tests\n",
        rationale="spawn_background ignores BRAIN_SKIP_BACKGROUND_JOBS → V-08 guard toothless",
    ),
    "INV-SESSION-01": TeethProbe(
        invariant_id="INV-SESSION-01",
        relative_file="brain/core/session_ingest.py",
        old=(
            "    if not has_substantive_transcript(messages):\n"
            "        print(\n"
            '            f"[session_ingest] skipped recycling: no substantive transcript "\n'
        ),
        new=(
            "    if False:  # BRAIN_FORGE_TEETH_PROBE\n"
            "        print(\n"
            '            f"[session_ingest] skipped recycling: no substantive transcript "\n'
        ),
        rationale="empty/meta transcripts reach LLM recycling",
    ),
    "INV-ENTITY-01": TeethProbe(
        invariant_id="INV-ENTITY-01",
        relative_file="brain/ingest/entity_extractor.py",
        old="        if _looks_like_secret(name) or _looks_like_junk(name):\n",
        new="        if False or _looks_like_junk(name):  # BRAIN_FORGE_TEETH_PROBE\n",
        rationale="secret-shaped tokens survive _clean_entities",
    ),
    "INV-ENTITY-02": TeethProbe(
        invariant_id="INV-ENTITY-02",
        relative_file="brain/ingest/entity_extractor.py",
        old=(
            '    """Mechanical junk: versions, .classes, foo(), Tailwind utilities (V-07)."""\n'
            "    n = name.strip()\n"
        ),
        new=(
            '    """Mechanical junk: versions, .classes, foo(), Tailwind utilities (V-07)."""\n'
            "    return False  # BRAIN_FORGE_TEETH_PROBE\n"
            "    n = name.strip()\n"
        ),
        rationale="junk/hub tokens survive _looks_like_junk",
    ),
    "INV-DEPLOY-01": TeethProbe(
        invariant_id="INV-DEPLOY-01",
        relative_file="brain/tests/deploy_parity_trace.py",
        old=(
            "HOOK_ENTRY_POINTS: tuple[str, ...] = (\n"
            '    "brain/hooks/post_tool_use.py",\n'
            '    "brain/hooks/session_end.py",\n'
            ")\n"
        ),
        new="HOOK_ENTRY_POINTS: tuple[str, ...] = ()  # BRAIN_FORGE_TEETH_PROBE\n",
        rationale="empty HOOK_ENTRY_POINTS drops session_end from sync set",
    ),
    "INV-INGEST-01": TeethProbe(
        invariant_id="INV-INGEST-01",
        relative_file="brain/ingest/__init__.py",
        old="from typing import TYPE_CHECKING\n",
        new=(
            "from typing import TYPE_CHECKING\n"
            "import torch  # BRAIN_FORGE_TEETH_PROBE — eager torch on import brain.ingest\n"
        ),
        rationale="import brain.ingest pulls torch at package import",
    ),
}


def probe_path(probe: TeethProbe) -> Path:
    return REPO_ROOT / probe.relative_file
