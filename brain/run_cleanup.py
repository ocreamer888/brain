#!/usr/bin/env python3
"""Background cleanup runner — called by session_end hook.

Every session: BVH dedup (exact-copy removal, ~2s)
Every 20 sessions: Noise detection + eval regression check (~30s total)

All auto-delete with logging to brain/hooks/cleanup.log.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

LOG = Path(__file__).parent / "cleanup.log"
COUNTER_FILE = Path(__file__).parent / "spool" / "cleanup_counter.json"
NOISE_EVERY_N = 20


def _log(msg: str) -> None:
    with LOG.open("a", encoding="utf-8") as f:
        f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")


def _load_counter() -> int:
    try:
        if COUNTER_FILE.exists():
            return json.loads(COUNTER_FILE.read_text()).get("count", 0)
    except Exception:
        pass
    return 0


def _save_counter(n: int) -> None:
    COUNTER_FILE.parent.mkdir(parents=True, exist_ok=True)
    COUNTER_FILE.write_text(json.dumps({"count": n}))


def run_title_dedup() -> None:
    """Title-based dedup: remove duplicate project_context summaries with same (project, title).

    Catches cases BVH misses — same session summarized multiple times with different LLM wording.
    """
    import sqlite3
    from brain.api_client import delete_memories

    db_path = Path(__file__).resolve().parents[1] / "rust" / "brain.db"
    if not db_path.exists():
        return

    conn = sqlite3.connect(str(db_path))
    rows = conn.execute(
        """SELECT project, title, GROUP_CONCAT(id) as ids
           FROM memories WHERE type='"project_context"' AND title IS NOT NULL
           GROUP BY project, title HAVING COUNT(*) > 1"""
    ).fetchall()
    conn.close()

    ids_to_delete = []
    for _, _, id_str in rows:
        all_ids = id_str.split(",")
        ids_to_delete.extend(all_ids[1:])

    if ids_to_delete:
        deleted = delete_memories(ids_to_delete)
        _log(f"title_dedup: deleted {deleted} duplicate project_context summaries from {len(rows)} groups")
    else:
        _log("title_dedup: clean (0 title duplicates)")


def run_bvh_dedup() -> None:
    """BVH dedup: find and delete exact-copy duplicates."""
    from brain.tools.bvh_dedup import run as bvh_run

    db_path = Path(__file__).resolve().parents[1] / "rust" / "brain.db"
    if not db_path.exists():
        return

    report = bvh_run(
        db_path=db_path,
        threshold=0.97,
        chunk=1000,
        delete=True,
        narrow_prefix=300,
    )

    n_deleted = report.get("n_to_delete", 0)
    n_clusters = report.get("n_clusters", 0)
    if n_deleted > 0:
        _log(f"bvh_dedup: deleted {n_deleted} duplicates from {n_clusters} clusters")
    else:
        _log(f"bvh_dedup: clean (0 duplicates)")


def run_noise_detect() -> None:
    """Noise detection: find and delete high-fragility memories."""
    from brain.tools.noise_detect import run as noise_run
    from brain.api_client import delete_memories

    db_path = Path(__file__).resolve().parents[1] / "rust" / "brain.db"
    if not db_path.exists():
        return

    FRAGILITY_DELETE_THRESHOLD = 0.95

    report = noise_run(
        db_path=db_path,
        sample=2000,
        sigma=0.05,
        k=10,
        trials=5,
        seed=42,
        threshold=FRAGILITY_DELETE_THRESHOLD,
        full=False,
    )

    worst = report.get("worst_100", [])
    to_delete = [m["id"] for m in worst if m["fragility"] >= FRAGILITY_DELETE_THRESHOLD]

    if to_delete:
        deleted = delete_memories(to_delete)
        _log(f"noise_detect: deleted {deleted} high-fragility memories (fragility>=0.95)")
        for m in worst[:10]:
            if m["fragility"] >= 0.95:
                _log(f"  [{m['fragility']:.3f}] ({m['type']}/{m['project']}) {m['title'][:60]}")
    else:
        overall = report.get("overall", {})
        _log(f"noise_detect: clean (mean_fragility={overall.get('mean_fragility', '?')}, 0 above 0.95)")


def run_eval_check() -> None:
    """Quick gate + MCP eval. Log warnings if regression thresholds breached."""
    try:
        from brain.api_client import BrainApiError

        # Quick gate
        from brain.tools.eval_suite import run_suite
        result = run_suite(
            modes={"quick_gate", "mcp_path"},
            quiet=True,
        )
        report = result.to_dict()

        qg = report.get("quick_gate") or {}
        if qg.get("status") == "ok":
            by_type = qg.get("by_type", {})
            for t, p1 in by_type.items():
                if isinstance(p1, (int, float)) and p1 < 0.45:
                    _log(f"REGRESSION quick_gate: {t} P@1={p1:.3f} (below 0.45 threshold)")

        mcp = report.get("mcp_path") or {}
        if mcp.get("status") == "ok":
            p1 = mcp.get("precision_at_1", 0)
            gap = mcp.get("gap_vs_kfold_p1")
            _log(f"eval_check: MCP P@1={p1:.3f}" + (f" gap={gap:.3f}" if gap is not None else ""))
            if gap is not None and gap < -0.30:
                _log(f"REGRESSION mcp_path: gap={gap:.3f} exceeds -0.30 threshold")
        elif mcp.get("status") == "skipped":
            _log(f"eval_check: MCP skipped (brain_api not reachable)")
    except Exception as e:
        _log(f"eval_check failed: {e}")


try:
    counter = _load_counter()
    counter += 1
    _save_counter(counter)

    # Title dedup + BVH dedup every session
    run_title_dedup()
    run_bvh_dedup()

    # Noise detection + eval check every N sessions
    if counter % NOISE_EVERY_N == 0:
        run_noise_detect()
        run_eval_check()

except Exception as e:
    _log(f"cleanup failed: {e}")
