use std::fmt;

#[derive(Debug)]
pub enum BrainError {
    Database(String),
    Embedding(String),
    Summarization(String),
    Io(std::io::Error),
    Json(serde_json::Error),
    NotFound(String),
}

impl fmt::Display for BrainError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Database(msg) => write!(f, "database error: {msg}"),
            Self::Embedding(msg) => write!(f, "embedding error: {msg}"),
            Self::Summarization(msg) => write!(f, "summarization error: {msg}"),
            Self::Io(err) => write!(f, "io error: {err}"),
            Self::Json(err) => write!(f, "json error: {err}"),
            Self::NotFound(msg) => write!(f, "not found: {msg}"),
        }
    }
}

impl std::error::Error for BrainError {}

impl From<std::io::Error> for BrainError {
    fn from(err: std::io::Error) -> Self {
        Self::Io(err)
    }
}

impl From<serde_json::Error> for BrainError {
    fn from(err: serde_json::Error) -> Self {
        Self::Json(err)
    }
}
