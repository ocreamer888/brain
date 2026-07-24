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
from brain.core.summarizer import summarize_session
from brain.ingest.payloads import with_ingest_tag
from brain.hooks.session_start import detect_project, PROJECT_DIR_MAP


def save_memory_fn(**kwargs):
    """Thin wrapper so tests can patch it easily."""
    from brain.api_client import save_memory as api_save
    from brain.core.memory import save_memory as py_save
    if backend_mode() == "python":
        return py_save(**kwargs)
    return api_save(**kwargs)


_TRIVIAL_MARKERS = (
    "no actionable",
    "no code changes",
    "no significant",
    "no tasks",
    "no decisions",
    "empty session",
    "no meaningful",
    "remained default",
    "no user or assistant",
    "no substantive",
    "no user or assistant messages",
    "transcript contains no",
    "session transcript contains no",
    "placeholder text",
    "impossible to determine",
)


def _is_trivial_summary(summary_text: str, decisions: list, next_steps: list) -> bool:
    """Skip saving when a session produced no usable signal."""
    if decisions or next_steps:
        return False
    if not summary_text or len(summary_text.strip()) < 40:
        return True
    lowered = summary_text.lower()
    return any(marker in lowered for marker in _TRIVIAL_MARKERS)


def save_session_extracted(*, messages: list, project: str, session_id: str, ended_at: str):
    """3-pass recycling extraction: error-fix pairs, decisions, then lean summary."""
    from brain.hooks.corpus_barrier import should_save
    from brain.hooks.action_state import ACTION_CONFIDENCE

    # Skip recycling entirely if no messages — saves 3 LLM calls + prevents thin output
    if not messages:
        print(
            f"[session_end] skipped recycling: empty message list session_id={session_id} project={project}",
            file=sys.stderr,
        )
        return

    try:
        date_str = ended_at[:10]
    except Exception:
        date_str = "unknown-date"

    # Pass 1: Error-fix pairs → solution memories
    try:
        from brain.core.summarizer import extract_error_fix_pairs
        pairs = extract_error_fix_pairs(messages)
        for pair in pairs:
            if not should_save(ACTION_CONFIDENCE["session_error_fix"]):
                continue
            content = f"Error: {pair.get('error', '?')}\nCause: {pair.get('cause', '?')}\nFix: {pair.get('fix', '?')}"
            files = pair.get("files", [])
            if isinstance(files, list) and files:
                content += f"\nFiles: {', '.join(str(f) for f in files)}"
            try:
                save_memory_fn(
                    content=content,
                    memory_type="error_lesson",
                    tags=with_ingest_tag(["error_fix", "recycling_pass", project]),
                    project=project,
                    session_id=session_id,
                    source="session_recycling",
                    title=f"Fix: {str(pair.get('error', ''))[:60]}",
                    timestamp=ended_at,
                )
            except Exception as e:
                print(f"[session_end] pass1 save failed: {e}", file=sys.stderr)
        if pairs:
            print(f"[session_end] pass1 extracted {len(pairs)} error_fix_pairs", file=sys.stderr)
    except Exception as e:
        print(f"[session_end] pass1 error_fix extraction failed: {e}", file=sys.stderr)

    # Pass 2: Decisions → pattern memories
    try:
        from brain.core.summarizer import extract_decisions
        decisions = extract_decisions(messages)
        for dec in decisions:
            if not should_save(ACTION_CONFIDENCE["session_decision"]):
                continue
            content = str(dec.get("decision", "?"))
            ctx = dec.get("context", "")
            if ctx:
                content += f"\nContext: {ctx}"
            alt = dec.get("alternatives_rejected", "")
            if alt:
                content += f"\nRejected: {alt}"
            try:
                save_memory_fn(
                    content=content,
                    memory_type="pattern",
                    tags=with_ingest_tag(["decision", "recycling_pass", project]),
                    project=project,
                    session_id=session_id,
                    source="session_recycling",
                    title=f"Decision: {str(dec.get('decision', ''))[:60]}",
                    timestamp=ended_at,
                )
            except Exception as e:
                print(f"[session_end] pass2 save failed: {e}", file=sys.stderr)
        if decisions:
            print(f"[session_end] pass2 extracted {len(decisions)} decisions", file=sys.stderr)
    except Exception as e:
        print(f"[session_end] pass2 decision extraction failed: {e}", file=sys.stderr)

    # Pass 3: Lean session summary (existing behavior)
    save_session_summary(
        messages=messages,
        project=project,
        session_id=session_id,
        ended_at=ended_at,
    )


def save_session_summary(*, messages: list, project: str, session_id: str, ended_at: str):
    """Generate a session summary and persist it as a project_context memory."""
    try:
        summary = summarize_session(messages)
    except Exception as e:
        print(f"[session_end] summarize_session failed project={project} error={e}", file=sys.stderr)
        return

    summary_text = summary.get("summary", "")
    decisions = summary.get("decisions", [])
    next_steps = summary.get("next_steps", [])

    if _is_trivial_summary(summary_text, decisions, next_steps):
        print(
            f"[session_end] skipped trivial session_summary project={project} ended_at={ended_at}"
            f' preview="{summary_text[:80]}"',
            file=sys.stderr,
        )
        return

    lines = [summary_text]
    if decisions:
        lines.append("Decisions: " + "; ".join(decisions))
    if next_steps:
        lines.append("Next: " + "; ".join(next_steps))
    content = "\n".join(lines)

    try:
        date_str = ended_at[:10]  # "YYYY-MM-DD"
    except Exception:
        date_str = "unknown-date"

    try:
        save_memory_fn(
            content=content,
            memory_type="project_context",
            tags=with_ingest_tag(["session_summary", project]),
            project=project,
            session_id=session_id,
            source="claude_code_session",
            title=f"Session {date_str} — {project}",
            timestamp=ended_at if ended_at else None,
        )
        print(
            f"[session_end] saved session_summary project={project} ended_at={ended_at}"
            f" len={len(content)} decisions={len(decisions)} next_steps={len(next_steps)}"
            f' preview="{summary_text[:80]}"',
            file=sys.stderr,
        )
    except Exception as e:
        print(f"[session_end] save_memory failed project={project} error={e}", file=sys.stderr)


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
        subprocess.Popen(
            [sys.executable, str(reflect_script)],
            cwd=str(Path(__file__).resolve().parents[2]),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        print("[BRAIN] Reflection scheduled in background.", file=sys.stderr)
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
        subprocess.Popen(
            [sys.executable, str(cleanup_script)],
            cwd=str(Path(__file__).resolve().parents[2]),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        print("[BRAIN] Cleanup (bvh_dedup + noise_detect) scheduled in background.", file=sys.stderr)
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
