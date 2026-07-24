# Deploying and supervising `brain_api`

The Rust binary is built from `brain/rust` (`cargo build --release --bin brain_api`). This folder holds **sample** unit definitions; adjust paths and secrets for your host.

## Prerequisites

- Release binary at `brain/rust/target/release/brain_api` (or install to a fixed path like `/usr/local/bin/brain_api`).
- Writable directories for SQLite and the vector index.
- Environment file **outside the repo** (e.g. `/etc/brain/brain-api.env`) containing at least:

```bash
BRAIN_DB_PATH=/var/lib/brain/brain.db
BRAIN_INDEX_PATH=/var/lib/brain/brain_index.bin
BRAIN_ONNX_PATH=/opt/brain/models/all-mpnet-base-v2-onnx
BRAIN_API_BIND=127.0.0.1:8787
BRAIN_API_KEY=replace-with-secret
BRAIN_API_AUTH_REQUIRED=true
```

Optional: rate limits and LLM keys as in `docs/PHASE4_API.md`.

## systemd (Linux)

Copy and edit `brain-api.service`, then:

```bash
sudo install -m 644 brain-api.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now brain-api
journalctl -u brain-api -f
```

Logs go to the journal by default (`StandardOutput=journal`).

## launchd (macOS) — canonical dev setup

**Deployed plist:** `~/Library/LaunchAgents/com.brain.api.plist` (active since 2026-04-08, updated 2026-04-21 for v0.2.0 web viewer).

`brain_api` runs under a **launchd user agent at login** — no manual start needed. `KeepAlive=true` respawns on crash; `RunAtLoad=true` starts at login.

**Deployed paths:**

- Binary: `brain/rust/target/release/brain_api`
- DB: `brain/rust/brain.db`
- Index: `brain/rust/brain_index.bin`
- Logs: `~/Library/Logs/brain/brain_api.log` / `brain_api.err`
- Bind: `127.0.0.1:8787`

**Auth note (2026-05-25):** `BRAIN_API_AUTH_REQUIRED=true` is safe with the viewer. The Rust server injects `window.__BRAIN_API_KEY__` into `index.html` at serve time; the React SPA reads it and sends `x-api-key` on every request. The plist can and should run with auth enabled.

---

## UI Dashboard — Build and Deploy

The React dashboard (`brain/rust/ui/`) is embedded **at compile time** into the `brain_api` binary via `rust_embed`. There is no runtime file serving — the binary carries the static assets.

### How the embedding works

```
brain/rust/ui/   ← React source (Vite + Tailwind)
      ↓  npm run build
brain/rust/static/  ← compiled HTML/JS/CSS  (outDir configured in vite.config.js)
      ↓  cargo build --release
brain_api binary  ← static/ embedded via rust_embed #[folder = "static/"]
```

`brain_api` injects `window.__BRAIN_API_KEY__` into `index.html` at serve time so the SPA can authenticate.

### One-command deploy

```bash
bash brain/rust/ui/deploy.sh
```

What it does, in order:
1. `npm run build` — compiles React → `brain/rust/static/`
2. `cargo build --release --bin brain_api` — recompiles binary with new assets embedded
3. `launchctl kickstart -k gui/<uid>/com.brain.api` — hot-swaps the supervised process
4. Verifies `/health` returns 200

Dashboard is live at **`http://127.0.0.1:8787/`** (root redirects to `/static/index.html`).

### Development workflow

Use Vite dev server when actively working on the UI — it has hot module reload:

```bash
cd brain/rust/ui && npm run dev
# → http://localhost:5173/
```

API calls are proxied to `localhost:8787` automatically (configured in `vite.config.js`), so `brain_api` must be running. When done with UI changes, run `deploy.sh` to publish them into the supervised binary.

### After a system restart

`brain_api` (with the last-deployed UI embedded) starts automatically via launchd. No manual action needed.

### Control commands (modern `bootstrap`/`bootout` — `load`/`unload` is legacy)

```bash
uid=$(id -u)

# Status
launchctl list | grep com.brain.api

# Restart (picks up a newly built release binary)
launchctl kickstart -k gui/$uid/com.brain.api

# Stop + disable this login session
launchctl bootout gui/$uid/com.brain.api

# Re-enable + start
launchctl enable   gui/$uid/com.brain.api
launchctl bootstrap gui/$uid ~/Library/LaunchAgents/com.brain.api.plist

# Tail logs
tail -f ~/Library/Logs/brain/brain_api.err
```

### After rebuilding the release binary

```bash
cd brain/rust && cargo build --release --bin brain_api
launchctl kickstart -k gui/$(id -u)/com.brain.api
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8787/health   # expect 200
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8787/static/index.html  # expect 200
```

### Port 8787 conflicts

If `cargo run` or manual `./brain_api` panics with `AddrInUse`, **launchd is already supervising it**. `pkill -f brain_api` alone **will not work** — `KeepAlive=true` respawns within seconds. Either:

1. Use the supervised instance (it already serves your hooks / MCP / viewer).
2. Stop launchd first, run manual, re-enable when done:
   ```bash
   launchctl bootout gui/$(id -u)/com.brain.api
   ./brain/rust/target/debug/brain_api
   # done →
   launchctl enable    gui/$(id -u)/com.brain.api
   launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.brain.api.plist
   ```
3. Run manual on a different port: `BRAIN_API_BIND=127.0.0.1:8790 ./brain/rust/target/debug/brain_api`

Template for new machines: `com.example.brain-api.plist` in this folder.

## Log rotation

- **systemd**: use journald retention (`journald.conf`) or ship logs to your aggregator.
- **launchd**: redirect `StandardOutPath` / `StandardErrorPath` to files under `~/Library/Logs/` and rotate with `newsyslog` or an external agent.

## Client processes (hooks, MCP)

The same host (or CI) must export **`BRAIN_BACKEND=api`**, **`BRAIN_API_URL`**, and **`BRAIN_API_KEY`** so MCP and hooks hit the supervised API. See `docs/BRAIN_ENV_MATRIX.md`.

**Deployed (macOS, 2026-04-08, auth flipped 2026-04-21) — added to `~/.zshrc`:**

```bash
export BRAIN_BACKEND=api
export BRAIN_API_URL=http://127.0.0.1:8787
export BRAIN_API_KEY=local-dev-key
export BRAIN_API_AUTH_REQUIRED=false   # v0.2.0: disabled so web viewer works on loopback
export BRAIN_DB_PATH=/Users/macm1air/Documents/AI/brain/rust/brain.db
export BRAIN_INDEX_PATH=/Users/macm1air/Documents/AI/brain/rust/brain_index.bin
export BRAIN_LLM_PROVIDER=openrouter
```

Verify with:

```bash
source ~/.zshrc
python3 -c "import sys; sys.path.insert(0,'.'); from brain.api_client import backend_mode; print(backend_mode())"
# expected: api
```

## Realtime SLO / SLI

Recommended production targets:

- **Freshness SLO**: `save -> searchable` under `2s` p95.
- **Write availability SLO**: `/save` success (or durable queued) >= `99.9%`.
- **Data loss objective**: `0` dropped memory events in hooks/MCP paths.

Track these SLIs:

- `/save` latency (`p50/p95/p99`) and error rate.
- Spool health from `brain/hooks/spool.py` metrics:
  - `queue_size`
  - `oldest_age_sec`
- Replay outcomes:
  - replayed count
  - DLQ moved count

Alert examples:

- freshness p95 > 2s for 5m
- queue_size > 100 for 10m
- oldest_age_sec > 300
- DLQ increment > 0
- sample rule file: `docs/deploy/alerts-example.yaml`

### Metrics probe command (JSON)

```bash
python3 brain/tools/brain_observability_probe.py
```

Example output includes API stats plus spool lag:

```json
{"status":"ok","api":{"total_memories":123},"spool":{"queue_size":0,"oldest_age_sec":0}}
```

### Prometheus textfile export

```bash
python3 brain/tools/export_metrics_prom.py --out brain/tmp/brain.prom
```

This writes gauges you can scrape (directly or via node-exporter textfile collector):

- `brain_status_ok`
- `brain_total_memories`
- `brain_total_sessions`
- `brain_spool_queue_size`
- `brain_spool_oldest_age_seconds`
- `brain_spool_queue_by_source{source="..."}`

## Incident Runbook (minimum)

### 1) API down / degraded

1. Verify process health (`systemctl status` or `launchctl list`).
2. Confirm `/health` and `/stats` behavior.
3. Keep hooks running; failed writes must enqueue to spool.
4. Recover API, then replay queued writes:
   - `python3 brain/tools/replay_spool.py`
5. Confirm queue drained (`queue_size == 0`) and no new DLQ entries.
6. Log evidence:
   - `python3 brain/tools/incident_drill.py log --message "api-down-start"`
   - `python3 brain/tools/incident_drill.py replay`
   - `python3 brain/tools/incident_drill.py complete`

### 2) Queue lag growing

1. Check API latency/errors first.
2. Inspect spool metrics (`queue_size`, `oldest_age_sec`).
3. Temporarily increase replay frequency (cron/agent call) if needed.
4. If persistent, scale API or lower ingest pressure until SLO recovers.

### 3) Restore from backup

1. Stop API writer traffic.
2. Restore `brain.db` and `brain_index.bin` from latest valid backup pair.
3. Restart API.
4. Replay spool to recover in-flight writes after backup point.
5. Run retrieval smoke test (`save -> search`) before reopening traffic.

## Chroma Cutover Guardrail

For production lock-in to Rust-only runtime, set:

```bash
BRAIN_ENFORCE_API_ONLY=1
```

With this guardrail, any accidental `BRAIN_BACKEND=python` is forced to `api` at runtime.

### Cutover verification command

```bash
export BRAIN_API_KEY="local-dev-key"
python3 brain/tools/verify_cutover.py
```

Expected success condition:
- `rust_delta >= 1`
- `chroma_delta == 0`
- output field `"ok": true`

## Spool maintenance (pruning)

Prune old spool + DLQ records:

```bash
python3 brain/tools/spool_maintenance.py --max-age-days 14
```

Use as scheduled hygiene job after replay job.


<!-- brain-linker -->
## Related
- [[brain-graph/conversation/User]]
- [[brain-graph/solution/Edited Usersmacm1airDocumentsAIbrainrustsrcbrain.rs Configur]]
- [[brain-graph/solution/Edited Usersmacm1airDocumentsAIbrainrustsrcbrain.rs pub stru]]
- [[brain-graph/solution/Edited Usersmacm1airDocumentsAIbrainrustsrcbinbrain_api.rs s]]
- [[brain-graph/solution/Edited Usersmacm1airDocumentsAIbrainrustsrcbrain.rs fn test_]]
<!-- /brain-linker -->
