"""Extraction helpers for Perplexity exported threads."""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

EXPORTS_DIR = Path(__file__).parent / "perplexity_exports"

SUMMARY_PROMPT = """Analyze this Perplexity AI conversation thread.
Extract structured knowledge for a personal knowledge base.

TITLE: {title}

CONVERSATION:
{conversation}

Respond with ONLY valid JSON:
{{
  "summary": "2-3 sentence description of what was researched and key findings",
  "topics": ["topic1", "topic2", "topic3"],
  "insights": ["key insight or answer discovered"],
  "type": "project_context"
}}"""


def summarize_thread_text(title: str, messages: list[dict]) -> str:
    """Build a plain-text summary of a thread without calling LLM.
    Used as fallback and for testing.
    """
    parts = [f"Perplexity thread: {title}"]
    for msg in messages[:6]:
        role = msg.get("role", "")
        content = msg.get("content", "")[:200]
        if role == "user":
            parts.append(f"Q: {content}")
        elif role == "assistant":
            parts.append(f"A: {content}")
    return " | ".join(parts)


def extract_thread_record(json_path: Path) -> dict:
    """Extract a memory record from a perplexport JSON thread file."""
    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
    except Exception:
        thread_id = json_path.stem
        return _make_record(thread_id, f"Perplexity thread: {thread_id}", [], thread_id, 0)

    thread_id = str(data.get("id", json_path.stem))
    title = data.get("title", f"Thread {thread_id}")
    messages = data.get("messages", [])
    created_at = data.get("created_at", 0)

    # Build tags from title words
    tags = [w.lower() for w in title.split() if len(w) > 3][:6]

    text = summarize_thread_text(title, messages)
    return _make_record(thread_id, text, tags, title, created_at)


def extract_thread_record_with_llm(json_path: Path) -> dict:
    """Extract with LLM summarization (used by 06_ingest_perplexity.py)."""
    from brain.core.summarizer import _chat, _parse_json

    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
    except Exception:
        return extract_thread_record(json_path)

    thread_id = str(data.get("id", json_path.stem))
    title = data.get("title", f"Thread {thread_id}")
    messages = data.get("messages", [])
    created_at = data.get("created_at", 0)

    # Build conversation text for LLM
    conv_parts = []
    for msg in messages[:8]:
        role = msg.get("role", "")
        content = msg.get("content", "")[:400]
        if role in ("user", "assistant"):
            conv_parts.append(f"{role.upper()}: {content}")
    conversation = "\n".join(conv_parts)[:3000]

    prompt = SUMMARY_PROMPT.format(title=title, conversation=conversation)
    try:
        raw = _chat(prompt, max_tokens=512)
        summary_data = _parse_json(raw)
        parts = [summary_data.get("summary", "")]
        parts += summary_data.get("insights", [])
        text = " | ".join(filter(None, parts))
        tags = summary_data.get("topics", [])[:6]
        record_type = summary_data.get("type", "project_context")
    except Exception:
        text = summarize_thread_text(title, messages)
        tags = [w.lower() for w in title.split() if len(w) > 3][:6]
        record_type = "project_context"

    return _make_record(thread_id, text, tags, title, created_at, record_type)


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_record(thread_id: str, text: str, tags: list[str], title: str = "", created_at: int = 0, record_type: str = "project_context") -> dict:
    file_path = f"threads/{thread_id}.json"
    ts = datetime.fromtimestamp(created_at, tz=timezone.utc).isoformat() if created_at else datetime.now(timezone.utc).isoformat()
    return {
        "file_path": file_path,
        "text": text,
        "metadata": {
            "type": record_type,
            "project": "perplexity",
            "tags": ",".join(tags),
            "source": "perplexity",
            "file_path": file_path,
            "importance": "0.85",
            "timestamp": ts,
            "thread_id": thread_id,
            "title": title,
        }
    }
