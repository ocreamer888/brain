"""
Retitle conversation memories with meaningful titles derived from content.

Four cases (processed in order):
  A. Session blobs with pipe-joined [user] marker:
     Extract first [user] message.
     → "{first_80_chars_of_user_msg} — {project}"

  B. Blobs with 'User:\\n\\nA:' format (no pipe structure):
     Extract assistant response after 'A: '.
     → "{first_80_chars} — {project}"

  C. Header-only sessions (no dialogue, just metadata):
     Derive from header: "N-msg session — {project} ({date})"

  D. Rich summaries (blank/null title, no session markers):
     Extract first segment before ' | ' from content.
     → first 80 chars of that segment

FTS5 sync: update memories, delete+reinsert in memories_fts per row.

Usage:
    python3 brain/tools/retitle_conversations.py [--dry-run] [--db PATH]
"""
from __future__ import annotations

import argparse
import re
import sqlite3
from pathlib import Path

DEFAULT_DB = Path(__file__).resolve().parents[1] / "rust" / "brain.db"


def _clean(s: str) -> str:
    return " ".join(s.split())


def _truncate(s: str, n: int = 80) -> str:
    return s[:77] + "..." if len(s) > n else s


def _extract_user_msg_title(content: str, project: str) -> str | None:
    """Case A: pipe-joined content with | [user] marker."""
    if "| [user] " not in content:
        return None
    user_part = content.split("| [user] ", 1)[1]
    first_msg = _clean(user_part.split(" | ")[0])
    if not first_msg:
        return None
    return f"{_truncate(first_msg)} — {project}"


def _extract_assistant_reply_title(content: str, project: str) -> str | None:
    """Case B: 'User:\\n\\nAssistant: ...' format — extract assistant reply."""
    if not content.startswith("User:"):
        return None
    # Match 'Assistant: ' (full word) or short 'A: '
    match = re.search(r"\b(?:Assistant|A):\s+(.+)", content, re.DOTALL)
    if not match:
        return None
    reply = _clean(match.group(1).split("\n\n")[0])
    if len(reply) < 5:
        return None
    return f"{_truncate(reply)} — {project}"


def _extract_header_title(content: str, project: str) -> str | None:
    """Case C: header-only session blob — derive from metadata."""
    # Format: "Claude Code session: proj | Ended: DATE | ... | Total messages: N"
    date_match = re.search(r"Ended:\s*(\d{4}-\d{2}-\d{2})", content)
    msg_match = re.search(r"Total messages:\s*(\d+)", content)
    date_str = date_match.group(1) if date_match else "unknown date"
    msg_count = msg_match.group(1) if msg_match else "?"
    return f"{msg_count}-msg session — {project} ({date_str})"


def _extract_summary_title(content: str) -> str | None:
    """Case D: rich summary — first segment before ' | '."""
    first_seg = _clean(content.split(" | ")[0])
    if not first_seg or len(first_seg) < 10:
        return None
    return _truncate(first_seg)


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


def _pick_title(content: str, project: str) -> str | None:
    """Route content to the right extractor."""
    t = _extract_user_msg_title(content, project)
    if t:
        return t
    t = _extract_assistant_reply_title(content, project)
    if t:
        return t
    # Header-only session blob
    if content.startswith("Claude Code session:") or content.startswith("Claude Code session"):
        return _extract_header_title(content, project)
    # Rich summary
    return _extract_summary_title(content)


def run_retitle(db_path: Path = DEFAULT_DB, dry_run: bool = False) -> dict:
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")

    stats = {
        "updated": 0,
        "skipped_no_title": 0,
        "unchanged_already_good": 0,
    }

    # All conversations that still have Session/User:/blank titles
    rows = conn.execute(
        "SELECT id, content, project, title FROM memories "
        "WHERE type='\"conversation\"' AND ("
        "  title IS NULL OR title = '' "
        "  OR title LIKE 'Session %' "
        "  OR title LIKE 'User: Assistant:%' "
        "  OR title LIKE 'User: %'"
        ")"
    ).fetchall()
    print(f"Conversations needing retitle: {len(rows)}")

    samples = []
    for memory_id, content, project, old_title in rows:
        new_title = _pick_title(content, project)
        if not new_title:
            stats["skipped_no_title"] += 1
            continue
        if new_title == old_title:
            stats["unchanged_already_good"] += 1
            continue
        samples.append((memory_id, old_title, new_title))
        if not dry_run:
            conn.execute("UPDATE memories SET title=? WHERE id=?", (new_title, memory_id))
            _sync_fts(conn, memory_id)
            stats["updated"] += 1

    if not dry_run:
        conn.commit()
        print("Committed.")
    else:
        stats["updated"] = len(samples)
        print(f"\n[DRY RUN] Sample retitles ({min(10, len(samples))} of {len(samples)}):")
        for mid, old, new in samples[:10]:
            print(f"  OLD: {old!r}")
            print(f"  NEW: {new!r}")
            print()

    conn.close()
    print(f"\nStats: {stats}")
    return stats


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    args = parser.parse_args()
    run_retitle(db_path=args.db, dry_run=args.dry_run)
