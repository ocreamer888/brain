#!/usr/bin/env python3
"""Save memory to brain API.
Usage: memory("user", content="...")
"""
import json
import sys
import urllib.request

API_URL = "http://127.0.0.1:8787/save"

def save_memory(content, memory_type="conversation", project="", tags="", title=""):
    data = {
        "content": content,
        "memory_type": memory_type,
        "project": project if project else "general",
        "tags": [t for t in tags.split(",") if t.strip()] if tags else [],
        "title": title,
    }
    req = urllib.request.Request(
        API_URL,
        data=json.dumps(data).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode())

if __name__ == "__main__":
    if len(sys.argv) > 2:
        target = sys.argv[1]
        content = sys.argv[2]
        result = save_memory(
            content=content,
            memory_type="conversation" if target == "memory" else "fact",
        )
        print(json.dumps(result, indent=2))
    else:
        print("Usage: python save_memory.py <target> <content>")
