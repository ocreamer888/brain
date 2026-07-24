# Entity + Edge Graph Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop dropping LLM-extracted entity names; persist them as first-class SQLite nodes + fact→entity edges, then use 1-hop graph expansion to improve hybrid retrieval — without Neo4j/Kuzu or adopting cognee wholesale.

**Architecture:** Add `entities` + `edges` tables in the existing Rust `MetadataStore` (same idempotent `CREATE IF NOT EXISTS` style as fact-layer columns). Wire `FactDraft.entities` through `save_memory` → `POST /save` so entity upsert + edge create happen atomically with fact save. Extend `Brain::search` with optional 1-hop expansion: hybrid seed facts → shared entities → neighbor facts → merge/rerank. Stay in SQLite; no new services.

**Tech Stack:** Rust (`brain/rust` + `brain_api`), SQLite, Python (`brain/ingest`, `brain/api_client`, `brain/mcp`), existing hybrid cosine+BM25 ranker

## Global Constraints

- Branch: `feature/entity-edge-graph` (already created from `main`)
- Smallest change that works — no Neo4j, Kuzu, RDF, or cognee dependency
- Schema migrations: only `CREATE TABLE IF NOT EXISTS` + ignored `ALTER ADD COLUMN` (match `store.rs::create_tables`)
- Entity identity: deterministic `uuid5` from normalized name (lowercase, collapse whitespace) — same name → same entity node (upsert)
- Phase 1 relation type is fixed string `"mentions"` (fact → entity). No typed relation extraction yet
- `exclude_superseded` stays default `true`; hop expansion must skip superseded facts
- Do **not** change default search behavior until Task 9 opts in via flag (default `graph_expand=false`)
- Pause for human review at each **Phase** boundary before starting the next phase
- Run Rust tests from `brain/rust/`; Python tests from repo root with `pytest brain/tests/...`
- Commit only when asked by the user (or at explicit Step: Commit if user approved commits for this plan)

---

## File Map

| Action | File | Responsibility |
|---|---|---|
| Modify | `brain/rust/src/store.rs` | `entities`/`edges` DDL + CRUD + neighbor query |
| Modify | `brain/rust/src/types.rs` | Optional: small helper types if needed; keep `SearchFilter` graph fields |
| Modify | `brain/rust/src/brain.rs` | `link_entities`, graph-expand path inside `search` |
| Modify | `brain/rust/src/bin/brain_api.rs` | `SaveRequest.entities`, `SearchRequest.graph_expand`, `GET /entities` / `GET /neighbors` |
| Modify | `brain/api_client.py` | Pass `entities`, `graph_expand`; add `get_neighbors` |
| Modify | `brain/ingest/fact_curator.py` | `_save_fact` passes `draft.entities` |
| Modify | `brain/mcp/server.py` | Optional `graph_expand` on `search_brain`; add `get_neighbors_tool` |
| Create | `brain/tests/test_entity_edges.py` | Python tests for curator → API entity wiring (mocked) |
| Modify | `brain/tests/test_fact_curator.py` | Assert `_save_fact` forwards entities |
| Create | `brain/tools/backfill_entities.py` | Optional re-extract entities for existing facts (Phase D) |

---

## Data Model (locked)

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
    UNIQUE(src_memory_id, dst_entity_id, relation_type),
    FOREIGN KEY (src_memory_id) REFERENCES memories(id) ON DELETE CASCADE,
    FOREIGN KEY (dst_entity_id) REFERENCES entities(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_edges_src ON edges(src_memory_id);
CREATE INDEX IF NOT EXISTS idx_edges_dst ON edges(dst_entity_id);
```

**Normalize rule (Rust + Python must match):**
```text
name_normalized = " ".join(name.strip().split()).to_lowercase()
```
Empty / whitespace-only names are dropped.

**Entity id:**
```text
uuid5(NAMESPACE_OID, "entity:" + name_normalized)
```

---

## Phase A — Schema + Rust CRUD

> **Gate:** All Phase A Rust tests pass. Pause for review before Phase B.

### Task 1: Entities + edges tables in `create_tables`

**Files:**
- Modify: `brain/rust/src/store.rs` (`create_tables`, after `backfill_batches` block ~L126–152)
- Test: inline `#[cfg(test)]` in `brain/rust/src/store.rs`

**Interfaces:**
- Consumes: existing `MetadataStore::open_in_memory` / `create_tables`
- Produces: empty `entities` + `edges` tables on every open

- [ ] **Step 1: Write the failing test**

Add at end of `store.rs` tests module (near other fact-layer tests ~L1232):

```rust
#[test]
fn create_tables_creates_entities_and_edges() {
    let store = MetadataStore::open_in_memory().unwrap();
    let entities_ok: i64 = store
        .conn
        .query_row(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='entities'",
            [],
            |r| r.get(0),
        )
        .unwrap();
    let edges_ok: i64 = store
        .conn
        .query_row(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='edges'",
            [],
            |r| r.get(0),
        )
        .unwrap();
    assert_eq!(entities_ok, 1);
    assert_eq!(edges_ok, 1);
}
```

Note: if `conn` is private, use a public helper or query via new CRUD that returns empty — prefer making the test call `list_entities_for_memory("none")` once Task 2 exists. For Task 1 only, either temporarily `pub(crate)` the check via:

```rust
#[test]
fn create_tables_creates_entities_and_edges() {
    let store = MetadataStore::open_in_memory().unwrap();
    // Will fail until tables exist — use raw SQL through a test-only method
    assert!(store.table_exists("entities").unwrap());
    assert!(store.table_exists("edges").unwrap());
}
```

Add minimal helper:

```rust
#[cfg(test)]
fn table_exists(&self, name: &str) -> Result<bool, BrainError> {
    let n: i64 = self.conn.query_row(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?1",
        [name],
        |r| r.get(0),
    ).map_err(|e| BrainError::Database(e.to_string()))?;
    Ok(n > 0)
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd brain/rust && cargo test create_tables_creates_entities_and_edges -- --nocapture`

Expected: FAIL (table missing or helper returns false)

- [ ] **Step 3: Add DDL to `create_tables`**

Append inside the final `execute_batch` (or a new `execute_batch` right after curation/backfill tables):

```sql
CREATE TABLE IF NOT EXISTS entities (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    name_normalized TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_entities_name_norm ON entities(name_normalized);

CREATE TABLE IF NOT EXISTS edges (
    id TEXT PRIMARY KEY,
    src_memory_id TEXT NOT NULL,
    dst_entity_id TEXT NOT NULL,
    relation_type TEXT NOT NULL DEFAULT 'mentions',
    weight REAL NOT NULL DEFAULT 1.0,
    created_at TEXT NOT NULL,
    UNIQUE(src_memory_id, dst_entity_id, relation_type)
);
CREATE INDEX IF NOT EXISTS idx_edges_src ON edges(src_memory_id);
CREATE INDEX IF NOT EXISTS idx_edges_dst ON edges(dst_entity_id);
```

Do **not** add SQLite `FOREIGN KEY` enforcement unless `PRAGMA foreign_keys` is already ON in this crate (verify — if OFF, skip FKs to avoid silent no-ops; keep logical integrity in CRUD).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd brain/rust && cargo test create_tables_creates_entities_and_edges -- --nocapture`

Expected: PASS

- [ ] **Step 5: Commit** (only if user asked)

```bash
git add brain/rust/src/store.rs
git commit -m "$(cat <<'EOF'
feat(brain): add entities and edges SQLite tables

EOF
)"
```

---

### Task 2: Entity/edge CRUD + neighbor lookup

**Files:**
- Modify: `brain/rust/src/store.rs`
- Test: `brain/rust/src/store.rs` `#[cfg(test)]`

**Interfaces:**
- Consumes: tables from Task 1
- Produces:
  - `normalize_entity_name(name: &str) -> Option<String>`
  - `entity_id_for(name_normalized: &str) -> String` (uuid5)
  - `upsert_entity(&self, name: &str) -> Result<String, BrainError>` → entity id
  - `link_memory_to_entity(&self, memory_id: &str, entity_id: &str, relation_type: &str) -> Result<(), BrainError>`
  - `link_memory_entities(&self, memory_id: &str, names: &[String]) -> Result<usize, BrainError>` (upsert each + link `mentions`)
  - `entities_for_memory(&self, memory_id: &str) -> Result<Vec<(String, String)>, BrainError>` → `(entity_id, name)`
  - `neighbor_memory_ids(&self, memory_ids: &[String], exclude_superseded: bool) -> Result<Vec<String>, BrainError>` — 1-hop via shared entities, excluding input ids

- [ ] **Step 1: Write failing tests**

```rust
#[test]
fn upsert_entity_is_idempotent_by_normalized_name() {
    let store = MetadataStore::open_in_memory().unwrap();
    let a = store.upsert_entity("  Open Router ").unwrap();
    let b = store.upsert_entity("open router").unwrap();
    assert_eq!(a, b);
}

#[test]
fn link_memory_entities_and_neighbors() {
    let store = MetadataStore::open_in_memory().unwrap();
    // minimal memories rows so neighbor query can join
    for id in ["f1", "f2", "f3"] {
        let mem = Memory {
            id: id.into(),
            content: format!("fact {id}"),
            metadata: fact_metadata("ep-1"),
            embedding: None,
        };
        store.upsert_memory(&mem).unwrap();
    }
    store.link_memory_entities("f1", &["Cognee".into(), "SQLite".into()]).unwrap();
    store.link_memory_entities("f2", &["Cognee".into()]).unwrap();
    store.link_memory_entities("f3", &["Neo4j".into()]).unwrap();

    let ents = store.entities_for_memory("f1").unwrap();
    assert_eq!(ents.len(), 2);

    let neighbors = store.neighbor_memory_ids(&["f1".into()], true).unwrap();
    assert!(neighbors.contains(&"f2".into()));
    assert!(!neighbors.contains(&"f3".into()));
    assert!(!neighbors.contains(&"f1".into()));
}

#[test]
fn neighbor_memory_ids_skips_superseded() {
    let store = MetadataStore::open_in_memory().unwrap();
    for (id, superseded) in [("f1", None), ("f2", Some("f9"))] {
        let mut meta = fact_metadata("ep-1");
        meta.superseded_by = superseded.map(|s| s.into());
        store.upsert_memory(&Memory {
            id: id.into(),
            content: format!("fact {id}"),
            metadata: meta,
            embedding: None,
        }).unwrap();
    }
    store.link_memory_entities("f1", &["X".into()]).unwrap();
    store.link_memory_entities("f2", &["X".into()]).unwrap();
    let neighbors = store.neighbor_memory_ids(&["f1".into()], true).unwrap();
    assert!(!neighbors.contains(&"f2".into()));
}
```

- [ ] **Step 2: Run tests — expect FAIL**

Run: `cd brain/rust && cargo test upsert_entity_is_idempotent -- --nocapture`

Expected: compile fail / method missing

- [ ] **Step 3: Implement CRUD**

```rust
use uuid::{Uuid, uuid};

const ENTITY_NS: Uuid = uuid!("6ba7b812-9dad-11d1-80b4-00c04fd430c8"); // NAMESPACE_OID

pub fn normalize_entity_name(name: &str) -> Option<String> {
    let n = name.split_whitespace().collect::<Vec<_>>().join(" ").to_lowercase();
    if n.is_empty() { None } else { Some(n) }
}

pub fn entity_id_for(name_normalized: &str) -> String {
    Uuid::new_v5(&ENTITY_NS, format!("entity:{name_normalized}").as_bytes()).to_string()
}

impl MetadataStore {
    pub fn upsert_entity(&self, name: &str) -> Result<String, BrainError> {
        let Some(norm) = normalize_entity_name(name) else {
            return Err(BrainError::Database("empty entity name".into()));
        };
        let id = entity_id_for(&norm);
        let now = chrono::Utc::now().to_rfc3339();
        self.conn.execute(
            "INSERT INTO entities (id, name, name_normalized, created_at)
             VALUES (?1, ?2, ?3, ?4)
             ON CONFLICT(name_normalized) DO NOTHING",
            rusqlite::params![id, name.trim(), norm, now],
        ).map_err(|e| BrainError::Database(e.to_string()))?;
        // Re-read id in case concurrent first-writer used different display casing
        let id: String = self.conn.query_row(
            "SELECT id FROM entities WHERE name_normalized = ?1",
            [&norm],
            |r| r.get(0),
        ).map_err(|e| BrainError::Database(e.to_string()))?;
        Ok(id)
    }

    pub fn link_memory_to_entity(
        &self,
        memory_id: &str,
        entity_id: &str,
        relation_type: &str,
    ) -> Result<(), BrainError> {
        let edge_id = Uuid::new_v4().to_string();
        let now = chrono::Utc::now().to_rfc3339();
        self.conn.execute(
            "INSERT INTO edges (id, src_memory_id, dst_entity_id, relation_type, weight, created_at)
             VALUES (?1, ?2, ?3, ?4, 1.0, ?5)
             ON CONFLICT(src_memory_id, dst_entity_id, relation_type) DO NOTHING",
            rusqlite::params![edge_id, memory_id, entity_id, relation_type, now],
        ).map_err(|e| BrainError::Database(e.to_string()))?;
        Ok(())
    }

    pub fn link_memory_entities(
        &self,
        memory_id: &str,
        names: &[String],
    ) -> Result<usize, BrainError> {
        let mut n = 0usize;
        for name in names {
            if normalize_entity_name(name).is_none() { continue; }
            let eid = self.upsert_entity(name)?;
            self.link_memory_to_entity(memory_id, &eid, "mentions")?;
            n += 1;
        }
        Ok(n)
    }

    pub fn entities_for_memory(
        &self,
        memory_id: &str,
    ) -> Result<Vec<(String, String)>, BrainError> {
        let mut stmt = self.conn.prepare(
            "SELECT e.id, e.name FROM entities e
             JOIN edges x ON x.dst_entity_id = e.id
             WHERE x.src_memory_id = ?1
             ORDER BY e.name_normalized",
        ).map_err(|e| BrainError::Database(e.to_string()))?;
        let rows = stmt.query_map([memory_id], |r| Ok((r.get(0)?, r.get(1)?)))
            .map_err(|e| BrainError::Database(e.to_string()))?;
        rows.collect::<Result<Vec<_>, _>>().map_err(|e| BrainError::Database(e.to_string()))
    }

    pub fn neighbor_memory_ids(
        &self,
        memory_ids: &[String],
        exclude_superseded: bool,
    ) -> Result<Vec<String>, BrainError> {
        if memory_ids.is_empty() {
            return Ok(vec![]);
        }
        let placeholders = memory_ids.iter().map(|_| "?").collect::<Vec<_>>().join(",");
        let superseded_clause = if exclude_superseded {
            "AND (m.superseded_by IS NULL OR m.superseded_by = '')"
        } else {
            ""
        };
        let sql = format!(
            "SELECT DISTINCT e2.src_memory_id
             FROM edges e1
             JOIN edges e2 ON e1.dst_entity_id = e2.dst_entity_id
             JOIN memories m ON m.id = e2.src_memory_id
             WHERE e1.src_memory_id IN ({placeholders})
               AND e2.src_memory_id NOT IN ({placeholders})
               {superseded_clause}"
        );
        let mut stmt = self.conn.prepare(&sql)
            .map_err(|e| BrainError::Database(e.to_string()))?;
        let params: Vec<&dyn rusqlite::ToSql> = memory_ids.iter()
            .chain(memory_ids.iter())
            .map(|s| s as &dyn rusqlite::ToSql)
            .collect();
        let rows = stmt.query_map(params.as_slice(), |r| r.get::<_, String>(0))
            .map_err(|e| BrainError::Database(e.to_string()))?;
        rows.collect::<Result<Vec<_>, _>>().map_err(|e| BrainError::Database(e.to_string()))
    }
}
```

Confirm `uuid` + `chrono` already in `brain/rust/Cargo.toml` (they are used elsewhere). Use existing import style.

- [ ] **Step 4: Run tests — expect PASS**

Run: `cd brain/rust && cargo test upsert_entity_is_idempotent link_memory_entities_and_neighbors neighbor_memory_ids_skips_superseded -- --nocapture`

Expected: PASS

- [ ] **Step 5: Commit** (if user asked)

```bash
git add brain/rust/src/store.rs
git commit -m "$(cat <<'EOF'
feat(brain): CRUD for entities, edges, and 1-hop neighbors

EOF
)"
```

---

### Task 3: `Brain::link_entities` wrapper

**Files:**
- Modify: `brain/rust/src/brain.rs`
- Test: `brain/rust/src/brain.rs` `#[cfg(test)]` or store tests already cover — add one Brain-level smoke test if easy

**Interfaces:**
- Consumes: `MetadataStore::link_memory_entities`
- Produces: `Brain::link_entities(&self, memory_id: &str, names: &[String]) -> Result<usize, BrainError>`

- [ ] **Step 1: Add method**

```rust
pub fn link_entities(
    &self,
    memory_id: &str,
    names: &[String],
) -> Result<usize, BrainError> {
    self.store.link_memory_entities(memory_id, names)
}
```

- [ ] **Step 2: Run full Rust suite smoke**

Run: `cd brain/rust && cargo test --lib 2>&1 | tail -30`

Expected: all existing tests still PASS

- [ ] **Step 3: Commit** (if user asked)

---

## Phase B — Wire ingest + API (stop dropping entities)

> **Gate:** Saving a fact with `entities: ["Foo"]` persists entity + edge. Pause for review before Phase C.

### Task 4: Extend `POST /save` with `entities`

**Files:**
- Modify: `brain/rust/src/bin/brain_api.rs` (`SaveRequest`, `save`, optionally `save_batch`)
- Test: add integration-style unit test if present pattern exists; otherwise manual curl after rebuild + Rust store tests already cover link path

**Interfaces:**
- Consumes: `Brain::link_entities`, existing save path
- Produces: `SaveRequest.entities: Option<Vec<String>>` — after successful save, call `link_entities`

- [ ] **Step 1: Extend `SaveRequest`**

```rust
/// Optional entity names to link (fact → entity "mentions" edges).
#[serde(default)]
entities: Option<Vec<String>>,
```

- [ ] **Step 2: After successful `brain.save(...)` in `save` handler, link**

Find where `id` is returned (~L476–515). After save succeeds:

```rust
if let Some(ref names) = req.entities {
    if !names.is_empty() {
        if let Err(e) = state.brain.link_entities(&id, names) {
            // Log but do not fail the save — fact is already persisted.
            eprintln!("link_entities failed for {id}: {e}");
        }
    }
}
```

Prefer: if linking fails, still return 200 with id (fact > edges). Document this in a code comment. Same for `save_batch` per item when `item.entities` present.

- [ ] **Step 3: Rebuild API binary (dev check)**

Run: `cd brain/rust && cargo build --bin brain_api`

Expected: success

- [ ] **Step 4: Commit** (if user asked)

```bash
git add brain/rust/src/bin/brain_api.rs brain/rust/src/brain.rs
git commit -m "$(cat <<'EOF'
feat(brain_api): accept entities on /save and link mentions edges

EOF
)"
```

---

### Task 5: Python `api_client.save_memory` + curator wiring

**Files:**
- Modify: `brain/api_client.py` (`save_memory`, and `save_memory_with_status` if it duplicates payload)
- Modify: `brain/ingest/fact_curator.py` (`_save_fact`)
- Modify: `brain/tests/test_fact_curator.py`
- Create: `brain/tests/test_entity_edges.py` (optional thin client test)

**Interfaces:**
- Consumes: `SaveRequest.entities`
- Produces: `_save_fact` forwards `draft.entities` (non-empty only)

- [ ] **Step 1: Write failing curator test**

In `brain/tests/test_fact_curator.py`:

```python
def test_save_fact_forwards_entities(monkeypatch):
    from brain.ingest.fact_curator import _save_fact
    from brain.ingest.fact_extractor import FactDraft

    captured = {}

    def fake_save(**kwargs):
        captured.update(kwargs)
        return "fact-id-1"

    monkeypatch.setattr("brain.ingest.fact_curator.api_client.save_memory", fake_save)

    draft = FactDraft(
        content="Chose SQLite for local brain graph",
        salience=0.9,
        event_time=None,
        entities=["SQLite", "brain"],
        fact_type="decision",
    )
    _save_fact(draft, project="brain", parent_id="ep-1", session_id=None)
    assert captured.get("entities") == ["SQLite", "brain"]
```

- [ ] **Step 2: Run — expect FAIL**

Run: `pytest brain/tests/test_fact_curator.py::test_save_fact_forwards_entities -v`

Expected: FAIL (`entities` missing from kwargs / TypeError)

- [ ] **Step 3: Implement**

`brain/api_client.py` — add param + payload:

```python
def save_memory(
    ...
    derived_from: str | None = None,
    entities: list[str] | None = None,
) -> str:
    ...
    if entities:
        payload["entities"] = entities
    return _request("POST", "/save", payload).get("id", "")
```

Mirror in `save_memory_with_status` if it builds its own payload.

`brain/ingest/fact_curator.py`:

```python
return api_client.save_memory(
    ...
    derived_from=draft.derived_from or None,
    entities=draft.entities or None,
)
```

- [ ] **Step 4: Run — expect PASS**

Run: `pytest brain/tests/test_fact_curator.py::test_save_fact_forwards_entities brain/tests/test_fact_curator.py::test_save_fact_uses_source_event_time_when_llm_null -v`

Expected: PASS

- [ ] **Step 5: Commit** (if user asked)

```bash
git add brain/api_client.py brain/ingest/fact_curator.py brain/tests/test_fact_curator.py
git commit -m "$(cat <<'EOF'
feat(ingest): persist FactDraft.entities via /save

EOF
)"
```

---

### Task 6: Read APIs — `/entities` + `/neighbors`

**Files:**
- Modify: `brain/rust/src/bin/brain_api.rs`
- Modify: `brain/api_client.py`
- Modify: `brain/mcp/server.py` (thin wrappers)

**Interfaces:**
- Produces:
  - `GET /entities?memory_id=...` → `{entities: [{id, name}]}`
  - `GET /neighbors?memory_id=...&exclude_superseded=true` → `{ids: [...]}`
  - Python: `get_entities(memory_id)`, `get_neighbors(memory_id, exclude_superseded=True)`
  - MCP: `get_neighbors_tool(memory_id: str)`

- [ ] **Step 1: Add routes + handlers** in `brain_api.rs` next to `/get-episode`

```rust
.route("/entities", get(entities_handler))
.route("/neighbors", get(neighbors_handler))
```

Handlers call `state.brain.store` methods (add thin `Brain` wrappers `entities_for_memory` / `neighbor_memory_ids` if `store` is private).

- [ ] **Step 2: Wire Python + MCP**

```python
def get_entities(memory_id: str) -> list[dict]:
    return _request("GET", f"/entities?memory_id={memory_id}").get("entities", [])

def get_neighbors(memory_id: str, exclude_superseded: bool = True) -> list[str]:
    flag = "true" if exclude_superseded else "false"
    return _request(
        "GET", f"/neighbors?memory_id={memory_id}&exclude_superseded={flag}"
    ).get("ids", [])
```

MCP tool returns neighbor IDs (agent can then `get_observations_tool`).

- [ ] **Step 3: `cargo build --bin brain_api` + quick unit sanity**

- [ ] **Step 4: Commit** (if user asked)

---

## Phase C — Graph-aware retrieval

> **Gate:** With `graph_expand=true`, search returns seed + 1-hop neighbors; default path unchanged. Pause for review before Phase D.

### Task 7: `SearchFilter.graph_expand` + expand in `Brain::search`

**Files:**
- Modify: `brain/rust/src/types.rs` (`SearchFilter`)
- Modify: `brain/rust/src/brain.rs` (`search`)
- Test: `brain/rust/src/brain.rs` or `store.rs` + brain integration test with `MockEmbedder`

**Interfaces:**
- Consumes: `neighbor_memory_ids`
- Produces: when `graph_expand == true`, after building the initial ranked candidate list (before final truncate to `n`), pull 1-hop neighbors of the top `min(n, seed_k)` results (default `seed_k=5`), fetch those memories, score them with a **hop penalty** so pure vector hits still win ties, merge, re-sort, take `n`

**Scoring rule (locked):**
```text
neighbor_score = seed_score * 0.85 * edge_weight_avg
```
Use `0.85` constant for v1 (`GRAPH_HOP_DECAY`). Cap neighbor injection at `n` extra candidates before final cut.

- [ ] **Step 1: Extend `SearchFilter`**

```rust
pub struct SearchFilter {
    pub memory_type: Option<MemoryType>,
    pub project: Option<String>,
    pub exclude_superseded: bool,
    pub alpha: Option<f32>,
    pub graph_expand: bool, // default false
}

impl Default for SearchFilter {
    fn default() -> Self {
        Self {
            memory_type: None,
            project: None,
            exclude_superseded: true,
            alpha: None,
            graph_expand: false,
        }
    }
}
```

- [ ] **Step 2: Write failing Brain test**

Use in-memory Brain + MockEmbedder pattern already in `brain.rs` tests. Save three facts with embeddings that make f1 top hit; link f1↔f2 via entity; set `graph_expand=true`; assert f2 appears in top results even if cosine alone would bury it.

- [ ] **Step 3: Implement expansion block** near end of `search`, before returning truncated vec:

```rust
if filter.as_ref().map(|f| f.graph_expand).unwrap_or(false) {
    let seed_ids: Vec<String> = ranked.iter().take(n.min(5)).map(|r| r.id.clone()).collect();
    let neighbor_ids = self.store.neighbor_memory_ids(&seed_ids, exclude_superseded)?;
    // fetch, score with hop decay from best seed that shares an entity, merge, re-sort
}
```

Keep helper private: `fn expand_graph_neighbors(...)`.

- [ ] **Step 4: Run tests**

Run: `cd brain/rust && cargo test graph_expand -- --nocapture && cargo test --lib 2>&1 | tail -40`

Expected: new test PASS; no regressions

- [ ] **Step 5: Commit** (if user asked)

---

### Task 8: Expose `graph_expand` on API + Python + MCP

**Files:**
- Modify: `brain/rust/src/bin/brain_api.rs` (`SearchRequest`)
- Modify: `brain/api_client.py` (`search`, `search_index` optional)
- Modify: `brain/mcp/server.py` (`search_brain`)

**Interfaces:**
- `SearchRequest.graph_expand: bool` default `false` via `#[serde(default)]`
- `api_client.search(..., graph_expand: bool = False)`
- `search_brain(..., graph_expand: bool = False)`

- [ ] **Step 1: Wire bool through all three layers**

- [ ] **Step 2: Manual live check** (after restarting `brain_api` / launchd):

```bash
curl -s http://127.0.0.1:8787/health
# save two facts with shared entity, then:
curl -s -X POST http://127.0.0.1:8787/search \
  -H 'content-type: application/json' \
  -d '{"query":"...","n":5,"graph_expand":true}'
```

- [ ] **Step 3: Commit** (if user asked)

---

## Phase D — Measure + optional backfill

> **Gate:** Eval numbers recorded. Decide keep / tweak / roll back hop decay.

### Task 9: Eval harness pass with `graph_expand`

**Files:**
- Modify: `brain/tools/retrieval_eval_kfold.py` **or** `brain/tools/mcp_eval.py` — add a mode/flag `--graph-expand` that passes `graph_expand=true` to search
- Do **not** make graph expand the default for production MCP yet

- [ ] **Step 1: Run baseline** (graph_expand off) on existing gold / kfold set; record P@1 / MRR

- [ ] **Step 2: Run with `--graph-expand`; compare**

- [ ] **Step 3: Write short note** in plan checkbox or `docs/` only if user wants — otherwise paste numbers in chat

Keep / ship if P@1 does not drop; if drop > 2pp, tune `GRAPH_HOP_DECAY` or seed_k before enabling wider use.

---

### Task 10 (optional): Backfill entities for old facts

**Files:**
- Create: `brain/tools/backfill_entities.py`

**Behavior:**
- Iterate active facts (`type=fact`, `superseded_by IS NULL`) that have **zero** edges
- Re-run `extract_facts` on parent episode **or** a cheap LLM “list entities in this fact” prompt (prefer small dedicated prompt — cheaper than full extract)
- Call `api_client` link path (may need `POST /save` patch-only endpoint — simpler: add `POST /link-entities` `{memory_id, entities}`)

Only implement if Phase C eval looks good and user wants historical coverage. Forward-only (new facts) is enough for first ship.

---

## Out of scope (follow-up plans)

| Idea | Why later |
|---|---|
| Feedback edge reweight (`memify`-style) | Needs edges + feedback join; separate plan |
| Triplet embeddings | Needs edges + embed pipeline change |
| Typed relations beyond `mentions` | Needs extractor schema change |
| Multi-hop (`hops=2`) | YAGNI until 1-hop proves value |
| Neo4j / Kuzu / cognee dependency | Explicitly rejected |
| Changing default `search_brain` to `graph_expand=true` | Only after Task 9 numbers |

---

## Self-review checklist

1. **Spec coverage:** Persist entities ✓ (A/B), stop drop ✓ (B), graph retrieval ✓ (C), measure ✓ (D), skip wholesale cognee ✓
2. **Placeholders:** none intentional — code blocks are concrete
3. **Type consistency:** `entities: Vec<String>` / `list[str]` throughout; `graph_expand: bool` default false; relation `"mentions"`; normalize rule shared
4. **DB path footgun:** entity writes go through HTTP `/save` → launchd `brain_api` DB — do **not** write entities via curator’s direct `~/.brain/brain.db` SQLite path

---

## Execution Handoff

Plan saved to `docs/superpowers/plans/2026-07-22-entity-edge-graph.md`.

**Two execution options:**

1. **Subagent-Driven (recommended)** — fresh subagent per task, review between tasks  
2. **Inline Execution** — this session, executing-plans with checkpoints  

**Also:** pause at Phase A / B / C / D boundaries for your OK (your preference).

Which approach?
