# Memory Contract (Stage 1)

Brain stores and ranks memories. It does not plan or act.

**Related:** `docs/superpowers/specs/2026-10-16-trustworthy-memory-and-advisory-routing-design.md`  
**Implementation plan:** `docs/superpowers/plans/2026-10-16-trustworthy-memory-contract.md`

## Field meanings (verified)

| Field | Storage | Meaning | Must not be treated as |
| --- | --- | --- | --- |
| `id` | `memories.id` | Stable id | |
| `content` | text | Memory body | |
| `type` | `memory_type` | One of `MemoryType` | |
| `project` | string | Project label (cwd/folder) | Structured project entity |
| `timestamp` | datetime | Prefer: when Brain observed/ingested the row; see Time contract | Always equal to event occurrence time |
| `event_time` | optional datetime | When the fact/event occurred | Ingest/observe time |
| `source` | `MemorySource` | Ingestion origin | Source quality / trustworthiness score |
| `salience` | f64 | Extractor confidence / UI audit | Retrieval weight (Phase 6: β=0.0) |
| `importance` | f64 | Priority hint | Calibrated confidence |
| `parent_id` | optional | Fact → episode parent | General semantic derivation |
| `superseded_by` | optional | Id of newer fact (curator UPDATE/MERGE) | Bidirectional typed graph edge |
| `derived_from` *(legacy name)* | optional string | Extractor model + prompt version (e.g. `ollama/.../v1`) | Parent memory id |
| `extracted_by` *(target name)* | same column after Stage 1 rename | Same as above | Parent memory id |
| `derived_from_memory_id` | reserved / later | Real parent-memory derivation | Extractor stamp |
| `outcome` | `fact_type` label in extractor | Fact classification tag | Action / execution result |
| `mentions` | `edges.relation_type` default | Extraction link memory→entity | Semantic claim (`supports`, etc.) |

## Time contract

1. Write **event occurrence** to `event_time`.
2. Write **Brain first saw this** to `timestamp` (documented alias: `observed_at`).
3. Some ingest paths currently pass historical session times into `timestamp` while leaving `event_time` null — inventory and fix under Stage 1 Task 3 (`docs/MEMORY_TIME_INVENTORY.md` once created).

Ranking already prefers `event_time` when present (`brain.rs` recency path).

## Feedback vs confidence

| Signal | Location | Stage 1 rule |
| --- | --- | --- |
| Host/user feedback | `feedback_events` / `record_feedback` | Keep; extend in Stage 2 with route/decision events |
| Extractor salience | `memories.salience` | Store for audit; do not use in hybrid score |
| Corroboration confidence | `brain/tools/confidence_score.py` | Shadow report only — do not persist until demotion safety passes |

## Graph / relations

- Only relation in production: `"mentions"`.
- `graph_expand` stays **default off** until `brain/tools/graph_expand_ab.py` returns PASS (`docs/ENTITY_EDGE_GRAPH.md`).
- New relation types must improve a named metric on a gold set before shipping.

## Identity statement

> Brain is a provenance-aware hybrid retrieval and memory-ranking system that observes an external host agent, with a future advisory routing layer — not yet an executive brain.
