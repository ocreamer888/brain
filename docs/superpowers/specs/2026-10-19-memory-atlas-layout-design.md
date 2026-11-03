# Memory atlas: layout in the database, atlas served live

**Date:** 2026-10-19
**Status:** Implemented 2026-10-19 (owner approved "the real fix"). Deviations from this draft are listed in §8.
**Replaces:** `brain/rust/ui/public/atlas.json` + `scripts/build_atlas.py` + `scripts/layout_atlas.mjs`.
**Related:** UI tracker `brain/rust/ui/src/docs/components-dev.md` #37; brand book §8 (a line is a real link).

---

## 1. Problem

The Linked view loads `atlas.json`, a 2.1 MB file built offline. About half of it copies the database (ids, types, projects, ~100-char excerpts, edges, entity names); the only new data is each point's 3D position.

- **Stale:** memories saved after the build are missing; edited or superseded ones keep old excerpts.
- **Second copy of memory text:** in production `public/` is baked into the binary by rust-embed, so excerpts ship inside the server.
- **Refreshing needs a redeploy:** rerunning the script doesn't change what production serves.
- **Wrong runtime:** the layout needs Python + numpy + Node + d3-force-3d. None of that can ship inside Tendrium.

## 2. What the AI Model Atlas does (the practice we follow)

Measured from its published project, 2026-10-19:

1. **The layout is data, stored once, next to the points.** Its node table carries `layout_x / layout_y / layout_z`. The viewer reads positions; `rescalePositions` only fits them to the screen.
2. **Attributes stay in their own table and are joined at load.** Labels, author, downloads, etc. are columns of the node table; links are a second table referencing node ids. Nothing is duplicated into a "render file".
3. **Columnar transfer.** Data arrives as Parquet (columns, typed, compressed): 176k nodes in 12 MB, 89k links in 1.2 MB.
4. **Layout is computed offline with a quality algorithm, not live in the browser.** The browser renders only.
5. **Framing uses quantiles** (`quantileExtent [0.05, 0.95]`), so outliers don't shrink the view.

Two general practices for maps that change over time (graph drawing literature, "mental map" preservation):

6. **Stability:** re-layouts warm-start from the previous positions, so familiar regions don't jump.
7. **Provisional placement:** new items appear near their known neighbours immediately; a full re-layout tidies them later.

## 3. Design

### 3.1 Storage: two small tables per brain

Each brain instance has its own `brain.db`, so each gets its own layout automatically.

```sql
-- One finished (or running) layout computation. Provenance + "built at".
CREATE TABLE IF NOT EXISTS atlas_runs (
  id            TEXT PRIMARY KEY,             -- uuid
  status        TEXT NOT NULL,                -- running | done | failed
  algorithm     TEXT NOT NULL,                -- e.g. 'forest-pack/1'
  params        TEXT NOT NULL,                -- JSON of the tuning used
  started_at    TEXT NOT NULL,
  finished_at   TEXT,
  points        INTEGER, families INTEGER, edges INTEGER,
  error         TEXT
);

-- Positions only. Everything else is read live from memories / entities / edges.
CREATE TABLE IF NOT EXISTS atlas_positions (
  run_id      TEXT NOT NULL REFERENCES atlas_runs(id) ON DELETE CASCADE,
  point_kind  INTEGER NOT NULL,               -- 0 memory, 1 entity (hub)
  point_id    TEXT NOT NULL,                  -- memories.id or entities.id
  x REAL NOT NULL, y REAL NOT NULL, z REAL NOT NULL,
  family      INTEGER NOT NULL,               -- packed body this point belongs to
  PRIMARY KEY (run_id, point_kind, point_id)
);
```

- Only the latest `done` run is served; the previous one is kept until a newer run finishes (instant rollback; older runs pruned to 2).
- Size: about 14k rows × ~60 B ≈ 1 MB per run. Written in one transaction after computing (measured target below 200 ms of write lock).
- **No change to `memories`.** No new columns on the hot table; deleting the two tables removes the feature cleanly.
- Created with `CREATE TABLE IF NOT EXISTS` in `create_tables`, the existing migration pattern.

### 3.2 Layout: ported into the Rust binary

The current algorithm (validated against the reference) is ported to `src/atlas.rs`, so it runs anywhere Brain runs, Tendrium included:

1. **Forest from real data:** each live memory → its most-mentioned shared entity; each hub → the bigger hub it is co-mentioned with in ≥ 15% of its memories; free memories get a layout-only pull to their most similar linked memory (existing embeddings, same project).
2. **Families** = connected components. Each family laid out alone: link springs, collision, slight repulsion, strong pull to its centre → a solid body.
3. **Packing:** families placed biggest-first at the centre, satellites in a shell, with a gap.
4. **Deterministic:** seeded RNG and stable ordering → same data gives the same layout (testable).
5. **Warm start:** a family that existed in the previous run starts from its old shape and centre; only new families search for space. Familiar regions stay put.

Expected cost: the JS version took ~25 s, mostly per-family simulation in d3; Rust with a uniform grid for collision should be well under that (to be measured, target < 10 s for 14k points). It runs off the request path.

### 3.3 Running it: the existing job worker

The API already polls a `jobs` table every 5 s per active brain (`worker::process_once`), handling only `noop` so far.

- New job kind `atlas_layout`. The worker runs it in `spawn_blocking`, writes an `atlas_runs` row `running` → `done` / `failed`.
- **One at a time:** enqueueing while one is pending or running returns the existing job.
- **Triggers:** the Rebuild button; optionally later, automatically when > N memories are unplaced (§3.5), N to be decided.
- Reads use the normal connection; the only write is the final transaction.

### 3.4 API

| Endpoint | Returns |
| --- | --- |
| `GET /v1/atlas` | The atlas, built live: points (id, kind, type, project, size, label, x/y/z, `placed` flag), forest edges, other real edges, projects, run metadata (`built_at`, algorithm, counts), and `unplaced` count. |
| `POST /v1/atlas/rebuild` | `{ job_id }` (or the job already queued). Write-class rate limit. |
| `GET /v1/atlas/status` | Latest run + job status, for the button's progress. |

**Transfer format, columnar like the reference:** one JSON object of parallel arrays (`id[]`, `type[]`, `x[]`…), not an array of objects. Positions rounded to 0.1. About 2 MB raw for 14k points (labels are the bulk).

- **Labels:** title, or the first 100 characters of content, computed in the query and never stored.
- **Compression:** the API sends nothing compressed today (`/linked` is 11.8 MB raw). Adding `tower-http`'s `CompressionLayer` would bring the atlas to about 0.8 MB and `/linked` far lower. **New dependency: needs approval.** Without it, the atlas still works at ~2 MB on localhost.
- **Caching:** `ETag` = latest run id + count + max timestamp of live memories; the browser revalidates with `If-None-Match` and gets `304` when nothing changed.

### 3.5 New memories between layouts (provisional placement)

A live memory with no row in the current run:

- has a shared entity that is placed → put next to that hub, offset by a deterministic hash of its id (no flicker between loads);
- otherwise → placed next to its most similar placed memory in the same project, if one exists, else in the outer shell.
- The response marks it `placed: false`; the card says "**38 new since this layout · Rebuild**".

So a memory saved a second ago shows in the atlas on the next load, no rebuild needed.

### 3.6 UI changes

- `loadAtlas()` reads `/v1/atlas` (same decoded shape as now; `decodeAtlas` keeps its tests).
- Atlas card: built-at from the run, "N new since this layout", **Rebuild** button with progress from `/v1/atlas/status`, then reload.
- Remove: `public/atlas.json`, its `.gitignore` line, `scripts/build_atlas.py`, `scripts/layout_atlas.mjs`, the `d3-force-3d` devDependency, the "not built yet" command text (becomes "Build the atlas" button).

## 4. What stays the same

- Rendering, colours, ribbons, interactions, and every flow tested so far.
- `/linked` keeps working for now (nothing else in the UI uses it); retire it later.
- Brand-book rule: lines only for real links. Similarity pulls are layout-only and never sent as edges.

## 5. Rollout

1. **Rust:** `atlas.rs` (forest, families, packing, warm start), tables, job kind, three endpoints, tests (below). Compare the Rust layout with the current JS one on the same data: families, largest share, no overlaps, visual side by side. Release build trialled on a DB snapshot (as with `/entities/top`), then live restart.
2. **UI:** switch to `/v1/atlas`, add Rebuild and "N new", remove the file pipeline.
3. **Later, separately:** compression layer; automatic rebuild threshold; retire `/linked`.

## 6. Tests

- **Store:** tables created idempotently; positions round-trip; only the latest `done` run is served; failed runs never replace a good one; pruning keeps 2.
- **Layout:** determinism (same input → same output); no family overlap; every live memory placed exactly once; free memories placed in their project; warm start keeps an unchanged family within a small tolerance.
- **Provisional placement:** a memory added after the run is returned near its hub, flagged unplaced; a superseded memory disappears.
- **API:** shape and counts; ETag returns 304 when nothing changed; rebuild is single-flight.
- **Worker:** `atlas_layout` job runs, records `done`; a panic records `failed` and leaves the previous run served.
- **Instances:** each brain's atlas is independent (switching brains switches atlas).

## 7. Risks and open questions

| Risk | Mitigation |
| --- | --- |
| Layout port differs from the tuned JS look | Side-by-side comparison gate in step 1; params kept identical; JS kept until approved |
| Write lock during save | One transaction of ~14k small rows after computing; measured before shipping |
| Large brains (100k+ memories) | Uniform-grid collision; per-family sims are independent, parallelisable later |
| Payload without compression | ~2 MB on localhost is fine; compression is a separate, approved step |

**Decisions needed:**
1. Approve the two new tables (schema change).
2. Approve the three endpoints and a live server restart for step 1.
3. `tower-http` compression now, later, or never?
4. Automatic rebuild: off for now (button only), or a threshold (e.g. 200 new memories)?

## 8. As built (2026-10-19)

- Tables named `memory_atlas_runs` / `memory_atlas_positions` (the `atlas_*` names went to stored reference datasets, `src/atlas.rs`). Created with the other tables in `store.rs`.
- Layout in `src/memory_atlas.rs` (Rust port of the tuned JS layout, deterministic seed). On Main: 14,432 points, 1,037 families in ~20 s, same family count and spacing (median neighbour gap 3.16 vs 3.14) as the JS version.
- Rebuild runs as a background blocking task from the endpoint, single-flight per brain (an in-process set), with durable status in `memory_atlas_runs` (running / done / failed); not through the `jobs` table, which only polls the active brain.
- Endpoints: `GET /v1/memory-atlas/:id` (the viewer's columnar JSON, live; ETag from run + live memory count + latest timestamp + edge count), `POST /:id/rebuild` (202), `GET /:id/status`. Any brain, no switching.
- Provisional placement: hubs at the centre of their placed children; memories beside their hub, else in their project, else near the centre; deterministic jitter from the id.
- Warm start added the same day: families mostly present in the previous run start from their old shape (alpha 0.3) and keep their old centre if free. Median move on Main 3.25 vs 111 cold.
- Automatic rebuild (built 2026-10-19, pending owner OK for live): a server task checks the active brain every `BRAIN_ATLAS_AUTO_CHECK_SECS` (600) and rebuilds once `BRAIN_ATLAS_AUTO_REBUILD` (200; 0 = off) live memories are newer than the current layout (`memory_atlas::new_since_layout`). Same single-flight as the button; never builds a brain that has no layout.
- Not yet: compression.
- Retired: `public/atlas.json`, `scripts/build_atlas.py`, `scripts/layout_atlas.mjs`, `d3-force-3d`. CLI: `brain_memory_atlas <db-path>`.
