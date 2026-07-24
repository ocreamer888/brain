use std::path::Path;

use chrono::{DateTime, Utc};
use rusqlite::{params, Connection};
use uuid::Uuid;

use crate::{
    BrainError, FeedbackEventRecord, FeedbackEventType, FeedbackSource, Memory, MemoryMetadata,
    MemorySource, MemoryType,
};

/// RFC 4122 OID namespace (same as Python `uuid.NAMESPACE_OID`).
const ENTITY_NS: Uuid = Uuid::from_bytes([
    0x6b, 0xa7, 0xb8, 0x12, 0x9d, 0xad, 0x11, 0xd1, 0x80, 0xb4, 0x00, 0xc0, 0x4f, 0xd4, 0x30,
    0xc8,
]);

pub fn normalize_entity_name(name: &str) -> Option<String> {
    let n = name
        .split_whitespace()
        .collect::<Vec<_>>()
        .join(" ")
        .to_lowercase();
    if n.is_empty() {
        None
    } else {
        Some(n)
    }
}

pub fn entity_id_for(name_normalized: &str) -> String {
    Uuid::new_v5(&ENTITY_NS, format!("entity:{name_normalized}").as_bytes()).to_string()
}

pub struct MetadataStore {
    conn: Connection,
}

/// Row from the `jobs` queue table (see `ensure_queue_schema`).
#[derive(Debug, Clone)]
pub struct QueuedJob {
    pub id: String,
    pub kind: String,
    pub payload: String,
    pub attempts: u32,
    pub last_error: Option<String>,
}

impl MetadataStore {
    pub fn open(path: impl AsRef<Path>) -> Result<Self, BrainError> {
        let conn = Connection::open(path).map_err(|e| BrainError::Database(e.to_string()))?;
        conn.execute_batch("PRAGMA journal_mode=WAL;")
            .map_err(|e| BrainError::Database(e.to_string()))?;
        let store = Self { conn };
        store.create_tables()?;
        Ok(store)
    }

    pub fn open_in_memory() -> Result<Self, BrainError> {
        let conn =
            Connection::open_in_memory().map_err(|e| BrainError::Database(e.to_string()))?;
        let store = Self { conn };
        store.create_tables()?;
        Ok(store)
    }

    fn create_tables(&self) -> Result<(), BrainError> {
        self.conn
            .execute_batch(
                "
            CREATE TABLE IF NOT EXISTS memories (
                id TEXT PRIMARY KEY,
                content TEXT NOT NULL,
                type TEXT NOT NULL,
                project TEXT NOT NULL DEFAULT 'general',
                tags TEXT NOT NULL DEFAULT '',
                timestamp TEXT NOT NULL,
                source TEXT NOT NULL,
                session_id TEXT NOT NULL DEFAULT '',
                importance REAL NOT NULL DEFAULT 0.5,
                file_path TEXT,
                thread_id TEXT,
                title TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_memories_type ON memories(type);
            CREATE INDEX IF NOT EXISTS idx_memories_project ON memories(project);
            ",
            )
            .map_err(|e| BrainError::Database(e.to_string()))?;
        // Idempotent ADD COLUMN statements — no-op if already present.
        let _ = self.conn.execute_batch("ALTER TABLE memories ADD COLUMN embedding BLOB;");
        let _ = self.conn.execute_batch("ALTER TABLE memories ADD COLUMN parent_id TEXT;");
        let _ = self.conn.execute_batch("ALTER TABLE memories ADD COLUMN event_time TEXT;");
        let _ = self.conn.execute_batch("ALTER TABLE memories ADD COLUMN salience REAL NOT NULL DEFAULT 0.5;");
        let _ = self.conn.execute_batch("ALTER TABLE memories ADD COLUMN superseded_by TEXT;");
        let _ = self.conn.execute_batch("ALTER TABLE memories ADD COLUMN derived_from TEXT;");
        let _ = self.conn.execute_batch(
            "CREATE INDEX IF NOT EXISTS idx_memories_parent ON memories(parent_id) WHERE parent_id IS NOT NULL;",
        );
        let _ = self.conn.execute_batch(
            "CREATE INDEX IF NOT EXISTS idx_memories_superseded ON memories(superseded_by) WHERE superseded_by IS NOT NULL;",
        );

        // FTS5 index for BM25 hybrid search
        let fts_existed: bool = self
            .conn
            .query_row(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='memories_fts'",
                [],
                |row| row.get::<_, i64>(0),
            )
            .unwrap_or(0)
            > 0;
        let _ = self.conn.execute_batch(
            "CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
                id UNINDEXED,
                content,
                title,
                tokenize='porter ascii'
            );",
        );
        // One-time backfill — only runs when the table was just created
        if !fts_existed {
            let _ = self.conn.execute_batch(
                "INSERT INTO memories_fts(rowid, id, content, title)
                 SELECT rowid, id, content, COALESCE(title, '') FROM memories;",
            );
        }
        self.conn
            .execute_batch(
                "
            CREATE TABLE IF NOT EXISTS feedback_events (
                id TEXT PRIMARY KEY,
                ts TEXT NOT NULL,
                event_type TEXT NOT NULL,
                memory_id TEXT,
                query TEXT,
                session_id TEXT,
                project TEXT,
                source TEXT NOT NULL,
                payload TEXT NOT NULL DEFAULT '{}',
                idempotency_key TEXT UNIQUE
            );
            CREATE INDEX IF NOT EXISTS idx_feedback_ts ON feedback_events(ts);
            ",
            )
            .map_err(|e| BrainError::Database(e.to_string()))?;
        self.ensure_queue_schema()?;
        self.conn
            .execute_batch(
                "CREATE TABLE IF NOT EXISTS curation_events (
                    id TEXT PRIMARY KEY,
                    ts TEXT NOT NULL,
                    fact_id TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    sim REAL,
                    reason TEXT,
                    model TEXT,
                    batch_id TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_curation_ts ON curation_events(ts);
                CREATE INDEX IF NOT EXISTS idx_curation_batch ON curation_events(batch_id);
                CREATE TABLE IF NOT EXISTS backfill_batches (
                    batch_id TEXT PRIMARY KEY,
                    project TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    p1_before REAL,
                    p1_after REAL,
                    rolled_back INTEGER NOT NULL DEFAULT 0,
                    facts_inserted INTEGER NOT NULL DEFAULT 0,
                    facts_superseded INTEGER NOT NULL DEFAULT 0
                );",
            )
            .map_err(|e| BrainError::Database(e.to_string()))?;
        self.conn
            .execute_batch(
                "CREATE TABLE IF NOT EXISTS entities (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    name_normalized TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_entities_name_norm ON entities(name_normalized);

                CREATE TABLE IF NOT EXISTS edges (
                    id TEXT PRIMARY KEY,
                    src_memory_id TEXT NOT NULL,
                    dst_entity_id TEXT NOT NULL,
                    relation_type TEXT NOT NULL DEFAULT 'mentions',
                    weight REAL NOT NULL DEFAULT 1.0,
                    created_at TEXT NOT NULL,
                    UNIQUE(src_memory_id, dst_entity_id, relation_type)
                );
                CREATE INDEX IF NOT EXISTS idx_edges_src ON edges(src_memory_id);
                CREATE INDEX IF NOT EXISTS idx_edges_dst ON edges(dst_entity_id);",
            )
            .map_err(|e| BrainError::Database(e.to_string()))
    }

    pub fn ensure_queue_schema(&self) -> Result<(), BrainError> {
        self.conn
            .execute_batch(
                "CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                payload TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                last_error TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS jobs_status_idx ON jobs(status);",
            )
            .map_err(|e| BrainError::Database(e.to_string()))
    }

    pub fn enqueue_job(&self, kind: &str, payload: &str) -> Result<String, BrainError> {
        let id = Uuid::new_v4().to_string();
        self.conn
            .execute(
                "INSERT INTO jobs(id, kind, payload) VALUES(?, ?, ?)",
                params![id, kind, payload],
            )
            .map_err(|e| BrainError::Database(e.to_string()))?;
        Ok(id)
    }

    pub fn pending_jobs(&self, limit: u32) -> Result<Vec<QueuedJob>, BrainError> {
        let limit = i64::from(limit);
        let mut stmt = self
            .conn
            .prepare(
                "SELECT id, kind, payload, attempts, last_error FROM jobs
             WHERE status='pending' ORDER BY created_at ASC LIMIT ?",
            )
            .map_err(|e| BrainError::Database(e.to_string()))?;
        let rows = stmt
            .query_map([limit], |row| {
                Ok(QueuedJob {
                    id: row.get(0)?,
                    kind: row.get(1)?,
                    payload: row.get(2)?,
                    attempts: row.get::<_, i64>(3)? as u32,
                    last_error: row.get(4)?,
                })
            })
            .map_err(|e| BrainError::Database(e.to_string()))?
            .collect::<Result<Vec<_>, _>>()
            .map_err(|e| BrainError::Database(e.to_string()))?;
        Ok(rows)
    }

    pub fn mark_job_done(&self, id: &str) -> Result<(), BrainError> {
        self.conn
            .execute(
                "UPDATE jobs SET status='done' WHERE id=?",
                params![id],
            )
            .map_err(|e| BrainError::Database(e.to_string()))?;
        Ok(())
    }

    pub fn mark_job_failed(&self, id: &str, err: &str) -> Result<(), BrainError> {
        self.conn
            .execute(
                "UPDATE jobs SET
                    attempts = attempts + 1,
                    last_error = ?1,
                    status = CASE WHEN attempts + 1 >= 5 THEN 'failed' ELSE 'pending' END
                 WHERE id = ?2",
                params![err, id],
            )
            .map_err(|e| BrainError::Database(e.to_string()))?;
        Ok(())
    }

    /// Current `jobs.status` for debugging/tests.
    pub fn job_status(&self, id: &str) -> Result<String, BrainError> {
        self.conn
            .query_row(
                "SELECT status FROM jobs WHERE id = ?1",
                params![id],
                |row| row.get::<_, String>(0),
            )
            .map_err(|e| BrainError::Database(e.to_string()))
    }

    pub fn upsert_memory(&self, memory: &Memory) -> Result<(), BrainError> {
        let meta = &memory.metadata;
        let emb_bytes: Option<Vec<u8>> = memory.embedding.as_deref().map(embedding_to_bytes);
        let event_time_str = meta.event_time.as_ref().map(|dt| dt.to_rfc3339());
        self.conn
            .execute(
                "INSERT INTO memories
                    (id, content, type, project, tags, timestamp, source, session_id, importance,
                     file_path, thread_id, title, embedding,
                     parent_id, event_time, salience, superseded_by, derived_from)
                 VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12, ?13,
                         ?14, ?15, ?16, ?17, ?18)
                 ON CONFLICT(id) DO UPDATE SET
                    content = excluded.content,
                    type = excluded.type,
                    project = excluded.project,
                    tags = excluded.tags,
                    timestamp = excluded.timestamp,
                    source = excluded.source,
                    session_id = excluded.session_id,
                    importance = excluded.importance,
                    file_path = excluded.file_path,
                    thread_id = excluded.thread_id,
                    title = excluded.title,
                    embedding = COALESCE(excluded.embedding, memories.embedding),
                    parent_id = excluded.parent_id,
                    event_time = excluded.event_time,
                    salience = excluded.salience,
                    superseded_by = excluded.superseded_by,
                    derived_from = excluded.derived_from",
                params![
                    memory.id,
                    memory.content,
                    serde_json::to_string(&meta.memory_type)
                        .map_err(|e| BrainError::Database(e.to_string()))?,
                    meta.project,
                    meta.tags,
                    meta.timestamp.to_rfc3339(),
                    serde_json::to_string(&meta.source)
                        .map_err(|e| BrainError::Database(e.to_string()))?,
                    meta.session_id,
                    meta.importance,
                    meta.file_path,
                    meta.thread_id,
                    meta.title,
                    emb_bytes,
                    meta.parent_id,
                    event_time_str,
                    meta.salience,
                    meta.superseded_by,
                    meta.derived_from,
                ],
            )
            .map_err(|e| BrainError::Database(e.to_string()))?;

        // Sync FTS5: delete stale entry (no-op on first insert), then re-insert
        // Delete before insert so rowid is stable on updates
        let _ = self.conn.execute(
            "DELETE FROM memories_fts WHERE rowid = (SELECT rowid FROM memories WHERE id = ?1)",
            params![memory.id],
        );
        let _ = self.conn.execute(
            "INSERT INTO memories_fts(rowid, id, content, title)
             SELECT rowid, id, content, COALESCE(title, '') FROM memories WHERE id = ?1",
            params![memory.id],
        );

        Ok(())
    }

    pub fn get_memory(&self, id: &str) -> Result<Option<Memory>, BrainError> {
        let result = self.conn.query_row(
            "SELECT id, content, type, project, tags, timestamp, source, session_id, importance,
                    file_path, thread_id, title, embedding,
                    parent_id, event_time, salience, superseded_by, derived_from
             FROM memories WHERE id = ?1",
            params![id],
            |row| memory_from_row(row),
        );

        match result {
            Ok(m) => Ok(Some(m)),
            Err(rusqlite::Error::QueryReturnedNoRows) => Ok(None),
            Err(e) => Err(BrainError::Database(e.to_string())),
        }
    }

    pub fn get_memories_by_ids(&self, ids: &[&str]) -> Result<Vec<Memory>, BrainError> {
        let mut out = Vec::new();
        for id in ids {
            if let Some(m) = self.get_memory(id)? {
                out.push(m);
            }
        }
        Ok(out)
    }

    pub fn timeline_around(
        &self,
        anchor_id: &str,
        before: u32,
        after: u32,
    ) -> Result<Vec<Memory>, BrainError> {
        let anchor_ts: String = self.conn.query_row(
            "SELECT timestamp FROM memories WHERE id = ?1",
            params![anchor_id],
            |row| row.get::<_, String>(0),
        )
        .map_err(|e| match e {
            rusqlite::Error::QueryReturnedNoRows => BrainError::NotFound(anchor_id.to_string()),
            _ => BrainError::Database(e.to_string()),
        })?;

        let before_lim = i64::from(before);
        let mut stmt = self
            .conn
            .prepare(
                "SELECT id, content, type, project, tags, timestamp, source, session_id, importance,
                        file_path, thread_id, title, embedding,
                        parent_id, event_time, salience, superseded_by, derived_from
                 FROM memories WHERE timestamp < ?1 ORDER BY timestamp DESC LIMIT ?2",
            )
            .map_err(|e| BrainError::Database(e.to_string()))?;
        let mut before_rows: Vec<Memory> = stmt
            .query_map(params![anchor_ts, before_lim], |row| memory_from_row(row))
            .map_err(|e| BrainError::Database(e.to_string()))?
            .collect::<Result<Vec<_>, _>>()
            .map_err(|e| BrainError::Database(e.to_string()))?;
        before_rows.reverse();

        let anchor = self
            .get_memory(anchor_id)?
            .ok_or_else(|| BrainError::NotFound(anchor_id.to_string()))?;

        let after_lim = i64::from(after);
        let mut stmt2 = self
            .conn
            .prepare(
                "SELECT id, content, type, project, tags, timestamp, source, session_id, importance,
                        file_path, thread_id, title, embedding,
                        parent_id, event_time, salience, superseded_by, derived_from
                 FROM memories WHERE timestamp > ?1 ORDER BY timestamp ASC LIMIT ?2",
            )
            .map_err(|e| BrainError::Database(e.to_string()))?;
        let after_rows: Vec<Memory> = stmt2
            .query_map(params![anchor_ts, after_lim], |row| memory_from_row(row))
            .map_err(|e| BrainError::Database(e.to_string()))?
            .collect::<Result<Vec<_>, _>>()
            .map_err(|e| BrainError::Database(e.to_string()))?;

        let mut out = before_rows;
        out.push(anchor);
        out.extend(after_rows);
        Ok(out)
    }

    pub fn delete_memories(&self, ids: &[&str]) -> Result<usize, BrainError> {
        let mut removed = 0;
        for id in ids {
            // FTS5 delete first — needs memories.rowid to still exist
            let _ = self.conn.execute(
                "DELETE FROM memories_fts WHERE rowid = (SELECT rowid FROM memories WHERE id = ?1)",
                params![id],
            );
            let n = self
                .conn
                .execute("DELETE FROM memories WHERE id = ?1", params![id])
                .map_err(|e| BrainError::Database(e.to_string()))?;
            removed += n;
        }
        Ok(removed)
    }

    /// BM25 full-text search. Returns memory ids ordered best-first.
    /// Returns empty vec (not an error) if query is unsearchable.
    pub fn fts_search(&self, query: &str, n: usize) -> Result<Vec<String>, BrainError> {
        let clean = sanitize_fts_query(query);
        if clean.is_empty() {
            return Ok(vec![]);
        }
        let mut stmt = self
            .conn
            .prepare(
                "SELECT id FROM memories_fts WHERE memories_fts MATCH ?1
                 ORDER BY bm25(memories_fts) LIMIT ?2",
            )
            .map_err(|e| BrainError::Database(e.to_string()))?;
        let ids: Vec<String> = stmt
            .query_map(params![clean, n as i64], |row| row.get(0))
            .map_err(|e| BrainError::Database(e.to_string()))?
            .collect::<Result<Vec<_>, _>>()
            .map_err(|e| BrainError::Database(e.to_string()))?;
        Ok(ids)
    }

    pub fn count_memories(&self) -> Result<usize, BrainError> {
        self.conn
            .query_row("SELECT COUNT(*) FROM memories", [], |row| {
                row.get::<_, usize>(0)
            })
            .map_err(|e| BrainError::Database(e.to_string()))
    }

    pub fn count_memories_by_type(&self) -> Result<std::collections::HashMap<String, usize>, BrainError> {
        let mut stmt = self.conn
            .prepare("SELECT type, COUNT(*) FROM memories GROUP BY type")
            .map_err(|e| BrainError::Database(e.to_string()))?;
        let mut map = std::collections::HashMap::new();
        let rows = stmt.query_map([], |row| {
            Ok((row.get::<_, String>(0)?, row.get::<_, usize>(1)?))
        }).map_err(|e| BrainError::Database(e.to_string()))?;
        for row in rows {
            let (raw_type, count) = row.map_err(|e| BrainError::Database(e.to_string()))?;
            let key = raw_type.trim_matches('"').to_string();
            map.insert(key, count);
        }
        Ok(map)
    }

    pub fn count_sessions(&self) -> Result<usize, BrainError> {
        self.conn
            .query_row(
                "SELECT COUNT(DISTINCT session_id) FROM memories WHERE session_id != ''",
                [],
                |row| row.get::<_, usize>(0),
            )
            .map_err(|e| BrainError::Database(e.to_string()))
    }

    pub fn count_feedback_events(&self) -> Result<usize, BrainError> {
        self.conn
            .query_row("SELECT COUNT(*) FROM feedback_events", [], |row| {
                row.get::<_, usize>(0)
            })
            .map_err(|e| BrainError::Database(e.to_string()))
    }

    pub fn feedback_last_event_ts(&self) -> Result<Option<String>, BrainError> {
        let result = self.conn.query_row(
            "SELECT ts FROM feedback_events ORDER BY ts DESC LIMIT 1",
            [],
            |row| row.get::<_, String>(0),
        );
        match result {
            Ok(ts) => Ok(Some(ts)),
            Err(rusqlite::Error::QueryReturnedNoRows) => Ok(None),
            Err(e) => Err(BrainError::Database(e.to_string())),
        }
    }

    fn feedback_id_by_idempotency_key(&self, key: &str) -> Result<Option<String>, BrainError> {
        let result = self.conn.query_row(
            "SELECT id FROM feedback_events WHERE idempotency_key = ?1",
            params![key],
            |row| row.get::<_, String>(0),
        );
        match result {
            Ok(id) => Ok(Some(id)),
            Err(rusqlite::Error::QueryReturnedNoRows) => Ok(None),
            Err(e) => Err(BrainError::Database(e.to_string())),
        }
    }

    /// Append a feedback event. If `idempotency_key` matches an existing row, returns that row's id.
    pub fn append_feedback(
        &self,
        event_type: FeedbackEventType,
        memory_id: Option<&str>,
        query: Option<&str>,
        session_id: Option<&str>,
        project: Option<&str>,
        source: FeedbackSource,
        payload: serde_json::Value,
        idempotency_key: Option<&str>,
    ) -> Result<String, BrainError> {
        if let Some(key) = idempotency_key {
            if let Some(id) = self.feedback_id_by_idempotency_key(key)? {
                return Ok(id);
            }
        }
        let id = uuid::Uuid::new_v4().to_string();
        let ts = Utc::now().to_rfc3339();
        let payload_str =
            serde_json::to_string(&payload).map_err(|e| BrainError::Database(e.to_string()))?;
        self.conn
            .execute(
                "INSERT INTO feedback_events (id, ts, event_type, memory_id, query, session_id, project, source, payload, idempotency_key)
                 VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10)",
                params![
                    id,
                    ts,
                    event_type.as_str(),
                    memory_id,
                    query,
                    session_id,
                    project,
                    source.as_str(),
                    payload_str,
                    idempotency_key,
                ],
            )
            .map_err(|e| BrainError::Database(e.to_string()))?;
        Ok(id)
    }

    /// Events with `ts >= since` (RFC3339 string comparison).
    pub fn list_feedback_since(&self, since: DateTime<Utc>) -> Result<Vec<FeedbackEventRecord>, BrainError> {
        let since_str = since.to_rfc3339();
        let mut stmt = self
            .conn
            .prepare(
                "SELECT id, ts, event_type, memory_id, query, session_id, project, source, payload, idempotency_key
                 FROM feedback_events WHERE ts >= ?1 ORDER BY ts ASC",
            )
            .map_err(|e| BrainError::Database(e.to_string()))?;
        let rows = stmt
            .query_map(params![since_str], |row| {
                Ok((
                    row.get::<_, String>(0)?,
                    row.get::<_, String>(1)?,
                    row.get::<_, String>(2)?,
                    row.get::<_, Option<String>>(3)?,
                    row.get::<_, Option<String>>(4)?,
                    row.get::<_, Option<String>>(5)?,
                    row.get::<_, Option<String>>(6)?,
                    row.get::<_, String>(7)?,
                    row.get::<_, String>(8)?,
                    row.get::<_, Option<String>>(9)?,
                ))
            })
            .map_err(|e| BrainError::Database(e.to_string()))?;

        let mut out = Vec::new();
        for row in rows {
            let (id, ts, event_type_s, memory_id, query, session_id, project, source_s, payload_s, idempotency_key) =
                row.map_err(|e| BrainError::Database(e.to_string()))?;
            let event_type = FeedbackEventType::from_str(&event_type_s).ok_or_else(|| {
                BrainError::Database(format!("unknown feedback event_type: {event_type_s}"))
            })?;
            let source = FeedbackSource::from_str(&source_s).ok_or_else(|| {
                BrainError::Database(format!("unknown feedback source: {source_s}"))
            })?;
            let payload: serde_json::Value = serde_json::from_str(&payload_s)
                .map_err(|e| BrainError::Database(e.to_string()))?;
            out.push(FeedbackEventRecord {
                id,
                ts,
                event_type,
                memory_id,
                query,
                session_id,
                project,
                source,
                payload,
                idempotency_key,
            });
        }
        Ok(out)
    }

    pub fn get_all_documents(&self) -> Result<Vec<Memory>, BrainError> {
        let mut stmt = self.conn.prepare(
            "SELECT id, content, type, project, tags, timestamp, source, session_id, importance,
                    file_path, thread_id, title, embedding,
                    parent_id, event_time, salience, superseded_by, derived_from
             FROM memories ORDER BY timestamp DESC",
        ).map_err(|e| BrainError::Database(e.to_string()))?;

        let rows = stmt
            .query_map([], |row| memory_from_row(row))
            .map_err(|e| BrainError::Database(e.to_string()))?;

        let mut memories = Vec::new();
        for row in rows {
            memories.push(row.map_err(|e| BrainError::Database(e.to_string()))?);
        }
        Ok(memories)
    }

    pub fn get_embeddings_for_index(&self) -> Result<Vec<(String, Vec<f32>)>, BrainError> {
        let mut stmt = self.conn.prepare(
            "SELECT id, embedding FROM memories WHERE embedding IS NOT NULL"
        ).map_err(|e| BrainError::Database(e.to_string()))?;
        let rows = stmt.query_map([], |row| {
            Ok((row.get::<_, String>(0)?, row.get::<_, Vec<u8>>(1)?))
        }).map_err(|e| BrainError::Database(e.to_string()))?;
        let mut out = Vec::new();
        for row in rows {
            let (id, bytes) = row.map_err(|e| BrainError::Database(e.to_string()))?;
            out.push((id, bytes_to_embedding(&bytes)));
        }
        Ok(out)
    }

    pub fn get_unembedded_ids_and_content(&self) -> Result<Vec<(String, String)>, BrainError> {
        let mut stmt = self.conn.prepare(
            "SELECT id, content FROM memories WHERE embedding IS NULL"
        ).map_err(|e| BrainError::Database(e.to_string()))?;
        let rows = stmt.query_map([], |row| {
            Ok((row.get::<_, String>(0)?, row.get::<_, String>(1)?))
        }).map_err(|e| BrainError::Database(e.to_string()))?;
        rows.map(|r| r.map_err(|e| BrainError::Database(e.to_string()))).collect()
    }

    pub fn update_embedding(&self, id: &str, emb: &[f32]) -> Result<(), BrainError> {
        let bytes = embedding_to_bytes(emb);
        self.conn.execute(
            "UPDATE memories SET embedding = ?1 WHERE id = ?2",
            params![bytes, id],
        ).map_err(|e| BrainError::Database(e.to_string()))?;
        Ok(())
    }

    /// BM25 search scoped to `type = "fact"` only. Returns memory IDs best-first.
    /// Used by Phase 4 fact-preferred retrieval — episode fallback handled in Brain::search.
    pub fn fts_search_facts(&self, query: &str, n: usize) -> Result<Vec<String>, BrainError> {
        let clean = sanitize_fts_query(query);
        if clean.is_empty() {
            return Ok(vec![]);
        }
        let mut stmt = self
            .conn
            .prepare(
                "SELECT f.id FROM memories_fts f
                 JOIN memories m ON m.rowid = f.rowid
                 WHERE memories_fts MATCH ?1 AND m.type = '\"fact\"'
                   AND m.superseded_by IS NULL
                 ORDER BY bm25(memories_fts) LIMIT ?2",
            )
            .map_err(|e| BrainError::Database(e.to_string()))?;
        let ids: Vec<String> = stmt
            .query_map(params![clean, n as i64], |row| row.get(0))
            .map_err(|e| BrainError::Database(e.to_string()))?
            .collect::<Result<Vec<_>, _>>()
            .map_err(|e| BrainError::Database(e.to_string()))?;
        Ok(ids)
    }

    /// Fetch all active (non-superseded) facts linked to an episode ID.
    pub fn get_facts_by_parent(&self, parent_id: &str) -> Result<Vec<Memory>, BrainError> {
        let mut stmt = self.conn.prepare(
            "SELECT id, content, type, project, tags, timestamp, source, session_id, importance,
                    file_path, thread_id, title, embedding,
                    parent_id, event_time, salience, superseded_by, derived_from
             FROM memories
             WHERE parent_id = ?1 AND type = '\"fact\"' AND superseded_by IS NULL
             ORDER BY salience DESC, timestamp ASC",
        ).map_err(|e| BrainError::Database(e.to_string()))?;
        let rows = stmt
            .query_map(params![parent_id], |row| memory_from_row(row))
            .map_err(|e| BrainError::Database(e.to_string()))?
            .collect::<Result<Vec<_>, _>>()
            .map_err(|e| BrainError::Database(e.to_string()))?;
        Ok(rows)
    }

    /// Mark a fact as superseded by a newer fact (soft-delete for audit trail).
    pub fn mark_superseded(&self, old_id: &str, new_id: &str) -> Result<(), BrainError> {
        self.conn
            .execute(
                "UPDATE memories SET superseded_by = ?1 WHERE id = ?2",
                params![new_id, old_id],
            )
            .map_err(|e| BrainError::Database(e.to_string()))?;
        Ok(())
    }

    pub fn update_salience(&self, id: &str, salience: f64) -> Result<bool, BrainError> {
        let rows = self.conn
            .execute(
                "UPDATE memories SET salience = ?1 WHERE id = ?2",
                params![salience, id],
            )
            .map_err(|e| BrainError::Database(e.to_string()))?;
        Ok(rows > 0)
    }

    /// Append a curation decision record for audit and Phase 6 calibration.
    pub fn log_curation_event(
        &self,
        fact_id: &str,
        decision: &str,
        sim: Option<f64>,
        reason: &str,
        model: Option<&str>,
        batch_id: Option<&str>,
    ) -> Result<(), BrainError> {
        let id = Uuid::new_v4().to_string();
        let ts = Utc::now().to_rfc3339();
        self.conn
            .execute(
                "INSERT INTO curation_events (id, ts, fact_id, decision, sim, reason, model, batch_id)
                 VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8)",
                params![id, ts, fact_id, decision, sim, reason, model, batch_id],
            )
            .map_err(|e| BrainError::Database(e.to_string()))?;
        Ok(())
    }

    /// Register a new backfill batch.
    pub fn start_backfill_batch(
        &self,
        batch_id: &str,
        project: &str,
        p1_before: Option<f64>,
    ) -> Result<(), BrainError> {
        let ts = Utc::now().to_rfc3339();
        self.conn
            .execute(
                "INSERT INTO backfill_batches (batch_id, project, started_at, p1_before)
                 VALUES (?1, ?2, ?3, ?4)",
                params![batch_id, project, ts, p1_before],
            )
            .map_err(|e| BrainError::Database(e.to_string()))?;
        Ok(())
    }

    /// Finish a backfill batch — record result or mark rolled back.
    pub fn finish_backfill_batch(
        &self,
        batch_id: &str,
        p1_after: Option<f64>,
        facts_inserted: usize,
        facts_superseded: usize,
        rolled_back: bool,
    ) -> Result<(), BrainError> {
        let ts = Utc::now().to_rfc3339();
        self.conn
            .execute(
                "UPDATE backfill_batches
                 SET finished_at = ?1, p1_after = ?2, facts_inserted = ?3,
                     facts_superseded = ?4, rolled_back = ?5
                 WHERE batch_id = ?6",
                params![
                    ts,
                    p1_after,
                    facts_inserted as i64,
                    facts_superseded as i64,
                    rolled_back as i64,
                    batch_id,
                ],
            )
            .map_err(|e| BrainError::Database(e.to_string()))?;
        Ok(())
    }

    /// Hard-rollback: delete all facts inserted by a batch + clear their superseded_by references.
    /// Called automatically when P@1 drops > 0.05 vs pre-batch baseline.
    pub fn rollback_batch(&self, batch_id: &str) -> Result<usize, BrainError> {
        // Collect fact IDs from this batch via curation_events
        let mut id_stmt = self
            .conn
            .prepare(
                "SELECT DISTINCT fact_id FROM curation_events
                 WHERE batch_id = ?1 AND decision IN ('ADD', 'UPDATE', 'MERGE')",
            )
            .map_err(|e| BrainError::Database(e.to_string()))?;
        let fact_ids: Vec<String> = id_stmt
            .query_map(params![batch_id], |row| row.get(0))
            .map_err(|e| BrainError::Database(e.to_string()))?
            .collect::<Result<Vec<_>, _>>()
            .map_err(|e| BrainError::Database(e.to_string()))?;

        // Clear superseded_by on episodes that were superseded by these batch facts
        for fid in &fact_ids {
            let _ = self.conn.execute(
                "UPDATE memories SET superseded_by = NULL WHERE superseded_by = ?1",
                params![fid],
            );
        }

        // Delete the facts themselves + their FTS entries
        let refs: Vec<&str> = fact_ids.iter().map(String::as_str).collect();
        let removed = self.delete_memories(&refs)?;

        self.finish_backfill_batch(batch_id, None, 0, 0, true)?;
        Ok(removed)
    }

    pub fn upsert_entity(&self, name: &str) -> Result<String, BrainError> {
        let Some(norm) = normalize_entity_name(name) else {
            return Err(BrainError::Database("empty entity name".into()));
        };
        let id = entity_id_for(&norm);
        let now = chrono::Utc::now().to_rfc3339();
        self.conn
            .execute(
                "INSERT INTO entities (id, name, name_normalized, created_at)
                 VALUES (?1, ?2, ?3, ?4)
                 ON CONFLICT(name_normalized) DO NOTHING",
                rusqlite::params![id, name.trim(), norm, now],
            )
            .map_err(|e| BrainError::Database(e.to_string()))?;
        let id: String = self
            .conn
            .query_row(
                "SELECT id FROM entities WHERE name_normalized = ?1",
                [&norm],
                |r| r.get(0),
            )
            .map_err(|e| BrainError::Database(e.to_string()))?;
        Ok(id)
    }

    pub fn link_memory_to_entity(
        &self,
        memory_id: &str,
        entity_id: &str,
        relation_type: &str,
    ) -> Result<(), BrainError> {
        let edge_id = Uuid::new_v4().to_string();
        let now = chrono::Utc::now().to_rfc3339();
        self.conn
            .execute(
                "INSERT INTO edges (id, src_memory_id, dst_entity_id, relation_type, weight, created_at)
                 VALUES (?1, ?2, ?3, ?4, 1.0, ?5)
                 ON CONFLICT(src_memory_id, dst_entity_id, relation_type) DO NOTHING",
                rusqlite::params![edge_id, memory_id, entity_id, relation_type, now],
            )
            .map_err(|e| BrainError::Database(e.to_string()))?;
        Ok(())
    }

    pub fn link_memory_entities(
        &self,
        memory_id: &str,
        names: &[String],
    ) -> Result<usize, BrainError> {
        let mut n = 0usize;
        for name in names {
            if normalize_entity_name(name).is_none() {
                continue;
            }
            let eid = self.upsert_entity(name)?;
            self.link_memory_to_entity(memory_id, &eid, "mentions")?;
            n += 1;
        }
        Ok(n)
    }

    pub fn entities_for_memory(
        &self,
        memory_id: &str,
    ) -> Result<Vec<(String, String)>, BrainError> {
        let mut stmt = self
            .conn
            .prepare(
                "SELECT e.id, e.name FROM entities e
                 JOIN edges x ON x.dst_entity_id = e.id
                 WHERE x.src_memory_id = ?1
                 ORDER BY e.name_normalized",
            )
            .map_err(|e| BrainError::Database(e.to_string()))?;
        let rows = stmt
            .query_map([memory_id], |r| Ok((r.get(0)?, r.get(1)?)))
            .map_err(|e| BrainError::Database(e.to_string()))?;
        rows.collect::<Result<Vec<_>, _>>()
            .map_err(|e| BrainError::Database(e.to_string()))
    }

    pub fn neighbor_memory_ids(
        &self,
        memory_ids: &[String],
        exclude_superseded: bool,
    ) -> Result<Vec<String>, BrainError> {
        if memory_ids.is_empty() {
            return Ok(vec![]);
        }
        let placeholders = memory_ids.iter().map(|_| "?").collect::<Vec<_>>().join(",");
        let superseded_clause = if exclude_superseded {
            "AND (m.superseded_by IS NULL OR m.superseded_by = '')"
        } else {
            ""
        };
        let sql = format!(
            "SELECT DISTINCT e2.src_memory_id
             FROM edges e1
             JOIN edges e2 ON e1.dst_entity_id = e2.dst_entity_id
             JOIN memories m ON m.id = e2.src_memory_id
             WHERE e1.src_memory_id IN ({placeholders})
               AND e2.src_memory_id NOT IN ({placeholders})
               {superseded_clause}"
        );
        let mut stmt = self
            .conn
            .prepare(&sql)
            .map_err(|e| BrainError::Database(e.to_string()))?;
        let params: Vec<&dyn rusqlite::ToSql> = memory_ids
            .iter()
            .chain(memory_ids.iter())
            .map(|s| s as &dyn rusqlite::ToSql)
            .collect();
        let rows = stmt
            .query_map(params.as_slice(), |r| r.get::<_, String>(0))
            .map_err(|e| BrainError::Database(e.to_string()))?;
        rows.collect::<Result<Vec<_>, _>>()
            .map_err(|e| BrainError::Database(e.to_string()))
    }

    #[cfg(test)]
    fn table_exists(&self, name: &str) -> Result<bool, BrainError> {
        let n: i64 = self
            .conn
            .query_row(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?1",
                [name],
                |r| r.get(0),
            )
            .map_err(|e| BrainError::Database(e.to_string()))?;
        Ok(n > 0)
    }
}

fn memory_from_row(row: &rusqlite::Row<'_>) -> Result<Memory, rusqlite::Error> {
    let id: String = row.get(0)?;
    let content: String = row.get(1)?;
    let type_str: String = row.get(2)?;
    let project: String = row.get(3)?;
    let tags: String = row.get(4)?;
    let timestamp: String = row.get(5)?;
    let source_str: String = row.get(6)?;
    let session_id: String = row.get(7)?;
    let importance: f64 = row.get(8)?;
    let file_path: Option<String> = row.get(9)?;
    let thread_id: Option<String> = row.get(10)?;
    let title: Option<String> = row.get(11)?;
    let emb_bytes: Option<Vec<u8>> = row.get(12)?;
    // Fact-layer columns (nullable — NULL for all pre-existing rows)
    let parent_id: Option<String> = row.get(13)?;
    let event_time_str: Option<String> = row.get(14)?;
    let salience: f64 = row.get::<_, Option<f64>>(15)?.unwrap_or(0.5);
    let superseded_by: Option<String> = row.get(16)?;
    let derived_from: Option<String> = row.get(17)?;

    let memory_type: MemoryType = serde_json::from_str(&type_str).map_err(|e| {
        rusqlite::Error::FromSqlConversionFailure(
            2,
            rusqlite::types::Type::Text,
            Box::new(e),
        )
    })?;
    let source: MemorySource = serde_json::from_str(&source_str).map_err(|e| {
        rusqlite::Error::FromSqlConversionFailure(
            6,
            rusqlite::types::Type::Text,
            Box::new(e),
        )
    })?;
    let timestamp = chrono::DateTime::parse_from_rfc3339(&timestamp)
        .map(|dt| dt.with_timezone(&Utc))
        .map_err(|e| {
            rusqlite::Error::FromSqlConversionFailure(
                5,
                rusqlite::types::Type::Text,
                Box::new(e),
            )
        })?;
    let event_time = event_time_str.as_deref().and_then(|s| {
        chrono::DateTime::parse_from_rfc3339(s)
            .map(|dt| dt.with_timezone(&Utc))
            .ok()
    });

    Ok(Memory {
        id,
        content,
        metadata: MemoryMetadata {
            memory_type,
            project,
            tags,
            timestamp,
            source,
            session_id,
            importance,
            file_path,
            thread_id,
            title,
            parent_id,
            event_time,
            salience,
            superseded_by,
            derived_from,
        },
        embedding: emb_bytes.map(|b| bytes_to_embedding(&b)),
    })
}

fn embedding_to_bytes(emb: &[f32]) -> Vec<u8> {
    emb.iter().flat_map(|f| f.to_le_bytes()).collect()
}

fn bytes_to_embedding(bytes: &[u8]) -> Vec<f32> {
    bytes.chunks_exact(4)
        .map(|b| f32::from_le_bytes([b[0], b[1], b[2], b[3]]))
        .collect()
}

/// Strip FTS5 special characters so arbitrary query text doesn't cause parse errors.
/// Keeps alphanumeric, spaces, hyphens, and apostrophes (common in English).
fn sanitize_fts_query(query: &str) -> String {
    query
        .chars()
        .map(|c| {
            if c.is_alphanumeric() || c == ' ' || c == '-' || c == '\'' {
                c
            } else {
                ' '
            }
        })
        .collect::<String>()
        .split_whitespace()
        .filter(|t| t.len() >= 2)
        .collect::<Vec<_>>()
        .join(" ")
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::TimeZone;
    use tempfile::TempDir;

    fn test_metadata() -> MemoryMetadata {
        MemoryMetadata {
            memory_type: MemoryType::Solution,
            project: "test".into(),
            tags: "rust,test".into(),
            timestamp: Utc::now(),
            source: MemorySource::ClaudeCodeSession,
            session_id: String::new(),
            importance: 0.5,
            file_path: None,
            thread_id: None,
            title: None,
            parent_id: None,
            event_time: None,
            salience: 0.5,
            superseded_by: None,
            derived_from: None,
        }
    }

    #[test]
    fn open_creates_tables() {
        let dir = TempDir::new().unwrap();
        let store = MetadataStore::open(dir.path().join("brain.db")).unwrap();
        assert_eq!(store.count_memories().unwrap(), 0);
    }

    #[test]
    fn upsert_and_get_memory() {
        let store = MetadataStore::open_in_memory().unwrap();
        let memory = Memory {
            id: "test-1".into(),
            content: "hello world".into(),
            metadata: test_metadata(),
            embedding: None,
        };
        store.upsert_memory(&memory).unwrap();
        let fetched = store.get_memory("test-1").unwrap().unwrap();
        assert_eq!(fetched.content, "hello world");
        assert_eq!(fetched.metadata.project, "test");
        assert_eq!(fetched.metadata.memory_type, MemoryType::Solution);
    }

    #[test]
    fn get_memories_by_ids_preserves_request_order() {
        let store = MetadataStore::open_in_memory().unwrap();
        for (id, body) in [("a", "one"), ("b", "two")] {
            store
                .upsert_memory(&Memory {
                    id: id.into(),
                    content: body.into(),
                    metadata: test_metadata(),
                    embedding: None,
                })
                .unwrap();
        }
        let rows = store.get_memories_by_ids(&["b", "a"]).unwrap();
        assert_eq!(rows.len(), 2);
        assert_eq!(rows[0].id, "b");
        assert_eq!(rows[1].id, "a");
    }

    #[test]
    fn timeline_returns_neighbors_by_timestamp() {
        let store = MetadataStore::open_in_memory().unwrap();
        for i in 0i64..5 {
            let mut meta = test_metadata();
            meta.timestamp = Utc
                .with_ymd_and_hms(2026, 4, 20, 0, 0, i as u32)
                .unwrap();
            store
                .upsert_memory(&Memory {
                    id: format!("m{i}"),
                    content: format!("content{i}"),
                    metadata: meta,
                    embedding: None,
                })
                .unwrap();
        }
        let rows = store.timeline_around("m2", 1, 1).unwrap();
        assert_eq!(rows.len(), 3);
        assert_eq!(rows[0].id, "m1");
        assert_eq!(rows[1].id, "m2");
        assert_eq!(rows[2].id, "m3");
    }

    #[test]
    fn upsert_updates_existing() {
        let store = MetadataStore::open_in_memory().unwrap();
        let mut memory = Memory {
            id: "test-1".into(),
            content: "version 1".into(),
            metadata: test_metadata(),
            embedding: None,
        };
        store.upsert_memory(&memory).unwrap();
        memory.content = "version 2".into();
        store.upsert_memory(&memory).unwrap();
        assert_eq!(store.count_memories().unwrap(), 1);
        let fetched = store.get_memory("test-1").unwrap().unwrap();
        assert_eq!(fetched.content, "version 2");
    }

    #[test]
    fn delete_memories_removes_entries() {
        let store = MetadataStore::open_in_memory().unwrap();
        for i in 0..3 {
            store
                .upsert_memory(&Memory {
                    id: format!("test-{i}"),
                    content: format!("content {i}"),
                    metadata: test_metadata(),
                    embedding: None,
                })
                .unwrap();
        }
        let removed = store.delete_memories(&["test-0", "test-2"]).unwrap();
        assert_eq!(removed, 2);
        assert_eq!(store.count_memories().unwrap(), 1);
    }

    #[test]
    fn get_memory_returns_none_for_missing() {
        let store = MetadataStore::open_in_memory().unwrap();
        assert!(store.get_memory("nonexistent").unwrap().is_none());
    }

    #[test]
    fn count_sessions_distinct() {
        let store = MetadataStore::open_in_memory().unwrap();
        for i in 0..3 {
            let mut meta = test_metadata();
            meta.session_id = if i < 2 {
                "session-a".into()
            } else {
                "session-b".into()
            };
            store
                .upsert_memory(&Memory {
                    id: format!("m-{i}"),
                    content: format!("c {i}"),
                    metadata: meta,
                    embedding: None,
                })
                .unwrap();
        }
        assert_eq!(store.count_sessions().unwrap(), 2);
    }

    #[test]
    fn get_all_documents_returns_all() {
        let store = MetadataStore::open_in_memory().unwrap();
        for i in 0..5 {
            store
                .upsert_memory(&Memory {
                    id: format!("d-{i}"),
                    content: format!("doc {i}"),
                    metadata: test_metadata(),
                    embedding: None,
                })
                .unwrap();
        }
        let docs = store.get_all_documents().unwrap();
        assert_eq!(docs.len(), 5);
    }

    #[test]
    fn append_feedback_and_count() {
        let store = MetadataStore::open_in_memory().unwrap();
        let id = store
            .append_feedback(
                FeedbackEventType::Accepted,
                Some("mem-1"),
                Some("q"),
                None,
                None,
                FeedbackSource::BrainApi,
                serde_json::json!({}),
                None,
            )
            .unwrap();
        assert_eq!(store.count_feedback_events().unwrap(), 1);
        assert!(store.feedback_last_event_ts().unwrap().is_some());
        let rows = store
            .list_feedback_since(Utc.timestamp_opt(0, 0).single().unwrap())
            .unwrap();
        assert_eq!(rows.len(), 1);
        assert_eq!(rows[0].id, id);
    }

    #[test]
    fn upsert_stores_and_retrieves_embedding() {
        let store = MetadataStore::open_in_memory().unwrap();
        let emb: Vec<f32> = vec![0.1, 0.2, 0.3];
        let memory = Memory {
            id: "emb-1".into(),
            content: "test".into(),
            metadata: test_metadata(),
            embedding: Some(emb.clone()),
        };
        store.upsert_memory(&memory).unwrap();
        let fetched = store.get_memory("emb-1").unwrap().unwrap();
        assert_eq!(fetched.embedding, Some(emb));
    }

    #[test]
    fn upsert_without_embedding_stores_null() {
        let store = MetadataStore::open_in_memory().unwrap();
        let memory = Memory {
            id: "no-emb".into(),
            content: "test".into(),
            metadata: test_metadata(),
            embedding: None,
        };
        store.upsert_memory(&memory).unwrap();
        let fetched = store.get_memory("no-emb").unwrap().unwrap();
        assert!(fetched.embedding.is_none());
    }

    #[test]
    fn get_embeddings_for_index_returns_only_non_null() {
        let store = MetadataStore::open_in_memory().unwrap();
        let with_emb = Memory {
            id: "a".into(),
            content: "x".into(),
            metadata: test_metadata(),
            embedding: Some(vec![1.0, 0.0]),
        };
        let without_emb = Memory {
            id: "b".into(),
            content: "y".into(),
            metadata: test_metadata(),
            embedding: None,
        };
        store.upsert_memory(&with_emb).unwrap();
        store.upsert_memory(&without_emb).unwrap();
        let pairs = store.get_embeddings_for_index().unwrap();
        assert_eq!(pairs.len(), 1);
        assert_eq!(pairs[0].0, "a");
    }

    #[test]
    fn get_unembedded_returns_only_null_rows() {
        let store = MetadataStore::open_in_memory().unwrap();
        let m1 = Memory {
            id: "a".into(),
            content: "c1".into(),
            metadata: test_metadata(),
            embedding: Some(vec![1.0]),
        };
        let m2 = Memory {
            id: "b".into(),
            content: "c2".into(),
            metadata: test_metadata(),
            embedding: None,
        };
        store.upsert_memory(&m1).unwrap();
        store.upsert_memory(&m2).unwrap();
        let unembedded = store.get_unembedded_ids_and_content().unwrap();
        assert_eq!(unembedded.len(), 1);
        assert_eq!(unembedded[0].0, "b");
    }

    #[test]
    fn update_embedding_fills_null_row() {
        let store = MetadataStore::open_in_memory().unwrap();
        let m = Memory {
            id: "x".into(),
            content: "c".into(),
            metadata: test_metadata(),
            embedding: None,
        };
        store.upsert_memory(&m).unwrap();
        store.update_embedding("x", &[0.5, 0.5]).unwrap();
        let fetched = store.get_memory("x").unwrap().unwrap();
        assert_eq!(fetched.embedding, Some(vec![0.5, 0.5]));
    }

    // ---- Fact-layer tests ----

    fn fact_metadata(parent_id: &str) -> MemoryMetadata {
        MemoryMetadata {
            memory_type: MemoryType::Fact,
            project: "test".into(),
            tags: "brain/extracted,test".into(),
            timestamp: Utc::now(),
            source: MemorySource::ClaudeCodeSession,
            session_id: String::new(),
            importance: 0.5,
            file_path: None,
            thread_id: None,
            title: Some("Test fact".into()),
            parent_id: Some(parent_id.to_string()),
            event_time: None,
            salience: 0.8,
            superseded_by: None,
            derived_from: Some("openrouter/claude-sonnet-4-5/v1".into()),
        }
    }

    #[test]
    fn upsert_and_get_fact_columns_roundtrip() {
        let store = MetadataStore::open_in_memory().unwrap();
        let memory = Memory {
            id: "fact-1".into(),
            content: "Use async/await for all IO operations".into(),
            metadata: fact_metadata("episode-1"),
            embedding: None,
        };
        store.upsert_memory(&memory).unwrap();
        let fetched = store.get_memory("fact-1").unwrap().unwrap();
        assert_eq!(fetched.metadata.memory_type, MemoryType::Fact);
        assert_eq!(fetched.metadata.parent_id.as_deref(), Some("episode-1"));
        assert!((fetched.metadata.salience - 0.8).abs() < 1e-6);
        assert_eq!(fetched.metadata.superseded_by, None);
        assert_eq!(
            fetched.metadata.derived_from.as_deref(),
            Some("openrouter/claude-sonnet-4-5/v1")
        );
    }

    #[test]
    fn get_facts_by_parent_returns_only_active_facts() {
        let store = MetadataStore::open_in_memory().unwrap();
        for (id, active) in [("f1", true), ("f2", false), ("f3", true)] {
            let mut meta = fact_metadata("ep-1");
            if !active {
                meta.superseded_by = Some("f3".into());
            }
            store.upsert_memory(&Memory {
                id: id.into(),
                content: format!("fact {id}"),
                metadata: meta,
                embedding: None,
            }).unwrap();
        }
        let facts = store.get_facts_by_parent("ep-1").unwrap();
        assert_eq!(facts.len(), 2);
        assert!(facts.iter().all(|f| f.metadata.superseded_by.is_none()));
        // Different parent returns empty
        let none = store.get_facts_by_parent("ep-99").unwrap();
        assert!(none.is_empty());
    }

    #[test]
    fn mark_superseded_sets_field() {
        let store = MetadataStore::open_in_memory().unwrap();
        store.upsert_memory(&Memory {
            id: "old-fact".into(),
            content: "old content".into(),
            metadata: fact_metadata("ep-1"),
            embedding: None,
        }).unwrap();
        store.mark_superseded("old-fact", "new-fact").unwrap();
        let fetched = store.get_memory("old-fact").unwrap().unwrap();
        assert_eq!(fetched.metadata.superseded_by.as_deref(), Some("new-fact"));
    }

    #[test]
    fn fts_search_facts_excludes_episodes_and_superseded() {
        let store = MetadataStore::open_in_memory().unwrap();

        // One active fact
        store.upsert_memory(&Memory {
            id: "active-fact".into(),
            content: "async await IO pattern".into(),
            metadata: fact_metadata("ep-1"),
            embedding: None,
        }).unwrap();

        // One superseded fact (same content — should NOT appear)
        let mut sup_meta = fact_metadata("ep-1");
        sup_meta.superseded_by = Some("active-fact".into());
        store.upsert_memory(&Memory {
            id: "sup-fact".into(),
            content: "async await IO pattern old".into(),
            metadata: sup_meta,
            embedding: None,
        }).unwrap();

        // One episode (should NOT appear in facts search)
        let mut ep_meta = test_metadata();
        ep_meta.memory_type = MemoryType::Episode;
        store.upsert_memory(&Memory {
            id: "ep-1".into(),
            content: "async await IO pattern episode".into(),
            metadata: ep_meta,
            embedding: None,
        }).unwrap();

        let hits = store.fts_search_facts("async await", 10).unwrap();
        assert_eq!(hits.len(), 1, "expected only active-fact, got: {hits:?}");
        assert_eq!(hits[0], "active-fact");
    }

    #[test]
    fn log_curation_event_and_rollback_batch() {
        let store = MetadataStore::open_in_memory().unwrap();

        // Insert a fact under a batch
        store.upsert_memory(&Memory {
            id: "bf-fact".into(),
            content: "backfill fact content".into(),
            metadata: fact_metadata("ep-1"),
            embedding: None,
        }).unwrap();

        // Insert an episode that gets superseded by this fact
        let mut ep_meta = test_metadata();
        ep_meta.memory_type = MemoryType::Episode;
        ep_meta.superseded_by = Some("bf-fact".into());
        store.upsert_memory(&Memory {
            id: "ep-1".into(),
            content: "episode content".into(),
            metadata: ep_meta,
            embedding: None,
        }).unwrap();

        store.start_backfill_batch("batch-1", "test", Some(0.5)).unwrap();
        store.log_curation_event("bf-fact", "ADD", Some(0.1), "auto", None, Some("batch-1")).unwrap();

        // Rollback: fact deleted, episode superseded_by cleared
        let removed = store.rollback_batch("batch-1").unwrap();
        assert_eq!(removed, 1);
        assert!(store.get_memory("bf-fact").unwrap().is_none());
        let ep = store.get_memory("ep-1").unwrap().unwrap();
        assert_eq!(ep.metadata.superseded_by, None);
    }

    #[test]
    fn curation_events_table_exists() {
        let store = MetadataStore::open_in_memory().unwrap();
        store.log_curation_event("f1", "IGNORE", Some(0.95), "dup", None, None).unwrap();
    }

    #[test]
    fn backfill_batch_finish_records_result() {
        let store = MetadataStore::open_in_memory().unwrap();
        store.start_backfill_batch("b1", "proj", Some(0.6)).unwrap();
        store.finish_backfill_batch("b1", Some(0.7), 10, 2, false).unwrap();
    }

    #[test]
    fn append_feedback_idempotent() {
        let store = MetadataStore::open_in_memory().unwrap();
        let id1 = store
            .append_feedback(
                FeedbackEventType::Rejected,
                None,
                None,
                None,
                None,
                FeedbackSource::Mcp,
                serde_json::json!({"note": "x"}),
                Some("key-a"),
            )
            .unwrap();
        let id2 = store
            .append_feedback(
                FeedbackEventType::Rejected,
                None,
                None,
                None,
                None,
                FeedbackSource::Mcp,
                serde_json::json!({"note": "y"}),
                Some("key-a"),
            )
            .unwrap();
        assert_eq!(id1, id2);
        assert_eq!(store.count_feedback_events().unwrap(), 1);
    }

    #[test]
    fn create_tables_creates_entities_and_edges() {
        let store = MetadataStore::open_in_memory().unwrap();
        assert!(store.table_exists("entities").unwrap());
        assert!(store.table_exists("edges").unwrap());
    }

    #[test]
    fn upsert_entity_is_idempotent_by_normalized_name() {
        let store = MetadataStore::open_in_memory().unwrap();
        let a = store.upsert_entity("  Open Router ").unwrap();
        let b = store.upsert_entity("open router").unwrap();
        assert_eq!(a, b);
    }

    #[test]
    fn link_memory_entities_and_neighbors() {
        let store = MetadataStore::open_in_memory().unwrap();
        for id in ["f1", "f2", "f3"] {
            let mem = Memory {
                id: id.into(),
                content: format!("fact {id}"),
                metadata: fact_metadata("ep-1"),
                embedding: None,
            };
            store.upsert_memory(&mem).unwrap();
        }
        store
            .link_memory_entities("f1", &["Cognee".into(), "SQLite".into()])
            .unwrap();
        store.link_memory_entities("f2", &["Cognee".into()]).unwrap();
        store.link_memory_entities("f3", &["Neo4j".into()]).unwrap();

        let ents = store.entities_for_memory("f1").unwrap();
        assert_eq!(ents.len(), 2);

        let neighbors = store.neighbor_memory_ids(&["f1".into()], true).unwrap();
        assert!(neighbors.contains(&"f2".into()));
        assert!(!neighbors.contains(&"f3".into()));
        assert!(!neighbors.contains(&"f1".into()));
    }

    #[test]
    fn neighbor_memory_ids_skips_superseded() {
        let store = MetadataStore::open_in_memory().unwrap();
        for (id, superseded) in [("f1", None), ("f2", Some("f9"))] {
            let mut meta = fact_metadata("ep-1");
            meta.superseded_by = superseded.map(|s| s.into());
            store
                .upsert_memory(&Memory {
                    id: id.into(),
                    content: format!("fact {id}"),
                    metadata: meta,
                    embedding: None,
                })
                .unwrap();
        }
        store.link_memory_entities("f1", &["X".into()]).unwrap();
        store.link_memory_entities("f2", &["X".into()]).unwrap();
        let neighbors = store.neighbor_memory_ids(&["f1".into()], true).unwrap();
        assert!(!neighbors.contains(&"f2".into()));
    }
}

#[cfg(test)]
mod queue_tests {
    use super::*;

    #[test]
    fn enqueue_and_dequeue_roundtrip() {
        let store = MetadataStore::open_in_memory().unwrap();
        let id = store
            .enqueue_job("compress_session", r#"{"session_id":"s1"}"#)
            .unwrap();
        let jobs = store.pending_jobs(10).unwrap();
        assert_eq!(jobs.len(), 1);
        assert_eq!(jobs[0].id, id);
        assert_eq!(jobs[0].kind, "compress_session");
    }

    #[test]
    fn mark_job_done_removes_from_pending() {
        let store = MetadataStore::open_in_memory().unwrap();
        let id = store.enqueue_job("test", "{}").unwrap();
        store.mark_job_done(&id).unwrap();
        assert!(store.pending_jobs(10).unwrap().is_empty());
    }

    #[test]
    fn mark_job_failed_increments_attempts() {
        let store = MetadataStore::open_in_memory().unwrap();
        let id = store.enqueue_job("test", "{}").unwrap();
        store.mark_job_failed(&id, "boom").unwrap();
        let jobs = store.pending_jobs(10).unwrap();
        assert_eq!(jobs[0].attempts, 1);
        assert_eq!(jobs[0].last_error.as_deref(), Some("boom"));
    }

    #[test]
    fn mark_job_failed_five_times_moves_to_failed_status() {
        let store = MetadataStore::open_in_memory().unwrap();
        let id = store.enqueue_job("test", "{}").unwrap();
        for _ in 0..5 {
            store.mark_job_failed(&id, "boom").unwrap();
        }
        assert!(store.pending_jobs(10).unwrap().is_empty());
        assert_eq!(store.job_status(&id).unwrap(), "failed");
    }

    #[test]
    fn mark_job_failed_four_times_stays_pending() {
        let store = MetadataStore::open_in_memory().unwrap();
        let id = store.enqueue_job("test", "{}").unwrap();
        for _ in 0..4 {
            store.mark_job_failed(&id, "boom").unwrap();
        }
        let jobs = store.pending_jobs(10).unwrap();
        assert_eq!(jobs.len(), 1);
        assert_eq!(jobs[0].attempts, 4);
        assert_eq!(store.job_status(&id).unwrap(), "pending");
    }
}
