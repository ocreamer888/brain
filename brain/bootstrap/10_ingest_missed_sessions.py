#!/usr/bin/env python3
"""
Recover Claude Code sessions that were never ingested because the terminal
was closed instead of using /exit (which fires the Stop hook).

Scans ~/.claude/projects/**/*.jsonl, finds sessions not yet in the brain,
converts them to the sessions_export format, and runs 07_ingest_claude_code.py.

Safe to run multiple times — idempotent via checkpoint and session_id check.
"""
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

CLAUDE_PROJECTS = Path.home() / ".claude" / "projects"
REPO_ROOT = Path(__file__).resolve().parents[2]
SESSIONS_EXPORT = REPO_ROOT / "brain" / "bootstrap" / "sessions_export"
INGEST_SCRIPT = REPO_ROOT / "brain" / "bootstrap" / "07_ingest_claude_code.py"
DB_PATH = REPO_ROOT / "brain" / "rust" / "brain.db"


def get_ingested_session_ids() -> set[str]:
    """Return session_ids already present in the brain SQLite."""
    if not DB_PATH.exists():
        return set()
    try:
        conn = sqlite3.connect(str(DB_PATH))
        rows = conn.execute(
            "SELECT DISTINCT session_id FROM memories WHERE session_id != ''"
        ).fetchall()
        conn.close()
        return {r[0] for r in rows}
    except Exception:
        return set()


def get_checkpoint_files() -> set[str]:
    """Return filenames already processed by 07_ingest_claude_code.py."""
    checkpoint = REPO_ROOT / "brain" / "bootstrap" / "checkpoint_claude_code.json"
    if not checkpoint.exists():
        return set()
    try:
        data = json.loads(checkpoint.read_text())
        return set(data.get("processed", {}).keys())
    except Exception:
        return set()


def scan_jsonl_files() -> list[Path]:
    """Find all Claude Code session JSONL files, excluding subagent files."""
    return [
        p for p in CLAUDE_PROJECTS.rglob("*.jsonl")
        if "subagents" not in p.parts
    ]


def extract_session_id(path: Path) -> str | None:
    """Extract sessionId from the first line that has one."""
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                d = json.loads(line)
                sid = d.get("sessionId")
                if sid:
                    return sid
    except Exception:
        pass
    return None


def convert_to_export(path: Path) -> dict | None:
    """Convert a raw Claude Code JSONL to the sessions_export JSON format."""
    try:
        lines = []
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line:
                    lines.append(json.loads(line))

        session_id = None
        cwd = None
        last_ts = None
        messages = []

        for entry in lines:
            if not session_id:
                session_id = entry.get("sessionId")
            if not cwd:
                cwd = entry.get("cwd")
            ts = entry.get("timestamp")
            if ts:
                last_ts = ts

            if entry.get("type") in ("user", "assistant") and entry.get("message"):
                msg = entry["message"]
                if not isinstance(msg, dict):
                    continue
                content = msg.get("content", "")
                if isinstance(content, list):
                    text = " ".join(
                        p.get("text", "")
                        for p in content
                        if isinstance(p, dict) and p.get("type") == "text"
                    )
                else:
                    text = str(content)
                text = text.strip()
                if text:
                    messages.append({
                        "role": msg.get("role", entry["type"]),
                        "content": text[:500],
                    })

        if not session_id:
            return None

        project = Path(cwd).name if cwd else path.stem

        return {
            "session_id": session_id,
            "project": project,
            "cwd": cwd or "",
            "ended_at": last_ts or "",
            "transcript_path": str(path),
            "message_count": len(messages),
            "messages": messages,
        }
    except Exception as e:
        print(f"[10_ingest_missed] Failed to convert {path.name}: {e}", file=sys.stderr)
        return None


def main():
    SESSIONS_EXPORT.mkdir(parents=True, exist_ok=True)

    ingested = get_ingested_session_ids()
    checkpoint_files = get_checkpoint_files()
    jsonl_files = scan_jsonl_files()

    new_files = 0
    for path in jsonl_files:
        sid = extract_session_id(path)
        if not sid:
            continue

        # Skip if already in brain
        if sid in ingested:
            continue

        # Skip if already converted and checkpointed
        export_name = f"recovered_{sid[:8]}.json"
        if export_name in checkpoint_files:
            continue

        export_path = SESSIONS_EXPORT / export_name
        # Skip if already converted (file exists, just not yet ingested)
        if export_path.exists():
            continue

        data = convert_to_export(path)
        if not data:
            continue

        export_path.write_text(json.dumps(data, indent=2))
        new_files += 1

    if new_files == 0:
        print("[10_ingest_missed] No new sessions to recover.", file=sys.stderr)
        return

    print(f"[10_ingest_missed] Converted {new_files} missed sessions. Running ingest...", file=sys.stderr)

    result = subprocess.run(
        [sys.executable, str(INGEST_SCRIPT), "--no-llm"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    # Print last few lines of output
    lines = (result.stdout + result.stderr).strip().splitlines()
    for line in lines[-5:]:
        print(f"[10_ingest_missed] {line}", file=sys.stderr)


if __name__ == "__main__":
    main()
