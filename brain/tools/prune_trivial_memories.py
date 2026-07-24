#!/usr/bin/env python3
"""
Scan the brain corpus for trivial / noise memories and optionally delete them.

Targets three known noise classes:
  1. Session summaries with "no actionable / no decisions / empty session" prose
     that slipped in before the session_end quality gate existed.
  2. Reflection "pattern" memories that are LLM meta-commentary
     ("Memories 0 and 1 relate to...", "These memories cover...").
  3. Short test / bootstrap memories ("test memory", content < 30 chars).

Usage:
    # Report only — prints counts and samples, no changes
    python3 brain/tools/prune_trivial_memories.py

    # Apply — actually delete matches in batches
    python3 brain/tools/prune_trivial_memories.py --apply

    # Narrow to one source
    python3 brain/tools/prune_trivial_memories.py --source reflection
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from brain.api_client import delete_memories, list_memories


TRIVIAL_CONTENT_MARKERS = (
    "no actionable",
    "no code changes",
    "no significant",
    "no tasks were",
    "no decisions",
    "no meaningful",
    "empty session",
    "remained default",
    "test memory",
)

REFLECTION_META_MARKERS = (
    "memories 0",
    "memory 0",
    "these memories",
    "the memories",
    "do not fit",
    "no clear pattern",
    "are related to",
)

MIN_CONTENT_CHARS = 30
DELETE_BATCH = 100


def classify(item: dict) -> str | None:
    """Return a reason string if the item is trivial, else None."""
    content = (item.get("content") or "").strip()
    source = item.get("source") or ""

    if len(content) < MIN_CONTENT_CHARS:
        return "too_short"

    lowered = content.lower()

    if source == "reflection":
        if any(m in lowered for m in REFLECTION_META_MARKERS):
            return "reflection_meta"

    if any(m in lowered for m in TRIVIAL_CONTENT_MARKERS):
        return "trivial_content"

    return None


def scan(source: str | None) -> tuple[list[dict], dict[str, int]]:
    """Pull all memories (optionally filtered by source), classify them."""
    offset = 0
    limit = 2000
    flagged: list[dict] = []
    reasons: dict[str, int] = {}

    while True:
        page = list_memories(source=source, limit=limit, offset=offset)
        items = page.get("items", [])
        if not items:
            break
        for it in items:
            reason = classify(it)
            if reason:
                it["_reason"] = reason
                flagged.append(it)
                reasons[reason] = reasons.get(reason, 0) + 1
        offset += len(items)
        if offset >= page.get("total", 0):
            break

    return flagged, reasons


def preview(flagged: list[dict], k: int = 10) -> None:
    print(f"\nPreview ({min(k, len(flagged))} of {len(flagged)}):")
    for it in flagged[:k]:
        preview_text = (it.get("content") or "").replace("\n", " ")[:120]
        print(
            f"  [{it['_reason']:<18}] {it['source']:<20} "
            f"{it['timestamp'][:10]}  {preview_text}"
        )


def apply_deletes(flagged: list[dict]) -> int:
    ids = [it["id"] for it in flagged]
    total = 0
    for i in range(0, len(ids), DELETE_BATCH):
        batch = ids[i : i + DELETE_BATCH]
        deleted = delete_memories(batch)
        total += deleted
        print(f"  deleted batch {i // DELETE_BATCH + 1}: {deleted} memories")
    return total


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually delete flagged memories (default: dry-run)",
    )
    parser.add_argument(
        "--source",
        default=None,
        help="Filter by source (e.g. reflection, claude_code_session). Default: all sources.",
    )
    args = parser.parse_args()

    print(f"Scanning{' source=' + args.source if args.source else ''}...")
    flagged, reasons = scan(args.source)

    if not flagged:
        print("No trivial memories found.")
        return 0

    print(f"\nFound {len(flagged)} trivial memories:")
    for reason, count in sorted(reasons.items(), key=lambda x: -x[1]):
        print(f"  {reason:<18}  {count}")

    preview(flagged, k=15)

    if not args.apply:
        print("\nDry-run only. Re-run with --apply to delete.")
        return 0

    print(f"\nDeleting {len(flagged)} memories in batches of {DELETE_BATCH}...")
    total = apply_deletes(flagged)
    print(f"\nDone. Deleted {total} memories.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
