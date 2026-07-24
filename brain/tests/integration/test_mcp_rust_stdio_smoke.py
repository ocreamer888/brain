"""
MCP stdio integration smoke — spawns the native `brain_mcp` Rust binary and
completes initialize + tools/list (no live brain_api required for list_tools).

Gate: set BRAIN_RUN_INTEGRATION=1 before running.

Run:
    BRAIN_RUN_INTEGRATION=1 python3 -m pytest brain/tests/integration/test_mcp_rust_stdio_smoke.py -v
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

_INTEGRATION_ENVS = {"1", "true", "yes", "on"}

_EXPECTED_TOOLS = {
    "search_index",
    "timeline_tool",
    "get_observations_tool",
}


def _should_run() -> bool:
    return os.environ.get("BRAIN_RUN_INTEGRATION", "").strip().lower() in _INTEGRATION_ENVS


def _rust_dir() -> Path:
    # brain/tests/integration -> brain
    return Path(__file__).resolve().parents[2] / "rust"


async def _handshake_tool_names() -> list[str]:
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    rust_dir = _rust_dir()
    cargo = os.environ.get("CARGO", "cargo")

    env = {
        **os.environ,
        "BRAIN_API_URL": "http://127.0.0.1:59999",
    }

    # Match `.mcp.json`: `cargo run --bin brain_mcp` from `brain/rust` so we do not
    # depend on `CARGO_TARGET_DIR` / workspace-local `target/debug/brain_mcp`.
    params = StdioServerParameters(
        command=cargo,
        args=["run", "--quiet", "--bin", "brain_mcp"],
        cwd=str(rust_dir),
        env=env,
    )

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools_result = await session.list_tools()

    return [t.name for t in tools_result.tools]


def test_rust_mcp_stdio_initialize_and_list_tools():
    if not _should_run():
        pytest.skip("set BRAIN_RUN_INTEGRATION=1 to run MCP rust stdio smoke")

    names = asyncio.run(_handshake_tool_names())
    assert set(names) == _EXPECTED_TOOLS
