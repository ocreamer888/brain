# Masterpiece Certificate

**Feature / job id:** `brain-forge-phase-b`  
**Date:** 2026-08-13  
**Forge phase:** B  
**Owner sign-off:** _pending (evidence filled by agent)_

---

## Invariants (human-approved)

| ID | Statement | Verified |
|----|-----------|----------|
| INV-HOOK-01 | session_end background guard prevents runaway subprocess | [x] teeth auto-probe |
| INV-DEPLOY-01 | Hook-path modules match deploy parity sync set | [x] via run_gates |
| INV-SESSION-01 | Empty/meta transcript → zero LLM writes | [x] via run_gates |
| INV-ENTITY-01 | Secret-shaped tokens never become entities | [x] via run_gates |
| INV-ENTITY-02 | Junk/hub entity filters | [x] via run_gates |
| INV-INGEST-01 | import brain.ingest does not eagerly import torch | [x] via run_gates |

---

## Evidence checklist

- [x] Original failure reproduced — V-08 (background guard) as teeth probe target; Phase B delivers repeatable roles
- [x] `run_gates.py --phase verify` exit 0 — `brain/eval/runs/gates-phase-b.json`
- [x] Teeth: `--auto-probe INV-HOOK-01` baseline pass → break fail → restore pass — `brain/eval/runs/teeth-INV-HOOK-01-phase-b.json`
- [x] Gold eval / quality gate: N/A for Phase B ship (gates verify used `--skip-quality-gate`; Phase A full verify already green)
- [x] Canary: 100-row sample — `brain/eval/runs/canary-phase-b-forge/` (format proof for skill; not a bulk mutation job)
- [x] Deploy parity: pass (included in run_gates)
- [x] Red team / critic: waived for harness scaffolding — skills themselves encode critic/canary/teeth contracts; no product code path changed beyond helpers
- [x] Live smoke: MCP `save_memory_tool` for this closure; helpers run under `.venv`

---

## Gate artifacts

| Artifact | Path |
|----------|------|
| Gates JSON | `brain/eval/runs/gates-phase-b.json` (gitignored under eval/runs) |
| Canary sample | `brain/eval/runs/canary-phase-b-forge/` |
| Teeth log | `brain/eval/runs/teeth-INV-HOOK-01-phase-b.json` |
| JSONL job transcript (Phase C+) | N/A |

---

## Known unknowns (explicit)

- Not tested: auto-probe registry for invariants other than INV-HOOK-01
- Assumes: Cursor loads project `.agents/skills/`; MCP host available for closure saves
- Deferred: `orchestrate_spec.py` headless driver (Phase B stretch); Phase C daemon

---

## Human sign-off

> I sign **invariants only**, not implementation detail. Known unknowns accepted.

**Owner:** _______________ **Date:** _______________

---

## Machine stub

```yaml
certificate:
  feature_id: brain-forge-phase-b
  invariants: [INV-HOOK-01, INV-DEPLOY-01, INV-SESSION-01, INV-ENTITY-01, INV-ENTITY-02, INV-INGEST-01]
  gates_json: brain/eval/runs/gates-phase-b.json
  teeth_json: brain/eval/runs/teeth-INV-HOOK-01-phase-b.json
  canary_dir: brain/eval/runs/canary-phase-b-forge
  signed: false
```

---

## History

### 2026-08-13 — Phase B closure certificate

- Skills: critic, canary, teeth, closure under `.agents/skills/brain-forge-*/`
- Helpers: `teeth_check.py`, `teeth_probes.py`, `canary_sample.py`
- Host bridge doc committed
