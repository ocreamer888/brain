#!/usr/bin/env python3
"""Retitle raw markdown chunks and enrich session stubs.

Two strategies:
  PPF Contact Solver (conversation chunks):
    Heuristic extraction of the most meaningful phrase from the content:
    1. Markdown header (# / ## / ### / ####) → cleaned header text
    2. Blockquote title (> **Title**) → bold phrase
    3. Bold phrase at start (**...**) → the phrase
    4. First prose sentence (≥ 10 chars) → truncated to 80 chars
    5. Fall back to existing title (no change)

  Farmaplus (session stubs):
    Content = "Claude Code session: farmaplus | Ended: ..." (no semantic body).
    Title = meaningful user message.
    Fix: prepend title into content so body has semantic signal matching the title.

FTS5 sync: delete + reinsert in memories_fts per changed row.

Usage:
    python3 brain/tools/retitle_chunks.py --dry-run
    python3 brain/tools/retitle_chunks.py
    python3 brain/tools/retitle_chunks.py --project ppf-contact-solver
    python3 brain/tools/retitle_chunks.py --project farmaplus
"""
from __future__ import annotations

import argparse
import re
import sqlite3
from pathlib import Path

DEFAULT_DB = Path(__file__).resolve().parents[1] / "rust" / "brain.db"

# ── helpers ──────────────────────────────────────────────────────────────────

def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def _trunc(s: str, n: int = 80) -> str:
    return s[:77] + "..." if len(s) > n else s


def _strip_markdown(s: str) -> str:
    """Remove `#`, `*`, `_`, backticks, `>` from a string."""
    s = re.sub(r"[#*_`>]", "", s)
    return _clean(s)


# ── title extractor for markdown chunks ──────────────────────────────────────

def _extract_chunk_title(content: str) -> str | None:
    first_lines = content.strip().split("\n")

    for line in first_lines[:8]:
        line = line.strip()
        if not line:
            continue

        # Strip leading bullet/blockquote markers (single dash, single *, >) but not **bold**
        clean_line = re.sub(r"^(?:[-*](?!\*)|>)\s+", "", line).strip()

        # 1. Markdown header: # Title or ## Title
        m = re.match(r"^#{1,4}\s+(.+)", line)
        if m:
            t = _strip_markdown(m.group(1))
            if len(t) >= 6:
                return _trunc(t)

        # 2. Blockquote with bold: > **Title**
        m = re.match(r"^>\s*\*\*(.+?)\*\*", line)
        if m:
            t = _clean(m.group(1))
            if len(t) >= 6:
                return _trunc(t)

        # 3. Bold phrase + optional continuation: **Label**: rest of sentence
        m = re.match(r"^\*\*(.+?)\*\*[:\s]+(.+)", clean_line)
        if m:
            label = _clean(m.group(1))
            rest = _clean(m.group(2).split(".")[0])  # up to first period
            combined = f"{label}: {rest}" if rest and len(rest) > 4 else label
            if len(combined) >= 8:
                return _trunc(combined)

        # 4. Bold phrase alone: **Title**
        m = re.match(r"^\*\*(.+?)\*\*", clean_line)
        if m:
            phrase = _clean(m.group(1))
            if len(phrase) >= 8:
                return _trunc(phrase)

        # 5. Plain prose sentence (not code block, HTML, or table)
        if not re.match(r"^[`<\[\|{]", clean_line) and len(clean_line) >= 15:
            # Take up to first sentence end
            sentence = re.split(r"[.!?]", clean_line)[0]
            sentence = _clean(sentence)
            if len(sentence) >= 10:
                return _trunc(sentence)

    return None


# ── FTS5 sync ─────────────────────────────────────────────────────────────────

def _sync_fts(conn: sqlite3.Connection, memory_id: str) -> None:
    conn.execute(
        "DELETE FROM memories_fts WHERE rowid=(SELECT rowid FROM memories WHERE id=?)",
        (memory_id,),
    )
    conn.execute(
        "INSERT INTO memories_fts(rowid, id, content, title) "
        "SELECT rowid, id, content, title FROM memories WHERE id=?",
        (memory_id,),
    )


# ── PPF retitler ─────────────────────────────────────────────────────────────

def retitle_ppf(conn: sqlite3.Connection, dry_run: bool) -> dict:
    rows = conn.execute(
        "SELECT id, content, title FROM memories "
        "WHERE project = 'ppf-contact-solver' AND type = '\"conversation\"'"
    ).fetchall()

    stats = {"updated": 0, "skipped": 0, "unchanged": 0}
    samples: list[tuple[str, str, str]] = []

    for mid, content, old_title in rows:
        new_title = _extract_chunk_title(content or "")
        if not new_title:
            stats["skipped"] += 1
            continue
        if new_title == (old_title or "").strip():
            stats["unchanged"] += 1
            continue
        samples.append((mid, old_title or "", new_title))
        if not dry_run:
            conn.execute("UPDATE memories SET title=? WHERE id=?", (new_title, mid))
            _sync_fts(conn, mid)
            stats["updated"] += 1

    if dry_run:
        stats["updated"] = len(samples)
        print(f"\n[DRY-RUN] ppf-contact-solver: {len(samples)} would be retitled")
        print(f"  Sample (first 8):")
        for _, old, new in samples[:8]:
            print(f"  OLD: {old!r}")
            print(f"  NEW: {new!r}")
            print()
    return stats


# ── Farmaplus retitler ────────────────────────────────────────────────────────

def retitle_farmaplus(conn: sqlite3.Connection, dry_run: bool) -> dict:
    """Retitle session stubs to 'N-msg session — project (date)' so title embedding
    aligns with the body ('Claude Code session: ... | Total messages: N').

    The current titles are user messages (semantically unrelated to the body),
    so kfold title-as-query fails. Body-matching titles fix this without re-embedding.
    """
    import re as _re

    rows = conn.execute(
        "SELECT id, content, title FROM memories "
        "WHERE project = 'farmaplus' AND type = '\"conversation\"'"
    ).fetchall()

    stats = {"updated": 0, "skipped": 0, "unchanged": 0}
    samples: list[tuple[str, str, str]] = []

    for mid, content, old_title in rows:
        if not content:
            stats["skipped"] += 1
            continue
        # Extract date and message count from session-stub body
        date_m = _re.search(r"Ended:\s*(\d{4}-\d{2}-\d{2})", content)
        msg_m = _re.search(r"Total messages:\s*(\d+)", content)
        if not date_m or not msg_m:
            stats["skipped"] += 1
            continue
        date_str = date_m.group(1)
        msg_count = msg_m.group(1)
        new_title = f"{msg_count}-msg session — farmaplus ({date_str})"
        if new_title == (old_title or "").strip():
            stats["unchanged"] += 1
            continue
        samples.append((mid, old_title or "", new_title))
        if not dry_run:
            conn.execute("UPDATE memories SET title=? WHERE id=?", (new_title, mid))
            _sync_fts(conn, mid)
            stats["updated"] += 1

    if dry_run:
        stats["updated"] = len(samples)
        print(f"\n[DRY-RUN] farmaplus: {len(samples)} would be retitled")
        print(f"  Sample (first 4):")
        for _, old, new in samples[:4]:
            print(f"  OLD: {old[:80]!r}")
            print(f"  NEW: {new!r}")
            print()
    return stats


# ── main ─────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument(
        "--project",
        choices=["ppf-contact-solver", "farmaplus", "all"],
        default="all",
        help="Which project to fix (default: all)",
    )
    args = parser.parse_args(argv)

    conn = sqlite3.connect(str(args.db))
    conn.execute("PRAGMA journal_mode=WAL")

    run_ppf = args.project in ("ppf-contact-solver", "all")
    run_farmaplus = args.project in ("farmaplus", "all")  # noqa: SIM118

    if run_ppf:
        print("=== ppf-contact-solver: heuristic retitle ===")
        ppf_stats = retitle_ppf(conn, args.dry_run)
        print(f"  updated={ppf_stats['updated']} skipped={ppf_stats['skipped']} unchanged={ppf_stats['unchanged']}")

    if run_farmaplus:
        print("\n=== farmaplus: title alignment ===")
        fp_stats = retitle_farmaplus(conn, args.dry_run)
        print(f"  updated={fp_stats['updated']} skipped={fp_stats['skipped']} unchanged={fp_stats['unchanged']}")

    if not args.dry_run:
        conn.commit()
        print("\nCommitted.")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
