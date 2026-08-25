# Masterpiece Certificate

**Feature / job id:** `phase-c-canary-1k`  
**Date:** 2026-08-13  
**Forge phase:** C  
**Owner sign-off:** _pending (evidence filled by agent)_

---

## Invariants (human-approved)

| ID | Statement | Verified |
|----|-----------|----------|
| INV-SESSION-01 … INV-INGEST-01 (all 6) | Constitution suite via mid+end `run_gates.py --phase smoke` | [x] |

---

## Evidence checklist

- [x] Original need: Phase C detach worker for long jobs (C2 chosen over C1/C3)
- [x] `run_gates.py` mid + end in JSONL — `brain/eval/runs/phase-c-canary-1k.jsonl`
- [x] Teeth: N/A (no invariant code change this phase)
- [x] Gold eval / quality gate: N/A (smoke gates for job; constitution already Phase A verified)
- [x] Canary: **1000 rows** — `brain/eval/runs/canary-phase-c-canary-1k/` (≥1000 row acceptance)
- [x] Deploy parity: included in smoke gate paths when INV-DEPLOY-01 in filter… smoke runs all invariant tests
- [x] Red team: N/A scaffolding; irreversible backfill still requires owner OK
- [x] Live smoke: supervisor start → status running → success; attach documented in native-worker.md

---

## Gate artifacts

| Artifact | Path |
|----------|------|
| Gates / transcript JSONL | `brain/eval/runs/phase-c-canary-1k.jsonl` |
| Canary sample | `brain/eval/runs/canary-phase-c-canary-1k/` (1000 lines) |
| State | `brain/eval/runs/phase-c-canary-1k.state.json` |
| Job spec | `brain/harness/examples/job-phase-c-canary-1k.json` |

---

## Known unknowns

- Not tested: multi-hour wall clock; crash mid irreversible mutation recovery
- Assumes: smoke gates sufficient for this non-mutating acceptance job
- Deferred: launchd plist packaging; agent auto-repair on gate failure; optional C1 bridge doc

---

## Human sign-off

> I sign **invariants only**, not implementation detail. Known unknowns accepted.

**Owner:** _______________ **Date:** _______________

---

## History

### 2026-08-13 — Phase C C2 acceptance job

- Approach: C2 native worker
- Detach start pid recorded; mid+end gates; 1000-row canary; status=success
