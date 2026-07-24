use std::path::{Path, PathBuf};

use chrono::{DateTime, Utc};
use serde_json::Value;

use crate::brain::Brain;
use crate::ingest::Checkpoint;
use crate::{BrainError, MemorySource, MemoryType};

/// Default Perplexity exports directory.
pub fn default_exports_dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .unwrap_or(Path::new("."))
        .join("bootstrap")
        .join("perplexity_exports")
}

/// Build plain-text summary of a Perplexity thread (no LLM needed).
pub fn summarize_thread_text(title: &str, messages: &[Value]) -> String {
    let mut parts = vec![format!("Perplexity thread: {title}")];
    for msg in messages.iter().take(6) {
        let role = msg["role"].as_str().unwrap_or("");
        let content = msg["content"].as_str().unwrap_or("");
        let preview = if content.len() > 200 { &content[..200] } else { content };
        match role {
            "user" => parts.push(format!("Q: {preview}")),
            "assistant" => parts.push(format!("A: {preview}")),
            _ => {}
        }
    }
    parts.join(" | ")
}

/// Extract a memory record from a Perplexity exported thread JSON.
///
/// Returns `(thread_id, title, summary, tags, created_at)`. `created_at`
/// prefers the thread's `created_at` / `updated_at` field so the saved memory
/// reflects event time, falling back to file mtime.
pub fn extract_thread_record(
    path: &Path,
) -> Result<(String, String, String, String, Option<DateTime<Utc>>), BrainError> {
    let text = std::fs::read_to_string(path)?;
    let val: Value = serde_json::from_str(&text)
        .unwrap_or_else(|_| Value::Object(Default::default()));

    let thread_id = val["id"]
        .as_str()
        .unwrap_or_else(|| path.file_stem().and_then(|s| s.to_str()).unwrap_or("unknown"))
        .to_string();
    let title = val["title"]
        .as_str()
        .unwrap_or(&format!("Thread {thread_id}"))
        .to_string();
    let messages = val["messages"].as_array().cloned().unwrap_or_default();

    // Build tags from title words (4+ chars, first 6)
    let tags: Vec<String> = title
        .split_whitespace()
        .filter(|w| w.len() > 3)
        .take(6)
        .map(|w| w.to_lowercase())
        .collect();
    let tags_str = tags.join(",");

    let event_time = val["created_at"]
        .as_str()
        .or_else(|| val["updated_at"].as_str())
        .and_then(|s| DateTime::parse_from_rfc3339(s).ok())
        .map(|dt| dt.with_timezone(&Utc))
        .or_else(|| {
            std::fs::metadata(path)
                .ok()
                .and_then(|m| m.modified().ok())
                .map(DateTime::<Utc>::from)
        });

    let summary = summarize_thread_text(&title, &messages);
    Ok((thread_id, title, summary, tags_str, event_time))
}

/// Ingest all Perplexity thread JSON files from `exports_dir` into `brain`.
pub fn ingest_perplexity(
    brain: &Brain,
    exports_dir: &Path,
    checkpoint_path: &Path,
) -> Result<usize, BrainError> {
    let mut checkpoint = Checkpoint::load(checkpoint_path);
    let mut ingested = 0;

    let mut files: Vec<PathBuf> = walkdir(exports_dir)?;
    files.sort();

    eprintln!(
        "Found {} thread files in {}",
        files.len(),
        exports_dir.display()
    );

    for (i, path) in files.iter().enumerate() {
        let stem = path.file_stem().and_then(|s| s.to_str()).unwrap_or("");

        if checkpoint.contains(stem) {
            continue;
        }

        eprintln!(
            "  [{}/{}] {}...",
            i + 1,
            files.len(),
            path.file_name().unwrap_or_default().to_string_lossy()
        );

        match extract_thread_record(&path) {
            Ok((_thread_id, title, text, tags, event_time)) => {
                brain.save_memory(
                    &text,
                    MemoryType::ProjectContext,
                    &tags.split(',').collect::<Vec<_>>(),
                    "general",
                    None,
                    MemorySource::Perplexity,
                    None,
                    Some(&title),
                    event_time,
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

        if (i + 1) % 10 == 0 {
            checkpoint.save()?;
        }
    }

    checkpoint.save()?;
    Ok(ingested)
}

fn walkdir(dir: &Path) -> Result<Vec<PathBuf>, BrainError> {
    if !dir.exists() {
        return Ok(Vec::new());
    }
    let mut out = Vec::new();
    collect_json(dir, &mut out)?;
    Ok(out)
}

fn collect_json(dir: &Path, out: &mut Vec<PathBuf>) -> Result<(), BrainError> {
    for entry in std::fs::read_dir(dir)? {
        let path = entry?.path();
        if path.is_dir() {
            collect_json(&path, out)?;
        } else if path.extension().and_then(|e| e.to_str()) == Some("json") {
            out.push(path);
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    fn write_thread(dir: &Path, name: &str, id: &str, title: &str) {
        let data = serde_json::json!({
            "id": id,
            "title": title,
            "messages": [
                {"role": "user", "content": "What is the best database for vectors?"},
                {"role": "assistant", "content": "ChromaDB is popular for semantic search."}
            ]
        });
        std::fs::write(dir.join(name), data.to_string()).unwrap();
    }

    #[test]
    fn extract_thread_record_returns_title_and_summary() {
        let dir = TempDir::new().unwrap();
        write_thread(dir.path(), "thread1.json", "t-001", "Vector Databases Overview");
        let (id, title, text, tags, event_time) =
            extract_thread_record(&dir.path().join("thread1.json")).unwrap();
        assert_eq!(id, "t-001");
        assert_eq!(title, "Vector Databases Overview");
        assert!(text.contains("Vector Databases Overview"));
        assert!(text.contains("ChromaDB"));
        assert!(!tags.is_empty());
        // No created_at in fixture → falls back to file mtime.
        assert!(event_time.is_some());
    }

    #[test]
    fn summarize_thread_text_includes_qa_pairs() {
        let messages = vec![
            serde_json::json!({"role": "user", "content": "What is Rust?"}),
            serde_json::json!({"role": "assistant", "content": "A systems programming language."}),
        ];
        let text = summarize_thread_text("Rust Overview", &messages);
        assert!(text.contains("Q: What is Rust?"));
        assert!(text.contains("A: A systems programming language."));
    }

    #[test]
    fn extract_handles_missing_fields_gracefully() {
        let dir = TempDir::new().unwrap();
        let path = dir.path().join("empty.json");
        std::fs::write(&path, "{}").unwrap();
        let result = extract_thread_record(&path);
        assert!(result.is_ok()); // should not panic
    }

    #[test]
    fn walkdir_finds_nested_json_files() {
        let dir = TempDir::new().unwrap();
        let subdir = dir.path().join("sub");
        std::fs::create_dir(&subdir).unwrap();
        write_thread(&subdir, "nested.json", "n-1", "Nested Thread");
        let files = walkdir(dir.path()).unwrap();
        assert_eq!(files.len(), 1);
    }
}
