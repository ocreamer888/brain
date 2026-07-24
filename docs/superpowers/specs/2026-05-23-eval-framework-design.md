# Brain Eval Framework — Design Spec
**Date:** 2026-05-23  
**Status:** Approved  
**Author:** Claude Code (CTO)

---

## Problem

The brain has 3 separate eval tools that don't communicate, no trend history, and a known retrieval regression (non-fact P@1 dropped 33pp between May 2 and May 21) with no way to diagnose when or why it happened. The kfold eval hits the DB directly and never measures what Claude actually sees through the MCP/API path. Any change to the brain is currently a guess.

---

## Goal

One command that runs all eval modes, measures the MCP path gap, writes results to a dashboard in the brain viewer, and auto-runs a quick check after every ingest session.

---

## Architecture

### New files

| File | Purpose |
|---|---|
| `brain/tools/eval_suite.py` | Unified entry point — orchestrates all eval modes, writes report |
| `brain/tools/mcp_eval.py` | New eval mode — tests actual MCP/API search path vs gold_semantic |
| `brain/tests/test_eval_suite.py` | TDD tests for eval_suite orchestration |
| `brain/tests/test_mcp_eval.py` | TDD tests for MCP path eval |

### Modified files

| File | Change |
|---|---|
| `brain/rust/static/index.html` | Add "Eval" tab that reads `/eval_dashboard.json` |
| Stop hook (`session_end` or equivalent) | Call `eval_suite.py --quick --mcp` after ingest |

### Eval modes (4 total)

| Mode | Flag | Speed | Data source | What it measures |
|---|---|---|---|---|
| `quick_gate` | `--quick` | ~10s | Direct DB (cosine) | P@1 per type — fast health check |
| `kfold` | `--kfold` | ~3 min | Direct DB (cosine + BM25) | P@1/P@5/MRR leave-one-out by type and project |
| `gold_vault` | `--vault` | ~30s | API path | Recall@k on hand-curated vault-file queries |
| `mcp_path` | `--mcp` | ~1 min | MCP/API path | P@1/MRR via actual search path vs gold_semantic.jsonl |

Default run: `--quick --mcp`. Full suite: `--all`.

---

## Data Flow

```
eval_suite.py --quick --mcp
  │
  ├── ingest_quality_gate.run_gate()    → quick P@1 per type
  ├── mcp_eval.run_mcp_eval()           → MCP P@1/MRR + gap vs DB
  │     └── api_client.search()         → actual search path Claude uses
  │
  ├── aggregate → EvalReport dataclass
  │
  ├── brain/eval/runs/2026-05-23-1430.json   (append)
  └── brain/rust/static/eval_dashboard.json  (overwrite with full history)
```

---

## EvalReport Structure

```json
{
  "run_id": "2026-05-23-1430",
  "modes_run": ["quick_gate", "mcp_path"],
  "pass": true,
  "quick_gate": {
    "status": "ok",
    "exit_code": 0,
    "by_type": {
      "conversation": 0.71,
      "pattern": 0.58,
      "solution": 0.63,
      "project_context": 0.52
    }
  },
  "kfold": null,
  "gold_vault": null,
  "mcp_path": {
    "status": "ok",
    "n_queries": 45,
    "precision_at_1": 0.64,
    "mrr": 0.71,
    "gap_vs_kfold_p1": -0.07
  }
}
```

`gap_vs_kfold_p1` = MCP P@1 minus last kfold P@1. Negative means the API path is losing quality vs the DB.

---

## MCP Path Eval (new module)

`mcp_eval.py` reuses `brain/eval/gold_semantic.jsonl` (45 hand-curated paraphrase queries, each with a `gold_memory_id`).

For each query:
1. Call `api_client.search(query, n=10)` — same call the MCP server makes
2. Check if `gold_memory_id` appears in top-1 and top-k results
3. Compute P@1, P@5, MRR

**Why this matters:** The kfold eval uses direct cosine similarity on raw DB embeddings. The production search path applies recency decay, mean-centering (T1), and reranking on top. If those layers degrade results, kfold P@1 will look fine while Claude gets bad answers. This eval surfaces that gap.

**If brain API is not running:** Mode is skipped, marked `"status": "skipped"` in the report. Not a hard failure.

---

## Dashboard (brain viewer tab)

`eval_suite.py` maintains `brain/rust/static/eval_dashboard.json`:

```json
{
  "runs": [
    {
      "run_id": "2026-05-23-1430",
      "pass": true,
      "quick_p1_avg": 0.61,
      "mcp_p1": 0.64,
      "mcp_gap": -0.07,
      "non_fact_p1": 0.58
    }
  ]
}
```

The "Eval" tab in `index.html` fetches `/eval_dashboard.json` at tab load and renders:
- A trend table: one row per run, newest first
- P@1 per type bars (quick_gate) for the most recent run
- MCP gap indicator (green if gap > -0.05, red if gap ≤ -0.05)

No new Rust endpoints. The existing static file server serves the JSON.

---

## Stop Hook Integration

After ingest, the stop hook calls:
```bash
python3 brain/tools/eval_suite.py --quick --mcp --quiet
```

`--quiet` suppresses per-query output; only writes the report files. If the brain API is not running (normal during off-session), `--mcp` is skipped automatically.

---

## Error Handling

- Each eval mode runs in isolation — a crash in one mode does not abort others
- Mode result is `{"status": "error", "reason": "<exception>"}` on failure
- Dashboard JSON is written atomically (write temp → rename) to avoid corruption on crash
- If `brain/rust/static/` does not exist, write dashboard to `brain/eval/eval_dashboard.json` and warn

---

## Testing Strategy

TDD — tests written before implementation.

`test_eval_suite.py`:
- `test_report_structure` — EvalReport serializes correctly with all modes
- `test_mode_isolation` — one mode error does not abort others
- `test_dashboard_append` — each run appends to history, newest first
- `test_pass_fail` — `pass=False` when any mode hits ERROR threshold

`test_mcp_eval.py`:
- `test_p1_calculation` — correct P@1 from mocked search results
- `test_gold_id_in_top1` — hit detected when gold_id is first result
- `test_api_unavailable` — returns `{"status": "skipped"}` on connection error
- `test_gap_calculation` — gap computed correctly from P@1 and baseline

Smoke test: `eval_suite.py --quick --dry-run` — loads DB, skips embedding/API, exit 0.

---

## Constraints

- No new Python dependencies (uses numpy, sqlite3, existing api_client)
- No Rust changes
- Dashboard JSON stays under 1MB for at least 2 years of daily runs (~700 runs × ~1KB each)
- `eval_suite.py` adds no new CLI flags to existing tools — purely a new orchestrator

---

## Success Criteria

1. `python3 brain/tools/eval_suite.py --all` produces one combined JSON report
2. The brain viewer "Eval" tab shows P@1 trend with at least 3 historical runs visible
3. MCP gap is measured and visible in the dashboard
4. Stop hook triggers `--quick --mcp` automatically and dashboard updates
5. All 8 new tests pass
