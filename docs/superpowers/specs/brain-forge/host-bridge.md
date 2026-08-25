# Brain Forge — MCP Host Bridge

**Date:** 2026-08-12  
**Phase:** B  
**Rule:** Python helpers and skills **must not** hold API keys or write SQLite directly for durable memory. Cursor (or another host) executes Brain MCP; the agent only requests tools.

---

## Pattern

```text
Agent (Cursor session)
  → follows skill (critic / canary / teeth / closure)
  → CallMcpTool on user-brain / brain
  → Host runs MCP → brain_api :8787
  → Result returns to agent
```

Helpers under `brain/harness/` may:

- Read `brain.db` **read-only** (`file:...?mode=ro`) for canary / local gates
- Run pytest / `run_gates.py` / `teeth_check.py`

Helpers must **not**:

- Embed `BRAIN_API_KEY` or OpenRouter keys in skill code
- `INSERT`/`UPDATE`/`DELETE` on production memories from skill scripts
- Call `reflect` / destructive backfills without owner OK + canary

---

## MCP tool map

| Need | MCP tool | Notes |
|------|----------|-------|
| Save tactic refine (Phase D) | `save_memory_tool` | `memory_type=pattern`, tags include `harness_refine` |
| Save phase/feature closure | `save_memory_tool` | `memory_type=decision`, tags `brain_forge,closure` |
| Load project context | `get_context_tool` | Session start; `project=brain` |
| Semantic recall | `search_brain` | Not for "latest" — use index/timeline for recency |
| Metadata / latest | `search_index` → `timeline_tool` | Recency-aware |
| Full bodies | `get_observations_tool` | After you have ids |
| Feedback | `record_feedback` | accepted / edited / rejected |
| Stats | `get_stats_tool` | Health check |

Vault two-hit rule: after `search_brain`, if a hit shows `vault/...`, **read the file** before citing numbers; if top two distances within ~0.02, read both.

---

## Invoking Forge roles from Cursor

| Role | How |
|------|-----|
| Critic | Read `.agents/skills/brain-forge-critic/SKILL.md`; or Task agent with that prompt |
| Canary | Follow canary skill → run `canary_sample.py` |
| Teeth | Follow teeth skill → run `teeth_check.py --auto-probe` |
| Closure | Follow closure skill → fill certificate → `save_memory_tool` |

Adding a new Forge role: create `.agents/skills/brain-forge-<name>/SKILL.md` with Agent Skills frontmatter (`name`, `description`); keep helpers in `brain/harness/`; document in Phase B Updates (append-only).

---

## Anti-patterns

| Bad | Why |
|-----|-----|
| Skill Python posts to `/save` with hardcoded key | Secrets leak; bypasses MCP audit trail |
| Agent declares "masterpiece" without gate JSON | Self-certify |
| Canary skipped "because query looks fine" | V-07 class failure |
| `git stash` for teeth on shared worktree | Destroys other agents' work |
| Refine that edits `brain/constitution/` | Constitution is human-locked |

---

## Updates

### 2026-08-12 — Initial

- Written for Phase B host-bridge acceptance criterion.
