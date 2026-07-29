#!/usr/bin/env python3
"""
Ingest QWorld Hackathon Workshop quantum computing notebooks into brain.

Strategy:
  1. Scan notebooks from /Users/Shared/hackathon-workshop/notebooks/
  2. Parse each notebook (qbronze, qcobalt, qnickel)
  3. Extract sections by ## markdown headers
  4. Preserve notebook origin and section order
  5. Tag by curriculum level (bronze/cobalt/nickel)
  6. Store raw content (no LLM summarization)
  7. Save to brain with project="quantum-computing"

Usage:
    python3 brain/bootstrap/11_ingest_quantum.py
    python3 brain/bootstrap/11_ingest_quantum.py --dry-run
    python3 brain/bootstrap/11_ingest_quantum.py --notebook "path/to/notebook.ipynb"
"""

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from brain.api_client import save_memory, get_stats
from brain.ingest.payloads import with_ingest_tag


NOTEBOOKS_DIR = Path("/Users/Shared/hackathon-workshop/notebooks")
CHECKPOINT_PATH = Path(__file__).parent / "checkpoint_quantum.json"

# Map curriculum directory to level
CURRICULUM_LEVELS = {
    "qbronze": "bronze",
    "qcobalt": "cobalt",
    "qnickel": "nickel",
}


def _load_checkpoint() -> dict[str, bool]:
    """Load which notebooks have been ingested."""
    if CHECKPOINT_PATH.exists():
        return json.loads(CHECKPOINT_PATH.read_text())
    return {}


def _save_checkpoint(data: dict[str, bool]) -> None:
    """Save ingested notebook list."""
    CHECKPOINT_PATH.write_text(json.dumps(data, indent=2))


def _extract_sections(notebook_path: Path, notebook_name: str) -> list[dict[str, Any]]:
    """
    Extract sections from notebook grouped by ## headers.

    Returns list of dicts with:
      - title: section title from ## header (or "Introduction" if starts with markdown)
      - notebook: notebook filename
      - notebook_path: relative path for reference
      - content: markdown + code cells in this section
      - order: sequence number
    """
    with open(notebook_path) as f:
        nb = json.load(f)

    sections = []
    current_section = None
    section_order = 0

    for cell in nb.get("cells", []):
        cell_type = cell.get("cell_type")
        source = "".join(cell.get("source", []))

        # Detect ## headers (section boundaries)
        if cell_type == "markdown" and source.strip().startswith("##"):
            # Save previous section if exists
            if current_section is not None:
                sections.append(current_section)

            # Start new section
            title = source.strip().lstrip("#").strip()
            section_order += 1
            current_section = {
                "title": title,
                "notebook": notebook_name,
                "notebook_path": str(notebook_path.relative_to(NOTEBOOKS_DIR)),
                "content": [{"type": "markdown", "source": source}],
                "order": section_order,
            }
        elif current_section is not None:
            # Add cell to current section
            if cell_type == "markdown":
                current_section["content"].append({"type": "markdown", "source": source})
            elif cell_type == "code":
                current_section["content"].append({"type": "code", "source": source})
        else:
            # Before first ## header - create "Introduction" section
            if cell_type in ("markdown", "code"):
                if current_section is None or current_section["title"] != "Introduction":
                    if current_section is not None:
                        sections.append(current_section)
                    section_order += 1
                    current_section = {
                        "title": "Introduction",
                        "notebook": notebook_name,
                        "notebook_path": str(notebook_path.relative_to(NOTEBOOKS_DIR)),
                        "content": [],
                        "order": section_order,
                    }

                if cell_type == "markdown":
                    current_section["content"].append({"type": "markdown", "source": source})
                elif cell_type == "code":
                    current_section["content"].append({"type": "code", "source": source})

    # Save last section
    if current_section is not None:
        sections.append(current_section)

    return sections


def _save_memory_with_retry(
    content: str,
    memory_type: str,
    title: str,
    tags: list[str],
    project: str,
    source: str,
    max_retries: int = 3,
    initial_wait: float = 0.5,
) -> bool:
    """Save memory with exponential backoff retry logic."""
    wait_time = initial_wait

    for attempt in range(max_retries):
        try:
            save_memory(
                content=content,
                memory_type=memory_type,
                title=title,
                tags=tags,
                project=project,
                source=source,
                auto_entities=False,  # bulk ingest: backfill_entities.py links these
            )
            return True
        except Exception as e:
            if "429" in str(e) or "rate limit" in str(e).lower():
                if attempt < max_retries - 1:
                    print(f"      ⏳ Rate limited, retrying in {wait_time}s...")
                    time.sleep(wait_time)
                    wait_time *= 2  # exponential backoff
                else:
                    print(f"      ✗ Failed after {max_retries} retries: {e}")
                    return False
            else:
                print(f"      ✗ Error: {e}")
                return False

    return False


def _format_section_content(section: dict[str, Any]) -> str:
    """Format section content for storage."""
    lines = [f"# {section['title']}"]
    lines.append(f"**Notebook:** {section['notebook_path']}")
    lines.append("")

    for item in section["content"]:
        if item["type"] == "markdown":
            lines.append(item["source"])
        elif item["type"] == "code":
            lines.append("```python")
            lines.append(item["source"])
            lines.append("```")

    return "\n".join(lines)


def _detect_curriculum_level(notebook_path: Path) -> str | None:
    """Detect curriculum level from path (bronze/cobalt/nickel)."""
    for part, level in CURRICULUM_LEVELS.items():
        if part in notebook_path.parts:
            return level
    return None


def _get_notebook_topic(notebook_name: str) -> str:
    """Extract topic from notebook name."""
    name = notebook_name.replace(".ipynb", "").lower()
    # Remove common prefixes
    for prefix in ["qb", "qc", "qn", "qworld", "quiz"]:
        if name.startswith(prefix):
            name = name[len(prefix):].lstrip("_")
    return name or "quantum-computing"


def ingest_quantum_notebooks(dry_run: bool = False, only_notebook: Path | None = None) -> int:
    """Ingest all quantum notebooks."""
    checkpoint = _load_checkpoint()
    saved_count = 0

    if not NOTEBOOKS_DIR.exists():
        print(f"Error: notebooks directory not found: {NOTEBOOKS_DIR}")
        return 0

    # Find all notebooks
    notebooks = sorted(NOTEBOOKS_DIR.rglob("*.ipynb"))

    if only_notebook:
        notebooks = [only_notebook] if only_notebook.exists() else []

    print(f"Found {len(notebooks)} notebooks to process\n")

    for nb_path in notebooks:
        nb_name = nb_path.name

        # Skip if already ingested
        if checkpoint.get(str(nb_path)) and not only_notebook:
            continue

        try:
            print(f"Processing: {nb_path.relative_to(NOTEBOOKS_DIR)}")

            # Extract sections
            sections = _extract_sections(nb_path, nb_name)
            print(f"  → Extracted {len(sections)} sections")

            if dry_run:
                for section in sections:
                    print(f"    - {section['order']}: {section['title']}")
                checkpoint[str(nb_path)] = True
                continue

            # Detect curriculum level
            level = _detect_curriculum_level(nb_path)
            topic = _get_notebook_topic(nb_name)

            # Save each section as a memory
            for section in sections:
                content = _format_section_content(section)

                # Build tags
                tags = ["quantum-computing", topic]
                if level:
                    tags.append(level)

                # Build title
                title = f"[{level or 'quantum'} - {nb_name}] {section['title']}"

                # Save with retry logic
                if _save_memory_with_retry(
                    content=content,
                    memory_type="solution",  # Quantum learning material
                    title=title,
                    tags=with_ingest_tag(tags),
                    project="quantum-computing",
                    source="quantum-notebook-ingest",
                ):
                    saved_count += 1
                    time.sleep(0.1)  # Small delay between saves to avoid rate limiting

            # Mark notebook as processed
            checkpoint[str(nb_path)] = True

        except Exception as e:
            print(f"  ✗ Error processing {nb_name}: {e}")

    # Save checkpoint
    _save_checkpoint(checkpoint)

    before = get_stats().get("total_memories", 0)
    print(f"\n✓ Ingested {saved_count} quantum sections")
    print(f"Total brain memories: {before}")

    return saved_count


def main():
    parser = argparse.ArgumentParser(description="Ingest quantum computing notebooks")
    parser.add_argument("--dry-run", action="store_true", help="Preview sections without saving")
    parser.add_argument("--notebook", type=Path, help="Ingest single notebook")
    parser.add_argument("--reset", action="store_true", help="Reset checkpoint and re-ingest all")

    args = parser.parse_args()

    if args.reset:
        CHECKPOINT_PATH.unlink(missing_ok=True)
        print("Checkpoint reset. Will re-ingest all notebooks.")

    ingest_quantum_notebooks(dry_run=args.dry_run, only_notebook=args.notebook)


if __name__ == "__main__":
    main()
