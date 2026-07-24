use std::collections::HashMap;

use turbovec::IdMapIndex;

/// turbovec bit width. 4-bit = 8× compression vs f32 with negligible
/// inner-product distortion at d=768 (D_prod ≤ 0.0000585 per unit vector).
/// Chosen over 3-bit: 4-bit is turbovec's shared, battle-tested `repack()`
/// path; 3-bit uses a separate, more complex `repack_3bit()` to save only
/// 1.7 MB — irrelevant at Brain's scale.
const BIT_WIDTH: usize = 4;

/// Quantized cosine-similarity vector index.
///
/// Wraps turbovec's [`IdMapIndex`] (TurboQuant 3-bit SIMD search). Brain
/// embeddings are L2-normalized by the embedder, so turbovec's inner-product
/// score equals cosine similarity, and we expose `distance = 1 - score` to
/// keep the exact contract the old brute-force index had (ascending distance,
/// closer = smaller).
///
/// turbovec addresses vectors by `u64` ids; Brain uses UUID strings. A pair of
/// side tables bridges them. turbovec owns the id↔slot mapping and swap-remove
/// internally, so this wrapper only tracks `uuid ↔ u64`.
pub struct VectorIndex {
    dims: usize,
    inner: IdMapIndex,
    uuid_to_id: HashMap<String, u64>,
    id_to_uuid: HashMap<u64, String>,
    /// Monotonic external-id counter. Never reused — removal frees the id in
    /// turbovec but we keep incrementing, so collisions are impossible.
    next_id: u64,
}

impl VectorIndex {
    pub fn new(dims: usize) -> Self {
        let inner = IdMapIndex::new(dims, BIT_WIDTH)
            .expect("embedding dims must be a positive multiple of 8");
        Self {
            dims,
            inner,
            uuid_to_id: HashMap::new(),
            id_to_uuid: HashMap::new(),
            next_id: 0,
        }
    }

    pub fn len(&self) -> usize {
        self.inner.len()
    }

    pub fn is_empty(&self) -> bool {
        self.inner.is_empty()
    }

    /// Pad/truncate an embedding to exactly `dims` so turbovec never sees a
    /// dim mismatch. Embedder output is already `dims` long; this is defensive.
    fn fit_dims(&self, embedding: &[f32]) -> Vec<f32> {
        let mut v = embedding[..embedding.len().min(self.dims)].to_vec();
        v.resize(self.dims, 0.0);
        v
    }

    /// Bulk-load all existing embeddings in one call at startup. A single
    /// `add_with_ids_2d` lets TQ+ calibration see the whole corpus at once
    /// (per-vector inserts would freeze calibration on the first vector).
    ///
    /// `flat_embeddings` must be `ids.len() * dims` long (row-major, each row a
    /// `dims`-length embedding). A length mismatch is logged and skipped rather
    /// than panicking — the corpus is then served by BM25 until a rebuild.
    pub fn bulk_insert(&mut self, ids: &[&str], flat_embeddings: &[f32]) {
        if ids.is_empty() {
            return;
        }
        let expected = ids.len() * self.dims;
        if flat_embeddings.len() != expected {
            eprintln!(
                "[brain] bulk_insert skipped: flat len {} != ids {} * dims {}",
                flat_embeddings.len(),
                ids.len(),
                self.dims
            );
            return;
        }
        let slot_ids: Vec<u64> = (0..ids.len() as u64).map(|i| self.next_id + i).collect();
        match self.inner.add_with_ids_2d(flat_embeddings, self.dims, &slot_ids) {
            Ok(()) => {
                for (uuid, &slot_id) in ids.iter().zip(slot_ids.iter()) {
                    self.uuid_to_id.insert(uuid.to_string(), slot_id);
                    self.id_to_uuid.insert(slot_id, uuid.to_string());
                }
                self.next_id += ids.len() as u64;
            }
            Err(e) => eprintln!("[brain] bulk_insert failed: {e}"),
        }
    }

    /// Insert or replace a single embedding (used for live saves after startup).
    ///
    /// Re-inserting an existing UUID removes the old entry first so no ghost
    /// vector lingers. Each insert invalidates turbovec's SIMD cache, repacked
    /// lazily on the next search (~2-5ms) — acceptable since saves are rare.
    pub fn insert(&mut self, id: &str, embedding: &[f32]) {
        if self.uuid_to_id.contains_key(id) {
            self.remove(id);
        }
        let v = self.fit_dims(embedding);
        let slot_id = self.next_id;
        match self.inner.add_with_ids_2d(&v, self.dims, &[slot_id]) {
            Ok(()) => {
                self.next_id += 1;
                self.uuid_to_id.insert(id.to_string(), slot_id);
                self.id_to_uuid.insert(slot_id, id.to_string());
            }
            Err(e) => eprintln!("[brain] index insert failed for {id}: {e}"),
        }
    }

    /// Remove an embedding by UUID. turbovec performs the internal swap-remove
    /// and keeps its own id↔slot tables consistent; we only drop our side maps.
    pub fn remove(&mut self, id: &str) {
        let Some(slot_id) = self.uuid_to_id.remove(id) else {
            return;
        };
        self.id_to_uuid.remove(&slot_id);
        self.inner.remove(slot_id);
    }

    /// Return top-n results as `(id, distance)` ordered by ascending distance
    /// (closer = smaller). `distance = 1 - cosine_similarity`.
    pub fn search(&self, query: &[f32], n: usize) -> Vec<(String, f32)> {
        if self.inner.is_empty() || n == 0 {
            return Vec::new();
        }
        let q = self.fit_dims(query);
        let (scores, ids) = self.inner.search(&q, n);
        scores
            .iter()
            .zip(ids.iter())
            .filter_map(|(&score, &slot_id)| {
                self.id_to_uuid
                    .get(&slot_id)
                    .map(|uuid| (uuid.clone(), 1.0 - score))
            })
            .collect()
    }

    /// Eagerly build turbovec's SIMD caches (rotation matrix, centroids,
    /// blocked code layout) so the first search after startup doesn't pay it.
    pub fn prepare(&self) {
        self.inner.prepare();
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    // turbovec requires dims to be a positive multiple of 8.
    const D: usize = 8;

    fn vec_at(coords: &[(usize, f32)]) -> Vec<f32> {
        let mut v = vec![0.0f32; D];
        for &(i, x) in coords {
            v[i] = x;
        }
        v
    }

    #[test]
    fn new_index_is_empty() {
        let idx = VectorIndex::new(D);
        assert_eq!(idx.len(), 0);
        assert!(idx.is_empty());
    }

    #[test]
    fn insert_and_search() {
        let mut idx = VectorIndex::new(D);
        idx.insert("a", &vec_at(&[(0, 1.0)]));
        idx.insert("b", &vec_at(&[(1, 1.0)]));
        idx.insert("c", &vec_at(&[(0, 0.7), (1, 0.7)]));
        let results = idx.search(&vec_at(&[(0, 1.0)]), 2);
        assert_eq!(results.len(), 2);
        assert_eq!(results[0].0, "a"); // exact direction match ranks first
    }

    #[test]
    fn search_returns_at_most_n() {
        let mut idx = VectorIndex::new(D);
        for i in 0..10 {
            idx.insert(&format!("v-{i}"), &vec_at(&[(0, 1.0), (1, i as f32)]));
        }
        let results = idx.search(&vec_at(&[(0, 1.0)]), 3);
        assert_eq!(results.len(), 3);
    }

    #[test]
    fn remove_excludes_from_search() {
        let mut idx = VectorIndex::new(D);
        idx.insert("a", &vec_at(&[(0, 1.0)]));
        idx.insert("b", &vec_at(&[(0, 0.9), (1, 0.1)]));
        idx.remove("a");
        assert_eq!(idx.len(), 1);
        let results = idx.search(&vec_at(&[(0, 1.0)]), 5);
        assert_eq!(results.len(), 1);
        assert_eq!(results[0].0, "b");
    }

    #[test]
    fn search_on_empty_index_returns_empty() {
        let idx = VectorIndex::new(D);
        assert!(idx.search(&vec_at(&[(0, 1.0)]), 5).is_empty());
    }

    #[test]
    fn bulk_insert_then_search() {
        let mut idx = VectorIndex::new(D);
        let a = vec_at(&[(0, 1.0)]);
        let b = vec_at(&[(1, 1.0)]);
        let c = vec_at(&[(2, 1.0)]);
        let flat: Vec<f32> = a.iter().chain(&b).chain(&c).copied().collect();
        idx.bulk_insert(&["a", "b", "c"], &flat);
        assert_eq!(idx.len(), 3);
        let results = idx.search(&a, 1);
        assert_eq!(results[0].0, "a");
    }

    #[test]
    fn remove_middle_after_bulk_keeps_others_searchable() {
        // Exercises turbovec's swap-remove: removing a non-last slot moves the
        // last vector into its place. The wrapper must still resolve both
        // remaining ids correctly.
        let mut idx = VectorIndex::new(D);
        let a = vec_at(&[(0, 1.0)]);
        let b = vec_at(&[(1, 1.0)]);
        let c = vec_at(&[(2, 1.0)]);
        let flat: Vec<f32> = a.iter().chain(&b).chain(&c).copied().collect();
        idx.bulk_insert(&["a", "b", "c"], &flat);
        idx.remove("b"); // middle slot
        assert_eq!(idx.len(), 2);
        assert_eq!(idx.search(&a, 1)[0].0, "a");
        assert_eq!(idx.search(&c, 1)[0].0, "c");
    }

    #[test]
    fn insert_replaces_existing_uuid() {
        let mut idx = VectorIndex::new(D);
        idx.insert("a", &vec_at(&[(0, 1.0)]));
        idx.insert("a", &vec_at(&[(1, 1.0)])); // replace, not duplicate
        assert_eq!(idx.len(), 1);
        let results = idx.search(&vec_at(&[(1, 1.0)]), 5);
        assert_eq!(results.len(), 1);
        assert_eq!(results[0].0, "a");
    }
}
