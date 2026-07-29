# Phase 6 — Salience Calibration

## Decision: beta=0.0 (salience excluded from retrieval scoring)

**Date:** 2026-05-02

### Calibration data

Across a curation run over existing sessions, the ADD vs. IGNORE populations showed:

| Decision | avg_salience |
|----------|-------------|
| ADD      | 0.754       |
| IGNORE   | 0.792       |

The extractor assigns *higher* salience to facts that the curator later ignores. There is no correlation between extractor confidence and fact novelty — IGNOREs score 5% higher on average than ADDs.

### Conclusion

Using salience as a retrieval weight would demote novel facts and promote duplicates. Setting beta=0.0 keeps salience out of all scoring paths.

Salience is **stored** in SQLite for:
- Curator UI audit (promote/reject in the Facts tab)
- Future supervised retraining if a better calibration signal is available

### Baseline P@1 (2026-05-02)

Eval harness: `brain/tools/retrieval_eval_kfold.py --facts-only --gold-semantic brain/tests/fixtures/eval/facts_queries.jsonl`
Gold set: 20 hand-written queries across projects (cursor, perplexity, AI, ocreamer, sicop, frontend)

| alpha | P@1   | P@5   | P@10  | MRR   |
|-------|-------|-------|-------|-------|
| 0.00 (BM25 only) | **1.000** | 1.000 | 1.000 | 1.000 |
| 0.30–1.00 (hybrid/vector) | 0.600 | 0.900 | 0.950 | 0.723 |

**Floor:** future changes must not drop P@1 by more than 0.05 from these baselines.

### Implementation

- `brain/rust/src/types.rs` — `salience` stored as `f32` in `MemoryMetadata`
- `brain/rust/src/brain.rs` — `search()` applies recency and RRF; salience not included
- `brain/rust/src/store.rs` — `update_salience(id, value)` for UI-driven updates
- `brain/rust/src/bin/brain_api.rs` — `PATCH /memories/:id` endpoint (`{"salience": 1.0}`)
- `brain/rust/static/` — Facts tab in web viewer: filter, episode expand, Reject/Promote buttons
