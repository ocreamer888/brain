#!/usr/bin/env python3
"""Extract and curate facts from multiple sources.

Modes:
  --file PATH        Single session JSON (called by session_end hook)
  --all              All unprocessed Claude Code session exports
  --from-perplexity  All unprocessed Perplexity export threads
  --from-db          Memories already in brain.db (use --source to filter)
  --from-cursor-db   Cursor chat history from a vscdb SQLite file

Common flags:
  --project PROJ     Filter by project name (--all / --from-db)
  --source SRC       Filter by source tag (--from-db)
  --cursor-db PATH   Path to state.vscdb.clean (default: cursor-recovery-backup/state.vscdb.clean)
  --limit N          Cap number of items
  --dry-run          Print what would happen, skip saves
  --batch-id ID      Reuse an existing batch ID (retries)

Regression gate (G5, 2026-11-03): the four bulk modes (--all/--from-db/
--from-perplexity/--from-cursor-db) automatically measure recall on the
trusted gold set (brain/eval/gold_mined.jsonl) before and after the run,
and auto-rollback the batch if recall drops more than 0.05 -- see
regression_gate()/the comment block above main(). Skipped on --dry-run or
--limit <= 20 (a canary shouldn't pay for a full gold pass), and NOT
applied to --file (small, frequent, session_end-hook-triggered batches --
the per-batch risk is low and a full eval pass per session is the wrong
cost). To roll back a batch manually instead (e.g. after noticing a problem
later): rollback_batch(db_path, batch_id) in brain/tools/retrieval_eval_kfold.py.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))

from brain.ingest.fact_extractor import extract_facts
from brain.ingest.fact_curator import curate_facts

_BOOTSTRAP = Path(__file__).resolve().parents[1] / "bootstrap"
SESSIONS_DIR = _BOOTSTRAP / "sessions_export"
PERPLEXITY_DIR = _BOOTSTRAP / "perplexity_exports"

CHECKPOINT_SESSIONS = _BOOTSTRAP / "checkpoint_fact_backfill.json"
CHECKPOINT_PERPLEXITY = _BOOTSTRAP / "checkpoint_fact_perplexity.json"
CHECKPOINT_DB = _BOOTSTRAP / "checkpoint_fact_db.json"
CHECKPOINT_CURSOR = _BOOTSTRAP / "checkpoint_fact_cursor.json"

_CURSOR_RECOVERY_DB = Path(__file__).resolve().parents[2] / "cursor-recovery-backup" / "state.vscdb.clean"

MIN_EPISODE_CHARS = 200


# ---------------------------------------------------------------------------
# Text extraction helpers
# ---------------------------------------------------------------------------

def _extract_text(message: dict) -> str:
    # Two formats: nested {"message": {"content": ...}} or flat {"content": ...}
    content = message.get("message", {}).get("content") or message.get("content", "")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
        return " ".join(parts).strip()
    return ""


_SKIP_PREFIXES = ("<local-command", "<command-name>", "<timestamp>", "<system-reminder")


def _build_episode_text(messages: list[dict], max_chars: int = 6000) -> str:
    parts: list[str] = []
    total = 0
    for m in messages:
        role = m.get("role") or m.get("type", "")
        if role not in ("user", "assistant"):
            continue
        text = _extract_text(m)
        if not text or len(text) < 30:
            continue
        if any(text.startswith(p) for p in _SKIP_PREFIXES):
            continue
        prefix = "User" if role == "user" else "Assistant"
        snippet = f"{prefix}: {text[:800]}"
        if total + len(snippet) > max_chars:
            break
        parts.append(snippet)
        total += len(snippet)
    return "\n\n".join(parts)


def _build_perplexity_episode(thread: dict, max_chars: int = 8000) -> str:
    """Build episode text from a Perplexity thread export."""
    title = thread.get("title", "")
    messages = thread.get("messages", [])
    parts: list[str] = []
    if title:
        parts.append(f"Thread: {title}")
    total = len(parts[0]) if parts else 0

    for m in messages:
        content = m.get("content", "")
        # full_text role = the complete thread text (use it directly)
        if m.get("role") == "full_text":
            snippet = str(content)[:max_chars]
            parts.append(snippet)
            break
        if not isinstance(content, str):
            content = str(content)
        role = m.get("role", "")
        if role == "user":
            prefix = "Question"
        elif role == "assistant":
            prefix = "Answer"
        else:
            continue
        snippet = f"{prefix}: {content[:1200]}"
        if total + len(snippet) > max_chars:
            break
        parts.append(snippet)
        total += len(snippet)

    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Checkpoint I/O
# ---------------------------------------------------------------------------

def load_checkpoint(path: Path | None = None) -> set[str]:
    cp = path or CHECKPOINT_SESSIONS
    if cp.exists():
        return set(json.loads(cp.read_text()).get("processed_ids", []))
    return set()


def save_checkpoint(done: set[str], path: Path | None = None) -> None:
    cp = path or CHECKPOINT_SESSIONS
    cp.write_text(json.dumps({"processed_ids": sorted(done)}))


# ---------------------------------------------------------------------------
# Core processing (shared by all modes)
# ---------------------------------------------------------------------------

def _run_extraction(
    episode_text: str,
    project: str,
    session_id: str,
    batch_id: str,
    dry_run: bool,
    label: str,
    source_event_time: str | None = None,
) -> tuple[int, int, int]:
    if len(episode_text) < MIN_EPISODE_CHARS:
        return 0, 0, 0

    if dry_run:
        print(f"  [dry-run] {label}: {len(episode_text)} chars, project={project}")
        return 0, 0, 0

    try:
        facts = extract_facts(
            episode_text=episode_text,
            project=project,
            session_id=session_id,
            parent_id=None,
        )
    except Exception as e:
        print(f"  [backfill] extract_facts failed for {label}: {e}", file=sys.stderr)
        return 0, 0, 0

    if not facts:
        return 0, 0, 0

    result = curate_facts(
        new_facts=facts,
        project=project,
        batch_id=batch_id,
        session_id=session_id,
        source_event_time=source_event_time,
    )
    return len(result.added), len(result.updated), len(result.merged)


def process_session(
    session: dict,
    batch_id: str,
    dry_run: bool = False,
) -> tuple[int, int, int]:
    project     = session.get("project") or "general"
    session_id  = session.get("session_id") or ""
    ended_at    = session.get("ended_at") or None
    messages    = session.get("messages", [])
    episode_text = _build_episode_text(messages)
    return _run_extraction(
        episode_text, project, session_id, batch_id, dry_run,
        f"session/{project}",
        source_event_time=ended_at,
    )


# ---------------------------------------------------------------------------
# Mode: single file
# ---------------------------------------------------------------------------

def run_single(path: Path, batch_id: str, dry_run: bool) -> None:
    session = json.loads(path.read_text())
    a, u, m = process_session(session, batch_id, dry_run)
    project = session.get("project", "?")
    print(f"[backfill] {path.name} project={project} added={a} updated={u} merged={m} batch={batch_id}")


# ---------------------------------------------------------------------------
# Mode: --all (Claude Code session exports)
# ---------------------------------------------------------------------------

def run_all(
    project_filter: str | None,
    limit: int | None,
    dry_run: bool,
    batch_id: str,
) -> None:
    done_ids = load_checkpoint(CHECKPOINT_SESSIONS)
    files = sorted(SESSIONS_DIR.glob("*.json"))

    to_process: list[tuple[Path, str]] = []
    seen_ids: set[str] = set()
    for f in files:
        try:
            data = json.loads(f.read_text())
            sid = data.get("session_id") or f.stem
            proj = data.get("project") or "general"
        except Exception:
            continue
        if project_filter and proj != project_filter:
            continue
        if sid in done_ids or sid in seen_ids:
            continue
        to_process.append((f, sid))
        seen_ids.add(sid)

    if limit:
        to_process = to_process[:limit]

    print(f"[backfill] {len(to_process)} sessions to process (batch={batch_id})", file=sys.stderr)
    total_added = total_updated = total_merged = 0

    for f, sid in to_process:
        try:
            session = json.loads(f.read_text())
            a, u, m = process_session(session, batch_id, dry_run)
            total_added += a
            total_updated += u
            total_merged += m
            proj = session.get("project", "?")
            if a or u or m:
                print(f"  {f.name} project={proj} +{a} ~{u} ={m}", file=sys.stderr)
        except Exception as e:
            print(f"  [backfill] {f.name} failed: {e}", file=sys.stderr)
        if not dry_run:
            done_ids.add(sid)
            save_checkpoint(done_ids, CHECKPOINT_SESSIONS)

    print(f"[backfill] done — added={total_added} updated={total_updated} merged={total_merged} batch={batch_id}")


# ---------------------------------------------------------------------------
# Mode: --from-perplexity
# ---------------------------------------------------------------------------

def run_perplexity(
    limit: int | None,
    dry_run: bool,
    batch_id: str,
) -> None:
    done_ids = load_checkpoint(CHECKPOINT_PERPLEXITY)
    files = sorted(PERPLEXITY_DIR.glob("*.json"))

    to_process = [f for f in files if f.stem not in done_ids]
    if limit:
        to_process = to_process[:limit]

    print(f"[backfill/perplexity] {len(to_process)} threads to process (batch={batch_id})", file=sys.stderr)
    total_added = total_updated = total_merged = 0

    for f in to_process:
        try:
            thread = json.loads(f.read_text())
            title = thread.get("title", f.stem)[:80]
            episode_text = _build_perplexity_episode(thread)
            # Use "perplexity" as project so facts are scoped correctly
            a, u, m = _run_extraction(
                episode_text=episode_text,
                project="perplexity",
                session_id=f.stem,
                batch_id=batch_id,
                dry_run=dry_run,
                label=f"perplexity/{title}",
            )
            total_added += a
            total_updated += u
            total_merged += m
            if a or u or m:
                print(f"  {f.name[:60]} +{a} ~{u} ={m}", file=sys.stderr)
        except Exception as e:
            print(f"  [backfill/perplexity] {f.name} failed: {e}", file=sys.stderr)
        if not dry_run:
            done_ids.add(f.stem)
            save_checkpoint(done_ids, CHECKPOINT_PERPLEXITY)

    print(f"[backfill/perplexity] done — added={total_added} updated={total_updated} merged={total_merged} batch={batch_id}")


# ---------------------------------------------------------------------------
# Mode: --from-cursor-db (Cursor vscdb recovery file)
# ---------------------------------------------------------------------------

def _build_cursor_episode(bubbles: list[dict], max_chars: int = 6000) -> str:
    """Build episode text from a list of Cursor bubbles sorted by rowid."""
    parts: list[str] = []
    total = 0
    for b in bubbles:
        btype = b.get("type")
        text = (b.get("text") or "").strip()
        if not text or len(text) < 30:
            continue
        prefix = "User" if btype == 1 else "Assistant"
        snippet = f"{prefix}: {text[:800]}"
        if total + len(snippet) > max_chars:
            break
        parts.append(snippet)
        total += len(snippet)
    return "\n\n".join(parts)


_CURSOR_MARKERS = {"src", "app", "lib", "components", "pages", "utils", "hooks"}


def _infer_cursor_project(bubbles: list[dict]) -> str:
    """Best-effort project name from relevantFiles paths."""
    for b in bubbles:
        for path_str in b.get("relevantFiles", []):
            parts = Path(path_str).parts
            for i, part in enumerate(parts):
                if part in _CURSOR_MARKERS and i > 0:
                    return parts[i - 1]
    return "cursor"


def run_from_cursor_db(
    db_path: Path,
    limit: int | None,
    dry_run: bool,
    batch_id: str,
) -> None:
    if not db_path.exists():
        print(f"error: cursor db not found: {db_path}", file=sys.stderr)
        return

    done_ids = load_checkpoint(CHECKPOINT_CURSOR)

    conn = sqlite3.connect(str(db_path), timeout=30)
    conn.row_factory = sqlite3.Row

    # Get all distinct composer IDs not yet processed
    rows = conn.execute(
        "SELECT DISTINCT substr(key, 10, instr(substr(key,10), ':')-1) as composer_id "
        "FROM cursorDiskKV WHERE key LIKE 'bubbleId:%'"
    ).fetchall()
    composer_ids = [r["composer_id"] for r in rows if r["composer_id"] not in done_ids]
    if limit:
        composer_ids = composer_ids[:limit]

    print(f"[backfill/cursor] {len(composer_ids)} conversations to process (batch={batch_id})", file=sys.stderr)
    total_added = total_updated = total_merged = 0

    for composer_id in composer_ids:
        bubble_rows = conn.execute(
            "SELECT value FROM cursorDiskKV WHERE key LIKE ? ORDER BY rowid",
            (f"bubbleId:{composer_id}:%",),
        ).fetchall()

        bubbles: list[dict] = []
        for row in bubble_rows:
            try:
                bubbles.append(json.loads(row["value"]))
            except Exception:
                continue

        project = _infer_cursor_project(bubbles)
        episode_text = _build_cursor_episode(bubbles)

        try:
            a, u, m = _run_extraction(
                episode_text=episode_text,
                project=project,
                session_id=composer_id,
                batch_id=batch_id,
                dry_run=dry_run,
                label=f"cursor/{project}/{composer_id[:8]}",
            )
            total_added += a
            total_updated += u
            total_merged += m
            if a or u or m:
                print(f"  {composer_id[:8]} project={project} +{a} ~{u} ={m}", file=sys.stderr)
        except Exception as e:
            print(f"  [backfill/cursor] {composer_id[:8]} failed: {e}", file=sys.stderr)
        if not dry_run:
            done_ids.add(composer_id)
            save_checkpoint(done_ids, CHECKPOINT_CURSOR)

    conn.close()
    print(f"[backfill/cursor] done — added={total_added} updated={total_updated} merged={total_merged} batch={batch_id}")


# ---------------------------------------------------------------------------
# Mode: --from-db (obsidian, cursor_history, etc.)
# ---------------------------------------------------------------------------

def run_from_db(
    source_filter: str,
    type_filter: str | None,
    project_filter: str | None,
    limit: int | None,
    dry_run: bool,
    batch_id: str,
) -> None:
    db_path = str(_resolve_db_path())

    done_ids = load_checkpoint(CHECKPOINT_DB)

    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row

    conditions = [f"source = '\"{ source_filter }\"'"]
    if type_filter:
        conditions.append(f"type = '\"{ type_filter }\"'")
    if project_filter:
        conditions.append(f"project = '{project_filter}'")
    where = " AND ".join(conditions)

    rows = conn.execute(f"SELECT id, content, project FROM memories WHERE {where}").fetchall()
    conn.close()

    to_process = [r for r in rows if r["id"] not in done_ids]
    if limit:
        to_process = to_process[:limit]

    tag = f"db/{source_filter}"
    print(f"[backfill/{tag}] {len(to_process)} memories to process (batch={batch_id})", file=sys.stderr)
    total_added = total_updated = total_merged = 0

    for row in to_process:
        mem_id = row["id"]
        content = row["content"] or ""
        project = row["project"] or "general"
        try:
            a, u, m = _run_extraction(
                episode_text=content,
                project=project,
                session_id="",
                batch_id=batch_id,
                dry_run=dry_run,
                label=f"{source_filter}/{project}/{mem_id[:8]}",
            )
            total_added += a
            total_updated += u
            total_merged += m
            if a or u or m:
                print(f"  {mem_id[:12]} project={project} +{a} ~{u} ={m}", file=sys.stderr)
        except Exception as e:
            print(f"  [backfill/{tag}] {mem_id[:12]} failed: {e}", file=sys.stderr)
        if not dry_run:
            done_ids.add(mem_id)
            save_checkpoint(done_ids, CHECKPOINT_DB)

    print(f"[backfill/{tag}] done — added={total_added} updated={total_updated} merged={total_merged} batch={batch_id}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# G5 regression gate (bulk modes only -- not --file, see module docstring's
# "Rollback a batch" note and docs/architecture/cognitive-architecture-spec.md
# section 3). The --file path runs via the session_end hook on small,
# frequent batches; a full gold-set pass per session is the wrong cost and
# the per-session risk is low. Bulk runs (--all/--from-db/--from-perplexity/
# --from-cursor-db) are deliberate, infrequent, and carry real regression
# risk, so they get an automatic before/after check instead of the
# previously-manual (and in practice never-run) retrieval_eval_kfold.py
# --rollback-batch step.
# ---------------------------------------------------------------------------

GATE_GOLD_PATH = _REPO_ROOT / "brain" / "eval" / "gold_mined.jsonl"
GATE_MIN_LIMIT = 20  # a canary-sized run shouldn't pay for a full gold pass
GATE_REGRESSION_TOLERANCE = 0.05  # matches the existing --rollback-baseline convention


def _resolve_db_path() -> Path:
    db_path = os.environ.get("BRAIN_DB_PATH", str(Path.home() / ".brain" / "brain.db"))
    rust_db = Path(__file__).resolve().parents[1] / "rust" / "brain.db"
    if rust_db.exists():
        db_path = str(rust_db)
    return Path(db_path)


def _measure_recall(gold_path: Path = GATE_GOLD_PATH) -> float | None:
    """Trusted-gold-set recall@k through the live production /search.

    Deliberately NOT retrieval_eval_kfold's own eval, which scores each
    memory's title against itself -- the 2026-10-27 audit already found
    that self-match structurally can't detect a real regression. gold_mined
    .jsonl is mined from real usage (brain/tools/mine_eval_queries.py) and
    replayed through the real production ranker (retrieval_eval.py).
    Returns None if the gold set doesn't exist -- the gate no-ops rather
    than block ingestion on a missing file.
    """
    if not gold_path.exists():
        return None
    from brain.tools.retrieval_eval import run_eval
    from brain.api_client import search as api_search

    def search_fn(query: str, n: int, project: str | None = None, memory_type: str | None = None):
        return api_search(query=query, n=n, project=project, memory_type=memory_type)

    report = run_eval(gold_path, k=10, search_fn=search_fn)
    return report["mean_recall"]


def _gate_start(batch_id: str, project: str | None) -> float | None:
    """Capture p1_before once, at the true start of a fresh bulk run, and
    persist it to backfill_batches so a --batch-id retry can reuse it
    instead of remeasuring against a corpus the batch has already changed."""
    recall = _measure_recall()
    if recall is None:
        print("[backfill/gate] no gold set found -- regression gate skipped", file=sys.stderr)
        return None
    conn = sqlite3.connect(str(_resolve_db_path()), timeout=30)
    try:
        conn.execute(
            "INSERT OR IGNORE INTO backfill_batches (batch_id, project, started_at, p1_before) "
            "VALUES (?, ?, ?, ?)",
            (batch_id, project or "general", datetime.now(timezone.utc).isoformat(), recall),
        )
        conn.commit()
    finally:
        conn.close()
    print(f"[backfill/gate] batch={batch_id} p1_before={recall:.4f}", file=sys.stderr)
    return recall


def _gate_load_p1_before(batch_id: str) -> float | None:
    conn = sqlite3.connect(str(_resolve_db_path()), timeout=30)
    try:
        row = conn.execute(
            "SELECT p1_before FROM backfill_batches WHERE batch_id = ?", (batch_id,)
        ).fetchone()
    finally:
        conn.close()
    if row is None or row[0] is None:
        print(f"[backfill/gate] no stored p1_before for batch={batch_id} -- gate skipped on resume", file=sys.stderr)
        return None
    return row[0]


def _gate_finish(batch_id: str, p1_before: float) -> None:
    recall_after = _measure_recall()
    if recall_after is None:
        return
    threshold = p1_before - GATE_REGRESSION_TOLERANCE
    db_path = _resolve_db_path()
    print(
        f"[backfill/gate] batch={batch_id} p1_before={p1_before:.4f} "
        f"p1_after={recall_after:.4f} threshold={threshold:.4f}",
        file=sys.stderr,
    )
    if recall_after < threshold:
        print(f"[backfill/gate] TRIGGERED -- rolling back batch {batch_id!r}", file=sys.stderr)
        from brain.tools.retrieval_eval_kfold import rollback_batch
        n = rollback_batch(db_path, batch_id)
        print(f"[backfill/gate] ROLLED BACK: {n} facts deleted", file=sys.stderr)
        return
    conn = sqlite3.connect(str(db_path), timeout=30)
    try:
        conn.execute(
            "UPDATE backfill_batches SET finished_at = ?, p1_after = ? WHERE batch_id = ?",
            (datetime.now(timezone.utc).isoformat(), recall_after, batch_id),
        )
        conn.commit()
    finally:
        conn.close()
    print("[backfill/gate] OK -- recall within acceptable range, batch retained", file=sys.stderr)


@contextmanager
def regression_gate(batch_id: str, project: str | None, dry_run: bool, limit: int | None, is_retry: bool):
    """Wraps a bulk backfill run with an automatic before/after regression
    check, auto-rolling back the batch if recall drops more than
    GATE_REGRESSION_TOLERANCE. No-ops on --dry-run or a canary-sized --limit."""
    gated = not dry_run and not (limit is not None and limit <= GATE_MIN_LIMIT)
    p1_before = None
    if gated:
        p1_before = _gate_load_p1_before(batch_id) if is_retry else _gate_start(batch_id, project)
    yield
    if gated and p1_before is not None:
        _gate_finish(batch_id, p1_before)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--file", type=Path, help="Single session JSON (session_end hook)")
    p.add_argument("--all", action="store_true", help="All Claude Code session exports")
    p.add_argument("--from-perplexity", action="store_true", help="All Perplexity export threads")
    p.add_argument("--from-db", action="store_true", help="Memories in brain.db (use --source)")
    p.add_argument("--from-cursor-db", action="store_true", help="Cursor chat history from vscdb")
    p.add_argument("--source", default="obsidian", help="source filter for --from-db (default: obsidian)")
    p.add_argument("--cursor-db", type=Path, default=_CURSOR_RECOVERY_DB, help="Path to state.vscdb.clean")
    p.add_argument("--type", dest="mem_type", help="type filter for --from-db")
    p.add_argument("--project", help="Filter by project")
    p.add_argument("--limit", type=int, help="Cap number of items")
    p.add_argument("--dry-run", action="store_true", help="Print what would happen, skip saves")
    p.add_argument("--batch-id", help="Reuse a batch ID (retries)")
    args = p.parse_args()

    batch_id = args.batch_id or str(uuid.uuid4())
    is_retry = bool(args.batch_id)

    if args.file:
        if not args.file.exists():
            print(f"error: {args.file} not found", file=sys.stderr)
            return 2
        # Not gated: small, frequent, session_end-hook-triggered batches --
        # see the regression_gate docstring for why.
        run_single(args.file, batch_id, args.dry_run)
        return 0

    if args.all:
        with regression_gate(batch_id, args.project, args.dry_run, args.limit, is_retry):
            run_all(args.project, args.limit, args.dry_run, batch_id)
        return 0

    if args.from_perplexity:
        with regression_gate(batch_id, args.project, args.dry_run, args.limit, is_retry):
            run_perplexity(args.limit, args.dry_run, batch_id)
        return 0

    if args.from_db:
        with regression_gate(batch_id, args.project, args.dry_run, args.limit, is_retry):
            run_from_db(args.source, args.mem_type, args.project, args.limit, args.dry_run, batch_id)
        return 0

    if args.from_cursor_db:
        with regression_gate(batch_id, args.project, args.dry_run, args.limit, is_retry):
            run_from_cursor_db(args.cursor_db, args.limit, args.dry_run, batch_id)
        return 0

    p.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
