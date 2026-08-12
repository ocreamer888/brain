#!/usr/bin/env python3
"""Paired A/B of `graph_expand` off vs on, with a hard statistical gate (A1).

This is the tool whose PASS verdict is the *only* thing that flips
`graph_expand` to default `true`.

Design notes that must not be "fixed" later by mistake:

  * `eval_suite.py:185` calls `api_search(query=q, n=n)` with no `graph_expand`
    argument and is deliberately left that way — it measures *default
    production behaviour*, and the default is `false`. Plumbing the flag
    through it would either move the baseline the dashboard trends or add a
    second orchestration path for one experiment. This tool calls `api_client`
    directly with both arms instead and needs nothing from `eval_suite`.
  * `retrieval_eval_kfold.py` scores offline in numpy and never calls the API,
    so it structurally *cannot* exercise `graph_expand` (which lives in Rust).
    It is not a candidate harness and needs no change.
  * If this gate ever returns PASS and the default flips, `eval_suite` must
    then gain an explicit `graph_expand=False` on its `api_search` call to keep
    measuring the same thing. That is a follow-up ON THE FLIP, not now.

The database is live and grows during a session (`decision` moved 22 -> 31
during the audit). Both arms are therefore interleaved per query inside one
process — off then on, back to back — never two sequential passes.

Exit codes: 0 PASS, 1 FAIL, 2 UNDERPOWERED / INVALID_SET / API unreachable.

Usage:
    python3 brain/tools/graph_expand_ab.py \
        --gold brain/eval/gold_graph_expand.jsonl --ks 1,3,5,10 \
        --surface template --report brain/eval/runs/graph_expand_ab_$(date +%F).json
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sqlite3
import statistics
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_REPO_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = _REPO_ROOT / "brain" / "rust" / "brain.db"
DEFAULT_GOLD = _REPO_ROOT / "brain" / "eval" / "gold_graph_expand.jsonl"

EXCLUDED_TYPE = "episode"
PRIMARY_K = 10

# Criterion 8's CI floor on the MRR delta. Not a GateConfig field because the
# A1 interface fixes GateConfig's members; kept explicit here rather than
# reusing max_delta_mrr_loss, which is a different quantity (point vs CI).
CI_DELTA_MRR_FLOOR = -0.02

SearchFn = Callable[[str, int, bool], list[dict[str, Any]]]


@dataclass
class GateConfig:
    min_n: int = 150
    max_baseline_hit10: float = 0.90
    min_reachable: int = 12
    min_discordant: int = 12
    alpha: float = 0.05
    min_delta_hit10: float = 0.03
    max_delta_mrr_loss: float = 0.01
    max_delta_hit3_loss: float = 0.02
    max_p95_latency_ratio: float = 1.25


# ---------------------------------------------------------------------------
# Gold I/O and validation
# ---------------------------------------------------------------------------

def load_gold(path: Path | str) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            entries.append(json.loads(line))
    return entries


def _ro_connect(db_path: Path | str) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def _norm_type(value: Any) -> str:
    """`memories.type` is JSON-quoted in SQLite but bare in API responses."""
    text = str(value or "").strip()
    if len(text) >= 2 and text.startswith('"') and text.endswith('"'):
        text = text[1:-1]
    return text.lower()


def inspect_gold_targets(db_path: Path | str, gold: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Resolve every gold target against the DB.

    Returns the three facts criterion 1 gates on: dangling ids, targets with no
    outgoing edges (expansion can never reach them), and `episode` targets.
    """
    dangling: list[str] = []
    unlinked = 0
    episodes = 0
    conn = _ro_connect(db_path)
    try:
        for row in gold:
            mid = str(row.get("gold_memory_id", ""))
            found = conn.execute(
                "SELECT m.type AS type, "
                "EXISTS (SELECT 1 FROM edges WHERE src_memory_id = m.id) AS linked "
                "FROM memories m WHERE m.id = ?",
                (mid,),
            ).fetchone()
            if found is None:
                dangling.append(mid)
                continue
            if not int(found["linked"]):
                unlinked += 1
            if _norm_type(found["type"]) == EXCLUDED_TYPE:
                episodes += 1
    finally:
        conn.close()
    return {
        "dangling_gold_ids": dangling,
        "n_unlinked_targets": unlinked,
        "n_episode_targets": episodes,
    }


def validate_gold(
    gold: Sequence[dict[str, Any]],
    db_path: Path | str,
    strict: bool = True,
) -> list[str]:
    """Return dangling gold ids. Raises ValueError on any when `strict`.

    A dangling id silently deflates every hit rate, so the default is a hard
    error; `strict=False` exists only so the report can record the ids.
    """
    dangling = inspect_gold_targets(db_path, gold)["dangling_gold_ids"]
    if dangling and strict:
        raise ValueError(
            f"gold set has {len(dangling)} dangling memory id(s): {dangling[:5]}"
        )
    return dangling


# ---------------------------------------------------------------------------
# Paired run
# ---------------------------------------------------------------------------

def _result_meta(result: dict[str, Any]) -> dict[str, Any]:
    meta = result.get("metadata") or {}
    return {
        "id": str(result.get("id", "")),
        "type": _norm_type(meta.get("type", result.get("type"))),
        "project": str(meta.get("project", result.get("project", "")) or ""),
    }


def _rank_of(ids: Sequence[str], target: str) -> int | None:
    for i, mid in enumerate(ids, start=1):
        if mid == target:
            return i
    return None


def run_paired(
    gold: Sequence[dict[str, Any]],
    search_fn: SearchFn,
    n: int = 10,
) -> list[dict[str, Any]]:
    """Run both arms INTERLEAVED per query: off, then on, back to back.

    Two sequential passes would confound the comparison with corpus growth —
    the DB is written to by live sessions while the A/B runs.
    """
    rows: list[dict[str, Any]] = []
    for entry in gold:
        query = str(entry["query"])
        target = str(entry["gold_memory_id"])

        t0 = time.perf_counter()
        off_raw = search_fn(query, n, False)
        off_ms = (time.perf_counter() - t0) * 1000.0

        t1 = time.perf_counter()
        on_raw = search_fn(query, n, True)
        on_ms = (time.perf_counter() - t1) * 1000.0

        off_results = [_result_meta(r) for r in off_raw]
        on_results = [_result_meta(r) for r in on_raw]
        off_ids = [r["id"] for r in off_results]
        on_ids = [r["id"] for r in on_results]

        rows.append(
            {
                "query": query,
                "gold_memory_id": target,
                "memory_type": entry.get("memory_type"),
                "project": entry.get("project"),
                "neighbor_degree": entry.get("neighbor_degree"),
                "off_ids": off_ids,
                "on_ids": on_ids,
                "off_results": off_results,
                "on_results": on_results,
                "off_rank": _rank_of(off_ids, target),
                "on_rank": _rank_of(on_ids, target),
                "off_ms": off_ms,
                "on_ms": on_ms,
                "injected_neighbors": len(set(on_ids) - set(off_ids)),
            }
        )
    return rows


# ---------------------------------------------------------------------------
# Statistics (stdlib only — scipy is not guaranteed to be importable under the
# interpreter this runs on, so the exact test is built from math.comb)
# ---------------------------------------------------------------------------

def mcnemar_exact(b: int, c: int) -> float:
    """Two-sided exact McNemar (binomial sign test, p=0.5) on discordant pairs.

    b = gains (off miss -> on hit), c = losses (off hit -> on miss).
    """
    b = int(b)
    c = int(c)
    if b < 0 or c < 0:
        raise ValueError("b and c must be non-negative")
    n = b + c
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, i) for i in range(min(b, c) + 1))
    return min(1.0, 2.0 * tail / (2.0**n))


def bootstrap_delta_ci(
    off: Sequence[float],
    on: Sequence[float],
    iters: int = 10_000,
    seed: int = 42,
) -> tuple[float, float]:
    """Percentile bootstrap 95% CI for mean(on) - mean(off) over PAIRED scores."""
    if len(off) != len(on):
        raise ValueError("off and on must be the same length (paired)")
    size = len(off)
    if size == 0 or iters <= 0:
        return (0.0, 0.0)
    diffs = [on[i] - off[i] for i in range(size)]
    rng = random.Random(seed)
    deltas: list[float] = []
    for _ in range(iters):
        total = 0.0
        for _ in range(size):
            total += diffs[rng.randrange(size)]
        deltas.append(total / size)
    deltas.sort()
    lo = deltas[max(0, int(0.025 * iters))]
    hi = deltas[min(iters - 1, int(0.975 * iters))]
    return (round(lo, 4), round(hi, 4))


def _percentile(values: Sequence[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = max(0, min(len(ordered) - 1, math.ceil(pct * len(ordered)) - 1))
    return ordered[idx]


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------

def reachable_targets(
    db_path: Path | str,
    rows: Sequence[dict[str, Any]],
    top_k: int = 5,
) -> int:
    """Queries whose gold target is in the 1-hop neighbourhood of the off-arm seeds.

    This is the a-priori ceiling on gains and is computable from the off arm
    alone: if it is below the gate's threshold the experiment is dead before
    the on arm is scored. The target is removed from its own seed list so a
    trivial self-join match cannot inflate the count.
    """
    count = 0
    conn = _ro_connect(db_path)
    try:
        for row in rows:
            target = str(row.get("gold_memory_id", ""))
            seeds = [i for i in list(row.get("off_ids") or [])[:top_k] if i != target]
            if not seeds:
                continue
            placeholders = ",".join("?" * len(seeds))
            hit = conn.execute(
                "SELECT 1 FROM edges e1 JOIN edges e2 ON e1.dst_entity_id = e2.dst_entity_id "
                f"WHERE e1.src_memory_id IN ({placeholders}) AND e2.src_memory_id = ? LIMIT 1",
                (*seeds, target),
            ).fetchone()
            if hit is not None:
                count += 1
    finally:
        conn.close()
    return count


def filter_violations(
    rows: Sequence[dict[str, Any]],
    memory_type: str | None,
    project: str | None,
) -> int:
    """Results in the EXPANDED arm that breach the requested filter (A2.1).

    Injected 1-hop neighbours are pushed into the scored list after the
    memory_type/project filter loop, so before A2.1's fix they are returned
    regardless of the filter. Counted on the on arm because the off arm cannot
    exhibit the bug.
    """
    if not memory_type and not project:
        return 0
    want_type = _norm_type(memory_type) if memory_type else None
    violations = 0
    for row in rows:
        for result in row.get("on_results") or []:
            bad_type = want_type is not None and result.get("type") != want_type
            bad_project = project is not None and result.get("project") != project
            if bad_type or bad_project:
                violations += 1
    return violations


# ---------------------------------------------------------------------------
# Scoring and report
# ---------------------------------------------------------------------------

def _score_arm(rows: Sequence[dict[str, Any]], ks: Sequence[int], arm: str) -> dict[str, Any]:
    rank_key = f"{arm}_rank"
    ms_key = f"{arm}_ms"
    total = len(rows) or 1
    out: dict[str, Any] = {}
    for k in ks:
        hits = sum(1 for r in rows if r[rank_key] is not None and r[rank_key] <= k)
        out[f"hit@{k}"] = round(hits / total, 4)
    rr = [1.0 / r[rank_key] if r[rank_key] is not None and r[rank_key] <= PRIMARY_K else 0.0 for r in rows]
    out[f"mrr@{PRIMARY_K}"] = round(sum(rr) / total, 4)
    latencies = [float(r[ms_key]) for r in rows]
    out["latency_ms_median"] = round(statistics.median(latencies), 2) if latencies else 0.0
    out["latency_ms_p95"] = round(_percentile(latencies, 0.95), 2)
    return out


def _hit_vector(rows: Sequence[dict[str, Any]], arm: str, k: int) -> list[float]:
    return [1.0 if r[f"{arm}_rank"] is not None and r[f"{arm}_rank"] <= k else 0.0 for r in rows]


def _rr_vector(rows: Sequence[dict[str, Any]], arm: str) -> list[float]:
    return [
        1.0 / r[f"{arm}_rank"] if r[f"{arm}_rank"] is not None and r[f"{arm}_rank"] <= PRIMARY_K else 0.0
        for r in rows
    ]


def _mcnemar_table(rows: Sequence[dict[str, Any]], k: int) -> dict[str, Any]:
    off = _hit_vector(rows, "off", k)
    on = _hit_vector(rows, "on", k)
    both_hit = sum(1 for i in range(len(rows)) if off[i] and on[i])
    b_gain = sum(1 for i in range(len(rows)) if not off[i] and on[i])
    c_loss = sum(1 for i in range(len(rows)) if off[i] and not on[i])
    both_miss = len(rows) - both_hit - b_gain - c_loss
    return {
        "both_hit": both_hit,
        "b_gain": b_gain,
        "c_loss": c_loss,
        "both_miss": both_miss,
        "n_discordant": b_gain + c_loss,
        "p_two_sided": round(mcnemar_exact(b_gain, c_loss), 6),
    }


def build_report(
    rows: Sequence[dict[str, Any]],
    gold: Sequence[dict[str, Any]],
    db_path: Path | str,
    ks: Sequence[int],
    surface: str,
    gold_file: str,
    memory_type: str | None = None,
    project: str | None = None,
    bootstrap_iters: int = 10_000,
    seed: int = 42,
) -> dict[str, Any]:
    baseline = _score_arm(rows, ks, "off")
    expanded = _score_arm(rows, ks, "on")

    delta = {f"hit@{k}": round(expanded[f"hit@{k}"] - baseline[f"hit@{k}"], 4) for k in ks}
    delta["mrr"] = round(expanded[f"mrr@{PRIMARY_K}"] - baseline[f"mrr@{PRIMARY_K}"], 4)
    base_p95 = baseline["latency_ms_p95"]
    delta["latency_ratio_p95"] = round(expanded["latency_ms_p95"] / base_p95, 4) if base_p95 else 0.0

    n_by_type: dict[str, int] = {}
    for entry in gold:
        key = str(entry.get("memory_type") or "unknown")
        n_by_type[key] = n_by_type.get(key, 0) + 1

    targets = inspect_gold_targets(db_path, gold)
    degrees = [float(e["neighbor_degree"]) for e in gold if e.get("neighbor_degree") is not None]
    injected = [int(r["injected_neighbors"]) for r in rows]

    conn = _ro_connect(db_path)
    try:
        corpus_size = int(conn.execute("SELECT COUNT(*) AS c FROM memories").fetchone()["c"])
    finally:
        conn.close()

    return {
        "run_id": f"graph_expand_ab_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
        "gold_file": gold_file,
        "db_path": str(db_path),
        "corpus_size": corpus_size,
        "surface": surface,
        "memory_type_filter": memory_type,
        "project_filter": project,
        "n_queries": len(rows),
        "n_by_type": n_by_type,
        "baseline": baseline,
        "expanded": expanded,
        "delta": delta,
        "mcnemar": {str(k): _mcnemar_table(rows, k) for k in ks},
        "ci": {
            f"delta_hit@{PRIMARY_K}": list(
                bootstrap_delta_ci(
                    _hit_vector(rows, "off", PRIMARY_K),
                    _hit_vector(rows, "on", PRIMARY_K),
                    iters=bootstrap_iters,
                    seed=seed,
                )
            ),
            "delta_mrr": list(
                bootstrap_delta_ci(
                    _rr_vector(rows, "off"),
                    _rr_vector(rows, "on"),
                    iters=bootstrap_iters,
                    seed=seed,
                )
            ),
        },
        "diagnostics": {
            "n_reachable": reachable_targets(db_path, rows),
            "mean_neighbor_degree": round(statistics.mean(degrees), 2) if degrees else None,
            "injected_neighbors_median": statistics.median(injected) if injected else 0,
            "filter_violations": filter_violations(rows, memory_type, project),
            "dangling_gold_ids": targets["dangling_gold_ids"],
            "n_unlinked_targets": targets["n_unlinked_targets"],
            "n_episode_targets": targets["n_episode_targets"],
        },
        "power_note": (
            "At a discordant rate of 0.12-0.15, n=150 yields 18-22 pairs: this design "
            "detects a 4:1 gain:loss ratio and will NOT detect a true lift below ~3 pp."
        ),
    }


def write_report(report: dict[str, Any], path: Path | str) -> Path:
    """Write the report as JSON, creating the parent directory if needed.

    `brain/eval/runs/` does not exist in this checkout and nothing on this code
    path creates it (only `eval_suite.py`, which this tool deliberately does not
    use). Without this mkdir the first real run would crash *after* paying for
    ~300 live searches.
    """
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return out


# ---------------------------------------------------------------------------
# Gate
# ---------------------------------------------------------------------------

def _mcnemar_at(report: dict[str, Any], k: int) -> dict[str, Any]:
    table = report.get("mcnemar") or {}
    return table.get(str(k)) or table.get(k) or {}


def gate(report: dict[str, Any], cfg: GateConfig = GateConfig()) -> tuple[str, list[str]]:
    """Apply A1's ten pass/fail criteria on the k=10 primary endpoint.

    Verdict precedence: INVALID_SET > UNDERPOWERED > FAIL > PASS. UNDERPOWERED
    is an explicit third verdict — it is never silently reported as a pass.
    """
    invalid: list[str] = []
    underpowered: list[str] = []
    failed: list[str] = []

    diag = report.get("diagnostics") or {}
    baseline = report.get("baseline") or {}
    delta = report.get("delta") or {}
    ci = report.get("ci") or {}
    mc = _mcnemar_at(report, PRIMARY_K)

    # 1 — set integrity
    n_queries = int(report.get("n_queries") or 0)
    if n_queries < cfg.min_n:
        invalid.append(f"1: n_queries {n_queries} < {cfg.min_n}")
    dangling = diag.get("dangling_gold_ids") or []
    if dangling:
        invalid.append(f"1: {len(dangling)} dangling gold id(s)")
    if int(diag.get("n_unlinked_targets") or 0) > 0:
        invalid.append(f"1: {diag['n_unlinked_targets']} target(s) have no edges")
    if int(diag.get("n_episode_targets") or 0) > 0:
        invalid.append(f"1: {diag['n_episode_targets']} episode target(s) present")

    # 2 — unsaturated baseline
    base_hit10 = float(baseline.get(f"hit@{PRIMARY_K}", 0.0))
    if base_hit10 > cfg.max_baseline_hit10:
        invalid.append(
            f"2: baseline hit@10 {base_hit10} > {cfg.max_baseline_hit10} "
            "(saturated set — regenerate harder queries)"
        )

    # 3 — a-priori reachability ceiling
    n_reachable = int(diag.get("n_reachable") or 0)
    if n_reachable < cfg.min_reachable:
        underpowered.append(f"3: n_reachable {n_reachable} < {cfg.min_reachable}")

    # 4 — discordant pairs and direction
    n_discordant = int(mc.get("n_discordant") or 0)
    b_gain = int(mc.get("b_gain") or 0)
    c_loss = int(mc.get("c_loss") or 0)
    if n_discordant < cfg.min_discordant:
        underpowered.append(f"4: n_discordant {n_discordant} < {cfg.min_discordant}")
    if b_gain <= c_loss:
        underpowered.append(f"4: b_gain {b_gain} <= c_loss {c_loss}")

    # 5 — significance
    p_value = float(mc.get("p_two_sided", 1.0))
    if p_value >= cfg.alpha:
        failed.append(f"5: mcnemar p {p_value} >= {cfg.alpha}")

    # A criterion whose input is MISSING must never be treated as satisfied.
    # Previously every read below used a passing default, so `--ks 10` produced a
    # report with no hit@1 / hit@3 keys and the gate returned PASS — silently
    # skipping the P@1 invariant (7) and the no-harm gate (8). Absent evidence is
    # INVALID_SET, not PASS.
    for _key, _crit in (
        (f"hit@{PRIMARY_K}", "6"), ("hit@1", "7"), ("hit@3", "8"), ("mrr", "8"),
        ("latency_ratio_p95", "10"),
    ):
        if _key not in delta:
            invalid.append(f"{_crit}: delta['{_key}'] missing — cannot evaluate criterion {_crit}")
    if "filter_violations" not in diag:
        invalid.append("9: diagnostics['filter_violations'] missing — cannot evaluate criterion 9")
    if "p_two_sided" not in mc:
        invalid.append("5: mcnemar['p_two_sided'] missing — cannot evaluate criterion 5")

    # 6 — effect size and its CI
    delta_hit10 = float(delta.get(f"hit@{PRIMARY_K}", 0.0))
    if delta_hit10 < cfg.min_delta_hit10:
        failed.append(f"6: delta hit@10 {delta_hit10} < {cfg.min_delta_hit10}")
    ci_hit10 = ci.get(f"delta_hit@{PRIMARY_K}") or [0.0, 0.0]
    if float(ci_hit10[0]) <= 0:
        failed.append(f"6: ci delta_hit@10 lower bound {ci_hit10[0]} <= 0")

    # 7 — invariant: k=1 is structurally frozen (neighbour score = seed * 0.85
    # and the diversity rerank admits the top item unconditionally). Nonzero
    # here means a Rust ranking bug, not a win.
    delta_hit1 = float(delta.get("hit@1", 0.0))
    if delta_hit1 != 0.0:
        failed.append(f"7: INVARIANT delta hit@1 {delta_hit1} != 0.0 — Rust ranking bug, stop and fix")

    # 8 — no harm
    delta_hit3 = float(delta.get("hit@3", 0.0))
    if delta_hit3 < -cfg.max_delta_hit3_loss:
        failed.append(f"8: delta hit@3 {delta_hit3} < {-cfg.max_delta_hit3_loss}")
    delta_mrr = float(delta.get("mrr", 0.0))
    if delta_mrr < -cfg.max_delta_mrr_loss:
        failed.append(f"8: delta mrr {delta_mrr} < {-cfg.max_delta_mrr_loss}")
    ci_mrr = ci.get("delta_mrr") or [0.0, 0.0]
    if float(ci_mrr[0]) <= CI_DELTA_MRR_FLOOR:
        failed.append(f"8: ci delta_mrr lower bound {ci_mrr[0]} <= {CI_DELTA_MRR_FLOOR}")

    # 9 — filter integrity (A2.1)
    violations = int(diag.get("filter_violations") or 0)
    if violations != 0:
        failed.append(f"9: filter_violations {violations} != 0")

    # 10 — latency
    ratio = float(delta.get("latency_ratio_p95", 0.0))
    if ratio > cfg.max_p95_latency_ratio:
        failed.append(f"10: latency_ratio_p95 {ratio} > {cfg.max_p95_latency_ratio}")

    if invalid:
        return "INVALID_SET", invalid + underpowered + failed
    if underpowered:
        return "UNDERPOWERED", underpowered + failed
    if failed:
        return "FAIL", failed
    return "PASS", []


# ---------------------------------------------------------------------------
# Surfaces and CLI
# ---------------------------------------------------------------------------

def make_search_fn(
    surface: str,
    memory_type: str | None = None,
    project: str | None = None,
) -> SearchFn:
    """Both arms use the identical surface; only `graph_expand` differs.

    `template` matches production MCP `search_brain` (which issues type-filtered
    sub-searches — the path where A2.1's filter bypass surfaces in the product).
    """
    import api_client  # local import: keeps the module importable without env

    if surface == "template":
        if memory_type:
            raise ValueError(
                "template_search has no memory_type parameter — "
                "run the type-filtered sub-run with --surface plain"
            )

        def template_fn(query: str, n: int, graph_expand: bool) -> list[dict[str, Any]]:
            return api_client.template_search(
                query=query, n=n, project=project, graph_expand=graph_expand
            )

        return template_fn

    if surface == "plain":

        def plain_fn(query: str, n: int, graph_expand: bool) -> list[dict[str, Any]]:
            return api_client.search(
                query=query,
                n=n,
                memory_type=memory_type,
                project=project,
                graph_expand=graph_expand,
            )

        return plain_fn

    raise ValueError(f"unknown surface {surface!r} (expected 'template' or 'plain')")


#: k values the gate MUST have data for. 10 is the primary endpoint; 1 is the
#: P@1 invariant (criterion 7); 3 is the no-harm gate (criterion 8). Omitting any
#: of these used to make gate() substitute a passing default and return PASS.
REQUIRED_KS = (1, 3, PRIMARY_K)


def _parse_ks(raw: str) -> list[int]:
    ks = sorted({int(part) for part in raw.split(",") if part.strip()})
    missing = [k for k in REQUIRED_KS if k not in ks]
    if missing:
        raise ValueError(
            f"--ks must include {sorted(REQUIRED_KS)} (missing {missing}). "
            "k=1 gates the P@1 invariant and k=3 the no-harm criterion; without "
            "them the gate cannot evaluate criteria 7 and 8."
        )
    return ks


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Paired, interleaved A/B of graph_expand off vs on, with the A1 gate. "
        "Exit 0 PASS, 1 FAIL, 2 UNDERPOWERED/INVALID_SET/unreachable."
    )
    parser.add_argument("--gold", default=str(DEFAULT_GOLD), help="gold JSONL path")
    parser.add_argument("--db", default=str(DB_PATH), help="SQLite path (read-only)")
    parser.add_argument("--report", required=True, help="output JSON report path")
    parser.add_argument("--ks", default="1,3,5,10", help="cut-offs to score (must include 10)")
    parser.add_argument("--n", type=int, default=10, help="results requested per search")
    parser.add_argument("--surface", default="template", choices=("template", "plain"))
    parser.add_argument("--memory-type", default=None, help="type-filtered sub-run (criterion 9)")
    parser.add_argument("--project", default=None, help="project-filtered sub-run (criterion 9)")
    parser.add_argument("--bootstrap-iters", type=int, default=10_000)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args(list(argv) if argv is not None else None)

    try:
        ks = _parse_ks(args.ks)
        gold = load_gold(args.gold)
        if not gold:
            print(f"[graph_expand_ab] empty gold set: {args.gold}", file=sys.stderr)
            return 2
        validate_gold(gold, args.db)
        search_fn = make_search_fn(args.surface, args.memory_type, args.project)
        rows = run_paired(gold, search_fn, n=args.n)
    except Exception as e:  # API down, bad gold, bad args — all verdict-less
        print(f"[graph_expand_ab] run aborted: {type(e).__name__}: {e}", file=sys.stderr)
        return 2

    report = build_report(
        rows,
        gold,
        args.db,
        ks,
        args.surface,
        gold_file=args.gold,
        memory_type=args.memory_type,
        project=args.project,
        bootstrap_iters=args.bootstrap_iters,
        seed=args.seed,
    )
    cfg = GateConfig()
    verdict, failed_criteria = gate(report, cfg)
    report["gate"] = {
        "verdict": verdict,
        "failed_criteria": failed_criteria,
        "config": asdict(cfg),
    }

    path = write_report(report, args.report)
    print(json.dumps({"verdict": verdict, "failed_criteria": failed_criteria, "report": str(path)}, indent=2))

    if verdict == "PASS":
        return 0
    if verdict == "FAIL":
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
