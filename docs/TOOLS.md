# Brain Tools Catalog

Operational scripts under `brain/tools/`. Run from repo root with **`.venv/bin/python`** unless noted.

**Regenerate this table:** `python3 brain/tools/list_tools.py --markdown`

## Quick picks

| Need | Start here |
|---|---|
| Daily maintenance | `brain_pipeline.py daily` |
| Hook spool stuck | `replay_spool.py` |
| Entity edges missing | `backfill_entities.py` (canary 100 first) |
| Fact layer backfill | `backfill_facts.py --all` |
| Authored docs corpus | `ingest_knowledge.py` |
| Retrieval quality | `eval_suite.py --quick --mcp` |
| `graph_expand` gate | `graph_expand_ab.py` |
| Path-fragment junk facts | `quarantine_path_fragment_facts.py` / `retag_path_fragment_projects.py` |
| List everything | `list_tools.py` |
| Masterpiece / Forge gates | `brain/harness/run_gates.py` (Phase A — see spec index below) |

## Brain Forge Harness (phased)

High-confidence agentic engineering: constitution + deterministic gates + skills + optional long-running worker.

**Doc index:** [`docs/superpowers/specs/2026-08-12-brain-forge-harness-index.md`](superpowers/specs/2026-08-12-brain-forge-harness-index.md)

| Phase | Status | Key paths |
|---|---|---|
| A — Constitution + gates | **Closed 2026-08-12** | `brain/constitution/`, `brain/harness/run_gates.py` |
| B — Skills + MCP bridge | **Closed 2026-08-13** | `.agents/skills/brain-forge-*/`, `teeth_check.py`, `canary_sample.py` |
| C — Long-running worker | **Closed 2026-08-13 (C2)** | `worker.py`, `supervisor.py`, `job_spec.schema.json` |
| D — Continual harness (tactics) | **Initial ship 2026-08-13** | `refine_audit.py`, `refine-policy.md`, skill `brain-forge-refine` |

**Run gates:** `.venv/bin/python brain/harness/run_gates.py --phase verify --emit-json brain/eval/runs/gates-$(date +%Y%m%d-%H%M%S).json`

**Teeth:** `.venv/bin/python brain/harness/teeth_check.py --all`

**Canary:** `.venv/bin/python brain/harness/canary_sample.py --label JOB --limit 100`

**Worker:** `.venv/bin/python brain/harness/supervisor.py start brain/harness/examples/job-phase-c-canary-1k.json`

**Recover:** `.venv/bin/python brain/harness/supervisor.py recover <job_id>`

**Daemon (inbox once / poll):** `.venv/bin/python brain/harness/supervisor.py daemon --once`  
_(always-on: `docs/deploy/com.brain.forge.plist` — do not `launchctl load` without owner OK)_

**Refine:** `.venv/bin/python brain/harness/refine_audit.py classify --target pattern --edit-summary "..."`  
**Pre-commit denylist:** `.venv/bin/python brain/harness/refine_audit.py check-staged` (hook: `brain/harness/git-hooks/pre-commit`)

**Entity backfill canary job (25 rows, dedicated checkpoint):** `brain/harness/examples/job-entity-backfill-canary-25.json`

**Prod simulation (real path):** `.venv/bin/python brain/harness/prod_simulation.py`  
_(fail-closed acts 1–3, then recover act 4 — not green theater)_

## Safety notes

- **Backfills:** checkpoint-resumable; freeze auto-reflect (`BRAIN_REFLECTION_DISABLED=1`) before bulk writes.
- **Destructive scripts** (`dedup_db.py`, `backfill_bad_data.py`, `prune_trivial_memories.py`): `--dry-run` first; backup `brain/rust/brain.db`.
- **Live API tools** use `brain/api_client.py` → `http://127.0.0.1:8787` (rate limits: read/write buckets split per V-17).
- **Hooks vs MCP:** hooks run from `~/Documents/AI`; MCP uses this repo. After editing hook-path code, run `pytest brain/tests/test_deploy_parity.py`.

## Full catalog

| Category | Script | Purpose |
|---|---|---|
| Pipeline & ops | `brain_pipeline.py` | Brain pipeline runner — executes named flows as ordered, logged steps. |
|  | `brain_chain.sh` | (shell script — see file header) |
|  | `brain_observability_probe.py` | Emit core Rust-brain runtime health and lag metrics as JSON. |
|  | `replay_spool.py` | Replay queued memory writes from durable hook spool. |
|  | `spool_maintenance.py` | Prune old spool and DLQ records by age. |
|  | `incident_drill.py` | Guided incident drill helper for API-down and replay evidence capture. |
|  | `verify_cutover.py` | Verify Rust grows while Chroma stays flat for a probe write. |
| Ingest & corpus | `ingest_knowledge.py` | Deliberate corpus ingest → type=knowledge memories (spec 2026-08-06). |
|  | `ingest_session_chunks.py` | Ingest raw session transcripts as chunked conversation memories. |
|  | `ingest_quality_gate.py` | Post-ingest quality gate: samples k-fold P@1 by type and warns/fails on thresholds. |
|  | `reingest_ocreamer_docs.py` | Re-ingest bracket-prefixed doc chunks into titled, word-bounded memories (any project). |
|  | `link_vault_files.py` | Link arbitrary vault markdown files into brain-graph via semantic search. |
| Backfill & migration | `backfill_entities.py` | Backfill entities/edges for existing durable memories that have zero edges. |
|  | `backfill_facts.py` | Extract and curate facts from multiple sources. |
|  | `backfill_orchestrator.py` | Checkpointed orchestrator for bulk backfill stages. |
|  | `backfill_state.py` | State helpers for checkpointed bulk backfill orchestration. |
|  | `backfill_bad_data.py` | One-shot script: fix all bad memories in brain.db created by ingest bugs. |
|  | `seed_durable_backfill_checkpoint.py` | One-off: seed the durable entity-backfill checkpoint from a legacy fact-only one. |
|  | `migrate_checkpoints.py` | One-off: populate ingest checkpoints with session_ids already in DB. |
|  | `merge_macbook_brain.py` | One-shot merge: pull memories from MacBook brain (via tunnel on :18787) |
|  | `export_to_jsonl.py` | Export all ChromaDB memories to JSONL for Phase 6 Rust migration. |
|  | `export_onnx.py` | Export all-mpnet-base-v2 to ONNX format for the Rust brain embedder. |
| Fact & entity hygiene | `quarantine_path_fragment_facts.py` | Quarantine path-fragment-project facts (soft-delete via superseded_by). |
|  | `retag_path_fragment_projects.py` | Retag path-fragment projects onto canonical names (high-confidence only). |
|  | `stamp_event_times.py` | One-time script: stamp event_time on facts that have none. |
| Eval & retrieval | `eval_suite.py` | Brain eval suite — unified orchestrator for all eval modes. |
|  | `mcp_eval.py` | MCP path eval — queries via api_client.search() and scores against gold_semantic.jsonl. |
|  | `eval_relevance_set.py` | Relevance-set retrieval eval: a hit = top-1 is ANY memory in the query's |
|  | `retrieval_eval.py` | Evaluate brain retrieval against a JSONL gold set (recall@k, MRR). |
|  | `retrieval_eval_kfold.py` | Leave-one-out retrieval eval (precision@k, MRR) over the full memory corpus. |
|  | `retrieval_compare_reports.py` | Compare retrieval reports side-by-side (RRF vs alpha-hybrid). |
|  | `retrieval_rerank.py` | Heuristic re-ranking for brain search hits (Phase 1: rules only). |
|  | `gen_gold_graph.py` | Generate a graph-aware gold set for the `graph_expand` A/B (amendment A1). |
|  | `graph_expand_ab.py` | Paired A/B of `graph_expand` off vs on, with a hard statistical gate (A1). |
|  | `rebuild_eval_dashboard.py` | Rebuild eval_dashboard.json from the per-run archive in brain/eval/runs/. |
|  | `show_eval_table.py` | Print brain retrieval eval metrics tables for social media screenshots. |
| Dedup, noise & quality | `bvh_dedup.py` | BVH-style near-duplicate detector for brain memories (Tier 1 Item 3). |
|  | `dedup_db.py` | One-off: remove duplicate memories from brain.db. |
|  | `noise_detect.py` | Perturbation-based memory fragility detector (Noise Detection, Tier 1 Item 2). |
|  | `noise_diagnose.py` | Root-cause diagnostic for why noise detection fails. Read-only. |
|  | `noise_effectiveness.py` | Measure whether deleting high-fragility memories actually helps retrieval. |
|  | `prune_trivial_memories.py` | Scan the brain corpus for trivial / noise memories and optionally delete them. |
|  | `confidence_score.py` | Confidence-by-Corroboration scorer — v1, SHADOW MODE (Task 10). |
|  | `corroboration.py` | Cross-memory corroboration scorer + Phase-0 measurement (AlphaFold MSA analog). |
| Retitle & re-embed | `retitle_chunks.py` | Retitle raw markdown chunks and enrich session stubs. |
|  | `retitle_conversations.py` | Retitle conversation memories with meaningful titles derived from content. |
|  | `retitle_ppf_llm.py` | LLM-retitle ppf-contact-solver conversation chunks using local Ollama. |
|  | `retitle_reembed.py` | Retitle AND re-embed memory chunks in place (IDs preserved). |
|  | `reembed_conversations.py` | Re-embed all conversation memories to encode their current titles. |
| Export & dashboards | `export_feedback.py` | Export `feedback_events` from the brain SQLite database as JSONL (one JSON object per line). |
|  | `export_knowledge_graph.py` | Export brain memories as an Obsidian knowledge graph. |
|  | `export_metrics_obsidian.py` | Export brain metrics to JSON for an Obsidian DataviewJS dashboard. |
|  | `export_metrics_prom.py` | Export brain observability metrics in Prometheus text format. |
|  | `feedback_digest.py` | Append new feedback_events to a markdown digest (Obsidian-style daily inbox). |
|  | `refresh_obsidian_dashboard.sh` | (shell script — see file header) |
