# Entity + Edge Graph Layer

Lightweight knowledge-graph layer bolted onto the existing hybrid (vector + FTS5) memory store. Stops dropping LLM-extracted entity names; persists them as first-class SQLite **nodes** plus fact→entity **edges**, and adds optional 1-hop graph expansion to retrieval.

- **Branch:** `feature/entity-edge-graph`
- **Plan:** `docs/superpowers/plans/2026-07-22-entity-edge-graph.md`
- **Status:** Phases A–D shipped. `graph_expand` is **OFF by default** (opt-in) — see [Evaluation](#evaluation--recommendation).

## Why (design decision)

Cognee-style knowledge graphs were researched. We deliberately **did not** adopt Neo4j / Kuzu / RDF / cognee. Rationale:

- The brain was already extracting entity names during fact extraction, then **throwing them away**.
- The smallest change that captures real value is to persist those names in SQLite and reuse them for 1-hop expansion — no new service, no new datastore, no new dependency.
- Everything stays in the existing `brain.db` SQLite file, written through the existing `brain_api` `/save` path.

Rejected / deferred ideas live in the plan's *Out of scope* table (typed relations beyond `mentions`, multi-hop, triplet embeddings, feedback edge reweighting, Neo4j/Kuzu/cognee).

## Data model

Two idempotent tables (`CREATE TABLE IF NOT EXISTS`), created in `brain/rust/src/store.rs::create_tables`:

```sql
CREATE TABLE IF NOT EXISTS entities (
    id TEXT PRIMARY KEY,              -- uuid5(NAMESPACE_OID, "entity:" || name_normalized)
    name TEXT NOT NULL,               -- display form (first-seen casing)
    name_normalized TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_entities_name_norm ON entities(name_normalized);

CREATE TABLE IF NOT EXISTS edges (
    id TEXT PRIMARY KEY,              -- uuid4
    src_memory_id TEXT NOT NULL,      -- fact (or other memory) id
    dst_entity_id TEXT NOT NULL,      -- entities.id
    relation_type TEXT NOT NULL DEFAULT 'mentions',
    weight REAL NOT NULL DEFAULT 1.0,
    created_at TEXT NOT NULL,
    UNIQUE(src_memory_id, dst_entity_id, relation_type)
);
CREATE INDEX IF NOT EXISTS idx_edges_src ON edges(src_memory_id);
CREATE INDEX IF NOT EXISTS idx_edges_dst ON edges(dst_entity_id);
```

**Entity identity is deterministic** — same name always maps to the same node (upsert):

```text
name_normalized = " ".join(name.strip().split()).lower()   # empty → dropped
entity_id       = uuid5(NAMESPACE_OID, "entity:" + name_normalized)
```

The Rust normalize rule (`store.rs::normalize_entity_name` / `entity_id_for`) and any Python caller must match. Relation type is the fixed string `"mentions"` in v1 (fact → entity).

## Write path (how edges get created)

Entities ride along with a normal save — upsert + edge creation happen right after the memory is persisted:

```
FactDraft.entities
  → api_client.save_memory(..., entities=[...])
  → POST /save { ..., "entities": ["SQLite", "brain"] }
  → Brain::link_entities(memory_id, names)
  → store.link_memory_entities  (upsert each entity + "mentions" edge)
```

- Wired in `brain/ingest/fact_curator.py::_save_fact` (forwards `draft.entities`).
- **Linking never fails the save.** If edge creation errors, the fact is still persisted and `/save` returns 200 (fact > edges). Applies to `/save` and per-item on `/save-batch`.
- Writes go **only** through the HTTP API (launchd `brain_api` owns the DB). Never write entities via a direct SQLite path.

## Retrieval — `graph_expand`

`Brain::search` takes an optional `graph_expand` flag (default `false`). When `true`, after the normal hybrid ranking:

1. Take the top `min(n, 5)` ranked hits as **seeds**.
2. Look up 1-hop entity-sharing neighbors (`neighbor_memory_ids`, skips superseded).
3. Score each neighbor as `seed_score * GRAPH_HOP_DECAY` (**0.85**, `brain/rust/src/brain.rs`). When a neighbor is reachable from multiple seeds, the highest seed score wins.
4. Merge (neighbors already in the list are skipped), re-sort, truncate to `n`.

**Key property:** neighbors are scored *below* their seed (×0.85), so expansion can lift **recall** (pull a missing memory into top-k) but can **never change P@1** (a neighbor cannot outrank the seed that surfaced it). Default search behavior is unchanged unless the flag is set.

## API

New/changed endpoints on `brain_api` (see `docs/PHASE4_API.md` for the full API + auth/rate-limit setup).

### `POST /save` — `entities` field

```json
{ "content": "Chose SQLite for the brain graph", "memory_type": "decision",
  "project": "brain", "entities": ["SQLite", "brain"] }
```

Optional `entities: string[]`. Also accepted per item on `POST /save-batch`.

### `POST /search` / `POST /v1/search_index` — `graph_expand`

```json
{ "query": "cognee graph", "n": 5, "graph_expand": true }
```

`graph_expand` defaults to `false`.

### `GET /entities?memory_id=<id>`

```json
{ "entities": [ { "id": "<uuid>", "name": "SQLite" } ] }
```

### `GET /neighbors?memory_id=<id>&exclude_superseded=true`

```json
{ "ids": ["<memory-uuid>", "..."] }
```

`exclude_superseded` defaults to `true`.

### `POST /link-entities`

Attach entities to an already-saved memory (used by the backfill tool).

```json
{ "memory_id": "<uuid>", "entities": ["Ollama", "Rust"] }
```

Response: `{ "linked": 2 }`

### Curl examples

```bash
# save a fact with entities
curl -sS -X POST http://127.0.0.1:8787/save \
  -H "content-type: application/json" -H "x-api-key: local-dev-key" \
  -d '{"content":"Chose SQLite for the brain graph","memory_type":"decision","project":"brain","entities":["SQLite","brain"]}'

# search with graph expansion
curl -sS -X POST http://127.0.0.1:8787/search \
  -H "content-type: application/json" -H "x-api-key: local-dev-key" \
  -d '{"query":"cognee graph","n":5,"graph_expand":true}'

# entities for a memory
curl -sS "http://127.0.0.1:8787/entities?memory_id=<id>" -H "x-api-key: local-dev-key"

# 1-hop neighbors
curl -sS "http://127.0.0.1:8787/neighbors?memory_id=<id>&exclude_superseded=true" -H "x-api-key: local-dev-key"

# link entities onto an existing memory
curl -sS -X POST http://127.0.0.1:8787/link-entities \
  -H "content-type: application/json" -H "x-api-key: local-dev-key" \
  -d '{"memory_id":"<id>","entities":["Ollama","Rust"]}'
```

## Python client (`brain/api_client.py`)

```python
search(query, n=10, ..., graph_expand=False) -> list[dict]
save_memory(content, ..., entities: list[str] | None = None) -> str
get_entities(memory_id) -> list[dict]          # [{"id","name"}, ...]
get_neighbors(memory_id, exclude_superseded=True) -> list[str]   # memory ids
link_entities(memory_id, entities) -> int      # count linked
```

## MCP tools (`brain/mcp/server.py`)

- `search_brain(query, ..., graph_expand=False)` — forwards the flag to `/search`.
- `get_neighbors_tool(memory_id)` — returns 1-hop neighbor IDs (then use `get_observations_tool` to expand). Requires `BRAIN_BACKEND=api`.

## Backfill — `brain/tools/backfill_entities.py`

Adds entities to historical facts that have zero edges. Resumable and safe to re-run.

```bash
# dry run (prints planned entities, no writes)
python3 brain/tools/backfill_entities.py --dry-run --limit 20

# real run (all edge-less active facts)
python3 brain/tools/backfill_entities.py

# scoped / capped / fresh
python3 brain/tools/backfill_entities.py --project brain --limit 500
python3 brain/tools/backfill_entities.py --reset-checkpoint
```

> Use the repo venv interpreter — `requests` is not on system `python3`:
> `/Users/abundancia888/Documents/AI/.venv/bin/python brain/tools/backfill_entities.py ...`

Behavior:

- Selects active facts (`type=fact`, not superseded) with **no** edges.
- Cheap dedicated Ollama prompt (`OLLAMA_SUMMARIZE_MODEL`, temp 0) — **not** the full `fact_extractor`.
- Defensive JSON parse (never raises) → `_clean_entities` filter → `POST /link-entities`.
- **Checkpoint:** `brain/bootstrap/checkpoint_entity_backfill.json` (`processed_ids`, `linked_total`, `facts_seen`).
- On API error (e.g. HTTP 429), the fact is **not** checkpointed, so it is retried on the next run — just re-run to mop up rate-limited facts.

### Entity noise control

`_clean_entities` prevents junk "hub" nodes from over-connecting unrelated facts:

- Drops a `_ENTITY_STOPLIST` of generic VCS/shell verbs (`git`, `commit`, `push`…), placeholder tokens (`file_path`, `url`, `id`…), and ultra-generic nouns (`code`, `file`, `project`, `system`…).
- Drops names `< 2` chars or with no alphanumeric char.
- Dedupes case-insensitively; caps at `MAX_ENTITIES_PER_FACT = 12`.

## Evaluation & recommendation

Post-backfill graph state (2026-07-23): **8,668 entities**, **20,789 edges**, **9,103 / 12,933 facts linked (~70%)**. Top hubs are all legitimate domain entities (`Next.js`, `React`, `Supabase`, `Tailwind CSS`, `SICOP`, `TypeScript`) — the stoplist held, zero junk hubs.

Gold eval (`brain/eval/gold_semantic.jsonl`, 14 queries), `graph_expand` on vs off:

| metric | off | on | delta |
|---|---|---|---|
| P@1 | 0.3571 | 0.3571 | +0.0000 |
| MRR | 0.4893 | 0.4893 | +0.0000 |
| recall@10 | 0.9286 | 0.9286 | +0.0000 |

**Zero measurable delta — for structural reasons, not a bug:**

1. Recall is already saturated (92.86%) — almost no headroom for expansion to fill.
2. Only **2/14** gold targets have edges (backfill linked `fact`-type only; the gold set is dominated by `solution`/`error_lesson`/`pattern`/`conversation`/`project_context`, which have no edges). `graph_expand` reaches memories only through edges, so it literally cannot touch those targets.

**Recommendation: keep `graph_expand` OFF by default** (as shipped). No measured gain, and it adds latency + noise-hub risk. To measure real value later, build a gold set whose targets are edge-linked `fact` memories, **or** extend entity linking beyond `fact`-type memories.

Eval artifacts: `brain/eval/runs/2026-07-22_phase-c-graph-expand.json`, `brain/eval/runs/2026-07-23_post-backfill-eval.json`.

## Files touched

| File | Responsibility |
|---|---|
| `brain/rust/src/store.rs` | `entities`/`edges` DDL, CRUD, `neighbor_memory_ids`, normalize/uuid5 |
| `brain/rust/src/types.rs` | `SearchFilter.graph_expand` (default false) |
| `brain/rust/src/brain.rs` | `link_entities`, `neighbor_memory_ids`, `expand_graph_neighbors`, `GRAPH_HOP_DECAY` |
| `brain/rust/src/bin/brain_api.rs` | `/save` + `/save-batch` `entities`; `graph_expand`; `GET /entities`, `GET /neighbors`, `POST /link-entities` |
| `brain/api_client.py` | `save_memory(entities=)`, `search(graph_expand=)`, `get_entities`, `get_neighbors`, `link_entities` |
| `brain/ingest/fact_curator.py` | `_save_fact` forwards `draft.entities` |
| `brain/mcp/server.py` | `search_brain(graph_expand=)`, `get_neighbors_tool` |
| `brain/tools/backfill_entities.py` | historical entity backfill (stoplist, checkpoint) |
| `brain/tests/test_fact_curator.py`, `brain/tests/test_backfill_entities.py` | coverage |

## Config / constants

- `GRAPH_HOP_DECAY = 0.85` — neighbor score multiplier (`brain/rust/src/brain.rs`).
- Seed count for expansion: `min(n, 5)`.
- `MAX_ENTITIES_PER_FACT = 12`, `PROGRESS_EVERY = 25` (`backfill_entities.py`).
- Backfill LLM: `OLLAMA_URL` + `OLLAMA_SUMMARIZE_MODEL` (`brain/config.py`).
- `exclude_superseded` stays default `true`; hop expansion skips superseded facts.

## Follow-ups (not built)

- Extend entity linking beyond `fact`-type memories (needed to actually prove retrieval value).
- Typed relations beyond `mentions`; multi-hop (`hops=2`); triplet embeddings; feedback edge reweighting.
- Flip `graph_expand` on by default — only after a gold set demonstrates a lift.
