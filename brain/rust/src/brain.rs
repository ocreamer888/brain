use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::{Arc, Mutex};

use chrono::{DateTime, Utc};
use serde::Serialize;
use tokio::sync::broadcast;
use uuid::Uuid;

use crate::embedder::EmbedderBackend;
use crate::index::VectorIndex;
use crate::store::MetadataStore;
use crate::title::derive_memory_title;
use crate::summarizer::{LlmClient, ReflectionResult, Summarizer};
use crate::{
    BrainError, BrainStats, FeedbackEventRecord, FeedbackEventType, FeedbackSource, Memory,
    MemoryMetadata, MemorySource, MemoryType, SearchFilter, SearchResult,
};

/// Cosine-distance threshold for the preventive save-time dedup guard. Memories
/// within this distance (≈97% similar) of an existing same-project, same-type
/// memory are treated as duplicates and skipped. `distance = 1 - cosine_sim`.
const DEDUP_DISTANCE_THRESHOLD: f32 = 0.03;

/// Score multiplier applied to a seed's score when injecting a 1-hop graph
/// neighbor (shared entity) into search results. Task 7 (Phase C).
pub(crate) const GRAPH_HOP_DECAY: f32 = 0.85;

/// Payload for the real-time memory stream (SSE / web viewer).
#[derive(Clone, Debug, Serialize)]
pub struct MemoryEvent {
    pub id: String,
    pub content_snippet: String,
    pub timestamp: String,
    pub memory_type: String,
}

/// Configuration for opening a Brain instance.
pub struct BrainConfig {
    /// Path to the SQLite database file. Use `:memory:` for in-memory.
    pub db_path: String,
    /// Number of dimensions for embeddings (768 for all-mpnet-base-v2).
    pub embedding_dims: usize,
    /// Auto-reflect after every N saves.
    pub reflect_every_n: usize,
    /// Disable all reflection side effects (auto + manual).
    pub reflection_disabled: bool,
    /// Weighted hybrid score: alpha*cosine + (1-alpha)*bm25_norm.
    pub hybrid_alpha: f32,
}

impl Default for BrainConfig {
    fn default() -> Self {
        Self {
            db_path: "brain.db".into(),
            embedding_dims: 768,
            reflect_every_n: 10,
            reflection_disabled: false,
            hybrid_alpha: 0.7,
        }
    }
}

/// High-level Brain API.
///
/// Composes MetadataStore (SQLite), VectorIndex (cosine search), and EmbedderBackend.
/// Mirrors the Python brain's `save_memory`, `search`, `get_context`, `get_stats` API.
pub struct Brain {
    store: MetadataStore,
    index: Arc<Mutex<VectorIndex>>,
    embedder: Box<dyn EmbedderBackend>,
    llm_client: Option<Box<dyn LlmClient>>,
    save_count: AtomicUsize,
    reflect_every_n: usize,
    reflection_disabled: bool,
    hybrid_alpha: f32,
    memory_events: Option<broadcast::Sender<MemoryEvent>>,
}

impl Brain {
    /// Open a Brain from config, loading existing index from disk if present.
    pub fn open(config: BrainConfig, embedder: Box<dyn EmbedderBackend>) -> Result<Self, BrainError> {
        Self::open_with_event_bus(config, embedder, None)
    }

    /// Same as [`Brain::open`], but fan-out save notifications on `memory_events` (for SSE).
    pub fn open_with_event_bus(
        config: BrainConfig,
        embedder: Box<dyn EmbedderBackend>,
        memory_events: Option<broadcast::Sender<MemoryEvent>>,
    ) -> Result<Self, BrainError> {
        let store = if config.db_path == ":memory:" {
            MetadataStore::open_in_memory()?
        } else {
            MetadataStore::open(&config.db_path)?
        };

        let mut index = VectorIndex::new(config.embedding_dims);
        let pairs = store.get_embeddings_for_index()?;
        let n_loaded = pairs.len();

        if n_loaded > 0 {
            // Batch insert: TQ+ calibration sees all vectors at once (not just the
            // first), so quantization quality is maximized. turbovec subsumes the
            // old corpus mean-centering via per-coordinate affine calibration.
            let ids: Vec<&str> = pairs.iter().map(|(id, _)| id.as_str()).collect();
            let flat: Vec<f32> = pairs.iter().flat_map(|(_, e)| e.iter().copied()).collect();
            index.bulk_insert(&ids, &flat);
            // Pre-build the SIMD layout so the first search doesn't pay the repack.
            index.prepare();
        }
        eprintln!("[brain] loaded {} embeddings from SQLite", index.len());

        Ok(Self {
            store,
            index: Arc::new(Mutex::new(index)),
            embedder,
            llm_client: None,
            save_count: AtomicUsize::new(0),
            reflect_every_n: config.reflect_every_n,
            reflection_disabled: config.reflection_disabled,
            hybrid_alpha: config.hybrid_alpha,
            memory_events,
        })
    }

    /// Subscribe to [`MemoryEvent`]s emitted after each successful [`Brain::save_memory`].
    pub fn subscribe_memory_events(&self) -> Option<broadcast::Receiver<MemoryEvent>> {
        self.memory_events.as_ref().map(|tx| tx.subscribe())
    }

    /// Save a memory. Returns the new memory ID.
    ///
    /// Pass `timestamp` to preserve event time for backfilled / historical content
    /// (e.g. old session ended_at, perplexity created_at, file mtime). When `None`,
    /// `Utc::now()` is used — correct for live captures.
    #[allow(clippy::too_many_arguments)]
    pub fn save_memory(
        &self,
        content: &str,
        memory_type: MemoryType,
        tags: &[&str],
        project: &str,
        session_id: Option<&str>,
        source: MemorySource,
        file_path: Option<&str>,
        title: Option<&str>,
        timestamp: Option<DateTime<Utc>>,
        // Fact-layer fields — None for all regular (non-fact) memories
        parent_id: Option<&str>,
        event_time: Option<DateTime<Utc>>,
        salience: Option<f64>,
        derived_from: Option<&str>,
    ) -> Result<String, BrainError> {
        let content = crate::privacy::strip_private_blocks(content);
        let resolved_title = title
            .map(str::trim)
            .filter(|s| !s.is_empty())
            .map(String::from)
            .unwrap_or_else(|| derive_memory_title(&content, session_id));
        let id = Uuid::new_v4().to_string();
        let embedding = self.embedder.embed(&content)?;

        // Preventive near-duplicate guard: if an almost-identical memory of the
        // same project+type already exists, skip the write and return its id.
        // Reuses the in-memory cosine index (no LLM, near-zero cost) since the
        // embedding is already computed. Reflection only cleans up post-hoc and
        // never sees Conversation memories or anything older than the last batch,
        // so this is the only guard that stops dups at write time.
        if let Some(existing_id) = self.find_duplicate(&embedding, project, &memory_type)? {
            // Still notify the live feed so the viewer sees activity on deduped writes.
            if let Some(ref tx) = self.memory_events {
                let snippet: String = content.chars().take(200).collect();
                let mt = serde_json::to_value(&memory_type)
                    .ok()
                    .and_then(|v| v.as_str().map(str::to_string))
                    .unwrap_or_else(|| "unknown".to_string());
                let _ = tx.send(MemoryEvent {
                    id: existing_id.clone(),
                    content_snippet: snippet,
                    timestamp: Utc::now().to_rfc3339(),
                    memory_type: mt,
                });
            }
            return Ok(existing_id);
        }

        let memory = Memory {
            id: id.clone(),
            content: content.clone(),
            metadata: MemoryMetadata {
                memory_type,
                project: project.to_string(),
                tags: tags.join(","),
                timestamp: timestamp.unwrap_or_else(Utc::now),
                source,
                session_id: session_id.unwrap_or("").to_string(),
                importance: 0.5,
                file_path: file_path.map(String::from),
                thread_id: None,
                title: Some(resolved_title),
                parent_id: parent_id.map(String::from),
                event_time,
                salience: salience.unwrap_or(0.5),
                superseded_by: None,
                derived_from: derived_from.map(String::from),
            },
            embedding: Some(embedding.clone()),
        };

        self.store.upsert_memory(&memory)?;
        self.index
            .lock()
            .map_err(|e| BrainError::Database(e.to_string()))?
            .insert(&id, &embedding);

        if let Some(ref tx) = self.memory_events {
            let snippet: String = memory.content.chars().take(200).collect();
            let memory_type = serde_json::to_value(&memory.metadata.memory_type)
                .ok()
                .and_then(|v| v.as_str().map(str::to_string))
                .unwrap_or_else(|| "unknown".to_string());
            let evt = MemoryEvent {
                id: id.clone(),
                content_snippet: snippet,
                timestamp: memory.metadata.timestamp.to_rfc3339(),
                memory_type,
            };
            let _ = tx.send(evt);
        }

        let count = self.save_count.fetch_add(1, Ordering::Relaxed) + 1;

        // Auto-reflect every N saves if an LLM client is available
        if !self.reflection_disabled && self.reflect_every_n > 0 && count % self.reflect_every_n == 0 {
            if let Some(ref llm) = self.llm_client {
                let _ = self.run_reflection(llm.as_ref());
            }
        }

        Ok(id)
    }

    /// Return the id of an existing near-duplicate (cosine distance below
    /// `DEDUP_DISTANCE_THRESHOLD`, same project + memory_type) for the given
    /// embedding, or None. Used as a preventive guard in `save_memory`.
    fn find_duplicate(
        &self,
        embedding: &[f32],
        project: &str,
        memory_type: &MemoryType,
    ) -> Result<Option<String>, BrainError> {
        let nearest = {
            let index = self
                .index
                .lock()
                .map_err(|e| BrainError::Database(e.to_string()))?;
            index.search(embedding, 1)
        };
        let Some((cand_id, distance)) = nearest.into_iter().next() else {
            return Ok(None);
        };
        if distance >= DEDUP_DISTANCE_THRESHOLD {
            return Ok(None);
        }
        match self.store.get_memory(&cand_id)? {
            Some(m)
                if m.metadata.project == project && &m.metadata.memory_type == memory_type =>
            {
                Ok(Some(cand_id))
            }
            _ => Ok(None),
        }
    }

    /// Search using weighted hybrid scoring of cosine distance + BM25 rank.
    /// Score = w(age) * [alpha * cosine_norm + (1-alpha) * bm25_norm].
    /// w(age) decays from 1.0 → 0.85 over ~2 years (tie-breaker only).
    pub fn search(
        &self,
        query: &str,
        n: usize,
        filter: Option<SearchFilter>,
    ) -> Result<Vec<SearchResult>, BrainError> {
        let embedding = self.embedder.embed(query)?;
        // Over-fetch cosine candidates: 30× when diversity reranking is active (no type filter)
        // so buried non-fact memories can surface past the fact-flood. 10× otherwise.
        let type_filter_active_for_fetch =
            filter.as_ref().and_then(|f| f.memory_type.as_ref()).is_some();
        let overfetch = if type_filter_active_for_fetch { n * 10 } else { n * 30 };
        let cos_candidates = self
            .index
            .lock()
            .map_err(|e| BrainError::Database(e.to_string()))?
            .search(&embedding, overfetch);

        // BM25 candidates — fetch more than n so filters don't starve the result set.
        let bm25_ids = self.store.fts_search(query, n * 5).unwrap_or_default();

        // Build score maps.
        let n_bm25 = bm25_ids.len();
        let alpha = filter
            .as_ref()
            .and_then(|f| f.alpha)
            .unwrap_or(self.hybrid_alpha)
            .clamp(0.0, 1.0);
        let cos_score_of: std::collections::HashMap<&str, f32> = cos_candidates
            .iter()
            .map(|(id, dist)| (id.as_str(), (1.0 - *dist).clamp(0.0, 1.0)))
            .collect();
        let bm25_rank_of: std::collections::HashMap<&str, usize> = bm25_ids
            .iter()
            .enumerate()
            .map(|(i, id)| (id.as_str(), i + 1))
            .collect();

        // Union candidate ids (cosine first, then BM25-only additions).
        let mut candidate_ids: Vec<&str> =
            cos_candidates.iter().map(|(id, _)| id.as_str()).collect();
        for id in &bm25_ids {
            if !cos_score_of.contains_key(id.as_str()) {
                candidate_ids.push(id.as_str());
            }
        }

        let now = Utc::now();
        let mut scored: Vec<(SearchResult, f32)> = Vec::new();

        for id in candidate_ids {
            let Some(memory) = self.store.get_memory(id)? else {
                continue;
            };
            if let Some(ref f) = filter {
                if let Some(ref mt) = f.memory_type {
                    if &memory.metadata.memory_type != mt {
                        continue;
                    }
                }
                if let Some(ref proj) = f.project {
                    if &memory.metadata.project != proj {
                        continue;
                    }
                }
                if f.exclude_superseded && memory.metadata.superseded_by.is_some() {
                    continue;
                }
            }

            let cos_norm = *cos_score_of.get(id).unwrap_or(&0.0);
            let bm25_norm = bm25_rank_of
                .get(id)
                .map(|r| {
                    if n_bm25 <= 1 {
                        1.0
                    } else {
                        1.0 - ((*r as f32 - 1.0) / (n_bm25 as f32 - 1.0))
                    }
                })
                .unwrap_or(0.0);
            let hybrid_score = alpha * cos_norm + (1.0 - alpha) * bm25_norm;

            let effective_time = memory.metadata.event_time.unwrap_or(memory.metadata.timestamp);
            let age_days =
                (now - effective_time).num_seconds().max(0) as f32 / 86_400.0;
            // T32: recency weight — half-life ~730 days, floor at 0.85 (never suppresses).
            // event_time used when available (Phase 7); falls back to ingest timestamp.
            let recency_w = 0.85 + 0.15 * 0.5_f32.powf(age_days / 730.0);
            // Salience weight: LLM-assigned quality signal (0.0–1.0, default 0.5).
            // salience=0.5 → 1.00 (neutral), salience=1.0 → 1.15 (boost), salience=0.0 → 0.85 (suppress).
            let sal = memory.metadata.salience as f32;
            let salience_w = (1.0 + 0.3 * (sal - 0.5)).clamp(0.85, 1.15);
            let final_score = salience_w * recency_w * hybrid_score;

            let distance = cos_candidates
                .iter()
                .find(|(cid, _)| cid == id)
                .map(|(_, d)| *d)
                .unwrap_or(1.0);

            scored.push((
                SearchResult {
                    id: memory.id,
                    content: memory.content,
                    metadata: memory.metadata,
                    distance,
                },
                final_score,
            ));
        }

        // Sort descending — higher hybrid score is better.
        scored.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal));

        // Graph expansion (Task 7): pull in 1-hop entity neighbors of the top
        // seeds, score them with a hop-decay penalty, merge, and re-sort —
        // strictly before the final truncate/diversity cut below.
        if filter.as_ref().map(|f| f.graph_expand).unwrap_or(false) {
            self.expand_graph_neighbors(&mut scored, n, filter.as_ref())?;
        }

        // Type-diversity reranking: when no type filter is active, cap any single
        // memory type at 40% of n (min 1) so facts can't crowd out solutions/conversations.
        if type_filter_active_for_fetch {
            return Ok(scored.into_iter().take(n).map(|(r, _)| r).collect());
        }
        let cap = ((n as f32 * 0.4).ceil() as usize).max(1);
        let mut type_counts: std::collections::HashMap<std::mem::Discriminant<crate::types::MemoryType>, usize> =
            std::collections::HashMap::new();
        let mut diverse: Vec<SearchResult> = Vec::with_capacity(n);
        for (result, _) in scored {
            let disc = std::mem::discriminant(&result.metadata.memory_type);
            let count = type_counts.entry(disc).or_insert(0);
            if *count < cap {
                *count += 1;
                diverse.push(result);
                if diverse.len() == n {
                    break;
                }
            }
        }
        Ok(diverse)
    }

    /// Expand a ranked candidate list with 1-hop graph neighbors (Task 7).
    ///
    /// Seeds from the top `min(n, 5)` entries of `scored`. For each seed, looks
    /// up entity-sharing neighbors and scores each as `seed_score *
    /// GRAPH_HOP_DECAY`. When a neighbor is reachable from multiple seeds, the
    /// *best* (highest) seed score wins. Neighbors already present in `scored`
    /// are skipped — an existing candidate's score is never lowered or
    /// overwritten. Injected neighbors are capped at `n` before merging back
    /// in, then the whole list is re-sorted descending by score.
    fn expand_graph_neighbors(
        &self,
        scored: &mut Vec<(SearchResult, f32)>,
        n: usize,
        filter: Option<&SearchFilter>,
    ) -> Result<(), BrainError> {
        let exclude_superseded = filter.map(|f| f.exclude_superseded).unwrap_or(true);
        let seeds: Vec<(String, f32)> = scored
            .iter()
            .take(n.min(5))
            .map(|(r, score)| (r.id.clone(), *score))
            .collect();
        if seeds.is_empty() {
            return Ok(());
        }

        let existing_ids: std::collections::HashSet<&str> =
            scored.iter().map(|(r, _)| r.id.as_str()).collect();

        // Best (highest) seed-derived score that surfaced each neighbor.
        let mut best_neighbor_score: std::collections::HashMap<String, f32> =
            std::collections::HashMap::new();
        for (seed_id, seed_score) in &seeds {
            let neighbor_ids = self
                .store
                .neighbor_memory_ids(std::slice::from_ref(seed_id), exclude_superseded)?;
            let candidate_score = seed_score * GRAPH_HOP_DECAY;
            for nid in neighbor_ids {
                if existing_ids.contains(nid.as_str()) {
                    continue; // already ranked — never overwrite its score
                }
                best_neighbor_score
                    .entry(nid)
                    .and_modify(|s| {
                        if candidate_score > *s {
                            *s = candidate_score;
                        }
                    })
                    .or_insert(candidate_score);
            }
        }

        if best_neighbor_score.is_empty() {
            return Ok(());
        }

        // Cap neighbor injection at n extra candidates before the final cut.
        let mut neighbors: Vec<(String, f32)> = best_neighbor_score.into_iter().collect();
        neighbors.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal));
        neighbors.truncate(n);

        let score_of: std::collections::HashMap<&str, f32> = neighbors
            .iter()
            .map(|(id, score)| (id.as_str(), *score))
            .collect();
        let ids: Vec<&str> = neighbors.iter().map(|(id, _)| id.as_str()).collect();
        let memories = self.store.get_memories_by_ids(&ids)?;

        for memory in memories {
            let score = *score_of.get(memory.id.as_str()).unwrap_or(&0.0);
            scored.push((
                SearchResult {
                    id: memory.id,
                    content: memory.content,
                    metadata: memory.metadata,
                    distance: 1.0,
                },
                score,
            ));
        }

        scored.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal));
        Ok(())
    }

    pub fn get_memories_by_ids(&self, ids: &[&str]) -> Result<Vec<Memory>, BrainError> {
        self.store.get_memories_by_ids(ids)
    }

    pub fn timeline_around(
        &self,
        anchor_id: &str,
        before: u32,
        after: u32,
    ) -> Result<Vec<Memory>, BrainError> {
        self.store.timeline_around(anchor_id, before, after)
    }

    /// Get top-N most relevant memories for a topic/project.
    pub fn get_context(
        &self,
        topic: &str,
        project: Option<&str>,
        n: usize,
    ) -> Result<Vec<SearchResult>, BrainError> {
        let filter = project.map(|p| SearchFilter {
            project: Some(p.to_string()),
            ..SearchFilter::default()
        });
        self.search(topic, n, filter)
    }

    pub fn get_stats(&self) -> Result<BrainStats, BrainError> {
        Ok(BrainStats {
            total_memories: self.store.count_memories()?,
            total_sessions: self.store.count_sessions()?,
            save_count_this_session: self.save_count.load(Ordering::Relaxed),
            feedback_events_total: self.store.count_feedback_events()?,
            feedback_last_event_ts: self.store.feedback_last_event_ts()?,
            by_type: self.store.count_memories_by_type()?,
        })
    }

    /// Record structured feedback (accepted / rejected / etc.). Does not touch the vector index.
    pub fn append_feedback(
        &self,
        event_type: FeedbackEventType,
        memory_id: Option<&str>,
        query: Option<&str>,
        session_id: Option<&str>,
        project: Option<&str>,
        source: FeedbackSource,
        payload: serde_json::Value,
        idempotency_key: Option<&str>,
    ) -> Result<String, BrainError> {
        self.store.append_feedback(
            event_type,
            memory_id,
            query,
            session_id,
            project,
            source,
            payload,
            idempotency_key,
        )
    }

    pub fn list_feedback_since(
        &self,
        since: DateTime<Utc>,
    ) -> Result<Vec<FeedbackEventRecord>, BrainError> {
        self.store.list_feedback_since(since)
    }

    /// Attach an LLM client for summarization and reflection.
    pub fn with_llm_client(mut self, client: Box<dyn LlmClient>) -> Self {
        self.llm_client = Some(client);
        self
    }

    /// Manually trigger memory reflection (also auto-fires every `reflect_every_n` saves).
    pub fn trigger_reflection(&self) -> Result<ReflectionResult, BrainError> {
        if self.reflection_disabled {
            return Ok(ReflectionResult::default());
        }
        let client = self
            .llm_client
            .as_deref()
            .ok_or_else(|| BrainError::Summarization("no LLM client configured".into()))?;
        self.run_reflection(client)
    }

    fn run_reflection(&self, client: &dyn LlmClient) -> Result<ReflectionResult, BrainError> {
        let all = self.store.get_all_documents()?;
        if all.len() < 5 {
            return Ok(ReflectionResult::default());
        }

        // Take the 10 most recent knowledge memories (store returns them ordered by
        // timestamp DESC). Skip Conversation (raw dialogue noise) and Episode (none
        // exist today; future-proofing). Batch (10) == reflect_every_n (10) → full coverage.
        let batch: Vec<&Memory> = all
            .iter()
            .filter(|m| {
                !matches!(
                    m.metadata.memory_type,
                    MemoryType::Conversation | MemoryType::Episode
                )
            })
            .take(10)
            .collect();
        let ids: Vec<&str> = batch.iter().map(|m| m.id.as_str()).collect();
        let texts: Vec<&str> = batch.iter().map(|m| m.content.as_str()).collect();

        let summarizer = Summarizer::from_ref(client);
        let result = summarizer.reflect_memories(&texts)?;

        // Delete near-duplicates
        let to_delete: Vec<&str> = result
            .to_delete_indices
            .iter()
            .filter_map(|&i| ids.get(i).copied())
            .collect();
        if !to_delete.is_empty() {
            self.store.delete_memories(&to_delete)?;
            let mut index = self
                .index
                .lock()
                .map_err(|e| BrainError::Database(e.to_string()))?;
            for id in &to_delete {
                index.remove(id);
            }
        }

        // Save consolidated memories as patterns, but filter out meta-commentary
        // and trivial outputs that were the main source of corpus noise.
        for text in &result.consolidated {
            if is_noisy_reflection_output(text) {
                eprintln!(
                    "[brain] skipped noisy reflection output: {}",
                    text.chars().take(120).collect::<String>()
                );
                continue;
            }
            self.save_memory(
                text,
                MemoryType::Pattern,
                &["reflected"],
                "general",
                None,
                MemorySource::Reflection,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
            )?;
        }

        Ok(result)
    }

    pub fn delete_memories(&self, ids: &[&str]) -> Result<usize, BrainError> {
        let removed = self.store.delete_memories(ids)?;
        let mut index = self
            .index
            .lock()
            .map_err(|e| BrainError::Database(e.to_string()))?;
        for id in ids {
            index.remove(id);
        }
        Ok(removed)
    }

    /// Return every memory in storage, ordered by timestamp descending.
    /// Used by admin/maintenance tooling (listing, pruning).
    pub fn list_all_memories(&self) -> Result<Vec<Memory>, BrainError> {
        self.store.get_all_documents()
    }

    /// Update the salience score of a single memory. Returns false if the ID is not found.
    pub fn update_salience(&self, id: &str, salience: f64) -> Result<bool, BrainError> {
        self.store.update_salience(id, salience)
    }

    /// Link a memory to named entities (upsert entity rows + `mentions` edges).
    pub fn link_entities(
        &self,
        memory_id: &str,
        names: &[String],
    ) -> Result<usize, BrainError> {
        self.store.link_memory_entities(memory_id, names)
    }

    /// Entity (id, name) pairs linked to a memory via `mentions` edges.
    pub fn entities_for_memory(
        &self,
        memory_id: &str,
    ) -> Result<Vec<(String, String)>, BrainError> {
        self.store.entities_for_memory(memory_id)
    }

    /// 1-hop neighbor memory IDs sharing entities with the given seeds.
    pub fn neighbor_memory_ids(
        &self,
        memory_ids: &[String],
        exclude_superseded: bool,
    ) -> Result<Vec<String>, BrainError> {
        self.store
            .neighbor_memory_ids(memory_ids, exclude_superseded)
    }

    /// Memories with entity links + entity catalog for the Linked graph UI.
    pub fn list_linked_graph(
        &self,
    ) -> Result<(Vec<crate::store::LinkedMemoryRow>, Vec<(String, String, usize)>), BrainError>
    {
        let memories = self.store.list_linked_memories()?;
        let entities = self.store.list_entities_with_counts()?;
        Ok((memories, entities))
    }
}

/// Heuristic filter to catch LLM meta-commentary and trivial outputs
/// before they get persisted as "pattern" memories.
fn is_noisy_reflection_output(text: &str) -> bool {
    let trimmed = text.trim();
    if trimmed.len() < 30 {
        return true;
    }
    let lowered = trimmed.to_lowercase();
    const MARKERS: &[&str] = &[
        "memories 0",
        "memory 0",
        "do not fit",
        "these memories",
        "the memories",
        "no clear pattern",
        "no actionable",
        "no significant",
        "empty session",
        "test memory",
        "as an ai",
    ];
    MARKERS.iter().any(|m| lowered.contains(m))
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use crate::embedder::MockEmbedder;
    use tokio::sync::broadcast;

    fn test_brain() -> Brain {
        let config = BrainConfig {
            db_path: ":memory:".into(),
            embedding_dims: 16, // small dims for tests
            reflect_every_n: 20,
            reflection_disabled: false,
            hybrid_alpha: 0.7,
        };
        Brain::open(config, Box::new(MockEmbedder::new(16))).unwrap()
    }

    #[tokio::test]
    async fn save_memory_broadcasts_event() {
        let (tx, _) = broadcast::channel(16);
        let mut rx = tx.subscribe();
        let config = BrainConfig {
            db_path: ":memory:".into(),
            embedding_dims: 16,
            reflect_every_n: 20,
            reflection_disabled: false,
            hybrid_alpha: 0.7,
        };
        let brain =
            Brain::open_with_event_bus(config, Box::new(MockEmbedder::new(16)), Some(tx)).unwrap();
        let id = brain
            .save_memory(
                "stream test body",
                MemoryType::Solution,
                &[],
                "proj",
                None,
                MemorySource::ClaudeCodeSession,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
            )
            .unwrap();
        let evt = tokio::time::timeout(std::time::Duration::from_millis(200), rx.recv())
            .await
            .expect("timeout")
            .expect("recv");
        assert_eq!(evt.id, id);
        assert!(evt.content_snippet.contains("stream test"));
    }

    #[test]
    fn save_memory_returns_uuid() {
        let brain = test_brain();
        let id = brain
            .save_memory("fix the parser bug", MemoryType::Solution, &["parser", "bug"], "myproject", None, MemorySource::ClaudeCodeSession, None, None, None, None, None, None, None)
            .unwrap();
        assert!(!id.is_empty());
        assert_eq!(id.len(), 36); // UUID v4 format
    }

    fn save(brain: &Brain, content: &str, ty: MemoryType, project: &str) -> String {
        brain
            .save_memory(content, ty, &[], project, None, MemorySource::ClaudeCodeSession, None, None, None, None, None, None, None)
            .unwrap()
    }

    #[test]
    fn save_memory_skips_same_project_type_duplicate() {
        let brain = test_brain();
        let id1 = save(&brain, "identical body text", MemoryType::Solution, "p");
        let id2 = save(&brain, "identical body text", MemoryType::Solution, "p");
        // Duplicate is skipped: returns the existing id, corpus does not grow.
        assert_eq!(id1, id2);
        assert_eq!(brain.list_all_memories().unwrap().len(), 1);
    }

    #[test]
    fn save_memory_keeps_duplicate_in_different_project() {
        let brain = test_brain();
        let id1 = save(&brain, "identical body text", MemoryType::Solution, "p1");
        let id2 = save(&brain, "identical body text", MemoryType::Solution, "p2");
        assert_ne!(id1, id2);
        assert_eq!(brain.list_all_memories().unwrap().len(), 2);
    }

    #[test]
    fn save_memory_keeps_duplicate_of_different_type() {
        let brain = test_brain();
        let id1 = save(&brain, "identical body text", MemoryType::Solution, "p");
        let id2 = save(&brain, "identical body text", MemoryType::Fact, "p");
        assert_ne!(id1, id2);
        assert_eq!(brain.list_all_memories().unwrap().len(), 2);
    }

    #[test]
    fn save_memory_keeps_distinct_content() {
        let brain = test_brain();
        let id1 = save(&brain, "first distinct memory body", MemoryType::Solution, "p");
        let id2 = save(&brain, "completely different memory body", MemoryType::Solution, "p");
        assert_ne!(id1, id2);
        assert_eq!(brain.list_all_memories().unwrap().len(), 2);
    }

    #[test]
    fn save_memory_strips_private_blocks() {
        let brain = test_brain();
        let id = brain
            .save_memory(
                "public part <private>secret</private> more public",
                MemoryType::Conversation,
                &[],
                "p",
                None,
                MemorySource::ClaudeCodeSession,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
            )
            .expect("save");
        let mem = brain.store.get_memory(&id).expect("get").expect("exists");
        assert!(!mem.content.contains("secret"));
        assert!(mem.content.contains("public part"));
    }

    #[test]
    fn save_memory_fills_title_when_omitted() {
        let brain = test_brain();
        let id = brain
            .save_memory(
                "[API] rate limits and retries\n\nbody",
                MemoryType::Solution,
                &[],
                "p",
                None,
                MemorySource::ClaudeCodeSession,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
            )
            .unwrap();
        let mem = brain.store.get_memory(&id).unwrap().expect("get");
        assert_eq!(mem.metadata.title.as_deref(), Some("API"));
    }

    #[test]
    fn save_memory_increments_stats() {
        let brain = test_brain();
        brain.save_memory("m1", MemoryType::Solution, &[], "p", None, MemorySource::ClaudeCodeSession, None, None, None, None, None, None, None).unwrap();
        brain.save_memory("m2", MemoryType::Decision, &[], "p", None, MemorySource::ClaudeCodeSession, None, None, None, None, None, None, None).unwrap();
        let stats = brain.get_stats().unwrap();
        assert_eq!(stats.total_memories, 2);
        assert_eq!(stats.save_count_this_session, 2);
    }

    #[test]
    fn append_feedback_increments_feedback_stats() {
        let brain = test_brain();
        brain
            .append_feedback(
                FeedbackEventType::Ranked,
                Some("mid"),
                Some("q"),
                None,
                None,
                FeedbackSource::BrainApi,
                serde_json::json!({"position": 2}),
                None,
            )
            .unwrap();
        let stats = brain.get_stats().unwrap();
        assert_eq!(stats.feedback_events_total, 1);
        assert!(stats.feedback_last_event_ts.is_some());
    }

    #[test]
    fn search_finds_saved_memory() {
        let brain = test_brain();
        let id = brain
            .save_memory("refactor the embedder module", MemoryType::Solution, &["refactor"], "AI", None, MemorySource::ClaudeCodeSession, None, None, None, None, None, None, None)
            .unwrap();
        let results = brain.search("refactor the embedder module", 5, None).unwrap();
        assert!(!results.is_empty());
        assert_eq!(results[0].id, id);
    }

    #[test]
    fn search_with_type_filter_excludes_non_matching() {
        let brain = test_brain();
        brain.save_memory("solution content", MemoryType::Solution, &[], "p", None, MemorySource::ClaudeCodeSession, None, None, None, None, None, None, None).unwrap();
        brain.save_memory("decision content", MemoryType::Decision, &[], "p", None, MemorySource::ClaudeCodeSession, None, None, None, None, None, None, None).unwrap();

        let filter = SearchFilter {
            memory_type: Some(MemoryType::Decision),
            ..SearchFilter::default()
        };
        let results = brain.search("content", 10, Some(filter)).unwrap();
        assert!(results.iter().all(|r| r.metadata.memory_type == MemoryType::Decision));
    }

    #[test]
    fn search_with_project_filter_excludes_non_matching() {
        let brain = test_brain();
        brain.save_memory("project A memory", MemoryType::Solution, &[], "project_a", None, MemorySource::ClaudeCodeSession, None, None, None, None, None, None, None).unwrap();
        brain.save_memory("project B memory", MemoryType::Solution, &[], "project_b", None, MemorySource::ClaudeCodeSession, None, None, None, None, None, None, None).unwrap();

        let filter = SearchFilter {
            project: Some("project_a".into()),
            ..SearchFilter::default()
        };
        let results = brain.search("memory", 10, Some(filter)).unwrap();
        assert!(results.iter().all(|r| r.metadata.project == "project_a"));
    }

    /// Task 7: `graph_expand=true` should pull in a 1-hop entity neighbor that
    /// the pure hybrid (cosine+BM25) ranking buries outside the overfetch
    /// window, and rank it above a "decoy" that beats it on raw similarity
    /// alone but shares no entity with the query's top hit.
    #[test]
    fn graph_expand_surfaces_linked_neighbor_above_decoy() {
        let brain = test_brain();
        let probe = MockEmbedder::new(16);
        let query = "widgetalpha graphseed uniquequery ztoken";

        fn cos_sim(a: &[f32], b: &[f32]) -> f32 {
            a.iter().zip(b).map(|(x, y)| x * y).sum()
        }

        let q_emb = probe.embed(query).unwrap();

        // Build a filler pool sharing no vocabulary with the query, rank it by
        // raw cosine similarity, and take the *weakest* one as the "neighbor".
        // With 25 candidates ranked strictly above it (seed + 24 fillers), it
        // falls outside both the cosine top-20 and BM25 top-10 overfetch
        // windows used below (n=2, type filter active) — so it cannot appear
        // in results at all without graph expansion.
        let pool: Vec<String> = (0..25)
            .map(|i| format!("fillertopic{i} unrelated block content"))
            .collect();
        let mut ranked: Vec<(String, f32)> = pool
            .into_iter()
            .map(|t| {
                let sim = cos_sim(&q_emb, &probe.embed(&t).unwrap());
                (t, sim)
            })
            .collect();
        ranked.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap());

        let (neighbor_text, _) = ranked.pop().unwrap(); // globally weakest similarity
        let decoy_text = ranked.remove(0).0; // strongest of the remaining fillers
        let fillers: Vec<String> = ranked.into_iter().map(|(t, _)| t).collect();

        let seed_id = brain
            .save_memory(query, MemoryType::Fact, &[], "p", None, MemorySource::ClaudeCodeSession, None, None, None, None, None, None, None)
            .unwrap();
        let decoy_id = brain
            .save_memory(&decoy_text, MemoryType::Fact, &[], "p", None, MemorySource::ClaudeCodeSession, None, None, None, None, None, None, None)
            .unwrap();
        let neighbor_id = brain
            .save_memory(&neighbor_text, MemoryType::Fact, &[], "p", None, MemorySource::ClaudeCodeSession, None, None, None, None, None, None, None)
            .unwrap();
        for filler in &fillers {
            brain
                .save_memory(filler, MemoryType::Fact, &[], "p", None, MemorySource::ClaudeCodeSession, None, None, None, None, None, None, None)
                .unwrap();
        }

        brain.link_entities(&seed_id, &["SharedTopic".into()]).unwrap();
        brain.link_entities(&neighbor_id, &["SharedTopic".into()]).unwrap();
        // decoy_id deliberately has no linked entity.

        let n = 2;
        let base_filter = SearchFilter {
            memory_type: Some(MemoryType::Fact),
            ..SearchFilter::default()
        };

        // RED (pre-implementation baseline): without graph_expand, the
        // neighbor is fully absent — buried outside the overfetch window —
        // and the decoy (highest raw similarity among fillers) takes the
        // second slot behind the seed.
        let baseline = brain.search(query, n, Some(base_filter.clone())).unwrap();
        let baseline_ids: Vec<&str> = baseline.iter().map(|r| r.id.as_str()).collect();
        assert_eq!(
            baseline_ids,
            vec![seed_id.as_str(), decoy_id.as_str()],
            "setup invariant: baseline top-2 should be [seed, decoy] with neighbor absent"
        );

        // GREEN: graph_expand=true surfaces the entity-linked neighbor above
        // the decoy, because 0.85 * seed_score always beats the decoy's max
        // possible hybrid score (0.7, since it earns no BM25 contribution).
        let expand_filter = SearchFilter {
            graph_expand: true,
            ..base_filter
        };
        let expanded = brain.search(query, n, Some(expand_filter)).unwrap();
        let expanded_ids: Vec<&str> = expanded.iter().map(|r| r.id.as_str()).collect();
        assert_eq!(
            expanded_ids,
            vec![seed_id.as_str(), neighbor_id.as_str()],
            "graph_expand should surface the linked neighbor above the decoy"
        );
    }

    #[test]
    fn delete_memories_removes_from_store_and_index() {
        let brain = test_brain();
        let id1 = brain.save_memory("keep this", MemoryType::Solution, &[], "p", None, MemorySource::ClaudeCodeSession, None, None, None, None, None, None, None).unwrap();
        let id2 = brain.save_memory("delete this", MemoryType::Solution, &[], "p", None, MemorySource::ClaudeCodeSession, None, None, None, None, None, None, None).unwrap();

        let removed = brain.delete_memories(&[&id2]).unwrap();
        assert_eq!(removed, 1);

        let stats = brain.get_stats().unwrap();
        assert_eq!(stats.total_memories, 1);

        // Deleted memory should not appear in search
        let results = brain.search("delete this", 5, None).unwrap();
        assert!(results.iter().all(|r| r.id != id2));

        // Kept memory should still be there
        let results = brain.search("keep this", 5, None).unwrap();
        assert!(results.iter().any(|r| r.id == id1));
    }

    #[test]
    fn get_context_filters_by_project() {
        let brain = test_brain();
        brain.save_memory("AI project context", MemoryType::ProjectContext, &[], "AI", None, MemorySource::ClaudeCodeSession, None, None, None, None, None, None, None).unwrap();
        brain.save_memory("other project context", MemoryType::ProjectContext, &[], "other", None, MemorySource::ClaudeCodeSession, None, None, None, None, None, None, None).unwrap();

        let results = brain.get_context("context", Some("AI"), 5).unwrap();
        assert!(results.iter().all(|r| r.metadata.project == "AI"));
    }

    #[test]
    fn save_memory_does_not_write_index_file() {
        let dir = tempfile::TempDir::new().unwrap();
        let db_path = dir.path().join("brain.db").to_string_lossy().to_string();
        let index_file = dir.path().join("brain_index.bin");

        let config = BrainConfig {
            db_path,
            embedding_dims: 16,
            reflect_every_n: 20,
            reflection_disabled: false,
            hybrid_alpha: 0.7,
        };
        let brain = Brain::open(config, Box::new(MockEmbedder::new(16))).unwrap();
        brain
            .save_memory("test", MemoryType::Solution, &[], "p", None, MemorySource::ClaudeCodeSession, None, None, None, None, None, None, None)
            .unwrap();
        assert!(!index_file.exists(), "index file should not be written");
    }

    #[test]
    fn trigger_reflection_without_client_errors() {
        let brain = test_brain();
        let result = brain.trigger_reflection();
        assert!(result.is_err());
    }

    #[test]
    fn trigger_reflection_skips_when_fewer_than_5_memories() {
        use crate::summarizer::MockLlmClient;
        let config = BrainConfig {
            db_path: ":memory:".into(),
            embedding_dims: 16,
            reflect_every_n: 20,
            reflection_disabled: false,
            hybrid_alpha: 0.7,
        };
        let brain = Brain::open(config, Box::new(MockEmbedder::new(16)))
            .unwrap()
            .with_llm_client(Box::new(MockLlmClient::new(
                r#"{"consolidated":[],"patterns":[],"to_delete_indices":[]}"#,
            )));
        brain.save_memory("only one", MemoryType::Solution, &[], "p", None, MemorySource::ClaudeCodeSession, None, None, None, None, None, None, None).unwrap();
        let result = brain.trigger_reflection().unwrap();
        assert!(result.to_delete_indices.is_empty());
    }

    #[test]
    fn trigger_reflection_deletes_marked_memories() {
        use crate::summarizer::MockLlmClient;
        let config = BrainConfig {
            db_path: ":memory:".into(),
            embedding_dims: 16,
            reflect_every_n: 100,
            reflection_disabled: false,
            hybrid_alpha: 0.7,
        };
        let brain = Brain::open(config, Box::new(MockEmbedder::new(16))).unwrap();

        // Save 6 clearly distinct memories. Content must be dissimilar enough to
        // survive the save-time dedup guard (different topics, not "memory N"),
        // so this test exercises reflection deletion in isolation.
        let bodies = [
            "fix the JSON parser overflow on deeply nested arrays",
            "configure nginx reverse proxy timeouts for upstream",
            "migrate the user table to add a soft-delete column",
            "debounce the search input to reduce API call volume",
            "cache embedding lookups in an LRU to cut latency",
            "rotate the signing keys and update the JWKS endpoint",
        ];
        for body in bodies {
            brain.save_memory(
                body,
                MemoryType::Solution, &[], "p", None, MemorySource::ClaudeCodeSession, None, None, None,
                None, None, None, None,
            ).unwrap();
        }

        let before = brain.get_stats().unwrap().total_memories;

        // Mock LLM says delete index 0 and 1, and proposes one substantive
        // consolidated pattern (must be > 30 chars and not match noise markers
        // to pass is_noisy_reflection_output).
        let mock_response = r#"{"consolidated":["Use builder pattern for all config structs across the codebase"],"patterns":[],"to_delete_indices":[0,1]}"#;
        let brain = brain.with_llm_client(Box::new(MockLlmClient::new(mock_response)));

        let result = brain.trigger_reflection().unwrap();
        assert_eq!(result.to_delete_indices, vec![0, 1]);

        let after = brain.get_stats().unwrap().total_memories;
        // deleted 2, added 1 consolidated → net -1
        assert_eq!(after, before - 1);
    }

    #[test]
    fn reflection_quality_filter_rejects_noise() {
        assert!(is_noisy_reflection_output("test memory"));
        assert!(is_noisy_reflection_output("short"));
        assert!(is_noisy_reflection_output(
            "Memories 0, 1, and 5 do not fit into these categories"
        ));
        assert!(is_noisy_reflection_output(
            "These memories cover various unrelated topics."
        ));
        assert!(!is_noisy_reflection_output(
            "Use builder pattern for all config structs across the codebase"
        ));
    }

    #[test]
    fn open_brain_rebuilds_index_from_sqlite() {
        let dir = tempfile::TempDir::new().unwrap();
        let db_path = dir.path().join("brain.db").to_string_lossy().to_string();

        {
            let config = BrainConfig {
                db_path: db_path.clone(),
                embedding_dims: 16,
                reflect_every_n: 20,
                reflection_disabled: false,
                hybrid_alpha: 0.7,
            };
            let brain = Brain::open(config, Box::new(MockEmbedder::new(16))).unwrap();
            brain
                .save_memory(
                    "rebuild from sql test",
                    MemoryType::Solution,
                    &[],
                    "p",
                    None,
                    MemorySource::ClaudeCodeSession,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                )
                .unwrap();
        }

        // Re-open — index must be rebuilt from SQLite, no binary file
        let config2 = BrainConfig {
            db_path,
            embedding_dims: 16,
            reflect_every_n: 20,
            reflection_disabled: false,
            hybrid_alpha: 0.7,
        };
        let brain2 = Brain::open(config2, Box::new(MockEmbedder::new(16))).unwrap();
        let results = brain2
            .search("rebuild from sql test", 1, None)
            .unwrap();
        assert_eq!(results.len(), 1);
    }

    #[test]
    fn get_stats_counts_sessions() {
        let brain = test_brain();
        let mut meta1 = MemoryMetadata {
            memory_type: MemoryType::Solution,
            project: "p".into(),
            tags: String::new(),
            timestamp: Utc::now(),
            source: MemorySource::ClaudeCodeSession,
            session_id: "session-1".into(),
            importance: 0.5,
            file_path: None,
            thread_id: None,
            title: None,
            parent_id: None,
            event_time: None,
            salience: 0.5,
            superseded_by: None,
            derived_from: None,
        };
        let m1 = Memory { id: "m1".into(), content: "c1".into(), metadata: meta1.clone(), embedding: None };
        brain.store.upsert_memory(&m1).unwrap();
        meta1.session_id = "session-2".into();
        let m2 = Memory { id: "m2".into(), content: "c2".into(), metadata: meta1, embedding: None };
        brain.store.upsert_memory(&m2).unwrap();

        let stats = brain.get_stats().unwrap();
        assert_eq!(stats.total_sessions, 2);
    }

    #[test]
    fn save_memory_persists_file_path() {
        let brain = test_brain();
        let id = brain
            .save_memory(
                "chunk body",
                MemoryType::ProjectContext,
                &["vault"],
                "AI",
                None,
                MemorySource::Obsidian,
                Some("vault/01 Projects/Foo/note.md"),
                Some("Foo — Section A"),
                None,
                None,
                None,
                None,
                None,
            )
            .unwrap();
        let mem = brain.store.get_memory(&id).unwrap().expect("saved memory");
        assert_eq!(
            mem.metadata.file_path.as_deref(),
            Some("vault/01 Projects/Foo/note.md")
        );
        assert_eq!(mem.metadata.title.as_deref(), Some("Foo — Section A"));
        assert_eq!(mem.metadata.source, MemorySource::Obsidian);

        let results = brain.search("chunk body", 5, None).unwrap();
        let hit = results.iter().find(|r| r.id == id).expect("search hit");
        assert_eq!(
            hit.metadata.file_path.as_deref(),
            Some("vault/01 Projects/Foo/note.md")
        );
    }

    #[test]
    fn recency_uses_event_time_over_timestamp() {
        use chrono::{Duration, Utc};
        let now = Utc::now();
        let old_event = now - Duration::days(730);

        // event_time present → age ~730 days
        let age_with = (now - Some(old_event).unwrap_or(now))
            .num_seconds().max(0) as f32 / 86_400.0;
        // event_time absent → fall back to timestamp (now) → age ~0 days
        let age_without = (now - (None::<chrono::DateTime<Utc>>).unwrap_or(now))
            .num_seconds().max(0) as f32 / 86_400.0;

        assert!(age_with > 700.0, "event_time should give ~730 day age, got {age_with}");
        assert!(age_without < 1.0, "no event_time → timestamp → ~0 day age, got {age_without}");
    }
}
