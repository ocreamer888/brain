# Brain environment variables (dev / staging / production)

Single reference for processes that run **`brain_api`** (Rust) and for **Python clients** (MCP stdio, Claude Code hooks, scripts) that talk to the API.

See also: `docs/PHASE4_API.md` (endpoints, curl), `docs/plans/2026-04-08-rust-primary-production-ready.md` (roadmap).

## Rust server (`brain_api`)

| Variable | Dev (typical) | Staging / prod | Notes |
|----------|----------------|----------------|-------|
| `BRAIN_DB_PATH` | Path under repo or `~/Library/...` | Dedicated volume path | Same SQLite file the API serves. |
| `BRAIN_INDEX_PATH` | Paired with DB (e.g. `brain_index.bin`) | Paired with DB | Vector index; back up with DB. |
| `BRAIN_ONNX_PATH` | Dir with ONNX model | Same or read-only mount | Optional; API falls back to mock if missing. |
| `BRAIN_API_BIND` | `127.0.0.1:8787` | `127.0.0.1:PORT` or `0.0.0.0:PORT` behind proxy | **Do not** expose plain HTTP publicly; use TLS terminator. |
| `BRAIN_API_KEY` | Long random string | Rotated secret | Empty disables auth only for local experiments. |
| `BRAIN_API_AUTH_REQUIRED` | **`true`** (2026-05-25+, viewer handles auth) | `true` | `/health` stays unauthenticated. Viewer works with auth enabled — Rust injects the key into `index.html` at serve time. |
| `BRAIN_API_RATE_LIMIT_MAX_REQUESTS` | default `120` | Tune per instance | Per client id. |
| `BRAIN_API_RATE_LIMIT_WINDOW_SECONDS` | default `60` | Tune per instance | |
| `ANTHROPIC_API_KEY` | optional | optional | For `/reflect` and LLM features. |
| `OPENROUTER_API_KEY` | optional | optional | Alternative LLM provider. |
| `BRAIN_LLM_PROVIDER` | `auto` | `auto` or fixed | See Phase 4 doc. |

## Python clients (hooks, MCP, maintenance scripts)

| Variable | Dev | Staging / prod | Notes |
|----------|-----|----------------|-------|
| `BRAIN_BACKEND` | `api` (default in code) | **`api`** | Set explicitly in supervised units to avoid accidental `python` mode. |
| `BRAIN_API_URL` | `http://127.0.0.1:8787` | Match real bind / internal URL | Must match where `brain_api` listens. |
| `BRAIN_API_KEY` | Same as server | Same as server | Sent as `x-api-key`. |

## Session hooks (session_end.py)

| Variable | Default | Notes |
|----------|---------|-------|
| `BRAIN_AUTO_INGEST_CLAUDE_CODE` | `0` | Set to `1` to run `07_ingest_claude_code.py --no-llm` in background after each session export. Disabled by default. |
| `BRAIN_FACT_EXTRACT` | `0` | Set to `1` to run `backfill_facts.py --file <export>` in background after each session. Requires `OPENROUTER_API_KEY`. |

## Backfill / eval scripts

| Variable | Default | Notes |
|----------|---------|-------|
| `BRAIN_DB_PATH` | `~/.brain/brain.db` | Used by `backfill_facts.py --from-db`, `retrieval_eval_kfold.py`, and the fact curator's direct SQLite helpers. Prefers `brain/rust/brain.db` if it exists. |
| `OPENROUTER_API_KEY` | — | Required for `extract_facts()` and the LLM tiebreaker in `curate_facts()`. |

`backfill_facts.py` source modes and their defaults:

| Flag | Source | Default path |
|------|--------|-------------|
| `--all` | Claude Code session JSONs | `brain/bootstrap/sessions_export/` |
| `--from-perplexity` | Perplexity thread JSONs | `brain/bootstrap/perplexity_exports/` |
| `--from-db --source obsidian` | Memories in brain.db by source tag | `BRAIN_DB_PATH` |
| `--from-cursor-db` | Cursor chat history (vscdb) | `cursor-recovery-backup/state.vscdb.clean` |

## Obsidian / books ingest (bootstrap scripts)

| Variable | Default | Notes |
|----------|---------|--------|
| `OBSIDIAN_VAULT_PATH` | `<repo>/vault` | Override if the vault root lives elsewhere. |
| `OBSIDIAN_CHUNK_WORDS` | `1500` | Files with more words than this are chunked before save. |
| `OBSIDIAN_CHUNK_STRATEGY` | `headers` | `headers` (split on markdown headings) or `paragraph` (merge paragraphs). |
| `OBSIDIAN_BOOKS_DIR` | `<repo>/vault/03 Resources/Books` | Used by `08_ingest_books.py`. |

## Checklist before calling an environment “production-ready”

1. **`BRAIN_BACKEND=api`** everywhere hooks and MCP run.
2. **`BRAIN_API_KEY`** set and not committed; auth enabled for non-local binds.
3. API reachable only on loopback or private network, or behind TLS proxy.
4. **`BRAIN_DB_PATH` / `BRAIN_INDEX_PATH`** on durable storage with backup policy.
5. Monitor **`GET /health`** (and optionally **`GET /stats`**) from your stack.

Supervision examples: `docs/deploy/README.md`.


<!-- brain-linker -->
## Related
- [[brain-graph/solution/Edited Usersmacm1airDocumentsAIbrainrustsrcconfig.rs Runtime]]
- [[brain-graph/conversation/User]]
- [[brain-graph/solution/Edited Usersmacm1airDocumentsAIbrainrustsrcbrain.rs fn test_]]
- [[brain-graph/solution/Edited Usersmacm1airDocumentsAIbrainrustsrcbinbrain_api.rs s]]
- [[brain-graph/solution/Edited Usersmacm1airDocumentsAIbrainrustsrcbrain.rs pub stru]]
<!-- /brain-linker -->
