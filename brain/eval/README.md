# Brain Retrieval Eval

Full documentation for measuring and tracking retrieval quality.

---

## Which eval to use per memory type

| Memory type | Correct eval | Why |
|-------------|-------------|-----|
| `fact` | K-fold | Every fact title is unique — k-fold is honest |
| `solution` | K-fold | Titles are unique enough for rank-1 signal |
| `pattern` | K-fold | Same |
| `project_context` | K-fold | Same |
| `decision` | K-fold | Same |
| `error_lesson` | K-fold | Same |
| **`conversation`** | **Gold-semantic only** | Titles collide semantically across thousands of sessions ("how do I fix CORS?", "add error handling"). K-fold rank-1 is near-random — not a retrieval failure, a metric artifact. |

**Rule:** Never use k-fold P@1 to judge conversation retrieval quality. Use `gold_semantic_conversations.jsonl`. Add queries there when covering new topic areas.

Gold-semantic result (2026-05-22, 11 queries, 0 vocab overlap): **P@1 = 1.000** — conversation retrieval is intact.

---

## Eval methods

Three complementary evals. Run all three for a complete picture.

### 1. K-fold (primary — no API required)

Leave-one-out: every memory's title/first sentence becomes the query; the eval checks whether that memory ranks #1. Runs directly on `brain/rust/brain.db`. No API needed.

```bash
# Full corpus, BM25+RRF (canonical run — use this for baselines)
python3 brain/tools/retrieval_eval_kfold.py --full --rrf \
  --report brain/eval/kfold_full_rrf_$(date +%Y_%m_%d).json --ks 1,3,5,10

# Sampled (faster, representative)
python3 brain/tools/retrieval_eval_kfold.py --sample 1000 --rrf \
  --report brain/eval/kfold_sample1k_rrf_$(date +%Y_%m_%d).json --ks 1,3,5,10

# Cosine-only (no BM25, for comparison)
python3 brain/tools/retrieval_eval_kfold.py --sample 1000 \
  --report brain/eval/kfold_sample1k_cosine_$(date +%Y_%m_%d).json --ks 1,3,5,10
```

### 2. Gold-semantic (paraphrase queries — no API required)

18 hand-curated queries written as **semantic paraphrases** (zero vocabulary overlap with stored content). Tests pure semantic retrieval. Sweeps alpha values to find optimal cosine/BM25 mix.

```bash
python3 brain/tools/retrieval_eval_kfold.py \
  --gold-semantic brain/eval/gold_semantic.jsonl \
  --report brain/eval/kfold_gold_semantic_$(date +%Y_%m_%d).json --ks 1,5,10
```

Key finding: **pure vector (alpha=0.0) is always best on paraphrase queries.** Any BM25 weight collapses P@1 from 1.0 to ~0.11. These queries have no keyword overlap with stored content by design.

Two gold-semantic sets exist:
- `brain/eval/gold_semantic.jsonl` — 18 queries across all types (original)
- `brain/eval/gold_semantic_conversations.jsonl` — 11 conversation-specific queries

```bash
# Run conversation gold-semantic:
python3 brain/tools/retrieval_eval_kfold.py \
  --gold-semantic brain/eval/gold_semantic_conversations.jsonl \
  --report brain/eval/kfold_gold_semantic_conversations_$(date +%Y_%m_%d).json --ks 1,5,10
```

**Key finding for conversations:** pure vector P@1=1.000 on all 11 queries. K-fold P@1=0.094 for `conversation` type is a metric artifact — titles like "how do I fix CORS?" are semantically similar across many conversations, so k-fold rank-1 is near-random. Use gold-semantic to measure conversation retrieval quality.

### 3. Gold vault-path (requires live brain API)

Hand-curated queries with known Obsidian vault file targets. Tests end-to-end retrieval including API stack.

```bash
# Start brain API first, then:
python3 brain/tools/retrieval_eval.py --gold brain/eval/gold.jsonl --k 10
```

1 query currently in `gold.jsonl`. Add more as new vault paths are indexed.

---

## Results history

Update this table every time you run a canonical eval.

| Date | Eval | Corpus n | Mode | P@1 | P@3 | P@5 | P@10 | MRR | Notes |
|------|------|----------|------|-----|-----|-----|------|-----|-------|
| 2026-04-?? | k-fold | ~2,400 | cosine | 0.640 | — | — | — | 0.700 | Pre-BM25 baseline |
| 2026-05-01 | k-fold | ~2,400 | RRF | 0.807 | — | — | — | 0.859 | After BM25+RRF shipped (+16.5pp P@1) |
| 2026-05-02 | k-fold | 2,271 | RRF | 0.797 | — | 0.908 | 0.934 | 0.849 | Post-reingest tuned |
| 2026-05-21 | k-fold sample | 19,581 | cosine | 0.818 | 0.853 | 0.863 | 0.870 | 0.838 | 8.6x corpus growth |
| 2026-05-21 | k-fold sample | 19,581 | RRF | 0.831 | 0.867 | 0.873 | 0.878 | 0.851 | BM25 adds +1.3pp |
| **2026-05-21** | **k-fold full** | **19,581** | **RRF** | **0.838** | **0.881** | **0.886** | **0.892** | **0.860** | **Canonical baseline — see warning below** |
| 2026-05-21 | gold-semantic | 19,581 | cosine α=0.0 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | Pure vector wins on paraphrase |
| 2026-05-22 | k-fold sample | 18,974 | RRF | 0.846 | 0.887 | 0.897 | 0.904 | 0.868 | Post-backfill: 621 bad patterns + 235 bad solutions deleted; 1671 conversation titles fixed |
| 2026-05-22 | gold-semantic | 18,974 | cosine α=0.0 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | Unchanged — embeddings untouched |
| 2026-05-22 | k-fold full | 19,049 | RRF | 0.835 | 0.879 | 0.886 | 0.894 | 0.860 | Post-retitle: 2,017 conversation memories re-embedded with title-anchored vectors |
| **2026-05-22** | **gold-semantic (conversations)** | **19,043** | **cosine α=0.0** | **1.000** | **1.000** | **1.000** | **1.000** | **1.000** | **11 conversation paraphrase queries — pure vector perfect; k-fold artifact confirmed** |
| 2026-05-25 | eval_suite --all (kfold sample) | 20,076 | RRF | 0.760 | — | 0.823 | 0.835 | 0.789 | Corpus +1k since May 22; conversation kfold P@1=0.228 (was 0.061 May 21 — conversation retitling working) |
| 2026-05-25 | eval_suite --all (quick_gate) | 20,076 | RRF | conversation=0.603, solution=0.987, pattern=1.0, proj_ctx=1.0 | — | — | — | — | All types above threshold |
| **2026-05-25** | **eval_suite --all (mcp_path)** | **20,076** | **API** | **0.429** | — | — | — | **0.572** | **MCP path gap: -0.331 vs direct kfold P@1=0.760. Primary open problem.** |

> ⚠️ **The overall P@1=0.838 is fact-layer dominated and misleading as a progress metric.**
> 14,759 facts (75% of corpus) score P@1=0.957 and pull the overall up.
> Non-fact types — the original episodic memory layer — score a **weighted P@1=0.462** in May 21
> vs **0.797** in May 2. That is a **-33.5pp regression** on the types that existed before the fact layer.
> Partly explained by 8.6x pool growth (harder eval), but the magnitude is too large to dismiss.
> Always report non-fact P@1 alongside overall when tracking progress.

---

## Current state (2026-05-25 — eval_suite --all)

**Corpus:** 20,076 memories. Run ID: `2026-05-25-1854`. All modes: PASS.

**How to run:** `python3 brain/tools/eval_suite.py --all`

### kfold (sample, n=2166)

| Type | n | P@1 | MRR | Status |
|------|---|-----|-----|--------|
| `fact` | 1,476 | 0.959 | 0.977 | Excellent |
| `decision` | 2 | 1.000 | 1.000 | Strong |
| `error_lesson` | 6 | 1.000 | 1.000 | Strong |
| `solution` | 175 | 0.514 | 0.589 | Moderate |
| `pattern` | 7 | 1.000 | 1.000 | Strong |
| `project_context` | 100 | 0.350 | 0.388 | Weak |
| `conversation` | 400 | **0.228** | **0.277** | **Weak (k-fold artifact — see note below)** |

> ⚠️ Conversation k-fold P@1=0.228 is a metric artifact — titles collide. Use gold-semantic for conversations (P@1=1.000). Notable improvement from 0.061 (May 21) — conversation retitling is working.

### kfold by project (sample)

| Project | n | P@1 | Status |
|---------|---|-----|--------|
| cursor | 643 | 0.963 | Excellent |
| src | 183 | 0.956 | Excellent |
| perplexity | 129 | 0.977 | Excellent |
| owelign | 92 | 0.978 | Excellent |
| landingpage | 87 | 0.931 | Excellent |
| frontend | 80 | 0.938 | Excellent |
| sicop | 61 | 0.984 | Excellent |
| AI | 166 | 0.428 | Weak |
| .claude | 166 | **0.217** | **Bad** |
| ppf-contact-solver | 140 | 0.429 | Weak |
| general | 134 | 0.485 | Weak |
| sicop-health | 36 | 0.750 | Good |
| lifehub | 35 | **0.171** | **Bad** |
| farmaplus | 22 | **0.182** | **Bad** |

### quick_gate (sampled, up to 300 per type)

| Type | P@1 | Status |
|------|-----|--------|
| `conversation` | 0.603 | OK |
| `solution` | 0.987 | OK |
| `pattern` | 1.000 | OK |
| `project_context` | 1.000 | OK |

### mcp_path (14 gold-semantic queries via API)

| Metric | Value |
|--------|-------|
| P@1 | 0.429 |
| MRR | 0.572 |
| Gap vs kfold P@1 | **-0.331** |

MCP path is the primary open problem — the API search path underperforms direct embedding by 33pp. Likely cause: API uses different retrieval parameters or routing vs direct k-fold.

---

## May 2 vs May 21 — honest comparison

| Metric | May 2 (n=2,271) | May 21 (n=19,469) | Delta | Honest read |
|--------|-----------------|-------------------|-------|-------------|
| Overall P@1 | 0.797 | 0.838 | +4.1pp | Misleading — fact layer drives this |
| Overall MRR | 0.849 | 0.860 | +1.2pp | Same caveat |
| **Non-fact P@1** | **0.797** | **0.462** | **-33.5pp** | **The real episodic layer signal** |
| **Non-fact MRR** | **0.849** | **0.497** | **-35.2pp** | **Real regression** |

**Per-type deltas (May 2 → May 21):**

| Type | May 2 P@1 | May 21 P@1 | Delta |
|------|-----------|------------|-------|
| `conversation` | 0.692 | 0.061 | -63.1pp |
| `pattern` | 0.931 | 0.664 | -26.7pp |
| `project_context` | 0.654 | 0.496 | -15.8pp |
| `solution` | 0.875 | 0.783 | -9.1pp |
| `fact` | — | 0.957 | NEW |

**Per-project deltas (selected):**

| Project | May 2 P@1 | May 21 P@1 | Delta |
|---------|-----------|------------|-------|
| `lifehub` | 0.658 | 0.195 | -46.3pp |
| `AI` | 0.697 | 0.505 | -19.3pp |
| `.claude` | 0.353 | 0.261 | -9.1pp |
| `ocreamer` | 0.423 | 0.852 | +42.9pp ✓ |
| `sicop` | 0.500 | 0.948 | +44.8pp ✓ |
| `owelign` | 0.551 | 0.926 | +37.4pp ✓ |

**Caveat on all deltas:** pool grew 8.6x so k-fold is harder by nature. Some degradation is expected from competition alone. But -33.5pp non-fact P@1 is too large to explain with pool size only.

---

## Known failure modes

### 1. Conversations (P@1=0.061)
Root cause: conversation titles are too generic to uniquely identify one memory in a 1,638-item pool. Both cosine and RRF score identically — this is not a BM25 problem, it's a title quality problem. Conversations with titles like "Session 2026-04-12" are indistinguishable by title-based k-fold. **May be a k-fold artifact** — if conversations are never searched by title in practice, this metric is misleading.

Action: investigate how conversations are actually queried in production. If title-based search is not the real use case, the k-fold number is noise for this type.

### 2. `.claude` project (P@1=0.261)
1,255 memories with very low retrievability. Similar profile to the pre-fix `ocreamer` project. Likely an ingest/chunking quality issue. Investigate chunking strategy for `.claude` memories.

### 3. `lifehub` project (P@1=0.195)
261 memories, almost none retrievable. Same investigation path as `.claude`.

### 4. `AI` project (P@1=0.505)
1,706 memories, half not retrievable at rank 1. Large volume makes this high priority.

### 5. BM25 hurts semantic queries
Gold-semantic result: pure vector P@1=1.0, any BM25 weight P@1=0.111. Need intent routing: keyword queries use RRF, paraphrase/semantic queries use pure vector. See gbrain's `intent.ts` for reference implementation.

---

## How to run a full eval session

```bash
cd /Users/macm1air/Documents/AI

# 1. Gold-semantic (fast, ~30s)
python3 brain/tools/retrieval_eval_kfold.py \
  --gold-semantic brain/eval/gold_semantic.jsonl \
  --report brain/eval/kfold_gold_semantic_$(date +%Y_%m_%d).json --ks 1,5,10

# 2. Sampled k-fold for quick signal (~2min)
python3 brain/tools/retrieval_eval_kfold.py --sample 1000 --rrf \
  --report brain/eval/kfold_sample1k_rrf_$(date +%Y_%m_%d).json --ks 1,3,5,10

# 3. Full k-fold canonical run (~5min)
python3 brain/tools/retrieval_eval_kfold.py --full --rrf \
  --report brain/eval/kfold_full_rrf_$(date +%Y_%m_%d).json --ks 1,3,5,10

# 4. Compare to previous run
python3 brain/tools/retrieval_compare_reports.py \
  brain/eval/kfold_full_rrf_PREV.json \
  brain/eval/kfold_full_rrf_$(date +%Y_%m_%d).json
```

After running: **update the Results history table above** and save a brain memory with the new numbers.

---

## When to run

- After any ingest pipeline change
- After any embedding model change
- After any retrieval code change (search, RRF weights, BM25 settings)
- After significant corpus growth (>20% more memories)
- Monthly as a health check

---

## Gold file formats

### gold_semantic.jsonl (paraphrase queries)
```json
{"query": "...", "gold_memory_id": "<uuid>", "k": 10, "description": "..."}
```
Queries intentionally use NO vocabulary from the stored memory. Tests pure semantic retrieval.

### gold.jsonl (vault-path queries, requires API)
```json
{"query": "...", "gold_files": ["vault/path/to/file.md"], "k": 10}
```
Tests end-to-end retrieval against Obsidian vault files.

---

## Report files

| File | Description |
|------|-------------|
| `kfold_full_rrf_YYYY_MM_DD.json` | Canonical full-corpus RRF run |
| `kfold_sample1k_rrf_YYYY_MM_DD.json` | Sampled RRF (fast check) |
| `kfold_sample1k_cosine_YYYY_MM_DD.json` | Sampled cosine-only (BM25 delta) |
| `kfold_gold_semantic_YYYY_MM_DD.json` | Gold-semantic alpha sweep |
| `kfold_report_final.json` | Last canonical run before 2026-05-21 (n=2,271) |
| `last_report.json` | Latest vault-path gold run |

---

## Quality gate

Run after any ingest that adds >100 memories:

```bash
python3 brain/tools/ingest_quality_gate.py --sample 300
```

Thresholds: WARN if P@1 < 0.45 for any non-fact type, ERROR if < 0.25.
Exit code 0 = all clear, 1 = warn, 2 = error.
