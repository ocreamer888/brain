# Entity + Edge Graph Layer

Lightweight knowledge-graph layer bolted onto the existing hybrid (vector + FTS5) memory store. Stops dropping LLM-extracted entity names; persists them as first-class SQLite **nodes** plus memory→entity **edges**, and adds optional 1-hop graph expansion to retrieval.

- **Branch:** `feature/entity-edge-graph`
- **Plan:** `docs/superpowers/plans/2026-07-22-entity-edge-graph.md`
- **Status:** Phases A–D shipped. `graph_expand` is **OFF by default** (opt-in) — see [Evaluation](#evaluation--recommendation).
- **Scope (locked):** entity linking covers the **seven durable memory types** — `fact`, `solution`, `decision`, `pattern`, `project_context`, `error_lesson`, `conversation`. **`episode` is excluded** (audit-body type; 0 rows in the DB). Single source of truth in code: `DURABLE_MEMORY_TYPES` in `brain/ingest/entity_extractor.py` (bare strings) and `_DURABLE_TYPES` in `brain/tools/backfill_entities.py` (JSON-quoted, for SQL).
- **Current data state:** the durable-7 code path is in place, but the widened backfill **has not been run yet** — today only `fact` memories carry edges (~9,096 linked). Non-fact durable types are edgeless until the backfill runs.

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

The Rust normalize rule (`store.rs::normalize_entity_name` / `entity_id_for`) and any Python caller must match. Relation type is the fixed string `"mentions"` in v1 (durable memory → entity).

## Write path (how edges get created)

Entities ride along with a normal save — upsert + edge creation happen right after the memory is persisted:

```
FactDraft.entities
  → api_client.save_memory(..., entities=[...])
  → POST /save { ..., "entities": ["SQLite", "brain"] }
  → Brain::link_entities(memory_id, names)
  → store.link_memory_entities  (upsert each entity + "mentions" edge)
```

- Wired in `brain/ingest/fact_curator.py::_save_fact` (forwards `draft.entities`, and passes `auto_entities=False` — the fact path never falls back to the cheap extractor; the backfill covers the residual).
- **Live auto-extraction** (`api_client._maybe_extract_entities`): `save_memory` / `save_memory_with_status` call the cheap extractor when *all* of — `entities` empty, `memory_type` in the durable-7, `auto_entities=True` (the default), and `BRAIN_AUTO_ENTITIES` not set to an off value. `BRAIN_AUTO_ENTITIES` is an **off-only kill switch**; it never forces extraction on for a caller that passed `auto_entities=False`. Bulk/migration ingest scripts pass `auto_entities=False` so they do not pay one LLM round-trip per row.
- **`save_memory_batch` is pass-through only, by design** — it forwards caller-supplied `entities` but never auto-extracts. Its callers are all bulk paths; memories saved through it land edgeless and are picked up by the backfill. Do not "fix" this back.
- Spool replay (`brain/hooks/spool.py`) forces `auto_entities=False`, so a retried save is not re-extracted on each of its up-to-8 attempts.
- **Linking never fails the save.** If edge creation errors, the fact is still persisted and `/save` returns 200 (fact > edges). Applies to `/save` and per-item on `/save-batch`.
- Writes go **only** through the HTTP API (launchd `brain_api` owns the DB). Never write entities via a direct SQLite path.

## Retrieval — `graph_expand`

`Brain::search` takes an optional `graph_expand` flag (default `false`). When `true`, after the normal hybrid ranking:

1. Take the top `min(n, 5)` ranked hits as **seeds**.
2. Look up 1-hop entity-sharing neighbors (`neighbor_memory_ids`, skips superseded).
3. Score each neighbor as `seed_score * GRAPH_HOP_DECAY` (**0.85**, `brain/rust/src/brain.rs`). When a neighbor is reachable from multiple seeds, the highest seed score wins.
4. Merge (neighbors already in the list are skipped), re-sort, truncate to `n`. **Ordering is `(score desc, id asc)` — deterministic.** Every neighbor of a seed gets the bit-identical score `seed_score × 0.85`, so ties are the norm, not the exception; the secondary key is the memory id (a unique primary key), which makes the sort total and the `truncate(n)` cut reproducible across calls and across process restarts. The same key is applied both when truncating the neighbor set and when re-sorting the merged result.

**Key property:** neighbors are scored *below* their seed (×0.85), so expansion can lift **recall** (pull a missing memory into top-k) while the top hit is preserved — pinned by the `graph_expand_preserves_top1` test in `brain/rust/src/brain.rs`. It is **not** free at ranks 2+: a live probe on 2026-07-28 injected 3 neighbors at ranks 2/3/4 and displaced 3 legitimate results. Default search behavior is unchanged unless the flag is set.

Two further properties, both previously wrong or unstated, now explicit:

- **Injected neighbors carry a real cosine distance.** `distance` is computed as `1 - cosine_similarity(query_embedding, neighbor_embedding)`, the same meaning it has everywhere else in the system. It is *not* the old hardcoded `1.0` — that value meant "orthogonal to the query" and silently cancelled expansion downstream (`hooks/post_tool_use.py` drops hits with `distance >= 0.5`; `tools/retrieval_rerank.py` sorts ascending). The corrected distance is reported only; it does **not** feed back into `score`.
- **`memory_type` / `project` / `exclude_superseded` filters apply to injected neighbors.** Neighbors are subject to the same predicates as base candidates, so a type- or project-filtered search can no longer have a neighbor of the wrong type or project injected into its results. (This was latent rather than visible while only `fact` had edges.)

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

Adds entities to historical **durable** memories that have zero edges — all seven durable types, not just facts. Resumable and safe to re-run.

```bash
# dry run (prints planned entities, no writes)
.venv/bin/python brain/tools/backfill_entities.py --dry-run --limit 20

# real run (all edge-less active durable memories)
.venv/bin/python brain/tools/backfill_entities.py

# scoped / capped / fresh
.venv/bin/python brain/tools/backfill_entities.py --project brain --limit 500
.venv/bin/python brain/tools/backfill_entities.py --reset-checkpoint
```

> Use **this repo's** venv interpreter — `.venv/bin/python` from the repo root
> (`/Users/abundancia888/Documents/Code/brain`). Verified: the system `python3`
> has neither `requests` nor `pytest`. The `Documents/AI/.venv` path previously
> documented here is **stale for this checkout** — do not use it.

Behavior:

- Selects active durable memories (`select_edgeless_durable`: the seven durable types, not superseded) with **no** edges. `episode` is never selected. Against the live DB this currently returns **~6,860 rows** (the DB is live and grows, so the count drifts).
- Cheap dedicated Ollama prompt (`OLLAMA_SUMMARIZE_MODEL`, temp 0) — **not** the full `fact_extractor`. The prompt, stoplist, parse and cap now live in `brain/ingest/entity_extractor.py`, shared with the live save path; `backfill_entities.py` keeps only selection, checkpoint I/O and `run()`.
- Input is head-truncated at `MAX_INPUT_CHARS = 8000` before prompting (`entity_extractor.py`).
- Defensive JSON parse (never raises) → `_clean_entities` filter → `POST /link-entities`.
- **Checkpoint:** `brain/bootstrap/checkpoint_entity_backfill_durable.json` (`processed_ids`, `linked_total`, `facts_seen`). The old fact-only `checkpoint_entity_backfill.json` is no longer read. Neither file exists in this checkout yet — no durable backfill has been run here. `brain/tools/seed_durable_backfill_checkpoint.py --source PATH` can seed the durable checkpoint from a legacy fact-only checkpoint (fact ids only, validated against the DB); the operator supplies `--source` explicitly, since the legacy file lives outside this repo.
- On API error (e.g. HTTP 429), the memory is **not** checkpointed, so it is retried on the next run — just re-run to mop up rate-limited rows.

### Entity noise control

`_clean_entities` (in `brain/ingest/entity_extractor.py`, shared by live save and backfill) prevents junk "hub" nodes from over-connecting unrelated memories:

- Drops a `_ENTITY_STOPLIST` of generic VCS/shell verbs (`git`, `commit`, `push`…), placeholder tokens (`file_path`, `url`, `id`…), and ultra-generic nouns (`code`, `file`, `project`, `system`…).
- Drops names `< 2` chars or with no alphanumeric char.
- Dedupes case-insensitively; caps at `MAX_ENTITIES_PER_FACT = 12`.

## Evaluation & recommendation

Graph state (measured 2026-07-28, unchanged from the 2026-07-23 fact backfill): **8,668 entities**, **20,789 edges**, **9,103 linked memories**, avg **2.28** edges per linked memory. Top hubs are all legitimate domain entities (`Next.js` deg 343, `React` 215, `Supabase` 199, `Tailwind CSS` 180, `SICOP` 162, `TypeScript` 151) — the stoplist held, zero junk hubs. **Only `fact` has edges** (~9,096 memories); the widened durable backfill has not been run.

### ⚠️ The 0.0000-delta table below is STRUCTURALLY UNINFORMATIVE — do not cite it as evidence

Gold eval (`brain/eval/gold_semantic.jsonl`), `graph_expand` on vs off:

| metric | off | on | delta |
|---|---|---|---|
| P@1 | 0.3571 | 0.3571 | +0.0000 |
| MRR | 0.4893 | 0.4893 | +0.0000 |
| recall@10 | 0.9286 | 0.9286 | +0.0000 |

**The zeros are an artifact of the experiment's structure, not a measurement of the feature:**

1. **n = 14 scored queries.** One query flipping is worth 7.1 pp; nothing smaller than that is even representable, and no significance test was run.
2. **0 of the 18 gold rows then in the file were edge-linked** (verified 2026-07-28; the file is now 17 rows after the dangling row was deleted). `graph_expand` reaches memories only through edges, so it could not reach a single gold target. An unreachable target cannot move — the identical numbers in the `on` column were guaranteed before the run started. (This supersedes the earlier "2/14 gold targets have edges" claim: entity/edge counts are unchanged since that run, so the re-verification stands.)
3. Recall was also already saturated (92.86% = 13/14), leaving **one query** of headroom.

A result that is forced by construction is not evidence for or against expansion. **Treat the table as a historical record of a null experiment, not as a finding.**

> **Eval artifacts: lost.** This table previously cited `brain/eval/runs/2026-07-22_phase-c-graph-expand.json` and `brain/eval/runs/2026-07-23_post-backfill-eval.json`. **Verified 2026-07-28: `brain/eval/runs/` does not exist in this checkout and neither file is present** — they were not carried over from the `Documents/AI` tree. The numbers above are therefore **unreproducible and unauditable**. The citation has been removed rather than left pointing at missing files.

**Replacement harness:** the first reproducible A/B will be the one produced by `brain/tools/graph_expand_ab.py` against an LLM-generated gold set (`brain/tools/gen_gold_graph.py`) whose targets are *edge-linked* durable memories — with interleaved on/off arms in one process, exact McNemar, bootstrap CIs and an explicit `UNDERPOWERED` verdict. Both tools exist in the tree, but the run has **not happened**: `brain/eval/gold_graph_expand.jsonl` has not been generated, no A/B has been executed, and `brain/eval/runs/` still does not exist. The gold set must also be built *after* the durable backfill, since every target has to be edge-linked for expansion to be able to reach it. `eval_suite.py` and `retrieval_eval_kfold.py` are deliberately not used for this: the former measures default production behaviour (where `graph_expand` is `false`), and the latter scores offline in numpy and never calls the API, so it structurally cannot exercise a Rust-side flag.

**Recommendation: keep `graph_expand` OFF by default** (as shipped). There is no measured gain — and, per the above, no valid measurement at all — while it adds latency plus noise-hub and displacement risk (a live probe on 2026-07-28 injected 3 neighbors at ranks 2/3/4, displacing 3 legitimate results). The flag flips to default `true` only when `graph_expand_ab.py` returns PASS.

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
| `brain/ingest/entity_extractor.py` | shared cheap NER: prompt, stoplist, clean/cap, input cap, `DURABLE_MEMORY_TYPES` |
| `brain/tools/backfill_entities.py` | historical durable-memory backfill (selection, checkpoint) |
| `brain/tests/test_fact_curator.py`, `test_backfill_entities.py`, `test_entity_extractor.py`, `test_api_client_auto_entities.py`, `test_save_memory_batch.py`, `test_seed_durable_backfill_checkpoint.py`, `test_spool_replay.py` | coverage |

## Config / constants

- `GRAPH_HOP_DECAY = 0.85` — neighbor score multiplier (`brain/rust/src/brain.rs`).
- Seed count for expansion: `min(n, 5)`.
- `MAX_ENTITIES_PER_FACT = 12`, `MAX_INPUT_CHARS = 8000`, `DURABLE_MEMORY_TYPES` (`brain/ingest/entity_extractor.py` — moved out of `backfill_entities.py`; the name is kept to avoid churn even though it now caps entities for every durable type).
- `PROGRESS_EVERY = 25`, `_DURABLE_TYPES` (JSON-quoted, for SQL), `CHECKPOINT_PATH` (`brain/tools/backfill_entities.py`).
- Backfill LLM: `OLLAMA_URL` + `OLLAMA_SUMMARIZE_MODEL` (`brain/config.py`).
- `exclude_superseded` stays default `true`; hop expansion skips superseded memories and also honours the caller's `memory_type` / `project` filters.

## Follow-ups (not built)

- **Run the widened durable backfill** — the code covers all seven durable types, but no run has happened, so only `fact` has edges today. This is the prerequisite for any meaningful `graph_expand` evaluation.
- Generate `brain/eval/gold_graph_expand.jsonl` and run `graph_expand_ab.py` (after the backfill) to produce the first reproducible A/B.
- Displacement guard for expansion (pre-registered: skip neighbors reached only through high-degree hub entities) — gated on the A/B showing displacement.
- Stoplist tuning for non-fact durable content (~15% low-value terms sampled) — needs a labelled set, not guesswork.
- Typed relations beyond `mentions`; multi-hop (`hops=2`); triplet embeddings; feedback edge reweighting.
- Clean up the 11 orphan edges left behind by deleted memories (`delete_memories` never touches `edges`), which inflate entity counts in the Linked UI.
- Flip `graph_expand` on by default — **only** after `graph_expand_ab.py` returns PASS.
