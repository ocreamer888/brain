# Phase 7 — Feedback signals and observability (start plan)

**Status:** Implemented on branch `feature/phase7-feedback` (see `docs/PHASE7.md`).

**Relationship to prior work:** Phase 6 completed data migration into the Rust brain (`docs/PHASE6_MIGRATION.md`). Phase 7 is the **first evolution milestone** from `docs/plans/2026-04-07-possible-evolution-neural-memory-to-autonomy.md` — specifically **Path A1 (feedback signal layer)** plus minimal **retrieval observability** so later phases (reranker, adapters) have data and baselines.

This is **one possible** Phase 7; you can narrow scope further if you prefer only feedback *or* only metrics first.

---

## Goal (Phase 7)

1. Capture **structured feedback events** when users or tooling accept, reject, or correct retrieved or saved memories (and optionally rank search results).
2. Persist them **separately** from core memory rows so training exports do not pollute semantic search.
3. Add **lightweight operational metrics** (counts, latency hooks placeholders) so you can prove signal volume before building a reranker.

---

## Non-goals (explicit)

- No online weight updates to ONNX/embedder in Phase 7.
- No full reranker training pipeline (that is a later phase).
- No claim of AGI or biological-style learning.

---

## Success criteria (exit gates)

| Gate | Criterion |
|------|-----------|
| G1 | Feedback schema is documented and versioned (JSON or SQL columns). |
| G2 | Events can be appended from at least **two** paths (e.g. API + one hook or CLI). |
| G3 | Export job produces a **JSONL** (or CSV) suitable for offline analysis without loading full `memories`. |
| G4 | Tests cover append + idempotency basics + export shape. |
| G5 | Optional: simple dashboard query or `get_stats`-style summary for feedback counts. |

**Decision gate before Phase 8:** If event volume is near-zero after 1–2 weeks of normal use, revisit **where** feedback is collected (UI/hooks/API) before investing in reranker.

---

## Workstreams

### WS1 — Schema and storage

**Options (pick one primary):**

- **A. SQLite table** in same DB as memories (e.g. `feedback_events`) — simplest for single-machine brain.
- **B. Append-only JSONL** under `~/.brain/` or repo-local path — simplest to ship, weaker for concurrent writers.

**Recommended:** **A** for consistency with `MetadataStore` / `brain/rust/src/store.rs`.

**Event fields (minimal):**

- `id` (UUID), `ts` (RFC3339), `event_type` (`accepted` \| `rejected` \| `edited` \| `ranked` \| `dismissed`), `memory_id` (optional), `query` (optional), `session_id` (optional), `project` (optional), `source` (e.g. `brain_api`, `mcp`, `hook`), `payload` (JSON blob for extras).

**Tasks:**

1. Add migration or `CREATE TABLE IF NOT EXISTS` in store open path.
2. Add `append_feedback(...)` and `list_feedback_since(ts)` or export function.
3. Unit tests in `brain/rust` (store + brain facade if exposed).

---

### WS2 — Surfaces (how events get in)

**Minimum viable surfaces (choose 2):**

1. **Rust API** (`brain/rust/src/bin/brain_api.rs`): `POST /feedback` with API key auth, same rate-limit story as other routes.
2. **MCP tool** (`brain/mcp/server.py`): optional tool `record_feedback` so Claude Code can log explicit feedback without new HTTP client work.

**Later (optional in Phase 7):**

- Hook scripts that call API or append via small CLI.

**Tasks:**

1. Define request/response types; validate `event_type`.
2. Wire to `MetadataStore` (or shared lib if Python calls Rust — if Python-only path, duplicate minimal append to JSONL with same schema file in `brain/`).

---

### WS3 — Export and analysis

**Tasks:**

1. `brain/tools/export_feedback.py` (or `cargo run --bin brain_export_feedback`) emitting JSONL lines.
2. Document one-liner: “export last N days for labeling review.”

---

### WS4 — Observability baseline (lightweight)

**Tasks:**

1. Extend `get_stats` (Rust) or parallel `/stats` JSON with `feedback_events_total` (and maybe last event time).
2. Optional: log structured line on `search` (query length, result count, ms) behind `BRAIN_LOG_SEARCH=1` — **only if** you want volume metrics before building reranker; keep PII-safe (truncate query in logs).

---

## Suggested order of execution

1. WS1 schema + tests (foundation).
2. WS2 surface #1 (HTTP API) — highest leverage for automation.
3. WS3 export script.
4. WS2 surface #2 (MCP) if you use MCP daily.
5. WS4 stats extension.
6. Run 1–2 weeks, review export volume → **gate decision** for Phase 8.

---

## Files likely to touch (reference)

| Area | Files (indicative) |
|------|-------------------|
| Store | `brain/rust/src/store.rs`, migrations if any |
| API | `brain/rust/src/bin/brain_api.rs` |
| Types | `brain/rust/src/types.rs` or new `feedback.rs` |
| MCP | `brain/mcp/server.py` |
| Tests | `brain/rust` unit tests; `brain/tests/` if Python export |
| Docs | `docs/BRAIN.md` or new `docs/PHASE7.md` when Phase 7 is *done* |

---

## Risk notes

- **Privacy:** feedback may contain queries; treat export files like secrets-adjacent; document retention.
- **Spam:** rate-limit feedback endpoint like `/save` / `/search`.
- **Scope creep:** do not add reranker training in Phase 7; only capture and export.

---

## Definition of done (Phase 7 complete)

- [x] Storage + API (and optional MCP) live behind same auth patterns as existing brain API.
- [x] Export path documented and tested.
- [x] Stats or documented query for event counts.
- [x] Short `docs/PHASE7.md` (or section in `docs/BRAIN.md`) describing how to record feedback and export — **only after implementation**.

---

## After Phase 7

Per the evolution doc, **Phase 8** candidates: retrieval evaluation harness + reranker prototype (Path A2), gated on feedback quality and volume from Phase 7.


<!-- brain-linker -->
## Related
- [[brain-graph/conversation/User i want to verify what kind of strong features would thi]]
- [[brain-graph/pattern/Edited Usersmacm1airDocumentsAIbrainrustsrcbrain.rs ( memori]]
- [[brain-graph/conversation/User]]
- [[brain-graph/solution/Edited Usersmacm1airDocumentsAIbrainrustsrcbrain.rs pub stru]]
- [[brain-graph/solution/Edited Usersmacm1airDocumentsAIbrainrustsrcbrain.rs fn test_]]
<!-- /brain-linker -->
