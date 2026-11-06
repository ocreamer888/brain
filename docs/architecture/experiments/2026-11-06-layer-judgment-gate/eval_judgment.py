"""Validate brain/ingest/layer_judgment.py against the uncensored hand-labelled
ground truth from docs/architecture/experiments/2026-10-21-layer-detection/exp3_labeled.json.

That experiment found deterministic tiers alone hit ~33% precision at
deciding whether a candidate pair is actually the same evolving subject
(LAYER) vs RELATED/DUP/UNRELATED. This measures whether the LLM judgement
step (spec §8.7a proposal B) does meaningfully better, using FULL live
content (not the 400-char truncated snippets baked into exp3_labeled.json)
read from the current brain.db.

Read-only. Writes nothing to brain.db. Pairs whose old_id or new_id no
longer exist live (DB has changed since 2026-10-21) are reported and
excluded, not silently dropped.

Usage:
    ./.venv/bin/python3 docs/architecture/experiments/2026-11-06-layer-judgment-gate/eval_judgment.py
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO_ROOT))

from brain.ingest.layer_judgment import classify_pair, VALID_LABELS, MIN_CANDIDATE_SIM

DEFAULT_LABELED_PATH = (
    REPO_ROOT
    / "docs/architecture/experiments/2026-10-21-layer-detection/exp3_labeled.json"
)
DB_PATH = REPO_ROOT / "brain/rust/brain.db"


def live_content(conn: sqlite3.Connection, memory_id: str) -> str | None:
    row = conn.execute(
        "SELECT content FROM memories WHERE id = ?", (memory_id,)
    ).fetchone()
    return row[0] if row else None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--labeled", type=Path, default=DEFAULT_LABELED_PATH)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()
    labeled_path = args.labeled
    out_path = args.out or Path(__file__).resolve().parent / f"results_{labeled_path.stem}.json"

    labeled = json.loads(labeled_path.read_text())
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)

    resolvable = []
    missing = []
    for row in labeled:
        old_c = live_content(conn, row["old_id"])
        new_c = live_content(conn, row["new_id"])
        if old_c is None or new_c is None:
            missing.append(row["idx"])
            continue
        resolvable.append({**row, "old_live": old_c, "new_live": new_c})

    print(f"hand-labelled pairs: {len(labeled)}")
    print(f"resolvable live (both ids still exist): {len(resolvable)}")
    print(f"dropped (id no longer live): {len(missing)} -> idx {missing}")
    print(f"ground-truth label distribution (resolvable set): "
          f"{Counter(r['label'] for r in resolvable)}")
    print()

    results = []
    errors = 0
    below_floor = 0
    t0 = time.time()
    for row in resolvable:
        if row["sim"] < MIN_CANDIDATE_SIM:
            # Not a candidate at all (see MIN_CANDIDATE_SIM) -- never reaches
            # the judgement call, recorded as a non-LAYER verdict for the
            # binary metric and as its own bucket in the confusion matrix.
            below_floor += 1
            results.append(
                {
                    "idx": row["idx"], "band": row.get("band", "n/a"), "sim": row["sim"],
                    "truth": row["label"], "judged": "SKIPPED(<floor)", "reason": "",
                }
            )
            continue
        try:
            judged = classify_pair(row["old_live"], row["new_live"], row["sim"])
        except Exception as e:  # noqa: BLE001 - record and continue, mirrors fact_curator error counting
            errors += 1
            print(f"  [idx {row['idx']}] classify_pair error: {e}")
            continue
        results.append(
            {
                "idx": row["idx"],
                "band": row.get("band", "n/a"),
                "sim": row["sim"],
                "truth": row["label"],
                "judged": judged.label,
                "reason": judged.reason,
            }
        )
    elapsed = time.time() - t0
    print(f"\nskipped below MIN_CANDIDATE_SIM={MIN_CANDIDATE_SIM}: {below_floor}")
    print(f"classified {len(results) - below_floor}/{len(resolvable) - below_floor} "
          f"eligible pairs in {elapsed:.1f}s "
          f"({errors} errors)")

    # Confusion matrix over the 4-way label.
    confusion: Counter[tuple[str, str]] = Counter()
    for r in results:
        confusion[(r["truth"], r["judged"])] += 1

    print("\nConfusion matrix (rows=truth, cols=judged):")
    truth_labels = sorted(VALID_LABELS)
    judged_labels = truth_labels + ["SKIPPED(<floor)"]
    header = "truth\\judged".ljust(12) + "".join(l.ljust(16) for l in judged_labels)
    print(header)
    for t in truth_labels:
        line = t.ljust(12)
        for j in judged_labels:
            line += str(confusion.get((t, j), 0)).ljust(16)
        print(line)

    # Binary LAYER-detection precision/recall/F1 -- this is the number that
    # actually gates depth(): only judged-LAYER pairs contribute to L(m).
    tp = sum(1 for r in results if r["truth"] == "LAYER" and r["judged"] == "LAYER")
    fp = sum(1 for r in results if r["truth"] != "LAYER" and r["judged"] == "LAYER")
    fn = sum(1 for r in results if r["truth"] == "LAYER" and r["judged"] != "LAYER")
    tn = sum(1 for r in results if r["truth"] != "LAYER" and r["judged"] != "LAYER")
    precision = tp / (tp + fp) if (tp + fp) else float("nan")
    recall = tp / (tp + fn) if (tp + fn) else float("nan")
    f1 = (
        2 * precision * recall / (precision + recall)
        if (precision + recall) and precision == precision and recall == recall
        else float("nan")
    )

    print(f"\nBinary LAYER detection: TP={tp} FP={fp} FN={fn} TN={tn}")
    print(f"  precision={precision:.3f}  recall={recall:.3f}  f1={f1:.3f}")
    print(f"  (2026-10-21 tier-only baseline precision: ~0.33 on a related-but-"
          f"different candidate pool -- not a strict apples-to-apples n, both "
          f"n are small; treat as directional, not a certified metric)")

    misclassified = [r for r in results if r["truth"] != r["judged"]]
    print(f"\nMisclassified ({len(misclassified)}):")
    for r in misclassified:
        print(f"  idx={r['idx']} band={r['band']} sim={r['sim']} "
              f"truth={r['truth']} judged={r['judged']} reason={r['reason']!r}")

    out_path.write_text(
        json.dumps(
            {
                "n_labeled": len(labeled),
                "n_resolvable": len(resolvable),
                "dropped_idx": missing,
                "errors": errors,
                "elapsed_s": elapsed,
                "confusion": {f"{t}|{j}": n for (t, j), n in confusion.items()},
                "layer_binary": {
                    "tp": tp, "fp": fp, "fn": fn, "tn": tn,
                    "precision": precision, "recall": recall, "f1": f1,
                },
                "results": results,
            },
            indent=2,
        )
    )
    print(f"\nFull results written to {out_path}")


if __name__ == "__main__":
    main()
