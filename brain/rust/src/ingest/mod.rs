pub mod claude_code;
pub mod perplexity;

use std::collections::HashSet;
use std::path::Path;

use crate::BrainError;

/// Persist and load a set of processed IDs to prevent re-ingesting.
pub struct Checkpoint {
    path: std::path::PathBuf,
    pub processed: HashSet<String>,
}

impl Checkpoint {
    pub fn load(path: impl AsRef<Path>) -> Self {
        let path = path.as_ref().to_path_buf();
        let processed = if path.exists() {
            let text = std::fs::read_to_string(&path).unwrap_or_default();
            let val: serde_json::Value = serde_json::from_str(&text).unwrap_or_default();
            val["processed_ids"]
                .as_array()
                .map(|arr| {
                    arr.iter()
                        .filter_map(|v| v.as_str().map(str::to_string))
                        .collect()
                })
                .unwrap_or_default()
        } else {
            HashSet::new()
        };
        Self { path, processed }
    }

    pub fn contains(&self, id: &str) -> bool {
        self.processed.contains(id)
    }

    pub fn mark(&mut self, id: &str) {
        self.processed.insert(id.to_string());
    }

    pub fn save(&self) -> Result<(), BrainError> {
        let mut ids: Vec<&str> = self.processed.iter().map(String::as_str).collect();
        ids.sort_unstable();
        let json = serde_json::json!({ "processed_ids": ids });
        std::fs::write(&self.path, json.to_string())?;
        Ok(())
    }
}
