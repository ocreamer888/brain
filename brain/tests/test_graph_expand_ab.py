"""Tests for brain/tools/graph_expand_ab.py and brain/tools/gen_gold_graph.py (A1).

No live API and no live Ollama: `search_fn` is stubbed and every DB is a
throwaway SQLite file built in `tmp_path`.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from brain.tools import gen_gold_graph, graph_expand_ab  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

_CONTENT = "supabase policy migration notes " * 20  # 640 chars, real tokens


def _make_db(tmp_path: Path, memories: list[tuple[str, str]], edges: list[tuple[str, str]]) -> Path:
    """memories: (id, bare_type). edges: (src_memory_id, dst_entity_id)."""
    db = tmp_path / "test.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE memories (id TEXT PRIMARY KEY, content TEXT NOT NULL, "
        "type TEXT NOT NULL, project TEXT NOT NULL DEFAULT 'general', "
        "timestamp TEXT NOT NULL DEFAULT '', superseded_by TEXT)"
    )
    conn.execute(
        "CREATE TABLE edges (id TEXT PRIMARY KEY, src_memory_id TEXT NOT NULL, "
        "dst_entity_id TEXT NOT NULL)"
    )
    for mid, mtype in memories:
        conn.execute(
            "INSERT INTO memories (id, content, type) VALUES (?, ?, ?)",
            (mid, _CONTENT, json.dumps(mtype)),
        )
    for i, (src, dst) in enumerate(edges):
        conn.execute("INSERT INTO edges (id, src_memory_id, dst_entity_id) VALUES (?, ?, ?)",
                     (f"e{i}", src, dst))
    conn.commit()
    conn.close()
    return db


def _passing_report() -> dict:
    """A report that satisfies all ten criteria; tests perturb one field each."""
    return {
        "n_queries": 150,
        "baseline": {"hit@1": 0.40, "hit@3": 0.60, "hit@5": 0.70, "hit@10": 0.80, "mrr@10": 0.50},
        "expanded": {"hit@1": 0.40, "hit@3": 0.60, "hit@5": 0.72, "hit@10": 0.85, "mrr@10": 0.505},
        "delta": {
            "hit@1": 0.0,
            "hit@3": 0.0,
            "hit@5": 0.02,
            "hit@10": 0.05,
            "mrr": 0.005,
            "latency_ratio_p95": 1.10,
        },
        "mcnemar": {
            "10": {
                "both_hit": 118,
                "b_gain": 12,
                "c_loss": 2,
                "both_miss": 18,
                "n_discordant": 14,
                "p_two_sided": graph_expand_ab.mcnemar_exact(12, 2),
            }
        },
        "ci": {"delta_hit@10": [0.01, 0.09], "delta_mrr": [-0.005, 0.02]},
        "diagnostics": {
            "n_reachable": 24,
            "mean_neighbor_degree": 53.5,
            "injected_neighbors_median": 2,
            "filter_violations": 0,
            "dangling_gold_ids": [],
            "n_unlinked_targets": 0,
            "n_episode_targets": 0,
        },
    }


# ---------------------------------------------------------------------------
# mcnemar_exact — math.comb only, no scipy
# ---------------------------------------------------------------------------

def test_mcnemar_exact_all_gains() -> None:
    assert graph_expand_ab.mcnemar_exact(6, 0) == pytest.approx(0.03125)


def test_mcnemar_exact_perfectly_tied() -> None:
    assert graph_expand_ab.mcnemar_exact(3, 3) == 1.0


def test_mcnemar_exact_no_discordant_pairs() -> None:
    assert graph_expand_ab.mcnemar_exact(0, 0) == 1.0


def test_mcnemar_exact_is_symmetric() -> None:
    assert graph_expand_ab.mcnemar_exact(9, 2) == graph_expand_ab.mcnemar_exact(2, 9)


def test_mcnemar_exact_does_not_need_scipy() -> None:
    """The exact test must be stdlib-only; scipy is absent under some interpreters."""
    import brain.tools.graph_expand_ab as mod

    assert "scipy" not in mod.__dict__
    assert not any(name.startswith("scipy") for name in sys.modules if name in mod.__dict__)


# ---------------------------------------------------------------------------
# run_paired — interleaving is the whole point
# ---------------------------------------------------------------------------

def test_run_paired_interleaves_arms_per_query() -> None:
    calls: list[tuple[str, bool]] = []

    def stub(query: str, n: int, graph_expand: bool) -> list[dict]:
        calls.append((query, graph_expand))
        return []

    gold = [
        {"query": "q1", "gold_memory_id": "m1"},
        {"query": "q2", "gold_memory_id": "m2"},
    ]
    graph_expand_ab.run_paired(gold, stub, n=10)

    assert calls == [("q1", False), ("q1", True), ("q2", False), ("q2", True)]


def test_run_paired_scores_ranks_and_injections() -> None:
    def stub(query: str, n: int, graph_expand: bool) -> list[dict]:
        if graph_expand:
            return [
                {"id": "a", "metadata": {"type": "fact", "project": "p"}},
                {"id": "target", "metadata": {"type": "fact", "project": "p"}},
                {"id": "new", "metadata": {"type": "solution", "project": "q"}},
            ]
        return [
            {"id": "a", "metadata": {"type": "fact", "project": "p"}},
            {"id": "b", "metadata": {"type": "fact", "project": "p"}},
        ]

    rows = graph_expand_ab.run_paired([{"query": "q", "gold_memory_id": "target"}], stub)

    assert len(rows) == 1
    assert rows[0]["off_rank"] is None
    assert rows[0]["on_rank"] == 2
    assert rows[0]["injected_neighbors"] == 2  # "target" and "new"
    assert rows[0]["off_ms"] >= 0.0 and rows[0]["on_ms"] >= 0.0


# ---------------------------------------------------------------------------
# validate_gold
# ---------------------------------------------------------------------------

def test_validate_gold_raises_on_dangling_id(tmp_path: Path) -> None:
    db = _make_db(tmp_path, [("m1", "solution")], [("m1", "e1")])
    gold = [{"query": "q", "gold_memory_id": "m1"}, {"query": "q2", "gold_memory_id": "ghost"}]

    with pytest.raises(ValueError, match="dangling"):
        graph_expand_ab.validate_gold(gold, db)


def test_validate_gold_passes_when_all_resolve(tmp_path: Path) -> None:
    db = _make_db(tmp_path, [("m1", "solution")], [("m1", "e1")])
    assert graph_expand_ab.validate_gold([{"query": "q", "gold_memory_id": "m1"}], db) == []


def test_inspect_gold_targets_flags_unlinked_and_episode(tmp_path: Path) -> None:
    db = _make_db(tmp_path, [("m1", "solution"), ("m2", "episode")], [("m2", "e1")])
    info = graph_expand_ab.inspect_gold_targets(
        db, [{"gold_memory_id": "m1"}, {"gold_memory_id": "m2"}]
    )
    assert info["dangling_gold_ids"] == []
    assert info["n_unlinked_targets"] == 1  # m1 has no edges
    assert info["n_episode_targets"] == 1  # m2 is an episode


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------

def test_reachable_targets_counts_one_hop_only(tmp_path: Path) -> None:
    # seed s1 and target t share entity e1; unrelated u shares nothing.
    db = _make_db(
        tmp_path,
        [("s1", "fact"), ("t", "fact"), ("u", "fact"), ("far", "fact")],
        [("s1", "e1"), ("t", "e1"), ("u", "e2"), ("far", "e3")],
    )
    rows = [
        {"gold_memory_id": "t", "off_ids": ["s1", "u"]},
        {"gold_memory_id": "far", "off_ids": ["s1", "u"]},
    ]
    assert graph_expand_ab.reachable_targets(db, rows) == 1


def test_reachable_targets_ignores_self_seed(tmp_path: Path) -> None:
    """A target already in its own top-5 must not count itself as reachable."""
    db = _make_db(tmp_path, [("t", "fact")], [("t", "e1")])
    rows = [{"gold_memory_id": "t", "off_ids": ["t"]}]
    assert graph_expand_ab.reachable_targets(db, rows) == 0


def test_filter_violations_counts_type_and_project_breaches() -> None:
    rows = [
        {
            "on_results": [
                {"id": "a", "type": "solution", "project": "brain"},
                {"id": "b", "type": "fact", "project": "brain"},  # wrong type
                {"id": "c", "type": "solution", "project": "other"},  # wrong project
            ],
            "off_results": [{"id": "z", "type": "fact", "project": "other"}],
        }
    ]
    assert graph_expand_ab.filter_violations(rows, "solution", None) == 1
    assert graph_expand_ab.filter_violations(rows, None, "brain") == 1
    assert graph_expand_ab.filter_violations(rows, "solution", "brain") == 2
    assert graph_expand_ab.filter_violations(rows, None, None) == 0


def test_bootstrap_delta_ci_brackets_a_real_gain() -> None:
    off = [0.0] * 100
    on = [1.0] * 20 + [0.0] * 80
    lo, hi = graph_expand_ab.bootstrap_delta_ci(off, on, iters=500, seed=42)
    assert lo > 0.0
    assert lo <= 0.20 <= hi


def test_bootstrap_delta_ci_is_deterministic() -> None:
    off = [0.0, 1.0] * 20
    on = [1.0, 1.0] * 20
    first = graph_expand_ab.bootstrap_delta_ci(off, on, iters=200, seed=7)
    second = graph_expand_ab.bootstrap_delta_ci(off, on, iters=200, seed=7)
    assert first == second


# ---------------------------------------------------------------------------
# gate — the ten criteria and the four verdicts
# ---------------------------------------------------------------------------

def test_gate_passes_on_a_clean_report() -> None:
    verdict, failed = graph_expand_ab.gate(_passing_report())
    assert verdict == "PASS"
    assert failed == []


def test_gate_underpowered_at_five_discordant_pairs() -> None:
    report = _passing_report()
    report["mcnemar"]["10"] = {
        "both_hit": 118,
        "b_gain": 4,
        "c_loss": 1,
        "both_miss": 27,
        "n_discordant": 5,
        "p_two_sided": graph_expand_ab.mcnemar_exact(4, 1),
    }
    verdict, failed = graph_expand_ab.gate(report)
    assert verdict == "UNDERPOWERED"
    assert any(c.startswith("4:") for c in failed)


def test_gate_underpowered_when_few_reachable_targets() -> None:
    report = _passing_report()
    report["diagnostics"]["n_reachable"] = 5
    verdict, failed = graph_expand_ab.gate(report)
    assert verdict == "UNDERPOWERED"
    assert any(c.startswith("3:") for c in failed)


def test_gate_invalid_set_on_saturated_baseline() -> None:
    report = _passing_report()
    report["baseline"]["hit@10"] = 0.95
    verdict, failed = graph_expand_ab.gate(report)
    assert verdict == "INVALID_SET"
    assert any(c.startswith("2:") for c in failed)


def test_gate_invalid_set_beats_underpowered() -> None:
    """Precedence: a broken set is reported as INVALID_SET, never UNDERPOWERED."""
    report = _passing_report()
    report["baseline"]["hit@10"] = 0.95
    report["diagnostics"]["n_reachable"] = 1
    verdict, _ = graph_expand_ab.gate(report)
    assert verdict == "INVALID_SET"


@pytest.mark.parametrize(
    "path,value",
    [
        (("n_queries",), 149),
        (("diagnostics", "dangling_gold_ids"), ["ghost"]),
        (("diagnostics", "n_unlinked_targets"), 3),
        (("diagnostics", "n_episode_targets"), 1),
    ],
)
def test_gate_criterion_one_invalidates_the_set(path: tuple, value: object) -> None:
    report = _passing_report()
    target = report
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    verdict, failed = graph_expand_ab.gate(report)
    assert verdict == "INVALID_SET"
    assert any(c.startswith("1:") for c in failed)


def test_gate_fails_on_hit_at_one_invariant_breach() -> None:
    report = _passing_report()
    report["delta"]["hit@1"] = 0.0067
    verdict, failed = graph_expand_ab.gate(report)
    assert verdict == "FAIL"
    assert any("INVARIANT" in c for c in failed)


@pytest.mark.parametrize(
    "mutate,prefix",
    [
        (lambda r: r["delta"].__setitem__("hit@10", 0.01), "6:"),
        (lambda r: r["ci"].__setitem__("delta_hit@10", [-0.01, 0.09]), "6:"),
        (lambda r: r["delta"].__setitem__("hit@3", -0.05), "8:"),
        (lambda r: r["delta"].__setitem__("mrr", -0.02), "8:"),
        (lambda r: r["ci"].__setitem__("delta_mrr", [-0.05, 0.02]), "8:"),
        (lambda r: r["diagnostics"].__setitem__("filter_violations", 7), "9:"),
        (lambda r: r["delta"].__setitem__("latency_ratio_p95", 1.9), "10:"),
    ],
)
def test_gate_fails_each_harm_criterion(mutate, prefix: str) -> None:
    report = _passing_report()
    mutate(report)
    verdict, failed = graph_expand_ab.gate(report)
    assert verdict == "FAIL"
    assert any(c.startswith(prefix) for c in failed)


def test_gate_fails_on_insignificant_p_value() -> None:
    report = _passing_report()
    report["mcnemar"]["10"]["b_gain"] = 9
    report["mcnemar"]["10"]["c_loss"] = 5
    report["mcnemar"]["10"]["p_two_sided"] = graph_expand_ab.mcnemar_exact(9, 5)
    verdict, failed = graph_expand_ab.gate(report)
    assert verdict == "FAIL"
    assert any(c.startswith("5:") for c in failed)


def test_gate_reads_integer_mcnemar_keys() -> None:
    """Pre-serialisation the mcnemar table may be keyed by int; both must work."""
    report = _passing_report()
    report["mcnemar"] = {10: report["mcnemar"]["10"]}
    verdict, _ = graph_expand_ab.gate(report)
    assert verdict == "PASS"


# ---------------------------------------------------------------------------
# Report writing — pins the missing brain/eval/runs/ directory
# ---------------------------------------------------------------------------

def test_report_path_parent_created(tmp_path: Path) -> None:
    """brain/eval/runs/ does not exist; the first real run must not crash."""
    target = tmp_path / "nonexistent" / "r.json"
    assert not target.parent.exists()

    written = graph_expand_ab.write_report({"verdict": "PASS"}, target)

    assert written.exists()
    assert json.loads(written.read_text())["verdict"] == "PASS"


def test_report_path_parent_created_nested(tmp_path: Path) -> None:
    target = tmp_path / "eval" / "runs" / "graph_expand_ab_2026-07-28.json"
    graph_expand_ab.write_report({"ok": True}, target)
    assert target.exists()


# ---------------------------------------------------------------------------
# Surfaces / CLI plumbing
# ---------------------------------------------------------------------------

def test_make_search_fn_rejects_type_filter_on_template_surface() -> None:
    with pytest.raises(ValueError, match="memory_type"):
        graph_expand_ab.make_search_fn("template", memory_type="solution")


def test_make_search_fn_rejects_unknown_surface() -> None:
    with pytest.raises(ValueError, match="unknown surface"):
        graph_expand_ab.make_search_fn("bogus")


def test_parse_ks_requires_all_gated_endpoints() -> None:
    """--ks must carry every k the gate reads, not just the primary.

    Regression: `--ks 10` used to be accepted, producing a report with no hit@1
    or hit@3 keys. gate() then substituted passing defaults and returned PASS,
    silently skipping the P@1 invariant (criterion 7) and the no-harm gate (8).
    """
    assert graph_expand_ab._parse_ks("1,3,5,10") == [1, 3, 5, 10]
    assert graph_expand_ab._parse_ks("1,3,10") == [1, 3, 10]
    for missing in ("10", "3,5,10", "1,5,10", "1,3,5"):
        with pytest.raises(ValueError, match=r"--ks must include"):
            graph_expand_ab._parse_ks(missing)


def test_gate_returns_invalid_set_when_criterion_input_is_missing() -> None:
    """Absent evidence must never read as a satisfied criterion."""
    base = _passing_report()
    assert graph_expand_ab.gate(base)[0] == "PASS"
    for key, crit in (("hit@1", "7"), ("hit@3", "8"), ("mrr", "8"),
                      ("latency_ratio_p95", "10"), ("hit@10", "6")):
        stripped = {**base, "delta": {k: v for k, v in base["delta"].items() if k != key}}
        verdict, failed = graph_expand_ab.gate(stripped)
        assert verdict == "INVALID_SET", f"missing delta[{key}] must invalidate, got {verdict}"
        assert any(key in f for f in failed), f"criterion {crit} must name the missing key"

    for section, key, crit in (("diagnostics", "filter_violations", "9"),):
        stripped = {**base, section: {k: v for k, v in base[section].items() if k != key}}
        assert graph_expand_ab.gate(stripped)[0] == "INVALID_SET", f"criterion {crit}"


def test_build_report_shape_and_gate_roundtrip(tmp_path: Path) -> None:
    db = _make_db(tmp_path, [("t", "solution"), ("s", "solution")], [("t", "e1"), ("s", "e1")])
    gold = [{"query": "q", "gold_memory_id": "t", "memory_type": "solution", "neighbor_degree": 4}]

    def stub(query: str, n: int, graph_expand: bool) -> list[dict]:
        if graph_expand:
            return [{"id": "s", "metadata": {"type": "solution", "project": "general"}},
                    {"id": "t", "metadata": {"type": "solution", "project": "general"}}]
        return [{"id": "s", "metadata": {"type": "solution", "project": "general"}}]

    rows = graph_expand_ab.run_paired(gold, stub)
    report = graph_expand_ab.build_report(
        rows, gold, db, [1, 3, 5, 10], "plain", gold_file="x.jsonl", bootstrap_iters=50
    )

    for key in ("run_id", "gold_file", "db_path", "corpus_size", "surface", "n_queries",
                "n_by_type", "baseline", "expanded", "delta", "mcnemar", "ci", "diagnostics"):
        assert key in report
    assert report["n_queries"] == 1
    assert report["baseline"]["hit@10"] == 0.0
    assert report["expanded"]["hit@10"] == 1.0
    assert report["delta"]["hit@10"] == 1.0
    assert report["diagnostics"]["n_reachable"] == 1
    assert report["diagnostics"]["mean_neighbor_degree"] == 4.0

    # Serialisable, and the gate still reads it after a JSON round-trip.
    verdict, _ = graph_expand_ab.gate(json.loads(json.dumps(report)))
    assert verdict == "INVALID_SET"  # n=1 is far below min_n


# ---------------------------------------------------------------------------
# gen_gold_graph — strata and the calibrated overlap filter
# ---------------------------------------------------------------------------

def test_durable_strata_sums_to_150() -> None:
    assert sum(gen_gold_graph.DURABLE_STRATA.values()) == 150


def test_durable_strata_covers_seven_types_including_conversation() -> None:
    assert gen_gold_graph.DURABLE_STRATA["conversation"] == 15  # locked decision D1
    assert len(gen_gold_graph.DURABLE_STRATA) == 7


def test_episode_never_appears_in_strata() -> None:
    assert "episode" not in gen_gold_graph.DURABLE_STRATA
    with pytest.raises(ValueError, match="episode"):
        gen_gold_graph._validate_strata({"episode": 5})
    with pytest.raises(ValueError, match="episode"):
        gen_gold_graph.select_linked_candidates("unused.db", "episode", 1)


def test_max_vocab_overlap_is_the_calibrated_value() -> None:
    assert gen_gold_graph.MAX_VOCAB_OVERLAP == 0.45
    assert gen_gold_graph.MIN_CONTENT_CHARS == 200


def test_vocab_overlap_bounds() -> None:
    assert gen_gold_graph.vocab_overlap("Supabase policy", "Supabase policy notes") == 1.0
    assert gen_gold_graph.vocab_overlap("kubernetes helm", "totally unrelated prose") == 0.0
    assert gen_gold_graph.vocab_overlap("", "anything") == 1.0


def test_vocab_overlap_ignores_stopwords() -> None:
    """Function words would otherwise inflate every score and break calibration."""
    assert gen_gold_graph.vocab_overlap("why is the widget", "the widget is here") == 1.0


def test_generate_query_defensive_parse(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gen_gold_graph, "_call_llm",
                        lambda *a, **kw: '{"query": "how do I bound the payload?"}')
    assert gen_gold_graph.generate_query("note") == "how do I bound the payload?"

    monkeypatch.setattr(gen_gold_graph, "_call_llm", lambda *a, **kw: "not json at all")
    assert gen_gold_graph.generate_query("note") is None

    monkeypatch.setattr(gen_gold_graph, "_call_llm", lambda *a, **kw: '{"entities": []}')
    assert gen_gold_graph.generate_query("note") is None

    monkeypatch.setattr(gen_gold_graph, "_call_llm",
                        lambda *a, **kw: '```json\n{"query": "fenced"}\n```')
    assert gen_gold_graph.generate_query("note") == "fenced"


def test_generate_query_swallows_llm_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*a, **kw):
        raise OSError("ollama is down")

    monkeypatch.setattr(gen_gold_graph, "_call_llm", boom)
    assert gen_gold_graph.generate_query("note") is None


def test_select_linked_candidates_requires_edges_and_is_reproducible(tmp_path: Path) -> None:
    memories = [(f"m{i}", "solution") for i in range(10)]
    edges = [(f"m{i}", "e1") for i in range(5)]  # only m0..m4 are linked
    db = _make_db(tmp_path, memories, edges)

    first = gen_gold_graph.select_linked_candidates(db, "solution", limit=3, seed=42)
    second = gen_gold_graph.select_linked_candidates(db, "solution", limit=3, seed=42)

    assert [r["id"] for r in first] == [r["id"] for r in second]
    assert len(first) == 3
    assert all(r["id"] in {"m0", "m1", "m2", "m3", "m4"} for r in first)
    assert all(r["n_edges"] == 1 for r in first)
    assert all(r["memory_type"] == "solution" for r in first)


def test_select_linked_candidates_respects_min_chars(tmp_path: Path) -> None:
    db = _make_db(tmp_path, [("m0", "solution")], [("m0", "e1")])
    assert gen_gold_graph.select_linked_candidates(db, "solution", 5, min_chars=100)
    assert gen_gold_graph.select_linked_candidates(db, "solution", 5, min_chars=100_000) == []


def test_neighbor_degree_counts_distinct_other_memories(tmp_path: Path) -> None:
    db = _make_db(
        tmp_path,
        [("m0", "fact"), ("m1", "fact"), ("m2", "fact"), ("m3", "fact")],
        [("m0", "e1"), ("m1", "e1"), ("m2", "e1"), ("m0", "e2"), ("m2", "e2"), ("m3", "e9")],
    )
    assert gen_gold_graph.neighbor_degree(db, "m0") == 2  # m1, m2 (m2 shared twice)
    assert gen_gold_graph.neighbor_degree(db, "m3") == 0


def test_build_gold_writes_expected_row_schema(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = _make_db(tmp_path, [("m0", "solution"), ("m1", "solution")], [("m0", "e1"), ("m1", "e1")])
    monkeypatch.setattr(gen_gold_graph, "generate_query", lambda content, model=None: "a wholly novel probe")

    out = tmp_path / "created" / "gold.jsonl"
    stats = gen_gold_graph.build_gold(db, {"solution": 2}, out, oversample=2.0)

    assert stats["n_rows"] == 2
    rows = [json.loads(line) for line in out.read_text().splitlines()]
    for row in rows:
        assert set(row) >= {
            "query", "gold_memory_id", "k", "description", "memory_type",
            "project", "n_edges", "neighbor_degree", "source", "generated_at",
        }
        assert row["k"] == 10
        assert row["source"] == "llm_paraphrase"
        assert row["memory_type"] == "solution"


def test_build_gold_rejects_high_overlap_queries(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = _make_db(tmp_path, [("m0", "solution")], [("m0", "e1")])
    # Every query token appears verbatim in the note -> containment 1.0 > 0.45.
    monkeypatch.setattr(
        gen_gold_graph, "generate_query", lambda content, model=None: "supabase policy migration"
    )

    stats = gen_gold_graph.build_gold(db, {"solution": 1}, tmp_path / "g.jsonl", dry_run=True)

    assert stats["n_rows"] == 0
    assert stats["rejected_overlap"] == 1
    assert stats["shortfalls"] == {"solution": 1}


def test_build_gold_dry_run_writes_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = _make_db(tmp_path, [("m0", "solution")], [("m0", "e1")])
    monkeypatch.setattr(gen_gold_graph, "generate_query", lambda content, model=None: "novel probe text")
    out = tmp_path / "gold.jsonl"

    stats = gen_gold_graph.build_gold(db, {"solution": 1}, out, dry_run=True)

    assert stats["n_rows"] == 1
    assert not out.exists()
