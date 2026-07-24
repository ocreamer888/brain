use std::path::Path;
use std::sync::Mutex;

use ort::session::Session;
use ort::value::Value;

use crate::BrainError;
use crate::config::{embedder_mode, onnx_model_path, EmbedderMode};

/// Number of dimensions for the `all-mpnet-base-v2` model.
pub const EMBEDDING_DIMS: usize = 768;

/// Trait for embedding backends — swappable between ONNX, mock, or HTTP.
pub trait EmbedderBackend: Send + Sync {
    fn embed(&self, text: &str) -> Result<Vec<f32>, BrainError>;
    fn embed_batch(&self, texts: &[&str]) -> Result<Vec<Vec<f32>>, BrainError>;
    fn dimensions(&self) -> usize;
}

// ---------------------------------------------------------------------------
// MockEmbedder — deterministic, hash-based, no model files needed
// ---------------------------------------------------------------------------

/// Deterministic pseudo-embedder for tests.
///
/// Uses a simple hash of the text to seed a fixed vector, so:
/// - Same text always → same vector
/// - Different texts → different vectors (with high probability)
/// - No model file or runtime required
pub struct MockEmbedder {
    dims: usize,
}

impl MockEmbedder {
    pub fn new(dims: usize) -> Self {
        Self { dims }
    }
}

impl Default for MockEmbedder {
    fn default() -> Self {
        Self::new(EMBEDDING_DIMS)
    }
}

impl EmbedderBackend for MockEmbedder {
    fn embed(&self, text: &str) -> Result<Vec<f32>, BrainError> {
        Ok(deterministic_vector(text, self.dims))
    }

    fn embed_batch(&self, texts: &[&str]) -> Result<Vec<Vec<f32>>, BrainError> {
        texts.iter().map(|t| self.embed(t)).collect()
    }

    fn dimensions(&self) -> usize {
        self.dims
    }
}

/// Produce a deterministic unit vector from a string by hashing.
fn deterministic_vector(text: &str, dims: usize) -> Vec<f32> {
    // FNV-1a-like hash seeded per dimension to spread values across the space.
    let mut v: Vec<f32> = (0..dims)
        .map(|i| {
            let mut h: u64 = 0xcbf2_9ce4_8422_2325_u64.wrapping_add(i as u64);
            for b in text.bytes() {
                h ^= u64::from(b);
                h = h.wrapping_mul(0x0000_0100_0000_01b3_u64);
                h ^= h >> 32;
            }
            // Map to [-1, 1]
            ((h as i64) as f32) / (i64::MAX as f32)
        })
        .collect();

    // L2-normalize so cosine similarity == dot product
    let norm: f32 = v.iter().map(|x| x * x).sum::<f32>().sqrt();
    if norm > 1e-10 {
        v.iter_mut().for_each(|x| *x /= norm);
    }
    v
}

// ---------------------------------------------------------------------------
// OnnxEmbedder — production implementation using ONNX Runtime
// ---------------------------------------------------------------------------

/// Sentence embedder backed by `all-mpnet-base-v2` exported to ONNX.
///
/// Requires:
/// - ONNX model directory at `model_path` (exported via `brain/tools/export_onnx.py`)
/// - `libonnxruntime` on the system (downloaded by `ort` or specified via `ORT_DYLIB_PATH`)
pub struct OnnxEmbedder {
    session: Mutex<Session>,
    tokenizer: tokenizers::Tokenizer,
    dims: usize,
}

impl OnnxEmbedder {
    /// Load the ONNX model from `model_path/model.onnx` and tokenizer from `model_path/tokenizer.json`.
    pub fn load(model_path: impl AsRef<Path>) -> Result<Self, BrainError> {
        let model_path = model_path.as_ref();

        let session = Session::builder()
            .map_err(|e: ort::Error| BrainError::Embedding(e.to_string()))?
            .commit_from_file(model_path.join("model.onnx"))
            .map_err(|e: ort::Error| BrainError::Embedding(e.to_string()))?;

        let tokenizer = tokenizers::Tokenizer::from_file(model_path.join("tokenizer.json"))
            .map_err(|e| BrainError::Embedding(e.to_string()))?;

        Ok(Self {
            session: Mutex::new(session),
            tokenizer,
            dims: EMBEDDING_DIMS,
        })
    }

    fn tokenize_and_run(&self, text: &str) -> Result<Vec<f32>, BrainError> {
        let encoding = self
            .tokenizer
            .encode(text, true)
            .map_err(|e| BrainError::Embedding(e.to_string()))?;

        let input_ids: Vec<i64> = encoding.get_ids().iter().map(|&x| x as i64).collect();
        let attention_mask: Vec<i64> = encoding
            .get_attention_mask()
            .iter()
            .map(|&x| x as i64)
            .collect();

        let seq_len = input_ids.len();

        // all-mpnet-base-v2 only takes input_ids and attention_mask (no token_type_ids)
        let ids_tensor = Value::from_array(([1usize, seq_len], input_ids))
            .map_err(|e: ort::Error| BrainError::Embedding(e.to_string()))?;
        let mask_tensor = Value::from_array(([1usize, seq_len], attention_mask))
            .map_err(|e: ort::Error| BrainError::Embedding(e.to_string()))?;

        let mut session_guard = self
            .session
            .lock()
            .map_err(|e| BrainError::Embedding(e.to_string()))?;
        let outputs = session_guard
            .run(ort::inputs![
                "input_ids" => ids_tensor,
                "attention_mask" => mask_tensor
            ])
            .map_err(|e: ort::Error| BrainError::Embedding(e.to_string()))?;

        // Model outputs: [token_embeddings (1, seq, 768), sentence_embedding (1, 768)]
        // Use sentence_embedding (index 1) — already mean-pooled and L2-normalized
        let (_, flat) = outputs[1]
            .try_extract_tensor::<f32>()
            .map_err(|e: ort::Error| BrainError::Embedding(e.to_string()))?;

        Ok(flat.to_vec())
    }
}

impl EmbedderBackend for OnnxEmbedder {
    fn embed(&self, text: &str) -> Result<Vec<f32>, BrainError> {
        self.tokenize_and_run(text)
    }

    fn embed_batch(&self, texts: &[&str]) -> Result<Vec<Vec<f32>>, BrainError> {
        texts.iter().map(|t| self.embed(t)).collect()
    }

    fn dimensions(&self) -> usize {
        self.dims
    }
}

pub fn embedder_from_env(log_prefix: &str) -> Result<Box<dyn EmbedderBackend>, BrainError> {
    match embedder_mode() {
        EmbedderMode::Mock => {
            eprintln!("{log_prefix} using MockEmbedder (BRAIN_EMBEDDER=mock)");
            Ok(Box::new(MockEmbedder::default()))
        }
        EmbedderMode::Onnx => {
            let path = onnx_model_path().ok_or_else(|| {
                BrainError::Embedding("BRAIN_ONNX_PATH is not set".to_string())
            })?;
            let embedder = OnnxEmbedder::load(&path)?;
            eprintln!("{log_prefix} using ONNX embedder from {path}");
            Ok(Box::new(embedder))
        }
    }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::PathBuf;

    #[test]
    fn mock_embedder_returns_correct_dims() {
        let emb = MockEmbedder::new(768);
        let v = emb.embed("hello world").unwrap();
        assert_eq!(v.len(), 768);
    }

    #[test]
    fn mock_embedder_is_deterministic() {
        let emb = MockEmbedder::default();
        let v1 = emb.embed("same text").unwrap();
        let v2 = emb.embed("same text").unwrap();
        assert_eq!(v1, v2);
    }

    #[test]
    fn mock_embedder_different_texts_differ() {
        let emb = MockEmbedder::default();
        let v1 = emb.embed("text one").unwrap();
        let v2 = emb.embed("text two").unwrap();
        assert_ne!(v1, v2);
    }

    #[test]
    fn mock_embedder_is_unit_normalized() {
        let emb = MockEmbedder::default();
        let v = emb.embed("normalize me").unwrap();
        let norm: f32 = v.iter().map(|x| x * x).sum::<f32>().sqrt();
        assert!((norm - 1.0).abs() < 1e-5, "norm was {norm}");
    }

    #[test]
    fn mock_embedder_batch_matches_single() {
        let emb = MockEmbedder::default();
        let texts = ["first", "second", "third"];
        let batch = emb.embed_batch(&texts).unwrap();
        for (t, b) in texts.iter().zip(batch.iter()) {
            let single = emb.embed(t).unwrap();
            assert_eq!(&single, b);
        }
    }

    /// Integration test (CI-gated):
    /// - Set BRAIN_RUN_ONNX_TESTS=1 to execute.
    /// - Optionally set BRAIN_ONNX_PATH, otherwise uses the default models path.
    #[test]
    fn onnx_embedder_loads_and_produces_768_dims() {
        if std::env::var("BRAIN_RUN_ONNX_TESTS").ok().as_deref() != Some("1") {
            return;
        }

        let model_path = std::env::var("BRAIN_ONNX_PATH").unwrap_or_else(|_| {
            PathBuf::from(env!("CARGO_MANIFEST_DIR"))
                .join("models")
                .join("all-mpnet-base-v2-onnx")
                .to_string_lossy()
                .into_owned()
        });

        if !PathBuf::from(&model_path).join("model.onnx").exists() {
            return;
        }

        let emb = OnnxEmbedder::load(&model_path).unwrap();
        let v = emb.embed("test sentence").unwrap();
        assert_eq!(v.len(), 768);
        let norm: f32 = v.iter().map(|x| x * x).sum::<f32>().sqrt();
        assert!((norm - 1.0).abs() < 1e-5);
    }
}
