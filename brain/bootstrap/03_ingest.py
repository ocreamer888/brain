"""Ingest cursor summaries into Rust brain API."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from brain.api_client import save_memory, get_stats
from tqdm import tqdm

INPUT_PATH = Path(__file__).parent / "summaries.jsonl"


def run():
    if not INPUT_PATH.exists():
        print("Run 02_summarize.py first.")
        sys.exit(1)

    summaries = [json.loads(l) for l in INPUT_PATH.read_text().splitlines() if l.strip()]
    print(f"Ingesting {len(summaries)} summaries...")

    before = get_stats().get("total_memories", 0)
    saved = 0
    for s in tqdm(summaries, desc="Saving to Rust API"):
        parts = [s.get("summary", "")]
        parts += s.get("solutions", [])
        parts += s.get("decisions", [])
        parts += s.get("patterns", [])
        text = " | ".join(filter(None, parts))
        tags = s.get("topics", [])
        save_memory(
            content=text,
            memory_type=s.get("type", "conversation"),
            tags=tags,
            project=s.get("project") or "general",
            session_id=s.get("session_id"),
            source="cursor_history",
            auto_entities=False,  # bulk ingest: backfill_entities.py links these
        )
        saved += 1

    after = get_stats().get("total_memories", before)
    print(f"\nIngestion complete. Saved={saved}. Rust memories: {before} -> {after} (+{after - before})")


if __name__ == "__main__":
    run()
