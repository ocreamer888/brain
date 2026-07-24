use serde::Deserialize;

#[derive(Debug, Deserialize)]
pub struct HookInput {
    #[serde(default)]
    pub session_id: String,
    pub prompt: String,
    #[serde(default)]
    pub cwd: String,
}

pub fn parse_hook_input(raw: &str) -> Result<HookInput, serde_json::Error> {
    serde_json::from_str(raw)
}

pub fn format_context(hits: &[(&str, f32)]) -> String {
    if hits.is_empty() {
        return String::new();
    }
    let mut out = String::from("### Relevant prior context\n");
    for (content, _dist) in hits.iter().take(5) {
        let snippet: String = content.chars().take(200).collect();
        out.push_str(&format!("- {}\n", snippet));
    }
    out
}

fn main() {
    let mut raw = String::new();
    if std::io::Read::read_to_string(&mut std::io::stdin(), &mut raw).is_err() {
        return;
    }
    let Ok(input) = parse_hook_input(&raw) else {
        return;
    };
    // Search brain for context relevant to this prompt, print as JSON to stdout.
    // Claude Code injects stdout into the context window.
    if let Err(e) = run(input) {
        eprintln!("brain_user_prompt_submit: {e}");
    }
}

fn run(input: HookInput) -> Result<(), Box<dyn std::error::Error>> {
    let api_url = std::env::var("BRAIN_API_URL").unwrap_or_else(|_| "http://127.0.0.1:8787".into());
    let client = reqwest::blocking::Client::new();
    let resp = client
        .post(format!("{}/v1/search", api_url))
        .json(&serde_json::json!({ "query": input.prompt, "n": 5 }))
        .send()?;
    let body: serde_json::Value = resp.json()?;
    let hits: Vec<(String, f32)> = body["results"]
        .as_array()
        .map(|arr| {
            arr.iter()
                .filter_map(|r| {
                    Some((
                        r["content"].as_str()?.to_string(),
                        r["distance"].as_f64().unwrap_or(1.0) as f32,
                    ))
                })
                .collect()
        })
        .unwrap_or_default();
    let refs: Vec<(&str, f32)> = hits.iter().map(|(s, d)| (s.as_str(), *d)).collect();
    println!("{}", format_context(&refs));
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn parses_hook_stdin_payload() {
        let payload = json!({
            "hook_event_name": "UserPromptSubmit",
            "session_id": "abc123",
            "prompt": "how do I wire up the worker queue?",
            "cwd": "/tmp/project"
        });
        let parsed = parse_hook_input(&payload.to_string()).expect("should parse");
        assert_eq!(parsed.session_id, "abc123");
        assert_eq!(parsed.prompt, "how do I wire up the worker queue?");
        assert_eq!(parsed.cwd, "/tmp/project");
    }

    #[test]
    fn format_context_empty_hits_returns_empty_string() {
        assert_eq!(format_context(&[]), "");
    }

    #[test]
    fn formats_context_for_injection() {
        let hits = vec![
            ("we decided to use SQLite not Chroma", 0.12),
            ("rust brain_api exposes /v1/search", 0.19),
        ];
        let out = format_context(&hits);
        assert!(out.contains("we decided to use SQLite"));
        assert!(out.contains("rust brain_api"));
        // Must be bounded — don't blow the context window.
        assert!(out.lines().count() <= 12);
    }
}
