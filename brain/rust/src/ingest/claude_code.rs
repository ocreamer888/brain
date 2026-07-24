use std::path::{Path, PathBuf};

use chrono::{DateTime, Utc};
use serde_json::Value;

use crate::brain::Brain;
use crate::ingest::Checkpoint;
use crate::{BrainError, MemorySource, MemoryType};

/// Default sessions export directory (mirrors Python brain location).
pub fn default_sessions_dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .unwrap_or(Path::new("."))
        .join("bootstrap")
        .join("sessions_export")
}

/// Required fields for a valid session export JSON.
const REQUIRED_FIELDS: &[&str] = &["session_id", "project", "cwd", "ended_at", "messages"];

pub fn validate_session_json(path: &Path) -> Result<(), String> {
    let text = std::fs::read_to_string(path).map_err(|e| e.to_string())?;
    let val: Value = serde_json::from_str(&text).map_err(|e| e.to_string())?;
    for field in REQUIRED_FIELDS {
        if val.get(field).is_none() {
            return Err(format!("missing field: {field}"));
        }
    }
    Ok(())
}

/// Extract the text content from a session JSON for embedding.
///
/// Returns `(session_id, project, text, ended_at)`. `ended_at` is the RFC3339
/// string from the session JSON (event time); callers should parse it and pass
/// to `save_memory` so the memory's timestamp reflects when the session ran,
/// not when we ingested it.
pub fn extract_session_text(
    path: &Path,
) -> Result<(String, String, String, Option<DateTime<Utc>>), BrainError> {
    let text = std::fs::read_to_string(path)?;
    let val: Value = serde_json::from_str(&text)?;

    let session_id = val["session_id"].as_str().unwrap_or("unknown").to_string();
    let project = val["project"].as_str().unwrap_or("unknown").to_string();
    let cwd = val["cwd"].as_str().unwrap_or("").to_string();
    let ended_at = val["ended_at"].as_str().unwrap_or("").to_string();
    let ended_at_ts = if ended_at.is_empty() {
        None
    } else {
        DateTime::parse_from_rfc3339(&ended_at)
            .ok()
            .map(|dt| dt.with_timezone(&Utc))
    };
    let message_count = val["message_count"].as_u64().unwrap_or(0);

    let mut parts = vec![
        format!("Claude Code session: {project}"),
        format!("Ended: {ended_at}"),
        format!("CWD: {cwd}"),
    ];

    if message_count > 0 {
        parts.push(format!("Total messages: {message_count}"));
    }

    // Extract up to 10 user/assistant messages
    let mut shown = 0;
    if let Some(messages) = val["messages"].as_array() {
        for msg in messages {
            if shown >= 10 {
                break;
            }
            let (role, content) = if let (Some(t), Some(inner)) = (
                msg["type"].as_str(),
                msg.get("message"),
            ) {
                if t != "user" && t != "assistant" {
                    continue;
                }
                let role = inner["role"].as_str().unwrap_or(t).to_string();
                let content = extract_content_text(&inner["content"]);
                (role, content)
            } else if let Some(role) = msg["role"].as_str() {
                let content = extract_content_text(&msg["content"]);
                (role.to_string(), content)
            } else {
                continue;
            };

            if !content.is_empty() {
                let preview = if content.len() > 200 { &content[..200] } else { &content };
                parts.push(format!("[{role}] {preview}"));
                shown += 1;
            }
        }
    }

    let full_text = parts.join(" | ");
    Ok((session_id, project, full_text, ended_at_ts))
}

fn extract_content_text(content: &Value) -> String {
    match content {
        Value::String(s) => s.clone(),
        Value::Array(parts) => parts
            .iter()
            .filter_map(|p| {
                if p["type"].as_str() == Some("text") {
                    p["text"].as_str().map(str::to_string)
                } else {
                    None
                }
            })
            .collect::<Vec<_>>()
            .join(" "),
        _ => String::new(),
    }
}

/// Ingest all new session JSON files from `sessions_dir` into `brain`.
///
/// Uses a checkpoint file at `checkpoint_path` to skip already-processed sessions.
/// Returns the number of new sessions ingested.
pub fn ingest_sessions(
    brain: &Brain,
    sessions_dir: &Path,
    checkpoint_path: &Path,
) -> Result<usize, BrainError> {
    let mut checkpoint = Checkpoint::load(checkpoint_path);
    let mut ingested = 0;

    let mut files: Vec<PathBuf> = std::fs::read_dir(sessions_dir)
        .map_err(|e| BrainError::Io(e))?
        .filter_map(|e| e.ok())
        .map(|e| e.path())
        .filter(|p| p.extension().and_then(|e| e.to_str()) == Some("json"))
        .collect();
    files.sort();

    eprintln!(
        "Found {} session files in {}",
        files.len(),
        sessions_dir.display()
    );

    for (i, path) in files.iter().enumerate() {
        let stem = path.file_stem().and_then(|s| s.to_str()).unwrap_or("");

        if checkpoint.contains(stem) {
            eprintln!("  [{}/{}] {} (already processed)", i + 1, files.len(), path.file_name().unwrap_or_default().to_string_lossy());
            continue;
        }

        eprintln!("  [{}/{}] {}...", i + 1, files.len(), path.file_name().unwrap_or_default().to_string_lossy());

        // Validate
        if let Err(e) = validate_session_json(&path) {
            eprintln!("    INVALID: {e}");
            checkpoint.mark(stem);
            continue;
        }

        match extract_session_text(&path) {
            Ok((session_id, project, text, ended_at_ts)) => {
                // Preserve event time: use the session's ended_at, not ingest time.
                let ingest_title = format!(
                    "Claude Code — {} ({})",
                    project,
                    session_id.chars().take(12).collect::<String>()
                );
                brain.save_memory(
                    &text,
                    MemoryType::Conversation,
                    &["claude_code", &project],
                    &project,
                    Some(&session_id),
                    MemorySource::ClaudeCodeSession,
                    None,
                    Some(&ingest_title),
                    ended_at_ts,
                    None,
                    None,
                    None,
                    None,
                )?;

                ingested += 1;
                checkpoint.mark(stem);
            }
            Err(e) => {
                eprintln!("    error: {e}");
                checkpoint.mark(stem);
            }
        }

        // Save checkpoint every 10 records
        if (i + 1) % 10 == 0 {
            checkpoint.save()?;
        }
    }

    checkpoint.save()?;
    Ok(ingested)
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    fn write_session(dir: &Path, name: &str, session_id: &str) {
        let data = serde_json::json!({
            "session_id": session_id,
            "project": "test_project",
            "cwd": "/test/path",
            "ended_at": "2026-04-04T10:00:00Z",
            "message_count": 2,
            "messages": [
                {"type": "user", "message": {"role": "user", "content": "fix the bug"}},
                {"type": "assistant", "message": {"role": "assistant", "content": "I found it in tokenizer.py"}}
            ]
        });
        std::fs::write(dir.join(name), data.to_string()).unwrap();
    }

    #[test]
    fn validate_accepts_valid_session() {
        let dir = TempDir::new().unwrap();
        write_session(dir.path(), "session_a.json", "abc-123");
        assert!(validate_session_json(&dir.path().join("session_a.json")).is_ok());
    }

    #[test]
    fn validate_rejects_missing_fields() {
        let dir = TempDir::new().unwrap();
        let path = dir.path().join("bad.json");
        std::fs::write(&path, r#"{"session_id": "x"}"#).unwrap();
        assert!(validate_session_json(&path).is_err());
    }

    #[test]
    fn extract_text_includes_messages() {
        let dir = TempDir::new().unwrap();
        write_session(dir.path(), "session_a.json", "abc-123");
        let (session_id, project, text, ended_at) =
            extract_session_text(&dir.path().join("session_a.json")).unwrap();
        assert_eq!(session_id, "abc-123");
        assert_eq!(project, "test_project");
        assert!(text.contains("fix the bug"));
        assert!(text.contains("tokenizer.py"));
        assert!(ended_at.is_some(), "ended_at should parse from fixture");
    }

    #[test]
    fn checkpoint_skips_processed() {
        let dir = TempDir::new().unwrap();
        let cp_path = dir.path().join("checkpoint.json");

        write_session(dir.path(), "session_a.json", "abc-1");
        write_session(dir.path(), "session_b.json", "abc-2");

        // Mark session_a as already processed
        std::fs::write(
            &cp_path,
            r#"{"processed_ids": ["session_a"]}"#,
        ).unwrap();

        let checkpoint = Checkpoint::load(&cp_path);
        assert!(checkpoint.contains("session_a"));
        assert!(!checkpoint.contains("session_b"));
    }
}
