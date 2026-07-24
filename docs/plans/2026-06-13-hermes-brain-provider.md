# Implementation Plan: Brain as a Hermes Memory Provider

**Date:** 2026-06-13
**Status:** Proposed — awaiting approval
**Goal:** Let Hermes drive the **same brain** as Claude Code, with the **same behavior** (auto-save at session end, context injection at start, save/search tools), via Hermes's native memory-provider extension point.

---

## Background

The brain is **harness-agnostic**. Verified from source:
- **Summarizer** (`brain/core/summarizer.py`) → uses local **Ollama**, not Claude's model.
- **Storage** (`brain/api_client.py`) → hits the **Rust API on `127.0.0.1:8787`** via env vars (`BRAIN_BACKEND`, `BRAIN_API_URL`, `BRAIN_API_KEY`).
- The Claude hook (`brain/hooks/session_end.py`) is a **thin adapter** — it parses Claude's stdin JSON, loads the transcript, then calls brain core (`summarize_session`, `save_memory`, reflect, cleanup).

Hermes has the matching extension point: a **memory provider plugin** (`plugins/memory/<name>/`), with lifecycle methods (`initialize`, `prefetch`, `sync_turn`, `on_session_end`, `get_tool_schemas`, `handle_tool_call`). Both callers hit the **same Rust API → same `brain.db`** → identical memories, dedup, reflection, retrieval.

Why NOT reuse Claude's hook files literally: they expect Claude's stdin contract (`session_id`, `transcript_path`, `cwd`, `ended_at`) that Hermes does not send. Instead we share the *orchestration logic* underneath the hook.

---

## Core principle: one brain, one logic path, two thin adapters

```
                  ┌──────────────────────────────┐
Claude Code ─────▶│ session_end.py (stdin adapter) │──┐
                  └──────────────────────────────┘   │
                                                      ▼
                                   brain/core/session_ingest.py  ──▶ Rust API :8787 ──▶ brain.db
                                   (3-pass extract + reflect +        (same as today)
                                    cleanup — SHARED)
                                                      ▲
                  ┌──────────────────────────────┐   │
Hermes ──────────▶│ plugins/memory/brain (provider)│──┘
                  └──────────────────────────────┘
```

All saves/searches already route through the Rust API in `brain/api_client.py`, so storage, dedup, reflection, and retrieval are identical regardless of caller.

---

## Files

### A. Brain repo (`~/Documents/AI/brain/`) — refactor for reuse

**1. NEW `brain/core/session_ingest.py`** — extract reusable orchestration out of `session_end.py`:
- `ingest_session(messages, project, session_id, ended_at)` → runs existing 3-pass extraction (`save_session_extracted`, already a function) + edit-group flush.
- `run_post_session_maintenance()` → the background reflect + cleanup (`run_cleanup.py`) + spool replay currently inlined in `session_end.py`.

**2. EDIT `brain/hooks/session_end.py`** — becomes a pure stdin adapter: parse Claude's JSON → load transcript → call `ingest_session(...)` + `run_post_session_maintenance()`. **Behavior-neutral for Claude** — primary test target.

### B. Hermes repo (`~/.hermes/hermes-agent/plugins/memory/brain/`) — NEW provider

**3. NEW `plugins/memory/brain/__init__.py`** — `BrainMemoryProvider(MemoryProvider)`, modeled on the mem0 plugin:

| Method | Maps to Claude hook | Implementation |
|---|---|---|
| `name` | — | returns `"brain"` |
| `is_available()` | — | true if brain repo path resolvable + API key present |
| `initialize(session_id, **kw)` | — | add brain repo root to `sys.path`; read `BRAIN_API_URL`/`BRAIN_API_KEY`; resolve project from `kwargs["agent_workspace"]`/cwd |
| `system_prompt_block()` | — | short "Brain active" note + tool hints |
| `queue_prefetch()` / `prefetch()` | `session_start.py` | background `brain.api_client.search(...)` → format recent summaries + relevant memories (reuse `filter_session_summaries`/`build_query`) |
| `sync_turn(user, asst, messages)` | `post_tool_use.py` | optional lightweight per-turn save (OFF by default to match Claude) |
| `on_session_end(messages)` | `session_end.py` | **main path** — normalize messages → call `brain.core.session_ingest.ingest_session(...)` + `run_post_session_maintenance()` |
| `get_tool_schemas()` + `handle_tool_call()` | MCP save/search tools | expose `brain_search` + `brain_save` → `brain.api_client.search`/`save_memory` |
| `shutdown()` | — | join background threads |
| `register(ctx)` | — | `ctx.register_memory_provider(BrainMemoryProvider())` |

### C. Config

**4. EDIT `~/.hermes/config.yaml`** → `memory.provider: brain` (claims the single external-provider slot).
**5. Env** → `BRAIN_REPO_ROOT=~/Documents/AI`, `BRAIN_API_URL=http://127.0.0.1:8787`, `BRAIN_API_KEY=<key>` (Rust API requires a key).

---

## Message-shape adapter

Claude transcript = JSONL objects; Hermes = OpenAI-style `{"role","content"}` (with tool calls). `summarize_session()` and the extractors expect a specific shape. The provider's `on_session_end` includes a small `_to_brain_messages(messages)` normalizer. **Verify exact expected shape against `core/summarizer.py` during build** — do not guess.

---

## Test strategy

1. **Brain refactor (behavior-neutral):** existing `brain/tests/test_session_end_export.py` + `test_mcp_eval.py` must pass unchanged after extracting `session_ingest.py`.
2. **New provider unit tests** (Hermes side, mirror `tests/agent/test_memory_provider.py` fakes): assert `on_session_end` calls `ingest_session` with normalized messages; `prefetch` formats search results; tools route correctly.
3. **Integration smoke:** short Hermes CLI session → exit → confirm a `project_context` "Session …" memory appears via `get_stats_tool`/`search_index` against the same DB.
4. **Regression:** confirm Claude Code session-end still saves (run one Claude session after refactor).

---

## Safety / rollout

- Refactor is behavior-neutral; brain tests gate it.
- Provider is best-effort (try/except like mem0) — a brain outage never breaks a Hermes turn.
- Reversible: `memory.provider: ''` disables instantly.
- Brain `.db` is shared — both harnesses write the same store (the point). Session dedup guard (`find_or_create_export_path`) prevents double-saves per `session_id`.

---

## Open risks

1. **API key** — need the `BRAIN_API_KEY` value (or where it's stored) to wire storage.
2. **sys.path import coupling** — provider imports brain Python by filesystem path. Fine for single Mac Studio; more decoupled long-term option is a `/ingest_session` HTTP endpoint on the Rust API (defer).
3. **Ollama must be running** for summaries — same requirement as Claude today.
4. **Two Python envs** — Hermes venv needs brain's deps (`requests` at minimum; `sentence_transformers` not needed since storage goes via HTTP API). Low risk.

---

## Effort

~1 day. Brain refactor (~2h, low risk) + provider (~4h) + tests (~2h).

---

## Open questions before build

1. Where is the `BRAIN_API_KEY`? (env var, `.env`, or config file)
2. `sync_turn` per-turn saves **on** (more memories, more API calls) or **off** to exactly match Claude's save-at-session-end? **Recommendation: off** to start — identical to Claude.
