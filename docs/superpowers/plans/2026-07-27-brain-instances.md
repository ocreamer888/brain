# Brain Instances Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add multi-instance Brain workspaces — separate SQLite DBs, one live `brain_api` with hot-switch, and an Instances tab to create/list/organize/jump — without cloning code.

**Architecture:** A JSON registry at `~/.brain/instances.json` tracks instances; new DBs live under `~/.brain/instances/<slug>/brain.db`. `brain_api` boots the active instance, exposes CRUD/switch routes, replaces the `Brain` behind `Arc<Mutex<Brain>>` on switch, returns `503` while switching, and makes the background job worker follow the active DB path. The Viewer gets an Instances tab; MCP keeps using port 8787 (always the active instance).

**Tech Stack:** Rust (`brain` crate + `brain_api`), serde_json, axum, SQLite via existing `MetadataStore`/`Brain::open*`, React JSX Viewer (`brain/rust/ui`)

**Spec:** `docs/superpowers/specs/2026-07-27-brain-instances-design.md`

## Global Constraints

- Separate SQLite files; hard isolation; no cross-search in v1
- One process; hot-switch only (no multi-port, no launchd restart-per-switch)
- Registry + new instance files under `~/.brain/` only (no `BRAIN_INSTANCES_*` env in v1)
- Existing DB registered as **Main** without copy/move; `id`/`slug` stay `main`
- Rename updates `name` / `description` / `tags` only — never `id`, `slug`, or `db_path`
- Delete only when `archived && id != active_id`
- Cannot archive the active instance
- During switch: search/save/list/etc. return `503`
- Background worker must follow active DB after switch (do not freeze boot-time `BRAIN_DB_PATH`)
- Match existing Viewer look (zinc/black); list + form, not card grid
- Pause for human review at each **Phase** boundary before starting the next
- Run Rust tests from `brain/rust/`; UI tests from `brain/rust/ui/` if present
- Do **not** commit unless the user explicitly asks (skip Commit steps or stop and ask)

---

## File Map

| Action | File | Responsibility |
|---|---|---|
| Create | `brain/rust/src/instances.rs` | Registry types, load/save, slugify, create/archive/delete guards |
| Modify | `brain/rust/src/lib.rs` | `pub mod instances;` |
| Modify | `brain/rust/src/bin/brain_api.rs` | AppState fields, boot from registry, instance routes, 503 gate, stats fields, worker active path, open Brain by path |
| Modify | `brain/rust/ui/src/api.js` | Instance API helpers |
| Modify | `brain/rust/ui/src/App.jsx` | Instances nav + view; sidebar active name |
| Create | `brain/rust/ui/src/views/Instances.jsx` | Instances tab UI |
| Modify | `brain/rust/ui/src/context/StatsContext.jsx` | Already has `refetch`; ensure used after switch |
| Modify | `brain/rust/ui/src/context/FeedContext.jsx` | Add `resetFeed()` to clear seeded/live items on switch |
| Skip | `brain/rust/ui/src/context/EvalContext.jsx` | Loads static `eval_dashboard.json` — not instance-scoped; leave alone |
| Build | `brain/rust/ui` → `brain/rust/static/` | Via existing `deploy.sh` when UI ships |

---

## Phase A — Registry module (pure Rust)

> **Gate:** `cargo test -p brain instances::` passes. Pause for review before Phase B.

### Task 1: `instances` module — types, slugify, load/save, bootstrap Main

**Files:**
- Create: `brain/rust/src/instances.rs`
- Modify: `brain/rust/src/lib.rs` (add `pub mod instances;`)
- Test: inline `#[cfg(test)]` in `instances.rs`

**Interfaces:**
- Consumes: `serde`, `serde_json`, `chrono`, `std::fs`/`Path`
- Produces:
  - `pub struct InstanceRecord { id, name, slug, db_path, description, tags, archived, created_at, updated_at }`
  - `pub struct InstanceRegistry { active_id: String, instances: Vec<InstanceRecord> }`
  - `pub fn slugify(name: &str) -> String`
  - `pub fn registry_path() -> PathBuf` → `~/.brain/instances.json`
  - `pub fn instances_root() -> PathBuf` → `~/.brain/instances`
  - `pub fn load_or_bootstrap(registry_path: &Path, main_db_path: &Path) -> Result<InstanceRegistry, String>`
  - `pub fn save_registry(path: &Path, registry: &InstanceRegistry) -> Result<(), String>`

- [ ] **Step 1: Write the failing tests**

```rust
#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;
    use tempfile::tempdir;

    #[test]
    fn slugify_basic() {
        assert_eq!(slugify("My Business!"), "my-business");
        assert_eq!(slugify("  Investigation Data  "), "investigation-data");
    }

    #[test]
    fn bootstrap_creates_main_without_moving_db() {
        let dir = tempdir().unwrap();
        let registry = dir.path().join("instances.json");
        let main_db = dir.path().join("existing.db");
        fs::write(&main_db, b"").unwrap();

        let reg = load_or_bootstrap(&registry, &main_db).unwrap();
        assert_eq!(reg.active_id, "main");
        assert_eq!(reg.instances.len(), 1);
        assert_eq!(reg.instances[0].id, "main");
        assert_eq!(reg.instances[0].db_path, main_db.to_string_lossy());
        assert!(registry.is_file());
        assert_eq!(fs::read(&main_db).unwrap(), b""); // untouched
    }

    #[test]
    fn save_and_reload_roundtrip() {
        let dir = tempdir().unwrap();
        let registry = dir.path().join("instances.json");
        let main_db = dir.path().join("brain.db");
        fs::write(&main_db, b"").unwrap();
        let reg = load_or_bootstrap(&registry, &main_db).unwrap();
        save_registry(&registry, &reg).unwrap();
        let again = load_or_bootstrap(&registry, &main_db).unwrap();
        assert_eq!(again.active_id, "main");
        assert_eq!(again.instances[0].name, "Main");
    }
}
```

- [ ] **Step 2: Run tests — expect FAIL**

Run: `cd brain/rust && cargo test --lib instances::tests -- --nocapture`  
Expected: compile fail (`instances` module missing) or link fail

- [ ] **Step 3: Implement module**

Add `brain/rust/src/instances.rs` with:

```rust
use chrono::Utc;
use serde::{Deserialize, Serialize};
use std::fs;
use std::path::{Path, PathBuf};

use crate::config::default_brain_dir;

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct InstanceRecord {
    pub id: String,
    pub name: String,
    pub slug: String,
    pub db_path: String,
    #[serde(default)]
    pub description: String,
    #[serde(default)]
    pub tags: Vec<String>,
    #[serde(default)]
    pub archived: bool,
    pub created_at: String,
    pub updated_at: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct InstanceRegistry {
    pub active_id: String,
    pub instances: Vec<InstanceRecord>,
}

pub fn registry_path() -> PathBuf {
    default_brain_dir().join("instances.json")
}

pub fn instances_root() -> PathBuf {
    default_brain_dir().join("instances")
}

pub fn slugify(name: &str) -> String {
    let mut out = String::new();
    let mut dash = false;
    for c in name.trim().chars() {
        if c.is_ascii_alphanumeric() {
            out.push(c.to_ascii_lowercase());
            dash = false;
        } else if !dash && !out.is_empty() {
            out.push('-');
            dash = true;
        }
    }
    out.trim_matches('-').to_string()
}

pub fn save_registry(path: &Path, registry: &InstanceRegistry) -> Result<(), String> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(|e| e.to_string())?;
    }
    let tmp = path.with_extension("json.tmp");
    let data = serde_json::to_vec_pretty(registry).map_err(|e| e.to_string())?;
    fs::write(&tmp, data).map_err(|e| e.to_string())?;
    fs::rename(&tmp, path).map_err(|e| e.to_string())
}

pub fn load_or_bootstrap(registry_path: &Path, main_db_path: &Path) -> Result<InstanceRegistry, String> {
    if registry_path.is_file() {
        let data = fs::read_to_string(registry_path).map_err(|e| e.to_string())?;
        return serde_json::from_str(&data).map_err(|e| e.to_string());
    }
    let now = Utc::now().to_rfc3339();
    let abs = main_db_path
        .canonicalize()
        .unwrap_or_else(|_| main_db_path.to_path_buf());
    let reg = InstanceRegistry {
        active_id: "main".into(),
        instances: vec![InstanceRecord {
            id: "main".into(),
            name: "Main".into(),
            slug: "main".into(),
            db_path: abs.to_string_lossy().into_owned(),
            description: "Primary personal brain".into(),
            tags: vec!["personal".into()],
            archived: false,
            created_at: now.clone(),
            updated_at: now,
        }],
    };
    save_registry(registry_path, &reg)?;
    Ok(reg)
}
```

Export in `lib.rs`: `pub mod instances;`

If `default_brain_dir` is private in `config.rs`, make it `pub` (it already is `pub` today).

- [ ] **Step 4: Run tests — expect PASS**

Run: `cd brain/rust && cargo test --lib instances::tests -- --nocapture`  
Expected: PASS

- [ ] **Step 5: Commit** (only if user asked)

```bash
git add brain/rust/src/instances.rs brain/rust/src/lib.rs brain/rust/src/config.rs
git commit -m "feat(instances): add registry load/save and Main bootstrap"
```

---

### Task 2: Registry mutations — create, patch, archive, delete, set_active

**Files:**
- Modify: `brain/rust/src/instances.rs`
- Test: same file

**Interfaces:**
- Produces:
  - `pub fn ensure_unique_slug(registry: &InstanceRegistry, base: &str) -> String` (append `-2`, `-3`, …)
  - `pub fn create_instance(registry: &mut InstanceRegistry, name: &str, description: &str, tags: Vec<String>, instances_root: &Path) -> Result<InstanceRecord, String>`
  - `pub fn patch_instance(registry: &mut InstanceRegistry, id: &str, name: Option<String>, description: Option<String>, tags: Option<Vec<String>>) -> Result<&InstanceRecord, String>`
  - `pub fn set_archived(registry: &mut InstanceRegistry, id: &str, archived: bool, active_id: &str) -> Result<(), String>`
  - `pub fn delete_instance(registry: &mut InstanceRegistry, id: &str, active_id: &str) -> Result<InstanceRecord, String>` (returns removed record for filesystem delete)
  - `pub fn set_active(registry: &mut InstanceRegistry, id: &str) -> Result<&InstanceRecord, String>`
  - `pub fn get(registry: &InstanceRegistry, id: &str) -> Option<&InstanceRecord>`

- [ ] **Step 1: Write the failing tests**

```rust
#[test]
fn create_instance_makes_db_file_and_unique_slug() {
    let dir = tempdir().unwrap();
    let root = dir.path().join("instances");
    let mut reg = InstanceRegistry { active_id: "main".into(), instances: vec![] };
    // seed main so slug collision is possible
    reg.instances.push(InstanceRecord {
        id: "main".into(), name: "Main".into(), slug: "main".into(),
        db_path: dir.path().join("main.db").to_string_lossy().into(),
        description: String::new(), tags: vec![], archived: false,
        created_at: "t".into(), updated_at: "t".into(),
    });
    let a = create_instance(&mut reg, "Biz", "work", vec!["work".into()], &root).unwrap();
    assert_eq!(a.id, "biz");
    assert!(Path::new(&a.db_path).is_file());
    let b = create_instance(&mut reg, "Biz", "", vec![], &root).unwrap();
    assert_eq!(b.id, "biz-2");
}

#[test]
fn cannot_archive_or_delete_active() {
    let dir = tempdir().unwrap();
    let mut reg = load_or_bootstrap(&dir.path().join("r.json"), &{
        let p = dir.path().join("m.db");
        fs::write(&p, b"").unwrap();
        p
    }).unwrap();
    assert!(set_archived(&mut reg, "main", true, "main").is_err());
    assert!(delete_instance(&mut reg, "main", "main").is_err());
}

#[test]
fn delete_only_when_archived() {
    let dir = tempdir().unwrap();
    let root = dir.path().join("instances");
    let main = dir.path().join("m.db");
    fs::write(&main, b"").unwrap();
    let mut reg = load_or_bootstrap(&dir.path().join("r.json"), &main).unwrap();
    let created = create_instance(&mut reg, "Temp", "", vec![], &root).unwrap();
    assert!(delete_instance(&mut reg, &created.id, "main").is_err());
    set_archived(&mut reg, &created.id, true, "main").unwrap();
    let removed = delete_instance(&mut reg, &created.id, "main").unwrap();
    assert_eq!(removed.id, created.id);
}

#[test]
fn set_active_rejects_archived() {
    let dir = tempdir().unwrap();
    let root = dir.path().join("instances");
    let main = dir.path().join("m.db");
    fs::write(&main, b"").unwrap();
    let mut reg = load_or_bootstrap(&dir.path().join("r.json"), &main).unwrap();
    let created = create_instance(&mut reg, "X", "", vec![], &root).unwrap();
    set_archived(&mut reg, &created.id, true, "main").unwrap();
    assert!(set_active(&mut reg, &created.id).is_err());
}

#[test]
fn patch_renames_display_only() {
    let dir = tempdir().unwrap();
    let main = dir.path().join("m.db");
    fs::write(&main, b"").unwrap();
    let mut reg = load_or_bootstrap(&dir.path().join("r.json"), &main).unwrap();
    let before_path = reg.instances[0].db_path.clone();
    patch_instance(&mut reg, "main", Some("Casa".into()), Some("home".into()), None).unwrap();
    assert_eq!(reg.instances[0].name, "Casa");
    assert_eq!(reg.instances[0].id, "main");
    assert_eq!(reg.instances[0].slug, "main");
    assert_eq!(reg.instances[0].db_path, before_path);
}
```

- [ ] **Step 2: Run tests — expect FAIL** (missing functions)

Run: `cd brain/rust && cargo test --lib instances::tests -- --nocapture`

- [ ] **Step 3: Implement mutations**

Rules:
- Empty/whitespace `name` → `Err("name required")`
- `create_instance`: `slug = ensure_unique_slug(...)`; if slug empty after slugify → error; `db_path = instances_root.join(slug).join("brain.db")`; `create_dir_all`; `File::create` empty db (schema created later by `Brain::open`); push record with `id = slug`
- `set_archived(..., true, active_id)` errors if `id == active_id`
- `delete_instance` errors if not archived or `id == active_id`; removes from vec; caller deletes files
- `set_active` errors if missing or archived; sets `registry.active_id`
- `patch_instance` 404-style err if missing; never changes id/slug/db_path

Also add helper for filesystem cleanup after delete:

```rust
pub fn remove_instance_files(record: &InstanceRecord) -> Result<(), String> {
    let path = Path::new(&record.db_path);
    if path.is_file() {
        fs::remove_file(path).map_err(|e| e.to_string())?;
    }
    if let Some(dir) = path.parent() {
        // only remove dir if it looks like ~/.brain/instances/<slug>
        if dir.ends_with(&record.slug) {
            let _ = fs::remove_dir(dir); // ignore if not empty
        }
    }
    Ok(())
}
```

- [ ] **Step 4: Run tests — expect PASS**

- [ ] **Step 5: Commit** (only if user asked)

---

## Phase B — `brain_api` boot, switch, routes, 503 gate

> **Gate:** API unit/integration tests for instances pass with `BRAIN_EMBEDDER=mock`. Pause before Phase C.

### Task 3: Open Brain by explicit `db_path` + AppState fields

**Files:**
- Modify: `brain/rust/src/bin/brain_api.rs`

**Interfaces:**
- Consumes: `brain::instances::*`, existing `open_brain_with_llm_tx` pattern
- Produces:
  - `fn open_brain_at(db_path: &str, memory_tx: &broadcast::Sender<MemoryEvent>) -> Result<Brain, BrainError>`
  - `AppState` gains:
    - `registry_path: PathBuf`
    - `instances_root: PathBuf`
    - `registry: Arc<Mutex<InstanceRegistry>>`
    - `active_db_path: Arc<Mutex<String>>`
    - `switching: Arc<AtomicBool>`
  - Boot uses `load_or_bootstrap(registry_path(), &PathBuf::from(brain_config_from_env().db_path))` then opens `active` record’s `db_path`

- [ ] **Step 1: Refactor open helpers**

Replace env-only open with:

```rust
fn open_brain_at(
    db_path: &str,
    memory_tx: &broadcast::Sender<brain::MemoryEvent>,
) -> Result<Brain, brain::BrainError> {
    let mut config = brain_config_from_env();
    config.db_path = db_path.to_string();
    let embedder = make_embedder()?;
    let brain = Brain::open_with_event_bus(config, embedder, Some(memory_tx.clone()))?;
    attach_llm(brain) // extract LLM attach from open_brain_with_llm_tx
}
```

Keep `open_brain_with_llm_tx` as thin wrapper calling `open_brain_at(&brain_config_from_env().db_path, …)` only if still needed by tests — prefer tests use `open_brain_at`.

- [ ] **Step 2: Extend `AppState` and boot**

In `main()`:

```rust
let env_db = brain_config_from_env().db_path;
let reg_path = brain::instances::registry_path();
let instances_root = brain::instances::instances_root();
let registry = brain::instances::load_or_bootstrap(&reg_path, Path::new(&env_db))
    .expect("instances registry");
let active_path = registry
    .instances
    .iter()
    .find(|i| i.id == registry.active_id)
    .map(|i| i.db_path.clone())
    .unwrap_or(env_db);
let brain = open_brain_at(&active_path, &memory_tx).expect("failed to open Brain");
// ... wrap brain ...
let state = AppState {
    // existing fields...
    registry_path: reg_path,
    instances_root,
    registry: Arc::new(Mutex::new(registry)),
    active_db_path: Arc::new(Mutex::new(active_path)),
    switching: Arc::new(AtomicBool::new(false)),
};
```

- [ ] **Step 3: Compile check**

Run: `cd brain/rust && BRAIN_EMBEDDER=mock cargo build --bin brain_api`  
Expected: success (routes not added yet; worker still old — fix in Task 5)

- [ ] **Step 4: Commit** (only if user asked)

---

### Task 4: `reject_if_switching` + instance HTTP routes

**Files:**
- Modify: `brain/rust/src/bin/brain_api.rs` (`build_router`, handlers, imports: `delete` routing)

**Interfaces:**
- Produces routes from spec table
- `fn reject_if_switching(state: &AppState) -> Result<(), (StatusCode, Json<ApiError>)>`
- Switch handler replaces `*state.brain.lock()`, updates registry `active_id`, updates `active_db_path`, clears `switching`

- [ ] **Step 1: Add gate helper and call it from brain-mutating/read handlers**

```rust
fn reject_if_switching(state: &AppState) -> Result<(), (StatusCode, Json<ApiError>)> {
    if state.switching.load(Ordering::SeqCst) {
        return Err((
            StatusCode::SERVICE_UNAVAILABLE,
            Json(ApiError {
                error: "switching instance".into(),
            }),
        ));
    }
    Ok(())
}
```

Call **after** `authorize_and_rate_limit` on: `/stats`, `/save`, `/save-batch`, `/search`, `/v1/search`, `/v1/search_index`, `/v1/get_observations`, `/v1/timeline`, `/list`, `/delete`, `/feedback`, `/reflect`, `/memories/:id`, `/get-episode`, `/entities`, `/link-entities`, `/neighbors`, `/linked`.  
Do **not** gate: `/health`, `/static/*`, `/eval_dashboard.json`, instance management routes (except switch sets the flag itself).

- [ ] **Step 2: Add request/response types and handlers**

Sketch for list + create + switch (implement archive/unarchive/patch/delete similarly):

```rust
#[derive(Debug, Deserialize)]
struct CreateInstanceRequest {
    name: String,
    #[serde(default)]
    description: String,
    #[serde(default)]
    tags: Vec<String>,
}

#[derive(Debug, Deserialize)]
struct PatchInstanceRequest {
    name: Option<String>,
    description: Option<String>,
    tags: Option<Vec<String>>,
}

async fn list_instances(...) -> Result<Json<Value>, ...> {
    authorize_and_rate_limit(...)?;
    // query ?include_archived=1
    let reg = state.registry.lock()...;
    let active_id = reg.active_id.clone();
    let items: Vec<_> = reg.instances.iter().filter(|i| include_archived || !i.archived).cloned().collect();
    // optional memory_count: for active id use brain.get_stats(); for others MetadataStore::open + count_memories (best-effort)
    Ok(Json(json!({ "active_id": active_id, "instances": items_with_counts })))
}

async fn switch_instance(Path(id): Path<String>, State(state): State<AppState>, ...) {
    authorize_and_rate_limit(...)?;
    if state.switching.swap(true, Ordering::SeqCst) {
        return Err(503 already switching);
    }
    // validate via set_active on a clone first; if err, clear switching and return
    let db_path = { /* lock registry, set_active, save_registry, clone db_path */ };
    let memory_tx = state.memory_tx.clone();
    let opened = tokio::task::spawn_blocking(move || open_brain_at(&db_path, &memory_tx)).await...;
    match opened {
        Ok(new_brain) => {
            *state.brain.lock()... = new_brain;
            *state.active_db_path.lock()... = db_path;
            state.switching.store(false, Ordering::SeqCst);
            // return active_id + stats
        }
        Err(e) => {
            // try reopen previous path from active_db_path / registry previous
            state.switching.store(false, Ordering::SeqCst);
            Err(500)
        }
    }
}
```

**Already-active switch:** if `id == active_id`, return 200 no-op without rebuild.

**Create:** `create_instance` + `save_registry`; do not switch.

**Delete:** `delete_instance` then `remove_instance_files`.

Wire routes:

```rust
.route("/v1/instances", get(list_instances).post(create_instance_handler))
.route("/v1/instances/:id", patch(patch_instance_handler).delete(delete_instance_handler))
.route("/v1/instances/:id/switch", post(switch_instance))
.route("/v1/instances/:id/archive", post(archive_instance))
.route("/v1/instances/:id/unarchive", post(unarchive_instance))
```

Import: `use axum::routing::delete;` (or method chain on `MethodRouter`).

- [ ] **Step 3: Enrich `/stats` with active instance**

```rust
"active_instance": {
  "id": active_id,
  "name": name
}
```

Read from `state.registry` while holding brain lock only as long as needed (avoid lock order inversion: take registry lock first or copy name before locking brain).

- [ ] **Step 4: Write API tests** (extend `brain_api.rs` `#[cfg(test)]` using existing `test_state` pattern)

Use temp dirs; set `BRAIN_EMBEDDER=mock`; point registry via constructing `AppState` fields directly (prefer not relying on `HOME`).

Minimum cases:
1. Bootstrap list contains `main`
2. Create → list grows; new db file exists
3. Switch to new empty instance → `/stats` `total_memories == 0`; switch back
4. While `switching=true`, `/search` returns 503 (set flag manually in test)
5. Delete active → 409; archive then delete → 200
6. Patch renames name only

- [ ] **Step 5: Run tests**

Run: `cd brain/rust && BRAIN_EMBEDDER=mock cargo test --bin brain_api -- --nocapture`  
Expected: PASS

- [ ] **Step 6: Commit** (only if user asked)

---

### Task 5: Background worker follows `active_db_path`

**Files:**
- Modify: `brain/rust/src/bin/brain_api.rs` (`main` worker spawn)

**Interfaces:**
- Consumes: `state.active_db_path: Arc<Mutex<String>>`
- Produces: each tick opens `MetadataStore` at **current** active path

- [ ] **Step 1: Replace frozen `db_path` clone**

```rust
let active_db_path = state.active_db_path.clone();
tokio::spawn(async move {
    loop {
        let db_path = active_db_path
            .lock()
            .unwrap_or_else(|p| p.into_inner())
            .clone();
        if db_path != ":memory:" {
            let tick = tokio::task::spawn_blocking(move || {
                let store = MetadataStore::open(&db_path)?;
                brain::worker::process_once(&store)
            })
            .await;
            // same error logging as today
        }
        tokio::time::sleep(Duration::from_secs(5)).await;
    }
});
```

- [ ] **Step 2: Manual sanity** — after switch in a test or local run, confirm worker errors do not reference the old path exclusively (optional log of db_path on error).

- [ ] **Step 3: Commit** (only if user asked)

---

## Phase C — Viewer Instances tab

> **Gate:** UI builds; manual click-through on local API. Pause before Phase D live smoke if desired.

### Task 6: API client + feed reset helpers

**Files:**
- Modify: `brain/rust/ui/src/api.js`
- Modify: `brain/rust/ui/src/context/FeedContext.jsx`
- Skip: `EvalContext.jsx` (static eval dashboard, not per-instance)

**Interfaces:**
- Produces JS helpers mirroring routes
- `FeedContext` value includes `resetFeed: () => void` that clears `feed` + `seen`

- [ ] **Step 1: Add to `api.js`**

```js
export function listInstances(includeArchived = false) {
  const q = includeArchived ? '?include_archived=1' : ''
  return api(`/v1/instances${q}`)
}

export function createInstance({ name, description = '', tags = [] }) {
  return api('/v1/instances', {
    method: 'POST',
    body: JSON.stringify({ name, description, tags }),
  })
}

export function patchInstance(id, body) {
  return api(`/v1/instances/${encodeURIComponent(id)}`, {
    method: 'PATCH',
    body: JSON.stringify(body),
  })
}

export function switchInstance(id) {
  return api(`/v1/instances/${encodeURIComponent(id)}/switch`, { method: 'POST' })
}

export function archiveInstance(id) {
  return api(`/v1/instances/${encodeURIComponent(id)}/archive`, { method: 'POST' })
}

export function unarchiveInstance(id) {
  return api(`/v1/instances/${encodeURIComponent(id)}/unarchive`, { method: 'POST' })
}

export function deleteInstance(id) {
  return api(`/v1/instances/${encodeURIComponent(id)}`, { method: 'DELETE' })
}
```

- [ ] **Step 2: Add `resetFeed` in `FeedContext.jsx`**

```js
function resetFeed() {
  seen.current = new Set()
  setFeed([])
  // optionally re-seed via listMemories(25)
}
// expose in Provider value: { feed, status, resetFeed }
```

- [ ] **Step 3: Commit** (only if user asked)

---

### Task 7: `Instances.jsx` view + App nav/sidebar

**Files:**
- Create: `brain/rust/ui/src/views/Instances.jsx`
- Modify: `brain/rust/ui/src/App.jsx`
- Modify: `brain/rust/ui/src/components/Sidebar.jsx` only if still used; primary shell is `App.jsx`

**Interfaces:**
- Consumes: api helpers, `useStats().refetch`, `useFeed().resetFeed`
- Produces: Instances tab matching zinc/black list UI

- [ ] **Step 1: Implement `Instances.jsx`**

Behavior:
- On mount: `listInstances(showArchived)`
- Header: active chip from `active_id` + name
- Toggle “Show archived”
- **New instance** form: name required; description; tags (comma-separated → array); submit → create → refresh; prompt `window.confirm('Switch to new instance now?')` → optional switch
- Row: name, description, tags, memory_count if present, Active badge
- Actions: Switch (disabled if active), Edit (inline or small form: name/description/tags), Archive / Unarchive, Delete (only if archived; `confirm` with name)
- On successful switch: `await switchInstance(id)` → `refetch()` stats → `resetFeed()` → clear any local search focus via callback prop if needed → show brief “Switched to X” status; if error mentions 503/500, show message

Keep styles consistent with `Curate.jsx` / `Dashboard.jsx` (Tailwind zinc).

- [ ] **Step 2: Wire `App.jsx`**

```js
import Instances from './views/Instances'
// NAV add: { id: 'instances', label: 'Instances', icon: '⧉' }
// sidebar header:
<p className="text-sm font-semibold tracking-wide">
  {stats?.active_instance?.name || 'Brain'}
</p>
<p className="text-xs text-zinc-500">
  {stats?.total_memories ?? '—'} memories
</p>
// main: view === 'instances' && <Instances />
```

- [ ] **Step 3: Build UI**

Run: `cd brain/rust/ui && npm run build`  
Or full: `bash brain/rust/ui/deploy.sh` (rebuilds API + kickstarts launchd)

Expected: build OK; `/` loads; Instances tab visible

- [ ] **Step 4: Commit** (only if user asked)

---

## Phase D — Live verification

> **Gate:** Manual live pass on this checkout. Then mark plan done.

### Task 8: Live switch smoke (this machine)

**Files:** none (ops)

- [ ] **Step 1: Ensure API running with new binary** (`deploy.sh` or launchd after `cargo build --release --bin brain_api`)

- [ ] **Step 2: Verify registry bootstrap**

```bash
ls -la ~/.brain/instances.json
curl -s -H "x-api-key: $BRAIN_API_KEY" http://127.0.0.1:8787/v1/instances | python3 -m json.tool
curl -s -H "x-api-key: $BRAIN_API_KEY" http://127.0.0.1:8787/stats | python3 -m json.tool
```

Expected: Main present; `active_instance` matches; Main `db_path` still this checkout’s `brain/rust/brain.db` (or whatever `BRAIN_DB_PATH` was); **memory count unchanged** vs pre-feature

- [ ] **Step 3: Create + switch + switch back**

```bash
# create
curl -s -H "x-api-key: $BRAIN_API_KEY" -H 'content-type: application/json' \
  -d '{"name":"Smoke Test","description":"temp","tags":["smoke"]}' \
  http://127.0.0.1:8787/v1/instances

# switch to smoke-test
curl -s -H "x-api-key: $BRAIN_API_KEY" -X POST \
  http://127.0.0.1:8787/v1/instances/smoke-test/switch

curl -s -H "x-api-key: $BRAIN_API_KEY" http://127.0.0.1:8787/stats
# expect total_memories near 0

# switch back to main
curl -s -H "x-api-key: $BRAIN_API_KEY" -X POST \
  http://127.0.0.1:8787/v1/instances/main/switch

curl -s -H "x-api-key: $BRAIN_API_KEY" http://127.0.0.1:8787/stats
# expect original Main count restored
```

- [ ] **Step 4: Archive + delete smoke instance** (after switched back to Main)

- [ ] **Step 5: UI click-through** — create, switch, sidebar name updates, Search empty on new instance, switch home, Search populated again; feed not showing old instance ghosts

- [ ] **Step 6: Record result** in PR/notes; fix any bugs found before calling done

---

## Spec coverage checklist

| Spec requirement | Task |
|---|---|
| Separate SQLite DBs | Task 2 create + Task 4 switch |
| One live brain; hot-switch | Task 4 |
| MCP same port / active only | unchanged port; switch updates Brain |
| Instances tab CRUD + organize | Task 7 |
| `~/.brain` registry + new DBs | Task 1–2 |
| Main bootstrap no move | Task 1 + Task 8 |
| Archive / delete guards | Task 2 + Task 4 |
| 503 while switching | Task 4 |
| Stats show active instance | Task 4 |
| Worker follows active DB | Task 5 |
| UI clear stale client state | Task 6–7 |
| Live verification | Task 8 |
| Non-goals (multi-port, clone, folders, env overrides) | intentionally omitted |

---

## Self-review notes

- No TBD/placeholder steps; worker path follow-up included (spec gap risk if omitted).
- `id == slug` consistent across tasks.
- Rename-does-not-change-slug enforced in Task 2 tests and Task 4 patch handler.
- Phase gates match user preference for pause-between-phases.
