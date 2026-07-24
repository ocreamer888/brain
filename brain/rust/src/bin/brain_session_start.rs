//! SessionStart hook — prints relevant memories at session start.
//!
//! Claude Code calls this at the beginning of every session.
//! Stdout is injected into the session context (visible to Claude).
//! Stderr is for diagnostics only.
//!
//! Configure in ~/.claude/settings.json:
//! ```json
//! "SessionStart": [{"hooks": [{"type": "command",
//!   "command": "/path/to/brain_session_start"}]}]
//! ```

use std::env;

use brain::brain::Brain;
use brain::config::{anthropic_api_key, brain_config_from_env};
use brain::embedder::{embedder_from_env, EmbedderBackend};
use brain::summarizer::AnthropicClient;

fn main() {
    if let Err(e) = run() {
        eprintln!("[BRAIN] SessionStart failed (non-fatal): {e}");
    }
}

fn run() -> Result<(), Box<dyn std::error::Error>> {
    let cwd = env::current_dir().unwrap_or_default();
    let project = cwd.file_name()
        .and_then(|n| n.to_str())
        .unwrap_or("unknown")
        .to_string();

    let config = brain_config_from_env();
    let embedder = make_embedder()?;
    let mut brain_instance = Brain::open(config, embedder)?;

    if let Some(key) = anthropic_api_key() {
        brain_instance = brain_instance.with_llm_client(Box::new(AnthropicClient::new(key)));
    }

    let memories = brain_instance.get_context(&project, Some(&project), 5)?;
    let stats = brain_instance.get_stats()?;

    if memories.is_empty() {
        println!("[BRAIN] No relevant memories for '{project}'. {} total.", stats.total_memories);
    } else {
        println!("\n[BRAIN] Loaded {} relevant memories for '{project}':", memories.len());
        for (i, m) in memories.iter().enumerate() {
            let type_str = format!("{:?}", m.metadata.memory_type).to_lowercase();
            let preview = if m.content.len() > 200 { &m.content[..200] } else { &m.content };
            println!("  [{}] ({type_str}) {preview}", i + 1);
        }
        println!("[BRAIN] Total: {} memories | {} sessions\n", stats.total_memories, stats.total_sessions);
    }

    Ok(())
}

fn make_embedder() -> Result<Box<dyn EmbedderBackend>, brain::BrainError> {
    embedder_from_env("[BRAIN]")
}
