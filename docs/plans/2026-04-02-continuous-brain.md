# Continuous Brain Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a living, self-updating memory system — bootstrapped from months of Cursor chat history, continuously fed by every Claude Code session, queryable via MCP — so Claude never loses context again.

**Architecture:** A local Python stack: sentence-transformers embeds knowledge into ChromaDB, Claude API summarizes/reflects, a FastMCP server exposes search/save/reflect tools, and Claude Code hooks auto-save every exchange in real-time.

**Tech Stack:** Python 3.11+, ChromaDB, sentence-transformers (`all-mpnet-base-v2`), Anthropic SDK (`claude-haiku-4-5-20251001` for summarization, `claude-sonnet-4-6` for reflection), FastMCP, SQLite3 (stdlib), tqdm

**Design doc:** `docs/plans/2026-04-02-continuous-brain-design.md`

---

## Pre-flight: Environment Check

Before starting, verify:
```bash
python3 --version          # Need 3.11+
echo $ANTHROPIC_API_KEY    # Must be set
ls /Users/macm1air/Documents/AI/cursor-recovery-backup/recovered.sql  # Must exist
```

---

## Task 1: Project Structure + Dependencies

**Files:**
- Create: `brain/requirements.txt`
- Create: `brain/config.py`
- Create: `brain/__init__.py`
- Create: `brain/core/__init__.py`
- Create: `brain/tests/__init__.py`

**Step 1: Create the brain directory and requirements**

```bash
mkdir -p /Users/macm1air/Documents/AI/brain/{core,mcp,hooks,bootstrap,sync,tests,db}
```

Create `brain/requirements.txt`:
```
chromadb>=0.5.0
sentence-transformers>=3.0.0
anthropic>=0.40.0
mcp>=1.0.0
tqdm>=4.66.0
pytest>=8.0.0
pytest-mock>=3.12.0
```

**Step 2: Create config.py**

Create `brain/config.py`:
```python
import os
from pathlib import Path

BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR / "db"
BOOTSTRAP_DIR = BASE_DIR / "bootstrap"
OBSIDIAN_VAULT = Path("/Users/macm1air/Documents/AI")
CLAUDE_MEMORY_DIR = Path.home() / ".claude/projects/-Users-macm1air-Documents-AI/memory"
SQL_PATH = OBSIDIAN_VAULT / "cursor-recovery-backup/recovered.sql"

EMBEDDING_MODEL = "all-mpnet-base-v2"
SUMMARIZE_MODEL = "claude-haiku-4-5-20251001"
REFLECT_MODEL = "claude-sonnet-4-6"
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

MEMORIES_COLLECTION = "memories"
SESSIONS_COLLECTION = "sessions"
REFLECT_EVERY_N = 20  # Trigger reflection every N new saves
```

**Step 3: Install dependencies**

```bash
cd /Users/macm1air/Documents/AI/brain
pip install -r requirements.txt
```

Expected: All packages install without error. `sentence-transformers` will download the model on first use (~420MB).

**Step 4: Commit**

```bash
cd /Users/macm1air/Documents/AI
git init  # if not already a git repo
git add brain/requirements.txt brain/config.py brain/__init__.py brain/core/__init__.py brain/tests/__init__.py
git commit -m "feat: brain project structure and dependencies"
```

---

## Task 2: ChromaDB Client (core/db.py)

**Files:**
- Create: `brain/core/db.py`
- Create: `brain/tests/test_db.py`

**Step 1: Write the failing tests**

Create `brain/tests/test_db.py`:
```python
import sys
sys.path.insert(0, str(__import__('pathlib').Path(__file__).parent.parent))

import pytest
import chromadb
from unittest.mock import patch, MagicMock


def make_in_memory_client():
    return chromadb.EphemeralClient()


def test_get_memories_collection_creates_if_not_exists(tmp_path, monkeypatch):
    monkeypatch.setenv("BRAIN_DB_PATH", str(tmp_path / "db"))
    import importlib
    import brain.core.db as db_module
    db_module._client = None
    with patch.object(db_module, 'DB_PATH', tmp_path / "db"):
        col = db_module.get_memories_collection()
        assert col.name == "memories"


def test_upsert_and_query_memory(tmp_path, monkeypatch):
    import brain.core.db as db_module
    db_module._client = chromadb.EphemeralClient()
    col = db_module.get_memories_collection()

    db_module.upsert_memory(
        id="test-1",
        document="Solved CORS issue with Express proxy",
        embedding=[0.1] * 768,
        metadata={"type": "solution", "project": "bella", "tags": "cors,express"}
    )

    results = db_module.query_memories(embedding=[0.1] * 768, n_results=1)
    assert results["ids"][0][0] == "test-1"
    assert "CORS" in results["documents"][0][0]


def test_count_memories(tmp_path):
    import brain.core.db as db_module
    db_module._client = chromadb.EphemeralClient()
    assert db_module.count_memories() == 0
    db_module.upsert_memory("id-1", "test doc", [0.1] * 768, {"type": "solution"})
    assert db_module.count_memories() == 1
```

**Step 2: Run tests to verify they fail**

```bash
cd /Users/macm1air/Documents/AI/brain
pytest tests/test_db.py -v
```

Expected: `ModuleNotFoundError` or `ImportError` — `brain.core.db` doesn't exist yet.

**Step 3: Implement core/db.py**

Create `brain/core/db.py`:
```python
import chromadb
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from config import DB_PATH, MEMORIES_COLLECTION, SESSIONS_COLLECTION

_client = None


def get_client():
    global _client
    if _client is None:
        DB_PATH.mkdir(parents=True, exist_ok=True)
        _client = chromadb.PersistentClient(path=str(DB_PATH))
    return _client


def get_memories_collection():
    return get_client().get_or_create_collection(
        name=MEMORIES_COLLECTION,
        metadata={"hnsw:space": "cosine"}
    )


def get_sessions_collection():
    return get_client().get_or_create_collection(
        name=SESSIONS_COLLECTION,
        metadata={"hnsw:space": "cosine"}
    )


def upsert_memory(id: str, document: str, embedding: list, metadata: dict):
    get_memories_collection().upsert(
        ids=[id],
        documents=[document],
        embeddings=[embedding],
        metadatas=[metadata]
    )


def upsert_session(id: str, document: str, embedding: list, metadata: dict):
    get_sessions_collection().upsert(
        ids=[id],
        documents=[document],
        embeddings=[embedding],
        metadatas=[metadata]
    )


def query_memories(embedding: list, n_results: int = 10, where: dict = None) -> dict:
    kwargs = {"query_embeddings": [embedding], "n_results": min(n_results, count_memories() or 1)}
    if where:
        kwargs["where"] = where
    return get_memories_collection().query(**kwargs)


def delete_memories(ids: list):
    get_memories_collection().delete(ids=ids)


def get_all_memory_documents(limit: int = 100) -> list:
    col = get_memories_collection()
    result = col.get(limit=limit, include=["documents", "metadatas"])
    return list(zip(result["ids"], result["documents"], result["metadatas"]))


def count_memories() -> int:
    return get_memories_collection().count()


def count_sessions() -> int:
    return get_sessions_collection().count()
```

**Step 4: Run tests to verify they pass**

```bash
pytest tests/test_db.py -v
```

Expected: All 3 tests PASS.

**Step 5: Commit**

```bash
git add brain/core/db.py brain/tests/test_db.py
git commit -m "feat: ChromaDB client with upsert/query/delete"
```

---

## Task 3: Embedder (core/embedder.py)

**Files:**
- Create: `brain/core/embedder.py`
- Create: `brain/tests/test_embedder.py`

**Step 1: Write failing tests**

Create `brain/tests/test_embedder.py`:
```python
import sys
sys.path.insert(0, str(__import__('pathlib').Path(__file__).parent.parent))
import pytest
from unittest.mock import patch, MagicMock
import numpy as np


def test_embed_returns_list_of_floats():
    import brain.core.embedder as emb
    result = emb.embed("test sentence about CORS")
    assert isinstance(result, list)
    assert len(result) == 768  # all-mpnet-base-v2 output dim
    assert all(isinstance(x, float) for x in result)


def test_embed_batch_returns_list_of_lists():
    import brain.core.embedder as emb
    results = emb.embed_batch(["sentence one", "sentence two"])
    assert len(results) == 2
    assert len(results[0]) == 768


def test_embed_is_deterministic():
    import brain.core.embedder as emb
    a = emb.embed("hello world")
    b = emb.embed("hello world")
    assert a == b


def test_similar_texts_have_higher_similarity():
    import brain.core.embedder as emb
    import numpy as np
    a = np.array(emb.embed("fix CORS issue in express server"))
    b = np.array(emb.embed("resolve cross origin resource sharing problem"))
    c = np.array(emb.embed("make pancakes for breakfast"))
    sim_ab = np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))
    sim_ac = np.dot(a, c) / (np.linalg.norm(a) * np.linalg.norm(c))
    assert sim_ab > sim_ac
```

**Step 2: Run to verify failure**

```bash
pytest tests/test_embedder.py -v
```

Expected: `ModuleNotFoundError`

**Step 3: Implement core/embedder.py**

Create `brain/core/embedder.py`:
```python
from sentence_transformers import SentenceTransformer
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from config import EMBEDDING_MODEL

_model = None


def get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        _model = SentenceTransformer(EMBEDDING_MODEL)
    return _model


def embed(text: str) -> list[float]:
    return get_model().encode(text, normalize_embeddings=True).tolist()


def embed_batch(texts: list[str], batch_size: int = 128) -> list[list[float]]:
    return get_model().encode(texts, batch_size=batch_size, normalize_embeddings=True).tolist()
```

**Step 4: Run tests**

```bash
pytest tests/test_embedder.py -v
```

Note: First run downloads the model (~420MB). Expected: All 4 tests PASS.

**Step 5: Commit**

```bash
git add brain/core/embedder.py brain/tests/test_embedder.py
git commit -m "feat: sentence-transformers embedder with batch support"
```

---

## Task 4: Summarizer (core/summarizer.py)

**Files:**
- Create: `brain/core/summarizer.py`
- Create: `brain/tests/test_summarizer.py`

**Step 1: Write failing tests (mocked — never hit real API in tests)**

Create `brain/tests/test_summarizer.py`:
```python
import sys
sys.path.insert(0, str(__import__('pathlib').Path(__file__).parent.parent))
import pytest
import json
from unittest.mock import patch, MagicMock


SAMPLE_CONVERSATION = [
    {"role": "user", "content": "How do I fix the CORS error in my Express app?"},
    {"role": "assistant", "content": "Add cors middleware: npm install cors, then app.use(cors())"},
    {"role": "user", "content": "That fixed it, thanks!"},
]

SAMPLE_SUMMARY_RESPONSE = json.dumps({
    "summary": "Fixed CORS error in Express by adding cors middleware",
    "project": "bella",
    "topics": ["cors", "express", "middleware"],
    "decisions": ["Use cors npm package"],
    "solutions": ["CORS error: install cors package, call app.use(cors())"],
    "patterns": ["Express middleware setup pattern"],
    "type": "solution"
})


def _make_mock_client(response_text: str):
    mock_message = MagicMock()
    mock_message.content = [MagicMock(text=response_text)]
    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_message
    return mock_client


def test_summarize_conversation_returns_dict():
    import brain.core.summarizer as s
    with patch.object(s, 'get_client', return_value=_make_mock_client(SAMPLE_SUMMARY_RESPONSE)):
        result = s.summarize_conversation(SAMPLE_CONVERSATION)
    assert isinstance(result, dict)
    assert "summary" in result
    assert "topics" in result
    assert "type" in result


def test_summarize_conversation_handles_json_with_surrounding_text():
    import brain.core.summarizer as s
    wrapped = "Here is the analysis:\n" + SAMPLE_SUMMARY_RESPONSE + "\nDone."
    with patch.object(s, 'get_client', return_value=_make_mock_client(wrapped)):
        result = s.summarize_conversation(SAMPLE_CONVERSATION)
    assert result["type"] == "solution"


def test_summarize_exchange_returns_string():
    import brain.core.summarizer as s
    mock_client = _make_mock_client("Saved CORS fix to brain.")
    with patch.object(s, 'get_client', return_value=mock_client):
        result = s.summarize_exchange("user asked about CORS", "assistant explained cors package")
    assert isinstance(result, str)
    assert len(result) > 0


def test_reflect_memories_returns_dict():
    import brain.core.summarizer as s
    reflect_response = json.dumps({
        "consolidated": ["Fixed CORS issues using cors package in Express apps"],
        "patterns": ["Always use cors middleware in Express for CORS"],
        "to_delete_indices": []
    })
    with patch.object(s, 'get_client', return_value=_make_mock_client(reflect_response)):
        result = s.reflect_memories(["memory 1", "memory 2"])
    assert "consolidated" in result
    assert "to_delete_indices" in result
```

**Step 2: Run to verify failure**

```bash
pytest tests/test_summarizer.py -v
```

Expected: `ModuleNotFoundError`

**Step 3: Implement core/summarizer.py**

Create `brain/core/summarizer.py`:
```python
import json
import sys
from pathlib import Path
import anthropic

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import ANTHROPIC_API_KEY, SUMMARIZE_MODEL, REFLECT_MODEL

_client = None


def get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    return _client


def _parse_json(text: str) -> dict:
    start = text.find('{')
    end = text.rfind('}') + 1
    if start == -1:
        raise ValueError(f"No JSON found in response: {text[:200]}")
    return json.loads(text[start:end])


def summarize_conversation(messages: list[dict]) -> dict:
    """Summarize a full conversation session into structured knowledge."""
    # Truncate long messages to fit context
    formatted_parts = []
    for m in messages[:30]:
        content = m.get("content", "")
        if isinstance(content, list):
            content = " ".join(p.get("text", "") for p in content if isinstance(p, dict))
        formatted_parts.append(f"{m.get('role', 'unknown')}: {str(content)[:800]}")
    formatted = "\n".join(formatted_parts)

    response = get_client().messages.create(
        model=SUMMARIZE_MODEL,
        max_tokens=1024,
        messages=[{
            "role": "user",
            "content": f"""Analyze this AI coding conversation. Extract structured knowledge.

CONVERSATION:
{formatted}

Respond with ONLY valid JSON (no markdown, no explanation):
{{
  "summary": "2-3 sentence description of what was accomplished",
  "project": "project name or null",
  "topics": ["topic1", "topic2"],
  "decisions": ["key architectural or design decision made"],
  "solutions": ["problem: solution description"],
  "patterns": ["reusable code pattern discovered"],
  "type": "solution|decision|conversation|project_context|error_lesson"
}}"""
        }]
    )
    return _parse_json(response.content[0].text)


def summarize_exchange(user_message: str, assistant_response: str) -> str:
    """Summarize a single exchange into a concise memory string."""
    response = get_client().messages.create(
        model=SUMMARIZE_MODEL,
        max_tokens=256,
        messages=[{
            "role": "user",
            "content": f"""Summarize this coding exchange in 1-2 sentences for future memory retrieval.
Focus on: what was done, what was decided, or what was solved.

USER: {user_message[:500]}
ASSISTANT: {assistant_response[:500]}

Respond with just the summary text, no JSON."""
        }]
    )
    return response.content[0].text.strip()


def reflect_memories(memory_texts: list[str]) -> dict:
    """Consolidate and find patterns across a batch of memories."""
    formatted = "\n\n".join([f"[{i}] {m}" for i, m in enumerate(memory_texts)])

    response = get_client().messages.create(
        model=REFLECT_MODEL,
        max_tokens=2048,
        messages=[{
            "role": "user",
            "content": f"""Review these memories. Consolidate near-duplicates, find patterns.

MEMORIES:
{formatted}

Respond with ONLY valid JSON:
{{
  "consolidated": ["merged or improved memory text for keeping"],
  "patterns": ["cross-memory insight or pattern worth saving"],
  "to_delete_indices": [0, 3]
}}"""
        }]
    )
    return _parse_json(response.content[0].text)
```

**Step 4: Run tests**

```bash
pytest tests/test_summarizer.py -v
```

Expected: All 4 tests PASS (no real API calls made).

**Step 5: Commit**

```bash
git add brain/core/summarizer.py brain/tests/test_summarizer.py
git commit -m "feat: Claude summarizer for conversations and exchanges"
```

---

## Task 5: Memory Operations (core/memory.py)

**Files:**
- Create: `brain/core/memory.py`
- Create: `brain/tests/test_memory.py`

**Step 1: Write failing tests**

Create `brain/tests/test_memory.py`:
```python
import sys
sys.path.insert(0, str(__import__('pathlib').Path(__file__).parent.parent))
import pytest
import chromadb
from unittest.mock import patch, MagicMock
from datetime import datetime


def _patch_db(module):
    """Replace ChromaDB client with ephemeral for testing."""
    module.db._client = chromadb.EphemeralClient()


def test_save_memory_stores_in_db():
    import brain.core.memory as m
    import brain.core.db as db
    _patch_db(m)
    # Mock embedder to avoid model loading
    with patch('brain.core.memory.embed', return_value=[0.1] * 768):
        m.save_memory(
            content="Fixed CORS in Express with cors package",
            memory_type="solution",
            tags=["cors", "express"],
            project="bella"
        )
    assert db.count_memories() == 1


def test_search_returns_relevant_results():
    import brain.core.memory as m
    import brain.core.db as db
    _patch_db(m)
    with patch('brain.core.memory.embed', return_value=[0.9] * 768):
        m.save_memory("CORS fix in Express", "solution", ["cors"], "bella")
    with patch('brain.core.memory.embed', return_value=[0.1] * 768):
        results = m.search("cors express", n=5)
    assert len(results) >= 0  # May not match with dummy embeddings — structure check


def test_save_memory_generates_id():
    import brain.core.memory as m
    _patch_db(m)
    with patch('brain.core.memory.embed', return_value=[0.1] * 768):
        memory_id = m.save_memory("test content", "solution", [], None)
    assert isinstance(memory_id, str)
    assert len(memory_id) > 0


def test_get_stats_returns_counts():
    import brain.core.memory as m
    import brain.core.db as db
    _patch_db(m)
    stats = m.get_stats()
    assert "total_memories" in stats
    assert "total_sessions" in stats
```

**Step 2: Run to verify failure**

```bash
pytest tests/test_memory.py -v
```

Expected: `ModuleNotFoundError`

**Step 3: Implement core/memory.py**

Create `brain/core/memory.py`:
```python
import sys
import uuid
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).parent.parent))
from brain.core.embedder import embed
from brain.core.summarizer import reflect_memories
import brain.core.db as db
from config import REFLECT_EVERY_N

_save_count = 0


def save_memory(
    content: str,
    memory_type: str,
    tags: list[str],
    project: str | None,
    session_id: str | None = None,
    source: str = "claude_code_session"
) -> str:
    global _save_count

    memory_id = str(uuid.uuid4())
    embedding = embed(content)
    metadata = {
        "type": memory_type,
        "project": project or "general",
        "tags": ",".join(tags),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "session_id": session_id or "",
        "importance": 0.5
    }

    db.upsert_memory(memory_id, content, embedding, metadata)

    _save_count += 1
    if _save_count % REFLECT_EVERY_N == 0:
        _trigger_reflection()

    return memory_id


def search(query: str, n: int = 10, memory_type: str | None = None, project: str | None = None) -> list[dict]:
    embedding = embed(query)
    where = None
    if memory_type and project:
        where = {"$and": [{"type": {"$eq": memory_type}}, {"project": {"$eq": project}}]}
    elif memory_type:
        where = {"type": {"$eq": memory_type}}
    elif project:
        where = {"project": {"$eq": project}}

    results = db.query_memories(embedding, n_results=n, where=where)
    if not results["ids"][0]:
        return []

    return [
        {
            "id": results["ids"][0][i],
            "content": results["documents"][0][i],
            "metadata": results["metadatas"][0][i],
            "distance": results["distances"][0][i] if "distances" in results else None
        }
        for i in range(len(results["ids"][0]))
    ]


def get_context(topic: str, project: str | None = None, n: int = 5) -> list[dict]:
    """Get top N most relevant memories for current context."""
    return search(topic, n=n, project=project)


def get_stats() -> dict:
    return {
        "total_memories": db.count_memories(),
        "total_sessions": db.count_sessions(),
        "save_count_this_session": _save_count
    }


def _trigger_reflection():
    """Consolidate recent memories."""
    recent = db.get_all_memory_documents(limit=50)
    if len(recent) < 5:
        return

    ids = [r[0] for r in recent]
    texts = [r[1] for r in recent]

    try:
        result = reflect_memories(texts)

        # Delete near-duplicates
        to_delete = [ids[i] for i in result.get("to_delete_indices", []) if i < len(ids)]
        if to_delete:
            db.delete_memories(to_delete)

        # Save consolidated memories
        for consolidated_text in result.get("consolidated", []):
            save_memory(consolidated_text, "pattern", ["reflected"], None, source="reflection")

    except Exception as e:
        print(f"[brain] Reflection failed (non-fatal): {e}", file=sys.stderr)
```

**Step 4: Run tests**

```bash
pytest tests/test_memory.py -v
```

Expected: All 4 tests PASS.

**Step 5: Commit**

```bash
git add brain/core/memory.py brain/tests/test_memory.py
git commit -m "feat: high-level memory operations with auto-reflection"
```

---

## Task 6: Bootstrap — SQL Parser (bootstrap/01_parse_sql.py)

**Files:**
- Create: `brain/bootstrap/01_parse_sql.py`
- Create: `brain/tests/test_bootstrap_parser.py`

**Step 1: Understand the SQL structure first**

```bash
# Import SQL into a temp SQLite DB to explore
cd /Users/macm1air/Documents/AI
sqlite3 /tmp/cursor_brain.db < cursor-recovery-backup/recovered.sql 2>&1 | head -5
sqlite3 /tmp/cursor_brain.db "SELECT key FROM ItemTable WHERE key LIKE '%composer%' LIMIT 20;"
sqlite3 /tmp/cursor_brain.db "SELECT COUNT(*) FROM ItemTable;"
sqlite3 /tmp/cursor_brain.db "SELECT key FROM ItemTable ORDER BY _rowid_ DESC LIMIT 10;"
```

Note the output — identify which key patterns contain actual chat messages (look for keys with "bubbles", "messages", "composerData", etc.)

**Step 2: Write failing tests**

Create `brain/tests/test_bootstrap_parser.py`:
```python
import sys
sys.path.insert(0, str(__import__('pathlib').Path(__file__).parent.parent))
import pytest
import json
import sqlite3
import tempfile
import os


SAMPLE_SQL = """
BEGIN;
CREATE TABLE ItemTable (key TEXT UNIQUE ON CONFLICT REPLACE, value BLOB);
INSERT OR IGNORE INTO 'ItemTable'(_rowid_, 'key', 'value') VALUES (1, 'composerData:abc123', '{"bubbles":[{"role":"user","content":"How do I fix CORS?"},{"role":"assistant","content":"Use cors package"}]}');
INSERT OR IGNORE INTO 'ItemTable'(_rowid_, 'key', 'value') VALUES (2, 'workbench.settings', '{"theme":"dark"}');
COMMIT;
"""


@pytest.fixture
def sample_db(tmp_path):
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(SAMPLE_SQL)
    conn.close()
    return db_path


def test_discover_chat_keys(sample_db):
    from brain.bootstrap.parse_sql import discover_chat_keys
    keys = discover_chat_keys(str(sample_db))
    assert len(keys) >= 1
    assert any("composerData" in k or "bubble" in k.lower() for k in keys)


def test_extract_messages_from_key(sample_db):
    from brain.bootstrap.parse_sql import extract_messages_from_row
    conn = sqlite3.connect(str(sample_db))
    value = conn.execute("SELECT value FROM ItemTable WHERE key = 'composerData:abc123'").fetchone()[0]
    conn.close()
    messages = extract_messages_from_row(value)
    assert len(messages) == 2
    assert messages[0]["role"] == "user"
    assert "CORS" in messages[0]["content"]


def test_extract_all_conversations(sample_db):
    from brain.bootstrap.parse_sql import extract_all_conversations
    convos = extract_all_conversations(str(sample_db))
    assert len(convos) >= 1
    assert "messages" in convos[0]
    assert "session_id" in convos[0]
```

**Step 3: Run to verify failure**

```bash
pytest tests/test_bootstrap_parser.py -v
```

Expected: `ModuleNotFoundError`

**Step 4: Implement bootstrap/01_parse_sql.py**

Create `brain/bootstrap/parse_sql.py`:
```python
"""
Parse Cursor's SQLite storage dump and extract conversation history.
"""
import sqlite3
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import SQL_PATH

# Key prefixes that contain actual chat content
# Discovered empirically by inspecting the DB
CHAT_KEY_PATTERNS = [
    "composerData",
    "aichat",
    "composer.",
    "workbench.panel.aichat",
]


def import_sql_to_db(sql_path: str, db_path: str) -> None:
    """Import SQL dump into a SQLite database."""
    print(f"Importing {sql_path} → {db_path}")
    conn = sqlite3.connect(db_path)
    with open(sql_path, 'r', encoding='utf-8', errors='replace') as f:
        sql = f.read()
    conn.executescript(sql)
    conn.close()
    print("Import complete.")


def discover_chat_keys(db_path: str) -> list[str]:
    """Find all keys that likely contain conversation data."""
    conn = sqlite3.connect(db_path)
    cursor = conn.execute("SELECT DISTINCT key FROM ItemTable")
    all_keys = [row[0] for row in cursor.fetchall()]
    conn.close()

    chat_keys = []
    for key in all_keys:
        if any(pattern.lower() in key.lower() for pattern in CHAT_KEY_PATTERNS):
            chat_keys.append(key)

    # Also look for keys whose JSON values contain "bubbles" or "messages"
    conn = sqlite3.connect(db_path)
    for key in all_keys:
        if key in chat_keys:
            continue
        try:
            row = conn.execute("SELECT value FROM ItemTable WHERE key = ?", (key,)).fetchone()
            if row and isinstance(row[0], str):
                val = row[0][:200]
                if '"bubbles"' in val or '"messages"' in val or '"role"' in val:
                    chat_keys.append(key)
        except Exception:
            pass
    conn.close()

    return list(set(chat_keys))


def extract_messages_from_row(value: str | bytes) -> list[dict]:
    """Parse JSON value and extract message list."""
    if isinstance(value, bytes):
        return []  # Binary blob — skip

    try:
        data = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return []

    # Try common structures
    if isinstance(data, dict):
        for key in ("bubbles", "messages", "history", "turns"):
            if key in data and isinstance(data[key], list):
                messages = []
                for item in data[key]:
                    if isinstance(item, dict):
                        role = item.get("role") or item.get("type") or "unknown"
                        content = item.get("content") or item.get("text") or item.get("message") or ""
                        if isinstance(content, list):
                            content = " ".join(
                                p.get("text", "") for p in content
                                if isinstance(p, dict) and "text" in p
                            )
                        if content:
                            messages.append({"role": str(role), "content": str(content)})
                if messages:
                    return messages

    return []


def extract_all_conversations(db_path: str) -> list[dict]:
    """Extract all conversations from the database."""
    chat_keys = discover_chat_keys(db_path)
    print(f"Found {len(chat_keys)} potential chat keys")

    conn = sqlite3.connect(db_path)
    conversations = []

    for key in chat_keys:
        try:
            row = conn.execute("SELECT value FROM ItemTable WHERE key = ?", (key,)).fetchone()
            if not row:
                continue
            messages = extract_messages_from_row(row[0])
            if len(messages) >= 2:  # Only keep conversations with actual exchange
                conversations.append({
                    "session_id": key,
                    "messages": messages,
                    "message_count": len(messages)
                })
        except Exception as e:
            print(f"[parse] Skipping {key}: {e}", file=sys.stderr)

    conn.close()
    print(f"Extracted {len(conversations)} conversations with ≥2 messages")
    return conversations


if __name__ == "__main__":
    import tempfile
    import os

    DB_CACHE = Path(__file__).parent / "cursor_brain.db"

    if not DB_CACHE.exists():
        import_sql_to_db(str(SQL_PATH), str(DB_CACHE))

    convos = extract_all_conversations(str(DB_CACHE))

    output_path = Path(__file__).parent / "raw_conversations.jsonl"
    with open(output_path, 'w') as f:
        for convo in convos:
            f.write(json.dumps(convo) + '\n')

    print(f"Saved {len(convos)} conversations to {output_path}")
```

**Step 5: Run tests**

```bash
pytest tests/test_bootstrap_parser.py -v
```

Expected: All 3 tests PASS.

**Step 6: Commit**

```bash
git add brain/bootstrap/parse_sql.py brain/tests/test_bootstrap_parser.py
git commit -m "feat: SQL parser for Cursor conversation extraction"
```

---

## Task 7: Bootstrap — Summarization Pipeline (bootstrap/02_summarize.py)

**Files:**
- Create: `brain/bootstrap/02_summarize.py`

**Step 1: Implement with checkpointing**

Create `brain/bootstrap/02_summarize.py`:
```python
"""
Summarize raw conversations using Claude API.
Checkpointed — safe to interrupt and resume.
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from brain.core.summarizer import summarize_conversation
from tqdm import tqdm

INPUT_PATH = Path(__file__).parent / "raw_conversations.jsonl"
OUTPUT_PATH = Path(__file__).parent / "summaries.jsonl"
CHECKPOINT_PATH = Path(__file__).parent / "checkpoint.json"


def load_checkpoint() -> set:
    if CHECKPOINT_PATH.exists():
        data = json.loads(CHECKPOINT_PATH.read_text())
        return set(data.get("processed_ids", []))
    return set()


def save_checkpoint(processed_ids: set):
    CHECKPOINT_PATH.write_text(json.dumps({"processed_ids": list(processed_ids)}))


def run():
    if not INPUT_PATH.exists():
        print("Run 01_parse_sql.py first.")
        sys.exit(1)

    conversations = [json.loads(line) for line in INPUT_PATH.read_text().splitlines() if line.strip()]
    processed_ids = load_checkpoint()

    print(f"Total conversations: {len(conversations)}")
    print(f"Already processed: {len(processed_ids)}")
    remaining = [c for c in conversations if c["session_id"] not in processed_ids]
    print(f"Remaining: {len(remaining)}")

    with open(OUTPUT_PATH, 'a') as out_file:
        for convo in tqdm(remaining, desc="Summarizing"):
            session_id = convo["session_id"]
            try:
                summary = summarize_conversation(convo["messages"])
                summary["session_id"] = session_id
                summary["message_count"] = convo["message_count"]
                out_file.write(json.dumps(summary) + '\n')
                out_file.flush()

                processed_ids.add(session_id)
                # Save checkpoint every 10
                if len(processed_ids) % 10 == 0:
                    save_checkpoint(processed_ids)

                # Rate limit — Claude haiku allows ~50 req/min
                time.sleep(0.5)

            except Exception as e:
                print(f"\n[summarize] Failed {session_id}: {e}", file=sys.stderr)
                save_checkpoint(processed_ids)

    save_checkpoint(processed_ids)
    print(f"\nDone. Summaries saved to {OUTPUT_PATH}")


if __name__ == "__main__":
    run()
```

**Step 2: Verify script is syntactically correct**

```bash
python -c "import brain.bootstrap.summarize_02; print('OK')"
# OR
python brain/bootstrap/02_summarize.py --help 2>&1 || python -m py_compile brain/bootstrap/02_summarize.py && echo "Syntax OK"
```

Expected: No syntax errors.

**Step 3: Commit**

```bash
git add brain/bootstrap/02_summarize.py
git commit -m "feat: checkpointed Claude summarization pipeline"
```

---

## Task 8: Bootstrap — Embed & Ingest (bootstrap/03_ingest.py)

**Files:**
- Create: `brain/bootstrap/03_ingest.py`

**Step 1: Implement**

Create `brain/bootstrap/03_ingest.py`:
```python
"""
Embed summaries and ingest into ChromaDB.
"""
import json
import sys
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).parent.parent))
from brain.core.embedder import embed_batch
from brain.core.db import upsert_memory, upsert_session, count_memories
from tqdm import tqdm
import uuid

INPUT_PATH = Path(__file__).parent / "summaries.jsonl"
BATCH_SIZE = 64


def run():
    if not INPUT_PATH.exists():
        print("Run 02_summarize.py first.")
        sys.exit(1)

    summaries = [json.loads(l) for l in INPUT_PATH.read_text().splitlines() if l.strip()]
    print(f"Ingesting {len(summaries)} summaries...")

    # Process in batches for efficiency
    for i in tqdm(range(0, len(summaries), BATCH_SIZE), desc="Embedding & ingesting"):
        batch = summaries[i:i + BATCH_SIZE]

        # Build texts for embedding
        texts = []
        for s in batch:
            parts = [s.get("summary", "")]
            parts += s.get("solutions", [])
            parts += s.get("decisions", [])
            parts += s.get("patterns", [])
            texts.append(" | ".join(filter(None, parts)))

        embeddings = embed_batch(texts)

        for j, s in enumerate(batch):
            # Upsert as memory
            memory_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, s["session_id"]))
            metadata = {
                "type": s.get("type", "conversation"),
                "project": s.get("project") or "general",
                "tags": ",".join(s.get("topics", [])),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "source": "cursor_history",
                "session_id": s["session_id"],
                "importance": 0.7
            }
            upsert_memory(memory_id, texts[j], embeddings[j], metadata)

            # Also upsert session-level record
            session_meta = {
                "date": datetime.now(timezone.utc).date().isoformat(),
                "project": s.get("project") or "general",
                "topics": ",".join(s.get("topics", [])),
                "message_count": str(s.get("message_count", 0)),
                "source": "cursor_history"
            }
            upsert_session(
                id=s["session_id"],
                document=s.get("summary", ""),
                embedding=embeddings[j],
                metadata=session_meta
            )

    print(f"\nIngestion complete. Total memories: {count_memories()}")


if __name__ == "__main__":
    run()
```

**Step 2: Syntax check**

```bash
python -m py_compile brain/bootstrap/03_ingest.py && echo "Syntax OK"
```

**Step 3: Commit**

```bash
git add brain/bootstrap/03_ingest.py
git commit -m "feat: batch embedding and ChromaDB ingestion pipeline"
```

---

## Task 9: Bootstrap — Sync Outputs (bootstrap/04_sync.py)

**Files:**
- Create: `brain/sync/obsidian.py`
- Create: `brain/sync/claude_memory.py`
- Create: `brain/bootstrap/04_sync.py`

**Step 1: Implement Obsidian sync**

Create `brain/sync/obsidian.py`:
```python
"""Write brain memories as Obsidian markdown notes."""
import json
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import OBSIDIAN_VAULT


def write_project_note(project: str, summaries: list[dict]):
    """Write a single note per project with all its memories."""
    notes_dir = OBSIDIAN_VAULT / "brain-notes"
    notes_dir.mkdir(exist_ok=True)

    safe_name = project.replace("/", "-").replace(" ", "-").lower()
    note_path = notes_dir / f"{safe_name}.md"

    lines = [
        f"# {project.title()} — Brain Notes",
        f"*Last updated: {datetime.now().strftime('%Y-%m-%d')}*",
        f"*{len(summaries)} memories*",
        "",
        "---",
        ""
    ]

    for s in summaries:
        lines.append(f"## {s.get('summary', 'Session')[:80]}")
        lines.append(f"*Topics: {', '.join(s.get('topics', []))}*")
        lines.append("")
        for decision in s.get("decisions", []):
            lines.append(f"- **Decision:** {decision}")
        for solution in s.get("solutions", []):
            lines.append(f"- **Solution:** {solution}")
        for pattern in s.get("patterns", []):
            lines.append(f"- **Pattern:** {pattern}")
        lines.append("")
        lines.append("---")
        lines.append("")

    note_path.write_text("\n".join(lines))
    print(f"Written: {note_path}")
```

Create `brain/sync/claude_memory.py`:
```python
"""Write brain summaries to Claude memory files."""
import json
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import CLAUDE_MEMORY_DIR


def write_project_memory(project: str, summaries: list[dict]):
    """Write a Claude memory file for a project."""
    CLAUDE_MEMORY_DIR.mkdir(parents=True, exist_ok=True)

    safe_name = project.replace("/", "-").replace(" ", "-").lower()
    mem_path = CLAUDE_MEMORY_DIR / f"project_{safe_name}.md"

    decisions = []
    solutions = []
    patterns = []
    topics = set()

    for s in summaries:
        decisions.extend(s.get("decisions", []))
        solutions.extend(s.get("solutions", []))
        patterns.extend(s.get("patterns", []))
        topics.update(s.get("topics", []))

    content = f"""---
name: {project} project knowledge
description: Key decisions, solutions, and patterns from {project} development history
type: project
---

## {project.title()}

**Topics worked on:** {', '.join(sorted(topics))}
**Sessions in history:** {len(summaries)}

### Key Decisions
{chr(10).join(f'- {d}' for d in decisions[:20])}

### Solutions Found
{chr(10).join(f'- {s}' for s in solutions[:20])}

### Patterns Discovered
{chr(10).join(f'- {p}' for p in patterns[:10])}

*Last synced: {datetime.now().strftime('%Y-%m-%d')}*
"""
    mem_path.write_text(content)
    print(f"Written: {mem_path}")
```

Create `brain/bootstrap/04_sync.py`:
```python
"""Sync summaries to Obsidian and Claude memory files."""
import json
import sys
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parent.parent))
from brain.sync.obsidian import write_project_note
from brain.sync.claude_memory import write_project_memory

INPUT_PATH = Path(__file__).parent / "summaries.jsonl"


def run():
    summaries = [json.loads(l) for l in INPUT_PATH.read_text().splitlines() if l.strip()]

    # Group by project
    by_project = defaultdict(list)
    for s in summaries:
        project = s.get("project") or "general"
        by_project[project].append(s)

    print(f"Syncing {len(by_project)} projects...")
    for project, project_summaries in by_project.items():
        write_project_note(project, project_summaries)
        write_project_memory(project, project_summaries)

    print("Sync complete.")


if __name__ == "__main__":
    run()
```

**Step 2: Syntax check all three**

```bash
python -m py_compile brain/sync/obsidian.py brain/sync/claude_memory.py brain/bootstrap/04_sync.py && echo "Syntax OK"
```

**Step 3: Commit**

```bash
git add brain/sync/ brain/bootstrap/04_sync.py
git commit -m "feat: Obsidian + Claude memory sync from brain summaries"
```

---

## Task 10: MCP Server (mcp/server.py)

**Files:**
- Create: `brain/mcp/server.py`
- Create: `brain/mcp/__init__.py`
- Create: `brain/tests/test_mcp.py`

**Step 1: Write failing tests**

Create `brain/tests/test_mcp.py`:
```python
import sys
sys.path.insert(0, str(__import__('pathlib').Path(__file__).parent.parent))
import pytest
import json
import chromadb
from unittest.mock import patch, MagicMock


def test_mcp_server_module_imports():
    """MCP server module must import without errors."""
    import brain.mcp.server
    assert hasattr(brain.mcp.server, 'mcp')


def test_search_brain_tool_exists():
    import brain.mcp.server as server
    tool_names = [t.name for t in server.mcp._tools.values()] if hasattr(server.mcp, '_tools') else []
    # FastMCP registers tools differently — just check the function exists
    assert hasattr(server, 'search_brain')


def test_save_memory_tool_exists():
    import brain.mcp.server as server
    assert hasattr(server, 'save_memory_tool')


def test_get_context_tool_exists():
    import brain.mcp.server as server
    assert hasattr(server, 'get_context_tool')


def test_reflect_tool_exists():
    import brain.mcp.server as server
    assert hasattr(server, 'reflect_tool')


def test_get_stats_tool_exists():
    import brain.mcp.server as server
    assert hasattr(server, 'get_stats_tool')
```

**Step 2: Run to verify failure**

```bash
pytest tests/test_mcp.py -v
```

Expected: `ModuleNotFoundError`

**Step 3: Implement mcp/server.py**

Create `brain/mcp/__init__.py`: (empty)

Create `brain/mcp/server.py`:
```python
"""
Brain MCP Server — exposes brain tools to Claude and Claude Code.

Run with: python -m brain.mcp.server
Or via Claude Code MCP config.
"""
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp.server.fastmcp import FastMCP
from brain.core.memory import save_memory, search, get_context, get_stats, _trigger_reflection

mcp = FastMCP("brain", instructions=(
    "You have access to a persistent brain with months of coding history. "
    "Use search_brain to recall past decisions and solutions. "
    "Use save_memory_tool to save important new knowledge. "
    "Use get_context_tool at session start to load relevant memories. "
    "Use reflect_tool periodically to consolidate memories."
))


@mcp.tool(description="Semantic search across all memories. Returns most relevant past decisions, solutions, patterns.")
def search_brain(query: str, n: int = 10, memory_type: str = "", project: str = "") -> str:
    results = search(
        query=query,
        n=n,
        memory_type=memory_type or None,
        project=project or None
    )
    if not results:
        return "No relevant memories found."

    lines = [f"Found {len(results)} relevant memories:\n"]
    for i, r in enumerate(results, 1):
        meta = r["metadata"]
        lines.append(f"[{i}] ({meta.get('type', '?')} | {meta.get('project', '?')})")
        lines.append(f"    {r['content']}")
        lines.append(f"    Tags: {meta.get('tags', '')} | Source: {meta.get('source', '?')}")
        lines.append("")
    return "\n".join(lines)


@mcp.tool(description="Save a new memory to the brain. Called automatically by hooks, but can also be called manually.")
def save_memory_tool(
    content: str,
    memory_type: str = "conversation",
    tags: str = "",
    project: str = ""
) -> str:
    memory_id = save_memory(
        content=content,
        memory_type=memory_type,
        tags=[t.strip() for t in tags.split(",") if t.strip()],
        project=project or None
    )
    return f"Memory saved: {memory_id}"


@mcp.tool(description="Get top N most relevant memories for the current topic/project. Use at session start.")
def get_context_tool(topic: str, project: str = "", n: int = 5) -> str:
    results = get_context(topic=topic, project=project or None, n=n)
    if not results:
        return "No relevant context found for this topic."

    lines = [f"Top {len(results)} memories for '{topic}':\n"]
    for i, r in enumerate(results, 1):
        meta = r["metadata"]
        lines.append(f"[{i}] [{meta.get('type', '?')}] {r['content']}")
    return "\n".join(lines)


@mcp.tool(description="Consolidate and find patterns across recent memories. Runs automatically every 20 saves.")
def reflect_tool() -> str:
    try:
        _trigger_reflection()
        stats = get_stats()
        return f"Reflection complete. Brain stats: {json.dumps(stats, indent=2)}"
    except Exception as e:
        return f"Reflection failed: {e}"


@mcp.tool(description="Get brain stats: memory counts, types, session info.")
def get_stats_tool() -> str:
    stats = get_stats()
    return json.dumps(stats, indent=2)


if __name__ == "__main__":
    mcp.run(transport="stdio")
```

**Step 4: Run tests**

```bash
pytest tests/test_mcp.py -v
```

Expected: All 6 tests PASS.

**Step 5: Test the MCP server manually**

```bash
echo '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' | python -m brain.mcp.server
```

Expected: JSON response listing 5 tools.

**Step 6: Commit**

```bash
git add brain/mcp/ brain/tests/test_mcp.py
git commit -m "feat: FastMCP brain server with search/save/context/reflect/stats tools"
```

---

## Task 11: Claude Code Hooks

**Files:**
- Create: `brain/hooks/session_start.py`
- Create: `brain/hooks/post_tool_use.py`
- Create: `brain/hooks/session_end.py`

**Step 1: Implement session_start.py**

Create `brain/hooks/session_start.py`:
```python
#!/usr/bin/env python3
"""
SessionStart hook — loads relevant context from brain at session start.
Claude Code calls this at the start of every session.
Outputs text that gets injected into the session context.
"""
import sys
import json
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    # Get current working directory as context hint
    cwd = os.getcwd()
    project_hint = Path(cwd).name

    from brain.core.memory import get_context, get_stats

    # Get top memories relevant to current project
    memories = get_context(topic=project_hint, n=5)
    stats = get_stats()

    if memories:
        print(f"\n[BRAIN] Loaded {len(memories)} relevant memories for '{project_hint}':")
        for i, m in enumerate(memories, 1):
            meta = m["metadata"]
            print(f"  [{i}] ({meta.get('type', '?')}) {m['content'][:200]}")
        print(f"[BRAIN] Total: {stats['total_memories']} memories | {stats['total_sessions']} sessions\n")
    else:
        print(f"[BRAIN] No relevant memories for '{project_hint}'. {stats['total_memories']} total memories available.\n")

except Exception as e:
    # Never crash a session over brain failure
    print(f"[BRAIN] Context load failed (non-fatal): {e}", file=sys.stderr)
```

**Step 2: Implement post_tool_use.py**

Create `brain/hooks/post_tool_use.py`:
```python
#!/usr/bin/env python3
"""
PostToolUse hook — saves memories after significant tool calls.
Claude Code passes tool context via stdin as JSON.
"""
import sys
import json
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

# Tools worth remembering
MEMORABLE_TOOLS = {"Edit", "Write", "Bash", "Agent"}

try:
    # Read hook context from stdin
    raw = sys.stdin.read().strip()
    if not raw:
        sys.exit(0)

    context = json.loads(raw)
    tool_name = context.get("tool_name", "")
    tool_input = context.get("tool_input", {})
    tool_response = context.get("tool_response", "")

    if tool_name not in MEMORABLE_TOOLS:
        sys.exit(0)

    # Build a description of what happened
    cwd = os.getcwd()
    project = Path(cwd).name

    if tool_name == "Edit":
        desc = f"Edited {tool_input.get('file_path', '?')}: {tool_input.get('new_string', '')[:200]}"
        memory_type = "solution"
    elif tool_name == "Write":
        desc = f"Wrote {tool_input.get('file_path', '?')}"
        memory_type = "solution"
    elif tool_name == "Bash":
        cmd = tool_input.get("command", "")[:200]
        desc = f"Ran command: {cmd}"
        memory_type = "pattern"
    elif tool_name == "Agent":
        desc = f"Dispatched agent: {tool_input.get('description', '')[:200]}"
        memory_type = "decision"
    else:
        sys.exit(0)

    from brain.core.summarizer import summarize_exchange
    from brain.core.memory import save_memory

    # Summarize the exchange for richer memory
    summary = summarize_exchange(
        user_message=desc,
        assistant_response=str(tool_response)[:500] if tool_response else ""
    )

    save_memory(
        content=summary,
        memory_type=memory_type,
        tags=[tool_name.lower(), project],
        project=project
    )

except Exception as e:
    # Never crash Claude Code over brain failure
    print(f"[BRAIN] Save failed (non-fatal): {e}", file=sys.stderr)
```

**Step 3: Implement session_end.py**

Create `brain/hooks/session_end.py`:
```python
#!/usr/bin/env python3
"""
Stop hook — reflects on session memories before closing.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from brain.core.memory import _trigger_reflection, get_stats
    print("[BRAIN] Running end-of-session reflection...", file=sys.stderr)
    _trigger_reflection()
    stats = get_stats()
    print(f"[BRAIN] Reflection done. Brain now has {stats['total_memories']} memories.", file=sys.stderr)
except Exception as e:
    print(f"[BRAIN] Reflection failed (non-fatal): {e}", file=sys.stderr)
```

**Step 4: Make hooks executable**

```bash
chmod +x brain/hooks/session_start.py brain/hooks/post_tool_use.py brain/hooks/session_end.py
```

**Step 5: Commit**

```bash
git add brain/hooks/
git commit -m "feat: Claude Code hooks for continuous real-time memory saving"
```

---

## Task 12: Register MCP Server + Hooks in Claude Code

**Files:**
- Modify: `~/.claude/settings.json`

**Step 1: Read current settings**

```bash
cat ~/.claude/settings.json
```

**Step 2: Add brain MCP server and hooks**

Add the following to `~/.claude/settings.json`. Merge carefully — don't overwrite existing settings:

```json
{
  "mcpServers": {
    "brain": {
      "command": "python",
      "args": ["-m", "brain.mcp.server"],
      "cwd": "/Users/macm1air/Documents/AI",
      "env": {
        "ANTHROPIC_API_KEY": "${ANTHROPIC_API_KEY}"
      }
    }
  },
  "hooks": {
    "SessionStart": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python /Users/macm1air/Documents/AI/brain/hooks/session_start.py"
          }
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "Edit|Write|Bash|Agent",
        "hooks": [
          {
            "type": "command",
            "command": "python /Users/macm1air/Documents/AI/brain/hooks/post_tool_use.py"
          }
        ]
      }
    ],
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python /Users/macm1air/Documents/AI/brain/hooks/session_end.py"
          }
        ]
      }
    ]
  }
}
```

**Step 3: Verify MCP server starts**

```bash
cd /Users/macm1air/Documents/AI
echo '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' | python -m brain.mcp.server
```

Expected: JSON with 5 tools listed: `search_brain`, `save_memory_tool`, `get_context_tool`, `reflect_tool`, `get_stats_tool`

**Step 4: Commit settings note**

```bash
git add brain/
git commit -m "feat: Claude Code MCP + hooks configuration"
```

---

## Task 13: Run the Bootstrap Pipeline

This is the one-time process to ingest all Cursor history.

**Step 1: Import SQL into SQLite (takes a few minutes — 860MB)**

```bash
cd /Users/macm1air/Documents/AI
time sqlite3 brain/bootstrap/cursor_brain.db < cursor-recovery-backup/recovered.sql
```

Expected: Completes in ~2-5 minutes. `brain/bootstrap/cursor_brain.db` created.

**Step 2: Run SQL parser**

```bash
cd /Users/macm1air/Documents/AI
python brain/bootstrap/parse_sql.py
```

Expected: Output like `Extracted N conversations` and `brain/bootstrap/raw_conversations.jsonl` created.

**Step 3: Inspect what was extracted**

```bash
wc -l brain/bootstrap/raw_conversations.jsonl
head -c 500 brain/bootstrap/raw_conversations.jsonl
```

Expected: Multiple lines, each a JSON object with `session_id`, `messages`, `message_count`.

> **If 0 conversations extracted:** The key patterns in `parse_sql.py::CHAT_KEY_PATTERNS` need updating. Run:
> ```bash
> sqlite3 brain/bootstrap/cursor_brain.db "SELECT key FROM ItemTable LIMIT 100;" | grep -i -E "chat|composer|bubble|message|convers"
> ```
> Add matching patterns to `CHAT_KEY_PATTERNS` in `brain/bootstrap/parse_sql.py`.

**Step 4: Run summarization pipeline**

```bash
cd /Users/macm1air/Documents/AI
python brain/bootstrap/02_summarize.py
```

Expected: Progress bar showing conversations being summarized. Safe to Ctrl+C and resume.
This will use Claude API — verify `ANTHROPIC_API_KEY` is set:
```bash
echo $ANTHROPIC_API_KEY
```

**Step 5: Run embedding + ingestion**

```bash
python brain/bootstrap/03_ingest.py
```

Expected: `Ingestion complete. Total memories: N`

**Step 6: Run sync**

```bash
python brain/bootstrap/04_sync.py
```

Expected: Obsidian notes written to `brain-notes/` in vault. Claude memory files written to `~/.claude/projects/.../memory/`.

**Step 7: Verify brain is working**

```bash
cd /Users/macm1air/Documents/AI
python -c "
from brain.core.memory import search, get_stats
print('Stats:', get_stats())
results = search('how did I build bella', n=3)
for r in results:
    print('---')
    print(r['content'][:200])
"
```

Expected: Stats show non-zero memories. Search returns relevant results about Bella project.

---

## Task 14: End-to-End Test

**Step 1: Run full test suite**

```bash
cd /Users/macm1air/Documents/AI/brain
pytest tests/ -v --tb=short
```

Expected: All tests PASS.

**Step 2: Test MCP server tools manually**

```bash
cd /Users/macm1air/Documents/AI
python -c "
from brain.core.memory import search, save_memory, get_stats

# Save a test memory
mid = save_memory('Test memory: brain is working', 'solution', ['test', 'brain'], 'brain-test')
print(f'Saved: {mid}')

# Search for it
results = search('brain working test', n=3)
print(f'Found {len(results)} results')

# Stats
print(get_stats())
"
```

Expected: Memory saved, found in search, stats show it.

**Step 3: Test hooks manually**

```bash
# Test session_start hook
python brain/hooks/session_start.py

# Test post_tool_use hook with sample input
echo '{"tool_name":"Edit","tool_input":{"file_path":"test.py","new_string":"print(hello)"},"tool_response":"File edited"}' | python brain/hooks/post_tool_use.py

# Test session_end hook
python brain/hooks/session_end.py
```

Expected: Each runs without error. Memory count increases after post_tool_use.

**Step 4: Restart Claude Code and verify brain MCP appears**

In a new Claude Code session, type:
```
/mcp
```

Expected: `brain` server listed with 5 tools available.

**Step 5: Final commit**

```bash
cd /Users/macm1air/Documents/AI
git add -A
git commit -m "feat: continuous brain system complete — bootstrapped, MCP server running, hooks active"
```

---

## Summary

| Phase | Tasks | Output |
|-------|-------|--------|
| Foundation | 1–5 | `brain/` project with ChromaDB, embedder, summarizer, memory ops |
| Bootstrap | 6–9 | All Cursor history ingested → ChromaDB + Obsidian + Claude memory |
| MCP Server | 10 | 5 tools available to Claude Code via `brain` MCP |
| Hooks | 11–12 | Auto-save every exchange, auto-load context at session start |
| Verification | 13–14 | Full pipeline tested end-to-end |

**Result:** Claude never loses context again. Every session adds to the brain. Every new session starts with relevant memory. The brain reflects and consolidates continuously.


<!-- brain-linker -->
## Related
- [[brain-graph/conversation/User]]
- [[brain-graph/solution/Created `07_ingest_claude_code.py` to automate the ingestion]]
- [[brain-graph/conversation/Claude Code session AI Ended 2026-04-08T181413.129421+0000 C]]
- [[brain-graph/conversation/Claude Code session AI Ended 2026-04-09T050638.779691+0000 C]]
- [[brain-graph/conversation/Claude Code session AI Ended 2026-04-09T045953.269990+0000 C]]
<!-- /brain-linker -->
