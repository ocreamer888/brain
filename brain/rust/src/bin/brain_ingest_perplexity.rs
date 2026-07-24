//! Ingest Perplexity exported threads into the Rust brain.
//!
//! Mirrors python brain/bootstrap/06_ingest_perplexity.py.
//!
//! Usage:
//!   brain_ingest_perplexity [--exports-dir PATH]
//!
//! Env vars:
//!   BRAIN_DB_PATH, BRAIN_INDEX_PATH, BRAIN_ONNX_PATH, ANTHROPIC_API_KEY
//!   BRAIN_PERPLEXITY_DIR  — override Perplexity exports directory

use std::path::PathBuf;

use brain::brain::Brain;
use brain::config::{anthropic_api_key, brain_config_from_env};
use brain::embedder::{embedder_from_env, EmbedderBackend};
use brain::ingest::perplexity::{default_exports_dir, ingest_perplexity};
use brain::summarizer::AnthropicClient;

fn main() {
    let exports_dir = std::env::var("BRAIN_PERPLEXITY_DIR")
        .map(PathBuf::from)
        .unwrap_or_else(|_| default_exports_dir());

    let checkpoint_path = exports_dir
        .parent()
        .unwrap_or(&exports_dir)
        .join("checkpoint_perplexity_rust.json");

    let config = brain_config_from_env();
    let embedder = make_embedder();
    let mut brain_instance = match Brain::open(config, embedder) {
        Ok(b) => b,
        Err(e) => {
            eprintln!("[BRAIN] Failed to open brain: {e}");
            std::process::exit(1);
        }
    };

    if let Some(key) = anthropic_api_key() {
        brain_instance = brain_instance.with_llm_client(Box::new(AnthropicClient::new(key)));
    }

    let before = brain_instance.get_stats().map(|s| s.total_memories).unwrap_or(0);
    eprintln!("Brain memories before: {before}\n");

    match ingest_perplexity(&brain_instance, &exports_dir, &checkpoint_path) {
        Ok(ingested) => {
            let after = brain_instance.get_stats().map(|s| s.total_memories).unwrap_or(0);
            eprintln!("\nDone. Ingested: {ingested} threads. Memories: {before} → {after} (+{})", after.saturating_sub(before));
        }
        Err(e) => {
            eprintln!("[BRAIN] Ingest failed: {e}");
            std::process::exit(1);
        }
    }
}

fn make_embedder() -> Box<dyn EmbedderBackend> {
    match embedder_from_env("[BRAIN]") {
        Ok(e) => e,
        Err(e) => {
            eprintln!("[BRAIN] Failed to initialize embedder: {e}");
            std::process::exit(1);
        }
    }
}
