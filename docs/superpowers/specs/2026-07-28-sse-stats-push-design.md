# SSE Stats Push — Design

**Date:** 2026-07-28  
**Status:** Approved for implementation planning  
**Goal:** Stop periodic `GET /stats` polling in the Brain Viewer. Keep dashboard/sidebar counts exact by pushing a full `BrainStats` snapshot on each live memory SSE event.

## Problem

The viewer `StatsProvider` polls `GET /stats` every 10 seconds. Dashboard also refetches on every live-feed event. That produces noisy API logs (`[BRAIN API] GET /stats -> 200 (0ms)`) and duplicates work: the app already has an SSE live stream for saves.

## Decision

**Approach A / variant 1:** Attach a full stats snapshot to every `MemoryEvent` on `/v1/stream`.

Rejected alternatives:


| Option                                  | Why not                                               |
| --------------------------------------- | ----------------------------------------------------- |
| B — client increments counts from event | Can drift on dedupe / delete / curate                 |
| C — refetch `/stats` on each SSE event  | Exact, but still one GET per save; no timer only      |
| Tagged union / second stats SSE channel | Extra protocol complexity for a local single-user app |




## Architecture

```
page load → GET /stats once → StatsProvider state
     │
save_memory (insert or near-dupe notify)
     → get_stats()
     → MemoryEvent { id, snippet, timestamp, memory_type, stats }
     → SSE /v1/stream
     → FeedProvider updates feed (ignores stats for cards)
     → StatsProvider replaces stats from evt.stats
```

- Drop `setInterval` poll in `StatsProvider`.
- Drop Dashboard `refetch` on `feed[0].id`.
- Keep `GET /stats` for cold start and reconnect resync only.



## Backend



### `MemoryEvent`

Extend `brain::MemoryEvent` with `stats: Option<BrainStats>` (serde: skip when `None`). When present, same shape as `GET /stats` / `BrainStats` today:

- `total_memories`
- `total_sessions`
- `save_count_this_session`
- `feedback_events_total`
- `feedback_last_event_ts`
- `by_type`



### Emit sites

Both existing broadcast paths in `Brain::save_memory` must attach stats:

1. Successful insert
2. Near-duplicate skip (still notifies live feed today)

After the write/notify decision, call `get_stats()`, set `stats: Some(...)`, then `tx.send(...)`.

No new HTTP endpoint. `GET /stats` remains for initial load and reconnect.

### Failure behavior

If `get_stats()` fails during save:

- Memory write still succeeds.
- Still emit the memory event with `stats: None` (non-fatal).
- UI keeps last known counts when `stats` is absent.



## Frontend



### `StatsProvider` (`brain/rust/ui/src/context/StatsContext.jsx`)

- On mount: one `GET /stats`.
- Remove `setInterval(..., 10_000)`.
- When an SSE/feed event includes `stats`, `setStats(evt.stats)`.
- Keep `refetch` for manual use and reconnect resync.



### `FeedProvider` (`brain/rust/ui/src/context/FeedContext.jsx`)

- Parse `stats` on incoming events.
- Apply into stats state via shared setter/callback (preferred) so updates work on every view, not only Dashboard.
- Feed cards continue to use `id` / snippet / `memory_type` / timestamp only.



### `Dashboard`

- Remove the `useEffect` that calls `refetch` when `feed?.[0]?.id` changes.
- Stat cards read `useStats()` only.



## Out of scope (v1)

- Emitting SSE (with stats) on delete / curate / supersede paths that do not already broadcast `MemoryEvent`.
  - Consequence: counts can lag until the next save or a reconnect/`refetch`.
  - Follow-up if those mutations become common while the viewer is open.



## Compatibility

- Events missing `stats` (old servers, failed attach): UI must **not** clear existing stats.
- `GET /stats` response shape unchanged.



## Success criteria

1. Viewer open and idle → **zero** periodic `/stats` lines in API logs.
2. Save a memory → live feed updates **and** sidebar/dashboard counts update **without** an extra `GET /stats`.
3. Hard refresh / SSE reconnect → one `GET /stats` resync; then push-only again.



## Tests

- Rust: after `save_memory`, subscribed `MemoryEvent` includes `stats.total_memories` matching a fresh `get_stats()`.
- Rust: near-dupe notify path also includes `stats`.
- UI (optional smoke): event with `stats` updates context; no interval timer registered.



## Non-goals

- Optimistic client-side count math.
- A second SSE endpoint for stats.
- Changing hybrid search, ingest, or MCP tool behavior.

