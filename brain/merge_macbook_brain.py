"""
One-shot merge: pull memories from MacBook brain (via tunnel on :18787)
that are missing from Mac Studio brain (:8787), then save them to Mac Studio.

Run from AI/ dir:
    python3 brain/tools/merge_macbook_brain.py
"""
import json
import sys
import urllib.request
import urllib.error

MACBOOK_URL = "http://127.0.0.1:18787"
STUDIO_URL  = "http://127.0.0.1:8787"
API_KEY     = "local-dev-key"
BATCH_SIZE  = 50


def _get(url: str, path: str) -> dict:
    req = urllib.request.Request(
        f"{url}{path}",
        headers={"x-api-key": API_KEY},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def _post(url: str, path: str, payload: dict) -> dict:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{url}{path}",
        data=data,
        method="POST",
        headers={"x-api-key": API_KEY, "content-type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def fetch_all(url: str, list_route: str = "/memories") -> list[dict]:
    items = []
    offset = 0
    limit = 5000
    while True:
        resp = _get(url, f"{list_route}?limit={limit}&offset={offset}")
        batch = resp.get("items", [])
        items.extend(batch)
        print(f"  fetched {len(items)}/{resp['total']} from {url}", end="\r")
        if len(items) >= resp["total"] or not batch:
            break
        offset += limit
    print()
    return items


def main():
    print("Fetching MacBook memories (tunnel :18787)...")
    mb_items = fetch_all(MACBOOK_URL, list_route="/list")
    print(f"MacBook total: {len(mb_items)}")

    print("Fetching Mac Studio memory IDs (:8787)...")
    st_items = fetch_all(STUDIO_URL, list_route="/list")
    studio_ids = {m["id"] for m in st_items}
    print(f"Mac Studio total: {len(st_items)}")

    missing = [m for m in mb_items if m["id"] not in studio_ids]
    print(f"Missing on Mac Studio: {len(missing)}")

    if not missing:
        print("Nothing to merge. Done.")
        return

    # Save in batches via /save-batch
    saved = 0
    failed = 0
    for i in range(0, len(missing), BATCH_SIZE):
        batch = missing[i : i + BATCH_SIZE]
        payload = {
            "items": [
                {
                    "content":     m["content"],
                    "memory_type": m["memory_type"],
                    "project":     m.get("project", "general"),
                    "source":      m.get("source", "merge_macbook"),
                    "session_id":  m.get("session_id") or None,
                    "timestamp":   m.get("timestamp") or None,
                }
                for m in batch
            ]
        }
        try:
            result = _post(STUDIO_URL, "/save-batch", payload)
            saved  += result.get("accepted", 0)
            failed += result.get("failed", 0)
            print(f"  batch {i//BATCH_SIZE + 1}: +{result.get('accepted',0)} saved, {result.get('failed',0)} failed")
        except Exception as e:
            print(f"  batch {i//BATCH_SIZE + 1} ERROR: {e}", file=sys.stderr)
            failed += len(batch)

    print(f"\nMerge complete. Saved: {saved} | Failed: {failed}")

    # Verify
    after = _get(STUDIO_URL, "/stats")
    total = sum(after.get("by_type", {}).values())
    print(f"Mac Studio total after merge: {total}")


if __name__ == "__main__":
    main()
