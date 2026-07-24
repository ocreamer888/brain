//! Phase 6 migration binary.
//!
//! Usage:
//!     brain_migrate <input.jsonl> [--db <path>]
//!
//! Environment variables (used when flags are absent):
//!     BRAIN_DB_PATH — path to SQLite file  (default: brain.db)
//!
//! Embeddings are stored directly in the SQLite `memories.embedding` column.
//! No separate index file is written.

use std::process;

use brain::migrate::migrate_from_jsonl;
use brain::store::MetadataStore;
use brain::BrainError;

fn main() -> Result<(), BrainError> {
    let args: Vec<String> = std::env::args().collect();

    if args.len() < 2 || args[1] == "--help" || args[1] == "-h" {
        eprintln!(
            "Usage: brain_migrate <input.jsonl> [--db <path>]\n\
             \n\
             Env vars (fallback when flags absent):\n\
               BRAIN_DB_PATH  SQLite path  (default: brain.db)"
        );
        process::exit(1);
    }

    let input = &args[1];
    let db_path = flag_or_env(&args, "--db", "BRAIN_DB_PATH", "brain.db");

    eprintln!("[migrate] input : {input}");
    eprintln!("[migrate] db    : {db_path}");

    let store = MetadataStore::open(&db_path)?;
    let result = migrate_from_jsonl(input, &store)?;

    eprintln!("[migrate] ── results ──────────────────────────");
    eprintln!("[migrate]  imported      : {}", result.imported);
    eprintln!("[migrate]  no embedding  : {}", result.no_embedding);
    eprintln!("[migrate]  errors        : {}", result.errors);

    if result.errors > 0 {
        eprintln!("[migrate] completed with {} error(s)", result.errors);
        process::exit(1);
    }

    eprintln!("[migrate] done ✓");
    Ok(())
}

/// Return the value of `--flag <value>` from args, falling back to the env var,
/// then to `default`.
fn flag_or_env(args: &[String], flag: &str, env_var: &str, default: &str) -> String {
    args.windows(2)
        .find(|w| w[0] == flag)
        .map(|w| w[1].clone())
        .or_else(|| std::env::var(env_var).ok())
        .unwrap_or_else(|| default.to_string())
}
