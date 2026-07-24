# Claude Code Session Capture & Ingest

This directory contains the pipeline for capturing and ingesting Claude Code sessions into the brain.

## How It Works

### 1. Session Export (Automatic via Hook)
When a Claude Code session ends, the `brain/hooks/session_end.py` hook:
- Receives conversation context from Claude Code
- Exports the full session transcript to `sessions_export/{timestamp}.json`
- Triggers reflection on session memories

### 2. Ingest Pipeline (Manual or Scheduled)
Run the ingest script to process accumulated session exports:

```bash
# With LLM summarization (default, requires OpenRouter API)
OPENROUTER_API_KEY="sk-or-..." python3 brain/bootstrap/07_ingest_claude_code.py

# Without summarization (faster, less rich)
python3 brain/bootstrap/07_ingest_claude_code.py --no-llm
```

### What It Does
1. **Scan** — Finds new session JSON files in `sessions_export/`
2. **Extract** — Validates and extracts memory records
3. **Summarize** — (Optional) Uses OpenRouter to create rich summaries
4. **Embed** — Batch-embeds all sessions with sentence-transformers
5. **Upsert** — Saves to Rust brain store (SQLite) via batch `/save-batch` API
6. **Checkpoint** — Saves progress; re-runs skip already-processed sessions

**Memory title format:** Conversations are stored as `"Session YYYY-MM-DD — {project}"` (e.g. `"Session 2026-05-21 — AI"`). The title is used both for display and k-fold retrieval quality. UUID-style titles (`Claude Code — <uuid>`) caused retrieval P@1=0.061 and were fixed on 2026-05-22.

## Session JSON Format

Each exported session looks like:

```json
{
  "session_id": "uuid",
  "project": "AI",
  "cwd": "/Users/macm1air/Documents/AI",
  "started_at": "2026-04-02T14:30:00Z",
  "ended_at": "2026-04-02T15:45:00Z",
  "messages": [
    {
      "role": "user",
      "content": "Add error handling..."
    },
    {
      "role": "assistant",
      "content": "I'll wrap the calls..."
    }
  ],
  "tool_events": [
    {
      "tool": "Edit",
      "file_path": "brain/core/summarizer.py"
    }
  ]
}
```

## Checkpointing

Progress is saved to `checkpoint_claude_code.json`. If the ingest fails:
1. Fix the issue
2. Re-run the script — it skips already-processed sessions
3. New sessions are ingested from where it left off

## Querying Sessions

Once ingested, search the brain:

```python
from brain.core.memory import search
results = search("what did I work on today", n=5)
for r in results:
    if r['metadata'].get('source') == 'claude_code_session':
        print(r['content'])
```

## Testing

```bash
# Run unit tests
python3 -m pytest brain/tests/test_07_ingest_file_arg.py brain/tests/test_ingest_session_chunks.py -v

# Manual smoke test
python3 brain/bootstrap/07_ingest_claude_code.py --no-llm
```


<!-- brain-linker -->
## Related
- [[brain-graph/conversation/User]]
- [[brain-graph/solution/Created `CLAUDE_CODE_SESSIONS.md` to document the pipeline f]]
- [[brain-graph/pattern/Successfully committed two new files (`brainbootstrapclaude_]]
- [[brain-graph/solution/Created `07_ingest_claude_code.py` to automate the ingestion]]
- [[brain-graph/pattern/Successfully committed documentation for Claude Code session]]
<!-- /brain-linker -->
