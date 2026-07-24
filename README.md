# Brain

**Local persistent memory for AI coding agents** (Cursor, Claude Code, and anything that speaks MCP or HTTP).

Brain stores decisions, fixes, patterns, facts, and project context across sessions. Agents search and save through MCP tools; optional hooks auto-capture work as you code. Everything runs on your machine — SQLite + ONNX embeddings behind a Rust API.

---

## What it is

Brain is a **personal long-horizon knowledge system**, not a chat log.

| Layer | Role |
|-------|------|
| **`brain_api` (Rust)** | Production server: save/search, hybrid ranking, job worker, web viewer |
| **SQLite DB** | Source of truth for memories, embeddings, entities, jobs, feedback |
| **ONNX embedder** | `all-mpnet-base-v2` (768-d); vectors live in SQLite and rebuild in-process at startup |
| **MCP server (Python)** | Stdio tools for Cursor / Claude (`search_brain`, `save_memory_tool`, …) |
| **Hooks (optional)** | Session start / prompt submit / tool use / session end → auto capture + cleanup |
| **Ingest (Python)** | Vault markdown, session exports, fact extraction, entity backfill |

**Production golden path:** `BRAIN_BACKEND=api` → clients talk to `brain_api` on `127.0.0.1:8787`.  
`BRAIN_BACKEND=python` (Chroma) is legacy / manual QA only.

---

## What it can do

- **Semantic + keyword search** — weighted cosine + BM25 hybrid (default α ≈ 0.7), with light recency weighting
- **Save typed memories** — `fact`, `solution`, `error_lesson`, `pattern`, `decision`, `project_context`, `conversation`, `episode`
- **Progressive disclosure** — cheap index → timeline → full observations (saves context tokens)
- **Auto capture** — hooks classify tool activity, title with LLM, recycle session into lessons/patterns/summaries
- **Fact layer** — extract / curate / supersede structured facts from sessions and corpora
- **Entity–edge graph** — memories linked to entities (`mentions`); neighbors + Linked viewer tab
- **Live web viewer** — `http://127.0.0.1:8787/` with SSE feed
- **Self-maintenance** — BVH dedup, noise detection, title dedup, reflection, spool replay
- **Evals** — gold / kfold / MCP path quality checks (`brain/eval/`, `brain/tools/eval_suite.py`)
- **Privacy** — strips `<private>…</private>` blocks on save

---

## How it fits together

```
Cursor / Claude Code
    │  MCP stdio (brain/mcp/run_server.sh)
    │  optional Claude Code hooks
    ▼
brain_api  ←── HTTP 127.0.0.1:8787
    │
    ├── SQLite (BRAIN_DB_PATH)     ← memories + embedding BLOBs + FTS5
    ├── In-process vector index   ← rebuilt from DB at every startup
    ├── ONNX all-mpnet-base-v2
    └── Static React viewer
```

---

## Database: created automatically on first server start

You do **not** run a separate “create database” script.

When `brain_api` starts:

1. It reads `BRAIN_DB_PATH` (default: `~/.brain/brain.db`).
2. It creates the parent directory if needed (`~/.brain/`).
3. SQLite opens the file (creates it if missing).
4. Schema is applied with `CREATE TABLE IF NOT EXISTS` (memories, FTS, jobs, entities, edges, feedback, curation, …).

So: **first successful `brain_api` boot = empty but valid DB.**  
Memories appear only after you save via MCP, HTTP `/save`, hooks, or ingest tools.

Startup log looks like:

```text
[BRAIN API] Brain ready (0 memories indexed) in … ms
[BRAIN API] listening on http://127.0.0.1:8787
```

`0 memories` on a fresh machine is expected.

**Tip:** Point `BRAIN_DB_PATH` at a durable path you control (e.g. `<repo>/brain/rust/brain.db` or `~/.brain/brain.db`) and back that file up. Do not mix unrelated corpora unless you intend to.

---

## Prerequisites

| Tool | Why |
|------|-----|
| **Rust** (stable, `cargo`) | Build `brain_api` |
| **Python 3.11+** | MCP server + ingest tools |
| **Git** | Clone this repo |
| **OpenRouter API key** (optional but recommended) | LLM titles, session recycling, fact extraction (`OPENROUTER_API_KEY`) |
| **Disk** | ONNX model export ~hundreds of MB; DB grows with corpus |

---

## Install on your machine

Replace `<REPO>` with the absolute path to this checkout.

### 1. Clone and Python env

```bash
cd <REPO>
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r brain/requirements.txt
```

### 2. Export the ONNX embedding model (once)

```bash
source .venv/bin/activate
pip install 'optimum[exporters]' sentence-transformers
python3 brain/tools/export_onnx.py
# → brain/rust/models/all-mpnet-base-v2-onnx/
```

Without ONNX, set `BRAIN_EMBEDDER=mock` for smoke tests only (not real semantic search).

### 3. Build the API

```bash
cd <REPO>/brain/rust
cargo build --release --bin brain_api
```

### 4. Set environment variables

Add to your shell profile (or a supervised unit env file):

```bash
export BRAIN_BACKEND=api
export BRAIN_API_URL=http://127.0.0.1:8787
export BRAIN_API_KEY=local-dev-key          # pick your own secret
export BRAIN_API_BIND=127.0.0.1:8787
export BRAIN_DB_PATH=<REPO>/brain/rust/brain.db
export BRAIN_ONNX_PATH=<REPO>/brain/rust/models/all-mpnet-base-v2-onnx
export BRAIN_LLM_PROVIDER=openrouter
export OPENROUTER_API_KEY=sk-or-...        # if you use LLM features
# Local viewer + API with a key: server injects the key into the SPA.
# For loopback-only experiments you may set BRAIN_API_AUTH_REQUIRED=0
```

### 5. Start the server (creates the DB)

```bash
cd <REPO>
BRAIN_DB_PATH=<REPO>/brain/rust/brain.db \
BRAIN_API_KEY=local-dev-key \
BRAIN_API_BIND=127.0.0.1:8787 \
./brain/rust/target/release/brain_api
```

Verify:

```bash
curl -s http://127.0.0.1:8787/health
curl -s -H "x-api-key: local-dev-key" http://127.0.0.1:8787/stats
# Open viewer: http://127.0.0.1:8787/
```

First run creates `<REPO>/brain/rust/brain.db` (+ WAL/SHM siblings) with empty tables.

### 6. Wire MCP (Cursor / Claude)

**Repo template:** `.mcp.json`  
**Cursor also reads:** `.cursor/mcp.json` (preferred for Cursor Desktop)

Example:

```json
{
  "mcpServers": {
    "brain": {
      "command": "<REPO>/brain/mcp/run_server.sh",
      "env": {
        "BRAIN_BACKEND": "api",
        "BRAIN_API_URL": "http://127.0.0.1:8787",
        "BRAIN_API_KEY": "local-dev-key"
      }
    }
  }
}
```

`run_server.sh` prefers `<REPO>/.venv/bin/python`. Restart Cursor after editing MCP config.

### 7. Optional: keep API running (macOS launchd / Linux systemd)

See `docs/deploy/README.md` and templates:

- macOS: `docs/deploy/com.example.brain-api.plist`
- Linux: `docs/deploy/brain-api.service`

---

## How to use

### MCP tools (agents)

| Need | Tool |
|------|------|
| Relevant memories (semantic) | `search_brain` |
| Latest / metadata-aware browse | `get_stats_tool` → `search_index` → `timeline_tool` |
| Full text for IDs | `get_observations_tool` |
| Topic kickoff | `get_context_tool` |
| Save knowledge | `save_memory_tool` |
| Consolidate | `reflect_tool` |
| Fact → source episode | `get_episode` |
| Graph neighbors | `get_neighbors_tool` |
| Log retrieval quality | `record_feedback` |

**3-layer pattern (token-efficient):**

1. `search_index(query)` → pick IDs  
2. `timeline_tool(anchor_id)` → neighbors in time  
3. `get_observations_tool(ids)` → full content only for what you need  

Do **not** use `search_brain` when you need “latest by time” — it ranks by relevance, not recency.

### HTTP API (highlights)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/health` | Liveness (no auth) |
| GET | `/stats` | Counts / status |
| POST | `/save` | Upsert memory (+ optional entities) |
| POST | `/save-batch` | Bulk ingest |
| POST | `/search`, `/v1/search` | Hybrid search |
| POST | `/v1/search_index` | Compact index rows |
| POST | `/v1/timeline` | Chronological neighbors |
| POST | `/v1/get_observations` | Full rows by id |
| GET | `/v1/stream` | SSE memory events |
| GET | `/entities`, `/neighbors` | Graph |
| GET | `/` + `/static/*` | Web viewer |

Send `x-api-key: <BRAIN_API_KEY>` when auth is enabled.

### Web viewer

Build/embed UI (after UI changes):

```bash
bash brain/rust/ui/deploy.sh
```

Dev HMR: `cd brain/rust/ui && npm run dev` (proxies API to `:8787`).

### Ingest & maintenance (optional)

| Task | Entry |
|------|--------|
| Canonical chunking / tags | `brain/ingest/` (always import from here) |
| Fact backfill | `python3 brain/tools/backfill_facts.py --all` |
| Entity backfill | `python3 brain/tools/backfill_entities.py` |
| Eval suite | `python3 brain/tools/eval_suite.py --all --quiet` |
| Ops probe | `python3 brain/tools/brain_observability_probe.py` |

Env details: `docs/BRAIN_ENV_MATRIX.md`.

---

## Memory types

| Type | Purpose |
|------|---------|
| `fact` | Verified data, metrics, timestamps |
| `solution` | Bug fixes, implementations |
| `error_lesson` | Error → fix with cause |
| `pattern` | Behaviors, best practices |
| `decision` | Architecture / approach choices |
| `project_context` | Session summaries, roadmaps |
| `conversation` | Chat / Q&A |
| `episode` | Full session/document body for audit |

---

## Copy-paste prompts for agents

Give these to Cursor / Claude **in the repo root** so an agent can set Brain up without guessing.

### Prompt A — Full local setup (new machine)

```text
You are setting up Brain (this repo) on my machine.

Goals:
1) Create Python venv at <REPO>/.venv and install brain/requirements.txt
2) Export ONNX model via: python3 brain/tools/export_onnx.py
   (install optimum[exporters] + sentence-transformers if needed)
3) cargo build --release --bin brain_api in brain/rust
4) Set BRAIN_DB_PATH to <REPO>/brain/rust/brain.db
   Set BRAIN_BACKEND=api, BRAIN_API_URL=http://127.0.0.1:8787,
   BRAIN_API_KEY to a local secret, BRAIN_ONNX_PATH to the exported model dir
5) Start brain_api once. IMPORTANT: the SQLite DB is created automatically on
   first successful server start (MetadataStore::open + CREATE TABLE IF NOT EXISTS).
   Do NOT invent a separate DB migration step. Fresh boot with 0 memories is OK.
6) Verify: curl /health and /stats; confirm brain.db exists on disk
7) Write/update .cursor/mcp.json (and optionally .mcp.json) so MCP launches
   <REPO>/brain/mcp/run_server.sh with BRAIN_BACKEND=api and matching API URL/key
8) Summarize What changed / how to start next time / any blockers

Rules:
- Use this checkout only; do not point at unrelated Documents/AI corpora
- Prefer smallest practical changes; ask before install system-wide daemons
- If port 8787 is busy, check for an existing brain_api / launchd job before killing
```

### Prompt B — Wire MCP only (API already running)

```text
Brain API should already be on http://127.0.0.1:8787.
Configure Cursor MCP for this repo:

1) Ensure <REPO>/brain/mcp/run_server.sh is executable
2) Create/update .cursor/mcp.json:
   command = <REPO>/brain/mcp/run_server.sh
   env: BRAIN_BACKEND=api, BRAIN_API_URL=http://127.0.0.1:8787,
        BRAIN_API_KEY=<same key as brain_api>
3) Prefer <REPO>/.venv for Python (run_server.sh already prefers it)
4) curl /health; if down, start brain_api first — DB auto-creates on first start
5) Tell me to reload Cursor MCP / restart Cursor

Do not change BRAIN_DB_PATH unless I ask.
```

### Prompt C — Smoke test after setup

```text
Verify Brain end-to-end in this repo:

1) GET http://127.0.0.1:8787/health → expect OK
2) GET /stats with x-api-key → print total_memories
3) POST /save a tiny test memory (type=fact, project=general, clear content)
4) POST /search for that content; confirm it ranks near top
5) Via MCP (if available): get_stats_tool + search_brain for the same text
6) Report pass/fail with exact commands and responses (no guessing)

If API is down: start ./brain/rust/target/release/brain_api with BRAIN_DB_PATH
set; remind me the DB file is created on first start if missing.
```

### Prompt D — Optional macOS launchd supervise

```text
Set up launchd so brain_api starts at login on this Mac.

1) Read docs/deploy/README.md and docs/deploy/com.example.brain-api.plist
2) Copy a plist to ~/Library/LaunchAgents/com.brain.api.plist with THIS repo's
   release binary path, BRAIN_DB_PATH, BRAIN_ONNX_PATH, BRAIN_API_KEY, bind 8787
3) Prefer wrapping via a small shell script if needed so launchd runs a signed shell
4) bootstrap/enable the job; verify KeepAlive respawn; curl /health
5) Document start/stop/restart commands for me
6) Ask before bootout of any existing com.brain.api job

Do not pkill alone if launchd KeepAlive is on — it will respawn.
```

---

## Configuration cheat sheet

| Variable | Typical | Notes |
|----------|---------|-------|
| `BRAIN_DB_PATH` | `<REPO>/brain/rust/brain.db` or `~/.brain/brain.db` | Created on first API start |
| `BRAIN_API_URL` | `http://127.0.0.1:8787` | Clients (MCP, hooks) |
| `BRAIN_API_KEY` | secret | `x-api-key` header |
| `BRAIN_API_BIND` | `127.0.0.1:8787` | Do not expose plain HTTP publicly |
| `BRAIN_BACKEND` | `api` | Production path |
| `BRAIN_ONNX_PATH` | `…/all-mpnet-base-v2-onnx` | Or `BRAIN_EMBEDDER=mock` for tests |
| `BRAIN_HYBRID_ALPHA` | `0.7` | Cosine vs BM25 blend |
| `OPENROUTER_API_KEY` | — | LLM summarization / facts |
| `BRAIN_FACT_EXTRACT` | `0` | Set `1` for live fact extract on session end |

Full matrix: [`docs/BRAIN_ENV_MATRIX.md`](docs/BRAIN_ENV_MATRIX.md).

---

## Troubleshooting

| Symptom | Check |
|---------|--------|
| MCP `Connection refused` | Is `brain_api` listening on 8787? |
| Fresh install, 0 memories | Normal until first save/ingest; confirm `brain.db` exists after first start |
| `database disk image is malformed` | Stop supervisor, snapshot corrupt DB, restore dated `brain.db.bak-*` (see AGENTS.md) |
| Viewer 401 on stream/search | Auth on but browser missing key — use injected SPA from API, or loopback auth settings |
| Port already in use | launchd may own it; `pkill` alone respawns — use `launchctl bootout` / kickstart |
| Search feels random / weak | Real ONNX model loaded? Not `BRAIN_EMBEDDER=mock`? |
| LLM titles / facts skip | `OPENROUTER_API_KEY` set? `BRAIN_LLM_PROVIDER=openrouter`? |

---

## Deeper documentation

| Doc | Covers |
|-----|--------|
| [`docs/BRAIN.md`](docs/BRAIN.md) | Session lifecycle, hooks, scoring, cleanup |
| [`docs/architecture/system-diagrams.md`](docs/architecture/system-diagrams.md) | Architecture diagrams |
| [`docs/BRAIN_ENV_MATRIX.md`](docs/BRAIN_ENV_MATRIX.md) | All env vars |
| [`docs/deploy/README.md`](docs/deploy/README.md) | Supervision, UI deploy, SLOs |
| [`docs/BRAIN_V0.2.0_CAPABILITIES.md`](docs/BRAIN_V0.2.0_CAPABILITIES.md) | Viewer, 3-layer MCP, symbols, privacy |
| [`docs/BRAIN_MEMORY_COMPREHENSIVE.md`](docs/BRAIN_MEMORY_COMPREHENSIVE.md) | Memory tools & retrieval patterns |
| [`brain/eval/README.md`](brain/eval/README.md) | Retrieval eval |
| [`AGENTS.md`](AGENTS.md) | Workspace facts for coding agents |
| [`CLAUDE.md`](CLAUDE.md) | Dev guidelines |

---

## License

See [`LICENSE.md`](LICENSE.md).
