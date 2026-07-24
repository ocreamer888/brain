#!/usr/bin/env python3
"""Cross-memory corroboration scorer + Phase-0 measurement (AlphaFold MSA analog).

READ-ONLY. Does NOT write the DB. See docs/plans/2026-06-10-corroboration-confidence-plan.md.

A memory is trustworthy when INDEPENDENT memories restate the same claim. For each
memory we count distinct sessions among its band-neighbors (cosine in [SUPPORT_MIN, DUP_MAX)):
  - >= DUP_MAX (0.97): near-duplicate, no new evidence (BVH's job) -> excluded
  - <  SUPPORT_MIN     : different claim -> not corroboration
  - distinct session_id among the rest = effective support (Neff proxy)
  corroboration = min(support, CAP) / CAP   in [0, 1]

Phase-0 experiments (all read-only):
  V1 gold-set ranking lift (before vs after corroboration-weighting)  <- primary gate
  V2 feedback correlation (accepted vs rejected corroboration)        <- weak, 6 linked events
  V3 face validity (top/bottom memories by corroboration)
  V4 calibration sweep over SUPPORT_MIN
  V5 leave-one-out self-retrieval lift on a larger sample

Usage:
    .venv/bin/python brain/tools/corroboration.py
"""
from __future__ import annotations

import json
import sqlite3
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np

_R = Path(__file__).resolve().parents[2]
if str(_R) not in sys.path:
    sys.path.insert(0, str(_R))

DB = _R / "brain" / "rust" / "brain.db"
GOLD_FILES = [
    _R / "brain" / "eval" / "gold_semantic.jsonl",
    _R / "brain" / "eval" / "gold_semantic_conversations.jsonl",
    _R / "brain" / "eval" / "gold_semantic_project_context.jsonl",
]
DUP_MAX = 0.97
SUPPORT_MIN = 0.60
CAP = 5
K_BAND = 50  # informational; band membership is the real filter
BETA = 0.3   # Trust-weight strength, mirrors brain.rs salience_w
W_LO, W_HI = 0.85, 1.15


def load_corpus_with_session(db_path):
    """Like retrieval_eval_kfold.load_corpus but also returns session_id codes."""
    conn = sqlite3.connect(str(db_path))
    rows = conn.execute(
        "SELECT id, type, project, title, content, session_id, embedding "
        "FROM memories WHERE embedding IS NOT NULL"
    ).fetchall()
    conn.close()

    metas, embs, sessions = [], [], []
    for mid, mtype, project, title, content, sess, blob in rows:
        e = np.frombuffer(blob, dtype="<f4")
        if e.shape[0] != 768:
            continue
        metas.append({"id": mid, "type": mtype or "unknown",
                      "project": project or "general", "title": (title or "").strip(),
                      "content": content or ""})
        embs.append(e)
        sessions.append(sess or "")
    M = np.vstack(embs).astype(np.float32)
    n = np.linalg.norm(M, axis=1, keepdims=True)
    n[n < 1e-10] = 1.0
    M /= n
    return metas, M, sessions


def session_codes(sessions):
    """Map session_id -> int. Empty session => unique negative code (counts as singleton)."""
    codes = np.empty(len(sessions), dtype=np.int64)
    lut, nxt = {}, 0
    for i, s in enumerate(sessions):
        if not s:
            codes[i] = -(i + 1)
        else:
            if s not in lut:
                lut[s] = nxt
                nxt += 1
            codes[i] = lut[s]
    return codes


def score_corroboration(M, codes, support_min, dup_max=DUP_MAX, cap=CAP, chunk=1000):
    """Return (corroboration[N] in [0,1], support_counts[N])."""
    N = M.shape[0]
    support = np.zeros(N, dtype=np.int32)
    t0 = time.time()
    for start in range(0, N, chunk):
        end = min(start + chunk, N)
        block = M[start:end] @ M.T  # (b, N)
        for r in range(end - start):
            i = start + r
            row = block[r]
            mask = (row >= support_min) & (row < dup_max)
            mask[i] = False
            if mask.any():
                support[i] = np.unique(codes[mask]).size
        if (end % 5000) == 0 or end == N:
            print(f"  corroboration {end}/{N} ({end/(time.time()-t0):.0f}/s)", file=sys.stderr)
    corr = np.minimum(support, cap) / cap
    return corr.astype(np.float32), support


def trust_w(corr):
    """Corroboration -> ranking multiplier, clamped like brain.rs salience_w."""
    return np.clip(1.0 + BETA * (corr - 0.5), W_LO, W_HI)


def load_gold():
    gold = []
    for gf in GOLD_FILES:
        if gf.exists():
            for line in gf.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line:
                    gold.append(json.loads(line))
    return gold


def rank_metrics(ranks, ks=(1, 5, 10)):
    n = len(ranks)
    out = {"n": n}
    for k in ks:
        out[f"p@{k}"] = round(sum(1 for r in ranks if r <= k) / max(1, n), 4)
    out["mrr"] = round(sum(1.0 / r for r in ranks) / max(1, n), 4)
    return out


def gold_lift(valid, id_to_idx, sims, corr):
    """V1: rank gold id before vs after corroboration weighting."""
    cw = trust_w(corr)  # (N,)
    ranks_base, ranks_w = [], []
    for qi, g in enumerate(valid):
        ti = id_to_idx[g["gold_memory_id"]]
        row = sims[qi]
        ranks_base.append(int((row > row[ti]).sum()) + 1)
        wrow = row * cw
        ranks_w.append(int((wrow > wrow[ti]).sum()) + 1)
    return rank_metrics(ranks_base), rank_metrics(ranks_w)


def main():
    print(f"Loading corpus from {DB}...", file=sys.stderr)
    metas, M, sessions = load_corpus_with_session(DB)
    N = len(metas)
    codes = session_codes(sessions)
    print(f"  {N} memories, {len(set(s for s in sessions if s))} distinct sessions", file=sys.stderr)

    print(f"Scoring corroboration (band [{SUPPORT_MIN}, {DUP_MAX}), cap {CAP})...", file=sys.stderr)
    corr, support = score_corroboration(M, codes, SUPPORT_MIN)

    # ---- embed gold queries once ----
    gold = load_gold()
    id_to_idx = {m["id"]: i for i, m in enumerate(metas)}
    valid = [g for g in gold if g["gold_memory_id"] in id_to_idx]
    missing = len(gold) - len(valid)
    from brain.core.embedder import embed_batch
    print(f"Embedding {len(valid)} gold queries...", file=sys.stderr)
    qv = np.asarray(embed_batch([g["query"] for g in valid]), dtype=np.float32)
    qn = np.linalg.norm(qv, axis=1, keepdims=True); qn[qn < 1e-10] = 1.0
    qv /= qn
    sims = qv @ M.T

    print("\n" + "=" * 70)
    print("PHASE-0 CORROBORATION MEASUREMENT")
    print("=" * 70)

    # distribution
    print(f"\nCORROBORATION DISTRIBUTION (full corpus, support_min={SUPPORT_MIN}):")
    print(f"  mean={corr.mean():.3f}  support: mean={support.mean():.2f} max={support.max()} "
          f"| isolated(support=0): {int((support==0).sum())} ({100*(support==0).mean():.1f}%)")
    for s in range(0, CAP + 1):
        c = int((support == s).sum()) if s < CAP else int((support >= s).sum())
        lbl = f"{s}" if s < CAP else f"{s}+"
        print(f"  support={lbl:>2}: {c:>6} ({100*c/N:>4.1f}%)")

    # V1
    mb, mw = gold_lift(valid, id_to_idx, sims, corr)
    print(f"\nV1 GOLD-SET RANKING LIFT (n={mb['n']}, {missing} gold IDs missing)")
    print(f"  {'metric':<6} {'BEFORE':>8} {'AFTER':>8} {'delta':>8}")
    for k in ["p@1", "p@5", "p@10", "mrr"]:
        print(f"  {k:<6} {mb[k]:>8.4f} {mw[k]:>8.4f} {mw[k]-mb[k]:>+8.4f}")

    # V2
    print("\nV2 FEEDBACK CORRELATION (weak: few linked events)")
    conn = sqlite3.connect(str(DB))
    fb = conn.execute("SELECT event_type, memory_id FROM feedback_events WHERE memory_id IS NOT NULL").fetchall()
    conn.close()
    buckets = defaultdict(list)
    for et, mid in fb:
        if mid in id_to_idx:
            buckets[et].append(corr[id_to_idx[mid]])
    for et in ("accepted", "rejected", "edited"):
        vals = buckets.get(et, [])
        if vals:
            print(f"  {et:<9} n={len(vals)}  mean_corroboration={np.mean(vals):.3f}")
        else:
            print(f"  {et:<9} n=0  (no linked-to-corpus events)")

    # V3
    print("\nV3 FACE VALIDITY")
    order = np.argsort(-support)
    print("  TOP corroborated:")
    for i in order[:6]:
        print(f"    [support={support[i]} corr={corr[i]:.2f}] ({metas[i]['type']}) {metas[i]['title'][:55]}")
    print("  ISOLATED (support=0) sample:")
    iso = np.where(support == 0)[0]
    for i in iso[:6]:
        print(f"    [support=0] ({metas[i]['type']}) {metas[i]['title'][:55]}")

    # V4 calibration sweep
    print("\nV4 CALIBRATION SWEEP (support_min -> gold lift)")
    print(f"  {'s_min':>6} {'isolated%':>9} {'mean_sup':>8} | {'dP@1':>7} {'dMRR':>7}")
    for sm in [0.55, 0.60, 0.65, 0.70]:
        c2, sup2 = score_corroboration(M, codes, sm)
        b2, w2 = gold_lift(valid, id_to_idx, sims, c2)
        print(f"  {sm:>6} {100*(sup2==0).mean():>8.1f}% {sup2.mean():>8.2f} | "
              f"{w2['p@1']-b2['p@1']:>+7.4f} {w2['mrr']-b2['mrr']:>+7.4f}")

    # V5 leave-one-out lift (larger sample, re-embed titles as queries)
    print("\nV5 LEAVE-ONE-OUT LIFT (sample, title->self retrieval)")
    rng = np.random.default_rng(42)
    cand = [i for i in range(N) if len(metas[i]["title"]) >= 12]
    samp = rng.choice(cand, size=min(800, len(cand)), replace=False)
    tq = embed_batch([metas[i]["title"] for i in samp])
    tq = np.asarray(tq, dtype=np.float32)
    tn = np.linalg.norm(tq, axis=1, keepdims=True); tn[tn < 1e-10] = 1.0
    tq /= tn
    tsims = tq @ M.T
    cw = trust_w(corr)
    rb, rw = [], []
    for j, i in enumerate(samp):
        row = tsims[j]
        rb.append(int((row > row[i]).sum()) + 1)
        wrow = row * cw
        rw.append(int((wrow > wrow[i]).sum()) + 1)
    lb, lw = rank_metrics(rb), rank_metrics(rw)
    print(f"  {'metric':<6} {'BEFORE':>8} {'AFTER':>8} {'delta':>8}")
    for k in ["p@1", "p@5", "p@10", "mrr"]:
        print(f"  {k:<6} {lb[k]:>8.4f} {lw[k]:>8.4f} {lw[k]-lb[k]:>+8.4f}")

    print("\nGATE: ship to Phase 1 only if V1 OR V5 shows >= +0.02 P@1 or MRR lift.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
