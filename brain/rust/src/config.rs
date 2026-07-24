/// Runtime configuration resolved from environment variables.
///
/// Environment variables:
///   BRAIN_DB_PATH       — SQLite database path (default: ~/.brain/brain.db)
///   BRAIN_LOG_SEARCH    — set to 1 to log search metrics (query length, result count, ms; no raw query)
///   BRAIN_REFLECTION_DISABLED — set to 1/true to freeze reflection writes/deletes
///   BRAIN_HYBRID_ALPHA  — weighted hybrid search alpha in [0,1] (default: 0.7)
///   BRAIN_ONNX_PATH     — ONNX model dir      (default: brain/rust/models/all-mpnet-base-v2-onnx)
///   BRAIN_EMBEDDER      — embedder mode       (default: onnx; options: onnx, mock)
///   ANTHROPIC_API_KEY   — API key for LLM summarization
///   OPENROUTER_API_KEY  — API key for LLM summarization (fallback)
use std::path::PathBuf;

use crate::brain::BrainConfig;

pub fn default_brain_dir() -> PathBuf {
    dirs_home().join(".brain")
}

fn dirs_home() -> PathBuf {
    std::env::var("HOME")
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from("."))
}

pub fn brain_config_from_env() -> BrainConfig {
    let brain_dir = default_brain_dir();
    std::fs::create_dir_all(&brain_dir).ok();

    let db_path = std::env::var("BRAIN_DB_PATH")
        .unwrap_or_else(|_| brain_dir.join("brain.db").to_string_lossy().into_owned());

    BrainConfig {
        db_path,
        embedding_dims: 768,
        reflect_every_n: 10,
        reflection_disabled: env_flag("BRAIN_REFLECTION_DISABLED"),
        hybrid_alpha: env_f32("BRAIN_HYBRID_ALPHA", 0.7).clamp(0.0, 1.0),
    }
}

fn env_flag(name: &str) -> bool {
    std::env::var(name)
        .map(|v| v == "1" || v.eq_ignore_ascii_case("true"))
        .unwrap_or(false)
}

fn env_f32(name: &str, default: f32) -> f32 {
    std::env::var(name)
        .ok()
        .and_then(|v| v.parse::<f32>().ok())
        .unwrap_or(default)
}

pub fn onnx_model_path() -> Option<String> {
    std::env::var("BRAIN_ONNX_PATH")
        .ok()
        .or_else(|| {
            Some(
                PathBuf::from(env!("CARGO_MANIFEST_DIR"))
                    .join("models")
                    .join("all-mpnet-base-v2-onnx")
                    .to_string_lossy()
                    .into_owned(),
            )
        })
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum EmbedderMode {
    Onnx,
    Mock,
}

pub fn embedder_mode() -> EmbedderMode {
    match std::env::var("BRAIN_EMBEDDER")
        .unwrap_or_else(|_| "onnx".to_string())
        .to_lowercase()
        .as_str()
    {
        "mock" => EmbedderMode::Mock,
        _ => EmbedderMode::Onnx,
    }
}

pub fn anthropic_api_key() -> Option<String> {
    std::env::var("ANTHROPIC_API_KEY").ok()
}

pub fn openrouter_api_key() -> Option<String> {
    std::env::var("OPENROUTER_API_KEY").ok()
}
