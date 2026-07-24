# Automate Bulk Backfill After Preview Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Automatically trigger bulk backfill ingest pipelines once a preview/ready step is complete, with idempotent checkpoints, locking, and verification.

**Architecture:** Add a Python orchestrator that watches/consumes a small state file (ready flag + batch metadata), runs ingest stages in order, records stage results, and exits safely on errors. Keep existing ingest scripts as-is; orchestration wraps them with retry/lock/checkpoint semantics.

**Tech Stack:** Python 3, existing bootstrap scripts (`03/06/07`), existing migration/export tools, JSON state files under `.cursor/hooks/state/`, pytest.

---

### Task 1: Define orchestration contract and state schema

**Files:**
- Create: `brain/tools/backfill_state.py`
- Create: `brain/schemas/backfill_state_v1.json`
- Modify: `docs/AUTOMATION_STATUS.md`
- Test: `brain/tests/test_backfill_state.py`

**Step 1: Write the failing test (state defaults + transitions)**

```python
def test_new_state_defaults():
    state = load_or_init_state(tmp_path / "state.json")
    assert state["version"] == 1
    assert state["preview"]["ready"] is False
    assert state["run"]["status"] == "idle"
```

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest brain/tests/test_backfill_state.py::test_new_state_defaults -v`  
Expected: FAIL (module/file does not exist)

**Step 3: Write minimal implementation**

Implement helpers in `backfill_state.py`:
- `load_or_init_state(path)`
- `mark_preview_ready(path, batch_id, inputs)`
- `mark_stage(path, stage, status, detail)`
- `mark_run_complete(path, success)`

**Step 4: Add JSON schema**

Create `brain/schemas/backfill_state_v1.json` with required keys:
- `version`
- `preview` (`ready`, `batch_id`, `inputs`)
- `run` (`status`, `started_at`, `ended_at`, `last_error`)
- `stages` map

**Step 5: Run test to verify it passes**

Run: `python3 -m pytest brain/tests/test_backfill_state.py -v`  
Expected: PASS

**Step 6: Commit**

```bash
git add brain/tools/backfill_state.py brain/schemas/backfill_state_v1.json brain/tests/test_backfill_state.py docs/AUTOMATION_STATUS.md
git commit -m "feat: add backfill state contract and schema"
```

---

### Task 2: Build backfill orchestrator with lock + stage pipeline

**Files:**
- Create: `brain/tools/backfill_orchestrator.py`
- Modify: `brain/tools/brain_chain.sh`
- Test: `brain/tests/test_backfill_orchestrator.py`

**Step 1: Write failing test for lock behavior**

```python
def test_orchestrator_refuses_when_lock_exists(tmp_path):
    lock = tmp_path / "backfill.lock"
    lock.write_text("busy")
    rc = run_orchestrator(["--lock", str(lock)], cwd=tmp_path)
    assert rc == 2
```

**Step 2: Run failing test**

Run: `python3 -m pytest brain/tests/test_backfill_orchestrator.py::test_orchestrator_refuses_when_lock_exists -v`  
Expected: FAIL

**Step 3: Implement orchestrator skeleton**

In `backfill_orchestrator.py` add:
- CLI args (`--state`, `--lock`, `--dry-run`, `--no-llm`, `--skip-migrate`)
- lock acquire/release
- state load
- early exit when `preview.ready` is false

**Step 4: Implement stage execution**

Stages (in order):
1. `ingest_claude_code`: `python3 brain/bootstrap/07_ingest_claude_code.py [--no-llm]`
2. `ingest_perplexity`: `python3 brain/bootstrap/06_ingest_perplexity.py [--no-llm]`
3. `ingest_cursor_history`: `python3 brain/bootstrap/03_ingest.py`
4. `export_to_jsonl`: `python3 brain/tools/export_to_jsonl.py <artifact>`
5. `migrate_rust`: `cargo run --bin brain_migrate -- <artifact> --db <...> --index <...>` (optional by flag)
6. `verify`: API `/stats` or count deltas

Track each stage status in state file.

**Step 5: Add idempotent stage skip logic**

If stage status already `success` for current `batch_id`, skip stage unless `--force-stage`.

**Step 6: Run tests**

Run: `python3 -m pytest brain/tests/test_backfill_orchestrator.py -v`  
Expected: PASS

**Step 7: Commit**

```bash
git add brain/tools/backfill_orchestrator.py brain/tools/brain_chain.sh brain/tests/test_backfill_orchestrator.py
git commit -m "feat: add checkpointed backfill orchestrator with lock and stages"
```

---

### Task 3: Add preview completion trigger contract

**Files:**
- Modify: `brain/tools/backfill_orchestrator.py`
- Modify: `docs/AUTOMATION_STATUS.md`
- Modify: `docs/BRAIN.md`
- Test: `brain/tests/test_backfill_orchestrator.py`

**Step 1: Write failing test for preview-ready gate**

```python
def test_no_run_when_preview_not_ready(tmp_path):
    write_state(tmp_path / "state.json", preview_ready=False)
    rc = run_orchestrator(["--state", str(tmp_path / "state.json")], cwd=repo_root)
    assert rc == 0
    assert "preview not ready" in read_logs(tmp_path)
```

**Step 2: Run failing test**

Run: `python3 -m pytest brain/tests/test_backfill_orchestrator.py::test_no_run_when_preview_not_ready -v`  
Expected: FAIL

**Step 3: Implement preview gate**

Require:
- `preview.ready == true`
- `preview.batch_id` present
- optional input fingerprints list present

If missing, exit cleanly without side effects.

**Step 4: Add trigger helper**

Add command mode:
- `python3 brain/tools/backfill_orchestrator.py mark-preview-ready --batch-id <id> --input <path>`

This updates state and arms the next scheduled run.

**Step 5: Run tests**

Run: `python3 -m pytest brain/tests/test_backfill_orchestrator.py -v`  
Expected: PASS

**Step 6: Commit**

```bash
git add brain/tools/backfill_orchestrator.py brain/tests/test_backfill_orchestrator.py docs/AUTOMATION_STATUS.md docs/BRAIN.md
git commit -m "feat: add preview-ready trigger contract for backfill automation"
```

---

### Task 4: Add scheduler-ready entrypoint and logs

**Files:**
- Modify: `brain/tools/backfill_orchestrator.py`
- Create: `docs/BACKFILL_AUTOMATION.md`
- Modify: `docs/PHASE7.md`
- Test: `brain/tests/test_backfill_orchestrator.py`

**Step 1: Write failing test for structured run log**

```python
def test_writes_run_log(tmp_path):
    rc = run_orchestrator(["--state", str(state), "--log-dir", str(tmp_path / "logs")], cwd=repo_root)
    assert rc in (0, 1)
    assert any((tmp_path / "logs").glob("backfill-*.log"))
```

**Step 2: Run failing test**

Run: `python3 -m pytest brain/tests/test_backfill_orchestrator.py::test_writes_run_log -v`  
Expected: FAIL

**Step 3: Implement logging + exit codes**

Add:
- one log file per run under `docs/feedback-digests/` or configurable `--log-dir`
- clear exit codes (`0` success/no-op, `1` stage failure, `2` lock conflict)

**Step 4: Document scheduler wiring**

In `docs/BACKFILL_AUTOMATION.md` include:
- launchd example (daily/hourly)
- cron example
- required env vars
- manual replay command for failed batch

**Step 5: Run tests**

Run: `python3 -m pytest brain/tests/test_backfill_orchestrator.py -v`  
Expected: PASS

**Step 6: Commit**

```bash
git add brain/tools/backfill_orchestrator.py docs/BACKFILL_AUTOMATION.md docs/PHASE7.md brain/tests/test_backfill_orchestrator.py
git commit -m "docs+feat: scheduler-ready backfill automation with run logs"
```

---

### Task 5: End-to-end validation in dry-run and live-safe mode

**Files:**
- Modify: `brain/tests/test_backfill_orchestrator.py`
- Modify: `docs/AUTOMATION_STATUS.md`

**Step 1: Add failing integration-style test (dry run)**

```python
def test_stage_order_dry_run(tmp_path):
    seed_preview_ready_state(tmp_path, batch_id="b1")
    result = run_orchestrator(["--dry-run", "--state", str(tmp_path / "state.json")], cwd=repo_root)
    assert result == 0
    assert read_stage_sequence(tmp_path) == [
        "ingest_claude_code",
        "ingest_perplexity",
        "ingest_cursor_history",
        "export_to_jsonl",
        "migrate_rust",
        "verify",
    ]
```

**Step 2: Run failing test**

Run: `python3 -m pytest brain/tests/test_backfill_orchestrator.py::test_stage_order_dry_run -v`  
Expected: FAIL

**Step 3: Implement/adjust ordering logic**

Ensure deterministic stage order and persisted stage results.

**Step 4: Run full relevant test set**

Run:
- `python3 -m pytest brain/tests/test_backfill_state.py -v`
- `python3 -m pytest brain/tests/test_backfill_orchestrator.py -v`

Expected: PASS

**Step 5: Commit**

```bash
git add brain/tests/test_backfill_state.py brain/tests/test_backfill_orchestrator.py docs/AUTOMATION_STATUS.md
git commit -m "test: validate backfill orchestration order and checkpoints"
```

---

### Task 6: Final operational handoff

**Files:**
- Modify: `docs/AUTOMATION_STATUS.md`
- Modify: `docs/BRAIN.md`
- Modify: `docs/architecture/system-diagrams.md`

**Step 1: Document “manual -> automated” delta**

Update docs to state bulk backfill is automated once:
- preview-ready marker is set
- scheduler is enabled

**Step 2: Add runbook snippets**

Commands:
- Arm batch: `python3 brain/tools/backfill_orchestrator.py mark-preview-ready --batch-id ...`
- Run once: `python3 brain/tools/backfill_orchestrator.py`
- Inspect state: `cat .cursor/hooks/state/backfill-state.json`
- Retry failed stage: `python3 brain/tools/backfill_orchestrator.py --force-stage migrate_rust`

**Step 3: Final verification commands**

Run:
- `python3 -m pytest brain/tests/test_backfill_state.py brain/tests/test_backfill_orchestrator.py -v`
- `python3 brain/tools/backfill_orchestrator.py --dry-run`

Expected:
- Tests pass
- Dry run prints stage sequence and writes no destructive data

**Step 4: Commit**

```bash
git add docs/AUTOMATION_STATUS.md docs/BRAIN.md docs/architecture/system-diagrams.md
git commit -m "docs: publish end-to-end automated backfill runbook"
```

---

## Risks and guardrails

- Keep `--no-llm` default for scheduled runs unless token/cost budget is explicit.
- Do not run migrate against production DB without explicit `--db`/`--index`.
- Use lock file + checkpoint to avoid concurrent data races.
- Treat exported JSONL as sensitive if content can include private text.

## Out of scope (YAGNI)

- Full workflow engine (Airflow/Prefect) right now.
- Parallel stage execution.
- Automatic rollback of migrated data.
<!-- brain-linker -->
## Related
- [[brain-graph/conversation/User nice. now we need to automate flows, making system chai]]
- [[brain-graph/conversation/User]]
- [[brain-graph/solution/Added a new integration test stub `test_full_ingest_pipeline]]
- [[brain-graph/pattern/The daily pipeline has been automated, running at 6am, and i]]
- [[brain-graph/pattern/Successfully committed `07_ingest_claude_code.py` to the rep]]
<!-- /brain-linker -->
