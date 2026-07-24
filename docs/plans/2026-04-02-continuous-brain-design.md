# Continuous Brain — Design Document
**Date:** 2026-04-02  
**Status:** Approved

---

## Vision

A living, self-updating memory system for Claude and Claude Code that:
- Never loses context between sessions
- Continuously learns from every exchange in real-time
- Can be queried semantically ("what did I decide about X?", "how did I solve Y?")
- Grows smarter over time through periodic reflection and consolidation

This is not a one-time import. It is a neural-network-inspired persistent brain that ingests the past (Cursor SQL history) and continuously records the present (every Claude Code session).

---

## Architecture

```
┌─────────────────────────────────────────────┐
│           Claude / Claude Code               │
│         (queries & writes in real-time)      │
└────────────────────┬────────────────────────┘
                     │ MCP (stdio)
┌────────────────────▼────────────────────────┐
│              Brain MCP Server               │
│   search() · save() · reflect() · context() │
│              brain/mcp/server.py            │
└──────┬─────────────┬──────────────┬─────────┘
       │             │              │
┌──────▼──────┐ ┌────▼─────┐ ┌─────▼──────────┐
│  ChromaDB   │ │ Obsidian │ │ Claude Memory  │
│ (vectors)   │ │  Notes   │ │   Files        │
│ brain/db/   │ │ AI vault │ │ .claude/memory │
└─────────────┘ └──────────┘ └────────────────┘
```

### Layers

| Layer | Technology | Purpose |
|-------|-----------|---------|
| Vector store | ChromaDB (local, persistent) | Semantic search core |
| Embeddings | sentence-transformers `all-mpnet-base-v2` | Convert text → vectors |
| Summarization | Claude API (claude-haiku-4-5) | Compress conversations into dense knowledge |
| Query synthesis | Claude API (claude-sonnet-4-6) | Answer questions from retrieved context |
| Human-readable | Obsidian markdown notes | Browse/edit memories visually |
| Session context | Claude memory files | Quick context injection at session start |

---

## Data Model

### ChromaDB Collections

**`memories` collection** — atomic knowledge units
```json
{
  "document": "Solved CORS issue in Bella by adding proxy middleware in Express...",
  "embedding": [0.023, -0.412, ...],
  "metadata": {
    "type": "solution|decision|pattern|conversation|project_context|user_preference|error_lesson",
    "project": "bella",
    "tags": ["cors", "express", "proxy"],
    "timestamp": "2026-04-02T14:30:00Z",
    "source": "cursor_history|claude_code_session",
    "session_id": "uuid",
    "importance": 0.85
  }
}
```

**`sessions` collection** — session-level summaries
```json
{
  "document": "Session working on Bella voice interface. Added ElevenLabs TTS...",
  "metadata": {
    "date": "2026-01-15",
    "project": "bella",
    "topics": ["tts", "elevenlabs", "voice"],
    "num_exchanges": 47,
    "source": "cursor_history"
  }
}
```

### Memory Types

| Type | Description |
|------|-------------|
| `solution` | How a specific problem was solved |
| `decision` | Architecture/design choices and why |
| `pattern` | Reusable code patterns discovered |
| `conversation` | Raw exchange summary |
| `project_context` | What a project is, its stack, goals |
| `user_preference` | How the user likes things done |
| `error_lesson` | Mistakes made and lessons learned |

---

## MCP Server Tools

| Tool | Signature | Description |
|------|-----------|-------------|
| `search_brain` | `(query: str, n: int=10, type: str=None, project: str=None)` | Semantic search across all memories |
| `save_memory` | `(content: str, type: str, tags: list, project: str=None)` | Save + embed a new memory |
| `get_context` | `(topic: str, project: str=None, n: int=5)` | Top N most relevant memories for current context |
| `reflect` | `()` | Consolidate, deduplicate, identify patterns, update importance scores |
| `get_stats` | `()` | Memory count by type/project, last reflection time, brain health |

---

## Claude Code Integration (Hooks)

Three hooks configured in `~/.claude/settings.json`:

### SessionStart Hook
**Trigger:** Every new Claude Code session  
**Action:** Calls `get_context()` with current working directory as topic  
**Effect:** Injects top 5 relevant memories into session context automatically

### PostToolUse Hook  
**Trigger:** After every Edit, Write, Bash, Agent tool call  
**Action:** Calls `save_memory()` with a summary of what was done and why  
**Types saved:** `solution`, `decision`, `pattern` depending on content  
**Effect:** Real-time continuous learning — nothing is forgotten

### Stop Hook (session end)
**Trigger:** Session ends  
**Action:** Calls `reflect()` — consolidates session memories, prunes duplicates, finds patterns  
**Effect:** Brain becomes smarter after every session, not just bigger

---

## Bootstrap Pipeline (One-Time)

### Phase 1: SQL Discovery & Extraction
1. Import `recovered.sql` into a temporary SQLite database
2. Query `ItemTable` to discover all chat/composer related keys
3. Extract JSON values for conversation sessions
4. Parse bubbles (user/assistant message pairs)
5. Output: `bootstrap/raw_conversations.jsonl`

### Phase 2: Claude Summarization
1. Batch conversations (max 50k tokens each batch)
2. Claude haiku summarizes each conversation session into structured knowledge:
   - Summary, key decisions, solutions, code patterns, topics, project detected
3. Checkpoint every 100 conversations (resume on failure)
4. Output: `bootstrap/summaries.jsonl`

### Phase 3: Embedding & Ingestion
1. Load `all-mpnet-base-v2` sentence-transformers model
2. Embed all summaries in batches of 128
3. Upsert into ChromaDB `memories` and `sessions` collections
4. Output: ChromaDB at `brain/db/`

### Phase 4: Derived Outputs
1. Write Obsidian markdown notes per project to `/Users/macm1air/Documents/AI/`
2. Write Claude memory files to `~/.claude/projects/.../memory/`

### Checkpointing
The pipeline writes progress to `bootstrap/checkpoint.json` after each batch.  
Re-running the script skips already-processed conversations. Safe to interrupt.

---

## Continuous Learning Flow

```
[User exchange in Claude Code]
         │
         ▼
PostToolUse hook fires
         │
         ▼
Brain MCP save_memory() called
         │
         ├─→ Claude haiku summarizes the exchange
         │
         ├─→ sentence-transformers embeds the summary
         │
         ├─→ ChromaDB upsert (with dedup check)
         │
         └─→ If memories % 20 == 0: trigger reflect()
                     │
                     ▼
              Claude sonnet consolidates:
              - Merges near-duplicate memories
              - Extracts cross-session patterns
              - Updates importance scores
              - Syncs to Obsidian + Claude memory files
```

---

## Project Structure

```
/Users/macm1air/Documents/AI/brain/
├── requirements.txt           # All Python deps
├── config.py                  # Paths, model names, API settings
├── db/                        # ChromaDB persistent storage
├── bootstrap/
│   ├── 01_parse_sql.py        # Extract conversations from SQL dump
│   ├── 02_summarize.py        # Claude summarization pipeline
│   ├── 03_embed_ingest.py     # Embed + load into ChromaDB
│   ├── 04_sync_outputs.py     # Write Obsidian notes + Claude memory
│   └── checkpoint.json        # Resume state
├── mcp/
│   ├── server.py              # MCP server entry point
│   └── tools/
│       ├── search.py
│       ├── save.py
│       ├── context.py
│       ├── reflect.py
│       └── stats.py
├── hooks/
│   ├── session_start.py       # SessionStart hook script
│   ├── post_tool_use.py       # PostToolUse hook script
│   └── session_end.py         # Stop hook script
└── sync/
    ├── obsidian.py            # Obsidian note writer
    └── claude_memory.py       # Claude memory file writer
```

---

## Dependencies

```
chromadb>=0.5.0
sentence-transformers>=3.0.0
anthropic>=0.40.0
mcp>=1.0.0
sqlite3 (stdlib)
tqdm>=4.0.0       # Progress bars for bootstrap
```

---

## Success Criteria

1. All Cursor chat history ingested, searchable by semantic query
2. `search_brain("how did I solve X")` returns accurate results in <500ms
3. Every Claude Code exchange auto-saved without manual intervention
4. Session start automatically surfaces relevant past context
5. After reflection, near-duplicate memories are merged
6. Obsidian vault has readable notes per project
7. Brain grows continuously — zero context loss going forward


<!-- brain-linker -->
## Related
- [[brain-graph/conversation/User]]
- [[brain-graph/conversation/User i want to verify what kind of strong features would thi]]
- [[brain-graph/solution/Edited Usersmacm1airDocumentsAIbrainrustsrcbrain.rs Ok(Self ]]
- [[brain-graph/conversation/Claude Code session AI Ended 2026-04-08T181413.129421+0000 C]]
- [[brain-graph/conversation/Claude Code session AI Ended 2026-04-09T050638.779691+0000 C]]
<!-- /brain-linker -->
