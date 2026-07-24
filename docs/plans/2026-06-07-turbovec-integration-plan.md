# Turbovec Integration Plan
**Date:** 2026-06-07  
**Status:** ✅ Phase 1 SHIPPED (2026-06-07) · Phase 2 WON'T DO (see below)  
**Risk:** Low (Phase 1) / Medium (Phase 2)

---

## Outcome (2026-06-07)

Phase 1 shipped and deployed to the live launchd service (`com.brain.api`).
A follow-on change — building the `Brain` once at boot and sharing it across
requests — turned the index swap into a large end-to-end speedup.

**Commits (branch merged to `main`):**
- `f03c2ba` feat(brain-index): replace f32 brute-force VectorIndex with turbovec 4-bit
- `92f9d4b` perf(brain-api): build Brain once at boot, share across requests

**Final decisions vs. this plan:**
- **4-bit, not 3-bit** — shared/battle-tested `repack()` path; +1.7 MB vs 3-bit is irrelevant. (Plan updated throughout.)
- **Wrapper is `uuid ↔ u64` only** — `IdMapIndex` already owns id↔slot mapping + swap-remove, so the plan's manual slot tables were dropped as redundant.
- **distance = 1 − score** — turbovec returns a length-renormalized inner-product score; embeddings are L2-normalized so this equals cosine, preserving the old contract.

**Measured on the real 17,408-vector corpus (ONNX, not mock):**

| Check | Result |
|---|---|
| recall@10 vs exact f32 cosine | **0.9758** |
| top-1 agreement vs exact | **1.0000** (1000 queries) |
| self-retrieval | **1.0000** |
| delete correctness / empty / zero-query | PASS, no panics |
| end-to-end HTTP top-5 (old vs new) | identical ordering, Δdistance < 0.007 |
| `/search` latency | 310 ms → **~18 ms** (caching) |
| `/stats` latency | 300 ms → **~11 ms** (caching) |
| boot (index built once) | **~350–530 ms** |
| tests | 99 lib + integration green |

Validation harness: `brain/rust/src/bin/tv_validate.rs` (compares quantized
vs exact cosine on a real DB; run `tv_validate <db> [sample]`).

> **RSS note:** the plan's "51 MB → 6.7 MB RAM" was only realizable once the
> index is *held* in memory. The old server rebuilt and dropped the index per
> request, so the win materialized only after the boot-once caching change.

---

## Goal

Replace Brain's `VectorIndex` (51 MB f32, brute-force scalar search) with turbovec 4-bit (6.7 MB, SIMD NEON). No behavior change visible from outside.

### Verified baseline (from SQLite + code)

```
17,410 memories × 768 dims × 4 bytes = 51 MB RAM (VectorIndex)
                                      + 51 MB SQLite BLOB
                                      = 102 MB for embeddings alone
Search: 17,410 × 768 = 13.4M scalar multiply-adds per query (no SIMD)
```

### Expected outcome after Phase 1

| Metric | Before | After |
|---|---|---|
| Embedding RAM | 51 MB | 6.7 MB |
| Search compute | Scalar f32 loop | SIMD NEON (Mac Studio, Apple Silicon) |
| Startup bulk-load | 51 MB from SQLite | Same (Phase 2 handles disk) |
| Recall quality | Baseline | D_prod ≤ 0.0000585 loss — unmeasurable |
| Insert latency | O(1) | O(1) + ~2-5ms repack on next search |

---

## Research Basis

- **TurboQuant paper**: Google Research, ICLR 2026. Near-Shannon-optimal vector quantization.
- **turbovec repo**: `RyanCodrai/turbovec` — 6,900 stars, 25 releases, version 0.8.0.
- **Crate name**: `turbovec = "0.8.0"` (verified from `turbovec/Cargo.toml`).
- **Bit-width = 4 (chosen over 3)**: 4-bit is turbovec's battle-tested path — every example, benchmark, and integration targets it. It uses the shared `pack.rs::repack()`. 3-bit takes a dedicated `repack_3bit()` that emits two separate arrays (`sub_codes` + `plane2_blocked`) — more code, more bug surface, for a 1.7 MB saving (6.7 MB vs 5.0 MB) that is irrelevant at Brain's scale on a Mac Studio. Both are effectively zero-error at d=768.
- **d=768 accuracy**: At 4-bit, d=768: D_prod ≤ 0.045/768 ≈ 0.0000585 per unit vector (≈4× tighter than 3-bit). Negligible.
- **SIMD**: ARM NEON kernel confirmed in `search.rs`. Mac Studio is Apple Silicon. 12–20% faster than FAISS PQ on ARM.

---

## Phase 1 — In-Memory Index

**Files changed**: 3  
**Schema changed**: No  
**Rollback**: `git revert` — 30 seconds  

---

### Step 1.1 — Add Dependency

**File**: `brain/rust/Cargo.toml`

```toml
turbovec = "0.8.0"
```

New transitive deps brought in: `faer`, `ndarray+BLAS`, `rayon`, `rand_chacha`, `rand_distr`, `statrs`, `ordered-float`. First compile will be slower. Runtime is unaffected.

---

### Step 1.2 — Rewrite `VectorIndex`

**File**: `brain/rust/src/index.rs` — full rewrite

**Why `IdMapIndex`**: Brain calls `delete_memories()` (`brain.rs:508`). `IdMapIndex` supports O(1) `remove(u64)`. `TurboQuantIndex` does not.

**Why 4-bit**: 8× compression. turbovec's shared/battle-tested `repack()` path (3-bit uses a separate, more complex `repack_3bit()`). Inner-product distortion at d=768 is negligible (see Research Basis); the 1.7 MB given up vs 3-bit is irrelevant.

**ID mapping required**: turbovec uses `u64` IDs; Brain uses UUID strings. A side table bridges them.

```rust
use std::collections::HashMap;
use std::sync::atomic::{AtomicU64, Ordering};
use turbovec::{IdMapIndex, AddError};
use crate::BrainError;

pub struct VectorIndex {
    inner: IdMapIndex,
    uuid_to_slot: HashMap<String, u64>,
    slot_to_uuid: HashMap<u64, String>,
    next_slot: AtomicU64,
}

impl VectorIndex {
    pub fn new(dims: usize) -> Self {
        // IdMapIndex::new(dims, 4).expect("768 is multiple of 8")
    }

    // Bulk insert — called once at startup with all existing memories.
    // Required so TQ+ calibration sees 17,410+ vectors, not just 1.
    pub fn bulk_insert(&mut self, ids: &[&str], flat_embeddings: &[f32]) {
        // assign slots 0..n
        // inner.add_with_ids_2d(flat_embeddings, dims, &slots)
        // populate uuid_to_slot + slot_to_uuid
    }

    pub fn insert(&mut self, id: &str, embedding: &[f32]) {
        // single insert — for new saves after startup
        // inner.add_with_ids_2d(embedding, dims, &[next_slot])
        // update side tables
        // NOTE: invalidates BlockedCache → next search repacks (~2-5ms)
    }

    pub fn remove(&mut self, id: &str) {
        // 1. look up slot
        // 2. capture last_slot = inner.len() - 1 and last_uuid
        // 3. inner.remove(slot)  — IdMapIndex does swap-remove internally
        // 4. update uuid_to_slot + slot_to_uuid for the swapped entry
    }

    pub fn search(&self, query: &[f32], n: usize) -> Vec<(String, f32)> {
        // inner.search(query, n) → (scores, u64_ids)
        // map u64 → uuid via slot_to_uuid
        // return Vec<(String, f32)>  — identical contract to today
    }

    pub fn len(&self) -> usize { self.inner.len() }
    pub fn is_empty(&self) -> bool { self.inner.is_empty() }

    pub fn prepare(&self) {
        self.inner.prepare()  // pre-builds SIMD BlockedCache
    }

    // REMOVED: apply_mean_centering() — turbovec TQ+ subsumes this
    // REMOVED: save() / load() — Brain rebuilds index from SQLite on startup
}
```

**Swap-remove logic** (critical — gets wrong without this):

```rust
pub fn remove(&mut self, id: &str) {
    let Some(&slot) = self.uuid_to_slot.get(id) else { return };
    let last_slot = (self.inner.len() as u64).saturating_sub(1);
    let last_uuid = self.slot_to_uuid.get(&last_slot).cloned();

    self.inner.remove(slot);

    self.uuid_to_slot.remove(id);
    self.slot_to_uuid.remove(&slot);

    if slot != last_slot {
        if let Some(moved_uuid) = last_uuid {
            self.uuid_to_slot.insert(moved_uuid.clone(), slot);
            self.slot_to_uuid.insert(slot, moved_uuid);
        }
    }
}
```

---

### Step 1.3 — Remove Mean-Centering

**File**: `brain/rust/src/brain.rs` — **delete lines 96–111**

```rust
// DELETE THIS ENTIRE BLOCK:
// T2: corpus mean-centering — subtract shared language baseline from all embeddings.
// Computed once at open; new inserts are centered with this (slightly stale) mean.
if n_loaded > 0 {
    let dims = config.embedding_dims;
    let mut mean = vec![0.0f32; dims];
    for (_, emb) in &pairs {
        for (m, e) in mean.iter_mut().zip(emb.iter()) {
            *m += *e;
        }
    }
    let n_f32 = n_loaded as f32;
    for m in mean.iter_mut() {
        *m /= n_f32;
    }
    index.apply_mean_centering(mean);
}
```

**Why**: Turbovec's TQ+ applies per-coordinate affine calibration automatically. Running Brain's mean-centering on top corrupts the coordinate distribution that TQ+'s Lloyd-Max codebook expects. They conflict.

---

### Step 1.4 — Replace Line-by-Line Insert With Bulk Insert + `prepare()`

**File**: `brain/rust/src/brain.rs` — replace lines 88–94

Current (bad for TQ+ calibration):
```rust
let mut index = VectorIndex::new(config.embedding_dims);
let pairs = store.get_embeddings_for_index()?;
let n_loaded = pairs.len();
for (id, emb) in &pairs {
    index.insert(id, emb);   // 17,410 individual inserts = calibration from 1 vector
}
eprintln!("[brain] loaded {} embeddings from SQLite", index.len());
```

New:
```rust
let mut index = VectorIndex::new(config.embedding_dims);
let pairs = store.get_embeddings_for_index()?;
let n_loaded = pairs.len();

if n_loaded > 0 {
    // Batch insert: TQ+ calibration sees all vectors at once (not just the first)
    let ids: Vec<&str> = pairs.iter().map(|(id, _)| id.as_str()).collect();
    let flat: Vec<f32> = pairs.iter().flat_map(|(_, e)| e.iter().copied()).collect();
    index.bulk_insert(&ids, &flat);
    // Pre-build SIMD layout — hides repack cost in startup, not first search
    index.prepare();
}
eprintln!("[brain] loaded {} embeddings from SQLite", index.len());
```

**Why batch matters**: TQ+ calibration freezes on the first `add_with_ids_2d` call. If that call contains 1 vector, calibration is garbage (needs ≥1,000 samples). Batch insert with all 17,410 vectors gives maximum calibration quality.

---

## Phase 2 — SQLite BLOB Compression — ❌ WON'T DO (2026-06-07)

**Decision: not worth it.** The two prizes (RAM via turbovec, 17–27× speed via
boot-once caching) are already banked. Phase 2 trades real migration risk for a
benefit that no longer matters:

1. **~46 MB disk on a Mac Studio is irrelevant** — same logic that picked 4-bit over 3-bit.
2. **The "10× smaller startup I/O" win evaporated** — the index is now built **once** at boot (~350 ms), not per request. Optimizing a once-per-launch 51 MB read isn't worth a schema migration.
3. **Medium risk for ~zero gain** — schema migration, irreversible without backup.
4. **More complex than written** — storing/reloading per-row packed codes needs extra turbovec plumbing (or switching to turbovec's `.tvim` file persistence), not just a BLOB column.

Original sketch (kept for reference only, do not implement):
1. ~~Add `embedding_tq BLOB` column via migration in `store.rs::create_tables()`~~
2. ~~Write 4-bit packed bytes (384 bytes) instead of raw f32 (3,072 bytes)~~
3. ~~`get_embeddings_for_index()` reads `embedding_tq` if present, falls back to `embedding`~~
4. ~~Keep `embedding` column until validated, then drop~~

If disk ever becomes a real constraint, prefer turbovec's native `.tvim`
persistence over a SQLite BLOB column.

---

## Test Plan

### Before merging Phase 1

1. **Compile**: `cargo build --release` — confirms dependency resolves, no linker errors
2. **Unit tests**: `cargo test` — all existing `index.rs` tests must pass unchanged
3. **Accuracy spot-check**: search 5 known queries before and after — expect same top-1 result for each
4. **Memory**: `ps aux | grep brain_api` — expect RSS down ≥40 MB
5. **Delete correctness**: insert 3 memories → delete middle → search — no panic, no ghost results
6. **Empty index**: search on fresh empty Brain — no panic (turbovec handles gracefully)
7. **TQ+ calibration**: add only 1 memory to empty Brain, search — should work (identity calibration fallback per turbovec code)

### Passing criteria
- All existing `cargo test` green
- RSS reduced ≥40 MB
- Top-1 search result identical for 5 test queries
- No panics on remove, empty search, or fresh Brain

---

## Risks and Mitigations

| Risk | From codebase | Mitigation |
|---|---|---|
| TQ+ calibration poor on fresh Brain (< 1,000 memories) | `encode.rs`: "identity calibration fallback when degenerate" | Fallback exists. Brain has 17,410 — not a real risk today |
| BlockedCache rebuild on every insert (~2-5ms) | `lib.rs`: mutation invalidates derived caches | Acceptable — saves are rare vs searches. `prepare()` at startup hides startup cost |
| First search after restart pays QR decomp (~10-50ms) | `rotation.rs`: `OnceLock` lazy init of 768×768 matrix | `prepare()` call at startup forces this before first request |
| `add()` panics on contract violation | `error.rs`: only `add_2d` returns Result | Use `add_with_ids_2d()` exclusively — never `add()` |
| Swap-remove corrupts side tables | `id_map.rs`: IdMapIndex syncs its own tables | Wrapper must also update `uuid_to_slot` for the swapped entry (see Step 1.2 code) |
| Build time increase | `faer`, `ndarray+BLAS` are large crates | One-time. Runtime unaffected |

---

## Rollback

Phase 1: `git revert` the 3 changed files. No SQLite changes. Done in 30 seconds.  
Phase 2: Restore from backup before migration. Keep `embedding` column as fallback until fully validated.

---

## Files Changed (Phase 1 Only)

| File | Change | Net lines |
|---|---|---|
| `brain/rust/Cargo.toml` | Add `turbovec = "0.8.0"` | +1 |
| `brain/rust/src/index.rs` | Full rewrite with wrapper struct | ~+150 |
| `brain/rust/src/brain.rs` | Delete mean-centering, batch bulk-load, add prepare() | ~-10 |

**Total**: ~141 net lines. 3 files. Zero changes to Python hooks, MCP tools, API contracts, or web UI.
