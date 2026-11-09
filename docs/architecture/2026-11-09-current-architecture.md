# Brain — Current Architecture (2026-11-09)

**What this is:** a snapshot of the system as actually deployed and verified against code, not a design intent. Every claim below was checked against `brain.rs`/`brain_api.rs`/`store.rs`/`types.rs`/the UI source at **HEAD `90ad94c`** on 2026-11-09 — grep'd and read, not recalled. Where something is only partly true (shipped in code but not yet surfaced, or shipped but off by default), that's called out explicitly rather than smoothed over.

**Companion docs, not duplicated here:** `docs/architecture/cognitive-architecture-spec.md` (the formal model and the G0–G10 gate history — *why* each piece exists), `docs/architecture/cognitive-architecture-diagram.md` (the temporal-layer node model specifically), `docs/SECURITY_AUDIT_2026-11-05.md` (the security findings this architecture's auth/CORS layer closes), `docs/CHANGELOG-SHARED-CODE-BRAIN.md` (commit-by-commit history). `docs/architecture/system-diagrams.md` is **not current** — it describes a pre-Rust-cutover, ChromaDB-era topology and a "native Rust MCP" that isn't what's deployed (the MCP server is Python stdio, `brain/mcp/server.py`); kept as-is per this repo's own rule against rewriting historical records, but don't read it as today's state.

---

## 1. System context

Who talks to `brain_api`, and how.

```mermaid
flowchart LR
    subgraph Clients
        Browser["Browser dashboard<br/>(React SPA, embedded)"]
        CC["Cursor / Claude Code<br/>hooks (per tool-call subprocess)<br/>+ MCP (persistent stdio)"]
        LAN["Other LAN machines<br/>(MacBook/iMac)<br/>as remote API clients"]
        CLI["CLI tools<br/>ingest_knowledge.py, bench_knowledge.py,<br/>backfill_*.py, verify_cutover.py"]
    end

    Browser -->|"fetch, x-api-key<br/>from localStorage via AuthGate"| API
    CC -->|"brain.api_client<br/>(HTTP, BRAIN_API_KEY from brain/.env)"| API
    LAN -->|"same HTTP API,<br/>Studio LAN IP"| API
    CLI -->|"brain.api_client,<br/>--on-db-host guard for bulk jobs"| API

    API["brain_api<br/>(Rust, axum)<br/>0.0.0.0:8787"]
    API --> SQLite[("brain.db<br/>SQLite, WAL mode")]
    API --> VecIdx[("In-process VectorIndex<br/>(turbovec, 4-bit quantized)<br/>rebuilt from SQLite BLOBs on start/switch")]
    API --> ONNX["ONNX embedder<br/>all-mpnet-base-v2, 768-dim"]
    API -.->|"layer_judgment.py, fact_curator.py<br/>LLM judgement calls only"| Ollama["Ollama<br/>127.0.0.1:11434"]
```

**Why the LAN binding (`0.0.0.0:8787`) is not a bug:** this Mac Studio is the single host; other machines on the same LAN are meant to reach it as remote clients (confirmed deliberate, 2026-11-08). The security boundary is auth (§5), not network isolation.

---

## 2. Request pipeline

Every request's path from socket to response. Two real forks: **fast path vs. locked path** (performance, G6), and **auth-required vs. not** (currently off in production — see §5).

```mermaid
flowchart TD
    Req["Incoming request"] --> CORS["CORS middleware<br/>(global layer, brain_api.rs)<br/>explicit origin allowlist, never '*'"]
    CORS --> Route["axum router dispatch"]
    Route --> ARL["authorize_and_rate_limit()<br/>per-handler, not global"]
    ARL --> RL["Rate-limit check FIRST<br/>(client_key = 'local' — collapsed<br/>after the X-Forwarded-For spoof fix,<br/>security audit #4)"]
    RL --> Auth{"BRAIN_API_AUTH_REQUIRED?"}
    Auth -->|"0 (current prod default)"| Handler
    Auth -->|"1 (template default since tonight)"| KeyCheck{"x-api-key matches?"}
    KeyCheck -->|no| R401["401, dispatches no server-side<br/>event (that's a frontend concern,<br/>see §6 AuthGate)"]
    KeyCheck -->|yes| Handler["Route handler"]

    Handler --> Fork{"graph_expand requested?"}
    Fork -->|"false (default) — fast path"| ReadPool["ReadPool (G6)<br/>fixed pool of read-only SQLite conns<br/>+ cloned Arc&lt;VectorIndex&gt;/embedder<br/>— no Brain lock at all"]
    Fork -->|"true — locked path"| Mutex["Arc&lt;Mutex&lt;Brain&gt;&gt;<br/>serializes with every writer"]

    ReadPool --> Rank["rank_candidates()<br/>see §3 for the formula"]
    Mutex --> Rank
    Rank --> Resp["SearchResult[]<br/>+ lineage when a superseded<br/>row resolves to a real successor"]
```

**Writes** (`/save`, `/save-batch`, `/memories/:id` PATCH, instance mutations) always take the `Arc<Mutex<Brain>>` path — only reads got a lock-free fast path (G6's own scope, verified: profiling showed CPU climbing to 500–800% under concurrent load once the lock was removed from the read side; absolute throughput ceiling past that point is ONNX embedding inference cost, not lock contention — a different, accepted limit).

---

## 3. The ranking formula — what "cognitive" actually means in code

This is the heart of the system: not a single relevance score, but several independent modulators multiplied together, most of them gated behind an explicit decision (a "G" gate) about whether they're trustworthy enough to apply by default.

```
final_score = source_quality_w  ×  salience_w  ×  layer_confidence_w  ×  recency_w  ×  hybrid_score  ×  knowledge_w
```

| Term | Formula | Default | Gate | What it means |
|---|---|---|---|---|
| `hybrid_score` | `α·cos_norm + (1-α)·bm25_norm` | always applied | — | The base relevance signal: blended vector similarity + keyword rank. Everything else *modulates* this, none of it substitutes for it. |
| `recency_w` | `0.85 + 0.15 · 0.5^(age_days/730)` | always applied | — | 2-year half-life, floor 0.85 — age alone never suppresses a result by more than 15%. |
| `salience_w` | `clamp(1 + 0.3·(salience-0.5), 0.85, 1.15)` **only if `salience_pinned`** | on, but only affects ~19 pinned rows | **G0** | The LLM's own one-time quality guess was found to *anti-correlate* with real quality (Phase 6 calibration) — so it's excluded from ranking except for a human's deliberate "Promote" in the UI. |
| `layer_confidence_w` | `layer_w(depth(m))`, bounded `[0.85, 1.0]` | **on by default** | **G8** | Replaces the old blanket `salience_w` for the ~99% of rows that were never pinned. `depth(m)` = how many newer memories about the *same subject* sit on top of this one (via `layer_judgment.py`'s LLM same-subject classifier, F1 0.851). The deeper buried, the more demoted — but never below the floor. |
| `source_quality_w` | fixed per `source` enum (Obsidian 1.15, Perplexity 1.0, session/hook sources 0.85) | **computed always, applied only if the request opts in** | G2 | Shipped but deliberately not live in default ranking — an A/B on the one gold set available was inconclusive (93.7% of the corpus shares one source tier, nothing to contrast against). |
| `knowledge_w` | `clamp(1 + K_BASE + K_CLOSE_MAX·closeness(distance) [+ K_PROJ if same-project], 1.0, cap)` | on, `knowledge`-type rows only | — | A small, hard-capped proximity bonus so deliberately-ingested reference material (`ingest_knowledge.py`) can win a close match without overwhelming everything else. |

**The gate that decides whether a result *appears at all*, separate from scoring:**

```mermaid
flowchart LR
    Cand["Candidate row,<br/>superseded_by IS NOT NULL"] --> Resolve{"resolved_supersedes()<br/>points to a REAL existing row?<br/>(not a dangling id or quarantine sentinel)"}
    Resolve -->|no| Excluded["Excluded from results<br/>— stays hidden, no trace to show"]
    Resolve -->|yes| Flag{"include_superseded_with_lineage?<br/>(default TRUE as of 2026-11-06)"}
    Flag -->|false, explicit override| Excluded
    Flag -->|true| Surface["Surfaces at its demoted layer_w,<br/>carrying lineage{successor id, snippet}<br/>— G8's core promise: nothing hidden,<br/>everything traceable"]
```

This is the one piece of the vision most worth naming precisely: **a superseded memory is never silently gone.** It's demoted, not deleted, and the row that replaced it is attached as `lineage` — though as of today that `lineage` field is **not rendered anywhere in the UI** (verified: zero references to `lineage`/`layer_w`/confidence in the frontend). The reasoning is real and live in the ranking engine; it isn't yet visible to a person using the dashboard. That gap is tracked, not accidental — see the closing note.

---

## 4. The cognitive/temporal-layer data model

The "tree + associative links" hybrid the owner's own notation describes (`cognitive-architecture-spec.md` §8.1), as it actually exists in SQLite today:

```mermaid
flowchart TB
    subgraph Tree["The tree — exact, structured (existing columns, no new tables)"]
        M["memories<br/>project · source · type · timestamp/event_time"]
    end

    subgraph Links["z — associative, cross-cutting (3 relation types, 2 tables)"]
        Edges["edges<br/>relation_type='mentions'<br/>memory → entity<br/>(pre-existing, text/NER-derived)"]
        Similar["memory_links<br/>relation_type='similar_to' (G7)<br/>memory ↔ memory, embedding cosine<br/>86,099 live rows, deduped"]
        Layers["memory_links<br/>relation_type='layers_on' (G8)<br/>memory → memory, same-subject<br/>6,163 live rows from backfill"]
        Decisions["decision_events (G3)<br/>schema exists, NOTHING writes<br/>or reads it in production"]
    end

    M --- Edges
    M --- Similar
    M --- Layers
    M -.->|"not wired up"| Decisions

    Edges -->|"powers"| EntityUI["Linked view:<br/>'shared entity' edges,<br/>MemoryReading's 'Linked' section"]
    Similar -->|"powers"| SimUI["Linked view:<br/>dimmer 3rd ribbon tier,<br/>MemoryReading's 'Related' section<br/>(both shipped 2026-11-08)"]
    Layers -->|"powers"| RankUI["rank_candidates()'s<br/>layer_confidence_w — §3"]
    Decisions -.->|"would power"| Future["G3: an advisory 'what should<br/>happen with this retrieval' layer<br/>— NOT built; explicit non-goal<br/>for this stage"]
```

**What's genuinely new since the last architecture review (this week):** the `similar_to` edges existed in storage for months but had no consumer anywhere — a completely invisible half of the "hybrid system" the vision describes. As of 2026-11-08 they're drawn in the graph and listed in the reading pane. `layers_on` edges, by contrast, never surface as *edges* anywhere visually — they only act invisibly, inside the ranking formula (§3).

**G4, the gate not yet open:** none of these link types currently expand or re-rank a query's results (`graph_expand` only ever walks `edges`, and even that is opt-in, off by default). Using `similar_to` or `layers_on` to actually *change what a search returns* — not just what you can browse to afterward — requires a gold-eval pass that hasn't been run.

---

## 5. Memory architecture — the `Memory` entity and its relations

§4 showed the *conceptual* tree+links model. This is the literal schema underneath it — every table a `Memory` actually touches, read straight from `store.rs`'s `CREATE TABLE` statements, not inferred.

```mermaid
erDiagram
    MEMORIES {
        text id PK
        text content
        text type "9 values, see taxonomy below"
        text project
        text tags "comma-separated"
        text timestamp "ingest time"
        text event_time "nullable, Phase 7, when it actually happened"
        text source
        text session_id
        real importance
        text file_path "nullable, 2.6 pct coverage, G10"
        text thread_id
        text title
        real salience "0.5 default, LLM one-time guess"
        bool salience_pinned "G0, true only on a deliberate human Promote"
        text superseded_by "nullable FK to MEMORIES.id, or a quarantine/hidden sentinel string"
        text extracted_by "G1, canonical provenance field"
        text derived_from "legacy, unused going forward, kept not dropped"
        blob embedding "768-dim, ONNX all-mpnet-base-v2"
    }
    ENTITIES {
        text id PK
        text name
        text name_normalized UK
    }
    EDGES {
        text id PK
        text src_memory_id FK
        text dst_entity_id FK
        text relation_type "mentions, always, today"
        real weight
    }
    MEMORY_LINKS {
        text id PK
        text src_memory_id FK
        text dst_memory_id FK
        text relation_type "similar_to G7 or layers_on G8"
        real weight
    }
    MEMORIES_FTS {
        text id "UNINDEXED, mirrors MEMORIES.id"
        text content
        text title
    }
    PROJECT_PINS {
        text project PK
        text memory_id FK
        text pinned_at
    }
    FEEDBACK_EVENTS {
        text id PK
        text memory_id "nullable, no FK constraint"
        text event_type
        text query
    }

    MEMORIES ||--o{ EDGES : "src mentions an entity"
    ENTITIES ||--o{ EDGES : "dst mentioned by"
    MEMORIES ||--o{ MEMORY_LINKS : "src newer or one side of similar_to"
    MEMORIES ||--o{ MEMORY_LINKS : "dst older or other side of similar_to"
    MEMORIES ||--o| MEMORIES : "superseded_by self reference nullable"
    MEMORIES ||--|| MEMORIES_FTS : "mirrored 1 to 1 for BM25"
    MEMORIES ||--o| PROJECT_PINS : "pinned as a project brief"
    MEMORIES ||--o{ FEEDBACK_EVENTS : "accepted rejected or edited"
```

**Deliberately not folded together, on purpose:** `edges` (memory to **entity**) and `memory_links` (memory to **memory**) look similar but were kept as two tables specifically so neither target type's column gets overloaded the way `superseded_by` already was once (it carries both a real predecessor id *and* `quarantine:*`/`hidden:*` sentinel strings — a known, accepted overload, not a new one to repeat). `memory_links.relation_type` already carries two unrelated shapes (`similar_to` is symmetric/undirected in practice, `layers_on` is directed newer→older) in the same table by design, per spec §7.2's note that a third relation type can join later without conflating either existing shape.

**Operational/audit tables that reference memories loosely (by id string, no FK, often nullable) but aren't part of the entity graph itself:** `curation_events` (`fact_id`, every curator ADD/MERGE/IGNORE/UPDATE decision), `backfill_batches` (`p1_before`/`p1_after` — the regression gate, G5), `decision_events` (`retrieved_memory_ids` as a JSON array — G3, currently written by nothing), `memory_atlas_positions` (cached 3D layout coordinates per `(run_id, point_kind, point_id)`, rebuilt from live data on demand, never a source of truth).

### Memory type taxonomy

Nine `type` values exist; the brand book (§5.6) groups them into seven "signal" roles so two types can share a feel when the icon/word still tell them apart:

| Signal | Types | What it's for |
|---|---|---|
| **Rely** | `fact`, `knowledge` | "You can stand on this" — verified data, or deliberately ingested reference material (`ingest_knowledge.py`, the only sanctioned writer besides explicit saves) |
| **Use** | `decision`, `solution` | A choice or a fix you'd apply again |
| **Notice** | `pattern` | A recurrence worth flagging |
| **Lesson** | `error_lesson` | Something failed and was kept, deliberately, not hidden |
| **Spoken** | `conversation` | Talk — not a status, kept quiet |
| **Frame** | `project_context` | The shelf a memory sits on |
| **Raw** | `episode` | Source tape — a raw tool-call trace, excluded from untyped search by default (`exclude_episodes_by_default`) so it never crowds out curated memory |

### Lifecycle: save → (optional) structure → query-time resolution

```mermaid
flowchart LR
    Save["POST /save or /save-batch<br/>(hook, MCP, CLI, or UI)"] --> Embed["ONNX embed<br/>(768-dim)"]
    Embed --> Write["INSERT INTO memories<br/>+ memories_fts mirror"]
    Write --> MaybeEntities{"auto_entities?"}
    MaybeEntities -->|yes| Extract["entity_extractor.py<br/>-&gt; edges (mentions)"]
    MaybeEntities -->|no, default for bulk| Skip1["skipped — backfill_entities.py<br/>can run later"]

    Write -.->|"offline, scheduled —<br/>NOT part of the save path"| Backfill1["backfill_similar_links.py (G7)<br/>top-k cosine neighbors<br/>-&gt; memory_links(similar_to)"]
    Write -.->|"offline, scheduled"| Backfill2["backfill_layer_links.py (G8)<br/>layer_judgment.py same-subject call<br/>-&gt; memory_links(layers_on)<br/>+ sets superseded_by on the older side"]

    Backfill2 --> Query["A later /search"]
    Extract --> Query
    Skip1 --> Query
    Backfill1 --> Query
    Query --> Rank["rank_candidates()<br/>— §3's formula, reads<br/>layers_on via layer::depth()"]
```

No part of this lifecycle deletes a row. `superseded_by` is the only thing that changes an existing memory after it's written, and only ever to point forward at what replaced it — never to remove content, never to rewrite it.

---

## 6. Security and auth

```mermaid
flowchart LR
    subgraph Today["Production, right now"]
        T1["AUTH_REQUIRED=0"]
        T2["BRAIN_API_KEY=local-dev-key"]
        T3["Any request succeeds,<br/>key checked but not enforced"]
        T1 --> T3
        T2 --> T3
    end
    subgraph Ready["Built, not yet switched on"]
        R1["docs/deploy/com.brain.api.plist<br/>template: AUTH_REQUIRED=1,<br/>BRAIN_API_KEY=REPLACE_ME"]
        R2["brain/.env<br/>(gitignored, holds the real key)<br/>— does not exist yet"]
        R3["AuthGate + Login (UI)<br/>localStorage-backed session,<br/>shipped 2026-11-08"]
        R1 -.->|"owner runs:<br/>openssl rand -hex 32 → .env<br/>+ plutil -replace on live plist<br/>+ launchctl bootstrap"| R2
    end
```

Closed findings (verified against live state, not a commit message, on 2026-11-08): CORS allowlist (no wildcard, RFC1918-LAN-aware), rate-limit bucket-spoofing fix (collapsed to one shared key instead of trusting `X-Forwarded-For`), every committed placeholder key scrubbed from the public repo, the AGENTS.md LAN IP redacted, `.claude/settings.local.json`'s overly-broad grants narrowed. **Not yet flipped live:** the actual `AUTH_REQUIRED=1` + real key rollout — the code and UI are ready; the live service is intentionally still running open, by the owner's own choice, pending that one manual step (`brain/.env` + `plutil -replace` + a launchd reload — see §1 for why I can't do this step myself: the sandbox blocks an agent from both generating *and* reading back real credential material, by design).

---

## 7. Frontend

```mermaid
flowchart TD
    App["App.jsx"] --> Gate["AuthGate<br/>(outside every provider,<br/>so nothing fires a request<br/>before a key is confirmed)"]
    Gate -->|"no/invalid stored key"| Login["Login.jsx<br/>GlowHero reused, Level-4 mesh,<br/>brand book §6.4/§6.5"]
    Gate -->|"valid key"| Providers["StatsProvider + EvalProvider<br/>+ FeedProvider"]
    Providers --> Shell["Shell: Dock nav + view switch"]
    Shell --> Dashboard & Search & Linked & Curate & Eval & Instances

    Linked --> AtlasCanvas["3D atlas (three.js)<br/>forest edges + entity-mention<br/>'extra' edges + similar_to ribbon<br/>tier (3 tiers, §4)"]
    Search --> Reading["MemoryReading<br/>Linked (entities) + Related<br/>(similarity) + Around (time)"]

    Unauthed["Any api() call → 401"] -.->|"dispatches<br/>brain:unauthorized"| Gate
    LockBtn["Dock lock button"] -.->|"same event"| Gate
```

Six views exist (`Dock.jsx`'s `VIEWS`); no new destinations added by this week's work. The brand book's "no new destinations in this pass" rule (§10) still holds — Login isn't a seventh *view*, it's a gate in front of all of them.

---

## 8. Deployment and ops

```mermaid
flowchart LR
    subgraph Launchd["launchd (user agent, uid 501)"]
        Main["com.brain.api<br/>KeepAlive, RunAtLoad<br/>exec: target/release/brain_api"]
        Restart["com.brain.api.restart (NEW, 2026-11-09)<br/>daily 4:10am kickstart -k"]
    end
    Main -->|"writes"| Log["~/Library/Logs/brain_api.err<br/>every request logged"]
    Restart -->|"forces a fresh fd"| Log
    Rotate["/etc/newsyslog.d/brain_api.conf (NEW)<br/>hourly check, 20MB threshold,<br/>5 compressed copies kept"] -->|"renames + compresses<br/>when oversized"| Log
```

`brain_api` has no SIGHUP-reopen support for its log file, so rotation alone would silently stop working after the first rotation (the process keeps writing into the renamed-away file). The daily restart closes that gap — both pieces were missing until 2026-11-09; the log had grown unbounded to 18MB+ before this was noticed and fixed.

---

## What this diagram deliberately does *not* claim

- It does not claim the dashboard *shows* the cognitive reasoning behind a ranking (§3's closing note) — the engine and the product experience are at different levels of completion.
- It does not include G3 (decision-event router / advisory routing) as a working system, because it isn't one — schema only, explicitly out of scope for this stage.
- It does not claim `similar_to`/`layers_on` edges influence *what* gets retrieved, only what gets *shown alongside* a retrieval or *how it's scored once already retrieved* — G4 (ranking/expansion use of new edge types) remains ungated.

**Verified against:** `git log -1` → `90ad94c`, 2026-11-09. Re-verify before trusting exact numbers (edge counts, test counts) against a later HEAD — they drift fast in this project, which is the whole reason this file exists instead of relying on memory.
