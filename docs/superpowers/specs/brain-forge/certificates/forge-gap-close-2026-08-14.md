# Masterpiece Certificate

**Feature / job id:** `forge-gap-close-2026-08-14`  
**Date:** 2026-08-14  
**Forge phase:** D (gap close — teeth / hook / daemon / crash-resume)  
**Owner sign-off:** _pending_

---

## Invariants (human-approved)

| ID | Statement | Verified |
|----|-----------|----------|
| INV-HOOK-01 | session_end background guard prevents runaway subprocess | [x] auto-probe |
| INV-SESSION-01 | Empty or meta-only transcript produces zero LLM memory writes | [x] auto-probe |
| INV-ENTITY-01 | Secret-shaped token names never become entities | [x] auto-probe |
| INV-ENTITY-02 | Junk and hub entity names are filtered | [x] auto-probe |
| INV-DEPLOY-01 | Hook-path Python modules match AST-derived deploy parity sync set | [x] auto-probe |
| INV-INGEST-01 | import brain.ingest does not eagerly import torch | [x] auto-probe |

---

## Evidence checklist

- [x] Original gaps named: only INV-HOOK-01 had teeth; refine policy soft; no packaged daemon; no mutating worker E2E; crash mid-write unproven
- [x] `teeth_check.py --all` exit 0 — all 6 registered probes (2026-08-14T23:03:43Z evidence under `brain/eval/runs/teeth-INV-*-20260814-230343.json` et al.)
- [x] `pytest brain/tests/test_forge_phase_b.py` 7 passed (parametrized auto-probe + canary)
- [x] Git hook: `.git/hooks/pre-commit` → `brain/harness/git-hooks/pre-commit`; `test_refine_audit.py` check-staged tests passed
- [x] Daemon: `supervisor.py daemon --once` (`test_daemon_once_processes_inbox`); plist template `docs/deploy/com.brain.forge.plist` **not** loaded
- [x] Crash resume (faux): `test_worker_crash_then_recover` — step 0 write, SIGTERM during sleep, recover, step 2 marker
- [x] Canary preflight (read-only): 100 edgeless durable rows — `brain/eval/runs/canary-forge-entity-backfill-canary-25-preflight/` — corpus has 1437 edgeless durable; sample includes `.claude` / `services` path-fragment projects (known, not a secret leak)
- [x] Live mutating 25-row backfill through worker + mid-write crash/recover on `:8787` — **run 2026-08-18** (owner-approved). Crash at 13/25 (SIGTERM), atomic checkpoint intact, recover → success, end gate pass. DB delta +300 edges / +134 entities; prod checkpoint untouched. **Finding:** resumed run processed 38 distinct memories, not 25 — see history.

---

## Gate artifacts

| Artifact | Path |
|----------|------|
| Teeth --all | `brain/eval/runs/teeth-INV-*-20260814-23034*.json` |
| Canary preflight | `brain/eval/runs/canary-forge-entity-backfill-canary-25-preflight/` |
| Job spec | `brain/harness/examples/job-entity-backfill-canary-25.json` |
| Dedicated checkpoint (when run) | `brain/eval/runs/checkpoint_forge_entity_backfill_canary.json` |
| Plist (not loaded) | `docs/deploy/com.brain.forge.plist` |

---

## Known unknowns (explicit)

- ~~Not tested: live `POST /link-entities` × 25 via worker; crash then `recover`~~ — **TESTED 2026-08-18** (crash at 13/25 → recover → success; see History). Superseded.
- ~~Open (behavior): `--limit N` is not a lifetime cap across a crash~~ — **CLOSED 2026-08-19** (frozen work_set; see History). Bounded canaries are now crash-stable.
- ~~Open (data quality): path-fragment/hostname junk still becomes entities~~ — **CLOSED 2026-08-19** (path/host filter in `_looks_like_junk`, synced to live tree; see History). Full ~1437-row backfill unblocked pending a fresh dry-run confirm.
- Assumes: `brain_api` on `:8787` (health ok 2026-08-14 and 2026-08-18); Ollama for extract (empty entities on LLM fail still checkpoint)
- Deferred: `launchctl load` of `com.brain.forge`
- Does not touch: production `brain/bootstrap/checkpoint_entity_backfill_durable.json` (verified untouched post-drill, mtime Jul 28)

---

## Human sign-off

> I sign **invariants only**, not implementation detail. Known unknowns accepted.

**Owner:** _______________ **Date:** _______________

---

## History

### 2026-08-14 — Gap close (code + unit/teeth; live mutate pending)

- Closed automated teeth for all six constitution invariants.
- Refine denylist enforced at pre-commit.
- Packaged daemon + recover path; faux crash drill green.
- Live 25-row worker mutate + mid-write crash still owner-run.

### 2026-08-18 — Re-validation loop (owner declined live mutate)

- Re-ran full gauntlet on `:8787` (API + Ollama healthy): `teeth_check.py --all` exit 0
  (6/6, evidence `brain/eval/runs/teeth-INV-*-20260818-2242*.json`); forge suite
  `test_forge_phase_b / test_harness_worker / test_refine_audit / test_run_gates /
  test_hook_background_guard` 37 passed; backfill/entity/api_client suites 116 passed.
- Refine denylist re-verified end-to-end: constitution + gate paths → exit 2; normal path → exit 0.
- **Fix shipped:** `backfill_entities.save_checkpoint` now writes atomically (temp + `os.replace`)
  so a SIGTERM during the crash-resume drill cannot leave a torn checkpoint that breaks
  `load_checkpoint` on recover. Directly hardens the mid-write path INV the drill exercises.
- Pre-mutation evidence: full read-only 25-row dry-run against the live sample — no secret-shaped
  values emitted (INV-ENTITY-01 holds); residual noise is path-fragment/hostname junk nodes
  (INV-ENTITY-02 does not filter these — known, cleanup tools exist). Prod checkpoint untouched
  (mtime Jul 28); dedicated canary checkpoint not created (job not started).
- **Live 25-row mutate: owner declined this session — remains owner-pending.** Gap 5 open by choice.

### 2026-08-18 (later) — Live canary drill run (owner-approved)

- Baseline: 51503 edges / 20562 entities. Fresh dedicated checkpoint.
- Sequence (transcript `brain/eval/runs/forge-entity-backfill-canary-25.jsonl`):
  `job_start → canary → mid-gate exit 0 → command_start → CRASH (SIGTERM, signal 15) at 13/25 →
  job_resume next_step=1 → command_end exit 0 → end-gate exit 0 → success`.
- **Crash-safety proven on the real mutating path:** checkpoint was valid JSON at crash (atomic
  write held — no torn file, no leftover `.tmp`); recover skipped already-processed ids (idempotent
  per-id); zero data loss.
- Writes landed: +300 edges (51503→51803, = `linked_total`), +134 entities (20562→20696).
  Production checkpoint `checkpoint_entity_backfill_durable.json` untouched (mtime Jul 28).
- **FINDING (behavior, low severity):** the resumed run processed **38 distinct memories, not 25.**
  Root cause: `select_edgeless_durable(limit=25)` re-evaluates a predicate (`id NOT IN edges`) that
  the job itself mutates. After the crash, the 13 already-linked rows left the edgeless set, so the
  resume re-selected a fresh 25-row window; `processed_ids` prevented re-processing but did not cap
  the total to the nominal limit. Idempotency holds; the `--limit` is not a hard cap across a crash.
- **Scope of finding:** affects only `--limit`-bounded canaries. The production full-corpus backfill
  (no `--limit`) is unaffected — it targets *all* edgeless rows and converges correctly on resume.
- **Recommended hardening (optional, before any future limited-crash job):** on first run, freeze the
  selected id set into the checkpoint and process only from that frozen list on resume, so `--limit`
  is a stable work set. Not required for the un-limited production backfill.

### 2026-08-19 — Both hardenings shipped (owner-directed)

- **#1 Frozen work set (`backfill_entities.py`):** `--limit N` jobs now snapshot their selected id
  list into the checkpoint (`work_set`) and, on resume, process exactly those ids via `select_by_ids`
  — no more re-querying the mutated edgeless window. `--limit` is now a hard lifetime cap across a
  crash. Un-limited full-corpus runs unchanged (re-query edgeless → converge). Tests:
  `test_limit_freezes_work_set_in_checkpoint`, `test_resume_limit_stays_within_frozen_set`
  (the exact 38-not-25 regression), `test_unlimited_run_does_not_freeze`. Backfill suite 15 passed.
- **#2 Path/host junk filter (`entity_extractor.py`):** `_looks_like_junk` now drops per-machine
  junk the dry-run surfaced — absolute/home paths (`/Users/…`, `~/…`, `C:\…`), URLs, mDNS `*.local`
  hostnames, IP[:port]; `localhost` added to the stoplist. Repo-relative paths (`brain/api_client.py`)
  are intentionally kept. Test `test_clean_entities_drops_machine_path_and_host_junk` uses the exact
  dry-run leaks; now part of INV-ENTITY-02's teeth. Entity suite 36 passed; teeth `--all` 6/6.
- **Deploy parity restored:** synced `entity_extractor.py` to the live hook tree (`~/Documents/AI`,
  old copy backed up under `~/brain-backups/`) so hook-originated saves get the filter too.
  `test_deploy_parity.py` 22 passed.
- **Full backfill unblock:** with #2 live, the data-quality gate on the ~1.4k-row backfill is closed.
  Junk shapes are filtered at the golden path; remaining recommendation before a full run is a fresh
  read-only dry-run to confirm the residual entity mix.
