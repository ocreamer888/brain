# Design: claw-code-main → Brain Integration

**Date:** 2026-04-02  
**Status:** Approved  
**Approach:** Hybrid (Option C)

## Goal

Ingest the `claw-code-main` codebase into the brain ChromaDB vector store so that future sessions can retrieve architectural context, design decisions, and implementation details from the Claude Code reimplementation via semantic search.

## What Gets Ingested

### Tier 1 — Markdown docs via OpenRouter (6 files)

Files:
- `CLAW.md`, `README.md`, `PARITY.md`
- `rust/README.md`, `rust/CONTRIBUTING.md`, `rust/docs/releases/0.1.0.md`

Each file is sent to OpenRouter (Qwen free tier) for a rich structured summary covering architecture, design decisions, and parity status. Output type: `project_context` or `decision`.

### Tier 2 — Python source via AST heuristics (67 files)

Files: all `src/**/*.py`

Extract per file:
- Module path (relative to claw-code-main)
- Module-level docstring
- Class names + their docstrings
- Top-level function signatures (name + args)

Produces one memory record per file. No API calls. Type: `solution`.

### Tier 3 — Rust source via regex heuristics (48 files)

Files: all `rust/**/*.rs`

Extract per file:
- Crate name (from directory path)
- `///` doc comments (first block)
- `pub fn`, `pub struct`, `pub enum` names

Produces one memory record per file. No API calls. Type: `solution`.

### Tier 4 — Reference JSON subsystems (25 files)

Files: `src/reference_data/subsystems/*.json`

Each subsystem JSON is ingested directly as structured context. Type: `project_context`.

## Architecture

Single new script: `brain/bootstrap/05_ingest_claw.py`

```
claw-code-main/
├── *.md, rust/**/*.md     → OpenRouter summarize  ─┐
├── src/**/*.py            → AST heuristics          ├→ upsert_memory() → ChromaDB
├── rust/**/*.rs           → regex heuristics        │   (source="claw_code")
└── src/reference_data/    → direct JSON parse      ─┘
```

No intermediate JSONL file needed — records are upserted directly into ChromaDB using the existing `brain.core.db.upsert_memory()` and `brain.core.embedder.embed_batch()` functions.

## Memory Metadata Schema

```json
{
  "type": "project_context | solution | decision",
  "project": "claw-code",
  "tags": "rust, session, mcp, ...",
  "source": "claw_code",
  "file_path": "rust/crates/runtime/src/session.rs",
  "importance": 0.8
}
```

## What Is NOT Changed

- No changes to hooks (PostToolUse, SessionStart, Stop)
- No changes to MCP server tools
- No changes to config.py
- This is a one-shot bootstrap, same pattern as `01_parse_sql.py` → `03_ingest.py`

## Success Criteria

- `brain_search("how does claw handle sessions")` returns records from `runtime/src/session.rs`
- `brain_search("claw parity with claude code")` returns PARITY.md summary
- `brain_search("claw plugin system")` returns plugin crate records
- All 146 source files + 6 markdown docs represented in ChromaDB with `source=claw_code`


<!-- brain-linker -->
## Related
- [[brain-graph/conversation/User okay. first, let's clarify the claw code files are for ]]
- [[brain-graph/conversation/User]]
- [[brain-graph/project_context/This README introduces an open-source, clean-room reimplemen]]
- [[brain-graph/project_context/This document provides contribution guidelines and developme]]
- [[brain-graph/project_context/This document serves as the README for Claw Code, a local co]]
<!-- /brain-linker -->
