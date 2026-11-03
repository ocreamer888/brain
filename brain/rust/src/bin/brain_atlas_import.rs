//! Load an atlas dataset (points CSV + links CSV) into one brain's database.
//!
//!   brain_atlas_import <instance-id> <points.csv> <links.csv> [--preset ai-model-atlas]
//!
//! Writes only that brain's `atlas_*` tables (replacing any previous atlas);
//! memories are untouched. The preset carries the reference project's column
//! mapping and viewer config (AI Model Atlas, run.cosmograph.app, 2026-10-19).

use std::path::Path;

use brain::atlas::{import_csv, AtlasConfig, ColumnMapping};

fn ai_model_atlas() -> (ColumnMapping, AtlasConfig) {
    let map = ColumnMapping {
        id: "id".into(),
        label: "label".into(),
        color: "author".into(),
        size: "size".into(),
        x: "layout_x".into(),
        y: "layout_y".into(),
        z: "layout_z".into(),
        link_source: "source".into(),
        link_target: "target".into(),
        link_id: "id".into(),
        link_color: "color".into(),
    };
    let config = AtlasConfig {
        title: "AI Model Atlas".into(),
        description: "Model Atlas visualizes entire populations of machine-learning models as an interconnected graph, \
                      showing how models evolve, relate, and transform through fine-tuning. (Replica for learning: \
                      horwitz.ai/model-atlas.)"
            .into(),
        palette: ["#ff595e", "#ff924c", "#ffca3a", "#c5ca30", "#8ac926", "#52a675", "#1982c4", "#4267ac", "#6a4c93", "#b5a6c9"]
            .map(String::from)
            .to_vec(),
        point_size_range: [6.0, 10.0],
        link_opacity: 0.8,
        quantile_extent: [0.05, 0.95],
        background: "#192129".into(),
    };
    (map, config)
}

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    if args.len() < 3 || args.iter().any(|a| a == "-h" || a == "--help") {
        eprintln!("usage: brain_atlas_import <instance-id> <points.csv> <links.csv>");
        std::process::exit(2);
    }
    let (instance, points, links) = (&args[0], Path::new(&args[1]), Path::new(&args[2]));

    let registry_file = brain::instances::registry_path();
    if !registry_file.is_file() {
        fail(&format!("no instance registry at {} (create the brain in the app first)", registry_file.display()));
    }
    let registry = brain::instances::load_or_bootstrap(
        &registry_file,
        Path::new(&std::env::var("BRAIN_DB_PATH").unwrap_or_default()),
    )
    .unwrap_or_else(|e| fail(&format!("instance registry: {e}")));
    let Some(record) = registry.instances.iter().find(|i| i.id == *instance) else {
        fail(&format!("no brain with id '{instance}'"))
    };
    if record.id == registry.active_id {
        eprintln!("note: '{instance}' is the active brain; importing into it anyway (memories are untouched).");
    }

    let (map, config) = ai_model_atlas();
    let mut conn = rusqlite::Connection::open(&record.db_path).unwrap_or_else(|e| fail(&format!("{}: {e}", record.db_path)));
    conn.busy_timeout(std::time::Duration::from_secs(10)).ok();
    let started = std::time::Instant::now();
    let report = import_csv(&mut conn, points, links, &map, &config).unwrap_or_else(|e| fail(&e.to_string()));
    println!(
        "imported into '{}' ({}): {} points, {} links, {} links skipped · {:.1}s",
        record.name,
        record.db_path,
        report.points,
        report.links,
        report.links_skipped,
        started.elapsed().as_secs_f64()
    );
}

fn fail(msg: &str) -> ! {
    eprintln!("brain_atlas_import: {msg}");
    std::process::exit(1)
}
