import json
import sys
from pathlib import Path

import requests

from brain.config import OLLAMA_URL, OLLAMA_SUMMARIZE_MODEL

SUMMARIZE_MODEL = OLLAMA_SUMMARIZE_MODEL


def _openrouter_chat(model: str, messages: list[dict], max_tokens: int) -> str:
    resp = requests.post(
        f"{OLLAMA_URL}/api/chat",
        json={"model": model, "messages": messages, "stream": False, "options": {"num_predict": max_tokens}},
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json()["message"]["content"]


def _chat(prompt: str, max_tokens: int = 512) -> str:
    """Single-prompt convenience wrapper over the local Ollama chat call.

    Used by the offline ingest/backfill scripts that just need one completion.
    """
    return _openrouter_chat(SUMMARIZE_MODEL, [{"role": "user", "content": prompt}], max_tokens)


def _parse_json(text: str) -> dict:
    start = text.find('{')
    end = text.rfind('}') + 1
    if start == -1:
        raise ValueError(f"No JSON found in response: {text[:200]}")
    return json.loads(text[start:end])


def summarize_conversation(messages: list[dict]) -> dict:
    """Summarize a full conversation session into structured knowledge."""
    # Truncate long messages to fit context
    formatted_parts = []
    for m in messages[:30]:
        content = m.get("content", "")
        if isinstance(content, list):
            content = " ".join(p.get("text", "") for p in content if isinstance(p, dict))
        formatted_parts.append(f"{m.get('role', 'unknown')}: {str(content)[:800]}")
    formatted = "\n".join(formatted_parts)

    text = _openrouter_chat(SUMMARIZE_MODEL, [{
        "role": "user",
        "content": f"""Analyze this AI coding conversation. Extract structured knowledge.

CONVERSATION:
{formatted}

Respond with ONLY valid JSON (no markdown, no explanation):
{{
  "summary": "2-3 sentence description of what was accomplished",
  "project": "project name or null",
  "topics": ["topic1", "topic2"],
  "decisions": ["key architectural or design decision made"],
  "solutions": ["problem: solution description"],
  "patterns": ["reusable code pattern discovered"],
  "type": "solution|decision|conversation|project_context|error_lesson"
}}"""
    }], max_tokens=1024)
    return _parse_json(text)


def summarize_exchange(user_message: str, assistant_response: str) -> str:
    """Summarize a single exchange into a concise memory string."""
    text = _openrouter_chat(SUMMARIZE_MODEL, [{
        "role": "user",
        "content": f"""Summarize this coding exchange in 1-2 sentences for future memory retrieval.
Focus on: what was done, what was decided, or what was solved.

USER: {user_message[:500]}
ASSISTANT: {assistant_response[:500]}

Respond with just the summary text, no JSON."""
    }], max_tokens=256)
    return text.strip()


def _enforce_session_summary_caps(raw: dict) -> dict:
    """Enforce strict shape and length caps on summarize_session output."""
    summary = str(raw.get("summary", ""))[:400]
    decisions = [str(d)[:160] for d in raw.get("decisions", []) if d][:3]
    next_steps = [str(s)[:160] for s in raw.get("next_steps", []) if s][:3]
    return {"summary": summary, "decisions": decisions, "next_steps": next_steps}


def summarize_session(messages: list[dict]) -> dict:
    """Summarize a full session into a structured, size-capped dict."""
    formatted_parts = []
    for m in messages[:40]:
        content = m.get("content", "")
        if isinstance(content, list):
            content = " ".join(p.get("text", "") for p in content if isinstance(p, dict))
        role = m.get("role", m.get("type", "unknown"))
        formatted_parts.append(f"{role}: {str(content)[:600]}")
    formatted = "\n".join(formatted_parts) if formatted_parts else "(empty session)"

    text = _openrouter_chat(SUMMARIZE_MODEL, [{
        "role": "user",
        "content": f"""You are summarizing a single Claude Code session transcript.
Focus on what changed in this session, not general project background.
Do NOT repeat specific error-fix pairs or decisions — those are extracted separately.
Ignore greetings, small talk, and generic LLM meta ("let me think", "as an AI", etc.).

Return ONLY valid JSON with this exact shape:
{{
  "summary": "string, 1-3 sentences, max 400 characters",
  "decisions": ["string, max 160 characters"],
  "next_steps": ["string, max 160 characters"]
}}

Rules:
- summary must describe what the user and assistant actually did and concluded.
- decisions: up to 3 concrete decisions made. Empty array if none.
- next_steps: up to 3 specific next actions. Infer from the work if not stated, or use empty array.
- No code blocks, no markdown, no keys other than summary/decisions/next_steps.
- All strings must be single-line (no newlines).

Transcript:
{formatted}"""
    }], max_tokens=512)
    raw = _parse_json(text)
    return _enforce_session_summary_caps(raw)


def _format_transcript(messages: list[dict], max_msgs: int = 40, max_chars: int = 600) -> str:
    parts = []
    for m in messages[:max_msgs]:
        content = m.get("content", "")
        if isinstance(content, list):
            content = " ".join(p.get("text", "") for p in content if isinstance(p, dict))
        role = m.get("role", m.get("type", "unknown"))
        parts.append(f"{role}: {str(content)[:max_chars]}")
    return "\n".join(parts) if parts else "(empty session)"


def _enforce_list_caps(items: list, max_items: int, max_chars: int) -> list[dict]:
    out = []
    for item in items[:max_items]:
        if isinstance(item, dict):
            out.append({k: str(v)[:max_chars] for k, v in item.items()})
        elif isinstance(item, str):
            out.append({"text": item[:max_chars]})
    return out


def extract_error_fix_pairs(messages: list[dict]) -> list[dict]:
    """Pass 1: Extract resolved error→fix pairs from session transcript."""
    formatted = _format_transcript(messages)
    text = _openrouter_chat(SUMMARIZE_MODEL, [{
        "role": "user",
        "content": f"""You are extracting error→fix pairs from a coding session transcript.
For each distinct error that was encountered AND resolved in this session, output one JSON object.

Return ONLY a valid JSON array. Each element:
{{
  "error": "exact error message or traceback (max 200 chars)",
  "cause": "why it happened (1 sentence, max 100 chars)",
  "fix": "what was done to fix it (1-2 sentences, max 200 chars)",
  "files": ["file1.py", "file2.py"]
}}

Rules:
- Only include errors that were RESOLVED in this session
- Include exact error text, file paths, and commands when available
- Skip errors that were just read/discussed but not fixed
- Return [] if no error-fix pairs found
- Max 5 pairs per session

Transcript:
{formatted}"""
    }], max_tokens=1024)
    raw = json.loads(text[text.find("["):text.rfind("]") + 1])
    return _enforce_list_caps(raw, 5, 200)


def extract_decisions(messages: list[dict]) -> list[dict]:
    """Pass 2: Extract architecture decisions from session transcript."""
    formatted = _format_transcript(messages)
    text = _openrouter_chat(SUMMARIZE_MODEL, [{
        "role": "user",
        "content": f"""You are extracting architectural decisions and reusable patterns from a coding session.
Focus on choices that would be useful to recall in future sessions.

Return ONLY a valid JSON array. Each element:
{{
  "decision": "what was decided (1-2 sentences, max 200 chars)",
  "context": "why this choice was made (1 sentence, max 150 chars)",
  "alternatives_rejected": "what was considered but not chosen (optional, max 100 chars)"
}}

Rules:
- Only include deliberate choices, not incidental actions
- Skip trivial decisions (formatting, variable naming)
- Include technology choices, architecture patterns, workaround strategies
- Return [] if no significant decisions found
- Max 3 decisions per session

Transcript:
{formatted}"""
    }], max_tokens=512)
    raw = json.loads(text[text.find("["):text.rfind("]") + 1])
    return _enforce_list_caps(raw, 3, 200)


def reflect_memories(memory_texts: list[str]) -> dict:
    """Consolidate and find patterns across a batch of memories."""
    formatted = "\n\n".join([f"[{i}] {m}" for i, m in enumerate(memory_texts)])

    text = _openrouter_chat(SUMMARIZE_MODEL, [{
        "role": "user",
        "content": f"""Review these memories. Consolidate near-duplicates, find patterns.

MEMORIES:
{formatted}

Respond with ONLY valid JSON:
{{
  "consolidated": ["merged or improved memory text for keeping"],
  "patterns": ["cross-memory insight or pattern worth saving"],
  "to_delete_indices": [0, 3]
}}"""
    }], max_tokens=2048)
    return _parse_json(text)
