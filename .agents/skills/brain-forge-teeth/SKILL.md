---
name: brain-forge-teeth
description: Prove an invariant has teeth — baseline pass, temporary break fails tests, restore passes. Use after fixing a Forge invariant or when closing a certificate with teeth true.
---

# Brain Forge Teeth

A test that passes before **and** after the change is worthless. Prove revert fails.

## Procedure (automated helper)

```bash
# Full auto-probe for registered invariants (safe try/finally restore):
.venv/bin/python brain/harness/teeth_check.py --invariant INV-HOOK-01 --auto-probe

# All registered probes:
.venv/bin/python brain/harness/teeth_check.py --all

# Baseline only:
.venv/bin/python brain/harness/teeth_check.py --invariant INV-HOOK-01
```

What `--auto-probe` does:

1. Baseline: invariant tests must **pass**
2. Apply a registered temporary break (patch file under try/finally — **not** `git stash`)
3. Same tests must **fail**
4. Restore file; same tests must **pass**
5. Write evidence JSON under `brain/eval/runs/teeth-INV-*.json`

## Manual break (unregistered invariants)

1. Baseline: `teeth_check.py --invariant INV-ID`
2. Save a reverse patch; edit production code to break the invariant
3. `teeth_check.py --invariant INV-ID --expect-fail`
4. Restore from patch
5. `teeth_check.py --invariant INV-ID` again

**Never** `git stash` on a shared worktree (other agents' work).

## Output

Attach teeth JSON path on the Masterpiece Certificate.

## Hard limits

- Do not leave a broken file on disk if the process is interrupted — helper uses try/finally
- Do not weaken tests to make teeth "pass"
- `--auto-probe` only for invariants listed in `brain/harness/teeth_probes.py`

## Related

- `brain/constitution/README.md` teeth procedure
- `brain/harness/teeth_check.py`
