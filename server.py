#!/usr/bin/env python3
"""
hermes-mcp-server — Full Hermes Agent control via MCP protocol.

Usage:
    python3 server.py                    # stdio mode (default)
    python3 server.py --transport http   # HTTP/SSE mode
    python3 server.py --port 9221        # custom port

MCP client config (e.g. claude_desktop_config.json):
{
    "mcpServers": {
        "hermes-agent": {
            "command": "python3",
            "args": ["~/.hermes/tmp/hermes-mcp-server/server.py"]
        }
    }
}
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    sys.exit("Error: 'mcp' package required. Install: pip install mcp")

try:
    import websockets
except ImportError:
    sys.exit("Error: 'websockets' package required. Install: pip install websockets")

from ws_bridge import WSBridge, ReadCursor
from db_reader import DBReader
from tools import (
    register_session_tools,
    register_prompt_tools,
    register_messaging_tools,
    register_approval_tools,
    register_cli_tools,
    register_config_tools,
    register_model_tools,
    register_skill_tools,
)


def create_server(host: str = "127.0.0.1", port: int = 8000, auto_approve: bool = True) -> FastMCP:
    """Create and configure the MCP server with all tools."""
    mcp = FastMCP(
        "hermes-agent",
        instructions=(
            "Full Hermes Agent control. Use these tools to manage sessions, "
            "submit prompts, read messages (all/unread/stream), send messages "
            "to platforms, handle approvals, execute slash commands, configure "
            "settings, manage models, and browse skills."
        ),
        host=host,
        port=port,
    )

    bridge = WSBridge(auto_approve=auto_approve)
    db = DBReader()
    cursor = ReadCursor()

    # Register all tool groups
    register_session_tools(mcp, bridge)
    register_prompt_tools(mcp, bridge)
    register_messaging_tools(mcp, bridge, db, cursor)
    register_approval_tools(mcp, bridge)
    register_cli_tools(mcp, bridge)
    register_config_tools(mcp, bridge)
    register_model_tools(mcp, bridge)
    register_skill_tools(mcp, db)

    # Store refs for lifecycle management
    mcp._bridge = bridge
    mcp._db = db
    mcp._cursor = cursor

    return mcp


def main():
    parser = argparse.ArgumentParser(description="Hermes Agent MCP Server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "http"],
        default="stdio",
        help="Transport mode (default: stdio)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=9221,
        help="Port for HTTP transport (default: 9221)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable debug logging",
    )
    parser.add_argument(
        "--auto-approve",
        choices=["on", "off"],
        default="on",
        help="Auto-approve exec requests (default: on)",
    )
    args = parser.parse_args()

    # Logging
    level = logging.DEBUG if args.verbose else logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(name)s %(levelname)s: %(message)s",
        stream=sys.stderr,
    )

    server = create_server(
        host="0.0.0.0" if args.transport == "http" else "127.0.0.1",
        port=args.port,
        auto_approve=args.auto_approve == "on",
    )

    async def _run():
        # Start WS bridge
        await server._bridge.start()
        try:
            if args.transport == "stdio":
                await server.run_stdio_async()
            else:
                await server.run_streamable_http_async()
        finally:
            await server._bridge.stop()

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
