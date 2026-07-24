//! Extract top-level symbol names from source using tree-sitter (for `sym:` tags).

use std::collections::BTreeSet;
use std::path::Path;

use tree_sitter::{Language, Parser, Query, QueryCursor};

/// Build a [`Language`] from a grammar entrypoint (`tree_sitter_*` in language crates).
///
/// Grammar crates expose `LanguageFn`; `tree-sitter` 0.22 does not implement `Into<Language>`
/// for it, so we bridge via the raw C pointer (same pattern as `Language::from_raw` docs).
unsafe fn language_from_fn(f: unsafe extern "C" fn() -> *const ()) -> Language {
    Language::from_raw(f().cast())
}

/// Return unique function / class / method names found in `content` for `path`'s extension.
pub fn extract_symbols(path: &str, content: &str) -> Vec<String> {
    let ext = Path::new(path)
        .extension()
        .and_then(|s| s.to_str())
        .unwrap_or("");
    let (language, query_src): (Language, &'static str) = match ext {
        "rs" => (
            tree_sitter_rust::language(),
            "(function_item name: (identifier) @name)",
        ),
        "ts" | "mts" | "cts" => (
            unsafe { language_from_fn(tree_sitter_typescript::LANGUAGE_TYPESCRIPT.into_raw()) },
            "(function_declaration name: (identifier) @name)",
        ),
        "tsx" => (
            unsafe { language_from_fn(tree_sitter_typescript::LANGUAGE_TSX.into_raw()) },
            "(function_declaration name: (identifier) @name)",
        ),
        "py" => (
            unsafe { language_from_fn(tree_sitter_python::LANGUAGE.into_raw()) },
            "(function_definition name: (identifier) @name)
             (class_definition name: (identifier) @name)",
        ),
        _ => return vec![],
    };

    let mut parser = Parser::new();
    if parser.set_language(&language).is_err() {
        return vec![];
    }
    let Some(tree) = parser.parse(content, None) else {
        return vec![];
    };
    let Ok(query) = Query::new(&language, query_src) else {
        return vec![];
    };

    let mut cursor = QueryCursor::new();
    let mut seen = BTreeSet::new();
    for m in cursor.matches(&query, tree.root_node(), content.as_bytes()) {
        for cap in m.captures {
            if let Ok(s) = cap.node.utf8_text(content.as_bytes()) {
                seen.insert(s.to_string());
            }
        }
    }
    seen.into_iter().collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn extracts_rust_functions() {
        let src = "pub fn hello() {} fn private() {}";
        let syms = extract_symbols("lib.rs", src);
        assert!(syms.contains(&"hello".to_string()));
        assert!(syms.contains(&"private".to_string()));
    }

    #[test]
    fn extracts_python_functions_and_classes() {
        let src = "def foo(): pass\nclass Bar: pass";
        let syms = extract_symbols("mod.py", src);
        assert!(syms.contains(&"foo".to_string()));
        assert!(syms.contains(&"Bar".to_string()));
    }

    #[test]
    fn returns_empty_for_unknown_extension() {
        assert!(extract_symbols("README.md", "# hi").is_empty());
    }
}
