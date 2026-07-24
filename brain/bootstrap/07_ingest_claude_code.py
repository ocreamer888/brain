"""
Ingest Claude Code session exports into Rust brain via HTTP API.

Sessions are exported by the session_end.py hook to brain/bootstrap/sessions_export/.
This script:
  1. Scans for new session JSON files
  2. Summarizes each via OpenRouter (optional, can skip with --no-llm)
  3. Optional LLM summarization
  4. Saves to Rust API (/save)
  5. Saves checkpoint for resumability

Usage:
    OPENROUTER_API_KEY="sk-or-..." python3 brain/bootstrap/07_ingest_claude_code.py
    python3 brain/bootstrap/07_ingest_claude_code.py --no-llm  # skip summarization
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from brain.api_client import get_stats
from brain.bootstrap.claude_code_extractors import SESSIONS_EXPORT_DIR
from brain.bootstrap.ingest_claude_code_lib import run_with_dirs

CHECKPOINT_PATH = Path(__file__).parent / "checkpoint_claude_code.json"


def _resolve_only_file(only_file: Path) -> Path | None:
    """Return resolved path if under SESSIONS_EXPORT_DIR, else None."""
    p = only_file.resolve()
    root = SESSIONS_EXPORT_DIR.resolve()
    try:
        p.relative_to(root)
    except ValueError:
        return None
    return p if p.is_file() else None


def run(use_llm: bool = True, only_file: Path | None = None):
    """Main entry point."""
    before = get_stats().get("total_memories", 0)
    print(f"Rust API memories before: {before}\n")

    saved_count = run_with_dirs(
        sessions_dir=SESSIONS_EXPORT_DIR,
        checkpoint_path=CHECKPOINT_PATH,
        use_llm=use_llm,
        only_file=only_file,
    )

    after = get_stats().get("total_memories", before)
    print(f"\nDone. Saved: {saved_count}. Rust memories: {before} → {after} (+{after - before})")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-llm", action="store_true", help="Skip LLM summarization (faster)")
    parser.add_argument(
        "--file",
        type=Path,
        default=None,
        metavar="PATH",
        help="Ingest only this session JSON (must be under sessions_export/)",
    )
    args = parser.parse_args()
    if args.file is not None:
        resolved = _resolve_only_file(args.file)
        if resolved is None:
            print(
                f"error: --file must be an existing path under {SESSIONS_EXPORT_DIR}",
                file=sys.stderr,
            )
            sys.exit(2)
        run(use_llm=not args.no_llm, only_file=resolved)
    else:
        run(use_llm=not args.no_llm)
