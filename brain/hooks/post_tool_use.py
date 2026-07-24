#!/usr/bin/env python3
"""PostToolUse hook — smart action capture with confidence scoring and corpus barrier.

Classifies each tool call as high-signal (error-fix pair, test pass, source write)
or noise (discovery commands, read operations, skip files). Maintains session state
across calls to track errors and pair them with fixes.
"""
import sys
import json
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))  # AI/ dir

from brain.hooks.session_start import detect_project
from brain.hooks.action_state import (
    ACTION_CONFIDENCE,
    load_state,
    save_state,
    record_error,
    record_edit,
    pop_matching_error,
    flush_edit_groups,
    is_error_response,
    is_skip_bash,
    is_skip_file,
    is_test_pass,
    get_cached_corpus_size,
)
from brain.hooks.corpus_barrier import should_save


def _llm_title(context: str) -> str:
    """Generate a meaningful title via LLM. Falls back to first 80 chars on failure."""
    try:
        from brain.core.summarizer import _openrouter_chat, SUMMARIZE_MODEL
        raw = _openrouter_chat(SUMMARIZE_MODEL, [{
            "role": "user",
            "content": f"""Generate a concise, descriptive title (max 80 chars) for this coding event.
The title should describe WHAT was done and WHY, not just file names.
Return ONLY the title text, nothing else.

Event:
{context[:1000]}"""
        }], max_tokens=64)
        return raw.strip().strip('"')[:80]
    except Exception:
        return context[:80]


def classify_action(tool_name, tool_input, tool_response, state):
    """Classify a tool call. Returns (memory_type, content, title, confidence) or None to skip."""
    response_str = str(tool_response or "")[:2000]
    project = detect_project(os.getcwd()) or Path(os.getcwd()).name

    if tool_name == "Bash":
        command = str(tool_input.get("command", ""))

        if is_skip_bash(command):
            return None

        if is_test_pass(response_str) and state.get("pending_test_failure"):
            state["pending_test_failure"] = False
            return (
                "solution",
                f"Tests passing after fix: {command[:200]}",
                f"Tests pass — {project}",
                ACTION_CONFIDENCE["test_pass"],
            )

        if is_error_response(response_str):
            record_error(state, "Bash", response_str[:300], command)
            if "test" in command.lower() or "pytest" in command.lower():
                state["pending_test_failure"] = True
            # Strategy Layer: pre-search brain for similar past errors
            try:
                from brain.api_client import template_search
                error_query = f"{command[:100]}: {response_str[:200]}"
                hits = template_search(query=error_query, n=3)
                if hits:
                    state["strategy_hints"] = [{
                        "type": "similar_error",
                        "query": error_query[:150],
                        "hits": [
                            {"content": h.get("content", "")[:200], "type": h.get("metadata", {}).get("type", "?")}
                            for h in hits[:3]
                            if h.get("distance", 1.0) < 0.5
                        ],
                    }]
            except Exception:
                pass
            return None

        return None

    if tool_name in ("Edit", "Write"):
        file_path = str(tool_input.get("file_path", ""))
        if is_skip_file(file_path):
            return None

        matched_error = pop_matching_error(state, file_path)
        if matched_error:
            content = f"Error: {matched_error['error_snippet']}\nFixed by editing: {file_path}"
            if matched_error.get("command"):
                content += f"\nTriggered by: {matched_error['command']}"
            title = _llm_title(content)
            return (
                "solution",
                content,
                title,
                ACTION_CONFIDENCE["error_fix"],
            )

        if tool_name == "Write":
            content_preview = str(tool_input.get("content", ""))[:500]
            content = f"Created {file_path}\nContent preview: {content_preview}"
            title = _llm_title(content)
            return (
                "solution",
                content,
                title,
                ACTION_CONFIDENCE["write_source"],
            )

        if tool_name == "Edit":
            old_str = str(tool_input.get("old_string", ""))
            new_str = str(tool_input.get("new_string", ""))
            record_edit(state, file_path, old_str, new_str)
            return None  # grouped edits flushed separately

    if tool_name == "Agent":
        agent_desc = str(tool_input.get("description", ""))[:200]
        return (
            "decision",
            f"Dispatched agent: {agent_desc}",
            agent_desc[:100] or f"Agent — {project}",
            ACTION_CONFIDENCE["agent"],
        )

    return None


try:
    raw = sys.stdin.read().strip()
    if not raw:
        sys.exit(0)

    context = json.loads(raw)
    tool_name = context.get("tool_name", "")
    tool_input = context.get("tool_input", {})
    tool_response = context.get("tool_response", "")

    state = load_state()
    state["tool_count"] = state.get("tool_count", 0) + 1

    result = classify_action(tool_name, tool_input, tool_response, state)

    # Flush idle edit groups (edits to a file that stopped N tool calls ago)
    flushed = flush_edit_groups(state)
    save_state(state)

    if flushed:
        from brain.api_client import backend_mode, save_memory_with_status
        from brain.ingest.payloads import with_ingest_tag
        from brain.hooks.spool import enqueue_memory

        n = get_cached_corpus_size(state)
        save_state(state)
        project = detect_project(os.getcwd()) or Path(os.getcwd()).name
        for fp, content_text, group_title in flushed:
            conf = ACTION_CONFIDENCE["edit_group"]
            if not should_save(conf, n):
                continue
            payload = {
                "content": content_text,
                "memory_type": "solution",
                "tags": with_ingest_tag(["edit_group", project]),
                "project": project,
                "source": "claude_code_hook",
                "title": group_title,
            }
            try:
                save_memory_with_status(**payload)
                print(f"[BRAIN] action=edit_group file={Path(fp).name} confidence={conf:.2f}", file=sys.stderr)
            except Exception as e:
                enqueue_memory(payload, str(e))

    if result is None:
        sys.exit(0)

    memory_type, content, title, confidence = result
    n = get_cached_corpus_size(state)
    save_state(state)

    if not should_save(confidence, n):
        print(
            f"[BRAIN] action=barrier_blocked tool={tool_name} confidence={confidence:.2f} n={n}",
            file=sys.stderr,
        )
        sys.exit(0)

    from brain.api_client import backend_mode, save_memory_with_status
    from brain.ingest.payloads import with_ingest_tag

    project = detect_project(os.getcwd()) or Path(os.getcwd()).name
    tags = with_ingest_tag([tool_name.lower(), project])

    if backend_mode() == "python":
        from brain.core.memory import save_memory
        save_memory(
            content=content,
            memory_type=memory_type,
            tags=tags,
            project=project,
            title=title,
        )
        print(f"[BRAIN] action={memory_type} tool={tool_name} confidence={confidence:.2f}", file=sys.stderr)
    else:
        from brain.hooks.spool import enqueue_memory, replay_once, metrics

        payload = {
            "content": content,
            "memory_type": memory_type,
            "tags": tags,
            "project": project,
            "source": "claude_code_hook",
            "title": title,
        }
        try:
            res = save_memory_with_status(**payload)
            print(
                f"[BRAIN] action={memory_type} tool={tool_name} confidence={confidence:.2f} save={res['status']}",
                file=sys.stderr,
            )
            replay_stats = replay_once()
            if replay_stats.replayed or replay_stats.remaining or replay_stats.moved_to_dlq:
                m = metrics()
                print(
                    f"[BRAIN] replayed={replay_stats.replayed} remaining={m['queue_size']}",
                    file=sys.stderr,
                )
        except Exception as e:
            enqueue_memory(payload, str(e))
            m = metrics()
            print(
                f"[BRAIN] action=queued queue_size={m['queue_size']}",
                file=sys.stderr,
            )

except Exception as e:
    print(f"[BRAIN] PostToolUse failed (non-fatal): {e}", file=sys.stderr)
