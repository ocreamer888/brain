//! Rebuild a brain's memory atlas layout from the command line.
//!   brain_memory_atlas <db-path>
//! Same work as the API's Rebuild button; positions only are written.
fn main() {
    let Some(path) = std::env::args().nth(1) else {
        eprintln!("usage: brain_memory_atlas <db-path>");
        std::process::exit(2);
    };
    let mut conn = rusqlite::Connection::open(&path).unwrap_or_else(|e| {
        eprintln!("{path}: {e}");
        std::process::exit(1)
    });
    conn.busy_timeout(std::time::Duration::from_secs(10)).ok();
    brain::memory_atlas::create_schema(&conn).expect("schema");
    let t = std::time::Instant::now();
    match brain::memory_atlas::rebuild(&mut conn) {
        Ok(run) => println!("layout {run} · {:.1}s · {}", t.elapsed().as_secs_f64(), brain::memory_atlas::status(&conn).unwrap()),
        Err(e) => {
            eprintln!("rebuild failed: {e}");
            std::process::exit(1)
        }
    }
}
