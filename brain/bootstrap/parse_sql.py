"""
Parse Cursor's SQLite storage dump and extract conversation history.

Supports two formats:
 - ItemTable with composerData keys (older format / test sample)
 - cursorDiskKV with binary bubbleId keys (actual Cursor format)
"""
import sqlite3
import json
import sys
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import SQL_PATH

# Key prefixes that contain actual chat content in ItemTable
CHAT_KEY_PATTERNS = [
    "composerData",
    "aichat",
    "composer.",
    "workbench.panel.aichat",
]

# Bubble type constants from Cursor
BUBBLE_TYPE_USER = 1
BUBBLE_TYPE_ASSISTANT = 2


def import_sql_to_db(sql_path: str, db_path: str) -> None:
    """Import SQL dump into a SQLite database."""
    print(f"Importing {sql_path} → {db_path}")
    conn = sqlite3.connect(db_path)
    with open(sql_path, 'r', encoding='utf-8', errors='replace') as f:
        sql = f.read()
    conn.executescript(sql)
    conn.close()
    print("Import complete.")


def discover_chat_keys(db_path: str) -> list[str]:
    """Find all keys that likely contain conversation data."""
    conn = sqlite3.connect(db_path)
    chat_keys = []

    # --- ItemTable format (older Cursor / test sample) ---
    try:
        cursor = conn.execute("SELECT DISTINCT key FROM ItemTable")
        all_keys = [row[0] for row in cursor.fetchall()]

        for key in all_keys:
            if any(pattern.lower() in key.lower() for pattern in CHAT_KEY_PATTERNS):
                chat_keys.append(key)

        # Also look for keys whose JSON values contain "bubbles" or "messages"
        for key in all_keys:
            if key in chat_keys:
                continue
            try:
                row = conn.execute("SELECT value FROM ItemTable WHERE key = ?", (key,)).fetchone()
                if row and isinstance(row[0], str):
                    val = row[0][:200]
                    if '"bubbles"' in val or '"messages"' in val or '"role"' in val:
                        chat_keys.append(key)
            except Exception:
                pass
    except sqlite3.OperationalError:
        pass  # ItemTable doesn't exist in this DB

    # --- cursorDiskKV format (actual Cursor data) ---
    try:
        cursor = conn.execute("SELECT DISTINCT key FROM cursorDiskKV")
        all_kv_keys = cursor.fetchall()
        has_bubble_keys = False
        for row in all_kv_keys:
            raw_key = row[0]
            if raw_key is None:
                continue
            try:
                decoded = raw_key.decode('utf-8') if isinstance(raw_key, bytes) else raw_key
                if decoded.startswith('bubbleId:'):
                    has_bubble_keys = True
                    break
            except Exception:
                pass
        if has_bubble_keys:
            chat_keys.append("cursorDiskKV:bubbleId")
    except sqlite3.OperationalError:
        pass  # cursorDiskKV doesn't exist in this DB

    conn.close()
    return list(set(chat_keys))


def extract_messages_from_row(value: str | bytes) -> list[dict]:
    """Parse JSON value and extract message list from ItemTable composerData format."""
    if isinstance(value, bytes):
        return []  # Binary blob — skip

    try:
        data = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return []

    # Try common structures
    if isinstance(data, dict):
        for key in ("bubbles", "messages", "history", "turns"):
            if key in data and isinstance(data[key], list):
                messages = []
                for item in data[key]:
                    if isinstance(item, dict):
                        role = item.get("role") or item.get("type") or "unknown"
                        content = item.get("content") or item.get("text") or item.get("message") or ""
                        if isinstance(content, list):
                            content = " ".join(
                                p.get("text", "") for p in content
                                if isinstance(p, dict) and "text" in p
                            )
                        if content:
                            messages.append({"role": str(role), "content": str(content)})
                if messages:
                    return messages

    return []


def _extract_from_item_table(db_path: str) -> list[dict]:
    """Extract conversations from ItemTable format."""
    chat_keys = []
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.execute("SELECT DISTINCT key FROM ItemTable")
        all_keys = [row[0] for row in cursor.fetchall()]
    except sqlite3.OperationalError:
        conn.close()
        return []

    for key in all_keys:
        if any(pattern.lower() in key.lower() for pattern in CHAT_KEY_PATTERNS):
            chat_keys.append(key)
        else:
            try:
                row = conn.execute("SELECT value FROM ItemTable WHERE key = ?", (key,)).fetchone()
                if row and isinstance(row[0], str):
                    val = row[0][:200]
                    if '"bubbles"' in val or '"messages"' in val or '"role"' in val:
                        chat_keys.append(key)
            except Exception:
                pass

    conversations = []
    for key in chat_keys:
        try:
            row = conn.execute("SELECT value FROM ItemTable WHERE key = ?", (key,)).fetchone()
            if not row:
                continue
            messages = extract_messages_from_row(row[0])
            if len(messages) >= 2:
                conversations.append({
                    "session_id": key,
                    "messages": messages,
                    "message_count": len(messages)
                })
        except Exception as e:
            print(f"[parse] Skipping {key}: {e}", file=sys.stderr)

    conn.close()
    return conversations


def _extract_from_cursor_disk_kv(db_path: str) -> list[dict]:
    """Extract conversations from cursorDiskKV bubbleId format (actual Cursor data)."""
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute("SELECT key, value FROM cursorDiskKV").fetchall()
    except sqlite3.OperationalError:
        conn.close()
        return []

    # Group bubbles by composerId
    composer_bubbles = defaultdict(list)

    for raw_key, raw_val in rows:
        if raw_key is None or raw_val is None:
            continue
        try:
            decoded_key = raw_key.decode('utf-8') if isinstance(raw_key, bytes) else raw_key
            if not decoded_key.startswith('bubbleId:'):
                continue

            parts = decoded_key.split(':')
            if len(parts) < 3:
                continue
            composer_id = parts[1]

            decoded_val = raw_val.decode('utf-8') if isinstance(raw_val, bytes) else raw_val
            data = json.loads(decoded_val)

            bubble_type = data.get('type')
            text = data.get('text', '')
            if not text or bubble_type not in (BUBBLE_TYPE_USER, BUBBLE_TYPE_ASSISTANT):
                continue

            role = 'user' if bubble_type == BUBBLE_TYPE_USER else 'assistant'
            bubble_id = data.get('bubbleId', parts[2] if len(parts) > 2 else '')

            composer_bubbles[composer_id].append({
                'bubble_id': bubble_id,
                'role': role,
                'content': str(text)
            })
        except Exception:
            continue

    conn.close()

    conversations = []
    for composer_id, bubbles in composer_bubbles.items():
        if len(bubbles) < 2:
            continue
        # Sort by bubble_id (UUIDs are time-ordered in Cursor)
        bubbles.sort(key=lambda b: b['bubble_id'])
        messages = [{'role': b['role'], 'content': b['content']} for b in bubbles]
        conversations.append({
            'session_id': f'composerData:{composer_id}',
            'messages': messages,
            'message_count': len(messages)
        })

    print(f"[cursorDiskKV] Extracted {len(conversations)} conversations")
    return conversations


def extract_all_conversations(db_path: str) -> list[dict]:
    """Extract all conversations from the database (both formats)."""
    conversations = _extract_from_item_table(db_path)
    conversations += _extract_from_cursor_disk_kv(db_path)

    print(f"Extracted {len(conversations)} total conversations with ≥2 messages")
    return conversations


if __name__ == "__main__":
    DB_CACHE = Path(__file__).parent / "cursor_brain.db"

    if not DB_CACHE.exists():
        import_sql_to_db(str(SQL_PATH), str(DB_CACHE))

    convos = extract_all_conversations(str(DB_CACHE))

    output_path = Path(__file__).parent / "raw_conversations.jsonl"
    with open(output_path, 'w') as f:
        for convo in convos:
            f.write(json.dumps(convo) + '\n')

    print(f"Saved {len(convos)} conversations to {output_path}")
