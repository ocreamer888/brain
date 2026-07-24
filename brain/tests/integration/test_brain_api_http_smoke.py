"""
HTTP integration smoke — exercises brain_api over real TCP.

Gate: set BRAIN_RUN_INTEGRATION=1 and have brain_api running on BRAIN_API_URL
(default http://127.0.0.1:8787) before running.

Run:
    BRAIN_RUN_INTEGRATION=1 python3 -m pytest brain/tests/integration/test_brain_api_http_smoke.py -v

Uses urllib.request to match production api_client.py behaviour exactly
(same URL resolution, same x-api-key header, same JSON encode/decode path).
"""

import json
import os
import time
import urllib.error
import urllib.request

import pytest

pytestmark = pytest.mark.integration

_INTEGRATION_ENVS = {"1", "true", "yes", "on"}


def _should_run() -> bool:
    return os.environ.get("BRAIN_RUN_INTEGRATION", "").strip().lower() in _INTEGRATION_ENVS


def _base() -> str:
    return os.environ.get("BRAIN_API_URL", "http://127.0.0.1:8787").rstrip("/")


def _headers() -> dict:
    h = {"content-type": "application/json"}
    key = os.environ.get("BRAIN_API_KEY", "").strip()
    if key:
        h["x-api-key"] = key
    return h


def _get(path: str) -> dict:
    req = urllib.request.Request(_base() + path, headers=_headers(), method="GET")
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode())


def _post(path: str, payload: dict) -> dict:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(_base() + path, data=data, headers=_headers(), method="POST")
    with urllib.request.urlopen(req, timeout=15) as r:
        raw = r.read().decode()
        return json.loads(raw) if raw else {}


def test_brain_api_health_save_search_roundtrip():
    if not _should_run():
        pytest.skip("set BRAIN_RUN_INTEGRATION=1 and start brain_api on BRAIN_API_URL")

    # 1. Health
    health = _get("/health")
    assert health.get("status") == "ok", f"unexpected health response: {health}"

    # 2. Save unique sentinel
    sentinel = f"smoke-test-sentinel-{int(time.time() * 1000)}"
    save_resp = _post("/save", {
        "content": sentinel,
        "memory_type": "conversation",
        "tags": ["smoke"],
        "project": "integration-test",
    })
    assert "id" in save_resp, f"save did not return id: {save_resp}"
    mem_id = save_resp["id"]
    assert mem_id, "save returned empty id"

    # 3. Search — the sentinel we just saved must appear in results
    search_resp = _post("/search", {"query": sentinel, "n": 5})
    results = search_resp.get("results", [])
    assert results, "search returned no results after save"
    contents = [r.get("content", "") for r in results]
    assert any(sentinel in c for c in contents), (
        f"sentinel not found in search results.\n"
        f"  sentinel: {sentinel!r}\n"
        f"  returned: {contents}"
    )
