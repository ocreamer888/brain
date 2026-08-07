# Knowledge Memory Type + Adaptive Proximity Grounding

**Date:** 2026-08-06  
**Status:** Shipped 2026-08-06 — all 8 implementation steps landed, live-verified on loopback `brain_api`  
**Approach:** A — new `MemoryType::Knowledge` + proximity-weighted retrieval / grounding hints

## Problem

Agents need a **source-of-truth corpus** (documentation, books, specs, manuals) so they can ground answers in real authored material—not session crumbs, not May `fact_type` extract sludge, not invent-from-empty-transcript recycling.

Today:

- Rich vault/doc material often lands as `project_context` / `conversation` / undifferentiated `fact`, mixed with noise.
- There is no first-class type for “authored library chunk with provenance.”
- Grounding is either absent or imagined as a global hard/soft switch—too blunt for real work (debug CSS vs “what does Tilopay webhook X mean?”).

Product intent (owner): fill Brain with **real rich data** so any agent can become more professional—build, fix, and understand better—with less hallucination when the corpus is nearby.

## Goals

1. Add **`knowledge`** as a first-class `MemoryType` for authored corpus chunks (docs, books, papers, manuals, specs).
2. Provide a **dedicated ingest path** that preserves provenance (`source`, `file_path`, title, optional `derived_from`).
3. Apply a **tiny, context-aware retrieval boost** for knowledge when relevant (proximity + project match)—not a flood.
4. Surface an adaptive **`grounding_hint`: `hard` | `soft` | `off`** to MCP/agents from the score landscape (not a global mode).
5. Keep knowledge **strictly separate** from session recycling and fact-extractor backfill.

## Non-goals (v1)

- Auto-converting existing `fact_type:*` rows into `knowledge`
- Auto-tagging Stop-hook / recycling / PostToolUse output as `knowledge`
- New `MemoryType` rename bikeshed to `reference` (name is `knowledge`; revisit only if product language confuses users)
- Hard “refuse unless cite” enforcement inside `brain_api` (hint only; agent skill can follow)
- Turning `graph_expand` on by default
- Full re-embed / ONNX changes
- UI “Knowledge” tab (follow-up)
- Changing quarantine of path-fragment facts (orthogonal; stays)

## Decisions

| Topic | Choice |
| --- | --- |
| Shape | New enum variant `Knowledge` / wire name `knowledge` |
| vs tag-only | Rejected — corpus needs type-level filter, diversity, ingest boundary |
| vs existing `fact` | `fact` = atomic extract; `knowledge` = rich authored chunk with provenance |
| vs `project_context` | `project_context` = project state/session briefs; `knowledge` = library/reference material |
| Grounding | **Adaptive** proximity weights + hint — not fixed hard-or-soft |
| Who writes | Deliberate corpus ingest + agents/MCP with explicit `memory_type=knowledge`; **never** session_recycling / fact_extractor |
| Durable entity linking | Include `knowledge` in durable types for auto-entities (same as other durable non-episode types) |
| Boost magnitude | Tiny base prior; scales with closeness + project match; hard-capped |
| Boost mechanism | **Single knob** — corpus salience stays neutral (0.5); `knowledge_w` is the only corpus-trust mechanism. Salience 0.7 + `K_BASE` would double-count (`salience_w` 1.06 × cap 1.22 ≈ 1.29×) and make the "twins" test untestable |
| Score exposure | Add `score` (final ranked score) to `SearchResult` + API response — `grounding_hint` must see the hybrid score, not cosine distance alone (BM25 keyword wins are invisible to distance) |
| Ingest idempotency | Content hash per chunk; re-ingest supersedes changed chunks with same `file_path`, skips unchanged — no duplicate flood from re-running the CLI |

## Architecture

```text
Docs / books / specs (files)
        │
        ▼
brain/ingest/*  (chunk + provenance)
        │
        ▼
save_memory(type=knowledge, file_path=…, source=…, project=…)
        │
        ▼
SQLite + vector index  (same store; type discriminates)

Query (MCP / API)
        │
        ▼
Brain::search  ──► hybrid score × salience_w × recency_w × knowledge_w(proximity, project)
        │
        ▼
results + grounding_hint(hard|soft|off)   # MCP layer derives from distances / scores
```

## Components

### 1. Schema / type wire format

**Rust** `brain/rust/src/types.rs`:

- Add `Knowledge` to `MemoryType` (`snake_case` → `"knowledge"`).
- Update serde tests / `from_str` / display helpers if present.
- Update any exhaustive matches (save, filter, diversity, UI type lists).

**Python** (MCP coerce, hooks, ingest):

- Accept `memory_type="knowledge"` everywhere types are parsed.
- Unknown labels still coerce to `conversation` (existing behavior)—document that `knowledge` is now known.

**MemorySource:** reuse existing sources where possible (`Obsidian`, `ObsidianBooks`, new optional later). Do **not** invent a source per book; use `file_path` + title for provenance. Optional v1.1: `MemorySource::Corpus` if needed—**out of v1** unless ingest is blocked without it.

### 2. Ingest path

New or extended helper under `brain/ingest/` (canonical ingest library):

- Chunk docs/books via existing `text_chunking.py` (section/paragraph + word budget).
- Each chunk saved as `memory_type=knowledge` with:
  - `file_path` = source path or URI
  - `title` = doc title + section
  - `project` = owning product when known, else `general` / corpus name
  - `source` = appropriate `MemorySource`
  - `salience` default **0.5** (neutral) — `knowledge_w` is the single corpus-trust knob; salience must not double-count it (see Decisions)
  - `tags` include `brain/ingest` + optional `corpus:<name>`
  - **Chunk ordering (write now, use later):** `doc_id` (stable id of the parent doc, e.g. hash of `file_path`) + `chunk_ordinal` (0-based position). Sibling/adjacent-chunk expansion at retrieval is v1.1, but these fields must be written at ingest time — retrofitting means re-ingesting the whole corpus. Two metadata fields, nearly free.
  - **Content hash:** hash of the chunk text stored in metadata for idempotency (below).
- **Idempotent re-ingest:** docs get updated and re-run. On ingest, look up existing `knowledge` rows with the same `file_path`: skip chunks whose content hash is unchanged; **supersede** chunks whose hash changed (store already supports `exclude_superseded`). Re-running the CLI on an unchanged doc adds zero rows.
- **Kill switches:** none required beyond not wiring hooks to this path.
- CLI: `brain/tools/ingest_knowledge.py` (or extend an existing vault ingest with `--as-knowledge`) — exact name in plan.

**Forbidden writers (must not set type=knowledge):**

- `session_end` / `session_ingest` recycling passes
- `fact_extractor` / `backfill_facts`
- PostToolUse edit-group flush

**Enforced in code, not convention:** each forbidden path gets a one-line guard that rejects (or coerces away from) `type=knowledge`, plus a test per path. Success criterion 4 must not depend on nobody making a mistake.

### 3. Retrieval: proximity-weighted knowledge prior

In `Brain::search` scoring (after existing `salience_w` / `recency_w`):

```text
final_score = salience_w * recency_w * hybrid_score * knowledge_w

knowledge_w starts at 1.0
  + K_BASE   if type == knowledge          # e.g. 0.06
  + K_PROJ   if filter.project matches     # e.g. 0.08 (only when project filter set OR
                                           #          request carries working_project—see below)
  + K_CLOSE * closeness(distance)          # e.g. up to 0.10 when distance is excellent

Clamp knowledge_w to [1.0, 1.22]
```

**Closeness (decided): smoothstep between τ_far and τ_close**, applied only to `knowledge` rows — zero boost at/beyond τ_far, full `K_CLOSE_MAX` at/inside τ_close. A plain `(1 - distance)` was rejected: it leaks boost to junk (a knowledge hit at distance 0.7 — beyond the spec's own "not usefully close" line — would still get +0.03). The smoothstep reuses the **same τ constants as `grounding_hint`** so the ranker and the hint cannot disagree about what "close" means.

**Score exposure:** add `score: f32` (the final ranked score) to `SearchResult` and the API response. Today `final_score` is dropped at the truncate and only cosine `distance` reaches the MCP layer — but ranking is hybrid (`alpha*cos + (1-alpha)*bm25`), so a knowledge chunk can lead on an exact BM25 keyword match while its distance looks mediocre. `grounding_hint` needs the real score, and every future tuning session needs it measurable. Small additive change; in v1.

**Working project without filter:** v1 may only apply `K_PROJ` when `SearchFilter.project` is set (MCP `project=`). Optional v1.1: pass `working_project` in search request without hard-filtering—**out of v1** unless trivial.

**Constants:** named in Rust (`K_BASE`, `K_PROJ`, `K_CLOSE_MAX`, clamp) and documented; tune via env later if needed (`BRAIN_KNOWLEDGE_BASE` etc.)—env optional in v1 (hardcoded constants OK).

### 4. Adaptive grounding hint (MCP)

Not a ranker-only concern. After search, MCP formats results and computes:

```text
d*  = min distance among hits with type==knowledge (if any)
Δ   = score_gap(best_knowledge, best_other)   # real ranked scores — exposed on SearchResult (see §3)
g   = any top-k knowledge hit has project == request.project
leads = best_knowledge_score ≥ best_other_score   # catches BM25 keyword wins that distance alone would miss

if no knowledge in top-k OR (d* > τ_far AND NOT leads):
    grounding_hint = off
elif (d* ≤ τ_close OR leads) AND (g OR Δ clearly positive):
    grounding_hint = hard
else:
    grounding_hint = soft
```

**Initial thresholds (tunable):**

| Symbol | Start | Meaning |
| --- | --- | --- |
| τ_close | ~0.35 distance | “nearby” corpus hit |
| τ_far | ~0.55 distance | “not usefully close” |

(Exact numbers validated in implementation plan with a small fixture; adjust if live ONNX distances differ.)

**Agent contract (documentation in MCP tool description):**

- `hard` — Prefer citing knowledge hits; if answering factual/doc questions, say when corpus lacks coverage. May re-query with `memory_type=knowledge` to bypass the diversity cap (see §5).
- `soft` — Prefer knowledge when relevant; other types OK.
- `off` — Normal hybrid; no cite pressure.

v1 does **not** block answers inside the API.

### 5. Type diversity

Existing diversity rerank caps any single type at 40% of `n`. Knowledge participates like other types—**no special exemption**. Corpus must not drown solutions when both match.

**Escape hatch (documented, zero code):** for a pure doc question the cap limits knowledge to 4 of 10 even when the top 8 relevant hits are all corpus. Diversity only applies when no type filter is set — so the MCP tool description tells agents: on `grounding_hint=hard`, re-query with `memory_type=knowledge` to get the full corpus ranking.

### 6. Durable entity linking

Add `knowledge` to `DURABLE_MEMORY_TYPES` in `entity_extractor` / api_client auto-entities path so corpus chunks get entity edges like other durable types. `episode` remains excluded.

## Write rules (product)

Apply `memory_type=knowledge` only when:

1. Content is **authored reference** (doc/book/spec/manual/paper chunk), not a chat summary.
2. **Provenance** is set (`file_path` and/or clear `source` + title).
3. Chunk is **self-contained enough** to retrieve (ingest chunking rules).
4. Save is **deliberate** corpus ingest or explicit agent/MCP choice.

Never use `knowledge` for:

- Session recycling summaries / invented error-fix pairs  
- Fact-extractor atoms  
- One-off CSS/lint tweaks  
- “Assistant will…” future plans  

## Success criteria

1. Can ingest a sample doc → rows with `type=knowledge`, `file_path`, `doc_id`, `chunk_ordinal`, content hash set; searchable via `memory_type=knowledge`.
2. Query with a close doc chunk nearby → knowledge hits rank slightly higher than twins without the type prior (clean test: corpus salience is neutral 0.5, so `knowledge_w` is the only differentiator); `grounding_hint` is `hard` or `soft` as expected on fixtures.
3. Query with no nearby corpus → `grounding_hint=off`; unrelated knowledge does not dominate (smoothstep gives zero boost beyond τ_far).
4. Session Stop-hook path never writes `knowledge` — enforced by code guards with a test per forbidden path, not convention.
5. Re-running ingest on an unchanged doc adds zero rows; a changed chunk supersedes its predecessor.
6. API/MCP responses include `score`; hint fixtures cover a BM25-keyword-win case where distance alone would say `off`.
7. Rust + Python tests for type parse, scoring multiplier bounds, and hint thresholds.
8. Live smoke on Mac Studio `brain_api` after deploy (type round-trip + one search).

## Risks

| Risk | Mitigation |
| --- | --- |
| Knowledge flood like fact backfill | No auto-backfill; deliberate ingest only |
| Over-boost drowns working memory | Tiny clamp; type diversity unchanged |
| Wrong τ for distances | Fixture + live canary; constants easy to retune |
| Agents ignore `grounding_hint` | Document in MCP; optional follow-up skill |
| Name collision with colloquial “knowledge” | Spec + MCP docs: type = corpus library |

## Open questions (non-blocking for v1)

1. Exact CLI name / whether Obsidian books path defaults to `knowledge` vs opt-in flag.
2. Whether `working_project` boost without hard filter lands in v1.1.
3. Follow-up agent skill for hard-cite discipline.

## Implementation order (preview)

1. Type enum + coerce + tests  
2. Expose `score` on `SearchResult` + API response  
3. Scoring `knowledge_w` (smoothstep closeness) + unit tests  
4. Forbidden-writer guards + tests  
5. MCP grounding_hint (score-aware) + tool description (incl. `hard` → filtered re-query)  
6. Ingest CLI (idempotent; `doc_id`/`chunk_ordinal`/hash) + one sample corpus smoke  
7. Durable-types include `knowledge`  
8. Deploy/restart `brain_api` + live verify  

## References

- Prior audit: fact-layer 82% corpus / path-fragment quarantine (2026-08-06/07)  
- Owner decision: Approach A + adaptive proximity grounding (this thread)  
- Related: durable entity linking seven types — **amend to eight** by adding `knowledge`
