# Cognitive Architecture — Vision Diagram

Companion to `docs/architecture/cognitive-architecture-spec.md`. Three views: the full loop at scale, a zoom into the memory row mapped against the original vision, and the owner's temporal-layer model (spec §8).

Sources: the original vision (`docs/architecture/I designed this for brain, what do u think_.md`) and the owner's hand-drawn sketches from 2026-10-21 (`docs/architecture/sketches/2026-10-21-layers-full.png`, `docs/architecture/sketches/2026-10-21-layers-zoom.png`).

Solid/green = exists in code today. Dashed/yellow = proposed, not built. Red = referenced in the vision but doesn't exist in that form yet.

**Revised 2026-10-21:** confidence is now defined (layer confidence, derived at query time, spec §8.3), salience is marked for retirement from ranking, `superseded_by` is reinterpreted as a layer link, and §3–§4 are new.

**Revised 2026-11-05:** salience retirement shipped as `salience_pinned` (G0) rather than a blind retirement — see section 2's `SAL` node. `source_quality_w` added as a new, real (code-shipped) node, closing the gap where the original vision's `source_quality` idea had no place in this diagram — see section 2's new `SQ` node and item 4 below.

---

## 1. Full architecture in vision

```mermaid
flowchart TD
    subgraph HOST["HOST AGENT — Cursor / Claude (owns cognition)"]
        PERCEIVE[Perceive]
        PLAN[Plan]
        ACT[Act]
        OBSERVE[Observe]
    end

    subgraph BRAIN["BRAIN — owns memory, not cognition"]
        RETRIEVE["R(q, c, M)<br/>hybrid retrieve + rank<br/>cosine + BM25 + recency + knowledge-type<br/>(salience live today — to be replaced by layer confidence, G8)"]
        M[("M — memory store, append-only<br/>memories + entities + mentions-edges<br/>+ feedback_events + curation_events")]
        LAYER["layer confidence c(m)<br/>derived at query time from<br/>how many newer layers sit on the same subject"]
        ROUTE["f_π(q,c,m,g)<br/>ADVISORY route recommendation<br/>answer · clarify · search · verify · act"]
    end

    subgraph LEDGER["EXECUTION LEDGER — proposed, Stage 4"]
        GOAL[Goal] --> GPLAN[Plan] --> STEP[Step] --> GACT[Action] --> GOBS[Observation] --> OUT[Outcome]
    end

    PERCEIVE --> RETRIEVE
    M --> RETRIEVE
    M -.-> LAYER
    LAYER -. "modulates rank" .-> RETRIEVE
    RETRIEVE --> ROUTE
    ROUTE -. "recommendation, host may override" .-> PLAN
    PLAN --> ACT
    ACT --> OBSERVE
    OBSERVE -. "new layer on top, never overwrite" .-> M
    OBSERVE -. "proposed: record" .-> GOAL
    OBSERVE --> PERCEIVE

    classDef exists fill:#102010,stroke:#4a9,color:#fff
    classDef proposed fill:#201010,stroke:#e5bd24,color:#fff,stroke-dasharray: 6 4
    class HOST,RETRIEVE,M exists
    class ROUTE,LEDGER,LAYER proposed
```

**Reading it:** Brain is one box, not the whole diagram. Perceive/Plan/Act/Observe belong to the host today and stay there in every stage of the spec. Brain's proposed expansions beyond "store and rank" are two advisory signals: **layer confidence** (which memory in a stack to trust) and **route identification** (what the host should do next). Both are recommendations the host can ignore, not replacements for the host's box.

---

## 2. Memory structure — mapped to the original vision's symbols

Verified against `brain/rust/src/types.rs` and the live schema:

```mermaid
flowchart TD
    subgraph ROW["ONE memory row — x, s, t, y are ATTRIBUTES (columns) on it"]
        direction LR
        ID["id, content<br/>(m — the memory itself)"]
        TYPE["type (t)<br/>fact · solution · decision · conversation ·<br/>pattern · project_context · error_lesson · episode · knowledge"]
        PROJ["project (x)<br/>plain string — NOT a structured entity"]
        TIME["timestamp + event_time (y)<br/>ingest-time vs occurred-time<br/>layer order uses event_time, fallback timestamp"]
        SRC["source (s)<br/>WHERE it came from (claude_code_session, cursor_history...)<br/>NOT trustworthiness — see source_quality_w"]
        SQ["source_quality_w(source)<br/>HOW MUCH to trust the origin, computed from source<br/>93.7% of rows are claude_code_session alone (one tier) —<br/>exposed on every result; not applied to ranking by default,<br/>inconclusive A/B on the current gold set (2026-11-05)"]
        SAL["salience<br/>LLM score set once at save; UI 'pin'<br/>live in ranking only when salience_pinned (G0, 2026-11-04)"]
        FP["file_path<br/>strongest 'same subject' signal<br/>only 2.7% of rows have it (G10)"]
        SUP["superseded_by<br/>today: HIDES the old row from search<br/>vision: explicit layer link (w = 1)<br/>overloaded for quarantine:*/hidden:* (not history) —<br/>resolved_supersedes() (store.rs, 2026-11-05) resolves this<br/>safely; dangling pointers (59 rows) reclassified, not left raw"]
    end

    CONF["confidence c(m)<br/>NOT a column — derived at query time<br/>from layer depth (spec §8.3)"]

    ID -.-> TYPE
    ID -.-> PROJ
    ID -.-> TIME
    ID -.-> SRC
    SRC -. "derives" .-> SQ
    ID -.-> SAL
    ID -.-> FP
    ID -.-> SUP
    SUP -. "feeds" .-> CONF

    ENT[("entities table<br/>28,289 rows")]
    EDGE["edges (z — 'links')<br/>relation_type = 'mentions' ONLY<br/>memory to entity, 71,025 edges<br/>old (superseded) layers: 0 edges (G9)"]

    ID --> EDGE --> ENT

    classDef real fill:#102010,stroke:#4a9,color:#fff
    classDef warn fill:#2a1a05,stroke:#e5bd24,color:#fff
    classDef proposed fill:#201010,stroke:#e5bd24,color:#fff,stroke-dasharray: 6 4
    class ID,TYPE,PROJ,TIME,SRC,EDGE,ENT real
    class SAL,FP,SUP,SQ warn
    class CONF proposed
```

### Where the vision matches, and where it doesn't

1. **Type / source / date / project as a tree above memory** — matches, as a **view**. In the owner's sketch they form a navigation path (`brain → project → source → type → date`). Those are all columns on one row, so the tree is a way of addressing and filtering existing data and needs no new tables. That path is the structured, traceable half of the hybrid system.

2. **`links` (z)** — exists, but narrower than drawn: "this memory mentions this entity" (e.g. a memory mentioning "Supabase" links to a `Supabase` entity row). It is not memory-to-memory reasoning ("this contradicts that"). That richer link type was tried once (`graph_expand`), measurably hurt retrieval, and is off by default pending a benchmark. In the owner's model, `z` is the associative half: it finds neighbours and decides which memories are layers of the same subject (§4 below).

3. **`confidence` (c)** — **now defined** (spec §8). It is not salience (the LLM's one-time score) and not the raw ranker `score`. It is **layer confidence**: how many newer memories sit on top of this one about the same subject. It is **computed at query time and never stored**, so old memories are never rewritten. On the sketch's 1–10 scale, the top layer is `c = 10`.

4. **`source_quality` (s, trustworthiness half)** — the original vision conversation proposed this, and the gate table carried it forward as an orphaned "G2" reference that the 2026-10-21 revision never reconciled against the layer model. It earns a real place here because it answers a question neither `salience_pinned` nor layer confidence does: not "did a human pin this" and not "has something newer superseded it," but "how much should I inherently trust the pipeline that produced it, independent of both." Implemented 2026-11-05 as `source_quality_w(source)` — a pure function of the already-stored `source` enum, no schema column needed. Exposed on every search result; **not** applied to `final_score` by default, matching the discipline G0 established for salience. A/B on the current gold set was inconclusive (97.8% of the corpus shares one tier, so nothing in that set exercises a real tier contrast) — needs a gold set that actually contrasts `obsidian_books`/`perplexity` against session capture before this can be validated either way.

---

## 3. Temporal layers — the owner's model (spec §8)

Append-only: a change adds a new layer on top, and the old layer stays, linked and traceable.

```mermaid
flowchart TD
    A((a · agent)) --> N((n · brain))
    N --> X1((x₁ · project))
    N --> X2((x₂))
    N --> X3((x₃))
    X1 --> S((s · source))
    S --> T1((t₁ · type))
    S --> T2((t₂))

    subgraph STACK1["stack: one subject, under t₁"]
        direction TB
        M2a["m₂ · y₂ (newer)<br/>depth 0 → c = 10"]
        M1a["m₁ · y₁ (older)<br/>depth 1 → c lower"]
        M2a --- M1a
    end

    subgraph STACK2["stack: another subject, under t₂"]
        direction TB
        M2b["m₂ · y₂ (newer)<br/>c = 10"]
        M1b["m₁ · y₁ (older)<br/>c lower"]
        M2b --- M1b
    end

    T1 --> M2a
    T2 --> M2b

    N -.-> Z{{"z · links<br/>(associative layer)"}}
    Z -. "same subject?" .-> STACK1
    Z -. "neighbours across projects/types" .-> STACK2

    classDef real fill:#102010,stroke:#4a9,color:#fff
    classDef proposed fill:#201010,stroke:#e5bd24,color:#fff,stroke-dasharray: 6 4
    class A,N,X1,X2,X3,S,T1,T2 real
    class STACK1,STACK2,Z proposed
```

**Key rule:** confidence depends on **relative depth within a subject's stack, not absolute age.** A year-old decision that nothing has replaced stays `c = 10`. A file changed three times last week leaves its first version low. Absolute age is handled separately and lightly by `recency_w`.

```
depth(m)   = Σ  w(m, m')   over newer m' on the same subject   (w ∈ [0,1], 1 if explicit supersede)
layer_w(m) = F + (1 − F) · λ^depth(m)        ranking modulator, bounded [F, 1]
c(m)       = 1 + 9 · λ^depth(m)              display scale 1–10
```

---

## 4. Spotting specifics — how Brain decides two memories share a subject

From the sketch: *"For a vectorize layer we need a way to spot specifics, but this can be a wide range of things."*

```mermaid
flowchart LR
    PAIR["newer m'<br/>older m"] --> T1{"Tier 1<br/>same file_path?"}
    T1 -- yes --> SAME["same subject → m' layers on m"]
    T1 -- "no / missing (97% of rows)" --> T2{"Tier 2<br/>same project +<br/>shared SPECIFIC entity?<br/>2 ≤ df(e) ≤ D_max"}
    T2 -- yes --> SAME
    T2 -- no --> T3{"Tier 3<br/>same project + type,<br/>similarity ≥ τ_sim?"}
    T3 -- yes --> SAME
    T3 -- no --> DIFF["different subjects<br/>no layering"]

    classDef real fill:#102010,stroke:#4a9,color:#fff
    classDef proposed fill:#201010,stroke:#e5bd24,color:#fff,stroke-dasharray: 6 4
    class PAIR real
    class T1,T2,T3,SAME,DIFF proposed
```

| Tier | Live data (2026-10-21) | Problem to solve |
|---|---|---|
| 1 file path | 614 rows have one; 44 paths have >1 memory | Capture at save time + index (G10) |
| 2 specific entity | 28,289 entities: 18,747 used once (useless), 95 used 50+ times (too generic, e.g. Next.js 805), useful middle like `SmileDoc.tsx` (9) | Pick `D_max`; filter noise entities |
| 3 similarity | every row has an embedding | Precompute `similar_to` neighbours (G7) to keep it cheap |

**Ground truth for tuning:** 1,780 real "newer replaced older" pairs already in the DB (spec §8.6). Today 0 of their older rows have entity links, because entity backfill skips superseded rows (G9). The experiment in spec §8.7 measures each tier against these pairs before anything changes live.
