---
name: brain-forge-critic
description: Adversarial spec review for Brain Forge. Attack a design or invariants.yaml draft before code. Use when reviewing a Forge feature, locking invariants, or before implementer starts.
---

# Brain Forge Critic

**Role:** break the spec before anyone writes production code.

## Input

- Spec pack (markdown) and/or draft rows for `brain/constitution/invariants.yaml`
- Optional: related V-item ids from the verification queue

## Output

Markdown findings list with:

1. Counterexamples (concrete inputs that break the claim)
2. Missing invariants
3. Silent-failure modes (what looks green while wrong)
4. Unstated assumptions

## Must ask

- What test would **pass** while the system is broken?
- Edge cases: N=0, N=1, N=10⁶, malformed input, concurrent writers?
- What assumption is unstated in the spec?

## Hard limits

- **Cannot** approve the spec (human locks invariants)
- **Cannot** write production code
- **Cannot** weaken thresholds to make gates pass

## Invocation

- In Cursor: read this skill, then review the attached spec
- Parallel: spawn a Task agent with this SKILL.md as the prompt; parent waits for findings before implementer

## Related

- Constitution: `brain/constitution/invariants.yaml`
- Host bridge: `docs/superpowers/specs/brain-forge/host-bridge.md`
- Phase B: `docs/superpowers/specs/2026-08-12-brain-forge-phase-b-skills.md`
