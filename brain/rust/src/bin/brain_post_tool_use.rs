//! PostToolUse hook — saves a memory after significant tool calls.
//!
//! Claude Code sends JSON via stdin:
//! {"tool_name": "Edit", "tool_input": {...}, "tool_response": "..."}
//!
//! Configure in ~/.claude/settings.json:
//! ```json
//! "PostToolUse": [{"matcher": "Edit|Write|Bash|Agent", "hooks": [{"type": "command",
//!   "command": "/path/to/brain_post_tool_use"}]}]
//! ```

use std::env;
use std::io::Read;

use brain::brain::Brain;
use brain::config::{anthropic_api_key, brain_config_from_env};
use brain::embedder::{embedder_from_env, EmbedderBackend};
use brain::summarizer::AnthropicClient;
use brain::{MemorySource, MemoryType};
use serde_json::Value;

const MEMORABLE_TOOLS: &[&str] = &["Edit", "Write", "Bash", "Agent"];

fn symbols_to_tags(path: &str, content: &str) -> Vec<String> {
    brain::symbols::extract_symbols(path, content)
        .into_iter()
        .map(|s| format!("sym:{s}"))
        .collect()
}

fn append_symbol_tags(tool_name: &str, tool_input: &Value, tags: &mut Vec<String>) {
    if tool_name != "Edit" && tool_name != "Write" {
        return;
    }
    let Some(path) = tool_input["file_path"].as_str() else {
        return;
    };
    let Some(content) = tool_input["new_string"]
        .as_str()
        .or_else(|| tool_input["content"].as_str())
    else {
        return;
    };
    tags.extend(symbols_to_tags(path, content));
}

fn main() {
    if let Err(e) = run() {
        eprintln!("[BRAIN] PostToolUse failed (non-fatal): {e}");
    }
}

fn run() -> Result<(), Box<dyn std::error::Error>> {
    let mut raw = String::new();
    std::io::stdin().read_to_string(&mut raw)?;
    let raw = raw.trim();
    if raw.is_empty() {
        return Ok(());
    }

    let context: Value = serde_json::from_str(raw)?;
    let tool_name = context["tool_name"].as_str().unwrap_or("");

    if !MEMORABLE_TOOLS.contains(&tool_name) {
        return Ok(());
    }

    let cwd = env::current_dir().unwrap_or_default();
    let project = cwd.file_name()
        .and_then(|n| n.to_str())
        .unwrap_or("unknown")
        .to_string();

    let tool_input = &context["tool_input"];
    let tool_response = context["tool_response"].as_str().unwrap_or("");

    let (description, memory_type, mut tags) = match tool_name {
        "Edit" => {
            let path = tool_input["file_path"].as_str().unwrap_or("?");
            let change = tool_input["new_string"].as_str().unwrap_or("");
            let change = if change.len() > 200 { &change[..200] } else { change };
            (
                format!("Edited {path}: {change}"),
                MemoryType::Solution,
                vec!["edit".to_string(), project.clone()],
            )
        }
        "Write" => {
            let path = tool_input["file_path"].as_str().unwrap_or("?");
            (
                format!("Wrote {path}"),
                MemoryType::Solution,
                vec!["write".to_string(), project.clone()],
            )
        }
        "Bash" => {
            let cmd = tool_input["command"].as_str().unwrap_or("");
            let cmd = if cmd.len() > 200 { &cmd[..200] } else { cmd };
            (
                format!("Ran command: {cmd}"),
                MemoryType::Pattern,
                vec!["bash".to_string(), project.clone()],
            )
        }
        "Agent" => {
            let desc = tool_input["description"].as_str().unwrap_or("");
            let desc = if desc.len() > 200 { &desc[..200] } else { desc };
            (
                format!("Dispatched agent: {desc}"),
                MemoryType::Decision,
                vec!["agent".to_string(), project.clone()],
            )
        }
        _ => return Ok(()),
    };

    append_symbol_tags(tool_name, tool_input, &mut tags);

    let config = brain_config_from_env();
    let embedder = make_embedder()?;
    let mut brain_instance = Brain::open(config, embedder)?;

    // If LLM available, summarize the exchange for a richer memory
    let content = if let Some(key) = anthropic_api_key() {
        use brain::summarizer::Summarizer;
        let llm = AnthropicClient::new(&key);
        brain_instance = brain_instance.with_llm_client(Box::new(AnthropicClient::new(key)));
        let summarizer = Summarizer::new(llm);
        let response_preview = if tool_response.len() > 500 { &tool_response[..500] } else { tool_response };
        summarizer
            .summarize_exchange(&description, response_preview)
            .unwrap_or(description)
    } else {
        description
    };

    let tag_refs: Vec<&str> = tags.iter().map(String::as_str).collect();
    let mem_title = format!("{tool_name} · {project}");
    brain_instance.save_memory(
        &content,
        memory_type,
        &tag_refs,
        &project,
        None,
        MemorySource::ClawCode,
        None,
        Some(&mem_title),
        None,
        None,
        None,
        None,
        None,
    )?;

    eprintln!("[BRAIN] Saved memory for {tool_name} in '{project}'");
    Ok(())
}

fn make_embedder() -> Result<Box<dyn EmbedderBackend>, brain::BrainError> {
    embedder_from_env("[BRAIN]")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn symbols_become_tags() {
        let tags = symbols_to_tags("lib.rs", "fn foo() {}");
        assert!(tags.contains(&"sym:foo".to_string()));
    }

    #[test]
    fn memorable_tools_contains_expected_entries() {
        // Changing this list changes which tool calls get saved to brain.
        // Test fails when someone adds/removes a tool without reviewing the impact.
        let expected = ["Edit", "Write", "Bash", "Agent"];
        for tool in &expected {
            assert!(
                MEMORABLE_TOOLS.contains(tool),
                "MEMORABLE_TOOLS missing expected tool: {tool}"
            );
        }
        assert_eq!(
            MEMORABLE_TOOLS.len(),
            expected.len(),
            "MEMORABLE_TOOLS length changed — update this test and review the impact"
        );
    }
}
