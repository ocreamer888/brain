import os
from pathlib import Path


BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR / "db"
BOOTSTRAP_DIR = BASE_DIR / "bootstrap"
OBSIDIAN_VAULT = Path("/Users/abundancia888/Documents/AI")
CLAUDE_MEMORY_DIR = Path.home() / ".claude/projects/-Users-abundancia888-Documents-AI/memory"
SQL_PATH = OBSIDIAN_VAULT / "cursor-recovery-backup/recovered.sql"


# Must match the Rust API's production ONNX model (all-mpnet-base-v2, 768-dim)
# so Python-extracted facts share the same vector space as API-saved memories.
EMBEDDING_MODEL = "sentence-transformers/all-mpnet-base-v2"
OLLAMA_URL = "http://127.0.0.1:11434"
OLLAMA_SUMMARIZE_MODEL = "qwen3-coder:30b"


MEMORIES_COLLECTION = "memories"
SESSIONS_COLLECTION = "sessions"
REFLECT_EVERY_N = 20  # Trigger reflection every N new saves