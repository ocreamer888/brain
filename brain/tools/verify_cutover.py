#!/usr/bin/env python3
"""Verify Rust grows while Chroma stays flat for a probe write."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from brain.api_client import get_stats, save_memory  # noqa: E402
from brain.core.db import count_memories as chroma_count  # noqa: E402


def main() -> int:
    before_rust = int(get_stats().get("total_memories", 0))
    before_chroma = int(chroma_count())

    marker = f"cutover-verify-{uuid4()}"
    save_memory(
        content=marker,
        memory_type="pattern",
        tags=["cutover", "verify"],
        project="AI",
        source="claw_code",
        auto_entities=False,  # one-off probe write: no LLM round-trip needed
    )

    after_rust = int(get_stats().get("total_memories", before_rust))
    after_chroma = int(chroma_count())

    out = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "marker": marker,
        "rust_before": before_rust,
        "rust_after": after_rust,
        "rust_delta": after_rust - before_rust,
        "chroma_before": before_chroma,
        "chroma_after": after_chroma,
        "chroma_delta": after_chroma - before_chroma,
        "ok": (after_rust - before_rust) >= 1 and (after_chroma - before_chroma) == 0,
    }
    print(json.dumps(out, ensure_ascii=True))
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
