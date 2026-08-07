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

    /// Extraction confidence from the fact extractor (0.0–1.0).
    /// Stored but NOT included in retrieval scoring until Phase 6 calibration.
    #[serde(default = "default_salience")]
    pub salience: f64,

    /// ID of the fact that supersedes this one (set on UPDATE/MERGE by curator).
    /// Superseded facts stay in DB for audit; excluded from search by default.
    #[serde(default)]
    pub superseded_by: Option<String>,

    /// Extractor model + prompt version tag (e.g. "openrouter/claude-sonnet-4-5/v1").
    /// Used to track extraction quality across prompt iterations.
    #[serde(default)]
    pub derived_from: Option<String>,
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
}

impl Default for SearchFilter {
    fn default() -> Self {
        Self {
            memory_type: None,
            project: None,
            exclude_superseded: true,
            alpha: None,
            graph_expand: false,
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
            superseded_by: None,
            derived_from: None,
        };
        let json = serde_json::to_string(&meta).unwrap();
        let deserialized: MemoryMetadata = serde_json::from_str(&json).unwrap();
        assert_eq!(deserialized.project, "test");
        assert_eq!(deserialized.memory_type, MemoryType::Solution);
    }
}
