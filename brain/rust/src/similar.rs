//! Associative similarity layer (cognitive-architecture-spec.md §7), G7.
//!
//! For each memory, its nearest neighbors by embedding distance, stored as
//! `memory_links(relation_type='similar_to')` rows -- weight = 1 - cosine
//! distance, the spec's literal §7.2 formula. Read-only consumption only
//! (§7.3: dedup, atlas layout, "related memories" browsing). NOT wired into
//! `/search` ranking or `graph_expand` by default -- G4's standing rule
//! requires a gold-set A/B before any new edge type touches ranking, and
//! the entity-based `graph_expand` precedent already measurably hurt
//! retrieval once (spec §7.4). Building that A/B is out of scope here.
//!
//! Storage reuses the `memory_links` table built for G8's `layers_on`
//! relation (`brain/rust/src/layer.rs`) rather than a new table -- same
//! shape, different `relation_type`, by design (see that module's and
//! `store.rs`'s `memory_links` doc comments: room was deliberately left
//! for this).

use rusqlite::{params, Connection};

use crate::index::VectorIndex;
use crate::BrainError;

pub const SIMILAR_TO: &str = "similar_to";

/// Find `memory_id`'s top-`k` nearest *other* memories via the existing
/// vector index. Over-fetches by one so dropping a self-match (a memory's
/// own embedding is its own nearest neighbor at distance ~0) still leaves
/// `k` results. Returns `(neighbor_id, weight)`, `weight = 1 - distance`
/// per spec §7.2 -- `VectorIndex::search` already returns `distance`, so
/// this is the one place that inverts it back to a similarity weight.
pub fn find_similar(
    index: &VectorIndex,
    memory_id: &str,
    embedding: &[f32],
    k: usize,
) -> Vec<(String, f64)> {
    index
        .search(embedding, k + 1)
        .into_iter()
        .filter(|(id, _)| id != memory_id)
        .take(k)
        .map(|(id, distance)| (id, (1.0 - distance) as f64))
        .collect()
}

/// Record a `similar_to` link: `memory_id` -> `neighbor_id`, found from
/// `memory_id`'s own nearest-neighbor query. Idempotent via the same
/// `UNIQUE(src,dst,relation_type)` constraint `layers_on` uses (see
/// `layer::insert_layer_link`) -- re-running a backfill never double-counts.
pub fn insert_similar_link(
    conn: &Connection,
    id: &str,
    memory_id: &str,
    neighbor_id: &str,
    weight: f64,
) -> Result<(), BrainError> {
    let now = chrono::Utc::now().to_rfc3339();
    conn.execute(
        "INSERT INTO memory_links (id, src_memory_id, dst_memory_id, relation_type, weight, created_at) \
         VALUES (?1, ?2, ?3, ?4, ?5, ?6) \
         ON CONFLICT(src_memory_id, dst_memory_id, relation_type) DO NOTHING",
        params![id, memory_id, neighbor_id, SIMILAR_TO, weight, now],
    )
    .map_err(|e| BrainError::Database(e.to_string()))?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::store::MetadataStore;

    const EPS: f64 = 1e-6;

    fn idx_with(pairs: &[(&str, [f32; 8])]) -> VectorIndex {
        let mut idx = VectorIndex::new(8);
        for (id, v) in pairs {
            idx.insert(id, v);
        }
        idx
    }

    #[test]
    fn find_similar_excludes_self_and_orders_by_closeness() {
        let idx = idx_with(&[
            ("a", [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]),
            ("b", [0.99, 0.01, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]), // very close to a
            ("c", [0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]),   // orthogonal to a
        ]);
        let results = find_similar(&idx, "a", &[1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0], 2);
        assert_eq!(results.len(), 2);
        assert_eq!(results[0].0, "b", "closest neighbor must come first");
        assert!(results[0].1 > results[1].1, "closer neighbor must have higher weight");
        assert!(results.iter().all(|(id, _)| id != "a"), "must never return itself");
    }

    #[test]
    fn find_similar_caps_at_k_even_with_more_candidates() {
        let idx = idx_with(&[
            ("a", [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]),
            ("b", [0.9, 0.1, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]),
            ("c", [0.8, 0.2, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]),
            ("d", [0.7, 0.3, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]),
        ]);
        let results = find_similar(&idx, "a", &[1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0], 2);
        assert_eq!(results.len(), 2);
    }

    #[test]
    fn insert_similar_link_is_idempotent_and_weight_matches_formula() {
        let store = MetadataStore::open_in_memory().unwrap();
        let conn = store.conn();
        insert_similar_link(conn, "s1", "a", "b", 0.8).unwrap();
        insert_similar_link(conn, "s1-retry", "a", "b", 0.8).unwrap();
        let count: i64 = conn
            .query_row(
                "SELECT COUNT(*) FROM memory_links WHERE relation_type = ?1",
                params![SIMILAR_TO],
                |r| r.get(0),
            )
            .unwrap();
        assert_eq!(count, 1, "re-running must not double-insert");
        let weight: f64 = conn
            .query_row(
                "SELECT weight FROM memory_links WHERE relation_type = ?1",
                params![SIMILAR_TO],
                |r| r.get(0),
            )
            .unwrap();
        assert!((weight - 0.8).abs() < EPS);
    }

    #[test]
    fn similar_to_and_layers_on_coexist_without_conflict() {
        // The whole point of reusing memory_links: two different relation
        // types between the same two ids must not collide on the
        // UNIQUE(src,dst,relation_type) constraint.
        let store = MetadataStore::open_in_memory().unwrap();
        let conn = store.conn();
        crate::layer::insert_layer_link(conn, "l1", "a", "b", 0.9).unwrap();
        insert_similar_link(conn, "s1", "a", "b", 0.9).unwrap();
        let count: i64 = conn
            .query_row("SELECT COUNT(*) FROM memory_links", [], |r| r.get(0))
            .unwrap();
        assert_eq!(count, 2, "different relation_type must not collide");
    }
}
