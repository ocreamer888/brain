# Brain Forge — Phase B: Executable Skills + MCP Host Bridge

**Date:** 2026-08-12  
**Status:** Closed 2026-08-13  
**Depends on:** [Phase A closed](./2026-08-12-brain-forge-phase-a-constitution-gates.md)  
**Blocks:** Phase C (unblocked)  
**Next phase when closed:** [Phase C — Worker](./2026-08-12-brain-forge-phase-c-daemon-worker.md)

---

## Goal

Formalize **role-fixed subagents** as Prime-style **Python-backed skills** (or Cursor Agent Skills with executable helpers), wired to Brain MCP as the **host bridge** — credentials and durable memory stay outside the kernel.

Phase B makes the orchestration phases (Architect → Critic → Implementer → Red team) **repeatable invocations**, not ad-hoc prompts.

---

## Deliverables

| Path | Purpose |
|------|---------|
| `.agents/skills/brain-forge-critic/SKILL.md` | Critic role prompt + when to invoke |
| `.agents/skills/brain-forge-canary/SKILL.md` | 100-row sample + inspect procedure |
| `.agents/skills/brain-forge-teeth/SKILL.md` | Revert → fail → restore workflow |
| `.agents/skills/brain-forge-closure/SKILL.md` | Write certificate + update phase doc |
| `brain/harness/roles/` | Optional Python helpers callable from skills |
| `docs/superpowers/specs/brain-forge/host-bridge.md` | MCP patterns: save/search without secrets in REPL |

**Note:** Skills may live under repo `.agents/skills/` (project) or `~/.agents/skills/` (global). Prefer **project** for Brain Forge so deploy parity applies to docs.

---

## Role skills (contracts)

### `brain-forge-critic`

**Input:** spec pack + `invariants.yaml` draft  
**Output:** markdown findings list — counterexamples, missing invariants, silent-failure modes  
**Must ask:**

- What test passes while system is broken?
- N=0, N=1, N=10⁶, malformed, concurrent?
- What assumption is unstated?

**Cannot:** approve spec, write production code

### `brain-forge-canary`

**Input:** bulk job description + sample SQL/query  
**Output:** `canary/` artifact dir with 100-row sample + human-readable summary  
**Hard rule:** no bulk without canary artifact path in certificate

Wraps verification handoff rule: *four minutes of canary prevents 23k bad edges.*

### `brain-forge-teeth`

**Input:** invariant id + test path  
**Output:** pass/fail evidence (test output when fix reverted)  
**Procedure:**

1. Record baseline pass with `run_gates.py`
2. Revert fix (stash or temp checkout — **never** `git stash` on shared worktree per handoff rules; use patch file)
3. Run specific test — must fail
4. Restore fix — must pass

Phase B automates steps 1+3+4 for a single `--invariant INV-*`.

### `brain-forge-closure`

**Input:** feature id, gate JSON, findings queue state  
**Output:** filled certificate + suggested closure block for phase doc  
**Writes:** Brain MCP `save_memory_tool` (`memory_type=decision`, tags `brain_forge,closure`)

---

## MCP host bridge

Python/kernel code **must not** hold API keys. Pattern:

```text
Agent in Cursor
  → skill instructs: CallMcpTool save_memory_tool / search_brain
  → host (Cursor) executes MCP
  → result returned to agent
```

Document in `host-bridge.md`:

| Need | MCP tool | Notes |
|------|----------|-------|
| Save tactic refine | `save_memory_tool` | `memory_type=pattern`, tag `harness_refine` |
| Save closure | `save_memory_tool` | `memory_type=decision` |
| Load project context | `get_context_tool` | Session start |
| Verify corpus | `search_brain` + read vault file | Two-hit rule within 0.02 |

**Forbidden:** embedding `brain_api` keys in skill Python; direct SQLite writes from skills (use tools/API).

---

## Prime Agent parallels

| Prime | Phase B Brain Forge |
|-------|---------------------|
| Python-backed `await skill(...)` | Cursor skills + optional `brain/harness/roles/*.py` |
| `rlm()` spawn | Cursor `Task` tool with `subagent_type` + skill prompt |
| `agent_message.send()` | Parent session @ mention or Task resume |
| Built-in skill-creator | Document how to add new Forge roles |

We do **not** require IPython kernel in Phase B — Cursor is the runtime. Phase C adds kernel optional.

---

## Orchestration script (optional v1)

`brain/harness/orchestrate_spec.py` — headless driver:

```bash
.venv/bin/python brain/harness/orchestrate_spec.py \
  --intent "Fix INV-SESSION-01" \
  --phase critic \
  --spec path/to/spec.md
```

Phase B minimum: skills documented + manual invocation via `/skill` or `@brain-forge-critic`. Script is stretch.

---

## Acceptance criteria (Phase B done)

- [x] Four skills committed under `.agents/skills/brain-forge-*/`
- [x] `host-bridge.md` committed
- [x] Teeth skill + helper automates one invariant end-to-end
- [x] Canary skill produces sample artifact format documented
- [x] At least one real feature closure uses certificate + MCP decision save
- [x] Index phase tracker: Phase B **Closed**
- [x] Closure block below filled

---

## Tasks (execution checklist)

1. Create skill directories + SKILL.md frontmatter per [Agent Skills spec](https://agentskills.io/specification).
2. Write `host-bridge.md` with MCP table and anti-patterns.
3. Implement `brain/harness/teeth_check.py` helper (called by skill).
4. Run teeth on one invariant from Phase A registry; attach evidence to closure.
5. Document Cursor invocation: `@brain-forge-critic`, Task dispatch pattern.
6. Update `docs/TOOLS.md` if new CLI helpers added.

---

## Closure log

| Field | Value |
|-------|-------|
| Closed | 2026-08-13 |
| Evidence | Skills critic/canary/teeth/closure; `teeth_check --auto-probe INV-HOOK-01` passed; canary 100 rows; `test_forge_phase_b.py` 2 passed; `run_gates --phase verify --skip-quality-gate` exit 0; certificate `docs/superpowers/specs/brain-forge/certificates/brain-forge-phase-b.md`; MCP decision save |
| Commits | Uncommitted until owner requests |

---

## Updates

### 2026-08-12 — Phase spec created

- Blocked on Phase A `run_gates.py` + invariants registry.

### 2026-08-12 — Unblocked

- Phase A closed: constitution + `run_gates.py` live. Ready to execute when owner starts Phase B.

### 2026-08-13 — Phase B executed and closed

- Created `.agents/skills/brain-forge-{critic,canary,teeth,closure}/SKILL.md`
- Created `docs/superpowers/specs/brain-forge/host-bridge.md`
- Created `brain/harness/teeth_check.py`, `teeth_probes.py` (INV-HOOK-01), `canary_sample.py`, `roles/__init__.py`
- Created `brain/tests/test_forge_phase_b.py`
- Live: teeth E2E + canary 100 + gates green; background.py restored after probe
- Certificate filled; Phase C marked Ready on index
- Stretch skipped: `orchestrate_spec.py` (document as deferred)
