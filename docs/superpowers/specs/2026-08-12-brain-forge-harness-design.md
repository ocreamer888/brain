# Brain Forge Harness — Design

**Date:** 2026-08-12  
**Status:** Draft — approved for phased execution  
**Approach:** Prime Agent runtime patterns + Brain verification constitution + deterministic truth layer

---

## Problem

Frontier models are strong at **generating** mathematically flavored system designs and code. They are weak at **guaranteeing** global correctness over long horizons. Green tests can pass for wrong specs (V-01/V-02/V-03 in the entity-linking ship). Self-improving harnesses can reward-hack by mutating supplemental state.

We need a harness that:

1. Runs agents as **programs** (compose, parallelize, persist — not one chat thread).
2. Treats **invariants as law** (human-locked, machine-verified).
3. Separates **tactical adaptation** from **constitutional truth**.
4. Reuses Brain's existing verification muscle (queue, teeth, parity, gold eval, canary).

---

## Conversation lineage (preserve context)

This design synthesizes three discussion threads (2026-08-12):

### Thread 1 — Confidence in frontier models for deep mathematical logic

- **Local math / known patterns:** high confidence with verification tooling.
- **Multi-subsystem design:** medium — needs human invariant ownership.
- **Novel formal theory, unsupervised:** low — silent wrongness is the failure mode.
- **Rule:** confidence = how fast you can **falsify** the design.

### Thread 2 — Masterpiece harness (100% confidence goal)

Proposed 5-layer architecture:

1. Human invariant lock
2. Architect → spec pack
3. Critic adversary (pre-code)
4. Implementer + test author (tests from invariants, not impl)
5. Deterministic verifier harness → red team → human signs invariant sheet only

Key Brain mappings already in production:

- `ingest_quality_gate.py` — threshold exit codes
- `test_deploy_parity.py` — hook sync
- Verification queue handoff — reproduce → fix → teeth → close with evidence
- `graph_expand_ab.py` — eval before default flip

### Thread 3 — Prime Agent as reference

Deep read of [Prime Agent](https://github.com/PrimeIntellect-ai/prime-agent) → rethought as **Brain Forge**, not a TypeScript rewrite.

---

## Prime Agent — engineering summary

### Two core abstractions

**1. RLM (Recursive Language Model)**

- Persistent IPython kernel = single built-in model tool.
- Context as Python variables; subagents = `await rlm("task", name="reviewer")`.
- Children return via `agent_message.send()`, not function return values.
- TypeScript host owns providers, credentials, transcripts, scheduling; Python is control plane.
- Docs: [rlm.md](https://github.com/PrimeIntellect-ai/prime-agent/blob/main/packages/coding-agent/docs/rlm.md), [architecture.md](https://github.com/PrimeIntellect-ai/prime-agent/blob/main/packages/coding-agent/docs/architecture.md).

**2. Continual Harness** — H = (ρ, G, K, M)

- ρ prompts, G subagent specs, K skills, M memory — mutable supplemental state.
- `/refine` — smallest evidence-backed CRUD edit from trajectory; rollback by snapshot.
- **Immutable base system prompt** — refinements cannot rewrite core instructions.
- Paper: [arXiv 2605.09998](https://arxiv.org/abs/2605.09998).

### Long-running substrate

- Daemon supervisor → session workers → IPython kernels (lifecycle isolation, **not** security sandbox).
- Goals (`/goal`), heartbeats, cron schedules, agent-to-agent messaging.
- Autonomous mode: bounded turns/tokens/time + **user-defined shell quality gates**.
- Explicit caveat: **passed gate verifies only what that gate checks**; limits reached ≠ success.

### Skills

- Agent Skills standard + Python-backed packages (`await skill_name(...)`).
- Progressive disclosure: names in prompt, full `SKILL.md` on demand.
- JSON/RPC modes for headless orchestration.

### What Prime optimizes for

| Strength | Gap for "masterpiece" |
|----------|----------------------|
| Eval episodes, ARC-AGI-style tasks | Formal invariant layer |
| Harness self-improvement | Adversarial spec review before code |
| Shell gates (`npm run check`) | Domain gold sets + statistical thresholds |
| Session-local refine | Cross-session corpus truth (Brain `knowledge`) |
| Velocity on frontier models | Reward-hack via harness self-edit |

Known failure mode (disclosed in community analysis): agent mutates supplemental harness state to satisfy scorable objective through unintended path. Mitigation: **split constitution from harness**.

---

## Brain Forge — rethought architecture

```text
┌─────────────────────────────────────────────────────────────────┐
│ IMMUTABLE CONSTITUTION (repo)                                   │
│  invariants.yaml · run_gates.py · gold evals · AGENTS.md core   │
└───────────────────────────────┬─────────────────────────────────┘
                                │ gates must pass
┌───────────────────────────────▼─────────────────────────────────┐
│ RUNTIME (Prime-inspired)                                        │
│  orchestrator · IPython/kernel or Cursor tasks · rlm-style spawn│
└───────────────────────────────┬─────────────────────────────────┘
                                │
┌───────────────────────────────▼─────────────────────────────────┐
│ MUTABLE HARNESS (session + Brain pattern memories)              │
│  tactics · routing · refined subagent notes — NOT constitution  │
└───────────────────────────────┬─────────────────────────────────┘
                                │
┌───────────────────────────────▼─────────────────────────────────┐
│ TRUTH LAYER (deterministic, no LLM self-certify)                │
│  pytest · teeth · quality_gate · parity · canary · certificate  │
└─────────────────────────────────────────────────────────────────┘
                                │
┌───────────────────────────────▼─────────────────────────────────┐
│ CORPUS (Brain MCP)                                              │
│  knowledge · project_context · decisions · verification closure   │
└─────────────────────────────────────────────────────────────────┘
```

### Orchestration phases (fixed order)

| Phase | Actor | Output | Gate |
|-------|-------|--------|------|
| 0 | Human | Locked `invariants.yaml` | Sign-off |
| 1 | Architect | Spec pack | — |
| 2 | Critic | Counterexamples / revised spec | No open unaccepted risks |
| 3 | Implementer ∥ Test author | Code + tests from INV-* only | — |
| 4 | `run_gates.py` | Exit code + JSON artifact | All green |
| 5 | Red team | Findings queue | No open P0/P1 |
| 6 | Refine (optional) | Brain `pattern` tactics | Cannot touch constitution |
| 7 | Human | Masterpiece Certificate | Ship |

### Role-fixed subagents

| Role | May | May not |
|------|-----|---------|
| Architect | Spec, invariant candidates, failure modes | Implement |
| Critic | Attack spec, demand invariants | Approve without human |
| Implementer | Minimal diff to spec | Change invariants |
| Test author | Tests from invariant sheet | Read implementation first |
| Red team | Security, data, ops adversarial | Declare done |

Prime `rlm()` mapping (Phase B+): spawn Critic + Test author in parallel; block Implementer until Critic clears.

### What to borrow vs avoid

**Borrow:**

- Persistent programmatic control (IPython or equivalent)
- Subagents as spawn + message, not return values
- Autonomous mode + shell/python gates
- Python-backed executable skills
- Daemon + detach for long jobs (Phase C)
- JSON event stream for harness integration
- Host bridge pattern (MCP for Brain, not secrets in kernel)

**Avoid:**

- Full TypeScript rewrite of Brain stack
- Unbounded `/refine` on all harness state
- Shell-only gates without gold eval
- Session-only memory instead of Brain corpus
- Treating autonomous completion as success

---

## Relationship to existing Brain systems

| Existing | Brain Forge role |
|----------|------------------|
| Verification queue (V-*) | Seed invariants; closure format for certificate |
| `ingest_quality_gate.py` | Gate in `run_gates.py` |
| `test_deploy_parity.py` | Gate in `run_gates.py` |
| `brain/eval/` gold sets | Constitution thresholds |
| Entity graph A/B | Example of eval-before-default |
| Brain MCP | Corpus + tactical memory; host bridge |
| `AGENTS.md` | Constitutional source; append-only |
| Hooks (`session_end`, ingest) | First invariant targets (grounding, entities) |

---

## Phased delivery

See [index](./2026-08-12-brain-forge-harness-index.md) for status tracker.

| Phase | Deliverable | ~Effort |
|-------|-------------|---------|
| A | `brain/constitution/`, `brain/harness/run_gates.py`, certificate template | 1 week |
| B | Skills: critic, canary, teeth, closure; MCP bridge docs | 1 week |
| C | `brain-forge` worker, JSON to `brain/eval/runs/` | 2+ weeks |
| D | Tactic refine → Brain `pattern`; refine audit log | ongoing |

---

## Non-goals (v1)

- Replacing Cursor/Claude Code as primary IDE agent
- Formal proof assistants in the hot path (optional later for closed-form math)
- Generic multi-repo template (Brain-first; generalize after Phase B)
- Auto-editing constitution via `/refine`
- CI that downloads ONNX or runs paid LLM APIs

---

## Updates

### 2026-08-12 — Initial design

- Full context from Cursor session preserved.
- Prime Agent investigated via upstream docs (README, architecture, rlm, long-running, skills, usage, AGENTS.md).
- Decision: Brain-specific sequential phases A→D.

<!-- Append future design revisions here. Do not delete above. -->
