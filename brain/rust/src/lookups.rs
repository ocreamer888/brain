//! Direct lookups the semantic tools cannot answer: calendar window, project
//! tag, file path, and entity name. Samples are capped. Ranking is untouched.

use chrono::{Datelike, NaiveDate};
use rusqlite::{params, Connection};

use crate::store::normalize_entity_name;
use crate::BrainError;

const BRIEF_OK_MIN: usize = 3;
const FILE_PATH_CAP: usize = 8;
const ENTITY_HUB_DEGREE: usize = 40;
const SNIPPET: &str = "substr(replace(replace(content, char(10), ' '), char(13), ' '), 1, 180)";
const ACTIVE: &str = "CASE WHEN superseded_by IS NULL OR superseded_by = '' THEN 1 ELSE 0 END";
const FILE_WHERE: &str = "file_path IS NOT NULL AND (file_path = ?1 OR file_path LIKE ?2 ESCAPE '\\')";
const FOLLOW_CAP: usize = 8;

/// Which clock a calendar query uses. `Stored` is ingest time. `Event` is
/// when the fact happened, and rows with no `event_time` stay out of that window.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TimeAxis {
    Stored,
    Event,
}

impl TimeAxis {
    pub fn parse(raw: &str) -> Result<Self, String> {
        match raw.trim().to_ascii_lowercase().as_str() {
            "" | "stored" | "timestamp" => Ok(Self::Stored),
            "event" | "event_time" => Ok(Self::Event),
            other => Err(format!("when must be stored or event, got {other}")),
        }
    }

    fn as_str(self) -> &'static str {
        match self {
            Self::Stored => "stored",
            Self::Event => "event",
        }
    }

    fn column(self) -> &'static str {
        match self {
            Self::Stored => "timestamp",
            Self::Event => "event_time",
        }
    }
}

fn calendar_where(axis: TimeAxis) -> String {
    let col = axis.column();
    format!(
        "{col} >= ?1 AND {col} < ?2 \
         AND (?3 = '' OR TRIM(type, '\"') = ?3) \
         AND (?4 = '' OR project = ?4)"
    )
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CalendarWindow {
    pub since: String,
    pub until: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CalendarCount {
    pub key: String,
    pub count: usize,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CalendarMemory {
    pub id: String,
    pub timestamp: String,
    pub memory_type: String,
    pub project: String,
    pub snippet: String,
    pub active: bool,
    pub event_time: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CalendarReport {
    pub since: String,
    pub until: String,
    pub when: String,
    pub stored: usize,
    pub active: usize,
    /// Rows saved in this window that have no event_time. They appear only for `when=stored`.
    pub saved_without_event_time: usize,
    pub by_type: Vec<CalendarCount>,
    pub by_day: Vec<CalendarCount>,
    pub memories: Vec<CalendarMemory>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ProjectCandidate {
    pub project: String,
    pub stored: usize,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ProjectBrief {
    pub query: String,
    pub matched_project: Option<String>,
    pub candidates: Vec<ProjectCandidate>,
    pub status: String,
    pub stored: usize,
    pub active: usize,
    pub by_type: Vec<CalendarCount>,
    pub pinned: Option<PinnedBrief>,
    pub briefs: Vec<CalendarMemory>,
}

impl ProjectBrief {
    fn empty(query: &str, status: &str) -> Self {
        Self {
            query: query.to_string(),
            matched_project: None,
            candidates: Vec::new(),
            status: status.into(),
            stored: 0,
            active: 0,
            by_type: Vec::new(),
            pinned: None,
            briefs: Vec::new(),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct FileReport {
    pub query: String,
    pub status: String,
    pub path_count: usize,
    pub paths: Vec<String>,
    pub stored: usize,
    pub memories: Vec<CalendarMemory>,
}

impl FileReport {
    fn empty(query: &str, status: &str) -> Self {
        Self {
            query: query.to_string(),
            status: status.into(),
            path_count: 0,
            paths: Vec::new(),
            stored: 0,
            memories: Vec::new(),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct EntityReport {
    pub query: String,
    pub name: String,
    pub status: String,
    pub degree: usize,
    pub capped: bool,
    pub memories: Vec<CalendarMemory>,
}

impl EntityReport {
    fn missing(query: &str) -> Self {
        Self {
            query: query.to_string(),
            name: String::new(),
            status: "missing".into(),
            degree: 0,
            capped: false,
            memories: Vec::new(),
        }
    }
}

pub fn brief_status(project_context_rows: usize) -> &'static str {
    if project_context_rows == 0 {
        "no_brief"
    } else if project_context_rows < BRIEF_OK_MIN {
        "thin"
    } else {
        "ok"
    }
}

pub fn entity_status(degree: usize) -> &'static str {
    if degree >= ENTITY_HUB_DEGREE {
        "hub"
    } else {
        "ok"
    }
}

/// `since` is `YYYY-MM` (that month) or `YYYY-MM-DD` (that day).
/// `until`, when set, is the exclusive bound in the same two shapes.
pub fn resolve_calendar_window(since: &str, until: Option<&str>) -> Result<CalendarWindow, String> {
    let since = since.trim();
    if since.is_empty() {
        return Err("since is required (YYYY-MM or YYYY-MM-DD)".into());
    }
    let since_date = parse_calendar_start(since)?;
    let until_date = match until.map(str::trim).filter(|s| !s.is_empty()) {
        Some(raw) => parse_calendar_start(raw)?,
        None if since.len() == 7 => next_month(since_date)?,
        None => since_date
            .checked_add_days(chrono::Days::new(1))
            .ok_or_else(|| "date overflow".to_string())?,
    };
    if until_date <= since_date {
        return Err("until must be after since".into());
    }
    Ok(CalendarWindow {
        since: since_date.format("%Y-%m-%d").to_string(),
        until: until_date.format("%Y-%m-%d").to_string(),
    })
}

pub fn memories_in_calendar(
    conn: &Connection,
    window: &CalendarWindow,
    axis: TimeAxis,
    memory_type: &str,
    project: &str,
    limit: usize,
) -> Result<CalendarReport, BrainError> {
    let where_sql = calendar_where(axis);
    let col = axis.column();
    let (stored, active) = calendar_counts(conn, &where_sql, &window.since, &window.until, memory_type, project)?;
    Ok(CalendarReport {
        since: window.since.clone(),
        until: window.until.clone(),
        when: axis.as_str().into(),
        stored,
        active,
        saved_without_event_time: saved_without_event_time(
            conn,
            &window.since,
            &window.until,
            memory_type,
            project,
        )?,
        by_type: calendar_buckets(
            conn,
            "SELECT TRIM(type, '\"') AS k, COUNT(*) AS n FROM memories WHERE ",
            " GROUP BY k ORDER BY n DESC, k ASC",
            &where_sql,
            &window.since,
            &window.until,
            memory_type,
            project,
        )?,
        by_day: calendar_buckets(
            conn,
            &format!("SELECT substr({col}, 1, 10) AS k, COUNT(*) AS n FROM memories WHERE "),
            " GROUP BY k ORDER BY k ASC",
            &where_sql,
            &window.since,
            &window.until,
            memory_type,
            project,
        )?,
        memories: calendar_sample(
            conn,
            &where_sql,
            col,
            &window.since,
            &window.until,
            memory_type,
            project,
            limit,
        )?,
    })
}

pub fn project_brief(conn: &Connection, project: &str, limit: usize) -> Result<ProjectBrief, BrainError> {
    let matched = project_name_matches(conn, project)?;
    if matched.is_empty() {
        return Ok(ProjectBrief::empty(project, "missing"));
    }
    if matched.len() > 1 {
        let mut brief = ProjectBrief::empty(project, "ambiguous");
        brief.candidates = matched;
        return Ok(brief);
    }
    let tag = matched[0].project.clone();
    let (stored, active) = project_counts(conn, &tag)?;
    let by_type = project_type_counts(conn, &tag)?;
    let contexts = by_type
        .iter()
        .find(|c| c.key == "project_context")
        .map(|c| c.count)
        .unwrap_or(0);
    let pinned = load_pin(conn, &tag)?;
    let exclude = pinned
        .as_ref()
        .map(|p| p.memory_id.clone())
        .unwrap_or_default();
    Ok(ProjectBrief {
        query: project.to_string(),
        matched_project: Some(tag.clone()),
        candidates: matched,
        status: brief_status(contexts).into(),
        stored,
        active,
        by_type,
        pinned,
        briefs: project_context_sample(conn, &tag, &exclude, limit)?,
    })
}

pub fn memories_for_file(conn: &Connection, path: &str, limit: usize) -> Result<FileReport, BrainError> {
    let like = file_like_pattern(path);
    let path_count = file_path_count(conn, path, &like)?;
    if path_count == 0 {
        return Ok(FileReport::empty(path, "missing"));
    }
    let stored = file_memory_count(conn, path, &like)?;
    let paths = file_paths(conn, path, &like)?;
    if path_count > FILE_PATH_CAP {
        return Ok(FileReport {
            query: path.to_string(),
            status: "ambiguous".into(),
            path_count,
            paths,
            stored,
            memories: Vec::new(),
        });
    }
    Ok(FileReport {
        query: path.to_string(),
        status: "ok".into(),
        path_count,
        paths,
        stored,
        memories: file_memory_sample(conn, path, &like, limit)?,
    })
}

pub fn memories_for_entity(
    conn: &Connection,
    name: &str,
    limit: usize,
) -> Result<EntityReport, BrainError> {
    let Some(norm) = normalize_entity_name(name) else {
        return Ok(EntityReport::missing(name));
    };
    let found = conn.query_row(
        "SELECT e.name, COUNT(DISTINCT x.src_memory_id) \
         FROM entities e \
         LEFT JOIN edges x ON x.dst_entity_id = e.id \
         WHERE e.name_normalized = ?1 \
         GROUP BY e.id",
        [&norm],
        |row| Ok((row.get::<_, String>(0)?, row.get::<_, i64>(1)?)),
    );
    let (stored_name, degree) = match found {
        Ok(pair) => pair,
        Err(rusqlite::Error::QueryReturnedNoRows) => return Ok(EntityReport::missing(name)),
        Err(e) => return Err(BrainError::Database(e.to_string())),
    };
    let degree = degree as usize;
    let memories = entity_memory_sample(conn, &norm, limit)?;
    Ok(EntityReport {
        query: name.to_string(),
        name: stored_name,
        status: entity_status(degree).into(),
        degree,
        capped: degree > memories.len(),
        memories,
    })
}

/// A `similar_to` neighbor for read-only "related memories" browsing
/// (cognitive-architecture-spec.md §7.3 item 3, G7). No effect on search
/// ranking -- this is a lookup, same non-goal as every other function in
/// this module.
#[derive(Debug, Clone, PartialEq)]
pub struct RelatedMemory {
    pub memory: CalendarMemory,
    pub weight: f64,
}

/// `memory_links` rows are directed (`src_memory_id` -> `dst_memory_id`,
/// written from the `src` side's own nearest-neighbor query, see
/// `similar::find_similar`), but a k-NN relation is not guaranteed
/// symmetric -- A's nearest neighbor is not always B when B's nearest
/// neighbor is A. Reads both directions rather than assuming one.
pub fn related_memories(
    conn: &Connection,
    memory_id: &str,
    limit: usize,
) -> Result<Vec<RelatedMemory>, BrainError> {
    let sql = format!(
        "SELECT m.id, m.timestamp, COALESCE(m.event_time, ''), TRIM(m.type, '\"'), m.project, \
            {SNIPPET}, {ACTIVE}, ml.weight \
         FROM memory_links ml \
         JOIN memories m ON m.id = (CASE WHEN ml.src_memory_id = ?1 THEN ml.dst_memory_id ELSE ml.src_memory_id END) \
         WHERE ml.relation_type = 'similar_to' AND (ml.src_memory_id = ?1 OR ml.dst_memory_id = ?1) \
         ORDER BY ml.weight DESC LIMIT ?2"
    );
    let mut stmt = conn.prepare(&sql).map_err(db)?;
    let rows = stmt
        .query_map(params![memory_id, limit as i64], |row| {
            Ok(RelatedMemory {
                memory: CalendarMemory {
                    id: row.get(0)?,
                    timestamp: row.get(1)?,
                    event_time: {
                        let raw: String = row.get(2)?;
                        if raw.is_empty() { None } else { Some(raw) }
                    },
                    memory_type: row.get(3)?,
                    project: row.get(4)?,
                    snippet: row.get(5)?,
                    active: row.get::<_, i64>(6)? == 1,
                },
                weight: row.get(7)?,
            })
        })
        .map_err(db)?;
    rows.collect::<Result<Vec<_>, _>>().map_err(db)
}

fn parse_calendar_start(raw: &str) -> Result<NaiveDate, String> {
    let text = if raw.len() == 7 {
        format!("{raw}-01")
    } else if raw.len() == 10 {
        raw.to_string()
    } else {
        return Err(format!("use YYYY-MM or YYYY-MM-DD, got {raw}"));
    };
    NaiveDate::parse_from_str(&text, "%Y-%m-%d").map_err(|_| format!("invalid date: {raw}"))
}

fn next_month(day: NaiveDate) -> Result<NaiveDate, String> {
    let (year, month) = if day.month() == 12 {
        (day.year() + 1, 1)
    } else {
        (day.year(), day.month() + 1)
    };
    NaiveDate::from_ymd_opt(year, month, 1).ok_or_else(|| "date overflow".to_string())
}

fn db(err: rusqlite::Error) -> BrainError {
    BrainError::Database(err.to_string())
}

fn calendar_counts(
    conn: &Connection,
    where_sql: &str,
    since: &str,
    until: &str,
    memory_type: &str,
    project: &str,
) -> Result<(usize, usize), BrainError> {
    let sql = format!(
        "SELECT COUNT(*), COALESCE(SUM(CASE WHEN superseded_by IS NULL OR superseded_by = '' THEN 1 ELSE 0 END), 0) \
         FROM memories WHERE {where_sql}"
    );
    conn.query_row(&sql, params![since, until, memory_type, project], |row| {
        Ok((row.get::<_, i64>(0)? as usize, row.get::<_, i64>(1)? as usize))
    })
    .map_err(db)
}

fn saved_without_event_time(
    conn: &Connection,
    since: &str,
    until: &str,
    memory_type: &str,
    project: &str,
) -> Result<usize, BrainError> {
    conn.query_row(
        "SELECT COUNT(*) FROM memories \
         WHERE timestamp >= ?1 AND timestamp < ?2 \
           AND (event_time IS NULL OR event_time = '') \
           AND (?3 = '' OR TRIM(type, '\"') = ?3) \
           AND (?4 = '' OR project = ?4)",
        params![since, until, memory_type, project],
        |row| row.get::<_, i64>(0),
    )
    .map(|n| n as usize)
    .map_err(db)
}

fn calendar_buckets(
    conn: &Connection,
    select_sql: &str,
    tail_sql: &str,
    where_sql: &str,
    since: &str,
    until: &str,
    memory_type: &str,
    project: &str,
) -> Result<Vec<CalendarCount>, BrainError> {
    let sql = format!("{select_sql}{where_sql}{tail_sql}");
    let mut stmt = conn.prepare(&sql).map_err(db)?;
    let rows = stmt
        .query_map(params![since, until, memory_type, project], |row| {
            Ok(CalendarCount {
                key: row.get(0)?,
                count: row.get::<_, i64>(1)? as usize,
            })
        })
        .map_err(db)?;
    rows.collect::<Result<Vec<_>, _>>().map_err(db)
}

fn calendar_sample(
    conn: &Connection,
    where_sql: &str,
    order_col: &str,
    since: &str,
    until: &str,
    memory_type: &str,
    project: &str,
    limit: usize,
) -> Result<Vec<CalendarMemory>, BrainError> {
    let sql = format!(
        "SELECT id, timestamp, COALESCE(event_time, ''), TRIM(type, '\"'), project, {SNIPPET}, {ACTIVE} \
         FROM memories WHERE {where_sql} \
         ORDER BY {order_col} DESC, id ASC LIMIT ?5"
    );
    sample_rows(conn, &sql, params![since, until, memory_type, project, limit as i64])
}

fn project_name_matches(conn: &Connection, project: &str) -> Result<Vec<ProjectCandidate>, BrainError> {
    let mut stmt = conn
        .prepare(
            "SELECT project, COUNT(*) FROM memories \
             WHERE project = ?1 COLLATE NOCASE \
             GROUP BY project ORDER BY COUNT(*) DESC, project ASC",
        )
        .map_err(db)?;
    let rows = stmt
        .query_map(params![project], |row| {
            Ok(ProjectCandidate {
                project: row.get(0)?,
                stored: row.get::<_, i64>(1)? as usize,
            })
        })
        .map_err(db)?;
    rows.collect::<Result<Vec<_>, _>>().map_err(db)
}

fn project_counts(conn: &Connection, project: &str) -> Result<(usize, usize), BrainError> {
    conn.query_row(
        "SELECT COUNT(*), COALESCE(SUM(CASE WHEN superseded_by IS NULL OR superseded_by = '' THEN 1 ELSE 0 END), 0) \
         FROM memories WHERE project = ?1",
        params![project],
        |row| Ok((row.get::<_, i64>(0)? as usize, row.get::<_, i64>(1)? as usize)),
    )
    .map_err(db)
}

fn project_type_counts(conn: &Connection, project: &str) -> Result<Vec<CalendarCount>, BrainError> {
    let mut stmt = conn
        .prepare(
            "SELECT TRIM(type, '\"') AS k, COUNT(*) AS n FROM memories \
             WHERE project = ?1 GROUP BY k ORDER BY n DESC, k ASC",
        )
        .map_err(db)?;
    let rows = stmt
        .query_map(params![project], |row| {
            Ok(CalendarCount {
                key: row.get(0)?,
                count: row.get::<_, i64>(1)? as usize,
            })
        })
        .map_err(db)?;
    rows.collect::<Result<Vec<_>, _>>().map_err(db)
}

fn project_context_sample(
    conn: &Connection,
    project: &str,
    exclude_id: &str,
    limit: usize,
) -> Result<Vec<CalendarMemory>, BrainError> {
    let sql = format!(
        "SELECT id, timestamp, COALESCE(event_time, ''), TRIM(type, '\"'), project, {SNIPPET}, {ACTIVE} \
         FROM memories WHERE project = ?1 AND TRIM(type, '\"') = 'project_context' \
           AND (?2 = '' OR id != ?2) \
         ORDER BY timestamp DESC, id ASC LIMIT ?3"
    );
    sample_rows(conn, &sql, params![project, exclude_id, limit as i64])
}

fn file_like_pattern(path: &str) -> String {
    let mut escaped = String::new();
    for c in path.chars() {
        if c == '\\' || c == '%' || c == '_' {
            escaped.push('\\');
        }
        escaped.push(c);
    }
    format!("%/{escaped}")
}

fn file_path_count(conn: &Connection, path: &str, like: &str) -> Result<usize, BrainError> {
    conn.query_row(
        &format!("SELECT COUNT(DISTINCT file_path) FROM memories WHERE {FILE_WHERE}"),
        params![path, like],
        |row| row.get::<_, i64>(0),
    )
    .map(|n| n as usize)
    .map_err(db)
}

fn file_memory_count(conn: &Connection, path: &str, like: &str) -> Result<usize, BrainError> {
    conn.query_row(
        &format!("SELECT COUNT(*) FROM memories WHERE {FILE_WHERE}"),
        params![path, like],
        |row| row.get::<_, i64>(0),
    )
    .map(|n| n as usize)
    .map_err(db)
}

fn file_paths(conn: &Connection, path: &str, like: &str) -> Result<Vec<String>, BrainError> {
    let mut stmt = conn
        .prepare(&format!(
            "SELECT DISTINCT file_path FROM memories WHERE {FILE_WHERE} \
             ORDER BY file_path ASC LIMIT {FILE_PATH_CAP}"
        ))
        .map_err(db)?;
    let rows = stmt
        .query_map(params![path, like], |row| row.get(0))
        .map_err(db)?;
    rows.collect::<Result<Vec<_>, _>>().map_err(db)
}

fn file_memory_sample(
    conn: &Connection,
    path: &str,
    like: &str,
    limit: usize,
) -> Result<Vec<CalendarMemory>, BrainError> {
    let sql = format!(
        "SELECT id, timestamp, COALESCE(event_time, ''), TRIM(type, '\"'), project, {SNIPPET}, {ACTIVE} \
         FROM memories WHERE {FILE_WHERE} \
         ORDER BY timestamp DESC, id ASC LIMIT ?3"
    );
    sample_rows(conn, &sql, params![path, like, limit as i64])
}

fn entity_memory_sample(
    conn: &Connection,
    norm: &str,
    limit: usize,
) -> Result<Vec<CalendarMemory>, BrainError> {
    let sql = format!(
        "SELECT m.id, m.timestamp, COALESCE(m.event_time, ''), TRIM(m.type, '\"'), m.project, \
            substr(replace(replace(m.content, char(10), ' '), char(13), ' '), 1, 180), \
            CASE WHEN m.superseded_by IS NULL OR m.superseded_by = '' THEN 1 ELSE 0 END \
         FROM edges x \
         JOIN memories m ON m.id = x.src_memory_id \
         JOIN entities e ON e.id = x.dst_entity_id \
         WHERE e.name_normalized = ?1 \
         ORDER BY m.timestamp DESC, m.id ASC LIMIT ?2"
    );
    sample_rows(conn, &sql, params![norm, limit as i64])
}

fn sample_rows(
    conn: &Connection,
    sql: &str,
    params: impl rusqlite::Params,
) -> Result<Vec<CalendarMemory>, BrainError> {
    let mut stmt = conn.prepare(sql).map_err(db)?;
    let rows = stmt
        .query_map(params, |row| {
            Ok(CalendarMemory {
                id: row.get(0)?,
                timestamp: row.get(1)?,
                event_time: {
                    let raw: String = row.get(2)?;
                    if raw.is_empty() { None } else { Some(raw) }
                },
                memory_type: row.get(3)?,
                project: row.get(4)?,
                snippet: row.get(5)?,
                active: row.get::<_, i64>(6)? == 1,
            })
        })
        .map_err(db)?;
    rows.collect::<Result<Vec<_>, _>>().map_err(db)
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PinnedBrief {
    pub memory_id: String,
    pub pinned_at: String,
    pub state: String,
    pub memory: Option<CalendarMemory>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PinOutcome {
    pub project: String,
    pub memory_id: String,
    pub pinned_at: String,
    pub previous_memory_id: Option<String>,
}

#[derive(Debug)]
pub enum LookupReject {
    Bad(String),
    Db(BrainError),
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct FollowReport {
    pub id: String,
    pub status: String,
    pub detail: String,
    pub chain: Vec<CalendarMemory>,
    pub predecessors: Vec<CalendarMemory>,
}

struct LoadedMemory {
    memory: CalendarMemory,
    superseded_by: Option<String>,
    memory_type: String,
    project: String,
}

pub fn pin_project_brief(
    conn: &Connection,
    project: &str,
    memory_id: &str,
) -> Result<PinOutcome, LookupReject> {
    let loaded = load_memory(conn, memory_id).map_err(LookupReject::Db)?;
    let Some(loaded) = loaded else {
        return Err(LookupReject::Bad(format!("memory {memory_id} not found")));
    };
    if loaded.memory_type != "project_context" {
        return Err(LookupReject::Bad(
            "only a project_context memory can be the pinned brief".into(),
        ));
    }
    let tag = resolve_pin_project(conn, project, &loaded.project)?;
    let previous: Option<String> = conn
        .query_row(
            "SELECT memory_id FROM project_pins WHERE project = ?1",
            [&tag],
            |row| row.get(0),
        )
        .ok();
    let pinned_at = chrono::Utc::now().to_rfc3339();
    conn.execute(
        "INSERT INTO project_pins (project, memory_id, pinned_at) VALUES (?1, ?2, ?3) \
         ON CONFLICT(project) DO UPDATE SET memory_id = excluded.memory_id, pinned_at = excluded.pinned_at",
        params![tag, memory_id, pinned_at],
    )
    .map_err(|e| LookupReject::Db(db(e)))?;
    let previous_memory_id = previous.filter(|id| id != memory_id);
    Ok(PinOutcome {
        project: tag,
        memory_id: memory_id.to_string(),
        pinned_at,
        previous_memory_id,
    })
}

pub fn unpin_project_brief(conn: &Connection, project: &str) -> Result<bool, LookupReject> {
    let matched = project_name_matches(conn, project).map_err(LookupReject::Db)?;
    let tag = match matched.len() {
        0 => return Ok(false),
        1 => matched[0].project.clone(),
        _ => {
            return Err(LookupReject::Bad(
                "project tag is ambiguous; pass the exact stored spelling".into(),
            ))
        }
    };
    let n = conn
        .execute("DELETE FROM project_pins WHERE project = ?1", [&tag])
        .map_err(|e| LookupReject::Db(db(e)))?;
    Ok(n > 0)
}

pub fn follow_memory(conn: &Connection, id: &str) -> Result<FollowReport, BrainError> {
    let Some(start) = load_memory(conn, id)? else {
        return Ok(FollowReport {
            id: id.to_string(),
            status: "missing".into(),
            detail: "No memory with that id.".into(),
            chain: Vec::new(),
            predecessors: Vec::new(),
        });
    };
    let predecessors = predecessors_of(conn, id)?;
    let mut chain = vec![start.memory];
    let mut seen = std::collections::HashSet::from([id.to_string()]);
    let mut link = start.superseded_by;
    let mut status = "current".to_string();
    let mut detail = "This memory has no successor.".to_string();
    while chain.len() < FOLLOW_CAP {
        let Some(raw) = link.clone().filter(|s| !s.is_empty()) else {
            break;
        };
        if let Some(kind) = sentinel_kind(&raw) {
            status = kind.into();
            detail = format!("Superseded by a {kind} label ({raw}), not a memory.");
            break;
        }
        if !seen.insert(raw.clone()) {
            status = "cycle".into();
            detail = format!("Successor chain loops at {raw}.");
            break;
        }
        let Some(next) = load_memory(conn, &raw)? else {
            status = "dangling".into();
            detail = format!("Successor {raw} does not exist.");
            break;
        };
        status = "replaced".into();
        detail = format!("Live row is {}.", next.memory.id);
        link = next.superseded_by.clone();
        chain.push(next.memory);
    }
    if chain.len() == FOLLOW_CAP && link.as_deref().unwrap_or("").is_empty() == false && status == "replaced" {
        detail = format!("{detail} Chain stopped at {FOLLOW_CAP} rows.");
    }
    Ok(FollowReport {
        id: id.to_string(),
        status,
        detail,
        chain,
        predecessors,
    })
}

fn sentinel_kind(raw: &str) -> Option<&'static str> {
    if raw.starts_with("quarantine:") {
        Some("quarantined")
    } else if raw.starts_with("hidden:") {
        Some("hidden")
    } else {
        None
    }
}

fn resolve_pin_project(
    conn: &Connection,
    requested: &str,
    memory_project: &str,
) -> Result<String, LookupReject> {
    let requested = requested.trim();
    if requested.is_empty() {
        return Ok(memory_project.to_string());
    }
    if requested == memory_project {
        return Ok(memory_project.to_string());
    }
    let matched = project_name_matches(conn, requested).map_err(LookupReject::Db)?;
    if matched.len() > 1 {
        return Err(LookupReject::Bad(
            "project tag is ambiguous; pass the exact stored spelling".into(),
        ));
    }
    if matched.len() == 1 && matched[0].project == memory_project {
        return Ok(memory_project.to_string());
    }
    Err(LookupReject::Bad(format!(
        "memory is tagged {memory_project}, not {requested}"
    )))
}

fn load_pin(conn: &Connection, project: &str) -> Result<Option<PinnedBrief>, BrainError> {
    let found = conn.query_row(
        "SELECT memory_id, pinned_at FROM project_pins WHERE project = ?1",
        [project],
        |row| Ok((row.get::<_, String>(0)?, row.get::<_, String>(1)?)),
    );
    let (memory_id, pinned_at) = match found {
        Ok(pair) => pair,
        Err(rusqlite::Error::QueryReturnedNoRows) => return Ok(None),
        Err(e) => return Err(db(e)),
    };
    let loaded = load_memory(conn, &memory_id)?;
    let state = match &loaded {
        None => "missing",
        Some(row) if !row.memory.active || row.memory_type != "project_context" || row.project != project => {
            "stale"
        }
        Some(_) => "current",
    };
    Ok(Some(PinnedBrief {
        memory_id,
        pinned_at,
        state: state.into(),
        memory: loaded.map(|row| row.memory),
    }))
}

fn load_memory(conn: &Connection, id: &str) -> Result<Option<LoadedMemory>, BrainError> {
    let found = conn.query_row(
        &format!(
            "SELECT id, timestamp, COALESCE(event_time, ''), TRIM(type, '\"'), project, {SNIPPET}, {ACTIVE}, \
                    COALESCE(superseded_by, '') \
             FROM memories WHERE id = ?1"
        ),
        [id],
        |row| {
            let event_raw: String = row.get(2)?;
            Ok(LoadedMemory {
                memory: CalendarMemory {
                    id: row.get(0)?,
                    timestamp: row.get(1)?,
                    event_time: if event_raw.is_empty() { None } else { Some(event_raw) },
                    memory_type: row.get(3)?,
                    project: row.get(4)?,
                    snippet: row.get(5)?,
                    active: row.get::<_, i64>(6)? == 1,
                },
                memory_type: row.get(3)?,
                project: row.get(4)?,
                superseded_by: {
                    let raw: String = row.get(7)?;
                    if raw.is_empty() { None } else { Some(raw) }
                },
            })
        },
    );
    match found {
        Ok(row) => Ok(Some(row)),
        Err(rusqlite::Error::QueryReturnedNoRows) => Ok(None),
        Err(e) => Err(db(e)),
    }
}

fn predecessors_of(conn: &Connection, id: &str) -> Result<Vec<CalendarMemory>, BrainError> {
    let sql = format!(
        "SELECT id, timestamp, COALESCE(event_time, ''), TRIM(type, '\"'), project, {SNIPPET}, {ACTIVE} \
         FROM memories WHERE superseded_by = ?1 \
         ORDER BY timestamp DESC, id ASC LIMIT {FOLLOW_CAP}"
    );
    sample_rows(conn, &sql, params![id])
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::{DateTime, Utc};

    use crate::store::MetadataStore;
    use crate::{Memory, MemoryMetadata, MemorySource, MemoryType};

    fn meta(ty: MemoryType, project: &str, ts: &str, file_path: Option<&str>) -> MemoryMetadata {
        MemoryMetadata {
            memory_type: ty,
            project: project.into(),
            tags: String::new(),
            timestamp: DateTime::parse_from_rfc3339(ts).unwrap().with_timezone(&Utc),
            source: MemorySource::ClaudeCodeSession,
            session_id: String::new(),
            importance: 0.5,
            file_path: file_path.map(str::to_string),
            thread_id: None,
            title: None,
            parent_id: None,
            event_time: None,
            salience: 0.5,
            salience_pinned: false,
            superseded_by: None,
            extracted_by: None,
        }
    }

    fn save(store: &MetadataStore, id: &str, content: &str, metadata: MemoryMetadata) {
        store
            .upsert_memory(&Memory {
                id: id.into(),
                content: content.into(),
                metadata,
                embedding: None,
            })
            .unwrap();
    }

    #[test]
    fn calendar_window_resolves_month_and_day() {
        let month = resolve_calendar_window("2026-05", None).unwrap();
        assert_eq!(month.since, "2026-05-01");
        assert_eq!(month.until, "2026-06-01");
        let day = resolve_calendar_window("2026-05-23", None).unwrap();
        assert_eq!(day.until, "2026-05-24");
        assert!(resolve_calendar_window("May", None).is_err());
        assert!(resolve_calendar_window("2026-05-02", Some("2026-05-02")).is_err());
        assert_eq!(brief_status(0), "no_brief");
        assert_eq!(brief_status(2), "thin");
        assert_eq!(brief_status(3), "ok");
        assert_eq!(entity_status(39), "ok");
        assert_eq!(entity_status(40), "hub");
    }

    #[test]
    fn calendar_query_keeps_june_out() {
        let store = MetadataStore::open_in_memory().unwrap();
        save(
            &store,
            "may-fact",
            "fact body",
            meta(MemoryType::Fact, "brain", "2026-05-02T12:00:00+00:00", None),
        );
        let mut old = meta(MemoryType::Solution, "brain", "2026-05-03T08:00:00+00:00", None);
        old.superseded_by = Some("quarantine:test".into());
        save(&store, "may-old", "old solution\nsecond line", old);
        save(
            &store,
            "june",
            "june",
            meta(MemoryType::Fact, "brain", "2026-06-01T00:00:00+00:00", None),
        );
        let window = resolve_calendar_window("2026-05", None).unwrap();
        let report = memories_in_calendar(store.conn(), &window, TimeAxis::Stored, "", "", 8).unwrap();
        assert_eq!(report.stored, 2);
        assert_eq!(report.active, 1);
        assert_eq!(report.memories[0].id, "may-old");
        assert!(!report.memories[0].snippet.contains('\n'));
        let facts = memories_in_calendar(store.conn(), &window, TimeAxis::Stored, "fact", "", 8).unwrap();
        assert_eq!(facts.stored, 1);
    }

    #[test]
    fn project_brief_folds_case_and_flags_thin() {
        let store = MetadataStore::open_in_memory().unwrap();
        save(
            &store,
            "ctx",
            "the brief",
            meta(MemoryType::ProjectContext, "Brain", "2026-08-01T00:00:00+00:00", None),
        );
        save(
            &store,
            "fact",
            "a fact",
            meta(MemoryType::Fact, "Brain", "2026-08-02T00:00:00+00:00", None),
        );
        let brief = project_brief(store.conn(), "brain", 5).unwrap();
        assert_eq!(brief.status, "thin");
        assert_eq!(brief.matched_project.as_deref(), Some("Brain"));
        assert_eq!(brief.stored, 2);
        assert_eq!(brief.briefs.len(), 1);
        assert_eq!(project_brief(store.conn(), "nope", 5).unwrap().status, "missing");

        save(
            &store,
            "other",
            "other",
            meta(MemoryType::Fact, "brain", "2026-08-03T00:00:00+00:00", None),
        );
        let split = project_brief(store.conn(), "brain", 5).unwrap();
        assert_eq!(split.status, "ambiguous");
        assert!(split.matched_project.is_none());
        assert_eq!(split.candidates.len(), 2);
    }

    #[test]
    fn file_lookup_matches_suffix_and_stops_when_ambiguous() {
        let store = MetadataStore::open_in_memory().unwrap();
        save(
            &store,
            "abs",
            "server",
            meta(
                MemoryType::Solution,
                "brain",
                "2026-08-02T00:00:00+00:00",
                Some("/repo/brain/mcp/server.py"),
            ),
        );
        let hit = memories_for_file(store.conn(), "brain/mcp/server.py", 8).unwrap();
        assert_eq!(hit.status, "ok");
        assert_eq!(hit.stored, 1);
        assert_eq!(hit.memories[0].id, "abs");

        for i in 0..9 {
            save(
                &store,
                &format!("n{i}"),
                "note",
                meta(
                    MemoryType::Solution,
                    "brain",
                    "2026-08-01T00:00:00+00:00",
                    Some(&format!("/tmp/dir{i}/note.md")),
                ),
            );
        }
        let many = memories_for_file(store.conn(), "note.md", 8).unwrap();
        assert_eq!(many.status, "ambiguous");
        assert_eq!(many.path_count, 9);
        assert!(many.memories.is_empty());
        assert_eq!(memories_for_file(store.conn(), "missing.rs", 8).unwrap().status, "missing");
    }

    #[test]
    fn entity_lookup_is_case_insensitive_and_capped() {
        let store = MetadataStore::open_in_memory().unwrap();
        save(
            &store,
            "m1",
            "mentions brain",
            meta(MemoryType::Fact, "brain", "2026-08-01T00:00:00+00:00", None),
        );
        save(
            &store,
            "m2",
            "mentions it again",
            meta(MemoryType::Fact, "brain", "2026-08-02T00:00:00+00:00", None),
        );
        store
            .link_memory_entities("m1", &["Brain".into()])
            .unwrap();
        store
            .link_memory_entities("m2", &["brain".into()])
            .unwrap();
        let report = memories_for_entity(store.conn(), "BRAIN", 1).unwrap();
        assert_eq!(report.status, "ok");
        assert_eq!(report.degree, 2);
        assert!(report.capped);
        assert_eq!(report.memories.len(), 1);
        assert_eq!(report.memories[0].id, "m2");
        assert_eq!(memories_for_entity(store.conn(), "nope", 5).unwrap().status, "missing");
    }

    #[test]
    fn event_axis_ignores_rows_without_event_time() {
        let store = MetadataStore::open_in_memory().unwrap();
        let mut happened = meta(MemoryType::Fact, "brain", "2026-06-01T00:00:00+00:00", None);
        happened.event_time = Some(
            DateTime::parse_from_rfc3339("2026-05-15T00:00:00+00:00")
                .unwrap()
                .with_timezone(&Utc),
        );
        save(&store, "happened", "happened in may", happened);
        save(
            &store,
            "saved-only",
            "saved in may",
            meta(MemoryType::Fact, "brain", "2026-05-02T00:00:00+00:00", None),
        );
        let window = resolve_calendar_window("2026-05", None).unwrap();
        let stored = memories_in_calendar(store.conn(), &window, TimeAxis::Stored, "", "", 8).unwrap();
        assert_eq!(stored.when, "stored");
        assert_eq!(stored.stored, 1);
        assert_eq!(stored.memories[0].id, "saved-only");
        assert_eq!(stored.saved_without_event_time, 1);
        let event = memories_in_calendar(store.conn(), &window, TimeAxis::Event, "", "", 8).unwrap();
        assert_eq!(event.when, "event");
        assert_eq!(event.stored, 1);
        assert_eq!(event.memories[0].id, "happened");
        assert_eq!(event.memories[0].event_time.as_deref(), Some("2026-05-15T00:00:00+00:00"));
        assert!(TimeAxis::parse("nope").is_err());
    }

    #[test]
    fn pin_replaces_and_rejects_a_fact() {
        let store = MetadataStore::open_in_memory().unwrap();
        save(
            &store,
            "brief-1",
            "first brief",
            meta(MemoryType::ProjectContext, "brain", "2026-08-01T00:00:00+00:00", None),
        );
        save(
            &store,
            "brief-2",
            "second brief",
            meta(MemoryType::ProjectContext, "brain", "2026-08-02T00:00:00+00:00", None),
        );
        save(
            &store,
            "a-fact",
            "not a brief",
            meta(MemoryType::Fact, "brain", "2026-08-03T00:00:00+00:00", None),
        );
        assert!(pin_project_brief(store.conn(), "brain", "a-fact").is_err());
        pin_project_brief(store.conn(), "BRAIN", "brief-1").unwrap();
        let replaced = pin_project_brief(store.conn(), "brain", "brief-2").unwrap();
        assert_eq!(replaced.previous_memory_id.as_deref(), Some("brief-1"));
        let brief = project_brief(store.conn(), "brain", 5).unwrap();
        assert_eq!(brief.pinned.as_ref().unwrap().memory_id, "brief-2");
        assert_eq!(brief.pinned.as_ref().unwrap().state, "current");
        assert!(brief.briefs.iter().all(|row| row.id != "brief-2"));
        assert!(unpin_project_brief(store.conn(), "brain").unwrap());
        assert!(project_brief(store.conn(), "brain", 5).unwrap().pinned.is_none());
    }

    #[test]
    fn follow_walks_a_successor_and_stops_on_quarantine() {
        let store = MetadataStore::open_in_memory().unwrap();
        save(
            &store,
            "older",
            "old",
            meta(MemoryType::Fact, "brain", "2026-08-01T00:00:00+00:00", None),
        );
        save(
            &store,
            "newer",
            "new",
            meta(MemoryType::Fact, "brain", "2026-08-02T00:00:00+00:00", None),
        );
        save(
            &store,
            "boxed",
            "boxed",
            meta(MemoryType::Fact, "brain", "2026-08-03T00:00:00+00:00", None),
        );
        store.conn().execute("UPDATE memories SET superseded_by = 'newer' WHERE id = 'older'", []).unwrap();
        store.conn().execute("UPDATE memories SET superseded_by = 'quarantine:test' WHERE id = 'boxed'", []).unwrap();
        let followed = follow_memory(store.conn(), "older").unwrap();
        assert_eq!(followed.status, "replaced");
        assert_eq!(followed.chain.len(), 2);
        assert_eq!(followed.chain[1].id, "newer");
        assert_eq!(followed.predecessors.len(), 0);
        let back = follow_memory(store.conn(), "newer").unwrap();
        assert_eq!(back.status, "current");
        assert_eq!(back.predecessors[0].id, "older");
        let boxed = follow_memory(store.conn(), "boxed").unwrap();
        assert_eq!(boxed.status, "quarantined");
        assert_eq!(follow_memory(store.conn(), "missing").unwrap().status, "missing");
        store.conn().execute("UPDATE memories SET superseded_by = 'gone' WHERE id = 'newer'", []).unwrap();
        assert_eq!(follow_memory(store.conn(), "newer").unwrap().status, "dangling");
    }

    #[test]
    fn related_memories_reads_real_rows_from_either_direction() {
        let store = MetadataStore::open_in_memory().unwrap();
        save(&store, "a", "memory a", meta(MemoryType::Fact, "p", "2026-01-01T00:00:00+00:00", None));
        save(&store, "b", "memory b", meta(MemoryType::Fact, "p", "2026-01-02T00:00:00+00:00", None));
        save(&store, "c", "memory c", meta(MemoryType::Fact, "p", "2026-01-03T00:00:00+00:00", None));

        // a -> b (a's own KNN query found b). c -> a (c's query found a) --
        // the opposite direction, still must surface when querying "a".
        crate::similar::insert_similar_link(store.conn(), "s1", "a", "b", 0.9).unwrap();
        crate::similar::insert_similar_link(store.conn(), "s2", "c", "a", 0.7).unwrap();

        let related = related_memories(store.conn(), "a", 10).unwrap();
        let ids: Vec<&str> = related.iter().map(|r| r.memory.id.as_str()).collect();
        assert_eq!(ids, vec!["b", "c"], "ordered by weight desc, both directions included");
        assert_eq!(related[0].memory.snippet, "memory b");
        assert!((related[0].weight - 0.9).abs() < 1e-9);
    }

    #[test]
    fn related_memories_is_empty_with_no_similar_to_rows() {
        let store = MetadataStore::open_in_memory().unwrap();
        save(&store, "a", "memory a", meta(MemoryType::Fact, "p", "2026-01-01T00:00:00+00:00", None));
        assert!(related_memories(store.conn(), "a", 10).unwrap().is_empty());
    }

    #[test]
    fn related_memories_ignores_other_relation_types() {
        let store = MetadataStore::open_in_memory().unwrap();
        save(&store, "a", "memory a", meta(MemoryType::Fact, "p", "2026-01-01T00:00:00+00:00", None));
        save(&store, "b", "memory b", meta(MemoryType::Fact, "p", "2026-01-02T00:00:00+00:00", None));
        crate::layer::insert_layer_link(store.conn(), "l1", "b", "a", 0.9).unwrap();
        assert!(
            related_memories(store.conn(), "a", 10).unwrap().is_empty(),
            "a layers_on row must not be mistaken for similar_to"
        );
    }
}
