# Mac Studio + Local Ollama Migration

**Date:** 2026-06-07/08 · **Host:** Mac Studio (Apple M4 Max, 16-core, 64 GB) · **Status:** ✅ live

This documents the session that finished moving Brain off cloud LLMs (OpenRouter/Anthropic)
onto **local Ollama** on the Mac Studio, wired Claude Code hooks, fixed the MCP launcher,
and tuned local-model performance.

---

## 1. Summary

Brain's whole **Python** path — hooks, summaries, fact extraction, reflection, *and* the
offline ingest/backfill tools — now runs on **local Ollama**. No cloud LLM calls remain in
Python (no `ANTHROPIC_API_KEY` / `OPENROUTER_API_KEY` set anywhere). The interactive Stop-hook
freeze was eliminated by switching the model to `qwen3-coder:30b` and tuning Ollama, not by
backgrounding work.

---

## 2. What was fixed

| Area | Problem | Fix |
|------|---------|-----|
| **Claude Code hooks** | Studio `~/.claude/settings.json` had no `hooks` block → no auto memory capture | Ported the 4-hook block from the MacBook (SessionStart, UserPromptSubmit, PostToolUse `Edit\|Write\|Bash\|Agent`, Stop), pointed at `.venv/bin/python3` + Studio paths |
| **Cursor MCP** | `brain/mcp/run_server.sh` used system `python3` (no `mcp` module) → silent failure | Point `exec` at `.venv/bin/python` |
| **`.mcp.json`** | Ran the release binary | Run `.venv/bin/python -m brain.mcp.server` with `BRAIN_BACKEND=api` |
| **Fact pipeline** | `fact_extractor.py` / `fact_curator.py` imported removed `OPENROUTER_*` → Stop hook crashed on import | Migrated both to Ollama `/api/chat`; `derived_from` now `ollama/<model>` |
| **Python embedder** | `EMBEDDING_MODEL = "nomic-embed-text"` (an Ollama tag, invalid HF id) → 401 crash | Set to `sentence-transformers/all-mpnet-base-v2` to match the Rust API's production ONNX vector space (768-dim) |
| **Offline ingest/tools** | `05/08_ingest_*`, `retitle_ppf_llm`, extractors used OpenRouter or a removed `_chat` helper | Added `_chat()` shim to `summarizer.py` (fixes 05/06/07); repointed `08` + `retitle` to `_chat` |
| **Reflection model** | `brain_api` used `qwen2.5:7b` while Python used `qwen3-coder:30b` | Unified `brain_api` `OLLAMA_MODEL` → `qwen3-coder:30b` |
| **Repo hygiene** | 68 `*.pyc` tracked; no ignore rules | Untracked them; added `__pycache__/`, `*.pyc`, `.DS_Store` to `.gitignore` |

---

## 3. Model benchmark (Apple M4 Max)

Measured on the 3 real hook passes (summarize / error-fix / decisions). Generation is
memory-bandwidth bound; **smaller non-reasoning models win**. Thinking models return **empty
content** unless `think:false` is sent.

| Model | gen speed | 3-pass total (warm) | JSON valid | Notes |
|-------|-----------|---------------------|-----------|-------|
| **qwen3-coder:30b** (MoE ~3B active) | 131 tok/s | **~4.0 s** | **3/3 ✅** | **chosen** — fast + reliable |
| deepseek-coder-v2 (15.7B MoE) | 179 tok/s | ~3.3 s | 3/3 ✅ | fastest; smallest (8.9 GB) |
| qwen2.5:7b | 106 tok/s | ~3.1 s | 2/3 | slight recall dip |
| qwen2.5:32b (previous) | 27 tok/s | ~17.5 s | 3/3 ✅ | 4.5× slower |
| qwen3.6:35b | 92 tok/s | ~24 s | 0/3 ❌ | thinking on → empty (1.4 s & valid with `think:false`) |
| gemma4:e4b / gemma4:31b | — | 21 s / 77 s | 1/3 ❌ | thinking models; 31b burns tokens on hidden reasoning |

Per-call breakdown for qwen2.5:32b: load 0.09 s · prompt-eval 0.37 s (199 tok/s) ·
**generation 4.33 s (23 tok/s)** — i.e. generation dominates.

---

## 4. Performance tuning (Ollama)

Set in `~/.local/bin/ollama-tune.sh` (re-applied each login by the `com.user.ollama-tune`
LaunchAgent; `launchctl setenv` does not survive reboot):

| Env | Value | Why |
|-----|-------|-----|
| `OLLAMA_KEEP_ALIVE` | `-1` | Keep model resident — no ~7 s reload between turns |
| `OLLAMA_MAX_LOADED_MODELS` | `2` | Interactive + Brain model can co-reside |
| `OLLAMA_FLASH_ATTENTION` | `1` | Faster attention / less memory (added this session) |

---

## 5. Active model configuration

| Path | Setting | Value |
|------|---------|-------|
| `brain/config.py` | `OLLAMA_SUMMARIZE_MODEL` | `qwen3-coder:30b` (summaries + facts) |
| `brain/config.py` | `EMBEDDING_MODEL` | `sentence-transformers/all-mpnet-base-v2` |
| `brain/config.py` | `OLLAMA_URL` | `http://127.0.0.1:11434` |
| `~/Library/LaunchAgents/com.brain.api.plist` | `OLLAMA_MODEL` | `qwen3-coder:30b` (reflection) |
| plist | `BRAIN_LLM_PROVIDER` | `ollama` |

Ollama serves an **Anthropic-compatible** API at `/v1/messages` and lists all models at
`/v1/models`.

---

## 6. Claude Code on local models

`ollama launch claude --model <name>` points Claude Code at Ollama
(`ANTHROPIC_BASE_URL=localhost:11434`, auth token `ollama`). One launcher per model added to
`~/.zshrc`:

```sh
claude-local() { ollama launch claude --model "${1:-qwen3-coder:30b}"; }
alias cc-coder='claude-local qwen3-coder:30b'      # recommended
alias cc-qwen35='claude-local qwen3.6:35b'
alias cc-qwen32='claude-local qwen2.5:32b'
alias cc-qwen7='claude-local qwen2.5:7b'           # fastest
alias cc-deepseek='claude-local deepseek-coder-v2:latest'
alias cc-gemma='claude-local gemma4:31b'
alias cc-gemma-e4b='claude-local gemma4:e4b'
```

Switch within a session with `/model <ollama-name>`.

---

## 7. Verification (all passed this session)

- `brain.ingest` imports clean; **Stop hook runs end-to-end, exit 0**.
- Real fact extraction + summary via Ollama produce valid JSON.
- Warm `summarize_session` ≈ **1.2 s** (was ~6–7 s on 32B).
- Flash attention confirmed in Ollama server log; model stays resident.
- `brain_api` health 200 on `qwen3-coder:30b`.
- Fact-pipeline tests: **115 passed**.
- All offline scripts import/compile; no OpenRouter HTTP left in Python.

---

## 8. Commits

| Hash | Summary |
|------|---------|
| `a774f6f` | feat(brain-ingest): move fact pipeline to local Ollama + qwen3-coder |
| `aed4f52` | chore(repo): stop tracking bytecode caches, ignore pyc/__pycache__/.DS_Store |
| `5f3e9c2` | chore(studio): point MCP at venv python + update migration docs |
| (earlier) | fix(brain-mcp): use venv python in run_server.sh so Cursor MCP loads |

Uncommitted (local-only repo, left intentionally): `summarizer.py` (`_chat` shim), offline
script migrations, and a large pre-existing working-tree WIP. Outside the repo:
`~/.claude/settings.json` (hooks), `~/.local/bin/ollama-tune.sh`, `~/.zshrc`,
`com.brain.api.plist`.

---

## 9. Remaining / dormant (not in the live path)

- **Rust** hook binaries (`brain_session_*`, `brain_post_tool_use`) and ingest bins are
  **Anthropic-only**; `summarizer.rs` keeps unused OpenRouter/Anthropic clients as fallbacks.
  They never fire — `brain_api` is `BRAIN_LLM_PROVIDER=ollama` and no cloud keys exist. Only
  matters if you switch to the Rust hooks or want to delete dead code.
- 5 pre-existing failing tests in peripheral areas (`test_backfill_bad_data`,
  untracked `test_feedback_digest`) — unrelated to this migration.

---

## 10. Activation notes

- **Hooks:** restart Claude Code / start a new session to load the new `hooks` block.
- **Cursor MCP:** reload Cursor to pick up `run_server.sh`.
- **zsh launchers:** open a new terminal or `source ~/.zshrc`.
