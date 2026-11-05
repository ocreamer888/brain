# Shared/Code Brain — Complete Change Chronicle

**Repo:** `/Users/Shared/Code/brain`  
**Coverage:** orphan `main` baseline (2026-07-23) → HEAD + uncommitted WIP (as of 2026-11-04). §§1–4.1–4.(N-1) verified as of 2026-07-28 and not re-audited since; §3.9 onward and §4's final entry verified as of 2026-11-04.  
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
| Old (Documents/AI) vs this product | `docs/OLD-VS-NEW-BRAIN-INSPECTION.md` | — |
| Build + Phase 4 cutover runbook | `docs/BUILD-AND-CUTOVER.md` | — |

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

### 3.9 `1e40ba4` — Trustworthy eval harness: usage-mined gold set + recency pairs (2026-11-03)

| | |
| --- | --- |
| **Status** | `shipped` |
| **Before** | The only eval (`retrieval_eval_kfold.py`) scored each memory's own title against itself — circular; couldn't show whether salience/layers/gates actually help (per a 2026-10-27 audit). |
| **After** | Three new tools replace it as the trusted oracle: `mine_eval_queries.py` mines real Claude Code transcripts for `search_index`/`search_brain`/`get_context_tool` calls, treating any result later promoted to `get_observations_tool`/`timeline_tool` as a genuine usage-grounded relevance judgment; `retrieval_eval.py` threads `project`/`memory_type` per gold row through `score_one`/`run_eval`/`search_fn` so replayed queries hit production `/search` with the same filters the original call used (the missing filter caused 5 of 6 early "misses" — recall went 0.70 → 0.95 → 1.0 as filters were restored); `recency_eval.py` is a pairwise "does the newer memory outrank the older" scorer built from 16 hand-labelled true layer pairs + 47 curator-confirmed pairs. |
| **How** | New: `brain/tools/mine_eval_queries.py`, `brain/tools/recency_eval.py`; extended `retrieval_eval.py`. Outputs: `brain/eval/gold_mined.jsonl`, `brain/eval/gold_recency.jsonl`. |
| **Why** | G8 (the owner's temporal-layer model) can't be validated against a circular self-match eval. This is the precursor gold set it needs. |

---

### 3.10 `77851f3` — Soft-hide untraceable path-fragment-project noise (2026-11-03)

| | |
| --- | --- |
| **Status** | `shipped` (live DB mutation, reversible) |
| **Before** | 8,565 live rows carried a May-backfill metadata bug: `project` field was a path fragment (`cursor/src/.claude`) instead of a real project — 97.9% `type=fact`, 77.6% byte-identical to their own title (zero elaboration). Real content (verified by sampling), not hallucinated, but the single largest "project" bucket in the corpus, diluting unscoped search with generic dev-boilerplate phrasing. |
| **After** | Soft-hidden via `superseded_by` (same reversible mechanism these rows already survived once under an earlier quarantine) rather than deleted. Backed up per-row before mutating. |
| **How** | `brain/tools/hide_untraceable_bad_project_facts.py`, run against production. |
| **Why** | User explicitly asked whether to "just get rid of them" given no traceable project/context link exists; settled on soft-hide over hard delete per the project's zero-data-loss default. |

---

### 3.11 `442658c` — Drop the corpus save-threshold barrier; synthesize real content for Write/Agent hook captures (2026-11-03)

| | |
| --- | --- |
| **Status** | `shipped` |
| **Before** | `corpus_barrier.py`'s cubic threshold silently blocked every `write_source`/`edit_group` `PostToolUse` save once the corpus passed ~18k memories (threshold rose above both action types' fixed confidence) — contradicting the append-only cognitive-architecture design and explaining why Claude Code's hook-captured saves had gone quiet relative to Cursor's MCP-rule-driven saves. Separately, Write-tool hook saves were a mechanical "Created X, preview: &lt;raw 500 chars&gt;" dump with no synthesis, unlike Edit's already-LLM-synthesized `edit_group` saves. |
| **After** | `corpus_barrier.py` removed entirely (module + every call site in `post_tool_use.py`/`session_end.py`/`session_ingest.py`); four dead top-level duplicate hook files deleted (`brain/post_tool_use.py`, `brain/action_state.py`, `brain/session_end.py`, `brain/corpus_barrier.py` — confirmed unreferenced by any live import or `.claude/settings.json` at the time). Added `_summarize_write` mirroring `edit_group`'s LLM-synthesis pattern; extracted the shared LLM-call/JSON-parse/fallback mechanics into `action_state.llm_json_title_summary` so both callers only own their own prompt text. |
| **How** | `brain/hooks/post_tool_use.py`, `brain/hooks/action_state.py`, `brain/hooks/session_end.py`, `brain/core/session_ingest.py`; deletions above. |
| **Why** | Explicit owner decision: "every agent should work with brain just like cursor agents do... the corpus barrier is against the cognitive brain design." Starvation was verified in production (file_path coverage 0/251 → 27/58 after the fix) before and after, not assumed. |
| **Bug found during this change** | The shared `llm_json_title_summary` helper discarded a valid `summary` whenever only `title` was missing from the LLM response (`if not title: return None` ran too early). Fixed by removing that early return; each caller now applies `title or fallback_title` independently per field. Regression test: `test_summarize_write_uses_summary_even_when_title_missing`. |

**Note (added 2026-11-04):** `fd252eb` (§3.16, same day) separately recorded a "hooks are off, MCP-only like Cursor" decision in `AGENTS.md`/`CLAUDE.md` — but this repo's own project-level `.claude/settings.json` was never changed to match, and still wires these exact hook files live. See §4's 2026-11-04 entry for the correction.

---

### 3.12 `6a2d1bc` — Backfill entity links onto superseded (older) layer rows, G9 (2026-11-03)

| | |
| --- | --- |
| **Status** | `shipped` (live DB mutation via golden-path API) |
| **Before** | `backfill_entities.py` always skipped superseded rows outright, so old layers of a real supersede chain couldn't be traced or stacked — 0 of 1,780 old-layer rows had any entity edge (spec §8.6) even though 1,120 of their replacements did. |
| **After** | Added `select_superseded_true_layers` + `--superseded-layers`, selecting exactly the superseded rows that are real history (`superseded_by` resolves to another existing memory row, not a `quarantine:*`/`hidden:*` tag string overloading the same column). Ran live via the existing golden-path `POST /link-entities`: 1,484 of 1,781 true-layer rows (83.3%) now have an entity edge, up from 0. |
| **How** | `brain/tools/backfill_entities.py`. |
| **Why** | Closes gate **G9**. Unblocks testing the entity-based "same subject" detection tier against real old-layer data — a G8 prerequisite. |

---

### 3.13 `339d96e` — Automatic regression gate + safe rollback for bulk fact backfill runs, G5 (2026-11-03)

| | |
| --- | --- |
| **Status** | `shipped` |
| **Before** | The spec described `backfill_batches` as "already gated," but Python never actually wired it: `start_backfill_batch`/`finish_backfill_batch` were only ever called from Rust tests, `backfill_facts.py` never inserted a batch row, and the documented rollback command (missing `--rollback-baseline`) never triggered the gate. Separately, `rollback_batch` deleted facts via raw SQLite, which never evicts `brain_api`'s in-process vector index — a "successful" rollback would keep serving deleted facts until a restart; and a failed delete after the SQLite clear was already committed left no signal a rollback was half-done. |
| **After** | `regression_gate()` wraps the four bulk modes (`--all`/`--from-db`/`--from-perplexity`/`--from-cursor-db`, not `--file`'s small session-hook-triggered batches): captures a trusted-gold recall baseline once per fresh batch, reuses it across `--batch-id` retries, skips on `--dry-run`/small `--limit`, auto-rolls-back on a >0.05 recall drop. `rollback_batch` now deletes through the live `POST /delete` API (index-consistent) and raises with a clear retry message on partial failure (naturally retriable — fact IDs are re-read fresh from `curation_events` every call). `salience_weights()` gained named constants mirroring `brain.rs:437` exactly, plus a locking test, so an accidental edit to this third independent copy of the production salience formula fails loudly. |
| **How** | `brain/tools/backfill_facts.py`. |
| **Why** | Closes gate **G5**. Curator/backfill runs can otherwise silently regress retrieval with no before/after check. |

---

### 3.14 `ac59605` — Correctness bugs found by code review: MCP scripts, migrate.rs, episodic-leak check (2026-11-03)

| | |
| --- | --- |
| **Status** | `shipped` |
| **Before** | `brain/mcp/memory_consolidation.py` ran 9 real `save()` calls unconditionally at module scope — any future `import` would silently re-insert hardcoded personal/project content into whatever brain the importer points at. `brain/mcp/save_memory.py` posted to `/api/v1/memory` (a path the Rust API never registers — only `/save`), sent `tags` as a raw string where `SaveRequest` expects `Vec<String>`, and sent an empty `project` string bypassing the server default — would 404/fail on every real invocation. `migrate.rs`'s `parse_memory_source` had no match arm for `"hermes"` despite `types.rs` defining `MemorySource::Hermes`, silently falling through to `CursorHistory`. `run_cleanup.py`'s episodic-leak check used hardcoded content-wording fingerprints from one 2026-10-21 incident instead of structural matching. |
| **After** | Both MCP scripts guarded with `if __name__ == "__main__"`; `save_memory.py`'s endpoint/tags/project bugs fixed. `migrate.rs` gained the missing `"hermes"` match arm. The episodic-leak check is now structural: tag `write`/`agent` **and** `source="claude_code_hook"` — exactly what `post_tool_use.py`'s hook always sets. |
| **How** | `brain/mcp/memory_consolidation.py`, `brain/mcp/save_memory.py`, `brain/rust/src/migrate.rs`, `brain/hooks/run_cleanup.py`. |
| **Why** | Surfaced by a forensic `/code-review` pass over the session's work so far. |
| **Near-miss caught during this fix** | The first unscoped structural leak-check version flagged ~150 unrelated live rows (an older `claw_code` tool on a different machine; a Perplexity thread whose content literally contains the word "agent"). Caught by sampling flagged rows before trusting the count; fixed by adding the `source` constraint, verified against the live DB (0 false positives after), 7 tests added. |
| **Side-effect found while testing** | `run_cleanup.py`'s own module-level block ran real BVH-dedup deletion unconditionally on import — the same bug class as `memory_consolidation.py` — discovered when testing the leak check deleted 16 live rows as a side effect. Confirmed benign (same dedup job already running automatically via the Stop hook) and guarded the same way. |

---

### 3.15 `99b2d32` — Rename `derived_from` to `extracted_by`; quarantine remediation tooling (2026-11-03)

| | |
| --- | --- |
| **Status** | `shipped` (code rename `shipped`; remediation tools `shipped` and already run live) |
| **Before** | G1's `extracted_by` wire-name rename (trustworthy-memory-contract Stage 1) was approved but not propagated through all Python call sites. Separately: the May-backfill path-fragment bug (§3.10's predecessor) had hidden 8,654 rows of real content with no way to recover ones that *did* have a resolvable project; a handful of leaked OpenRouter keys existed in live memory content; 51 confirmed content-free session stubs existed; and a 2026-10-21 regression had mis-typed 1,489 + 79 Write/Agent hook captures as `episode`. |
| **After** | `extracted_by` rename propagated through `api_client.py`, `fact_curator.py`, `fact_extractor.py`, `mcp/server.py`, `ingest_knowledge.py`, and tests. New remediation tools, all already run against production: `recategorize_quarantine_project.py` / `recategorize_generic_project_tags.py` / `recategorize_embedded_path_project.py` (recover real projects where a session sibling resolves one, else keep the bucket label honest); `redact_leaked_openrouter_keys.py`; `delete_junk_stubs.py` (51 rows, backed up first); `recategorize_episodic_traces.py` (1,489 + 79 rows fixed at the source — the exact incident §3.14's structural leak check replaces fingerprint-matching for). |
| **How** | Listed files above, all under `brain/tools/` except the rename sites. |
| **Why** | G1 completion + cleanup of known data-quality incidents found during this session's verification work. |

---

### 3.16 `fd252eb` — Record the Cursor-parity (MCP-only, no session hooks) decision (2026-11-03)

| | |
| --- | --- |
| **Status** | `shipped` as a doc, **but found stale 2026-11-04 — see correction in §4** |
| **Before** | `AGENTS.md`/`CLAUDE.md` didn't document a 2026-10-18 decision that Claude Code and Hermes should mirror Cursor: saves only via `save_memory_tool`, with session hooks and Hermes `memory.provider: brain` off. |
| **After (as written)** | Both docs updated to state hooks are off. |
| **How** | `AGENTS.md` (10 lines), `CLAUDE.md` (13 lines). |
| **Why (as written)** | Avoid automatic dedup/cleanup running alongside explicit MCP saves. |
| **Correction (2026-11-04)** | This repo's project-level `.claude/settings.json` was never actually changed to match — `SessionStart`/`UserPromptSubmit`/`PostToolUse`/`Stop` hooks are wired to `brain/hooks/*.py` there and were confirmed firing live today. The user's explicit 2026-11-03 instruction (§3.11) to restore richer hook-based saves further supersedes the 2026-10-18 intent anyway. Both docs corrected in §4 below; hooks are being kept **on** by explicit 2026-11-04 decision. |

---

### 3.17 `4f043ce` — Cognitive architecture vision, verified spec, and layer-detection experiment (2026-11-03)

| | |
| --- | --- |
| **Status** | `shipped` (docs) |
| **Before** | The owner's Perplexity design conversation and 2026-10-21 hand-drawn temporal-layer sketches existed outside the repo; no single doc verified that vision against the actual Rust implementation line-by-line. |
| **After** | `docs/architecture/cognitive-architecture-spec.md`: formalizes the vision's algebra, verifies it against the real implementation, and turns each gap into a concrete gated fix (G0–G10 — see this doc's own §10 for current status). Includes the layer-detection experiment (`docs/architecture/experiments/2026-10-21-layer-detection/`), which found no deterministic tier is precise enough to auto-stack layers (~33% precision) and that the default k-fold eval can't validate a ranking change — the two blockers §3.9's eval-harness work and §3.12's G9 backfill were built to start clearing. |
| **How** | New docs under `docs/architecture/`; `brain/rust/docs/notes.md` (the design note that directly scoped §3.13's G5 implementation). |
| **Why** | "First read and understand deeply what the cognitive brain goals and vision are" — explicit instruction before continuing further gate work. |

---

### 3.18 `a72c3c3` — Memory-atlas backend: live per-brain layout, storage, and API (2026-11-03)

| | |
| --- | --- |
| **Status** | `shipped` (pre-existing/inherited implementation; this session landed it plus its own review fixes) |
| **Before** | Atlas visualization was a static-file `atlas.json`/build pipeline, not live per-brain. |
| **After** | `atlas.rs`/`memory_atlas.rs`: live-built forest layout per brain (real memories, mention edges, hub/co-mention springs), stored per-brain in new `memory_atlas_runs`/`memory_atlas_positions` tables, served live (`GET /v1/memory-atlas/:id` with ETag, `POST` rebuild, status). `brain_atlas_import`/`brain_memory_atlas` are the CLI entry points. |
| **How** | New Rust modules + schema in `types.rs`/`store.rs`/`lib.rs` (also carries the `extracted_by`/`derived_from` field split, below). |
| **Why** | Replace the static atlas pipeline with one that reflects live brain state per-instance. |
| **This session's review fixes landed in the same (previously uncommitted) files** | `SaveRequest.extracted_by`/`derived_from` no longer errors on "duplicate field" when a request sends both keys (split into two fields + a merge method, 4 new tests); `atlas_source()` now reuses `brain_db_path()` instead of duplicating its lookup; `MemoryEvent` gained a `project` field so the SSE live feed matches the initial `/list-seeded` path; `atlas.rs`'s CSV import returns a graceful `BrainError` on a short row instead of panicking; `memory_atlas.rs` now prunes old failed rebuild runs, not just done ones. |

---

### 3.19 `197186f` — Rewrite the brain viewer: brand system, memory-atlas 3D explorer, redesigned views (2026-11-03)

| | |
| --- | --- |
| **Status** | `shipped` (pre-existing/inherited implementation; this session landed it plus its own review fixes) |
| **Before** | Brain Viewer SPA used ad hoc Tailwind utilities; the Linked tab was a bipartite entity-graph browse canvas only. |
| **After** | Full React/Vite rewrite on a token/role-based design system (`components/brand/*`, `styles/tokens.css`, self-hosted Geist/GeistMono) following a brand book derived from the owner's UI references; Tailwind/PostCSS config removed. Dashboard, Curate, Search, Eval, and Instances rebuilt on this system. The old Linked tab is replaced by **LinkedAtlas** — a live 3D explorer (`AtlasCanvas`) over §3.18's memory-atlas backend, with view-state restore across rebuilds, topic labels, and search-ranked entity lookup. |
| **How** | `brain/rust/ui/` (components, styles, views); `atlas-preview/` is a local dev harness for the atlas layout. |
| **Why** | Product-driven UI redesign; Linked's old static bipartite graph couldn't show live per-brain layout. |
| **This session's review fixes landed in the same (previously uncommitted) files** | "Undo promote" no longer silently overwrites a fact's real prior salience with a hardcoded guess for a fact promoted in an earlier session, while still showing its true promoted state (`Curate.jsx`/`FactRow.jsx` — split into an always-accurate `promoted` flag and a separately-gated `canUndo`). LinkedAtlas's Explorer now remounts on atlas rebuild instead of reusing stale entity/focus indices. Search's "Show more" fetches a bounded result set once and slices client-side instead of re-running a full embed+rank on every click. **`vite.config.js`'s `emptyOutDir` is now `false`**, matching `deploy.sh`'s own stated design — this session's own `npm run build` verification runs had been wiping the git-tracked `eval_dashboard.json` (780 lines) on every build, a config/comment mismatch already diagnosed twice before in old spec docs but never fixed; recovered via the existing `rebuild_eval_dashboard.py` tool and proved fixed by rebuilding twice more. |

---

### 3.20 `1f47fcf` — Lock-free read fast path for `/search`, G6 (2026-11-04)

| | |
| --- | --- |
| **Status** | `shipped` |
| **Before** | Every `/search` request, however trivial, serialized on the single `Arc<Mutex<Brain>>` — profiling confirmed throughput was pinned flat (~73 req/s) regardless of concurrency. |
| **After** | New `ReadPool` (`brain/rust/src/read_pool.rs`): a small fixed-size pool of independent read-only SQLite connections, checked out via a bounded channel. `Brain::search` extracted into two free functions, `rank_candidates` and `apply_type_diversity_cap`, so the fast path and the locked path share identical ranking code. `Brain.embedder` changed `Box` → `Arc<dyn EmbedderBackend>` for cheap cloning. `FastHandles` (index + embedder + read pool, behind an `RwLock`) lets `/search` bypass the `Brain` lock entirely when `graph_expand` is off, rebuilt and swapped atomically on every instance switch. |
| **How** | `brain/rust/src/read_pool.rs` (new), `brain/rust/src/brain.rs`, `brain/rust/src/store.rs`, `brain/rust/src/bin/brain_api.rs`. |
| **Why** | Closes the "profile first" half of gate **G6**; the bottleneck was verified real, not assumed. |
| **Regression test added** | `search_after_switch_reflects_new_instance_not_stale_fast_handles` — proves the fast path's handles are genuinely rebuilt on instance switch, not serving stale data from the previous instance (the exact risk this design was built around). `cargo test --lib`: 159 passed; `cargo test --bin brain_api`: 18 passed. |

---

### 3.21 `95dbe01` — Extend the G6 lock-free fast path to `/stats` (2026-11-04)

| | |
| --- | --- |
| **Status** | `shipped` |
| **Before** | `/stats` still went through `Arc<Mutex<Brain>>` even though its five queries are pure reads. |
| **After** | The five stats queries in `store.rs` extracted into connection-parameterized free functions (`count_memories_conn`, `count_sessions_conn`, etc.), mirroring §3.20's pattern, plus a `brain::compute_stats` free function both `Brain::get_stats` and the fast path call. `save_count` (in-process "saves this session" counter, not in SQLite) is now `Arc<AtomicUsize>`, cloned into `FastHandles` the same way the embedder already is — a real alias, not a snapshot. |
| **How** | `brain/rust/src/store.rs`, `brain/rust/src/brain.rs`, `brain/rust/src/lib.rs`, `brain/rust/src/bin/brain_api.rs`. |
| **Why** | Same G6 rationale, applied to the other hot read endpoint. |
| **Regression test added** | `stats_save_count_reflects_saves_via_fast_path` — proves a write through the normal `/save` path stays visible to `/stats` regardless of which path (locked or fast) serves the read. `cargo test --lib`: 159 passed; `cargo test --bin brain_api`: 19 passed. |

---

### 3.22 `84ae1fb` — Move G6 fast-path SQLite/embedding work off the async runtime (2026-11-04)

| | |
| --- | --- |
| **Status** | `shipped` |
| **Before** | §3.20/§3.21's fast paths called `pool.acquire()` and the blocking `rank_candidates`/`compute_stats` work directly inside their `async fn` handlers — unlike every other handler in `brain_api.rs` — blocking a Tokio worker thread for the duration of a SQLite query + embedding inference, which reduces real concurrency independent of the lock removal itself. |
| **After** | Both fast paths now wrap their blocking work in `tokio::task::spawn_blocking`, matching the file's established convention. |
| **How** | `brain/rust/src/bin/brain_api.rs`. |
| **Why** | Found via live profiling after restarting the service: CPU usage during a concurrent `/search` burst climbed to 500–800% (multiple cores genuinely busy at once) — direct proof the lock removal is real, not just theoretical — but absolute throughput only moved ~73→85 req/s. Investigated with Apache Bench (not just an ad hoc Python harness, which turned out to have its own confounds) plus CPU sampling, and found this missing convention as a real, fixable gap. |
| **Also tried and reverted** | Widened the read pool from 4 to 16 connections to test whether pool size was a secondary ceiling; this made `/stats` *worse* under concurrency (45 → 38 req/s) from real contention on concurrent full-table scans. Reverted rather than keep an unproven "optimization." Remaining throughput ceiling (~85 req/s) is governed by genuine CPU cost of ONNX embedding inference, not an artificial lock — a different, expected kind of limit, out of scope for G6. `cargo test --lib`: 159 passed; `cargo test --bin brain_api`: 19 passed. Deployed live via `launchctl kickstart`; verified no data loss (23,538 memories intact) after restart. |

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

### 4.N `(uncommitted)` — Correct the stale "hooks are off" claim; document §3.9–§3.22 (2026-11-04)

| | |
| --- | --- |
| **Status** | `WIP` |
| **Before** | `AGENTS.md` (three places) and `CLAUDE.md` stated Claude Code session hooks are absent/removed, mirroring Cursor's MCP-only save path — per `fd252eb` (§3.16). This was never true for this repo: its **project-level** `.claude/settings.json` has always wired `SessionStart`/`UserPromptSubmit`/`PostToolUse`/`Stop` to `brain/hooks/*.py`, confirmed firing live in the very session that found this (the `[BRAIN] Relevant memories...` SessionStart message). §3.11's corpus-barrier removal had already been actively editing these same live hook files without anyone noticing the docs disagreed. Also: `docs/architecture/cognitive-architecture-spec.md`'s gate table hadn't been updated since 2026-10-21 and still listed G5/G6/G9 as open. |
| **After** | Asked the owner explicitly which side was correct (keep hooks on and fix the docs, vs. disable hooks to match the docs); owner chose **keep hooks on, fix the docs**. `AGENTS.md` and `CLAUDE.md` corrected to state hooks are live via the project-level settings file, distinct from the global one. Gate tracker updated: G5/G6/G9 marked shipped with commit references and result summaries; G10 checked and found already satisfied (not new work); G0/G8 confirmed still open. This changelog itself extended with §3.9–§3.22 (the full commit-by-commit record of this session's work) and this entry. |
| **How** | `AGENTS.md`, `CLAUDE.md`, `docs/architecture/cognitive-architecture-spec.md`, `docs/CHANGELOG-SHARED-CODE-BRAIN.md`. |
| **Why** | Explicit request: "make complete and structured documentation of each job done so far, plus update existing documentation if needed." Found the hooks conflict while verifying rather than restating docs from memory (this doc's own §6 principle — "no guessed history"). |

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

**Last verified against git:** 2026-07-28 (HEAD `6e75315` + WIP listed in §4) for §§1–3.8; 2026-11-04 (HEAD `84ae1fb` + WIP listed in §4's final entry) for §3.9 onward.
