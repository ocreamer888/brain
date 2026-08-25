# Brain Forge — Refine Policy (Phase D)

**Date:** 2026-08-13  
**Rule:** Tactics may evolve. Constitution may not — except by human PR / explicit owner OK.

Continual Harness analog: [arXiv 2605.09998](https://arxiv.org/abs/2605.09998). Brain Forge **narrows** the writable set so refine cannot reward-hack gates.

---

## Writable (tactics)

| Target | How | Tags / notes |
|--------|-----|----------------|
| Operating lessons | Brain MCP `save_memory_tool` | `memory_type=pattern`, tags `harness_refine,forge_tactic` |
| Canary / teeth checklists | Append to skill **Tactics** section only | PR preferred; audit required |
| Job-wrapper tips | Brain `pattern` | e.g. “run parity before hook edits” |
| Audit log | `brain/harness/refine_audit.py append` | Always |

---

## Forbidden (constitution / truth)

Refine **must STOP and escalate to human** if the proposal touches:

| Path / surface | Why |
|----------------|-----|
| `brain/constitution/**` | Immutable laws |
| `brain/constitution/invariants.yaml` | Thresholds & statements |
| Lowering `WARN_THRESHOLD` / `ERROR_THRESHOLD` in quality gate | Weakens truth |
| Disabling teeth / removing `teeth: true` | Theater tests |
| Auto-approving bulk / irreversible without canary | V-07 class failure |
| `AGENTS.md` / `CLAUDE.md` **core non-negotiables** | Base prompt analog |
| Deleting or rewriting Masterpiece Certificate history | Append-only evidence |
| Direct SQLite writes to “fix” gates | Bypass MCP / tools |

Denylist globs (enforced by `refine_audit.py check-path`):

```
brain/constitution/**
**/invariants.yaml
brain/tools/ingest_quality_gate.py
brain/harness/run_gates.py
brain/harness/teeth_probes.py
docs/superpowers/specs/brain-forge/templates/masterpiece-certificate.md
```

(`run_gates.py` / `teeth_probes.py` may gain *features* via normal PR — refine skill must not edit them mid-flight.)

---

## Git hook

Install (repo-local, not `git config`):

```bash
ln -sfn ../../brain/harness/git-hooks/pre-commit .git/hooks/pre-commit
```

The hook runs `refine_audit.py check-staged` on `git diff --cached`. Exit 2 blocks the commit.

Tests: `check-staged --paths` in `brain/tests/test_refine_audit.py`.

---

## Pipeline

```text
Trigger → classify (tactic | constitution)
  → constitution: exit 2, no Brain write, audit blocked event
  → tactic: MCP pattern save (host bridge) → refine_audit append
  → next session: get_context_tool(topic=..., project=brain) loads harness_refine
```

---

## Human review required

- Edits to Critic / Red-team / Refine **core** skill instructions (not Tactics appendix)
- New irreversible-action rules
- Any denylist exception

---

## Reflect vs refine

`reflect_tool` = dedupe corpus. Refine = add tactics. **Never** wire refine to auto-delete memories. Bulk ingest: `BRAIN_REFLECTION_DISABLED=1`.

---

## Updates

### 2026-08-13 — Initial ship

- Phase D policy locked with constitution denylist.

### 2026-08-14 — Pre-commit hook

- Hook script: `brain/harness/git-hooks/pre-commit`
- Command: `refine_audit.py check-staged`
- Installed this checkout: `.git/hooks/pre-commit` → hook script (symlink)
