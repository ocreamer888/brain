"""Write brain memories as Obsidian markdown notes."""
import json
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import OBSIDIAN_VAULT


def write_project_note(project: str, summaries: list[dict]):
    """Write a single note per project with all its memories."""
    notes_dir = OBSIDIAN_VAULT / "brain-notes"
    notes_dir.mkdir(exist_ok=True)

    safe_name = project.replace("/", "-").replace(" ", "-").lower()
    note_path = notes_dir / f"{safe_name}.md"

    lines = [
        f"# {project.title()} — Brain Notes",
        f"*Last updated: {datetime.now().strftime('%Y-%m-%d')}*",
        f"*{len(summaries)} memories*",
        "",
        "---",
        ""
    ]

    for s in summaries:
        lines.append(f"## {s.get('summary', 'Session')[:80]}")
        lines.append(f"*Topics: {', '.join(s.get('topics', []))}*")
        lines.append("")
        for decision in s.get("decisions", []):
            lines.append(f"- **Decision:** {decision}")
        for solution in s.get("solutions", []):
            lines.append(f"- **Solution:** {solution}")
        for pattern in s.get("patterns", []):
            lines.append(f"- **Pattern:** {pattern}")
        lines.append("")
        lines.append("---")
        lines.append("")

    note_path.write_text("\n".join(lines))
    print(f"Written: {note_path}")
