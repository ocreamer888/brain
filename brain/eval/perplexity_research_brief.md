# Project Context — BRAIN

## What This Is and Why It Exists

BRAIN is a personal long-term memory system built to give Claude Code (Anthropic's CLI coding assistant) persistent memory across sessions. Without it, every Claude session starts blank — no knowledge of what was built yesterday, what bugs were solved last week, or what architectural decisions were made last month.

The problem: a developer working on 10+ projects simultaneously loses compounding context every time a session ends. Solutions decided once get re-decided. Bugs fixed before get solved again. The same onboarding happens every session.

BRAIN solves this by automatically capturing every Claude Code session as structured memories and injecting the most relevant ones at the start of every new session. When you open Claude Code in a project folder, the first thing injected into context is: "here are the 5 most relevant things you already know about this project."

---

## Origin and Development History

The system was built incrementally over ~6 months using Claude Code itself as the primary engineering tool. The founder/user is non-technical (product/design background). Every component was designed and implemented by Claude Code in a collaborative loop — making this a project that is literally a product of the same tool it's designed to augment.

**Bootstrap:** Started by ingesting months of existing Cursor IDE history, Claude.ai chat exports, and Perplexity research threads. Custom ingestion pipelines were written for each source.

**v0.1 (Python):** ChromaDB + sentence-transformers + Python MCP server. Functional but slow. Hook system wired into Claude Code's `SessionStart`, `PostToolUse`, and `Stop` events.

**v0.2.0 (2026-04-20, Rust rewrite):** Full rewrite to Rust for production quality:
- `brain_api` — Axum HTTP server with SQLite + in-process cosine index
- `brain_mcp` — native Rust MCP server (replaces Python stdio wrapper)
- ONNX embedder (all-mpnet-base-v2, 768-dim) — no Python at query time
- `brain_user_prompt_submit` — Rust hook that fires on EVERY user prompt, injecting top-5 memories mid-session
- tree-sitter symbol extraction on every file edit — function/class names as searchable tags
- SSE broadcast on every save — live web viewer at `localhost:8787`
- Job retry queue — durable ingest with 5-attempt cutoff
- `<private>` block stripping — redact sensitive content before embedding
- 3-layer progressive-disclosure MCP: `search_index` → `timeline_tool` → `get_observations_tool`

**Current state:** Supervised by macOS `launchd` (auto-start at login, auto-restart on crash). 2,517 memories. ~20 new memories added per day. The system has been running in production for 3+ months.

---

## Full Technical Stack

**Runtime (Rust binary):**
- `brain_api` binary: Axum HTTP server on `127.0.0.1:8787`
- SQLite (`brain.db`): single source of truth — memories, sessions, jobs, feedback_events tables
- FTS5 virtual table: full-text search with BM25 scoring, porter ASCII stemmer
- In-process cosine index: embeddings loaded from SQLite BLOBs at startup, L2-normalized float32 matrix in RAM (~7MB for 2.5K × 768 dims)
- ONNX Runtime: all-mpnet-base-v2 (768-dim), ~200ms per batch, CPU-only (M1 MacBook Air)

**Retrieval algorithm (production):**
```
score = 0.7 × cos_normalized + 0.3 × bm25_normalized
final_score = score × (0.85 + 0.15 × 0.5^(age_days / 730))
```
T1 mean-centering applied to the full embedding matrix at index load.

**Hook pipeline (Python scripts calling the Rust API):**
- `SessionStart`: embed project name → top-5 memories injected as `[BRAIN]` block
- `UserPromptSubmit` (Rust binary): embed user prompt → top-5 hits injected mid-session
- `PostToolUse`: summarize tool output → save as typed memory via `/save`
- `Stop`: export full session JSONL → background ingest

**Ingestion sources:**
- Claude Code sessions (live, automatic via Stop hook)
- Cursor IDE history (batch bootstrap, ~600 sessions)
- Claude.ai chat exports (batch via Selenium scraper)
- Perplexity research threads (batch via JSON exporter)
- Obsidian vault notes (chunked by headers, `OBSIDIAN_CHUNK_WORDS=1500`)
- Books (Obsidian vault `03 Resources/Books/*.md`)

**Memory schema:**
```sql
id TEXT, content TEXT, type TEXT, project TEXT, tags TEXT,
timestamp INTEGER, source TEXT, session_id TEXT, importance REAL,
file_path TEXT, thread_id TEXT, title TEXT, embedding BLOB
```

**Memory types:** `solution`, `project_context`, `conversation`, `pattern`, `error_lesson`, `decision`

**LLM components (optional, for summarization):**
- OpenRouter: `google/gemma-3-27b-it:free` for summarization, `meta-llama/llama-3.3-70b-instruct` for reflection
- Anthropic API: fallback for reflection
- Used ONLY at ingest/reflect time, never at query time

**Constraints that cannot change:**
- Local-only: no cloud API calls at query time
- SQLite only: no Qdrant, Chroma, Pinecone, or other vector store
- CPU-only: M1 MacBook Air, no GPU
- Latency budget: <500ms end-to-end for search
- ONNX embedder must stay (model already deployed, hooks depend on it)
- Rust binary is the production runtime — Python is ingest-side only

---

## Projects Stored in Memory

The system tracks memories across 20+ active projects, including:

| Project | Domain | P@1 (retrieval) |
|---|---|---|
| `general` | cross-project solutions | 0.540 |
| `AI` | this brain system itself | 0.706 |
| `perplexity` | research threads | 0.971 |
| `claw-code` | Claude.ai session exports | 1.000 |
| `owelign` | HR / payroll SaaS | 0.551 |
| `sicop` | Costa Rica government procurement | 0.430 |
| `meddefi` / `MedDeFi` | Starknet medical DeFi platform | 0.45–0.93 |
| `ocreamer` | creative agency / brand | 0.228 |
| `lifehub` | personal OS app | 0.727 |

---

## What We Are Trying to Achieve

**Goal:** Make the retrieval layer as precise and sharp as possible — when Claude searches the brain for "how did we solve X", it should get the single most relevant memory at rank 1, consistently, across all project types and query styles.

**Current baseline (measured):**
- Overall P@1: 0.640 (full corpus k-fold)
- Best type: `decision` 1.0, `error_lesson` 0.95, `pattern` 0.92
- Worst type: `project_context` 0.56, `solution` 0.63
- Worst project: `ocreamer` 0.23, `sicop` 0.43

**The failure modes we've confirmed:**
1. **Multi-topic session summaries**: one session produces one embedding that blends 3-5 unrelated topics → query for any single topic gets a near-zero similarity to the blended vector (confirmed: cosine sim = -0.009 for an npm error query against a mixed npm+CSS+Safari session memory)
2. **Style gap**: 10-20 word queries vs 100-2000 word session summaries → embedding model maps them into different regions
3. **Sibling confusion**: multiple memories from the same project with nearly identical structure (procurement templates, repeated layout fixes) → neither BM25 nor cosine can discriminate
4. **Alpha unmeasurable**: BM25 trivially wins all natural-language evals because natural-language queries share vocabulary with natural-language documents — cannot empirically validate the 0.7 alpha weight

**What we know works:**
- `pattern` type (short, single-topic, avg 148 chars) → P@1=0.92
- Unique descriptive titles → P@1=0.97 (perplexity project)
- BM25 on specific technical vocabulary → highly discriminative
- Cosine for genuinely unique semantic concepts (creative works, unique technical combinations)

**Working hypothesis:** The dominant fix is indexing granularity — extract individual atomic facts from multi-topic session memories at ingest time, giving each fact its own embedding while linking back to the parent session for context retrieval. The `pattern` type is essentially doing this already and outperforms every other type.

# BRAIN Memory Retrieval — Research Brief for Perplexity

## What BRAIN Is

A personal AI long-term memory system. Every Claude conversation is automatically summarized and saved as a "memory" into SQLite (brain.db). At query time, the system retrieves the most relevant past memories to inject into Claude's context. The system runs locally on macOS, written in Rust, with Python ingestion tooling.

**Stack:**
- SQLite with FTS5 virtual table (BM25, porter ASCII stemmer)
- all-mpnet-base-v2 ONNX embeddings (768-dim, L2-normalized, LE float32 stored as BLOBs)
- Hybrid retrieval: `score = 0.7 * cos_norm + 0.3 * bm25_norm`
- Recency decay: `0.85 + 0.15 * 0.5^(age_days/730)`
- Mean-centering (T1) applied to the full embedding matrix at index load
- 2,517 memories total

---

## Memory Structure

Each memory row: `id, content, type, project, tags, timestamp, title, embedding BLOB`

**Type distribution:**
- `solution`: 1,244 (avg 994 chars) — session summaries of what was built/fixed
- `project_context`: 683 (avg 2,379 chars) — project state / design docs
- `conversation`: 263 (avg 726 chars) — raw conversation exports
- `pattern`: 251 (avg 148 chars) — short reusable code/design patterns
- `error_lesson`: 61 (avg 819 chars) — bug post-mortems
- `decision`: 15 (avg 546 chars) — architectural choices

**Critical fact: 78.5% of memories have no title.** Query fallback is first sentence of content (≤200 chars).

**Typical solution memory content:**
```
Refactored a Next.js frontend layout to implement a fixed transparent header, a full-height two-panel 
main container, and proper footer positioning. Adjusted responsive padding, viewport heights, and flex 
positioning to resolve overlapping content, scrolling, and visual containment issues. | Header overlaps 
page content: Applied fixed positioning and bg-transparent to header while adding pt-20 offset padding 
to the main content area | Container extends behind footer: Removed min-h-screen from page component...
```
→ Pipe-delimited, multiple fixes per memory. One session = one memory = one embedding = blended vector.

---

## Measured Retrieval Performance

### Leave-one-out k-fold eval (query = memory title/first sentence)

| Scope | P@1 | P@5 | MRR |
|---|---|---|---|
| Full corpus (n=2,381) | 0.640 | 0.746 | 0.694 |
| 10% held-out (n=249) | 0.795 | 0.914 | 0.849 |

**By type (full corpus):**
| Type | P@1 | n |
|---|---|---|
| `decision` | 1.000 | 10 |
| `error_lesson` | 0.951 | 61 |
| `pattern` | 0.921 | 165 |
| `solution` | 0.629 | 1218 |
| `project_context` | 0.562 | 786 |
| `conversation` | 0.688 | 141 |

**By project:**
| Project | P@1 | Characteristic |
|---|---|---|
| `claw-code` | 1.000 | Clear distinct titles |
| `perplexity` | 0.971 | Unique Q&A-style titles |
| `general` | 0.540 | Untitled multi-topic solutions |
| `ocreamer` | 0.228 | Near-duplicate procurement docs |
| `sicop` | 0.430 | Template documents |

### Semantic paraphrase eval (query = vocabulary-divergent rephrase, n=18)

Queries deliberately avoid all technical vocabulary from target documents. Example:
- Query: `"why do my fonts and color scheme disappear inside a grouped route folder?"` (no App Router / CSS / layout vocabulary)
- Gold: memory about Next.js App Router CSS scoping

| Alpha | P@1 | MRR | Notes |
|---|---|---|---|
| 0.0 (pure BM25) | **1.000** | 1.000 | Best — even "vocabulary-free" queries share natural language overlap |
| 0.3 | 0.278 | 0.415 | Sharp cliff |
| 0.7 (production) | 0.278 | 0.415 | Same as 0.3 |
| 1.0 (pure cosine) | 0.278 | 0.415 | Flat across all alpha > 0 |

Adding T1 mean-centering to the eval: **zero change.** Same results.

---

## Root Cause Analysis (Confirmed)

### Problem 1: Single embedding per multi-topic session → blended vector

Worst case: query `"the package manager says a command is unavailable even though I can see the configuration file"` → gold memory cosine similarity = **-0.0087** (rank 1,959/2,517).

The gold memory content mixes: npm dev script error + Safari CSS fixes + layout adjustments. Its embedding is the centroid of 3 unrelated topics. The query embeds into a completely different region of the space.

What beats it at cosine rank 1: an `ls -la /var/tmp/automl_repo/` command output (sim=0.38). The top 1,958 memories beat the gold with sims between 0.38 and ~0.00 while gold sits at -0.009.

### Problem 2: Style gap — short descriptive queries vs long prose documents

- Query: 10-20 words, natural language description of the problem
- Memory: 100-2,000 words, pipe-delimited session summary with multiple fixes

The embedding model (all-mpnet-base-v2) maps these into different regions. BM25 is immune to this because it operates on term frequency, not document-level semantics.

### Problem 3: Why BM25 "wins" even on vocabulary-divergent queries

All-natural-language queries about a topic naturally share vocabulary with natural-language documents about the same topic. You cannot write "the package manager says a command is unavailable" without those words appearing in the npm-error memory. True vocabulary isolation is impossible when both sides are natural language descriptions of the same event.

Consequence: **alpha cannot be empirically validated with any natural-language query design** on this corpus. Every test set becomes a BM25 tiebreaker.

### Problem 4: Intra-project sibling confusion (distinct from cross-project leakage)

`ocreamer` project (P@1=0.228): 100+ procurement bid documents with near-identical template structure. Only the line items and dates differ. Their embeddings are very close → cosine can't discriminate the correct one. BM25 also fails because all share the same template vocabulary.

Adding project scoping (mask out different-project memories) gives `ocreamer` a +0.195 lift but `owelign` (intra-project sibling confusion) shows zero improvement → two distinct failure modes.

### Problem 5: The eval itself has a self-consistency artifact

The k-fold eval uses memory title/first-sentence as the query. This works for: `decision` (clear titles), `error_lesson` (specific error text), `pattern` (short unique descriptions). It fails as a signal for `solution` and `project_context` because those don't have titles — the query is the first 200 chars of content, which BM25 trivially matches to the same document.

High kfold P@1 for `pattern` (0.92) and `error_lesson` (0.95) reflects good retrieval AND eval design alignment, not just retrieval quality.

---

## What We Need to Research

### 1. Chunking strategy for multi-topic memories

Current: 1 session → 1 memory → 1 embedding (avg 994 chars for `solution`).

**Questions:**
- What is the optimal chunk size for dense retrieval over conversational memories? (128 tokens? 256? Sentence-level?)
- How do production RAG systems handle documents that contain multiple independent facts?
- What does the research say about the trade-off between chunk granularity and context completeness?
- "Parent document retrieval" / small-to-big chunking — does it apply to memory systems?
- How does LlamaIndex / LangChain handle chunking of session transcripts?

### 2. Query-document asymmetry (short query → long document)

Current: query is 10-20 words; document is 100-2000 words.

**Questions:**
- What is the standard technique for asymmetric dense retrieval (short query vs long passage)?
- Is all-mpnet-base-v2 appropriate for this asymmetry, or is a query-focused model better (e.g., msmarco, e5-base-v2, bge-large)?
- What does the BEIR benchmark say about model selection for this use case?
- HyDE (Hypothetical Document Embeddings) — how effective is it for short-query → long-document retrieval? Practical cost?
- Does asymmetric bi-encoder training (separate query/document encoders) actually help at this corpus scale (2.5K docs)?

### 3. How successful memory systems achieve high retrieval precision

Specifically looking at: Mem0, MemGPT / Letta, Zep, cognee, OpenMemory.

**Questions:**
- How does Mem0 handle the multi-topic problem? Does it extract individual facts before storing?
- What is MemGPT's approach to memory granularity? Do they chunk by fact/entity?
- What embedding model does Zep use for their Temporal Knowledge Graph, and what P@k do they report?
- Does cognee use per-fact knowledge graph nodes instead of per-session chunks?
- What chunking / extraction pipeline does OpenMemory (Mem0 cloud) use?
- How do these systems handle the "same-project sibling" problem (multiple memories about the same codebase)?

### 4. Late interaction models vs bi-encoder for small-corpus retrieval

Current: bi-encoder (all-mpnet-base-v2, dot product). 

**Questions:**
- Is ColBERT worth deploying for a corpus of 2,500 memories? What is the memory and latency overhead?
- Does PLAID (ColBERT v2's compression) make small-corpus ColBERT practical on CPU?
- What is the typical P@1 lift from ColBERT over bi-encoder + BM25 fusion?
- What about cross-encoder reranking as a second stage? At what corpus size does the latency cost justify the precision gain?
- Is there a lightweight cross-encoder that works well on CPU for a 2.5K-doc corpus?

### 5. Memory-specific architecture patterns

**Questions:**
- What is the state of the art for "episodic memory" retrieval in AI agents?
- How do systems handle temporal relevance — is time decay a common component or an antipattern?
- What is the standard approach to deduplication / near-duplicate detection in memory systems?
- Entity-based vs passage-based memory storage — what does research show about retrieval accuracy?
- How does the "reflection" / consolidation step in MemGPT / Generative Agents affect retrieval quality?
- What role does LLM-generated summaries play in improving embedding quality for conversational memory?

### 6. Evaluation methodology for memory systems

**Questions:**
- How do production memory systems evaluate retrieval quality? Is there a standard benchmark?
- How do you evaluate retrieval when the "query" is natural language and the corpus is also natural language (unavoidable vocabulary overlap)?
- What is the LoTTe benchmark and does it apply to personal memory retrieval?
- How does RAGAS handle evaluation of memory retrieval quality?
- What is click-through / implicit feedback used for in production RAG evaluation?

---

## Success Signals We Observed in Our Own Data

| Signal | Observation |
|---|---|
| Short, unique content → high P@1 | `pattern` (148 avg chars, P@1=0.92), `decision` (P@1=1.0) |
| Clear unique title → high P@1 | `perplexity` project has Q&A titles, P@1=0.97 |
| Long multi-topic → low P@1 | `project_context` (2379 avg chars, P@1=0.56) |
| Near-duplicate templates → catastrophic | `ocreamer` P@1=0.23 |
| Single-topic embedding → cosine works | War of Art, globe viz, voice API — cosine rank 1 |
| Multi-topic embedding → cosine fails | npm+CSS+Safari session → cosine sim=-0.009 |

**Strong hypothesis:** If we extract individual facts from multi-topic memories and create one embedding per fact (pointing back to the parent memory for context), retrieval precision on `solution` and `project_context` would increase dramatically. The `pattern` type already does this by design.

---

## Constraints

- **Local-only**: No cloud API for embeddings at query time (ONNX model, ~200ms per batch)
- **Rust runtime**: Embedding store and retrieval must stay in current Rust binary
- **Python ingestion side**: Chunking/extraction at ingest time is acceptable
- **SQLite only**: No dedicated vector store (Qdrant, Chroma, etc.)
- **Corpus size**: ~2,500 memories, growing ~20/day — not a big-data problem
- **CPU only**: No GPU, M1 MacBook Air
- **Latency budget**: Retrieval must complete in <500ms

