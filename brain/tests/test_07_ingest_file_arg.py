"""CLI guard for 07_ingest_claude_code --file outside export dir."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_ingest_rejects_file_outside_sessions_export(tmp_path):
    outside = tmp_path / "outside.json"
    outside.write_text("{}", encoding="utf-8")
    script = Path(__file__).resolve().parents[1] / "bootstrap" / "07_ingest_claude_code.py"
    repo = Path(__file__).resolve().parents[2]
    proc = subprocess.run(
        [sys.executable, str(script), "--no-llm", "--file", str(outside)],
        cwd=str(repo),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 2
    assert "error:" in proc.stderr.lower()
