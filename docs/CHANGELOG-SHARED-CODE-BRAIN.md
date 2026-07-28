# Shared/Code Brain — Complete Change Chronicle

**Repo:** `/Users/Shared/Code/brain`  
**Coverage:** orphan `main` baseline (2026-07-23) → HEAD + uncommitted WIP (as of 2026-07-28)  
**Purpose:** Explicit before → after record of every change in this checkout, with **how** and **why**.  
**Method:** Verified from `git log` / `git show` / working-tree diffs only. No guessed history.

---

## 0. How to read this document

| Column | Meaning |
| --- | --- |
| **Before** | Behavior or content immediately prior to the change |
| **After** | Behavior or content after the change |
| **How** | Concrete mechanism (files, APIs, commands) |
| **Why** | Product / engineering reason that justified the change |
| **Status** | `shipped` (on `main`), `WIP` (uncommitted), `designed` (spec/plan only; code not landed) |

Related design/plan docs (deeper detail):

| Topic | Spec | Plan |
| --- | --- | --- |
| Linked bipartite graph UI | `docs/superpowers/specs/2026-07-23-linked-graph-visualization-design.md` | `docs/superpowers/plans/2026-07-23-linked-graph-visualization.md` |
| Entity–edge graph (inherited + shipped earlier) | `docs/ENTITY_EDGE_GRAPH.md` | `docs/superpowers/plans/2026-07-22-entity-edge-graph.md` |
| Multi-instance DBs | `docs/superpowers/specs/2026-07-27-brain-instances-design.md` | `docs/superpowers/plans/2026-07-27-brain-instances.md` |
| SSE stats push | `docs/superpowers/specs/2026-07-28-sse-stats-push-design.md` | _(plan not written yet)_ |

Agent operating memory for this workspace lives in `AGENTS.md` (also updated in WIP below).

---

## 1. Baseline — what “before Shared/Code era” means

### 1.1 Commit `10a2c2b` — *Initial code-only brain tree* (2026-07-23)

| | |
| --- | --- |
| **Status** | `shipped` |
| **Before** | Prior git history for this tree was dump-heavy / not the intended operational checkout. Operational brain historically lived under Documents/AI with absolute paths baked into launchers. |
| **After** | Fresh orphan history: runnable source, lean docs, UI assets; **no** sessions, DBs, or ONNX models in git. |
| **How** | Single large import commit of the Brain codebase (Rust `brain_api`, Python package, MCP, hooks, ingest, evals, docs). Models and DBs stay gitignored. |
| **Why** | Separate **code** (this repo) from **data** (local SQLite / models). Give Shared/Code a clean, shareable code plane that does not depend on Documents/AI paths as the default. |

**What the baseline already included (not invented in later Shared/Code commits):**

- Rust `brain_api` on `127.0.0.1:8787` with SQLite + in-process ONNX vectors
- Hybrid search (cosine + BM25), FTS5, jobs worker, feedback
- Fact layer (types, extractor/curator, supersede, MCP `get_episode`)
- Entity–edge tables + `/entities`, `/neighbors`, `/link-entities`, MCP `get_neighbors_tool`
- React Brain Viewer under `brain/rust/ui/` → built into `brain/rust/static/`
- Python MCP tools, ingest library under `brain/ingest/`
- GitHub workflow `.github/workflows/brain-rust-onnx.yml` (ONNX CI) — later removed

**Important operational shift after baseline:** this checkout’s default data plane is `brain/rust/brain.db` under Shared/Code — **not** the Documents/AI corpus. Documents/AI remains a separate legacy plane.

---

## 2. Commit timeline (newest last within each day)

```
10a2c2b  2026-07-23  Initial code-only brain tree
fc41229  2026-07-23  Clean up CLAUDE.md by removing empty lines and links
8353a64  2026-07-23  feat: port Linked graph, Live Feed, and local wiring onto OG main
259c573  2026-07-24  readme updated
62aabfb  2026-07-24  dashboard updated
cd2732d  2026-07-24  fix(ci): export/cache ONNX model before onnx-integration verify
be7272f  2026-07-24  ci: remove brain-rust-onnx GitHub Actions workflow
cfb55c6  2026-07-27  docs: add brain instances multi-DB workspace design
6e75315  2026-07-28  docs: add SSE stats push design for viewer live counts
```

---

## 3. Shipped code changes (commit by commit)

### 3.1 `fc41229` — CLAUDE.md cleanup (2026-07-23)

| | |
| --- | --- |
| **Status** | `shipped` |
| **Before** | `CLAUDE.md` ended with empty lines plus Obsidian-style `[[brain-graph/...]]` “Related” links to unrelated project notes. |
| **After** | Trailing related-links block removed; doc ends at the Notes section. |
| **How** | Delete 11 lines from `CLAUDE.md`. |
| **Why** | Those links were vault-export noise from another corpus. Agent guidelines should stay general and portable for Shared/Code. |

---

### 3.2 `8353a64` — Linked graph, Live Feed, local wiring (2026-07-23)

| | |
| --- | --- |
| **Status** | `shipped` |
| **Why (umbrella)** | Orphan `main` had core Brain but was missing Shared/Code progress: bipartite Linked UI, SSE live feed wiring, portable MCP/hooks, and MCP memory-type coercion. This commit re-ports that work onto OG main without bringing Documents/AI data. |

#### 3.2.A — `GET /linked` API + store helpers

| | |
| --- | --- |
| **Before** | Entity graph existed (`entities` / `edges`, `/neighbors`, etc.) but there was **no** single endpoint that returned the full memory↔entity payload the Linked canvas needs. |
| **After** | `GET /linked` returns `{ memories[], entities[] }` for graph rendering. |
| **How** | |
| | 1. `MetadataStore::list_linked_memories` — memories with ≥1 edge, snippet (160 chars), entity pairs, neighbor IDs |
| | 2. `MetadataStore::list_entities_with_counts` — entities with distinct memory counts |
| | 3. `Brain::list_linked_graph` wraps both |
| | 4. `linked_handler` in `brain_api.rs` serializes snake_case types |
| **Why** | UI needs one round-trip for bipartite layout. Avoid N+1 `/neighbors` calls from the browser. Spec: Linked design (2026-07-23). |

#### 3.2.B — Near-duplicate saves still notify the live feed

| | |
| --- | --- |
| **Before** | `Brain::save_memory` on near-dupe returned the existing ID **without** broadcasting a `MemoryEvent`. Viewer looked “dead” on deduped writes. |
| **After** | Near-dupe path still returns existing ID, but also `tx.send(MemoryEvent { … })` with a 200-char snippet. |
| **How** | Extra block in `brain.rs` before `return Ok(existing_id)` when `memory_events` channel is present. |
| **Why** | Live Feed should show activity even when BVH/dedup skips insert. Operators otherwise think saves failed. |

#### 3.2.C — Brain Viewer: Linked tab (bipartite force graph)

| | |
| --- | --- |
| **Before** | Viewer nav was Dashboard / Search / Curate / Eval. Linked was list-oriented or missing as a first-class spatial view in this tree. |
| **After** | New **Linked** nav item; full-bleed canvas force graph (memories ↔ entities); floating detail/list panel; entity filter chips; focus/ego behaviors per design. |
| **How** | New/updated UI: |
| | - `views/Linked.tsx`, `components/LinkedGraph.tsx`, `components/LinkedFloater.tsx` |
| | - `lib/linkedGraphModel.ts` (+ tests), `lib/pointerClick.ts`, `lib/memoryTypeColors.ts` |
| | - `api.js` helpers for `/linked` |
| | - Vite/TS (`tsconfig.json`, vitest), package deps for d3-force stack |
| | - Built assets under `brain/rust/static/` |
| **Why** | List UX showed *that* links exist, not *how* they connect. Spatial bipartite view is the product answer. Design explicitly rejected React Flow / Cytoscape and API shape changes. |

#### 3.2.D — Live Feed via SSE (`FeedProvider`)

| | |
| --- | --- |
| **Before** | No app-wide live feed context; Dashboard did not stream saves. |
| **After** | `FeedProvider` seeds last 25 memories from `/list`, then connects `EventSource` to `/v1/stream`, prepends events (cap 200), reconnects after 1.5s on error. Dashboard shows Live Feed with connection status. |
| **How** | `context/FeedContext.jsx`; `App.jsx` wraps shell in `FeedProvider`; Dashboard consumes `useFeed()`. |
| **Why** | Operators need to see memory writes in real time while debugging hooks/MCP/API. SSE already existed server-side; UI was not subscribed. |

#### 3.2.E — Viewer shell / Search / MemoryCard

| | |
| --- | --- |
| **Before** | Separate `Sidebar` + keep-mounted-but-hidden views (`visited` set). |
| **After** | Inline zinc/black sidebar in `App.jsx` with memory totals + by-type counts; mount active view only; Search can receive `focusId` from Linked → Search deep-link; MemoryCard / Search updated for entity neighbors. |
| **How** | Rewrite of `App.jsx` navigation; updates to `Dashboard.jsx`, `Search.jsx`, `MemoryCard.jsx`, CSS. |
| **Why** | Linked needs full-bleed height (`overflow-hidden` main). Keep-alive-hidden views fought that layout. Sidebar totals make corpus health visible without leaving Dashboard. |

#### 3.2.F — Portable MCP + hooks launchers (leave Documents/AI hardcoding)

| | |
| --- | --- |
| **Before** | `brain/mcp/run_server.sh` hard-coded `cd /Users/abundancia888/Documents/AI` and that tree’s `.venv` python. Hooks lacked a Shared/Code launcher. |
| **After** | Launchers resolve repo root from script location; prefer `$VIRTUAL_ENV`, then repo `.venv`, then Documents/AI `.venv` as fallback, then `python3`. Default `BRAIN_API_URL=http://127.0.0.1:8787`. |
| **How** | Rewrite `brain/mcp/run_server.sh`; add `brain/hooks/run_hook.sh`; add repo `.mcp.json` pointing at Shared/Code `run_server.sh`. |
| **Why** | Hard-coded Documents/AI paths made MCP “connection refused” / wrong corpus when working in Shared/Code. Code ≠ data; launchers must follow the checkout. |

#### 3.2.G — MCP `save_memory_tool` memory-type coercion

| | |
| --- | --- |
| **Before** | Agents often sent labels like `knowledge`, `bugfix`, CamelCase. Rust API only accepts a fixed snake_case allow-list → saves failed or mis-typed. |
| **After** | `_normalize_memory_type` maps aliases (`knowledge`→`fact`, `bugfix`→`solution`, …), lowercases/snakifies, falls back to `conversation`. Tool description documents the allow-list. Return string includes `(type=…)`. |
| **How** | Changes in `brain/mcp/server.py`. |
| **Why** | Agents hallucinate type labels. Coercion at MCP boundary prevents silent failure and keeps SQLite type enum clean. |

#### 3.2.H — Hook import path fixes + edit buffering log

| | |
| --- | --- |
| **Before** | `session_end.py` imported `brain.summarizer` / `brain.memory` (stale paths for this package layout). Edit hooks returned `None` with no stderr breadcrumb when buffering. |
| **After** | Imports use `brain.core.summarizer` / `brain.core.memory`. Edit buffer path logs `[BRAIN] action=edit_buffered …` to stderr. |
| **How** | `session_end.py`, `post_tool_use.py`. |
| **Why** | Broken imports = silent session-end failure. Buffer log proves Edit matcher fired when debugging “hooks not saving.” |

#### 3.2.I — Misc packaging

| | |
| --- | --- |
| **Before** | No `.mcp.json` in repo tip; `.local-backup/` not ignored. |
| **After** | `.mcp.json` committed for Shared/Code; `.gitignore` adds `.local-backup/`. |
| **Why** | Local DB/migration backups must not enter git; MCP config should match this checkout. |

---

### 3.3 `259c573` — README rewrite (2026-07-24)

| | |
| --- | --- |
| **Status** | `shipped` |
| **Before** | Stub “AI Workspace” README: short bullet list of doc paths + brain-linker related wiki links. |
| **After** | Full **Brain** product README: what it is, layers table, capabilities, architecture diagram, “DB auto-created on first start”, prerequisites, run instructions, MCP/hooks, privacy, evals. |
| **How** | Replace `README.md` (~22 lines → ~400+). |
| **Why** | New contributors (and future-you) need a self-contained entry point. Stub + Documents/AI wiki links did not describe Shared/Code Brain. |

---

### 3.4 `62aabfb` — Dashboard UI trim (2026-07-24)

| | |
| --- | --- |
| **Status** | `shipped` |
| **Before** | Dashboard padding `p-8`; included a “Linked graph” promo card telling users to open the Linked tab. |
| **After** | Padding `p-4`; Linked promo card removed. Live Feed + stats remain. |
| **How** | `brain/rust/ui/src/views/Dashboard.jsx` (−9 lines). |
| **Why** | Linked already has its own nav tab. Promo card was redundant clutter on the first viewport. Tighter padding matches denser operator use. |

**Note:** Dashboard still calls `refetch()` when `feed[0].id` changes (stats poll + per-save refetch). SSE stats-push design (below) intends to remove that later.

---

### 3.5 `cd2732d` — CI ONNX export/cache fix (2026-07-24)

| | |
| --- | --- |
| **Status** | `shipped` (then superseded by removal) |
| **Before** | Workflow assumed `models/` existed in checkout. Models are gitignored (~417MB) → verify step always failed on push. |
| **After** | Workflow exports/caches ONNX before integration verify. |
| **How** | Edit `.github/workflows/brain-rust-onnx.yml` (+29 lines). |
| **Why** | Unblock CI green while the workflow still existed. |

---

### 3.6 `be7272f` — Remove ONNX GitHub Actions workflow (2026-07-24)

| | |
| --- | --- |
| **Status** | `shipped` |
| **Before** | CI downloaded/exported ONNX and gated pushes on embedder integration. |
| **After** | Workflow file deleted entirely. Embedder is **local-machine only**. Smoke without model: `BRAIN_EMBEDDER=mock`. Export locally: `python3 brain/tools/export_onnx.py`. |
| **How** | Delete `.github/workflows/brain-rust-onnx.yml`. |
| **Why** | Project policy: do not add CI that downloads/runs the ONNX embedder on GitHub. Local-first; CI complexity and HF downloads were the wrong gate for this product. Fix commit `cd2732d` became moot once the workflow was removed. |

---

### 3.7 `cfb55c6` — Brain Instances design doc (2026-07-27)

| | |
| --- | --- |
| **Status** | `designed` (spec committed; implementation plan exists as untracked/WIP file — see §5) |
| **Before** | One `brain_api` process ↔ one SQLite file. No registry, no hot-switch, no Instances UI. |
| **After (docs only)** | Approved v1 design: separate DBs under `~/.brain/instances/`, JSON registry, hot-switch inside one process, Instances tab, MCP always hits **active** instance on 8787. |
| **How** | Add `docs/superpowers/specs/2026-07-27-brain-instances-design.md`. |
| **Why** | Need focused corpora (business / investigation / personal) **without cloning the codebase**. Hard SQLite walls beat soft filters. |

---

### 3.8 `6e75315` — SSE stats push design (2026-07-28)

| | |
| --- | --- |
| **Status** | `designed` (not implemented in code yet) |
| **Before (current code)** | `StatsProvider` polls `GET /stats` every 10s; Dashboard also `refetch()` on each live-feed head id. Noisy API logs; duplicate work. |
| **After (intended)** | Attach full `BrainStats` to each `MemoryEvent` on `/v1/stream`; drop interval poll; keep `GET /stats` for cold start / reconnect only. |
| **How (intended)** | Extend `MemoryEvent` with `stats: Option<BrainStats>`; emit on insert **and** near-dupe notify; UI applies `evt.stats` when present. Spec rejects client-side count math and a second SSE channel. |
| **Why** | Exact counts without timer spam; reuse existing save SSE path. |

---

## 4. Uncommitted working-tree changes (as of 2026-07-28)

Verified with `git status` / `git diff` at documentation time.

### 4.1 `AGENTS.md` — operational facts for Shared/Code

| | |
| --- | --- |
| **Status** | `WIP` |
| **Before** | Facts still described Mac Studio Documents/AI paths, “no remote git / no GitHub CI”, long entity-graph metrics, execution-mode preference line. |
| **After** | Facts updated to: |
| | - Default DB = this checkout’s `brain/rust/brain.db`; extra instances under `~/.brain/instances/` (code ≠ data) |
| | - MCP launchers point at Shared/Code `run_server.sh` |
| | - ONNX model gitignored; no GitHub ONNX workflow; `BRAIN_EMBEDDER=mock` smoke |
| | - Operational brain = `/Users/Shared/Code/brain`; Documents/AI = legacy plane |
| | - Multi-instance product lock summary |
| | - Full Viewer paths (`static/` + `ui/`) |
| | - launchd plist must target Shared/Code (wrong plist → wrong corpus / missing Linked) |
| | - Entity graph description shortened; product scope = all types except `episode` (extract/backfill still fact-scoped today) |
| **How** | Edit learned preferences + learned workspace facts in `AGENTS.md`. |
| **Why** | Agents reading stale AGENTS.md would wire MCP/launchd to Documents/AI and corrupt the mental model of this checkout. |

### 4.2 Viewer static rebuild pointer

| | |
| --- | --- |
| **Status** | `WIP` |
| **Before** | `index.html` loaded `/static/assets/index-_yG8bFRp.js`. |
| **After** | Loads `/static/assets/index-2BLRCRek.js`; old asset deleted from tree; new asset untracked. |
| **How** | UI build → `brain/rust/static/`. |
| **Why** | Serve latest Viewer bundle from `brain_api` static files. |

### 4.3 `eval_dashboard.json` — two new run rows

| | |
| --- | --- |
| **Status** | `WIP` |
| **Before** | Newest run in file was older (e.g. `2026-07-21-2334`). |
| **After** | Prepends runs `2026-07-24-1348` and `2026-07-24-1237` (`pass: true`, `quick_p1_avg: 1.0`, `non_fact_p1: 1.0`). |
| **How** | Append/prepend JSON objects in `brain/rust/static/eval_dashboard.json`. |
| **Why** | Eval tab shows latest local suite results. |

### 4.4 New gold semantic JSONL files (untracked)

| | |
| --- | --- |
| **Status** | `WIP` |
| **Before** | Not present in this checkout tip. |
| **After** | `brain/eval/gold_semantic.jsonl` (18 lines) and `brain/eval/gold_semantic_local.jsonl` (25 lines) — query / `gold_memory_id` / `k` / description rows for semantic retrieval eval. |
| **How** | New JSONL fixtures under `brain/eval/`. |
| **Why** | Local gold sets for retrieval quality checks without relying only on older report JSON blobs. |

### 4.5 Instances implementation plan (untracked)

| | |
| --- | --- |
| **Status** | `WIP` / `designed` |
| **Before** | Spec existed (`cfb55c6`); no checked-in task plan in git tip. |
| **After** | `docs/superpowers/plans/2026-07-27-brain-instances.md` — phased TDD plan (registry module → API → UI), phase gates, file map. |
| **How** | Superpowers writing-plans output; not implemented in Rust/UI yet. |
| **Why** | Turn approved design into executable agent tasks with review pauses per phase. |

---

## 5. Designed but not yet implemented (lock these in product memory)

### 5.1 Multi-instance workspaces

**Problem:** One DB file cannot safely hold unrelated focused corpora.

**Decision summary:**

- Separate SQLite files (hard isolation; no cross-search in v1)
- One `brain_api`; hot-switch rebuilds in-memory index
- Registry: `~/.brain/instances.json`; new DBs: `~/.brain/instances/<slug>/brain.db`
- Existing DB registered as **Main** without move/copy in v1
- During switch: mutating/search routes return `503`
- Instances tab: create / list / rename / description+tags / switch / archive / delete-archived
- MCP stays on 8787 → always **active** instance

**Rejected:** multi-port processes, launchd restart-per-switch, folders in UI, auto-move Main.

### 5.2 SSE stats push

**Problem:** 10s `/stats` polling + Dashboard refetch-on-feed = log noise and duplicate work.

**Decision summary:**

- Push `BrainStats` on every `MemoryEvent` (insert + near-dupe notify)
- Drop `setInterval` in `StatsProvider`; drop Dashboard feed-triggered refetch
- Keep one `GET /stats` on mount / reconnect
- If `get_stats()` fails during save: still emit event with `stats: None`; UI keeps last counts
- Out of scope v1: delete/curate/supersede paths that do not already broadcast

---

## 6. Explicit non-changes (avoid false memories)

These did **not** change in the Shared/Code commit series above:

- Hybrid ranker math (weighted cosine + BM25; RRF remains offline-eval only)
- Embedding model identity (`all-mpnet-base-v2` ONNX)
- Fact-layer schema / curator architecture (already in baseline)
- Entity table schema / `"mentions"` relation (already in baseline; Linked is a **consumer** UI + `/linked` aggregator)
- Default MCP tool set names (`search_brain`, `save_memory_tool`, …)
- Requirement that browser viewer needs `BRAIN_API_AUTH_REQUIRED=0`

If something feels “new” but is not listed in §§3–5, check whether it was already present in `10a2c2b`.

---

## 7. Operational “how it was → how it is” (day-to-day)

| Concern | How it was | How it is now |
| --- | --- | --- |
| Default code+data plane | Documents/AI paths hard-coded in launchers | Shared/Code repo; DB at `brain/rust/brain.db` |
| MCP launcher | Absolute Documents/AI `cd` + `.venv` | Portable `run_server.sh` from repo root |
| Viewer Linked | Missing / non-spatial in this tree | Bipartite force-graph Linked tab + `GET /linked` |
| Live activity | No UI SSE subscription | `FeedProvider` + Dashboard Live Feed; near-dupes also notify |
| Agent memory types | Raw strings often rejected | MCP coerces aliases → allow-list |
| README | Stub + linker links | Full product README |
| ONNX in CI | Workflow present (then briefly patched) | Workflow removed; local export only |
| Stats freshness | Poll every 10s (+ refetch on feed) | Still polling today; **designed** to switch to SSE push |
| Multiple corpora | Clone repo or mix into one DB | **Designed** instances under `~/.brain/` (not coded yet) |

---

## 8. Success / verification notes already used

- Live Feed smoke saves observed in brain memories (conversation probes for Dashboard SSE).
- Eval dashboard rows for 2026-07-24 show `pass: true` at P@1 = 1.0 on recorded quick runs.
- MCP type coercion verified conceptually via allow-list + alias map in `server.py` (e.g. `knowledge` → `fact`).

---

## 9. Maintenance of this chronicle

When landing further work:

1. Add a new subsection under §3 (if committed) or §4 (if WIP).
2. Always fill **Before / After / How / Why / Status**.
3. Move items from §5 → §3 when implementation merges.
4. Do not delete old entries — append corrections with a dated note if a decision reverses.

**Last verified against git:** 2026-07-28 (HEAD `6e75315` + WIP listed in §4).
