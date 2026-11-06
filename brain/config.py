import os
from pathlib import Path


BASE_DIR = Path(__file__).parent
_REPO_ROOT = BASE_DIR.parent
DB_PATH = BASE_DIR / "db"
BOOTSTRAP_DIR = BASE_DIR / "bootstrap"

# Override with OBSIDIAN_VAULT or OBSIDIAN_VAULT_PATH. Default: in-repo vault/ (code ≠ data).
OBSIDIAN_VAULT = Path(
    os.environ.get("OBSIDIAN_VAULT")
    or os.environ.get("OBSIDIAN_VAULT_PATH")
    or str(_REPO_ROOT / "vault")
)

# Override with CLAUDE_MEMORY_DIR. Default: Claude project slug for this checkout path.
_default_claude_slug = "-" + str(_REPO_ROOT).lstrip("/").replace("/", "-")
CLAUDE_MEMORY_DIR = Path(
    os.environ.get(
        "CLAUDE_MEMORY_DIR",
        str(Path.home() / ".claude" / "projects" / _default_claude_slug / "memory"),
    )
)

SQL_PATH = Path(
    os.environ.get(
        "BRAIN_SQL_PATH",
        str(OBSIDIAN_VAULT / "cursor-recovery-backup" / "recovered.sql"),
    )
)


# Must match the Rust API's production ONNX model (all-mpnet-base-v2, 768-dim)
# so Python-extracted facts share the same vector space as API-saved memories.
EMBEDDING_MODEL = "sentence-transformers/all-mpnet-base-v2"
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
# 2026-11-05: switched from qwen3-coder:30b to ornith-35b-eval:latest.
# brain memory 5d5ed144 (2026-11-05 or earlier) found ornith:35b -- a
# thinking/agentic model -- unsafe here because Brain's Ollama calls
# (summarize/fact-extract/curator/entity-extract) didn't send think:false,
# so reasoning went into message.thinking and message.content came back
# empty. That's now fixed: every call site (entity_extractor.py,
# fact_extractor.py, fact_curator.py, core/summarizer.py, and the Rust
# OllamaClient) sends "think": false unconditionally. Verified live:
# ornith-35b-eval:latest with think:false parsed cleanly through Brain's
# real JSON parsers (markdown-fence stripping included) on both the
# entity-extraction and title/summary prompts, 6/6 runs, 0.6-1.0s each
# once Ollama wasn't contended by another session -- actually faster than
# qwen3-coder's benchmarked ~4s. Known caveat: the model's llama-server
# runs with -np 1 (one concurrent request), so Brain's calls queue behind
# any other active use of this same model.
OLLAMA_SUMMARIZE_MODEL = os.environ.get("OLLAMA_SUMMARIZE_MODEL", "ornith-35b-eval:latest")


MEMORIES_COLLECTION = "memories"
SESSIONS_COLLECTION = "sessions"
REFLECT_EVERY_N = 20  # Trigger reflection every N new saves
