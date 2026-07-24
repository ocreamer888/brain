from __future__ import annotations

import brain.api_client as api_client


def test_save_then_search_immediate_visibility(monkeypatch):
    saved: list[dict] = []

    def fake_request(method: str, path: str, payload: dict | None = None) -> dict:
        if method == "POST" and path == "/save":
            assert payload is not None
            saved.append(payload)
            return {"id": f"id-{len(saved)}"}
        if method == "POST" and path == "/search":
            query = (payload or {}).get("query", "")
            hits = [
                {
                    "id": f"id-{i+1}",
                    "content": p["content"],
                    "metadata": {
                        "type": p.get("memory_type", "conversation"),
                        "project": p.get("project", "general"),
                        "source": p.get("source", "claude_code_session"),
                    },
                    "distance": 0.0,
                }
                for i, p in enumerate(saved)
                if query.lower() in p.get("content", "").lower()
            ]
            return {"results": hits}
        raise AssertionError(f"unexpected call: {method} {path}")

    monkeypatch.setattr(api_client, "_request", fake_request)

    mem_id = api_client.save_memory(
        content="realtime-memory-smoke-123",
        memory_type="solution",
        tags=["smoke"],
        project="AI",
        source="claude_code_session",
    )
    assert mem_id == "id-1"

    results = api_client.search("realtime-memory-smoke-123", n=5, project="AI")
    assert results
    assert results[0]["content"] == "realtime-memory-smoke-123"
