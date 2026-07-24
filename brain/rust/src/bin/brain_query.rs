use brain::brain::{Brain, BrainConfig};
use brain::embedder::OnnxEmbedder;
use brain::{BrainError, SearchFilter};

fn main() -> Result<(), BrainError> {
    let args: Vec<String> = std::env::args().collect();
    if args.len() < 2 {
        eprintln!(
            "Usage: brain_query <query> [n] [--db <path>] [--model <onnx_dir>]"
        );
        std::process::exit(1);
    }

    let query = args[1].clone();
    let n: usize = args.get(2).and_then(|s| s.parse().ok()).unwrap_or(5);

    let db_path = flag_or_default(&args, "--db", "brain.db");
    let model_path = flag_or_default(
        &args,
        "--model",
        "models/all-mpnet-base-v2-onnx",
    );

    let embedder = OnnxEmbedder::load(model_path)?;
    let brain = Brain::open(
        BrainConfig {
            db_path,
            embedding_dims: 768,
            reflect_every_n: 20,
            reflection_disabled: false,
            hybrid_alpha: 0.7,
        },
        Box::new(embedder),
    )?;

    let results = brain.search(&query, n, Some(SearchFilter::default()))?;
    for r in results {
        println!("{}\t{:.6}\t{}", r.id, r.distance, one_line(&r.content));
    }
    Ok(())
}

fn flag_or_default(args: &[String], flag: &str, default: &str) -> String {
    args.windows(2)
        .find(|w| w[0] == flag)
        .map(|w| w[1].clone())
        .unwrap_or_else(|| default.to_string())
}

fn one_line(s: &str) -> String {
    s.replace('\n', " ").trim().to_string()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn flag_or_default_returns_value_when_flag_present() {
        let args: Vec<String> = vec!["prog".into(), "--db".into(), "custom.db".into()];
        assert_eq!(flag_or_default(&args, "--db", "brain.db"), "custom.db");
    }

    #[test]
    fn flag_or_default_returns_default_when_flag_absent() {
        let args: Vec<String> = vec!["prog".into(), "query".into()];
        assert_eq!(flag_or_default(&args, "--db", "brain.db"), "brain.db");
    }

    #[test]
    fn one_line_collapses_newlines() {
        assert_eq!(one_line("foo\nbar\nbaz"), "foo bar baz");
    }

    #[test]
    fn one_line_trims_whitespace() {
        assert_eq!(one_line("  hello  "), "hello");
    }
}

