# Durable Entity Linking (Beyond Facts)

**Date:** 2026-07-28  
**Status:** Approved for planning  
**Approach:** A — shared Python extractor + golden-path wrap + widened backfill

## Problem

Entity + edge tables and `/save` / `/link-entities` already accept any memory id. Live extraction and backfill are still **fact-scoped**. Linked UI and optional `graph_expand` therefore miss most durable knowledge (`solution`, `decision`, `pattern`, `project_context`, `error_lesson`, `conversation`).

## Goals

- Link entities for **durable** memory types on every golden-path save when entities are not already provided.
- Backfill historical **edgeless** durable memories via the existing checkpointed tool pattern.
- Keep fail-soft behavior: Ollama failure must not block memory save.
- Leave default retrieval unchanged (`graph_expand` stays off until a later eval proves lift).

## Non-goals

- Linking `episode`
- Turning `graph_expand` on by default
- Async queue / background worker for extraction
- Extracting inside Rust `brain_api` `/save`
- Schema changes (tables already support any `src_memory_id`)
- Typed relations beyond `"mentions"`
- New Linked UI features
- Auto-extract on `BRAIN_BACKEND=python` saves (API golden path only)

## Decisions

| Topic | Choice |
| --- | --- |
| Types | Seven durable types: `fact`, `solution`, `decision`, `pattern`, `project_context`, `error_lesson`, `conversation` (amendments D1). Only `episode` is excluded (D2). |
| Timing | Live on save **and** historical backfill |
| Architecture | Shared Python extractor; auto-fill in `api_client` save helpers |
| Caller entities | If `entities` already non-empty → skip extract (facts via curator keep current path) |
| Failures | Extract errors → `[]`; save proceeds without edges |
| `graph_expand` | Remains default `false` until `brain/tools/graph_expand_ab.py` returns verdict **PASS** (amendments A1). The previous "until new gold eval" wording was unfalsifiable — the old 14-query set could not detect the effect at any size. |
| Checkpoint | New checkpoint file for durable backfill (do not treat fact-only progress as complete) |

## Architecture

```text
hooks / MCP / tools
        │
        ▼
api_client.save_memory*  ──if durable & entities empty──► entity_extractor (Ollama)
        │                                                      │
        │◄──────────────── entities list ──────────────────────┘
        ▼
POST /save  (Rust upserts memory + entities/edges when entities present)
```

Backfill (separate):

```text
SQLite RO select edgeless durable types
        ▼
entity_extractor
        ▼
POST /link-entities  (never direct SQLite writes)
```

## Components

### 1. `brain/ingest/entity_extractor.py` (new)

- Move prompt, stoplist, clean/cap, parse, and Ollama call out of `backfill_entities.py`.
- Public surface: `extract_entities(text: str) -> list[str]` (never raises; returns `[]` on failure).
- Constants: durable type frozenset, max entities (12), stoplist — single source of truth.
- Do **not** reuse `fact_extractor`’s heavy fact-draft prompt; keep the cheap named-entity prompt.

### 2. `brain/api_client.py`

- Before `POST /save`: if `memory_type` in durable set and `entities` is missing/empty, call `extract_entities(content)` and attach result.
- Apply to `save_memory` and `save_memory_with_status` only. **`save_memory_batch` is deliberately pass-through: it forwards caller-supplied `entities` but never calls the extractor** (amendments A4). This asymmetry is intentional — do not "fix" it. All three batch callers are bulk paths (two send only `conversation`; the third is an unresumable migration script), so batch auto-extraction would have had no live consumer while adding unbounded serial LLM cost with no checkpointing. Those rows are picked up by `backfill_entities.py` instead.
- Gated by `auto_entities: bool = True` per call, plus the OFF-only `BRAIN_AUTO_ENTITIES` env kill switch. 14 bulk ingest call sites opt out explicitly.
- MCP and hooks already go through these helpers → no per-hook entity code required.
- `BRAIN_BACKEND=python` (manual QA only): **out of scope** for auto-extract this ship. Production golden path is `BRAIN_BACKEND=api`.

### 3. Fact path

- `fact_extractor` → `fact_curator` already forwards `draft.entities`.
- **`_save_fact` passes `auto_entities=False` unconditionally** (amendments D4, shipped at `fact_curator.py:192`). The fact path never falls back to the cheap extractor — not even when the curator's draft entities come back empty. Backfill covers the residual.
- Rationale: an emptiness heuristic would fire a second LLM call for ~22% of facts. That call is not useless (the dedicated NER prompt recovers entities for ~78% of the empty population), but the checkpointed backfill recovers the same rows off the hot path, so paying ~0.66 s synchronously per affected save buys latency, not coverage.

### 4. `brain/tools/backfill_entities.py`

- Select edgeless rows where `type` is one of the seven durable types (JSON-encoded type strings as today).
- Import shared extractor; drop duplicated prompt/stoplist.
- Use a **new** checkpoint path (e.g. `checkpoint_entity_backfill_durable.json`) so prior fact-only runs do not skip non-fact rows.
- Keep golden-path writes via `api_client.link_entities` only.
- Respect existing rate-limit / burst guidance (progress logging; no fire-and-forget shell hacks).

### 5. Docs

- Update `docs/ENTITY_EDGE_GRAPH.md` (scope + eval note).
- Update `AGENTS.md` learned fact: linking no longer fact-only for live + backfill.

## Error handling

| Case | Behavior |
| --- | --- |
| Ollama down / timeout | Log warning; save without entities |
| Unparseable LLM JSON | Treat as `[]` |
| `/link-entities` fail in backfill | Log; do **not** mark id processed (retry next run) |
| Empty extract (`[]`) | Mark id processed (avoid infinite re-extract loops) |
| Non-durable type | Never auto-extract |

**Backfill processed-id rule (locked):** mark processed on empty extract or on successful `link_entities`; leave unmarked if `link_entities` raises after a non-empty extract.

## Testing

- Unit: stoplist, clean, parse, durable-type gate.
- Mock LLM: `api_client` attaches entities for durable types; skips for `episode`; skips when entities pre-supplied.
- Backfill: SQL selection includes non-fact durable types (`conversation` included); excludes `episode`.
- No live Ollama required in CI.

## Success criteria

1. Saving a durable memory via MCP/hooks with Ollama up produces edges visible in Linked / `GET /entities`.
2. `backfill_entities.py` can process edgeless durable rows beyond facts.
3. Default search metrics path unchanged (`graph_expand=false`).
4. Existing fact curator entity forwarding still works without double LLM.

## Follow-ups (out of this ship)

- Gold set whose targets are edge-linked durable memories; re-run expand on vs off.
- Consider default `graph_expand=true` only after measured lift.
- Optional later: async extract worker if sync save latency becomes a real product pain.
