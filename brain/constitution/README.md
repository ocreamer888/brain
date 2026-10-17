# Brain Constitution

Immutable laws for Brain Forge. Agents may **propose** changes; only the owner **locks** them (explicit OK or PR merge).

See: [Phase A spec](../../docs/superpowers/specs/2026-08-12-brain-forge-phase-a-constitution-gates.md)

## Files

| Path | Role |
|------|------|
| `invariants.yaml` | Machine-readable invariant registry |
| This README | Editing rules + teeth procedure |

## Editing rules

1. **Never delete** an invariant row. Supersede with `superseded_by: INV-NEW-ID`.
2. **Human lock** — new or changed `statement` / thresholds require owner approval.
3. Agents may draft entries via Architect/Critic; merge (or session OK) locks them.
4. Every invariant with `teeth: true` must have a test that fails when the fix is reverted.
5. Constitution is **not** writable by Continual Harness refine (Phase D).

## Teeth procedure (manual — Phase A; automate in Phase B)

For an invariant with `teeth: true`:

1. Confirm baseline:  
   `.venv/bin/python brain/harness/run_gates.py --filter INV-ID --skip-quality-gate`
2. Temporarily revert the production fix (prefer a patch file; do **not** `git stash` on a shared worktree).
3. Run the invariant's test path alone — it **must fail**.
4. Restore the fix — the same test **must pass**.
5. Record evidence in the Masterpiece Certificate (`teeth` checkbox).

A test that passes both before and after the change has no teeth.

## Running gates

```bash
.venv/bin/python brain/harness/run_gates.py \
  --invariants brain/constitution/invariants.yaml \
  --phase verify \
  --emit-json brain/eval/runs/gates-$(date +%Y%m%d-%H%M%S).json
```

Exit codes: `0` pass · `1` warn · `2` hard fail (do not ship).

Skip the DB quality gate when hooks are hammering the API or you only need unit/parity:

```bash
.venv/bin/python brain/harness/run_gates.py --phase verify --skip-quality-gate
```
