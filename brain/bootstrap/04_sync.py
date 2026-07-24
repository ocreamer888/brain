"""Sync summaries to Obsidian and Claude memory files."""
import json
import sys
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parent.parent))
from brain.sync.obsidian import write_project_note
from brain.sync.claude_memory import write_project_memory

INPUT_PATH = Path(__file__).parent / "summaries.jsonl"


def run():
    summaries = [json.loads(l) for l in INPUT_PATH.read_text().splitlines() if l.strip()]

    # Group by project
    by_project = defaultdict(list)
    for s in summaries:
        project = s.get("project") or "general"
        by_project[project].append(s)

    print(f"Syncing {len(by_project)} projects...")
    for project, project_summaries in by_project.items():
        write_project_note(project, project_summaries)
        write_project_memory(project, project_summaries)

    print("Sync complete.")


if __name__ == "__main__":
    run()
