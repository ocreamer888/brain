# Trustworthy Memory Contract (Stage 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Brain’s memory metadata honest: rename extractor provenance, clarify time fields, and document contracts so future routing cannot misuse fields—without changing default retrieval behavior.

**Architecture:** Dual-read / dual-write API aliases on existing SQLite columns first; no new relation types; no router; no executive ledger. Schema renames are additive (new column or alias) until callers migrate.

**Tech Stack:** Rust (`brain/rust` types, store, API), Python (`fact_extractor`, `fact_curator`, `api_client`, tests), docs under `docs/`.

## Global Constraints

- Default search path unchanged (`graph_expand` remains false; salience β=0.0).
- No new edge `relation_type` values in Stage 1.
- Do not persist corroboration confidence from `confidence_score.py`.
- Do not add `source_quality` or `status` columns in Stage 1 unless a follow-up task is explicitly approved (deferred below).
- Breaking renames must keep wire compatibility for at least one release via serde aliases.
- Ask before any migration that rewrites production `brain.db` rows in place without dual-read.

---

### Task 1: Document the memory contract in-repo

**Files:**
- Create: `docs/MEMORY_CONTRACT.md`
- Modify: `docs/architecture/system-diagrams.md` (add link + short “agent loop” pointer)
- Modify: `CLAUDE.md` or `docs/BRAIN.md` only if a single sentence pointer is needed (prefer `docs/BRAIN.md`)

**Interfaces:**
- Produces: canonical field table used by later tasks

- [ ] **Step 1: Write `docs/MEMORY_CONTRACT.md`** with this exact field table (copy from design, keep verified meanings):

```markdown
# Memory Contract (Stage 1)

Brain stores and ranks memories. It does not plan or act.

| Field | Storage | Meaning | Must not be treated as |
| --- | --- | --- | --- |
| `id` | `memories.id` | Stable id | |
| `content` | text | Memory body | |
| `type` | `memory_type` | One of MemoryType | |
| `project` | string | Project label (cwd/folder) | Structured project entity |
| `timestamp` | datetime | Prefer: Brain observed/ingest time; see Time contract | Event time |
| `event_time` | optional datetime | When the fact/event occurred | Ingest time |
| `source` | MemorySource | Ingestion origin | Source quality |
| `salience` | f64 | Extractor confidence / UI audit | Retrieval weight (β=0) |
| `importance` | f64 | Priority hint | Calibrated confidence |
| `parent_id` | optional | Fact → episode parent | General derivation |
| `superseded_by` | optional | Id of newer fact | Bidirectional graph edge |
| `extracted_by` | optional (was `derived_from`) | Extractor model+prompt version | Parent memory id |
| `derived_from_memory_id` | reserved / later | Real parent-memory derivation | Extractor stamp |
| `outcome` (fact_type) | extractor label | Fact classification | Action/execution result |
| `mentions` | edges.relation_type | Extraction link to entity | Semantic claim |

## Time contract

1. Prefer writing **event occurrence** to `event_time`.
2. Prefer writing **Brain first saw this** to `timestamp` (observed_at alias in docs).
3. Ingest scripts that currently pass historical times into `timestamp` must be inventoried and fixed in Task 3.

## Feedback vs confidence

- `feedback_events` = host/user signal (Phase 7).
- Corroboration confidence (`brain/tools/confidence_score.py`) = shadow report only until explicitly approved to write.
```

- [ ] **Step 2: Add a section to `docs/architecture/system-diagrams.md`** after the intro list:

```markdown
7. **Memory contract + agent loop** — see `docs/MEMORY_CONTRACT.md` and
   `docs/superpowers/specs/2026-10-16-trustworthy-memory-and-advisory-routing-design.md`
   (Brain retrieves; host plans/acts; route identification is future/advisory).
```

- [ ] **Step 3: Commit**

```bash
git add docs/MEMORY_CONTRACT.md docs/architecture/system-diagrams.md
git commit -m "docs: add Stage 1 memory contract and architecture pointer"
```

---

### Task 2: Rename `derived_from` → `extracted_by` with wire aliases

**Files:**
- Modify: `brain/rust/src/types.rs` (`MemoryMetadata`)
- Modify: `brain/rust/src/store.rs` (column dual-read; prefer rename via `ALTER` + keep reading old name if present, or add column)
- Modify: `brain/rust/src/brain.rs`, `brain/rust/src/bin/brain_api.rs`, `brain/rust/src/migrate.rs`
- Modify: `brain/api_client.py`, `brain/ingest/fact_extractor.py`, `brain/ingest/fact_curator.py`
- Modify: `brain/tests/test_fact_extractor.py`, `brain/tests/test_fact_curator.py`
- Test: `brain/rust` unit tests that assert `derived_from` today

**Interfaces:**
- Consumes: existing `derived_from` column/values
- Produces: public JSON field `extracted_by`; accept legacy `derived_from` on input; serialize both during transition **or** only `extracted_by` with `#[serde(alias = "derived_from")]` on deserialize

**Recommended Rust shape:**

```rust
/// Extractor model + prompt version tag (e.g. "ollama/.../v1").
/// Wire name: `extracted_by`. Legacy input alias: `derived_from`.
#[serde(default, alias = "derived_from")]
pub extracted_by: Option<String>,
```

SQLite: rename column when safe:

```sql
-- On open, after create_tables:
-- If column derived_from exists and extracted_by does not:
ALTER TABLE memories RENAME COLUMN derived_from TO extracted_by;
```

If SQLite version lacks `RENAME COLUMN`, add `extracted_by TEXT`, copy, leave old column until a later cleanup task.

- [ ] **Step 1: Write failing Rust test** in `brain/rust/src/types.rs` tests module (or store test):

```rust
#[test]
fn memory_metadata_accepts_legacy_derived_from_alias() {
    let json = r#"{"type":"fact","project":"brain","tags":"","timestamp":"2026-10-16T00:00:00Z","source":"claude_code_session","derived_from":"ollama/test/v1"}"#;
    let meta: MemoryMetadata = serde_json::from_str(json).unwrap();
    assert_eq!(meta.extracted_by.as_deref(), Some("ollama/test/v1"));
}
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd brain/rust && cargo test memory_metadata_accepts_legacy_derived_from_alias -- --nocapture
```

Expected: FAIL (field still named `derived_from` or missing).

- [ ] **Step 3: Implement rename + alias + store migration**

- [ ] **Step 4: Update Python writers** to send `extracted_by` (and optionally still accept `derived_from` in readers).

```python
# fact_extractor.py
f.extracted_by = f"ollama/{OLLAMA_SUMMARIZE_MODEL}/{prompt_version}"
```

- [ ] **Step 5: Run Rust + Python tests**

```bash
cd brain/rust && cargo test extracted_by -- --nocapture
.venv/bin/python -m pytest brain/tests/test_fact_extractor.py brain/tests/test_fact_curator.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add brain/rust/src brain/api_client.py brain/ingest brain/tests
git commit -m "refactor: rename derived_from to extracted_by with legacy alias"
```

---

### Task 3: Inventory and clarify timestamp vs event_time writers

**Files:**
- Create: `docs/MEMORY_TIME_INVENTORY.md` (short table of call sites)
- Modify: only call sites that **clearly** write historical event time into `timestamp` while leaving `event_time` null — set `event_time` instead / as well, without changing default ranking floors

**Interfaces:**
- Produces: inventory table; minimal writer fixes

- [ ] **Step 1: Grep and list writers**

```bash
rg -n "event_time|timestamp=" brain/rust/src/ingest brain/api_client.py brain/hooks brain/tools --glob '*.{rs,py}'
```

- [ ] **Step 2: Write inventory markdown** with columns: path, currently sets `timestamp`?, sets `event_time`?, recommended fix.

- [ ] **Step 3: For each mis-writer found, add/adjust a unit or integration test** that asserts historical session time lands in `event_time`.

Example assertion pattern (Python API client mock or Rust ingest test):

```python
assert payload.get("event_time") is not None
# timestamp may still be set; event_time must carry occurrence time
```

- [ ] **Step 4: Minimal writer fixes** — prefer setting `event_time` without changing search defaults.

- [ ] **Step 5: Commit**

```bash
git add docs/MEMORY_TIME_INVENTORY.md brain/
git commit -m "docs+fix: clarify event_time vs timestamp write paths"
```

---

### Task 4: Reserve `derived_from_memory_id` without enabling graph semantics

**Files:**
- Modify: `docs/MEMORY_CONTRACT.md` (already reserved)
- Modify: `brain/rust/src/types.rs` — add optional field **only if approved**; default None; **not** used in search

**Defer by default:** skip code until G1 approves. If approved:

```rust
/// Real parent-memory derivation (not extractor provenance). Unused in Stage 1 ranking.
#[serde(default)]
pub derived_from_memory_id: Option<String>,
```

- [ ] **Step 1: Confirm approval for new optional column** (human gate G1/G2).
- [ ] **Step 2: If approved — failing store round-trip test, then column + serde, then commit.**
- [ ] **Step 3: If not approved — mark deferred in MEMORY_CONTRACT.md and skip.**

---

### Task 5: Explicitly block Stage 1 anti-patterns in docs + comments

**Files:**
- Modify: `brain/tools/confidence_score.py` module docstring (already shadow — add “Stage 1: do not wire to /save”)
- Modify: `docs/ENTITY_EDGE_GRAPH.md` Evaluation section — one sentence pointing to trustworthy-memory design (no new relation types without gold PASS)
- Modify: `brain/ingest/fact_extractor.py` comment on `outcome` fact_type

- [ ] **Step 1: Add comments** clarifying `outcome` is a fact classification tag, not execution outcome.

- [ ] **Step 2: Commit**

```bash
git add brain/tools/confidence_score.py brain/ingest/fact_extractor.py docs/ENTITY_EDGE_GRAPH.md
git commit -m "docs: clarify outcome, confidence shadow mode, graph relation gates"
```

---

### Task 6: Regression gate — default retrieval unchanged

**Files:**
- Test only / run existing harness

- [ ] **Step 1: Run Rust search tests**

```bash
cd brain/rust && cargo test graph_expand_ -- --nocapture
cd brain/rust && cargo test search_ -- --nocapture
```

Expected: PASS; `graph_expand` default still false.

- [ ] **Step 2: Run Python fact + confidence shadow tests**

```bash
.venv/bin/python -m pytest brain/tests/test_fact_extractor.py brain/tests/test_confidence_score.py -q
```

Expected: PASS; confidence tool still does not write salience.

- [ ] **Step 3: Commit empty or doc-only “Stage 1 complete” note in design status**

```bash
# Update design status line to "Stage 1 implemented (semantic cleanup)" when code tasks done
git add docs/superpowers/specs/2026-10-16-trustworthy-memory-and-advisory-routing-design.md
git commit -m "docs: mark Stage 1 semantic cleanup complete"
```

---

## Deferred (needs separate approval — not Stage 1)

| Item | Why deferred |
| --- | --- |
| `source_quality` column | No write path or rank monotonicity tests yet |
| `status` enum | Supersession already covers one state; quarantine/dispute need workflows |
| Normalized `supersedes` edge table | `superseded_by` field works; migrate only if query needs reverse index |
| Structured project entities | String filters sufficient until continuity metric fails |
| `recommend_route` / decision events | Stage 2 |
| Execution ledger | Stage 4 |

## Spec coverage self-check

| Design Stage 1 item | Task |
| --- | --- |
| Rename `derived_from` → `extracted_by` | Task 2 |
| Time contract / observed_at clarity | Tasks 1, 3 |
| Do not persist confidence yet | Task 5 + Global Constraints |
| No new relations | Task 5 + Global Constraints |
| Projects stay strings | Deferred table |
| Docs match behavior | Tasks 1, 5, 6 |
