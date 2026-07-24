# Brain v0.2.0 — New Capabilities

> **Tag:** `v0.2.0-feature-parity` (commit `d7e0d86`)
> **Merged:** 2026-04-20
> **Post-rebase main:** `15faa79` (includes admin endpoints + timestamp support)

Nine user-facing capabilities shipped together in the claude-mem feature-parity work, plus the admin-endpoints WIP that landed immediately after. This doc is the canonical summary; per-subsystem details live in `BRAIN.md`, `PHASE4_API.md`, and `claude-code-hook-system.md`.

---

## Summary table

| # | Capability | Entry point | Replaces |
|---|---|---|---|
| 1 | Mid-session context injection | `UserPromptSubmit` hook | nothing (net new) |
| 2 | Code-aware search via tree-sitter symbols | `brain_post_tool_use` | opaque file diffs |
| 3 | 3-layer progressive-disclosure MCP | `search_index` → `timeline_tool` → `get_observations_tool` | single fat `search_brain` |
| 4 | Native Rust MCP server | `brain_mcp` bin | Python `brain/mcp/server.py` wrapper |
| 5 | `<private>` block stripping | auto at `save_memory` entry | nothing (secrets would leak) |
| 6 | Job queue with max-attempts | `jobs` table + `brain::worker` | nothing (silent failures) |
| 7 | Admin: list / delete memories | `POST /list`, `POST /delete` | manual SQLite surgery |
| 8 | Event-time timestamps | `timestamp` field on `/save` | ingest-time only (`Utc::now()`) |
| 9 | Live web viewer + SSE stream | `http://127.0.0.1:8787/` | no realtime visibility |

---

## 1. Mid-session context injection — `UserPromptSubmit`

**Before:** Context was injected only at `SessionStart`. If the conversation drifted mid-session, the brain stayed silent unless Claude explicitly called `search_brain`.

**Now:** A new hook bin `brain_user_prompt_submit` runs on every user prompt. It POSTs the prompt text to `/v1/search` and injects the top 5 hits (bounded to ≤12 lines) into Claude's context.

**Wire up** in `~/.claude/settings.json`:

```json
{
  "hooks": {
    "UserPromptSubmit": [
      {
        "hooks": [
          { "type": "command", "command": "/path/to/brain/rust/target/release/brain_user_prompt_submit" }
        ]
      }
    ]
  }
}
```

**Env:** `BRAIN_API_URL` (default `http://127.0.0.1:8787`). Errors go to stderr, not stdout — hook stays soft-fail.

Empty results emit nothing, so prompts aren't polluted with an empty header when the brain has no relevant context.

---

## 2. Code-aware search — tree-sitter symbols

**Before:** Edits were ingested as raw diffs. Searching `"save_memory"` matched prose mentions but not the actual function definition.

**Now:** `brain_post_tool_use` runs tree-sitter on file edits and appends `sym:<name>` tags for each function/class. A `PostToolUse` on `brain.rs` editing `fn save_memory` now produces tags like `["sym:save_memory"]` — directly searchable.

**Supported languages:** Rust (`.rs`), TypeScript (`.ts`, `.tsx`, `.mts`, `.cts`), Python (`.py`).

**Add a language:** extend `brain/rust/src/symbols.rs` with a new branch in `extract_symbols`.

---

## 3. Progressive-disclosure MCP — 3-layer search pattern

**Before:** Calling `search_brain` returned ~10 fat rows (~500–1000 tokens each), bloating Claude's context window for minor lookups.

**Now:** Three MCP tools, each a layer of detail:

| Layer | Tool | Returns | Token cost |
|---|---|---|---|
| 1 | `search_index(query)` | compact rows: `[#id] type \| project \| snippet` | ~50–100 / row |
| 2 | `timeline_tool(anchor_id)` | chronological neighbors by timestamp | ~100–200 / row |
| 3 | `get_observations_tool(ids)` | full content for filtered IDs | ~500–1000 / row |

**Workflow:** get an index, decide which IDs matter, fetch details. Roughly **10× savings** vs. the one-shot `search_brain` call.

`search_brain` still exists for backward-compat but should be reserved for "get me everything".

HTTP equivalents: `POST /v1/search_index`, `POST /v1/timeline`, `POST /v1/get_observations`.

---

## 4. Native Rust MCP server — `brain_mcp`

**Before:** MCP ran as Python (`brain/mcp/server.py`) wrapping the Rust HTTP API. Extra process, extra Python startup, extra dependency.

**Now:** `brain_mcp` is a native stdio MCP server built on the `rmcp` crate. It registers the three progressive-disclosure tools and proxies to `brain_api` over HTTP.

**`.mcp.json`:**

```json
{
  "mcpServers": {
    "brain": {
      "command": "cargo",
      "args": ["run", "--quiet", "--bin", "brain_mcp"],
      "cwd": "brain/rust",
      "env": { "BRAIN_API_URL": "http://127.0.0.1:8787" }
    }
  }
}
```

**For production** (drops the cargo compile step at startup):

```bash
cd brain/rust && cargo build --release --bin brain_mcp
```

Then in `.mcp.json`:

```json
"command": "/Users/macm1air/Documents/AI/brain/rust/target/release/brain_mcp"
```

---

## 5. `<private>` block stripping

**Before:** Pasting an API key into chat meant it would be embedded, indexed, and searchable forever.

**Now:** Any text wrapped in `<private>...</private>` is stripped at the `save_memory` entry point before embedding. Multiline, case-insensitive, handles multiple blocks.

**Example:**

```
Keep this.
<private>
OPENAI_API_KEY=sk-abc123
</private>
Also keep this.
```

→ stored as `"Keep this.\n\nAlso keep this."`

**Implementation:** `brain/rust/src/privacy.rs`. Single regex, no external dep beyond `regex = "1"`.

---

## 6. Retry queue — `jobs` table + worker

**Before:** A failed compression, API timeout, or OOM during ingestion left no trace and no retry path.

**Now:** Async work goes into a SQLite `jobs` table. A background loop (`brain::worker::process_once`) runs every 5 seconds inside `brain_api` and drains pending jobs. Failures increment `attempts`; after 5 attempts a job moves to `status='failed'` and the worker stops touching it.

**Schema:**

```sql
CREATE TABLE jobs (
  id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  payload TEXT NOT NULL,
  attempts INTEGER NOT NULL DEFAULT 0,
  last_error TEXT,
  status TEXT NOT NULL DEFAULT 'pending',
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
```

**Adding a job kind:** extend the `match job.kind.as_str()` in `brain/rust/src/worker.rs`.

**Not enabled for** `BRAIN_DB_PATH=:memory:` — separate connections wouldn't share the in-memory DB.

---

## 7. Admin endpoints — `/list` and `/delete`

**Before:** Inspecting or pruning memories meant opening the SQLite file with a viewer or writing ad-hoc scripts.

**Now:** Two HTTP endpoints behind the same auth as everything else:

**`POST /list`** — paginated, filterable:

```json
{ "source": "perplexity", "project": "AI", "limit": 100, "offset": 0 }
```

Returns `{ total, returned, items: [...] }`.

**`POST /delete`** — batch delete by IDs:

```json
{ "ids": ["uuid-1", "uuid-2"] }
```

Returns `{ deleted: 2 }`.

**Python wrappers:** `brain.api_client.list_memories()`, `brain.api_client.delete_memories()`.

---

## 8. Event-time timestamps

**Before:** Every memory was stamped with `Utc::now()` at ingest time. A Perplexity thread from 2024 ingested today looked like it happened today. "When did we first discuss X?" always returned today's date.

**Now:** `/save` and `/save-batch` accept an optional RFC3339 `timestamp` field representing the **event time** (session ended_at, Perplexity `created_at`, file `mtime`). Omit the field for live captures — the server still falls back to `Utc::now()`.

**Python client:** `save_memory(..., timestamp="2024-11-03T14:22:00Z")`.

**Ingest pipelines updated to use event time:** `05_ingest_claw.py`, `06_ingest_perplexity.py`, `07_ingest_claude_code.py`, `08_ingest_books.py`, `09_ingest_obsidian.py`.

Critical because retrieval ordering and timeline context depend on correct timestamps.

---

## 9. Live web viewer + SSE stream

**Before:** Debugging "did the hook fire? did the memory save?" meant tailing logs and running `sqlite3` queries.

**Now:** When `brain_api` is running, open **http://127.0.0.1:8787/** for:

- **Live stream** via Server-Sent Events (`GET /v1/stream`) — every `save_memory` broadcasts a `MemoryEvent` with id, snippet, type, timestamp
- **Search box** wired to `POST /v1/search_index` with 200ms debounce
- **Static assets** embedded into the `brain_api` binary via `rust-embed` — no filesystem dependency at runtime

**Auth (2026-05-25+):** viewer works with `BRAIN_API_AUTH_REQUIRED=true`. The Rust server injects `window.__BRAIN_API_KEY__` into `index.html` at serve time; the React SPA reads it and sends `x-api-key` on every request. SSE uses `?key=` query param. `AUTH_REQUIRED=0` workaround is no longer needed.

**Always-on:** on this machine the launchd agent (`~/Library/LaunchAgents/com.brain.api.plist`) starts `brain_api` at login with `KeepAlive=true`, so the viewer URL is live whenever the Mac is up. Supervision details, control commands, and port-conflict recovery: `docs/deploy/README.md`.

**Viewer (2026-05-25):** rewritten as React 18 + Tailwind v3 + Vite SPA. Four tabs: Dashboard (stat cards, SSE feed, eval summary), Search (semantic search + timeline drawer), Curate (promote/reject facts), Eval (run history + P@1 metrics). Source: `brain/rust/ui/`. Build output embedded via rust-embed: `brain/rust/static/`.

---

## Test coverage added

- 104 Rust tests (up from 97 pre-parity)
- 70 Python unit tests
- 4 integration tests, including `brain/tests/integration/test_claude_mem_parity.py` (end-to-end HTTP smoke: private stripping → search_index → get_observations → timeline → SSE)

Run everything:

```bash
cd brain/rust && cargo test
cd /Users/macm1air/Documents/AI && python3 -m pytest brain/tests/
BRAIN_RUN_INTEGRATION=1 python3 -m pytest brain/tests/integration/
```

---

## Not shipped (deferred)

| Feature | Why deferred |
|---|---|
| i18n observations (Chinese/Japanese/etc.) | Internal tool; English only |
| Plugin marketplace installer | Manual install only |
| Web UI cookie-based auth | Not worth it for localhost dev |
| Cleanup of `status='done'` rows in `jobs` | Unbounded growth, but tiny rows — revisit at 100k+ |
| Configurable worker poll interval | Hard-coded 5s — add `BRAIN_WORKER_POLL_SECS` if it becomes annoying |
| Tree-sitter for more languages (Go, Java, C++, etc.) | Add on demand; 3 languages covers our repo today |

---

## Related docs

- `docs/BRAIN.md` — system overview and architecture
- `docs/PHASE4_API.md` — HTTP API reference (all endpoints)
- `docs/claude-code-hook-system.md` — hook lifecycle including UserPromptSubmit
- `docs/plans/2026-04-20-claude-mem-gap-closure.md` — the execution plan this work followed
