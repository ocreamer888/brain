use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum MemoryType {
    Solution,
    Decision,
    Conversation,
    Pattern,
    ProjectContext,
    ErrorLesson,
    /// Atomic extracted fact — the primary retrieval unit (Mem0-style dual layer).
    Fact,
    /// Full session/document body retained for audit and Letta-style recall.
    Episode,
    /// Authored corpus chunk (docs, books, specs, manuals) with provenance.
    /// Written only by deliberate ingest or explicit agent choice — never by
    /// session recycling or fact extraction.
    Knowledge,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum MemorySource {
    ClaudeCodeSession,
    Reflection,
    CursorHistory,
    ClawCode,
    Perplexity,
    Obsidian,
    ObsidianBooks,
    /// Hermes agent (any profile/platform — see metadata.tags for which one).
    Hermes,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SaveOutcome {
    pub id: String,
    /// True when save-time near-duplicate guard returned an existing memory id.
    pub deduped: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MemoryMetadata {
    #[serde(rename = "type")]
    pub memory_type: MemoryType,
    pub project: String,
    pub tags: String,
    pub timestamp: DateTime<Utc>,
    pub source: MemorySource,
    #[serde(default)]
    pub session_id: String,
    #[serde(default = "default_importance")]
    pub importance: f64,
    pub file_path: Option<String>,
    pub thread_id: Option<String>,
    pub title: Option<String>,

    // --- Fact-layer fields (null for all pre-existing memories) ---

    /// For `Fact` memories: ID of the parent `Episode` from which this was extracted.
    #[serde(default)]
    pub parent_id: Option<String>,

    /// When the fact/event actually occurred (distinct from `timestamp` = ingest time).
    /// Zep-inspired: enables event-time recency decay in Phase 7 once calibrated.
    #[serde(default)]
    pub event_time: Option<DateTime<Utc>>,

    /// Extraction confidence from the fact extractor (0.0–1.0), OR a human's
    /// manual override via `PATCH /memories/:id` (see `salience_pinned`).
    /// Affects retrieval scoring (`brain.rs:437`'s `salience_w`) only when
    /// `salience_pinned` is true (G0, cognitive-architecture-spec.md §0).
    #[serde(default = "default_salience")]
    pub salience: f64,

    /// G0: true only when `salience` was set by a deliberate human action
    /// (`PATCH /memories/:id`), never by the LLM extractor's `/save` call —
    /// the extractor's auto-score was found to anti-correlate with true
    /// quality (Phase 6 calibration), so it's excluded from ranking unless
    /// pinned. Default false.
    #[serde(default)]
    pub salience_pinned: bool,

    /// ID of the fact that supersedes this one (set on UPDATE/MERGE by curator).
    /// Superseded facts stay in DB for audit; excluded from search by default.
    #[serde(default)]
    pub superseded_by: Option<String>,

    /// Extractor model + prompt version tag (e.g. "openrouter/claude-sonnet-4-5/v1").
    /// Used to track extraction quality across prompt iterations.
    /// Wire name: `extracted_by`. Legacy input alias: `derived_from`.
    #[serde(default, alias = "derived_from")]
    pub extracted_by: Option<String>,
}

fn default_importance() -> f64 {
    0.5
}

fn default_salience() -> f64 {
    0.5
}

#[derive(Debug, Clone)]
pub struct Memory {
    pub id: String,
    pub content: String,
    pub metadata: MemoryMetadata,
    pub embedding: Option<Vec<f32>>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SearchResult {
    pub id: String,
    pub content: String,
    pub metadata: MemoryMetadata,
    pub distance: f32,
    /// Final ranked score (salience_w × recency_w × hybrid × knowledge_w).
    /// Distance alone can't show BM25 keyword wins; grounding hints need this.
    #[serde(default)]
    pub score: f32,
    /// source_quality_w for this result's `metadata.source` (brain.rs's
    /// source_quality_w doc comment -- a proposed, not-yet-scoped-into-G2
    /// line from the original vision, newly grounded). Always computed and
    /// exposed for inspection; only multiplied into `score` when the request
    /// set `SearchFilter::apply_source_quality` (default off).
    #[serde(default)]
    pub source_quality: f32,
    /// Only set when `SearchFilter::include_superseded_with_lineage` let
    /// this superseded row through -- see that field's doc comment.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub lineage: Option<MemoryLineage>,
}

#[derive(Debug, Clone)]
pub struct SearchFilter {
    pub memory_type: Option<MemoryType>,
    pub project: Option<String>,
    pub exclude_superseded: bool,
    pub alpha: Option<f32>,
    /// When true, expand the ranked candidate list with 1-hop graph neighbors
    /// (shared entities) before the final truncate. Default off (Phase C, Task 7).
    pub graph_expand: bool,
    /// Episode rows (raw PostToolUse/session traces) are audit trail, not
    /// curated knowledge — excluded from untyped search by default so they
    /// never crowd context-injection. An explicit `memory_type` filter (or
    /// `get_episode` by id) still reaches them. Default true.
    pub exclude_episodes_by_default: bool,
    /// G0 (cognitive-architecture-spec.md §0): when true, treat salience_w as
    /// 1.0 for this request only instead of the live brain.rs:437 formula.
    /// Request-scoped and default-off so it never changes ranking for real
    /// traffic — exists solely so the eval harness can A/B live vs. neutral
    /// salience against the trustworthy gold set without a global ranking
    /// change. Do not wire this to a public API default without a decision.
    pub salience_neutral: bool,
    /// When true, multiply source_quality_w (brain.rs) into the final score
    /// for this request. Default off -- source_quality is always computed
    /// and exposed on every SearchResult regardless of this flag, but it
    /// does not affect real-traffic ranking until validated the same way
    /// G0 validated salience (A/B on the trustworthy gold set) and this
    /// default is deliberately flipped. Do not flip without that A/B.
    pub apply_source_quality: bool,
    /// G8 (cognitive-architecture-spec.md §8.4): when true, multiply
    /// layer_w into the final score, derived at query time from
    /// `layer::depth()` (explicit superseded_by + judged `layers_on`
    /// memory_links, see brain/rust/src/layer.rs). Independent of
    /// salience_w -- a deliberate human pin (G0) still applies on top; only
    /// the automatic, majority-neutral LLM auto-score is what layer_w
    /// actually targets, not the pin (fixed 2026-11-06 after an earlier
    /// version of this flag unconditionally zeroed salience_w, which would
    /// have discarded every pinned "Promote" row — see
    /// `use_layer_confidence_does_not_discard_a_deliberate_pin`, brain.rs).
    /// **Default true as of 2026-11-06**, after validating 0 unexplained
    /// regressions / 4 fixes on a 42-pair real A/B
    /// (docs/architecture/experiments/2026-11-06-layer-judgment-gate/).
    /// Still request-overridable to `false` for eval/ops work that needs
    /// the pre-G8 baseline for comparison.
    pub use_layer_confidence: bool,
    /// Spec §8.8 open question 1 (owner condition, 2026-11-06): a
    /// superseded memory may resurface in search ONLY if the result
    /// genuinely carries its historical link — what it was replaced by —
    /// not stale content with no traceability. When true: a row with
    /// `exclude_superseded=true` and a non-null `superseded_by` is no
    /// longer hard-excluded; it is let through *only if*
    /// `store::resolved_supersedes` resolves it to a real, existing row
    /// (a dangling id or a `quarantine:*`/`hidden:*` sentinel still has
    /// nothing to trace, so it stays excluded either way). When let
    /// through, `SearchResult::lineage` is populated with the resolved
    /// successor and this row's own `layer::depth()`/`layer_w()` — the
    /// "timeline position" the owner asked to see, not just the row.
    /// Default true as of 2026-11-06 (owner decision, after the opt-in
    /// build was verified live against real production data). Does
    /// nothing when `exclude_superseded` is false (nothing is being
    /// excluded to let back in). Still request-overridable to `false`.
    pub include_superseded_with_lineage: bool,
}

/// Populated on a `SearchResult` only when `SearchFilter::
/// include_superseded_with_lineage` let a superseded memory through —
/// `None` for every other result, including every result today before
/// this field existed. This is the traceability payload spec §8.8's
/// resurfacing condition requires: what replaced this memory, and how
/// deep it sits in its own stack.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MemoryLineage {
    pub superseded_by_id: String,
    pub superseded_by_snippet: String,
    pub depth: f32,
    pub layer_w: f32,
}

impl Default for SearchFilter {
    fn default() -> Self {
        Self {
            memory_type: None,
            project: None,
            exclude_superseded: true,
            alpha: None,
            graph_expand: false,
            exclude_episodes_by_default: true,
            salience_neutral: false,
            apply_source_quality: false,
            use_layer_confidence: true,
            include_superseded_with_lineage: true,
        }
    }
}

/// User/tool feedback on retrieval or saved memories (Phase 7). Stored separately from `memories`.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum FeedbackEventType {
    Accepted,
    Rejected,
    Edited,
    Ranked,
    Dismissed,
}

impl FeedbackEventType {
    pub fn as_str(&self) -> &'static str {
        match self {
            FeedbackEventType::Accepted => "accepted",
            FeedbackEventType::Rejected => "rejected",
            FeedbackEventType::Edited => "edited",
            FeedbackEventType::Ranked => "ranked",
            FeedbackEventType::Dismissed => "dismissed",
        }
    }

    pub fn from_str(s: &str) -> Option<Self> {
        match s {
            "accepted" => Some(FeedbackEventType::Accepted),
            "rejected" => Some(FeedbackEventType::Rejected),
            "edited" => Some(FeedbackEventType::Edited),
            "ranked" => Some(FeedbackEventType::Ranked),
            "dismissed" => Some(FeedbackEventType::Dismissed),
            _ => None,
        }
    }
}

/// Where the feedback event originated (distinct from [`MemorySource`]).
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum FeedbackSource {
    BrainApi,
    Mcp,
    Hook,
}

impl FeedbackSource {
    pub fn as_str(&self) -> &'static str {
        match self {
            FeedbackSource::BrainApi => "brain_api",
            FeedbackSource::Mcp => "mcp",
            FeedbackSource::Hook => "hook",
        }
    }

    pub fn from_str(s: &str) -> Option<Self> {
        match s {
            "brain_api" => Some(FeedbackSource::BrainApi),
            "mcp" => Some(FeedbackSource::Mcp),
            "hook" => Some(FeedbackSource::Hook),
            _ => None,
        }
    }
}

/// One row from `feedback_events`, suitable for JSONL export (schema version 1).
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FeedbackEventRecord {
    pub id: String,
    pub ts: String,
    pub event_type: FeedbackEventType,
    pub memory_id: Option<String>,
    pub query: Option<String>,
    pub session_id: Option<String>,
    pub project: Option<String>,
    pub source: FeedbackSource,
    pub payload: serde_json::Value,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub idempotency_key: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BrainStats {
    pub total_memories: usize,
    pub total_sessions: usize,
    pub save_count_this_session: usize,
    pub feedback_events_total: usize,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub feedback_last_event_ts: Option<String>,
    pub by_type: std::collections::HashMap<String, usize>,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn memory_type_serializes_to_snake_case() {
        assert_eq!(
            serde_json::to_string(&MemoryType::ErrorLesson).unwrap(),
            "\"error_lesson\""
        );
        assert_eq!(
            serde_json::to_string(&MemoryType::Solution).unwrap(),
            "\"solution\""
        );
        assert_eq!(
            serde_json::to_string(&MemoryType::Fact).unwrap(),
            "\"fact\""
        );
        assert_eq!(
            serde_json::to_string(&MemoryType::Episode).unwrap(),
            "\"episode\""
        );
        assert_eq!(
            serde_json::to_string(&MemoryType::Knowledge).unwrap(),
            "\"knowledge\""
        );
    }

    #[test]
    fn memory_type_knowledge_round_trips() {
        let t: MemoryType = serde_json::from_str("\"knowledge\"").unwrap();
        assert_eq!(t, MemoryType::Knowledge);
    }

    #[test]
    fn memory_metadata_accepts_legacy_derived_from_alias() {
        let json = r#"{"type":"fact","project":"brain","tags":"","timestamp":"2026-10-16T00:00:00Z","source":"claude_code_session","derived_from":"ollama/test/v1"}"#;
        let meta: MemoryMetadata = serde_json::from_str(json).unwrap();
        assert_eq!(meta.extracted_by.as_deref(), Some("ollama/test/v1"));
    }

    #[test]
    fn feedback_event_type_round_trip() {
        assert_eq!(
            FeedbackEventType::from_str("accepted"),
            Some(FeedbackEventType::Accepted)
        );
        assert_eq!(FeedbackEventType::Accepted.as_str(), "accepted");
    }

    #[test]
    fn feedback_source_round_trip() {
        assert_eq!(
            FeedbackSource::from_str("mcp"),
            Some(FeedbackSource::Mcp)
        );
        assert_eq!(FeedbackSource::Mcp.as_str(), "mcp");
    }

    #[test]
    fn memory_source_serializes_to_snake_case() {
        assert_eq!(
            serde_json::to_string(&MemorySource::ClaudeCodeSession).unwrap(),
            "\"claude_code_session\""
        );
        assert_eq!(
            serde_json::to_string(&MemorySource::ClawCode).unwrap(),
            "\"claw_code\""
        );
        assert_eq!(
            serde_json::to_string(&MemorySource::Obsidian).unwrap(),
            "\"obsidian\""
        );
        assert_eq!(
            serde_json::to_string(&MemorySource::ObsidianBooks).unwrap(),
            "\"obsidian_books\""
        );
    }

    #[test]
    fn memory_metadata_round_trips() {
        let meta = MemoryMetadata {
            memory_type: MemoryType::Solution,
            project: "test".into(),
            tags: "rust,brain".into(),
            timestamp: Utc::now(),
            source: MemorySource::ClaudeCodeSession,
            session_id: String::new(),
            importance: 0.7,
            file_path: None,
            thread_id: None,
            title: None,
            parent_id: None,
            event_time: None,
            salience: 0.5,
            salience_pinned: false,
            superseded_by: None,
            extracted_by: None,
        };
        let json = serde_json::to_string(&meta).unwrap();
        let deserialized: MemoryMetadata = serde_json::from_str(&json).unwrap();
        assert_eq!(deserialized.project, "test");
        assert_eq!(deserialized.memory_type, MemoryType::Solution);
    }
}
