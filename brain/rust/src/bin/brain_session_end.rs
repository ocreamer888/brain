//! Stop hook — exports session, ingests transcript, triggers reflection.
//!
//! Claude Code sends JSON via stdin:
//! {"session_id": "...", "transcript_path": "...", "cwd": "...", ...}
//!
//! Configure in ~/.claude/settings.json:
//! ```json
//! "Stop": [{"hooks": [{"type": "command",
//!   "command": "/path/to/brain_session_end"}]}]
//! ```

use std::io::Read;

use brain::brain::Brain;
use brain::config::{anthropic_api_key, brain_config_from_env};
use brain::embedder::{embedder_from_env, EmbedderBackend};
use brain::summarizer::AnthropicClient;
use brain::{MemorySource, MemoryType};
use serde_json::Value;

fn main() {
    if let Err(e) = run() {
        eprintln!("[BRAIN] SessionEnd failed (non-fatal): {e}");
    }
}

fn run() -> Result<(), Box<dyn std::error::Error>> {
    let mut raw = String::new();
    std::io::stdin().read_to_string(&mut raw)?;
    let context: Value = serde_json::from_str(raw.trim()).unwrap_or_default();

    let session_id = context["session_id"].as_str().unwrap_or("unknown");
    let transcript_path = context["transcript_path"].as_str();
    let cwd = context["cwd"].as_str().unwrap_or(".");
    let project = std::path::Path::new(cwd)
        .file_name()
        .and_then(|n| n.to_str())
        .unwrap_or("unknown");

    let config = brain_config_from_env();
    let embedder = make_embedder()?;
    let mut brain_instance = Brain::open(config, embedder)?;

    if let Some(key) = anthropic_api_key() {
        brain_instance = brain_instance.with_llm_client(Box::new(AnthropicClient::new(key)));
    }

    // Read transcript JSONL and ingest each user/assistant message pair
    let mut message_count = 0;
    if let Some(path) = transcript_path {
        let path = std::path::Path::new(path);
        if path.exists() {
            let content = std::fs::read_to_string(path)?;
            let messages: Vec<(String, String)> = parse_transcript(&content);
            message_count = messages.len();

            for (role, text) in &messages {
                if text.trim().is_empty() {
                    continue;
                }
                let preview = if text.len() > 300 { &text[..300] } else { text };
                let content = format!("[{role}] {preview}");
                let row_title = format!(
                    "Transcript {}/{}",
                    session_id.chars().take(10).collect::<String>(),
                    role
                );
                brain_instance.save_memory(
                    &content,
                    MemoryType::Conversation,
                    &["session", project],
                    project,
                    Some(session_id),
                    MemorySource::ClaudeCodeSession,
                    None,
                    Some(&row_title),
                    None,
                    None,
                    None,
                    None,
                    None,
                )?;
            }
        }
    }

    // Trigger reflection if LLM is available
    let reflection_msg = if brain_instance.trigger_reflection().is_ok() {
        "reflection done"
    } else {
        "no LLM for reflection"
    };

    eprintln!(
        "[BRAIN] Session '{session_id}' ended. {message_count} messages ingested. {reflection_msg}."
    );

    Ok(())
}

/// Parse a Claude Code JSONL transcript into (role, content) pairs.
fn parse_transcript(jsonl: &str) -> Vec<(String, String)> {
    let mut messages = Vec::new();
    for line in jsonl.lines() {
        let line = line.trim();
        if line.is_empty() {
            continue;
        }
        let Ok(val): Result<Value, _> = serde_json::from_str(line) else {
            continue;
        };
        let msg_type = val["type"].as_str().unwrap_or("");
        if msg_type != "user" && msg_type != "assistant" {
            continue;
        }
        let content = &val["message"]["content"];
        let text = match content {
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
            _ => continue,
        };
        messages.push((msg_type.to_string(), text));
    }
    messages
}

fn make_embedder() -> Result<Box<dyn EmbedderBackend>, brain::BrainError> {
    embedder_from_env("[BRAIN]")
}

#[cfg(test)]
mod tests {
    use super::*;

    fn user_msg(text: &str) -> String {
        format!(r#"{{"type":"user","message":{{"content":"{text}"}}}}"#)
    }

    fn assistant_msg_parts(text: &str) -> String {
        format!(
            r#"{{"type":"assistant","message":{{"content":[{{"type":"text","text":"{text}"}}]}}}}"#
        )
    }

    #[test]
    fn parse_transcript_extracts_user_and_assistant() {
        let jsonl = format!("{}\n{}", user_msg("hello"), assistant_msg_parts("world"));
        let msgs = parse_transcript(&jsonl);
        assert_eq!(msgs.len(), 2);
        assert_eq!(msgs[0], ("user".to_string(), "hello".to_string()));
        assert_eq!(msgs[1], ("assistant".to_string(), "world".to_string()));
    }

    #[test]
    fn parse_transcript_skips_non_message_types() {
        let jsonl = r#"{"type":"summary","message":{"content":"irrelevant"}}"#;
        assert!(parse_transcript(jsonl).is_empty());
    }

    #[test]
    fn parse_transcript_skips_blank_lines() {
        let jsonl = format!("\n\n{}\n\n", user_msg("hi"));
        let msgs = parse_transcript(&jsonl);
        assert_eq!(msgs.len(), 1);
    }

    #[test]
    fn parse_transcript_skips_invalid_json() {
        let jsonl = "not-json\n".to_string() + &user_msg("valid");
        let msgs = parse_transcript(&jsonl);
        assert_eq!(msgs.len(), 1);
    }
}
