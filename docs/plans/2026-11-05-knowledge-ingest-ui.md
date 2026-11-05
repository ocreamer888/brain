# Implementation Plan: Knowledge Ingest UI (attach a file or link)

**Date:** 2026-11-05
**Status:** Proposed — **deferred until the open cognitive-architecture gates (G3, G7, G8, and the `superseded_by` quarantine cleanup scoped under G2) are built.** Captured now so the design discussion isn't lost.
**Goal:** A page in the Brain Viewer (served at `/static/`, dev at `localhost:5173`) where a user attaches a file or pastes a link, and Brain ingests it as `memory_type=knowledge` — verbatim, chunked, with correct `source`/`file_path`/provenance — without needing an agent to remember the right CLI invocation or risk the wrong pipeline.

---

## Why this is worth building (background, verified against source — not assumed)

**The current pipeline (`brain/tools/ingest_knowledge.py`) is purely mechanical — it never paraphrases or summarizes.** Checked directly: zero paraphrasing/summarization logic exists anywhere in it or in `brain/ingest/text_chunking.py`. It reads a file, splits it by section headers (`chunk_by_sections`), re-chunks to a ~1500-word threshold (`refine_chunks_for_word_limit`), hashes each chunk for idempotency, and saves verbatim via the golden-path `api_client.save_memory()` with `memory_type=knowledge`, the given `source`, `file_path`, a generated title, and an `extracted_by` provenance string (`corpus:<doc_id>:c<ordinal>:sha:<hash>`) that makes re-running safe (unchanged chunks skip; changed chunks save fresh and mark the old one `superseded_by`).

**What actually required a human, every time, with no tooling at all:** writing the *source markdown file* in the first place. The one example in production (`telling-stories-with-data`, 290 live rows) used hand-paraphrased notes because of a since-reversed copyright-caution policy (see `AGENTS.md`, decision reversed 2026-11-05 — verbatim ingestion is now the norm for this private, non-distributed system). With that policy gone, there's no reason ingestion needs a paraphrase-writing step at all — raw file/link content can go straight into the same unchanged chunker.

**Agents can already write `knowledge` directly, no gap exists.** Checked `brain/mcp/server.py`'s `save_memory_tool`: no code-level block on `memory_type=knowledge`. The only guard (`forbid_knowledge_type`, in `brain/ingest/payloads.py`) is called exclusively from the two *automatic background hooks* (`post_tool_use.py`, `session_ingest.py`), silently coercing to `conversation` — it exists to stop passive, unintentional session capture from polluting the corpus, not to stop an agent acting on explicit user instruction. (Confirmed live: one stray `knowledge` row with `source=claude_code_session` already exists from exactly this — the user asked an agent to save something as knowledge, and it worked.)

So the actual remaining friction is narrower than it first looked: **someone still has to manually create a file (or run a CLI command) and remember the right flags** (`--project`, `--source`, `--corpus`). A UI removes that, now that the paraphrase step is gone.

---

## The real design question: where does chunking run?

The browser can't execute Python — `brain/ingest/text_chunking.py` only runs server-side today, invoked from a terminal. Three options, discussed and compared:

1. **Reimplement chunking in Rust.** Rejected — directly violates the existing project rule ("ALL Python ingest paths must import from here, never implement chunking/tagging inline") and creates two implementations that can drift.
2. **A separate standalone Python microservice just for ingestion.** Keeps chunking in its one canonical place, but adds a second local server to run, document, and keep alive (new port, new launchd job, new failure mode) for a feature used occasionally, not continuously.
3. **A new `brain_api` (Rust) endpoint that receives the upload/link, then shells out to the existing `ingest_knowledge.py` as a subprocess.** — **Recommended.** The browser only ever talks to one backend (port 8787, same as everything else). Chunking logic stays exactly where it already lives, zero duplication. There's already precedent for Rust spawning a subprocess for something it'd rather not reimplement: `summarizer.rs` calls `curl` via `std::process::Command`. `reqwest` (needed for the link-fetch half) is already a Cargo dependency — no new crate required.

## Known open sub-problem: link ingestion

Fetching a URL server-side is trivial (`reqwest`, already available). Extracting *readable* text from arbitrary HTML is not solved anywhere in this codebase yet — no HTML-to-text logic exists in `brain/ingest/` today. Needs a deliberate, scoped decision before building (strip-tags-and-take-main-content vs. something smarter) rather than picking silently.

## Sketch of the flow (not yet detailed into tasks — do that when this is picked up)

```
Browser (Brain Viewer, new "Ingest" view)
  │  attach file  OR  paste URL
  ▼
POST /ingest  (new brain_api endpoint)
  │  file: write to a temp path
  │  link: fetch via reqwest, extract readable text (TBD), write to a temp path
  ▼
Command::new("python3") brain/tools/ingest_knowledge.py <temp_path> --project ... --source ...
  │  (existing, unchanged: chunk_by_sections → refine_chunks_for_word_limit → api_client.save_memory)
  ▼
memory_type=knowledge rows, verbatim, correct source/file_path/provenance
```

## Why deferred

Explicit owner decision: build the open cognitive-architecture gates (G3, G7, G8, and the `superseded_by` quarantine cleanup identified while scoping G2) first. This doc exists so the design work already done in conversation isn't lost or re-derived later.
