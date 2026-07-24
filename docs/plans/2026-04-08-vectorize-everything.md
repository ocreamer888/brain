# Vectorize Everything Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make SQLite the single source of truth for both memory metadata and embeddings, eliminate the separate `brain_index.bin` file, and ingest raw session transcripts as chunked conversation memories so nothing is ever lost.

**Architecture:** Add an `embedding BLOB` column to the `memories` table. `Brain::open()` rebuilds the in-memory `VectorIndex` from SQLite on startup instead of loading a binary file. `save_memory()` writes the embedding to the SQL row atomically — no separate index file save per write. A one-time backfill binary embeds all existing rows that have `NULL` embedding. A new Python tool chunks raw session transcripts (user+assistant exchanges) and ingests them via `/save-batch`.

**Tech Stack:** Rust (rusqlite, bincode removed from hot path), Python 3, existing ONNX embedder, existing `/save-batch` API endpoint.

---

## Task 1: Add `embedding BLOB` column and update `store.rs`

**Files:**
- Modify: `brain/rust/src/store.rs`
- Test: `brain/rust/src/store.rs` (existing `#[cfg(test)]` block)

**What changes:**
- `create_tables()`: add `embedding BLOB` column to `memories` table via `ALTER TABLE ADD COLUMN IF NOT EXISTS` (safe, idempotent, existing rows get `NULL`)
- `upsert_memory()`: include `embedding` in INSERT and ON CONFLICT UPDATE; serialize `Vec<f32>` as raw bytes (`bytemuck` or manual `f32` → `u8` cast)
- `get_memory()` and `get_all_documents()`: read `embedding` column back; deserialize bytes → `Vec<f32>`; populate `memory.embedding`
- New method `store.get_embeddings_for_index() -> Vec<(String, Vec<f32>)>`: returns all rows where `embedding IS NOT NULL` — used by `Brain::open()` to build the index

**Step 1: Write the failing tests**

Add to the `#[cfg(test)]` block in `brain/rust/src/store.rs`:

```rust
#[test]
fn upsert_stores_and_retrieves_embedding() {
    let store = MetadataStore::open_in_memory().unwrap();
    let emb: Vec<f32> = vec![0.1, 0.2, 0.3];
    let memory = Memory {
        id: "emb-1".into(),
        content: "test".into(),
        metadata: test_metadata(),
        embedding: Some(emb.clone()),
    };
    store.upsert_memory(&memory).unwrap();
    let fetched = store.get_memory("emb-1").unwrap().unwrap();
    assert_eq!(fetched.embedding, Some(emb));
}

#[test]
fn upsert_without_embedding_stores_null() {
    let store = MetadataStore::open_in_memory().unwrap();
    let memory = Memory {
        id: "no-emb".into(),
        content: "test".into(),
        metadata: test_metadata(),
        embedding: None,
    };
    store.upsert_memory(&memory).unwrap();
    let fetched = store.get_memory("no-emb").unwrap().unwrap();
    assert!(fetched.embedding.is_none());
}

#[test]
fn get_embeddings_for_index_returns_only_non_null() {
    let store = MetadataStore::open_in_memory().unwrap();
    let with_emb = Memory {
        id: "a".into(), content: "x".into(), metadata: test_metadata(),
        embedding: Some(vec![1.0, 0.0]),
    };
    let without_emb = Memory {
        id: "b".into(), content: "y".into(), metadata: test_metadata(),
        embedding: None,
    };
    store.upsert_memory(&with_emb).unwrap();
    store.upsert_memory(&without_emb).unwrap();
    let pairs = store.get_embeddings_for_index().unwrap();
    assert_eq!(pairs.len(), 1);
    assert_eq!(pairs[0].0, "a");
}
```

**Step 2: Run tests — expect FAIL**

```bash
cd brain/rust
cargo test store::tests::upsert_stores_and_retrieves_embedding 2>&1 | tail -5
```

Expected: compile error — `get_embeddings_for_index` not yet defined; `upsert_memory` ignores embedding.

**Step 3: Implement**

In `create_tables()`, after the existing `CREATE TABLE IF NOT EXISTS memories (...)`, add:

```rust
// Idempotent: no-op if column already exists
let _ = self.conn.execute_batch(
    "ALTER TABLE memories ADD COLUMN embedding BLOB;"
);
```

Embedding serialization helper (add as private functions at bottom of `store.rs`):

```rust
fn embedding_to_bytes(emb: &[f32]) -> Vec<u8> {
    emb.iter().flat_map(|f| f.to_le_bytes()).collect()
}

fn bytes_to_embedding(bytes: &[u8]) -> Vec<f32> {
    bytes.chunks_exact(4)
        .map(|b| f32::from_le_bytes([b[0], b[1], b[2], b[3]]))
        .collect()
}
```

Update `upsert_memory()` signature and SQL:

```rust
pub fn upsert_memory(&self, memory: &Memory) -> Result<(), BrainError> {
    let meta = &memory.metadata;
    let emb_bytes: Option<Vec<u8>> = memory.embedding.as_deref().map(embedding_to_bytes);
    self.conn.execute(
        "INSERT INTO memories
            (id, content, type, project, tags, timestamp, source, session_id,
             importance, file_path, thread_id, title, embedding)
         VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11,?12,?13)
         ON CONFLICT(id) DO UPDATE SET
            content=excluded.content, type=excluded.type,
            project=excluded.project, tags=excluded.tags,
            timestamp=excluded.timestamp, source=excluded.source,
            session_id=excluded.session_id, importance=excluded.importance,
            file_path=excluded.file_path, thread_id=excluded.thread_id,
            title=excluded.title,
            embedding=COALESCE(excluded.embedding, memories.embedding)",
        params![
            memory.id, memory.content,
            serde_json::to_string(&meta.memory_type).map_err(|e| BrainError::Database(e.to_string()))?,
            meta.project, meta.tags, meta.timestamp.to_rfc3339(),
            serde_json::to_string(&meta.source).map_err(|e| BrainError::Database(e.to_string()))?,
            meta.session_id, meta.importance,
            meta.file_path, meta.thread_id, meta.title,
            emb_bytes,
        ],
    ).map_err(|e| BrainError::Database(e.to_string()))?;
    Ok(())
}
```

> Note: `COALESCE(excluded.embedding, memories.embedding)` means an upsert without an embedding will NOT erase an existing embedding — idempotent and safe.

Update `get_memory()` to read column 12 (`embedding BLOB`):

```rust
// In the SELECT: add `embedding` as column 12
// In the row closure: add row.get::<_, Option<Vec<u8>>>(12)?
// When constructing Memory:
embedding: emb_bytes.map(|b| bytes_to_embedding(&b)),
```

Update `get_all_documents()` identically (add column 12).

Add new method:

```rust
pub fn get_embeddings_for_index(&self) -> Result<Vec<(String, Vec<f32>)>, BrainError> {
    let mut stmt = self.conn.prepare(
        "SELECT id, embedding FROM memories WHERE embedding IS NOT NULL"
    ).map_err(|e| BrainError::Database(e.to_string()))?;
    let rows = stmt.query_map([], |row| {
        Ok((row.get::<_, String>(0)?, row.get::<_, Vec<u8>>(1)?))
    }).map_err(|e| BrainError::Database(e.to_string()))?;
    let mut out = Vec::new();
    for row in rows {
        let (id, bytes) = row.map_err(|e| BrainError::Database(e.to_string()))?;
        out.push((id, bytes_to_embedding(&bytes)));
    }
    Ok(out)
}
```

**Step 4: Run tests — expect PASS**

```bash
cd brain/rust
cargo test store::tests 2>&1 | tail -10
```

Expected: all store tests pass including the 3 new ones.

**Step 5: Commit**

```bash
git add brain/rust/src/store.rs
git commit -m "feat(store): add embedding BLOB column to memories table"
```

---

## Task 2: Update `Brain::open()` to load index from SQLite

**Files:**
- Modify: `brain/rust/src/brain.rs`
- Test: `brain/rust/src/brain.rs` (existing `#[cfg(test)]` block)

**What changes:**
- `Brain::open()`: after opening the store, call `store.get_embeddings_for_index()` and populate `VectorIndex` from those rows. Remove loading from `brain_index.bin` entirely.
- `BrainConfig`: keep `index_path` field for now but it becomes unused (will remove in Task 3).

**Step 1: Write the failing test**

```rust
#[test]
fn open_brain_rebuilds_index_from_sqlite() {
    // Save a memory directly to store (with embedding), then re-open Brain
    // and verify it can find the memory via search.
    let dir = tempfile::TempDir::new().unwrap();
    let db_path = dir.path().join("brain.db").to_string_lossy().to_string();

    {
        let config = BrainConfig { db_path: db_path.clone(), index_path: None, embedding_dims: 16, reflect_every_n: 20 };
        let brain = Brain::open(config, Box::new(MockEmbedder::new(16))).unwrap();
        brain.save_memory("rebuild from sql test", MemoryType::Solution, &[], "p", None, MemorySource::ClaudeCodeSession).unwrap();
    }

    // Re-open — index must be rebuilt from SQLite, no binary file
    let config2 = BrainConfig { db_path, index_path: None, embedding_dims: 16, reflect_every_n: 20 };
    let brain2 = Brain::open(config2, Box::new(MockEmbedder::new(16))).unwrap();
    let results = brain2.search("rebuild from sql test", 1, None).unwrap();
    assert_eq!(results.len(), 1);
}
```

**Step 2: Run test — expect FAIL**

```bash
cd brain/rust
cargo test brain::tests::open_brain_rebuilds_index_from_sqlite 2>&1 | tail -5
```

Expected: FAIL — index is empty after re-open (currently loaded from missing binary file).

**Step 3: Implement**

Replace the index-loading block in `Brain::open()`:

```rust
// OLD:
let index = if let Some(ref path) = config.index_path {
    if Path::new(path).exists() {
        VectorIndex::load(path, config.embedding_dims)?
    } else {
        VectorIndex::new(config.embedding_dims)
    }
} else {
    VectorIndex::new(config.embedding_dims)
};

// NEW:
let mut index = VectorIndex::new(config.embedding_dims);
let pairs = store.get_embeddings_for_index()?;
for (id, emb) in pairs {
    index.insert(&id, &emb);
}
eprintln!("[brain] loaded {} embeddings from SQLite", index.len());
```

**Step 4: Run tests — expect PASS**

```bash
cd brain/rust
cargo test brain::tests 2>&1 | tail -10
```

**Step 5: Commit**

```bash
git add brain/rust/src/brain.rs
git commit -m "feat(brain): rebuild vector index from SQLite on open — no binary file needed"
```

---

## Task 3: Remove per-save index file write from `save_memory()`

**Files:**
- Modify: `brain/rust/src/brain.rs`
- Modify: `brain/rust/src/brain.rs` (`BrainConfig` — remove `index_path`)

**What changes:**
- `save_memory()`: remove the block that calls `self.index.lock()?.save(path)` after every write. The embedding is now in SQLite — no separate file needed.
- `BrainConfig`: remove `index_path` field. Update all usages (brain_api.rs, brain_migrate.rs, brain_query.rs, config.rs).

**Step 1: Check all usages of `index_path`**

```bash
cd brain/rust
grep -rn "index_path\|BRAIN_INDEX_PATH\|brain_index.bin" src/ 2>&1
```

Note every file listed — each needs updating.

**Step 2: Write test confirming no file is written**

```rust
#[test]
fn save_memory_does_not_write_index_file() {
    let dir = tempfile::TempDir::new().unwrap();
    let db_path = dir.path().join("brain.db").to_string_lossy().to_string();
    let index_file = dir.path().join("brain_index.bin");

    let config = BrainConfig { db_path, index_path: None, embedding_dims: 16, reflect_every_n: 20 };
    let brain = Brain::open(config, Box::new(MockEmbedder::new(16))).unwrap();
    brain.save_memory("test", MemoryType::Solution, &[], "p", None, MemorySource::ClaudeCodeSession).unwrap();

    assert!(!index_file.exists(), "index file should not be written");
}
```

**Step 3: Run — expect PASS already** (index_path is None in test_brain())

This test documents the intended behavior.

**Step 4: Remove `index_path` from `BrainConfig` and the save block**

In `brain.rs`:
- Remove `index_path: Option<String>` from `BrainConfig` struct and `Default` impl
- Remove `index_path: Option<String>` field from `Brain` struct
- Remove the `if let Some(ref path) = self.index_path { ... index.save(path) }` block in `save_memory()`

In `brain/rust/src/config.rs` (check what `brain_config_from_env()` returns):

```bash
cat brain/rust/src/config.rs
```

Remove `BRAIN_INDEX_PATH` env var reading from `brain_config_from_env()`.

Update `brain/rust/src/bin/brain_api.rs`: remove `BRAIN_INDEX_PATH` from `open_brain()`.

Update `brain/rust/src/bin/brain_migrate.rs`: keep the index path for backward compat during migration, but after migration completes it's unused. Change it to write embeddings to SQLite during migrate (see Task 6).

Update `brain/rust/src/bin/brain_query.rs`: remove `--index` flag, rebuild from SQLite.

**Step 5: Run all tests**

```bash
cd brain/rust
cargo test 2>&1 | tail -20
```

Expected: all pass.

**Step 6: Commit**

```bash
git add brain/rust/src/brain.rs brain/rust/src/bin/brain_api.rs brain/rust/src/bin/brain_query.rs brain/rust/src/config.rs
git commit -m "feat(brain): remove per-save index file write — embeddings are in SQLite"
```

---

## Task 4: Backfill binary — embed all existing rows with `NULL` embedding

**Files:**
- Create: `brain/rust/src/bin/brain_backfill_embeddings.rs`
- Create: test inline in the binary (or via integration test)

**What it does:**
1. Opens SQLite via `MetadataStore`
2. Queries `SELECT id, content FROM memories WHERE embedding IS NULL`
3. For each row: embeds content via ONNX embedder, calls new `store.update_embedding(id, &emb)`
4. Also inserts into in-memory index (for the running session)
5. Reports progress every 100 rows
6. Idempotent: already-embedded rows are untouched

**New `store` method needed:**

Add to `store.rs`:

```rust
pub fn get_unembedded_ids_and_content(&self) -> Result<Vec<(String, String)>, BrainError> {
    let mut stmt = self.conn.prepare(
        "SELECT id, content FROM memories WHERE embedding IS NULL"
    ).map_err(|e| BrainError::Database(e.to_string()))?;
    let rows = stmt.query_map([], |row| {
        Ok((row.get::<_, String>(0)?, row.get::<_, String>(1)?))
    }).map_err(|e| BrainError::Database(e.to_string()))?;
    rows.map(|r| r.map_err(|e| BrainError::Database(e.to_string()))).collect()
}

pub fn update_embedding(&self, id: &str, emb: &[f32]) -> Result<(), BrainError> {
    let bytes = embedding_to_bytes(emb);
    self.conn.execute(
        "UPDATE memories SET embedding = ?1 WHERE id = ?2",
        params![bytes, id],
    ).map_err(|e| BrainError::Database(e.to_string()))?;
    Ok(())
}
```

**Step 1: Write tests for new store methods**

```rust
#[test]
fn get_unembedded_returns_only_null_rows() {
    let store = MetadataStore::open_in_memory().unwrap();
    let m1 = Memory { id: "a".into(), content: "c1".into(), metadata: test_metadata(), embedding: Some(vec![1.0]) };
    let m2 = Memory { id: "b".into(), content: "c2".into(), metadata: test_metadata(), embedding: None };
    store.upsert_memory(&m1).unwrap();
    store.upsert_memory(&m2).unwrap();
    let unembedded = store.get_unembedded_ids_and_content().unwrap();
    assert_eq!(unembedded.len(), 1);
    assert_eq!(unembedded[0].0, "b");
}

#[test]
fn update_embedding_fills_null_row() {
    let store = MetadataStore::open_in_memory().unwrap();
    let m = Memory { id: "x".into(), content: "c".into(), metadata: test_metadata(), embedding: None };
    store.upsert_memory(&m).unwrap();
    store.update_embedding("x", &[0.5, 0.5]).unwrap();
    let fetched = store.get_memory("x").unwrap().unwrap();
    assert_eq!(fetched.embedding, Some(vec![0.5, 0.5]));
}
```

**Step 2: Run — expect FAIL**

```bash
cd brain/rust && cargo test store::tests::get_unembedded 2>&1 | tail -5
```

**Step 3: Implement store methods** (add to `store.rs`), run tests — expect PASS.

**Step 4: Write the binary**

```rust
// brain/rust/src/bin/brain_backfill_embeddings.rs

use brain::embedder::embedder_from_env;
use brain::store::MetadataStore;
use brain::BrainError;

const BATCH: usize = 50;

fn main() -> Result<(), BrainError> {
    let db_path = std::env::var("BRAIN_DB_PATH").unwrap_or_else(|_| "brain.db".into());
    eprintln!("[backfill] db: {db_path}");

    let store = MetadataStore::open(&db_path)?;
    let embedder = embedder_from_env("[backfill]")?;

    let rows = store.get_unembedded_ids_and_content()?;
    let total = rows.len();
    eprintln!("[backfill] {total} rows need embeddings");

    if total == 0 {
        eprintln!("[backfill] nothing to do ✓");
        return Ok(());
    }

    let mut done = 0;
    for (id, content) in &rows {
        let emb = embedder.embed(content)?;
        store.update_embedding(id, &emb)?;
        done += 1;
        if done % BATCH == 0 {
            eprintln!("[backfill] {done}/{total}…");
        }
    }

    eprintln!("[backfill] done — {done} embeddings written ✓");
    Ok(())
}
```

**Step 5: Build and run against live DB**

```bash
source ~/.zshrc
cd brain/rust
cargo build --release --bin brain_backfill_embeddings 2>&1 | tail -5
./target/release/brain_backfill_embeddings 2>&1
```

Expected output:
```
[backfill] db: /Users/.../brain.db
[backfill] N rows need embeddings
[backfill] 50/N…
[backfill] done — N embeddings written ✓
```

**Step 6: Verify**

```bash
sqlite3 "$BRAIN_DB_PATH" "SELECT COUNT(*) FROM memories WHERE embedding IS NULL;"
```

Expected: `0`

**Step 7: Commit**

```bash
git add brain/rust/src/store.rs brain/rust/src/bin/brain_backfill_embeddings.rs
git commit -m "feat(backfill): embed all existing memories into SQLite embedding column"
```

---

## Task 5: Session transcript chunker + ingestion

**Files:**
- Create: `brain/tools/ingest_session_chunks.py`
- Test: `brain/tests/test_ingest_session_chunks.py`

**What it does:**
1. Reads a session JSON file from `sessions_export/`
2. Filters messages to only `type: user` and `type: assistant`
3. Groups into exchanges: each exchange = one consecutive user turn + the following assistant turn
4. Skips exchanges where `message.content` is empty or too short (< 50 chars combined)
5. Formats each chunk: `"User: {user_text}\n\nAssistant: {assistant_text}"`
6. Sends chunks to `/save-batch` with `memory_type=conversation`, `source=claude_code_session`, `session_id` from the file
7. Checkpoints processed files to avoid re-ingesting

**Step 1: Write tests first**

```python
# brain/tests/test_ingest_session_chunks.py

import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from brain.tools.ingest_session_chunks import chunk_session

def make_session(pairs):
    messages = []
    for user_text, asst_text in pairs:
        messages.append({"type": "user", "message": {"role": "user", "content": user_text}})
        messages.append({"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": asst_text}]}})
    return {"session_id": "test-session", "project": "test", "messages": messages}

def test_chunk_session_pairs_user_assistant():
    session = make_session([("hello how are you today?", "I am doing well, thank you for asking!")])
    chunks = chunk_session(session)
    assert len(chunks) == 1
    assert "User:" in chunks[0]["content"]
    assert "Assistant:" in chunks[0]["content"]
    assert chunks[0]["session_id"] == "test-session"

def test_chunk_session_skips_short_exchanges():
    session = make_session([("hi", "ok")])  # too short
    chunks = chunk_session(session)
    assert len(chunks) == 0

def test_chunk_session_filters_non_user_assistant():
    session = {
        "session_id": "s1", "project": "p",
        "messages": [
            {"type": "system", "message": {"content": "system msg"}},
            {"type": "file-history-snapshot", "snapshot": {}},
            {"type": "user", "message": {"role": "user", "content": "what is rust?"}},
            {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "Rust is a systems programming language focused on safety and performance."}]}},
        ]
    }
    chunks = chunk_session(session)
    assert len(chunks) == 1

def test_chunk_session_multiple_pairs():
    session = make_session([
        ("what is rust?", "Rust is a systems language."),
        ("what is python?", "Python is a high-level scripting language."),
    ])
    chunks = chunk_session(session)
    assert len(chunks) == 2
```

**Step 2: Run tests — expect FAIL**

```bash
python3 -m pytest brain/tests/test_ingest_session_chunks.py -v 2>&1 | tail -10
```

Expected: ImportError — module not yet created.

**Step 3: Implement `brain/tools/ingest_session_chunks.py`**

```python
#!/usr/bin/env python3
"""Ingest raw session transcripts as chunked conversation memories.

Each user+assistant exchange becomes one memory (type=conversation).
Skips system messages, file-history snapshots, and very short exchanges.

Usage:
    python3 brain/tools/ingest_session_chunks.py [--file path.json] [--all] [--dry-run]
"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from brain.api_client import save_memory_batch

SESSIONS_DIR = Path(__file__).resolve().parents[1] / "bootstrap" / "sessions_export"
CHECKPOINT   = Path(__file__).resolve().parents[1] / "bootstrap" / "checkpoint_session_chunks.json"
MIN_CHARS    = 50
BATCH_SIZE   = 32


def _extract_text(message: dict) -> str:
    """Extract plain text from a message dict (handles str and list content)."""
    content = message.get("message", {}).get("content", "")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
        return " ".join(parts).strip()
    return ""


def chunk_session(session: dict) -> list[dict]:
    """Return list of save-batch items from a session dict."""
    session_id = session.get("session_id", "")
    project    = session.get("project", "general")
    messages   = session.get("messages", [])

    # Keep only user and assistant messages in order
    useful = [m for m in messages if m.get("type") in ("user", "assistant")]

    chunks = []
    i = 0
    while i < len(useful) - 1:
        u = useful[i]
        a = useful[i + 1]
        if u.get("type") == "user" and a.get("type") == "assistant":
            user_text = _extract_text(u)
            asst_text = _extract_text(a)
            combined  = f"User: {user_text}\n\nAssistant: {asst_text}"
            if len(user_text) + len(asst_text) >= MIN_CHARS:
                chunks.append({
                    "content":     combined,
                    "memory_type": "conversation",
                    "tags":        ["session_chunk", project],
                    "project":     project,
                    "session_id":  session_id,
                    "source":      "claude_code_session",
                })
            i += 2
        else:
            i += 1
    return chunks


def load_checkpoint() -> set:
    if CHECKPOINT.exists():
        return set(json.loads(CHECKPOINT.read_text()).get("done", []))
    return set()


def save_checkpoint(done: set) -> None:
    CHECKPOINT.write_text(json.dumps({"done": sorted(done)}))


def ingest_file(path: Path, dry_run: bool = False) -> int:
    session = json.loads(path.read_text())
    chunks  = chunk_session(session)
    if not chunks:
        return 0
    if dry_run:
        print(f"[chunks] {path.name}: {len(chunks)} chunks (dry-run, not sent)")
        return len(chunks)
    for i in range(0, len(chunks), BATCH_SIZE):
        save_memory_batch(chunks[i:i + BATCH_SIZE])
    return len(chunks)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--file", help="Single session JSON file to ingest")
    p.add_argument("--all", action="store_true", help="Ingest all sessions (checkpoint-resumable)")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    if args.file:
        n = ingest_file(Path(args.file), args.dry_run)
        print(f"[chunks] ingested {n} chunks from {args.file}")
        return 0

    if args.all:
        done = load_checkpoint()
        files = sorted(SESSIONS_DIR.glob("session_*.json"))
        new_files = [f for f in files if f.name not in done]
        print(f"[chunks] {len(new_files)}/{len(files)} sessions to process", file=sys.stderr)
        total = 0
        for f in new_files:
            n = ingest_file(f, args.dry_run)
            total += n
            done.add(f.name)
            if not args.dry_run:
                save_checkpoint(done)
            print(f"[chunks] {f.name}: {n} chunks", file=sys.stderr)
        print(f"[chunks] done — {total} chunks total")
        return 0

    print("Usage: ingest_session_chunks.py [--file path.json] [--all] [--dry-run]")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
```

**Step 4: Run tests — expect PASS**

```bash
python3 -m pytest brain/tests/test_ingest_session_chunks.py -v 2>&1 | tail -10
```

**Step 5: Dry-run on all sessions**

```bash
source ~/.zshrc
python3 brain/tools/ingest_session_chunks.py --all --dry-run 2>&1 | tail -10
```

Verify chunks are produced without errors.

**Step 6: Run for real**

```bash
python3 brain/tools/ingest_session_chunks.py --all 2>&1 | tail -10
```

**Step 7: Verify memory count increased**

```bash
curl -fsS -H "x-api-key: $BRAIN_API_KEY" http://127.0.0.1:8787/stats
```

**Step 8: Add to pipeline**

In `brain/tools/brain_pipeline.py`:

```python
def step_ingest_session_chunks() -> str:
    out = _run_script("brain/tools/ingest_session_chunks.py", "--all", timeout=600)
    for line in reversed(out.splitlines()):
        if line.strip():
            return line.strip()[:80]
    return "done"

ALL_STEPS["ingest_chunks"] = Step("ingest_chunks", step_ingest_session_chunks, critical=False)
FLOWS["weekly"].insert(3, "ingest_chunks")  # after ingest_sessions
```

**Step 9: Commit**

```bash
git add brain/tools/ingest_session_chunks.py brain/tests/test_ingest_session_chunks.py brain/tools/brain_pipeline.py
git commit -m "feat(ingest): chunk raw session transcripts into conversation memories"
```

---

## Task 6: Update `brain_migrate.rs` to store embeddings in SQLite

**Files:**
- Modify: `brain/rust/src/migrate.rs`
- Modify: `brain/rust/src/bin/brain_migrate.rs`

**What changes:**
- `migrate_from_jsonl()`: after `store.upsert_memory(&memory)`, if embedding is present, also call `store.update_embedding(&id, emb)`
- `brain_migrate.rs` binary: remove `--index` flag and `VectorIndex` usage — no longer needed
- `MigrateResult`: keep `no_embedding` counter to report rows without embeddings

**Step 1: Update `migrate.rs` — replace the embedding-in-index block**

Old:
```rust
match embedding {
    Some(ref emb) => {
        index.insert(&id, emb);
        result.imported += 1;
    }
    None => {
        result.no_embedding += 1;
        result.imported += 1;
    }
}
```

New:
```rust
if let Some(ref emb) = embedding {
    store.update_embedding(&id, emb)?;
    result.imported += 1;
} else {
    result.no_embedding += 1;
    result.imported += 1;
}
```

Remove `index: &mut VectorIndex` from `migrate_from_jsonl()` signature.

**Step 2: Update tests in `migrate.rs`**

Remove `VectorIndex` from test helpers. Update assertions:
- `index.len()` checks → `store.get_embeddings_for_index().unwrap().len()`

**Step 3: Update `brain_migrate.rs` binary**

Remove `VectorIndex` import and usage. Remove `--index` flag. Just open store and migrate.

**Step 4: Run tests**

```bash
cd brain/rust && cargo test migrate 2>&1 | tail -10
```

**Step 5: Commit**

```bash
git add brain/rust/src/migrate.rs brain/rust/src/bin/brain_migrate.rs
git commit -m "feat(migrate): store embeddings in SQLite during migration — remove binary index"
```

---

## Task 7: Build, verify end-to-end, update docs, retire `brain_index.bin`

**Step 1: Full build**

```bash
cd brain/rust
cargo build --release 2>&1 | tail -5
```

Expected: clean build, no warnings on changed files.

**Step 2: Run full test suite**

```bash
cd brain/rust && cargo test 2>&1 | tail -20
python3 -m pytest brain/tests/ -v 2>&1 | tail -20
```

Expected: all pass.

**Step 3: Restart brain_api and verify**

```bash
launchctl stop com.brain.api
launchctl start com.brain.api
sleep 3
source ~/.zshrc && curl -fsS -H "x-api-key: $BRAIN_API_KEY" http://127.0.0.1:8787/stats
```

Verify `total_memories` matches `SELECT COUNT(*) FROM memories` — they must be equal now.

**Step 4: Verify zero unembedded rows**

```bash
sqlite3 "$BRAIN_DB_PATH" "SELECT COUNT(*) FROM memories WHERE embedding IS NULL;"
```

Expected: `0`

**Step 5: Archive `brain_index.bin`**

```bash
source ~/.zshrc
mv "$BRAIN_INDEX_PATH" "${BRAIN_INDEX_PATH}.bak"
# Restart to confirm brain loads without it
launchctl stop com.brain.api && launchctl start com.brain.api
sleep 3
curl -fsS -H "x-api-key: $BRAIN_API_KEY" http://127.0.0.1:8787/health
```

Expected: `{"status":"ok",...}` — brain loads entirely from SQLite.

**Step 6: Remove `BRAIN_INDEX_PATH` from `~/.zshrc`**

```bash
# Edit ~/.zshrc to remove the BRAIN_INDEX_PATH export line
source ~/.zshrc
```

**Step 7: Add `brain_backfill_embeddings` to pipeline**

In `brain/tools/brain_pipeline.py`, add to `ALL_STEPS` and `FLOWS["daily"]` after `ingest_sessions`:

```python
def step_backfill_embeddings() -> str:
    import subprocess, os
    binary = Path(__file__).resolve().parents[2] / "brain/rust/target/release/brain_backfill_embeddings"
    result = subprocess.run([str(binary)], capture_output=True, text=True,
                            timeout=300, env={**os.environ})
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip()[-200:])
    for line in reversed((result.stderr or result.stdout).splitlines()):
        if line.strip():
            return line.strip()[:80]
    return "done"

ALL_STEPS["backfill_embeddings"] = Step("backfill_embeddings", step_backfill_embeddings, critical=False)
# Insert after ingest_sessions in daily flow
idx = FLOWS["daily"].index("ingest_sessions")
FLOWS["daily"].insert(idx + 1, "backfill_embeddings")
```

**Step 8: Update `docs/BRAIN_PIPELINE.md`** — add `backfill_embeddings` and `ingest_chunks` steps to the step reference table and Mermaid diagram.

**Step 9: Update `docs/BRAIN.md`** — update Storage Layer section: remove mention of `brain_index.bin` as separate file.

**Step 10: Final commit**

```bash
git add brain/rust/ brain/tools/ brain/tests/ docs/
git commit -m "feat: single-source-of-truth vectorization — embeddings in SQLite, binary index retired"
```

---

## Verification checklist

After all tasks complete:

```bash
# 1. Zero unembedded memories
sqlite3 "$BRAIN_DB_PATH" "SELECT COUNT(*) FROM memories WHERE embedding IS NULL;"
# → 0

# 2. API count matches SQL count
sqlite3 "$BRAIN_DB_PATH" "SELECT COUNT(*) FROM memories;"
curl -fsS -H "x-api-key: $BRAIN_API_KEY" http://127.0.0.1:8787/stats | python3 -m json.tool
# → total_memories matches

# 3. Semantic search works after restart (no binary index file)
source ~/.zshrc
brain_query "rust brain migration" 3

# 4. Full pipeline runs clean
python3 brain/tools/brain_pipeline.py daily
```


<!-- brain-linker -->
## Related
- [[brain-graph/solution/Edited Usersmacm1airDocumentsAIbrainrustsrcbrain.rs pub stru]]
- [[brain-graph/conversation/User]]
- [[brain-graph/conversation/Claude Code session AI Ended 2026-04-09T045953.269990+0000 C]]
- [[brain-graph/solution/Edited Usersmacm1airDocumentsAIbrainrustsrcbrain.rs Ok(Self ]]
- [[brain-graph/conversation/Claude Code session AI Ended 2026-04-09T050638.779691+0000 C]]
<!-- /brain-linker -->
