# Brain Forge Harness — Documentation Index

**Created:** 2026-08-12  
**Status:** Active — Phase D **initial ship** 2026-08-13 (A–D complete; D ongoing)  
**Owner decision:** Execute phases sequentially (A → B → C → D). Do not skip ahead without closing the prior phase.

---

## Purpose

This doc series preserves **complete context** for the Brain Forge Harness vision: high-confidence agentic engineering that combines Prime Agent runtime patterns with Brain's verification discipline.

**Doc maintenance rule (append-only):**

- **Never delete** prior sections, phase status history, or changelog entries.
- **Add** new material under dated `## Updates` subsections or new dated spec files.
- When a phase ships, add a **closure block** to that phase doc (evidence, commit refs, baseline numbers) — do not rewrite the original plan.
- If the architecture changes materially, add `2026-08-12-brain-forge-harness-design.md` § Updates rather than replacing the original thesis.

---

## Read order

| # | Document | When to read |
|---|----------|--------------|
| 1 | [Design — vision, Prime Agent analysis, architecture](./2026-08-12-brain-forge-harness-design.md) | First — full context |
| 2 | [Phase A — Constitution + gates](./2026-08-12-brain-forge-phase-a-constitution-gates.md) | Before any harness code |
| 3 | [Phase B — Executable skills + MCP bridge](./2026-08-12-brain-forge-phase-b-skills.md) | After Phase A gates green |
| 4 | [Phase C — Long-running worker + JSON events](./2026-08-12-brain-forge-phase-c-daemon-worker.md) | When detach/reattach jobs needed |
| 5 | [Phase D — Continual harness (tactics only)](./2026-08-12-brain-forge-phase-d-continual-harness.md) | After B stable; highest risk |
| — | [Templates](./brain-forge/templates/) | Certificate, invariants examples |

**Related existing docs (do not duplicate — link only):**

- [Verification queue handoff](./2026-07-29-verification-queue-handoff.md) — teeth tests, canary rule, working agreement
- [Verification findings queue](./2026-07-28-durable-entity-linking-verification-findings.md) — V-01…V-38
- [Knowledge type design](./2026-08-06-knowledge-type-design.md) — corpus truth layer
- [Eval framework design](./2026-05-23-eval-framework-design.md) — gold sets, thresholds
- [TOOLS.md](../../TOOLS.md) — existing tool catalog

**External reference:**

- [Prime Agent (GitHub)](https://github.com/PrimeIntellect-ai/prime-agent) — RLM + Continual Harness reference implementation
- [Continual Harness paper (arXiv 2605.09998)](https://arxiv.org/abs/2605.09998)

---

## Phase tracker

| Phase | Name | Status | Started | Closed | Notes |
|-------|------|--------|---------|--------|-------|
| **A** | Constitution + deterministic gates | **Closed** | 2026-08-12 | 2026-08-12 | 6 invariants; `run_gates.py` exit 0 |
| **B** | Python skills + MCP host bridge | **Closed** | 2026-08-13 | 2026-08-13 | 4 skills; teeth + canary helpers |
| **C** | `brain-forge` worker + JSON stream | **Closed** | 2026-08-13 | 2026-08-13 | **C2** native worker; 1k canary job |
| **D** | Continual harness (tactics → Brain) | **Initial ship** | 2026-08-13 | 2026-08-13 (initial) | Refine policy + audit; constitution blocked |

Update this table when a phase starts or closes. **Do not remove rows.**

---

## Core thesis (immutable)

> **Mutable harness for speed. Immutable constitution for truth.**

| Layer | Mutable | Immutable |
|-------|---------|-----------|
| Tactics, routing, skill usage | Yes (`/refine`-style → Brain `pattern`) | — |
| Subagent role prompts (non-core) | Yes, evidence-backed | Base roles fixed |
| Invariants, gate scripts, gold thresholds | — | Yes — human sign-off |
| `AGENTS.md` / `CLAUDE.md` core rules | Append-only refinements | Core non-negotiables frozen |

---

## Confidence model

| Layer | What it buys |
|-------|--------------|
| **Prime-style RLM runtime** | Operational — compose, parallelize, persist work |
| **Brain constitution** | Logical — invariants hold under tests |
| **Gold eval + canary** | Empirical — behaves on real corpus |
| **Human certificate sign-off** | Accountability — known unknowns explicit |

**"100% confident"** is not achievable globally. It is achievable **per invariant** when: written → tested with teeth → gold/canary where applicable → adversary clear → human signs certificate.

---

## Changelog

### 2026-08-12 — Initial series

- Created index, design doc, phases A–D, templates.
- Source: Cursor session on frontier model confidence, masterpiece harness, Prime Agent deep investigation.
- Decision: sequential phases; Brain-specific (not generic template v1).
- Phase A is next actionable slice.

### 2026-08-12 — Phase A closed

- Shipped `brain/constitution/invariants.yaml` (6 active invariants) + README.
- Shipped `brain/harness/run_gates.py` + `__init__.py` + `brain/tests/test_run_gates.py`.
- Live verify: `--phase verify` exit 0 (pytest + parity + ingest_quality_gate); JSON at `brain/eval/runs/gates-phase-a-verify-full.json` (gitignored under `brain/eval/runs/`).
- Certificate templates already present under `docs/superpowers/specs/brain-forge/templates/`.
- Next: Phase B (skills + MCP host bridge).

### 2026-08-13 — Phase B closed

- Skills: `.agents/skills/brain-forge-{critic,canary,teeth,closure}/SKILL.md`
- Helpers: `brain/harness/teeth_check.py`, `teeth_probes.py`, `canary_sample.py`
- Host bridge: `docs/superpowers/specs/brain-forge/host-bridge.md`
- Evidence: teeth INV-HOOK-01 auto-probe passed; canary 100 rows; `test_forge_phase_b.py` 2 passed; gates exit 0
- Certificate: `docs/superpowers/specs/brain-forge/certificates/brain-forge-phase-b.md`
- Next: Phase C when a long detach job is needed (or owner starts early)

### 2026-08-13 — Phase C closed (C2)

- Approach: native `worker.py` + `supervisor.py` (not Prime C1).
- Runbook: `docs/superpowers/specs/brain-forge/native-worker.md`
- Acceptance: job `phase-c-canary-1k` — 1000-row canary, mid+end gates, detach start/status success.
- Tests: `brain/tests/test_harness_worker.py` 4 passed.
- Next: Phase D (continual harness tactics-only).

### 2026-08-13 — Phase D initial ship

- Policy: `docs/superpowers/specs/brain-forge/refine-policy.md`
- Helper: `brain/harness/refine_audit.py` + skill `brain-forge-refine`
- Tactic: parity-before-hooks + canary-before-bulk → pattern `2cd6e2f3-17bb-4797-a5f2-cf01ac1908cc`
- Constitution block drill audited; `get_context_tool` loads harness_refine
- A–D series complete; D remains ongoing for future tactics

### 2026-08-14 — Gap close (teeth / hook / daemon / crash-resume)

- Auto-probes for **all 6** `teeth: true` invariants: `teeth_check.py --all` passed (INV-HOOK-01, INV-SESSION-01, INV-ENTITY-01, INV-ENTITY-02, INV-DEPLOY-01, INV-INGEST-01).
- Refine denylist is a **git pre-commit hook** (`brain/harness/git-hooks/pre-commit` → `refine_audit.py check-staged`), not skill-only.
- Packaged daemon: `supervisor.py daemon --poll` + plist template `docs/deploy/com.brain.forge.plist` (**not** launchd-loaded).
- Worker `--resume` / supervisor `recover` / `reconcile`; pytest crash drill passed (`test_worker_crash_then_recover`).
- Mutating 25-row entity-backfill job spec ready: `brain/harness/examples/job-entity-backfill-canary-25.json` (edgeless canary SQL; dedicated checkpoint; `--checkpoint-every 1`). Live worker E2E + mid-write crash on `:8787` **not executed this session** (mutating-write approval). Preflight: 1437 edgeless durable; canary 100 rows at `brain/eval/runs/canary-forge-entity-backfill-canary-25-preflight/`.
- Certificate: `docs/superpowers/specs/brain-forge/certificates/forge-gap-close-2026-08-14.md`

### 2026-08-24 — Production-ready packaging

- Confirmation dry-run post-`0834003` clean on path/host; CSS/UUID/`styles.*` filter added + live-tree sync.
- Forge package (`brain/harness/`, `brain/constitution/`, skills, docs) committed so gates/teeth/worker are cloneable.
- Full corpus backfill still owner-triggered; `com.brain.forge` not launchd-loaded.
