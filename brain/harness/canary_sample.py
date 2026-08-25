"""Read-only canary sample before bulk Brain jobs.

Opens brain.db with mode=ro. Writes sample.jsonl + summary.md + meta.json.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = REPO_ROOT / "brain" / "rust" / "brain.db"

# Default: recent durable memories (eyeball project tags / content junk)
DEFAULT_SQL = """
SELECT id, type, project, substr(content, 1, 240) AS content_preview, timestamp
FROM memories
WHERE type IN (
  '"fact"', '"solution"', '"decision"', '"pattern"',
  '"project_context"', '"error_lesson"', '"conversation"', '"knowledge"'
)
ORDER BY timestamp DESC
LIMIT ?
"""


def open_ro(db: Path) -> sqlite3.Connection:
    uri = f"file:{db.resolve()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Brain Forge canary sample (read-only)")
    parser.add_argument("--label", required=True, help="Job label for output dir name")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument(
        "--sql",
        default=None,
        help="Custom SELECT; use ? placeholder for limit, or omit limit bind",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="Output directory (default brain/eval/runs/canary-<label>)",
    )
    args = parser.parse_args(argv)

    db = args.db if args.db.is_absolute() else REPO_ROOT / args.db
    if not db.is_file():
        print(f"DB not found: {db}", file=sys.stderr)
        return 2

    out_dir = args.out_dir
    if out_dir is None:
        out_dir = REPO_ROOT / "brain" / "eval" / "runs" / f"canary-{args.label}"
    elif not out_dir.is_absolute():
        out_dir = REPO_ROOT / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    sql = (args.sql or DEFAULT_SQL).strip()
    # Safety: refuse obvious writes
    head = sql.lstrip().split(None, 1)[0].upper()
    if head not in ("SELECT", "WITH"):
        print("Refusing non-SELECT SQL", file=sys.stderr)
        return 2

    ts = datetime.now(timezone.utc).isoformat()
    conn = open_ro(db)
    try:
        if "?" in sql:
            rows = conn.execute(sql, (args.limit,)).fetchall()
        else:
            rows = conn.execute(sql).fetchall()
    finally:
        conn.close()

    sample_path = out_dir / "sample.jsonl"
    with sample_path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(dict(row), default=str) + "\n")

    cols = list(rows[0].keys()) if rows else []
    summary = out_dir / "summary.md"
    summary.write_text(
        "\n".join(
            [
                f"# Canary — {args.label}",
                "",
                f"- Timestamp: {ts}",
                f"- DB: `{db}` (read-only)",
                f"- Rows: {len(rows)} (limit={args.limit})",
                f"- Columns: {', '.join(cols)}",
                "",
                "## Eyeball checklist",
                "",
                "- [ ] Sample reflects the **same filter** the bulk job will use",
                "- [ ] No secret-shaped strings that should be filtered",
                "- [ ] Project tags look sane (not path fragments)",
                "- [ ] Content is not empty/meta garbage",
                "- [ ] Owner OK to scale after this sample",
                "",
                f"Sample file: `{sample_path}`",
                "",
            ]
        ),
        encoding="utf-8",
    )

    meta: dict[str, Any] = {
        "label": args.label,
        "timestamp": ts,
        "db": str(db),
        "limit": args.limit,
        "row_count": len(rows),
        "sql": sql,
        "columns": cols,
    }
    (out_dir / "meta.json").write_text(
        json.dumps(meta, indent=2) + "\n", encoding="utf-8"
    )

    print(f"canary wrote {out_dir} rows={len(rows)}")
    return 0 if rows else 1


if __name__ == "__main__":
    raise SystemExit(main())
