//! When `title` is missing or blank, derive a short label for hybrid retrieval (FTS + UI).

/// Prefer `[label]` prefix, else first line, else session id, else a fixed fallback.
pub fn derive_memory_title(content: &str, session_id: Option<&str>) -> String {
    let t = content.trim();
    if t.is_empty() {
        return session_fallback(session_id);
    }
    if let Some(rest) = t.strip_prefix('[') {
        if let Some(end) = rest.find(']') {
            let label = rest[..end].trim();
            let after = rest[end + 1..].trim();
            if !label.is_empty() && label.chars().count() <= 240 {
                let role_like = label.eq_ignore_ascii_case("user")
                    || label.eq_ignore_ascii_case("assistant");
                if role_like && after.chars().count() > 10 {
                    let snippet: String = after.chars().take(72).collect();
                    return truncate_chars(&format!("{label}: {snippet}"), 120);
                }
                return truncate_chars(label, 120);
            }
        }
    }
    let line = t.lines().next().unwrap_or("").trim();
    if line.is_empty() {
        session_fallback(session_id)
    } else {
        truncate_chars(line, 120)
    }
}

fn session_fallback(session_id: Option<&str>) -> String {
    session_id
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .map(|s| format!("session {}", truncate_chars(s, 80)))
        .unwrap_or_else(|| "Untitled memory".to_string())
}

fn truncate_chars(s: &str, max_chars: usize) -> String {
    if s.chars().count() <= max_chars {
        s.to_string()
    } else {
        s.chars().take(max_chars).collect()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn bracket_prefix_becomes_title() {
        assert_eq!(
            derive_memory_title("[My Doc] intro\n\nbody", None),
            "My Doc"
        );
    }

    #[test]
    fn user_role_gets_snippet() {
        let t = derive_memory_title("[user] fix the CORS middleware on staging", None);
        assert!(t.contains("user"));
        assert!(t.contains("CORS") || t.contains("fix"));
    }

    #[test]
    fn first_line_fallback() {
        assert_eq!(
            derive_memory_title("Only one line here", None),
            "Only one line here"
        );
    }

    #[test]
    fn empty_uses_session() {
        let t = derive_memory_title("  ", Some("sid-abc"));
        assert!(t.contains("sid-abc"));
    }
}
