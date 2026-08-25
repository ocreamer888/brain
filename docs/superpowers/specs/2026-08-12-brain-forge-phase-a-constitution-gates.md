# Brain Forge — Phase A: Constitution + Deterministic Gates

**Date:** 2026-08-12  
**Status:** Closed 2026-08-12  
**Depends on:** [Design doc](./2026-08-12-brain-forge-harness-design.md)  
**Blocks:** Phase B (unblocked)  
**Next phase when closed:** [Phase B — Skills](./2026-08-12-brain-forge-phase-b-skills.md)

---

## Goal

Ship the **immutable constitution** and a **deterministic gate runner** that can block "done" without any LLM in the loop. No daemon, no new dependencies — repo-only, runnable from Cursor or CLI today.

Phase A makes the masterpiece harness **falsifiable**: every claimed invariant maps to a command that exits non-zero when broken.

---

## Deliverables

| Path | Purpose |
|------|---------|
| `brain/constitution/invariants.yaml` | Machine-readable invariant registry |
| `brain/constitution/README.md` | Human rules: who may edit, teeth requirement |
| `brain/harness/run_gates.py` | Orchestrator: pytest, quality gate, parity, optional gold |
| `brain/harness/__init__.py` | Package marker |
| `docs/superpowers/specs/brain-forge/templates/masterpiece-certificate.md` | Ship artifact template |
| `docs/superpowers/specs/brain-forge/templates/invariants.example.yaml` | Annotated example |

---

## `invariants.yaml` schema (v1)

```yaml
version: 1
project: brain  # default scope

invariants:
  - id: INV-SESSION-01
    statement: "Empty or meta-only transcript produces zero LLM memory writes"
    source: "2026-08 session ingest grounding fix"
    tests:
      - "brain/tests/test_transcript_normalize.py"
      - "brain/tests/test_session_ingest_grounding.py"
    teeth: true          # run_gates must verify revert-fails (manual or scripted)
    gold_eval: null
    parity: false
    live_smoke: false

  - id: INV-ENTITY-01
    statement: "Secret-shaped token names never become entities"
    tests:
      - "brain/tests/test_entity_extractor.py"
    teeth: true
    gold_eval: null
    parity: false

  - id: INV-DEPLOY-01
    statement: "Hook-path Python modules match deploy parity sync set"
    tests:
      - "brain/tests/test_deploy_parity.py"
    teeth: false
    parity: true
```

**Editing rules:**

- New invariants: human approves in PR (or explicit owner OK in session).
- Agents may **propose** entries via Architect/Critic; only human merge locks them.
- Never delete rows — set `superseded_by: INV-NEW-ID` if replaced.

---

## `run_gates.py` behavior

### CLI (target)

```bash
.venv/bin/python brain/harness/run_gates.py \
  --invariants brain/constitution/invariants.yaml \
  --phase verify \
  --emit-json brain/eval/runs/gates-$(date +%Y%m%d-%H%M%S).json
```

### Flags

| Flag | Default | Description |
|------|---------|-------------|
| `--invariants PATH` | `brain/constitution/invariants.yaml` | Registry file |
| `--phase` | `verify` | `verify` \| `smoke` \| `full` |
| `--filter INV-*` | all | Subset by id glob |
| `--skip-quality-gate` | false | Skip `ingest_quality_gate.py` (slow / no DB) |
| `--skip-parity` | false | Skip deploy parity |
| `--emit-json PATH` | stdout optional | Machine-readable results |
| `--teeth-check` | false | Run teeth verification (Phase A: document manual procedure; automate in B) |

### Gate sequence (`--phase verify`)

1. Collect test paths from invariants → `pytest` (fail fast).
2. If any invariant has `parity: true` → `pytest brain/tests/test_deploy_parity.py`.
3. If not `--skip-quality-gate` and DB exists → `brain/tools/ingest_quality_gate.py`.
4. Write JSON summary: per-invariant pass/fail, exit code, duration.

### Exit codes (match `ingest_quality_gate.py` spirit)

| Code | Meaning |
|------|---------|
| 0 | All gates passed |
| 1 | Warning threshold (e.g. quality gate warn band) |
| 2 | Hard fail — do not ship |

### Prime Agent autonomous mapping (future)

When Phase C exists, same command becomes:

```bash
brain-forge --autonomous \
  --autonomous-gate ".venv/bin/python brain/harness/run_gates.py --phase verify" \
  ...
```

---

## Seed invariants (from verification queue)

Initial candidates — confirm against live tests before locking:

| ID | Source | Rationale |
|----|--------|-----------|
| INV-SESSION-01 | transcript + session_ingest | Grounding gate |
| INV-ENTITY-01 | V-04 secret-shape filter | Credential entities |
| INV-ENTITY-02 | V-07/V-10 junk filters | Hub/deg1 caps |
| INV-DEPLOY-01 | deploy parity | Two-tree drift |
| INV-HOOK-01 | V-08 background guard | `session_end` import safety |
| INV-INGEST-01 | lazy submodules | No eager torch on `import brain.ingest` |

Add rows as phases close V-items; link `source: "V-04"` in YAML.

---

## Masterpiece Certificate (Phase A template only)

Use [template](./brain-forge/templates/masterpiece-certificate.md). Phase A ships the template; filling it is required before marking any feature "Forge-shipped."

---

## Acceptance criteria (Phase A done)

- [x] `brain/constitution/invariants.yaml` exists with ≥5 seeded invariants
- [x] `run_gates.py` runs under `.venv/bin/python` with exit 0 on current main
- [x] JSON emit writes to `brain/eval/runs/` (mkdir if missing)
- [x] Certificate template committed
- [x] [Index](./2026-08-12-brain-forge-harness-index.md) phase tracker updated to **Closed**
- [x] Closure block added below with evidence (test count, sample JSON path)
- [x] `docs/TOOLS.md` lists `run_gates.py` (one line)

---

## Tasks (execution checklist)

1. Create `brain/constitution/` + README + example YAML in templates.
2. Implement `run_gates.py` — subprocess pytest, optional quality gate / parity.
3. Seed invariants from table above; run full suite; fix any mismatch in YAML paths.
4. Document teeth procedure in constitution README (automate in Phase B).
5. Add minimal test `brain/tests/test_run_gates.py` — smoke that runner exits 0.
6. Update index + this doc closure section.

**Ask owner before:** changing invariant statements that affect product behavior; running quality gate against production DB during peak hook traffic.

---

## Closure log

<!-- Append when Phase A ships. Do not delete tasks above. -->

| Field | Value |
|-------|-------|
| Closed | 2026-08-12 |
| Evidence | `run_gates.py --phase verify` exit 0; pytest paths for 6 invariants; parity ran; quality_gate exit 0 (~0.5s); `brain/tests/test_run_gates.py` 2 passed; JSON `brain/eval/runs/gates-phase-a-verify-full.json` (gitignored) |
| Commits | Uncommitted until owner requests commit |
| Baseline | 6 active invariants (INV-SESSION-01, INV-ENTITY-01/02, INV-DEPLOY-01, INV-HOOK-01, INV-INGEST-01); pytest duration ~2.5s |

---

## Updates

### 2026-08-12 — Phase spec created

- Scope locked: repo-only, no daemon.
- Seed invariants mapped from verification queue.

### 2026-08-12 — Phase A executed and closed

- Created `brain/constitution/{README.md,invariants.yaml}`.
- Created `brain/harness/{__init__.py,run_gates.py}` and `brain/tests/test_run_gates.py`.
- Templates already at `docs/superpowers/specs/brain-forge/templates/`.
- Verified: smoke + verify (+ quality gate) exit 0.
- Teeth automation deferred to Phase B (manual procedure in constitution README).
- Index + TOOLS.md updated; Phase B unblocked.
