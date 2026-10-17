# Handoff — Verification Findings Queue

**For:** the next agent continuing the open findings from the durable-entity-linking ship.
**Written:** 2026-07-29, at a context handoff. Everything needed is in this file plus the two documents it points at.

---

## 1. Read these first, in order

1. `CLAUDE.md` — project rules. Non-negotiable. Especially: read before acting, never guess, smallest change that works, check in before major changes.
2. `docs/superpowers/specs/2026-07-28-durable-entity-linking-verification-findings.md` — **the queue.** 38 findings, V-01…V-38, 10 closed. Contains the working agreement, per-issue evidence, and sequencing notes.
3. `docs/superpowers/specs/2026-07-28-durable-entity-linking-amendments.md` — what was built and why. Reference only; do not re-litigate it.

---

## 2. Your working agreement — follow this exactly

Adopted after this ship produced compounding defects. **One issue at a time.**

1. **Reproduce first.** If you cannot reproduce it, it is not real — downgrade or close it with your evidence. Do not fix things you have not seen fail.
2. **Fix it.**
3. **Prove the fix has teeth.** Revert your fix, watch the *specific* test fail, restore. A test that passes before and after your change is worthless. This has caught real problems three times.
4. **Run the suites.** `pytest brain/` and, if Rust changed, `cargo test --lib`. Parity too if you touched anything synced.
5. **Close it in the findings doc** with evidence inline, and update the Queue + Closure log tables.

**Hard rule: no irreversible action without a canary.**
- No bulk job without sampling ~100 rows and *inspecting the output*.
- No service restart without capturing the before-measurement.
- No sync without knowing what breaks if it is wrong.

> Why: the worst finding (V-07, 28% junk entities) came from running 6,864 rows through an extractor whose output had never been eyeballed on 100. Four minutes of canary would have prevented 23,470 edges of damage.
>
> What it does *not* fix: V-01/V-02/V-03 were each a faithful implementation of a **wrong spec**, with green tests. Sequencing cannot catch that. Only adversarial verification against live data does. Assume your specs are wrong too.

**Ask the owner before:** committing, revoking credentials, deleting DB rows, restarting `brain_api`, or changing `~/.claude/settings.json`.

---

## 3. Environment — get this wrong and you will waste an hour

| Thing | Value |
|---|---|
| Canonical repo | `/Users/abundancia888/Documents/Code/brain` |
| Branch | `feature/durable-entity-linking` (tracks origin, committed) |
| **Interpreter** | **`.venv/bin/python`** — system `python3` has NO pytest and NO requests |
| Full Python suite | **`pytest brain/`** — *not* `brain/tests/`; `brain/bootstrap/tests/` exists and is easy to miss |
| Rust | `cd brain/rust && cargo test --lib` |
| Live API | `http://127.0.0.1:8787`, key `local-dev-key`, launchd `com.brain.api` |
| DB | `brain/rust/brain.db` — **always open `file:...?mode=ro`** for reads |
| Live hook tree | `/Users/abundancia888/Documents/AI` — **hooks execute from here, not the repo** |
| Backups | `~/brain-backups/` — includes a pre-backfill DB snapshot |

**Baseline (2026-07-29):** Python 390 passed / 5 skipped / 0 failed · Rust 121 passed · memories 17,679 · edges 44,439 · entities 16,866. If your numbers differ wildly, something else changed — investigate before assuming you broke it.

---

## 4. Traps in this codebase — every one of these bit us

1. **Two trees.** Editing the repo does **not** change hook behaviour. `~/.claude/settings.json` runs `Documents/AI/brain/hooks/*.py`, which `sys.path.insert` to the AI root. `brain/tests/test_deploy_parity.py` enforces 9 files; run it after touching anything on that list. MCP, by contrast, *does* use the repo (`run_server.sh` exports `PYTHONPATH`).
2. **Stale duplicate modules.** `brain/post_tool_use.py`, `brain/session_end.py`, `brain/memory.py`, `brain/spool.py`, `brain/server.py`, `brain/mcp_eval.py`, `brain/ingest_session_chunks.py`, `brain/reingest_ocreamer_docs.py`, `brain/verify_cutover.py` are **stale**. Live code is under `brain/hooks/`, `brain/core/`, `brain/tools/`, `brain/mcp/`. Three separate agents edited the wrong copy. **Verify which is live before editing** (check what tests import, and what `run_server.sh` / `settings.json` point at).
3. **Memory types are JSON-quoted in SQLite.** `type = '"fact"'`, not `'fact'`. A bare-string predicate returns 0 rows and can make a test pass *for the wrong reason*. `entity_extractor.DURABLE_MEMORY_TYPES` holds **bare** strings for `memory_type` comparison; `backfill_entities._DURABLE_TYPES` holds **quoted** ones for SQL. Never mix.
4. **Rate limiting: 120 req/60s on a single shared `"local"` bucket** (this is V-17, still open). Concurrent probing produces sustained 429s that look like defects but are not. Pace your live calls; sleep between them.
5. **`ui/deploy.sh` comment lies.** It claims vite `emptyOutDir` is off; `vite.config.js:10` sets it `true`. `npm run build` **wipes the git-tracked `brain/rust/static/eval_dashboard.json`**. Restore it before `cargo build --release`, and build the UI *before* the Rust binary (rust-embed compiles `static/` in).
6. **`session_end.py`'s body runs at import** — you cannot import it in a test. That is why V-08's guard was extracted into `brain/hooks/background.py`. Do the same for anything else there that needs testing.
7. **A broad `try` swallows stub signature errors.** When you add a parameter, existing test doubles with narrower signatures raise `TypeError`, which `extract_entities`' catch-all converts into a silent empty result. Symptom: a test fails with `IndexError: list index out of range` on a capture list. Fix the stub, not the production code.
8. **`brain/eval/runs/` does not exist.** Any tool writing there must `mkdir(parents=True, exist_ok=True)` first.
9. **Don't script-edit Rust test blocks.** A text insertion between `#[test]` and its `fn` silently disables the original test and double-registers yours. Verify with `cargo test --lib <filter> -- --list` and check the names.
10. **Do not mutate git state** to answer questions (no `stash`, `checkout --`, `reset`, `clean`). Compare file mtimes or ask instead.

---

## 5. What is next

**V-17 — single shared rate-limit bucket starves the hooks.** Owner chose operational-safety-first.

`client_key()` at `brain/rust/src/bin/brain_api.rs:1388` returns `"local"` for anything lacking an `x-forwarded-for` header, so hooks, MCP, evals, backfills and ad-hoc scripts share one 120 req/60s budget. Hook saves then fail-soft into the spool — silent and easy to miss. It directly threatens Success Criterion 1.

**This is not purely additive** — changing the bucket key affects every client. So:
1. Reproduce the starvation (flood `/search`, watch `/save` 429).
2. **Propose the keying scheme to the owner before implementing.** Options worth weighing: separate write vs read buckets (no client changes, directly fixes the observed failure); a client-supplied `x-brain-client` label with a default; or per-endpoint budgets. Recommend one, do not survey.
3. Then the standard 5 steps.

After V-17, the queue order is in the findings doc. Two notes carried forward:
- **V-04 needs the owner** — key revocation is not yours, and purging entities writes to production.
- **V-05 is the only finding actively worsening** (orphan edges 11 → 192 → 329, ~137/day). If V-17 stalls, do this one instead; it is contained.
- **V-07 gates the A1 A/B.** Do not run the gate before entity cleanup — it would produce a precise number measuring noise propagation.

---

## 6. How to behave

- **Verify claims yourself.** Subagents and prior notes report confidently and are sometimes wrong. Three agents corrected *my* stated facts during this ship, and one of my own "verified" numbers (`0/6 gold ids resolve`) was a bug in my own check — the schema key was `gold_ids`, not `gold_memory_id`, and I had printed the correct key and misread it.
- **Report failures verbatim.** Never claim a passing test you did not observe.
- **Say UNVERIFIABLE** when you cannot check something. It is more useful than a confident guess.
- **Push back** when a finding is wrong, a fix is over-engineered, or the sequencing is bad. The findings doc is evidence, not scripture.
- **Distinguish "the tests pass" from "it works."** Four defects in this ship had green suites and were live in production.

---

## Updates

### 2026-10-17 — this handoff’s “what is next” is historical

Section 5 still says to start at V-17. That item closed on 2026-07-30 (read/write rate buckets, deployed). V-05 and V-07 closed after this file was written. Do not follow section 5 as a work order.

Read, in this order:

1. [`2026-10-17-verification-queue-status.md`](./2026-10-17-verification-queue-status.md) — one row per V-01…V-38.
2. [`2026-07-28-durable-entity-linking-verification-findings.md`](./2026-07-28-durable-entity-linking-verification-findings.md) — original evidence. Its opening “~18 open” line is the August snapshot.

Open as of that status page: **V-11, V-27, V-28, V-32, V-33, V-34, V-37**. V-11 is a bulk link (6,667 edgeless durable rows on 2026-10-16). No backfill without a canary the owner has eyeballed. Trap 4 in section 4 (one shared `"local"` bucket) is outdated for writes: reads and writes have separate budgets. A Viewer `/stats` flood can still 429 other reads.
