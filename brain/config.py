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
OLLAMA_SUMMARIZE_MODEL = os.environ.get("OLLAMA_SUMMARIZE_MODEL", "qwen3-coder:30b")


MEMORIES_COLLECTION = "memories"
SESSIONS_COLLECTION = "sessions"
REFLECT_EVERY_N = 20  # Trigger reflection every N new saves
