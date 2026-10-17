#!/usr/bin/env python3
"""
Stop hook — exports session metadata and reflects on memories before closing.
Claude Code calls this when a session ends.
Receives: session_id, transcript_path, cwd, ended_at, hook_event_name, last_assistant_message
"""
import sys
import json
import os
import subprocess
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).parent.parent.parent))  # AI/ dir

from brain.api_client import backend_mode
from brain.ingest.payloads import with_ingest_tag
from brain.hooks.session_start import detect_project, PROJECT_DIR_MAP
from brain.hooks.background import spawn_background
from brain.core.session_ingest import (
    save_session_extracted,
    save_session_summary,
    save_memory_fn,
)


# Re-export for tests / callers that still import from this module.
__all__ = [
    "save_session_extracted",
    "save_session_summary",
    "save_memory_fn",
    "find_or_create_export_path",
]


def find_or_create_export_path(export_dir: Path, session_id: str) -> tuple[Path, bool]:
    """Return (path, is_new) for this session's export file.

    is_new=True  → first time we see this session_id → safe to save summary.
    is_new=False → hook fired again for same session  → skip summary (dedup guard).
    """
    for existing in export_dir.glob("session_*.json"):
        try:
            data = json.loads(existing.read_text())
            if data.get("session_id") == session_id:
                return existing, False
        except Exception:
            continue
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M-%S-%f")
    return export_dir / f"session_{ts}.json", True


try:
    # Read hook context from stdin (Claude Code provides this for Stop events)
    raw_context = sys.stdin.read().strip()
    context = json.loads(raw_context) if raw_context else {}

    # Extract the fields Claude Code actually provides
    session_id = context.get("session_id", "unknown")
    transcript_path = context.get("transcript_path")
    cwd = context.get("cwd", os.getcwd())
    ended_at = context.get("ended_at", datetime.now(timezone.utc).isoformat())

    project = detect_project(cwd) or Path(cwd).name

    # Export session metadata to JSON
    export_dir = Path(__file__).parent.parent / "bootstrap" / "sessions_export"
    export_dir.mkdir(parents=True, exist_ok=True)

    export_file, is_new_session = find_or_create_export_path(export_dir, session_id)

    # Load messages from transcript JSONL if available
    messages = []
    message_count = 0
    if transcript_path:
        try:
            transcript_file = Path(transcript_path)
            if not transcript_file.exists():
                print(
                    f"[session_end] WARN transcript_path does not exist: {transcript_path}",
                    file=sys.stderr,
                )
            else:
                # JSONL: one JSON object per line
                with open(transcript_file) as f:
                    for line in f:
                        if line.strip():
                            msg = json.loads(line)
                            messages.append(msg)
                message_count = len(messages)
                if message_count == 0:
                    print(
                        f"[session_end] WARN transcript loaded but empty: {transcript_path}",
                        file=sys.stderr,
                    )
        except Exception as e:
            print(f"[BRAIN] Warning: Could not load transcript from {transcript_path}: {e}", file=sys.stderr)

    # Build export with what we have
    session_export = {
        "session_id": session_id,
        "project": project,
        "cwd": cwd,
        "ended_at": ended_at,
        "transcript_path": transcript_path,  # Reference to original transcript
        "message_count": message_count,
        "messages": messages,  # Loaded from JSONL if available
    }

    export_file.write_text(json.dumps(session_export, indent=2))
    print(f"[BRAIN] Session exported to {export_file.name} ({message_count} messages)", file=sys.stderr)

    # Auto-ingest of raw session blobs is disabled by default: it duplicated the
    # LLM summary path with lower-signal content and hurt retrieval quality.
    # Opt in with BRAIN_AUTO_INGEST_CLAUDE_CODE=1 to re-enable for backfill flows.
    auto_flag = os.environ.get("BRAIN_AUTO_INGEST_CLAUDE_CODE", "0").strip().lower()
    if auto_flag in ("1", "true", "yes", "on"):
        repo_root = Path(__file__).resolve().parents[2]
        ingest_script = repo_root / "brain" / "bootstrap" / "07_ingest_claude_code.py"
        log_path = Path(__file__).resolve().parent / "auto_ingest_claude_code.log"
        try:
            with open(log_path, "a", encoding="utf-8") as logf:
                subprocess.Popen(
                    [
                        sys.executable,
                        str(ingest_script),
                        "--no-llm",
                        "--file",
                        str(export_file.resolve()),
                    ],
                    cwd=str(repo_root),
                    stdin=subprocess.DEVNULL,
                    stdout=logf,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
            print("[BRAIN] Scheduled background Claude Code session ingest (--no-llm)", file=sys.stderr)
        except Exception as e:
            print(f"[BRAIN] Auto-ingest schedule failed (non-fatal): {e}", file=sys.stderr)

    # Fact extraction — opt-in via BRAIN_FACT_EXTRACT=1
    fact_flag = os.environ.get("BRAIN_FACT_EXTRACT", "0").strip().lower()
    if fact_flag in ("1", "true", "yes", "on"):
        repo_root = Path(__file__).resolve().parents[2]
        backfill_script = repo_root / "brain" / "tools" / "backfill_facts.py"
        fact_log = Path(__file__).resolve().parent / "fact_extract.log"
        try:
            with open(fact_log, "a", encoding="utf-8") as logf:
                subprocess.Popen(
                    [sys.executable, str(backfill_script), "--file", str(export_file.resolve())],
                    cwd=str(repo_root),
                    stdin=subprocess.DEVNULL,
                    stdout=logf,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
            print("[BRAIN] Fact extraction scheduled in background.", file=sys.stderr)
        except Exception as e:
            print(f"[BRAIN] Fact extraction schedule failed (non-fatal): {e}", file=sys.stderr)

    # Trigger reflection in background — too slow to run synchronously with 7k+ memories
    try:
        reflect_script = Path(__file__).resolve().parent / "run_reflect.py"
        spawn_background(
            "Reflection",
            [sys.executable, str(reflect_script)],
            cwd=str(Path(__file__).resolve().parents[2]),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception as e:
        print(f"[BRAIN] Reflection schedule failed (non-fatal): {e}", file=sys.stderr)

    # Eval quick check — opt-in via BRAIN_EVAL_AUTO=1
    eval_flag = os.environ.get("BRAIN_EVAL_AUTO", "0").strip().lower()
    if eval_flag in ("1", "true", "yes", "on"):
        repo_root = Path(__file__).resolve().parents[2]
        eval_script = repo_root / "brain" / "tools" / "eval_suite.py"
        eval_log = Path(__file__).resolve().parent / "eval_auto.log"
        try:
            with open(eval_log, "a", encoding="utf-8") as logf:
                subprocess.Popen(
                    [sys.executable, str(eval_script), "--quick", "--mcp", "--quiet"],
                    cwd=str(repo_root),
                    stdin=subprocess.DEVNULL,
                    stdout=logf,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
            print("[BRAIN] Eval quick check scheduled in background.", file=sys.stderr)
        except Exception as e:
            print(f"[BRAIN] Eval auto-run schedule failed (non-fatal): {e}", file=sys.stderr)

    # Save session memories — only on first Stop event for this session.
    # The Stop hook fires once per subagent; without this guard the same summary
    # would be saved once for every Agent tool call in the session.
    if is_new_session:
        save_session_extracted(
            messages=messages,
            project=project,
            session_id=session_id,
            ended_at=ended_at,
        )
        # Flush any remaining edit groups before clearing state
        try:
            from brain.hooks.action_state import load_state, flush_all_edit_groups, ACTION_CONFIDENCE
            from brain.hooks.corpus_barrier import should_save as barrier_check

            ptu_state = load_state()
            remaining_edits = flush_all_edit_groups(ptu_state)
            for fp, content_text, group_title in remaining_edits:
                if not barrier_check(ACTION_CONFIDENCE["edit_group"]):
                    continue
                try:
                    save_memory_fn(
                        content=content_text,
                        memory_type="solution",
                        tags=with_ingest_tag(["edit_group", project]),
                        project=project,
                        session_id=session_id,
                        source="claude_code_hook",
                        title=group_title,
                        timestamp=ended_at,
                    )
                except Exception as e:
                    print(f"[session_end] edit_group flush failed: {e}", file=sys.stderr)
            if remaining_edits:
                print(f"[session_end] flushed {len(remaining_edits)} edit groups at session end", file=sys.stderr)
        except Exception as e:
            print(f"[session_end] edit_group flush error: {e}", file=sys.stderr)

        # Clear PostToolUse session state
        try:
            from brain.hooks.action_state import clear_state
            clear_state()
        except Exception:
            pass
    else:
        print(
            f"[session_end] dedup guard: skipped duplicate summary session_id={session_id} project={project}",
            file=sys.stderr,
        )

    # Automated cleanup: BVH dedup every session, noise detect every 20 sessions.
    # Runs in background — never blocks session end.
    try:
        cleanup_script = Path(__file__).resolve().parent / "run_cleanup.py"
        spawn_background(
            "Cleanup (bvh_dedup + noise_detect)",
            [sys.executable, str(cleanup_script)],
            cwd=str(Path(__file__).resolve().parents[2]),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception as e:
        print(f"[BRAIN] Cleanup schedule failed (non-fatal): {e}", file=sys.stderr)

    # Opportunistic spool replay to reduce lag after transient API failures.
    if backend_mode() != "python":
        try:
            from brain.hooks.spool import replay_once, metrics

            replay_stats = replay_once()
            if replay_stats.replayed or replay_stats.remaining or replay_stats.moved_to_dlq:
                m = metrics()
                print(
                    f"[BRAIN] spool_replay replayed={replay_stats.replayed} remaining={m['queue_size']} oldest_age_sec={m['oldest_age_sec']} dlq_added={replay_stats.moved_to_dlq}",
                    file=sys.stderr,
                )
        except Exception as e:
            print(f"[BRAIN] Spool replay skipped (non-fatal): {e}", file=sys.stderr)

except Exception as e:
    # Never crash Claude Code over brain failure
    print(f"[BRAIN] Stop hook failed (non-fatal): {e}", file=sys.stderr)
