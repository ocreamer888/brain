# Brain Gaps Audit — 2026-05-01

> Audit of the current brain codebase. Use this as the backlog for future improvements.
> Baseline: v0.2.0 shipped. 2,224 memories | 1,451 sessions.

---

## What's Already Shipped (don't re-do)

| Feature | Location |
|---|---|
| RRF hybrid search (BM25 + cosine, k=60) | `brain/rust/src/brain.rs` `search()` |
| Mean-centering (T2) | `brain/rust/src/brain.rs` `open()` + `index.rs` |
| Recency weighting (T32, floor 0.85) | `brain/rust/src/brain.rs` `search()` |
| Tree-sitter symbol tagging (`sym:name`) | `brain/rust/src/symbols.rs` |
| 3-layer MCP (search_index → timeline → get_observations) | `brain/rust/src/` + `brain/mcp/server.py` |
| FTS5 Porter stemming on content + title | `brain/rust/src/store.rs` `create_tables()` |
| Job retry queue (5-attempt cutoff) | `brain/rust/src/worker.rs` + `store.rs` |
| SSE stream + web viewer | `brain/rust/src/bin/brain_api.rs` + `static/index.html` |
| `<private>` block stripping | `brain/rust/src/privacy.rs` |
| Feedback events table | `brain/rust/src/store.rs` `feedback_events` table |

---

## Gaps Backlog

### GAP-1 — Feedback loop is dead
**Severity: HIGH**

`feedback_events` table has 3 total rows ever. The schema and `record_feedback` MCP tool exist but nothing closes the loop — feedback isn't used to re-rank, boost importance, or generate ground truth.

**What to do:**
1. Wire `record_feedback` calls into session_start hook: when a surfaced memory leads to a useful action, log `accepted`; when Claude overrides/ignores it, log `rejected`.
2. Use feedback signal to update `memories.importance` score dynamically (accepted → +0.05, rejected → -0.05, clamped 0.1–1.0).
3. Mine `feedback_events` to build a gold set for retrieval eval automatically.

**Files to touch:** `brain/rust/src/brain.rs`, `brain/hooks/session_start.py`, `brain/rust/src/store.rs`

---

### GAP-2 — Session mining unused (1,451 sessions of untapped signal)
**Severity: HIGH**

1,451 stored sessions exist but are ingested as flat summaries. Which memories were queried during a session and never used? Which queries returned nothing useful? This is free ground truth.

**What to do:**
1. Add a `brain/tools/mine_session_signal.py` script that:
   - Reads `sessions_export/` JSONL files
   - Detects when `search_brain` was called and what query was used
   - Detects when a returned memory ID appears later in the same session (positive signal) vs. doesn't (negative signal)
   - Writes found signals as `feedback_events` rows
2. Run once as backfill, then wire into session_end hook.

**Files to touch:** `brain/tools/` (new script), `brain/hooks/session_end.py`

---

### GAP-3 — `importance` field always 0.5
**Severity: MEDIUM**

Every memory is born with `importance=0.5` and it never changes. The field exists in the schema and `retrieval_rerank.py` already has logic to adjust distances. Dynamic scoring would let high-signal memories rise and noise sink.

**What to do:**
1. Decay importance for memories that are never retrieved (age > 90 days, no feedback → decay to 0.3).
2. Boost importance on positive feedback (GAP-1).
3. Wire `importance` into the RRF scoring in `brain.rs` `search()`: multiply final_score by `importance` (not recency — keep those orthogonal).

**Files to touch:** `brain/rust/src/brain.rs` `search()`, `brain/rust/src/store.rs` (add `update_importance`), new `brain/tools/decay_importance.py`

---

### GAP-4 — `rerank_results.py` not wired into production
**Severity: MEDIUM**

`brain/tools/retrieval_rerank.py` has vault path boost (−0.12) and short-content penalty (+0.08 for q≥12 words) but is never called by `api_client.search` or `search_brain` MCP. It only runs if you call it manually.

**What to do:**
Wire it as a post-processing step in `brain/core/memory.py` `search()` and/or the Rust API `/search` endpoint response handler in `api_client.py`.

**Files to touch:** `brain/api_client.py` `search()`, or port logic into `brain/rust/src/brain.rs`

---

### GAP-5 — No `human_fact` memory type
**Severity: MEDIUM**

All 6 memory types (`conversation`, `solution`, `pattern`, `decision`, `project_context`, `error_lesson`) are about code or projects. Personal facts ("user is left-handed", "user's daughter is named X", "user prefers X approach when tired") have no first-class home. They get stored as `conversation` and are buried.

**What to do:**
1. Add `human_fact` to `MemoryType` enum in `brain/rust/src/types.rs` (and Python `brain/core/memory.py`).
2. Add a migration in `brain/rust/src/migrate.rs` to reclassify qualifying existing memories.
3. Add a `human_fact` extraction pass to `session_end.py` — LLM prompt that pulls personal facts from the transcript before the full session ingest.

**Files to touch:** `brain/rust/src/types.rs`, `brain/rust/src/migrate.rs`, `brain/hooks/session_end.py`, `brain/core/memory.py`

---

### GAP-6 — `title` missing on ~70% of corpus
**Severity: MEDIUM**

FTS5 indexes both `content` and `title`, but `title` is only populated for Obsidian chunks. Session, claw, perplexity memories have empty titles. This weakens BM25 retrieval for those sources.

**What to do:**
1. In `07_ingest_claude_code.py` and `05_ingest_claw.py`: extract a title from the first line / first sentence of the summary.
2. In `session_end.py`: set `title` to the LLM-generated session summary headline.
3. For existing corpus: add a backfill script `brain/tools/backfill_titles.py` that sets `title` from `content[:80]` for memories where it's NULL.

**Files to touch:** `brain/bootstrap/07_ingest_claude_code.py`, `brain/bootstrap/05_ingest_claw.py`, `brain/hooks/session_end.py`, new `brain/tools/backfill_titles.py`

---

### GAP-7 — ocreamer/sicop retrieval ceiling at P@1≈0.50
**Severity: HIGH** (if ocreamer work resumes)

206 ocreamer memories are raw PDF chunks (Costa Rica AI Strategy × 123, ESPECIFICACIONES TECNICAS × 46, INVU tender × 23). No titles. Adjacent-page embeddings overlap heavily. P@1=0.500, up from 0.228 after RRF but stuck.

**Root cause:** Ingest problem, not retrieval. Chunks are too granular and lack semantic identity.

**What to do:**
1. Re-ingest ocreamer PDFs with per-chunk LLM summaries as `title` field.
2. Merge adjacent near-duplicate chunks (cosine distance < 0.05) into single memory during ingest.
3. Add `brain/bootstrap/reingest_ocreamer_docs.py` (stub already exists at `brain/tools/reingest_ocreamer_docs.py`).

**Files to touch:** `brain/tools/reingest_ocreamer_docs.py`, `brain/bootstrap/pdf_to_md.py`

---

### GAP-8 — Knowledge graph is export-only
**Severity: LOW**

`brain/tools/export_knowledge_graph.py` builds per-memory Obsidian notes with wikilinks to top-N neighbors, but this is a one-way export — the graph structure isn't used to improve retrieval. Neighbor relationships are computed on every export but thrown away after.

**What to do:**
Add a `memory_links` table to SQLite that stores `(source_id, target_id, score)` and is populated during graph export (or continuously on save). Use it in search to boost memories that are neighbors of a high-scoring hit (graph expansion round).

**Files to touch:** `brain/rust/src/store.rs` (new table), `brain/rust/src/brain.rs` (graph expansion in search), `brain/tools/export_knowledge_graph.py`

---

### GAP-9 — `thread_id` never populated
**Severity: LOW**

`thread_id` column exists in the schema but is always NULL. Can't group related conversation turns or link a memory back to the session message thread it came from.

**What to do:**
Populate `thread_id` with the session ID in PostToolUse hook so related memories from the same session cluster together. Useful for timeline_tool navigation.

**Files to touch:** `brain/hooks/post_tool_use.py`, `brain/rust/src/bin/brain_post_tool_use.rs`

---

## Priority Order

| # | Gap | Effort | Impact |
|---|---|---|---|
| 1 | GAP-2: Session mining for ground truth | Medium | High |
| 2 | GAP-1: Close feedback loop → importance | Medium | High |
| 3 | GAP-6: Backfill titles on corpus | Low | Medium |
| 4 | GAP-3: Dynamic importance scoring | Medium | Medium |
| 5 | GAP-4: Wire reranker into production | Low | Medium |
| 6 | GAP-5: `human_fact` memory type | Medium | Medium |
| 7 | GAP-7: Re-ingest ocreamer PDFs | High | High (project-specific) |
| 8 | GAP-8: Graph-based retrieval expansion | High | Low |
| 9 | GAP-9: Populate thread_id | Low | Low |

---

## Quick wins (do first, <1 hour each)

1. **GAP-6 backfill_titles.py** — one script, no schema change, immediate FTS5 improvement
2. **GAP-4 wire reranker** — 5-line change in `api_client.py`, already written
3. **GAP-9 populate thread_id** — 2-line change in PostToolUse hook
