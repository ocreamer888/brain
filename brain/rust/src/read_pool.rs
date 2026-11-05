//! A small fixed-size pool of independent, read-only SQLite connections.
//!
//! G6 (cognitive-architecture-spec.md section 6.2): profiling confirmed the
//! single `Arc<Mutex<Brain>>` genuinely serializes every request, including
//! trivial ones -- throughput was pinned flat regardless of concurrency.
//! SQLite's WAL mode (already on, see store.rs) already supports concurrent
//! readers alongside the one writer; the bottleneck was never SQLite, it was
//! the application wrapping every read in one exclusive Rust-level lock on
//! top of that. This pool lets read-only handlers (e.g. /search) bypass that
//! lock entirely for their SQLite access, while writes keep going through
//! the existing single-writer path unchanged -- SQLite only ever allows one
//! writer at a time regardless of what's built around it, so there was
//! nothing to gain by touching the write path.
//!
//! Each connection is fully independent (its own OS-level handle), opened
//! read-only against the same file. Checked out via a bounded channel: if
//! all connections are in use, `acquire()` blocks until one is returned --
//! natural backpressure instead of opening unboundedly many connections.

use std::path::Path;
use std::sync::mpsc::{sync_channel, Receiver, SyncSender};
use std::sync::Mutex;

use rusqlite::{Connection, OpenFlags};

use crate::error::BrainError;

pub struct ReadPool {
    tx: SyncSender<Connection>,
    rx: Mutex<Receiver<Connection>>,
}

impl ReadPool {
    /// Opens `size` independent read-only connections against `path`.
    /// Returns an error if the very first connection can't be opened (e.g.
    /// the file doesn't exist yet); callers on a fresh/in-memory DB should
    /// treat pool construction as optional, not fall back silently.
    pub fn open(path: impl AsRef<Path>, size: usize) -> Result<Self, BrainError> {
        let path = path.as_ref();
        let (tx, rx) = sync_channel(size.max(1));
        for _ in 0..size.max(1) {
            let conn = Connection::open_with_flags(
                path,
                OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_NO_MUTEX,
            )
            .map_err(|e| BrainError::Database(e.to_string()))?;
            // sync_channel(size) never blocks on the first `size` sends.
            tx.send(conn).expect("pool channel just created, cannot be full or closed");
        }
        Ok(Self { tx, rx: Mutex::new(rx) })
    }

    /// Borrow a connection, blocking if every connection is currently
    /// checked out. Returned to the pool automatically when the guard drops.
    pub fn acquire(&self) -> PooledConn<'_> {
        let conn = self
            .rx
            .lock()
            .unwrap_or_else(|p| p.into_inner())
            .recv()
            .expect("the sender half lives as long as the pool, so recv cannot fail");
        PooledConn { conn: Some(conn), pool: self }
    }
}

pub struct PooledConn<'a> {
    conn: Option<Connection>,
    pool: &'a ReadPool,
}

impl std::ops::Deref for PooledConn<'_> {
    type Target = Connection;
    fn deref(&self) -> &Connection {
        self.conn.as_ref().expect("conn is only None after drop")
    }
}

impl Drop for PooledConn<'_> {
    fn drop(&mut self) {
        if let Some(conn) = self.conn.take() {
            // A full channel here would mean more sends than the pool's
            // original size, which can't happen -- every acquire() removes
            // exactly one connection that only this drop ever returns.
            let _ = self.pool.tx.send(conn);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::Arc;

    fn make_db(dir: &std::path::Path) -> std::path::PathBuf {
        let path = dir.join("test.db");
        let conn = Connection::open(&path).unwrap();
        conn.execute_batch(
            "PRAGMA journal_mode=WAL;
             CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT);
             INSERT INTO t (v) VALUES ('hello');",
        )
        .unwrap();
        path
    }

    #[test]
    fn acquire_reads_committed_data() {
        let dir = tempfile::tempdir().unwrap();
        let path = make_db(dir.path());
        let pool = ReadPool::open(&path, 2).unwrap();
        let conn = pool.acquire();
        let v: String = conn.query_row("SELECT v FROM t WHERE id=1", [], |r| r.get(0)).unwrap();
        assert_eq!(v, "hello");
    }

    #[test]
    fn connection_returns_to_pool_on_drop() {
        let dir = tempfile::tempdir().unwrap();
        let path = make_db(dir.path());
        let pool = ReadPool::open(&path, 1).unwrap();
        {
            let _c = pool.acquire();
        } // dropped here
        // If drop didn't return the connection, this would block forever
        // (pool size 1). Test has an implicit timeout via the test harness.
        let _c2 = pool.acquire();
    }

    #[test]
    fn read_pool_sees_writes_committed_by_a_separate_connection() {
        let dir = tempfile::tempdir().unwrap();
        let path = make_db(dir.path());
        let pool = ReadPool::open(&path, 1).unwrap();

        let writer = Connection::open(&path).unwrap();
        writer.execute("INSERT INTO t (v) VALUES ('world')", []).unwrap();

        let conn = pool.acquire();
        let count: i64 = conn.query_row("SELECT COUNT(*) FROM t", [], |r| r.get(0)).unwrap();
        assert_eq!(count, 2);
    }

    #[test]
    fn concurrent_acquire_from_multiple_threads() {
        let dir = tempfile::tempdir().unwrap();
        let path = make_db(dir.path());
        let pool = Arc::new(ReadPool::open(&path, 4).unwrap());

        let handles: Vec<_> = (0..8)
            .map(|_| {
                let pool = pool.clone();
                std::thread::spawn(move || {
                    let conn = pool.acquire();
                    let v: String =
                        conn.query_row("SELECT v FROM t WHERE id=1", [], |r| r.get(0)).unwrap();
                    assert_eq!(v, "hello");
                })
            })
            .collect();
        for h in handles {
            h.join().unwrap();
        }
    }
}
