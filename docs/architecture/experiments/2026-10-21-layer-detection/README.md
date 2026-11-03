# Experiment: detecting temporal layers ("same subject") — 2026-10-21

**Question (spec §8.5–§8.7):** can Brain tell, without an LLM, that a newer memory is a *layer on top of* an older one about the same subject?
**Data:** read-only snapshot of live `brain/rust/brain.db` taken 2026-10-21 (`sqlite3 .backup` → `/tmp/brain-exp/brain.db`), 23,058 memories. Nothing live was changed.
**Files here:** `exp1_pairs.py`, `exp2_by_decision.py`, `exp3_candidates.py` (scripts; they read the `/tmp` snapshot path) and `exp1.json`, `exp2.json`, `exp3_stats.json`, `exp3_labeled.json` (results; the 70 hand labels are in `exp3_labeled.json` for owner review).

---

## Headline

1. **The existing "real stacks" are a biased ground truth.** The curator only links old → new when cosine similarity is between **0.78 and 0.92** (`brain/ingest/fact_curator.py:3-6`). Below 0.78 it saves the new fact as brand new and never links them. So the 1,780 supersede pairs only contain layers the curator could see, and they are facts and knowledge only.
2. **Most real layers fall below the curator's threshold.** In an uncensored hand-labelled sample, **10 of 16** true layers had similarity < 0.78. Band-weighted estimate: about **4,350** layer pairs among memories that share a specific entity, roughly **90% of them below 0.78**. The curator is structurally blind to most history.
3. **Real layers are mostly work progressions, not fact edits.** Of the 16 labelled layers: 9 are task/branch/run status progressions ("Task 2 BLOCKED" → "Task 4 done"; "shard 0 running" → "both shards passed"), 2 are bug → fix, 3 are decision refinements, and 2 are file versions (a spec going Draft → Implement). They live in conversations, decisions and episodes, the types the curator never touches.
4. **No deterministic tier is precise enough to auto-stack.** Shared specific entity + similarity 0.5–0.92 is about **33%** LAYER (14/42). The rest are RELATED: same subject, different aspect, both still valid. Auto-stacking on these rules would wrongly demote about 2 of every 3 linked memories.
5. **Dates are corrupted for facts.** **13,419 of 14,717** fact `event_time` values are placeholders: `2025-07-01T00:00:00` (10,933, all from the `openrouter/google/gemini-2.5-flash-lite/v1` backfill) and `2025-01-01T00:00:00` (2,465). Layer order by `event_time` fails: 1,638 of the 1,780 pairs have identical `event_time`. **Ingest `timestamp` orders 1,717 / 1,780 (96.5%) correctly** and 100% of UPDATE/MERGE pairs. This also affects live `recency_w`, which prefers `event_time`.

---

## Exp 1 — tiers on the 1,780 curator pairs (`exp1.json`)

Baseline = random pairs from the same project + type (529 pairs; mostly *not* the same subject).

| Tier | Real pairs | Random baseline |
|---|---|---|
| Same `file_path` | 42 / 1,780 (all knowledge chunks) | 5 / 529. Knowledge chunks of the same document share a path, so **path alone ≠ same subject** for chunked docs |
| Cosine ≥ 0.80 | 95.7% | 0.2% |
| Cosine ≥ 0.85 | 86.9% | 0.0% |
| Specific entity, df ≤ 20 | 65.2% | 2.3% |
| Specific entity, df ≤ 50 | 77.1% | 3.3% |
| Any entity | 92.6% | 11.2% |

Old rows have **no entity edges** (`backfill_entities.py` skips superseded rows), so the entity tier here is text matching: does the old row's content mention a specific entity linked to the new row?

**Caveat:** these numbers look excellent *because* the curator selected these pairs by similarity. Exp 2 and Exp 3 show why they don't generalise.

## Exp 2 — split by curator decision (`exp2.json`)

| | UPDATE (real change) | MERGE (near-duplicate) | Knowledge re-ingest |
|---|---|---|---|
| Pairs | 164 | 1,503 | 113 |
| Median similarity | 0.856 | 0.940 | 0.865 |
| Cosine ≥ 0.85 | 54.9% | 92.9% | 53.1% |
| Cosine ≥ 0.90 | 12.8% | 75.8% | 33.6% |
| Ingest `timestamp` newer | 100% | 100% | 44.2% |

UPDATE examples are exactly the owner's layer model: *"contact form submission failed…" → "contact form is now working…"*, *"SUPABASE_SERVICE_ROLE_KEY is optional" → "…is required for production"*, *"Next.js 15.3.3" → "15.5.6 was installed"*. Real changes are **less similar** than duplicates, so a single similarity threshold is fighting itself: high thresholds find duplicates, not history.

Knowledge re-ingest pairs are ordered newer by `timestamp` only 44% of the time. I haven't investigated why; it's a lead for the time-contract fix.

## Exp 3 — uncensored sample, hand-labelled (`exp3_stats.json`, `exp3_labeled.json`)

Candidates: pairs of **live** memories in the same project sharing a specific entity (2 ≤ df ≤ 20, name ≥ 3 chars), older → newer by ingest time. **32,029 pairs** (23,881 same type). 14 sampled per similarity band, labelled by Claude (CTO) with fixed rules:
- **LAYER:** the newer one changes, fixes or replaces the status of what the older one says about the same specific thing.
- **RELATED:** same subject, different aspect; both remain valid.
- **DUP:** the same content stored twice.
- **UNRELATED:** only the entity name is shared.

| Similarity band | Pairs in DB | LAYER | RELATED | DUP | UNRELATED | Est. layers |
|---|---|---|---|---|---|---|
| < 0.50 | 18,537 | 0 | 7 | 0 | 7 | ~0 |
| 0.50–0.65 | 7,384 | 4 | 9 | 1 | 0 | ~2,110 |
| 0.65–0.78 | 4,157 | 6 | 6 | 0 | 2 | ~1,782 |
| 0.78–0.92 | 1,439 | 4 | 9 | 1 | 0 | ~411 |
| ≥ 0.92 | 342 | 2 | 1 | 2 | 9 | ~49 |
| **Total** | **32,029** | **16** | **32** | **4** | **18** | **~4,350** |

Notes:
- **14 per band is small;** each band estimate has wide error bars (roughly ±25 points). The direction is clear, but the totals are not precise.
- The ≥ 0.92 band is dominated by junk: 29 content-free session stubs (`"Claude Code session: .claude | Ended: …"`) and 3 `verification_probe` test rows. They're near-identical to each other, so they look like perfect "layers" while carrying no information.
- Labels are one reviewer's judgement (mine). The owner should spot-check `exp3_labeled.json`, especially the progression cases, which are the closest calls.

## Exp 4 — ranking A/B: not run, and why

Protocol step 5 (spec §8.7) was to A/B `layer_w` on the gold harness. It's **blocked**:
- The gold sets are tiny and don't test this: `gold.jsonl` has 6 queries and `gold_semantic.jsonl` has 17, with **0** "current state / latest / status" style queries. They can only check for no-regression, not whether layers help.
- With about 33% precision on stack detection, a `layer_w` A/B would mostly measure wrongly demoted RELATED memories.
- With explicit supersede links only (high precision), the top layer has depth 0 → `layer_w = 1`. Since superseded rows are already hidden, live ranking wouldn't change at all.

Running it now would produce a number with no meaning. It needs (a) a recency gold set and (b) a precise stack detector first.

---

## What this means for the design (proposals, not applied)

1. **Deterministic tiers find candidates; they can't decide layers.** "Is m′ a layer on m?" is a judgement step. Two options, cheapest first:
   - **(A) Let the writer declare it.** The host agent usually *knows* it's updating something: "Task 4 done" in the same branch, a fix for a reported bug. A save-time field like `supersedes: <id>` or `updates_subject: <key>` is cheap and precise. It also fits Stage 2 observability: the host records what it did.
   - **(B) A curator-style judgement on entity candidates.** Same LLM tiebreak the curator already uses, but fed by specific-entity candidates in the 0.5–0.92 band instead of only similarity ≥ 0.78, and extended to all durable types, not just facts.
2. **Work-progression layers need a subject key the schema doesn't have:** branch, task id, run id, spec path. Entities partly capture these (`feat/source-field-ledger-guard`, `aci-sicop-history`). A structured `subject` key at save time would make them exact.
3. **Order layers by `timestamp`, not `event_time`,** until the placeholder dates are fixed (Stage 1 time contract). Also flag that live `recency_w` currently ages about 13.4k facts from a fake date.
4. **Filter junk before any stacking:** session stubs, verification probes and exact duplicates.
5. **Build a recency gold set** ("what's the current state of X?") from the 16 labelled layers plus the 164 UPDATE pairs before any ranking change.
6. **Chunked documents need a section key, not just `file_path`,** since chunks of one file aren't layers of each other.
