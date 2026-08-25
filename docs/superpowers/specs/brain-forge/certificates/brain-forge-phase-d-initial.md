# Masterpiece Certificate

**Feature / job id:** `brain-forge-phase-d-initial`  
**Date:** 2026-08-13  
**Forge phase:** D (initial ship)  
**Owner sign-off:** _pending_

---

## Invariants

Constitution untouched. Phase D adds refine **policy + audit**, not new INV-* rows.

| Claim | Verified |
|-------|----------|
| Refine cannot edit `brain/constitution/**` | [x] `check-path` + classify drill exit 2 |
| Tactic refine → Brain `pattern` + audit | [x] memory `2cd6e2f3-17bb-4797-a5f2-cf01ac1908cc` |
| Blocked constitution attempts audited | [x] `refine_audit.jsonl` |

---

## Evidence checklist

- [x] `refine-policy.md` with denylist
- [x] `refine_audit.py` + `test_refine_audit.py` 3 passed
- [x] Skill `.agents/skills/brain-forge-refine/SKILL.md`
- [x] Real tactic refine (parity before hooks + canary before bulk) — recovers repeated V-07 / two-tree process failures
- [x] `get_context_tool(topic=harness_refine…)` returned the pattern as top hit
- [x] Constitution block drill recorded with `--force-blocked`

---

## Gate artifacts

| Artifact | Path |
|----------|------|
| Policy | `docs/superpowers/specs/brain-forge/refine-policy.md` |
| Audit JSONL | `brain/eval/runs/refine_audit.jsonl` |
| Brain pattern id | `2cd6e2f3-17bb-4797-a5f2-cf01ac1908cc` |

---

## Known unknowns

- Not tested: multi-agent concurrent refine races on audit file
- Assumes: agents follow skill classify-before-write (policy is soft without CI hook)
- Deferred: pre-commit hook calling `check-path` on staged files

---

## History

### 2026-08-13 — Phase D initial ship

---

## Updates

### 2026-08-14 — Pre-commit shipped (gap close)

Deferred hook is no longer deferred: `brain/harness/git-hooks/pre-commit` + `check-staged`. See certificate `forge-gap-close-2026-08-14.md`.
