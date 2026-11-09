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

### 3.23 `205dbfc` — salience_pinned: gate salience_w on deliberate human pins, G0 (2026-11-04)

| | |
| --- | --- |
| **Status** | `shipped` (schema change, deployed live) |
| **Before** | The live `salience_w` formula (`brain.rs:437`) applied to every memory's `salience` column, which conflated two signals: the LLM extractor's one-time guess at save time (Phase 6 calibration found this anti-correlates with true quality — curator-`IGNORE`d facts average higher salience than `ADD`ed ones) and a human's deliberate "Promote" in Curate.jsx (`PATCH /memories/:id`, trustworthy, actively used — 19 live rows at exactly `salience=1.0`). The spec's G0 recommended an A/B before deciding, using `retrieval_eval_kfold.py` — the same circular self-matching eval §3.9 had already flagged and replaced. |
| **After** | A/B run instead against the trustworthy usage-mined gold set (`gold_mined.jsonl` via `retrieval_eval.py`, extended with a new `--salience-neutral` flag and a request-scoped `SearchFilter.salience_neutral` override — default off, never affects real traffic). Results: recall@k is a ceiling either way (1.0 on this 20-query set) but `mean_mrr` is marginally better neutral (0.6634) than live (0.656), consistent with Phase 6's finding. Rather than a blind revert (losing the real Promote feature) or leaving the known-bad signal live, added `salience_pinned` (new column, default false, best-effort backfilled true for existing `salience=1.0` rows): `salience_w` now applies only when a memory is pinned; the >99% LLM-assigned majority is neutral. `PATCH /memories/:id` gained `salience_pinned` (defaults true when omitted — a PATCH is always deliberate today); Curate.jsx's Promote sends `true`, Undo sends `false` explicitly. |
| **How** | `brain/rust/src/types.rs`, `brain/rust/src/brain.rs`, `brain/rust/src/store.rs`, `brain/rust/src/migrate.rs`, `brain/rust/src/bin/brain_api.rs`, `brain/api_client.py`, `brain/tools/retrieval_eval.py`, `brain/rust/ui/src/views/Curate.jsx`. |
| **Why** | Closes gate **G0**. The real question the owner asked mid-implementation — "is the calibration wrong?" — led to separating the two conflated signals instead of patching the symptom. |
| **Live deploy verification** | Took a fresh DB backup before restarting. Post-migration: 23,601 memories intact, 19 rows backfilled pinned, 0 `salience=1.0` rows left unpinned. One restart stalled ~6 minutes in the same macOS first-launch binary-verification step seen (and resolved on its own) twice earlier the same session; killed and let launchd relaunch, which came up clean in under 5s on retry — flagged to the owner rather than assumed benign given it ran long. `cargo test --lib`: 160 passed; `cargo test --bin brain_api`: 20 passed. |

---

### 3.24 `8303cfe` — source_quality_w: ship the orphaned G2 reference, drop the generic status enum (2026-11-05)

| | |
| --- | --- |
| **Status** | `shipped` |
| **Before** | The gate table's G2 line ("approve `status`/`source_quality` columns, or defer") was an orphaned reference to the original Perplexity vision conversation, carried into the 2026-10-16 design doc and then into this spec's gate table without ever being reconciled against the 2026-10-21 temporal-layer revision. Neither field appeared anywhere in the authoritative diagram. Separately, `superseded_by` was found to be overloaded with `quarantine:*`/`hidden:*` tag strings on 7,402 rows plus 59 dangling (deleted-target) pointers — a real blocker to ever walking it as a clean layer link (G7/G8). |
| **After** | Traced `source_quality`'s actual origin (Perplexity's own critique of the owner's design, not something the owner asked for) and re-evaluated it on merit rather than provenance: it answers a question neither `salience_pinned` (G0) nor layer confidence (G8) does — not "was this pinned" or "has this been superseded," but "how much should I trust the pipeline that produced it." Shipped as `source_quality_w(source)` (`brain.rs`) — a pure function of the already-stored `source` enum, needing no schema column. Exposed on every `SearchResult`; gated behind `SearchFilter::apply_source_quality` (default off) so it never affects real traffic, mirroring G0's validate-before-wiring discipline exactly. A/B on `gold_mined.jsonl` was inconclusive: 93.7% of the corpus is `claude_code_session` alone (97.8% combined with `cursor_history`), so this particular gold set never surfaces a query where a competing tier (`obsidian_books` 1.2%, `perplexity` 0.7%) is actually in play. `status` was **not** implemented as a generic enum — the real problem (the quarantine overload above) is now tracked as cleanup needed before G7/G8, not its own gate. |
| **How** | `brain/rust/src/brain.rs`, `brain/rust/src/types.rs`, `brain/rust/src/bin/brain_api.rs`, `brain/api_client.py`, `brain/tools/retrieval_eval.py`, plus matching updates to `docs/architecture/cognitive-architecture-spec.md` and `cognitive-architecture-diagram.md`. |
| **Why** | Closes the orphaned half of gate **G2**. The owner pushed back on dismissing `source_quality` by provenance alone and asked for the actual merits — this is the result of that discussion. |
| **Verification** | `cargo test --lib`: 161 passed (new: `source_quality_is_always_exposed_but_only_applied_when_requested`). `cargo test --bin brain_api`: 20 passed. Live-deployed (no schema change, no backup needed); confirmed `source_quality` field correctly returns 0.85 for `claude_code_session` results in production. |

---

### 3.25 `7db2915` — reclassify dangling superseded_by pointers, add resolved_supersedes (2026-11-05)

| | |
| --- | --- |
| **Status** | `shipped` (data fix + prep code, no live behavior change) |
| **Before** | 59 live rows had `superseded_by` set to a UUID that no longer resolved to any existing memory — their real successor had been deleted by a later cleanup pass. Every existing quarantine/cleanup tool (`hide_untraceable_bad_project_facts.py`, `quarantine_path_fragment_facts.py`, `recategorize_generic_project_tags.py`, `retag_path_fragment_projects.py`) explicitly skips rows where `superseded_by` is already non-null, so these 59 fell through every pass — sampled and confirmed same mechanical session-dump noise, same `cursor`/`src`/`frontend` project pattern as the already-quarantined May-2026 backfill-bug rows, just excluded by every `WHERE` clause written so far. |
| **After** | `brain/tools/reclassify_dangling_superseded.py` relabels them with the same `quarantine:*` sentinel convention the rest of the corpus already uses (backed up to `junk_scrub_backups/` first). No visibility change — both the old dangling UUID and the new sentinel were already excluded by `SearchFilter::exclude_superseded`'s non-null check. `store.rs` gains `resolved_supersedes(conn, superseded_by)` — returns the real target id only if it's non-empty, not a `quarantine:*`/`hidden:*` sentinel, and actually resolves to an existing row. Deliberately did **not** touch the 7 existing scripts or their string convention — rewriting working tools that already partially preserve quarantine reasons in `tags` wasn't justified for a feature (G7/G8) not yet being built. |
| **How** | `brain/tools/reclassify_dangling_superseded.py` (new), `brain/rust/src/store.rs`. |
| **Why** | Closes the `superseded_by` cleanup identified while scoping G2 — a real prerequisite for G7/G8 to ever safely walk supersede chains as layer links. |
| **Verification** | `cargo test --lib`: 163 passed (new: `resolved_supersedes_none_for_absent_or_sentinel_or_dangling`, `resolved_supersedes_some_for_a_real_existing_row`). `cargo test --bin brain_api`: 20 passed. Live DB verified post-fix: the "other string value" `superseded_by` category dropped to 0; total memory count unchanged (23,694) confirming no rows lost. |

### 3.26 `1f37ffe` — switch to ornith-35b-eval, force think:false on every Ollama call (2026-11-06)

| | |
| --- | --- |
| **Status** | `shipped` |
| **Before** | `OLLAMA_SUMMARIZE_MODEL` defaulted to `qwen3-coder:30b`. None of Brain's Ollama call sites (`entity_extractor.py`, `fact_extractor.py`, `fact_curator.py`, `core/summarizer.py`, the Rust `OllamaClient`) sent `"think": false`. |
| **After** | Default switched to `ornith-35b-eval:latest`; every one of those call sites now sends `"think": false` unconditionally. Without it, a reasoning model's output lands in `message.thinking` instead of `message.content`, which Brain's JSON parsers read as empty. |
| **How** | `brain/config.py`, `brain/core/summarizer.py`, `brain/ingest/entity_extractor.py`, `brain/ingest/fact_curator.py`, `brain/ingest/fact_extractor.py`, `brain/rust/src/summarizer.rs`. |
| **Why** | `qwen3-coder:30b` → `ornith-35b-eval` was a deliberate model swap; without the `think:false` guard the new model would silently return empty content on every call. |
| **Verification** | Verified live: 6/6 manual runs across entity-extraction and title/summary prompts parsed cleanly, 0.6–1.0s each, faster than `qwen3-coder`'s benchmarked ~4s. Known caveat recorded in the code comment: `ornith`'s llama-server runs `-np 1` (one concurrent request), so Brain's calls queue behind any other active use of the same model — this mattered later, directly limiting §4.8 below. |

### 3.27 `be88698` — extract calendar/project/file/entity lookups into `lookups.rs`; event-time axis + project pinning (2026-11-06)

| | |
| --- | --- |
| **Status** | `shipped` |
| **Before** | `store.rs` owned `memories_in_calendar` and friends directly, growing indefinitely; calendar queries could only use ingest `timestamp`, not `event_time`; no way to pin a specific memory as a project's "brief". |
| **After** | New `brain/rust/src/lookups.rs` holds calendar/project-brief/file/entity lookups. Calendar queries take a `TimeAxis` (`stored` vs `event`) — added directly in response to a correction earlier in this session (falling back to raw `sqlite3` for a date-scoped question Brain's own tools couldn't yet answer). Added project-brief pinning: new `project_pins` table, `pin_project_brief`/`unpin_project_brief`, exposed as MCP tools. New `idx_memories_event_time` index backs the event-axis queries. `brain.rs` gained thin delegating methods; `brain_api.rs`/`mcp/server.py`/`api_client.py` wire the new pin/unpin routes and the `when` param on the existing calendar endpoint, all behind the pre-existing `authorize_and_rate_limit` guard. |
| **How** | New `brain/rust/src/lookups.rs`; edits to `store.rs`, `lib.rs`, `brain.rs`, `bin/brain_api.rs`, `mcp/server.py`, `api_client.py`. |
| **Why** | Consolidate a growing set of "semantic search can't answer this" lookups into one module before it kept sprawling inside `store.rs`, and close the specific date-axis gap found moments earlier in the same session. |
| **Verification** | `cargo check`/`cargo test` clean both before and after (one pre-existing partially-staged hunk from before this session rode along into the commit — see commit message note; net diff across both commits is correct and tested). |

---

### 3.28 `206c7d6` — Surface G7 `similar_to` links in the UI; fix a dedupe bug and a crash (2026-11-08)

| | |
| --- | --- |
| **Status** | `shipped` |
| **Before** | `/v1/related` (G7, spec §7.3) and the G7 `similar_to` backfill existed server-side (landed the prior session, §4.6-era work) but nothing in the UI ever called it — no "related memories" surfaced anywhere, in the reading pane or the atlas graph. |
| **After** | `MemoryReading.jsx` gained a `Related` section (new `api.js::getRelated`) beside the existing entity-based `Linked` section. `memory_atlas.rs`'s `build_forest` now also reads `similar_to` out of `memory_links` and draws it as a third, dimmer ribbon tier in `AtlasCanvas.jsx`, alongside the forest/entity-mention tiers — decorative only, not fed into `layout()`'s spring simulation, same treatment as the existing "extra" tier. Ran the G7 backfill live: 121,873 raw pairs → 86,099 deduped `similar_to` rows across 14,663 memories. |
| **Bugs found and fixed in the same pass** | (1) `related_memories()` (`lookups.rs`) returned the same neighbor twice for any mutual top-k pair, since `memory_links` stores both directions and the query matched both without deduping by resolved neighbor id — fixed with `GROUP BY` + `MAX(weight)`, regression test added. (2) Switching to a brain instance with only a stored reference dataset (no memory atlas) blanked the whole UI: `AtlasCanvas` is shared by both atlas types, and `ReferenceAtlas` decodes its edges as a `Uint32Array` (`atlasRef.ts`), which has no `.concat` — the first pass at the three-tier ribbon list called `.concat` unconditionally. Extracted `concatPairs()` (`linkRibbons.js`), which only builds a new array when there's something to add and uses spread (safe on both plain and typed arrays) when it does; `linkRibbons.test.ts` pins the `Uint32Array` case so this can't silently regress. |
| **How** | `brain/rust/src/lookups.rs`, `brain/rust/src/memory_atlas.rs`, `brain/rust/ui/src/api.js`, `brain/rust/ui/src/components/brand/MemoryReading.jsx`, `brain/rust/ui/src/lib/atlas.ts`, `brain/rust/ui/src/views/linked/AtlasCanvas.jsx`, `LinkedAtlas.jsx`, `linkRibbons.js` (+ new `linkRibbons.test.ts`). |
| **Why** | A real, already-built capability (G7) was sitting completely unused; found while auditing whether `views/linked` needed updates after the prior session's ranking work. |
| **Verification** | `cargo test`: 213 passed, 0 failed (up from 211). `npm test`: 63 passed (up from 59). Rebuilt and redeployed; re-checked both atlas types live (main's memory atlas with 86,099 `similar_edges`, and the separate `ATLAS` instance's stored reference dataset) after each fix, not just in theory. |

### 3.29 `c5601c6` — Correct the spec/diagram to match what G8 actually shipped (2026-11-08)

| | |
| --- | --- |
| **Status** | `shipped` |
| **Before** | `cognitive-architecture-spec.md` §8.8 still said superseded memories "stay hidden" and `use_layer_confidence` was "opt-in, not the default" — true the morning of 2026-11-06, stale by that afternoon once `808988c`/`f5d2e49`/`c13ccb6`/`4e1135a` (prior session) flipped both flags to default-on and resolved §8.8 open question 1. This exact drift led to incorrect status being reported in this session's own conversation before being caught and re-verified directly against the live API and commit history — not a hypothetical risk, an observed one. |
| **After** | Both docs corrected with a dated 2026-11-08 revision note: `use_layer_confidence` and `include_superseded_with_lineage` both default `true`; §8.8 Q1 marked resolved; §10's G8 row updated to `shipped`. Also struck through **G1** in the spec's gate table: `extracted_by` has been the live field (`derived_from` a legacy deserialization alias only, proven by a test) since before this spec existed, but the row was never marked done — flagged once already (§3.24-era G2 revision) and still not fixed until now. |
| **How** | `docs/architecture/cognitive-architecture-spec.md`, `docs/architecture/cognitive-architecture-diagram.md`. |
| **Why** | Keeping the living spec honest is the whole point of this document's own discipline (§9's maintenance rule) — and this specific drift caused a real, observed mistake in-session before being corrected. |

### 3.30 `090b1e9` — Remove `MAX_FIX_DISTANCE`, dead since the V-36 fix (2026-11-08)

| | |
| --- | --- |
| **Status** | `shipped` |
| **Before** | `action_state.py`'s `pop_matching_error()` no longer did proximity-based fallback matching (a prior-session security-audit fix replaced it with a strict "edited path appears in the error text" check), but `MAX_FIX_DISTANCE` stayed behind, unused by any logic path, referenced only in test comments explaining the old buggy behavior the regression tests guard against. |
| **After** | Constant removed. |
| **How** | `brain/hooks/action_state.py`. |
| **Why** | Found while re-verifying which architecture gates were actually open — this session initially mis-reported G5/G6/V-36 as still-open based on an incomplete grep, then re-verified properly and found V-36 (and the dead constant left behind by its fix) along the way. |
| **Verification** | `pytest brain/tests/test_smart_capture.py`: 21 passed. Full suite: 529 passed (unchanged baseline failures). |

### 3.31 `be00e62` — API-routed existence-check/supersede for `ingest_knowledge.py` (2026-11-08)

| | |
| --- | --- |
| **Status** | `shipped` |
| **Before** | `ingest_knowledge.py`'s existence-check and supersede were direct-SQLite (`_db_path()` against `BRAIN_DB_PATH`) — silently wrong on any client machine that isn't co-located with `brain.db`, exactly the MacBook/iMac-as-API-client topology AGENTS.md documents. This work existed, complete and tested, but sat uncommitted in an abandoned agent-dispatch worktree (`.claude/worktrees/agent-afd05a6fd45f5762b`) since the knowledge-type feature shipped (`e40bd67`) — found while investigating 3 leftover worktrees flagged earlier in this session as "probably safe to clean up." |
| **After** | Both existence-check and supersede now go through `brain.api_client`: new `GET /knowledge/existing` (`brain_api.rs`) + `Brain::knowledge_chunks_for_file` + `MetadataStore::get_active_knowledge_by_file_path`, reading the live `extracted_by` column — fixed from the original patch's stale `derived_from` reference, since G1 (§3.29 above, and originally §3.15) retired that column from new reads before this work was written. `PATCH /memories/:id` gains `superseded_by` alongside the existing `salience`/`salience_pinned` fields (merged, not replaced — G0's `salience_pinned` work had touched the same `PatchMemoryRequest`/`patch_memory` code in the meantime, so the old patch's 4 rejected hunks were reconciled by hand, not force-applied). `MetadataStore::mark_superseded` now returns `bool` (was `()`) so callers can tell whether `old_id` actually matched. `ingest_knowledge.py` gains a `--on-db-host` guard refusing a non-loopback `BRAIN_API_URL` by default — this is a bulk corpus job, and running it against a remote `brain_api` from a stale env var is the exact footgun the guard exists for. |
| **How** | `brain/api_client.py`, `brain/rust/src/bin/brain_api.rs`, `brain/rust/src/brain.rs`, `brain/rust/src/store.rs`, `brain/tests/test_ingest_knowledge.py`, `brain/tools/ingest_knowledge.py`. |
| **Why** | Real, tested, valuable work was about to be lost to an abandoned worktree. Verified safe before porting, not assumed: the work's own tests passed at its original base commit once isolated from an unrelated pre-existing startup panic at that same old commit (reproduced the identical panic on a clean checkout of `e40bd67` with none of this diff applied, confirming it was never this work's fault). |
| **Verification** | `cargo test`: 234 passed, 0 failed. `pytest`: 537 passed, the same 13 pre-existing/unrelated failures unchanged. |

### 3.32 `8101d58` — Save the knowledge-type release runbook, marked historical (2026-11-08)

| | |
| --- | --- |
| **Status** | `shipped` (docs only) |
| **Before** | A second abandoned worktree (`agent-a455f2d6a1b2614ea`) held an uncommitted, never-saved runbook for merging/deploying the knowledge-type feature — plus a 3-line `test_deploy_parity.py` metadata-message addition. |
| **After** | Runbook saved to `docs/deploy/knowledge-type-release-runbook.md` with a header marking it historical (the merge and Studio deploy it describes are both already done, re-done many times over by this session's own repeated rebuild/redeploy cycles) — kept as a record and a template for the next similar ship, not an outstanding TODO. The `test_deploy_parity.py` metadata change was deliberately **not** ported — it only mattered for the `~/Documents/AI` live hook tree, which the owner said this session to leave alone. |
| **How** | New `docs/deploy/knowledge-type-release-runbook.md`. |
| **Why** | Same "don't lose real work to an abandoned worktree" motivation as §3.31, applied to documentation instead of code. Incidentally, the runbook's own pre-merge checklist independently documented and explained a Tokio runtime panic (`reqwest::blocking` + `#[tokio::main]`, debug-build-only) this session had separately spent time isolating — good independent confirmation of that diagnosis. |

### 3.33 `b9a0916` — Recover `bench_knowledge.py`, the knowledge-type calibration harness (2026-11-08)

| | |
| --- | --- |
| **Status** | `shipped` |
| **Before** | A third abandoned worktree (`agent-ad057e5a597904337`) held `bench_knowledge.py` (quality/latency/freshness/distance-band metrics for the knowledge memory type, with the Rust↔Python `KNOWLEDGE_TAU_CLOSE`/`_FAR` mirror asserted at runtime, not assumed) plus a 42-row gold eval set — both untracked, never committed. |
| **After** | Both files copied in unchanged — unlike §3.31, this one applied with zero code changes needed: every piece of current-`main` surface area it depends on (`brain.rs`'s tau constants, `mcp/server.py::_grounding_hint`, `/search`'s request/response shape, `/save`) was unchanged since this was written. |
| **How** | New `brain/tools/bench_knowledge.py`, `brain/eval/gold_bench_nonknowledge.jsonl`. |
| **Why** | Third and last of the abandoned-worktree recoveries this session. |
| **Verification** | Not just read — actually run: built a disposable `brain_api` instance (copied `brain.db`, mock embedder, port 8790, since the script's own docstring says "never the live :8787 service") and ran all four subcommands (`gold`, `quality`, `latency`, `freshness`) plus `distances` with missing optional query files, confirming each executes cleanly against today's API and produces well-formed output. Instance and DB copy torn down after. |

### 3.34 `0d0841a` — Add an explicit CORS allowlist to `brain_api` (2026-11-08)

| | |
| --- | --- |
| **Status** | `shipped` |
| **Before** | `docs/SECURITY_AUDIT_2026-11-05.md` finding #6 (MEDIUM): no CORS headers configured at all. |
| **After** | Hand-rolled CORS middleware in `brain_api.rs` — `tower-http` was not a dependency and wasn't added just for this (the project's own conventions favor the smallest footprint over a new crate for one feature). Explicit allowlist: the dashboard's own origins (`127.0.0.1`/`localhost:8787`) plus any RFC1918-private IPv4 on `:8787` (`std::net::Ipv4Addr::is_private()`, no new dependency), since `BRAIN_API_BIND=0.0.0.0` is deliberate — other machines on the LAN are meant to reach this API. Never echoes an arbitrary `Origin`, never emits `"*"`. Handles `OPTIONS` preflight. |
| **How** | `brain/rust/src/bin/brain_api.rs` only. |
| **Why** | One of 9 actionable findings from a dedicated 2026-11-05 security audit (`docs/SECURITY_AUDIT_2026-11-05.md`) that this session discovered were still open — a **different**, more specific document than the `brain/rust/SECURITY_AUDIT_REPORT.md`-derived findings §4.10 already describes as "7 of 8 closed"; the two reports don't share a numbering scheme and shouldn't be conflated (see the note after §4.11 below). |
| **Verification** | 8 new tests (allow/deny/wildcard-never/preflight, both allowed and disallowed). Full suite: 257 passed, 0 failed (was 249). Verified live against a disposable instance: allowed origins get the header back, disallowed origins and requests with no `Origin` at all get nothing. |

### 3.35 `5e27710` — Remove placeholder keys and a leaked LAN IP, enable auth by default (2026-11-08)

| | |
| --- | --- |
| **Status** | `shipped` (code/docs/config); **one step still open, owner action required** — see below |
| **Before** | Re-auditing `docs/SECURITY_AUDIT_2026-11-05.md` finding-by-finding against live state (not the commit message's claim) found 8 of 9 actionable findings still open, including both the CRITICAL ones: the live, installed plist actually had `BRAIN_API_BIND=0.0.0.0`, `BRAIN_API_KEY=local-dev-key`, `BRAIN_API_AUTH_REQUIRED=0` — exactly the audited vulnerable state, deployed and running, the whole time this session had been rebuilding and restarting it. The repo is **public** (`ocreamer888/brain`, confirmed via `gh repo view`), raising the real stakes of a committed placeholder key and an exposed LAN IP well past "best-practice nit." |
| **After**, finding by finding (`docs/SECURITY_AUDIT_2026-11-05.md` numbering): **#1/#5** — `local-dev-key` removed from every committed file where it could be mistaken for a real value (`README.md`, `.mcp.json(.example)`, `brain/.env.example`, several docs, two `merge_macbook_brain.py` copies, one `.scratch` script now reading `BRAIN_API_KEY` from env with that string only as a last-resort fallback). One dated historical deploy-log entry in `docs/deploy/README.md` and the audit report itself deliberately left as-is — rewriting a historical record or the evidence a finding cites isn't "fixing" it. **#2** — confirmed with the owner this is deliberate (multi-machine LAN access per AGENTS.md); left at `0.0.0.0`, documented inline as intentional, auth is the real boundary. **#3** — `docs/deploy/com.brain.api.plist` (committed template) now defaults `BRAIN_API_AUTH_REQUIRED=1` and `BRAIN_API_KEY=REPLACE_ME`. **#7** — OpenRouter example-key pattern fixed in 5 files (closed by a parallel subagent). **#8** — AGENTS.md's literal LAN IP replaced with `<studio-lan-ip>`, pointing at the gitignored `brain/.env` as the real source; scoped narrowly to just the IP, not AGENTS.md's other operational detail (closed by a parallel subagent). **#9** — `.claude/settings.local.json` overly-broad `Read` grants narrowed (gitignored file — local hygiene, not a public leak; closed by a parallel subagent). `docs/RUN_BRAIN_API_WITH_KEY.md`'s viewer note was found actively wrong while fixing its key examples (claimed auth works fine in the browser) and corrected to match real, already-shipped behavior (key only injected when auth is off, by design, since the static-`index.html`-leak fix). |
| **How** | `brain/rust/src/bin/brain_api.rs` (CORS, §3.34), `.mcp.json(.example)`, `README.md`, `AGENTS.md`, `brain/.env.example`, `docs/deploy/com.brain.api.plist`, `docs/{BUILD-AND-CUTOVER,ENTITY_EDGE_GRAPH,PHASE4_API,RUN_BRAIN_API_WITH_KEY}.md`, `docs/deploy/README.md`, two `merge_macbook_brain.py`, one `.scratch` script, two bootstrap scripts, `CLAUDE_CODE_SESSIONS.md`. Four of these findings (#6 CORS, #7, #8, #9) were closed by parallel subagents dispatched for the self-contained, lower-risk pieces while the key/auth/bind work (real blast radius, needed holistic testing) was done directly. |
| **Why** | Explicit instruction: "run agents to close each of these findings maximizing excellence." Found the live/template plist discrepancy, the two-separate-audit-documents conflation, and the public-repo status by direct verification rather than trusting an earlier summary — each of which changed what "closing" a finding actually required. |
| **Known, accepted gap** | Confirmed with the owner: once auth is required, the dashboard's own fetches `401` until a real login/session flow exists — not built here, a deliberate scope boundary, not silently glossed over. |
| **Owner action still required** | The live, installed plist (`~/Library/LaunchAgents/com.brain.api.plist`) and `brain/.env` (gitignored, holds the real key) are **not** touched by this entry — generating and placing the actual secret value is a manual step for the owner, not something this assistant could do: the sandbox explicitly blocked both writing a generated key to a file and reading one back, twice, by design (credential materialization). Exact commands to finish this were handed to the owner directly in-session, not recorded here since they embed no secret themselves. |
| **Verification** | `cargo test`: 257 passed, 0 failed. `pytest`: 537 passed, 13 pre-existing failures unchanged. `plutil -lint` clean on the edited template plist. |

**Note on §4.10 below:** that entry's "7 of 8" refers to `brain/rust/SECURITY_AUDIT_REPORT.md`'s own finding list (key leak via `/static`, rate-limiter header trust, secret-file patterns, transcript-path safety, reflection delete cap, stream query-string key, redact dry-run backup, export-clean flag) — a **different** document from `docs/SECURITY_AUDIT_2026-11-05.md` (bind address, hardcoded key, auth-disabled default, rate-limit spoofing, placeholder keys in docs, CORS, example-key format, AGENTS.md detail, broad local permissions), which §3.34-§3.35 above close. The two reports don't share a numbering scheme; conflating "finding #1" between them was a real mistake caught and corrected in-session before this entry was written, not a hypothetical risk.

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

### 4.6 G8 judgement step: `layer_judgment.py`, built and validated across two independent label sets (2026-11-06)

| | |
| --- | --- |
| **Status** | `WIP` (uncommitted; validated) |
| **Before** | G8 (spec §8.4, replacing `salience_w` with layer confidence) was blocked on a named, unsolved problem: deterministic tiers (file_path / shared entity / similarity, the 2026-10-21 experiment) find *candidate* same-subject pairs but can't *decide* which are real layers — measured ~33% precision. The spec's own §8.7a named the fix as proposal (B): generalize the fact-curator's LLM tiebreak to every durable type. Nothing implemented it. |
| **After** | `brain/ingest/layer_judgment.py`: a 4-way classifier (`LAYER`/`RELATED`/`DUP`/`UNRELATED`) reusing the curator's Ollama-call pattern, gated by `MIN_CANDIDATE_SIM=0.50` (an empirically-grounded floor — the 2026-10-21 hand-labelled sample found ~0 true layers below it, not a number picked to fit this session's data). Iterated 3 times against the original 61-pair hand-labelled set, landing at **0.833 precision / 0.938 recall / F1 0.882**. Then independently re-validated against a *second*, fresh 32-pair sample drawn from the live full-corpus backfill (§4.8) and hand-labelled directly against live content — **0.759 / 0.917 / 0.830** on that set, exposing that the first number overstated real-world precision (the original sample under-represented two failure modes the full corpus surfaces: chunked-document siblings, and elaboration mistaken for override). Combined across both sets: **0.787 / 0.925 / F1 0.851** — this combined number, not the first one, is the honest production estimate. Two further prompt rewrites, each aimed at the elaboration/override ambiguity, were tried and **reverted** after being measured against *both* sets (not just the one that motivated each): iteration 4 (require a quoted contradicting phrase) dropped combined F1 to ~0.50-equivalent via recall collapse; iteration 5 (a softer "would you still give this answer" framing) still landed at combined F1 0.625, below the shipped version's 0.851. The shipped prompt is iteration 3, unchanged by either attempt. One real, separate bug found during the same review *was* fixed (see §4.8). |
| **How** | New `brain/ingest/layer_judgment.py`; new `docs/architecture/experiments/2026-11-06-layer-judgment-gate/` (`eval_judgment.py`, `spotcheck_32_labeled.json`, `results_*.json`, `README.md` with the full iteration table). |
| **Why** | This was the one named, concrete blocker on G8 (spec §8.7a, §10's G8 row) — without a working judgement step, `depth()`/`layer_w()` have no real data to compute from. |
| **Verification** | `docs/architecture/experiments/2026-11-06-layer-judgment-gate/eval_judgment.py --labeled <either set>`, reproducible against live `brain.db` content. No live schema or ranking touched by this entry alone. |

### 4.7 G8 math and schema: `layer.rs`, `memory_links` table (2026-11-06)

| | |
| --- | --- |
| **Status** | `WIP` (uncommitted; unit-tested) |
| **Before** | Spec §8.4's `depth(m)`/`layer_w(m)`/`c(m)` formulas existed only on paper. No table could store a memory-to-memory "layers on" relationship — the existing `edges` table is memory-to-**entity** only (`dst_entity_id`, not `dst_memory_id`); reusing it would have repeated the exact `superseded_by` column-overloading mistake §3.24/§3.25 just finished cleaning up. |
| **After** | New `brain/rust/src/layer.rs`: pure `layer_w(depth, floor, lambda)` and `confidence_scale(depth, lambda)` matching the spec formulas exactly, plus `depth(conn, memory_id, superseded_by)` which sums weight across two de-duplicated sources per distinct newer-memory id — explicit `superseded_by` resolution (via `resolved_supersedes`, weight 1.0, wins on conflict) and judged `layers_on` rows (weight = cosine similarity, the spec's literal "similarity-based weight otherwise"). New dedicated `memory_links` table in `store.rs` (`src_memory_id`/`dst_memory_id`/`relation_type`/`weight`, `UNIQUE(src,dst,relation_type)`, idempotent `CREATE TABLE IF NOT EXISTS` — same safe-to-rerun pattern every prior schema addition in this file uses) — deliberately separate from `edges`, with room for a future `similar_to` relation (G7) without conflating two different edge shapes under one column. 10 unit tests, including a proof (not just an assertion) that swapping `layer_w` in for `salience_w` **tightens** the §2.1 dominance-invariant band from ~1.942× to ~1.688× — replacing the known-wrong signal can only make the "relevance can't be overridden" guarantee stronger. |
| **How** | New `brain/rust/src/layer.rs`; `store.rs` (`memory_links` table + indexes); `lib.rs` (module registration). |
| **Why** | Spec §8.4 is "the real fix" G0 deferred to; this is that formula, implemented and proven correct against its own stated invariants rather than assumed correct. |
| **Verification** | `cargo test --lib layer::` — 10/10 passed (`layer_w_at_depth_zero_is_exactly_one`, `confidence_at_depth_zero_is_exactly_ten`, `layer_w_is_monotonically_non_increasing_in_depth`, `layer_w_is_bounded_in_floor_one`, `layer_w_approaches_floor_as_depth_grows`, `layer_w_tightens_the_dominance_band_vs_salience_w`, `depth_is_zero_with_no_links_and_no_supersede`, `depth_counts_explicit_supersede_as_weight_one`, `depth_sums_judged_layer_links_and_dedupes_against_explicit`, `insert_layer_link_is_idempotent`). Full crate: 183 passed, 0 failed. |

### 4.8 G8 full-corpus backfill: `backfill_layer_links.py`, 6,163 `layers_on` rows (2026-11-06)

| | |
| --- | --- |
| **Status** | `WIP` (uncommitted script; data already written live to `brain.db`) |
| **Before** | `memory_links` existed as schema only — zero rows. No tool generated candidates (file_path / shared-entity tiers, same-project required per spec §8.5a) across the whole corpus and judged them. |
| **After** | `brain/tools/backfill_layer_links.py`: generates candidates from 14,563 active memories (1,182 file-path pairs + 39,848 shared-entity pairs → 16,548 above `MIN_CANDIDATE_SIM`), judges each via §4.6's classifier, writes `layers_on` rows for `LAYER` verdicts. Ran to completion: 16,546/16,548 judged (2 errors), **6,170 rows written** (6,170 LAYER, 10,150 RELATED, 183 DUP, 43 UNRELATED). **One real bug found and fixed mid-run, caught before it could cause data loss:** the first launch held one uncommitted SQLite transaction open for the entire ~5-hour run against a *live* database the API was also reading — killed and restarted with per-row `commit()` plus an incrementally-flushed JSONL audit log, so a kill/crash at any point loses at most one row's work, not the whole run. **A second real bug found during §4.6's independent 32-pair review, fixed mechanically, not by prompt-tuning:** sibling chunks of one re-ingested document (same `session_id = reingest_<slug>_<N>` prefix) were being judged `LAYER` against each other — confirmed this can't be caught from content text alone (the two reverted prompt attempts in §4.6 tried and failed at exactly this). Fixed in candidate generation via a `chunk_group()` check on `session_id`; found and removed the 7 already-written bad links from the live DB (backed up to `brain/bootstrap/junk_scrub_backups/chunk_sibling_layer_links_removed_*.json` first — current total **6,163** `layers_on` rows). |
| **How** | New `brain/tools/backfill_layer_links.py`. Live mutation: `brain/rust/brain.db`'s new `memory_links` table (additive only, backed up before the one subtractive correction). |
| **Why** | `depth()` needs real `layers_on` data to be anything other than always-zero; this is that data, generated with the validated judgement step from §4.6. |
| **Verification** | Full run log preserved at `brain/eval/runs/layer-backfill-1793956863.jsonl` (gitignored, local). Live row count re-verified via direct `sqlite3` query (6,163) after the chunk-sibling cleanup. |

### 4.9 G8 opt-in ranking flag + real A/B, gold-set hygiene (2026-11-06)

| | |
| --- | --- |
| **Status** | `WIP` (uncommitted; **flag defaults off, no live ranking change for real traffic**) |
| **Before** | `score(x,q)` always used `salience_w`. No way to substitute `layer_w` for a single request; no way to measure the effect even if there were, since `brain/eval/gold_recency.jsonl` (63 pairs: 16 hand-labelled + 47 curator-UPDATE) was the only recency-specific gold set and its own README (2026-10-21) said the ranking A/B was blocked pending a precise stack detector. |
| **After** | `SearchFilter::use_layer_confidence` (new field, **default `false`**, same pattern as `apply_source_quality`/`salience_neutral`): when set, `layer_confidence_w` (from §4.7's `depth()`+`layer_w()`) replaces `salience_w` in `final_score` for that request only — `salience_w` is forced to `1.0` when the flag is set, matching the spec's "layer_w replaces salience_w, not alongside it" (§8.4). Wired end-to-end: `types.rs` → `brain.rs` scoring → `bin/brain_api.rs`'s `/search` request/handler → `api_client.py`'s `search()` → `recency_eval.py --use-layer-confidence`. Two new `brain.rs` tests prove (a) the flag off is byte-identical regardless of what's in `memory_links` (regression safety) and (b) the flag on reproduces the exact `layer_w(depth)/salience_w(1.15)` ratio algebraically, not approximately. **Separately, a parallel investigation (run concurrently, see note below) found the gold set's real bottleneck wasn't ranking at all**: 51 of 86 pairs (after a first expansion to 86, see below) surfaced *neither* memory at all. Root-caused: 39 were dangling references to memory ids deleted by earlier cleanup work; 10 were `type=episode` content hitting the pre-existing, intentional `exclude_episodes_by_default`; 3 were single-generic-word queries ("solution", "profiles") matching thousands of unrelated rows. Fixed: dropped the 42 dead/bad pairs, tagged the 10 episode pairs with `memory_type` and taught `recency_eval.py` to pass it through. Gold set: 86 → **44** pairs, coverage 36% → **95%**. |
| **How** | `brain/rust/src/types.rs` (new `SearchFilter` field), `brain.rs` (scoring + 2 tests), `bin/brain_api.rs` (request field + wiring), `brain/api_client.py`, `brain/tools/recency_eval.py` (`--use-layer-confidence` flag, `memory_type` passthrough), `brain/eval/gold_recency.jsonl` (grew 63→86 via 23 independently-verified pairs from §4.6's spot-check, then hygiene-cleaned to 44). |
| **Why** | This is the actual G8 deliverable: a safe, reversible, measurable way to test whether the spec's core model helps real ranking, without touching default behavior. |
| **Verification — the real A/B, not a simulation**, run against the live `brain_api` (rebuilt release + `launchctl kickstart`'d mid-session to pick up the flag) on the final 44-pair, 95%-coverage gold set: baseline 65.1% (28/43 judged) → `layer_w` 71.4% (30/42 judged). Per-pair diff (not just the headline rate): **4 pairs fixed, 1 "regressed", 1 dropped from judged.** Both the regression and the drop trace to the same explained cause, verified by reading the actual `memory_links` rows: two fast-moving `sicop-health` subjects where the gold set's own "current" answer has itself been superseded again since being labelled — `layer_w` correctly demoted it too, which is the model working, not a defect. **Zero unexplained regressions.** Full history (including the pre-hygiene 63- and 86-pair runs, kept for the record rather than deleted) in `brain/eval/last_recency_report_*.json` and `docs/architecture/experiments/2026-11-06-layer-judgment-gate/README.md`. |

### 4.10 Security remediation: 7 of 8 report-only audit findings fixed (2026-11-06)

| | |
| --- | --- |
| **Status** | `WIP` (uncommitted; **Rust fixes deployed live** via release rebuild + `launchctl kickstart`; Python fixes in this repo's working tree only — see open item below) |
| **Before** | `brain/rust/SECURITY_AUDIT_REPORT.md` / `docs/SECURITY_AUDIT_2026-11-05.md` (an earlier, same-session report-only pass) had documented 8 real findings, none fixed. |
| **After**, finding by finding: |
| | 1. **`/static/index.html` leaked the live API key to anyone, even with auth on** — the route never called `authorize_and_rate_limit`. Fixed: key only injected when `auth_required` is explicitly `false` (this deployment's own documented LAN posture); served without the key otherwise. |
| | 2. **Rate limiter trusted a spoofable `X-Forwarded-For`, and failed-auth attempts bypassed it entirely** (unlimited brute force) — fixed both: `client_key()` stopped trusting the header (no reverse proxy sits in front of this deployment, so it was pure spoof surface, not a real client identifier); rate-limit check moved *before* the auth check so failed attempts now consume budget too. |
| | 3. **The Ollama-summarization hook had no secret-file exclusions** — `action_state.py`'s `SKIP_FILE_PATTERNS` gained `.env*` (excluding `.example`/`.sample`), key/cert files, SSH keys, `.npmrc`/`.netrc`, `credentials*`, `secrets.*`, mirroring what `.gitignore` already excludes from version control. |
| | 4. **Session transcript export opened an unchecked path from hook stdin** — `session_end.py` gained `is_safe_transcript_path()`: must resolve inside `~/.claude/projects/` and end in `.jsonl`. |
| | 5. **Real, serious: the live Python-backend reflection path deleted memories from raw LLM output, no cap, no backup** — `brain/core/memory.py`'s `_trigger_reflection()` now refuses (doesn't silently truncate) a delete batch over 30% of the reflected set, and writes a JSON backup before any delete, matching this repo's existing backup-then-mutate convention. Same pattern also patched in `brain/memory.py`, an unreferenced duplicate, for defense-in-depth. |
| | 6. **Viewer puts the API key on the `/v1/stream` query string** — **not code-fixed**, characterized instead: confirmed `EventSource` genuinely cannot set headers (the real constraint, not an oversight), and confirmed via every `log_request()` call site that the URI is never logged (only hardcoded path literals are). Residual exposure is browser history/extensions; closing it needs a short-lived stream-token feature, which is new scope — flagged for a product decision, not invented here. |
| | 7. **Redact dry-run wrote an unredacted backup unconditionally, before the `--dry-run` check** — fixed: backup now only written in the `--apply` path, immediately before mutation. Verified live: dry-run now writes zero files. **Found but not touched**: two pre-existing backup files from 2026-10-27 in `brain/bootstrap/junk_scrub_backups/` confirmed (10 occurrences each) to still contain real OpenRouter key material in plaintext — gitignored, never in git history, but real exposure sitting on local disk right now. Deleting them, or rotating the underlying key, is explicitly left as an open owner decision below, not done silently. |
| | 8. **Ops script deleted `--out` by default, and had a path-containment bug** — `export_knowledge_graph.py` flipped from opt-out (`--no-clean`) to opt-in (`--clean`), matching this repo's convention everywhere else; added a hard containment check before any `rmtree` call (previously, `vault_root / absolute_path` silently discarded the vault root, so a bad `--out` value could have deleted outside it). `brain_pipeline.py`'s one real caller updated to pass `--clean` explicitly so its existing behavior doesn't silently change. Same pattern patched in `brain/export_knowledge_graph.py`, an unreferenced top-level duplicate. |
| **How** | `brain/rust/src/bin/brain_api.rs`, `brain/hooks/action_state.py`, `brain/hooks/session_end.py`, `brain/core/memory.py`, `brain/memory.py`, `brain/tools/export_knowledge_graph.py`, `brain/export_knowledge_graph.py`, `brain/tools/redact_leaked_openrouter_keys.py`, `brain/tools/brain_pipeline.py`. New tests: `brain/tests/test_memory.py`, `test_session_end_export.py`, `test_smart_capture.py`, new `test_export_knowledge_graph_safety.py`; 11 new tests total, all passing. |
| **Why** | These were real, open findings from this session's own earlier audit — "production ready" cannot mean leaving known, fixed-cost vulnerabilities undeployed. |
| **Verification** | `cargo check`/`cargo test`: 183+23 passed, 0 failed, both before and after. Full Python suite run on a stashed diff to isolate real regressions: 11 pre-existing failures confirmed untouched by this work (`test_deploy_parity.py` ×7 — see §6's standing note, `test_forge_phase_b.py`, `test_realtime_save_search.py`, `test_run_gates.py`, `test_save_memory_batch.py` ×2); zero new regressions beyond the one deploy-parity diff that's `test_deploy_parity.py`'s own by-design behavior (it diffs this repo against `~/Documents/AI`, the legacy plane this very changelog's §1/§3.1/§3.2.F/§4.1 already establish is **not** where anything executes — editing a live hook file here mechanically trips that stale-parity check, same as §3.9's note that it's "red only because `test_deploy_parity` compares against ~/Documents/AI, which nothing executes anymore"). Owner confirmed directly (2026-11-06): `~/Documents/AI` is an old twin, not a parallel deployment — item 5's fix does **not** need copying there. Rust changes **rebuilt in release mode and deployed live** (`launchctl kickstart -k gui/$(id -u)/com.brain.api`), confirmed healthy via `/stats` afterward. |
| **Open, owner-decision items (not resolved by this entry):** (a) the two leaked-key backup files on disk — delete and/or rotate the key; (b) item 6's stream-token feature. The `~/Documents/AI` deploy-parity question from this entry's first pass is resolved, not open — see Verification. |

### 4.11 Spec/diagram doc revisions for G8 progress (2026-11-06)

| | |
| --- | --- |
| **Status** | `WIP` (uncommitted) |
| **Before** | `docs/architecture/cognitive-architecture-spec.md`'s G8 row and `cognitive-architecture-diagram.md`'s §3 nodes still described the layer-confidence model as entirely proposed/dashed, last revised 2026-11-05 for G2. |
| **After** | Both files gained a dated 2026-11-06 revision note and an updated G8 gate-table row reflecting everything in §4.6–§4.9 above: stack detector built and measured, `layer_w`/`depth()` implemented and proven, backfill run, flag wired and A/B'd — explicitly still marked **not closed** (flag off by default pending a product decision; open question 1 from §8.8 still deferred by the owner; the elaboration-vs-override residual accepted, not solved). |
| **How** | `docs/architecture/cognitive-architecture-spec.md`, `docs/architecture/cognitive-architecture-diagram.md`. |
| **Why** | This doc's own §9 maintenance rule and the owner's standing preference (§4.N above) — update the living spec in the same session as the work, don't let it drift. |

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

**Last verified against git:** 2026-07-28 (HEAD `6e75315` + WIP listed in §4) for §§1–3.8; 2026-11-05 (HEAD `7db2915` + WIP listed in §4's final entry) for §3.9 onward; 2026-11-06 (HEAD `be88698` + WIP listed in §4.6–§4.11, `git status --porcelain` cross-checked against every file named above) for §3.26 onward; 2026-11-08 (HEAD `5e27710`, every commit from `206c7d6` onward verified by this session's own `cargo test`/`pytest` runs, not restated from memory) for §3.28–§3.35. §4.6–§4.11 are now fully committed (see §3.28–§3.35's mapping) but left in place rather than moved, per rule 4 above; new work should treat them as historical, superseded by §3.28 onward where they overlap.
