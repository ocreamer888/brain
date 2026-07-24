# Claude-Mem Gap Closure Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Close the 8 feature gaps between our Rust brain and `thedotmack/claude-mem` so the brain reaches feature parity on the pieces worth stealing.

**Architecture:** Keep existing layout — Rust core (`brain/rust/`) exposes an HTTP API via `brain_api.rs`; Python MCP (`brain/mcp/server.py`) thinly wraps the HTTP API; hooks live as dedicated Rust bins under `brain/rust/src/bin/`. New features extend this shape rather than rewrite it. Async work (compression retries, tree-sitter parsing) uses a SQLite-backed job queue processed by a background worker loop inside `brain_api`.

**Tech Stack:** Rust 2021 (axum, rusqlite, tokio, serde), Python 3.13 (FastMCP), `tree-sitter` + language crates, SQLite FTS5, Server-Sent Events (SSE) for the web UI, vanilla HTML/JS frontend (no framework dependency).

**Ordering rationale:** small wins first (UserPromptSubmit hook, `<private>` filtering) to warm up the codebase; then the job queue (enables async features later); then the MCP redesign (biggest UX win); tree-sitter and web UI last.

**Worktree note:** This plan was written directly from a spec conversation — no brainstorming worktree was used. Execute in a fresh worktree (`EnterWorktree`) before Phase 1.

---

## Phase 1: UserPromptSubmit Hook

**Why:** Claude-mem injects context at `UserPromptSubmit` for mid-session recall. We only inject at `SessionStart`, so mid-session the context goes stale. Small, standalone, perfect warm-up task.

### Task 1.1: Add failing test for `handle_user_prompt_submit` binary

**Files:**
- Create: `brain/rust/src/bin/brain_user_prompt_submit.rs`

**Step 1: Write the failing test**

Add at the bottom of the new file:

```rust
fn main() {
    // placeholder
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn parses_hook_stdin_payload() {
        let payload = json!({
            "hook_event_name": "UserPromptSubmit",
            "session_id": "abc123",
            "prompt": "how do I wire up the worker queue?",
            "cwd": "/tmp/project"
        });
        let parsed = parse_hook_input(&payload.to_string()).expect("should parse");
        assert_eq!(parsed.session_id, "abc123");
        assert_eq!(parsed.prompt, "how do I wire up the worker queue?");
        assert_eq!(parsed.cwd, "/tmp/project");
    }
}
```

**Step 2: Run test to verify it fails**

Run: `cd brain/rust && cargo test --bin brain_user_prompt_submit -- parses_hook_stdin_payload`
Expected: FAIL with `parse_hook_input not defined`.

**Step 3: Commit the failing test**

```bash
git add brain/rust/src/bin/brain_user_prompt_submit.rs
git commit -m "test(hooks): failing test for UserPromptSubmit hook stdin parser"
```

### Task 1.2: Implement `parse_hook_input`

**Files:**
- Modify: `brain/rust/src/bin/brain_user_prompt_submit.rs`

**Step 1: Write minimal implementation**

Replace file contents with:

```rust
use serde::Deserialize;

#[derive(Debug, Deserialize)]
pub struct HookInput {
    #[serde(default)]
    pub session_id: String,
    pub prompt: String,
    #[serde(default)]
    pub cwd: String,
}

pub fn parse_hook_input(raw: &str) -> Result<HookInput, serde_json::Error> {
    serde_json::from_str(raw)
}

fn main() {
    let mut raw = String::new();
    if std::io::Read::read_to_string(&mut std::io::stdin(), &mut raw).is_err() {
        return;
    }
    let Ok(input) = parse_hook_input(&raw) else { return; };
    // Search brain for context relevant to this prompt, print as JSON to stdout.
    // Claude Code injects stdout into the context window.
    let _ = run(input);
}

fn run(_input: HookInput) -> Result<(), Box<dyn std::error::Error>> {
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn parses_hook_stdin_payload() {
        let payload = json!({
            "hook_event_name": "UserPromptSubmit",
            "session_id": "abc123",
            "prompt": "how do I wire up the worker queue?",
            "cwd": "/tmp/project"
        });
        let parsed = parse_hook_input(&payload.to_string()).expect("should parse");
        assert_eq!(parsed.session_id, "abc123");
        assert_eq!(parsed.prompt, "how do I wire up the worker queue?");
        assert_eq!(parsed.cwd, "/tmp/project");
    }
}
```

**Step 2: Verify it passes**

Run: `cd brain/rust && cargo test --bin brain_user_prompt_submit`
Expected: PASS.

**Step 3: Commit**

```bash
git add brain/rust/src/bin/brain_user_prompt_submit.rs
git commit -m "feat(hooks): add UserPromptSubmit hook stdin parser"
```

### Task 1.3: Wire the hook to call the brain HTTP API and emit context

**Files:**
- Modify: `brain/rust/src/bin/brain_user_prompt_submit.rs`
- Test: same file

**Step 1: Write failing test using an in-process mock**

Append to the `tests` module:

```rust
#[test]
fn formats_context_for_injection() {
    let hits = vec![
        ("we decided to use SQLite not Chroma", 0.12),
        ("rust brain_api exposes /v1/search", 0.19),
    ];
    let out = format_context(&hits);
    assert!(out.contains("we decided to use SQLite"));
    assert!(out.contains("rust brain_api"));
    // Must be bounded — don't blow the context window.
    assert!(out.lines().count() <= 12);
}
```

**Step 2: Run, expect failure**

Run: `cd brain/rust && cargo test --bin brain_user_prompt_submit formats_context`
Expected: FAIL (`format_context` missing).

**Step 3: Implement `format_context`**

Add to the same file:

```rust
pub fn format_context(hits: &[(&str, f32)]) -> String {
    let mut out = String::from("### Relevant prior context\n");
    for (content, _dist) in hits.iter().take(5) {
        let snippet: String = content.chars().take(200).collect();
        out.push_str(&format!("- {}\n", snippet));
    }
    out
}
```

**Step 4: Run again, expect PASS**

Run: `cd brain/rust && cargo test --bin brain_user_prompt_submit`
Expected: PASS.

**Step 5: Wire `run()` to call brain HTTP API**

Replace the `run()` stub with:

```rust
fn run(input: HookInput) -> Result<(), Box<dyn std::error::Error>> {
    let api_url = std::env::var("BRAIN_API_URL").unwrap_or_else(|_| "http://127.0.0.1:8765".into());
    let client = reqwest::blocking::Client::new();
    let resp = client
        .post(format!("{}/v1/search", api_url))
        .json(&serde_json::json!({ "query": input.prompt, "n": 5 }))
        .send()?;
    let body: serde_json::Value = resp.json()?;
    let hits: Vec<(String, f32)> = body["results"]
        .as_array()
        .map(|arr| {
            arr.iter()
                .filter_map(|r| {
                    Some((
                        r["content"].as_str()?.to_string(),
                        r["distance"].as_f64().unwrap_or(1.0) as f32,
                    ))
                })
                .collect()
        })
        .unwrap_or_default();
    let refs: Vec<(&str, f32)> = hits.iter().map(|(s, d)| (s.as_str(), *d)).collect();
    println!("{}", format_context(&refs));
    Ok(())
}
```

**Step 6: Register in Cargo.toml** — no change needed; Rust picks up `bin/*.rs` automatically.

**Step 7: Document hook wiring in settings**

Modify `brain/hooks/session_start.py` docstring or create `brain/hooks/README.md` note:

Append to `CLAUDE.md` (project root) a one-liner:

```
- brain_user_prompt_submit bin must be registered as UserPromptSubmit hook in ~/.claude/settings.json
```

**Step 8: Commit**

```bash
git add brain/rust/src/bin/brain_user_prompt_submit.rs CLAUDE.md
git commit -m "feat(hooks): implement UserPromptSubmit context injection"
```

---

## Phase 2: `<private>` Tag Filtering

**Why:** Some prompts or outputs contain secrets users don't want indexed. Claude-mem strips `<private>...</private>` blocks before storing. We must do the same at ingestion.

### Task 2.1: Add failing test for `strip_private_blocks`

**Files:**
- Modify: `brain/rust/src/store.rs` (add helper at top of file) OR create new `brain/rust/src/privacy.rs`
- Test: inline `#[cfg(test)]` module

**Step 1: Create privacy module**

Create `brain/rust/src/privacy.rs`:

```rust
// Placeholder — implementation in next step
```

Add to `brain/rust/src/lib.rs`:

```rust
pub mod privacy;
```

**Step 2: Write failing test**

Append to `brain/rust/src/privacy.rs`:

```rust
#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn strips_single_private_block() {
        let input = "keep this <private>API_KEY=sk-abc</private> keep this too";
        assert_eq!(strip_private_blocks(input), "keep this  keep this too");
    }

    #[test]
    fn strips_multiple_blocks_case_insensitive() {
        let input = "<PRIVATE>a</PRIVATE> b <private>c</private>";
        assert_eq!(strip_private_blocks(input), " b ");
    }

    #[test]
    fn preserves_content_without_tags() {
        let input = "no private data here";
        assert_eq!(strip_private_blocks(input), input);
    }

    #[test]
    fn is_multiline_safe() {
        let input = "before\n<private>\nsecret\nmultiline\n</private>\nafter";
        assert_eq!(strip_private_blocks(input), "before\n\nafter");
    }
}
```

**Step 3: Run, expect failure**

Run: `cd brain/rust && cargo test --lib privacy`
Expected: FAIL (`strip_private_blocks` missing).

**Step 4: Implement**

Replace `brain/rust/src/privacy.rs` contents (keep tests):

```rust
use std::sync::OnceLock;

static RE: OnceLock<regex::Regex> = OnceLock::new();

pub fn strip_private_blocks(input: &str) -> String {
    let re = RE.get_or_init(|| {
        regex::Regex::new(r"(?is)<private>.*?</private>").expect("valid regex")
    });
    re.replace_all(input, "").into_owned()
}
```

Add `regex = "1"` to `brain/rust/Cargo.toml` dependencies.

**Step 5: Run, expect PASS**

Run: `cd brain/rust && cargo test --lib privacy`
Expected: PASS (4 tests).

**Step 6: Commit**

```bash
git add brain/rust/src/privacy.rs brain/rust/src/lib.rs brain/rust/Cargo.toml
git commit -m "feat(privacy): add <private> block stripping helper"
```

### Task 2.2: Apply `strip_private_blocks` at ingestion point

**Files:**
- Modify: `brain/rust/src/brain.rs` (line ~81, `save_memory` method)
- Test: new test in same file's `mod tests`

**Step 1: Write failing integration test**

Append to `brain/rust/src/brain.rs` `mod tests`:

```rust
#[test]
fn save_memory_strips_private_blocks() {
    let brain = test_brain();
    let id = brain
        .save_memory(
            "public part <private>secret</private> more public",
            MemoryType::Conversation,
            &[],
            None,
            None,
            None,
            None,
            None,
            None,
            None,
        )
        .expect("save");
    let mem = brain.store.get_memory(&id).expect("get").expect("exists");
    assert!(!mem.content.contains("secret"));
    assert!(mem.content.contains("public part"));
}
```

(Adjust argument list to match actual `save_memory` signature — see `brain.rs:81`.)

**Step 2: Run, expect failure**

Run: `cd brain/rust && cargo test --lib save_memory_strips_private`
Expected: FAIL (secret still present).

**Step 3: Apply filter in `save_memory`**

At the top of `save_memory` in `brain/rust/src/brain.rs:81`, add:

```rust
let content = crate::privacy::strip_private_blocks(content);
// Then use `&content` everywhere the original `content` was used.
```

**Step 4: Run, expect PASS**

Run: `cd brain/rust && cargo test --lib`
Expected: PASS (all existing + new test).

**Step 5: Commit**

```bash
git add brain/rust/src/brain.rs
git commit -m "feat(privacy): strip <private> blocks at save_memory entrypoint"
```

---

## Phase 3: Pending / Retry Queue

**Why:** Compression sometimes fails (API rate limits, OOM, network). Claude-mem has a pending queue that retries asynchronously. Needed before async features (tree-sitter, compression-on-background-thread) land.

### Task 3.1: Design queue schema

**Files:**
- Modify: `brain/rust/src/store.rs` — add `ensure_queue_schema` method
- Modify: `brain/rust/src/store.rs:16` (`open`) — call new method

**Step 1: Write failing test**

Append to `brain/rust/src/store.rs` (or create `mod tests` if absent):

```rust
#[cfg(test)]
mod queue_tests {
    use super::*;

    #[test]
    fn enqueue_and_dequeue_roundtrip() {
        let store = MetadataStore::open_in_memory().unwrap();
        let id = store
            .enqueue_job("compress_session", r#"{"session_id":"s1"}"#)
            .unwrap();
        let jobs = store.pending_jobs(10).unwrap();
        assert_eq!(jobs.len(), 1);
        assert_eq!(jobs[0].id, id);
        assert_eq!(jobs[0].kind, "compress_session");
    }

    #[test]
    fn mark_job_done_removes_from_pending() {
        let store = MetadataStore::open_in_memory().unwrap();
        let id = store.enqueue_job("test", "{}").unwrap();
        store.mark_job_done(&id).unwrap();
        assert!(store.pending_jobs(10).unwrap().is_empty());
    }

    #[test]
    fn mark_job_failed_increments_attempts() {
        let store = MetadataStore::open_in_memory().unwrap();
        let id = store.enqueue_job("test", "{}").unwrap();
        store.mark_job_failed(&id, "boom").unwrap();
        let jobs = store.pending_jobs(10).unwrap();
        assert_eq!(jobs[0].attempts, 1);
        assert_eq!(jobs[0].last_error.as_deref(), Some("boom"));
    }
}
```

**Step 2: Run, expect failure**

Run: `cd brain/rust && cargo test --lib queue`
Expected: FAIL (methods missing).

**Step 3: Implement schema + methods**

Add to `brain/rust/src/store.rs`:

```rust
#[derive(Debug, Clone)]
pub struct QueuedJob {
    pub id: String,
    pub kind: String,
    pub payload: String,
    pub attempts: u32,
    pub last_error: Option<String>,
}

impl MetadataStore {
    pub fn ensure_queue_schema(&self) -> Result<(), BrainError> {
        self.conn.execute_batch(
            "CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                payload TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                last_error TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS jobs_status_idx ON jobs(status);",
        )?;
        Ok(())
    }

    pub fn enqueue_job(&self, kind: &str, payload: &str) -> Result<String, BrainError> {
        let id = uuid::Uuid::new_v4().to_string();
        self.conn.execute(
            "INSERT INTO jobs(id, kind, payload) VALUES(?, ?, ?)",
            rusqlite::params![id, kind, payload],
        )?;
        Ok(id)
    }

    pub fn pending_jobs(&self, limit: u32) -> Result<Vec<QueuedJob>, BrainError> {
        let mut stmt = self.conn.prepare(
            "SELECT id, kind, payload, attempts, last_error FROM jobs
             WHERE status='pending' ORDER BY created_at ASC LIMIT ?",
        )?;
        let rows = stmt
            .query_map([limit], |row| {
                Ok(QueuedJob {
                    id: row.get(0)?,
                    kind: row.get(1)?,
                    payload: row.get(2)?,
                    attempts: row.get(3)?,
                    last_error: row.get(4)?,
                })
            })?
            .collect::<Result<Vec<_>, _>>()?;
        Ok(rows)
    }

    pub fn mark_job_done(&self, id: &str) -> Result<(), BrainError> {
        self.conn.execute(
            "UPDATE jobs SET status='done' WHERE id=?",
            [id],
        )?;
        Ok(())
    }

    pub fn mark_job_failed(&self, id: &str, err: &str) -> Result<(), BrainError> {
        self.conn.execute(
            "UPDATE jobs SET attempts=attempts+1, last_error=? WHERE id=?",
            rusqlite::params![err, id],
        )?;
        Ok(())
    }
}
```

Call `self.ensure_queue_schema()?` in `MetadataStore::open()` and `open_in_memory()` (lines 16 and 25).

**Step 4: Run, expect PASS**

Run: `cd brain/rust && cargo test --lib queue`
Expected: PASS (3 tests).

**Step 5: Commit**

```bash
git add brain/rust/src/store.rs
git commit -m "feat(queue): add jobs table with enqueue/dequeue/mark helpers"
```

### Task 3.2: Add a worker loop in `brain_api`

**Files:**
- Modify: `brain/rust/src/bin/brain_api.rs` (near `main()`)
- Create: `brain/rust/src/worker.rs`
- Modify: `brain/rust/src/lib.rs`

**Step 1: Write failing test**

Create `brain/rust/src/worker.rs`:

```rust
use crate::store::MetadataStore;

pub async fn process_once(store: &MetadataStore) -> Result<usize, crate::BrainError> {
    let jobs = store.pending_jobs(10)?;
    let mut processed = 0;
    for job in jobs {
        // Stub: a real handler registry goes here in later phases.
        match job.kind.as_str() {
            "noop" => {
                store.mark_job_done(&job.id)?;
                processed += 1;
            }
            _ => {
                store.mark_job_failed(&job.id, "unknown kind")?;
            }
        }
    }
    Ok(processed)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::store::MetadataStore;

    #[tokio::test]
    async fn processes_noop_jobs() {
        let store = MetadataStore::open_in_memory().unwrap();
        store.enqueue_job("noop", "{}").unwrap();
        let n = process_once(&store).await.unwrap();
        assert_eq!(n, 1);
        assert!(store.pending_jobs(10).unwrap().is_empty());
    }
}
```

Add `pub mod worker;` to `brain/rust/src/lib.rs`.

Add `tokio = { version = "1", features = ["full", "test-util"] }` to `[dev-dependencies]` (if not already).

**Step 2: Run, expect PASS** (test is straightforward)

Run: `cd brain/rust && cargo test --lib worker`
Expected: PASS.

**Step 3: Spawn worker loop in `brain_api` startup**

In `brain/rust/src/bin/brain_api.rs` `main()`, after the `Brain` is constructed and before `axum::serve`, add:

```rust
let store_for_worker = brain.store_handle();  // add accessor if needed
tokio::spawn(async move {
    loop {
        if let Err(e) = brain::worker::process_once(&store_for_worker).await {
            eprintln!("worker error: {e}");
        }
        tokio::time::sleep(std::time::Duration::from_secs(5)).await;
    }
});
```

(Add `pub fn store_handle(&self) -> MetadataStore` to `Brain` if store is wrapped in Arc — or clone the connection.)

**Step 4: Verify the bin still compiles and runs**

Run: `cd brain/rust && cargo build --bin brain_api`
Expected: success, no warnings about unused `store_for_worker`.

**Step 5: Commit**

```bash
git add brain/rust/src/worker.rs brain/rust/src/lib.rs brain/rust/src/bin/brain_api.rs brain/rust/Cargo.toml
git commit -m "feat(queue): spawn worker loop in brain_api for async job processing"
```

---

## Phase 4: Progressive Disclosure MCP + `timeline` Tool

**Why:** Current `search_brain` returns full content for 10 results (~5k tokens). Claude-mem's 3-layer pattern (`search` index → `timeline` → `get_observations`) saves ~10x tokens. Core UX improvement.

### Task 4.1: Add `/v1/search_index` endpoint (compact results)

**Files:**
- Modify: `brain/rust/src/bin/brain_api.rs` (add new handler + route)
- Test: add a `#[tokio::test]` in a `tests` mod

**Step 1: Write failing test**

At the bottom of `brain/rust/src/bin/brain_api.rs`:

```rust
#[cfg(test)]
mod search_index_tests {
    use super::*;

    #[test]
    fn search_index_response_is_compact() {
        let row = SearchIndexRow {
            id: 42,
            snippet: "test".into(),
            memory_type: "solution".into(),
            project: "brain".into(),
            timestamp: "2026-04-20T00:00:00Z".into(),
            distance: 0.12,
        };
        let json = serde_json::to_string(&row).unwrap();
        // Compact rows must be < 300 chars each, no full content field.
        assert!(json.len() < 300, "row too large: {}", json.len());
        assert!(!json.contains("\"content\""));
    }
}
```

**Step 2: Run, expect failure**

Run: `cd brain/rust && cargo test --bin brain_api search_index`
Expected: FAIL (`SearchIndexRow` missing).

**Step 3: Add `SearchIndexRow` struct and handler**

Add near the existing search handler in `brain/rust/src/bin/brain_api.rs`:

```rust
#[derive(Debug, Serialize)]
pub struct SearchIndexRow {
    pub id: u64,
    pub snippet: String,   // max 120 chars
    pub memory_type: String,
    pub project: String,
    pub timestamp: String,
    pub distance: f32,
}

#[derive(Debug, Serialize)]
struct SearchIndexResponse {
    results: Vec<SearchIndexRow>,
}

async fn search_index_handler(
    State(_state): State<AppState>,
    Json(req): Json<SearchRequest>,
) -> Result<Json<SearchIndexResponse>, (StatusCode, Json<ApiError>)> {
    // Reuse existing search; shrink each hit.
    let full = perform_search(&req).map_err(internal_error)?;
    let results = full
        .into_iter()
        .map(|r| SearchIndexRow {
            id: r.numeric_id,
            snippet: r.content.chars().take(120).collect(),
            memory_type: r.memory_type,
            project: r.project,
            timestamp: r.timestamp,
            distance: r.distance,
        })
        .collect();
    Ok(Json(SearchIndexResponse { results }))
}
```

(`numeric_id` may require adding an `AUTOINCREMENT` rowid alias to the `memories` table via a migration — check `store.rs` schema first; if not present, expose the UUID `id` directly and rename field to `String`.)

**Step 4: Register route**

Find the axum `Router::new()` block and add:

```rust
.route("/v1/search_index", post(search_index_handler))
```

**Step 5: Run test, expect PASS**

Run: `cd brain/rust && cargo test --bin brain_api`
Expected: PASS.

**Step 6: Commit**

```bash
git add brain/rust/src/bin/brain_api.rs
git commit -m "feat(api): add /v1/search_index compact-row endpoint"
```

### Task 4.2: Add `/v1/get_observations` batch endpoint

**Files:**
- Modify: `brain/rust/src/bin/brain_api.rs`
- Modify: `brain/rust/src/store.rs` — add `get_memories_by_ids(&[&str])`

**Step 1: Failing test in `store.rs`**

```rust
#[test]
fn get_memories_by_ids_returns_requested_rows() {
    let store = MetadataStore::open_in_memory().unwrap();
    let m1 = sample_memory("one");
    let m2 = sample_memory("two");
    store.upsert_memory(&m1).unwrap();
    store.upsert_memory(&m2).unwrap();
    let rows = store.get_memories_by_ids(&[&m1.id, &m2.id]).unwrap();
    assert_eq!(rows.len(), 2);
}
```

(Add `fn sample_memory(content: &str) -> Memory` helper if not present.)

**Step 2: Run, expect FAIL.**

**Step 3: Implement**

```rust
pub fn get_memories_by_ids(&self, ids: &[&str]) -> Result<Vec<Memory>, BrainError> {
    if ids.is_empty() { return Ok(vec![]); }
    let placeholders = vec!["?"; ids.len()].join(",");
    let sql = format!("SELECT ... FROM memories WHERE id IN ({})", placeholders);
    let mut stmt = self.conn.prepare(&sql)?;
    let params: Vec<&dyn rusqlite::ToSql> =
        ids.iter().map(|s| s as &dyn rusqlite::ToSql).collect();
    let rows = stmt
        .query_map(params.as_slice(), |row| memory_from_row(row))?
        .collect::<Result<Vec<_>, _>>()?;
    Ok(rows)
}
```

**Step 4: Run, expect PASS.**

**Step 5: Wire HTTP handler**

Add to `brain_api.rs`:

```rust
#[derive(Debug, Deserialize)]
struct GetObservationsRequest { ids: Vec<String> }

async fn get_observations_handler(
    State(_state): State<AppState>,
    Json(req): Json<GetObservationsRequest>,
) -> Result<Json<serde_json::Value>, (StatusCode, Json<ApiError>)> {
    let refs: Vec<&str> = req.ids.iter().map(|s| s.as_str()).collect();
    let mems = /* call store.get_memories_by_ids(&refs) */;
    Ok(Json(serde_json::json!({ "results": mems })))
}
```

Add route `.route("/v1/get_observations", post(get_observations_handler))`.

**Step 6: Commit**

```bash
git add brain/rust/src/store.rs brain/rust/src/bin/brain_api.rs
git commit -m "feat(api): add /v1/get_observations batch endpoint"
```

### Task 4.3: Add `/v1/timeline` endpoint (chronological context around an ID)

**Files:**
- Modify: `brain/rust/src/store.rs` — add `timeline_around(id: &str, before: u32, after: u32)`
- Modify: `brain/rust/src/bin/brain_api.rs`

**Step 1: Failing test**

```rust
#[test]
fn timeline_returns_neighbors_by_timestamp() {
    let store = MetadataStore::open_in_memory().unwrap();
    // Insert 5 memories with ascending timestamps.
    for i in 0..5 {
        let mut m = sample_memory(&format!("m{i}"));
        m.timestamp = format!("2026-04-20T00:00:0{i}Z");
        store.upsert_memory(&m).unwrap();
    }
    let anchor_id = /* third memory's id */;
    let rows = store.timeline_around(anchor_id, 1, 1).unwrap();
    assert_eq!(rows.len(), 3); // before + anchor + after
}
```

**Step 2: Run, expect FAIL.**

**Step 3: Implement**

```rust
pub fn timeline_around(
    &self,
    anchor_id: &str,
    before: u32,
    after: u32,
) -> Result<Vec<Memory>, BrainError> {
    let anchor_ts: String = self.conn.query_row(
        "SELECT timestamp FROM memories WHERE id=?",
        [anchor_id],
        |row| row.get(0),
    )?;
    let mut before_rows: Vec<Memory> = {
        let mut stmt = self.conn.prepare(
            "SELECT ... FROM memories WHERE timestamp < ? ORDER BY timestamp DESC LIMIT ?",
        )?;
        stmt.query_map(rusqlite::params![anchor_ts, before], memory_from_row)?
            .collect::<Result<Vec<_>, _>>()?
    };
    before_rows.reverse();
    let anchor = self.get_memory(anchor_id)?.ok_or(BrainError::NotFound)?;
    let after_rows: Vec<Memory> = {
        let mut stmt = self.conn.prepare(
            "SELECT ... FROM memories WHERE timestamp > ? ORDER BY timestamp ASC LIMIT ?",
        )?;
        stmt.query_map(rusqlite::params![anchor_ts, after], memory_from_row)?
            .collect::<Result<Vec<_>, _>>()?
    };
    before_rows.push(anchor);
    before_rows.extend(after_rows);
    Ok(before_rows)
}
```

**Step 4: Run, expect PASS.**

**Step 5: Wire HTTP handler + route**

```rust
#[derive(Debug, Deserialize)]
struct TimelineRequest {
    anchor_id: String,
    #[serde(default = "default_three")] before: u32,
    #[serde(default = "default_three")] after: u32,
}
fn default_three() -> u32 { 3 }
```

Route: `.route("/v1/timeline", post(timeline_handler))`

**Step 6: Commit**

```bash
git add brain/rust/src/store.rs brain/rust/src/bin/brain_api.rs
git commit -m "feat(api): add /v1/timeline endpoint for chronological context"
```

### Task 4.4: Expose new tools via MCP

**Files:**
- Modify: `brain/mcp/server.py`
- Modify: `brain/api_client.py`

**Step 1: Add API client methods**

In `brain/api_client.py`, add:

```python
def search_index(query: str, n: int = 10, memory_type: str | None = None,
                 project: str | None = None) -> list[dict]:
    return _post("/v1/search_index", {
        "query": query, "n": n,
        "memory_type": memory_type, "project": project,
    })["results"]

def get_observations(ids: list[str]) -> list[dict]:
    return _post("/v1/get_observations", {"ids": ids})["results"]

def timeline(anchor_id: str, before: int = 3, after: int = 3) -> list[dict]:
    return _post("/v1/timeline", {
        "anchor_id": anchor_id, "before": before, "after": after,
    })["results"]
```

**Step 2: Register MCP tools**

In `brain/mcp/server.py`, add three new `@mcp.tool` functions:

```python
@mcp.tool(description="Layer 1: search brain index, returns compact rows with IDs.")
def search_index(query: str, n: int = 10, memory_type: str = "",
                 project: str = "") -> str:
    rows = api_client.search_index(query, n, memory_type or None, project or None)
    return "\n".join(
        f"[#{r['id']}] {r['memory_type']} | {r['project']} | {r['snippet']}"
        for r in rows
    )

@mcp.tool(description="Layer 2: get chronological context around an observation ID.")
def timeline_tool(anchor_id: str, before: int = 3, after: int = 3) -> str:
    rows = api_client.timeline(anchor_id, before, after)
    return "\n".join(f"[{r['timestamp']}] {r['content'][:200]}" for r in rows)

@mcp.tool(description="Layer 3: fetch full details for observation IDs.")
def get_observations_tool(ids: str) -> str:
    id_list = [s.strip() for s in ids.split(",") if s.strip()]
    rows = api_client.get_observations(id_list)
    return "\n\n".join(f"--- {r['id']} ---\n{r['content']}" for r in rows)
```

**Step 3: Update MCP instructions**

In the `FastMCP("brain", instructions=...)` string, add:

```
For large queries, use the 3-layer pattern: search_index → timeline_tool → get_observations_tool.
Start with search_index to get IDs, use timeline_tool for surrounding context, then get_observations_tool for full content of only the IDs you actually need.
```

**Step 4: Manual smoke test**

```bash
cd /Users/macm1air/Documents/AI && python -m brain.mcp.server &
# In another shell:
curl -s -X POST http://127.0.0.1:8765/v1/search_index \
  -H 'content-type: application/json' \
  -d '{"query":"rust brain","n":3}' | jq .
```

Expected: compact rows, each < 300 chars.

**Step 5: Commit**

```bash
git add brain/api_client.py brain/mcp/server.py
git commit -m "feat(mcp): expose search_index, timeline, get_observations tools"
```

---

## Phase 5: MCP Fully in Rust

**Why:** Current MCP is Python wrapping Rust HTTP. Native Rust MCP drops the Python dependency at the hook layer and simplifies distribution.

### Task 5.1: Add `rmcp` dependency and stub binary

**Files:**
- Modify: `brain/rust/Cargo.toml`
- Create: `brain/rust/src/bin/brain_mcp.rs`

**Step 1: Add dependency**

```toml
rmcp = { version = "0.1", features = ["server", "transport-io"] }
```

(Check crates.io for current version; `rmcp` is Anthropic's reference Rust MCP crate. If unavailable, use `modelcontextprotocol = "..."` or write JSON-RPC directly over stdio using `tokio`.)

**Step 2: Write failing test**

Create `brain/rust/src/bin/brain_mcp.rs`:

```rust
fn main() {}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn advertises_three_tools() {
        let tools = tool_definitions();
        let names: Vec<&str> = tools.iter().map(|t| t.name.as_str()).collect();
        assert!(names.contains(&"search_index"));
        assert!(names.contains(&"timeline"));
        assert!(names.contains(&"get_observations"));
    }
}
```

**Step 3: Run, expect FAIL.**

**Step 4: Implement `tool_definitions` and stdio server**

```rust
pub struct ToolDef { pub name: String, pub description: String }

pub fn tool_definitions() -> Vec<ToolDef> {
    vec![
        ToolDef { name: "search_index".into(), description: "compact search".into() },
        ToolDef { name: "timeline".into(), description: "chronological context".into() },
        ToolDef { name: "get_observations".into(), description: "batch fetch".into() },
    ]
}
```

Then wire up the stdio JSON-RPC loop (initialize, list_tools, call_tool). Use `brain::api_client`-style reqwest calls to the existing HTTP API so we don't duplicate business logic.

**Step 5: Integration smoke test**

Create `brain/tests/integration/test_mcp_rust_stdio_smoke.py` (reuse shape of existing `test_mcp_stdio_smoke.py`):

```python
def test_rust_mcp_initialize_and_list_tools():
    proc = subprocess.Popen(
        ["cargo", "run", "--bin", "brain_mcp", "--quiet"],
        cwd="/Users/macm1air/Documents/AI/brain/rust",
        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
    )
    # send initialize, expect response; send list_tools, expect 3 tools.
```

**Step 6: Commit**

```bash
git add brain/rust/Cargo.toml brain/rust/src/bin/brain_mcp.rs brain/tests/integration/test_mcp_rust_stdio_smoke.py
git commit -m "feat(mcp): add native Rust MCP server bin"
```

### Task 5.2: Switch MCP registration to Rust bin

**Files:**
- Modify: `.mcp.json` (project root)
- Modify: `brain/mcp/run_server.sh` (or delete)

**Step 1: Update `.mcp.json`**

Replace the `"brain"` server config with:

```json
"brain": {
  "command": "cargo",
  "args": ["run", "--bin", "brain_mcp", "--quiet"],
  "cwd": "/Users/macm1air/Documents/AI/brain/rust"
}
```

For release builds: `"command": "/path/to/brain/rust/target/release/brain_mcp"`.

**Step 2: Verify with `claude mcp list`**

Run: `claude mcp list`
Expected: `brain` server listed, status `running`.

**Step 3: Commit**

```bash
git add .mcp.json
git commit -m "chore(mcp): switch brain MCP to native Rust server"
```

---

## Phase 6: Tree-sitter Code Parsing

**Why:** PostToolUse sees raw file edits. Claude-mem uses tree-sitter to extract function/class names so observations are searchable by symbol. Improves recall precision for code queries.

### Task 6.1: Add tree-sitter dependencies

**Files:**
- Modify: `brain/rust/Cargo.toml`

**Step 1: Add**

```toml
tree-sitter = "0.22"
tree-sitter-rust = "0.21"
tree-sitter-typescript = "0.23"
tree-sitter-python = "0.23"
```

Start with these three languages; add more as needed.

**Step 2: Build check**

Run: `cd brain/rust && cargo build`
Expected: success.

**Step 3: Commit**

```bash
git add brain/rust/Cargo.toml brain/rust/Cargo.lock
git commit -m "chore(deps): add tree-sitter + 3 language parsers"
```

### Task 6.2: Implement `extract_symbols(path, content)`

**Files:**
- Create: `brain/rust/src/symbols.rs`
- Modify: `brain/rust/src/lib.rs`

**Step 1: Failing test**

Create `brain/rust/src/symbols.rs`:

```rust
#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn extracts_rust_functions() {
        let src = "pub fn hello() {} fn private() {}";
        let syms = extract_symbols("lib.rs", src);
        assert!(syms.contains(&"hello".to_string()));
        assert!(syms.contains(&"private".to_string()));
    }

    #[test]
    fn extracts_python_functions_and_classes() {
        let src = "def foo(): pass\nclass Bar: pass";
        let syms = extract_symbols("mod.py", src);
        assert!(syms.contains(&"foo".to_string()));
        assert!(syms.contains(&"Bar".to_string()));
    }

    #[test]
    fn returns_empty_for_unknown_extension() {
        assert!(extract_symbols("README.md", "# hi").is_empty());
    }
}
```

Add `pub mod symbols;` to `lib.rs`.

**Step 2: Run, expect FAIL.**

**Step 3: Implement**

```rust
use std::path::Path;
use tree_sitter::{Parser, Query, QueryCursor};

pub fn extract_symbols(path: &str, content: &str) -> Vec<String> {
    let ext = Path::new(path).extension().and_then(|s| s.to_str()).unwrap_or("");
    let (lang, query_src) = match ext {
        "rs" => (tree_sitter_rust::LANGUAGE.into(),
                 "(function_item name: (identifier) @name)"),
        "ts" | "tsx" => (tree_sitter_typescript::LANGUAGE_TYPESCRIPT.into(),
                         "(function_declaration name: (identifier) @name)"),
        "py" => (tree_sitter_python::LANGUAGE.into(),
                 "(function_definition name: (identifier) @name)
                  (class_definition name: (identifier) @name)"),
        _ => return vec![],
    };
    let mut parser = Parser::new();
    parser.set_language(&lang).expect("lang");
    let Some(tree) = parser.parse(content, None) else { return vec![]; };
    let query = Query::new(&lang, query_src).expect("query");
    let mut cursor = QueryCursor::new();
    let mut out = Vec::new();
    for m in cursor.matches(&query, tree.root_node(), content.as_bytes()) {
        for cap in m.captures {
            if let Ok(s) = cap.node.utf8_text(content.as_bytes()) {
                out.push(s.to_string());
            }
        }
    }
    out
}
```

**Step 4: Run, expect PASS.**

**Step 5: Commit**

```bash
git add brain/rust/src/symbols.rs brain/rust/src/lib.rs
git commit -m "feat(symbols): extract function/class names via tree-sitter"
```

### Task 6.3: Tag memories with extracted symbols in PostToolUse

**Files:**
- Modify: `brain/rust/src/bin/brain_post_tool_use.rs`

**Step 1: Read current bin**

Run: `cat brain/rust/src/bin/brain_post_tool_use.rs`

**Step 2: Add symbol extraction when payload contains a file edit**

Locate the place where the hook inspects `tool_input.file_path` and `tool_input.new_string` (or equivalent). Append:

```rust
if let (Some(path), Some(content)) = (file_path.as_deref(), new_content.as_deref()) {
    let syms = brain::symbols::extract_symbols(path, content);
    for s in syms {
        tags.push(format!("sym:{}", s));
    }
}
```

**Step 3: Add test**

Append to the bin's `#[cfg(test)] mod tests`:

```rust
#[test]
fn symbols_become_tags() {
    let tags = symbols_to_tags("lib.rs", "fn foo() {}");
    assert!(tags.contains(&"sym:foo".to_string()));
}
```

And factor the tagging into a helper `symbols_to_tags(path, content) -> Vec<String>` for testability.

**Step 4: Run, expect PASS.**

**Step 5: Commit**

```bash
git add brain/rust/src/bin/brain_post_tool_use.rs
git commit -m "feat(hooks): tag PostToolUse memories with tree-sitter symbols"
```

---

## Phase 7: Web Viewer UI

**Why:** Real-time memory stream at localhost:37777 is genuinely useful for debugging ("did the hook fire? did compression happen?"). Biggest piece of work; save for last.

### Task 7.1: Add SSE endpoint for memory stream

**Files:**
- Modify: `brain/rust/src/bin/brain_api.rs`
- Modify: `brain/rust/Cargo.toml` — add `tokio-stream = "0.1"` if not present
- Modify: `brain/rust/src/brain.rs` — add a `tokio::sync::broadcast` sender so saves can fan-out

**Step 1: Add broadcast channel to `Brain`**

Add a field `events: tokio::sync::broadcast::Sender<MemoryEvent>` to `Brain`. On each `save_memory`, `send` a `MemoryEvent { id, content_snippet, timestamp, memory_type }`.

**Step 2: Write failing test**

```rust
#[tokio::test]
async fn save_memory_broadcasts_event() {
    let brain = test_brain_async();
    let mut rx = brain.subscribe_events();
    let id = brain.save_memory(/* ... */).unwrap();
    let evt = tokio::time::timeout(
        std::time::Duration::from_millis(100),
        rx.recv(),
    ).await.expect("timeout").expect("recv");
    assert_eq!(evt.id, id);
}
```

**Step 3: Implement, run, expect PASS.**

**Step 4: Add `/v1/stream` SSE endpoint**

```rust
use axum::response::sse::{Event, KeepAlive, Sse};
use tokio_stream::{wrappers::BroadcastStream, StreamExt};

async fn stream_handler(State(state): State<AppState>) -> Sse<impl Stream<...>> {
    let rx = state.brain.subscribe_events();
    let stream = BroadcastStream::new(rx).filter_map(|r| async move {
        r.ok().and_then(|evt| Event::default().json_data(&evt).ok())
    });
    Sse::new(stream).keep_alive(KeepAlive::default())
}
```

Route: `.route("/v1/stream", get(stream_handler))`

**Step 5: Smoke test**

```bash
curl -N http://127.0.0.1:8765/v1/stream &
# In another shell:
curl -X POST http://127.0.0.1:8765/v1/save -d '{"content":"test","memory_type":"test"}'
# Expect: SSE event appears in the first shell.
```

**Step 6: Commit**

```bash
git add brain/rust/src/brain.rs brain/rust/src/bin/brain_api.rs brain/rust/Cargo.toml
git commit -m "feat(ui): SSE endpoint for real-time memory stream"
```

### Task 7.2: Static HTML/JS frontend

**Files:**
- Create: `brain/rust/static/index.html`
- Create: `brain/rust/static/app.js`
- Modify: `brain/rust/src/bin/brain_api.rs` — serve static dir

**Step 1: Create `brain/rust/static/index.html`**

```html
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Brain Viewer</title>
  <style>
    body { font-family: system-ui; max-width: 900px; margin: 2rem auto; padding: 0 1rem; }
    .row { padding: 0.5rem 0; border-bottom: 1px solid #eee; }
    .type { color: #888; font-size: 0.8rem; }
    input { width: 100%; padding: 0.5rem; font-size: 1rem; }
  </style>
</head>
<body>
  <h1>Brain</h1>
  <input id="q" placeholder="search..." />
  <div id="stream"></div>
  <script src="/static/app.js"></script>
</body>
</html>
```

**Step 2: Create `brain/rust/static/app.js`**

```js
const stream = document.getElementById("stream");
const q = document.getElementById("q");

const es = new EventSource("/v1/stream");
es.onmessage = (e) => {
  const evt = JSON.parse(e.data);
  const row = document.createElement("div");
  row.className = "row";
  row.innerHTML = `<div class="type">${evt.memory_type} — ${evt.timestamp}</div>
                   <div>${escapeHtml(evt.content_snippet)}</div>`;
  stream.prepend(row);
};

q.addEventListener("input", debounce(async () => {
  if (!q.value.trim()) return;
  const r = await fetch("/v1/search_index", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ query: q.value, n: 20 }),
  });
  const data = await r.json();
  stream.innerHTML = data.results.map(row => `
    <div class="row">
      <div class="type">[#${row.id}] ${row.memory_type} | ${row.project}</div>
      <div>${escapeHtml(row.snippet)}</div>
    </div>
  `).join("");
}, 200));

function escapeHtml(s) {
  return s.replace(/[&<>"']/g, c => ({
    "&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"
  }[c]));
}
function debounce(fn, ms) {
  let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}
```

**Step 3: Serve static dir**

Add `tower-http = { version = "0.5", features = ["fs"] }` to Cargo.toml.

In `brain_api.rs`:

```rust
use tower_http::services::ServeDir;
let app = Router::new()
    .route("/", get(|| async { axum::response::Redirect::permanent("/static/index.html") }))
    .nest_service("/static", ServeDir::new("brain/rust/static"))
    // ... rest of routes
```

**Step 4: Manual test**

Run: `cd brain/rust && cargo run --bin brain_api`
Open browser: `http://127.0.0.1:8765/`
Expected: page loads, search works, new saves appear in stream.

**Step 5: Commit**

```bash
git add brain/rust/static/ brain/rust/src/bin/brain_api.rs brain/rust/Cargo.toml
git commit -m "feat(ui): static HTML/JS viewer with live stream and search"
```

### Task 7.3: Bake static assets into binary (optional polish)

**Why:** Right now `ServeDir` requires the `static/` dir to exist next to the binary. For distribution, embed with `rust-embed`.

**Files:**
- Modify: `brain/rust/Cargo.toml` — add `rust-embed = "8"`
- Modify: `brain/rust/src/bin/brain_api.rs`

**Step 1: Replace `ServeDir` with `rust-embed`-backed handler**

```rust
#[derive(rust_embed::RustEmbed)]
#[folder = "static/"]
struct StaticAssets;

async fn static_handler(axum::extract::Path(path): axum::extract::Path<String>) -> impl IntoResponse {
    match StaticAssets::get(&path) {
        Some(content) => {
            let mime = mime_guess::from_path(&path).first_or_octet_stream();
            ([(axum::http::header::CONTENT_TYPE, mime.as_ref())], content.data.into_owned()).into_response()
        }
        None => StatusCode::NOT_FOUND.into_response(),
    }
}
```

Register `.route("/static/*path", get(static_handler))`.

**Step 2: Commit**

```bash
git add brain/rust/Cargo.toml brain/rust/src/bin/brain_api.rs
git commit -m "refactor(ui): embed static assets into brain_api binary"
```

---

## Phase 8: Integration & Documentation

### Task 8.1: Update CLAUDE.md with new tool guidance

**Files:**
- Modify: `CLAUDE.md`

Add to the `## Brain` section:

```markdown
### 3-layer MCP search pattern

For large queries use this order to save tokens:
1. `search_index(query)` → compact rows with IDs
2. `timeline_tool(anchor_id=...)` → chronological context
3. `get_observations_tool(ids=...)` → full content only for IDs you actually need

### Web viewer
Open http://127.0.0.1:8765 (when `brain_api` is running) to see live memory stream and search.
```

### Task 8.2: Add end-to-end smoke test

**Files:**
- Create: `brain/tests/integration/test_claude_mem_parity.py`

Write a test that:
1. Saves a memory with `<private>...</private>`
2. Asserts stored content has the block stripped
3. Calls `search_index` — asserts compact rows
4. Calls `get_observations` — asserts full content
5. Calls `timeline` around a known ID — asserts chronological neighbors
6. Opens SSE `/v1/stream`, saves another memory, asserts event fires

**Step 1: Run full test suite**

```bash
cd brain/rust && cargo test
cd /Users/macm1air/Documents/AI && python -m pytest brain/tests/
```

Expected: all pass.

**Step 2: Commit**

```bash
git add CLAUDE.md brain/tests/integration/test_claude_mem_parity.py
git commit -m "test: end-to-end claude-mem parity smoke test"
```

### Task 8.3: Tag release

**Files:** none

```bash
git tag -a v0.2.0-feature-parity -m "feature parity with claude-mem"
```

Do not push until user approves.

---

## Deferred / Explicitly Out of Scope

| Feature | Why skipped |
|---|---|
| Multi-language i18n for observations | We're an internal tool, English is fine |
| Plugin marketplace installer | We install manually |
| Discord release notify | Not using Discord |
| `np` release tooling | Not publishing to npm |
| 20+ tree-sitter languages | Start with 3; add on demand |

---

## Execution Dependency Graph

```
Phase 1 (hook) ─┐
Phase 2 (priv) ─┤─► Phase 3 (queue) ─► Phase 6 (treesitter) ─► Phase 7 (UI)
Phase 4 (MCP) ──┘                  └► Phase 5 (rust MCP) ────┘
                                                              └► Phase 8 (docs)
```

Phases 1 and 2 are independent (pick either first). Phase 4 is independent of 1/2/3 but benefits from them landing. Phase 5 depends on Phase 4 (exposes the same tools). Phase 7 depends on Phase 4 (uses `/v1/search_index`).

---

## Estimated Effort

| Phase | Size | Reasoning |
|---|---|---|
| 1. UserPromptSubmit hook | S | New bin, reuses HTTP API |
| 2. `<private>` filtering | XS | Regex + one call site |
| 3. Pending queue | M | Schema + worker loop |
| 4. Progressive disclosure MCP | M | 3 endpoints + MCP tools |
| 5. Rust MCP | M | Port Python MCP; stdio JSON-RPC |
| 6. Tree-sitter | M | New crate, per-language queries |
| 7. Web UI | L | SSE + frontend + static serving |
| 8. Docs + e2e | S | Catch-up pass |

**Total:** ~2–3 weeks of focused work.
