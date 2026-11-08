#!/usr/bin/env python3
"""Deliberate corpus ingest → type=knowledge memories (spec 2026-08-06).

Chunks authored reference files (docs, books, specs, manuals) and saves each
chunk as ``memory_type=knowledge`` with provenance:

  - ``file_path``     source path
  - ``title``         doc stem + section
  - ``extracted_by``  ``corpus:<doc_id>:c<ordinal>:sha:<hash>`` — parent doc id,
                      chunk ordinal (for future sibling expansion), content hash

Idempotent by content hash: re-running on an unchanged file adds zero rows;
changed chunks are saved fresh and their stale predecessors marked superseded.
Save, existence-check, and supersede all go through ``brain.api_client`` (HTTP
to ``BRAIN_API_URL``) — never direct SQLite. A client machine (e.g. a MacBook
pointed at a remote Mac Studio brain_api) has no reliable local brain.db, so a
direct-SQLite existence/supersede path would silently look at the wrong
database and never retire stale chunks.

This is the ONLY sanctioned writer of type=knowledge besides explicit agent/MCP
saves. Session recycling and fact extraction are guarded against it.

Usage:
    python3 brain/tools/ingest_knowledge.py PATH [PATH ...] \
        [--project NAME] [--corpus NAME] [--source obsidian] \
        [--entities] [--dry-run] [--on-db-host]
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
import urllib.parse
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from brain import api_client  # noqa: E402
from brain.api_client import save_memory  # noqa: E402
from brain.ingest.payloads import (  # noqa: E402
    format_bracketed_memory,
    memory_display_title,
    with_ingest_tag,
)
from brain.ingest.text_chunking import (  # noqa: E402
    chunk_by_sections,
    normalize_section_title,
    refine_chunks_for_word_limit,
)

TEXT_SUFFIXES = {".md", ".markdown", ".txt", ".rst"}

_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


CHUNK_WORD_THRESHOLD = max(200, _int_env("OBSIDIAN_CHUNK_WORDS", 1500))


def _api_url() -> str:
    return os.environ.get("BRAIN_API_URL", "http://127.0.0.1:8787")


def guard_api_host(on_db_host: bool) -> None:
    """Refuse to run against a non-loopback BRAIN_API_URL unless --on-db-host.

    Defense in depth: existence-check + supersede now go through the API (not
    direct SQLite), so pointing at a remote brain_api is *correct*. But this
    CLI is a bulk, potentially slow corpus job — running it unattended against
    a shared remote Studio API from a stale env var or wrong shell is easy to
    do by accident. Forcing an explicit flag for any non-loopback
    BRAIN_API_URL makes that a deliberate choice instead of a silent default.
    """
    if on_db_host:
        return
    url = _api_url()
    host = (urllib.parse.urlparse(url).hostname or "").lower()
    if host in _LOOPBACK_HOSTS:
        return
    raise SystemExit(
        f"Refusing to run: BRAIN_API_URL={url!r} is not loopback "
        f"(127.0.0.1/localhost). ingest_knowledge is a bulk corpus job — "
        f"running it against a remote brain_api by accident (stale env var, "
        f"wrong shell) is the exact footgun this guard exists for. "
        f"Pass --on-db-host to confirm this is deliberate."
    )


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def doc_id_for(file_path: str) -> str:
    """Stable parent-doc id: hash of the stored file path."""
    return _sha(file_path)


def provenance(doc_id: str, ordinal: int, chunk_sha: str) -> str:
    return f"corpus:{doc_id}:c{ordinal}:sha:{chunk_sha}"


def sha_of_provenance(extracted_by: str | None) -> str | None:
    """Extract the content hash back out of an extracted_by string."""
    if not extracted_by or ":sha:" not in extracted_by:
        return None
    return extracted_by.rsplit(":sha:", 1)[1] or None


def build_chunks(text: str, stem: str) -> list[tuple[str, str, str]]:
    """→ [(title, content, chunk_sha)] in document order."""
    raw = chunk_by_sections(text, stem)
    refined = refine_chunks_for_word_limit(raw, stem, word_threshold=CHUNK_WORD_THRESHOLD)
    out: list[tuple[str, str, str]] = []
    for section_title, body in refined:
        if not body.strip():
            continue
        st = normalize_section_title(stem, section_title)
        content = format_bracketed_memory(stem, st, body)
        out.append((memory_display_title(stem, st), content, _sha(content)))
    return out


def existing_chunks(file_path: str) -> list[tuple[str, str | None]]:
    """[(id, extracted_by)] of live knowledge rows for this file, via the API.

    Routed through ``brain.api_client`` (GET /knowledge/existing) — never
    direct SQLite — so it works correctly whether this CLI runs on the DB
    host or a remote client machine.
    """
    rows = api_client.knowledge_chunks_for_file(file_path)
    return [(r.get("id", ""), r.get("extracted_by")) for r in rows]


def mark_superseded(old_id: str, new_id: str) -> None:
    """Mark ``old_id`` superseded by ``new_id`` via the API (PATCH /memories/:id)."""
    api_client.mark_superseded(old_id, new_id)


def ingest_file(
    path: Path,
    *,
    project: str,
    corpus: str | None,
    source: str,
    entities: bool,
    dry_run: bool,
) -> tuple[int, int, int]:
    """Returns (saved, skipped, superseded) for one file."""
    text = path.read_text(encoding="utf-8", errors="replace")
    stem = path.stem
    file_path = str(path)
    doc_id = doc_id_for(file_path)
    chunks = build_chunks(text, stem)

    existing = existing_chunks(file_path)
    existing_shas = {sha_of_provenance(d) for _, d in existing} - {None}

    tags = ["knowledge"]
    if corpus:
        tags.append(f"corpus:{corpus}")

    saved = skipped = superseded = 0
    new_shas: set[str] = set()
    saved_ids: list[str] = []  # ordinal-aligned replacement candidates
    for ordinal, (title, content, chunk_sha) in enumerate(chunks):
        new_shas.add(chunk_sha)
        if chunk_sha in existing_shas:
            skipped += 1
            saved_ids.append("")
            continue
        if dry_run:
            saved += 1
            saved_ids.append("")
            continue
        mem_id = save_memory(
            content=content,
            memory_type="knowledge",
            tags=with_ingest_tag(tags),
            project=project,
            source=source,
            file_path=file_path,
            title=title,
            extracted_by=provenance(doc_id, ordinal, chunk_sha),
            auto_entities=entities,
        )
        saved += 1
        saved_ids.append(mem_id)

    # Content-addressed staleness: any live row whose hash vanished from the
    # new chunk set belongs to an older version of the doc.
    replacement = next((i for i in saved_ids if i), "")
    for old_id, derived in existing:
        old_sha = sha_of_provenance(derived)
        if old_sha is not None and old_sha in new_shas:
            continue
        superseded += 1
        if not dry_run and replacement:
            mark_superseded(old_id, replacement)
    return saved, skipped, superseded


def collect_files(paths: list[str]) -> list[Path]:
    files: list[Path] = []
    for p in paths:
        pth = Path(p).expanduser().resolve()
        if pth.is_dir():
            files.extend(
                f for f in sorted(pth.rglob("*")) if f.suffix.lower() in TEXT_SUFFIXES
            )
        elif pth.is_file():
            files.append(pth)
        else:
            print(f"skip (not found): {pth}", file=sys.stderr)
    return files


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", help="Files or directories to ingest")
    parser.add_argument("--project", default="general", help="Owning project (default general)")
    parser.add_argument("--corpus", default=None, help="Corpus name for tags (corpus:<name>)")
    parser.add_argument("--source", default="obsidian", help="MemorySource label (default obsidian)")
    parser.add_argument("--entities", action="store_true",
                        help="Extract entities per chunk at save time (slow; backfill covers this later)")
    parser.add_argument("--dry-run", action="store_true", help="Print plan, do not save")
    parser.add_argument(
        "--on-db-host", action="store_true",
        help="Confirm BRAIN_API_URL intentionally points at a remote (non-loopback) "
             "host; required to run this bulk ingest against anything but 127.0.0.1/localhost",
    )
    args = parser.parse_args(argv)

    guard_api_host(args.on_db_host)

    files = collect_files(args.paths)
    if not files:
        print("No ingestable files found.", file=sys.stderr)
        return 1

    print(f"Ingesting {len(files)} file(s) as knowledge "
          f"(project={args.project!r}, threshold={CHUNK_WORD_THRESHOLD}w)\n")
    t_saved = t_skipped = t_superseded = 0
    for f in files:
        saved, skipped, superseded = ingest_file(
            f,
            project=args.project,
            corpus=args.corpus,
            source=args.source,
            entities=args.entities,
            dry_run=args.dry_run,
        )
        t_saved += saved
        t_skipped += skipped
        t_superseded += superseded
        print(f"  {f.name}: saved={saved} skipped={skipped} superseded={superseded}")

    verb = "Would save" if args.dry_run else "Saved"
    print(f"\n{verb} {t_saved} chunks, skipped {t_skipped} unchanged, "
          f"superseded {t_superseded} stale.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
