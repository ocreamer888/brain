# Old Brain vs Updated Product — Inspection Report

**Date verified:** 2026-07-28  
**Method:** Side-by-side file inventory, content diffs on critical modules, live HTTP/launchd checks. No guessed history.

| Plane | Path | Role |
| --- | --- | --- |
| **Old / live ops** | `/Users/abundancia888/Documents/AI/brain` | Python package inside AI workspace; **launchd still points here**; full corpus DB (~118MB) |
| **Updated product** | `/Users/abundancia888/Documents/Code/brain` | Code-only git product (MacBook upload); Linked + portable MCP |

**Note:** `/Users/Shared/Code/brain` does **not** exist on this Mac (as of verification date). Historical AGENTS/changelog references to Shared/Code describe an intended operational twin, not a path present here.

Related chronicle: [`CHANGELOG-SHARED-CODE-BRAIN.md`](CHANGELOG-SHARED-CODE-BRAIN.md).

---

## 1. Live proof (this Mac, 2026-07-28)

| Check | Result |
| --- | --- |
| `GET http://127.0.0.1:8787/health` | **200** |
| `GET http://127.0.0.1:8787/linked` | **200** (product binary; was 404 pre-cutover) |
| launchd `com.brain.api` `BRAIN_DB_PATH` | `/Users/abundancia888/Documents/Code/brain/brain/rust/brain.db` |
| launchd `BRAIN_ONNX_PATH` | `/Users/abundancia888/Documents/Code/brain/brain/rust/models/all-mpnet-base-v2-onnx` |
| launchd ProgramArguments | Documents/Code `brain/rust/target/release/brain_api` |
| Product checkout `brain/rust/brain.db` | **Present** (copied 2026-07-28 cutover; 17632 memories) |

**Verdict (post–Phase 4):** Live process is **this product** checkout (`Documents/Code/brain`). Documents/AI DB retained as backup.
---

## 2. Product feature matrix

| Area | Old (Documents/AI) | Updated (this repo) | Verdict |
| --- | --- | --- | --- |
| MCP tools (11) | present | same + memory-type coercion | OK / ahead |
| HTTP API | no `/linked` | has `GET /linked` | ahead |
| Viewer | Dashboard / Search / Curate / Eval | + **Linked** + Live Feed (`FeedContext`) | ahead |
| Facts / entities / SSE `/v1/stream` | present | present | OK |
| Hybrid search / FTS / jobs | present | present | OK |
| `tools/`, `ingest/`, hooks scripts | present | same names; critical py diffs ≈0 except MCP | OK |
| Multi-instance / SSE stats-push | absent | **docs only** | not in either codebase |

### MCP tools (both)

`search_brain`, `search_index`, `timeline_tool`, `get_observations_tool`, `get_episode`, `get_neighbors_tool`, `save_memory_tool`, `get_context_tool`, `reflect_tool`, `get_stats_tool`, `record_feedback`.

### What old lacks vs product

- No Linked API/UI
- No MCP memory-type aliases (`knowledge`→`fact`, etc.)
- MCP `run_server.sh` hard-coded to Documents/AI

---

## 3. Intentionally absent from product (not gaps)

- Production SQLite corpora, ONNX model binaries (~417MB), bootstrap session dumps, Chroma legacy DB
- Research/vault essays under Documents/AI `docs/` (Karpathy, quantum, Hermes, etc.)
- Eval gold dumps / `reingest_backups` / backfill checkpoints (data, not product)

---

## 4. Real gaps addressed in product repo (2026-07-28 pass)

| Gap | Fix |
| --- | --- |
| `brain/rust/start_api.sh` exec’d Documents/AI binary | Portable launcher → this checkout’s `target/release/brain_api` |
| `.mcp.json` pointed at missing `/Users/Shared/Code/brain` | Points at this checkout’s `brain/mcp/run_server.sh` |
| `brain/config.py` hard-coded Documents/AI vault paths | Env-overridable (`OBSIDIAN_VAULT` / `OBSIDIAN_VAULT_PATH`, `CLAUDE_MEMORY_DIR`); default vault = repo `vault/` |
| Missing ops phase docs | Ported into `docs/`: `PHASE4_API.md`, `BACKFILL_AUTOMATION.md`, `PHASE6_SALIENCE.md`, `RUN_BRAIN_API_WITH_KEY.md`, `MAC_STUDIO_OLLAMA_MIGRATION.md` |

---

## 5. Cutover gate (Phase 4) — **DONE 2026-07-28**

| Check | Result |
| --- | --- |
| Release binary | `brain/rust/target/release/brain_api` built locally |
| ONNX | Copied from Documents/AI → `brain/rust/models/all-mpnet-base-v2-onnx/` (~423MB, gitignored) |
| DB | Copied from Documents/AI (118MB); AI original kept + `brain.db.bak-cutover-*` |
| launchd `com.brain.api` | Points at this checkout’s **binary** + DB + ONNX + repo `.venv` ORT dylib |
| `GET /health` | **200** |
| `GET /linked` | **200** (was 404 on old binary) |
| Stats | **17632** memories indexed |

Build/run runbook: [`BUILD-AND-CUTOVER.md`](BUILD-AND-CUTOVER.md).  
Plist: [`deploy/com.brain.api.plist`](deploy/com.brain.api.plist).

**Note:** launchd must exec the **binary** directly (not `start_api.sh`) — shell wrapper hit TCC “Operation not permitted” under Documents/Code.

## 6. Leftover audit (2026-07-28 follow-up)

### Cleared in this pass (runtime)

| Leftover | Fix |
| --- | --- |
| `brain/run_server.sh` → Documents/AI | Delegates to portable `mcp/run_server.sh` |
| `export_knowledge_graph.py` `_VAULT=/Users/macm1air/...` | Uses `brain.config.OBSIDIAN_VAULT` |
| `refresh_obsidian_dashboard.sh` macm1air ROOT | Repo-relative + `OBSIDIAN_VAULT` |
| `~/.cursor/mcp.json` brain/user-brain → Documents/AI | → this checkout’s `brain/mcp/run_server.sh` |
| `AGENTS.md` operational path `/Users/Shared/Code/brain` | → `/Users/abundancia888/Documents/Code/brain` |

### Still intentional / deferred

| Item | Why leave |
| --- | --- |
| Historical `docs/plans/*`, old phase command examples with macm1air paths | Archive plans; not runtime |
| Bootstrap one-off scripts (`17_ingest_fhir.py`, alphafold paths) | Legacy ingest against old corpus dirs; override when re-run |
| Ported ops docs still containing old `cd` examples | Historical; run from this repo instead |

### Product parity (re-verified after cutover)

- `tools/` names: full match vs old
- `rust/src/bin/`: full match
- MCP `@mcp.tool` count: 11 = 11
- Live `:8787` serves **this** product binary — `/linked` **200**
