# Cognitive Architecture Spec — Brain as a Memory-Grounded Agent Loop

**Status:** Proposed — awaiting approval before any schema or API changes (same gate discipline as the doc below).
**Supersedes nothing. Extends:**
- `docs/MEMORY_CONTRACT.md` (Stage 1 field contract)
- `docs/superpowers/specs/2026-10-16-trustworthy-memory-and-advisory-routing-design.md` (Stage 1–4 roadmap, gates G1–G4)
- `docs/architecture/system-diagrams.md` (runtime/storage diagrams)
**Source vision:** `docs/architecture/I designed this for brain, what do u think_.md` (Perplexity design conversation), plus the owner's hand-drawn temporal-layer sketches (2026-10-21): `docs/architecture/sketches/2026-10-21-layers-full.png`, `docs/architecture/sketches/2026-10-21-layers-zoom.png`.
**Revised 2026-10-21:** after review with the owner. Added §8 (temporal layers and layer confidence, the owner's core model), corrected §0, §2.1, §6.2 and §7, and added gates G8–G10. All data figures in §8 come from read-only queries against the live `brain/rust/brain.db` on 2026-10-21.

This document does three things: (1) gives the vision document's algebra a single, internally-consistent formal model; (2) verifies that algebra against the actual Rust implementation line-by-line, not by assumption; (3) turns each gap into a concrete, gated fix that upscales toward a cognitive architecture without violating the existing non-goals (no full executive yet, no `graph_expand` by default, no indiscriminate typed edges, no online weight retraining).

The 2026-10-16 design doc already got the big call right: **Brain retrieves and ranks. It does not plan or act.** Nothing here reopens that. What's new here is making the math underneath it rigorous enough to build on, and naming where today's code already (or doesn't yet) match it.

---

## 0. Headline finding — read this before the rest

The code **currently contradicts its own written contract**. `docs/PHASE6_SALIENCE.md` (2026-05-02) set `β = 0.0`: salience excluded from retrieval scoring, because calibration data showed curator-`IGNORE`d facts average *higher* salience (0.792) than curator-`ADD`ed ones (0.754) — using it would systematically promote near-duplicates and demote novel facts. `docs/MEMORY_CONTRACT.md` repeats this as a Stage 1 rule: *"Extractor salience → do not use in hybrid score."*

The live ranker in `brain/rust/src/brain.rs` (verified by reading the function, not inferred):

```rust
let salience_w = (1.0 + 0.3 * (sal - 0.5)).clamp(0.85, 1.15);   // brain.rs:437
let final_score = salience_w * recency_w * hybrid_score * knowledge_w;  // brain.rs:456
```

`salience_w` is live in every search today. I could not date exactly when this landed (the repo's git history starts from a single "Initial code-only brain tree" squash commit, so blame doesn't reach further back) — but the present-tense fact is verifiable by reading the function: **the documented `β=0.0` decision is not what's running.**

(`AGENTS.md` acknowledges salience as "already a live rank weight," but no document records why the Phase 6 decision was reversed or any new calibration behind it.)

This is Gap #0, not a future-roadmap item. It needs a decision before anything below proceeds, because §2's monotonicity and dominance properties and §4's routing validation both assume you know which modulators are actually "live and trusted" vs. "live and known-bad." Options, cheapest first:
- **G0a** — set `salience_w ≡ 1.0` (restore `β=0.0` exactly as documented), re-run the Phase 6 gold harness (`retrieval_eval_kfold.py --facts-only`) to confirm P@1 is back at/above the 2026-05-02 baseline.
- **G0b** — if someone deliberately re-enabled it and has newer calibration data showing it no longer anti-correlates with curator `ADD`, document that recalibration and keep it — but that calibration doesn't currently exist anywhere I found.
- **G0c** — leave as-is and accept the contract is currently aspirational, not enforced.

**Revised recommendation (2026-10-21): measure before reverting.** Three facts weaken a blind G0a:
- The Phase 6 evidence covered **extracted facts only** (curator `ADD` vs `IGNORE`). Salience on conversations, solutions, decisions, etc. was never measured either way.
- The UI's `PATCH /memories/:id {"salience": 1.0}` is effectively a manual "pin." Forcing `salience_w ≡ 1.0` silently disables it.
- Reverting first and measuring after is backwards when an on/off A/B on the same harness is cheap and read-only.

So: run `retrieval_eval_kfold.py` with `salience_w` live vs. neutral first, then decide. **Longer term, the owner's model (§8) replaces the meaning of salience entirely:** a fixed, once-assigned LLM score is the wrong signal. Confidence should come from a memory's position in its temporal layer stack, computed at query time. G0 is therefore an interim cleanup, and G8 is the real fix. **No change has been made. Changing `salience_w` alters live ranking for every search and needs sign-off.**

---

## 1. Formal model: the fix that matters most

The source document's algebra (`r = f(q,c,m,g,π)`, state `s_t=(q_t,c_t,M_t,g_t,π_t)`, transition `s_{t+1}=F(s_t,a_t,o_t)`) has a structural problem: it treats the *entire* tuple as evolving every turn. It doesn't. Three of its five components don't change per-turn at all, and the document never says so — which is exactly the kind of imprecision that would let a future router treat `g` (tools) or `π` (policy) as something to "update" per request, when in reality only `M` (memory) legitimately changes inside the fast loop.

### 1.1 Split state into exogenous input vs. owned state

```
Exogenous, supplied fresh each call (Brain/host do not own these):
  q_t   current query or goal
  c_t   current context

Owned, persists across calls, changes on its own timescale:
  M_t   memory store                — changes every save/curate/backfill (fast-ish)
  g_t   available tools/capabilities — changes on deploy/config change (slow)
  π_t   routing policy parameters    — changes on deliberate retrain/recalibration (slow)
```

A single turn is:

```
m_t = R(q_t, c_t, M_t)              Brain:  retrieve + rank   (owns this; exists)
r_t = f_{π_t}(q_t, c_t, m_t, g_t)    Brain:  advisory route    (does not exist; Stage 3)
p_t = P(q_t, c_t, m_t, r_t)          Host:   plan
a_t = A(p_t, g_t)                    Host:   act
o_t = O(a_t)                         Host/env: observe
M_{t+1} = U(M_t, q_t,c_t,m_t,r_t,p_t,a_t,o_t, feedback_t)   Brain: learn
g_{t+1} = g_t                        unchanged this turn
π_{t+1} = π_t                        unchanged this turn
```

This is the correction that makes the model match the actual division of labor: **the per-turn transition function only has one real degree of freedom, `M`.** `g` and `π` are step functions on a much slower clock (deploys, recalibration runs), not variables in the same transition `F`. Writing them as if they update every turn invites building infrastructure (versioning, locking, migration) for a problem that doesn't exist, while under-specifying the one that does (concurrent writers to `M_t` — see §6).

### 1.2 Fix the `f_π` notation collision

The source document uses `π` two incompatible ways: as a data argument to `f` ("routing policy or priority rules," passed in), and later, in its own "LLM-based version" section, as the *parameters of a distribution* (`r ~ π_θ(r|q,c,m,g,π)` — note `π` appears both as the thing being modeled and as one of its own inputs). That's a type error, not just sloppy notation: a policy can't simultaneously be the function and an argument to the function.

Fix: `π` parameterizes `f`, it is not passed to it. Write `f_{π_t}(q,c,m,g)`. Updating the policy (Stage 3 calibration, future RL-free tuning) means producing `π_{t+1}` out of band — a deliberate, logged, reversible deployment event — never a side effect of a single `/search` or `/save` call.

### 1.3 Retrieval must take the memory store as an argument

The source doc is inconsistent with itself across sections: §"algebra diagram" (and the 2026-10-16 design doc, correctly) write `m = R(q, c, M)`. The later "validate mathematically" and "is this an algorithm" sections drop `M` and write `m = R(q,c)`. Retrieval without a corpus argument is undefined — keep the 2026-10-16 doc's version, `m_t = R(q_t, c_t, M_t)`, everywhere. This is a correction to the *vision document*, not to the code (the code obviously does search against the store).

---

## 2. The real ranking function `R`, verified against code

The source document hypothesized `R` as a flat weighted sum:

```
S(x,q) = α·cos(x,q) + β·BM25(x,q) + γ·recency(x) + δ·salience(x) + ε·prior(x)
```

That is **not** what's implemented. Reading `brain.rs:330–500` directly, `R` is:

```
hybrid(x,q)   = α·cos_norm(x,q) + (1−α)·bm25_norm(x,q)     α = 0.7 default, per-request override
recency_w(x)  = 0.85 + 0.15 · 2^(−age_days(x) / 730)        age from event_time, fallback timestamp
salience_w(x) = clamp(1 + 0.3·(salience(x) − 0.5), 0.85, 1.15)   ⚠ see Gap #0 — documented to be off
knowledge_w(x)= clamp(1 + K_BASE + K_CLOSE_MAX·closeness(dist(x)) [+ K_PROJ if project filter], 1.0, 1.22)
                        — only for type=Knowledge, else 1.0
score(x,q)    = salience_w(x) · recency_w(x) · hybrid(x,q) · knowledge_w(x)
```

This is a **product**, not a sum: one query-dependent relevance term (`hybrid`) multiplied by up to three query-independent *modulators*. That structural difference matters for every validation technique the source document proposed, and it's good news once corrected — multiplicative, bounded modulators are provably safer than an unconstrained additive sum.

### 2.1 Relevance-dominance invariant (provable, not assumed)

Each modulator is bounded: `recency_w ∈ [0.85, 1.0]`, `salience_w ∈ [0.85, 1.15]` (contract says should be `≡1.0`), `knowledge_w ∈ [1.0, 1.22]` (non-knowledge: `=1.0`). So the combined modulator `mod(x) = salience_w·recency_w·knowledge_w` is bounded in roughly `[0.72, 1.40]` — a ratio of at most **~1.94×** between the best-case and worst-case modulator for any two memories.

**Claim:** if `hybrid(x1,q) / hybrid(x2,q) > 1.94`, then `score(x1,q) > score(x2,q)` regardless of recency/salience/knowledge, for any `x1, x2`.
**Proof:** `score(x1)/score(x2) = (hybrid(x1)/hybrid(x2)) · (mod(x1)/mod(x2))`. Since `mod(x1)/mod(x2) ≥ 0.72/1.40 ≈ 0.51`, and `hybrid(x1)/hybrid(x2) > 1.94`, the product exceeds `1.94 × 0.51 ≈ 1.0`. ∎

This is worth stating explicitly because it's a real safety property the current architecture already has, by construction, whether or not anyone designed it on purpose: **non-relevance signals can only ever re-rank within a ~2× band around true semantic/lexical relevance — they cannot invert a strong relevance gap.** Any new modulator (source-quality, conflict penalty, layer confidence from §8) should be designed to preserve this property: multiplicative, bounded close to 1.0, never additive and unbounded.

**Caveat: the guarantee covers `score`, not the final result list.** After sorting, `brain.rs:480–500` applies a type-diversity cap: when no type filter is set, no single memory type may fill more than 40% of the `n` results. That step can drop a high-`score` row, for example the 5th strongly relevant fact in a top-10, in favour of a weaker row of another type. So the dominance invariant holds for the ranked candidate list but **not** for what the host actually receives. Any eval of a new modulator should measure both before and after the diversity cut.

### 2.2 Corrected monotonicity property

The source doc's monotonicity axiom referenced a `sourceQuality(x)` term that doesn't exist in the ranker. Restated for what actually exists:

> For fixed `q`, and any two memories `x1, x2` with equal `hybrid(x1,q) = hybrid(x2,q)`: if `salience_w(x1) > salience_w(x2)` (all else equal), then `score(x1,q) > score(x2,q)`.

**Proof:** trivial — `score = salience_w · (positive constant)`, and multiplication by a larger positive factor strictly increases a positive product. ∎ The same holds independently for `recency_w` and `knowledge_w`. This gives you a cheap regression test: for any modulator you add or change, assert this property holds over a sample of pairs — if it doesn't, the modulator isn't implemented as a clean multiplicative factor and will break the dominance invariant in §2.1.

### 2.3 Fixing the ablation methodology

Because the ranker is multiplicative, the source doc's ablation instruction ("remove one term at a time," `S₋recency`) is wrong as written: literally dropping a multiplicative factor means setting it to **0**, which zeroes the entire score for every row, not a meaningful ablation.

**Fix:** ablation means setting the modulator to its **neutral value (1.0)**, not removing it:
```
S₋recency(x,q)  = salience_w(x) · 1.0        · hybrid(x,q) · knowledge_w(x)
S₋salience(x,q) = 1.0           · recency_w(x) · hybrid(x,q) · knowledge_w(x)
```
This is exactly what `docs/PHASE6_SALIENCE.md`'s own baseline table already does conceptually (comparing `alpha=0.0` vs `alpha∈[0.3,1.0]` against a fixed gold set) — the existing eval harness (`brain/tools/retrieval_eval_kfold.py`) is already structured correctly for this; the fix here is only to the *vision document's* description of ablation, so future contributors don't "ablate" a modulator by deleting it from the product.

### 2.4 Calibration — bounded ≠ probabilistic

`score(x,q)` is bounded (§2.1) but not a probability, and isn't comparable in an absolute sense across different queries (a `score=0.9` for one query and `score=0.9` for another don't mean "equally relevant" — `hybrid` itself is only loosely comparable across queries since BM25's scale depends on corpus statistics for that query's terms). The source doc's routing examples use hard thresholds (`confidence: 0.86`) as if `score` were already calibrated. It isn't.

**Fix, zero regression risk:** fit a monotone calibration map `g: score → P̂(relevant | score)` via isotonic regression against the existing labeled gold sets (`brain/eval/gold.jsonl`, `gold_semantic.jsonl`). Isotonic regression is **order-preserving by construction** — applying `g` after the fact cannot change which memory ranks above which other memory, so it cannot regress the Phase 6 P@1/P@5 floor. It only adds a second, calibrated number (`P̂`) alongside the existing `score`, for Stage 3 routing thresholds to consume instead of a magic number. This is additive and safe to ship independently of the routing work itself.

---

## 3. Learning: `U` is already two gated operators, not one online update

The source doc's `M_{t+1} = U(M_t, q,c,m,r,p,a,o)` reads as a per-step online update. The real system already has two separate paths, and one of them already implements the doc's own §7 "validate learning" proposal almost exactly:

**Append (fast, ungated):** `POST /save` → `M_{t+1} = M_t ∪ {row}`. No evaluation gate — correct, since a single new memory can't regress retrieval on its own and gating every save would be pure latency cost for no safety benefit.

**Curate (batch, currently ungated on outcome):** `curation_events` — 15,644 rows (`ADD`/`MERGE`/`UPDATE`/`IGNORE`) produced by `brain/ingest/fact_curator.py` in periodic runs, not per-request.

**Backfill-with-rollback (batch, already gated — this is the model to generalize):** `backfill_batches` table tracks `p1_before`, `p1_after`, `rolled_back`. This is a **working implementation** of the source doc's §7 regression-rate check:

```
ΔP@1 = p1_after − p1_before
commit the batch   iff  ΔP@1 ≥ −ε
else                    rolled_back ← 1   (revert)
```

**Proposed fix:** generalize this exact gate to every batch-mutating path, not just backfill — specifically `fact_curator.py`'s curation runs, which currently write 15,644+ decisions with no before/after check against the gold harness at all. Concretely: wrap curator runs the same way `backfill_batches` wraps backfills — snapshot P@1/P@5/MRR on the existing gold set before the run, apply the batch, re-measure, and roll back (restore `superseded_by`/row state) if the delta exceeds a tolerance. This turns the source document's abstract "RegressionRate" invariant into an enforced commit gate using infrastructure that already exists for one of the two batch paths — it's a generalization, not new infrastructure.

---

## 4. Route identification `f_π` — concrete, deterministic-first design

Nothing here exists yet (confirmed: no `route`/`router` logic anywhere in `brain/rust/src`, `jobs` table has 0 rows). Per the existing design doc's non-goal list and G3/G4 gates, this stays **advisory and Stage 3** — the host decides, Brain recommends. The source doc's own warning against a "giant central router" is correct; keep `f_π` small and deterministic, not an LLM call per request (that would add latency and cost to every turn for a decision most of the time trivially "answer").

Proposed concrete form, deliberately boring:

```
f_π(q, c, m, g) =
  clarify   if  ambiguity(q) > τ_amb                     (e.g. missing required slot, pronoun w/o antecedent)
  verify    if  conflict(m) = 1                           (see below — no new edge type required)
  search    if  max_i P̂(relevant | score_i) < τ_low       (calibrated score from §2.4; nothing in m clears bar)
  act       if  risk(q) ≥ ρ_high                          (requires host approval — §6.2)
  answer    otherwise
```

`conflict(m)` does **not** require a new `contradicts` edge type (which the existing design doc explicitly says must earn its place on a gold benchmark before shipping — the August graph-expand A/B already showed added edges can hurt, not help). Cheap proxy: flag conflict when the top-2 results have near-equal calibrated scores (`|P̂₁ − P̂₂| < ε`) but came from different `project`/non-overlapping `event_time` windows — a retrieval-time heuristic, not a stored semantic relation, consistent with "a relation should earn its place by improving a named metric" from the Memory Contract.

Validation order (already specified correctly in the 2026-10-16 doc — repeating it here because it composes with §2–3): confusion matrix + macro-F1 over a route-labeled gold set → high-risk recall specifically (a false negative routing a destructive request to `act` instead of `clarify` is categorically worse than a false positive routing a harmless request to `verify`) → only then, utility delta `ΔJ = J_{router+host} − J_{host-only}` on a held-out set, promoted toward enforcement only if `ΔJ > 0`.

---

## 5. Termination and risk invariants — made constructive

The source doc's invariants are correctly chosen but non-constructive. Two fixes that turn them into checkable code:

**Termination (was: `∃t: stop ∨ clarify ∨ safeFailure`, no witness).** Fix: every `Goal → Plan` (Stage 4 execution ledger, §6) carries `step_count ≤ N_max` and `elapsed ≤ T_max` as stored fields, checked on every step. This gives an actual proof by construction: the loop halts within `N_max` steps or `T_max` time, because the counter is monotonically incremented and bounded, not an existential claim resting on hope.

**Approval invariant (was: abstract `risk(a_t) ≥ ρ ⇒ approval(a_t)`).** Ground it in what Brain can actually do destructively today: `POST /delete` and `PATCH /memories/:id` (`brain_api.rs`) are the only mutating/destructive endpoints Brain exposes, and neither has an approval/confirmation concept right now — which is fine, because nothing currently calls them autonomously (Brain doesn't plan or act). The invariant becomes a **pre-condition for Stage 4**, not a gap today: before any future route (`act`) is allowed to call `/delete` or a destructive `PATCH` without a human in the loop, `risk(a) ≥ ρ_high ⇒ approval(a) = true` must be enforced at the API layer, not just documented.

---

## 6. Upscaling — where the real bottleneck is (and isn't)

The user's goal includes scaling this up. Two findings here, one reassuring, one not:

### 6.1 Retrieval is already reasonably scalable — don't rebuild this

`VectorIndex` (`index.rs`) wraps `turbovec`'s `IdMapIndex`: 4-bit quantized SIMD inner-product search, not brute-force f32 cosine. At 23k rows this is already far from the naive-scan assumption the source doc implicitly made when it worried about "building a general-purpose graph." The retrieval layer doesn't need an upgrade to scale another 10×; it needs the calibration (§2.4) and the contract fix (§0) before it needs more horsepower.

### 6.2 Possible bottleneck: a single global mutex (unmeasured — see correction below)

SQLite is already in **WAL mode** (`store.rs:93`), which supports concurrent readers with one writer — but `brain_api.rs` wraps the entire `Brain` (store + vector index + embedder) in one `Arc<Mutex<Brain>>` (`brain_api.rs:43`), and every handler — including pure reads like `/search`, `/stats`, `/list` — takes that same lock (`lock_brain(&state)`, used at 15+ call sites). This serializes all traffic application-side, which throws away the concurrency WAL mode was turned on to provide.

**Correction (2026-10-21): the original fix here doesn't work as written.** It proposed replacing `Mutex<Brain>` with `RwLock<Brain>`. But `brain_api.rs:40` documents why the lock is a `Mutex`: *"rusqlite's Connection is `!Sync`."* `Arc<RwLock<T>>` can only be shared across threads if `T: Sync`, so `RwLock<Brain>` won't compile while `Brain` owns a `rusqlite::Connection`. A real read/write split needs one of:
- separate read-only SQLite connections, one per reader or from a small pool, with the vector index and embedder behind their own shareable lock; or
- a dedicated writer thread or connection, with readers on their own connections.

Either one touches how `Brain` is constructed, so it is a **major change**.

**Also unverified: that this is the bottleneck at all.** The original text asserted it was "the actual throughput ceiling" without any measurement. With a handful of local sessions it may not be. **G6 is now "profile first":** measure lock wait time and `/search` latency under realistic concurrent load before designing the split. Embedding dimension (`768`) and the index algorithm are still not bottlenecks.

---

## 7. Associative memory layer — `similar_to` edges (proposed addendum)

Raised during spec review: should `z` ("links") be a memory-to-memory **similarity** layer — for each memory, its nearest neighbors by embedding distance — rather than (or in addition to) the existing entity-mention graph? Short answer: yes as a new, separate structure; no, not wired into ranking by default; and it is **not** "building a neural network," though the cognitive-science framing it borrows from (associative memory, spreading activation) is legitimate for this project's stated goal.

### 7.1 What exists today, verified

`VectorIndex` wraps `turbovec::IdMapIndex` — confirmed by reading the crate (`turbovec = "0.8.0"`, TurboQuant algorithm): a **flat quantized index**, exhaustive search with fast quantized distance math, not a graph-based ANN (no HNSW). There is **no latent neighbor graph** hiding inside the current vector layer to simply "expose" — it does per-query nearest-neighbor search, and nothing else. A memory-to-memory similarity layer has to be built as new, explicit structure; it doesn't fall out of what's already running.

The closest existing precedent is the save-time dedup guard (`brain.rs:22`, `DEDUP_DISTANCE_THRESHOLD = 0.03`): a one-off cosine-distance check against existing same-project, same-type memories, used only to skip inserting near-duplicates. It's the same primitive (embedding-to-embedding distance) used for a single narrow purpose, not a stored, queryable graph.

### 7.2 Proposed structure

A new, separate relation, **not** reusing `mentions`:

```
edges (relation_type = 'similar_to')
  src_memory_id, dst_memory_id, weight    -- weight = 1 - cosine_distance
```

Build mechanism: cheap by construction. The embedding for a memory is already computed at save time; querying the existing index with that same embedding for its top-k nearest *other* memories costs one extra index lookup per save, not a new indexing scheme. Existing memories need a one-time backfill job (query each of the ~23k rows against the index, same O(N) cost structure the dedup guard already pays per-save, just run once for history).

### 7.3 Where this earns its place first (low-risk, before touching ranking)

1. **Consolidation/dedup, generalized.** Replace the ad hoc `DEDUP_DISTANCE_THRESHOLD` check with a queryable "nearest-neighbor" primitive the curator can use for merge/supersede decisions, not just save-time skip.
2. **Atlas layout** (`memory_atlas.rs`, in progress). Current layout hubs memories by *most-mentioned shared entity* — a symbolic proxy for "these belong together." Embedding similarity is a more direct signal for the same purpose and a natural input to the existing layout algorithm.
3. **"Related memories" browsing** — a host- or UI-facing feature, read-only, no effect on search ranking.
4. **Temporal layer detection (§8).** Similarity is the fallback signal for deciding that a newer memory is a layer on top of an older one about the same subject. In the owner's model, `z` (links) is the associative, "cognitive" half of a hybrid system: it finds neighbours and relationships quickly without spending tokens re-reading content. The structured hierarchy (§8.1) is the precise, traceable half.

### 7.4 What this is not allowed to do yet

Same gate as every other edge type in this spec (G4): **no use of `similar_to` edges in `/search` ranking or in `graph_expand`-style result expansion until it passes a gold-set A/B.** The precedent is direct — `graph_expand` (entity-based neighbor expansion, the same *shape* of idea with a different edge type) already measurably hurt retrieval and is off by default pending proof. A similarity-based neighbor expansion is exactly as likely to repeat that failure mode until shown otherwise on the same harness.

### 7.5 Naming correction: associative memory, not a neural network

A k-NN similarity graph has no learned weights, no training signal, no backpropagation — it's a static index of "which embeddings are close," computed once and looked up, not learned over time. That is not what "neuron" means in neural-network terms, and framing it that way invites a future assumption that learning is happening here when it isn't.

The framing that *is* legitimate: this is an **associative memory** structure — a weighted semantic-similarity network you can traverse or "spread activation" across, the same primitive cognitive architectures like ACT-R use to model human associative recall. For a project whose explicit goal is a cognitive architecture, that's a reasonable and well-precedented thing to build toward. Keep the vocabulary as "associative memory / spreading activation," not "neural network," so the distinction between this (a static similarity index) and an actual trained model stays clear as the system grows.

---

## 8. Temporal layers and layer confidence (owner's model, 2026-10-21)

This section records the owner's core model as clarified in review. It is the most important part of the spec for what Brain is meant to become. The sketches are in `docs/architecture/sketches/`.

### 8.1 The model in the owner's notation

```
a = agent    n = brain    x = project    s = source    t = type
y = date     m = memory   c = confidence  z = links

a → n → x → s → t → [ m₁(y₁), m₂(y₂), … ]     stacked by date, newest on top
n → z → {x, s, t, y}                         links cross-cut the tree
```

- **Append-only.** No memory is deleted or replaced. When something changes, a new memory is written **on top of** the older one about the same subject. The older layer stays, so Brain can trace the history of a project, file, decision or idea.
- **Confidence comes from the layer, not from the content.** In the sketch, the top layer is `c = 10` and the bottom is `c = 1`. Confidence tells the agent which layer to trust most, without hiding the ones below.
- **A hybrid system by design.** The tree `n → x → s → t → y` is a structured, precisely traceable retrieval system: every memory has an exact address. `z` (links) is the associative, "cognitive" half: relationships, neighbours and instant findings without spending tokens re-reading content. Each half covers the other's weakness: the tree is exact but rigid, and the links are fast but fuzzy.

**Notation reconciliation.** The owner's letters collide with symbols used in §1–§4. Read them by form:
- `c(m)` (a function of a memory) is **confidence**. `c_t` (subscripted by turn) is **context**.
- `x` alone, or `x₁ x₂ x₃` in the sketch, is a **project**. `x` inside `score(x,q)`, `hybrid(x,q)` etc. in §2 is a **candidate memory**.
- `s` is **source**. The full state `s_t` from the source vision is not used in this spec.
- `t` alone, or `t₁ t₂`, is **type**. The subscript `_t` is the **turn**.
- `y` is **date**: `event_time`, falling back to `timestamp`.

If this spec is ever turned into code or a formal paper, rename one side, e.g. context to `κ_t`.

**Mapping to today's schema (verified):** `x`, `s`, `t` and `y` already exist as columns on every memory (`project`, `source`, `type`, `timestamp`/`event_time`), so the tree is a **view** over existing columns and needs no new tables. `z` partly exists as `edges(relation_type='mentions')` from memory to entity. `c` in the owner's sense does not exist; see §8.3.

### 8.2 The key clarification: relative depth, not absolute age

> Confidence depends on **how many newer memories sit on top of the same subject**, not on how old a memory is overall.

- A year-old decision that nothing has changed since is still the top of its stack, so it keeps **high** confidence.
- A config file changed three times last week leaves its first version **low** confidence, even though it is only a week old.

Absolute age is already handled, lightly, by `recency_w` (§2). Layer confidence is a different signal: **"has this been overwritten by something about the same subject?"** The two must not double-penalise; the experiment in §8.7 measures this.

### 8.3 Decision: compute confidence at query time, never store it

Confidence is **derived when searching**, not written to the row. If it were stored, every new memory would mean rewriting numbers on older rows, which contradicts "nothing gets replaced." Deriving it keeps old rows immutable and keeps history fully traceable, and the formula can be retuned without migrating data. *(Agreed with the owner, 2026-10-21.)*

This also settles §0's question about what salience means. A once-assigned LLM score (`salience`) is the wrong signal for this model. Layer confidence is intended to replace `salience_w` in ranking once validated (G8).

### 8.4 Formula (proposed; thresholds to be set by §8.7)

```
σ(m)        subject keys of memory m   (how Brain knows what m is "about")
same(m,m')  m and m' share a subject   (§8.5 tiers)
L(m)        = { m' : same(m,m') ∧ y(m') > y(m) }        layers on top of m
             y = event_time, falling back to timestamp (same as recency_w)
w(m,m')     ∈ [0,1]  how strongly m' overrides m
             = 1                          if m.superseded_by = m'  (explicit)
             = similarity-based weight    otherwise
depth(m)    = Σ_{m' ∈ L(m)} w(m,m')
layer_w(m)  = F + (1 − F) · λ^depth(m)       F = floor (e.g. 0.85), 0 < λ < 1
c(m)        = 1 + 9 · λ^depth(m)             1–10 display scale from the sketch, display only
score(x,q)  = layer_w(x) · recency_w(x) · hybrid(x,q) · knowledge_w(x)     (salience_w retired)
```

Why each piece is shaped this way:
- **`w` is weighted, not a 0/1 count.** Two memories about `SmileDoc.tsx` can cover different aspects, like styling and a bug, and the newer one should not push the older one down. Only a newer memory that says something similar about the same subject counts fully.
- **`layer_w` is bounded in `[F, 1]` and multiplicative.** That preserves the §2.1 dominance invariant: an old layer is ranked lower but can never outrank a strongly relevant answer, and the top layer (`depth = 0`) gets exactly `1.0`.
- **`c` on a 1–10 scale** matches the owner's notes for UI and agent display. Ranking uses `layer_w`.

### 8.5 How Brain decides two memories share a subject: the "spot specifics" problem

From the sketch: *"For a vectorize layer we need a way to spot specifics, but this can be a wide range of things."* Signal tiers, from most to least reliable, with live-DB coverage (2026-10-21, 23,058 memories, 13,019 not superseded):

| Tier | Signal | Coverage today | Verdict |
|---|---|---|---|
| 1 | Same `file_path` | 614 rows (2.7%), mostly `knowledge` (290), `project_context` (181), `solution` (143). Only **44** paths have >1 memory. None on facts or conversations. | Most reliable and almost unused. Worth capturing at save time (G10); I haven't yet checked whether the hooks know the file being edited. |
| 2 | Same project + a **specific** shared entity | 28,289 entities, 71,025 mention edges, 16,241 memories with ≥1 entity. 18,747 entities are mentioned once (can't form a stack). 95 are mentioned 50+ times and are too generic (`Next.js` 805, `React` 537, `Supabase` 424). The useful middle: e.g. `SmileDoc.tsx` (9), `RifaNumbers.tsx` (7), `scrollToForm` (4). | Main realistic signal. Filter by frequency: `σ_E(m) = { e ∈ E(m) : 2 ≤ df(e) ≤ D_max }`. Some entities are noise (`aspect-[3/4]`, `message`). |
| 3 | Embedding similarity ≥ `τ_sim`, same project + type | Every memory has an embedding | Fallback. Cheap at query time only if `similar_to` neighbours are precomputed (§7, G7). Otherwise it costs one index lookup per candidate. |

Entity coverage by type (live rows with ≥1 entity / total): fact 4,086/5,178 · solution 1,579/2,788 · conversation 2,226/2,327 · episode 918/1,571 · project_context 412/474 · pattern 147/216 · decision 140/161 · error_lesson 93/126 · **knowledge 0/178**.

#### 8.5a Project scope gate (resolved 2026-10-22, answers open question 4)

Before any tier above runs, `same(m,m')` requires `m.project = m'.project`, **unless** one of two explicit conditions holds:

```
cross_project(m,m') = (m.file_path = m'.file_path ≠ NULL)         # exact path match, e.g. a monorepo split
                     ∨ declared_alias(m.project, m'.project)       # owner- or host-declared rename/merge, never inferred
```

Why a hard default instead of a softer cross-project similarity tier: every apparent cross-project supersede pair in the live DB turned out to be the **same project**, mistagged — see §8.7b. A tier that lets embedding or entity similarity bridge two different `project` values would just rediscover that mistagging bug, not real history. `declared_alias` is a small explicit table (`project_a, project_b, declared_by, declared_at`), written only by a human or host action that says "these are the same lineage," never by a similarity threshold. This keeps `same(m,m')` honest: project is a hard boundary unless something stronger than content closeness says otherwise.

### 8.6 Verified findings that shape the design

1. **Real stacks already exist.** 1,839 rows have `superseded_by` pointing at another memory id; **1,780** of those resolve to an existing row (1,667 fact, 113 knowledge; 1,728 same-project). The other 59 point to an id no longer in `memories`. These 1,780 pairs are ground truth for stack detection.
2. **Old layers have no links, which conflicts with the model.** **0 of the 1,780** older rows have any entity edge, while 1,120 of their replacements do. Cause: `brain/tools/backfill_entities.py:55–64` selects only *non-superseded* rows. In the owner's model old layers must stay linked, or the agent cannot trace back through history. Fixing this is a prerequisite (G9).
3. **Today's supersede is binary: hide, not layer.** `SearchFilter.exclude_superseded` defaults to `true` (`types.rs:136`, applied at `brain.rs:410`), so a replaced memory disappears from search entirely. The model wants it visible at lower confidence. Changing this default is a live ranking change (part of G8).
4. **Two different things share the `superseded_by` column.** 8,200 rows are `superseded_by = 'quarantine:path_fragment_project'` (bad project tags from the May backfill). That is **data-quality removal, not history** — layers must not inherit quarantine semantics. *(Revised 2026-10-22: "data-quality removal" described the tag, not the content. Checking the actual rows showed 0 of 8,200 were empty — they're real facts with a corrupted `project` field, not junk. "Stay hidden" was the wrong call; see §8.7b for the remediation actually applied.)*
5. **Deletion still exists.** `POST /delete` is live and has been used, e.g. a brain memory records a 2026-08-07 scrub of 74 hallucinated memories. "Nothing deleted" needs a rule for junk versus history. *(Resolved, owner 2026-10-21: delete stays for confirmed junk. Applied 2026-10-22 to 51 content-free rows, see §8.7b.)*
6. **No `file_path` index.** `memories` has indexes on `type`, `project`, `parent_id` and `superseded_by`, but not `file_path`. Tier 1 lookups at query time would need one (a schema change, so G10).
7. **History browsing by subject doesn't exist.** `timeline_tool` walks by time around an anchor, not by subject. A "show me the stack for X" read API is the natural traceability surface for this model (proposed, read-only).

### 8.7 Experiment protocol (read-only; nothing live changes)

1. **Recall per tier on real stacks:** for the 1,780 pairs, what fraction does each tier detect? Caveat: the older rows have no entities (finding 2), so the entity tier can only be tested after extracting entities for them **in a scratch copy of the DB**. I haven't checked yet what `backfill_entities.py` uses to extract entities (LLM call or local), so that comes first.
2. **Bias check:** these pairs are curator near-duplicates of facts/knowledge only, so they will flatter the similarity tier. Add a hand-labelled sample (~100 candidate pairs across solutions, decisions and conversations) for precision.
3. **Precision:** of the pairs each tier links, how many are truly "same subject"? Also the stack-size distribution, where giant stacks indicate generic keys and `D_max` is too high.
4. **Tune** `D_max`, `τ_sim`, `λ` and `F` from steps 1–3.
5. **Ranking A/B** on the existing gold harness: `layer_w` vs `salience_w` vs neutral, measuring P@1/P@5/MRR **before and after the diversity cut** (§2.1 caveat), plus a check that `layer_w` and `recency_w` don't double-penalise.

### 8.7a Experiment results (2026-10-21)

Full report, scripts and the 70 hand labels: `docs/architecture/experiments/2026-10-21-layer-detection/`. What changes in this spec as a result:
- **The 1,780 supersede pairs are censored ground truth.** The curator only links pairs with similarity 0.78–0.92 (`fact_curator.py:3-6`), and only for facts and knowledge.
- **Most real layers sit below 0.78 similarity** (10/16 in the labelled sample; ~4,350 estimated, ~90% below 0.78). They are mostly work progressions, bug → fix and decision refinements in conversations, decisions and episodes.
- **The §8.5 tiers find candidates but can't decide layers:** about 33% precision for shared specific entity + similarity 0.5–0.92. So `same(m,m')` needs a judgement step: either (A) the host declares `supersedes` at save time, or (B) a curator-style judgement over entity candidates across all durable types.
- **`y` must be `timestamp` for now, not `event_time`.** 13,419 of 14,717 fact `event_time` values are placeholder dates (`2025-07-01`, `2025-01-01`). This also skews live `recency_w` for those facts.
- **The ranking A/B (step 5) is blocked** until there is a recency gold set ("current state of X?") and a precise layer detector; the existing gold sets have 0 such queries.

### 8.7b Quarantine remediation and the cross-project question (resolved 2026-10-22)

Before trusting any project-tag signal (§8.5 tier 2, §8.5a), the 8,200 quarantined rows and the cross-project pairs both needed verification, not assumption — same discipline as §8.7a.

**The 8,200 were real content, not junk.** Direct sampling: 0 of 8,200 empty/content-free, 0 duplicate an already-visible row. The `project` field itself held a path fragment (`cursor` 5,192 · `src` 1,383 · `landingpage` 705 · `frontend` 662 · `.claude` 231 · `etl` 21 · `rust` 5 · `test` 1) from the May backfill — a metadata bug, not a content problem. Hiding them was throwing away real history over a tagging error.

**No ground truth for the correct project exists on these rows**, so recovery only trusts a signal already present elsewhere, never a guess:
1. `brain/tools/recategorize_quarantine_project.py` — for each quarantined row, look at other live (non-quarantined) rows sharing its `session_id`. If exactly one real project appears among them, correct `project` to it and clear `superseded_by`; otherwise just clear `superseded_by` and leave `project` as the generic bucket (un-hidden, not guessed). Result: **978 recovered, 7,222 un-hidden with project unchanged.**
2. The same generic-bucket bug also existed on **2,962 rows that were never quarantined at all** — including the older side of what looked like cross-project supersede pairs. `recategorize_generic_project_tags.py` applied the same session-sibling rule: **189 recovered, 2,773 left as-is** (tagged `checked` so a future pass can tell "reviewed, unresolved" apart from "never looked at").
3. For `episode`/`solution` rows (raw tool-call traces), the real project is often sitting directly in the content, e.g. `Created /Users/Shared/Code/sicop-health/services/...`. `recategorize_embedded_path_project.py` parses the segment after `/Code/` and rejects it if it's itself a generic-bucket value. Scoped to rows the session-sibling passes couldn't resolve: **1,437 of 1,437 matched rows recovered** (`sicop-health` 668, `intelli-ehr` 313, `brain` 104, `lifehub` 96, others smaller).
4. **51 rows were genuinely junk** — 54 content-free session stubs (`"Claude Code session: ... Ended: ..."`, e.g. `[user] hi` repeated) and 3 `verification_probe` test-harness rows — confirmed empty of content and deleted via `delete_junk_stubs.py`. 6 stubs reporting an unusually high message count were held back from auto-delete and manually checked; all 6 turned out to contain real work (SICOP ETL debugging, an SQL-summarization pipeline discussion, an obsidian-brain import request) and were left alone.

All three recategorize scripts are reversible (backup JSON per row in `brain/bootstrap/junk_scrub_backups/`), touch only `project`/`tags`/`superseded_by`, never invent a project value, and never delete. `delete_junk_stubs.py` is the only destructive one and backs up full row content (embedding included) before deleting.

**The cross-project question is answered by the same investigation.** Before remediation, 135 supersede pairs (not the 52 originally estimated — that count was stale) had `project(old) ≠ project(new)`. Checked directly: **100% of them were `old.project` ∈ the generic-bucket set and `new.project` a specific real project** — i.e. the *same* project, mistagged on the older side by the exact bug above. Zero pairs involved two genuinely distinct, correctly-tagged projects. After the three remediation passes, the false-cross-project count dropped 135 → 62 (the rest resolved to same-project once the old side's tag was fixed); the remaining 62 have no resolvable session or path signal and are left as unresolved mistagging, not evidence of real cross-project history. **There is no example anywhere in 23,035 memories of a real layer spanning two distinct projects.** That is why §8.5a makes project a hard default boundary rather than building a cross-project similarity tier with no positive examples to validate against.

### 8.8 Open questions for the owner

1. Should explicitly superseded memories **reappear in search** as low-confidence layers (the model) or stay hidden (today)? **Deferred by the owner (2026-10-21): stays hidden for now**, until the layer model itself (§8.4) is implemented and validated.
2. Quarantined and junk rows: history or noise? **Resolved (§8.7b):** verification showed the 8,200 quarantined rows are real content with a mistagged `project`, not noise — they were recovered/un-hidden, never treated as junk. Only the 51 rows confirmed content-free were junk.
3. Does `POST /delete` stay for junk? **Resolved (owner, 2026-10-21): yes** — the 51 confirmed-junk rows were hard-deleted via `delete_junk_stubs.py` (backed up, reversible).
4. Can a stack cross projects? **Resolved (§8.7b, §8.5a): no, not by inference.** Zero genuine cross-project layers exist in the live data; every apparent case was mistagging. Default `same(m,m')` to same-project; a cross-project link requires an exact `file_path` match or an explicit, non-inferred `declared_alias` — never embedding or entity similarity across differing project tags.

---

## 9. Corrected symbol table (reference)

| Symbol | Meaning | Owner | Changes on | Exists today? |
|---|---|---|---|---|
| `q_t` | query/goal | host, exogenous | every call | — |
| `c_t` | context | host, exogenous | every call | — |
| `M_t` | memory store | Brain | every save/curate/backfill | yes |
| `g_t` | tools/capabilities | host, config | deploy | — |
| `π_t` | route-policy parameters | Brain, config | deliberate recalibration only | no (Stage 3) |
| `m_t = R(q_t,c_t,M_t)` | retrieved+ranked memories | Brain | — | yes, §2 |
| `score(x,q)` | raw ranker output, bounded not calibrated | Brain | — | yes, §2 |
| `P̂(relevant\|score)` | calibrated confidence | Brain | — | no, §2.4 |
| `r_t = f_{π_t}(q_t,c_t,m_t,g_t)` | advisory route | Brain | — | no, §4 |
| `p_t, a_t, o_t` | plan, act, observe | host | every call | host-only, unchanged |
| `U(M_t, …)` | learn/update | Brain | append: every save; curate: batch, currently ungated; backfill: batch, gated | partial, §3 |
| `σ(m)` | subject keys of a memory (file path, specific entities, similarity neighbours) | Brain | derived | partial: entities exist, file paths sparse, §8.5 |
| `L(m)` | newer memories layered on top of `m` (same subject) | Brain | derived at query time | no, §8.4 |
| `depth(m)` | weighted count of layers on top of `m` | Brain | derived at query time | no, §8.4 |
| `layer_w(m)` | ranking modulator from depth, bounded `[F,1]` | Brain | derived at query time | no; intended to replace `salience_w` (G8) |
| `c(m)` | layer confidence, 1–10 display scale (owner's `c`) | Brain | derived at query time, **never stored** | no, §8.3 |
| `salience` | LLM-assigned score at save time; UI "pin" | Brain | save / UI PATCH | yes, live in ranking (§0); to be retired from ranking by G8 |

---

## 10. What this spec asks you to decide (gates)

Matches the existing G1–G4 structure in the 2026-10-16 design doc, adds G0 and G5–G7, and adds G8–G10 for the temporal-layer model (§8).

| Gate | Question | Risk if skipped |
|---|---|---|
| **G0** | A/B `salience_w` live vs neutral on the gold harness, *then* decide (§0, revised). Interim only; G8 is the real fix. | Ranking currently contradicts its own written contract; unknown live quality impact |
| G1 (existing) | Approve `derived_from → extracted_by` rename / time-contract clarification | — |
| G2 (existing) | Approve `status`/`source_quality` columns, or defer. **Note:** a *stored* `confidence` column would conflict with §8.3 (confidence is derived at query time, never stored). | — |
| G3 (existing) | Approve Stage 2 decision-event schema before router code | — |
| G4 (existing) | New edge type only after gold-eval PASS | — |
| **G5 (new)** | Generalize the `backfill_batches` regression gate to curator runs (§3)? | Curator can silently regress retrieval with no before/after check, unlike backfill |
| **G6 (new)** | **Profile first:** measure lock wait and `/search` latency under concurrent sessions. Only if it's a real bottleneck, design a read-connection split (`RwLock<Brain>` won't compile; §6.2 corrected). | Premature major refactor if the bottleneck isn't real |
| **G7 (new)** | Build `similar_to` edges (storage + backfill) for dedup/atlas/browsing/layer detection (§7)? Separately: any future use of them in ranking/expansion still requires G4. | None if confined to §7.3 uses; repeats the `graph_expand` regression if wired into ranking without the gate |
| **G8 (new)** | After the §8.7 experiment: replace `salience_w` with query-time `layer_w`, and decide whether superseded layers reappear in search (open question 1). | Ranking keeps a known-wrong signal; history stays hidden instead of layered |
| **G9 (new)** | Extend entity linking to superseded (older) layers. `backfill_entities.py` currently skips them, so 0/1,780 old layers are linked. Writes to the live DB. | Old layers can't be traced or stacked; entity tier can't be evaluated on real stacks |
| **G10 (new)** | Capture `file_path` at save time from hooks, plus an index on `memories.file_path` (schema change). | Most reliable stacking signal stays at 2.7% coverage |

Nothing in this document changes code or schema. §0's interim fix and §8's model are flagged, not applied, pending G0 and G8–G10.
