#!/usr/bin/env python3
"""Repeatable benchmark + calibration harness for the knowledge memory type.

Measures, against a RUNNING brain_api (default the isolated calibration instance
on :8790, never the live :8787 service):

  * quality     — P@1 / P@5 / recall@10 / MRR on a seeded self-retrieve gold set
                  of NON-knowledge rows (regression guard: the knowledge prior
                  must not knock these off rank 1).
  * latency     — /search p50/p95/p99 over a fixed warm query batch.
  * freshness   — save -> searchable latency (p95 over N trials).
  * distances   — cosine distance of the top knowledge hit for corpus-hitting
                  vs off-corpus queries; percentiles + grounding-band per query.

The grounding-hint logic is a faithful re-implementation of
``brain/mcp/server.py::_grounding_hint``; the tau constants are PARSED from
source (brain.rs + server.py) at runtime so a band-reachability proof always
reflects the constants actually shipped, and the Rust<->Python mirror invariant
is asserted.

Usage:
    python3 brain/tools/bench_knowledge.py all \
        --api http://127.0.0.1:8790 --db /tmp/calib/brain.db \
        --label baseline --out docs/superpowers/specs/bench_baseline.json

    python3 brain/tools/bench_knowledge.py distances \
        --api http://127.0.0.1:8790 \
        --hits brain/eval/knowledge_hit_queries.jsonl \
        --miss brain/eval/knowledge_miss_queries.jsonl
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sqlite3
import statistics
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
_RUST_BRAIN = _REPO_ROOT / "brain" / "rust" / "src" / "brain.rs"
_MCP_SERVER = _REPO_ROOT / "brain" / "mcp" / "server.py"

# Non-knowledge types eligible for the self-retrieve regression gold set.
_GOLD_TYPES = ("solution", "conversation", "pattern", "project_context",
               "decision", "error_lesson", "fact")


# ---------------------------------------------------------------------------
# tau constants (parsed from source, mirror-checked)
# ---------------------------------------------------------------------------
def parse_rust_tau(path: Path = _RUST_BRAIN) -> tuple[float, float]:
    txt = path.read_text(encoding="utf-8")
    close = re.search(r"KNOWLEDGE_TAU_CLOSE:\s*f32\s*=\s*([0-9.]+)", txt)
    far = re.search(r"KNOWLEDGE_TAU_FAR:\s*f32\s*=\s*([0-9.]+)", txt)
    if not (close and far):
        raise RuntimeError("could not parse KNOWLEDGE_TAU_* from brain.rs")
    return float(close.group(1)), float(far.group(1))


def parse_py_tau(path: Path = _MCP_SERVER) -> tuple[float, float]:
    txt = path.read_text(encoding="utf-8")
    close = re.search(r"_TAU_CLOSE\s*=\s*([0-9.]+)", txt)
    far = re.search(r"_TAU_FAR\s*=\s*([0-9.]+)", txt)
    if not (close and far):
        raise RuntimeError("could not parse _TAU_* from server.py")
    return float(close.group(1)), float(far.group(1))


def resolved_tau() -> tuple[float, float]:
    """Parsed tau, asserting the Rust<->Python mirror invariant (spec 2026-08-06)."""
    r_close, r_far = parse_rust_tau()
    p_close, p_far = parse_py_tau()
    if (r_close, r_far) != (p_close, p_far):
        raise SystemExit(
            f"tau mirror BROKEN: rust=({r_close},{r_far}) python=({p_close},{p_far})"
        )
    return r_close, r_far


def grounding_hint(results: list[dict], project: str, tau_close: float,
                   tau_far: float) -> str:
    """Faithful copy of server.py::_grounding_hint, tau injected."""
    know = [r for r in results if (r.get("metadata") or {}).get("type") == "knowledge"]
    if not know:
        return "off"
    know_ids = {id(r) for r in know}
    others = [r for r in results if id(r) not in know_ids]
    d_star = 1.0
    for r in know:
        try:
            d_star = min(d_star, float(r.get("distance")))
        except (TypeError, ValueError):
            pass

    def score_of(r: dict) -> float | None:
        try:
            return float(r["score"])
        except (KeyError, TypeError, ValueError):
            return None

    k_scores = [s for s in (score_of(r) for r in know) if s is not None]
    o_scores = [s for s in (score_of(r) for r in others) if s is not None]
    leads = bool(k_scores) and (not o_scores or max(k_scores) >= max(o_scores))
    if d_star > tau_far and not leads:
        return "off"
    project_match = bool(project) and any(
        (r.get("metadata") or {}).get("project") == project for r in know
    )
    if (d_star <= tau_close or leads) and (project_match or leads):
        return "hard"
    return "soft"


# ---------------------------------------------------------------------------
# HTTP client
# ---------------------------------------------------------------------------
def api_post(base: str, key: str, path: str, body: dict, timeout: float = 30.0) -> dict:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(base.rstrip("/") + path, data=data, method="POST")
    req.add_header("content-type", "application/json")
    if key:
        req.add_header("x-api-key", key)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def search(base: str, key: str, query: str, n: int = 10, memory_type: str = "",
           project: str = "") -> tuple[list[dict], float]:
    body: dict[str, Any] = {"query": query, "n": n}
    if memory_type:
        body["memory_type"] = memory_type
    if project:
        body["project"] = project
    t0 = time.perf_counter()
    out = api_post(base, key, "/search", body)
    dt = (time.perf_counter() - t0) * 1000.0
    return out.get("results", []), dt


# ---------------------------------------------------------------------------
# gold set (self-retrieve, non-knowledge)
# ---------------------------------------------------------------------------
def build_gold(db: Path, out: Path, n: int, seed: int) -> list[dict]:
    """Sample live non-knowledge rows -> {query, gold_memory_id, type}.

    query = a middle slice of the content (chars 40..200) so retrieval leans on
    semantics, not an exact-prefix BM25 gimme. Persisted for reuse across the
    baseline/after runs so both score the identical set.
    """
    if out.exists():
        return [json.loads(l) for l in out.read_text().splitlines() if l.strip()]
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    rng = random.Random(seed)
    per_type = max(1, n // len(_GOLD_TYPES))
    rows: list[dict] = []
    for t in _GOLD_TYPES:
        cur = conn.execute(
            """SELECT id, content FROM memories
               WHERE type = ? AND superseded_by IS NULL
                 AND length(content) >= 120""",
            (json.dumps(t),),  # type column stores serde JSON ('"solution"')
        ).fetchall()
        rng.shuffle(cur)
        for mid, content in cur[:per_type]:
            q = content[40:200].strip()
            if len(q) < 40:
                continue
            rows.append({"query": q, "gold_memory_id": mid, "type": t})
    conn.close()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    return rows


def quality(base: str, key: str, gold: list[dict]) -> dict:
    p1 = p5 = r10 = 0
    mrr = 0.0
    n = 0
    misses = []
    for g in gold:
        results, _ = search(base, key, g["query"], n=10)
        ids = [r.get("id", "") for r in results]
        gid = g["gold_memory_id"]
        n += 1
        rank = ids.index(gid) + 1 if gid in ids else None
        if rank == 1:
            p1 += 1
        if rank is not None and rank <= 5:
            p5 += 1
        if rank is not None and rank <= 10:
            r10 += 1
        if rank:
            mrr += 1.0 / rank
        if rank != 1:
            misses.append({"type": g["type"], "rank": rank,
                           "top_type": (results[0]["metadata"].get("type") if results else None)})
    return {
        "n": n,
        "p_at_1": round(p1 / n, 4),
        "p_at_5": round(p5 / n, 4),
        "recall_at_10": round(r10 / n, 4),
        "mrr": round(mrr / n, 4),
        "misses": misses,
    }


# ---------------------------------------------------------------------------
# latency + freshness
# ---------------------------------------------------------------------------
_LATENCY_QUERIES = [
    "retrieval evaluation gold set precision recall",
    "brain memory type knowledge grounding hint",
    "session end hook transcript summary",
    "rust vector index cosine similarity search",
    "QAOA weighted max cut quantum optimization",
    "prompt engineering techniques for LLMs",
    "how to win friends and influence people",
    "next.js production architecture server components",
    "dental tourism costa rica market",
    "why language models hallucinate calibration",
    "entity linking durable memory types",
    "salience recency weighting scoring",
    "HL7 FHIR blockchain healthcare interoperability",
    "GSAP animation timeline scroll trigger",
    "cybersecurity threat modeling defense",
    "stoic philosophy meditations marcus aurelius",
]


def latency(base: str, key: str, warmup: int, reps: int) -> dict:
    for q in _LATENCY_QUERIES[:warmup]:
        search(base, key, q, n=10)
    samples = []
    for _ in range(reps):
        for q in _LATENCY_QUERIES:
            _, dt = search(base, key, q, n=10)
            samples.append(dt)
    samples.sort()
    return {
        "n_samples": len(samples),
        "p50_ms": round(_pct(samples, 50), 2),
        "p95_ms": round(_pct(samples, 95), 2),
        "p99_ms": round(_pct(samples, 99), 2),
        "mean_ms": round(statistics.mean(samples), 2),
    }


def _pct(sorted_samples: list[float], p: float) -> float:
    if not sorted_samples:
        return 0.0
    k = (len(sorted_samples) - 1) * (p / 100.0)
    lo = int(k)
    hi = min(lo + 1, len(sorted_samples) - 1)
    return sorted_samples[lo] + (sorted_samples[hi] - sorted_samples[lo]) * (k - lo)


def freshness(base: str, key: str, trials: int, poll_timeout: float = 10.0) -> dict:
    # Each sentinel must be far (> dedup 0.03 distance) from the others, or the
    # store's near-duplicate guard skips saves 2..N and freshness under-counts.
    _vocab = ["falcon", "meadow", "quartz", "lantern", "cobalt", "thicket",
              "voyage", " member", "granite", "willow", "cascade", "ember",
              "harbor", "nimbus", "orchard", "pewter", "ripple", "sierra",
              "tundra", "velvet", "walnut", "zephyr", "cinder", "dapple"]
    rng = random.Random(0xF00D)
    lat = []
    for i in range(trials):
        token = f"benchfresh-{int(time.time()*1000)}-{i}-zzq"
        # A few distinct words keep each trial > dedup 0.03 distance apart; the
        # sentence itself is the query, so once embedded it self-retrieves at #1.
        body = " ".join(rng.sample(_vocab, 6))
        content = f"Benchmark freshness sentinel {token} about {body} trial {i}."
        t0 = time.perf_counter()
        resp = api_post(base, key, "/save", {
            "content": content, "memory_type": "conversation",
            "tags": ["bench_freshness"], "project": "bench",
            "source": "obsidian", "auto_entities": False,
        })
        saved_id = resp.get("id")
        found = None
        while (time.perf_counter() - t0) < poll_timeout:
            results, _ = search(base, key, content, n=5)
            if any(r.get("id") == saved_id for r in results):
                found = (time.perf_counter() - t0) * 1000.0
                break
            time.sleep(0.05)
        if found is not None:
            lat.append(found)
    lat.sort()
    return {
        "trials": trials, "found": len(lat),
        "p50_ms": round(_pct(lat, 50), 2) if lat else None,
        "p95_ms": round(_pct(lat, 95), 2) if lat else None,
        "max_ms": round(max(lat), 2) if lat else None,
    }


# ---------------------------------------------------------------------------
# distance distribution + grounding bands
# ---------------------------------------------------------------------------
def _load_queries(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


def distances(base: str, key: str, hits: Path, miss: Path,
              project: str = "vault") -> dict:
    tau_close, tau_far = resolved_tau()
    hit_q = _load_queries(hits) if hits and hits.exists() else []
    miss_q = _load_queries(miss) if miss and miss.exists() else []

    def collect(qs: list[dict]) -> list[dict]:
        out = []
        for g in qs:
            # unfiltered search: knowledge competes with the real corpus
            results, _ = search(base, key, g["query"], n=10)
            know = [r for r in results
                    if (r.get("metadata") or {}).get("type") == "knowledge"]
            d_star = min((float(r["distance"]) for r in know), default=None)
            hint = grounding_hint(results, g.get("project", project), tau_close, tau_far)
            out.append({
                "query": g["query"][:60],
                "top_knowledge_distance": round(d_star, 4) if d_star is not None else None,
                "n_knowledge_in_top10": len(know),
                "grounding_hint": hint,
                "top_type": results[0]["metadata"].get("type") if results else None,
            })
        return out

    hit_rows = collect(hit_q)
    miss_rows = collect(miss_q)
    hit_d = sorted(r["top_knowledge_distance"] for r in hit_rows
                   if r["top_knowledge_distance"] is not None)
    miss_d = sorted(r["top_knowledge_distance"] for r in miss_rows
                    if r["top_knowledge_distance"] is not None)

    def summ(ds: list[float]) -> dict:
        if not ds:
            return {"n": 0}
        return {
            "n": len(ds), "min": round(min(ds), 4),
            "p10": round(_pct(ds, 10), 4), "p25": round(_pct(ds, 25), 4),
            "median": round(_pct(ds, 50), 4), "p75": round(_pct(ds, 75), 4),
            "p90": round(_pct(ds, 90), 4), "max": round(max(ds), 4),
        }

    bands = {"hard": 0, "soft": 0, "off": 0}
    for r in hit_rows + miss_rows:
        bands[r["grounding_hint"]] = bands.get(r["grounding_hint"], 0) + 1
    return {
        "tau_close": tau_close, "tau_far": tau_far,
        "relevant_hits": summ(hit_d),
        "irrelevant_hits": summ(miss_d),
        "band_counts": bands,
        "hit_rows": hit_rows,
        "miss_rows": miss_rows,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _write(out: Path | None, report: dict) -> None:
    print(json.dumps(report, indent=2))
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2))
        print(f"\n[wrote {out}]")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("cmd", choices=["quality", "latency", "freshness",
                                    "distances", "gold", "all"])
    ap.add_argument("--api", default="http://127.0.0.1:8790")
    ap.add_argument("--key", default="local-dev-key")
    ap.add_argument("--db", type=Path, default=Path("/tmp/calib/brain.db"))
    ap.add_argument("--gold", type=Path,
                    default=_REPO_ROOT / "brain" / "eval" / "gold_bench_nonknowledge.jsonl")
    ap.add_argument("--gold-n", type=int, default=42)
    ap.add_argument("--seed", type=int, default=1337)
    ap.add_argument("--warmup", type=int, default=8)
    ap.add_argument("--reps", type=int, default=5)
    ap.add_argument("--fresh-trials", type=int, default=8)
    ap.add_argument("--hits", type=Path,
                    default=_REPO_ROOT / "brain" / "eval" / "knowledge_hit_queries.jsonl")
    ap.add_argument("--miss", type=Path,
                    default=_REPO_ROOT / "brain" / "eval" / "knowledge_miss_queries.jsonl")
    ap.add_argument("--label", default="run")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args(argv)

    if args.cmd == "gold":
        rows = build_gold(args.db, args.gold, args.gold_n, args.seed)
        print(f"gold set: {len(rows)} queries -> {args.gold}")
        return 0

    report: dict[str, Any] = {"label": args.label, "api": args.api,
                              "ts": time.strftime("%Y-%m-%dT%H:%M:%S")}
    if args.cmd in ("quality", "all"):
        gold = build_gold(args.db, args.gold, args.gold_n, args.seed)
        report["quality"] = quality(args.api, args.key, gold)
    if args.cmd in ("latency", "all"):
        report["latency"] = latency(args.api, args.key, args.warmup, args.reps)
    if args.cmd in ("freshness", "all"):
        report["freshness"] = freshness(args.api, args.key, args.fresh_trials)
    if args.cmd in ("distances", "all"):
        report["distances"] = distances(args.api, args.key, args.hits, args.miss)

    _write(args.out, report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
