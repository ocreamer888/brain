---
name: brain-forge-refine
description: Evidence-backed tactical refine for Brain Forge. Propose smallest operating lesson; never touch constitution. Use after repeated gate failures, post-closure lessons, or explicit /refine.
---

# Brain Forge Refine (Phase D)

Tactics evolve. **Constitution does not.**

Policy: `docs/superpowers/specs/brain-forge/refine-policy.md`

## Steps

1. **Classify** before writing anything:

```bash
.venv/bin/python brain/harness/refine_audit.py classify \
  --target pattern \
  --edit-summary "YOUR PROPOSAL"
```

Exit `2` ⇒ constitution-class → **STOP**, escalate to human. Optionally:

```bash
.venv/bin/python brain/harness/refine_audit.py append \
  --trigger "..." \
  --target constitution \
  --edit-summary "attempted: ..." \
  --force-blocked \
  --outcome "blocked"
```

2. **Check paths** if editing files:

```bash
.venv/bin/python brain/harness/refine_audit.py check-path brain/constitution/invariants.yaml
# must exit 2
```

Staged commits: hook runs `check-staged`. Manual:

```bash
.venv/bin/python brain/harness/refine_audit.py check-staged
```

3. **Persist tactic** via **MCP host bridge** (not raw SQLite):

```
save_memory_tool(
  content="<dense tactic>",
  memory_type="pattern",
  project="brain",
  tags="harness_refine,forge_tactic"
)
```

4. **Audit**:

```bash
.venv/bin/python brain/harness/refine_audit.py append \
  --trigger "..." \
  --target pattern \
  --edit-summary "..." \
  --brain-memory-id "<id from MCP>" \
  --outcome "recorded" \
  --rollback "supersede or delete memory id"
```

5. Next sessions: `get_context_tool(topic="harness_refine forge_tactic", project="brain")`.

## May propose

- Run deploy parity before hook-path edits
- Critic checks JSON-quoted memory types in SQL
- Canary checklist additions
- Job-wrapper ordering tips

## Must not propose

- Lower quality-gate thresholds
- Remove / weaken invariants
- Disable teeth
- Skip canary on irreversible jobs
- Edit `brain/constitution/**`

## Tactics

<!-- Append-only operating notes from approved refines (optional). -->

- Prefer `refine_audit.py classify` before every refine.
- Prefer MCP `pattern` + tags `harness_refine,forge_tactic` over rewriting skills mid-job.
