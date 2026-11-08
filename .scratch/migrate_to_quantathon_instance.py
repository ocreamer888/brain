import glob
import json
import sys

sys.path.insert(0, "brain")
from api_client import save_memory, BrainApiError

path = sorted(glob.glob("brain/bootstrap/junk_scrub_backups/macbook_orphaned_db_full_backup_*.json"))[-1]
rows = [r for r in json.load(open(path)) if r["project"] == "quantathon-lifehub"]
print(f"migrating {len(rows)} rows into the active instance (should be quantathon-lifehub)")

ok = 0
failed = []
for r in rows:
    mtype = (r["type"] or "").strip('"')
    source = (r["source"] or "").strip('"')
    tags = [t for t in (r["tags"] or "").split(",") if t]
    try:
        save_memory(
            content=r["content"],
            memory_type=mtype,
            tags=tags,
            project=r["project"] or "general",
            session_id=r["session_id"] or None,
            source=source or None,
            file_path=r["file_path"] or None,
            title=r["title"] or None,
            timestamp=r["timestamp"] or None,
            parent_id=r["parent_id"] or None,
            event_time=r["event_time"] or None,
            salience=r["salience"] if r["salience"] is not None else None,
            extracted_by=r["derived_from"] or None,
            auto_entities=False,
        )
        ok += 1
    except BrainApiError as e:
        failed.append((r["id"], str(e)))

print(f"saved={ok} failed={len(failed)}")
for fid, err in failed[:10]:
    print(f"  FAIL {fid}: {err}")
