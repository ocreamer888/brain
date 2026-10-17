use chrono::Utc;
use serde::{Deserialize, Serialize};
use std::fs;
use std::path::{Path, PathBuf};

use crate::config::default_brain_dir;

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct InstanceRecord {
    pub id: String,
    pub name: String,
    pub slug: String,
    pub db_path: String,
    #[serde(default)]
    pub description: String,
    #[serde(default)]
    pub tags: Vec<String>,
    #[serde(default)]
    pub archived: bool,
    pub created_at: String,
    pub updated_at: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct InstanceRegistry {
    pub active_id: String,
    pub instances: Vec<InstanceRecord>,
}

pub fn registry_path() -> PathBuf {
    default_brain_dir().join("instances.json")
}

pub fn instances_root() -> PathBuf {
    default_brain_dir().join("instances")
}

pub fn slugify(name: &str) -> String {
    let mut out = String::new();
    let mut dash = false;
    for c in name.trim().chars() {
        if c.is_ascii_alphanumeric() {
            out.push(c.to_ascii_lowercase());
            dash = false;
        } else if !dash && !out.is_empty() {
            out.push('-');
            dash = true;
        }
    }
    out.trim_matches('-').to_string()
}

pub fn save_registry(path: &Path, registry: &InstanceRegistry) -> Result<(), String> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(|e| e.to_string())?;
    }
    let tmp = path.with_extension("json.tmp");
    let data = serde_json::to_vec_pretty(registry).map_err(|e| e.to_string())?;
    fs::write(&tmp, data).map_err(|e| e.to_string())?;
    fs::rename(&tmp, path).map_err(|e| e.to_string())
}

/// Resolve `p` to an absolute path, lexically (no symlink resolution), so the
/// registry never persists a leftover relative path. Deliberately avoids
/// `canonicalize()`: on macOS the default temp dir sits behind a `/var` ->
/// `/private/var` symlink, so canonicalizing would silently rewrite a path
/// the caller gave us as absolute into a different (if equivalent) string.
fn absolute_path(p: &Path) -> PathBuf {
    std::path::absolute(p).unwrap_or_else(|_| {
        std::env::current_dir()
            .map(|cwd| cwd.join(p))
            .unwrap_or_else(|_| p.to_path_buf())
    })
}

pub fn ensure_unique_slug(registry: &InstanceRegistry, base: &str) -> String {
    if !registry.instances.iter().any(|i| i.slug == base) {
        return base.to_string();
    }
    let mut n = 2;
    loop {
        let candidate = format!("{}-{}", base, n);
        if !registry.instances.iter().any(|i| i.slug == candidate) {
            return candidate;
        }
        n += 1;
    }
}

pub fn create_instance(
    registry: &mut InstanceRegistry,
    name: &str,
    description: &str,
    tags: Vec<String>,
    instances_root: &Path,
) -> Result<InstanceRecord, String> {
    if name.trim().is_empty() {
        return Err("name required".into());
    }
    let base_slug = slugify(name);
    if base_slug.is_empty() {
        return Err("name required".into());
    }
    let slug = ensure_unique_slug(registry, &base_slug);
    let dir = instances_root.join(&slug);
    fs::create_dir_all(&dir).map_err(|e| e.to_string())?;
    let db_path = absolute_path(&dir.join("brain.db"));
    fs::File::create(&db_path).map_err(|e| e.to_string())?;
    let now = Utc::now().to_rfc3339();
    let record = InstanceRecord {
        id: slug.clone(),
        name: name.trim().to_string(),
        slug,
        db_path: db_path.to_string_lossy().into_owned(),
        description: description.to_string(),
        tags,
        archived: false,
        created_at: now.clone(),
        updated_at: now,
    };
    registry.instances.push(record.clone());
    Ok(record)
}

pub fn get<'a>(registry: &'a InstanceRegistry, id: &str) -> Option<&'a InstanceRecord> {
    registry.instances.iter().find(|i| i.id == id)
}

pub fn patch_instance<'a>(
    registry: &'a mut InstanceRegistry,
    id: &str,
    name: Option<String>,
    description: Option<String>,
    tags: Option<Vec<String>>,
) -> Result<&'a InstanceRecord, String> {
    let record = registry
        .instances
        .iter_mut()
        .find(|i| i.id == id)
        .ok_or_else(|| format!("instance not found: {}", id))?;
    if let Some(name) = name {
        if name.trim().is_empty() {
            return Err("name required".into());
        }
        record.name = name.trim().to_string();
    }
    if let Some(description) = description {
        record.description = description;
    }
    if let Some(tags) = tags {
        record.tags = tags;
    }
    record.updated_at = Utc::now().to_rfc3339();
    Ok(record)
}

pub fn set_archived(
    registry: &mut InstanceRegistry,
    id: &str,
    archived: bool,
    active_id: &str,
) -> Result<(), String> {
    if archived && id == active_id {
        return Err("cannot archive the active instance".into());
    }
    let record = registry
        .instances
        .iter_mut()
        .find(|i| i.id == id)
        .ok_or_else(|| format!("instance not found: {}", id))?;
    record.archived = archived;
    record.updated_at = Utc::now().to_rfc3339();
    Ok(())
}

pub fn delete_instance(
    registry: &mut InstanceRegistry,
    id: &str,
    active_id: &str,
) -> Result<InstanceRecord, String> {
    if id == active_id {
        return Err("cannot delete the active instance".into());
    }
    let idx = registry
        .instances
        .iter()
        .position(|i| i.id == id)
        .ok_or_else(|| format!("instance not found: {}", id))?;
    if !registry.instances[idx].archived {
        return Err("instance must be archived before deletion".into());
    }
    Ok(registry.instances.remove(idx))
}

pub fn set_active<'a>(registry: &'a mut InstanceRegistry, id: &str) -> Result<&'a InstanceRecord, String> {
    let archived = registry
        .instances
        .iter()
        .find(|i| i.id == id)
        .ok_or_else(|| format!("instance not found: {}", id))?
        .archived;
    if archived {
        return Err("cannot activate an archived instance".into());
    }
    registry.active_id = id.to_string();
    get(registry, id).ok_or_else(|| format!("instance not found: {}", id))
}

/// Remove an instance's db file (and its slug-named parent dir) — but only
/// when `db_path` actually lives under `instances_root`. Main and any other
/// instance pointed at a db outside the managed instances directory must
/// never be touched here, even if it gets archived and deleted.
pub fn remove_instance_files(record: &InstanceRecord, instances_root: &Path) -> Result<(), String> {
    let path = Path::new(&record.db_path);
    if !path.starts_with(instances_root) {
        return Ok(());
    }
    if path.is_file() {
        fs::remove_file(path).map_err(|e| e.to_string())?;
    }
    if let Some(dir) = path.parent() {
        if dir.ends_with(&record.slug) {
            let _ = fs::remove_dir(dir);
        }
    }
    Ok(())
}

pub fn load_or_bootstrap(
    registry_path: &Path,
    main_db_path: &Path,
) -> Result<InstanceRegistry, String> {
    if registry_path.is_file() {
        let data = fs::read_to_string(registry_path).map_err(|e| e.to_string())?;
        return serde_json::from_str(&data).map_err(|e| e.to_string());
    }
    let now = Utc::now().to_rfc3339();
    let abs = absolute_path(main_db_path);
    let reg = InstanceRegistry {
        active_id: "main".into(),
        instances: vec![InstanceRecord {
            id: "main".into(),
            name: "Main".into(),
            slug: "main".into(),
            db_path: abs.to_string_lossy().into_owned(),
            description: "Primary personal brain".into(),
            tags: vec!["personal".into()],
            archived: false,
            created_at: now.clone(),
            updated_at: now,
        }],
    };
    save_registry(registry_path, &reg)?;
    Ok(reg)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;
    use tempfile::tempdir;

    #[test]
    fn slugify_basic() {
        assert_eq!(slugify("My Business!"), "my-business");
        assert_eq!(slugify("  Investigation Data  "), "investigation-data");
    }

    #[test]
    fn bootstrap_creates_main_without_moving_db() {
        let dir = tempdir().unwrap();
        let registry = dir.path().join("instances.json");
        let main_db = dir.path().join("existing.db");
        fs::write(&main_db, b"").unwrap();

        let reg = load_or_bootstrap(&registry, &main_db).unwrap();
        assert_eq!(reg.active_id, "main");
        assert_eq!(reg.instances.len(), 1);
        assert_eq!(reg.instances[0].id, "main");
        assert_eq!(reg.instances[0].db_path, main_db.to_string_lossy());
        assert!(registry.is_file());
        assert_eq!(fs::read(&main_db).unwrap(), b""); // untouched
    }

    #[test]
    fn save_and_reload_roundtrip() {
        let dir = tempdir().unwrap();
        let registry = dir.path().join("instances.json");
        let main_db = dir.path().join("brain.db");
        fs::write(&main_db, b"").unwrap();
        let reg = load_or_bootstrap(&registry, &main_db).unwrap();
        save_registry(&registry, &reg).unwrap();
        let again = load_or_bootstrap(&registry, &main_db).unwrap();
        assert_eq!(again.active_id, "main");
        assert_eq!(again.instances[0].name, "Main");
    }

    #[test]
    fn create_instance_makes_db_file_and_unique_slug() {
        let dir = tempdir().unwrap();
        let root = dir.path().join("instances");
        let mut reg = InstanceRegistry {
            active_id: "main".into(),
            instances: vec![],
        };
        // seed main so slug collision is possible
        reg.instances.push(InstanceRecord {
            id: "main".into(),
            name: "Main".into(),
            slug: "main".into(),
            db_path: dir.path().join("main.db").to_string_lossy().into(),
            description: String::new(),
            tags: vec![],
            archived: false,
            created_at: "t".into(),
            updated_at: "t".into(),
        });
        let a = create_instance(&mut reg, "Biz", "work", vec!["work".into()], &root).unwrap();
        assert_eq!(a.id, "biz");
        assert!(Path::new(&a.db_path).is_file());
        let b = create_instance(&mut reg, "Biz", "", vec![], &root).unwrap();
        assert_eq!(b.id, "biz-2");
    }

    #[test]
    fn cannot_archive_or_delete_active() {
        let dir = tempdir().unwrap();
        let mut reg = load_or_bootstrap(&dir.path().join("r.json"), &{
            let p = dir.path().join("m.db");
            fs::write(&p, b"").unwrap();
            p
        })
        .unwrap();
        assert!(set_archived(&mut reg, "main", true, "main").is_err());
        assert!(delete_instance(&mut reg, "main", "main").is_err());
    }

    #[test]
    fn delete_only_when_archived() {
        let dir = tempdir().unwrap();
        let root = dir.path().join("instances");
        let main = dir.path().join("m.db");
        fs::write(&main, b"").unwrap();
        let mut reg = load_or_bootstrap(&dir.path().join("r.json"), &main).unwrap();
        let created = create_instance(&mut reg, "Temp", "", vec![], &root).unwrap();
        assert!(delete_instance(&mut reg, &created.id, "main").is_err());
        set_archived(&mut reg, &created.id, true, "main").unwrap();
        let removed = delete_instance(&mut reg, &created.id, "main").unwrap();
        assert_eq!(removed.id, created.id);
    }

    #[test]
    fn set_active_rejects_archived() {
        let dir = tempdir().unwrap();
        let root = dir.path().join("instances");
        let main = dir.path().join("m.db");
        fs::write(&main, b"").unwrap();
        let mut reg = load_or_bootstrap(&dir.path().join("r.json"), &main).unwrap();
        let created = create_instance(&mut reg, "X", "", vec![], &root).unwrap();
        set_archived(&mut reg, &created.id, true, "main").unwrap();
        assert!(set_active(&mut reg, &created.id).is_err());
    }

    #[test]
    fn patch_renames_display_only() {
        let dir = tempdir().unwrap();
        let main = dir.path().join("m.db");
        fs::write(&main, b"").unwrap();
        let mut reg = load_or_bootstrap(&dir.path().join("r.json"), &main).unwrap();
        let before_path = reg.instances[0].db_path.clone();
        patch_instance(&mut reg, "main", Some(" Casa ".into()), Some("home".into()), None).unwrap();
        assert_eq!(reg.instances[0].name, "Casa");
        assert_eq!(reg.instances[0].id, "main");
        assert_eq!(reg.instances[0].slug, "main");
        assert_eq!(reg.instances[0].db_path, before_path);
    }

    #[test]
    fn remove_instance_files_deletes_db_and_slug_dir() {
        let dir = tempdir().unwrap();
        let root = dir.path().join("instances");
        let main = dir.path().join("m.db");
        fs::write(&main, b"").unwrap();
        let mut reg = load_or_bootstrap(&dir.path().join("r.json"), &main).unwrap();
        let created = create_instance(&mut reg, "Temp", "", vec![], &root).unwrap();
        let db_path = Path::new(&created.db_path).to_path_buf();
        let instance_dir = db_path.parent().unwrap().to_path_buf();
        assert!(db_path.is_file());
        assert!(instance_dir.is_dir());

        set_archived(&mut reg, &created.id, true, "main").unwrap();
        let removed = delete_instance(&mut reg, &created.id, "main").unwrap();
        remove_instance_files(&removed, &root).unwrap();

        assert!(!db_path.exists());
        assert!(!instance_dir.exists());
    }

    #[test]
    fn remove_instance_files_skips_paths_outside_instances_root() {
        let dir = tempdir().unwrap();
        let instances_root = dir.path().join("instances");
        fs::create_dir_all(&instances_root).unwrap();
        // Simulate a "Main"-style db_path that lives outside instances_root —
        // this is the case that must never be deleted (C1).
        let db_path = dir.path().join("main.db");
        fs::write(&db_path, b"").unwrap();
        let record = InstanceRecord {
            id: "main".into(),
            name: "Main".into(),
            slug: "main".into(),
            db_path: db_path.to_string_lossy().into_owned(),
            description: String::new(),
            tags: vec![],
            archived: true,
            created_at: "t".into(),
            updated_at: "t".into(),
        };
        remove_instance_files(&record, &instances_root).unwrap();

        assert!(db_path.exists(), "db file outside instances_root must not be removed");
        assert!(dir.path().is_dir(), "parent dir must be left alone");
    }
}
