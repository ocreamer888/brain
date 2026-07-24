"""Extraction helpers for Claude Code session exports."""
import json
from pathlib import Path
from datetime import datetime, timezone
from typing import Tuple

SESSIONS_EXPORT_DIR = Path(__file__).parent / "sessions_export"


def validate_session_json(file_path: Path) -> Tuple[bool, str | None]:
    """Validate that a session JSON has required fields."""
    required_fields = {
        "session_id",
        "project",
        "cwd",
        "ended_at",
        "messages",
    }

    try:
        data = json.loads(file_path.read_text())
        missing = required_fields - set(data.keys())
        if missing:
            return False, f"Missing fields: {missing}"
        return True, None
    except Exception as e:
        return False, f"Invalid JSON: {e}"


def extract_session_record(file_path: Path) -> dict:
    """Extract a memory record from a Claude Code session JSON export."""
    is_valid, error = validate_session_json(file_path)
    if not is_valid:
        raise ValueError(f"Invalid session JSON: {error}")

    data = json.loads(file_path.read_text())
    session_id = data["session_id"]
    project = data.get("project", "unknown")
    cwd = data.get("cwd", "")

    # Build text from messages and metadata
    parts = [
        f"Claude Code session: {project}",
        f"Ended: {data['ended_at']}",
        f"CWD: {cwd}",
    ]

    # Add message count summary
    message_count = data.get("message_count", 0)
    if message_count > 0:
        parts.append(f"Total messages: {message_count}")

    # Add first few user/assistant messages for context
    # Handles both raw JSONL format ({"type": "user", "message": {...}})
    # and flat format ({"role": "user", "content": "..."})
    messages = data.get("messages", [])
    shown = 0
    for msg in messages:
        if shown >= 10:
            break
        # Raw JSONL format from Claude Code transcript
        if "type" in msg and msg["type"] in ("user", "assistant") and "message" in msg:
            inner = msg["message"]
            role = inner.get("role", msg["type"])
            content = inner.get("content", "")
        # Flat format (legacy / test fixtures)
        elif "role" in msg:
            role = msg["role"]
            content = msg.get("content", "")
        else:
            continue

        if isinstance(content, str):
            preview = content[:200]
        elif isinstance(content, list):
            texts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
            preview = " ".join(texts)[:200]
        else:
            preview = ""

        if preview:
            parts.append(f"[{role}] {preview}")
            shown += 1

    text = " | ".join(parts)

    # Use the session's ended_at as event time so search/recency reflects when
    # the session ran, not when we happened to ingest it. Falls back to "now"
    # only if ended_at is missing / malformed.
    ended_at_raw = data.get("ended_at")
    event_ts: str
    if ended_at_raw:
        try:
            parsed = datetime.fromisoformat(ended_at_raw.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            event_ts = parsed.astimezone(timezone.utc).isoformat()
        except (ValueError, TypeError):
            event_ts = datetime.now(timezone.utc).isoformat()
    else:
        event_ts = datetime.now(timezone.utc).isoformat()

    return {
        "session_id": session_id,
        "project": project,
        "file_path": file_path.name,
        "text": text,
        "metadata": {
            "type": "conversation",
            "project": project,
            "tags": f"claude_code,{project}",
            "source": "claude_code_session",
            "session_id": session_id,
            "file_path": file_path.name,
            "timestamp": event_ts,
            "importance": "0.6",
        }
    }
