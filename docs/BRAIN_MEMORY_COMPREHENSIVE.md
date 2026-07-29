# Brain Memory System — Comprehensive Documentation

**Last Updated:** 2026-05-27  
**Based on:** Actual MCP brain implementation (Rust brain_api + Python fallback)  
**Scope:** All memory types, save methods, retrieval patterns, and efficiency insights

---

## Overview

The brain is a persistent memory system with ~17,400 memories (auto-maintained via BVH dedup, noise detection, and title dedup). It provides semantic search with type-biased template routing, metadata-aware queries, and temporal retrieval. Automated cleanup runs after every session. See `docs/BRAIN.md` for the full architecture and session lifecycle.

---

## Part 1: Memory Types, Subtypes & Tags

### Actual Memory Types (8 categories)

The brain stores memories in these type categories:

| Type | Purpose | Created by | Example |
|------|---------|-----------|---------|
| **fact** | Verified data, metrics, timestamps | Fact backfill pipeline | "Auth migration took 3 weeks in production (2026-04-15)" |
| **solution** | Bug fixes, implementations | PostToolUse hook (error-fix pairs, writes) | "Fixed race condition in token cache by using atomic swap" |
| **error_lesson** | Error→fix pairs with cause and context | Session end recycling Pass 1 | "Error: ModuleNotFoundError. Cause: missing dep. Fix: added to requirements.txt" |
| **pattern** | Decisions, best practices, approaches | Session end recycling Pass 2 | "Chose cubic barrier over linear threshold for corpus self-regulation" |
| **decision** | Architecture choices, agent dispatches | PostToolUse hook (Agent tool) | "Dispatched agent to audit all hook files for inconsistencies" |
| **project_context** | Session summaries, roadmaps, constraints | Session end recycling Pass 3 | "Phase 10 shipped: smart capture + corpus barrier + recycling loop" |
| **conversation** | Chat, Q&A, dialogue | Historical ingests | "User asked about authentication flow options" |
| **episode** | Full session/document body for audit | Fact layer (parent of extracted facts) | Full transcript of a Claude Code session |

### Tags (Metadata Descriptors)

Tags further categorize memories. Common tags observed in the brain:

- **Process tags:** `reflected` (consolidated by reflection), `ingest_<source>` (ingested from specific source)
- **Domain tags:** `security`, `performance`, `testing`, `documentation`, `architecture`
- **Status tags:** `blocked_by_<dependency>`, `requires_approval`, `deprecated`
- **Source tags:** `claude_code_session`, `perplexity`, `obsidian`, `books`, `cursor_session`

Tags are **comma-separated strings**. You can use any tags that make semantic sense for your memory.

### No Subtypes

The brain does not have formal "subtypes" within each memory_type. Classification happens via:
1. The **memory_type** (5 types above)
2. The **tags** (flexible, user-defined)
3. The **project** (scoping to a specific project or "general")

---

## Part 2: Saving Memories — Complete Reference

### save_memory_tool() Function

**MCP Signature:**
```
save_memory_tool(
  content: str,           # Required. The memory content.
  memory_type: str = "conversation",  # Optional. One of: conversation, fact, solution, pattern, project_context
  tags: str = "",         # Optional. Comma-separated tags, e.g. "security,performance,blocked_by_auth"
  project: str = "",      # Optional. Project name. Defaults to "general" if empty.
  source: str = "claude_code_session",  # Optional. Source identifier.
  title: str = ""         # Optional. Short title for the memory.
) -> str
```

### Metadata Stored Automatically

When you save, the system auto-generates and stores:

| Field | Type | Generated/Set By |
|-------|------|------------------|
| id | UUID string | Auto-generated |
| content | text | Your content parameter |
| embedding | vector | Auto-embedded (semantic meaning) |
| timestamp | ISO 8601 datetime | Auto-set to current time (or you can pass via title if needed) |
| type | string | Your memory_type parameter |
| project | string | Your project parameter (or "general") |
| tags | comma-separated string | Your tags parameter |
| source | string | Your source parameter |
| title | string | Your title parameter |
| session_id | string | Auto-filled if available |
| importance | float | Defaults to 0.5 (not directly settable) |

### File Structure (Filesystem Memories)

Beyond the MCP database, memories can be stored as markdown files in `~/.claude/projects/<project>/memory/`:

**Format:**
```markdown
---
name: {{memory_name}}
description: {{one-line description — used for search relevance}}
type: {{conversation|pattern|project_context|solution|fact}}
---

{{Memory content with structured sections}}

**Why:** {{Reasoning behind the decision/pattern}}

**How to apply:** {{When/where this matters}}
```

**Example:**
```markdown
---
name: Never guess, suppose, or imagine
description: Claude must never speculate without verified sources
type: feedback
---

Only state facts you can verify from files, tools, or search results.

**Why:** User explicitly demanded this after Claude speculated about integration without verified sources.

**How to apply:** If uncertain, say "I don't know" and use tools to research rather than guessing.
```

### Ways to Save Data

**1. Via MCP save_memory_tool (recommended)**
```
save_memory_tool(
  content="Fixed race condition by using atomic swap in cache layer",
  memory_type="solution",
  tags="performance,thread-safety,cache",
  project="wealth-api",
  title="Cache atomicity fix — 2026-05-10"
)
```

**2. Via MCP hooks (automatic)**
The `brain_user_prompt_submit` hook automatically saves session summaries. Configured in `~/.claude/settings.json`.

**3. Via filesystem (manual index)**
Save `.md` files directly to `memory/` directory, then update `MEMORY.md` index:
```markdown
- [Cache Atomicity Fix](solution_cache_atomic.md) — Race condition fix using atomic swap
```

**4. Via brain reflection (automatic consolidation)**
Every 20 saves, `reflect_tool()` automatically:
- Identifies duplicate/near-duplicate memories
- Consolidates patterns
- Saves consolidated memories as `pattern` type with `reflected` tag
- Deletes redundant originals

---

## Part 3: Retrieval Patterns & Efficiency Insights

### The 3-Layer Retrieval Pattern (Recommended)

**DO THIS ORDER:**

**Layer 1: Get Stats (for metadata recency)**
```
get_stats_tool()
```
Returns: total_memories, total_sessions, feedback_events_total, feedback_last_event_ts, save_count_this_session

**Layer 2: Search Index (metadata-aware with timestamps)**
```
search_index(query="latest projects", n=20, memory_type="project_context", project="")
```
Returns compact rows with:
- id (UUID)
- memory_type
- project
- snippet (first 200 chars)
- parent_id (if episode)
- **timestamp** (crucial for ordering)

**Layer 3: Timeline Tool (chronological context around an ID)**
```
timeline_tool(anchor_id="<id-from-layer-2>", before=3, after=3)
```
Returns chronological neighbors (3 before, 3 after) with timestamps.

**Layer 4: Get Observations (full content for specific IDs)**
```
get_observations_tool(ids="id1,id2,id3")
```
Returns full content for only the IDs you actually need.

### Critical Efficiency Insight: Don't Use search_brain for Recency

**❌ WRONG (will return semantically relevant but old memories):**
```
search_brain(query="latest projects")
```
Result: Returns LifeHub (May 9) + SICOP Health (May 5) ordered by semantic distance, not timestamp.
Problem: search_brain orders by semantic relevance distance, not creation time.

**✅ RIGHT (will return actually newest memories):**
```
1. get_stats_tool()  # see feedback_last_event_ts
2. search_index(query="projects", n=20)  # returns with timestamps
3. Sort by timestamp in results
4. timeline_tool(anchor_id=newest_id, before=10)  # see chronological context
```

### Tool Selection Guide

| Goal | Tool(s) | Why |
|------|---------|-----|
| Find latest memories | stats → search_index → timeline | search_index returns timestamps; timeline shows context |
| Find relevant memories regardless of age | search_brain | Semantic relevance ordering |
| Get full context around a memory | timeline_tool | Chronological neighbors |
| Get complete content for IDs | get_observations_tool | Only fetch what you need |
| Get topic-relevant memories at session start | get_context_tool | Pre-filtered top N |
| Consolidate duplicates | reflect_tool | Automatic every 20 saves |
| Save new knowledge | save_memory_tool | Specify type, tags, project |
| Log user feedback | record_feedback | Track accepted/rejected/edited memories |

### search_brain vs search_index

| Feature | search_brain | search_index |
|---------|--------------|-------------|
| Ordering | Semantic distance (closest first) | Metadata relevance + snippet |
| Returns | Full content + metadata | Compact ID + snippet + timestamp |
| Speed | Slower (vector embedding) | Faster (metadata index) |
| When to use | "Find all patterns like this" | "Find memories matching criteria with recency" |
| Timestamp aware | No | Yes |

---

## Part 4: Complete MCP Tool Reference

### search_brain(query, n=10, memory_type="", project="", graph_expand=False, min_salience=0.0)

Semantic search across all memories. When `memory_type` is not set, the query is
routed through **template_search** (query-intent → type-weighted retrieval).

**Parameters:**
- `query` (str): Natural language search query
- `n` (int): Number of results (default 10)
- `memory_type` (str): Optional filter: "conversation", "solution", "fact", "pattern", "project_context". Setting it bypasses query-intent routing.
- `project` (str): Optional filter by project name
- `min_salience` (float, 0.0–1.0): Optional **confidence filter** — suppress results whose Trust (salience) is below this threshold. Default 0.0 (no filtering).

**Returns:** List of up to n memories ordered by semantic relevance (closest first)

**Output format:**
```
[1] (type | project)
    [Content]
    Tags: [tags] | Source: [source]
    Distance: [relevance_score] | Trust: [salience]   ← "⚠ low-trust" appended when < 0.40
    Source file: [file_path if applicable]
```

**Trust score:** the `Trust` value is the memory's salience — LLM-assigned importance/durability
(populated for facts; 0.5 default for other types) nudged by feedback (accepted +0.05 / rejected −0.10).
It also weights ranking (`salience_w` in the Rust scorer). Note: this is a trust/importance signal,
**not** a correctness/hallucination score.

**Query-intent routing (template_search):** if no `memory_type` is given, the query is classified
(troubleshooting→solution+error_lesson, decision→decision+pattern, status→project_context, factual→fact)
and intent-matched types are boosted to the top. Measured +0.143 P@1 / +0.201 MRR vs plain search.

**Active-learning prompt:** when the top-2 results are within ~0.05 cosine distance, the output appends an
"⚠ Uncertain retrieval" note inviting `record_feedback` — this is how the feedback→salience loop is seeded.

**Use when:** Finding related memories, patterns, or solutions regardless of age.

---

### search_index(query, n=10, memory_type="", project="")

Metadata-aware search with timestamps. Returns compact rows.

**Parameters:** Same as search_brain

**Returns:** Compact rows with id, memory_type, project, snippet, parent_id (if episode), timestamp

**Output format:**
```
[#<id>] <memory_type> | <project> | <snippet>
```

**Use when:** Finding memories by recency, filtering by metadata, bulk ID retrieval.

---

### timeline_tool(anchor_id, before=3, after=3)

Get chronological context around a specific memory.

**Parameters:**
- `anchor_id` (str): UUID of the memory to center on
- `before` (int): How many older memories to show (default 3)
- `after` (int): How many newer memories to show (default 3)

**Returns:** Chronologically ordered memories (older → anchor → newer) with timestamps

**Output format:**
```
[2026-05-12T10:30:00Z] [Memory content first 200 chars]
[2026-05-12T09:15:00Z] [Previous memory...]
...
```

**Use when:** Understanding the context when a memory was saved, seeing what else was happening.

---

### get_observations_tool(ids)

Fetch full content for specific memory IDs.

**Parameters:**
- `ids` (str): Comma-separated list of UUIDs, e.g., "id1,id2,id3"

**Returns:** Full content for each ID

**Output format:**
```
--- <id> ---
[Full memory content]

--- <id> ---
[Full memory content]
```

**Use when:** Retrieving complete details after using search_index (which returns snippets).

---

### get_context_tool(topic, project="", n=5)

Get top N most relevant memories for a topic at session start.

**Parameters:**
- `topic` (str): Topic to retrieve context for (e.g., "authentication flow")
- `project` (str): Optional project filter
- `n` (int): Number of memories (default 5)

**Returns:** Top n memories ordered by relevance

**Output format:**
```
Top 5 memories for 'authentication flow':

[1] [conversation] User asked about OAuth vs session tokens
[2] [solution] Implemented JWT validation with refresh rotation
...
```

**Use when:** Starting work on a topic to load relevant context quickly.

---

### save_memory_tool(content, memory_type="conversation", tags="", project="", source="claude_code_session", title="")

Save a new memory to the brain.

**Parameters:**
- `content` (str, required): The memory content
- `memory_type` (str): "conversation" (default), "solution", "fact", "pattern", or "project_context"
- `tags` (str): Comma-separated tags, e.g., "security,performance,blocked_by_auth"
- `project` (str): Project name (defaults to "general")
- `source` (str): Source identifier (defaults to "claude_code_session")
- `title` (str): Short title for the memory

**Returns:** Memory saved: {id}

**Use when:** Storing important decisions, solutions, patterns, or project context.

---

### get_episode(id)

Expand a memory to its source episode (context from when it was saved).

**Parameters:**
- `id` (str): UUID of a memory (typically a fact)

**Returns:** Episode content with project and full context

**Use when:** Needing the broader context around a specific fact.

---

### reflect_tool()

Consolidate and find patterns across recent memories.

**How it works:**
- Runs automatically every 20 saves
- Identifies duplicate/near-duplicate memories
- Finds common patterns
- Saves consolidated memories as `pattern` type with `reflected` tag
- Deletes redundant originals

**Parameters:** None

**Returns:** Reflection complete. Brain stats: {...}

**Use when:** Manually triggering consolidation or checking stats after bulk saves.

---

### get_stats_tool()

Get brain statistics.

**Parameters:** None

**Returns:** JSON with:
- `total_memories`: Total count across all time
- `total_sessions`: Number of sessions
- `save_count_this_session`: Memories saved this session
- `feedback_events_total`: Feedback events logged
- `feedback_last_event_ts`: ISO timestamp of last feedback event

**Use when:** Checking brain health, understanding recency baseline.

---

### record_feedback(event_type, memory_id="", query="", session_id="", project="", payload_json="", idempotency_key="")

Log feedback when user accepts, rejects, edits, or dismisses a memory.

**Parameters:**
- `event_type` (str): "accepted", "rejected", "edited", "ranked", or "dismissed"
- `memory_id` (str): UUID of the memory
- `query` (str): Original query that retrieved the memory
- `session_id` (str): Session ID where feedback occurred
- `project` (str): Project context
- `payload_json` (str): Optional JSON object with extra data
- `idempotency_key` (str): For deduplication

**Returns:** `Feedback recorded: {feedback_id}` — and for `accepted`/`rejected` with a `memory_id`, the memory's salience is auto-nudged (+0.05 / −0.10, clamped 0.1–1.0) and appended to the message. Since salience weights ranking, this closes the active-learning loop.

**Use when:** User confirms/corrects a retrieved memory, so future retrieval improves. Especially after an "⚠ Uncertain retrieval" prompt from `search_brain`.

---

## Part 5: Metadata Fields Reference

When you save a memory, these fields are stored:

| Field | Type | Set By | Notes |
|-------|------|--------|-------|
| id | UUID string | Auto | Unique identifier |
| content | text | save_memory_tool parameter | The actual memory text |
| embedding | vector | Auto | Semantic embedding (768 dims, all-mpnet-base-v2) |
| timestamp | ISO 8601 | Auto (current time) | When memory was saved |
| type | string | memory_type parameter | One of 5 types |
| project | string | project parameter | Scoping (default: "general") |
| tags | comma-separated string | tags parameter | User-defined descriptors |
| source | string | source parameter | Origin identifier |
| session_id | string | Auto | Session where saved |
| title | string | title parameter | Short name/label |
| importance | float | Auto | Defaults to 0.5 |
| salience | float | LLM at ingest (facts) + feedback nudge | Trust/importance 0.0–1.0; weights ranking; surfaced as "Trust" in search_brain. Default 0.5 |
| file_path | string | Auto (for ingested files) | Source file if applicable |
| parent_id | UUID string | Auto (for episodes) | Episode parent if applicable |

---

## Part 6: Discovered Efficiency Insights

### Key Findings

1. **Semantic search is not for recency** — search_brain orders by distance, not timestamp. For "latest", use stats → search_index → timeline.

2. **search_index is metadata-aware** — Returns timestamps, so you can sort by creation time.

3. **timeline_tool shows chronological context** — Perfect for understanding what else was happening when a memory was saved.

4. **get_observations_tool is fetch-efficient** — Returns full content only for IDs you need, avoiding bloat.

5. **Reflection consolidates automatically** — Every 20 saves, duplicates are merged and patterns extracted as `pattern` type memories.

6. **Filesystem memories (MEMORY.md) are separate** — The 8 saved `.md` files are a manual index; the MCP database (18,832 memories) is the authoritative store.

### Query Cost Considerations

- **search_brain:** Expensive (full embedding + similarity), slowest, most thorough
- **search_index:** Cheaper (metadata index), fast, good for bulk filtering
- **timeline_tool:** Cheap (chronological walk), instant, context-aware
- **get_observations_tool:** Cheap (ID lookup), instant, only fetch what needed

### Recommended Workflow

```
1. Use search_index first — fast metadata filter
2. If you need context, use timeline_tool on the anchor ID
3. If you need full content, use get_observations_tool on IDs
4. Fall back to search_brain only if semantic relevance matters more than recency
```

---

## Part 7: Best Practices

### DO:
- ✅ Save non-obvious decisions, patterns, and solutions
- ✅ Use specific memory_type (don't default everything to "conversation")
- ✅ Add relevant tags for filtering (e.g., "blocked_by_migration", "security")
- ✅ Use project filter to scope queries to specific projects
- ✅ Use the 3-layer pattern for complex queries
- ✅ Log feedback when user corrects or confirms a memory

### DON'T:
- ❌ Use search_brain for "latest" queries — use search_index + timeline instead
- ❌ Save trivial ephemeral context that won't matter in future sessions
- ❌ Guess memory_type — think about whether it's a fact, solution, pattern, etc.
- ❌ Fetch full observations for all search results — use IDs and get only what's needed
- ❌ Ignore reflection results — consolidated memories are more valuable

---

## Part 8: Integration with CLAUDE.md

Add this to your project's CLAUDE.md under a "Brain Memory" section:

```markdown
## Brain (Persistent Memory)

The brain is a vector-search memory system with 18,832+ memories. Query it proactively using these tools:

**Three-Layer Retrieval (for latest):**
1. `get_stats_tool()` — metadata baseline
2. `search_index(query, memory_type="...", project="...")` — metadata-aware with timestamps
3. `timeline_tool(anchor_id)` — chronological context

**Single Query:**
- `search_brain(query)` — semantic relevance (not for recency)
- `get_context_tool(topic, project="", n=5)` — topic-specific top N

**Save:**
- `save_memory_tool(content, memory_type="fact|solution|pattern|project_context|conversation", tags="...", project="...")`

**Memory Types:**
- `fact` — verified information, metrics, timestamps
- `solution` — bug fixes, implementations, code work
- `pattern` — recurring behaviors, best practices, decisions
- `project_context` — roadmaps, constraints, stakeholder decisions
- `conversation` — chat context, questions, clarifications

**Key Insight:** For "latest", don't use search_brain (orders by semantic distance, not time). Use stats → search_index → timeline instead.

**Efficiency:** search_index is fast and metadata-aware. Use get_observations_tool to fetch full content only for IDs you need.
```

---

## Appendix: Quick Reference

### Memory Types at a Glance
- **conversation** - Chat, Q&A, dialogue
- **fact** - Data, metrics, verified info
- **solution** - Fixes, implementations, PRs
- **pattern** - Behaviors, best practices
- **project_context** - Decisions, constraints

### Tools by Use Case
| Need | Tool | Order |
|------|------|-------|
| Latest memories | stats → search_index → timeline | 1 → 2 → 3 |
| Relevant regardless of age | search_brain | 1 |
| Topic context at start | get_context_tool | 1 |
| Full content for IDs | get_observations_tool | 1 |
| Consolidate duplicates | reflect_tool | manual |
| Save new | save_memory_tool | anytime |

---

**This documentation reflects the actual MCP brain implementation as of 2026-05-12.**
