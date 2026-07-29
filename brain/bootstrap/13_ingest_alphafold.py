#!/usr/bin/env python3
"""Ingest AlphaFold repo into Algorithm Space brain."""
import json
import sys
import time
import subprocess
from pathlib import Path
import re

# Add project root to path
script_dir = Path(__file__).resolve().parent
project_root = script_dir.parent.parent
sys.path.insert(0, str(project_root))

from brain.api_client import save_memory, get_stats

REPO_PATH = Path("/tmp/alphafold")
CHECKPOINT = Path(__file__).parent / "checkpoint_alphafold.json"
GITHUB_URL = "https://github.com/deepmind/alphafold"

def load_checkpoint():
    """Load ingestion checkpoint."""
    if CHECKPOINT.exists():
        return json.loads(CHECKPOINT.read_text())
    return {
        "repo_cloned": False,
        "files_processed": 0,
        "memories_saved": 0,
        "components_found": []
    }

def save_checkpoint(state):
    """Save ingestion checkpoint."""
    CHECKPOINT.write_text(json.dumps(state, indent=2))

def clone_repo():
    """Clone AlphaFold repo if not exists."""
    if REPO_PATH.exists():
        print(f"Repo already exists at {REPO_PATH}")
        return True

    print(f"Cloning AlphaFold from {GITHUB_URL}...")
    try:
        subprocess.run(
            ["git", "clone", "--depth", "1", GITHUB_URL, str(REPO_PATH)],
            check=True,
            capture_output=True
        )
        print("Clone successful")
        return True
    except subprocess.CalledProcessError as e:
        print(f"Clone failed: {e}")
        return False

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
    print(f"Extracted {len(docs)} markdown documents")
    return docs

def extract_python_modules():
    """Extract Python modules and their key components."""
    modules = []
    for py_file in REPO_PATH.glob("**/*.py"):
        # Skip __pycache__ and test files
        if "__pycache__" in str(py_file) or py_file.name.startswith("test_"):
            continue

        try:
            content = py_file.read_text(errors="ignore")
            rel_path = py_file.relative_to(REPO_PATH)

            # Extract docstrings
            docstring_pattern = r'"""(.*?)"""'
            docstrings = re.findall(docstring_pattern, content, re.DOTALL)

            # Extract class definitions
            class_pattern = r'class\s+(\w+).*?:'
            classes = re.findall(class_pattern, content)

            # Extract function definitions
            func_pattern = r'def\s+(\w+)\s*\('
            functions = re.findall(func_pattern, content)

            modules.append({
                "path": str(rel_path),
                "type": "python_module",
                "docstrings": docstrings[:3],  # First 3 docstrings
                "classes": classes,
                "functions": functions,
                "content_sample": content[:1000]  # First 1000 chars
            })
        except Exception as e:
            print(f"Error processing {py_file}: {e}")

    print(f"Extracted {len(modules)} Python modules")
    return modules

def identify_algorithms():
    """Identify key algorithms in AlphaFold."""
    algorithms = {
        "structure_prediction": [],
        "attention_variants": [],
        "loss_functions": [],
        "data_processing": [],
        "confidence_estimation": [],
        "geometric_constraints": []
    }

    # Search for key algorithm components
    for py_file in REPO_PATH.glob("**/*.py"):
        if "__pycache__" in str(py_file):
            continue

        try:
            content = py_file.read_text(errors="ignore")
            rel_path = str(py_file.relative_to(REPO_PATH))

            # Structure prediction components
            if any(x in content for x in ["folding", "structure", "inference"]):
                algorithms["structure_prediction"].append(rel_path)

            # Attention mechanisms
            if any(x in content for x in ["attention", "multihead", "self_attention"]):
                algorithms["attention_variants"].append(rel_path)

            # Loss functions
            if any(x in content for x in ["loss", "fape", "violation"]):
                algorithms["loss_functions"].append(rel_path)

            # Data processing (MSA, templates, etc)
            if any(x in content for x in ["msa", "template", "feature", "preprocessing"]):
                algorithms["data_processing"].append(rel_path)

            # Confidence estimation (pTM, pAE, etc)
            if any(x in content for x in ["confidence", "pae", "ptm", "quality"]):
                algorithms["confidence_estimation"].append(rel_path)

            # Geometric constraints (SE3, equivariance, etc)
            if any(x in content for x in ["se3", "equivariant", "rotation", "rigid"]):
                algorithms["geometric_constraints"].append(rel_path)

        except Exception as e:
            continue

    return algorithms

def save_algorithm_memories(algorithms, state):
    """Save identified algorithms as brain memories."""
    for category, files in algorithms.items():
        if not files:
            continue

        memory_content = f"""
AlphaFold {category.replace('_', ' ').title()}

Category: {category}
Files identified: {len(files)}
Components: {', '.join(files[:5])}{'...' if len(files) > 5 else ''}

Key algorithms in this category:
{chr(10).join(f'- {f}' for f in files[:10])}

Domain: Biomolecular structure prediction
Status: Research (AlphaFold3, 2024)
Maturity: Proven architecture, available in multiple implementations

This category covers critical components of AlphaFold's structure prediction pipeline.
"""

        try:
            save_memory(
                content=memory_content,
                memory_type="solution",
                project="algorithms",
                tags=["alphafold", "biomolecular", category, "architecture"],
                title=f"AlphaFold: {category.replace('_', ' ').title()}",
                auto_entities=False,  # bulk ingest: backfill_entities.py links these
            )
            state["memories_saved"] += 1
            print(f"Saved memory for {category}")
            time.sleep(0.1)  # Rate limiting
        except Exception as e:
            print(f"Error saving memory for {category}: {e}")

def save_doc_memories(docs, state):
    """Save documentation as brain memories."""
    for doc in docs:
        if len(doc["content"]) < 100:  # Skip tiny files
            continue

        try:
            title = Path(doc["path"]).stem.replace("_", " ").title()

            save_memory(
                content=f"""
{title}

Source: {doc['path']}
Type: {doc['type']}

Content summary:
{doc['content'][:500]}...

Domain: Biomolecular, AlphaFold
Source: AlphaFold repository documentation
""",
                memory_type="conversation",
                project="algorithms",
                tags=["alphafold", "documentation", "biomolecular"],
                title=f"AlphaFold Docs: {title}",
                auto_entities=False,  # bulk ingest: backfill_entities.py links these
            )
            state["memories_saved"] += 1
            state["files_processed"] += 1
            time.sleep(0.05)  # Rate limiting
        except Exception as e:
            print(f"Error saving doc {doc['path']}: {e}")

def main():
    """Main ingestion pipeline."""
    state = load_checkpoint()

    print("=" * 60)
    print("AlphaFold Repository Ingestion")
    print("=" * 60)

    # Clone repo
    if not state["repo_cloned"]:
        if not clone_repo():
            print("Failed to clone repo")
            return
        state["repo_cloned"] = True
        save_checkpoint(state)

    # Extract components
    print("\nExtracting documentation...")
    docs = extract_markdown_docs()

    print("\nExtracting Python modules...")
    modules = extract_python_modules()

    print("\nIdentifying algorithms...")
    algorithms = identify_algorithms()

    print(f"\nIdentified algorithm categories:")
    for category, files in algorithms.items():
        print(f"  {category}: {len(files)} files")

    state["components_found"] = {k: len(v) for k, v in algorithms.items()}

    # Save to brain
    print("\nSaving to brain...")
    print(f"  Processing {len(docs)} documentation files...")
    save_doc_memories(docs, state)

    print(f"  Processing {len(algorithms)} algorithm categories...")
    save_algorithm_memories(algorithms, state)

    # Save summary
    summary = f"""
AlphaFold Repository Ingestion Complete

Total memories saved: {state['memories_saved']}
Files processed: {state['files_processed']}

Algorithm categories identified:
{chr(10).join(f"- {k}: {v} components" for k, v in state['components_found'].items())}

Documentation extracted:
- Markdown files: {len(docs)}
- Python modules: {len(modules)}

Next steps:
1. Review extracted algorithm components
2. Create detailed algorithm documentation in ALGORITHMS/domains/biomolecular/
3. Update INDEX_BY_PROBLEM, INDEX_BY_PATTERN
4. Map connections to other algorithms (transformers, attention, optimization)
5. Update RELATIONSHIPS.md with biomolecular insights
"""

    print(summary)

    # Save summary to brain
    try:
        save_memory(
            content=summary,
            memory_type="project_context",
            project="algorithms",
            tags=["alphafold", "ingestion-complete", "biomolecular", "research"],
            title="AlphaFold Ingestion Summary",
            auto_entities=False,  # bulk ingest: backfill_entities.py links these
        )
        state["memories_saved"] += 1
    except Exception as e:
        print(f"Error saving summary: {e}")

    save_checkpoint(state)
    print(f"\nCheckpoint saved. Total memories: {state['memories_saved']}")

if __name__ == "__main__":
    main()
