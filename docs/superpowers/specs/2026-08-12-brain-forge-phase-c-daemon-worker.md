# Brain Forge — Phase C: Long-Running Worker + JSON Event Stream

**Date:** 2026-08-12  
**Status:** Closed 2026-08-13 (C2)  
**Depends on:** [Phase B closed](./2026-08-12-brain-forge-phase-b-skills.md)  
**Blocks:** Phase D (unblocked)  
**Next phase when closed:** [Phase D — Continual harness](./2026-08-12-brain-forge-phase-d-continual-harness.md)

---

## Goal

Add a **detach/reattach capable worker** for jobs that exceed one Cursor session: entity backfill (~6k rows), graph A/B evals, long ingest, scheduled verification re-runs.

Prime Agent reference: daemon supervisor → session worker → persistent IPython → JSONL transcript. Brain Forge adapts the **pattern**, not the TypeScript stack.

**Trigger to start Phase C:** owner has a concrete job that failed or stalled due to session disconnect (e.g. V-11 backfill, widened durable entity backfill).

---

## Design options (pick one at Phase C kickoff)

| Option | Pros | Cons |
|--------|------|------|
| **C1 — Prime Agent as external runner** | Battle-tested daemon, `--autonomous-gate run_gates.py`, JSON mode | Second runtime, TS stack, not Brain-native |
| **C2 — Minimal `brain-forge` Python daemon** | Fits repo, wraps existing tools | Build supervisor ourselves |
| **C3 — launchd + background harness only** | Reuse `brain/hooks/background.py` patterns | No IPython RLM; less composable |

**Default recommendation:** C2 minimal daemon **or** C1 if owner already runs Prime Agent — document both in closure.

---

## Target architecture (C2)

```text
brain-forge supervisor (launchd or foreground)
  └── worker process per job
        ├── job spec JSON (intent, invariants, gates, budgets)
        ├── subprocess: Cursor/agent CLI OR embedded agent API
        ├── periodic: run_gates.py
        └── transcript: brain/eval/runs/<job-id>.jsonl
```

### Job spec schema (v1)

```json
{
  "job_id": "v11-backfill-canary",
  "intent": "Run entity backfill with canary gate",
  "invariants": ["INV-ENTITY-01", "INV-ENTITY-02"],
  "gates": ["python brain/harness/run_gates.py --phase verify"],
  "autonomous": {
    "max_turns": 20,
    "max_wall_ms": 7200000,
    "gate_retries": 3
  },
  "canary_required": true,
  "irreversible": true
}
```

### JSON event stream (Prime-inspired)

Events appended to `brain/eval/runs/<job-id>.jsonl`:

```json
{"type":"job_start","job_id":"...","timestamp":"..."}
{"type":"gate_start","gate":"run_gates.py","phase":"verify"}
{"type":"gate_end","exit_code":0,"duration_ms":12345}
{"type":"canary_complete","sample_path":"brain/eval/runs/.../canary.json"}
{"type":"agent_message","role":"critic","summary":"..."}
{"type":"job_end","status":"success|failed|budget","certificate_path":"..."}
```

Mirror Prime [JSON mode event types](https://github.com/PrimeIntellect-ai/prime-agent/blob/main/packages/coding-agent/docs/json.md) where useful — do not require full compatibility.

---

## Prime Agent integration path (C1)

If using [Prime Agent](https://github.com/PrimeIntellect-ai/prime-agent) directly:

```bash
cd /Users/abundancia888/Documents/Code/brain
prime-agent -p \
  --autonomous \
  --autonomous-gate ".venv/bin/python brain/harness/run_gates.py --phase verify" \
  --autonomous-gate ".venv/bin/python brain/tools/ingest_quality_gate.py --sample 100" \
  --autonomous-max-turns 30 \
  --mode json \
  "Execute job spec @brain/eval/runs/job-spec.json"
```

Document in `docs/superpowers/specs/brain-forge/prime-agent-bridge.md` when chosen.

---

## Deliverables

| Path | Purpose |
|------|---------|
| `brain/harness/job_spec.schema.json` | Job spec validation |
| `brain/harness/worker.py` | Minimal worker loop (C2) |
| `brain/harness/supervisor.sh` or launchd plist template | Start/stop/status |
| `docs/superpowers/specs/brain-forge/prime-agent-bridge.md` OR `native-worker.md` | Chosen approach |
| `brain/tests/test_harness_worker.py` | Faux job, no live LLM |

---

## Goals, heartbeats, schedules (Prime mapping)

| Prime feature | Brain Forge use |
|---------------|-----------------|
| `/goal` | Job spec `intent` until certificate written |
| `/heartbeat` | Re-run gates during long backfill |
| `prime-agent schedule` | Nightly quality gate on production DB (read-only) |

Implement in C2 only if C1 not adopted — avoid duplicating Prime if external runner wins.

---

## Acceptance criteria (Phase C done)

- [x] One long job (≥1 hour wall time or ≥1000 rows) completed with detach/reattach documented
- [x] JSONL transcript for that job in `brain/eval/runs/`
- [x] `run_gates.py` invoked automatically at least once mid-job and at end
- [x] Certificate produced for that job
- [x] Runbook: start, attach, stop, recover after crash
- [x] Index phase tracker: Phase C **Closed**

---

## Tasks (execution checklist)

1. Owner picks C1 vs C2 at kickoff — record in Updates below.
2. Implement chosen path with minimal scope.
3. Run one real job (likely canary + partial backfill, not full 6k without owner OK).
4. Write runbook + bridge doc.
5. Closure block below.

**Ask owner before:** full V-11 backfill, `brain_api` restart, any irreversible DB mutation.

---

## Closure log

| Field | Value |
|-------|-------|
| Closed | 2026-08-13 |
| Approach | **C2** (native `worker.py` + `supervisor.py`) |
| Job reference | `phase-c-canary-1k` — 1000-row RO canary, mid+end gates, detach start |
| Evidence | JSONL `brain/eval/runs/phase-c-canary-1k.jsonl`; canary 1000 rows; `test_harness_worker.py` 4 passed; runbook `docs/superpowers/specs/brain-forge/native-worker.md`; certificate `…/certificates/phase-c-canary-1k.md` |

---

## Updates

### 2026-08-12 — Phase spec created

- Deferred until Phase B closed and a concrete long job exists.

### 2026-08-13 — Unblocked

- Phase B closed (skills + teeth + canary + host bridge). Start Phase C when owner picks C1/C2/C3 and has a long job (e.g. durable entity backfill).

### 2026-08-13 — C2 chosen and closed

- Owner selected C2 (not C1 Prime, not C3 launchd-only).
- Shipped: `job_spec.schema.json`, `worker.py`, `supervisor.py`, `supervisor.sh`, `examples/job-phase-c-canary-1k.json`, `native-worker.md`, `test_harness_worker.py`.
- Acceptance job: detach `supervisor start` → status running → success; events include `gate_start mid` + `gate_start end`; 1000-row canary.
- No irreversible DB mutation (full V-11 still needs owner OK + canary).
- Phase D unblocked.
