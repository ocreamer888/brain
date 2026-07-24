# Production Check Evidence

Date: 2026-04-08

## 1) Chroma cutover verification

Command:

```bash
export BRAIN_API_KEY="local-dev-key"
python3 brain/tools/verify_cutover.py
```

Observed result:

- `rust_delta = 1`
- `chroma_delta = 0`
- `"ok": true`

Interpretation:

- New write landed in Rust API-backed store.
- Chroma memory count did not increase for this runtime write.

## 2) SLO/SLI metrics wiring proof

Command:

```bash
python3 brain/tools/export_metrics_prom.py --out brain/tmp/brain.prom
```

Result:

- Prometheus textfile exported at `brain/tmp/brain.prom`.
- Includes: `brain_status_ok`, `brain_total_memories`, `brain_total_sessions`, `brain_spool_queue_size`, `brain_spool_oldest_age_seconds`.

## 3) Incident drill validation proof

Evidence artifact:

- `docs/deploy/incident-drill-evidence.json`

Observed sequence:

- event `api-down-simulated` logged with spool queue present (`queue_size=3`)
- `replay_spool` executed
- queue drained (`queue_size=0`, `oldest_age_sec=0`)
- drill marked completed

Conclusion:

- Queue/replay path works and recovery evidence captured.

## 4) P0/P1 production verification (2026-04-08)

### Supervised launchd agent

```bash
launchctl list | grep brain
# 56635   0   com.brain.api
```

- PID active, exit code 0 (healthy).
- Plist: `~/Library/LaunchAgents/com.brain.api.plist`
- Binary: `brain/rust/target/release/brain_api` (release build, 11MB)
- `KeepAlive=true` — restarts on crash and at login.

### Env vars set in `~/.zshrc`

```
BRAIN_BACKEND=api
BRAIN_API_URL=http://127.0.0.1:8787
BRAIN_API_KEY=local-dev-key
BRAIN_API_AUTH_REQUIRED=true
BRAIN_DB_PATH=.../brain/rust/brain.db
BRAIN_INDEX_PATH=.../brain/rust/brain_index.bin
BRAIN_LLM_PROVIDER=openrouter
```

### backend_mode() verification

```python
from brain.api_client import backend_mode
backend_mode()  # → "api"
```

### Hook write test

```
total_memories before: 1580
total_memories after:  1581
delta: +1  ✓
```

Conclusion: hooks write to Rust. Chroma not involved in hot path. P0 and P1 complete.


<!-- brain-linker -->
## Related
- [[brain-graph/conversation/User]]
- [[brain-graph/pattern/Edited Usersmacm1airDocumentsAIbrainrustsrcbrain.rs ( memori]]
- [[brain-graph/solution/Edited Usersmacm1airDocumentsAIbrainrustsrcbrain.rs pub stru]]
- [[brain-graph/solution/Edited Usersmacm1airDocumentsAIbrainrustsrcbrain.rs Ok(Self ]]
- [[brain-graph/solution/Edited Usersmacm1airDocumentsAIbrainrustsrcbrain.rs fn test_]]
- [brain/bootstrap/PENDING_TASKS](obsidian://open?vault=AI&file=brain%2Fbootstrap%2FPENDING_TASKS)
<!-- /brain-linker -->
