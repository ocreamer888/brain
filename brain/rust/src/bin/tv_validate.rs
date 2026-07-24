//! Offline validation harness for the turbovec 4-bit VectorIndex.
//!
//! Loads a real Brain SQLite DB, builds the quantized index, and compares its
//! search results against an exact brute-force f32 cosine baseline computed
//! from the same embeddings. Reports recall@10, top-1 agreement, self-retrieval
//! rate, build time, and per-query latency. Exits non-zero if quality or
//! robustness thresholds are not met.
//!
//! Usage: tv_validate <path-to-brain.db> [sample_size]

use std::time::Instant;

use brain::index::VectorIndex;
use brain::store::MetadataStore;

const DIMS: usize = 768;
const K: usize = 10;

// Pass/fail thresholds.
const MIN_RECALL_AT_K: f64 = 0.90; // overlap of quantized top-10 vs exact top-10
const MIN_TOP1_AGREEMENT: f64 = 0.85; // quantized top-1 == exact top-1
const MIN_SELF_RETRIEVAL: f64 = 0.95; // querying a stored vector returns itself top-1

fn cosine(a: &[f32], b: &[f32]) -> f32 {
    let mut dot = 0.0f32;
    let mut na = 0.0f32;
    let mut nb = 0.0f32;
    for i in 0..a.len().min(b.len()) {
        dot += a[i] * b[i];
        na += a[i] * a[i];
        nb += b[i] * b[i];
    }
    if na < 1e-12 || nb < 1e-12 {
        return -1.0;
    }
    dot / (na.sqrt() * nb.sqrt())
}

/// Exact brute-force top-K ids (by descending cosine) over the whole corpus.
fn exact_topk(query: &[f32], ids: &[String], embs: &[Vec<f32>], k: usize) -> Vec<String> {
    let mut scored: Vec<(f32, usize)> = embs
        .iter()
        .enumerate()
        .map(|(i, e)| (cosine(query, e), i))
        .collect();
    scored.sort_by(|a, b| b.0.partial_cmp(&a.0).unwrap_or(std::cmp::Ordering::Equal));
    scored.iter().take(k).map(|&(_, i)| ids[i].clone()).collect()
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    let db_path = args.get(1).cloned().unwrap_or_else(|| {
        eprintln!("usage: tv_validate <path-to-brain.db> [sample_size]");
        std::process::exit(2);
    });
    let sample_size: usize = args.get(2).and_then(|s| s.parse().ok()).unwrap_or(500);

    eprintln!("[tv_validate] opening {db_path}");
    let store = MetadataStore::open(&db_path).expect("open db");
    let pairs = store.get_embeddings_for_index().expect("load embeddings");
    eprintln!("[tv_validate] {} rows from SQLite", pairs.len());

    // Keep only well-formed DIMS-length vectors; report any anomalies.
    let mut ids: Vec<String> = Vec::with_capacity(pairs.len());
    let mut embs: Vec<Vec<f32>> = Vec::with_capacity(pairs.len());
    let mut bad = 0usize;
    for (id, e) in pairs {
        if e.len() == DIMS && e.iter().all(|x| x.is_finite()) {
            ids.push(id);
            embs.push(e);
        } else {
            bad += 1;
        }
    }
    eprintln!(
        "[tv_validate] usable vectors: {} (skipped {} malformed/wrong-dim)",
        ids.len(),
        bad
    );
    let n = ids.len();
    if n == 0 {
        eprintln!("[tv_validate] FAIL: no usable vectors");
        std::process::exit(1);
    }

    // ---- Build the quantized index exactly like brain.rs::open ----
    let t0 = Instant::now();
    let mut index = VectorIndex::new(DIMS);
    let id_refs: Vec<&str> = ids.iter().map(|s| s.as_str()).collect();
    let flat: Vec<f32> = embs.iter().flat_map(|e| e.iter().copied()).collect();
    index.bulk_insert(&id_refs, &flat);
    index.prepare();
    let build_ms = t0.elapsed().as_secs_f64() * 1000.0;
    eprintln!(
        "[tv_validate] index built: len={} in {:.0} ms",
        index.len(),
        build_ms
    );
    if index.len() != n {
        eprintln!(
            "[tv_validate] FAIL: index len {} != usable vectors {}",
            index.len(),
            n
        );
        std::process::exit(1);
    }

    // ---- Deterministic sample across the corpus ----
    let sample = sample_size.min(n);
    let stride = (n / sample).max(1);
    let sample_idx: Vec<usize> = (0..n).step_by(stride).take(sample).collect();

    let mut recall_sum = 0.0f64;
    let mut top1_hits = 0usize;
    let mut self_hits = 0usize;
    let mut exact_self_hits = 0usize;
    let mut empty_results = 0usize;
    let mut latency_ms = 0.0f64;

    for &qi in &sample_idx {
        let query = &embs[qi];
        let self_id = &ids[qi];

        let exact = exact_topk(query, &ids, &embs, K);

        let ts = Instant::now();
        let tv: Vec<String> = index.search(query, K).into_iter().map(|(id, _)| id).collect();
        latency_ms += ts.elapsed().as_secs_f64() * 1000.0;

        if tv.is_empty() {
            empty_results += 1;
            continue;
        }

        let exact_set: std::collections::HashSet<&String> = exact.iter().collect();
        let overlap = tv.iter().filter(|id| exact_set.contains(id)).count();
        recall_sum += overlap as f64 / K as f64;

        if !exact.is_empty() && tv[0] == exact[0] {
            top1_hits += 1;
        }
        if tv[0] == *self_id {
            self_hits += 1;
        }
        if !exact.is_empty() && exact[0] == *self_id {
            exact_self_hits += 1;
        }
    }

    let s = sample_idx.len() as f64;
    let recall = recall_sum / s;
    let top1 = top1_hits as f64 / s;
    let self_rate = self_hits as f64 / s;
    let exact_self_rate = exact_self_hits as f64 / s;
    let avg_latency = latency_ms / s;

    // ---- Robustness checks ----
    // Delete correctness: remove a sampled id, confirm it vanishes from its own
    // top-K, then it stays gone. (Mutates the in-memory index only.)
    let victim = ids[sample_idx[0]].clone();
    let victim_emb = embs[sample_idx[0]].clone();
    index.remove(&victim);
    let after_del: Vec<String> = index
        .search(&victim_emb, K)
        .into_iter()
        .map(|(id, _)| id)
        .collect();
    let delete_ok = !after_del.contains(&victim) && index.len() == n - 1;

    // Empty / zero query robustness (must not panic).
    let zero = vec![0.0f32; DIMS];
    let _ = index.search(&zero, K);

    eprintln!("\n================ TURBOVEC 4-BIT VALIDATION ================");
    eprintln!("corpus vectors        : {n}");
    eprintln!("sample size           : {}", sample_idx.len());
    eprintln!("build time            : {build_ms:.0} ms");
    eprintln!("avg search latency    : {avg_latency:.3} ms/query");
    eprintln!("recall@{K}            : {:.4}  (threshold {MIN_RECALL_AT_K})", recall);
    eprintln!("top-1 agreement (vs exact): {:.4}  (threshold {MIN_TOP1_AGREEMENT})", top1);
    eprintln!("self-retrieval (tv)   : {:.4}  (threshold {MIN_SELF_RETRIEVAL})", self_rate);
    eprintln!("self-retrieval (exact ref): {:.4}", exact_self_rate);
    eprintln!("empty results         : {empty_results}");
    eprintln!("delete correctness    : {}", if delete_ok { "PASS" } else { "FAIL" });
    eprintln!("==========================================================\n");

    let mut failed = false;
    if recall < MIN_RECALL_AT_K {
        eprintln!("FAIL: recall@{K} {recall:.4} < {MIN_RECALL_AT_K}");
        failed = true;
    }
    if top1 < MIN_TOP1_AGREEMENT {
        eprintln!("FAIL: top-1 agreement {top1:.4} < {MIN_TOP1_AGREEMENT}");
        failed = true;
    }
    if self_rate < MIN_SELF_RETRIEVAL {
        eprintln!("FAIL: self-retrieval {self_rate:.4} < {MIN_SELF_RETRIEVAL}");
        failed = true;
    }
    if !delete_ok {
        eprintln!("FAIL: delete correctness");
        failed = true;
    }
    if empty_results > 0 {
        eprintln!("FAIL: {empty_results} queries returned empty results");
        failed = true;
    }

    if failed {
        std::process::exit(1);
    }
    eprintln!("[tv_validate] ALL CHECKS PASSED");
}
