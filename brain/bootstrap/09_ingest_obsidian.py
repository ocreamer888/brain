"""
Ingest Obsidian vault (projects, areas, resources, maps) into the Rust brain API.

Canonical vault copy: ``<repo>/vault/`` (full tree rsync'd from the old external vault;
no symlink — override with env ``OBSIDIAN_VAULT_PATH`` if needed).

Skips: Books/, 00 Inbox/, copilot/custom-prompts/, Templates/, Nodes/,
       .obsidian/, .smart-env/, empty files (<50 words).

``02 Areas/`` is ingested (ongoing responsibilities — not skipped).

For large files (word count above ``OBSIDIAN_CHUNK_WORDS``, default 1500): chunk by
``##`` headers (strategy ``headers``) or merged paragraphs (strategy ``paragraph``).
For small/medium files: store as single memory.

Env:

- ``OBSIDIAN_CHUNK_WORDS`` — integer threshold (default ``1500``).
- ``OBSIDIAN_CHUNK_STRATEGY`` — ``headers`` (default) or ``paragraph``.

Usage:
    python3 brain/bootstrap/09_ingest_obsidian.py
    python3 brain/bootstrap/09_ingest_obsidian.py --dry-run
"""
import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))

from brain.api_client import save_memory, get_stats, BrainApiError
from brain.ingest.payloads import (
    format_bracketed_memory,
    memory_display_title,
    with_ingest_tag,
)
from brain.ingest.text_chunking import (
    chunk_by_paragraphs,
    chunk_by_sections,
    normalize_section_title,
    refine_chunks_for_word_limit,
)


def vault_repo_relpath(vault_file: Path) -> str:
    """POSIX path under repo: ``vault/<relative-to-vault>``."""
    rel = vault_file.resolve().relative_to(VAULT.resolve())
    return (Path("vault") / rel).as_posix()


def save_with_retry(
    content,
    memory_type,
    tags,
    project,
    source,
    session_id,
    *,
    file_path=None,
    title=None,
):
    for attempt in range(6):
        try:
            save_memory(
                content=content,
                memory_type=memory_type,
                tags=tags,
                project=project,
                source=source,
                session_id=session_id,
                file_path=file_path,
                title=title,
                auto_entities=False,  # bulk ingest: backfill_entities.py links these
            )
            time.sleep(0.4)  # gentle pacing — don't overwhelm the Rust API
            return
        except BrainApiError as e:
            if ("429" in str(e) or "503" in str(e)) and attempt < 5:
                wait = 2 ** attempt
                print(f"    [api wait {wait}s]")
                time.sleep(wait)
            else:
                raise
        except Exception as e:
            if attempt < 5:
                wait = 2 ** attempt
                print(f"    [retry {attempt+1} after {wait}s: {e}]")
                time.sleep(wait)
            else:
                raise

VAULT = Path(
    os.environ.get("OBSIDIAN_VAULT_PATH", str(_REPO_ROOT / "vault"))
).resolve()


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


CHUNK_WORD_THRESHOLD = max(200, _int_env("OBSIDIAN_CHUNK_WORDS", 1500))
_s = os.environ.get("OBSIDIAN_CHUNK_STRATEGY", "headers").strip().lower()
CHUNK_STRATEGY = _s if _s in ("headers", "paragraph") else "headers"

CHECKPOINT_PATH = Path(__file__).parent / "checkpoint_obsidian.json"

# Directories to skip entirely
SKIP_DIRS = {
    ".obsidian", ".smart-env", "Books", "00 Inbox",
    "copilot-custom-prompts", "Templates", "Nodes",
}

# Map vault path segments to brain project names
PROJECT_MAP = {
    "LIFEHUB": "lifehub",
    "Wealth": "wealth",
    "Le Chandelier": "le_chandelier",
    "MedDeFi": "meddefi",
    "OCREAMER STUDIO": "ocreamer",
    "OWELIGN": "owelign",
    "QOL": "qol",
    "RMT Soluciones": "rmt",
    "SICOP Health Intelligence": "sicop",
    "Scheduler App": "scheduler",
    "Tayasal": "tayasal",
    "Inventario App": "inventario",
}

# Map top-level vault dirs to memory types and base tags
DIR_TYPE_MAP = {
    "01 Projects": ("project_context", ["obsidian_project"]),
    "02 Areas":    ("solution",         ["obsidian_area"]),
    "03 Resources":("solution",         ["obsidian_resource"]),
    "Maps":        ("solution",         ["obsidian_map"]),
    "docs":        ("decision",         ["obsidian_docs"]),
    "04 Archive":  ("solution",         ["obsidian_archive"]),
    "copilot":     ("conversation",     ["obsidian_copilot"]),
    "Home.md":     ("solution",         ["obsidian_home"]),
}


def should_skip(path: Path) -> bool:
    for part in path.parts:
        if part in SKIP_DIRS:
            return True
    return False


def detect_project(path: Path) -> str:
    """Extract project name from path if inside 01 Projects/."""
    parts = path.parts
    for i, part in enumerate(parts):
        if part == "01 Projects" and i + 1 < len(parts):
            project_dir = parts[i + 1]
            return PROJECT_MAP.get(project_dir, project_dir.lower().replace(" ", "_"))
    return "general"


def detect_type_and_tags(path: Path) -> tuple[str, list[str], str]:
    """Return (memory_type, tags, project) based on vault path."""
    rel = path.relative_to(VAULT)
    top = rel.parts[0] if rel.parts else ""

    memory_type, base_tags = DIR_TYPE_MAP.get(top, ("solution", ["obsidian"]))
    tags = list(base_tags)
    project = detect_project(path)

    # Add resource subcategory tag
    if top == "03 Resources" and len(rel.parts) > 1:
        category = rel.parts[1].lower().replace(" ", "_")
        tags.append(f"resource/{category}")

    # Add area tag
    if top == "02 Areas" and len(rel.parts) > 1:
        area = rel.parts[1].lower().replace(" ", "_")
        tags.append(f"area/{area}")

    # Add project tag
    if top == "01 Projects" and len(rel.parts) > 1:
        proj = rel.parts[1]
        tags.append(f"project/{PROJECT_MAP.get(proj, proj.lower().replace(' ', '_'))}")

    return memory_type, tags, project


def clean_obsidian(text: str) -> str:
    """Strip Obsidian-specific syntax noise."""
    # Remove wikilinks [[...]] -> keep display text
    text = re.sub(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]", r"\1", text)
    # Remove frontmatter
    text = re.sub(r"^---\n.*?\n---\n", "", text, flags=re.DOTALL)
    # Remove empty callouts
    text = re.sub(r"^>\s*$", "", text, flags=re.MULTILINE)
    # Collapse blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def collect_files() -> list[Path]:
    files = []
    for f in VAULT.rglob("*.md"):
        if should_skip(f):
            continue
        files.append(f)
    return sorted(files)


def load_checkpoint() -> set:
    if CHECKPOINT_PATH.exists():
        return set(json.loads(CHECKPOINT_PATH.read_text()).get("processed", []))
    return set()


def save_checkpoint(processed: set):
    CHECKPOINT_PATH.write_text(json.dumps({"processed": list(processed)}))


def ingest_file(path: Path, processed: set, dry_run: bool) -> int:
    file_key = str(path.relative_to(VAULT))
    if file_key in processed:
        return 0

    content = path.read_text(encoding="utf-8", errors="replace")
    content = clean_obsidian(content)
    word_count = len(content.split())

    if word_count < 50:
        # Empty template — skip and mark done
        processed.add(file_key)
        return 0

    memory_type, tags, project = detect_type_and_tags(path)
    note_stem = path.stem
    fp = vault_repo_relpath(path)
    source_tag = f"file/{str(path.relative_to(VAULT)).replace(' ', '_')}"
    tags = with_ingest_tag(tags + ["source/obsidian", source_tag])

    if word_count > CHUNK_WORD_THRESHOLD:
        if CHUNK_STRATEGY == "paragraph":
            tw = max(400, CHUNK_WORD_THRESHOLD // 2)
            raw_chunks = chunk_by_paragraphs(content, note_stem, target_words=tw)
        else:
            raw_chunks = chunk_by_sections(content, note_stem)
    else:
        raw_chunks = [(note_stem, content)]

    chunks = refine_chunks_for_word_limit(
        raw_chunks, note_stem, word_threshold=CHUNK_WORD_THRESHOLD
    )

    saved = 0
    for i, (section_title, body) in enumerate(chunks):
        chunk_key = f"{file_key}::{i}" if len(chunks) > 1 else file_key
        if chunk_key in processed:
            continue
        section_title = normalize_section_title(note_stem, section_title)
        memory_text = format_bracketed_memory(note_stem, section_title, body)
        mem_title = memory_display_title(note_stem, section_title)
        if not dry_run:
            save_with_retry(
                content=memory_text,
                memory_type=memory_type,
                tags=tags,
                project=project,
                source="obsidian",
                session_id=f"obsidian_{path.stem}_{i}",
                file_path=fp,
                title=mem_title,
            )
        else:
            print(
                f"    DRY: [{memory_type}] {note_stem} / {section_title[:50]} ({len(body.split())}w)"
            )
        processed.add(chunk_key)
        saved += 1

    return saved


def run(dry_run: bool = False):
    files = collect_files()
    print(
        f"Found {len(files)} obsidian files (chunk_if_words>{CHUNK_WORD_THRESHOLD}, "
        f"strategy={CHUNK_STRATEGY})"
    )

    processed = load_checkpoint()
    before = get_stats().get("total_memories", 0)
    total_saved = 0

    for i, f in enumerate(files):
        rel = str(f.relative_to(VAULT))
        n = ingest_file(f, processed, dry_run)
        if n > 0:
            print(f"  [{i+1}/{len(files)}] +{n} — {rel[:70]}")
        if (i + 1) % 20 == 0 and not dry_run:
            save_checkpoint(processed)
        total_saved += n

    if not dry_run:
        save_checkpoint(processed)

    after = get_stats().get("total_memories", before)
    label = "DRY RUN" if dry_run else "Done"
    print(f"\n{label}. Saved={total_saved}. Brain: {before} -> {after} (+{after - before})")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Show what would be ingested without saving")
    args = parser.parse_args()
    run(dry_run=args.dry_run)
