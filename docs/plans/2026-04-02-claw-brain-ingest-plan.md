# claw-code-main Brain Ingestion Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Ingest claw-code-main into the brain ChromaDB vector store via a single bootstrap script so future sessions can semantically search its architecture and source code.

**Architecture:** A new `brain/bootstrap/claw_extractors.py` module holds three pure extraction functions (AST for Python, regex for Rust, direct parse for JSON). A new `brain/bootstrap/05_ingest_claw.py` script orchestrates all four tiers, calls OpenRouter for markdown summaries, then batch-embeds and upserts everything into ChromaDB with `source="claw_code"`.

**Tech Stack:** Python `ast` stdlib (Python extraction), `re` stdlib (Rust extraction), `json` stdlib (subsystem JSON), `brain.core.summarizer._chat` (OpenRouter markdown summaries), `brain.core.embedder.embed_batch`, `brain.core.db.upsert_memory`, ChromaDB PersistentClient.

---

### Task 1: Create extractor module with Python AST extraction

**Files:**
- Create: `brain/bootstrap/claw_extractors.py`
- Create: `brain/bootstrap/tests/test_claw_extractors.py`

**Step 1: Create the tests directory and write the failing test**

```bash
mkdir -p /Users/macm1air/Documents/AI/brain/bootstrap/tests
touch /Users/macm1air/Documents/AI/brain/bootstrap/tests/__init__.py
```

Then create `brain/bootstrap/tests/test_claw_extractors.py`:

```python
"""Tests for claw-code-main extraction helpers."""
import ast
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from brain.bootstrap.claw_extractors import extract_python_record


def test_extract_python_record_basic(tmp_path):
    src = tmp_path / "example.py"
    src.write_text('''"""Module docstring."""

class Foo:
    """Foo class."""
    pass

def bar(x, y):
    """Bar function."""
    return x + y
''')
    result = extract_python_record(src, base_dir=tmp_path)
    assert result["file_path"] == "example.py"
    assert "Module docstring" in result["text"]
    assert "Foo" in result["text"]
    assert "bar" in result["text"]
    assert result["metadata"]["type"] == "solution"
    assert result["metadata"]["project"] == "claw-code"
    assert result["metadata"]["source"] == "claw_code"


def test_extract_python_record_no_docstring(tmp_path):
    src = tmp_path / "plain.py"
    src.write_text("x = 1\n")
    result = extract_python_record(src, base_dir=tmp_path)
    assert result["file_path"] == "plain.py"
    assert "plain.py" in result["text"]
```

**Step 2: Run tests to verify they fail**

```bash
cd /Users/macm1air/Documents/AI && python -m pytest brain/bootstrap/tests/test_claw_extractors.py -v 2>&1 | head -30
```

Expected: `ModuleNotFoundError: No module named 'brain.bootstrap.claw_extractors'`

**Step 3: Create `brain/bootstrap/claw_extractors.py` with Python extraction**

```python
"""Extraction helpers for claw-code-main source files."""
import ast
import json
import re
import sys
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

CLAW_DIR = Path("/Users/macm1air/Documents/AI/claw-code-main")


def extract_python_record(file_path: Path, base_dir: Path) -> dict:
    """Extract a memory record from a Python source file using AST."""
    rel = str(file_path.relative_to(base_dir))
    try:
        source = file_path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source)
    except SyntaxError:
        return _make_record(rel, f"Python file: {rel} (parse error)", ["python"])

    parts = [f"Python module: {rel}"]

    # Module docstring
    mod_doc = ast.get_docstring(tree)
    if mod_doc:
        parts.append(mod_doc[:300])

    # Classes
    classes = [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
    for cls in classes[:10]:
        doc = ast.get_docstring(cls)
        entry = f"class {cls.name}"
        if doc:
            entry += f": {doc[:150]}"
        parts.append(entry)

    # Top-level functions
    funcs = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    for fn in funcs[:15]:
        args = [a.arg for a in fn.args.args]
        doc = ast.get_docstring(fn)
        entry = f"def {fn.name}({', '.join(args)})"
        if doc:
            entry += f": {doc[:100]}"
        parts.append(entry)

    tags = _tags_from_path(rel)
    return _make_record(rel, " | ".join(parts), tags)


def extract_rust_record(file_path: Path, base_dir: Path) -> dict:
    """Extract a memory record from a Rust source file via regex."""
    rel = str(file_path.relative_to(base_dir))
    try:
        source = file_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return _make_record(rel, f"Rust file: {rel}", ["rust"])

    parts = [f"Rust file: {rel}"]

    # Crate name from path (e.g. rust/crates/runtime/src/session.rs → runtime)
    path_parts = Path(rel).parts
    if "crates" in path_parts:
        crate_idx = list(path_parts).index("crates")
        if crate_idx + 1 < len(path_parts):
            parts.append(f"crate: {path_parts[crate_idx + 1]}")

    # Leading doc comments (/// lines before first non-comment)
    doc_lines = []
    for line in source.splitlines()[:30]:
        stripped = line.strip()
        if stripped.startswith("///"):
            doc_lines.append(stripped[3:].strip())
        elif stripped and not stripped.startswith("//"):
            break
    if doc_lines:
        parts.append(" ".join(doc_lines)[:300])

    # Public items
    pub_items = re.findall(r"^pub\s+(?:async\s+)?(?:fn|struct|enum|trait|type)\s+(\w+)", source, re.MULTILINE)
    if pub_items:
        parts.append("pub: " + ", ".join(pub_items[:20]))

    tags = _tags_from_path(rel) + ["rust"]
    return _make_record(rel, " | ".join(parts), tags)


def extract_json_record(file_path: Path, base_dir: Path) -> dict:
    """Extract a memory record from a reference_data subsystem JSON file."""
    rel = str(file_path.relative_to(base_dir))
    try:
        data = json.loads(file_path.read_text())
    except Exception:
        return _make_record(rel, f"JSON subsystem: {rel}", ["reference"])

    parts = [f"Subsystem: {data.get('archive_name', file_path.stem)}"]
    if "package_name" in data:
        parts.append(f"package: {data['package_name']}")
    if "module_count" in data:
        parts.append(f"{data['module_count']} modules")
    sample = data.get("sample_files", [])
    if sample:
        parts.append("samples: " + ", ".join(Path(s).name for s in sample[:5]))

    return _make_record(rel, " | ".join(parts), ["reference", "subsystem"])


# ── helpers ──────────────────────────────────────────────────────────────────

def _tags_from_path(rel: str) -> list[str]:
    parts = Path(rel).parts
    tags = []
    for p in parts[:-1]:  # skip filename
        if p not in ("src", "crates", "rust", ".", ".."):
            tags.append(p)
    stem = Path(rel).stem
    if stem not in tags:
        tags.append(stem)
    return tags[:6]


def _make_record(file_path: str, text: str, tags: list[str]) -> dict:
    return {
        "file_path": file_path,
        "text": text,
        "metadata": {
            "type": "solution",
            "project": "claw-code",
            "tags": ",".join(tags),
            "source": "claw_code",
            "file_path": file_path,
            "importance": "0.8",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    }
```

**Step 4: Run tests to verify they pass**

```bash
cd /Users/macm1air/Documents/AI && python -m pytest brain/bootstrap/tests/test_claw_extractors.py -v
```

Expected: `2 passed`

**Step 5: Commit**

```bash
cd /Users/macm1air/Documents/AI
git add brain/bootstrap/claw_extractors.py brain/bootstrap/tests/
git commit -m "feat: add claw-code-main extraction helpers (AST, regex, JSON)"
```

---

### Task 2: Add Rust and JSON extraction tests, verify

**Files:**
- Modify: `brain/bootstrap/tests/test_claw_extractors.py`

**Step 1: Add Rust and JSON tests**

Append to `brain/bootstrap/tests/test_claw_extractors.py`:

```python
from brain.bootstrap.claw_extractors import extract_rust_record, extract_json_record


def test_extract_rust_record_pub_items(tmp_path):
    src = tmp_path / "lib.rs"
    src.write_text('''/// Session management module.
/// Handles persisting conversations to disk.

pub struct Session {
    id: String,
}

pub fn save_session(s: &Session) -> Result<(), Error> {
    todo!()
}

pub enum SessionError {
    NotFound,
    IoError,
}
''')
    result = extract_rust_record(src, base_dir=tmp_path)
    assert "Session" in result["text"]
    assert "save_session" in result["text"]
    assert "SessionError" in result["text"]
    assert "Session management" in result["text"]
    assert result["metadata"]["source"] == "claw_code"


def test_extract_json_record_subsystem(tmp_path):
    f = tmp_path / "hooks.json"
    f.write_text('{"archive_name": "hooks", "package_name": "hooks", "module_count": 104, "sample_files": ["hooks/foo.ts"]}')
    result = extract_json_record(f, base_dir=tmp_path)
    assert "hooks" in result["text"]
    assert "104" in result["text"]
    assert result["metadata"]["type"] == "solution"
```

**Step 2: Run all extractor tests**

```bash
cd /Users/macm1air/Documents/AI && python -m pytest brain/bootstrap/tests/test_claw_extractors.py -v
```

Expected: `4 passed`

**Step 3: Commit**

```bash
cd /Users/macm1air/Documents/AI
git add brain/bootstrap/tests/test_claw_extractors.py
git commit -m "test: add Rust and JSON extractor tests"
```

---

### Task 3: Write and run `05_ingest_claw.py`

**Files:**
- Create: `brain/bootstrap/05_ingest_claw.py`

**Step 1: Write the script**

Create `brain/bootstrap/05_ingest_claw.py`:

```python
"""
Ingest claw-code-main into ChromaDB brain vector store.

Tier 1: Markdown docs → OpenRouter summary (6 files, ~6 API calls)
Tier 2: Python source → AST heuristics (no API calls)
Tier 3: Rust source → regex heuristics (no API calls)
Tier 4: Reference JSON → direct parse (no API calls)
"""
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from brain.core.embedder import embed_batch
from brain.core.db import upsert_memory, count_memories
from brain.bootstrap.claw_extractors import (
    extract_python_record,
    extract_rust_record,
    extract_json_record,
    CLAW_DIR,
)

MARKDOWN_FILES = [
    "CLAW.md",
    "README.md",
    "PARITY.md",
    "rust/README.md",
    "rust/CONTRIBUTING.md",
    "rust/docs/releases/0.1.0.md",
]

BATCH_SIZE = 64

MARKDOWN_PROMPT_TEMPLATE = """Analyze this documentation from claw-code-main (a Claude Code reimplementation in Rust/Python).
Extract structured knowledge.

FILE: {filename}

CONTENT:
{content}

Respond with ONLY valid JSON:
{{
  "summary": "2-3 sentence description of what this document covers",
  "topics": ["topic1", "topic2"],
  "decisions": ["key architectural or design decision described"],
  "type": "project_context"
}}"""


def summarize_markdown(file_path: Path) -> dict:
    """Summarize a markdown file via OpenRouter."""
    from brain.core.summarizer import _chat, _parse_json
    content = file_path.read_text(encoding="utf-8", errors="replace")
    prompt = MARKDOWN_PROMPT_TEMPLATE.format(
        filename=file_path.name,
        content=content[:4000],
    )
    raw = _chat(prompt, max_tokens=512)
    data = _parse_json(raw)
    return data


def collect_all_records() -> list[dict]:
    """Collect all memory records from all four tiers."""
    records = []

    # Tier 1: Markdown
    print("Tier 1: Summarizing markdown docs via OpenRouter...")
    for rel_path in MARKDOWN_FILES:
        full_path = CLAW_DIR / rel_path
        if not full_path.exists():
            print(f"  [skip] {rel_path} not found")
            continue
        print(f"  Summarizing {rel_path}...")
        try:
            data = summarize_markdown(full_path)
            parts = [data.get("summary", "")]
            parts += data.get("decisions", [])
            text = " | ".join(filter(None, parts))
            topics = data.get("topics", [])
            from datetime import datetime, timezone
            records.append({
                "file_path": rel_path,
                "text": text,
                "metadata": {
                    "type": data.get("type", "project_context"),
                    "project": "claw-code",
                    "tags": ",".join(topics[:6]),
                    "source": "claw_code",
                    "file_path": rel_path,
                    "importance": "0.9",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            })
        except Exception as e:
            print(f"  [error] {rel_path}: {e}")

    # Tier 2: Python source
    print("\nTier 2: Extracting Python source files...")
    py_files = sorted((CLAW_DIR / "src").rglob("*.py"))
    print(f"  Found {len(py_files)} Python files")
    for f in py_files:
        records.append(extract_python_record(f, CLAW_DIR))

    # Tier 3: Rust source
    print("\nTier 3: Extracting Rust source files...")
    rs_files = sorted((CLAW_DIR / "rust").rglob("*.rs"))
    print(f"  Found {len(rs_files)} Rust files")
    for f in rs_files:
        records.append(extract_rust_record(f, CLAW_DIR))

    # Tier 4: Reference JSON
    print("\nTier 4: Ingesting reference JSON subsystems...")
    json_files = sorted((CLAW_DIR / "src" / "reference_data" / "subsystems").glob("*.json"))
    print(f"  Found {len(json_files)} subsystem files")
    for f in json_files:
        records.append(extract_json_record(f, CLAW_DIR))

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
            mem_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"claw:{record['file_path']}"))
            upsert_memory(mem_id, batch_texts[j], embeddings[j], record["metadata"])
        print(f"  Upserted {min(i + BATCH_SIZE, len(records))}/{len(records)}")


def run():
    before = count_memories()
    print(f"ChromaDB memories before: {before}\n")

    records = collect_all_records()
    print(f"\nTotal records collected: {len(records)}")

    ingest(records)

    after = count_memories()
    print(f"\nDone. Memories: {before} → {after} (+{after - before})")


if __name__ == "__main__":
    run()
```

**Step 2: Dry-run to verify imports work before committing**

```bash
cd /Users/macm1air/Documents/AI && python -c "
import sys
sys.path.insert(0, '.')
from brain.bootstrap.claw_extractors import extract_python_record, CLAW_DIR
print('CLAW_DIR:', CLAW_DIR)
print('Imports OK')
"
```

Expected: `CLAW_DIR: /Users/macm1air/Documents/AI/claw-code-main` and `Imports OK`

**Step 3: Commit**

```bash
cd /Users/macm1air/Documents/AI
git add brain/bootstrap/05_ingest_claw.py
git commit -m "feat: add 05_ingest_claw.py bootstrap script for claw-code-main ingestion"
```

---

### Task 4: Run the ingestion and verify results

**Files:** (none new)

**Step 1: Run the ingestion script**

```bash
cd /Users/macm1air/Documents/AI && OPENROUTER_API_KEY="$OPENROUTER_API_KEY" python brain/bootstrap/05_ingest_claw.py
```

Expected output (approximately):
```
ChromaDB memories before: <N>

Tier 1: Summarizing markdown docs via OpenRouter...
  Summarizing CLAW.md...
  Summarizing README.md...
  ...
Tier 2: Extracting Python source files...
  Found 67 Python files
Tier 3: Extracting Rust source files...
  Found 48 Rust files
Tier 4: Ingesting reference JSON subsystems...
  Found 25 subsystem files

Total records collected: ~146
Embedding 146 records...
  Upserted 64/146
  Upserted 128/146
  Upserted 146/146

Done. Memories: <N> → <N+146> (+146)
```

If any markdown summary fails (OpenRouter error), the script continues — those files are skipped. Re-run is safe; upsert is idempotent (same UUID per file path).

**Step 2: Verify via brain MCP search (manual spot check)**

```bash
cd /Users/macm1air/Documents/AI && python -c "
import sys
sys.path.insert(0, '.')
from brain.core.memory import search
results = search('how does claw handle sessions', n_results=3)
for r in results:
    print('---')
    print(r['document'][:200])
    print('source:', r['metadata'].get('source'))
    print('file:', r['metadata'].get('file_path'))
"
```

Expected: Results with `source: claw_code` and `file_path` containing `session` or `session_store`.

**Step 3: Verify parity doc is searchable**

```bash
cd /Users/macm1air/Documents/AI && python -c "
import sys
sys.path.insert(0, '.')
from brain.core.memory import search
results = search('claw parity with claude code', n_results=3)
for r in results:
    print('source:', r['metadata'].get('source'), '| file:', r['metadata'].get('file_path'))
"
```

Expected: At least one result with `file_path: PARITY.md`.

**Step 4: Final commit**

```bash
cd /Users/macm1air/Documents/AI
git add -p  # review any stray changes
git commit -m "chore: claw-code-main ingestion complete — ~146 memories added to brain"
```


<!-- brain-linker -->
## Related
- [[brain-graph/conversation/User okay. first, let's clarify the claw code files are for ]]
- [[brain-graph/conversation/User]]
- [[brain-graph/project_context/This README introduces an open-source, clean-room reimplemen]]
- [[brain-graph/pattern/Successfully committed `07_ingest_claude_code.py` to the rep]]
- [[brain-graph/solution/Edited Usersmacm1airDocumentsAIbrainbootstrap09_ingest_obsid]]
<!-- /brain-linker -->
