# Retrieval Quality, Vault Provenance, and Eval Harness — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make brain retrieval **measurable and trustworthy** by (1) improving ranking/filtering using richer metadata, (2) attaching **explicit `vault/` paths (+ optional section anchors)** to every vault-originated memory and exposing them on search, and (3) adding a **repeatable eval script** (queries → gold files → recall@k / hit metrics) so chunking and rerank knobs are tuned by data, not intuition.

**Architecture:** Keep **SQLite + vector index** (`brain/rust/brain_api`) as the system of record for vectors. Treat **`vault/`** as the canonical full-text store. Extend **save + search** APIs so provenance fields round-trip; add a **thin Python rerank/filter** step (optional second stage after vector over-fetch) without requiring a new service on day one. Add **`brain/eval/`** (or `brain/tools/`) scripts plus a small **gold YAML/JSON** corpus under version control. Chunking changes in `09_ingest_obsidian.py` are driven only after eval shows gain.

**Tech Stack:** Rust (`brain/rust`, `brain_api`), Python 3 (`brain/api_client.py`, `brain/mcp/server.py`, `brain/bootstrap/09_ingest_obsidian.py`), SQLite schema in `brain/rust/src/store.rs` / migrations, pytest for Python helpers, optional `pyyaml` if YAML gold files are used (or use JSON only to avoid new deps — prefer **JSONL gold file** to stay YAGNI).

---

### Task 1: Provenance fields on save (Rust API + store)

**Files:**
- Modify: `brain/rust/src/types.rs` — extend `MemorySource` with `Obsidian` (or `VaultDoc`) variant; ensure serde snake_case matches Python `source="obsidian"`.
- Modify: `brain/rust/src/bin/brain_api.rs` — extend `SaveRequest` with optional `file_path: Option<String>`, `title: Option<String>` (and optional `doc_type: Option<String>` if you want a dedicated column later; YAGNI: put doc type in `tags` prefix `doc_type/` first).
- Modify: `brain/rust/src/brain.rs` — `save_memory(...)` already builds `MemoryMetadata`; thread `file_path` / `title` from request into metadata.
- Modify: `brain/rust/src/store.rs` (and any migration SQL) — ensure `file_path` / `title` columns persist (schema already has columns per `types.rs`; verify `upsert_memory` writes them).
- Modify: `brain/api_client.py` — `save_memory(..., file_path=None, title=None)` append to JSON payload when set.
- Test: `brain/rust/src/brain.rs` (existing test module) add unit test: save with `file_path`, read back via `get_memory` / search result includes path.

**Step 1: Write failing Rust test**

Add test that POST body would map to metadata: either integration test hitting in-memory brain + store, or unit test on metadata builder if split.

**Step 2: Run test — expect FAIL**

```bash
cd /Users/macm1air/Documents/AI/brain/rust && cargo test brain::tests::save_memory_persists_file_path -q
```

Expected: compile fail or test fail until API wired.

**Step 3: Implement minimal Rust + Python client**

- Add enum variant + `parse_memory_source("obsidian")`.
- Extend `SaveRequest` + `save` handler to pass `file_path` / `title` into `brain.save_memory`.
- Extend Python `save_memory` to send optional keys.

**Step 4: Run tests — expect PASS**

```bash
cd /Users/macm1air/Documents/AI/brain/rust && cargo test -q
```

**Step 5: Commit**

```bash
git add brain/rust/src/types.rs brain/rust/src/bin/brain_api.rs brain/rust/src/brain.rs brain/rust/src/store.rs brain/api_client.py
git commit -m "feat(brain): persist file_path and title on save; Obsidian memory source"
```

---

### Task 2: Ingest writes `vault_relpath` + section anchor

**Files:**
- Modify: `brain/bootstrap/09_ingest_obsidian.py` — for each chunk / whole file memory:
  - Set `file_path` API field to **`vault/<relative path>`** (POSIX, use `/` — repo root is `Path(__file__).parents[2]`; vault is `_REPO_ROOT / "vault"`).
  - Set `title` to **`{note_stem} — {section_title}`** for chunked docs, or note stem only for small files.
  - Add tag **`vault_relpath/<urlencoded-or-safe-slug-of-relpath>`** only if needed for filtering before API supports query by file_path (prefer `file_path` as primary; tags optional duplicate for Chroma-era consumers).
- Modify: `brain/bootstrap/08_ingest_books.py` — same pattern for book chunks: `file_path` = `vault/03 Resources/Books/<file>.md` when source file known.

**Step 1: Dry-run ingest**

```bash
cd /Users/macm1air/Documents/AI && python3 brain/bootstrap/09_ingest_obsidian.py --dry-run 2>&1 | head -5
```

**Step 2: Add one integration assertion (optional)**

Small pytest: mock `save_memory` and assert payload contains `file_path` starting with `vault/`.

**Step 3: Run against API (staging)**

With `brain_api` running locally, run ingest on **one** new test file in `vault/` to verify DB row shows `file_path` (sqlite query).

**Step 4: Commit**

```bash
git add brain/bootstrap/09_ingest_obsidian.py brain/bootstrap/08_ingest_books.py
git commit -m "feat(ingest): set vault file_path and title for Obsidian memories"
```

---

### Task 3: Search returns structured provenance + over-fetch hook

**Files:**
- Modify: `brain/rust/src/bin/brain_api.rs` — ensure `POST /search` JSON includes full `metadata` object (including `file_path`, `title`) per hit — verify serialization; add optional query param `overfetch_multiplier` default 4 (already internal in `Brain::search` — consider exposing `candidates` vs `returned` only in logs first; YAGNI: keep internal over-fetch, document it).
- Modify: `brain/api_client.py` — `search()` return type already list of dicts; ensure keys match API.
- Create: `brain/tools/retrieval_rerank.py` — function `rerank_results(query: str, results: list[dict], *, boost_vault: bool = True) -> list[dict]`:
  - **Phase 1 (no ML):** reorder by rules: if `metadata.file_path` starts with `vault/`, small boost; if `memory_type` filter passed, respect; penalize very short `content` for document-like queries (heuristic on query length).
  - Leave hook for **Phase 2**: cross-encoder / bge-reranker behind env `BRAIN_RERANKER=none|cross_encoder`.

**Step 1: Unit test rerank deterministic order**

```bash
cd /Users/macm1air/Documents/AI && pytest brain/tests/test_retrieval_rerank.py -q
```

(Create test file with two fake results, assert vault-boost changes order when distances tie.)

**Step 2: Wire MCP (optional in same task)**

Modify `brain/mcp/server.py` `search_brain` to append a line per hit:

`Source file: vault/...` when `metadata.file_path` or parse from tags.

**Step 3: Commit**

```bash
git add brain/tools/retrieval_rerank.py brain/mcp/server.py brain/tests/test_retrieval_rerank.py brain/rust/src/bin/brain_api.rs
git commit -m "feat(retrieval): expose vault paths in MCP; heuristic rerank hook"
```

---

### Task 4: Agent policy (Cursor / Claude)

**Files:**
- Modify: `CLAUDE.md` (repo root) — short subsection **Retrieval discipline**: after `search_brain`, if answer uses facts from a hit that has `vault/...` path, **read that file** with the editor tool before stating numbers or commitments; on **borderline** similarity (document in plan: define borderline = top hit distance within ε of 2nd hit, or expose `distance` in MCP output first).
- Modify: `brain/mcp/server.py` instructions string — same one-paragraph policy for MCP-only sessions.

**Step 1: Commit docs**

```bash
git add CLAUDE.md brain/mcp/server.py
git commit -m "docs: agent policy to open vault file for uncertain retrieval hits"
```

---

### Task 5: Evaluation harness (repeatable)

**Files:**
- Create: `brain/eval/gold.jsonl` — each line: `{"query":"...","gold_files":["vault/01 Projects/Foo/docs/bar.md"],"k":10}` (gold_files are relative to repo root).
- Create: `brain/eval/README.md` — how to add cases, how to interpret metrics.
- Create: `brain/tools/retrieval_eval.py` — CLI:
  - Loads gold.jsonl
  - Calls `brain.api_client.search(query, n=k)` (or hits `POST /search` directly)
  - For each result, extract candidate path from `metadata.file_path` or regex `vault/...` from tags
  - Metrics: **recall@k** (any gold file in top k), **MRR** optional, **first_correct_rank** (0 if none)
  - Exit code non-zero if recall below threshold (optional `--min-recall 0.3` for CI)
- Test: `brain/tests/test_retrieval_eval_smoke.py` — one synthetic gold line + mock search.

**Step 1: Write failing smoke test**

**Step 2: Implement `retrieval_eval.py` minimal**

**Step 3: Run**

```bash
cd /Users/macm1air/Documents/AI && python3 brain/tools/retrieval_eval.py --gold brain/eval/gold.jsonl --k 10
```

Expected: human-readable table + JSON summary to stdout or `brain/eval/last_report.json`.

**Step 4: Commit**

```bash
git add brain/eval/gold.jsonl brain/eval/README.md brain/tools/retrieval_eval.py brain/tests/test_retrieval_eval_smoke.py
git commit -m "feat(eval): retrieval gold set and recall@k harness"
```

---

### Task 6: Tune chunking from eval (close the loop)

**Files:**
- Modify: `brain/bootstrap/09_ingest_obsidian.py` — make `1500` word threshold and `##` chunking configurable via env `OBSIDIAN_CHUNK_WORDS` / `OBSIDIAN_CHUNK_STRATEGY=headers|paragraph` (default current behavior).
- Modify: `docs/plans/2026-04-11-retrieval-provenance-eval.md` (this file) or `brain/eval/README.md` — document: run eval before/after threshold change; keep best in comment.

**Step 1:** Baseline eval with current threshold (record score in `brain/eval/README.md`).

**Step 2:** Change threshold on a branch, re-ingest **subset** (checkpoint trick: use separate test vault copy or `--limit-files` flag if you add it).

**Step 3:** Compare recall@k; merge only if improved.

**Step 4: Commit**

```bash
git add brain/bootstrap/09_ingest_obsidian.py brain/eval/README.md
git commit -m "feat(ingest): configurable chunk thresholds for eval-driven tuning"
```

---

## Non-goals (YAGNI for v1)

- Full Obsidian graph import into SQLite as edges table (future).
- Training learned rerankers (Phase 2 env flag only).
- Replacing `brain_graph/` export — orthogonal.

---

## Execution handoff

**Plan complete and saved to `docs/plans/2026-04-11-retrieval-provenance-eval.md`. Two execution options:**

**1. Subagent-Driven (this session)** — dispatch a fresh subagent per task, review between tasks, fast iteration  
**2. Parallel Session (separate)** — new session with `superpowers:executing-plans`, batch execution with checkpoints  

**Which approach?**

If **Subagent-Driven** is chosen: **REQUIRED SUB-SKILL:** `superpowers:subagent-driven-development` — stay in this session, fresh subagent per task + code review.

If **Parallel Session** is chosen: guide to open a new session in a clean worktree; **REQUIRED SUB-SKILL:** `superpowers:executing-plans`.
