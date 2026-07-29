#!/bin/bash
# Package-root MCP entry — delegates to the portable launcher.
exec "$(cd "$(dirname "$0")" && pwd)/mcp/run_server.sh"
