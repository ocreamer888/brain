# Backfill Automation Runbook

This runbook documents the automated bulk backfill flow that starts after a preview-ready signal.

**Claude Code sessions** are ingested continuously from the Stop hook (`session_end.py` → background `07_ingest_claude_code.py --file …`). The orchestrator’s `ingest_claude_code` stage is for **scheduled catch-up / bulk** runs (same script, full folder scan). See `docs/BRAIN.md` § Claude Code Sessions.

## What was implemented

- State contract: `brain/tools/backfill_state.py`
- State schema: `brain/schemas/backfill_state_v1.json`
- Orchestrator: `brain/tools/backfill_orchestrator.py`
- Chain entrypoint: `brain/tools/brain_chain.sh backfill`

The orchestrator uses:

- Preview gate (`preview.ready` + `preview.batch_id`)
- Lock file to prevent concurrent runs
- Stage checkpoints by `batch_id`
- Optional dry-run and stage forcing

## State and lock files

- Default state: `.cursor/hooks/state/backfill-state.json`
- Default lock: `.cursor/hooks/state/backfill.lock`

## Stage order

1. `ingest_claude_code`
2. `ingest_perplexity`
3. `ingest_cursor_history`
4. `export_to_jsonl`
5. `migrate_rust` (skippable)
6. `verify`

## Exit codes

- `0`: success or no-op (preview not ready)
- `1`: stage failure
- `2`: lock conflict

## Commands

```bash
# 1) Arm a batch after preview is approved
python3 brain/tools/backfill_orchestrator.py mark-preview-ready --batch-id <batch-id> --input <path>

# 2) Safe validation run (no writes to ingest/migration targets)
python3 brain/tools/backfill_orchestrator.py --dry-run --no-llm --skip-migrate

# 3) Run pipeline (recommended default: no-llm)
python3 brain/tools/backfill_orchestrator.py --no-llm

# 4) Retry a failed stage explicitly
python3 brain/tools/backfill_orchestrator.py --force-stage migrate_rust

# 5) Run through chain helper
bash brain/tools/brain_chain.sh backfill
```

## Scheduler wiring

### launchd (macOS, hourly example)

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
 "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.ai.backfill-orchestrator</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/python3</string>
    <string>/ABS/PATH/TO/AI/brain/tools/backfill_orchestrator.py</string>
    <string>--no-llm</string>
  </array>
  <key>WorkingDirectory</key><string>/ABS/PATH/TO/AI</string>
  <key>StartInterval</key><integer>3600</integer>
</dict>
</plist>
```

### cron (hourly example)

```cron
0 * * * * cd /ABS/PATH/TO/AI && /usr/bin/python3 brain/tools/backfill_orchestrator.py --no-llm >> /tmp/backfill.log 2>&1
```

## Verification executed

The following checks were run and passed in this repository:

- `python3 -m pytest brain/tests -q`
- `cargo test --manifest-path brain/rust/Cargo.toml -q`
- `python3 brain/tools/backfill_orchestrator.py mark-preview-ready ...`
- `python3 brain/tools/backfill_orchestrator.py --dry-run --no-llm --skip-migrate ...`
- `bash brain/tools/brain_chain.sh digest`
- `bash brain/tools/brain_chain.sh export 1`

## Notes

- `feedback_digest.py` and `export_feedback.py` are resilient when `feedback_events` does not exist; they exit cleanly with informational messages.
- Keep `--no-llm` as default for scheduled runs unless cost budget is explicit.
- Do not run migration against production paths without explicit `--db` and `--index` values.


<!-- brain-linker -->
## Related
- [[brain-graph/conversation/User]]
- [[brain-graph/conversation/User Run Claude Code session ingest pipeline]]
- [[brain-graph/pattern/Successfully committed `07_ingest_claude_code.py` to the rep]]
- [[brain-graph/solution/Wrote Usersmacm1airDocumentsAIbrainteststest_ingest_session_]]
- [[brain-graph/solution/Wrote Usersmacm1airDocumentsAIbraintoolsingest_session_chunk]]
- obsidian://open?vault=AI&file=brain%2Fbootstrap%2FPENDING_TASKS
<!-- /brain-linker -->
