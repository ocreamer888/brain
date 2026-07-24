use crate::store::MetadataStore;

/// Drain up to `pending_jobs(10)` and handle known kinds. Unknown kinds are marked failed.
pub fn process_once(store: &MetadataStore) -> Result<usize, crate::BrainError> {
    let jobs = store.pending_jobs(10)?;
    let mut processed = 0;
    for job in jobs {
        match job.kind.as_str() {
            "noop" => {
                store.mark_job_done(&job.id)?;
                processed += 1;
            }
            _ => {
                store.mark_job_failed(&job.id, "unknown kind")?;
            }
        }
    }
    Ok(processed)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::store::MetadataStore;

    #[test]
    fn processes_noop_jobs() {
        let store = MetadataStore::open_in_memory().unwrap();
        store.enqueue_job("noop", "{}").unwrap();
        let n = process_once(&store).unwrap();
        assert_eq!(n, 1);
        assert!(store.pending_jobs(10).unwrap().is_empty());
    }
}
