# Phase 7 — Temporal Teeth

**Shipped:** 2026-05-03  
**Goal:** Give every fact a meaningful `event_time` so recency decay reflects actual knowledge age, not ingest date.

---

## Problem

Before Phase 7, `event_time` was `NULL` on 14,904 facts (100%). The recency decay formula in `brain.rs` used the ingest `timestamp` instead — meaning a fact from a session six months ago looked brand-new if it was re-ingested or re-processed recently. Decay was measuring storage time, not knowledge age.

---

## What Changed

### 7.1 — Historical backfill (`brain/tools/stamp_event_times.py`)

One-time script that stamped `event_time` on all existing facts using three passes:

| Pass | Condition | Value assigned |
|------|-----------|----------------|
| Sessions | `session_id` matches a Claude Code session export | `ended_at` from that session JSON |
| Cursor / Perplexity | Has a `session_id` but no matching export | `2025-07-01T00:00:00+00:00` |
| No session | `session_id` is empty or NULL | `2025-01-01T00:00:00+00:00` |

Result: **14,771 facts stamped**, 0 remaining NULL. Idempotent — safe to re-run.

### 7.2 — Forward path: `fact_curator.py`

`_save_fact()`, `_curate_one()`, and `curate_facts()` now accept `source_event_time: str | None`. When the LLM extractor returns `event_time=None`, the session's `ended_at` is used as fallback. LLM-extracted values always win.

### 7.3 — Forward path: `backfill_facts.py`

`process_session()` reads `ended_at` from the session dict and threads it as `source_event_time` through `_run_extraction()` → `curate_facts()`. All future fact extractions inherit the session's end time automatically.

### 7.4 — Rust ranking (`brain/rust/src/brain.rs`)

Age calculation changed from:

```rust
// Before
let age_days = (now - memory.metadata.timestamp).num_seconds().max(0) as f32 / 86_400.0;
```

to:

```rust
// After
let effective_time = memory.metadata.event_time.unwrap_or(memory.metadata.timestamp);
let age_days = (now - effective_time).num_seconds().max(0) as f32 / 86_400.0;
```

The recency weight formula itself is unchanged (half-life 730 days, floor 0.85). Only the anchor point shifted from ingest time to event time.

---

## Files Changed

| File | Type | Change |
|------|------|--------|
| `brain/tools/stamp_event_times.py` | New | Historical backfill script |
| `brain/tests/test_stamp_event_times.py` | New | 4 tests |
| `brain/ingest/fact_curator.py` | Modified | `source_event_time` param added to `_save_fact`, `_curate_one`, `curate_facts` |
| `brain/tests/test_fact_curator.py` | Modified | 2 new tests (source_event_time fallback + LLM wins) |
| `brain/tools/backfill_facts.py` | Modified | `process_session` reads `ended_at`, threads through `_run_extraction` |
| `brain/tests/test_backfill_facts.py` | Modified | 1 new test (ended_at forwarded) |
| `brain/rust/src/brain.rs` | Modified | Age calc uses `event_time.unwrap_or(timestamp)` |

---

## Test Coverage

- 4 tests: stamp passes (session, cursor, no-session, idempotent)
- 2 tests: `source_event_time` fallback + LLM precedence
- 1 test: `ended_at` forwarded through full backfill call chain
- 1 Rust test: `event_time` gives correct age vs. `timestamp` fallback
- All 43 Python + 96 Rust tests green post-merge

---


