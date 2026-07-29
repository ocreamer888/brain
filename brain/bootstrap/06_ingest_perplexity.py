"""
Ingest Perplexity exported threads into Rust brain API.

Each JSON file from perplexport -> extract/summary -> /save.
Checkpoint ensures resumable runs (one API call per thread).

Usage:
    OPENROUTER_API_KEY="sk-or-..." python brain/bootstrap/06_ingest_perplexity.py
    python brain/bootstrap/06_ingest_perplexity.py --no-llm  # skip summarization
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from brain.api_client import save_memory, get_stats
from brain.bootstrap.perplexity_extractors import (
    EXPORTS_DIR,
    extract_thread_record,
    extract_thread_record_with_llm,
)

CHECKPOINT_PATH = Path(__file__).parent / "checkpoint_perplexity.json"
def load_checkpoint() -> set:
    if CHECKPOINT_PATH.exists():
        return set(json.loads(CHECKPOINT_PATH.read_text()).get("processed_ids", []))
    return set()


def save_checkpoint(processed_ids: set):
    CHECKPOINT_PATH.write_text(json.dumps({"processed_ids": list(processed_ids)}))


def collect_records(use_llm: bool = True) -> list[dict]:
    json_files = sorted(EXPORTS_DIR.rglob("*.json"))
    print(f"Found {len(json_files)} thread files in {EXPORTS_DIR}")

    processed = load_checkpoint()
    records = []

    for i, f in enumerate(json_files):
        thread_id = f.stem
        if thread_id in processed:
            continue

        print(f"  [{i+1}/{len(json_files)}] {f.name}...")
        try:
            if use_llm:
                record = extract_thread_record_with_llm(f)
            else:
                record = extract_thread_record(f)
            records.append(record)
            processed.add(thread_id)
        except Exception as e:
            print(f"  [error] {f.name}: {e}")

        if len(records) % 10 == 0:
            save_checkpoint(processed)

    save_checkpoint(processed)
    return records


def run(use_llm: bool = True):
    before = get_stats().get("total_memories", 0)
    print(f"Rust API memories before: {before}\n")

    records = collect_records(use_llm=use_llm)
    print(f"\nTotal records collected: {len(records)}")

    if not records:
        print("Nothing new to ingest.")
        return

    saved = 0
    for record in records:
        tags = [
            t.strip()
            for t in str(record["metadata"].get("tags", "")).split(",")
            if t.strip()
        ]
        save_memory(
            content=record["text"],
            memory_type=record["metadata"].get("type", "conversation"),
            tags=tags,
            project=record["metadata"].get("project", "general"),
            source=record["metadata"].get("source", "perplexity"),
            session_id=record["metadata"].get("thread_id"),
            timestamp=record["metadata"].get("timestamp"),
            auto_entities=False,  # bulk ingest: backfill_entities.py links these
        )
        saved += 1

    after = get_stats().get("total_memories", before)
    print(f"\nDone. Saved={saved}. Rust memories: {before} -> {after} (+{after - before})")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-llm", action="store_true", help="Skip LLM summarization (faster, less rich)")
    args = parser.parse_args()
    run(use_llm=not args.no_llm)
