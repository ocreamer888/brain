"""
Summarize raw conversations using Claude API.
Checkpointed — safe to interrupt and resume.
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from brain.core.summarizer import summarize_conversation
from tqdm import tqdm

INPUT_PATH = Path(__file__).parent / "raw_conversations.jsonl"
OUTPUT_PATH = Path(__file__).parent / "summaries.jsonl"
CHECKPOINT_PATH = Path(__file__).parent / "checkpoint.json"


def load_checkpoint() -> set:
    if CHECKPOINT_PATH.exists():
        data = json.loads(CHECKPOINT_PATH.read_text())
        return set(data.get("processed_ids", []))
    return set()


def save_checkpoint(processed_ids: set):
    CHECKPOINT_PATH.write_text(json.dumps({"processed_ids": list(processed_ids)}))


def run():
    if not INPUT_PATH.exists():
        print("Run 01_parse_sql.py first.")
        sys.exit(1)

    conversations = [json.loads(line) for line in INPUT_PATH.read_text().splitlines() if line.strip()]
    processed_ids = load_checkpoint()

    print(f"Total conversations: {len(conversations)}")
    print(f"Already processed: {len(processed_ids)}")
    remaining = [c for c in conversations if c["session_id"] not in processed_ids]
    print(f"Remaining: {len(remaining)}")

    with open(OUTPUT_PATH, 'a') as out_file:
        for convo in tqdm(remaining, desc="Summarizing"):
            session_id = convo["session_id"]
            try:
                summary = summarize_conversation(convo["messages"])
                summary["session_id"] = session_id
                summary["message_count"] = convo["message_count"]
                out_file.write(json.dumps(summary) + '\n')
                out_file.flush()

                processed_ids.add(session_id)
                # Save checkpoint every 10
                if len(processed_ids) % 10 == 0:
                    save_checkpoint(processed_ids)

                # Rate limit — Claude haiku allows ~50 req/min
                time.sleep(0.5)

            except Exception as e:
                print(f"\n[summarize] Failed {session_id}: {e}", file=sys.stderr)
                save_checkpoint(processed_ids)

    save_checkpoint(processed_ids)
    print(f"\nDone. Summaries saved to {OUTPUT_PATH}")


if __name__ == "__main__":
    run()
