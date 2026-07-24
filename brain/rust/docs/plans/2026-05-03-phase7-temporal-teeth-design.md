# Phase 7 — Temporal Teeth

## Problem

All 14,904 facts have `event_time = NULL`. Recency decay uses `metadata.timestamp`
(ingest time = May 2026 for the entire historical batch), so every fact looks equally
fresh. The brain cannot distinguish "decided last week" from "decided two years ago."

## Why LLM extraction failed (gate check)

0.3% parse rate (42/13,180). Source corpora — Cursor bubbles, Perplexity exports —
contain almost no inline dates the LLM can extract.

## Solution

Two-part fix: stamp historical facts with representative dates, then wire event_time
into the search ranking.

### Part 1 — Historical stamp backfill

One-time SQL UPDATE pass. We know the rough age of each source:

| Source | Facts | Stamp | Rationale |
|---|---|---|---|
| Claude Code sessions (193 sessions) | ~1,284 | `ended_at` from session JSON | Real timestamps available |
| Cursor / Perplexity (session_id != '') | ~11,135 | `2025-07-01` | Cursor backup made Feb 2026; most chats from 2025 |
| No session_id | ~2,485 | `2025-01-01` | Oldest/least certain batch |

Result: 100% of facts get an event_time. Ordering is approximate but honest.

### Part 2 — Rust search ranking

Switch age calculation in `brain/rust/src/brain.rs` from:
```rust
let age_days = (now - memory.metadata.timestamp)...
```
to:
```rust
let effective_time = memory.metadata.event_time.unwrap_or(memory.metadata.timestamp);
let age_days = (now - effective_time)...
```

Safe now because Part 1 ensures every fact has event_time.

### Part 3 — Forward path

`brain/tools/backfill_facts.py`: when processing a session file, read `ended_at` and
pass it as `event_time` through `_run_extraction` → `curate_facts` → `_save_fact`.
LLM-extracted event_time takes precedence; session `ended_at` is the fallback.

## Expected recency weights (post-Phase 7)

| Fact age | recency_w |
|---|---|
| Today (new session) | ~1.000 |
| Claude Code sessions (Mar–May 2026) | ~0.999 |
| Cursor/Perplexity stamp (Jul 2025) | ~0.978 |
| Oldest batch stamp (Jan 2025) | ~0.969 |
| 2 years old | ~0.925 |

Range 0.85–1.0. Recency is a tiebreaker, not a dominant signal.

## Gate

After implementation: extract one new session via `backfill_facts.py --file`. Verify
the resulting facts have `event_time = ended_at` from the session JSON.
Check DB: `SELECT COUNT(*) FROM memories WHERE type='"fact"' AND event_time IS NULL`
should return 0.

## Files changed

- `brain/rust/src/brain.rs` — 4-line change to age calculation
- `brain/tools/backfill_facts.py` — pass event_time from session metadata
- `brain/ingest/fact_curator.py` — accept source_event_time fallback in `_save_fact`
- New script: `brain/tools/stamp_event_times.py` — one-time historical backfill
