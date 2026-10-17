# Verification Findings — Durable Entity Linking

**Verification run:** 2026-07-28 · **Last updated:** 2026-08-12
**Scope:** adversarial verification of amendments A1–A9 (see [`2026-07-28-durable-entity-linking-amendments.md`](./2026-07-28-durable-entity-linking-amendments.md))
**Method:** five independent read-only agents, each briefed to *find defects* and to report `PASS` only for claims it reproduced itself. Domains: Rust (A2/A8), Python save path (A3–A5/A7), backfill data integrity, live deployment (A9c), eval statistics (A1).

**System state (2026-08-12 validation remount)**

| | |
|---|---|
| memories / edges / entities / linked | 18,205 · 45,826 · 18,367 · 13,498 |
| orphan edges | **0** |
| live hook tree | synced for extractor + api_client after V-04b |
| git | `feature/durable-entity-linking` + uncommitted validation fixes |

**38 findings — ~20 closed / revised, ~18 open.** (August 2026 snapshot. Do not treat this line as current.)

**Current rollup (2026-10-17):** 31 closed or fixed in source, 7 open. Per-item table, live counts, and what not to run: [`2026-10-17-verification-queue-status.md`](./2026-10-17-verification-queue-status.md). The October code is uncommitted and `brain_api` has not been rebuilt.

Every severity below was independently reproduced before being recorded; anything an agent could not verify is marked as such rather than asserted.

---

## Working agreement for the open queue

Adopted 2026-07-29 after the ship produced compounding defects. **One issue at a time**, each with the same definition of done:

1. **Reproduce it first.** If it can't be reproduced, it isn't real and gets downgraded or closed.
2. **Fix it.**
3. **Prove the fix has teeth** — revert it, watch the specific test fail, restore.
4. **Full suite** (Python + Rust as applicable), plus parity if the live tree is touched.
5. **Close it here** with the evidence inline.

**Hard rule: no irreversible action without a canary.** No backfill without sampling ~100 rows and inspecting the output. No restart without the before-measurement captured. No sync without knowing what breaks if it's wrong.

*Why this rule exists:* the single most damaging finding (V-07, 28% junk entities) came from running 6,864 rows through an extractor whose output had never been inspected on 100. A four-minute canary would have caught it before 23,470 edges were written.

*What this rule does not fix:* V-01, V-02 and V-03 were each a **faithful implementation of a spec that was wrong**, with passing tests. Sequencing doesn't catch those — adversarial verification against live data does, and only once the defect is live enough to be observable. Both disciplines are needed.

Issues are grouped only when they share a file *and* a test run (e.g. the eval-gate LOW items). Bundling across subsystems is what produced this list.

---

## Severity key

| Level | Meaning |
|---|---|
| **CRITICAL** | Produces a materially wrong result that a human would act on, or loses data silently |
| **HIGH** | Security exposure, data-integrity decay, or a broken invariant the design depends on |
| **MEDIUM** | Real defect with a bounded blast radius, or a guard that fails open |
| **LOW** | Correctness hygiene; wrong but currently unreachable or cosmetic |
| **INFO** | Recorded for accuracy; no action implied |

---

## CRITICAL

### V-01 — `graph_expand_ab` gate could return PASS on absent evidence · **FIXED**

`_parse_ks` required only `10`, and `gate()` read every criterion with a *passing* default. `--ks 10` therefore produced a report with no `hit@1` key, and criterion 7 — the P@1 invariant whose stated purpose is "nonzero means a Rust ranking bug, stop and fix" — silently evaluated as satisfied.

```
same synthetic run, real +0.40 hit@1 invariant breach:
  --ks 1,3,5,10  ->  FAIL  "7: INVARIANT delta hit@1 0.4 != 0.0"   exit 1
  --ks 10        ->  PASS  []                                       exit 0
```

Also fail-open for absent `hit@3`, `mrr`, `latency_ratio_p95`, `filter_violations`.

**Fix:** `_parse_ks` now requires `{1, 3, 10}`; `gate()` returns `INVALID_SET` on any missing criterion input. Regression tests `test_parse_ks_requires_all_gated_endpoints` and `test_gate_returns_invalid_set_when_criterion_input_is_missing`.
**Impact if unfixed:** would have flipped `graph_expand` to default `true` on false evidence.

---

## HIGH

### V-02 — `graph_expand` changed rank 1; the A2.2 tie-break was the cause · **FIXED**

Introduced by this ship's own determinism fix. `final_score` can be exactly `0.0` (`bm25_norm` is 0 for the last-ranked BM25 hit; `cos_norm` is 0 for anything absent from the cosine set), so `0.0 × GRAPH_HOP_DECAY == 0.0` and an injected neighbour **ties the seed**. The `.then_with(|| a.0.id.cmp(&b.0.id))` tie-break then handed rank 1 to whichever UUID sorted lower. The previous score-only sort was *stable*, so base candidates always won.

```
"tailwind css dark mode", memory_type=solution, n=1
  OFF -> 617b0c86    ON -> 0100d3df     P@1 CHANGED
incidence: 4/480 default-alpha runs; 13/24 at alpha=0.0
```

**Fix:** tie-break on **origin**, not id — `(score desc, is_injected asc)` with a stable sort. Base candidates keep pre-expansion order; injected rows keep their deterministic `(score desc, id asc)` push order.
**Verified after rebuild+restart:** exact reproduction fixed; **0/38** default-alpha flips; **0/12** at `alpha=0.0`.
**Note:** this is precisely the defect V-01's criterion 7 exists to catch. Both were live simultaneously — the gate would have been blind to it.

### V-03 — Silent memory loss: 120 s LLM timeout on the interactive hook path · **FIXED**

`entity_extractor._call_llm` kept `timeout=120` when A3 moved that call onto the synchronous save path. `requests` applies a scalar timeout to connect **and** read separately, so worst case ≈240 s.

The chain, all three links verified:
1. live tree `entity_extractor.py:64` → `timeout=120`
2. `~/.claude/settings.json` → **no `timeout` on any of the four hooks** → harness default kills the process
3. `post_tool_use.py:186` → `enqueue_memory` is only reached inside `except` — a **killed process never reaches it**

Net: a stalled Ollama loses the memory entirely, with no spool entry and no error.

**Fix:** split budgets as `(connect, read)` tuples — `LIVE_TIMEOUT = (3, 10)`, `BACKFILL_TIMEOUT = (5, 120)`; backfill opts in explicitly. **Measured 120 s → 10.0 s** against a socket that accepts and never responds.
**Root cause:** amendment A5 said "move `_call_llm` verbatim". Verbatim was right for the prompt and stoplist and wrong for the timeout, because the execution context changed from batch to interactive.

### V-04 — Credential material stored as graph entities · **FIXED 2026-08-12**

```
entities matching sk-or-v1-* at reopen : 6  (4 real @73 chars, sk-or-v1-free, sk-or-v1-*)
edges                                  : 8
memories containing keys in CONTENT    : 10  (9 historical + 1 status-check save)
other secret shapes (sk-ant-, ghp_, AKIA, xox) as entities : 0
```

**The leak is ~3 months old and lives in memory content.** This ship did not create it — entity extraction surfaced the keys into a table designed to be exposed by retrieval, turning buried strings into queryable graph nodes. PII also present (a personal email, a named individual).

Mitigating: OpenRouter is no longer used anywhere (`0` env vars, no config references; the June migration moved everything to local Ollama), so the keys are probably already inactive.

**Closed 2026-08-12 (revised after validation — V-04b):**
1. **Secret-shape filter** widened to `search()` for bare `sk-or-v1` / `sk-or`, slash-meta `ghp/…/AKIA`, embedded keys; `_clean_entities` also runs on caller-supplied `entities=` and `link_entities` (no bypass). Synced to live hook tree. Reload MCP after deploy.
2. **Purges** — initial 6/8; remints (`sk-or-v1`, `sk-or`, `ghp/github_pat/AKIA`) + **Scene** hub re-purged. Backups under `junk_scrub_backups/` (**gitignored**; v04 JSON **redacted**). Live filter-matching secret entities: **0**.
3. **Memory redaction still deferred** — source memories can still contain key strings in **content** (retrieval exposure). Owner should **revoke** OpenRouter keys.
4. **Rust `/link-entities`** still has no server-side secret check — Python client sanitizes; direct HTTP can still plant secrets until a Rust guard lands.

### V-05 — Orphan edges are accumulating: 11 → 192 → 329 → **1190** · **FIXED 2026-08-02**

No FK or `ON DELETE CASCADE` from `edges.src_memory_id` → `memories.id`. 91 of the first batch existed *because* the backfill linked memories that `reflect_tool` then consolidated away. Every reflection cycle mints more.

**True count was undercounted.** Reads via `sqlite3 'file:...?mode=ro'` see a pre-checkpoint snapshot and miss uncommitted WAL frames — the 329/744/821 readings were low. A full `.backup` (WAL-aware) and a post-restart checkpoint both showed the real figure: **1190**.

**Two distinct orphan sources, both reproduced live and both fixed:**

1. **Delete path never cleaned edges** — the documented mechanism (~137/day). `store.delete_memories` (`store.rs`) deleted from `memories`/`memories_fts` only. Both live churn paths route through it — `/delete` and `/reflect`→`run_reflection` (`brain.rs:693`) — so every consolidation orphaned the deleted memory's edges. **Fix:** `DELETE FROM edges WHERE src_memory_id = ?1` inside the delete loop.
2. **`link_memory_entities` inserted edges without checking the memory exists** — `/link-entities` on a never-saved id returned `{"linked":2}` and created 2 orphan edges. In production this is a race (a backfill, or a caller whose id `reflect` deleted between read and link); memory `d292e442` orphaned with 8 edges on the *already-fixed* binary, which is what surfaced this second source. **Fix:** an existence guard at the top of `link_memory_entities` (`SELECT EXISTS(... FROM memories WHERE id=?)` → return `0` if absent). TOCTOU-safe: every API op serialises on one brain `Mutex`.

Chose the edge-cleanup step + existence guard over `ON DELETE CASCADE`, per "smallest change" — no schema migration, no per-connection `foreign_keys=ON` discipline. A CASCADE FK would also have covered both but is a recreate-table migration on a 44k-edge production table.

**Teeth:** `delete_memories_cleans_edges` (orphan check via `entities_for_memory`, which joins on `src_memory_id`) and `link_memory_entities_skips_nonexistent_memory`. Each proven by reverting only its fix and watching that test fail, then restored.

**Suites:** Rust **123 lib** (was 121) **+ 7 bin** · Python **390 / 5 skipped**. Rust-only; no parity impact.

**Deployed + verified live** (rebuild → `kickstart -k`, backup at `~/brain-backups/v05-orphan-sweep-20260801-151704.db`):
- delete path: saved a fact with 3 entities → 3 edges; `/delete` → **0 edges** (cleaned).
- link guard: `/link-entities` on a ghost id → `{"linked":0}`, **0 edges**.
- **one-off sweep** of `WHERE NOT EXISTS (live source memory)` — canary-verified 0 live edges in scope — cleared **1190 → 0**; residual orphans from the pre-guard window swept to **0**. Orphan count held at **0** afterward.

### V-06 — Production was running from an uncommitted working tree · **CLOSED 2026-07-29**

```
was: 77 uncommitted entries · 55 files changed, 1175 insertions(+), 435 deletions(-)
```

The `brain_api` binary serving port 8787 had been compiled from an uncommitted tree (verified by inode via `lsof`, SHA-256 `774ccaa8…`), with six of those files also being the live hook tree's dependencies — no commit boundary, and a stray `git checkout -- .` would have silently regressed production.

**Resolution:** committed and pushed. Verified `feature/durable-entity-linking` tracks `origin/feature/durable-entity-linking`; working tree clean apart from in-flight edits. Every subsequent issue now produces a readable per-issue diff against a real baseline.

### V-07 — Entity quality: ~28% junk, and generic words became hubs · **FIXED 2026-08-12**

Hand-classified sample of 200 of the 8,133 new entities:

| class | share |
|---|---|
| GOOD (technologies, files, people, orgs) | 37% |
| WEAK (code identifiers, generic concepts) | 35% |
| **JUNK** (code fragments, phrases, numbers, colors, CSS classes) | **28%** |

A mechanical regex detector independently finds 16.9% (1,371 entities, 2,800 edges) — treat that as a hard floor, since it cannot catch `constants`, `import`, `batch processing`.

Nine generic single words now have hub-scale degree: `solver` 93, `SPHERE` 48, `rod` 39, `spin` 33, `sheet` 29, `Transfer` 28, `wall` 27, `Wind` 23. `solver` at 93 would have cracked the pre-ship top-20. These are exactly the "hubs without meaning" the stoplist comment says it exists to prevent.

The top of the graph is still dominated by legitimate entities (`Next.js` 732, `React` 475, `PPF Contact Solver API` 464 — the last a genuine new domain). But **degree-weighted graph expansion should not ship on this as-is**, because that is what high degree does.

**Closed 2026-08-12 (honest residual):**
1. **Forward filter** — junk shapes + stoplist hubs including `scene` / `constants` / `import`. Keep real short names like `p-queue` / `font-awesome` (suffix allowlist, not len≤18).
2. **DB purge** — 398 entities / 711 edges (deg-1 junk + 8 measured hubs). **Later:** `Scene` (deg 101) purged with V-04b residual pass. `constants` / `import` may still exist at low degree (forward-stoplist only).
3. **Residual** — hundreds of **non-deg1** Tailwind/dotfile entities remain (out of cheap-pass scope; ~1–2% of graph). Deg-1 mechanical junk held at 0 post-purge.
4. Synced extractor (+ `api_client`) to live hook tree.

**Related:** amendment A5 deferred stoplist tuning on the grounds that `graph_expand` was off by default. That was true but incomplete — the Linked UI surfaces these today and the gate depends on them tomorrow.

### V-08 — Stop hook triggered real destructive maintenance with no dry-run guard · **CLOSED 2026-07-29**

`session_end.py` unconditionally spawned `run_reflect.py` (`POST /reflect`, which **deletes** memories — its log shows `-12`, `-7`, `-4` entries) and `run_cleanup.py` (BVH dedup with real `delete_memories`; noise auto-delete every 20th session). `_base_url()` always points at the real API regardless of where the script lives.

Surfaced because a verification agent was told to run each hook. **No data was lost** — dedup found `0 duplicates` and both reflection attempts hit 429, so rate-limit saturation from concurrent agents inadvertently protected the DB. The instruction that caused this was mine, and it was under-considered.

**Fix:** `BRAIN_SKIP_BACKGROUND_JOBS` guard, extracted into a new `brain/hooks/background.py` rather than left inline — `session_end.py`'s body executes at import, which is exactly why nothing in it had test coverage (the existing `test_session_end_summary.py` tests `core/session_ingest` instead of the hook).

**Proven both directions:**
```
guard ON   → both jobs skipped, no processes spawned, memories 17679 → 17679
guard OFF  → Popen called (mocked; nothing actually spawned)
teeth      → reverted to a bare Popen → structural test FAILED → restored → passes
live       → real Stop hook honours the guard; real PostToolUse save still succeeds
```
16 tests in `brain/tests/test_hook_background_guard.py`, including a structural test that greps for `spawn_background` near each destructive script so a regression to a bare `Popen` is caught rather than silently reintroducing this.

### V-38 — Hook *entry-point scripts* had drifted between trees · **CLOSED 2026-07-29**

Found while checking parity before syncing the V-08 fix. `SYNC_SET` covered only *imported modules*; A9c's derivation traced the import graph and never considered the scripts the harness actually executes.

```
session_end.py     DIFFERS  — live tree imported the STALE brain.summarizer / brain.memory;
                              repo imports brain.core.*
post_tool_use.py   DIFFERS  — repo had 7 lines of edit-buffered logging the live tree lacked
```

So the live Stop hook had been running an older module layout the entire time. This is also the mechanism behind the earlier "nothing imports the stale duplicates" correction — it was the *live* copy doing the importing.

**Fix:** verified the live tree could take the repo versions (`brain.core.*` imports cleanly there), backed up to `~/brain-backups/ai-hooks-232640/`, synced all three files, and added `session_end.py`, `post_tool_use.py` and `background.py` to `SYNC_SET`. Parity is now 11 tests over 9 files. Both hooks verified running live post-sync.

**Note:** this is V-16 materialising within one issue of starting the queue — a required file existed that the parity guard structurally could not have flagged.

---

## MEDIUM

### V-09 — Criterion 9 is vacuous on the default invocation · **FIXED 2026-08-12**
`filter_violations(rows, None, None)` returns `0`, and the gate accepts `0`. The unfiltered main run therefore passes criterion 9 without ever exercising a filter. Worse, `--surface template` (the default, and the one in A1's own verification command) **raises** on `--memory-type`, so the type-filtered sub-run is impossible on that surface. As written, A1's verification block can never produce criterion-9 evidence yet always passes it.

**Closed 2026-08-12 (revised after validation):** gate returns **INVALID_SET** on unfiltered runs for criterion 9 (no silent skip / no vacuous PASS). Full PASS requires `--memory-type` and/or `--project`. Lift-only analysis uses `--lift-only` / `GateConfig.allow_unfiltered_skip_criterion_9`. `filter_criterion_status` wired into consistency checks. Type-filtered sub-runs still require `--surface plain`.

### V-10 — Entity cap truncates 43% of `conversation` memories · **FIXED 2026-08-12**
`MAX_ENTITIES_PER_FACT = 12` was calibrated for ~100-char facts and holds there (0.1% saturation). Measured saturation at exactly 12:

| type | at cap | linked | % |
|---|---|---|---|
| conversation | 413 | 964 | **42.8%** |
| project_context | 76 | 338 | 22.5% |
| decision | 5 | 24 | 20.8% |
| solution | 197 | 1,308 | 15.1% |
| fact | 14 | 10,428 | 0.1% |

The 11→119→**734** cliff is a wall, not a distribution. `_clean_entities` breaks on the first 12 survivors **in LLM output order**, so what is kept is arbitrary rather than most-salient.

**Closed 2026-08-12 (forward path):** `MAX_ENTITIES_BY_TYPE` — fact/error_lesson=12, pattern/solution/decision/knowledge=16, project_context=20, conversation=24. Salience rank (uppercase / pathish / multi-word / length) before truncate. `api_client` + backfill pass `memory_type`. Existing at-cap rows are not re-extracted (would need a separate backfill pass).

### V-11 — 2,654 durable memories still have zero edges · **OPEN**
Checkpoint records 6,869 processed but only 4,219 received edges — **38.6% of processed rows produced zero entities**, 2,565 of them facts. Not corruption, but coverage is materially short of what "6,864 processed" implies.

### V-12 — `--bootstrap-iters` is unvalidated and guts criterion 6 · **FIXED 2026-08-12**
False-positive rate of `ci_lo > 0` under a true null (400 trials): `iters=1` → **0.26** (nominal 0.025); `iters=3` → 0.07; `iters=200` → 0.00. With `iters=1` the "95% CI" is a single replicate. **Recommended:** floor at 1000. Seed-shopping is *not* exploitable (0/200 seeds produced a false positive at 1000 iters).

**Closed 2026-08-12:** `MIN_BOOTSTRAP_ITERS = 1000`; CLI rejects lower values with exit 2 before any live searches.

### V-13 — `eval_suite` never passes `db_path` to `run_mcp_eval` · **FIXED 2026-10-16**
`eval_suite.py:203-206` passes `--db` to `offline_rrf_p1` but not to `run_mcp_eval`, which falls back to `_DEFAULT_DB_PATH`. With `--db <other.db>` the dangling-skip set is computed against one database and the baseline against another. Latent today (the two defaults are identical).

**Closed 2026-10-16:** both `brain/tools/eval_suite.py` and the top-level `brain/eval_suite.py` pass `db_path=` into `run_mcp_eval`.

### V-14 — `decision` stratum has zero slack; the gate will likely return INVALID_SET · **FIXED 2026-08-12**
Measured against the live DB at `oversample=1.5`: every stratum has slack except `decision` (want 10, asked 15, **got 10, slack +0**), because `MIN_CONTENT_CHARS=200` binds. Max achievable `n_queries` is exactly 150 at a **0% rejection rate** — so a single rejection anywhere drops below `min_n` → criterion 1 → `INVALID_SET`, after burning ~300 live searches. **Recommended:** decide before the run whether to lower `min_n`, relax `MIN_CONTENT_CHARS` for `decision`, or reallocate those 10 slots.

**Closed 2026-08-12 (revised after validation):** `check_stratum_capacity` uses `rejection_headroom = min(pool, asked) - want` with `MIN_REJECTION_SLACK=5` (oversample binds). Live re-measure: decision pool=16, want=10, asked=15, headroom=5 — passes.

### V-15 — Lazy `brain/ingest/__init__.py` breaks submodule attribute access · **FIXED 2026-08-12**
`import brain.ingest as bi; bi.payloads` raised `AttributeError` after PEP 562 lazy re-exports (submodules no longer auto-registered on the package).

**Fix:** `_LAZY_SUBMODULES` maps all seven ingest submodules; `__getattr__` returns the module for those names. Symbol re-exports unchanged.

**Teeth:** `brain/tests/test_ingest_lazy_submodules.py` (8 tests). Reverting the submodule branch → `AttributeError` on `bi.payloads`.

### V-16 — `test_deploy_parity.py` cannot catch a newly-required file · **FIXED 2026-08-12**
Hand-maintained `SYNC_SET` could not see newly imported siblings until something broke.

**Fix:** `brain/tests/deploy_parity_trace.py` — AST-closure of static `brain.*` imports from `HOOK_ENTRY_POINTS` (`post_tool_use.py`, `session_end.py`), minus `EXCLUDED`, plus `brain/ingest/__init__.py` when any ingest submodule is required. `test_deploy_parity.py` parametrizes over `derive_sync_set()` at collection time; `SYNC_SET_REASONS` is documentation-only.

**Discovered drift:** AST added `action_state.py`, `session_start.py`, `db.py`, `embedder.py`, `corpus_barrier.py` — two were out of sync with Documents/AI (synced). `fact_curator.py` correctly **drops** from hook sync (tool-only via `backfill_facts.py`, not hook path).

**Teeth:** `test_derive_sync_set_teeth_empty_entry_points` — empty entry points → `session_end` not required. `test_derive_sync_set_includes_hook_entry_points` — both entry points always in set.

### V-17 — Single shared rate-limit bucket starves the hooks · **FIXED 2026-07-30**
`client_key()` (`brain_api.rs:1388`) returns `"local"` for anything without an `x-forwarded-for` header, so hooks, MCP, evals, backfills and ad-hoc scripts share one 120 req/60 s budget. Reproduced repeatedly during verification. Hook saves then fail-soft into the spool — silent, and easy to miss. Not part of A1–A9, but it directly threatens Success Criterion 1.

**Reproduced (live, pre-fix):** flooding read-only `GET /stats` to exhaust the shared `"local"` bucket (112×200 → 429) starved the very next `POST /save` → **429, no write**. A read-heavy client (evals, MCP searches, ad-hoc scripts) thus silently blocks hook saves.

**Fix (owner chose read/write split, 2026-07-30):** the limiter key is now `(client_key, RateClass)` with `RateClass ∈ {Read, Write}` (`brain_api.rs`). Reads (`/stats`, `/search`, `/v1/*`, `/neighbors`, `/linked`, `/list`, `/entities`, `/get-episode`, `/stream`) and writes (`/save`, `/save-batch`, `/link-entities`, `/feedback`, `/delete`, `/reflect`, `PATCH /memories/:id`) hold independent 120/60 s budgets per client. No client changes; a read flood can no longer starve hook writes. All 18 call sites tagged (11 read / 7 write); `/health` remains unlimited.

**Teeth:** new bin test `read_flood_does_not_starve_writes` exhausts the read bucket then asserts a same-client `/save` returns 200. Reverting only `save`'s class to `RateClass::Read` made it fail (`429 != 200`); restored → passes.

**Suites:** Rust 121 lib + 7 bin (was 6) · Python 390 passed / 5 skipped. No parity impact (Rust-only; hook `SYNC_SET` untouched).

**Verified live after rebuild + `launchctl kickstart -k com.brain.api` (pid 88127 → 50800):** read bucket exhausted (`/stats` → 429) while a same-client `/save` returned **200** (id `27fd5c0c…`) — the exact sequence that returned 429 pre-fix.

### V-18 — Extraction runs *before* the save, so it is paid on deduped and failed saves · **FIXED 2026-08-12**
Identical content saved twice returned the **same id** (server-side dedup) after a full GPU call on the second. Same shape on API outage: full extraction cost, then a spooled payload that D5 forbids re-extracting.

**Fix:** `POST /save` response adds `deduped: bool` (`SaveOutcome` in Rust). Python `save_memory*` saves without entities, then `_link_entities_after_save` runs extract + `link_entities` only when save succeeded and `deduped` is false. Failed saves never call the extractor.

**Teeth:** `test_deduped_save_skips_extraction`, `test_save_failure_skips_extraction` in `test_api_client_auto_entities.py`; `save_memory_reports_deduped_flag` in Rust.

---

## LOW

| ID | Finding | Status |
|---|---|---|
| V-19 | `extract_entities` raised on non-`str` input (`text[:N]` was outside the `try`) — the docstring promised it never raises, and the test named for that invariant only made `_call_llm` raise | **FIXED** |
| V-20 | `_parse_entities` was outside the `try`; an OpenAI-compatible gateway returning `content` as a list of parts would raise | **FIXED** |
| V-21 | `[str(item) for item in raw_entities]` stringified junk — `{"entities":[{"name":"React"}]}` became an entity named `{'name': 'React'}` | **FIXED** |
| V-22 | `cosine_distance` returns a bare `1.0` on dimension mismatch with no log; if the embed model ever changes without a re-embed, every expanded hit silently reverts to the value downstream consumers discard. Unreachable today (all 17,681 embeddings are 768-dim, 0 NULL) | **FIXED 2026-10-16** — still returns neutral 1.0; logs once per process. Test `cosine_distance_mismatch_is_neutral_not_a_truncated_dot` |
| V-23 | Bootstrap percentile index off by one, biased **up** — the lower bound is the one criterion 6 gates on, so the bias direction is unsafe. No measurable practical effect | **FIXED 2026-10-16** — type-1 `ceil` via `_percentile` |
| V-24 | `mcnemar_exact` overflows at `b+c ≥ 1024` (`2.0**n`). Unreachable at `min_n=150` | **FIXED 2026-10-16** — log-space; `2.0**1024` is `inf`, new p stays finite |
| V-25 | Criterion 10 fails **open** when `baseline.latency_ms_p95` rounds to 0.00 — demonstrated passing a ~1e7× slowdown | **FIXED 2026-10-16** — ratio key omitted → INVALID_SET |
| V-26 | `gate()` raises `TypeError` on `p_two_sided: null` instead of failing closed; every other malformed input degrades to FAIL | **FIXED 2026-10-16** — null/non-numeric → INVALID_SET |
| V-27 | No `hit@5` no-harm gate despite A1's prose calling k=3 and k=5 "no-harm gates"; implementation matches the numbered criteria, prose and criteria disagree | OPEN — numbered criteria win; do not add a gate the criteria do not name |
| V-28 | `MAX_VOCAB_OVERLAP = 0.45` is tightly coupled to the exact shipped `_STOPWORDS`; the spec's cited mean (0.224) reproduces under a *different* stoplist than the one shipped (0.2356). Max (0.4545) reproduces exactly | OPEN — calibration note, threshold not retuned |
| V-29 | `n_skipped_dangling` is dropped exactly when it matters — an all-dangling gold set returns `status="skipped"`, `reason="no queries completed"` with no indication that 100% dangling was the cause | **FIXED 2026-10-16** — skipped payload includes the count and a dangling reason |
| V-30 | `brain/mcp_eval.py` is a **divergent** stale duplicate lacking the A9b fix (no importer found) | **FIXED 2026-10-16** — module re-exports `brain.tools.mcp_eval` |
| V-31 | `_load_corpus_ids` counts superseded memories as present, so a superseded gold target is scored as a guaranteed miss — the same P@1-deflation shape A9b fixed | **FIXED 2026-10-16** — SQL skips `superseded_by` when the column exists |
| V-32 | 78.7% of new entities are degree-1 (6,397 of 8,133) — index weight, no traversal value | OPEN — product fact, not a defect to mass-delete |
| V-33 | Identity fragmentation: `FEM`/`FINITE ELEMENT METHOD`, `MCP`/`MCP servers`, `gen_gold_graph.py`/`brain/tools/gen_gold_graph.py`. Normalization is lowercase-only; no aliasing | OPEN — no alias table without an owner-locked list |
| V-34 | `MAX_INPUT_CHARS` is a char cap, not a token cap — 8,000 chars is 8 KB ASCII but 24 KB CJK / 32 KB emoji, so A5's "≈1,221 tokens ≈ 2.0 s" holds only for ASCII | OPEN — changing the cap changes extraction input |
| V-35 | `memory_type` is matched case- and whitespace-sensitively; `"Solution"` or `"solution "` silently skip extraction. `mcp/server.py` normalizes, so only direct `api_client` callers are exposed | **FIXED 2026-10-16** — strip+lower before the durable-type check; cap lookup too |
| V-36 | `pop_matching_error`'s proximity fallback (`MAX_FIX_DISTANCE = 3`) mislabels memories — a Bash failure matched an unrelated `Write` one call later, producing a `solution` claiming a fix that never happened. Pre-existing | **FIXED 2026-10-16** — path match only; proximity fallback removed |
| V-37 | `brain_api.err` holds a ~600-line historical crash-loop (`database disk image is malformed`), never rotated and undateable. `PRAGMA integrity_check` is `ok` now | OPEN — do not delete the log from this pass |

---

## INFO — corrections to the amendments, and to my own reporting

- **"Nothing imports the stale duplicates" is false for one.** `brain/hooks/session_end.py:25` does `from brain.memory import save_memory as py_save` — the stale top-level copy, which has **0** references to `auto_entities` versus 2 in the synced `brain/core/memory.py`. Dead today only because `BRAIN_BACKEND=api`; flipping to `python` raises `TypeError`. *(Corrected in the amendments.)*
- **The `/linked` "over 6 MB means `neighbor_ids` leaked" tripwire in A8 is now wrong.** Actual is **8.08 MB** with no `neighbor_ids` — the backfill more than doubled entity refs. The mechanism still holds: reconstructing the removed payload gives ~139 neighbours/memory, so the old endpoint would return **~72 MB** today.
- **The claimed per-type link table was captured pre-mop-up.** It reconciles exactly once the mop-up (+64 memories, +228 edges) and 15 reflection deletions are applied. The backfill's own accounting matches the DB **to the edge** (`linked_total: 23470`).
- **15 pre-existing memories were deleted during the window** — attributable to `reflect_tool` consolidation, **not** the backfill. One deleted row's content reappears verbatim under a new id.
- **`fact_curator.py`'s place in `SYNC_SET` does not match the stated derivation.** No hook reaches it; it is required only if `backfill_facts.py` is ever run from the AI tree. Harmless, but the methodology claim is loose.
- **A9a's "`episode` — 0 rows exist" is stale.** There is now 1. Does not affect the gate.
- **A test was nearly disabled during the V-02 fix.** A scripted insertion landed between the original `#[test]` attribute and its function, silently turning `graph_expand_preserves_top1` into an uncalled function while registering the new test twice. Caught because cargo listed 8 tests with a duplicated name. Both are real tests now.
- **The original `graph_expand_preserves_top1` was structurally vacuous against V-02** — its fixture always gives the seed a strictly positive score, so `0.85 × s1 < s1` always held. Proven by reverting the fix: the new test fails, the original still passes.

---

## What survived attack

Recorded because it is evidence, not decoration:

- **A8's grouped-JOIN rewrite is equivalent byte-for-byte on all 13,297 live rows** — membership, entity list *and order*, snippet, type, project, timestamp. Attacked on orphan rows, duplicate edges, timestamp ties (21 groups now), and multibyte/emoji boundaries. Nothing found.
- **A2.1's filter fix holds across 640 live filtered runs, 0 violations** — and non-vacuously: 178 neighbours were genuinely injected, and a bare-string predicate control returns 0 rows, so a regression would fail the test rather than pass it.
- **The backfill write path is provably non-destructive.** All 17,671 common memories are byte-identical across **13 columns including the embedding BLOB**; all 20,789 baseline edges and 8,668 baseline entities survive with identical ids, weights, relation types and timestamps.
- **Scope discipline is exact:** 0 episodes linked, 0 superseded linked, 0 non-durable types linked, 0 cap violations, 0 duplicate triples, and **16,801/16,801** entity ids correctly derived per the documented `uuid5` rule.
- **`mcnemar_exact` matches `scipy.stats.binomtest` on 3,721 exhaustive pairs plus 7,000 random ones** — zero mismatches.
- **The bootstrap genuinely preserves pairing** — identical arms yield a zero-width CI, which is only possible if it resamples queries rather than arms. Coverage measured at 0.948–0.965 against nominal 0.95.
- **Success Criterion 1 is proven end-to-end through a real `PostToolUse` hook** — memory `b68759ad…` saved with 4 correctly-linked entities via the synced files.
- **The parity guard caught real drift within minutes of being written.**

---

## Queue

Owner chose **operational safety first** (2026-07-29).

| # | Issue | State |
|---|---|---|
| — | **V-06** commit the tree | ✅ closed — baseline exists |
| — | **V-08** Stop-hook background guard | ✅ closed |
| — | **V-38** hook entry-point drift | ✅ closed (fell out of V-08) |
| — | **V-17** rate-limit keying — read/write bucket split | ✅ closed — deployed + verified live |
| — | **V-04** revoke + purge credentials, add a secret-shape filter | ✅ closed — filter + purge; revoke still owner; redact deferred |
| — | **V-05** orphan-edge leak (delete path + link-without-check) | ✅ closed — deployed, swept 1190→0, verified live |
| — | **V-07 + V-10** entity-quality cleanup and per-type caps | ✅ closed — junk/hubs purged; caps+rank forward |
| — | **V-09, V-12, V-14** remaining gate holes → then run the A/B | ✅ closed — gate/CLI/gold preflight fixed |
| 7 | **A/B run** or **V-11** backfill | ← next (V-15–V-18 closed) |
| 7 | LOW table as hygiene | nothing blocks |

**Sequencing notes**

- **V-04b (2026-08-12):** graph secret entities held at 0 after widened filter + residual purge; **revoke keys + content redaction** still owner. `junk_scrub_backups/` gitignored. Reload MCP so filter loads. Rust `/link-entities` still lacks server-side secret check.
- **V-07 + V-10 closed 2026-08-12** — deg-1 junk + measured hubs purged; Scene removed in V-04b; non-deg1 Tailwind residual remains; forward caps/salience.
- **V-09 / V-12 / V-14 closed 2026-08-12** — unfiltered → INVALID_SET for criterion 9; bootstrap floor 1000; gold capacity preflight. A/B ready (plus filtered sub-runs).
- **V-05 closed 2026-08-02** — orphan sources fixed; orphans held at 0.
- **Next:** A/B run or V-11 backfill. V-15/V-16/V-18 closed 2026-08-12.
- **Superseded 2026-10-17:** the A/B already ran (expand hurts; leave `graph_expand` off). V-11 remeasured at 6,667 edgeless durable rows and was not backfilled. Read [`2026-10-17-verification-queue-status.md`](./2026-10-17-verification-queue-status.md) before picking the next issue.

## Closure log

| Date | Issue | Evidence |
|---|---|---|
| 2026-07-28 | V-01, V-02, V-03, V-19, V-20, V-21 | fixed during verification; each proven by reverting the fix and observing the specific failure |
| 2026-07-29 | V-06 | committed + pushed; branch tracks origin |
| 2026-07-29 | V-08 | 16 tests; guard proven ON and OFF; teeth proven; live hooks verified |
| 2026-07-29 | V-38 | 3 files synced; parity 11 tests / 9 files; both hooks verified live |
| 2026-07-30 | V-17 | read/write bucket split; teeth-proven regression test; deployed (pid 88127→50800) and verified live — read flood no longer 429s a same-client save |
| 2026-08-02 | V-05 | two orphan sources fixed (delete-path edge cleanup + link existence guard); 2 teeth-proven tests; deployed; swept 1190→0; verified live (delete cleans, link-guard blocks); orphans held at 0 |
| 2026-08-12 | V-04 | secret-shape filter + teeth tests; purged 6→0 entities/8 edges then 1 re-mint from stale MCP process (re-purged); live count 0; sync to Documents/AI hook tree; memory redact deferred; provider revoke still owner; **reload Cursor brain MCP** so filter loads |
| 2026-08-12 | V-04b | validation: widen filter (bare/slash secrets); sanitize entities=/link_entities; purge remints+Scene; gitignore+redact v04 backups; content redact still deferred; Rust link path still open |
| 2026-08-12 | V-07 | stoplist hubs + junk-shape filter; purged 398 entities/711 edges (deg-1 junk + 8 hubs); backup under junk_scrub_backups/; hubs gone; orphans 0; teeth-proven |
| 2026-08-12 | V-10 | MAX_ENTITIES_BY_TYPE + salience rank before truncate; api_client/backfill pass memory_type; forward-only (no re-extract of existing at-cap rows) |
| 2026-08-12 | V-09 | gate skips criterion 9 unless filtered sub-run; filter_criterion_status; 61 tests |
| 2026-08-12 | V-09b | validation fix: unfiltered → INVALID_SET (not silent skip); --lift-only escape; teeth tests |
| 2026-08-12 | V-12 | MIN_BOOTSTRAP_ITERS=1000; CLI exit 2 if lower |
| 2026-08-12 | V-12b | build_report also enforces floor; CLI test checks V-12 stderr before gold load |
| 2026-08-12 | V-14 | check_stratum_capacity + MIN_REJECTION_SLACK=5; live decision slack +6 |
| 2026-08-12 | V-18 | extract-after-save + `deduped` on `/save`; link_entities post-save; Python+Rust teeth |
| 2026-08-12 | V-16 | AST-derived sync set via deploy_parity_trace.py; 21 parity tests; synced action_state+session_start drift; fact_curator off hook path |
| 2026-08-12 | V-15 | `_LAZY_SUBMODULES` + 8 teeth tests; `bi.payloads` / `bi.fact_curator` etc. resolve without eager heavy imports |
| 2026-10-16 | V-13, V-22–V-26, V-29–V-31, V-35, V-36, V-04 Rust link guard | code fixes + tests below. Not deployed. No bulk DB write. |

## Updates

### 2026-10-16 — fail-closed hygiene, no bulk

Reproduced in the working tree, then fixed. Tests run: `pytest` on `test_graph_expand_ab.py`, `test_mcp_eval.py`, `test_api_client_auto_entities.py`, `test_smart_capture.py`, `test_entity_extractor.py` (164 passed, then the overflow assertion tightened and the new cases re-run, 15 passed). Rust: `cosine_distance_mismatch_is_neutral_not_a_truncated_dot` and `link_memory_entities_drops_secret_shaped_names` passed. `link_memory_entities_skips_nonexistent_memory` kept its `#[test]` (an edit had briefly stripped it; restored before the warning was left in the tree).

Left open on purpose:

- **V-11** — edgeless backfill is a bulk write. No canary eyeball this session, so it was not run.
- **V-27, V-28, V-32, V-33, V-34, V-37** — spec disagreement, calibration note, degree-1 share, aliasing, char-vs-token cap, historical log. No code change.
- **V-04 content redaction** — owner already said dead keys stay in memory bodies. Graph filter + the new Rust `looks_like_secret` guard on `link_memory_entities` is the remaining code hole. Provider revoke is still the owner's.

`brain_api` was not rebuilt or restarted, so the Rust secret guard is in source only until the next release build.

### 2026-10-16 — forensic remeasure (read-only)

Three read-only passes inspected the tree before the fixes above were saved. Re-checked after: V-13, V-22–V-26, V-29–V-31, V-35, V-36, and `looks_like_secret` are in the working tree. Their "still open" line cites are stale.

Live DB (`mode=ro`), same day:

| Check | Measured |
|---|---|
| Memories / edges / entities | 26,321 · 70,671 · 27,348 |
| V-11 edgeless durable, non-superseded | **6,667** (solution 5,140, fact 1,054, knowledge 168, project_context 86, conversation 80, pattern 57, decision 55, error_lesson 27). The Aug-19 "backfill finished, ~9 left" note does not match this database. |
| V-32 degree exactly 1 | **65.75%** (17,980 / 27,348). The 78.7% figure is stale. |
| V-31 superseded rows inside an unfiltered `SELECT id` | **9,982** |
| V-28 overlap, 17/17 `gold_semantic.jsonl` vs live content | mean **0.2356**, max **0.4545**. Comment updated. `MAX_VOCAB_OVERLAP` stays 0.45. |
| Generic names still stored | `JSON` deg 127, `table` 28, `stack` 20, `Re` 17. Stoplist comment still leaves Row/Stat/Table/Stack/State/Query out. Not purged. |

Still not done, with reason:

- **V-11** stays a bulk link job. No canary eyeball, no backfill.
- **V-27** prose clarified in the amendments. No new `hit@5` gate.
- **V-33 / V-34** alias map and token cap stay out. Both change extraction or merge existing rows.
- **Index residual:** `mark_superseded` is a SQL update. Python curators write it directly, so the in-memory vector index keeps those embeddings until `brain_api` restarts. Startup load now skips `superseded_by`. Search drops them only when a filter is present and `exclude_superseded` is set. No mid-process `index.remove` was added.
- **V-37** live log is `~/Library/Logs/brain_api.err` (~12 MB). Plist has no rotation. Log was not deleted.
- **V-18** save-then-link is in the uncommitted tree. Batch saves still do not auto-extract. A response missing `deduped` is treated as not deduped, so an old binary would still extract. `brain_api` was not restarted.
