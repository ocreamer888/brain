# Brain Forge — Phase D: Continual Harness (Tactics Only)

**Date:** 2026-08-12  
**Status:** Initial ship 2026-08-13 (ongoing capability)  
**Depends on:** [Phase B closed](./2026-08-12-brain-forge-phase-b-skills.md); [Phase C](./2026-08-12-brain-forge-phase-c-daemon-worker.md) recommended  
**Blocks:** — (ongoing capability)

---

## Goal

Enable **evidence-backed tactical improvement** — Prime Agent's Continual Harness `/refine` — **without** mutating the constitution.

Tactics (how to operate) may evolve. Invariants (what must be true) may not, except via human PR.

Paper reference: [Continual Harness (arXiv 2605.09998)](https://arxiv.org/abs/2605.09998) — H = (ρ, G, K, M).

---

## Threat model

| Risk | Mitigation |
|------|------------|
| Reward hacking via self-edit | Constitution files excluded from refine surface |
| Bad refine compounding | Rollback via Brain memory id + git history |
| Weak model mis-refines | Require frontier model + human review for ρ/G changes |
| Session-only loss | Persist to Brain MCP `pattern`, not session JSON only |

Prime Agent explicitly allows harness CRUD on ρ, G, K, M with immutable base prompt. Brain Forge **narrows** writable set:

| Component | Prime | Brain Forge |
|-----------|-------|-------------|
| Base system prompt | Immutable | `AGENTS.md` / `CLAUDE.md` core — immutable |
| Supplemental prompts ρ | `/refine` | Brain `pattern` tagged `harness_refine` |
| Subagent specs G | `/refine` | `.agents/skills/brain-forge-*/` — PR review |
| Skills K | skill-creator + refine | New skills via PR; refine updates SKILL.md tactics section only |
| Memory M | `/refine` | Brain MCP patterns; never auto-write `decision` as constitution |
| Constitution | N/A | **`brain/constitution/` — human PR only** |

---

## Refine pipeline (Brain Forge)

```text
Trigger: repeated failure OR explicit /refine OR post-closure lesson
  ↓
Planning (background LLM): propose smallest edit
  ↓
Classify target: tactic vs constitution
  ↓
If constitution → STOP, open human issue
  ↓
If tactic → write Brain pattern + optional SKILL.md append
  ↓
Record: refine_audit.jsonl (trigger, edit, outcome, rollback_id)
  ↓
Next job: load patterns tagged harness_refine in get_context_tool
```

### Audit log schema

`brain/eval/runs/refine_audit.jsonl`:

```json
{
  "refine_id": "uuid",
  "timestamp": "2026-08-12T...",
  "trigger": "gate failed twice on parity",
  "target": "pattern",
  "brain_memory_id": "...",
  "edit_summary": "Always run deploy_parity before hook edits",
  "outcome": "next run exit 0",
  "rollback": "delete memory id or revert skill commit"
}
```

---

## Deliverables

| Path | Purpose |
|------|---------|
| `docs/superpowers/specs/brain-forge/refine-policy.md` | Writable vs forbidden surfaces |
| `brain/harness/refine_audit.py` | Append-only audit helper |
| `.agents/skills/brain-forge-refine/SKILL.md` | Safe refine invocation |
| Brain tag convention | `harness_refine`, `forge_tactic` |

---

## `/refine` skill rules

**May propose:**

- "After editing hooks, run deploy parity first"
- "Critic must check JSON-quoted memory types in SQL"
- Canary checklist additions

**May not propose:**

- Lowering quality gate thresholds
- Removing invariants
- Disabling teeth checks
- Auto-approving bulk jobs

**Human review required for:**

- Changes to Critic/Red team core prompts
- New irreversible-action rules

---

## Relationship to Brain `reflect_tool`

`reflect_tool` consolidates duplicate memories — **orthogonal**. Refine adds tactics; reflect dedupes corpus. **Do not** wire refine to auto-delete memories. Freeze reflection during bulk ingest (`BRAIN_REFLECTION_DISABLED=1`) per AGENTS.md.

---

## Acceptance criteria (Phase D done)

- [x] `refine-policy.md` committed with forbidden paths list
- [x] `refine_audit.jsonl` written on at least one real refine event
- [x] One tactic refine recovered a repeated failure (documented in closure)
- [x] One attempted constitution edit correctly **blocked** (test or drill)
- [x] Index notes Phase D **Initial ship** (ongoing capability; not "forever closed")

Phase D is never fully "closed" — use **Initial ship** milestone then maintain via Updates.

---

## Tasks (execution checklist)

1. Write `refine-policy.md` with explicit path denylist (`brain/constitution/**`).
2. Implement audit append helper (no LLM inside).
3. Create `brain-forge-refine` skill with policy embedded.
4. Drill: attempt refine on invariant statement — must fail/escalate.
5. Real refine from verification lesson → Brain pattern → verify next job loads it via `get_context_tool`.

---

## Closure log (initial ship)

| Field | Value |
|-------|-------|
| Initial ship | 2026-08-13 |
| Evidence | Policy + `refine_audit.py`; tactic pattern `2cd6e2f3-17bb-4797-a5f2-cf01ac1908cc` (parity before hooks + canary before bulk); audit JSONL; `get_context_tool` top-hit; `test_refine_audit.py` 3 passed; certificate `…/brain-forge-phase-d-initial.md` |
| Blocked constitution drill | `check-path invariants.yaml` exit 2; append `--force-blocked` for remove INV-HOOK-01 / lower threshold |

---

## Updates

### 2026-08-12 — Phase spec created

- Highest risk phase — last in sequence by design.
- Reward-hack lesson from Prime Agent community analysis incorporated.

### 2026-08-13 — Unblocked

- Phase C closed with C2 native worker. Ready to execute Phase D (tactics-only refine + audit; constitution denylist).

### 2026-08-13 — Initial ship

- Shipped `refine-policy.md`, `refine_audit.py`, `.agents/skills/brain-forge-refine/SKILL.md`, `test_refine_audit.py`.
- Real refine: deploy-parity-before-hooks + canary-before-bulk → Brain `pattern` + audit.
- Constitution attacks blocked and audited.
- Ongoing: append more tactics via skill; never auto-edit constitution.

### 2026-08-14 — Refine denylist has a git hook

- `refine_audit.py check-staged` + `brain/harness/git-hooks/pre-commit` installed as `.git/hooks/pre-commit`.
- Constitution / gate paths cannot be committed without owner override (`--no-verify` is a human act).
- Policy is no longer skill-only classify.
