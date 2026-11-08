//! The memory atlas: a 3D layout of a brain's live memories, stored as data.
//!
//! Follows the AI Model Atlas practice (see `atlas.rs`): positions are computed
//! once by a quality layout and stored; everything else (labels, types, links)
//! is read live from the memories / entities / edges tables, so nothing is
//! duplicated and nothing goes stale. Memories saved after the last layout are
//! placed provisionally next to their main topic until the next rebuild.
//!
//! Layout (ported from the tuned `ui/scripts/layout_atlas.mjs`, 2026-10-19):
//!   forest  each memory → its most-mentioned shared entity; each hub entity →
//!           the bigger hub it is co-mentioned with in ≥ 15% of its memories;
//!           memories with no shared entity get a layout-only pull to their
//!           most similar linked memory in the same project (never drawn);
//!   bodies  each connected family simulated alone into a solid ball;
//!   packing families placed biggest-first at the centre, small ones in a shell.

use std::collections::{HashMap, HashSet};

use rusqlite::{params, Connection};
use serde_json::{json, Value};

use crate::error::BrainError;

pub const ALGORITHM: &str = "forest-pack/1";
const TYPES: [&str; 9] = ["fact", "knowledge", "decision", "solution", "pattern", "error_lesson", "conversation", "project_context", "episode"];
const HUB_LINK_SHARE: f64 = 0.15;
const MIN_ENTITY_DEGREE: usize = 2;
const DIM: usize = 768;

fn db(e: rusqlite::Error) -> BrainError {
    BrainError::Database(e.to_string())
}

const SCHEMA: &str = "
CREATE TABLE IF NOT EXISTS memory_atlas_runs (
  id          TEXT PRIMARY KEY,
  status      TEXT NOT NULL,              -- running | done | failed
  algorithm   TEXT NOT NULL,
  started_at  TEXT NOT NULL,
  finished_at TEXT,
  points      INTEGER,
  families    INTEGER,
  error       TEXT
);
CREATE TABLE IF NOT EXISTS memory_atlas_positions (
  run_id     TEXT NOT NULL REFERENCES memory_atlas_runs(id) ON DELETE CASCADE,
  point_kind INTEGER NOT NULL,            -- 0 memory, 1 entity
  point_id   TEXT NOT NULL,
  x REAL NOT NULL, y REAL NOT NULL, z REAL NOT NULL,
  PRIMARY KEY (run_id, point_kind, point_id)
);";

pub fn create_schema(conn: &Connection) -> Result<(), BrainError> {
    conn.execute_batch(SCHEMA).map_err(db)
}

// ---------------------------------------------------------------- forest ----

/// The live graph the atlas draws: points (memories, then hub entities) and real links.
pub struct Forest {
    pub mem_id: Vec<String>,
    pub mem_type: Vec<usize>,
    pub mem_project: Vec<usize>,
    pub mem_label: Vec<String>,
    mem_embedding: Vec<Option<Vec<f32>>>,
    pub hub_id: Vec<String>,
    pub hub_name: Vec<String>,
    pub hub_project: Vec<usize>,
    pub projects: Vec<(String, usize)>,
    /// Real links that shape the layout, as point indices (memory i, hub nmem + j).
    pub tree: Vec<(usize, usize)>,
    /// Every other real mention link.
    pub extra: Vec<(usize, usize)>,
    /// `similar_to` links (G7): memory-memory only, decorative like `extra` --
    /// never fed into `layout()`'s spring simulation, same as `extra` already isn't.
    pub similar: Vec<(usize, usize)>,
    /// Point size input: shared entities per memory, tree children per hub.
    pub size: Vec<usize>,
    /// Memory → its parent hub point (None for free memories).
    pub parent: Vec<Option<usize>>,
}

impl Forest {
    pub fn n(&self) -> usize {
        self.mem_id.len() + self.hub_id.len()
    }
}

fn clean_type(raw: &str) -> usize {
    let t = raw.trim().trim_matches('"');
    TYPES.iter().position(|x| *x == t).unwrap_or(6) // unknown → conversation
}

fn label_of(title: Option<String>, body: &str) -> String {
    let text = title.filter(|t| !t.trim().is_empty()).unwrap_or_else(|| body.to_string());
    let words: Vec<&str> = text.split_whitespace().collect();
    words.join(" ").chars().take(100).collect()
}

pub fn build_forest(conn: &Connection, with_embeddings: bool) -> Result<Forest, BrainError> {
    let emb = if with_embeddings { "embedding" } else { "NULL" };
    let mut stmt = conn
        .prepare(&format!(
            "SELECT id, type, title, substr(content, 1, 200), project, {emb} FROM memories
             WHERE superseded_by IS NULL ORDER BY timestamp DESC, id"
        ))
        .map_err(db)?;
    let mut f = Forest {
        mem_id: vec![],
        mem_type: vec![],
        mem_project: vec![],
        mem_label: vec![],
        mem_embedding: vec![],
        hub_id: vec![],
        hub_name: vec![],
        hub_project: vec![],
        projects: vec![],
        tree: vec![],
        extra: vec![],
        similar: vec![],
        size: vec![],
        parent: vec![],
    };
    let mut project_names: Vec<String> = vec![];
    let mut rows = stmt.query([]).map_err(db)?;
    while let Some(r) = rows.next().map_err(db)? {
        f.mem_id.push(r.get(0).map_err(db)?);
        f.mem_type.push(clean_type(&r.get::<_, String>(1).map_err(db)?));
        let body: String = r.get::<_, Option<String>>(3).map_err(db)?.unwrap_or_default();
        f.mem_label.push(label_of(r.get(2).map_err(db)?, &body));
        project_names.push(r.get::<_, Option<String>>(4).map_err(db)?.filter(|p| !p.is_empty()).unwrap_or_else(|| "general".into()));
        let blob: Option<Vec<u8>> = r.get(5).map_err(db)?;
        f.mem_embedding.push(blob.filter(|b| b.len() >= DIM * 4).map(|b| {
            let mut v: Vec<f32> = b[..DIM * 4].chunks_exact(4).map(|c| f32::from_le_bytes(c.try_into().unwrap())).collect();
            let norm = v.iter().map(|x| x * x).sum::<f32>().sqrt().max(1e-8);
            v.iter_mut().for_each(|x| *x /= norm);
            v
        }));
    }
    let nmem = f.mem_id.len();

    // Projects ranked by size (index 0 = biggest), the legend order.
    let mut counts: HashMap<&str, usize> = HashMap::new();
    for p in &project_names {
        *counts.entry(p).or_default() += 1;
    }
    let mut ranked: Vec<(String, usize)> = counts.into_iter().map(|(k, v)| (k.to_string(), v)).collect();
    ranked.sort_by(|a, b| b.1.cmp(&a.1).then(a.0.cmp(&b.0)));
    let pidx: HashMap<String, usize> = ranked.iter().enumerate().map(|(i, (p, _))| (p.clone(), i)).collect();
    f.mem_project = project_names.iter().map(|p| pidx[p]).collect();
    f.projects = ranked;

    // Real mention edges among live memories.
    let mindex: HashMap<&str, usize> = f.mem_id.iter().enumerate().map(|(i, id)| (id.as_str(), i)).collect();
    let mut raw: Vec<(usize, String)> = vec![];
    let mut names: HashMap<String, String> = HashMap::new();
    let mut stmt = conn
        .prepare("SELECT x.src_memory_id, x.dst_entity_id, e.name FROM edges x JOIN entities e ON e.id = x.dst_entity_id")
        .map_err(db)?;
    let mut rows = stmt.query([]).map_err(db)?;
    while let Some(r) = rows.next().map_err(db)? {
        let m: String = r.get(0).map_err(db)?;
        if let Some(&i) = mindex.get(m.as_str()) {
            let e: String = r.get(1).map_err(db)?;
            names.insert(e.clone(), r.get(2).map_err(db)?);
            raw.push((i, e));
        }
    }
    let mut degree: HashMap<String, usize> = HashMap::new();
    for (_, e) in &raw {
        *degree.entry(e.clone()).or_default() += 1;
    }
    let mut mentions: Vec<Vec<String>> = vec![vec![]; nmem];
    for (m, e) in raw {
        if degree[&e] >= MIN_ENTITY_DEGREE && !mentions[m].contains(&e) {
            mentions[m].push(e);
        }
    }
    let rank = |e: &String| (degree[e], e.clone());

    // Memory → its most-mentioned entity.
    let parent_entity: Vec<Option<String>> = mentions.iter().map(|es| es.iter().max_by_key(|e| rank(e)).cloned()).collect();
    let mut hubs: Vec<String> = parent_entity.iter().flatten().cloned().collect::<HashSet<_>>().into_iter().collect();
    hubs.sort_by(|a, b| degree[b].cmp(&degree[a]).then(names[a].to_lowercase().cmp(&names[b].to_lowercase())).then(a.cmp(b)));
    let hub_index: HashMap<&str, usize> = hubs.iter().enumerate().map(|(j, h)| (h.as_str(), nmem + j)).collect();

    // Hub → the bigger hub it is co-mentioned with most (if ≥ HUB_LINK_SHARE of its memories).
    let mut kids: HashMap<&str, usize> = HashMap::new();
    for p in parent_entity.iter().flatten() {
        *kids.entry(p.as_str()).or_default() += 1;
    }
    let mut co: HashMap<&str, HashMap<&str, usize>> = HashMap::new();
    for es in &mentions {
        let hs: Vec<&str> = es.iter().map(|e| e.as_str()).filter(|e| hub_index.contains_key(e)).collect();
        for a in &hs {
            for b in &hs {
                if a != b {
                    *co.entry(a).or_default().entry(b).or_default() += 1;
                }
            }
        }
    }
    let mut parent_of_hub: Vec<(usize, usize)> = vec![];
    for h in &hubs {
        let own = kids.get(h.as_str()).copied().unwrap_or(0) as f64;
        let best = co.get(h.as_str()).and_then(|m| {
            m.iter()
                .filter(|(b, w)| rank(&b.to_string()) > rank(h) && (**w as f64) >= HUB_LINK_SHARE * own)
                .max_by_key(|(b, w)| (**w, degree[**b], b.to_string()))
                .map(|(b, _)| *b)
        });
        if let Some(b) = best {
            parent_of_hub.push((hub_index[h.as_str()], hub_index[b]));
        }
    }

    f.parent = parent_entity.iter().map(|p| p.as_ref().map(|e| hub_index[e.as_str()])).collect();
    for (m, p) in f.parent.iter().enumerate() {
        if let Some(p) = p {
            f.tree.push((m, *p));
        }
    }
    f.tree.extend(parent_of_hub.iter().copied());
    for (m, es) in mentions.iter().enumerate() {
        for e in es {
            if Some(e) != parent_entity[m].as_ref() {
                if let Some(&h) = hub_index.get(e.as_str()) {
                    f.extra.push((m, h));
                }
            }
        }
    }

    // similar_to links (G7 backfill): memory-memory only. The table is written
    // from each side's own KNN query, so a mutual pair stores both directions --
    // dedupe by unordered pair so it draws as one line, not two stacked ones.
    let mut seen_similar: HashSet<(usize, usize)> = HashSet::new();
    let mut stmt = conn
        .prepare("SELECT src_memory_id, dst_memory_id FROM memory_links WHERE relation_type = 'similar_to'")
        .map_err(db)?;
    let mut rows = stmt.query([]).map_err(db)?;
    while let Some(r) = rows.next().map_err(db)? {
        let src: String = r.get(0).map_err(db)?;
        let dst: String = r.get(1).map_err(db)?;
        if let (Some(&a), Some(&b)) = (mindex.get(src.as_str()), mindex.get(dst.as_str())) {
            if a != b && seen_similar.insert((a.min(b), a.max(b))) {
                f.similar.push((a.min(b), a.max(b)));
            }
        }
    }

    // Sizes and hub projects (where most of a hub's memories live).
    let mut children = vec![0usize; nmem + hubs.len()];
    let mut votes: Vec<HashMap<usize, usize>> = vec![HashMap::new(); hubs.len()];
    for &(a, b) in &f.tree {
        children[b] += 1;
        if a < nmem {
            *votes[b - nmem].entry(f.mem_project[a]).or_default() += 1;
        }
    }
    f.size = (0..nmem).map(|m| mentions[m].len()).chain((0..hubs.len()).map(|j| children[nmem + j])).collect();
    f.hub_project = votes.iter().map(|v| v.iter().max_by_key(|(p, n)| (**n, usize::MAX - **p)).map(|(p, _)| *p).unwrap_or(0)).collect();
    f.hub_name = hubs.iter().map(|h| names[h].clone()).collect();
    f.hub_id = hubs;
    Ok(f)
}

/// Free memories (no shared entity) → most similar linked memory in their project. Layout only.
fn free_springs(f: &Forest) -> Vec<(usize, usize)> {
    let mut by_project: HashMap<usize, (Vec<usize>, Vec<usize>)> = HashMap::new();
    for m in 0..f.mem_id.len() {
        if f.mem_embedding[m].is_none() {
            continue;
        }
        let e = by_project.entry(f.mem_project[m]).or_default();
        if f.parent[m].is_some() { e.0.push(m) } else { e.1.push(m) }
    }
    let mut out = vec![];
    for (linked, free) in by_project.values() {
        for &a in free {
            let va = f.mem_embedding[a].as_ref().unwrap();
            let best = linked.iter().max_by(|&&x, &&y| {
                let dot = |m: usize| f.mem_embedding[m].as_ref().unwrap().iter().zip(va).map(|(p, q)| p * q).sum::<f32>();
                dot(x).total_cmp(&dot(y))
            });
            if let Some(&b) = best {
                out.push((a, b));
            }
        }
    }
    out
}

// ---------------------------------------------------------------- layout ----

pub struct Params {
    pub link_distance: f64,
    pub spring_distance: f64,
    pub collide: f64,
    pub charge: f64,
    pub charge_range: f64,
    pub gravity: f64,
    pub gap: f64,
    pub core: usize,
    pub shell: f64,
    pub ticks: usize,
}

impl Default for Params {
    fn default() -> Self {
        Self { link_distance: 2.0, spring_distance: 2.5, collide: 1.6, charge: -0.3, charge_range: 30.0, gravity: 0.22, gap: 1.05, core: 150, shell: 1.6, ticks: 260 }
    }
}

/// Seeded LCG (same as the JS layout) so a layout is reproducible.
struct Rng(u64);
impl Rng {
    fn next(&mut self) -> f64 {
        self.0 = (self.0.wrapping_mul(1664525).wrapping_add(1013904223)) % 4294967296;
        self.0 as f64 / 4294967296.0
    }
}

type V3 = [f64; 3];

/// One family relaxed into a solid body around the origin (d3-force semantics:
/// link, many-body within a range, collision, gravity; velocity decay 0.4).
fn relax(n: usize, links: &[(usize, usize, f64, f64)], p: &Params, rng: &mut Rng, warm: Option<Vec<V3>>) -> Vec<V3> {
    let r0 = 2.0 * (n as f64).cbrt();
    let random: Vec<V3> = (0..n).map(|_| [(rng.next() - 0.5) * r0, (rng.next() - 0.5) * r0, (rng.next() - 0.5) * r0]).collect();
    // Warm start: begin from the previous shape and settle gently (d3's reheat to 0.3).
    let (mut pos, mut alpha) = match warm {
        Some(w) => (w, 0.3),
        None => (random, 1.0),
    };
    if n < 2 {
        return pos;
    }
    let mut vel = vec![[0.0; 3]; n];
    let mut count = vec![0usize; n];
    for &(a, b, _, _) in links {
        count[a] += 1;
        count[b] += 1;
    }
    let ticks = p.ticks.min(60 + n);
    let decay = 1.0 - 0.001f64.powf(1.0 / ticks as f64);
    let cell = p.charge_range;
    let r = 2.0 * p.collide;
    for _ in 0..ticks {
        alpha += (0.0 - alpha) * decay;
        for &(s, t, d, w) in links {
            let mut x = [0.0; 3];
            for k in 0..3 {
                x[k] = pos[t][k] + vel[t][k] - pos[s][k] - vel[s][k];
            }
            let mut l = (x[0] * x[0] + x[1] * x[1] + x[2] * x[2]).sqrt();
            if l < 1e-9 {
                x = [1e-6, 0.0, 0.0];
                l = 1e-6;
            }
            let f = (l - d) / l * alpha * w;
            let bias = count[s] as f64 / (count[s] + count[t]) as f64;
            for k in 0..3 {
                vel[t][k] -= x[k] * f * bias;
                vel[s][k] += x[k] * f * (1.0 - bias);
            }
        }
        // Uniform grid: only pairs within the charge range interact.
        let mut grid: HashMap<(i64, i64, i64), Vec<usize>> = HashMap::new();
        let key = |v: &V3| ((v[0] / cell).floor() as i64, (v[1] / cell).floor() as i64, (v[2] / cell).floor() as i64);
        for (i, v) in pos.iter().enumerate() {
            grid.entry(key(v)).or_default().push(i);
        }
        for i in 0..n {
            let (cx, cy, cz) = key(&pos[i]);
            for dx in -1..=1 {
                for dy in -1..=1 {
                    for dz in -1..=1 {
                        let Some(cellv) = grid.get(&(cx + dx, cy + dy, cz + dz)) else { continue };
                        for &j in cellv {
                            if j == i {
                                continue;
                            }
                            let d = [pos[j][0] - pos[i][0], pos[j][1] - pos[i][1], pos[j][2] - pos[i][2]];
                            let mut l2 = d[0] * d[0] + d[1] * d[1] + d[2] * d[2];
                            if l2 >= cell * cell {
                                continue;
                            }
                            if l2 < 1.0 {
                                l2 = l2.max(1e-6).sqrt();
                            }
                            let w = p.charge * alpha / l2;
                            for k in 0..3 {
                                vel[i][k] += d[k] * w;
                            }
                            if j > i {
                                let q = [pos[i][0] + vel[i][0] - pos[j][0] - vel[j][0], pos[i][1] + vel[i][1] - pos[j][1] - vel[j][1], pos[i][2] + vel[i][2] - pos[j][2] - vel[j][2]];
                                let l = (q[0] * q[0] + q[1] * q[1] + q[2] * q[2]).sqrt();
                                if l < r && l > 1e-9 {
                                    let s = (r - l) / l * 0.85 * 0.5;
                                    for k in 0..3 {
                                        vel[i][k] += q[k] * s;
                                        vel[j][k] -= q[k] * s;
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
        for i in 0..n {
            for k in 0..3 {
                vel[i][k] += -pos[i][k] * p.gravity * alpha;
                vel[i][k] *= 0.6;
                pos[i][k] += vel[i][k];
            }
        }
    }
    pos
}

/// Positions for every forest point (memories, then hubs) and the number of families.
/// `prev`: positions from the previous layout, keyed by (point kind, id). Families
/// that mostly existed before keep their shape and place; new ones search for space.
pub fn layout(f: &Forest, p: &Params, prev: Option<&HashMap<(i64, String), V3>>) -> (Vec<V3>, usize) {
    let nmem = f.mem_id.len();
    let key = |i: usize| if i < nmem { (0i64, f.mem_id[i].clone()) } else { (1i64, f.hub_id[i - nmem].clone()) };
    let old = |i: usize| prev.and_then(|m| m.get(&key(i)).copied());
    let n = f.n();
    let springs = free_springs(f);
    let mut all: Vec<(usize, usize, f64, f64)> = f.tree.iter().map(|&(a, b)| (a, b, p.link_distance, 1.0)).collect();
    all.extend(springs.iter().map(|&(a, b)| (a, b, p.spring_distance, 0.7)));

    let mut parent: Vec<usize> = (0..n).collect();
    fn find(p: &mut [usize], mut a: usize) -> usize {
        while p[a] != a {
            p[a] = p[p[a]];
            a = p[a];
        }
        a
    }
    for &(a, b, _, _) in &all {
        let (ra, rb) = (find(&mut parent, a), find(&mut parent, b));
        parent[ra] = rb;
    }
    let mut groups: HashMap<usize, Vec<usize>> = HashMap::new();
    let mut order = vec![];
    for i in 0..n {
        let r = find(&mut parent, i);
        if !groups.contains_key(&r) {
            order.push(r);
        }
        groups.entry(r).or_default().push(i);
    }
    let mut links_of: HashMap<usize, Vec<(usize, usize, f64, f64)>> = HashMap::new();
    for &l in &all {
        let r = find(&mut parent, l.0);
        links_of.entry(r).or_default().push(l);
    }
    let mut families: Vec<(Vec<usize>, Vec<(usize, usize, f64, f64)>)> =
        order.iter().map(|r| (groups.remove(r).unwrap(), links_of.remove(r).unwrap_or_default())).collect();
    families.sort_by(|a, b| b.0.len().cmp(&a.0.len()));

    let mut rng = Rng(7);
    let mut out = vec![[0.0; 3]; n];
    let mut radius = vec![0.0; families.len()];
    let mut anchor: Vec<Option<V3>> = vec![None; families.len()];
    for (k, (members, links)) in families.iter().enumerate() {
        let local: HashMap<usize, usize> = members.iter().enumerate().map(|(i, g)| (*g, i)).collect();
        let ll: Vec<_> = links.iter().map(|&(a, b, d, w)| (local[&a], local[&b], d, w)).collect();
        let known: Vec<V3> = members.iter().filter_map(|&g| old(g)).collect();
        let warm = (known.len() * 2 >= members.len() && !known.is_empty()).then(|| {
            let c = known.iter().fold([0.0; 3], |s, v| [s[0] + v[0], s[1] + v[1], s[2] + v[2]]).map(|v| v / known.len() as f64);
            anchor[k] = Some(c);
            // Known points keep their offset from the old centre; new ones start near it.
            members
                .iter()
                .map(|&g| match old(g) {
                    Some(v) => [v[0] - c[0], v[1] - c[1], v[2] - c[2]],
                    None => [(rng.next() - 0.5) * 2.0, (rng.next() - 0.5) * 2.0, (rng.next() - 0.5) * 2.0],
                })
                .collect()
        });
        let pos = relax(members.len(), &ll, p, &mut rng, warm);
        let c = pos.iter().fold([0.0; 3], |s, v| [s[0] + v[0], s[1] + v[1], s[2] + v[2]]).map(|v| v / pos.len() as f64);
        let mut rad: f64 = 0.0;
        for (i, g) in members.iter().enumerate() {
            let v = [pos[i][0] - c[0], pos[i][1] - c[1], pos[i][2] - c[2]];
            rad = rad.max((v[0] * v[0] + v[1] * v[1] + v[2] * v[2]).sqrt());
            out[*g] = v;
        }
        radius[k] = rad.max(p.collide);
    }

    // Packing: biggest first at the centre; satellites in a shell around the core.
    let mut centers: Vec<V3> = vec![];
    let mut core_radius = 0.0;
    for (k, (members, _)) in families.iter().enumerate() {
        if centers.is_empty() {
            centers.push(anchor[k].unwrap_or([0.0; 3]));
            continue;
        }
        if core_radius == 0.0 && members.len() < p.core {
            core_radius = centers.iter().enumerate().map(|(j, c)| (c[0] * c[0] + c[1] * c[1] + c[2] * c[2]).sqrt() + radius[j]).fold(0.0, f64::max);
        }
        let fits = |c: V3| {
            centers.iter().enumerate().all(|(j, o)| {
                let d = [c[0] - o[0], c[1] - o[1], c[2] - o[2]];
                (d[0] * d[0] + d[1] * d[1] + d[2] * d[2]).sqrt() >= p.gap * (radius[k] + radius[j])
            })
        };
        if let Some(a) = anchor[k] {
            if fits(a) {
                centers.push(a); // stays where it was
                continue;
            }
        }
        let random = [rng.next() * 2.0 - 1.0, rng.next() * 2.0 - 1.0, rng.next() * 2.0 - 1.0];
        let mut dir = anchor[k].filter(|a| a.iter().any(|v| v.abs() > 1e-6)).unwrap_or(random);
        let len = (dir[0] * dir[0] + dir[1] * dir[1] + dir[2] * dir[2]).sqrt().max(1e-9);
        dir.iter_mut().for_each(|v| *v /= len);
        let free = |d: f64| {
            centers.iter().enumerate().all(|(j, o)| {
                let c = [dir[0] * d - o[0], dir[1] * d - o[1], dir[2] * d - o[2]];
                (c[0] * c[0] + c[1] * c[1] + c[2] * c[2]).sqrt() >= p.gap * (radius[k] + radius[j])
            })
        };
        let mut hi = 1.0;
        while !free(hi) {
            hi *= 1.6;
        }
        let mut lo = 0.0;
        for _ in 0..24 {
            let mid = (lo + hi) / 2.0;
            if free(mid) { hi = mid } else { lo = mid }
        }
        if members.len() < p.core && core_radius > 0.0 && anchor[k].is_none() {
            let want = core_radius * (1.05 + rng.next() * (p.shell - 1.05));
            if want > hi && free(want) {
                hi = want;
            }
        }
        centers.push(dir.map(|v| v * hi));
    }
    for (k, (members, _)) in families.iter().enumerate() {
        for g in members {
            for d in 0..3 {
                out[*g][d] += centers[k][d];
            }
        }
    }
    (out, families.len())
}

// ----------------------------------------------------------- store / read ----

/// Compute and store a new layout for this brain. Records a `running` row first
/// so status is visible; a failure is recorded and the previous layout stays served.
pub fn rebuild(conn: &mut Connection) -> Result<String, BrainError> {
    create_schema(conn)?;
    let id = uuid::Uuid::new_v4().to_string();
    let now = || chrono::Utc::now().to_rfc3339();
    conn.execute(
        "INSERT INTO memory_atlas_runs(id, status, algorithm, started_at) VALUES(?, 'running', ?, ?)",
        params![id, ALGORITHM, now()],
    )
    .map_err(db)?;
    let previous = match current_run(conn)? {
        Some((run, _)) => Some(stored_positions(conn, &run)?),
        None => None,
    };
    let result = (|| -> Result<(usize, usize, Forest, Vec<V3>), BrainError> {
        let f = build_forest(conn, true)?;
        let (pos, families) = layout(&f, &Params::default(), previous.as_ref());
        Ok((f.n(), families, f, pos))
    })();
    match result {
        Ok((points, families, f, pos)) => {
            let tx = conn.transaction().map_err(db)?;
            {
                let mut ins = tx
                    .prepare("INSERT INTO memory_atlas_positions(run_id, point_kind, point_id, x, y, z) VALUES(?,?,?,?,?,?)")
                    .map_err(db)?;
                let nmem = f.mem_id.len();
                for (i, v) in pos.iter().enumerate() {
                    let (kind, pid) = if i < nmem { (0, &f.mem_id[i]) } else { (1, &f.hub_id[i - nmem]) };
                    ins.execute(params![id, kind, pid, v[0], v[1], v[2]]).map_err(db)?;
                }
            }
            tx.execute(
                "UPDATE memory_atlas_runs SET status='done', finished_at=?, points=?, families=? WHERE id=?",
                params![now(), points as i64, families as i64, id],
            )
            .map_err(db)?;
            // Keep the two newest finished layouts (instant fallback), drop older ones.
            tx.execute(
                "DELETE FROM memory_atlas_positions WHERE run_id IN (SELECT id FROM memory_atlas_runs WHERE status='done' ORDER BY finished_at DESC LIMIT -1 OFFSET 2)",
                [],
            )
            .map_err(db)?;
            tx.execute("DELETE FROM memory_atlas_runs WHERE status='done' AND id NOT IN (SELECT DISTINCT run_id FROM memory_atlas_positions)", [])
                .map_err(db)?;
            tx.commit().map_err(db)?;
            Ok(id)
        }
        Err(e) => {
            conn.execute("UPDATE memory_atlas_runs SET status='failed', finished_at=?, error=? WHERE id=?", params![now(), e.to_string(), id])
                .map_err(db)?;
            conn.execute(
                "DELETE FROM memory_atlas_runs WHERE status='failed' AND id NOT IN (SELECT id FROM memory_atlas_runs WHERE status='failed' ORDER BY finished_at DESC LIMIT 2)",
                [],
            )
            .map_err(db)?;
            Err(e)
        }
    }
}

fn has_table(conn: &Connection, name: &str) -> Result<bool, BrainError> {
    conn.query_row("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?", [name], |r| r.get::<_, i64>(0))
        .map(|n| n > 0)
        .map_err(db)
}

/// Latest run (any status) as JSON, or null.
pub fn status(conn: &Connection) -> Result<Value, BrainError> {
    if !has_table(conn, "memory_atlas_runs")? {
        return Ok(Value::Null);
    }
    conn.query_row(
        "SELECT id, status, started_at, finished_at, points, families, error FROM memory_atlas_runs ORDER BY started_at DESC LIMIT 1",
        [],
        |r| {
            Ok(json!({
                "id": r.get::<_, String>(0)?, "status": r.get::<_, String>(1)?, "started_at": r.get::<_, String>(2)?,
                "finished_at": r.get::<_, Option<String>>(3)?, "points": r.get::<_, Option<i64>>(4)?,
                "families": r.get::<_, Option<i64>>(5)?, "error": r.get::<_, Option<String>>(6)?,
            }))
        },
    )
    .or_else(|e| if matches!(e, rusqlite::Error::QueryReturnedNoRows) { Ok(Value::Null) } else { Err(db(e)) })
}

/// The latest finished layout: (run id, finished at). Cheap: used for ETags.
pub fn current_run(conn: &Connection) -> Result<Option<(String, String)>, BrainError> {
    if !has_table(conn, "memory_atlas_runs")? {
        return Ok(None);
    }
    conn.query_row("SELECT id, finished_at FROM memory_atlas_runs WHERE status='done' ORDER BY finished_at DESC LIMIT 1", [], |r| Ok((r.get(0)?, r.get(1)?)))
        .map(Some)
        .or_else(|e| if matches!(e, rusqlite::Error::QueryReturnedNoRows) { Ok(None) } else { Err(db(e)) })
}

fn stored_positions(conn: &Connection, run_id: &str) -> Result<HashMap<(i64, String), V3>, BrainError> {
    let mut out = HashMap::new();
    let mut stmt = conn.prepare("SELECT point_kind, point_id, x, y, z FROM memory_atlas_positions WHERE run_id=?").map_err(db)?;
    let mut rows = stmt.query([run_id]).map_err(db)?;
    while let Some(r) = rows.next().map_err(db)? {
        out.insert((r.get(0).map_err(db)?, r.get(1).map_err(db)?), [r.get(2).map_err(db)?, r.get(3).map_err(db)?, r.get(4).map_err(db)?]);
    }
    Ok(out)
}

/// Live memories saved since the current layout started (None if never built).
/// Cheap: one count, used to decide automatic rebuilds.
pub fn new_since_layout(conn: &Connection) -> Result<Option<i64>, BrainError> {
    if !has_table(conn, "memory_atlas_runs")? {
        return Ok(None);
    }
    let started: Option<String> = conn
        .query_row("SELECT started_at FROM memory_atlas_runs WHERE status='done' ORDER BY finished_at DESC LIMIT 1", [], |r| r.get(0))
        .map(Some)
        .or_else(|e| if matches!(e, rusqlite::Error::QueryReturnedNoRows) { Ok(None) } else { Err(db(e)) })?;
    let Some(started) = started else { return Ok(None) };
    // julianday() on both sides: timestamps come in "+00:00" and "Z" forms.
    conn.query_row(
        "SELECT COUNT(*) FROM memories WHERE superseded_by IS NULL AND julianday(timestamp) > julianday(?)",
        [started],
        |r| r.get(0),
    )
    .map(Some)
    .map_err(db)
}

/// Deterministic small offset from an id, so provisional points don't flicker.
fn jitter(id: &str, radius: f64) -> V3 {
    let mut h: u64 = 1469598103934665603;
    for b in id.bytes() {
        h = (h ^ b as u64).wrapping_mul(1099511628211);
    }
    let mut rng = Rng(h % 4294967296);
    let v = [rng.next() * 2.0 - 1.0, rng.next() * 2.0 - 1.0, rng.next() * 2.0 - 1.0];
    v.map(|c| c * radius)
}

/// The memory atlas, live, in the viewer's columnar format. Points without a
/// stored position (saved since the layout) are placed next to their parent
/// hub, or in their project, and counted as `unplaced`.
pub fn read(conn: &Connection) -> Result<Value, BrainError> {
    let Some((run_id, built_at)) = current_run(conn)? else {
        return Ok(json!({ "meta": { "built_at": null, "needs_build": true }, "status": status(conn)? }));
    };
    let f = build_forest(conn, false)?;
    let nmem = f.mem_id.len();
    let stored = stored_positions(conn, &run_id)?;

    let id_of = |i: usize| if i < nmem { (0i64, f.mem_id[i].clone()) } else { (1i64, f.hub_id[i - nmem].clone()) };
    let mut pos: Vec<Option<V3>> = (0..f.n()).map(|i| stored.get(&id_of(i)).copied()).collect();
    let placed_count = pos.iter().filter(|p| p.is_some()).count();

    // Hubs first: at the centre of their placed children.
    let mut sums: HashMap<usize, (V3, usize)> = HashMap::new();
    for &(a, b) in &f.tree {
        if let Some(v) = pos[a] {
            let e = sums.entry(b).or_insert(([0.0; 3], 0));
            (0..3).for_each(|k| e.0[k] += v[k]);
            e.1 += 1;
        }
    }
    for j in 0..f.hub_id.len() {
        let i = nmem + j;
        if pos[i].is_none() {
            if let Some((s, c)) = sums.get(&i) {
                pos[i] = Some(s.map(|v| v / *c as f64));
            }
        }
    }
    // Memories: beside their hub; else in their project; else near the centre.
    let mut proj_sum: HashMap<usize, (V3, usize)> = HashMap::new();
    for m in 0..nmem {
        if let Some(v) = pos[m] {
            let e = proj_sum.entry(f.mem_project[m]).or_insert(([0.0; 3], 0));
            (0..3).for_each(|k| e.0[k] += v[k]);
            e.1 += 1;
        }
    }
    for i in 0..f.n() {
        if pos[i].is_some() {
            continue;
        }
        let (_, id) = id_of(i);
        let anchor = if i < nmem {
            f.parent[i].and_then(|h| pos[h]).or_else(|| proj_sum.get(&f.mem_project[i]).map(|(s, c)| s.map(|v| v / *c as f64)))
        } else {
            None
        };
        let base = anchor.unwrap_or([0.0; 3]);
        let j = jitter(&id, if anchor.is_some() { 3.0 } else { 40.0 });
        pos[i] = Some([base[0] + j[0], base[1] + j[1], base[2] + j[2]]);
    }

    let superseded: i64 = conn.query_row("SELECT COUNT(*) FROM memories WHERE superseded_by IS NOT NULL", [], |r| r.get(0)).map_err(db)?;
    let flat = |v: &[(usize, usize)]| v.iter().flat_map(|&(a, b)| [a, b]).collect::<Vec<_>>();
    let xyz: Vec<f64> = pos.iter().flat_map(|p| p.unwrap().map(|v| (v * 10.0).round() / 10.0)).collect();
    Ok(json!({
        "meta": {
            "built_at": built_at,
            "run_id": run_id,
            "memories": nmem,
            "superseded": superseded,
            "entities": f.hub_id.len(),
            "edges": f.tree.len(),
            "extra_edges": f.extra.len(),
            "similar_edges": f.similar.len(),
            "projects": f.projects.len(),
            "unplaced": f.n() - placed_count,
            "layout": ALGORITHM,
        },
        "types": TYPES,
        "projects": f.projects.iter().map(|(n, c)| json!({ "name": n, "count": c })).collect::<Vec<_>>(),
        "points": {
            "id": f.mem_id.iter().chain(f.hub_id.iter()).collect::<Vec<_>>(),
            "kind": (0..f.n()).map(|i| (i >= nmem) as u8).collect::<Vec<_>>(),
            "type": f.mem_type.iter().map(|t| *t as i64).chain(std::iter::repeat(-1).take(f.hub_id.len())).collect::<Vec<_>>(),
            "project": f.mem_project.iter().chain(f.hub_project.iter()).collect::<Vec<_>>(),
            "size": f.size,
            "label": f.mem_label.iter().chain(f.hub_name.iter()).collect::<Vec<_>>(),
            "xyz": xyz,
        },
        "edges": flat(&f.tree),
        "extra": flat(&f.extra),
        "similar": flat(&f.similar),
    }))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::store::MetadataStore;

    /// A small brain: memories in two projects linked through entities, one free memory, one superseded.
    fn fixture() -> (tempfile::TempDir, String) {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("b.db").to_string_lossy().into_owned();
        drop(MetadataStore::open(&path).unwrap()); // creates every table, incl. ours
        let conn = Connection::open(&path).unwrap();
        let mem = |id: &str, project: &str, ts: i64, superseded: bool| {
            conn.execute(
                "INSERT INTO memories(id, content, type, project, timestamp, source, superseded_by) VALUES(?, ?, '\"fact\"', ?, ?, 'claude_code_session', ?)",
                params![id, format!("content of {id}"), project, format!("2026-10-{:02}T00:00:00Z", ts), if superseded { Some("x") } else { None::<&str> }],
            )
            .unwrap();
        };
        let ent = |id: &str| {
            conn.execute("INSERT INTO entities(id, name, name_normalized, created_at) VALUES(?, ?, ?, 't')", params![id, id.to_uppercase(), id]).unwrap();
        };
        let edge = |m: &str, e: &str| {
            conn.execute(
                "INSERT INTO edges(id, src_memory_id, dst_entity_id, created_at) VALUES(?, ?, ?, 't')",
                params![format!("{m}-{e}"), m, e],
            )
            .unwrap();
        };
        for (i, m) in ["a1", "a2", "a3", "b1", "b2"].iter().enumerate() {
            mem(m, if m.starts_with('a') { "alpha" } else { "beta" }, i as i64 + 1, false);
        }
        mem("free", "alpha", 9, false);
        mem("old", "alpha", 10, true);
        ent("react");
        ent("next");
        for m in ["a1", "a2", "a3", "b1"] {
            edge(m, "react");
        }
        for m in ["a1", "b1", "b2"] {
            edge(m, "next");
        }
        edge("old", "react");
        (dir, path)
    }

    #[test]
    fn forest_uses_real_links_and_skips_superseded() {
        let (_d, path) = fixture();
        let conn = Connection::open(&path).unwrap();
        let f = build_forest(&conn, false).unwrap();
        assert_eq!(f.mem_id.len(), 6, "superseded memory excluded");
        assert!(!f.mem_id.contains(&"old".to_string()));
        assert_eq!(f.hub_name, vec!["REACT", "NEXT"], "hubs ranked by degree");
        let free = f.mem_id.iter().position(|m| m == "free").unwrap();
        assert_eq!(f.parent[free], None);
        // b2 only mentions next → its parent is NEXT; next co-mentioned with react in 2/1 → links under REACT.
        let b2 = f.mem_id.iter().position(|m| m == "b2").unwrap();
        assert_eq!(f.parent[b2], Some(f.mem_id.len() + 1));
        assert!(f.tree.contains(&(f.mem_id.len() + 1, f.mem_id.len())), "NEXT hangs off REACT");
        assert_eq!(f.projects[0].0, "alpha");
    }

    #[test]
    fn forest_dedupes_similar_to_and_skips_superseded() {
        let (_d, path) = fixture();
        let conn = Connection::open(&path).unwrap();
        // a1<->a2 mutual (both directions stored, same as a real mutual top-k
        // pair) must draw once. old<->a1 touches a superseded memory and must
        // be dropped entirely, same as every other edge type here.
        crate::similar::insert_similar_link(&conn, "s1", "a1", "a2", 0.9).unwrap();
        crate::similar::insert_similar_link(&conn, "s2", "a2", "a1", 0.9).unwrap();
        crate::similar::insert_similar_link(&conn, "s3", "old", "a1", 0.8).unwrap();
        let f = build_forest(&conn, false).unwrap();
        assert_eq!(f.similar.len(), 1, "mutual pair drawn once, superseded pair dropped");
        let a1 = f.mem_id.iter().position(|m| m == "a1").unwrap();
        let a2 = f.mem_id.iter().position(|m| m == "a2").unwrap();
        assert_eq!(f.similar[0], (a1.min(a2), a1.max(a2)));
    }

    #[test]
    fn layout_is_deterministic_and_complete() {
        let (_d, path) = fixture();
        let conn = Connection::open(&path).unwrap();
        let f = build_forest(&conn, false).unwrap();
        let (a, fam) = layout(&f, &Params::default(), None);
        let (b, _) = layout(&f, &Params::default(), None);
        assert_eq!(a, b);
        assert_eq!(a.len(), f.n());
        assert!(fam >= 2, "the free memory without an embedding is its own family");
        assert!(a.iter().all(|v| v.iter().all(|c| c.is_finite())));
    }

    #[test]
    fn rebuild_then_read_places_everything_and_new_memories_provisionally() {
        let (_d, path) = fixture();
        let mut conn = Connection::open(&path).unwrap();
        assert_eq!(read(&conn).unwrap()["meta"]["needs_build"], true);
        let run = rebuild(&mut conn).unwrap();
        let a = read(&conn).unwrap();
        assert_eq!(a["meta"]["run_id"], run);
        assert_eq!(a["meta"]["unplaced"], 0);
        assert_eq!(a["points"]["id"].as_array().unwrap().len(), 8); // 6 memories + 2 hubs
        assert_eq!(a["points"]["xyz"].as_array().unwrap().len(), 24);
        assert_eq!(a["meta"]["superseded"], 1);

        // A memory saved after the layout appears at once, next to its hub.
        conn.execute("INSERT INTO memories(id, content, type, project, timestamp, source) VALUES('new', 'n', '\"fact\"', 'alpha', '2026-10-20T00:00:00Z', 'x')", []).unwrap();
        conn.execute("INSERT INTO edges(id, src_memory_id, dst_entity_id, created_at) VALUES('new-react', 'new', 'react', 't')", []).unwrap();
        let b = read(&conn).unwrap();
        assert_eq!(b["meta"]["unplaced"], 1);
        let ids: Vec<&str> = b["points"]["id"].as_array().unwrap().iter().map(|v| v.as_str().unwrap()).collect();
        let xyz = b["points"]["xyz"].as_array().unwrap();
        let at = |i: usize| (0..3).map(|k| xyz[i * 3 + k].as_f64().unwrap()).collect::<Vec<_>>();
        let (new, react) = (ids.iter().position(|i| *i == "new").unwrap(), ids.iter().position(|i| *i == "react").unwrap());
        let d: f64 = at(new).iter().zip(at(react)).map(|(p, q)| (p - q).powi(2)).sum::<f64>().sqrt();
        assert!(d < 6.0, "provisional memory sits by its hub (distance {d})");
    }

    #[test]
    fn rebuild_keeps_familiar_regions_in_place() {
        let (_d, path) = fixture();
        let mut conn = Connection::open(&path).unwrap();
        rebuild(&mut conn).unwrap();
        let first = stored_positions(&conn, &current_run(&conn).unwrap().unwrap().0).unwrap();
        // New data arrives: one more memory on react, one free memory elsewhere.
        conn.execute("INSERT INTO memories(id, content, type, project, timestamp, source) VALUES('n1', 'n', '\"fact\"', 'alpha', '2026-10-21T00:00:00Z', 'x')", []).unwrap();
        conn.execute("INSERT INTO edges(id, src_memory_id, dst_entity_id, created_at) VALUES('n1-react', 'n1', 'react', 't')", []).unwrap();
        conn.execute("INSERT INTO memories(id, content, type, project, timestamp, source) VALUES('n2', 'm', '\"fact\"', 'beta', '2026-10-22T00:00:00Z', 'x')", []).unwrap();
        rebuild(&mut conn).unwrap();
        let second = stored_positions(&conn, &current_run(&conn).unwrap().unwrap().0).unwrap();
        let mut moved: Vec<f64> = first
            .iter()
            .map(|(k, a)| {
                let b = second[k];
                ((a[0] - b[0]).powi(2) + (a[1] - b[1]).powi(2) + (a[2] - b[2]).powi(2)).sqrt()
            })
            .collect();
        moved.sort_by(f64::total_cmp);
        let median = moved[moved.len() / 2];
        assert!(median < 1.5, "existing points stay put (median move {median:.2}, all: {moved:?})");
        assert_eq!(second.len(), first.len() + 2);
    }

    #[test]
    fn counts_memories_saved_since_the_layout() {
        let (_d, path) = fixture();
        let mut conn = Connection::open(&path).unwrap();
        assert_eq!(new_since_layout(&conn).unwrap(), None, "never built");
        rebuild(&mut conn).unwrap();
        assert_eq!(new_since_layout(&conn).unwrap(), Some(0));
        conn.execute("INSERT INTO memories(id, content, type, project, timestamp, source) VALUES('later', 'n', '\"fact\"', 'alpha', '2999-01-01T00:00:00Z', 'x')", []).unwrap();
        conn.execute("INSERT INTO memories(id, content, type, project, timestamp, source, superseded_by) VALUES('gone', 'n', '\"fact\"', 'alpha', '2999-01-02T00:00:00+00:00', 'x', 'later')", []).unwrap();
        assert_eq!(new_since_layout(&conn).unwrap(), Some(1), "superseded ones don't count");
    }

    #[test]
    fn keeps_two_finished_layouts() {
        let (_d, path) = fixture();
        let mut conn = Connection::open(&path).unwrap();
        for _ in 0..3 {
            rebuild(&mut conn).unwrap();
        }
        let runs: i64 = conn.query_row("SELECT COUNT(*) FROM memory_atlas_runs WHERE status='done'", [], |r| r.get(0)).unwrap();
        assert_eq!(runs, 2);
        assert_eq!(status(&conn).unwrap()["status"], "done");
    }
}
