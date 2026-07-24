//! Phase 6 data migration: import memories exported from Python ChromaDB into
//! the Rust SQLite store + vector index.
//!
//! Each JSONL line must be:
//! ```json
//! {"id":"...","content":"...","metadata":{...},"embedding":[...]}
//! ```
//!
//! The metadata object must contain at minimum: `type`, `project`, `tags`,
//! `timestamp`, `source`. `session_id` and `importance` default if missing.
//! `file_path`, `thread_id`, `title` are optional.

use std::io::{BufRead, BufReader};
use std::path::Path;

use chrono::{DateTime, Utc};
use serde::Deserialize;
use serde_json::Value;

use crate::store::MetadataStore;
use crate::{BrainError, Memory, MemoryMetadata, MemorySource, MemoryType};

#[derive(Debug, Deserialize)]
struct MigrateRecord {
    id: String,
    content: String,
    metadata: Value,
    embedding: Option<Vec<f32>>,
}

/// Result counters from a migration run.
#[derive(Debug, Default)]
pub struct MigrateResult {
    /// Records successfully upserted into the store (and indexed if embedding present).
    pub imported: usize,
    /// Records upserted into the store but skipped from the vector index (no embedding).
    pub no_embedding: usize,
    /// Lines that could not be parsed or stored.
    pub errors: usize,
}

/// Read JSONL from `input_path`, upsert every record into `store`.
/// If a record has an embedding, it is stored in the `embedding` column atomically.
///
/// Idempotent: re-running with the same file only overwrites; it never duplicates.
/// Returns aggregated counters. On per-record errors the function continues and
/// increments `result.errors` rather than aborting.
pub fn migrate_from_jsonl(
    input_path: impl AsRef<Path>,
    store: &MetadataStore,
) -> Result<MigrateResult, BrainError> {
    let file = std::fs::File::open(input_path)?;
    let reader = BufReader::new(file);

    let mut result = MigrateResult::default();

    for (line_no, line_result) in reader.lines().enumerate() {
        let line = match line_result {
            Ok(l) => l,
            Err(e) => {
                eprintln!("[migrate] line {}: io error: {e}", line_no + 1);
                result.errors += 1;
                continue;
            }
        };

        let line = line.trim();
        if line.is_empty() {
            continue;
        }

        let record: MigrateRecord = match serde_json::from_str(line) {
            Ok(r) => r,
            Err(e) => {
                eprintln!("[migrate] line {}: parse error: {e}", line_no + 1);
                result.errors += 1;
                continue;
            }
        };

        let id = record.id.clone();
        let embedding = record.embedding.clone();

        let metadata = match parse_metadata(&record.metadata) {
            Ok(m) => m,
            Err(e) => {
                eprintln!(
                    "[migrate] line {}: metadata parse error for id={id}: {e}",
                    line_no + 1
                );
                result.errors += 1;
                continue;
            }
        };

        let memory = Memory {
            id: record.id,
            content: record.content,
            metadata,
            embedding: record.embedding,
        };

        if let Err(e) = store.upsert_memory(&memory) {
            eprintln!("[migrate] line {}: store error for id={id}: {e}", line_no + 1);
            result.errors += 1;
            continue;
        }

        if let Some(ref emb) = embedding {
            store.update_embedding(&id, emb)?;
            result.imported += 1;
        } else {
            result.no_embedding += 1;
            result.imported += 1;
        }

        if (result.imported + result.no_embedding) % 200 == 0 {
            eprintln!(
                "[migrate] {} imported so far ({} errors)…",
                result.imported, result.errors
            );
        }
    }

    Ok(result)
}

fn parse_metadata(v: &Value) -> Result<MemoryMetadata, BrainError> {
    let obj = v
        .as_object()
        .ok_or_else(|| BrainError::Json(serde_json::Error::io(std::io::Error::new(
            std::io::ErrorKind::InvalidData,
            "metadata must be object",
        ))))?;

    let memory_type = parse_memory_type(obj.get("type"));
    let source = parse_memory_source(obj.get("source"));
    let project = get_string(obj.get("project")).unwrap_or_else(|| "general".to_string());
    let tags = get_string(obj.get("tags")).unwrap_or_default();
    let session_id = get_string(obj.get("session_id")).unwrap_or_default();
    let importance = parse_importance(obj.get("importance"));
    let file_path = get_opt_string(obj.get("file_path"));
    let thread_id = get_opt_string(obj.get("thread_id"));
    let title = get_opt_string(obj.get("title"));
    let parent_id = get_opt_string(obj.get("parent_id"));
    let superseded_by = get_opt_string(obj.get("superseded_by"));
    let derived_from = get_opt_string(obj.get("derived_from"));
    let salience = match obj.get("salience") {
        Some(Value::Number(n)) => n.as_f64().unwrap_or(0.5),
        Some(Value::String(s)) => s.parse::<f64>().unwrap_or(0.5),
        _ => 0.5,
    };
    let event_time = if let Some(s) = get_string(obj.get("event_time")) {
        DateTime::parse_from_rfc3339(&s)
            .map(|dt| Some(dt.with_timezone(&Utc)))
            .unwrap_or(None)
    } else {
        None
    };

    let timestamp = parse_timestamp(obj.get("timestamp"))?;

    Ok(MemoryMetadata {
        memory_type,
        project,
        tags,
        timestamp,
        source,
        session_id,
        importance,
        file_path,
        thread_id,
        title,
        parent_id,
        event_time,
        salience,
        superseded_by,
        derived_from,
    })
}

fn parse_memory_type(v: Option<&Value>) -> MemoryType {
    match get_string(v).as_deref() {
        Some("solution") => MemoryType::Solution,
        Some("decision") => MemoryType::Decision,
        Some("conversation") => MemoryType::Conversation,
        Some("pattern") => MemoryType::Pattern,
        Some("project_context") => MemoryType::ProjectContext,
        Some("error_lesson") => MemoryType::ErrorLesson,
        Some("fact") => MemoryType::Fact,
        Some("episode") => MemoryType::Episode,
        // Legacy/foreign values default to conversation to keep migration lossless.
        _ => MemoryType::Conversation,
    }
}

fn parse_memory_source(v: Option<&Value>) -> MemorySource {
    match get_string(v).as_deref() {
        Some("claude_code_session") => MemorySource::ClaudeCodeSession,
        Some("reflection") => MemorySource::Reflection,
        Some("cursor_history") => MemorySource::CursorHistory,
        Some("claw_code") => MemorySource::ClawCode,
        Some("perplexity") => MemorySource::Perplexity,
        Some("obsidian") => MemorySource::Obsidian,
        Some("obsidian_books") => MemorySource::ObsidianBooks,
        _ => MemorySource::CursorHistory,
    }
}

fn parse_importance(v: Option<&Value>) -> f64 {
    match v {
        Some(Value::Number(n)) => n.as_f64().unwrap_or(0.5),
        Some(Value::String(s)) => s.parse::<f64>().unwrap_or(0.5),
        _ => 0.5,
    }
}

fn parse_timestamp(v: Option<&Value>) -> Result<DateTime<Utc>, BrainError> {
    let s = get_string(v).ok_or_else(|| {
        BrainError::Json(serde_json::Error::io(std::io::Error::new(
            std::io::ErrorKind::InvalidData,
            "missing timestamp",
        )))
    })?;
    DateTime::parse_from_rfc3339(&s)
        .map(|dt| dt.with_timezone(&Utc))
        .map_err(|e| BrainError::Json(serde_json::Error::io(std::io::Error::new(
            std::io::ErrorKind::InvalidData,
            format!("invalid timestamp: {e}"),
        ))))
}

fn get_string(v: Option<&Value>) -> Option<String> {
    v.and_then(|x| x.as_str().map(ToString::to_string))
}

fn get_opt_string(v: Option<&Value>) -> Option<String> {
    match v {
        Some(Value::Null) | None => None,
        Some(Value::String(s)) => Some(s.to_string()),
        _ => None,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::store::MetadataStore;
    use std::io::Write;
    use tempfile::NamedTempFile;

    fn jsonl_line(id: &str, content: &str) -> String {
        serde_json::json!({
            "id": id,
            "content": content,
            "metadata": {
                "type": "solution",
                "project": "test",
                "tags": "rust,test",
                "timestamp": "2026-01-01T00:00:00+00:00",
                "source": "claude_code_session",
                "session_id": "sess-1",
                "importance": 0.7
            },
            "embedding": [0.1f32, 0.2f32, 0.3f32]
        })
        .to_string()
    }

    #[test]
    fn migrate_inserts_records() {
        let store = MetadataStore::open_in_memory().unwrap();

        let mut tmp = NamedTempFile::new().unwrap();
        writeln!(tmp, "{}", jsonl_line("id-1", "first memory")).unwrap();
        writeln!(tmp, "{}", jsonl_line("id-2", "second memory")).unwrap();

        let result = migrate_from_jsonl(tmp.path(), &store).unwrap();

        assert_eq!(result.imported, 2);
        assert_eq!(result.errors, 0);
        assert_eq!(store.count_memories().unwrap(), 2);
        assert_eq!(store.get_embeddings_for_index().unwrap().len(), 2);
    }

    #[test]
    fn migrate_is_idempotent() {
        let store = MetadataStore::open_in_memory().unwrap();

        let mut tmp = NamedTempFile::new().unwrap();
        writeln!(tmp, "{}", jsonl_line("id-1", "hello")).unwrap();

        migrate_from_jsonl(tmp.path(), &store).unwrap();
        migrate_from_jsonl(tmp.path(), &store).unwrap();

        assert_eq!(store.count_memories().unwrap(), 1);
        assert_eq!(store.get_embeddings_for_index().unwrap().len(), 1);
    }

    #[test]
    fn migrate_skips_bad_lines_and_continues() {
        let store = MetadataStore::open_in_memory().unwrap();

        let mut tmp = NamedTempFile::new().unwrap();
        writeln!(tmp, "not valid json {{{{").unwrap();
        writeln!(tmp, "{}", jsonl_line("id-ok", "good record")).unwrap();

        let result = migrate_from_jsonl(tmp.path(), &store).unwrap();

        assert_eq!(result.imported, 1);
        assert_eq!(result.errors, 1);
        assert_eq!(store.count_memories().unwrap(), 1);
    }

    #[test]
    fn migrate_handles_no_embedding() {
        let store = MetadataStore::open_in_memory().unwrap();

        let line = serde_json::json!({
            "id": "no-emb",
            "content": "no embedding here",
            "metadata": {
                "type": "decision",
                "project": "test",
                "tags": "",
                "timestamp": "2026-01-01T00:00:00+00:00",
                "source": "reflection",
                "session_id": "",
                "importance": 0.5
            },
            "embedding": null
        })
        .to_string();

        let mut tmp = NamedTempFile::new().unwrap();
        writeln!(tmp, "{line}").unwrap();

        let result = migrate_from_jsonl(tmp.path(), &store).unwrap();

        assert_eq!(result.imported, 1);
        assert_eq!(result.no_embedding, 1);
        assert_eq!(store.get_embeddings_for_index().unwrap().len(), 0);
        assert_eq!(store.count_memories().unwrap(), 1);
    }
}
