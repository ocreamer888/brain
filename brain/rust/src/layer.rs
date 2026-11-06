//! Temporal-layer confidence (cognitive-architecture-spec.md §8.4), G8.
//!
//! `depth(m)` counts newer memories about the same subject stacked on top of
//! `m`. A memory counts toward `L(m)` through exactly one of two paths,
//! de-duplicated per distinct newer-memory id so a pair is never counted
//! twice if both happen to apply:
//!
//!   - **Explicit supersede**: `m.superseded_by` resolves (via
//!     `store::resolved_supersedes`, which already filters quarantine/hidden
//!     sentinels and dangling pointers) to a real newer memory `m'`.
//!     `w(m,m') = 1.0` -- the spec's literal formula for this case.
//!   - **Judged layer**: a `memory_links` row with `relation_type =
//!     'layers_on'`, `src_memory_id = m'`, `dst_memory_id = m`. These rows are
//!     written offline by a backfill that first filters candidate pairs
//!     through `brain/ingest/layer_judgment.py`'s LLM judgement step --
//!     deterministic tiers alone (file_path / shared entity / similarity)
//!     only reach ~33% precision at deciding "is this actually the same
//!     evolving subject" (docs/architecture/experiments/2026-10-21-layer-detection),
//!     so tier-matched candidates are *not* layers on their own; only
//!     judged-LAYER candidates get written here. `weight` is the pair's
//!     cosine similarity -- the spec's "similarity-based weight otherwise",
//!     where the judgement step's job was gating *membership*, not deriving
//!     the weight itself.
//!
//! When both paths name the same `m'`, the explicit weight (1.0) wins --
//! explicit is more certain than a similarity-gated judgement call.
//!
//! `depth` is a `Result`, not cached on the row: computed fresh at query
//! time (spec §8.3 -- never stored, so old rows stay immutable).
use rusqlite::{params, Connection};

use crate::store::resolved_supersedes;
use crate::BrainError;

pub const LAYERS_ON: &str = "layers_on";

/// Floor for `layer_w`: the maximum confidence penalty a memory can take no
/// matter how deeply buried. Matches the spec's own worked example (§8.4).
pub const DEFAULT_FLOOR: f64 = 0.85;

/// Decay rate. Chosen as a half-life, not fit to any one dataset: each unit
/// of depth closes half the remaining distance to `DEFAULT_FLOOR`, so a
/// single explicit supersede (depth=1, w=1.0) already produces a clearly
/// felt, but not drastic, confidence drop -- `layer_w(1) = F + (1-F)*0.5`.
/// This is the one parameter the spec explicitly leaves for §8.7 tuning;
/// 0.5 is a principled default, not a result of fitting the 61-pair sample
/// in docs/architecture/experiments/2026-11-06-layer-judgment-gate/.
pub const DEFAULT_LAMBDA: f64 = 0.5;

/// `layer_w(m) = F + (1-F)*lambda^depth`, spec §8.4. Bounded in `[F, 1]`:
/// `depth=0` gives exactly `1.0` (top of stack, no penalty); as `depth`
/// grows, `lambda^depth -> 0` so `layer_w -> F`. Requires `0 < lambda < 1`
/// and `0 <= floor <= 1` and `depth >= 0` to stay in range -- callers control
/// all three, so this does not validate them, it is a pure formula.
pub fn layer_w(depth: f64, floor: f64, lambda: f64) -> f64 {
    floor + (1.0 - floor) * lambda.powf(depth)
}

/// `c(m) = 1 + 9*lambda^depth`, spec §8.4 -- the 1-10 display scale from the
/// owner's sketch. `depth=0` gives exactly `10.0`; as `depth` grows this
/// tends to `1.0`. Display only; ranking uses `layer_w`.
pub fn confidence_scale(depth: f64, lambda: f64) -> f64 {
    1.0 + 9.0 * lambda.powf(depth)
}

/// `depth(m) = sum of w(m, m')` over every newer memory on the same subject,
/// de-duplicated per `m'` (see module docs). `memory_id` must be the OLDER
/// side (`m`, the `dst_memory_id` of any `layers_on` row).
pub fn depth(
    conn: &Connection,
    memory_id: &str,
    superseded_by: Option<&str>,
) -> Result<f64, BrainError> {
    let mut weight_by_newer: std::collections::HashMap<String, f64> =
        std::collections::HashMap::new();

    if let Some(explicit_newer) = resolved_supersedes(conn, superseded_by)? {
        weight_by_newer.insert(explicit_newer, 1.0);
    }

    let mut stmt = conn
        .prepare(
            "SELECT src_memory_id, weight FROM memory_links \
             WHERE dst_memory_id = ?1 AND relation_type = ?2",
        )
        .map_err(|e| BrainError::Database(e.to_string()))?;
    let rows = stmt
        .query_map(params![memory_id, LAYERS_ON], |row| {
            Ok((row.get::<_, String>(0)?, row.get::<_, f64>(1)?))
        })
        .map_err(|e| BrainError::Database(e.to_string()))?;
    for row in rows {
        let (newer_id, weight) = row.map_err(|e| BrainError::Database(e.to_string()))?;
        weight_by_newer.entry(newer_id).or_insert(weight);
    }

    Ok(weight_by_newer.values().sum())
}

/// Record a judged layer link (`m'` layers on `m`). Called by the offline
/// backfill (Python, after `layer_judgment.classify_pair` returns LAYER),
/// never at query time. `weight` should be the pair's cosine similarity
/// (see module docs); `id` the caller's own UUID so re-running a backfill is
/// idempotent via the UNIQUE(src,dst,relation_type) constraint.
pub fn insert_layer_link(
    conn: &Connection,
    id: &str,
    newer_memory_id: &str,
    older_memory_id: &str,
    weight: f64,
) -> Result<(), BrainError> {
    let now = chrono::Utc::now().to_rfc3339();
    conn.execute(
        "INSERT INTO memory_links (id, src_memory_id, dst_memory_id, relation_type, weight, created_at) \
         VALUES (?1, ?2, ?3, ?4, ?5, ?6) \
         ON CONFLICT(src_memory_id, dst_memory_id, relation_type) DO NOTHING",
        params![id, newer_memory_id, older_memory_id, LAYERS_ON, weight, now],
    )
    .map_err(|e| BrainError::Database(e.to_string()))?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::store::MetadataStore;

    const EPS: f64 = 1e-9;

    #[test]
    fn layer_w_at_depth_zero_is_exactly_one() {
        for floor in [0.0, 0.5, 0.85, 0.99] {
            for lambda in [0.01, 0.3, 0.5, 0.9, 0.99] {
                assert!((layer_w(0.0, floor, lambda) - 1.0).abs() < EPS);
            }
        }
    }

    #[test]
    fn confidence_at_depth_zero_is_exactly_ten() {
        for lambda in [0.01, 0.3, 0.5, 0.9, 0.99] {
            assert!((confidence_scale(0.0, lambda) - 10.0).abs() < EPS);
        }
    }

    #[test]
    fn layer_w_is_monotonically_non_increasing_in_depth() {
        let (floor, lambda) = (DEFAULT_FLOOR, DEFAULT_LAMBDA);
        let depths: Vec<f64> = (0..200).map(|i| i as f64 * 0.1).collect();
        for pair in depths.windows(2) {
            let (d0, d1) = (pair[0], pair[1]);
            assert!(
                layer_w(d1, floor, lambda) <= layer_w(d0, floor, lambda) + EPS,
                "layer_w should not increase as depth grows: d0={d0} d1={d1}"
            );
        }
    }

    #[test]
    fn layer_w_is_bounded_in_floor_one() {
        let (floor, lambda) = (DEFAULT_FLOOR, DEFAULT_LAMBDA);
        for depth_tenths in 0..500 {
            let depth = depth_tenths as f64 * 0.1;
            let w = layer_w(depth, floor, lambda);
            assert!(w <= 1.0 + EPS && w >= floor - EPS, "depth={depth} w={w}");
        }
    }

    #[test]
    fn layer_w_approaches_floor_as_depth_grows() {
        let (floor, lambda) = (DEFAULT_FLOOR, DEFAULT_LAMBDA);
        assert!((layer_w(100.0, floor, lambda) - floor).abs() < 1e-6);
        assert!((confidence_scale(100.0, lambda) - 1.0).abs() < 1e-6);
    }

    /// Dominance invariant (spec §2.1): the combined modulator band must stay
    /// at least as tight as today's salience_w-based band (~1.94x, proven in
    /// the spec from salience_w in [0.85,1.15], recency_w in [0.85,1.0],
    /// knowledge_w in [1.0,1.22]). Replacing salience_w with layer_w in
    /// [DEFAULT_FLOOR, 1.0] can only shrink that band, since layer_w's upper
    /// bound (1.0) is lower than salience_w's (1.15) while the floor is
    /// identical (0.85) -- this test proves the arithmetic, not just asserts
    /// the conclusion.
    #[test]
    fn layer_w_tightens_the_dominance_band_vs_salience_w() {
        let recency_w_range = (0.85_f64, 1.0_f64);
        let knowledge_w_range = (1.0_f64, 1.22_f64);
        let salience_w_range = (0.85_f64, 1.15_f64);
        let layer_w_range = (DEFAULT_FLOOR, 1.0_f64);

        let salience_ratio = (salience_w_range.1 * recency_w_range.1 * knowledge_w_range.1)
            / (salience_w_range.0 * recency_w_range.0 * knowledge_w_range.0);
        let layer_ratio = (layer_w_range.1 * recency_w_range.1 * knowledge_w_range.1)
            / (layer_w_range.0 * recency_w_range.0 * knowledge_w_range.0);

        assert!((salience_ratio - 1.9415_f64).abs() < 1e-3, "sanity: {salience_ratio}");
        assert!(
            layer_ratio < salience_ratio,
            "layer_w band ({layer_ratio}) should be tighter than salience_w's ({salience_ratio})"
        );
        assert!((layer_ratio - 1.6879_f64).abs() < 1e-3, "sanity: {layer_ratio}");
    }

    #[test]
    fn depth_is_zero_with_no_links_and_no_supersede() {
        let store = MetadataStore::open_in_memory().unwrap();
        assert_eq!(depth(store.conn(), "m1", None).unwrap(), 0.0);
    }

    #[test]
    fn depth_counts_explicit_supersede_as_weight_one() {
        let store = MetadataStore::open_in_memory().unwrap();
        let conn = store.conn();
        conn.execute_batch(
            "INSERT INTO memories (id, content, type, project, tags, timestamp, source, session_id, importance) \
             VALUES ('newer', 'x', '\"fact\"', 'p', '[]', '2026-01-01T00:00:00Z', '\"claude_code_session\"', 's', 0.5)",
        )
        .unwrap();
        let d = depth(conn, "older", Some("newer")).unwrap();
        assert!((d - 1.0).abs() < EPS);
    }

    #[test]
    fn depth_sums_judged_layer_links_and_dedupes_against_explicit() {
        let store = MetadataStore::open_in_memory().unwrap();
        let conn = store.conn();
        conn.execute_batch(
            "INSERT INTO memories (id, content, type, project, tags, timestamp, source, session_id, importance) \
             VALUES ('newer_explicit', 'x', '\"fact\"', 'p', '[]', '2026-01-01T00:00:00Z', '\"claude_code_session\"', 's', 0.5)",
        )
        .unwrap();
        insert_layer_link(conn, "l1", "newer_explicit", "older", 0.80).unwrap();
        insert_layer_link(conn, "l2", "newer_other", "older", 0.65).unwrap();

        let d = depth(conn, "older", Some("newer_explicit")).unwrap();
        // newer_explicit: explicit wins (1.0), not the 0.80 link weight.
        // newer_other: judged-layer weight 0.65. Total = 1.65, not 1.0+0.80+0.65.
        assert!((d - 1.65).abs() < EPS, "depth was {d}");
    }

    #[test]
    fn insert_layer_link_is_idempotent() {
        let store = MetadataStore::open_in_memory().unwrap();
        let conn = store.conn();
        insert_layer_link(conn, "l1", "a", "b", 0.7).unwrap();
        insert_layer_link(conn, "l1-retry", "a", "b", 0.7).unwrap();
        let d = depth(conn, "b", None).unwrap();
        assert!((d - 0.7).abs() < EPS, "re-running the backfill must not double-count: {d}");
    }
}
