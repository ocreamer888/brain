# Build `brain_api` and run it (Documents/AI → this repo)

**Purpose:** How the old Documents/AI plane built and supervised `brain_api`, and how to do the same in this product checkout (`/Users/abundancia888/Documents/Code/brain`).

**Verified:** 2026-07-28 (Phase 4 cutover).

---

## 1. How Documents/AI did it

| Piece | Documents/AI path / value |
| --- | --- |
| Source | `/Users/abundancia888/Documents/AI/brain/rust/` |
| Release binary | `cargo build --release` → `brain/rust/target/release/brain_api` (~13MB) |
| Launcher | `brain/rust/start_api.sh` (hard-coded `exec` of that binary); launchd often called the binary **directly** |
| Supervisor | `~/Library/LaunchAgents/com.brain.api.plist` (`KeepAlive` + `RunAtLoad`) |
| DB | `BRAIN_DB_PATH=.../Documents/AI/brain/rust/brain.db` |
| Embeddings | `BRAIN_ONNX_PATH=.../Documents/AI/brain/rust/models/all-mpnet-base-v2-onnx` (~417MB) |
| ORT dylib | `ORT_DYLIB_PATH=.../Documents/AI/.venv/.../libonnxruntime.*.dylib` (`ort` crate loads ONNX Runtime dynamically) |
| Bind | `BRAIN_API_BIND=0.0.0.0:8787` |
| Auth | `BRAIN_API_AUTH_REQUIRED=true` + `BRAIN_API_KEY=local-dev-key` (browser viewer needs `0` — JS does not send the key) |
| LLM | `BRAIN_LLM_PROVIDER=ollama`, `OLLAMA_URL`, `OLLAMA_MODEL` |

**Build command (old tree):**

```bash
cd /Users/abundancia888/Documents/AI/brain/rust
cargo build --release
```

ONNX was produced once via Hugging Face export (or copied between machines), **not** committed to git.

---

## 2. What the ONNX model does

Directory `all-mpnet-base-v2-onnx/` holds the exported **sentence-transformers `all-mpnet-base-v2`** model (768-dim):

- `model.onnx`, `tokenizer.json`, `vocab.txt`, …

`brain_api` uses it to embed memory text on save and queries on search. Without it (and without `BRAIN_EMBEDDER=mock`), semantic search/save fail.

**Bring into this repo (preferred when old copy exists):**

```bash
mkdir -p brain/rust/models
rsync -a --delete \
  /Users/abundancia888/Documents/AI/brain/rust/models/all-mpnet-base-v2-onnx/ \
  brain/rust/models/all-mpnet-base-v2-onnx/
```

**Or export fresh:**

```bash
source .venv/bin/activate
python3 brain/tools/export_onnx.py
```

`brain/rust/models/` is **gitignored** (~417MB). Do not commit it.

---

## 3. Build and run in this product repo

### Prerequisites

- Rust stable (`cargo`, `rustc`)
- Repo `.venv` with `brain/requirements.txt` (for MCP/hooks/tools; also provides `onnxruntime` dylib)
- ONNX dir under `brain/rust/models/all-mpnet-base-v2-onnx/`
- SQLite DB at `brain/rust/brain.db` (auto-created empty on first start, or **copied** from Documents/AI for zero data loss)

### Build release binary

```bash
cd /Users/abundancia888/Documents/Code/brain/brain/rust
cargo build --release
# → target/release/brain_api
```

`target/` is gitignored. Rebuild after Rust source changes.

### Manual run (smoke)

```bash
export BRAIN_DB_PATH="/Users/abundancia888/Documents/Code/brain/brain/rust/brain.db"
export BRAIN_ONNX_PATH="/Users/abundancia888/Documents/Code/brain/brain/rust/models/all-mpnet-base-v2-onnx"
export ORT_DYLIB_PATH="/Users/abundancia888/Documents/Code/brain/.venv/lib/python3.14/site-packages/onnxruntime/capi/libonnxruntime.1.28.0.dylib"
export BRAIN_API_BIND="127.0.0.1:8787"
export BRAIN_API_KEY="local-dev-key"
export BRAIN_API_AUTH_REQUIRED="0"   # browser Linked/Dashboard
export BRAIN_LLM_PROVIDER="ollama"
export OLLAMA_URL="http://127.0.0.1:11434"
export OLLAMA_MODEL="qwen3-coder:30b"

./start_api.sh
# or: ./target/release/brain_api
```

### launchd (production on this Mac)

Plist label: `com.brain.api`  
**Program:** this repo’s `brain/rust/target/release/brain_api` (**direct binary** — same pattern as Documents/AI).

> Do **not** point launchd at `start_api.sh` under Documents/Code on this Mac: launchd got `Operation not permitted` / exit 126 on the shell wrapper (TCC). `start_api.sh` remains fine for interactive/manual runs.

Env: `BRAIN_DB_PATH` / `BRAIN_ONNX_PATH` / `ORT_DYLIB_PATH` under **Documents/Code/brain**.  
**Canonical plist in repo:** [`deploy/com.brain.api.plist`](deploy/com.brain.api.plist) → copy to `~/Library/LaunchAgents/com.brain.api.plist`.

**Auth:** `BRAIN_API_AUTH_REQUIRED=0` so the browser viewer (Linked / Dashboard) works without sending `x-api-key`. MCP may still send the key.

Reload:

```bash
launchctl bootout "gui/$(id -u)/com.brain.api" 2>/dev/null || true
cp docs/deploy/com.brain.api.plist ~/Library/LaunchAgents/com.brain.api.plist
launchctl bootstrap "gui/$(id -u)" ~/Library/LaunchAgents/com.brain.api.plist
```
### Smoke checks

```bash
curl -sS -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8787/health    # 200
curl -sS -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8787/linked   # 200 (product binary)
```

MCP: Cursor `.cursor/mcp.json` → `.../Documents/Code/brain/brain/mcp/run_server.sh` with `BRAIN_API_URL=http://127.0.0.1:8787`.

---

## 4. Zero-data-loss DB cutover

1. Stop launchd (`bootout`) so SQLite is not open.
2. Copy (do **not** delete the old file):

```bash
cp -p /Users/abundancia888/Documents/AI/brain/rust/brain.db \
      /Users/abundancia888/Documents/Code/brain/brain/rust/brain.db
# optional dated backup of the source:
cp -p /Users/abundancia888/Documents/AI/brain/rust/brain.db \
      /Users/abundancia888/Documents/AI/brain/rust/brain.db.bak-cutover-$(date +%Y%m%d-%H%M%S)
```

3. Point `BRAIN_DB_PATH` at the **new** copy; leave Documents/AI DB as freeze/backup.
4. Start launchd; confirm `/health` and memory counts via `/stats` or MCP `get_stats_tool`.

---

## 5. Related docs

- Cutover status: [`OLD-VS-NEW-BRAIN-INSPECTION.md`](OLD-VS-NEW-BRAIN-INSPECTION.md)
- Example plist template: [`deploy/com.example.brain-api.plist`](deploy/com.example.brain-api.plist)
- Env matrix: [`BRAIN_ENV_MATRIX.md`](BRAIN_ENV_MATRIX.md)
