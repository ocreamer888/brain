"""
MCP stdio integration smoke — spawns brain.mcp.server as subprocess and
completes the MCP initialize + tools/list handshake.

Backend strategy: BRAIN_BACKEND=api pointing at a dummy URL.
Tools are only invoked when the client calls them; initialize and list_tools
require no live brain_api connection, so no mock HTTP server is needed.

Gate: set BRAIN_RUN_INTEGRATION=1 before running.

Run:
    BRAIN_RUN_INTEGRATION=1 python3 -m pytest brain/tests/integration/test_mcp_stdio_smoke.py -v
"""

import asyncio
import os
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

_INTEGRATION_ENVS = {"1", "true", "yes", "on"}

# Tools the server registers (brain/mcp/server.py)
_EXPECTED_TOOLS = {
    "search_brain",
    "save_memory_tool",
    "get_context_tool",
    "reflect_tool",
    "get_stats_tool",
    "record_feedback",
}


def _should_run() -> bool:
    return os.environ.get("BRAIN_RUN_INTEGRATION", "").strip().lower() in _INTEGRATION_ENVS


def _ensure_pypi_mcp_on_path() -> None:
    """brain/mcp/ shadows PyPI `mcp` when .../brain is on sys.path; mirror server.py."""
    import site
    import sys

    _brain_dir = str(Path(__file__).resolve().parents[2])
    _sp = next((p for p in site.getsitepackages() if "site-packages" in p), None)
    if not _sp:
        return
    sys.path = [_sp] + [p for p in sys.path if p not in (_brain_dir, _sp)]
    for _k in [k for k in list(sys.modules) if k == "mcp" or k.startswith("mcp.")]:
        del sys.modules[_k]


async def _do_handshake() -> tuple[str, list[str]]:
    """Spawn MCP server subprocess and run initialize + list_tools.

    Returns (server_name, list_of_tool_names).
    """
    _ensure_pypi_mcp_on_path()
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    # Point at a dummy URL — tools won't be invoked during handshake so no
    # live brain_api is required.  Using BRAIN_BACKEND=api avoids Chroma/
    # embedder startup side-effects in the server process.
    env = {
        **os.environ,
        "BRAIN_BACKEND": "api",
        "BRAIN_API_URL": "http://127.0.0.1:9999",  # intentionally offline
        # Ensure the AI workspace root is in PYTHONPATH so brain.* imports resolve
        "PYTHONPATH": str(Path(__file__).parent.parent.parent.parent),
    }

    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "brain.mcp.server"],
        env=env,
    )

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            init_result = await session.initialize()
            tools_result = await session.list_tools()

    server_name = init_result.serverInfo.name
    tool_names = [t.name for t in tools_result.tools]
    return server_name, tool_names


def test_mcp_stdio_initialize_and_list_tools():
    if not _should_run():
        pytest.skip("set BRAIN_RUN_INTEGRATION=1 to run MCP stdio smoke")

    server_name, tool_names = asyncio.run(_do_handshake())

    assert server_name == "brain", f"unexpected server name: {server_name!r}"
    missing = _EXPECTED_TOOLS - set(tool_names)
    assert not missing, (
        f"MCP server missing expected tools: {missing}\n"
        f"  registered tools: {tool_names}"
    )
