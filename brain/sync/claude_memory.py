"""Write brain summaries to Claude memory files."""
import json
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import CLAUDE_MEMORY_DIR


def write_project_memory(project: str, summaries: list[dict]):
    """Write a Claude memory file for a project."""
    CLAUDE_MEMORY_DIR.mkdir(parents=True, exist_ok=True)

    safe_name = project.replace("/", "-").replace(" ", "-").lower()
    mem_path = CLAUDE_MEMORY_DIR / f"project_{safe_name}.md"

    decisions = []
    solutions = []
    patterns = []
    topics = set()

    for s in summaries:
        decisions.extend(s.get("decisions", []))
        solutions.extend(s.get("solutions", []))
        patterns.extend(s.get("patterns", []))
        topics.update(s.get("topics", []))

    content = f"""---
name: {project} project knowledge
description: Key decisions, solutions, and patterns from {project} development history
type: project
---

## {project.title()}

**Topics worked on:** {', '.join(sorted(topics))}
**Sessions in history:** {len(summaries)}

### Key Decisions
{chr(10).join(f'- {d}' for d in decisions[:20])}

### Solutions Found
{chr(10).join(f'- {s}' for s in solutions[:20])}

### Patterns Discovered
{chr(10).join(f'- {p}' for p in patterns[:10])}

*Last synced: {datetime.now().strftime('%Y-%m-%d')}*
"""
    mem_path.write_text(content)
    print(f"Written: {mem_path}")
