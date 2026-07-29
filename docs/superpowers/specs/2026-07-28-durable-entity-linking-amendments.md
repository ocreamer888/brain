# Amendments — Durable Entity Linking (Beyond Facts)

**Date:** 2026-07-28
**Status:** Approved for planning
**Amends:** [`2026-07-28-durable-entity-linking-design.md`](./2026-07-28-durable-entity-linking-design.md) (the "base spec")
**Origin:** Code audit of the base spec against the live tree + nine parallel planning passes, each validated against source.

The base spec's architecture is sound and its claims about existing code were verified correct. These amendments fix one strategic gap (no measurable outcome), one unbounded blast radius, three quantified regressions, and **two latent bugs the base spec would have activated**.

Each amendment below is a self-contained work packet: problem, exact anchors, code shape, tests, verification, and dependencies. Do not read the others to implement one, except where `Depends on` says so.

---

## 0. Locked decisions

These override the base spec where they conflict. Do not relitigate.

| # | Decision | Consequence |
|---|---|---|
| D1 | **`conversation` is in the durable set.** Seven types total. | `AGENTS.md:33` ("all memory types except `episode`") stands as written. Base spec's non-goal becomes `episode` only. +1,009 rows ≈ +15 min backfill. |
| D2 | **`episode` stays excluded.** | 0 rows exist in the DB today; it is an audit-body type. |
| D3 | **Dangling gold row 18 is deleted, not repaired.** | `gold_semantic.jsonl` → 17 rows. Do not guess a replacement id. |
| D4 | **Fact path passes `auto_entities=False` explicitly.** | Not an emptiness heuristic. See A7. |
| D5 | **Spool replay disables auto-extraction** rather than forwarding extracted entities through the exception. | One line, not three files. See A3. |
| D6 | **`api_client.py` stays stdlib-only at import time.** | The extractor is lazy-imported. See A3. |
| D7 | **No displacement guard this ship.** | Determinism first; the guard is pre-registered in A2 for the next ship. |

**The seven durable types:** `fact`, `solution`, `decision`, `pattern`, `project_context`, `error_lesson`, `conversation`.

---

## 1. Measured baseline

All figures measured on the live tree on 2026-07-28. **Do not re-derive.** The DB is live and grows during sessions; counts drift by a few rows. Shape and conclusions do not.

### Corpus (`brain/rust/brain.db`, 17,626 rows)

Active (non-superseded) rows with **zero edges**:

| type | edgeless | avg chars | p90 | p99 | max |
|---|---|---|---|---|---|
| fact | 3,896 | 100 | — | — | 9,289 |
| solution | 1,276 | 619 | 1,206 | 1,689 | 4,789 |
| conversation | 1,009 | 1,211 | — | — | 16,689 |
| project_context | 361 | 3,110 | 6,693 | 12,898 | **513,464** |
| pattern | 147 | 441 | 604 | 3,553 | 6,743 |
| error_lesson | 84 | 655 | 1,095 | 1,463 | 1,463 |
| decision | 31 | 401 | 959 | 1,501 | 1,501 |

Durable-7 edgeless total: **6,804** (2,908 non-fact). Only **21** edgeless durable rows exceed 8,000 chars; exactly **1** exceeds 32,000.

### Graph

- 8,668 entities · 20,789 edges · 9,103 linked memories · avg **2.28** edges/linked memory
- Max entity degree **343** (`Next.js`), then React 215, Supabase 199, Tailwind CSS 180, SICOP 162, TypeScript 151
- Σ deg² = **519,085** → ~57 neighbor-scan rows per memory
- **Only one type has edges today: `fact` (9,096 memories).** This is why several bugs below are currently latent.
- 11 orphan edges exist from deleted memories (`delete_memories` never cleans `edges`)

### Extraction cost (qwen3-coder:30b, warm, M4 Max, 19 real samples)

| type | latency | entities/memory |
|---|---|---|
| solution | 0.62 s | 6.0 |
| project_context | 0.83 s | 4.4 |
| pattern | 0.71 s | 6.3 |
| error_lesson | 0.60 s | 7.0 |
| decision | 0.44 s | 5.0 |
| **weighted mean (non-fact)** | **0.66 s** | **5.9** |

Prompt throughput ~1,000–1,600 tok/s. Tokenisation ≈ **6.55 chars/token** on this corpus.

### Projections (labelled as projections, not measurements)

- Backfill wall-clock: non-fact incl. conversation ≈ **36 min**; unprocessed facts ≈ **8.5 min**; total ≈ **45 min**
- New edges ≈ **+17,000–19,000** (20,789 → ~38,000–40,000, +85–92%); linked memories 9,103 → ~12,000 (+32%)

### Endpoints and eval

- `GET /linked`: **1.047 s, 23,506,483 bytes** for 9,103 memories (2,582 B/memory; `neighbor_ids` ≈ 83% of body)
- `gold_semantic.jsonl`: 18 rows → **17** after D3. Types: 12 solution, 2 error_lesson, 2 conversation, 1 pattern. **0 currently edge-linked.**
- `gold_semantic_local.jsonl`: 25 rows, 0 resolve against this DB — scoped to a different instance. **Leave untouched.**
- Legacy checkpoint (`Documents/AI/brain/bootstrap/checkpoint_entity_backfill.json`): 11,714 `processed_ids`, `linked_total` 20,778. **100% present in the current DB, all typed `fact`.** 2,618 of today's edgeless facts are in it (known-empty); 1,278 were never processed.
- Live `graph_expand` probe, query `"Supabase row level security policy"`, n=10: **3 neighbors injected at ranks 2/3/4, 3 legitimate results displaced.**

---

## 2. Build order

Strict ordering. A7 raises `TypeError` before A3 exists; A2 must precede the backfill or the backfill activates a live bug.

```
STAGE 0 (independent, ship first)
  A8  GET /linked bounding
  A9b gold row deletion + mcp_eval dangling skip

STAGE 1 (Python, strict internal order)
  A5  entity_extractor.py      ──►  A3  auto_entities + kill switch
                                      ├─► A4  batch pass-through
                                      └─► A7  fact-path opt-out

STAGE 2 (Rust, MUST precede backfill)
  A2  determinism + real distance + FILTER BYPASS FIX

STAGE 3 (data + docs)
  A6  checkpoint seed ──► widened backfill ──► A9c sync to AI tree
  A1  gold set generation ──► A/B gate
  A9a/A9d doc reconciliation
```

---

## A1 — Statistically valid success metric

**Stage:** 3 · **Depends on:** A2, A6 (backfill must have run), A9b · **Files:** `brain/tools/gen_gold_graph.py` (new), `brain/tools/graph_expand_ab.py` (new), `brain/tests/test_graph_expand_ab.py` (new)

### Problem

The base spec defers its only value gate to a follow-up ("re-run expand on vs off"). That gate cannot produce a verdict:

- 17 usable gold queries → one query flip = **5.9 pp**
- `recall@10` baseline 0.9286 → headroom ≈ **1.2 queries**
- Exact sign test needs **≥6 discordant pairs** for p<0.05 → **n ≥ 86** if expansion fixes every miss, ~170 realistically

Additionally verified: **nothing in the repo does paired comparison, confidence intervals, or significance testing.** `retrieval_eval_kfold.py` scores offline in numpy and never calls the API, so it *cannot* exercise `graph_expand` (which lives in Rust). `eval_suite.py:185` calls `api_search(query=q, n=n)` with no `graph_expand` argument. The two eval artifacts cited in `docs/ENTITY_EDGE_GRAPH.md:220` do not exist — `brain/eval/runs/` is absent, so the documented 0.0000-delta table is **unreproducible**.

### Ruled out as query sources (verified, do not revisit)

- **Feedback data:** `feedback_events` has **10 rows total**; only 3 have both a query and a `memory_id`.
- **k-fold self-queries:** title-verbatim queries put the target at rank 1 — zero headroom, zero discordant pairs.
- **No paraphrase generator exists.** The 18 existing rows were hand-written.

→ **LLM generation from memory content**, using the cheap-Ollama pattern (`OLLAMA_URL` + `OLLAMA_SUMMARIZE_MODEL`, temp 0, `/api/chat`, defensive parse). Keep the call self-contained; **do not import from `backfill_entities.py`**, which A5 is refactoring.

### Validity filter (calibrated, not guessed)

Containment overlap `|tokens(query) ∩ tokens(content)| / |tokens(query)|` measured across the 17 live gold rows: mean 0.224, **max 0.455**. Reject generated queries with overlap **> 0.45** — this reproduces the hand-written distribution.

### Stratification (n = 150 usable; generate ~220 for ~30% filter loss)

Selection requires `EXISTS (SELECT 1 FROM edges WHERE src_memory_id = m.id)` — a necessary condition for expansion to reach the target at all. Run **after** the backfill.

| type | n | note |
|---|---|---|
| solution | 40 | largest durable pool |
| fact | 30 | controls for the type the feature was built for |
| conversation | 15 | per D1 |
| project_context | 20 | |
| pattern | 20 | |
| error_lesson | 15 | pool is 84 |
| decision | 10 | pool is 31; only ~10 have ≥200 chars — take all, do not inflate |

`episode` must not appear.

### Endpoint choice (from the numbers)

- **k=1:** structurally frozen. Neighbor score = `seed × 0.85` and the diversity rerank admits the top item unconditionally. Use `Δhit@1 == 0.0` as an **invariant check** — nonzero means a Rust ranking bug, stop and fix.
- **k=3, k=5:** almost pure harm surface (neighbors enter at ranks ~2–6). **No-harm gates.**
- **k=10:** the only k where a gain can register. **Primary endpoint = `hit@10`**, usable only if the new set is unsaturated.

### Interfaces

```python
# gen_gold_graph.py
DURABLE_STRATA: dict[str, int]      # table above
MAX_VOCAB_OVERLAP = 0.45
MIN_CONTENT_CHARS = 200

def select_linked_candidates(db_path, memory_type, limit, min_chars=200, seed=42) -> list[dict]
def neighbor_degree(db_path, memory_id) -> int
def generate_query(content, model=OLLAMA_SUMMARIZE_MODEL) -> str | None
def vocab_overlap(query, content) -> float
def build_gold(db_path, strata, out_path, max_overlap=0.45, oversample=1.5, seed=42, dry_run=False) -> dict
```

Read-only SQLite (`file:...?mode=ro`). Reproducible sampling: fetch ids, then `random.Random(seed).sample` — not `ORDER BY RANDOM()`.

Prompt: *"Write one natural question a developer would ask that this note answers. Use NO words from the note — paraphrase every technical term into plain description. Return JSON: {\"query\": \"...\"}"*. Defensive parse → `None` on failure.

Row schema (superset of the existing format, so `mcp_eval.load_gold` still reads it):
`{"query", "gold_memory_id", "k": 10, "description", "memory_type", "project", "n_edges", "neighbor_degree", "source": "llm_paraphrase", "generated_at"}`
Output: `brain/eval/gold_graph_expand.jsonl`

```python
# graph_expand_ab.py
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

def validate_gold(gold, db_path) -> list[str]        # dangling ids -> hard error
def run_paired(gold, search_fn, n=10) -> list[dict]  # INTERLEAVED off/on per query
def mcnemar_exact(b, c) -> float                     # two-sided, math.comb only (no scipy in .venv)
def bootstrap_delta_ci(off, on, iters=10_000, seed=42) -> tuple[float, float]
def reachable_targets(db_path, rows) -> int          # target ∈ 1-hop(top-5 off seeds)
def filter_violations(rows, memory_type, project) -> int
def gate(report, cfg=GateConfig()) -> tuple[str, list[str]]  # PASS|FAIL|UNDERPOWERED|INVALID_SET
```

**The DB is live** (`decision` count moved 22 → 31 during the audit session). Both arms **must be interleaved per query in one process**, never two sequential passes.

`surface="template"` → `api_client.template_search(...)` (matches production MCP `search_brain`); `surface="plain"` → `api_client.search(...)`. Both arms use the identical surface. Exit code: 0 PASS, 1 FAIL, 2 UNDERPOWERED/INVALID_SET/unreachable.

### Report schema

`brain/eval/runs/graph_expand_ab_<YYYY-MM-DD>.json`:

```
run_id, gold_file, db_path, corpus_size, surface, n_queries, n_by_type
baseline: {hit@1, hit@3, hit@5, hit@10, mrr@10, latency_ms_median, latency_ms_p95}
expanded: {same keys}
delta:    {hit@k deltas, mrr delta, latency_ratio_p95}
mcnemar:  {k: {both_hit, b_gain, c_loss, both_miss, n_discordant, p_two_sided}}
ci:       {delta_hit@10: [lo, hi], delta_mrr: [lo, hi]}
diagnostics: {n_reachable, mean_neighbor_degree, injected_neighbors_median,
              filter_violations, dangling_gold_ids: []}
gate: {verdict, failed_criteria: [...], config: {...}}
```

`n_reachable` is the a-priori ceiling on gains and is computable from the off arm alone — **if it is < 12 the experiment is dead before the on arm is scored.** Measured covariate to report: 1-hop neighbor set over 2,000 linked memories has **mean 53.5, max 957**.

**`brain/eval/runs/` does not exist.** Verified: the only code that creates it is `eval_suite.py:231`, and `graph_expand_ab.py` does not run through `eval_suite`. It **must** `report_path.parent.mkdir(parents=True, exist_ok=True)` before writing, or the first real run crashes after paying for 300 live searches. Cover it with a test that writes to a `tmp_path` subdirectory that does not pre-exist.

### Why `eval_suite.py` is deliberately NOT modified

`eval_suite.py:185` calls `lambda q, n: api_search(query=q, n=n)` with no `graph_expand`. **Leave it that way.** `eval_suite` measures *default production behaviour*, and `graph_expand` defaults to `false`; plumbing the flag through it would either change the baseline numbers the dashboard trends, or add a second orchestration path for one experiment. The A/B is a purpose-built standalone tool that calls `api_client` directly with both arms — it needs nothing from `eval_suite`.

Two consequences to write into the code as comments, so this is not "fixed" later by mistake:

1. `retrieval_eval_kfold.py` scores **offline in numpy and never calls the API**, so it structurally cannot exercise `graph_expand` (which lives in Rust). It is not a candidate harness for this work and needs no change. Do not attempt to extend it.
2. **If A1's gate ever returns PASS and `graph_expand` flips to default `true`**, `eval_suite`'s baseline silently starts measuring the expanded path. At that point — and only then — `eval_suite` must gain an explicit `graph_expand=False` on its `api_search` call to keep measuring the same thing. Record this as a required follow-up on the flip, not now.

### Pass/fail — the threshold that flips `graph_expand` to default `true`

All must hold on the k=10 primary:

1. `n_queries ≥ 150`, every target edge-linked, zero dangling ids, no `episode` targets
2. `baseline.hit@10 ≤ 0.90` — else `INVALID_SET`, regenerate harder queries
3. `diagnostics.n_reachable ≥ 12` — else `UNDERPOWERED`
4. `mcnemar[10].n_discordant ≥ 12` and `b > c` — else `UNDERPOWERED`
5. `mcnemar[10].p_two_sided < 0.05`
6. `delta.hit@10 ≥ +0.03` **and** `ci.delta_hit@10[0] > 0`
7. **Invariant:** `delta.hit@1 == 0.0` exactly
8. No harm: `delta.hit@3 ≥ −0.02` and `delta.mrr ≥ −0.01` with `ci.delta_mrr[0] > −0.02`
9. `diagnostics.filter_violations == 0` on a type-filtered **and** a project-filtered sub-run (see A2)
10. `delta.latency_ratio_p95 ≤ 1.25`

Any failure ⇒ default stays `false`. `UNDERPOWERED` is an explicit third verdict, never a silent pass.

**Power note to state in the report, not hide:** at ψ ≈ 0.12–0.15 discordant rate, n=150 yields 18–22 pairs — detects a 4:1 gain:loss ratio, will **not** detect a true lift below ~3 pp.

### Tests (`brain/tests/test_graph_expand_ab.py`, no live API)

`mcnemar_exact(6,0) ≈ 0.03125`; `mcnemar_exact(3,3) == 1.0`; `run_paired` with a stub `search_fn`; `gate()` → UNDERPOWERED at b+c=5, INVALID_SET at baseline hit@10=0.95; `validate_gold` raises on a dangling id; **`test_report_path_parent_created` — write to `tmp_path / "nonexistent" / "r.json"` and assert it succeeds** (pins the missing-`runs/` fix above).

### Verification

```bash
cd /Users/abundancia888/Documents/Code/brain
curl -sS http://127.0.0.1:8787/stats -H 'x-api-key: local-dev-key'
.venv/bin/python -m pytest brain/tests/test_graph_expand_ab.py -q
.venv/bin/python brain/tools/gen_gold_graph.py --out brain/eval/gold_graph_expand.jsonl --seed 42
.venv/bin/python brain/tools/graph_expand_ab.py \
  --gold brain/eval/gold_graph_expand.jsonl --ks 1,3,5,10 --surface template \
  --report brain/eval/runs/graph_expand_ab_$(date +%Y-%m-%d).json
echo "verdict exit=$?"
```

Use this repo's `.venv` — the `Documents/AI/.venv` path in `docs/ENTITY_EDGE_GRAPH.md:183` is stale for this checkout.

### Spec edits

Replace the Follow-ups bullet *"Gold set whose targets are edge-linked durable memories; re-run expand on vs off"* with a **Success metric** section carrying criteria 1–10. Change the Decisions row for `graph_expand` from "until new gold eval" to "until `graph_expand_ab.py` returns PASS".

---

## A2 — Deterministic ranking, real distance, and the filter-bypass fix

**Stage:** 2 — **must land before the backfill** · **Depends on:** none · **Files:** `brain/rust/src/brain.rs`, `docs/ENTITY_EDGE_GRAPH.md`

### A2.1 — Filter bypass (latent bug this ship activates) — **highest priority in this document**

`expand_graph_neighbors` (`brain.rs:432-505`) reads only `filter.exclude_superseded`. Neighbors are pushed into `scored` **after** the `memory_type` / `project` filter loop (`brain.rs:332-345`), so they bypass filtering entirely and are returned.

**Verified latent, not absent.** A live probe returned 0 violations for both `memory_type=fact` and `memory_type=solution`, because:

- `type=fact` → seeds' neighbors are also facts → no visible violation
- `type=solution` → solutions have **no edges today** → nothing is injected at all

**Only `fact` has edges right now (9,096 memories).** The moment A6's backfill gives solutions, patterns and conversations edges, a `memory_type="solution"` search begins injecting `fact` neighbors that violate the filter. There are already **5,000+ cross-project neighbor pairs** waiting. Production MCP `search_brain` routes through `template_search`, which issues **type-filtered sub-searches** — so this surfaces in the product, not just the eval.

**Fix:** apply the same `memory_type` / `project` / `exclude_superseded` predicates to injected neighbors that the main loop applies to base candidates. Either filter in `neighbor_memory_ids`' SQL or filter the fetched `memories` before pushing. Prefer the SQL predicate — it also shrinks the scan.

### A2.2 — Deterministic tie-break (required for A1 to be meaningful)

`brain.rs:452` collects into `HashMap<String, f32>`; `:479` `.into_iter().collect()`; `:480` sorts by score only; `:481` `truncate(n)`. Every neighbor of a seed gets the bit-identical score `seed_score * GRAPH_HOP_DECAY` (`:458`), so **ties are the norm, not incidental**, and `truncate` keeps an arbitrary `RandomState`-ordered subset. Rust seeds `RandomState` per **instance**, so this varies between two `search()` calls in one process as well as across restarts. **A non-deterministic ranker cannot be A/B tested.**

```rust
// replace brain.rs:478-481
let mut neighbors: Vec<(String, f32)> = best_neighbor_score.into_iter().collect();
neighbors.sort_by(|a, b| {
    b.1.partial_cmp(&a.1)
        .unwrap_or(std::cmp::Ordering::Equal)
        .then_with(|| a.0.cmp(&b.0))
});
neighbors.truncate(n);

// replace the merge sort at brain.rs:503 with the same key
scored.sort_by(|a, b| {
    b.1.partial_cmp(&a.1)
        .unwrap_or(std::cmp::Ordering::Equal)
        .then_with(|| a.0.id.cmp(&b.0.id))
});
```

`(score desc, id asc)` is total — memory ids are unique primary keys.

**Do not touch the baseline sort at `brain.rs:391`.** Its input order is already deterministic and `sort_by` is stable; changing it would alter the default `graph_expand=false` path.

### A2.3 — Real cosine distance

`brain.rs:497` hardcodes `distance: 1.0` on injected neighbors. `distance` everywhere else means `1 - cosine_similarity` (`index.rs:128`). `1.0` means "orthogonal to the query", which is almost never true, and it silently cancels expansion downstream: `hooks/post_tool_use.py:87` drops hits with `distance >= 0.5`, and `tools/retrieval_rerank.py:40` sorts ascending, sinking every expanded hit.

**Verified safe:** `get_memory` SELECTs `embedding`, and **0 of 17,626 rows have a NULL embedding** — the `unwrap_or(1.0)` fallback is dead code in practice.

```rust
// brain.rs:397 — `embedding` (line 284) is only borrowed at 294, so no clone needed
self.expand_graph_neighbors(&mut scored, n, filter.as_ref(), &embedding)?;

// in the push loop, brain.rs:490-501
let distance = memory.embedding.as_ref()
    .map(|e| cosine_distance(query_embedding, e))
    .unwrap_or(1.0);

// new private fn near GRAPH_HOP_DECAY (brain.rs:26); no shared helper exists
fn cosine_distance(query: &[f32], other: &[f32]) -> f32 {
    if query.len() != other.len() { return 1.0; }
    (1.0 - query.iter().zip(other).map(|(a, b)| a * b).sum::<f32>()).clamp(0.0, 2.0)
}
```

Corrects the reported `distance` only — it does **not** feed back into `score`, so P@1 is preserved.

### A2.4 — Displacement guard: NOT this ship (D7)

Measured: 3 neighbors injected at ranks 2/3/4, 3 legitimate results displaced. **Correction to an earlier claim in the audit:** the driver is not a narrow score spread. `bm25_norm` (`brain.rs:349-358`) is rank-linear and collapses to `0.0` for anything absent from the BM25 set — a **0.3 absolute score cliff at `alpha=0.7`**. That is why `0.85 × s1` outranks a cosine-only rank 2.

Deferred because: zero production callers pass `graph_expand=true` (verified — every Python occurrence is a parameter defaulting to `False`); and every candidate guard needs a tuned constant, which cannot be tuned against a shuffling ranker. Bundling both would confound the guard's measured effect with the tie-break's.

**Pre-registered guard for the next ship, if A1's A/B shows displacement: skip neighbors reached *only* through high-degree hub entities.** Justification: mean degree 2.4, so a *typical* seed reaches ~3 neighbors and has no problem; all damage is in the tail — one seed touching `Next.js` (degree 343) injects 342 candidates at a single tied score. Rejected alternatives: a per-seed cap makes garbage deterministic rather than absent; requiring ≥2 shared entities is an off-switch at avg 2.28 entities/memory and would be misread as "expansion has no value".

### Tests (in-module at `brain.rs:756`, reuse `test_brain()` and the `graph_expand_surfaces_linked_neighbor_above_decoy` setup at `:986`)

Shared setup: one seed matching the query + 8 neighbors all linked to the same single entity, distinct filler content, `n = 4` so `truncate` must discard.

1. `graph_expand_neighbor_tie_break_is_stable_across_calls` — 20 identical searches, assert every run equals the first. Pre-fix this fails with probability ≈1.
2. `graph_expand_tie_break_prefers_lowest_id` — pins the *rule*: injected ids equal `sorted(ids)[..k]`.
3. `graph_expand_preserves_top1` — off vs on, assert `baseline[0].id == expanded[0].id == seed_id`; also with `n = 1`.
4. `graph_expand_reports_real_cosine_distance` — with `MockEmbedder::new(16)` as probe, assert `distance` within `1e-4` of `1.0 - dot(q, v)`.
5. **`graph_expand_respects_memory_type_filter`** — seed of type Fact linked to a Solution neighbor; search with `memory_type: Some(Fact)`; assert no Solution appears.
6. **`graph_expand_respects_project_filter`** — same shape across two projects.

`store.rs` needs no new test if the filter lands in Rust; if it lands in SQL, add one for the predicate.

### Verification

```bash
cd /Users/abundancia888/Documents/Code/brain/brain/rust
cargo test --lib graph_expand
cargo test --lib -q
cargo clippy --all-targets
cargo build --release --bin brain_api
launchctl kickstart -k gui/$(id -u)/com.brain.api

# cross-process determinism: run twice with a restart in between, ids must match
curl -sS -X POST http://127.0.0.1:8787/search -H 'content-type: application/json' \
  -H 'x-api-key: local-dev-key' \
  -d '{"query":"Supabase row level security policy","n":10,"graph_expand":true}' \
  | python3 -c 'import sys,json;print([h["id"] for h in json.load(sys.stdin)["results"]])'
```

### Docs

`docs/ENTITY_EDGE_GRAPH.md:76` — state the `score desc, id asc` ordering. `:79` — expanded hits now carry a real cosine distance, and note that filters apply to neighbors.

---

## A3 — `auto_entities` parameter and kill switch

**Stage:** 1 · **Depends on:** A5 · **Files:** `brain/api_client.py`, `brain/hooks/spool.py`, `brain/core/memory.py`, 13 bulk call sites

### Problem

The base spec puts auto-extraction inside the `api_client` save helpers and lists only `BRAIN_BACKEND=python` as out of scope. Verified: `api_client.save_memory` is called directly by 9 bootstrap ingest scripts plus `core/session_ingest.py`. Each would silently gain one 30B-model round-trip per memory — an Obsidian re-ingest of a few thousand notes goes from minutes to about an hour.

**Census corrections (verified, the audit's original list was wrong on one point):** `brain/core/memory.py:173` calls a **local** `save_memory` defined in that same file, not `api_client`'s. It never reaches the network extractor and needs no opt-out. Separately, `brain/post_tool_use.py`, `brain/session_end.py`, `brain/memory.py`, `brain/spool.py`, `brain/server.py`, `brain/ingest_session_chunks.py`, `brain/reingest_ocreamer_docs.py`, `brain/verify_cutover.py` are **stale top-level duplicates**. The live hooks are `brain/hooks/*.py`. Do not touch the duplicates.

> **Correction — "nothing imports them" is false for exactly one.** `brain/hooks/session_end.py:25` does `from brain.memory import save_memory as py_save` — the **stale top-level** module, not the synced `brain/core/memory.py`. Verified: the stale copy has **0** references to `auto_entities`; `brain/core/memory.py` has 2. Today this is dead code because `BRAIN_BACKEND=api`, so the branch never executes. Flip that env var to `python` and `session_end`'s saves route through an un-synced module that will raise `TypeError: unexpected keyword argument 'auto_entities'`. Latent, not active — but the blanket claim above should not be relied on.

### Design

**Default ON** (`auto_entities: bool = True`), with `BRAIN_AUTO_ENTITIES` as an OFF-only kill switch.

Justified by the census, not preference: with default True, 13 bulk sites add `auto_entities=False` and **zero** interactive files change — which is what makes the base spec's "hooks already go through these helpers → no per-hook entity code" true. With default False the reverse holds, and any future interactive call site that forgets to opt in silently loses linking. Missing edges are quiet; a cost blowup is loud and already characterised. Backfill also makes the default-True failure mode recoverable.

Extraction runs iff **all** of: (1) `entities` is empty, (2) `memory_type` ∈ durable-7, (3) `auto_entities` is `True`, (4) `BRAIN_AUTO_ENTITIES` not disabled. The env var can only turn extraction **off**; it never forces it on for a site that passed `False`.

```python
def _auto_entities_env_enabled() -> bool:
    """Global kill switch — OFF-only. Default enabled."""
    return os.environ.get("BRAIN_AUTO_ENTITIES", "1").strip().lower() not in {"0", "false", "no", "off"}

def _maybe_extract_entities(*, memory_type, content, entities, auto_entities):
    if entities:
        return entities
    if not auto_entities or not _auto_entities_env_enabled():
        return entities
    try:
        # D6: lazy import keeps api_client stdlib-only at import time.
        # MUST be inside the try — in an environment without `requests` this
        # raises ImportError, and an unguarded import would fail the save.
        from brain.ingest.entity_extractor import extract_entities, DURABLE_MEMORY_TYPES
        if memory_type not in DURABLE_MEMORY_TYPES:
            return entities
        return extract_entities(content) or None
    except Exception:
        return entities
```

**D6 is load-bearing.** Verified: `api_client.py` imports **only stdlib** today (`json, os, sys, urllib.*, typing`) and `config.py` pulls nothing heavy. A5's extractor imports `requests`. A module-level import would give `api_client` a third-party dependency and break the lean callers (`core/session_ingest.py` documents a Hermes venv with no numpy). **Import inside the function, and inside the `try`.**

> **Resolved during implementation — read this before writing the import.**
> A5 discovered that `brain/ingest/__init__.py` eagerly re-exported `fact_extractor` / `fact_curator`, which pull `numpy` + `torch` + `sentence-transformers`. Because Python always executes a package `__init__` before any submodule, `from brain.ingest.entity_extractor import ...` inherited that cost. **Measured: 2.00 s and torch loaded, versus 0.06 s for the module alone.** `PostToolUse` spawns a fresh process per Edit/Write and currently pulls **zero** heavy modules (0.02 s), so this would have added ~2 s to every edit on top of the 0.66 s extraction.
>
> **Fixed:** `brain/ingest/__init__.py` is now lazy (PEP 562 `__getattr__`). Re-measured after the fix: `from brain.ingest import entity_extractor` = **0.05 s, no heavy modules**; light members (`with_ingest_tag`, `chunk_by_sections`) still resolve instantly; heavy members (`FactDraft`, `curate_facts`) still work and pull torch only on demand; unknown attributes still raise `AttributeError`. Full suite after the change: **237 passed, 4 pre-existing failures** (`test_mcp` "Trust: 0.90" formatting ×3, and `test_retrieval_eval_smoke` needing `brain/eval/gold.jsonl`, a file never tracked in git).
>
> A3 needs no workaround — just use the import above as written.

Style: copy the `.strip().lower()` / set-membership shape from `api_client.py:19-24` (`BRAIN_ENFORCE_API_ONLY`). This is deliberately opt-**out** unlike the repo's other flags (`BRAIN_FACT_EXTRACT`, `BRAIN_EVAL_AUTO` — all opt-in) because it is a kill switch, the mirror case.

Wire into `save_memory` (`:149`, before `:190`), `save_memory_with_status` (`:195`, before `:225`), and `save_memory_batch` (`:232`, see A4 — pass-through only, `default_auto_entities=False`).

### D5 — spool fix (one line, not three files)

Verified: `hooks/post_tool_use.py:181-193` builds `payload` with no `entities`, calls `save_memory_with_status(**payload)`, and on failure spools that same pre-extraction dict. `hooks/spool.py:139-143` then replays it, re-extracting on every retry up to `MAX_ATTEMPTS = 8`.

Rejected: smuggling the augmented payload through an exception attribute across `api_client` → `post_tool_use` → `spool`. The spool only fills during API outages and attempts are bounded; three files of coupling is not worth it.

```python
# brain/hooks/spool.py, in replay_once, replacing `payload = rec.get("payload", {})`
payload = {**rec.get("payload", {}), "auto_entities": False}
```

Spooled memories save without entities; the backfill catches them — the same safety-net principle as A7. Single choke point for all replays.

### `core/memory.py` compatibility (required)

`core/session_ingest.py:26-37` dispatches `**kwargs` to **either** `brain.core.memory.save_memory` or `api_client.save_memory` by `backend_mode()`. Adding `auto_entities=False` to its call sites would raise `TypeError` under `BRAIN_BACKEND=python`. Add `auto_entities: bool = True` (accepted, unused) to `core/memory.py`'s `save_memory` signature.

> Note: `core/memory.py` defines `save_memory` **twice** (lines 15 and 110; the second shadows the first). Pre-existing, out of scope — add the parameter to the effective definition and flag the duplication separately.

### Opt-out call sites (add `auto_entities=False`)

| File:line | memory_type source |
|---|---|
| `brain/bootstrap/03_ingest.py:30` | data-driven |
| `brain/bootstrap/05_ingest_claw.py:135` | default `project_context` |
| `brain/bootstrap/06_ingest_perplexity.py:84` | data-driven |
| `brain/bootstrap/08_ingest_books.py:269` | `solution` |
| `brain/bootstrap/09_ingest_obsidian.py:69` | default `solution` |
| `brain/bootstrap/11_ingest_quantum.py:142` | `solution` |
| `brain/bootstrap/12_ingest_ppf_contact_solver.py:194,209,223,237` | conversation/solution/conversation/pattern |
| `brain/bootstrap/13_ingest_alphafold.py:182,205,295` | solution/conversation/project_context |
| `brain/bootstrap/17_ingest_fhir.py:233` | data-driven |
| `brain/bootstrap/ingest_claude_code_lib.py:88` | batch — `default_auto_entities=False` |
| `brain/reingest_ocreamer_docs.py:140` | batch, `project_context` — **required** |
| `brain/core/session_ingest.py:94,126,185,238` | error_lesson/pattern/project_context/solution |
| `brain/ingest_session_chunks.py:99` | batch, `conversation` — defence-in-depth |
| `brain/verify_cutover.py:23` | `pattern` — hygiene, one-off |

**No change:** `hooks/post_tool_use.py`, `hooks/session_end.py`, `mcp/server.py`. **`fact_curator.py:180` is resolved by A7/D4 — it passes `False` explicitly.**

### Tests (`brain/tests/test_api_client_auto_entities.py`, no live Ollama)

Monkeypatch `api_client._request` and the lazily-imported extractor (patch `brain.ingest.entity_extractor.extract_entities`), per the `test_realtime_save_search.py` pattern:

1. durable type, defaults → extractor called once with `content`
2. `auto_entities=False` → not called, no `entities` in payload
3. `memory_type="episode"` → not called
4. pre-supplied `entities=["Bar"]` → not called, payload keeps `["Bar"]`
5. extractor raises → save still returns the id
6. `BRAIN_AUTO_ENTITIES=0` → not called
7. repeat 1–3 for `save_memory_with_status`
8. **`test_api_client_imports_no_third_party`** — assert `requests` is absent from `sys.modules` after a fresh `import brain.api_client` (pins D6)

Extend `brain/tests/test_spool_replay.py`: `test_replay_disables_auto_extraction` — assert the payload passed to `save_memory_with_status` during replay carries `auto_entities=False`.

### Verification

```bash
cd /Users/abundancia888/Documents/Code/brain
python3 -m pytest brain/tests/test_api_client_auto_entities.py brain/tests/test_spool_replay.py \
  brain/tests/test_realtime_save_search.py brain/tests/test_fact_curator.py -v
python3 -m pytest brain/tests/ -q
```

---

## A4 — `save_memory_batch` pass-through only

**Stage:** 1 · **Depends on:** A3 · **Files:** `brain/api_client.py`, `brain/tests/test_save_memory_batch.py` (new)

### Problem and finding

`save_memory_batch` (`api_client.py:232-253`) builds each item from an explicit key whitelist and **drops `entities` entirely** — the batch path cannot carry entities even when a caller supplies them. The Rust side already accepts them per item (`brain_api.rs:100-102`, `:607-613`, fail-soft).

**This amendment overrides the base spec's Component 2**, which says to apply auto-extraction to `save_memory_batch`. Verified batch callers:

| Caller | memory_type | durable? |
|---|---|---|
| `brain/ingest_session_chunks.py:62` | `"conversation"` hardcoded | yes under D1, but see below |
| `brain/bootstrap/ingest_claude_code_lib.py:134` | `record["metadata"]["type"]`, always `"conversation"` (`claude_code_extractors.py:109` is the sole assignment; the `.get(..., "conversation")` fallback is dead code) | same |
| `brain/reingest_ocreamer_docs.py:99` | `"project_context"` hardcoded | yes |

All three are **bulk/migration** paths. `reingest_ocreamer_docs.py` has no checkpoint or resume — a mid-run failure just skips a doc. Adding synchronous per-item Ollama calls there means unbounded serial cost with no resumability, duplicating what the checkpointed backfill already does properly. Memories saved through this path land edgeless and are picked up by A6's widened backfill automatically. **No coverage gap.**

### Change (whole fix)

```python
# api_client.py, after the timestamp block (~:251), before payload_items.append(body)
if item.get("entities"):
    body["entities"] = item["entities"]
```

Matches the truthy-check style of every other optional field and of `save_memory:190`. Add `default_auto_entities: bool = False` for A3's signature symmetry, but **do not call the extractor from this path.**

### Tests (`brain/tests/test_save_memory_batch.py`)

Monkeypatch `api_client._request` (assert `method=="POST"`, `path=="/save-batch"`, `timeout==120`):

1. provided entities pass through
2. absent `entities` → key omitted
3. `entities: []` → key omitted
4. durable type without entities → key omitted (**proves no extractor call**)
5. per-item independence across a two-item batch

Regression: `brain/tests/test_ingest_session_chunks.py`.

### Verification

```bash
cd /Users/abundancia888/Documents/Code/brain
python3 -m pytest brain/tests/test_save_memory_batch.py brain/tests/test_ingest_session_chunks.py -v
```

### Spec edit

Amend Component 2 to state the asymmetry explicitly: `save_memory` and `save_memory_with_status` auto-extract; `save_memory_batch` is pass-through only, by design. **Record the reason** — otherwise the next reader "fixes" it back.

---

## A5 — Shared extractor module with input cap

**Stage:** 1, first · **Depends on:** none · **Files:** `brain/ingest/entity_extractor.py` (new), `brain/ingest/__init__.py`, `brain/tools/backfill_entities.py`, `brain/tests/test_entity_extractor.py` (new)

### Move verbatim from `brain/tools/backfill_entities.py`

`_ENTITY_STOPLIST` (:36), `_ENTITY_PROMPT` (:49), `_call_llm` (:64, `timeout=120`), `_clean_entities` (:79), `_parse_entities` (:99), `extract_entities` (:122), `MAX_ENTITIES_PER_FACT = 12` (:33). Keep the constant name — renaming is churn.

`backfill_entities.py` retains `select_edgeless_*`, checkpoint I/O and `run()`.

### Module

```python
"""Cheap named-entity extraction for durable-memory linking.

Shared by live save (api_client) and brain/tools/backfill_entities.py.
Never raises — callers get [] on any failure so a save is never blocked.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path          # NOTE: required — an earlier draft omitted this
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import OLLAMA_URL, OLLAMA_SUMMARIZE_MODEL

DURABLE_MEMORY_TYPES = frozenset({
    "fact", "solution", "decision", "pattern",
    "project_context", "error_lesson", "conversation",   # D1
})
MAX_ENTITIES_PER_FACT = 12
MAX_INPUT_CHARS = 8000

def extract_entities(text: str) -> list[str]:
    """Never raises; returns [] on any failure."""
    prompt = _ENTITY_PROMPT.format(text=text[:MAX_INPUT_CHARS])
    try:
        raw = _call_llm(prompt)
    except Exception as e:
        print(f"[entity_extractor] LLM call failed: {e}", file=sys.stderr)
        return []
    return _parse_entities(raw)
```

The `sys.path.insert` + `from config import` shape matches `brain/ingest/fact_extractor.py:17-18` — repo convention, not an invention.

`DURABLE_MEMORY_TYPES` holds **bare** strings (matching the `memory_type` argument). The DB stores JSON-encoded types (`'"fact"'`); **A6 keeps its own quoted tuple for SQL — do not feed this frozenset into a SQL `IN` clause.**

Export from `brain/ingest/__init__.py` alongside `FactDraft`/`extract_facts`, adding both names to `__all__`.

**Keep this module dependency-light** (`requests` + stdlib only, no numpy / sentence-transformers) — A3 lazy-imports it from `api_client`, which lean environments import.

### `backfill_entities.py` edits

Delete the extraction block. Import as a module (`from brain.ingest import entity_extractor`) rather than by name, so a single patch target covers both callers — matching how `fact_curator.py:33` does `import brain.api_client as api_client`. Line 212 becomes `entity_extractor.extract_entities(...)`.

> **Two corrections found during implementation:**
> 1. An earlier draft said "delete lines 33–130". **That range includes line 34, `PROGRESS_EVERY = 25`**, which `run()` still uses — deleting it verbatim breaks the backfill with `NameError`. Keep `PROGRESS_EVERY`.
> 2. `backfill_entities.py` only inserted `parents[1]` (`brain/`) on `sys.path`, for `import api_client`. `from brain.ingest import ...` needs the **repo root**, so run as a script it would `ModuleNotFoundError`. Add `sys.path.insert(0, str(_REPO_ROOT))`, matching `backfill_facts.py:32`, and keep the existing `brain/` insert.
>
> Also intentional: stderr prefixes inside the moved functions change from `[backfill/entities]` to `[entity_extractor]`, since the module now also runs on live saves where the old prefix would be misleading. Prompt text, stoplist contents and `MAX_ENTITIES_PER_FACT` are byte-identical.

### Cap justification (from measured percentiles)

`MAX_INPUT_CHARS = 8000`, plain head-truncation.

- p99 ≤ 1,689 chars for every durable type except `project_context` (p99 12,898). 8,000 leaves solution/pattern/error_lesson/decision untouched at p99 and only trims the `project_context` tail.
- Only **21** edgeless durable rows exceed 8,000; exactly **1** exceeds 32,000. The cap changes nothing for >99.6% of the corpus.
- 8,000 chars ≈ 1,221 tokens ≈ ~2.0 s. The uncapped 513,464-char outlier is ~78,000 tokens — either a ~40 s call or silent Ollama context-shifting that yields garbage with no error.
- Head-truncation over head+tail or chunk-and-merge: 21 affected rows do not justify a multi-call merge pipeline, and the repo's existing convention for exactly this problem is unconditional head-slicing (`retitle_ppf_llm.py:31` `MAX_CONTENT_CHARS = 1200`; `reembed_conversations.py:60` `content[:1500]`). **Verified: `text_chunking.py` has no char-cap primitive to reuse** — it does word/section splitting only.

### Stoplist: leave it alone this ship

Sampled durable extractions produced ~15% low-value terms (`DOM`, `ssr`, `AI`, `assistant`, `agent`, `scene`, `sphere`, `version control`, `len() function`, `h-screen`). Unlike the current stoplist's bounded categories, these span unrelated domains — piecemeal additions are whack-a-mole. `graph_expand` is off by default, so the exposure is UI-only today. Tuning without a labelled set is guesswork. **Track as a follow-up next to A1's gold set**, where it can be evaluated against real precision.

### `num_ctx`

Verified: **no call site in the repo sets `num_ctx`** — `options` is always `{"temperature": 0.0}` or `{"num_predict": ...}`. The model default governs. Not changed here (the fix is capping input, not reshaping the call). Residual risk if the default context is under ~1,221 tokens + overhead — unlikely, flagged.

### Tests

New `brain/tests/test_entity_extractor.py` — move the 9 extractor tests from `test_backfill_entities.py` (currently 16 tests: 9 extractor at lines 26–95, 7 selection/run at 140–277), retargeted, plus:

- `test_extract_entities_truncates_input_before_prompting` — capture the prompt, assert embedded text length == `MAX_INPUT_CHARS`
- `test_extract_entities_does_not_truncate_at_or_under_cap` — boundary
- `test_parse_entities_rejects_non_dict_json` / `_missing_entities_key` / `_non_list_entities`
- `test_durable_memory_types_contains_expected_seven`
- `test_extract_entities_never_raises_on_unexpected_exception` — `_call_llm` raises `ValueError` → `[]`

`test_backfill_entities.py` keeps the 7 selection/run tests; retarget their mocking from `backfill_entities._call_llm` to `backfill_entities.entity_extractor.extract_entities`.

### Verification

```bash
cd /Users/abundancia888/Documents/Code/brain
python3 -m pytest brain/tests/test_entity_extractor.py brain/tests/test_backfill_entities.py -v
python3 -c "from brain.ingest import entity_extractor as e; print(sorted(e.DURABLE_MEMORY_TYPES), e.MAX_INPUT_CHARS)"
python3 -m pytest brain/tests/ -k entity -v
```

---

## A6 — Checkpoint seeding and widened selection

**Stage:** 3, first · **Depends on:** A2 (must land first), A5 · **Files:** `brain/tools/backfill_entities.py`, `brain/tools/seed_durable_backfill_checkpoint.py` (new), tests

### Overriding the base spec's locked checkpoint decision

The base spec locks "new checkpoint file … do not treat fact-only progress as complete". **That intent is preserved; the cost is not.** Verified:

- Legacy checkpoint: 11,714 `processed_ids`, **100% present in the current DB, 100% typed `fact`**
- **2,618** of today's 3,896 edgeless facts are in that set — processed, yielded zero entities, still edgeless
- 1,278 were never processed

A fresh checkpoint re-extracts all 3,896, of which 2,618 are known-empty ≈ **17 minutes of GPU for guaranteed-zero yield**.

**Decision: seed the new durable checkpoint from the legacy one, fact-ids only.** The five non-fact types were never checkpointed, so they start at zero either way — which is exactly what the locked decision requires. Refusing to reuse *verified fact progress* is not required by it.

**Risk assessment (the crux):** could a known-empty fact now yield entities?

1. *Prompt change* — none in A6. A5 relocates the same prompt verbatim. Mitigated by the pre-flight below.
2. *Input cap* — A5 adds one, but facts average 100 chars; an 8,000-char cap cannot affect them. Not a risk vector.
3. *Model drift* — `OLLAMA_SUMMARIZE_MODEL` tags can be silently re-pulled. **Unverifiable.** This is the one real gap.
4. *Bounding* — worst case is a **completeness** risk (a few facts stay edgeless longer), never a **correctness** one. No wrong edges, nothing deleted, fully recoverable via `--reset-checkpoint`.

**Mandatory pre-flight (~20 s):** run `--dry-run` over ~50 ids from the known-empty intersection and confirm they still extract `[]`. If a non-trivial fraction now yields entities, **abort the seed** and run facts unseeded. Record the outcome in the PR as the go/no-go gate.

### Widened selection

```python
_DURABLE_TYPES = ('"fact"', '"solution"', '"decision"', '"pattern"',
                  '"project_context"', '"error_lesson"', '"conversation"')  # D1

def select_edgeless_durable(db_path, limit=None, project=None) -> list[dict]:
    """Active durable memories (not superseded) with zero outgoing edges, newest first."""
    uri = f"file:{db_path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        placeholders = ",".join("?" for _ in _DURABLE_TYPES)
        query = (
            f"SELECT id, content, project, timestamp FROM memories "
            f"WHERE type IN ({placeholders}) "
            "AND (superseded_by IS NULL OR superseded_by = '') "
            "AND id NOT IN (SELECT DISTINCT src_memory_id FROM edges)"
        )
        params: list = list(_DURABLE_TYPES)
        if project:
            query += " AND project = ?"; params.append(project)
        query += " ORDER BY timestamp DESC"
        if limit:
            query += " LIMIT ?"; params.append(limit)
        return [dict(r) for r in conn.execute(query, params).fetchall()]
    finally:
        conn.close()
```

Rename `select_edgeless_facts` → `select_edgeless_durable`; update the call site in `run()` (:201) and tests. `--project` / `--limit` wiring in `main()` (:259-274) is unchanged.

**Types are JSON-encoded in the DB** (literal quotes). Keep this quoted tuple local — do **not** import A5's bare-string frozenset into SQL.

Checkpoint path (`:31`) → `checkpoint_entity_backfill_durable.json`, resolved repo-relative via the existing `_REPO_ROOT` pattern. Leave the old file on disk as the seed source and historical record.

### Seed script

`brain/tools/seed_durable_backfill_checkpoint.py`, run once, manually. **No `Documents/AI` path in committed code** — `--source PATH` is required and supplied by the operator; `--target` defaults to the new checkpoint; `--dry-run` supported.

```python
def seed_processed_ids(source_path, target_path, db_path=DB_PATH) -> dict:
    legacy_ids = set(json.loads(source_path.read_text()).get("processed_ids", []))
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    fact_ids = {r[0] for r in conn.execute("SELECT id FROM memories WHERE type = '\"fact\"'")}
    conn.close()
    valid = legacy_ids & fact_ids          # defensive: must exist AND be a fact
    target = json.loads(target_path.read_text()) if target_path.exists() else {
        "processed_ids": [], "linked_total": 0, "facts_seen": 0}
    before = set(target["processed_ids"])
    merged = before | valid
    target["processed_ids"] = sorted(merged)
    target.update(seeded_from=str(source_path), seeded_count=len(valid), seeded_at=_now_iso())
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(json.dumps(target))
    return {"added": len(merged) - len(before), "total_processed": len(merged)}
```

`linked_total` / `facts_seen` are deliberately **not** copied — they must keep meaning "work done by runs of this checkpoint". Provenance lives in `seeded_*`.

`brain/tools/backfill_state.py` (a preview/run staging tracker) and `migrate_checkpoints.py` (a one-off script) were both evaluated: neither exposes a reusable processed-id abstraction. Follow `migrate_checkpoints.py`'s *shape*, import nothing from it.

### Tests (`brain/tests/test_backfill_entities.py` + new `test_seed_durable_backfill_checkpoint.py`)

Extend `_make_test_db` (:97-137) with edgeless active rows for all seven types, an `episode` row, a superseded non-fact, and an edged non-fact.

1. selection includes all seven durable types
2. selection excludes `episode`
3. excludes superseded (non-fact too)
4. excludes rows with edges (non-fact too)
5. rename existing project-filter / limit tests
6. **`test_run_marks_processed_on_empty_extract`** — closes a real gap: no current test covers the empty-extract branch
7. keep the success branch and the `link_entities`-raises branch (already covered)

Seed script: imports legacy ids; filters ids absent from the DB; filters non-fact ids; idempotent on a second run (`added == 0`); preserves pre-existing target ids.

### Verification

```bash
cd /Users/abundancia888/Documents/Code/brain
.venv/bin/python -m pytest brain/tests/test_backfill_entities.py \
  brain/tests/test_seed_durable_backfill_checkpoint.py -v

# pre-flight go/no-go
.venv/bin/python brain/tools/backfill_entities.py --dry-run --limit 50

# seed (operator supplies the legacy path explicitly)
.venv/bin/python brain/tools/seed_durable_backfill_checkpoint.py \
  --source /Users/abundancia888/Documents/AI/brain/bootstrap/checkpoint_entity_backfill.json

# selection sanity — expect ~6,800
.venv/bin/python -c "from brain.tools.backfill_entities import select_edgeless_durable; \
from pathlib import Path; print(len(select_edgeless_durable(Path('brain/rust/brain.db'))))"
```

### Flagged unverifiable

Repo history is a single squashed commit, so the exact script version that produced the legacy checkpoint cannot be diffed. Same for the model weights behind the tag. Both are mitigated by the pre-flight.

---

## A7 — Fact path opt-out

**Stage:** 1, last · **Depends on:** A3 (raises `TypeError` before it) · **Files:** `brain/ingest/fact_curator.py`, `brain/tests/test_fact_curator.py`

### Correction to the audit

There is **no second save call site at line 329.** That line is `entities=draft.entities` inside a `FactDraft(...)` constructor for the MERGE branch, which then calls `_save_fact(merged, ...)`. **All five branches of `_curate_one`** (no-existing :258, below-tiebreak :282, tiebreaker-ADD :299, UPDATE :311, MERGE :333) route through the single `_save_fact` helper (:171-192). This is a **one-line change**.

### Why an explicit flag, not the emptiness heuristic

`_save_fact:191` passes `entities=draft.entities or None`. When the curator draft has no entities, that collapses to `None` — precisely the "missing/empty" condition that triggers auto-extraction. So the base spec's rule silently produces a second, different-prompt LLM call for every fact the heavy prompt left empty.

The interesting part: that second call is **not** waste. The backfill's dedicated NER prompt, run against exactly this population, recovered entities for ~78% of them (11,714 processed → ~2,618 still empty). The heavy fact-extraction prompt does multi-task work (content + salience + event_time + fact_type + entities in one JSON response) and plausibly has lower entity recall than a single-purpose prompt.

**It is suppressed anyway** because backfill already recovers that same 78% off the hot path, with checkpointing and rate-limit handling. Paying 0.66 s synchronously per affected save buys latency, not coverage. Facts are the one type that already paid for an entity-extraction attempt; they should not pay twice synchronously. An emptiness heuristic would also couple behaviour silently to prompt quality — improve the heavy prompt later and this changes with no code edit.

Cost avoided: at a 22.3% empty rate, ~22 extra synchronous Ollama calls per 100 live fact saves ≈ 14.5 s per 100 facts, on top of the existing heavy-prompt latency.

### Change

```python
# brain/ingest/fact_curator.py, _save_fact (:171-192)
return api_client.save_memory(
    ...
    entities=draft.entities or None,   # unchanged — non-empty case still forwards
    auto_entities=False,               # D4
)
```

Do not alter the `entities=` line. `fact_extractor.py` needs no change.

### Tests (`brain/tests/test_fact_curator.py`, follow the `fake_save(**kwargs)` pattern at :329)

1. `test_save_fact_passes_auto_entities_false_with_entities` — assert `entities == [...]`, `auto_entities is False`, one call
2. `test_save_fact_passes_auto_entities_false_when_empty` — assert `entities is None`, `auto_entities is False`, one call

Two tests only. (An earlier draft proposed a third with a `MagicMock` guard and then retracted it mid-paragraph — omit it; `auto_entities=False` is what makes the extractor unreachable, and `api_client` is fully mocked.)

### Verification

```bash
cd /Users/abundancia888/Documents/Code/brain
python3 -m pytest brain/tests/test_fact_curator.py -v
grep -n "auto_entities" brain/ingest/fact_curator.py brain/api_client.py
```

### Spec edit

Component 3 currently says "when those entities are non-empty, `api_client` must not call the cheap extractor again." Replace with: *"the fact path always passes `auto_entities=False` and never falls back to the cheap extractor, even when curator entities are empty — backfill covers the residual."*

---

## A8 — Bound `GET /linked`

**Stage:** 0, independent · **Depends on:** none · **Files:** `brain/rust/src/store.rs`, `brain/rust/src/bin/brain_api.rs`, `brain/rust/ui/src/lib/linkedGraphModel.ts`, `.../views/Linked.tsx`, `.../components/LinkedFloater.tsx`, `.../lib/linkedGraphModel.test.ts`

### Problem

Measured: **1.047 s, 23,506,483 bytes** for 9,103 linked memories. `list_linked_memories` (`store.rs:962-1008`) has no LIMIT and issues **2 sub-queries per row** (18,206 total), all under `lock_brain` — the same mutex as `/save` and `/search`. `content` is fetched in full for every row and then truncated to 160 chars in Rust (`:996`).

### The decisive finding

`neighbor_ids` is ~83% of the payload and is used in **exactly one place, as a length**:

- `linkedGraphModel.ts:59` copies it onto the node; `:69-74` builds graph links **only** from `m.entities`. Neighbors are never edges in the graph.
- `LinkedFloater.tsx:103` renders `{selected.neighbor_ids.length} neighbor memories` — for the single selected memory.

`api.js:51 getNeighbors(memoryId)` already exists and is already used lazily by `MemoryCard.jsx:68`.

Pagination was evaluated and **rejected**: `Linked.tsx:42` builds a full in-memory bipartite graph and every downstream operation works over `fullGraph.nodes`. Pagination is unusable without rewriting the view.

### Arithmetic

2,582 B/memory measured. Non-neighbor fields ≈ 440 B (id 44 + snippet ≤160 + type/project/timestamp ~60 + 2.28 entities × ~60). Residual ≈ 2,142 B ≈ 55 UUIDs at 39 B — consistent with the Σd²/N = 57 upper bound.

- After removal: 9,103 × 440 B + 0.6 MB entity list ≈ **4.0–4.6 MB**
- Post-backfill it then scales **linearly** (memories +32%, entity refs +85%) → ~6 MB, versus a projected 35–50 MB if left alone

The point is that the only super-linear term (Σd²) **leaves the endpoint entirely** rather than being scaled by a constant. A per-memory neighbor cap was rejected: it keeps the Σd² scan server-side and silently corrupts the count the floater renders.

### Changes

1. `store.rs:51-59` — drop `neighbor_ids` from `LinkedMemoryRow`.
2. `store.rs:962-1008` — one query, no per-row calls:

```sql
SELECT m.id, substr(m.content, 1, 160), m.type, m.project, m.timestamp, e.id, e.name
FROM memories m
JOIN edges x    ON x.src_memory_id = m.id
JOIN entities e ON e.id = x.dst_entity_id
ORDER BY m.timestamp DESC, m.id, e.name_normalized
```

Fold consecutive rows by `m.id`. Correctness notes:
- `m.id` **must** follow `m.timestamp DESC` in `ORDER BY` — timestamp ties would otherwise interleave two memories' rows and break consecutive-run grouping.
- `e.name_normalized` third preserves current per-memory entity ordering (`entities_for_memory:951`).
- `substr(...,1,160)` counts characters in SQLite, matching `content.chars().take(160)`, and stops hauling full episode bodies out of the DB.
- The inner `JOIN entities` is provably equivalent to the current `WHERE EXISTS`: **verified that nothing deletes from `entities` or `edges`** (`DELETE FROM` in `store.rs` hits only `memories` / `memories_fts`).
- Leave `entities_for_memory` and `neighbor_memory_ids` untouched — `/entities`, `/neighbors` and `expand_graph_neighbors` still use them.

3. `brain_api.rs:872-881` and `:889-923` — remove `neighbor_ids` from `LinkedMemoryItem` and the mapping. No handler-signature or lock change.
4. `linkedGraphModel.ts` — drop `neighbor_ids` from `:11`, `:27`, `:59`.
5. `Linked.tsx:75-92` — extend the existing hydrate effect: alongside `getObservations([selected.id])`, call `getNeighbors(selected.id)`, store `neighborCount`, reset to `null` on selection change. Reuse the same `cancelled` guard; do not add a second effect.
6. `LinkedFloater.tsx:103` — take `neighborCount: number | null`, render `{neighborCount ?? '…'} neighbor memories`.
7. `linkedGraphModel.test.ts:22,31,43` — remove `neighbor_ids` from fixtures.

**Backward compatible:** `linkedGraphModel.ts:59` reads `m.neighbor_ids ?? []`, so a stale cached bundle against a new server degrades to "0 neighbor memories", not a crash.

### Tests (`store.rs` `mod tests` at :1192)

1. `list_linked_memories_groups_entities_per_memory` — catches the classic one-row-per-edge bug
2. `list_linked_memories_orders_by_timestamp_desc`
3. **`list_linked_memories_groups_across_timestamp_ties`** — fails if `m.id` is omitted from `ORDER BY`
4. `list_linked_memories_entities_sorted_by_normalized_name`
5. `list_linked_memories_snippet_truncates_at_160_chars`

Existing `link_memory_entities_and_neighbors` (:1700) and `neighbor_memory_ids_skips_superseded` (:1713) must stay green **unmodified** — that is the proof `/neighbors` is untouched.

### Verification

```bash
cd /Users/abundancia888/Documents/Code/brain/brain/rust
cargo test --lib store::tests && cargo build --release --bin brain_api
cd ui && npm run test && npm run build

# capture on the OLD binary first, then compare
curl -sS -o /dev/null -w 'http=%{http_code} bytes=%{size_download} time=%{time_total}\n' \
  http://127.0.0.1:8787/linked
curl -sS http://127.0.0.1:8787/linked | jq '{
  memories: (.memories|length), entities: (.entities|length),
  entity_refs: ([.memories[].entities|length]|add), keys: (.memories[0]|keys)}'
```

Before: `bytes=23506483 time≈1.047`. After: expect **4.0–4.6 MB** (>6 MB means `neighbor_ids` is still serialized somewhere) and ≥3× faster — **record the actual number, do not assert a threshold**. `entity_refs` must match the pre-change value exactly. Then load the Linked tab, select a memory, confirm a non-zero neighbor count.

### ⚠️ Build trap (verified, unrelated to this ship but it will bite here)

`ui/deploy.sh:15` claims "vite `emptyOutDir` is off so `eval_dashboard.json` survives", but `ui/vite.config.js:10` sets `emptyOutDir: true`. `npm run build` **wipes the git-tracked `brain/rust/static/eval_dashboard.json`**, which `rust-embed` compiles into the binary (`brain_api.rs:260-261`). Run `git checkout -- brain/rust/static/eval_dashboard.json` **before** `cargo build --release`. The UI must be built before the Rust binary or the server embeds the old bundle.

### Ship ordering

Zero file overlap with the entity-linking work — land it independently and first. It is **not** a merge blocker, but it **is** a blocker for running the backfill: validating success criterion 1 through a 35–50 MB / 2–3 s endpoint is validating through a degraded UI.

---

## A9 — Scope, gold set, deployment, docs

**Stage:** 0 (A9b) and 3 (A9a/c/d) · **Files:** `brain/eval/gold_semantic.jsonl`, `brain/tools/mcp_eval.py`, `AGENTS.md`, `docs/ENTITY_EDGE_GRAPH.md`, the base spec

### A9a — Scope reconciliation (D1)

`AGENTS.md:33` was already correct. Amend **the base spec** to match:

| Base spec line | Change |
|---|---|
| :9 (Problem) | add `conversation` to the durable list |
| :20 (Non-goals) | `Linking conversation or episode` → `Linking episode` |
| :33 (Decisions, Types) | seven types |
| :87 (Component 4) | "six durable types" → "seven durable types" |
| :113-114 (Testing) | "skips for conversation / episode" → "skips for episode"; "excludes conversation/episode" → "excludes episode" |

`episode` is correctly excluded everywhere — **0 rows exist in the DB** and it is an audit-body type.

### A9b — Gold set (D3) — Stage 0

Delete line 18 of `brain/eval/gold_semantic.jsonl` (`gold_memory_id: 7062fe23-9b7f-4492-9556-722365b1dbfe`, the SICOP procurement query). File → 17 rows. **Do not substitute a replacement id** — three facts match the query text closely enough that choosing one would be a guess about authorial intent. If coverage matters later, `7f92e475-83a0-488e-b067-8a755a77c78d` is the strongest candidate, to be confirmed by a human.

`gold_semantic_local.jsonl` (25 rows, 0 resolve) is **scoped to a different instance**, documented in `docs/CHANGELOG-SHARED-CODE-BRAIN.md:311`, and never loaded by default (`eval_suite.py:25` wires only `gold_semantic.jsonl`). **Leave it untouched.**

Add the detection command as a pre-flight before every eval run:

```bash
python3 - <<'EOF'
import json, sqlite3
cur = sqlite3.connect("brain/rust/brain.db").cursor()
for i, line in enumerate(open("brain/eval/gold_semantic.jsonl"), 1):
    d = json.loads(line)
    if not cur.execute("SELECT 1 FROM memories WHERE id=?", (d["gold_memory_id"],)).fetchone():
        print(f"line {i}: dangling {d['gold_memory_id']!r} query={d['query'][:60]!r}")
EOF
```

**Also fix `mcp_eval.run_mcp_eval`:** it counts a nonexistent target in `n_valid` and scores it as a guaranteed miss — the dangling row was silently costing ~5.6 pp of P@1 in every `eval_suite --mcp` run. Skip entries whose `gold_memory_id` is absent from the corpus.

### A9c — Deployment sync (required for Success Criterion 1) — Stage 3

**Verified mechanism.** The live hooks in `~/.claude/settings.json` run `/Users/abundancia888/Documents/AI/brain/hooks/*.py`, which do `sys.path.insert(0, Path(__file__).parent.parent.parent)` → `/Users/abundancia888/Documents/AI`. So `from brain.api_client import ...` resolves to **that tree's** `api_client.py`. By contrast `brain/mcp/run_server.sh` exports `PYTHONPATH=$REPO_ROOT` and `cd`s here, so **MCP saves use this repo**.

Consequence: after A3 edits this repo, auto-extraction fires for MCP-originated saves and **silently does not fire for hook-originated saves** — `PostToolUse` and `session_end`, where most golden-path saves happen. That is exactly what the base spec's Success Criterion 1 tests.

Edit target is always this repo (git-tracked, canonical).

> **Corrected during deployment.** The two-file `cp` originally prescribed here was **wrong — six files participate.** The real set was derived by AST-tracing the transitive `brain.*` import graph of every script in the live tree's `brain/hooks/`, not by inspection. Shipping only the original two would have left hooks paying ~2 s of torch per process (eager `ingest/__init__.py`), double-extracting on the fact path, and re-extracting on every spool retry.

| File | Why it must be in the live tree |
| --- | --- |
| `brain/api_client.py` | the `auto_entities` gate and `_maybe_extract_entities`; without it hooks never extract at all |
| `brain/ingest/entity_extractor.py` | the extractor itself — **did not exist** in the live tree before this ship |
| `brain/ingest/__init__.py` | PEP 562 lazy package init. Python runs a package `__init__` before any submodule, so the eager version costs **~2 s of torch per hook process** (measured 2.00 s vs 0.05 s) |
| `brain/ingest/fact_curator.py` | `auto_entities=False` on the fact path; without it every fact double-extracts |
| `brain/hooks/spool.py` | D5 replay fix; without it a spooled save re-extracts on each of up to 8 retries |
| `brain/core/memory.py` | accepts `auto_entities`; without it `BRAIN_BACKEND=python` raises `TypeError` |

**Deliberately NOT synced** (the tracer surfaced both; both were verified out of scope):

| File | Why not |
| --- | --- |
| `brain/config.py` | Its divergence is **pre-existing** — an `OBSIDIAN_VAULT` path refactor already in the working tree before this ship. Each tree's vault path is correct for itself. Syncing it would push an unrelated change onto the live hook path. |
| `brain/tools/mcp_eval.py` | Not on the hook import path (tracer false positive). A9b's change affects eval runs only. |

**Enforcement, not a checklist.** A manual `cp` list rots the moment someone edits one of these six. `brain/tests/test_deploy_parity.py` pins the set: it asserts byte-identity for each file, carries the *reason* each one matters in its failure message, and skips cleanly when the live tree is absent (CI, fresh clone, another machine). Override the location with `BRAIN_LIVE_HOOK_TREE`. Verified to catch drift by mutating a live copy and observing the failure.

```bash
.venv/bin/python -m pytest brain/tests/test_deploy_parity.py -v   # 8 tests
```

`docs/BUILD-AND-CUTOVER.md` covers `brain_api` and MCP only — the hooks were never part of that migration, which is why this gap existed.

**Deployment verified (2026-07-28), live hook tree:** `api_client` import 0.022 s and `entity_extractor` 0.040 s with **zero** heavy modules; a real `solution` save took **0.67 s** and auto-linked 5 entities (Success Criterion 1 **PASS**); `BRAIN_AUTO_ENTITIES=0` suppressed extraction; `episode` correctly skipped.

**Follow-up, not this ship:** repointing the hook commands in `~/.claude/settings.json` at this repo is the cleaner long-term fix, but it is a global settings change affecting every Claude Code session. Out of scope here.

### A9d — Documentation

`docs/ENTITY_EDGE_GRAPH.md`:
- Add an explicit **Scope** statement near the Status line (:7): durable-7 in, `episode` out. Currently only `AGENTS.md` states this.
- Update Evaluation (:201-220): mark the 0.0000-delta table **structurally uninformative** — n=14, and **0 of 18 gold targets were edge-linked**, so `graph_expand` could not reach a single target. The zeros are a structural artifact, not a measurement of the feature.
- **Delete or annotate line 220 outright.** It cites `brain/eval/runs/2026-07-22_phase-c-graph-expand.json` and `brain/eval/runs/2026-07-23_post-backfill-eval.json` as evidence. **Verified: `brain/eval/runs/` does not exist in this checkout — neither file is present.** The table is therefore unreproducible and unauditable. Do not silently leave a citation pointing at missing files; either delete the line or replace it with an explicit note that the artifacts were lost in the Documents/AI → Documents/Code migration and the numbers cannot be re-derived.
- Point the section at `graph_expand_ab.py` as the replacement, and state that the first reproducible A/B is the one A1 produces.
- `:76` / `:79` — per A2.

`AGENTS.md:33` — keep the scope clause; append that live + backfill extraction is no longer fact-only, and say **`conversation` is included** explicitly so the ambiguity does not recur.

### Out of scope — flagged, deliberately not bundled

- `brain/post_tool_use.py` has drifted from `brain/hooks/post_tool_use.py` (7 extra debug lines in the hooks copy). Neither is touched by this ship.
- `brain/backfill_facts.py` / `brain/tools/backfill_facts.py` are byte-identical duplicates. Untouched.
- `core/memory.py` defines `save_memory` twice (:15, :110).
- 11 orphan edges survive deleted memories (`delete_memories` never cleans `edges`), inflating entity counts in the Linked UI.

---

## 3. Cross-cutting rules for implementers

1. **Never write entities via direct SQLite.** All writes go through `POST /save`, `/save-batch`, or `/link-entities`. `brain_api` owns the DB.
2. **`extract_entities` never raises.** Every caller treats failure as `[]`, and a save never fails because of linking.
3. **Bare vs JSON-quoted types.** A5's `DURABLE_MEMORY_TYPES` holds bare strings for `memory_type` comparison. SQL needs `'"fact"'`. Never mix them.
4. **`api_client.py` stays stdlib-only at import time** (D6). Test 8 in A3 pins this.
5. **No live Ollama in any test.** Mock at the `extract_entities` or `_call_llm` boundary.
6. **The DB is live.** Counts drift between runs. Any A/B must interleave arms in one process.
7. **Record measured numbers, do not assert thresholds** in verification steps — except where A1 defines an explicit gate.

---

## 4. Open items

| Item | Owner | Blocking? |
|---|---|---|
| Confirm `7f92e475…` as the intended gold row 18 target | human | no — file works at 17 rows |
| Model-weight drift behind `OLLAMA_SUMMARIZE_MODEL` (A6 risk 3) | pre-flight dry-run | no — mitigated |
| Ollama query-generation yield vs the 0.45 overlap filter (A1) | `--oversample` knob | no |
| Repoint `~/.claude/settings.json` hooks at this repo | follow-up ship | no — A9c covers it |
| Stoplist tuning for durable content (~15% noise) | follow-up, alongside A1 | no |
| Displacement guard (A2.4 pre-registered) | next ship, gated on A1 | no |
| Add explicit `graph_expand=False` to `eval_suite.py:185` — **only if** A1's gate passes and the default flips | follow-up on flip | no — see A1 |
| `brain/eval/runs/` artifacts cited in `ENTITY_EDGE_GRAPH.md:220` are missing and unrecoverable | A9d deletes/annotates the citation | no |
