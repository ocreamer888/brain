"""
End-to-end parity smoke against a live `brain_api` (Rust): privacy strip,
search_index, get_observations, timeline, and SSE save notifications.

Gate: set BRAIN_RUN_INTEGRATION=1 before running.

Run:
    BRAIN_RUN_INTEGRATION=1 python3 -m pytest brain/tests/integration/test_claude_mem_parity.py -v
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

_INTEGRATION_ENVS = {"1", "true", "yes", "on"}


def _should_run() -> bool:
    return os.environ.get("BRAIN_RUN_INTEGRATION", "").strip().lower() in _INTEGRATION_ENVS


def _rust_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "rust"


def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    _, port = s.getsockname()
    s.close()
    return int(port)


def _wait_health(base: str, timeout_s: float = 20.0) -> None:
    url = f"{base.rstrip('/')}/health"
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                if r.status == 200:
                    return
        except (urllib.error.URLError, OSError):
            pass
        time.sleep(0.05)
    raise AssertionError("brain_api did not become healthy in time")


def _post_json(base: str, path: str, payload: dict) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{base.rstrip('/')}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def _spawn_brain_api(db_path: Path, port: int) -> subprocess.Popen:
    rust = _rust_dir()
    env = os.environ.copy()
    env.update(
        {
            "BRAIN_DB_PATH": str(db_path),
            "BRAIN_EMBEDDER": "mock",
            "BRAIN_API_BIND": f"127.0.0.1:{port}",
            "BRAIN_API_KEY": "",
            "BRAIN_API_AUTH_REQUIRED": "0",
        }
    )
    return subprocess.Popen(
        ["cargo", "run", "--quiet", "--bin", "brain_api"],
        cwd=str(rust),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def test_claude_mem_parity_http_flow():
    if not _should_run():
        pytest.skip("set BRAIN_RUN_INTEGRATION=1 to run brain_api parity smoke")

    port = _free_port()
    base = f"http://127.0.0.1:{port}"
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "parity.db"
        proc = _spawn_brain_api(db, port)
        try:
            _wait_health(base)

            # 1–2: save with <private>; stored content must strip the block
            marker = "PARITY_VISIBLE_AAA"
            secret = "PARITY_SECRET_SHOULD_NOT_PERSIST"
            save = _post_json(
                base,
                "/save",
                {
                    "content": f"{marker} <private>{secret}</private> tail",
                    "memory_type": "decision",
                    "project": "general",
                },
            )
            mid = save["id"]
            obs = _post_json(base, "/v1/get_observations", {"ids": [mid]})
            stored = obs["results"][0]["content"]
            assert secret not in stored
            assert "<private>" not in stored.lower()
            assert marker in stored

            # 3: search_index returns compact rows
            idx = _post_json(
                base,
                "/v1/search_index",
                {"query": marker, "n": 10},
            )
            rows = idx["results"]
            assert any(r["id"] == mid for r in rows)
            top = next(r for r in rows if r["id"] == mid)
            for k in ("id", "snippet", "memory_type", "project", "timestamp", "distance"):
                assert k in top
            assert len(top["snippet"]) <= 130

            # 4: full content via get_observations (already checked strip + marker)

            # 5: timeline around middle of three saves (distinct timestamps)
            ids = []
            for i, body in enumerate(["TL_FIRST", "TL_ANCHOR", "TL_LAST"]):
                if i:
                    time.sleep(0.06)
                ids.append(
                    _post_json(
                        base,
                        "/save",
                        {
                            "content": body,
                            "memory_type": "pattern",
                            "project": "timeline_test",
                        },
                    )["id"]
                )
            anchor = ids[1]
            tl = _post_json(
                base,
                "/v1/timeline",
                {"anchor_id": anchor, "before": 2, "after": 2},
            )
            contents = [r["content"] for r in tl["results"]]
            assert "TL_FIRST" in contents and "TL_ANCHOR" in contents and "TL_LAST" in contents

            # 6: SSE receives an event after a new save
            sse_marker = "SSE_PARITY_EVENT_MARKER"
            events: list[dict] = []
            stop = threading.Event()

            def _read_sse() -> None:
                req = urllib.request.Request(f"{base}/v1/stream")
                try:
                    with urllib.request.urlopen(req, timeout=15) as r:
                        while not stop.is_set():
                            raw = r.readline()
                            if not raw:
                                break
                            line = raw.decode("utf-8", errors="replace").strip()
                            if line.startswith("data:"):
                                try:
                                    events.append(json.loads(line[5:].strip()))
                                except json.JSONDecodeError:
                                    pass
                except (urllib.error.URLError, OSError, TimeoutError):
                    pass

            reader = threading.Thread(target=_read_sse, daemon=True)
            reader.start()
            time.sleep(0.35)
            _post_json(
                base,
                "/save",
                {
                    "content": sse_marker,
                    "memory_type": "solution",
                    "project": "sse_test",
                },
            )
            deadline = time.time() + 8.0
            while time.time() < deadline:
                if any(sse_marker in e.get("content_snippet", "") for e in events):
                    break
                time.sleep(0.05)
            stop.set()
            assert any(sse_marker in e.get("content_snippet", "") for e in events), (
                f"SSE did not deliver save event; got {events!r}"
            )
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
