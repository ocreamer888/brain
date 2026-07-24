#!/usr/bin/env python3
"""Link arbitrary vault markdown files into brain-graph via semantic search.

For each markdown file in configured globs, searches the brain API for the
most relevant memories and injects/updates a managed ## Related block with
[[brain-graph/type/slug]] wikilinks.

The managed block is idempotent — re-runs replace it in-place:
    <!-- brain-linker -->
    ...
    <!-- /brain-linker -->

Usage:
    python3 brain/tools/link_vault_files.py [options]

Options:
    --top N          Wikilinks per file (default: 5)
    --query-chars N  Chars of file content used as search query (default: 600)
    --dry-run        Print changes without writing
    --file PATH      Process a single file instead of all globs
    --verbose        Show search scores
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from brain.api_client import search  # noqa: E402

# ── config ────────────────────────────────────────────────────────────────────

# Globs to walk (relative to ROOT). brain-graph/** excluded by design.
INCLUDE_GLOBS = [
    "docs/**/*.md",
    "*.md",
    "reference-claw-code-main/*.md",
    "reference-claw-code-main/rust/docs/**/*.md",
    "dashboards/*.md",
    "brain/bootstrap/*.md",
]

# Root-level policy / memory files: keep free of linker blocks (continual-learning AGENTS.md contract).
LINKER_EXCLUDE_ROOT_NAMES = frozenset({"AGENTS.md"})

# Marker wrapping the injected block
MARKER_OPEN = "<!-- brain-linker -->"
MARKER_CLOSE = "<!-- /brain-linker -->"
MARKER_RE = re.compile(
    r"<!-- brain-linker -->.*?<!-- /brain-linker -->",
    re.DOTALL,
)

# Where brain-graph notes live (relative to ROOT)
BRAIN_GRAPH_DIR = ROOT / "brain-graph"


# ── helpers ───────────────────────────────────────────────────────────────────

_UNSAFE = re.compile(r'[\\/:*?"<>|#^\[\]]')


def _slug(text: str, max_len: int = 60) -> str:
    """Same slug function as export_knowledge_graph.py."""
    first_line = text.strip().splitlines()[0] if text.strip() else "untitled"
    s = _UNSAFE.sub("", first_line)
    s = re.sub(r"\s+", " ", s).strip()
    return s[:max_len] or "untitled"


def _slug_index() -> dict[str, str]:
    """Build {content_slug: 'type/slug'} from brain-graph note filenames.

    Keyed by slug (first 60 chars of content, sanitized) rather than memory ID,
    because the graph was generated from a different DB snapshot and IDs don't
    match current SQLite UUIDs.
    """
    index: dict[str, str] = {}
    if not BRAIN_GRAPH_DIR.exists():
        return index
    for note in BRAIN_GRAPH_DIR.rglob("*.md"):
        if note.name == "Brain Knowledge Graph.md":
            continue
        # The stem IS the slug (filename without extension)
        stem = note.stem
        index[stem.lower()] = str(note.relative_to(BRAIN_GRAPH_DIR).with_suffix(""))
    return index


def _build_query(path: Path, max_chars: int) -> str:
    """Use title (first heading or filename) + first N chars as query."""
    text = path.read_text(encoding="utf-8", errors="replace")
    # Extract first heading
    heading_m = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
    title = heading_m.group(1).strip() if heading_m else path.stem.replace("-", " ")
    # Strip frontmatter and markers before taking body
    body = re.sub(r"^---\n.*?\n---\n", "", text, flags=re.DOTALL)
    body = MARKER_RE.sub("", body).strip()
    combined = f"{title}\n\n{body}"
    return combined[:max_chars]


def _managed_block(links: list[str]) -> str:
    lines = [MARKER_OPEN, "## Related"]
    lines += [f"- [[{lnk}]]" for lnk in links]
    lines.append(MARKER_CLOSE)
    return "\n".join(lines)


def _inject(path: Path, links: list[str], dry_run: bool) -> bool:
    """Replace or append managed block. Returns True if file changed."""
    text = path.read_text(encoding="utf-8", errors="replace")
    block = _managed_block(links)

    if MARKER_RE.search(text):
        new_text = MARKER_RE.sub(block, text)
    else:
        sep = "\n\n" if not text.endswith("\n\n") else ""
        new_text = text.rstrip("\n") + sep + "\n" + block + "\n"

    if new_text == text:
        return False
    if not dry_run:
        path.write_text(new_text, encoding="utf-8")
    return True


def collect_files() -> list[Path]:
    seen: set[Path] = set()
    files: list[Path] = []
    for glob in INCLUDE_GLOBS:
        for f in sorted(ROOT.glob(glob)):
            if not f.is_file():
                continue
            if f.parent == ROOT and f.name in LINKER_EXCLUDE_ROOT_NAMES:
                continue
            r = f.resolve()
            if r not in seen:
                seen.add(r)
                files.append(f)
    return files


# ── main ─────────────────────────────────────────────────────────────────────

def process_file(
    path: Path,
    slug_index: dict[str, str],
    top: int,
    query_chars: int,
    dry_run: bool,
    verbose: bool,
) -> None:
    query = _build_query(path, query_chars)
    if not query.strip():
        print(f"  [skip] {path.relative_to(ROOT)} — empty")
        return

    try:
        # Fetch extra hits so we can still fill `top` after slug dedupe / index misses.
        results = search(query, n=max(top * 8, 24))
    except Exception as e:
        print(f"  [error] {path.relative_to(ROOT)}: {e}", file=sys.stderr)
        return

    links: list[str] = []
    seen_links: set[str] = set()
    for r in results:
        content_slug = _slug(r.get("content", "")).lower()
        slug = slug_index.get(content_slug)
        if not slug:
            continue
        href = f"brain-graph/{slug}"
        if href in seen_links:
            continue
        seen_links.add(href)
        if verbose:
            dist = r.get("distance", r.get("score"))
            dist_s = f"{float(dist):.4f}" if isinstance(dist, (int, float)) else str(dist)
            print(f"    {dist_s}  {href}")
        links.append(href)
        if len(links) >= top:
            break

    if not links:
        print(f"  [skip] {path.relative_to(ROOT)} — no matches in slug index")
        return

    changed = _inject(path, links, dry_run)
    tag = "[dry-run] would update" if dry_run else "updated"
    status = tag if changed else "unchanged"
    print(f"  {status}: {path.relative_to(ROOT)} ({len(links)} links)")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--top", type=int, default=5)
    p.add_argument("--query-chars", type=int, default=600)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--file", type=Path, default=None)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    if not BRAIN_GRAPH_DIR.exists():
        print(f"[link] brain-graph not found at {BRAIN_GRAPH_DIR}", file=sys.stderr)
        print("[link] Run export_knowledge_graph.py first.", file=sys.stderr)
        return 1

    print("[link] Building slug index from brain-graph/…", file=sys.stderr)
    slug_index = _slug_index()
    print(f"[link] {len(slug_index)} memory slugs indexed", file=sys.stderr)

    if not slug_index:
        print("[link] Slug index is empty — nothing to link to.", file=sys.stderr)
        return 1

    files = [args.file.resolve()] if args.file else collect_files()
    print(f"[link] {len(files)} files to process", file=sys.stderr)
    if args.dry_run:
        print("[link] dry-run — no files will be written", file=sys.stderr)

    for f in files:
        process_file(f, slug_index, args.top, args.query_chars, args.dry_run, args.verbose)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
