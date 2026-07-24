# Cross-Memory Corroboration Confidence — Structured Plan (O1)

**Date**: 2026-06-10
**Owner**: CTO (Claude) + product partner
**Status**: ⛔ **STOPPED at Phase 0 — gate FAILED (2026-06-10).** Corroboration-as-ranking-signal does not help retrieval. Do not build Phase 1. See "Phase 0 Result" below.
**Replaces**: Task 5 "Noise Detection via Implicit Geometric Learning" (proven broken — premise inverted; see brain memory `f1bc4fee` and `docs/tasks/pending-tasks.md` Task 5)
**Inspiration**: AlphaFold MSA co-evolution — confidence from corroboration across *independent* evidence, not single-point geometry.

---

## ⛔ Phase 0 Result (2026-06-10) — GATE FAILED, O1 STOPPED

Ran `brain/tools/corroboration.py` (read-only, full corpus 17,347). Measured:

| Experiment | Result | Verdict |
|---|---|---|
| V1 gold-set ranking lift | P@1 **−0.105**, MRR **−0.086** | hurts |
| V5 leave-one-out (800 sample) | P@1 −0.005, MRR −0.005 | hurts slightly |
| V4 calibration sweep (support_min 0.55–0.70) | negative at **every** band | no good operating point |
| V3 face validity | top-corroborated = PPF API bulk-ingest cluster | signal contaminated |
| V2 feedback | only 3 corpus-linked events | uninformative (expected) |

Gate required ≥ +0.02 P@1 or MRR lift. Got negative everywhere → **STOP. No Phase 1.**

**Two confirmed root causes:**
1. **Band [0.60, 0.97) measures topical breadth, not "same claim."** A PPF memory scored `support=385 sessions` though the PPF cluster is only 1 session — those 385 are loosely-related memories across unrelated sessions within cos 0.6–0.97. Genuine claim-level corroboration would require NLI/entailment (the deferred Phase 2), not embedding proximity.
2. **Trust ≠ relevance — the *use* was wrong.** 6 of 19 gold answers are isolated (support ≤ 1) specific facts; multiplying scores by corroboration demotes them (the same trap as fragility — penalizes unique correct answers) while boosting generic bulk clusters above the specific answer. Multiplying a confidence signal into a relevance score distorts relevance even if the confidence were perfect.

**Insights (worth more than the code):**
- A trust signal belongs as a **separate displayed axis / filter** (like Task 3's `⚠ low-trust` flag), **not** a ranking multiplier.
- We have **no ground-truth for hallucination**, so no trust detector can be validated directly. Ranking-lift was the best measurable proxy and it says "no help."
- **Inverse-pLDDT lesson:** AlphaFold could build pLDDT because it had the PDB (labels). We can't engineer any validated detector until we have labels. → **next priority is building ground-truth, not another unsupervised detector.**

**Discipline worked as designed:** ~150 read-only lines + one run killed the idea before any schema/Trust/LLM investment. A negative result here is the gate doing its job (cf. Task 5, which shipped 250 lines on an unvalidated premise).

**Artifacts kept as diagnostics (no DB writes):** `brain/tools/corroboration.py`, `brain/tools/noise_effectiveness.py`, `brain/tools/noise_diagnose.py`.

Phases 1–2 below are **not pursued** (kept for record).

---

## Thesis

A memory is trustworthy when **independent** memories restate the same claim (AlphaFold MSA analog: a contact is real when many independent homologous sequences co-vary). We compute a per-memory **corroboration** score and feed it into the existing Trust signal to **demote isolated/unverified memories and boost well-supported ones — never delete.**

## Non-negotiable principles (apply to every phase)

1. **Measure-first.** No machinery ships without a data gate proving lift. (This is the exact discipline whose absence produced the Task 5 disaster.)
2. **Demote, don't delete.** Confidence lowers ranking; it never removes data. Deletion is irreversible; AlphaFold itself only *flags* low-pLDDT residues.
3. **Cheap → expensive, gated.** Each phase must pass its gate before the next starts.
4. **Reuse infra.** numpy + sqlite + existing eval harness + existing Trust/salience plumbing. No new deps.
5. **Honest caveats surfaced, not hidden.** Consensus-hallucination and popularity≠truth risks are documented and tested for.

---

## Data model (verified 2026-06-10, `brain/rust/brain.db`)

- `memories`: `id, content, type, project, tags, timestamp, source, session_id, importance, salience, superseded_by, embedding`
- `session_id`: 77% populated, 2,279 distinct sessions → independence key
- `source`: claude_code_session (16k), cursor_history (721), claw_code (184), perplexity (175), reflection (33)
- `salience`: already 0.1–1.0, already feeds Trust in `search_brain` (Task 3)
- BVH dedup threshold = 0.97 → reuse as the near-duplicate ceiling

---

## Metric definition (frozen for v1)

For memory `m` with unit embedding, over the normalized corpus matrix:

```
neighbors      = top-K cosine neighbors of m (K=50, exclude self)
corroborators  = neighbors with cosine in band [SUPPORT_MIN, DUP_MAX)
                 DUP_MAX     = 0.97   # ≥ this = near-dup, no new evidence (BVH's job)
                 SUPPORT_MIN = 0.60   # < this = different claim (calibrated in Phase 0)
support        = count of DISTINCT session_id among corroborators
                 (empty session_id → each counts as its own singleton; Neff proxy)
corroboration  = min(support, CAP) / CAP      # CAP=5 → score in [0,1]
```

Rationale: independence (distinct sessions) is the Neff idea — redundant copies inside one session add no evidence, mirroring MSA sequence-reweighting.

---

## Phase 0 — Measure (ZERO DB writes)

**Goal:** decide go/no-go with data. Pure read-only.

**Deliverable:** `brain/tools/corroboration.py` (scorer + measurement, ~120–150 lines).

**Steps:**
1. Local corpus loader pulling `id, type, project, title, content, session_id, embedding` (extend the `retrieval_eval_kfold.load_corpus` pattern — it does not currently load `session_id`).
2. Vectorized corroboration scorer per the frozen metric.
3. Validation experiments (reuse `noise_effectiveness.py` harness pattern):
   - **V1 Ranking lift** — re-rank gold-set retrieval using corroboration as a Trust multiplier; report P@1/P@5/P@10/MRR **before vs after**. Primary gate metric.
   - **V2 Feedback correlation** — pull `feedback_events`; compare corroboration of `accepted` vs `rejected` memories. (10 events — weak, reported honestly as directional only.)
   - **V3 Face validity** — print top-10 highest and bottom-10 (isolated singletons) with titles/types.
   - **V4 Calibration** — sweep `SUPPORT_MIN ∈ {0.55, 0.60, 0.65, 0.70}`; pick value maximizing V1 lift without runaway corroborator counts.
4. Second lift signal to offset small gold set: leave-one-out self-retrieval lift on a larger stratified sample.

**GATE → Phase 1 (all must hold):**
- V1 shows measurable lift (≥ **+0.02** P@1 *or* MRR, beyond noise), AND
- V2 not contradicted (rejected corroboration ≤ accepted, or insufficient signal), AND
- V3 passes eyeball sanity.
- If no lift → **STOP.** Keep `corroboration.py` as a manual diagnostic only; document the negative result. (A negative result here is a *success* of the measure-first discipline, not a failure.)

**Effort:** ~1 session. **Risk:** small gold set (19 valid) → mitigated by V1+leave-one-out dual signal. **No approval needed beyond this plan** (no writes).

---

## Phase 1 — Persist + integrate (ONLY if Phase 0 passes)

**Goal:** make corroboration a live, low-weight term in Trust; retire the broken auto-delete.

**Steps:**
1. **Schema (major — re-confirm before running):** additive `ALTER TABLE memories ADD COLUMN corroboration REAL` (nullable, backward-compatible). Add to the Rust store migration (`store.rs`), not a raw ad-hoc ALTER. Back up DB first (`cp brain.db brain.db.bak-<ts>`).
2. **Batch compute:** `corroboration.py --persist` writes scores; idempotent; logs counts.
3. **Trust integration:** extend `search_brain` Trust (currently salience+feedback) with a conservative corroboration term, clamped like the existing `salience_w` band (`brain.rs`). Weight chosen to not destabilize current ranking.
4. **Retire auto-delete:** replace `run_noise_detect()` with `run_corroboration()` in `brain/hooks/run_cleanup.py` — computes & persists every 20 sessions, **deletes nothing.** Keep `noise_detect.py` as a manual diagnostic.
5. **Tests:** behavior tests — corroborated memory outranks isolated same-claim memory; score persists; Trust reflects it. Match existing `test_mcp*.py` style.
6. **Re-measure:** full `eval_suite.py --all`; confirm quick_gate + mcp_path no regression vs current baseline.

**GATE → done:** full eval suite shows no regression AND live gold lift holds. Commit per step (user controls commits); update `pending-tasks.md` Task 5 to reflect reality; save brain memory with measured deltas + caveats.

**Effort:** ~1–2 sessions. **Risk:** schema/Rust change → mitigated by additive column + DB backup + eval gate.

---

## Phase 2 — Contradiction detection (OPTIONAL, only if Phase 1 proves value)

**Goal:** move from support-only to support-vs-contradict (closer to true hallucination detection).

**Steps:**
1. LLM entailment (local Ollama `qwen3-coder:30b` — no new dep) on band-neighbors, **budget-bounded**: only high-salience facts or low-corroboration facts, NOT all ~850k pairs.
2. Classify pairs support / contradict / neutral; aggregate a `contested` flag.
3. Contradiction → surface for review (report or `contested` tag). **Still no auto-delete.**
4. Measure: manual audit of flagged contradictions → precision of the flag.

**GATE:** contradiction-flag precision on audit sample clears an agreed bar. Design details deferred until Phase 1 ships.

**Effort:** larger, LLM-bounded. **Defer full design.**

---

## Out of scope for this plan (tracked elsewhere)

- **O3 / Task 7 — Entity graph → relational confidence (AlphaFold PAE analog).** Net-new, needs NER dependency + its own approval. Complementary; builds on top, not in this critical path.
- **Auto-deletion of any kind.** Permanently rejected (demote-don't-delete).

---

## Phase map

```
Phase 0  measure (no writes)         gate: P@1/MRR lift ≥ +0.02 → go / else STOP
Phase 1  persist + Trust + retire    gate: full eval no regression
         the broken auto-delete
Phase 2  contradiction (Ollama)      gate: flag precision on audit
O3/T7    entity graph (separate)     own NER-dependency approval
         never: auto-delete
```

**Next action:** implement Phase 0 `corroboration.py` and run V1–V4.
