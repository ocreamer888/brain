# Brain Live Status Check Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Run a reliable live memory-system check that confirms current brain context loading and semantic recall are working, then save a short evidence report.

**Architecture:** This plan validates MCP brain connectivity first, then runs two read operations (`get_context_tool` and `search_brain`) as acceptance tests. Results are normalized into one markdown report so future sessions can quickly verify system health without repeating exploratory commands. Scope stays minimal: no product code changes, only operational verification artifacts.

**Tech Stack:** Cursor MCP (`user-brain`), markdown docs, shell verification commands, git

---

### Task 1: Verify MCP brain tool availability and auth state

**Files:**
- Modify: `docs/plans/2026-04-21-brain-live-status-check.md`
- Test: `docs/plans/2026-04-21-brain-live-status-check.md` (checklist validation)

**Step 1: Write the failing test**

Add this checklist block to the working notes (it should start failing because values are unknown):

```markdown
- [ ] `user-brain` tool descriptors readable
- [ ] `mcp_auth` status confirmed (if present)
- [ ] Required tools identified: `get_context_tool`, `search_brain`
```

**Step 2: Run test to verify it fails**

Run: `rg "^\- \[x\]" docs/plans/2026-04-21-brain-live-status-check.md`
Expected: FAIL (no completed checklist items yet)

**Step 3: Write minimal implementation**

Read MCP descriptors for `user-brain`, then:
- if `mcp_auth` exists, run it once
- confirm `get_context_tool` and `search_brain` input schema

**Step 4: Run test to verify it passes**

Run: `rg "get_context_tool|search_brain|mcp_auth" /Users/macm1air/.cursor/projects/Users-macm1air-Documents-AI/mcps/user-brain/tools/*.json`
Expected: PASS with matching descriptor entries

**Step 5: Commit**

```bash
git add docs/plans/2026-04-21-brain-live-status-check.md
git commit -m "docs: add brain live status check plan"
```

### Task 2: Execute live brain context retrieval check

**Files:**
- Create: `docs/reports/2026-04-21-brain-live-status.md`
- Test: `docs/reports/2026-04-21-brain-live-status.md`

**Step 1: Write the failing test**

Create expected report skeleton:

```markdown
# Brain Live Status Report

## get_context_tool
- status: FAIL
- notes: not run
```

**Step 2: Run test to verify it fails**

Run: `rg "status: PASS" docs/reports/2026-04-21-brain-live-status.md`
Expected: FAIL (PASS line not present yet)

**Step 3: Write minimal implementation**

Call `get_context_tool` on `user-brain` and update report:

```markdown
## get_context_tool
- status: PASS
- notes: context payload returned
```

**Step 4: Run test to verify it passes**

Run: `rg "## get_context_tool|status: PASS" docs/reports/2026-04-21-brain-live-status.md`
Expected: PASS with both lines present

**Step 5: Commit**

```bash
git add docs/reports/2026-04-21-brain-live-status.md
git commit -m "docs: record live brain context check result"
```

### Task 3: Execute semantic recall check and finalize evidence

**Files:**
- Modify: `docs/reports/2026-04-21-brain-live-status.md`
- Test: `docs/reports/2026-04-21-brain-live-status.md`

**Step 1: Write the failing test**

Add expected section with failing placeholder:

```markdown
## search_brain
- query: "recent memory decision"
- status: FAIL
- hits: 0
```

**Step 2: Run test to verify it fails**

Run: `rg "status: PASS" docs/reports/2026-04-21-brain-live-status.md`
Expected: FAIL for `search_brain` section

**Step 3: Write minimal implementation**

Call `search_brain` with a focused query, then update:

```markdown
## search_brain
- query: "recent memory decision"
- status: PASS
- hits: <non-zero>
- top_sources: <vault/... or memory ids>
```

If top two search distances are near-tied (~0.02), read both referenced vault files before recording final interpretation.

**Step 4: Run test to verify it passes**

Run: `rg "## search_brain|status: PASS|hits: [1-9]" docs/reports/2026-04-21-brain-live-status.md`
Expected: PASS with non-zero hits

**Step 5: Commit**

```bash
git add docs/reports/2026-04-21-brain-live-status.md
git commit -m "docs: add semantic recall verification evidence"
```

### Task 4: Return concise user-facing health summary

**Files:**
- Modify: `docs/reports/2026-04-21-brain-live-status.md`
- Test: `docs/reports/2026-04-21-brain-live-status.md`

**Step 1: Write the failing test**

Require explicit summary block:

```markdown
## Final Health Summary
- Overall: FAIL
- Blockers: pending
- Next action: pending
```

**Step 2: Run test to verify it fails**

Run: `rg "Overall: PASS" docs/reports/2026-04-21-brain-live-status.md`
Expected: FAIL before update

**Step 3: Write minimal implementation**

Set final summary using observed evidence:

```markdown
## Final Health Summary
- Overall: PASS
- Blockers: none
- Next action: optional `save_memory_tool` for new session learnings
```

**Step 4: Run test to verify it passes**

Run: `rg "Final Health Summary|Overall: PASS" docs/reports/2026-04-21-brain-live-status.md`
Expected: PASS

**Step 5: Commit**

```bash
git add docs/reports/2026-04-21-brain-live-status.md
git commit -m "docs: finalize brain live health summary"
```

### References

- Required execution skill: `@superpowers:executing-plans`
- Optional parallelization skill for independent checks: `@superpowers:subagent-driven-development`
- Brain memory policy context: `@/Users/macm1air/.cursor/rules/brain-realtime-memory.mdc`
