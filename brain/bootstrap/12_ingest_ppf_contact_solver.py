#!/usr/bin/env python3
"""Ingest ppf-contact-solver repo into brain."""
import json
import sys
import time
from pathlib import Path
import re

# Add project root to path
script_dir = Path(__file__).resolve().parent
project_root = script_dir.parent.parent
sys.path.insert(0, str(project_root))

from brain.api_client import save_memory, get_stats

REPO_PATH = Path("/tmp/ppf-contact-solver")
CHECKPOINT = Path(__file__).parent / "checkpoint_ppf.json"


def load_checkpoint():
    """Load ingestion checkpoint."""
    if CHECKPOINT.exists():
        return json.loads(CHECKPOINT.read_text())
    return {"files_processed": 0, "memories_saved": 0}


def save_checkpoint(state):
    """Save ingestion checkpoint."""
    CHECKPOINT.write_text(json.dumps(state, indent=2))


def extract_markdown_docs():
    """Extract all markdown documentation."""
    docs = []
    for md_file in REPO_PATH.glob("**/*.md"):
        try:
            content = md_file.read_text(errors="ignore")
            rel_path = md_file.relative_to(REPO_PATH)
            docs.append({
                "path": str(rel_path),
                "content": content,
                "type": "documentation"
            })
        except Exception as e:
            print(f"Error reading {md_file}: {e}")
    return docs


def extract_python_apis():
    """Extract Python API code and docstrings."""
    apis = []
    for py_file in (REPO_PATH / "frontend").glob("**/*.py"):
        try:
            content = py_file.read_text(errors="ignore")
            rel_path = py_file.relative_to(REPO_PATH)

            # Extract class docstrings
            class_pattern = r'class\s+(\w+)[^:]*:\s*"""(.*?)"""'
            for match in re.finditer(class_pattern, content, re.DOTALL):
                apis.append({
                    "path": str(rel_path),
                    "class": match.group(1),
                    "docstring": match.group(2).strip(),
                    "type": "python_api"
                })

            # Extract function docstrings
            func_pattern = r'def\s+(\w+)\([^)]*\)[^:]*:\s*"""(.*?)"""'
            for match in re.finditer(func_pattern, content, re.DOTALL):
                apis.append({
                    "path": str(rel_path),
                    "function": match.group(1),
                    "docstring": match.group(2).strip(),
                    "type": "python_api"
                })
        except Exception as e:
            print(f"Error extracting from {py_file}: {e}")
    return apis


def extract_examples():
    """Extract example notebooks descriptions."""
    examples = []
    for nb_file in (REPO_PATH / "examples").glob("*.ipynb"):
        try:
            nb_data = json.loads(nb_file.read_text())
            name = nb_file.stem

            # Extract markdown cells as description
            markdown_cells = []
            for cell in nb_data.get("cells", []):
                if cell.get("cell_type") == "markdown":
                    markdown_cells.append("".join(cell.get("source", [])))

            if markdown_cells:
                examples.append({
                    "name": name,
                    "description": "\n".join(markdown_cells[:3]),  # First 3 markdown cells
                    "type": "example"
                })
        except Exception as e:
            print(f"Error reading {nb_file}: {e}")
    return examples


def extract_key_concepts():
    """Extract key technical concepts from docs."""
    concepts = []

    # From README
    readme = REPO_PATH / "README.md"
    if readme.exists():
        content = readme.read_text()

        # Highlights section
        if "Highlights" in content:
            section = content.split("Highlights")[1].split("##")[0]
            concepts.append({
                "topic": "Key Features",
                "content": section.strip(),
                "type": "concept"
            })

    # From docs directory
    for doc_file in (REPO_PATH / "docs").glob("**/*.md"):
        try:
            content = doc_file.read_text()
            name = doc_file.stem
            concepts.append({
                "topic": name.replace("_", " ").title(),
                "content": content[:1000],  # First 1000 chars
                "type": "concept",
                "file": str(doc_file.relative_to(REPO_PATH))
            })
        except Exception as e:
            print(f"Error reading doc {doc_file}: {e}")

    return concepts


def chunk_text(text, max_length=2000):
    """Split text into chunks."""
    if len(text) <= max_length:
        return [text]

    chunks = []
    current = ""
    for paragraph in text.split("\n\n"):
        if len(current) + len(paragraph) > max_length:
            if current:
                chunks.append(current)
            current = paragraph
        else:
            current += "\n\n" + paragraph if current else paragraph
    if current:
        chunks.append(current)
    return chunks


def ingest_all():
    """Main ingestion function."""
    if not REPO_PATH.exists():
        print(f"Repo not found at {REPO_PATH}")
        sys.exit(1)

    state = load_checkpoint()
    before = get_stats().get("total_memories", 0)

    print("=" * 60)
    print("Ingesting ppf-contact-solver")
    print("=" * 60)

    # Extract all content
    print("\n[1/4] Extracting markdown documentation...")
    docs = extract_markdown_docs()
    print(f"  Found {len(docs)} markdown files")

    print("[2/4] Extracting Python APIs...")
    apis = extract_python_apis()
    print(f"  Found {len(apis)} API definitions")

    print("[3/4] Extracting examples...")
    examples = extract_examples()
    print(f"  Found {len(examples)} examples")

    print("[4/4] Extracting key concepts...")
    concepts = extract_key_concepts()
    print(f"  Found {len(concepts)} concepts")

    # Ingest documentation
    print("\n[INGEST] Saving documentation...")
    for doc in docs:
        for chunk in chunk_text(doc["content"]):
            save_memory(
                content=chunk,
                memory_type="conversation",
                tags=["ppf-contact-solver", "documentation", doc["path"].replace("/", "-")],
                project="ppf-contact-solver",
                source="ppf_contact_solver_repo",
                auto_entities=False,  # bulk ingest: backfill_entities.py links these
            )
            time.sleep(0.1)  # Rate limit
        state["files_processed"] += 1

    # Ingest APIs
    print("[INGEST] Saving Python APIs...")
    for api in apis:
        title = api.get("class") or api.get("function")
        content = f"PPF Contact Solver API: {title}\n\n{api['docstring']}\n\nLocation: {api['path']}"
        save_memory(
            content=content,
            memory_type="solution",
            tags=["ppf-contact-solver", "python-api", title.lower()],
            project="ppf-contact-solver",
            source="ppf_contact_solver_repo",
            auto_entities=False,  # bulk ingest: backfill_entities.py links these
        )
        state["memories_saved"] += 1
        time.sleep(0.05)  # Rate limit

    # Ingest examples
    print("[INGEST] Saving examples...")
    for example in examples:
        content = f"PPF Example: {example['name']}\n\n{example['description']}"
        save_memory(
            content=content,
            memory_type="conversation",
            tags=["ppf-contact-solver", "example", example["name"].lower()],
            project="ppf-contact-solver",
            source="ppf_contact_solver_repo",
            auto_entities=False,  # bulk ingest: backfill_entities.py links these
        )
        state["memories_saved"] += 1
        time.sleep(0.05)  # Rate limit

    # Ingest concepts
    print("[INGEST] Saving technical concepts...")
    for concept in concepts:
        for chunk in chunk_text(concept["content"]):
            save_memory(
                content=f"{concept['topic']}:\n\n{chunk}",
                memory_type="pattern",
                tags=["ppf-contact-solver", "concept", concept["topic"].lower().replace(" ", "-")],
                project="ppf-contact-solver",
                source="ppf_contact_solver_repo",
                auto_entities=False,  # bulk ingest: backfill_entities.py links these
            )
            state["memories_saved"] += 1
            time.sleep(0.05)  # Rate limit

    after = get_stats().get("total_memories", before)
    state["memories_saved"] = after - before
    save_checkpoint(state)

    print("\n" + "=" * 60)
    print(f"✅ Ingestion complete")
    print(f"  Files processed: {state['files_processed']}")
    print(f"  Memories saved: {after - before}")
    print(f"  Total memories: {before} → {after}")
    print("=" * 60)


if __name__ == "__main__":
    ingest_all()
