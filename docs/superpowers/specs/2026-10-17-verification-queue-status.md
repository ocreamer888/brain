# Verification queue — status as of 2026-10-17

Current rollup for V-01…V-38. Evidence and the original writeups stay in [`2026-07-28-durable-entity-linking-verification-findings.md`](./2026-07-28-durable-entity-linking-verification-findings.md). The 2026-07-29 handoff’s “start at V-17” section is historical.

**Branch:** `feature/durable-entity-linking` (`85305c4`, 4 commits ahead of origin, plus an uncommitted working tree).
**Not done:** nothing from 2026-10-16 is committed. `brain_api` was not rebuilt, so Rust changes are source-only until the next release build.

**Live DB, read-only, 2026-10-16:** 26,321 memories · 70,671 edges · 27,348 entities · 9,982 superseded.

**Count:** 31 closed or fixed in source · 7 still open. Owner leftovers sit on closed V-04 (key revoke, memory-body redaction).

---

## Still open

| ID | What it is | Why it is still open | Do not |
|---|---|---|---|
| V-11 | Durable memories with zero edges | Remeasured **6,667** (solution 5,140, fact 1,054, knowledge 168, project_context 86, conversation 80, pattern 57, decision 55, error_lesson 27). The doc’s 2,654 and the Aug-19 “~9 left” note do not match this database. | Run `backfill_entities.py` without a canary the owner has eyeballed. |
| V-27 | Prose called `hit@5` a no-harm gate; numbered criterion 8 does not | Amendments now say criterion 8 gates `hit@3` and MRR. `hit@5` stays descriptive. | Add a `hit@5` pass/fail the numbered criteria do not name. |
| V-28 | Cited overlap mean 0.224 did not match the shipped stoplist | Remeasured 17/17 `gold_semantic.jsonl` rows: mean **0.2356**, max **0.4545**. Comment in `gen_gold_graph.py` updated. | Retune `MAX_VOCAB_OVERLAP` (stays 0.45). |
| V-32 | Many entities are degree-1 | **65.75%** (17,980 / 27,348). The 78.7% figure is stale. | Mass-delete degree-1 entities. |
| V-33 | Same thing stored under different names (`FEM` / `FINITE ELEMENT METHOD`) | Normalization is still lowercase plus whitespace. No alias table. | Invent aliases. |
| V-34 | `MAX_INPUT_CHARS = 8000` is characters, not tokens | Still a char slice in `entity_extractor.py`. No token budget. | Change the cap; it changes what the extractor sees. |
| V-37 | `brain_api.err` is an unbounded launchd log | Live file `~/Library/Logs/brain_api.err` (~12 MB). `docs/deploy/com.brain.api.plist` sets the path and does not rotate. | Delete the log. |

Generic names still in the entity table, not purged: `JSON` degree 127, `table` 28, `stack` 20, `Re` 17. The stoplist comment still leaves Row, Stat, Table, Stack, State, and Query out on purpose.

---

## Fixed 2026-10-16 (in the working tree, not deployed)

| ID | What changed | Where |
|---|---|---|
| V-13 | `eval_suite` passes `db_path` into `run_mcp_eval` | `brain/tools/eval_suite.py`, `brain/eval_suite.py` |
| V-22 | Dimension mismatch still returns neutral `1.0`, and logs once per process | `brain/rust/src/brain.rs` `cosine_distance` |
| V-23 | Bootstrap CI uses the type-1 percentile (`ceil`), so the lower bound is not one rank high | `brain/tools/graph_expand_ab.py` `bootstrap_delta_ci` |
| V-24 | McNemar p-value is computed in log space. `2.0**1024` is `inf`; the new value stays finite | `mcnemar_exact` |
| V-25 | Baseline p95 of 0 omits `latency_ratio_p95`, so the gate returns `INVALID_SET` | `build_report` |
| V-26 | `p_two_sided: null` returns `INVALID_SET` instead of `TypeError` | `gate` |
| V-29 | An all-dangling gold set includes `n_skipped_dangling` and says the ids are dangling | `brain/tools/mcp_eval.py` `run_mcp_eval` |
| V-30 | `brain/mcp_eval.py` re-exports `brain.tools.mcp_eval` | `brain/mcp_eval.py` |
| V-31 | Corpus-id load skips rows with `superseded_by` set when that column exists | `_load_corpus_ids` |
| V-35 | `" Solution "` still extracts. The type is stripped and lowercased first. Cap lookup does the same | `brain/api_client.py`, `entity_extractor._cap_for_type` |
| V-36 | `pop_matching_error` matches the file path only. A nearby unrelated error is not claimed as the fix | `brain/hooks/action_state.py`, `brain/action_state.py` |
| V-04 Rust hole | `link_memory_entities` drops secret-shaped names (`sk-or-v1`, `ghp/`). `sk-order` still links | `brain/rust/src/store.rs` `looks_like_secret` |

Tests that cover this batch: `brain/tests/test_graph_expand_ab.py`, `test_mcp_eval.py`, `test_api_client_auto_entities.py`, `test_smart_capture.py`. Rust: `cosine_distance_mismatch_is_neutral_not_a_truncated_dot`, `link_memory_entities_drops_secret_shaped_names`. Python 164 passed on that set, then the new cases re-ran at 15 passed. Those five Rust tests passed, including the existing orphan-edge test.

---

## Closed earlier

| ID | Closed | One line |
|---|---|---|
| V-01 | 2026-07-28 | Gate returns `INVALID_SET` when a criterion input is missing. `--ks 10` can no longer PASS. |
| V-02 | 2026-07-28 | Graph-expand tie-break keeps the base hit at rank 1. Injected neighbors do not win on UUID order. |
| V-03 | 2026-07-28 | Live entity LLM timeout is `(connect, read) = (3, 10)` seconds, not 120. |
| V-04 | 2026-08-12 | Python secret-shape filter plus entity purge. Memory-body redaction and provider revoke stay with the owner. Rust guard added 2026-10-16, not deployed. |
| V-05 | 2026-08-02 | Delete path cleans edges. Link refuses a missing memory. Orphans swept 1190 → 0. |
| V-06 | 2026-07-29 | The ship was committed so later diffs have a baseline. The tree is dirty again as of 2026-10-16. |
| V-07 | 2026-08-12 | Junk and hub entities purged (398 entities / 711 edges) plus a forward stoplist. |
| V-08 | 2026-07-29 | Stop hook cannot run destructive maintenance without the dry-run guard. |
| V-09 | 2026-08-12 | Unfiltered A/B runs are `INVALID_SET` on criterion 9. `--lift-only` is the explicit skip. |
| V-10 | 2026-08-12 | Per-type entity caps and salience rank. Existing at-cap rows were not re-extracted. |
| V-12 | 2026-08-12 | Bootstrap iterations below 1000 are rejected. |
| V-14 | 2026-08-12 | Gold preflight requires rejection slack so one `decision` miss cannot invalidate the run. |
| V-15 | 2026-08-12 | `import brain.ingest as bi; bi.payloads` works. Lazy package exports submodules. |
| V-16 | 2026-08-12 | Deploy parity set is derived from hook imports, not a hand-maintained list. |
| V-17 | 2026-07-30 | Read and write rate limits are separate. A `/stats` flood no longer 429s `/save`. Deployed that day. |
| V-18 | 2026-08-12 | Extract and link run after a successful, non-deduped save. Code is in the working tree. Batch saves still do not auto-extract. A response with no `deduped` field is treated as not deduped, so the running binary (not rebuilt) would still extract. |
| V-19 | 2026-07-28 | `extract_entities` does not raise on a non-string. |
| V-20 | 2026-07-28 | Parse stays inside the try. A list-shaped model `content` does not escape. |
| V-21 | 2026-07-28 | Non-string entity items are dropped, not stringified into a fake name. |
| V-38 | 2026-07-29 | Hook entry scripts are in the parity set, not only their imports. |

---

## Known residual (not a new V-id)

`mark_superseded` is a SQL update. Python curators write it directly, so the in-memory vector index keeps those embeddings until `brain_api` restarts. Startup load skips `superseded_by`. Search drops them only when a filter is present and `exclude_superseded` is set. No mid-process `index.remove` was added.

`graph_expand` stays **off**. The August 2026 live A/B on 150 gold queries: expand hurt hit@10 by 5.3 points and raised p95 latency 1.62× (1 gain, 9 losses at k=10).
