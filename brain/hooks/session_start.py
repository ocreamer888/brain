#!/usr/bin/env python3
"""
SessionStart hook — loads relevant context from brain at session start.
"""
import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

PROJECT_DIR_MAP = {
    "lifehub": "lifehub",
    "LifeHub": "lifehub",
    "wealth": "wealth",
    "Wealth": "wealth",
    "le-chandelier": "le_chandelier",
    "Le Chandelier": "le_chandelier",
    "lechandelier": "le_chandelier",
    "meddefi": "meddefi",
    "MedDeFi": "meddefi",
    "ocreamer": "ocreamer",
    "OCREAMER": "ocreamer",
    "owelign": "owelign",
    "OWELIGN": "owelign",
    "qol": "qol",
    "QOL": "qol",
    "rmt": "rmt",
    "RMT": "rmt",
    "sicop": "sicop",
    "SICOP": "sicop",
    "tayasal": "tayasal",
    "Tayasal": "tayasal",
    "scheduler": "scheduler",
    "inventario": "inventario",
    "AI": "AI",
}


def detect_project(cwd: str) -> str | None:
    parts = Path(cwd).parts
    for part in reversed(parts):
        if part in PROJECT_DIR_MAP:
            return PROJECT_DIR_MAP[part]
    return None


def extract_date(timestamp: str | None) -> str:
    """Extract YYYY-MM-DD from an RFC3339 timestamp string."""
    if not timestamp:
        return "unknown"
    try:
        return str(timestamp)[:10]
    except Exception:
        return "unknown"


def filter_session_summaries(memories: list) -> list:
    """Return only session_summary-tagged memories, sorted newest first."""
    summaries = [
        m for m in memories
        if "session_summary" in (m.get("metadata", {}).get("tags") or "")
    ]
    summaries.sort(
        key=lambda m: m.get("metadata", {}).get("timestamp", ""),
        reverse=True,
    )
    return summaries


def build_query(summaries: list, fallback: str) -> str:
    """Use last session summary text as query; fall back to provided string."""
    if summaries:
        return summaries[0]["content"].split("\n")[0][:300]
    return fallback


# ── Background recovery (DISABLED) ──────────────────────────────────────────
# 10_ingest_missed_sessions.py creates raw "Claude Code session:" blobs that
# pollute the corpus. Session summaries are handled by session_end.py's 3-pass
# recycling loop. Automated cleanup (run_cleanup.py) handles dedup. This
# recovery path is no longer needed and was the source of 450+ junk memories.
#
# To re-enable for one-off backfill: run manually with
#   python3 brain/bootstrap/10_ingest_missed_sessions.py

if __name__ == "__main__":
    try:
        cwd = os.getcwd()
        project = detect_project(cwd)
        project_hint = project or Path(cwd).name

        from brain.api_client import search, get_stats

        raw_summaries = search(query="session summary", n=20, memory_type="project_context", project=project_hint)
        recent_summaries = filter_session_summaries(raw_summaries)[:3]

        if recent_summaries:
            dates = [extract_date(m["metadata"].get("timestamp")) for m in recent_summaries]
            print(f"[session_start] loaded_recent_summaries project={project_hint} count={len(recent_summaries)} dates={dates}", file=sys.stderr)
        else:
            print(f"[session_start] loaded_recent_summaries project={project_hint} count=0 fallback_query={project_hint!r}", file=sys.stderr)

        semantic_query = build_query(recent_summaries, fallback=project_hint)
        query_source = "last_session_summary" if recent_summaries else "fallback"
        print(f"[session_start] semantic_query_source={query_source}", file=sys.stderr)

        semantic_mems = []
        if project and project != "general":
            semantic_mems.extend(search(query=semantic_query, n=5, project=project))
        general_mems = search(query=semantic_query, n=5)
        seen = {m["content"][:80] for m in recent_summaries + semantic_mems}
        for m in general_mems:
            if m["content"][:80] not in seen:
                semantic_mems.append(m)
                seen.add(m["content"][:80])
        semantic_mems = [
            m for m in semantic_mems
            if "session_summary" not in (m.get("metadata", {}).get("tags") or "")
        ][:5]

        stats = get_stats()

        if recent_summaries:
            print(f"\n[BRAIN] Recent sessions for '{project_hint}':")
            for i, m in enumerate(recent_summaries, 1):
                date = extract_date(m["metadata"].get("timestamp"))
                title = m["metadata"].get("title") or f"Session {date}"
                print(f"  [S{i}] ({date}) {title}")
                for line in m["content"].split("\n")[:4]:
                    if line.strip():
                        print(f"       {line.strip()}")
            print()

        if semantic_mems:
            print(f"[BRAIN] Relevant memories for '{project_hint}':")
            for i, m in enumerate(semantic_mems, 1):
                meta = m["metadata"]
                src = meta.get("source", "")
                src_label = f" [{src}]" if src else ""
                date = extract_date(meta.get("timestamp"))
                mem_type = meta.get("type", "?")
                print(f"  [{i}] ({mem_type}, {date}{src_label}) {m['content'][:200]}")
            print()

        print(f"[BRAIN] Total: {stats['total_memories']} memories | {stats['total_sessions']} sessions\n")

    except Exception as e:
        print(f"[BRAIN] Context load failed (non-fatal): {e}", file=sys.stderr)
