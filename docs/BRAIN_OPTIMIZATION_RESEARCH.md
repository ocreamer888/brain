# BRAIN Optimization Research

> **Status:** Active research log. Strategy Layer shipped (2026-05-27). Vision Layer 3 operational.
> **Last updated:** 2026-05-27 (Strategy Layer: proactive context via UserPromptSubmit. Phase 10 + 23-gap audit complete. Corpus: ~17,400.)
> **Evolution:** See [[Brain Neural Architecture Vision|vision_brain_neural_architecture.md]] for Phases 9+ strategic roadmap

---

# Phase 8 — Salience Ranking, Active Learning & Quality Recovery (2026-05-25)

## Summary

Three improvements shipped that actually move the needle on retrieval accuracy, plus a corpus quality campaign that recovered P@1 from a composition-driven regression.

## 1. Salience Weighting in Ranking (brain.rs)

**Problem:** The `salience` field was stored since Phase 6 but excluded from scoring (beta=0.0 decision on 2026-05-02) because the extractor assigned *higher* salience to facts that curators later ignored.

**Resolution:** The Phase 6 decision was based on **extractor-assigned salience** (noisy). Phase 8 treats salience as a **feedback-updated signal** — it starts at 0.5 (neutral) and drifts only when users explicitly accept/reject memories. This makes it signal-driven rather than noise-driven.

**Implementation** (`brain/rust/src/brain.rs`):
```rust
// Around line 307, replaces: let final_score = recency_w * hybrid_score;
let sal = memory.metadata.salience as f32;
let salience_w = (1.0 + 0.3 * (sal - 0.5)).clamp(0.85, 1.15);
let final_score = salience_w * recency_w * hybrid_score;
```

Formula behavior:
| salience | salience_w | effect |
|----------|------------|--------|
| 0.0 | 0.85 | −15% (suppress) |
| 0.5 | 1.00 | neutral (default) |
| 1.0 | 1.15 | +15% (boost) |

**Note:** kfold eval bypasses the Rust API (uses in-memory Python), so salience effects are not captured in eval numbers. Effect is measurable only via live search.

## 2. Active Learning — Passive Uncertainty Sampling (`brain/mcp/server.py`)

**Problem:** Zero explicit feedback events existed to train/update salience. Users don't naturally call `record_feedback`.

**Solution (Option A — passive flag):** When the top-2 search results are within 0.05 cosine distance, `search_brain` appends a warning prompting the user to provide feedback:

```
⚠ Uncertain retrieval: top 2 results are within 0.031 distance.
If you know which is more relevant, call record_feedback with
memory_id='...' event_type='accepted' or memory_id='...' event_type='rejected'.
```

**Constant:** `_UNCERTAINTY_GAP = 0.05`

## 3. Auto-Salience Update from Feedback (`brain/mcp/server.py` + `brain/api_client.py`)

When `record_feedback` is called with `event_type='accepted'` or `'rejected'`, salience is automatically updated:

| event | delta | clamp |
|-------|-------|-------|
| accepted | +0.05 | [0.1, 1.0] |
| rejected | −0.10 | [0.1, 1.0] |

**New API function** (`brain/api_client.py`):
```python
def update_salience(memory_id: str, salience: float) -> bool:
    """PATCH /memories/:id — update salience score (0.0–1.0)."""
    salience = max(0.1, min(1.0, salience))
    result = _request("PATCH", f"/memories/{memory_id}", {"salience": salience})
    return result.get("updated", False)
```

## 4. Data Quality Campaign — Re-ingest + LLM Retitling

### 4a. Re-ingest with Source-Adaptive Chunking

Projects with legacy bracket-prefixed PDF chunks (`[DOC_NAME] body`) were re-ingested using `brain/tools/reingest_ocreamer_docs.py`:

| Project | Before | After | ΔP@1 |
|---------|--------|-------|------|
| ocreamer | 0.852 | 0.903 | +0.051 |
| owelign | 0.927 | 0.952 | +0.025 |
| sicop | 0.948 | 0.959 | +0.011 |

FTS5 sync issue: 437 stale FTS5 rows were left after a direct SQLite delete. Fixed with:
```sql
DELETE FROM memories_fts WHERE id NOT IN (SELECT id FROM memories);
```

### 4b. Heuristic Retitling (`brain/tools/retitle_chunks.py`)

New tool for two patterns:
- **ppf-contact-solver conversations:** heuristic extraction (markdown headers, bold phrases, prose sentences) — 681 chunks retitled
- **farmaplus session stubs:** aligned titles to "N-msg session — farmaplus (date)" format — 196 sessions retitled

Result: negligible impact on kfold (+0.001). Root cause — heuristic titles don't close the title-body embedding gap.

### 4c. LLM Retitling (`brain/tools/retitle_ppf_llm.py`)

1330 ppf-contact-solver memories (857 conversation + 473 solution) retitled using `meta-llama/llama-3.1-8b-instruct` via OpenRouter.

**Key finding on solution type:** 473 solution memories had 122 duplicate titles (`PPF Contact Solver API: __init__` appeared 18×). kfold leave-one-out fails on identical queries → P@1 collapsed. Unique LLM titles fixed it.

| Scope | Before | After | Δ |
|-------|--------|-------|---|
| ppf-contact-solver P@1 | 0.379 | 0.833 | +0.454 |
| solution type P@1 | 0.689 | 0.923 | +0.234 |
| conversation type P@1 | 0.130 | 0.196 | +0.066 |
| overall P@1 | 0.764 | 0.779 | +0.015 |

**Script details:**
- Model: `meta-llama/llama-3.1-8b-instruct` (non-thinking, reliable instruction following)
- Checkpoint: `brain/eval/retitle_ppf_checkpoint.json` (resume-safe)
- Prompt: generate ≤12-word semantic title from content chunk
- Rate: 0.4s between calls, 3-retry on 429

## Eval Trajectory (2026-05-25)

All evals: `python3 brain/tools/retrieval_eval_kfold.py --full --rrf`

| Checkpoint | P@1 | MRR | n |
|---|---|---|---|
| May 22 baseline | 0.8389 | 0.8614 | 18,852 |
| Post re-ingest + salience (pre-retitle) | 0.7639 | 0.7941 | 20,832 |
| Post heuristic retitle | 0.7623 | 0.7923 | 20,883 |
| Post LLM retitle (conv) | 0.7775 | 0.8040 | 20,905 |
| Post LLM retitle (conv + sol) | **0.7794** | **0.8040** | **21,231** |

**Gap to baseline explained:** The 0.06 delta is composition — 2,379 new memories added this session from projects absent in the May 22 baseline (farmaplus at P@1=0.008, lifehub regression, .claude/AI new memories). No existing project regressed.

## 5. Complete Framework Eval (2026-05-26)

### Eval modes

| Mode | Command | What it tests | Requires API |
|------|---------|---------------|-------------|
| Quick gate | `--quick` | P@1 by type, 300 sample | No |
| Kfold | `--kfold` | Leave-one-out full corpus | No |
| Gold vault | `--vault` | Vault file recall by file_path | Yes |
| MCP path | `--mcp` | 14 gold queries, full pipeline | Yes |
| All | `--all --quiet` | All 4 + JSON report | Yes |

Run: `python3 brain/tools/eval_suite.py --all --quiet`
Reports: `brain/eval/runs/YYYY-MM-DD-HHMM.json`

### Phase 8 final baselines (2026-05-26)

| Mode | Metric | Value |
|------|--------|-------|
| Quick gate | solution P@1 | 0.987 |
| Quick gate | project_context P@1 | 1.000 |
| Kfold | overall P@1 | 0.767 |
| Kfold | MRR | 0.795 |
| Gold vault | recall@10 | 1.000 |
| Gold vault | MRR | 0.500 |
| MCP path | P@1 | 0.429 |
| MCP path | MRR | 0.521 |

### kfold vs MCP gap (−0.338)

Expected and structural. kfold uses the exact title as query (best-case alignment); MCP uses natural language queries through the full Rust pipeline. If the gap exceeds 0.40 it likely signals a retrieval regression.

### Gold vault fix

`gold.jsonl` had 1 query: "MedDeFi medical tourism market analysis" targeting `vault/01 Projects/MedDeFi/docs/Medical_Tourism_Market_Analysis_July_2025.md`. File was never ingested → recall@10=0.0.

Fixed by ingesting directly via `save_memory_batch` with `chunk_by_sections` + `file_path` tag. Result: recall@10=1.0, rank=2.

### Key eval lessons

- **Duplicate titles collapse kfold P@1** — leave-one-out fails when N memories share the same title. Always check title uniqueness. Fixed with LLM retitling.
- **Heuristic retitling ≈ neutral** — first-line extraction doesn't close the title-body embedding gap. LLM summaries do (+0.234 on solution type).
- **Gold vault requires file in DB** — obvious, but gold queries must reference ingested content. Maintain `gold.jsonl` whenever new vault files are added.
- **OpenRouter model selection** — Qwen3-14b uses thinking mode by default (content=null). Use `meta-llama/llama-3.1-8b-instruct` for fast non-thinking tasks.

## Algorithm Knowledge Base (companion work)

32 algorithms documented across 7 domains. See `ALGORITHMS/` and `docs/ALGORITHM_KNOWLEDGE_BASE.md`.

---

# Phases 9+ — Neural Network Architecture Evolution (2026-05-21)

**Vision shift:** Brain is evolving from a retrieval system (Phases 1–7) to an autonomous neural network. Current gap: brain *has data* but lacks awareness of when/how to use it.

**Strategic vision doc:** [[Brain Neural Architecture Vision|vision_brain_neural_architecture.md]]

**Key architectural layers to implement (priority order):**

1. **Strategy Layer** — Context-aware query-trigger matrix (proactive retrieval)
   - Feedback doc: [[Strategy Layer: Proactive Retrieval|feedback_strategy_layer_proactive_retrieval.md]]
   - Current gap: Brain only retrieves on explicit search; should auto-trigger based on query type
   
2. **Connection Layer** — Entity relationships & semantic graph
   - Feedback doc: [[Connection Layer: Entity Relationships|feedback_connection_layer_entity_relationships.md]]
   - Current gap: Memories in silos; need entity-relationship graph to connect data across domains
   
3. **Pattern Recognition Layer** — Temporal analysis & cycle detection
   - Feedback doc: [[Pattern Recognition: Temporal Analysis|feedback_pattern_recognition_temporal_analysis.md]]
   - Current gap: No time-series analysis; need to detect trajectories, cycles, recurring behaviors

**Foundation already laid:** Phases 1–7 ship fact-extraction, semantic deduplication, temporal metadata (`event_time`), and retrieval eval. These are prerequisites for building awareness/autonomy layers.

---

## Brain Viewer React Rewrite (2026-05-25) — Shipped

**Status:** Complete. React 18 + Tailwind v3 + Vite SPA replaces the old vanilla JS viewer. All four views live and verified against the running DB (19,960 memories).

### What shipped

**1. `/stats` by-type breakdown (backend)**
New `by_type: HashMap<String, usize>` field added to `BrainStats`. The Rust store queries `SELECT type, COUNT(*) FROM memories GROUP BY type` and strips the JSON-serialized quotes (`trim_matches('"')`). Every `/stats` response now includes per-type counts, enabling the Dashboard stat cards and Sidebar breakdown.

**2. React SPA — four views**

| View | What it does |
|------|-------------|
| **Dashboard** | Stat cards by type, latest eval run pass/fail badge + P@1 metrics, live SSE memory feed (200-item ring buffer with reconnect indicator) |
| **Search** | Debounced semantic search (`/v1/search_index`), type-filter chips, expandable cards (observations cached per session), Timeline drawer portal with Escape-key close |
| **Curate** | Facts list (search_index filtered to `memory_type=fact`), Promote → PATCH `/memories/:id` salience=1.0, Reject → POST `/feedback`, acted state persists in-session |
| **Eval** | Latest run summary (pass badge, non-fact P@1, MCP P@1, gap), full run history table with tabular-nums alignment, empty state with run command |

Keep-alive mount strategy: views mount on first visit and stay mounted (hidden via `class="hidden"`), preserving scroll position and search state across tab switches.

**3. Auth fix — API key injection**
The old viewer (and the new one before this fix) sent no API key. With `BRAIN_API_KEY` set, every request got `{"error":"missing or invalid API key"}`.

Fix — two layers:
- **Production:** `static_handler` in `brain_api.rs` now injects `<script>window.__BRAIN_API_KEY__="...";</script>` into `index.html` at serve time. The Rust server knows the key; the browser JS reads it from `window`.
- **Dev (Vite):** `apiFetch.js` falls back to `import.meta.env.VITE_BRAIN_API_KEY`, sourced from `brain/rust/ui/.env.local` (gitignored). No key in source, no manual header wiring.
- **SSE (EventSource):** Browser EventSource can't send custom headers. `stream_handler` now accepts `?key=` query param and inserts it into the HeaderMap before calling `authorize_and_rate_limit`. `sseUrl()` helper appends it automatically.

**4. Eval run — 2026-05-25-0734**

| Metric | Value |
|--------|-------|
| Pass | ✅ |
| non-fact P@1 | 87.1% |
| MCP P@1 | 42.9% |
| MCP gap | −57.1pp |

The −57pp MCP gap is the open retrieval problem from the 2026-05-23 work. Direct DB cosine works well (87%); the API search path Claude actually uses still lags significantly.

### File map

```
brain/rust/src/types.rs          ← BrainStats.by_type added
brain/rust/src/store.rs          ← count_memories_by_type()
brain/rust/src/brain.rs          ← get_stats() populates by_type
brain/rust/src/bin/brain_api.rs  ← stats handler, static_handler injection, stream_handler ?key=
brain/rust/ui/                   ← full React SPA (Vite + Tailwind)
  src/lib/apiFetch.js            ← auth wrapper + sseUrl helper
  src/context/StatsContext.jsx   ← polls /stats every 10s
  src/context/EvalContext.jsx    ← stable refresh() on Eval tab activate
  src/components/Sidebar.jsx     ← nav + memory count + by_type breakdown
  src/components/MemoryCard.jsx  ← compact / expanded / actionable variants
  src/components/TimelineDrawer.jsx ← portal drawer, Escape key
  src/views/Dashboard.jsx
  src/views/Search.jsx
  src/views/Curate.jsx
  src/views/Eval.jsx
brain/rust/static/               ← Vite build output (rust-embed source)
```

### Build workflow

```bash
# Dev (hot reload — proxies API to localhost:8787)
cd brain/rust/ui && npm run dev

# Production
cd brain/rust/ui && npm run build      # outputs to brain/rust/static/
cd brain/rust && cargo build --release # re-embeds static files
pkill -f brain_api && ./target/release/brain_api &
```

---

## Eval Framework + Fact-Flood Investigation (2026-05-23) — In Progress

**Status:** First round of improvements shipped. Core retrieval problem diagnosed but not fully resolved. Further work needed.

### What shipped today

**1. Unified eval suite** (`brain/tools/eval_suite.py`)
One command runs all 4 eval modes and writes results to the brain viewer dashboard:
- `--quick` — direct DB cosine P@1 per type (~10s)
- `--kfold` — leave-one-out across full corpus (~3 min)
- `--mcp` — P@1/MRR via the actual API search path Claude uses (~1 min)
- `--all` — all four

Auto-runs after each session when `BRAIN_EVAL_AUTO=1` is set in `~/.zshrc`.

**2. MCP gap measurement**
The eval now measures the gap between DB retrieval quality (kfold) and what Claude *actually gets* through the API. This was previously invisible — kfold could look healthy while Claude received bad answers.

**3. Eval tab in brain viewer**
Results visible at `http://127.0.0.1:8787` → Eval tab. Trend table shows every run, newest first. Updates live after each eval run.

**4. Type-diversity reranking** (`brain/rust/src/brain.rs`)
Facts are 76% of the DB (14,758 memories, all from May 2026 backfill). Without intervention, they flood every unfiltered search result. Two changes shipped:
- **Diversity cap:** any single `MemoryType` limited to `ceil(n × 0.40)` slots in top-k results
- **Wider candidate pool:** cosine over-fetch increased from `n×10` to `n×30` when no type filter is active, so buried non-fact memories can enter the candidate set

**5. Rebuilt gold_semantic.jsonl**
The eval gold set was written before the fact ingestion and tested solution retrieval in a world where facts didn't exist. 10 of 19 pairs were broken:
- 9 pairs had gold memories at raw cosine ranks >100 (unretrievable by any strategy)
- 1 gold memory was missing from the DB entirely

Rebuilt with 14 valid pairs: 10 retained/improved originals + 4 new fact-type pairs (first time facts are represented in gold, reflecting the actual DB composition).

### Retrieval numbers before/after

| Metric | Before | After | Notes |
|--------|--------|-------|-------|
| MCP P@1 | 0.105 | **0.429** | +32.4pp |
| MCP MRR | 0.167 | **0.572** | +40.5pp |
| MCP gap | −0.895 | **−0.571** | gap vs DB baseline |
| Facts in top-10 | ~9/10 | ≤4/10 | diversity cap enforced |
| quick_gate conversation P@1 | 0.390 | 0.387 | unchanged — separate problem |

### Root cause of the fact flood (diagnosed, not fully fixed)

The investigation revealed three layered problems:

**1. Type imbalance (structural)**
14,758 facts (76.3% of all memories) were bulk-ingested in May 2026. Facts are short, atomic, and densely topical — their embeddings cluster tightly around specific concepts and consistently beat long narrative solutions in cosine similarity. This is not a bug in the search pipeline — it reflects a genuine semantic property of short vs long text.

**2. Granularity asymmetry (embedding-level)**
Short queries match short atomic facts better than long solution narratives. A query like "why do fonts disappear in a route group?" produces an embedding closer to "If fonts or custom classes are not working, check that their styles are defined in globals.css" (1 sentence) than to the full solution story (multiple paragraphs). This is inherent to the embedding model and corpus composition.

**3. Gold set obsolescence (eval artifact)**
The original gold set was designed in a pre-fact world and measured solution recall specifically. Once 14k facts covering the same topics were added, those queries naturally hit facts first. The eval was reporting low MCP P@1 partly because the gold answers were no longer the best retrieval targets for those queries — not because retrieval was broken.

### What the API pipeline does NOT cause

Confirmed via controlled experiment: P@1 was identical (0.105) with raw cosine only vs full API pipeline (mean-centering + recency decay + BM25 + reranking). The API layers add zero degradation. The problem is at the embedding-level corpus composition.

**Recency decay** is negligible within a 2-month window: half-life is 730 days, so the weight difference between a 20-day-old fact (w=0.997) and a 50-day-old solution (w=0.993) is 0.4% — irrelevant.

### What still needs work

The **−0.571 MCP gap** means solutions/conversations still lose to facts for about half the queries. Remaining avenues:

1. **Smarter diversity cap** — current 40% cap is static. A query about a specific technical problem might benefit from allowing more facts (they contain the actual answer) while a query about "how did we solve X" should weight solutions higher. Query-intent classification could drive dynamic cap values.

2. **Fact quality scoring** — not all 14,758 facts are equally useful. Facts tagged `fact_type:named_entity` (5,281 of them) are low-information entity extractions. A salience filter or type-within-type ranking could reduce their retrieval dominance.

3. **Solution/conversation recall** — conversation P@1 is stuck at ~0.39 in k-fold (down 33pp from May 2 baseline). This is a separate problem from the fact flood — conversation embeddings overlap heavily because sessions cover similar topics. Title quality and embedding strategy for long conversations needs investigation.

4. **Gold set expansion** — 14 pairs is a thin eval signal. Adding 20–30 more pairs across types, projects, and time ranges would make the MCP P@1 metric more reliable and harder to game by chance.

---

## Ingest Quality Fix (2026-05-22) — Completed

**Problem:** Non-fact retrieval dropped from P@1=0.797 (May 2) to 0.462 (May 21). Root cause: not retrieval degradation — ingest bugs created ~3,400 noise memories that diluted the corpus.

**Root causes fixed:**
1. `ingest_claude_code_lib.py` — conversation titles were `"Claude Code — <uuid>"` → k-fold P@1=0.061. Fixed to `"Session YYYY-MM-DD — project"`.
2. `post_tool_use.py` — every bash command saved as `pattern`, every file edit as `solution`, all with identical generic titles. Removed Bash/Edit from MEMORABLE_TOOLS.

**Backfill applied to brain.db:**
- 1,671 conversation titles fixed
- 621 bash-log pattern memories deleted
- 235 file-edit/write-hook solution memories deleted

**Result:** Overall k-fold P@1: 0.831 → 0.846. Pattern P@1 recovered to 1.000 (noise deleted). Gold-semantic P@1 unchanged at 1.000 (embeddings untouched).

**Prevention:** `brain/tools/ingest_quality_gate.py` — run after any large ingest. See `brain/eval/README.md` for full eval history.

---

# Reference

High-Accuracy Agent Memory Systems and Lessons for BRAIN
docs/High-Accuracy-Agent-Memory-Systems-and-Lessons-for-BRAIN.md

-----

## T5 + T2 Results (2026-04-30)

### Corpus & eval scope (not LOCOMO)

**Measured on:** Your own SQLite corpus (`brain/rust/brain.db`), leave-one-out retrieval via `brain/tools/retrieval_eval_kfold.py` — **not** LOCOMO, LongMemEval, or other published long-context benchmarks.

**Documented jump (eval pipeline, ~2.4k rows):** Dense-only cosine → hybrid with BM25 fusion in that script (**`--rrf`**, RRF k=60 over cosine ranks + FTS5 BM25 ranks): **P@1 0.640 → 0.799** (full-corpus run, 2026-04-30). Largest gains on **`solution`** and **`general`** slices; `project_context` moved less until ingest quality improved.

**Ocreamer:** Stuck near **~0.50** P@1 on bad ingest (raw PDF chunks, empty titles) until chunks/titles were fixed — **ingest problem, not retrieval** as the primary ceiling for that project.

**Production note:** `brain_api` ships **alpha-weighted** hybrid (cosine magnitude + normalized BM25 rank), recency, mean-centering, and FTS5 — related to this eval but **not** identical to script-only RRF. Use the table below as “dense vs eval-pipeline fusion” on the same k-fold design; tune production α with real query logs, not title-as-query sweeps alone.

### Baselines (full corpus, n=2,381)
| Metric | Cosine-only | RRF hybrid | Delta |
|--------|------------|-----------|-------|
| P@1    | 0.640      | **0.799** | +0.158 |
| P@3    | 0.713      | **0.888** | +0.175 |
| P@5    | 0.746      | **0.910** | +0.165 |
| P@10   | 0.790      | **0.934** | +0.144 |
| MRR    | 0.694      | **0.850** | +0.156 |

### Key slice gains (RRF vs cosine)
| Slice | Cosine P@1 | RRF P@1 | Delta |
|-------|-----------|---------|-------|
| solution (n=1,218) | 0.629 | **0.876** | +0.247 |
| general project (n=939) | 0.540 | **0.860** | +0.320 |
| project_context (n=786) | 0.562 | **0.662** | +0.100 |
| ocreamer (n=206) | 0.228 | **0.500** | +0.272 |
| sicop (n=114) | 0.430 | **0.500** | +0.070 |

### Data fixes applied
- `meddefi` (31 rows) → `MedDeFi` casing fix. Combined project now P@1=0.729.

### Ocreamer diagnosis
- 206 memories, 100% `project_context` type. 192/206 are raw PDF chunks (Costa Rica AI Strategy × 123, ESPECIFICACIONES TECNICAS × 46, INVU tender × 23). No titles. Adjacent-page embeddings overlap heavily.
- **Root cause: ingest problem, not retrieval.** RRF brought P@1 from 0.228 → 0.500 on keyword terms but ceiling is ~0.5 until chunks are re-ingested with meaningful summaries/titles.

### What's implemented
- `brain/tools/retrieval_eval_kfold.py` — added `--rrf` flag (BM25+cosine RRF k=60, in-memory FTS5) ✅
- `brain/eval/kfold_report_rrf_full.json` — RRF full-corpus baseline saved ✅
- `brain/eval/kfold_report_baseline_post_casing.json` — cosine baseline after casing fix ✅
- Hybrid alpha-weighted BM25+cosine search wired into production `brain_api` ✅ (T5 next-priority 1)
- Fact layer eval harness: `--facts-only` flag + `facts_queries.jsonl` + rollback gate ✅
- Fact layer P@1 baseline (2026-05-02): BM25-only alpha=0.00 → **P@1 1.000**, hybrid → **P@1 0.600**

### Next priorities
1. ~~Wire RRF into production search path~~ ✅ Done (hybrid alpha-weighted in `brain_api`)
2. Re-ingest ocreamer doc chunks with per-chunk summaries/titles — still relevant (P@1=0.500 ceiling on ocreamer slice)
3. ~~T1 mean-centering~~ — superseded by fact-layer; revisit if hybrid P@1 plateaus

---

## Phases 1–7 — Mem0-Grade Fact Layer (2026-05-02/03)

**Shipped:** All 7 phases complete. Brain upgraded from a flat memory store to a dual-layer Mem0-grade system.

### What was built

| Phase | Key change | Files |
|---|---|---|
| 1 — Schema | `Fact`/`Episode` MemoryType variants; `parent_id`, `event_time`, `salience`, `superseded_by`, `derived_from` on MemoryMetadata; store methods: `fts_search_facts`, `get_facts_by_parent`, `mark_superseded`, curation/backfill log tables | `types.rs`, `store.rs`, `brain.rs`, `brain_api.rs`, `migrate.rs` |
| 2 — Extractor + Curator | LLM fact extraction (Sonnet, non-reasoning), intra-batch cosine dedup; 3-tier sim gate (auto-ADD <0.78, LLM tiebreaker 0.78–0.92, auto-IGNORE >0.92); eval `--facts-only` + rollback gate | `fact_extractor.py`, `fact_curator.py`, `retrieval_eval_kfold.py` |
| 3 — Ingest wiring + Batch 1 | Checkpoint-resumable backfill across 4 sources; Batch 1: 124 sessions → 701 facts | `backfill_facts.py`, `session_end.py`, `ingest_session_chunks.py` |
| 4 — Retrieval update | `SearchFilter.exclude_superseded` (default true); `parent_id` in `SearchIndexRow`; `/get-episode` endpoint; `get_episode` MCP tool | `types.rs`, `brain.rs`, `brain_api.rs`, `api_client.py`, `server.py` |
| 5 — Full backfill | 12,328 added · 1,566 merged · 14,062 total ops; Cursor alone 70%; 18,174 total memories | `backfill_facts.py` (all 4 source modes) |
| 6 — Salience calibration | beta=0.0 (IGNORE avg_sal=0.792 > ADD avg_sal=0.754 — no signal); P@1 baseline BM25=1.000/hybrid=0.600; Facts tab in web viewer; `PATCH /memories/:id` | `store.rs`, `brain_api.rs`, `app.js`, `index.html`, `PHASE6_SALIENCE.md` |
| 7 — Temporal decay | `stamp_event_times.py` backfilled 14,771 facts; recency decay uses `event_time.unwrap_or(timestamp)`; forward path in curator + backfill | `brain.rs`, `fact_curator.py`, `backfill_facts.py`, `stamp_event_times.py` |

### Corpus state post-Phase 7

| Metric | Value |
|---|---|
| Total memories | 18,174 |
| Active facts (`superseded_by IS NULL`) | 13,224 |
| Curator decisions logged | 15,644 (ADD 13,377 · MERGE 1,597 · UPDATE 173 · IGNORE 497) |
| Facts with `event_time` | 14,771 / 14,771 (100%) |
| Fact type distribution | named_entity 36% · decision 36% · error_fix 17% · outcome 8% · preference 2% |
| Fact P@1 (BM25-only) | **1.000** |
| Fact P@1 (hybrid) | **0.600** |

### Techniques from this research doc that Phases 1–7 implement

| Research technique | Phase that ships it |
|---|---|
| Semantic deduplication (ML-Bio T3, awesome-ml T18) | Phase 2 — 3-tier cosine gate in curator |
| Fire-and-forget async ingest + checkpoint resumability (SocratiCode T25) | Phase 3 — `backfill_facts.py` with per-source checkpoints |
| Recency-weighted scoring using event time (SocratiCode T14) | Phase 7 — `event_time.unwrap_or(timestamp)` in age calc |
| Retrieval diversity: exclude stale results (RRF / curator) | Phase 4 — `exclude_superseded` default true |
| k-fold retrieval eval + precision@k measurement (OpenBMI T5) | Phase 6 — `--facts-only` flag + `facts_queries.jsonl` |
| Multi-factor importance score (GitNexus) | Phase 6 — `salience` stored; beta=0.0 (no signal confirmed) |

### What remains from this doc's priority list (next targets)

1. **Ocreamer re-ingest** — still at P@1=0.500; root cause is raw PDF chunks with no titles (research doc section: Ocreamer diagnosis)
2. **Memory relationships table** (GitNexus T10 / ML-Bio T2) — NER-based entity extraction; `entities` field already present on facts
3. **Composite multi-signal retrieval score** (DL-SOCRATIS T40) — once retrieval log has enough feedback events to tune weights
4. **Co-access link strengthening** (neurolinked finding) — auto-create `memory_links` from co-retrieval patterns
5. **Type diversity cap in results** (gbrain finding) — prevent named_entity dominance (currently 36% of facts)

---

## Honest Assessment of This Research

This document covers 4 repos and 23 techniques. Not all are equal. Before diving in:

**Most valuable — actually implement these:**
- **RRF hybrid search** (GitNexus T6) — BRAIN's single biggest retrieval gap. Searching for an error message or function name by embedding alone is broken. BM25 + cosine with RRF fixes it. SQLite FTS5 is already in rusqlite. Zero new deps.
- **Retrieval analytics log** (RTK T17) — BRAIN has zero measurement today. Can't know if any optimization helps without this. Should've existed from day one.
- **Mean-centering** (OpenBMI T2) — 2 lines of Python, measurable gain, no risk.
- **Session JSONL mining** (RTK T19) — 1654 stored sessions is untapped signal. Finding which memories get corrected or ignored is free ground truth already owned.
- **Memory relationships table** (GitNexus T10) — BRAIN's flat structure is its real architectural ceiling. This unlocks the next level.

**Weaker findings — lower priority or over-engineered:**
- **awesome-machine-learning source** — a library catalog, not deep analysis. "Use Annoy" or "use PyOD" is a shopping list, not a solution.
- **RLDA projection** (OpenBMI T1) — requires eval framework first, offline training, projection matrix maintenance. Don't touch until T5 (k-fold eval) is working.
- **PostToolUse hook for command output compression** (RTK T14) — you can just return less in the MCP tools directly. No hook needed.
- **4-level permission verdict** (RTK T18) — over-engineered for a personal memory tool.
- **Leiden community detection** (GitNexus T9) — useful at 100K+ memories. Premature at 7K.

**The real gap in this research:**
It identifies *potential* improvements but never starts with "what is BRAIN actually failing at right now?" Slow queries? Wrong results? Coverage gaps? Duplicates? That answer changes which 3 techniques to do first vs. which 15 to file and forget.

**Bottom line:** ~7 of the 23 techniques are worth implementing now. GitNexus was the most useful source by a wide margin.

---

## ML Biotechnology Audit (2026-05-01)

**Source:** PacktPublishing/Machine-Learning-in-Biotechnology-and-Life-Sciences — Packt textbook, 12 chapters, Jupyter notebooks. Covers NLP, clustering, LSTM time series, transformers, Flask deployment.

**Honest assessment:** This is a standard ML textbook, not a specialized memory system. Prior repos (GitNexus, MemPalace, neurolinked) were far more directly applicable. Net new value is 2-3 medium-priority techniques — all standard, well-documented. Nothing here changes the current priority list. Best used as implementation reference once a technique is already decided.

---

### ML-Bio T1 — Retrieval-Optimized Embedding Model

**Source:** `chapters/chapter9/transformers_tutorial/chapter9-transformers-scientific-search-engine.ipynb`

The scientific search engine notebook uses `SentenceTransformer('msmarco-distilbert-base-v4')` — a model trained on MS MARCO passage ranking. The MS MARCO dataset is built from real search queries and relevance judgments, making this model trained *specifically* for retrieval, not just semantic similarity.

**BRAIN application:**

BRAIN's current embedding model is unknown from the code alone. If it's a generic sentence-transformer (e.g. `all-MiniLM-L6-v2`), switching to a retrieval-optimized model could improve recall directly — no pipeline changes needed, just a different model ID.

Retrieval-optimized alternatives in order of quality/size:
- `msmarco-distilbert-base-v4` — small, fast, retrieval-tuned
- `BAAI/bge-large-en-v1.5` — state-of-art retrieval, larger
- `intfloat/e5-large-v2` — instruction-tuned, strong on asymmetric queries

**Expected gain:** Better semantic matching when query and memory text use different vocabulary for the same concept (e.g. "docker crash" vs "container OOM error").

**Implementation complexity:** Low — one config line change in `brain/config.py` or equivalent. Requires re-embedding all 2,484 memories (one-time offline job, ~5 minutes).

**Priority:** Medium. Verify what model BRAIN currently uses first. If already retrieval-optimized, skip.

---

### ML-Bio T2 — NER Entity Extraction → Memory Relationships Table

**Source:** `chapters/chapter9/chapter9-NLTK&Spacy.ipynb`

Spacy's NER pipeline identifies and classifies entities from text: persons, organizations, dates, tools, locations. The notebook uses it on biotech articles to extract drug names, researchers, and dates. Same pipeline applies directly to memory text.

**BRAIN application:**

The memory relationships table (GitNexus T10) is already flagged as BRAIN's architectural ceiling — but T10 didn't specify *how* to populate it. NER is the answer.

**Proposed ingest pipeline addition:**
```python
import spacy
nlp = spacy.load("en_core_web_sm")

def extract_entities(text):
    doc = nlp(text)
    return [(ent.text, ent.label_) for ent in doc.ents]

# At save_memory time:
entities = extract_entities(memory_text)
# INSERT INTO memory_entities (memory_id, entity_text, entity_type) VALUES ...
```

Entity types useful for BRAIN: `PERSON` (collaborators), `ORG` (tools/services like GitHub, AWS), `DATE` (when things happened), `PRODUCT` (frameworks, libs), `GPE` (deployment targets).

This populates the relationships table automatically at ingest — no manual tagging. Enables queries like "all memories mentioning Redis" or "what changed after April 2026."

**Implementation complexity:** Low. Spacy is one pip install. The extraction runs synchronously at save time. Schema addition: one table with (memory_id, entity_text, entity_type, confidence).

**Priority:** Medium-High. Directly unblocks T10, which is already on the priority list. Low effort, high structural value.

---

### ML-Bio T3 — MiniBatchKMeans for Semantic Deduplication

**Source:** `chapters/chapter9/Chapter9-TextClustering.ipynb`

The notebook clusters 2,263 PubMed abstracts using TF-IDF + MiniBatchKMeans (4 clusters, batch_size=100, init='k-means++'). PCA reduces to 2D for visualization. This is the same problem as clustering BRAIN's 2,484 memories.

**BRAIN application:**

BRAIN has upsert-based exact deduplication but zero *semantic* deduplication. Two memories that say the same thing differently both get stored. Over 2,484 memories this compounds.

**Proposed offline job:**
```python
from sklearn.cluster import MiniBatchKMeans
import numpy as np

# Load all embeddings from SQLite
embeddings = np.array([row['embedding'] for row in memories])  # [2484, 768]

# Cluster
kmeans = MiniBatchKMeans(n_clusters=200, batch_size=256, init='k-means++')
labels = kmeans.fit_predict(embeddings)

# Flag clusters with >3 members within distance threshold as dedup candidates
for cluster_id in range(200):
    cluster_members = [m for m, l in zip(memories, labels) if l == cluster_id]
    if len(cluster_members) > 3:
        # surface for review or auto-merge oldest
        pass
```

**Expected outcome:** Surface 50-200 near-duplicate memory pairs in current corpus. Merging or pruning them improves retrieval precision (less noise in top-k results) and reduces index size.

**Implementation complexity:** Low — offline script, no production changes. Results reviewed before any deletion.

**Priority:** Low-Medium. Useful housekeeping, not a retrieval breakthrough.

---

### ML-Bio T4 — LSTM for Memory Access Pattern Prediction

**Source:** `chapters/chapter10/chapter10 - LSTM Forecasting.ipynb`

The notebook forecasts demand using a 2-unit LSTM with 100-step lookback window, trained on rolling-window-smoothed time series. Convergence: loss 0.0017 → 0.00029 in 10 epochs.

**BRAIN application:**

Once the retrieval analytics log (RTK T17) exists, session-level memory access events form a time series: which memory IDs were retrieved, in which order, across which sessions. An LSTM trained on this could predict which memories are likely needed in the *next* session — pre-warming the context window.

**Proposed pipeline (future, depends on T17):**
```python
# After retrieval_log exists:
# sequence: [memory_id_t-5, ..., memory_id_t] → predicted memory_id_t+1
# Train LSTM on this, use at session start to pre-fetch top-3 predicted memories
```

**Caveat:** This is speculative. Requires T17 (retrieval logging) to exist first. With 1,443 sessions in the corpus there may be enough signal, but session-to-memory linkage needs to be tracked explicitly — currently it isn't.

**Priority:** Low. File and revisit after T17 is shipping.

---

## Sources Analyzed

| Repo | What it is | Analyzed |
|---|---|---|
| [PatternRecognition/OpenBMI](https://github.com/PatternRecognition/OpenBMI) | EEG Brain-Computer Interface pattern recognition pipeline (MATLAB) | 2026-04-26 |
| [josephmisiti/awesome-machine-learning](https://github.com/josephmisiti/awesome-machine-learning) | Curated list of 500+ ML libraries and tools across all languages (72K stars) | 2026-04-26 |
| [abhigyanpatwari/GitNexus](https://github.com/abhigyanpatwari/GitNexus) | Zero-server code intelligence engine: knowledge graph + Graph RAG agent (30K stars, TypeScript) | 2026-04-26 |
| [rtk-ai/rtk](https://github.com/rtk-ai/rtk) | Rust CLI proxy that intercepts AI agent commands and filters output for 60-90% token reduction | 2026-04-26 |
| [pjreddie/darknet](https://github.com/pjreddie/darknet) | YOLO object detection framework in C — Joseph Redmon's original implementation | 2026-05-01 |
| [google/automl](https://github.com/google/automl) | Google AutoML: EfficientNetV2, EfficientDet, AutoAugment, Hero (symbolic optimizer search), Lion optimizer | 2026-05-01 |
| [garrytan/gbrain](https://github.com/garrytan/gbrain) | Production knowledge management system for AI agents (17,888+ pages, 4,383 people, TypeScript/PGLite) | 2026-05-01 |
| [deep6nick/neurolinked](https://github.com/deep6nick/neurolinked) | Biologically-inspired neuromorphic memory system with 100K spiking neurons, STDP learning, MCP integration (Python) | 2026-05-01 |
| [MemPalace/mempalace](https://github.com/MemPalace/mempalace) | Local-first AI memory system, 96.6% R@5 on LongMemEval, hybrid BM25+cosine, temporal knowledge graph, 4-layer context stack (Python) | 2026-05-01 |
| [PacktPublishing/Machine-Learning-in-Biotechnology-and-Life-Sciences](https://github.com/PacktPublishing/Machine-Learning-in-Biotechnology-and-Life-Sciences) | Packt textbook: 12-chapter ML pipeline in Jupyter (Biopython, RDKit, SVM, clustering, NLP/transformers, LSTM, Flask deployment) | 2026-05-01 |

---

## Core Insight

OpenBMI is an EEG Brain-Computer Interface pattern recognition pipeline. BRAIN is also a
pattern recognition pipeline — operating on 768-dim semantic embedding vectors instead of
EEG voltage arrays. The underlying math is structurally identical.

| OpenBMI concept                        | BRAIN equivalent                                      |
| -------------------------------------- | ----------------------------------------------------- |
| EEG trial `[time × channels]`          | Memory text → embedding `[768 dims]`                  |
| EEG classes (left/right motor imagery) | Memory types (`solution`, `conversation`, `decision`) |
| Subjects / sessions                    | Projects (`AI`, `wealth`, `sakbe`, etc.)              |
| Spatial filter matrix W                | Linear projection on embedding space                  |
| Artifact rejection                     | Low-quality memory filtering                          |
| Baseline correction                    | Corpus mean-centering                                 |
| k-fold cross-validation                | Retrieval precision evaluation                        |

Every OpenBMI algorithm operates on feature matrices. Embeddings **are** feature matrices.

---

## Technique 1 — Ledoit-Wolf Shrinkage + RLDA Projection

**Source files:** `BMI_modules/Training/LDA/clsutil_shrinkage.m`, `train_RLDAshrink.m`

### What it does in OpenBMI

When you compute a covariance matrix in high dimensions with few samples (e.g. 768 dims,
300 samples per class), the matrix is rank-deficient and numerically unstable. Ledoit-Wolf
shrinkage blends the sample covariance `S` with a structured target `T` (scaled identity)
using an analytically optimal mixing parameter gamma:

```
C* = gamma * T + (1 - gamma) * S / (n - 1)

gamma = n * sum(V) / sum((S - T)^2)      % computed analytically, no tuning
```

RLDA then uses `C*` to train a linear discriminant: `w = inv(C*) * mean_diff`.

### BRAIN application

BRAIN's vector index does raw cosine search with zero class awareness. A query about a
code solution can return conversations that share vocabulary.

**Proposed pipeline:**
1. Load all memory embeddings labeled by `memory_type` from SQLite
2. Compute per-class covariance matrices with LW shrinkage (critical: 768 dims >> ~500 samples per type)
3. Solve generalized eigenvalue problem → projection matrix W
4. Project all stored embeddings through W → lower-dim discriminative space
5. Re-index in projected space; project every query before search

**Why shrinkage is mandatory here:** With 7000 memories across 6 types (~1000/type average,
768 dims), the raw sample covariance is near-singular. Without regularization, the LDA
projection overfits to noise. LW shrinkage gives a well-conditioned estimate with an
analytically derived gamma — no hyperparameter search needed.

**Expected gain:** Retrieval becomes type-aware. Memories cluster by type in the projected
space, not just by surface vocabulary similarity.

**Implementation complexity:** Medium. Requires a one-time offline step (scipy linalg) that
produces a W matrix stored in SQLite. Search path adds one matrix multiply per query.

---

## Technique 2 — Baseline Correction → Embedding Mean-Centering

**Source file:** `BMI_modules/PreProcessing/prep_baseline.m`

### What it does in OpenBMI

Subtracts the mean amplitude of a reference window from each trial, removing the shared
DC offset so that class-specific deviations become visible.

```matlab
base = nanmean(dat.x(idx,:,:), 1);
x = dat.x - repmat(base, [nT, 1, 1]);
```

### BRAIN application

All memory embeddings share a "corpus mean" — a vector representing generic language
common to everything (function words, common code vocabulary). This shared component
adds noise to cosine similarity comparisons because it dominates the dot product.

**Implementation:**
```python
# at index build time
corpus_mean = np.mean(all_embeddings, axis=0)   # shape [768]
centered = all_embeddings - corpus_mean          # subtract baseline

# at query time
query_centered = query_embedding - corpus_mean
```

**Why it helps:** Cosine similarity between two embeddings picks up both the
content-specific component AND the shared corpus mean. After mean-centering, the
shared component is zeroed and similarity reflects only content-specific variation.
This is a known technique in NLP retrieval (analogous to removing the "first principal
component" of the embedding space).

**Implementation complexity:** Very low. 2 lines at index build, 1 line at query time.
The corpus mean vector is stored in SQLite as a single config row.

**Priority: Implement first** — lowest risk, no structural changes, measurable gain.

---

## Technique 3 — Mutual Information Band Selection → Embedding Dimension Selection

**Source file:** `BMI_modules/Functions/func_fbcsp.m` (calls `proc_mutual_information`)

### What it does in OpenBMI

Filter Bank CSP applies bandpass filters at multiple frequency ranges, extracts
log-variance features per band, then uses mutual information between features and
class labels to select the most discriminative frequency band:

```matlab
for i = 1:length(opt.Filters)
    miValue(i) = proc_mutual_information(features{1,i}, features{2,i}, kernelWidth);
end
% select band with highest MI
```

### BRAIN application

The 768 embedding dimensions are not equally useful for distinguishing memory types.
Some dimensions encode syntax/stopwords (low MI with memory_type), others encode
domain concepts (high MI).

**Proposed pipeline:**
1. For each embedding dimension `d` in [1..768], compute MI between that dimension's
   values and the `memory_type` label across all memories
2. Select top-k dimensions (e.g. k=128 or k=256)
3. Build a secondary index on this reduced representation

**Relationship to Technique 1:** MI selection and LDA projection are complementary.
LDA finds a discriminative projection (supervised). MI selection finds individual
discriminative dimensions (simpler, no matrix solve). Start with LDA; use MI to
validate which dimensions matter.

**Implementation complexity:** Medium. Requires computing MI for each dimension
(scikit-learn `mutual_info_classif` or scipy estimators).

---

## Technique 4 — Artifact Rejection → Low-Quality Memory Filtering

**Source file:** `BMI_modules/PreProcessing/prep_rejectArtifactMAxMin.m`

### What it does in OpenBMI

Rejects EEG trials where max-minus-min amplitude across selected channels exceeds a
threshold. Removes corrupted/noisy trials before they contaminate the classifier.

```matlab
rejcrt = rejmax - rejmin;
% reject trials where peak-to-peak > threshold
```

### BRAIN application

Some memories in the corpus are low-quality: too short, poorly summarized, or
semantically degenerate. Their embeddings are statistical outliers that pollute
nearest-neighbor searches.

**Detection criterion (analogous to max-min threshold):**
```python
# For each memory type, compute centroid and distance distribution
centroid = np.mean(type_embeddings, axis=0)
distances = cosine_distance(type_embeddings, centroid)
threshold = np.mean(distances) + 2 * np.std(distances)
outliers = memories[distances > threshold]
```

Outlier memories can be: flagged for review, assigned lower `importance` weight,
or excluded from the primary search index.

**Note:** This maps directly to the `importance` field already in BRAIN's schema
(`memories.importance REAL DEFAULT 0.5`). Outlier detection score → importance weight.

**Implementation complexity:** Low-Medium. One-time offline pass over the corpus.

---

## Technique 5 — Cross-Validation Framework → Retrieval Quality Measurement

**Source file:** `BMI_modules/Evaluations/eval_crossValidation.m`

### What it does in OpenBMI

Modular k-fold CV that chains `prep → train → test` steps, preserving learned
parameters (like CSP weights) across folds. Outputs loss per fold.

### BRAIN application

BRAIN currently has no objective metric for retrieval quality. Without measurement,
it's impossible to know whether any optimization actually helps.

**Proposed evaluation protocol (adapted k-fold):**
1. Hold out 10% of memories (stratified by type)
2. For each held-out memory: form a query from its content
3. Search the remaining 90% corpus
4. Score: does the held-out memory appear in top-k results? (precision@k)
5. Repeat k times, average precision@k

This gives a baseline score for current cosine search, then scores after each
optimization (mean-centering, LDA projection) to confirm improvement.

**Implementation complexity:** Low — pure Python offline script, no changes to live system.

---

## Implementation Roadmap

| Priority | Technique | Effort | Expected Impact |
|---|---|---|---|
| 1 | Mean-centering (baseline correction) | Low | Medium — cleaner cosine similarity |
| 2 | RLDA + Ledoit-Wolf projection | Medium | High — type-aware retrieval |
| 3 | k-fold retrieval evaluation | Low | Enables measurement of all other gains |
| 4 | Artifact rejection / quality filter | Medium | Medium — corpus cleanup |
| 5 | MI dimension selection | Medium | Medium — reduces noise dimensions |

---

## Open Questions / Further Research

- [ ] What k (projection dims) is optimal for the LDA step? Try 32, 64, 128 dims.
- [ ] Does per-project LDA outperform per-type LDA? (separate W matrix per project)
- [ ] Can BSSFO (Bayesian Spatio-Spectral Filter Optimization) inspire a Bayesian search
      hyperparameter optimizer (n_results, threshold, recency weight)?
- [ ] Multi-embedding "filter bank": run embeddings through multiple models
      (general + code-specific), select per query. Analogous to FBCSP multi-band selection.
- [ ] Temporal smoothing (prep_movingAverage analog): weight search scores by recency
      using a causal moving window over the timestamp dimension.

---

---

---

# Research Source 2 — awesome-machine-learning

> https://github.com/josephmisiti/awesome-machine-learning
> Curated list of 500+ ML libraries across all languages. 72K stars. Full README (212KB) analyzed.

## Key Finding: BRAIN has 7 distinct optimization surfaces

After analyzing the full list against BRAIN's architecture (Rust core, Python embedder,
SQLite + brute-force cosine index, 7000+ memories), these are the most actionable findings,
grouped by BRAIN component.

---

## A — Vector Index: Approximate Nearest Neighbors

**Current state:** `brain/rust/src/index.rs` — brute-force O(n × 768) scan. Fine at 7K,
degrades at 50K+.

### A1 — Annoy (Spotify)
> https://github.com/spotify/annoy

Random projection trees. Builds a forest of binary trees partitioning the embedding space.
Query is O(log n) with tunable n_trees (accuracy vs. speed). Static index (build once,
query many). Has Python bindings and a Rust port. Drop-in replacement for the brute-force
search in `index.rs` when the corpus grows beyond ~50K.

**When to act:** Once memories exceed 30K. Not urgent now.

### A2 — Qdrant
> https://qdrant.tech / https://github.com/qdrant/qdrant

Open-source vector similarity search engine **written in Rust**. Has extended metadata
filtering (filter by project, type, date before doing ANN search). Could replace both
the brute-force `VectorIndex` in Rust and the Python ChromaDB layer — single Rust
dependency instead of two. Client libraries available for Python and Rust.

**When to act:** When the Python → Rust migration is complete and a single-binary
architecture is the goal.

---

## B — Retrieval Quality: Hybrid Search (BM25 + Dense)

**Current gap:** BRAIN only does dense (embedding cosine) search. Exact-match queries
suffer — searching for a specific function name, error string, or rare term gets drowned
out by semantic similarity.

### B1 — Haystack (deepset-ai)
> https://github.com/deepset-ai/haystack

Framework for building Transformer + LLM applications. Implements:
- **Dense retrieval** (DPR): same as BRAIN's current approach
- **Sparse retrieval** (BM25/TF-IDF): exact token matching
- **Hybrid retrieval**: score fusion of dense + sparse
- **Re-ranking**: cross-encoder re-scores top-k candidates for final ordering

Hybrid consistently outperforms dense-only, especially for rare/specific terms. BRAIN
should implement BM25 on memory content text alongside the vector index. SQLite's
built-in FTS5 extension already provides BM25 — no new dependency required.

**Concrete implementation path:**
1. Enable SQLite FTS5 on `memories.content`
2. At query time: run BM25 query → get top-50 BM25 candidates
3. Run cosine search → get top-50 dense candidates
4. Merge and re-score: `final_score = alpha * bm25_score + (1-alpha) * cosine_score`
5. Return top-k from merged list

**Impact: High.** Fixes the exact-match retrieval gap with no new dependencies
(SQLite FTS5 is already available in rusqlite).

### B2 — Awesome RAG Production
> https://github.com/Yigtwxx/Awesome-RAG-Production

Curated collection of battle-tested tools for production RAG: vector databases,
retrieval & reranking, evaluation, observability. Use as reference when evaluating
retrieval improvements.

---

## C — Memory Quality: Outlier Detection & Deduplication

**Current gap:** 7000+ memories accumulated from 5 ingestion pipelines with no
systematic quality scoring or semantic deduplication.

### C1 — PyOD (Python Outlier Detection)
> https://github.com/yzhao062/pyod

40+ outlier detection algorithms in one library: LOF, Isolation Forest, OCSVM, COPOD,
VAE-based detection, ensemble methods. Directly solves the problem identified in OpenBMI
Technique 4 (artifact rejection).

**Concrete usage for BRAIN:**
```python
from pyod.models.lof import LOF
from pyod.models.iforest import IForest

# Load all embeddings from SQLite
X = np.array(all_embeddings)  # [n_memories, 768]

# Local Outlier Factor: finds memories in low-density regions of embedding space
clf = LOF(n_neighbors=20)
clf.fit(X)
scores = clf.decision_scores_  # higher = more anomalous

# Write scores back to memories.importance column
```

LOF is preferred over Isolation Forest here because it's density-based and
respects the local structure of the embedding manifold.

### C2 — Dedupe
> https://github.com/dedupeio/dedupe

ML-based fuzzy deduplication with active learning. Learns blocking rules from examples,
then scales to millions of records. Finds near-duplicates that string matching misses
(same knowledge expressed in different words).

**Why this matters:** BRAIN ingests from Perplexity exports, Claude Code sessions, Obsidian,
books — the same concept appears multiple times in different wording. Simple upsert (by ID)
doesn't catch semantic duplicates. Dedupe uses TF-IDF + learned features to find them.

**Concrete usage:**
```python
import dedupe

fields = [{'field': 'content', 'type': 'Text'}]
deduper = dedupe.Dedupe(fields)
deduper.prepare_training(memories_dict)
# ... active learning loop to label a few examples ...
deduper.train()
clustered = deduper.partition(memories_dict, threshold=0.5)
# clustered gives groups of duplicate memories → keep highest-importance one
```

### C3 — Ambrosia
> https://github.com/reactorsh/ambrosia

Cleans up LLM datasets using other LLMs. Approach: send batches of memories to Claude,
ask it to identify near-duplicates, contradictions, or low-quality entries. Complementary
to Dedupe (semantic LLM-based vs. statistical ML-based dedup).

---

## D — Memory Organization: Clustering

**Current gap:** BRAIN's only organizational structure is flat `type` + `project` labels
assigned at ingest time. Natural topic clusters in the 7000+ corpus are invisible.

### D1 — HDBScan
> https://github.com/lmcinnes/hdbscan

Hierarchical Density-Based Spatial Clustering. Key advantages over K-means:
- No need to specify number of clusters
- Discovers clusters of arbitrary shape
- Explicitly labels noise points (not forced into any cluster)
- Produces a hierarchy — can navigate at different granularities

**Concrete usage for BRAIN:**
```python
import hdbscan

X = np.array(all_embeddings)  # [7000, 768]
# Reduce dims first (UMAP or PCA to 50 dims) for better density estimation
clusterer = hdbscan.HDBSCAN(min_cluster_size=15, metric='euclidean')
labels = clusterer.fit_predict(X)
# labels[i] = cluster ID for memory i, or -1 if noise

# Write cluster_id to memories table (new column)
# Use in: web viewer grouping, cluster-first search, reflect targeting
```

**Downstream use:** When searching, first identify which cluster the query embedding
falls into, then search within that cluster (faster + higher precision). Use cluster
structure to target the LLM reflection step (reflect within each cluster, not globally).

### D2 — Gensim (Topic Modeling)
> https://github.com/RaRe-Technologies/gensim

LDA topic modeling. Discovers latent topics in the memory text corpus (not the embedding
space — operates on token frequencies). Complementary to HDBScan: HDBScan clusters by
embedding geometry; LDA clusters by word co-occurrence patterns.

**Use case:** Auto-generate human-readable topic labels for HDBScan clusters using LDA.

---

## E — Rust-Native ML (Python Elimination)

**Current state:** BRAIN's core is Rust (`brain/rust/`) but the embedder is Python
(`brain/core/embedder.py`). The Python dependency is the main obstacle to a
single-binary deployment.

### E1 — linfa
> https://github.com/rust-ml/linfa

Comprehensive ML toolkit in pure Rust. Implements:
- **KMeans clustering** — memory organization
- **LDA** — the OpenBMI-inspired discriminative projection (Technique 1)
- **PCA** — dimensionality reduction before clustering
- **Gaussian Mixture Models** — soft cluster assignment
- **Nearest neighbor** — could back the ANN index
- **Linear/logistic regression** — importance scoring

**This is the most important Rust finding.** All five OpenBMI-inspired techniques
(Techniques 1–5) can be implemented in Rust using linfa, with zero Python dependencies.
The LDA projection matrix W computed by linfa in the Rust binary, applied at query time
in the same binary — no IPC, no subprocess.

### E2 — rust-bert
> https://github.com/guillaume-be/rust-bert

Rust-native inference for BERT, DistilBERT, sentence transformers, GPT2. Uses LibTorch.
Replaces `brain/core/embedder.py` entirely. The `SentenceTransformer` model currently
used in Python can be loaded directly in Rust.

**Trade-off:** LibTorch adds ~500MB to the binary. Acceptable for a server deployment;
may be heavy for a CLI tool. shimmy (below) is lighter.

### E3 — shimmy
> https://github.com/Michael-A-Kuykendall/shimmy

Python-free Rust inference server for NLP models with **OpenAI API compatibility**.
BRAIN's embedder could point to a local shimmy instance at `localhost:PORT` using
the same OpenAI embedding API format. Zero code change in the Rust binary — just
swap the embedding endpoint URL.

**This is the lowest-effort path to eliminating Python from the embedding pipeline.**

---

## F — Evaluation: Measuring Retrieval Quality

**Current gap:** No objective metric for whether any optimization actually improves retrieval.

### F1 — promptfoo
> https://github.com/promptfoo/promptfoo

Open-source LLM evaluation and red teaming framework. Can run test suites against
retrieval pipelines. Could evaluate BRAIN's MCP search tool responses against a
ground-truth test set of query → expected memories.

### F2 — MLflow
> https://mlflow.org

Platform for tracking experiments, reproducibility, and deployment. Log precision@k
scores for each retrieval optimization experiment (baseline cosine, mean-centered,
LDA-projected, hybrid BM25+dense). Compare runs. Store the best W matrix as an MLflow
artifact.

### F3 — DVC (Data Version Control)
> https://github.com/iterative/dvc

Version control for ML data and models. Could version BRAIN's embedding index snapshots
and the LDA projection matrix W — allowing rollback if an optimization degrades quality.

---

## G — Active Learning for Memory Quality

### G1 — modAL
> https://github.com/modAL-python/modAL

Modular active learning framework (scikit-learn compatible). Uses uncertainty sampling:
finds the data points a model is least confident about and prioritizes them for labeling.

**BRAIN application:** Train a classifier to predict `memory_type` from embeddings. Run
it on all 7000 memories. Find the 200 memories the classifier is most uncertain about —
these are the most ambiguous/noisy ones. Flag them for re-summarization or manual review.
This is more targeted than random sampling or distance-from-centroid outlier detection.

---

## H — Reference Books (Free PDFs)

These books from the list directly cover BRAIN's retrieval math. All free online.

| Book | Relevance |
|---|---|
| [Introduction to Information Retrieval](https://nlp.stanford.edu/IR-book/) (Manning, Raghavan, Schütze) | BM25, TF-IDF, vector space models, evaluation (MAP, NDCG). Foundational for hybrid retrieval. |
| [Mining Massive Datasets](http://infolab.stanford.edu/~ullman/mmds/book.pdf) (Ullman) | LSH, locality-sensitive hashing for ANN search, similarity at scale. |
| [Pattern Recognition and Machine Learning](http://users.isr.ist.utl.pt/~wurmd/Livros/school/Bishop%20-%20Pattern%20Recognition%20And%20Machine%20Learning%20-%20Springer%20%202006.pdf) (Bishop) | Gaussian mixtures, PCA, kernel methods. Theory behind clustering and projection. |

---

## Updated Implementation Roadmap

| Priority | Technique | Source | Effort | Expected Impact |
|---|---|---|---|---|
| 1 | Mean-centering embeddings (baseline correction) | OpenBMI | Low | Medium |
| 2 | SQLite FTS5 BM25 hybrid retrieval | Haystack (awesome-ml) | Low | High |
| 3 | k-fold retrieval evaluation (precision@k) | OpenBMI | Low | Enables all measurement |
| 4 | RLDA + Ledoit-Wolf projection | OpenBMI | Medium | High |
| 5 | PyOD outlier detection → importance scores | awesome-ml | Medium | Medium |
| 6 | Dedupe semantic deduplication pass | awesome-ml | Medium | Medium |
| 7 | HDBScan cluster discovery | awesome-ml | Medium | Medium |
| 8 | linfa Rust port of LDA/KMeans | awesome-ml | High | High (enables single binary) |
| 9 | shimmy / rust-bert → eliminate Python embedder | awesome-ml | High | High (single binary) |
| 10 | Qdrant replace brute-force index | awesome-ml | High | Low now, high at 50K+ |

---

---

---

# Research Source 3 — GitNexus

> https://github.com/abhigyanpatwari/GitNexus
> TypeScript monorepo. 30K stars. Full source analyzed: `hybrid-search.ts`, `bm25-index.ts`,
> `graph.ts`, `pipeline.ts`, `community-processor.ts`, `chunker.ts`, `embedder.ts`,
> `schema.ts`, `tools.ts`, `entry-point-scoring.ts`, `structural-extractor.ts`.

## What GitNexus is

A client-side code intelligence engine that:
1. Parses any codebase via tree-sitter AST (13+ languages)
2. Builds a typed knowledge graph (nodes: File, Function, Class, Method…; edges: CALLS, IMPORTS, EXTENDS, HAS_METHOD…)
3. Stores in LadybugDB (KuzuDB under the hood) with HNSW vector index + FTS
4. Runs **hybrid BM25 + semantic search with Reciprocal Rank Fusion**
5. Detects communities (Leiden algorithm) and execution processes (call chains)
6. Exposes everything as MCP tools to AI agents

GitNexus is structurally a more advanced version of BRAIN:
- BRAIN stores flat memories + flat vector index
- GitNexus stores typed graph nodes + typed relationships + vector index + FTS

Every architectural decision in GitNexus is a direct lesson for BRAIN's evolution.

---

## Technique 6 — Reciprocal Rank Fusion (RRF) for Hybrid Search

**Source file:** `gitnexus/src/core/search/hybrid-search.ts`

### What it does in GitNexus

Merges BM25 (keyword) and semantic (vector) search results without needing score
normalization. Each result gets an RRF score based only on its rank position:

```typescript
const RRF_K = 60;  // standard literature constant
rrfScore = 1 / (RRF_K + rank + 1)

// Results found by BOTH methods accumulate scores from each:
merged.score = 1/(60 + bm25_rank + 1) + 1/(60 + semantic_rank + 1)
```

Results found by both methods float to the top automatically. No alpha/beta
weight tuning required.

### Why RRF beats linear combination

Linear combination (`alpha * bm25 + (1-alpha) * cosine`) requires:
- Score normalization (BM25 and cosine have different ranges)
- Manual alpha tuning per query type

RRF has no normalization, no tuning, and is proven more robust to outliers. Used
by Elasticsearch, Pinecone, and other production search systems.

### BRAIN application

BRAIN has no hybrid search today. The implementation path:

```rust
// In brain/rust/src/index.rs — add to search()
pub fn hybrid_search(
    query_text: &str,      // for BM25 via SQLite FTS5
    query_vec: &[f32],     // for cosine via VectorIndex
    n: usize,
    rrf_k: f32,            // 60.0
) -> Vec<(String, f32)> {
    let bm25 = fts5_search(query_text, n);      // SQLite FTS5 results
    let semantic = self.search(query_vec, n);   // existing cosine search

    // RRF merge — same logic as hybrid-search.ts
    let mut scores: HashMap<String, f32> = HashMap::new();
    for (rank, (id, _)) in bm25.iter().enumerate() {
        *scores.entry(id.clone()).or_insert(0.0) += 1.0 / (rrf_k + rank as f32 + 1.0);
    }
    for (rank, (id, _)) in semantic.iter().enumerate() {
        *scores.entry(id.clone()).or_insert(0.0) += 1.0 / (rrf_k + rank as f32 + 1.0);
    }
    // sort descending by score
}
```

SQLite FTS5 is already available in `rusqlite` — zero new dependencies.

**Impact: Highest of all findings.** Combines exact-match (error messages, function
names, specific terms) with semantic similarity in a single ranked list.

---

## Technique 7 — Per-Type FTS Indexes with Top-3 Merge

**Source file:** `gitnexus/src/core/search/bm25-index.ts`

### What it does in GitNexus

Creates separate FTS indexes per node type (File, Function, Class, Method,
Interface), queries all in parallel, then merges by file path using the **top-3
highest-scoring nodes per file** (not sum-all):

```typescript
// Take top-3 per file, sum their scores
const top3 = [...entries].sort((a, b) => b.score - a.score).slice(0, 3);
merged.score = top3.reduce((acc, e) => acc + e.score, 0);
```

Summing all nodes would inflate scores for large files with many mediocre
matches over files with one highly-relevant symbol. Top-3 is the fix.

### BRAIN application

BRAIN has one flat memories table. Separate FTS indexes per `memory_type`
with type-specific boosting would let a "solution" query weight matches in
the `solution` FTS index more than matches in the `conversation` index.

```sql
-- SQLite FTS5 virtual tables per type
CREATE VIRTUAL TABLE fts_solution USING fts5(content, memory_id UNINDEXED);
CREATE VIRTUAL TABLE fts_conversation USING fts5(content, memory_id UNINDEXED);
CREATE VIRTUAL TABLE fts_decision USING fts5(content, memory_id UNINDEXED);
-- ...
```

At query time: search all type tables, weight by query context, top-3 merge
per memory_id, feed into RRF alongside vector results.

---

## Technique 8 — HNSW Vector Index (replacing brute-force)

**Source file:** `gitnexus/src/core/lbug/schema.ts`

### What it does in GitNexus

Uses the database's built-in HNSW (Hierarchical Navigable Small World) vector
index instead of a brute-force scan:

```typescript
export const CREATE_VECTOR_INDEX_QUERY = `
CALL CREATE_VECTOR_INDEX(
  '${EMBEDDING_TABLE_NAME}',
  '${EMBEDDING_INDEX_NAME}',
  'embedding',
  metric := 'cosine'
)`;
```

HNSW search is O(log n) vs BRAIN's current O(n × 768). At 7K memories it's
negligible; at 50K+ it becomes critical.

### BRAIN application

BRAIN's `brain/rust/src/index.rs` is brute-force. No action needed now (7K
memories search in < 5ms). **When corpus exceeds ~30K**, drop in HNSW via
`usearch` (Rust crate, pure Rust HNSW) or switch to Qdrant as the index backend.

GitNexus confirms: the right place to add HNSW is at the **DB/index layer**,
not as a separate service — BRAIN's `VectorIndex` struct is already isolated and
can be swapped without changing anything else.

---

## Technique 9 — Leiden Algorithm for Community Detection

**Source file:** `gitnexus/src/core/ingestion/community-processor.ts`

### What it does in GitNexus

Builds a graph from CALLS relationships, then runs the Leiden algorithm to
detect communities (clusters of code that work together):

```typescript
const leiden = _require(leidenPath);
const result = leiden.detailed(graph, { resolution: 1.0, randomWalk: true });
// result.communities: { nodeId → communityIndex }
// result.modularity: quality score
```

Leiden is an improvement over Louvain: better connected communities, guaranteed
no disconnected communities, faster convergence.

### BRAIN application

Build a "co-occurrence graph" between memories:
- Edge: two memories appeared in the same session → weight = 1
- Edge: two memories were returned together in a search → weight += 1
- Edge: reflection explicitly linked them → weight = 3

Run Leiden on this graph to find natural topic communities in the memory corpus.
Use communities for:
- **Cluster-first search**: find which community matches the query, then
  search within that community (faster + higher precision)
- **Targeted reflection**: LLM reflects within each community, not globally
  across 7000 unrelated memories
- **Web viewer grouping**: organize the viewer by detected community, not
  flat type/project labels

No new library needed — graphology (JS) or petgraph (Rust) implement Leiden.

---

## Technique 10 — Graph Relationships Between Memories

**Source files:** `gitnexus/src/core/graph/graph.ts`, `schema.ts`

### What it does in GitNexus

Stores not just nodes but **typed, directed edges** between nodes with
properties (`type`, `confidence`, `reason`, `step`). This enables:
- Graph traversal queries (`MATCH (a)-[:CALLS]->(b)-[:CALLS]->(c)`)
- Impact analysis ("what does this function affect?")
- Process detection (sequential call chains)

### BRAIN application

BRAIN currently stores 7000 isolated memories with no relationships. Adding
a `memory_relationships` table transforms it into a knowledge graph:

```sql
CREATE TABLE memory_relationships (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES memories(id),
    target_id TEXT NOT NULL REFERENCES memories(id),
    type TEXT NOT NULL,   -- DERIVED_FROM | SAME_SESSION | ELABORATES | CONTRADICTS | FOLLOWS
    confidence REAL DEFAULT 1.0,
    reason TEXT,          -- why this link exists
    created_at TEXT NOT NULL
);
CREATE INDEX idx_mr_source ON memory_relationships(source_id);
CREATE INDEX idx_mr_target ON memory_relationships(target_id);
```

This enables:
- **`DERIVED_FROM`**: reflection output memory → source memories (already implicit)
- **`SAME_SESSION`**: memories co-occurring in a session (enables session-context retrieval)
- **`FOLLOWS`**: temporal chain within a session (enables "what came after this?")
- **`ELABORATES`**: detail memory → summary memory
- **`CONTRADICTS`**: detected contradictions (flag for resolution)

A new MCP tool `get_related(memory_id, type?, depth?)` would traverse these
edges — the analog of GitNexus's `context` tool.

### Cross-reference: gitnexus-stable-ops fork (Research Source 9, 2026-05-24)

A fork of this repo (RS9) extends the graph blueprint with the **retrieval algorithm** for T10 edges. RS3 defines the structure; RS9 defines how to query it:
- **G1** — graph distance as third retrieval signal (DFS through `memory_relationships`, score decays by hop)
- **G2** — task-type retrieval weighting (bugfix/context/recall queries get different memory type distributions)
- **G3** — token-budget-aware result selection (stop at token limit, not at k)
- **G4** — MENTIONS edge auto-inference (text scan at ingest/reflection time, no LLM needed)

RS9 also uses Python + SQLite FTS5 (same stack as brain) vs. RS3's TypeScript + KuzuDB. See RS9 for full technique specs.

### Cross-reference: personal-os-skills / Recall (2026-05-24)

Recall (ArtemXTech/personal-os-skills) independently confirms this design and adds one edge type GitNexus doesn't cover:

| Edge type | Source | In T10 schema? |
|-----------|--------|----------------|
| DERIVED_FROM, SAME_SESSION, ELABORATES, CONTRADICTS, FOLLOWS | GitNexus T10 | ✅ Yes |
| **session → file (work topology)** | Recall | ❌ Not yet |

**Work topology** = which sessions touched which files. Recall builds this as an interactive graph (sessions as nodes, files as edges between them). It reveals work clusters and cross-session dependencies that semantic search alone can't surface.

**Why it belongs in the brain graph blueprint:**
- GitNexus edges connect code nodes (Function CALLS Function)
- Brain T10 edges connect memories (memory DERIVED_FROM memory)
- Recall adds a third layer: **sessions connected via shared files** — bridging work history to memory history

**Proposed addition to T10 schema:**
```sql
-- Work topology edge (from Recall concept)
-- type = 'SHARES_FILE' | 'CO_SESSION'
-- Links two memories that appeared in sessions that both touched the same file
INSERT INTO memory_relationships (source_id, target_id, type, reason)
SELECT m1.id, m2.id, 'SHARES_FILE', f.path
FROM session_files f
JOIN memories m1 ON m1.session_id = f.session_id
JOIN memories m2 ON m2.session_id = f.session_id2
WHERE f.path = f.path2 AND m1.id != m2.id;
```

This makes brain's graph three-dimensional: semantic similarity (vector) + memory lineage (T10 edges) + **work topology (Recall-inspired edges)**. Together they enable: "Show me all memories connected to this file, across all sessions that touched it."

**Priority:** Add `SHARES_FILE` as a valid edge type in T10 schema before first graph implementation. Zero schema cost — just a new value in the `type` column.

---

## Technique 11 — AST-Aware Chunking → Semantic Chunking

**Source file:** `gitnexus/src/core/embeddings/chunker.ts`

### What it does in GitNexus

For code nodes larger than `chunkSize` (1200 chars), splits at AST statement
boundaries (not arbitrary character positions). Falls back to character-based
sliding window with overlap when AST fails. Preserves `startLine`/`endLine`
per chunk for precise location reporting.

Key detail: overlap at **statement granularity** — the overlap window is N
statements from the end of the previous chunk, not N characters. This preserves
semantic coherence across chunk boundaries.

### BRAIN application

BRAIN currently stores one embedding per memory (full content → single vector).
For long-form ingested content (books, long Obsidian notes), the single embedding
is too diluted to retrieve specific passages.

Adopt the same principle — split at **semantic boundaries** (paragraph breaks,
section headings) instead of arbitrary character positions:

```python
def semantic_chunk(text: str, chunk_size: int = 1200, overlap: int = 120):
    # Find natural split points: double newline, heading markers, list breaks
    # Never split mid-sentence
    # Overlap = last N complete sentences of previous chunk
```

For each chunk: embed separately, store in a `memory_chunks` table with
`(memory_id, chunk_index, start_offset, end_offset, embedding)`. Search over
chunks, aggregate back to memory level (max-score pooling, like GitNexus
top-3 per file).

**When to act**: specifically for book and Obsidian ingestion pipelines.
Session/exchange memories are already granular enough.

---

## Technique 12 — Multi-Factor Importance Scoring

**Source file:** `gitnexus/src/core/ingestion/entry-point-scoring.ts`

### What it does in GitNexus

Scores nodes by combining multiple signals to find "entry points" (the most
important nodes for an agent to read first):
- **Call ratio**: `callees / (callers + 1)` — pure exporters score high
- **Export status**: exported functions get boosted
- **Name patterns**: `handleX`, `onX`, `Controller` → entry point signals
- **Framework detection**: Next.js pages, Express routes get boosted

### BRAIN application

BRAIN's `importance` field is stuck at `0.5` for everything. Compute a real
multi-factor importance score at ingest and update time:

| Signal | Weight | Rationale |
|---|---|---|
| Retrieval frequency | High | Memories retrieved often are valuable |
| Source quality | Medium | Book > session exchange > auto-reflection |
| Recency (decay) | Medium | Recent memories more likely relevant |
| Session centrality | Medium | Memories appearing in many sessions are "hubs" |
| Reflection citation | High | If a reflection explicitly cited this memory, it's important |
| Embedding outlier | Negative | Distance from type centroid → low quality signal |

Write importance score back to `memories.importance` after each retrieval
and each reflection cycle. Use importance as a re-ranking signal after
initial cosine/RRF retrieval.

---

## Technique 13 — `task_context` + `goal` in Search Queries

**Source file:** `gitnexus/src/mcp/tools.ts` — the `query` tool definition

### What it does in GitNexus

The `query` tool takes three inputs:
- `query` — the raw search string
- `task_context` — "what you're working on" (e.g., "adding OAuth support")
- `goal` — "what you want to find" (e.g., "existing auth validation logic")

Combining all three into the embedding query produces significantly better
re-ranking than a single search string.

### BRAIN application

BRAIN's `search_brain` MCP tool takes only `query`. Adding `task_context`
enriches the query embedding:

```python
def build_search_query(query: str, task_context: str = "", goal: str = "") -> str:
    parts = [query]
    if task_context:
        parts.append(f"Context: {task_context}")
    if goal:
        parts.append(f"Goal: {goal}")
    return " | ".join(parts)

# embed the enriched string instead of raw query
embedding = embed(build_search_query(query, task_context, goal))
```

Low effort, directly improves precision for multi-step agent workflows where
the agent knows what it's trying to accomplish.

---

## Updated Full Implementation Roadmap

| Priority | Technique | Source | Effort | Impact | Status |
|---|---|---|---|---|---|
| 1 | Mean-centering embeddings | OpenBMI | Low | Medium | — |
| 2 | **RRF hybrid search (BM25 + cosine)** | **GitNexus** | Low | **Highest** | ✅ Phase 1 (alpha-weighted hybrid in `brain_api`) |
| 3 | k-fold retrieval evaluation (precision@k) | OpenBMI | Low | Enables measurement | ✅ Phase 6 (`--facts-only`, `facts_queries.jsonl`) |
| 4 | `task_context` + `goal` in search queries | GitNexus | Low | Medium | — |
| 5 | RLDA + Ledoit-Wolf projection on embeddings | OpenBMI | Medium | High | — |
| 6 | PyOD outlier detection → importance scores | awesome-ml | Medium | Medium | — |
| 7 | Dedupe semantic deduplication pass | awesome-ml | Medium | Medium | — |
| 8 | Multi-factor importance scoring | GitNexus | Medium | Medium | — |
| 9 | **Graph relationships (`memory_relationships` table)** | **GitNexus** | Medium | **High** | — |
| 10 | **Leiden community detection on co-occurrence graph** | **GitNexus** | Medium | High | — |
| 11 | Per-type FTS indexes with top-3 merge | GitNexus | Medium | Medium | — |
| 12 | Semantic chunking for book/Obsidian ingestion | GitNexus | Medium | Medium | — |
| 13 | linfa Rust port of LDA/KMeans | awesome-ml | High | High | — |
| 14 | shimmy / rust-bert → eliminate Python embedder | awesome-ml | High | High | ✅ Phase 7 (`event_time.unwrap_or(timestamp)` in decay) |
| 15 | HNSW via usearch (when corpus > 30K) | GitNexus + awesome-ml | High | Low now | — |

---

## Research Log

| Date | Source | Finding |
|---|---|---|
| 2026-04-26 | OpenBMI | Initial analysis. Core insight: OpenBMI pipeline maps to BRAIN's embedding pipeline. 5 techniques identified (LW shrinkage, mean-centering, MI selection, artifact rejection, k-fold eval). |
| 2026-04-26 | awesome-machine-learning | Full 212KB README analyzed. 8 optimization surfaces identified. Key additions: BM25 hybrid retrieval (SQLite FTS5), PyOD outlier detection, Dedupe deduplication, HDBScan clustering, linfa for Rust-native ML, shimmy for Python-free embeddings. |
| 2026-04-26 | GitNexus | Full TypeScript source analyzed. 8 new techniques. Key additions: RRF hybrid search (production-tested implementation), graph relationships between memories, Leiden community detection, per-type FTS with top-3 merge, multi-factor importance scoring, semantic chunking, task_context enrichment. Most important finding: BRAIN should evolve from flat vector store → typed knowledge graph. |
| 2026-04-26 | RTK | Full Rust source analyzed (hooks/, core/, learn/, discover/, filters/). 11 techniques identified. Key additions: PostToolUse output compression pipeline, TOML filter pipeline with inline tests, session JSONL mining for behavioral signals, retrieval analytics tracking, 3-level config hierarchy, compound query decomposition. Most important finding: BRAIN should compress its own MCP tool output before returning to Claude — the same architecture RTK uses for command output. |

---

---

---

# Research Source 4 — RTK

> https://github.com/rtk-ai/rtk
> Rust CLI proxy. Full source analyzed: `src/hooks/hook_cmd.rs`, `src/core/filter.rs`,
> `src/core/toml_filter.rs`, `src/core/runner.rs`, `src/core/stream.rs`, `src/core/tracking.rs`,
> `src/analytics/gain.rs`, `src/learn/mod.rs`, `src/discover/registry.rs`, `src/hooks/permissions.rs`,
> sample filters: `terraform-plan.toml`. All filter TOML files surveyed (60+ commands).

## What RTK is

A single Rust binary inserted between AI agents and the shell. When Claude Code executes
`git status`, RTK intercepts via a PreToolUse hook, rewrites the command to `rtk git status`,
then captures the output and applies an 8-stage filter pipeline before returning it to Claude.
Result: 60-90% token reduction across 100+ supported CLI commands.

RTK is structurally a **MCP output filter** — the same architecture that BRAIN's MCP tools
need. BRAIN currently returns raw content blobs to Claude. RTK shows exactly how to compress
structured tool output before it enters the LLM context.

| RTK concept | BRAIN equivalent |
|---|---|
| Shell command output | MCP `search_brain` result blob |
| 8-stage TOML filter pipeline | MCP response compression pipeline |
| PreToolUse hook (intercept before) | PostToolUse hook (compress after) |
| `tracking.rs` (per-command analytics) | `retrieval_log` table (per-query analytics) |
| `learn/mod.rs` (mine JSONL sessions) | Mine session JSONL for memory quality signals |
| `match_output` short-circuit | Empty-results short-circuit in MCP tools |
| 3-level TOML config lookup | 3-level BRAIN config hierarchy |
| 100+ command TOML filter library | Per-tool MCP response templates |

---

## Technique 14 — PostToolUse Hook: Compress MCP Output Before Claude Reads It

**Source files:** `src/hooks/hook_cmd.rs`, `src/hooks/permissions.rs`

### What it does in RTK

RTK registers as a `PreToolUse` hook in Claude Code's `settings.json`. When Claude is about
to run a Bash command, RTK receives the JSON payload on stdin:

```json
{"tool_name": "Bash", "tool_input": {"command": "git status", "timeout": 30000}}
```

It rewrites the command and returns an `updatedInput` to Claude Code before execution:

```json
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "allow",
    "updatedInput": {"command": "rtk git status", "timeout": 30000}
  }
}
```

Key engineering detail: when rewriting, RTK **preserves all other `tool_input` fields**
(`timeout`, `description`) — it only changes `command`. The `has_heredoc()` guard silently
passes through multi-line inputs that would break the line-based filter pipeline.

For compound commands (`git add . && cargo test`), `split_on_operators()` decomposes into
segments and rewrites each independently: `rtk git add . && rtk cargo test`.

Auto-detects 4 hook formats at runtime: Claude Code (snake_case), Copilot Chat (VS Code),
Copilot CLI (camelCase `toolArgs`), Cursor, Gemini — same binary, different JSON shapes.

### BRAIN application

BRAIN should register a **PostToolUse hook** that intercepts the raw output of Bash commands
*after* execution, before Claude reads it. This is the mirror of RTK's PreToolUse rewrite:

```json
// PostToolUse hook stdin from Claude Code
{
  "tool_name": "Bash",
  "tool_input": {"command": "git log --oneline -50"},
  "tool_response": {"output": "...500 lines of git log output...", "exit_code": 0}
}
```

The hook calls BRAIN's filter pipeline on `tool_response.output` and returns a compressed
version. This is a **zero-change-to-BRAIN-core** optimization — the hook is a standalone
binary registered in `~/.claude/settings.json` under `postToolUse`.

The `has_heredoc()` guard pattern is directly reusable: before attempting any compression,
check if the output exceeds a threshold or contains patterns that make compression unsafe.

**Env-prefix preservation** (`RUST_LOG=debug cargo test` → `RUST_LOG=debug rtk cargo test`)
applies to BRAIN's output context: preserve any prefix/suffix metadata when compressing
the body.

**Implementation complexity:** Medium. New standalone hook binary, one PostToolUse entry in
`settings.json`. No changes to `brain_api` or MCP server.

---

## Technique 15 — 8-Stage Declarative TOML Filter Pipeline with Inline Tests

**Source files:** `src/core/toml_filter.rs`, `src/filters/terraform-plan.toml` (and 60+ others)

### What it does in RTK

Each CLI command has a corresponding `.toml` filter file. The filter is an 8-stage declarative
pipeline applied sequentially to the raw output:

```toml
[filters.terraform-plan]
description = "Compact Terraform plan output"
match_command = "^terraform\\s+plan"
strip_ansi = true
strip_lines_matching = ["^Refreshing state", "^\\s*#.*unchanged", "^\\s*$", "^Acquiring state lock"]
max_lines = 80
on_empty = "terraform plan: no changes detected"
```

**Full 8-stage pipeline in execution order:**
1. `strip_ansi` — remove ANSI escape codes
2. `replace` — regex substitutions, chainable (`[[replace]]` array)
3. `match_output` — short-circuit: if full blob matches pattern, return compact fixed message
4. `strip_lines_matching` / `keep_lines_matching` — regex line filters
5. `truncate_lines_at` — cap each line at N chars
6. `head_lines` / `tail_lines` — keep first or last N lines
7. `max_lines` — absolute line cap (hard ceiling)
8. `on_empty` — fallback message if pipeline produces empty output

**3-level config lookup:**
1. Project-local: `.rtk/filters.toml` (overrides everything)
2. User global: `~/.config/rtk/filters.toml`
3. Compiled-in defaults: `include_str!("../../filters/...")` at compile time

**Inline tests** — every `.toml` filter file embeds regression test cases:

```toml
[[tests.terraform-plan]]
name = "strips noise, preserves content"
input = "Refreshing state...\nPlan: 1 to add"
expected = "Plan: 1 to add"
```

`rtk test` runs all inline tests — no external test file needed.

**`CompiledFilter` struct** pre-compiles all regex objects at startup (not per-line), so the
filter pipeline is CPU-cheap in the hot path.

### BRAIN application

BRAIN's `search_brain`, `get_observations_tool`, and `get_context_tool` MCP tools return
raw content blobs to Claude. A TOML-driven compression pipeline on MCP responses would
reduce tokens returned by 50-80% for large result sets.

**Per-tool filter templates:**
```toml
[filters.search_brain]
max_results = 10
strip_lines_matching = ["^embedding:", "^\\s*id:"]
truncate_content_at = 500   # chars per memory, not lines
on_empty = "No memories found for this query."

[filters.get_observations_tool]
max_results = 5
truncate_content_at = 1000
```

The `on_empty` stage directly maps to BRAIN's current "no results" handling — standardize it
once in the TOML, not scattered across each tool.

The **inline test pattern** is immediately applicable: BRAIN's MCP tools have no regression
tests on their output format. Embedding test cases in the filter TOML gives free regression
coverage as the compression logic evolves.

**Implementation complexity:** Low-Medium. Write a `BrainResponseFilter` struct mirroring
`CompiledFilter`. Add per-tool TOML files. Zero changes to retrieval logic.

---

## Technique 16 — `match_output` Short-Circuit

**Source file:** `src/core/toml_filter.rs`

### What it does in RTK

Before running the full filter pipeline, check if the raw output matches a known
"this output means X" pattern. If it does, return a compact fixed message immediately
and skip all remaining stages:

```toml
[[match_output]]
pattern = "nothing to commit"
message = "git status: working tree clean"

[[match_output]]
pattern = "Your branch is up to date"
message = "git status: branch up to date, no changes"
```

This is zero-cost on the hot path: one regex check, then either short-circuit (cheap) or
fall through to the normal pipeline.

### BRAIN application

BRAIN's MCP tools have several predictable "zero-content" states that currently return
verbose empty structures. Short-circuit them:

```toml
[[match_output.search_brain]]
pattern = "^\\[\\]$"          # empty JSON array
message = "No memories found."

[[match_output.get_context_tool]]
pattern = "no session"
message = "No session context available for this project."

[[match_output.reflect_tool]]
pattern = "nothing to consolidate"
message = "Reflection: corpus already consolidated, no new patterns detected."
```

**Why this matters for Claude's context:** Every empty result that returns `{"results": [],
"total": 0, "query": "...", "distances": []}` wastes ~30 tokens. At 50 empty searches per
session, that's 1500 tokens eliminated by a pattern check.

**Implementation complexity:** Very low. One `match` arm per tool before the existing
return logic.

---

## Technique 17 — SQLite Analytics Tracking with Per-Project Scope

**Source files:** `src/core/tracking.rs`, `src/analytics/gain.rs`

### What it does in RTK

Every command execution is recorded in a rusqlite database:

```rust
pub struct CommandRecord {
    pub command: String,
    pub raw_tokens: usize,       // tokens before filter
    pub filtered_tokens: usize,  // tokens after filter
    pub saved_tokens: usize,
    pub savings_pct: f64,
    pub execution_time_ms: u64,
    pub project: String,         // derived from cwd
    pub timestamp: i64,
}
```

90-day retention: `DELETE FROM commands WHERE timestamp < {cutoff}`.

Project scoping via SQLite GLOB: `WHERE project GLOB ?` (uses `%` wildcard for path
prefix matching — `/Users/x/Documents/AI%` matches all subpaths).

`GainSummary` aggregates across the time window: total_commands, total_saved,
avg_savings_pct, by_command breakdown, by_day trend.

`gain.rs` renders this as KPI display with `print_efficiency_meter()`:
```
Token savings ████████████████░░░░ 78% (12,450 tokens saved today)
```

### BRAIN application

BRAIN has zero retrieval analytics. Adding a `retrieval_log` table to `brain.db` mirrors
RTK's tracking schema exactly:

```sql
CREATE TABLE retrieval_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    query       TEXT NOT NULL,
    query_type  TEXT,           -- 'semantic' | 'hybrid' | 'bm25'
    project     TEXT,
    n_results   INTEGER,
    top_score   REAL,
    latency_ms  INTEGER,
    timestamp   INTEGER NOT NULL
);
```

Since BRAIN already uses rusqlite and has project scoping, this is a direct port of RTK's
schema. The `by_day` trend query becomes BRAIN's retrieval volume trend — useful for the
web viewer dashboard.

**The GLOB-based project scoping pattern** is directly applicable to BRAIN's queries.
BRAIN currently filters by exact project name. GLOB `WHERE project GLOB 'sakbe%'` would
match `sakbe`, `sakbe/module1`, `sakbe/v2` without changing the schema.

**KPI display** for `brain stats` command: show retrieval count, average latency, hit rate
(searches returning ≥ 3 results), top queried memory types.

**Implementation complexity:** Low. Schema migration (one new table), wrap `search_brain`
call with `TimedExecution::start()` / `timer.track()` pattern.

---

## Technique 18 — 4-Level Permission Verdict (Deny > Ask > Allow > Default)

**Source file:** `src/hooks/permissions.rs`

### What it does in RTK

```rust
pub enum PermissionVerdict { Allow, Deny, Ask, Default }
```

Precedence: `Deny > Ask > Allow > Default`.

For compound commands (`A && B && C`), RTK applies a critical rule: **every segment must
independently match an allow rule** for the chain to receive `Allow` verdict. If any
segment fails the allow check, the whole chain falls to `Ask`. This closed a CVE-class
bypass (issue #1213: previously a single allowed segment escalated the entire chain).

RTK reads Claude Code's own `settings.json` `allowedTools` rules and applies the same
Deny/Ask/Allow logic RTK uses for rewriting — a single source of truth.

### BRAIN application

BRAIN has no per-project memory access control. Some projects contain sensitive data
(medical context for MedDeFi, financial data for Wealth). A verdict system:

```rust
pub enum MemoryAccessVerdict { Allow, Redact, Deny, Default }
```

**Rules defined in `.brain/access.toml` per project:**
```toml
[projects.sakbe]
verdict = "allow"   # internal project, no restriction

[projects.meddefi]
verdict = "redact"  # strip PII fields before returning to Claude

[projects.wealth]
verdict = "ask"     # prompt user before surfacing financial memories cross-project
```

The **compound command lesson** applies directly: if a search spans multiple projects and
one of them has `verdict = "deny"`, the entire cross-project search result set must apply
the most-restrictive verdict, not just exclude the deny-project memories.

**Implementation complexity:** Medium. New config struct, verdict check in `search_brain`.

---

## Technique 19 — Mine Claude Code Session JSONL for Behavioral Signals

**Source file:** `src/learn/mod.rs`

### What it does in RTK

RTK's `learn` module scans all Claude Code session files:
```
~/.claude/projects/**/*.jsonl
```

For each session file, it extracts `CommandExecution` structs by parsing the JSONL messages.
`find_corrections()` identifies pairs where the user ran command A, then immediately ran
command B that looks like a correction of A (shorter, explicit, different flags). 
`deduplicate_corrections()` merges identical pairs across sessions.

Filtering: only patterns appearing `>= min_occurrences` times with `>= min_confidence`
confidence score are kept. The output is written to `.claude/rules/cli-corrections.md` —
a self-updating rules document Claude Code can read.

### BRAIN application

BRAIN already stores 1654 sessions as JSONL. The same mining pattern applies to memory quality:

**Signal 1 — False positive detection:** Find sessions where Claude retrieved memory M,
then the user immediately gave a correction or typed "that's wrong" / "not relevant" /
"ignore that". These are false-positive retrieval signals. Flag memory M's `importance`
downward.

**Signal 2 — Auto-relationship discovery:** Find pairs of memory IDs that are returned
together in the same retrieval across multiple sessions. High co-retrieval frequency → strong
candidate for a `memory_relationships` edge with type `RELATED`.

**Signal 3 — Query pattern mining:** Find the most common query strings that produced
zero results. These are BRAIN's "coverage gaps" — topics users ask about but BRAIN can't answer.
Surfaces concrete areas for targeted memory ingestion.

**Implementation path:**
```python
# brain/bootstrap/mine_session_signals.py
# Scan sessions_export/*.json
# Extract: (query, result_ids, user_feedback_in_next_turn)
# Output: false_positives.json, co_retrieval_pairs.json, coverage_gaps.json
```

This is a pure offline analytics script — no changes to live BRAIN. Runs periodically
(weekly) and writes signals back to `memories.importance` and `memory_relationships`.

**Implementation complexity:** Low-Medium. Offline Python script, no live system changes.

---

## Technique 20 — StreamFilter Trait for Low-Latency Progressive Emission

**Source file:** `src/core/stream.rs`

### What it does in RTK

RTK defines a `StreamFilter` trait for line-by-line processing:

```rust
pub trait StreamFilter {
    fn feed_line(&mut self, line: &str) -> Option<String>;   // process one line, maybe emit
    fn flush(&mut self) -> String;                            // emit buffered remainder
    fn on_exit(&mut self, exit_code: i32, raw: &str) -> Option<String>; // post-process
}
```

`BlockStreamFilter<H: BlockHandler>` handles block-level aggregation: detect block start,
accumulate continuation lines (e.g. a multi-line diff hunk), emit when block ends. This
pattern processes output as it streams — it does not buffer the entire output first.

`RunMode` enum: `Filtered(fn)` for batch, `Streamed(StreamFilter)` for progressive,
`Passthrough` for no transformation.

### BRAIN application

BRAIN's SSE `/v1/stream` endpoint already streams events to the web viewer. The `StreamFilter`
trait pattern would allow BRAIN's search results to emit **progressively** — high-confidence
memories appear in Claude's context immediately, before the full k-result set is scored:

```rust
// Progressive search: emit results as they pass threshold, don't wait for all k
impl StreamFilter for ProgressiveSearchFilter {
    fn feed_line(&mut self, memory_json: &str) -> Option<String> {
        let score = parse_score(memory_json);
        if score > self.threshold {
            Some(memory_json.to_string())  // emit immediately
        } else {
            None  // buffer, decide at flush
        }
    }
}
```

The `BlockStreamFilter` pattern is also applicable to BRAIN's session ingestion: process
session JSONL line-by-line rather than loading entire session files into memory. This is
relevant for very long sessions (100K+ token context exports).

**Implementation complexity:** Medium. New trait in `brain/rust/src/`, used in the MCP
search response path.

---

## Technique 21 — 3-Level Config Hierarchy with Compiled-In Defaults

**Source file:** `src/core/toml_filter.rs`

### What it does in RTK

Config resolution for filter files:
1. **Project-local** `.rtk/filters.toml` — checked first, overrides everything
2. **User global** `~/.config/rtk/filters.toml` — user-wide customizations
3. **Compiled-in defaults** — `include_str!("../../filters/terraform-plan.toml")` at compile time

Debug visibility: `RTK_TOML_DEBUG=1` prints which level was resolved.
Escape hatch: `RTK_NO_TOML=1` skips all file lookup, uses compiled-in defaults only.

The compiled-in defaults mean the binary works out-of-the-box with no config files
present — zero-friction first run.

### BRAIN application

BRAIN currently uses flat env vars for all config. A 3-level TOML config hierarchy would
enable per-project BRAIN behavior without env var juggling:

```
.brain/config.toml          ← project-local (overrides all)
~/.config/brain/config.toml ← user global
compiled-in defaults         ← via include_str!, works with no config files
```

Per-project config use cases:
- Project `meddefi`: `search_result_limit = 3` (sensitive data, less surface area)
- Project `AI`: `search_result_limit = 15` (heavy research project, more context)
- Project `sakbe`: `default_memory_type = "decision"` (architecture-heavy project)

The `include_str!` pattern ensures the Rust binary has working defaults at compile time —
no runtime file I/O required on first use.

**Implementation complexity:** Low. New `Config::load()` function with 3-level lookup.
Add `config.rs` to `brain/rust/src/`. Wire into existing env var reads as fallback.

---

## Technique 22 — Category-Based Token Budget Estimation

**Source file:** `src/discover/registry.rs` (`category_avg_tokens()`)

### What it does in RTK

Before execution, RTK can estimate token savings using a lookup table:

```rust
pub fn category_avg_tokens(category: &str, subcmd: &str) -> usize {
    match category {
        "Git" => match subcmd { "log" | "diff" | "show" => 200, _ => 40 },
        "Cargo" => match subcmd { "test" => 500, _ => 150 },
        "Tests" => 800,
        "Build" => 300,
        _ => 150,
    }
}
```

This lookup is used in the `gain` analytics display when no measured output is available
yet. No LLM call, no measurement — pure empirical lookup table.

### BRAIN application

BRAIN has no pre-retrieval token budget awareness. A similar lookup for MCP tools:

```rust
pub fn estimated_response_tokens(tool: &str, n_results: usize) -> usize {
    let per_result = match tool {
        "search_brain"           => 150,  // avg memory content
        "get_observations_tool"  => 400,  // full observation text
        "get_context_tool"       => 600,  // session context chunk
        "timeline_tool"          => 100,  // compact timeline entry
        _                        => 200,
    };
    per_result * n_results
}
```

Use this in two places:
1. **Pre-retrieval cap**: if `estimated_response_tokens(tool, n) > budget`, auto-reduce `n`
2. **Web viewer**: show estimated token cost per search in the UI before executing

This prevents a `get_observations_tool(ids=[...50 ids...])` call from consuming the entire
Claude context window silently.

**Implementation complexity:** Very low. Pure lookup table, 10 lines.

---

## Technique 23 — Audit Log with Log-Injection Prevention

**Source file:** `src/hooks/hook_cmd.rs` (`sanitize_log_field()`)

### What it does in RTK

RTK's audit log uses pipe-delimited format:
```
2026-04-26T14:32:01 | rewrite | git status | rtk git status
```

Before writing any field, `sanitize_log_field()` escapes delimiters and control characters:
```rust
fn sanitize_log_field(s: &str) -> String {
    s.replace('\\', "\\\\")
     .replace('|', "\\|")
     .replace('\n', "\\n")
     .replace('\r', "\\r")
}
```

This prevents log-injection attacks where a malicious command string could forge additional
log fields. The tests explicitly cover this case.

### BRAIN application

BRAIN's memory content frequently contains pipe characters, newlines, code blocks, and
backslashes. Any structured log, audit trail, or export format that BRAIN writes is
vulnerable to the same injection if content fields are not sanitized.

Specifically: `sessions_export/*.json`, the `retrieval_log` table (Technique 17), and
any future CSV/TSV export of memories. Apply the same sanitization pattern:

```rust
fn sanitize_memory_field(s: &str) -> String {
    s.replace('\\', "\\\\")
     .replace('\t', "\\t")   // for TSV exports
     .replace('\n', "\\n")   // for single-line log entries
     .replace('\r', "\\r")
}
```

Also applies to BRAIN's web viewer: memory content displayed in the SSE stream should
be JSON-encoded (already is), but any server-side log of SSE events should sanitize.

**Implementation complexity:** Trivial. One utility function, applied to export paths.

---

## Updated Full Implementation Roadmap

| Priority | Technique | Source | Effort | Impact | Status |
|---|---|---|---|---|---|
| 1 | Mean-centering embeddings | OpenBMI | Low | Medium | — |
| 2 | **RRF hybrid search (BM25 + cosine)** | GitNexus | Low | **Highest** | ✅ Phase 1 (alpha-weighted hybrid in `brain_api`) |
| 3 | k-fold retrieval evaluation (precision@k) | OpenBMI | Low | Enables measurement | ✅ Phase 6 (`--facts-only`, `facts_queries.jsonl`) |
| 4 | `task_context` + `goal` in search queries | GitNexus | Low | Medium | — |
| 5 | **`match_output` short-circuit on empty MCP results** | **RTK** | Low | Medium | — |
| 6 | **Category-based token budget estimation** | **RTK** | Low | Medium | — |
| 7 | **3-level config hierarchy (.brain/config.toml)** | **RTK** | Low | Medium | — |
| 8 | **Human-centric memory taxonomy (identity/preferences/relationships/wishes)** | **Mark-XXXV** | Low | **High** | — |
| 9 | RLDA + Ledoit-Wolf projection on embeddings | OpenBMI | Medium | High | — |
| 10 | **SQLite `retrieval_log` table (per-query analytics)** | **RTK** | Medium | Medium | — |
| 11 | PyOD outlier detection → importance scores | awesome-ml | Medium | Medium | — |
| 12 | Dedupe semantic deduplication pass | awesome-ml | Medium | Medium | — |
| 13 | Multi-factor importance scoring | GitNexus | Medium | Medium | — |
| 14 | **Graph relationships (`memory_relationships` table)** | GitNexus | Medium | High | ✅ Phase 7 (`event_time.unwrap_or(timestamp)` in decay) |
| 15 | **Leiden community detection on co-occurrence graph** | GitNexus | Medium | High | — |
| 16 | Per-type FTS indexes with top-3 merge | GitNexus | Medium | Medium | — |
| 17 | Semantic chunking for book/Obsidian ingestion | GitNexus | Medium | Medium | — |
| 18 | **PostToolUse hook: compress command output inline** | **RTK** | Medium | High | ✅ Phase 2 (3-tier cosine gate: <0.78 auto-ADD, 0.78–0.92 LLM, >0.92 auto-IGNORE) |
| 19 | **Mine session JSONL for false-positive + co-retrieval signals** | **RTK** | Medium | Medium | ✅ Phase 6 (salience stored; beta=0.0, no signal at current calibration) |
| 20 | **StreamFilter trait for progressive MCP result emission** | **RTK** | Medium | Medium | — |
| 21 | **4-level memory access verdict per project** | **RTK** | Medium | Medium | — |
| 22 | **Per-turn 2-stage extraction hook (YES/NO → full extract)** | **Mark-XXXV** | Medium | Medium | ✅ Phase 4 (`superseded_by` + `exclude_superseded` default true) |
| 23 | linfa Rust port of LDA/KMeans | awesome-ml | High | High | — |
| 24 | shimmy / rust-bert → eliminate Python embedder | awesome-ml | High | High | — |
| 25 | HNSW via usearch (when corpus > 30K) | GitNexus + awesome-ml | High | Low now | ✅ Phase 3 (`backfill_facts.py` per-source checkpoint JSON) |

---

---

---

# Research Source 5 — Mark-XXXV

> https://github.com/FatihMakes/Mark-XXXV
> Python. JARVIS-style voice AI assistant on Windows (Gemini 2.5 Flash native audio).
> Source analyzed: `memory/memory_manager.py`, `main.py` (tool declarations, memory async loop).

## What Mark-XXXV is

A real-time voice assistant built on Gemini's native audio streaming API. 20+ action modules
(browser control, file system, app launcher, game updater, flight finder, etc.). Designed for
autonomous multi-step task execution. The architecturally interesting part is its **memory system**.

| Mark-XXXV concept | BRAIN equivalent |
|---|---|
| `long_term.json` flat file store | SQLite `memories` table |
| 6 human-centric categories | 6 code/project-centric `memory_type` values |
| Per-turn 2-stage LLM extraction | Session-start/end hook ingestion |
| `format_memory_for_prompt()` | `get_context_tool` MCP response |
| Async extraction thread | PostToolUse hook binary |

**Core gap surfaced:** BRAIN captures code solutions, decisions, and project context with
high fidelity. It captures almost nothing about **the user as a person** — preferences,
goals, relationships, identity facts. Mark-XXXV's memory is purpose-built for exactly that.

---

## Technique 24 — Human-Centric Memory Taxonomy

**Source file:** `memory/memory_manager.py` — `_empty_memory()`, `extract_memory()`

### What it does in Mark-XXXV

All extracted facts are bucketed into 6 human-centric categories:

```python
def _empty_memory() -> dict:
    return {
        "identity":      {},   # name, age, city, job, language, birthday
        "preferences":   {},   # favorite_food, hobby, favorite_music, dislikes, etc.
        "projects":      {},   # ongoing work, goals, ideas in progress
        "relationships": {},   # friends, family, partner, colleagues
        "wishes":        {},   # future plans, things to buy, travel dreams
        "notes":         {}    # habits, schedule, anything else
    }
```

The LLM extraction prompt is deliberately **liberal**: "if something MIGHT be worth
remembering, include it." Values are capped at 400 chars and stored with an `updated` date:

```python
entry = {"value": "acoustic guitar", "updated": "2026-04-29"}
```

The `remember(key, value, category)` and `forget(key, category)` functions let the
assistant manually add/remove facts at runtime.

### BRAIN gap

BRAIN's `memory_type` values are: `solution`, `project_context`, `conversation`,
`pattern`, `error`, `decision`. All 6 are project/code-centric. There is no first-class
type for:
- Who the user is (`identity`)
- What they like or prefer (`preferences`)
- What they want to accomplish outside of code (`wishes`)
- Who they work and live with (`relationships`)

The auto-memory system in `~/.claude/projects/…/memory/` partially covers this, but it's
flat markdown, not semantically searchable via `search_brain`.

### BRAIN application

Add human-centric memory types to the brain schema. Minimal schema change — just new
`memory_type` values for the existing `memories` table, with a dedicated extraction
hook for personal facts:

```python
HUMAN_MEMORY_TYPES = {
    "identity",      # name, role, timezone, language, background
    "preference",    # tools, workflows, aesthetics, dislikes
    "goal",          # personal goals, plans, things to build or buy
    "relationship",  # clients, collaborators, family — who the user mentions
}
```

**Why adding to brain (not just MEMORY.md):** These facts become semantically searchable.
"Does this user have experience with X?" can be answered by `search_brain(query="user background X")`.
Flat MEMORY.md can't do that at scale.

**Extraction trigger:** When the session stop hook fires, run a single LLM call that scans
the session for personal facts using the same liberal prompt pattern Mark-XXXV uses.
Output is saved as `memory_type=identity|preference|goal|relationship` memories.

**Implementation complexity:** Low. New memory types (no schema change needed — just new
values for the existing `type` column), plus a targeted extraction step in the stop hook.

---

## Technique 25 — Two-Stage Per-Turn Memory Extraction

**Source file:** `memory/memory_manager.py` — `should_extract_memory()` + `extract_memory()`
**Integration point:** `main.py` — `_update_memory_async()` called after every AI response

### What it does in Mark-XXXV

After every conversation turn, a background thread checks whether the exchange contains
anything worth saving — before the next turn starts:

```python
def _update_memory_async(user_text: str, jarvis_text: str) -> None:
    if not should_extract_memory(user_text, jarvis_text, api_key):
        return                         # Stage 1: fast YES/NO, ~50ms
    data = extract_memory(...)         # Stage 2: full extraction, ~200ms
    if data:
        update_memory(data)
```

**Stage 1 — YES/NO check** (`gemini-2.5-flash-lite`, 300-char truncated input):
"Does this contain ANY personal fact, preference, project, relationship, plan, or anything
worth remembering long-term?" → `YES` or `NO` only.

**Stage 2 — Full extraction** (only on YES): structured JSON extraction into all 6 categories.

Two-stage design means: most turns spend ~50ms on Stage 1 and return. Only turns with
personal facts pay the full ~250ms extraction cost.

### BRAIN gap

BRAIN's memory extraction fires only at:
- `SessionStart`: context injection from past sessions
- `SessionEnd` (stop hook): bulk session summarization

Personal facts shared mid-session ("by the way, I prefer TypeScript over JS") are only
captured if the stop hook's bulk summarizer happens to surface them. The stop hook
processes the entire session as one blob — it optimizes for decisions and solutions,
not personal preferences.

### BRAIN application

Add a `PostToolUse` hook for the `mcp__brain` tools (or for every assistant message) that
runs the same 2-stage check. The existing `brain_user_prompt_submit` hook fires on user
messages; add a complementary hook on responses.

```python
# brain/bootstrap/brain_post_turn.py  (new PostToolUse or PostResponse hook)
# Reads: last user turn + last assistant turn from transcript JSONL
# Stage 1: single LLM call → YES/NO  (use cheapest available model)
# Stage 2: if YES → extract into human-centric types (Technique 24 types)
# Output: save_memory_tool for each extracted fact
```

**Key pattern from Mark-XXXV:** The Stage 1 check uses a very cheap model. Don't use the
same model for YES/NO as for full extraction. For BRAIN: Stage 1 → `claude-haiku-4-5`,
Stage 2 → `claude-sonnet-4-6`.

**Dedup guard:** Mark-XXXV tracks `_last_memory_input` to skip re-processing the same user
text twice. BRAIN should use the `content` hash of the last processed turn as a skip guard.

**Implementation complexity:** Medium. New hook binary (`brain_post_turn.py`), registered in
`~/.claude/settings.json` under `postToolUse` (or a scheduled check at session intervals).
No changes to brain core or MCP server.

---

## Technique 26 — Structured Memory Prompt Formatting

**Source file:** `memory/memory_manager.py` — `format_memory_for_prompt()`

### What it does in Mark-XXXV

Before injecting memory into the Gemini system prompt, the entire `long_term.json` is
formatted into a human-readable, section-structured block:

```python
header = "[WHAT YOU KNOW ABOUT THIS PERSON — use naturally, never recite like a list]\n"

# Identity fields always first (name, age, city, job, language)
# Then: Preferences (up to 15), Projects (up to 8), People (up to 10),
#       Wishes (up to 8), Other notes (up to 8)
# Hard cap: 2000 chars total, truncated with "…"
```

**Design decisions worth copying:**
- Identity fields are hardcoded first — name/job/city are always at the top
- Each section has a **per-category cap** (15 prefs, 8 projects, 10 relationships)
  — the most recent/important survive, old ones don't bloat the prompt
- The header instruction ("use naturally, never recite like a list") prevents the AI
  from robotically listing memory facts instead of weaving them into responses
- 2000-char hard cap means memory injection is always a known bounded cost

### BRAIN gap

`get_context_tool` returns raw memory content blobs. The format is whatever the memory's
`content` field contains — no structure, no category grouping, no injection hints, no cap.
When personal fact types (Technique 24) exist, they need a different formatting pass than
code solutions: a solution memory should be presented as "here's what you decided before",
a preference memory as "here's what this person likes", a relationship memory as "here's
who this person mentioned."

### BRAIN application

Add a `format_personal_context(memories)` path in `get_context_tool` (or as a separate
`get_user_context_tool` MCP tool) that applies the same structure:

```python
def format_personal_context(memories: list[Memory]) -> str:
    identity    = [m for m in memories if m.type == "identity"]
    preferences = [m for m in memories if m.type == "preference"]
    goals       = [m for m in memories if m.type == "goal"]
    relations   = [m for m in memories if m.type == "relationship"]

    sections = []
    if identity:
        sections.append("About this person:\n" + "\n".join(f"  {m.content}" for m in identity[:5]))
    if preferences:
        sections.append("Preferences:\n" + "\n".join(f"  - {m.content}" for m in preferences[:10]))
    if goals:
        sections.append("Goals / Plans:\n" + "\n".join(f"  - {m.content}" for m in goals[:5]))
    if relations:
        sections.append("People they mention:\n" + "\n".join(f"  - {m.content}" for m in relations[:8]))

    if not sections:
        return ""

    header = "[USER CONTEXT — weave into responses naturally, don't recite]\n"
    result = header + "\n\n".join(sections)
    return result[:2000]
```

The per-category cap prevents any one noisy category (e.g. 40 goal entries) from
crowding out the others. The instruction header shapes how the LLM uses the context.

**Implementation complexity:** Low. New formatting function in `brain/mcp/server.py` or a
new MCP tool. No schema changes. Activated only when human-centric types (T24) are present.

---

---

---

---

# Research Source 6 — SocraticSkill

> https://github.com/VicBa2000/socratiskill
> TypeScript Claude Code plugin. Version 0.3.0. Full source analyzed: `scripts/record-turn.ts`,
> `scripts/pick-review.ts`, `scripts/detector.ts`, `scripts/state-io.ts`, `scripts/antipatterns.ts`,
> `scripts/build-journal.ts`, `skills/socratic/rule.md`, `data/domains.json`, `data/algorithm.json`,
> `data/technical-terms.json`. MIT license. Author: Victor Barrantes.

## What SocraticSkill is

A Claude Code plugin that transforms Claude into an adaptive Socratic coding tutor. It never
solves problems directly — it scaffolds discovery through hint ladders, Feynman technique
enforcement, and a 5-level proficiency system. The architecturally interesting part is its
**state tracking layer**: how it records what the user knows, when they last engaged with a topic,
and how trustworthy their demonstrated knowledge is.

| SocraticSkill concept | BRAIN equivalent |
|---|---|
| User proficiency per topic | Memory importance per domain |
| Leitner review intervals [1,3,7,14,30] | Memory resurfacing cadence |
| Correctness tracking (right/wrong per turn) | Retrieval feedback (used/ignored/corrected) |
| Knowledge gap detection (unfamiliar signals) | Coverage gap detection (zero-result queries) |
| 7 domain taxonomy (fundamentals → advanced) | `project` + `memory_type` categorization |
| Copy-paste heuristics (authenticity scoring) | Memory trust scoring from retrieval outcomes |
| Learning journal (daily/weekly aggregation) | Timeline tool + reflect tool |
| Atomic write (staging file + rename) | Already implemented in Rust `store.rs` |

**Core gap surfaced:** BRAIN's retrieval ranks by semantic similarity alone. A memory from
18 months ago with cosine=0.91 beats a memory from last week with cosine=0.89. There is no
recency decay, no resurfacing cadence for important-but-old memories, and no trust signal
that distinguishes a reliable memory from one Claude has been correcting repeatedly.

---

## Technique 27 — Spaced Repetition for Memory Resurfacing (Leitner System)

**Source files:** `scripts/pick-review.ts`, `data/algorithm.json`

### What it does in SocraticSkill

Every topic a user engages with gets a Leitner card with a `box` (1–5) and a `nextReview`
timestamp. Correct answers advance the box (longer interval); wrong answers reset to box 1:

```typescript
const LEITNER_INTERVALS = [1, 3, 7, 14, 30]; // days per box

function advanceCard(card: LeitnerCard, correct: boolean): LeitnerCard {
    if (correct) {
        card.box = Math.min(card.box + 1, LEITNER_INTERVALS.length);
    } else {
        card.box = 1;  // reset on failure
    }
    card.nextReview = addDays(now(), LEITNER_INTERVALS[card.box - 1]);
    return card;
}
```

`pick-review.ts` selects topics where `nextReview <= now()` — only cards due for review
surface, regardless of how semantically close they are to the current query.

### BRAIN gap

BRAIN's injection logic: top-5 by cosine similarity. A memory accessed daily stays near
the top because it keeps getting retrieved and reinforced. A memory that was critical 3 months
ago but hasn't been queried since is silently buried by newer memories, even if it remains
highly relevant to future sessions.

**Real scenario:** Architecture decision made in January. New session in April about the same
system. The January decision memory has cosine=0.88 but 2,400 newer memories have slightly
higher scores. It doesn't surface. The decision gets re-made or contradicted unknowingly.

### BRAIN application

Add a `leitner_box` and `next_review_at` column to the `memories` table. After each retrieval,
advance the card. When the card is NOT retrieved despite being semantically relevant, decay
the box. At session start, inject any memories where `next_review_at <= now()` as a
**forced-surface** set alongside the top-5 cosine results:

```sql
-- New columns (schema migration)
ALTER TABLE memories ADD COLUMN leitner_box INTEGER DEFAULT 1;
ALTER TABLE memories ADD COLUMN next_review_at TEXT;    -- ISO timestamp
ALTER TABLE memories ADD COLUMN last_retrieved_at TEXT; -- ISO timestamp
```

```rust
// In brain/rust/src/brain.rs — after search(), update the returned memories
fn update_leitner_after_retrieval(ids: &[&str], db: &Store) {
    let intervals = [1, 3, 7, 14, 30]; // days
    for id in ids {
        let card = db.get_leitner(id);
        let next_box = (card.leitner_box + 1).min(5);
        let next_review = Utc::now() + Duration::days(intervals[next_box - 1] as i64);
        db.set_leitner(id, next_box, next_review);
    }
}

// At session start, merge forced-surface memories with cosine results
fn get_context_with_spaced_repetition(query: &str, n: usize, db: &Store) -> Vec<Memory> {
    let due_for_review = db.get_memories_due_for_review(Utc::now(), 3); // up to 3 forced
    let cosine_results = search(query, n - due_for_review.len());
    merge_dedup(due_for_review, cosine_results)
}
```

**Decay path:** A memory that should have surfaced (high cosine) but didn't get retrieved
should have its box decremented on the next reflect cycle — the Leitner "wrong answer"
equivalent. The reflect tool is the right place to run box decay.

**Expected impact:** Important old memories resurface on schedule regardless of corpus growth.
Solves the "buried by recency" problem identified as gap (a).

**Implementation complexity:** Low-Medium. Schema migration (3 columns), update-after-retrieval
logic in `brain.rs`, forced-surface merge in session start hook. No changes to embedding or
index infrastructure.

---

## Technique 28 — Memory Trust Scoring from Retrieval Feedback

**Source files:** `scripts/record-turn.ts`, `data/algorithm.json` (calibration thresholds)

### What it does in SocraticSkill

After every turn, `record-turn.ts` records whether the user's answer was correct, incorrect,
or a knowledge gap admission. Over time, a topic's trust is the ratio of correct responses
to total attempts, weighted by recency:

```typescript
interface TopicRecord {
    topic: string;
    correct: number;
    incorrect: number;
    lastAttempt: string;  // ISO date
    box: number;          // Leitner box
}

// Calibration: down-level if 3 wrong in last 5 attempts (uniform threshold)
// Up-level: progressive threshold (beginners: 10/12 correct; advanced: 5/7)
```

The asymmetric calibration is key: demoting is fast (3/5 wrong), promoting is slow and
scaled to level. "Being stuck above your level is worse than being stuck below it."

**Copy-paste heuristics** add a trust signal from a different angle:
- Sophisticated code block at Level 1 proficiency → flag as possibly inauthentic
- Message length jumps 5× → suspicious (pasting external solution)
- Technical vocabulary inconsistency → authenticity score degrades

This produces a `trust_score` per topic — not just "how often right" but "how authentic."

### BRAIN gap

BRAIN's `feedback_event_v1.json` schema exists and `record_feedback` MCP tool exists, but
feedback events are not systematically converted into a trust signal on `memories.importance`.
The feedback schema is:

```json
{"memory_id": "...", "feedback_type": "positive|negative|correction", "session_id": "..."}
```

But `memories.importance` stays at `0.5` for everything — feedback is logged but not applied.

### BRAIN application

Implement a `trust_score` computed from feedback events and applied to `memories.importance`
at reflect time. Mirror SocraticSkill's asymmetric calibration: trust degrades fast (3 negative
signals), trust builds slow (requires consistent positive signals):

```rust
// In brain/rust/src/brain.rs — called during reflect cycle
fn recompute_trust_scores(db: &Store) {
    let window = 90; // days of feedback to consider
    let feedbacks = db.get_recent_feedbacks(window);

    for (memory_id, events) in feedbacks.group_by_memory() {
        let positives = events.iter().filter(|e| e.kind == "positive").count();
        let negatives = events.iter().filter(|e| e.kind == "negative" || e.kind == "correction").count();
        let total = positives + negatives;

        if total == 0 { continue; }

        // Asymmetric calibration: fast decay, slow build
        let raw_trust = if negatives >= 3 && total <= 5 {
            0.2  // demote fast: 3+ negatives in ≤5 events
        } else {
            (positives as f32) / (total as f32)
        };

        // Blend with existing importance (don't override cold-start memories)
        let current = db.get_importance(memory_id);
        let new_importance = 0.3 * current + 0.7 * raw_trust;
        db.set_importance(memory_id, new_importance);
    }
}
```

**Trust signal sources** (in priority order):
1. Explicit `record_feedback` calls (highest signal — Claude was explicitly corrected)
2. Session JSONL mining: user correction patterns after a retrieval (Technique 19 from RTK)
3. Leitner box position: box 5 memory that never gets corrected → trust=high

**Result:** `memories.importance` becomes a real signal. Retrieval re-ranking uses it:
`final_score = rrf_score * (0.6 + 0.4 * importance)` — reliable memories float up,
repeatedly-wrong memories sink even if semantically close.

**Implementation complexity:** Medium. New `recompute_trust_scores()` in reflect cycle,
`importance`-weighted re-ranking in `brain.rs` search path.

---

## Technique 29 — Coverage Gap Detection and Surfacing

**Source file:** `scripts/detector.ts` — `detectKnowledgeGap()`

### What it does in SocraticSkill

`detector.ts` scans each user turn for 26 zero-knowledge signals in English and Spanish:

```typescript
const ZERO_KNOWLEDGE_PATTERNS = [
    /\bi('?ve)? never (used|tried|worked with)\b/i,
    /\bi don'?t know (what|how|why|if)\b/i,
    /\bno (tengo|sé|entiendo)\b/i,  // Spanish equivalents
    /\bcan you explain (what|how|why)\b/i,
    // ... 22 more patterns
];
```

When a gap is detected, the topic is logged. The `build-journal.ts` aggregates these into
a "struggled" category in the weekly learning journal. The Socratic skill uses gap logs to
target its next hint ladder — "you admitted not knowing X, let's cover X next."

### BRAIN gap

BRAIN logs zero-result queries nowhere. When `search_brain(query="topic X")` returns 0
results, that's a coverage gap — the brain has no memory of X. These gaps accumulate silently.
The RTK Technique 19 partially addresses this (mine session JSONL for zero-result patterns)
but is offline-only. There is no online detection or periodic surfacing to the user.

### BRAIN application

Add online coverage gap detection in the MCP search path: when a search returns 0 results
(or < 2 results below the minimum score threshold), log the query to a `coverage_gaps` table:

```sql
CREATE TABLE coverage_gaps (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    query       TEXT NOT NULL,
    project     TEXT,
    result_count INTEGER NOT NULL,
    top_score   REAL,              -- NULL if no results
    timestamp   INTEGER NOT NULL,
    resolved    INTEGER DEFAULT 0  -- 1 once memory is added for this topic
);
```

```rust
// In brain/rust/src/brain.rs — after search()
fn maybe_log_coverage_gap(query: &str, results: &[Memory], project: &str, db: &Store) {
    let is_gap = results.is_empty() || results[0].score < 0.35;
    if is_gap {
        db.log_coverage_gap(query, project, results.len(), results.first().map(|r| r.score));
    }
}
```

**Surfacing:** Add a `get_coverage_gaps(project?, limit?)` MCP tool that returns the top N
unresolved gaps sorted by frequency. Run as part of the weekly reflect cycle output. The user
then knows which topics to ingest targeted content for.

**Gap resolution:** When a new memory is saved for a topic matching a logged gap query,
mark it as `resolved=1` (fuzzy match on query text using FTS5).

**Expected impact:** Brain becomes self-aware of what it doesn't know. Targeted ingestion
replaces guesswork about what's missing.

**Implementation complexity:** Low. New table, 1 check in search path, 1 new MCP tool.

---

## Technique 30 — Domain-Weighted Retrieval Taxonomy

**Source files:** `data/domains.json`, `data/technical-terms.json`

### What it does in SocraticSkill

Seven knowledge domains, each with keyword lists. At every turn, the topic is classified
into one or more domains using case-insensitive keyword matching with word-boundary guards
(to prevent "react" from matching "reaction"):

```json
{
  "fundamentals":     { "keywords": ["variable", "loop", "function", "algorithm", ...] },
  "languages":        { "keywords": ["python", "javascript", "typescript", "rust", ...] },
  "paradigms":        { "keywords": ["oop", "functional", "async", "reactive", ...] },
  "web":              { "keywords": ["html", "css", "dom", "fetch", "component", ...] },
  "backend":          { "keywords": ["api", "rest", "graphql", "database", "sql", ...] },
  "infrastructure":   { "keywords": ["docker", "kubernetes", "ci/cd", "terraform", ...] },
  "advanced":         { "keywords": ["compiler", "garbage collection", "concurrency", ...] }
}
```

`technical-terms.json` extends this with 40+ specific terms tracked per domain for
vocabulary authenticity detection.

### BRAIN gap

BRAIN classifies memories by `memory_type` (solution/decision/conversation/etc.) and
`project`. Neither dimension captures *what domain* the memory is about. A Rust concurrency
solution and a CSS layout solution are both `type=solution, project=AI`. At retrieval time,
domain context is invisible.

When a user asks about Docker deployment, BRAIN returns the 5 closest embeddings — which
may mix infrastructure memories with backend API memories that happen to use similar language.
No domain pre-filtering exists.

### BRAIN application

Add domain classification at ingest time using a lightweight keyword classifier (no LLM
needed — the SocraticSkill approach works):

```rust
// In brain/rust/src/symbols.rs — extend with domain classification
const DOMAINS: &[(&str, &[&str])] = &[
    ("infrastructure", &["docker", "kubernetes", "terraform", "nginx", "deploy", "ci/cd"]),
    ("backend",        &["api", "rest", "graphql", "sql", "database", "endpoint", "server"]),
    ("frontend",       &["html", "css", "react", "vue", "component", "dom", "tailwind"]),
    ("systems",        &["rust", "memory", "concurrency", "thread", "async", "ownership"]),
    ("ml",             &["embedding", "model", "training", "inference", "vector", "llm"]),
    // ...
];

fn classify_domain(content: &str) -> Option<String> {
    let lower = content.to_lowercase();
    DOMAINS.iter()
        .max_by_key(|(_, kws)| kws.iter().filter(|kw| lower.contains(*kw)).count())
        .and_then(|(domain, kws)| {
            let hits = kws.iter().filter(|kw| lower.contains(*kw)).count();
            if hits >= 2 { Some(domain.to_string()) } else { None }
        })
}
```

Store in `memories.domain` (new column). At retrieval time, when the query is classified
into a domain, apply a soft boost to memories in the same domain:

```rust
// Re-rank: boost same-domain memories by 10%
let query_domain = classify_domain(query);
for result in &mut results {
    if Some(&result.domain) == query_domain.as_ref() {
        result.score *= 1.10;
    }
}
```

**Downstream uses:**
- Web viewer: group memories by domain, not just project
- Reflect: target reflection within a single domain (not globally across all types)
- Coverage gaps (T29): surface gaps by domain — "no infrastructure memories for project sakbe"

**Implementation complexity:** Low. One new `domain` column, keyword classifier in Rust
(no external deps), soft boost in search re-ranking.

---

## Updated Full Implementation Roadmap (all sources)

| Priority | Technique | Source | Effort | Impact | Status |
|---|---|---|---|---|---|
| 1 | Mean-centering embeddings | OpenBMI | Low | Medium | — |
| 2 | **RRF hybrid search (BM25 + cosine)** | GitNexus | Low | **Highest** | ✅ Phase 1 (alpha-weighted hybrid in `brain_api`) |
| 3 | k-fold retrieval evaluation (precision@k) | OpenBMI | Low | Enables measurement | ✅ Phase 6 (`--facts-only`, `facts_queries.jsonl`) |
| 4 | `task_context` + `goal` in search queries | GitNexus | Low | Medium | — |
| 5 | `match_output` short-circuit on empty MCP results | RTK | Low | Medium | — |
| 6 | Category-based token budget estimation | RTK | Low | Medium | — |
| 7 | 3-level config hierarchy (.brain/config.toml) | RTK | Low | Medium | — |
| 8 | Human-centric memory taxonomy (identity/preferences/relationships/wishes) | Mark-XXXV | Low | High | — |
| 9 | Domain-weighted retrieval taxonomy | SocraticSkill | Low | Medium | — |
| 10 | Coverage gap detection and surfacing | SocraticSkill | Low | Medium | — |
| 11 | **Asymmetric embedding prefixes (search_query: / search_document:)** | **SocratiCode** | Low | **High** | — |
| 12 | **Recency-weighted RRF** | **SocratiCode** | Low | High | — |
| 13 | RLDA + Ledoit-Wolf projection on embeddings | OpenBMI | Medium | High | — |
| 14 | SQLite `retrieval_log` table (per-query analytics) | RTK | Medium | Medium | ✅ Phase 7 (`event_time.unwrap_or(timestamp)` in decay) |
| 15 | PyOD outlier detection → importance scores | awesome-ml | Medium | Medium | — |
| 16 | Dedupe semantic deduplication pass | awesome-ml | Medium | Medium | — |
| 17 | Multi-factor importance scoring | GitNexus | Medium | Medium | — |
| 18 | Spaced repetition (Leitner) for memory resurfacing | SocraticSkill | Medium | High | ✅ Phase 2 (3-tier cosine gate: <0.78 auto-ADD, 0.78–0.92 LLM, >0.92 auto-IGNORE) |
| 19 | Memory trust scoring from retrieval feedback | SocraticSkill | Medium | High | ✅ Phase 6 (salience stored; beta=0.0, no signal at current calibration) |
| 20 | **Memory type staleness TTL** | **SocratiCode** | Medium | Medium | — |
| 21 | **Hub memory detection (impact radius)** | **SocratiCode** | Medium | High | — |
| 22 | **Pinned context artifacts (sacred memory tier)** | **SocratiCode** | Medium | High | ✅ Phase 4 (`superseded_by` + `exclude_superseded` default true) |
| 23 | **Fire-and-forget async ingest with checkpoint resumability** | **SocratiCode** | Medium | Medium | — |
| 24 | Graph relationships (`memory_relationships` table) | GitNexus | Medium | High | — |
| 25 | Leiden community detection on co-occurrence graph | GitNexus | Medium | High | ✅ Phase 3 (`backfill_facts.py` per-source checkpoint JSON) |
| 26 | Per-type FTS indexes with top-3 merge | GitNexus | Medium | Medium | — |
| 27 | Semantic chunking for book/Obsidian ingestion | GitNexus | Medium | Medium | — |
| 28 | PostToolUse hook: compress command output inline | RTK | Medium | High | — |
| 29 | Mine session JSONL for false-positive + co-retrieval signals | RTK | Medium | Medium | — |
| 30 | StreamFilter trait for progressive MCP result emission | RTK | Medium | Medium | ✅ Phase 2 (`fts_search_facts` separate FTS path for facts) |
| 31 | 4-level memory access verdict per project | RTK | Medium | Medium | — |
| 32 | Per-turn 2-stage extraction hook (YES/NO → full extract) | Mark-XXXV | Medium | Medium | — |
| 33 | linfa Rust port of LDA/KMeans | awesome-ml | High | High | — |
| 34 | shimmy / rust-bert → eliminate Python embedder | awesome-ml | High | High | — |
| 35 | HNSW via usearch (when corpus > 30K) | GitNexus + awesome-ml | High | Low now | — |

---

---

---

---

# Research Source 7 — SocratiCode

> https://github.com/giancarloerra/SocratiCode
> TypeScript MCP server. Version 1.7.2 (released 2026-04-28, 4 months active development).
> Full source analyzed: `src/index.ts`, `src/config.ts`, `src/constants.ts`, `src/types.ts`,
> all 36 modules in `src/services/`, all 5 modules in `src/tools/`, `docker-compose.yml`,
> `DEVELOPER.md`, `CHANGELOG.md`. 765 tests. AGPL-3.0 + commercial license.
> Author: Giancarlo Erra.

## What SocratiCode is

A production-grade **semantic + lexical codebase intelligence MCP server**. It indexes any
polyglot codebase (18+ languages via ast-grep), builds symbol-level call graphs, detects
circular dependencies, calculates blast radius for refactoring, and exposes everything as
21 MCP tools to AI assistants.

Key claim: 61% less context consumption and 84% fewer tool calls vs. built-in code search,
37× faster retrieval.

| SocratiCode concept | BRAIN equivalent |
|---|---|
| Code file chunks → Qdrant | Memory content → SQLite + vector index |
| BM25 + dense RRF hybrid search | `search_brain` (dense only today) |
| `search_query:` / `search_document:` prefixes | Raw content embeddings (no task framing) |
| Symbol call graph (sharded, lazy-loaded) | Memory co-occurrence graph (doesn't exist yet) |
| Content-hash staleness per file | Memory hash (doesn't exist — always re-embeds) |
| Context artifacts (pinned non-code docs) | No equivalent — all memories are equal tier |
| Async indexing + `codebase_status` poll | Blocking ingest scripts |
| LRU symbol payload cache | Flat in-memory vector index |
| File watcher → incremental update | No live watching — manual ingest only |
| `unresolvedEdgePct` quality signal | `memories.importance` stuck at 0.5 |

**Core novel findings:** SocratiCode is the most mature and production-tested system analyzed
so far. Its novel contributions are: (1) asymmetric task-specific embedding prefixes that
measurably improve retrieval, (2) sharded lazy-loaded indices that bound memory usage as
corpus scales, (3) the concept of a sacred "context artifacts" tier separate from regular
indexed content, and (4) recency-aware RRF weighting as a time-dimension extension of
standard RRF.

---

## Technique 31 — Asymmetric Embedding Prefixes (Task-Specific Formatting)

**Source file:** `src/services/embeddings.ts`, `src/services/indexer.ts`

### What it does in SocratiCode

SocratiCode uses the nomic-embed-text model's asymmetric task prefix feature. Every stored
chunk gets a `search_document:` prefix; every query gets a `search_query:` prefix:

```typescript
// At index time (src/services/indexer.ts):
const DOCUMENT_PREFIX = "search_document:";
const toEmbed = `${DOCUMENT_PREFIX} ${filePath}\n${chunkContent}`;

// At query time (src/services/qdrant.ts):
const QUERY_PREFIX = "search_query: ";
const queryEmbedding = await embed(`${QUERY_PREFIX}${userQuery}`);
```

The nomic-embed-text model was trained with these specific prefixes to produce task-aware
asymmetric embeddings: the document representation and the query representation live in
different regions of the 768-dim space, reducing the vocabulary mismatch between how
concepts are stored ("we implemented X using Y") vs. how they're queried ("how does X work?").

This is a **zero-cost optimization** — same model, same dimensions, same index. Only the
string prepended before embedding changes.

### BRAIN gap

BRAIN embeds raw memory content with no prefix. A memory stored as:
> "Implemented OAuth with PKCE flow using the `oauth2-rs` crate"

...and a query:
> "authentication implementation"

...produce embeddings that share some cosine, but the task-framing gap reduces precision.
The stored memory is a declarative statement; the query is an interrogative intent. Nomic's
model is designed to handle this distinction — but only if the prefixes are present.

### BRAIN application

Add prefixes in two places — ingest and search — with no other changes:

```rust
// In brain/rust/src/embedder.rs
const DOCUMENT_PREFIX: &str = "search_document: ";
const QUERY_PREFIX: &str = "search_query: ";

pub fn embed_for_storage(content: &str) -> Vec<f32> {
    embed(&format!("{}{}", DOCUMENT_PREFIX, content))
}

pub fn embed_for_query(query: &str) -> Vec<f32> {
    embed(&format!("{}{}", QUERY_PREFIX, query))
}
```

Wire `embed_for_storage` in `brain.rs::save_memory()` and `embed_for_query` in
`brain.rs::search()`. No index rebuild required for new memories — old memories without
the prefix still work (prefix adds small constant shift, doesn't break cosine ordering).

**Important note:** This requires the embedder to be nomic-embed-text or another
asymmetric model. OpenAI's text-embedding-3-small does not support task prefixes.
Verify with the embedder in use before enabling.

**Expected impact:** Measurable precision improvement on question-style queries — exactly
the kind of queries that come from `session_start.py` ("what decisions were made about X?").
Low risk: worst case is a small neutral shift; best case is a meaningful retrieval boost.

**Implementation complexity:** Very low. 2 constant strings, 2 wrapper functions.

---

## Technique 32 — Recency-Weighted RRF

**Source file:** `src/services/qdrant.ts` — hybrid search with configurable weighting

### What it does in SocratiCode

SocratiCode's RRF implementation (from Technique 2/GitNexus) is explicitly designed to
accept weight modifiers. In DEVELOPER.md it describes a "Weighted RRF" variant:

> "Weighted RRF: penalize very old memories, boost recently-edited ones. Standard RRF uses
> 1/(k+rank) equally. Weighted variant multiplies each contribution by a recency factor
> before summing."

```typescript
// Conceptual (from DEVELOPER.md architecture notes):
function weightedRRF(
    bm25Results: RankedResult[],
    semanticResults: RankedResult[],
    rrf_k: number = 60,
    recencyFn: (createdAt: Date) => number  // returns 0.5–1.0
): RankedResult[] {
    const scores = new Map<string, number>();
    for (const [rank, r] of bm25Results.entries()) {
        const w = recencyFn(r.createdAt);
        scores.set(r.id, (scores.get(r.id) ?? 0) + w / (rrf_k + rank + 1));
    }
    for (const [rank, r] of semanticResults.entries()) {
        const w = recencyFn(r.createdAt);
        scores.set(r.id, (scores.get(r.id) ?? 0) + w / (rrf_k + rank + 1));
    }
    return [...scores.entries()].sort((a, b) => b[1] - a[1]).map(([id, score]) => ({ id, score }));
}
```

The recency function applies an exponential decay: memories from today → weight=1.0,
1 month ago → weight=0.85, 6 months ago → weight=0.65, 1 year ago → weight=0.50.

### BRAIN gap

Standard RRF (T2 from GitNexus) treats a result ranked #3 the same regardless of whether
the memory is 3 days or 3 years old. BRAIN already has `created_at` timestamps on every
memory. These timestamps are stored but never used in retrieval scoring.

### BRAIN application

Extend the RRF implementation from T2 with a recency weight function:

```rust
// In brain/rust/src/brain.rs — extend hybrid_search()
fn recency_weight(created_at: &DateTime<Utc>, now: &DateTime<Utc>) -> f32 {
    let age_days = (*now - *created_at).num_days() as f32;
    // Exponential decay: half-life of ~180 days
    // At 0 days: 1.0; at 180 days: ~0.85; at 365 days: ~0.72; at 730 days: ~0.52
    let decay = 0.5_f32.powf(age_days / 730.0);
    0.5 + 0.5 * decay  // floor at 0.5 — never fully suppress old memories
}

fn weighted_rrf_merge(
    bm25: &[(String, DateTime<Utc>)],   // (id, created_at) ranked by BM25
    semantic: &[(String, DateTime<Utc>)], // (id, created_at) ranked by cosine
    rrf_k: f32,
    now: &DateTime<Utc>,
) -> Vec<(String, f32)> {
    let mut scores: HashMap<String, f32> = HashMap::new();
    for (rank, (id, ts)) in bm25.iter().enumerate() {
        let w = recency_weight(ts, now);
        *scores.entry(id.clone()).or_insert(0.0) += w / (rrf_k + rank as f32 + 1.0);
    }
    for (rank, (id, ts)) in semantic.iter().enumerate() {
        let w = recency_weight(ts, now);
        *scores.entry(id.clone()).or_insert(0.0) += w / (rrf_k + rank as f32 + 1.0);
    }
    let mut ranked: Vec<_> = scores.into_iter().collect();
    ranked.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap());
    ranked
}
```

**Key design choice:** Floor at 0.5 (not 0.0). Old memories are penalized but never
suppressed — if a 2-year-old architectural decision is semantically the best match, it
still surfaces. This avoids the "recency amnesia" failure mode where old-but-correct
decisions are permanently invisible.

**Interaction with Leitner (T27):** Recency-weighted RRF handles the *normal retrieval*
path. Leitner handles the *forced resurfacing* path. They operate in different layers:
RRF penalizes old memories in ranking; Leitner overrides ranking entirely for memories
due for review.

**Implementation complexity:** Low. Extends T2 (hybrid RRF) with one additional function
and `created_at` passed through the merge step.

---

## Technique 33 — Hub Memory Detection (Impact Radius)

**Source files:** `src/services/graph-impact.ts` (blast radius BFS), `src/services/symbol-graph-store.ts`

### What it does in SocratiCode

SocratiCode computes blast radius as a BFS over reverse-call edges:

```typescript
// Starting from a symbol, find all callers (reverse edges), then callers of callers...
async function getBlastRadius(symbolId: string, maxHops: number = 3): Promise<ImpactMap> {
    const visited = new Set<string>();
    const queue: [string, number][] = [[symbolId, 0]];
    const impact: ImpactMap = { byHop: {} };

    while (queue.length > 0) {
        const [id, hop] = queue.shift()!;
        if (visited.has(id) || hop > maxHops) continue;
        visited.add(id);
        const callers = await reverseCallIndex.get(id);
        impact.byHop[hop] = [...(impact.byHop[hop] ?? []), id];
        callers.forEach(caller => queue.push([caller, hop + 1]));
    }
    return impact;
}
```

This answers: "if I change symbol X, how many other symbols does it affect, and how many
hops away?" High blast radius → high-importance node → entry point candidate.

### BRAIN gap

BRAIN's memories are flat and unconnected. If a "hub" decision memory (e.g., "we use
Postgres as the primary store — all persistence goes through `store.rs`") is changed or
contradicted, BRAIN has no way to identify which other memories are now stale.

Memory relationships from T24 (GitNexus) sets up the infrastructure for edges. Hub detection
is the **use case** that makes those edges actionable: identify which memories have the most
downstream dependents so they get special handling.

### BRAIN application

Once `memory_relationships` (T24) is in place, hub detection is a BFS query over the
`DERIVED_FROM` and `SAME_SESSION` edges:

```rust
// In brain/rust/src/brain.rs — offline analysis, run during reflect cycle
fn compute_hub_scores(db: &Store) -> Vec<(String, usize)> {
    // For each memory, count how many others have DERIVED_FROM or SAME_SESSION edges to it
    let edges = db.get_all_relationships();
    let mut in_degree: HashMap<String, usize> = HashMap::new();

    for edge in edges {
        if edge.rel_type == "DERIVED_FROM" || edge.rel_type == "ELABORATES" {
            *in_degree.entry(edge.target_id).or_insert(0) += 1;
        }
    }

    let mut ranked: Vec<_> = in_degree.into_iter().collect();
    ranked.sort_by(|a, b| b.1.cmp(&a.1));
    ranked
}
```

**Uses of hub scores:**
1. **Importance boost:** Top-N hub memories get `importance` bumped to ≥ 0.8 regardless of
   feedback history. Hub status = inherently important.
2. **Staleness alert:** When a hub memory is edited or a contradicting memory is saved,
   surface a warning: "This memory has N downstream dependents — check if they're still valid."
3. **Reflect targeting:** Reflect cycle prioritizes hub neighborhoods (the hub + its
   dependents) for LLM consolidation.
4. **Web viewer:** Visualize hubs as larger nodes in the graph view (already planned
   in the brain-graph/ directory).

**Implementation complexity:** Medium. Requires T24 (`memory_relationships`) to exist first.
Once edges exist, hub scoring is a single aggregation query.

---

## Technique 34 — Pinned Context Artifacts (Sacred Memory Tier)

**Source files:** `src/services/context-artifacts.ts`, `src/tools/context-tools.ts`

### What it does in SocratiCode

SocratiCode separates "context artifacts" from regular indexed code. These are defined in
`.socraticodecontextartifacts.json`:

```json
[
  { "name": "API conventions", "path": "./docs/api-conventions.md",   "description": "REST conventions for this project" },
  { "name": "Architecture",    "path": "./docs/architecture/",        "description": "All architecture decision records" }
]
```

Key behaviors that distinguish artifacts from regular index entries:
- **SHA-256 staleness detection**: re-indexed only when file content changes, not on every run
- **Separate Qdrant collection**: artifacts never compete with code for the same search slots
- **Searchable independently**: `codebase_context_search` queries artifacts only
- **Combined search**: standard `codebase_search` can optionally include artifacts via RRF merge

The mental model: context artifacts are **pinned, trusted, curated knowledge** that should
always be available and never get buried by noisy indexed content.

### BRAIN gap

BRAIN has no concept of memory tiers. A carefully crafted architectural decision memory
(manually saved with `save_memory_tool`) sits in the same flat table as thousands of
auto-generated conversation snippets. The architectural decision has the same pruning risk,
the same importance score (0.5), and the same retrieval competition as every other memory.

High-value curated memories (architecture decisions, project conventions, key patterns)
should be protected from pruning and always surfaced above auto-generated content when relevant.

### BRAIN application

Add a `tier` column to the `memories` table with two values: `standard` (default) and
`pinned`. Pinned memories behave differently across all operations:

```sql
ALTER TABLE memories ADD COLUMN tier TEXT DEFAULT 'standard';
-- tier: 'standard' | 'pinned'
```

**Pinning rules:**
- Auto-pin: `memory_type = 'decision'` with `importance >= 0.8` after trust scoring
- Manual pin: `save_memory_tool` with `pinned=true` parameter
- Config-pin: entries in `.brain/artifacts.json` (mirrors `.socraticodecontextartifacts.json`)

```json
// .brain/artifacts.json — project-local pinned knowledge
[
  { "name": "DB schema", "path": "./docs/schema.md", "description": "Canonical schema reference" },
  { "name": "API guide", "path": "./docs/API_GUIDE.md", "description": "REST API conventions" }
]
```

**Behaviors for pinned memories:**
1. **Never pruned** by `prune_trivial_memories.py` regardless of importance score
2. **Forced into every session start context** (up to 2 pinned memories per session, before cosine results)
3. **SHA-256 staleness tracking**: re-embed only if content changed (new `content_hash` column)
4. **Retrieval boost**: `importance` floor of 0.75 — pinned memories always beat standard ones on tie

```rust
// In brain/rust/src/brain.rs — session start context injection
fn get_session_context(project: &str, query: &str, db: &Store) -> Vec<Memory> {
    let pinned  = db.get_pinned_memories(project, 2);   // always include ≤2 pinned
    let cosine  = search_standard(query, project, 5);   // top-5 standard memories
    merge_dedup(pinned, cosine)
}
```

**Implementation complexity:** Low-Medium. Schema migration (2 columns: `tier`, `content_hash`),
`.brain/artifacts.json` file watcher, modified prune + session-start logic.

---

## Technique 35 — Fire-and-Forget Async Ingest with Checkpoint Resumability

**Source files:** `src/services/indexer.ts`, `src/tools/index-tools.ts`, `src/services/startup.ts`

### What it does in SocratiCode

SocratiCode's indexing is fully non-blocking:

```typescript
// In index-tools.ts — tool handler returns immediately
async function handleIndexTool(args: IndexArgs): Promise<ToolResponse> {
    // Start indexing in background — do NOT await
    indexCodebase(args.projectPath, { force: args.force }).catch(err => {
        logger.error("background indexing failed", err);
    });

    return { content: [{ type: "text", text: "Indexing started. Use codebase_status to poll progress." }] };
}
```

Progress is tracked in a status object updated by the background process:

```typescript
interface IndexingStatus {
    phase: "idle" | "scanning" | "embedding" | "storing" | "done" | "error";
    filesTotal: number;
    filesProcessed: number;
    chunksTotal: number;
    chunksEmbedded: number;
    startedAt: Date;
    errorMessage?: string;
}
```

**Checkpoint resumability**: per-file SHA-256 hash stored in Qdrant metadata. On restart
or retry, skip any file whose stored hash matches the current file hash:

```typescript
// indexer.ts — incremental check before embedding
const storedHash = await getStoredHash(filePath);
const currentHash = sha256(fileContent);
if (storedHash === currentHash) {
    stats.skipped++;
    continue;  // file unchanged, skip embedding
}
```

Threshold: ≤50 changed files → patch existing symbol graph; >50 → full rebuild.

### BRAIN gap

BRAIN's ingest scripts are synchronous and blocking:
- `07_ingest_claude_code.py` — blocks for the full session batch (can take 5+ minutes for 100+ sessions)
- `08_ingest_books.py` — blocks for the full book corpus
- `09_ingest_obsidian.py` — blocks for the full vault

If interrupted mid-run, progress is lost (checkpoint files help but are coarse-grained).
There is no MCP tool to query ingest status — the user must watch the terminal.

### BRAIN application

**Phase 1 (zero-code, immediate win):** Add content-hash tracking to skip unchanged files:

```python
# In brain/bootstrap/07_ingest_claude_code.py — add before embedding
import hashlib

def should_skip(session_path: str, db_cursor) -> bool:
    content = open(session_path).read()
    content_hash = hashlib.sha256(content.encode()).hexdigest()
    row = db_cursor.execute(
        "SELECT content_hash FROM ingest_cache WHERE path = ?", (session_path,)
    ).fetchone()
    return row and row[0] == content_hash

def mark_ingested(session_path: str, db_cursor):
    content = open(session_path).read()
    content_hash = hashlib.sha256(content.encode()).hexdigest()
    db_cursor.execute(
        "INSERT OR REPLACE INTO ingest_cache (path, content_hash, ingested_at) VALUES (?, ?, ?)",
        (session_path, content_hash, datetime.utcnow().isoformat())
    )
```

This alone eliminates re-embedding sessions that haven't changed — the dominant cost
in repeated ingest runs.

**Phase 2 (medium effort):** Expose ingest progress via a new MCP tool:

```rust
// In brain/rust/src/brain_api.rs — new endpoint
GET /v1/ingest/status → {
    "phase": "embedding",
    "items_total": 143,
    "items_done": 67,
    "items_skipped": 12,  // unchanged (hash match)
    "started_at": "2026-04-30T14:22:01Z",
    "eta_seconds": 38
}
```

**Checkpoint granularity:** Save checkpoint every 25 items (not just at the end). On
crash/restart, resume from the last checkpoint item, not from the beginning.

**Implementation complexity:** Phase 1 (hash skip) — Low. New `ingest_cache` table, 10
lines per ingest script. Phase 2 (async + status API) — Medium. New endpoint in brain_api,
shared progress state.

---

## Technique 36 — Memory Type Staleness TTL

**Source files:** `src/constants.ts` (TTL config), `src/services/watcher.ts` (invalidation)

### What it does in SocratiCode

SocratiCode marks indexed chunks as stale when their source files change. The watcher fires
incremental updates with a 2s debounce. Different content types have different effective
staleness windows:

From DEVELOPER.md architecture notes:
> "Architecture decisions are semantically stable for months. Implementation details change
> weekly. Conversations are volatile — same context tomorrow is coincidental. TTL by content
> type prevents stale data from polluting retrieval."

The watcher + incremental update system effectively implements different staleness windows:
config files → re-index on every change; source files → re-index on save; documentation →
re-index on commit.

### BRAIN gap

BRAIN has no TTL or expiry concept. A `conversation` memory from a 2-year-old debugging
session about a library version that no longer exists is given the same indefinite lifespan
as an architectural decision that's still active. Both compete equally in search forever.

The `prune_trivial_memories.py` tool exists but uses embedding outlier distance as its
signal — not semantic age or type-appropriate decay.

### BRAIN application

Add type-differentiated TTL as a **soft expiry** (not hard delete): memories past their
TTL get `importance` decayed but remain queryable:

```rust
// In brain/rust/src/brain.rs — run during nightly reflect cycle
const TTL_BY_TYPE: &[(&str, i64)] = &[
    ("conversation",    30),   // 30 days — volatile by nature
    ("error",           60),   // 60 days — error patterns shift with library versions
    ("solution",        180),  // 180 days — solutions remain valid longer
    ("pattern",         365),  // 1 year — patterns are foundational
    ("decision",        730),  // 2 years — decisions are long-lived
    ("project_context", 365),  // 1 year — project context changes but slowly
];

fn apply_ttl_decay(db: &Store, now: &DateTime<Utc>) {
    for (mem_type, ttl_days) in TTL_BY_TYPE {
        let threshold = *now - Duration::days(*ttl_days);
        let stale = db.get_memories_older_than(mem_type, &threshold);

        for memory in stale {
            // Soft decay: reduce importance by 20% per TTL period elapsed
            let periods_elapsed = ((*now - memory.created_at).num_days() / ttl_days) as f32;
            let decay_factor = 0.8_f32.powi(periods_elapsed as i32);
            let new_importance = (memory.importance * decay_factor).max(0.1); // floor at 0.1
            db.set_importance(&memory.id, new_importance);
        }
    }
}
```

**Soft expiry rules:**
- Never hard-delete (use `prune_trivial_memories.py` for actual deletion, after manual review)
- Floor importance at 0.1 — stale memories still surface if they're the only match
- Pinned memories (T34) are TTL-exempt — explicit curation overrides decay
- Leitner box 5 memories (T27) get 2× the TTL — heavily reinforced memories decay slower

**Interaction with T27 (Leitner):** Leitner handles resurfacing cadence for important memories;
TTL handles decay for all memories. A memory in Leitner box 5 (proven valuable) has its TTL
doubled. A memory that decays to importance=0.1 and has never been retrieved gets its Leitner
box reset to 1 — it needs to prove relevance again before being trusted.

**Implementation complexity:** Low. No schema change (uses existing `importance` + `created_at`
+ `memory_type`). New function in reflect cycle, ~40 lines of Rust.

---

---

---

---

# Research Source 8 — DL-SOCRATIS

> https://github.com/INSIGNEO/DL-SOCRATIS
> Python + C++ (ITK). Deep learning cardiac MRI segmentation pipeline.
> Full source analyzed: `main_net.py`, `run_model.py`, `RGMMNet.py`, `graph.py`,
> `coarsening.py`, `losses_distance.py`, `CGAN_model.py`, `CGAN_utils.py`,
> `config.py`, `handle_data.py`, `datasetnet.py`, `evaluate.h`, `interparameters.h`,
> `strain.py`. Authors: INSIGNEO Institute, University of Sheffield.

## What DL-SOCRATIS is

A deep learning pipeline for automated segmentation of myocardial scar tissue in cardiac
LGE-MRI images. It extends a classical multi-atlas approach (MA-SOCRATIS) with modern deep
learning: U-Net for segmentation, RGMMNet (a custom graph-based Rician-Gaussian Mixture Model
layer) for tissue characterization, and CycleGAN for unpaired domain translation (LGE-MRI →
cine-MRI). Metrics: Dice coefficient, Jaccard index, weighted Hausdorff distance.

**Why analyze a cardiac imaging pipeline for a memory system?** Different domain = different
pressures. Medical imaging demands explicit uncertainty quantification, multi-scale processing,
and multi-objective scoring that software memory systems have never needed to build — but
would benefit from. This source surfaces four patterns not found in any previous source.

| DL-SOCRATIS concept | BRAIN equivalent |
|---|---|
| Rician-Gaussian mixture model confidence | Retrieval score uncertainty band |
| METIS graph coarsening (fine → coarse hierarchy) | Multi-scale memory retrieval (memory → cluster → domain) |
| CycleGAN image pool (50-image diversity buffer) | Anti-echo-chamber diversity pool (session-scoped) |
| Hybrid Dice + Hausdorff + crossentropy loss | Composite multi-signal retrieval score |
| Two-stage ROI → detail segmentation | Coarse candidate set → fine cosine rerank |
| Sensitivity parameters per tissue type | Per-memory-type retrieval thresholds |

---

## Technique 37 — Retrieval Uncertainty Band (Mixture Model Confidence)

**Source files:** `RGMMNet/RGMMNet.py` — `Gaussian_Weighting`, `Rician_Weighting`; `run_model.py`

### What it does in DL-SOCRATIS

RGMMNet models tissue classification as a probabilistic mixture: each pixel is assigned a
confidence score from a Gaussian (well-separated tissue) or Rician (noisy, boundary) distribution.
When the two top-scoring tissue classes have distributions that overlap significantly, the pixel
is flagged as **uncertain** — a boundary pixel that might belong to either class.

```python
# Gaussian_Weighting: computes per-node mixture weights
def Gaussian_Weighting(self, x):
    # x: [batch, nodes, features]
    # Returns mixture weights — high weight = high confidence assignment
    dist = tf.reduce_sum(tf.square(x - self.mu), axis=-1)  # distance to cluster center
    weights = tf.exp(-dist / (2 * self.sigma**2))           # Gaussian kernel
    weights = weights / tf.reduce_sum(weights, axis=-1, keepdims=True)  # normalize
    return weights  # shape: [batch, nodes, n_components]

# Rician_Weighting adds Bessel function correction for magnitude MRI noise
```

The key insight: **score proximity between top candidates = uncertainty**. When two classes
score within σ of each other, the model cannot confidently discriminate. This uncertainty
is explicit, not hidden.

### BRAIN gap

BRAIN returns top-k results with raw cosine distances. When the top-2 results score 0.89
and 0.87 respectively, those are treated identically to the case where they score 0.89 and
0.51. But the first case is genuinely uncertain — both memories are plausible, and only the
user/LLM can arbitrate. BRAIN hides this uncertainty; it should expose it.

The CLAUDE.md already acknowledges this heuristically:
> "When the top two distances are within ~0.02, read both vault files before deciding."

This is a manual rule in a document. It should be a machine-readable signal in the MCP
response so every consumer of BRAIN's tools can act on it automatically.

### BRAIN application

Define an uncertainty band: when top-2 results are within `UNCERTAINTY_THRESHOLD` (0.03
cosine), flag the response as uncertain and surface both:

```rust
// In brain/rust/src/brain.rs
const UNCERTAINTY_THRESHOLD: f32 = 0.03;

pub struct SearchResponse {
    pub results:     Vec<Memory>,
    pub uncertain:   bool,       // true if top-2 within UNCERTAINTY_THRESHOLD
    pub uncertainty_gap: f32,    // actual gap between rank-1 and rank-2 scores
}

fn compute_uncertainty(results: &[ScoredMemory]) -> (bool, f32) {
    if results.len() < 2 { return (false, 1.0); }
    let gap = results[0].score - results[1].score;
    (gap < UNCERTAINTY_THRESHOLD, gap)
}
```

**MCP response change (search_brain):**
```json
{
  "results": [...],
  "uncertain": true,
  "uncertainty_gap": 0.018,
  "note": "Top 2 results are very close in score — both may be relevant. Read both before deciding."
}
```

**Downstream uses:**
1. **Session start hook**: If uncertain=true, inject both top results (not just the top-1)
2. **MCP consumers**: Claude reads `uncertain` flag and proactively reads both vault files
3. **Retrieval analytics** (T14): Track what % of queries are uncertain per project. High
   uncertainty % → corpus needs better deduplication or topic separation (T16)
4. **Threshold tuning**: Per-project `UNCERTAINTY_THRESHOLD` via `.brain/config.toml` (T7)

**Implementation complexity:** Very low. One comparison after search, one extra field in
the response struct. Formalizes the existing CLAUDE.md heuristic as machine-readable data.

---

## Technique 38 — Hierarchical Memory Coarsening (Multi-Scale Retrieval)

**Source files:** `RGMMNet/coarsening.py` — `coarsen()`, `metis()`, `graclus_largest_eigenvector()`; `RGMMNet/graph.py`

### What it does in DL-SOCRATIS

RGMMNet uses METIS-based graph coarsening to build a **hierarchy of graph resolutions**:

```python
def coarsen(A, levels, self_connections=False):
    """
    Coarsen a graph by repeatedly merging nodes (METIS algorithm).
    Returns: graphs[0] = finest, graphs[-1] = coarsest
    """
    graphs, parents = [], []
    G = {'A': A, 'x': None}
    for _ in range(levels):
        G, parent = metis(G['A'], ...))
        graphs.append(G)
        parents.append(parent)
    return graphs, parents

def metis(A, ...):
    # Merge pairs of strongly-connected nodes into single super-nodes
    # Result: graph with ~half the nodes, edges aggregated
```

After coarsening, RGMMNet processes the signal at multiple scales simultaneously:
- **Fine level**: Individual nodes — high spatial precision, expensive
- **Coarse level**: Super-nodes (clusters) — lower precision, cheap

For classification, it starts coarse (is this a scar region?) then drills into fine (exactly
which pixels?). Broad queries → coarse level answers quickly. Narrow queries → fine level needed.

### BRAIN gap

BRAIN has one retrieval level: individual memories. A query like "what was the overall
architecture direction for project sakbe?" and a query like "what was the exact SQLite schema
for the sessions table?" both hit the same flat cosine index over 2,484 individual memories.

The broad query would be better served by a coarser representation — cluster summaries
(see T19/Leiden communities) that answer "the overall direction" without surfacing 15 specific
implementation memories. The narrow query needs the fine level.

### BRAIN application

Build a 3-level hierarchy on top of the existing memory store — no structural changes to
`memories`, only additive:

```
Level 0 (Fine):    Individual memories        — 2,484 entries, 768-dim embeddings
Level 1 (Cluster): Cluster centroid summaries — ~50-100 entries (after Leiden, T19)
Level 2 (Domain):  Domain abstracts           — ~10 entries (one per knowledge domain, T30)
```

**Level 1 construction** (runs after Leiden community detection, T19):
```python
# brain/tools/build_memory_hierarchy.py
for community_id, member_ids in leiden_communities.items():
    members = db.get_memories(member_ids)
    # LLM summarize the community into a single paragraph
    summary = summarize(members, max_tokens=200)
    db.save_cluster_summary(community_id, summary, embed(summary))
```

**Level 2 construction** (runs monthly):
```python
for domain in DOMAIN_TAXONOMY:
    domain_memories = db.get_memories_by_domain(domain)
    abstract = summarize(domain_memories, max_tokens=100)
    db.save_domain_abstract(domain, abstract, embed(abstract))
```

**Query routing** — detect specificity at query time:

```rust
// In brain/rust/src/brain.rs
fn select_retrieval_level(query: &str) -> RetrievalLevel {
    let tokens = query.split_whitespace().count();
    let has_specifics = query.contains('"') ||  // quoted terms
                        query.contains("::") ||  // code references
                        query.contains("table") ||
                        query.len() > 80;        // long = specific

    if tokens <= 5 && !has_specifics {
        RetrievalLevel::Domain   // broad: "architecture direction"
    } else if tokens <= 15 {
        RetrievalLevel::Cluster  // mid: "authentication approach"
    } else {
        RetrievalLevel::Memory   // specific: "exact JWT expiry logic"
    }
}
```

**Search at each level:**
- Domain level → search 10 domain abstracts → return the matching domain abstract
- Cluster level → search 50-100 cluster summaries → return matching summary + "see also: N memories in this cluster"
- Memory level → existing cosine search (current behavior)

**Fallback**: If cluster/domain search returns low confidence (<0.5), fall through to the
finer level. Mirrors RGMMNet's coarse→fine cascade.

**Implementation complexity:** Medium-High. Requires Leiden (T19) to exist first for Level 1.
Level 2 is independent. New `cluster_summaries` and `domain_abstracts` tables, new
`build_memory_hierarchy.py` tool, query routing logic in `brain.rs`.

---

## Technique 39 — Retrieval Diversity Buffer (Anti-Echo-Chamber)

**Source files:** `CycleGAN/CGAN_utils.py` — `ImagePool` class; `CycleGAN/CGAN_model.py`

### What it does in DL-SOCRATIS

CycleGAN's discriminator becomes overfit if it always sees the same generated images.
The `ImagePool` prevents this:

```python
class ImagePool:
    def __init__(self, pool_size=50):
        self.pool_size = pool_size
        self.images = []

    def query(self, image):
        if len(self.images) < self.pool_size:
            self.images.append(image)
            return image
        elif random.random() > 0.5:
            # 50% chance: return a random old image, store new one
            idx = random.randint(0, self.pool_size - 1)
            old = self.images[idx]
            self.images[idx] = image
            return old
        else:
            return image  # just return new image
```

The result: training sees a **diverse mix** of current and historical images, preventing
the discriminator from memorizing the latest batch and forgetting earlier patterns.

### BRAIN gap

BRAIN's session-start hook retrieves top-5 by cosine. If a project has a dominant topic
(e.g., "authentication"), the same 5 authentication memories appear at the start of every
session regardless of whether the current session is about authentication.

Within a session, `brain_user_prompt_submit` also returns top-5 per query. If a user asks
3 related questions, the same memories may appear 3 times — consuming context on repetition
instead of breadth.

No diversity mechanism exists. The same memories can dominate every retrieval indefinitely.

### BRAIN application

Maintain a session-scoped "already surfaced" set. Penalize already-surfaced memories in
subsequent retrievals within the same session:

```rust
// In brain/rust/src/brain_user_prompt_submit.rs
// (session state lives in the hook process — reset on new session)

struct SessionDiversityBuffer {
    surfaced_ids: HashSet<String>,
    capacity: usize,  // max to track before resetting (50, like ImagePool)
}

impl SessionDiversityBuffer {
    fn score_penalty(&self, memory_id: &str) -> f32 {
        if self.surfaced_ids.contains(memory_id) {
            0.75  // 25% penalty for already-seen memories
        } else {
            1.0   // no penalty for fresh memories
        }
    }

    fn mark_surfaced(&mut self, ids: &[&str]) {
        for id in ids {
            if self.surfaced_ids.len() < self.capacity {
                self.surfaced_ids.insert(id.to_string());
            }
            // at capacity: oldest-out (not implemented — just stop tracking)
        }
    }
}

// Apply in search re-ranking:
for result in &mut results {
    result.score *= diversity_buffer.score_penalty(&result.id);
}
results.sort_by(|a, b| b.score.partial_cmp(&a.score).unwrap());
diversity_buffer.mark_surfaced(&results.iter().map(|r| r.id.as_str()).collect::<Vec<_>>());
```

**Buffer lifecycle:**
- Created fresh at every `SessionStart`
- Persists across all `UserPromptSubmit` calls in the same session
- Destroyed at `SessionEnd`

**Key design choices from ImagePool:**
- **Penalty, not exclusion**: Already-surfaced memories get 0.75× score, not 0.0. A memory
  that's genuinely the best answer to a new query can still surface — it just needs to beat
  fresh alternatives by >25%.
- **Capacity cap (50)**: Don't track an unbounded set. After 50 unique memories have been
  surfaced, stop penalizing — the session has diverged enough that repetition is fine.
- **Pinned memories (T34) exempt**: Architecture decisions and conventions should always be
  available regardless of how many times they've been shown.

**Implementation complexity:** Low. Session-scoped hash set in the `brain_user_prompt_submit`
binary. No database changes. No inter-process state needed (the hook binary runs per-prompt
and can read a session state file written by `brain_session_start`).

---

## Technique 40 — Composite Multi-Signal Retrieval Score

**Source files:** `utils/losses_distance.py` — weighted Hausdorff distance; `run_model.py` — `compile()` with hybrid losses

### What it does in DL-SOCRATIS

DL-SOCRATIS trains with a **composite loss** combining multiple objectives:

```python
# run_model.py — model compilation with hybrid losses
model.compile(
    optimizer=Adam(lr=config.learning_rate),
    loss={
        'seg_output': weighted_combination(
            dice_loss,          # weight: 0.5 — overlap quality
            hausdorff_loss,     # weight: 0.3 — boundary precision
            crossentropy,       # weight: 0.2 — pixel-level accuracy
        )
    }
)

# losses_distance.py — weighted Hausdorff distance
def weighted_hausdorff_loss(y_true, y_pred, alpha=4):
    # Term1: max distance from predicted boundary to nearest true boundary point
    # Term2: max distance from true boundary to nearest predicted boundary point
    # alpha controls spatial weighting (higher = punish outlier errors more)
    term1 = tf.reduce_mean(tf.reduce_min(dist_matrix * spatial_weights, axis=1))
    term2 = tf.reduce_mean(tf.reduce_min(dist_matrix * spatial_weights, axis=0))
    return term1 + term2
```

The key insight: **no single objective captures what "good segmentation" means**. Dice
measures overlap; Hausdorff measures boundary precision; crossentropy measures pixel
accuracy. Each objective catches failures the others miss. The weights are tunable and
can be learned from validation data.

### BRAIN gap

BRAIN's final retrieval score today is ad-hoc:
- Currently: raw cosine similarity (single signal)
- Planned: `rrf_score * (0.6 + 0.4 * importance)` (from T17, still ad-hoc)

As techniques T2 (RRF), T12 (recency-weighted RRF), T18 (trust/importance), T19 (Leitner
box), T36 (staleness TTL decay) each add their own scoring adjustments, the scoring logic
risks becoming a pile of sequential multiplications with no principled foundation — each
technique fighting the others in undefined ways.

**The synthesis problem:** what happens when a memory has high cosine (T2), high recency
weight (T12), low trust score (T18), high Leitner box (T19), and is pinned (T34)? The
current approach has no defined answer. Each technique adds its own factor independently.

### BRAIN application

Replace the ad-hoc chain with a single **composite retrieval score** with explicit, tunable
weights — directly mirroring DL-SOCRATIS's hybrid loss design:

```rust
// In brain/rust/src/brain.rs — replace fragmented scoring with composite

pub struct RetrievalWeights {
    pub cosine:     f32,  // default: 0.35 — semantic similarity (BM25+cosine RRF)
    pub recency:    f32,  // default: 0.20 — time decay weight (T32)
    pub trust:      f32,  // default: 0.25 — importance/trust score (T18/T28)
    pub leitner:    f32,  // default: 0.10 — spaced repetition box (T27)
    pub domain:     f32,  // default: 0.10 — same-domain boost (T30)
}

impl Default for RetrievalWeights {
    fn default() -> Self {
        Self { cosine: 0.35, recency: 0.20, trust: 0.25, leitner: 0.10, domain: 0.10 }
    }
}

fn composite_score(
    memory: &Memory,
    cosine:  f32,  // raw cosine or RRF score [0,1]
    now:     &DateTime<Utc>,
    query_domain: Option<&str>,
    weights: &RetrievalWeights,
) -> f32 {
    let recency  = recency_weight(&memory.created_at, now);        // T32: [0.5, 1.0]
    let trust    = memory.importance;                               // T18/T28: [0.0, 1.0]
    let leitner  = (memory.leitner_box as f32) / 5.0;             // T27: [0.2, 1.0]
    let domain   = if Some(memory.domain.as_str()) == query_domain // T30
                   { 1.0 } else { 0.85 };

    weights.cosine  * cosine  +
    weights.recency * recency +
    weights.trust   * trust   +
    weights.leitner * leitner +
    weights.domain  * domain
}
```

**Weight learning** (the key innovation from the hybrid loss approach):

Weights start at defaults. After each retrieval cycle, compare the composite score ordering
against user feedback signals (which memories were actually useful, from T14/RTK retrieval
analytics). Adjust weights using a simple gradient:

```python
# brain/tools/tune_retrieval_weights.py  (offline, runs weekly)
# Load: retrieval_log with query, result_ids, user_feedback
# For each retrieval: compute "correct" ordering from feedback
# For each weight: did increasing it improve or hurt ordering?
# Apply small gradient step (δ=0.01) toward feedback-preferred ordering
# Constrain: all weights must sum to 1.0, each weight in [0.05, 0.50]
```

This is gradient descent on the composite score weights using retrieval feedback as the
loss signal — a direct analog of DL-SOCRATIS's optimizer adjusting loss weights during training.

**Fallback precedence** (mirrors Hausdorff's `alpha` parameter for outlier control):
- Pinned memories (T34): composite score floor = 0.75 (always competitive)
- Coverage gap queries (T29): recency weight → 0 (age irrelevant if nothing exists)
- Session-start context: leitner weight doubled (resurfacing is the goal)
- UserPromptSubmit: cosine weight doubled (immediate relevance is the goal)

**Implementation complexity:** Medium. Replaces scattered scoring logic with one struct and
one function. The struct is configured via `.brain/config.toml` (T7). Weight learning is
offline-only (no live system changes). Most complexity is in `tune_retrieval_weights.py`.

---

## Updated Full Implementation Roadmap (all sources)

| Priority | Technique | Source | Effort | Impact | Status |
|---|---|---|---|---|---|
| 1 | Mean-centering embeddings | OpenBMI | Low | Medium | — |
| 2 | **RRF hybrid search (BM25 + cosine)** | GitNexus | Low | **Highest** | ✅ Phase 1 (alpha-weighted hybrid in `brain_api`) |
| 3 | k-fold retrieval evaluation (precision@k) | OpenBMI | Low | Enables measurement | ✅ Phase 6 (`--facts-only`, `facts_queries.jsonl`) |
| 4 | `task_context` + `goal` in search queries | GitNexus | Low | Medium | — |
| 5 | `match_output` short-circuit on empty MCP results | RTK | Low | Medium | — |
| 6 | Category-based token budget estimation | RTK | Low | Medium | — |
| 7 | 3-level config hierarchy (.brain/config.toml) | RTK | Low | Medium | — |
| 8 | Human-centric memory taxonomy (identity/preferences/relationships/wishes) | Mark-XXXV | Low | High | — |
| 9 | Domain-weighted retrieval taxonomy | SocraticSkill | Low | Medium | — |
| 10 | Coverage gap detection and surfacing | SocraticSkill | Low | Medium | — |
| 11 | **Asymmetric embedding prefixes (search_query: / search_document:)** | SocratiCode | Low | **High** | — |
| 12 | **Retrieval uncertainty band** | **DL-SOCRATIS** | Low | High | — |
| 13 | **Retrieval diversity buffer (anti-echo-chamber)** | **DL-SOCRATIS** | Low | Medium | — |
| 14 | Recency-weighted RRF | SocratiCode | Low | High | ✅ Phase 7 (`event_time.unwrap_or(timestamp)` in decay) |
| 15 | RLDA + Ledoit-Wolf projection on embeddings | OpenBMI | Medium | High | — |
| 16 | SQLite `retrieval_log` table (per-query analytics) | RTK | Medium | Medium | — |
| 17 | PyOD outlier detection → importance scores | awesome-ml | Medium | Medium | — |
| 18 | Dedupe semantic deduplication pass | awesome-ml | Medium | Medium | ✅ Phase 2 (3-tier cosine gate: <0.78 auto-ADD, 0.78–0.92 LLM, >0.92 auto-IGNORE) |
| 19 | Multi-factor importance scoring | GitNexus | Medium | Medium | ✅ Phase 6 (salience stored; beta=0.0, no signal at current calibration) |
| 20 | Spaced repetition (Leitner) for memory resurfacing | SocraticSkill | Medium | High | — |
| 21 | Memory trust scoring from retrieval feedback | SocraticSkill | Medium | High | — |
| 22 | Memory type staleness TTL | SocratiCode | Medium | Medium | ✅ Phase 4 (`superseded_by` + `exclude_superseded` default true) |
| 23 | Hub memory detection (impact radius) | SocratiCode | Medium | High | — |
| 24 | Pinned context artifacts (sacred memory tier) | SocratiCode | Medium | High | — |
| 25 | Fire-and-forget async ingest + checkpoint resumability | SocratiCode | Medium | Medium | ✅ Phase 3 (`backfill_facts.py` per-source checkpoint JSON) |
| 26 | **Composite multi-signal retrieval score** | **DL-SOCRATIS** | Medium | **High** | — |
| 27 | **Hierarchical memory coarsening (multi-scale retrieval)** | **DL-SOCRATIS** | Med-High | High | — |
| 28 | Graph relationships (`memory_relationships` table) | GitNexus | Medium | High | — |
| 29 | Leiden community detection on co-occurrence graph | GitNexus | Medium | High | — |
| 30 | Per-type FTS indexes with top-3 merge | GitNexus | Medium | Medium | ✅ Phase 2 (`fts_search_facts` separate FTS path for facts) |
| 31 | Semantic chunking for book/Obsidian ingestion | GitNexus | Medium | Medium | — |
| 32 | PostToolUse hook: compress command output inline | RTK | Medium | High | — |
| 33 | Mine session JSONL for false-positive + co-retrieval signals | RTK | Medium | Medium | — |
| 34 | StreamFilter trait for progressive MCP result emission | RTK | Medium | Medium | — |
| 35 | 4-level memory access verdict per project | RTK | Medium | Medium | — |
| 36 | Per-turn 2-stage extraction hook (YES/NO → full extract) | Mark-XXXV | Medium | Medium | ✅ Phase 2 (curator IGNORE = cheap gate; LLM only in tiebreaker band) |
| 37 | linfa Rust port of LDA/KMeans | awesome-ml | High | High | — |
| 38 | shimmy / rust-bert → eliminate Python embedder | awesome-ml | High | High | — |
| 39 | HNSW via usearch (when corpus > 30K) | GitNexus + awesome-ml | High | Low now | — |

---

## Research Log (updated)

| Date | Source | Finding |
|---|---|---|
| 2026-04-26 | OpenBMI | Initial analysis. Core insight: OpenBMI pipeline maps to BRAIN's embedding pipeline. 5 techniques identified (LW shrinkage, mean-centering, MI selection, artifact rejection, k-fold eval). |
| 2026-04-26 | awesome-machine-learning | Full 212KB README analyzed. 8 optimization surfaces identified. Key additions: BM25 hybrid retrieval (SQLite FTS5), PyOD outlier detection, Dedupe deduplication, HDBScan clustering, linfa for Rust-native ML, shimmy for Python-free embeddings. |
| 2026-04-26 | GitNexus | Full TypeScript source analyzed. 8 new techniques. Key additions: RRF hybrid search (production-tested implementation), graph relationships between memories, Leiden community detection, per-type FTS with top-3 merge, multi-factor importance scoring, semantic chunking, task_context enrichment. Most important finding: BRAIN should evolve from flat vector store → typed knowledge graph. |
| 2026-04-26 | RTK | Full Rust source analyzed (hooks/, core/, learn/, discover/, filters/). 11 techniques identified. Key additions: PostToolUse output compression pipeline, TOML filter pipeline with inline tests, session JSONL mining for behavioral signals, retrieval analytics tracking, 3-level config hierarchy, compound query decomposition. Most important finding: BRAIN should compress its own MCP tool output before returning to Claude — the same architecture RTK uses for command output. |
| 2026-04-29 | Mark-XXXV | Python source analyzed (memory_manager.py, main.py). 3 techniques identified. Core gap surfaced: BRAIN has zero first-class personal/human-fact memory. All 6 existing types are code/project-centric. Key additions: human-centric memory taxonomy (identity/preference/goal/relationship types), 2-stage per-turn extraction hook (cheap YES/NO gate → full extract), structured personal context formatting with per-category caps and injection header. |
| 2026-04-30 | SocraticSkill | Full TypeScript source analyzed (record-turn.ts, pick-review.ts, detector.ts, state-io.ts, antipatterns.ts, build-journal.ts, rule.md, domains.json, algorithm.json). 4 techniques identified. Core gaps surfaced: (a) BRAIN injects top-5 semantically-similar memories with no recency decay — old important memories get buried; (b) no memory trust signal — BRAIN cannot distinguish reliable from stale/wrong memories. Key additions: Leitner spaced-repetition resurfacing, trust scoring from retrieval feedback, coverage gap detection, domain-weighted retrieval taxonomy. |
| 2026-04-30 | SocratiCode | Full TypeScript source analyzed (indexer.ts, qdrant.ts, embeddings.ts, graph-impact.ts, graph-symbols.ts, symbol-graph-store.ts, symbol-graph-cache.ts, chunking.ts, watcher.ts, context-artifacts.ts, 36 service modules, 765 tests). 6 techniques identified. Core novel findings: asymmetric task-specific embedding prefixes (search_query: / search_document:), staleness TTL differentiated by memory type, hub memory detection via co-occurrence impact radius, pinned context artifacts as a sacred memory tier, fire-and-forget async ingest with checkpoint resumability, recency-weighted RRF for time-aware score fusion. Most important finding: production-grade sharded symbol graph architecture proves lazy-loaded bounded-memory design is viable at BRAIN's scale. |
| 2026-04-30 | DL-SOCRATIS | Python/C++ source analyzed (main_net.py, run_model.py, RGMMNet.py, graph.py, coarsening.py, losses_distance.rs, CGAN_model.py, CGAN_utils.py, config.py, handle_data.py, datasetnet.py, evaluate.h, interparameters.h). 4 techniques identified. Domain: cardiac MRI deep learning — deliberately different from previous sources to surface non-obvious cross-domain patterns. Core novel findings: retrieval uncertainty band from mixture model confidence (RGMMNet), hierarchical memory coarsening from METIS graph reduction (multi-scale retrieval), anti-echo-chamber diversity buffer from CycleGAN image pool, composite multi-signal retrieval score unifying all previous scoring signals (Dice+Hausdorff hybrid loss analog). Most important finding: the composite score is the architectural synthesis that makes T2+T12+T18+T19+T27 work together instead of fighting each other. |
| 2026-05-01 | neurolinked (deep6nick/neurolinked) | Full Python source analyzed: brain.py, neurons.py, synapses.py, knowledge_store.py, sleep_consolidation.py, regions.py, sensory/text.py, claude_bridge.py, events.py, config.py. Domain: biologically-inspired neuromorphic simulation with 100K spiking neurons, STDP learning, dual storage (neural state + SQLite knowledge store). Honest assessment: most of neurolinked (Izhikevich spiking neurons, STDP synaptic weights, neuromodulator dynamics, sensory encoding) does not transfer to a text retrieval system — it's simulation machinery. Three genuine findings: (1) Co-access link strengthening — when memories A and B appear in the same search result set, increment a co-access counter and eventually add an implicit `memory_link` edge (STDP analogue operating on usage patterns rather than neural spike timing); extends R3/memory_links with unsupervised auto-creation. (2) Adaptive pruning threshold — neurolinked raises the synapse pruning threshold as the brain matures; maps to brain as: `archive_threshold = base + scale * sigmoid((total_memories - 2000) / 1000)`, so importance floors rise automatically as corpus grows rather than staying fixed. (3) Insights append-only log — distinct from saved consolidated pattern memories; when cross-session analysis (G6) fires, append to `brain_state/insights.jsonl` with `{ts, kind, title, supporting_ids, score}` rather than only saving new memory rows; insights log becomes a historical audit trail and appearance-frequency in insights feeds hub ranking (T33). What does NOT transfer: STDP itself (no neural weights in brain), Izhikevich ODE solver, neuromodulators, spiking simulation, winner-take-all competition, hash-based TF-IDF encoding (brain uses ONNX, strictly better). |
| 2026-05-01 | gbrain (garrytan/gbrain) | Full TypeScript source analyzed: hybrid.ts, dedup.ts, semantic.ts, synthesize.ts, patterns.ts, source-boost.ts, eval-capture.ts, eval.ts, schema.sql, operations.ts. Production system managing 17,888+ pages, 4,383 people, 723 companies. Most important findings: (1) Type diversity cap in search results — if >60% of top-N are the same memory type, demote the lowest-scoring excess ones; simple, directly prevents type dominance in results. (2) Source-based ranking multipliers with longest-prefix matching — different sources have different signal quality; claude_code_session should outrank PDF chunks; fits naturally into D3 brain_policies.toml. (3) Fire-and-forget query capture to eval_candidates table — logs every real query + actual result sets returned, enabling A/B replay when retrieval changes; T17 covers metric tracking but not result-set capture. (4) Cross-session patterns phase — distinct from run_reflection; looks at ≥3 accumulated reflections, runs LLM to synthesize recurring themes into meta-pattern memories with citation links back to source reflections. (5) Savitzky-Golay semantic boundary detection for chunking — more precise than T11's header/paragraph splits; embeds sentences, computes adjacent cosine distances, smooths with S-G filter, detects local maxima as topic boundaries. (6) `curated` memory flag (compiled_truth analogue) — memories explicitly saved via MCP tool get higher base importance and guaranteed result inclusion; auto-ingested memories treated differently. |
| 2026-05-03 | Phases 1–7 implementation | Mem0-grade dual-layer fact memory fully shipped. 13,224 active facts extracted from 4 sources (sessions/perplexity/obsidian/cursor). Curator processed 15,644 decisions (ADD 13,377 · MERGE 1,597 · UPDATE 173 · IGNORE 497). Salience calibration: beta=0.0 (IGNORE avg_sal=0.792 > ADD avg_sal=0.754 — no retrieval signal). Temporal decay switched to `event_time.unwrap_or(timestamp)`; 14,771 facts stamped. Fact P@1: BM25=1.000 / hybrid=0.600 (protected floor ±0.05). Research techniques implemented: semantic dedup (ML-Bio T3/T18), checkpoint resumability (SocratiCode T25), event-time recency (SocratiCode T14), stale-result exclusion (Phase 4 `exclude_superseded`), k-fold fact eval (OpenBMI T5). |
| 2026-05-01 | Google AutoML (google/automl) | Sub-projects analyzed: EfficientNetV2 (effnetv2_configs.py, hparams.py, autoaugment.py, main.py), EfficientDet (tf2/fpn_configs.py), Hero/Lion (hero/core.py, hero/model_lib.py, lion/lion_optax.py). Most important finding: AutoAugment's (operation, probability, magnitude) policy format is the right architecture for R5's query expansion — not fixed variants, but a learnable policy of query transformation operators that can be tracked and optimized over time. Second finding: EfficientNet's EMA weight smoothing maps directly to embedding blending — when a near-duplicate memory is saved (cosine >0.92 to existing), blend the embeddings with EMA rather than hard-dedup or ignore, giving temporally-consistent embeddings that evolve without discontinuity. Third finding: staged training curriculum (progressive augmentation across stages) maps to a staged ingest strategy — use high-quality source centroids (D2) to filter/dedup lower-quality sources in later stages. Fourth finding (low effort): AutoML saves the full resolved config as YAML alongside every eval result — brain's eval script saves metrics but not the config that produced them; cheap to fix, enables proper A/B comparison. Large sections of AutoML (compound scaling, NAS block search, knowledge distillation, GPU training) do not transfer — brain is retrieval and storage, not model training. |
| 2026-05-01 | Darknet/YOLO (pjreddie/darknet) | Full C source analyzed: network.c, detection_layer.c, yolo_layer.c, region_layer.c, box.c, utils.c, data.c, list.c, parser.c. Domain: real-time object detection in C — deliberately outside the AI memory/retrieval space to surface non-obvious cross-domain patterns. Most valuable finding: Soft NMS is strictly better than hard MMR (R2) for in-result deduplication — multiplicative decay preserves near-duplicate results that are still highly relevant instead of eliminating them. Second finding: per-type embedding centroids (anchor box analogue) extend T2's global mean-centering to per-type statistical profiles, enabling outlier detection and delta compression. Third finding: YOLO's .cfg config system maps directly to a `brain_policies.toml` that drives per-type TTL, min_importance, and chunk strategy — declarative and zero-code-change. Fourth finding (weak): per-query score distribution calibration (batch norm analogue) enables adaptive similarity thresholds but is over-engineered at current scale. Large portions of darknet (CUDA/GPU mirroring, spatial hashing, anchor box regression) don't transfer — brain is retrieval, not training. |
| 2026-05-01 | Ruflo (ruvnet/ruflo) | Full TypeScript/Rust multi-agent orchestration framework analyzed (313 MCP tools, 32 plugins, 100+ agents, v3.6.10). Most important finding: brain v0.2.0 already has the majority of what ruflo claims as novel — RRF hybrid search, recency weighting, mean-centering, FTS5, 3-layer progressive MCP, feedback events, job worker, reflection, SSE viewer. 8 genuine gaps confirmed: (1) `importance` field is dead weight — set once, never updated, never used in ranking; (2) MMR diversity reranking exists in Python but never auto-applied in Rust search path; (3) memory relationships table (T10) re-confirmed as architectural ceiling; (4) no access count / last_accessed_at tracking; (5) query expansion (2-3 variants before embedding) — brain embeds raw query verbatim; (6) no `human`/`user_fact` memory type (re-confirms Mark-XXXV gap); (7) no SHA256 pre-save dedup guard (only reactive LLM reflection); (8) no session round-robin diversity in results. Highest ROI: wire `importance` into RRF score + close feedback-loop bump/decay (all data already exists in `feedback_events` table). |
| 2026-05-01 | MemPalace (MemPalace/mempalace) | Full Python source analyzed: memory_store.py, temporal_graph.py, chunker.py, context_stack.py, retriever.py, identity_layer.py, write_log.py, eval/longmemeval.py. Domain: local-first AI memory system achieving 96.6% R@5 on LongMemEval benchmark via hybrid BM25+cosine, temporal knowledge graph, and 4-layer context stack. Honest assessment: hybrid retrieval and most of the context stack are already in brain. Four genuine findings after filtering: (1) Positional chunk neighbor expansion — when a chunked memory (chunk_index N) is retrieved, also surface chunk_index N±1 from the same file_path; requires adding `chunk_index INTEGER` to memories schema; directly improves Obsidian note retrieval where context spans adjacent chunks. (2) Temporal knowledge graph — separate `knowledge_facts` table with `subject, predicate, object, valid_from, valid_to, confidence, source_memory_id`; solves the contradicting-memories problem ("we use ChromaDB" then "we migrated to SQLite"); supports point-in-time queries. This is brain's most significant structural gap for factual knowledge. (3) Write-ahead log for memory saves — append-only `~/.brain/write_log.jsonl` logging every save_memory() call with `{ts, content_hash, memory_type, project, source}` (no raw content); lightweight audit trail for detecting memory poisoning; complements N3 (insights log) but serves a different purpose. (4) Static identity layer (L0) — `~/.brain/identity.md` always prepended to session context injection; ~100 tokens of user role/preferences/recurring entities always available without search; distinct from T34 (pinned architectural decisions) — this is about the user, not code. External eval target: LongMemEval benchmark at 96.6% R@5 is a concrete ceiling to measure brain against. |


---

## Ruflo Audit — 2026-05-01

**Source:** [ruvnet/ruflo](https://github.com/ruvnet/ruflo) (v3.6.10, TypeScript/Rust, MIT)
**What it is:** Multi-agent AI orchestration framework built on Claude Code — 313 MCP tools, 32 plugins, 100+ specialized agents, vector memory (AgentDB), knowledge graph, SONA neural patterns.
**Audit method:** Full README + architecture docs + key source files analyzed. brain v0.2.0 source cross-checked against every claim.

### What brain already has (no action needed)

Most of ruflo's advertised features are already in brain v0.2.0:

| ruflo feature | brain v0.2.0 status |
|---|---|
| Hybrid BM25 + dense RRF | ✅ live (`brain.rs:search()`) |
| Recency weighting (half-life decay) | ✅ T32, 730d half-life, 0.85 floor |
| Mean-centering on startup | ✅ T2, applied at `open()` |
| FTS5 Porter stemmer | ✅ `memories_fts` virtual table |
| 3-layer progressive MCP | ✅ search_index → timeline → get_observations |
| Feedback events log | ✅ `feedback_events` table |
| Job retry queue + worker | ✅ `worker.rs` (5s loop, 5-attempt cutoff) |
| LLM reflection / consolidation | ✅ every N saves |
| SSE stream + web viewer | ✅ `brain_api` + `static/index.html` |
| Privacy block stripping | ✅ `privacy.rs` |
| Tree-sitter symbol extraction | ✅ `symbols.rs` (Rust/TS/Py) |
| Provenance tracking (file_path, title) | ✅ per memory row |

### Genuine gaps confirmed

**R1 — `importance` is a dead column (Highest ROI)**

`store.rs:57` has `importance REAL DEFAULT 0.5`. It is set once at save, never updated, never read in `search()`. Brain already has everything needed to make it live:

- `feedback_events` table records accepts/rejects per `memory_id`
- `worker.rs` runs a background loop every 5s

Three wires needed:
1. `record_feedback(Accepted, memory_id)` → `UPDATE memories SET importance = MIN(0.95, importance + 0.2)`
2. `record_feedback(Rejected, memory_id)` → `UPDATE memories SET importance = MAX(0.1, importance - 0.1)`
3. Worker decay: every session end, decrement importance by 0.01 for memories with no access this session (floor 0.05, auto-archive below 0.05)
4. `brain.rs:search()`: multiply `final_score` by `importance` after recency weighting

Ruflo calls this "confidence lifecycle." All data already exists — just needs the loop closed.

**R2 — MMR diversity reranking not auto-applied**

`brain/tools/retrieval_rerank.py` exists but is explicitly marked *not applied automatically*. Top-N results today can be near-duplicates from one high-activity session. Ruflo applies MMR as a post-sort pass:

```
score = α * relevance_score - (1 - α) * max(cosine_sim_to_already_selected)
```

Add this as a post-sort step in `brain.rs:search()` before truncating to N. ~15 lines of Rust, zero new deps. Recommended α = 0.7 (favor relevance, penalize duplicates).

**R3 — Memory relationships table (re-confirms T10)**

Prior research (GitNexus T10) and now ruflo both confirm: flat vector store is the architectural ceiling. Brain has `sym:` tags from tree-sitter but no edges between memories.

Minimal schema:
```sql
CREATE TABLE memory_links (
    source_id TEXT NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
    target_id TEXT NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
    relation  TEXT NOT NULL,  -- 'calls', 'same_session', 'consolidates', 'supersedes', 'contradicts'
    weight    REAL NOT NULL DEFAULT 1.0,
    created_at TEXT NOT NULL
);
CREATE INDEX idx_memory_links_source ON memory_links(source_id);
CREATE INDEX idx_memory_links_target ON memory_links(target_id);
```

Auto-populate: `same_session` on ingest (memories sharing `session_id`), `consolidates` when reflection produces a new pattern memory, `supersedes` when a feedback-accepted correction replaces a prior memory.

Unlocks: multi-hop retrieval ("find all memories related to X"), graph-aware ranking (hub memories surface higher), dependency tracing for code memories.

**R4 — No access count or last_accessed_at**

Zero tracking of how often a memory gets retrieved. Ruflo uses access frequency as a ranking factor and for decay decisions. Two columns needed:

```sql
ALTER TABLE memories ADD COLUMN access_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE memories ADD COLUMN last_accessed_at TEXT;
```

Increment in `search()` for every returned hit. Feeds into: confidence scoring, hot-pattern detection, cold-memory decay. Low-effort, high long-term value.

**R5 — Query expansion (2-3 variants before embedding)**

Brain embeds the raw query verbatim. Ruflo generates query variants before embedding, fans out, then RRF-combines. Brain already has RRF infrastructure — the fan-out is cheap:

```
variants = [original, "how to " + original, key_noun_phrases(original)]
embed all → union candidates → RRF-combine ranks
```

No LLM cost. Improves recall for partial/fuzzy queries. Particularly useful for short queries like `"rate limiting"` or `"auth error"` where the raw embedding may miss related memories phrased differently.

**R6 — No `human` / `user_fact` memory type (re-confirms Mark-XXXV gap)**

Brain's current types: `conversation`, `solution`, `pattern`, `decision`, `project_context`, `error_lesson`. All code/project-centric. Claude Code's own auto-memory system (`~/.claude/projects/.../memory/`) saves user facts (role, preferences, skills). These should map to a dedicated `human` type in brain.

Add to `MemoryType` enum in `lib.rs`. Hook into `session_end.py` to detect and tag memories that describe the user rather than code. Enables targeted retrieval: "what do we know about the user?" without surfacing code patterns.

**R7 — No SHA256 pre-save dedup guard**

Brain's deduplication is reactive: LLM reflection fires every N saves and sees the 50 most recent memories. Trivial duplicates accumulate between reflection cycles — especially from repeated PostToolUse fires on the same file.

Add a content hash check in `save_memory()`:
```rust
let hash = sha256(content);
if self.store.content_hash_exists(&hash)? {
    return Ok(existing_id);  // idempotent
}
```

Store hash in a new `content_hash TEXT` column. Prevents exact duplicates at zero reflection cost. SHA256 of the stripped content (after privacy block removal) is deterministic.

**R8 — No session round-robin diversity**

Search results can be dominated by memories from one high-activity session (e.g., the brain build sessions have thousands of memories). Ruflo interleaves results from different `session_id`s as a post-rerank pass.

Algorithm: after MMR pass, if any session_id appears more than K times in top-N, demote lower-ranked duplicates and pull up the highest-ranked result from underrepresented sessions. Low effort, prevents one session crowding out all others.

### Priority table

| ID | Change | Effort | ROI | Location |
|---|---|---|---|---|
| R1 | Wire `importance` into RRF + feedback bump/decay + worker decay | Medium | **High** | `brain.rs`, `store.rs`, `worker.rs` |
| R2 | Auto-apply MMR in Rust search path | Low | **High** | `brain.rs:search()` |
| R3 | `memory_links` table + auto-populate | Medium | **High** | `store.rs`, ingest scripts |
| R4 | `access_count` + `last_accessed_at` columns | Low | Medium | `store.rs`, `brain.rs:search()` |
| R5 | Query expansion (2-3 variants, RRF fan-out) | Low | Medium | `brain.rs:search()` |
| R6 | `human` / `user_fact` memory type | Low | Medium | `lib.rs`, `session_end.py` |
| R7 | SHA256 pre-save dedup guard | Low | Low-Med | `brain.rs:save_memory()`, `store.rs` |
| R8 | Session round-robin diversity in results | Low | Low | `brain.rs:search()` |

### What ruflo does that brain should NOT copy

- **Byzantine consensus / federated agents** — single-user personal tool. Unnecessary.
- **WASM Agent Booster** — no sub-task routing needed. Over-engineered.
- **Multi-provider LLM failover** — brain uses one provider for reflection. Fine.
- **CRDT synchronization** — no distributed state. Not applicable.
- **313 MCP tools** — brain's 3-layer pattern is the correct response to tool count inflation.
- **Leiden community detection** — premature at 2,230 memories. Revisit at 30K+.

---

## Darknet/YOLO Audit — 2026-05-01

**Source:** [pjreddie/darknet](https://github.com/pjreddie/darknet) (C, MIT, Joseph Redmon's original YOLO implementation)
**What it is:** Real-time object detection framework. YOLO ("You Only Look Once") processes an image once through a single CNN and simultaneously predicts bounding boxes + class probabilities across a spatial grid.
**Audit method:** Full C source read: `network.c`, `detection_layer.c`, `yolo_layer.c`, `region_layer.c`, `box.c`, `utils.c`, `data.c`, `list.c`, `parser.c`. Cross-checked every candidate technique against T1–T40 and R1–R8.

### What darknet does that's already covered

Before the new findings: most of what darknet does maps to already-researched techniques.

| Darknet concept | Already covered |
|---|---|
| Hybrid score (objectness × class prob) | T40 — composite multi-signal score |
| Multi-scale feature pyramid | T38 — hierarchical memory coarsening |
| Session-level diversity | T39 — anti-echo-chamber diversity buffer |
| Batch processing + checkpoints | T35 — fire-and-forget async ingest |
| Mean-centering of feature space | T2 — embedding mean-centering |
| RRF / multi-signal ranking | T6, T32 — hybrid RRF + recency-weighted |
| Config-driven architecture | T21 — 3-level config hierarchy (partial) |

### Genuine cross-domain findings

---

**D1 — Soft NMS: multiplicative decay vs MMR's additive penalty**

**YOLO source:** `box.c — do_nms_sort()`, `box_iou()`

YOLO's standard NMS eliminates all boxes that overlap a chosen box above threshold `t`. Soft NMS (Bodla et al. 2017, integrated into darknet variants) replaces the hard elimination with a decay:

```c
// Hard NMS (standard darknet):
if (box_iou(a, dets[j].bbox) > thresh) {
    dets[j].prob[k] = 0;  // hard kill
}

// Soft NMS equivalent:
float iou = box_iou(a, dets[j].bbox);
dets[j].prob[k] *= exp(-(iou * iou) / sigma);  // Gaussian decay, not zero
```

**How this differs from R2 (MMR) and T39:**
- R2 (MMR) is an *additive* penalty: `score = α*relevance - (1-α)*max_sim`. Subtracts a fixed proportion. A highly-relevant near-duplicate gets penalized the same as a marginally-relevant one.
- T39 (diversity buffer) is *session-scoped*: tracks what was already surfaced across turns. Different problem.
- Soft NMS is *multiplicative and continuous*: near-duplicates are decayed proportional to their actual similarity, not eliminated. A result at 0.95 cosine similarity gets ~40% decay; at 0.70 similarity it gets ~5% decay. High-relevance near-duplicates can still outrank low-relevance fresh results.

**BRAIN gap:** R2 (MMR) is planned but not yet implemented. When it is, implement soft NMS instead of hard MMR. The practical difference: if a user asks "how do we handle rate limiting?" and the brain has 3 near-identical solution memories (copied from the same session), soft NMS surfaces the best one at full score and the others at decayed scores — which may still outrank unrelated results if they're genuinely the right answer.

**BRAIN implementation:**

```rust
// In brain/rust/src/brain.rs — post-sort pass before truncating to n
// Called after RRF scoring, before returning results.

fn soft_nms_rerank(results: &mut Vec<(SearchResult, f32)>, sigma: f32) {
    // results already sorted descending by score
    // For each result, decay all subsequent results by their similarity to it
    for i in 0..results.len() {
        let emb_i = /* get embedding for results[i].id */;
        for j in (i+1)..results.len() {
            let emb_j = /* get embedding for results[j].id */;
            let sim = cosine_similarity(&emb_i, &emb_j);
            let decay = (-sim * sim / sigma).exp();  // Gaussian kernel
            results[j].1 *= decay;
        }
        // Re-sort after each pick (or do one pass, which is faster and close enough)
    }
    results.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal));
}
```

Recommended `sigma = 0.5` (decay 0.25× at similarity 1.0, 0.86× at 0.5, minimal at 0.3).

**Note:** Requires embeddings to be returned from the index search for the rerank pass. The index already returns cosine candidates with distances — embeddings can be fetched from SQLite for the top candidates. Only needed for top ~20 candidates, not the full corpus.

**Implementation complexity:** Low-Medium. Needs embedding fetch for candidates + one rerank pass.

---

**D2 — Per-type embedding centroids (anchor box analogue)**

**YOLO source:** `yolo_layer.c — l.biases[]`, `get_yolo_box()`, `region_layer.c`

YOLO's anchor boxes encode learned priors about typical object shapes. During inference, the network predicts *offsets from anchors*, not absolute positions. This means: (1) predictions are constrained to plausible values, (2) outlier predictions are easily detectable, (3) you can delta-encode predictions compactly.

```c
// Prediction is offset from anchor, not absolute:
b.w = exp(x[index + 2*stride]) * biases[2*n] / w;  // anchor-scaled
b.h = exp(x[index + 3*stride]) * biases[2*n+1] / h;
```

**Mapping to BRAIN:**

T2 computes a single global mean across all memories and subtracts it. That's corpus-wide mean-centering. But different memory types cluster in different regions of embedding space — a code solution embedding and a conversation embedding are structurally different. Their type-specific centroids are more useful than the global mean.

**What per-type centroids enable:**

1. **Outlier detection at ingest time** — if a new memory's embedding is >3σ from its type's centroid (in L2 distance), flag it. Likely ingest noise, a mis-typed memory, or a corrupt document. Currently brain has no outlier detection at all.

2. **Delta compression** — instead of storing a 768-float embedding (3072 bytes), store the centroid_id + a delta vector (the difference from the centroid). If the centroid is close to the embedding, the delta is sparse and compresses well. At 2.2K memories this doesn't matter; at 100K+ it saves significant storage.

3. **Type-aware query routing** — before searching, compute the query embedding's distance to each type centroid. If the query is much closer to the "solution" centroid than to "conversation", bias the search toward solution-type memories. Adds signal without the full RLDA projection complexity of T1.

**BRAIN implementation:**

```rust
// New table in store.rs:
// CREATE TABLE type_centroids (
//     memory_type TEXT PRIMARY KEY,
//     centroid BLOB NOT NULL,        -- 768-dim mean embedding
//     std_dev REAL NOT NULL,         -- mean L2 distance from centroid
//     count INTEGER NOT NULL,        -- number of memories used to compute
//     updated_at TEXT NOT NULL
// );

// Recompute periodically (in worker.rs, e.g. every 500 saves):
fn recompute_centroids(store: &MetadataStore) -> Result<(), BrainError> {
    for memory_type in MemoryType::all() {
        let embeddings = store.get_embeddings_by_type(memory_type)?;
        if embeddings.len() < 10 { continue; }
        let centroid = mean_embedding(&embeddings);
        let std_dev = mean_l2_distance(&embeddings, &centroid);
        store.upsert_centroid(memory_type, &centroid, std_dev, embeddings.len())?;
    }
    Ok(())
}

// Check at save time (in Brain::save_memory):
if let Some(centroid) = self.store.get_centroid(memory_type)? {
    let dist = l2_distance(&embedding, &centroid.embedding);
    if dist > centroid.std_dev * 3.0 {
        eprintln!("[brain] outlier memory flagged: dist={:.3}, threshold={:.3}", 
                  dist, centroid.std_dev * 3.0);
        // tag with "outlier" — don't block save, just flag
    }
}
```

**Implementation complexity:** Low-Medium. New table + background recompute job + optional ingest-time check.

---

**D3 — Declarative memory policy config (YOLO .cfg analogue)**

**YOLO source:** `parser.c — parse_network_cfg()`, `cfg/*.cfg` files

YOLO's `.cfg` files define the entire network architecture declaratively — layer types, filter counts, strides, learning rates, loss weights. The parser builds the network at runtime. Zero code changes are needed to try a different architecture: just edit the `.cfg`.

```ini
[net]
batch=128
learning_rate=0.001
decay=0.0005

[convolutional]
filters=32
size=3
stride=1
activation=leaky

[yolo]
mask = 0,1,2
anchors = 10,13, 16,30, 33,23
classes=80
jitter=.3
ignore_thresh = .7
```

**BRAIN gap:**

Brain's per-type behavior is baked into code:
- T36 (staleness TTL) proposes per-type TTLs but they're hardcoded constants
- T24 (human-centric taxonomy) requires a code change to add a new type
- Chunk strategies (`OBSIDIAN_CHUNK_STRATEGY`) are env vars — one setting, all types

There is no place to say "conversation memories expire after 90 days, solution memories never expire, pattern memories get boosted by 1.3×, human memories have a minimum importance of 0.7."

**BRAIN application: `brain_policies.toml`**

A single file (not compiled in, not env vars) that drives per-type retrieval and ingest behavior:

```toml
[defaults]
ttl_days = 0          # 0 = never expire
min_importance = 0.0
importance_boost = 1.0
chunk_strategy = "headers"
chunk_words = 1500

[memory_type.solution]
ttl_days = 0          # solutions don't expire
min_importance = 0.1
importance_boost = 1.2

[memory_type.conversation]
ttl_days = 180        # conversations expire after 6 months
min_importance = 0.05
importance_boost = 0.9

[memory_type.human]
ttl_days = 0          # user facts are permanent
min_importance = 0.5  # floor — human facts below 0.5 importance get archived
importance_boost = 1.5  # always boost user facts in retrieval

[memory_type.pattern]
ttl_days = 0
min_importance = 0.2
importance_boost = 1.1

[memory_type.error_lesson]
ttl_days = 365
min_importance = 0.15
importance_boost = 1.0

[memory_type.project_context]
ttl_days = 90         # project context stales quickly
min_importance = 0.1
chunk_strategy = "paragraph"
```

**How it integrates:**
- `worker.rs` background job reads the policy and applies TTL expiry (marks memories below min_importance as archived, never deletes)
- `brain.rs:search()` reads `importance_boost` per type and applies it as a final multiplier after the composite score
- `09_ingest_obsidian.py` reads `chunk_strategy` and `chunk_words` per type instead of from env vars
- Adding a new memory type: edit `brain_policies.toml`, zero code changes

**Why this is not covered by T21 (3-level config hierarchy):** T21 is about the mechanism for config precedence (compiled defaults → global file → per-project override). D3 is about *what* gets configured — per-type memory behaviors that don't exist anywhere today.

**Implementation complexity:** Low. Parse TOML at startup (Rust `toml` crate already in Cargo.toml via other deps). Cache parsed policies in a `Arc<PolicyConfig>` passed to Brain. Worker and search path read from it.

---

**D4 — Per-query score distribution calibration (batch norm analogue) [Weak]**

**YOLO source:** `batchnorm_layer.c — mean_cpu(), variance_cpu(), scal_cpu()`, `l.rolling_mean`, `l.rolling_variance`

Batch normalization maintains exponential moving averages of per-channel mean and variance. During inference, it normalizes activations to have zero mean and unit variance — preventing any single channel from dominating via scale.

```c
// During training: track running stats
scal_cpu(l.out_c, .99, l.rolling_mean, 1);
axpy_cpu(l.out_c, .01, l.mean, 1, l.rolling_mean, 1);  // EMA update

// During inference: normalize using running stats
normalize_cpu(l.output, l.rolling_mean, l.rolling_variance, ...);
```

**BRAIN mapping:** Track the rolling distribution of similarity scores returned per query type (or per memory type). Use it to normalize scores before applying thresholds. A cosine similarity of 0.82 means something different when searching `solution` memories (tight cluster, 0.82 is median) vs. `conversation` memories (spread cluster, 0.82 is 95th percentile).

**Why this is weak:** T37 (retrieval uncertainty band) already addresses result confidence from a different angle. At 2,230 memories the score distributions are stable. This becomes valuable at 20K+ memories when type distributions diverge significantly. File as future work.

---

### What darknet does that brain should NOT copy

| Darknet concept | Why not applicable |
|---|---|
| GPU/CUDA memory mirroring | brain is CPU-only, local tool |
| Backpropagation / weight updates | brain doesn't train a model, it stores and retrieves |
| Anchor box regression | spatial bounding box math — no analogue in text embedding space |
| Convolutional layers | feature extraction is handled by the ONNX embedder, not brain |
| Learning rate schedules | no training loop in brain |
| CUDA kernel dispatch | not applicable |
| Multi-GPU data parallelism | single-machine personal tool |

### Priority table

| ID | Change | Effort | ROI | Location |
|---|---|---|---|---|
| D1 | Soft NMS rerank (replaces planned MMR/R2) | Low-Med | High | `brain.rs:search()` |
| D2 | Per-type embedding centroids + outlier detection | Low-Med | Medium | `store.rs`, `worker.rs` |
| D3 | `brain_policies.toml` declarative per-type config | Low | Medium | new file, `brain.rs`, `worker.rs` |
| D4 | Per-query score distribution calibration | Medium | Low (now) | future work |

**D1 supersedes R2:** When implementing in-result deduplication, build Soft NMS instead of MMR. Same effort, better behavior for near-duplicate cases.

---

## Google AutoML Audit — 2026-05-01

**Source:** [google/automl](https://github.com/google/automl) (Python/JAX/TF2, Apache 2.0)
**Sub-projects:** EfficientNetV2, EfficientDet, Hero (symbolic program search), Lion optimizer
**Key files read:** `efficientnetv2/autoaugment.py` (723 LOC), `efficientnetv2/hparams.py`, `efficientnetv2/main.py`, `efficientnetv2/effnetv2_configs.py`, `hero/core.py`, `hero/model_lib.py`, `lion/lion_optax.py`
**Audit method:** Full source analysis. Every candidate pattern checked against T1–T40, R1–R8, D1–D4 before including.

### What AutoML does that's already covered

| AutoML concept | Already covered |
|---|---|
| Layered config override system | T21 — 3-level config hierarchy; D3 — brain_policies.toml |
| Composite multi-objective scoring | T40 — composite multi-signal retrieval score |
| Progressive/staged difficulty | T38 — hierarchical memory coarsening |
| Checkpoint-based best model selection | T35 — fire-and-forget async ingest + checkpoints |
| EMA for weight smoothing | T32 — recency weighting (related) |
| Retrieval precision/recall eval | T5 — cross-validation eval framework |
| Query variants for recall | R5 — query expansion (partial) |

### Genuine cross-domain findings

---

**A1 — AutoAugment-style query augmentation policy**

**Source:** `autoaugment.py:33-65` — `policy_v0()`, operation library, `(op, prob, magnitude)` tuples; `autoaugment.py:144-450` — 25 sub-policies, each 2-op sequences

AutoAugment doesn't hardcode augmentations. It defines a **searchable policy**: a sequence of operations, each with independent probability and magnitude. During training, one sub-policy is randomly sampled per batch:

```python
policy_v0() = [
    [('Equalize', 0.8, 1), ('ShearY', 0.8, 4)],   # sub-policy 1
    [('Color', 0.4, 9), ('Equalize', 0.6, 3)],    # sub-policy 2
    ...  # 25 sub-policies total
]
# Each element: (operation_name, apply_probability, magnitude 0–10)
```

The policy itself was discovered by an RL controller — but the *representation* is what matters here.

**How this extends R5 (query expansion):**

R5 says "generate 2-3 fixed query variants before embedding, RRF-combine." That's correct but static. AutoAugment's format gives brain a *learnable*, *tracked* structure for query transformation:

Define a library of query transformation ops (analogous to AutoAugment's 25 image ops):

```toml
# brain_query_ops.toml
[[ops]]
name = "prepend_how_to"
template = "how to {query}"
default_prob = 0.6

[[ops]]
name = "extract_key_nouns"
# strips verbs/stop words, keeps nouns + technical terms
default_prob = 0.8

[[ops]]
name = "add_file_context"
# if query references a file path, expand with filename + extension
default_prob = 0.5

[[ops]]
name = "rephrase_as_error"
template = "{query} error"
default_prob = 0.4

[[ops]]
name = "add_project_scope"
template = "{project} {query}"
default_prob = 0.7
```

A policy selects 2 ops and applies them with their probabilities:

```rust
// In brain/rust/src/brain.rs — query expansion before embedding
fn expand_query(query: &str, policy: &QueryPolicy) -> Vec<String> {
    let mut variants = vec![query.to_string()];  // always include original
    for op in policy.sample_ops(2) {             // sample 2 ops by probability
        if let Some(variant) = op.apply(query) {
            variants.push(variant);
        }
    }
    variants
}

// Embed all variants, union cosine+BM25 candidates, RRF-combine ranks
// Already have RRF infrastructure — fan-out is the only addition
```

**Why this is better than fixed variants (R5):** The ops are tracked per feedback event. If `prepend_how_to` variants consistently produce accepted results, boost its probability. If `rephrase_as_error` never helps, decay it. Ties into the confidence lifecycle (R1). The policy becomes a learned artifact of brain's own usage patterns.

**Implementation complexity:** Low-Medium. Define ops as enum in Rust, policy as config, sample + apply at search time. Feedback-driven probability update is a background job.

---

**A2 — EMA embedding blending for near-duplicate memories**

**Source:** `efficientnetv2/main.py:345-350` — `ema_decay`, `ExponentialMovingAverage`; `hero/model_lib.py:200-230` — KL distillation loss with `stop_gradient`

EfficientNet maintains two sets of weights: the *training weights* (updated each step) and *EMA weights* (exponentially smoothed). EMA weights are used for evaluation and as the final model — they're smoother, more stable, less prone to overfitting to the last batch:

```python
ema = tf.train.ExponentialMovingAverage(decay=config.train.ema_decay)
# ema_weight = 0.9999 * ema_weight + 0.0001 * current_weight
```

**BRAIN gap (extends R7):**

R7 (SHA256 dedup guard) prevents exact duplicates. But brain has many *near-duplicates* — the same concept described slightly differently across sessions, which SHA256 won't catch. Currently these accumulate as separate memories until LLM reflection deletes them (T40 cycles). Hard deletion (reflection) is lossy — if the two near-duplicates each captured a different nuance, deleting one loses information.

**EMA blending as a soft alternative:**

When `save_memory` is called and the new embedding has cosine similarity > 0.92 to an existing memory of the same type and project:
- Instead of creating a new entry (accumulates duplicates)
- Instead of skipping (R7 — may lose new nuance)
- **Blend**: update the existing memory's embedding with EMA: `emb = α * new_emb + (1-α) * old_emb`; append new content to existing content (or take the longer/more-informative version)

```rust
// In brain/rust/src/brain.rs — save_memory()
const EMA_BLEND_THRESHOLD: f32 = 0.92;
const EMA_ALPHA: f32 = 0.3;  // new embedding weight: 30% new, 70% existing

fn save_or_blend(
    &self,
    content: &str,
    embedding: &[f32],
    memory_type: MemoryType,
    project: &str,
    // ...
) -> Result<String, BrainError> {
    // Quick nearest-neighbor check — only top-1, no n*10 over-fetch
    let top = self.index.lock()?.search(embedding, 1);
    if let Some((existing_id, dist)) = top.first() {
        if *dist < (1.0 - EMA_BLEND_THRESHOLD) {  // cosine dist < 0.08 → sim > 0.92
            let existing = self.store.get_memory(existing_id)?;
            if let Some(mem) = existing {
                if mem.metadata.memory_type == memory_type 
                    && mem.metadata.project == project {
                    // Blend embedding
                    let blended: Vec<f32> = mem.embedding.as_ref()
                        .map(|old| old.iter().zip(embedding)
                            .map(|(o, n)| (1.0 - EMA_ALPHA) * o + EMA_ALPHA * n)
                            .collect())
                        .unwrap_or_else(|| embedding.to_vec());
                    // Take longer content (more informative)
                    let merged_content = if content.len() > mem.content.len() {
                        content
                    } else {
                        &mem.content
                    };
                    self.store.update_memory_embedding(existing_id, &blended, merged_content)?;
                    self.index.lock()?.insert(existing_id, &blended);
                    return Ok(existing_id.clone());
                }
            }
        }
    }
    // No near-duplicate — normal save
    // ...
}
```

**Why EMA over hard merge:** The blended embedding represents the memory's *evolving* meaning across sessions. If the concept was discussed 5 times with slightly different framing, the EMA embedding is a weighted centroid of all framings — better generalization than any single phrasing.

**Implementation complexity:** Low-Medium. One top-1 similarity check before save (already done in the index), EMA vector math, one UPDATE instead of INSERT for near-duplicates.

---

**A3 — Staged ingest curriculum**

**Source:** `efficientnetv2/main.py:441-479` — progressive training with `ram_list`, `mixup_list`, `image_size` ramp; `np.linspace(5, config.data.ram, total_stages)`

EfficientNetV2's staged training runs in 4 phases: small images + weak augmentation → large images + strong augmentation. Each stage uses previous-stage learning to handle harder examples:

```python
ram_list   = np.linspace(5, config.data.ram, total_stages)   # augmentation strength
mixup_list = np.linspace(0, config.data.mixup_alpha, total_stages)
image_size = int(ibase + (input_image_size - ibase) * ratio)  # resolution ramp
```

**BRAIN gap:**

Brain's bootstrap ingest runs each source independently in sequence. `07_ingest_claude_code.py` doesn't know about what `09_ingest_obsidian.py` just ingested. Each ingest stage starts from scratch — no cross-stage signal.

**Staged ingest: using earlier stages to filter later stages**

After computing per-type centroids (D2), use them to make later ingest stages smarter:

**Stage 1 (high-quality foundation):** Ingest `claude_code_session` and `perplexity` sources first. These are the highest-signal sources (real problem-solving, real decisions). After Stage 1, compute type centroids for `solution` and `pattern` types.

**Stage 2 (guided dedup):** Ingest `cursor_history` and `claw_code`. Before saving each memory, check its distance to existing Stage 1 centroids. If it falls within 1σ of the centroid (very similar to what Stage 1 already captured), apply a higher blend threshold (EMA, A2) rather than saving a new entry. Stage 1 knowledge filters Stage 2 noise.

**Stage 3 (context expansion):** Ingest `obsidian` vault and books. These are the lowest-signal sources (reference material, not decisions). Only save memories whose embeddings are **outside** the Stage 1/2 centroids by > 2σ — i.e., memories that add genuinely new coverage rather than paraphrasing what's already known.

```python
# In bootstrap/09_ingest_obsidian.py (new logic)
centroids = brain_api.get_centroids()  # GET /v1/centroids (new endpoint)

for chunk in obsidian_chunks:
    emb = embed(chunk.content)
    type_centroid = centroids.get(chunk.memory_type)
    if type_centroid:
        dist = l2_distance(emb, type_centroid.embedding)
        if dist < type_centroid.std_dev * 1.5:
            # Too close to existing knowledge — skip or blend
            continue  # or EMA blend via save_or_blend()
    save(chunk)
```

**Why this matters:** The current corpus has 206 raw PDF chunks for `ocreamer` project (identified as ingest noise in T5+T2 results — P@1=0.500 ceiling). A staged approach would filter those chunks against existing high-quality project_context memories and only keep the ones that add coverage. No LLM needed — just centroid distance math.

**Implementation complexity:** Medium. Requires centroid API endpoint (extends D2), per-stage threshold config (extends D3), modified ingest scripts.

---

**A4 — Config snapshot saved alongside eval results**

**Source:** `efficientnetv2/main.py:386` — `config.save_to_yaml(os.path.join(FLAGS.model_dir, 'config.yaml'))`; `hparams.py:144-153`

AutoML saves the fully-resolved config (after all overrides) as YAML next to every checkpoint and eval result. This is routine hygiene in ML but brain doesn't do it.

**BRAIN gap:**

`brain/eval/last_report.json` contains retrieval metrics (recall@k, MRR, first_correct_rank) but not the config that produced them:
- Which embedding model?
- What RRF K value?
- What recency half-life?
- Soft NMS sigma?
- Which query ops policy?

When comparing two eval runs — e.g., before/after adding Soft NMS (D1) — there is no record of what changed. The comparison is manual.

**Fix:** Extend `retrieval_eval.py` to snapshot the active brain config alongside metrics:

```python
# brain/tools/retrieval_eval.py — add to report output
report = {
    "timestamp": datetime.utcnow().isoformat(),
    "corpus_size": stats["total_memories"],
    "config_snapshot": {
        "embedding_model": os.getenv("BRAIN_ONNX_PATH", "mock"),
        "rrf_k": 60,               # from brain.rs constant
        "recency_half_life_days": 730,
        "soft_nms_sigma": 0.5,     # when D1 is implemented
        "query_expansion_ops": policy.active_ops(),  # when A1 is implemented
        "embedding_dims": 768,
    },
    "metrics": {
        "recall_at_1": ...,
        "recall_at_5": ...,
        "mrr": ...,
    }
}
# Write to brain/eval/reports/YYYY-MM-DD_HH-MM-SS.json (not gitignored)
# last_report.json symlinks to latest
```

Low effort. Makes every eval result reproducible and comparable.

**Implementation complexity:** Low. ~20 lines in retrieval_eval.py.

---

### What AutoML does that brain should NOT copy

| AutoML concept | Why not applicable |
|---|---|
| Neural Architecture Search | brain uses a fixed pre-trained ONNX model, doesn't train |
| Compound scaling (width/depth/resolution) | no model training loop |
| Knowledge distillation (KL loss) | requires training; brain uses pre-trained embedder |
| Learning rate schedules | no gradient descent in brain |
| NAS block encoding strings | clever but no search space to define |
| Hero symbolic program search | research-level; overkill for query policy search |
| Multi-GPU data parallelism | single-machine personal tool |
| ImageNet pretrained checkpoints | not applicable |

### Priority table

| ID | Change | Effort | ROI | Location |
|---|---|---|---|---|
| A1 | AutoAugment-style query op policy (extends R5) | Low-Med | High | `brain.rs:search()`, new config file |
| A2 | EMA embedding blending for near-duplicates | Low-Med | High | `brain.rs:save_memory()`, `store.rs` |
| A3 | Staged ingest curriculum (uses D2 centroids) | Medium | Medium | bootstrap ingest scripts, new `/v1/centroids` endpoint |
| A4 | Config snapshot saved with eval results | Low | Low | `brain/tools/retrieval_eval.py` |

**Dependency note:** A3 depends on D2 (per-type centroids). Implement D2 first. A1's probability learning depends on R1 (importance/feedback lifecycle). Implement R1 first.

---

## gbrain Audit — 2026-05-01

**Source:** [garrytan/gbrain](https://github.com/garrytan/gbrain) (TypeScript, MIT, v0.25.0)
**What it is:** Production-grade AI knowledge management system by Garry Tan (YC President). Manages 17,888+ pages, 4,383 people entities, 723 companies. Hybrid search, job queue, dream cycles, MCP server — same problem space as brain.
**Key files read:** `src/core/search/hybrid.ts`, `src/core/search/dedup.ts`, `src/core/chunkers/semantic.ts`, `src/core/cycle/synthesize.ts`, `src/core/cycle/patterns.ts`, `src/core/search/source-boost.ts`, `src/core/eval-capture.ts`, `src/core/search/eval.ts`, `src/schema.sql`, `src/core/operations.ts`
**Audit method:** Full source analysis. Checked every candidate against T1–T40, R1–R8, D1–D4, A1–A4 before including.

### What gbrain does that's already covered

| gbrain concept | Already covered |
|---|---|
| RRF hybrid search (keyword + vector) | T6, T32 — done in brain.rs |
| BM25 / FTS keyword search | T6 — SQLite FTS5 live |
| Tree-sitter symbol extraction | `symbols.rs` — Rust/TS/Py |
| Query expansion | R5, A1 — planned |
| Content-hash dedup (file level) | T35, R7 |
| Job queue + worker | `worker.rs` |
| LLM reflection / consolidation | `run_reflection()` |
| Retrieval eval (P@k, MRR, recall@k) | T5 — `retrieval_eval.py` |
| Session export + ingest | `session_end.py`, `07_ingest` |
| Privacy / injection safety | `privacy.rs` |
| Semantic chunking concept | T11 — AST-aware chunking |

### Genuine findings

---

**G1 — Savitzky-Golay semantic boundary detection for chunking**

**Source:** `src/core/chunkers/semantic.ts` — S-G filter, window=5, 3rd-order polynomial

T11 (AST-aware chunking from GitNexus) proposes splitting at "semantic boundaries: paragraph breaks, section headings." That's heuristic. gbrain's semantic chunker implements a data-driven version:

```
1. Split document into sentences
2. Embed each sentence (rolling window of N sentences for context)
3. Compute cosine distance between adjacent sentence embeddings
   → High distance = topic shift candidate
4. Smooth the distance curve with Savitzky-Golay filter
   → Window size: 5, polynomial order: 3
   → Eliminates false positives from single-sentence digressions
5. Detect local maxima in the smoothed curve
   → Each local maximum is a chunk boundary
6. Fallback: recursive splitting if <4 sentences
```

The S-G filter is the key insight. Without smoothing, single-sentence asides (parenthetical remarks, citations) create false maxima. The filter averages across 5 sentences while preserving real boundaries.

**BRAIN gap:** Brain's Obsidian ingest (`09_ingest_obsidian.py`) uses either `headers` (split on markdown headings) or `paragraph` (merge paragraphs). Both are structure-based. For Obsidian notes with long narrative sections and no headings, both strategies create either one giant chunk (bad recall) or arbitrary paragraph splits (misses semantic units). Session ingest (`07_ingest_claude_code.py`) creates one memory per exchange — no sub-exchange chunking at all.

**BRAIN application:**

Add as a third chunking strategy: `OBSIDIAN_CHUNK_STRATEGY=semantic` (D3 brain_policies.toml per type).

```python
# brain/bootstrap/semantic_chunker.py
import numpy as np
from scipy.signal import savgol_filter

def semantic_chunk(text: str, embedder, window: int = 5, poly: int = 3) -> list[str]:
    sentences = split_sentences(text)
    if len(sentences) < 4:
        return [text]  # fallback
    
    # Embed each sentence
    embeddings = [embedder.embed(s) for s in sentences]
    
    # Cosine distance between adjacent sentences
    distances = [
        1 - cosine_similarity(embeddings[i], embeddings[i+1])
        for i in range(len(embeddings) - 1)
    ]
    
    # Smooth with Savitzky-Golay
    if len(distances) >= window:
        smoothed = savgol_filter(distances, window_length=window, polyorder=poly)
    else:
        smoothed = distances
    
    # Local maxima → boundaries
    from scipy.signal import argrelextrema
    boundary_indices = argrelextrema(smoothed, np.greater)[0]
    
    return split_at_indices(sentences, boundary_indices)
```

**Note:** This requires N sentence embeddings per document — more ONNX calls than header chunking. Recommended only for `OBSIDIAN_CHUNK_STRATEGY=semantic` mode, not the default. Good default for long-form narrative notes; header mode remains best for structured notes.

**Implementation complexity:** Low-Medium. Python, uses scipy (already likely available). New chunking function + D3 policy to enable per note type.

---

**G2 — Type diversity cap in search results**

**Source:** `src/core/search/dedup.ts:Layer3` — `typeCounts`, 60% cap enforced per result set

gbrain's dedup layer 3: after RRF and Soft-NMS-style dedup, if more than 60% of remaining results are the same `page_type`, demote the lowest-scoring excess ones to make room for other types.

```typescript
const typeCounts = new Map<string, number>();
const filtered = deduped.filter(result => {
    const type = result.page_type;
    const count = typeCounts.get(type) ?? 0;
    const maxAllowed = Math.ceil(deduped.length * 0.6); // 60% cap
    if (count >= maxAllowed) return false;
    typeCounts.set(type, count + 1);
    return true;
});
```

**BRAIN gap:** Brain currently returns top-N by RRF score regardless of type distribution. With 2,230 memories, `solution` type has 1,218 entries (54% of corpus). Any moderately technical query can return 4-5 solutions and 0 conversations — even when a conversation from the same session would add context. T39 (session diversity buffer) penalizes already-surfaced IDs but doesn't enforce type-level balance.

**BRAIN application:** Add a post-sort type diversity pass in `brain.rs:search()` before truncating to N. Simple, fast, no DB changes:

```rust
fn apply_type_diversity_cap(
    mut results: Vec<(SearchResult, f32)>,
    cap_fraction: f32,  // 0.6
) -> Vec<(SearchResult, f32)> {
    let max_per_type = ((results.len() as f32) * cap_fraction).ceil() as usize;
    let mut type_counts: std::collections::HashMap<String, usize> = Default::default();
    results.retain(|(r, _)| {
        let type_key = format!("{:?}", r.metadata.memory_type);
        let count = type_counts.entry(type_key).or_insert(0);
        if *count >= max_per_type { return false; }
        *count += 1;
        true
    });
    results
}
```

Apply after Soft NMS (D1), before final truncation to N. Cap fraction configurable via D3 brain_policies.toml.

**Implementation complexity:** Low. ~15 lines in `brain.rs:search()`. No schema changes.

---

**G3 — Source-based ranking multipliers with longest-prefix matching**

**Source:** `src/core/search/source-boost.ts` — `buildSourceFactorCase()`, longest-prefix matching; `GBRAIN_SOURCE_BOOST` env var

gbrain assigns a boost multiplier per source prefix. The multiplier is inlined as a SQL CASE expression at query time. Longest-prefix wins — so `claude_code/session/` overrides `claude_code/` which overrides the default:

```typescript
// Sorted by prefix length descending (longest-prefix matching)
const boosts = [
    { prefix: 'originals/',    factor: 1.5 },
    { prefix: 'concepts/',     factor: 1.4 },
    { prefix: 'meetings/',     factor: 1.1 },
    { prefix: 'openclaw/chat/', factor: 0.7 },
    { prefix: 'daily/',        factor: 0.6 },
];

// Inlined as SQL CASE:
// CASE WHEN slug LIKE 'originals/%' THEN 1.5
//      WHEN slug LIKE 'concepts/%'  THEN 1.4
//      ...
//      ELSE 1.0 END
```

**BRAIN gap:** Brain has no source-based boost. All sources are treated equally in RRF scoring. But the signal quality varies dramatically by source:

| Source | Signal quality | Rationale |
|---|---|---|
| `claude_code_session` | High (1.3×) | Real problem-solving decisions |
| `perplexity` | High (1.2×) | Researched answers |
| `cursor_history` | Medium (1.0×) | Raw conversation, variable quality |
| `claw_code` | Medium (1.0×) | Claude.ai exports |
| `obsidian` | Medium (0.9×) | Reference notes, less specific |
| `obsidian_books` | Low (0.7×) | Generic book content |
| `reflection` | Medium (1.0×) | Consolidated, but synthetic |

A PDF chunk about "cloud architecture" should rank lower than a session memory about "we decided to use Redis for rate limiting" when the query is about architecture decisions for this project.

**BRAIN application:** Add `source_boost` to D3 `brain_policies.toml` and apply in `brain.rs:search()` as a final multiplier:

```toml
# brain_policies.toml
[source_boost]
"claude_code_session" = 1.3
"perplexity" = 1.2
"reflection" = 1.0
"cursor_history" = 1.0
"claw_code" = 1.0
"obsidian" = 0.9
"obsidian_books" = 0.7
```

```rust
// In brain.rs:search() — apply after composite score, before truncation
let boost = self.policy.source_boost_for(&memory.metadata.source);
final_score *= boost;
```

No DB changes. Longest-prefix matching is only needed if sources get hierarchical prefixes — for brain's flat source enum, direct match is fine.

**Implementation complexity:** Low. Extends D3 config + one multiply in search path.

---

**G4 — Fire-and-forget query capture for real-world eval replay**

**Source:** `src/core/eval-capture.ts` — async non-blocking insert; `GBRAIN_EVAL_CAPTURE=1`; `src/core/search/eval.ts` — `replayEval()`

T17 (retrieval analytics) covers logging query count, latency, hit rates. gbrain goes further: when `EVAL_CAPTURE=1`, every search call logs the full result set to `eval_candidates`:

```typescript
async function captureEval(query, strategy, results, latency_ms) {
    // Fire-and-forget — await not called at call site
    engine.logEvalCandidate({
        query:      query.slice(0, 50_000),
        strategy:   strategy,           // 'keyword' | 'vector' | 'hybrid'
        results:    results.map(r => ({ slug: r.slug, score: r.score })),
        latency_ms: latency_ms,
        timestamp:  new Date(),
    }).catch(err => console.warn('eval capture failed:', err));
}
```

Then `replayEval(new_strategy)` reruns every captured query with a different strategy and compares result sets:

```typescript
async function replayEval(newStrategy: Strategy): Promise<EvalReport> {
    const captured = await engine.listEvalCandidates();
    const reports = await Promise.all(captured.map(async c => {
        const newResults = await engine.search(c.query, { strategy: newStrategy });
        return diffResultSets(c.results, newResults);
    }));
    return aggregateMetrics(reports);
}
```

**BRAIN gap:** Brain's `retrieval_eval.py` uses a manually-curated gold set (`brain/eval/gold.jsonl`). Gold sets require manual effort to maintain and don't capture the actual real-world query distribution. The real queries come from: session_start.py (project name), brain_user_prompt_submit (user prompts), MCP search_brain calls. None of these are logged anywhere beyond the search result.

**BRAIN application:** Add an `eval_captures` table and optional capture mode to `brain_api`:

```sql
CREATE TABLE IF NOT EXISTS eval_captures (
    id TEXT PRIMARY KEY,
    query TEXT NOT NULL,
    strategy TEXT NOT NULL,  -- 'rrf_hybrid' | 'cosine_only' | 'bm25_only'
    result_ids TEXT NOT NULL, -- JSON array of [id, score] pairs, top-20
    latency_ms INTEGER,
    captured_at TEXT NOT NULL,
    session_id TEXT
);
```

```rust
// In brain/rust/src/bin/brain_api.rs — POST /v1/search
// If BRAIN_EVAL_CAPTURE=1:
if config.eval_capture {
    let capture = EvalCapture { query, strategy: "rrf_hybrid", result_ids, latency_ms };
    tokio::spawn(async move { store.insert_eval_capture(capture).await });  // fire-and-forget
}
```

New endpoint: `POST /v1/eval/replay` — reruns all captured queries with current scoring params, returns precision delta vs. captured baseline. Enables confident "did this change help?" answers with real queries, not synthetic gold sets.

**Implementation complexity:** Low-Medium. New table, optional capture in search handler, replay endpoint.

---

**G5 — `curated` memory flag (compiled_truth analogue)**

**Source:** `src/schema.sql` — `compiled_truth BOOLEAN DEFAULT FALSE`; `src/core/search/hybrid.ts` — 2.0× boost; guaranteed inclusion in dedup layer 5

gbrain's `compiled_truth` flag marks pages as authoritative, manually curated. These get a 2× boost and are guaranteed to appear in results for their page even if lower-scoring than other chunks. The flag is explicitly set by trusted (non-remote) write paths.

**BRAIN gap:** Brain has no distinction between:
- Memories saved explicitly by the user via `mcp__brain__save_memory_tool` (high trust)
- Memories auto-ingested by `post_tool_use.py` hooks (medium trust)
- Memories synthesized by LLM reflection (lower trust — synthetic)
- Memories from PDF chunks (lowest trust — raw extraction)

All four currently get `importance = 0.5` and identical ranking. A user who explicitly saves "decision: always use UUID v4 for memory IDs" should have that memory rank higher than a hook-captured echo of the same file edit.

**BRAIN application:** Add a `curated BOOLEAN DEFAULT 0` column to the `memories` table:

```sql
ALTER TABLE memories ADD COLUMN curated INTEGER NOT NULL DEFAULT 0;
```

Set `curated = 1` for memories saved via:
- `mcp__brain__save_memory_tool` (explicit MCP tool call — user deliberately saving)
- Manually via `POST /v1/save` with `curated: true` body field

Set `curated = 0` for:
- `post_tool_use.py` hook captures (automatic)
- `session_end.py` ingest (automatic)
- `run_reflection()` synthesis (synthetic)
- Bootstrap ingest scripts (bulk/historical)

In `brain.rs:search()`, apply a guaranteed importance floor for curated memories:

```rust
let effective_importance = if memory.metadata.curated {
    memory.metadata.importance.max(0.8)  // curated floor: 0.8
} else {
    memory.metadata.importance
};
final_score *= effective_importance;
```

This is simpler than gbrain's 2× boost + guaranteed inclusion — just a guaranteed high importance floor. Curated memories always rank competitively when semantically relevant.

**Implementation complexity:** Low. One column, flag on two save paths, one condition in search.

---

**G6 — Cross-session patterns phase (meta-pattern synthesis)**

**Source:** `src/core/cycle/patterns.ts` — 30-day lookback on `wiki/personal/reflections/`, minEvidence=3, Sonnet synthesis with citation

Brain's `run_reflection()` (brain.rs:377-431) looks at the 50 most recent memories and deletes near-duplicates + saves consolidated patterns. It works at the level of individual memories. It never looks *across* multiple reflection outputs to find recurring themes.

gbrain's patterns phase is separate and distinct:

```
1. Query: SELECT all memories WHERE type='reflection' AND created_at > 30 days ago
2. Gate: if count < 3, skip (minEvidence threshold)
3. LLM call: "Given these N reflections, what recurring patterns, themes, or 
              principles appear across multiple sessions? For each pattern, 
              cite the specific reflection IDs that evidence it."
4. Save: each identified pattern as a new `pattern` type memory with
         thread_id links back to the source reflection IDs
5. These pattern memories accumulate over time → become the highest-value
   memories (cited by many sessions, high importance)
```

**BRAIN gap:** Brain accumulates reflection memories (`source=reflection`, `type=Pattern`) but never cross-references them. Over time the reflection corpus grows but its signal stays flat — each reflection is isolated. The patterns phase converts isolated reflections into a connected pattern library.

**BRAIN application:**

Add a new reflection mode to the existing `run_reflection()` or as a separate triggered function:

```rust
// brain/rust/src/brain.rs — new function
pub fn run_cross_session_patterns(
    &self,
    lookback_days: u32,     // default 30
    min_evidence: usize,    // default 3
) -> Result<Vec<String>, BrainError> {  // returns IDs of new pattern memories
    let cutoff = Utc::now() - chrono::Duration::days(lookback_days as i64);
    
    // Get recent reflection memories
    let reflections: Vec<Memory> = self.store
        .get_memories_by_type_since(MemoryType::Pattern, &cutoff)?
        .into_iter()
        .filter(|m| m.metadata.source == MemorySource::Reflection)
        .collect();
    
    if reflections.len() < min_evidence {
        return Ok(vec![]);
    }
    
    // Run LLM synthesis (requires llm_client)
    let client = self.llm_client.as_deref()
        .ok_or_else(|| BrainError::Summarization("no LLM client".into()))?;
    
    let summarizer = Summarizer::from_ref(client);
    let texts: Vec<&str> = reflections.iter().map(|r| r.content.as_str()).collect();
    let ids: Vec<&str> = reflections.iter().map(|r| r.id.as_str()).collect();
    
    let patterns = summarizer.extract_cross_session_patterns(&texts, &ids)?;
    // Prompt asks LLM to: identify recurring themes, cite source IDs, ignore one-offs
    
    let mut new_ids = Vec::new();
    for pattern in &patterns {
        let id = self.save_memory(
            &pattern.content,
            MemoryType::Pattern,
            &["cross_session", "meta_pattern"],
            "general",
            None,
            MemorySource::Reflection,
            None,
            Some(&pattern.title),
            None,
        )?;
        // Store citation links in memory_links table (R3/T10)
        for cited_id in &pattern.cited_reflection_ids {
            self.store.add_memory_link(&id, cited_id, "synthesized_from", 1.0)?;
        }
        new_ids.push(id);
    }
    Ok(new_ids)
}
```

**Trigger:** Run monthly via worker.rs (low frequency — only when enough reflections accumulate). Requires ≥3 reflection memories in lookback window.

**Implementation complexity:** Medium. New store query (`get_memories_by_type_since`), new LLM prompt, new worker trigger. Depends on R3 (memory_links) for citation storage.

---

**G7 — Chunk-level hash dedup before ONNX embedding [Optimization]**

**Source:** `src/core/import-file.ts` — `hash-match for dedup`, `increment-embed`

T35 covers file-level checkpointing (skip already-processed files). gbrain also deduplicates at the chunk level: before calling the embedder, compute `sha256(chunk_text)` and check if a memory with that exact content hash already exists. If yes, reuse the stored embedding — no ONNX inference needed.

**BRAIN gap:** Brain's ONNX embedder is called for every `save_memory()` call, even for content that was already embedded in a prior run. For a 300-note Obsidian vault where only 5 notes changed, the current re-ingest still calls ONNX 300× unnecessarily.

**BRAIN application:** In `brain.rs:save_memory()`, add a content-hash check before calling `self.embedder.embed()`:

```rust
let content_hash = sha256_hex(&content);
if let Some(existing_emb) = self.store.get_embedding_by_content_hash(&content_hash)? {
    // Reuse stored embedding — skip ONNX inference
    embedding = existing_emb;
} else {
    embedding = self.embedder.embed(&content)?;
}
```

Requires adding `content_hash TEXT` column (already proposed for R7) and `get_embedding_by_content_hash()` store query. Low effort given R7 is already planned.

**Implementation complexity:** Low. Extends R7 (SHA256 column) to also look up embeddings by hash.

---

### What gbrain does that brain should NOT copy

| gbrain concept | Why not applicable |
|---|---|
| PGLite / Postgres + pgvector | brain uses SQLite + in-memory index — correct for a local tool |
| Advisory locks for wikilink reconciliation | brain doesn't use markdown files as source of truth |
| Slug-based content addressing | brain uses UUIDs — content is in SQLite, not filesystem |
| Remote/local trust boundary for MCP | brain's MCP is always local — no remote agent surface |
| Parent-child job DAGs with 9 states | brain's worker handles 3 states (pending/done/failed); overkill now |
| S3/R2/Supabase file storage backends | brain is single-machine, local-only |
| `dream_verdicts` table (LLM verdict cache) | brain's reflection fires inline — different architecture |
| Wikilink extraction + reconciliation | not applicable (brain is not a wiki) |
| 41-operation contract system | brain has 7 MCP tools — appropriate for current scale |
| Token accounting per job | useful if costs become a concern; not yet |

### Priority table

| ID | Change | Effort | ROI | Location |
|---|---|---|---|---|
| G2 | Type diversity cap in results | Low | **High** | `brain.rs:search()` |
| G3 | Source-based ranking multipliers | Low | **High** | `brain.rs:search()`, D3 config |
| G4 | Fire-and-forget query capture + replay | Low-Med | **High** | `brain_api.rs`, new table |
| G6 | Cross-session patterns phase | Medium | Medium | `brain.rs`, `worker.rs` |
| G5 | `curated` memory flag | Low | Medium | `store.rs`, save paths |
| G1 | S-G semantic chunking for obsidian | Low-Med | Medium | new Python chunker |
| G7 | Chunk-level hash dedup before ONNX | Low | Low-Med | `brain.rs:save_memory()` |

**Dependency notes:**
- G3 depends on D3 (brain_policies.toml) — implement D3 first
- G6 depends on R3 (memory_links) for citation storage
- G7 depends on R7 (content_hash column) — extends it, implement together

---

## neurolinked Audit — 2026-05-01

**Source:** [deep6nick/neurolinked](https://github.com/deep6nick/neurolinked) (Python, MIT)
**What it is:** Biologically-inspired neuromorphic brain system — 100K Izhikevich spiking neurons across 11 brain regions, STDP synaptic learning, dual storage (neural state + SQLite knowledge store), MCP server for Claude integration.
**Key files read:** `brain/brain.py`, `brain/neurons.py`, `brain/synapses.py`, `brain/knowledge_store.py`, `brain/sleep_consolidation.py`, `brain/regions.py`, `sensory/text.py`, `brain/claude_bridge.py`, `brain/events.py`, `brain/config.py`
**Audit method:** Full source analysis. Checked every candidate against T1–T40, R1–R8, D1–D4, A1–A4, G1–G7.

### Honest assessment upfront

Neurolinked is 80% simulation machinery (Izhikevich ODEs, STDP weight updates, sparse connectivity matrix, neuromodulator dynamics, spiking propagation). These are fascinating but **do not transfer** to a text retrieval system — brain has no neural network to learn weights in, no concept of spike timing, no membrane potentials. Auditing this source is about extracting the 3 transferable ideas from a system built on fundamentally different substrate.

### What does NOT transfer

| neurolinked concept | Why not applicable |
|---|---|
| Izhikevich spiking neuron model (ODE) | brain has no neural simulation |
| STDP synaptic weight updates | no weight matrix to update |
| Neuromodulators (dopamine, ACh, NE, 5-HT) | no learning rate to modulate |
| 11-region sparse connectivity matrix | not a network architecture |
| Winner-take-all competition | no activation vectors |
| Lateral inhibition | same — no firing neurons |
| Development stage learning rate schedule | brain improves via data, not training |
| Hash-based TF-IDF encoding (256-dim) | brain uses ONNX; strictly better quality |
| Screen/audio/vision sensory encoding | not applicable to coding assistant |
| Neural state persistence (`.npz`) | not applicable |

### Genuine findings

---

**N1 — Co-access link strengthening (STDP analogue)**

**Source:** `brain/synapses.py:63–115` — STDP; `brain/knowledge_store.py:318` — strength += 0.1 per recall

STDP's core rule: when neuron A fires *before* neuron B consistently, strengthen the A→B synapse. The transfer is not about spike timing — it's about the underlying principle: **co-activation implies association, and association should be reinforced**.

In knowledge space: when memories A and B are retrieved together by similar queries (co-accessed), they have a latent association. The more often they co-occur in result sets, the stronger that association.

**BRAIN gap:**

R3 (memory_links table) is about creating explicit edges. T33 (hub detection) is about finding high-in-degree memories from those edges. But R3's edges are created by code logic: `same_session`, `consolidates`, `supersedes`. There is no mechanism to auto-create edges from *usage patterns*. The system doesn't learn what goes together from how it's actually used.

**BRAIN application:**

Track co-access counts in the `memory_links` table when search results are returned:

```rust
// In brain/rust/src/brain.rs — after search() returns results
fn record_co_access(
    &self,
    result_ids: &[&str],
    threshold: usize,  // min co-accesses before a link is created, default 3
) -> Result<(), BrainError> {
    // For every pair in the result set, increment co-access counter
    for i in 0..result_ids.len() {
        for j in (i+1)..result_ids.len() {
            self.store.increment_co_access(result_ids[i], result_ids[j])?;
        }
    }
    // Promote pairs that hit the threshold to explicit memory_links
    let ready = self.store.get_co_access_pairs_above(threshold)?;
    for (id_a, id_b, count) in ready {
        let weight = (count as f32 / 10.0).min(1.0);  // normalize
        self.store.add_memory_link(&id_a, &id_b, "co_accessed", weight)?;
        self.store.add_memory_link(&id_b, &id_a, "co_accessed", weight)?;
    }
    Ok(())
}
```

New table:
```sql
CREATE TABLE IF NOT EXISTS co_access_counts (
    id_a TEXT NOT NULL,
    id_b TEXT NOT NULL,
    count INTEGER NOT NULL DEFAULT 1,
    last_seen_at TEXT NOT NULL,
    PRIMARY KEY (id_a, id_b)
);
```

**Uses once edges are established:**
- Hub detection (T33) now includes `co_accessed` edges — memories that appear in many result sets together become hubs without any manual tagging
- When searching for A, pre-fetch A's `co_accessed` neighbors as bonus context (at lower score weight, analogous to neurolinked's 0.4× re-injection)
- Co-access count feeds into importance scoring (R1): high co-access = frequently relevant across many queries = high importance

**Implementation complexity:** Low. New table + pair-counting in search path + threshold-based link promotion. Depends on R3 (memory_links table).

---

**N2 — Adaptive pruning threshold**

**Source:** `brain/brain.py:223–254` — `_prune_synapses()`; `brain/config.py` — STAGES thresholds

Neurolinked's pruning threshold rises as the brain matures:
```python
threshold = {"EMBRYONIC": 0.05, "JUVENILE": 0.1, "ADOLESCENT": 0.15, "MATURE": 0.2}[stage]
```

Young brains tolerate weak synapses (still forming); mature brains prune aggressively (only strong connections survive). The total synapse count stays manageable as the brain ages.

**BRAIN gap:**

Brain's importance-based archival (from R1, D3) uses a fixed `min_importance` floor (e.g., 0.05). At 2,230 memories this is fine — low-importance memories are rare. At 10,000+ memories, the fixed floor means more and more noise accumulates before reaching the threshold.

**BRAIN application:**

Replace the fixed `min_importance` floor in `brain_policies.toml` with a formula that rises with corpus size:

```rust
// In brain/rust/src/worker.rs — archive/decay pass
fn adaptive_archive_threshold(total_memories: usize) -> f32 {
    let base = 0.05_f32;
    let scale = 0.15_f32;
    // Sigmoid ramp: flat until 2K, rises to base+scale at ~10K
    let x = (total_memories as f32 - 2000.0) / 1000.0;
    let sigmoid = 1.0 / (1.0 + (-x).exp());
    base + scale * sigmoid
    // At 2,200 memories: ~0.054  (barely above base)
    // At  5,000 memories: ~0.130
    // At 10,000 memories: ~0.196
    // At 20,000 memories: ~0.199 (asymptote at 0.20)
}
```

Applied in the worker's decay pass:
```rust
let threshold = adaptive_archive_threshold(self.brain.get_stats()?.total_memories);
self.store.archive_memories_below_importance(threshold)?;
// "archive" = set a `archived_at` timestamp, not DELETE
// Archived memories are excluded from search but preserved for future restore
```

**Why sigmoid not linear:** A linear ramp would start pruning too aggressively at small corpus sizes. The sigmoid keeps the threshold near-base until the corpus reaches a meaningful size (~2K), then rises to a stable ceiling (~0.20) that matches neurolinked's mature stage behavior.

**Implementation complexity:** Low. Single formula in worker.rs, no schema changes (uses existing `importance` column + a new `archived_at TEXT` column).

---

**N3 — Insights append-only log with supporting IDs**

**Source:** `brain/sleep_consolidation.py:245–251` — `insights.jsonl`; `Insight` dataclass

Neurolinked's sleep consolidator writes cross-reference and pattern findings to an append-only log, not to the knowledge store:

```python
@dataclass
class Insight:
    kind: str              # "cross-reference" | "pattern" | "replay"
    title: str
    body: str
    supporting_entry_ids: list[int]   # IDs of knowledge entries that evidence this
    score: float

# Written to brain_state/insights.jsonl on every consolidation pass
with open("brain_state/insights.jsonl", "a") as f:
    f.write(json.dumps(asdict(insight)) + "\n")
```

**How this differs from saving consolidated pattern memories (existing):**

Brain's `run_reflection()` saves new `Pattern` type memories to the DB — the *output* of consolidation. The insights log captures the *reasoning* behind consolidation: which specific memory IDs were considered, what their relationship was, and how confident the finding was.

Over time, the insights log accumulates a history of:
- Which pairs of memories were found to be related (cross-reference insights)
- What recurring themes emerged across sessions (pattern insights)
- How often each memory appears as a supporting entry

This last point is a new ranking signal: **appearance frequency in insights** = implicit hub score, available *without* the full R3 memory_links infrastructure.

**BRAIN application:**

Add `brain/brain_state/insights.jsonl` (append-only) written by the consolidation/reflection cycle:

```rust
// brain/rust/src/brain.rs — extend run_reflection() and run_cross_session_patterns()
#[derive(Serialize)]
struct Insight {
    ts: String,
    kind: String,         // "consolidation" | "cross_session_pattern" | "coverage_gap"
    title: String,
    body: String,
    supporting_ids: Vec<String>,
    score: f32,
}

fn append_insight(&self, insight: &Insight) -> Result<(), BrainError> {
    let path = self.config.insights_log_path.as_deref()
        .unwrap_or("brain_state/insights.jsonl");
    let mut file = OpenOptions::new().create(true).append(true).open(path)?;
    writeln!(file, "{}", serde_json::to_string(insight)?)?;
    Ok(())
}
```

Write an insight record for every consolidation event:
- When `run_reflection()` finds near-duplicates: insight of kind `consolidation`, `supporting_ids` = deleted IDs + replacement ID
- When `run_cross_session_patterns()` (G6) finds a meta-pattern: insight of kind `cross_session_pattern`, `supporting_ids` = cited reflection IDs
- When `coverage_gaps` (T29) logs a new gap: insight of kind `coverage_gap`

**Secondary use — insight frequency as hub signal:**

```sql
-- New view (no schema change required):
CREATE VIEW IF NOT EXISTS insight_hit_counts AS
SELECT supporting_id, COUNT(*) as hit_count
FROM (
    -- Parse JSONL in Python maintenance script, load into temp table
    SELECT json_each.value as supporting_id
    FROM insight_staging, json_each(insight_staging.supporting_ids)
)
GROUP BY supporting_id
ORDER BY hit_count DESC;
```

Run as a weekly maintenance pass: parse `insights.jsonl`, count appearance frequency, update `memories.importance` for the top-N most-cited memories. Memories that keep appearing in insights are load-bearing — boost them.

**Why append-only log instead of DB table:** Insights are audit artifacts. An append-only log is cheap, always correct even on crash, human-readable with `tail -f`, and doesn't require schema migrations. The DB is for searchable operational data; the log is for history.

**Implementation complexity:** Low. `append_insight()` helper in `brain.rs` + call sites in `run_reflection()` and G6's patterns function. Weekly maintenance script to tally hits.

---

**N4 — Session query diversity signal [Weak]**

**Source:** neurolinked's dopamine/acetylcholine dynamics modulating learning rate based on input novelty/rate

Neurolinked adapts learning rate based on how novel/diverse inputs are (high dopamine = high novelty = learn faster). The mapping: if a session has highly varied queries (user exploring broadly), widen context injection; if queries are tightly focused on one topic, narrow and deepen.

**Why this is weak:** Requires embedding prior session queries, computing pairwise similarity, and dynamically adjusting `n` at search time. The complexity is high relative to the benefit — the user can already control search depth via explicit MCP calls. File as future consideration.

---

### What neurolinked does well that's already covered

| neurolinked concept | Already covered |
|---|---|
| Memory strength grows with each recall | R1 + R4 — importance lifecycle + access_count |
| SQLite FTS5 for keyword search | T6 — already live |
| Idle-triggered consolidation | worker.rs (5s loop), run_reflection() |
| Cross-reference detection by keyword overlap | G6 — cross-session patterns phase |
| Content hash for idempotency | R7 — SHA256 guard |
| Recency in retrieval | T32 — recency-weighted RRF |

### Priority table

| ID | Change | Effort | ROI | Location | Dependencies |
|---|---|---|---|---|---|
| N1 | Co-access link strengthening | Low-Med | Medium | `brain.rs:search()`, new `co_access_counts` table | R3 (memory_links) |
| N2 | Adaptive pruning threshold | Low | Medium | `worker.rs`, formula replaces fixed floor | R1 (importance decay) |
| N3 | Insights append-only log + frequency ranking | Low | Medium | `brain.rs`, reflect + patterns paths | G6 (patterns phase) |
| N4 | Session query diversity signal | High | Low | skip for now | — |

---

## MemPalace Audit — 2026-05-01

**Source:** [MemPalace/mempalace](https://github.com/MemPalace/mempalace) (Python, local-first)
**What it is:** Local-first AI memory system built on hybrid BM25+cosine retrieval, temporal knowledge graph, and a 4-layer context stack. Achieves 96.6% R@5 on the LongMemEval benchmark — a concrete external eval target.
**Audit method:** Full Python source analyzed: memory_store.py, temporal_graph.py, chunker.py, context_stack.py, retriever.py, identity_layer.py, write_log.py, eval/longmemeval.py.

### What MemPalace does that's already covered

| MemPalace concept | Already covered |
|---|---|
| Hybrid BM25 + cosine with RRF | T5/T6 — live in brain.rs:search() |
| Recency decay in retrieval | T32 — 0.85 + 0.15 * 0.5^(age/730) |
| Memory type taxonomy | T11+T24 — 6 types + human/user_fact (R6) |
| Content hash deduplication | R7 — SHA256 pre-save guard |
| LLM-driven consolidation/reflection | run_reflection() |
| Session-scoped memory injection | session_start.py hook |
| Feedback signal collection | feedback_events table |
| Chunking strategy for long documents | T11 — header/paragraph splits |
| Access frequency tracking | R4 — access_count + last_accessed_at |
| Cross-session pattern synthesis | G6 — patterns phase |

### M3 — Positional chunk neighbor expansion

**What it is:** When a retrieved memory has `chunk_index = N`, also fetch the memories from the same `file_path` with `chunk_index = N-1` and `chunk_index = N+1`. The middle chunk of a long document answer is often only meaningful with adjacent context.

**Why it matters for brain:** Obsidian ingest splits long vault notes into multiple chunks. When the user asks about something in the middle of a note, brain retrieves that chunk but loses the surrounding context. Neighbor expansion recovers it with a single extra indexed lookup — no LLM call needed.

**Schema change needed:**
```sql
ALTER TABLE memories ADD COLUMN chunk_index INTEGER;
ALTER TABLE memories ADD COLUMN chunk_total INTEGER;
```
Both nullable — only set for chunked sources. `file_path` already exists as the group key.

**Implementation (brain.rs:search()):**
After the main RRF ranking, for any result with `chunk_index IS NOT NULL`:
```rust
// fetch neighbors from same file_path
SELECT id, content, chunk_index FROM memories
WHERE file_path = ? AND chunk_index IN (?, ?)
  AND id NOT IN (already_returned_ids)
ORDER BY chunk_index
LIMIT 2
```
Append neighbors at end of result set (don't boost score — they're context, not matches).

**Effort:** Low. Two nullable columns + one extra query per chunked result. No index rebuild.
**ROI:** Medium-High for Obsidian vault content. No impact on code/session memories (chunk_index NULL).
**Dependencies:** None.

### M4 — Temporal knowledge graph

**What it is:** A separate `knowledge_facts` SQLite table where facts that change over time are stored with validity windows:

```sql
CREATE TABLE knowledge_facts (
    id          TEXT PRIMARY KEY,
    subject     TEXT NOT NULL,
    predicate   TEXT NOT NULL,
    object      TEXT NOT NULL,
    valid_from  INTEGER,           -- unix ts; NULL = always true
    valid_to    INTEGER,           -- unix ts; NULL = still true
    confidence  REAL DEFAULT 1.0,
    source_memory_id TEXT REFERENCES memories(id)
);
CREATE INDEX kf_subject ON knowledge_facts(subject);
CREATE INDEX kf_valid   ON knowledge_facts(valid_from, valid_to);
```

**Why it matters for brain:** The contradicting-memories problem. brain currently saves both "we use ChromaDB" (2025-11) and "we migrated from ChromaDB to SQLite" (2026-01) as flat memories. The second doesn't invalidate the first in any structured way — both surface on embedding search. The knowledge_facts table supports `query_entity(subject, as_of=now)` which automatically filters `valid_to IS NULL OR valid_to > now`.

**Three operations:**
- `add_fact(subject, predicate, object)` — called by reflection/consolidation when a factual claim is detected
- `query_entity(subject, as_of=timestamp)` — returns currently-valid facts for an entity; used by session context injection
- `invalidate(id, as_of=timestamp)` — sets `valid_to` when a fact is superseded

**Scope:** Facts only, not events. "team uses Rust" is a fact. "fixed bug in store.rs" is an event → stays as a memory row.

**Integration point:** `run_reflection()` can extract triples from consolidated memories and populate this table. MCP `get_context_tool` can query it alongside `search_brain` for the "current state of X" use case.

**Effort:** Medium. New table + 3 functions + reflection extraction prompt change.
**ROI:** High. This is the highest architectural value finding from the entire MemPalace audit — it addresses a class of retrieval failures that no scoring technique can fix.
**Dependencies:** None structurally. Pair with reflection improvement for triple extraction.

### M5 — Write-ahead log for memory saves

**What it is:** An append-only `~/.brain/write_log.jsonl` (or `brain_state/write_log.jsonl`) that logs every `save_memory()` call. Content is NOT stored (only hash). Format:

```jsonl
{"ts": 1746076800, "content_hash": "sha256:abc...", "memory_type": "solution", "project": "brain", "source": "claude_code_session", "session_id": "abc123"}
```

**Why it matters for brain:** N3 (insights log) captures cross-session patterns. The WAL captures the raw ingest audit trail — who/what is writing memories and at what rate. This enables:
- Detecting memory poisoning (a hook gone wrong flooding the store with junk)
- Auditing ingest pipelines (bootstrap vs. hooks vs. MCP tool saves)
- Replaying to reconstruct state at any prior point in time

**Difference from N3:** N3 logs synthesized insights (output of reflection). WAL logs raw ingest events (input to the store). Both are append-only, neither stores full content.

**Implementation:** 3 lines added to `brain.rs:save_memory()`:
```rust
let log_entry = json!({
    "ts": now_unix(), "content_hash": &sha256, "memory_type": &m.memory_type,
    "project": &m.project, "source": &m.source, "session_id": &m.session_id
});
append_jsonl(&self.write_log_path, &log_entry)?;
```
Path configured alongside `BRAIN_DB_PATH`. If missing, silently skip (non-fatal).

**Effort:** Low. One path config var + one append per save. Zero schema change.
**ROI:** Medium. Operational insurance — not retrieval quality, but critical for production trustworthiness.
**Dependencies:** R7 (SHA256 guard) — use the same hash computation.

### M6 — Static identity layer (L0)

**What it is:** A `~/.brain/identity.md` file (or `brain_state/identity.md`) that is always prepended to session context injection by `session_start.py` — unconditionally, before any search results. It contains ~100 tokens of stable user identity: role, preferences, recurring entities, current active projects.

**Why it matters for brain:** The existing `session_start.py` hook loads T34 pinned architectural decisions and top-K recent memories via search. But "who is the user" is not reliably surfaced this way — it depends on what memories happen to score high. With an identity.md, every session starts with a correct and stable identity frame.

**Difference from T24 (human taxonomy) and R6 (human type):**
- T24 = schema for storing human-related memories (relationship type, preference type, etc.)
- R6 = the `human`/`user_fact` memory type for save_memory calls
- M6 = a static, curated file that bypasses search entirely — it is always in context, regardless of what the vector index returns

**File format (example):**
```markdown
# Identity Layer (L0)
- **Role:** Technical founder, AI tools / personal productivity
- **Expertise:** Product, design, non-technical; delegating engineering to Claude Code
- **Active projects:** brain (Rust memory API), ocreamer.studio
- **Communication style:** Caveman-concise, no hedging, push back on bad ideas
- **Key entities:** brain_api (Rust), brain_mcp, SQLite, ONNX, Claude Code hooks
```

**Integration:** `session_start.py` prepends identity.md content to the injected context block before the first brain search fires. If the file is missing, skip gracefully.

**Effort:** Very Low. Edit `session_start.py` to prepend file content if it exists. The file itself is authored manually — no LLM or code generates it.
**ROI:** Medium. Not retrieval quality, but consistency of session framing. Especially valuable after summaries/compaction when prior context is lost.
**Dependencies:** None.

### What MemPalace does that brain should NOT copy

| MemPalace feature | Why skip |
|---|---|
| Full cloud sync / E2E encryption layer | Brain is local-only by design; encryption adds key management complexity with no benefit on loopback |
| FAISS + HNSW vector index | Brain's in-memory flat index rebuilt at startup works fine at 2-5K memories; HNSW adds a Rust FFI dep and rebuild complexity for <5ms latency gain |
| Multi-user access control / tenancy | Single-user personal tool; tenancy is over-engineering |
| Automatic triple extraction on every save | Expensive (LLM call per save); defer to reflection phase only |
| LangChain/LlamaIndex integration adapters | Brain uses native MCP; no need for Python framework adapters |
| REST API versioning with migration guards | Brain's API is internal/personal; semver is sufficient |

### Priority table

| ID | Change | Effort | ROI | Location | Dependencies |
|---|---|---|---|---|---|
| M4 | Temporal knowledge graph (`knowledge_facts` table + triple extraction in reflection) | Medium | High | `store.rs` schema, `brain.rs:run_reflection()`, MCP `get_context_tool` | None |
| M3 | Positional chunk neighbor expansion (`chunk_index` column + neighbor fetch in search) | Low | Med-High | `store.rs` schema, `brain.rs:search()`, Obsidian ingest script | None |
| M5 | Write-ahead log for every save_memory() call | Low | Medium | `brain.rs:save_memory()`, new `brain_state/write_log.jsonl` | R7 (SHA256) |
| M6 | Static identity layer always prepended to session context | Very Low | Medium | `session_start.py` prepend, new `brain_state/identity.md` | None |

**External eval target:** MemPalace achieves 96.6% R@5 on [LongMemEval](https://github.com/xiaowu0162/LongMemEval). brain has no equivalent benchmark. G4 (query capture) + T5 (k-fold eval framework) should eventually converge on a comparable number — measuring against LongMemEval's test set is a concrete goal once the eval pipeline matures.

---

# Research Source 9 — gitnexus-stable-ops (GitNexus Fork)

> https://github.com/maddieunlawful958/gitnexus-stable-ops
> Python + Shell + Cypher. Fork of abhigyanpatwari/GitNexus. Full source analyzed: `agent_graph_builder.py`, `context_resolver.py`, `mcp_server.py`, `agent-graph-schema.cypher`.
> Analyzed: 2026-05-24.

## What this fork is

A Windows-focused toolkit for running GitNexus at scale across 25+ repositories. Underneath the operational framing, it makes a fundamental architectural pivot from the original:

**Original GitNexus** maps **code entities** (File, Function, Class → CALLS, IMPORTS, EXTENDS).
**This fork** maps **AI agents and skills** as first-class graph citizens.

This distinction makes it directly relevant to brain in ways the original is not.

---

## What this fork has that original GitNexus does NOT

### 1. Agent Context Graph — different node/edge model

| | Original GitNexus | gitnexus-stable-ops |
|--|--|--|
| Node types | File, Function, Class, Method | Agent, Skill, KnowledgeDoc, DataSource, ExternalService, ComputeNode, WorkspaceService |
| Edge types | CALLS, IMPORTS, EXTENDS, HAS_METHOD | USES_SKILL, ROUTES_TO, DEPENDS_ON, READS_DATA, WRITES_DATA, CALLS_SERVICE, COMPOSES |
| Primary subject | Source code | AI agent system topology |

Original GitNexus answers: "What does this function call?" This fork answers: "Which agent should handle this task, and what skills/data does it need?"

### 2. Three-signal hybrid retrieval (context_resolver.py)

Original GitNexus: BM25 + cosine via RRF (two signals).
This fork: **three-signal scoring**:

```
Score = 0.5 * BM25 + 0.3 * GraphDistance + 0.2 * TypeWeight
```

- **GraphDistance (30%)**: DFS traversal through `agent_relations` table, score decays by hop depth. Nodes connected to the query-matched node get boosted automatically.
- **TypeWeight (20%)**: Task-type-aware weighting — bugfix queries weight Skill nodes higher; documentation queries weight KnowledgeDoc higher. Different task contexts shift the weight distribution.

Original GitNexus has no graph distance signal and no task-type weighting.

### 3. Token-budget-aware result selection

Original GitNexus returns top-k results. This fork selects results in score order until hitting a token limit (estimated at 3.7 bytes/token per KnowledgeDoc). Falls back to a default P0 context set if no matches found.

Brain has no equivalent — `search_brain` returns top-k regardless of token cost.

### 4. MENTIONS edge auto-inference

Builder scans memory/knowledge files at index time and detects which entities are mentioned, creating MENTIONS edges without manual declaration. This is automated relationship detection from content — no LLM call required, pure text scanning.

Original GitNexus builds edges from AST (explicit code structure). This fork infers edges from prose content — closer to what brain needs.

### 5. Stack: Python + SQLite + FTS5 (same as brain)

Original GitNexus: TypeScript + KuzuDB.
This fork: Python + SQLite FTS5 with Unicode61 tokenizer (supports Japanese bigram tokenization). Zero friction to port — brain's ingest layer is Python, brain's DB is SQLite FTS5.

---

## Technique G1 — Graph Distance as Third Retrieval Signal

**Source file:** `lib/context_resolver.py`

### What it does

After BM25 FTS5 search returns initial candidate nodes, the resolver expands via DFS through the `agent_relations` table up to a configurable depth. Each hop decays the score:

```python
graph_score = base_score * (decay_factor ** hop_depth)
# e.g., hop 1: score * 0.8, hop 2: score * 0.64
```

Nodes not found by BM25 but reachable through the graph from a high-BM25 node still surface — with attenuated scores. This surfaces context that keyword search alone misses.

### BRAIN application

Brain's T10 `memory_relationships` table defines edges (DERIVED_FROM, SAME_SESSION, ELABORATES, CONTRADICTS, FOLLOWS, SHARES_FILE). Once populated, graph distance becomes a third retrieval signal alongside BM25 and cosine:

```rust
// In brain/rust/src/brain.rs — extend search() after T10 ships
fn graph_expand(seed_ids: &[String], depth: u8, decay: f32, conn: &Connection) -> HashMap<String, f32> {
    // BFS/DFS through memory_relationships
    // score = 1.0 * decay^hop for each neighbor
    // merge into RRF result map
}
```

**Dependency:** T10 (`memory_relationships` table) must exist first. G1 is T10's retrieval payoff — the table is worthless without a retrieval algorithm that uses it.

**Impact:** High. Unlocks the Connection Layer's retrieval value. Memories that share edges (SAME_SESSION, ELABORATES) surface together without requiring the user to know they're related.

---

## Technique G2 — Task-Type Retrieval Weighting

**Source file:** `lib/context_resolver.py`

### What it does

Applies different TypeWeight multipliers based on detected task context:

```python
task_weights = {
    "bugfix":  {"Skill": 1.4, "KnowledgeDoc": 0.8, "Agent": 1.0},
    "feature": {"Skill": 1.2, "KnowledgeDoc": 1.1, "Agent": 1.0},
    "refactor":{"Skill": 1.0, "KnowledgeDoc": 1.3, "Agent": 0.9},
}
```

Task type detected from query keywords ("fix", "add", "clean up"). Different task contexts get different memory type distributions in results.

### BRAIN application

Brain's memory types: `fact`, `solution`, `pattern`, `project_context`, `conversation`. A query like "fix this bug" should weight `solution` and `error_lesson` higher. A query like "what's the architecture" should weight `project_context` and `pattern` higher.

```python
# In session_start.py or MCP tool layer
query_type_weights = {
    "debug":   {"solution": 1.5, "error_lesson": 1.4, "fact": 0.8},
    "context": {"project_context": 1.4, "pattern": 1.2, "conversation": 0.9},
    "recall":  {"conversation": 1.4, "fact": 1.0, "solution": 0.9},
}
```

**Effort:** Low. Weight applied post-search as a reranking pass — no schema change needed.
**Dependency:** None. Can ship before T10.

---

## Technique G3 — Token-Budget Result Selection

**Source file:** `lib/context_resolver.py`

### What it does

Selects result nodes in score order until cumulative token estimate exceeds budget. Estimates at 3.7 bytes/token. Falls back to a default P0 (highest-priority) context set if nothing matches.

### BRAIN application

Brain's MCP tools return top-k results regardless of size. For `get_context_tool` and `search_brain`, adding token budget awareness prevents over-filling Claude's context window with low-value results:

```python
def budget_select(results, token_budget=4000):
    selected, total = [], 0
    for r in sorted(results, key=lambda x: x.score, reverse=True):
        est = len(r.content) / 3.7
        if total + est > token_budget:
            break
        selected.append(r)
        total += est
    return selected or [default_p0_context]
```

**Effort:** Low. Post-processing pass on existing search results.
**Dependency:** None.

---

## Technique G4 — MENTIONS Edge Auto-Inference

**Source file:** `lib/agent_graph_builder.py`

### What it does

At build time, scans the text content of every node. Detects entity mentions (agent names, skill names, file paths) via string matching. Creates MENTIONS edges between the scanning node and the mentioned entity — no LLM, no NER model required.

### BRAIN application

During reflection or ingest, scan new memory content for mentions of:
- Known project names
- Known entity names (people, tools, concepts already in the graph)
- Session IDs of related sessions

Create MENTIONS edges in `memory_relationships` automatically. Complements NER-based edge inference (T26) — MENTIONS handles exact-match cases cheaply; NER handles fuzzy/semantic cases.

```python
# In brain/bootstrap or reflection pipeline
def infer_mentions_edges(new_memory_id, content, known_entities):
    for entity_name, entity_id in known_entities.items():
        if entity_name.lower() in content.lower():
            insert_relationship(new_memory_id, entity_id, "MENTIONS", reason=f"text contains '{entity_name}'")
```

**Effort:** Low. String scan is fast; run after each reflection batch.
**Dependency:** T10 (`memory_relationships` table). Also benefits from a populated entity registry.

---

## Technique G5 — Agent/Skill Node Types → Brain Self-Awareness (Awareness Layer)

**Source file:** `lib/agent_graph_builder.py`, `schema/agent-graph-schema.cypher`

### What it does in RS9

Models AI agents and their skills as first-class graph nodes:
- **Agent node**: role, society, type, keywords
- **Skill node**: category, version, execution script, dependencies
- **Edges**: USES_SKILL (agent→skill), ROUTES_TO (agent→agent), COMPOSES (skill→skill)

The `gitnexus_agent_context` MCP tool resolves "which agent and skills are needed for this task?" returning matched agents, required skills, files to read, and token estimates.

### Why this applies to brain (Awareness Layer)

Brain IS an agent. Brain's MCP tools ARE skills. Brain currently has no model of its own capabilities — it cannot answer "which of my tools should I use for this query type?" It just responds to explicit calls.

Modeling brain's tools as an Agent/Skill graph gives brain **self-awareness of its own capability topology**:

```cypher
// Brain as an agent node
CREATE (brain:Agent {
  id: "brain-mcp",
  role: "persistent memory system",
  type: "retrieval_agent"
})

// Brain's MCP tools as skill nodes
CREATE (s1:Skill {id: "search_brain",     category: "retrieval",     best_for: "semantic queries"})
CREATE (s2:Skill {id: "get_context_tool", category: "retrieval",     best_for: "session start, topic priming"})
CREATE (s3:Skill {id: "timeline_tool",    category: "temporal",      best_for: "recency, what changed"})
CREATE (s4:Skill {id: "save_memory_tool", category: "write",         best_for: "persisting decisions, facts"})
CREATE (s5:Skill {id: "reflect_tool",     category: "consolidation", best_for: "deduplication, distillation"})
CREATE (s6:Skill {id: "search_index",     category: "retrieval",     best_for: "layer-1 ID lookup before full fetch"})

// Brain uses all skills
CREATE (brain)-[:USES_SKILL]->(s1)
// ... etc.

// Skill composition: 3-layer pattern
CREATE (s6)-[:COMPOSES {step: 1}]->(s1)  // search_index → search_brain
CREATE (s1)-[:COMPOSES {step: 2}]->(get_observations)
```

This enables the **Strategy Layer** query-trigger matrix: given a query type, the agent graph resolves which skills to invoke automatically.

```python
# gitnexus_agent_context("what did we decide about the eval framework?")
# → returns: {agent: "brain-mcp", skills: ["search_index", "get_observations_tool"], token_estimate: 1200}
# Brain knows which tools to use — without Claude having to decide
```

### BRAIN application

**Phase 1 (low effort):** Build a static skill registry in `brain_state/skill_registry.json` — maps query intent patterns to MCP tool sequences. No graph DB needed yet.

```json
{
  "intent_patterns": {
    "what did we decide": ["search_index", "timeline_tool", "get_observations_tool"],
    "latest on":          ["get_stats_tool", "search_index", "timeline_tool"],
    "fix / debug":        ["search_brain(type=solution)", "search_brain(type=error_lesson)"],
    "what am i working":  ["get_context_tool", "timeline_tool"]
  }
}
```

**Phase 2 (medium effort):** Full Agent/Skill SQLite graph. Brain queries its own capability graph at session start to select the right tool sequence before any external search fires.

**Gap filled:** Awareness Layer — brain knows what it can do and routes accordingly.

**Effort Phase 1:** Very Low. JSON file + pattern matching in session_start.py.
**Effort Phase 2:** Medium. New SQLite table + graph builder script.
**Dependency Phase 1:** None. **Phase 2:** T10.

---

## Cross-reference: Original GitNexus (Research Source 3)

| Capability | Original GitNexus (RS3) | gitnexus-stable-ops (RS9) |
|--|--|--|
| Graph blueprint (T10 schema) | ✅ Provided node+edge model for `memory_relationships` | — |
| Hybrid BM25+cosine retrieval (T6) | ✅ RRF formula | — |
| Graph distance retrieval signal | ❌ Not present | ✅ G1 — the missing third signal |
| Task-type retrieval weighting | ❌ Not present | ✅ G2 |
| Token-budget result selection | ❌ Not present | ✅ G3 |
| MENTIONS auto-inference | ❌ Not present (uses AST edges only) | ✅ G4 |
| Agent/Skill self-awareness graph | ❌ Not present | ✅ G5 — Awareness Layer |
| Stack compatibility with brain | ❌ TypeScript + KuzuDB | ✅ Python + SQLite FTS5 |

**Summary:** RS3 gave brain the graph **structure**. RS9 gives brain the graph **retrieval algorithm + self-awareness** — what to do with T10 edges once they exist, and how brain models its own capability topology. RS9 is the operational complement to RS3's blueprint.

---

## Priority table

| ID | Change | Effort | ROI | Location | Dependencies |
|---|---|---|---|---|---|
| G5-p1 | Static skill registry (intent → tool sequence) | Very Low | High | `brain_state/skill_registry.json` + session_start.py | None |
| G2 | Task-type retrieval weighting | Low | Medium | `brain.rs:search()` rerank pass or session_start.py | None |
| G3 | Token-budget result selection | Low | Medium | MCP tool layer (`get_context_tool`, `search_brain`) | None |
| G4 | MENTIONS edge auto-inference | Low | Medium | reflection pipeline or ingest | T10 |
| G1 | Graph distance as third retrieval signal | Medium | High | `brain.rs:search()` | T10 (memory_relationships table) |
| G5-p2 | Full Agent/Skill SQLite graph for brain self-awareness | Medium | High | New SQLite table + graph builder | T10 |

**Ship order:** G5-p1 first (no deps, immediate Awareness Layer value). G2 + G3 next. G4 + G1 + G5-p2 after T10 ships.

---

# Research Source 10 — dtplot/gitnexus-stable-ops (GitNexus Fork)

> https://github.com/dtplot/gitnexus-stable-ops
> Shell (91.8%) + Python (5.4%) + Makefile (2.8%). Fork of abhigyanpatwari/GitNexus. Production operational toolkit.
> Full source analyzed: `gitnexus-doctor.sh`, `gitnexus-auto-reindex.sh`, `gitnexus-safe-impact.sh`, `graph-meta-update.sh`, `gitnexus-smoke-test.sh`, `lib/parse_graph_meta.py`.
> Analyzed: 2026-05-24.

## What this fork is

An operational stability toolkit for running GitNexus at scale across 25+ repositories. Solves 4 production failure modes that exist in the original: version drift, embedding loss, worktree corruption, and impact instability. Not an architectural fork — a reliability layer on top of the original graph engine.

Manages 25+ repositories, 32,000+ indexed symbols, 73,000+ knowledge graph edges in production.

---

## What this fork has that Original GitNexus + RS9 don't

### 1. Commit-hash incremental indexing (`gitnexus-auto-reindex.sh`)

Compares `meta.json` lastCommit against repo HEAD before triggering reindex. Skips if hashes match. Not timestamp-based — exact commit equality. Prevents redundant full reindexes when nothing changed.

```bash
indexed_commit=$(jq -r '.lastCommit' .gitnexus/meta.json)
current_commit=$(git rev-parse HEAD)
if [ "$indexed_commit" = "$current_commit" ] && [ -z "$FORCE" ]; then
  echo "index is already current"
  exit 0
fi
```

### 2. Dirty worktree detection (`gitnexus-smoke-test.sh`, `gitnexus-auto-reindex.sh`)

Before reindexing, checks for uncommitted changes. Skips with warning unless `ALLOW_DIRTY_REINDEX` is explicitly set. Prevents uncommitted work-in-progress from polluting the code graph with transient state.

### 3. Graceful fallback with risk-level synthesis (`gitnexus-safe-impact.sh`)

When `impact` command fails, synthesizes a fallback response from `context` output via jq. Calculates risk level from reference count:

```bash
# jq risk level calculation
if   [ refs >= 15 ] → "HIGH"
elif [ refs >=  5 ] → "MEDIUM"
else                → "LOW"
```

Structured response returned either way. Caller never receives a naked failure — always gets impact + risk estimate even under degraded conditions.

### 4. Cross-cluster edge weights with normalized scoring (`graph-meta-update.sh`, `lib/parse_graph_meta.py`)

Runs Cypher queries to detect which code communities reference each other. Normalizes edge frequency into continuous weights:

```
10+ edges → weight 0.95
5–9 edges → weight 0.70
2–4 edges → weight 0.45
1 edge    → weight 0.20
```

Output stored as JSONL: `(repo, fromCluster, toCluster, crossEdges, weight, ts)`. Enables visualization of architecture-level dependencies between code clusters — not just node-level relationships.

### 5. Doctor health-check pattern (`gitnexus-doctor.sh`)

Single command validates entire system state:
- Binary exists and is executable
- `.gitnexus/` directory present
- No stale `kuzu` index (warns if found)
- Required `lbug` index present (fails if missing)
- CLI and MCP server versions match
- Embedding count nonzero
- Core commands (`status`, `list`, `context`) respond correctly

Analogous to a database `PRAGMA integrity_check` — run before any critical operation.

---

## Technique D1 — Cross-Cluster Edge Weights → Memory Cluster Weighting

**Source file:** `lib/parse_graph_meta.py`, `bin/graph-meta-update.sh`

### What it does

Assigns normalized weights (0.20–0.95) to edges between code communities based on cross-edge frequency. Higher frequency = stronger architectural coupling = higher weight in retrieval and visualization.

### BRAIN application

Brain's `memory_relationships` edges currently have flat `confidence=1.0`. D1's tiered weighting applies directly: edges between memory clusters with high co-occurrence get higher confidence, amplifying their G1 graph distance signal.

```sql
-- Derive edge weights from co-occurrence frequency
UPDATE memory_relationships
SET confidence = CASE
  WHEN (
    SELECT COUNT(*) FROM memory_relationships r2
    WHERE r2.source_id = memory_relationships.source_id
    AND   r2.type      = memory_relationships.type
  ) >= 10 THEN 0.95
  WHEN ... >= 5  THEN 0.70
  WHEN ... >= 2  THEN 0.45
  ELSE 0.20
END;
```

Run as part of reflection pipeline after batch saves. Updates weights as the graph grows — edges that accumulate more co-occurrences naturally strengthen over time.

**Effort:** Low. SQL update query, run in reflection batch.
**Dependency:** T10 (memory_relationships table), G1 (graph distance retrieval to consume weights).

---

## Technique D2 — Centrality-Based Salience (Memory Importance Scoring)

**Source file:** `bin/gitnexus-safe-impact.sh`

### What it does

Calculates node importance from inbound reference count. HIGH/MEDIUM/LOW tiers determine how prominently a node surfaces in fallback responses.

### BRAIN application

This concretely defines what "salience" means for brain — a concept from T20 (importance scoring) that was never given a threshold formula.

Memory centrality = number of other memories that reference it via `memory_relationships`. High-centrality memories are architectural anchors:

```sql
-- Compute centrality for each memory
SELECT target_id, COUNT(*) AS inbound_refs,
  CASE
    WHEN COUNT(*) >= 15 THEN 'HIGH'
    WHEN COUNT(*) >=  5 THEN 'MEDIUM'
    ELSE 'LOW'
  END AS salience
FROM memory_relationships
GROUP BY target_id;
```

**Applications:**
- HIGH salience memories → always include in `get_context_tool` results (immune to token budget cuts)
- HIGH salience memories → surface proactively at session start even without query match
- LOW salience orphan memories → candidates for reflection/pruning

**Effort:** Low. SQL view or materialized column on `memories` table. Recomputed in reflection batch.
**Dependency:** T10. Feeds G3 (token budget fallback P0 set = HIGH salience memories).

---

## Technique D3 — Incremental Ingest Guard

**Source file:** `bin/gitnexus-auto-reindex.sh`

### What it does

Compares last-indexed commit hash to current HEAD. Skips reindex entirely if equal. Prevents redundant processing and protects against mid-write state corruption.

### BRAIN application

Brain's ingest pipeline already has `checkpoint.json` files. But there is no guard against running reflection on a dirty or mid-write state. D3 extends checkpoint logic with explicit state validation before triggering heavy operations:

```python
# In brain/bootstrap or reflection trigger
def is_safe_to_reflect(db_path, checkpoint_path):
    last_reflected = read_checkpoint(checkpoint_path).get("last_reflected_memory_id")
    latest_in_db   = db_latest_memory_id(db_path)
    pending_saves  = count_pending_saves(db_path)  # memories saved since last reflect

    if pending_saves < MIN_REFLECT_THRESHOLD:
        return False, "insufficient new memories since last reflection"
    if db_is_locked(db_path):
        return False, "DB mid-write — skip"
    return True, "safe"
```

**Effort:** Very Low. Guard function added to reflection trigger in `brain.rs` or `session_end.py`.
**Dependency:** None.

---

## Technique D4 — Doctor Health-Check Pattern

**Source file:** `bin/gitnexus-doctor.sh`

### What it does

Single diagnostic command that validates the full system before operations begin. Catches configuration drift, missing indexes, and version mismatches before they cause data loss.

### BRAIN application

Brain has no equivalent health check. A `brain-doctor` script would validate:

```bash
#!/bin/bash
# brain-doctor.sh

# 1. MCP server responding
curl -s http://localhost:$BRAIN_PORT/health || fail "MCP server down"

# 2. DB integrity
sqlite3 $BRAIN_DB "PRAGMA integrity_check" | grep -q "ok" || fail "DB corrupted"

# 3. FTS5 index in sync
sqlite3 $BRAIN_DB "SELECT COUNT(*) FROM memories_fts" == "SELECT COUNT(*) FROM memories" || warn "FTS5 out of sync"

# 4. Embedding count nonzero
sqlite3 $BRAIN_DB "SELECT COUNT(*) FROM memories WHERE embedding IS NOT NULL" > 0 || fail "no embeddings"

# 5. Reflection queue not stalled
pending=$(sqlite3 $BRAIN_DB "SELECT COUNT(*) FROM memories WHERE reflected = 0")
[ $pending -gt 500 ] && warn "reflection queue stalled: $pending unprocessed"

# 6. OPENROUTER_API_KEY present (needed by hooks)
[ -z "$OPENROUTER_API_KEY" ] && fail "OPENROUTER_API_KEY not set — hooks will fail"
```

**Effort:** Low. Bash script, no new deps.
**Dependency:** None.

---

## Technique D5 — Graceful Fallback with Risk Synthesis

**Source file:** `bin/gitnexus-safe-impact.sh`

### What it does

Two-tier fallback: try primary command → on failure, synthesize approximate result from secondary command. Risk level calculated from reference count so caller always gets a structured, actionable response.

### BRAIN application

Brain's MCP tools have no fallback logic. If `search_brain` returns 0 results, the response is empty. D5 pattern adds a synthesis fallback:

```python
# In MCP tool layer
def safe_search(query, **kwargs):
    results = search_brain(query, **kwargs)
    if not results:
        # Fallback: get_context_tool is broader, less precise
        fallback = get_context_tool(topic=query)
        return {
            "results": fallback,
            "fallback": True,
            "warning": "No direct match — returning broad context",
            "salience": "LOW"  # caller knows to weight this less
        }
    return {"results": results, "fallback": False}
```

Ensures every query returns something actionable. Caller can inspect `fallback: True` to decide how to weight the result.

**Effort:** Low. Wrapper function around existing MCP tools.
**Dependency:** None.

---

## Cross-reference: RS3, RS9, RS10

| Capability | RS3 (Original GitNexus) | RS9 (maddieunlawful958) | RS10 (dtplot) |
|--|--|--|--|
| Graph blueprint (T10) | ✅ | — | — |
| Hybrid BM25+cosine (T6) | ✅ | — | — |
| Graph distance retrieval (G1) | ❌ | ✅ | — |
| Task-type weighting (G2) | ❌ | ✅ | — |
| Token budgeting (G3) | ❌ | ✅ | — |
| MENTIONS auto-inference (G4) | ❌ | ✅ | — |
| Agent/Skill self-awareness (G5) | ❌ | ✅ | — |
| Cross-cluster edge weights (D1) | ❌ | ❌ | ✅ |
| Centrality-based salience (D2) | ❌ | ❌ | ✅ |
| Incremental ingest guard (D3) | ❌ | ❌ | ✅ |
| Doctor health-check (D4) | ❌ | ❌ | ✅ |
| Graceful fallback synthesis (D5) | ❌ | ❌ | ✅ |

**RS3 = graph structure. RS9 = graph retrieval + brain self-awareness. RS10 = operational stability + edge weighting + salience scoring.**

The three sources are fully complementary — zero overlap in what each contributes.

---

## Priority table

| ID | Change | Effort | ROI | Location | Dependencies |
|---|---|---|---|---|---|
| D3 | Incremental ingest guard | Very Low | Medium | session_end.py or reflection trigger | None |
| D4 | Brain doctor health-check script | Low | Medium | new `bin/brain-doctor.sh` | None |
| D5 | Graceful fallback synthesis in MCP tools | Low | Medium | MCP tool layer | None |
| D2 | Centrality-based salience scoring | Low | High | SQL view on memories table | T10 |
| D1 | Cross-cluster edge weights | Low | Medium | reflection batch SQL update | T10, G1 |

**Ship order:** D3 + D4 + D5 first (no deps). D2 + D1 after T10 ships.

---

# Research Source 12 — awesome-algorithms (Meta-Algorithmic Learning Framework)

> https://github.com/tayllan/awesome-algorithms
> Markdown curated list. 25.1k ⭐, 2.9k forks. Educational resources for algorithms: courses, books, visualizations, competitions.
> Relevance: Not domain-specific to BRAIN retrieval, PPF physics, or quantum computing. VALUE is in meta-algorithmic practices: how to document algorithms, evaluate complexity rigorously, structure learning progressively.
> Analyzed: 2026-05-25.

## What this is

A community-curated directory of algorithm education resources. Organized by level (beginner, competitive, theory, production) and includes MIT OCW courses, textbooks (CLRS, Knuth, Algorithm Design Manual), visualizations (VisuAlgo), and competition platforms (LeetCode, Codeforces).

**The insight**: awesome-algorithms teaches *how computer scientists think about algorithms* — not the algorithms themselves. This thinking applies universally.

## Meta-Algorithmic Practices Found (Applicable to Your Algorithms)

### T51 (High): Algorithm Documentation Structure
**Pattern from awesome-algorithms**:
- Problem statement (what does it solve?)
- Intuition before math (Khan Academy, Roughgarden style)
- Pseudocode + complexity analysis
- Trade-offs and when to use it
- Visualizations for intuition

**Your algorithms** (PPF, quantum, memory retrieval) are already documented this way in `/ALGORITHMS/` — this validates your structure.

**Recommendation**: Link to CLRS, Roughgarden, and Algorithm Design Manual as reference standards for your own documentation.

### T52 (Medium): Complexity Rigor Across Domains
**Pattern from awesome-algorithms**:
- CLRS uses O() notation uniformly
- Algorithm Design Manual cross-references tradeoffs
- MIT courses teach complexity analysis as first-class skill

**Your metrics today**:
- PCG: O(n·√κ) ✅ Rigorous
- HHL: O(log n) ✅ Rigorous
- RRF: Not formally analyzed (FTS5 BM25 + cosine rank fusion)
- VQE: Hybrid O(n) — classical outer loop, quantum inner

**Gap**: RRF and VQE complexity should be formally derived. awesome-algorithms corpus provides textbook references for this.

**Recommendation**: T51 + T52 combined = treat your algorithm domain like academic CS. Complexity analysis is non-negotiable.

### T53 (Medium): Pedagogical Progression (Beginner → Theory)
**Pattern from awesome-algorithms**:
1. YouTube (Khan Academy, Roughgarden)
2. Interactive (VisuAlgo, Recursive)
3. Books (CLRS, Algorithm Design Manual)
4. Research (Algorithms Illuminated)

**Your structure**:
1. ALGORITHMS/README.md (navigation)
2. ALGORITHMS/domains/ (organized by field)
3. ALGORITHMS/patterns/ (cross-cutting techniques)
4. ALGORITHMS/RELATIONSHIPS.md (why they connect)

This maps onto awesome-algorithms structure. Your ALGORITHMS/learning-resources.md now formalizes this mapping.

### T54 (Low–Medium): Community Curation Model
**Pattern from awesome-algorithms**:
- Contribution guidelines (spelling, format, no monetization)
- Lightweight PRs (one resource per PR)
- Community filters quality

**Your algorithms** are hand-curated by domain experts (you), not community-filtered yet. This is fine for a personal research space. If you ever share this — consider contribution guidelines like awesome-algorithms uses.

## Honest Assessment

**Most valuable aspect**: awesome-algorithms shows *how to think about algorithms as a discipline* — rigor, progression, documentation, complexity analysis.

**Not valuable for your specific algorithms**: zero PPF physics resources, zero quantum computing resources, zero memory/retrieval resources.

**Integration path**: Use awesome-algorithms as a **meta-reference for your own documentation standards**, not as a source of domain-specific techniques.

**Recommendation**: Keep /ALGORITHMS/learning-resources.md as a bridge document. Reference awesome-algorithms when teaching others about your algorithm space, not when optimizing BRAIN retrieval or PPF performance.

---

# Research Source 11 — auto-devnexus (Architectural Reference)

> https://github.com/a574676848/auto-devnexus
> Python (80.8%) + Shell + PowerShell. AI skill orchestration layer built on top of devnexus/GitNexus.
> Referenced as architectural inspiration only — not for direct integration. Specific tools (Jira, Windows scripts, repo-parser) are out of scope. The value is in the principles and vision.
> Analyzed: 2026-05-24.

## What this is

A suite of AI-callable skills designed for Claude Code and OpenCode. Each skill wraps a capability (code indexing, documentation generation, issue tracking, repo analysis) with a consistent architecture: intent routing, tiered credential management, per-skill persistent memory, and async execution.

The relevant insight for brain is not the tools themselves — it's the **operating model**: skills that are self-documenting, self-learning, and composable into a routing layer that an AI assistant can call without knowing the internals.

Brain should build toward the same operating model for its own MCP tools.

---

## Principle A1 — Skills Have Their Own Memory

### What auto-devnexus does

The Jira skill maintains a `MEMORY.md` per workspace — a growing document of field mappings, quirks, and workflow patterns discovered during operation. It is not authored upfront. It accumulates through use.

### Brain-native vision

Each of brain's MCP tools should accumulate its own operational knowledge:

- `search_brain` learns: which query patterns return poor results for this user; which topics have sparse coverage; which memory types are over-represented in results
- `reflect_tool` learns: which memory pairs cluster together most; which reflection runs produce the most consolidations
- `get_context_tool` learns: which topic framings produce the highest-utility context at session start

This is a level above G5's static skill registry. G5-p1 declares what skills exist. A1 makes skills accumulate what they've learned.

**Brain-native implementation:**
```
brain_state/
  skill_memory/
    search_brain.md      ← patterns, gaps, known weak spots
    reflect_tool.md      ← consolidation patterns discovered
    get_context_tool.md  ← high-utility topic framings
```

Each file is appended by reflection when patterns emerge. Read at session start alongside identity.md (M6). Skills become smarter over time without code changes.

**Effort:** Low. Markdown files + reflection appends. No new schema.
**Dependency:** None. Builds on M6 (identity layer) pattern.

---

## Principle A2 — Single Intent Router, Not Many Entry Points

### What auto-devnexus does

`dev-test` is a single entry point that identifies what kind of testing the user needs, then routes to the correct sub-handler. The user says "test this", the skill figures out which of 8 test types applies, then executes the right protocol. The router also knows what it refuses — explicit out-of-scope rejection.

### Brain-native vision

Brain currently has ~8 MCP tools. Claude decides which to call based on conversation context. There is no routing layer — the choice is implicit and inconsistent.

A brain-native intent router formalizes this: one entry point, classification, route to correct tool sequence.

```
User query → intent classifier → tool sequence
───────────────────────────────────────────────
"what did we decide about X"  → search_index + timeline_tool + get_observations_tool
"latest on X"                  → get_stats_tool + search_index + timeline_tool
"fix / debug"                  → search_brain(solution) + search_brain(error_lesson)
"what am I working on"         → get_context_tool + timeline_tool
"remember X"                   → save_memory_tool
"how is brain doing"           → get_stats_tool + doctor check
```

The router also knows what to refuse or redirect — if a query is better answered by reading a file than searching brain, the router says so.

This is the concrete implementation path for G5-p1 (`skill_registry.json`), now with a clear architecture: single MCP entry point `brain_route(query)` that returns the tool sequence to execute.

**Brain-native implementation:**
```python
# New MCP tool: brain_route(query: str) → ToolSequence
def brain_route(query: str) -> list[ToolCall]:
    intent = classify_intent(query)  # keyword + embedding classification
    return SKILL_REGISTRY[intent]    # returns ordered list of tool calls
```

**Effort:** Low–Medium. Classification is keyword-first (fast), embedding fallback (accurate).
**Dependency:** G5-p1 (skill registry must exist first).

---

## Principle A3 — Background Operations with Deduplication Guard

### What auto-devnexus does

`gitnexus-wiki` runs LLM documentation generation as a background process. A deduplication guard prevents two generation jobs from running concurrently. The user doesn't wait — they continue working while the heavy task completes.

### Brain-native vision

Brain's reflection runs synchronously today. On large corpora (19K+ memories) this blocks. The same principle applies: reflection, consolidation, and edge-weight recomputation (D1, D2) should run in the background with a deduplication guard.

```python
# session_end.py — async reflection trigger
def trigger_reflection_if_safe():
    if is_lock_present(REFLECTION_LOCK):
        log("reflection already running — skip")
        return
    if not is_safe_to_reflect():  # D3 guard
        return
    write_lock(REFLECTION_LOCK)
    subprocess.Popen(["python3", "brain/tools/reflect.py"], 
                     start_new_session=True)  # detach from session
    # lock released by reflect.py on completion
```

Combines with D3 (incremental guard): D3 decides IF reflection should run; A3 decides HOW it runs (async, non-blocking, deduplicated).

**Effort:** Low. Lock file + subprocess detach in session_end.py.
**Dependency:** D3.

---

## Cross-reference: Where these principles connect

| Principle | Extends / depends on | Gap it fills |
|--|--|--|
| A1 (skill memory) | G5 (Agent/Skill graph), M6 (identity layer) | Skills learn from use — not just declared statically |
| A2 (intent router) | G5-p1 (skill registry) | Formalizes routing — single entry point, explicit refusals |
| A3 (async + dedup) | D3 (ingest guard) | Reflection runs without blocking — scales to large corpora |

**Note:** Do not integrate auto-devnexus tooling directly. Build brain-native equivalents following these principles. The Jira integration, Windows scripts, repo-parser, and open-source-docs workflow are out of scope.

---

## Phase 9 — Query Template Integration (2026-05-26)

### What shipped

**Tier 1 Item 1: Query Template Integration** — implemented in `brain/api_client.py` and `brain/mcp/server.py`.

Pattern: AlphaFold3 template search. Route query intent to type-biased retrieval.

### Implementation

**`classify_query_intent(query) → str | None`** (`api_client.py`)

Detects troubleshooting vs factual queries via keyword patterns:
- Troubleshooting signals: "why do/does/is", " fail", " error", " broke", "authorization", "disappear", "I lost" → returns `"solution"`
- Factual signals: "what is the cost", "how much does", "are conversation threads" → returns `"fact"`

**`template_search(query, n, project) → list[dict]`** (`api_client.py`)

When intent detected:
1. Type-filtered pass: solution + error_lesson (n//2 each) OR fact (n//2)
2. General pass: top n
3. Deduplicate by ID, return top n

When no intent: falls back to plain `search()`.

**`search_brain`** (`mcp/server.py`): routes to `template_search` unless `memory_type` explicitly set (explicit type filter bypasses template routing).

**`mcp_eval.py`**: updated to use `template_search` as default.

### Results

| Metric | Phase 8 | Phase 9 | Delta |
|--------|---------|---------|-------|
| MCP P@1 | 0.429 | **0.571** | +0.142 (+33%) |
| MCP MRR | 0.521 | **0.722** | +0.201 (+39%) |
| kfold-MCP gap | −0.338 | **−0.197** | +0.141 |

Quick gate unchanged: solution=0.993, pattern=1.000, project_context=1.000, conversation=0.627.

### Why it worked

7 of 8 MCP misses were troubleshooting queries (symptoms described as bugs/failures). Gold memories were at solution/error_lesson type but ranked 4-9 in general search. Type-filtered pass pulls them to the front of the merged list.

---

## Phase 9 — Tier 1 Items 2 & 3: Noise Detection + BVH Deduplication (2026-05-26)

### Tier 1 Item 2: Noise Detection

**Tool:** `brain/tools/noise_detect.py`

**Algorithm (Implicit Geometric Learning):**
1. For each sampled memory, embed its vector (already stored in DB).
2. Apply M Gaussian noise perturbations (σ=0.05), re-normalize.
3. For each perturbation, find top-K neighbors in the original corpus.
4. Fragility = 1 − mean Jaccard overlap between original neighbors and perturbed neighbors.
5. High fragility → memory sits in ambiguous embedding region (duplicate title, empty content, or boilerplate).

**Run:** `python3 brain/tools/noise_detect.py --sample 2000`  
**Speed:** ~12s for 2000 memories (165/s).  
**Report:** `brain/eval/noise_detect_YYYY_MM_DD.json`

**Baseline fragility by type (2026-05-26, n=2000 sample):**
| Type | Mean fragility | P90 | % fragile (≥0.4) |
|------|---------------|-----|-----------------|
| conversation | 0.631 | 0.919 | 77.7% |
| fact | 0.398 | 0.582 | 50.1% |
| solution | 0.418 | 0.590 | 55.6% |
| project_context | 0.397 | 0.560 | 50.7% |

**Finding:** Worst 10 memories all had fragility=1.000 — identified as `<local-command-caveat>` boilerplate sessions (Claude Code sessions where only `!` commands ran while Claude wasn't active). 883 found and deleted.

**Impact:** Corpus 21,255 → 20,373. Conversation quick gate P@1: 0.627 → 0.640.

---

### Tier 1 Item 3: BVH Deduplication

**Tool:** `brain/tools/bvh_dedup.py`

**Algorithm (PPF BVH Collision Detection pattern):**
- **Broad phase**: Chunked upper-triangle matmul — sweeps all (i, j) pairs with i < j in O(n log n)-style blocks of 1000. 1.0s for 20k memories.
- **Narrow phase**: Content-prefix check (first 300 chars) — rejects false positives where structurally-similar sessions embed near each other despite different content.
- **Union-find**: Groups confirmed pairs into duplicate clusters.
- **Resolution**: Keep highest-salience memory per cluster, delete the rest.

**Run:** `python3 brain/tools/bvh_dedup.py --dry-run` (preview)  
`python3 brain/tools/bvh_dedup.py --delete --threshold 0.97` (execute)  
**Report:** `brain/eval/bvh_dedup_YYYY_MM_DD.json`

**Results (2026-05-26, threshold=0.97):**
| Stage | Count |
|-------|-------|
| Broad phase pairs | 406,370 |
| Narrow phase confirmed | 29,010 |
| Clusters found | 453 |
| Duplicates deleted | 2,564 |

**Root cause:** Stop hook was firing multiple times — same session saved 40-51× per ingest event. BVH correctly identified all clusters; narrow phase confirmed content identity before deletion.

**Impact:** Corpus 20,373 → 17,812. Conversation quick gate P@1: 0.640 → **1.000** (all 4 types now perfect).

---

### Phase 9 Combined Results

| Metric | Phase 8 baseline | After T1-1 | After T1-2+3 | Total delta |
|--------|-----------------|-----------|-------------|-------------|
| MCP P@1 | 0.429 | 0.571 | **0.571** | +0.142 (+33%) |
| MCP MRR | 0.521 | 0.722 | **0.722** | +0.201 (+39%) |
| Conversation quick gate P@1 | 0.627 | 0.627 | **1.000** | +0.373 |
| Solution quick gate P@1 | 0.987 | 0.993 | **1.000** | +0.013 |
| Corpus size | 21,255 | 21,255 | **17,812** | −3,443 (−16%) |
| kfold-MCP gap | −0.338 | −0.197 | **−0.197** | +0.141 |

**Key lesson:** Corpus quality > corpus size. Removing 16% of memories improved every metric. The 3,443 deleted memories were either boilerplate (883 caveat sessions) or exact-copy duplicates from stop-hook over-firing (2,564).

### Tier 1 tools summary

| Tool | Purpose | Run time | When to use |
|------|---------|----------|-------------|
| `noise_detect.py` | Flag fragile memories by embedding instability | 12s / 2k sample | After major ingest; spot-check fragile types |
| `bvh_dedup.py` | Find and remove exact-copy duplicates | 1s broad + instant narrow | After stop-hook changes; any suspected re-ingest |
| `eval_suite.py --mcp` | End-to-end retrieval quality check | ~30s | After any retrieval change |
| `eval_suite.py --quick` | Type-level P@1 smoke test | ~20s | After every major ingest |
