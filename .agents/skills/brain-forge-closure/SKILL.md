---
name: brain-forge-closure
description: Fill a Masterpiece Certificate and record Forge closure in Brain MCP. Use when a Forge phase or feature is ready to ship after gates, teeth, and canary (if needed).
---

# Brain Forge Closure

## Input

- Feature / job id
- Gate JSON path (`brain/eval/runs/gates-*.json`)
- Optional: teeth JSON, canary dir, critic findings
- Invariant ids claimed

## Procedure

1. Copy template:

```bash
cp docs/superpowers/specs/brain-forge/templates/masterpiece-certificate.md \
   docs/superpowers/specs/brain-forge/certificates/<feature-id>.md
```

2. Fill checklist from real artifact paths (no invented paths).
3. Append closure block to the phase doc (`## Closure log` + `## Updates`).
4. Update [harness index](../../docs/superpowers/specs/2026-08-12-brain-forge-harness-index.md) phase tracker.
5. **Host bridge** — save via MCP (do not write SQLite from scripts):

```
save_memory_tool(
  content="<dense closure summary>",
  memory_type="decision",
  project="brain",
  tags="brain_forge,closure,<feature-id>"
)
```

## Hard limits

- Do not mark Closed if `run_gates.py` exit ≠ 0
- Do not skip Known unknowns (write "none" only if truly none)
- Human still signs invariants on the certificate; agent fills evidence only

## Related

- Host bridge: `docs/superpowers/specs/brain-forge/host-bridge.md`
- Template: `docs/superpowers/specs/brain-forge/templates/masterpiece-certificate.md`
