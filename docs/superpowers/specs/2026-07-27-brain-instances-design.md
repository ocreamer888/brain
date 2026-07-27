# Brain Instances — Multi-DB Workspaces

**Date:** 2026-07-27  
**Status:** Approved for planning  
**Scope:** `brain_api` instance registry + hot-switch; Brain Viewer **Instances** tab; MCP continues on single port and always targets the **active** instance

## Problem

One Brain process today binds to a single SQLite file (`BRAIN_DB_PATH` / `brain/rust/brain.db`). Users need separate focused corpora (business, investigation, personal, etc.) **without cloning the codebase** — create, list, organize, and jump between isolated data stores from one place in the Viewer.

## Goals

- Same code + one `brain_api` process; **separate SQLite databases** per instance (hard isolation, no cross-search in v1).
- **One live brain at a time:** switch closes the current DB, opens another, rebuilds the in-memory vector index.
- MCP / agents keep using **port 8787**; they always hit the **active** instance.
- **Instances** tab: create empty, list, rename, description/tags, switch, archive, delete (archived only).
- Registry + new instance files under **`~/.brain/`** (data separate from repo).
- **Zero data loss:** existing DB registered as **Main** without copy/move in v1.

## Non-goals (v1)

- Multiple concurrent `brain_api` processes / ports
- Hot-reload alternatives that restart launchd on every switch (rejected)
- Clone / merge / search-across instances
- Folder/group hierarchy in the UI
- Automatically relocating Main into `~/.brain/instances/`
- Per-instance MCP configuration
- Changing embedding model or schema per instance

## Decisions

| Topic | Choice |
| --- | --- |
| Isolation | Separate SQLite files |
| Runtime | One process; hot-switch Brain behind existing `Arc<Mutex<Brain>>` |
| Concurrency | Single active instance; mutating routes `503` while switching |
| Storage root | `~/.brain/instances/<slug>/brain.db` for new instances |
| Registry | `~/.brain/instances.json` |
| Existing DB | Register as Main; keep current path (e.g. `brain/rust/brain.db`) |
| Organize | Name, description, tags; archive + hard-delete archived |
| UI | New Instances nav tab; match existing zinc/black Viewer |

## Architecture

```
~/.brain/
  instances.json
  instances/
    business/brain.db
    investigation/brain.db

brain/rust/brain.db          # Main (registered path; not moved in v1)
       │
       ▼
  brain_api (8787)
  ┌─────────────────────────┐
  │ instances registry      │
  │ active Brain + index    │◄── switch → close → open → rebuild
  └─────────────────────────┘
       │
       ├── Viewer (Instances tab + all other tabs)
       └── MCP (always active instance)
```

### Boot

1. Load `~/.brain/instances.json`; if missing, create and register current DB as **Main** (`id`/`slug` = `main`).
2. Resolve active DB from `active_id` (fallback: Main / `BRAIN_DB_PATH`).
3. Open Brain and rebuild index as today.
4. Persist `active_id` so restart resumes last instance.

### Create

- Input: `name` (required), `description?`, `tags?`.
- Derive unique `slug` from name; create `~/.brain/instances/<slug>/brain.db` (empty; schema via existing `CREATE TABLE IF NOT EXISTS`).
- Append registry row. Do **not** auto-switch unless the client requests switch after create.

### Switch

1. Reject unknown or archived ids; already-active is a no-op success.
2. Enter switching state (block search/save/etc. with `503`).
3. Drop current `Brain` (close SQLite).
4. Open new `db_path`, rebuild in-memory index (same path as cold start).
5. Write `active_id` to registry.
6. Return `{ active_id, stats }`. On failure: prefer keeping or restoring previous instance; avoid leaving the API with no Brain when possible.

### Archive / delete

- **Archive:** set `archived: true`; cannot archive the active instance (switch away first).
- **Unarchive:** clear flag.
- **Delete:** only if archived and not active; remove registry row and DB files; UI must confirm.

## Registry schema

```json
{
  "active_id": "main",
  "instances": [
    {
      "id": "main",
      "name": "Main",
      "slug": "main",
      "db_path": "/Users/Shared/Code/brain/brain/rust/brain.db",
      "description": "Primary personal brain",
      "tags": ["personal"],
      "archived": false,
      "created_at": "2026-07-27T00:00:00Z",
      "updated_at": "2026-07-27T00:00:00Z"
    }
  ]
}
```

- `id` equals `slug` in v1 (unique, stable after create; rename updates `name` only, not `id`/`slug`/`db_path`).
- Paths are absolute.
- Env overrides (`BRAIN_INSTANCES_ROOT`, `BRAIN_INSTANCES_REGISTRY`) are out of v1; defaults under `~/.brain` only.

## API

Same auth model as existing `/v1/*` routes.

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/v1/instances` | List (default non-archived); include `active_id`; optional cheap `memory_count` |
| `POST` | `/v1/instances` | Create `{ name, description?, tags? }` |
| `PATCH` | `/v1/instances/:id` | Update name / description / tags |
| `POST` | `/v1/instances/:id/switch` | Activate + reload Brain |
| `POST` | `/v1/instances/:id/archive` | Soft-hide |
| `POST` | `/v1/instances/:id/unarchive` | Restore |
| `DELETE` | `/v1/instances/:id` | Hard delete if archived and not active |

**Errors**

| Case | Status |
| --- | --- |
| Bad name / payload | `400` |
| Duplicate slug | `409` |
| Unknown id | `404` |
| Archive/delete active or delete non-archived | `409` |
| Switch/reload failure | `500` (restore previous when possible) |
| Request during switch | `503` |

Expose active instance identity on stats (or instances list) so the sidebar can show `Main · N memories`.

## UI

- New nav item **Instances**.
- One screen: active chip, list (active first, then name), optional “Show archived”.
- Row actions: Switch, Edit (name/description/tags), Archive, Delete (archived + confirm).
- **New instance** CTA → form → create → optional “Switch now?”.
- After switch: refetch stats; clear search / feed / linked client state so prior instance data does not ghost.
- Visual language: existing Brain Viewer (zinc/black); list + form, not a new card-heavy layout.

## Migration

1. First boot with feature: create registry if absent.
2. Register current DB as Main without copying or moving the file.
3. New instances only under `~/.brain/instances/<slug>/`.
4. No automatic rewrite of launchd `BRAIN_DB_PATH`; runtime active path comes from the registry after boot.

## Testing

- Unit: registry CRUD, slugify, archive/delete guards, active-id persistence.
- API: create → switch → stats reflect new DB; `503` while switching; delete blocked when active/unarchived.
- UI smoke: list, create, switch clears stale client state.
- Live verification: switch away from Main and back; counts match each DB.

## Implementation sketch (planning input)

1. Rust module for registry load/save + slug helpers.
2. `AppState`: hold registry path, switching flag, replace `Brain` under mutex on switch.
3. Wire instance routes; gate existing handlers on switching flag.
4. Boot path: registry bootstrap + open active DB.
5. UI: `api.js` helpers, `Instances` view, nav + sidebar active label, post-switch cache invalidation.
6. Tests + one live switch smoke on this checkout’s DB.
