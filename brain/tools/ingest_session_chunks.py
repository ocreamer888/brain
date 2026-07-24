#!/usr/bin/env python3
"""Ingest raw session transcripts as chunked conversation memories.

Each user+assistant exchange becomes one memory (type=conversation).
Skips system messages, file-history snapshots, and very short exchanges.

Usage:
    python3 brain/tools/ingest_session_chunks.py [--file path.json] [--all] [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from brain.api_client import save_memory_batch
from brain.ingest.payloads import with_ingest_tag

SESSIONS_DIR = Path(__file__).resolve().parents[1] / "bootstrap" / "sessions_export"
CHECKPOINT = Path(__file__).resolve().parents[1] / "bootstrap" / "checkpoint_session_chunks.json"
MIN_CHARS = 50
BATCH_SIZE = 32


def _extract_text(message: dict) -> str:
    """Extract plain text from a message dict (handles str and list content)."""
    content = message.get("message", {}).get("content", "")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
        return " ".join(parts).strip()
    return ""


def chunk_session(session: dict) -> list[dict]:
    """Return list of save-batch items from a session dict."""
    session_id = session.get("session_id", "")
    project = session.get("project", "general")
    messages = session.get("messages", [])

    # Keep only user and assistant messages in order
    useful = [m for m in messages if m.get("type") in ("user", "assistant")]

    chunks = []
    i = 0
    while i < len(useful) - 1:
        u = useful[i]
        a = useful[i + 1]
        if u.get("type") == "user" and a.get("type") == "assistant":
            user_text = _extract_text(u)
            asst_text = _extract_text(a)
            combined = f"User: {user_text}\n\nAssistant: {asst_text}"
            if len(user_text) + len(asst_text) >= MIN_CHARS:
                u_preview = user_text[:72] + ("…" if len(user_text) > 72 else "")
                sid = session_id[:12] if session_id else "session"
                chunks.append(
                    {
                        "content": combined,
                        "memory_type": "conversation",
                        "tags": with_ingest_tag(["session_chunk", project]),
                        "project": project,
                        "session_id": session_id,
                        "source": "claude_code_session",
                        "title": f"Chunk {sid} · {u_preview}",
                    }
                )
            i += 2
        else:
            i += 1
    return chunks


def load_checkpoint(path: Path | None = None) -> set:
    cp = path or CHECKPOINT
    if cp.exists():
        data = json.loads(cp.read_text())
        # Support old format (filenames under "done") and new format (session_ids)
        return set(data.get("session_ids", data.get("done", [])))
    return set()


def save_checkpoint(done: set, path: Path | None = None) -> None:
    cp = path or CHECKPOINT
    cp.write_text(json.dumps({"session_ids": sorted(done)}))


def ingest_file(path: Path, dry_run: bool = False) -> int:
    session = json.loads(path.read_text())
    chunks = chunk_session(session)
    if not chunks:
        return 0
    if dry_run:
        print(f"[chunks] {path.name}: {len(chunks)} chunks (dry-run, not sent)")
        return len(chunks)
    for i in range(0, len(chunks), BATCH_SIZE):
        save_memory_batch(chunks[i : i + BATCH_SIZE])
    return len(chunks)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--file", help="Single session JSON file to ingest")
    p.add_argument("--all", action="store_true", help="Ingest all sessions (checkpoint-resumable)")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    if args.file:
        n = ingest_file(Path(args.file), args.dry_run)
        print(f"[chunks] ingested {n} chunks from {args.file}")
        return 0

    if args.all:
        done_ids = load_checkpoint()
        files = sorted(SESSIONS_DIR.glob("session_*.json"))

        to_process: list[tuple[Path, str]] = []
        seen_ids: set[str] = set()
        for f in files:
            try:
                sid = json.loads(f.read_text()).get("session_id", "")
            except Exception:
                continue
            if sid and sid not in done_ids and sid not in seen_ids:
                to_process.append((f, sid))
                seen_ids.add(sid)

        print(f"[chunks] {len(to_process)}/{len(files)} sessions to process", file=sys.stderr)
        total = 0
        for f, sid in to_process:
            n = ingest_file(f, args.dry_run)
            total += n
            done_ids.add(sid)
            if not args.dry_run:
                save_checkpoint(done_ids)
            print(f"[chunks] {f.name} (sid={sid[:8]}): {n} chunks", file=sys.stderr)
        print(f"[chunks] done — {total} chunks total")
        return 0

    print("Usage: ingest_session_chunks.py [--file path.json] [--all] [--dry-run]")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
