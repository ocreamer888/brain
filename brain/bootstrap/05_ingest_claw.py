"""
Ingest claw-code-main into Rust brain API.

Tier 1: Markdown docs → OpenRouter summary (6 files, ~6 API calls)
Tier 2: Python source → AST heuristics (no API calls)
Tier 3: Rust source → regex heuristics (no API calls)
Tier 4: Reference JSON → direct parse (no API calls)
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from brain.api_client import save_memory, get_stats
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


def run():
    before = get_stats().get("total_memories", 0)
    print(f"Rust API memories before: {before}\n")

    records = collect_all_records()
    print(f"\nTotal records collected: {len(records)}")

    saved = 0
    for record in records:
        tags = [
            t.strip()
            for t in str(record["metadata"].get("tags", "")).split(",")
            if t.strip()
        ]
        save_memory(
            content=record["text"],
            memory_type=record["metadata"].get("type", "project_context"),
            tags=tags,
            project=record["metadata"].get("project", "claw-code"),
            source=record["metadata"].get("source", "claw_code"),
            timestamp=record["metadata"].get("timestamp"),
            auto_entities=False,  # bulk ingest: backfill_entities.py links these
        )
        saved += 1

    after = get_stats().get("total_memories", before)
    print(f"\nDone. Saved={saved}. Rust memories: {before} -> {after} (+{after - before})")


if __name__ == "__main__":
    run()
