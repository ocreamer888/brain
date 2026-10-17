# Masterpiece Certificate

**Feature / job id:** `FEATURE-ID-HERE`  
**Date:** YYYY-MM-DD  
**Forge phase:** A | B | C | D  
**Owner sign-off:** _pending_

---

## Invariants (human-approved)

List only ids from `brain/constitution/invariants.yaml` that this ship claims to satisfy.

| ID | Statement | Verified |
|----|-----------|----------|
| INV-... | ... | [ ] |

---

## Evidence checklist

- [ ] Original failure reproduced (link: issue, V-item, or session note)
- [ ] `run_gates.py --phase verify` exit 0 (attach JSON: `brain/eval/runs/...`)
- [ ] Teeth: revert fix → test `TEST_PATH` fails → restore passes
- [ ] Gold eval / quality gate: metric = X (threshold Y) — or N/A with reason
- [ ] Canary: 100-row sample inspected — path: `...` — or N/A with reason
- [ ] Deploy parity: pass — or N/A with reason
- [ ] Red team / critic: 0 open P0/P1 — or waived with owner OK
- [ ] Live smoke: MCP/API path verified — or N/A with reason

---

## Gate artifacts

| Artifact | Path |
|----------|------|
| Gates JSON | |
| Canary sample | |
| Teeth log | |
| JSONL job transcript (Phase C+) | |

---

## Known unknowns (explicit — do not leave empty if any exist)

- Not tested:
- Assumes:
- Deferred:

---

## Human sign-off

> I sign **invariants only**, not implementation detail. Known unknowns accepted.

**Owner:** _______________ **Date:** _______________

---

## Machine stub (optional, for automation)

```yaml
certificate:
  feature_id: FEATURE-ID-HERE
  invariants: [INV-SESSION-01]
  gates_json: brain/eval/runs/gates-YYYYMMDD-HHMMSS.json
  signed: false
```

---

## History

<!-- Append-only: do not delete prior certificates. Copy to brain/eval/runs/certificates/ when filled. -->

### YYYY-MM-DD — Created from template

- Template version: 2026-08-12
