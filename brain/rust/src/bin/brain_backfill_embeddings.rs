//! One-shot binary: embed all `memories` rows that have `embedding IS NULL`.
//!
//! Safe to run multiple times — already-embedded rows are untouched.
//!
//! Environment variables:
//!   BRAIN_DB_PATH, BRAIN_ONNX_PATH, BRAIN_EMBEDDER

use brain::embedder::embedder_from_env;
use brain::store::MetadataStore;
use brain::BrainError;

const BATCH: usize = 50;

fn main() -> Result<(), BrainError> {
    let db_path = std::env::var("BRAIN_DB_PATH").unwrap_or_else(|_| "brain.db".into());
    eprintln!("[backfill] db: {db_path}");

    let store = MetadataStore::open(&db_path)?;
    let embedder = embedder_from_env("[backfill]")?;

    let rows = store.get_unembedded_ids_and_content()?;
    let total = rows.len();
    eprintln!("[backfill] {total} rows need embeddings");

    if total == 0 {
        eprintln!("[backfill] nothing to do ✓");
        return Ok(());
    }

    let mut done = 0;
    for (id, content) in &rows {
        let emb = embedder.embed(content)?;
        store.update_embedding(id, &emb)?;
        done += 1;
        if done % BATCH == 0 {
            eprintln!("[backfill] {done}/{total}…");
        }
    }

    eprintln!("[backfill] done — {done} embeddings written ✓");
    Ok(())
}
