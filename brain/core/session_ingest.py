#!/usr/bin/env python3
"""Shared session-ingest orchestration — pure brain logic, harness-agnostic.

Reused by:
  - Claude Code's Stop hook (``brain/hooks/session_end.py``) — parses Claude's
    stdin contract, then delegates here.
  - External harnesses (e.g. the Hermes ``brain`` memory provider) — pass the
    conversation messages in directly.

This module contains NO harness-specific I/O (no stdin parsing, no transcript
file loading). Callers hand in an already-loaded ``messages`` list; this layer
does the 3-pass extraction, edit-group flush, and post-session maintenance
(reflect + cleanup + spool replay). Storage routes through ``brain.api_client``
(Rust API) or ``brain.core.memory`` (python backend) exactly as before, so the
saved memories are identical regardless of caller.
"""
import subprocess
import sys
from pathlib import Path

from brain.api_client import backend_mode
from brain.core.summarizer import summarize_session
from brain.ingest.payloads import with_ingest_tag


def save_memory_fn(**kwargs):
    """Thin wrapper so tests can patch it easily.

    The python-backend import is lazy so API-only callers (e.g. the Hermes
    brain provider, whose env has no numpy/sentence-transformers) never pull
    ``brain.core.memory`` and its heavy deps.
    """
    if backend_mode() == "python":
        from brain.core.memory import save_memory as py_save
        return py_save(**kwargs)
    from brain.api_client import save_memory as api_save
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
            f"[session_ingest] skipped recycling: empty message list session_id={session_id} project={project}",
            file=sys.stderr,
        )
        return

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
                    auto_entities=False,  # session-end batch: backfill links these
                )
            except Exception as e:
                print(f"[session_ingest] pass1 save failed: {e}", file=sys.stderr)
        if pairs:
            print(f"[session_ingest] pass1 extracted {len(pairs)} error_fix_pairs", file=sys.stderr)
    except Exception as e:
        print(f"[session_ingest] pass1 error_fix extraction failed: {e}", file=sys.stderr)

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
                    auto_entities=False,  # session-end batch: backfill links these
                )
            except Exception as e:
                print(f"[session_ingest] pass2 save failed: {e}", file=sys.stderr)
        if decisions:
            print(f"[session_ingest] pass2 extracted {len(decisions)} decisions", file=sys.stderr)
    except Exception as e:
        print(f"[session_ingest] pass2 decision extraction failed: {e}", file=sys.stderr)

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
        print(f"[session_ingest] summarize_session failed project={project} error={e}", file=sys.stderr)
        return

    summary_text = summary.get("summary", "")
    decisions = summary.get("decisions", [])
    next_steps = summary.get("next_steps", [])

    if _is_trivial_summary(summary_text, decisions, next_steps):
        print(
            f"[session_ingest] skipped trivial session_summary project={project} ended_at={ended_at}"
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
            auto_entities=False,  # session-end batch: backfill links these
        )
        print(
            f"[session_ingest] saved session_summary project={project} ended_at={ended_at}"
            f" len={len(content)} decisions={len(decisions)} next_steps={len(next_steps)}"
            f' preview="{summary_text[:80]}"',
            file=sys.stderr,
        )
    except Exception as e:
        print(f"[session_ingest] save_memory failed project={project} error={e}", file=sys.stderr)


def ingest_session(*, messages: list, project: str, session_id: str, ended_at: str,
                   flush_edit_groups: bool = True):
    """Full session ingest: 3-pass extraction + edit-group flush + state clear.

    This is the single entry point external harnesses call at session end.
    Behaviour matches what Claude Code's Stop hook does for a new session.

    ``flush_edit_groups`` controls the PostToolUse edit-group flush, which reads
    Claude Code's shared ``action_state`` file. Harnesses without a PostToolUse
    hook (e.g. Hermes) should pass ``False`` so they don't flush another
    harness's pending edits.
    """
    save_session_extracted(
        messages=messages,
        project=project,
        session_id=session_id,
        ended_at=ended_at,
    )

    if not flush_edit_groups:
        return

    # Flush any remaining edit groups before clearing state
    try:
        from brain.hooks.action_state import load_state, flush_all_edit_groups, ACTION_CONFIDENCE, clear_state
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
                    auto_entities=False,  # session-end batch: backfill links these
                )
            except Exception as e:
                print(f"[session_ingest] edit_group flush failed: {e}", file=sys.stderr)
        if remaining_edits:
            print(f"[session_ingest] flushed {len(remaining_edits)} edit groups at session end", file=sys.stderr)
        # Clear PostToolUse session state
        try:
            clear_state()
        except Exception:
            pass
    except Exception as e:
        print(f"[session_ingest] edit_group flush error: {e}", file=sys.stderr)


def run_post_session_maintenance():
    """Background brain maintenance: reflect, cleanup (bvh_dedup + noise_detect),
    and opportunistic spool replay. Each is best-effort and never blocks.

    Reflect/cleanup are spawned as detached subprocesses (too slow to run
    synchronously with thousands of memories). Spool replay runs inline (fast).
    """
    hooks_dir = Path(__file__).resolve().parents[1] / "hooks"
    repo_root = Path(__file__).resolve().parents[2]

    # Reflect/cleanup are brain-internal jobs that need numpy + the embedder, so
    # they must run with the brain repo's interpreter — not the caller's (e.g. the
    # Hermes venv has no numpy). Prefer BRAIN_PYTHON, then the repo venv, then us.
    import os
    brain_python = os.environ.get("BRAIN_PYTHON", "")
    if not brain_python:
        venv_py = repo_root / ".venv" / "bin" / "python"
        brain_python = str(venv_py) if venv_py.exists() else sys.executable

    # Trigger reflection in background
    try:
        reflect_script = hooks_dir / "run_reflect.py"
        subprocess.Popen(
            [brain_python, str(reflect_script)],
            cwd=str(repo_root),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        print("[BRAIN] Reflection scheduled in background.", file=sys.stderr)
    except Exception as e:
        print(f"[BRAIN] Reflection schedule failed (non-fatal): {e}", file=sys.stderr)

    # Automated cleanup: BVH dedup every session, noise detect every 20 sessions.
    try:
        cleanup_script = hooks_dir / "run_cleanup.py"
        subprocess.Popen(
            [brain_python, str(cleanup_script)],
            cwd=str(repo_root),
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
