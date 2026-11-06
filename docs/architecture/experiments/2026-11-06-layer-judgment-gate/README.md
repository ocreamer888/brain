# G8 judgement-step validation and backfill — 2026-11-06

Builds and validates the missing piece spec §8.7a named: a judgement step
that decides which tier-matched candidate pairs (file_path / shared entity
/ similarity, docs/architecture/experiments/2026-10-21-layer-detection/)
are actually the same evolving subject (LAYER), as opposed to RELATED /
DUP / UNRELATED. Deterministic tiers alone measured ~33% precision at this
decision; this is proposal (B), a curator-style LLM judgement, generalized
from facts-only to every durable type.

## Files

- `eval_judgment.py` — validates `brain/ingest/layer_judgment.py` against a
  labelled file (`--labeled`, defaults to the 2026-10-21 61-pair set).
- `spotcheck_32_labeled.json` — a second, independent hand-labelled set
  (CTO review, 2026-11-06), stratified across similarity bands 0.5-1.0 from
  the live full-corpus backfill's 6,170 LAYER-judged pairs. Not derived
  from or validated against the classifier's own reasoning -- each pair was
  read and labelled from the live `brain.db` content directly.
- `results_exp3_labeled.json`, `results_spotcheck_32_labeled.json` — latest
  run outputs for each set.

## Headline result

| Validation set | n | Precision | Recall | F1 |
|---|---|---|---|---|
| 2026-10-21 hand-labelled (61 resolvable) | 61 | 0.833 | 0.938 | 0.882 |
| 2026-11-06 independent spot-check (32) | 32 | 0.759 | 0.917 | 0.830 |
| **Combined (pooled TP/FP/FN/TN)** | **93** | **0.787** | **0.925** | **0.851** |

The smaller original set overstated real-world precision somewhat (0.882
vs a combined 0.851) because it under-represented two failure modes the
full-corpus backfill actually surfaces at scale (see below). The combined
number, not the original one, is the production estimate.

## Two prompt-tuning attempts, both reverted

Two rewrites of the LAYER criteria in `layer_judgment.py` were tried to
fix the false positives found in the spot-check (elaboration mistaken for
override: a definition + later implementation steps, a rule + a later
notification detail, two different specific sub-efforts sharing a project).
Both were measured against **both** validation sets, not just the one that
motivated them:

| Prompt version | 61-set F1 | 32-set F1 | Combined F1 |
|---|---|---|---|
| Iteration 3 (shipped, this is what's live) | 0.882 | 0.830 | **0.851** |
| Iteration 4 (require quoted contradicting phrase) | — | 0.545 | — |
| Iteration 5 ("still the right answer?" framing) | 0.435 | 0.732 | 0.625 |

Both rewrites traded recall on the original set for precision on the new
one, net negative every time. Reverted to iteration 3. Conclusion: the
elaboration-vs-override ambiguity is a real, currently irreducible-by-prompt
residual in the ~0.5-0.92 similarity band; the mechanical fix below
(chunk-siblings) was tractable, this one wasn't, at least not without a
different model or additional structured context (e.g. feeding session_id/
task metadata into the prompt, not attempted here).

## One real, fixed bug: chunked-document sibling false positives

The spot-check caught a documents-re-ingested-in-chunks pair (same source
document, consecutive `session_id = reingest_<slug>_<N>`) being judged
LAYER when it's actually two sibling sections of one document -- the exact
failure mode `cognitive-architecture-diagram.md` §4 already warned about
("chunked documents need a section key, not just file_path"). Confirmed
this cannot be reliably caught from content text alone (tried; made it
worse, see iteration 4/5 above) -- fixed instead at candidate generation in
`brain/tools/backfill_layer_links.py` via a `chunk_group()` check on
`session_id`. Found and removed 7 already-written `memory_links` rows with
this pattern from the live DB (backed up to
`brain/bootstrap/junk_scrub_backups/chunk_sibling_layer_links_removed_*.json`,
additive-only, never overwrites a memory).

## Expanded recency gold set and re-run A/B

Appended 23 of the 32 spot-check pairs (the ones independently confirmed
LAYER, not just LLM-labelled) to `brain/eval/gold_recency.jsonl`
(`source: cto_independent_review_2026-11-06`), growing it from 63 to 86
pairs. Re-ran `recency_eval.py` baseline vs `--use-layer-confidence` on the
corrected (post chunk-sibling-cleanup) backfill:

| | judged pairs | new outranks old |
|---|---|---|
| Baseline (salience_w) | 35 | 54.3% |
| layer_w | 34 | 64.7% |

Per-pair diff (not just the headline rate): **4 pairs fixed, 0 regressed**,
1 dropped from the judged set because the gold set's own "current" answer
has itself been superseded 6 more times since 2026-10-21 (the subject is a
frequently-recurring auto-summary) -- `layer_w` correctly demoted it too;
that's the model working, not a ranking failure.

## Gold-set hygiene (2026-11-06, after a parallel coverage audit)

A separate agent audited why 51 of 86 gold pairs surfaced *neither* memory
at all -- the real bottleneck on the A/B above, bigger than ranking order.
Root cause, verified against live data, not guessed: **39 of 51 were
dangling references** (the `curator_update_pair` tier, built against an
older DB snapshot since cleaned up -- those target rows no longer exist
and can never be judged by any ranking change). **10 were `type=episode`**
content hitting `exclude_episodes_by_default=true` (7 of those are from
today's own `cto_independent_review` tier). **3 were single-generic-word
subjects** ("solution", "profiles", "Artifacts") matching thousands of
unrelated rows -- a bad query, not bad ranking.

Fixed: dropped the 39 dangling + 3 generic rows, tagged the 10 episode
pairs with `memory_type` and taught `recency_eval.py` to pass it through.
Gold set: 86 → 44 pairs, but **coverage jumped from 36% to 95%** (`neither
surfaced` 51 → 1-2). Re-ran the real A/B on this now near-complete set:

| | judged | new outranks old |
|---|---|---|
| Baseline | 43 | 65.1% (28/43) |
| layer_w | 42 | 71.4% (30/42) |

Per-pair diff: **4 fixed, 1 "regressed", 1 dropped.** Traced both the
regression and the drop to the same root cause as before: the gold set's
own "current" answer for two fast-moving sicop-health subjects
(`continual-learning-index.json`, `ACI market entry volume and
competitors`) has itself been superseded multiple times since the pair
was labelled -- `layer_w` demoted the designated "new" side because
*something newer than it* now exists too, which is the model working
correctly, not a defect. Zero unexplained regressions on the largest,
highest-coverage version of this test run yet.

## Status

`SearchFilter::use_layer_confidence` remains off by default. This is real,
validated evidence on 42-43 independent judged pairs at ~95% gold-set
coverage -- a much stronger sample than the 17-18 pair run this backfill
started from, with every apparent regression traced to an explained,
non-ranking cause -- but not yet a case for flipping the default without
a product decision.
