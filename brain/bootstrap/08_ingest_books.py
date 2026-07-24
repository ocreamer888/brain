"""
Ingest books from obsidian-brain into the Rust brain API.

Each book is chunked by chapter/section (## headers).
LLM extracts core principles/insights per chunk — raw OCR text is NOT stored.
Each chunk = one memory of type 'solution' with book-specific tags.

Usage:
    python brain/bootstrap/08_ingest_books.py
    python brain/bootstrap/08_ingest_books.py --no-llm   # store raw chunk summaries
    python brain/bootstrap/08_ingest_books.py --book "The War of Art"  # single book
"""
import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

import requests

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))

from brain.api_client import save_memory, get_stats
from brain.ingest.payloads import with_ingest_tag


BOOKS_DIR = Path(
    os.environ.get(
        "OBSIDIAN_BOOKS_DIR",
        str(_REPO_ROOT / "vault" / "03 Resources" / "Books"),
    )
).resolve()
CHECKPOINT_PATH = Path(__file__).parent / "checkpoint_books.json"

# Topic tags auto-detected from filename keywords
TOPIC_MAP = {
    "persuasion": ["psychology", "influence", "persuasion"],
    "covert": ["psychology", "influence", "persuasion"],
    "meditaciones": ["philosophy", "stoicism", "marcus_aurelius"],
    "marco aurelio": ["philosophy", "stoicism", "marcus_aurelius"],
    "carnegie": ["psychology", "relationships", "communication"],
    "ganar amigos": ["psychology", "relationships", "communication"],
    "psicópatas": ["psychology", "human_behavior"],
    "psicopatas": ["psychology", "human_behavior"],
    "libertad financiera": ["finance", "personal_finance"],
    "pasos": ["finance", "personal_finance"],
    "war of art": ["creativity", "productivity", "resistance"],
    "castaneda": ["philosophy", "spirituality", "shamanism"],
    "don juan": ["philosophy", "spirituality", "shamanism"],
    "werther": ["literature", "classics"],
    "mein kampf": ["history", "politics"],
    "arturo": ["literature", "mythology"],
    "excalibur": ["literature", "mythology"],
    "diario": ["history", "exploration"],
    "descubrimiento": ["history", "exploration"],
}


def detect_topics(filename: str) -> list[str]:
    name_lower = filename.lower()
    topics = []
    for keyword, tags in TOPIC_MAP.items():
        if keyword in name_lower:
            for t in tags:
                if t not in topics:
                    topics.append(t)
    return topics if topics else ["self_development"]


def slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "_", text)
    return text[:60]


def clean_text(text: str) -> str:
    """Strip OCR noise: page markers, URLs, page numbers."""
    # Remove <!-- Página N --> markers
    text = re.sub(r"<!--\s*P[áa]gina\s*\d+\s*-->", "", text)
    # Remove www.* URLs on their own line
    text = re.sub(r"^\s*www\.\S+\s*$", "", text, flags=re.MULTILINE)
    # Remove standalone page numbers
    text = re.sub(r"^\s*\d+\s*$", "", text, flags=re.MULTILINE)
    # Remove horizontal rules that are just noise
    text = re.sub(r"^\s*---+\s*$", "", text, flags=re.MULTILINE)
    # Collapse multiple blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def chunk_by_pages(content: str, pages_per_chunk: int = 15) -> list[tuple[str, str]]:
    """
    Split OCR'd markdown into chunks by grouping N pages together.
    These books are raw PDF exports — ## headers are OCR artifacts, not real chapters.
    Page markers (<!-- Página N -->) are the reliable structural signal.
    Returns list of (label, body) tuples.
    """
    # Split on page markers
    page_pattern = re.compile(r"<!--\s*P[áa]gina\s*(\d+)\s*-->")
    parts = page_pattern.split(content)

    # parts alternates: [pre_content, page_num, page_content, page_num, page_content, ...]
    pages = []
    if parts[0].strip():
        pages.append((0, parts[0]))  # content before first page marker

    i = 1
    while i < len(parts) - 1:
        page_num = int(parts[i])
        page_content = parts[i + 1] if i + 1 < len(parts) else ""
        pages.append((page_num, page_content))
        i += 2

    if not pages:
        # No page markers — fall back to word-count windowing
        return chunk_by_words(content)

    # Group into chunks of N pages
    chunks = []
    for start in range(0, len(pages), pages_per_chunk):
        group = pages[start:start + pages_per_chunk]
        page_nums = [p[0] for p in group if p[0] > 0]
        body = clean_text("\n\n".join(p[1] for p in group))
        if len(body.split()) < 80:
            continue
        if page_nums:
            label = f"Pages {page_nums[0]}–{page_nums[-1]}"
        else:
            label = f"Section {start + 1}"
        chunks.append((label, body))

    return chunks


def chunk_by_words(content: str, target_words: int = 600) -> list[tuple[str, str]]:
    """Fallback: chunk by paragraph groups when no page markers exist."""
    paragraphs = re.split(r"\n{2,}", content)
    chunks = []
    current = []
    count = 0
    chunk_num = 1

    for para in paragraphs:
        w = len(para.split())
        current.append(para)
        count += w
        if count >= target_words:
            body = clean_text("\n\n".join(current))
            if len(body.split()) > 80:
                chunks.append((f"Section {chunk_num}", body))
                chunk_num += 1
            current = []
            count = 0

    if current:
        body = clean_text("\n\n".join(current))
        if len(body.split()) > 80:
            chunks.append((f"Section {chunk_num}", body))

    return chunks


def split_large_chunk(title: str, body: str, max_words: int = 2500) -> list[tuple[str, str]]:
    """Split oversized chunks at paragraph boundaries."""
    words = body.split()
    if len(words) <= max_words:
        return [(title, body)]

    paragraphs = body.split("\n\n")
    result = []
    part_words = []
    part_num = 1

    for para in paragraphs:
        part_words.append(para)
        if len(" ".join(part_words).split()) >= max_words:
            result.append((f"{title} (part {part_num})", "\n\n".join(part_words)))
            part_words = []
            part_num += 1

    if part_words:
        result.append((f"{title} (part {part_num})", "\n\n".join(part_words)))

    return result


def summarize_chapter(book_title: str, chapter_title: str, text: str) -> str:
    """Extract core principles and insights from a chapter via local Ollama."""
    words = text.split()
    if len(words) > 3000:
        text = " ".join(words[:3000]) + "\n\n[truncated]"

    prompt = f"""You are extracting knowledge from a book for a personal AI brain.

Book: {book_title}
Chapter/Section: {chapter_title}

TEXT:
{text}

Extract the core principles, key lessons, and memorable insights from this section.
Write as dense, direct knowledge — not a summary of what the text says, but the actual wisdom.
Preserve specific techniques, frameworks, quotes, and actionable principles.
Be concise but rich. 3-8 sentences max. No preamble."""

    from brain.core.summarizer import _chat
    return _chat(prompt, max_tokens=800).strip()

    raise RuntimeError("Max retries exceeded")


def load_checkpoint() -> dict:
    if CHECKPOINT_PATH.exists():
        return json.loads(CHECKPOINT_PATH.read_text())
    return {}


def save_checkpoint(data: dict):
    CHECKPOINT_PATH.write_text(json.dumps(data, indent=2))


def ingest_book(book_path: Path, use_llm: bool, checkpoint: dict) -> int:
    book_slug = slugify(book_path.stem)
    book_title = book_path.stem.replace("-", " ").replace("_", " ")
    topics = detect_topics(book_path.stem)

    tags = [
        "content_type/book",
        f"book/{book_slug}",
        "source/obsidian",
    ] + [f"topic/{t}" for t in topics]

    content = book_path.read_text(encoding="utf-8", errors="replace")
    raw_chunks = chunk_by_pages(content)

    # Further split oversized chunks
    final_chunks = []
    for title, body in raw_chunks:
        final_chunks.extend(split_large_chunk(title, body))

    book_checkpoint = checkpoint.get(book_slug, {})
    saved = 0

    for i, (chapter_title, body) in enumerate(final_chunks):
        chunk_key = f"{i}:{slugify(chapter_title)}"
        if chunk_key in book_checkpoint:
            continue

        print(f"  [{i+1}/{len(final_chunks)}] {chapter_title[:60]}...")

        if use_llm:
            try:
                memory_text = summarize_chapter(book_title, chapter_title, body)
                memory_text = f"[{book_title}] {chapter_title}\n\n{memory_text}"
            except Exception as e:
                print(f"    [LLM error] {e} — storing raw excerpt")
                memory_text = f"[{book_title}] {chapter_title}\n\n{body[:1200]}"
        else:
            # No LLM: store first 600 words as-is
            words = body.split()[:600]
            memory_text = f"[{book_title}] {chapter_title}\n\n{' '.join(words)}"

        vault_fp = (_REPO_ROOT / "vault" / "03 Resources" / "Books" / book_path.name).as_posix()
        mem_title = f"{book_title} — {chapter_title}"
        save_memory(
            content=memory_text,
            memory_type="solution",
            tags=with_ingest_tag(tags + [f"chapter/{slugify(chapter_title)}"]),
            project="general",
            source="obsidian_books",
            session_id=f"book_{book_slug}_{i}",
            file_path=vault_fp,
            title=mem_title,
        )

        book_checkpoint[chunk_key] = True
        checkpoint[book_slug] = book_checkpoint
        save_checkpoint(checkpoint)
        saved += 1

    return saved


def run(use_llm: bool = True, only_book: str | None = None):
    book_files = sorted(BOOKS_DIR.glob("*.md"))
    if not book_files:
        print(f"No books found in {BOOKS_DIR}")
        return

    if only_book:
        book_files = [f for f in book_files if only_book.lower() in f.stem.lower()]
        if not book_files:
            print(f"No book matching '{only_book}'")
            return

    print(f"Found {len(book_files)} book(s)")
    checkpoint = load_checkpoint()
    before = get_stats().get("total_memories", 0)

    total_saved = 0
    for book_path in book_files:
        print(f"\n=== {book_path.stem} ===")
        n = ingest_book(book_path, use_llm, checkpoint)
        print(f"  Saved {n} chunks")
        total_saved += n

    after = get_stats().get("total_memories", before)
    print(f"\nDone. Chunks saved={total_saved}. Brain: {before} -> {after} (+{after - before})")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-llm", action="store_true", help="Skip LLM summarization (store raw text)")
    parser.add_argument("--book", type=str, help="Only ingest book matching this name substring")
    args = parser.parse_args()
    run(use_llm=not args.no_llm, only_book=args.book)
