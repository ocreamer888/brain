//! Atlas datasets: a points table, a links table, and a config, stored the way
//! Cosmograph projects store them (the AI Model Atlas: nodes with
//! `layout_x/y/z`, links by node id, a project config naming which column is
//! the label / colour / size). Lives in each brain's own database.
//!
//! Positions are data: computed once, stored, read by the viewer.

use std::collections::HashMap;
use std::io::{BufRead, BufReader};
use std::path::Path;

use rusqlite::{params, Connection};
use serde::{Deserialize, Serialize};

use crate::error::BrainError;

const SCHEMA: &str = "
CREATE TABLE IF NOT EXISTS atlas_points (
  id     TEXT PRIMARY KEY,
  label  TEXT NOT NULL DEFAULT '',
  color  TEXT NOT NULL DEFAULT '',   -- categorical colour key (e.g. author)
  size   REAL NOT NULL DEFAULT 1,
  x REAL NOT NULL, y REAL NOT NULL, z REAL NOT NULL,
  attrs  TEXT NOT NULL DEFAULT '{}'  -- every other column, JSON
);
CREATE TABLE IF NOT EXISTS atlas_links (
  id     TEXT PRIMARY KEY,
  source TEXT NOT NULL,
  target TEXT NOT NULL,
  color  TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_atlas_links_source ON atlas_links(source);
CREATE INDEX IF NOT EXISTS idx_atlas_links_target ON atlas_links(target);
CREATE TABLE IF NOT EXISTS atlas_meta (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);";

fn db(e: rusqlite::Error) -> BrainError {
    BrainError::Database(e.to_string())
}

pub fn create_schema(conn: &Connection) -> Result<(), BrainError> {
    conn.execute_batch(SCHEMA).map_err(db)
}

/// Which source column feeds each atlas field (Cosmograph's `columnMapping`).
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ColumnMapping {
    pub id: String,
    pub label: String,
    pub color: String,
    pub size: String,
    pub x: String,
    pub y: String,
    pub z: String,
    pub link_source: String,
    pub link_target: String,
    pub link_id: String,
    pub link_color: String,
}

/// Viewer settings stored with the data (Cosmograph's `cosmographConfig`).
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct AtlasConfig {
    pub title: String,
    pub description: String,
    pub palette: Vec<String>,
    pub point_size_range: [f64; 2],
    pub link_opacity: f64,
    pub quantile_extent: [f64; 2],
    pub background: String,
}

#[derive(Debug, Default, PartialEq)]
pub struct ImportReport {
    pub points: usize,
    pub links: usize,
    pub links_skipped: usize,
}

/// One CSV record (RFC 4180: quoted fields, doubled quotes, newlines inside quotes).
fn records(path: &Path) -> Result<impl Iterator<Item = Result<Vec<String>, BrainError>>, BrainError> {
    let file = std::fs::File::open(path).map_err(|e| BrainError::Database(format!("{}: {e}", path.display())))?;
    let mut lines = BufReader::new(file).lines();
    Ok(std::iter::from_fn(move || {
        let mut fields = Vec::new();
        let mut cur = String::new();
        let mut quoted = false;
        loop {
            let line = match lines.next()? {
                Ok(l) => l,
                Err(e) => return Some(Err(BrainError::Database(e.to_string()))),
            };
            let mut chars = line.chars().peekable();
            while let Some(c) = chars.next() {
                match (c, quoted) {
                    ('"', true) if chars.peek() == Some(&'"') => {
                        cur.push('"');
                        chars.next();
                    }
                    ('"', _) => quoted = !quoted,
                    (',', false) => fields.push(std::mem::take(&mut cur)),
                    _ => cur.push(c),
                }
            }
            if quoted {
                cur.push('\n'); // field continues on the next line
                continue;
            }
            fields.push(cur);
            return Some(Ok(fields));
        }
    }))
}

fn column(header: &[String], name: &str, file: &Path) -> Result<usize, BrainError> {
    header
        .iter()
        .position(|h| h == name)
        .ok_or_else(|| BrainError::Database(format!("{}: no column '{name}'", file.display())))
}

/// Replace this brain's atlas with the given points and links CSVs.
/// Links whose endpoints are not in the points table are skipped and counted.
pub fn import_csv(
    conn: &mut Connection,
    points: &Path,
    links: &Path,
    map: &ColumnMapping,
    config: &AtlasConfig,
) -> Result<ImportReport, BrainError> {
    create_schema(conn)?;
    let tx = conn.transaction().map_err(db)?;
    tx.execute_batch("DELETE FROM atlas_links; DELETE FROM atlas_points; DELETE FROM atlas_meta;")
        .map_err(db)?;
    let mut report = ImportReport::default();
    let mut ids = std::collections::HashSet::new();
    {
        let mut rows = records(points)?;
        let header = rows.next().ok_or_else(|| BrainError::Database("points: empty file".into()))??;
        let col = |n: &str| column(&header, n, points);
        let (ci, cl, cc, cs, cx, cy, cz) =
            (col(&map.id)?, col(&map.label)?, col(&map.color)?, col(&map.size)?, col(&map.x)?, col(&map.y)?, col(&map.z)?);
        let mapped = [ci, cl, cc, cs, cx, cy, cz];
        let mut ins = tx
            .prepare("INSERT INTO atlas_points(id,label,color,size,x,y,z,attrs) VALUES(?,?,?,?,?,?,?,?)")
            .map_err(db)?;
        for row in rows {
            let row = row?;
            let num = |i: usize| row.get(i).and_then(|v| v.parse::<f64>().ok());
            let (Some(x), Some(y), Some(z)) = (num(cx), num(cy), num(cz)) else {
                return Err(BrainError::Database(format!("points: row without a position: {:?}", row.get(ci))));
            };
            let Some(id) = row.get(ci).cloned() else {
                return Err(BrainError::Database(format!("points: row missing id column: {:?}", row)));
            };
            let attrs: serde_json::Map<String, serde_json::Value> = header
                .iter()
                .enumerate()
                .filter(|(i, _)| !mapped.contains(i))
                .map(|(i, h)| (h.clone(), serde_json::Value::String(row.get(i).cloned().unwrap_or_default())))
                .collect();
            ins.execute(params![
                id,
                row.get(cl).cloned().unwrap_or_default(),
                row.get(cc).cloned().unwrap_or_default(),
                num(cs).unwrap_or(1.0),
                x,
                y,
                z,
                serde_json::Value::Object(attrs).to_string()
            ])
            .map_err(db)?;
            ids.insert(id);
            report.points += 1;
        }
    }
    {
        let mut rows = records(links)?;
        let header = rows.next().ok_or_else(|| BrainError::Database("links: empty file".into()))??;
        let col = |n: &str| column(&header, n, links);
        let (cs, ct, ci, cc) = (col(&map.link_source)?, col(&map.link_target)?, col(&map.link_id)?, col(&map.link_color)?);
        let mut ins = tx
            .prepare("INSERT OR REPLACE INTO atlas_links(id,source,target,color) VALUES(?,?,?,?)")
            .map_err(db)?;
        for row in rows {
            let row = row?;
            let (Some(src), Some(tgt)) = (row.get(cs).cloned(), row.get(ct).cloned()) else {
                return Err(BrainError::Database(format!("links: row missing source/target column: {:?}", row)));
            };
            if !ids.contains(&src) || !ids.contains(&tgt) {
                report.links_skipped += 1;
                continue;
            }
            let link_id = row.get(ci).cloned().unwrap_or_default();
            ins.execute(params![link_id, src, tgt, row.get(cc).cloned().unwrap_or_default()])
                .map_err(db)?;
            report.links += 1;
        }
    }
    let meta = [
        ("config", serde_json::to_string(config).unwrap_or_default()),
        ("mapping", serde_json::to_string(map).unwrap_or_default()),
        ("imported_at", chrono::Utc::now().to_rfc3339()),
    ];
    for (k, v) in meta {
        tx.execute("INSERT INTO atlas_meta(key,value) VALUES(?,?)", params![k, v]).map_err(db)?;
    }
    tx.commit().map_err(db)?;
    Ok(report)
}

/// The atlas, columnar (parallel arrays), ready for the GPU. Colour keys are
/// replaced by a category index ranked by frequency (most common = 0), which is
/// how the reference assigns its palette.
#[derive(Debug, Serialize)]
pub struct AtlasColumns {
    pub config: AtlasConfig,
    pub imported_at: String,
    pub categories: Vec<String>,
    pub category_counts: Vec<u32>,
    pub id: Vec<String>,
    pub label: Vec<String>,
    pub category: Vec<u32>,
    pub size: Vec<f32>,
    pub xyz: Vec<f32>,
    /// Links as point indices: [s, t, s, t, …].
    pub links: Vec<u32>,
    /// Links are coloured from their endpoints in the viewer, so link colours aren't sent.
    pub link_count: usize,
}

impl AtlasColumns {
    fn empty() -> Self {
        Self {
            config: AtlasConfig::default(),
            imported_at: String::new(),
            categories: Vec::new(),
            category_counts: Vec::new(),
            id: Vec::new(),
            label: Vec::new(),
            category: Vec::new(),
            size: Vec::new(),
            xyz: Vec::new(),
            links: Vec::new(),
            link_count: 0,
        }
    }
}

/// Open a brain's database for reading the atlas only (never writes).
pub fn open_read(path: &str) -> Result<Connection, BrainError> {
    let conn = Connection::open_with_flags(path, rusqlite::OpenFlags::SQLITE_OPEN_READ_ONLY | rusqlite::OpenFlags::SQLITE_OPEN_NO_MUTEX)
        .map_err(db)?;
    conn.busy_timeout(std::time::Duration::from_secs(5)).map_err(db)?;
    Ok(conn)
}

fn has_atlas(conn: &Connection) -> Result<bool, BrainError> {
    conn.query_row("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='atlas_points'", [], |r| r.get::<_, i64>(0))
        .map(|n| n > 0)
        .map_err(db)
}

/// Cheap fingerprint of the stored atlas (changes on every import): for ETags.
/// `None` when this brain has no atlas.
pub fn version(conn: &Connection) -> Result<Option<String>, BrainError> {
    if !has_atlas(conn)? {
        return Ok(None);
    }
    let v: Option<String> = conn
        .query_row("SELECT value FROM atlas_meta WHERE key='imported_at'", [], |r| r.get(0))
        .map(Some)
        .or_else(|e| if matches!(e, rusqlite::Error::QueryReturnedNoRows) { Ok(None) } else { Err(db(e)) })?;
    Ok(v)
}

/// Geometry as one little-endian binary block, so the viewer can hand it
/// straight to the GPU: u32 n, u32 m, f32 xyz[3n], f32 size[n], u32 category[n], u32 links[2m].
pub fn geometry_bytes(a: &AtlasColumns) -> Vec<u8> {
    let n = a.id.len();
    let m = a.link_count;
    let mut out = Vec::with_capacity(8 + n * 20 + m * 8);
    out.extend_from_slice(&(n as u32).to_le_bytes());
    out.extend_from_slice(&(m as u32).to_le_bytes());
    for v in &a.xyz {
        out.extend_from_slice(&v.to_le_bytes());
    }
    for v in &a.size {
        out.extend_from_slice(&v.to_le_bytes());
    }
    for v in &a.category {
        out.extend_from_slice(&v.to_le_bytes());
    }
    for v in &a.links {
        out.extend_from_slice(&v.to_le_bytes());
    }
    out
}

pub fn read_columns(conn: &Connection) -> Result<AtlasColumns, BrainError> {
    if !has_atlas(conn)? {
        return Ok(AtlasColumns::empty());
    }
    let meta: HashMap<String, String> = conn
        .prepare("SELECT key, value FROM atlas_meta")
        .map_err(db)?
        .query_map([], |r| Ok((r.get(0)?, r.get(1)?)))
        .map_err(db)?
        .collect::<Result<_, _>>()
        .map_err(db)?;
    let mut out = AtlasColumns::empty();
    out.config = meta.get("config").and_then(|c| serde_json::from_str(c).ok()).unwrap_or_default();
    out.imported_at = meta.get("imported_at").cloned().unwrap_or_default();
    let mut colors = Vec::new();
    let mut stmt = conn
        .prepare("SELECT id, label, color, size, x, y, z FROM atlas_points ORDER BY rowid")
        .map_err(db)?;
    let mut rows = stmt.query([]).map_err(db)?;
    while let Some(r) = rows.next().map_err(db)? {
        out.id.push(r.get(0).map_err(db)?);
        out.label.push(r.get(1).map_err(db)?);
        colors.push(r.get::<_, String>(2).map_err(db)?);
        out.size.push(r.get::<_, f64>(3).map_err(db)? as f32);
        for i in 4..7 {
            out.xyz.push(r.get::<_, f64>(i).map_err(db)? as f32);
        }
    }

    let mut counts: HashMap<&str, u32> = HashMap::new();
    for c in &colors {
        *counts.entry(c).or_default() += 1;
    }
    let mut ranked: Vec<(&str, u32)> = counts.into_iter().collect();
    ranked.sort_by(|a, b| b.1.cmp(&a.1).then(a.0.cmp(b.0)));
    let rank: HashMap<&str, u32> = ranked.iter().enumerate().map(|(i, (c, _))| (*c, i as u32)).collect();
    out.category = colors.iter().map(|c| rank[c.as_str()]).collect();
    out.categories = ranked.iter().map(|(c, _)| c.to_string()).collect();
    out.category_counts = ranked.iter().map(|(_, n)| *n).collect();

    let index: HashMap<&str, u32> = out.id.iter().enumerate().map(|(i, id)| (id.as_str(), i as u32)).collect();
    let mut stmt = conn.prepare("SELECT source, target FROM atlas_links ORDER BY rowid").map_err(db)?;
    let mut rows = stmt.query([]).map_err(db)?;
    while let Some(r) = rows.next().map_err(db)? {
        let (s, t): (String, String) = (r.get(0).map_err(db)?, r.get(1).map_err(db)?);
        if let (Some(a), Some(b)) = (index.get(s.as_str()), index.get(t.as_str())) {
            out.links.push(*a);
            out.links.push(*b);
        }
    }
    out.link_count = out.links.len() / 2;
    Ok(out)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn write(dir: &Path, name: &str, body: &str) -> std::path::PathBuf {
        let p = dir.join(name);
        std::fs::write(&p, body).unwrap();
        p
    }

    fn mapping() -> ColumnMapping {
        ColumnMapping {
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
        }
    }

    #[test]
    fn imports_reads_columnar_and_ranks_categories() {
        let dir = tempfile::tempdir().unwrap();
        let points = write(
            dir.path(),
            "p.csv",
            "id,size,label,author,license,layout_x,layout_y,layout_z\n\
             1,50,\"a, \"\"quoted\"\" model\",bob,mit,1,2,3\n\
             2,60,second,alice,apache,4,5,6\n\
             3,70,\"multi\nline\",alice,mit,7,8,9\n",
        );
        let links = write(dir.path(), "l.csv", "source,target,id,color\n1,2,10,red\n2,3,11,\"rgb(1,2,3)\"\n2,99,12,x\n");
        let mut conn = Connection::open_in_memory().unwrap();
        let report = import_csv(&mut conn, &points, &links, &mapping(), &AtlasConfig::default()).unwrap();
        assert_eq!(report, ImportReport { points: 3, links: 2, links_skipped: 1 });

        let a = read_columns(&conn).unwrap();
        assert_eq!(a.label, vec!["a, \"quoted\" model", "second", "multi\nline"]);
        assert_eq!(a.categories, vec!["alice", "bob"]); // most common first
        assert_eq!(a.category, vec![1, 0, 0]);
        assert_eq!(a.xyz, vec![1., 2., 3., 4., 5., 6., 7., 8., 9.]);
        assert_eq!(a.links, vec![0, 1, 1, 2]);
        let attrs: String = conn.query_row("SELECT attrs FROM atlas_points WHERE id='1'", [], |r| r.get(0)).unwrap();
        assert_eq!(attrs, r#"{"license":"mit"}"#);
    }

    #[test]
    fn reimport_replaces_and_missing_column_is_named() {
        let dir = tempfile::tempdir().unwrap();
        let p = write(dir.path(), "p.csv", "id,size,label,author,layout_x,layout_y,layout_z\n1,1,a,b,0,0,0\n");
        let l = write(dir.path(), "l.csv", "source,target,id,color\n");
        let mut conn = Connection::open_in_memory().unwrap();
        import_csv(&mut conn, &p, &l, &mapping(), &AtlasConfig::default()).unwrap();
        import_csv(&mut conn, &p, &l, &mapping(), &AtlasConfig::default()).unwrap();
        assert_eq!(read_columns(&conn).unwrap().id.len(), 1);

        let bad = write(dir.path(), "bad.csv", "id,label\n1,a\n");
        let err = import_csv(&mut conn, &bad, &l, &mapping(), &AtlasConfig::default()).unwrap_err();
        assert!(err.to_string().contains("no column 'author'"), "{err}");
        assert_eq!(read_columns(&conn).unwrap().id.len(), 1, "a failed import leaves the old atlas");
    }

    #[test]
    fn geometry_bytes_layout() {
        let dir = tempfile::tempdir().unwrap();
        let p = write(dir.path(), "p.csv", "id,size,label,author,layout_x,layout_y,layout_z\n1,2,a,b,1,2,3\n2,4,c,b,4,5,6\n");
        let l = write(dir.path(), "l.csv", "source,target,id,color\n1,2,9,x\n");
        let mut conn = Connection::open_in_memory().unwrap();
        import_csv(&mut conn, &p, &l, &mapping(), &AtlasConfig::default()).unwrap();
        let a = read_columns(&conn).unwrap();
        let b = geometry_bytes(&a);
        let u32_at = |o: usize| u32::from_le_bytes(b[o..o + 4].try_into().unwrap());
        let f32_at = |o: usize| f32::from_le_bytes(b[o..o + 4].try_into().unwrap());
        assert_eq!((u32_at(0), u32_at(4)), (2, 1));
        assert_eq!(f32_at(8 + 5 * 4), 6.0); // last z
        assert_eq!(f32_at(8 + 6 * 4 + 4), 4.0); // second size
        assert_eq!(u32_at(8 + 8 * 4 + 4), 0); // second category
        assert_eq!((u32_at(8 + 10 * 4), u32_at(8 + 11 * 4)), (0, 1)); // the link
        assert_eq!(b.len(), 8 + 2 * 20 + 8);
        assert!(version(&conn).unwrap().is_some());
    }

    #[test]
    fn empty_atlas_reads_empty() {
        let conn = Connection::open_in_memory().unwrap();
        let a = read_columns(&conn).unwrap();
        assert!(a.id.is_empty() && a.links.is_empty());
        assert_eq!(version(&conn).unwrap(), None, "a brain without atlas tables has no version");
    }
}
