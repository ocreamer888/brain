#!/usr/bin/env python3
"""Print the brain/tools catalog (purpose + category) from each script's docstring.

Usage:
    python3 brain/tools/list_tools.py
    python3 brain/tools/list_tools.py --markdown   # same table as docs/TOOLS.md body
"""
from __future__ import annotations

import argparse
import ast
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_TOOLS = _REPO / "brain" / "tools"

# Hand-maintained categories — update when adding a tool.
_CATEGORIES: dict[str, list[str]] = {
    "Pipeline & ops": [
        "brain_pipeline.py",
        "brain_chain.sh",
        "brain_observability_probe.py",
        "replay_spool.py",
        "spool_maintenance.py",
        "incident_drill.py",
        "verify_cutover.py",
    ],
    "Ingest & corpus": [
        "ingest_knowledge.py",
        "ingest_session_chunks.py",
        "ingest_quality_gate.py",
        "reingest_ocreamer_docs.py",
        "link_vault_files.py",
    ],
    "Backfill & migration": [
        "backfill_entities.py",
        "backfill_facts.py",
        "backfill_orchestrator.py",
        "backfill_state.py",
        "backfill_bad_data.py",
        "seed_durable_backfill_checkpoint.py",
        "migrate_checkpoints.py",
        "merge_macbook_brain.py",
        "export_to_jsonl.py",
        "export_onnx.py",
    ],
    "Fact & entity hygiene": [
        "quarantine_path_fragment_facts.py",
        "retag_path_fragment_projects.py",
        "stamp_event_times.py",
    ],
    "Eval & retrieval": [
        "eval_suite.py",
        "mcp_eval.py",
        "eval_relevance_set.py",
        "retrieval_eval.py",
        "retrieval_eval_kfold.py",
        "retrieval_compare_reports.py",
        "retrieval_rerank.py",
        "gen_gold_graph.py",
        "graph_expand_ab.py",
        "rebuild_eval_dashboard.py",
        "show_eval_table.py",
    ],
    "Dedup, noise & quality": [
        "bvh_dedup.py",
        "dedup_db.py",
        "noise_detect.py",
        "noise_diagnose.py",
        "noise_effectiveness.py",
        "prune_trivial_memories.py",
        "confidence_score.py",
        "corroboration.py",
    ],
    "Retitle & re-embed": [
        "retitle_chunks.py",
        "retitle_conversations.py",
        "retitle_ppf_llm.py",
        "retitle_reembed.py",
        "reembed_conversations.py",
    ],
    "Export & dashboards": [
        "export_feedback.py",
        "export_knowledge_graph.py",
        "export_metrics_obsidian.py",
        "export_metrics_prom.py",
        "feedback_digest.py",
        "refresh_obsidian_dashboard.sh",
    ],
}

_SKIP_SUFFIXES = {".sh"}


def _summary(path: Path) -> str:
    if path.suffix in _SKIP_SUFFIXES:
        return "(shell script — see file header)"
    try:
        doc = ast.get_docstring(ast.parse(path.read_text(encoding="utf-8")))
    except SyntaxError:
        return "(parse error)"
    if not doc:
        return "(no docstring)"
    return doc.strip().split("\n")[0]


def _all_tools() -> list[Path]:
    return sorted(p for p in _TOOLS.iterdir() if p.is_file() and p.name != "list_tools.py")


def _categorized() -> tuple[list[tuple[str, Path]], list[Path]]:
    known = {name for names in _CATEGORIES.values() for name in names}
    ordered: list[tuple[str, Path]] = []
    for category, names in _CATEGORIES.items():
        for name in names:
            path = _TOOLS / name
            if path.is_file():
                ordered.append((category, path))
    uncategorized = [p for p in _all_tools() if p.name not in known]
    return ordered, uncategorized


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--markdown", action="store_true", help="Markdown table output")
    args = parser.parse_args()

    ordered, uncategorized = _categorized()
    rows: list[tuple[str, str, str]] = []
    last_cat = ""
    for category, path in ordered:
        rows.append((category if category != last_cat else "", path.name, _summary(path)))
        last_cat = category
    for path in uncategorized:
        rows.append(("Uncategorized", path.name, _summary(path)))

    if args.markdown:
        print("| Category | Script | Purpose |")
        print("|---|---|---|")
        for cat, name, summary in rows:
            print(f"| {cat} | `{name}` | {summary} |")
    else:
        for cat, name, summary in rows:
            label = f"[{cat}] " if cat else ""
            print(f"{label}{name}: {summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
