"""
Importable core logic for Claude Code session ingestion.
Used by 07_ingest_claude_code.py and tests.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from brain.api_client import save_memory_batch
from brain.ingest.payloads import with_ingest_tag
from brain.bootstrap.claude_code_extractors import extract_session_record, validate_session_json


def _derive_session_title(record: dict, sid: str) -> str:
	"""Derive a human-readable, unique title from the first user message in the session."""
	project = record.get("project", "unknown")
	text = record.get("text", "")

	# Extract first user message from pipe-joined content
	if "| [user] " in text:
		user_part = text.split("| [user] ", 1)[1]
		first_msg = user_part.split(" | ")[0].strip()
		first_msg = " ".join(first_msg.split())  # collapse whitespace/newlines
		if len(first_msg) > 80:
			first_msg = first_msg[:77] + "..."
		if first_msg:
			return f"{first_msg} — {project}"

	# Fall back to date+project when no user message found
	ts = record.get("metadata", {}).get("timestamp", "")
	date_str = ts[:10] if ts and len(ts) >= 10 else "unknown-date"
	if not (len(date_str) == 10 and date_str[4] == "-" and date_str[7] == "-"):
		date_str = "unknown-date"
	return f"Session {date_str} — {project}"


BATCH_SIZE = 32


def load_checkpoint(checkpoint_path: Path) -> set:
    if checkpoint_path.exists():
        return set(json.loads(checkpoint_path.read_text()).get("processed_ids", []))
    return set()


def save_checkpoint(processed: set, checkpoint_path: Path) -> None:
    checkpoint_path.write_text(json.dumps({"processed_ids": sorted(processed)}))


def run_with_dirs(
    sessions_dir: Path,
    checkpoint_path: Path,
    use_llm: bool = True,
    only_file: Path | None = None,
) -> int:
    """
    Ingest session JSONs from sessions_dir, checkpointing by session_id.
    Returns number of memories saved.
    """
    session_files = [only_file] if only_file else sorted(sessions_dir.glob("*.json"))
    processed = load_checkpoint(checkpoint_path)
    saved_count = 0

    # Build deduplicated list: first file per unique session_id not already processed
    seen_ids: set[str] = set()
    to_process: list[tuple[Path, str]] = []
    for f in session_files:
        try:
            raw = json.loads(f.read_text())
            sid = raw.get("session_id") or f.stem
        except Exception:
            sid = f.stem
        if sid not in processed and sid not in seen_ids:
            to_process.append((f, sid))
            seen_ids.add(sid)

    pending_items: list[dict] = []
    pending_ids: list[str] = []

    def flush() -> None:
        nonlocal saved_count, pending_items, pending_ids, processed
        if not pending_items:
            return
        res = save_memory_batch(pending_items)
        failed_idx = {
            int(r.get("index", -1))
            for r in res.get("results", [])
            if r.get("error")
        }
        if failed_idx:
            raise RuntimeError(f"save-batch had failures at indices: {sorted(failed_idx)}")
        for sid in pending_ids:
            processed.add(sid)
        saved_count += len(pending_items)
        save_checkpoint(processed, checkpoint_path)
        pending_items.clear()
        pending_ids.clear()

    for f, sid in to_process:
        is_valid, error = validate_session_json(f)
        if not is_valid:
            print(f"  {f.name} INVALID: {error}", file=sys.stderr)
            processed.add(sid)
            save_checkpoint(processed, checkpoint_path)
            continue

        try:
            record = extract_session_record(f)
            if use_llm:
                from brain.core.summarizer import _chat, _parse_json
                prompt = f"Summarize this session in 2-3 sentences: {record['text'][:2000]}"
                try:
                    raw_summary = _chat(prompt, max_tokens=256)
                    data = _parse_json(raw_summary)
                    record["text"] = data.get("summary", record["text"])
                except Exception as e:
                    print(f"  [LLM summary failed]: {e}", file=sys.stderr)

            tags = with_ingest_tag(
                [
                    t.strip()
                    for t in str(record["metadata"].get("tags", "")).split(",")
                    if t.strip()
                ]
            )
            sid = str(record.get("session_id") or "")[:24] or "unknown"
            pending_items.append(
                {
                    "content": record["text"],
                    "memory_type": record["metadata"].get("type", "conversation"),
                    "tags": tags,
                    "project": record.get("project"),
                    "session_id": record.get("session_id"),
                    "source": record["metadata"].get("source", "claude_code_session"),
                    "timestamp": record["metadata"].get("timestamp"),
                    "title": _derive_session_title(record, sid),
                }
            )
            pending_ids.append(sid)
            if len(pending_items) >= BATCH_SIZE:
                flush()
        except Exception as e:
            print(f"  [error] {f.name}: {e}", file=sys.stderr)

    flush()
    return saved_count
