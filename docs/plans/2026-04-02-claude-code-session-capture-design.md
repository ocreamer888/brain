# Claude Code Session Capture & Ingest Pipeline — Design Document
**Date:** 2026-04-02  
**Status:** Approved

---

## Vision

Extend the continuous brain system to automatically capture and preserve every Claude Code session in real-time. Sessions are exported, summarized, embedded, and ingested into ChromaDB so the brain learns continuously from every coding exchange, not just tool actions.

---

## Architecture

### Hook-Based Real-Time Capture

**Extended PostToolUse hook:**
- Continues capturing tool summaries (Edit, Write, Bash, Agent)
- NEW: Also captures meaningful message exchanges (user→assistant)
- Summarizes exchanges via OpenRouter
- Embeds and saves to ChromaDB immediately for real-time learning

**Extended session_end hook:**
- Triggers reflection on session memories (existing behavior)
- NEW: Exports full conversation transcript to JSON file
- Creates stable session UUID for deduplication

### Session Export Format

Each exported session is saved to `brain/bootstrap/sessions_export/{session_id}.json`:

```json
{
  "session_id": "uuid",
  "project": "AI",
  "cwd": "/Users/macm1air/Documents/AI",
  "started_at": "2026-04-02T14:30:45Z",
  "ended_at": "2026-04-02T15:45:22Z",
  "messages": [
    {
      "role": "user",
      "content": "Add error handling to the API routes",
      "timestamp": "2026-04-02T14:31:00Z"
    },
    {
      "role": "assistant",
      "content": "I'll add try-catch blocks...",
      "timestamp": "2026-04-02T14:31:15Z"
    }
  ],
  "tool_events": [
    {
      "tool": "Edit",
      "file_path": "brain/api.py",
      "timestamp": "2026-04-02T14:31:30Z"
    }
  ]
}
```

---

## Ingest Pipeline (07_ingest_claude_code.py)

**Step 1: Collection**
- Scan `brain/bootstrap/sessions_export/` for new JSON files
- Load checkpoint to skip already-processed sessions

**Step 2: Summarization**
- For each session, OpenRouter summarizes into structured knowledge:
  - Summary: 2-3 sentence overview of session work
  - Topics: Key technologies/concepts touched
  - Decisions: Architectural or design choices made
  - Solutions: Problems solved and how
  - Type: "conversation" or "project_context"

**Step 3: Embedding & Upsert**
- Batch-embed all summaries (sentence-transformers `all-mpnet-base-v2`)
- Upsert into ChromaDB with:
  - Memory type: "conversation"
  - Project: extracted from session metadata
  - Tags: topics extracted from summary
  - Source: "claude_code_session"
  - Session ID for deduplication and grouping

**Step 4: Cleanup & Checkpoint**
- Save checkpoint (processed session IDs)
- Optionally archive or delete exported JSON files

---

## Continuous Learning Flow

```
[Claude Code Session Starts]
         │
         ├─ PostToolUse hook (tool + exchanges)
         │  ├─ Summarize exchange
         │  ├─ Embed
         │  └─ Save to ChromaDB
         │
[Session Ends]
         │
         ├─ session_end hook
         │  ├─ Export full transcript JSON
         │  └─ Trigger reflection (existing)
         │
[Operator runs 07_ingest_claude_code.py]
         │
         ├─ Summarize session transcript
         ├─ Batch-embed
         ├─ Upsert to ChromaDB
         └─ Update checkpoint
```

---

## Error Handling & Safety

**Non-fatal hook failures:**
- Both hooks catch all exceptions and log to stderr only
- Claude Code session continues normally even if brain export fails
- User sees warning in console, no disruption

**Idempotent ingestion:**
- Session IDs are stable UUIDs (same every time a session re-exports)
- Upserts are idempotent, so re-running ingest is safe

**Transcript truncation:**
- Sessions >500 messages are truncated to most recent 100 before summarization
- Keeps token usage and API costs reasonable

**Directory creation:**
- `brain/bootstrap/sessions_export/` created automatically if missing

---

## Testing Strategy

**Unit tests:**
- Hook logic in isolation (mock Claude Code context)
- JSON export format validation
- Checkpoint save/load

**Integration tests:**
- Create fake session JSON
- Run full ingest pipeline
- Verify summary, embedding, upsert in ChromaDB
- Verify checkpoint allows resumable runs

**Success Criteria:**
1. PostToolUse captures message exchanges without crashes
2. session_end exports full transcript to JSON with all required fields
3. `07_ingest_claude_code.py` successfully summarizes, embeds, upserts
4. Checkpoint allows resumable runs (re-run skips already-processed sessions)
5. Brain can be queried for session insights ("what did I work on today?")
6. Zero lost sessions — nothing exported is dropped

---

## Files Modified/Created

**Modified:**
- `brain/hooks/post_tool_use.py` — Add message exchange capture
- `brain/hooks/session_end.py` — Add transcript export

**Created:**
- `brain/bootstrap/07_ingest_claude_code.py` — Main ingest script
- `brain/bootstrap/claude_code_extractors.py` — Session extraction helpers (optional, for cleanliness)
- `brain/bootstrap/tests/test_claude_code_ingest.py` — Integration tests

**Generated (runtime):**
- `brain/bootstrap/sessions_export/` — Exported session JSONs
- `brain/bootstrap/checkpoint_claude_code.json` — Ingest checkpoint

---

## Dependencies

- `anthropic` or `openai` (for OpenRouter calls via summarizer)
- `sentence-transformers` (already required)
- `chromadb` (already required)
- stdlib: `json`, `uuid`, `datetime`, `pathlib`

No new external dependencies required.


<!-- brain-linker -->
## Related
- [[brain-graph/conversation/User]]
- [[brain-graph/solution/Created `07_ingest_claude_code.py` to automate the ingestion]]
- [[brain-graph/pattern/Successfully committed documentation for Claude Code session]]
- [[brain-graph/pattern/Successfully committed two new files (`brainbootstrapclaude_]]
- [[brain-graph/solution/Created `CLAUDE_CODE_SESSIONS.md` to document the pipeline f]]
<!-- /brain-linker -->
