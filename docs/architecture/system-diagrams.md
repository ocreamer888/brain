# System Diagrams

This document captures the brain system architecture in several views:

1. System context (actors and major components)
2. Runtime flow (how requests move during normal operation)
3. Data and storage flow (ingest, migration, and persistence)
4. End-to-end chain (real time → scheduled → review)
5. **Import → transcribe/extract → ingest → production → digest** (below)
6. **Unified motor map** — all major processes on one diagram + inventory (below)

**Storage note (Rust primary):** `brain_api` keeps vectors **in memory** (cosine index) and rebuilds from SQLite (`memories.embedding` BLOB + metadata) on startup. Some deploy docs still mention `BRAIN_INDEX_PATH` / `.bin` for backup or older layouts; the diagrams below emphasize **SQLite + in-process index** unless labeled otherwise.

**v0.2.0 (2026-04-20) changes reflected below:** native Rust MCP (`brain_mcp`) replaces the Python stdio wrapper as default; new `UserPromptSubmit` hook (`brain_user_prompt_submit`); tree-sitter symbol tags on PostToolUse; 3-layer progressive-disclosure tools (`search_index` → `timeline` → `get_observations`); SSE broadcast on save (`/v1/stream`); embedded web viewer (`GET /`, `/static/*`); admin endpoints (`/list`, `/delete`); `<private>` block stripping on save; job retry queue (`jobs` table + `brain::worker`); event-time `timestamp` field on `/save`. Full summary: `docs/BRAIN_V0.2.0_CAPABILITIES.md`.

**Fact layer (Phase 2+, 2026-05):** `brain/ingest/fact_extractor.py` + `brain/ingest/fact_curator.py` add a structured fact pipeline on top of raw memories. `brain/tools/backfill_facts.py` runs it across all historical sources (Claude Code sessions, Perplexity threads, Obsidian DB entries, Cursor vscdb) with per-source checkpoint files. Live per-session extraction opt-in via `BRAIN_FACT_EXTRACT=1` in `session_end.py`. New SQLite tables: `curation_events`, `backfill_batches`.

**Roadmap (Rust as sole production brain):** `docs/plans/2026-04-08-rust-primary-production-ready.md`

---

## 1) System Context

```mermaid
flowchart LR
    IDE[Cursor/Claude IDE Session]
    Browser[Browser<br/>localhost:8787]
    MCPClient[MCP Client]
    HookRuntime[Hook Runtime<br/>SessionStart + UserPromptSubmit<br/>PostToolUse + Stop]
    MCPServer[brain_mcp<br/>native Rust rmcp stdio]
    MCPLegacy[brain/mcp/server.py<br/>Python fallback]
    PythonCore[Python brain core]
    APISvc[Rust API brain_api<br/>+ SSE + static viewer + worker]
    LLM[Anthropic/OpenRouter]
    Chroma[(ChromaDB<br/>legacy brain/db)]
    Sqlite[(SQLite<br/>memories + jobs + feedback_events)]
    VEC[(Vector index<br/>in-process rebuilt from SQLite)]
    Vault[(vault/<br/>canonical MD)]
    IngestV[08 + 09 ingest]
    Sync[Sync Adapters]

    IDE --> HookRuntime
    IDE --> MCPClient
    Browser --> APISvc
    MCPClient --> MCPServer
    MCPClient -.fallback.-> MCPLegacy
    HookRuntime --> APISvc
    HookRuntime --> PythonCore
    MCPServer --> APISvc
    MCPLegacy --> PythonCore
    PythonCore --> APISvc
    PythonCore --> Chroma
    APISvc --> Sqlite
    APISvc --> VEC
    APISvc --> LLM
    PythonCore --> LLM
    Vault --> IngestV
    IngestV --> APISvc
    Chroma --> Sync
```

---

## 2) Runtime Flow

```mermaid
flowchart TD
    Start[Session starts] --> S1[session_start.py]
    Prompt[User prompt submitted] --> S0[brain_user_prompt_submit<br/>Rust hook]
    ToolUse[Edit/Write/Bash/Agent event] --> S2[post_tool_use.py<br/>+ tree-sitter sym tags]
    End[Session ends] --> S3[session_end.py]
    MCPReq[MCP tool request] --> M1[brain_mcp native Rust<br/>search_index + timeline + get_observations]
    Viewer[Browser at 127.0.0.1:8787] --> SSE[GET /v1/stream<br/>+ POST /v1/search_index]

    S1 --> B{BRAIN_BACKEND}
    S0 --> API
    S2 --> B
    S3 --> B
    M1 --> API
    SSE --> API

    B -->|api default| APIClient[brain/api_client.py]
    B -->|python fallback| PyMemory[brain.core.memory]

    APIClient --> API[HTTP Rust brain_api]
    PyMemory --> Chroma[(ChromaDB)]

    API --> Priv[privacy.rs<br/>strip &lt;private&gt; blocks]
    Priv --> DB[(SQLite<br/>memories + jobs + feedback_events<br/>embedding BLOB)]
    API --> VEC[(In-process vector index)]
    API --> Reflect[Reflection/Summarization]
    API --> Broadcast[SSE broadcast<br/>MemoryEvent]
    Broadcast --> SSE
    API --> Worker[brain::worker<br/>5s loop + 5-attempt cutoff]
    Worker --> DB
```

---

## 3) Data and Storage Flow

```mermaid
flowchart TD
    Perplexity[Perplexity exports/scripts<br/>event-time timestamp] --> IngestP[06_ingest_perplexity.py]
    Claude[Claude/Claw/Cursor exports<br/>event-time timestamp] --> IngestC[05 / 07 / 03 ingest pipelines]
    VaultMD[repo vault Markdown] --> IngestO[08_ingest_books + 09_ingest_obsidian]

    IngestP --> API[brain_api /save + /save-batch<br/>optional timestamp RFC3339]
    IngestC --> API
    IngestO --> API

    API --> Priv[privacy.rs<br/>strip &lt;private&gt; blocks]
    Priv --> Sqlite[(SQLite: memories + embeddings + jobs<br/>+ curation_events + backfill_batches)]
    API --> Vidx[(In-process vector index)]
    API --> Jobs[jobs table<br/>pending/failed with attempts]
    Jobs --> Worker[brain::worker<br/>5s poll, 5-attempt cutoff]
    Worker --> Sqlite

    Chroma[(ChromaDB legacy)] --> Export[tools/export_to_jsonl.py]
    Export --> Jsonl[memories_export.jsonl]
    Jsonl --> Migrate[brain_migrate]
    Migrate --> Sqlite
    Migrate --> Vidx

    subgraph factlayer["Fact layer (Phase 2+)"]
        FE[fact_extractor.py<br/>LLM → FactDraft list]
        FC[fact_curator.py<br/>similarity gate + tiebreaker<br/>ADD / UPDATE / MERGE / IGNORE]
        BF[backfill_facts.py<br/>--all / --from-perplexity<br/>--from-db / --from-cursor-db<br/>checkpoint-resumable]
    end

    IngestC -.BRAIN_FACT_EXTRACT=1.-> BF
    BF --> FE
    FE --> FC
    FC --> Sqlite

    Sqlite --> Query[brain_api<br/>/search + /v1/search_index<br/>/v1/timeline + /v1/get_observations<br/>/list + /delete + /stats]
    Vidx --> Query
    API --> Stream[/v1/stream SSE<br/>MemoryEvent on save/]
```

---

## 4) End-to-end chain (real time → scheduled → review)

Single story: **capture while you work**, **surface deltas on a schedule**, **export when you need raw data** (e.g. Phase 8).

```mermaid
flowchart TD
    subgraph live["Real time (session)"]
        A1[SessionStart → session_start.py] --> API1[brain_api: get_context / search]
        A2[PostToolUse → post_tool_use.py] --> API2[brain_api: save]
        A3[User or agent judgment] --> API3[brain_api: POST /feedback or MCP record_feedback]
        A4[SessionEnd → session_end.py] --> EXP[Export session JSON → sessions_export/]
    end

    subgraph store["Persistence"]
        API1 --> SQL[(SQLite memories + feedback_events)]
        API2 --> SQL
        API3 --> SQL
        API1 --> VIX[(In-process vector index)]
        API2 --> VIX
    end

    subgraph batch["Scheduled or on-demand"]
        D1[feedback_digest.py] --> MD[docs/feedback-digests/*.md]
        E1[export_feedback.py] --> JSL[JSONL file]
        EV[retrieval_eval.py + brain/eval/gold.jsonl]
    end

    SQL --> D1
    SQL --> E1
    EV -.->|HTTP /search| API1
```

**Order of operations (conceptual):**

1. **Run** `brain_api` (if `BRAIN_BACKEND=api`) with env for DB/index/key.  
2. **Wire** Claude/Cursor hooks + MCP once.  
3. During work: **context → save → optional feedback** hit SQLite continuously.  
4. **Daily (or manual):** `feedback_digest.py` → markdown inbox.  
5. **When needed:** `export_feedback.py` (or `brain/tools/brain_chain.sh`) → JSONL for analysis / Phase 8.

---

## 5) Production path: import documents -> memory -> digest

How **external knowledge** becomes **searchable memory**, then **operational review** artifacts. "Transcribe" here means **turn raw files or exports into clean text + metadata** (extractors, optional LLM summarize); dedicated audio/PDF pipelines are usually upstream unless you add a converter step.

```mermaid
flowchart TD
    subgraph src["① Sources"]
        S1[Notes / MD / docs in repo or vault]
        S2[Chat exports: Perplexity JSON, Claude session JSON]
        S3[Cursor history → `02_summarize.py` input]
        S4[Claude.ai / Claw JSON exports]
        S5[Optional: PDF or audio → text<br/>external tool / future ingest]
    end

    subgraph xform["② Extract & normalize (transcribe)"]
        X1[bootstrap extractors<br/>`claude_code_extractors.py`, `perplexity_extractors.py`, …]
        X2[Optional LLM pass<br/>summarize / structure — or `--no-llm`]
        X3[Validated text + metadata<br/>ready for ingest]
    end

    subgraph ingest["③ Ingest"]
        I1[Python ingest scripts<br/>`03` / `05` / `06` / `07` / `08` / `09`]
        I2[`brain_api`<br/>`/save` + `/save-batch`]
        I3[(SQLite + embeddings + in-process vector index)]
        I4[(ChromaDB `brain/db`<br/>legacy archive/migration only)]
    end

    subgraph prod["④ Production runtime"]
        R1[`brain_api` + embedder<br/>ONNX or mock]
        R2[Hooks + MCP<br/>search / save / feedback]
        R3[(SQLite + in-process index<br/>`BRAIN_DB_PATH`)]
    end

    subgraph out["⑤ Digest & datasets"]
        O1[`feedback_digest.py` → markdown inbox]
        O2[`export_feedback.py` / `brain_chain.sh` → JSONL]
        O3[Spot checks: `/stats`, `brain_query`, search in IDE]
        O4[`retrieval_eval.py` → `brain/eval/last_report.json`]
    end

    S1 --> X1
    S2 --> X1
    S3 --> X2
    S4 --> X1
    S5 --> X1
    X1 --> X2
    X2 --> X3
    X3 --> I1
    I1 --> I2
    I2 --> I3
    I4 --> R3
    R1 --> R3
    R2 --> R1
    R3 --> O1
    R3 --> O2
    R2 --> O3
    R2 -.->|queries via API| O4
```

**Production-ready checklist (conceptual):**

| Step | Goal |
|------|------|
| ① | Single **source of truth** per corpus (export format known, paths stable). |
| ② | **Text is UTF-8 text** with minimal junk; metadata (project, type, source, optional `file_path` / `title` for vault rows) is set before or during ingest. |
| ③ | Ingest scripts write to **Rust API** (`/save` or `/save-batch`) as default production sink. Chroma remains for legacy export/migration only. |
| ④ | **`brain_api` running** with matching `BRAIN_DB_PATH` (and optional index path if your deploy uses on-disk index); hooks/MCP pointed at same backend. |
| ⑤ | **Feedback + digest** on a schedule or runbook so operators see new signal without ad-hoc SQL. |

**Shortcuts:** Greenfield Rust-only users can skip Chroma entirely. Legacy users can keep migration tooling only as archive/rehydration path.

---

## 6) Unified motor map (all major processes)

Single view of **every motor group** the brain uses: entry points, routing, storage, bulk pipelines, cognition, observability, sync, and utilities. Arrows are **primary data/control flow** (some optional paths are omitted for clarity—see inventory).

```mermaid
flowchart TB
  LLM[External LLMs<br/>OpenRouter / Anthropic]

  IDE[IDE / operator]

  SCH[Schedulers<br/>cron / launchd]

  EXP[Exports and docs<br/>JSON MD vault]

  BRW[Browser<br/>live viewer]

  subgraph hooks["Hook motors"]
    H0[brain_user_prompt_submit<br/>Rust: POST /v1/search]
    H1[session_start.py]
    H2[post_tool_use.py<br/>+ tree-sitter sym tags]
    H3[session_end.py]
  end

  subgraph mcpM["MCP motor (v0.2.0 default: native Rust)"]
    MCP[brain_mcp<br/>rmcp crate stdio<br/>search_index + timeline + get_observations]
    MCPLEG[brain/mcp/server.py<br/>Python fallback]
  end

  BE{BRAIN_BACKEND<br/>api vs python}

  subgraph clientM["HTTP client motor"]
    AC[api_client.py]
  end

  subgraph pyMemM["Python memory motor"]
    MEM[core/memory.py +<br/>Chroma sentence-transformers]
  end

  subgraph apiM["Rust API motor"]
    API[brain_api<br/>/health /stats /save /save-batch /search /reflect /feedback<br/>/v1/search_index /v1/timeline /v1/get_observations<br/>/v1/search /v1/stream SSE /list /delete<br/>GET / + /static/* embedded viewer]
    PRIV[privacy.rs<br/>&lt;private&gt; stripping]
    SYM[symbols.rs<br/>tree-sitter rust/ts/py]
    WRK[brain::worker<br/>jobs queue 5s loop]
    SV[static viewer<br/>index.html + app.js<br/>via rust-embed]
  end

  subgraph embedM["Embedding motor"]
    EMB[ONNX all-mpnet or mock<br/>BRAIN_EMBEDDER]
  end

  subgraph storeR["Rust stores"]
    SQL[(SQLite:<br/>memories + feedback_events + jobs<br/>+ curation_events + backfill_batches<br/>+ embedding BLOB + event-time timestamp)]
    VIX[(Vector index<br/>in-process)]
  end

  subgraph storeC["Chroma store"]
    CH[(ChromaDB brain/db)]
  end

  subgraph bulkM["Bulk ingest motors"]
    BI[bootstrap 02–09 + extractors]
    EX[export_to_jsonl.py]
    MG[brain_migrate]
    RI[brain_ingest_sessions<br/>brain_ingest_perplexity]
  end

  subgraph vaultM["Vault corpus"]
    RV[vault/*.md<br/>canonical notes + books]
  end

  subgraph evalM["Retrieval quality tooling"]
    REV[retrieval_eval.py<br/>gold.jsonl]
    RR[retrieval_rerank.py<br/>optional 2nd stage]
  end

  subgraph factM["Fact layer motors (Phase 2+)"]
    FEX[fact_extractor.py<br/>LLM → FactDraft list]
    FCU[fact_curator.py<br/>similarity gate 0.78 / 0.92<br/>ADD / UPDATE / MERGE / IGNORE]
    BFT[backfill_facts.py<br/>--all / --from-perplexity<br/>--from-db / --from-cursor-db<br/>checkpoint files per source]
  end

  subgraph cognM["Cognition motors"]
    SU[summarize:<br/>ingest + post_tool path]
    RF[reflect:<br/>session_end MCP API<br/>auto every N saves]
  end

  subgraph obsM["Observability motors"]
    FD[feedback_digest.py]
    FE[export_feedback.py]
    CHN[brain_chain.sh]
    LG[BRAIN_LOG_SEARCH]
  end

  subgraph syncM["Sync motors"]
    OB[sync/obsidian.py]
    CL[sync/claude_memory.py]
    S4[bootstrap/04_sync.py]
  end

  subgraph utilM["Utility motors"]
    BQ[brain_query]
  end

  subgraph optR["Optional Rust hook CLIs<br/>mirror Python hooks"]
    RH[brain_session_start<br/>brain_session_end<br/>brain_post_tool_use]
  end

  IDE --> hooks
  IDE --> MCP
  IDE -.fallback.-> MCPLEG
  BRW --> SV
  BRW --> API
  H0 --> API
  hooks --> BE
  MCP --> API
  MCPLEG --> BE
  BE -->|api| AC
  BE -->|python| MEM
  AC --> API
  API --> PRIV
  PRIV --> SQL
  API --> SYM
  SYM --> SQL
  API --> WRK
  WRK --> SQL
  API --> SV
  API --> EMB
  API --> SQL
  API --> VIX
  API --> LG
  MEM --> CH
  EXP --> BI
  RV --> BI
  BI --> API
  CH --> EX
  EX --> MG
  MG --> SQL
  MG --> VIX
  RI --> SQL
  RI --> VIX
  H2 --> SU
  H2 --> SYM
  MEM --> SU
  LLM --> SU
  H3 --> RF
  MCP --> RF
  API --> RF
  LLM --> RF
  SCH --> FD
  SCH --> FE
  SCH --> CHN
  SQL --> FD
  SQL --> FE
  BQ --> SQL
  BQ --> VIX
  CH --> OB
  CH --> CL
  MEM --> S4
  IDE -.optional.-> RH
  RH -.-> API
  IDE -.eval / tuning.-> REV
  REV --> AC
  H3 -.BRAIN_FACT_EXTRACT=1.-> BFT
  EXP --> BFT
  BFT --> FEX
  FEX --> FCU
  FCU --> SQL
  FCU --> VIX
```

### Motor / process inventory (by artifact)

| Group | Processes |
|-------|-----------|
| **Hooks** | `brain_user_prompt_submit` (Rust, v0.2.0+), `session_start.py`, `post_tool_use.py`, `session_end.py` |
| **MCP (primary)** | `brain_mcp` — native Rust (`rmcp` crate) stdio server; 3-layer tools: `search_index`, `timeline_tool`, `get_observations_tool` (plus legacy `search_brain` / `save_memory_tool` / `get_context_tool` / `reflect_tool` / `get_stats_tool` / `record_feedback`) |
| **MCP (fallback)** | `brain/mcp/server.py` — retained Python stdio wrapper (`BRAIN_BACKEND=python`, manual QA) |
| **Client** | `brain/api_client.py` (incl. `list_memories`, `delete_memories`, optional `timestamp` kwarg on `save_memory`) |
| **Rust API** | `brain_api` — routes: `/health`, `/stats`, `/save`, `/save-batch`, `/search`, `/reflect`, `/feedback`, `/v1/search`, `/v1/search_index`, `/v1/timeline`, `/v1/get_observations`, `/v1/stream` (SSE), `/list`, `/delete`, `GET /` + `/static/*` (embedded viewer) |
| **Rust ingest** | `brain_migrate`, `brain_ingest_sessions`, `brain_ingest_perplexity` |
| **Rust hook CLIs** | `brain_user_prompt_submit` (default on), `brain_session_start`, `brain_session_end`, `brain_post_tool_use` (+ tree-sitter sym tags) |
| **Rust utility** | `brain_query` |
| **Rust internals (new in v0.2.0)** | `privacy.rs` (`<private>` stripping), `symbols.rs` (tree-sitter rust/ts/py), `worker.rs` (jobs queue, 5s loop, 5-attempt cutoff) |
| **Python core** | `brain/core/memory.py`, `brain/core/db.py`, `brain/core/embedder.py`, `brain/core/summarizer.py` |
| **Bootstrap / extract** | `02_summarize.py`, `03_ingest.py`, `05_ingest_claw.py`, `06_ingest_perplexity.py`, `07_ingest_claude_code.py`, `08_ingest_books.py`, `09_ingest_obsidian.py`, `*_extractors.py`, `parse_sql.py` |
| **Fact layer** | `brain/ingest/fact_extractor.py` (LLM → `FactDraft` list), `brain/ingest/fact_curator.py` (similarity gate: >0.92 IGNORE, 0.78–0.92 tiebreaker, <0.78 ADD; writes `curation_events` + `backfill_batches`), `brain/tools/backfill_facts.py` (4 modes: `--all`, `--from-perplexity`, `--from-db`, `--from-cursor-db`; checkpoint-resumable per source; opt-in live via `BRAIN_FACT_EXTRACT=1`) |
| **Tools** | `export_to_jsonl.py`, `export_feedback.py`, `feedback_digest.py`, `brain_chain.sh`, `retrieval_eval.py`, `retrieval_rerank.py` (optional second-stage rerank; not wired into MCP by default) |
| **Sync** | `sync/obsidian.py`, `sync/claude_memory.py`, `04_sync.py` |
| **Embedding runtime** | ONNX under `brain/rust/models/…` or mock; tokenization inside Rust crate |
| **Stores** | SQLite (metadata + embedding BLOB + `jobs` + `feedback_events` + `curation_events` + `backfill_batches`, event-time `timestamp` field) + in-process vector index on `brain_api` (primary); ChromaDB (legacy/archive) |
| **Observability** | Embedded web viewer (`brain/rust/static/index.html` + `app.js`) served at `http://127.0.0.1:8787/`; SSE stream on `/v1/stream`; `feedback_digest.py` markdown inbox; `BRAIN_LOG_SEARCH` |
| **Vault + eval** | `vault/` corpus; `09`/`08` ingest; `brain/tools/retrieval_eval.py`, `retrieval_rerank.py`, `brain/eval/gold.jsonl` |

**Not drawn as separate boxes:** rate limiting and auth inside `brain_api`; idempotency on feedback; `continual-learning` / `AGENTS.md` (meta, not runtime). **Retrieval eval** (`brain/eval/gold.jsonl` + `brain/tools/retrieval_eval.py`) and **heuristic rerank** (`brain/tools/retrieval_rerank.py`) exist as tooling; default MCP search still uses API vector order unless you add a second-stage call. **Web viewer auth caveat:** `/static/*` is public but `/v1/stream` and `/v1/search_index` require auth — the browser can't send an API key, so set `BRAIN_API_AUTH_REQUIRED=0` for local viewer use only.

---

## Notes

- Runtime path supports `api` (default production) and `python` (legacy fallback) via `BRAIN_BACKEND`.
- Production guardrail can force API path: `BRAIN_ENFORCE_API_ONLY=1`.
- Data migration from ChromaDB to Rust storage is implemented and idempotent.
- **`retrieval_rerank.py`** is a library helper; wire it after `api_client.search` if you want heuristic reordering in a custom tool or MCP fork—default MCP uses raw API order.
- This document is architecture-level and intentionally omits low-level module internals.


<!-- brain-linker -->
## Related
- [[brain-graph/conversation/User]]
- [[brain-graph/conversation/User i want to verify what kind of strong features would thi]]
- [[brain-graph/solution/Edited Usersmacm1airDocumentsAIbrainrustsrcbrain.rs pub stru]]
- [[brain-graph/pattern/Edited Usersmacm1airDocumentsAIbrainrustsrcbrain.rs ( memori]]
- [[brain-graph/solution/Edited Usersmacm1airDocumentsAIbrainrustsrcbrain.rs Ok(Self ]]
<!-- /brain-linker -->
