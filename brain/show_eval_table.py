#!/usr/bin/env python3
"""Print brain retrieval eval metrics tables for social media screenshots."""


def box(title, rows, headers, widths):
    total = sum(widths) + len(widths) * 3 + 1
    top = "┌" + "─" * (total - 2) + "┐"
    bot = "└" + "─" * (total - 2) + "┘"
    mid = "├" + "─" * (total - 2) + "┤"
    title_pad = (total - 2 - len(title)) // 2
    title_line = "│" + " " * title_pad + title + " " * (total - 2 - title_pad - len(title)) + "│"

    def row_line(cells):
        parts = [f" {cell:<{w}} " for cell, w in zip(cells, widths)]
        return "│" + "│".join(parts) + "│"

    print(top)
    print(title_line)
    print(mid)
    print(row_line(headers))
    print(mid)
    for r in rows:
        print(row_line(r))
    print(bot)


print()

headers1 = ["Date", "Eval", "Corpus", "Mode", "P@1", "MRR", "Notes"]
widths1  = [8, 16, 8, 10, 6, 6, 38]
rows1 = [
    ["APR 26", "k-fold",        "~2,400",  "cosine", "0.640", "0.700", "Pre-BM25 baseline"],
    ["MAY 01", "k-fold",        "~2,400",  "RRF",    "0.807", "0.859", "BM25+RRF shipped (+16.7pp)"],
    ["MAY 02", "k-fold",        "2,271",   "RRF",    "0.797", "0.849", "Post-reingest tuned"],
    ["MAY 21", "k-fold full",   "19,581",  "RRF",    "0.838", "0.860", "8.6x corpus growth"],
    ["MAY 21", "gold-semantic", "19,581",  "vector", "1.000", "1.000", "18 paraphrase queries — perfect"],
    ["MAY 22", "k-fold sample", "18,975",  "RRF",    "0.846", "0.868", "Post-backfill (+3,400 fixed)"],
    ["MAY 22", "k-fold full",   "19,049",  "RRF",    "0.835", "0.860", "Post-retitle (2,017 re-embedded)"],
    ["MAY 22", "gold-semantic", "19,043",  "vector", "1.000", "1.000", "11 conversation queries — perfect"],
]
box("  BRAIN RETRIEVAL EVAL — HISTORY  ", rows1, headers1, widths1)

print()

headers2 = ["Type", "n", "P@1", "MRR", "Status"]
widths2  = [16, 6, 6, 6, 30]
rows2 = [
    ["fact",            "14,759", "0.957", "0.976", "✓ Excellent"],
    ["decision",        "16",     "0.938", "0.948", "✓ Strong"],
    ["error_lesson",    "61",     "0.902", "0.940", "✓ Strong"],
    ["pattern",         "651",    "0.964", "0.980", "✓ Excellent  (+30pp post-fix)"],
    ["solution",        "1,440",  "0.844", "0.896", "✓ Good       (+6pp post-fix)"],
    ["project_context", "904",    "0.480", "0.535", "⚠ Weak"],
    ["conversation *",  "2,017",  "0.094", "—",     "→ gold-semantic: 1.000 ✓"],
]
box("  BY TYPE — 2026-05-22 FULL K-FOLD (RRF, n=19,049)  ", rows2, headers2, widths2)

print()
print("  * Conversation k-fold P@1 is a metric artifact — titles semantically")
print("    collide across 2,017 sessions. Gold-semantic (11 paraphrase queries,")
print("    0 vocab overlap) confirms retrieval is intact: P@1 = 1.000.")
print()
