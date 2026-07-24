use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::process::Command;

use crate::BrainError;

// ---------------------------------------------------------------------------
// Models used (mirrors brain/config.py)
// ---------------------------------------------------------------------------

pub const SUMMARIZE_MODEL: &str = "claude-haiku-4-5-20251001";
pub const REFLECT_MODEL: &str = "claude-sonnet-4-6";
pub const OPENROUTER_DEFAULT_SUMMARIZE_MODEL: &str = "google/gemma-3-27b-it:free";
pub const OPENROUTER_DEFAULT_REFLECT_MODEL: &str = "meta-llama/llama-3.3-70b-instruct";
pub const OPENROUTER_DEFAULT_REFLECT_FALLBACK_MODEL: &str = "google/gemma-3-27b-it";

// ---------------------------------------------------------------------------
// Output types
// ---------------------------------------------------------------------------

/// Structured knowledge extracted from a full conversation.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ConversationSummary {
    pub summary: String,
    pub project: Option<String>,
    #[serde(default)]
    pub topics: Vec<String>,
    #[serde(default)]
    pub decisions: Vec<String>,
    #[serde(default)]
    pub solutions: Vec<String>,
    #[serde(default)]
    pub patterns: Vec<String>,
    #[serde(rename = "type", default)]
    pub memory_type: String,
}

/// Result of memory reflection — what to keep, consolidate, and delete.
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct ReflectionResult {
    #[serde(default)]
    pub consolidated: Vec<String>,
    #[serde(default)]
    pub patterns: Vec<String>,
    #[serde(default)]
    pub to_delete_indices: Vec<usize>,
}

// ---------------------------------------------------------------------------
// LlmClient trait — sync wrapper around async HTTP
// ---------------------------------------------------------------------------

/// Synchronous LLM client trait. Implementations hide the async runtime.
pub trait LlmClient: Send + Sync {
    fn complete(
        &self,
        model: &str,
        max_tokens: u32,
        user_msg: &str,
    ) -> Result<String, BrainError>;
}

// ---------------------------------------------------------------------------
// AnthropicClient — real HTTP client
// ---------------------------------------------------------------------------

pub struct AnthropicClient {
    api_key: String,
    client: reqwest::blocking::Client,
}

impl AnthropicClient {
    pub fn new(api_key: impl Into<String>) -> Self {
        Self {
            api_key: api_key.into(),
            client: reqwest::blocking::Client::new(),
        }
    }

    /// Build from ANTHROPIC_API_KEY env var.
    pub fn from_env() -> Result<Self, BrainError> {
        let key = std::env::var("ANTHROPIC_API_KEY")
            .map_err(|_| BrainError::Summarization("ANTHROPIC_API_KEY not set".into()))?;
        Ok(Self::new(key))
    }
}

impl LlmClient for AnthropicClient {
    fn complete(&self, model: &str, max_tokens: u32, user_msg: &str) -> Result<String, BrainError> {
        let body = json!({
            "model": model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": user_msg}],
            "response_format": {"type": "json_object"}
        });

        let resp = self
            .client
            .post("https://api.anthropic.com/v1/messages")
            .header("x-api-key", &self.api_key)
            .header("anthropic-version", "2023-06-01")
            .header("content-type", "application/json")
            .json(&body)
            .send()
            .map_err(|e: reqwest::Error| BrainError::Summarization(e.to_string()))?;

        if !resp.status().is_success() {
            let status = resp.status();
            let text = resp.text().unwrap_or_default();
            return Err(BrainError::Summarization(format!(
                "API error {status}: {text}"
            )));
        }

        let json: Value = resp
            .json()
            .map_err(|e: reqwest::Error| BrainError::Summarization(e.to_string()))?;

        json["content"][0]["text"]
            .as_str()
            .map(str::to_string)
            .ok_or_else(|| BrainError::Summarization("unexpected response shape".into()))
    }
}

// ---------------------------------------------------------------------------
// OpenRouterClient — real HTTP client via OpenRouter
// ---------------------------------------------------------------------------

pub struct OpenRouterClient {
    api_key: String,
    client: reqwest::blocking::Client,
}

impl OpenRouterClient {
    pub fn new(api_key: impl Into<String>) -> Self {
        let client = reqwest::blocking::Client::builder()
            .http1_only()
            .no_gzip()
            .no_brotli()
            .no_deflate()
            .build()
            .unwrap_or_else(|_| reqwest::blocking::Client::new());
        Self {
            api_key: api_key.into(),
            client,
        }
    }

    fn map_model(&self, model: &str) -> String {
        if model == SUMMARIZE_MODEL {
            std::env::var("OPENROUTER_SUMMARIZE_MODEL")
                .unwrap_or_else(|_| OPENROUTER_DEFAULT_SUMMARIZE_MODEL.to_string())
        } else if model == REFLECT_MODEL {
            std::env::var("OPENROUTER_REFLECT_MODEL")
                .unwrap_or_else(|_| OPENROUTER_DEFAULT_REFLECT_MODEL.to_string())
        } else {
            model.to_string()
        }
    }

    fn fallback_model(&self, model: &str) -> Option<String> {
        if model == SUMMARIZE_MODEL {
            std::env::var("OPENROUTER_SUMMARIZE_FALLBACK_MODEL").ok()
        } else if model == REFLECT_MODEL {
            Some(
                std::env::var("OPENROUTER_REFLECT_FALLBACK_MODEL")
                    .unwrap_or_else(|_| OPENROUTER_DEFAULT_REFLECT_FALLBACK_MODEL.to_string()),
            )
        } else {
            None
        }
    }

    fn request_model(
        &self,
        model: &str,
        max_tokens: u32,
        user_msg: &str,
    ) -> Result<String, BrainError> {
        let body = json!({
            "model": model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": user_msg}],
            "response_format": {"type": "json_object"}
        });

        let resp = self
            .client
            .post("https://openrouter.ai/api/v1/chat/completions")
            .header("Authorization", format!("Bearer {}", &self.api_key))
            .header("accept", "application/json")
            .header("accept-encoding", "identity")
            .header("content-type", "application/json")
            .json(&body)
            .send()
            .map_err(|e: reqwest::Error| BrainError::Summarization(e.to_string()))?;

        if !resp.status().is_success() {
            let status = resp.status();
            let text = resp.text().unwrap_or_default();
            return Err(BrainError::Summarization(format!(
                "OpenRouter API error {status}: {text}"
            )));
        }

        let body = match resp.bytes() {
            Ok(b) => b.to_vec(),
            Err(e) => {
                // Fallback for provider/body-decoder incompatibilities.
                let payload = body.to_string();
                let output = Command::new("curl")
                    .args([
                        "-sS",
                        "https://openrouter.ai/api/v1/chat/completions",
                        "-H",
                        &format!("Authorization: Bearer {}", &self.api_key),
                        "-H",
                        "Content-Type: application/json",
                        "-d",
                        &payload,
                    ])
                    .output()
                    .map_err(|ce| {
                        BrainError::Summarization(format!(
                            "error reading response body: {e}; curl fallback failed: {ce}"
                        ))
                    })?;
                if !output.status.success() {
                    return Err(BrainError::Summarization(format!(
                        "error reading response body: {e}; curl fallback non-zero exit {}",
                        output.status
                    )));
                }
                output.stdout
            }
        };

        // Some providers can prepend whitespace/noise around JSON; extract outermost object.
        let json: Value = match serde_json::from_slice(&body) {
            Ok(v) => v,
            Err(_) => {
                let lossy = String::from_utf8_lossy(&body);
                let start = lossy
                    .find('{')
                    .ok_or_else(|| BrainError::Summarization("OpenRouter response missing JSON start".into()))?;
                let end = lossy
                    .rfind('}')
                    .ok_or_else(|| BrainError::Summarization("OpenRouter response missing JSON end".into()))?
                    + 1;
                serde_json::from_str(&lossy[start..end]).map_err(|e| {
                    BrainError::Summarization(format!("OpenRouter JSON parse error: {e}"))
                })?
            }
        };

        if let Some(s) = json["choices"][0]["message"]["content"].as_str() {
            return Ok(s.to_string());
        }
        if let Some(parts) = json["choices"][0]["message"]["content"].as_array() {
            let text = parts
                .iter()
                .filter_map(|p| p.get("text").and_then(|t| t.as_str()))
                .collect::<Vec<_>>()
                .join("");
            if !text.is_empty() {
                return Ok(text);
            }
        }
        Err(BrainError::Summarization(
            "unexpected OpenRouter response shape".into(),
        ))
    }
}

impl LlmClient for OpenRouterClient {
    fn complete(&self, model: &str, max_tokens: u32, user_msg: &str) -> Result<String, BrainError> {
        let primary = self.map_model(model);
        match self.request_model(&primary, max_tokens, user_msg) {
            Ok(v) => Ok(v),
            Err(primary_err) => {
                if let Some(fallback) = self.fallback_model(model) {
                    self.request_model(&fallback, max_tokens, user_msg).map_err(|fallback_err| {
                        BrainError::Summarization(format!(
                            "primary model '{}' failed: {}; fallback model '{}' failed: {}",
                            primary, primary_err, fallback, fallback_err
                        ))
                    })
                } else {
                    Err(primary_err)
                }
            }
        }
    }
}

// ---------------------------------------------------------------------------
// OllamaClient — local LLM via Ollama (no API key)
// ---------------------------------------------------------------------------

/// Default local model used for summarize + reflect when `OLLAMA_MODEL` is unset.
pub const OLLAMA_DEFAULT_MODEL: &str = "qwen2.5:32b";

pub struct OllamaClient {
    url: String,
    model: String,
    client: reqwest::blocking::Client,
}

impl OllamaClient {
    pub fn new(url: impl Into<String>, model: impl Into<String>) -> Self {
        // 32B models are slow locally; give generous headroom but still bound it
        // so a stuck generation can't wedge the background worker forever.
        let client = reqwest::blocking::Client::builder()
            .timeout(std::time::Duration::from_secs(300))
            .build()
            .unwrap_or_else(|_| reqwest::blocking::Client::new());
        Self {
            url: url.into(),
            model: model.into(),
            client,
        }
    }

    /// Build from env: `OLLAMA_URL` (default `http://127.0.0.1:11434`),
    /// `OLLAMA_MODEL` (default `qwen2.5:32b`).
    pub fn from_env() -> Self {
        let url = std::env::var("OLLAMA_URL")
            .unwrap_or_else(|_| "http://127.0.0.1:11434".to_string());
        let model = std::env::var("OLLAMA_MODEL")
            .unwrap_or_else(|_| OLLAMA_DEFAULT_MODEL.to_string());
        Self::new(url, model)
    }
}

impl LlmClient for OllamaClient {
    // The trait `model` (a Claude model id) is ignored; the configured local
    // model serves both summarize and reflect.
    fn complete(&self, _model: &str, max_tokens: u32, user_msg: &str) -> Result<String, BrainError> {
        let body = json!({
            "model": self.model,
            "messages": [{"role": "user", "content": user_msg}],
            "stream": false,
            "options": {"num_predict": max_tokens}
        });

        let endpoint = format!("{}/api/chat", self.url.trim_end_matches('/'));
        let resp = self
            .client
            .post(&endpoint)
            .header("content-type", "application/json")
            .json(&body)
            .send()
            .map_err(|e: reqwest::Error| BrainError::Summarization(e.to_string()))?;

        if !resp.status().is_success() {
            let status = resp.status();
            let text = resp.text().unwrap_or_default();
            return Err(BrainError::Summarization(format!(
                "Ollama API error {status}: {text}"
            )));
        }

        let json: Value = resp
            .json()
            .map_err(|e: reqwest::Error| BrainError::Summarization(e.to_string()))?;

        json["message"]["content"]
            .as_str()
            .map(str::to_string)
            .ok_or_else(|| BrainError::Summarization("unexpected Ollama response shape".into()))
    }
}

// ---------------------------------------------------------------------------
// MockLlmClient — deterministic responses for tests
// ---------------------------------------------------------------------------

pub struct MockLlmClient {
    response: String,
}

impl MockLlmClient {
    pub fn new(response: impl Into<String>) -> Self {
        Self {
            response: response.into(),
        }
    }
}

impl LlmClient for MockLlmClient {
    fn complete(&self, _model: &str, _max_tokens: u32, _user_msg: &str) -> Result<String, BrainError> {
        Ok(self.response.clone())
    }
}

// ---------------------------------------------------------------------------
// Summarizer — ports brain/core/summarizer.py prompts exactly
// ---------------------------------------------------------------------------

pub struct Summarizer<C: LlmClient> {
    client: C,
}

impl<C: LlmClient> Summarizer<C> {
    pub fn new(client: C) -> Self {
        Self { client }
    }
}

/// Blanket impl so `&T` where `T: LlmClient` also satisfies `LlmClient`.
impl<T: LlmClient + ?Sized> LlmClient for &T {
    fn complete(&self, model: &str, max_tokens: u32, user_msg: &str) -> Result<String, BrainError> {
        (**self).complete(model, max_tokens, user_msg)
    }
}

/// Convenience: create a Summarizer from a `&dyn LlmClient` reference.
impl<'a> Summarizer<&'a dyn LlmClient> {
    pub fn from_ref(client: &'a dyn LlmClient) -> Self {
        Self { client }
    }
}

impl<C: LlmClient> Summarizer<C> {

    /// Extract first JSON object from LLM response (may be wrapped in markdown).
    fn parse_json(text: &str) -> Result<Value, BrainError> {
        let start = text
            .find('{')
            .ok_or_else(|| BrainError::Summarization(format!("no JSON in response: {}", &text[..text.len().min(200)])))?;
        let end = text
            .rfind('}')
            .ok_or_else(|| BrainError::Summarization("no closing brace".into()))?
            + 1;
        serde_json::from_str(&text[start..end])
            .map_err(|e| BrainError::Summarization(format!("JSON parse error: {e}")))
    }

    /// Summarize a full conversation session into structured knowledge.
    pub fn summarize_conversation(
        &self,
        messages: &[(&str, &str)], // (role, content) pairs
    ) -> Result<ConversationSummary, BrainError> {
        let formatted: Vec<String> = messages
            .iter()
            .take(30)
            .map(|(role, content)| {
                let truncated = if content.len() > 800 {
                    &content[..800]
                } else {
                    content
                };
                format!("{role}: {truncated}")
            })
            .collect();
        let formatted = formatted.join("\n");

        let prompt = format!(
            r#"Analyze this AI coding conversation. Extract structured knowledge.

CONVERSATION:
{formatted}

Respond with ONLY valid JSON (no markdown, no explanation):
{{
  "summary": "2-3 sentence description of what was accomplished",
  "project": "project name or null",
  "topics": ["topic1", "topic2"],
  "decisions": ["key architectural or design decision made"],
  "solutions": ["problem: solution description"],
  "patterns": ["reusable code pattern discovered"],
  "type": "solution|decision|conversation|project_context|error_lesson"
}}"#
        );

        let text = self.client.complete(SUMMARIZE_MODEL, 1024, &prompt)?;
        let val = Self::parse_json(&text)?;
        serde_json::from_value(val)
            .map_err(|e| BrainError::Summarization(format!("deserialize ConversationSummary: {e}")))
    }

    /// Summarize a single user/assistant exchange into a concise memory string.
    pub fn summarize_exchange(
        &self,
        user_message: &str,
        assistant_response: &str,
    ) -> Result<String, BrainError> {
        let user_truncated = if user_message.len() > 500 {
            &user_message[..500]
        } else {
            user_message
        };
        let asst_truncated = if assistant_response.len() > 500 {
            &assistant_response[..500]
        } else {
            assistant_response
        };

        let prompt = format!(
            r#"Summarize this coding exchange in 1-2 sentences for future memory retrieval.
Focus on: what was done, what was decided, or what was solved.

USER: {user_truncated}
ASSISTANT: {asst_truncated}

Respond with just the summary text, no JSON."#
        );

        self.client
            .complete(SUMMARIZE_MODEL, 256, &prompt)
            .map(|s| s.trim().to_string())
    }

    /// Consolidate and find patterns across a batch of memories.
    pub fn reflect_memories(
        &self,
        memory_texts: &[&str],
    ) -> Result<ReflectionResult, BrainError> {
        // Cap each memory so one giant memory (project_context seen up to ~513k chars)
        // can't blow the prompt past the model's context window. 10 * 2000 chars ~= 5k tokens.
        let formatted: Vec<String> = memory_texts
            .iter()
            .enumerate()
            .map(|(i, m)| {
                let capped: String = if m.chars().count() > 2000 {
                    format!("{}…", m.chars().take(2000).collect::<String>())
                } else {
                    (*m).to_string()
                };
                format!("[{i}] {capped}")
            })
            .collect();
        let formatted = formatted.join("\n\n");

        let prompt = format!(
            r#"You are reviewing a batch of memories from a developer's knowledge store.
Your job is to consolidate near-duplicates and extract concrete, reusable patterns.

DEFINITIONS:
- consolidated = two or more memories stating the SAME fact, merged into one that keeps every specific (numbers, names, paths).
- patterns = a reusable lesson the memories only imply together — not a restatement of any single one.

STRICT RULES:
- Return empty arrays if nothing substantive emerges. Empty is the correct default.
- Every pattern MUST contain the specific detail that makes it reusable: exact numbers, thresholds, file/function/tool names, commands, or error text. A pattern with no concrete anchor is noise — drop it.
- DO NOT summarize the batch itself ("Memories 0 and 1 relate to X", "These memories cover...").
- DO NOT write meta-commentary about which memories fit which category.
- DO NOT restate memory content verbatim as a pattern.
- DO NOT invent patterns where none exist. Prefer empty over speculative.
- Each consolidated/pattern string must be self-contained and actionable on its own.
- to_delete_indices should only include true duplicates or pure noise (e.g., "test memory", empty summaries).

EXAMPLE:
- GOOD pattern: "qwen2.5:32b has a 32k context; inputs beyond it truncate silently (keep=4 drops the middle) — cap LLM batch inputs to fit."
- BAD pattern (too vague, reject): "Limit memory sizes to improve efficiency."

MEMORIES:
{formatted}

Respond with ONLY valid JSON in this exact shape:
{{
  "consolidated": ["merged memory text — only if two+ memories genuinely cover the same specific fact"],
  "patterns": ["reusable insight — concrete, with the specific anchor (number/name/command) that makes it actionable"],
  "to_delete_indices": [0, 3]
}}"#
        );

        let text = self.client.complete(REFLECT_MODEL, 2048, &prompt)?;
        let val = Self::parse_json(&text)?;
        serde_json::from_value(val)
            .map_err(|e| BrainError::Summarization(format!("deserialize ReflectionResult: {e}")))
    }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    fn mock_conversation_json() -> &'static str {
        r#"{
            "summary": "Fixed a parser bug in the tokenizer module.",
            "project": "my_project",
            "topics": ["parser", "tokenizer"],
            "decisions": ["use recursive descent"],
            "solutions": ["tokenizer crash: added bounds check"],
            "patterns": [],
            "type": "solution"
        }"#
    }

    fn mock_reflection_json() -> &'static str {
        r#"{
            "consolidated": ["Use builder pattern for all config structs"],
            "patterns": ["Config objects use builder pattern across 3 projects"],
            "to_delete_indices": [1, 2]
        }"#
    }

    #[test]
    fn summarize_conversation_parses_structured_json() {
        let client = MockLlmClient::new(mock_conversation_json());
        let summarizer = Summarizer::new(client);
        let result = summarizer
            .summarize_conversation(&[("user", "fix the parser"), ("assistant", "I found the bug")])
            .unwrap();
        assert_eq!(result.summary, "Fixed a parser bug in the tokenizer module.");
        assert_eq!(result.project.as_deref(), Some("my_project"));
        assert_eq!(result.topics, vec!["parser", "tokenizer"]);
        assert_eq!(result.memory_type, "solution");
    }

    #[test]
    fn summarize_exchange_returns_plain_text() {
        let client = MockLlmClient::new("Added error handling to the database layer.");
        let summarizer = Summarizer::new(client);
        let result = summarizer
            .summarize_exchange("add error handling", "I added try-catch blocks")
            .unwrap();
        assert_eq!(result, "Added error handling to the database layer.");
    }

    #[test]
    fn reflect_memories_parses_delete_indices() {
        let client = MockLlmClient::new(mock_reflection_json());
        let summarizer = Summarizer::new(client);
        let memories = ["memory 0", "memory 1", "memory 2", "memory 3"];
        let result = summarizer.reflect_memories(&memories).unwrap();
        assert_eq!(result.to_delete_indices, vec![1, 2]);
        assert_eq!(result.consolidated.len(), 1);
        assert_eq!(result.patterns.len(), 1);
    }

    #[test]
    fn parse_json_extracts_from_markdown_wrapper() {
        let text = "Here is the result:\n```json\n{\"key\": \"value\"}\n```";
        let val = Summarizer::<MockLlmClient>::parse_json(text).unwrap();
        assert_eq!(val["key"], "value");
    }

    #[test]
    fn summarize_conversation_truncates_long_messages() {
        // 35 messages — only first 30 should be used (no crash)
        let long_content = "x".repeat(1000);
        let messages: Vec<(&str, &str)> = (0..35).map(|_| ("user", long_content.as_str())).collect();
        let client = MockLlmClient::new(mock_conversation_json());
        let summarizer = Summarizer::new(client);
        let result = summarizer.summarize_conversation(&messages);
        assert!(result.is_ok());
    }

    #[test]
    fn reflect_memories_handles_empty_deleted_indices() {
        let json = r#"{"consolidated": [], "patterns": [], "to_delete_indices": []}"#;
        let client = MockLlmClient::new(json);
        let summarizer = Summarizer::new(client);
        let result = summarizer.reflect_memories(&["only one memory"]).unwrap();
        assert!(result.to_delete_indices.is_empty());
    }

    #[test]
    fn ollama_client_holds_configured_url_and_model() {
        let c = OllamaClient::new("http://127.0.0.1:11434", "qwen2.5:32b");
        assert_eq!(c.url, "http://127.0.0.1:11434");
        assert_eq!(c.model, "qwen2.5:32b");
    }

    #[test]
    fn ollama_default_model_is_qwen() {
        assert_eq!(OLLAMA_DEFAULT_MODEL, "qwen2.5:32b");
    }
}
