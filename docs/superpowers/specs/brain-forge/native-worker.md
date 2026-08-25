# Brain Forge — Native Worker (C2)

**Date:** 2026-08-13  
**Decision:** Phase C uses **C2** — minimal in-repo Python worker + supervisor. Not Prime Agent (C1), not bare launchd-only (C3).

---

## Architecture

```text
supervisor.py  start|status|attach|stop
       │
       ▼
worker.py  (--job spec.json)
       ├── validate job_spec.schema.json
       ├── canary_sample.py (if required / step)
       ├── command steps (argv)
       ├── mid gate + end gate → run_gates.py
       └── brain/eval/runs/<job_id>.jsonl + .state.json + .pid
```

Constitution stays law. Worker never self-certifies without gate exit 0.

---

## Runbook

### Start (detach)

```bash
cd /Users/abundancia888/Documents/Code/brain
.venv/bin/python brain/harness/supervisor.py start path/to/job.json
# or: bash brain/harness/supervisor.sh start path/to/job.json
```

Worker continues if the terminal closes (`start_new_session=True`).

### Status

```bash
.venv/bin/python brain/harness/supervisor.py status <job_id>
```

### Attach (follow transcript)

```bash
.venv/bin/python brain/harness/supervisor.py attach <job_id>
# dump once:
.venv/bin/python brain/harness/supervisor.py attach <job_id> --no-follow
```

Ctrl-C detaches; **job keeps running**.

### Stop

```bash
.venv/bin/python brain/harness/supervisor.py stop <job_id>
```

### Foreground (debug)

```bash
.venv/bin/python brain/harness/supervisor.py start path/to/job.json --foreground
```

### Recover after crash

1. `status <job_id>` — if `alive=false` and `state.status=running`, treat as crashed.
2. Inspect `brain/eval/runs/<job_id>.jsonl` last event.
3. Fix cause; re-`start` with a **new** `job_id` (or clear pid/state after owner OK).
4. Do **not** resume mid-mutation without canary + owner OK if `irreversible=true`.

---

## Job spec

Schema: `brain/harness/job_spec.schema.json`  
Example: `brain/harness/examples/job-phase-c-canary-1k.json`

Rules:

- `irreversible: true` ⇒ `canary_required: true`
- Steps: `canary` | `command` | `gate`
- If no explicit `gate` step, worker inserts a **mid** gate after the first half of steps
- `run_end_gate` default true

---

## What C2 is not

- Not an LLM agent loop (no auto code repair)
- Not Prime Agent daemon / IPython RLM
- Gate failure → job fails (retries only re-run the gate command, `gate_retries` times)

For agent repair loops, document optional C1 bridge later — constitution still wins.

---

## Updates

### 2026-08-13 — Initial (C2 chosen)

- Owner selected C2 over C1/C3.

### 2026-08-14 — Resume, recover, packaged daemon

**Crash / resume (replaces “always new job_id” for crashed workers):**

```bash
.venv/bin/python brain/harness/supervisor.py stop <job_id>      # SIGTERM process group
.venv/bin/python brain/harness/supervisor.py reconcile         # dead pid + status=running → crashed
.venv/bin/python brain/harness/supervisor.py recover <job_id>  # start --resume from state next_step
```

Worker writes `next_step` after each completed step; SIGTERM sets `status=crashed` and kills the current child. Irreversible jobs set `BRAIN_REFLECTION_DISABLED=1` on command steps. Mutating tools must checkpoint (entity backfill: `--checkpoint-every 1` on canary jobs).

**Daemon (inbox poller, not launchd-loaded):**

```bash
.venv/bin/python brain/harness/supervisor.py daemon --once          # tests / one shot
.venv/bin/python brain/harness/supervisor.py daemon --poll 5        # foreground poller
```

Inbox: `brain/eval/jobs/{inbox,running,done,failed}` (override `BRAIN_FORGE_JOBS_ROOT`). Plist template: `docs/deploy/com.brain.forge.plist`. **Do not `launchctl load` without owner OK.**

**Mutating canary job spec:** `brain/harness/examples/job-entity-backfill-canary-25.json` (25 rows, dedicated checkpoint, edgeless SELECT canary). Live E2E through worker on this corpus: pending owner run (see certificate 2026-08-14).
