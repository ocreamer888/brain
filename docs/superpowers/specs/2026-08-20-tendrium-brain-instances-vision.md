# Tendrium Brain Instances — Product Vision

**Date:** 2026-08-20
**Status:** Vision draft — not approved for build. Captures the shared picture so we can polish the structure before speccing implementation.
**Scope:** Brain shipped *inside* the Tendrium product as a per-customer memory / control-tower surface — distinct from Brain-for-building-Tendrium (dev memory), which we are **not** designing here.

---

## 1. Lineage (how we got here)

Conversation of 2026-08-20. The question was: *"How would brain work for Tendrium if we make an instance just for Tendrium?"*

We split it into two readings:

- **Reading A — dev brain:** Brain as the Tendrium team's engineering memory. Cheap; mostly solved by existing `project=` scoping or one dedicated instance.
- **Reading B — product feature:** Brain as a runtime capability serving **Tendrium's end customers** — per-customer memory over their tenders/licitaciones and briefings.

The user chose **Reading B**. This document is Reading B only.

---

## 2. What Tendrium is (for readers without context)

Tendrium is the in-app briefing agent built on the `sicop-health` codebase (SICOP = Costa Rican public-procurement / licitación domain). It has:

- a **data plane** (ETL over tenders/licitaciones), and
- a **conversation plane** (in-app briefing agent).

Status as of 2026-08-16: agent-executable scope for "Tendrium A" complete (226 frontend + 601 ETL tests pass), production launch gated on a live Anthropic key + deploy. See `sicop-health/docs/superpowers/2026-08-16-tendrium-a-implementation.md`.

The product value of Brain-inside-Tendrium: a **per-customer control tower over their tenders** — "why did we flag this licitación," "what did we decide last time," "what changed since the last briefing" — backed by durable, searchable memory instead of a stateless chat.

---

## 3. What Brain is today (grounded, with file refs)

Verified against this checkout (`feature/durable-entity-linking`):

- **One process, one store.** `brain_api` binds one SQLite file via a single `rusqlite::Connection` (`brain/rust/src/store.rs:36,61`), guarded by one global write lock.
- **Vector index is in-memory**, rebuilt from stored embeddings on load.
- **Single global auth.** One `BRAIN_API_KEY` Bearer token; `auth_required` toggles it (`brain/rust/src/bin/brain_api.rs:333,1349`). No per-user, no per-tenant identity.
- **`project` is a filter column, not a boundary.** Indexed (`idx_memories_project`), applied as an optional `AND m.project = ?` supplied *by the caller* (`brain/rust/src/store.rs:1097`). The client chooses the value; the server does not enforce it.
- **Memory taxonomy** (`brain/rust/src/types.rs`): `Fact`, `Episode`, `Knowledge`, `Solution`, `Decision`, `Pattern`, `ProjectContext`, `ErrorLesson`, `Conversation` — plus `event_time`, `salience`, `parent_id`, `superseded_by` fields already in the schema.
- **Reusable engine:** hybrid BM25 + vector retrieval, BVH dedup, entity/graph linking, recency/salience scoring, feedback loop.

### 3a. Brain Instances (already built — see `2026-07-27-brain-instances-design.md`)

The **instances** primitive exists in the product (built, not yet pulled to this checkout). Its shape:

- Same code + **one** `brain_api` process; **separate SQLite file per instance** under `~/.brain/instances/<slug>/brain.db`.
- **One live instance at a time**: switching closes the current DB, opens another, rebuilds the in-memory index.
- Registry at `~/.brain/instances.json`; CRUD + archive/delete via `/v1/instances*`.
- **Explicit v1 non-goals:** multiple concurrent processes/ports, cross-instance search, per-instance MCP config.

**Key implication for Tendrium:** the built instances feature is a *single-user, one-active-at-a-time corpus switcher*. It gives us **hard data isolation per instance** (separate SQLite files) — which is exactly the isolation primitive a per-customer product wants — but its runtime model (one active brain, mutating routes `503` while switching) is **not** a concurrent multi-customer server. Tendrium reuses the *isolation* primitive and must add a *concurrency* model.

---

## 4. The core constraint

Brain is **single-tenant by construction**: one SQLite file, one in-memory index, one API key, `project` as a caller-supplied filter. "An instance just for Tendrium" cleanly means *one dedicated store for Tendrium* — trivial. The hard part is that **Tendrium has many end customers**, and neither `project=` scoping nor the one-active-instance switcher isolates customer A's data from customer B at runtime.

**The non-negotiable:** in a product, the **server** must enforce tenant scope from the authenticated identity. Today the *caller* supplies the scope. Until that inverts, there is no security boundary.

---

## 5. Tenancy models (the fork to decide)

| Model | What it is | Best for | Cost / risk |
| --- | --- | --- | --- |
| **Instance-per-customer** | Each Tendrium customer = its own instance (own SQLite file, own key), built on the existing instances primitive | Enterprise deals, data residency, one-click delete (drop the file), zero blast radius | Existing primitive is one-active-at-a-time → needs concurrent-instances runtime; RAM = sum of every active customer's vector index; ops scale with customer count |
| **Shared instance, tenant = enforced scope** | One store for all customers; reuse `project`/tenant column, but **server forces** the scope from the API key | Many small customers, cheap infra | Requires hardening: cascade delete, per-tenant residency story, single-writer lock becomes a bottleneck under concurrent load |

**Recommendation (from the conversation):** shared instance with **server-enforced tenant scoping** as the default; offer **instance-per-customer** only to enterprise customers who contractually need physical isolation. Standard SaaS pattern. **This choice is still open and is the first decision to lock.**

---

## 6. Gaps to build (Reading B)

Ordered by load-bearing-ness:

1. **Tenant-aware auth** — key→tenant mapping; every handler auto-scopes to the caller's tenant server-side. Nothing else is safe until this exists.
2. **Ingestion path** — today memories come from Claude Code session-end hooks + fact extraction. Tendrium feeds Brain from its **ETL** (tenders/briefings) via the save API. The taxonomy maps cleanly: `Episode` = full tender doc, `Fact` = extracted atomic facts, `Knowledge` = authored corpus, `event_time` = the tender's real date for recency decay.
3. **Scale / RAM** — in-memory vector index means a shared instance holds *all* tenants' vectors in RAM (unbounded); concurrent per-customer instances hold the *sum* of active indexes. Needs sharding or an on-disk ANN, and/or an instance eviction/LRU policy.
4. **Concurrency ceiling** — single SQLite + one global write lock is fine for a solo dev loop; a live product with concurrent customer traffic bottlenecks on it. WAL buys headroom; it is a known ceiling. The one-active-instance switcher must become concurrent for instance-per-customer.
5. **Deletion / residency / PII** — "delete my company's data" must cascade across `memories`, FTS, entities, edges, feedback. Per-customer files make this a file delete; shared instance needs a real cascade + per-tenant residency story.
6. **Embedding cost / latency** — every save and search embeds; at product volume that is a real API bill + p95 latency. Needs batching + caching.

---

## 7. What we get for free

The valuable core already exists and is reusable as-is: hybrid retrieval, dedup, entity/graph linking, the memory-type taxonomy, recency/salience scoring, the feedback loop, **and hard per-corpus isolation via the built instances primitive**. What's missing is not the brain — it's the **multi-tenant + auth + concurrency + ingestion envelope** around it.

---

## 8. Open questions (to polish before speccing)

1. **Tenancy model:** shared-with-enforced-scope vs instance-per-customer vs hybrid-by-tier. (§5)
2. **Where does it run?** Alongside Tendrium's cloud deploy, or a separate Brain service Tendrium calls over the network?
3. **Identity source:** does tenant identity come from Tendrium's existing auth (map Tendrium org → Brain tenant), or a Brain-native key registry?
4. **Ingestion trigger:** batch ETL push, event-driven on tender change, or on-demand at briefing time?
5. **What is a "memory" to a customer?** tender-level, licitación-line-level, briefing-decision-level — sets the granularity of `Episode`/`Fact`.
6. **Deletion / residency contract:** what do we commit to customers (GDPR-style delete, region pinning)?
7. **Cross-customer knowledge:** is there any shared `Knowledge` corpus (e.g. SICOP rules) all tenants read, separate from private per-tenant memory?

---

## 9. Status & next step

- This is a **vision draft**, not an approved build spec. Per project rules (major/architectural change → propose and get approval first), no code follows from this document.
- **Next step:** lock the tenancy model (§5, Q1) and the run/identity questions (§8, Q2–Q3). Once those are fixed, write the implementation spec that extends the built instances primitive with server-enforced tenancy.

## Related

- `2026-07-27-brain-instances-design.md` — the built single-user instances primitive this reuses.
- `sicop-health/docs/superpowers/2026-08-16-tendrium-a-implementation.md` — Tendrium architecture.
- `brain/rust/src/{store.rs,types.rs,bin/brain_api.rs}` — the single-tenant substrate.
