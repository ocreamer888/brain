#!/usr/bin/env python3
"""Backfill memory_links (relation_type='layers_on') from the deterministic
candidate tiers (spec §8.5), gated through brain/ingest/layer_judgment.py's
LLM judgement step (spec §8.7a proposal B, validated in
docs/architecture/experiments/2026-11-06-layer-judgment-gate/).

Deterministic tiers alone only hit ~33% precision at deciding whether a
candidate pair is actually the same evolving subject (2026-10-21
experiment). This backfill never writes a link from tier membership alone;
every candidate is judged, and only a LAYER verdict produces a row.

Candidate generation (same project required, spec §8.5a -- cross-project
layering is never inferred; both sides must be currently active, i.e. not
superseded, since a hidden row's depth has no observable ranking effect):
  Tier 1: exact same file_path, both non-null.
  Tier 2: shared specific entity, 2 <= df(entity) <= D_MAX.
Deduplicated into one (older, newer) pair set by ingest `timestamp` (not
event_time -- see the 2026-10-21 experiment on placeholder-dated facts),
then filtered by MIN_CANDIDATE_SIM before judgement.

Safety: read-only unless --apply is passed. --apply creates memory_links
(idempotent CREATE TABLE IF NOT EXISTS, identical schema to
brain/rust/src/store.rs so the live Rust binary reads the same shape) and
inserts judged-LAYER rows with ON CONFLICT DO NOTHING -- purely additive,
never deletes or overwrites a memory row. Every run writes a JSON report
(counts + every judged pair) for audit, dry run or not.

Usage:
    ./.venv/bin/python3 brain/tools/backfill_layer_links.py --count-only
    ./.venv/bin/python3 brain/tools/backfill_layer_links.py                 # dry run: judges, does not write
    ./.venv/bin/python3 brain/tools/backfill_layer_links.py --apply         # judges AND writes memory_links
    ./.venv/bin/python3 brain/tools/backfill_layer_links.py --project brain
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import time
import uuid
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from brain.ingest.layer_judgment import classify_pair, MIN_CANDIDATE_SIM

D_MAX = 20  # entity document-frequency cap, matches the 2026-10-21 experiment
DB_PATH = REPO_ROOT / "brain" / "rust" / "brain.db"
RELATION_TYPE = "layers_on"

CREATE_MEMORY_LINKS = """
CREATE TABLE IF NOT EXISTS memory_links (
    id TEXT PRIMARY KEY,
    src_memory_id TEXT NOT NULL,
    dst_memory_id TEXT NOT NULL,
    relation_type TEXT NOT NULL,
    weight REAL NOT NULL DEFAULT 1.0,
    created_at TEXT NOT NULL,
    UNIQUE(src_memory_id, dst_memory_id, relation_type)
);
"""


CHUNK_GROUP_RE = re.compile(r"^(reingest_.+)_\d+$")


def chunk_group(session_id: str | None) -> str | None:
    """Documents re-ingested in chunks get session_id = reingest_<doc-slug>_<N>
    (verified live, 2026-11-06: 43 rows, e.g. reingest_sicop_api_reference_v3_0..3).
    Two memories sharing a chunk_group are sibling sections of ONE document,
    never a layer of each other -- the spec's own caveat ("chunked documents
    need a section key, not just file_path") caught this before it was ever
    observed; the 2026-11-06 spot-check of 32 live-judged pairs found the LLM
    judgement step cannot reliably tell siblings from real updates from text
    alone, so this is filtered at candidate generation instead."""
    if not session_id:
        return None
    m = CHUNK_GROUP_RE.match(session_id)
    return m.group(1) if m else None


def load_active_memories(conn: sqlite3.Connection, project: str | None):
    """id -> (type, project, content, timestamp, file_path, unit_vec|None, session_id)."""
    sql = (
        "SELECT id, TRIM(type,'\"'), project, content, timestamp, file_path, embedding, session_id "
        "FROM memories WHERE superseded_by IS NULL"
    )
    args: list = []
    if project:
        sql += " AND project = ?"
        args.append(project)
    out = {}
    for mid, t, p, c, ts, fp, emb, sid in conn.execute(sql, args):
        vec = None
        if emb is not None:
            v = np.frombuffer(emb, dtype="<f4")
            n = np.linalg.norm(v)
            if n > 0:
                vec = v / n
        out[mid] = (t, p, c, ts, fp, vec, sid)
    return out


def tier1_file_path_pairs(live: dict) -> set[tuple[str, str]]:
    by_path: dict[tuple[str, str], list[str]] = defaultdict(list)
    for mid, (_t, p, _c, _ts, fp, _v, _sid) in live.items():
        if fp:
            by_path[(p, fp)].append(mid)
    pairs = set()
    for (_p, _fp), ids in by_path.items():
        if len(ids) < 2:
            continue
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                a, b = ids[i], ids[j]
                if chunk_group(live[a][6]) and chunk_group(live[a][6]) == chunk_group(live[b][6]):
                    continue  # sibling chunks of one ingested document, never a layer
                old, new = (a, b) if live[a][3] < live[b][3] else (b, a)
                pairs.add((old, new))
    return pairs


def tier2_entity_pairs(conn: sqlite3.Connection, live: dict, project: str | None) -> set[tuple[str, str]]:
    sql = (
        "SELECT g.src_memory_id, e.id, e.name FROM edges g "
        "JOIN entities e ON e.id = g.dst_entity_id"
    )
    by_ent: dict[str, list[str]] = defaultdict(list)
    names: dict[str, str] = {}
    for mid, eid, name in conn.execute(sql):
        if mid in live:
            by_ent[eid].append(mid)
            names[eid] = name

    pairs = set()
    for eid, mids in by_ent.items():
        uniq = list(dict.fromkeys(mids))
        if not (2 <= len(uniq) <= D_MAX) or len(names[eid]) < 3:
            continue
        for i in range(len(uniq)):
            for j in range(i + 1, len(uniq)):
                a, b = uniq[i], uniq[j]
                if live[a][1] != live[b][1]:  # same project required (spec §8.5a)
                    continue
                if chunk_group(live[a][6]) and chunk_group(live[a][6]) == chunk_group(live[b][6]):
                    continue  # sibling chunks of one ingested document, never a layer
                old, new = (a, b) if live[a][3] < live[b][3] else (b, a)
                pairs.add((old, new))
    return pairs


def cosine(live: dict, old_id: str, new_id: str) -> float | None:
    v_old, v_new = live[old_id][5], live[new_id][5]
    if v_old is None or v_new is None:
        return None
    return float(v_old @ v_new)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default=None)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--count-only", action="store_true")
    ap.add_argument("--limit", type=int, default=None, help="cap judged pairs, for a bounded trial run")
    args = ap.parse_args()

    mode = "ro" if not args.apply else "rwc"
    conn = sqlite3.connect(f"file:{DB_PATH}?mode={mode}", uri=True)

    live = load_active_memories(conn, args.project)
    print(f"active (non-superseded) memories in scope: {len(live)}", flush=True)

    t1 = tier1_file_path_pairs(live)
    t2 = tier2_entity_pairs(conn, live, args.project)
    all_pairs = t1 | t2
    print(f"tier 1 (file_path) candidate pairs: {len(t1)}", flush=True)
    print(f"tier 2 (shared specific entity, 2<=df<={D_MAX}) candidate pairs: {len(t2)}", flush=True)
    print(f"union, deduplicated: {len(all_pairs)}", flush=True)

    with_sim = []
    no_embedding = 0
    for old_id, new_id in all_pairs:
        sim = cosine(live, old_id, new_id)
        if sim is None:
            no_embedding += 1
            continue
        with_sim.append((old_id, new_id, sim))
    above_floor = [p for p in with_sim if p[2] >= MIN_CANDIDATE_SIM]
    print(f"pairs missing an embedding on one side: {no_embedding}", flush=True)
    print(f"pairs at/above MIN_CANDIDATE_SIM={MIN_CANDIDATE_SIM}: {len(above_floor)} "
          f"(of {len(with_sim)} with both embeddings)", flush=True)

    if args.count_only:
        return

    if args.apply:
        conn.executescript(CREATE_MEMORY_LINKS)

    above_floor.sort(key=lambda p: -p[2])
    if args.limit:
        above_floor = above_floor[: args.limit]

    # Incremental, append-as-we-go audit log (flushed every line) so a
    # multi-hour run's progress survives a kill/crash -- the alternative
    # (holding one big list + writing it once at the end, like the first
    # version of this script did) matched holding one giant uncommitted DB
    # transaction for the same duration: both lose everything on interrupt.
    # This also makes `tail -f` on the log meaningful despite stdout being
    # fully buffered when redirected to a file.
    audit_path = Path(__file__).resolve().parent.parent / "eval" / "runs" / f"layer-backfill-{int(time.time())}.jsonl"
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    audit_f = audit_path.open("w")

    judged = []
    errors = 0
    written = 0
    t0 = time.time()
    for i, (old_id, new_id, sim) in enumerate(above_floor, 1):
        old_c, new_c = live[old_id][2], live[new_id][2]
        try:
            verdict = classify_pair(old_c, new_c, sim)
        except Exception as e:  # noqa: BLE001
            errors += 1
            continue
        rec = {
            "old_id": old_id, "new_id": new_id, "sim": sim,
            "old_project": live[old_id][1], "label": verdict.label,
            "reason": verdict.reason,
        }
        judged.append(rec)
        audit_f.write(json.dumps(rec) + "\n")
        audit_f.flush()
        if verdict.label == "LAYER" and args.apply:
            conn.execute(
                "INSERT INTO memory_links (id, src_memory_id, dst_memory_id, relation_type, weight, created_at) "
                "VALUES (?, ?, ?, ?, ?, datetime('now')) "
                "ON CONFLICT(src_memory_id, dst_memory_id, relation_type) DO NOTHING",
                (str(uuid.uuid4()), new_id, old_id, RELATION_TYPE, sim),
            )
            conn.commit()  # commit per-row, not once at the end -- see note above
            written += 1
        if i % 25 == 0:
            print(f"  judged {i}/{len(above_floor)} ({time.time()-t0:.0f}s elapsed, "
                  f"{written} written so far)", flush=True)

    audit_f.close()
    elapsed = time.time() - t0
    label_counts = Counter(r["label"] for r in judged)
    print(f"\njudged {len(judged)} pairs in {elapsed:.0f}s, {errors} errors", flush=True)
    print(f"label distribution: {dict(label_counts)}", flush=True)
    if args.apply:
        print(f"memory_links rows written (ON CONFLICT DO NOTHING applied): {written}", flush=True)
    else:
        print(f"DRY RUN -- {label_counts.get('LAYER', 0)} would-be LAYER rows NOT written. Pass --apply to write.", flush=True)
    print(f"audit log: {audit_path}", flush=True)


if __name__ == "__main__":
    main()
