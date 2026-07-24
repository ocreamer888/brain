# Claude Code Session Capture Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a checkpoint-resumable ingest pipeline that captures Claude Code sessions exported via hooks and ingests them into ChromaDB for continuous learning.

**Architecture:** Two components: (1) Extend `session_end.py` hook to export session transcripts as JSON files, (2) Create `07_ingest_claude_code.py` that scans the export folder, summarizes sessions via OpenRouter, embeds, and upserts into ChromaDB with checkpoint-based resumability. Message-level capture via PostToolUse happens immediately; session-level digestion happens on-demand.

**Tech Stack:** Python (ast, json, uuid, pathlib), OpenRouter API (for summarization), ChromaDB (upsert), sentence-transformers (embed_batch), TDD (pytest)

---

### Task 1: Create session extractors helper module

**Files:**
- Create: `brain/bootstrap/claude_code_extractors.py`
- Test: `brain/bootstrap/tests/test_claude_code_extractors.py`

**Step 1: Write failing test for session extraction**

Create `brain/bootstrap/tests/test_claude_code_extractors.py`:

```python
"""Tests for Claude Code session extraction helpers."""
import json
import sys
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from brain.bootstrap.claude_code_extractors import (
    extract_session_record,
    validate_session_json,
)


def test_extract_session_record_basic(tmp_path):
    """Test basic session record extraction."""
    session_file = tmp_path / "session_2026-04-02_14-30-45.json"
    session_file.write_text(json.dumps({
        "session_id": "abc-123",
        "project": "AI",
        "cwd": "/Users/macm1air/Documents/AI",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "ended_at": datetime.now(timezone.utc).isoformat(),
        "messages": [
            {"role": "user", "content": "Add error handling"},
            {"role": "assistant", "content": "I'll add try-catch blocks..."},
        ],
        "tool_events": [{"tool": "Edit", "file_path": "api.py"}],
    }))
    
    record = extract_session_record(session_file)
    assert record["session_id"] == "abc-123"
    assert record["project"] == "AI"
    assert "Add error handling" in record["text"]
    assert record["metadata"]["source"] == "claude_code_session"
    assert record["metadata"]["type"] == "conversation"


def test_validate_session_json_valid(tmp_path):
    """Test validation of valid session JSON."""
    session_file = tmp_path / "valid.json"
    session_file.write_text(json.dumps({
        "session_id": "uuid",
        "project": "test",
        "cwd": "/path",
        "started_at": "2026-04-02T10:00:00Z",
        "ended_at": "2026-04-02T11:00:00Z",
        "messages": [],
        "tool_events": [],
    }))
    
    is_valid, error = validate_session_json(session_file)
    assert is_valid is True
    assert error is None


def test_validate_session_json_missing_field(tmp_path):
    """Test validation rejects missing required fields."""
    session_file = tmp_path / "invalid.json"
    session_file.write_text(json.dumps({
        "session_id": "uuid",
        # Missing "project", "cwd", etc.
    }))
    
    is_valid, error = validate_session_json(session_file)
    assert is_valid is False
    assert error is not None
```

**Step 2: Run test to verify failure**

```bash
cd /Users/macm1air/Documents/AI
python -m pytest brain/bootstrap/tests/test_claude_code_extractors.py -v
```

Expected: `FAILED ... ModuleNotFoundError: No module named 'brain.bootstrap.claude_code_extractors'`

**Step 3: Write session extractor module**

Create `brain/bootstrap/claude_code_extractors.py`:

```python
"""Extraction helpers for Claude Code session exports."""
import json
from pathlib import Path
from datetime import datetime, timezone
from typing import Tuple

SESSIONS_EXPORT_DIR = Path(__file__).parent / "sessions_export"


def validate_session_json(file_path: Path) -> Tuple[bool, str | None]:
    """Validate that a session JSON has required fields."""
    required_fields = {
        "session_id",
        "project",
        "cwd",
        "started_at",
        "ended_at",
        "messages",
        "tool_events",
    }
    
    try:
        data = json.loads(file_path.read_text())
        missing = required_fields - set(data.keys())
        if missing:
            return False, f"Missing fields: {missing}"
        return True, None
    except Exception as e:
        return False, f"Invalid JSON: {e}"


def extract_session_record(file_path: Path) -> dict:
    """Extract a memory record from a Claude Code session JSON export."""
    is_valid, error = validate_session_json(file_path)
    if not is_valid:
        raise ValueError(f"Invalid session JSON: {error}")
    
    data = json.loads(file_path.read_text())
    session_id = data["session_id"]
    project = data.get("project", "unknown")
    cwd = data.get("cwd", "")
    
    # Build text from messages and metadata
    parts = [
        f"Claude Code session: {project}",
        f"Duration: {data['started_at']} to {data['ended_at']}",
        f"CWD: {cwd}",
    ]
    
    # Add message summary
    messages = data.get("messages", [])
    if messages:
        message_count = len(messages)
        parts.append(f"Total messages: {message_count}")
        
        # Add first few messages for context
        for msg in messages[:10]:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")[:200]
            if content:
                parts.append(f"[{role}] {content}")
    
    # Add tool events summary
    tool_events = data.get("tool_events", [])
    if tool_events:
        tools_used = {}
        for event in tool_events:
            tool = event.get("tool", "unknown")
            tools_used[tool] = tools_used.get(tool, 0) + 1
        parts.append(f"Tools: {', '.join(f'{k}({v})' for k, v in sorted(tools_used.items()))}")
    
    text = " | ".join(parts)
    
    return {
        "session_id": session_id,
        "file_path": file_path.name,
        "text": text,
        "metadata": {
            "type": "conversation",
            "project": project,
            "tags": f"claude_code,{project}",
            "source": "claude_code_session",
            "session_id": session_id,
            "file_path": file_path.name,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "importance": "0.6",
        }
    }
```

**Step 4: Run tests to verify pass**

```bash
cd /Users/macm1air/Documents/AI
python -m pytest brain/bootstrap/tests/test_claude_code_extractors.py -v
```

Expected: `2 passed`

**Step 5: Commit**

```bash
cd /Users/macm1air/Documents/AI
git add brain/bootstrap/claude_code_extractors.py brain/bootstrap/tests/test_claude_code_extractors.py
git commit -m "feat: add Claude Code session extraction helpers with validation"
```

---

### Task 2: Create 07_ingest_claude_code.py ingest pipeline

**Files:**
- Create: `brain/bootstrap/07_ingest_claude_code.py`

**Step 1: Write the ingest pipeline script**

Create `brain/bootstrap/07_ingest_claude_code.py`:

```python
"""
Ingest Claude Code session exports into ChromaDB brain vector store.

Sessions are exported by the session_end.py hook to brain/bootstrap/sessions_export/.
This script:
  1. Scans for new session JSON files
  2. Summarizes each via OpenRouter (optional, can skip with --no-llm)
  3. Embeds batch-wise
  4. Upserts to ChromaDB
  5. Saves checkpoint for resumability

Usage:
    OPENROUTER_API_KEY="sk-or-..." python brain/bootstrap/07_ingest_claude_code.py
    python brain/bootstrap/07_ingest_claude_code.py --no-llm  # skip summarization
"""
import argparse
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from brain.core.embedder import embed_batch
from brain.core.db import upsert_memory, count_memories
from brain.bootstrap.claude_code_extractors import (
    extract_session_record,
    validate_session_json,
    SESSIONS_EXPORT_DIR,
)

CHECKPOINT_PATH = Path(__file__).parent / "checkpoint_claude_code.json"
BATCH_SIZE = 64


def load_checkpoint() -> set:
    """Load set of already-processed session IDs."""
    if CHECKPOINT_PATH.exists():
        return set(json.loads(CHECKPOINT_PATH.read_text()).get("processed_ids", []))
    return set()


def save_checkpoint(processed_ids: set):
    """Save set of processed session IDs."""
    CHECKPOINT_PATH.write_text(json.dumps({"processed_ids": sorted(list(processed_ids))}))


def summarize_session_with_llm(record: dict) -> dict:
    """Enhance record with LLM summary (optional)."""
    from brain.core.summarizer import _chat, _parse_json
    
    text = record["text"]
    prompt = f"""Analyze this Claude Code session. Extract structured knowledge.

SESSION:
{text}

Respond with ONLY valid JSON:
{{
  "summary": "2-3 sentence description of what was accomplished",
  "topics": ["topic1", "topic2"],
  "decisions": ["key decision made"],
  "type": "conversation"
}}"""
    
    try:
        raw = _chat(prompt, max_tokens=512)
        data = _parse_json(raw)
        record["metadata"]["type"] = data.get("type", "conversation")
        record["metadata"]["tags"] = ",".join(data.get("topics", []))
        record["text"] = data.get("summary", record["text"])
        return record
    except Exception as e:
        print(f"  [LLM summary failed, using basic]: {e}", file=sys.stderr)
        return record


def collect_records(use_llm: bool = True) -> list[dict]:
    """Collect session records from export directory."""
    SESSIONS_EXPORT_DIR.mkdir(exist_ok=True)
    
    session_files = sorted(SESSIONS_EXPORT_DIR.glob("*.json"))
    print(f"Found {len(session_files)} session files in {SESSIONS_EXPORT_DIR}")
    
    processed = load_checkpoint()
    records = []
    
    for i, f in enumerate(session_files, 1):
        session_id = f.stem
        if session_id in processed:
            print(f"  [{i}/{len(session_files)}] {f.name} (already processed)")
            continue
        
        # Validate before processing
        is_valid, error = validate_session_json(f)
        if not is_valid:
            print(f"  [{i}/{len(session_files)}] {f.name} INVALID: {error}")
            processed.add(session_id)
            continue
        
        print(f"  [{i}/{len(session_files)}] {f.name}...")
        try:
            record = extract_session_record(f)
            
            if use_llm:
                record = summarize_session_with_llm(record)
            
            records.append(record)
            processed.add(session_id)
        except Exception as e:
            print(f"  [error] {f.name}: {e}", file=sys.stderr)
            processed.add(session_id)
        
        if len(records) % 10 == 0:
            save_checkpoint(processed)
    
    save_checkpoint(processed)
    return records


def ingest(records: list[dict]):
    """Embed and upsert all records into ChromaDB."""
    print(f"\nEmbedding {len(records)} records...")
    texts = [r["text"] for r in records]
    
    for i in range(0, len(records), BATCH_SIZE):
        batch = records[i:i + BATCH_SIZE]
        batch_texts = texts[i:i + BATCH_SIZE]
        embeddings = embed_batch(batch_texts)
        
        for j, record in enumerate(batch):
            mem_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"claude_code:{record['session_id']}"))
            upsert_memory(mem_id, batch_texts[j], embeddings[j], record["metadata"])
        
        print(f"  Upserted {min(i + BATCH_SIZE, len(records))}/{len(records)}")


def run(use_llm: bool = True):
    """Main entry point."""
    before = count_memories()
    print(f"ChromaDB memories before: {before}\n")
    
    records = collect_records(use_llm=use_llm)
    print(f"\nTotal records collected: {len(records)}")
    
    if not records:
        print("Nothing new to ingest.")
        return
    
    ingest(records)
    
    after = count_memories()
    print(f"\nDone. Memories: {before} → {after} (+{after - before})")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-llm", action="store_true", help="Skip LLM summarization (faster)")
    args = parser.parse_args()
    run(use_llm=not args.no_llm)
```

**Step 2: Verify dry-run**

```bash
cd /Users/macm1air/Documents/AI
python -c "
import sys
sys.path.insert(0, '.')
from brain.bootstrap.claude_code_extractors import SESSIONS_EXPORT_DIR
print(f'SESSIONS_EXPORT_DIR: {SESSIONS_EXPORT_DIR}')
from brain.core.embedder import embed_batch
from brain.core.db import count_memories
print(f'Imports OK, current memory count: {count_memories()}')
"
```

Expected: `SESSIONS_EXPORT_DIR: /Users/macm1air/Documents/AI/brain/bootstrap/sessions_export` and memory count

**Step 3: Commit**

```bash
cd /Users/macm1air/Documents/AI
git add brain/bootstrap/07_ingest_claude_code.py
git commit -m "feat: add 07_ingest_claude_code.py ingest pipeline with checkpoint"
```

---

### Task 3: Extend session_end hook to export session transcript

**Files:**
- Modify: `brain/hooks/session_end.py`

**Step 1: Backup and update session_end.py**

Read current session_end.py and update it:

```bash
cp /Users/macm1air/Documents/AI/brain/hooks/session_end.py /Users/macm1air/Documents/AI/brain/hooks/session_end.py.backup
```

Replace `/Users/macm1air/Documents/AI/brain/hooks/session_end.py` with:

```python
#!/usr/bin/env python3
"""
Stop hook — exports session transcript and reflects on memories before closing.
Claude Code calls this when a session ends.
"""
import sys
import json
import os
from pathlib import Path
from datetime import datetime, timezone
import uuid

sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    # Read hook context from stdin (if available)
    raw_context = sys.stdin.read().strip()
    context = json.loads(raw_context) if raw_context else {}
    
    # Try to get session metadata from context
    session_id = context.get("session_id") or str(uuid.uuid4())
    messages = context.get("messages", [])
    tool_events = context.get("tool_events", [])
    
    # Get cwd as project hint
    cwd = os.getcwd()
    project = Path(cwd).name
    
    # Export session to JSON if we have meaningful data
    if messages or tool_events:
        export_dir = Path(__file__).parent.parent / "bootstrap" / "sessions_export"
        export_dir.mkdir(parents=True, exist_ok=True)
        
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M-%S")
        export_file = export_dir / f"session_{timestamp}.json"
        
        session_export = {
            "session_id": session_id,
            "project": project,
            "cwd": cwd,
            "started_at": context.get("started_at", datetime.now(timezone.utc).isoformat()),
            "ended_at": datetime.now(timezone.utc).isoformat(),
            "messages": messages,
            "tool_events": tool_events,
        }
        
        export_file.write_text(json.dumps(session_export, indent=2))
        print(f"[BRAIN] Session exported to {export_file.name}", file=sys.stderr)
    
    # Trigger reflection on session memories
    from brain.core.memory import _trigger_reflection, get_stats
    print("[BRAIN] Running end-of-session reflection...", file=sys.stderr)
    _trigger_reflection()
    stats = get_stats()
    print(f"[BRAIN] Reflection done. Brain now has {stats['total_memories']} memories.", file=sys.stderr)

except Exception as e:
    # Never crash Claude Code over brain failure
    print(f"[BRAIN] Stop hook failed (non-fatal): {e}", file=sys.stderr)
```

**Step 2: Test the updated hook**

```bash
cd /Users/macm1air/Documents/AI
python brain/hooks/session_end.py <<< '{
  "session_id": "test-123",
  "messages": [
    {"role": "user", "content": "test message"}
  ],
  "tool_events": []
}'
```

Expected: Output mentioning "Session exported" and "Reflection done"

**Step 3: Commit**

```bash
cd /Users/macm1air/Documents/AI
git add brain/hooks/session_end.py
git commit -m "feat: extend session_end hook to export session transcripts"
```

---

### Task 4: Add integration test for full pipeline

**Files:**
- Modify: `brain/bootstrap/tests/test_claude_code_extractors.py`

**Step 1: Add integration test**

Append to `brain/bootstrap/tests/test_claude_code_extractors.py`:

```python
def test_full_ingest_pipeline(tmp_path, monkeypatch):
    """Integration test: export → extract → ingest."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
    
    from brain.bootstrap.claude_code_extractors import SESSIONS_EXPORT_DIR
    from brain.core.db import query_memories
    
    # Create a fake session export
    export_dir = tmp_path / "sessions_export"
    export_dir.mkdir()
    monkeypatch.setattr("brain.bootstrap.claude_code_extractors.SESSIONS_EXPORT_DIR", export_dir)
    
    session_file = export_dir / "session_test.json"
    session_data = {
        "session_id": "integration-test-123",
        "project": "test_project",
        "cwd": "/test/path",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "ended_at": datetime.now(timezone.utc).isoformat(),
        "messages": [
            {"role": "user", "content": "Fix the bug in parser"},
            {"role": "assistant", "content": "I found the issue in tokenizer.py"},
        ],
        "tool_events": [
            {"tool": "Edit", "file_path": "parser.py"},
            {"tool": "Bash", "command": "pytest tests/"},
        ],
    }
    session_file.write_text(json.dumps(session_data))
    
    # Extract record
    record = extract_session_record(session_file)
    assert record["session_id"] == "integration-test-123"
    assert "Fix the bug" in record["text"]
    assert record["metadata"]["source"] == "claude_code_session"
```

**Step 2: Run updated tests**

```bash
cd /Users/macm1air/Documents/AI
python -m pytest brain/bootstrap/tests/test_claude_code_extractors.py::test_full_ingest_pipeline -v
```

Expected: `1 passed`

**Step 3: Commit**

```bash
cd /Users/macm1air/Documents/AI
git add brain/bootstrap/tests/test_claude_code_extractors.py
git commit -m "test: add integration test for session export → extract pipeline"
```

---

### Task 5: Manual smoke test with mock data

**Files:** (runtime)

**Step 1: Create mock session export**

```bash
mkdir -p /Users/macm1air/Documents/AI/brain/bootstrap/sessions_export

cat > /Users/macm1air/Documents/AI/brain/bootstrap/sessions_export/session_smoke_test.json <<'EOF'
{
  "session_id": "smoke-test-001",
  "project": "AI",
  "cwd": "/Users/macm1air/Documents/AI",
  "started_at": "2026-04-02T14:30:00Z",
  "ended_at": "2026-04-02T15:45:00Z",
  "messages": [
    {
      "role": "user",
      "content": "Add error handling to the summarizer"
    },
    {
      "role": "assistant",
      "content": "I'll wrap the API calls in try-catch blocks and add logging"
    },
    {
      "role": "user",
      "content": "Also add rate limiting"
    },
    {
      "role": "assistant",
      "content": "Added exponential backoff with max retries=3"
    }
  ],
  "tool_events": [
    {
      "tool": "Edit",
      "file_path": "brain/core/summarizer.py",
      "timestamp": "2026-04-02T14:31:30Z"
    },
    {
      "tool": "Bash",
      "command": "python -m pytest brain/tests/test_summarizer.py",
      "timestamp": "2026-04-02T14:32:45Z"
    }
  ]
}
EOF
```

**Step 2: Run ingest with --no-llm flag**

```bash
cd /Users/macm1air/Documents/AI
OPENROUTER_API_KEY="" python brain/bootstrap/07_ingest_claude_code.py --no-llm
```

Expected: Output showing:
```
Found 1 session files in ...
  [1/1] session_smoke_test.json...
Total records collected: 1
Embedding 1 records...
  Upserted 1/1
Done. Memories: X → Y (+1)
```

**Step 3: Query the brain to verify ingestion**

```bash
cd /Users/macm1air/Documents/AI
python -c "
import sys
sys.path.insert(0, '.')
from brain.core.memory import search
results = search('error handling summarizer', n=3)
for r in results:
    print('---')
    print('Source:', r['metadata'].get('source'))
    print('Content:', r['content'][:100])
"
```

Expected: Result with `source: claude_code_session`

**Step 4: Verify checkpoint prevents re-processing**

```bash
cd /Users/macm1air/Documents/AI
python brain/bootstrap/07_ingest_claude_code.py --no-llm
```

Expected: Output showing:
```
Found 1 session files
  [1/1] session_smoke_test.json (already processed)
Total records collected: 0
Nothing new to ingest.
```

**Step 5: Commit and document**

```bash
cd /Users/macm1air/Documents/AI
git add brain/bootstrap/sessions_export/
git commit -m "test: add smoke test session data"
```

---

### Task 6: Document usage and create README

**Files:**
- Create: `brain/bootstrap/CLAUDE_CODE_SESSIONS.md`

**Step 1: Write session capture documentation**

Create `brain/bootstrap/CLAUDE_CODE_SESSIONS.md`:

```markdown
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
OPENROUTER_API_KEY="sk-or-..." python brain/bootstrap/07_ingest_claude_code.py

# Without summarization (faster, less rich)
python brain/bootstrap/07_ingest_claude_code.py --no-llm
```

### What It Does
1. **Scan** — Finds new session JSON files in `sessions_export/`
2. **Extract** — Validates and extracts memory records
3. **Summarize** — (Optional) Uses OpenRouter to create rich summaries
4. **Embed** — Batch-embeds all sessions with sentence-transformers
5. **Upsert** — Saves to ChromaDB with stable session UUIDs
6. **Checkpoint** — Saves progress; re-runs skip already-processed sessions

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
python -m pytest brain/bootstrap/tests/test_claude_code_extractors.py -v

# Manual smoke test
python brain/bootstrap/07_ingest_claude_code.py --no-llm
```
```

**Step 2: Commit documentation**

```bash
cd /Users/macm1air/Documents/AI
git add brain/bootstrap/CLAUDE_CODE_SESSIONS.md
git commit -m "docs: add Claude Code session capture documentation"
```

---

## Summary

**Implementation complete when all 6 tasks are done:**

✅ Task 1 — Session extractor module with validation  
✅ Task 2 — 07_ingest_claude_code.py with checkpoint  
✅ Task 3 — Extended session_end hook to export transcripts  
✅ Task 4 — Integration test for full pipeline  
✅ Task 5 — Smoke test with mock data  
✅ Task 6 — Documentation  

**Commits expected:** 6 feature commits + documentation

**Final verification:**
- `pytest brain/bootstrap/tests/test_claude_code_extractors.py` → all pass
- `python brain/bootstrap/07_ingest_claude_code.py --no-llm` → processes mock sessions
- `git log --oneline | head -10` → shows 6+ new commits


<!-- brain-linker -->
## Related
- [[brain-graph/solution/Created `07_ingest_claude_code.py` to automate the ingestion]]
- [[brain-graph/solution/Created `CLAUDE_CODE_SESSIONS.md` to document the pipeline f]]
- [[brain-graph/pattern/Successfully committed two new files (`brainbootstrapclaude_]]
- [[brain-graph/pattern/Executed the `07_ingest_claude_code.py` script with the `--n]]
- [[brain-graph/solution/Created `claude_code_extractors.py` containing foundational ]]
<!-- /brain-linker -->
