# Phase 4 API (Axum) — Quick Guide

## Purpose

Expose the Rust brain as an HTTP service so other processes/tools can use it via standard API calls.

Current binary: `brain/rust/src/bin/brain_api.rs`

## Start The API

**On this dev machine `brain_api` is auto-started by launchd** (`~/Library/LaunchAgents/com.brain.api.plist`, `RunAtLoad=true`, `KeepAlive=true`). You should not need to start it manually. See `docs/deploy/README.md` for the canonical supervision setup and port-conflict recovery.

The manual invocation below is for **first-time bring-up on a new machine** or when you explicitly `launchctl bootout` the agent to run a local debug build.

From repo root:

```bash
cd /Users/macm1air/Documents/AI/brain/rust
BRAIN_DB_PATH=/Users/macm1air/Documents/AI/brain/rust/brain.db \
BRAIN_INDEX_PATH=/Users/macm1air/Documents/AI/brain/rust/brain_index.bin \
BRAIN_ONNX_PATH=/Users/macm1air/Documents/AI/brain/rust/models/all-mpnet-base-v2-onnx \
BRAIN_API_BIND=127.0.0.1:8787 \
BRAIN_API_KEY=local-dev-key \
BRAIN_API_AUTH_REQUIRED=true \
BRAIN_API_RATE_LIMIT_MAX_REQUESTS=120 \
BRAIN_API_RATE_LIMIT_WINDOW_SECONDS=60 \
cargo run --bin brain_api
```

Notes:

- If `BRAIN_ONNX_PATH` is missing or fails to load, API falls back to mock embedder.
- To use reflection endpoint with real LLM, set either `ANTHROPIC_API_KEY` or `OPENROUTER_API_KEY`.
- OpenRouter summarize default is `google/gemma-3-27b-it:free`.
- OpenRouter reflect primary default is `meta-llama/llama-3.3-70b-instruct`.
- OpenRouter reflect fallback default is `google/gemma-3-27b-it`.
- If `BRAIN_API_AUTH_REQUIRED=true`, send either `x-api-key` or `Authorization: Bearer <key>`.

## API Security and Limits

Env vars used by `brain_api`:

- `BRAIN_API_BIND` (default `127.0.0.1:8787`)
- `BRAIN_API_KEY` (default empty)
- `BRAIN_API_AUTH_REQUIRED` (default `true` when key is set, else `false`)
- `BRAIN_API_RATE_LIMIT_MAX_REQUESTS` (default `120`)
- `BRAIN_API_RATE_LIMIT_WINDOW_SECONDS` (default `60`)
- `OPENROUTER_API_KEY` (optional fallback LLM provider)
- `OPENROUTER_SUMMARIZE_MODEL` (optional override)
- `OPENROUTER_REFLECT_MODEL` (optional override)
- `OPENROUTER_SUMMARIZE_FALLBACK_MODEL` (optional failover model)
- `OPENROUTER_REFLECT_FALLBACK_MODEL` (optional failover model)
- `BRAIN_LLM_PROVIDER` (`auto` default, or `openrouter`, `anthropic`)

Behavior:

- `/health` is always open.
- Other endpoints require key when auth is enabled.
- Rate limiting is per client (`x-forwarded-for`, else `local`).

## Endpoints

### `GET /health`

Health check.

Response:

```json
{"status":"ok","bind":"127.0.0.1:8787"}
```

### `GET /stats`

Returns brain stats for the configured DB.

Response:

```json
{
  "total_memories": 1538,
  "total_sessions": 127,
  "save_count_this_session": 0
}
```

### `POST /save`

Create/save one memory.

Request body:

```json
{
  "content": "axum api smoke test",
  "memory_type": "solution",
  "tags": ["api"],
  "project": "AI",
  "session_id": "optional-session-id",
  "source": "claude_code_session",
  "file_path": "vault/01 Projects/Foo/note.md",
  "title": "Foo — Section A",
  "timestamp": "2024-11-03T14:22:00Z"
}
```

Optional **`file_path`** and **`title`** are stored in SQLite and returned on `POST /search` inside each hit’s `metadata` (provenance for vault-backed memories).

Optional **`timestamp`** (RFC3339) represents the **event time** of the memory (e.g. session `ended_at`, Perplexity `created_at`, file `mtime`). Omit for live captures — the server falls back to `Utc::now()`. Critical for retrieval ordering and timeline context when backfilling historical sources. Also supported on `/save-batch` items.

Any text wrapped in `<private>...</private>` inside `content` is stripped at the entry point before embedding. Case-insensitive, multiline, handles multiple blocks. See `brain/rust/src/privacy.rs`.

**`<private>` block stripping** also auto-scrubs secrets at the `save_memory` boundary. Implementation: `brain/rust/src/privacy.rs`.

The server broadcasts a `MemoryEvent` on the SSE channel (`GET /v1/stream`) for every successful save — id, snippet, type, timestamp.

Allowed `memory_type`:

- `solution`
- `decision`
- `conversation`
- `pattern`
- `project_context`
- `error_lesson`

Allowed `source`:

- `claude_code_session`
- `reflection`
- `cursor_history`
- `claw_code`
- `perplexity`
- `obsidian`
- `obsidian_books`

Response:

```json
{"id":"<uuid>"}
```

### `POST /save-batch`

Batch save many memories in one request.

Request body:

```json
{
  "items": [
    {
      "content": "memory one",
      "memory_type": "solution",
      "tags": ["batch"],
      "project": "AI",
      "source": "claude_code_session"
    },
    {
      "content": "memory two",
      "memory_type": "pattern",
      "tags": ["batch"],
      "project": "AI",
      "file_path": "vault/02 Areas/x/note.md",
      "title": "x"
    }
  ]
}
```

Response:

```json
{
  "accepted": 2,
  "failed": 0,
  "results": [
    {"index":0,"id":"<uuid>","error":null},
    {"index":1,"id":"<uuid>","error":null}
  ]
}
```

### `POST /search`

Semantic search.

Request body:

```json
{
  "query": "phase 6 migration",
  "n": 5,
  "project": "AI",
  "memory_type": "solution",
  "exclude_superseded": true
}
```

`project` and `memory_type` are optional filters. `exclude_superseded` defaults to `true` — superseded facts are hidden from results unless explicitly set to `false`.

Response:

```json
{
  "results": [
    {
      "id": "uuid",
      "content": "text",
      "metadata": {
        "type": "solution",
        "project": "AI",
        "tags": "a,b",
        "timestamp": "2026-04-10T12:00:00Z",
        "source": "obsidian",
        "session_id": "",
        "importance": 0.5,
        "file_path": "vault/01 Projects/Foo/note.md",
        "thread_id": null,
        "title": "Foo — Section A"
      },
      "distance": 0.12
    }
  ]
}
```

`metadata.file_path` / `metadata.title` are `null` when unset. `type` is the serialized `memory_type`.

### `POST /v1/search_index`

**Layer 1 of progressive disclosure.** Compact rows — the cheapest way to decide which memories to drill into.

Request body:

```json
{ "query": "save_memory", "n": 10, "project": "AI", "memory_type": "solution", "exclude_superseded": true }
```

`exclude_superseded` defaults to `true`. Pass `false` to include superseded facts (e.g. for audit or backfill review).

Response (per row is ~50–100 tokens vs. ~500–1000 for `/search`):

```json
{
  "results": [
    {
      "id": "uuid",
      "memory_type": "solution",
      "project": "AI",
      "snippet": "first 120 chars of content...",
      "timestamp": "2026-04-18T09:12:00Z",
      "distance": 0.12,
      "parent_id": null
    }
  ]
}
```

`parent_id` is non-null only for `type=fact` memories — it is the ID of the source `Episode` from which the fact was extracted. Use `/get-episode` to expand it.

### `GET /get-episode?id=<id>`

Expand a fact to its source episode. Works for both `type=fact` and non-fact IDs:

- **Fact ID** → resolves `parent_id`, returns the parent `Episode` memory.
- **Any other ID** → returns the memory directly.

Use this after `search_index` returns a row with a non-null `parent_id` to read the full episode context that produced the fact.

```bash
curl -s "http://127.0.0.1:8787/get-episode?id=<fact-or-episode-id>" \
  -H "x-api-key: local-dev-key"
```

Response: full memory JSON (same shape as a `/search` hit). Returns `{"error": "..."}` if ID not found.

### `POST /v1/get_observations`

**Layer 3.** Full content for explicit IDs (skip distance-ranked tail; no embedding computed).

Request body:

```json
{ "ids": ["uuid-1", "uuid-2"] }
```

Response: array of full memory rows matching `/search` hit shape.

### `POST /v1/timeline`

**Layer 2.** Chronological neighbors of an anchor memory by event timestamp — useful for reconstructing "what happened around this decision".

Request body:

```json
{ "anchor_id": "uuid", "before": 3, "after": 3 }
```

Response: array of full rows ordered by `timestamp`.

### `POST /v1/search`

Same shape as `POST /search` but mounted under the `/v1/` namespace used by hooks (`brain_user_prompt_submit`) and the web viewer.

### `GET /v1/stream` (Server-Sent Events)

Live SSE stream of `MemoryEvent` objects emitted by `save_memory`. Requires auth when enabled. Connect with an `EventSource` in the browser (allowed when `BRAIN_API_AUTH_REQUIRED=0` for local dev) or `curl -N`.

Event body:

```json
{ "id": "uuid", "snippet": "...", "type": "solution", "timestamp": "2026-04-20T..." }
```

### `POST /list`

Admin: paginated list of memories with filters.

Request body:

```json
{ "source": "perplexity", "project": "AI", "limit": 100, "offset": 0 }
```

Response:

```json
{ "total": 912, "returned": 100, "items": [ /* full rows */ ] }
```

Python wrapper: `brain.api_client.list_memories(...)`.

### `POST /delete`

Admin: batch delete by IDs.

Request body:

```json
{ "ids": ["uuid-1", "uuid-2"] }
```

Response:

```json
{ "deleted": 2 }
```

Python wrapper: `brain.api_client.delete_memories(ids)`.

### `GET /` and `/static/*`

Live web viewer — static HTML/JS embedded into the `brain_api` binary via `rust-embed`. Public (no auth) so the browser can fetch assets. The backing endpoints (`/v1/stream`, `/v1/search_index`) still require auth, so for local browser use set `BRAIN_API_AUTH_REQUIRED=0`. **Do not expose to untrusted networks with auth disabled.**

### `POST /reflect`

Triggers reflection using configured LLM client.

- Requires `ANTHROPIC_API_KEY` for real reflection.
- Without key, endpoint returns error from `trigger_reflection`.

Response:

```json
{
  "consolidated": [],
  "patterns": [],
  "to_delete_indices": []
}
```

## Curl Examples

```bash
# health
curl -sS http://127.0.0.1:8787/health

# stats
curl -sS http://127.0.0.1:8787/stats

# save
curl -sS -X POST http://127.0.0.1:8787/save \
  -H "content-type: application/json" \
  -H "x-api-key: local-dev-key" \
  -d '{"content":"api test","memory_type":"solution","tags":["api"],"project":"AI"}'

# search
curl -sS -X POST http://127.0.0.1:8787/search \
  -H "content-type: application/json" \
  -H "x-api-key: local-dev-key" \
  -d '{"query":"api test","n":3}'

# save batch
curl -sS -X POST http://127.0.0.1:8787/save-batch \
  -H "content-type: application/json" \
  -H "x-api-key: local-dev-key" \
  -d '{"items":[{"content":"batch-1","memory_type":"solution","tags":["batch"],"project":"AI"},{"content":"batch-2","memory_type":"pattern","tags":["batch"],"project":"AI"}]}'

# reflect
curl -sS -X POST http://127.0.0.1:8787/reflect \
  -H "x-api-key: local-dev-key"

# progressive disclosure — layer 1 (superseded excluded by default)
curl -sS -X POST http://127.0.0.1:8787/v1/search_index \
  -H "content-type: application/json" \
  -H "x-api-key: local-dev-key" \
  -d '{"query":"save_memory","n":10}'

# expand a fact to its source episode
curl -sS "http://127.0.0.1:8787/get-episode?id=<fact-id>" \
  -H "x-api-key: local-dev-key"

# include superseded facts in search (audit/backfill review)
curl -sS -X POST http://127.0.0.1:8787/v1/search_index \
  -H "content-type: application/json" \
  -H "x-api-key: local-dev-key" \
  -d '{"query":"wallet auth","n":10,"exclude_superseded":false}'

# layer 3: fetch full content for specific IDs
curl -sS -X POST http://127.0.0.1:8787/v1/get_observations \
  -H "content-type: application/json" \
  -H "x-api-key: local-dev-key" \
  -d '{"ids":["uuid-1","uuid-2"]}'

# timeline around an anchor
curl -sS -X POST http://127.0.0.1:8787/v1/timeline \
  -H "content-type: application/json" \
  -H "x-api-key: local-dev-key" \
  -d '{"anchor_id":"uuid-1","before":3,"after":3}'

# admin: list (paginated)
curl -sS -X POST http://127.0.0.1:8787/list \
  -H "content-type: application/json" \
  -H "x-api-key: local-dev-key" \
  -d '{"source":"perplexity","limit":10,"offset":0}'

# admin: delete
curl -sS -X POST http://127.0.0.1:8787/delete \
  -H "content-type: application/json" \
  -H "x-api-key: local-dev-key" \
  -d '{"ids":["uuid-1"]}'

# SSE live stream (keep connection open)
curl -N -H "x-api-key: local-dev-key" http://127.0.0.1:8787/v1/stream
```

## Background Worker

`brain_api` spawns a background loop (`brain::worker::process_once`) every 5s that drains the SQLite `jobs` table (async retries for compression, summarization, etc.). Failures bump `attempts`; after 5 attempts a job moves to `status='failed'` and is left alone. Not enabled for `BRAIN_DB_PATH=:memory:` (separate connections wouldn't share the in-memory DB). Full detail: `docs/BRAIN_V0.2.0_CAPABILITIES.md` §6.

## MCP and Hooks Cutover

- MCP default is now native Rust `brain_mcp` (stdio, `rmcp` crate) — see `.mcp.json` in repo root. The Python stdio server is retained for manual QA (`BRAIN_BACKEND=python`).
- `BRAIN_BACKEND=api` (default) routes Python hooks through HTTP API.
- `BRAIN_BACKEND=python` rolls back to direct Python memory path.
- Optional endpoint override: `BRAIN_API_URL` (default `http://127.0.0.1:8787`) — used by `brain_mcp`, `brain_user_prompt_submit`, and Python hook clients.

**Production:** set env vars explicitly in supervised units; see `docs/BRAIN_ENV_MATRIX.md` and `docs/deploy/README.md`.

## Troubleshooting

- `python` not found: use `python3` in this workspace.
- `total_memories` unexpectedly `0`: wrong `BRAIN_DB_PATH`/`BRAIN_INDEX_PATH`.
- poor search quality: ensure `BRAIN_ONNX_PATH` points to valid model directory; for vault-tuned chunking use `brain/tools/retrieval_eval.py` and `brain/eval/README.md`.
- server bind error: set `BRAIN_API_BIND` to another port (e.g. `127.0.0.1:8788`).
<!-- brain-linker -->
## Related
- [[brain-graph/solution/Edited Usersmacm1airDocumentsAIbrainrustsrcbrain.rs Ok(Self ]]
- [[brain-graph/conversation/User]]
- [[brain-graph/solution/Edited Usersmacm1airDocumentsAIbrainrustsrcbrain.rs pub stru]]
- [[brain-graph/pattern/Edited Usersmacm1airDocumentsAIbrainrustsrcbrain.rs ( memori]]
- [[brain-graph/solution/Edited Usersmacm1airDocumentsAIbrainrustsrcbrain.rs fn test_]]
<!-- /brain-linker -->
